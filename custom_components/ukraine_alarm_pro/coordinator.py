"""Push-based coordinator fed by the transport supervisor."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN, RESTORE_MAX_AGE_SECONDS, STALE_AFTER_SECONDS
from .models import Alert, Snapshot

_LOGGER = logging.getLogger(__name__)


class AlarmCoordinator(DataUpdateCoordinator[Snapshot]):
    """Holds the latest snapshot; updates are pushed, never polled."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        supervisor,
        store: Store,
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
        self._store = store
        self._saved_active: dict[str, frozenset] | None = None

    async def async_restore(self) -> None:
        """Publish the alert map the last run ended with, if it is recent.

        `last_push` deliberately stays unset: the map was restored, not
        received, so `binary_sensor.uap_data_stale` reports it as untrustworthy
        until a transport actually delivers. Entities still come up with the
        last known state instead of `unavailable`, which is what an automation
        reading them during a post-blackout restart needs.
        """
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        saved_at = dt_util.parse_datetime(str(stored.get("saved_at", "")))
        if saved_at is None:
            return
        age = (dt_util.utcnow() - saved_at).total_seconds()
        if not 0 <= age <= RESTORE_MAX_AGE_SECONDS:
            _LOGGER.debug("Stored alert map is %.0fs old — starting blank", age)
            return
        snap = _snapshot_from_store(stored)
        if snap is None:
            return
        _LOGGER.debug("Restored the alert map saved %.0fs ago", age)
        self.async_set_updated_data(snap)

    @callback
    def _store_data(self) -> dict[str, Any]:
        snap = self.data
        return {
            "saved_at": dt_util.utcnow().isoformat(),
            "regions": {
                rid: [asdict(alert) for alert in alerts]
                for rid, alerts in snap.regions.items()
                if alerts
            }
            if snap is not None
            else {},
            "names": dict(snap.names) if snap is not None else {},
        }

    async def async_save_now(self, _now: datetime | None = None) -> None:
        """Persist the alert map if it changed since the last write.

        Driven by a fixed interval and by unload — deliberately NOT by the push
        path. `Store.async_delay_save` is a trailing debounce: every call moves
        the pending write further out, and the country-wide map changes every
        couple of minutes during a mass raid, so saving on change postponed the
        write indefinitely and nothing ever reached the disk — precisely during
        the event this exists for.
        """
        snap = self.data
        if snap is None:
            return
        active = snap.active
        if active == self._saved_active:
            return
        self._saved_active = active
        await self._store.async_save(self._store_data())

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


def _snapshot_from_store(stored: dict[str, Any]) -> Snapshot | None:
    """Rebuild a snapshot from disk, ignoring anything malformed."""
    raw = stored.get("regions")
    if not isinstance(raw, dict):
        return None
    regions: dict[str, list[Alert]] = {}
    for rid, alerts in raw.items():
        if not isinstance(alerts, list):
            continue
        regions[str(rid)] = [
            Alert(
                type=str(a.get("type", "")),
                last_update=str(a.get("last_update", "")),
                region_id=str(a.get("region_id", "")),
                region_type=str(a.get("region_type", "")),
            )
            for a in alerts
            if isinstance(a, dict)
        ]
    names = stored.get("names")
    return Snapshot(
        regions=regions,
        names={str(k): str(v) for k, v in names.items()}
        if isinstance(names, dict)
        else {},
    )
