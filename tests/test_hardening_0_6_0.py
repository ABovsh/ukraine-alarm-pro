"""Hardening tests for 0.6.0 — deselecting a region must delete its entities.

The options flow rebuilds the entities on save, but HA keeps registry entries
for entities that are no longer created: a region removed from the selection
left `sensor.uap_<id>_threat` and `binary_sensor.uap_<id>_alert` behind forever,
permanently unavailable, and the user had to hunt them down in the entity
registry by hand. Setup now purges them.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ukraine_alarm_pro.const import DOMAIN

ENTRY_ID = "test1"
ENTRY_DATA = {
    "regions": {
        "703": {
            "name": "Вишнева громада",
            "ancestors": ["75", "14"],
            "descendants": [],
        },
    }
}


def _seed_stale_region(hass: HomeAssistant, entry: MockConfigEntry) -> list[str]:
    """Register entities of region 692 as if it had been selected earlier."""
    registry = er.async_get(hass)
    return [
        registry.async_get_or_create(
            platform,
            DOMAIN,
            f"{ENTRY_ID}_692_{suffix}",
            config_entry=entry,
            suggested_object_id=f"uap_692_{suffix}",
        ).entity_id
        for platform, suffix in (("sensor", "threat"), ("binary_sensor", "alert"))
    ]


async def _setup(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, entry_id=ENTRY_ID)
    entry.add_to_hass(hass)
    stale = _seed_stale_region(hass, entry)
    sup = AsyncMock()
    sup.mode = "websocket"
    sup.set_listener = MagicMock()
    sup.set_mode_listener = MagicMock()
    with patch(
        "custom_components.ukraine_alarm_pro.TransportSupervisor", return_value=sup
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return stale


async def test_deselected_region_entities_are_removed(
    hass: HomeAssistant, enable_custom_integrations
):
    stale = await _setup(hass)
    registry = er.async_get(hass)
    for entity_id in stale:
        assert registry.async_get(entity_id) is None, (
            f"{entity_id} survived; a deselected region must not leave orphans"
        )


async def test_selected_and_hub_entities_survive(
    hass: HomeAssistant, enable_custom_integrations
):
    await _setup(hass)
    registry = er.async_get(hass)
    for entity_id in (
        "sensor.uap_703_threat",
        "binary_sensor.uap_703_alert",
        "sensor.uap_transport",
        "sensor.uap_active_regions",
        "sensor.uap_last_update",
        "binary_sensor.uap_data_stale",
    ):
        assert registry.async_get(entity_id) is not None, f"{entity_id} was purged"
