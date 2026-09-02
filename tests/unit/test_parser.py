from __future__ import annotations

from pathlib import Path

from ci_dashboard.parser import (
    infer_image_type,
    parse_packages,
    parse_results,
    parse_session_timestamp,
    parse_snap_packages,
    parse_top_level_meta,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_submission.json"


def test_parse_top_level_meta():
    meta = parse_top_level_meta(FIXTURE)
    assert meta["testplan_id"] == "com.canonical.qa.carmel::carmel-desktop-24-04-automated"
    assert meta["distribution"] == "Ubuntu 24.04.4 LTS"
    assert meta["distribution_codename"] == "noble"
    assert meta["distribution_release"] == "24.04"
    assert meta["checkbox_version"] == "7.5.0.dev34"
    assert meta["kernel"] == "6.8.0-1084-qcom"
    assert meta["architecture"] == "arm64"


def test_parse_packages():
    packages = parse_packages(FIXTURE)
    assert {"name": "acl", "version": "2.3.2-1build1.1"} in packages
    assert len(packages) == 2


def test_parse_snap_packages():
    snaps = parse_snap_packages(FIXTURE)
    assert snaps == [
        {"name": "core24", "version": "20260410", "channel": "latest/stable", "revision": "1644"}
    ]


def test_parse_results_strips_output_fields():
    results = parse_results(FIXTURE)
    assert len(results) == 30
    for r in results:
        assert not hasattr(r, "io_log")
        assert not hasattr(r, "comments")
        assert r.status in {"pass", "fail", "skip"}
        assert r.full_id
        assert r.name


def test_parse_results_preserves_outcome_detail():
    results = parse_results(FIXTURE)
    outcomes = {r.outcome for r in results}
    assert "skipped-resource" in outcomes or "skipped-dependency" in outcomes


def test_infer_image_type():
    assert infer_image_type("com.canonical.qa.carmel::carmel-desktop-24-04-automated") == "desktop"
    assert infer_image_type("com.canonical.certification::server-plan") == "server"
    assert infer_image_type(None) is None
    assert infer_image_type("unrelated") is None


def test_parse_session_timestamp_extracts_embedded_datetime():
    ts = parse_session_timestamp(FIXTURE)
    assert ts == "2026-09-01T07:42:00+00:00"
