"""The bundled dashboard card: served and registered by the integration."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from test_entities import _setup

from custom_components.ukraine_alarm_pro import CARD_URL, _async_register_card
from custom_components.ukraine_alarm_pro.models import parse_alert_payload

CARD = Path(__file__).parent.parent / "custom_components/ukraine_alarm_pro/frontend/ukraine-alarm-pro-card.js"


async def test_card_is_served_and_added_to_the_frontend(hass: HomeAssistant):
    hass.config.components.add("frontend")
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    with patch("custom_components.ukraine_alarm_pro.add_extra_js_url") as add_js:
        await _async_register_card(hass)
    [[paths], _] = hass.http.async_register_static_paths.call_args
    assert paths[0].url_path == CARD_URL
    assert Path(paths[0].path) == CARD
    url = add_js.call_args[0][1]
    assert url.startswith(f"{CARD_URL}?v=")
    assert len(url.split("?v=")[1]) == 8, "cache-busting content hash"


async def test_card_registration_is_skipped_without_the_frontend(hass: HomeAssistant):
    hass.http = None
    with patch("custom_components.ukraine_alarm_pro.add_extra_js_url") as add_js:
        await _async_register_card(hass)
    add_js.assert_not_called()


async def test_region_entities_carry_their_region_id_for_the_card(
    hass: HomeAssistant, enable_custom_integrations
):
    _, push = await _setup(hass)
    push(parse_alert_payload({"alerts": []}))
    await hass.async_block_till_done()
    for entity_id in (
        "binary_sensor.uap_31_alert",
        "sensor.uap_31_threat",
        "sensor.uap_31_air_alert_level",
        "sensor.uap_31_alert_started",
        "event.uap_31_event",
    ):
        assert hass.states.get(entity_id).attributes["region_id"] == "31", entity_id


def test_card_defines_its_element_and_picker_entry():
    source = CARD.read_text(encoding="utf-8")
    assert 'customElements.define(CARD' in source
    assert "window.customCards" in source
    assert "getConfigForm" in source
