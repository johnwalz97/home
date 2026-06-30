"""Optional AI briefing layer — distills the raw forecast into expert intelligence.

At build time (in CI, with ANTHROPIC_API_KEY set) this sends the compacted
forecast payload to Claude and returns a structured briefing: a headline, an
expert narrative, a single best bet, scenario-based plans, judgment calls (where
the model agrees/disagrees with the deterministic score), and safety hazards.

It degrades to ``None`` whenever the key or the ``anthropic`` SDK is missing, or
the call fails — so local builds, tests, and the page all work without it. The
deterministic forecast is the source of truth; this is an expert read on top.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

MODEL = "claude-opus-4-8"

# A briefing the agent (this assistant) wrote on its daily run and committed.
# Used when no ANTHROPIC_API_KEY is present — so the deploy needs no secret.
COMMITTED = Path(__file__).resolve().parent.parent / "data" / "ai_brief.json"


def _today_edt() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def load_committed() -> dict | None:
    """Return the committed briefing if it exists and was written today (EDT)."""
    try:
        brief = json.loads(COMMITTED.read_text())
    except (FileNotFoundError, ValueError):
        return None
    # Only serve a same-day briefing; a stale one is worse than none.
    return brief if brief.get("date") == _today_edt() else None


def write_committed(brief: dict) -> None:
    """Persist a briefing (stamped with today's date) for the keyless build to pick up."""
    brief = dict(brief)
    brief["date"] = _today_edt()
    COMMITTED.parent.mkdir(parents=True, exist_ok=True)
    COMMITTED.write_text(json.dumps(brief, indent=2))

SYSTEM = (
    "You are an expert White Mountains (New Hampshire) mountain-weather forecaster "
    "and trip advisor, in the spirit of the Mount Washington Observatory higher-summits "
    "forecasters. You are given a machine-generated forecast dataset for ~22 summits: "
    "per-day temp/wind/cloud rollups and a 0-100 'go score', hazard flags, a cross-peak "
    "day planner (best peaks per day), live Mount Washington summit observations, sunrise/"
    "sunset, and any active NWS alerts.\n\n"
    "Turn that data into genuine intelligence a hiker can act on. Be specific and grounded "
    "ONLY in the data provided; never invent numbers or conditions not present. Think like "
    "a ranger: terse, expert, safety-aware, no hype. Crucially, exercise judgment the raw "
    "score can't: call out where a high score is misleading (a peak about to fog in, "
    "dangerous wind the score underweights, a great-looking day undercut by an afternoon "
    "storm), and where a mediocre score still has a real window. Recommend concrete plans "
    "(which day, which peak, what time window, and why). Flag genuine hazards (wind chill, "
    "thunderstorms, above-treeline exposure, rapid changes). Honesty about uncertainty beats "
    "false confidence."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string",
                     "description": "One punchy sentence: the single most useful takeaway for the next few days."},
        "narrative": {"type": "string",
                      "description": "2-4 sentences of expert synthesis of the overall pattern and what's driving it."},
        "best_bet": {
            "type": "object",
            "properties": {
                "peak": {"type": "string"},
                "day": {"type": "string"},
                "window": {"type": "string"},
                "why": {"type": "string"},
            },
            "required": ["peak", "day", "window", "why"],
            "additionalProperties": False,
        },
        "plan": {
            "type": "array",
            "description": "2-4 scenario-based recommendations for different goals.",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string",
                              "description": "e.g. 'If you want big views', 'If you want solitude / low effort', 'Safest pick'"},
                    "recommendation": {"type": "string"},
                },
                "required": ["label", "recommendation"],
                "additionalProperties": False,
            },
        },
        "judgments": {"type": "array", "items": {"type": "string"},
                      "description": "Where you agree/disagree with the deterministic score, or notable nuance it misses."},
        "hazards": {"type": "array", "items": {"type": "string"},
                    "description": "Concrete safety callouts grounded in the data. Empty if genuinely benign."},
    },
    "required": ["headline", "narrative", "best_bet", "plan", "judgments", "hazards"],
    "additionalProperties": False,
}


def _compact(payload: dict) -> dict:
    """Trim the payload to the decision-relevant fields (drop the big hourly arrays)."""
    peaks = []
    for p in payload.get("peaks", []):
        if p.get("type") != "summit":
            continue
        peaks.append({
            "name": p["name"],
            "elev_ft": p["elev_ft"],
            "range": p["range"],
            "today_score": p.get("day_score"),
            "best_day": p.get("best_day"),
            "flags": [f["t"] for f in p.get("flags", [])],
            "difficulty": p.get("difficulty"),
            "days": [
                {k: d[k] for k in ("label", "score", "best_window", "hi", "lo", "cloud_pct") if k in d}
                for d in p.get("days", [])
            ],
            "summary": p.get("summary"),
        })
    return {
        "generated": payload.get("generated"),
        "day_labels": payload.get("day_labels"),
        "sunrise": payload.get("sunrise"),
        "sunset": payload.get("sunset"),
        "summit_now": payload.get("summit_now"),
        "alerts": payload.get("alerts"),
        "planner": payload.get("planner"),
        "peaks": peaks,
    }


def compact_context(payload: dict) -> dict:
    """Public: the decision-relevant data the agent reasons over to write a brief."""
    return _compact(payload)


def build_briefing(payload: dict, *, model: str = MODEL) -> dict | None:
    """Return the structured AI briefing.

    With an API key, calls Claude directly. Without one, falls back to the
    committed same-day briefing the agent wrote on its daily run — so the
    GitHub Pages build needs no secret.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return load_committed()
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model,
            max_tokens=4000,
            thinking={"type": "adaptive"},
            system=SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{
                "role": "user",
                "content": ("Here is today's White Mountains forecast dataset (JSON). "
                            "Produce the briefing.\n\n" + json.dumps(_compact(payload))),
            }],
        )
        text = next((b.text for b in resp.content if b.type == "text"), None)
        briefing = json.loads(text) if text else None
        if briefing:
            briefing["model"] = getattr(resp, "model", model)
        return briefing
    except Exception:
        # Never let the AI layer break a build.
        return None
