"""Calendar statistics (issue #5): today and the current month, split at midnight.

An alert that crosses a day or month boundary is cut there: each period counts
it once and only its own part of the duration. Clocks are literal, zone Kyiv.
"""

from datetime import UTC, datetime, timedelta

import pytest
import voluptuous as vol
from test_alert_history import _hist, _payload
from test_entities import _setup
from test_legacy_history_store import legacy_import

from custom_components.ukraine_alarm_pro.const import DOMAIN
from custom_components.ukraine_alarm_pro.history import TYPICAL_MIN_ALERTS, _parse
from custom_components.ukraine_alarm_pro.models import Snapshot

CREATED = datetime(2026, 8, 1, 12, tzinfo=UTC)


async def _journal(hass, now, *, created=CREATED):
    await hass.config.async_set_time_zone("Europe/Kyiv")
    history, clock = _hist(now=created)
    await history.async_load()
    history.confirm(["31"], created)
    clock["now"] = now
    return history, clock


def _episode(history, start, end=None):
    history.handle_event("started", _payload("started", start, active=True))
    if end is not None:
        history.handle_event("cleared", _payload("cleared", end, active=False))


async def test_issue_example_splits_at_the_month_boundary(hass):
    # 30.09 23:00 -> 01.10 02:00 Kyiv (UTC+3)
    start = datetime(2026, 9, 30, 20, tzinfo=UTC)
    end = datetime(2026, 9, 30, 23, tzinfo=UTC)
    history, clock = await _journal(hass, datetime(2026, 9, 30, 20, 30, tzinfo=UTC))
    _episode(history, start, end)
    clock["now"] = datetime(2026, 10, 1, 9, tzinfo=UTC)
    history.confirm(["31"], clock["now"])

    month = history.calendar("31")["month"]
    assert month["start"] == "2026-10-01T00:00:00+03:00"
    assert (month["count"], month["observed_duration_seconds"]) == (1, 7200)
    assert month["longest_duration_seconds"] == 7200
    assert month["average_duration_seconds"] == 7200

    midnight = datetime(2026, 9, 30, 21, tzinfo=UTC)
    september = history._window(
        "31", datetime(2026, 8, 31, 21, tzinfo=UTC), midnight, now=clock["now"]
    )
    assert (september["count"], september["observed_duration_seconds"]) == (1, 3600)


async def test_today_counts_only_the_part_after_midnight(hass):
    history, clock = await _journal(hass, datetime(2026, 10, 10, 20, tzinfo=UTC))
    _episode(history, datetime(2026, 10, 10, 20, tzinfo=UTC), datetime(2026, 10, 10, 22, 30, tzinfo=UTC))
    clock["now"] = datetime(2026, 10, 11, 5, tzinfo=UTC)  # 08:00 Kyiv
    history.confirm(["31"], clock["now"])

    calendar = history.calendar("31")
    # Midnight Kyiv is 21:00 UTC: 1 h 30 min of the 2 h 30 min fall on the 11th.
    assert calendar["today"]["start"] == "2026-10-11T00:00:00+03:00"
    assert calendar["today"]["observed_duration_seconds"] == 5400
    assert calendar["today"]["count"] == 1
    assert calendar["month"]["observed_duration_seconds"] == 9000


async def test_dst_day_is_25_hours_and_daily_follows_local_midnights(hass):
    start = datetime(2026, 10, 24, 21, tzinfo=UTC)  # 25.10 00:00 Kyiv
    end = datetime(2026, 10, 25, 22, tzinfo=UTC)  # 26.10 00:00 Kyiv, day is 25 h
    history, clock = await _journal(hass, start)
    _episode(history, start, end)
    clock["now"] = datetime(2026, 10, 26, 6, tzinfo=UTC)
    history.confirm(["31"], clock["now"])

    daily = {d["date"]: d for d in history.calendar("31")["month"]["daily"]}
    assert daily["2026-10-25"]["observed_duration_seconds"] == 90000
    assert daily["2026-10-25"]["count"] == 1
    assert daily["2026-10-24"]["count"] == 0
    assert daily["2026-10-26"]["count"] == 0
    assert [d["date"] for d in history.calendar("31")["month"]["daily"]][-1] == "2026-10-26"
    assert len(daily) == 26


async def test_daily_splits_one_alert_over_two_days(hass):
    history, clock = await _journal(hass, datetime(2026, 10, 10, 20, tzinfo=UTC))
    _episode(history, datetime(2026, 10, 10, 20, tzinfo=UTC), datetime(2026, 10, 10, 22, tzinfo=UTC))
    clock["now"] = datetime(2026, 10, 11, 9, tzinfo=UTC)
    history.confirm(["31"], clock["now"])

    daily = {d["date"]: d for d in history.calendar("31")["month"]["daily"]}
    assert daily["2026-10-10"] == {"date": "2026-10-10", "count": 1, "observed_duration_seconds": 3600, "quality": "complete"}
    assert daily["2026-10-11"] == {"date": "2026-10-11", "count": 1, "observed_duration_seconds": 3600, "quality": "complete"}


async def test_active_alert_ends_at_now_and_counts_in_both_periods(hass):
    history, clock = await _journal(hass, datetime(2026, 10, 11, 8, tzinfo=UTC))
    _episode(history, datetime(2026, 10, 11, 7, tzinfo=UTC))
    history.confirm(["31"], clock["now"])

    calendar = history.calendar("31")
    assert calendar["today"]["end"].startswith("2026-10-11T11:00:00")
    for period in ("today", "month"):
        assert calendar[period]["count"] == 1
        assert calendar[period]["observed_duration_seconds"] == 3600


async def test_overlapping_journal_and_official_make_one_interval(hass):
    history, clock = await _journal(hass, datetime(2026, 10, 11, 8, tzinfo=UTC))
    start = datetime(2026, 10, 11, 5, tzinfo=UTC)
    end = datetime(2026, 10, 11, 6, tzinfo=UTC)
    _episode(history, start, end)
    history.confirm(["31"], clock["now"])
    legacy_import(
        history, "31", [(start + timedelta(minutes=5), end + timedelta(minutes=5))],
        since=CREATED,
    )
    month = history.calendar("31")["month"]
    assert month["count"] == 1
    assert month["observed_duration_seconds"] == 3900


async def test_journal_created_mid_month_is_incomplete_not_zero(hass):
    created = datetime(2026, 10, 15, 6, tzinfo=UTC)
    history, clock = await _journal(hass, created, created=created)
    _episode(history, datetime(2026, 10, 16, 6, tzinfo=UTC), datetime(2026, 10, 16, 7, tzinfo=UTC))
    clock["now"] = datetime(2026, 10, 20, 6, tzinfo=UTC)
    history.confirm(["31"], clock["now"])

    calendar = history.calendar("31")
    assert calendar["month"]["quality"] == "incomplete"
    assert calendar["month"]["coverage_complete"] is False
    assert calendar["month"]["observed_duration_seconds"] == 3600
    assert calendar["today"]["quality"] == "complete"
    assert calendar["today"]["coverage_complete"] is True


async def test_no_alerts_gives_zero_count_and_no_average(hass):
    history, clock = await _journal(hass, datetime(2026, 10, 11, 8, tzinfo=UTC))
    history.confirm(["31"], clock["now"])
    for period in history.calendar("31").values():
        assert period["count"] == 0
        assert period["observed_duration_seconds"] == 0
        assert period["longest_duration_seconds"] == 0
        assert period["average_duration_seconds"] is None
        assert period["coverage_complete"] is True
        assert period["gap_seconds"] == 0


async def test_average_is_rounded_duration_over_count(hass):
    history, clock = await _journal(hass, datetime(2026, 10, 11, 8, tzinfo=UTC))
    _episode(history, datetime(2026, 10, 3, 5, tzinfo=UTC), datetime(2026, 10, 3, 5, 10, tzinfo=UTC))
    _episode(history, datetime(2026, 10, 4, 5, tzinfo=UTC), datetime(2026, 10, 4, 5, 25, tzinfo=UTC))
    _episode(history, datetime(2026, 10, 5, 5, tzinfo=UTC), datetime(2026, 10, 5, 5, 20, tzinfo=UTC))
    history.confirm(["31"], clock["now"])
    month = history.calendar("31")["month"]
    assert (month["count"], month["observed_duration_seconds"]) == (3, 3300)
    assert month["longest_duration_seconds"] == 1500
    assert month["average_duration_seconds"] == 1100


async def test_window_matches_rolling_for_the_rolling_bounds(hass):
    now = datetime(2026, 10, 11, 8, tzinfo=UTC)
    history, _ = await _journal(hass, now)
    _episode(history, now - timedelta(hours=5), now - timedelta(hours=4))
    history.confirm(["31"], now)
    rolling = history.rolling("31", 86400)
    window = history._window("31", now - timedelta(days=1), now, now=now)
    for key in ("quality", "coverage_complete", "gap_seconds", "count",
                "observed_duration_seconds", "longest_duration_seconds"):
        assert window[key] == rolling[key]


async def test_service_returns_calendar_and_schema_is_unchanged(hass, enable_custom_integrations):
    _, push = await _setup(hass)
    push(Snapshot())
    await hass.async_block_till_done()
    response = await hass.services.async_call(
        DOMAIN, "get_summary", {"region_id": "31", "days": 1},
        blocking=True, return_response=True,
    )
    assert set(response["calendar"]) == {"today", "month"}
    assert "daily" in response["calendar"]["month"]
    assert "daily" not in response["calendar"]["today"]
    assert response["days"] == 1 and "rolling_24h" in response
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "get_summary", {"region_id": "31", "days": 30},
            blocking=True, return_response=True,
        )


async def test_percentage_is_the_share_of_the_period_so_far(hass):
    history, clock = await _journal(hass, datetime(2026, 10, 10, 20, tzinfo=UTC))
    # Midnight Kyiv is 21:00 UTC; 08:00 Kyiv is 8 h = 28800 s into the day.
    _episode(history, datetime(2026, 10, 11, 1, tzinfo=UTC), datetime(2026, 10, 11, 2, 30, tzinfo=UTC))
    clock["now"] = datetime(2026, 10, 11, 5, tzinfo=UTC)
    history.confirm(["31"], clock["now"])

    calendar = history.calendar("31")
    assert calendar["today"]["percentage"] == 18.8  # 5400 / 28800
    # Oct 1 00:00 Kyiv .. Oct 11 08:00 Kyiv = 10 d 8 h = 892800 s
    assert calendar["month"]["percentage"] == 0.6


async def test_percentage_counts_only_the_time_the_journal_covers(hass):
    created = datetime(2026, 10, 15, 6, tzinfo=UTC)
    history, clock = await _journal(hass, created, created=created)
    _episode(history, datetime(2026, 10, 16, 6, tzinfo=UTC), datetime(2026, 10, 16, 7, tzinfo=UTC))
    clock["now"] = datetime(2026, 10, 20, 6, tzinfo=UTC)
    history.confirm(["31"], clock["now"])

    # Five days of journal, not the 19 days since the 1st: 3600 / 432000.
    assert history.calendar("31")["month"]["percentage"] == 0.8


async def test_percentage_zero_is_a_value_and_missing_coverage_is_none(hass):
    history, clock = await _journal(hass, datetime(2026, 10, 11, 8, tzinfo=UTC))
    history.confirm(["31"], clock["now"])
    assert history.calendar("31")["month"]["percentage"] == 0.0

    empty, _ = _hist(now=datetime(2026, 10, 11, 8, tzinfo=UTC))
    await empty.async_load()
    assert empty.calendar("31")["today"]["percentage"] is None


async def test_percentage_counts_official_history_before_the_live_feed(hass):
    """The journal was created on 2026-08-01 (before the 90-day official window) and the live feed seen only from
    10-15, but official history covers the whole month: the share is over the
    month, not over the days since the feed."""
    history, clock = await _journal(hass, datetime(2026, 10, 15, 6, tzinfo=UTC))
    history._live_since["31"] = datetime(2026, 10, 15, 6, tzinfo=UTC).isoformat()
    official = [(datetime(2026, 10, 2, 5, tzinfo=UTC), datetime(2026, 10, 2, 6, tzinfo=UTC))]
    legacy_import(history, "31", official, since=datetime(2026, 8, 5, tzinfo=UTC), episodes=True)
    clock["now"] = datetime(2026, 10, 16, 6, tzinfo=UTC)
    history.confirm(["31"], clock["now"])

    month = history.calendar("31")["month"]
    # Oct 1 00:00 Kyiv .. Oct 16 09:00 Kyiv = 15 d 9 h = 1328400 s
    assert month["observed_duration_seconds"] == 3600
    assert month["percentage"] == 0.3


async def test_clock_set_back_marks_the_period_clock_jump_not_complete(hass):
    """A confirmation stamped after `now` means the clock went back: the calendar
    periods say so instead of passing a share off as complete."""
    history, clock = await _journal(hass, datetime(2026, 10, 11, 8, tzinfo=UTC))
    _episode(history, datetime(2026, 10, 11, 5, tzinfo=UTC), datetime(2026, 10, 11, 6, tzinfo=UTC))
    history.confirm(["31"], clock["now"] + timedelta(hours=2))

    for period in history.calendar("31").values():
        assert period["quality"] == "clock_jump"
        assert period["coverage_complete"] is False


def test_unparseable_stamps_are_ignored_not_fatal():
    # Valid shape, impossible date; a stamp without an offset is damage too.
    assert _parse("2026-02-30T00:00:00+00:00") is None
    assert _parse("2026-10-11T00:00:00") is None
    assert _parse(None) is None
    assert _parse("2026-10-11T00:00:00+00:00") == datetime(2026, 10, 11, tzinfo=UTC)


async def test_a_region_added_later_is_covered_from_its_own_first_sight(hass):
    """Without the official import a region added through Configure has no
    earlier history: the journal's age must not count as its coverage."""
    history, clock = await _journal(hass, datetime(2026, 10, 15, 6, tzinfo=UTC))
    added = datetime(2026, 10, 15, 6, tzinfo=UTC)
    history.confirm(["31", "692"], added)
    start = datetime(2026, 10, 16, 6, tzinfo=UTC)
    for day in range(TYPICAL_MIN_ALERTS):
        lo = start + timedelta(hours=8 * day)
        history.handle_event("started", _payload("started", lo, active=True, region="692"))
        history.handle_event(
            "cleared", _payload("cleared", lo + timedelta(minutes=6), active=False, region="692")
        )
    clock["now"] = datetime(2026, 10, 20, 6, tzinfo=UTC)
    history.confirm(["31", "692"], clock["now"])

    assert history.summary("692", 7)["coverage_start"] == added.isoformat()
    assert history.typical("692")["days"] == 5
    # Five days observed: 3600 / 432000, not over the 19 days since the 1st.
    assert history.calendar("692")["month"]["percentage"] == 0.8
    # The region present from the start keeps the journal's coverage.
    assert history.summary("31", 7)["coverage_start"] == CREATED.isoformat()


async def test_newly_selected_region_without_observations_has_no_coverage(hass):
    history, clock = await _journal(hass, datetime(2026, 10, 11, 8, tzinfo=UTC))
    assert history.summary("692", 1)["coverage_start"] is None
    assert history.calendar("692")["month"]["percentage"] is None
    history.confirm(["692"], clock["now"])
    clock["now"] += timedelta(minutes=1)
    assert history.calendar("692")["month"]["percentage"] == 0.0


@pytest.mark.parametrize(("before", "after", "day", "hours"), [
    (datetime(2026, 3, 27, tzinfo=UTC), datetime(2026, 3, 31, tzinfo=UTC), "2026-03-29", 23),
    (datetime(2026, 10, 23, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC), "2026-10-25", 25),
])
async def test_multiday_episode_agrees_with_month_total_across_dst(hass, before, after, day, hours):
    history, _ = await _journal(hass, after, created=before - timedelta(days=1))
    _episode(history, before, after)
    month = history.calendar("31")["month"]
    daily = {row["date"]: row["observed_duration_seconds"] for row in month["daily"]}
    assert daily[day] == hours * 3600
    assert sum(daily.values()) == month["observed_duration_seconds"]


async def test_daily_quality_marks_start_and_gap_without_tainting_other_days(hass):
    start = datetime(2026, 10, 2, 3, tzinfo=UTC)
    now = datetime(2026, 10, 6, 9, tzinfo=UTC)
    history, clock = await _journal(hass, now, created=start)
    gap = datetime(2026, 10, 4, 9, tzinfo=UTC)
    history.confirm(["31"], gap)
    history.mark_gap(["31"])
    history.confirm(["31"], gap + timedelta(hours=2))
    clock["now"] = now
    daily = history.calendar("31")["month"]["daily"]
    assert [day["quality"] for day in daily] == [
        "before_start", "gaps", "complete", "gaps", "complete", "complete",
    ]
    assert all(day["count"] == 0 for day in daily)


async def test_daily_quality_open_gap_crosses_midnight(hass):
    last = datetime(2026, 10, 4, 20, tzinfo=UTC)
    now = last + timedelta(hours=3)
    history, clock = await _journal(hass, last)
    history.confirm(["31"], last)
    history.mark_gap(["31"])
    clock["now"] = now
    daily = history.calendar("31")["month"]["daily"]
    assert [day["quality"] for day in daily] == [
        "complete", "complete", "complete", "gaps", "gaps",
    ]


async def test_daily_quality_respects_legacy_journal_before_per_region_tracking(hass):
    now = datetime(2026, 10, 6, 9, tzinfo=UTC)
    history, clock = await _journal(hass, now)
    _episode(history, datetime(2026, 10, 2, 3, tzinfo=UTC), datetime(2026, 10, 2, 4, tzinfo=UTC))
    # An upgraded journal contains recordings before it began tracking live_since.
    history._live_since["31"] = datetime(2026, 10, 4, 3, tzinfo=UTC).isoformat()
    history.confirm(["31"], clock["now"])
    day = history.calendar("31")["month"]["daily"][1]
    assert day["observed_duration_seconds"] == 3600
    assert day["quality"] == "complete"
