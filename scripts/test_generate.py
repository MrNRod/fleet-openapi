import importlib.util
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
module = importlib.util.spec_from_file_location('generator', ROOT / 'scripts/generate.py')
if module is None or module.loader is None:
    raise ImportError('Unable to load scripts/generate.py')
g = importlib.util.module_from_spec(module)
module.loader.exec_module(g)

FIXTURE = '''## Hosts
### Update host
`PATCH /api/v1/fleet/hosts/:id`
#### Parameters
| Name | Type | In | Description |
| id | integer | path | **Required**. Host ID. |
| query | string | query | Search filter. |
| name | string | body | **Required**. Name. |
#### Example
##### Request body
```json
{"name": "https://example.test/a//b", // keep URL, remove comment
 "enabled": true,}
```
##### Default response
`Status: 200`
```json
{"host": {"id": 1}}
```
'''


class GeneratorTests(unittest.TestCase):
    def test_examples_params_auth_and_yaml(self):
        collection = g.build(FIXTURE, 'test', 'test')
        report = collection['extensions']['fleet']
        item = yaml.safe_load(g.dump(collection))['items'][0]['items'][0]
        self.assertEqual(report['operation_count'], 1)
        self.assertEqual(item['http']['auth'], 'inherit')
        self.assertTrue(item['http']['params'][1]['disabled'])
        self.assertEqual(item['http']['params'][0]['type'], 'path')
        self.assertEqual(json.loads(item['http']['body']['data'])['name'], 'https://example.test/a//b')
        self.assertEqual(item['examples'][0]['response']['status'], 200)

    def test_response_status_labels_are_stable(self):
        # These phrases changed between Python 3.12 and 3.14. Exercise the
        # complete parse/build/YAML path, including an unknown status code.
        expected = {200: 'OK', 413: 'Content Too Large', 414: 'URI Too Long',
                    416: 'Range Not Satisfiable', 422: 'Unprocessable Content', 599: ''}
        for status, phrase in expected.items():
            with self.subTest(status=status):
                text = FIXTURE.replace('Status: 200', f'Status: {status}')
                collection = yaml.safe_load(g.dump(g.build(text, 'test', 'test')))
                response = collection['items'][0]['items'][0]['examples'][0]['response']
                self.assertEqual(response['status'], status)
                self.assertEqual(response['statusText'], phrase)

    def test_public_routes_do_not_inherit_auth(self):
        for route in ['/api/v1/fleet/login', '/api/v1/fleet/device/:token']:
            endpoint = g.parse_markdown('## Auth\n### Public\n`POST ' + route + '`\n')[0][0]
            self.assertNotIn('auth', g.request_yaml(endpoint, 1)['http'])

    def test_file_upload_and_optional_fields(self):
        text = '''## Uploads
### Upload
`POST /api/v1/fleet/scripts`
#### Parameters
| Name | Type | In | Description |
| script | file | body | **Required**. Script file. |
| team_id | integer | body | Optional. |
'''
        endpoint = g.parse_markdown(text)[0][0]
        body = g.request_yaml(endpoint, 1)['http']['body']
        self.assertEqual(body['type'], 'multipart-form')
        self.assertEqual(body['data'][0]['value'], [])
        self.assertFalse(body['data'][0]['disabled'])
        self.assertTrue(body['data'][1]['disabled'])

    def test_nested_body_skeleton_and_scim_urn(self):
        params = g.params_from('''| users | array | body | Users |
| &nbsp;&nbsp;id | integer | body | ID |
| name.givenName | string | body | Given name |
| urn:ietf:params:scim:schemas:extension:enterprise:2.0:User.department | string | body | Department |''')
        body = g.skeleton(params)
        self.assertEqual(body['users'], [{'id': 0}])
        self.assertEqual(body['name'], {'givenName': ''})
        self.assertEqual(body['urn:ietf:params:scim:schemas:extension:enterprise:2.0:User'], {'department': ''})

    def test_inline_method_and_path_alias(self):
        text = '''## Teams
### Add users
`PATCH /api/v1/fleet/teams/:id/users`
This also applies to `DELETE /api/v1/fleet/teams/:id/users`.
| team_id | integer | path | **Required**. ID |
'''
        endpoints, _, notes = g.parse_markdown(text)
        self.assertEqual([e['method'] for e in endpoints], ['PATCH', 'DELETE'])
        self.assertEqual(endpoints[0]['params'][0]['name'], 'id')
        self.assertTrue(notes)

    def test_ignores_headings_inside_fences(self):
        text = FIXTURE + '\n```sh\n### Not an endpoint\n```\n'
        self.assertEqual(len(g.parse_markdown(text)[0]), 1)

    def test_definition_is_not_example_or_deprecation(self):
        text = '''## Test
### Item
> Old `GET /api/v1/fleet/old` is deprecated.
`GET /api/v1/fleet/items/:id`
#### Example
`GET /api/v1/fleet/items/123`
'''
        self.assertEqual(g.parse_markdown(text)[0][0]['path'], '/api/v1/fleet/items/:id')

    def test_fail_on_duplicate_invalid_json_or_empty_document(self):
        for text in [FIXTURE + FIXTURE, FIXTURE.replace('"enabled": true,', '"enabled": ...,'), '# No endpoints']:
            with self.assertRaises(ValueError):
                g.parse_markdown(text)

    def test_deterministic_generation(self):
        self.assertEqual(g.build(FIXTURE, 'test', 'test'), g.build(FIXTURE, 'test', 'test'))

    def test_bundle_includes_environment_and_metadata(self):
        collection = yaml.safe_load(g.dump(g.build(FIXTURE, 'test', 'test')))
        self.assertTrue(collection['bundled'])
        self.assertTrue(collection['config']['environments'][0]['variables'][1]['secret'])
        self.assertEqual(collection['extensions']['fleet']['source_sha256'], g.sha(FIXTURE.encode()))
        self.assertEqual(collection['items'][0]['request']['auth'], 'inherit')
        self.assertIn('https://creativecommons.org/licenses/by-sa/4.0/', collection['docs']['content'])
        self.assertIn('Fleet Device Management Inc', collection['docs']['content'])
        self.assertIn('Changes: converted Markdown', collection['docs']['content'])

    def test_write_and_check(self):
        collection = g.build(FIXTURE, 'test', 'test')
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'collection'
            g.write_collection(output, collection)
            g.write_collection(output, collection, check=True)
            request = output / 'hosts/patch-update-host.yml'
            request.write_text('changed')
            with self.assertRaises(ValueError):
                g.write_collection(output, collection, check=True)
            self.assertEqual(request.read_text(), 'changed')

    def test_native_files_preserve_collection_content(self):
        collection = g.build(FIXTURE, 'test', 'test')
        original = copy.deepcopy(collection)
        files = g.collection_files(collection)
        root = yaml.safe_load(files['opencollection.yml'])
        self.assertFalse(root['bundled'])
        self.assertNotIn('items', root)
        self.assertNotIn('config', root)
        self.assertEqual(root['request'], collection['request'])
        self.assertEqual(root['docs'], collection['docs'])
        self.assertEqual(yaml.safe_load(files['environments/Fleet.yml']), collection['config']['environments'][0])
        folder = collection['items'][0]
        self.assertEqual(yaml.safe_load(files['hosts/folder.yml']), {k: v for k, v in folder.items() if k != 'items'})
        self.assertEqual(yaml.safe_load(files['hosts/patch-update-host.yml']), folder['items'][0])
        self.assertEqual(collection, original)

    def test_bundle_cli_matches_directory_and_check_does_not_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'api.md'
            source.write_text(FIXTURE)
            directory = root / 'collection'
            bundle = root / 'fleet.opencollection.yml'
            command = [sys.executable, str(ROOT / 'scripts/generate.py'),
                       '--input', str(source), '--version', 'test']
            subprocess.run(command + ['--output', str(directory)], check=True, capture_output=True)
            before = {p.relative_to(directory): p.read_bytes() for p in directory.rglob('*.yml')}
            subprocess.run(command + ['--bundle', str(bundle)], check=True, capture_output=True)
            collection = yaml.safe_load(bundle.read_text())
            self.assertEqual(collection, g.build(FIXTURE, 'test', 'test'))
            self.assertEqual(before, {Path(name): content for name, content in g.collection_files(collection).items()})
            subprocess.run(command + ['--bundle', str(bundle), '--check'], check=True, capture_output=True)
            bundle.write_text('changed')
            result = subprocess.run(command + ['--bundle', str(bundle), '--check'], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(bundle.read_text(), 'changed')
            self.assertEqual(before, {p.relative_to(directory): p.read_bytes() for p in directory.rglob('*.yml')})

    def test_removed_and_renamed_requests_preserve_local_files(self):
        collection = g.build(FIXTURE, 'test', 'test')
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            g.write_collection(output, collection)
            local = output / 'environments/Local.yml'
            local.write_text('name: Local\nvariables: []\n')
            custom = output / 'hosts/custom.yml'
            custom.write_text('personal request')
            updated = copy.deepcopy(collection)
            updated['items'][0]['info']['name'] = 'Devices'
            g.write_collection(output, updated)
            self.assertFalse((output / 'hosts/patch-update-host.yml').exists())
            self.assertFalse((output / 'hosts/folder.yml').exists())
            self.assertTrue((output / 'devices/patch-update-host.yml').is_file())
            self.assertEqual(local.read_text(), 'name: Local\nvariables: []\n')
            self.assertEqual(custom.read_text(), 'personal request')
            g.write_collection(output, updated, check=True)
            updated['items'] = []
            g.write_collection(output, updated)
            self.assertFalse((output / 'devices').exists())

    def test_new_endpoint_does_not_rename_existing_files(self):
        before = g.collection_files(g.build(FIXTURE, 'test', 'test'))
        extra = '## Hosts\n### List hosts\n`GET /api/v1/fleet/hosts`\n'
        after = g.collection_files(g.build(extra + FIXTURE, 'test', 'test'))
        self.assertTrue(before.keys() <= after.keys())

    def test_filename_collisions_and_reserved_directories(self):
        collision = FIXTURE + '\n## Hosts\n### Update host!\n`PATCH /api/v1/fleet/other`\n'
        with self.assertRaisesRegex(ValueError, 'collision'):
            g.collection_files(g.build(collision, 'test', 'test'))
        files = g.collection_files(g.build(FIXTURE.replace('## Hosts', '## Scripts'), 'test', 'test'))
        self.assertIn('scripts-api/folder.yml', files)

    def test_preflight_rejects_unsafe_paths_and_unmanaged_collisions(self):
        collection = g.build(FIXTURE, 'test', 'test')
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'collection'
            g.write_collection(output, collection)
            root_file = output / 'opencollection.yml'
            original = root_file.read_bytes()
            for path in ['../outside.yml', '/outside.yml', 'environments/Local.yml', 'scripts/generate.yml']:
                root = yaml.safe_load(original)
                root['extensions']['fleet']['generated_files'].append(path)
                root_file.write_text(g.dump(root))
                with self.assertRaises(ValueError):
                    g.write_collection(output, collection)
                self.assertEqual(root_file.read_text(), g.dump(root))
            root_file.write_bytes(original)
            updated = copy.deepcopy(collection)
            updated['items'][0]['info']['name'] = 'Devices'
            (output / 'devices').mkdir()
            target = output / 'devices/patch-update-host.yml'
            target.write_text('personal request')
            with self.assertRaisesRegex(ValueError, 'unmanaged'):
                g.write_collection(output, updated)
            self.assertEqual(target.read_text(), 'personal request')
            self.assertEqual(root_file.read_bytes(), original)
            target.unlink()
            (output / 'devices').rmdir()
            (output / 'devices').symlink_to(output / 'hosts', target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                g.write_collection(output, updated)
            self.assertEqual(root_file.read_bytes(), original)

    def test_generated_tree_has_unique_operations_valid_paths_and_json(self):
        collection = yaml.safe_load((ROOT / 'opencollection.yml').read_text())
        self.assertFalse(collection['bundled'])
        seen = set()
        generated = collection['extensions']['fleet']['generated_files']
        self.assertEqual(len(generated), len(set(generated)))
        for relative in generated:
            item = yaml.safe_load((ROOT / relative).read_text())
            if 'http' in item:
                request = item['http']
                key = (request['method'], request['url'])
                self.assertNotIn(key, seen)
                seen.add(key)
                for name in g.re.findall(r':([A-Za-z_][A-Za-z_0-9]*)', request['url']):
                    self.assertTrue(any(p['name'] == name and p['type'] == 'path' for p in request.get('params', [])))
                if request.get('body', {}).get('type') == 'json':
                    json.loads(request['body']['data'])
        self.assertGreater(len(seen), 200)
        self.assertEqual(len(seen), collection['extensions']['fleet']['operation_count'])


if __name__ == '__main__':
    unittest.main()
