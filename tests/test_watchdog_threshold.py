"""N3: a silent WebSocket is cross-checked sooner while selected regions are under alert.

The threshold is FACTOR x the median interval between WebSocket publications
of the last hour, bounded by CROSS_CHECK_MIN_SECONDS..CROSS_CHECK_AFTER_SECONDS,
and only with at least CROSS_CHECK_MIN_INTERVALS intervals. Fake clock: the
supervisor module sees a monotonic clock and a sleep that only advance it.
"""

import asyncio
import itertools
import types
from unittest.mock import AsyncMock

import pytest

from custom_components.ukraine_alarm_pro.api import supervisor as supervisor_mod
from custom_components.ukraine_alarm_pro.api.supervisor import (
    MODE_WS,
    TransportSupervisor,
)
from custom_components.ukraine_alarm_pro.const import (
    CROSS_CHECK_AFTER_SECONDS,
    CROSS_CHECK_MIN_SECONDS,
    STALE_AFTER_SECONDS,
)
from custom_components.ukraine_alarm_pro.models import parse_alert_payload

CLEAR = parse_alert_payload({"alerts": []})
WATCHDOG_TICK = supervisor_mod.DEFAULT_WATCHDOG_INTERVAL


@pytest.fixture
def clock(monkeypatch):
    now = [10_000.0]
    real_sleep = asyncio.sleep

    async def fake_sleep(delay, *args):
        now[0] += delay
        await real_sleep(0)

    # Module-local fakes: the event loop keeps its real clock.
    monkeypatch.setattr(
        supervisor_mod, "time", types.SimpleNamespace(monotonic=lambda: now[0])
    )
    fake_asyncio = types.SimpleNamespace(**vars(asyncio))
    fake_asyncio.sleep = fake_sleep
    monkeypatch.setattr(supervisor_mod, "asyncio", fake_asyncio)
    return now


def _sup(poll=None, alert=True):
    sup = TransportSupervisor(
        ws=AsyncMock(),
        poll=poll or AsyncMock(),
        stale_after=CROSS_CHECK_AFTER_SECONDS,
    )
    sup.alert_active = lambda: alert
    sup._running = True
    sup.mode = MODE_WS
    return sup


def _publish(sup, clock, count, every):
    for _ in range(count):
        clock[0] += every
        sup._accept_ws(CLEAR)


def test_the_margin_still_fits_before_stale():
    assert CROSS_CHECK_AFTER_SECONDS + WATCHDOG_TICK + 30 < STALE_AFTER_SECONDS
    assert CROSS_CHECK_MIN_SECONDS <= CROSS_CHECK_AFTER_SECONDS


def test_quiet_selected_regions_keep_the_full_threshold(clock):
    sup = _sup(alert=False)
    _publish(sup, clock, 20, 20)
    assert sup.cross_check_after(clock[0]) == CROSS_CHECK_AFTER_SECONDS


def test_frequent_publications_during_an_alert_shorten_the_threshold(clock):
    sup = _sup()
    _publish(sup, clock, 20, 20)
    assert sup.cross_check_after(clock[0]) == CROSS_CHECK_MIN_SECONDS


def test_the_threshold_follows_three_median_intervals_inside_the_bounds(clock):
    sup = _sup()
    _publish(sup, clock, 6, 210)
    assert sup.cross_check_after(clock[0]) == 630


def test_fewer_than_five_intervals_keep_the_full_threshold(clock):
    sup = _sup()
    _publish(sup, clock, 5, 20)  # four intervals
    assert sup.cross_check_after(clock[0]) == CROSS_CHECK_AFTER_SECONDS
    _publish(sup, clock, 1, 20)
    assert sup.cross_check_after(clock[0]) == CROSS_CHECK_MIN_SECONDS


def test_publications_older_than_an_hour_do_not_count(clock):
    sup = _sup()
    _publish(sup, clock, 20, 20)
    clock[0] += 3601
    assert sup.cross_check_after(clock[0]) == CROSS_CHECK_AFTER_SECONDS


def test_http_snapshots_do_not_enter_the_intervals(clock):
    sup = _sup()
    for _ in range(20):
        clock[0] += 20
        sup._emit_if_current(CLEAR, sup.snapshot_revision)
    assert sup.cross_check_after(clock[0]) == CROSS_CHECK_AFTER_SECONDS


def test_a_failing_alert_check_keeps_the_full_threshold(clock):
    sup = _sup()
    _publish(sup, clock, 20, 20)

    def broken():
        raise RuntimeError("boom")

    sup.alert_active = broken
    assert sup.cross_check_after(clock[0]) == CROSS_CHECK_AFTER_SECONDS


async def _first_checks(sup, poll, clock, count):
    calls = []

    async def fetch():
        calls.append(clock[0])
        if len(calls) >= count:
            task.cancel()
        return poll_answer[0]

    poll.fetch = fetch
    poll_answer = [CLEAR]
    task = asyncio.get_running_loop().create_task(sup._watchdog())
    try:
        await asyncio.wait_for(task, 5)
    except asyncio.CancelledError:
        pass
    return calls, poll_answer


async def test_a_stall_during_an_alert_is_checked_after_the_short_threshold(clock):
    poll = AsyncMock()
    sup = _sup(poll)
    _publish(sup, clock, 20, 20)
    last = clock[0]
    [first], _ = await _first_checks(sup, poll, clock, 1)
    assert CROSS_CHECK_MIN_SECONDS <= first - last <= CROSS_CHECK_MIN_SECONDS + WATCHDOG_TICK


async def test_a_quiet_stall_waits_for_the_full_threshold(clock):
    poll = AsyncMock()
    sup = _sup(poll, alert=False)
    _publish(sup, clock, 20, 20)
    last = clock[0]
    [first], _ = await _first_checks(sup, poll, clock, 1)
    assert CROSS_CHECK_AFTER_SECONDS <= first - last <= CROSS_CHECK_AFTER_SECONDS + WATCHDOG_TICK


async def test_a_healthy_silent_socket_is_checked_once_per_window(clock):
    poll = AsyncMock()
    sup = _sup(poll)
    _publish(sup, clock, 20, 20)
    calls, _ = await _first_checks(sup, poll, clock, 3)
    # The answer agreed with the last push: no reconnect, no mode change.
    sup._ws.close.assert_not_awaited()
    assert sup.mode == MODE_WS
    for earlier, later in itertools.pairwise(calls):
        assert later - earlier >= sup.cross_check_after(later)


async def test_a_matching_cross_check_writes_no_region_rows(
    hass, enable_custom_integrations, freezer
):
    """A matching answer is an identical map: no entity writes at once. The
    minute-truncated `sensor.uap_last_update` follows on its own tick, one row
    per check; the alert predicate sees the selected region's alert."""
    from test_entities import SNAP_OBLAST_AIR, _setup

    entry, push = await _setup(hass)
    push(parse_alert_payload(SNAP_OBLAST_AIR))
    await hass.async_block_till_done()
    assert entry.runtime_data.alert_in_selected_regions() is True
    seen = []
    hass.bus.async_listen("state_changed", lambda event: seen.append(event.data["entity_id"]))
    freezer.tick(CROSS_CHECK_MIN_SECONDS)
    push(parse_alert_payload(SNAP_OBLAST_AIR))
    await hass.async_block_till_done()
    assert seen == []
    push(parse_alert_payload({"alerts": []}))
    await hass.async_block_till_done()
    assert entry.runtime_data.alert_in_selected_regions() is False
