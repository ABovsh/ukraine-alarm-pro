"""Audit round 2026-09-19: batched WS frames, damaged stores, removal, empty choice."""

import asyncio
import json
from datetime import timedelta
from unittest.mock import patch

from aiohttp import ClientSession, web
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from test_alert_history import FakeStore, _hist
from test_entities import _setup
from test_features_0_7_0 import _setup as _setup_restorable
from test_features_0_7_0 import _stored
from test_hardening_0_2_0 import TREE
from test_ws_transport import PUSH_DATA, SNAPSHOT_DATA, FakeAlarmServer

from custom_components.ukraine_alarm_pro.api.errors import TransportError
from custom_components.ukraine_alarm_pro.api.ws import WsTransport
from custom_components.ukraine_alarm_pro.const import DOMAIN, STORAGE_KEY

# --- WebSocket framing -------------------------------------------------------


class BatchingServer(FakeAlarmServer):
    """Sends queued publications the way Centrifugo batches them: one frame,
    replies separated by newlines (centrifuge-js 2.8.5 `decodeReplies` splits
    every frame on "\\n", which is what the map page itself runs)."""

    async def _pump(self, ws):
        batch = []
        while True:
            data = await self.pushes.get()
            if data is None:
                return
            if isinstance(data, str):
                await ws.send_str(data)
                continue
            batch.append(
                json.dumps({"result": {"channel": "updateMap", "data": {"data": data}}})
            )
            if len(batch) == 2:
                await ws.send_str("\n".join(batch))
                batch = []


async def test_ws_reads_every_publication_of_a_batched_frame():
    srv = await BatchingServer().start()
    try:
        async with ClientSession() as session:
            t = WsTransport(session, map_url=srv.page_url)
            gen = t.stream()
            await asyncio.wait_for(anext(gen), timeout=5)  # history
            await srv.pushes.put(SNAPSHOT_DATA)
            await srv.pushes.put(PUSH_DATA)
            first = await asyncio.wait_for(anext(gen), timeout=5)
            second = await asyncio.wait_for(anext(gen), timeout=5)
            assert "703" in first.regions
            assert "31" in second.regions
            await t.close()
    finally:
        await srv.close()


async def test_ws_non_object_reply_is_a_transport_error_and_closes_the_socket():
    srv = await BatchingServer().start()
    try:
        async with ClientSession() as session:
            t = WsTransport(session, map_url=srv.page_url)
            gen = t.stream()
            await asyncio.wait_for(anext(gen), timeout=5)
            socket = t._ws
            await srv.pushes.put("[1, 2]")
            try:
                await asyncio.wait_for(anext(gen), timeout=5)
            except TransportError:
                pass
            else:
                raise AssertionError("a non-object reply must raise TransportError")
            assert socket.closed
    finally:
        await srv.close()


# --- damaged stores ----------------------------------------------------------


async def test_journal_with_a_zoneless_stamp_starts_clean_instead_of_crashing():
    naive = "2026-09-15T08:00:00"
    episode = {
        "episode_id": "x",
        "region_id": "31",
        "observed_started_at": naive,
        "declared_started_at": None,
        "observed_cleared_at": naive,
        "active_types_seen": ["air"],
        "maximum_air_level": "none",
        "had_gap": False,
        "source_start_known": True,
        "start_origin": "live",
    }
    history, _ = _hist(FakeStore({"episodes": [episode], "active": {}}))
    await history.async_load()
    assert history.history("31", 20) == []


async def test_a_zoneless_saved_at_is_ignored_not_fatal(
    hass: HomeAssistant, enable_custom_integrations, hass_storage
):
    hass_storage[STORAGE_KEY] = _stored("2026-09-15T08:00:00")
    entry, _ = await _setup_restorable(hass)
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert hass.states.get("sensor.uap_20_threat").state == "unavailable"


# --- entry removal -----------------------------------------------------------


async def test_removing_the_entry_deletes_its_stored_journal_and_map(
    hass: HomeAssistant, enable_custom_integrations, hass_storage
):
    hass_storage[STORAGE_KEY] = _stored(
        (dt_util.utcnow() - timedelta(minutes=5)).isoformat()
    )
    entry, _ = await _setup_restorable(hass)
    await entry.runtime_data.async_flush_history()
    history_key = f"{DOMAIN}.history.{entry.entry_id}"
    assert history_key in hass_storage

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert history_key not in hass_storage
    assert STORAGE_KEY not in hass_storage


# --- empty region choice -----------------------------------------------------


async def test_setup_refuses_an_empty_region_choice(
    hass: HomeAssistant, enable_custom_integrations
):
    with patch(
        "custom_components.ukraine_alarm_pro.config_flow.async_fetch_regions",
        return_value=TREE,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"regions": []}
        )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "no_regions"}


async def test_configure_refuses_to_drop_every_region(
    hass: HomeAssistant, enable_custom_integrations
):
    entry, _ = await _setup(hass)
    before = dict(entry.data["regions"])
    with patch(
        "custom_components.ukraine_alarm_pro.config_flow.async_fetch_regions",
        return_value=TREE,
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"regions": []}
        )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "no_regions"}
    assert entry.data["regions"] == before



class ReplyBatchingServer(FakeAlarmServer):
    """Batches a live publication into the same frame as the history reply,
    and answers history with `result: null`."""

    async def ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            d = json.loads(msg.data)
            if "method" not in d or d["method"] == 1:  # connect, subscribe
                await ws.send_str(json.dumps({"id": d["id"], "result": {}}))
            elif d["method"] == 6:
                publication = {"result": {"channel": "updateMap", "data": {"data": PUSH_DATA}}}
                await ws.send_str(
                    json.dumps({"id": d["id"], "result": None})
                    + "\n"
                    + json.dumps(publication)
                )
        return ws


async def test_ws_keeps_a_publication_batched_with_a_command_reply():
    srv = await ReplyBatchingServer().start()
    try:
        async with ClientSession() as session:
            t = WsTransport(session, map_url=srv.page_url)
            snap = await asyncio.wait_for(anext(t.stream()), timeout=5)
            assert "31" in snap.regions
            await t.close()
    finally:
        await srv.close()
