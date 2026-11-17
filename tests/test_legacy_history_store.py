"""The journal no longer imports outside history; 0.15.0 stores stay readable.

The fixture was written by the 0.15.0 code (live episodes, imported official
intervals, a restart gap, an interrupted import of a region added later). The
expected values are what 0.15.0 reported on the same data at the same moment.
"""

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from test_alert_history import FakeStore, _hist
from test_entities import _setup

from custom_components.ukraine_alarm_pro.history import _union

FIXTURES = Path(__file__).parent / "fixtures"
T0 = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)
LEGACY_KEYS = ("official_synced_at", "official_synced_regions", "backfill_targets", "cursors")


def legacy_import(history, region_id, spans, *, since, episodes=False):
    """What a 0.15.0 store holds after importing official intervals."""
    history._official_spans[region_id] = [
        (lo.isoformat(), hi.isoformat()) for lo, hi in _union(list(spans))
    ]
    history._official_since[region_id] = since.isoformat()
    for lo, hi in spans if episodes else ():
        episode = {
            "episode_id": f"h{lo:%Y%m%d%H%M}",
            "region_id": region_id,
            "observed_started_at": lo.isoformat(),
            "declared_started_at": lo.isoformat(),
            "observed_cleared_at": hi.isoformat(),
            "active_types_seen": ["air"],
            "maximum_air_level": "none",
            "had_gap": False,
            "source_start_known": True,
            "start_origin": "history",
        }
        history._completed.append(episode)
        history._index.setdefault(region_id, []).append(episode)


def _stored():
    return json.loads((FIXTURES / "history_store_0_15_0.json").read_text())


def _expected():
    return json.loads((FIXTURES / "history_store_0_15_0_expected.json").read_text())


def _report(history, region_id):
    summary = history.summary(region_id, 7)
    last = history.last_cleared(region_id)
    return json.loads(
        json.dumps(
            {
                "coverage_start": summary["coverage_start"],
                "typical": history.typical(region_id),
                "rolling_24h": history.rolling(region_id, 86400)["percentage"],
                "rolling_7d": history.rolling(region_id, 604800)["percentage"],
                "rolling_7d_quality": history.rolling(region_id, 604800)["quality"],
                "calendar": history.calendar(region_id),
                "last_cleared": last.isoformat() if last else None,
                "history": history.history(region_id, 50),
            }
        )
    )


async def _load(hass, store):
    await hass.config.async_set_time_zone("Europe/Kyiv")
    history, clock = _hist(store, now=T0)
    await history.async_load()
    return history, clock


async def test_a_0_15_0_store_reports_what_0_15_0_reported(hass: HomeAssistant):
    history, _ = await _load(hass, FakeStore(_stored()))
    history.confirm(["31", "695"], T0)
    expected = _expected()
    for region_id in ("31", "695"):
        assert _report(history, region_id) == expected[region_id]
    origins = [ep["start_origin"] for ep in history.history("31", 50)]
    assert origins.count("history") == 14
    # 90 days of imported coverage, not the ten days since installation.
    assert expected["31"]["typical"]["days"] == 90


async def test_saving_drops_only_the_import_bookkeeping(hass: HomeAssistant):
    store = FakeStore(_stored())
    history, _ = await _load(hass, store)
    history.confirm(["31", "695"], T0)
    await history.async_flush()
    saved = json.loads(json.dumps(store.data))  # what Store writes to disk
    for key in LEGACY_KEYS:
        assert key not in saved
    # Store version is unchanged and the imported data stays, so 0.15.0 can
    # still read it after a rollback.
    assert saved["schema_version"] == 2
    assert saved["official_spans"] == _stored()["official_spans"]
    assert saved["official_since"] == _stored()["official_since"]
    reloaded, _ = await _load(hass, FakeStore(saved))
    expected = _expected()
    assert reloaded.typical("31") == expected["31"]["typical"]
    assert reloaded.summary("31", 7)["coverage_start"] == expected["31"]["coverage_start"]


async def test_imported_intervals_leave_with_the_90_day_window(hass: HomeAssistant):
    store = FakeStore(_stored())
    history, clock = await _load(hass, store)
    oldest = min(lo for lo, _hi in _stored()["official_spans"]["31"])
    clock["now"] = datetime.fromisoformat(oldest) + timedelta(days=91)
    history.confirm(["31", "695"], clock["now"])
    await history.async_flush()
    kept = store.data["official_spans"]["31"]
    assert oldest not in [lo for lo, _hi in kept]
    assert len(kept) == len(_stored()["official_spans"]["31"]) - 1
    assert all(
        ep["observed_cleared_at"] > (clock["now"] - timedelta(days=90)).isoformat()
        for ep in store.data["episodes"]
    )


async def test_no_history_requests_in_two_hours(
    hass: HomeAssistant, enable_custom_integrations, aioclient_mock, monkeypatch
):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "custom_components.ukraine_alarm_pro.regions.async_refresh_region_cache",
        AsyncMock(),
    )
    aioclient_mock.get(re.compile(r"map\.ukrainealarm\.com"), text="<html></html>")
    aioclient_mock.get(re.compile(r"."), json=[])
    await _setup(hass)
    start = dt_util.utcnow()
    for seconds in (301, 3605, 7205):
        async_fire_time_changed(hass, start + timedelta(seconds=seconds))
        await hass.async_block_till_done(wait_background_tasks=True)
    assert [str(url) for _m, url, _d, _h in aioclient_mock.mock_calls if "ukrainealarm" in str(url)] == []
