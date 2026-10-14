/* Cloudflare Pages Function — POST /api/close
 *
 * Receives a bot-book close request from the site and dispatches the GitHub
 * Actions "close_position" workflow to record it in the book, commit, and let
 * Cloudflare Pages redeploy.
 *
 * Requires the same GH_DISPATCH_TOKEN used by /api/scan (Actions: read+write).
 *
 * Request: POST, Content-Type application/json, same-origin (_same_origin.js,
 * REFINE200 #52), body
 *   { journal_type: "bot", closes: [{symbol, market, direction, price}, ...] }
 *
 * ONE SHAPE (REFINE200 #172, 2026-10-14). This is the BATCH shape (2026-08-13):
 * N bot-book closes in ONE workflow run -- nine closes as nine serial runs was
 * ~half an hour behind the scan mutex; as one batch it is one dispatch, one
 * commit, one deploy, ~2 minutes for the lot. A single close is a one-entry
 * batch. The old single-close shape ({symbol, price, market, journal_type}) is
 * GONE: its only callers were the manual journal's close modal and the
 * swing/scalp pages, removed 2026-09-21, and both remaining callers (the
 * journal's close-all and the stalled strip) post this shape. It still routed
 * to the legacy swing/scalp journals, i.e. an open write route nothing used.
 * close_position.yml keeps its swing/scalp path for a manual workflow_dispatch.
 *
 * EXIT PRICE SANITY (REFINE200 #53). Every entry's price must sit within
 * PRICE_BAND of that position's last_mark in the PUBLISHED book (the number
 * both callers send). Any positive price used to be booked, so one stray digit
 * wrote a fantasy exit into the only track record. When the published book
 * cannot be read the close is allowed and the gap logged: refusing a real close
 * because a static asset hiccuped would be the worse failure.
 *
 * Access-logged (2026-08-20): every dispatch's envelope goes to KV via
 * _access_log.js — best-effort, never blocks the close. See that file.
 */
import { withAccessLog } from "./_access_log.js";
import { dispatchWorkflow } from "./_dispatch.js";
import { crossSiteRefusal } from "./_same_origin.js";
import { cleanSecret } from "./_secrets.js";

// An exit more than 50% away from the row's last mark is refused. Both callers
// send the mark itself, so a real close sits at 0%; the band only has to
// tolerate the book moving on between page load and click.
const PRICE_BAND = 0.5;
// CLOSES (not requests) per UTC day, REFINE200 #53. One full-book close-all is
// 60 (the book cap); a batch used to cost one unit whatever its size, so the
// cap protected Actions runs but put no ceiling on what could be closed.
const CLOSE_DAILY_CAP = 60;
const BOOK = "/data/vivek_bot_book.json";

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

export const onRequestPost = withAccessLog("/api/close", async ({ request, env }) => {
  const refused = crossSiteRefusal(request);
  if (refused) return json(refused.status, { ok: false, message: refused.message });

  if (!cleanSecret(env.GH_DISPATCH_TOKEN)) {
    return json(503, {
      ok: false,
      message: "GH_DISPATCH_TOKEN not configured — add it to Cloudflare Pages env vars.",
    });
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return json(400, { ok: false, message: "Invalid JSON body." });
  }

  // Validated entry-by-entry and then RE-SERIALISED from the validated fields
  // only — the raw client JSON never reaches the workflow input, so nothing
  // unvalidated can ride along in it.
  if (!Array.isArray(body?.closes)) {
    return json(400, { ok: false, message: 'Send {"journal_type": "bot", "closes": [...]}; a single close is a one-entry batch.' });
  }
  if (body.journal_type !== "bot") {
    return json(400, { ok: false, message: "Batch close is bot-book only." });
  }
  // Ceiling = the book cap (config VIVEK_BOT_MAX_OPEN_TOTAL, 60 since the
  // owner's 2026-09-27 resize; was 30), so a FULL book closes in ONE run.
  // Mirrored by journal.js CLOSE_ALL_MAX and vivek_run CLOSE_BATCH_MAX;
  // tests/test_close_ceiling_parity.py pins all three to config, because a
  // split ceiling accepts a close here that the workflow then refuses.
  if (body.closes.length < 1 || body.closes.length > 60) {
    return json(400, { ok: false, message: "Batch must contain 1-60 closes." });
  }
  const entries = [];
  const seen = new Set();
  for (const c of body.closes) {
    const sym = String(c?.symbol || "").trim().toUpperCase();
    const mkt = String(c?.market || "").trim().toLowerCase();
    const px  = parseFloat(c?.price);
    if (!/^[A-Z0-9.\-]{1,15}$/.test(sym) || !isFinite(px) || px <= 0) {
      return json(400, { ok: false, message: `Batch entry ${sym || "?"}: symbol and a positive price are required.` });
    }
    if (!["asx", "nasdaq", "crypto"].includes(mkt)) {
      return json(400, { ok: false, message: `Batch entry ${sym}: market must be asx|nasdaq|crypto.` });
    }
    const key = mkt + ":" + sym;
    if (seen.has(key)) {
      return json(400, { ok: false, message: `Batch lists ${sym} twice.` });
    }
    seen.add(key);
    entries.push({
      symbol: sym,
      market: mkt,
      direction: c?.direction === "short" ? "short" : "long",
      price: String(px),
    });
  }

  const offBand = await priceBandRefusal(env, request, entries);
  if (offBand) return json(400, { ok: false, message: offBand });

  return dispatchClose(env, {
    // The single-close inputs are required by the workflow and display-only
    // here: the roster makes the Actions list legible at a glance.
    symbol: entries[0].symbol + (entries.length > 1 ? `+${entries.length - 1}` : ""),
    direction: "long",
    market: entries[0].market,
    price: entries[0].price,
    exit_date: "",
    journal_type: "bot",
    batch: JSON.stringify(entries),
  }, entries.length);
});

/* REFINE200 #53: the first entry whose price is outside PRICE_BAND of its
 * published last_mark, as a message; null when every checkable entry is in
 * band. An entry the published book cannot vouch for (not open there, or no
 * usable mark) is passed and logged -- the workflow's own --close refuses a
 * position that is not open, and blocking on a stale deploy would refuse a
 * real close. The whole check is skipped, and logged, if the book is
 * unreadable. */
async function priceBandRefusal(env, request, entries) {
  let book;
  try {
    if (!env.ASSETS) throw new Error("no ASSETS binding");
    const res = await env.ASSETS.fetch(new Request(new URL(BOOK, request.url)));
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    book = await res.json();
  } catch (e) {
    console.log(`[close] exit-price band NOT checked: ${BOOK} unreadable (${(e && e.message) || e})`);
    return null;
  }
  const marks = new Map();
  for (const p of Array.isArray(book && book.open) ? book.open : []) {
    const v = p && p.last_mark;
    if (typeof v === "number" && isFinite(v) && v > 0) {
      marks.set(String(p.market || "").toLowerCase() + ":" + String(p.symbol || "").toUpperCase(), v);
    }
  }
  for (const e of entries) {
    const mark = marks.get(e.market + ":" + e.symbol);
    if (mark == null) {
      console.log(`[close] exit-price band NOT checked for ${e.market}:${e.symbol}: no open row with a usable last_mark in the published book`);
      continue;
    }
    const px = Number(e.price);
    if (px < mark * (1 - PRICE_BAND) || px > mark * (1 + PRICE_BAND)) {
      return `${e.symbol}: exit price ${px} is more than ${Math.round(PRICE_BAND * 100)}% away from its last mark ${mark}, so nothing was closed. ` +
        "Reload the page and close again, or use close_position.yml for a deliberate off-mark price.";
    }
  }
  return null;
}

// Guard rules unchanged from the 2026-07-09/07-29 design: cooldown written
// BEFORE the dispatch (closes the double-click race), refunded if the dispatch
// fails, kept on a timeout (the dispatch MAY have landed, and a duplicate
// close-run costs more than a one-minute wait). The daily cap counts CLOSES
// (#53), and like /api/scan the limiter FAILS CLOSED on a KV error (#158): a
// spent write quota used to switch both guards off for the rest of the day.
async function dispatchClose(env, inputs, nCloses) {
  const token = cleanSecret(env.GH_DISPATCH_TOKEN);
  const repo  = env.GH_REPO || "FakeCurrency/googy-boys-scanner";
  const ref   = env.GH_REF  || "main";

  let refundGuard = null;
  if (env.JOURNAL_KV) {
    const cdKey = "ratelimit:close:batch";
    const dayKey = `ratelimit:close:day:${new Date().toISOString().slice(0, 10)}`;
    let used = 0;
    let wroteCooldown = false;
    try {
      if (await env.JOURNAL_KV.get(cdKey)) {
        return json(429, { ok: false,
          message: "A close was just requested — give it a minute to process." });
      }
      used = parseInt((await env.JOURNAL_KV.get(dayKey)) || "0", 10);
      if (used + nCloses > CLOSE_DAILY_CAP) {
        return json(429, { ok: false,
          message: `Daily close limit: ${used} of ${CLOSE_DAILY_CAP} closes already requested today (UTC), ` +
            `so these ${nCloses} would pass it. close_position.yml still works by hand.` });
      }
      await env.JOURNAL_KV.put(cdKey, "1", { expirationTtl: 60 });
      wroteCooldown = true;
      await env.JOURNAL_KV.put(dayKey, String(used + nCloses), { expirationTtl: 172800 });
    } catch (_) {
      if (wroteCooldown) {
        try { await env.JOURNAL_KV.delete(cdKey); } catch (_) { /* best-effort */ }
      }
      return json(503, { ok: false,
        message: "The close rate limiter is unavailable (Cloudflare KV refused a read or write), so nothing was closed. " +
          "Try again later, or close via close_position.yml (journal_type=bot)." });
    }
    refundGuard = async () => {
      try {
        await env.JOURNAL_KV.delete(cdKey);
        await env.JOURNAL_KV.put(dayKey, String(used), { expirationTtl: 172800 });
      } catch (_) { /* refund is best-effort */ }
    };
  }

  // Transport + the cooldown refund rule live in _dispatch.js.
  const r = await dispatchWorkflow({
    token, repo, workflow: "close_position.yml", ref, inputs, refund: refundGuard,
  });

  if (r.ok) {
    return json(202, {
      ok: true,
      message: nCloses > 1
        ? `${nCloses} closes queued as ONE run — the strip confirms each against the book.`
        : `${inputs.symbol} close queued — the book updates when that run lands (~2 minutes).`,
    });
  }

  if (r.status) {
    // Never echo the upstream body — it can carry token/repo details. But DO
    // say something actionable: this endpoint's input is a deliberate human
    // act on the track record, and it used to give the least useful error of
    // the three dispatch endpoints (flagged in the 2026-08-07 audit).
    const friendly = {
      401: "Dispatch token invalid or expired — regenerate GH_DISPATCH_TOKEN in Cloudflare.",
      403: "Dispatch token lacks permission (needs Actions: Read and write), or GitHub is rate-limiting.",
      404: "close_position.yml or the repo was not found — check GH_REPO.",
      422: "GitHub could not dispatch on this ref — check the branch and workflow inputs.",
      429: "GitHub is rate-limiting dispatches — wait a minute and retry.",
    }[r.status] || `GitHub rejected the request (${r.status}).`;

    return json(502, { ok: false, message: friendly });
  }

  return json(r.aborted ? 504 : 502, {
    ok: false,
    message: r.aborted ? "GitHub took too long — try again." : "Network error reaching GitHub.",
  });
}
