"""Alert events: one coherent payload per accepted change per region (UAP-03)."""

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from test_entities import _setup

from custom_components.ukraine_alarm_pro.events import RegionState, classify
from custom_components.ukraine_alarm_pro.models import parse_alert_payload

EVENT = "event.uap_31_event"
CLEAR = parse_alert_payload({"alerts": []})


def _air(level=None, *extra_types, reason=""):
    alerts = [{"type": "AIR", "lastUpdate": "2026-09-15T06:00:00Z"}]
    if level:
        alerts[0]["activeAlertLevels"] = [{"alertLevel": level, "reason": reason}]
    alerts += [{"type": t, "lastUpdate": "2026-09-15T06:05:00Z"} for t in extra_types]
    return parse_alert_payload({"alerts": [{"regionId": "31", "activeAlerts": alerts}]})


def _state(active=True, types=("air",), level="yellow", reasons=(), coverage="whole"):
    return RegionState(
        active=active,
        threat_types=tuple(types) if active else (),
        air_level=level if active else "none",
        reasons=tuple(reasons),
        coverage=coverage if active else "none",
        declared_started_at="2026-09-15T06:00:00+00:00" if active else None,
    )


QUIET = _state(active=False)


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (QUIET, _state(level="red"), "started"),
        (_state(), QUIET, "cleared"),
        (_state(), _state(types=("chemical", "air")), "threat_added"),
        (_state(), _state(level="red"), "escalated"),
        (_state(level="unrecognized"), _state(level="red"), "escalated"),
        (_state(), _state(types=("chemical", "air"), level="red"), "escalated"),
        (_state(level="red"), _state(), "updated"),
        (_state(reasons=("a",)), _state(reasons=("b",)), "updated"),
        (_state(types=("chemical", "air")), _state(), "updated"),
        (_state(), _state(), None),
        (QUIET, QUIET, None),
        (_state(types=("artillery",), level="none"), _state(types=("artillery", "air")), "threat_added"),
    ],
)
def test_transition_table(previous, current, expected):
    assert classify(previous, current) == expected


async def _events(hass):
    captured = []

    def _listener(event):
        if event.data["entity_id"] == EVENT and event.data["new_state"] is not None:
            attrs = event.data["new_state"].attributes
            if "event_type" in attrs and event.data["new_state"].state not in ("unknown",):
                captured.append(dict(attrs))

    hass.bus.async_listen("state_changed", _listener)
    return captured


async def test_first_snapshot_is_a_bootstrap_resync_not_a_start(
    hass: HomeAssistant, enable_custom_integrations
):
    _, push = await _setup(hass)
    events = await _events(hass)
    push(_air("Red"))
    await hass.async_block_till_done()
    assert [e["event_type"] for e in events] == ["resynced"]
    payload = events[0]
    assert payload["origin"] == "bootstrap"
    assert payload["had_gap"] is True
    assert payload["schema_version"] == 1
    assert payload["region_id"] == "31"
    assert payload["current"]["active"] is True
    assert payload["current"]["air_level"] == "red"
    assert payload["current"]["threat_types"] == ["air"]
    assert payload["previous"] is None
    assert payload["observed_active_since"] == payload["observed_at"]
    assert payload["active_since_known"] is False


async def test_live_sequence_publishes_one_event_per_change(
    hass: HomeAssistant, enable_custom_integrations
):
    _, push = await _setup(hass)
    push(CLEAR)
    await hass.async_block_till_done()
    events = await _events(hass)

    push(_air("Yellow"))
    await hass.async_block_till_done()
    push(_air("Yellow"))  # identical: nothing
    await hass.async_block_till_done()
    push(_air("Red", "CHEMICAL"))  # new type + red together: one escalated
    await hass.async_block_till_done()
    push(_air("Yellow", "CHEMICAL"))
    await hass.async_block_till_done()
    push(CLEAR)
    await hass.async_block_till_done()

    assert [e["event_type"] for e in events] == [
        "started",
        "escalated",
        "updated",
        "cleared",
    ]
    escalated = events[1]
    assert escalated["added_types"] == ["chemical"]
    assert escalated["current"]["air_level"] == "red"
    assert escalated["previous"]["air_level"] == "yellow"
    assert all(e["origin"] == "live" and e["had_gap"] is False for e in events)
    cleared = events[-1]
    assert cleared["previous"]["active"] is True
    assert cleared["observed_active_since"] == events[0]["observed_at"]
    assert cleared["active_since_known"] is True
    assert events[0]["observed_active_since"] == events[0]["observed_at"]
    assert cleared["removed_types"] == ["chemical", "air"]
    ids = [e["transition_id"] for e in events]
    assert len(set(ids)) == len(ids)


async def test_staleness_is_announced_once_and_recovery_resyncs(
    hass: HomeAssistant, enable_custom_integrations
):
    entry, push = await _setup(hass)
    push(_air("Yellow"))
    await hass.async_block_till_done()
    events = await _events(hass)

    coordinator = entry.runtime_data
    coordinator.last_push = dt_util.utcnow() - timedelta(hours=1)
    for minutes in (1, 2, 3):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes))
        await hass.async_block_till_done()
    assert [e["event_type"] for e in events] == ["data_stale"]
    assert events[0]["current"]["active"] is True
    assert hass.states.get("binary_sensor.uap_31_alert").state == "on"

    push(_air("Yellow"))  # same map after the gap
    await hass.async_block_till_done()
    assert [e["event_type"] for e in events] == ["data_stale", "resynced"]
    assert events[1]["origin"] == "recovery"
    assert events[1]["had_gap"] is True


async def test_recovery_into_clear_is_a_resync_not_a_cleared(
    hass: HomeAssistant, enable_custom_integrations
):
    entry, push = await _setup(hass)
    push(_air("Yellow"))
    await hass.async_block_till_done()
    events = await _events(hass)
    entry.runtime_data.last_push = dt_util.utcnow() - timedelta(hours=1)
    push(CLEAR)
    await hass.async_block_till_done()
    assert [e["event_type"] for e in events] == ["resynced"]
    assert events[0]["current"]["active"] is False
    assert events[0]["previous"]["active"] is True


async def test_unload_removes_the_event_listeners(
    hass: HomeAssistant, enable_custom_integrations
):
    entry, _ = await _setup(hass)
    coordinator = entry.runtime_data
    # Two region event entities plus the history journal.
    assert coordinator.events.listener_count == 3
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert coordinator.events.listener_count == 0


def test_event_published_before_the_entity_exists_is_delivered_on_subscribe():
    """At startup the seed can beat the event platform by seconds."""
    from custom_components.ukraine_alarm_pro.events import AlertEventHub

    hub = AlertEventHub()
    hub.accept({"31": ("м. Київ", _state())}, origin="bootstrap", observed_at="t0")
    received = []
    remove = hub.add_listener("31", lambda kind, payload: received.append(kind))
    assert received == ["resynced"]
    remove()
    hub.add_listener("31", lambda kind, payload: received.append(kind))
    assert received == ["resynced"], "delivered once, not replayed to every listener"
