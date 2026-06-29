"""Build a standalone, interactive HTML report.

`build_payload()` assembles the forecast data; `render_html()` injects it into
the design template at ``wxmtn/template.html`` (the "DATUM" field-instrument UI:
ranked list, Leaflet map with a basemap/overlay switcher, per-peak detail with an
arc gauge + sparkline, and a slide-rule time scrubber that recolours everything
as you scrub). The template is responsive (3-bay console on desktop, Map/List/
Detail tabs + a full-width scrubber on mobile) and degrades gracefully if the
Leaflet CDN is unreachable. All forecast data is embedded inline.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .fetch import LocationForecast
from .model import ascent_profile, estimate, summit_temp_bias_c
from .astro import sun_times
from .alerts import active as active_alerts
from .alerts import mountain_relevant
from .score import best_window, composite
from .summary import peak_summary
from .trailheads import for_peak

EASTERN = ZoneInfo("America/New_York")


def _hour_label(when: datetime) -> str:
    return when.astimezone(EASTERN).strftime("%a %-I%p").lower()


def _fmt_win(win):
    if not win:
        return None
    if win.hours > 1:
        return (f"{win.start.astimezone(EASTERN):%-I%p}–"
                f"{win.end.astimezone(EASTERN):%-I%p}").lower()
    return f"around {win.start.astimezone(EASTERN):%-I%p}".lower()


def _aggregate_days(h_ests, loc):
    """Per-calendar-day rollup (daylight-focused) for the multi-day planner."""
    bydate = {}
    for e in h_ests:
        bydate.setdefault(e.when.astimezone(EASTERN).date(), []).append(e)
    days = []
    for d in sorted(bydate):
        s = sun_times(d, loc.lat, loc.lon)
        dl = (s.get("sunrise"), s.get("sunset")) if s.get("sunrise") else None
        ests_d = bydate[d]
        day_ests = ([e for e in ests_d if dl[0] <= e.when <= dl[1]] or ests_d) if dl else ests_d
        scored = [(e.when, composite(e)) for e in day_ests]
        win = best_window(scored, threshold=55)
        dscore = round(win.avg_score) if win else round(max((x for _, x in scored), default=0))
        temps = [e.temp_f for e in ests_d if e.temp_f is not None]
        cloud_pct = round(100 * sum(1 for e in day_ests if e.in_cloud) / max(1, len(day_ests)))
        days.append({
            "date": d.isoformat(),
            "label": d.strftime("%a %-m/%-d").lower(),
            "weekday": d.strftime("%a"),
            "score": dscore,
            "best_window": _fmt_win(win),
            "hi": round(max(temps)) if temps else None,
            "lo": round(min(temps)) if temps else None,
            "cloud_pct": cloud_pct,
            "sunrise": s["sunrise"].astimezone(EASTERN).strftime("%-I:%M%p").lower() if s.get("sunrise") else None,
            "sunset": s["sunset"].astimezone(EASTERN).strftime("%-I:%M%p").lower() if s.get("sunset") else None,
        })
    return days


def _hazards(h_ests, loc):
    """Plain-language hazard flags from the next ~36h of daytime conditions."""
    near = h_ests[:36]
    winds = [e.wind_mph for e in near if e.wind_mph is not None]
    gusts = [e.gust_mph for e in near if e.gust_mph is not None]
    feels = [e.feels_like_f for e in near if e.feels_like_f is not None]
    pops = [e.pop_pct for e in near if e.pop_pct is not None]
    temps = [e.temp_f for e in near if e.temp_f is not None]
    flags = []
    if gusts and max(gusts) >= 45:
        flags.append({"l": "warn", "t": f"High wind · gusts {round(max(gusts))} mph"})
    elif winds and max(winds) >= 30:
        flags.append({"l": "warn", "t": f"Windy · to {round(max(winds))} mph"})
    if feels and min(feels) <= 20:
        flags.append({"l": "warn", "t": f"Wind chill to {round(min(feels))}°F"})
    elif temps and min(temps) <= 32:
        flags.append({"l": "info", "t": "Below freezing up high"})
    if pops and max(pops) >= 40:
        flags.append({"l": "warn", "t": f"Thunder/precip risk {round(max(pops))}%"})
    if loc.elevation_m * 3.28084 >= 4500:
        flags.append({"l": "info", "t": "Above treeline · fully exposed"})
    return flags


def _peak_payload(all_fc, summit, times, hourly, bias_c, now, daylight):
    ests = [estimate(all_fc, summit, w, bias_c=bias_c, bias_from=now) for w in times]
    h_ests = [estimate(all_fc, summit, w, bias_c=bias_c, bias_from=now) for w in hourly]
    scored = [(e.when, composite(e)) for e in h_ests]
    if daylight:
        lo, hi = daylight
        day = [s for s in scored if lo <= s[0] <= hi] or scored
    else:
        day = scored
    win = best_window(day, threshold=55)
    day_score = round(win.avg_score, 0) if win else (
        round(max((s for _, s in day), default=0), 0))
    days = _aggregate_days(h_ests, summit.loc)
    best_day = max(days, key=lambda x: x["score"]) if days else None
    th = for_peak(summit.loc.name)
    # "Weather as you climb" — a band-by-band ascent profile at today's best hour
    start_m = th.start_elev_m if th else max(300.0, summit.loc.elevation_m - 900)
    asc_when = win.start if win else now
    ascent = ascent_profile(all_fc, summit, asc_when, start_m)
    if ascent:
        ascent["at"] = asc_when.astimezone(EASTERN).strftime("%a %-I%p").lower()
    return {
        "name": summit.loc.name,
        "lat": summit.loc.lat,
        "lon": summit.loc.lon,
        "elev_ft": round(summit.loc.elevation_m * 3.28084),
        "range": summit.loc.range,
        "type": "summit",
        "day_score": day_score,
        "best_window": _fmt_win(win),
        "days": days,
        "best_day": ({"label": best_day["label"], "score": best_day["score"],
                      "window": best_day["best_window"]} if best_day else None),
        "flags": _hazards(h_ests, summit.loc),
        "summary": peak_summary(summit.loc.name, h_ests, daylight),
        "trailhead": (f"{th.route} · {th.round_trip_mi:.1f} mi · {th.difficulty}"
                      if th else None),
        "difficulty": th.difficulty if th else None,
        "ascent": ascent,
        "hours": [
            {
                "t": _hour_label(e.when),
                "temp": round(e.temp_f) if e.temp_f is not None else None,
                "feels": round(e.feels_like_f) if e.feels_like_f is not None else None,
                "wind": round(e.wind_mph) if e.wind_mph is not None else None,
                "gust": round(e.gust_mph) if e.gust_mph is not None else None,
                "wdir": (round(summit.value("wind_dir_deg", e.when))
                         if summit.value("wind_dir_deg", e.when) is not None else None),
                "pop": round(e.pop_pct) if e.pop_pct is not None else None,
                "vis": e.visibility_label,
                "cloud": e.in_cloud,
                "score": round(composite(e)),
            }
            for e in ests
        ],
    }


def _spot_payload(fc, times):
    from .model import c_to_f, kmh_to_mph
    rows = []
    for w in times:
        t = fc.value("temp_c", w)
        wind = fc.value("wind_kmh", w)
        pop = fc.value("pop_pct", w)
        vis = fc.value("vis_m", w)
        rows.append({
            "t": _hour_label(w),
            "temp": round(c_to_f(t)) if t is not None else None,
            "feels": None,
            "wind": round(kmh_to_mph(wind)) if wind is not None else None,
            "gust": None,
            "pop": round(pop) if pop is not None else None,
            "vis": "fog/low cloud" if (vis is not None and vis < 1609) else "clear",
            "cloud": bool(vis is not None and vis < 1609),
            "score": None,
        })
    return {
        "name": fc.loc.name, "lat": fc.loc.lat, "lon": fc.loc.lon,
        "elev_ft": round(fc.loc.elevation_m * 3.28084), "range": fc.loc.range,
        "type": "spot", "day_score": None, "best_window": None,
        "summary": None, "trailhead": None, "hours": rows,
    }


def build_payload(all_fc, summits, times, spot_fc=None) -> dict:
    now = times[0]
    bias_c = summit_temp_bias_c(all_fc, now) or 0.0
    ref = summits[0].loc
    sun = sun_times(now.astimezone(EASTERN).date(), ref.lat, ref.lon)
    daylight = (sun.get("sunrise"), sun.get("sunset")) if sun.get("sunrise") else None
    # an hourly grid for scoring even if the display step is coarse
    span_h = int((times[-1] - times[0]).total_seconds() // 3600)
    hourly = [times[0] + timedelta(hours=i) for i in range(span_h + 1)]

    peaks_pl = [_peak_payload(all_fc, s, times, hourly, bias_c, now, daylight)
                for s in summits]
    if spot_fc:
        peaks_pl += [_spot_payload(fc, times) for fc in spot_fc.values()]

    # Planner: for each forecast day, rank the peaks by that day's score.
    planner = []
    canon = next((p["days"] for p in peaks_pl if p.get("days")), [])
    for i, dref in enumerate(canon):
        ranked = sorted(
            (p for p in peaks_pl if p.get("days") and i < len(p["days"])),
            key=lambda p: p["days"][i]["score"], reverse=True)
        planner.append({
            "label": dref["label"], "weekday": dref["weekday"],
            "sunrise": dref.get("sunrise"), "sunset": dref.get("sunset"),
            "top": [{"name": p["name"], "score": p["days"][i]["score"],
                     "window": p["days"][i]["best_window"],
                     "elev_ft": p["elev_ft"]} for p in ranked[:6]],
        })

    obs = next((fc for fc in all_fc.values()
                if getattr(fc, "observation", None) and fc.loc.is_summit), None)
    summit_now = None
    if obs:
        from .model import c_to_f, kmh_to_mph
        o = obs.observation
        summit_now = {
            "temp": round(c_to_f(o["temp_c"])) if o.get("temp_c") is not None else None,
            "wind": round(kmh_to_mph(o["wind_kmh"])) if o.get("wind_kmh") is not None else None,
            "vis_mi": round(o["vis_m"] / 1609.344, 1) if o.get("vis_m") is not None else None,
            "cloud": bool(o.get("vis_m") is not None and o["vis_m"] < 1609),
        }
    al = mountain_relevant(active_alerts("NH") + active_alerts("ME"))
    return {
        "generated": datetime.now(EASTERN).strftime("%A %B %-d, %-I:%M%p").replace("AM", "am").replace("PM", "pm"),
        "labels": [_hour_label(w) for w in times],
        "sunrise": sun["sunrise"].astimezone(EASTERN).strftime("%-I:%M%p").lower() if sun.get("sunrise") else None,
        "sunset": sun["sunset"].astimezone(EASTERN).strftime("%-I:%M%p").lower() if sun.get("sunset") else None,
        "summit_now": summit_now,
        "alerts": [a["event"] for a in al[:5]],
        "day_labels": [d["label"] for d in canon],
        "planner": planner,
        "peaks": peaks_pl,
    }


def render_html(payload: dict) -> str:
    """Inject the JSON payload into the standalone HTML template (wxmtn/template.html)."""
    from pathlib import Path
    data = json.dumps(payload)
    tpl = (Path(__file__).resolve().parent / "template.html").read_text()
    return tpl.replace("/*__DATA__*/null", data)
