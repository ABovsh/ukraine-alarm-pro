"""Failure paths of the release: transport errors, token refresh and journal writes."""

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aiohttp import ClientSession
from test_entities import _setup

from custom_components.ukraine_alarm_pro.api.errors import TransportError
from custom_components.ukraine_alarm_pro.api.supervisor import TransportSupervisor
from custom_components.ukraine_alarm_pro.api.ws import WsTransport

T0 = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)


async def test_failed_history_write_warns_once_then_stays_quiet(hass, enable_custom_integrations, caplog):
    entry, _push = await _setup(hass)
    coordinator = entry.runtime_data
    coordinator.history.async_flush = AsyncMock(side_effect=OSError("disk full"))
    with caplog.at_level(logging.DEBUG):
        await coordinator.async_flush_history()
        await coordinator.async_flush_history()
    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "Could not save the alert history" in r.getMessage()
    ]
    assert len(warnings) == 1
    assert coordinator._history_save_failed is True
    coordinator.history.async_flush = AsyncMock()
    await coordinator.async_flush_history()
    assert coordinator._history_save_failed is False


async def test_ws_connect_failure_becomes_a_transport_error():
    async with ClientSession() as session:
        transport = WsTransport(session)
        with (
            patch.object(transport, "_mint_token", AsyncMock(return_value=("tok", "wss://example.invalid/ws"))),
            patch.object(session, "ws_connect", AsyncMock(side_effect=aiohttp.ClientConnectionError("boom"))),
            pytest.raises(TransportError, match="ws connect failed"),
        ):
            await anext(transport.stream())


async def test_ws_handshake_error_is_raised_as_it_is():
    async with ClientSession() as session:
        transport = WsTransport(session)
        socket = MagicMock()
        socket.send_str = AsyncMock()
        with (
            patch.object(transport, "_mint_token", AsyncMock(return_value=("tok", "wss://example.invalid/ws"))),
            patch.object(session, "ws_connect", AsyncMock(return_value=socket)),
            patch.object(WsTransport, "_recv_id", AsyncMock(side_effect=TransportError("centrifugo error: 100"))),
            pytest.raises(TransportError, match="centrifugo error"),
        ):
            await anext(transport.stream())
        assert transport._ws is None


def test_a_fresh_supervisor_has_no_data_ages():
    supervisor = TransportSupervisor(ws=MagicMock(), poll=AsyncMock())
    assert supervisor.seconds_since_snapshot is None
    assert supervisor.seconds_since_check is None


def test_an_http_answer_that_was_overtaken_is_discarded():
    supervisor = TransportSupervisor(ws=MagicMock(), poll=AsyncMock())
    seen = []
    supervisor.set_listener(seen.append)
    # Stopped supervisor: nothing is published.
    assert supervisor._emit_if_current(MagicMock(), supervisor.snapshot_revision) is False
    supervisor._running = True
    # A newer snapshot arrived while the request was out.
    assert supervisor._emit_if_current(MagicMock(), supervisor.snapshot_revision - 1) is False
    assert seen == []


async def test_ws_task_cancelled_while_connecting_closes_the_socket():
    import asyncio

    async with ClientSession() as session:
        transport = WsTransport(session)
        with (
            patch.object(transport, "_mint_token", AsyncMock(return_value=("tok", "wss://example.invalid/ws"))),
            patch.object(session, "ws_connect", AsyncMock(side_effect=asyncio.CancelledError())),
            pytest.raises(asyncio.CancelledError),
        ):
            await anext(transport.stream())
        assert transport._ws is None


def test_retry_after_garbage_falls_back_to_a_minute():
    from custom_components.ukraine_alarm_pro.api.poll import retry_after_seconds

    assert retry_after_seconds("soon-ish") == 60.0
    assert retry_after_seconds(None) == 60.0


def test_a_damaged_saved_map_is_ignored_piece_by_piece():
    from custom_components.ukraine_alarm_pro.coordinator import _snapshot_from_store

    assert _snapshot_from_store({"regions": "nope"}) is None
    snapshot = _snapshot_from_store({"regions": {"31": "bad", "14": [{"type": "AIR"}, "x"]}})
    assert list(snapshot.regions) == ["14"] and len(snapshot.regions["14"]) == 1


async def test_seconds_since_push_needs_both_clocks(hass, enable_custom_integrations):
    entry, _push = await _setup(hass)
    coordinator = entry.runtime_data
    coordinator.last_push = None
    assert coordinator.seconds_since_push is None
    coordinator.last_push = datetime.now(UTC)
    coordinator._last_push_monotonic = None
    assert coordinator.seconds_since_push is None
