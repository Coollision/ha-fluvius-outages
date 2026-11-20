"""Shared entity base."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONFIGURATION_URL, DOMAIN
from .coordinator import FluviusCoordinator

if TYPE_CHECKING:
    from .matching import Outage


class FluviusEntity(CoordinatorEntity[FluviusCoordinator]):
    """An entity of one watched location."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FluviusCoordinator, key: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Fluvius",
            model="Outage monitor",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=CONFIGURATION_URL,
        )


def outage_attributes(coordinator: FluviusCoordinator, outage: Outage) -> dict:
    """Describe an outage for entity attributes."""
    return {
        "type": outage.type,
        "start": outage.start.isoformat(),
        "end": outage.end.isoformat() if outage.end else None,
        "werfcode": outage.werfcode,
        "customers_affected": outage.customers_affected,
        "customers_restored": outage.customers_restored,
        "streets": list(coordinator.location.touched_streets(outage)),
        "cities": sorted(
            {
                a.city
                for a in outage.areas
                if a.postcode == coordinator.location.postcode
            }
        ),
    }
