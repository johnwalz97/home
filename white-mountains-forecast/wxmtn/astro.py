"""Sunrise / sunset / golden-hour for a coordinate and date.

Pure-Python NOAA solar position algorithm (no dependencies). Accurate to well
under a minute for our purposes. Times are returned as timezone-aware UTC
datetimes; the caller converts to Eastern for display.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone


def _solar_event_utc(d: date, lat: float, lon: float, zenith_deg: float, rising: bool):
    """Hour-angle method. Returns a UTC datetime, or None if the sun never
    reaches that altitude on this date (polar day/night — never here)."""
    n = d.toordinal() - date(d.year, 1, 1).toordinal() + 1
    lng_hour = lon / 15.0
    t = n + ((6 if rising else 18) - lng_hour) / 24.0

    m = 0.9856 * t - 3.289                                   # sun's mean anomaly
    l = (m + 1.916 * math.sin(math.radians(m))
         + 0.020 * math.sin(math.radians(2 * m)) + 282.634) % 360  # true longitude

    ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(l)))) % 360
    ra += (math.floor(l / 90) * 90) - (math.floor(ra / 90) * 90)   # same quadrant
    ra /= 15.0

    sin_dec = 0.39782 * math.sin(math.radians(l))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_h = ((math.cos(math.radians(zenith_deg)) - sin_dec * math.sin(math.radians(lat)))
             / (cos_dec * math.cos(math.radians(lat))))
    if cos_h > 1 or cos_h < -1:
        return None
    h = (360 - math.degrees(math.acos(cos_h)) if rising
         else math.degrees(math.acos(cos_h))) / 15.0

    local_t = (h + ra - 0.06571 * t - 6.622) % 24
    # Do NOT wrap to [0,24): for western longitudes sunset lands after 00 UTC the
    # next day, so keep the full offset and add it as a timedelta from midnight.
    ut = local_t - lng_hour
    midnight = datetime.combine(d, time(0), tzinfo=timezone.utc)
    return midnight + timedelta(hours=ut)


def sun_times(d: date, lat: float, lon: float) -> dict:
    """Sunrise, sunset, and golden-hour edges (UTC)."""
    sunrise = _solar_event_utc(d, lat, lon, 90.833, True)   # standard refraction
    sunset = _solar_event_utc(d, lat, lon, 90.833, False)
    # golden hour ≈ sun below 6° altitude (zenith 96°) through sunrise/sunset
    dawn = _solar_event_utc(d, lat, lon, 96.0, True)
    dusk = _solar_event_utc(d, lat, lon, 96.0, False)
    out = {"sunrise": sunrise, "sunset": sunset}
    if dawn and sunrise:
        out["golden_am"] = (dawn, sunrise + timedelta(minutes=30))
    if sunset and dusk:
        out["golden_pm"] = (sunset - timedelta(minutes=40), dusk)
    return out
