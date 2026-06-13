"""Render triangulated summit estimates as a human-readable forecast."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .fetch import LocationForecast
from .model import SummitEstimate, estimate

EASTERN = ZoneInfo("America/New_York")


def forecast_times(now: datetime, hours: int, step: int) -> list[datetime]:
    start = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [start + timedelta(hours=h) for h in range(0, hours + 1, step)]


def _fmt(v: float | None, suffix: str = "", nd: int = 0) -> str:
    if v is None:
        return " --"
    return f"{v:.{nd}f}{suffix}"


def summit_block(
    all_fc: dict[str, LocationForecast],
    summit: LocationForecast,
    times: list[datetime],
) -> str:
    loc = summit.loc
    head = (
        f"{loc.name}  ({loc.elevation_m*3.28084:.0f} ft / {loc.elevation_m:.0f} m"
        f", {loc.range})"
    )
    lines = [head, "-" * len(head)]
    lines.append(
        f"  {'When (EDT)':<17}{'Temp':>6}{'Feels':>7}{'Wind':>9}{'Gust':>7}"
        f"{'Sky':>6}{'Precip':>8}  Visibility"
    )
    for when in times:
        est = estimate(all_fc, summit, when)
        local = when.astimezone(EASTERN).strftime("%a %m/%d %H:%M")
        lines.append(
            f"  {local:<17}"
            f"{_fmt(est.temp_f, '°F'):>6}"
            f"{_fmt(est.feels_like_f, '°F'):>7}"
            f"{_fmt(est.wind_mph, ' mph'):>9}"
            f"{_fmt(est.gust_mph, ''):>7}"
            f"{_fmt(est.sky_pct, '%'):>6}"
            f"{_fmt(est.pop_pct, '%'):>8}"
            f"  {est.visibility_label}"
        )
    return "\n".join(lines)


def region_overview(
    all_fc: dict[str, LocationForecast],
    summits: list[LocationForecast],
    when: datetime,
) -> str:
    ests: list[SummitEstimate] = [estimate(all_fc, s, when) for s in summits]
    have_temp = [e for e in ests if e.temp_f is not None]
    local = when.astimezone(EASTERN).strftime("%a %m/%d %H:%M EDT")
    lines = [f"REGION SNAPSHOT — {local}", "=" * 60]
    if have_temp:
        coldest = min(have_temp, key=lambda e: e.temp_f)
        warmest = max(have_temp, key=lambda e: e.temp_f)
        avg = sum(e.temp_f for e in have_temp) / len(have_temp)
        lines.append(
            f"  Temps across the peaks avg {avg:.0f}°F"
            f"  (coldest {coldest.name} {coldest.temp_f:.0f}°F,"
            f" warmest {warmest.name} {warmest.temp_f:.0f}°F)"
        )
        lapse = next((e.lapse_c_per_1000m for e in ests if e.lapse_c_per_1000m), None)
        if lapse is not None:
            lines.append(
                f"  Fitted lapse rate: {abs(lapse):.1f} °C cooler per 1000 m climbed"
                f"  ({abs(lapse)*1.8/3.28084:.1f} °F per 1000 ft)"
            )
    socked = [e.name for e in ests if e.in_cloud]
    clear = [e.name for e in ests if not e.in_cloud and e.vis_mi and e.vis_mi >= 3]
    if socked:
        lines.append(f"  In the clouds / fogged in: {', '.join(socked)}")
    if clear:
        lines.append(f"  Likely clear views: {', '.join(clear)}")
    windy = [e for e in ests if e.wind_mph]
    if windy:
        worst = max(windy, key=lambda e: e.wind_mph)
        lines.append(
            f"  Strongest winds: {worst.name} ~{worst.wind_mph:.0f} mph"
            + (f" gusting {worst.gust_mph:.0f}" if worst.gust_mph else "")
        )
    return "\n".join(lines)


def full_report(
    all_fc: dict[str, LocationForecast],
    summits: list[LocationForecast],
    times: list[datetime],
) -> str:
    out = [
        "WHITE MOUNTAINS SUMMIT FORECAST (triangulated from NWS point data)",
        f"Generated {datetime.now(EASTERN):%Y-%m-%d %H:%M EDT}",
        f"Stations/points used: {len(all_fc)}  |  summits forecast: {len(summits)}",
        "",
        region_overview(all_fc, summits, times[0]),
        "",
    ]
    for s in summits:
        out.append(summit_block(all_fc, s, times))
        out.append("")
    out.append(
        "Method: temperature is a least-squares lapse-rate fit over all points,"
        " evaluated at each true summit elevation; visibility blends the NWS grid"
        " visibility with a lifting-condensation-level cloud-base estimate."
    )
    return "\n".join(out)
