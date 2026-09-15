"""Payload integrity — a damaged record must never read as an all-clear.

Both feeds send full snapshots, so a region missing from a *valid* snapshot is
clear. A record that is present but unusable is a different case: before this
it was skipped or its `activeAlerts` replaced with `[]`, which cleared every
region it covered.
"""

import asyncio

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from custom_components.ukraine_alarm_pro.api.errors import TransportError
from custom_components.ukraine_alarm_pro.api.poll import PollTransport
from custom_components.ukraine_alarm_pro.api.supervisor import TransportSupervisor
from custom_components.ukraine_alarm_pro.api.ws import _parse
from custom_components.ukraine_alarm_pro.models import (
    ThreatLevel,
    parse_alert_payload,
    region_alerts,
    region_threat,
)

AIR = {"regionId": "31", "activeAlerts": [{"type": "AIR", "lastUpdate": "2026-09-15T06:00:00Z"}]}
CLEAR = {"regionId": "31", "activeAlerts": []}

DAMAGED = [
    pytest.param([{"regionId": "31"}], id="missing-activeAlerts"),
    pytest.param([{"regionId": "31", "activeAlerts": {}}], id="dict-activeAlerts"),
    pytest.param([{"regionId": "31", "activeAlerts": None}], id="null-activeAlerts"),
    pytest.param([None], id="null-record"),
    pytest.param(["junk"], id="string-record"),
    pytest.param([AIR, {"regionId": "703"}], id="valid-plus-damaged"),
    pytest.param([{"regionId": "31", "activeAlerts": [None]}], id="null-alert"),
    pytest.param([{"regionId": "31", "activeAlerts": [{"type": "AIR"}, 5]}], id="int-alert"),
    pytest.param([{"regionId": None, "activeAlerts": []}], id="null-region-id"),
    pytest.param([{"activeAlerts": []}], id="missing-region-id"),
    pytest.param([{"regionId": "", "activeAlerts": []}], id="empty-region-id"),
    pytest.param([{"regionId": True, "activeAlerts": []}], id="bool-region-id"),
    pytest.param([{"regionId": ["31"], "activeAlerts": []}], id="list-region-id"),
    pytest.param(
        [{"regionId": "31", "activeAlerts": [{"type": ["AIR"]}]}], id="list-type"
    ),
    pytest.param(
        [{"regionId": "31", "activeAlerts": [{"type": {"x": 1}}]}], id="dict-type"
    ),
    pytest.param(
        [{"regionId": "31", "activeAlerts": [{"type": "AIR", "regionId": ["9"]}]}],
        id="list-declaring-region",
    ),
]


@pytest.mark.parametrize("raw", DAMAGED)
def test_damaged_record_rejects_the_whole_snapshot(raw):
    with pytest.raises(ValueError):
        parse_alert_payload(raw)
    with pytest.raises(ValueError):
        parse_alert_payload({"alerts": raw})


@pytest.mark.parametrize("raw", DAMAGED)
def test_ws_path_reports_damaged_record_as_transport_error(raw):
    with pytest.raises(TransportError):
        _parse({"alerts": raw})


def test_error_message_does_not_echo_the_payload():
    secret = "x" * 50
    with pytest.raises(ValueError) as err:
        parse_alert_payload([{"regionId": "31", "activeAlerts": secret}])
    assert secret not in str(err.value)


@pytest.mark.parametrize("raw", [[], {"alerts": []}, [CLEAR]])
def test_valid_clear_stays_valid(raw):
    snap = parse_alert_payload(raw)
    assert region_threat(snap, "31") is ThreatLevel.NONE


def test_numeric_region_ids_are_normalized():
    snap = parse_alert_payload(
        [{"regionId": 31, "activeAlerts": [{"type": "AIR", "regionId": 31}]}]
    )
    assert snap.regions["31"][0].region_id == "31"


@pytest.mark.parametrize("type_", [None, "", "  "])
def test_missing_or_empty_type_stays_an_active_threat(type_):
    alert = {"lastUpdate": "2026-09-15T06:00:00Z"}
    if type_ is not None:
        alert["type"] = type_
    snap = parse_alert_payload([{"regionId": "31", "activeAlerts": [alert]}])
    assert region_threat(snap, "31") is ThreatLevel.UNKNOWN


def test_unknown_type_stays_unrecognized():
    snap = parse_alert_payload(
        [{"regionId": "31", "activeAlerts": [{"type": "PLASMA", "lastUpdate": "x"}]}]
    )
    assert region_threat(snap, "31") is ThreatLevel.UNKNOWN


@pytest.mark.parametrize("stamp", [None, 1726380000, ["2026"], {"t": 1}, "not-a-date"])
def test_unusable_declaration_time_keeps_the_alert_without_crashing(stamp):
    alert = {"type": "AIR"}
    if stamp is not None:
        alert["lastUpdate"] = stamp
    snap = parse_alert_payload(
        [
            {
                "regionId": "31",
                "activeAlerts": [
                    alert,
                    {"type": "ARTILLERY", "lastUpdate": "2026-09-15T06:00:00Z"},
                ],
            }
        ]
    )
    # Sorting mixes the unusable stamp with a real one: must not raise.
    found = region_alerts(snap, "31")
    assert {a.type for a in found} == {"AIR", "ARTILLERY"}
    assert region_threat(snap, "31") is ThreatLevel.ARTILLERY


def test_malformed_levels_keep_the_air_alert():
    snap = parse_alert_payload(
        [
            {
                "regionId": "31",
                "activeAlerts": [
                    {"type": "AIR", "lastUpdate": "x", "activeAlertLevels": "junk"}
                ],
            }
        ]
    )
    assert region_threat(snap, "31") is ThreatLevel.AIR


class _ScriptedWs:
    """Publishes the given raw payloads through the real WS parse path."""

    def __init__(self, payloads):
        self._payloads = list(payloads)

    async def stream(self):
        while self._payloads:
            yield _parse(self._payloads.pop(0))
        await asyncio.sleep(3600)

    async def close(self):
        pass


async def test_damaged_ws_publication_keeps_the_last_alert_and_its_clock():
    received = []
    sup = TransportSupervisor(
        ws=_ScriptedWs([{"alerts": [AIR]}, {"alerts": [{"regionId": "31"}]}]),
        poll=None,
        seed_delay=3600,
        watchdog_interval=3600,
        ws_retry_delay=3600,
    )
    sup.set_listener(received.append)
    await sup.start()
    await asyncio.sleep(0.05)
    try:
        assert len(received) == 1
        assert region_threat(received[-1], "31") is ThreatLevel.AIR
        # The transport task survived the damaged publication.
        assert not sup._task.done()
    finally:
        await sup.stop()


async def test_poll_path_rejects_damaged_payload_then_accepts_a_real_clear():
    bodies = [[AIR], [{"regionId": "31", "activeAlerts": None}], [CLEAR]]

    async def handler(request):
        return web.json_response(bodies.pop(0))

    app = web.Application()
    app.router.add_get("/alerts", handler)
    server = TestServer(app)
    await server.start_server()
    try:
        async with ClientSession() as session:
            poll = PollTransport(session, base_url=str(server.make_url("")).rstrip("/"))
            snaps = []
            sup = TransportSupervisor(ws=None, poll=poll)
            sup.set_listener(snaps.append)
            for _ in range(3):
                try:
                    sup._emit(await poll.fetch())
                except TransportError:
                    after_air = sup.seconds_since_snapshot
            assert after_air is not None
            assert [region_threat(s, "31") for s in snaps] == [
                ThreatLevel.AIR,
                ThreatLevel.NONE,
            ]
    finally:
        await server.close()
