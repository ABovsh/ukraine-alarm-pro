"""Hardening round 0.2.0: descendant alerts, feed staleness, entry-owned tasks."""

import asyncio
import logging
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ukraine_alarm_pro.api.errors import TransportError
from custom_components.ukraine_alarm_pro.api.supervisor import (
    MODE_POLL,
    TransportSupervisor,
)
from custom_components.ukraine_alarm_pro.config_flow import _flatten
from custom_components.ukraine_alarm_pro.const import (
    DOMAIN,
    ISSUE_WS_UNAVAILABLE,
    STALE_AFTER_SECONDS,
)
from custom_components.ukraine_alarm_pro.coordinator import AlarmCoordinator
from custom_components.ukraine_alarm_pro.models import (
    Snapshot,
    ThreatLevel,
    parse_alert_payload,
    region_alerts,
    region_threat,
)

TREE = {
    "states": [
        {
            "regionId": "14",
            "regionName": "Сумська область",
            "regionChildIds": [
                {
                    "regionId": "114",
                    "regionName": "Сумський район",
                    "regionChildIds": [
                        {"regionId": "703", "regionName": "Сумська громада"}
                    ],
                }
            ],
        }
    ]
}

RAION_AIR = parse_alert_payload(
    {
        "alerts": [
            {
                "regionId": "114",
                "activeAlerts": [{"type": "AIR", "lastUpdate": "2026-07-25T06:00:00Z"}],
            }
        ]
    }
)

ENTRY_DATA = {
    "regions": {
        "14": {
            "name": "Сумська область",
            "ancestors": [],
            "descendants": ["114", "703"],
        }
    }
}


# --- alerts declared below the selected region -------------------------------


def test_region_threat_sees_descendant_alert():
    """An oblast is in alert when one of its raions is (live-verified gap)."""
    assert (
        region_threat(RAION_AIR, "14", [], ["114", "703"]) is ThreatLevel.AIR
    )
    # unchanged: ancestor inheritance and true all-clear
    assert region_threat(RAION_AIR, "703", ["114", "14"], []) is ThreatLevel.AIR
    assert region_threat(RAION_AIR, "99", [], []) is ThreatLevel.NONE


def test_region_alerts_deduplicates_repeated_alerts():
    snap = parse_alert_payload(
        {
            "alerts": [
                {
                    "regionId": "114",
                    "activeAlerts": [
                        {"type": "AIR", "lastUpdate": "2026-07-25T06:00:00Z"},
                        {"type": "AIR", "lastUpdate": "2026-07-25T06:00:00Z"},
                    ],
                }
            ]
        }
    )
    # the region is reachable both directly and as a descendant
    found = region_alerts(snap, "114", [], ["114"])
    assert len(found) == 1


def test_unrecognized_alert_type_warns_once(caplog):
    from custom_components.ukraine_alarm_pro import models

    models._WARNED_TYPES.discard("PLASMA")
    snap = parse_alert_payload(
        {"alerts": [{"regionId": "1", "activeAlerts": [{"type": "PLASMA"}]}]}
    )
    with caplog.at_level(logging.WARNING):
        assert region_threat(snap, "1") is ThreatLevel.UNKNOWN
        assert region_threat(snap, "1") is ThreatLevel.UNKNOWN
    assert sum("PLASMA" in rec.message for rec in caplog.records) == 1


# --- region tree -------------------------------------------------------------


def test_flatten_builds_descendants():
    flat = _flatten(TREE)
    assert flat["14"]["descendants"] == ["114", "703"]
    assert flat["114"]["descendants"] == ["703"]
    assert flat["703"]["descendants"] == []
    assert flat["703"]["ancestors"] == ["114", "14"]


def test_flatten_survives_a_self_referential_tree():
    node = {"regionId": "1", "regionName": "loop"}
    node["regionChildIds"] = [node]
    flat = _flatten({"states": [node]})
    assert list(flat) == ["1"]


# --- coordinator -------------------------------------------------------------


async def test_manual_refresh_returns_the_pushed_snapshot(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    coordinator = AlarmCoordinator(hass, entry, MagicMock())

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    coordinator.handle_snapshot(RAION_AIR)
    assert await coordinator._async_update_data() is RAION_AIR


async def test_coordinator_reports_staleness(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    coordinator = AlarmCoordinator(hass, entry, MagicMock())

    assert coordinator.is_stale is True  # nothing received yet
    coordinator.handle_snapshot(Snapshot())
    assert coordinator.is_stale is False
    coordinator.last_push = dt_util.utcnow() - timedelta(
        seconds=STALE_AFTER_SECONDS + 1
    )
    assert coordinator.is_stale is True


# --- supervisor --------------------------------------------------------------


class _StubWs:
    def __init__(self) -> None:
        self.closed = 0

    async def stream(self):
        while True:
            await asyncio.sleep(3600)
            yield Snapshot()

    async def close(self):
        self.closed += 1


async def test_start_uses_the_injected_task_factory():
    created: list[str] = []

    def factory(coro, name):
        created.append(name)
        return asyncio.get_running_loop().create_task(coro, name=name)

    sup = TransportSupervisor(ws=_StubWs(), poll=AsyncMock())
    await sup.start(factory)
    await asyncio.sleep(0)
    assert len(created) == 2  # transport loop + watchdog
    await sup.stop()


async def test_watchdog_restarts_a_silent_transport():
    ws = _StubWs()
    sup = TransportSupervisor(
        ws=ws, poll=AsyncMock(), stale_after=0.01, watchdog_interval=0.01
    )
    sup._emit(Snapshot())
    await sup.start()
    await asyncio.sleep(0.05)
    await sup.stop()
    assert ws.closed >= 2, "watchdog must drop the socket so _run reconnects"


async def test_watchdog_stays_quiet_before_the_first_snapshot():
    ws = _StubWs()
    sup = TransportSupervisor(
        ws=ws, poll=AsyncMock(), stale_after=0.01, watchdog_interval=0.01
    )
    await sup.start()
    await asyncio.sleep(0.05)
    await sup.stop()
    assert ws.closed == 1, "only stop() closes the socket while connecting"


async def test_stop_cancels_every_task():
    sup = TransportSupervisor(ws=_StubWs(), poll=AsyncMock())
    await sup.start()
    sup._set_mode(MODE_POLL)
    tasks = [sup._task, sup._poll_task, sup._watchdog_task]
    assert all(task is not None for task in tasks)
    await sup.stop()
    assert all(task.cancelled() or task.done() for task in tasks)
    assert sup._task is None and sup._poll_task is None
    assert sup._watchdog_task is None


# --- ws transport ------------------------------------------------------------


async def test_stream_reports_transport_error_when_the_socket_is_pulled():
    """close() clears self._ws; the read loop must not raise AttributeError."""
    from custom_components.ukraine_alarm_pro.api import ws as ws_mod

    class _Msg:
        type = ws_mod.aiohttp.WSMsgType.CLOSED
        data = ""

    fake_ws = MagicMock()
    fake_ws.closed = False
    fake_ws.send_str = AsyncMock()
    fake_ws.close = AsyncMock()

    transport = ws_mod.WsTransport(MagicMock())
    transport._session.ws_connect = AsyncMock(return_value=fake_ws)

    replies = [
        {"id": 1},
        {"id": 2},
        {"id": 3, "result": {"publications": []}},
    ]
    fake_ws.receive = AsyncMock(side_effect=[_Msg()])

    with patch.object(
        ws_mod.WsTransport, "_mint_token", AsyncMock(return_value=("t", "wss://x"))
    ), patch.object(ws_mod.WsTransport, "_recv_id", AsyncMock(side_effect=replies)):
        stream = transport.stream()
        with pytest.raises(TransportError):
            async for _ in stream:
                await transport.close()  # simulate the watchdog/unload path


# --- entities and issues -----------------------------------------------------


def _mock_supervisor():
    """Async mock whose @callback setters stay synchronous."""
    sup = AsyncMock()
    sup.mode = "websocket"
    sup.set_listener = MagicMock()
    sup.set_mode_listener = MagicMock()
    return sup


async def _setup(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, entry_id="hard020")
    entry.add_to_hass(hass)
    sup = _mock_supervisor()
    with patch(
        "custom_components.ukraine_alarm_pro.TransportSupervisor", return_value=sup
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, sup


async def test_diagnostic_entities_live_before_the_first_snapshot(
    hass: HomeAssistant, enable_custom_integrations
):
    await _setup(hass)
    assert hass.states.get("sensor.uap_transport").state == "websocket"
    assert hass.states.get("binary_sensor.uap_data_stale").state == "on"


async def test_oblast_entity_reacts_to_a_raion_alert(
    hass: HomeAssistant, enable_custom_integrations
):
    _, sup = await _setup(hass)
    push = sup.set_listener.call_args[0][0]
    push(RAION_AIR)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.uap_14_threat").state == "air"
    assert hass.states.get("binary_sensor.uap_14_alert").state == "on"
    assert hass.states.get("binary_sensor.uap_data_stale").state == "off"


async def test_polling_fallback_raises_and_clears_a_repair_issue(
    hass: HomeAssistant, enable_custom_integrations
):
    _, sup = await _setup(hass)
    on_mode = sup.set_mode_listener.call_args[0][0]
    registry = ir.async_get(hass)

    on_mode(MODE_POLL)
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, ISSUE_WS_UNAVAILABLE) is not None

    on_mode("websocket")
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, ISSUE_WS_UNAVAILABLE) is None


async def test_background_tasks_belong_to_the_entry(
    hass: HomeAssistant, enable_custom_integrations
):
    entry, sup = await _setup(hass)
    factory = sup.start.call_args[0][0]
    task = factory(asyncio.sleep(0), "probe")
    assert task in entry._background_tasks
    await task


async def test_diagnostics_dump_has_no_secrets(
    hass: HomeAssistant, enable_custom_integrations
):
    from custom_components.ukraine_alarm_pro.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry, sup = await _setup(hass)
    sup.set_listener.call_args[0][0](RAION_AIR)
    await hass.async_block_till_done()
    dump = await async_get_config_entry_diagnostics(hass, entry)
    assert dump["transport"]["mode"] == "websocket"
    assert dump["configured_regions"]["14"]["descendant_count"] == 2
    assert dump["active_alerts"] == {"114": ["AIR"]}


# --- options flow ------------------------------------------------------------


async def test_options_flow_replaces_the_monitored_regions(
    hass: HomeAssistant, enable_custom_integrations
):
    entry, _ = await _setup(hass)
    with patch(
        "custom_components.ukraine_alarm_pro.config_flow.async_fetch_regions",
        return_value=TREE,
    ), patch(
        "custom_components.ukraine_alarm_pro.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == "form"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"regions": ["703"]}
        )
        await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    regions = entry.data["regions"]
    assert list(regions) == ["703"]
    assert regions["703"]["ancestors"] == ["114", "14"]


async def test_options_flow_aborts_when_the_region_list_is_unreachable(
    hass: HomeAssistant, enable_custom_integrations
):
    entry, _ = await _setup(hass)
    with patch(
        "custom_components.ukraine_alarm_pro.config_flow.async_fetch_regions",
        side_effect=TransportError("down"),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "abort"
    assert result["reason"] == "cannot_connect"


async def test_second_entry_is_refused(hass: HomeAssistant, enable_custom_integrations):
    await _setup(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "single_instance_allowed"


# --- migration of entries created before descendants existed -----------------


async def test_setup_backfills_descendants_for_legacy_entries(
    hass: HomeAssistant, enable_custom_integrations
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"regions": {"14": {"name": "Сумська область", "ancestors": []}}},
        entry_id="legacy",
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.ukraine_alarm_pro.TransportSupervisor",
        return_value=_mock_supervisor(),
    ), patch(
        "custom_components.ukraine_alarm_pro.config_flow.async_fetch_regions",
        return_value=TREE,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.data["regions"]["14"]["descendants"] == ["114", "703"]


async def test_setup_survives_an_unreachable_region_tree(
    hass: HomeAssistant, enable_custom_integrations
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"regions": {"14": {"name": "Сумська область", "ancestors": []}}},
        entry_id="legacy2",
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.ukraine_alarm_pro.TransportSupervisor",
        return_value=_mock_supervisor(),
    ), patch(
        "custom_components.ukraine_alarm_pro.config_flow.async_fetch_regions",
        side_effect=TransportError("down"),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert "descendants" not in entry.data["regions"]["14"]
    assert hass.states.get("sensor.uap_14_threat") is not None


async def test_staleness_entities_tick_without_new_data(
    hass: HomeAssistant, enable_custom_integrations
):
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    entry, sup = await _setup(hass)
    sup.set_listener.call_args[0][0](RAION_AIR)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.uap_data_stale").state == "off"

    # no new snapshot arrives; only the clock moves on
    entry.runtime_data.last_push = dt_util.utcnow() - timedelta(
        seconds=STALE_AFTER_SECONDS + 120
    )
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.uap_data_stale").state == "on"


# --- adversarial pass over the 0.2.0 diff ------------------------------------


async def test_backfill_does_not_block_setup(
    hass: HomeAssistant, enable_custom_integrations
):
    """A slow region endpoint must not add its timeout to every restart."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"regions": {"14": {"name": "Сумська область", "ancestors": []}}},
        entry_id="slowtree",
    )
    entry.add_to_hass(hass)
    released = asyncio.Event()

    async def _slow_fetch(_session):
        await released.wait()
        return TREE

    with patch(
        "custom_components.ukraine_alarm_pro.TransportSupervisor",
        return_value=_mock_supervisor(),
    ), patch(
        "custom_components.ukraine_alarm_pro.config_flow.async_fetch_regions",
        _slow_fetch,
    ):
        # a blocking backfill would hang here until the fetch returns
        assert await asyncio.wait_for(
            hass.config_entries.async_setup(entry.entry_id), timeout=5
        )
        assert hass.states.get("sensor.uap_14_threat") is not None
        released.set()
        await hass.async_block_till_done()

    assert entry.data["regions"]["14"]["descendants"] == ["114", "703"]


async def test_watchdog_leaves_the_socket_alone_in_poll_mode():
    ws = _StubWs()
    sup = TransportSupervisor(
        ws=ws, poll=AsyncMock(), stale_after=0.01, watchdog_interval=0.01
    )
    sup._emit(Snapshot())
    sup._set_mode(MODE_POLL)
    await sup.start()
    await asyncio.sleep(0.05)
    closes_during_run = ws.closed
    await sup.stop()
    assert closes_during_run == 0, "closing the WS does not restart polling"


async def test_region_attributes_are_capped(
    hass: HomeAssistant, enable_custom_integrations
):
    from custom_components.ukraine_alarm_pro.sensor import MAX_LISTED_ALERTS

    total = MAX_LISTED_ALERTS + 5
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "regions": {
                "14": {
                    "name": "Сумська область",
                    "ancestors": [],
                    "descendants": [str(i) for i in range(total)],
                }
            }
        },
        entry_id="bigoblast",
    )
    entry.add_to_hass(hass)
    sup = _mock_supervisor()
    with patch(
        "custom_components.ukraine_alarm_pro.TransportSupervisor", return_value=sup
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    sup.set_listener.call_args[0][0](
        parse_alert_payload(
            {
                "alerts": [
                    {
                        "regionId": str(i),
                        "activeAlerts": [{"type": "AIR", "lastUpdate": "t"}],
                    }
                    for i in range(total)
                ]
            }
        )
    )
    await hass.async_block_till_done()
    state = hass.states.get("sensor.uap_14_threat")
    assert state.state == "air"
    assert state.attributes["active_alert_count"] == total
    assert len(state.attributes["active_alerts"]) == MAX_LISTED_ALERTS
