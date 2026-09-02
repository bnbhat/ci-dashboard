"""CLI entry point: ``ci-dashboard ingest submission.json --device ... --image ...``

Designed to be invoked from a GitHub Actions job in the same workflow as
the device's Checkbox test run, after checking out the dedicated ``data``
branch into e.g. ``./data-branch`` (or ``docs/data`` directly on that
branch's worktree).
"""

from __future__ import annotations

import re
import sys
import tarfile
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import click

from ci_dashboard.aggregator import (
    DEFAULT_RETENTION_DAYS,
    ingest_run,
    rebuild_compare_matrix,
    rebuild_test_index,
    register_known_devices,
)
from ci_dashboard.imageconfig import ImagesConfig, classify_ignored
from ci_dashboard.models import PackageInfo, RunMeta, SnapPackageInfo, TestResult
from ci_dashboard.parser import (
    infer_image_type,
    parse_packages,
    parse_results,
    parse_session_timestamp,
    parse_snap_packages,
    parse_top_level_meta,
)

# Matches e.g. "submission_202403-33871_508607.tar.xz" -> cid="202403-33871",
# submission_id="508607". Device CIDs are always "<yyyymm>-<serial>".
_ARCHIVE_NAME_RE = re.compile(r"submission_(?P<cid>[^_]+)_(?P<submission_id>\d+)\.tar\.(?:xz|gz|bz2)$")

_ARCHIVE_SUFFIXES = {".tar", ".xz", ".gz", ".bz2", ".tgz", ".txz"}


def parse_archive_filename(path: Path) -> tuple[str, str] | None:
    """Best-effort extraction of (device_cid, submission_id) from a
    ``submission_<CID>_<SUBMISSION_ID>.tar.xz``-style filename."""
    m = _ARCHIVE_NAME_RE.match(path.name)
    if not m:
        return None
    return m.group("cid"), m.group("submission_id")


def _is_archive(path: Path) -> bool:
    return any(suffix in _ARCHIVE_SUFFIXES for suffix in path.suffixes[-2:])


@contextmanager
def _resolve_submission_json(path: Path) -> Iterator[Path]:
    """If ``path`` is a tar archive, extract its ``submission.json`` member
    to a temp file and yield that path; otherwise yield ``path`` unchanged."""
    if not _is_archive(path):
        yield path
        return
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(path) as tar:
            tar.extract("submission.json", path=tmp, filter="data")
        yield Path(tmp) / "submission.json"


@click.group()
def main() -> None:
    """ci-dashboard: parse Checkbox submission.json files into the static
    dashboard's JSON data store."""


@main.command()
@click.argument("submission_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--device",
    "device_cid",
    default=None,
    help="Device CID identifying the physical test machine. Auto-detected from the "
    "filename when SUBMISSION_PATH is a 'submission_<CID>_<SUBMISSION_ID>.tar.xz' archive.",
)
@click.option(
    "--image",
    "image_type",
    default=None,
    type=click.Choice(["desktop", "server"], case_sensitive=False),
    help="Image type under test. Auto-detected from testplan_id when omitted.",
)
@click.option(
    "--submission-id",
    default=None,
    help="Submission ID for this run. Auto-detected from the archive filename when omitted.",
)
@click.option("--run-id", default=None, help="Unique run identifier. Defaults to '<device>-<image>-<utc timestamp>'.")
@click.option("--timestamp", default=None, help="ISO-8601 UTC run timestamp. Defaults to now.")
@click.option(
    "--data-dir",
    default="docs/data",
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory (normally the checked-out 'data' branch) to write JSON into.",
)
@click.option(
    "--retention-days",
    default=DEFAULT_RETENTION_DAYS,
    type=int,
    help="Drop history entries older than this many days.",
)
@click.option(
    "--images-yaml",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help=(
        "Path to images.yaml. When given, its ignored_tests are used to "
        "reclassify expected failures as 'failed-ignored', and its "
        "queues[] provide device alias/platform/series metadata."
    ),
)
def ingest(
    submission_path: Path,
    device_cid: str | None,
    image_type: str | None,
    submission_id: str | None,
    run_id: str | None,
    timestamp: str | None,
    data_dir: Path,
    retention_days: int,
    images_yaml: Path | None,
) -> None:
    """Parse SUBMISSION_PATH (a raw submission.json, or a
    'submission_<CID>_<SUBMISSION_ID>.tar.xz' archive as produced by
    Checkbox) and merge it into the dashboard's data store.

    Only test id/name/category/status/outcome/duration are extracted from
    results — test output (io_log/comments) is never read or stored.
    Package name/version lists (deb + snap) ARE stored, to help correlate
    test regressions with package/kernel changes.
    """
    detected = parse_archive_filename(submission_path)
    if detected:
        detected_cid, detected_submission_id = detected
        device_cid = device_cid or detected_cid
        submission_id = submission_id or detected_submission_id
    if not device_cid:
        raise click.UsageError(
            "--device is required (could not auto-detect it from the filename; "
            "expected 'submission_<CID>_<SUBMISSION_ID>.tar.xz')."
        )

    with _resolve_submission_json(submission_path) as submission_json:
        click.echo(f"Parsing {submission_path} ...", err=True)
        top_meta = parse_top_level_meta(submission_json)

        image = (image_type or infer_image_type(top_meta.get("testplan_id")) or "").lower()
        if not image:
            raise click.UsageError(
                "--image is required (could not auto-detect desktop/server from testplan_id "
                f"'{top_meta.get('testplan_id')}')."
            )
        if image_type and infer_image_type(top_meta.get("testplan_id")) not in (None, image):
            click.echo(
                f"Warning: --image={image} but testplan_id suggests "
                f"'{infer_image_type(top_meta.get('testplan_id'))}'.",
                err=True,
            )

        results = parse_results(submission_json)
        click.echo(f"Parsed {len(results)} test results.", err=True)

        packages = [PackageInfo(**p) for p in parse_packages(submission_json)]
        snap_packages = [SnapPackageInfo(**p) for p in parse_snap_packages(submission_json)]
        click.echo(
            f"Parsed {len(packages)} deb package(s), {len(snap_packages)} snap package(s).",
            err=True,
        )

        now = datetime.now(UTC).isoformat()
        ts = timestamp or parse_session_timestamp(submission_json) or now
        rid = (
            run_id
            or f"{device_cid}-{image}-{ts[:19].replace(':', '').replace('-', '')}-{uuid.uuid4().hex[:6]}"
        )

        device_alias = platform = series = None
        images_config = None
        if images_yaml is not None:
            images_config = ImagesConfig.from_file(images_yaml)
            device_info = images_config.device_info(device_cid)
            if device_info is None:
                click.echo(
                    f"Warning: device '{device_cid}' not found in {images_yaml} — "
                    "no alias/ignore-list will be applied.",
                    err=True,
                )
            else:
                device_alias, platform, series = device_info.alias, device_info.platform, device_info.series

            rules = images_config.ignore_rules_for(device_cid, image)
            ignored_count = 0
            reclassified: list[TestResult] = []
            for r in results:
                new_status, reason = classify_ignored(r.full_id, r.status, rules)
                if new_status != r.status:
                    ignored_count += 1
                    reclassified.append(
                        TestResult(
                            full_id=r.full_id,
                            name=r.name,
                            category=r.category,
                            status=new_status,
                            outcome=r.outcome,
                            duration=r.duration,
                            ignore_reason=reason,
                        )
                    )
                else:
                    reclassified.append(r)
            results = reclassified
            if ignored_count:
                click.echo(
                    f"Reclassified {ignored_count} known-failing test(s) as 'failed-ignored' "
                    f"per {images_yaml}.",
                    err=True,
                )

        run = RunMeta(
            run_id=rid,
            device_cid=device_cid,
            image_type=image,
            testplan_id=top_meta.get("testplan_id") or "unknown",
            distribution=top_meta.get("distribution") or "unknown",
            timestamp=ts,
            results=results,
            device_alias=device_alias,
            platform=platform,
            series=series,
            submission_id=submission_id,
            checkbox_version=top_meta.get("checkbox_version"),
            kernel=top_meta.get("kernel"),
            architecture=top_meta.get("architecture"),
            distribution_codename=top_meta.get("distribution_codename"),
            distribution_release=top_meta.get("distribution_release"),
            packages=packages,
            snap_packages=snap_packages,
        )

        ingest_run(data_dir, run, retention_days=retention_days)
        if images_config is not None:
            # Register the full device roster (including devices that have never
            # submitted a run yet) so they still show up in the dashboard.
            register_known_devices(
                data_dir,
                [
                    {"cid": d.cid, "alias": d.alias, "platform": d.platform, "series": d.series}
                    for d in images_config.devices()
                ],
            )
        rebuild_test_index(data_dir)
        rebuild_compare_matrix(data_dir)
        click.echo(f"Ingested run '{rid}' for device={device_cid} image={image}.", err=True)


@main.command("sync-devices")
@click.option(
    "--images-yaml",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to images.yaml. Registers every device it declares.",
)
@click.option(
    "--data-dir",
    default="docs/data",
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory (normally the checked-out 'data' branch) to write JSON into.",
)
def sync_devices(images_yaml: Path, data_dir: Path) -> None:
    """Register every device declared in IMAGES_YAML into manifest.json,
    even ones that have never submitted a run yet. Useful to run once (or
    on a schedule) so the dashboard's Devices section always lists the
    full lab fleet, independent of ingest activity."""
    images_config = ImagesConfig.from_file(images_yaml)
    devices = images_config.devices()
    register_known_devices(
        data_dir,
        [{"cid": d.cid, "alias": d.alias, "platform": d.platform, "series": d.series} for d in devices],
    )
    click.echo(f"Registered {len(devices)} device(s) from {images_yaml}.", err=True)


if __name__ == "__main__":
    sys.exit(main())
