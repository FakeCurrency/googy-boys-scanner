/* ⚡ IGNITION — the coil -> ignition deck pill + panel (2026-09-28). REPORT-ONLY.

   The owner's "QNT-type" crypto play: a coin that goes quiet for months (the
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
     * app.js only PLACES the pill (after "At level") and calls in here. Every
       rule — which markets, what the count means, when the pill shows, what
       the panel says — lives in this file so test/ignition.test.js can slice
       the shipped functions and run them for real.

   THE THREE RULES THE TESTS PIN.
     1. The pill's number is `summary.counts.igniting_confirmed`: triggers on a
        COMPLETED daily bar. A break on today's still-forming bar is not a
        trigger until the bar closes (a poke above the base that closes back
        inside it never counts), so it is a separate "+p" marker, never part
        of N. The pill still shows when N is 0 but rows exist, so the coiled
        watchlist is one tap away on a quiet day.
     2. CLOSED rows are shown ON PURPOSE. A list of only the survivors is the
        survivorship bias this lens exists to stop fooling us with.
     3. Absent data hides silently. The live file is fetched lazily, only on
        an Ignition market; the backtest only when the panel opens. The
        `.catch()` is scoped to the FETCH AND THE PARSE (HANDOFF 17.6, TOP100
        #88): a missing file is "nothing to show", while a fault in anything
        that renders is re-raised asynchronously to window.onerror instead of
        disguising itself as a missing file for weeks. */
(() => {
  "use strict";

  // Mirrored from scanner/config.py IGNITION_MARKETS and pinned to it by
  // tests/test_ignition_frontend.py: a market the engine starts screening
  // cannot stay invisible here, and a pill can never appear for a market the
  // engine does not screen (which would only ever fetch a 404).
  const IGNITION_MARKETS = ["crypto"];

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const DASH = "—";
  // The deck auto-refreshes every 5 minutes; the live file is re-read on the
  // same cadence (the engine publishes a handful of times a day).
  const LIVE_TTL_MS = 5 * 60 * 1000;
  // Page order, mirroring scanner/ignition/engine.py state_rank.
  const STATE_ORDER = { IGNITING: 0, RUNNING: 1, CLOSED: 2, COILED: 3 };
  const EXIT_TEXT = { trail: "closed under the 9-SMA", stop: "stop hit" };
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

  function fmtPx(v) {
    const x = num(v);
    if (x == null) return DASH;
    const a = Math.abs(x);
    if (a >= 1000) return "$" + x.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (a >= 1) return "$" + x.toFixed(2);
    if (a === 0) return "$0";
    return "$" + String(Number(x.toPrecision(4)));   // sub-dollar coins keep 4 significant figures
  }

  function fmtPct(v, signed) {
    const x = num(v);
    if (x == null) return DASH;
    return (signed && x > 0 ? "+" : "") + x.toFixed(1) + "%";
  }

  function fmtR(v) {
    const x = num(v);
    if (x == null) return DASH;
    return (x > 0 ? "+" : "") + x.toFixed(2) + "R";
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

  // Sort key for one row, or null for a state this page does not know (a
  // future engine state is dropped, never mis-filed into a known section).
  function rowRank(r) {
    const st = r && typeof r === "object" ? STATE_ORDER[r.state] : undefined;
    if (st == null) return null;
    if (st < 3) {
      const bs = num(r.bars_since);
      return [st, r.provisional ? 1 : 0, bs == null ? 99 : bs, -(num(r.rvol) || 0)];
    }
    const c = (r.coil && typeof r.coil === "object") ? r.coil : {};
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

  // What the deck pill shows, or null for "no pill". `mark` is finished,
  // escaped HTML for app.js's pill() helper to append after the count.
  function pillInfo(payload, open) {
    if (!payload || typeof payload !== "object" || !Array.isArray(payload.results)) return null;
    const k = countsOf(payload);
    if (!(k.confirmed > 0 || k.rows > 0)) return null;
    const title = "IGNITION — report-only, not traded by the bot. " +
      k.confirmed + " confirmed ignition(s) on the last completed daily bar: a coin " +
      "closing out of a months-long quiet base on a multiple of its normal volume. " +
      "Also on the panel: " + k.running + " running, " + k.closed + " closed, " +
      k.coiled + " coiled. Click to " + (open ? "close" : "open") + " the panel.";
    const mark = k.provisional
      ? `<span class="ig-pmark" title="${esc(k.provisional + " more on the forming bar, unconfirmed: " +
          "today's daily bar has not closed, and a break that closes back inside its base never " +
          "counts. Not included in the number.")}">+p</span>`
      : "";
    return { n: k.confirmed, provisional: k.provisional, title, mark, open: !!open };
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

  function chartHref(market, sym) {
    return "chart.html?m=" + encodeURIComponent(market) + "&s=" + encodeURIComponent(sym);
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

  function cardHead(r, market, tags) {
    const sym = String(r.symbol == null ? "" : r.symbol);
    return `<div class="ig-card-head">` +
      `<a class="ig-sym" href="${esc(chartHref(market, sym))}" title="${esc("Open the " + sym + " chart")}">${esc(sym || DASH)}</a>` +
      (r.name ? `<span class="ig-name">${esc(r.name)}</span>` : "") +
      (tags.length ? `<span class="ig-tags">${tags.join("")}</span>` : "") +
      `</div>`;
  }

  // IGNITING / RUNNING / CLOSED — one trigger, and what the exit rule has
  // done with it since.
  function triggerCardHTML(r, market, rules) {
    const st = String(r.state == null ? "" : r.state);
    const prov = !!r.provisional;
    const tags = [];
    const bs = num(r.bars_since);
    if (bs != null) tags.push(tag("day " + (bs + 1), "is-day", (bs + 1) + " daily bar(s) since the trigger, counting the trigger bar"));
    if (prov) {
      tags.push(tag("forming bar · unconfirmed", "is-prov",
        "Triggered on today's still-forming daily bar. It is not a trigger until the bar closes: " +
        "a break that closes back inside the base never counts."));
    }
    if (r.wide_stop) {
      const w = num(rules && rules.wide_stop_pct);
      tags.push(tag("wide stop", "is-wide",
        "Risk " + fmtPct(r.risk_pct) + " of the trigger close" +
        (w == null ? "" : " — over the " + fmtPct(w) + " wide-stop flag") +
        ". Flagged, never skipped."));
    }
    if (st === "CLOSED" && r.exit_pending) tags.push(tag("exits next open", "is-pend"));

    const mm = r.mm_passed
      ? kv("Measured move", "passed", "", "The trigger candle already overshot the base's measured move (" +
          fmtPx(r.mm_target) + " sits at or under the trigger close), so there is no target left above it.")
      : kv("Measured move", fmtPx(r.mm_target) + (num(r.mm_r) == null ? "" : " · " + fmtR(r.mm_r)));
    const cells = [
      kv("Triggered", r.trigger_date || DASH),
      kv("Trigger close", fmtPx(r.trigger_close)),
      kv("Price", fmtPx(r.price)),
      kv("Since trigger", fmtPct(r.change_pct, true), toneOf(r.change_pct)),
      // On a CLOSED row r_now is today's price against the trigger, NOT the
      // trade's result (that is the exit R below) — so it is named for what it is.
      st === "CLOSED"
        ? kv("R if held", fmtR(r.r_now), toneOf(r.r_now), "Today's price against the trigger close and stop, had it not been exited. The trade's result is the exit R.")
        : kv("R now", fmtR(r.r_now), toneOf(r.r_now), "Measured from the trigger close against its stop"),
      kv("Stop", fmtPx(r.stop)),
      kv("Risk", fmtPct(r.risk_pct), "", "Stop distance as a % of the trigger close"),
      kv("RVOL", fmtX(r.rvol), "", "Trigger-day volume over its prior 20-day average"),
      kv("Over 9-SMA", fmtPct(r.ext_pct, true), "", "How far the trigger close sat above its 9-SMA"),
      kv("MFE", fmtR(r.mfe_r), "", "Best close-to-high excursion since the trigger, in R"),
      mm,
    ];
    if (st !== "CLOSED" && num(r.trail) != null) {
      cells.push(kv("9-SMA trail", fmtPx(r.trail), "", "The exit line: a daily close under it exits at the next open"));
    }
    let exit = "";
    if (st === "CLOSED") {
      const reason = EXIT_TEXT[r.exit_reason] || String(r.exit_reason || "closed");
      exit = `<div class="ig-exit">` +
        `<span>${esc("Closed · " + reason)}</span>` +
        `<span>${esc(r.exit_date || DASH)}</span>` +
        `<span>${esc("exit " + fmtPx(r.exit_price))}</span>` +
        `<b class="${esc(toneOf(r.exit_r))}">${esc(fmtR(r.exit_r))}</b>` +
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
    const c = (r.coil && typeof r.coil === "object") ? r.coil : {};
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

  // The evidence line. Every number is read off the backtest file; a field
  // it does not carry is a dash. Nothing here computes a statistic.
  function evidenceHTML(status, bt, live) {
    if (status === "loading") return `<div class="ig-ev is-pending">${esc("Backtest loading…")}</div>`;
    if (status !== "ok" || !bt || typeof bt !== "object") {
      return `<div class="ig-ev is-pending">${esc("Backtest pending")}</div>`;
    }
    const p = (bt.primary && typeof bt.primary === "object") ? bt.primary : {};
    const split = (p.by_split && typeof p.by_split === "object") ? p.by_split : {};
    const oos = (split.out_of_sample && typeof split.out_of_sample === "object") ? split.out_of_sample : {};
    const base = (bt.baselines && typeof bt.baselines === "object") ? bt.baselines : {};
    const rnd = (base.random_timing && typeof base.random_timing === "object") ? base.random_timing : {};
    const pf = num(p.pf);
    const items = [
      ["trades", fmtN(p.n)],
      ["expectancy", fmtR(p.exp_r)],
      ["median", fmtR(p.median_r)],
      ["PF", pf == null ? DASH : pf.toFixed(2)],
      ["out-of-sample exp", fmtR(oos.exp_r)],
      ["random-timing exp", fmtR(rnd.exp_r)],
      ["top-5 share", fmtPct(p.top5_share_pct)],
    ];
    const range = Array.isArray(bt.date_range) && bt.date_range.length === 2
      ? bt.date_range[0] + " → " + bt.date_range[1] : "";
    const tip = "Walk-forward replay, pre-registered before it ran" +
      (bt.ruleset_version ? " · ruleset " + bt.ruleset_version : "") +
      (range ? " · " + range : "") +
      (bt.generated_at ? " · run " + utcText(bt.generated_at) : "") +
      ". Per-trade R, not a portfolio.";
    const caveats = Array.isArray(bt.caveats) && bt.caveats.length
      ? bt.caveats.map((x) => String(x == null ? "" : x)).join("\n\n") : CAVEAT_FALLBACK;
    const drift = live && live.ruleset_version && bt.ruleset_version &&
      String(live.ruleset_version) !== String(bt.ruleset_version)
      ? `<span class="ig-ev-warn">${esc("backtest ruleset " + bt.ruleset_version + " ≠ live " + live.ruleset_version)}</span>`
      : "";
    return `<div class="ig-ev"><span class="ig-ev-k" title="${esc(tip)}">${esc("Backtest")}</span>` +
      items.map(([k, v]) => `<span class="ig-ev-i">${esc(k)} <b>${esc(v)}</b></span>`).join("") +
      `<span class="ig-ev-cav" title="${esc(caveats)}">${esc("⚠ survivor-biased universe")}</span>` +
      drift + `</div>`;
  }

  function headHTML(payload) {
    const gen = payload && payload.generated_at;
    const tip = "Market-local/UTC: " + (utcText(gen) || DASH) +
      (payload && payload.last_closed_bar ? " · last completed daily bar " + payload.last_closed_bar : "") +
      (payload && payload.ruleset_version ? " · ruleset " + payload.ruleset_version : "");
    return `<div class="ig-head">` +
      `<div class="ig-title">${esc("⚡ IGNITION · coil → ignition")}</div>` +
      `<div class="ig-sub" title="${esc(tip)}">${esc("Report-only · not traded by the bot · daily bars · updated " +
        (gen ? melb(gen) : DASH))}</div>` +
      `</div>`;
  }

  function sectionHTML(cls, label, note, rows, cardFn) {
    return `<section class="ig-sec ${esc(cls)}">` +
      `<h4 class="ig-h">${esc(label)} <b>${esc(rows.length)}</b>` +
      (note ? ` <span class="ig-note">${esc(note)}</span>` : "") + `</h4>` +
      `<div class="ig-cards">${rows.map(cardFn).join("")}</div></section>`;
  }

  // The whole panel, as one string. `coiledOpen` carries the COILED
  // disclosure's state across a repaint (the backtest landing, a refresh).
  function panelHTML(payload, btStatus, bt, market, coiledOpen) {
    const g = groupRows(payload && payload.results);
    const rules = (payload && payload.rules) || {};
    const trig = (r) => triggerCardHTML(r, market, rules);
    let h = headHTML(payload) + evidenceHTML(btStatus, bt, payload);
    h += g.IGNITING.length
      ? sectionHTML("ig-sec-igniting", "Igniting", "confirmed first", g.IGNITING, trig)
      : `<section class="ig-sec ig-sec-igniting"><h4 class="ig-h">${esc("Igniting")} <b>0</b></h4>` +
        `<p class="ig-empty">${esc("Nothing igniting on the last completed daily bar.")}</p></section>`;
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
        // "updated" stamp says how old it is); a first failure hides.
        if (d || e.data == null) e.data = d;
        e.at = Date.now();
        e.inflight = false;
        const cb = e.onReady;
        e.onReady = null;
        if (cb) { try { cb(market); } catch (err) { report(err); } }
      });
    return e;
  }

  // Called by app.js's renderDeckPills. Returns pillInfo() for a market whose
  // file has loaded, else null — and starts the lazy load, calling `onReady`
  // (the deck's re-render) once it settles.
  function pill(market, onReady) {
    if (!isMarket(market)) return null;
    const e = load(live, market, liveUrl(market), LIVE_TTL_MS, onReady);
    return pillInfo(e.data, openFor === market);
  }

  function toggle(market) {
    if (!isMarket(market)) return false;
    openFor = openFor === market ? null : market;
    return openFor === market;
  }

  // Show / hide / repaint #ignition-panel for the market the deck is on.
  function sync(market) {
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
    const key = market + "|" + e.at + "|" + status + "|" + b.at;
    if (key === painted && !host.hidden) return;
    const det = host.querySelector ? host.querySelector("details.ig-coiled") : null;
    let html;
    try {
      html = panelHTML(e.data, status, b.data, market, !!(det && det.open));
    } catch (err) {
      host.hidden = true;
      host.innerHTML = "";
      painted = "";
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
