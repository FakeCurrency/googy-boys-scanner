// Cloudflare Pages Function — proxies Yahoo Finance v8 for historical OHLCV bars.
// GET /api/bars?sym=ORCL&interval=1d&range=2y
// Returns { bars: [{time, open, high, low, close, volume}, ...] } (Unix epoch seconds)

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });

const ALLOWED_INTERVALS = new Set(["1d", "1wk", "1mo"]);
const ALLOWED_RANGES    = new Set(["1y", "2y", "5y", "max"]);

export async function onRequestGet(ctx) {
  const url      = new URL(ctx.request.url);
  const sym      = url.searchParams.get("sym")      || "";
  const interval = url.searchParams.get("interval") || "1d";
  const range    = url.searchParams.get("range")    || "2y";

  if (!/^[A-Za-z0-9.^]{1,20}$/.test(sym))    return json(400, { error: "Invalid symbol" });
  if (!ALLOWED_INTERVALS.has(interval))         return json(400, { error: "Invalid interval" });
  if (!ALLOWED_RANGES.has(range))               return json(400, { error: "Invalid range" });

  const yahooUrl =
    `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}` +
    `?interval=${interval}&range=${range}&includePrePost=false`;

  let resp;
  try {
    resp = await fetch(yahooUrl, {
      headers: {
        "User-Agent": "Mozilla/5.0 (compatible; GoogyBoysScanner/1.0)",
        "Accept": "application/json",
      },
      cf: { cacheTtl: 300 },
    });
  } catch (err) {
    return json(503, { error: "Upstream fetch failed: " + String(err) });
  }

  if (!resp.ok) return json(502, { error: `Yahoo returned ${resp.status}` });

  let body;
  try { body = await resp.json(); } catch (_) { return json(502, { error: "Parse failed" }); }

  const result = body?.chart?.result?.[0];
  if (!result) return json(502, { error: "No data for " + sym });

  const timestamps = result.timestamp || [];
  const q = result.indicators?.quote?.[0] || {};
  const opens   = q.open   || [];
  const highs   = q.high   || [];
  const lows    = q.low    || [];
  const closes  = q.close  || [];
  const volumes = q.volume || [];

  const bars = [];
  for (let i = 0; i < timestamps.length; i++) {
    const c = closes[i];
    if (c == null || !isFinite(c)) continue;
    bars.push({
      time:   timestamps[i],
      open:   opens[i]   ?? c,
      high:   highs[i]   ?? c,
      low:    lows[i]    ?? c,
      close:  c,
      volume: volumes[i] ?? 0,
    });
  }

  return json(200, { bars });
}
