"""Binary sensors: per-region any-alert flag."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_REGIONS, DOMAIN
from .coordinator import AlarmCoordinator
from .entity import UapEntity
from .models import ThreatLevel, region_threat


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AlarmCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        RegionAlertBinarySensor(coordinator, entry.entry_id, rid, info)
        for rid, info in entry.data[CONF_REGIONS].items()
    )


class RegionAlertBinarySensor(UapEntity, BinarySensorEntity):
    """On when the region (or an ancestor) has any active alert."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(self, coordinator, entry_id, region_id, info) -> None:
        super().__init__(coordinator, entry_id)
        self._region_id = region_id
        self._ancestors = info["ancestors"]
        self._attr_name = f"{info['name']} alert"
        self._attr_unique_id = f"{entry_id}_{region_id}_alert"
        self.entity_id = f"binary_sensor.uap_{region_id}_alert"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return (
            region_threat(self.coordinator.data, self._region_id, self._ancestors)
            is not ThreatLevel.NONE
        )
