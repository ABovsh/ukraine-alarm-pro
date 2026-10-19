"""`sensor.uap_<id>_alert_cleared`: when the last alert in the region ended.

Automations ("quiet for 30 min") and the card's quiet timer read it without a
journal call. It is written once per clear and never on an unchanged map.
"""

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_capture_events
from test_entities import _setup

from custom_components.ukraine_alarm_pro.models import parse_alert_payload

QUIET = {"alerts": []}
AIR_31 = {"alerts": [{"regionId": "31", "activeAlerts": [{"type": "AIR", "lastUpdate": "2026-10-19T10:00:00Z"}]}]}
ENTITY = "sensor.uap_31_alert_cleared"


async def test_alert_cleared_is_written_once_per_clear(
    hass: HomeAssistant, enable_custom_integrations
):
    _, push = await _setup(hass)
    push(parse_alert_payload(QUIET))
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes["device_class"] == "timestamp"
    assert "state_class" not in state.attributes
    assert state.attributes["region_id"] == "31"

    push(parse_alert_payload(AIR_31))
    await hass.async_block_till_done()
    before = hass.states.get(ENTITY).state
    events = async_capture_events(hass, EVENT_STATE_CHANGED)
    push(parse_alert_payload(QUIET))
    await hass.async_block_till_done()
    cleared = dt_util.parse_datetime(hass.states.get(ENTITY).state)
    assert cleared is not None
    assert abs((dt_util.utcnow() - cleared).total_seconds()) < 60
    assert hass.states.get(ENTITY).state != before
    # Unchanged quiet maps and a new alert leave the last clear as it was.
    push(parse_alert_payload(QUIET))
    push(parse_alert_payload(AIR_31))
    await hass.async_block_till_done()
    assert dt_util.parse_datetime(hass.states.get(ENTITY).state) == cleared
    writes = [e for e in events if e.data["entity_id"] == ENTITY]
    assert len(writes) == 1


async def test_active_regions_keeps_history_but_no_statistics(
    hass: HomeAssistant, enable_custom_integrations
):
    """781 states and 287 short-term statistics rows a day on the live HA:
    the country-wide count changes with every map update. The states stay;
    the five-minute statistics on top of them are dropped."""
    _, push = await _setup(hass)
    push(parse_alert_payload(AIR_31))
    await hass.async_block_till_done()
    state = hass.states.get("sensor.uap_active_regions")
    assert state.state == "1"
    assert "state_class" not in state.attributes
