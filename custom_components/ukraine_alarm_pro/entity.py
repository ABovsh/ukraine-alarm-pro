"""Base entity."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AlarmCoordinator


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
