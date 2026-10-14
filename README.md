# Fleet API for Bruno

A Bruno collection generated from [Fleet's REST API documentation](https://fleetdm.com/docs/rest-api/rest-api), with requests, parameters, example bodies, and saved responses grouped by API section.

## Setup

1. Import [fleet.bruno.yml](fleet.bruno.yml) into Bruno as an OpenCollection YAML collection.
2. Select the **Fleet** environment.
3. Set `baseUrl` to your Fleet server origin, such as `https://fleet.example.com`, without a trailing slash.
4. Set the secret `token` variable to your API token, without the `Bearer ` prefix. Get a token from **My account → Get API token** in Fleet.
5. Send **Authentication → Me** to check your connection.

Fill in path parameters, enable the query parameters you need, and edit example bodies or select upload files before sending requests. Keep credentials and personal changes in your imported Bruno copy; regenerating replaces the repository's collection file.

## Generate

Python 3.12 is recommended and used by both GitHub workflows. Requires Python 3.10+:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/generate.py --tag latest
```

To generate for a specific Fleet release:

```sh
python scripts/generate.py --tag fleet-v4.93.0
```

Use `-o another.yml` to choose an output filename. To generate from a local documentation file:

```sh
python scripts/generate.py --input /path/to/rest-api.md --version 4.93.0
```

## Validate

```sh
python -m unittest discover -s scripts -v
python scripts/generate.py --check
```

The tests run offline. `--check` downloads documentation for the collection's recorded release and verifies that it reproduces the collection. Supply `--input` and `--version` to check against a local documentation file instead.

## Automatic updates

The update workflow checks for new Fleet releases on weekdays at **09:00 UTC** and opens a pull request with the regenerated collection. Run it manually in GitHub Actions to select a release tag or force regeneration. The validation workflow runs on pull requests and pushes to `main`.

To enable update PRs, allow **GitHub Actions to create and approve pull requests** under **Settings → Actions → General**. Review and merge the generated PRs when ready.

## Coverage

The collection covers documented HTTP endpoints. WebSocket/SockJS streaming and historical routes mentioned only in deprecation notices are excluded. Request bodies contain examples or placeholders and may need adjustment for your use case.

The collection's Fleet version is recorded in `info.version`. Source details and generation notes are available under `extensions.fleet` in the YAML file.
