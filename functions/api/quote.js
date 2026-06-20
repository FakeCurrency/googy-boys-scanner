// Cloudflare Pages Function — proxies Yahoo Finance v8 for ASX / NASDAQ quotes.
// GET /api/quote?sym=BHP.AX  → { price, currency, time }
// GET /api/quote?sym=AAPL    → { price, currency, time }

export async function onRequestGet(ctx) {
  const sym = new URL(ctx.request.url).searchParams.get("sym") || "";

  // Validate: only safe ticker characters allowed.
  if (!/^[A-Z0-9.]{1,20}$/.test(sym)) {
    return new Response(JSON.stringify({ error: "Invalid symbol" }), {
      status: 400,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  }

  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?interval=1m&range=1d`;

  let resp;
  try {
    resp = await fetch(url, {
      headers: {
        "User-Agent": "Mozilla/5.0 (compatible; GoogyBoysScanner/1.0)",
        "Accept": "application/json",
      },
      cf: { cacheTtl: 0, cacheEverything: false },
    });
  } catch (err) {
    return new Response(JSON.stringify({ error: "Upstream fetch failed: " + String(err) }), {
      status: 503,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  }

  if (!resp.ok) {
    return new Response(JSON.stringify({ error: `Yahoo returned ${resp.status}` }), {
      status: 502,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  }

  let body;
  try {
    body = await resp.json();
  } catch (_) {
    return new Response(JSON.stringify({ error: "Could not parse Yahoo response" }), {
      status: 502,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  }

  const meta = body?.chart?.result?.[0]?.meta;
  if (!meta) {
    return new Response(JSON.stringify({ error: "No data returned for " + sym }), {
      status: 502,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  }

  const price    = meta.regularMarketPrice ?? null;
  const currency = meta.currency ?? "USD";
  const time     = meta.regularMarketTime ?? Math.floor(Date.now() / 1000);

  return new Response(JSON.stringify({ price, currency, time }), {
    status: 200,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}
