#!/usr/bin/env python3
"""Generate native Bruno OpenCollection YAML directly from Fleet Markdown."""
import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = 'docs/REST API/rest-api.md'
DOC_URL = 'https://fleetdm.com/docs/rest-api/rest-api'
METHOD = r'GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS'
ROUTE = re.compile(r'^`(' + METHOD + r')\s+(/[^`\s]+)`\s*$', re.M)
PUBLIC = {'/api/v1/fleet/login', '/api/v1/fleet/forgot_password',
          '/api/v1/fleet/reset_password', '/api/v1/fleet/sso', '/api/v1/fleet/sso/callback'}
PATH_FIXUPS = {('POST', '/scripts/batch/abc-def/cancel'):
               '/api/v1/fleet/scripts/batch/:batch_execution_id/cancel'}


# Fixed labels keep generated YAML identical across Python versions.
# Preserve the Python 3.14 labels used by the original collection.
HTTP_STATUS_PHRASES = {
    100: 'Continue',
    101: 'Switching Protocols',
    102: 'Processing',
    103: 'Early Hints',
    200: 'OK',
    201: 'Created',
    202: 'Accepted',
    203: 'Non-Authoritative Information',
    204: 'No Content',
    205: 'Reset Content',
    206: 'Partial Content',
    207: 'Multi-Status',
    208: 'Already Reported',
    226: 'IM Used',
    300: 'Multiple Choices',
    301: 'Moved Permanently',
    302: 'Found',
    303: 'See Other',
    304: 'Not Modified',
    305: 'Use Proxy',
    307: 'Temporary Redirect',
    308: 'Permanent Redirect',
    400: 'Bad Request',
    401: 'Unauthorized',
    402: 'Payment Required',
    403: 'Forbidden',
    404: 'Not Found',
    405: 'Method Not Allowed',
    406: 'Not Acceptable',
    407: 'Proxy Authentication Required',
    408: 'Request Timeout',
    409: 'Conflict',
    410: 'Gone',
    411: 'Length Required',
    412: 'Precondition Failed',
    413: 'Content Too Large',
    414: 'URI Too Long',
    415: 'Unsupported Media Type',
    416: 'Range Not Satisfiable',
    417: 'Expectation Failed',
    418: "I'm a Teapot",
    421: 'Misdirected Request',
    422: 'Unprocessable Content',
    423: 'Locked',
    424: 'Failed Dependency',
    425: 'Too Early',
    426: 'Upgrade Required',
    428: 'Precondition Required',
    429: 'Too Many Requests',
    431: 'Request Header Fields Too Large',
    451: 'Unavailable For Legal Reasons',
    500: 'Internal Server Error',
    501: 'Not Implemented',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
    504: 'Gateway Timeout',
    505: 'HTTP Version Not Supported',
    506: 'Variant Also Negotiates',
    507: 'Insufficient Storage',
    508: 'Loop Detected',
    510: 'Not Extended',
    511: 'Network Authentication Required',
}


class Dumper(yaml.SafeDumper):
    pass


def string_representer(dumper, value):
    return dumper.represent_scalar('tag:yaml.org,2002:str', value,
                                  style='|' if '\n' in value else None)


Dumper.add_representer(str, string_representer)


def dump(value):
    return yaml.dump(value, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=110)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def slug(value):
    return re.sub(r'[^a-z0-9 _-]', '', value.lower()).replace(' ', '-')


def headings(text, levels):
    """Ignore heading-looking content inside code fences."""
    offset, fence = 0, None
    for line in text.splitlines(keepends=True):
        mark = re.match(r'^\s*(`{3,}|~{3,})', line)
        if mark:
            if fence is None:
                fence = mark[1][0]
            elif mark[1][0] == fence:
                fence = None
        elif fence is None:
            match = re.match(r'^(#{2,6}) ([^\n]+)', line)
            if match and len(match[1]) in levels:
                yield len(match[1]), match[2].strip(), offset, offset + len(line)
        offset += len(line)


def sections(text, levels):
    marks = list(headings(text, levels))
    for i, (level, title, start, end) in enumerate(marks):
        yield level, title, text[end:marks[i + 1][2] if i + 1 < len(marks) else len(text)]


def json_example(text):
    # Fleet examples sometimes contain comments/trailing commas. Preserve strings.
    text = re.sub(r'("(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/)',
                  lambda m: m[0] if m[0].startswith('"') else '', text, flags=re.S)
    text = re.sub(r'("(?:\\.|[^"\\])*"|,\s*(?=[}\]]))',
                  lambda m: m[0] if m[0].startswith('"') else '', text)
    return json.loads(text)


def params_from(text):
    result = []
    for line in text.splitlines():
        if not line.startswith('|'):
            continue
        cells = [x.strip() for x in re.split(r'(?<!\\)\|', line.strip().strip('|'))]
        if len(cells) != 4 or cells[2] not in ('query', 'body', 'json', 'form', 'path', 'url', 'header', 'cookie'):
            continue
        name, typ, loc, desc = cells
        required = bool(re.match(r'\W*required\b', desc, re.I)) and not re.search(r'required\W+(if|when|for)\b', desc, re.I)
        result.append({'name': name.replace('&nbsp;', '').strip('` *'), 'nested': '&nbsp;' in name,
                       'type': typ.strip('` ').lower(), 'in': {'url': 'path', 'json': 'body'}.get(loc, loc),
                       'description': desc, 'required': bool(required)})
    return result


def placeholder(typ):
    return {'integer': 0, 'number': 0, 'float': 0, 'boolean': False, 'bool': False,
            'array': [], 'list': [], 'object': {}, 'objects': {}}.get(typ, '')


def skeleton(params):
    result, last = {}, None
    for param in params:
        name, parent = param['name'], result
        if param['nested'] and last:
            if not isinstance(result.get(last), list) or not result[last]:
                result[last] = [{}]
            parent = result[last][0]
        parts = name.rsplit('.', 1) if name.startswith('urn:') else name.split('.')
        for key in parts[:-1]:
            if isinstance(parent.get(key), list):
                if not parent[key]:
                    parent[key].append({})
                parent = parent[key][0]
            else:
                if not isinstance(parent.get(key), dict):
                    parent[key] = {}
                parent = parent[key]
        parent[parts[-1]] = placeholder(param['type'])
        if not param['nested']:
            last = parts[0]
    return result


def parse_markdown(text):
    endpoints, skipped, warnings, identities = [], [], [], set()
    group = 'General'
    for level, title, body in sections(text, {2, 3}):
        if level == 2:
            group = title
            continue
        pre = re.split(r'^#### Examples?\b', body, maxsplit=1, flags=re.M)[0]
        route = ROUTE.search(pre)
        if not route:
            if re.search(r'`(?:' + METHOD + r') /api/', body) and 'websocket' not in title.lower():
                raise ValueError(f'Unrecognized endpoint definition: {title}')
            skipped.append(title)
            continue
        method, path = route.groups()
        path = PATH_FIXUPS.get((method, path), path.split('?')[0])
        path = re.sub(r'{([^}]+)}', r':\1', path)
        if not path.startswith(('/api/', '/debug/')):
            raise ValueError(f'Unexpected API path: {method} {path}')
        params = params_from(pre)
        # This table labels its two filters as path parameters; the example URL
        # puts query in the query string and the route has only an id segment.
        if path == '/api/v1/fleet/policies/:id/automation_activities':
            for param in params:
                if param['name'] in ('status', 'query') and param['in'] == 'path':
                    param['in'] = 'query'
                    warnings.append(f'{method} {path}: {param["name"]} corrected from path to query')
        paths = re.findall(r':([A-Za-z_][A-Za-z_0-9]*)', path)
        documented_paths = [p for p in params if p['in'] == 'path']
        missing = set(paths) - {p['name'] for p in documented_paths}
        for param in documented_paths:
            if param['name'] not in paths:
                if len(missing) != 1:
                    raise ValueError(f'Ambiguous path parameter in {title}: {param["name"]}')
                replacement = missing.pop()
                warnings.append(f'{method} {path}: path parameter {param["name"]} normalized to {replacement}')
                param['name'] = replacement
        for name in paths:
            if not any(p['in'] == 'path' and p['name'] == name for p in params):
                params.append({'name': name, 'in': 'path', 'type': 'string', 'description': '', 'required': True})
        request_body, responses = None, []
        for _, label, chunk in sections(body, {4, 5, 6}):
            code = re.search(r'```([^\n]*)\n(.*?)\n```', chunk, re.S)
            is_request = 'request body' in label.lower() or label.lower() == 'request data'
            if is_request and code and request_body is None:
                language, raw = code.groups()
                request_body = {'type': language.strip().lower(), 'data': raw}
                if request_body['type'] == 'json':
                    request_body['data'] = json_example(raw)
            elif not is_request:
                status = re.search(r'`(?:Status:\s*)?(\d{3})', chunk)
                if status:
                    response = {'name': label, 'status': int(status[1])}
                    if code:
                        language, raw = code.groups()
                        response['body'] = {'type': 'json' if language.strip() == 'json' else 'text',
                                            'data': json.dumps(json_example(raw), indent=2, ensure_ascii=False)
                                            if language.strip() == 'json' else raw}
                    responses.append(response)
                elif code and 'response' in label.lower():
                    warnings.append(f'{method} {path}: response without status retained in request documentation')
        endpoint = {'group': group, 'title': title, 'method': method, 'path': path, 'params': params,
                    'body': request_body, 'responses': responses, 'docs': body.strip(),
                    'multipart': 'multipart/form-data' in pre or any(p['type'] == 'file' for p in params),
                    'urlencoded': 'application/x-www-form-urlencoded' in pre,
                    'public': path in PUBLIC or path.startswith('/api/v1/fleet/device/') or
                    any(p in pre.lower() for p in ('authentication is not required', 'no authentication required',
                                                   "doesn't require api token authentication"))}
        variants = [endpoint]
        # Some methods are documented inline alongside the primary operation.
        for alt_method, alt_path in re.findall(r'This also applies to `(' + METHOD + r') (/[^`]+)`', pre):
            alt_path = re.sub(r'{([^}]+)}', r':\1', alt_path)
            if alt_path != path:
                raise ValueError(f'Inline alternate route needs review: {alt_path}')
            other = copy.deepcopy(endpoint)
            other.update(method=alt_method, title=title.replace('Add users', 'Remove users')
                         if alt_method == 'DELETE' else f'{title} ({alt_method})')
            variants.append(other)
        for item in variants:
            key = (item['method'], item['path'])
            if key in identities:
                raise ValueError(f'Duplicate operation: {key}')
            identities.add(key)
            endpoints.append(item)
    if not endpoints:
        raise ValueError('No HTTP endpoints found; refusing to replace the collection')
    return endpoints, skipped, warnings


def request_yaml(endpoint, seq):
    http = {'method': endpoint['method'], 'url': '{{baseUrl}}' + endpoint['path']}
    if not endpoint['public']:
        http['auth'] = 'inherit'
    params, headers = [], []
    for param in endpoint['params']:
        loc = param['in']
        if loc in ('path', 'query'):
            entry = {'name': param['name'], 'value': '', 'type': loc}
            if loc == 'query':
                entry['disabled'] = True
            if param['description']:
                entry['description'] = param['description']
            if not any(p['name'] == entry['name'] and p['type'] == loc for p in params):
                params.append(entry)
        elif loc in ('header', 'cookie'):
            headers.append({'name': param['name'] if loc == 'header' else 'Cookie',
                            'value': '' if loc == 'header' else param['name'] + '=',
                            'description': param['description'], 'disabled': not param['required']})
    if params:
        http['params'] = params
    body_params = [p for p in endpoint['params'] if p['in'] in ('body', 'form')]
    example = endpoint['body']
    if endpoint['multipart'] or endpoint['urlencoded']:
        fields = []
        for param in body_params:
            field = {'name': param['name'], 'value': [] if param['type'] == 'file' else '',
                     'description': param['description'], 'disabled': not param['required']}
            if endpoint['multipart']:
                field['type'] = 'file' if param['type'] == 'file' else 'text'
            fields.append(field)
        http['body'] = {'type': 'multipart-form' if endpoint['multipart'] else 'form-urlencoded', 'data': fields}
    elif example and example['type'] != 'json':
        http['body'] = {'type': 'xml' if example['type'] == 'xml' else 'text', 'data': example['data']}
    elif example is not None or body_params:
        value = example['data'] if example is not None else skeleton(body_params)
        http['body'] = {'type': 'json', 'data': json.dumps(value, indent=2, ensure_ascii=False)}
        headers.append({'name': 'Content-Type', 'value': 'application/json'})
    if headers:
        http['headers'] = headers
    result = {'info': {'name': endpoint['title'], 'type': 'http', 'seq': seq}, 'http': http,
              'docs': endpoint['docs'] + '\n\nReference: ' + DOC_URL + '#' + slug(endpoint['title'])}
    examples = []
    for response in endpoint['responses']:
        status = response['status']
        res = {'status': status, 'statusText': HTTP_STATUS_PHRASES.get(status, '')}
        if 'body' in response:
            res['body'] = response['body']
            if response['body']['type'] == 'json':
                res['headers'] = [{'name': 'Content-Type', 'value': 'application/json'}]
        examples.append({'name': f'{status} {response["name"]}', 'request':
                         {k: copy.deepcopy(v) for k, v in http.items() if k != 'auth'}, 'response': res})
    if examples:
        result['examples'] = examples
    return result


def build(text, version, source_ref):
    endpoints, skipped, warnings = parse_markdown(text)
    groups = {}
    for endpoint in endpoints:
        group = groups.setdefault(endpoint['group'], {
            'info': {'name': endpoint['group'], 'type': 'folder', 'seq': len(groups) + 1},
            'request': {'auth': 'inherit'}, 'items': []})
        group['items'].append(request_yaml(endpoint, len(group['items']) + 1))
    return {
        'opencollection': '1.0.0',
        'info': {'name': 'Fleet REST API', 'version': version},
        'request': {'auth': {'type': 'bearer', 'token': '{{token}}'}},
        'config': {'environments': [{'name': 'Fleet', 'variables': [
            {'name': 'baseUrl', 'value': 'https://fleet.example.com'},
            {'name': 'token', 'secret': True}]}]},
        'items': list(groups.values()),
        'docs': {'type': 'text/markdown', 'content':
                 f'Unofficial Fleet API collection generated directly from {source_ref}. '
                 'HTTP only; excludes WebSocket/SockJS and historical routes mentioned only in deprecation notices.'},
        'bundled': True,
        'extensions': {'fleet': {
            'source_ref': source_ref, 'source_sha256': sha(text.encode()),
            'operation_count': len(endpoints), 'path_count': len({e['path'] for e in endpoints}),
            'skipped_sections': skipped, 'warnings': warnings}}
    }


def write_collection(output, collection, check=False):
    content = dump(collection).encode('utf-8')
    if check:
        if not output.exists() or output.read_bytes() != content:
            raise ValueError(f'Generated collection is out of date: {output}')
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    # Replace atomically only after parsing and serialization succeed.
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    try:
        temporary.chmod(0o644)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def fetch(url, github_api=False):
    headers = {'User-Agent': 'fleet-bruno-collection-generator'}
    if github_api and os.environ.get('GH_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        return response.read().decode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--tag', help='Fleet release tag (fleet-v4.x.y), or latest')
    source.add_argument('--input', type=Path, help='Local REST API Markdown (offline)')
    parser.add_argument('--version', help='Required with --input, e.g. 4.92.3 or snapshot')
    parser.add_argument('--output', '-o', type=Path, default=ROOT / 'fleet.bruno.yml')
    parser.add_argument('--check', action='store_true', help='Verify generated files without changing them')
    args = parser.parse_args()
    if not args.tag and not args.input:
        if not args.check:
            parser.error('Choose --tag or --input')
        args.tag = yaml.safe_load(args.output.read_text())['extensions']['fleet']['source_ref']
    if args.tag:
        tag = json.loads(fetch('https://api.github.com/repos/fleetdm/fleet/releases/latest', True))['tag_name'] if args.tag == 'latest' else args.tag
        if not re.fullmatch(r'fleet-v\d+\.\d+\.\d+(?:[-.][A-Za-z0-9.-]+)?', tag):
            parser.error('Expected a Fleet release tag such as fleet-v4.92.3')
        version = tag.removeprefix('fleet-v')
        text = fetch('https://raw.githubusercontent.com/fleetdm/fleet/' + tag + '/' + urllib.parse.quote(DOC_PATH))
    else:
        if not args.version:
            parser.error('--version is required with --input')
        version, text = args.version, args.input.read_text(encoding='utf-8')
        tag = 'fleet-v' + version if re.fullmatch(r'\d+\.\d+\.\d+(?:[-.][A-Za-z0-9.-]+)?', version) else version
    collection = build(text, version, tag)
    write_collection(args.output, collection, args.check)
    report = collection['extensions']['fleet']
    action = 'Verified' if args.check else 'Generated'
    print(f'{action} {args.output.name}: Fleet {version}, '
          f'{report["operation_count"]} requests, {len(report["warnings"])} parsing notes')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        sys.exit(str(exc))
