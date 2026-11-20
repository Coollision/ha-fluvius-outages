"""Polling coordinator: fetch, filter to the location, wake at start/end times."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import FluviusApi, FluviusError, active_or_upcoming
from .const import (
    CONF_LOOKAHEAD_DAYS,
    CONF_SCAN_INTERVAL,
    DEFAULT_LOOKAHEAD_DAYS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
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
        self.api = api
        self.lookahead = timedelta(
            days=int(
                {**entry.data, **entry.options}.get(
                    CONF_LOOKAHEAD_DAYS, DEFAULT_LOOKAHEAD_DAYS
                )
            )
        )
        self.location = location
        self._boundary: CALLBACK_TYPE | None = None

    async def _async_update_data(self) -> tuple[Outage, ...]:
        now = dt_util.utcnow()
        try:
            raw = await self.api.interruptions(now, self.lookahead.days)
        except FluviusError as err:
            raise UpdateFailed(str(err)) from err
        mine = [
            o
            for o in active_or_upcoming(parse_outages(raw), now)
            if self.location.matches(o) and o.start <= now + self.lookahead
        ]
        mine.sort(key=lambda o: o.start)
        self._schedule_boundary(mine, now)
        return tuple(mine)

    # -- views on the data, relative to "now" -------------------------------

    @property
    def outages(self) -> tuple[Outage, ...]:
        """Return every matching outage that is not over yet."""
        return self.data or ()

    def active(self, now: datetime | None = None) -> list[Outage]:
        """Return the outages that are under way."""
        now = now or dt_util.utcnow()
        return [o for o in self.outages if o.is_active(now)]

    def next_planned(self, now: datetime | None = None) -> Outage | None:
        """Return the next planned outage that has not started."""
        now = now or dt_util.utcnow()
        return next((o for o in self.outages if o.planned and o.is_upcoming(now)), None)

    # -- state changes that need no poll ------------------------------------

    def _schedule_boundary(self, outages: list[Outage], now: datetime) -> None:
        """Re-evaluate the entities exactly when an outage starts or ends."""
        self._cancel_boundary()
        moments = [m for o in outages for m in (o.start, o.end) if m and m > now]
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
