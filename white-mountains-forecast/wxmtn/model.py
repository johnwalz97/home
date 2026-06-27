"""The triangulation model: turn a cloud of point forecasts into a summit estimate.

Two physical ideas do the work here:

1. **Temperature lapse rate.** Across the region at any given hour, temperature
   falls roughly linearly with elevation. We least-squares fit ``T = a + b*z``
   using every point we downloaded (summits *and* valley anchors), then evaluate
   that line at each summit's *true* elevation. This corrects for the fact that
   the NWS grid can't resolve a sharp peak and reports a smoothed, too-low
   elevation (and therefore a too-warm temperature) for the summit cell.

2. **Cloud base / "in the clouds".** A summit's visibility is usually dictated
   by whether it pokes into cloud. We estimate the lifting condensation level
   (cloud base) from the valley temperature/dewpoint spread -- Espy's rule,
   ~125 m of base height per °C of spread -- and compare it to the summit
   elevation. If the summit is at or above cloud base it's likely fogged in,
   which we fold together with the grid's own visibility forecast.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .fetch import LocationForecast

# Standard environmental lapse rate, used only as a fallback when a regression
# can't be fit (≈6.5 °C per 1000 m).
FALLBACK_LAPSE_C_PER_M = -0.0065
LCL_M_PER_C = 125.0  # Espy approximation for cloud-base height per °C spread


def c_to_f(c: float) -> float:
    return c * 9 / 5 + 32


def kmh_to_mph(k: float) -> float:
    return k * 0.621371


def m_to_mi(m: float) -> float:
    return m / 1609.344


def _fit_line(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Ordinary least squares ``y = a + b*x``; returns (a, b) or None."""
    n = len(points)
    if n < 2:
        return None
    sx = sum(x for x, _ in points)
    sy = sum(y for _, y in points)
    sxx = sum(x * x for x, _ in points)
    sxy = sum(x * y for x, y in points)
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-9:
        return None
    b = (n * sxy - sx * sy) / denom
    a = (sy - b * sx) / n
    return a, b


@dataclass
class SummitEstimate:
    name: str
    when: datetime
    temp_f: float | None
    lapse_c_per_1000m: float | None
    wind_mph: float | None
    gust_mph: float | None
    sky_pct: float | None
    pop_pct: float | None
    vis_mi: float | None
    cloud_base_m: float | None
    in_cloud: bool
    visibility_label: str
    feels_like_f: float | None


def _lapse_temp(
    all_fc: dict[str, LocationForecast], summit: LocationForecast, when: datetime
) -> tuple[float | None, float | None]:
    """Estimate summit temperature (°C) and the fitted lapse rate (°C/1000 m)."""
    pts: list[tuple[float, float]] = []
    for fc in all_fc.values():
        t = fc.value("temp_c", when)
        if t is not None:
            pts.append((fc.grid_elevation_m, t))
    fit = _fit_line(pts)
    if fit is None:
        base = summit.value("temp_c", when)
        return base, None
    a, b = fit
    # constrain to a physically sane lapse (avoid wild slopes from sparse data)
    b = max(min(b, 0.0), -0.012)
    return a + b * summit.loc.elevation_m, b * 1000.0


def _cloud_base_m(all_fc: dict[str, LocationForecast], when: datetime) -> float | None:
    """Lifting condensation level (m MSL) from the lowest available anchor."""
    lowest: LocationForecast | None = None
    for fc in all_fc.values():
        if lowest is None or fc.grid_elevation_m < lowest.grid_elevation_m:
            if fc.value("temp_c", when) is not None and fc.value("dewpoint_c", when) is not None:
                lowest = fc
    if lowest is None:
        return None
    t = lowest.value("temp_c", when)
    td = lowest.value("dewpoint_c", when)
    spread = max(0.0, t - td)
    return lowest.grid_elevation_m + LCL_M_PER_C * spread


def _wind_chill_f(temp_f: float | None, wind_mph: float | None) -> float | None:
    if temp_f is None or wind_mph is None:
        return None
    if temp_f > 50 or wind_mph < 3:
        return temp_f
    v = wind_mph ** 0.16
    return 35.74 + 0.6215 * temp_f - 35.75 * v + 0.4275 * temp_f * v


def estimate(
    all_fc: dict[str, LocationForecast], summit: LocationForecast, when: datetime
) -> SummitEstimate:
    temp_c, lapse = _lapse_temp(all_fc, summit, when)
    temp_f = c_to_f(temp_c) if temp_c is not None else None

    wind = summit.value("wind_kmh", when)
    gust = summit.value("gust_kmh", when)
    wind_mph = kmh_to_mph(wind) if wind is not None else None
    gust_mph = kmh_to_mph(gust) if gust is not None else None

    sky = summit.value("sky_pct", when)
    pop = summit.value("pop_pct", when)
    vis_m = summit.value("vis_m", when)

    cloud_base = _cloud_base_m(all_fc, when)
    in_cloud = cloud_base is not None and summit.loc.elevation_m >= cloud_base

    label, vis_mi = _visibility(vis_m, in_cloud, sky)
    feels = _wind_chill_f(temp_f, wind_mph)

    return SummitEstimate(
        name=summit.loc.name,
        when=when,
        temp_f=temp_f,
        lapse_c_per_1000m=lapse,
        wind_mph=wind_mph,
        gust_mph=gust_mph,
        sky_pct=sky,
        pop_pct=pop,
        vis_mi=vis_mi,
        cloud_base_m=cloud_base,
        in_cloud=in_cloud,
        visibility_label=label,
        feels_like_f=feels,
    )


def _visibility(
    vis_m: float | None, in_cloud: bool, sky_pct: float | None
) -> tuple[str, float | None]:
    """Combine the grid visibility forecast with the in-cloud test into a label."""
    vis_mi = m_to_mi(vis_m) if vis_m is not None else None
    # If the summit is above cloud base, cap the usable visibility low regardless
    # of what the (valley-biased) grid says.
    if in_cloud:
        if vis_mi is None or vis_mi > 0.25:
            vis_mi = min(vis_mi or 0.1, 0.1)
    if vis_mi is None:
        return "unknown", None
    if vis_mi < 0.06:
        return "in the clouds — near zero (<100 m)", vis_mi
    if vis_mi < 0.25:
        return "fogged in — very poor", vis_mi
    if vis_mi < 1:
        return "poor", vis_mi
    if vis_mi < 3:
        return "moderate / hazy", vis_mi
    if vis_mi < 10:
        return "good", vis_mi
    return "excellent (clear)", vis_mi
