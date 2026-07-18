"""WS-primary / poll-fallback transport supervisor."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from typing import Any

from ..models import Snapshot
from .errors import TransportError

_LOGGER = logging.getLogger(__name__)

MODE_WS = "websocket"
MODE_POLL = "polling"

DEFAULT_MAX_WS_FAILURES = 3
DEFAULT_POLL_INTERVAL = 60.0
DEFAULT_WS_RETRY_DELAY = 5.0
DEFAULT_WS_PROBE_INTERVAL = 300.0


class TransportSupervisor:
    """Runs the WS stream, degrades to polling, probes WS to recover."""

    def __init__(
        self,
        ws: Any,
        poll: Any,
        max_ws_failures: int = DEFAULT_MAX_WS_FAILURES,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        ws_retry_delay: float = DEFAULT_WS_RETRY_DELAY,
        ws_probe_interval: float = DEFAULT_WS_PROBE_INTERVAL,
    ) -> None:
        self._ws = ws
        self._poll = poll
        self._max_ws_failures = max_ws_failures
        self._poll_interval = poll_interval
        self._ws_retry_delay = ws_retry_delay
        self._ws_probe_interval = ws_probe_interval
        self._listener: Callable[[Snapshot], None] | None = None
        self._task: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None
        self.mode = MODE_WS

    def set_listener(self, listener: Callable[[Snapshot], None]) -> None:
        self._listener = listener

    def _emit(self, snap: Snapshot) -> None:
        if self._listener is not None:
            self._listener(snap)

    async def start(self) -> None:
        self._task = asyncio.get_event_loop().create_task(self._run())

    async def stop(self) -> None:
        for task in (self._task, self._poll_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._task = self._poll_task = None
        await self._ws.close()

    async def _run(self) -> None:
        failures = 0
        while True:
            try:
                async for snap in self._ws.stream():
                    failures = 0
                    self._set_mode(MODE_WS)
                    self._emit(snap)
            except TransportError as err:
                failures += 1
                _LOGGER.debug("WS failure %s/%s: %s", failures, self._max_ws_failures, err)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — task must never die silently
                failures += 1
                _LOGGER.exception(
                    "Unexpected WS transport error (%s/%s)", failures, self._max_ws_failures
                )
            if failures >= self._max_ws_failures:
                self._set_mode(MODE_POLL)
                delay = self._ws_probe_interval
            else:
                delay = self._ws_retry_delay * (2 ** max(failures - 1, 0))
            await asyncio.sleep(delay * (1 + random.random() * 0.2))

    def _set_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        _LOGGER.info("Transport mode: %s -> %s", self.mode, mode)
        self.mode = mode
        if mode == MODE_POLL and self._poll_task is None:
            self._poll_task = asyncio.get_event_loop().create_task(self._poll_loop())
        elif mode == MODE_WS and self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None

    async def _poll_loop(self) -> None:
        while True:
            try:
                self._emit(await self._poll.fetch())
            except TransportError as err:
                _LOGGER.warning("Poll fallback failed: %s", err)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — task must never die silently
                _LOGGER.exception("Unexpected poll fallback error")
            await asyncio.sleep(self._poll_interval)
