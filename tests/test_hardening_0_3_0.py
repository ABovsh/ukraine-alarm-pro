"""Hardening tests for 0.3.0 — cold-start seeding, honest watchdog, payload guard.

Grounded in a live probe of the production feed (2026-07-25): the `updateMap`
channel returns an EMPTY history on connect and the next push arrived 144 s
later, so a fresh connection is blind for minutes.
"""

import asyncio

import pytest
from aiohttp import ClientSession
from homeassistant.core import HomeAssistant

# The tests directory is not a package; pytest puts it on sys.path.
from test_entities import _setup
from test_ws_transport import FakeAlarmServer

from custom_components.ukraine_alarm_pro.api.errors import TransportError
from custom_components.ukraine_alarm_pro.api.supervisor import TransportSupervisor
from custom_components.ukraine_alarm_pro.api.ws import WsTransport
from custom_components.ukraine_alarm_pro.models import parse_alert_payload

SNAP_A = parse_alert_payload(
    {"alerts": [{"regionId": "31", "activeAlerts": [{"type": "AIR", "lastUpdate": "a"}]}]}
)
SNAP_B = parse_alert_payload(
    {"alerts": [{"regionId": "703", "activeAlerts": [{"type": "AIR", "lastUpdate": "b"}]}]}
)


class SilentWs:
    """Connects fine and never publishes — the real feed's quiet state."""

    def __init__(self, snap=None, lifetime=None):
        self.streams = 0
        self.closed = 0
        self._snap = snap
        self._lifetime = lifetime

    async def stream(self):
        self.streams += 1
        if self._snap is not None:
            yield self._snap
        if self._lifetime is not None:
            await asyncio.sleep(self._lifetime)
            raise TransportError("server dropped an idle connection")
        await asyncio.sleep(3600)

    async def close(self):
        self.closed += 1


class Poll:
    def __init__(self, snap=SNAP_A, fail=False):
        self.snap = snap
        self.fail = fail
        self.fetches = 0

    async def fetch(self):
        self.fetches += 1
        if self.fail:
            raise TransportError("poll down")
        return self.snap


def _sup(ws, poll, **kw):
    kw.setdefault("seed_delay", 100.0)
    kw.setdefault("poll_interval", 3600.0)
    kw.setdefault("watchdog_interval", 3600.0)
    return TransportSupervisor(ws=ws, poll=poll, **kw)


async def test_startup_seeds_snapshot_from_poll_when_ws_has_no_history():
    """Without this, every restart leaves the region entities blank for minutes."""
    ws, poll = SilentWs(), Poll()
    sup = _sup(ws, poll, seed_delay=0.01)
    updates = []
    sup.set_listener(updates.append)
    await sup.start()
    await asyncio.sleep(0.1)
    assert updates == [SNAP_A]
    assert sup.mode == "websocket"
    await sup.stop()


async def test_seed_is_skipped_when_the_websocket_delivers_first():
    ws, poll = SilentWs(snap=SNAP_B), Poll()
    sup = _sup(ws, poll, seed_delay=0.05)
    updates = []
    sup.set_listener(updates.append)
    await sup.start()
    await asyncio.sleep(0.15)
    assert poll.fetches == 0
    assert updates == [SNAP_B]
    await sup.stop()


async def test_quiet_feed_is_not_mistaken_for_a_dead_websocket():
    """A poll that agrees with the last push proves the country is simply calm."""
    ws, poll = SilentWs(snap=SNAP_A), Poll(snap=SNAP_A)
    sup = _sup(ws, poll, stale_after=0.03, watchdog_interval=0.02)
    updates = []
    sup.set_listener(updates.append)
    await sup.start()
    await asyncio.sleep(0.2)
    assert poll.fetches >= 1
    assert ws.closed == 0
    # The cross-check keeps the data fresh instead of letting it age out.
    assert sup.seconds_since_snapshot < 0.1
    assert len(updates) > 1
    await sup.stop()


async def test_cross_check_ignores_how_each_source_lists_calm_regions():
    """The WS may spell out cleared regions; the poll endpoint omits them."""
    ws_snap = parse_alert_payload(
        {
            "alerts": [
                {"regionId": "31", "activeAlerts": [{"type": "AIR", "lastUpdate": "a"}]},
                {"regionId": "703", "activeAlerts": []},
            ]
        }
    )
    ws, poll = SilentWs(snap=ws_snap), Poll(snap=SNAP_A)
    sup = _sup(ws, poll, stale_after=0.03, watchdog_interval=0.02)
    sup.set_listener(lambda snap: None)
    await sup.start()
    await asyncio.sleep(0.2)
    assert poll.fetches >= 1
    assert ws.closed == 0
    await sup.stop()


async def test_watchdog_reconnects_when_poll_proves_the_websocket_missed_updates():
    ws, poll = SilentWs(snap=SNAP_A), Poll(snap=SNAP_B)
    sup = _sup(ws, poll, stale_after=0.03, watchdog_interval=0.02)
    updates = []
    sup.set_listener(updates.append)
    await sup.start()
    await asyncio.sleep(0.15)
    assert ws.closed >= 1
    assert SNAP_B in updates
    await sup.stop()


async def test_watchdog_restarts_ws_when_the_poll_fallback_also_fails():
    ws, poll = SilentWs(snap=SNAP_A), Poll(fail=True)
    sup = _sup(ws, poll, stale_after=0.03, watchdog_interval=0.02)
    sup.set_listener(lambda snap: None)
    await sup.start()
    await asyncio.sleep(0.15)
    assert ws.closed >= 1
    await sup.stop()


async def test_long_lived_ws_sessions_do_not_degrade_to_polling():
    """The server drops idle sockets (2 h token TTL); that is not a broken WS."""
    ws, poll = SilentWs(lifetime=0.06), Poll()
    sup = _sup(
        ws,
        poll,
        max_ws_failures=3,
        ws_retry_delay=0.01,
        ws_probe_interval=3600,
        healthy_session=0.05,
    )
    sup.set_listener(lambda snap: None)
    await sup.start()
    await asyncio.sleep(0.4)
    assert ws.streams >= 3
    assert sup.mode == "websocket"
    await sup.stop()


@pytest.mark.parametrize(
    "raw",
    [{}, {"alerts": "boom"}, {"alerts": {"31": []}}, "nope", 5, None],
)
def test_malformed_payload_is_rejected_instead_of_reported_as_all_clear(raw):
    with pytest.raises(ValueError):
        parse_alert_payload(raw)


@pytest.mark.parametrize("raw", [{"alerts": []}, []])
def test_empty_but_well_formed_payload_stays_valid(raw):
    assert parse_alert_payload(raw).regions == {}


async def test_ws_stream_raises_on_a_malformed_publication():
    srv = await FakeAlarmServer().start()
    try:
        async with ClientSession() as session:
            transport = WsTransport(session, map_url=srv.page_url)
            gen = transport.stream()
            await asyncio.wait_for(anext(gen), timeout=5)  # initial snapshot
            await srv.pushes.put({"unexpected": "shape"})
            with pytest.raises(TransportError):
                await asyncio.wait_for(anext(gen), timeout=5)
    finally:
        await srv.close()


async def test_stale_sensor_attributes_do_not_change_between_pushes(
    hass: HomeAssistant, enable_custom_integrations
):
    """A per-minute counter attribute would write a recorder row every tick."""
    _, push = await _setup(hass)
    push(parse_alert_payload({"alerts": []}))
    await hass.async_block_till_done()
    attrs = hass.states.get("binary_sensor.uap_data_stale").attributes
    assert "seconds_since_update" not in attrs
    assert attrs["last_update"] is not None
