/* ⚡ IGNITION — the coil -> ignition deck pill + panel. REPORT-ONLY.

   A name goes quiet for months (SMAs stacked tight, volatility and volume at
   multi-year lows, far under its old highs), then CLOSES out of that base on
   a multiple of its normal volume. scanner/ignition/ publishes
   data/ignition/<market>.json and a pre-registered replay,
   data/ignition/<market>_backtest.json. This file only RENDERS them: it
   writes, posts and stores nothing, and the bot does not trade this lens, so
   every surface says so in words. app.js only places the pill.

   Rules the tests pin (test/ignition.test.js slices these functions):
     1. The pill's N is summary.counts.igniting_confirmed (a COMPLETED bar). A
        break on today's forming bar is a separate "+N forming" note, never in
        N; the IGNITING heading prints the same N. The pill still shows at
        N = 0 when rows exist, so the coiled list is one tap away.
     2. CLOSED rows stay on purpose: a list of survivors is the bias this lens
        exists to catch.
     3. Absent data hides silently. The live file loads lazily (a placeholder
        pill holds the slot), the backtest only when the panel opens, and the
        .catch() covers only the fetch and parse: a render fault is re-raised
        to window.onerror, never mistaken for a missing file (TOP100 #88).
     4. A stale screen says "as of <date>" on the pill and the panel head.
     5. The evidence line READS the backtest; it never computes a statistic.

   Layout (2026-09-30, owner: "very hard on the eyes"): trigger cards say what
   happened in plain sentences; COILED is one table, largest cap first, that
   folds into two-line rows on a phone. */
(() => {
  "use strict";

  // Mirrors scanner/config.py IGNITION_MARKETS (pinned by
  // tests/test_ignition_frontend.py), so a pill never fetches a 404.
  const IGNITION_MARKETS = ["crypto", "asx"];

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // An OWN key only, so a payload value like "toString" or "__proto__" reads
  // as unknown in the tables below instead of hitting Object.prototype.
  const own = (o, k) => o != null && typeof k === "string" && Object.prototype.hasOwnProperty.call(o, k);
  const lookup = (t, k, dflt) => (own(t, k) ? t[k] : dflt);

  const DASH = "—";
  const LIVE_TTL_MS = 5 * 60 * 1000;   // the deck's own refresh cadence
  // A 24/7 screen that last RAN over this long ago is stale: a missed day,
  // with slack for a late cron.
  const STALE_GEN_H = 26;
  // Yesterday's bar closes at 00:00 UTC but its screen runs 00:14 (crons land
  // up to 5h late), so the bar rule waits this long; flagging from 00:00
  // would light STALE every morning and train the reader to ignore it.
  const STALE_BAR_GRACE_H = 6;
  // Markets whose daily bar closes at 00:00 UTC every day. A stock market's
  // weekends and holidays are not the bar rule's business.
  const BAR_24_7 = ["crypto"];
  // A session market's run-age limit in WEEKDAY hours: a Friday screen read
  // Monday is ~18h old, a Monday holiday ~43h; two dead trading days flag.
  const STALE_SESSION_H = 50;
  // Page order, mirroring scanner/ignition/engine.py state_rank.
  const STATE_ORDER = { IGNITING: 0, RUNNING: 1, CLOSED: 2, COILED: 3 };
  const STATE_LABEL = { IGNITING: "Igniting", RUNNING: "Running", CLOSED: "Closed" };
  const SMA9 = "9\u2011SMA";   // a non-breaking hyphen: "9-SMA" never splits over two lines
  // Where a row's bars came from (engine row `source`).
  const SOURCE_LABEL = {
    binance_vision: "Binance", binance: "Binance", bybit: "Bybit",
    coinbase: "Coinbase", yahoo: "Yahoo", cache: "Cached",
  };
  const SOURCE_TIP = {
    binance_vision: "Daily klines from Binance's public market-data mirror (data-api.binance.vision)",
    binance: "Daily klines from Binance",
    bybit: "Daily klines from Bybit",
    coinbase: "Daily candles from Coinbase",
    yahoo: "Yahoo's daily series (every ASX name; for crypto, the fallback for coins no exchange source served)",
    cache: "Bars from the last good download: this run's fetch did not return this symbol",
  };
  const CAVEAT_FALLBACK = "Replayed over today's coin list: coins that pumped " +
    "and then died out of it are missing, so long-breakout results are biased " +
    "UP. Judge them against the random-timing baseline, not against zero.";
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  // Market cap: the engine row's `mcap`, in the market's OWN currency (the
  // paper book's face-value convention), with `mcap_asof` / `mcap_src`.
  // Context only — nothing is filtered on it.
  const CAP_CCY = { asx: "A$", crypto: "US$" };
  const CAP_SRC = { coingecko: "CoinGecko", yahoo: "Yahoo", cache: "the shared cap cache", previous: "the previous run" };
  const CAP_UNITS = [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"], [1, ""]];
  // A coiled row whose price text is longer than this (sub-$0.001 coins)
  // gets a smaller phone font, so the row still fits two lines at 390px.
  const LONG_PX_CHARS = 9;
  // A gap under this many % would print as "0.0%", so the row says "at level".
  const AT_LEVEL_PCT = 0.05;
  // The COILED table's columns: [cell class, head, head tooltip].
  const COIL_COLS = [
    ["c-sym", "Name", "Symbol and company. Hover a row for its quiet readings in words."],
    ["c-cap", "Mkt cap", "Market cap, in the market's own currency (A$ on the ASX, US$ on crypto). Context, not a filter."],
    ["c-px", "Price", "The latest price the screen read"],
    ["c-brk", "Breakout", "The top of the base: a daily close above it, on enough volume, would be a trigger"],
    ["c-gap", "To breakout", "How far the price sits under the breakout level"],
    ["c-bars", "Coiled", "Quiet bars in a row up to the last completed bar; \"last <date>\" = the coil ended after that bar"],
    ["c-dd", "Under high", "How far under its 3-year high"],
    ["c-q", "ATR pctl", "How quiet: ATR as a % of price, as a percentile of its own 2-year history (low = quiet)"],
  ];

  // ── pure helpers (sliced and executed by test/ignition.test.js) ──────────

  function isMarket(m) { return IGNITION_MARKETS.indexOf(String(m == null ? "" : m).toLowerCase()) >= 0; }
  function liveUrl(market) { return `data/ignition/${market}.json`; }
  function btUrl(market) { return `data/ignition/${market}_backtest.json`; }

  // A number the payload carries, or null: NaN/Infinity/strings are missing,
  // never coerced, so a missing field renders a dash, not a 0.
  function num(v) { return (typeof v === "number" && isFinite(v)) ? v : null; }
  // A plain object, or {}: a field read off a missing block is undefined, never a throw.
  function obj(v) { return (v && typeof v === "object" && !Array.isArray(v)) ? v : {}; }

  // A price at every magnitude this lens meets: $84,472.00 · $319.40 ·
  // $1.189 (4 significant figures under $10) · $0.0991, $0.50, $0.000000912
  // (a plain decimal, never an exponent, never under 2 decimals). The band is
  // picked off the ROUNDED value, so 999.996 prints "$1,000.00", never "$1000.00".
  function fmtPx(v) {
    const x = num(v);
    if (x == null) return DASH;
    if (x === 0) return "$0";
    const sign = x < 0 ? "-" : "";
    const a = Math.abs(x);
    if (a < 1) {
      const d = Math.min(100, Math.max(0, 3 - Math.floor(Math.log10(a))));
      const s = a.toFixed(d), t = s.replace(/0+$/, "");
      if (Number(s) < 1) return sign + "$" + (/\.\d\d/.test(t) ? t : a.toFixed(2));
    }
    if (Number(a.toFixed(3)) < 10) return sign + "$" + a.toFixed(3);
    const r2 = Number(a.toFixed(2));
    if (r2 < 1000) return sign + "$" + a.toFixed(2);
    return sign + "$" + r2.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  // Two prices at ONE precision, so a row compares like with like:
  // "$0.04 → $0.058" reads "$0.040 → $0.058". The shorter one is zero-padded.
  function fmtPxPair(a, b) {
    const s = [fmtPx(a), fmtPx(b)];
    const dp = (t) => (t.indexOf(".") < 0 ? 0 : t.length - t.indexOf(".") - 1);
    const want = Math.max(dp(s[0]), dp(s[1]));
    return s.map((t) => (t === DASH || dp(t) === want ? t
      : t + (dp(t) ? "" : ".") + "0".repeat(want - dp(t))));
  }

  // `dp` decimals with an explicit "+" on a positive value. A value that
  // ROUNDS to zero prints as a bare zero: never "-0.0", never "+0.00".
  function signed(x, dp) {
    const s = x.toFixed(dp);
    if (Number(s) === 0) return (0).toFixed(dp);
    return (x > 0 ? "+" : "") + s;
  }

  function fmtPct(v, sign) {
    const x = num(v);
    if (x == null) return DASH;
    const s = x.toFixed(1);
    if (Number(s) === 0) return (0).toFixed(1) + "%";
    return (sign && x > 0 ? "+" : "") + s + "%";
  }

  function fmtR(v) { const x = num(v); return x == null ? DASH : signed(x, 2) + "R"; }
  function fmtX(v) { const x = num(v); return x == null ? DASH : x.toFixed(1) + "×"; }
  function fmtN(v, dp) { const x = num(v); return x == null ? DASH : x.toFixed(dp || 0); }
  function toneOf(v) { const x = num(v); return x == null || x === 0 ? "" : (x > 0 ? "is-up" : "is-down"); }
  function isDay(s) { return typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s); }
  function utcDay(ms) { return new Date(ms).toISOString().slice(0, 10); }

  // "2026-09-04" -> "4 Sep". A daily bar's date, not an instant, so no
  // timezone applies.
  function shortDay(s) {
    if (!isDay(s)) return DASH;
    const m = MONTHS[Number(s.slice(5, 7)) - 1];
    return m ? Number(s.slice(8, 10)) + " " + m : s;
  }

  // Hours between two instants (ms) that fall on a weekday, in UTC.
  function weekdayHours(from, to) {
    if (!(to > from)) return 0;
    let ms = 0;
    let t = from;
    while (t < to) {
      const next = Math.min(to, (Math.floor(t / 86400000) + 1) * 86400000);
      const dow = new Date(t).getUTCDay();
      if (dow !== 0 && dow !== 6) ms += next - t;
      t = next;
    }
    return ms / 3600000;
  }

  // null when fresh, else { asOf, reasons[] }. Stale when a 24/7 market's
  // newest COMPLETED bar is older than UTC-yesterday (after the grace), or the
  // screen last ran too long ago, or its run time is unreadable (unknown is
  // never fresh). `now` is a parameter so the rule is testable.
  function staleOf(payload, market, now) {
    if (!payload || typeof payload !== "object") return null;
    const t = num(now) == null ? Date.now() : now;
    const bars = obj(obj(payload.summary).bars);
    const lastBar = isDay(payload.last_closed_bar) ? payload.last_closed_bar
      : (isDay(bars.completed_last) ? bars.completed_last : null);
    const is247 = BAR_24_7.indexOf(String(market == null ? "" : market).toLowerCase()) >= 0;
    const reasons = [];
    if (lastBar && is247) {
      const want = utcDay(t - 86400000 - STALE_BAR_GRACE_H * 3600000);
      if (lastBar < want) {
        reasons.push("its newest completed daily bar is " + lastBar + ", but " + want +
          " closed at 00:00 UTC and the screen should have had it by " + STALE_BAR_GRACE_H + ":00 UTC");
      }
    }
    const gen = Date.parse(payload.generated_at);
    if (!isFinite(gen)) {
      reasons.push("it carries no readable run time");
    } else if (is247 && (t - gen) / 3600000 > STALE_GEN_H) {
      reasons.push("it last ran " + utcText(payload.generated_at) + ", over " + STALE_GEN_H + "h ago");
    } else if (!is247 && weekdayHours(gen, t) > STALE_SESSION_H) {
      reasons.push("it last ran " + utcText(payload.generated_at) + ", over " + STALE_SESSION_H +
        " weekday hours ago");
    }
    if (!reasons.length) return null;
    return { asOf: lastBar || (isFinite(gen) ? utcDay(gen) : null), reasons };
  }

  // Sort key for one row, or null for a state this page does not know (a
  // future engine state is dropped, never mis-filed into a known section).
  function rowRank(r) {
    if (!r || typeof r !== "object" || !own(STATE_ORDER, r.state)) return null;
    const st = STATE_ORDER[r.state];
    if (st < 3) {
      const bs = num(r.bars_since);
      return [st, r.provisional ? 1 : 0, bs == null ? 99 : bs, -(num(r.rvol) || 0)];
    }
    const c = obj(r.coil);
    const rib = num(c.ribbon_pct);
    return [st, 0, -(num(c.coiled_bars) || 0), rib == null ? 99 : rib];
  }

  // IGNITING (confirmed, then forming) · RUNNING · CLOSED · COILED, freshest
  // first inside each — the engine's order, re-derived for older payloads.
  function groupRows(results) {
    const rows = (Array.isArray(results) ? results : []).filter((r) => rowRank(r));
    rows.sort((a, b) => {
      const x = rowRank(a), y = rowRank(b);
      for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] - y[i];
      return String(a.symbol == null ? "" : a.symbol).localeCompare(String(b.symbol == null ? "" : b.symbol));
    });
    const out = { IGNITING: [], RUNNING: [], CLOSED: [], COILED: [] };
    rows.forEach((r) => out[r.state].push(r));
    return out;
  }

  // The pill's numbers. N is the PUBLISHED confirmed count; the rows are only
  // a fallback for a payload that predates `summary.counts`.
  function countsOf(payload) {
    const g = groupRows(payload && payload.results);
    const s = payload && payload.summary;
    const c = (s && s.counts && typeof s.counts === "object") ? s.counts : {};
    const pick = (v, fallback) => {
      const x = num(v);
      return x == null ? fallback : Math.max(0, Math.round(x));
    };
    return {
      confirmed: pick(c.igniting_confirmed, g.IGNITING.filter((r) => !r.provisional).length),
      provisional: pick(c.provisional, g.IGNITING.filter((r) => r.provisional).length),
      running: g.RUNNING.length,
      closed: g.CLOSED.length,
      coiled: g.COILED.length,
      rows: g.IGNITING.length + g.RUNNING.length + g.CLOSED.length + g.COILED.length,
    };
  }

  function provNote(n) { return "+" + n + " forming"; }

  // What the deck pill shows, or null for no pill. `mark` is escaped HTML
  // that app.js appends after the count; `stale` is staleOf()'s verdict.
  function pillInfo(payload, open, stale) {
    if (!payload || typeof payload !== "object" || !Array.isArray(payload.results)) return null;
    const k = countsOf(payload);
    if (!(k.confirmed > 0 || k.rows > 0)) return null;
    const asOf = stale ? "STALE, as of " + (stale.asOf || DASH) + ": " + stale.reasons.join("; ") + ". " : "";
    const title = asOf + "IGNITION — report-only, not traded by the bot. " +
      k.confirmed + " confirmed ignition(s) on the last completed daily bar: a name " +
      "closing out of a months-long quiet base on a multiple of its normal volume. " +
      (k.provisional ? k.provisional + " more forming on today's bar, unconfirmed and not counted. " : "") +
      "Also on the panel: " + k.running + " running, " + k.closed + " closed, " +
      k.coiled + " coiled. Click to " + (open ? "close" : "open") + " the panel.";
    // Visible TEXT, not only a title: a screen reader and a touch screen get
    // "+1 forming" too, and it cannot be misread as part of the count.
    let mark = k.provisional
      ? `<span class="ig-pmark" title="${esc(k.provisional + " more on the forming bar, unconfirmed: " +
          "today's daily bar has not closed, and a break that closes back inside its base never " +
          "counts. Not included in the number.")}">${esc(provNote(k.provisional))}</span>`
      : "";
    if (stale) {
      mark += `<span class="ig-smark" title="${esc("Stale — as of " + (stale.asOf || DASH))}">⚠` +
        `<span class="ig-vh">${esc(" stale, as of " + (stale.asOf || DASH))}</span></span>`;
    }
    return { n: k.confirmed, provisional: k.provisional, title, mark, open: !!open, stale: !!stale };
  }

  // The placeholder pill while the FIRST fetch is in flight (no reflow).
  function loadingInfo() {
    return {
      loading: true, n: "…", provisional: 0, mark: "", open: false, stale: false,
      title: "IGNITION — report-only, not traded by the bot. Loading the latest screen…",
    };
  }

  function melb(iso) {
    const pm = window.PM;
    return (pm && typeof pm.fmtMelb === "function") ? pm.fmtMelb(iso) : String(iso == null ? "" : iso);
  }

  function utcText(iso) {
    const t = Date.parse(iso);
    if (!isFinite(t)) return "";
    return new Date(t).toISOString().slice(0, 16).replace("T", " ") + " UTC";
  }

  // `src=ignition`: chart.js reads the VENUE off this lens's row for a coin
  // VIVEK has no row for (Binance's TAO is not Yahoo's "TAO-USD").
  function chartHref(market, sym) {
    return "chart.html?m=" + encodeURIComponent(market) + "&s=" + encodeURIComponent(sym) + "&src=ignition";
  }

  function symLink(market, symbol) {
    const sym = String(symbol == null ? "" : symbol);
    return `<a class="ig-sym" href="${esc(chartHref(market, sym))}" title="${esc("Open the " + sym + " chart")}">` +
      `${esc(sym || DASH)}</a>`;
  }

  function tag(text, cls, tip) {
    const c = cls ? " " + cls : "";
    return `<span class="ig-tag${c}"${tip ? ` title="${esc(tip)}"` : ""}>${esc(text)}</span>`;
  }

  // The row's data source as a small muted label. An unknown source string
  // is shown as itself (escaped) rather than hidden; no source, no label.
  function sourceHTML(src) {
    if (typeof src !== "string" || !src) return "";
    return `<span class="ig-src" title="${esc("Data: " + lookup(SOURCE_TIP, src, src))}">` +
      `${esc(lookup(SOURCE_LABEL, src, src))}</span>`;
  }

  // The source most rows share (Yahoo for every ASX name), or null. A coiled
  // row names its source only when it differs from this: the same word on
  // 77 rows buries the one "Cached" worth seeing.
  function mainSource(rows) {
    const n = new Map();
    let best = null;
    (Array.isArray(rows) ? rows : []).forEach((r) => {
      const s = r && typeof r.source === "string" && r.source ? r.source : null;
      if (!s) return;
      n.set(s, (n.get(s) || 0) + 1);
      if (best == null || n.get(s) > n.get(best)) best = s;
    });
    return best;
  }

  // ── market cap ────────────────────────────────────────────────────────────

  // A cap only when it is a real, positive figure; anything else is "none".
  function capOf(v) { const x = num(v); return x != null && x > 0 ? x : null; }
  function ccy(market) { return lookup(CAP_CCY, market, "$"); }

  // Two to three significant figures: A$2.8M, A$94M, A$445M, US$1.2B. A value
  // that rounds across a unit (999.96M) prints in the unit it lands in
  // (1.0B, never 1000M). Missing, zero or junk is a dash — never "0".
  function fmtCap(v, market) {
    const x = capOf(v);
    if (x == null) return DASH;
    let i = CAP_UNITS.findIndex((u) => x >= u[0]);
    if (i < 0) i = CAP_UNITS.length - 1;
    const txt = (k) => {
      const s = x / CAP_UNITS[k][0];
      return Number(s.toFixed(1)) < 10 ? s.toFixed(1) : s.toFixed(0);
    };
    let t = txt(i);
    if (Number(t) >= 1000 && i > 0) t = txt(--i);
    return ccy(market) + t + CAP_UNITS[i][1];
  }

  // "as of 29 Sep, from CoinGecko" — how old the cap is and where it came
  // from; "" when the row says neither.
  function capProv(r) {
    const src = typeof r.mcap_src === "string" && r.mcap_src ? r.mcap_src : "";
    return [isDay(r.mcap_asof) ? "as of " + shortDay(r.mcap_asof) : "",
      src ? "from " + lookup(CAP_SRC, src, src) : ""].filter(Boolean).join(", ");
  }

  function capTip(r, market) {
    const x = capOf(r.mcap);
    if (x == null) return "No market cap on file";
    const prov = capProv(r);
    return "Market cap " + ccy(market) + Math.round(x).toLocaleString("en-US") +
      (prov ? ", " + prov : "") + ". Context, not a filter.";
  }

  // "cap A$198M" / "cap —". The word "cap" is hidden where a column head
  // already says it (the desk table). A missing cap (is-none) is drawn quiet.
  function capHTML(r, market) {
    const none = capOf(r.mcap) == null ? " is-none" : "";
    return `<span class="ig-cap${none}" title="${esc(capTip(r, market))}"><span class="ig-cap-k">cap </span>` +
      `${esc(fmtCap(r.mcap, market))}</span>`;
  }

  // Largest market cap first; rows without one follow in the order they came
  // (the engine's). Array sort is stable, so equal caps keep that order too.
  function sortByCap(rows) {
    const has = (r) => capOf(r.mcap) != null;
    return rows.filter(has).sort((a, b) => capOf(b.mcap) - capOf(a.mcap))
      .concat(rows.filter((r) => !has(r)));
  }

  // ── trigger cards: IGNITING / RUNNING / CLOSED ───────────────────────────

  // What the entry price IS, in words — the engine's `entry_basis`.
  function entryTip(r) {
    if (r.entry_basis === "next_open") {
      return "Entry: the next open after the trigger" + (r.entry_date ? " (" + r.entry_date + ")" : "") +
        " — the fill the replay books, so this R and the backtest's R are one number";
    }
    if (r.entry_basis === "trigger_close") {
      return "Entry: the trigger close, until the next bar opens — then the entry becomes that open";
    }
    return "The price R is measured from";
  }

  // The ONE number a card leads with: a closed trade's exit R (a gap under
  // the stop is NO TRADE, so a dash even if a stray number rides along),
  // otherwise today's R against the entry and stop.
  function outcomeOf(r) {
    if (r.state !== "CLOSED") {
      return { text: fmtR(r.r_now), tone: toneOf(r.r_now), cap: "R now", tip: "Measured from the entry against the stop" };
    }
    if (r.exit_reason === "gap_below_stop") {
      return { text: DASH, tone: "", cap: "no trade", tip: "It opened under the stop, so the replay books no trade and no R" };
    }
    return { text: fmtR(r.exit_r), tone: toneOf(r.exit_r), cap: "exit R",
      tip: "The trade's result: the exit against the entry and stop" +
        (r.exit_pending ? " (priced at the close; the exit fills at the next open)" : "") };
  }

  // A figure inside a sentence: bold, toned when given a tone. "" when the
  // value is missing, so the clause around it drops itself.
  function fig(text, tone) {
    if (text === DASH) return "";
    return `<b${tone === "is-up" || tone === "is-down" ? ` class="${tone}"` : ""}>${esc(text)}</b>`;
  }

  // "Broke out 25 Sep at $1.189 on 6.9× normal volume, 12.3% over its 9-SMA."
  function breakoutLine(r) {
    const d = shortDay(r.trigger_date), px = fig(fmtPx(r.trigger_close)), vol = fig(fmtX(r.rvol));
    const ext = num(r.ext_pct);
    const head = r.provisional ? "Breaking out on the forming " + (d === DASH ? "" : d + " ") + "bar"
      : "Broke out" + (d === DASH ? "" : " " + d);
    return esc(head) + (px ? " at " + px : "") +
      (vol ? " on " + vol + " normal volume" + (r.provisional ? " so far" : "") : "") +
      (ext == null ? "" : ", " + fig(fmtPct(Math.abs(ext))) + (ext < 0 ? " under" : " over") + " its " + SMA9) + ".";
  }

  // An open trigger: "Now $267.96, +171.5% since the 26 Sep open. Best so far +22.42R."
  function sinceLine(r) {
    const px = fig(fmtPx(r.price)), chg = fig(fmtPct(r.change_pct, true), toneOf(r.change_pct));
    const best = fig(fmtR(r.mfe_r), toneOf(r.mfe_r));
    const since = r.entry_basis !== "next_open" ? "the trigger close"
      : (isDay(r.entry_date) ? "the " + shortDay(r.entry_date) + " open" : "the entry");
    return (px ? "Now " + px + (chg ? ", " + chg + " since " + esc(since) : "") + ". " : "") +
      (best ? "Best so far " + best + "." : "");
  }

  // How a closed trigger ended. A gap under the stop is no trade.
  function exitLine(r) {
    const d = shortDay(r.exit_date), on = d === DASH ? "" : " " + esc(d);
    const px = fig(fmtPx(r.exit_price)), at = px ? " at " + px : "";
    const best = fig(fmtR(r.mfe_r), toneOf(r.mfe_r));
    const tail = best ? " Best while held " + best + "." : "";
    if (r.exit_reason === "gap_below_stop") {
      const stop = fig(fmtPx(r.stop));
      return "Opened" + on + at + (stop ? ", under the " + stop + " stop" : "") + ": no trade.";
    }
    if (r.exit_reason === "stop") return "Stopped out" + on + at + "." + tail;
    if (r.exit_reason === "trail" && r.exit_pending) {
      return "Closed under the " + SMA9 + (on ? " on" + on : "") + at + "; the exit fills at the next open." + tail;
    }
    if (r.exit_reason === "trail") return "Exited" + on + at + ", the open after a close under the " + SMA9 + "." + tail;
    const why = typeof r.exit_reason === "string" && r.exit_reason ? r.exit_reason : "closed";
    return "Closed" + on + at + " (" + esc(why) + ")." + tail;
  }

  // A closed row's r_now is today's price against the entry — NOT its result
  // (that is the exit R), so it is named for what it is.
  function heldLine(r) {
    const px = fig(fmtPx(r.price)), held = fig(fmtR(r.r_now), toneOf(r.r_now));
    if (!px && !held) return "";
    return (px ? "Now " + px + (held ? "; " : ".") : "") + (held ? held + " had it been held." : "");
  }

  function storyHTML(r) {
    const p = (html) => (html ? `<p>${html}</p>` : "");
    if (r.state !== "CLOSED") return `<div class="ig-story">${p(breakoutLine(r))}${p(sinceLine(r))}</div>`;
    return `<div class="ig-story">${p(breakoutLine(r))}${p(exitLine(r))}` +
      (r.exit_reason === "gap_below_stop" ? "" : p(heldLine(r))) + `</div>`;
  }

  // One pair of the levels list, escaped here. `note` is a quieter second
  // value (a stop's distance, a measured move's R).
  function level(label, value, tip, note) {
    return `<div${tip ? ` title="${esc(tip)}"` : ""}><dt>${esc(label)}</dt><dd>${esc(value)}` +
      (note && note !== DASH ? ` <span>${esc(note)}</span>` : "") + `</dd></div>`;
  }

  function levelsHTML(r) {
    const risk = num(r.risk_pct);
    const mm = r.mm_passed
      ? level("Measured move", "passed", "The trigger candle already overshot the base's measured move (" +
          fmtPx(r.mm_target) + " sits at or under the entry), so there is nothing left of it above.")
      : level("Measured move", fmtPx(r.mm_target), "The base's height projected up from its top", fmtR(r.mm_r));
    const trail = r.state !== "CLOSED" && num(r.trail) != null
      ? level("Exit line", fmtPx(r.trail), "The 9-SMA trail: a daily close under it exits at the next open") : "";
    return `<dl class="ig-levels">` +
      level("Entry", fmtPx(r.entry), entryTip(r)) +
      level("Stop", fmtPx(r.stop), "The stop, and its distance under the entry (the risk)",
        risk == null ? "" : fmtPct(-Math.abs(risk))) +
      mm + trail + `</dl>`;
  }

  // Where the card's numbers came from, as visible text (a tooltip never
  // reaches a phone): "Bars from Binance · cap as of 29 Sep, from CoinGecko".
  function footHTML(r) {
    const src = sourceHTML(r.source);
    const cap = capOf(r.mcap) == null ? "no market cap on file" : "cap " + (capProv(r) || "on file");
    return `<p class="ig-card-foot">${src ? "Bars from " + src + " · " : ""}${esc(cap)}</p>`;
  }

  function tagsHTML(r, rules) {
    const tags = [];
    const bs = num(r.bars_since);
    if (bs != null) tags.push(tag("day " + (bs + 1), "is-day", (bs + 1) + " daily bar(s) since the trigger, counting the trigger bar"));
    if (r.provisional) {
      tags.push(tag("forming bar · unconfirmed", "is-prov",
        "Triggered on today's still-forming daily bar. It is not a trigger until the bar closes: " +
        "a break that closes back inside the base never counts. Not in the IGNITING count."));
    }
    if (r.wide_stop) {
      const w = num(rules && rules.wide_stop_pct);
      tags.push(tag("wide stop", "is-wide", "Risk " + fmtPct(r.risk_pct) + " of the entry" +
        (w == null ? "" : " — over the " + fmtPct(w) + " wide-stop flag") + ". Flagged, never skipped."));
    }
    return tags.join("");
  }

  // One trigger and what the exit rule has done with it since: a headline
  // (symbol, state, name, the one outcome number), a meta line (cap first,
  // then the tags), two or three plain sentences, the levels, and where the
  // numbers came from. The cap leads the meta line so it sits in one place at
  // every width, never wrapping between a ticker and its name.
  function triggerCardHTML(r, market, rules) {
    const st = String(r.state == null ? "" : r.state);
    const out = outcomeOf(r);
    return `<article class="ig-card ig-${esc(st.toLowerCase())}${r.provisional ? " is-prov" : ""}">` +
      `<div class="ig-card-top"><div class="ig-id"><div class="ig-id-l1">` + symLink(market, r.symbol) +
      `<span class="ig-state">${esc(lookup(STATE_LABEL, st, st))}</span></div>` +
      (r.name ? `<div class="ig-name">${esc(r.name)}</div>` : "") + `</div>` +
      `<div class="ig-out${out.tone ? " " + out.tone : ""}" title="${esc(out.tip)}">` +
      `<b>${esc(out.text)}</b><span>${esc(out.cap)}</span></div></div>` +
      `<div class="ig-card-meta">${capHTML(r, market)}${tagsHTML(r, rules)}</div>` +
      storyHTML(r) + levelsHTML(r) + footHTML(r) + `</article>`;
  }

  // ── COILED: one table, largest market cap first ─────────────────────────

  // How far the price sits under the breakout level, in %, or null.
  function coilGap(r) {
    const lvl = num(r.breakout_level), px = num(r.price);
    return lvl != null && px != null && px > 0 ? (lvl / px - 1) * 100 : null;
  }

  // A base that never left one price: the name has barely traded, so its
  // quiet readings measure no trading, not a base tightening. Tagged, never
  // dropped.
  function isFlatBase(r) {
    const b = obj(r.base);
    const hi = num(b.high), lo = num(b.low);
    return hi != null && lo != null && hi <= lo;
  }

  // The "flat base" tag; its tooltip says which side of the level the price
  // sits on now, unless it is still at it.
  function flatTag(r, gap, at) {
    const b = obj(r.base);
    const now = at || gap == null ? ""
      : " The price now, " + fmtPx(r.price) + ", sits " + (gap > 0 ? "under" : "over") + " that level.";
    return tag("flat base", "is-flat", "Every bar of the " + (num(b.bars) == null ? "" : b.bars + "-bar ") +
      "base traded at one price (" + fmtPx(b.high) + "): it has barely traded, so its quiet readings " +
      "measure no trading, not a base tightening. Shown, not filtered." + now);
  }

  // The row's quiet readings in words, for its hover tooltip.
  function coilTip(r) {
    const c = obj(r.coil), b = obj(r.base);
    const rib = num(c.ribbon_pct);
    return [
      String(r.symbol == null ? "" : r.symbol) + (r.name ? " · " + r.name : ""),
      "SMA spread " + (rib == null ? DASH : rib.toFixed(2) + "%") + " (the 9/26/43/200 SMAs, highest over lowest)",
      "Volatility pctl " + fmtN(c.atr_pctl, 1) + " · volume pctl " + fmtN(c.vol_pctl, 1) +
        " (of its own 2-year history; low = quiet)",
      fmtPct(c.drawdown_pct) + " under its 3-year high",
      "Base " + fmtPx(b.low) + " – " + fmtPx(b.high) + (num(b.bars) == null ? "" : " over " + b.bars + " bars"),
      c.coiled ? "Coiled " + fmtN(c.coiled_bars) + " bar(s) in a row, up to the last completed bar"
        : (isDay(c.last_coiled) ? "The coil ended after " + c.last_coiled : ""),
      typeof r.source === "string" && r.source ? "Bars from " + lookup(SOURCE_LABEL, r.source, r.source) : "",
    ].filter(Boolean).join("\n");
  }

  function coiledRowHTML(r, market, srcMain) {
    const c = obj(r.coil);
    const gap = coilGap(r);
    const at = gap != null && Math.abs(gap) < AT_LEVEL_PCT;
    const flat = isFlatBase(r);
    const [px, brk] = fmtPxPair(r.price, r.breakout_level);
    const atr = num(c.atr_pctl), dd = num(c.drawdown_pct);
    const bars = c.coiled
      ? (num(c.coiled_bars) == null ? DASH : c.coiled_bars + (c.coiled_bars === 1 ? " bar" : " bars"))
      : (isDay(c.last_coiled) ? "last " + shortDay(c.last_coiled) : DASH);
    const flag = flat ? flatTag(r, gap, at) : "";
    const cls = ["ig-tr", c.coiled ? "" : "is-ended", flat && at ? "is-dim" : "",
      Math.max(px.length, brk.length) > LONG_PX_CHARS ? "is-longpx" : ""].filter(Boolean).join(" ");
    return `<tr class="${cls}" title="${esc(coilTip(r))}">` +
      `<td class="c-sym"><div class="ig-symcell">${symLink(market, r.symbol)}` +
      (r.name ? `<span class="ig-name">${esc(r.name)}</span>` : "") + flag +
      (r.source !== srcMain ? sourceHTML(r.source) : "") + `</div></td>` +
      `<td class="c-cap">${capHTML(r, market)}</td>` +
      `<td class="c-px">${esc(px)}</td>` +
      `<td class="c-brk"><span class="ig-ml" aria-hidden="true">→\u00a0</span>${esc(brk)}</td>` +
      `<td class="c-gap${at ? " is-at" : ""}">${esc(gap == null ? DASH : (at ? "at level" : fmtPct(gap, true)))}</td>` +
      `<td class="c-bars">${esc(bars)}</td>` +
      `<td class="c-dd">${esc(dd == null ? DASH : dd.toFixed(0) + "%")}</td>` +
      `<td class="c-q">${esc(atr == null ? DASH : (atr < 1 ? "<1" : String(Math.round(atr))))}</td></tr>`;
  }

  function coiledTableHTML(rows, market, srcMain) {
    return `<table class="ig-tbl"><thead><tr>` +
      COIL_COLS.map(([cls, label, tip]) => `<th scope="col" class="${cls}" title="${esc(tip)}">${esc(label)}</th>`).join("") +
      `</tr></thead><tbody>${sortByCap(rows).map((r) => coiledRowHTML(r, market, srcMain)).join("")}</tbody></table>`;
  }

  // One line under the COILED heading saying what a trigger IS, read off the
  // payload's own params. A definition, never an instruction.
  function coilNote(params) {
    const p = obj(params);
    const rvol = num(p.rvol_min), ext = num(p.max_ext), look = num(p.coil_lookback);
    return "A trigger is a daily close above the breakout level" +
      (rvol == null ? "" : " on at least " + fmtX(rvol) + " normal volume") +
      (ext == null ? "" : ", no more than " + fmtN(ext * 100) + "% over its " + SMA9) +
      ", with the turnover floors met. A \"last\" date under Coiled means the coil ended after that bar" +
      (look == null ? "" : "; a break within " + fmtN(look) + " bars of it still counts") + ".";
  }

  // ── the evidence line ───────────────────────────────────────────────────

  // "loading" until the fetch settles, then "ok" or "absent".
  function entryStatus(e) { return !e || e.at == null ? "loading" : (e.data ? "ok" : "absent"); }
  function fmtP(v) { const x = num(v); return x == null ? DASH : x.toFixed(3); }

  function fmtCI(v) {
    return Array.isArray(v) && v.length === 2 && num(v[0]) != null && num(v[1]) != null
      ? signed(v[0], 2) + ".." + signed(v[1], 2) : DASH;
  }

  // Every number is read off the backtest file; a field it lacks is a dash.
  // Nothing here computes a statistic (not the CI, the P or a difference).
  function evidenceHTML(status, bt, live) {
    if (status === "loading") return `<div class="ig-ev is-pending">${esc("Backtest loading…")}</div>`;
    if (status !== "ok" || !bt || typeof bt !== "object") {
      return `<div class="ig-ev is-pending">${esc("Backtest pending")}</div>`;
    }
    const p = obj(bt.primary);
    const oos = obj(obj(p.by_split).out_of_sample);
    const rnd = obj(obj(bt.baselines).random_timing);
    const vs = obj(obj(bt.versus).random_timing);
    const sc = obj(bt.scoring);
    const pf = num(p.pf);
    const nPar = (n) => "(n " + fmtN(n) + ")";
    const openN = num(p.open);
    // [key, value, trailing note, tooltip, extra class]
    const items = [
      [sc.realised_only === true ? "realised trades" : "trades", fmtN(p.n), "",
        sc.realised_only === true ? "Closed trades only: a trade still open, or with its exit pending, is a mark, never a result" : ""],
    ];
    if (openN != null && openN > 0) {
      items.push(["open", fmtN(openN), "(not counted)",
        "Still open (or exit pending) at the end of the data: marked at " + fmtR(p.open_mtm_r) +
        " in total, and outside every number on this line"]);
    }
    const ci = fmtCI(p.exp_r_ci90);
    items.push(
      ["expectancy", fmtR(p.exp_r), "",
        ci === DASH ? "" : "90% CI " + ci + "R (" + (p.ci_method || "bootstrap") + "); P(exp ≤ 0) " + fmtP(p.boot_p_exp_le_0)],
      ["median", fmtR(p.median_r), ""],
      ["PF", pf != null ? pf.toFixed(2) : (p.pf_note ? "∞ (no losses)" : DASH), ""],
      ["out-of-sample exp", fmtR(oos.exp_r), nPar(oos.n)],
    );
    const hasCI = vs.diff_ci90 != null || vs.p_diff_le_0 != null;
    items.push(["vs random timing", fmtR(vs.diff_r),
      hasCI ? "(90% CI " + fmtCI(vs.diff_ci90) + ", P(no edge) " + fmtP(vs.p_diff_le_0) + ")" : "",
      "THE DECISION NUMBER: " + (sc.decision_statistic ||
        "the primary's expectancy minus the random-timing baseline's, on the same coins") +
        ". Primary n " + fmtN(vs.n_primary) + " vs baseline n " + fmtN(vs.n_baseline) +
        ". Beating random timing, not beating zero, is the bar on a survivor-biased list.",
      "ig-ev-dec"]);
    items.push(
      ["random-timing exp", fmtR(rnd.exp_r), nPar(num(rnd.n) != null ? rnd.n : vs.n_baseline)],
      ["top-5 share", fmtPct(p.top5_share_pct), "",
        num(p.exp_r_ex_top5) == null ? "" : "The best five trades' share of the total R. Expectancy without them: " + fmtR(p.exp_r_ex_top5)],
    );
    const range = Array.isArray(bt.date_range) && bt.date_range.length === 2
      ? bt.date_range[0] + " → " + bt.date_range[1] : "";
    const design = obj(sc.design_cases_excluded);
    const dNames = Object.keys(design);
    const tip = "Walk-forward replay, pre-registered before it ran" +
      (bt.ruleset_version ? " · ruleset " + bt.ruleset_version : "") +
      (range ? " · " + range : "") +
      (bt.generated_at ? " · run " + utcText(bt.generated_at) : "") +
      ". Per-trade R, not a portfolio." +
      (dNames.length ? " Design case(s) excluded from every scored number: " +
        dNames.map((s) => s + (design[s] ? " (from " + design[s] + ")" : "")).join(", ") +
        " — their move informed the thresholds, so they are case studies, never evidence." : "");
    const caveats = Array.isArray(bt.caveats) && bt.caveats.length
      ? bt.caveats.map((x) => String(x == null ? "" : x)).join("\n\n") : CAVEAT_FALLBACK;
    const drift = live && live.ruleset_version && bt.ruleset_version &&
      String(live.ruleset_version) !== String(bt.ruleset_version)
      ? `<span class="ig-ev-warn">${esc("backtest ruleset " + bt.ruleset_version + " ≠ live " + live.ruleset_version)}</span>`
      : "";
    return `<div class="ig-ev"><span class="ig-ev-k" title="${esc(tip)}">${esc("Backtest")}</span>` +
      items.map(([k, v, note, t, cls]) =>
        `<span class="ig-ev-i${cls ? " " + cls : ""}"${t ? ` title="${esc(t)}"` : ""}>${esc(k)} <b>${esc(v)}</b>` +
        (note ? " " + esc(note) : "") + `</span>`).join("") +
      `<span class="ig-ev-cav" title="${esc(caveats + (dNames.length ? "\n\n" + tip : ""))}">${esc("⚠ survivor-biased universe")}</span>` +
      drift + `</div>`;
  }

  // ── the panel head ──────────────────────────────────────────────────────

  // "bars: Binance 117 · Yahoo 36 · …" for the header tooltip.
  function sourcesText(src) {
    const by = obj(src.by_source);
    const parts = Object.keys(by).filter((k) => num(by[k]) != null)
      .map((k) => lookup(SOURCE_LABEL, k, k) + " " + by[k]);
    const dead = obj(src.dead);
    const deadTxt = Object.keys(dead).map((k) => k + " (" + String(dead[k]) + ")");
    const rej = obj(src.identity_rejected);
    const nRej = Object.keys(rej).length;
    return (parts.length ? " · bars: " + parts.join(" · ") : "") +
      (deadTxt.length ? " · unreachable from the runner: " + deadTxt.join(", ") : "") +
      (nRej ? " · " + nRej + " same-ticker listing(s) rejected as a different coin" : "");
  }

  // The market's benchmark against its 200-SMA — context, never a filter.
  // Crypto's block carries btc_* keys; a stock market's the generic ones.
  function regimeHTML(rg) {
    if (!rg || typeof rg !== "object") return "";
    const btc = typeof rg.btc_above_200 === "boolean";
    if (!btc && typeof rg.above_200 !== "boolean") return "";
    const up = btc ? rg.btc_above_200 : rg.above_200;
    const label = btc ? "BTC" : (typeof rg.label === "string" && rg.label ? rg.label : "Index");
    const pct = num(btc ? rg.btc_vs_200_pct : rg.vs_200_pct);
    const close = num(btc ? rg.btc_close : rg.close);
    const sma = num(btc ? rg.btc_sma200 : rg.sma200);
    const text = label + " " + (up ? "above" : "below") + " its 200-SMA" +
      (pct == null ? "" : " (" + fmtPct(pct, true) + ")");
    const tip = (btc
      ? "Context, not a filter: the replay's edge came from periods with BTC above its " +
        "200-SMA, and nothing on this panel is filtered on it."
      : "Context, not a filter: the market's own trend, reported beside the replay's " +
        "split by it; nothing on this panel is filtered on it.") +
      (close != null ? " " + label + " " + (btc ? fmtPx(close) : close.toLocaleString("en-US",
        { minimumFractionDigits: 2, maximumFractionDigits: 2 })) : "") +
      (sma != null ? " vs 200-SMA " + (btc ? fmtPx(sma) : sma.toLocaleString("en-US",
        { minimumFractionDigits: 2, maximumFractionDigits: 2 })) : "") +
      (isDay(rg.as_of) ? ", as of " + rg.as_of : "") + ".";
    return `<span class="ig-regime ${up ? "is-up" : "is-down"}" title="${esc(tip)}">${esc(text)}</span>`;
  }

  // "N coins behind yesterday's close": screened coins whose source had not
  // served that bar yet. Context, not an alarm (Yahoo coins often land late).
  function lagHTML(bars) {
    const n = num(bars.lagging);
    if (n == null || n <= 0) return "";
    const dist = obj(bars.completed_dist);
    const tip = n + " screened coin(s) had no completed " +
      (isDay(bars.expected_completed) ? bars.expected_completed + " " : "") +
      "bar from their source when the screen ran (Yahoo-sourced coins often land late), " +
      "so they are screened through their last final bar." +
      (Object.keys(dist).length ? " Newest completed bar per coin: " +
        Object.keys(dist).map((d) => d + " ×" + dist[d]).join(" · ") : "");
    return `<span class="ig-lag" title="${esc(tip)}">${esc(n + " coin" + (n === 1 ? "" : "s") +
      " behind yesterday's close")}</span>`;
  }

  function headHTML(payload, stale) {
    const p = obj(payload);
    const gen = p.generated_at;
    const s = obj(p.summary);
    const tip = "Market-local/UTC: " + (utcText(gen) || DASH) +
      (p.last_closed_bar ? " · last completed daily bar " + p.last_closed_bar : "") +
      (p.ruleset_version ? " · ruleset " + p.ruleset_version : "") +
      sourcesText(obj(s.sources));
    const badge = stale
      ? ` <span class="ig-stale" title="${esc("This screen is behind: " + stale.reasons.join("; ") +
          (p.market === "crypto" || p.market == null
            ? ". It normally refreshes just after 00:00 UTC and several times a day; check the Ignition workflow runs."
            : ". It normally refreshes just after the close and a few times in session on weekdays; check the Ignition (ASX) workflow runs."))}">` +
        `${esc("⚠ STALE · as of " + (stale.asOf || DASH))}</span>`
      : "";
    const meta = [regimeHTML(p.regime), lagHTML(obj(s.bars))].filter(Boolean);
    return `<div class="ig-head">` +
      `<div class="ig-title">${esc("⚡ IGNITION · coil → ignition")}${badge}</div>` +
      `<div class="ig-sub" title="${esc(tip)}">${esc("Report-only · not traded by the bot · daily bars · updated " +
        (gen ? melb(gen) : DASH))}</div>` +
      (meta.length ? `<div class="ig-meta">${meta.join("")}</div>` : "") +
      `</div>`;
  }

  // ── sections + the whole panel ──────────────────────────────────────────

  // A grid of trigger cards. A lone card gets a wider track (is-solo) so it
  // does not sit in a third of the panel.
  function cardsHTML(rows, cardFn, extra) {
    return `<div class="ig-cards${extra ? " " + extra : ""}${rows.length === 1 ? " is-solo" : ""}">` +
      `${rows.map(cardFn).join("")}</div>`;
  }

  function sectionHTML(cls, label, note, rows, cardFn) {
    return `<section class="ig-sec ${esc(cls)}">` +
      `<h4 class="ig-h">${esc(label)} <b>${esc(rows.length)}</b>` +
      (note ? ` <span class="ig-note">${esc(note)}</span>` : "") + `</h4>` +
      cardsHTML(rows, cardFn) + `</section>`;
  }

  // IGNITING: the heading prints the CONFIRMED count — the pill's N, the same
  // number, from the same function — and the forming-bar breaks sit under
  // their own label, listed but never counted.
  function ignitingHTML(g, k, trig) {
    const conf = g.IGNITING.filter((r) => !r.provisional);
    const prov = g.IGNITING.filter((r) => r.provisional);
    let h = `<section class="ig-sec ig-sec-igniting">` +
      `<h4 class="ig-h">${esc("Igniting")} <b>${esc(k.confirmed)}</b>` +
      ` <span class="ig-note">${esc("confirmed on a completed daily bar")}</span>` +
      (k.provisional ? ` <span class="ig-note ig-prov-note">${esc(provNote(k.provisional) + " (unconfirmed)")}</span>` : "") +
      `</h4>`;
    h += conf.length
      ? cardsHTML(conf, trig)
      : `<p class="ig-empty">${esc(prov.length ? "Nothing confirmed on the last completed daily bar."
          : "Nothing igniting on the last completed daily bar.")}</p>`;
    if (prov.length) {
      h += `<p class="ig-subh">${esc("Forming bar · unconfirmed · not in the count")}</p>` +
        cardsHTML(prov, trig, "ig-cards-prov");
    }
    return h + `</section>`;
  }

  // The whole panel, as one string. `coiledOpen` carries the COILED
  // disclosure's state across a repaint (the backtest landing, a refresh).
  function panelHTML(payload, btStatus, bt, market, coiledOpen, stale) {
    const p = obj(payload);
    const g = groupRows(p.results);
    const k = countsOf(payload);
    const rules = p.rules || {};
    const trig = (r) => triggerCardHTML(r, market, rules);
    let h = headHTML(payload, stale) + evidenceHTML(btStatus, bt, payload);
    h += ignitingHTML(g, k, trig);
    if (g.RUNNING.length) h += sectionHTML("ig-sec-running", "Running", "", g.RUNNING, trig);
    if (g.CLOSED.length) {
      h += sectionHTML("ig-sec-closed", "Closed", "kept on purpose so misses stay visible", g.CLOSED, trig);
    }
    if (g.COILED.length) {
      h += `<details class="ig-coiled"${coiledOpen ? " open" : ""}>` +
        `<summary class="ig-h">${esc("Coiled")} <b>${esc(g.COILED.length)}</b> ` +
        `<span class="ig-note">${esc("quiet bases one close from a trigger")}</span></summary>` +
        `<p class="ig-explain">${esc(coilNote(p.params))}</p>` +
        coiledTableHTML(g.COILED, market, mainSource(p.results)) + `</details>`;
    }
    return h;
  }

  // ── fetch + state ─────────────────────────────────────────────────────────

  const live = {};          // market -> { data, at, inflight, onReady }
  const bts = {};           // market -> same, for the backtest
  let openFor = null;       // the market whose panel is open, or null
  let current = null;       // the market the deck is showing (last sync)
  let painted = "";         // what the panel currently shows, to skip repaints

  // A renderer fault must reach window.onerror, not vanish into a catch.
  const report = (err) => { setTimeout(() => { throw err; }, 0); };

  function getJSON(url) {
    const pm = window.PM;
    const get = (pm && typeof pm.fetchTimeout === "function") ? pm.fetchTimeout : fetch;
    return get(url, { cache: "no-cache" }).then((r) => {
      if (!r || !r.ok) throw new Error(String(r ? r.status : "no response"));
      return r.json();
    });
  }

  function load(store, market, url, ttl, onReady) {
    const e = store[market] || (store[market] = { data: null, at: null, inflight: false, onReady: null });
    const fresh = e.at != null && (ttl == null || Date.now() - e.at < ttl);
    if (fresh) return e;
    if (typeof onReady === "function") e.onReady = onReady;   // the latest caller wins
    if (e.inflight) return e;
    e.inflight = true;
    getJSON(url)
      .then((d) => (d && typeof d === "object" && !Array.isArray(d) ? d : null))
      // Scoped to the FETCH AND THE PARSE only: absent / unreadable => null.
      .catch(() => null)
      .then((d) => {
        // A failed REFRESH keeps the copy already on screen (its own
        // "updated" stamp and the stale rule say how old it is); a first
        // failure hides.
        if (d || e.data == null) e.data = d;
        e.at = Date.now();
        e.inflight = false;
        const cb = e.onReady;
        e.onReady = null;
        if (cb) { try { cb(market); } catch (err) { report(err); } }
      });
    return e;
  }

  // Called by app.js's renderDeckPills. Returns loadingInfo() while the first
  // fetch is in flight (the placeholder pill), pillInfo() once the file has
  // loaded, null for no pill — and starts the lazy load, calling `onReady`
  // (the deck's re-render) once it settles.
  function pill(market, onReady) {
    if (!isMarket(market)) return null;
    const e = load(live, market, liveUrl(market), LIVE_TTL_MS, onReady);
    if (entryStatus(e) === "loading") return loadingInfo();
    return pillInfo(e.data, openFor === market, staleOf(e.data, market, Date.now()));
  }

  function toggle(market) {
    if (!isMarket(market)) return false;
    openFor = openFor === market ? null : market;
    return openFor === market;
  }

  // The pill was drawn "pressed" before a repaint failed: un-press it in
  // place, so the page never shows an open control over a hidden panel.
  function unpress() {
    const list = document.querySelectorAll ? document.querySelectorAll("[data-ignition]") : [];
    Array.prototype.forEach.call(list || [], (el) => {
      if (el.classList) el.classList.remove("is-active");
      if (el.setAttribute) {
        el.setAttribute("aria-pressed", "false");
        el.setAttribute("aria-expanded", "false");
      }
    });
  }

  // Show / hide / repaint #ignition-panel for the market the deck is on.
  function sync(market) {
    // A market switch CLOSES the panel: coming back must not re-open it
    // unasked (the open state belongs to one visit, not to the market).
    if (openFor != null && openFor !== market) openFor = null;
    current = market;
    const host = document.getElementById("ignition-panel");
    if (!host) return;
    const e = live[market];
    if (openFor !== market || !isMarket(market) || !e || !e.data) {
      if (!host.hidden) host.hidden = true;
      if (host.innerHTML) host.innerHTML = "";
      painted = "";
      return;
    }
    // Only now — the panel is open — is the backtest worth its bytes.
    const b = load(bts, market, btUrl(market), null, () => { painted = ""; sync(current); });
    const status = entryStatus(b);
    let html, key;
    // Everything that reads the payload sits inside the try: a value that
    // throws while being read (a generated_at that cannot be coerced) must
    // take the same path as a render fault — panel hidden, open state and
    // pill reset, error reported — not leave the old panel up with no pill.
    try {
      const stale = staleOf(e.data, market, Date.now());
      key = market + "|" + e.at + "|" + status + "|" + b.at + "|" + (stale ? stale.asOf + stale.reasons.length : "");
      if (key === painted && !host.hidden) return;
      const det = host.querySelector ? host.querySelector("details.ig-coiled") : null;
      html = panelHTML(e.data, status, b.data, market, !!(det && det.open), stale);
    } catch (err) {
      host.hidden = true;
      host.innerHTML = "";
      painted = "";
      openFor = null;
      unpress();
      report(err);
      return;
    }
    host.innerHTML = html;
    host.hidden = false;
    painted = key;
  }

  // A market switch hides the panel at once rather than after the new
  // market's payload has loaded (the deck re-renders the pill strip then).
  document.addEventListener("click", (ev) => {
    const b = ev.target && ev.target.closest ? ev.target.closest(".market-btn[data-market]") : null;
    if (b) sync(b.getAttribute("data-market"));
  });

  window.Ignition = { MARKETS: IGNITION_MARKETS.slice(), isMarket, pill, toggle, sync };
})();
