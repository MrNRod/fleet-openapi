import importlib.util
import json
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
            output = Path(temp) / 'fleet.yml'
            g.write_collection(output, collection)
            g.write_collection(output, collection, check=True)
            output.write_text('changed')
            with self.assertRaises(ValueError):
                g.write_collection(output, collection, check=True)
            self.assertEqual(output.read_text(), 'changed')

    def test_generated_bundle_has_unique_operations_valid_paths_and_json(self):
        collection = yaml.safe_load((ROOT / 'fleet.bruno.yml').read_text())
        self.assertTrue(collection['bundled'])
        seen = set()
        for folder in collection['items']:
            for item in folder['items']:
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
