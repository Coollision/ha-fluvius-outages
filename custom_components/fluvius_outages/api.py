"""Client for the endpoint behind the outage map on fluvius.be."""

from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
import logging
import re
from typing import TYPE_CHECKING, Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import (
    API_URL,
    LOOKBACK,
    MAX_LOOKAHEAD_DAYS,
    ORIGIN,
    PAGE_URL,
    REQUEST_TIMEOUT,
)

if TYPE_CHECKING:
    from datetime import datetime

_LOGGER = logging.getLogger(__name__)

_KEY_RE = re.compile(r'"subscription_key"\s*:\s*"([0-9A-Za-z]{16,64})"')
_AUTH_STATUSES = (401, 403)


class FluviusError(Exception):
    """Fluvius could not be reached or answered something unusable."""


class FluviusApi:
    """Read interruptions, finding (and re-finding) the public key by itself."""

    def __init__(self, session: ClientSession, user_agent: str) -> None:
        """Initialize."""
        self._session = session
        self._headers = {
            "accept": "application/json",
            "origin": ORIGIN,
            "referer": f"{ORIGIN}/",
            "user-agent": user_agent,
        }
        self._key: str | None = None

    async def _fetch_key(self) -> str:
        """Read the key Fluvius embeds in the outage page for every visitor."""
        try:
            async with self._session.get(
                PAGE_URL,
                headers={"user-agent": self._headers["user-agent"]},
                timeout=ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                response.raise_for_status()
                html = await response.text()
        except (ClientError, TimeoutError) as err:
            raise FluviusError(
                f"Could not load the Fluvius outage page: {err}"
            ) from err
        if (match := _KEY_RE.search(html)) is None:
            raise FluviusError("The Fluvius outage page no longer contains an API key")
        _LOGGER.debug("Fetched a new Fluvius API key")
        return match.group(1)

    async def _get(self, params: list[tuple[str, str]]) -> dict[str, Any]:
        """GET the endpoint, refreshing the key once if it is refused."""
        for attempt in (1, 2):
            if self._key is None:
                self._key = await self._fetch_key()
            try:
                async with self._session.get(
                    API_URL,
                    params=params,
                    headers={**self._headers, "subscription-key": self._key},
                    timeout=ClientTimeout(total=REQUEST_TIMEOUT),
                ) as response:
                    if response.status in _AUTH_STATUSES and attempt == 1:
                        self._key = None
                        continue
                    if response.status >= HTTPStatus.BAD_REQUEST:
                        detail = (await response.text())[:300]
                        raise FluviusError(
                            f"Fluvius answered HTTP {response.status}: {detail}"
                        )
                    return await response.json(content_type=None)
            except (ClientError, TimeoutError, ValueError) as err:
                raise FluviusError(f"Fluvius request failed: {err}") from err
        raise FluviusError("Fluvius keeps refusing the API key")  # pragma: no cover

    async def _records(
        self, events: tuple[str, ...], date_from: datetime, date_until: datetime
    ) -> list[dict[str, Any]]:
        """Return the raw records of some event types within a date window."""
        params = [
            ("InterruptionTypes", "Planned"),
            ("InterruptionTypes", "Unplanned"),
            *(("EventTypes", event) for event in events),
            ("DateFrom", date_from.date().isoformat()),
            ("DateUntil", f"{date_until.date().isoformat()}T23:59:59"),
        ]
        data = await self._get(params)
        records = data.get("interruptions")
        if not isinstance(records, list):
            raise FluviusError("Fluvius answered without an interruptions list")
        return records

    async def interruptions(
        self, now: datetime, lookahead_days: int = MAX_LOOKAHEAD_DAYS
    ) -> list[dict[str, Any]]:
        """Return the current and announced interruptions (not the restored ones)."""
        return await self._records(
            ("New", "Update"),
            now - LOOKBACK,
            now + timedelta(days=lookahead_days),
        )

    async def resolved(self, now: datetime, hours: int) -> list[dict[str, Any]]:
        """Return the interruptions restored within the last ``hours``."""
        return await self._records(("End",), now - timedelta(hours=hours), now)
