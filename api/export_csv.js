const { buildCsv } = require("./_telemetry");

module.exports = (req, res) => {
  const url = new URL(req.url, "http://localhost");
  const threshold = parseFloat(url.searchParams.get("threshold")) || 500;
  const stamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "");

  res.statusCode = 200;
  res.setHeader("Content-Type", "text/csv; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("Content-Disposition", `attachment; filename="monitoring_logs_${stamp}.csv"`);
  res.end(buildCsv(Date.now() / 1000, threshold));
};
