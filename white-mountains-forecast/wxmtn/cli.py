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

from . import backtest, fetch, obs, peaks, report
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
    ap.add_argument("--region", help="filter summits by range (substring)")
    ap.add_argument("--brief", action="store_true", help="short morning brief: top picks")
    ap.add_argument("--rank", action="store_true", help="rank peaks by today's score")
    ap.add_argument("--spots", action="store_true", help="include lower-elevation spots")
    ap.add_argument("--mwobs", action="store_true",
                    help="append the Mount Washington Obs higher-summits text")
    ap.add_argument("--html", metavar="PATH",
                    help="write a standalone interactive map report to PATH")
    ap.add_argument("--no-ai", action="store_true",
                    help="skip the AI briefing even if ANTHROPIC_API_KEY is set")
    ap.add_argument("--ai-context", metavar="PATH",
                    help="write the compacted forecast JSON (for the agent to brief over) and exit")
    ap.add_argument("--backtest", action="store_true",
                    help="log this hour vs KMWN and print the scoreboard")
    args = ap.parse_args(argv)

    summits = _select_summits(args.peak)
    if args.region:
        summits = [s for s in summits if args.region.lower() in s.range.lower()]
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

    if args.backtest:
        rec = backtest.log_now(all_fc, now)
        if rec:
            print(f"Logged: model {rec['model_temp_f']}°F vs obs {rec['obs_temp_f']}°F "
                  f"(in-cloud model={rec['model_in_cloud']}, obs vis {rec['obs_vis_mi']} mi)")
        board = backtest.scoreboard()
        print(f"Backtest scoreboard: {board['samples']} samples, "
              f"temp MAE {board.get('temp_mae_f')}°F, "
              f"cloud accuracy {board.get('cloud_accuracy')}")
        return 0

    if args.ai_context:
        from . import ai, webreport
        spot_fc = fetch.fetch_all(peaks.SPOTS)
        payload = webreport.build_payload(all_fc, summit_fc, times, spot_fc=spot_fc)
        with open(args.ai_context, "w") as fh:
            json.dump(ai.compact_context(payload), fh, indent=2)
        print(f"Wrote AI context: {args.ai_context}", file=sys.stderr)
        return 0

    if args.html:
        from . import webreport
        spot_fc = fetch.fetch_all(peaks.SPOTS)
        payload = webreport.build_payload(all_fc, summit_fc, times, spot_fc=spot_fc)
        if not args.no_ai:
            from . import ai
            brief = ai.build_briefing(payload)
            if brief:
                payload["ai"] = brief
                print(f"AI briefing added ({brief.get('model','?')}).", file=sys.stderr)
            else:
                print("AI briefing skipped (no ANTHROPIC_API_KEY / SDK / call failed).",
                      file=sys.stderr)
        with open(args.html, "w") as fh:
            fh.write(webreport.render_html(payload))
        print(f"Wrote interactive report: {args.html} "
              f"({len(payload['peaks'])} peaks, {len(payload['labels'])} hours)")
        return 0

    if args.brief:
        print(report.brief_report(all_fc, summit_fc, times))
        return 0
    if args.rank:
        print(report.rank_report(all_fc, summit_fc, times))
        return 0

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
        if args.spots:
            spot_fc = fetch.fetch_all(peaks.SPOTS)
            print()
            print(report.spots_block(spot_fc, times))
        if args.mwobs:
            from . import mwobs
            text = mwobs.higher_summits_text()
            print("\nMOUNT WASHINGTON OBS — HIGHER SUMMITS FORECAST (cross-check)")
            print("=" * 60)
            print("  " + (text if text else "(unavailable)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
