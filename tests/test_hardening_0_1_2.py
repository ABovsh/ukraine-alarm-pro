"""Hardening round 2: transport-mode changes must reach entities immediately."""

from unittest.mock import AsyncMock, MagicMock

from custom_components.ukraine_alarm_pro.api.errors import TransportError
from custom_components.ukraine_alarm_pro.api.supervisor import (
    MODE_POLL,
    MODE_WS,
    TransportSupervisor,
)


def _supervisor(**kw):
    poll = MagicMock()
    poll.fetch = AsyncMock(side_effect=TransportError("down"))
    ws = MagicMock()
    ws.close = AsyncMock()
    return TransportSupervisor(ws=ws, poll=poll, **kw)


async def test_mode_listener_fires_on_transition():
    sup = _supervisor()
    seen = []
    sup.set_mode_listener(seen.append)
    sup._set_mode(MODE_WS)  # no-op: already ws
    assert seen == []
    sup._set_mode(MODE_POLL)
    assert seen == [MODE_POLL]
    sup._set_mode(MODE_WS)
    assert seen == [MODE_POLL, MODE_WS]
    await sup.stop()


def test_coordinator_mode_change_notifies_listeners():
    from custom_components.ukraine_alarm_pro.coordinator import AlarmCoordinator

    coordinator = AlarmCoordinator.__new__(AlarmCoordinator)
    coordinator.async_update_listeners = MagicMock()
    coordinator.handle_mode_change(MODE_POLL)
    coordinator.async_update_listeners.assert_called_once()


def test_setup_wires_mode_listener():
    import inspect

    from custom_components import ukraine_alarm_pro

    src = inspect.getsource(ukraine_alarm_pro.async_setup_entry)
    assert "set_mode_listener" in src
