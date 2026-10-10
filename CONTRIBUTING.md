# Contributing to Stopover

Thanks for helping. Bug reports, client setup notes and focused pull requests are all welcome.

## Before you start

- **Bugs:** open an issue with what you did, what you expected, what happened, and your Stopover version and client (Claude Code, Codex, Cursor and so on).
- **Security issues:** don't open an issue; follow [SECURITY.md](SECURITY.md).
- **New features:** open an issue first to discuss it. Stopover deliberately stays small: one container, no accounts, no outbound calls. Features that need a hosted service may not fit here.

## Development setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
```

On Windows, use `.venv\Scripts\python.exe` and `.venv\Scripts\pip.exe`. To run the server without Docker: `.venv/bin/python -m stopover --data-dir ./data serve --host 127.0.0.1 --port 8765`.

## Pull requests

- Keep each pull request to one change, and add or update tests for it. The suite covers storage, HTTP, MCP over HTTP and stdio, the backend conformance suite and the dashboard in a real browser.
- Match the surrounding code: its naming, comment density and style. Comments explain *why*, not what.
- Changing an MCP tool, its input schema or a model? Regenerate the committed schemas in `schemas/` (the test `test_committed_schemas_match_models` shows the difference) and update [docs/api.md](docs/api.md).
- Changing the dashboard? Check it at phone and desktop widths, and regenerate the documentation screenshots with `.venv/bin/python scripts/screenshots.py` if they changed.
- Changing dependencies? Update `pyproject.toml` and both lock files, and keep `requirements-min.txt` at the lowest versions `pyproject.toml` allows. CI tests those minimums and audits the locks.
- Add a line to the **Unreleased** section of [CHANGELOG.md](CHANGELOG.md) for anything users would notice.

CI must pass: tests on Python 3.10 and 3.12, the minimum dependency versions, the dependency audit, packaging, and the Docker image under the Compose restrictions.

## Licensing

Stopover is licensed under the [Apache License 2.0](LICENSE). By submitting a contribution, you agree it's licensed under the same terms (section 5 of the license); there's no separate contributor agreement.
