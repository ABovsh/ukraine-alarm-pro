"""Episode journal: observed times, gap marks, bounded storage (UAP-07)."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from test_entities import _setup

from custom_components.ukraine_alarm_pro.const import DOMAIN
from custom_components.ukraine_alarm_pro.history import AlertHistory
from custom_components.ukraine_alarm_pro.models import parse_alert_payload

T0 = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)


class FakeStore:
    def __init__(self, data=None, fail=0):
        self.data = data
        self.fail = fail
        self.saves = 0

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        if self.fail:
            self.fail -= 1
            raise OSError("disk full")
        self.saves += 1
        self.data = data


def _payload(event_type, at, *, active, types=("air",), level="yellow", origin="live",
             region="31", declared="2026-09-15T09:59:00+00:00"):
    return {
        "region_id": region,
        "event_type": event_type,
        "observed_at": at.isoformat(),
        "origin": origin,
        "had_gap": origin != "live",
        "current": {
            "active": active,
            "threat_types": list(types) if active else [],
            "air_level": level if active else "none",
            "declared_started_at": declared if active else None,
        },
    }


def _hist(store=None, now=T0, **kw):
    clock = {"now": now}
    history = AlertHistory(store or FakeStore(), now=lambda: clock["now"], **kw)
    return history, clock


async def test_overlapping_declarations_form_one_episode():
    history, _ = _hist()
    await history.async_load()
    history.handle_event("started", _payload("started", T0, active=True))
    history.handle_event(
        "threat_added",
        _payload("threat_added", T0 + timedelta(minutes=30), active=True, types=("chemical", "air")),
    )
    history.handle_event(
        "escalated",
        _payload("escalated", T0 + timedelta(minutes=45), active=True, level="red"),
    )
    history.handle_event("cleared", _payload("cleared", T0 + timedelta(minutes=90), active=False))
    [episode] = history.history("31", 20)
    assert episode["observed_started_at"] == T0.isoformat()
    assert episode["observed_cleared_at"] == (T0 + timedelta(minutes=90)).isoformat()
    assert episode["declared_started_at"] == "2026-09-15T09:59:00+00:00"
    assert episode["active_types_seen"] == ["air", "chemical"]
    assert episode["maximum_air_level"] == "red"
    assert episode["had_gap"] is False
    assert episode["source_start_known"] is True
    assert episode["start_origin"] == "live"
    assert episode["observed_duration_seconds"] == 5400


async def test_bootstrap_mid_alert_marks_unknown_start_and_restart_does_not_duplicate():
    store = FakeStore()
    history, clock = _hist(store)
    await history.async_load()
    history.handle_event("resynced", _payload("resynced", T0, active=True, origin="bootstrap"))
    await history.async_flush()

    clock["now"] = T0 + timedelta(minutes=10)
    restarted, _ = _hist(store, now=clock["now"])
    await restarted.async_load()
    restarted.handle_event(
        "resynced", _payload("resynced", clock["now"], active=True, origin="bootstrap")
    )
    [episode] = restarted.history("31", 20)
    assert episode["source_start_known"] is False
    assert episode["start_origin"] == "bootstrap"
    assert episode["had_gap"] is True
    assert episode["observed_cleared_at"] is None
    assert episode["observed_duration_seconds"] is None


async def test_clear_after_gap_keeps_the_gap_mark():
    history, _ = _hist()
    await history.async_load()
    history.handle_event("started", _payload("started", T0, active=True))
    history.handle_event("data_stale", _payload("data_stale", T0 + timedelta(minutes=20), active=True))
    history.handle_event(
        "resynced",
        _payload("resynced", T0 + timedelta(hours=2), active=False, origin="recovery"),
    )
    [episode] = history.history("31", 20)
    assert episode["had_gap"] is True
    assert episode["observed_cleared_at"] == (T0 + timedelta(hours=2)).isoformat()


async def test_failed_save_is_retried_on_the_next_flush():
    store = FakeStore(fail=1)
    history, _ = _hist(store)
    await history.async_load()
    history.handle_event("started", _payload("started", T0, active=True))
    with pytest.raises(OSError):
        await history.async_flush()
    await history.async_flush()
    assert store.saves == 1
    await history.async_flush()
    assert store.saves == 1, "nothing new: no rewrite"


async def test_continuous_events_do_not_postpone_the_flush():
    store = FakeStore()
    history, _ = _hist(store)
    await history.async_load()
    for minute in range(50):
        at = T0 + timedelta(minutes=minute)
        history.handle_event("updated", _payload("updated", at, active=True))
        if minute % 5 == 0:
            await history.async_flush()
    assert store.saves >= 1
    assert store.data["active"]["31"]["region_id"] == "31"


@pytest.mark.parametrize("data", ["junk", {"active": "x", "episodes": 5}, {"episodes": [None, 3]}])
async def test_corrupted_store_starts_an_empty_journal(data):
    history, _ = _hist(FakeStore(data))
    await history.async_load()
    assert history.history("31", 20) == []


async def test_caps_drop_old_completed_but_never_active_episodes():
    history, clock = _hist(max_episodes=3, max_days=90)
    await history.async_load()
    for i in range(5):
        start = T0 + timedelta(hours=i)
        history.handle_event("started", _payload("started", start, active=True))
        history.handle_event("cleared", _payload("cleared", start + timedelta(minutes=5), active=False))
    history.handle_event("started", _payload("started", T0 + timedelta(hours=9), active=True, region="14"))
    assert len(history.history("31", 100)) == 3
    assert history.history("31", 100)[0]["observed_started_at"] == (T0 + timedelta(hours=4)).isoformat()
    # Age cap: everything completed is over 90 days old now; the active one stays.
    clock["now"] = T0 + timedelta(days=120)
    history.handle_event("updated", _payload("updated", clock["now"], active=True, region="14"))
    assert history.history("31", 100) == []
    assert len(history.history("14", 100)) == 1


async def test_summary_uses_local_days_and_reports_coverage_start(hass: HomeAssistant):
    await hass.config.async_set_time_zone("Europe/Kyiv")
    kyiv = ZoneInfo("Europe/Kyiv")
    now = datetime(2026, 9, 15, 12, 0, tzinfo=kyiv)
    history, _ = _hist(now=now.astimezone(UTC))
    await history.async_load()
    # 23:30 -> 00:30 local: only 30 min belong to today.
    start = datetime(2026, 9, 14, 23, 30, tzinfo=kyiv)
    history.handle_event("started", _payload("started", start, active=True))
    history.handle_event("cleared", _payload("cleared", start + timedelta(hours=1), active=False))
    day = history.summary("31", 1)
    assert day["count"] == 1
    assert day["observed_duration_seconds"] == 1800
    assert day["has_gaps"] is False
    assert day["period_start"] == datetime(2026, 9, 15, tzinfo=kyiv).isoformat()
    assert day["coverage_start"] == now.astimezone(UTC).isoformat()
    assert day["longest_duration_seconds"] == 1800
    assert day["daily"] == [{"date": "2026-09-15", "count": 1, "observed_duration_seconds": 1800}]
    week = history.summary("31", 7)
    assert week["observed_duration_seconds"] == 3600
    assert week["longest_duration_seconds"] == 3600
    assert [d["date"] for d in week["daily"]] == [f"2026-09-{d:02d}" for d in range(9, 16)]
    assert week["daily"][-2] == {"date": "2026-09-14", "count": 1, "observed_duration_seconds": 1800}
    assert sum(d["count"] for d in week["daily"][:-2]) == 0


async def test_services_return_history_and_validate_input(
    hass: HomeAssistant, enable_custom_integrations
):
    _, push = await _setup(hass)
    push(parse_alert_payload({"alerts": []}))
    await hass.async_block_till_done()
    push(parse_alert_payload(
        {"alerts": [{"regionId": "31", "activeAlerts": [{"type": "AIR", "lastUpdate": "2026-09-15T06:00:00Z"}]}]}
    ))
    await hass.async_block_till_done()

    result = await hass.services.async_call(
        DOMAIN, "get_history", {"region_id": "31", "limit": 5}, blocking=True, return_response=True
    )
    [episode] = result["episodes"]
    assert episode["region_id"] == "31"
    assert episode["source_start_known"] is True
    assert episode["observed_cleared_at"] is None

    summary = await hass.services.async_call(
        DOMAIN, "get_summary", {"region_id": "31", "days": 7}, blocking=True, return_response=True
    )
    assert summary["count"] == 1

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "get_history", {"region_id": "999"}, blocking=True, return_response=True
        )
    with pytest.raises(Exception):  # noqa: B017 - schema rejects limit > 100
        await hass.services.async_call(
            DOMAIN, "get_history", {"region_id": "31", "limit": 101}, blocking=True, return_response=True
        )
    assert dt_util.utcnow() is not None


async def test_journal_and_map_are_saved_when_home_assistant_stops(
    hass: HomeAssistant, enable_custom_integrations, hass_storage
):
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP

    entry, push = await _setup(hass)
    push(parse_alert_payload(
        {"alerts": [{"regionId": "31", "activeAlerts": [{"type": "AIR", "lastUpdate": "2026-09-15T06:00:00Z"}]}]}
    ))
    await hass.async_block_till_done()
    key = f"{DOMAIN}.history.{entry.entry_id}"
    assert key not in hass_storage
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert hass_storage[key]["data"]["active"]["31"]["region_id"] == "31"
    assert f"{DOMAIN}.snapshot" in hass_storage
