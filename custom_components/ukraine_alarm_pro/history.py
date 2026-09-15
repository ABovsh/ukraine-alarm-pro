"""Alert episode journal — observed periods of "any alert on" per region.

An episode is not a declaration: two overlapping alerts form one episode from
the first start to the last clear, which is why `alert_started` (the oldest
*still active* declaration) keeps its own meaning. Times are what the
integration observed; a gap is marked, never filled in.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

HISTORY_STORAGE_VERSION = 1
MAX_HISTORY_DAYS = 90
MAX_HISTORY_EPISODES = 1000
_AIR_RANK = {"none": 0, "unrecognized": 1, "yellow": 2, "red": 3}
_FIELDS = (
    "episode_id",
    "region_id",
    "observed_started_at",
    "declared_started_at",
    "observed_cleared_at",
    "active_types_seen",
    "maximum_air_level",
    "had_gap",
    "source_start_known",
    "start_origin",
)


def _parse(stamp: Any) -> datetime | None:
    return dt_util.parse_datetime(stamp) if isinstance(stamp, str) else None


def _valid(episode: Any) -> bool:
    return (
        isinstance(episode, dict)
        and all(key in episode for key in _FIELDS)
        and isinstance(episode["region_id"], str)
        and _parse(episode["observed_started_at"]) is not None
        and isinstance(episode["active_types_seen"], list)
    )


class AlertHistory:
    """Builds episodes from alert events and keeps them in a bounded store."""

    def __init__(
        self,
        store: Any,
        *,
        now: Callable[[], datetime] = dt_util.utcnow,
        max_days: int = MAX_HISTORY_DAYS,
        max_episodes: int = MAX_HISTORY_EPISODES,
    ) -> None:
        self._store = store
        self._now = now
        self._max_age = timedelta(days=max_days)
        self._max_episodes = max_episodes
        self._active: dict[str, dict[str, Any]] = {}
        self._completed: list[dict[str, Any]] = []
        self._created_at: str | None = None
        self._version = 0
        self._saved_version = 0

    async def async_load(self) -> None:
        """Read the journal; a damaged or unknown store starts a new one."""
        try:
            stored = await self._store.async_load()
        # A broken journal must never break the entry or the alert map.
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Alert history unreadable (%s) — starting a new one", err)
            stored = None
        if isinstance(stored, dict):
            active = stored.get("active")
            if isinstance(active, dict):
                self._active = {
                    rid: ep for rid, ep in active.items()
                    if _valid(ep) and ep["region_id"] == rid
                }
            episodes = stored.get("episodes")
            if isinstance(episodes, list):
                self._completed = [
                    ep for ep in episodes
                    if _valid(ep) and _parse(ep["observed_cleared_at"]) is not None
                ]
            if _parse(stored.get("created_at")) is not None:
                self._created_at = stored["created_at"]
        elif stored is not None:
            _LOGGER.warning("Alert history has an unknown format — starting a new one")
        if self._created_at is None:
            # History before this moment is unknown, not empty.
            self._created_at = self._now().isoformat()
            self._version += 1
        self._prune()

    def handle_event(self, event_type: str, payload: dict[str, Any]) -> None:
        region_id = payload["region_id"]
        current = payload["current"]
        at = payload["observed_at"]
        origin = payload["origin"]
        episode = self._active.get(region_id)
        if current["active"]:
            if episode is None:
                episode = self._active[region_id] = {
                    "episode_id": uuid.uuid4().hex[:12],
                    "region_id": region_id,
                    "observed_started_at": at,
                    "declared_started_at": current.get("declared_started_at"),
                    "observed_cleared_at": None,
                    "active_types_seen": [],
                    "maximum_air_level": "none",
                    # Only a live clear→active transition shows when it began.
                    "had_gap": event_type != "started",
                    "source_start_known": event_type == "started",
                    "start_origin": origin,
                }
            elif origin != "live" or event_type == "data_stale":
                episode["had_gap"] = True
            for threat in current["threat_types"]:
                if threat not in episode["active_types_seen"]:
                    episode["active_types_seen"].append(threat)
            level = current.get("air_level", "none")
            if _AIR_RANK.get(level, 0) > _AIR_RANK.get(episode["maximum_air_level"], 0):
                episode["maximum_air_level"] = level
        elif episode is not None:
            # After a gap the end was detected now; the exact moment is unknown.
            if origin != "live":
                episode["had_gap"] = True
            episode["observed_cleared_at"] = at
            self._completed.append(self._active.pop(region_id))
        else:
            return
        self._version += 1
        self._prune()

    async def async_flush(self, _now: datetime | None = None) -> None:
        """Write pending changes; marked saved only after the write succeeded.

        Called on a fixed interval and at unload, never as a trailing debounce
        that a steady stream of events could postpone forever.
        """
        if self._version == self._saved_version:
            return
        version = self._version
        await self._store.async_save(
            {
                "created_at": self._created_at,
                "active": self._active,
                "episodes": self._completed,
            }
        )
        self._saved_version = version

    def _prune(self) -> None:
        cutoff = self._now() - self._max_age
        kept = [
            ep for ep in self._completed
            if (_parse(ep["observed_cleared_at"]) or cutoff) >= cutoff
        ]
        kept.sort(key=lambda ep: ep["observed_started_at"])
        kept = kept[-self._max_episodes:]
        if len(kept) != len(self._completed):
            self._version += 1
        self._completed = kept

    def history(self, region_id: str, limit: int) -> list[dict[str, Any]]:
        """Newest first, the ongoing episode included."""
        episodes = [ep for ep in self._completed if ep["region_id"] == region_id]
        if region_id in self._active:
            episodes.append(self._active[region_id])
        episodes.sort(key=lambda ep: _parse(ep["observed_started_at"]), reverse=True)
        return [self._render(ep) for ep in episodes[:limit]]

    @staticmethod
    def _render(episode: dict[str, Any]) -> dict[str, Any]:
        started = _parse(episode["observed_started_at"])
        cleared = _parse(episode["observed_cleared_at"])
        return {
            **{key: episode[key] for key in _FIELDS},
            "active_types_seen": list(episode["active_types_seen"]),
            # Observed-to-observed; not an official duration.
            "observed_duration_seconds": (
                round((cleared - started).total_seconds()) if cleared else None
            ),
        }

    def summary(self, region_id: str, days: int) -> dict[str, Any]:
        """Episodes overlapping the last `days` local calendar days."""
        now = self._now()
        today = dt_util.as_local(now).date()
        # Per-day bounds from local midnights, so a DST day stays 23 or 25 h.
        bounds = [
            dt_util.start_of_local_day(today - timedelta(days=offset))
            for offset in range(days - 1, -1, -1)
        ]
        bounds.append(now)
        period_start = bounds[0]
        episodes = [ep for ep in self._completed if ep["region_id"] == region_id]
        if region_id in self._active:
            episodes.append(self._active[region_id])
        daily = [
            {"date": start.date().isoformat(), "count": 0, "observed_duration_seconds": 0.0}
            for start in bounds[:-1]
        ]
        count = 0
        duration = 0.0
        longest = 0.0
        has_gaps = False
        for ep in episodes:
            start = _parse(ep["observed_started_at"])
            ongoing = ep["observed_cleared_at"] is None
            end = min(_parse(ep["observed_cleared_at"]) or now, now)
            if not self._overlaps(start, end, period_start, now, ongoing):
                continue
            overlap = max((end - max(start, period_start)).total_seconds(), 0)
            count += 1
            duration += overlap
            longest = max(longest, overlap)
            has_gaps = has_gaps or ep["had_gap"]
            for bucket, day_start, day_end in zip(daily, bounds, bounds[1:], strict=False):
                if self._overlaps(start, end, day_start, day_end, ongoing):
                    bucket["count"] += 1
                    bucket["observed_duration_seconds"] += max(
                        (min(end, day_end) - max(start, day_start)).total_seconds(), 0
                    )
        for bucket in daily:
            bucket["observed_duration_seconds"] = round(bucket["observed_duration_seconds"])
        return {
            "region_id": region_id,
            "days": days,
            "period_start": period_start.isoformat(),
            "count": count,
            "observed_duration_seconds": round(duration),
            "longest_duration_seconds": round(longest),
            "has_gaps": has_gaps,
            "daily": daily,
            # Before this the journal did not exist: incomplete, not zero.
            "coverage_start": self._created_at,
        }

    @staticmethod
    def _overlaps(
        start: datetime, end: datetime, lo: datetime, hi: datetime, ongoing: bool
    ) -> bool:
        if start > hi or (start == hi and not ongoing):
            return False
        # An ongoing episode that began this very moment still counts.
        return end > lo or (ongoing and end >= lo)
