/* ⚡ IGNITION — the coil -> ignition deck pill + panel (2026-09-28). REPORT-ONLY.

   The owner's "QNT-type" play (crypto first; the ASX since 2026-09-29, after
   DTR): a name that goes quiet for months (the
   9/26/43/200 SMAs stacked tight, volatility and volume at multi-year lows,
   far under its old highs) and then CLOSES out of that base on a multiple of
   its normal volume. The engine is scanner/ignition/ and publishes ONE file
   per market, data/ignition/<market>.json, plus a replay the lead engineer
   pre-registered before it ever ran, data/ignition/<market>_backtest.json.

   WHAT THIS FILE IS, AND IS NOT.
     * It RENDERS those two files. It writes nothing, posts nothing, stores
       nothing, and knows nothing about the paper book, the confluence
       machinery or the HIGH CONVICTION rule. The bot does not trade this lens
       and every surface here says so in words, because a lightning bolt on
       the deck reads like a trade signal unless it is told not to.
     * app.js only PLACES the pill (third, straight after "A", so a phone
       sees it without swiping) and calls in here. Every rule — which
       markets, what the count means, when the pill shows, when the data is
       stale, what the panel says — lives in this file so
       test/ignition.test.js can slice the shipped functions and run them.

   THE RULES THE TESTS PIN.
     1. The pill's number is `summary.counts.igniting_confirmed`: triggers on a
        COMPLETED daily bar. A break on today's still-forming bar is not a
        trigger until the bar closes (a poke above the base that closes back
        inside it never counts), so it is a separate "+N forming" marker,
        never part of N — and the panel's IGNITING heading prints the SAME N.
        The pill still shows when N is 0 but rows exist, so the coiled
        watchlist is one tap away on a quiet day.
     2. CLOSED rows are shown ON PURPOSE. A list of only the survivors is the
        survivorship bias this lens exists to stop fooling us with.
     3. Absent data hides silently. The live file is fetched lazily, only on
        an Ignition market (a placeholder pill holds its slot while the FIRST
        fetch is in flight, so the deck does not reflow when it lands); the
        backtest only when the panel opens. The `.catch()` is scoped to the
        FETCH AND THE PARSE (HANDOFF 17.6, TOP100 #88): a missing file is
        "nothing to show", while a fault in anything that renders is
        re-raised asynchronously to window.onerror instead of disguising
        itself as a missing file for weeks.
     4. STALE IS SAID OUT LOUD. A screen whose newest completed bar is older
        than UTC-yesterday (24/7 markets), or that last ran over STALE_GEN_H
        hours ago, marks the pill and the panel header "as of <date>". The
        whole value of this lens is catching a break the morning after it
        closes; a day-old screen presented as today's is the failure.
     5. The evidence line READS the backtest file; it never computes a
        statistic. The decision number is `versus.random_timing` — the
        primary's edge OVER random timing on the same coins, not over zero. */
(() => {
  "use strict";

  // Mirrored from scanner/config.py IGNITION_MARKETS and pinned to it by
  // tests/test_ignition_frontend.py: a market the engine starts screening
  // cannot stay invisible here, and a pill can never appear for a market the
  // engine does not screen (which would only ever fetch a 404).
  const IGNITION_MARKETS = ["crypto", "asx"];

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // An OWN key only. A payload value is looked up in the tables below, and a
  // state/reason/source of "toString", "constructor" or "__proto__" must read
  // as unknown — not as Object.prototype's member (which used to throw).
  const own = (o, k) => o != null && typeof k === "string" && Object.prototype.hasOwnProperty.call(o, k);

  const DASH = "—";
  // The deck auto-refreshes every 5 minutes; the live file is re-read on the
  // same cadence (the engine publishes a handful of times a day).
  const LIVE_TTL_MS = 5 * 60 * 1000;
  // A screen that last RAN more than this long ago is stale whatever its bars
  // say: the workflow runs just past 00:00 UTC plus backstops and four
  // intraday passes, so 26h is a whole missed day with slack for a late cron.
  const STALE_GEN_H = 26;
  // Yesterday's bar closes at 00:00 UTC, but the screen that reads it runs at
  // 00:14 with backstops at 01:14 / 02:14, and GitHub has delivered crons
  // 2-5h late. Flagging from 00:00 would light STALE every morning (10-11am
  // Melbourne) for a run that is simply due — a daily alarm that trains the
  // reader to ignore it. So the bar rule waits this long past 00:00 UTC; a
  // pipeline that is really dead is still caught by STALE_GEN_H.
  const STALE_BAR_GRACE_H = 6;
  // Markets that trade 24/7: yesterday's UTC daily bar is complete at 00:00
  // UTC, so a screen whose newest completed bar is older than that is a day
  // behind. A stock market's calendar (weekends, holidays) is not this
  // rule's business — only the generated_at rule applies to one.
  const BAR_24_7 = ["crypto"];
  // A session market (the ASX) publishes after its close and a few times in
  // session, weekdays only. Its run-age rule counts WEEKDAY hours (Saturday
  // and Sunday UTC do not count) against this limit: a Friday screen read on
  // Monday morning is ~18 weekday hours old, and 50 still clears a Monday
  // public holiday (~43h) without a false alarm, while a pipeline dead for two
  // trading days is flagged.
  const STALE_SESSION_H = 50;
  // Page order, mirroring scanner/ignition/engine.py state_rank.
  const STATE_ORDER = { IGNITING: 0, RUNNING: 1, CLOSED: 2, COILED: 3 };
  const EXIT_TEXT = {
    trail: "closed under the 9-SMA",
    stop: "stop hit",
    gap_below_stop: "gapped under the stop at the open - no trade",
  };
  // Where a row's bars came from (engine row `source`). binance_vision is
  // Binance's public market-data mirror — the same candles as Binance.
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

  // ── pure helpers (sliced and executed by test/ignition.test.js) ──────────

  function isMarket(m) {
    return IGNITION_MARKETS.indexOf(String(m == null ? "" : m).toLowerCase()) >= 0;
  }

  function liveUrl(market) {
    return `data/ignition/${market}.json`;
  }

  function btUrl(market) {
    return `data/ignition/${market}_backtest.json`;
  }

  // A number the payload actually carries, or null. NaN/Infinity/strings are
  // "missing", never coerced — a missing field renders as a dash, not a 0.
  function num(v) {
    return (typeof v === "number" && isFinite(v)) ? v : null;
  }

  // A plain object the payload carries, or {} — so a field read off a missing
  // or malformed block is simply undefined, never a throw.
  function obj(v) {
    return (v && typeof v === "object" && !Array.isArray(v)) ? v : {};
  }

  // A price, legible at every magnitude this lens meets:
  //   >= $1,000   thousands separator, 2 dp        $84,472.00
  //   $10–$1,000  2 dp                             $319.40
  //   $1–$10      3 dp = 4 significant figures     $1.189 vs a $1.098 stop
  //   under $1    4 significant figures, a PLAIN decimal (never an exponent),
  //               trailing zeros trimmed           $0.0991, $0.000000912
  // The band is chosen off the value ROUNDED at the lower band's precision,
  // so a price that rounds across a boundary (999.996, 9.9996, 0.99996) is
  // printed in the format of the side it lands on: "$1,000.00", never
  // "$1000.00".
  function fmtPx(v) {
    const x = num(v);
    if (x == null) return DASH;
    if (x === 0) return "$0";
    const sign = x < 0 ? "-" : "";
    const a = Math.abs(x);
    if (a < 1) {
      const d = Math.min(100, Math.max(0, 3 - Math.floor(Math.log10(a))));
      const s = a.toFixed(d);
      if (Number(s) < 1) return sign + "$" + (s.indexOf(".") >= 0 ? s.replace(/0+$/, "").replace(/\.$/, "") : s);
    }
    if (Number(a.toFixed(3)) < 10) return sign + "$" + a.toFixed(3);
    const r2 = Number(a.toFixed(2));
    if (r2 < 1000) return sign + "$" + a.toFixed(2);
    return sign + "$" + r2.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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

  function fmtR(v) {
    const x = num(v);
    return x == null ? DASH : signed(x, 2) + "R";
  }

  function fmtX(v) {
    const x = num(v);
    return x == null ? DASH : x.toFixed(1) + "×";
  }

  function fmtN(v, dp) {
    const x = num(v);
    return x == null ? DASH : x.toFixed(dp || 0);
  }

  function toneOf(v) {
    const x = num(v);
    return x == null || x === 0 ? "" : (x > 0 ? "is-up" : "is-down");
  }

  function isDay(s) {
    return typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s);
  }

  function utcDay(ms) {
    return new Date(ms).toISOString().slice(0, 10);
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

  // Is this screen stale, as of `now` (ms)? null when fresh, else
  // { asOf, reasons[] }. Two independent tests, either one is enough:
  //   * its newest COMPLETED daily bar (last_closed_bar, else
  //     summary.bars.completed_last) is older than UTC-yesterday on a 24/7
  //     market, once STALE_BAR_GRACE_H has passed since 00:00 UTC — the bar
  //     that should be final AND screened by now is not in it;
  //   * it last ran over STALE_GEN_H hours ago (a session market: over
  //     STALE_SESSION_H WEEKDAY hours ago), or it carries no readable run
  //     time at all (unknown is never read as fresh).
  // `now` is a parameter so the rule is testable; the module passes the clock.
  function staleOf(payload, market, now) {
    if (!payload || typeof payload !== "object") return null;
    const t = num(now) == null ? Date.now() : now;
    const bars = obj(obj(payload.summary).bars);
    const lastBar = isDay(payload.last_closed_bar) ? payload.last_closed_bar
      : (isDay(bars.completed_last) ? bars.completed_last : null);
    const reasons = [];
    if (lastBar && BAR_24_7.indexOf(String(market == null ? "" : market).toLowerCase()) >= 0) {
      const want = utcDay(t - 86400000 - STALE_BAR_GRACE_H * 3600000);
      if (lastBar < want) {
        reasons.push("its newest completed daily bar is " + lastBar + ", but " + want +
          " closed at 00:00 UTC and the screen should have had it by " + STALE_BAR_GRACE_H + ":00 UTC");
      }
    }
    const gen = Date.parse(payload.generated_at);
    const is247 = BAR_24_7.indexOf(String(market == null ? "" : market).toLowerCase()) >= 0;
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
  // OWN keys only: "toString" / "constructor" / "__proto__" are unknown.
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

  // IGNITING (confirmed first, then provisional) · RUNNING · CLOSED · COILED,
  // freshest / strongest first inside each — the engine's own order, re-derived
  // so a hand-edited or older payload still reads the same way.
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

  function provNote(n) {
    return "+" + n + " forming";
  }

  // What the deck pill shows, or null for "no pill". `mark` is finished,
  // escaped HTML for app.js's pill() helper to append after the count.
  // `stale` is staleOf()'s verdict (null = fresh).
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

  // The placeholder app.js draws while the FIRST fetch is in flight, so the
  // pill's slot is held and the deck does not reflow when the file lands.
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

  // `src=ignition` (2026-09-28): the chart's back-link reads it, and chart.js
  // reads the VENUE off this lens's row for a coin VIVEK has no row for —
  // TAO (Bittensor) is Binance-sourced here and is NOT Yahoo's "TAO-USD", so
  // a bare m+s link dead-ended on "No chart data".
  function chartHref(market, sym) {
    return "chart.html?m=" + encodeURIComponent(market) + "&s=" + encodeURIComponent(sym) + "&src=ignition";
  }

  // One label/value cell. Both are TEXT, escaped here — nothing reaches the
  // page through a cell unescaped. `tone` is one of a fixed set of classes.
  function kv(label, text, tone, tip) {
    const cls = tone === "is-up" || tone === "is-down" ? " " + tone : "";
    return `<div class="ig-kv${cls}"${tip ? ` title="${esc(tip)}"` : ""}>` +
      `<dt>${esc(label)}</dt><dd>${esc(text)}</dd></div>`;
  }

  function tag(text, cls, tip) {
    const c = cls ? " " + cls : "";
    return `<span class="ig-tag${c}"${tip ? ` title="${esc(tip)}"` : ""}>${esc(text)}</span>`;
  }

  // The row's data source as a small muted label. An unknown source string
  // is shown as itself (escaped) rather than hidden; no source, no label.
  function sourceHTML(src) {
    if (typeof src !== "string" || !src) return "";
    const label = own(SOURCE_LABEL, src) ? SOURCE_LABEL[src] : src;
    const tip = "Data: " + (own(SOURCE_TIP, src) ? SOURCE_TIP[src] : src);
    return `<span class="ig-src" title="${esc(tip)}">${esc(label)}</span>`;
  }

  function cardHead(r, market, tags) {
    const sym = String(r.symbol == null ? "" : r.symbol);
    return `<div class="ig-card-head">` +
      `<a class="ig-sym" href="${esc(chartHref(market, sym))}" title="${esc("Open the " + sym + " chart")}">${esc(sym || DASH)}</a>` +
      (r.name ? `<span class="ig-name">${esc(r.name)}</span>` : "") +
      sourceHTML(r.source) +
      (tags.length ? `<span class="ig-tags">${tags.join("")}</span>` : "") +
      `</div>`;
  }

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

  // IGNITING / RUNNING / CLOSED — one trigger, and what the exit rule has
  // done with it since.
  function triggerCardHTML(r, market, rules) {
    const st = String(r.state == null ? "" : r.state);
    const prov = !!r.provisional;
    const gap = r.exit_reason === "gap_below_stop";
    const tags = [];
    const bs = num(r.bars_since);
    if (bs != null) tags.push(tag("day " + (bs + 1), "is-day", (bs + 1) + " daily bar(s) since the trigger, counting the trigger bar"));
    if (prov) {
      tags.push(tag("forming bar · unconfirmed", "is-prov",
        "Triggered on today's still-forming daily bar. It is not a trigger until the bar closes: " +
        "a break that closes back inside the base never counts. Not in the IGNITING count."));
    }
    if (r.wide_stop) {
      const w = num(rules && rules.wide_stop_pct);
      tags.push(tag("wide stop", "is-wide",
        "Risk " + fmtPct(r.risk_pct) + " of the entry" +
        (w == null ? "" : " — over the " + fmtPct(w) + " wide-stop flag") +
        ". Flagged, never skipped."));
    }
    if (st === "CLOSED" && r.exit_pending) tags.push(tag("exits next open", "is-pend"));

    const mm = r.mm_passed
      ? kv("Measured move", "passed", "", "The trigger candle already overshot the base's measured move (" +
          fmtPx(r.mm_target) + " sits at or under the entry), so there is no target left above it.")
      : kv("Measured move", fmtPx(r.mm_target) + (num(r.mm_r) == null ? "" : " · " + fmtR(r.mm_r)));
    const hasEntry = num(r.entry) != null;
    const cells = [
      kv("Triggered", r.trigger_date || DASH),
      kv("Trigger close", fmtPx(r.trigger_close)),
      kv("Entry", fmtPx(r.entry), "", entryTip(r)),
      kv("Price", fmtPx(r.price)),
      hasEntry
        ? kv("Since entry", fmtPct(r.change_pct, true), toneOf(r.change_pct), "Today's price against the entry")
        : kv("Since trigger", fmtPct(r.change_pct, true), toneOf(r.change_pct)),
      // On a CLOSED row r_now is today's price against the entry, NOT the
      // trade's result (that is the exit R below) — so it is named for what it is.
      st === "CLOSED"
        ? kv("R if held", fmtR(r.r_now), toneOf(r.r_now),
            "Today's price against the entry and stop, had it not been exited. The trade's result is the exit R.")
        : kv("R now", fmtR(r.r_now), toneOf(r.r_now), "Measured from the entry against the stop"),
      kv("Stop", fmtPx(r.stop)),
      kv("Risk", fmtPct(r.risk_pct), "", "Stop distance as a % of the entry"),
      kv("RVOL", fmtX(r.rvol), "", "Trigger-day volume over its prior 20-day average"),
      kv("Over 9-SMA", fmtPct(r.ext_pct, true), "", "How far the trigger close sat above its 9-SMA"),
      kv("MFE", fmtR(r.mfe_r), "", "Best excursion since the entry, in R"),
      mm,
    ];
    if (st !== "CLOSED" && num(r.trail) != null) {
      cells.push(kv("9-SMA trail", fmtPx(r.trail), "", "The exit line: a daily close under it exits at the next open"));
    }
    let exit = "";
    if (st === "CLOSED") {
      const reason = own(EXIT_TEXT, r.exit_reason) ? EXIT_TEXT[r.exit_reason]
        : String(typeof r.exit_reason === "string" && r.exit_reason ? r.exit_reason : "closed");
      // A gap under the stop is NO TRADE: it never had an R, so the R is a
      // dash even if a stray number rides along, and its price is the open.
      exit = `<div class="ig-exit">` +
        `<span>${esc("Closed · " + reason)}</span>` +
        `<span>${esc(r.exit_date || DASH)}</span>` +
        `<span>${esc((gap ? "opened " : "exit ") + fmtPx(r.exit_price))}</span>` +
        (gap ? `<b>${esc(DASH)}</b>` : `<b class="${esc(toneOf(r.exit_r))}">${esc(fmtR(r.exit_r))}</b>`) +
        (r.exit_pending ? `<span>${esc("(fills at the next open)")}</span>` : "") +
        `</div>`;
    }
    return `<article class="ig-card ig-${esc(st.toLowerCase())}${prov ? " is-prov" : ""}">` +
      cardHead(r, market, tags) +
      `<dl class="ig-grid">${cells.join("")}</dl>` + exit + `</article>`;
  }

  // COILED — a quiet base one bar from a trigger. No plan exists yet, so no
  // stop, no R and no target are shown: only how quiet it is and the level.
  function coiledCardHTML(r, market) {
    const c = obj(r.coil);
    const tags = [];
    if (c.coiled) tags.push(tag("coiled " + fmtN(c.coiled_bars) + " bars", "is-coil"));
    else if (c.last_coiled) tags.push(tag("last coiled " + c.last_coiled, "is-coil"));
    const lvl = num(r.breakout_level), px = num(r.price);
    const gap = lvl != null && px != null && px > 0 ? (lvl / px - 1) * 100 : null;
    const cells = [
      kv("Ribbon", fmtN(c.ribbon_pct, 2) + (num(c.ribbon_pct) == null ? "" : "%"), "",
        "Spread of the 9/26/43/200 SMAs: highest over lowest, minus one"),
      kv("ATR pctl", fmtN(c.atr_pctl, 1), "", "ATR as a % of price, as a percentile of its own history (low = quiet)"),
      kv("Vol pctl", fmtN(c.vol_pctl, 1), "", "20-day average volume as a percentile of its own history (low = quiet)"),
      kv("Drawdown", fmtPct(c.drawdown_pct) + (num(c.drawdown_pct) == null ? "" : " off high")),
      kv("Coiled bars", fmtN(c.coiled_bars)),
      kv("Breakout", fmtPx(lvl), "", "A daily close above this, on enough volume, would be a trigger"),
      kv("Price", fmtPx(px)),
      kv("To breakout", fmtPct(gap, true)),
    ];
    return `<article class="ig-card ig-coiled">` + cardHead(r, market, tags) +
      `<dl class="ig-grid">${cells.join("")}</dl></article>`;
  }

  // "loading" until the fetch settles, then "ok" or "absent".
  function entryStatus(e) {
    if (!e || e.at == null) return "loading";
    return e.data ? "ok" : "absent";
  }

  function fmtP(v) {
    const x = num(v);
    return x == null ? DASH : x.toFixed(3);
  }

  function fmtCI(v) {
    return Array.isArray(v) && v.length === 2 && num(v[0]) != null && num(v[1]) != null
      ? signed(v[0], 2) + ".." + signed(v[1], 2) : DASH;
  }

  // The evidence line. Every number is read off the backtest file; a field
  // it does not carry is a dash. Nothing here computes a statistic — not the
  // CI, not the P, not a difference. Schema 1 files (no `versus`, no
  // `scoring`, no `open`) still render, with dashes where the new fields go.
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

  // "Bars: Binance 117 · Yahoo 36 · …" for the header tooltip, read off
  // summary.sources. Empty when the payload predates it.
  function sourcesText(src) {
    const by = obj(src.by_source);
    const parts = Object.keys(by).filter((k) => num(by[k]) != null)
      .map((k) => (own(SOURCE_LABEL, k) ? SOURCE_LABEL[k] : k) + " " + by[k]);
    const dead = obj(src.dead);
    const deadTxt = Object.keys(dead).map((k) => k + " (" + String(dead[k]) + ")");
    const rej = obj(src.identity_rejected);
    const nRej = Object.keys(rej).length;
    return (parts.length ? " · bars: " + parts.join(" · ") : "") +
      (deadTxt.length ? " · unreachable from the runner: " + deadTxt.join(", ") : "") +
      (nRej ? " · " + nRej + " same-ticker listing(s) rejected as a different coin" : "");
  }

  // The market's benchmark against its 200-SMA — CONTEXT, never a filter
  // (the engine gates on nothing here). Crypto's block carries btc_* keys;
  // a stock market's the generic ones (label "ASX 200", above_200, ...).
  // Absent when the payload carries no regime block.
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

  // "N coins behind yesterday's close" when summary.bars says some SCREENED
  // coins' source had not served that bar when the screen ran (the engine
  // counts only frames it screens; one too old to screen is its own skip).
  // Context, not an alarm: Yahoo-fallback coins routinely land a day late.
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

  function sectionHTML(cls, label, note, rows, cardFn) {
    return `<section class="ig-sec ${esc(cls)}">` +
      `<h4 class="ig-h">${esc(label)} <b>${esc(rows.length)}</b>` +
      (note ? ` <span class="ig-note">${esc(note)}</span>` : "") + `</h4>` +
      `<div class="ig-cards">${rows.map(cardFn).join("")}</div></section>`;
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
      ? `<div class="ig-cards">${conf.map(trig).join("")}</div>`
      : `<p class="ig-empty">${esc(prov.length ? "Nothing confirmed on the last completed daily bar."
          : "Nothing igniting on the last completed daily bar.")}</p>`;
    if (prov.length) {
      h += `<p class="ig-subh">${esc("Forming bar · unconfirmed · not in the count")}</p>` +
        `<div class="ig-cards ig-cards-prov">${prov.map(trig).join("")}</div>`;
    }
    return h + `</section>`;
  }

  // The whole panel, as one string. `coiledOpen` carries the COILED
  // disclosure's state across a repaint (the backtest landing, a refresh).
  function panelHTML(payload, btStatus, bt, market, coiledOpen, stale) {
    const g = groupRows(payload && payload.results);
    const k = countsOf(payload);
    const rules = (payload && payload.rules) || {};
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
        `<div class="ig-cards">${g.COILED.map((r) => coiledCardHTML(r, market)).join("")}</div></details>`;
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
