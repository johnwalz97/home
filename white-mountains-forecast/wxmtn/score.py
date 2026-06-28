"""Turn a summit estimate into a 0-100 'should I go' score, and find windows.

Three components, because hikers weigh different things:
  * view    -- is it clear, can you see anything (the whole point of a summit)
  * comfort -- temperature + wind chill in a pleasant band
  * safety  -- thunderstorms, high wind, being in cloud (navigation/lightning)
The composite weights view highest, then safety, then comfort.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .model import SummitEstimate


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


def view_score(e: SummitEstimate) -> float:
    if e.in_cloud:
        return 8.0
    if e.vis_mi is None:
        return 50.0
    return _clamp(e.vis_mi / 10.0 * 100.0)


def comfort_score(e: SummitEstimate) -> float:
    f = e.feels_like_f if e.feels_like_f is not None else e.temp_f
    if f is None:
        return 50.0
    # ideal 50-68°F, falls off either side
    temp_pen = 0.0 if 50 <= f <= 68 else (50 - f if f < 50 else f - 68) * 2.2
    wind = e.wind_mph or 0.0
    wind_pen = max(0.0, wind - 15) * 1.6   # above 15 mph starts to bite
    return _clamp(100 - temp_pen - wind_pen)


def safety_score(e: SummitEstimate) -> float:
    s = 100.0
    s -= (e.pop_pct or 0) * 0.8              # storm/precip chance
    s -= max(0.0, (e.wind_mph or 0) - 25) * 1.5
    s -= max(0.0, (e.gust_mph or 0) - 40) * 1.2
    if e.in_cloud:
        s -= 20                              # whiteout navigation risk
    return _clamp(s)


def composite(e: SummitEstimate) -> float:
    return round(
        0.45 * view_score(e) + 0.25 * comfort_score(e) + 0.30 * safety_score(e), 1
    )


@dataclass
class Window:
    start: datetime
    end: datetime
    avg_score: float
    hours: int


def best_window(
    scored: list[tuple[datetime, float]], threshold: float = 55.0
) -> Window | None:
    """Longest-then-best contiguous run of times scoring >= threshold."""
    best: Window | None = None
    run: list[tuple[datetime, float]] = []

    def flush(r):
        nonlocal best
        if not r:
            return
        avg = sum(s for _, s in r) / len(r)
        w = Window(r[0][0], r[-1][0], round(avg, 1), len(r))
        if best is None or (w.hours, w.avg_score) > (best.hours, best.avg_score):
            best = w

    for t, s in scored:
        if s >= threshold:
            run.append((t, s))
        else:
            flush(run)
            run = []
    flush(run)
    return best
