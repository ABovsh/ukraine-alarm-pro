"""Official alert history fills the journal before install and across gaps."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from test_alert_history import FakeStore, _hist, _payload
from test_entities import _setup

from custom_components.ukraine_alarm_pro.api.errors import TransportError
from custom_components.ukraine_alarm_pro.backfill import (
    async_fetch_official_history,
    official_intervals,
    parse_ranged_alerts,
    root_regions,
)

T0 = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)


def _rec(region, start, end, *, alert_type="AIR"):
    return {
        "regionId": region,
        "regionName": "x",
        "startDate": start,
        "endDate": end,
        "duration": "00:10:00",
        "alertType": alert_type,
        "isContinue": False,
    }


def test_parse_accepts_the_double_encoded_answer_and_skips_ongoing_alerts():
    records = [
        _rec("77", "2026-09-14T06:25:06.701682Z", "2026-09-14T06:41:00.457098Z"),
        _rec("77", "2026-09-15T12:00:39Z", "0001-01-01T00:00:00"),  # still active
        _rec("77", "2026-09-14T08:00:00Z", "2026-09-14T07:00:00Z"),  # ends before start
        {"regionId": "77"},  # damaged record
    ]
    parsed = parse_ranged_alerts(json.dumps(json.dumps(records)))
    assert parsed == [
        (
            "77",
            datetime(2026, 9, 14, 6, 25, 6, 701682, tzinfo=UTC),
            datetime(2026, 9, 14, 6, 41, 0, 457098, tzinfo=UTC),
        )
    ]


@pytest.mark.parametrize("body", ["not json", json.dumps({"a": 1}), json.dumps(json.dumps(5))])
def test_parse_rejects_an_unusable_envelope(body):
    with pytest.raises(ValueError):
        parse_ranged_alerts(body)


def test_root_regions_are_the_top_ancestors():
    regions = {
        "31": {"ancestors": [], "descendants": []},
        "692": {"ancestors": ["77", "14"], "descendants": []},
        "695": {"ancestors": ["77", "14"], "descendants": []},
    }
    assert root_regions(regions) == ["14", "31"]


def test_intervals_include_ancestors_and_descendants_and_merge_overlaps():
    h = lambda hh, mm: datetime(2026, 9, 14, hh, mm, tzinfo=UTC)
    records = [
        ("77", h(6, 0), h(6, 30)),
        ("14", h(6, 20), h(7, 0)),  # overlaps the raion alert: one episode
        ("73", h(8, 0), h(8, 10)),  # another raion: not ours
        ("900", h(9, 0), h(9, 5)),  # a hromada inside the region
    ]
    info = {"ancestors": ["77", "14"], "descendants": []}
    assert official_intervals(records, "692", info) == [(h(6, 0), h(7, 0))]
    info_raion = {"ancestors": ["14"], "descendants": ["900"]}
    assert official_intervals(records, "77", info_raion) == [
        (h(6, 0), h(7, 0)),
        (h(9, 0), h(9, 5)),
    ]


async def test_merge_adds_only_periods_the_journal_did_not_observe():
    history, _ = _hist(FakeStore())
    await history.async_load()
    # Observed live: 09:00:10 – 09:20.
    history.handle_event("started", _payload("started", T0 - timedelta(minutes=59, seconds=50), active=True))
    history.handle_event("cleared", _payload("cleared", T0 - timedelta(minutes=40), active=False))
    official = [
        (T0 - timedelta(hours=1), T0 - timedelta(minutes=41)),  # the same alert, official times
        (T0 - timedelta(days=2), T0 - timedelta(days=2) + timedelta(minutes=30)),  # before install
    ]
    added = history.merge_official("31", official, window_start=T0 - timedelta(days=90))
    assert added == 1
    episodes = history.history("31", 10)
    assert len(episodes) == 2
    old = episodes[-1]
    assert old["start_origin"] == "history"
    assert old["observed_duration_seconds"] == 1800
    assert old["had_gap"] is False and old["source_start_known"] is True
    assert history.summary("31", 7)["coverage_start"] == (T0 - timedelta(days=90)).isoformat()


async def test_merge_is_idempotent_and_persisted():
    store = FakeStore()
    history, _ = _hist(store)
    await history.async_load()
    official = [(T0 - timedelta(days=1), T0 - timedelta(days=1, minutes=-20))]
    assert history.merge_official("31", official, window_start=T0 - timedelta(days=90)) == 1
    assert history.merge_official("31", official, window_start=T0 - timedelta(days=90)) == 0
    await history.async_flush()
    reloaded, _ = _hist(FakeStore(store.data))
    await reloaded.async_load()
    assert len(reloaded.history("31", 10)) == 1


async def test_merge_never_extends_coverage_forward_and_skips_the_active_period():
    history, _ = _hist(FakeStore())
    await history.async_load()
    history.handle_event("resynced", _payload("resynced", T0 - timedelta(minutes=5), active=True, origin="bootstrap"))
    ongoing_overlap = [(T0 - timedelta(minutes=30), T0 - timedelta(minutes=2))]
    assert history.merge_official("31", ongoing_overlap, window_start=T0 + timedelta(days=1)) == 0
    assert history.summary("31", 1)["coverage_start"] == T0.isoformat()


class _Resp:
    def __init__(self, text, status=200):
        self._text = text
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise __import__("aiohttp").ClientResponseError(MagicMock(), (), status=self.status)

    async def text(self):
        return self._text


async def test_fetch_uses_the_map_page_token_and_one_request_per_root():
    page = '<input id="api-token" type="hidden" value="tok123" />'
    body = json.dumps(json.dumps([_rec("31", "2026-09-14T06:00:00Z", "2026-09-14T06:10:00Z")]))
    session = MagicMock()
    session.get = AsyncMock(side_effect=[_Resp(page), _Resp(body)])
    records = await async_fetch_official_history(
        session, ["31"], T0 - timedelta(days=90), T0
    )
    assert len(records) == 1
    url = session.get.call_args_list[1].args[0]
    assert "regionId=31" in url and "apiToken=tok123" in url
    assert "startDate=20260617" in url and "endDate=20260916" in url


async def test_fetch_without_a_token_is_a_transport_error():
    session = MagicMock()
    session.get = AsyncMock(return_value=_Resp("<html></html>"))
    with pytest.raises(TransportError):
        await async_fetch_official_history(session, ["31"], T0 - timedelta(days=1), T0)


async def test_setup_backfills_the_journal_in_the_background(
    hass: HomeAssistant, enable_custom_integrations, monkeypatch
):
    start = datetime.now(UTC) - timedelta(days=3)
    records = [("31", start, start + timedelta(minutes=25))]
    fetch = AsyncMock(return_value=records)
    monkeypatch.setattr("custom_components.ukraine_alarm_pro.backfill._fetch", fetch)
    entry, _ = await _setup(hass)
    coordinator = entry.runtime_data
    await coordinator.async_backfill_history()
    episodes = coordinator.history.history("31", 10)
    assert [ep["start_origin"] for ep in episodes] == ["history"]
    # A failing source never raises out of the background job.
    fetch.side_effect = TransportError("down")
    await coordinator.async_backfill_history()


async def test_backfill_runs_five_minutes_after_setup_and_then_daily(
    hass: HomeAssistant, enable_custom_integrations, monkeypatch
):
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("custom_components.ukraine_alarm_pro.backfill._fetch", fetch)
    await _setup(hass)
    now = dt_util.utcnow()
    async_fire_time_changed(hass, now + timedelta(seconds=299))
    await hass.async_block_till_done()
    assert fetch.await_count == 0
    async_fire_time_changed(hass, now + timedelta(seconds=301))
    await hass.async_block_till_done()
    assert fetch.await_count == 1
    async_fire_time_changed(hass, now + timedelta(hours=24, seconds=5))
    await hass.async_block_till_done()
    assert fetch.await_count == 2
