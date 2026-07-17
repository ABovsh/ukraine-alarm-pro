"""Sensors: per-region threat level + hub diagnostics."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_REGIONS, DOMAIN
from .coordinator import AlarmCoordinator
from .entity import UapEntity
from .models import ThreatLevel, region_threat


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AlarmCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        RegionThreatSensor(coordinator, entry.entry_id, rid, info)
        for rid, info in entry.data[CONF_REGIONS].items()
    ]
    entities.append(TransportSensor(coordinator, entry.entry_id))
    entities.append(ActiveRegionsSensor(coordinator, entry.entry_id))
    entities.append(LastUpdateSensor(coordinator, entry.entry_id))
    async_add_entities(entities)


class RegionThreatSensor(UapEntity, SensorEntity):
    """Highest active threat in a region (inheriting from ancestors)."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [level.value for level in ThreatLevel]
    _attr_translation_key = "threat"

    def __init__(self, coordinator, entry_id, region_id, info) -> None:
        super().__init__(coordinator, entry_id)
        self._region_id = region_id
        self._ancestors = info["ancestors"]
        self._attr_name = f"{info['name']} threat"
        self._attr_unique_id = f"{entry_id}_{region_id}_threat"
        self.entity_id = f"sensor.uap_{region_id}_threat"

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return region_threat(
            self.coordinator.data, self._region_id, self._ancestors
        ).value

    @property
    def extra_state_attributes(self):
        if self.coordinator.data is None:
            return {}
        alerts = []
        for rid in [self._region_id, *self._ancestors]:
            alerts.extend(
                {"region_id": rid, "type": a.type, "since": a.last_update}
                for a in self.coordinator.data.regions.get(rid, [])
            )
        return {"active_alerts": alerts, "region_id": self._region_id}


class TransportSensor(UapEntity, SensorEntity):
    """Which transport is feeding data: websocket or polling."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Transport"

    def __init__(self, coordinator, entry_id) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_transport"
        self.entity_id = "sensor.uap_transport"

    @property
    def native_value(self) -> str:
        return self.coordinator.supervisor.mode


class ActiveRegionsSensor(UapEntity, SensorEntity):
    """Country-wide count of regions with any active alert."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Active regions"

    def __init__(self, coordinator, entry_id) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_active_regions"
        self.entity_id = "sensor.uap_active_regions"

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.active_region_count


class LastUpdateSensor(UapEntity, SensorEntity):
    """Timestamp of the last received snapshot — staleness indicator."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_name = "Last update"

    def __init__(self, coordinator, entry_id) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_last_update"
        self.entity_id = "sensor.uap_last_update"

    @property
    def native_value(self):
        return self.coordinator.last_push
