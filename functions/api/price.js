/* Cloudflare Pages Function — GET /api/price?symbol=JST-USD
 *
 * Server-side proxy to Yahoo Finance so the browser avoids CORS restrictions.
 *
 * Default (price only):
 *   GET /api/price?symbol=AAPL            → { ok, price, symbol }
 *
 * History (for the chart fallback when no static scan JSON exists). Pass a
 * range and interval and it also returns OHLCV candles + a "delayed" flag:
 *   GET /api/price?symbol=AAPL&range=2y&interval=1d
 *     → { ok, price, symbol, delayed, candles: [{time,open,high,low,close,volume}] }
 */
export const onRequestGet = async ({ request }) => {
  const url = new URL(request.url);
  const symbol = url.searchParams.get("symbol") || "";

  // Whitelist the few ranges / intervals we actually use so the param can't be
  // used to craft arbitrary upstream requests.
  const RANGES    = new Set(["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "max"]);
  const INTERVALS = new Set(["1m", "5m", "15m", "30m", "60m", "1h", "1d", "1wk", "1mo"]);
  const range    = RANGES.has(url.searchParams.get("range"))       ? url.searchParams.get("range")    : null;
  const interval = INTERVALS.has(url.searchParams.get("interval")) ? url.searchParams.get("interval") : null;
  const wantCandles = Boolean(range && interval);

  const json = (status, body) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });

  if (!symbol || symbol.length > 30 || !/^[\w.\-^=]+$/i.test(symbol)) {
    return json(400, { ok: false, error: "Invalid symbol" });
  }

  try {
    const q = wantCandles ? `interval=${interval}&range=${range}` : `interval=1d&range=1d`;
    const yf = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?${q}`;
    const res = await fetch(yf, {
      headers: { "User-Agent": "Mozilla/5.0" },
      signal: AbortSignal.timeout(9000),
    });
    if (!res.ok) throw new Error(`yf ${res.status}`);

    const data   = await res.json();
    const result = data?.chart?.result?.[0];
    const meta   = result?.meta;
    const price  = meta?.regularMarketPrice ?? meta?.previousClose ?? null;
    if (price == null) throw new Error("no price");

    const body = { ok: true, price: +price.toFixed(8), symbol };

    if (wantCandles) {
      const ts    = result?.timestamp || [];
      const quote = result?.indicators?.quote?.[0] || {};
      const { open = [], high = [], low = [], close = [], volume = [] } = quote;
      const candles = [];
      for (let i = 0; i < ts.length; i++) {
        const o = open[i], h = high[i], l = low[i], c = close[i];
        // Yahoo pads gaps with nulls — skip any incomplete bar.
        if (o == null || h == null || l == null || c == null) continue;
        candles.push({
          time: ts[i],
          open: +o, high: +h, low: +l, close: +c,
          volume: volume[i] == null ? 0 : Math.round(volume[i]),
        });
      }
      body.candles = candles;
      // Non-crypto Yahoo data is ~15 min delayed; surface it so the UI can label.
      body.delayed = true;
    }

    return json(200, body);
  } catch (err) {
    return json(502, { ok: false, error: String(err) });
  }
};
