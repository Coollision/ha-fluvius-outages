"""Tests for the config and options flows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.fluvius_outages.const import (
    API_URL,
    CONF_LOOKAHEAD_DAYS,
    CONF_POSTCODE,
    CONF_SCAN_INTERVAL,
    CONF_STREETS,
    CONF_WERFCODES,
    DOMAIN,
    PAGE_URL,
)

from .conftest import PAGE, record, serve

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )


async def _start(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_creates_an_entry(
    hass: HomeAssistant, fluvius: AiohttpClientMocker
) -> None:
    """Postcode, streets and work codes end up in the entry; blanks are dropped."""
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_POSTCODE: " 9000 ",
            CONF_STREETS: ["Teststraat", "  ", "Voorbeeldweg "],
            CONF_WERFCODES: ["400001"],
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "9000 Teststraat, Voorbeeldweg"
    assert result["data"] == {
        CONF_POSTCODE: "9000",
        CONF_STREETS: ["Teststraat", "Voorbeeldweg"],
        CONF_WERFCODES: ["400001"],
        CONF_LOOKAHEAD_DAYS: 7,
    }


async def test_postcode_only(hass: HomeAssistant, fluvius: AiohttpClientMocker) -> None:
    """Streets are optional: the whole postcode can be watched."""
    result = await hass.config_entries.flow.async_configure(
        (await _start(hass))["flow_id"], {CONF_POSTCODE: "9000"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "9000"
    assert result["data"][CONF_STREETS] == []


@pytest.mark.parametrize("postcode", ["900", "90000", "abcd", ""])
async def test_rejects_invalid_postcode(
    hass: HomeAssistant, fluvius: AiohttpClientMocker, postcode: str
) -> None:
    """Anything but four digits is refused before Fluvius is asked."""
    result = await hass.config_entries.flow.async_configure(
        (await _start(hass))["flow_id"], {CONF_POSTCODE: postcode}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_POSTCODE: "invalid_postcode"}


async def test_cannot_connect(
    hass: HomeAssistant, fluvius: AiohttpClientMocker
) -> None:
    """A Fluvius outage is reported and the form stays open."""
    fluvius.clear_requests()
    fluvius.get(PAGE_URL, text=PAGE)
    fluvius.get(API_URL, status=500)

    result = await hass.config_entries.flow.async_configure(
        (await _start(hass))["flow_id"], {CONF_POSTCODE: "9000"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_same_location_twice_aborts(
    hass: HomeAssistant, fluvius: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    """The same postcode and street cannot be added twice, however it is spelled."""
    result = await hass.config_entries.flow.async_configure(
        (await _start(hass))["flow_id"],
        {CONF_POSTCODE: "9000", CONF_STREETS: ["TESTSTRAAT"]},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_change_streets_and_reload(
    hass: HomeAssistant, fluvius: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    """Changing the options reloads the entry with the new location."""
    serve(fluvius, record(streets=("ANDERSTRAAT",)))
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.9000_teststraat_power_outage").state == "off"

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_STREETS: ["Anderstraat"],
            CONF_WERFCODES: [],
            CONF_LOOKAHEAD_DAYS: 3,
            CONF_SCAN_INTERVAL: 900,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.runtime_data.location.streets == ("Anderstraat",)
    assert entry.runtime_data.update_interval.total_seconds() == 900
    assert entry.runtime_data.lookahead.days == 3


async def test_options_reject_too_frequent_polling(
    hass: HomeAssistant, fluvius: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    """Hammering Fluvius is not offered."""
    await hass.config_entries.async_setup(entry.entry_id)
    result = await hass.config_entries.options.async_init(entry.entry_id)

    with pytest.raises(Exception, match=r"scan_interval|value must be at least"):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SCAN_INTERVAL: 10}
        )


async def test_lookahead_is_chosen_in_setup(
    hass: HomeAssistant, fluvius: AiohttpClientMocker
) -> None:
    """The window is part of the setup form; 0 means only what is happening now."""
    result = await hass.config_entries.flow.async_configure(
        (await _start(hass))["flow_id"],
        {CONF_POSTCODE: "9000", CONF_LOOKAHEAD_DAYS: 0},
    )

    assert result["data"][CONF_LOOKAHEAD_DAYS] == 0


async def test_lookahead_cannot_exceed_what_fluvius_serves(
    hass: HomeAssistant, fluvius: AiohttpClientMocker
) -> None:
    """More than 14 days is refused by the form itself."""
    result = await _start(hass)

    with pytest.raises(Exception, match=r"lookahead_days|at most"):
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_POSTCODE: "9000", CONF_LOOKAHEAD_DAYS: 30}
        )
