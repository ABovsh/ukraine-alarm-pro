"""Hardening tests for 0.5.0 — no entity writes on unchanged snapshots.

Measured on the live recorder DB (2026-08-07): the feed republishes the same
alert map every ~2.6 s, and every republish wrote a state row for
`sensor.uap_last_update` and `binary_sensor.uap_data_stale` — 65k recorder
rows/day carrying no information.
"""

from datetime import timedelta
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ukraine_alarm_pro.const import DOMAIN
from custom_components.ukraine_alarm_pro.coordinator import AlarmCoordinator
from custom_components.ukraine_alarm_pro.models import parse_alert_payload

ENTRY_DATA = {"regions": ["31"]}

SNAP = parse_alert_payload(
    {"alerts": [{"regionId": "31", "activeAlerts": [{"type": "AIR", "lastUpdate": "a"}]}]}
)
# Same alert map, spelled differently: the WS also lists regions it just
# cleared, and neither feed guarantees order.
SNAP_SAME = parse_alert_payload(
    {
        "alerts": [
            {"regionId": "703", "activeAlerts": []},
            {"regionId": "31", "activeAlerts": [{"type": "AIR", "lastUpdate": "a"}]},
        ]
    }
)
SNAP_OTHER = parse_alert_payload({"alerts": [{"regionId": "31", "activeAlerts": []}]})


def _coordinator(hass: HomeAssistant) -> AlarmCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    return AlarmCoordinator(hass, entry, MagicMock())


async def test_repeated_snapshot_does_not_notify_listeners(hass: HomeAssistant):
    coordinator = _coordinator(hass)
    listener = MagicMock()
    coordinator.async_add_listener(listener)

    coordinator.handle_snapshot(SNAP)
    assert listener.call_count == 1

    coordinator.handle_snapshot(SNAP)
    coordinator.handle_snapshot(SNAP_SAME)
    assert listener.call_count == 1, "identical alert map must not write state"

    coordinator.handle_snapshot(SNAP_OTHER)
    assert listener.call_count == 2


async def test_repeated_snapshot_still_counts_as_liveness(hass: HomeAssistant):
    coordinator = _coordinator(hass)
    coordinator.handle_snapshot(SNAP)
    coordinator.last_push = dt_util.utcnow() - timedelta(hours=1)
    assert coordinator.is_stale is True

    coordinator.handle_snapshot(SNAP)
    assert coordinator.is_stale is False, "a repeat push still proves the feed is alive"
    assert coordinator.data is not None
