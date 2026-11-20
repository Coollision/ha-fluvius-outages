"""End-to-end tests: setup, entities, time passing."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.fluvius_outages.const import (
    API_URL,
    CONF_LOOKAHEAD_DAYS,
    CONF_SCAN_INTERVAL,
    PAGE_URL,
)
from custom_components.fluvius_outages.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import PAGE, record, serve

if TYPE_CHECKING:
    from freezegun.api import FrozenDateTimeFactory
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )

OUTAGE = "binary_sensor.9000_teststraat_power_outage"
UPCOMING = "binary_sensor.9000_teststraat_planned_outage_upcoming"
NEXT = "sensor.9000_teststraat_next_planned_outage"
BACK = "sensor.9000_teststraat_power_expected_back"
CALENDAR = "calendar.9000_teststraat_outages"

# 2026-11-20 06:00 UTC = 07:00 local: half an hour before a 07:30 start.
BEFORE = "2026-11-20T06:00:00+00:00"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_quiet_day(
    hass: HomeAssistant,
    fluvius: AiohttpClientMocker,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """With nothing reported everything is off or unknown."""
    freezer.move_to(BEFORE)
    await _setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(OUTAGE).state == "off"
    assert hass.states.get(UPCOMING).state == "off"
    assert hass.states.get(NEXT).state == "unknown"
    assert hass.states.get(BACK).state == "unknown"


async def _setup_slow_polling(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Poll hourly, so only the start/end timer can explain a state change."""
    hass.config_entries.async_update_entry(entry, options={CONF_SCAN_INTERVAL: 3600})
    await _setup(hass, entry)


async def test_planned_outage_turns_on_at_its_start(
    hass: HomeAssistant,
    fluvius: AiohttpClientMocker,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The sensor turns on at 07:30 local, without another poll."""
    serve(fluvius, record())
    freezer.move_to(BEFORE)
    await _setup_slow_polling(hass, entry)
    calls = len(fluvius.mock_calls)

    assert hass.states.get(OUTAGE).state == "off"
    assert hass.states.get(UPCOMING).state == "on"
    assert hass.states.get(UPCOMING).attributes["cities"] == ["GENT - GENT"]
    assert hass.states.get(NEXT).state == "2026-11-20T06:30:00+00:00"
    assert hass.states.get(NEXT).attributes["customers_affected"] == 18

    freezer.move_to("2026-11-20T06:31:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(OUTAGE)
    assert state.state == "on"
    assert state.attributes["type"] == "planned"
    assert state.attributes["streets"] == ["TESTSTRAAT", "VOORBEELDWEG"]
    assert hass.states.get(UPCOMING).state == "off"  # it has begun
    assert hass.states.get(BACK).state == "2026-11-20T15:00:00+00:00"
    assert hass.states.get(NEXT).state == "unknown"
    assert len(fluvius.mock_calls) == calls  # the timer noticed, not a poll


async def test_planned_outage_turns_off_at_its_end(
    hass: HomeAssistant,
    fluvius: AiohttpClientMocker,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The sensor turns off at 16:00 local, without another poll."""
    serve(fluvius, record())
    freezer.move_to("2026-11-20T14:30:00+00:00")
    await _setup_slow_polling(hass, entry)
    calls = len(fluvius.mock_calls)
    assert hass.states.get(OUTAGE).state == "on"

    freezer.move_to("2026-11-20T15:01:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(OUTAGE).state == "off"
    assert hass.states.get(BACK).state == "unknown"
    assert len(fluvius.mock_calls) == calls


async def test_unplanned_outage_without_end(
    hass: HomeAssistant,
    fluvius: AiohttpClientMocker,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An unplanned outage is on right away and has no restoration time."""
    serve(
        fluvius,
        record(planned=False, start="2026-11-20T07:00:00+01:00", end=None, restored=3),
    )
    freezer.move_to("2026-11-20T06:30:00+00:00")
    await _setup(hass, entry)

    state = hass.states.get(OUTAGE)
    assert state.state == "on"
    assert state.attributes["type"] == "unplanned"
    assert state.attributes["customers_restored"] == 3
    assert hass.states.get(BACK).state == "unknown"


async def test_other_streets_and_postcodes_are_ignored(
    hass: HomeAssistant,
    fluvius: AiohttpClientMocker,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Outages elsewhere do not turn the sensor on."""
    serve(
        fluvius,
        record(werfcode="1", streets=("ANDERSTRAAT",)),
        record(werfcode="2", postcode="9100"),
    )
    freezer.move_to("2026-11-20T06:31:00+00:00")
    await _setup(hass, entry)

    assert hass.states.get(OUTAGE).state == "off"
    assert hass.states.get(CALENDAR).state == "off"


async def test_calendar_lists_the_outage(
    hass: HomeAssistant,
    fluvius: AiohttpClientMocker,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The calendar entity shows the announced outage."""
    serve(fluvius, record())
    freezer.move_to(BEFORE)
    await _setup(hass, entry)

    state = hass.states.get(CALENDAR)
    assert state.attributes["message"] == "Planned power outage"
    assert "400001" in state.attributes["description"]
    events = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": CALENDAR,
            "start_date_time": "2026-11-20T00:00:00+00:00",
            "end_date_time": "2026-11-21T00:00:00+00:00",
        },
        blocking=True,
        return_response=True,
    )
    assert len(events[CALENDAR]["events"]) == 1


async def test_entities_have_stable_unique_ids(
    hass: HomeAssistant, fluvius: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    """Unique ids are built from the entry, so renaming never duplicates entities."""
    await _setup(hass, entry)

    registry = er.async_get(hass)
    ids = {
        e.unique_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert ids == {
        f"{entry.entry_id}_{key}"
        for key in (
            "outage",
            "outage_upcoming",
            "next_planned_outage",
            "restoration_time",
            "calendar",
        )
    }


async def test_unavailable_when_fluvius_fails_then_recovers(
    hass: HomeAssistant,
    fluvius: AiohttpClientMocker,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A failed poll makes entities unavailable; the next good one restores them."""
    freezer.move_to(BEFORE)
    await _setup(hass, entry)
    fluvius.clear_requests()
    fluvius.get(PAGE_URL, text=PAGE)
    fluvius.get(API_URL, status=500)

    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(OUTAGE).state == "unavailable"

    serve(fluvius)
    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(OUTAGE).state == "off"


async def test_setup_retries_when_fluvius_is_down(
    hass: HomeAssistant, fluvius: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    """If Fluvius is down at startup Home Assistant retries by itself."""
    fluvius.clear_requests()
    fluvius.get(PAGE_URL, text=PAGE)
    fluvius.get(API_URL, status=500)

    await _setup(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_diagnostics_hide_the_address(
    hass: HomeAssistant, fluvius: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    """Diagnostics never contain the postcode, streets or work codes."""
    serve(fluvius, record())
    await _setup(hass, entry)

    data = await async_get_config_entry_diagnostics(hass, entry)

    assert "9000" not in str(data["entry"])
    assert "Teststraat" not in str(data["entry"])
    assert data["entry"]["postcode"] == "**REDACTED**"


@pytest.mark.parametrize(
    ("days", "expected_next"),
    [
        (0, "unknown"),  # only what is happening now
        (3, "unknown"),  # the planned work is 5 days out
        (7, "2026-11-25T06:30:00+00:00"),
    ],
)
async def test_lookahead_limits_planned_works(
    hass: HomeAssistant,
    fluvius: AiohttpClientMocker,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    days: int,
    expected_next: str,
) -> None:
    """Planned works beyond the window are not reported yet."""
    serve(
        fluvius,
        record(start="2026-11-25T07:30:00+01:00", end="2026-11-25T16:00:00+01:00"),
    )
    freezer.move_to(BEFORE)
    hass.config_entries.async_update_entry(entry, options={CONF_LOOKAHEAD_DAYS: days})

    await _setup(hass, entry)

    assert hass.states.get(NEXT).state == expected_next
    until = fluvius.mock_calls[-1][1].query["DateUntil"]
    assert until == f"{(datetime(2026, 11, 20) + timedelta(days=days)).date()}T23:59:59"


async def test_zero_days_still_reports_what_is_happening_now(
    hass: HomeAssistant,
    fluvius: AiohttpClientMocker,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """With 0 days ahead a current outage is still reported, planned or not."""
    serve(
        fluvius,
        record(werfcode="1"),
        record(
            werfcode="2", planned=False, start="2026-11-20T08:00:00+01:00", end=None
        ),
    )
    freezer.move_to("2026-11-20T08:00:00+00:00")
    hass.config_entries.async_update_entry(entry, options={CONF_LOOKAHEAD_DAYS: 0})

    await _setup(hass, entry)

    assert hass.states.get(OUTAGE).state == "on"
    assert len(entry.runtime_data.outages) == 2
