"""Alert transitions — which event an accepted change is, with its payload.

Pure logic: the coordinator decides *when* a change was accepted and the event
platform delivers it. One accepted snapshot yields at most one event per region,
carrying every fact of the transition, so an automation never has to merge
several rapid events or read sensors that are still updating one by one.
"""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .models import MAX_AFFECTED_REGIONS, RegionView, ThreatLevel

SCHEMA_VERSION = 1

EVENT_STARTED = "started"
EVENT_CLEARED = "cleared"
EVENT_THREAT_ADDED = "threat_added"
EVENT_ESCALATED = "escalated"
EVENT_UPDATED = "updated"
EVENT_DATA_STALE = "data_stale"
EVENT_RESYNCED = "resynced"
EVENT_TYPES = [
    EVENT_STARTED,
    EVENT_ESCALATED,
    EVENT_THREAT_ADDED,
    EVENT_UPDATED,
    EVENT_CLEARED,
    EVENT_DATA_STALE,
    EVENT_RESYNCED,
]

ORIGIN_LIVE = "live"
ORIGIN_RECOVERY = "recovery"
ORIGIN_BOOTSTRAP = "bootstrap"

MAX_REASON_LENGTH = 256
_AIR_RANK = {"none": 0, "unrecognized": 1, "yellow": 2, "red": 3}


@dataclass(frozen=True)
class RegionState:
    """The compact, comparable picture of one region that events carry.

    Level timestamps are left out on purpose: a re-stamped level with the same
    value is not a change anyone should be notified about.
    """

    active: bool = False
    threat_types: tuple[str, ...] = ()
    air_level: str = "none"
    reasons: tuple[str, ...] = ()
    coverage: str = "none"
    declared_started_at: str | None = None

    @classmethod
    def from_view(cls, view: RegionView) -> RegionState:
        return cls(
            active=view.threat is not ThreatLevel.NONE,
            threat_types=view.threat_types,
            air_level=view.air_levels[0] if view.air_levels else "none",
            reasons=tuple(
                reason[:MAX_REASON_LENGTH]
                for reason in view.air_reasons[:MAX_AFFECTED_REGIONS]
            ),
            coverage=view.coverage,
            declared_started_at=view.started.isoformat() if view.started else None,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "threat_types": list(self.threat_types),
            "air_level": self.air_level,
            "reasons": list(self.reasons),
            "coverage": self.coverage,
            "declared_started_at": self.declared_started_at,
        }


def classify(previous: RegionState, current: RegionState) -> str | None:
    """The one event type of a live change, or None when nothing changed.

    Priority: start/clear, then a higher known air level, then a new threat
    type, then anything else. A change that adds a type and raises the level
    together is one `escalated` event; the new type is in its payload.
    """
    if previous == current:
        return None
    if current.active != previous.active:
        return EVENT_STARTED if current.active else EVENT_CLEARED
    if (
        previous.air_level != "none"
        and current.air_level in ("yellow", "red")
        and _AIR_RANK[current.air_level] > _AIR_RANK.get(previous.air_level, 0)
    ):
        return EVENT_ESCALATED
    if set(current.threat_types) - set(previous.threat_types):
        return EVENT_THREAT_ADDED
    return EVENT_UPDATED


type EventListener = Callable[[str, dict[str, Any]], None]


class AlertEventHub:
    """Remembers each region's last published state and fans events out."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[EventListener]] = {}
        self._states: dict[str, RegionState] = {}
        # Unique within one runtime; no exactly-once promise across restarts.
        self._runtime = uuid.uuid4().hex[:8]
        self._counter = itertools.count(1)
        self.bootstrapped = False
        self.stale_announced = False

    @property
    def listener_count(self) -> int:
        return sum(len(listeners) for listeners in self._listeners.values())

    def add_listener(
        self, region_id: str | None, listener: EventListener
    ) -> Callable[[], None]:
        """Listen to one region, or to every region with `None`."""
        self._listeners.setdefault(region_id, []).append(listener)

        def _remove() -> None:
            self._listeners[region_id].remove(listener)

        return _remove

    def accept(
        self,
        states: dict[str, tuple[str, RegionState]],
        *,
        origin: str,
        observed_at: str,
    ) -> None:
        """Publish the transition of every region for one accepted snapshot."""
        for region_id, (name, current) in states.items():
            previous = self._states.get(region_id)
            self._states[region_id] = current
            if origin == ORIGIN_LIVE and previous is not None:
                event_type = classify(previous, current)
                if event_type is None:
                    continue
            else:
                # After a gap nobody knows what started or ended in between:
                # report where things stand instead of replaying guesses.
                event_type = EVENT_RESYNCED
            self._publish(
                region_id,
                name,
                event_type,
                origin=origin,
                observed_at=observed_at,
                previous=None if origin == ORIGIN_BOOTSTRAP else previous,
                current=current,
                had_gap=origin != ORIGIN_LIVE,
            )
        self.bootstrapped = True
        self.stale_announced = False

    def announce_stale(self, names: dict[str, str], *, observed_at: str) -> None:
        """Tell each region once that its last known state is no longer live."""
        if self.stale_announced or not self.bootstrapped:
            return
        self.stale_announced = True
        for region_id, name in names.items():
            state = self._states.get(region_id)
            if state is None:
                continue
            self._publish(
                region_id,
                name,
                EVENT_DATA_STALE,
                origin=ORIGIN_LIVE,
                observed_at=observed_at,
                previous=state,
                current=state,
                had_gap=True,
            )

    def _publish(
        self,
        region_id: str,
        name: str,
        event_type: str,
        *,
        origin: str,
        observed_at: str,
        previous: RegionState | None,
        current: RegionState,
        had_gap: bool,
    ) -> None:
        before = previous.threat_types if previous is not None else ()
        payload = {
            "schema_version": SCHEMA_VERSION,
            "transition_id": f"{self._runtime}-{next(self._counter)}",
            "region_id": region_id,
            "region_name": name,
            "event_type": event_type,
            "observed_at": observed_at,
            "origin": origin,
            "previous": previous.as_dict() if previous is not None else None,
            "current": current.as_dict(),
            "added_types": [t for t in current.threat_types if t not in before],
            "removed_types": [t for t in before if t not in current.threat_types],
            "had_gap": had_gap,
        }
        for listener in (
            *self._listeners.get(region_id, ()),
            *self._listeners.get(None, ()),
        ):
            listener(event_type, payload)
