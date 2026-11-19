"""Event-driven notification blueprint and the test script (UAP-05)."""

import time
from datetime import timedelta
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)
from test_entities import _setup

from custom_components.ukraine_alarm_pro.models import parse_alert_payload

ROOT = Path(__file__).parent.parent / "blueprints"
CLEAR = parse_alert_payload({"alerts": []})


def _air(level="Red", *extra, reason="Загроза балістики"):
    alerts = [
        {
            "type": "AIR",
            "lastUpdate": "2026-09-15T11:32:00Z",
            "activeAlertLevels": [{"alertLevel": level, "reason": reason}],
        }
    ]
    alerts += [{"type": t, "lastUpdate": "2026-09-15T11:40:00Z"} for t in extra]
    return parse_alert_payload(
        {"alerts": [{"regionId": "31", "regionName": "м. Київ", "activeAlerts": alerts}]}
    )


def _action(kind):
    return [{"event": "uap_test", "event_data": {"kind": kind, "msg": "{{ message }}"}}]


async def _install(hass, language="uk", **extra):
    for kind, name in (("automation", "alert_notify_events.yaml"), ("script", "test_notification.yaml")):
        dest = Path(hass.config.path(f"blueprints/{kind}/ukraine_alarm_pro"))
        dest.mkdir(parents=True, exist_ok=True)
        (dest / name).write_text(
            (ROOT / kind / "ukraine_alarm_pro" / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": "ukraine_alarm_pro/alert_notify_events.yaml",
                    "input": {
                        "event_entity": "event.uap_31_event",
                        "language": language,
                        "on_started": _action("started"),
                        "on_escalation": _action("escalation"),
                        "on_cleared": _action("cleared"),
                        "on_stale": _action("stale"),
                        "on_resynced": _action("resynced"),
                        **extra,
                    },
                }
            }
        },
    )
    await hass.async_block_till_done()


async def test_bootstrap_is_silent_and_live_changes_are_reported_in_ukrainian(
    hass: HomeAssistant, enable_custom_integrations
):
    entry, push = await _setup(hass)
    await _install(hass)
    events = async_capture_events(hass, "uap_test")

    push(_air("Red"))  # valid red right after a cold start
    await hass.async_block_till_done()
    assert events == [], "an alert in progress at startup is not a new alert"

    push(CLEAR)
    await hass.async_block_till_done()
    push(_air("Yellow"))
    await hass.async_block_till_done()
    push(_air("Red", "CHEMICAL"))
    await hass.async_block_till_done()
    push(CLEAR)
    await hass.async_block_till_done()

    kinds = [e.data["kind"] for e in events]
    assert kinds == ["cleared", "started", "escalation", "cleared"]
    started = events[1].data["msg"]
    assert started.startswith("м. Київ: повітряна тривога з ")
    assert "Рівень: жовтий." in started
    assert "Причина: Загроза балістики." in started
    escalation = events[2].data["msg"]
    assert "рівень повітряної тривоги підвищився до червоного" in escalation
    assert "Додалося: хімічна загроза" in escalation
    cleared = events[3].data["msg"]
    assert cleared.startswith("м. Київ: відбій.")
    assert "Тривалість за спостереженнями: 0 хв." in cleared
    # The bootstrap red was active, so its clear is reported, but without a
    # duration: its real start was never observed.
    assert "Тривалість" not in events[0].data["msg"]

    coordinator = entry.runtime_data
    assert coordinator.events.bootstrapped


async def test_stale_and_recovery_never_claim_an_all_clear(
    hass: HomeAssistant, enable_custom_integrations
):
    entry, push = await _setup(hass)
    push(_air("Yellow"))
    await hass.async_block_till_done()
    await _install(hass, language="en")
    events = async_capture_events(hass, "uap_test")

    entry.runtime_data.last_push = dt_util.utcnow() - timedelta(hours=1)
    entry.runtime_data._last_push_monotonic = time.monotonic() - (dt_util.utcnow() - entry.runtime_data.last_push).total_seconds()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    push(CLEAR)  # the alert ended somewhere inside the gap
    await hass.async_block_till_done()

    assert [e.data["kind"] for e in events] == ["stale", "resynced"]
    assert events[0].data["msg"] == "Alert data is stale. Last known state for м. Київ: alert."
    assert events[1].data["msg"] == "м. Київ: no active alert after the connection was restored."
    assert "clear" not in events[1].data["msg"].lower()


async def test_bootstrap_can_be_reported_when_asked(
    hass: HomeAssistant, enable_custom_integrations
):
    _, push = await _setup(hass)
    await _install(hass, notify_on_bootstrap=True)
    events = async_capture_events(hass, "uap_test")
    push(_air("Red"))
    await hass.async_block_till_done()
    assert [e.data["kind"] for e in events] == ["resynced"]
    assert "Дані отримано після запуску" in events[0].data["msg"]
    assert "тривога триває" in events[0].data["msg"]


async def test_test_script_runs_actions_without_touching_alerts(
    hass: HomeAssistant, enable_custom_integrations
):
    entry, push = await _setup(hass)
    push(CLEAR)
    await hass.async_block_till_done()
    await _install(hass)
    events = async_capture_events(hass, "uap_test")
    before = {s.entity_id: s.state for s in hass.states.async_all() if s.entity_id.split(".")[0] != "script" and "uap_" in s.entity_id}
    history_before = entry.runtime_data.history.history("31", 100)

    assert await async_setup_component(
        hass,
        "script",
        {
            "script": {
                "uap_test_notification": {
                    "use_blueprint": {
                        "path": "ukraine_alarm_pro/test_notification.yaml",
                        "input": {"region": "м. Київ", "test_actions": _action("test")},
                    }
                }
            }
        },
    )
    await hass.services.async_call("script", "uap_test_notification", blocking=True)
    await hass.async_block_till_done()

    assert [e.data["kind"] for e in events] == ["test"]
    assert events[0].data["msg"].startswith("ТЕСТ. м. Київ:")
    after = {s.entity_id: s.state for s in hass.states.async_all() if s.entity_id.split(".")[0] != "script" and "uap_" in s.entity_id}
    assert after == before
    assert entry.runtime_data.history.history("31", 100) == history_before


async def test_country_blueprint_delivers_same_timestamp_and_filters(
    hass, enable_custom_integrations
):
    from unittest.mock import patch

    from test_country_threats import COUNTRY_EVENT, _feed

    entry, push = await _setup(hass)
    name = "country_threat_notify.yaml"
    relative = f"automation/ukraine_alarm_pro/{name}"
    dest = Path(hass.config.path("blueprints", relative))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text((ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")
    assert await async_setup_component(hass, "automation", {
        "automation": [
            {"alias": "Full notifications", "use_blueprint": {
                "path": f"ukraine_alarm_pro/{name}",
                "input": {"event_entity": COUNTRY_EVENT,
                          "notify_action": _action("uk")},
            }},
            {"alias": "Filtered notifications", "use_blueprint": {
                "path": f"ukraine_alarm_pro/{name}",
                "input": {"event_entity": COUNTRY_EVENT, "language": "en",
                          "threats": ["missile_carriers"], "event_types": ["launch", "cleared"],
                          "notify_on_recovery": True, "notify_action": _action("en")},
            }},
        ],
    })
    await hass.async_block_till_done()
    events = async_capture_events(hass, "uap_test")
    push(parse_alert_payload(_feed()))
    await hass.async_block_till_done()
    assert events == []

    with patch.object(dt_util, "utcnow", return_value=dt_util.utcnow()):
        push(parse_alert_payload(_feed(hasBallistics=True, hasBoats=True, boatsRockets=True)))
    await hass.async_block_till_done()
    assert [e.data["msg"] for e in events if e.data["kind"] == "uk"] == [
        "По Україні · балістична загроза · початок",
        "По Україні · ракетоносії · пуск ракет",
    ]
    assert [e.data["msg"] for e in events if e.data["kind"] == "en"] == [
        "Country-wide · missile carriers · missile launch",
    ]
    coordinator = entry.runtime_data
    coordinator.supervisor.mode = "polling"
    coordinator.handle_mode_change("polling")
    coordinator.supervisor.mode = "websocket"
    coordinator.handle_mode_change("websocket")
    push(parse_alert_payload(_feed()))
    await hass.async_block_till_done()
    assert [e.data["msg"] for e in events[3:]] == [
        "Country-wide · missile carriers · threat ended (data restored)",
    ]

    # A real automation condition also rejects events while the health sensor is on.
    hass.states.async_set("binary_sensor.uap_data_stale", "on")
    attrs = dict(hass.states.get(COUNTRY_EVENT).attributes)
    attrs.update(event_type="launch", previous="active", current="launch", origin="live")
    hass.states.async_set(COUNTRY_EVENT, "2026-11-20T00:00:00.000+00:00", attrs)
    await hass.async_block_till_done()
    assert len(events) == 4
