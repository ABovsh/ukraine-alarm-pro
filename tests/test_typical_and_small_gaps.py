"""How long an alert usually lasts, and shares that survive a short gap.

A restart leaves a gap of a few minutes. When it is under 1 % of the window
it cannot move the share by more than that, so the share is still reported,
over the time the journal covers; the quality stays "gaps".
"""

from datetime import UTC, datetime, timedelta

from test_alert_history import FakeStore, _hist, _payload
from test_short_gaps import DAY, T0, _journal, _restart


async def test_a_gap_under_one_percent_still_gives_the_share():
    store = await _journal(active_from=T0 - timedelta(minutes=50))
    history, clock = await _restart(store, T0 + timedelta(minutes=6), active=True)
    clock["now"] = T0 + timedelta(hours=1)
    history.confirm(["31"], clock["now"])
    for window in (DAY, 7 * DAY):
        result = history.rolling("31", window)
        assert result["quality"] == "gaps"
        assert result["coverage_complete"] is False
        assert result["gap_seconds"] == 360
        known = window - result["gap_seconds"]
        assert result["percentage"] == round(100 * result["observed_duration_seconds"] / known, 1)
        assert result["percentage"] > 0


async def test_a_gap_of_one_percent_or_more_leaves_the_share_unknown():
    store = await _journal()
    # 15 min: 1.04 % of a day, 0.15 % of a week.
    history, clock = await _restart(store, T0 + timedelta(minutes=15), active=False)
    clock["now"] = T0 + timedelta(hours=1)
    history.confirm(["31"], clock["now"])
    assert history.rolling("31", DAY)["percentage"] is None
    assert history.rolling("31", 7 * DAY)["percentage"] == 0.0


async def test_other_doubts_still_leave_the_share_unknown():
    """A young journal is not a gap: nothing is known before it began."""
    history, clock = _hist(FakeStore(), now=T0)
    await history.async_load()
    history.confirm(["31"], T0)
    clock["now"] = T0 + timedelta(hours=1)
    history.confirm(["31"], clock["now"])
    result = history.rolling("31", DAY)
    assert result["quality"] == "incomplete"
    assert result["percentage"] is None


async def _alerts(minutes, *, now=T0, extra=()):
    history, clock = _hist(FakeStore(), now=now - timedelta(days=95))
    await history.async_load()
    starts = [now - timedelta(days=i + 1) for i in range(len(minutes))]
    for (start, length) in [*zip(starts, minutes, strict=True), *extra]:
        declared = start.isoformat()
        history.handle_event("started", _payload("started", start, active=True, declared=declared))
        history.handle_event("cleared", _payload("cleared", start + timedelta(minutes=length), active=False))
    clock["now"] = now
    return history, clock


async def test_typical_duration_is_the_median_and_upper_quartile_of_90_days():
    lengths = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    # Older than 90 days: left out, however long.
    history, _clock = await _alerts(lengths, extra=[(T0 - timedelta(days=93), 600)])
    typical = history.summary("31", 7)["typical"]
    assert typical["count"] == 10
    assert typical["median_seconds"] == 55 * 60
    assert typical["p75_seconds"] == round(77.5 * 60)
    assert typical["days"] == 90


async def test_an_ongoing_alert_is_not_part_of_its_own_typical_duration():
    history, _clock = await _alerts([30] * 10)
    history.handle_event("started", _payload("started", T0 - timedelta(hours=5), active=True,
                                             declared=(T0 - timedelta(hours=5)).isoformat()))
    typical = history.summary("31", 7)["typical"]
    assert typical["count"] == 10
    assert typical["median_seconds"] == 1800


async def test_too_few_alerts_give_no_typical_duration():
    history, _clock = await _alerts([30] * 9)
    assert history.summary("31", 7)["typical"] is None


async def test_a_young_journal_says_how_many_days_it_covers():
    now = datetime(2026, 11, 12, 12, tzinfo=UTC)
    history, clock = _hist(FakeStore(), now=now - timedelta(days=20))
    await history.async_load()
    for i in range(12):
        start = now - timedelta(days=i + 1)
        history.handle_event("started", _payload("started", start, active=True, declared=start.isoformat()))
        history.handle_event("cleared", _payload("cleared", start + timedelta(minutes=40), active=False))
    clock["now"] = now
    assert history.summary("31", 7)["typical"]["days"] == 20


async def test_a_small_gap_in_a_journal_younger_than_the_window_stays_unknown():
    """The gap verdict outranks "incomplete" in the quality field; the share
    must still not count the time before the journal began as quiet."""
    store = FakeStore()
    history, clock = _hist(store, now=T0 - timedelta(hours=10))
    await history.async_load()
    history.confirm(["31"], clock["now"])
    history.confirm(["31"], T0)
    clock["now"] = T0
    await history.async_flush()
    history, clock = await _restart(store, T0 + timedelta(minutes=6), active=False)
    clock["now"] = T0 + timedelta(hours=1)
    history.confirm(["31"], clock["now"])
    assert history.rolling("31", DAY)["percentage"] is None
