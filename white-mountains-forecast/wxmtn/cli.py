"""Command-line entry point.

    python -m wxmtn                 # 48h report, every 6h, all summits
    python -m wxmtn --hours 24 --step 3
    python -m wxmtn --peak Washington --peak Lafayette
    python -m wxmtn --json > forecast.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from . import fetch, obs, peaks, report
from .model import estimate


def _select_summits(names: list[str]):
    if not names:
        return list(peaks.SUMMITS)
    out = []
    for s in peaks.SUMMITS:
        if any(n.lower() in s.name.lower() for n in names):
            out.append(s)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="wxmtn", description="Triangulated White Mountains summit forecast."
    )
    ap.add_argument("--hours", type=int, default=48, help="forecast horizon (default 48)")
    ap.add_argument("--step", type=int, default=6, help="hours between rows (default 6)")
    ap.add_argument(
        "--peak", action="append", default=[], help="filter to summit(s) by name substring"
    )
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument(
        "--no-live", action="store_true", help="skip live station observations"
    )
    args = ap.parse_args(argv)

    summits = _select_summits(args.peak)
    if not summits:
        print("No summits matched.", file=sys.stderr)
        return 2

    # Always fetch every location so the lapse-rate fit has the full elevation
    # spread, even when the user filters the displayed summits.
    print("Fetching NWS point data...", file=sys.stderr)
    all_fc = fetch.fetch_all(peaks.ALL)
    summit_fc = [all_fc[s.name] for s in summits]

    # Fold in live observations (incl. the Mount Washington Obs summit station)
    # as real-time anchors so the current hour is pinned to measured reality.
    if not args.no_live:
        for anchor in obs.live_anchors():
            all_fc[anchor.loc.name] = anchor

    now = datetime.now(timezone.utc)
    times = report.forecast_times(now, args.hours, args.step)

    if args.json:
        payload = {
            "generated_utc": now.isoformat(),
            "points_used": sorted(all_fc),
            "summits": {},
        }
        for s in summit_fc:
            rows = []
            for when in times:
                e = estimate(all_fc, s, when)
                rows.append(
                    {
                        "time_utc": when.isoformat(),
                        "temp_f": e.temp_f,
                        "feels_like_f": e.feels_like_f,
                        "wind_mph": e.wind_mph,
                        "gust_mph": e.gust_mph,
                        "sky_pct": e.sky_pct,
                        "pop_pct": e.pop_pct,
                        "visibility_mi": e.vis_mi,
                        "visibility_label": e.visibility_label,
                        "in_cloud": e.in_cloud,
                        "cloud_base_m": e.cloud_base_m,
                    }
                )
            payload["summits"][s.loc.name] = {
                "elevation_m": s.loc.elevation_m,
                "range": s.loc.range,
                "rows": rows,
            }
        print(json.dumps(payload, indent=2))
    else:
        print(report.full_report(all_fc, summit_fc, times))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
