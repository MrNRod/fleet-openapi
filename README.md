# Fleet API for Bruno

A Bruno collection generated from [Fleet's REST API documentation](https://fleetdm.com/docs/rest-api/rest-api).

## Setup

1. Import [fleet.bruno.yml](fleet.bruno.yml) into Bruno as an OpenCollection YAML collection.
2. Select the **Fleet** environment and set:
   - `baseUrl`: your Fleet server URL, without a trailing slash.
   - `token`: your API token, without the `Bearer ` prefix. Get one from **My account → Get API token** in Fleet.
3. Send **Authentication → Me** to check your connection.

Fill in path parameters, enable query parameters as needed, and edit sample bodies before sending requests. WebSocket/SockJS endpoints are excluded.

## Generate

Use Python 3.14:

```sh
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/generate.py --tag latest
```

Replace `latest` with a Fleet release tag, such as `fleet-v4.93.0`, to generate a specific version. See `python scripts/generate.py --help` for other options.

## Validate

```sh
python -m unittest discover -s scripts -v
python scripts/generate.py --check
```

`--check` downloads the pinned release's docs and compares the generated output with the collection.

## Automatic updates

GitHub Actions checks for new Fleet releases weekdays at **09:00 UTC**, validates the collection, and opens an update PR with squash auto-merge enabled. GitHub merges it once required checks and reviews pass, preserving the PR history and one commit per update. Both workflows can also be run manually.

Enable **Allow GitHub Actions to create and approve pull requests** under **Settings → Actions → General**.

Under **Settings → General → Pull Requests**, enable **Allow squash merging**, **Allow auto-merge**, and **Automatically delete head branches**. Add a rule for `main` requiring the `validate` status check. Require one approving review if you want to approve each update before it merges. The workflow does not approve PRs or bypass branch rules. Without required checks or reviews, a validated update can merge immediately.

## License

Project code: [MIT](LICENSE). Generated collection: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), adapted from Fleet's documentation. See [NOTICE](NOTICE) for attribution.
