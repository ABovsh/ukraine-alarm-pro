"""Persistence, coverage and rolling statistics regressions, with literal clocks."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from aiohttp import ClientSession
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)
from test_alert_history import FakeStore, _hist, _payload
from test_entities import _setup
from test_ws_transport import FakeAlarmServer

from custom_components.ukraine_alarm_pro.api.errors import RateLimited
from custom_components.ukraine_alarm_pro.api.poll import (
    PollTransport,
    retry_after_seconds,
)
from custom_components.ukraine_alarm_pro.api.supervisor import TransportSupervisor
from custom_components.ukraine_alarm_pro.api.ws import WsTransport
from custom_components.ukraine_alarm_pro.models import Snapshot, parse_alert_payload

T0 = datetime(2026, 10, 4, 12, tzinfo=UTC)


async def test_snapshot_failed_write_retries(hass, enable_custom_integrations):
    entry, push = await _setup(hass)
    coordinator = entry.runtime_data
    coordinator._store = FakeStore(fail=1)
    push(Snapshot())
    await coordinator.async_save_now()
    await coordinator.async_save_now()
    assert coordinator._store.saves == 1


async def test_snapshot_read_error_does_not_break_setup(
    hass, enable_custom_integrations
):
    with patch(
        "custom_components.ukraine_alarm_pro.coordinator.Store.async_load",
        AsyncMock(side_effect=OSError("disk error")),
    ):
        entry, push = await _setup(hass)
    push(Snapshot())
    assert entry.runtime_data.data is not None


async def test_unchanged_snapshot_saved_with_confirmation_time(
    hass, enable_custom_integrations
):
    entry, push = await _setup(hass)
    coordinator = entry.runtime_data
    store = coordinator._store = FakeStore()
    with patch.object(dt_util, "utcnow", return_value=T0):
        push(Snapshot())
        await coordinator.async_save_now()
    with patch.object(dt_util, "utcnow", return_value=T0 + timedelta(hours=7)):
        push(Snapshot())
        await coordinator.async_save_now()
    assert store.saves == 2
    assert store.data["confirmed_at"] == (T0 + timedelta(hours=7)).isoformat()
    with patch.object(dt_util, "utcnow", return_value=T0 + timedelta(hours=9)):
        push(
            parse_alert_payload(
                {"alerts": [{"regionId": "31", "activeAlerts": [{"type": "AIR"}]}]}
            )
        )
    with patch.object(dt_util, "utcnow", return_value=T0 + timedelta(hours=20)):
        await coordinator.async_save_now()
    assert store.data["confirmed_at"] == (T0 + timedelta(hours=9)).isoformat()


async def test_snapshot_concurrent_writes_are_serial(hass, enable_custom_integrations):
    entry, push = await _setup(hass)
    coordinator = entry.runtime_data
    entered, release = asyncio.Event(), asyncio.Event()
    writes = []

    async def save(data):
        writes.append(data)
        entered.set()
        await release.wait()

    coordinator._store = FakeStore()
    coordinator._store.async_save = save
    push(Snapshot())
    first = asyncio.create_task(coordinator.async_save_now())
    await entered.wait()
    push(
        parse_alert_payload(
            {"alerts": [{"regionId": "31", "activeAlerts": [{"type": "AIR"}]}]}
        )
    )
    second = asyncio.create_task(coordinator.async_save_now())
    await asyncio.sleep(0)
    assert len(writes) == 1
    release.set()
    await asyncio.gather(first, second)
    assert "31" in writes[-1]["regions"]


async def test_timestamp_rounding_and_callback_gate(hass, enable_custom_integrations):
    entry, push = await _setup(hass)
    with patch.object(dt_util, "utcnow", return_value=T0 + timedelta(seconds=1)):
        push(Snapshot())
        await hass.async_block_till_done()
    first = hass.states.get("sensor.uap_last_update")
    assert dt_util.parse_datetime(first.state) == T0
    with patch.object(dt_util, "utcnow", return_value=T0 + timedelta(seconds=10)):
        push(
            parse_alert_payload(
                {"alerts": [{"regionId": "31", "activeAlerts": [{"type": "AIR"}]}]}
            )
        )
        await hass.async_block_till_done()
    assert hass.states.get("sensor.uap_last_update").last_updated == first.last_updated
    assert entry.runtime_data.last_push == T0 + timedelta(seconds=10)


@pytest.mark.parametrize("seconds,expected", [(0, 0.0), (3600, 4.2), (86400, 100.0)])
async def test_rolling_percentage_fixed_denominator(seconds, expected):
    history, clock = _hist(now=T0 - timedelta(days=8))
    await history.async_load()
    history.confirm(["31"], clock["now"])
    if seconds:
        start = T0 - timedelta(seconds=seconds)
        history.handle_event("started", _payload("started", start, active=True))
    history.confirm(["31"], T0)
    clock["now"] = T0
    result = history.rolling("31", 86400)
    assert result["percentage"] == expected
    assert result["window_seconds"] == 86400
    assert result["coverage_complete"] is True


async def test_official_air_history_is_not_all_threat_coverage():
    history, _ = _hist(now=T0)
    await history.async_load()
    history.merge_official("31", [], window_start=T0 - timedelta(days=90))
    history.mark_synced(T0, ["31"])
    assert history.rolling("31", 86400)["percentage"] is None


async def test_quiet_gap_persisted_and_expires_from_window():
    store = FakeStore()
    history, clock = _hist(store, now=T0 - timedelta(days=8))
    await history.async_load()
    history.confirm(["31"], clock["now"])
    history.confirm(["31"], T0 - timedelta(hours=2))
    history.mark_gap(["31"])
    history.confirm(["31"], T0 - timedelta(hours=1))
    clock["now"] = T0
    result = history.rolling("31", 86400)
    assert result["percentage"] is None
    assert result["gap_seconds"] == 3600
    await history.async_flush()
    restored, _ = _hist(store, now=T0)
    await restored.async_load()
    assert restored.rolling("31", 604800)["percentage"] is None
    clock["now"] = T0 + timedelta(days=1)
    assert history.rolling("31", 86400)["percentage"] == 0.0


async def test_many_regions_do_not_consume_each_others_retention():
    history, _ = _hist(now=T0, max_episodes=3)
    await history.async_load()
    for rid in ("31", "14", "695"):
        for i in range(3):
            start = T0 - timedelta(hours=5 - i)
            history.handle_event(
                "started", _payload("started", start, active=True, region=rid)
            )
            history.handle_event(
                "cleared",
                _payload(
                    "cleared", start + timedelta(minutes=5), active=False, region=rid
                ),
            )
    assert all(len(history.history(rid, 100)) == 3 for rid in ("31", "14", "695"))


async def test_rolling_more_than_fifty_episodes_and_overlap_union():
    history, clock = _hist(now=T0 - timedelta(days=8))
    await history.async_load()
    history.confirm(["31"], clock["now"])
    for i in range(60):
        start = T0 - timedelta(hours=20) + timedelta(minutes=10 * i)
        history.handle_event("started", _payload("started", start, active=True))
        history.handle_event(
            "cleared", _payload("cleared", start + timedelta(minutes=1), active=False)
        )
    clock["now"] = T0
    result = history.rolling("31", 86400)
    assert result["percentage"] == 4.2
    assert result["count"] == 60
    official = [
        (T0 - timedelta(hours=20), T0 - timedelta(hours=20) + timedelta(minutes=1))
    ] * 2
    history.merge_official("31", official, window_start=T0 - timedelta(days=7))
    assert history.rolling("31", 86400)["percentage"] == 4.2


async def test_percentage_entities_exist_and_report_unknown(
    hass, enable_custom_integrations
):
    _, push = await _setup(hass)
    push(Snapshot())
    await hass.async_block_till_done()
    for window in ("24h", "7d"):
        state = hass.states.get(f"sensor.uap_31_alert_percentage_{window}")
        assert state is not None
        assert state.state == "unknown"
        assert state.attributes["unit_of_measurement"] == "%"
        assert "state_class" not in state.attributes
        assert state.attributes["coverage_complete"] is False


async def test_http_calls_share_the_original_revision():
    poll, ws = AsyncMock(), AsyncMock()
    entered, release = asyncio.Event(), asyncio.Event()

    async def fetch():
        entered.set()
        await release.wait()
        return Snapshot()

    poll.fetch.side_effect = fetch
    supervisor = TransportSupervisor(ws, poll)
    supervisor._running = True
    first = asyncio.create_task(supervisor._fetch_poll("seed"))
    await entered.wait()
    # This new WS message must invalidate ALL users of the old HTTP request,
    # including a waiter that joins the shared request after the WS message.
    supervisor._emit(Snapshot())
    second = asyncio.create_task(supervisor._fetch_poll("watchdog"))
    await asyncio.sleep(0)
    release.set()
    assert await first is None
    assert await second is None
    assert poll.fetch.await_count == 1
    await supervisor.stop()


async def test_backfill_retries_only_failed_chunks(
    hass, enable_custom_integrations, monkeypatch
):
    entry, _ = await _setup(hass)
    coordinator = entry.runtime_data
    fetch = AsyncMock(side_effect=[[], OSError("history down")])
    monkeypatch.setattr("custom_components.ukraine_alarm_pro.backfill._fetch", fetch)
    with patch.object(dt_util, "utcnow", return_value=T0):
        await coordinator.async_backfill_history()
    # A successful first chunk advances that root's persisted cursor.
    calls = fetch.call_args_list
    first_root = calls[0].args[1][0]
    failed_start = calls[1].args[2]
    fetch.reset_mock()
    fetch.side_effect = None
    fetch.return_value = []
    with patch.object(dt_util, "utcnow", return_value=T0):
        await coordinator.async_backfill_history()
    retry = next(call for call in fetch.call_args_list if call.args[1] == [first_root])
    assert retry.args[2] == failed_start
    assert (retry.args[3] - retry.args[2]).total_seconds() <= 7 * 86400


async def test_ws_close_cancels_heartbeat_after_close_frame():
    server = await FakeAlarmServer().start()
    try:
        async with ClientSession() as session:
            transport = WsTransport(session, map_url=server.page_url)
            stream = transport.stream()
            await anext(stream)
            socket = transport._ws
            await transport.close()
            await asyncio.sleep(0)
            timer = socket._heartbeat_cb
            assert timer is None or timer.cancelled()
            await stream.aclose()
    finally:
        await server.close()


@pytest.mark.parametrize(
    "value,expected",
    [("120", 120), ("0", 1), ("9000", 3600), ("NaN", 60), ("junk", 60)],
)
def test_retry_after_bounded(value, expected):
    assert retry_after_seconds(value) == expected


async def test_http_429_is_not_retried_before_deadline():
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    calls = []

    async def limited(request):
        calls.append(request)
        return web.Response(status=429, headers={"Retry-After": "120"})

    app = web.Application()
    app.router.add_get("/alerts", limited)
    async with TestServer(app) as server, ClientSession() as session:
        transport = PollTransport(
            session, base_url=str(server.make_url("/")).rstrip("/")
        )
        for _ in range(2):
            with pytest.raises(RateLimited) as error:
                await transport.fetch()
            assert 119 <= error.value.retry_after <= 120
        assert len(calls) == 1


async def test_utc_jumps_do_not_change_transport_freshness(
    hass, enable_custom_integrations
):
    entry, push = await _setup(hass)
    with patch.object(dt_util, "utcnow", return_value=T0):
        push(Snapshot())
    for jump in (timedelta(hours=3), timedelta(hours=-3)):
        with patch.object(dt_util, "utcnow", return_value=T0 + jump):
            assert entry.runtime_data.is_stale is False
            push(Snapshot())
            assert entry.runtime_data.is_stale is False
            assert (
                entry.runtime_data.history.rolling("31", 86400, now=T0 + jump)[
                    "percentage"
                ]
                is None
            )


@pytest.mark.parametrize(
    "start,end,expected_seconds,expected_pct",
    [
        (
            datetime(2026, 3, 28, 22, tzinfo=UTC),
            datetime(2026, 3, 29, 21, tzinfo=UTC),
            82800,
            95.8,
        ),
        (
            datetime(2026, 10, 24, 21, tzinfo=UTC),
            datetime(2026, 10, 25, 22, tzinfo=UTC),
            90000,
            100.0,
        ),
    ],
)
async def test_dst_calendar_days_and_fixed_rolling_window(
    hass, start, end, expected_seconds, expected_pct
):
    await hass.config.async_set_time_zone("Europe/Kyiv")
    history, clock = _hist(now=end - timedelta(days=8))
    await history.async_load()
    history.confirm(["31"], clock["now"])
    history.handle_event("started", _payload("started", start, active=True))
    history.handle_event("cleared", _payload("cleared", end, active=False))
    clock["now"] = end
    day = start.astimezone(ZoneInfo("Europe/Kyiv")).date().isoformat()
    bucket = next(d for d in history.summary("31", 7)["daily"] if d["date"] == day)
    assert bucket["observed_duration_seconds"] == expected_seconds
    assert history.rolling("31", 86400)["percentage"] == expected_pct
    assert history.rolling("31", 604800)["window_seconds"] == 604800


async def test_sensor_service_equality_and_no_duplicate_state_events(
    hass, enable_custom_integrations
):
    entry, push = await _setup(hass)
    push(Snapshot())
    await hass.async_block_till_done()
    history = entry.runtime_data.history
    now = dt_util.utcnow()
    history._live_since["31"] = (now - timedelta(days=8)).isoformat()
    history._confirmed["31"] = (now - timedelta(hours=3)).isoformat()
    history.handle_event(
        "started", _payload("started", now - timedelta(hours=2), active=True)
    )
    history.handle_event(
        "cleared", _payload("cleared", now - timedelta(hours=1), active=False)
    )
    history.confirm(["31"], now)
    captured = async_capture_events(hass, EVENT_STATE_CHANGED)
    with patch.object(dt_util, "utcnow", return_value=now):
        for _ in range(20):
            entry.runtime_data.async_update_percentages()
        await hass.async_block_till_done()
    response = await hass.services.async_call(
        "ukraine_alarm_pro",
        "get_summary",
        {"region_id": "31", "days": 7},
        blocking=True,
        return_response=True,
    )
    for window, pct in (("24h", 4.2), ("7d", 0.6)):
        entity = f"sensor.uap_31_alert_percentage_{window}"
        state = hass.states.get(entity)
        assert float(state.state) == pct == response[f"rolling_{window}"]["percentage"]
        assert (
            len([event for event in captured if event.data["entity_id"] == entity]) == 1
        )
        assert "calculated_at" not in state.attributes
        assert "state_class" not in state.attributes


async def test_one_shared_percentage_timer(
    hass, enable_custom_integrations, monkeypatch
):
    entry, push = await _setup(hass)
    # The independent backfill job also starts at five minutes and may
    # legitimately recalculate percentages after journal changes.
    monkeypatch.setattr(entry.runtime_data, "_async_backfill_chunks", AsyncMock())
    push(Snapshot())
    listener = MagicMock()
    remove = entry.runtime_data.add_percentage_listener(listener)
    now = dt_util.utcnow()
    async_fire_time_changed(hass, now + timedelta(seconds=299))
    await hass.async_block_till_done()
    assert listener.call_count == 0
    async_fire_time_changed(hass, now + timedelta(seconds=301))
    await hass.async_block_till_done()
    assert listener.call_count == 1
    remove()


async def test_region_views_are_retained_for_unaffected_regions(
    hass, enable_custom_integrations
):
    entry, push = await _setup(hass)
    push(Snapshot())
    coordinator = entry.runtime_data
    view = coordinator.region_view("703", ["75", "14"], [])
    push(
        parse_alert_payload(
            {"alerts": [{"regionId": "31", "activeAlerts": [{"type": "AIR"}]}]}
        )
    )
    assert coordinator.region_view("703", ["75", "14"], []) is view


async def test_history_write_uses_immutable_snapshot_and_serial_lock():
    history, _ = _hist(now=T0)
    await history.async_load()
    history.handle_event("started", _payload("started", T0, active=True))
    entered, release = asyncio.Event(), asyncio.Event()
    writes = []

    async def save(data):
        writes.append(data)
        entered.set()
        await release.wait()

    history._store.async_save = save
    first = asyncio.create_task(history.async_flush())
    await entered.wait()
    history.handle_event(
        "cleared", _payload("cleared", T0 + timedelta(minutes=1), active=False)
    )
    second = asyncio.create_task(history.async_flush())
    await asyncio.sleep(0)
    assert "31" in writes[0]["active"]
    assert len(writes) == 1
    release.set()
    await asyncio.gather(first, second)
    assert len(writes[-1]["episodes"]) == 1
    assert history._version == history._saved_version


async def test_pruning_announces_incomplete_history():
    history, clock = _hist(now=T0 - timedelta(days=8), max_episodes=1)
    await history.async_load()
    history.confirm(["31"], clock["now"])
    for hours in (3, 1):
        start = T0 - timedelta(hours=hours)
        history.handle_event("started", _payload("started", start, active=True))
        history.handle_event(
            "cleared", _payload("cleared", start + timedelta(minutes=1), active=False)
        )
    clock["now"] = T0
    assert history.rolling("31", 86400)["quality"] == "truncated"
    assert history.rolling("31", 86400)["percentage"] is None


async def test_hundreds_of_regions_have_independent_indexes():
    history, clock = _hist(now=T0 - timedelta(days=8))
    await history.async_load()
    region_ids = [str(rid) for rid in range(500)]
    history.confirm(region_ids, clock["now"])
    for rid in region_ids:
        history.handle_event(
            "started",
            _payload("started", T0 - timedelta(hours=2), active=True, region=rid),
        )
        history.handle_event(
            "cleared",
            _payload("cleared", T0 - timedelta(hours=1), active=False, region=rid),
        )
    clock["now"] = T0
    assert len(history._index) == 500
    assert all(history.rolling(rid, 86400)["percentage"] == 4.2 for rid in region_ids)


async def test_staleness_is_published_before_regional_transitions(
    hass, enable_custom_integrations
):
    import time

    entry, push = await _setup(hass)
    push(Snapshot())
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    # Platform setup order must not decide whether an automation sees fresh
    # data. Arrange the health callback last in the ordinary coordinator list.
    listeners = coordinator._listeners
    ordered = sorted(
        listeners.items(),
        key=lambda item: (
            type(getattr(item[1][0], "__self__", None)).__name__ == "DataStaleSensor"
        ),
    )
    coordinator._listeners = dict(ordered)
    coordinator._last_push_monotonic = time.monotonic() - 3600
    captured = async_capture_events(hass, EVENT_STATE_CHANGED)
    coordinator.async_set_updated_data(
        parse_alert_payload(
            {"alerts": [{"regionId": "31", "activeAlerts": [{"type": "AIR"}]}]}
        )
    )
    await hass.async_block_till_done()
    changed = [event.data["entity_id"] for event in captured]
    assert changed.index("binary_sensor.uap_data_stale") < changed.index(
        "binary_sensor.uap_31_alert"
    )


async def test_completed_backfill_checkpoint_recovers_after_power_loss():
    store = FakeStore()
    history, _ = _hist(store, now=T0)
    await history.async_load()
    history.begin_backfill(["31"], T0)
    history.advance_cursor(["31"], T0)
    # Last chunk is durable, but power disappears before finish_backfill flushes.
    await history.async_flush()
    restored, _ = _hist(store, now=T0 + timedelta(days=1, seconds=1))
    await restored.async_load()
    window = restored.backfill_window("31", T0 + timedelta(days=1, seconds=1))
    assert window is not None
    assert window[1] == T0 + timedelta(days=1, seconds=1)
    assert "31" not in restored._backfill_targets


async def test_finished_backfill_marker_is_immediately_durable(
    hass, enable_custom_integrations, monkeypatch
):
    entry, _ = await _setup(hass)
    coordinator = entry.runtime_data
    coordinator.history._store = FakeStore()
    monkeypatch.setattr(
        "custom_components.ukraine_alarm_pro.backfill._fetch",
        AsyncMock(return_value=[]),
    )
    await coordinator.async_backfill_history()
    assert coordinator.history._store.data["backfill_targets"] == {}
