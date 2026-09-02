"""Diagnostics for the config entry — no credentials exist to redact."""

from __future__ import annotations

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
