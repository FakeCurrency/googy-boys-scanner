/* Cloudflare Pages Function — GET /api/price?symbol=JST-USD
 *
 * Server-side proxy to Yahoo Finance so the browser avoids CORS restrictions.
 * Returns { ok, price, symbol } on success or { ok: false, error } on failure.
 */
export const onRequestGet = async ({ request }) => {
  const url = new URL(request.url);
  const symbol = url.searchParams.get("symbol") || "";

  const json = (status, body) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });

  if (!symbol || symbol.length > 30 || !/^[\w.\-^=]+$/i.test(symbol)) {
    return json(400, { ok: false, error: "Invalid symbol" });
  }

  try {
    const yf = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?interval=1d&range=1d`;
    const res = await fetch(yf, {
      headers: { "User-Agent": "Mozilla/5.0" },
      signal: AbortSignal.timeout(8000),
    });
    if (!res.ok) throw new Error(`yf ${res.status}`);

    const data = await res.json();
    const meta  = data?.chart?.result?.[0]?.meta;
    const price = meta?.regularMarketPrice ?? meta?.previousClose ?? null;

    if (price == null) throw new Error("no price");

    return json(200, { ok: true, price: +price.toFixed(8), symbol });
  } catch (err) {
    return json(502, { ok: false, error: String(err) });
  }
};
