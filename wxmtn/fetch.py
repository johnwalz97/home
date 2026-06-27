"""Download and assemble per-location hourly forecast series."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from . import nws, series
from .peaks import Location

# gridpoint property name -> friendly key
_VARS = {
    "temperature": "temp_c",
    "dewpoint": "dewpoint_c",
    "skyCover": "sky_pct",
    "visibility": "vis_m",
    "windSpeed": "wind_kmh",
    "windGust": "gust_kmh",
    "probabilityOfPrecipitation": "pop_pct",
    "relativeHumidity": "rh_pct",
}


@dataclass
class LocationForecast:
    loc: Location
    grid_elevation_m: float
    office: str
    grid_x: int
    grid_y: int
    # friendly key -> {utc_hour: value}
    hourly: dict[str, dict[datetime, float]] = field(default_factory=dict)

    def value(self, key: str, when: datetime) -> float | None:
        return series.at(self.hourly.get(key, {}), when)


def fetch_location(loc: Location) -> LocationForecast:
    meta = nws.point(loc.lat, loc.lon)
    raw = nws.gridpoint_raw(meta["gridId"], meta["gridX"], meta["gridY"])
    grid_elev = (raw.get("elevation") or {}).get("value", loc.elevation_m)
    fc = LocationForecast(
        loc=loc,
        grid_elevation_m=grid_elev,
        office=meta["gridId"],
        grid_x=meta["gridX"],
        grid_y=meta["gridY"],
    )
    for prop, key in _VARS.items():
        fc.hourly[key] = series.hourly(raw.get(prop, {}))
    return fc


def fetch_all(locations: list[Location]) -> dict[str, LocationForecast]:
    out: dict[str, LocationForecast] = {}
    for loc in locations:
        out[loc.name] = fetch_location(loc)
    return out
