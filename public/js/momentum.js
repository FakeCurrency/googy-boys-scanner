/* VIVEK MOMENTUM — the divergence lens. REPORT-ONLY.
 *
 * Reads ONE published file per market, `data/momentum/<market>.json`, and
 * renders it. It writes nothing, posts nothing, and knows nothing about the
 * paper book, the confluence machinery or the HIGH CONVICTION rule — the
 * fences in tests/test_momentum_fences.py exist to keep that true.
 *
 * TWO THINGS ON THIS PAGE ARE NOT COSMETIC:
 *
 * 1. EVERY ROW SHOWS TWO AGES FOR RULE A. `bars_ago` is when the scanner could
 *    KNOW; `pivot_bars_ago` is the bar the TradingView label sits on, always
 *    exactly five more. Rule B has no lag at all. Show only one and the owner
 *    opens a chart, sees the label on a different bar from the date we named,
 *    and stops trusting the page.
 * 2. A CONFLICT IS SHOWN, NOT RESOLVED. A bullish divergence beside a bearish
 *    cross is the interesting case — momentum turning up while trend structure
 *    turns down — so it gets its own chip rather than being collapsed to a
 *    direction by a priority rule.
 *
 * The page degrades to an honest sentence when a market has never run: a 404
 * means "no scan yet", anything else means the connection or the CDN, and
 * those want different words. The catch is scoped to the FETCH AND PARSE only,
 * with the renderer after it — a renderer bug that fell into the same catch
 * would be indistinguishable from "the data isn't there yet", which is how a
 * broken panel stays invisible for weeks.
 */
(() => {
  "use strict";

  const esc = PM.esc;                       // one escaper, shared, null-safe
  const { fmtPrice, fmtTurnover, fmtMelb, loadFailKind, retryHTML,
          fetchTimeout } = PM;

  const MARKETS = ["asx", "nasdaq", "crypto"];
  const FILTERS = [
    ["all", "ALL", "every hit this mode published"],
    ["a", "RULE A", "RSI divergence off a strict pivot"],
    ["b", "RULE B", "a scored 20/50 cross"],
    ["bull", "BULL", "bullish direction"],
    ["bear", "BEAR", "bearish direction"],
  ];
  // Mode A lists Rule A only, so a RULE A pill always equals ALL and a RULE B
  // pill is always 0: the page read as if crosses were screened when they are
  // not (REFINE200 #183). Those two pills show in modes B and C only.
  const RULE_PILLS = ["a", "b"];
  // A stock market publishes once per weekday after its close; past this many
  // WEEKDAY hours since the last run it has missed a close. Crypto publishes
  // daily: past this many calendar hours it has missed a day (its Sunday and
  // Monday runs land a few hours late, so a day plus that slack).
  const STALE_WEEKDAY_H = 30;
  const STALE_CRYPTO_H = 30;
  const BAR_24_7 = ["crypto"];
  const LONG_SHORT = { bull: "long", bear: "short" };

  const state = { market: "asx", filter: "all", data: null, err: null, loading: true,
                  bt: {} };   // {market: backtest payload | null}, loaded lazily

  const $ = (id) => document.getElementById(id);

  /* ---- data ------------------------------------------------------------ */

  function marketFromUrl() {
    const m = new URLSearchParams(location.search).get("m");
    return MARKETS.includes(m) ? m : "asx";
  }

  async function load(market) {
    state.loading = true;
    state.err = null;
    render();
    loadBacktest(market);   // rides beside the screen, never gates it
    let payload = null;
    try {
      // Scoped to the fetch and the parse. The renderer runs AFTER, outside.
      const res = await fetchTimeout(`data/momentum/${market}.json`,
                                     { cache: "no-cache" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      payload = await res.json();
    } catch (err) {
      // A slow failure for the PREVIOUS market must not wipe the rows the
      // current one already loaded (REFINE200 #175): same guard as success.
      if (market !== state.market) return;
      state.err = err;
      state.data = null;
      state.loading = false;
      render();
      return;
    }
    // A market switch can land while an older fetch is still in flight. Apply
    // nothing if the answer changed underneath us, or ASX rows appear under
    // the NASDAQ heading — a page that is not merely stale but wrong about
    // which market it is showing, with nothing on screen saying so.
    if (market !== state.market) return;
    state.data = payload;
    state.loading = false;
    render();
  }

  // The market's replay, if one is published (only some markets have one).
  // Absent or broken reads as "no evidence", never as an error on the page.
  async function loadBacktest(market) {
    if (Object.prototype.hasOwnProperty.call(state.bt, market)) return;
    state.bt[market] = null;
    try {
      const res = await fetchTimeout(`data/momentum/${market}_backtest.json`, { cache: "no-cache" });
      if (!res.ok) return;
      state.bt[market] = await res.json();
    } catch (_) { return; }
    if (market === state.market && state.data) render();
  }

  /* ---- derived --------------------------------------------------------- */

  function rows() {
    const all = (state.data && state.data.results) || [];
    switch (state.filter) {
      case "a": return all.filter((r) => r.rule_a);
      case "b": return all.filter((r) => r.rule_b);
      case "bull": return all.filter((r) => dirOf(r) === "bull");
      case "bear": return all.filter((r) => dirOf(r) === "bear");
      default: return all;
    }
  }

  function dirOf(r) {
    const d = String(r.direction || "");
    if (d === "bull" || d === "bear") return d;
    return "";                                // "conflict", "both" or nothing
  }

  function counts() {
    const all = (state.data && state.data.results) || [];
    return {
      all: all.length,
      a: all.filter((r) => r.rule_a).length,
      b: all.filter((r) => r.rule_b).length,
      bull: all.filter((r) => dirOf(r) === "bull").length,
      bear: all.filter((r) => dirOf(r) === "bear").length,
    };
  }

  // A local spark, deliberately NOT imported from app.js: that file is the 5.0
  // deck's and this page must not take a runtime dependency on it. Unused while
  // the payload carries no series -- present so the slot works the day it does.
  function spark(vals, w, h, color) {
    if (!vals || vals.length < 2) return "";
    const min = Math.min(...vals), max = Math.max(...vals), rng = (max - min) || 1;
    const step = w / (vals.length - 1);
    const pts = vals.map((v, i) =>
      `${(i * step).toFixed(1)},${(h - ((v - min) / rng) * h).toFixed(1)}`).join(" ");
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">` +
      `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5" ` +
      `stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  }

  /* ---- staleness and evidence (read off the files, never computed) ------ */

  // Hours between two instants (ms) that fall on a UTC weekday.
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

  // null when fresh, else one sentence saying why not. A stock market is
  // stale past STALE_WEEKDAY_H weekday hours since its last run (a weekend
  // never counts); crypto past STALE_CRYPTO_H hours. An unreadable run time is
  // never fresh. `now` is a parameter so the rule is testable.
  function staleOf(data, market, now) {
    if (!data || typeof data !== "object") return null;
    const gen = Date.parse(data.generated_at);
    if (!isFinite(gen)) return "the file carries no readable run time";
    const is247 = BAR_24_7.includes(String(market || "").toLowerCase());
    const h = is247 ? (now - gen) / 3600000 : weekdayHours(gen, now);
    const limit = is247 ? STALE_CRYPTO_H : STALE_WEEKDAY_H;
    if (h <= limit) return null;
    return `last run ${fmtMelb(data.generated_at)}, over ${limit}` +
      `${is247 ? "" : " weekday"} hours ago`;
  }

  // The replay stream a row of this direction belongs to, by the payload's
  // mode: mode A lists Rule A hits only, so its rows are Rule A's stream.
  function btStream(bt, mode, dir) {
    const side = LONG_SHORT[dir];
    const s = bt && bt.summary;
    if (!side || !s || typeof s !== "object") return null;
    const key = String(mode || "A") === "A" ? `rule_a_${side}` : side;
    const st = s[key];
    return st && typeof st === "object" ? { key, st } : null;
  }

  // "no edge in the ASX backtest" when the market's OWN replay scores this
  // direction at or below zero R a trade (REFINE200 #50: ASX shorts -0.10R
  // over 2,235 Rule A trades). Threshold logic on a published number only.
  function noEdgeOf(bt, mode, dir, market) {
    const got = btStream(bt, mode, dir);
    if (!got) return null;
    const exp = got.st.expectancy_r, n = got.st.trades;
    if (typeof exp !== "number" || !isFinite(exp) || exp > 0) return null;
    if (typeof n !== "number" || !(n > 0)) return null;
    const mk = String(market || "").toUpperCase();
    const label = `no edge in the ${mk} backtest`;
    const what = got.key.startsWith("rule_a") ? `Rule A ${LONG_SHORT[dir]}s` : `${LONG_SHORT[dir]}s`;
    const tip = `The ${mk} replay (${bt.period || "5y"}, run ${String(bt.generated_at || "").slice(0, 10)}) ` +
      `scores ${what} at ${exp >= 0 ? "+" : ""}${exp}R a trade over ${n.toLocaleString("en-AU")} ` +
      `trades: no edge. Report only — shown, not filtered.`;
    return { label, tip };
  }

  /* ---- chrome ---------------------------------------------------------- */

  // COVERAGE, in counts and never as a percentage. The first scheduled ASX
  // file screened 1,165 of 2,047 names -- Yahoo returned nothing for 882 and
  // the frame cache was cold, so nothing filled the gap -- while the header
  // said "298 scanned · 867 gated", which reads as the whole market. `line`
  // puts the denominator in the header; `note` is one sentence, only when
  // names are missing; `partial` turns the dot amber. A summary without a
  // universe count shows the download count alone rather than a guessed ratio.
  function coverage(s) {
    const n = (v) => (typeof v === "number" && isFinite(v) ? v : null);
    const fmt = (v) => v.toLocaleString("en-AU");
    const got = n(s && s.downloaded);
    const all = n(s && s.universe);
    if (got == null) return { line: null, note: "", partial: false };
    if (all == null) return { line: `${fmt(got)} downloaded`, note: "", partial: false };
    const line = `${fmt(got)} of ${fmt(all)} downloaded`;
    const missing = all - got;
    if (missing <= 0) return { line, note: "", partial: false };
    const reused = n(s.cache && s.cache.reused);
    const why = reused === 0
      ? "and the frame cache was cold (0 reused), so there was no earlier copy to fall back on"
      : reused == null ? "and the file does not say whether the frame cache filled any"
        : `even after ${fmt(reused)} were filled from the frame cache`;
    const note = `${fmt(missing)} of ${fmt(all)} names returned no daily bars ${why}` +
      ` — this screen covers ${fmt(got)} names, not the whole market.`;
    return { line, note, partial: true };
  }

  function renderHead() {
    const s = (state.data && state.data.summary) || {};
    const title = $("mo-title");
    const sub = $("mo-sub");
    const dot = $("mo-dot");
    const cover = $("mo-cover");
    if (state.loading) {
      title.textContent = "MOMENTUM · loading…";
      dot.className = "deck-dot";
      return;
    }
    if (!state.data) {
      title.textContent = "MOMENTUM · no data";
      dot.className = "deck-dot is-stale warn";
      sub.textContent = "RSI divergence screen · report only";
      if (cover) { cover.textContent = ""; cover.hidden = true; }
      return;
    }
    const n = ((state.data.results) || []).length;
    title.textContent = `MOMENTUM · ${n} ${n === 1 ? "name" : "names"}`;
    const cov = coverage(s);
    const stale = staleOf(state.data, state.market, Date.now());
    dot.className = stale ? "deck-dot is-stale warn"
      : (cov.partial ? "deck-dot is-partial warn" : "deck-dot is-fresh");
    const mode = String(state.data.mode || "A");
    const win = (state.data.params && state.data.params.div_fresh_bars) || 1;
    const bits = [
      ...(stale ? [`⚠ STALE: ${stale}`] : []),
      mode === "A" ? "mode A: divergence only" : `mode ${mode}`,
      `${win}-bar window`,
      ...(cov.line ? [cov.line] : []),
      `${s.scanned == null ? "?" : s.scanned} scanned`,
      `${s.skipped_gates == null ? "?" : s.skipped_gates} gated`,
    ];
    if (cover) { cover.textContent = cov.note; cover.hidden = !cov.note; }
    if (s.errors) bits.push(`${s.errors} errored`);
    // The last CLOSED bar, visible rather than hidden in a title attribute:
    // it is the date every number on this page was measured on.
    if (state.data.last_closed_bar) bits.push(`last bar ${state.data.last_closed_bar}`);
    sub.textContent = bits.join(" · ");
    const stamp = $("mo-stamp");
    stamp.textContent = state.data.generated_at
      ? `scanned ${fmtMelb(state.data.generated_at)}` : "";
    stamp.title = state.data.last_closed_bar
      ? `last closed bar ${state.data.last_closed_bar}` : "";
  }

  // The deck's own pill (app.js renderDeckPills): .fpill, count in <b>, and
  // aria-pressed so the on/off state reaches assistive tech, not just colour.
  // It used to render .deck-pill / .deck-pill-n, which no stylesheet defines:
  // browser-default grey buttons reading "ALL4", "RULE A4".
  function renderPills() {
    const c = counts();
    const mode = String((state.data && state.data.mode) || "A");
    const bt = (state.bt || {})[state.market];
    $("mo-pills").innerHTML = FILTERS.filter(([key]) => mode !== "A" || !RULE_PILLS.includes(key))
      .map(([key, label, why]) => {
        const on = state.filter === key;
        const ne = noEdgeOf(bt, mode, key, state.market);
        return `<button class="fpill${on ? " is-active" : ""}" data-pill="${esc(key)}" ` +
          `aria-pressed="${on ? "true" : "false"}" title="${esc(ne ? why + " — " + ne.tip : why)}">` +
          `${esc(label)} <b>${c[key]}</b>` +
          (ne ? ` <span class="mo-noedge">${esc("no edge")}</span>` : "") + `</button>`;
      }).join("");
  }

  function renderMarkets() {
    document.querySelectorAll("#mo-market .market-btn").forEach((b) => {
      const on = b.dataset.market === state.market;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
  }

  /* ---- rows ------------------------------------------------------------ */

  function rulesBadge(r) {
    if (r.rule_a && r.rule_b) return "A+B";
    return r.rule_a ? "A" : (r.rule_b ? "B" : "—");
  }

  function chip(text, cls, title) {
    return `<span class="mo-chip${cls ? " " + cls : ""}"` +
      (title ? ` title="${esc(title)}"` : "") + `>${esc(text)}</span>`;
  }

  function rowHTML(r) {
    const dir = dirOf(r);
    const conflict = String(r.direction || "") === "conflict";
    const chips = [];

    if (r.rule_a) {
      // BOTH ages, always. See the header note.
      chips.push(chip(
        `A ${r.rule_a_direction || "?"} · knew ${r.rule_a_bars_ago}b`,
        "mo-chip-a",
        `Divergence confirmed ${r.rule_a_bars_ago} bar(s) ago; the pivot it ` +
        `describes — where TradingView draws the label — is ` +
        `${r.rule_a_pivot_bars_ago} bar(s) ago` +
        (r.rule_a_pivot_bar ? ` (${String(r.rule_a_pivot_bar).slice(0, 10)})` : "")));
      chips.push(chip(`label ${r.rule_a_pivot_bars_ago}b back`, "mo-chip-lag",
        "Rule A carries a 5-bar detection lag: you cannot know a bar was a " +
        "local low until you have seen the bars after it."));
    }
    if (r.rule_b) {
      chips.push(chip(
        `B ${r.rule_b_direction || "?"} ${r.rule_b_score != null ? "+" + r.rule_b_score : ""}`
          .trim(),
        "mo-chip-b",
        `${r.rule_b_label || "scored cross"} — printed ${r.rule_b_bars_ago} ` +
        "bar(s) ago. Rule B has no detection lag."));
    }
    if (conflict) {
      chips.push(chip("CONFLICT", "mo-chip-conflict",
        "The two rules disagree on direction — momentum turning one way while " +
        "trend structure turns the other. Shown, not resolved."));
    }
    if (r.slow_ready === false) {
      chips.push(chip("NO 200", "mo-chip-warn",
        "Fewer bars than the slow moving average needs, so the " +
        "price-beyond-200 point cannot be awarded and the score is capped at 2."));
    }
    if (r.is_product) {
      chips.push(chip("PRODUCT", "mo-chip-warn",
        "A fund, REIT, LIC, preferred line or warrant rather than an " +
        "operating company."));
    }
    // A row screened on an older bar than the file's newest (its source had
    // not served the latest close yet) says so (REFINE200 #174).
    const lastDay = String(r.last_bar || "").slice(0, 10);
    const fileDay = String((state.data && state.data.last_closed_bar) || "").slice(0, 10);
    if (lastDay && fileDay && lastDay < fileDay) {
      chips.push(chip(`as of ${lastDay}`, "mo-chip-warn",
        `Screened on its ${lastDay} bar: its source had not served the ${fileDay} ` +
        "close when this ran, so this signal is a session older than the rest."));
    }
    const ne = noEdgeOf((state.bt || {})[state.market], state.data && state.data.mode, dir, state.market);
    if (ne) chips.push(chip(ne.label, "mo-chip-noedge", ne.tip));

    const cls = ["mo-row"];
    if (dir) cls.push("is-" + dir);
    if (conflict) cls.push("is-conflict");
    const href = `chart.html?s=${encodeURIComponent(r.symbol || "")}` +
      `&amp;m=${encodeURIComponent(state.market)}&amp;src=momentum`;
    // Only a series the SCANNER published is a spark. Nothing here reaches for
    // another payload to draw one -- test-pinned.
    const sparkVals = Array.isArray(r.spark) && r.spark.length > 1 ? r.spark : null;

    return `<article class="${cls.join(" ")}">` +
      `<div class="mo-rail" aria-hidden="true"></div>` +
      `<div class="mo-badge" title="Which rules fired">${esc(rulesBadge(r))}</div>` +
      `<div class="mo-main">` +
        `<div class="mo-head">` +
          `<a class="mo-sym" href="${href}">${esc(r.symbol)}</a>` +
          `<span class="mo-name">${esc(r.name || "")}</span>` +
        `</div>` +
        `<div class="mo-chips">${chips.join("")}</div>` +
      `</div>` +
      `<div class="mo-right">` +
        // THE SPARK SLOT IS RESERVED AND EMPTY, ON PURPOSE. The payload carries
        // `close` and `n_bars` but no price SERIES, and the three ways to get
        // one are each worse than a blank: read another lens's payload, fetch
        // per-row history (ASX-only, one request per card), or draw something
        // that is not the price. The box is held so the card height matches the
        // 5.0 deck and the absence is stated rather than filled. If the scanner
        // ever publishes `spark`, this is where it goes.
        `<a class="mo-spark${sparkVals ? "" : " is-empty"}" href="${href}" ` +
          `title="${sparkVals ? "Open chart" : "No price series in this payload — open the chart for one"}">` +
          `${sparkVals ? spark(sparkVals, 64, 28, dir === "bear" ? "var(--red)" : "var(--green)") : `<span class="mo-nospark">no spark</span>`}` +
        `</a>` +
        `<div class="mo-pricewrap">` +
          `<div class="mo-price">${esc(fmtPrice(r.close))}</div>` +
          `<div class="mo-meta">RSI ${r.rsi == null ? "—" : Math.round(r.rsi)}` +
          ` · ${esc(fmtTurnover(r.dollar_adv_20))}</div>` +
        `</div>` +
      `</div>` +
    `</article>`;
  }

  function emptyHTML() {
    if (state.loading) return `<p class="mo-empty">Loading…</p>`;
    if (state.err) {
      const kind = loadFailKind(state.err);
      if (kind === "missing") {
        return `<p class="mo-empty">No ${esc(state.market.toUpperCase())} ` +
          `momentum scan yet. This lens publishes after each market's close.</p>`;
      }
      return `<p class="mo-empty">Could not load the ${esc(state.market.toUpperCase())}` +
        ` scan — this looks like a connection problem rather than missing data.` +
        `</p><p class="mo-empty">${retryHTML("mo-retry")}</p>`;
    }
    const total = ((state.data && state.data.results) || []).length;
    if (!total) {
      return `<p class="mo-empty">Nothing fired on ` +
        `${esc(state.market.toUpperCase())} in this window. ` +
        `On a 1-bar window that is an ordinary day, not a fault.</p>`;
    }
    return `<p class="mo-empty">No name matches this filter.</p>`;
  }

  function render() {
    renderHead();
    renderMarkets();
    renderPills();
    const list = $("mo-list");
    const rs = rows();
    list.innerHTML = rs.length ? rs.map(rowHTML).join("") : emptyHTML();
    const retry = $("mo-retry");
    // Wired here rather than with an onclick attribute, which would be an
    // eval sink.
    if (retry) retry.addEventListener("click", () => load(state.market));
  }

  /* ---- wiring ---------------------------------------------------------- */

  function init() {
    state.market = marketFromUrl();
    document.getElementById("mo-market").addEventListener("click", (e) => {
      const b = e.target.closest(".market-btn");
      if (!b || b.dataset.market === state.market) return;
      state.market = b.dataset.market;
      const u = new URL(location.href);
      u.searchParams.set("m", state.market);
      history.replaceState(null, "", u);
      load(state.market);
    });
    document.getElementById("mo-pills").addEventListener("click", (e) => {
      const b = e.target.closest(".fpill");
      if (!b) return;
      state.filter = b.dataset.pill;
      render();
    });
    load(state.market);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
