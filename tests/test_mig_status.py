"""MiG-31K take-off and Kinzhal launch, read from the map feed.

The polling fallback carries no such data, so outside the live WebSocket the
status is unknown: a "none" nobody confirmed would be a false all clear.
"""

import time
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util
from test_alert_history import FakeStore, _hist
from test_entities import _setup

from custom_components.ukraine_alarm_pro.const import STALE_AFTER_SECONDS
from custom_components.ukraine_alarm_pro.models import (
    MigState,
    parse_alert_payload,
    parse_mig,
)

STATUS = "sensor.uap_mig_status"
EVENT = "event.uap_mig_event"
EMPTY = "0001-01-01T00:00:00"


def _feed(mig=(), *, rockets=False, has_mig=None, mig_type=None):
    return {
        "alerts": [],
        "migAlerts": list(mig),
        "mapNotifications": {
            "hasMig": bool(mig) if has_mig is None else has_mig,
            "migRockets": rockets,
            "migType": mig_type,
            "lastMigUpdateTime": EMPTY,
            "lastMigRocketsUpdateTime": EMPTY,
        },
    }


TAKEOFF = {"type": "Savasleika", "startDate": "2026-11-01T09:00:00Z"}


def test_parse_reads_the_feed_shapes():
    assert parse_mig(_feed()) == MigState()
    state = parse_mig(_feed([TAKEOFF]))
    assert (state.status, state.airfield, state.since) == ("takeoff", "savasleika", "2026-11-01T09:00:00Z")
    assert parse_mig(_feed([TAKEOFF], rockets=True)).status == "launch"
    # A launch flag alone does not start a flight: the map reads it only with one.
    assert parse_mig(_feed(rockets=True)).status == "none"
    assert parse_mig(_feed([{"type": "Mozdok"}])).airfield == "mozdok"
    assert parse_mig(_feed([{"type": "NewField"}])).airfield == "unknown"
    # The notification alone also reports a flight; its zero date is no time at all.
    flagged = parse_mig(_feed(has_mig=True, mig_type="Mozdok"))
    assert (flagged.status, flagged.airfield, flagged.since) == ("takeoff", "mozdok", "")


def test_parse_says_unknown_instead_of_none_for_missing_or_damaged_data():
    assert parse_mig([]) is None
    assert parse_mig({"alerts": []}) is None
    assert parse_mig({"alerts": [], "migAlerts": "x"}) is None
    assert parse_mig({"alerts": [], "migAlerts": [TAKEOFF], "mapNotifications": None}).status == "takeoff"
    assert parse_mig({"alerts": [], "migAlerts": ["x", 3]}).status == "takeoff"
    assert parse_mig({"alerts": [], "migAlerts": ["x", 3]}).airfield == "unknown"


def test_damaged_mig_fields_never_cost_the_alert_map():
    raw = {"alerts": [{"regionId": "31", "activeAlerts": []}], "migAlerts": 5, "mapNotifications": 7}
    snap = parse_alert_payload(raw)
    assert "31" in snap.regions and snap.mig is None
    assert parse_alert_payload([]).mig is None


async def test_status_and_attributes_follow_the_feed(hass: HomeAssistant, enable_custom_integrations):
    _, push = await _setup(hass)
    assert hass.states.get(STATUS).state == "unknown"
    push(parse_alert_payload(_feed()))
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "none"
    push(parse_alert_payload(_feed([TAKEOFF])))
    await hass.async_block_till_done()
    state = hass.states.get(STATUS)
    assert state.state == "takeoff"
    assert state.attributes["airfield"] == "savasleika"
    assert state.attributes["since"] == "2026-11-01T09:00:00Z"
    push(parse_alert_payload(_feed([TAKEOFF], rockets=True)))
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "launch"


def _events(hass):
    fired = []

    @callback
    def seen(event):
        if event.data["entity_id"] == EVENT and event.data["new_state"].state != "unknown":
            fired.append(event.data["new_state"].attributes["event_type"])

    hass.bus.async_listen("state_changed", seen)
    return fired


async def test_events_fire_on_real_transitions_only(hass: HomeAssistant, enable_custom_integrations):
    _, push = await _setup(hass)
    fired = _events(hass)
    # A flight already under way at start-up is not announced as a new one.
    push(parse_alert_payload(_feed([TAKEOFF])))
    await hass.async_block_till_done()
    assert fired == []
    push(parse_alert_payload(_feed([TAKEOFF], rockets=True)))
    await hass.async_block_till_done()
    push(parse_alert_payload(_feed()))
    await hass.async_block_till_done()
    push(parse_alert_payload(_feed([TAKEOFF])))
    await hass.async_block_till_done()
    assert fired == ["launch", "cleared", "takeoff"]


async def test_a_feed_without_mig_data_keeps_the_live_status(hass: HomeAssistant, enable_custom_integrations):
    """The watchdog's cross-check reads the polling endpoint every 15 quiet
    minutes while the socket stays up: it must not blank the status or re-announce."""
    entry, push = await _setup(hass)
    push(parse_alert_payload(_feed()))
    push(parse_alert_payload(_feed([TAKEOFF])))
    await hass.async_block_till_done()
    fired = _events(hass)
    push(parse_alert_payload([]))
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "takeoff"
    push(parse_alert_payload(_feed([TAKEOFF])))
    await hass.async_block_till_done()
    assert fired == []
    assert entry.runtime_data.mig_state.status == "takeoff"


async def test_polling_and_stale_data_make_the_status_unknown(hass: HomeAssistant, enable_custom_integrations):
    entry, push = await _setup(hass)
    coordinator = entry.runtime_data
    push(parse_alert_payload(_feed()))
    await hass.async_block_till_done()
    coordinator.supervisor.mode = "polling"
    coordinator.handle_mode_change("polling")
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "unknown"
    coordinator.supervisor.mode = "websocket"
    coordinator.handle_mode_change("websocket")
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "none"
    coordinator.last_push = dt_util.utcnow() - timedelta(seconds=STALE_AFTER_SECONDS + 60)
    coordinator._last_push_monotonic = time.monotonic() - STALE_AFTER_SECONDS - 60
    for listener in tuple(coordinator._health_listeners):
        listener()
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "unknown"


async def test_an_unchanged_feed_writes_no_rows(hass: HomeAssistant, enable_custom_integrations):
    _, push = await _setup(hass)
    push(parse_alert_payload(_feed([TAKEOFF])))
    await hass.async_block_till_done()
    rows = []

    @callback
    def seen(event):
        if event.data["entity_id"] in (STATUS, EVENT):
            rows.append(event.data["entity_id"])

    hass.bus.async_listen("state_changed", seen)
    for _ in range(3):
        push(parse_alert_payload(_feed([TAKEOFF])))
        await hass.async_block_till_done()
    assert rows == []


async def test_status_has_no_statistics_and_survives_entry_cleanup(hass: HomeAssistant, enable_custom_integrations):
    entry, _push = await _setup(hass)
    assert "state_class" not in hass.states.get(STATUS).attributes
    # The hub entities must not read as a region called "mig" when regions are purged.
    from homeassistant.helpers import entity_registry as er

    from custom_components.ukraine_alarm_pro import _async_purge_deselected_regions

    _async_purge_deselected_regions(hass, entry)
    registry = er.async_get(hass)
    assert registry.async_get(EVENT) is not None and registry.async_get(STATUS) is not None


async def test_a_quiet_journal_still_trims_old_episodes_on_flush():
    """A heartbeat-only flush must not skip the daily retention pass."""
    from datetime import UTC, datetime

    from test_alert_history import _payload

    start = datetime(2026, 8, 1, 9, tzinfo=UTC)
    main, beat = FakeStore(), FakeStore()
    history, clock = _hist(main, now=start, heartbeat_store=beat)
    await history.async_load()
    history.confirm(["31"], start)
    history.handle_event("started", _payload("started", start, active=True))
    history.handle_event("cleared", _payload("cleared", start + timedelta(hours=1), active=False))
    await history.async_flush()
    clock["now"] = start + timedelta(days=100)
    history.confirm(["31"], clock["now"])
    await history.async_flush()
    assert main.data["episodes"] == []
