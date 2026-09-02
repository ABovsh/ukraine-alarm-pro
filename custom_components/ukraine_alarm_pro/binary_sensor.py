"""Binary sensors: per-region any-alert flag + feed health."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import UkraineAlarmProConfigEntry
from .const import CONF_REGIONS, STALE_AFTER_SECONDS
from .entity import UapEntity, UapStalenessEntity
from .models import ThreatLevel, region_threat


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UkraineAlarmProConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        RegionAlertBinarySensor(coordinator, entry.entry_id, rid, info)
        for rid, info in entry.data[CONF_REGIONS].items()
    ]
    entities.append(DataStaleBinarySensor(coordinator, entry.entry_id))
    async_add_entities(entities)


class RegionAlertBinarySensor(UapEntity, BinarySensorEntity):
    """On when the region, an ancestor or a descendant has any active alert."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_translation_key = "alert"

    def __init__(self, coordinator, entry_id, region_id, info) -> None:
        super().__init__(coordinator, entry_id)
        self._region_id = region_id
        self._ancestors = info["ancestors"]
        self._descendants = info.get("descendants", [])
        # The region name comes from the feed; only the suffix is translated.
        self._attr_translation_placeholders = {"region": info["name"]}
        self._attr_unique_id = f"{entry_id}_{region_id}_alert"
        self.entity_id = f"binary_sensor.uap_{region_id}_alert"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return (
            region_threat(
                self.coordinator.data,
                self._region_id,
                self._ancestors,
                self._descendants,
            )
            is not ThreatLevel.NONE
        )


class DataStaleBinarySensor(UapStalenessEntity, BinarySensorEntity):
    """On when no snapshot arrived recently — the alert state is not trustworthy."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "data_stale"

    def __init__(self, coordinator, entry_id) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_data_stale"
        self.entity_id = "binary_sensor.uap_data_stale"

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_stale

    @property
    def extra_state_attributes(self):
        # Nothing here may move on its own: Home Assistant writes a recorder row
        # whenever the attributes differ, so a push clock or a seconds-since
        # counter here would cost a row per feed update even though the verdict
        # below is unchanged. The clock is its own entity, sensor.uap_last_update.
        return {
            "stale_after_seconds": STALE_AFTER_SECONDS,
            "transport": self.coordinator.supervisor.mode,
        }
