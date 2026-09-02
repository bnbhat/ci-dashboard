from __future__ import annotations

from pathlib import Path

from ci_dashboard.imageconfig import ImagesConfig, classify_ignored, short_test_id

FIXTURE = Path(__file__).parent.parent / "fixtures" / "images.yaml"


def test_short_test_id_strips_namespace():
    assert short_test_id("com.canonical.certification::acpi/oem_osi") == "acpi/oem_osi"
    assert short_test_id("no_namespace_id") == "no_namespace_id"


def test_devices_are_parsed_from_queues():
    config = ImagesConfig.from_file(FIXTURE)
    devices = {d.cid: d for d in config.devices()}
    assert set(devices) == {"202509-37951", "202605-38792"}

    d1 = devices["202509-37951"]
    assert d1.alias == "HAMOA-12C SIPA-64GB EVK IQX7181"
    assert d1.platform == "dragonwing"
    assert d1.series == "resolute"
    assert any("IQ-X.1.8" in f for f in d1.extra_files)


def test_device_info_lookup():
    config = ImagesConfig.from_file(FIXTURE)
    assert config.device_info("202605-38792").alias == "PURWA-8C SIPA-64GB EVK IQX5121"
    assert config.device_info("unknown-cid") is None


def test_ignore_rules_merge_platform_and_series_levels():
    config = ImagesConfig.from_file(FIXTURE)
    rules = config.ignore_rules_for("202509-37951", "desktop")
    patterns = {r.pattern for r in rules}
    # platform-level rule
    assert "miscellanea/check_prerelease" in patterns
    # series-level rule
    assert "camera/.*" in patterns


def test_ignore_rules_for_unknown_device_is_empty():
    config = ImagesConfig.from_file(FIXTURE)
    assert config.ignore_rules_for("does-not-exist", "desktop") == []


def test_classify_ignored_matches_platform_rule():
    config = ImagesConfig.from_file(FIXTURE)
    rules = config.ignore_rules_for("202509-37951", "desktop")
    status, reason = classify_ignored(
        "com.canonical.certification::miscellanea/check_prerelease", "fail", rules
    )
    assert status == "failed-ignored"
    assert "devel kernel" in reason


def test_classify_ignored_matches_wildcard_series_rule():
    config = ImagesConfig.from_file(FIXTURE)
    rules = config.ignore_rules_for("202509-37951", "desktop")
    status, reason = classify_ignored(
        "com.canonical.qa.carmel::carmel-video/transform-rotate-180-automated", "fail", rules
    )
    assert status == "failed-ignored"
    assert "2154814" in reason


def test_classify_ignored_leaves_unmatched_fail_alone():
    config = ImagesConfig.from_file(FIXTURE)
    rules = config.ignore_rules_for("202509-37951", "desktop")
    status, reason = classify_ignored(
        "com.canonical.certification::some_other_test", "fail", rules
    )
    assert status == "fail"
    assert reason is None


def test_classify_ignored_only_applies_to_fail_status():
    config = ImagesConfig.from_file(FIXTURE)
    rules = config.ignore_rules_for("202509-37951", "desktop")
    status, reason = classify_ignored(
        "com.canonical.certification::miscellanea/check_prerelease", "pass", rules
    )
    assert status == "pass"
    assert reason is None
