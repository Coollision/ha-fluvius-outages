"""Fixtures for the Fluvius outages tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_SCAN_INTERVAL  # noqa: F401
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fluvius_outages.const import (
    API_URL,
    CONF_POSTCODE,
    CONF_STREETS,
    CONF_WERFCODES,
    DOMAIN,
    PAGE_URL,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )

KEY = "0123456789abcdef0123456789abcdef"
PAGE = f'<script>{{"fluvius_onderbrekingen":{{"subscription_key":"{KEY}"}}}}</script>'


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow loading the integration from custom_components."""


def record(
    *,
    werfcode: str = "400001",
    planned: bool = True,
    start: str = "2026-11-20T07:30:00+01:00",
    end: str | None = "2026-11-20T16:00:00+01:00",
    postcode: str = "9000",
    streets: tuple[str, ...] = ("TESTSTRAAT", "VOORBEELDWEG"),
    affected: int = 18,
    restored: int = 0,
) -> dict[str, Any]:
    """Return an API record shaped like the real ones."""
    item: dict[str, Any] = {
        "startDateTime": start,
        "id": f"id-{werfcode}",
        "gonId": werfcode,
        "interruptionType": "Planned" if planned else "Unplanned",
        "eventType": "Update",
        "lastUpdateReceivedOn": "2026-11-03T11:29:14.2581039",
        "numberOfAffectedCustomers": affected,
        "numberOfRestoredCustomers": restored,
        "impactedAreas": [
            {
                "city": "GENT - GENT",
                "zipCode": postcode,
                "latitude": 51.0,
                "longitude": 3.7,
                "affectedStreets": list(streets),
            }
        ],
    }
    if end:
        item["endDateTime"] = end
    return item


@pytest.fixture
def fluvius(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Serve the outage page and an (empty) interruptions list."""
    aioclient_mock.get(PAGE_URL, text=PAGE)
    aioclient_mock.get(API_URL, json={"interruptions": []})
    return aioclient_mock


def serve(mocker: AiohttpClientMocker, *records: dict[str, Any]) -> None:
    """Replace the interruptions the API returns."""
    mocker.clear_requests()
    mocker.get(PAGE_URL, text=PAGE)
    mocker.get(API_URL, json={"interruptions": list(records)})


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    """Provide a config entry watching a street in postcode 9000."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="9000 Teststraat",
        unique_id="9000|teststraat|",
        data={
            CONF_POSTCODE: "9000",
            CONF_STREETS: ["Teststraat"],
            CONF_WERFCODES: [],
        },
    )
    config_entry.add_to_hass(hass)
    return config_entry
