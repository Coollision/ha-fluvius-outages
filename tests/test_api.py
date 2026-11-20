"""Tests for the API client."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)

from custom_components.fluvius_outages.api import FluviusApi, FluviusError
from custom_components.fluvius_outages.const import (
    API_URL,
    MAX_LOOKAHEAD_DAYS,
    PAGE_URL,
)

from .conftest import KEY, PAGE, record

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )

NOW = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)


def _api(hass: HomeAssistant) -> FluviusApi:
    return FluviusApi(async_get_clientsession(hass), "test-agent")


async def test_reads_key_from_page_and_sends_it(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The key comes from the outage page and goes into the request header."""
    aioclient_mock.get(PAGE_URL, text=PAGE)
    aioclient_mock.get(API_URL, json={"interruptions": [record()]})

    records = await _api(hass).interruptions(NOW)

    assert len(records) == 1
    headers = aioclient_mock.mock_calls[-1][3]
    assert headers["subscription-key"] == KEY
    assert headers["user-agent"] == "test-agent"


async def test_asks_for_ongoing_interruptions_in_a_window(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The query asks for both types, not-yet-ended ones, and a date window."""
    aioclient_mock.get(PAGE_URL, text=PAGE)
    aioclient_mock.get(API_URL, json={"interruptions": []})

    await _api(hass).interruptions(NOW)

    url = aioclient_mock.mock_calls[-1][1]
    assert url.query.getall("InterruptionTypes") == ["Planned", "Unplanned"]
    assert url.query.getall("EventTypes") == ["New", "Update"]
    assert url.query["DateFrom"] == "2026-11-06"
    assert url.query["DateUntil"] == "2026-12-04T23:59:59"


async def test_refreshes_a_refused_key_once(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 401 triggers one fresh read of the key and one retry."""
    answers = [401, 200]

    async def _api_answer(method, url, data):
        status = answers.pop(0)
        return AiohttpClientMockResponse(
            method, url, status=status, json={"interruptions": []}
        )

    aioclient_mock.get(PAGE_URL, text=PAGE)
    aioclient_mock.get(API_URL, side_effect=_api_answer)
    api = _api(hass)

    assert await api.interruptions(NOW) == []
    pages = [c for c in aioclient_mock.mock_calls if str(c[1]) == PAGE_URL]
    assert len(pages) == 2  # first read + refresh after the 401


async def test_keeps_failing_after_one_refresh(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Two refusals in a row are an error, not a loop."""
    aioclient_mock.get(PAGE_URL, text=PAGE)
    aioclient_mock.get(API_URL, status=403)

    with pytest.raises(FluviusError):
        await _api(hass).interruptions(NOW)


async def test_page_without_key(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A page that no longer carries a key is reported clearly."""
    aioclient_mock.get(PAGE_URL, text="<html>redesigned</html>")

    with pytest.raises(FluviusError, match="no longer contains"):
        await _api(hass).interruptions(NOW)


@pytest.mark.parametrize("body", [{"nope": []}, {"interruptions": "x"}])
async def test_unexpected_answer(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, body: dict
) -> None:
    """An answer without an interruptions list is an error."""
    aioclient_mock.get(PAGE_URL, text=PAGE)
    aioclient_mock.get(API_URL, json=body)

    with pytest.raises(FluviusError):
        await _api(hass).interruptions(NOW)


async def test_server_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """HTTP errors become FluviusError."""
    aioclient_mock.get(PAGE_URL, text=PAGE)
    aioclient_mock.get(API_URL, status=500)

    with pytest.raises(FluviusError):
        await _api(hass).interruptions(NOW)


async def test_error_message_from_fluvius_is_kept(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A rejected request says why, so the log is useful."""
    aioclient_mock.get(PAGE_URL, text=PAGE)
    aioclient_mock.get(API_URL, status=400, text="DateUntil cannot be more")

    with pytest.raises(FluviusError, match="HTTP 400: DateUntil cannot be more"):
        await _api(hass).interruptions(NOW)


def test_lookahead_respects_the_fluvius_limit() -> None:
    """Fluvius answers 400 for a DateUntil more than 15 days ahead."""
    assert 0 < MAX_LOOKAHEAD_DAYS <= 15


@pytest.mark.parametrize(
    ("days", "until"),
    [
        (0, "2026-11-20T23:59:59"),
        (3, "2026-11-23T23:59:59"),
        (14, "2026-12-04T23:59:59"),
    ],
)
async def test_window_follows_the_lookahead(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    days: int,
    until: str,
) -> None:
    """DateUntil is today plus the configured days."""
    aioclient_mock.get(PAGE_URL, text=PAGE)
    aioclient_mock.get(API_URL, json={"interruptions": []})

    await _api(hass).interruptions(NOW, days)

    assert aioclient_mock.mock_calls[-1][1].query["DateUntil"] == until


async def test_resolved_asks_only_for_restored_outages_in_a_short_window(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Restored outages are a separate, narrow request."""
    aioclient_mock.get(PAGE_URL, text=PAGE)
    aioclient_mock.get(API_URL, json={"interruptions": [record(event="End")]})

    records = await _api(hass).resolved(NOW, 24)

    assert len(records) == 1
    query = aioclient_mock.mock_calls[-1][1].query
    assert query.getall("EventTypes") == ["End"]
    assert query["DateFrom"] == "2026-11-19"
    assert query["DateUntil"] == "2026-11-20T23:59:59"
