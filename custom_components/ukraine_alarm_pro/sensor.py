"""Sensors: per-region threat level + hub diagnostics."""

from __future__ import annotations

from typing import ClassVar

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import UkraineAlarmProConfigEntry
from .const import CONF_REGIONS
from .entity import UapDiagnosticEntity, UapEntity, UapStalenessEntity
from .models import ThreatLevel, region_alerts, region_threat, threat_types

# Attributes land in the recorder on every state write, so the per-region
# breakdown is capped; the full picture stays available in diagnostics.
MAX_LISTED_ALERTS = 25


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UkraineAlarmProConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []
    for rid, info in entry.data[CONF_REGIONS].items():
        entities.append(RegionThreatSensor(coordinator, entry.entry_id, rid, info))
        entities.append(AlertStartedSensor(coordinator, entry.entry_id, rid, info))
    entities.append(TransportSensor(coordinator, entry.entry_id))
    entities.append(ActiveRegionsSensor(coordinator, entry.entry_id))
    entities.append(LastUpdateSensor(coordinator, entry.entry_id))
    async_add_entities(entities)


class RegionSensor(UapEntity, SensorEntity):
    """Sensor bound to one configured region."""

    def __init__(self, coordinator, entry_id, region_id, info) -> None:
        super().__init__(coordinator, entry_id)
        self._region_id = region_id
        self._ancestors = info["ancestors"]
        self._descendants = info.get("descendants", [])
        # The region name comes from the feed; only the suffix is translated.
        self._region_name = info["name"]
        self._attr_translation_placeholders = {"region": info["name"]}

    def _found(self):
        if self.coordinator.data is None:
            return None
        return region_alerts(
            self.coordinator.data,
            self._region_id,
            self._ancestors,
            self._descendants,
        )


class RegionThreatSensor(RegionSensor):
    """Highest active threat in a region (any administrative level)."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = [level.value for level in ThreatLevel]
    _attr_translation_key = "threat"

    def __init__(self, coordinator, entry_id, region_id, info) -> None:
        super().__init__(coordinator, entry_id, region_id, info)
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
        found = self._found()
        if found is None:
            return {}
        names = self.coordinator.data.names
        return {
            # An oblast can have a hundred subdivisions in alert at once; the
            # full list would be written to the recorder on every push during
            # exactly the events this integration exists for. Newest first, so
            # the cap drops the oldest declarations rather than the newest.
            "active_alerts": [
                {
                    "region_id": alert.region_id,
                    "region_name": names.get(alert.region_id, ""),
                    "type": alert.type,
                    "since": alert.last_update,
                }
                for alert in found[:MAX_LISTED_ALERTS]
            ],
            "active_alert_count": len(found),
            "active_threat_types": ",".join(threat_types(found)),
            "region_id": self._region_id,
            # Constant, so it costs bytes on a recorder row but never a row of
            # its own — and it spares templates from parsing the friendly name.
            "region_name": self._region_name,
        }


class AlertStartedSensor(RegionSensor):
    """When the oldest alert now affecting the region was declared.

    The feed stamps every alert with its declaration time, so this survives a
    restart and is right from the first state — unlike a duration counted from
    when Home Assistant happened to notice.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "alert_started"

    def __init__(self, coordinator, entry_id, region_id, info) -> None:
        super().__init__(coordinator, entry_id, region_id, info)
        self._attr_unique_id = f"{entry_id}_{region_id}_started"
        self.entity_id = f"sensor.uap_{region_id}_alert_started"

    @property
    def native_value(self):
        found = self._found()
        if not found:
            return None
        # Parsed, not compared as text: the feed mixes whole-second and
        # microsecond stamps, and an unparsable one must not become "now".
        stamps = [
            parsed
            for alert in found
            if (parsed := dt_util.parse_datetime(alert.last_update)) is not None
        ]
        return min(stamps, default=None)


class TransportSensor(UapDiagnosticEntity, SensorEntity):
    """Which transport is feeding data: websocket or polling."""

    _attr_translation_key = "transport"

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
    _attr_translation_key = "active_regions"

    def __init__(self, coordinator, entry_id) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_active_regions"
        self.entity_id = "sensor.uap_active_regions"

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.active_region_count



class LastUpdateSensor(UapStalenessEntity, SensorEntity):
    """Timestamp of the last received snapshot — staleness indicator."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_update"

    def __init__(self, coordinator, entry_id) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_last_update"
        self.entity_id = "sensor.uap_last_update"

    @callback
    def _publish_key(self):
        # This sensor's state *is* the push clock, so it cannot sit on the
        # verdict alone: the feed goes hours without an alert-map change and
        # the state froze at the last one, showing a healthy feed as long dead.
        # Truncating to the minute caps it at ~1.4k rows/day instead of the
        # ~34k of publishing every push; the frontend renders a live
        # "x minutes ago" from the static state in between.
        push = self.coordinator.last_push
        return (
            self.coordinator.is_stale,
            push and push.replace(second=0, microsecond=0),
        )

    @property
    def native_value(self):
        return self.coordinator.last_push
