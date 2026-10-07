# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project overview

`pe-ci-dashboard` (package `ci_dashboard`) is a static, database-free CI
dashboard for historic Ubuntu Desktop/Server/Core image test results
(Canonical Checkbox `submission.json` reports). It has two halves:

- **Backend (`src/ci_dashboard/`)**: a Python CLI (`ci-dashboard ingest ...`)
  that parses a Checkbox `submission.json`, extracts only
  test id/name/category/status/outcome/duration (never `io_log`/`comments`
  test output), and merges the result into small JSON files under
  `docs/data/`.
- **Frontend (`docs/`)**: a static, build-step-free site (Vanilla Framework +
  Alpine.js) that fetches the JSON files in `docs/data/` directly in the
  browser. `docs/data/` is regenerated/overwritten by the ingest pipeline on
  a dedicated `data` branch — treat its contents as generated output, not
  hand-edited source.

See [README.md](README.md) for the full pipeline description.

## Build / test / lint commands

```bash
python3 -m pip install -e ".[dev]"
pytest                      # run unit tests (tests/unit/)
ruff check src tests        # lint
```

Serve the dashboard locally:

```bash
cd docs && python3 -m http.server 8080
```

## Conventions

- Python 3.11+, line length 100 (see `[tool.ruff]` in `pyproject.toml`).
- Never read or persist Checkbox test *output* (`io_log`/`comments`) —
  only status/outcome metadata. This is a hard size constraint, not
  a style preference.
- Data retention: history older than `--retention-days` (default 180) is
  pruned at ingest time; don't remove this pruning when touching
  `aggregator.py`.
- Frontend pages have no build step — edit the HTML/JS in `docs/` directly
  (`docs/assets/app.js`, `docs/assets/style.css`), don't introduce a bundler.

## Testing expectations

Add/update unit tests under `tests/unit/` for any change to
`src/ci_dashboard/` (parser, aggregator, imageconfig, cli). Fixtures live in
`tests/fixtures/`.
