"""Active NWS watches/warnings/advisories for our area."""

from __future__ import annotations

from . import nws


def active(area: str = "NH") -> list[dict]:
    """Return simplified active alerts for a state (e.g. 'NH', 'ME')."""
    try:
        data = nws._get(f"{nws.API}/alerts/active?area={area}", max_age_s=600)
    except nws.NWSError:
        return []
    out = []
    for feat in data.get("features", []):
        p = feat.get("properties", {})
        out.append(
            {
                "event": p.get("event"),
                "severity": p.get("severity"),
                "headline": p.get("headline"),
                "area": p.get("areaDesc"),
                "ends": p.get("ends") or p.get("expires"),
            }
        )
    return out


def mountain_relevant(alerts: list[dict]) -> list[dict]:
    """Filter to alerts whose area text mentions the mountain counties/zones."""
    keys = ("Coos", "Grafton", "Carroll", "mountain", "Summit", "White Mountains")
    keep = []
    for a in alerts:
        area = (a.get("area") or "")
        ev = (a.get("event") or "")
        if any(k.lower() in area.lower() for k in keys) or "Wind" in ev or "Heat" in ev:
            keep.append(a)
    return keep
