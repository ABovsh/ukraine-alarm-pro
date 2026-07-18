"""Tests for the WS-primary / poll-fallback transport supervisor."""

import asyncio


from custom_components.ukraine_alarm_pro.api.supervisor import TransportSupervisor
from custom_components.ukraine_alarm_pro.api.errors import TransportError
from custom_components.ukraine_alarm_pro.models import parse_alert_payload

SNAP_WS = parse_alert_payload({"alerts": [{"regionId": "703", "regionType": "Community", "activeAlerts": [{"type": "AIR", "lastUpdate": "x"}]}]})
SNAP_POLL = parse_alert_payload({"alerts": [{"regionId": "31", "regionType": "State", "activeAlerts": [{"type": "AIR", "lastUpdate": "y"}]}]})


class FakeWs:
    def __init__(self, fail_times=0):
        self.fail_times = fail_times
        self.attempts = 0
        self.closed = False

    async def stream(self):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise TransportError("ws down")
        while True:
            yield SNAP_WS
            await asyncio.sleep(3600)

    def stream_gen(self):
        return self.stream()

    async def close(self):
        self.closed = True


class FakePoll:
    def __init__(self):
        self.fetches = 0

    async def fetch(self):
        self.fetches += 1
        return SNAP_POLL


async def test_ws_healthy_uses_websocket():
    sup = TransportSupervisor(ws=FakeWs(), poll=FakePoll(), max_ws_failures=3, poll_interval=0.05)
    updates = []
    sup.set_listener(lambda snap: updates.append(snap))
    await sup.start()
    await asyncio.sleep(0.1)
    assert sup.mode == "websocket"
    assert updates and "703" in updates[0].regions
    await sup.stop()


async def test_degrades_to_polling_after_max_failures():
    sup = TransportSupervisor(
        ws=FakeWs(fail_times=99), poll=FakePoll(), max_ws_failures=3,
        poll_interval=0.05, ws_retry_delay=0.01, ws_probe_interval=3600,
    )
    updates = []
    sup.set_listener(lambda snap: updates.append(snap))
    await sup.start()
    await asyncio.sleep(0.3)
    assert sup.mode == "polling"
    assert any("31" in u.regions for u in updates)
    await sup.stop()


async def test_recovers_to_websocket_when_probe_succeeds():
    ws = FakeWs(fail_times=3)
    sup = TransportSupervisor(
        ws=ws, poll=FakePoll(), max_ws_failures=3,
        poll_interval=0.05, ws_retry_delay=0.01, ws_probe_interval=0.1,
    )
    sup.set_listener(lambda snap: None)
    await sup.start()
    for _ in range(50):
        await asyncio.sleep(0.05)
        if sup.mode == "websocket":
            break
    assert sup.mode == "websocket"
    await sup.stop()
