"""Air-level transitions, persistence and actual HA state-event cost."""

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_capture_events
from test_features_0_7_0 import _setup

from custom_components.ukraine_alarm_pro.coordinator import _snapshot_from_store
from custom_components.ukraine_alarm_pro.models import (
    parse_alert_payload,
    region_alerts,
)

ENTITY = "sensor.uap_20_air_alert_level"
STAMP = "2026-09-08T05:51:37.453397Z"


def payload(*levels, reason="", region="122", alert_type="AIR"):
    return [
        {
            "regionId": region,
            "activeAlerts": [
                {
                    "regionId": region,
                    "type": alert_type,
                    "lastUpdate": STAMP,
                    "activeAlertLevels": [
                        {"alertLevel": level, "reason": reason, "createdAt": STAMP}
                        for level in levels
                    ],
                }
            ],
        }
    ]


def test_levels_participate_in_snapshot_equality_and_ignore_order():
    yellow = parse_alert_payload(payload("Yellow"))
    mixed = parse_alert_payload(payload("Red", "Yellow"))
    assert yellow.active != mixed.active
    assert mixed.active == parse_alert_payload(payload("Yellow", "Red", "Red")).active
    assert (
        mixed.active
        != parse_alert_payload(payload("Yellow", "Red", reason="Missile risk")).active
    )


def test_duplicate_inherited_levels_are_merged_independent_of_order():
    raw = payload("Yellow")
    echo = deepcopy(payload("Red")[0])
    echo["regionId"] = "1313"  # repeats the same declaration from 122
    raw.append(echo)
    snap = parse_alert_payload(raw)
    a = region_alerts(snap, "20", [], ["122", "1313"])
    b = region_alerts(snap, "20", [], ["1313", "122"])
    assert a == b
    assert len(a) == 1
    assert {level.level for level in a[0].levels} == {"red", "yellow"}


@pytest.mark.parametrize(
    "levels,expected",
    [
        (("Yellow",), "yellow"),
        (("Red",), "red"),
        (("Yellow", "Red"), "red"),
        ((), "unrecognized"),
        (("Purple",), "unrecognized"),
        (("Purple", "Yellow"), "yellow"),
    ],
)
async def test_level_sensor(hass, enable_custom_integrations, levels, expected):
    _, push = await _setup(hass)
    push(parse_alert_payload(payload(*levels)))
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == expected
    assert "state_class" not in state.attributes
    assert "created_at" not in state.attributes
    assert hass.states.get("sensor.uap_20_threat").state == "air"
    assert hass.states.get("binary_sensor.uap_20_alert").state == "on"


async def test_only_air_alerts_contribute_to_level(hass, enable_custom_integrations):
    _, push = await _setup(hass)
    push(parse_alert_payload(payload("Red", alert_type="ARTILLERY")))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "none"


@pytest.mark.parametrize("bad", [None, {}, "Red", [None, {}, {"alertLevel": []}]])
async def test_malformed_levels_never_clear_air_alert(
    hass, enable_custom_integrations, bad
):
    raw = payload("Yellow")
    raw[0]["activeAlerts"][0]["activeAlertLevels"] = bad
    _, push = await _setup(hass)
    push(parse_alert_payload(raw))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "unrecognized"
    assert hass.states.get("binary_sensor.uap_20_alert").state == "on"


async def test_state_events_only_on_meaningful_local_changes(
    hass, enable_custom_integrations
):
    _, push = await _setup(hass)
    raw = payload("Yellow", reason="Drone risk")
    push(parse_alert_payload(raw))
    await hass.async_block_till_done()
    events = async_capture_events(hass, EVENT_STATE_CHANGED)
    for _ in range(20):
        push(parse_alert_payload(raw))
    # Every push changes another region, while our region stays unchanged.
    for i in range(20):
        push(parse_alert_payload(raw + payload("Red", reason=str(i), region="9999")))
        await hass.async_block_till_done()
    assert not [
        e
        for e in events
        if e.data["entity_id"].startswith(("sensor.uap_20_", "binary_sensor.uap_20_"))
    ]
    for levels in [("Yellow", "Red"), ("Red", "Yellow", "Red"), ("Yellow",), ()]:
        push(parse_alert_payload(payload(*levels) if levels else []))
        await hass.async_block_till_done()
    assert [
        e.data["new_state"].state for e in events if e.data["entity_id"] == ENTITY
    ] == ["red", "yellow", "none"]


async def test_reason_attributes_are_bounded_and_timestamps_not_recorded(
    hass, enable_custom_integrations
):
    _, push = await _setup(hass)
    raw = [
        payload("Yellow", reason=f"{i:02d}" + "x" * 500, region=str(200 + i))[0]
        for i in range(40)
    ]
    # All declarations appear under the selected descendant.
    raw = [{"regionId": "122", "activeAlerts": [r["activeAlerts"][0] for r in raw]}]
    push(parse_alert_payload(raw))
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert len(state.attributes["reasons"]) == 25
    assert max(map(len, state.attributes["reasons"])) <= 256
    assert state.attributes["reason_count"] == 40
    events = async_capture_events(hass, EVENT_STATE_CHANGED)
    raw[0]["activeAlerts"][0]["activeAlertLevels"][0]["createdAt"] = (
        "2026-09-08T06:00:00Z"
    )
    push(parse_alert_payload(raw))
    await hass.async_block_till_done()
    assert not [e for e in events if e.data["entity_id"] == ENTITY]


async def test_storage_roundtrip_and_legacy(
    hass, enable_custom_integrations, hass_storage
):
    entry, push = await _setup(hass)
    push(parse_alert_payload(payload("Yellow")))
    await entry.runtime_data.async_save_now()
    push(parse_alert_payload(payload("Yellow", "Red", reason="Risk")))
    await entry.runtime_data.async_save_now()
    stored = entry.runtime_data._store_data()
    assert _snapshot_from_store(stored).active == entry.runtime_data.data.active
    # Simulate a restart, including the real restore path.
    await hass.config_entries.async_unload(entry.entry_id)
    supervisor = AsyncMock(mode="websocket")
    supervisor.set_listener = MagicMock()
    supervisor.set_mode_listener = MagicMock()
    with patch(
        "custom_components.ukraine_alarm_pro.TransportSupervisor",
        return_value=supervisor,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "red"
    assert hass.states.get("binary_sensor.uap_data_stale").state == "on"
    for alerts in stored["regions"].values():
        for alert in alerts:
            alert.pop("levels", None)
    assert _snapshot_from_store(stored).regions["122"][0].levels == ()


async def test_level_entity_removed_when_region_deselected(
    hass, enable_custom_integrations
):
    entry, _ = await _setup(hass)
    registry = er.async_get(hass)
    assert registry.async_get(ENTITY) is not None
    hass.config_entries.async_update_entry(entry, data={"regions": {}})
    await hass.async_block_till_done()
    assert registry.async_get(ENTITY) is None


async def setup_level_blueprint(hass):
    source = (
        Path(__file__).parent.parent
        / "blueprints/automation/ukraine_alarm_pro/alert_notify.yaml"
    )
    dest = Path(
        hass.config.path("blueprints/automation/ukraine_alarm_pro/alert_notify.yaml")
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(source.read_text())
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": "ukraine_alarm_pro/alert_notify.yaml",
                    "input": {
                        "alert_sensor": "binary_sensor.uap_20_alert",
                        "threat_sensor": "sensor.uap_20_threat",
                        "started_sensor": "sensor.uap_20_alert_started",
                        "level_sensor": ENTITY,
                        "on_alert": [
                            {
                                "event": "uap_level_test",
                                "event_data": {"kind": "start", "level": "{{ level }}"},
                            }
                        ],
                        "on_clear": [
                            {"event": "uap_level_test", "event_data": {"kind": "clear"}}
                        ],
                        "on_escalation": [
                            {
                                "event": "uap_level_test",
                                "event_data": {
                                    "kind": "escalation",
                                    "reason": "{{ reason }}",
                                },
                            }
                        ],
                    },
                }
            }
        },
    )
    await hass.async_block_till_done()


async def test_blueprint_escalates_once_and_keeps_start_clear(
    hass, enable_custom_integrations
):
    _, push = await _setup(hass)
    push(parse_alert_payload([]))
    await hass.async_block_till_done()
    await setup_level_blueprint(hass)
    events = async_capture_events(hass, "uap_level_test")
    for levels in [("Yellow",), ("Yellow", "Red"), ("Red", "Yellow"), ()]:
        push(parse_alert_payload(payload(*levels, reason="Risk") if levels else []))
        await hass.async_block_till_done()
    assert [e.data["kind"] for e in events] == ["start", "escalation", "clear"]
    assert events[0].data["level"] == "yellow"
    assert events[1].data["reason"] == "Risk"


async def test_blueprint_does_not_escalate_stale_or_initial_red(
    hass, enable_custom_integrations
):
    entry, push = await _setup(hass)
    await setup_level_blueprint(hass)
    events = async_capture_events(hass, "uap_level_test")
    push(parse_alert_payload(payload("Red")))
    await hass.async_block_till_done()
    assert events == []
    push(parse_alert_payload(payload("Yellow")))
    await hass.async_block_till_done()
    entry.runtime_data.last_push = dt_util.utcnow() - timedelta(hours=1)
    entry.runtime_data.async_set_updated_data(parse_alert_payload(payload("Red")))
    await hass.async_block_till_done()
    assert events == []


async def test_captured_levels_survive_both_transports():
    """Public feed samples captured 2026-09-08, served over real local sockets."""
    import asyncio
    import json

    from aiohttp import ClientSession, web
    from test_poll_transport import _server
    from test_ws_transport import FakeAlarmServer

    from custom_components.ukraine_alarm_pro.api.poll import PollTransport
    from custom_components.ukraine_alarm_pro.api.ws import WsTransport

    fixtures = Path(__file__).parent / "fixtures"
    poll_data = json.loads((fixtures / "air_levels_poll.json").read_text())
    ws_data = json.loads((fixtures / "air_levels_ws.json").read_text())

    async def handler(request):
        return web.json_response(poll_data)

    poll_server = await _server(handler)
    ws_server = await FakeAlarmServer().start()
    try:
        async with ClientSession() as session:
            poll = PollTransport(
                session, base_url=str(poll_server.make_url("")).rstrip("/")
            )
            poll_snap = await poll.fetch()
            ws = WsTransport(session, map_url=ws_server.page_url)
            stream = ws.stream()
            try:
                await asyncio.wait_for(anext(stream), 5)
                await ws_server.pushes.put(ws_data)
                ws_snap = await asyncio.wait_for(anext(stream), 5)
            finally:
                await stream.aclose()
                await ws.close()
            for snap in (poll_snap, ws_snap):
                assert {
                    level.level
                    for alerts in snap.regions.values()
                    for a in alerts
                    for level in a.levels
                } == {"red", "yellow"}
                assert any(
                    len(a.levels) == 2
                    for alerts in snap.regions.values()
                    for a in alerts
                )
    finally:
        await poll_server.close()
        await ws_server.close()
