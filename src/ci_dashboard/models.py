"""Data models for the CI dashboard.

Only the fields needed to render the dashboard are kept. Per project
requirements, test *output* (io_log / comments) is intentionally never
stored — only the test name/id and its outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TestResult:
    """A single Checkbox job result, stripped of any log/output content."""

    full_id: str
    name: str
    category: str
    status: str  # "pass" | "fail" | "skip" | "failed-ignored"
    outcome: str  # e.g. "pass", "fail", "skipped-dependency", "skipped-resource"
    duration: float | None = None
    ignore_reason: str | None = None  # set when status == "failed-ignored"


@dataclass(frozen=True, slots=True)
class PackageInfo:
    """A single installed .deb package (name + version only)."""

    name: str
    version: str | None = None


@dataclass(frozen=True, slots=True)
class SnapPackageInfo:
    """A single installed snap package."""

    name: str
    version: str | None = None
    channel: str | None = None
    revision: str | None = None


@dataclass(frozen=True, slots=True)
class RunMeta:
    """Metadata for a single test-run submission, supplied by the calling
    CI job (device CID + image type are not reliably present inside
    submission.json itself, so they are passed in explicitly)."""

    run_id: str
    device_cid: str
    image_type: str  # "desktop" | "server"
    testplan_id: str
    distribution: str
    timestamp: str  # ISO-8601 UTC, assigned at ingest time
    results: list[TestResult] = field(default_factory=list)
    device_alias: str | None = None
    platform: str | None = None
    series: str | None = None
    submission_id: str | None = None
    checkbox_version: str | None = None
    kernel: str | None = None
    architecture: str | None = None
    distribution_codename: str | None = None
    distribution_release: str | None = None
    packages: list[PackageInfo] = field(default_factory=list)
    snap_packages: list[SnapPackageInfo] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        counts = {"pass": 0, "fail": 0, "skip": 0, "failed-ignored": 0}
        for r in self.results:
            counts[r.status] = counts.get(r.status, 0) + 1
        return counts
