"""Parser for ``images.yaml`` — the CI's image/test-plan configuration.

This file is the source of truth for:

* **Devices**: each ``platforms.<platform>.series.<series>.testing.queues[]``
  entry is one physical lab device (``name`` = device CID, ``alias`` =
  human-friendly name, ``extra_files`` = boot assets used for that device).
* **Ignore list**: ``ignored_tests`` blocks (each: a ``reason`` + a list of
  regex ``patterns`` matched against the short Checkbox test id, e.g.
  ``wireless/detect``) can appear at four levels, all of which apply
  cumulatively to a given device + image type:
    1. ``platforms.<platform>.testing.ignored_tests``            (platform-wide)
    2. ``platforms.<platform>.series.<series>.testing.ignored_tests``  (series-wide)
    3. ``...queues[].ignored_tests``                              (this device only)
    4. ``...configurations.<desktop|server>.testing.ignored_tests`` (image-type-wide)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """A physical lab device, as declared under a series' `testing.queues`."""

    cid: str
    alias: str
    platform: str
    series: str
    extra_files: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    reason: str
    pattern: str


def short_test_id(full_id: str) -> str:
    """``com.canonical.certification::acpi/oem_osi`` -> ``acpi/oem_osi``.

    Ignore-list patterns in images.yaml are written against this short form
    (no namespace prefix), matching Checkbox's own `id` field.
    """
    return full_id.split("::", 1)[-1]


def _flatten_ignored_tests(blocks: list[dict] | None) -> list[IgnoreRule]:
    rules: list[IgnoreRule] = []
    for block in blocks or []:
        reason = str(block.get("reason", "")).strip()
        for pattern in block.get("patterns", []) or []:
            rules.append(IgnoreRule(reason=reason, pattern=pattern))
    return rules


class ImagesConfig:
    """Parsed view of images.yaml, providing device listing and per-device/
    per-image-type ignore-rule resolution."""

    def __init__(self, raw: dict):
        self._raw = raw or {}
        self._devices: dict[str, DeviceInfo] = {}
        self._device_context: dict[str, tuple[str, str, dict]] = {}
        # platform_name -> (platform_dict, {series_name: series_dict})
        for platform_name, platform in (self._raw.get("platforms") or {}).items():
            for series_name, series in (platform.get("series") or {}).items():
                testing = series.get("testing") or {}
                for queue in testing.get("queues") or []:
                    cid = queue["name"]
                    self._devices[cid] = DeviceInfo(
                        cid=cid,
                        alias=queue.get("alias", cid),
                        platform=platform_name,
                        series=series_name,
                        extra_files=tuple(queue.get("extra_files") or ()),
                    )
                    self._device_context[cid] = (platform_name, series_name, queue)

    @classmethod
    def from_file(cls, path: str | Path) -> ImagesConfig:
        with open(path, encoding="utf-8") as fh:
            return cls(yaml.safe_load(fh))

    def devices(self) -> list[DeviceInfo]:
        return list(self._devices.values())

    def device_info(self, device_cid: str) -> DeviceInfo | None:
        return self._devices.get(device_cid)

    def ignore_rules_for(self, device_cid: str, image_type: str) -> list[IgnoreRule]:
        """Merge platform + series + queue + configuration(image_type) level
        ignored_tests for the given device. Returns [] if the device is
        unknown to this config (e.g. not yet declared in images.yaml)."""
        context = self._device_context.get(device_cid)
        if context is None:
            return []
        platform_name, series_name, queue = context
        platform = self._raw["platforms"][platform_name]
        series = platform["series"][series_name]
        series_testing = series.get("testing") or {}

        rules: list[IgnoreRule] = []
        rules += _flatten_ignored_tests((platform.get("testing") or {}).get("ignored_tests"))
        rules += _flatten_ignored_tests(series_testing.get("ignored_tests"))
        rules += _flatten_ignored_tests(queue.get("ignored_tests"))

        configurations = series.get("configurations") or {}
        image_config = configurations.get(image_type) or {}
        rules += _flatten_ignored_tests((image_config.get("testing") or {}).get("ignored_tests"))
        return rules


def classify_ignored(
    full_id: str, status: str, rules: list[IgnoreRule]
) -> tuple[str, str | None]:
    """If `status` is "fail" and the test's short id matches an ignore-list
    pattern, return ("failed-ignored", reason). Otherwise pass status
    through unchanged with no reason."""
    if status != "fail" or not rules:
        return status, None
    sid = short_test_id(full_id)
    for rule in rules:
        try:
            if re.fullmatch(rule.pattern, sid):
                return "failed-ignored", rule.reason
        except re.error:
            continue
    return status, None
