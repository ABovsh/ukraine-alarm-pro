"""Event entities: one per region, fired on each accepted alert transition."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import UkraineAlarmProConfigEntry
from .const import CONF_REGIONS
from .entity import UapEntity
from .events import EVENT_TYPES


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UkraineAlarmProConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        RegionAlertEvent(coordinator, entry.entry_id, rid, info)
        for rid, info in entry.data[CONF_REGIONS].items()
    )


class RegionAlertEvent(UapEntity, EventEntity):
    """Alert transitions of one region, each with a self-contained payload.

    No state_class and no clock: it writes a row only when an event fires.
    """

    _attr_event_types = EVENT_TYPES
    _attr_translation_key = "event"

    def __init__(self, coordinator, entry_id, region_id, info) -> None:
        super().__init__(coordinator, entry_id)
        self._region_id = region_id
        self._attr_translation_placeholders = {"region": info["name"]}
        self._attr_unique_id = f"{entry_id}_{region_id}_event"
        self.entity_id = f"event.uap_{region_id}_event"

    @property
    def available(self) -> bool:
        # The last event stays meaningful across outages; staleness is an event.
        return True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.events.add_listener(self._region_id, self._on_event)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Map updates are not events; only transitions write this entity."""

    @callback
    def _on_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self._trigger_event(event_type, payload)
        self.async_write_ha_state()
