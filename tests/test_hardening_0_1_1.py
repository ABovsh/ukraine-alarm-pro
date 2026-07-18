"""Hardening round 2026-07-18: parse-error resilience, supervisor survival,
state-string collision, translations, single-instance guard."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ukraine_alarm_pro.api.errors import TransportError
from custom_components.ukraine_alarm_pro.api.supervisor import (
    MODE_POLL,
    TransportSupervisor,
)
from custom_components.ukraine_alarm_pro.models import (
    Alert,
    ThreatLevel,
    parse_alert_payload,
)

COMPONENT = Path(__file__).parent.parent / "custom_components" / "ukraine_alarm_pro"


# --- A-F01: malformed payloads must become TransportError / be skipped ---


def test_parse_payload_skips_non_dict_entries():
    snap = parse_alert_payload([None, "junk", {"regionId": 7, "activeAlerts": [{"type": "AIR"}]}])
    assert list(snap.regions) == ["7"]


def test_parse_payload_skips_non_dict_alerts():
    snap = parse_alert_payload([{"regionId": 7, "activeAlerts": [None, {"type": "AIR"}]}])
    assert [a.type for a in snap.regions["7"]] == ["AIR"]


def test_parse_payload_non_list_items_gives_empty_snapshot():
    assert parse_alert_payload({"alerts": "garbage"}).regions == {}


class _FakeMsg:
    def __init__(self, data, type_=None):
        import aiohttp

        self.type = type_ or aiohttp.WSMsgType.TEXT
        self.data = data


async def test_ws_malformed_json_frame_raises_transport_error():
    from custom_components.ukraine_alarm_pro.api.ws import WsTransport

    session = MagicMock()
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = AsyncMock(
        return_value='centrifugo-token" value="t"/> centrifugo-url" value="wss://x"/>'
    )
    session.get = AsyncMock(return_value=resp)
    ws = MagicMock()
    ws.closed = False
    ws.close = AsyncMock()
    ws.send_str = AsyncMock()
    ws.receive = AsyncMock(return_value=_FakeMsg("NOT JSON {"))
    session.ws_connect = AsyncMock(return_value=ws)

    transport = WsTransport(session)
    with pytest.raises(TransportError):
        async for _ in transport.stream():
            pass


async def test_ws_malformed_push_frame_raises_transport_error():
    from custom_components.ukraine_alarm_pro.api.ws import WsTransport

    session = MagicMock()
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = AsyncMock(
        return_value='centrifugo-token" value="t"/> centrifugo-url" value="wss://x"/>'
    )
    session.get = AsyncMock(return_value=resp)
    ws = MagicMock()
    ws.closed = False
    ws.close = AsyncMock()
    ws.send_str = AsyncMock()
    handshake = [
        _FakeMsg(json.dumps({"id": 1})),
        _FakeMsg(json.dumps({"id": 2})),
        _FakeMsg(json.dumps({"id": 3, "result": {"publications": []}})),
        _FakeMsg("BROKEN {"),
    ]
    ws.receive = AsyncMock(side_effect=handshake)
    session.ws_connect = AsyncMock(return_value=ws)

    transport = WsTransport(session)
    with pytest.raises(TransportError):
        async for _ in transport.stream():
            pass


# --- A-F02: supervisor must survive non-TransportError exceptions ---


async def test_supervisor_survives_unexpected_exception_and_degrades():
    class ExplodingWs:
        async def close(self):
            pass

        def stream(self):
            raise RuntimeError("boom")  # not a TransportError

    poll = MagicMock()
    poll.fetch = AsyncMock(side_effect=TransportError("down"))
    sup = TransportSupervisor(
        ws=ExplodingWs(),
        poll=poll,
        max_ws_failures=2,
        ws_retry_delay=0.01,
        ws_probe_interval=0.01,
        poll_interval=0.01,
    )
    await sup.start()
    await asyncio.sleep(0.2)
    assert not sup._task.done(), "supervisor task must not die on unexpected exceptions"
    assert sup.mode == MODE_POLL
    await sup.stop()


async def test_poll_loop_survives_unexpected_exception():
    poll = MagicMock()
    poll.fetch = AsyncMock(side_effect=RuntimeError("boom"))
    sup = TransportSupervisor(ws=MagicMock(), poll=poll, poll_interval=0.01)
    sup._poll_task = asyncio.get_event_loop().create_task(sup._poll_loop())
    await asyncio.sleep(0.1)
    assert not sup._poll_task.done(), "poll loop must not die on unexpected exceptions"
    sup._poll_task.cancel()
    try:
        await sup._poll_task
    except asyncio.CancelledError:
        pass


# --- B-F01: state string must not collide with HA STATE_UNKNOWN ---


def test_unknown_threat_value_does_not_collide_with_ha_state_unknown():
    assert ThreatLevel.UNKNOWN.value != "unknown"
    assert Alert(type="WEIRD_NEW_TYPE", last_update="").threat is ThreatLevel.UNKNOWN


# --- B-F02: ENUM state translations must exist for every threat level ---


@pytest.mark.parametrize("fname", ["strings.json", "translations/en.json"])
def test_threat_state_translations_cover_all_levels(fname):
    data = json.loads((COMPONENT / fname).read_text())
    states = data["entity"]["sensor"]["threat"]["state"]
    assert set(states) == {level.value for level in ThreatLevel}


# --- single-instance guard ---


async def test_config_flow_aborts_second_instance(monkeypatch):
    from custom_components.ukraine_alarm_pro.config_flow import UkraineAlarmProConfigFlow

    flow = UkraineAlarmProConfigFlow()
    monkeypatch.setattr(flow, "_async_current_entries", lambda: [MagicMock()])
    result = await flow.async_step_user()
    assert result["type"] == "abort"
    assert result["reason"] == "single_instance_allowed"
