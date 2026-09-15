"""Whole-region vs partial coverage (UAP-04) — an explanation, never a filter."""

from homeassistant.core import HomeAssistant
from test_entities import _setup

from custom_components.ukraine_alarm_pro.models import (
    MAX_AFFECTED_REGIONS,
    ThreatLevel,
    parse_alert_payload,
    region_view,
)

OBLAST, RAION, HROMADA = "14", "75", "703"
OBLAST_TREE = {"region_id": OBLAST, "ancestors": [], "descendants": [RAION, HROMADA, "704", "705"]}
HROMADA_TREE = {"region_id": HROMADA, "ancestors": [RAION, OBLAST], "descendants": []}


def _alert(type_="AIR", region=None, stamp="2026-09-15T06:00:00Z"):
    alert = {"type": type_, "lastUpdate": stamp}
    if region is not None:
        alert["regionId"] = region
    return alert


def _snap(*records):
    return parse_alert_payload(
        {"alerts": [{"regionId": rid, "regionName": f"name-{rid}", "activeAlerts": alerts}
                    for rid, alerts in records]}
    )


def _view(snap, tree):
    return region_view(snap, tree["region_id"], tree["ancestors"], tree["descendants"])


def test_raion_alert_is_partial_for_the_oblast():
    view = _view(_snap((RAION, [_alert()])), OBLAST_TREE)
    assert view.coverage == "partial"
    assert view.coverage_by_type == {"air": "partial"}
    assert view.threat is ThreatLevel.AIR


def test_oblast_alert_is_whole_for_a_hromada():
    snap = _snap((OBLAST, [_alert()]), (HROMADA, [_alert(region=OBLAST)]))
    assert _view(snap, HROMADA_TREE).coverage == "whole"


def test_own_declaration_is_whole():
    assert _view(_snap((OBLAST, [_alert()])), OBLAST_TREE).coverage == "whole"


def test_one_raion_repeated_in_many_hromadas_is_one_affected_region():
    snap = _snap(
        (RAION, [_alert()]),
        *[(h, [_alert(region=RAION)]) for h in (HROMADA, "704", "705")],
    )
    view = _view(snap, OBLAST_TREE)
    assert view.coverage == "partial"
    assert view.affected_regions == ({"region_id": RAION, "region_name": f"name-{RAION}"},)
    assert view.affected_region_count == 1


def test_mixed_types_keep_their_own_coverage():
    snap = _snap((RAION, [_alert("AIR")]), (OBLAST, [_alert("CHEMICAL")]))
    view = _view(snap, OBLAST_TREE)
    assert view.coverage == "whole"
    assert view.coverage_by_type == {"chemical": "whole", "air": "partial"}


def test_copy_order_does_not_change_the_classification():
    a = _snap((HROMADA, [_alert(region=RAION)]), (RAION, [_alert()]))
    b = _snap((RAION, [_alert()]), (HROMADA, [_alert(region=RAION)]))
    assert _view(a, OBLAST_TREE) == _view(b, OBLAST_TREE)


def test_valid_clear_is_none():
    view = _view(_snap((RAION, [])), OBLAST_TREE)
    assert view.coverage == "none"
    assert view.coverage_by_type == {}
    assert view.affected_regions == ()
    assert view.affected_region_count == 0


def test_unknown_declaring_region_is_unrecognized_and_still_on():
    snap = _snap((HROMADA, [_alert(region="9999")]))
    view = _view(snap, HROMADA_TREE)
    assert view.coverage == "unrecognized"
    assert view.threat is ThreatLevel.AIR


def test_unrecognized_outranks_partial_but_not_whole():
    partial_and_unknown = _snap((RAION, [_alert("AIR")]), (HROMADA, [_alert("CHEMICAL", region="9999")]))
    assert _view(partial_and_unknown, OBLAST_TREE).coverage == "unrecognized"
    whole_and_unknown = _snap((OBLAST, [_alert("AIR")]), (HROMADA, [_alert("CHEMICAL", region="9999")]))
    assert _view(whole_and_unknown, OBLAST_TREE).coverage == "whole"


def test_region_without_descendants_and_affected_cap():
    many = [str(1000 + i) for i in range(MAX_AFFECTED_REGIONS + 5)]
    snap = _snap(*[(rid, [_alert()]) for rid in many])
    view = region_view(snap, OBLAST, [], many)
    assert view.coverage == "partial"
    assert len(view.affected_regions) == MAX_AFFECTED_REGIONS
    assert view.affected_region_count == MAX_AFFECTED_REGIONS + 5
    assert region_view(snap, "31", [], []).coverage == "none"


async def test_threat_sensor_exposes_coverage_without_touching_old_attributes(
    hass: HomeAssistant, enable_custom_integrations
):
    _, push = await _setup(hass)
    push(_snap((OBLAST, [_alert()]), (HROMADA, [_alert(region=OBLAST)])))
    await hass.async_block_till_done()
    state = hass.states.get("sensor.uap_703_threat")
    assert state.state == "air"
    attrs = state.attributes
    assert attrs["coverage"] == "whole"
    assert attrs["coverage_by_type"] == {"air": "whole"}
    assert attrs["affected_regions"] == [{"region_id": OBLAST, "region_name": f"name-{OBLAST}"}]
    assert attrs["affected_region_count"] == 1
    assert attrs["active_alert_count"] == 1
    assert attrs["active_threat_types"] == "air"
    assert hass.states.get("binary_sensor.uap_703_alert").state == "on"
    assert hass.states.get("sensor.uap_31_threat").attributes["coverage"] == "none"
