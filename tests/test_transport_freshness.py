"""Startup recovery, snapshot ordering and freshness (UAP-02).

F02: the WS opened and stayed silent while the one startup poll failed — the
integration then had no data until the map next changed. F03: a watchdog poll
that was already in flight when the WS published a newer map overwrote it with
the older answer.
"""

import asyncio
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from test_entities import _setup
from test_hardening_0_3_0 import SilentWs

from custom_components.ukraine_alarm_pro.api.errors import TransportError
from custom_components.ukraine_alarm_pro.api.supervisor import (
    MODE_POLL,
    TransportSupervisor,
)
from custom_components.ukraine_alarm_pro.models import parse_alert_payload

CLEAR = parse_alert_payload({"alerts": []})
AIR = parse_alert_payload(
    {"alerts": [{"regionId": "31", "activeAlerts": [{"type": "AIR", "lastUpdate": "a"}]}]}
)


class ScriptedPoll:
    """Each fetch takes the next scripted outcome; a gate holds it in flight."""

    def __init__(self, *outcomes, gate: asyncio.Event | None = None):
        self._outcomes = list(outcomes)
        self.gate = gate
        self.fetches = 0
        self.started = asyncio.Event()

    async def fetch(self):
        self.fetches += 1
        outcome = self._outcomes.pop(0) if self._outcomes else self._last
        self._last = outcome
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _sup(ws, poll, **kw):
    kw.setdefault("seed_delay", 3600.0)
    kw.setdefault("poll_interval", 3600.0)
    kw.setdefault("watchdog_interval", 3600.0)
    return TransportSupervisor(ws=ws, poll=poll, **kw)


async def _until(predicate, timeout=1.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


# --- F02: startup seed recovers from a transient failure --------------------


async def test_seed_retries_until_the_first_snapshot_arrives():
    poll = ScriptedPoll(TransportError("down"), TransportError("down"), AIR)
    sup = _sup(SilentWs(), poll, seed_delay=0.01, seed_retry_interval=0.01)
    updates = []
    sup.set_listener(updates.append)
    await sup.start()
    try:
        await _until(lambda: updates)
        await asyncio.sleep(0.05)
        assert updates == [AIR]
        assert poll.fetches == 3, "retries stop once a snapshot is accepted"
    finally:
        await sup.stop()


async def test_seed_retry_backs_off_but_is_capped():
    sup = _sup(SilentWs(), ScriptedPoll(), seed_retry_interval=10, seed_retry_max=25)
    assert [sup._next_seed_delay(n) for n in range(4)] == [10, 20, 25, 25]


async def test_seed_in_flight_does_not_overwrite_a_websocket_snapshot():
    gate = asyncio.Event()
    poll = ScriptedPoll(CLEAR, gate=gate)
    sup = _sup(SilentWs(), poll, seed_delay=0.0, seed_retry_interval=0.01)
    updates = []
    sup.set_listener(updates.append)
    await sup.start()
    try:
        await asyncio.wait_for(poll.started.wait(), 1)
        sup._emit(AIR)  # the WS publishes while the seed request is in flight
        gate.set()
        await asyncio.sleep(0.05)
        assert updates == [AIR]
        assert poll.fetches == 1
    finally:
        await sup.stop()


# --- F03: a late HTTP answer never rolls back a newer publication -----------


async def test_watchdog_poll_does_not_overwrite_a_newer_websocket_publication():
    gate = asyncio.Event()
    poll = ScriptedPoll(CLEAR, gate=gate)
    ws = SilentWs(snap=CLEAR)
    sup = _sup(ws, poll, stale_after=0.02, watchdog_interval=0.01)
    updates = []
    sup.set_listener(updates.append)
    await sup.start()
    try:
        await asyncio.wait_for(poll.started.wait(), 1)
        sup._emit(AIR)  # newer WS publication while the cross-check waits
        gate.set()
        await asyncio.sleep(0.01)
        assert updates == [CLEAR, AIR]
        assert sup._last_snap is AIR
        assert ws.closed == 0, "a discarded answer is no reason to drop a live WS"
    finally:
        await sup.stop()


async def test_poll_fallback_answer_is_dropped_when_a_newer_snapshot_won():
    gate = asyncio.Event()
    poll = ScriptedPoll(CLEAR, gate=gate)
    sup = _sup(SilentWs(), poll)
    updates = []
    sup.set_listener(updates.append)
    await sup.start()
    try:
        sup._set_mode(MODE_POLL)
        await asyncio.wait_for(poll.started.wait(), 1)
        sup._emit(AIR)
        gate.set()
        await asyncio.sleep(0.02)
        assert updates == [AIR]
    finally:
        await sup.stop()


async def test_revision_counts_every_accepted_snapshot_even_identical_ones():
    sup = _sup(SilentWs(), ScriptedPoll())
    sup._emit(AIR)
    sup._emit(AIR)
    assert sup.snapshot_revision == 2


# --- health: success, check attempts and warnings are separate --------------


async def test_failed_cross_check_does_not_count_as_fresh_data():
    poll = ScriptedPoll(TransportError("down"))
    ws = SilentWs(snap=AIR)
    sup = _sup(ws, poll, stale_after=0.03, watchdog_interval=0.01)
    sup.set_listener(lambda snap: None)
    await sup.start()
    try:
        await _until(lambda: poll.fetches >= 1)
        await asyncio.sleep(0.01)
        assert sup.seconds_since_snapshot >= 0.03
        assert sup.seconds_since_check is not None
        assert sup.seconds_since_check < sup.seconds_since_snapshot
    finally:
        await sup.stop()


async def test_no_listener_calls_after_stop_during_an_in_flight_seed():
    gate = asyncio.Event()
    poll = ScriptedPoll(AIR, gate=gate)
    sup = _sup(SilentWs(), poll, seed_delay=0.0)
    updates = []
    sup.set_listener(updates.append)
    await sup.start()
    await asyncio.wait_for(poll.started.wait(), 1)
    await sup.stop()
    gate.set()
    await asyncio.sleep(0.02)
    assert updates == []
    assert sup._seed_task is None


async def test_identical_snapshot_after_staleness_refreshes_health_immediately(
    hass: HomeAssistant, enable_custom_integrations
):
    """A recovery with an unchanged map must not wait for the 60 s tick."""
    entry, push = await _setup(hass)
    push(AIR)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.uap_data_stale").state == "off"

    coordinator = entry.runtime_data
    coordinator.last_push = dt_util.utcnow() - timedelta(hours=1)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.uap_data_stale").state == "on"

    push(AIR)  # same map, no tick in between
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.uap_data_stale").state == "off"


async def test_diagnostics_keep_success_and_check_attempts_apart(
    hass: HomeAssistant, enable_custom_integrations
):
    from custom_components.ukraine_alarm_pro.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry, _ = await _setup(hass)
    sup = entry.runtime_data.supervisor
    sup.seconds_since_snapshot = None
    sup.seconds_since_check = 4.0
    sup.snapshot_revision = 0
    dump = await async_get_config_entry_diagnostics(hass, entry)
    assert dump["transport"]["seconds_since_accepted_snapshot"] is None
    assert dump["transport"]["seconds_since_cross_check"] == 4.0
    assert dump["transport"]["snapshot_revision"] == 0
