"""Sensors: per-region threat level + hub diagnostics."""

from __future__ import annotations

from typing import ClassVar

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import UkraineAlarmProConfigEntry
from .const import CONF_REGIONS
from .entity import UapDiagnosticEntity, UapEntity, UapStalenessEntity
from .models import ThreatLevel, region_alerts, region_threat

# Attributes land in the recorder on every state write, so the per-region
# breakdown is capped; the full picture stays available in diagnostics.
MAX_LISTED_ALERTS = 25


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UkraineAlarmProConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        RegionThreatSensor(coordinator, entry.entry_id, rid, info)
        for rid, info in entry.data[CONF_REGIONS].items()
    ]
    entities.append(TransportSensor(coordinator, entry.entry_id))
    entities.append(ActiveRegionsSensor(coordinator, entry.entry_id))
    entities.append(LastUpdateSensor(coordinator, entry.entry_id))
    async_add_entities(entities)


class RegionThreatSensor(UapEntity, SensorEntity):
    """Highest active threat in a region (any administrative level)."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = [level.value for level in ThreatLevel]
    _attr_translation_key = "threat"

    def __init__(self, coordinator, entry_id, region_id, info) -> None:
        super().__init__(coordinator, entry_id)
        self._region_id = region_id
        self._ancestors = info["ancestors"]
        self._descendants = info.get("descendants", [])
        self._attr_name = f"{info['name']} threat"
        self._attr_unique_id = f"{entry_id}_{region_id}_threat"
        self.entity_id = f"sensor.uap_{region_id}_threat"

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return region_threat(
            self.coordinator.data,
            self._region_id,
            self._ancestors,
            self._descendants,
        ).value

    @property
    def extra_state_attributes(self):
        if self.coordinator.data is None:
            return {}
        found = region_alerts(
            self.coordinator.data,
            self._region_id,
            self._ancestors,
            self._descendants,
        )
        return {
            # An oblast can have a hundred subdivisions in alert at once; the
            # full list would be written to the recorder on every push during
            # exactly the events this integration exists for.
            "active_alerts": [
                {"region_id": rid, "type": alert.type, "since": alert.last_update}
                for rid, alert in found[:MAX_LISTED_ALERTS]
            ],
            "active_alert_count": len(found),
            "region_id": self._region_id,
        }


class TransportSensor(UapDiagnosticEntity, SensorEntity):
    """Which transport is feeding data: websocket or polling."""

    _attr_name = "Transport"

    def __init__(self, coordinator, entry_id) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_transport"
        self.entity_id = "sensor.uap_transport"

    @property
    def native_value(self) -> str:
        return self.coordinator.supervisor.mode


class ActiveRegionsSensor(UapDiagnosticEntity, SensorEntity):
    """Country-wide count of regions with any active alert."""

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

    @property
    def extra_state_attributes(self):
        if self.coordinator.data is None:
            return {}
        # Occupied regions carry permanent alerts (Luhansk oblast since 2022,
        # Crimea since 2022), so this count never returns to zero — listing the
        # ids makes that visible instead of looking like a stuck sensor.
        return {
            "region_ids": sorted(
                rid for rid, alerts in self.coordinator.data.regions.items() if alerts
            )
        }


class LastUpdateSensor(UapStalenessEntity, SensorEntity):
    """Timestamp of the last received snapshot — staleness indicator."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_name = "Last update"

    def __init__(self, coordinator, entry_id) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_last_update"
        self.entity_id = "sensor.uap_last_update"

    @property
    def native_value(self):
        return self.coordinator.last_push
