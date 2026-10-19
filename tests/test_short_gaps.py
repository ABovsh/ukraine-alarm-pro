"""A Home Assistant restart must not hide the alert percentages for a week.

2026-10-18 the live journal of region 31 held six 15–66 s gaps, one per
restart; each made the 24 h share unknown for a day and the 7 d share for a
week. A short gap with the same state on both sides and no alert starting or
ending across it hides nothing: it is bridged. Anything else stays a gap.
"""

from datetime import UTC, datetime, timedelta

from test_alert_history import FakeStore, _hist, _payload

T0 = datetime(2026, 10, 18, 12, tzinfo=UTC)
DAY = 86400


async def _restart(store, at, *, active):
    """Flush, reload as after a restart, and accept the first live snapshot."""
    restored, clock = _hist(store, now=at)
    await restored.async_load()
    restored.handle_event("resynced", _payload("resynced", at, active=active, origin="resync"))
    return restored, clock


async def _journal(*, active_from=None):
    store = FakeStore()
    history, clock = _hist(store, now=T0 - timedelta(days=8))
    await history.async_load()
    history.confirm(["31"], clock["now"])
    if active_from is not None:
        history.handle_event("started", _payload("started", active_from, active=True))
    history.confirm(["31"], T0)
    clock["now"] = T0
    await history.async_flush()
    return store


async def test_quiet_restart_gap_is_bridged():
    store = await _journal()
    history, clock = await _restart(store, T0 + timedelta(seconds=40), active=False)
    clock["now"] = T0 + timedelta(hours=1)
    history.confirm(["31"], clock["now"])
    result = history.rolling("31", DAY)
    assert result["coverage_complete"] is True
    assert result["percentage"] == 0.0
    assert result["gap_seconds"] == 0
    assert history.rolling("31", 7 * DAY)["percentage"] == 0.0


async def test_alert_running_across_a_restart_counts_whole():
    store = await _journal(active_from=T0 - timedelta(minutes=50))
    history, clock = await _restart(store, T0 + timedelta(seconds=40), active=True)
    clock["now"] = T0 + timedelta(minutes=10)
    history.confirm(["31"], clock["now"])
    result = history.rolling("31", DAY)
    assert result["coverage_complete"] is True
    assert result["observed_duration_seconds"] == 3600
    assert result["percentage"] == 4.2


async def test_alert_that_ended_during_the_restart_stays_a_gap():
    store = await _journal(active_from=T0 - timedelta(minutes=50))
    history, clock = await _restart(store, T0 + timedelta(seconds=40), active=False)
    clock["now"] = T0 + timedelta(minutes=10)
    history.confirm(["31"], clock["now"])
    result = history.rolling("31", DAY)
    assert result["percentage"] is None
    assert result["quality"] == "gaps"


async def test_alert_that_began_during_the_restart_stays_a_gap():
    store = await _journal()
    history, clock = await _restart(store, T0 + timedelta(seconds=40), active=True)
    clock["now"] = T0 + timedelta(minutes=10)
    history.confirm(["31"], clock["now"])
    assert history.rolling("31", DAY)["percentage"] is None


async def test_long_quiet_gap_is_not_bridged():
    store = await _journal()
    history, clock = await _restart(store, T0 + timedelta(minutes=6), active=False)
    clock["now"] = T0 + timedelta(hours=1)
    history.confirm(["31"], clock["now"])
    result = history.rolling("31", DAY)
    assert result["percentage"] is None
    assert result["gap_seconds"] == 360


async def test_alert_that_cleared_right_before_the_restart_is_bridged():
    """2026-10-19 22:42: the all clear was the last confirmed map before the
    restart, so the edge sits exactly at the gap's start. The state there is
    known — quiet before the gap and after it."""
    store = FakeStore()
    history, clock = _hist(store, now=T0 - timedelta(days=8))
    await history.async_load()
    history.confirm(["31"], clock["now"])
    history.handle_event("started", _payload("started", T0 - timedelta(minutes=30), active=True))
    history.handle_event("cleared", _payload("cleared", T0, active=False))
    clock["now"] = T0
    await history.async_flush()
    history, clock = await _restart(store, T0 + timedelta(seconds=21), active=False)
    clock["now"] = T0 + timedelta(minutes=10)
    history.confirm(["31"], clock["now"])
    result = history.rolling("31", DAY)
    assert result["coverage_complete"] is True
    assert result["percentage"] == 2.1
