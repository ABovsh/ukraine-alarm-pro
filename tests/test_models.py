"""Tests for snapshot model and threat resolution."""

from custom_components.ukraine_alarm_pro.models import (
    Alert,
    Snapshot,
    ThreatLevel,
    parse_alert_payload,
    region_threat,
)

RAW = {
    "alerts": [
        {
            "regionId": "31",
            "regionType": "State",
            "regionName": "м. Київ",
            "lastUpdate": "2026-07-17T06:00:00Z",
            "activeAlerts": [
                {"regionId": "31", "type": "AIR", "lastUpdate": "2026-07-17T06:00:00Z"},
                {"regionId": "31", "type": "ARTILLERY", "lastUpdate": "2026-07-17T06:01:00Z"},
            ],
        },
        {
            "regionId": "703",
            "regionType": "Community",
            "regionName": "Вишнева громада",
            "lastUpdate": "2026-07-17T06:02:00Z",
            "activeAlerts": [
                {"regionId": "703", "type": "NUCLEAR", "lastUpdate": "2026-07-17T06:02:00Z"}
            ],
        },
    ]
}


def test_parse_alert_payload_builds_snapshot():
    snap = parse_alert_payload(RAW)
    assert isinstance(snap, Snapshot)
    assert set(snap.regions) == {"31", "703"}
    assert snap.regions["31"][0] == Alert(type="AIR", last_update="2026-07-17T06:00:00Z")
    assert len(snap.regions["31"]) == 2


def test_parse_unknown_alert_type_maps_to_unknown():
    raw = {
        "alerts": [
            {
                "regionId": "5",
                "regionType": "State",
                "activeAlerts": [{"type": "FUTURE_NEW_TYPE", "lastUpdate": "x"}],
            }
        ]
    }
    snap = parse_alert_payload(raw)
    assert region_threat(snap, "5", []) is ThreatLevel.UNKNOWN


def test_region_threat_picks_highest_priority():
    snap = parse_alert_payload(RAW)
    assert region_threat(snap, "31", []) is ThreatLevel.ARTILLERY
    assert region_threat(snap, "703", []) is ThreatLevel.NUCLEAR


def test_region_threat_none_when_quiet():
    snap = parse_alert_payload(RAW)
    assert region_threat(snap, "692", []) is ThreatLevel.NONE


def test_region_threat_inherits_from_ancestors():
    snap = parse_alert_payload(RAW)
    # 692 has no own alert, but its ancestor 14 (Kyiv oblast)... use 31 as ancestor here
    assert region_threat(snap, "692", ["31"]) is ThreatLevel.ARTILLERY


def test_country_active_count():
    snap = parse_alert_payload(RAW)
    assert snap.active_region_count == 2
