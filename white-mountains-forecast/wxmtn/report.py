"""Render triangulated summit estimates as a human-readable forecast."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .alerts import active as active_alerts
from .alerts import mountain_relevant
from .astro import sun_times
from .fetch import LocationForecast
from .model import (
    SummitEstimate,
    c_to_f,
    estimate,
    kmh_to_mph,
    m_to_mi,
    summit_temp_bias_c,
)
from .obs import obs_in_cloud, observed_lapse
from .score import best_window, composite
from .summary import peak_summary, ridge_wind_note

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
    *,
    bias_c: float = 0.0,
    bias_from: datetime | None = None,
    daylight: tuple[datetime, datetime] | None = None,
) -> str:
    loc = summit.loc
    head = (
        f"{loc.name}  ({loc.elevation_m*3.28084:.0f} ft / {loc.elevation_m:.0f} m"
        f", {loc.range})"
    )
    ests = [estimate(all_fc, summit, w, bias_c=bias_c, bias_from=bias_from) for w in times]
    # Summaries need hourly resolution so view windows aren't quantized to the
    # (possibly coarse) display step.
    span_h = int((times[-1] - times[0]).total_seconds() // 3600)
    hourly_times = [times[0] + timedelta(hours=i) for i in range(span_h + 1)]
    hourly_ests = [
        estimate(all_fc, summit, w, bias_c=bias_c, bias_from=bias_from)
        for w in hourly_times
    ]
    lines = [head, "-" * len(head)]
    lines.append("  " + peak_summary(loc.name, hourly_ests, daylight))
    lines.append(
        f"  {'When (EDT)':<17}{'Temp':>6}{'Feels':>7}{'Wind':>9}{'Gust':>7}"
        f"{'Sky':>6}{'Precip':>8}  Visibility"
    )
    for when, est in zip(times, ests):
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
    *,
    bias_c: float = 0.0,
    bias_from: datetime | None = None,
) -> str:
    ests: list[SummitEstimate] = [
        estimate(all_fc, s, when, bias_c=bias_c, bias_from=bias_from) for s in summits
    ]
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
    anchors = [fc for fc in all_fc.values() if getattr(fc, "observation", None)]
    obs_lapse, inversion, detail = observed_lapse(anchors)
    if obs_lapse is not None:
        msg = f"  Observed lapse (live stations): {abs(obs_lapse):.1f} °C/1000 m"
        if inversion:
            msg += f"  — INVERSION aloft: {detail}"
        lines.append(msg)
    if bias_c:
        sign = "warmer" if bias_c > 0 else "colder"
        lines.append(
            f"  Live obs ran {abs(bias_c)*1.8:.1f}°F {sign} than the grid on the"
            " summit now; applied (decaying) to near-term temps."
        )
    rn = ridge_wind_note(all_fc, when)
    if rn:
        lines.append(f"  {rn}")
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


def daylight_window(loc, day) -> tuple[datetime, datetime] | None:
    s = sun_times(day, loc.lat, loc.lon)
    if s.get("sunrise") and s.get("sunset"):
        return s["sunrise"], s["sunset"]
    return None


def full_report(
    all_fc: dict[str, LocationForecast],
    summits: list[LocationForecast],
    times: list[datetime],
) -> str:
    now = times[0]
    bias_c = summit_temp_bias_c(all_fc, now) or 0.0
    ref = summits[0].loc if summits else None
    sun = sun_times(now.astimezone(EASTERN).date(), ref.lat, ref.lon) if ref else {}
    daylight = (sun.get("sunrise"), sun.get("sunset")) if sun.get("sunrise") else None

    out = [
        "WHITE MOUNTAINS SUMMIT FORECAST (triangulated from NWS point data)",
        f"Generated {datetime.now(EASTERN):%Y-%m-%d %H:%M EDT}",
        f"Stations/points used: {len(all_fc)}  |  summits forecast: {len(summits)}",
        "",
    ]
    if sun.get("sunrise") and sun.get("sunset"):
        sr = sun["sunrise"].astimezone(EASTERN).strftime("%-I:%M%p").lower()
        ss = sun["sunset"].astimezone(EASTERN).strftime("%-I:%M%p").lower()
        line = f"Daylight: {sr} – {ss}"
        if sun.get("golden_pm"):
            g0, g1 = sun["golden_pm"]
            line += (f"  |  PM golden hour ~{g0.astimezone(EASTERN):%-I:%M%p}".lower()
                     + f"–{g1.astimezone(EASTERN):%-I:%M%p}".lower())
        out += [line, ""]

    al = mountain_relevant(active_alerts("NH") + active_alerts("ME"))
    if al:
        out.append("⚠ ACTIVE NWS ALERTS")
        for a in al[:6]:
            out.append(f"  - {a['event']}: {a.get('headline') or a.get('area')}")
        out.append("")

    live = live_conditions_block(all_fc)
    if live:
        out += [live, ""]
    out += [region_overview(all_fc, summits, now, bias_c=bias_c, bias_from=now), ""]
    for s in summits:
        out.append(summit_block(all_fc, s, times, bias_c=bias_c, bias_from=now,
                                daylight=daylight))
        out.append("")
    out.append(
        "Method: temperature is a least-squares lapse-rate fit over all points,"
        " evaluated at each true summit elevation; visibility blends the NWS grid"
        " visibility with a lifting-condensation-level cloud-base estimate. Live"
        " station obs (incl. the Mount Washington Obs summit) anchor the current"
        " hour to measured reality."
    )
    return "\n".join(out)


def _rank(all_fc, summits, times, bias_c, now, daylight):
    """Score each summit over today's daylight; return [(score, name, window)]."""
    ranked = []
    span_h = int((times[-1] - times[0]).total_seconds() // 3600)
    hours = [times[0] + timedelta(hours=i) for i in range(span_h + 1)]
    for s in summits:
        ests = [estimate(all_fc, s, w, bias_c=bias_c, bias_from=now) for w in hours]
        if daylight:
            lo, hi = daylight
            day = [e for e in ests if lo <= e.when <= hi] or ests
        else:
            day = ests
        scored = [(e.when, composite(e)) for e in day]
        win = best_window(scored, threshold=55)
        # Headline score = best sustained window average (spreads peaks apart on
        # good days better than a single peak hour, which saturates at 100).
        score_val = win.avg_score if win else max((s2 for _, s2 in scored), default=0.0)
        ranked.append((score_val, s, win))
    ranked.sort(key=lambda r: (r[0], r[2].hours if r[2] else 0), reverse=True)
    return ranked


def rank_report(all_fc, summits, times) -> str:
    now = times[0]
    bias_c = summit_temp_bias_c(all_fc, now) or 0.0
    ref = summits[0].loc if summits else None
    sun = sun_times(now.astimezone(EASTERN).date(), ref.lat, ref.lon) if ref else {}
    daylight = (sun.get("sunrise"), sun.get("sunset")) if sun.get("sunrise") else None
    ranked = _rank(all_fc, summits, times, bias_c, now, daylight)
    out = [f"PEAK RANKING — best bets for {now.astimezone(EASTERN):%a %m/%d}", "=" * 60]
    for i, (sc, s, win) in enumerate(ranked, 1):
        w = (f"best window {_fmt_window_h(win)}" if win else "no good window")
        out.append(f"  {i:>2}. {s.loc.name:<24} score {sc:>4.0f}/100  — {w}")
    return "\n".join(out)


def _fmt_window_h(win) -> str:
    a = win.start.astimezone(EASTERN).strftime("%-I%p").lower()
    if win.hours <= 1:
        return f"around {a}"
    b = win.end.astimezone(EASTERN).strftime("%-I%p").lower()
    return f"{a}–{b} (score {win.avg_score:.0f})"


def brief_report(all_fc, summits, times) -> str:
    now = times[0]
    bias_c = summit_temp_bias_c(all_fc, now) or 0.0
    ref = summits[0].loc if summits else None
    sun = sun_times(now.astimezone(EASTERN).date(), ref.lat, ref.lon) if ref else {}
    daylight = (sun.get("sunrise"), sun.get("sunset")) if sun.get("sunrise") else None
    ranked = _rank(all_fc, summits, times, bias_c, now, daylight)

    out = [f"MORNING BRIEF — {now.astimezone(EASTERN):%A %B %-d}", "=" * 60]
    al = mountain_relevant(active_alerts("NH") + active_alerts("ME"))
    if al:
        out.append(f"  ⚠ {len(al)} active alert(s): " + "; ".join(a["event"] for a in al[:3]))
    obs = next((fc for fc in all_fc.values()
                if getattr(fc, "observation", None) and fc.loc.is_summit), None)
    if obs:
        o = obs.observation
        from .model import c_to_f as _f, kmh_to_mph as _w
        out.append(f"  Summit now (MWObs): {_f(o['temp_c']):.0f}°F, "
                   f"wind {_w(o['wind_kmh']):.0f} mph, "
                   f"{'in cloud' if (o.get('vis_m') or 1e9) < 1609 else 'clear'}.")
    out.append("")
    out.append("  Today's best bets:")
    span_h = int((times[-1] - times[0]).total_seconds() // 3600)
    hours = [times[0] + timedelta(hours=i) for i in range(span_h + 1)]
    for sc, s, win in ranked[:3]:
        ests = [estimate(all_fc, s, w, bias_c=bias_c, bias_from=now) for w in hours]
        out.append(f"  • {s.loc.name} (score {sc:.0f}/100)")
        out.append(f"      {peak_summary(s.loc.name, ests, daylight)}")
    return "\n".join(out)


def spots_block(spot_fc: dict[str, LocationForecast], times: list[datetime]) -> str:
    """Low spots are reported straight from their own grid cell -- they're near
    sea/valley level so no lapse correction is needed (and Camden is coastal,
    far from the White Mountain lapse fit)."""
    out = ["LOWER-ELEVATION SPOTS (direct grid forecast)", "=" * 60]
    for fc in spot_fc.values():
        out.append(f"  {fc.loc.name} ({fc.loc.elevation_m*3.28084:.0f} ft, {fc.loc.range})")
        for w in times:
            t = fc.value("temp_c", w)
            wind = fc.value("wind_kmh", w)
            pop = fc.value("pop_pct", w)
            vis = fc.value("vis_m", w)
            sky = "fog/low cloud" if vis is not None and vis < 1609 else "clear"
            local = w.astimezone(EASTERN).strftime("%a %H:%M")
            out.append(
                f"      {local}  {_fmt(c_to_f(t) if t is not None else None,'°F')}, "
                f"wind {_fmt(kmh_to_mph(wind) if wind is not None else None,' mph')}, "
                f"{_fmt(pop,'% rain')}, {sky}"
            )
    return "\n".join(out)
