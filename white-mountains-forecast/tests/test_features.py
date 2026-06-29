"""Offline tests for the richer features (astro, scoring, obs lapse, mwobs)."""

from datetime import date, datetime, timedelta, timezone

from wxmtn import astro, mwobs
from wxmtn.fetch import LocationForecast
from wxmtn.model import SummitEstimate, estimate
from wxmtn.obs import observed_lapse
from wxmtn.peaks import Location
from wxmtn.score import best_window, composite, view_score


def test_sun_times_order():
    s = astro.sun_times(date(2026, 6, 28), 44.27, -71.30)
    assert s["sunrise"] < s["sunset"]
    # late June in NH: well over 14 hours of daylight
    assert (s["sunset"] - s["sunrise"]) > timedelta(hours=14)


def test_view_score_clear_beats_cloud():
    base = dict(name="x", when=datetime(2026, 6, 28, tzinfo=timezone.utc),
                temp_f=55, lapse_c_per_1000m=-6.0, wind_mph=5, gust_mph=8,
                sky_pct=10, pop_pct=0, cloud_base_m=3000, feels_like_f=55)
    clear = SummitEstimate(vis_mi=10, in_cloud=False, visibility_label="clear", **base)
    foggy = SummitEstimate(vis_mi=0.1, in_cloud=True, visibility_label="fog", **base)
    assert view_score(clear) > view_score(foggy)
    assert composite(clear) > composite(foggy)


def test_best_window_picks_contiguous_good_run():
    t0 = datetime(2026, 6, 28, 10, tzinfo=timezone.utc)
    scored = [(t0 + timedelta(hours=i), s) for i, s in enumerate([40, 70, 75, 80, 30, 90])]
    w = best_window(scored, threshold=55)
    assert w is not None and w.hours == 3       # the 70,75,80 run, not the lone 90
    assert w.start == t0 + timedelta(hours=1)


def _anchor(name, elev, temp_c, when):
    loc = Location(name, 44.0, -71.0, elev)
    fc = LocationForecast(loc=loc, grid_elevation_m=elev, office="OBS", grid_x=0, grid_y=0)
    fc.observation = {"temp_c": temp_c, "when": when, "vis_m": 20000}
    return fc


def test_observed_lapse_and_inversion():
    when = datetime(2026, 6, 28, 12, tzinfo=timezone.utc)
    # normal: warmer low, colder high
    normal = [_anchor("low", 200, 24, when), _anchor("high", 1900, 8, when)]
    lapse, inv, _ = observed_lapse(normal)
    assert lapse is not None and lapse < 0 and inv is False
    # inversion: a low station colder than one above it
    inverted = [_anchor("cold valley", 200, 5, when), _anchor("warm slope", 800, 12, when)]
    _, inv2, detail = observed_lapse(inverted)
    assert inv2 is True and detail


def test_bias_decays_to_zero():
    when0 = datetime(2026, 6, 28, 12, tzinfo=timezone.utc)
    loc = Location("Summit", 44.0, -71.0, 1900)
    fc = LocationForecast(loc=loc, grid_elevation_m=1900, office="GYX", grid_x=0, grid_y=0)
    fc.hourly = {"temp_c": {when0 + timedelta(hours=h): 10.0 for h in range(8)}}
    all_fc = {"Summit": fc}
    e_now = estimate(all_fc, fc, when0, bias_c=3.0, bias_from=when0)
    e_later = estimate(all_fc, fc, when0 + timedelta(hours=6), bias_c=3.0, bias_from=when0)
    assert e_now.bias_f > e_later.bias_f                # bias fades with time
    assert abs(e_later.bias_f) < 0.1                    # ~zero at the decay horizon


def test_ascent_profile_enters_cloud():
    from wxmtn.model import ascent_profile
    when = datetime(2026, 6, 28, 12, tzinfo=timezone.utc)
    valley = _anchor_fc("low", 200, 20.0, when)
    summit = _anchor_fc("Summit", 1900, 8.0, when)  # cold/cloudy high
    summit.hourly["dewpoint_c"] = {when: 7.5}
    valley.hourly["dewpoint_c"] = {when: 19.5}       # tiny spread -> low cloud base
    all_fc = {"low": valley, "Summit": summit}
    prof = ascent_profile(all_fc, summit, when, start_elev_m=300)
    assert prof and len(prof["bands"]) == 7
    assert prof["bands"][0]["elev_ft"] < prof["bands"][-1]["elev_ft"]  # trailhead -> summit
    assert any(b["cloud"] for b in prof["bands"])    # high bands are in cloud
    assert prof["enters_cloud_ft"] is not None


def test_ai_briefing_none_without_key(monkeypatch=None):
    import os
    from wxmtn import ai
    os.environ.pop("ANTHROPIC_API_KEY", None)
    assert ai.build_briefing({"peaks": []}) is None


def _anchor_fc(name, elev, temp_c, when):
    loc = Location(name, 44.0, -71.0, elev)
    fc = LocationForecast(loc=loc, grid_elevation_m=elev, office="GYX", grid_x=0, grid_y=0)
    fc.hourly = {"temp_c": {when: temp_c}}
    return fc


def test_webreport_renders_payload():
    from wxmtn import webreport
    payload = {"generated": "x", "labels": ["sun 12pm"], "sunrise": "5am",
               "sunset": "8pm", "summit_now": None, "alerts": [], "peaks": []}
    html = webreport.render_html(payload)
    assert "/*__DATA__*/null" not in html          # placeholder was replaced
    assert '"sun 12pm"' in html and "leaflet" in html


def test_mwobs_returns_none_on_junk(monkeypatch=None):
    # The scraper must never emit nav/placeholder junk; None is the honest answer.
    out = mwobs.higher_summits_text(timeout=1)
    assert out is None or ("Switch to Metric" not in out and len(out) >= 120)
