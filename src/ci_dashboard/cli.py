"""CLI entry point: ``ci-dashboard ingest submission.json --device ... --image ...``

Designed to be invoked from a GitHub Actions job in the same workflow as
the device's Checkbox test run, after checking out the dedicated ``data``
branch into e.g. ``./data-branch`` (or ``docs/data`` directly on that
branch's worktree).
"""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import click

from ci_dashboard.aggregator import (
    DEFAULT_RETENTION_DAYS,
    ingest_run,
    rebuild_compare_matrix,
    rebuild_test_index,
)
from ci_dashboard.imageconfig import ImagesConfig, classify_ignored
from ci_dashboard.models import RunMeta, TestResult
from ci_dashboard.parser import infer_image_type, parse_results, parse_top_level_meta


@click.group()
def main() -> None:
    """ci-dashboard: parse Checkbox submission.json files into the static
    dashboard's JSON data store."""


@main.command()
@click.argument("submission_json", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--device", "device_cid", required=True, help="Device CID identifying the physical test machine.")
@click.option(
    "--image",
    "image_type",
    required=True,
    type=click.Choice(["desktop", "server"], case_sensitive=False),
    help="Image type under test.",
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
    submission_json: Path,
    device_cid: str,
    image_type: str,
    run_id: str | None,
    timestamp: str | None,
    data_dir: Path,
    retention_days: int,
    images_yaml: Path | None,
) -> None:
    """Parse SUBMISSION_JSON and merge it into the dashboard's data store.

    Only test id/name/category/status/outcome/duration are extracted —
    test output (io_log/comments) is never read or stored.
    """
    now = datetime.now(UTC).isoformat()
    ts = timestamp or now
    rid = run_id or f"{device_cid}-{image_type}-{ts[:19].replace(':', '').replace('-', '')}-{uuid.uuid4().hex[:6]}"

    click.echo(f"Parsing {submission_json} ...", err=True)
    top_meta = parse_top_level_meta(submission_json)
    results = parse_results(submission_json)
    click.echo(f"Parsed {len(results)} test results.", err=True)

    image = image_type.lower()
    inferred = infer_image_type(top_meta.get("testplan_id"))
    if inferred and inferred != image:
        click.echo(
            f"Warning: --image={image} but testplan_id suggests '{inferred}'.",
            err=True,
        )

    device_alias = platform = series = None
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
    )

    ingest_run(data_dir, run, retention_days=retention_days)
    rebuild_test_index(data_dir)
    rebuild_compare_matrix(data_dir)
    click.echo(f"Ingested run '{rid}' for device={device_cid} image={image}.", err=True)


if __name__ == "__main__":
    sys.exit(main())
