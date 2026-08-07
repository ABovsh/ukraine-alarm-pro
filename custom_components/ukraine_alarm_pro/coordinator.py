"""Push-based coordinator fed by the transport supervisor."""

from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN, STALE_AFTER_SECONDS
from .models import Snapshot

_LOGGER = logging.getLogger(__name__)


class AlarmCoordinator(DataUpdateCoordinator[Snapshot]):
    """Holds the latest snapshot; updates are pushed, never polled."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, supervisor
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=None,
        )
        self.supervisor = supervisor
        self.last_push: datetime | None = None

    async def _async_update_data(self) -> Snapshot:
        """Serve the pushed snapshot back.

        Data arrives over the transport, never by polling, but HA can still
        route a manual `homeassistant.update_entity` here; without this the
        base class raises NotImplementedError and marks the update failed.
        """
        if self.data is None:
            raise UpdateFailed("no alert snapshot received yet")
        return self.data

    def handle_snapshot(self, snap: Snapshot) -> None:
        # The feed republishes the same alert map every few seconds. Only the
        # liveness clock moves then — pushing the identical snapshot at the
        # entities wrote a recorder row per repeat (65k rows/day, measured
        # 2026-08-07) without carrying any new information. Staleness has its
        # own tick in entity.py, so it keeps working without these writes.
        self.last_push = dt_util.utcnow()
        if self.data is not None and snap.active == self.data.active:
            return
        self.async_set_updated_data(snap)

    def handle_mode_change(self, mode: str) -> None:
        """Refresh entities immediately so the transport sensor never lags."""
        self.async_update_listeners()

    @property
    def seconds_since_push(self) -> float | None:
        """Age of the newest snapshot, or None if nothing arrived yet."""
        if self.last_push is None:
            return None
        return (dt_util.utcnow() - self.last_push).total_seconds()

    @property
    def is_stale(self) -> bool:
        """True when the feed went quiet — displayed state can't be trusted."""
        age = self.seconds_since_push
        return age is None or age > STALE_AFTER_SECONDS
