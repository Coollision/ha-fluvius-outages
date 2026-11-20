"""Calendar: every outage announced for the location."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.util import dt as dt_util

from .const import OPEN_ENDED_CALENDAR_SPAN, OUTAGE_TYPE_PLANNED
from .entity import FluviusEntity

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
    """Set up the calendar."""
    async_add_entities([OutageCalendar(entry.runtime_data)])


class OutageCalendar(FluviusEntity, CalendarEntity):
    """Outages as calendar events, so they show up next to everything else."""

    _attr_translation_key = "outages"

    def __init__(self, coordinator: FluviusCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "calendar")

    def _to_event(self, outage: Outage, now: datetime) -> CalendarEvent:
        # An unplanned outage has no end yet; keep it on the calendar while it lasts.
        end = outage.end or max(now, outage.start) + OPEN_ENDED_CALENDAR_SPAN
        kind = "Planned" if outage.type == OUTAGE_TYPE_PLANNED else "Unplanned"
        resolved = " (resolved)" if outage.ended else ""
        streets = ", ".join(self.coordinator.location.touched_streets(outage))
        return CalendarEvent(
            start=outage.start,
            end=end,
            summary=f"{kind} power outage{resolved}",
            description=(
                f"{outage.customers_affected} customers affected. Streets: {streets}. "
                f"Work code {outage.werfcode}."
            ),
            uid=outage.id,
        )

    @property
    def event(self) -> CalendarEvent | None:
        """Return the outage under way, or else the next one."""
        now = dt_util.utcnow()
        outages = self.coordinator.active(now) or [
            o for o in self.coordinator.outages if o.is_upcoming(now)
        ]
        return self._to_event(outages[0], now) if outages else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return the outages that overlap a period."""
        now = dt_util.utcnow()
        return [
            event
            for outage in self.coordinator.outages
            if (event := self._to_event(outage, now))
            and event.start < end_date
            and event.end > start_date
        ]
