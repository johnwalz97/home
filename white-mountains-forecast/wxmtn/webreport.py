"""Build a standalone, interactive HTML report (topo map + hour slider).

Produces a single self-contained .html file: a Leaflet topo map with a marker
per peak coloured by that hour's score, a slider to scrub through the forecast
(watch summits fog in and clear out), a ranked list, and a click-through detail
panel. Mobile-first and responsive: on phones the map and list are tabs and the
detail is a bottom sheet; on desktop they sit side by side. Map tiles + Leaflet
load from CDN (graceful fallback if offline); all forecast data is embedded.
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
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b0f15">
<title>White Mountains Summit Forecast</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
  :root{
    --bg:#0b0f15; --panel:#121821; --panel2:#0f141c; --ink:#e8eef6; --mut:#93a1b3;
    --line:#222c39; --accent:#4aa3ff; --good:#34d399; --ok:#fbbf24; --bad:#f87171;
    --sheet-pad: env(safe-area-inset-bottom, 0px);
  }
  *{box-sizing:border-box; -webkit-tap-highlight-color:transparent}
  html,body{height:100%; margin:0}
  body{font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       background:var(--bg); color:var(--ink); overscroll-behavior:none}
  button{font:inherit}
  #app{display:flex; flex-direction:column; height:100dvh}

  header{flex:none; padding:12px 14px calc(12px) ; border-bottom:1px solid var(--line);
         background:linear-gradient(180deg,#10161f,#0b0f15)}
  header h1{margin:0; font-size:17px; letter-spacing:.2px}
  header .sub{color:var(--mut); font-size:12px; margin-top:1px}
  .chips{display:flex; gap:7px; margin-top:9px; overflow-x:auto; -webkit-overflow-scrolling:touch;
         scrollbar-width:none; padding-bottom:2px}
  .chips::-webkit-scrollbar{display:none}
  .chip{flex:none; background:#1a2330; border:1px solid var(--line); border-radius:999px;
        padding:5px 11px; font-size:12px; color:var(--mut); white-space:nowrap}
  .chip.live{background:#0e2a1d; border-color:#1f7a4d; color:#7ee2a8}
  .chip.warn{background:#2c1414; border-color:#a33; color:#ffb3b3}

  #tabs{flex:none; display:flex; gap:6px; padding:8px 14px; border-bottom:1px solid var(--line)}
  #tabs button{flex:1; padding:9px; border-radius:10px; border:1px solid var(--line);
        background:#131a24; color:var(--mut); font-weight:600}
  #tabs button.on{background:var(--accent); border-color:var(--accent); color:#04121f}

  #body{flex:1; position:relative; min-height:0}
  #map{position:absolute; inset:0; background:#0f141c}
  #side{position:absolute; inset:0; overflow-y:auto; background:var(--bg);
        display:none; z-index:400; padding:8px}
  body.show-list #side{display:block}

  .row{display:flex; align-items:center; gap:11px; padding:11px 12px; border-radius:12px;
       cursor:pointer; border:1px solid transparent}
  .row:active{background:#1a2330}
  .row.active{background:#15233a; border-color:#27457a}
  .dot{width:13px; height:13px; border-radius:50%; flex:none; box-shadow:0 0 0 2px #0007}
  .row .nm{flex:1; font-weight:650; font-size:15px}
  .row .meta{color:var(--mut); font-size:12px; margin-right:2px}
  .row .sc{font-variant-numeric:tabular-nums; font-weight:800; min-width:30px; text-align:right;
           padding:2px 7px; border-radius:8px; background:#131a24}

  #timebar{flex:none; border-top:1px solid var(--line); background:#0f141c;
           padding:9px 14px calc(9px + var(--sheet-pad))}
  #timebar .when{text-align:center; font-weight:750; margin-bottom:7px; font-size:15px}
  #timebar .ctl{display:flex; align-items:center; gap:12px}
  #play{flex:none; width:42px; height:38px; border-radius:11px; border:1px solid var(--line);
        background:#1a2330; color:var(--ink); font-size:15px}
  #play:active{background:#243248}
  input[type=range]{flex:1; -webkit-appearance:none; appearance:none; height:6px; border-radius:6px;
        background:#27323f; outline:none}
  input[type=range]::-webkit-slider-thumb{-webkit-appearance:none; width:24px; height:24px;
        border-radius:50%; background:var(--accent); border:3px solid #0b0f15; cursor:pointer}
  input[type=range]::-moz-range-thumb{width:22px; height:22px; border-radius:50%;
        background:var(--accent); border:3px solid #0b0f15; cursor:pointer}
  .ends{display:flex; justify-content:space-between; color:var(--mut); font-size:11px; margin-top:3px}

  #detail{position:fixed; left:0; right:0; bottom:0; z-index:600; background:var(--panel);
          border-top:1px solid var(--line); border-radius:18px 18px 0 0;
          max-height:80dvh; overflow-y:auto; transform:translateY(110%);
          transition:transform .26s cubic-bezier(.2,.8,.2,1);
          padding:6px 16px calc(18px + var(--sheet-pad)); box-shadow:0 -10px 40px #0008}
  #detail.open{transform:none}
  .grab{width:40px; height:5px; border-radius:3px; background:#36424f; margin:6px auto 12px}
  #detail h2{margin:0 0 2px; font-size:18px}
  #detail .el{color:var(--mut); font-size:13px}
  #detail .x{position:absolute; top:14px; right:16px; color:var(--mut); font-size:20px; cursor:pointer}
  .sum{font-size:14px; margin:11px 0; padding:11px; background:var(--panel2);
       border:1px solid var(--line); border-radius:12px; line-height:1.5}
  .bw{display:inline-block; background:#0e2a1d; color:#7ee2a8; border:1px solid #1f7a4d;
      border-radius:8px; padding:2px 9px; font-weight:700; font-size:13px}
  .spark{margin:10px 0 4px}
  .spark svg{display:block; width:100%; height:42px}
  table{width:100%; border-collapse:collapse; font-size:13px; margin-top:8px}
  th,td{padding:6px 6px; text-align:right; border-bottom:1px solid #1b2531}
  th:first-child,td:first-child{text-align:left; color:var(--mut)}
  th{color:var(--mut); font-weight:600; position:sticky; top:0; background:var(--panel)}
  td.cloud{color:#f0a36b}

  .legend{display:none}
  .leaflet-popup-content-wrapper,.leaflet-popup-tip{background:#121821; color:var(--ink)}
  .leaflet-control-attribution{font-size:10px}
  /* dark-theme the layer switcher */
  .leaflet-control-layers{background:#121821 !important; color:var(--ink);
        border:1px solid var(--line) !important; border-radius:10px; box-shadow:0 6px 20px #0007}
  .leaflet-control-layers-toggle{background-color:#121821; border-radius:8px; filter:invert(.92)}
  .leaflet-control-layers-expanded{padding:8px 10px}
  .leaflet-control-layers label{margin:3px 0; font-size:13px}
  .leaflet-control-layers-separator{border-top:1px solid var(--line)}

  /* ---- Desktop: side-by-side, detail docked right, no tabs ---- */
  @media (min-width:820px){
    #tabs{display:none}
    #body{display:flex}
    #map{position:relative; inset:auto; flex:1; order:2}
    #side{position:relative; inset:auto; display:block; width:360px; flex:none; order:1;
          border-right:1px solid var(--line); z-index:auto}
    #detail{position:absolute; top:14px; right:14px; left:auto; bottom:auto; width:340px;
            max-height:calc(100% - 96px); transform:none; display:none; border-radius:16px;
            border:1px solid var(--line); padding-top:14px}
    #detail.open{display:block}
    #detail .grab{display:none}
    .legend{display:block; position:absolute; left:14px; bottom:16px; z-index:450;
            background:#121821ee; border:1px solid var(--line); border-radius:10px;
            padding:8px 11px; font-size:11px; color:var(--mut)}
    .legend i{display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:4px; vertical-align:-1px}
  }
</style></head>
<body>
<div id="app">
  <header>
    <h1>White Mountains Summit Forecast</h1>
    <div class="sub" id="gen"></div>
    <div class="chips" id="chips"></div>
  </header>
  <div id="tabs">
    <button data-t="map" class="on">🗺️ Map</button>
    <button data-t="list">📋 Peaks</button>
  </div>
  <div id="body">
    <div id="map"></div>
    <div id="side"><div id="list"></div></div>
    <div class="legend">
      <div><i style="background:#34d399"></i>great <i style="background:#fbbf24"></i>ok
        <i style="background:#f87171"></i>poor</div>
      <div style="margin-top:3px">◍ ring = in the clouds that hour</div>
    </div>
  </div>
  <div id="timebar">
    <div class="when" id="when"></div>
    <div class="ctl"><button id="play" aria-label="play">▶</button>
      <input id="hr" type="range" min="0" value="0" step="1"/></div>
    <div class="ends"><span id="e0"></span><span id="e1"></span></div>
  </div>
</div>
<div id="detail"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const D = /*__DATA__*/null;
let idx = 0, selected = null;
const mix=(a,b,t)=>a.map((v,i)=>Math.round(v+(b[i]-v)*t));
const rgb=c=>`rgb(${c[0]},${c[1]},${c[2]})`;
function scoreColor(s){
  if(s==null) return '#8b949e';
  const G=[52,211,153],Y=[251,191,36],R=[248,113,113];
  return s>=50 ? rgb(mix(Y,G,(s-50)/50)) : rgb(mix(R,Y,s/50));
}

// ---- map (enhancement; list+detail work without it) ----
let map=null, markers=[], mapOK=(typeof L!=='undefined');
if(mapOK){ try{
  map = L.map('map',{zoomControl:true, attributionControl:true}).setView([44.18,-71.35],10);

  // Basemaps — all free / no key. Esri & USGS use {z}/{y}/{x} tile order.
  const bases={
    'Topographic': L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
      {maxZoom:17, attribution:'© OpenTopoMap, © OSM'}),
    'Satellite': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      {maxZoom:18, attribution:'© Esri, Maxar'}),
    'Dark': L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
      {maxZoom:19, attribution:'© CARTO, © OSM'}),
    'USGS Topo': L.tileLayer('https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}',
      {maxZoom:16, attribution:'USGS The National Map'}),
    'USGS Imagery+Topo': L.tileLayer('https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryTopo/MapServer/tile/{z}/{y}/{x}',
      {maxZoom:16, attribution:'USGS The National Map'}),
    'NatGeo': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/NatGeo_World_Map/MapServer/tile/{z}/{y}/{x}',
      {maxZoom:16, attribution:'© Esri, National Geographic'}),
    'CyclOSM': L.tileLayer('https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png',
      {maxZoom:18, attribution:'CyclOSM, © OSM'}),
  };
  bases['Topographic'].addTo(map);

  // Overlays
  const overlays={
    'Hiking trails': L.tileLayer('https://tile.waymarkedtrails.org/hiking/{z}/{x}/{y}.png',
      {opacity:.85, attribution:'© waymarkedtrails.org'}),
  };
  // NASA GIBS true-colour clouds (use yesterday UTC for guaranteed availability)
  const gd=new Date(Date.now()-86400000).toISOString().slice(0,10);
  overlays['Satellite clouds']=L.tileLayer(
    'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/'
    +gd+'/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg',
    {maxNativeZoom:9, maxZoom:17, opacity:.8, attribution:'NASA GIBS'});

  const layerCtl=L.control.layers(bases, overlays, {collapsed:true, position:'topright'}).addTo(map);

  // Live precip radar (RainViewer, fetched at view-time so it's always current)
  fetch('https://api.rainviewer.com/public/weather-maps.json').then(r=>r.json()).then(j=>{
    const fr=(j.radar.past||[]).concat(j.radar.nowcast||[]); if(!fr.length) return;
    const last=fr[fr.length-1];
    const radar=L.tileLayer(j.host+last.path+'/256/{z}/{x}/{y}/4/1_1.png',
      {opacity:.6, attribution:'© RainViewer'});
    layerCtl.addOverlay(radar,'Precip radar · now');
  }).catch(()=>{});

  markers = D.peaks.map(p=>{
    const m=L.circleMarker([p.lat,p.lon],{radius:9,weight:2,color:'#0008',fillOpacity:.95});
    m.peak=p; m.addTo(map); m.on('click',()=>select(p));
    m.bindTooltip(p.name,{direction:'top'}); return m;
  });
  map.fitBounds(L.latLngBounds(D.peaks.map(p=>[p.lat,p.lon])).pad(.12));
}catch(e){ mapOK=false; } }
if(!mapOK){ document.getElementById('map').innerHTML=
  '<div style="display:flex;height:100%;align-items:center;justify-content:center;color:#93a1b3;'+
  'text-align:center;padding:24px">Topo map needs a connection.<br>The Peaks list works offline.</div>'; }

function hourOf(p){ return p.hours[Math.min(idx,p.hours.length-1)]; }
function refresh(){
  document.getElementById('when').textContent = D.labels[idx]||'';
  if(mapOK) markers.forEach(m=>{
    const h=hourOf(m.peak), sc=m.peak.type==='spot'?(h.cloud?20:75):h.score;
    m.setStyle({fillColor:scoreColor(m.peak.type==='spot'?null:sc),
      color:h.cloud?'#dff':'#0008', weight:h.cloud?3:2,
      radius:m.peak.type==='spot'?7:9, dashArray:h.cloud?'3 3':null});
  });
  buildList();
  if(selected) renderDetail(selected);
}
function buildList(){
  const L0=document.getElementById('list'); L0.innerHTML='';
  D.peaks.slice().sort((a,b)=>(b.day_score??-1)-(a.day_score??-1)).forEach(p=>{
    const h=hourOf(p), div=document.createElement('div');
    div.className='row'+(selected&&selected.name===p.name?' active':'');
    div.innerHTML=`<span class="dot" style="background:${scoreColor(p.type==='spot'?null:h.score)}"></span>
      <span class="nm">${p.name}</span>
      <span class="meta">${p.elev_ft.toLocaleString()}'${h.cloud?' · ◍':''}</span>
      <span class="sc">${p.day_score??'·'}</span>`;
    div.onclick=()=>{ select(p); if(mapOK) map.panTo([p.lat,p.lon]); };
    L0.appendChild(div);
  });
}
function sparkline(p){
  const sc=p.hours.map(h=>h.score);
  if(sc.every(s=>s==null)) return '';
  const W=300,H=42,n=sc.length,dx=W/Math.max(1,n-1);
  const pts=sc.map((s,i)=>`${(i*dx).toFixed(1)},${(H-3-(s??0)/100*(H-6)).toFixed(1)}`);
  const j=Math.min(idx,n-1), cx=(j*dx).toFixed(1), cy=(H-3-(sc[j]??0)/100*(H-6)).toFixed(1);
  return `<div class="spark"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <line x1="0" y1="${H-3-55/100*(H-6)}" x2="${W}" y2="${H-3-55/100*(H-6)}" stroke="#2a3744" stroke-dasharray="3 3"/>
    <polyline fill="none" stroke="#4aa3ff" stroke-width="2.5" points="${pts.join(' ')}"/>
    <circle cx="${cx}" cy="${cy}" r="4" fill="#7ee2a8"/></svg></div>`;
}
function renderDetail(p){
  const d=document.getElementById('detail'); d.classList.add('open');
  const rows=p.hours.map((h,i)=>`<tr${i===idx?' style="background:#16243a"':''}>
    <td>${h.t}</td><td>${h.temp??'·'}°</td><td>${h.feels??'·'}</td>
    <td>${h.wind??'·'}</td><td>${h.pop??'·'}%</td>
    <td class="${h.cloud?'cloud':''}">${h.cloud?'cloud':(h.vis||'').split(' ')[0]}</td></tr>`).join('');
  d.innerHTML=`<div class="grab"></div>
    <span class="x" onclick="closeDetail()">✕</span>
    <h2>${p.name}</h2>
    <div class="el">${p.elev_ft.toLocaleString()} ft · ${p.range}${p.day_score!=null?` · score ${p.day_score}/100`:''}</div>
    ${sparkline(p)}
    ${p.summary?`<div class="sum">${p.summary}</div>`:''}
    ${p.best_window?`<div class="el" style="margin-bottom:6px">Best window: <span class="bw">${p.best_window}</span></div>`:''}
    ${p.trailhead?`<div class="el">🥾 ${p.trailhead}</div>`:''}
    <table><thead><tr><th>time</th><th>temp</th><th>feels</th><th>wind</th><th>rain</th><th>sky</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}
function closeDetail(){ selected=null; document.getElementById('detail').classList.remove('open'); buildList(); }
function select(p){ selected=p; renderDetail(p); buildList(); }

// ---- header chips ----
document.getElementById('gen').textContent='Updated '+D.generated;
const chips=document.getElementById('chips');
if(D.summit_now){const s=D.summit_now;
  chips.innerHTML+=`<span class="chip live">Mt Washington now · ${s.temp}°F · ${s.wind} mph · ${s.cloud?'in cloud':s.vis_mi+' mi'}</span>`;}
if(D.sunrise) chips.innerHTML+=`<span class="chip">☀ ${D.sunrise} – ${D.sunset}</span>`;
D.alerts.forEach(a=> chips.innerHTML+=`<span class="chip warn">⚠ ${a}</span>`);

// ---- time slider + play ----
const hr=document.getElementById('hr'); hr.max=D.labels.length-1;
document.getElementById('e0').textContent=D.labels[0]||'';
document.getElementById('e1').textContent=D.labels[D.labels.length-1]||'';
hr.oninput=e=>{idx=+e.target.value; refresh();};
let timer=null; const playBtn=document.getElementById('play');
playBtn.onclick=()=>{
  if(timer){clearInterval(timer);timer=null;playBtn.textContent='▶';return;}
  playBtn.textContent='⏸';
  timer=setInterval(()=>{idx=(idx+1)%D.labels.length; hr.value=idx; refresh();},650);
};

// ---- mobile tabs ----
function setTab(t){
  document.body.classList.toggle('show-list', t==='list');
  document.querySelectorAll('#tabs button').forEach(b=>b.classList.toggle('on', b.dataset.t===t));
  if(t==='map' && mapOK) setTimeout(()=>map.invalidateSize(),60);
}
document.querySelectorAll('#tabs button').forEach(b=> b.onclick=()=>setTab(b.dataset.t));
window.addEventListener('resize',()=>{ if(mapOK) map.invalidateSize(); });

refresh();
</script></body></html>"""
