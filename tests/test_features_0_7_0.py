"""0.7.0: declaring-region identity, alert start time, restore across restarts."""

from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.ukraine_alarm_pro.const import (
    DOMAIN,
    RESTORE_MAX_AGE_SECONDS,
    STALE_AFTER_SECONDS,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from custom_components.ukraine_alarm_pro.models import (
    parse_alert_payload,
    region_alerts,
)

# Real shape, both transports: every alert names the region that declared it,
# and an affected region repeats an ancestor's alert verbatim (captured live
# 2026-09-02 — Вовчанська громада carrying Чугуївський район's air raid).
RAW = {
    "alerts": [
        {
            "regionId": "122",
            "regionType": "District",
            "regionName": "Чугуївський район",
            "activeAlerts": [
                {
                    "regionId": "122",
                    "regionType": "District",
                    "type": "AIR",
                    "lastUpdate": "2026-09-02T16:36:34.543539Z",
                }
            ],
        },
        {
            "regionId": "1313",
            "regionType": "Community",
            "regionName": "Вовчанська територіальна громада",
            "activeAlerts": [
                {
                    "regionId": "1313",
                    "regionType": "Community",
                    "type": "ARTILLERY",
                    "lastUpdate": "2024-05-20T09:31:37Z",
                },
                {
                    "regionId": "122",
                    "regionType": "District",
                    "type": "AIR",
                    "lastUpdate": "2026-09-02T16:36:34.543539Z",
                },
            ],
        },
    ]
}

# 20 = the oblast; 122 and 1313 are its descendants.
ENTRY_DATA = {
    "regions": {
        "20": {
            "name": "Харківська область",
            "ancestors": [],
            "descendants": ["122", "1313"],
        }
    }
}


def test_parse_keeps_declaring_region_and_names():
    snap = parse_alert_payload(RAW)
    air = snap.regions["1313"][1]
    assert air.region_id == "122"
    assert air.region_type == "District"
    # An alert with no regionId of its own was declared by its container.
    legacy = parse_alert_payload(
        {"alerts": [{"regionId": "31", "activeAlerts": [{"type": "AIR"}]}]}
    )
    assert legacy.regions["31"][0].region_id == "31"
    assert snap.names["122"] == "Чугуївський район"


def test_region_alerts_dedupes_by_declaring_region():
    """The same declared alert reached the oblast through two descendants."""
    snap = parse_alert_payload(RAW)
    found = region_alerts(snap, "20", [], ["122", "1313"])
    assert [(a.region_id, a.type) for a in found] == [
        ("122", "AIR"),
        ("1313", "ARTILLERY"),
    ]


async def _setup(hass: HomeAssistant, entry_data=None):
    entry = MockConfigEntry(
        domain=DOMAIN, data=entry_data or ENTRY_DATA, entry_id="test1"
    )
    entry.add_to_hass(hass)
    sup = AsyncMock()
    sup.mode = "websocket"
    sup.set_listener = MagicMock()
    sup.set_mode_listener = MagicMock()
    with patch(
        "custom_components.ukraine_alarm_pro.TransportSupervisor", return_value=sup
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, sup.set_listener.call_args[0][0]


async def test_alert_started_reports_earliest_declaration(
    hass: HomeAssistant, enable_custom_integrations
):
    _, push = await _setup(hass)
    push(parse_alert_payload(RAW))
    await hass.async_block_till_done()

    state = hass.states.get("sensor.uap_20_alert_started")
    assert state is not None
    assert dt_util.parse_datetime(state.state) == dt_util.parse_datetime(
        "2024-05-20T09:31:37Z"
    )


async def test_alert_started_unknown_when_quiet(
    hass: HomeAssistant, enable_custom_integrations
):
    _, push = await _setup(hass)
    push(parse_alert_payload({"alerts": []}))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.uap_20_alert_started").state == "unknown"


async def test_active_alerts_attribute_names_the_declaring_region(
    hass: HomeAssistant, enable_custom_integrations
):
    _, push = await _setup(hass)
    push(parse_alert_payload(RAW))
    await hass.async_block_till_done()

    attrs = hass.states.get("sensor.uap_20_threat").attributes
    # Newest first, and no double count of the air raid that arrived twice.
    assert attrs["active_alert_count"] == 2
    assert attrs["active_alerts"][0] == {
        "region_id": "122",
        "region_name": "Чугуївський район",
        "type": "AIR",
        "since": "2026-09-02T16:36:34.543539Z",
    }


def _stored(saved_at: str) -> dict:
    return {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            "saved_at": saved_at,
            "regions": {
                "122": [
                    {
                        "type": "AIR",
                        "last_update": "2026-09-02T16:36:34.543539Z",
                        "region_id": "122",
                        "region_type": "District",
                    }
                ]
            },
            "names": {"122": "Чугуївський район"},
        },
    }


async def test_restores_last_snapshot_before_the_first_push(
    hass: HomeAssistant, enable_custom_integrations, hass_storage
):
    """Power back, internet not yet: entities must not come up blind."""
    hass_storage[STORAGE_KEY] = _stored(dt_util.utcnow().isoformat())
    await _setup(hass)

    assert hass.states.get("sensor.uap_20_threat").state == "air"
    assert hass.states.get("binary_sensor.uap_20_alert").state == "on"
    # Restored, not received — the state is explicitly not trustworthy yet.
    assert hass.states.get("binary_sensor.uap_data_stale").state == "on"


async def test_ignores_a_stale_stored_snapshot(
    hass: HomeAssistant, enable_custom_integrations, hass_storage
):
    old = dt_util.utcnow() - timedelta(seconds=RESTORE_MAX_AGE_SECONDS + 60)
    hass_storage[STORAGE_KEY] = _stored(old.isoformat())
    await _setup(hass)
    assert hass.states.get("sensor.uap_20_threat").state == "unavailable"


async def test_stores_the_snapshot_for_the_next_start(
    hass: HomeAssistant, enable_custom_integrations, hass_storage
):
    entry, push = await _setup(hass)
    push(parse_alert_payload(RAW))
    await hass.async_block_till_done()
    await entry.runtime_data.async_save_now()

    stored = hass_storage[STORAGE_KEY]["data"]
    assert stored["regions"]["122"][0]["region_id"] == "122"
    assert stored["names"]["122"] == "Чугуївський район"
    assert dt_util.parse_datetime(stored["saved_at"]) is not None


async def test_deselecting_a_region_also_removes_its_start_sensor(
    hass: HomeAssistant, enable_custom_integrations
):
    entry, _ = await _setup(hass)
    registry = er.async_get(hass)
    assert registry.async_get("sensor.uap_20_alert_started") is not None

    hass.config_entries.async_update_entry(entry, data={"regions": {}})
    await hass.async_block_till_done()
    assert registry.async_get("sensor.uap_20_alert_started") is None


BLUEPRINT = (
    Path(__file__).parent.parent
    / "blueprints/automation/ukraine_alarm_pro/alert_notify.yaml"
)


async def _setup_blueprint_automation(hass: HomeAssistant):
    """Install the shipped blueprint and build a real automation from it."""
    dest = Path(hass.config.path("blueprints/automation/ukraine_alarm_pro"))
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "alert_notify.yaml").write_text(
        BLUEPRINT.read_text(encoding="utf-8"), encoding="utf-8"
    )
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
                        "on_alert": [
                            {
                                "event": "uap_test",
                                "event_data": {"kind": "start", "msg": "{{ message }}"},
                            }
                        ],
                        "on_clear": [
                            {
                                "event": "uap_test",
                                "event_data": {"kind": "clear", "msg": "{{ message }}"},
                            }
                        ],
                    },
                }
            }
        },
    )
    await hass.async_block_till_done()


async def test_blueprint_notifies_on_start_and_clear(
    hass: HomeAssistant, enable_custom_integrations
):
    _, push = await _setup(hass)
    push(parse_alert_payload({"alerts": []}))
    await hass.async_block_till_done()
    await _setup_blueprint_automation(hass)

    events = async_capture_events(hass, "uap_test")

    push(parse_alert_payload(RAW))
    await hass.async_block_till_done()
    assert [e.data["kind"] for e in events] == ["start"]
    assert "Харківська область" in events[0].data["msg"]
    assert "air" in events[0].data["msg"]

    push(parse_alert_payload({"alerts": []}))
    await hass.async_block_till_done()
    assert [e.data["kind"] for e in events] == ["start", "clear"]
    assert "min" in events[1].data["msg"]


async def test_blueprint_stays_silent_while_the_feed_is_stale(
    hass: HomeAssistant, enable_custom_integrations
):
    """An alert map that appears without a fresh push is not announced.

    A push always refreshes the liveness clock, so the only way the region
    entities move while the feed is stale is a map published from somewhere
    other than a transport — the restore path today. That map may be hours
    old, and announcing it as a new raid is exactly the false alarm the
    documented `data_stale` guard exists to prevent.
    """
    entry, push = await _setup(hass)
    push(parse_alert_payload({"alerts": []}))
    await hass.async_block_till_done()
    await _setup_blueprint_automation(hass)

    events = async_capture_events(hass, "uap_test")
    coordinator = entry.runtime_data
    coordinator.last_push = dt_util.utcnow() - timedelta(
        seconds=STALE_AFTER_SECONDS + 60
    )
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.uap_data_stale").state == "on"

    coordinator.async_set_updated_data(parse_alert_payload(RAW))
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.uap_20_alert").state == "on"
    assert events == []


async def test_blueprint_does_not_fire_on_a_restored_alert(
    hass: HomeAssistant, enable_custom_integrations, hass_storage
):
    """Coming back from a restart mid-raid is not a new alert."""
    hass_storage[STORAGE_KEY] = _stored(dt_util.utcnow().isoformat())
    await _setup(hass)
    await _setup_blueprint_automation(hass)

    events = async_capture_events(hass, "uap_test")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.uap_20_alert").state == "on"
    assert events == []
