// Serverless is stateless, so the threshold cannot be stored server-side.
// The dashboard keeps it client-side and echoes it on every poll; this
// endpoint just validates and acknowledges the value.
module.exports = (req, res) => {
  const body = req.body || {};
  const value = parseFloat(body.threshold);

  res.statusCode = 200;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify({ ok: true, threshold: value > 0 ? value : 500 }));
};
