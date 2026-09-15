"""Push-based coordinator fed by the transport supervisor."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import backfill
from .const import CONF_REGIONS, DOMAIN, RESTORE_MAX_AGE_SECONDS, STALE_AFTER_SECONDS
from .events import (
    ORIGIN_BOOTSTRAP,
    ORIGIN_LIVE,
    ORIGIN_RECOVERY,
    AlertEventHub,
    RegionState,
)
from .history import HISTORY_STORAGE_VERSION, AlertHistory
from .models import Alert, RegionView, Snapshot, parse_alert_levels, region_view

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
        self._views: dict[str, RegionView] = {}
        self._views_of: Snapshot | None = None
        self.events = AlertEventHub()
        self.history = AlertHistory(
            Store(
                hass,
                HISTORY_STORAGE_VERSION,
                f"{DOMAIN}.history.{entry.entry_id}",
            )
        )

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

        A map that no transport has confirmed is never written back. It can only
        be one we restored, and re-saving it would renew its `saved_at`: an
        uplink that stays down would keep re-stamping the same pre-outage map
        every interval, and `RESTORE_MAX_AGE_SECONDS` would never expire it.
        """
        snap = self.data
        if snap is None or self.last_push is None:
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
        was_stale = self.is_stale
        self.last_push = dt_util.utcnow()
        changed = self.data is None or snap.active != self.data.active
        if changed:
            self.async_set_updated_data(snap)
        elif was_stale:
            # Regaining freshness is news even when the map is unchanged: the
            # health entities must not wait for their minute tick. HA drops
            # the identical region states, so this costs no region rows.
            self.async_update_listeners()
        self._publish_events(was_stale=was_stale, changed=changed)

    @callback
    def _publish_events(self, *, was_stale: bool, changed: bool) -> None:
        """Turn the accepted snapshot into region events, after the states.

        The first snapshot of a run and the first after a gap are resyncs, not
        live transitions: what happened in between was not observed.
        """
        if not self.events.bootstrapped:
            origin = ORIGIN_BOOTSTRAP
        elif was_stale or self.events.stale_announced:
            origin = ORIGIN_RECOVERY
        elif changed:
            origin = ORIGIN_LIVE
        else:
            return
        states = {}
        for rid, info in self._regions.items():
            view = self.region_view(rid, info["ancestors"], info.get("descendants", []))
            if view is not None:
                states[rid] = (info["name"], RegionState.from_view(view))
        self.events.accept(
            states, origin=origin, observed_at=self.last_push.isoformat()
        )

    @callback
    def async_check_stale(self, _now: datetime | None = None) -> None:
        """Announce once that the data went stale; the alert state is kept."""
        if self.is_stale:
            self.events.announce_stale(
                {rid: info["name"] for rid, info in self._regions.items()},
                observed_at=dt_util.utcnow().isoformat(),
            )

    async def async_backfill_history(self, _now: datetime | None = None) -> None:
        """Merge the official alert history into the journal, best effort."""
        regions = self._regions
        if not regions:
            return
        now = dt_util.utcnow()
        start = self.history.backfill_start(now)
        try:
            records = await backfill._fetch(
                async_get_clientsession(self.hass),
                backfill.root_regions(regions),
                start,
                now,
            )
        # A missing history must never break the entry or the live alerts.
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Official alert history unavailable: %s", err)
            return
        added = sum(
            self.history.merge_official(
                rid, backfill.official_intervals(records, rid, info), window_start=start
            )
            for rid, info in regions.items()
        )
        self.history.mark_synced(now)
        _LOGGER.debug("Merged %d alert episodes from the official history", added)

    async def async_flush_history(self, _now: datetime | None = None) -> None:
        """Persist the journal; a failed write stays pending for the next try."""
        try:
            await self.history.async_flush()
        # Disk trouble must not break the periodic timer or unload.
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not save the alert history: %s", err)

    @property
    def _regions(self) -> dict[str, dict[str, Any]]:
        return self.config_entry.data.get(CONF_REGIONS, {})

    def region_view(
        self, region_id: str, ancestors, descendants
    ) -> RegionView | None:
        """The region's aggregated alerts, computed once per accepted map.

        Six entities per region read it on every update; aggregating in each
        getter repeated the same work six times. Region trees only change
        through a reload, which builds a new coordinator.
        """
        snap = self.data
        if snap is None:
            return None
        if snap is not self._views_of:
            self._views = {}
            self._views_of = snap
        view = self._views.get(region_id)
        if view is None:
            view = self._views[region_id] = region_view(
                snap, region_id, ancestors, descendants
            )
        return view

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
                levels=parse_alert_levels(a.get("levels"), stored=True),
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
