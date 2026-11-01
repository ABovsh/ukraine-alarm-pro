"""A quiet feed must not rewrite the whole journal every five minutes.

2026-11-01 the live journal held 1559 episodes (~1 MB) and was rewritten on
every five-minute flush although only the "last confirmed" stamps moved:
~280 MB of disk writes a day and a deep copy on the event loop each time.
The stamps now go to a small separate store; the journal is written only when
its content changes. A restart still measures its gap from the newest stamp.
"""

from datetime import UTC, datetime, timedelta

from homeassistant.core import HomeAssistant
from test_alert_history import FakeStore, _hist, _payload
from test_entities import _setup

from custom_components.ukraine_alarm_pro import async_remove_entry
from custom_components.ukraine_alarm_pro.const import DOMAIN
from custom_components.ukraine_alarm_pro.models import parse_alert_payload

T0 = datetime(2026, 11, 1, 9, tzinfo=UTC)
DAY = 86400


async def _quiet_journal():
    main, beat = FakeStore(), FakeStore()
    history, clock = _hist(main, now=T0 - timedelta(days=2), heartbeat_store=beat)
    await history.async_load()
    history.confirm(["31"], clock["now"])
    await history.async_flush()
    return history, clock, main, beat


async def test_confirmations_alone_do_not_rewrite_the_journal():
    history, clock, main, beat = await _quiet_journal()
    saved = main.saves
    for minutes in (5, 10, 15):
        clock["now"] = T0 - timedelta(days=2) + timedelta(minutes=minutes)
        history.confirm(["31"], clock["now"])
        await history.async_flush()
    assert main.saves == saved
    assert beat.saves == 3
    assert beat.data["confirmed"]["31"] == clock["now"].isoformat()


async def test_nothing_new_writes_nothing():
    history, _clock, main, beat = await _quiet_journal()
    saved, beats = main.saves, beat.saves
    await history.async_flush()
    assert (main.saves, beat.saves) == (saved, beats)


async def test_an_alert_still_writes_the_journal():
    _history, clock, main, _beat = await _quiet_journal()
    saved = main.saves
    clock["now"] += timedelta(minutes=5)
    history.handle_event("started", _payload("started", clock["now"], active=True))
    await history.async_flush()
    assert main.saves == saved + 1
    assert main.data["active"]["31"]["region_id"] == "31"


async def test_restart_gap_starts_at_the_newest_stamp():
    history, clock, main, beat = await _quiet_journal()
    clock["now"] = T0
    history.confirm(["31"], T0)
    await history.async_flush()
    # The journal's own stamp is two days old; only the heartbeat has T0.
    assert main.data["confirmed"]["31"] != T0.isoformat()
    restarted, clock = _hist(main, now=T0 + timedelta(seconds=40), heartbeat_store=beat)
    await restarted.async_load()
    restarted.handle_event(
        "resynced", _payload("resynced", clock["now"], active=False, origin="resync")
    )
    clock["now"] = T0 + timedelta(hours=1)
    restarted.confirm(["31"], clock["now"])
    result = restarted.rolling("31", DAY)
    assert result["coverage_complete"] is True
    assert result["gap_seconds"] == 0


async def test_damaged_heartbeat_falls_back_to_the_journal():
    _history, clock, main, _beat = await _quiet_journal()
    broken = FakeStore({"confirmed": {"31": "not a time", 7: None}})
    restarted, _ = _hist(main, now=clock["now"], heartbeat_store=broken)
    await restarted.async_load()
    assert restarted._confirmed["31"] == main.data["confirmed"]["31"]


async def test_older_heartbeat_does_not_move_the_stamp_back():
    _history, clock, main, _beat = await _quiet_journal()
    stale = FakeStore({"confirmed": {"31": (clock["now"] - timedelta(hours=1)).isoformat()}})
    restarted, _ = _hist(main, now=clock["now"], heartbeat_store=stale)
    await restarted.async_load()
    assert restarted._confirmed["31"] == main.data["confirmed"]["31"]


async def test_entry_keeps_and_removes_its_heartbeat(
    hass: HomeAssistant, enable_custom_integrations, hass_storage
):
    entry, push = await _setup(hass)
    push(parse_alert_payload({"alerts": []}))
    await hass.async_block_till_done()
    await entry.runtime_data.async_flush_history()
    push(parse_alert_payload({"alerts": []}))
    await hass.async_block_till_done()
    await entry.runtime_data.async_flush_history()
    await hass.async_block_till_done()
    key = f"{DOMAIN}.heartbeat.{entry.entry_id}"
    assert key in hass_storage
    assert await hass.config_entries.async_unload(entry.entry_id)
    await async_remove_entry(hass, entry)
    await hass.async_block_till_done()
    assert key not in hass_storage
