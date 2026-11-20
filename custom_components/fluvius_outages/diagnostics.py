"""Diagnostics, without the address."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data

from .const import CONF_POSTCODE, CONF_STREETS

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import FluviusConfigEntry

TO_REDACT = {CONF_POSTCODE, CONF_STREETS}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FluviusConfigEntry
) -> dict[str, Any]:
    """Return what helps to debug, with the watched location redacted."""
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data({**entry.data, **entry.options}, TO_REDACT),
        "last_update_success": coordinator.last_update_success,
        "matching_outages": [
            {
                "type": o.type,
                "start": o.start.isoformat(),
                "end": o.end.isoformat() if o.end else None,
                "customers_affected": o.customers_affected,
                "customers_restored": o.customers_restored,
            }
            for o in coordinator.outages
        ],
    }
