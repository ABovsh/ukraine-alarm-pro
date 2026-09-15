"""Diagnostics for the config entry — no credentials exist to redact."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import UkraineAlarmProConfigEntry
from .const import CONF_REGIONS


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: UkraineAlarmProConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    snapshot = coordinator.data
    return {
        "transport": {
            "mode": coordinator.supervisor.mode,
            "seconds_since_update": coordinator.seconds_since_push,
            "stale": coordinator.is_stale,
            # Accepted data and cross-check attempts are separate facts: a
            # failed check must never read as a fresh snapshot.
            "seconds_since_accepted_snapshot": (
                coordinator.supervisor.seconds_since_snapshot
            ),
            "seconds_since_cross_check": coordinator.supervisor.seconds_since_check,
            "snapshot_revision": coordinator.supervisor.snapshot_revision,
        },
        "configured_regions": {
            rid: {
                "name": info.get("name"),
                "ancestors": info.get("ancestors", []),
                "descendant_count": len(info.get("descendants", [])),
            }
            for rid, info in entry.data.get(CONF_REGIONS, {}).items()
        },
        "active_alerts": (
            {
                rid: [
                    {
                        "type": alert.type,
                        "declared_by": alert.region_id,
                        "declared_by_name": snapshot.names.get(alert.region_id, ""),
                        "since": alert.last_update,
                        "levels": [asdict(level) for level in alert.levels],
                    }
                    for alert in alerts
                ]
                for rid, alerts in snapshot.regions.items()
                if alerts
            }
            if snapshot is not None
            else None
        ),
    }
