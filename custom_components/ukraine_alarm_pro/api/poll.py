"""Polling fallback transport via the siren.pp.ua public proxy."""

from __future__ import annotations

import asyncio
import math
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import aiohttp

from ..models import Snapshot, parse_alert_payload
from .errors import RateLimited, TransportError

DEFAULT_BASE_URL = "https://siren.pp.ua/api/v3"
DEFAULT_TIMEOUT = 30.0


class PollTransport:
    """Fetches all-region alerts in a single request."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._session = session
        self._base_url = base_url
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._retry_at = 0.0

    async def fetch(self) -> Snapshot:
        remaining = self._retry_at - time.monotonic()
        if remaining > 0:
            raise RateLimited(remaining)
        resp = None
        try:
            resp = await self._session.get(
                f"{self._base_url}/alerts",
                headers={"accept": "application/json"},
                timeout=self._timeout,
            )
            if resp.status in (429, 503):
                retry = retry_after_seconds(resp.headers.get("Retry-After"))
                self._retry_at = time.monotonic() + retry
                raise RateLimited(retry)
            resp.raise_for_status()
            return parse_alert_payload(await resp.json())
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise TransportError(f"poll failed: {err}") from err
        finally:
            if resp is not None:
                resp.release()


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
