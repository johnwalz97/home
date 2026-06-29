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

1. **Downloads** `api.weather.gov` gridpoint forecasts for 22 summits
   (Presidentials, Franconia Range, other 4,000-footers, and lower view-ledges)
   plus 7 valley/notch reference points. Responses are cached under `data/cache/`.
2. **Triangulates temperature.** At each forecast hour it least-squares fits
   temperature against elevation across *all* the points (a regional lapse
   rate), then evaluates that line at each summit's **true** elevation. On a
   typical day this comes out around 5 °F colder per 1,000 ft climbed.
3. **Estimates visibility.** It computes the lifting-condensation level (cloud
   base) from the valley temperature/dewpoint spread and checks whether each
   summit pokes into the cloud deck, then blends that with the grid's own
   visibility forecast. Summits above cloud base get flagged "in the clouds."
4. **Anchors the nowcast to live observations.** It folds in real-time NWS
   station obs — including **KMWN, the Mount Washington Observatory summit** —
   as current-hour anchors. Measured summit data corrects the lapse fit, bias-
   corrects the near-term forecast (a decaying offset), and overrides the cloud-
   base model (a measured-clear summit can't be "fogged in"). It also reports the
   **observed** lapse rate and flags **temperature inversions**.
5. **Adds the context hikers actually decide on:** plain-language per-peak
   summaries, **sunrise/sunset + golden hour**, **active NWS alerts**, trailhead
   route/distance/difficulty, a **0–100 score** with each peak's **best window**,
   and a **ranking** of where to go today.
6. **Reports** per-summit tables plus a region snapshot (coldest/windiest, who's
   socked in vs. who has views), with a `--brief` morning digest and a
   `--backtest` scoreboard that grades the model against what KMWN actually did.

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

# morning brief: today's top picks + live summit conditions
python -m wxmtn --brief

# rank every peak by today's score / best window
python -m wxmtn --rank

# filter to a range, add lower spots + the MWObs higher-summits text
python -m wxmtn --region Franconia --spots --mwobs

# grade the model against the live KMWN observation, append to the log
python -m wxmtn --backtest

# skip live obs / machine-readable output
python -m wxmtn --no-live
python -m wxmtn --json > forecast.json

# standalone interactive report (topo map + hour slider + play button)
python -m wxmtn --hours 36 --step 1 --html today.html
```

## AI briefing (optional)

If an `ANTHROPIC_API_KEY` is available at build time, the report gains an **AI
Briefing** panel: each morning the full forecast dataset is sent to Claude
(`claude-opus-4-8`), which returns an expert read on top of the deterministic
numbers — a headline, a narrative, a single best bet, scenario-based plans,
**judgment calls** (where it agrees/disagrees with the raw "go score"), and
safety hazards. The deterministic forecast stays the source of truth; this is
the advisor layer. It degrades to nothing without the key (`wxmtn/ai.py` returns
`None`), so local builds and tests never need it. Add the key as a repo secret
named `ANTHROPIC_API_KEY` to enable it in the daily build; pass `--no-ai` to skip.

## Ascent profile ("weather as you climb")

The per-peak detail shows a band-by-band **ascent profile** from the trailhead to
the true summit at the day's best hour — temperature by elevation and, crucially,
**where the climb enters the clouds** (the cloud-base crossing), which a single
valley point forecast can't tell you. CLI: this data rides in the `--html`
payload; the model function is `wxmtn.model.ascent_profile`.

## Live daily report (GitHub Pages)

`.github/workflows/daily-forecast.yml` rebuilds the interactive report every
morning (10:00 UTC) and on demand, and publishes it to GitHub Pages — so there's
always a fresh, phone-friendly dashboard at:

**https://johnwalz97.github.io/home/**

One-time setup: in the repo **Settings → Pages**, set **Source = GitHub Actions**
(the workflow tries to enable this automatically via `configure-pages`, but if
the first run can't, flip it once and re-run the workflow).

The NWS asks clients to identify themselves; set a contact string with
`WXMTN_CONTACT="you@example.com"` (it goes in the User-Agent only).

## Layout

| File | Purpose |
|------|---------|
| `wxmtn/peaks.py`  | Summit + anchor + spot coordinates and true elevations |
| `wxmtn/nws.py`    | Cached NWS API client |
| `wxmtn/series.py` | Expands NWS ISO-interval time series into hourly lookups |
| `wxmtn/fetch.py`  | Assembles per-location hourly forecast series |
| `wxmtn/obs.py`    | Live station obs (incl. KMWN) → current-hour anchors; observed lapse/inversion |
| `wxmtn/model.py`  | Lapse fit + cloud base (obs-constrained) + obs bias-correction |
| `wxmtn/astro.py`  | Sunrise / sunset / golden hour (pure-Python solar calc) |
| `wxmtn/alerts.py` | Active NWS watches/warnings/advisories |
| `wxmtn/mwobs.py`  | Best-effort Mount Washington Obs higher-summits text |
| `wxmtn/score.py`  | View/comfort/safety scoring + best-window finder |
| `wxmtn/summary.py`| Plain-language summaries + ridge-wind/hazard callouts |
| `wxmtn/trailheads.py` | Trailhead route / distance / difficulty per peak |
| `wxmtn/backtest.py` | Logs forecast vs KMWN obs and scores the model |
| `wxmtn/report.py` | Human-readable report rendering |
| `wxmtn/cli.py`    | Command-line entry point |

## Caveats

This is a derived estimate, not an official product. Live obs pin the current
hour, but **future hours** still lean on the single regional LCL cloud-base
approximation, which won't catch every upslope/banding situation. Wind is the
summit grid value (not elevation-scaled), with a live-anchored "ridges are
windier than modeled" flag when KMWN disagrees. The MWObs text cross-check is
best-effort (their page renders client-side, so it's often unavailable here).
For life-safety decisions in the Presidentials, cross-check the
[Mount Washington Observatory Higher Summits Forecast](https://www.mountwashington.org/experience-the-weather/higher-summit-forecast/).
