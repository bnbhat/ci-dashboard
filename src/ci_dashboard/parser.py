"""Streaming parser for Checkbox ``submission.json`` files.

These files can be 100+ MB (mostly due to ``io_log`` / attachment payload
content we don't need). We use ``ijson`` to stream the ``results`` array so
we never hold the whole file in memory, and we deliberately only extract
the handful of fields the dashboard needs. Test output (``io_log``,
``comments``) is never read into memory or stored.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

import ijson

from ci_dashboard.models import TestResult

_SESSION_TIMESTAMP_RE = re.compile(r"PE-Images-(\d{12})")

# Only these top-level scalar fields are read, streamed independently so we
# never have to materialize the (much larger) `results`/`packages` arrays
# to reach them.
_TOP_LEVEL_PATHS = {
    "testplan_id": "testplan_id",
    "distribution": "distribution.description",
    "distribution_codename": "distribution.codename",
    "distribution_release": "distribution.release",
    "checkbox_version": "origin.version",
    "kernel": "kernel",
    "architecture": "architecture",
}

# outcome values that should not count as a real pass/fail/skip signal for
# history purposes are still recorded as "skip" (grouped) to keep the
# dashboard simple; `outcome` itself is preserved for detail views.
_STATUS_VALUES = {"pass", "fail", "skip"}


def _stream_top_level_field(fh: IO[bytes], path: str) -> str | None:
    for value in ijson.items(fh, path):
        return str(value) if value is not None else None
    return None


def parse_top_level_meta(path: str | Path) -> dict[str, str | None]:
    """Read only the handful of top-level scalar fields we need (testplan
    id, distribution details, checkbox version, kernel, architecture)
    without loading the rest of the (potentially huge) submission file."""
    meta: dict[str, str | None] = {}
    for key, json_path in _TOP_LEVEL_PATHS.items():
        with open(path, "rb") as fh:
            meta[key] = _stream_top_level_field(fh, json_path)
    return meta


def parse_packages(path: str | Path) -> list[dict[str, str | None]]:
    """Stream the ``packages`` (.deb) array, keeping only name/version."""
    packages: list[dict[str, str | None]] = []
    with open(path, "rb") as fh:
        for item in ijson.items(fh, "packages.item"):
            name = item.get("name")
            if not name:
                continue
            packages.append({"name": name, "version": item.get("version")})
    return packages


def parse_snap_packages(path: str | Path) -> list[dict[str, str | None]]:
    """Stream the ``snap-packages`` array, keeping name/version/channel/
    revision."""
    snaps: list[dict[str, str | None]] = []
    with open(path, "rb") as fh:
        for item in ijson.items(fh, "snap-packages.item"):
            name = item.get("name")
            if not name:
                continue
            revision = item.get("revision")
            snaps.append(
                {
                    "name": name,
                    "version": item.get("version"),
                    "channel": item.get("channel"),
                    "revision": str(revision) if revision is not None else None,
                }
            )
    return snaps


def parse_results(path: str | Path) -> list[TestResult]:
    """Stream ``results[]`` from a submission.json, keeping only the name/
    id/category/status/outcome/duration fields. ``io_log`` and ``comments``
    are never read into a Python object — ijson skips over them cheaply at
    the parse-event level since we don't reference those keys.
    """
    results: list[TestResult] = []
    with open(path, "rb") as fh:
        for item in ijson.items(fh, "results.item"):
            status = item.get("status") or "skip"
            if status not in _STATUS_VALUES:
                status = "skip"
            duration = item.get("duration")
            results.append(
                TestResult(
                    full_id=item.get("full_id") or item.get("id") or "unknown",
                    name=item.get("name") or item.get("full_id") or "Unnamed test",
                    category=item.get("category") or "Uncategorized",
                    status=status,
                    outcome=item.get("outcome") or status,
                    # ijson yields Decimal for numbers; JSON-serialize as float.
                    duration=float(duration) if duration is not None else None,
                )
            )
    return results


def infer_image_type(testplan_id: str | None) -> str | None:
    """Best-effort fallback if the caller ever omits --image explicitly."""
    if not testplan_id:
        return None
    lowered = testplan_id.lower()
    if "desktop" in lowered:
        return "desktop"
    if "server" in lowered:
        return "server"
    return None


def parse_session_timestamp(path: str | Path) -> str | None:
    """Extract the real test-run timestamp embedded in Checkbox's launcher
    session description (e.g. ``PE-Images-202609010742-...`` ->
    2026-09-01T07:42:00+00:00), used as a fallback when --timestamp isn't
    given explicitly."""
    with open(path, "rb") as fh:
        for value in ijson.items(fh, "launcher.launcher.session_desc"):
            if not value:
                continue
            m = _SESSION_TIMESTAMP_RE.search(str(value))
            if m:
                dt = datetime.strptime(m.group(1), "%Y%m%d%H%M").replace(tzinfo=UTC)
                return dt.isoformat()
    return None
