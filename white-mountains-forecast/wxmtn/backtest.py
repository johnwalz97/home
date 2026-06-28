"""Log forecasts and score them against what KMWN actually did.

Each run can append its current-hour Mount Washington estimate alongside the
live KMWN observation to a JSONL log. Later we can read the log back and report
the model's mean error -- evidence the triangulation works, not just a claim.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .fetch import LocationForecast
from .model import c_to_f, estimate

LOG = Path(__file__).resolve().parent.parent / "data" / "backtest.jsonl"


def log_now(all_fc: dict[str, LocationForecast], now: datetime) -> dict | None:
    """Append a (forecast, observation) pair for the current hour, if possible."""
    summit = all_fc.get("Mount Washington")
    obs = next(
        (fc for fc in all_fc.values()
         if getattr(fc, "observation", None) and fc.loc.is_summit), None)
    if summit is None or obs is None:
        return None
    est = estimate(all_fc, summit, now)
    o = obs.observation
    rec = {
        "logged_utc": now.astimezone(timezone.utc).isoformat(),
        "obs_time": o["timestamp"],
        "model_temp_f": round(est.temp_f, 1) if est.temp_f is not None else None,
        "obs_temp_f": round(c_to_f(o["temp_c"]), 1) if o.get("temp_c") is not None else None,
        "model_in_cloud": est.in_cloud,
        "obs_vis_mi": round(o["vis_m"] / 1609.344, 1) if o.get("vis_m") is not None else None,
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


def scoreboard() -> dict:
    """Read the log and summarize model-vs-obs error."""
    if not LOG.exists():
        return {"samples": 0}
    errs, cloud_hits, cloud_n = [], 0, 0
    n = 0
    for line in LOG.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        n += 1
        if r.get("model_temp_f") is not None and r.get("obs_temp_f") is not None:
            errs.append(abs(r["model_temp_f"] - r["obs_temp_f"]))
        if r.get("obs_vis_mi") is not None and r.get("model_in_cloud") is not None:
            cloud_n += 1
            obs_cloud = r["obs_vis_mi"] < 1.0
            if obs_cloud == r["model_in_cloud"]:
                cloud_hits += 1
    return {
        "samples": n,
        "temp_mae_f": round(sum(errs) / len(errs), 2) if errs else None,
        "cloud_accuracy": round(cloud_hits / cloud_n, 2) if cloud_n else None,
    }
