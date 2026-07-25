"""WS-primary / poll-fallback transport supervisor."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Callable, Coroutine
from typing import Any

from ..models import Snapshot
from .errors import TransportError

_LOGGER = logging.getLogger(__name__)

# Backoff jitter only — SystemRandom to keep security scanners quiet.
_RNG = random.SystemRandom()

MODE_WS = "websocket"
MODE_POLL = "polling"

DEFAULT_MAX_WS_FAILURES = 3
DEFAULT_POLL_INTERVAL = 60.0
DEFAULT_WS_RETRY_DELAY = 5.0
DEFAULT_WS_PROBE_INTERVAL = 300.0
DEFAULT_STALE_AFTER = 900.0
DEFAULT_WATCHDOG_INTERVAL = 60.0
# The WS channel serves an empty history, so a fresh connection stays blind
# until the map changes somewhere in the country (measured: minutes). Seed from
# the polling endpoint instead — after a short grace period, so a WS that does
# deliver straight away spares the volunteer-run proxy the request.
DEFAULT_SEED_DELAY = 2.0
# A session that streamed for this long was healthy; the drop that ended it is
# the server recycling an idle socket (2 h token TTL), not a broken transport.
DEFAULT_HEALTHY_SESSION = 120.0

TaskFactory = Callable[[Coroutine[Any, Any, None], str], "asyncio.Task[None]"]


def _default_task_factory(
    coro: Coroutine[Any, Any, None], name: str
) -> asyncio.Task[None]:
    return asyncio.get_running_loop().create_task(coro, name=name)


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
        stale_after: float = DEFAULT_STALE_AFTER,
        watchdog_interval: float = DEFAULT_WATCHDOG_INTERVAL,
        seed_delay: float = DEFAULT_SEED_DELAY,
        healthy_session: float = DEFAULT_HEALTHY_SESSION,
    ) -> None:
        self._ws = ws
        self._poll = poll
        self._max_ws_failures = max_ws_failures
        self._poll_interval = poll_interval
        self._ws_retry_delay = ws_retry_delay
        self._ws_probe_interval = ws_probe_interval
        self._stale_after = stale_after
        self._watchdog_interval = watchdog_interval
        self._seed_delay = seed_delay
        self._healthy_session = healthy_session
        self._listener: Callable[[Snapshot], None] | None = None
        self._mode_listener: Callable[[str], None] | None = None
        self._task: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._seed_task: asyncio.Task | None = None
        self._task_factory: TaskFactory = _default_task_factory
        self._last_snapshot: float | None = None
        self._last_snap: Snapshot | None = None
        self.mode = MODE_WS

    def set_listener(self, listener: Callable[[Snapshot], None]) -> None:
        self._listener = listener

    def set_mode_listener(self, listener: Callable[[str], None]) -> None:
        self._mode_listener = listener

    def _emit(self, snap: Snapshot) -> None:
        self._last_snapshot = time.monotonic()
        self._last_snap = snap
        if self._listener is not None:
            self._listener(snap)

    async def start(self, task_factory: TaskFactory | None = None) -> None:
        """Start the transport tasks, optionally through HA's task tracker."""
        if task_factory is not None:
            self._task_factory = task_factory
        self._task = self._task_factory(self._run(), f"{MODE_WS}-supervisor")
        self._watchdog_task = self._task_factory(
            self._watchdog(), "transport-watchdog"
        )
        self._seed_task = self._task_factory(self._seed(), "initial-seed")

    async def _seed(self) -> None:
        """Fill in a first snapshot the WebSocket cannot provide.

        Subscribing yields an empty history, so the region entities would stay
        blank from startup until the alert map next changes anywhere in the
        country — minutes, and precisely when the user needs them most.
        """
        await asyncio.sleep(self._seed_delay)
        if self._last_snapshot is not None:
            return
        snap = await self._fetch_poll("Could not seed the initial alert map")
        # Re-checked: the WS may have delivered while the request was in flight.
        if snap is not None and self._last_snapshot is None:
            self._emit(snap)

    async def _fetch_poll(self, context: str) -> Snapshot | None:
        try:
            return await self._poll.fetch()
        except asyncio.CancelledError:
            raise
        # Best effort only: a failing cross-check must never kill the caller.
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("%s: %s", context, err)
            return None

    async def stop(self) -> None:
        tasks = [
            task
            for task in (
                self._task,
                self._poll_task,
                self._watchdog_task,
                self._seed_task,
            )
            if task is not None
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            # gather() re-raises a cancellation of *this* task, which is what
            # a caller shutting us down expects, while swallowing the children's.
            await asyncio.gather(*tasks, return_exceptions=True)
        self._task = self._poll_task = self._watchdog_task = None
        self._seed_task = None
        await self._ws.close()

    async def _run(self) -> None:
        failures = 0
        while True:
            started = time.monotonic()
            try:
                async for snap in self._ws.stream():
                    failures = 0
                    self._set_mode(MODE_WS)
                    self._emit(snap)
            except TransportError as err:
                failures = self._count_failure(failures, started)
                _LOGGER.debug("WS failure %s/%s: %s", failures, self._max_ws_failures, err)
            except asyncio.CancelledError:
                raise
            except Exception:  # the transport task must never die silently
                failures = self._count_failure(failures, started)
                _LOGGER.exception(
                    "Unexpected WS transport error (%s/%s)", failures, self._max_ws_failures
                )
            if failures >= self._max_ws_failures:
                self._set_mode(MODE_POLL)
                delay = self._ws_probe_interval
            else:
                delay = self._ws_retry_delay * (2 ** max(failures - 1, 0))
            await asyncio.sleep(delay * (1 + _RNG.random() * 0.2))

    def _count_failure(self, failures: int, started: float) -> int:
        """Count one WS failure, forgiving the end of a long healthy session.

        The feed serves no history and can stay quiet for minutes, so a session
        that never yielded a snapshot is not evidence of a broken WebSocket —
        only a *short-lived* one is. Without this, three idle-socket recycles
        (token TTL is 2 h) would push a perfectly healthy transport to polling.
        """
        if time.monotonic() - started >= self._healthy_session:
            return 1
        return failures + 1

    def _set_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        _LOGGER.info("Transport mode: %s -> %s", self.mode, mode)
        self.mode = mode
        if mode == MODE_POLL and self._poll_task is None:
            self._poll_task = self._task_factory(self._poll_loop(), "poll-fallback")
        elif mode == MODE_WS and self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None
        if self._mode_listener is not None:
            self._mode_listener(mode)

    async def _poll_loop(self) -> None:
        while True:
            try:
                self._emit(await self._poll.fetch())
            except TransportError as err:
                _LOGGER.warning("Poll fallback failed: %s", err)
            except asyncio.CancelledError:
                raise
            except Exception:  # the poll loop must never die silently
                _LOGGER.exception("Unexpected poll fallback error")
            await asyncio.sleep(self._poll_interval)

    @property
    def seconds_since_snapshot(self) -> float | None:
        """Age of the last snapshot in seconds, or None if none arrived yet."""
        if self._last_snapshot is None:
            return None
        return time.monotonic() - self._last_snapshot

    async def _watchdog(self) -> None:
        """Cross-check a silent transport against the polling endpoint.

        A WebSocket can stay open at the TCP level and simply stop publishing;
        nothing else in the loop notices, so the integration would serve a
        frozen alert map forever. But silence is ambiguous — the feed only
        publishes on change, so a calm country looks exactly like a dead
        socket. The poll endpoint settles it: if it agrees with the last push
        the stream is fine, and if it does not (or fails outright) the socket
        is dropped, which makes `stream()` raise and sends `_run` through its
        normal reconnect/degrade path.
        """
        while True:
            await asyncio.sleep(self._watchdog_interval)
            age = self.seconds_since_snapshot
            if age is None or age < self._stale_after:
                continue
            # Reset the clock so a permanently dead feed warns once per window
            # instead of on every watchdog tick.
            self._last_snapshot = time.monotonic()
            if self.mode != MODE_WS:
                # The poll loop retries on its own schedule and owns no socket
                # to drop — closing the WS here would fix nothing.
                _LOGGER.warning(
                    "No alert data for %.0fs while polling — the feed itself "
                    "looks unavailable",
                    age,
                )
                continue
            previous = self._last_snap
            snap = await self._fetch_poll("Watchdog cross-check failed")
            if snap is not None:
                self._emit(snap)
                if previous is not None and snap.active == previous.active:
                    _LOGGER.debug(
                        "No alert data for %.0fs, but the feed agrees with the "
                        "last push — the alert map simply did not change",
                        age,
                    )
                    continue
                _LOGGER.warning(
                    "The WebSocket missed alert updates for %.0fs — reconnecting",
                    age,
                )
            else:
                _LOGGER.warning(
                    "No alert data for %.0fs and the fallback is unreachable — "
                    "reconnecting the WebSocket",
                    age,
                )
            try:
                await self._ws.close()
            except Exception:  # the watchdog must never die
                _LOGGER.exception("Failed to restart the WS transport")
