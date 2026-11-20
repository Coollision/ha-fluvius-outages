"""Binary sensor: is there an outage at the watched location right now?"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .entity import FluviusEntity, outage_attributes

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import FluviusConfigEntry
    from .coordinator import FluviusCoordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FluviusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor."""
    coordinator = entry.runtime_data
    async_add_entities([OutageSensor(coordinator), UpcomingOutageSensor(coordinator)])


class OutageSensor(FluviusEntity, BinarySensorEntity):
    """On while a planned or unplanned outage covers the location."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "outage"

    def __init__(self, coordinator: FluviusCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "outage")

    @property
    def is_on(self) -> bool:
        """Return whether an outage is under way."""
        return bool(self.coordinator.active())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Describe the outage that has been going on longest, and list them all.

        Fluvius can report several outages for one street at once; the headline
        attributes follow the oldest, ``outages`` holds every one.
        """
        coordinator = self.coordinator
        if not (active := coordinator.active()):
            return None
        return {
            **outage_attributes(coordinator, active[0]),
            "outage_count": len(active),
            "outages": [outage_attributes(coordinator, o) for o in active],
        }


class UpcomingOutageSensor(FluviusEntity, BinarySensorEntity):
    """On while planned works are announced for the location but have not begun.

    Use it to be warned ahead of time; the "Days ahead" setting decides how early.
    """

    _attr_translation_key = "outage_upcoming"

    def __init__(self, coordinator: FluviusCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "outage_upcoming")

    @property
    def is_on(self) -> bool:
        """Return whether a planned outage is still to come."""
        return self.coordinator.next_planned() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Describe the next planned outage, and list every announced one.

        A new announcement changes ``upcoming_count`` even while the sensor stays
        on, so an automation can trigger on that attribute.
        """
        coordinator = self.coordinator
        if not (upcoming := coordinator.upcoming_planned()):
            return None
        return {
            **outage_attributes(coordinator, upcoming[0]),
            "upcoming_count": len(upcoming),
            "upcoming": [outage_attributes(coordinator, o) for o in upcoming],
        }
