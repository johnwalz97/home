# wxmtn — White Mountains summit forecaster

Downloads **point forecast data** from the US National Weather Service for the
major peaks of the White Mountains (New Hampshire) plus surrounding valley
stations, then **triangulates** what conditions will actually be like on each
summit — how cold it'll be and how good the visibility is.

It's built around the fact that you can't just read a single grid cell off a
weather map and trust it on a 5,000–6,000 ft peak: the forecast grid smooths the
terrain, so it thinks Mount Washington's summit is ~600 ft lower (and therefore
several degrees warmer) than it really is. So instead of trusting one cell, we
pull a cloud of points spanning the whole elevation range and fit the mountain
weather to it.

## What it does

1. **Downloads** `api.weather.gov` gridpoint forecasts for 15 summits
   (Presidentials, Franconia Range, and other 4,000-footers) and 7 lower
   reference points (the notches and valley towns). Responses are cached under
   `data/cache/`.
2. **Triangulates temperature.** At each forecast hour it least-squares fits
   temperature against elevation across *all* the points (a regional lapse
   rate), then evaluates that line at each summit's **true** elevation. On a
   typical day this comes out around 5 °F colder per 1,000 ft climbed.
3. **Estimates visibility.** It computes the lifting-condensation level (cloud
   base) from the valley temperature/dewpoint spread and checks whether each
   summit pokes into the cloud deck, then blends that with the grid's own
   visibility forecast. Summits above cloud base get flagged "in the clouds /
   fogged in."
4. **Reports** a per-summit table (temp, wind-chill "feels like", wind + gusts,
   sky cover, precip chance, visibility) plus a region snapshot calling out the
   coldest peak, the windiest, and which summits will have views vs. be socked
   in.

## Usage

No third-party dependencies — standard-library Python 3.11+. Run from inside the
`white-mountains-forecast/` folder:

```bash
# 48-hour outlook, every 6 hours, all summits
python -m wxmtn

# next 24 hours in 3-hour steps
python -m wxmtn --hours 24 --step 3

# just a couple of peaks (name substring match)
python -m wxmtn --peak Washington --peak Lafayette

# machine-readable output
python -m wxmtn --json > forecast.json
```

The NWS asks clients to identify themselves; set a contact string with
`WXMTN_CONTACT="you@example.com"` (it goes in the User-Agent only).

## Layout

| File | Purpose |
|------|---------|
| `wxmtn/peaks.py`  | Summit + anchor coordinates and true elevations |
| `wxmtn/nws.py`    | Cached NWS API client |
| `wxmtn/series.py` | Expands NWS ISO-interval time series into hourly lookups |
| `wxmtn/fetch.py`  | Assembles per-location hourly forecast series |
| `wxmtn/model.py`  | Lapse-rate fit + cloud-base / visibility model |
| `wxmtn/report.py` | Human-readable report rendering |
| `wxmtn/cli.py`    | Command-line entry point |

## Caveats

This is a derived estimate, not an official product. The cloud-base model is a
single regional LCL approximation and won't catch every upslope/inversion
situation. For life-safety decisions in the Presidentials, cross-check the
[Mount Washington Observatory Higher Summits Forecast](https://www.mountwashington.org/experience-the-weather/higher-summit-forecast/).
