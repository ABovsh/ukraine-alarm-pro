"""Alert episode journal — observed periods of "any alert on" per region.

An episode is not a declaration: two overlapping alerts form one episode from
the first start to the last clear, which is why `alert_started` (the oldest
*still active* declaration) keeps its own meaning. Times are what the
integration observed; a gap is marked, never filled in.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from bisect import bisect_right
from collections.abc import Callable, Iterable
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

HISTORY_STORAGE_VERSION = 1
MAX_HISTORY_DAYS = 90
MAX_HISTORY_EPISODES = 10000  # Per region; trimming also limits claimed coverage.
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


def history_storage_key(entry_id: str) -> str:
    return f"{DOMAIN}.history.{entry_id}"


def _parse(stamp: Any) -> datetime | None:
    # Every stamp this journal writes carries its offset; one without it is
    # damage, and comparing it with an aware time would fail the whole setup.
    try:
        parsed = dt_util.parse_datetime(stamp) if isinstance(stamp, str) else None
    except (ValueError, OverflowError):
        return None
    return parsed if parsed is not None and parsed.tzinfo is not None else None


def _valid(episode: Any) -> bool:
    return (
        isinstance(episode, dict)
        and all(key in episode for key in _FIELDS)
        and isinstance(episode["region_id"], str)
        and _parse(episode["observed_started_at"]) is not None
        and isinstance(episode["active_types_seen"], list)
        and all(isinstance(kind, str) for kind in episode["active_types_seen"])
        and isinstance(episode["maximum_air_level"], str)
        and isinstance(episode["had_gap"], bool)
        and isinstance(episode["source_start_known"], bool)
        and isinstance(episode["start_origin"], str)
        and (
            episode["observed_cleared_at"] is None
            or (
                _parse(episode["observed_cleared_at"]) is not None
                and _parse(episode["observed_cleared_at"])
                >= _parse(episode["observed_started_at"])
            )
        )
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
        # When the official history was last merged; drives the next window.
        self._synced_at: str | None = None
        # Which regions that merge covered; a region added later has none yet.
        self._synced_regions: set[str] = set()
        self._version = 0
        self._saved_version = 0
        self._flush_lock = asyncio.Lock()
        self._index: dict[str, list[dict[str, Any]]] = {}
        self._last_prune_day = None
        self._live_since: dict[str, str] = {}
        self._confirmed: dict[str, str] = {}
        self._gaps: dict[str, list[tuple[str, str]]] = {}
        self._open_gaps: dict[str, str] = {}
        self._resync: set[str] = set()
        self._retained_from: dict[str, str] = {}
        self._official_since: dict[str, str] = {}
        self._official_spans: dict[str, list[tuple[str, str]]] = {}
        self._cursors: dict[str, str] = {}
        self._backfill_targets: dict[str, str] = {}

    @property
    def version(self) -> int:
        return self._version

    def _episodes(self, region_id: str) -> list[dict[str, Any]]:
        return [
            *self._index.get(region_id, []),
            *([self._active[region_id]] if region_id in self._active else []),
        ]

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
                    rid: ep
                    for rid, ep in active.items()
                    if _valid(ep) and ep["region_id"] == rid
                }
            episodes = stored.get("episodes")
            if isinstance(episodes, list):
                self._completed = [
                    ep
                    for ep in episodes
                    if _valid(ep) and _parse(ep["observed_cleared_at"]) is not None
                ]
            if _parse(stored.get("created_at")) is not None:
                self._created_at = stored["created_at"]
            if _parse(stored.get("official_synced_at")) is not None:
                self._synced_at = stored["official_synced_at"]
                synced_regions = stored.get("official_synced_regions")
                if isinstance(synced_regions, list):
                    self._synced_regions = {str(rid) for rid in synced_regions}
            # Additive schema: v1 episodes stay readable. Old global coverage
            # did not distinguish air backfill from all threats, so it cannot
            # certify a new percentage sensor's denominator.
            for key, target in (
                ("live_since", self._live_since),
                ("confirmed", self._confirmed),
                ("retained_from", self._retained_from),
                ("official_since", self._official_since),
                ("cursors", self._cursors),
                ("open_gaps", self._open_gaps),
                ("backfill_targets", self._backfill_targets),
            ):
                raw = stored.get(key)
                if isinstance(raw, dict):
                    target.update(
                        {
                            str(rid): stamp
                            for rid, stamp in raw.items()
                            if _parse(stamp) is not None
                        }
                    )
            for key, target in (
                ("gaps", self._gaps),
                ("official_spans", self._official_spans),
            ):
                raw = stored.get(key)
                if isinstance(raw, dict):
                    for rid, spans in raw.items():
                        if isinstance(spans, list):
                            target[str(rid)] = [
                                (lo, hi)
                                for item in spans
                                if isinstance(item, (list, tuple)) and len(item) == 2
                                for lo, hi in [item]
                                if _parse(lo) is not None
                                and _parse(hi) is not None
                                and _parse(hi) > _parse(lo)
                            ]
            self._resync = set(self._confirmed)
        elif stored is not None:
            _LOGGER.warning("Alert history has an unknown format — starting a new one")
        if self._created_at is None:
            # History before this moment is unknown, not empty.
            self._created_at = self._now().isoformat()
            self._version += 1
        self._index = {}
        for ep in self._completed:
            self._index.setdefault(ep["region_id"], []).append(ep)
        self._prune()

    def confirm(self, region_ids: Iterable[str], at: datetime) -> None:
        """Confirm continuity, including unchanged/quiet snapshots.

        A restart or a stale feed leaves an explicit hole from its last real
        confirmation to recovery. An air-only backfill never closes that hole
        for the all-threat binary-sensor definition.
        """
        at = at.astimezone(dt_util.UTC)
        stamp = at.isoformat()
        for rid in region_ids:
            previous = _parse(self._confirmed.get(rid))
            if rid in self._resync and previous is not None:
                self._open_gaps.setdefault(rid, previous.isoformat())
                self._resync.discard(rid)
            opened = _parse(self._open_gaps.pop(rid, None))
            if opened is not None and at > opened:
                self._gaps.setdefault(rid, []).append((opened.isoformat(), stamp))
            if previous is not None and at < previous:
                self._gaps.setdefault(rid, []).append((stamp, previous.isoformat()))
            self._live_since.setdefault(rid, stamp)
            self._confirmed[rid] = stamp
        self._version += 1

    def mark_gap(self, region_ids: Iterable[str]) -> None:
        """Keep gaps even when the last known state was quiet."""
        for rid in region_ids:
            if rid in self._confirmed and rid not in self._open_gaps:
                self._open_gaps[rid] = self._confirmed[rid]
                self._version += 1

    def handle_event(self, event_type: str, payload: dict[str, Any]) -> None:
        region_id = payload["region_id"]
        current = payload["current"]
        at = payload["observed_at"]
        origin = payload["origin"]
        if event_type == "data_stale":
            self.mark_gap([region_id])
        else:
            self.confirm([region_id], _parse(at))
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
            finished = self._active.pop(region_id)
            self._completed.append(finished)
            self._index.setdefault(region_id, []).append(finished)
        else:
            return
        self._version += 1
        self._prune(region_id)

    async def async_flush(self, _now: datetime | None = None) -> None:
        """Write pending changes; marked saved only after the write succeeded.

        Called on a fixed interval and at unload, never as a trailing debounce
        that a steady stream of events could postpone forever.
        """
        async with self._flush_lock:
            if self._version == self._saved_version:
                return
            self._prune()
            version = self._version
            await self._store.async_save(
                deepcopy(
                    {
                        "schema_version": 2,
                        "created_at": self._created_at,
                        "official_synced_at": self._synced_at,
                        "official_synced_regions": sorted(self._synced_regions),
                        "active": self._active,
                        "episodes": self._completed,
                        "live_since": self._live_since,
                        "confirmed": self._confirmed,
                        "gaps": self._gaps,
                        "open_gaps": self._open_gaps,
                        "retained_from": self._retained_from,
                        "official_since": self._official_since,
                        "official_spans": self._official_spans,
                        "cursors": self._cursors,
                        "backfill_targets": self._backfill_targets,
                    }
                )
            )
            self._saved_version = version

    def cursor(self, region_id: str, now: datetime) -> datetime:
        return max(
            now - self._max_age,
            _parse(self._cursors.get(region_id)) or now - self._max_age,
        )

    def advance_cursor(self, region_ids: Iterable[str], end: datetime) -> None:
        for rid in region_ids:
            previous = _parse(self._cursors.get(rid))
            self._cursors[rid] = max(previous or end, end).isoformat()
        self._version += 1

    def backfill_window(
        self, region_id: str, now: datetime
    ) -> tuple[datetime, datetime] | None:
        cursor = self.cursor(region_id, now)
        target = _parse(self._backfill_targets.get(region_id))
        if target is not None:
            return (cursor, target) if cursor < target else None
        if cursor >= now - timedelta(hours=24):
            return None
        return max(now - self._max_age, cursor - timedelta(days=2)), now

    def begin_backfill(self, region_ids: Iterable[str], target: datetime) -> None:
        for rid in region_ids:
            self._backfill_targets[rid] = target.isoformat()
        self._version += 1

    def finish_backfill(self, region_ids: Iterable[str]) -> None:
        for rid in region_ids:
            self._backfill_targets.pop(rid, None)
        self._version += 1

    def backfill_start(self, now: datetime, region_ids: Iterable[str]) -> datetime:
        """Where the next official-history window begins.

        The first run covers the whole retention; later runs re-read a couple
        of days before the last sync, enough to fill any outage since. A region
        the last sync did not cover (added through Configure) needs it all.
        """
        oldest = now - self._max_age
        synced = _parse(self._synced_at)
        if synced is None or not set(region_ids) <= self._synced_regions:
            return oldest
        return max(oldest, synced - timedelta(days=2))

    def mark_synced(self, now: datetime, region_ids: Iterable[str]) -> None:
        self._synced_at = now.isoformat()
        self._synced_regions = set(region_ids)
        self._version += 1

    def merge_official(
        self,
        region_id: str,
        intervals: list[tuple[datetime, datetime]],
        *,
        window_start: datetime,
    ) -> int:
        """Add official episodes for periods the journal did not observe.

        What the integration observed wins wherever the two overlap, so a
        re-run or a slightly different official time never duplicates an
        episode. Returns how many episodes were added.
        """
        now = self._now()
        added = 0
        spans = [
            (_parse(lo), _parse(hi))
            for lo, hi in self._official_spans.get(region_id, [])
        ]
        spans.extend((start, end) for start, end in intervals if start < end <= now)
        merged = _union(spans)
        encoded = [(lo.isoformat(), hi.isoformat()) for lo, hi in merged]
        if encoded != self._official_spans.get(region_id, []):
            self._official_spans[region_id] = encoded
            self._version += 1
        for start, end in _union(intervals):
            overlapping = [
                ep
                for ep in self._episodes(region_id)
                if start < (_parse(ep["observed_cleared_at"]) or now)
                and end > _parse(ep["observed_started_at"])
            ]
            if end > now:
                continue
            if overlapping:
                for ep in overlapping:
                    if (
                        not ep["source_start_known"]
                        and ep["active_types_seen"] == ["air"]
                        and start < _parse(ep["observed_started_at"])
                    ):
                        ep["observed_started_at"] = start.isoformat()
                        ep["declared_started_at"] = start.isoformat()
                        ep["source_start_known"] = True
                        self._version += 1
                continue
            episode = {
                "episode_id": uuid.uuid4().hex[:12],
                "region_id": region_id,
                "observed_started_at": start.isoformat(),
                "declared_started_at": start.isoformat(),
                "observed_cleared_at": end.isoformat(),
                "active_types_seen": ["air"],
                # The history carries no levels.
                "maximum_air_level": "none",
                "had_gap": False,
                "source_start_known": True,
                "start_origin": "history",
            }
            self._completed.append(episode)
            self._index.setdefault(region_id, []).append(episode)
            added += 1
            self._version += 1  # Invalidate the region index before the next span.
        created = _parse(self._official_since.get(region_id)) or _parse(
            self._created_at
        )
        if created is None or window_start < created:
            self._official_since[region_id] = window_start.isoformat()
            self._version += 1
        if added:
            self._version += 1
            self._prune(region_id)
        return added

    def _prune(self, region_id: str | None = None) -> None:
        now = self._now()
        daily = self._last_prune_day != now.date()
        self._last_prune_day = now.date()
        cutoff = now - self._max_age
        changed = False
        for rid in list(self._index) if daily or region_id is None else [region_id]:
            previous = self._index.get(rid, [])
            if not daily and len(previous) <= self._max_episodes:
                continue
            episodes = (
                [ep for ep in previous if _parse(ep["observed_cleared_at"]) >= cutoff]
                if daily
                else list(previous)
            )
            episodes.sort(key=lambda ep: _parse(ep["observed_started_at"]))
            dropped = episodes[: -self._max_episodes]
            if dropped:
                self._retained_from[rid] = max(
                    _parse(ep["observed_cleared_at"]) for ep in dropped
                ).isoformat()
            kept = episodes[-self._max_episodes :]
            self._index[rid] = kept
            changed |= len(kept) != len(previous)
        if daily:
            for target in (self._gaps, self._official_spans):
                for rid, spans in target.items():
                    remaining = [(lo, hi) for lo, hi in spans if _parse(hi) >= cutoff]
                    if len(remaining) > self._max_episodes:
                        self._retained_from[rid] = remaining[-self._max_episodes - 1][1]
                        remaining = remaining[-self._max_episodes :]
                    changed |= len(remaining) != len(spans)
                    target[rid] = remaining
        if changed:
            self._version += 1
            self._completed = [
                ep for episodes in self._index.values() for ep in episodes
            ]

    def history(self, region_id: str, limit: int) -> list[dict[str, Any]]:
        """Newest first, the ongoing episode included."""
        episodes = self._episodes(region_id)
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
        episodes = self._episodes(region_id)
        daily = [
            {
                "date": start.date().isoformat(),
                "count": 0,
                "observed_duration_seconds": 0.0,
            }
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
            for bucket, day_start, day_end in zip(
                daily, bounds, bounds[1:], strict=False
            ):
                if self._overlaps(start, end, day_start, day_end, ongoing):
                    bucket["count"] += 1
                    bucket["observed_duration_seconds"] += max(
                        min(end, day_end).timestamp()
                        - max(start, day_start).timestamp(),
                        0,
                    )
        for bucket in daily:
            bucket["observed_duration_seconds"] = round(
                bucket["observed_duration_seconds"]
            )
        has_gaps |= any(
            _parse(start) < now and _parse(end) > period_start
            for start, end in self._gaps.get(region_id, [])
        )
        has_gaps |= region_id in self._open_gaps or region_id in self._resync
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
            "coverage_start": self._official_since.get(region_id, self._created_at),
            "rolling": self.rolling(region_id, 86400 if days == 1 else 604800),
        }

    def rolling(
        self, region_id: str, window_seconds: int, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Fixed UTC-second window, union of intervals, honest quality metadata."""
        now = (now or self._now()).astimezone(dt_util.UTC)
        lo = now - timedelta(seconds=window_seconds)
        episodes = self._episodes(region_id)
        spans = [
            (
                _parse(ep["observed_started_at"]),
                _parse(ep["observed_cleared_at"]) or now,
            )
            for ep in episodes
        ]
        spans.extend(
            (_parse(a), _parse(b)) for a, b in self._official_spans.get(region_id, [])
        )
        intervals = _union(
            [
                (max(start, lo), min(end, now))
                for start, end in spans
                if start < now and end > lo
            ]
        )
        duration = sum((end - start).total_seconds() for start, end in intervals)
        gaps = [(_parse(a), _parse(b)) for a, b in self._gaps.get(region_id, [])]
        opened = _parse(self._open_gaps.get(region_id))
        if opened is not None:
            gaps.append((opened, now))
        holes = _union(
            [
                (max(start, lo), min(end, now))
                for start, end in gaps
                if start < now and end > lo
            ]
        )
        gap_seconds = sum((end - start).total_seconds() for start, end in holes)
        since = _parse(self._live_since.get(region_id))
        retained = _parse(self._retained_from.get(region_id))
        confirmed = _parse(self._confirmed.get(region_id))
        quality = "complete"
        if since is None or since > lo:
            quality = "incomplete"
        if retained is not None and retained > lo:
            quality = "truncated"
        if holes:
            quality = "gaps"
        if opened is not None or region_id in self._resync:
            quality = "stale"
        if confirmed is not None and confirmed > now:
            quality = "clock_jump"
        if any(start <= now < end for start, end in gaps):
            quality = "clock_jump" if opened is None else "stale"
        complete = quality == "complete"
        rendered = [
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "maximum_air_level": "none",
                "had_gap": False,
                "ongoing": False,
            }
            for start, end in intervals
        ]
        starts = [start for start, _end in intervals]
        for ep in episodes:
            start = max(_parse(ep["observed_started_at"]), lo)
            end = min(_parse(ep["observed_cleared_at"]) or now, now)
            if start >= end or not starts:
                continue
            index = max(0, bisect_right(starts, start) - 1)
            row = rendered[index]
            if _AIR_RANK.get(ep["maximum_air_level"], 0) > _AIR_RANK.get(
                row["maximum_air_level"], 0
            ):
                row["maximum_air_level"] = ep["maximum_air_level"]
            row["had_gap"] |= ep["had_gap"]
            row["ongoing"] |= ep["observed_cleared_at"] is None
        return {
            "region_id": region_id,
            "window_seconds": window_seconds,
            "percentage": round(100 * duration / window_seconds, 1)
            if complete
            else None,
            "coverage_complete": complete,
            "quality": quality,
            "threat_scope": "any_alert",
            "gap_seconds": round(gap_seconds),
            "count": len(intervals),
            "observed_duration_seconds": round(duration),
            "longest_duration_seconds": round(
                max(
                    ((end - start).total_seconds() for start, end in intervals),
                    default=0,
                )
            ),
            "intervals": rendered,
        }

    @staticmethod
    def _overlaps(
        start: datetime, end: datetime, lo: datetime, hi: datetime, ongoing: bool
    ) -> bool:
        if start > hi or (start == hi and not ongoing):
            return False
        # An ongoing episode that began this very moment still counts.
        return end > lo or (ongoing and end >= lo)


def _union(spans: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    result: list[tuple[datetime, datetime]] = []
    for start, end in sorted(
        (a, b) for a, b in spans if a is not None and b is not None and b > a
    ):
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result
