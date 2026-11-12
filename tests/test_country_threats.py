"""Country-wide threats from the map feed: ballistics, strategic and tactical
aviation, missile carriers at sea.

Like the MiG status, only the live WebSocket carries them: on polling or stale
data each sensor is unknown, never a "none" nobody confirmed.
"""

import time
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from test_entities import _setup

from custom_components.ukraine_alarm_pro import _async_purge_deselected_regions
from custom_components.ukraine_alarm_pro.const import STALE_AFTER_SECONDS
from custom_components.ukraine_alarm_pro.models import (
    CountryThreat,
    parse_alert_payload,
    parse_country,
)

EMPTY = "0001-01-01T00:00:00"
SENSORS = {
    "ballistics": "sensor.uap_ballistics",
    "strategic_aviation": "sensor.uap_strategic_aviation",
    "tactical_aviation": "sensor.uap_tactical_aviation",
    "missile_carriers": "sensor.uap_missile_carriers",
}


def _feed(**flags):
    notes = {
        "hasMig": False, "hasBoats": False, "hasTacticalAviation": False,
        "hasStrategicAviation": False, "hasBallistics": False, "migRockets": False,
        "boatsRockets": False, "tacticalAviationRockets": False, "strategicAviationRockets": False,
        "lastBoatsUpdateTime": EMPTY, "lastTacticalAviationUpdateTime": EMPTY,
        "lastStrategicAviationUpdateTime": EMPTY, "lastBallisticsUpdateTime": EMPTY,
        "lastBoatsRocketsUpdateTime": EMPTY, "lastTacticalAviationRocketsUpdateTime": EMPTY,
        "lastStrategicAviationRocketsUpdateTime": EMPTY,
    }
    notes.update(flags)
    return {"alerts": [], "migAlerts": [], "mapNotifications": notes}


def test_parse_reads_each_threat():
    quiet = parse_country(_feed())
    assert quiet == {key: CountryThreat() for key in SENSORS}
    feed = parse_country(_feed(
        hasBallistics=True, lastBallisticsUpdateTime="2026-11-12T18:00:00Z",
        hasStrategicAviation=True, lastStrategicAviationUpdateTime="2026-11-12T17:00:00Z",
        hasBoats=True, boatsRockets=True, lastBoatsRocketsUpdateTime="2026-11-12T18:05:00Z",
        lastBoatsUpdateTime="2026-11-12T10:00:00Z",
    ))
    assert feed["ballistics"] == CountryThreat("active", "2026-11-12T18:00:00Z")
    assert feed["strategic_aviation"] == CountryThreat("active", "2026-11-12T17:00:00Z")
    # A launch is timed by its own stamp, not by when the ships were first reported.
    assert feed["missile_carriers"] == CountryThreat("launch", "2026-11-12T18:05:00Z")
    assert feed["tactical_aviation"] == CountryThreat()
    # A launch flag alone does not raise the threat, as with the MiG; a zero date is no time.
    alone = parse_country(_feed(tacticalAviationRockets=True))
    assert alone["tactical_aviation"] == CountryThreat()
    assert parse_country(_feed(hasTacticalAviation=True))["tactical_aviation"] == CountryThreat("active", "")


def test_missing_or_damaged_data_is_unknown_and_never_costs_the_map():
    assert parse_country({"alerts": []}) is None
    assert parse_country({"alerts": [], "mapNotifications": "x"}) is None
    assert parse_country([]) is None
    snap = parse_alert_payload({"alerts": [{"regionId": "31", "activeAlerts": []}], "mapNotifications": 7})
    assert "31" in snap.regions and snap.country is None
    # One damaged flag does not invent a threat.
    assert parse_country(_feed(hasBallistics="yes"))["ballistics"] == CountryThreat()


async def test_sensors_follow_the_feed(hass: HomeAssistant, enable_custom_integrations):
    _, push = await _setup(hass)
    assert {hass.states.get(e).state for e in SENSORS.values()} == {"unknown"}
    push(parse_alert_payload(_feed()))
    await hass.async_block_till_done()
    assert {hass.states.get(e).state for e in SENSORS.values()} == {"none"}
    push(parse_alert_payload(_feed(hasBallistics=True, hasBoats=True, boatsRockets=True,
                                   lastBoatsRocketsUpdateTime="2026-11-12T18:05:00Z")))
    await hass.async_block_till_done()
    assert hass.states.get(SENSORS["ballistics"]).state == "active"
    carriers = hass.states.get(SENSORS["missile_carriers"])
    assert carriers.state == "launch" and carriers.attributes["since"] == "2026-11-12T18:05:00Z"
    assert "since" not in hass.states.get(SENSORS["tactical_aviation"]).attributes
    assert "state_class" not in carriers.attributes


async def test_a_feed_without_the_data_keeps_the_live_status(hass: HomeAssistant, enable_custom_integrations):
    _, push = await _setup(hass)
    push(parse_alert_payload(_feed(hasStrategicAviation=True)))
    await hass.async_block_till_done()
    push(parse_alert_payload([]))  # the watchdog's poll cross-check
    await hass.async_block_till_done()
    assert hass.states.get(SENSORS["strategic_aviation"]).state == "active"


async def test_polling_and_stale_data_make_them_unknown(hass: HomeAssistant, enable_custom_integrations):
    entry, push = await _setup(hass)
    coordinator = entry.runtime_data
    push(parse_alert_payload(_feed(hasBallistics=True)))
    await hass.async_block_till_done()
    coordinator.supervisor.mode = "polling"
    coordinator.handle_mode_change("polling")
    await hass.async_block_till_done()
    assert hass.states.get(SENSORS["ballistics"]).state == "unknown"
    coordinator.supervisor.mode = "websocket"
    coordinator.handle_mode_change("websocket")
    await hass.async_block_till_done()
    assert hass.states.get(SENSORS["ballistics"]).state == "active"
    coordinator.last_push = dt_util.utcnow() - timedelta(seconds=STALE_AFTER_SECONDS + 60)
    coordinator._last_push_monotonic = time.monotonic() - STALE_AFTER_SECONDS - 60
    for listener in tuple(coordinator._health_listeners):
        listener()
    await hass.async_block_till_done()
    assert hass.states.get(SENSORS["ballistics"]).state == "unknown"


async def test_an_unchanged_feed_writes_no_rows(hass: HomeAssistant, enable_custom_integrations):
    _, push = await _setup(hass)
    push(parse_alert_payload(_feed(hasBallistics=True)))
    await hass.async_block_till_done()
    rows = []

    @callback
    def seen(event):
        if event.data["entity_id"] in SENSORS.values():
            rows.append(event.data["entity_id"])

    hass.bus.async_listen("state_changed", seen)
    for _ in range(3):
        push(parse_alert_payload(_feed(hasBallistics=True)))
        await hass.async_block_till_done()
    assert rows == []
    # Only the sensor that changed writes.
    push(parse_alert_payload(_feed(hasBallistics=True, hasTacticalAviation=True)))
    await hass.async_block_till_done()
    assert rows == [SENSORS["tactical_aviation"]]


async def test_hub_sensors_survive_region_cleanup(hass: HomeAssistant, enable_custom_integrations):
    entry, _push = await _setup(hass)
    _async_purge_deselected_regions(hass, entry)
    registry = er.async_get(hass)
    assert all(registry.async_get(entity_id) is not None for entity_id in SENSORS.values())
