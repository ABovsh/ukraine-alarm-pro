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

# Staleness is a function of wall-clock time, not of incoming data, so the
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


class UapDiagnosticEntity(UapEntity):
    """Diagnostic entity: must report even before the first snapshot."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        return True


class UapStalenessEntity(UapDiagnosticEntity):
    """Diagnostic entity whose value ages on its own."""

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_interval(self.hass, self._async_tick, STALENESS_TICK)
        )

    @callback
    def _async_tick(self, _now) -> None:
        self.async_write_ha_state()
