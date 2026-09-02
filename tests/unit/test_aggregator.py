from __future__ import annotations

import json
from pathlib import Path

from ci_dashboard.aggregator import (
    ingest_run,
    rebuild_compare_matrix,
    rebuild_test_index,
    slugify_test_id,
)
from ci_dashboard.models import RunMeta, TestResult


def _make_run(run_id: str, device: str, image: str, timestamp: str, statuses: list[str]) -> RunMeta:
    results = [
        TestResult(
            full_id=f"com.canonical.certification::test/{i}",
            name=f"Test {i}",
            category="Networking",
            status=s,
            outcome=s,
            duration=1.0 + i,
        )
        for i, s in enumerate(statuses)
    ]
    return RunMeta(
        run_id=run_id,
        device_cid=device,
        image_type=image,
        testplan_id="com.canonical.qa.carmel::carmel-desktop-24-04-automated",
        distribution="Ubuntu 24.04.4 LTS",
        timestamp=timestamp,
        results=results,
    )


def test_slugify_is_filesystem_safe_and_stable():
    slug = slugify_test_id("com.canonical.certification::acpi/oem_osi")
    assert "/" not in slug and ":" not in slug
    assert slug == slugify_test_id("com.canonical.certification::acpi/oem_osi")


def test_ingest_run_creates_manifest_devices_tests_runs(tmp_path: Path):
    run = _make_run("run-1", "cid-aaa111", "desktop", "2026-09-01T00:00:00+00:00", ["pass", "fail"])
    ingest_run(tmp_path, run)

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["runs"][0]["run_id"] == "run-1"
    assert manifest["runs"][0]["summary"] == {"pass": 1, "fail": 1, "skip": 0, "failed-ignored": 0}
    assert manifest["devices"] == ["cid-aaa111"]

    device = json.loads((tmp_path / "devices" / "cid-aaa111.json").read_text())
    assert device["runs"][0]["run_id"] == "run-1"

    run_detail = json.loads((tmp_path / "runs" / "run-1.json").read_text())
    assert len(run_detail["results"]) == 2
    assert "io_log" not in run_detail["results"][0]
    assert "comments" not in run_detail["results"][0]


def test_ingest_run_is_idempotent_on_reingest(tmp_path: Path):
    run = _make_run("run-1", "cid-aaa111", "desktop", "2026-09-01T00:00:00+00:00", ["pass"])
    ingest_run(tmp_path, run)
    ingest_run(tmp_path, run)  # re-ingest same run_id
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert len(manifest["runs"]) == 1


def test_ingest_run_across_devices_builds_test_history(tmp_path: Path):
    run_a = _make_run("run-a", "cid-aaa111", "desktop", "2026-09-01T00:00:00+00:00", ["pass"])
    run_b = _make_run("run-b", "cid-bbb222", "desktop", "2026-09-02T00:00:00+00:00", ["fail"])
    ingest_run(tmp_path, run_a)
    ingest_run(tmp_path, run_b)

    slug = slugify_test_id("com.canonical.certification::test/0")
    test_history = json.loads((tmp_path / "tests" / f"{slug}.json").read_text())
    assert len(test_history["history"]) == 2
    devices_seen = {h["device_cid"] for h in test_history["history"]}
    assert devices_seen == {"cid-aaa111", "cid-bbb222"}
    # newest first
    assert test_history["history"][0]["run_id"] == "run-b"


def test_retention_prunes_old_entries(tmp_path: Path):
    old_run = _make_run("run-old", "cid-aaa111", "desktop", "2020-01-01T00:00:00+00:00", ["pass"])
    ingest_run(tmp_path, old_run, retention_days=30)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["runs"] == []


def test_rebuild_test_index(tmp_path: Path):
    run = _make_run("run-1", "cid-aaa111", "desktop", "2026-09-01T00:00:00+00:00", ["pass", "fail"])
    ingest_run(tmp_path, run)
    rebuild_test_index(tmp_path)
    index = json.loads((tmp_path / "tests" / "index.json").read_text())
    assert len(index["tests"]) == 2
    names = {t["name"] for t in index["tests"]}
    assert names == {"Test 0", "Test 1"}


def test_rebuild_compare_matrix_latest_status_per_device(tmp_path: Path):
    run_a1 = _make_run("run-a1", "cid-aaa111", "desktop", "2026-09-01T00:00:00+00:00", ["pass"])
    run_a2 = _make_run("run-a2", "cid-aaa111", "desktop", "2026-09-02T00:00:00+00:00", ["fail"])
    run_b1 = _make_run("run-b1", "cid-bbb222", "server", "2026-09-01T12:00:00+00:00", ["pass"])
    for r in (run_a1, run_a2, run_b1):
        ingest_run(tmp_path, r)
    rebuild_compare_matrix(tmp_path)

    compare = json.loads((tmp_path / "compare.json").read_text())
    assert set(compare["devices"]) == {"cid-aaa111", "cid-bbb222"}
    test0 = next(t for t in compare["tests"] if t["name"] == "Test 0")
    # cid-aaa111's latest result should be the fail from run-a2, not the earlier pass
    assert test0["latest_by_device"]["cid-aaa111"]["status"] == "fail"
    assert test0["latest_by_device"]["cid-aaa111"]["run_id"] == "run-a2"
    assert test0["latest_by_device"]["cid-bbb222"]["status"] == "pass"
