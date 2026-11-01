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
    entities: list[EventEntity] = [
        RegionAlertEvent(coordinator, entry.entry_id, rid, info)
        for rid, info in entry.data[CONF_REGIONS].items()
    ]
    entities.append(MigEvent(coordinator, entry.entry_id))
    async_add_entities(entities)


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
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"region_id": self._region_id}

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


class MigEvent(UapEntity, EventEntity):
    """MiG-31K transitions on the live feed; a row only when one fires."""

    _attr_event_types = ["takeoff", "launch", "cleared"]  # noqa: RUF012
    _attr_translation_key = "mig"

    def __init__(self, coordinator, entry_id) -> None:
        super().__init__(coordinator, entry_id)
        # Not "_event": region cleanup reads that suffix as "<region>_event".
        self._attr_unique_id = f"{entry_id}_mig_events"
        self.entity_id = "event.uap_mig_event"

    @property
    def available(self) -> bool:
        return True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.add_mig_event_listener(self._on_event))

    @callback
    def _handle_coordinator_update(self) -> None:
        """Map updates are not events; only transitions write this entity."""

    @callback
    def _on_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self._trigger_event(event_type, payload)
        self.async_write_ha_state()
