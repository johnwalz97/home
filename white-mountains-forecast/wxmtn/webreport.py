"""Build a standalone, interactive HTML report (topo map + hour slider).

Produces a single self-contained .html file: a Leaflet topo map with a marker
per peak coloured by that hour's score, a slider to scrub through the forecast
(watch summits fog in and clear out), a ranked sidebar, and a click-through
detail panel. Map tiles + Leaflet load from CDN, so viewing needs a connection;
all the forecast data is embedded inline.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .fetch import LocationForecast
from .model import estimate, summit_temp_bias_c
from .astro import sun_times
from .alerts import active as active_alerts
from .alerts import mountain_relevant
from .score import best_window, composite
from .summary import peak_summary
from .trailheads import for_peak

EASTERN = ZoneInfo("America/New_York")


def _hour_label(when: datetime) -> str:
    return when.astimezone(EASTERN).strftime("%a %-I%p").lower()


def _peak_payload(all_fc, summit, times, hourly, bias_c, now, daylight):
    ests = [estimate(all_fc, summit, w, bias_c=bias_c, bias_from=now) for w in times]
    h_ests = [estimate(all_fc, summit, w, bias_c=bias_c, bias_from=now) for w in hourly]
    scored = [(e.when, composite(e)) for e in h_ests]
    if daylight:
        lo, hi = daylight
        day = [s for s in scored if lo <= s[0] <= hi] or scored
    else:
        day = scored
    win = best_window(day, threshold=55)
    day_score = round(win.avg_score, 0) if win else (
        round(max((s for _, s in day), default=0), 0))
    th = for_peak(summit.loc.name)
    return {
        "name": summit.loc.name,
        "lat": summit.loc.lat,
        "lon": summit.loc.lon,
        "elev_ft": round(summit.loc.elevation_m * 3.28084),
        "range": summit.loc.range,
        "type": "summit",
        "day_score": day_score,
        "best_window": (
            f"{win.start.astimezone(EASTERN):%-I%p}–{win.end.astimezone(EASTERN):%-I%p}".lower()
            if win and win.hours > 1 else
            (f"around {win.start.astimezone(EASTERN):%-I%p}".lower() if win else None)
        ),
        "summary": peak_summary(summit.loc.name, h_ests, daylight),
        "trailhead": (f"{th.route} · {th.round_trip_mi:.1f} mi · {th.difficulty}"
                      if th else None),
        "hours": [
            {
                "t": _hour_label(e.when),
                "temp": round(e.temp_f) if e.temp_f is not None else None,
                "feels": round(e.feels_like_f) if e.feels_like_f is not None else None,
                "wind": round(e.wind_mph) if e.wind_mph is not None else None,
                "gust": round(e.gust_mph) if e.gust_mph is not None else None,
                "pop": round(e.pop_pct) if e.pop_pct is not None else None,
                "vis": e.visibility_label,
                "cloud": e.in_cloud,
                "score": round(composite(e)),
            }
            for e in ests
        ],
    }


def _spot_payload(fc, times):
    from .model import c_to_f, kmh_to_mph
    rows = []
    for w in times:
        t = fc.value("temp_c", w)
        wind = fc.value("wind_kmh", w)
        pop = fc.value("pop_pct", w)
        vis = fc.value("vis_m", w)
        rows.append({
            "t": _hour_label(w),
            "temp": round(c_to_f(t)) if t is not None else None,
            "feels": None,
            "wind": round(kmh_to_mph(wind)) if wind is not None else None,
            "gust": None,
            "pop": round(pop) if pop is not None else None,
            "vis": "fog/low cloud" if (vis is not None and vis < 1609) else "clear",
            "cloud": bool(vis is not None and vis < 1609),
            "score": None,
        })
    return {
        "name": fc.loc.name, "lat": fc.loc.lat, "lon": fc.loc.lon,
        "elev_ft": round(fc.loc.elevation_m * 3.28084), "range": fc.loc.range,
        "type": "spot", "day_score": None, "best_window": None,
        "summary": None, "trailhead": None, "hours": rows,
    }


def build_payload(all_fc, summits, times, spot_fc=None) -> dict:
    now = times[0]
    bias_c = summit_temp_bias_c(all_fc, now) or 0.0
    ref = summits[0].loc
    sun = sun_times(now.astimezone(EASTERN).date(), ref.lat, ref.lon)
    daylight = (sun.get("sunrise"), sun.get("sunset")) if sun.get("sunrise") else None
    # an hourly grid for scoring even if the display step is coarse
    span_h = int((times[-1] - times[0]).total_seconds() // 3600)
    hourly = [times[0] + timedelta(hours=i) for i in range(span_h + 1)]

    peaks_pl = [_peak_payload(all_fc, s, times, hourly, bias_c, now, daylight)
                for s in summits]
    if spot_fc:
        peaks_pl += [_spot_payload(fc, times) for fc in spot_fc.values()]

    obs = next((fc for fc in all_fc.values()
                if getattr(fc, "observation", None) and fc.loc.is_summit), None)
    summit_now = None
    if obs:
        from .model import c_to_f, kmh_to_mph
        o = obs.observation
        summit_now = {
            "temp": round(c_to_f(o["temp_c"])) if o.get("temp_c") is not None else None,
            "wind": round(kmh_to_mph(o["wind_kmh"])) if o.get("wind_kmh") is not None else None,
            "vis_mi": round(o["vis_m"] / 1609.344, 1) if o.get("vis_m") is not None else None,
            "cloud": bool(o.get("vis_m") is not None and o["vis_m"] < 1609),
        }
    al = mountain_relevant(active_alerts("NH") + active_alerts("ME"))
    return {
        "generated": datetime.now(EASTERN).strftime("%A %B %-d, %-I:%M%p").replace("AM", "am").replace("PM", "pm"),
        "labels": [_hour_label(w) for w in times],
        "sunrise": sun["sunrise"].astimezone(EASTERN).strftime("%-I:%M%p").lower() if sun.get("sunrise") else None,
        "sunset": sun["sunset"].astimezone(EASTERN).strftime("%-I:%M%p").lower() if sun.get("sunset") else None,
        "summit_now": summit_now,
        "alerts": [a["event"] for a in al[:5]],
        "peaks": peaks_pl,
    }


def render_html(payload: dict) -> str:
    data = json.dumps(payload)
    return _TEMPLATE.replace("/*__DATA__*/null", data)


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>White Mountains Summit Forecast</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
  :root{--bg:#0e1116;--panel:#161b22;--ink:#e6edf3;--mut:#8b949e;--line:#30363d;}
  *{box-sizing:border-box}
  body{margin:0;font:14px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
       background:var(--bg);color:var(--ink);height:100vh;overflow:hidden}
  #app{display:grid;grid-template-columns:340px 1fr;height:100vh}
  #side{background:var(--panel);border-right:1px solid var(--line);display:flex;flex-direction:column;min-height:0}
  header{padding:14px 16px;border-bottom:1px solid var(--line)}
  header h1{margin:0 0 2px;font-size:16px}
  header .sub{color:var(--mut);font-size:12px}
  .chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
  .chip{background:#21262d;border:1px solid var(--line);border-radius:20px;padding:3px 9px;font-size:11px;color:var(--mut)}
  .chip.warn{background:#3d1d1d;border-color:#a33;color:#ffb3b3}
  .chip.live{background:#10241a;border-color:#2ea043;color:#7ee2a8}
  #list{overflow:auto;flex:1;padding:6px}
  .row{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:8px;cursor:pointer}
  .row:hover{background:#21262d}
  .row.active{background:#1f6feb22;outline:1px solid #1f6feb55}
  .dot{width:12px;height:12px;border-radius:50%;flex:none;box-shadow:0 0 0 2px #0006}
  .row .nm{flex:1;font-weight:600}
  .row .meta{color:var(--mut);font-size:11px}
  .row .sc{font-variant-numeric:tabular-nums;font-weight:700}
  #main{position:relative;min-width:0}
  #map{position:absolute;inset:0}
  #slider{position:absolute;left:50%;transform:translateX(-50%);bottom:18px;z-index:500;
          background:#161b22ee;border:1px solid var(--line);border-radius:12px;padding:10px 16px;
          width:min(680px,86%);backdrop-filter:blur(6px)}
  #slider .when{text-align:center;font-weight:700;margin-bottom:6px}
  #slider input{width:100%}
  #detail{position:absolute;top:14px;right:14px;z-index:500;width:300px;max-height:calc(100vh - 60px);
          overflow:auto;background:#161b22f2;border:1px solid var(--line);border-radius:12px;padding:14px;
          backdrop-filter:blur(6px);display:none}
  #detail h2{margin:0 0 2px;font-size:15px}
  #detail .el{color:var(--mut);font-size:12px;margin-bottom:8px}
  #detail .sum{font-size:13px;margin:8px 0;padding:8px;background:#0d1117;border-radius:8px;border:1px solid var(--line)}
  table{width:100%;border-collapse:collapse;font-size:12px}
  th,td{padding:3px 4px;text-align:right;border-bottom:1px solid #21262d}
  th:first-child,td:first-child{text-align:left;color:var(--mut)}
  td.cloud{color:#f0a36b}
  .x{float:right;cursor:pointer;color:var(--mut)}
  .legend{position:absolute;left:14px;bottom:18px;z-index:500;background:#161b22ee;border:1px solid var(--line);
          border-radius:10px;padding:8px 10px;font-size:11px;color:var(--mut)}
  .legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px;vertical-align:-1px}
  .leaflet-popup-content-wrapper,.leaflet-popup-tip{background:#161b22;color:var(--ink)}
</style></head>
<body><div id="app">
  <div id="side">
    <header>
      <h1>White Mountains Summit Forecast</h1>
      <div class="sub" id="gen"></div>
      <div class="chips" id="chips"></div>
    </header>
    <div id="list"></div>
  </div>
  <div id="main">
    <div id="map"></div>
    <div id="detail"></div>
    <div class="legend">
      <div><i style="background:#2ecc71"></i>great &nbsp;<i style="background:#f1c40f"></i>ok &nbsp;<i style="background:#e74c3c"></i>poor &nbsp;<i style="background:#8b949e"></i>spot</div>
      <div style="margin-top:3px">◍ ring = in the clouds that hour</div>
    </div>
    <div id="slider">
      <div class="when" id="when"></div>
      <input id="hr" type="range" min="0" value="0" step="1"/>
    </div>
  </div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const D = /*__DATA__*/null;
let idx = 0, selected = null;
const mix=(a,b,t)=>a.map((v,i)=>Math.round(v+(b[i]-v)*t));
const rgb=c=>`rgb(${c[0]},${c[1]},${c[2]})`;
function scoreColor(s){
  if(s==null) return '#8b949e';
  const G=[46,204,113],Y=[241,196,15],R=[231,76,60];
  return s>=50 ? rgb(mix(Y,G,(s-50)/50)) : rgb(mix(R,Y,s/50));
}
const map = L.map('map',{zoomControl:true}).setView([44.18,-71.35],10);
L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',{
  maxZoom:17, attribution:'© OpenTopoMap (CC-BY-SA), © OpenStreetMap'}).addTo(map);

const markers = D.peaks.map(p=>{
  const m = L.circleMarker([p.lat,p.lon],{radius:9,weight:2,color:'#0008',fillOpacity:.95});
  m.peak = p; m.addTo(map);
  m.on('click',()=>select(p));
  m.bindTooltip(p.name,{direction:'top'});
  return m;
});
const bounds = L.latLngBounds(D.peaks.map(p=>[p.lat,p.lon])); map.fitBounds(bounds.pad(.12));

function hourOf(p){ return p.hours[Math.min(idx,p.hours.length-1)]; }
function refresh(){
  document.getElementById('when').textContent = D.labels[idx] || '';
  markers.forEach(m=>{
    const h = hourOf(m.peak);
    const sc = m.peak.type==='spot' ? (h.cloud?20:75) : h.score;
    m.setStyle({fillColor:scoreColor(m.peak.type==='spot'?null:sc),
                color: h.cloud ? '#cfe' : '#0008',
                weight: h.cloud ? 3 : 2,
                radius: m.peak.type==='spot'?7:9,
                dashArray: h.cloud ? '3 3' : null});
  });
  buildList();
  if(selected) renderDetail(selected);
}
function buildList(){
  const L0 = document.getElementById('list'); L0.innerHTML='';
  const ps = D.peaks.slice().sort((a,b)=>(b.day_score??-1)-(a.day_score??-1));
  ps.forEach(p=>{
    const h = hourOf(p);
    const div = document.createElement('div');
    div.className='row'+(selected&&selected.name===p.name?' active':'');
    div.innerHTML = `<span class="dot" style="background:${scoreColor(p.type==='spot'?null:h.score)}"></span>
      <span class="nm">${p.name}</span>
      <span class="meta">${p.elev_ft.toLocaleString()}'${h.cloud?' · ◍ cloud':''}</span>
      <span class="sc">${p.day_score??'·'}</span>`;
    div.onclick=()=>{select(p); map.panTo([p.lat,p.lon]);};
    L0.appendChild(div);
  });
}
function renderDetail(p){
  const d=document.getElementById('detail'); d.style.display='block';
  const rows = p.hours.map((h,i)=>`<tr${i===idx?' style="background:#1f6feb22"':''}>
    <td>${h.t}</td><td>${h.temp??'·'}°</td><td>${h.feels??'·'}</td>
    <td>${h.wind??'·'}</td><td>${h.pop??'·'}%</td>
    <td class="${h.cloud?'cloud':''}">${h.cloud?'cloud':(h.vis||'').split(' ')[0]}</td></tr>`).join('');
  d.innerHTML=`<span class="x" onclick="document.getElementById('detail').style.display='none'">✕</span>
    <h2>${p.name}</h2><div class="el">${p.elev_ft.toLocaleString()} ft · ${p.range}${p.day_score!=null?` · score ${p.day_score}/100`:''}</div>
    ${p.summary?`<div class="sum">${p.summary}</div>`:''}
    ${p.best_window?`<div class="el">Best window: <b style="color:#7ee2a8">${p.best_window}</b></div>`:''}
    ${p.trailhead?`<div class="el">🥾 ${p.trailhead}</div>`:''}
    <table><tr><th>time</th><th>temp</th><th>feels</th><th>wind</th><th>rain</th><th>sky</th></tr>${rows}</table>`;
}
function select(p){ selected=p; renderDetail(p); buildList(); }

document.getElementById('gen').textContent = 'Updated '+D.generated;
const chips=document.getElementById('chips');
if(D.summit_now){const s=D.summit_now;
  chips.innerHTML += `<span class="chip live">Mt Washington now: ${s.temp}°F · ${s.wind} mph · ${s.cloud?'in cloud':s.vis_mi+' mi'}</span>`;}
if(D.sunrise) chips.innerHTML += `<span class="chip">☀ ${D.sunrise}–${D.sunset}</span>`;
D.alerts.forEach(a=> chips.innerHTML += `<span class="chip warn">⚠ ${a}</span>`);

const hr=document.getElementById('hr'); hr.max=D.labels.length-1;
hr.oninput=e=>{idx=+e.target.value; refresh();};
refresh();
</script></body></html>"""
