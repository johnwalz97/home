"""Turn NWS gridpoint time series into plain hourly lookups.

Each gridpoint property looks like::

    {"uom": "wmoUnit:degC",
     "values": [{"validTime": "2026-06-13T08:00:00+00:00/PT4H", "value": 7.7}, ...]}

The ``validTime`` is an ISO-8601 ``start/duration`` interval, and values are
emitted sparsely (only when they change), so a single entry can cover many
hours. We expand each entry across the hours it spans and index by the UTC hour
so different variables can be lined up by time.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_DUR = re.compile(
    r"P(?:(?P<d>\d+)D)?(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?)?"
)


def parse_duration(text: str) -> timedelta:
    """Parse the subset of ISO-8601 durations the NWS emits (days/h/m/s)."""
    m = _DUR.fullmatch(text)
    if not m:
        raise ValueError(f"unparseable duration: {text}")
    p = {k: int(v) if v else 0 for k, v in m.groupdict().items()}
    return timedelta(days=p["d"], hours=p["h"], minutes=p["m"], seconds=p["s"])


def hourly(prop: dict) -> dict[datetime, float]:
    """Expand one gridpoint property into ``{utc_hour: value}``."""
    out: dict[datetime, float] = {}
    if not prop:
        return out
    for entry in prop.get("values", []):
        start_s, dur_s = entry["validTime"].split("/")
        start = datetime.fromisoformat(start_s).astimezone(timezone.utc)
        # snap to the top of the hour so different variables align
        start = start.replace(minute=0, second=0, microsecond=0)
        span = parse_duration(dur_s)
        hours = max(1, int(span.total_seconds() // 3600))
        for i in range(hours):
            out[start + timedelta(hours=i)] = entry["value"]
    return out


def at(series: dict[datetime, float], when: datetime) -> float | None:
    """Look up a value at a UTC hour, tolerating small gaps (±2h)."""
    when = when.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    for delta in (0, -1, 1, -2, 2):
        v = series.get(when + timedelta(hours=delta))
        if v is not None:
            return v
    return None
