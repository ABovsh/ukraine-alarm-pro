"""Entity behavior tests: sensors reflect pushed snapshots, never false all-clear."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ukraine_alarm_pro.const import DOMAIN
from custom_components.ukraine_alarm_pro.models import parse_alert_payload

ENTRY_DATA = {
    "regions": {
        "703": {"name": "Вишнева громада", "ancestors": ["75", "14"]},
        "31": {"name": "м. Київ", "ancestors": []},
    }
}

SNAP_OBLAST_AIR = {
    "alerts": [
        {
            "regionId": "14",
            "regionType": "State",
            "activeAlerts": [{"type": "AIR", "lastUpdate": "2026-07-17T06:00:00Z"}],
        }
    ]
}


async def _setup(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, entry_id="test1")
    entry.add_to_hass(hass)
    sup = AsyncMock()
    sup.mode = "websocket"
    sup.set_listener = MagicMock()
    with patch(
        "custom_components.ukraine_alarm_pro.TransportSupervisor", return_value=sup
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    listener = sup.set_listener.call_args[0][0]
    return entry, listener


async def test_threat_sensor_inherits_oblast_alert(
    hass: HomeAssistant, enable_custom_integrations
):
    _, push = await _setup(hass)
    push(parse_alert_payload(SNAP_OBLAST_AIR))
    await hass.async_block_till_done()
    state = hass.states.get("sensor.uap_703_threat")
    assert state is not None
    assert state.state == "air"
    assert hass.states.get("binary_sensor.uap_703_alert").state == "on"
    assert hass.states.get("sensor.uap_31_threat").state == "none"
    assert hass.states.get("binary_sensor.uap_31_alert").state == "off"


async def test_all_clear_and_diagnostics(
    hass: HomeAssistant, enable_custom_integrations
):
    _, push = await _setup(hass)
    push(parse_alert_payload(SNAP_OBLAST_AIR))
    await hass.async_block_till_done()
    push(parse_alert_payload({"alerts": []}))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.uap_703_threat").state == "none"
    assert hass.states.get("sensor.uap_transport").state == "websocket"
    assert hass.states.get("sensor.uap_active_regions").state == "0"
