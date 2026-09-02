"""Hardening tests for 0.6.2 — attributes must not manufacture recorder rows.

Measured on the live recorder 2026-09-02: `binary_sensor.uap_data_stale` wrote
744 rows/day and `sensor.uap_active_regions` 739, while the WebSocket was up
and the local verdict never flipped. Home Assistant only stores a row when the
state *or the attributes* differ, and both entities carried a value that moves
on every country-wide alert-map change:

  * `data_stale` published `last_update` — the push clock, which already has
    its own entity (`sensor.uap_last_update`);
  * `active_regions` published `region_ids` — a ~66-entry list that changes
    whenever any of Ukraine's regions goes on or off alert, so the count could
    sit at 66 all day and still write a row (plus a ~700-byte blob) each time.

Both entities must publish a row only when their own value changes.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ukraine_alarm_pro.const import DOMAIN
from custom_components.ukraine_alarm_pro.models import parse_alert_payload

ENTRY_DATA = {"regions": {"31": {"name": "м. Київ", "ancestors": [], "descendants": []}}}


def _map(*region_ids: str) -> dict:
    return {
        "alerts": [
            {
                "regionId": rid,
                "regionType": "State",
                "activeAlerts": [{"type": "AIR", "lastUpdate": f"t{rid}"}],
            }
            for rid in region_ids
        ]
    }


async def _setup(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, entry_id="test1")
    entry.add_to_hass(hass)
    sup = AsyncMock()
    sup.mode = "websocket"
    sup.set_listener = MagicMock()
    sup.set_mode_listener = MagicMock()
    with patch(
        "custom_components.ukraine_alarm_pro.TransportSupervisor", return_value=sup
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return sup.set_listener.call_args[0][0]


async def _push(hass: HomeAssistant, push, payload: dict) -> None:
    push(parse_alert_payload(payload))
    await hass.async_block_till_done()


async def test_data_stale_writes_no_row_when_the_country_map_changes(
    hass: HomeAssistant, enable_custom_integrations
):
    push = await _setup(hass)
    await _push(hass, push, _map("14", "43"))
    before = hass.states.get("binary_sensor.uap_data_stale")

    await _push(hass, push, _map("14", "43", "31"))
    after = hass.states.get("binary_sensor.uap_data_stale")

    assert after.state == before.state == "off"
    assert after.last_updated == before.last_updated, (
        "the feed is healthy and the verdict did not flip — no recorder row is due"
    )


async def test_active_regions_writes_no_row_when_the_count_holds(
    hass: HomeAssistant, enable_custom_integrations
):
    push = await _setup(hass)
    await _push(hass, push, _map("14", "43"))
    before = hass.states.get("sensor.uap_active_regions")

    # Two regions still on alert, but a different two.
    await _push(hass, push, _map("31", "50"))
    after = hass.states.get("sensor.uap_active_regions")

    assert after.state == before.state == "2"
    assert after.last_updated == before.last_updated, (
        "the published number is unchanged — no recorder row is due"
    )
