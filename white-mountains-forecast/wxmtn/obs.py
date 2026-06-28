"""Live NWS surface observations used as real-time anchors and ground truth.

The forecast grid is a *prediction*; these stations report what's *actually*
happening right now. Most importantly **KMWN is the Mount Washington Observatory
summit station** (~1,910 m), so it gives us a measured high-elevation anchor for
the lapse-rate fit and a reality check on whether the summit is truly in cloud.

Each station is wrapped as a `LocationForecast` whose time series contains a
single point at the observation hour, so it only influences the *current* hour
of the triangulation (via `series.at`'s small tolerance) and never contaminates
future forecast hours.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import nws
from .fetch import LocationForecast
from .peaks import Location

# (station id, label, lat, lon, is_summit). KMWN = Mount Washington Observatory
# summit station (~1,910 m) -- our only high anchor; the rest bracket the valleys
# so the real-time elevation spread is well constrained.
OBS_STATIONS = [
    ("KMWN", "Mount Washington summit (MWOBS, live)", 44.2706, -71.3033, True),
    ("KBML", "Berlin valley (live)", 44.5750, -71.1790, False),
    ("KHIE", "Whitefield valley (live)", 44.3675, -71.5453, False),
    ("KIZG", "Fryeburg valley (live)", 43.9908, -70.9483, False),
    ("K1P1", "Plymouth valley (live)", 43.7790, -71.7550, False),
    ("KLCI", "Laconia valley (live)", 43.5725, -71.4189, False),
    ("KCON", "Concord valley (live)", 43.1950, -71.5020, False),
]


def _val(prop: dict | None) -> float | None:
    return (prop or {}).get("value")


def live_anchor(station: str, name: str, lat: float, lon: float, is_summit: bool):
    """Fetch one station's latest obs and wrap it as a current-hour anchor."""
    p = nws.latest_observation(station)
    if not p:
        return None
    ts = p.get("timestamp")
    temp = _val(p.get("temperature"))
    if not ts or temp is None:
        return None
    when = (
        datetime.fromisoformat(ts)
        .astimezone(timezone.utc)
        .replace(minute=0, second=0, microsecond=0)
    )
    elev = _val(p.get("elevation")) or 0.0
    loc = Location(name, lat, lon, elev, "live-obs", is_summit=is_summit)
    fc = LocationForecast(loc=loc, grid_elevation_m=elev, office="OBS", grid_x=0, grid_y=0)
    fc.hourly = {"temp_c": {when: temp}}
    for key, prop in (
        ("dewpoint_c", "dewpoint"),
        ("wind_kmh", "windSpeed"),
        ("gust_kmh", "windGust"),
        ("vis_m", "visibility"),
        ("rh_pct", "relativeHumidity"),
    ):
        v = _val(p.get(prop))
        if v is not None:
            fc.hourly[key] = {when: v}
    # stash the raw obs for the report (dynamic attr; LocationForecast isn't slotted)
    fc.observation = {
        "station": station,
        "timestamp": ts,
        "when": when,
        "text": p.get("textDescription"),
        "temp_c": temp,
        "dewpoint_c": _val(p.get("dewpoint")),
        "wind_kmh": _val(p.get("windSpeed")),
        "gust_kmh": _val(p.get("windGust")),
        "vis_m": _val(p.get("visibility")),
        "rh_pct": _val(p.get("relativeHumidity")),
    }
    return fc


def live_anchors() -> list[LocationForecast]:
    out = []
    for st in OBS_STATIONS:
        a = live_anchor(*st)
        if a is not None:
            out.append(a)
    return out


def observed_lapse(anchors: list[LocationForecast]):
    """Measured lapse rate (°C/1000 m) and inversion flag from the live anchors.

    Returns (lapse_c_per_1000m, inversion, detail) or (None, False, "") if there
    aren't enough stations. An inversion is when temperature *rises* with height
    across some layer (common at dawn / under high pressure) -- the linear lapse
    fit can't represent it, so we flag it explicitly.
    """
    pts = sorted(
        ((a.grid_elevation_m, a.observation["temp_c"], a.loc.name)
         for a in anchors if a.observation and a.observation.get("temp_c") is not None),
        key=lambda p: p[0],
    )
    if len(pts) < 2:
        return None, False, ""
    z0, t0, _ = pts[0]
    z1, t1, _ = pts[-1]
    lapse = (t1 - t0) / (z1 - z0) * 1000.0 if z1 != z0 else None
    inversion, detail = False, ""
    for (za, ta, na), (zb, tb, nb) in zip(pts, pts[1:]):
        if zb - za > 100 and tb - ta > 0.5:  # warmer higher up = inversion
            inversion = True
            detail = f"{na} ({ta:.0f}°C) colder than {nb} ({tb:.0f}°C) above it"
            break
    return lapse, inversion, detail


def obs_in_cloud(o: dict) -> bool | None:
    """Ground-truth in-cloud test from a station's measured visibility/humidity."""
    vis, rh = o.get("vis_m"), o.get("rh_pct")
    if vis is not None:
        return vis < 1609  # under ~1 mile -> effectively in fog/cloud
    if rh is not None:
        return rh >= 99
    return None
