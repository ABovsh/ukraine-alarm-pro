"""Snapshot model and threat resolution."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

_LOGGER = logging.getLogger(__name__)


class ThreatLevel(Enum):
    """Alert threat levels, ordered by ascending severity."""

    NONE = "none"
    # not "unknown": that string is HA's reserved STATE_UNKNOWN sentinel and
    # would make a real unrecognized-type alert look like "no data yet"
    UNKNOWN = "unrecognized"
    AIR = "air"
    ARTILLERY = "artillery"
    URBAN_FIGHTS = "urban_fights"
    CHEMICAL = "chemical"
    NUCLEAR = "nuclear"


_SEVERITY = {level: i for i, level in enumerate(ThreatLevel)}

_TYPE_MAP = {
    "AIR": ThreatLevel.AIR,
    "ARTILLERY": ThreatLevel.ARTILLERY,
    "URBAN_FIGHTS": ThreatLevel.URBAN_FIGHTS,
    "CHEMICAL": ThreatLevel.CHEMICAL,
    "NUCLEAR": ThreatLevel.NUCLEAR,
}

# An unrecognized type ranks below AIR, so on the enum sensor a concurrent
# air-raid alert masks it (the binary sensor and the attributes still show it).
# Warn once per new type so it gets mapped instead of sitting there unnoticed.
_WARNED_TYPES: set[str] = set()


def _warn_unrecognized(alert_type: str) -> None:
    if alert_type in _WARNED_TYPES:
        return
    _WARNED_TYPES.add(alert_type)
    _LOGGER.warning(
        "Unrecognized alert type %r from the alert feed — reported as "
        "'unrecognized'. Please report it so it can be mapped",
        alert_type,
    )


@dataclass(frozen=True)
class Alert:
    """One active alert, as declared by `region_id`.

    An affected region repeats its ancestor's alert verbatim, so the declaring
    region — not the region the alert was found under — is what identifies it.
    """

    type: str
    last_update: str
    region_id: str = ""
    region_type: str = ""

    @property
    def threat(self) -> ThreatLevel:
        level = _TYPE_MAP.get(self.type)
        if level is None:
            _warn_unrecognized(self.type)
            return ThreatLevel.UNKNOWN
        return level


@dataclass
class Snapshot:
    """Active alerts across all regions at one point in time."""

    regions: dict[str, list[Alert]] = field(default_factory=dict)
    # Region names as the feed spells them, for display in attributes. Both
    # transports carry them, so no separate region-tree request is needed.
    names: dict[str, str] = field(default_factory=dict)

    @property
    def active_region_count(self) -> int:
        return sum(1 for alerts in self.regions.values() if alerts)

    @property
    def active(self) -> dict[str, frozenset[Alert]]:
        """Comparable view of what is actually in alert.

        The two feeds describe the same map differently — the WebSocket may
        spell out regions it just cleared, the polling endpoint omits them, and
        neither guarantees an order — so only this view is safe to compare.
        """
        return {
            rid: frozenset(alerts) for rid, alerts in self.regions.items() if alerts
        }


def parse_alert_payload(raw: dict[str, Any] | list[dict[str, Any]]) -> Snapshot:
    """Normalize a WS publication ({"alerts": [...]}) or poll response ([...]).

    Raises ValueError on anything else. An unrecognized payload must never be
    read as "no alerts anywhere": that would silently clear every region — the
    one failure mode this integration cannot afford. The transports turn this
    into a TransportError, which reconnects or degrades instead.
    """
    items = raw.get("alerts") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        # ValueError, not TypeError: the transports already map it onto a
        # TransportError, which is the behavior every caller relies on.
        raise ValueError(  # noqa: TRY004
            f"unrecognized alert payload: {type(raw).__name__}"
        )
    regions: dict[str, list[Alert]] = {}
    names: dict[str, str] = {}
    for region in items:
        if not isinstance(region, dict):
            continue
        region_id = str(region.get("regionId", ""))
        if not region_id:
            continue
        name = region.get("regionName")
        if name:
            names[region_id] = str(name)
        active = region.get("activeAlerts")
        regions[region_id] = [
            Alert(
                type=a.get("type", ""),
                last_update=a.get("lastUpdate", ""),
                # An alert with no region of its own was declared by its container.
                region_id=str(a.get("regionId") or region_id),
                region_type=str(a.get("regionType") or ""),
            )
            for a in (active if isinstance(active, list) else [])
            if isinstance(a, dict)
        ]
    return Snapshot(regions=regions, names=names)


# Sorts an unparsable stamp oldest rather than dropping the alert.
_UNDATED = datetime.min.replace(tzinfo=UTC)


def declared_at(alert: Alert) -> datetime | None:
    """When the alert was declared, or None if the feed's stamp is unusable.

    Never compare these stamps as text: the feed mixes whole-second and
    microsecond precision within the same second, and "Z" sorts after ".", so
    the alert declared at the top of the second would rank as the newer one.
    """
    try:
        parsed = datetime.fromisoformat(alert.last_update)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def region_alerts(
    snap: Snapshot,
    region_id: str,
    ancestors: Iterable[str] = (),
    descendants: Iterable[str] = (),
) -> list[Alert]:
    """Alerts affecting a region, deduplicated, newest declaration first.

    Alerts are published at whichever administrative level they were declared
    at, so a region is affected by its own alerts, by an ancestor's (an
    oblast-wide raid) *and* by a descendant's (one raion of the oblast under
    fire). One declared alert reaches a region through every descendant that
    repeats it, so the key is the *declaring* region: keying on the region it
    was found under counted a single raion-wide raid once per hromada below it.
    """
    seen: set[tuple[str, str, str]] = set()
    found: list[Alert] = []
    for rid in [region_id, *ancestors, *descendants]:
        for alert in snap.regions.get(rid, []):
            key = (alert.region_id, alert.type, alert.last_update)
            if key in seen:
                continue
            seen.add(key)
            found.append(alert)
    # Newest first: the attribute list is capped, and a raid that just started
    # is what the cap must never drop.
    found.sort(key=lambda a: declared_at(a) or _UNDATED, reverse=True)
    return found


def region_threat(
    snap: Snapshot,
    region_id: str,
    ancestors: Iterable[str] = (),
    descendants: Iterable[str] = (),
) -> ThreatLevel:
    """Highest active threat for a region, from any administrative level."""
    found = region_alerts(snap, region_id, ancestors, descendants)
    if not found:
        return ThreatLevel.NONE
    return max((alert.threat for alert in found), key=_SEVERITY.__getitem__)


def threat_types(found: list[Alert]) -> list[str]:
    """Distinct threat types among alerts, most severe first."""
    uniq = {alert.threat for alert in found}
    return [
        level.value
        for level in sorted(uniq, key=_SEVERITY.__getitem__, reverse=True)
        if level is not ThreatLevel.NONE
    ]
