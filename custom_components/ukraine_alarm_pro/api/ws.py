"""Anonymous Centrifugo WebSocket transport behind the official alert map."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator

import aiohttp

from ..models import Snapshot, parse_alert_payload
from .errors import TransportError

DEFAULT_MAP_URL = "https://map.ukrainealarm.com/"
CHANNEL = "updateMap"
_TOKEN_RE = re.compile(r'centrifugo-token"[^>]*value="([^"]+)"')
_URL_RE = re.compile(r'centrifugo-url"[^>]*value="([^"]+)"')
_METHOD_SUBSCRIBE = 1
_METHOD_HISTORY = 6


class WsTransport:
    """Streams alert snapshots pushed by ws.ukrainealarm.com."""

    def __init__(self, session: aiohttp.ClientSession, map_url: str = DEFAULT_MAP_URL) -> None:
        self._session = session
        self._map_url = map_url
        self._ws: aiohttp.ClientWebSocketResponse | None = None

    async def _mint_token(self) -> tuple[str, str]:
        resp = await self._session.get(self._map_url, timeout=aiohttp.ClientTimeout(total=30))
        resp.raise_for_status()
        html = await resp.text()
        token_m = _TOKEN_RE.search(html)
        url_m = _URL_RE.search(html)
        if not token_m or not url_m:
            raise TransportError("map page has no centrifugo token/url (page changed?)")
        return token_m.group(1), url_m.group(1)

    async def _recv_id(self, ws: aiohttp.ClientWebSocketResponse, want: int) -> dict:
        for _ in range(20):
            msg = await ws.receive(timeout=30)
            if msg.type != aiohttp.WSMsgType.TEXT:
                raise TransportError(f"unexpected ws frame: {msg.type}")
            frame = json.loads(msg.data)
            if frame.get("id") == want:
                if "error" in frame:
                    raise TransportError(f"centrifugo error: {frame['error']}")
                return frame
        raise TransportError("no reply to command")

    async def stream(self) -> AsyncIterator[Snapshot]:
        """Connect and yield the initial snapshot, then every pushed update."""
        try:
            token, ws_url = await self._mint_token()
            self._ws = await self._session.ws_connect(ws_url, heartbeat=25)
            ws = self._ws
            await ws.send_str(json.dumps({"id": 1, "params": {"token": token}}))
            await self._recv_id(ws, 1)
            await ws.send_str(
                json.dumps({"id": 2, "method": _METHOD_SUBSCRIBE, "params": {"channel": CHANNEL}})
            )
            await self._recv_id(ws, 2)
            await ws.send_str(
                json.dumps({"id": 3, "method": _METHOD_HISTORY, "params": {"channel": CHANNEL}})
            )
            history = await self._recv_id(ws, 3)
        except (aiohttp.ClientError, asyncio.TimeoutError, TransportError) as err:
            await self.close()
            if isinstance(err, TransportError):
                raise
            raise TransportError(f"ws connect failed: {err}") from err

        publications = history.get("result", {}).get("publications") or []
        if publications:
            yield parse_alert_payload(publications[-1].get("data", {}))

        try:
            while True:
                msg = await self._ws.receive()
                if msg.type != aiohttp.WSMsgType.TEXT:
                    raise TransportError(f"ws closed: {msg.type}")
                frame = json.loads(msg.data)
                result = frame.get("result", {})
                if result.get("channel") == CHANNEL:
                    yield parse_alert_payload(result.get("data", {}).get("data", {}))
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise TransportError(f"ws stream failed: {err}") from err
        finally:
            await self.close()

    async def close(self) -> None:
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        self._ws = None
