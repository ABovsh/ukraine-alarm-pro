"""Adversarial RC regressions: clocks, retention and card lifecycle."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import WSMessage, WSMsgType
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_capture_events
from test_air_alert_levels import payload as air_payload
from test_alert_history import FakeStore, _hist, _payload
from test_card_browser import page as browser_page_fixture
from test_entities import _setup

from custom_components.ukraine_alarm_pro.api.errors import TransportError
from custom_components.ukraine_alarm_pro.api.ws import WsTransport
from custom_components.ukraine_alarm_pro.models import (
    Alert,
    Snapshot,
    parse_alert_payload,
    region_view,
)

T0 = datetime(2026, 10, 5, 12, tzinfo=UTC)
page = browser_page_fixture


@pytest.mark.parametrize("clearing", [False, True])
async def test_region_details_precede_binary_alert_transitions_in_any_platform_order(
    hass, enable_custom_integrations, clearing, monkeypatch
):
    entry, push = await _setup(hass)
    active = parse_alert_payload(air_payload("Red", region="31", reason="Missile risk"))
    push(active if clearing else Snapshot())
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    # Reproduce the CI platform order: binary sensors registered before sensors.
    coordinator._listeners = dict(sorted(
        coordinator._listeners.items(),
        key=lambda item: (
            type(getattr(item[1][0], "__self__", None)).__name__
            != "RegionAlertBinarySensor"
        ),
    ))
    writes = {}
    for listener, _ in coordinator._listeners.values():
        entity = getattr(listener, "__self__", None)
        if type(entity).__name__ in {
            "RegionThreatSensor", "AlertStartedSensor", "AirAlertLevelSensor"
        } and entity._region_id == "31":
            writes[entity.entity_id] = MagicMock(wraps=entity.async_write_ha_state)
            monkeypatch.setattr(entity, "async_write_ha_state", writes[entity.entity_id])
    captured = async_capture_events(hass, EVENT_STATE_CHANGED)
    push(Snapshot() if clearing else active)
    await hass.async_block_till_done()
    changed = [event.data["entity_id"] for event in captured]
    alert_index = changed.index("binary_sensor.uap_31_alert")
    for suffix in ("threat", "alert_started", "air_alert_level"):
        entity_id = f"sensor.uap_31_{suffix}"
        assert changed.index(entity_id) < alert_index
        assert changed.count(entity_id) == 1
        assert writes[entity_id].call_count == 1


async def test_percentage_zero_remains_numeric_without_statistics_or_duplicate_events(
    hass, enable_custom_integrations
):
    entry, push = await _setup(hass)
    push(Snapshot())
    await hass.async_block_till_done()
    history = entry.runtime_data.history
    now = dt_util.utcnow()
    history._live_since["31"] = (now - timedelta(days=8)).isoformat()
    history.confirm(["31"], now)
    captured = async_capture_events(hass, EVENT_STATE_CHANGED)
    with patch.object(dt_util, "utcnow", return_value=now):
        for _ in range(20):
            entry.runtime_data.async_update_percentages()
        await hass.async_block_till_done()
    for window in ("24h", "7d"):
        entity_id = f"sensor.uap_31_alert_percentage_{window}"
        state = hass.states.get(entity_id)
        assert float(state.state) == 0.0
        assert state.attributes["coverage_complete"] is True
        assert "state_class" not in state.attributes
        assert len([e for e in captured if e.data["entity_id"] == entity_id]) == 1
    # The released country-wide series keeps its statistics contract.
    assert (
        hass.states.get("sensor.uap_active_regions").attributes["state_class"]
        == "measurement"
    )


@pytest.mark.parametrize("event_type", ["cleared", "updated"])
async def test_clock_rollback_cannot_save_a_negative_episode(event_type):
    store = FakeStore()
    history, clock = _hist(store, now=T0)
    await history.async_load()
    history.handle_event("started", _payload("started", T0, active=True))
    clock["now"] = T0 - timedelta(hours=1)
    history.handle_event(
        event_type, _payload(event_type, clock["now"], active=event_type == "updated")
    )
    [episode] = history.history("31", 10)
    assert episode["observed_started_at"] == clock["now"].isoformat()
    assert episode["observed_duration_seconds"] == (None if event_type == "updated" else 0)
    assert episode["had_gap"] is True
    assert episode["source_start_known"] is False
    await history.async_flush()
    restored, _ = _hist(store, now=clock["now"])
    await restored.async_load()
    assert restored.history("31", 10) == [episode]


@pytest.mark.parametrize("source", ["gaps", "official_spans", "episodes"])
async def test_retention_frontier_cannot_regress_when_another_source_is_trimmed(source):
    history, clock = _hist(now=T0 - timedelta(days=8), max_episodes=1)
    await history.async_load()
    history.confirm(["31"], clock["now"])
    for hours in (3, 1):
        start = T0 - timedelta(hours=hours)
        history.handle_event("started", _payload("started", start, active=True))
        history.handle_event(
            "cleared", _payload("cleared", start + timedelta(minutes=1), active=False)
        )
    frontier = history._retained_from["31"]
    # Older gap history hits its own cap on the next daily prune.
    clock["now"] = T0
    if source == "episodes":
        history.merge_official(
            "31", [(T0 - timedelta(days=3), T0 - timedelta(days=2))],
            window_start=T0 - timedelta(days=8),
        )
    else:
        getattr(history, f"_{source}")["31"] = [
            ((T0 - timedelta(days=3)).isoformat(), (T0 - timedelta(days=2)).isoformat()),
            ((T0 - timedelta(days=2)).isoformat(), (T0 - timedelta(days=1)).isoformat()),
        ]
    history._prune()
    assert history._retained_from["31"] == frontier
    # The gaps have expired out of this window, but the missing episode has not.
    result = history.rolling("31", 86400)
    assert result["quality"] == "truncated"
    assert result["percentage"] is None


async def test_card_reconfiguration_releases_old_inflight_request(page):
    await page.evaluate("""window.hass=makeHass(); window.pending=[];
      hass.callWS=(request)=>{calls.push(request); return new Promise(resolve=>pending.push(resolve));};
      window.c=makeCard(hass,'status');""")
    await page.clock.run_for(200)
    await page.wait_for_function("pending.length===1")
    assert await page.evaluate("calls.length") == 1
    await page.evaluate("c.setConfig({entity:'binary_sensor.uap_31_alert',layout:'full'})")
    await page.clock.run_for(30000)
    assert await page.evaluate("calls.map(call=>call.service)") == ["get_history", "get_summary"]
    await page.evaluate("pending[0]({response:{episodes:[]}})")
    assert await page.evaluate("c._loading") is True
    await page.evaluate("pending[1]({response:{last_episode:[],rolling_24h:{},rolling_7d:{}}})")
    await page.wait_for_function("c._stats?.summary !== null && c._loading===false")


async def test_card_discovers_siblings_that_arrive_after_the_alert_state(page):
    await page.evaluate("""window.hass=makeHass(); window.late={...hass.states};
      hass.states={'binary_sensor.uap_31_alert':late['binary_sensor.uap_31_alert']};
      window.c=makeCard(hass,'status');""")
    await page.clock.run_for(200)
    await page.evaluate("""hass.states=late;
      hass.states['binary_sensor.uap_data_stale'].state='on'; c.hass={...hass};""")
    assert await page.evaluate("c._entities().stale") == "binary_sensor.uap_data_stale"
    assert "Data is stale" in await page.evaluate("c.shadowRoot.textContent")


async def test_card_connection_change_cannot_accept_the_old_connection_reply(page):
    await page.evaluate("""window.first=makeHass(); window.oldReply=null;
      first.callWS=(request)=>{calls.push(request); return new Promise(resolve=>oldReply=resolve);};
      window.c=makeCard(first);""")
    await page.clock.run_for(200)
    # IntersectionObserver delivery is asynchronous even with the fake clock.
    # Establish the old in-flight request before replacing its connection.
    await page.wait_for_function("calls.length===1 && typeof oldReply==='function'")
    await page.evaluate("window.second=makeHass(); second.connection={}; c.hass=second")
    await page.clock.run_for(200)
    assert await page.evaluate("calls.length") == 2
    await page.wait_for_function("c._stats?.summary?.rolling_24h?.count===60")
    await page.evaluate("oldReply({response:{last_episode:[],rolling_24h:{count:999},rolling_7d:{}}})")
    assert await page.evaluate("c._stats.summary.rolling_24h.count") == 60


@pytest.mark.parametrize("stamp", ["2026-10-05T12:00:00.000000Z", "2026-10-05T15:00:00+03:00"])
def test_snapshot_signature_and_declaration_deduplication_agree(stamp):
    # Identical instants spelled at different precision are one declaration.
    alert = Alert("AIR", "2026-10-05T12:00:00Z", "31")
    precise = Alert("AIR", stamp, "31")
    repeated = Snapshot(regions={"31": [alert, precise]})
    single = Snapshot(regions={"31": [alert]})
    assert repeated.signature == single.signature
    assert len(region_view(repeated, "31").alerts) == len(region_view(single, "31").alerts) == 1


def test_signature_does_not_hide_distinct_undated_declarations():
    first = Alert("AIR", "broken-a", "31")
    second = Alert("AIR", "broken-b", "31")
    single = Snapshot(regions={"31": [first]})
    repeated = Snapshot(regions={"31": [first, second]})
    assert len(region_view(repeated, "31").alerts) == 2
    assert repeated.signature != single.signature


async def test_deeply_nested_handshake_reply_closes_owned_socket():
    socket = AsyncMock()
    socket.closed = False
    socket.receive.return_value = WSMessage(WSMsgType.TEXT, "[" * 20000 + "]" * 20000, "")
    session = MagicMock()
    session.ws_connect = AsyncMock(return_value=socket)
    transport = WsTransport(session)
    transport._mint_token = AsyncMock(return_value=("token", "ws://localhost"))
    try:
        with pytest.raises(TransportError):
            await anext(transport.stream())
        socket.close.assert_awaited_once()
        assert transport._ws is None
    finally:
        await transport.close()
