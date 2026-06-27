"""Thin client for the US National Weather Service API (api.weather.gov).

We use two endpoints per location:

* ``/points/{lat},{lon}``  -> resolves which forecast grid (office + x/y) a
  coordinate falls in, plus the nearest observation stations.
* ``/gridpoints/{office}/{x},{y}``  -> the raw numerical forecast for that grid
  cell: dense time series for temperature, dewpoint, sky cover, visibility,
  wind, etc., each as ISO-8601 ``start/duration`` intervals.

Responses are cached to ``data/`` so repeated runs (and offline poking) don't
hammer the service. The NWS asks every client to send a self-identifying
User-Agent; set ``WXMTN_CONTACT`` to override the default contact string.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.weather.gov"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
CONTACT = os.environ.get("WXMTN_CONTACT", "wxmtn White Mountains forecaster")
USER_AGENT = f"wxmtn/0.1 ({CONTACT})"


class NWSError(RuntimeError):
    pass


def _get(url: str, *, max_age_s: float = 1800, retries: int = 4) -> dict:
    """GET a JSON document, caching the body on disk for ``max_age_s`` seconds."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    cached = CACHE_DIR / f"{key}.json"
    if cached.exists() and (time.time() - cached.stat().st_mtime) < max_age_s:
        return json.loads(cached.read_text())

    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json"}
    )
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode()
            cached.write_text(body)
            return json.loads(body)
        except (urllib.error.URLError, TimeoutError) as exc:  # network hiccup
            last = exc
            time.sleep(2 ** attempt)
    raise NWSError(f"GET {url} failed after {retries} attempts: {last}")


def point(lat: float, lon: float) -> dict:
    """Resolve a coordinate to its forecast grid + station metadata."""
    return _get(f"{API}/points/{lat:.4f},{lon:.4f}")["properties"]


def gridpoint_raw(office: str, x: int, y: int) -> dict:
    """Raw numerical forecast grid (the dense time series we triangulate on)."""
    return _get(f"{API}/gridpoints/{office}/{x},{y}")["properties"]


def latest_observation(station: str) -> dict | None:
    """Most recent surface observation from a station (e.g. KMWN), if any."""
    try:
        return _get(
            f"{API}/stations/{station}/observations/latest", max_age_s=600
        )["properties"]
    except NWSError:
        return None
