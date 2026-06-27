"""Offline unit tests for the parsing + triangulation logic (no network)."""

from datetime import datetime, timezone

from wxmtn import series
from wxmtn.fetch import LocationForecast
from wxmtn.model import estimate
from wxmtn.peaks import Location


def test_parse_duration():
    assert series.parse_duration("PT1H").total_seconds() == 3600
    assert series.parse_duration("PT4H").total_seconds() == 4 * 3600
    assert series.parse_duration("P1DT2H").total_seconds() == 26 * 3600


def test_hourly_expands_intervals():
    prop = {"values": [{"validTime": "2026-06-13T08:00:00+00:00/PT3H", "value": 5.0}]}
    h = series.hourly(prop)
    assert len(h) == 3
    t0 = datetime(2026, 6, 13, 8, tzinfo=timezone.utc)
    assert h[t0] == 5.0
    assert series.at(h, datetime(2026, 6, 13, 9, tzinfo=timezone.utc)) == 5.0


def _fc(name, elev_m, temp_c, dewpoint_c, when):
    loc = Location(name, 44.0, -71.0, elev_m)
    fc = LocationForecast(loc=loc, grid_elevation_m=elev_m, office="GYX", grid_x=0, grid_y=0)
    fc.hourly = {
        "temp_c": {when: temp_c},
        "dewpoint_c": {when: dewpoint_c},
        "wind_kmh": {when: 64.0},
        "sky_pct": {when: 50.0},
        "vis_m": {when: 16000.0},
    }
    return fc


def test_lapse_rate_makes_summits_colder():
    """A higher summit must come out colder than a lower one via the lapse fit."""
    when = datetime(2026, 6, 13, 12, tzinfo=timezone.utc)
    valley = _fc("Valley", 200, 20.0, 10.0, when)
    mid = _fc("Mid", 1000, 14.0, 6.0, when)
    summit = _fc("Summit", 1900, 9.0, 2.0, when)
    all_fc = {f.loc.name: f for f in (valley, mid, summit)}

    est = estimate(all_fc, summit, when)
    est_valley = estimate(all_fc, valley, when)
    assert est.temp_f is not None and est_valley.temp_f is not None
    assert est.temp_f < est_valley.temp_f
    # lapse rate should be negative (cooling with height)
    assert est.lapse_c_per_1000m is not None and est.lapse_c_per_1000m < 0


def test_in_cloud_when_summit_above_lcl():
    """Small valley T/Td spread -> low cloud base -> high summit is in cloud."""
    when = datetime(2026, 6, 13, 12, tzinfo=timezone.utc)
    valley = _fc("Valley", 200, 12.0, 11.0, when)  # 1°C spread -> base ~325 m
    summit = _fc("Summit", 1900, 4.0, 3.0, when)
    all_fc = {f.loc.name: f for f in (valley, summit)}

    est = estimate(all_fc, summit, when)
    assert est.in_cloud is True
    assert "cloud" in est.visibility_label or "fog" in est.visibility_label
