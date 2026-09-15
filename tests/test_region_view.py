"""One computed result per region per accepted map change (UAP-09).

Every region entity used to aggregate the region's alerts on its own — six
passes per region per update. The shared view must give exactly the values the
old getters produced, and be computed once.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from test_entities import _setup

from custom_components.ukraine_alarm_pro import models
from custom_components.ukraine_alarm_pro.models import (
    air_alert_levels,
    declared_at,
    parse_alert_payload,
    region_alerts,
    region_threat,
    region_view,
    threat_types,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _legacy(snap, rid, ancestors, descendants):
    found = region_alerts(snap, rid, ancestors, descendants)
    stamps = [d for a in found if (d := declared_at(a)) is not None]
    reasons = sorted({
        lvl.reason for a in found if a.type == "AIR" for lvl in a.levels if lvl.reason
    })
    return {
        "alerts": found,
        "threat": region_threat(snap, rid, ancestors, descendants),
        "threat_types": threat_types(found),
        "started": min(stamps, default=None),
        "air_levels": air_alert_levels(found),
        "air_reasons": reasons,
    }


def _snapshots():
    yield parse_alert_payload(json.loads((FIXTURES / "air_levels_poll.json").read_text()))
    yield parse_alert_payload(json.loads((FIXTURES / "air_levels_ws.json").read_text()))
    yield parse_alert_payload({"alerts": []})
    yield parse_alert_payload(
        {
            "alerts": [
                {"regionId": "14", "activeAlerts": [
                    {"type": "AIR", "lastUpdate": "2026-09-15T06:00:00Z",
                     "activeAlertLevels": [{"alertLevel": "Yellow", "reason": "b"}]},
                    {"type": "PLASMA", "lastUpdate": "bad"},
                ]},
                {"regionId": "703", "activeAlerts": [
                    {"type": "AIR", "regionId": "14", "lastUpdate": "2026-09-15T06:00:00Z",
                     "activeAlertLevels": [{"alertLevel": "Red", "reason": "a"}]},
                    {"type": "CHEMICAL", "lastUpdate": "2026-09-15T05:00:00Z"},
                ]},
            ]
        }
    )


@pytest.mark.parametrize("snap", list(_snapshots()))
@pytest.mark.parametrize(
    ("rid", "ancestors", "descendants"),
    [("14", [], ["75", "703"]), ("703", ["75", "14"], []), ("31", [], [])],
)
def test_view_matches_the_legacy_getters(snap, rid, ancestors, descendants):
    view = region_view(snap, rid, ancestors, descendants)
    legacy = _legacy(snap, rid, ancestors, descendants)
    assert list(view.alerts) == legacy["alerts"]
    assert view.threat is legacy["threat"]
    assert list(view.threat_types) == legacy["threat_types"]
    assert view.started == legacy["started"]
    assert list(view.air_levels) == legacy["air_levels"]
    assert list(view.air_reasons) == legacy["air_reasons"]
    assert isinstance(view.alerts, tuple)


async def test_each_region_is_aggregated_once_per_map_change(
    hass: HomeAssistant, enable_custom_integrations
):
    _, push = await _setup(hass)
    with patch.object(models, "region_alerts", wraps=models.region_alerts) as spy:
        push(parse_alert_payload(
            {"alerts": [{"regionId": "14", "activeAlerts": [{"type": "AIR", "lastUpdate": "x"}]}]}
        ))
        await hass.async_block_till_done()
        # Two configured regions, six region entities each reading the view.
        assert spy.call_count == 2
        spy.reset_mock()
        push(parse_alert_payload(
            {"alerts": [{"regionId": "14", "activeAlerts": [{"type": "AIR", "lastUpdate": "x"}]}]}
        ))
        await hass.async_block_till_done()
        assert spy.call_count == 0, "an identical map reuses nothing and writes nothing"
    assert hass.states.get("binary_sensor.uap_703_alert").state == "on"
