"""Snapshot model and threat resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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


@dataclass(frozen=True)
class Alert:
    """One active alert in a region."""

    type: str
    last_update: str

    @property
    def threat(self) -> ThreatLevel:
        return _TYPE_MAP.get(self.type, ThreatLevel.UNKNOWN)


@dataclass
class Snapshot:
    """Active alerts across all regions at one point in time."""

    regions: dict[str, list[Alert]] = field(default_factory=dict)

    @property
    def active_region_count(self) -> int:
        return sum(1 for alerts in self.regions.values() if alerts)


def parse_alert_payload(raw: dict[str, Any] | list[dict[str, Any]]) -> Snapshot:
    """Normalize a WS publication ({"alerts": [...]}) or poll response ([...])."""
    items = raw.get("alerts", []) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        items = []
    regions: dict[str, list[Alert]] = {}
    for region in items:
        if not isinstance(region, dict):
            continue
        region_id = str(region.get("regionId", ""))
        if not region_id:
            continue
        active = region.get("activeAlerts")
        regions[region_id] = [
            Alert(type=a.get("type", ""), last_update=a.get("lastUpdate", ""))
            for a in (active if isinstance(active, list) else [])
            if isinstance(a, dict)
        ]
    return Snapshot(regions=regions)


def region_threat(snap: Snapshot, region_id: str, ancestors: list[str]) -> ThreatLevel:
    """Highest active threat for a region, inheriting from its ancestors."""
    alerts: list[Alert] = []
    for rid in [region_id, *ancestors]:
        alerts.extend(snap.regions.get(rid, []))
    if not alerts:
        return ThreatLevel.NONE
    return max((a.threat for a in alerts), key=_SEVERITY.__getitem__)
