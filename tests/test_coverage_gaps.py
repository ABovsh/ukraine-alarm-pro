"""Failure paths of the region fetch, WS framing and history parsing."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.core import HomeAssistant

from custom_components.ukraine_alarm_pro.api.errors import TransportError
from custom_components.ukraine_alarm_pro.api.ws import (
    WsTransport,
    _publication,
    _replies,
)
from custom_components.ukraine_alarm_pro.backfill import parse_ranged_alerts
from custom_components.ukraine_alarm_pro.regions import (
    async_fetch_regions,
    async_refresh_region_cache,
)


def _session(resp=None, err=None):
    session = MagicMock()
    session.get = AsyncMock(return_value=resp, side_effect=err)
    return session


async def test_fetch_regions_returns_json():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = AsyncMock(return_value={"states": []})
    assert await async_fetch_regions(_session(resp)) == {"states": []}


async def test_fetch_regions_wraps_client_errors():
    with pytest.raises(TransportError, match="regions fetch failed"):
        await async_fetch_regions(_session(err=aiohttp.ClientError("boom")))


async def test_refresh_region_cache_swallows_fetch_failure(hass: HomeAssistant):
    fetch = AsyncMock(side_effect=TransportError("down"))
    await async_refresh_region_cache(hass, fetch)
    fetch.assert_awaited()


def test_replies_skips_blank_lines_and_rejects_garbage():
    assert _replies('{"id": 1}\n\n{"id": 2}') == [{"id": 1}, {"id": 2}]
    with pytest.raises(TransportError, match="malformed"):
        _replies("{nope")


def test_publication_ignores_other_replies():
    assert _publication({}) is None
    assert _publication({"result": {"channel": "other"}}) is None


def _ws_with(*messages):
    ws = MagicMock()
    ws.receive = AsyncMock(side_effect=list(messages))
    return ws


def _text(data):
    return MagicMock(type=aiohttp.WSMsgType.TEXT, data=data)


async def test_recv_id_rejects_non_text_frame():
    transport = WsTransport(MagicMock())
    ws = _ws_with(MagicMock(type=aiohttp.WSMsgType.CLOSED))
    with pytest.raises(TransportError, match="unexpected ws frame"):
        await transport._recv_id(ws, 1, [])


async def test_recv_id_raises_on_centrifugo_error():
    transport = WsTransport(MagicMock())
    ws = _ws_with(_text(json.dumps({"id": 1, "error": {"code": 109}})))
    with pytest.raises(TransportError, match="centrifugo error"):
        await transport._recv_id(ws, 1, [])


async def test_recv_id_keeps_batched_publications():
    transport = WsTransport(MagicMock())
    pending: list[dict] = []
    ws = _ws_with(_text('{"push": 1}\n{"id": 1}\n{"push": 2}'))
    assert await transport._recv_id(ws, 1, pending) == {"id": 1}
    assert pending == [{"push": 1}, {"push": 2}]


async def test_recv_id_gives_up_without_reply():
    transport = WsTransport(MagicMock())
    ws = _ws_with(*[_text('{"id": 9}')] * 20)
    with pytest.raises(TransportError, match="no reply"):
        await transport._recv_id(ws, 1, [])


def test_parse_ranged_alerts_edge_cases():
    inner = json.dumps(
        [
            "junk",
            {"regionId": True, "startDate": "2026-07-17T06:00:00Z", "endDate": "2026-07-17T07:00:00Z"},
            {"regionId": 5, "startDate": "bad", "endDate": "2026-07-17T07:00:00Z"},
            {"regionId": 5, "startDate": 1, "endDate": "2026-07-17T07:00:00Z"},
            {"regionId": 5, "startDate": "2026-07-17T07:00:00Z", "endDate": "2026-07-17T06:00:00Z"},
            {"regionId": 7, "startDate": "2026-07-17T06:00:00", "endDate": "2026-07-17T07:00:00Z"},
        ]
    )
    records = parse_ranged_alerts(json.dumps(inner))
    assert [r[0] for r in records] == ["7"]
    assert records[0][1].tzinfo is not None


def test_parse_ranged_alerts_rejects_unusable_answers():
    with pytest.raises(ValueError, match="not JSON"):
        parse_ranged_alerts("<html>")
    with pytest.raises(ValueError, match="not a list"):
        parse_ranged_alerts("{}")


async def test_refresh_region_cache_ignores_unreadable_copy(hass: HomeAssistant):
    fetch = AsyncMock(side_effect=TransportError("down"))
    with patch(
        "custom_components.ukraine_alarm_pro.regions.Store.async_load",
        AsyncMock(side_effect=OSError("corrupt")),
    ):
        await async_refresh_region_cache(hass, fetch)
    fetch.assert_awaited()
