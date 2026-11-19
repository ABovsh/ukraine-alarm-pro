"""N2: the official map's HTTP snapshot is the first fallback, siren.pp.ua the second.

The fixture is a real `mapUpdate` answer (17.11.2026, 29 regions under alert).
"""

import json
import types
from pathlib import Path

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from custom_components.ukraine_alarm_pro.api import poll as poll_mod
from custom_components.ukraine_alarm_pro.api.errors import RateLimited, TransportError
from custom_components.ukraine_alarm_pro.api.poll import (
    SOURCE_OFFICIAL,
    SOURCE_SIREN,
    ChainedPollTransport,
    OfficialPollTransport,
    PollTransport,
)
from custom_components.ukraine_alarm_pro.models import parse_alert_payload

OFFICIAL = json.loads(
    (Path(__file__).parent / "fixtures" / "map_update_official.json").read_text()
)
THREATS = {
    **OFFICIAL,
    "migAlerts": [],
    "mapNotifications": {"hasMig": True, "hasBallistics": True},
}
SIREN = [
    {
        "regionId": "31",
        "regionType": "State",
        "activeAlerts": [{"type": "AIR", "lastUpdate": "2026-07-17T06:00:00Z"}],
    }
]


async def _serve(routes):
    """One handler per path; each answers from its list of (status, body, headers)."""
    app = web.Application()
    seen = {path: [] for path in routes}

    def handler_for(path):
        async def handler(request):
            seen[path].append(dict(request.headers))
            answers = routes[path]
            status, body, headers = answers.pop(0) if len(answers) > 1 else answers[0]
            if status == 304:
                return web.Response(status=304, headers=headers)
            if isinstance(body, str):
                return web.Response(status=status, text=body, headers=headers)
            return web.json_response(body, status=status, headers=headers)

        return handler

    for path in routes:
        app.router.add_get(path, handler_for(path))
    server = TestServer(app)
    await server.start_server()
    return server, seen


def _url(server, path=""):
    return str(server.make_url(path)).rstrip("/")


# --- the official snapshot -------------------------------------------------


async def test_official_parses_like_the_websocket_publication():
    server, _ = await _serve({"/mapUpdate": [(200, OFFICIAL, {})]})
    try:
        async with ClientSession() as session:
            snap = await OfficialPollTransport(session, _url(server, "/mapUpdate")).fetch()
    finally:
        await server.close()
    ws_shape = parse_alert_payload({"alerts": OFFICIAL["alerts"]})
    assert snap.active == ws_shape.active
    assert snap.signature == ws_shape.signature
    assert len(snap.regions) == 29


async def test_official_never_carries_country_data():
    server, _ = await _serve({"/mapUpdate": [(200, THREATS, {})]})
    try:
        async with ClientSession() as session:
            snap = await OfficialPollTransport(session, _url(server, "/mapUpdate")).fetch()
    finally:
        await server.close()
    assert snap.country is None
    assert snap.mig is None


@pytest.mark.parametrize(
    "body",
    [
        [],  # the siren shape, not the map's
        {"alarms": []},  # renamed key
        {"alerts": {}},
        {"alerts": [{"regionId": "31", "activeAlerts": "AIR"}]},  # damaged record
        "<html>maintenance</html>",
    ],
)
async def test_a_changed_or_damaged_official_answer_is_an_error(body):
    server, _ = await _serve({"/mapUpdate": [(200, body, {})]})
    try:
        async with ClientSession() as session:
            with pytest.raises(TransportError):
                await OfficialPollTransport(session, _url(server, "/mapUpdate")).fetch()
    finally:
        await server.close()


@pytest.mark.parametrize("status", [429, 503])
async def test_official_rate_limit_carries_retry_after(status):
    server, _ = await _serve({"/mapUpdate": [(status, {}, {"Retry-After": "120"})]})
    try:
        async with ClientSession() as session:
            transport = OfficialPollTransport(session, _url(server, "/mapUpdate"))
            with pytest.raises(RateLimited) as err:
                await transport.fetch()
            assert err.value.retry_after == 120
            # Inside the window no request is made at all.
            with pytest.raises(RateLimited):
                await transport.fetch()
    finally:
        await server.close()


# --- siren.pp.ua conditional requests --------------------------------------


async def test_siren_304_returns_the_previous_snapshot():
    server, seen = await _serve(
        {"/alerts": [(200, SIREN, {"ETag": '"v1"'}), (304, None, {"ETag": '"v1"'})]}
    )
    try:
        async with ClientSession() as session:
            transport = PollTransport(session, base_url=_url(server))
            first = await transport.fetch()
            second = await transport.fetch()
    finally:
        await server.close()
    assert "If-None-Match" not in seen["/alerts"][0]
    assert seen["/alerts"][1]["If-None-Match"] == '"v1"'
    assert second is first


async def test_siren_without_etag_sends_no_condition():
    server, seen = await _serve({"/alerts": [(200, SIREN, {})]})
    try:
        async with ClientSession() as session:
            transport = PollTransport(session, base_url=_url(server))
            await transport.fetch()
            await transport.fetch()
    finally:
        await server.close()
    assert all("If-None-Match" not in headers for headers in seen["/alerts"])


async def test_official_sends_no_condition():
    server, seen = await _serve({"/mapUpdate": [(200, OFFICIAL, {"ETag": '"x"'})]})
    try:
        async with ClientSession() as session:
            transport = OfficialPollTransport(session, _url(server, "/mapUpdate"))
            await transport.fetch()
            await transport.fetch()
    finally:
        await server.close()
    assert all("If-None-Match" not in headers for headers in seen["/mapUpdate"])


# --- the chain ---------------------------------------------------------------


class Source:
    def __init__(self, source, *outcomes):
        self.source = source
        self.outcomes = list(outcomes)
        self.calls = 0

    async def fetch(self):
        self.calls += 1
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


OK_OFFICIAL = parse_alert_payload({"alerts": OFFICIAL["alerts"]})
OK_SIREN = parse_alert_payload(SIREN)


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(poll_mod, "time", types.SimpleNamespace(monotonic=lambda: now[0]))
    return now


async def test_the_official_source_comes_first(clock):
    official, siren = Source(SOURCE_OFFICIAL, OK_OFFICIAL), Source(SOURCE_SIREN, OK_SIREN)
    chain = ChainedPollTransport([official, siren])
    assert await chain.fetch() is OK_OFFICIAL
    assert chain.source == SOURCE_OFFICIAL
    assert siren.calls == 0


async def test_one_failure_does_not_switch(clock):
    official = Source(SOURCE_OFFICIAL, TransportError("x"), OK_OFFICIAL)
    siren = Source(SOURCE_SIREN, OK_SIREN)
    chain = ChainedPollTransport([official, siren])
    with pytest.raises(TransportError):
        await chain.fetch()
    assert await chain.fetch() is OK_OFFICIAL
    assert siren.calls == 0
    assert chain.source == SOURCE_OFFICIAL


async def test_two_failures_in_a_row_switch_at_once(clock):
    official = Source(SOURCE_OFFICIAL, TransportError("x"))
    siren = Source(SOURCE_SIREN, OK_SIREN)
    switches = []
    chain = ChainedPollTransport([official, siren])
    chain.on_switch = lambda: switches.append(chain.source)
    with pytest.raises(TransportError):
        await chain.fetch()
    assert await chain.fetch() is OK_SIREN
    assert chain.source == SOURCE_SIREN
    assert switches == [SOURCE_SIREN]
    # Sticky: no request-by-request alternation.
    for _ in range(5):
        assert await chain.fetch() is OK_SIREN
    assert official.calls == 2


async def test_a_rate_limit_switches_at_once(clock):
    official = Source(SOURCE_OFFICIAL, RateLimited(60))
    siren = Source(SOURCE_SIREN, OK_SIREN)
    chain = ChainedPollTransport([official, siren])
    assert await chain.fetch() is OK_SIREN
    assert chain.source == SOURCE_SIREN


async def test_the_preferred_source_returns_only_after_ten_minutes_and_a_good_probe(clock):
    official = Source(SOURCE_OFFICIAL, RateLimited(60), TransportError("still"), OK_OFFICIAL)
    siren = Source(SOURCE_SIREN, OK_SIREN)
    chain = ChainedPollTransport([official, siren])
    assert await chain.fetch() is OK_SIREN
    clock[0] += 599
    assert await chain.fetch() is OK_SIREN
    assert official.calls == 1
    clock[0] += 1
    # A failed probe: the current source answers this request.
    assert await chain.fetch() is OK_SIREN
    assert official.calls == 2
    assert chain.source == SOURCE_SIREN
    clock[0] += 300
    assert await chain.fetch() is OK_SIREN
    assert official.calls == 2
    clock[0] += 300
    assert await chain.fetch() is OK_OFFICIAL
    assert chain.source == SOURCE_OFFICIAL


async def test_the_last_source_failing_keeps_it_and_raises(clock):
    official = Source(SOURCE_OFFICIAL, RateLimited(60))
    siren = Source(SOURCE_SIREN, TransportError("down"))
    chain = ChainedPollTransport([official, siren])
    with pytest.raises(TransportError):
        await chain.fetch()
    with pytest.raises(TransportError):
        await chain.fetch()
    assert chain.source == SOURCE_SIREN


@pytest.mark.parametrize("official_retry", [60, 1800])
async def test_siren_retry_after_does_not_delay_the_preferred_probe(clock, official_retry):
    """A source's cooldown must not suspend the whole chain's recovery."""
    from unittest.mock import AsyncMock

    from custom_components.ukraine_alarm_pro.api.supervisor import TransportSupervisor

    server, seen = await _serve({
        "/mapUpdate": [
            (503, {}, {"Retry-After": str(official_retry)}),
            (200, OFFICIAL, {}),
        ],
        "/alerts": [(429, {}, {"Retry-After": "3600"})],
    })
    try:
        async with ClientSession() as session:
            chain = ChainedPollTransport([
                OfficialPollTransport(session, _url(server, "/mapUpdate")),
                PollTransport(session, base_url=_url(server)),
            ])
            supervisor = TransportSupervisor(ws=AsyncMock(), poll=chain)
            assert await supervisor._fetch_poll("seed") is None
            # The supervisor uses this pause for both seed and fallback polling.
            assert supervisor._next_seed_delay(0) == 600
            assert [len(seen[path]) for path in ("/mapUpdate", "/alerts")] == [1, 1]
            clock[0] += 300
            assert await supervisor._fetch_poll("cross-check") is None
            assert supervisor._poll_retry_after == 300
            assert [len(seen[path]) for path in ("/mapUpdate", "/alerts")] == [1, 1]
            clock[0] += 300
            snapshot = await supervisor._fetch_poll("seed")
            if official_retry > 600:
                # Waking to probe must still respect each server's own cooldown.
                assert snapshot is None
                assert supervisor._next_seed_delay(1) == 600
                assert len(seen["/mapUpdate"]) == 1
                clock[0] += official_retry - 600
                snapshot = await supervisor._fetch_poll("seed")
            assert snapshot.signature == OK_OFFICIAL.signature
            assert chain.source == SOURCE_OFFICIAL
            assert [len(seen[path]) for path in ("/mapUpdate", "/alerts")] == [2, 1]
    finally:
        await server.close()


@pytest.mark.parametrize("single_source", [False, True])
async def test_a_short_or_single_source_cooldown_is_preserved(clock, single_source):
    siren = Source(SOURCE_SIREN, RateLimited(60 if not single_source else 3600))
    sources = [siren] if single_source else [Source(SOURCE_OFFICIAL, RateLimited(60)), siren]
    chain = ChainedPollTransport(sources)
    with pytest.raises(RateLimited) as err:
        await chain.fetch()
    assert err.value.retry_after == (3600 if single_source else 60)


# --- wiring and entities -----------------------------------------------------


async def test_setup_chains_official_then_siren(hass, enable_custom_integrations):
    from unittest.mock import patch

    with patch("custom_components.ukraine_alarm_pro.TransportSupervisor") as cls:
        cls.return_value.mode = "websocket"
        await _setup_with(hass, cls)
    chain = cls.call_args.kwargs["poll"]
    assert isinstance(chain, ChainedPollTransport)
    assert [s.source for s in chain._sources] == [SOURCE_OFFICIAL, SOURCE_SIREN]
    assert chain.on_switch is not None


async def _setup_with(hass, cls):
    from unittest.mock import MagicMock

    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from test_entities import ENTRY_DATA

    from custom_components.ukraine_alarm_pro.const import DOMAIN

    sup = cls.return_value
    sup.start = _noop
    sup.stop = _noop
    sup.set_listener = MagicMock()
    sup.set_mode_listener = MagicMock()
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, entry_id="test1")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _noop(*_args, **_kwargs):
    return None


async def test_transport_sensor_names_the_source(hass, enable_custom_integrations):
    from test_entities import _setup

    entry, _push = await _setup(hass)
    state = hass.states.get("sensor.uap_transport")
    assert (state.state, state.attributes["source"]) == ("websocket", "websocket")
    sup = entry.runtime_data.supervisor
    sup.mode = "polling"
    sup.poll_source = SOURCE_OFFICIAL
    entry.runtime_data.handle_mode_change("polling")
    await hass.async_block_till_done()
    state = hass.states.get("sensor.uap_transport")
    assert (state.state, state.attributes["source"]) == ("polling", SOURCE_OFFICIAL)


async def test_an_http_snapshot_keeps_the_websocket_country_data(
    hass, enable_custom_integrations
):
    from test_country_threats import _feed
    from test_entities import _setup

    _entry, push = await _setup(hass)
    push(parse_alert_payload(_feed(hasBallistics=True, lastBallisticsUpdateTime="2026-11-17T18:00:00Z")))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.uap_ballistics").state == "active"
    official = OfficialPollTransport(None)._parse(THREATS | {"mapNotifications": {}})
    push(official)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.uap_ballistics").state == "active"


async def test_unconditional_304_cannot_refresh_an_unvalidated_snapshot():
    server, seen = await _serve({"/alerts": [(200, SIREN, {}), (304, None, {})]})
    try:
        async with ClientSession() as session:
            transport = PollTransport(session, base_url=_url(server))
            await transport.fetch()
            with pytest.raises(TransportError):
                await transport.fetch()
        assert "If-None-Match" not in seen["/alerts"][1]
    finally:
        await server.close()
