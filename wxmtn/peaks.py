"""Locations used for triangulating White Mountains (NH) weather.

`SUMMITS` are the peaks we actually forecast for. `ANCHORS` are lower-elevation
points (notches, valley towns) that, together with the summits' own grid cells,
give us a spread of elevations to fit a regional temperature lapse rate against.

Elevations are *true* summit/station elevations in metres. The NWS grid cell a
point falls in usually reports a smoothed elevation that differs from the real
summit (the grid can't resolve a sharp peak), which is exactly why we re-fit
temperature to the true elevation rather than trusting the raw grid value.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    name: str
    lat: float
    lon: float
    elevation_m: float
    range: str = ""
    is_summit: bool = True


# Major White Mountain summits. Coordinates/elevations from USGS GNIS.
SUMMITS = [
    # Presidential Range
    Location("Mount Washington", 44.2706, -71.3033, 1916.6, "Presidentials"),
    Location("Mount Adams", 44.3206, -71.2914, 1760.2, "Presidentials"),
    Location("Mount Jefferson", 44.3036, -71.3168, 1741.0, "Presidentials"),
    Location("Mount Monroe", 44.2553, -71.3147, 1641.0, "Presidentials"),
    Location("Mount Madison", 44.3286, -71.2772, 1636.1, "Presidentials"),
    Location("Mount Eisenhower", 44.2422, -71.3522, 1456.9, "Presidentials"),
    # Franconia Range
    Location("Mount Lafayette", 44.1607, -71.6444, 1600.2, "Franconia"),
    Location("Mount Lincoln", 44.1486, -71.6447, 1551.1, "Franconia"),
    Location("Mount Liberty", 44.1640, -71.6500, 1359.1, "Franconia"),
    # Other notable 4000-footers
    Location("Mount Moosilauke", 44.0242, -71.8311, 1463.9, "Moosilauke"),
    Location("Mount Carrigain", 44.0967, -71.4475, 1432.6, "Carrigain"),
    Location("Mount Bond", 44.1392, -71.5083, 1417.3, "Twin-Bond"),
    Location("South Twin Mountain", 44.1872, -71.5547, 1430.7, "Twin-Bond"),
    Location("Mount Garfield", 44.1869, -71.6017, 1397.2, "Franconia"),
    Location("Mount Carter Dome", 44.2672, -71.1786, 1453.3, "Carter-Moriah"),
]

# Lower-elevation reference points (notches + valley towns). These anchor the
# bottom of the lapse-rate regression so the elevation slope is well constrained.
ANCHORS = [
    Location("Pinkham Notch", 44.2573, -71.2533, 612.0, "notch", is_summit=False),
    Location("Crawford Notch", 44.2186, -71.4111, 581.0, "notch", is_summit=False),
    Location("Franconia Notch", 44.1420, -71.6840, 580.0, "notch", is_summit=False),
    Location("North Conway", 44.0537, -71.1284, 161.8, "valley", is_summit=False),
    Location("Lincoln NH", 44.0454, -71.6709, 247.2, "valley", is_summit=False),
    Location("Berlin NH", 44.4687, -71.1851, 337.1, "valley", is_summit=False),
    Location("Gorham NH", 44.3878, -71.1734, 245.4, "valley", is_summit=False),
]

ALL = SUMMITS + ANCHORS
