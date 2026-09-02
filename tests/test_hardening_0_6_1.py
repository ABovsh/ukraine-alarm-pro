"""Hardening tests for 0.6.1 — the last-update clock has to keep moving.

0.5.0 stopped the coordinator from notifying on an unchanged alert map and
0.5.1 stopped the staleness tick from republishing an unchanged verdict.
Together they took `sensor.uap_last_update` from ~34k recorder rows/day to
zero — but `coordinator.last_push` keeps moving every couple of seconds, so
the published state froze at the last alert-map change and a perfectly healthy
feed was displayed as hours old (measured on the live recorder 2026-08-08:
0 rows/h after 08:00 while the WebSocket was up the whole time).

The state of that sensor *is* the push clock, so it has to be republished —
but at most once a minute. The frontend renders a live "x minutes ago" from
the static state in between.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ukraine_alarm_pro.binary_sensor import DataStaleBinarySensor
from custom_components.ukraine_alarm_pro.const import (
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from custom_components.ukraine_alarm_pro.coordinator import AlarmCoordinator
from custom_components.ukraine_alarm_pro.models import parse_alert_payload
from custom_components.ukraine_alarm_pro.sensor import LastUpdateSensor

CLOCK = "custom_components.ukraine_alarm_pro.coordinator.dt_util.utcnow"
SNAP = parse_alert_payload(
    {"alerts": [{"regionId": "31", "activeAlerts": [{"type": "AIR", "lastUpdate": "a"}]}]}
)


def _store(hass):
    """Real Store: the coordinator persists the alert map for restarts."""
    return Store(hass, STORAGE_VERSION, STORAGE_KEY)


def _coordinator(hass: HomeAssistant) -> AlarmCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, data={"regions": {}})
    entry.add_to_hass(hass)
    return AlarmCoordinator(hass, entry, MagicMock(), _store(hass))


def _quiet_push(coordinator: AlarmCoordinator, now) -> None:
    """Republish the identical alert map: only the push clock moves."""
    with patch(CLOCK, return_value=now):
        coordinator.handle_snapshot(SNAP)


async def test_last_update_republishes_once_the_minute_turns(hass: HomeAssistant):
    t0 = dt_util.utcnow().replace(second=0, microsecond=0)
    coordinator = _coordinator(hass)
    _quiet_push(coordinator, t0)
    entity = LastUpdateSensor(coordinator, "e1")

    with patch.object(entity, "async_write_ha_state") as write:
        _quiet_push(coordinator, t0 + timedelta(seconds=20))
        entity._async_tick(t0 + timedelta(seconds=20))
        _quiet_push(coordinator, t0 + timedelta(seconds=50))
        entity._async_tick(t0 + timedelta(seconds=50))
        assert write.call_count == 0, "same minute carries no new information"

        _quiet_push(coordinator, t0 + timedelta(seconds=90))
        entity._async_tick(t0 + timedelta(seconds=90))
        assert write.call_count == 1, "the clock moved into a new minute"

        _quiet_push(coordinator, t0 + timedelta(seconds=110))
        entity._async_tick(t0 + timedelta(seconds=110))
        assert write.call_count == 1, "still the same minute — one row is enough"


async def test_last_update_is_capped_at_one_row_per_minute(hass: HomeAssistant):
    """A 2.5 s feed must not produce more than a row per minute."""
    t0 = dt_util.utcnow().replace(second=0, microsecond=0)
    coordinator = _coordinator(hass)
    _quiet_push(coordinator, t0)
    entity = LastUpdateSensor(coordinator, "e1")

    with patch.object(entity, "async_write_ha_state") as write:
        for step in range(2, 602, 2):  # 10 minutes of pushes
            now = t0 + timedelta(seconds=step)
            _quiet_push(coordinator, now)
            entity._async_tick(now)
        assert write.call_count == 10, f"expected 10 rows, got {write.call_count}"


async def test_data_stale_still_only_publishes_verdict_changes(hass: HomeAssistant):
    """The boolean verdict entity must not pick up the per-minute heartbeat."""
    t0 = dt_util.utcnow().replace(second=0, microsecond=0)
    coordinator = _coordinator(hass)
    _quiet_push(coordinator, t0)
    entity = DataStaleBinarySensor(coordinator, "e1")

    with patch.object(entity, "async_write_ha_state") as write:
        for step in range(60, 601, 60):
            now = t0 + timedelta(seconds=step)
            _quiet_push(coordinator, now)
            entity._async_tick(now)
        assert write.call_count == 0, "the feed stayed healthy; nothing to publish"
