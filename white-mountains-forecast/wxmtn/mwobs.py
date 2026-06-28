"""Best-effort fetch of the Mount Washington Observatory Higher Summits Forecast.

This is MWObs's expert human forecast for the high summits -- the gold standard
cross-check for the Presidentials. It's not part of the NWS API, so we scrape the
public page leniently and degrade to None if the page layout changes or the
network blocks it. Never let this break a run.
"""

from __future__ import annotations

import html
import re
import urllib.request

URL = "https://www.mountwashington.org/weather/higher-summits-forecast/"


def higher_summits_text(timeout: int = 20) -> str | None:
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "wxmtn/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "ignore")
    except Exception:
        return None
    # strip scripts/styles, tags -> text, collapse whitespace
    body = re.sub(r"(?is)<(script|style).*?</\1>", " ", body)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", body))
    text = re.sub(r"\s+", " ", text).strip()
    # The live page renders the forecast client-side (JS), so the static HTML is
    # usually just chrome/nav placeholders ("Switch to Metric", empty "Wind: ").
    # Detect that shell and bail rather than returning junk.
    if "Switch to Metric" in text or "Skip to content" in text[:200]:
        # try to find real prose after the nav; require full sentences
        text = text.split("Switch to Metric")[-1]
    m = re.search(
        r"((?:Summits|In the clouds|Wind chill|Becoming|Increasing clouds|"
        r"A chance of|Highs? in|Lows? in|Gusts? to)\b[^.]{30,}\."
        r"(?:\s+[A-Z][^.]{15,}\.){1,8})",
        text,
    )
    snippet = m.group(0).strip() if m else ""
    if len(snippet) < 120:   # nothing real here (JS-only page)
        return None
    return snippet[:900]
