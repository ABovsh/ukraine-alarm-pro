"""Push-based coordinator fed by the transport supervisor."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import backfill
from .const import (
    CONF_REGIONS,
    DOMAIN,
    ISSUE_FEED_UNAVAILABLE,
    RESTORE_MAX_AGE_SECONDS,
    SAVE_DELAY_SECONDS,
    STALE_AFTER_SECONDS,
)
from .events import (
    ORIGIN_BOOTSTRAP,
    ORIGIN_LIVE,
    ORIGIN_RECOVERY,
    AlertEventHub,
    RegionState,
)
from .history import HISTORY_STORAGE_VERSION, AlertHistory, history_storage_key
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
        self.started_at = dt_util.utcnow()
        self._started_monotonic = time.monotonic()
        self._last_push_monotonic: float | None = None
        self._store = store
        self._saved_active: tuple | None = None
        self._saved_confirmed: datetime | None = None
        self.last_saved_at: datetime | None = None
        self._save_lock = asyncio.Lock()
        self._save_failed = False
        self._history_save_failed = False
        self.changed_regions: set[str] | None = None
        self._dependents: dict[str, set[str]] = {}
        for rid, info in self._regions.items():
            for source in (
                rid,
                *info.get("ancestors", []),
                *info.get("descendants", []),
            ):
                self._dependents.setdefault(source, set()).add(rid)
        self.percentages: dict[tuple[str, int], dict[str, Any]] = {}
        self._percentage_listeners: list = []
        self._health_listeners: list = []
        self._backfill_lock = asyncio.Lock()
        self._views: dict[str, RegionView] = {}
        self._views_of: Snapshot | None = None
        self.events = AlertEventHub()
        self.history = AlertHistory(
            Store(
                hass,
                HISTORY_STORAGE_VERSION,
                history_storage_key(entry.entry_id),
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
        try:
            stored = await self._store.async_load()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Alert snapshot unreadable — starting without cache: %s", err
            )
            return
        if not isinstance(stored, dict):
            return
        written = dt_util.parse_datetime(str(stored.get("saved_at", "")))
        if written is not None and written.tzinfo is not None:
            self.last_saved_at = written
        saved_at = dt_util.parse_datetime(
            str(stored.get("confirmed_at", stored.get("saved_at", "")))
        )
        # A stamp without an offset was not written by us: ignore it rather
        # than fail setup comparing it with an aware clock.
        if saved_at is None or saved_at.tzinfo is None:
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
    def _store_data(
        self, snap: Snapshot | None = None, confirmed: datetime | None = None
    ) -> dict[str, Any]:
        snap = snap or self.data
        return {
            "saved_at": dt_util.utcnow().isoformat(),
            "confirmed_at": (confirmed or self.last_push).isoformat(),
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
        """Persist changed content or a new five-minute confirmation checkpoint.

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
        async with self._save_lock:
            snap = self.data
            confirmed = self.last_push
            if snap is None or confirmed is None:
                return
            active = (snap.signature, snap.names)
            if (
                active == self._saved_active
                and self._saved_confirmed is not None
                and 0
                <= (confirmed - self._saved_confirmed).total_seconds()
                < SAVE_DELAY_SECONDS
            ):
                return
            try:
                await self._store.async_save(self._store_data(snap, confirmed))
            except Exception as err:  # noqa: BLE001
                log = _LOGGER.debug if self._save_failed else _LOGGER.warning
                log("Could not save alert snapshot; will retry: %s", err)
                self._save_failed = True
                return
            self._saved_active = active
            self._saved_confirmed = confirmed
            self.last_saved_at = dt_util.utcnow()
            self._save_failed = False

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
        # Unchanged maps move liveness and journal confirmation only. HA
        # compares state AND attributes before emitting state_changed; skipping
        # callbacks also avoids aggregation/serialization work before that check.
        was_stale = self.is_stale
        if was_stale:
            self.history.mark_gap(self._regions)
        now = dt_util.utcnow()
        monotonic = time.monotonic()
        clock_jump = (
            self.last_push is not None
            and self._last_push_monotonic is not None
            and abs(
                (now - self.last_push).total_seconds()
                - (monotonic - self._last_push_monotonic)
            )
            > 60
        )
        if clock_jump:
            self.history.mark_gap(self._regions)
        self.last_push = now
        self._last_push_monotonic = monotonic
        old = self.data
        sources = set(snap.signature) | set(old.signature if old else {})
        changed_sources = {
            rid
            for rid in sources
            if old is None or snap.signature.get(rid) != old.signature.get(rid)
        }
        names = set(snap.names) | set(old.names if old else {})
        changed_sources.update(
            rid
            for rid in names
            if old is None or snap.names.get(rid) != old.names.get(rid)
        )
        affected = (
            set(self._regions)
            if old is None or was_stale
            else set().union(
                *(self._dependents.get(rid, set()) for rid in changed_sources)
            )
        )
        changed = old is None or bool(changed_sources)
        self.history.confirm(self._regions, self.last_push)
        for rid in affected:
            self._views.pop(rid, None)
        self._views_of = snap
        self.changed_regions = None if was_stale else affected
        if changed:
            self.async_set_updated_data(snap)
        else:
            # Keep precise service fields for diagnostics/storage, without
            # invalidating unaffected RegionViews or notifying entities.
            self.data = snap
        if was_stale and not changed:
            # Regaining freshness is news even when the map is unchanged: the
            # health entities must not wait for their minute tick. HA drops
            # the identical region states, so this costs no region rows.
            self.async_update_listeners()
        self._publish_events(was_stale=was_stale, changed=changed)
        if clock_jump or affected:
            self.async_update_percentages(region_ids=None if clock_jump else affected)
        self.changed_regions = None
        if was_stale:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_FEED_UNAVAILABLE)

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
            if (
                origin == ORIGIN_LIVE
                and self.changed_regions is not None
                and rid not in self.changed_regions
            ):
                continue
            view = self.region_view(rid, info["ancestors"], info.get("descendants", []))
            if view is not None:
                states[rid] = (info["name"], RegionState.from_view(view))
        self.events.accept(
            states, origin=origin, observed_at=self.last_push.isoformat()
        )

    @callback
    def async_check_stale(self, _now: datetime | None = None) -> None:
        """Announce once that the data went stale; the alert state is kept."""
        before = self.history.version
        if self.is_stale:
            self.history.mark_gap(self._regions)
            self.events.announce_stale(
                {rid: info["name"] for rid, info in self._regions.items()},
                observed_at=dt_util.utcnow().isoformat(),
            )
        self._async_report_feed_health()
        if self.history.version != before:
            self.async_update_percentages()

    @callback
    def _async_report_feed_health(self) -> None:
        """Raise a repair issue only when no source delivers alert data.

        Polling after a WebSocket failure still delivers alerts, so it is no
        problem for the user. Before the first snapshot, the start-up grace
        period counts as the window instead of a push that never happened.
        """
        reference = (
            self._last_push_monotonic
            if self._last_push_monotonic is not None
            else self._started_monotonic
        )
        age = time.monotonic() - reference
        if age > STALE_AFTER_SECONDS:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                ISSUE_FEED_UNAVAILABLE,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_FEED_UNAVAILABLE,
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_FEED_UNAVAILABLE)

    async def async_backfill_history(self, _now: datetime | None = None) -> None:
        """One root and seven UTC days at a time; resume failed chunks only."""
        if self._backfill_lock.locked():
            return
        async with self._backfill_lock:
            await self._async_backfill_chunks()

    async def _async_backfill_chunks(self) -> None:
        regions = self._regions
        if not regions:
            return
        now = dt_util.utcnow()
        for root in backfill.root_regions(regions):
            windows = {
                rid: window
                for rid, info in regions.items()
                if (info.get("ancestors") or [rid])[-1] == root
                and (window := self.history.backfill_window(rid, now)) is not None
            }
            if not windows:
                continue
            start = min(lo for lo, _hi in windows.values())
            target = max(hi for _lo, hi in windows.values())
            self.history.begin_backfill(windows, target)
            while start < target:
                end = min(start + timedelta(days=7), target)
                try:
                    records = await backfill._fetch(
                        async_get_clientsession(self.hass), [root], start, end
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug(
                        "Official history root %s will resume at %s: %s",
                        root,
                        start.isoformat(),
                        err,
                    )
                    break
                for rid in windows:
                    self.history.merge_official(
                        rid,
                        backfill.official_intervals(records, rid, regions[rid]),
                        window_start=start,
                    )
                self.history.advance_cursor(windows, end)
                # Persist progress per chunk. Disk errors leave it dirty, while
                # cancellation/restart can resume the last successful checkpoint.
                await self.async_flush_history()
                start = end
                await asyncio.sleep(0)
            else:
                self.history.finish_backfill(windows)
                await self.async_flush_history()
        self.async_update_percentages()

    async def async_flush_history(self, _now: datetime | None = None) -> None:
        """Persist the journal; a failed write stays pending for the next try."""
        try:
            await self.history.async_flush()
        # Disk trouble must not break the periodic timer or unload.
        except Exception as err:  # noqa: BLE001
            log = _LOGGER.debug if self._history_save_failed else _LOGGER.warning
            log("Could not save the alert history; will retry: %s", err)
            self._history_save_failed = True
        else:
            self._history_save_failed = False

    @property
    def _regions(self) -> dict[str, dict[str, Any]]:
        return self.config_entry.data.get(CONF_REGIONS, {})

    def region_view(self, region_id: str, ancestors, descendants) -> RegionView | None:
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
        if self._last_push_monotonic is None:
            return None
        return max(0, time.monotonic() - self._last_push_monotonic)

    @property
    def is_stale(self) -> bool:
        """True when the feed went quiet — displayed state can't be trusted."""
        age = self.seconds_since_push
        return age is None or age > STALE_AFTER_SECONDS

    def add_percentage_listener(self, listener):
        self._percentage_listeners.append(listener)
        return lambda: self._percentage_listeners.remove(listener)

    def add_health_listener(self, listener):
        self._health_listeners.append(listener)
        return lambda: self._health_listeners.remove(listener)

    @callback
    def async_update_listeners(self) -> None:
        """Publish freshness first, so automation conditions see this update."""
        for listener in tuple(self._health_listeners):
            listener()
        super().async_update_listeners()

    @callback
    def async_update_percentages(
        self, _now: datetime | None = None, *, region_ids=None
    ) -> None:
        now = dt_util.utcnow()
        for rid in self._regions if region_ids is None else region_ids:
            for seconds in (86400, 604800):
                self.percentages[(rid, seconds)] = self.history.rolling(
                    rid, seconds, now=now
                )
                self.percentages[(rid, seconds)]["calculated_at"] = now.isoformat()
        for listener in tuple(self._percentage_listeners):
            listener()


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
