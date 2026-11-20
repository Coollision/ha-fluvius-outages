"""Every language has the same keys and placeholders as English."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

TRANSLATIONS = (
    Path(__file__).parents[1] / "custom_components/fluvius_outages/translations"
)
LANGUAGES = sorted(path.stem for path in TRANSLATIONS.glob("*.json"))

REQUIRED = [
    "config.step.user.title",
    "config.step.user.description",
    "config.step.user.data.postcode",
    "config.step.user.data.street",
    "config.step.user.data_description.street",
    "config.step.user.data_description.postcode",
    "config.step.user.data.resolved_hours",
    "config.step.user.data_description.resolved_hours",
    "config.step.user.data.lookahead_days",
    "config.step.user.data_description.lookahead_days",
    "config.error.invalid_postcode",
    "config.error.cannot_connect",
    "config.abort.already_configured",
    "options.step.init.title",
    "options.step.init.data.postcode",
    "options.step.init.data.street",
    "options.step.init.data_description.street",
    "options.error.invalid_postcode",
    "options.step.init.data.resolved_hours",
    "options.step.init.data_description.resolved_hours",
    "options.step.init.data.lookahead_days",
    "options.step.init.data_description.lookahead_days",
    "options.step.init.data.scan_interval",
    "entity.binary_sensor.outage.name",
    "entity.binary_sensor.outage_upcoming.name",
    "entity.sensor.next_planned_outage.name",
    "entity.sensor.restoration_time.name",
    "entity.sensor.last_resolved_outage.name",
    "entity.calendar.outages.name",
]
PLACEHOLDERS = {"options.step.init.title": {"postcode"}}


def _load(language: str) -> dict:
    return json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))


def _leaves(node: dict, prefix: str = "") -> dict[str, str]:
    leaves: dict[str, str] = {}
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            leaves.update(_leaves(value, path))
        else:
            leaves[path] = value
    return leaves


def test_english_exists() -> None:
    """English is the fallback and must exist."""
    assert "en" in LANGUAGES


@pytest.mark.parametrize("language", LANGUAGES)
def test_required_keys_exist(language: str) -> None:
    """Every key the integration can emit has a text."""
    leaves = _leaves(_load(language))
    assert not [key for key in REQUIRED if not leaves.get(key)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_same_keys_as_english(language: str) -> None:
    """No language lacks or adds keys."""
    assert _leaves(_load(language)).keys() == _leaves(_load("en")).keys()


@pytest.mark.parametrize("language", LANGUAGES)
def test_placeholders_match(language: str) -> None:
    """Texts use the placeholders the code passes."""
    leaves = _leaves(_load(language))
    for key, expected in PLACEHOLDERS.items():
        assert set(re.findall(r"{(\w+)}", leaves[key])) == expected, key
