"""Fluvius outages: planned and unplanned power outages at your address."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration

from .api import FluviusApi
from .const import CONF_POSTCODE, CONF_STREETS, DOMAIN
from .coordinator import FluviusCoordinator
from .matching import Location

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CALENDAR, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type FluviusConfigEntry = ConfigEntry[FluviusCoordinator]


def location_from_entry(entry: ConfigEntry) -> Location:
    """Build the watched location; options (when set) win over the original setup."""
    merged = {**entry.data, **entry.options}
    return Location(
        postcode=merged[CONF_POSTCODE],
        streets=tuple(merged.get(CONF_STREETS, ())),
    )


async def async_setup_entry(hass: HomeAssistant, entry: FluviusConfigEntry) -> bool:
    """Set up a watched location."""
    integration = await async_get_integration(hass, DOMAIN)
    api = FluviusApi(
        async_get_clientsession(hass),
        f"HomeAssistant-FluviusOutages/{integration.version}",
    )
    coordinator = FluviusCoordinator(hass, entry, api, location_from_entry(entry))
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FluviusConfigEntry) -> bool:
    """Unload a watched location."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
