from __future__ import annotations

from pathlib import Path

from ci_dashboard.cli import parse_archive_filename


def test_parse_archive_filename_extracts_cid_and_submission_id():
    assert parse_archive_filename(Path("submission_202403-33871_508607.tar.xz")) == (
        "202403-33871",
        "508607",
    )


def test_parse_archive_filename_supports_other_compressions():
    assert parse_archive_filename(Path("submission_202601-38369_508173.tar.gz")) == (
        "202601-38369",
        "508173",
    )


def test_parse_archive_filename_returns_none_for_non_matching_name():
    assert parse_archive_filename(Path("submission.json")) is None
    assert parse_archive_filename(Path("random.tar.xz")) is None
