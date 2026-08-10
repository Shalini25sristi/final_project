/* Shared telemetry model for the Vercel (serverless) deployment.
 *
 * The original platform samples the host machine once per second from a
 * long-running Python process (memory_leak_detector/monitor.py). Vercel
 * functions are stateless and only run while handling a request, so the
 * live stream is modelled here as a deterministic function of wall-clock
 * time: every poll (from any visitor) sees the same advancing signal,
 * including periodic "leak" episodes that breach the default threshold.
 */

const CYCLE = 180;        // seconds per leak cycle
const LEAK_START = 125;   // ramp begins this many seconds into a cycle
const LEAK_END = 168;     // ramp peak; memory recovers afterwards
const EPOCH = 1786320000; // 2026-08-10T00:00:00Z, sample counter base
const WINDOW = 80;        // samples returned per snapshot

// Deterministic pseudo-random in [-1, 1) — no state needed.
function noise(n) {
  const x = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return (x - Math.floor(x)) * 2 - 1;
}

function memoryAt(t) {
  const phase = t % CYCLE;
  let mb = 330 + 42 * Math.sin(t / 47) + 24 * Math.sin(t / 13 + 1.7) + noise(t) * 16;
  if (phase >= LEAK_START && phase <= LEAK_END) {
    mb += (phase - LEAK_START) * 7.5; // leak ramp, up to ~+320 MB
  }
  return Math.max(120, mb);
}

function cpuAt(t) {
  const phase = t % CYCLE;
  let cpu = 26 + 18 * Math.sin(t / 31 + 0.5) + 10 * Math.sin(t / 7 + 2.1) + noise(t * 3 + 17) * 7;
  if (phase >= LEAK_START && phase <= LEAK_END) {
    cpu += (phase - LEAK_START) * 0.5; // mild CPU pressure during leaks
  }
  return Math.min(97, Math.max(2, cpu));
}

// Same semantics as monitor.py: anomaly score, +20 when over threshold, flag at >= 60.
function riskAt(mem, t, threshold) {
  let score = Math.round(((mem - 250) / Math.max(80, threshold - 250)) * 62 + noise(t * 7 + 5) * 6);
  if (mem > threshold) score += 20;
  return Math.min(99, Math.max(2, score));
}

function sampleAt(t, threshold) {
  const mem = memoryAt(t);
  const cpu = cpuAt(t);
  const score = riskAt(mem, t, threshold);
  return {
    second: t - EPOCH,
    memory_mb: mem,
    cpu_percent: cpu,
    score,
    leak: score >= 60,
  };
}

function timestampOf(nowSec) {
  return new Date(Math.floor(nowSec) * 1000).toISOString().slice(0, 19).replace("T", " ");
}

function buildSnapshot(nowSec, threshold, running) {
  const now = Math.floor(nowSec);
  const times = [];
  const memory = [];
  const cpu = [];
  const alerts = [];

  for (let t = now - WINDOW + 1; t <= now; t++) {
    const s = sampleAt(t, threshold);
    times.push(s.second);
    memory.push(Math.round(s.memory_mb * 100) / 100);
    cpu.push(Math.round(s.cpu_percent * 100) / 100);
    if (s.leak) alerts.push([s.second, Math.round(s.memory_mb * 100) / 100]);
  }

  const latest = sampleAt(now, threshold);
  const health = Math.max(0, 100 - latest.score);
  const breached = latest.memory_mb > threshold;

  return {
    running,
    backend: "Mode: serverless demo (simulated telemetry)",
    threshold,
    sample_count: latest.second,
    latest: {
      timestamp: timestampOf(now),
      sample: latest.second,
      memory_mb: latest.memory_mb.toFixed(2),
      cpu_percent: latest.cpu_percent.toFixed(2),
      risk_score_percent: latest.score,
      system_health_percent: health,
      threshold_mb: threshold.toFixed(0),
      threshold_breached: breached ? "YES" : "NO",
      status: latest.leak ? "WARNING" : "STABLE",
    },
    times,
    memory,
    cpu,
    alerts,
    cpu_max: 100,
  };
}

const CSV_FIELDS = [
  "timestamp", "sample", "memory_mb", "cpu_percent", "risk_score_percent",
  "system_health_percent", "threshold_mb", "threshold_breached", "status",
];

function buildCsv(nowSec, threshold, rows = 120) {
  const now = Math.floor(nowSec);
  const lines = [CSV_FIELDS.join(",")];
  for (let t = now - rows + 1; t <= now; t++) {
    const s = sampleAt(t, threshold);
    const health = Math.max(0, 100 - s.score);
    lines.push([
      timestampOf(t),
      s.second,
      s.memory_mb.toFixed(2),
      s.cpu_percent.toFixed(2),
      s.score,
      health,
      threshold.toFixed(0),
      s.memory_mb > threshold ? "YES" : "NO",
      s.leak ? "WARNING" : "STABLE",
    ].join(","));
  }
  return lines.join("\n") + "\n";
}

module.exports = { buildSnapshot, buildCsv };
