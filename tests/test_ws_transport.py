"""Tests for the anonymous Centrifugo WebSocket transport."""

import asyncio
import json

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from custom_components.ukraine_alarm_pro.api.ws import WsTransport
from custom_components.ukraine_alarm_pro.api.errors import TransportError

SNAPSHOT_DATA = {
    "alerts": [
        {
            "regionId": "703",
            "regionType": "Community",
            "activeAlerts": [{"type": "AIR", "lastUpdate": "2026-07-17T06:00:00Z"}],
        }
    ]
}

PUSH_DATA = {
    "alerts": [
        {
            "regionId": "31",
            "regionType": "State",
            "activeAlerts": [{"type": "ARTILLERY", "lastUpdate": "2026-07-17T06:05:00Z"}],
        }
    ]
}


class FakeAlarmServer:
    """Fake map page + centrifugo WS endpoint."""

    def __init__(self):
        self.pushes: asyncio.Queue = asyncio.Queue()
        self.page_hits = 0
        self.server = None

    async def start(self):
        app = web.Application()
        app.router.add_get("/", self.page)
        app.router.add_get("/connection/websocket", self.ws)
        self.server = TestServer(app)
        await self.server.start_server()
        return self

    @property
    def page_url(self):
        return str(self.server.make_url("/"))

    async def page(self, request):
        self.page_hits += 1
        ws_url = str(self.server.make_url("/connection/websocket")).replace("http", "ws")
        html = (
            f'<input id="centrifugo-token" type="hidden" value="test-jwt-token">'
            f'<input id="centrifugo-url" type="hidden" value="{ws_url}">'
        )
        return web.Response(text=html, content_type="text/html")

    async def ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            d = json.loads(msg.data)
            if "method" not in d:  # connect
                if d["params"]["token"] != "test-jwt-token":
                    await ws.send_str(json.dumps({"id": d["id"], "error": {"code": 109}}))
                    continue
                await ws.send_str(json.dumps({"id": d["id"], "result": {"client": "c1", "ttl": 7199}}))
            elif d["method"] == 1:  # subscribe
                await ws.send_str(json.dumps({"id": d["id"], "result": {"recoverable": True}}))
                # after subscribe ack, deliver queued pushes as publications
                asyncio.get_event_loop().create_task(self._pump(ws))
            elif d["method"] == 6:  # history
                await ws.send_str(
                    json.dumps(
                        {
                            "id": d["id"],
                            "result": {"publications": [{"data": SNAPSHOT_DATA}]},
                        }
                    )
                )
        return ws

    async def _pump(self, ws):
        while True:
            data = await self.pushes.get()
            if data is None:
                return
            await ws.send_str(
                json.dumps({"result": {"channel": "updateMap", "data": {"data": data}}})
            )

    async def close(self):
        await self.pushes.put(None)
        await self.server.close()


async def test_ws_connects_and_yields_initial_snapshot():
    srv = await FakeAlarmServer().start()
    try:
        async with ClientSession() as session:
            t = WsTransport(session, map_url=srv.page_url)
            gen = t.stream()
            snap = await asyncio.wait_for(anext(gen), timeout=5)
            assert "703" in snap.regions
            await t.close()
    finally:
        await srv.close()


async def test_ws_yields_pushed_updates():
    srv = await FakeAlarmServer().start()
    try:
        async with ClientSession() as session:
            t = WsTransport(session, map_url=srv.page_url)
            gen = t.stream()
            await asyncio.wait_for(anext(gen), timeout=5)  # initial
            await srv.pushes.put(PUSH_DATA)
            snap = await asyncio.wait_for(anext(gen), timeout=5)
            assert "31" in snap.regions
            await t.close()
    finally:
        await srv.close()


async def test_ws_bad_page_raises_transport_error():
    async def page(request):
        return web.Response(text="<html>redesigned, no token</html>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/", page)
    server = TestServer(app)
    await server.start_server()
    try:
        async with ClientSession() as session:
            t = WsTransport(session, map_url=str(server.make_url("/")))
            with pytest.raises(TransportError):
                await asyncio.wait_for(anext(t.stream()), timeout=5)
    finally:
        await server.close()
