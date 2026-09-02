"""Merge a newly-ingested run into the existing ``docs/data/*.json`` files.

All functions are pure I/O over a ``data_dir`` (normally ``docs/data``)
which is expected to be checked out from the dedicated ``data`` branch
before ingest and committed back afterwards (see ``.github/workflows/
ingest.yml``).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ci_dashboard.models import RunMeta

SCHEMA_VERSION = "1"
DEFAULT_RETENTION_DAYS = 180

_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def slugify_test_id(full_id: str) -> str:
    """Turn a Checkbox full_id (e.g. ``com.canonical.certification::acpi/
    oem_osi``) into a filesystem-safe filename. Collisions are avoided with
    a short content hash suffix since sanitization is lossy."""
    base = _SLUG_RE.sub("_", full_id).strip("_")[:120]
    digest = hashlib.sha1(full_id.encode("utf-8")).hexdigest()[:8]
    return f"{base}-{digest}"


def _load_json(path: Path, default: dict) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return default


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _cutoff_iso(retention_days: int) -> str:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    return cutoff.isoformat()


def ingest_run(
    data_dir: str | Path,
    run: RunMeta,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> None:
    """Fold ``run`` into manifest.json, tests/*.json, devices/*.json, and
    write runs/{run_id}.json. Idempotent: re-ingesting the same run_id
    replaces the prior entry rather than duplicating it."""
    data_dir = Path(data_dir)
    cutoff = _cutoff_iso(retention_days)

    previous_run_id = _find_previous_run_id(data_dir, run)
    _update_manifest(data_dir, run, cutoff)
    _update_run_detail(data_dir, run)
    _update_device(data_dir, run, cutoff)
    _update_packages(data_dir, run, previous_run_id)
    for result in run.results:
        _update_test_history(data_dir, run, result, cutoff)


def _find_previous_run_id(data_dir: Path, run: RunMeta) -> str | None:
    """The most recent existing run for the same device+image, strictly
    before this run's timestamp — used as the baseline for the package
    diff. Looked up before the manifest is updated with the new run."""
    manifest = _load_json(data_dir / "manifest.json", {"runs": []})
    candidates = [
        r
        for r in manifest.get("runs", [])
        if r["device_cid"] == run.device_cid
        and r["image_type"] == run.image_type
        and r["run_id"] != run.run_id
        and r["timestamp"] < run.timestamp
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["timestamp"])["run_id"]


def _update_manifest(data_dir: Path, run: RunMeta, cutoff: str) -> None:
    path = data_dir / "manifest.json"
    manifest = _load_json(
        path,
        {
            "version": SCHEMA_VERSION,
            "generated_at": "",
            "runs": [],
            "devices": [],
            "device_meta": {},
        },
    )
    manifest["runs"] = [r for r in manifest["runs"] if r["run_id"] != run.run_id]
    manifest["runs"].append(
        {
            "run_id": run.run_id,
            "device_cid": run.device_cid,
            "image_type": run.image_type,
            "timestamp": run.timestamp,
            "testplan_id": run.testplan_id,
            "distribution": run.distribution,
            "summary": run.summary,
            "total": len(run.results),
            "submission_id": run.submission_id,
            "checkbox_version": run.checkbox_version,
            "kernel": run.kernel,
            "architecture": run.architecture,
        }
    )
    manifest["runs"] = [r for r in manifest["runs"] if r["timestamp"] >= cutoff]
    manifest["runs"].sort(key=lambda r: r["timestamp"], reverse=True)
    devices = sorted({r["device_cid"] for r in manifest["runs"]} | {run.device_cid})
    manifest["devices"] = devices
    device_meta = manifest.setdefault("device_meta", {})
    if run.device_alias or run.platform or run.series:
        device_meta[run.device_cid] = {
            "alias": run.device_alias or run.device_cid,
            "platform": run.platform,
            "series": run.series,
        }
    manifest["generated_at"] = datetime.now(UTC).isoformat()
    manifest["version"] = SCHEMA_VERSION
    _save_json(path, manifest)


def register_known_devices(data_dir: str | Path, devices: list[dict]) -> None:
    """Seed manifest.json's device roster/device_meta from images.yaml's full
    device list, even for devices that have never submitted a run. Existing
    entries (and any runs) are left untouched; this only adds devices that
    aren't already present."""
    data_dir = Path(data_dir)
    path = data_dir / "manifest.json"
    manifest = _load_json(
        path,
        {
            "version": SCHEMA_VERSION,
            "generated_at": "",
            "runs": [],
            "devices": [],
            "device_meta": {},
        },
    )
    device_meta = manifest.setdefault("device_meta", {})
    all_cids = set(manifest.get("devices", []))
    for d in devices:
        all_cids.add(d["cid"])
        device_meta.setdefault(
            d["cid"],
            {"alias": d.get("alias") or d["cid"], "platform": d.get("platform"), "series": d.get("series")},
        )
    manifest["devices"] = sorted(all_cids)
    manifest["generated_at"] = datetime.now(UTC).isoformat()
    manifest["version"] = SCHEMA_VERSION
    _save_json(path, manifest)


def _update_run_detail(data_dir: Path, run: RunMeta) -> None:
    path = data_dir / "runs" / f"{run.run_id}.json"
    results = []
    for r in run.results:
        entry = asdict(r)
        entry["slug"] = slugify_test_id(r.full_id)
        results.append(entry)
    _save_json(
        path,
        {
            "version": SCHEMA_VERSION,
            "run_id": run.run_id,
            "device_cid": run.device_cid,
            "image_type": run.image_type,
            "timestamp": run.timestamp,
            "testplan_id": run.testplan_id,
            "distribution": run.distribution,
            "summary": run.summary,
            "results": results,
            "submission_id": run.submission_id,
            "checkbox_version": run.checkbox_version,
            "kernel": run.kernel,
            "architecture": run.architecture,
            "distribution_codename": run.distribution_codename,
            "distribution_release": run.distribution_release,
            "device_alias": run.device_alias,
        },
    )


def _update_device(data_dir: Path, run: RunMeta, cutoff: str) -> None:
    path = data_dir / "devices" / f"{run.device_cid}.json"
    device = _load_json(
        path,
        {
            "version": SCHEMA_VERSION,
            "device_cid": run.device_cid,
            "alias": run.device_cid,
            "platform": None,
            "series": None,
            "runs": [],
        },
    )
    device["runs"] = [r for r in device["runs"] if r["run_id"] != run.run_id]
    device["runs"].append(
        {
            "run_id": run.run_id,
            "image_type": run.image_type,
            "timestamp": run.timestamp,
            "summary": run.summary,
            "total": len(run.results),
        }
    )
    device["runs"] = [r for r in device["runs"] if r["timestamp"] >= cutoff]
    device["runs"].sort(key=lambda r: r["timestamp"], reverse=True)
    device["version"] = SCHEMA_VERSION
    device["device_cid"] = run.device_cid
    if run.device_alias:
        device["alias"] = run.device_alias
    if run.platform:
        device["platform"] = run.platform
    if run.series:
        device["series"] = run.series
    _save_json(path, device)


def _diff_package_lists(old: list[dict], new: list[dict]) -> dict:
    """Compare two {"name", "version"} lists, returning added/removed/
    changed-version package names."""
    old_map = {p["name"]: p.get("version") for p in old}
    new_map = {p["name"]: p.get("version") for p in new}
    added = sorted(set(new_map) - set(old_map))
    removed = sorted(set(old_map) - set(new_map))
    changed = sorted(
        (
            {"name": n, "old_version": old_map[n], "new_version": new_map[n]}
            for n in (new_map.keys() & old_map.keys())
            if old_map[n] != new_map[n]
        ),
        key=lambda c: c["name"],
    )
    return {"added": added, "removed": removed, "changed": changed}


def _update_packages(data_dir: Path, run: RunMeta, previous_run_id: str | None) -> None:
    """Write packages/{run_id}.json with the full deb/snap package lists for
    this run, plus a diff against the previous run for the same device+image
    (added/removed/version-changed packages) so regressions can be
    correlated with package/kernel bumps."""
    path = data_dir / "packages" / f"{run.run_id}.json"
    packages = [asdict(p) for p in run.packages]
    snap_packages = [asdict(p) for p in run.snap_packages]

    diff = None
    if previous_run_id:
        prev = _load_json(data_dir / "packages" / f"{previous_run_id}.json", {})
        diff = {
            "packages": _diff_package_lists(prev.get("packages", []), packages),
            "snap_packages": _diff_package_lists(prev.get("snap_packages", []), snap_packages),
        }

    _save_json(
        path,
        {
            "version": SCHEMA_VERSION,
            "run_id": run.run_id,
            "device_cid": run.device_cid,
            "image_type": run.image_type,
            "timestamp": run.timestamp,
            "submission_id": run.submission_id,
            "checkbox_version": run.checkbox_version,
            "kernel": run.kernel,
            "architecture": run.architecture,
            "distribution_codename": run.distribution_codename,
            "distribution_release": run.distribution_release,
            "packages": packages,
            "snap_packages": snap_packages,
            "previous_run_id": previous_run_id,
            "diff_from_previous": diff,
        },
    )


def _update_test_history(data_dir: Path, run: RunMeta, result, cutoff: str) -> None:
    slug = slugify_test_id(result.full_id)
    path = data_dir / "tests" / f"{slug}.json"
    test = _load_json(
        path,
        {
            "version": SCHEMA_VERSION,
            "full_id": result.full_id,
            "name": result.name,
            "category": result.category,
            "history": [],
        },
    )
    test["name"] = result.name
    test["category"] = result.category
    test["history"] = [
        h
        for h in test["history"]
        if not (h["run_id"] == run.run_id and h["device_cid"] == run.device_cid)
    ]
    test["history"].append(
        {
            "run_id": run.run_id,
            "device_cid": run.device_cid,
            "image_type": run.image_type,
            "timestamp": run.timestamp,
            "status": result.status,
            "outcome": result.outcome,
            "duration": result.duration,
            "ignore_reason": result.ignore_reason,
        }
    )
    test["history"] = [h for h in test["history"] if h["timestamp"] >= cutoff]
    test["history"].sort(key=lambda h: h["timestamp"], reverse=True)
    test["version"] = SCHEMA_VERSION
    _save_json(path, test)


def rebuild_compare_matrix(data_dir: str | Path) -> None:
    """Write ``compare.json`` — for every known test, the latest status per
    device — so the cross-device comparison view can render without
    fetching every per-test history file individually."""
    data_dir = Path(data_dir)
    tests_dir = data_dir / "tests"
    manifest = _load_json(data_dir / "manifest.json", {"devices": [], "device_meta": {}})
    devices = manifest.get("devices", [])
    device_meta = manifest.get("device_meta", {})

    matrix = []
    if tests_dir.exists():
        for f in sorted(tests_dir.glob("*.json")):
            if f.name == "index.json":
                continue
            with open(f, encoding="utf-8") as fh:
                t = json.load(fh)
            latest_by_device: dict[str, dict] = {}
            for entry in t["history"]:
                dev = entry["device_cid"]
                if dev not in latest_by_device or entry["timestamp"] > latest_by_device[dev]["timestamp"]:
                    latest_by_device[dev] = entry
            matrix.append(
                {
                    "full_id": t["full_id"],
                    "name": t["name"],
                    "category": t["category"],
                    "slug": f.stem,
                    "latest_by_device": {
                        dev: {
                            "status": e["status"],
                            "run_id": e["run_id"],
                            "timestamp": e["timestamp"],
                            "image_type": e["image_type"],
                            "ignore_reason": e.get("ignore_reason"),
                        }
                        for dev, e in latest_by_device.items()
                    },
                }
            )

    _save_json(
        data_dir / "compare.json",
        {
            "version": SCHEMA_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "devices": devices,
            "device_meta": device_meta,
            "tests": matrix,
        },
    )


def rebuild_test_index(data_dir: str | Path) -> None:
    """Write ``tests/index.json`` — a lightweight list of all known tests
    (id/name/category only) so the frontend can populate the test picker
    without fetching every per-test history file."""
    data_dir = Path(data_dir)
    tests_dir = data_dir / "tests"
    index = []
    if tests_dir.exists():
        for f in sorted(tests_dir.glob("*.json")):
            if f.name == "index.json":
                continue
            with open(f, encoding="utf-8") as fh:
                t = json.load(fh)
            latest = t["history"][0] if t["history"] else None
            index.append(
                {
                    "full_id": t["full_id"],
                    "name": t["name"],
                    "category": t["category"],
                    "slug": f.stem,
                    "latest_status": latest["status"] if latest else None,
                    "run_count": len(t["history"]),
                }
            )
    _save_json(
        tests_dir / "index.json",
        {"version": SCHEMA_VERSION, "generated_at": datetime.now(UTC).isoformat(), "tests": index},
    )
