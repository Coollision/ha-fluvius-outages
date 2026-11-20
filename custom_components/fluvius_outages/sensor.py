"""Sensors: next planned outage and expected restoration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity

from .entity import FluviusEntity, outage_attributes

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import FluviusConfigEntry
    from .coordinator import FluviusCoordinator
    from .matching import Outage

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FluviusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            NextPlannedOutage(coordinator),
            RestorationTime(coordinator),
            LastResolvedOutage(coordinator),
        ]
    )


class NextPlannedOutage(FluviusEntity, SensorEntity):
    """When the next planned outage at the location starts."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "next_planned_outage"

    def __init__(self, coordinator: FluviusCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "next_planned_outage")

    @property
    def _outage(self) -> Outage | None:
        return self.coordinator.next_planned()

    @property
    def native_value(self) -> datetime | None:
        """Return the start of the next planned outage."""
        return outage.start if (outage := self._outage) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Describe the outage."""
        if (outage := self._outage) is None:
            return None
        return outage_attributes(self.coordinator, outage)


class RestorationTime(FluviusEntity, SensorEntity):
    """When the power is expected back; unknown for an unplanned outage."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "restoration_time"

    def __init__(self, coordinator: FluviusCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "restoration_time")

    @property
    def native_value(self) -> datetime | None:
        """Return when all outages under way end; unknown if any has no end yet."""
        active = self.coordinator.active()
        if not active or any(o.end is None for o in active):
            return None
        return max(o.end for o in active if o.end)


class LastResolvedOutage(FluviusEntity, SensorEntity):
    """When power was last restored; the attributes say what the outage was.

    It forgets the outage after the configured number of hours, so it reads
    "unknown" on a quiet day.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_resolved_outage"

    def __init__(self, coordinator: FluviusCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "last_resolved_outage")

    @property
    def _outage(self) -> Outage | None:
        return next(iter(self.coordinator.resolved()), None)

    @property
    def native_value(self) -> datetime | None:
        """Return when the most recently resolved outage ended."""
        return outage.end if (outage := self._outage) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Describe the outage, and say how many were resolved in the period."""
        if (outage := self._outage) is None:
            return None
        return {
            **outage_attributes(self.coordinator, outage),
            "resolved_count": len(self.coordinator.resolved()),
        }
