"""Polling coordinator: fetch, filter to the location, wake at start/end times."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import FluviusApi, FluviusError
from .const import (
    CONF_LOOKAHEAD_DAYS,
    CONF_RESOLVED_HOURS,
    CONF_SCAN_INTERVAL,
    DEFAULT_LOOKAHEAD_DAYS,
    DEFAULT_RESOLVED_HOURS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    RESOLVED_REFRESH,
)
from .matching import Location, Outage, parse_outages

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


class FluviusCoordinator(DataUpdateCoordinator[tuple[Outage, ...]]):
    """The outages that concern one location, soonest first."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: FluviusApi,
        location: Location,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        settings = {**entry.data, **entry.options}
        self.api = api
        self.location = location
        self.lookahead = timedelta(
            days=int(settings.get(CONF_LOOKAHEAD_DAYS, DEFAULT_LOOKAHEAD_DAYS))
        )
        self.retention = timedelta(
            hours=int(settings.get(CONF_RESOLVED_HOURS, DEFAULT_RESOLVED_HOURS))
        )
        self._boundary: CALLBACK_TYPE | None = None
        self._resolved: list[Outage] = []
        self._resolved_at: datetime | None = None
        self._current_ids: set[str] = set()

    async def _async_update_data(self) -> tuple[Outage, ...]:
        now = dt_util.utcnow()
        try:
            current = await self._fetch_current(now)
            resolved = await self._fetch_resolved(now, current)
        except FluviusError as err:
            raise UpdateFailed(str(err)) from err
        self._current_ids = {o.id for o in current}
        mine = sorted([*current, *resolved], key=lambda o: o.start)
        self._schedule_boundary(mine, now)
        return tuple(mine)

    async def _fetch_current(self, now: datetime) -> list[Outage]:
        """Outages under way or announced, within the configured window."""
        raw = await self.api.interruptions(now, self.lookahead.days)
        return [
            o
            for o in parse_outages(raw)
            if not o.ended
            and (o.end is None or o.end > now)
            and o.start <= now + self.lookahead
            and self.location.matches(o)
        ]

    async def _fetch_resolved(
        self, now: datetime, current: list[Outage]
    ) -> list[Outage]:
        """Recently restored outages, fetched rarely because the list is bulky."""
        if not self.retention:
            return []
        vanished = self._current_ids - {o.id for o in current}
        if (
            self._resolved_at is None
            or now - self._resolved_at >= RESOLVED_REFRESH
            or vanished  # one we showed as current is gone: it has probably ended
        ):
            raw = await self.api.resolved(
                now, int(self.retention.total_seconds() // 3600)
            )
            self._resolved = [o for o in parse_outages(raw) if self.location.matches(o)]
            self._resolved_at = now
        return [o for o in self._resolved if o.is_resolved(now, self.retention)]

    # -- views on the data, relative to "now" -------------------------------

    @property
    def outages(self) -> tuple[Outage, ...]:
        """Return every matching outage: current, announced and recently resolved."""
        return self.data or ()

    def active(self, now: datetime | None = None) -> list[Outage]:
        """Return the outages that are under way."""
        now = now or dt_util.utcnow()
        return [o for o in self.outages if o.is_active(now)]

    def next_planned(self, now: datetime | None = None) -> Outage | None:
        """Return the next planned outage that has not started."""
        now = now or dt_util.utcnow()
        return next((o for o in self.outages if o.planned and o.is_upcoming(now)), None)

    def resolved(self, now: datetime | None = None) -> list[Outage]:
        """Return recently restored outages, the most recently restored first."""
        now = now or dt_util.utcnow()
        found = [o for o in self.outages if o.is_resolved(now, self.retention)]
        return sorted(found, key=lambda o: o.end or o.start, reverse=True)

    # -- state changes that need no poll ------------------------------------

    def _schedule_boundary(self, outages: list[Outage], now: datetime) -> None:
        """Re-evaluate the entities exactly when something starts, ends or expires."""
        self._cancel_boundary()
        moments = [m for o in outages for m in (o.start, o.end) if m and m > now]
        moments += [
            o.end + self.retention for o in outages if o.ended and o.end is not None
        ]
        moments = [m for m in moments if m > now]
        if not moments:
            return

        @callback
        def _due(_now: datetime) -> None:
            self._boundary = None
            self._schedule_boundary(list(self.outages), dt_util.utcnow())
            self.async_update_listeners()

        self._boundary = async_track_point_in_utc_time(
            self.hass, _due, min(moments) + timedelta(seconds=1)
        )

    def _cancel_boundary(self) -> None:
        if self._boundary is not None:
            self._boundary()
            self._boundary = None

    async def async_shutdown(self) -> None:
        """Stop timers together with the polling."""
        self._cancel_boundary()
        await super().async_shutdown()
