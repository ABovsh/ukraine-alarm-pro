"""Base entity."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AlarmCoordinator

# Staleness advances with elapsed time even without incoming data, so the
# entities that expose it need their own tick.
STALENESS_TICK = timedelta(seconds=60)


class UapEntity(CoordinatorEntity[AlarmCoordinator]):
    """Entity bound to the hub device; never unavailable on transport loss."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AlarmCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Ukraine Alarm Pro",
            manufacturer="ukrainealarm.com (anonymous WS)",
        )

    @property
    def available(self) -> bool:
        # Keep last known state on transport loss; staleness is a diagnostic.
        return self.coordinator.data is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        rid = getattr(self, "_region_id", None)
        changed = self.coordinator.changed_regions
        if rid is not None and changed is not None and rid not in changed:
            return
        super()._handle_coordinator_update()


class UapDiagnosticEntity(UapEntity):
    """Diagnostic entity: must report even before the first snapshot."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        return True


class UapStalenessEntity(UapDiagnosticEntity):
    """Diagnostic entity whose value ages on its own."""

    def __init__(self, coordinator: AlarmCoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id)
        self._published = self._publish_key()

    @callback
    def _publish_key(self) -> object:
        """State/attribute key worth publishing; HA still compares actual states."""
        return self.coordinator.is_stale

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.add_health_listener(self._handle_coordinator_update)
        )
        self.async_on_remove(
            async_track_time_interval(self.hass, self._async_tick, STALENESS_TICK)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        # A push writes state through this path, so the tick's baseline has to
        # follow it — otherwise a recovery leaves the tick comparing against a
        # verdict two transitions old and it never publishes going stale again.
        key = self._publish_key()
        if key == self._published:
            return
        self._published = key
        super()._handle_coordinator_update()

    @callback
    def _async_tick(self, _now) -> None:
        key = self._publish_key()
        if key == self._published:
            return
        self._published = key
        self.async_write_ha_state()
