"""Tests for the siren.pp.ua polling fallback transport."""

import asyncio

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from custom_components.ukraine_alarm_pro.api.poll import PollTransport
from custom_components.ukraine_alarm_pro.api.errors import TransportError
from custom_components.ukraine_alarm_pro.models import Snapshot

PAYLOAD = [
    {
        "regionId": "31",
        "regionType": "State",
        "activeAlerts": [{"type": "AIR", "lastUpdate": "2026-07-17T06:00:00Z"}],
    }
]


async def _server(handler):
    app = web.Application()
    app.router.add_get("/alerts", handler)
    server = TestServer(app)
    await server.start_server()
    return server


async def test_fetch_returns_snapshot():
    async def handler(request):
        return web.json_response(PAYLOAD)

    server = await _server(handler)
    try:
        async with ClientSession() as session:
            t = PollTransport(session, base_url=str(server.make_url("")).rstrip("/"))
            snap = await t.fetch()
            assert isinstance(snap, Snapshot)
            assert "31" in snap.regions
    finally:
        await server.close()


async def test_fetch_timeout_raises_transport_error():
    async def handler(request):
        await asyncio.sleep(1)
        return web.json_response(PAYLOAD)

    server = await _server(handler)
    try:
        async with ClientSession() as session:
            t = PollTransport(
                session, base_url=str(server.make_url("")).rstrip("/"), timeout=0.1
            )
            with pytest.raises(TransportError):
                await t.fetch()
    finally:
        await server.close()


async def test_fetch_http_error_raises_transport_error():
    async def handler(request):
        return web.Response(status=502)

    server = await _server(handler)
    try:
        async with ClientSession() as session:
            t = PollTransport(session, base_url=str(server.make_url("")).rstrip("/"))
            with pytest.raises(TransportError):
                await t.fetch()
    finally:
        await server.close()
