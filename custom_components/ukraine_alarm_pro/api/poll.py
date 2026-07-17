"""Polling fallback transport via the siren.pp.ua public proxy."""

from __future__ import annotations

import asyncio

import aiohttp

from ..models import Snapshot, parse_alert_payload
from .errors import TransportError

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

    async def fetch(self) -> Snapshot:
        try:
            resp = await self._session.get(
                f"{self._base_url}/alerts",
                headers={"accept": "application/json"},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return parse_alert_payload(await resp.json())
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise TransportError(f"poll failed: {err}") from err
