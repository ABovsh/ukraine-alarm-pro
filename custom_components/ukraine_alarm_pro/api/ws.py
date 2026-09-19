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


def _parse(payload) -> Snapshot:
    """Parse a publication, reporting a shape change as a transport failure."""
    try:
        return parse_alert_payload(payload)
    except ValueError as err:
        raise TransportError(f"unusable publication: {err}") from err


def _publication(frame: dict) -> Snapshot | None:
    """The alert map in an `updateMap` publication, None for any other reply."""
    result = frame.get("result")
    if not isinstance(result, dict) or result.get("channel") != CHANNEL:
        return None
    data = result.get("data")
    return _parse(data.get("data") if isinstance(data, dict) else None)


def _replies(data: str) -> list[dict]:
    """The replies in one frame; anything but JSON objects is a broken stream.

    Centrifugo's JSON protocol may batch several replies into one frame,
    separated by newlines — the map page's own client splits every frame the
    same way. Reading the frame as a single document turned a batch into a
    "malformed frame", dropping its publications and the connection with them.
    """
    replies = []
    for line in data.split("\n"):
        if not line.strip():
            continue
        try:
            reply = json.loads(line)
        except ValueError as err:
            raise TransportError(f"malformed ws frame: {err}") from err
        if not isinstance(reply, dict):
            raise TransportError(f"unexpected ws reply: {type(reply).__name__}")
        replies.append(reply)
    return replies


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

    async def _recv_id(
        self, ws: aiohttp.ClientWebSocketResponse, want: int, pending: list[dict]
    ) -> dict:
        """The reply to command `want`; publications batched with it go to `pending`."""
        for _ in range(20):
            msg = await ws.receive(timeout=30)
            if msg.type != aiohttp.WSMsgType.TEXT:
                raise TransportError(f"unexpected ws frame: {msg.type}")
            replies = _replies(msg.data)
            for index, frame in enumerate(replies):
                if frame.get("id") == want:
                    if "error" in frame:
                        raise TransportError(f"centrifugo error: {frame['error']}")
                    pending.extend(replies[index + 1 :])
                    return frame
                pending.append(frame)
        raise TransportError("no reply to command")

    async def stream(self) -> AsyncIterator[Snapshot]:
        """Connect and yield the initial snapshot, then every pushed update."""
        # Publications that arrived in the same frame as a command reply.
        pending: list[dict] = []
        try:
            token, ws_url = await self._mint_token()
            self._ws = await self._session.ws_connect(ws_url, heartbeat=25)
            ws = self._ws
            await ws.send_str(json.dumps({"id": 1, "params": {"token": token}}))
            await self._recv_id(ws, 1, pending)
            await ws.send_str(
                json.dumps({"id": 2, "method": _METHOD_SUBSCRIBE, "params": {"channel": CHANNEL}})
            )
            await self._recv_id(ws, 2, pending)
            await ws.send_str(
                json.dumps({"id": 3, "method": _METHOD_HISTORY, "params": {"channel": CHANNEL}})
            )
            history = await self._recv_id(ws, 3, pending)
        except (aiohttp.ClientError, asyncio.TimeoutError, TransportError) as err:
            await self.close()
            if isinstance(err, TransportError):
                raise
            raise TransportError(f"ws connect failed: {err}") from err

        try:
            # The live channel serves an empty history in practice; the
            # supervisor seeds the first snapshot from the polling endpoint.
            result = history.get("result")
            publications = (
                result.get("publications") if isinstance(result, dict) else None
            ) or []
            if isinstance(publications, list) and publications and isinstance(
                publications[-1], dict
            ):
                yield _parse(publications[-1].get("data", {}))
            for frame in pending:
                if (snap := _publication(frame)) is not None:
                    yield snap
            while True:
                # `ws`, not `self._ws`: close() (watchdog, unload) clears the
                # attribute, and the loop must raise TransportError, not
                # AttributeError, when the socket is pulled from under it.
                msg = await ws.receive()
                if msg.type != aiohttp.WSMsgType.TEXT:
                    raise TransportError(f"ws closed: {msg.type}")
                for frame in _replies(msg.data):
                    if (snap := _publication(frame)) is not None:
                        yield snap
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise TransportError(f"ws stream failed: {err}") from err
        finally:
            await self.close()

    async def close(self) -> None:
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        self._ws = None
