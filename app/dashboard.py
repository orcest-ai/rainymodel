"""
RainyModel Dashboard — full observability UI + JSON API endpoints.

Serves a self-contained HTML dashboard (Chart.js + dark theme) and
exposes /dashboard/api/* JSON endpoints consumed by the frontend.
"""

import os

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse

from app.analytics import collector

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _auth_ok(key: str) -> bool:
    master = os.getenv("RAINYMODEL_MASTER_KEY", "")
    if not master:
        return True
    return key == master


# ── JSON API endpoints ─────────────────────────────────────────

@router.get("/api/overview")
async def api_overview(key: str = Query("")):
    if not _auth_ok(key):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return collector.get_overview()


@router.get("/api/providers")
async def api_providers(key: str = Query("")):
    if not _auth_ok(key):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return collector.get_providers()


@router.get("/api/models")
async def api_models(key: str = Query("")):
    if not _auth_ok(key):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return collector.get_models()


@router.get("/api/financial")
async def api_financial(key: str = Query("")):
    if not _auth_ok(key):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return collector.get_financial()


@router.get("/api/timeseries")
async def api_timeseries(key: str = Query(""), bucket: int = Query(5)):
    if not _auth_ok(key):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return collector.get_timeseries(bucket)


@router.get("/api/errors")
async def api_errors(key: str = Query("")):
    if not _auth_ok(key):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return collector.get_errors()


@router.get("/api/policies")
async def api_policies(key: str = Query("")):
    if not _auth_ok(key):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return collector.get_policies()


@router.get("/api/fallbacks")
async def api_fallbacks(key: str = Query("")):
    if not _auth_ok(key):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return collector.get_fallbacks()


@router.get("/api/request-log")
async def api_request_log(key: str = Query(""), limit: int = Query(200)):
    if not _auth_ok(key):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return collector.get_request_log(limit)


@router.get("/api/system-log")
async def api_system_log(
    key: str = Query(""), limit: int = Query(200), level: str = Query("")
):
    if not _auth_ok(key):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return collector.get_system_log(limit, level or None)


# ── HTML dashboard ─────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def dashboard_page(key: str = Query("")):
    if not _auth_ok(key):
        return HTMLResponse("<h1>401 — Unauthorized</h1>", status_code=401)
    return HTMLResponse(DASHBOARD_HTML)


# ---------------------------------------------------------------------------
# Self-contained dashboard HTML  (Chart.js 4 via CDN, dark theme, vanilla JS)
# ---------------------------------------------------------------------------

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RainyModel Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#0f172a;--card:#1e293b;--border:#334155;--text:#e2e8f0;--dim:#94a3b8;
--blue:#3b82f6;--green:#22c55e;--yellow:#eab308;--red:#ef4444;--purple:#a855f7;
--cyan:#06b6d4;--orange:#f97316;--emerald:#10b981;--indigo:#818cf8;--lime:#a3e635}
body{background:var(--bg);color:var(--text);font-family:'Inter',system-ui,-apple-system,sans-serif;
font-size:14px;line-height:1.5;padding:0 16px 48px}
a{color:var(--blue)}
h1{font-size:22px;font-weight:700}
h2{font-size:16px;font-weight:600;margin:32px 0 12px;padding-bottom:8px;border-bottom:1px solid var(--border)}
.hdr{display:flex;align-items:center;justify-content:space-between;padding:16px 0;
border-bottom:1px solid var(--border);margin-bottom:24px;flex-wrap:wrap;gap:8px}
.hdr small{color:var(--dim);font-size:12px}
.badge{display:inline-block;padding:2px 8px;border-radius:9999px;font-size:11px;font-weight:600}
.badge-ok{background:#166534;color:#bbf7d0}
.badge-err{background:#991b1b;color:#fecaca}
.badge-warn{background:#854d0e;color:#fef08a}
.badge-info{background:#1e3a5f;color:#bfdbfe}
/* cards */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px}
.card .label{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--dim);margin-bottom:4px}
.card .value{font-size:26px;font-weight:700}
.card .sub{font-size:11px;color:var(--dim);margin-top:2px}
/* charts */
.chart-row{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}
.chart-box{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px;min-height:260px}
.chart-box h3{font-size:13px;font-weight:600;margin-bottom:8px;color:var(--dim)}
@media(max-width:800px){.chart-row{grid-template-columns:1fr}}
/* tables */
.tbl-wrap{overflow-x:auto;margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:8px 10px;border-bottom:2px solid var(--border);color:var(--dim);
font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap}
td{padding:7px 10px;border-bottom:1px solid var(--border);white-space:nowrap}
tr:hover td{background:rgba(255,255,255,.03)}
.num{text-align:right;font-variant-numeric:tabular-nums}
.ok-text{color:var(--green)}.err-text{color:var(--red)}
/* logs */
.log-box{background:#0c1222;border:1px solid var(--border);border-radius:8px;
max-height:400px;overflow-y:auto;padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:12px}
.log-line{padding:2px 0;border-bottom:1px solid rgba(255,255,255,.04)}
.log-INFO{color:var(--blue)}.log-WARN{color:var(--yellow)}.log-ERROR{color:var(--red)}
.log-DEBUG{color:var(--dim)}
.refresh-bar{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--dim)}
.refresh-bar button{background:var(--card);color:var(--text);border:1px solid var(--border);
border-radius:6px;padding:4px 12px;cursor:pointer;font-size:12px}
.refresh-bar button:hover{background:var(--border)}
.countdown{min-width:20px;text-align:center}
.pill{display:inline-block;padding:1px 7px;border-radius:4px;font-size:11px;font-weight:500}
.pill-free{background:#166534;color:#bbf7d0}
.pill-internal{background:#1e3a5f;color:#bfdbfe}
.pill-premium{background:#581c87;color:#e9d5ff}
.pill-error{background:#991b1b;color:#fecaca}
</style>
</head>
<body>

<div class="hdr">
  <div><h1>RainyModel Dashboard</h1><small>Real-time observability &middot; rm.orcest.ai</small></div>
  <div class="refresh-bar">
    <span id="uptime"></span>
    <span>&middot;</span>
    <span>Refresh in <span class="countdown" id="countdown">30</span>s</span>
    <button onclick="loadAll()">Refresh Now</button>
  </div>
</div>

<!-- overview cards -->
<div class="cards" id="cards"></div>

<!-- time-series charts -->
<div class="chart-row">
  <div class="chart-box"><h3>Request Volume (last 24 h)</h3><canvas id="chartReqs"></canvas></div>
  <div class="chart-box"><h3>Avg Latency ms (last 24 h)</h3><canvas id="chartLat"></canvas></div>
</div>

<!-- distribution charts -->
<div class="chart-row">
  <div class="chart-box"><h3>Requests by Provider</h3><canvas id="chartProvDist"></canvas></div>
  <div class="chart-box"><h3>Requests by Tier (free / internal / premium)</h3><canvas id="chartTier"></canvas></div>
</div>

<!-- provider table -->
<h2>Provider Performance</h2>
<div class="tbl-wrap"><table id="tblProv"></table></div>

<!-- financial -->
<h2>Financial Analysis</h2>
<div class="cards" id="finCards" style="margin-bottom:12px"></div>
<div class="tbl-wrap"><table id="tblFin"></table></div>

<!-- model breakdown -->
<h2>Model Alias Usage</h2>
<div class="tbl-wrap"><table id="tblModels"></table></div>

<!-- errors & fallbacks -->
<h2>Errors &amp; Fallbacks</h2>
<div class="chart-row">
  <div class="chart-box"><h3>Error Types</h3><canvas id="chartErr"></canvas></div>
  <div class="chart-box"><h3>Policy Distribution</h3><canvas id="chartPol"></canvas></div>
</div>
<h2>Fallback Chains</h2>
<div class="tbl-wrap"><table id="tblFb"></table></div>

<!-- request log -->
<h2>Request Log <small style="color:var(--dim)">(last 200)</small></h2>
<div class="tbl-wrap" style="max-height:420px;overflow-y:auto"><table id="tblReqLog"></table></div>

<!-- system log -->
<h2>System Log <small style="color:var(--dim)">(last 200)</small></h2>
<div class="log-box" id="sysLog"></div>

<script>
const P = new URLSearchParams(location.search);
const K = P.get('key') || '';
const api = e => fetch(`/dashboard/api/${e}${e.includes('?')?'&':'?'}key=${K}`).then(r=>r.json());

// chart instances
let cReqs,cLat,cProvDist,cTier,cErr,cPol;

const COLORS = {
  hf:'#eab308',ollamafreeapi:'#a3e635',ollama:'#38bdf8',openrouter:'#818cf8',
  openai:'#10b981',anthropic:'#f97316',xai:'#ef4444',deepseek:'#06b6d4',gemini:'#a855f7'
};
const color = u => COLORS[u] || '#64748b';

function fmtNum(n){return n==null?'—':n.toLocaleString()}
function fmtUsd(n){return n==null?'—':'$'+n.toFixed(4)}
function fmtPct(n){return n==null?'—':n.toFixed(1)+'%'}
function fmtDur(s){
  if(s<60) return s+'s';
  if(s<3600) return Math.floor(s/60)+'m '+s%60+'s';
  const h=Math.floor(s/3600),m=Math.floor((s%3600)/60);
  return h+'h '+m+'m';
}
function pillRoute(r){
  if(r==='free') return '<span class="pill pill-free">FREE</span>';
  if(r==='internal') return '<span class="pill pill-internal">INTERNAL</span>';
  if(r==='premium') return '<span class="pill pill-premium">PREMIUM</span>';
  return '<span class="pill pill-error">'+r+'</span>';
}

// ── loaders ────────────────────────────────────

async function loadOverview(){
  const d = await api('overview');
  document.getElementById('uptime').textContent = 'Uptime: '+fmtDur(d.uptime_s);
  document.getElementById('cards').innerHTML = `
    <div class="card"><div class="label">Total Requests</div><div class="value">${fmtNum(d.total)}</div>
      <div class="sub">${fmtNum(d.ok)} ok &middot; ${fmtNum(d.err)} err</div></div>
    <div class="card"><div class="label">Success Rate</div><div class="value" style="color:${d.success_pct>=95?'var(--green)':d.success_pct>=80?'var(--yellow)':'var(--red)'}">${fmtPct(d.success_pct)}</div>
      <div class="sub">Stream ${fmtPct(d.stream_pct)}</div></div>
    <div class="card"><div class="label">Avg Latency</div><div class="value">${fmtNum(d.avg_ms)}<small style="font-size:14px">ms</small></div>
      <div class="sub">P95 ${fmtNum(d.p95_ms)}ms &middot; P99 ${fmtNum(d.p99_ms)}ms</div></div>
    <div class="card"><div class="label">Estimated Cost</div><div class="value">${fmtUsd(d.cost_usd)}</div>
      <div class="sub">${fmtNum(d.total_tokens)} tokens</div></div>
    <div class="card"><div class="label">Active Providers</div><div class="value">${d.providers}</div>
      <div class="sub">${d.rpm} req/min</div></div>`;
}

async function loadTimeseries(){
  const d = await api('timeseries?bucket=5');
  const labels = d.buckets.map(b=>new Date(b.t).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}));
  const reqs = d.buckets.map(b=>b.reqs);
  const errs = d.buckets.map(b=>b.err);
  const lat = d.buckets.map(b=>b.avg_ms);

  const base = {responsive:true,maintainAspectRatio:false,
    plugins:{legend:{labels:{color:'#94a3b8',font:{size:11}}}},
    scales:{x:{ticks:{color:'#64748b',maxTicksLimit:12},grid:{color:'#1e293b'}},
            y:{ticks:{color:'#64748b'},grid:{color:'#1e293b'}}}};

  if(cReqs) cReqs.destroy();
  cReqs = new Chart(document.getElementById('chartReqs'),{type:'line',
    data:{labels,datasets:[
      {label:'Requests',data:reqs,borderColor:'#3b82f6',backgroundColor:'rgba(59,130,246,.15)',fill:true,tension:.3},
      {label:'Errors',data:errs,borderColor:'#ef4444',backgroundColor:'rgba(239,68,68,.1)',fill:true,tension:.3}
    ]},options:base});

  if(cLat) cLat.destroy();
  cLat = new Chart(document.getElementById('chartLat'),{type:'line',
    data:{labels,datasets:[{label:'Avg Latency (ms)',data:lat,borderColor:'#eab308',
      backgroundColor:'rgba(234,179,8,.12)',fill:true,tension:.3}]},options:base});
}

async function loadProviders(){
  const d = await api('providers');
  // table
  let h='<tr><th>Provider</th><th class="num">Requests</th><th class="num">Success</th><th class="num">Avg ms</th><th class="num">P95 ms</th><th class="num">Min ms</th><th class="num">Max ms</th><th class="num">In Tokens</th><th class="num">Out Tokens</th><th class="num">Cost</th></tr>';
  d.forEach(p=>{
    h+=`<tr><td><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${color(p.upstream)};margin-right:6px"></span>${p.upstream}</td>
    <td class="num">${fmtNum(p.requests)}</td><td class="num ${p.success_pct>=95?'ok-text':'err-text'}">${fmtPct(p.success_pct)}</td>
    <td class="num">${fmtNum(p.avg_ms)}</td><td class="num">${fmtNum(p.p95_ms)}</td>
    <td class="num">${fmtNum(p.min_ms)}</td><td class="num">${fmtNum(p.max_ms)}</td>
    <td class="num">${fmtNum(p.input_tokens)}</td><td class="num">${fmtNum(p.output_tokens)}</td>
    <td class="num">${fmtUsd(p.cost_usd)}</td></tr>`;
  });
  document.getElementById('tblProv').innerHTML=h;

  // doughnut
  if(cProvDist) cProvDist.destroy();
  cProvDist = new Chart(document.getElementById('chartProvDist'),{type:'doughnut',
    data:{labels:d.map(p=>p.upstream),datasets:[{data:d.map(p=>p.requests),
      backgroundColor:d.map(p=>color(p.upstream)),borderWidth:0}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'right',labels:{color:'#94a3b8',font:{size:11}}}}}});
}

async function loadFinancial(){
  const d = await api('financial');
  document.getElementById('finCards').innerHTML = `
    <div class="card"><div class="label">Total Cost</div><div class="value">${fmtUsd(d.total_cost_usd)}</div></div>
    <div class="card"><div class="label">Avg Cost / Request</div><div class="value">${fmtUsd(d.avg_cost_per_req)}</div></div>
    <div class="card"><div class="label">Cost Saving Ratio</div>
      <div class="value" style="color:var(--green)">${fmtPct(d.saving_pct)}</div>
      <div class="sub">Requests served free/internal</div></div>`;
  let h='<tr><th>Provider</th><th class="num">Requests</th><th class="num">Input Tokens</th><th class="num">Output Tokens</th><th class="num">Cost</th><th class="num">Cost/Req</th></tr>';
  (d.breakdown||[]).forEach(r=>{
    h+=`<tr><td>${r.upstream}</td><td class="num">${fmtNum(r.requests)}</td><td class="num">${fmtNum(r.input_tokens)}</td><td class="num">${fmtNum(r.output_tokens)}</td><td class="num">${fmtUsd(r.cost_usd)}</td><td class="num">${fmtUsd(r.cost_per_req)}</td></tr>`;
  });
  document.getElementById('tblFin').innerHTML=h;

  // tier chart
  const td = d.tier_dist||{};
  if(cTier) cTier.destroy();
  cTier = new Chart(document.getElementById('chartTier'),{type:'doughnut',
    data:{labels:['Free','Internal','Premium'],datasets:[{data:[td.free||0,td.internal||0,td.premium||0],
      backgroundColor:['#22c55e','#38bdf8','#a855f7'],borderWidth:0}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'right',labels:{color:'#94a3b8',font:{size:11}}}}}});
}

async function loadModels(){
  const d = await api('models');
  let h='<tr><th>Model Alias</th><th class="num">Requests</th><th class="num">Success</th><th class="num">Avg ms</th></tr>';
  d.forEach(m=>{h+=`<tr><td>${m.model}</td><td class="num">${fmtNum(m.requests)}</td><td class="num">${fmtPct(m.success_pct)}</td><td class="num">${fmtNum(m.avg_ms)}</td></tr>`;});
  document.getElementById('tblModels').innerHTML=h;
}

async function loadErrors(){
  const d = await api('errors');
  if(cErr) cErr.destroy();
  const palette = ['#ef4444','#f97316','#eab308','#a855f7','#3b82f6','#06b6d4'];
  cErr = new Chart(document.getElementById('chartErr'),{type:'pie',
    data:{labels:d.map(e=>e.type),datasets:[{data:d.map(e=>e.count),
      backgroundColor:d.map((_,i)=>palette[i%palette.length]),borderWidth:0}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'right',labels:{color:'#94a3b8',font:{size:11}}}}}});
}

async function loadPolicies(){
  const d = await api('policies');
  if(cPol) cPol.destroy();
  const palette = ['#3b82f6','#a855f7','#22c55e','#eab308'];
  cPol = new Chart(document.getElementById('chartPol'),{type:'pie',
    data:{labels:d.map(p=>p.policy),datasets:[{data:d.map(p=>p.count),
      backgroundColor:d.map((_,i)=>palette[i%palette.length]),borderWidth:0}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'right',labels:{color:'#94a3b8',font:{size:11}}}}}});
}

async function loadFallbacks(){
  const d = await api('fallbacks');
  let h=`<tr><th>Fallback Rate</th><th class="num">${fmtPct(d.fallback_pct)} (${d.fallback_count}/${d.total})</th></tr>`;
  if(d.chains.length){
    h='<tr><th>From</th><th>To</th><th class="num">Count</th></tr>';
    d.chains.forEach(c=>{h+=`<tr><td>${c.from}</td><td>${c.to}</td><td class="num">${c.count}</td></tr>`;});
  }
  document.getElementById('tblFb').innerHTML=h;
}

async function loadRequestLog(){
  const d = await api('request-log?limit=200');
  let h='<tr><th>Time</th><th>Alias</th><th>Upstream</th><th>Route</th><th>Model</th><th>Policy</th><th class="num">ms</th><th>Status</th><th class="num">In</th><th class="num">Out</th><th>Error</th><th>Fallback</th></tr>';
  d.forEach(r=>{
    const t = new Date(r.ts).toLocaleTimeString();
    h+=`<tr>
      <td>${t}</td><td>${r.alias}</td>
      <td><span style="color:${color(r.upstream)}">${r.upstream}</span></td>
      <td>${pillRoute(r.route)}</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis">${r.model}</td>
      <td>${r.policy}</td>
      <td class="num">${r.ms}</td>
      <td class="${r.ok?'ok-text':'err-text'}">${r.ok?'OK':r.code}</td>
      <td class="num">${r.in_tok||'—'}</td><td class="num">${r.out_tok||'—'}</td>
      <td class="err-text">${r.err||''}</td>
      <td>${r.fb||''}</td></tr>`;
  });
  document.getElementById('tblReqLog').innerHTML=h;
}

async function loadSysLog(){
  const d = await api('system-log?limit=200');
  const box = document.getElementById('sysLog');
  box.innerHTML = d.map(l=>`<div class="log-line"><span class="log-${l.level}">[${l.level}]</span> <span style="color:var(--dim)">${new Date(l.ts).toLocaleTimeString()}</span> ${l.msg}</div>`).join('');
  box.scrollTop = box.scrollHeight;
}

// ── orchestrator ───────────────────────────────

async function loadAll(){
  await Promise.all([
    loadOverview(), loadTimeseries(), loadProviders(), loadFinancial(),
    loadModels(), loadErrors(), loadPolicies(), loadFallbacks(),
    loadRequestLog(), loadSysLog()
  ]);
}

// auto-refresh
let cd = 30;
setInterval(()=>{
  cd--;
  document.getElementById('countdown').textContent = cd;
  if(cd<=0){ cd=30; loadAll(); }
},1000);

loadAll();
</script>
</body>
</html>
"""
