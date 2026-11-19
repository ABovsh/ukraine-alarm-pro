"""HTTP fallback: the official map's snapshot first, then the siren.pp.ua proxy."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import aiohttp

from ..models import Snapshot, parse_alert_payload
from .errors import RateLimited, TransportError

DEFAULT_BASE_URL = "https://siren.pp.ua/api/v3"
OFFICIAL_URL = "https://map.ukrainealarm.com/api/v2/data/mapUpdate"
DEFAULT_TIMEOUT = 30.0
SOURCE_OFFICIAL = "official_http"
SOURCE_SIREN = "siren"
# A source is left after this many failures in a row, or at once on a rate
# limit; the preferred one is probed again at most this often.
SWITCH_AFTER_FAILURES = 2
RETRY_PREFERRED_SECONDS = 600.0


class PollTransport:
    """siren.pp.ua: all regions with an alert in one request, ETag-aware."""

    source = SOURCE_SIREN
    _conditional = True

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._session = session
        self._url = f"{base_url}/alerts"
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._retry_at = 0.0
        self._etag: str | None = None
        self._last: Snapshot | None = None

    def _parse(self, payload: Any) -> Snapshot:
        return parse_alert_payload(payload)

    async def fetch(self) -> Snapshot:
        remaining = self._retry_at - time.monotonic()
        if remaining > 0:
            raise RateLimited(remaining)
        headers = {"accept": "application/json"}
        if self._etag is not None:
            headers["If-None-Match"] = self._etag
        resp = None
        try:
            resp = await self._session.get(
                self._url, headers=headers, timeout=self._timeout
            )
            if resp.status in (429, 503):
                retry = retry_after_seconds(resp.headers.get("Retry-After"))
                self._retry_at = time.monotonic() + retry
                raise RateLimited(retry)
            # Not modified confirms the previous answer, nothing new to parse.
            if resp.status == 304:
                if "If-None-Match" not in headers or self._last is None:
                    raise TransportError(f"{self.source} returned an unsolicited 304")
                return self._last
            resp.raise_for_status()
            snap = self._parse(await resp.json())
            if self._conditional:
                self._etag = resp.headers.get("ETag")
                self._last = snap
            return snap
        except (TimeoutError, aiohttp.ClientError, ValueError) as err:
            raise TransportError(f"{self.source} poll failed: {err}") from err
        finally:
            if resp is not None:
                resp.release()


class OfficialPollTransport(PollTransport):
    """The official map's own snapshot: same alert records as the WebSocket.

    Conditional requests are not honoured there (always 200). Country-wide
    threats and MiG stay WebSocket-only: their HTTP copy is not proven to match,
    and an empty `mapNotifications` would read as "no threats".
    """

    source = SOURCE_OFFICIAL
    _conditional = False

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str = OFFICIAL_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        super().__init__(session, timeout=timeout)
        self._url = url

    def _parse(self, payload: Any) -> Snapshot:
        if not isinstance(payload, dict):
            raise ValueError(f"unrecognized map snapshot: {type(payload).__name__}")  # noqa: TRY004
        return parse_alert_payload({"alerts": payload.get("alerts")})


class ChainedPollTransport:
    """The first working source in order, switching rarely and never per request."""

    def __init__(self, sources: list[Any]) -> None:
        self._sources = sources
        self._current = 0
        self._failures = 0
        self._probed_at = 0.0
        self.on_switch: Callable[[], None] | None = None

    @property
    def source(self) -> str:
        return self._sources[self._current].source

    def _use(self, index: int) -> None:
        self._current = index
        self._failures = 0
        self._probed_at = time.monotonic()
        if self.on_switch is not None:
            self.on_switch()

    async def fetch(self) -> Snapshot:
        if self._current and time.monotonic() - self._probed_at >= RETRY_PREFERRED_SECONDS:
            self._probed_at = time.monotonic()
            try:
                snap = await self._sources[0].fetch()
            except TransportError:
                pass
            else:
                self._use(0)
                return snap
        try:
            snap = await self._sources[self._current].fetch()
        except TransportError as err:
            self._failures += 1
            last = self._current == len(self._sources) - 1
            if last and self._current and isinstance(err, RateLimited):
                # This source's cooldown must not postpone probing the preferred
                # one. Each transport still enforces its own Retry-After.
                probe_in = max(
                    1.0, RETRY_PREFERRED_SECONDS - (time.monotonic() - self._probed_at)
                )
                raise RateLimited(min(err.retry_after, probe_in)) from err
            if last or (
                self._failures < SWITCH_AFTER_FAILURES and not isinstance(err, RateLimited)
            ):
                raise
            self._use(self._current + 1)
            return await self.fetch()
        self._failures = 0
        return snap


def retry_after_seconds(value: str | None) -> float:
    """Retry-After accepts seconds or an HTTP date; bound untrusted values."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            stamp = parsedate_to_datetime(value)
            seconds = (stamp - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            seconds = 60.0
    return min(max(seconds, 1.0), 3600.0) if math.isfinite(seconds) else 60.0
