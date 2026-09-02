"""Hardening tests for 0.5.1 — the staleness tick must not write unchanged state.

Measured on the live recorder DB (2026-08-08): `binary_sensor.uap_data_stale`
and `sensor.uap_last_update` each wrote ~1.7k rows/day while the feed was
perfectly healthy. 0.5.0 stopped the *coordinator* from notifying on an
unchanged alert map, but the 60 s staleness tick still called
`async_write_ha_state()` unconditionally — and because the exposed
`last_update` moves on every push, every tick landed a new recorder row.

The tick exists to age the staleness verdict. If that verdict has not moved,
there is nothing to publish.
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
    STALE_AFTER_SECONDS,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from custom_components.ukraine_alarm_pro.coordinator import AlarmCoordinator
from custom_components.ukraine_alarm_pro.models import parse_alert_payload
from custom_components.ukraine_alarm_pro.sensor import LastUpdateSensor

ENTRY_DATA = {"regions": ["31"]}
SNAP = parse_alert_payload(
    {"alerts": [{"regionId": "31", "activeAlerts": [{"type": "AIR", "lastUpdate": "a"}]}]}
)


def _store(hass):
    """Real Store: the coordinator persists the alert map for restarts."""
    return Store(hass, STORAGE_VERSION, STORAGE_KEY)


def _coordinator(hass: HomeAssistant) -> AlarmCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    return AlarmCoordinator(hass, entry, MagicMock(), _store(hass))


def _entities(coordinator):
    return [
        DataStaleBinarySensor(coordinator, "e1"),
        LastUpdateSensor(coordinator, "e1"),
    ]


async def test_tick_does_not_write_while_staleness_is_unchanged(hass: HomeAssistant):
    coordinator = _coordinator(hass)
    coordinator.handle_snapshot(SNAP)

    for entity in _entities(coordinator):
        with patch.object(entity, "async_write_ha_state") as write:
            entity._async_tick(dt_util.utcnow())
            entity._async_tick(dt_util.utcnow())
            entity._async_tick(dt_util.utcnow())
            assert write.call_count == 0, (
                f"{type(entity).__name__} republished an unchanged staleness verdict"
            )


async def test_tick_writes_when_the_feed_goes_stale(hass: HomeAssistant):
    coordinator = _coordinator(hass)
    coordinator.handle_snapshot(SNAP)

    for entity in _entities(coordinator):
        with patch.object(entity, "async_write_ha_state") as write:
            entity._async_tick(dt_util.utcnow())  # healthy, seeds the baseline
            assert write.call_count == 0

            gone = dt_util.utcnow() + timedelta(seconds=STALE_AFTER_SECONDS + 60)
            with patch(
                "custom_components.ukraine_alarm_pro.coordinator.dt_util.utcnow",
                return_value=gone,
            ):
                assert coordinator.is_stale is True
                entity._async_tick(gone)
                entity._async_tick(gone)

            assert write.call_count == 1, (
                f"{type(entity).__name__} must publish the stale transition exactly once"
            )


async def test_tick_writes_again_on_recovery(hass: HomeAssistant):
    coordinator = _coordinator(hass)
    entity = DataStaleBinarySensor(coordinator, "e1")

    with patch.object(entity, "async_write_ha_state") as write:
        entity._async_tick(dt_util.utcnow())  # stale: no snapshot has arrived yet
        assert coordinator.is_stale is True
        assert write.call_count == 0  # first tick only seeds the baseline

        coordinator.handle_snapshot(SNAP)
        entity._async_tick(dt_util.utcnow())
        assert write.call_count == 1, "recovery must be published"
