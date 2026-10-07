# pe-ci-dashboard

A static, database-free CI dashboard for historic Ubuntu Desktop/Server/Core
image test results (Canonical Checkbox `submission.json` reports), covering
8 lab devices running daily image tests.

## How it works

1. Each device's test job produces a `submission.json` (Checkbox/
   Certification report).
2. A job in the same GitHub Actions workflow calls this repo's `ingest`
   CLI, passing the device CID, image type (`desktop`/`server`/`core`), and the
   `submission.json` as an artifact.
3. `ci-dashboard ingest` streams the (often 100+ MB) JSON, keeping only
   test id/name/category/status/outcome/duration — **test output
   (`io_log`/`comments`) is never read or stored.**
4. The result is merged into small JSON files under `docs/data/` on a
   dedicated `data` branch: `manifest.json`, `tests/*.json` (per-test
   history across all runs/devices), `devices/*.json` (per-device rollup),
   `runs/*.json` (per-submission detail).
5. A separate workflow assembles `docs/` (code from `main` + data from
   `data`) and publishes it to GitHub Pages.
6. The static frontend (Vanilla Framework + Alpine.js, no build step)
   fetches those JSON files directly in the browser.

## Local development

```bash
python3 -m pip install -e ".[dev]"
pytest

# Parse a submission.json and merge it into ./docs/data
ci-dashboard ingest path/to/submission.json \
  --device cid-abc123 \
  --image desktop \
  --data-dir docs/data

# Serve the dashboard locally
cd docs && python3 -m http.server 8080
```

## Data retention

History entries older than `--retention-days` (default 180) are pruned at
ingest time to keep per-test JSON files small.

## Repository layout

- `src/ci_dashboard/` — the `ingest` CLI (parser, aggregator, image config).
- `docs/` — the static frontend; `docs/data/` is generated output, not
  hand-edited source (see [AGENTS.md](AGENTS.md) for details).
- `tests/` — unit tests and fixtures.

See [AGENTS.md](AGENTS.md) for conventions and build/test commands.

## License

Licensed under the GPL-3.0-or-later. See [LICENSE](LICENSE) for the full
text. Copyright (C) 2026 Canonical Ltd.
