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

from . import UkraineAlarmProConfigEntry
from .const import CONF_REGIONS
from .entity import UapDiagnosticEntity, UapEntity, UapStalenessEntity
from .models import AIR_LEVEL_OPTIONS, RegionView, ThreatLevel

# Keep live lists bounded; recorder separately omits selected large attributes.
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
        entities.append(AirAlertLevelSensor(coordinator, entry.entry_id, rid, info))
        for seconds, suffix in ((86400, "24h"), (604800, "7d")):
            entities.append(
                AlertPercentageSensor(
                    coordinator, entry.entry_id, rid, info, seconds, suffix
                )
            )
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

    def _view(self) -> RegionView | None:
        return self.coordinator.region_view(
            self._region_id, self._ancestors, self._descendants
        )


class RegionThreatSensor(RegionSensor):
    """Highest active threat in a region (any administrative level)."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = [level.value for level in ThreatLevel]
    _attr_translation_key = "threat"
    _unrecorded_attributes = frozenset(
        {"active_alerts", "affected_regions", "coverage_by_type"}
    )

    def __init__(self, coordinator, entry_id, region_id, info) -> None:
        super().__init__(coordinator, entry_id, region_id, info)
        self._attr_unique_id = f"{entry_id}_{region_id}_threat"
        self.entity_id = f"sensor.uap_{region_id}_threat"

    @property
    def native_value(self) -> str | None:
        view = self._view()
        return None if view is None else view.threat.value

    @property
    def extra_state_attributes(self):
        view = self._view()
        if view is None:
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
                for alert in view.alerts[:MAX_LISTED_ALERTS]
            ],
            "active_alert_count": len(view.alerts),
            "active_threat_types": ",".join(view.threat_types),
            "region_id": self._region_id,
            # Constant, so it costs bytes on a recorder row but never a row of
            # its own — and it spares templates from parsing the friendly name.
            "region_name": self._region_name,
            # Whole/partial explains the state above; it never switches it off.
            # affected_regions counts declaring regions, not every hromada.
            "coverage": view.coverage,
            "coverage_by_type": view.coverage_by_type,
            "affected_regions": [dict(item) for item in view.affected_regions],
            "affected_region_count": view.affected_region_count,
        }


class AirAlertLevelSensor(RegionSensor):
    """Air-alert colour and reasons, only changing with local threat information.

    No state_class, timer, force_update or receipt timestamps: HA suppresses
    identical state/attributes even when another region updates the coordinator.
    Full level timestamps and untruncated reasons remain in diagnostics/storage.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = list(AIR_LEVEL_OPTIONS)
    _attr_translation_key = "air_alert_level"

    def __init__(self, coordinator, entry_id, region_id, info) -> None:
        super().__init__(coordinator, entry_id, region_id, info)
        self._attr_unique_id = f"{entry_id}_{region_id}_level"
        self.entity_id = f"sensor.uap_{region_id}_air_alert_level"

    @property
    def native_value(self) -> str | None:
        view = self._view()
        if view is None:
            return None
        return view.air_levels[0] if view.air_levels else "none"

    @property
    def extra_state_attributes(self):
        view = self._view()
        if view is None:
            return {}
        reasons = view.air_reasons
        return {
            "region_id": self._region_id,
            "active_levels": list(view.air_levels),
            "reasons": [reason[:256] for reason in reasons[:MAX_LISTED_ALERTS]],
            "reason_count": len(reasons),
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
        view = self._view()
        # An unparsable stamp is skipped, never turned into "now".
        return None if view is None else view.started

    @property
    def extra_state_attributes(self):
        return {"region_id": self._region_id}


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
        push = self.coordinator.last_push
        return push.replace(second=0, microsecond=0) if push is not None else None


class AlertPercentageSensor(RegionSensor):
    """Time under any alert, from one shared in-memory rolling calculation."""

    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, entry_id, region_id, info, seconds, suffix):
        super().__init__(coordinator, entry_id, region_id, info)
        self._seconds = seconds
        self._attr_unique_id = f"{entry_id}_{region_id}_percentage_{suffix}"
        self._attr_translation_key = f"alert_percentage_{suffix}"
        self.entity_id = f"sensor.uap_{region_id}_alert_percentage_{suffix}"
        self._published = None

    @property
    def available(self):
        return True

    @property
    def native_value(self):
        return self._result().get("percentage")

    def _result(self):
        return self.coordinator.percentages.get((self._region_id, self._seconds), {})

    @property
    def extra_state_attributes(self):
        result = self._result()
        return {
            "region_id": self._region_id,
            "window_seconds": self._seconds,
            "threat_scope": "any_alert",
            "coverage_complete": result.get("coverage_complete", False),
            "quality": result.get("quality", "incomplete"),
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._published = (self.native_value, self.extra_state_attributes)
        self.async_on_remove(
            self.coordinator.add_percentage_listener(self._percentage_changed)
        )

    @callback
    def _handle_coordinator_update(self):
        # Alert callbacks precede journal transitions; the dedicated listener
        # runs after that transaction and publishes only meaningful changes.
        return

    @callback
    def _percentage_changed(self):
        key = (self.native_value, self.extra_state_attributes)
        if key == self._published:
            return
        self._published = key
        self.async_write_ha_state()
