const { buildSnapshot } = require("./_telemetry");

module.exports = (req, res) => {
  const url = new URL(req.url, "http://localhost");
  const threshold = parseFloat(url.searchParams.get("threshold")) || 500;
  const running = url.searchParams.get("running") !== "0";

  res.statusCode = 200;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(buildSnapshot(Date.now() / 1000, threshold, running)));
};
