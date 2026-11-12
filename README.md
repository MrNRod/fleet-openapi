# Fleet OpenCollection

Fleet REST API requests generated from [Fleet's documentation](https://fleetdm.com/docs/rest-api/rest-api) in [OpenCollection](https://www.opencollection.com/) format.

## Use the collection

- **Git:** clone this repository and open its folder in a client that supports OpenCollection's directory layout. Pull updates with `git pull --ff-only` or your client's Git controls.
- **Download:** import [fleet.opencollection.yml](https://github.com/MrNRod/fleet-openapi/releases/latest/download/fleet.opencollection.yml) from the latest release. Reimport a newer bundle to update your copy.

Both contain the same requests, examples, documentation, and environment template. The repository's `opencollection.yml` requires the surrounding request folders; the release bundle is self-contained. This is OpenCollection, not OpenAPI.

### Bruno example

Tested with Bruno. Other clients must support OpenCollection and the chosen layout; their feature support may vary.

1. Use **Open Collection** to select your cloned repository folder, or import the release bundle as OpenCollection YAML.
2. Duplicate the **Fleet** environment as **Local**, select it, and set:
   - `baseUrl`: your Fleet server URL, without a trailing slash.
   - `token`: your API token as a secret, without the `Bearer ` prefix.
3. Send **Authentication → Me** to check your connection.

Fill in path parameters, enable query parameters as needed, and edit sample bodies before sending requests. WebSocket/SockJS endpoints are excluded.

For Git users, `Fleet` is the generated template. Other files in `environments/` are ignored by Git and preserved by the generator. Keep your settings in **Local**. Request files are generated; local edits can conflict with incoming updates.

## Generate

Use Python 3.14:

```sh
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/generate.py --tag latest
```

Use a Fleet release tag, such as `fleet-v4.94.1`, instead of `latest` to pin a version. To generate a bundle from the release recorded in `opencollection.yml`:

```sh
python scripts/generate.py --bundle dist/fleet.opencollection.yml
```

Bundles are build outputs and are not committed. See `python scripts/generate.py --help` for offline generation and output options.

## Validate

```sh
python -m unittest discover -s scripts -v
python scripts/generate.py --check
```

`--check` downloads the pinned release's documentation and checks every generated file without modifying it. Add `--bundle dist/fleet.opencollection.yml` to check a generated bundle instead.

## Automatic updates

GitHub Actions checks for new Fleet releases weekdays at **09:00 UTC** and on pushes to `main`. It validates updates and opens a PR with squash auto-merge enabled. Required checks and reviews must pass before merging.

The same workflow independently validates the collection on `main` and publishes a downloadable bundle. Each distinct bundle gets a release; unchanged runs reuse it. Scheduled runs also publish updates merged by bots. The workflow can be run manually.

Enable **Allow GitHub Actions to create and approve pull requests** under **Settings → Actions → General**. GitHub may require **Approve workflows to run** on bot-created PRs before their checks start.

Under **Settings → General → Pull Requests**, enable **Allow squash merging**, **Allow auto-merge**, and **Automatically delete head branches**. Require the `validate` status check on `main`. Require one approving review if you want to approve each update yourself.

## License

Project code: [MIT](LICENSE). Generated collection and bundles: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), adapted from Fleet's documentation. See [NOTICE](NOTICE) for attribution.
