"""Trailhead context per peak: where you start, how far, how hard.

Used to pair a summit's weather with the actual hike, and to warn about
swollen stream crossings after heavy rain. Distances are typical round-trip
miles for the most common route; not exhaustive.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Trailhead:
    route: str
    start_elev_m: float
    round_trip_mi: float
    difficulty: str           # easy | moderate | strenuous | expert
    stream_crossings: bool
    notes: str = ""


# keyed by exact peak name in peaks.py
TRAILHEADS = {
    "Mount Washington": Trailhead("Tuckerman Ravine Tr", 612, 8.4, "expert", True,
        "Exposed above treeline; weather kills here -- turn back in bad viz/wind."),
    "Mount Lafayette": Trailhead("Old Bridle Path / Falling Waters", 533, 8.9, "strenuous", True,
        "Franconia Ridge loop is long and fully exposed for ~1.7 mi."),
    "Mount Lincoln": Trailhead("Falling Waters Tr", 533, 8.0, "strenuous", True,
        "On the Franconia Ridge between Little Haystack and Lafayette."),
    "Mount Moosilauke": Trailhead("Gorge Brook Tr", 564, 7.4, "moderate", True,
        "Broad bald summit; great views, exposed top."),
    "Mount Chocorua": Trailhead("Piper Tr", 308, 7.6, "moderate", True,
        "Iconic rocky cone; ledgy summit, slippery when wet."),
    "Mount Willard": Trailhead("Mount Willard Tr", 580, 3.2, "easy", False,
        "Short, gentle; huge Crawford Notch view for little effort."),
    "Welch Mountain": Trailhead("Welch-Dickey Loop", 320, 4.4, "moderate", False,
        "Open ledges low down; loop with Dickey."),
    "Dickey Mountain": Trailhead("Welch-Dickey Loop", 320, 4.4, "moderate", False,
        "Ledge views; pairs with Welch."),
    "South Moat Mountain": Trailhead("South Moat Tr", 270, 5.4, "moderate", False,
        "Open bald ledges up high -- bad place to be in lightning."),
    "Black Cap": Trailhead("Black Cap Tr (Hurricane Mtn Rd)", 590, 2.4, "easy", False,
        "Easiest big view near Conway; bald granite summit."),
    "Mount Kearsarge North": Trailhead("Mount Kearsarge North Tr", 180, 6.2, "strenuous", False,
        "Restored fire tower with 360° views."),
}


def for_peak(name: str) -> Trailhead | None:
    return TRAILHEADS.get(name)
