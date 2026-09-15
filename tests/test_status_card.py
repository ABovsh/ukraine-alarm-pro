"""The bundled dashboard card: served and registered by the integration."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from test_entities import _setup

from custom_components.ukraine_alarm_pro import CARD_URL, _async_register_card
from custom_components.ukraine_alarm_pro.models import parse_alert_payload

CARD = Path(__file__).parent.parent / "custom_components/ukraine_alarm_pro/frontend/ukraine-alarm-pro-card.js"


class FakeResources:
    """Storage-mode Lovelace resources, as HACS cards are registered."""

    def __init__(self, items=()):
        self.items = [dict(item) for item in items]
        self.loaded = False

    async def async_get_info(self):
        self.loaded = True
        return {"resources": len(self.items)}

    def async_items(self):
        return list(self.items)

    async def async_create_item(self, data):
        self.items.append({"id": f"r{len(self.items)}", **data})

    async def async_update_item(self, item_id, data):
        for item in self.items:
            if item["id"] == item_id:
                item.update(data)


def _frontend(hass, resources):
    hass.config.components.update({"frontend", "lovelace"})
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    hass.data["lovelace"] = MagicMock(resources=resources, resource_mode="storage")


async def test_card_is_registered_as_a_lovelace_resource(hass: HomeAssistant):
    """Loaded after the frontend is ready, like any HACS card — no race."""
    resources = FakeResources([{"id": "x", "res_type": "module", "url": "/hacsfiles/other.js"}])
    _frontend(hass, resources)
    with patch("custom_components.ukraine_alarm_pro.add_extra_js_url") as add_js:
        await _async_register_card(hass)
    [[paths], _] = hass.http.async_register_static_paths.call_args
    assert paths[0].url_path == CARD_URL
    assert Path(paths[0].path) == CARD
    ours = [i for i in resources.items if i["url"].startswith(CARD_URL)]
    assert len(ours) == 1
    assert ours[0]["res_type"] == "module"
    assert len(ours[0]["url"].split("?v=")[1]) == 8, "cache-busting content hash"
    add_js.assert_not_called()


async def test_resource_url_is_updated_not_duplicated(hass: HomeAssistant):
    resources = FakeResources([{"id": "old", "res_type": "module", "url": f"{CARD_URL}?v=deadbeef"}])
    _frontend(hass, resources)
    await _async_register_card(hass)
    await _async_register_card(hass)
    ours = [i for i in resources.items if i["url"].startswith(CARD_URL)]
    assert len(ours) == 1 and ours[0]["id"] == "old"
    assert not ours[0]["url"].endswith("deadbeef")


async def test_yaml_mode_dashboards_fall_back_to_an_extra_module(hass: HomeAssistant):
    _frontend(hass, MagicMock(spec=["async_items"]))
    hass.data["lovelace"].resource_mode = "yaml"
    with patch("custom_components.ukraine_alarm_pro.add_extra_js_url") as add_js:
        await _async_register_card(hass)
    assert add_js.call_args[0][1].startswith(f"{CARD_URL}?v=")


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
    # Statistics come from the journal actions, not from new entities.
    assert '"get_summary"' in source and '"get_history"' in source
    assert "return_response: true" in source
