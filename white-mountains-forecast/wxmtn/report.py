"""Render triangulated summit estimates as a human-readable forecast."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .fetch import LocationForecast
from .model import SummitEstimate, c_to_f, estimate, kmh_to_mph, m_to_mi
from .obs import obs_in_cloud

EASTERN = ZoneInfo("America/New_York")


def live_conditions_block(all_fc: dict[str, LocationForecast]) -> str:
    """Show measured 'right now' obs (esp. Mount Washington) and validate the model."""
    obs_fcs = [fc for fc in all_fc.values() if getattr(fc, "observation", None)]
    if not obs_fcs:
        return ""
    lines = ["LIVE OBSERVATIONS — measured right now", "=" * 60]
    for fc in sorted(obs_fcs, key=lambda f: -f.grid_elevation_m):
        o = fc.observation
        local = o["when"].astimezone(EASTERN).strftime("%H:%M EDT")
        t = f"{c_to_f(o['temp_c']):.0f}°F" if o["temp_c"] is not None else "--"
        w = f"{kmh_to_mph(o['wind_kmh']):.0f} mph" if o["wind_kmh"] is not None else "--"
        vis = f"{m_to_mi(o['vis_m']):.0f} mi" if o["vis_m"] is not None else "--"
        cloud = obs_in_cloud(o)
        sky = "IN CLOUD/FOG" if cloud else "clear of cloud" if cloud is False else "?"
        extra = f", {o['text']}" if o.get("text") else ""
        lines.append(f"  {fc.loc.name} (~{fc.grid_elevation_m*3.28084:.0f} ft, {local})")
        lines.append(f"      {t}, wind {w}, visibility {vis} — {sky}{extra}")
    return "\n".join(lines)


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
    ]
    live = live_conditions_block(all_fc)
    if live:
        out += [live, ""]
    out += [region_overview(all_fc, summits, times[0]), ""]
    for s in summits:
        out.append(summit_block(all_fc, s, times))
        out.append("")
    out.append(
        "Method: temperature is a least-squares lapse-rate fit over all points,"
        " evaluated at each true summit elevation; visibility blends the NWS grid"
        " visibility with a lifting-condensation-level cloud-base estimate. Live"
        " station obs (incl. the Mount Washington Obs summit) anchor the current"
        " hour to measured reality."
    )
    return "\n".join(out)
