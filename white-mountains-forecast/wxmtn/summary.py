"""Plain-language per-peak summaries and hazard callouts."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .fetch import LocationForecast
from .model import SummitEstimate, kmh_to_mph
from .score import best_window, composite, view_score
from .trailheads import for_peak

EASTERN = ZoneInfo("America/New_York")


def _fmt_window(w) -> str:
    a = w.start.astimezone(EASTERN).strftime("%-I%p").lower()
    if w.hours <= 1:
        return f"around {a}"
    b = w.end.astimezone(EASTERN).strftime("%-I%p").lower()
    return f"{a}–{b}"


def ridge_wind_note(all_fc: dict[str, LocationForecast], now: datetime) -> str | None:
    """If live summit wind is much stronger than the grid, ridges are windier."""
    obs = next(
        (fc for fc in all_fc.values()
         if getattr(fc, "observation", None) and fc.loc.is_summit), None)
    grid = all_fc.get("Mount Washington")
    if not obs or not grid:
        return None
    ow = obs.observation.get("wind_kmh")
    gw = grid.value("wind_kmh", now)
    if ow is None or gw is None or gw < 1:
        return None
    if ow > gw * 1.4 and kmh_to_mph(ow) > 25:
        return (f"Live summit wind is {kmh_to_mph(ow):.0f} mph vs ~{kmh_to_mph(gw):.0f} "
                "modeled — exposed ridges are running windier than the grid.")
    return None


def peak_summary(
    name: str, estimates: list[SummitEstimate], daylight: tuple[datetime, datetime] | None
) -> str:
    """One- or two-sentence call for a peak over the day's estimates."""
    if not daylight:
        day = estimates
    else:
        lo, hi = daylight
        day = [e for e in estimates if lo <= e.when <= hi] or estimates
    if not day:
        return "No data."

    temps = [e.temp_f for e in day if e.temp_f is not None]
    feels = [e.feels_like_f for e in day if e.feels_like_f is not None]
    winds = [e.wind_mph for e in day if e.wind_mph is not None]
    pops = [(e.when, e.pop_pct or 0) for e in day]

    view_win = best_window([(e.when, view_score(e)) for e in day], threshold=60)
    parts: list[str] = []

    if view_win and view_win.hours >= 1:
        parts.append(f"Clear views ~{_fmt_window(view_win)}")
    elif all(e.in_cloud for e in day):
        parts.append("In the clouds all day — no views")
    else:
        parts.append("Mostly socked in, only brief breaks")

    if temps:
        parts.append(f"{min(temps):.0f}–{max(temps):.0f}°F")
    if feels and min(feels) <= 35:
        parts.append(f"feels as cold as {min(feels):.0f}°F up high")
    if winds and max(winds) >= 25:
        parts.append(f"wind to {max(winds):.0f} mph")

    storm = max(pops, key=lambda p: p[1]) if pops else None
    if storm and storm[1] >= 30:
        when = storm[0].astimezone(EASTERN).strftime("%-I%p").lower()
        parts.append(f"storm risk ~{storm[1]:.0f}% around {when}")

    th = for_peak(name)
    tail = ""
    if th:
        tail = f" [{th.route}, {th.round_trip_mi:.1f} mi {th.difficulty}]"
    return "; ".join(parts) + "." + tail
