"""Push-based coordinator fed by the transport supervisor."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .models import Snapshot

_LOGGER = logging.getLogger(__name__)


class AlarmCoordinator(DataUpdateCoordinator[Snapshot]):
    """Holds the latest snapshot; updates are pushed, never polled."""

    def __init__(self, hass: HomeAssistant, supervisor) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.supervisor = supervisor
        self.last_push = None

    def handle_snapshot(self, snap: Snapshot) -> None:
        self.last_push = dt_util.utcnow()
        self.async_set_updated_data(snap)

    def handle_mode_change(self, mode: str) -> None:
        """Refresh entities immediately so the transport sensor never lags."""
        self.async_update_listeners()
