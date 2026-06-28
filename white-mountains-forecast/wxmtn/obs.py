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

# (station id, label, lat, lon, is_summit). KMWN = Mount Washington Observatory.
OBS_STATIONS = [
    ("KMWN", "Mount Washington summit (MWOBS, live)", 44.2706, -71.3033, True),
    ("KHIE", "Whitefield valley (live)", 44.3675, -71.5453, False),
    ("KLCI", "Laconia valley (live)", 43.5725, -71.4189, False),
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


def obs_in_cloud(o: dict) -> bool | None:
    """Ground-truth in-cloud test from a station's measured visibility/humidity."""
    vis, rh = o.get("vis_m"), o.get("rh_pct")
    if vis is not None:
        return vis < 1609  # under ~1 mile -> effectively in fog/cloud
    if rh is not None:
        return rh >= 99
    return None
