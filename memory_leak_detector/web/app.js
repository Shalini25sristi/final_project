/* ============================================================
   Sentinel — Anomaly Detection Dashboard · client logic
   ============================================================ */

const $ = (id) => document.getElementById(id);
const els = {
  clock: $("clock"), session: $("session"),
  statusPill: $("statusPill"), statusText: $("statusText"),
  banner: $("warningBanner"), bannerDetail: $("bannerDetail"), bannerClose: $("bannerClose"),
  thInput: $("threshold"), btnSet: $("btnSet"), btnStart: $("btnStart"),
  btnStop: $("btnStop"), btnExport: $("btnExport"), btnRefresh: $("btnRefresh"),
  tick: $("tick"), alerts: $("alerts"), alertCount: $("alertCount"),
  threatTag: $("threatTag"), thRing: $("thRing"), thVal: $("thVal"),
  thLabel: $("thLabel"), thDesc: $("thDesc"),
  samplesInfo: $("samplesInfo"), backendInfo: $("backendInfo"), freshInfo: $("freshInfo"),
  gMem: $("gMem"), gCpu: $("gCpu"), gRisk: $("gRisk"), gHealth: $("gHealth"),
  metaMem: $("metaMem"), metaRisk: $("metaRisk"), metaHealth: $("metaHealth"),
  memVal: document.querySelector('[data-count="mem"]'),
  cpuVal: document.querySelector('[data-count="cpu"]'),
  riskVal: document.querySelector('[data-count="risk"]'),
  healthVal: document.querySelector('[data-count="health"]')
};

const CONFIG = { HISTORY: 320, POLL_MS: 1000, RING_C: 314.16, SPARK_N: 40 };
const state = { times: [], mem: [], cpu: [], risk: [], health: [] };
const seenAlerts = new Set();
let threshold = 500, running = true, sessionStart = Date.now();
let chart = null, sparks = {};
let apiFailures = 0;

/* ============================================================
   Gauges — animated SVG rings
   ============================================================ */
function setGauge(id, frac, color) {
  const el = document.getElementById(id);
  const clamped = Math.min(1, Math.max(0, frac));
  el.style.strokeDashoffset = String(CONFIG.RING_C * (1 - clamped));
  if (color) el.style.stroke = color;
  const glow = clamped > 0.75 ? "0 0 14px rgba(248,113,113,.8)"
              : clamped > 0.5  ? "0 0 12px rgba(251,191,36,.65)"
              : "0 0 7px rgba(56,189,248,.55)";
  el.style.filter = `drop-shadow(${glow})`;
}

/* ============================================================
   Animated counters (requestAnimationFrame count-up)
   ============================================================ */
const counters = { mem: 0, cpu: 0, risk: 0, health: 100 };
const counterRafs = {};
function countUp(key, target, dur = 700) {
  if (counterRafs[key]) cancelAnimationFrame(counterRafs[key]);
  const from = counters[key];
  const t0 = performance.now();
  const ease = (t) => 1 - Math.pow(1 - t, 3);
  const step = (now) => {
    const p = Math.min(1, (now - t0) / dur);
    counters[key] = from + (target - from) * ease(p);
    const label = counters[key].toFixed(0);
    const map = { mem: els.memVal, cpu: els.cpuVal, risk: els.riskVal, health: els.healthVal };
    if (map[key]) map[key].textContent = label;
    if (p < 1) counterRafs[key] = requestAnimationFrame(step); else counterRafs[key] = null;
  };
  counterRafs[key] = requestAnimationFrame(step);
}

/* ============================================================
   Main chart (dual axis + threshold + warning scatter)
   ============================================================ */
function buildChart() {
  const ctx = document.getElementById("chart");
  chart = new Chart(ctx, {
    type: "line",
    data: { datasets: [
      { label: "Memory (MB)", yAxisID: "y", data: [], borderColor: "#38bdf8", backgroundColor: "rgba(56,189,248,.10)", fill: true, tension: .38, borderWidth: 2.5, pointRadius: 0, pointHitRadius: 8 },
      { label: "CPU (%)", yAxisID: "y1", data: [], borderColor: "#fb923c", backgroundColor: "transparent", tension: .38, borderWidth: 2, pointRadius: 0 },
      { label: "Threshold", yAxisID: "y", data: [], type: "line", borderColor: "#fbbf24", borderDash: [7, 6], borderWidth: 1.6, pointRadius: 0 },
      { label: "Warning", type: "scatter", yAxisID: "y", data: [], pointBackgroundColor: "#f87171", pointBorderColor: "#fff", pointBorderWidth: 1.4, pointRadius: 5 }
    ]},
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 650, easing: "easeOutQuart" },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { backgroundColor: "rgba(10,16,30,.92)", borderColor: "rgba(148,163,184,.25)", borderWidth: 1, titleFont: { size: 11, weight: "600" }, bodyFont: { size: 12 }, padding: 12, displayColors: true, cornerRadius: 10 }
      },
      scales: {
        x: { grid: { color: "rgba(148,163,184,.06)" }, ticks: { color: "#55627a", maxTicksLimit: 9, font: { size: 10 } } },
        y: { position: "left", grid: { color: "rgba(148,163,184,.06)" }, ticks: { color: "#38bdf8", font: { size: 10 } }, title: { display: true, text: "MB", color: "#55627a", font: { size: 10 } } },
        y1: { position: "right", grid: { drawOnChartArea: false }, ticks: { color: "#fb923c", font: { size: 10 } }, title: { display: true, text: "%", color: "#55627a", font: { size: 10 } } }
      }
    }
  });
}

/* ============================================================
   Sparklines
   ============================================================ */
const sparkIds = { mem: "spMem", cpu: "spCpu", risk: "spRisk" };
function buildSparklines() {
  const ids = { mem: "spMem", cpu: "spCpu", risk: "spRisk", health: "sparkBtn" };
  for (const key of ["mem","cpu","risk","health"]) {
    sparks[key] = new Chart(document.getElementById(ids[key]), {
      type: "line",
      data: { labels: [], datasets: [{ data: [], borderColor: key==="mem"?"#38bdf8":key==="cpu"?"#fb923c":key==="risk"?"#f87171":"#34d399", borderWidth: 1.6, pointRadius: 0, tension: .45, fill: false }] },
      options: { responsive: true, maintainAspectRatio: false, animation: { duration: 420, easing: "linear" },
        scales: { x: { display: false }, y: { display: false, min: (c)=>Math.min(0, ...c.chart.data.datasets[0].data)-4, max: (c)=>Math.max(265, ...c.chart.data.datasets[0].data)+4 } },
        plugins: { legend: { display: false }, tooltip: { enabled: false } } }
    });
  }
}

/* ============================================================
   Threat level
   ============================================================ */
function updateThreat(risk, health) {
  const lvl = risk >= 75 ? 3 : risk >= 50 ? 2 : risk >= 25 ? 1 : 0;
  const cfg = [
    { tag: "stable",   cls: "stable",   color: "#34d399", word: "STABLE",   label: "System Nominal",               desc: "No anomalous resource growth detected." },
    { tag: "elevated", cls: "elevated", color: "#fbbf24", word: "ELEVATED", label: "Vigilance Mode",                 desc: "Resource growth above baseline; monitor closely." },
    { tag: "high",     cls: "high",     color: "#f87171", word: "HIGH",     label: "Potential Leak",                desc: "Sustained growth pattern consistent with leakage." },
    { tag: "critical", cls: "critical", color: "#ef4444", word: "CRITICAL", label: "Critical — Action Required",    desc: "Resource exhaustion imminent. Investigate now." }
  ][lvl];

  els.threatTag.className = "tw " + cfg.cls;
  els.threatTag.textContent = cfg.word;
  els.thLabel.textContent = cfg.label;
  els.thDesc.textContent = cfg.desc;
  els.thVal.textContent = health.toFixed(0);
  els.thRing.style.background =
    `conic-gradient(${cfg.color} 0%, ${cfg.color} ${health}%, rgba(148,163,184,.12) ${health}% 100%)`;

  document.querySelectorAll("#segMeter span").forEach((s) => {
    s.classList.toggle("on", +s.dataset.lvl === lvl);
  });
  countUp("health", health);
}

/* ============================================================
   Alerts feed
   ============================================================ */
function addAlerts(alerts) {
  for (const [t, mb] of alerts) {
    if (seenAlerts.has(t)) continue;
    seenAlerts.add(t);
    const li = document.createElement("li");
    li.innerHTML = `<span class="ai-dot"></span><span>Memory ${mb.toFixed(0)} MB flagged @ sample ${t}</span><span class="t">${t}s</span>`;
    els.alerts.insertBefore(li, els.alerts.firstChild);
    setTimeout(() => li.classList.add("old"), 9000);
  }
  while (els.alerts.children.length > 14) els.alerts.lastElementChild.remove();
  const has = els.alerts.querySelectorAll("li:not(.empty)").length;
  els.alertCount.textContent = has;
  els.alerts.querySelector(".empty")?.remove();
}

/* ============================================================
   Clock + session timer
   ============================================================ */
function tickClock() {
  const now = new Date();
  els.clock.textContent = [now.getHours(), now.getMinutes(), now.getSeconds()]
    .map((n) => String(n).padStart(2, "0")).join(":");
  const s = sessionStart ? Math.floor((now.getTime() - sessionStart) / 1000) : 0;
  const mm = String(Math.floor(s / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  els.session.textContent = `session ${mm}:${ss}`;
}

/* ============================================================
   Demo mode — simulated telemetry when no backend is reachable
   (e.g. the dashboard is served from static hosting such as
   Firebase). Local usage with the real Python backend is
   unaffected: demo mode only activates after repeated API
   failures.
   ============================================================ */
const demo = {
  active: false,
  t: 0,
  mem: 230,
  cpu: 22,
  leakPhase: false,
  times: [], mems: [], cpus: [],
  alerts: [],
  history: [],
  last: null,
};

function demoStep() {
  if (!running && demo.last) return demo.last;

  demo.t += 1;
  // Randomly drift into (and out of) a simulated leak phase.
  if (!demo.leakPhase && Math.random() < 0.015) demo.leakPhase = true;
  else if (demo.leakPhase && Math.random() < 0.04) demo.leakPhase = false;

  const drift = demo.leakPhase ? 5 + Math.random() * 9 : -1.5 + Math.random() * 4;
  demo.mem = Math.max(110, demo.mem + drift + (Math.random() - 0.5) * 5);
  demo.cpu = Math.min(98, Math.max(4, demo.cpu + (Math.random() - 0.5) * 16));

  const pressure = demo.mem / threshold;
  const risk = Math.round(Math.min(99, Math.max(2,
    pressure * 52 + (demo.leakPhase ? 24 : 0) + (Math.random() - 0.5) * 14)));
  const health = Math.max(1, 100 - risk);
  const breached = demo.mem > threshold;
  const warning = risk >= 60 || breached;

  demo.times.push(demo.t); demo.mems.push(demo.mem); demo.cpus.push(demo.cpu);
  if (demo.times.length > CONFIG.HISTORY) { demo.times.shift(); demo.mems.shift(); demo.cpus.shift(); }
  if (warning) demo.alerts.push([demo.t, +demo.mem.toFixed(1)]);

  const latest = {
    timestamp: new Date().toISOString().slice(0, 19).replace("T", " "),
    sample: demo.t,
    memory_mb: demo.mem.toFixed(2),
    cpu_percent: demo.cpu.toFixed(2),
    risk_score_percent: risk,
    system_health_percent: health,
    threshold_mb: threshold.toFixed(0),
    threshold_breached: breached ? "YES" : "NO",
    status: warning ? "WARNING" : "STABLE",
  };
  demo.history.push(latest);
  if (demo.history.length > 5000) demo.history = demo.history.slice(-5000);

  demo.last = {
    running,
    backend: "browser demo · simulated telemetry",
    threshold,
    sample_count: demo.history.length,
    latest,
    times: demo.times.slice(),
    memory: demo.mems.slice(),
    cpu: demo.cpus.slice(),
    alerts: demo.alerts.slice(-60),
    cpu_max: 100,
  };
  return demo.last;
}

function startDemo() {
  if (demo.active) return;
  demo.active = true;
  sessionStart = Date.now();
  const badge = document.querySelector(".live-badge");
  if (badge) badge.textContent = "DEMO";
  // Warm-up so the charts are not empty on first paint.
  for (let i = 0; i < 39; i++) {
    const p = demoStep();
    state.mem.push(parseFloat(p.latest.memory_mb));
    state.cpu.push(parseFloat(p.latest.cpu_percent));
    state.risk.push(p.latest.risk_score_percent);
    state.health.push(p.latest.system_health_percent);
  }
  console.info("[demo] Backend unreachable — running on simulated telemetry.");
  render(demoStep());
}

const CSV_FIELDS = ["timestamp","sample","memory_mb","cpu_percent","risk_score_percent","system_health_percent","threshold_mb","threshold_breached","status"];
function downloadDemoCsv() {
  const rows = [CSV_FIELDS.join(",")].concat(
    demo.history.map((r) => CSV_FIELDS.map((f) => r[f]).join(","))
  );
  const blob = new Blob([rows.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `monitoring_logs_demo_${new Date().toISOString().slice(0, 19).replace(/[:T-]/g, "")}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ============================================================
   Snapshot driver
   ============================================================ */
async function fetchSnapshot() {
  if (demo.active) { render(demoStep()); return; }
  try {
    // Serverless backends are stateless: echo our client-side state on each poll.
    const res = await fetch(`/api/snapshot?threshold=${threshold}&running=${running ? 1 : 0}`, { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    apiFailures = 0;
    await render(await res.json());
  } catch {
    apiFailures += 1;
    if (apiFailures >= 3) startDemo();
    else onDisconnect();
  }
}

function onDisconnect() {
  setStatus("off", "OFFLINE");
  els.tick.className = "tick idle";
}

function setStatus(kind, text) {
  els.statusPill.className = "status-pill " + kind;
  els.statusText.textContent = text;
}

async function render(d) {
  if (!sessionStart) sessionStart = Date.now();
  running = d.running;
  threshold = d.threshold;
  els.thInput.value = Math.round(threshold);

  const latest = d.latest || {};
  const mem = parseFloat(latest.memory_mb || 0);
  const cpu = parseFloat(latest.cpu_percent || 0);
  const risk = parseFloat(latest.risk_score_percent || 0);
  const health = parseFloat(latest.system_health_percent || 0);

  if (d.threshold && isFinite(d.threshold)) threshold = d.threshold;
  const memMax = Math.max(threshold * 1.25, mem, 60);
  setGauge("gMem", mem / memMax);
  setGauge("gCpu", cpu / 100, cpu > 85 ? "#f87171" : undefined);
  const riskColor = risk >= 75 ? "#f87171" : risk >= 50 ? "#fbbf24" : risk >= 30 ? "#fb923c" : "#34d399";
  setGauge("gRisk", risk / 100, riskColor);
  setGauge("gHealth", health / 100, health < 25 ? "#f87171" : health < 50 ? "#fbbf24" : "#34d399");

  countUp("mem", mem);
  countUp("cpu", cpu);
  countUp("risk", risk);
  countUp("health", health);

  els.metaMem.textContent = `threshold ${threshold.toFixed(0)} MB · live`;
  els.metaRisk.textContent = "≥ 60% is flagged";
  els.metaHealth.textContent = health < 25 ? "Critical" : health < 50 ? "Degraded" : health < 75 ? "Fair" : "Nominal";

  // history + sparks
  state.mem.push(mem); state.cpu.push(cpu); state.risk.push(risk); state.health.push(health);
  while (state.mem.length > CONFIG.HISTORY) { state.mem.shift(); state.cpu.shift(); state.risk.shift(); state.health.shift(); }
  const sN = Math.min(state.mem.length, CONFIG.SPARK_N);
  for (const k of ["mem","cpu","risk","health"]) {
    const s = sparks[k];
    if (!s) continue;
    s.data.datasets[0].data = state[k].slice(-sN);
    s.data.labels = [];
    s.update("none");
  }

  // main chart
  if (chart) {
    const timesArr = (d.times || []).slice(-CONFIG.HISTORY);
    const n = timesArr.length || state.mem.length;
    chart.data.labels = timesArr;
    chart.data.datasets[0].data = state.mem.slice(-n);
    chart.data.datasets[1].data = state.cpu.slice(-n);
    chart.data.datasets[2].data = Array(n).fill(threshold);
    chart.data.datasets[3].data = (d.alerts || [])
      .filter(([t]) => !timesArr.length || t >= timesArr[0])
      .slice(-40)
      .map(([t, v]) => ({ x: t, y: v }));
    chart.update("none");
  }

  if (running) { setStatus("on", "ON WATCH"); els.tick.className = "tick live"; }
  else { setStatus("conn", "PAUSED"); els.tick.className = "tick idle"; }

  els.samplesInfo.textContent = `Samples: ${d.sample_count || 0}`;
  els.backendInfo.textContent = `mode: ${d.backend || "—"}`;
  els.freshInfo.textContent = `last update: ${latest.timestamp || "—"}`;

  updateThreat(risk, health);
  els.banner.hidden = latest.status !== "WARNING" && !(d.alerts && d.alerts.length);
  if (!els.banner.hidden) {
    els.bannerDetail.textContent = `Memory ${mem.toFixed(0)} MB exceeds ${threshold.toFixed(0)} MB at ${latest.timestamp}`;
  }
  addAlerts(d.alerts || []);

  document.body.classList.remove("loading");
}

/* ============================================================
   Controls
   ============================================================ */
async function post(path, body) {
  if (demo.active) return { ok: true, demo: true }; // controls act on local demo state
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {})
  });
  return res.json();
}

els.btnSet.addEventListener("click", async () => {
  const v = parseFloat(els.thInput.value);
  if (!(v > 0)) return;
  await post("/api/threshold", { threshold: v });
  threshold = v;
  els.metaMem.textContent = `threshold ${v.toFixed(0)} MB — of ${v.toFixed(0)}`;
});

els.btnStart.addEventListener("click", async () => { await post("/api/start"); running = true; els.tick.className = "tick live"; });
els.btnStop.addEventListener("click", async () => { await post("/api/stop"); running = false; els.tick.className = "tick idle"; });

els.btnExport.addEventListener("click", async () => {
  const btn = els.btnExport;
  const orig = btn.innerHTML;
  btn.innerHTML = '<span class="spinner"></span>';
  btn.disabled = true;
  try {
    if (demo.active) downloadDemoCsv();
    else location.href = "/api/export.csv?threshold=" + threshold;
  }
  finally { setTimeout(() => { btn.innerHTML = orig; btn.disabled = false; }, 900); }
});

els.bannerClose.addEventListener("click", () => { els.banner.hidden = true; });
els.btnRefresh.addEventListener("click", () => fetchSnapshot());

/* ripple fx */
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".ripple");
  if (!btn) return;
  const r = btn.getBoundingClientRect();
  const s = document.createElement("span");
  const size = Math.max(r.width, r.height);
  s.className = "ripple";
  s.style.width = s.style.height = size + "px";
  s.style.left = e.clientX - r.left - size / 2 + "px";
  s.style.top = e.clientY - r.top - size / 2 + "px";
  btn.appendChild(s);
  setTimeout(() => s.remove(), 650);
});

/* ============================================================
   Boot
   ============================================================ */
buildChart();
buildSparklines();
tickClock();
setInterval(tickClock, 1000);
setStatus("conn", "Connecting");
setInterval(fetchSnapshot, CONFIG.POLL_MS);
fetchSnapshot();