/* TURTLE — the fourth lens (2026-08-21).
 *
 * Four views on one page: the RULES (the complete system, rendered from the
 * scan's own published params so the prose can never describe a different
 * system than the code runs), the SIGNALS the nightly scan found, a SIZING
 * calculator, and the EVIDENCE — what the arithmetic and the history
 * actually say about the number in the headline.
 *
 * THREE OF THE FOUR VIEWS NEED NO DATA. A rules reference that goes blank
 * when a fetch fails is not a reference, so RULES, SIZING and EVIDENCE render
 * from constants and from what you type; only SIGNALS needs the scan file,
 * and it says so plainly when the file is not there yet.
 *
 * READ-ONLY, like every other lens surface here. It fetches three published
 * JSON files and nothing else — no writes, no /api/, no state.
 */
(function () {
  "use strict";

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ── the parameter mirror ───────────────────────────────────────────────────
  // A hand-typed copy of scanner/config.py's TURTLE_* block, used ONLY when
  // the scan file has not loaded. It is a real fallback, not dead code, which
  // means it is what the page shows exactly when the reader is least able to
  // check it — the lesson risk_manager.js's PUBLISHED_DEFAULTS paid for by
  // drifting for months (TOP100 #34). tests/test_turtle.py parses config.py
  // and fails if any value here stops matching.
  const FALLBACK = {
    n_period: 20,
    s1_entry: 20, s1_exit: 10,
    s2_entry: 55, s2_exit: 20,
    stop_n: 2.0, pyramid_step_n: 0.5, max_units: 4,
    risk_pct: 0.01,
    max_units_close_corr: 6, max_units_loose_corr: 10, max_units_direction: 12,
    drawdown_step_pct: 10.0, drawdown_cut_pct: 20.0,
    whipsaw_risk_pct: 0.005, whipsaw_stop_n: 0.5,
    account_equity: 5000.0, allow_shorts: true,
    min_bars: 250, approach_pct: 3.0,
    min_coverage_pct: 60.0,
    small_universe_max: 30, small_universe_max_missing: 2,
    period: "5y",
  };

  const MARKETS = ["asx", "nasdaq", "crypto", "futures"];
  const CUR = { asx: "A$", nasdaq: "$", crypto: "$", futures: "$" };

  let DATA = null;               // the current market's payload, or null
  let P = FALLBACK;              // params in force (payload's, else the mirror)
  let PARAMS_ARE_LIVE = false;
  let MARKET = "asx";
  let VIEW = "signals";           // set to "rules" by load() when no scan exists
  let FILTER = "all";
  let QUERY = "";
  let EQUITY = FALLBACK.account_equity;
  let OPEN = null;               // expanded row symbol
  let SORT = "fired";            // URL-only so far (Phase 3): no sort control exists yet
  let TOUCHED = false;           // has the reader picked a view themselves?
  let BOOK = null;               // the forward paper book, all markets
  let PORTFOLIO = null;          // the shared-equity portfolio replay, per sleeve

  // ── formatting ─────────────────────────────────────────────────────────────
  const num = (v, d) => (v == null || !isFinite(v) ? "—" : Number(v).toFixed(d == null ? 2 : d));
  const money = (v, d) => (v == null || !isFinite(v) ? "—" : CUR[MARKET] + Number(v).toLocaleString(
    undefined, { minimumFractionDigits: d == null ? 2 : d, maximumFractionDigits: d == null ? 2 : d }));
  const pct = (v, d) => (v == null || !isFinite(v) ? "—" : Number(v).toFixed(d == null ? 1 : d) + "%");
  const sgnR = (v) => (v == null || !isFinite(v) ? "—" : (v >= 0 ? "+" : "") + Number(v).toFixed(2) + "R");
  const cls = (v) => (v == null || !isFinite(v) ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "");
  const big = (v) => (v == null || !isFinite(v) ? "—" : Number(v).toLocaleString(
    undefined, { maximumFractionDigits: 0 }));

  // ── the arithmetic the page does in the browser ────────────────────────────

  // Unit = (risk% x equity) / N. Same formula as scanner/turtle.unit_size;
  // duplicated here rather than read from the payload because the whole point
  // of the calculator is that it answers for YOUR account, not for the one the
  // scan happened to publish against.
  function unitShares(equity, n, riskPct) {
    const denom = Number(n);
    if (!isFinite(denom) || denom <= 0 || !isFinite(equity)) return 0;
    return ((riskPct == null ? P.risk_pct : riskPct) * equity) / denom;
  }

  // The four fills and the ONE stop the whole position ends up on.
  function ladder(entry, n, side) {
    const sign = side === "short" ? -1 : 1;
    const out = [];
    for (let u = 0; u < P.max_units; u++) {
      const price = entry + sign * P.pyramid_step_n * n * u;
      out.push({ unit: u + 1, price: price, ownStop: price - sign * P.stop_n * n });
    }
    // every earlier unit is dragged up to the last unit's stop
    const shared = out[out.length - 1].ownStop;
    out.forEach((r) => { r.shared = shared; });
    return out;
  }

  // The drawdown rule, compounding: one 20% cut per completed 10% of drawdown.
  function ddEquity(equity, ddPct) {
    const steps = Math.floor(ddPct / P.drawdown_step_pct);
    return equity * Math.pow(1 - P.drawdown_cut_pct / 100, Math.max(0, steps));
  }

  // Years of compounding to multiply `mult` times over at rate r.
  const yearsTo = (mult, r) => (r <= 0 ? Infinity : Math.log(mult) / Math.log(1 + r));

  // ── data ───────────────────────────────────────────────────────────────────
  function loadBook() {
    return fetch("data/turtle_book.json", { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null)
      .then((j) => { BOOK = j && j.summary ? j : null; return BOOK; });
  }

  function loadPortfolio() {
    return fetch("data/turtle_portfolio.json", { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null)
      .then((j) => { PORTFOLIO = j && j.sleeves ? j : null; return PORTFOLIO; });
  }

  function load() {
    loadBook();
    loadPortfolio();
    return fetch("data/" + MARKET + "_turtle.json", { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null)
      .then((j) => {
        DATA = j && j.results ? j : null;
        // A published params block always wins over the mirror: it is what the
        // engine actually ran with tonight.
        PARAMS_ARE_LIVE = !!(DATA && DATA.params);
        P = PARAMS_ARE_LIVE ? Object.assign({}, FALLBACK, DATA.params) : FALLBACK;
        // THE LANDING VIEW IS THE SCAN. This page is a scanner first and a
        // reference second: opening on the rulebook made a tab carrying 400
        // live rows look empty to anyone who did not think to click through.
        // Only fall back to RULES when there is genuinely nothing to scan --
        // and never override a view the reader has already chosen.
        if (!TOUCHED) VIEW = DATA ? "signals" : "rules";
        // Same reasoning, one field over: FILTER's default is "fired" (the
        // URL contract, Phase 2), but a fired-today count of zero is a real
        // possibility on a quiet day, and an empty SIGNALS list on first
        // paint reads as broken rather than as "nothing fired." Fall
        // through to the next non-empty bucket -- never past ALL, which is
        // never empty when DATA exists. A URL or a click that already
        // chose a filter (TOUCHED) is left exactly as chosen.
        if (!TOUCHED && DATA && FILTER === "fired") {
          const a = DATA.aggregate || {};
          if (!a.fired_today) FILTER = (a.long || a.short) ? "held" : "all";
        }
        return DATA;
      });
  }

  // ── deck ───────────────────────────────────────────────────────────────────
  // The five FILTER buckets, computed once from the aggregate so the deck
  // pills and the SIGNALS segs below can never show two different numbers
  // for the same word. "held" is aggregate.long + aggregate.short, not a
  // filter over DATA.results -- the results array is truncated (large
  // markets ship ~400 of a few thousand names) and keeps every long/short
  // row but only a sample of flat ones, so counting the array under-counts
  // "in a position" the moment a market is big enough to truncate at all.
  function filterCounts() {
    if (!DATA) return null;
    const a = DATA.aggregate || {};
    return {
      all: a.names || 0,
      fired: a.fired_today || 0,
      held: (a.long || 0) + (a.short || 0),
      near: a.approaching || 0,
      blocked: a.s1_blocked || 0,
    };
  }

  // The scan's own schedule (.github/workflows/turtle.yml), restated as a
  // fixed per-market sentence rather than a computed "next in Xm" -- a
  // countdown this page cannot keep honest across a DST change or a missed
  // run is worse than no countdown. Keep this in step with turtle.yml if
  // that file's cron lines ever move.
  const NEXT_CRON = {
    asx: "next scan ~06:30 UTC weekdays",
    nasdaq: "next scan ~21:30 UTC weekdays",
    crypto: "next scan every 4h (:05 past the hour)",
    futures: "next scan ~23:00 UTC weekdays",
  };

  // Buttons, not badges: role=group, one FILTER value per pill, shared with
  // the SIGNALS segs in render() below. SKIPS is not a filter value -- it
  // is a jump to the BOOK view's skip-reason table -- so it carries
  // data-skips instead of data-filter and is handled by its own branch in
  // mount()'s click delegate.
  function deckPillsHTML(counts) {
    const DEFS = [
      ["fired", "FIRED TODAY", counts.fired > 0],
      ["held", "IN A POSITION", false],
      ["near", "APPROACHING", false],
      ["blocked", "S1 BLOCKED", false],
      ["all", "ALL", false],
    ];
    let html = '<div class="deck-pills" role="group" aria-label="Turtle filter">' +
      DEFS.map(([k, label, hot]) => {
        const active = FILTER === k;
        return '<button type="button" class="fpill' + (hot ? " g" : "") +
          (active ? " is-active" : "") + '" data-filter="' + k + '" aria-pressed="' +
          (active ? "true" : "false") + '">' + label + ' <span class="seg-count">' +
          big(counts[k]) + "</span></button>";
      }).join("");
    const skipTotal = BOOK && BOOK.skip_counts ? (BOOK.skip_counts.total || 0) : 0;
    if (skipTotal) {
      html += '<button type="button" class="fpill" data-skips="1">SKIPS ' +
        '<span class="seg-count">' + big(skipTotal) + "</span></button>";
    }
    return html + "</div>";
  }

  function deckHTML() {
    if (!DATA) {
      return '<div class="deck-status"><span class="deck-dot" data-state="idle"></span>' +
        '<span class="deck-title">TURTLE &mdash; ' + esc(MARKET.toUpperCase()) + "</span></div>" +
        '<p class="deck-sub">No scan file for ' + esc(MARKET.toUpperCase()) +
        ' yet — the rules, the calculator and the evidence below work without one.</p>';
    }
    const counts = filterCounts();
    const cron = NEXT_CRON[MARKET] || "";
    return '<div class="deck-status"><span class="deck-dot" data-state="ok"></span>' +
      '<span class="deck-title">TURTLE &mdash; ' + esc(MARKET.toUpperCase()) + "</span></div>" +
      '<p class="deck-sub">' + big(DATA.evaluated) + " names evaluated of " + big(DATA.universe_size) +
      " in the universe &middot; scanned " + esc(String(DATA.generated_at || "").slice(0, 16).replace("T", " ")) +
      (cron ? " &middot; " + esc(cron) : "") + "</p>" + deckPillsHTML(counts);
  }

  // ── view 1: THE RULES ──────────────────────────────────────────────────────
  function rulesHTML() {
    const src = PARAMS_ARE_LIVE
      ? "Every number below is read from the scan's own published parameters, so this page cannot describe a system the engine is not running."
      : "The scan file has not loaded, so these are the built-in constants. They are checked against scanner/config.py by a test on every push.";

    const card = (title, body, note) =>
      '<section class="tt-card"><h3>' + title + "</h3>" + body +
      (note ? '<p class="tt-note">' + note + "</p>" : "") + "</section>";

    const N = "<b>N</b>";

    return '<p class="tt-lede">' + esc(src) + "</p>" +

      card("1 &middot; N — the volatility unit everything else is measured in", `
        <p>${N} is Wilder's ${P.n_period}-period Average True Range. The original rules give it
        as a recurrence rather than as an average:</p>
        <pre class="tt-math">True Range = max( H &minus; L , H &minus; PDC , PDC &minus; L )

N = ( ${P.n_period - 1} &times; PDN + TR ) / ${P.n_period}</pre>
        <p>PDC is the previous day's close, PDN the previous day's N. One N is roughly
        one average day's range, so "2N" means "two average days against me" on every
        instrument at once, whatever it costs in dollars.</p>`,
        "This is NOT a simple " + P.n_period + "-day mean of true range. A mean drops a " +
        "volatility spike abruptly when it leaves the window; Wilder's decays it smoothly. " +
        "N sets the position size, the stop AND the pyramid spacing, so the two choices " +
        "diverge three times over. It is also 20 periods, not the 14 most charting packages default to.") +

      card("2 &middot; Entries — two systems, run side by side", `
        <table class="tt-table"><thead><tr><th></th><th>System 1</th><th>System 2</th></tr></thead>
        <tbody>
          <tr><td>Long</td><td>break above the ${P.s1_entry}-day high</td><td>break above the ${P.s2_entry}-day high</td></tr>
          <tr><td>Short</td><td>break below the ${P.s1_entry}-day low</td><td>break below the ${P.s2_entry}-day low</td></tr>
          <tr><td>Filter</td><td class="tt-warn">yes — see rule 3</td><td>none, ever</td></tr>
        </tbody></table>
        <p>The breakout level is built from the bars <em>before</em> the signal bar, and the
        trigger is one tick beyond it. The Turtles entered <b>intraday, on the tick</b>, with a
        resting stop order placed in advance — not on the close and not on the next open.</p>
        <p><b>When one bar breaks both channels, the entry is tagged System 2 —
        the failsafe is tested first.</b> That tag is a money difference, not a
        label: the entering system owns the exit, so the position rides the
        patient ${P.s2_exit}-day channel instead of leaving at the
        ${P.s1_exit}-day.</p>`,
        "Entering on the close instead is the most common silent modification. It filters " +
        "out intraday false breaks, and it pays for that with worse fills on exactly the " +
        "trades that gap and run — which are the ones that pay for the year.") +

      card("3 &middot; The System 1 filter — the rule the short version drops", `
        <p>A ${P.s1_entry}-day breakout is <b>skipped</b> when the previous breakout in that
        market would have been a winner.</p>
        <ul>
          <li>A breakout counts as a <b>loser</b> if price moved <b>${P.stop_n}N against it</b>
              before a profitable ${P.s1_exit}-day exit. Anything else is a winner — including a
              trade that drifted out slightly <em>below</em> entry without ever going ${P.stop_n}N
              offside. That reads wrong and it is the rule as written.</li>
          <li>It counts <b>every breakout the market printed</b>, whether or not you took it.
              A breakout skipped by this very rule still becomes "the last breakout".</li>
          <li>It is <b>direction-agnostic</b>: a losing short breakout enables the next long
              one. One chronological chain per market, not two.</li>
        </ul>
        <p>The logic: big trends tend to start after a run of small false breakouts, so the
        filter tries to have you in the market precisely when the last attempt failed.</p>`,
        "Without this, System 1 is a plain " + P.s1_entry + "-day Donchian channel that takes " +
        "every whipsaw in a range. Implementing it requires replaying the market's own " +
        "breakout history, which is why most simplified versions leave it out.") +

      card("4 &middot; The failsafe", `
        <p>Because rule 3 can skip an entry that turns into the trend of the year, the
        <b>${P.s2_entry}-day breakout is taken unconditionally</b>. A System 1 signal blocked by the
        filter is picked up at the ${P.s2_entry}-day level by System 2.</p>
        <p>That is what lets the filter be aggressive without risking a total miss.</p>`) +

      card("5 &middot; Exits — the system that entered owns the exit", `
        <table class="tt-table"><thead><tr><th></th><th>Long exits on</th><th>Short exits on</th></tr></thead>
        <tbody>
          <tr><td>System 1</td><td>the ${P.s1_exit}-day low</td><td>the ${P.s1_exit}-day high</td></tr>
          <tr><td>System 2</td><td>the ${P.s2_exit}-day low</td><td>the ${P.s2_exit}-day high</td></tr>
        </tbody></table>
        <p>A position opened on the ${P.s2_entry}-day breakout does <b>not</b> exit on the
        ${P.s1_exit}-day low just because that level arrives first.</p>`) +

      card("6 &middot; The stop — " + P.stop_n + "N from the most recent unit", `
        <p>Every unit is issued a stop ${P.stop_n}N from its own fill. As units are added, every
        earlier unit's stop is raised too, so the <b>whole position ends up on one stop,
        ${P.stop_n}N from the most recently added unit</b>.</p>
        <p>If the market gaps through the stop you are filled at the gap, not at the stop.
        The replay behind the signals below books it that way on purpose.</p>`) +

      card("7 &middot; Pyramiding — and the stop-raise that halves its risk", `
        <p>Add one unit for every <b>${P.pyramid_step_n}N</b> the price moves in your favour,
        measured from the <b>last unit's actual fill</b>, to a maximum of
        <b>${P.max_units} units</b> in one market.</p>
        ${ladderTableHTML(100, 2, "long")}
        <p>Read the last column: the four units lose ${P.pyramid_step_n}N, 1N,
        ${P.pyramid_step_n + 1}N and ${P.stop_n}N — <b>5N, or 5% of the account</b>. Left on the
        stops they were issued they would lose 8N, or 8%.</p>`,
        "Halving the full-size risk is the entire purpose of the half-N stop raise. It is " +
        "the rule most often dropped in retail implementations, and dropping it makes a " +
        "fully pyramided position 60% riskier than the system intends.") +

      card("8 &middot; Position sizing — one unit = 1% of the account per N", `
        <pre class="tt-math">Dollar volatility = N &times; dollars per point
                          ( for one share, dollars per point = 1 )

Unit = ( ${(P.risk_pct * 100).toFixed(0)}% &times; account ) / dollar volatility</pre>
        <p>So one unit moving 1N is exactly ${(P.risk_pct * 100).toFixed(0)}% of the account, and a
        single-unit ${P.stop_n}N stop-out costs ${(P.risk_pct * P.stop_n * 100).toFixed(0)}%. Every
        other number in this system is stated in N precisely so it can be read in equity
        terms without knowing anything about the instrument.</p>
        <p><a class="tt-link" href="#" data-goto="sizing">Work it out for your account &rarr;</a></p>`) +

      card("9 &middot; Position limits — the rule that stops four-unit bets becoming one bet", `
        <table class="tt-table"><thead><tr><th>Scope</th><th>Max units</th></tr></thead><tbody>
          <tr><td>A single market</td><td class="mono">${P.max_units}</td></tr>
          <tr><td>Closely correlated markets</td><td class="mono">${P.max_units_close_corr}</td></tr>
          <tr><td>Loosely correlated markets</td><td class="mono">${P.max_units_loose_corr}</td></tr>
          <tr><td>One direction — all long, or all short</td><td class="mono">${P.max_units_direction}</td></tr>
        </tbody></table>
        <p>The last three are per direction, so the theoretical maximum book is
        ${P.max_units_direction} long plus ${P.max_units_direction} short.</p>`,
        "The SCAN states these; the FORWARD BOOK enforces three of them — " +
        P.max_units + " per name, " + P.max_units_close_corr + " per correlated " +
        "bucket (crypto counts as ONE bucket, deliberately) and " +
        P.max_units_direction + " per direction, counted over every unit " +
        "including pyramid adds. The loose-correlation " + P.max_units_loose_corr +
        " stays declared and honestly unenforced: no taxonomy for 'loosely " +
        "correlated' exists in this repo, and sector is already spent on the " +
        "close bucket — faking a second grouping would be worse than saying so.") +

      card("10 &middot; The drawdown rule — and it compounds", `
        <p>Cut the equity you <em>size from</em> by <b>${P.drawdown_cut_pct}%</b> for every
        <b>${P.drawdown_step_pct}%</b> the account is below its peak.</p>
        ${ddTableHTML(100000)}
        <p>Two 10% steps is 0.8 &times; 0.8 = 64% of the account, not 60%. Reading it as
        additive under-cuts exactly when the rule is trying hardest to keep you alive.</p>`,
        "Honest gap in the published rules: whether each further step measures against the " +
        "original or the already-reduced notional is stated ambiguously, and the rule for " +
        "scaling back UP after a recovery is not specified at all. This page and the engine " +
        "both measure drawdown from the real peak. Implementations differ here and the " +
        "choice materially changes results.") +

      card("11 &middot; The Whipsaw variant", `
        <p>The documented alternative stop: risk <b>${(P.whipsaw_risk_pct * 100).toFixed(1)}%</b> per
        unit with the stop at <b>${P.whipsaw_stop_n}N</b> instead of
        ${(P.risk_pct * P.stop_n * 100).toFixed(0)}% at ${P.stop_n}N — a quarter of the risk at a
        quarter of the distance.</p>
        <ul>
          <li>Stopped out, you re-enter when price reaches the original breakout level again,
              with no limit on re-entries.</li>
          <li>Earlier units' stops are <b>not</b> raised as units are added — each keeps its
              own ${P.whipsaw_stop_n}N stop.</li>
        </ul>
        <p>Many more losing trades, each a quarter the size, and much more slippage and
        commission. The original document reports better overall profitability.</p>`,
        "The signals below use the " + P.stop_n + "N stop, because that is the default the " +
        "rules specify. The Whipsaw numbers are stated for comparison only — nothing here " +
        "computes them.");
  }

  function ladderTableHTML(entry, n, side) {
    const rows = ladder(entry, n, side);
    const sign = side === "short" ? -1 : 1;
    const body = rows.map((r) => {
      const lossN = ((r.shared - r.price) * sign) / n;
      return "<tr><td>" + r.unit + "</td><td class=\"mono\">" +
        (r.unit === 1 ? "breakout" : (sign > 0 ? "+" : "−") + P.pyramid_step_n + "N from unit " + (r.unit - 1)) +
        '</td><td class="mono">' + num(r.price) + '</td><td class="mono">' + num(r.ownStop) +
        '</td><td class="mono neg">' + num(lossN, 2) + "N</td></tr>";
    }).join("");
    return '<div class="tt-tablewrap"><table class="tt-table tt-ladder">' +
      "<caption>A worked position: entry " + num(entry) + ", N = " + num(n) +
      ". The final shared stop is " + num(rows[rows.length - 1].shared) + ".</caption>" +
      "<thead><tr><th>Unit</th><th>Added at</th><th>Fill</th><th>Its own stop</th>" +
      "<th>Loses, on the final shared stop</th></tr></thead><tbody>" + body +
      '</tbody></table></div>';
  }

  function ddTableHTML(equity) {
    const rows = [0, 10, 20, 30, 40, 50].map((d) => {
      const e = ddEquity(equity, d);
      return "<tr><td>" + (d ? "−" + d + "%" : "at the peak") +
        '</td><td class="mono">' + big(equity * (1 - d / 100)) +
        '</td><td class="mono">' + big(e) +
        '</td><td class="mono">' + pct(100 * e / equity, 0) + "</td></tr>";
    }).join("");
    return '<div class="tt-tablewrap"><table class="tt-table">' +
      "<caption>A " + big(equity) + " account.</caption><thead><tr><th>Drawdown</th>" +
      "<th>Actual equity</th><th>Size from</th><th>&hellip;of the original</th></tr></thead>" +
      "<tbody>" + rows + "</tbody></table></div>";
  }

  // ── view 2: SIGNALS ────────────────────────────────────────────────────────
  function rowsFor() {
    if (!DATA) return [];
    let rows = DATA.results.slice();
    if (FILTER === "fired") rows = rows.filter((r) => r.signal);
    else if (FILTER === "held") rows = rows.filter((r) => r.state !== "flat");
    else if (FILTER === "near") rows = rows.filter((r) => r.approaching);
    else if (FILTER === "blocked") rows = rows.filter((r) => r.s1_blocked);
    if (QUERY) {
      const q = QUERY.toUpperCase();
      rows = rows.filter((r) => (r.symbol || "").toUpperCase().indexOf(q) >= 0 ||
        (r.name || "").toUpperCase().indexOf(q) >= 0);
    }
    return sortRows(rows);
  }

  function stateChip(r) {
    if (r.signal) {
      const sys = r.signal.indexOf("s1") === 0 ? "1" : "2";
      const side = r.signal.indexOf("long") > 0 ? "LONG" : "SHORT";
      return '<span class="tt-chip is-fired">ENTRY S' + sys + " " + side + " today</span>";
    }
    if (r.state !== "flat") {
      const p = r.position || {};
      return '<span class="tt-chip is-held">' + esc(r.state.toUpperCase()) + " &middot; " +
        (p.units || 1) + "u &middot; S" + (p.system || "?") + "</span>";
    }
    if (r.approaching && r.nearest) {
      return '<span class="tt-chip is-near">' + pct(Math.abs(r.nearest.distance_pct)) +
        " from " + esc(labelOf(r.nearest.key)) + "</span>";
    }
    return '<span class="tt-chip">flat</span>';
  }

  const labelOf = (k) => ({
    s1_long: "the " + P.s1_entry + "-day high", s2_long: "the " + P.s2_entry + "-day high",
    s1_short: "the " + P.s1_entry + "-day low", s2_short: "the " + P.s2_entry + "-day low",
  }[k] || k);

  // ── chart links + book facts on a row (Phase 6) ─────────────────────────────
  // chart.html has no page for a continuous futures contract (=F / 6E-style
  // symbols); a link it cannot resolve is worse than no link, so futures
  // gets a short honest sentence instead of a 404 <a>.
  function chartHref(market, sym) {
    if (market === "futures") return null;
    return "chart.html?m=" + encodeURIComponent(market) + "&s=" + encodeURIComponent(sym) + "&src=turtle";
  }

  // One R formula, shared with bookHTML()'s own open-positions table, so a
  // position can never show two different R's depending on which part of
  // the page you're reading. Any required field missing -> null, so the
  // caller omits the line rather than showing a guess.
  function openR(p) {
    if (!p || !p.n || !p.units || p.last_mark == null || p.cost_basis == null) return null;
    const sign = p.side === "short" ? -1 : 1;
    const avg = p.cost_basis / p.units;
    return sign * (p.last_mark - avg) * p.units / (P.stop_n * p.n * p.units);
  }

  // Isolated margin's liquidation line -- the same formula
  // scanner/turtle_book.py uses internally to decide whether the stop or
  // the liquidation price binds first. It is never published as its own
  // field, so it is re-derived here from fields that ARE published
  // (cost_basis, units, posted, side, last_mark); any of them missing
  // returns null rather than a fabricated distance.
  function liqDistanceR(p) {
    if (!p || !p.posted || !p.units || p.cost_basis == null || p.last_mark == null || !p.n) return null;
    const avg = p.cost_basis / p.units;
    const liq = p.side === "short" ? avg + p.posted / p.units : avg - p.posted / p.units;
    return Math.abs(p.last_mark - liq) / (P.stop_n * p.n);
  }

  // Next add (Phase D): Turtle's own rule -- one add per pyramid_step_n*N,
  // max_units total -- computed ONLY from fields the BOOK payload already
  // carries (last_fill, n, side, fills.length). Never a call into
  // turtle_book.py's own math, which this page cannot see and must not
  // guess at: a wrong next-add is worse than none. "max units" once
  // fills.length reaches P.max_units; "—" only when a required field is
  // genuinely missing. Top-level like liqDistanceR above, so posRow (BOOK)
  // and bookOpenHTML (a SIGNALS row's expanded detail) share one formula
  // and can never quote two different numbers for the same position.
  function nextAddStr(p) {
    if (!p || (p.fills || []).length >= P.max_units) return "max units";
    if (p.last_fill == null || p.n == null) return "—";
    const sign = p.side === "short" ? -1 : 1;
    return num(p.last_fill + sign * P.pyramid_step_n * p.n, 4);
  }

  // A symbol can be open in more than one sleeve at once (a cash position
  // and a levered one are separate books) -- every match is returned, not
  // just the first.
  function bookOpenPositions(symbol) {
    if (!BOOK || !BOOK.open) return [];
    return BOOK.open.filter((p) => p.symbol === symbol);
  }

  function leverageOf(market) {
    const params = BOOK && BOOK.by_market && BOOK.by_market[market] && BOOK.by_market[market].params;
    return params && params.leverage > 1 ? params.leverage : null;
  }

  // A BOOK sleeve key is not always a market this page can load a scan for:
  // a levered sleeve is priced from the very same scan as its cash sibling,
  // just filed under its own by_market key with a leverage suffix. Strip
  // that suffix and confirm the result is one of the four real markets;
  // anything unrecognised is returned unchanged rather than guessed at.
  function scanMarketFor(market) {
    const base = (market || "").replace(/\d+x$/i, "");
    return MARKETS.indexOf(base) !== -1 ? base : market;
  }

  // Vehicle badge: rendered from params.leverage, never a hardcoded
  // multiplier -- and only for a symbol actually open in a levered sleeve,
  // so a market that merely HAS a levered sleeve elsewhere never badges
  // every row in it.
  function vehicleBadgeHTML(symbol) {
    const positions = bookOpenPositions(symbol);
    for (let i = 0; i < positions.length; i++) {
      const lev = leverageOf(positions[i].market);
      if (lev) return '<span class="tt-chip" title="Open in a ' + big(lev) +
        '&times; sleeve — a perp analogue, not futures margin, sized from posted ' +
        'margin rather than notional">' + big(lev) + "&times; margin</span>";
    }
    return "";
  }

  // A name skipped from a levered sleeve for the correlated-group cap is a
  // fact this row can carry without a click-through to BOOK. Symmetric to
  // vehicleBadgeHTML: rendered from the skip's own leverage params, never
  // a hardcoded multiplier or sleeve name, and matched via scanMarketFor
  // (the same generic suffix-strip Phase 7 uses for the open-position
  // jump) rather than any literal sleeve key. Scoped to close_corr_cap
  // only, per spec -- not a general skip-reason display.
  function capSkipBadgeHTML(symbol) {
    if (!BOOK || !BOOK.skips) return "";
    let last = null;
    for (let i = 0; i < BOOK.skips.length; i++) {
      const k = BOOK.skips[i];
      if (k.symbol === symbol && k.reason === "close_corr_cap" &&
          k.market !== MARKET && scanMarketFor(k.market) === MARKET) last = k;
    }
    if (!last) return "";
    const lev = leverageOf(last.market);
    const label = lev ? big(lev) + "&times; cap" : "cap";
    return '<span class="tt-chip is-blocked" title="Skipped on the ' +
      esc((last.market || "").toUpperCase()) + ' sleeve: ' + big(last.units_on_book || 0) +
      ' of ' + big(last.cap || 0) + ' correlated units already held">' + label + '</span>';
  }

  function bookOpenHTML(symbol) {
    const positions = bookOpenPositions(symbol);
    if (!positions.length) return "";
    return positions.map((p) => {
      const avg = p.units ? p.cost_basis / p.units : null;
      const r = openR(p);
      const lev = leverageOf(p.market);
      const nextAdd = nextAddStr(p);
      let g = '<div class="tt-detail-grid">' +
        kv("In the book (" + esc((p.market || "").toUpperCase()) + ")",
          esc(p.side || "") + " S" + esc(String(p.system || "?"))) +
        kv("Units", (p.fills || []).length) +
        (avg != null ? kv("Avg fill", money(avg)) : "") +
        (p.stop != null ? kv("Stop", money(p.stop)) : "") +
        (nextAdd !== "—" ? kv("Next add", nextAdd) : "") +
        (r != null ? kv("Open R", sgnR(r)) : "");
      if (lev) {
        if (p.posted != null) g += kv(big(lev) + "&times; posted margin", money(p.posted));
        const distR = liqDistanceR(p);
        if (distR != null) g += kv("Liquidation distance", num(distR, 2) + "R");
      }
      return g + "</div>";
    }).join("");
  }

  // "verbatim" per the phase spec: the raw reason code as the book wrote
  // it, not translated through bookHTML()'s own WHY table -- this is a
  // fact about what the book did, not a second copy of that prose to keep
  // in sync with the first.
  function bookSkipHTML(symbol) {
    if (!BOOK || !BOOK.skips) return "";
    let last = null;
    for (let i = 0; i < BOOK.skips.length; i++) if (BOOK.skips[i].symbol === symbol) last = BOOK.skips[i];
    if (!last) return "";
    return '<p class="tt-note">The book skipped this on ' + esc(last.as_of || last.bar || "the last bar") +
      ": " + esc(last.action || "an action") + " &mdash; <code>" + esc(last.reason || "") + "</code></p>";
  }

  // ── sort (Phase 6) ───────────────────────────────────────────────────────
  const SORT_CYCLE = ["fired", "distance", "n", "symbol"];
  const SORT_LABELS = { fired: "FIRED", distance: "DISTANCE", n: "N", symbol: "SYMBOL" };

  // 0 for a name that already fired (nothing is closer than today), then
  // whatever the payload says is the nearest real distance -- to a trigger
  // level for a flat/approaching name, to the stop for a held one. Anything
  // with neither sorts last, never invented as some fake "far" number.
  function distanceOf(r) {
    if (r.signal) return 0;
    if (r.nearest && r.nearest.distance_pct != null) return r.nearest.distance_pct;
    if (r.stop_distance_pct != null) return r.stop_distance_pct;
    return Infinity;
  }

  // rows arrives already a fresh array (rowsFor()'s own .slice()/.filter()
  // chain, never DATA.results itself), so sorting it in place cannot reach
  // the published payload -- copy-then-sort happens before this is called,
  // not inside it.
  function sortRows(rows) {
    const bySymbol = (a, b) => (a.symbol || "").localeCompare(b.symbol || "");
    if (SORT === "distance") return rows.sort((a, b) => distanceOf(a) - distanceOf(b) || bySymbol(a, b));
    if (SORT === "n") return rows.sort((a, b) => (b.n || 0) - (a.n || 0) || bySymbol(a, b));
    if (SORT === "symbol") return rows.sort(bySymbol);
    return rows; // "fired" (default): the scan's own fired -> held -> proximity order, untouched
  }

  function rowHTML(r) {
    const shares = unitShares(EQUITY, r.n);
    const open = OPEN === r.symbol;
    const rec = r.record || {};
    const head =
      '<div class="tt-row-main">' +
        '<div class="tt-sym"><b class="mono">' + esc(r.symbol) + "</b>" +
          '<span class="tt-name">' + esc(r.name || "") + "</span></div>" +
        '<div class="tt-state">' + stateChip(r) +
          (r.s1_blocked ? '<span class="tt-chip is-blocked" title="The previous ' +
            P.s1_entry + '-day breakout in this name was a filter-winner, so System 1 is ' +
            'skipped until one fails. The ' + P.s2_entry + '-day failsafe still applies.">S1 filtered</span>' : "") +
          vehicleBadgeHTML(r.symbol) +
          capSkipBadgeHTML(r.symbol) +
        "</div>" +
        '<div class="tt-nums"><span class="mono">' + money(r.price) + "</span>" +
          '<span class="mono tt-dim">N ' + num(r.n) + " (" + pct(r.n_pct) + ")</span>" +
          (r.unit_stop_loss != null ? '<span class="mono tt-dim">stop ' +
            money(r.unit_stop_loss, 0) + "</span>" : "") +
        "</div>" +
        '<div class="tt-nums"><span class="mono">' + num(shares, shares < 10 ? 4 : 0) + " units</span>" +
          '<span class="mono tt-dim">' + money(shares * r.price, 0) + "</span></div>" +
      "</div>";

    // tabindex/role/aria mirror the main deck's rows (app.js): this is an
    // expander, so it has to be reachable and announceable, not just clickable.
    const attrs = ' data-sym="' + esc(r.symbol) + '" tabindex="0" role="button"' +
      ' aria-expanded="' + (open ? "true" : "false") + '"' +
      ' aria-label="' + esc(r.symbol) + " " + esc(r.state) + ' — Enter for details"';
    if (!open) return '<article class="tt-row"' + attrs + ">" + head + "</article>";

    let detail = "";
    const href = chartHref(MARKET, r.symbol);
    detail += href
      ? '<p class="tt-note"><a class="tt-link" href="' + esc(href) + '">Chart &rarr;</a></p>'
      : '<p class="tt-note">no chart for this contract.</p>';
    detail += bookOpenHTML(r.symbol);
    detail += bookSkipHTML(r.symbol);
    if (r.contracts) {
      const c = r.contracts;
      detail += '<div class="tt-detail-grid">' +
        kv("Dollars per point", money(c.dpp, 0)) +
        kv("One unit (full)", c.full_contracts == null ? "—" : num(c.full_contracts, 4) + " contracts") +
        kv("One unit (" + (c.micro || "no micro") + ")",
           c.micro_contracts == null ? "—" : num(c.micro_contracts, 4) + " contracts") +
        kv("Unit fits at " + money(EQUITY, 0), c.unit_fits ? "yes" : "<b>NO</b>") +
        "</div>";
      const rl = r.rolls;
      if (rl && rl.bars) {
        detail += '<p class="tt-note"><b>Back-adjusted tape.</b> ' + big(rl.bars) +
          " bar" + (rl.bars === 1 ? "" : "s") + " (" + pct(100 * rl.share, 1) +
          ") carry an overnight gap too large to be a real overnight move — " +
          "contract rolls, which a continuous <code>=F</code> series folds into " +
          "the price history. Nobody traded those steps, but true range counts " +
          "them, and the bar after a roll runs an N about 13–22% too high — a " +
          "stop that much too wide and a unit that much too small." +
          (rl.in_n_window
            ? " <b>One sits inside the current 20-bar N window, so today's N on " +
              "this market is affected.</b>"
            : " None is inside the current N window, so today's N is clean.") +
          (rl.last ? " Most recent: " + esc(rl.last) + "." : "") +
          " Detected, not corrected: the true-range formula is frozen and " +
          "quietly trimming it would be the exact dishonesty this lens refuses." +
          "</p>";
      }
      if (!c.unit_fits) {
        detail += '<p class="tt-note">At ' + money(EQUITY, 0) +
          " one unit is a fraction of a contract. Taking one anyway risks <b>" +
          pct(c.one_contract_risk_pct) + "</b> of the account on a " + P.stop_n +
          "N stop, against the " + (P.risk_pct * P.stop_n * 100).toFixed(0) +
          "% the rules intend. That is not this system run small — it is a " +
          "different and much more dangerous one. Raise the account or trade " +
          "a market whose unit fits.</p>";
      }
    }

    if (r.state === "flat" && r.triggers) {
      const t = r.triggers;
      detail += '<div class="tt-detail-grid">' +
        kv("Buy above (" + P.s1_entry + "d)", money(t.s1_long) + (r.s1_blocked ? " — filtered" : "")) +
        kv("Buy above (" + P.s2_entry + "d)", money(t.s2_long)) +
        kv("Sell below (" + P.s1_entry + "d)", money(t.s1_short)) +
        kv("Sell below (" + P.s2_entry + "d)", money(t.s2_short)) +
        "</div>";
      const lvl = r.nearest ? r.nearest.level : t.s2_long;
      detail += ladderTableHTML(lvl, r.n, (r.nearest && r.nearest.key || "").indexOf("short") > 0 ? "short" : "long");
      detail += '<p class="tt-note">At ' + money(EQUITY, 0) + ", one unit is " +
        num(shares, shares < 10 ? 4 : 0) + " units of stock (" + money(shares * lvl, 0) +
        ") and a full four-unit stop-out costs " + money(0.05 * EQUITY, 0) + " — 5% of the account.</p>";
    } else if (r.position) {
      const p = r.position;
      detail += '<div class="tt-detail-grid">' +
        kv("Entered", esc(p.entry_date) + " on S" + p.system) +
        kv("First fill", money(p.entry)) +
        kv("Average fill", money(p.avg)) +
        kv("Units held", p.units + " of " + P.max_units) +
        kv("Stop (all units)", money(p.stop)) +
        kv("Next add at", p.next_add == null ? "full size" : money(p.next_add)) +
        kv("Exit on the " + p.exit_channel + "-day", money(p.exit_level)) +
        kv("Open", sgnR(p.open_r) + " &middot; " + p.bars + " bars") +
        "</div>";
    }
    if (rec.n) {
      detail += '<p class="tt-note">Under these rules over the last ' + esc(P.period) +
        ": <b>" + rec.n + "</b> closed trades, " + pct(rec.win_pct) + " won, <b class=\"" +
        cls(rec.total_r) + '">' + sgnR(rec.total_r) + "</b> total net of costs" +
        (rec.gross_r == null ? "" : " (" + sgnR(rec.gross_r) + " gross, " +
          sgnR(-Math.abs(rec.cost_r || 0)) + " cost)") +
        ", median trade " + sgnR(rec.median_r) +
        ", worst drawdown " + sgnR(rec.max_dd_r) +
        ". In-sample, survivor-biased, single-instrument — see EVIDENCE.</p>";
    } else {
      detail += '<p class="tt-note">No closed trades in the last ' + esc(P.period) + ".</p>";
    }
    return '<article class="tt-row is-open"' + attrs + ">" + head +
      '<div class="tt-detail">' + detail + "</div></article>";
  }

  const kv = (k, v) => '<div class="tt-kv"><span>' + k + '</span><b class="mono">' + v + "</b></div>";

  function signalsHTML() {
    if (!DATA) {
      return '<p class="tt-empty">No <code>' + esc(MARKET) + "_turtle.json</code> published yet. " +
        "The nightly scan writes it at 09:30 UTC; the rules, calculator and evidence " +
        "views need no data.</p>";
    }
    const rows = rowsFor();
    if (!rows.length) return '<p class="tt-empty">Nothing matches that filter today.</p>';
    return rows.map(rowHTML).join("") +
      (DATA.truncated ? '<p class="tt-note">' + big(DATA.truncated) +
        " further names passed the gates and are not listed — ranking is by " +
        "today's signal, then open positions, then proximity to a level.</p>" : "");
  }

  // ── view 3: SIZING ─────────────────────────────────────────────────────────
  function sizingHTML() {
    const n1 = 2.0, price = 100;
    const shares = unitShares(EQUITY, n1);
    const wsShares = unitShares(EQUITY, n1, P.whipsaw_risk_pct);
    return `
      <section class="tt-card">
        <h3>Your account</h3>
        <div class="tt-calc">
          <label>Account size
            <input id="tt-equity" type="number" min="0" step="100" value="${EQUITY}" />
          </label>
          <div class="tt-calc-out">
            <div class="tt-kv"><span>Risk per unit (${(P.risk_pct * 100).toFixed(0)}%)</span>
              <b class="mono">${money(P.risk_pct * EQUITY, 0)}</b></div>
            <div class="tt-kv"><span>One-unit ${P.stop_n}N stop-out</span>
              <b class="mono">${money(P.risk_pct * P.stop_n * EQUITY, 0)}</b></div>
            <div class="tt-kv"><span>Full ${P.max_units}-unit stop-out</span>
              <b class="mono">${money(0.05 * EQUITY, 0)}</b></div>
          </div>
        </div>
        <p class="tt-note">Everything on this page recomputes from that number. It is stored
        nowhere and sent nowhere.</p>
      </section>

      <section class="tt-card">
        <h3>Unit size at a glance</h3>
        <div class="tt-tablewrap"><table class="tt-table">
          <caption>Units of stock per unit, at ${money(EQUITY, 0)}. A big N buys fewer units — that is
          the whole idea.</caption>
          <thead><tr><th>N</th><th>N as % of a ${money(price, 0)} share</th><th>Units</th><th>Notional</th></tr></thead>
          <tbody>${[0.5, 1, 2, 3, 5, 8].map((n) => {
            const u = unitShares(EQUITY, n);
            return "<tr><td class=\"mono\">" + num(n) + '</td><td class="mono">' + pct(100 * n / price) +
              '</td><td class="mono">' + num(u, u < 10 ? 3 : 0) + '</td><td class="mono">' +
              money(u * price, 0) + "</td></tr>";
          }).join("")}</tbody></table></div>
      </section>

      <section class="tt-card">
        <h3>The pyramid, at your size</h3>
        ${ladderTableHTML(price, n1, "long")}
        <p class="tt-note">At ${money(EQUITY, 0)} with N = ${num(n1)}, each unit is
        ${num(shares, shares < 10 ? 3 : 0)} units of stock. Four of them is
        ${num(shares * P.max_units, shares < 10 ? 3 : 0)} units,
        ${money(shares * P.max_units * 101.5, 0)} of exposure, risking
        ${money(0.05 * EQUITY, 0)} to the shared stop.</p>
      </section>

      <section class="tt-card">
        <h3>The drawdown rule, at your size</h3>
        ${ddTableHTML(EQUITY)}
      </section>

      <section class="tt-card">
        <h3>The Whipsaw variant, side by side</h3>
        <div class="tt-tablewrap"><table class="tt-table">
          <thead><tr><th></th><th>Standard</th><th>Whipsaw</th></tr></thead><tbody>
          <tr><td>Risk per unit</td><td class="mono">${(P.risk_pct * 100).toFixed(1)}%</td>
              <td class="mono">${(P.whipsaw_risk_pct * 100).toFixed(1)}%</td></tr>
          <tr><td>Stop distance</td><td class="mono">${P.stop_n}N</td>
              <td class="mono">${P.whipsaw_stop_n}N</td></tr>
          <tr><td>Units at N = ${num(n1)}</td><td class="mono">${num(shares, 2)}</td>
              <td class="mono">${num(wsShares, 2)}</td></tr>
          <tr><td>Cost of one stop-out</td><td class="mono">${money(P.risk_pct * P.stop_n * EQUITY, 0)}</td>
              <td class="mono">${money(P.whipsaw_risk_pct * P.whipsaw_stop_n * EQUITY, 0)}</td></tr>
          <tr><td>Earlier stops raised on an add?</td><td>yes</td><td>no</td></tr>
          <tr><td>Re-entry after a stop</td><td>on the next breakout</td>
              <td>at the original breakout price, unlimited</td></tr>
        </tbody></table></div>
        <p class="tt-note">Nothing on the SIGNALS view computes Whipsaw levels — it uses the
        ${P.stop_n}N default the rules specify. This table is for comparison.</p>
      </section>

      <section class="tt-card">
        <h3>The position limits</h3>
        <div class="tt-detail-grid">
          ${kv("Per market", P.max_units + " units")}
          ${kv("Closely correlated", P.max_units_close_corr + " units")}
          ${kv("Loosely correlated", P.max_units_loose_corr + " units")}
          ${kv("Per direction", P.max_units_direction + " units")}
        </div>
        <p class="tt-note">At ${money(EQUITY, 0)}, a full ${P.max_units_direction}-unit book one way
        risks roughly ${money(P.max_units_direction * P.risk_pct * P.stop_n * EQUITY, 0)} if every
        position stops at once and no stop has been raised — which is the scenario the
        correlation limits exist for, and the one a sector-shaped book actually produces.</p>
      </section>`;
  }

  // What these rules actually did on THIS market, put first on the EVIDENCE
  // view because it is the only number on the page derived from real bars
  // rather than from the historical record of somebody else's program.
  function marketRecordHTML() {
    if (!DATA || !DATA.aggregate || !DATA.aggregate.trades) return "";
    const a = DATA.aggregate;
    const good = a.total_r > 0;
    return `
      <section class="tt-card">
        <h3>What these rules did on ${esc(MARKET.toUpperCase())} over ${esc(P.period)}</h3>
        <div class="tt-detail-grid">
          ${kv("Closed trades", big(a.trades))}
          ${kv("Win rate", pct(a.win_pct))}
          ${kv("Total, net of costs", '<span class="' + cls(a.total_r) + '">' + sgnR(a.total_r) + "</span>")}
          ${kv("Average trade", '<span class="' + cls(a.avg_r) + '">' + sgnR(a.avg_r) + "</span>")}
          ${kv("Gross, before costs", sgnR(a.avg_gross_r) + " avg")}
          ${kv("Names with a trade", big(a.names_with_trades) + " of " + big(a.names))}
        </div>
        <p class="tt-note">${good
          ? "Positive here does NOT mean positive as a strategy. Each name is replayed alone, with no position limits, no shared capital and no correlation, so summing the winners is not a book you could have run. And the universe is TODAY's listed names, so anything delisted over the window is missing — which on a fast-moving market selects hard for survivors."
          : "Negative, and worth sitting with rather than explaining away: it is thousands of trades of the real rules on real bars, after costs. It is also the honest reading of the structural point below — the Turtles ran ~20 uncorrelated futures with margin, and diversification is the mechanism that makes the expectancy positive, not a garnish on top of it."}</p>
      </section>`;
  }

  // ── view: THE BOOK ─────────────────────────────────────────────────────────
  // The forward record. This is the ONLY number on the page that will ever
  // mean what it appears to mean: the five-year replay's universe is today's
  // listed names, so it was selected on outcomes the system could not have
  // known, and no amount of waiting fixes that. This book started flat, takes
  // only what fires from the day it started, and pays costs.
  function bookHTML() {
    if (!BOOK) {
      return '<p class="tt-empty">The forward book has not been written yet. ' +
        "It is created by the first scan that runs after this feature shipped, " +
        "and it accumulates from there.</p>";
    }
    const s = BOOK.summary || {};
    const days = s.started ? Math.max(1, Math.round(
      (Date.now() - Date.parse(s.started)) / 864e5)) : 0;
    const mk = Object.keys(BOOK.by_market || {});
    const open = (BOOK.open || []).slice().sort(
      (a, b) => (b.fills || []).length - (a.fills || []).length);
    // If only SOME sleeves have a closed trade, the combined Total above is
    // numerically that sleeve's own number wearing a five-sleeve label --
    // exactly the "crypto cash -6.696R is one sleeve, not the combined
    // story" risk. Named generically from whichever sleeves actually have
    // closes, never hardcoded to crypto, so this stays true whichever
    // sleeve gets there first on a future night.
    const closedSleeves = mk.filter((m) => (BOOK.by_market[m] || {}).closed > 0);
    const singleSleeveNote = (closedSleeves.length && closedSleeves.length < mk.length)
      ? ` The combined Total above is carried entirely by
        <b>${closedSleeves.map((m) => esc(m.toUpperCase())).join(", ")}</b> — every other
        sleeve is still at zero closes, so one sleeve's record is not yet the combined
        book's record.`
      : "";

    // A symbol here is a BOOK fact, not a scan row -- clicking or Enter/
    // Space on it jumps to that symbol's market on SIGNALS with the row
    // expanded (jumpToBookSymbol, wired in mount()). scanMarketFor() maps a
    // levered sleeve key back to the scan that actually prices it, so this
    // never tries to load a BOOK-only key as a market.
    const openSymbolHTML = (symbol, market) =>
      '<span class="tt-link" tabindex="0" role="button" data-open-symbol="' +
      esc(symbol) + '" data-open-market="' + esc(scanMarketFor(market)) + '">' +
      esc(symbol) + "</span>";

    // Coin/contract QUANTITY (p.units, e.g. UNI 213.66) and Turtle UNIT
    // COUNT (p.fills.length, always 1-4) are different numbers that happen
    // to share a field name upstream. Phase A traced every renderer of a
    // BOOK position and found both existing ones (this row, and
    // bookOpenHTML's detail grid) already used fills.length for "u" --
    // correct, not a bug. What was missing is qty itself: it was nowhere
    // visible on this table at all, only recoverable by dividing
    // cost_basis by an unlabelled number in a different view. qtyStr keeps
    // more precision under 10 (a ZEC position is 1.2655, not "1"), because
    // the whole point of this column is to show the real number precisely.
    const qtyStr = (u) => (u == null ? "—" : u < 10 ? num(u, 4) : num(u, 2));

    const posRow = (p, levered) => {
      const sign = p.side === "short" ? -1 : 1;
      const avg = p.units ? p.cost_basis / p.units : 0;
      const r = (p.n && p.units) ? sign * (p.last_mark - avg) * p.units /
        (P.stop_n * p.n * p.units) : null;
      let row = "<tr><td class=\"mono\">" + openSymbolHTML(p.symbol, p.market) + "</td><td>" +
        esc((p.market || "").toUpperCase()) + "</td><td>" + esc(p.side) +
        " S" + esc(String(p.system)) + '</td><td class="mono">' +
        (p.fills || []).length + "u</td><td class=\"mono\">" + qtyStr(p.units) +
        "</td><td class=\"mono\">" + num(avg, 4) +
        '</td><td class="mono">' + num(p.stop, 4) +
        '</td><td class="mono">' + nextAddStr(p) + "</td>";
      if (levered) {
        const distR = liqDistanceR(p);
        row += '<td class="mono">' + (p.posted != null ? money(p.posted) : "—") +
          '</td><td class="mono">' + (distR != null ? num(distR, 2) + "R" : "—") + "</td>";
      }
      row += '<td class="mono ' + cls(r) + '">' + sgnR(r) + "</td><td>" + esc(p.opened) + "</td></tr>";
      return row;
    };

    // BOOK IS THE MONEY SURFACE (Phase 7): what is open and what just closed
    // are facts, and lead. By-market and skips are still fact, one level
    // more aggregated. The headline essay and the portfolio replay are
    // context FOR reading those facts, not the facts themselves, so both
    // now read last rather than first.
    let h = "";

    if (open.length) {
      // Two table SHAPES, not one table with blank columns (Phase C): a
      // cash row drawn with empty Posted/Liq cells reads as "almost
      // levered", which is the exact confusion this split avoids. Split is
      // by leverageOf(p.market), read from params -- never a market-name
      // check -- so this holds however many levered sleeves ever exist.
      const openCash = open.filter((p) => !leverageOf(p.market));
      const openLevered = open.filter((p) => leverageOf(p.market));
      const anyFutures = open.some((p) => p.market === "futures");
      if (openCash.length) {
        h += `<section class="tt-card"><h3>Open positions</h3>
          <div class="tt-tablewrap"><table class="tt-table">
          <thead><tr><th>Symbol</th><th>Market</th><th>Side</th><th>Units</th><th>Qty</th>
          <th>Avg fill</th><th>Stop</th><th>Next add</th><th>Open R</th><th>Since</th></tr></thead>
          <tbody>${openCash.map((p) => posRow(p, false)).join("")}</tbody></table></div>
          <p class="tt-note">"Units" is the Turtle pyramid count (1-4, one add per
          ${P.pyramid_step_n}N); "Qty" is the actual coin or share count that count
          was built from. One shared stop per position, ${P.stop_n}N under the most
          recent unit. "Next add" is the next ${P.pyramid_step_n}N pyramid level from
          the last fill -- not a fill that has happened, and not a call into the
          book's own math -- reading "max units" once all ${P.max_units} fills are
          already in. On the equity and crypto books the cash constraint binds
          fast, because at ${(P.risk_pct * 100).toFixed(0)}% risk per N a single unit
          routinely costs a quarter to a half of a ${money(s.equity_start, 0)} account.
          That is exactly the leverage the Turtles had from futures margin and a
          cash account does not.</p>
          ${anyFutures ? `<p class="tt-note tt-warn-note"><b>Futures positions here are
          NOT constrained by cash.</b> A futures position consumes margin, not
          notional, and this repo has no margin data — so the only ceilings on the
          futures book are the unit caps (${P.max_units} per market,
          ${P.max_units_close_corr} correlated, ${P.max_units_direction} per
          direction) and the refusal to hold less than one contract. Do not read a
          futures sleeve that "fits" in ${money(s.equity_start, 0)} as evidence it
          would fit: the notional behind those contracts is many multiples of the
          account, and the leverage was never priced. It is disclosed rather than
          modelled because a fabricated margin number would be worse than an
          absent one.</p>` : ""}</section>`;
      }
      if (openLevered.length) {
        h += `<section class="tt-card"><h3>Open positions — levered sleeve</h3>
          <div class="tt-tablewrap"><table class="tt-table">
          <thead><tr><th>Symbol</th><th>Market</th><th>Side</th><th>Units</th><th>Qty</th>
          <th>Avg fill</th><th>Stop</th><th>Next add</th><th>Posted</th><th>Liq dist.</th>
          <th>Open R</th><th>Since</th></tr></thead>
          <tbody>${openLevered.map((p) => posRow(p, true)).join("")}</tbody></table></div>
          <p class="tt-note">Posted is the margin actually at risk on this position
          (notional/leverage, isolated). Liq dist. is how far price sits from the
          line where posted margin runs out, in the same ${P.stop_n}N unit the stop
          uses — a stop and a liquidation are different exits, and whichever is
          nearer fires first. A blank cell here means a required field is missing
          on that row, never a guessed number.</p></section>`;
      }
    }

    const closed = (BOOK.closed || []).slice(-25).reverse();
    if (closed.length) {
      h += `<section class="tt-card"><h3>Closed, most recent first</h3>
        <div class="tt-tablewrap"><table class="tt-table">
        <thead><tr><th>Symbol</th><th>Side</th><th>Reason</th><th>R</th>
        <th>P&amp;L</th><th>Fees</th><th>Opened</th><th>Closed</th></tr></thead>
        <tbody>${closed.map((t) => "<tr><td class=\"mono\">" + esc(t.symbol) +
          "</td><td>" + esc(t.side) + "</td><td>" + esc(t.reason) +
          '</td><td class="mono ' + cls(t.r) + '">' + sgnR(t.r) +
          '</td><td class="mono ' + cls(t.pnl) + '">' + money(t.pnl) +
          '</td><td class="mono">' + money(t.fees) + "</td><td>" + esc(t.opened) +
          "</td><td>" + esc(t.closed) + "</td></tr>").join("")}
        </tbody></table></div></section>`;
    }

    if (mk.length) {
      // A levered sleeve travels with its own params (turtle_book stamps
      // them), and the disclosure below renders FROM those params -- this
      // page cannot describe a 5x book the engine is not running.
      const lev5 = mk.map((m) => [m, (BOOK.by_market[m] || {}).params])
        .find(([, p]) => p && p.leverage > 1);
      // The correlated-group cap number in the note below is READ from the
      // skip rows' own units_on_book/cap (Phase C) -- never the literal 6 --
      // and only appears at all if a close_corr_cap skip against this
      // sleeve actually exists to derive it from.
      const capBind = (() => {
        if (!lev5) return null;
        const hits = (BOOK.skips || []).filter((k) =>
          k.reason === "close_corr_cap" && k.market === lev5[0]);
        if (!hits.length) return null;
        const worst = hits.reduce((a, b) =>
          (b.units_on_book || 0) > (a.units_on_book || 0) ? b : a, hits[0]);
        return (worst.units_on_book == null || worst.cap == null) ? null :
          { on: worst.units_on_book, cap: worst.cap, n: hits.length };
      })();
      h += `<section class="tt-card"><h3>By market</h3>
        <div class="tt-tablewrap"><table class="tt-table">
        <thead><tr><th>Market</th><th>Vehicle</th><th>Equity</th><th>Open</th><th>Closed</th><th>Total R</th></tr></thead>
        <tbody>${mk.map((m) => {
          const b = BOOK.by_market[m] || {};
          const margins = b.params && b.params.leverage > 1 &&
            b.posted_margin != null && b.free_margin != null
            ? " (" + money(b.posted_margin, 0) + " posted, " + money(b.free_margin, 0) + " free)"
            : "";
          const veh = b.params && b.params.leverage > 1
            ? big(b.params.leverage) + "&times; margin" + margins : "cash";
          return "<tr><td>" + esc(m.toUpperCase()) + "</td><td>" + veh +
            '</td><td class="mono">' +
            money(b.equity) + '</td><td class="mono">' + big(b.open_positions) +
            '</td><td class="mono">' + big(b.closed) + '</td><td class="mono ' +
            cls(b.total_r) + '">' + sgnR(b.total_r) + "</td></tr>";
        }).join("")}</tbody></table></div>
        ${lev5 ? `<p class="tt-note"><b>${esc(lev5[0].toUpperCase())} is
        ${big(lev5[1].leverage)}&times; posted margin</b> (notional/${big(lev5[1].leverage)},
        ${esc(lev5[1].margin_mode || "isolated")}) — a perp analogue, <b>not</b> Dennis's
        futures IM. The unit is still ${(P.risk_pct * 100).toFixed(0)}% of equity
        per N; what changes is only what a unit COSTS to hold. A position whose
        adverse move consumes its posted margin is closed as
        <b>liquidation</b>, at the liquidation price — isolated margin cannot
        lose more than it posted. It is a NEW series beside the cash crypto
        book, never a restatement of it.${capBind ? ` The correlated-group cap is
        <b>binding, not the margin</b>: <b>${big(capBind.on)}/${big(capBind.cap)}</b>
        crypto units already held is why further adds and new names are being
        declined tonight (see Not taken, and why, below) while margin itself
        still has room. Filling the cap on day one is the system saying "this
        is one correlated bet", not a shortage of money.` : ""}</p>` : ""}</section>`;
    }

    // NOT TAKEN, AND WHY. A book that quietly declines half its signals looks
    // identical to one that had no signals, and which ceiling is binding is
    // the whole story -- especially at $5,000, where cash binds long before
    // any Turtle rule does.
    const skips = BOOK.skips || [];
    // Cash-skip dollars, latest bar only (Phase D): computed here, ahead of
    // the skip board itself, so the SAME sentence can also reach the
    // combined card below rather than being recomputed (and risking
    // drifting) a second time. Restricted to the latest as_of so a re-run
    // mid-session can never double count across bars. want_notional is
    // summed only where the row actually carries it -- partial-data
    // honesty: a skip missing the field is counted into "N skips" but never
    // guessed into the dollar total, and the gap is stated rather than
    // hidden.
    const latestAsOf = skips.reduce((mx, k) => (k.as_of && (!mx || k.as_of > mx) ? k.as_of : mx), null);
    const cashToday = skips.filter((k) => k.reason === "cash" && k.as_of === latestAsOf);
    const cashTodayPriced = cashToday.filter((k) => k.want_notional != null);
    const cashMarkets = new Set(cashToday.map((k) => k.market));
    const cashSkipSentence = cashToday.length
      ? big(cashToday.length) + " cash skip" + (cashToday.length === 1 ? "" : "s") +
        " on " + esc(latestAsOf) + " across " + big(cashMarkets.size) +
        " book" + (cashMarkets.size === 1 ? "" : "s") + ": " +
        money(cashTodayPriced.reduce((sum, k) => sum + k.want_notional, 0), 0) +
        " notional the cash book" + (cashMarkets.size === 1 ? "" : "s") + " refused" +
        (cashTodayPriced.length < cashToday.length
          ? " (" + big(cashToday.length - cashTodayPriced.length) + " more without a notional figure on the row)"
          : "") + "."
      : "";
    if (skips.length) {
      const WHY = {
        direction_cap: "12-unit one-way ceiling",
        close_corr_cap: "6-unit correlated-group ceiling",
        loose_corr_cap: "10-unit loose-correlation ceiling",
        per_market_cap: "4-unit per-name ceiling",
        cash: "no cash — a unit would exceed the account",
        no_margin: "no free margin for the posted amount",
        unit_lt_one: "a unit is less than one contract",
        no_margin_file: "no real margin data — futures opens are OFF",
        roll_window: "a roll suspect sits in today's N window",
        same_bar_reentry: "exited on this bar — waiting for a NEW break",
        s1_skip_after_win: "System 1 filter: the last breakout won",
      };
      // Short forms for the one-line summary (Phase C) -- same reasons,
      // compact enough for a sentence rather than a detail grid.
      const SHORT_WHY = {
        direction_cap: "direction (cap binding)", close_corr_cap: "close-corr (cap binding)",
        loose_corr_cap: "loose-corr (cap binding)", per_market_cap: "per-name (cap binding)",
        cash: "cash", no_margin: "no margin", unit_lt_one: "unit < 1 contract",
        no_margin_file: "no margin file", roll_window: "roll suspect",
        same_bar_reentry: "same-bar re-entry", s1_skip_after_win: "S1 filtered",
      };
      const counts = BOOK.skip_counts || {};
      const byReason = Object.keys(counts).filter((k) => k !== "total")
        .sort((a, b) => counts[b] - counts[a]);
      const summaryLine = big(counts.total || 0) + " skips: " +
        byReason.map((r) => big(counts[r]) + " " + esc(SHORT_WHY[r] || r)).join(" · ");
      // Dedup by symbol x reason x action, with a count (Phase C): a name
      // skipped for the same reason across the crypto book's 4-hourly
      // reruns should read as one row with a count, not N near-identical
      // ones. Zero duplicates exist as of tonight's single run -- this is
      // for the night that does accumulate them, not a fix for tonight.
      const dedup = new Map();
      skips.forEach((k) => {
        const key = (k.symbol || "") + "|" + (k.reason || "") + "|" + (k.action || "");
        const existing = dedup.get(key);
        if (existing) existing.n += 1; else dedup.set(key, Object.assign({ n: 1 }, k));
      });
      // Tonight's actual readability problem was never duplication -- it
      // was ORDER. The scan writes skips market-by-market (asx first), so
      // the old raw slice(0,40) showed 40 ASX cash rows and never reached
      // the 12 close_corr_cap ones at all. Sort by how RARE the reason is
      // (ascending count) so the structural, diagnostic reasons surface
      // before the numerous cash ones, which the sentence above already
      // summarises on their own.
      const rows = Array.from(dedup.values()).sort((a, b) =>
        (counts[a.reason] || 0) - (counts[b.reason] || 0) ||
        (a.symbol || "").localeCompare(b.symbol || ""));
      // "Would this fit on the levered sleeve" (Phase D): a display
      // comparison only, never an order and never a hint to retune
      // anything. Renders ONLY where the skip is a cash skip carrying
      // want_notional AND a levered sibling of its market actually exists
      // in by_market -- found via scanMarketFor's own suffix rule, in
      // reverse, so no sleeve key is ever spelled out literally here, and
      // this simply produces nothing for a market with no levered sibling.
      const fitsOnLeveredHTML = (k) => {
        if (k.reason !== "cash" || k.want_notional == null) return "";
        const levMarket = mk.find((m) => m !== k.market && scanMarketFor(m) === k.market &&
          ((BOOK.by_market[m] || {}).params || {}).leverage > 1);
        if (!levMarket) return "";
        const b = BOOK.by_market[levMarket];
        const lev = b.params.leverage;
        if (b.free_margin == null) return "";
        const posted = k.want_notional / lev;
        const fits = posted <= b.free_margin;
        return ' <span class="tt-chip' + (fits ? "" : " is-blocked") + '" title="' +
          big(lev) + '&times; posted would be ' + money(posted, 0) + ' vs ' +
          money(b.free_margin, 0) + ' free on ' + esc(levMarket.toUpperCase()) + '">' +
          (fits ? "fits on " : "would not fit on ") + big(lev) + '&times;</span>';
      };
      h += `<section class="tt-card" id="tt-skips"><h3>Not taken, and why</h3>
        <p class="tt-note">${esc(summaryLine)}</p>
        <div class="tt-detail-grid">${byReason.map((r) =>
          kv(esc(WHY[r] || r), big(counts[r]))).join("")}</div>
        <div class="tt-tablewrap"><table class="tt-table">
        <thead><tr><th>Symbol</th><th>Market</th><th>Action</th><th>Reason</th><th>Detail</th></tr></thead>
        <tbody>${rows.slice(0, 40).map((k) => {
          const d = [];
          if (k.units_on_book != null) d.push(k.units_on_book + " on book vs cap " + k.cap);
          if (k.units_held != null && k.units_on_book == null) d.push(k.units_held + " units held");
          if (k.want_notional != null) d.push("wanted " + money(k.want_notional, 0));
          if (k.posted_want != null) d.push("posted " + money(k.posted_want, 0) + " wanted");
          if (k.need_im != null) d.push("IM " + money(k.need_im, 0) + " vs free " + money(k.free, 0));
          if (k.one_contract_risk_pct != null) d.push("one contract = " + pct(k.one_contract_risk_pct) + " of the account");
          if (k.bucket) d.push(esc(k.bucket));
          if (k.bar) d.push("bar " + esc(k.bar));
          return "<tr><td class=\"mono\">" + openSymbolHTML(k.symbol, k.market) + "</td><td>" +
            esc((k.market || "").toUpperCase()) + "</td><td>" + esc(k.action) +
            (k.n > 1 ? " &times;" + big(k.n) : "") +
            "</td><td>" + esc(WHY[k.reason] || k.reason) + '</td><td class="mono">' +
            esc(d.join(" · ")) + fitsOnLeveredHTML(k) + "</td></tr>";
        }).join("")}</tbody></table></div>
        <p class="tt-note">These are decisions, not failures, and not one story.
        ${counts.cash ? `The <b>${big(counts.cash)} cash</b> skips are the CASH
        books refusing a unit that would exceed their account — see Equity in
        By market, above; that is the futures-margin gap those sleeves do not
        have.` : ""}
        ${counts.close_corr_cap ? `The <b>${big(counts.close_corr_cap)}
        close-corr</b> skips are a DIFFERENT sleeve hitting its own
        correlated-unit cap with margin still free — a structural limit doing
        its job, not a shortage of money. Reading the two as one story
        misreads both.` : ""}</p></section>`;
    }

    h += `
      <section class="tt-card">
        <h3>The forward book — the only honest number here</h3>
        <div class="tt-detail-grid">
          ${kv("Running since", esc(s.started || "—") + (days ? " (" + days + "d)" : ""))}
          ${kv("Equity", money(s.equity) + " of " + money(s.equity_start))}
          ${kv("Return", (s.return_pct == null ? "—" :
            '<span class="' + cls(s.return_pct) + '">' + pct(s.return_pct, 2) + "</span>"))}
          ${kv("Open", big(s.open_positions) + " positions / " + big(s.open_units) + " units")}
          ${kv("Closed", big(s.closed) + (s.win_pct == null ? "" : " · " + pct(s.win_pct) + " won"))}
          ${kv("Total", '<span class="' + cls(s.total_r) + '">' + sgnR(s.total_r) + "</span>")}
          ${kv("Average trade", sgnR(s.avg_r))}
          ${kv("Median trade", sgnR(s.median_r))}
          ${kv("Fees paid", money(s.fees_paid))}
          ${kv("Sizing off", money(s.sizing_equity))}
        </div>
        <p class="tt-note">${s.closed
          ? "Small samples say very little. A trend system's result is carried by a handful of trades, so read the MEDIAN beside the average and treat anything under a few dozen closes as noise."
          : "Nothing has closed yet, so there is no result to read. That is the honest state of a forward test on day " + days + " — it cannot be hurried, and it is the reason the five-year replay exists as context rather than as evidence."}
        <b>A first print is a print, not evidence</b>: no sleeve's record means
        anything until it holds at least 30 closed trades AND 20 trading days.
        Five same-day stops are a verdict on the VEHICLE, not on expectancy.</p>
        <p class="tt-note">Equity here is <b>realised only</b> — open positions are
        not marked into the headline. This is <b>${mk.length} separate sleeve${mk.length === 1 ? "" : "s"}, not one account</b>
        — one book per market, own equity, own slot pool.${mk.length > 1 ? ` ${money(s.equity_start, 0)}
        start is ${mk.length} sleeves of about ${money(s.equity_start / mk.length, 0)} each, not
        one bigger bet.` : ""} The combined
        figures add A$ and US$ <b>at face value</b> (no FX conversion): read
        the per-market rows for anything you would act on. The crypto books run
        every four hours, but the BARS are daily — the cron is a scan cadence, not a four-hour Donchian.${singleSleeveNote}</p>
        ${cashSkipSentence ? `<p class="tt-note">${esc(cashSkipSentence)} That is universe the
        cash books can SEE but not size at their own equity -- see Not taken, and
        why, below for which of it would fit a levered sleeve instead.</p>` : ""}
</section>`;

    // The five-year portfolio replay, LAST: context for reading the facts
    // above, not a verdict on them -- portfolioCardHTML() itself already
    // avoids "does this work" framing. Same unmodified function EVIDENCE
    // has always called; BOOK gets a second call site, not a copy.
    h += portfolioCardHTML();

    return h;
  }

  // ── view 4: EVIDENCE ───────────────────────────────────────────────────────
  // The shared-equity portfolio replay: the per-name records above replay
  // every name with its own private equity, so they cannot answer "would
  // $5,000 have made money". This card renders the one surface that can ask
  // that question honestly -- and it renders the payload's OWN caveat, so
  // the page cannot oversell what the file itself refuses to claim.
  function portfolioCardHTML() {
    if (!PORTFOLIO || !PORTFOLIO.sleeves) return "";
    const names = Object.keys(PORTFOLIO.sleeves).sort();
    if (!names.length) return "";
    const rows = names.map((k) => {
      const v = PORTFOLIO.sleeves[k] || {};
      const ref = v.refused_units || {};
      const refTop = Object.keys(ref).sort((a, b) => ref[b] - ref[a])
        .slice(0, 2).map((r) => esc(r) + " " + big(ref[r])).join(" · ");
      return "<tr><td class=\"mono\">" + esc(k) + '</td><td class="mono">' +
        money(v.equity_start, 0) + (v.leverage > 1 ? " @" + big(v.leverage) + "&times;" : "") +
        '</td><td class="mono">' + big(v.trades) + '</td><td class="mono ' +
        cls(v.return_pct_marked) + '">' + pct(v.return_pct_marked) +
        '</td><td class="mono">' + pct(v.max_dd_pct_marked) +
        '</td><td class="mono">' + sgnR(v.median_r) + "</td><td>" +
        (refTop || "—") + "</td></tr>";
    }).join("");
    return `<section class="tt-card">
      <h3>The portfolio replay — one shared equity per sleeve</h3>
      <div class="tt-tablewrap"><table class="tt-table">
      <thead><tr><th>Sleeve</th><th>Start</th><th>Trades</th><th>Return</th>
      <th>Max DD</th><th>Median R</th><th>Top refusals</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
      <p class="tt-note">${esc(PORTFOLIO.caveat || "")} Ordering:
      ${esc(PORTFOLIO.ordering || "")}.</p>
    </section>`;
  }

  function evidenceHTML() {
    const start = EQUITY, target = 10e6;
    const mult = target / start;
    const rates = [0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.80, 1.00];
    const rows = rates.map((r) => {
      const y = yearsTo(mult, r);
      return "<tr><td class=\"mono\">" + (r * 100).toFixed(0) + '%</td><td class="mono">' +
        y.toFixed(1) + "</td><td>" + (r >= 0.8 ? "at the Turtles' reported average" :
          r >= 0.3 ? "an exceptional professional record" : "a very good one") + "</td></tr>";
    }).join("");

    return marketRecordHTML() + `
      <section class="tt-card">
        <h3>The headline number, as arithmetic</h3>
        <p>Turning ${money(start, 0)} into ${money(target, 0)} is a
        <b>${big(mult)}&times;</b> compounding, which is
        <b>${Math.log(mult).toFixed(2)}</b> natural logs. Years required, at a constant rate and
        with nothing withdrawn:</p>
        <div class="tt-tablewrap"><table class="tt-table">
          <thead><tr><th>Annual return</th><th>Years to ${money(target, 0)}</th><th></th></tr></thead>
          <tbody>${rows}</tbody></table></div>
        <p class="tt-note">Change the account size on the SIZING view and this table follows it.
        Note what it does not include: tax, withdrawals, a single losing year, and the fact
        that position size at ${money(target, 0)} runs into liquidity limits the Turtles hit
        for real — Dennis stopped trading grains because he was already at exchange position
        limits in them.</p>
      </section>

      <section class="tt-card">
        <h3>What actually happened, including the part usually left out</h3>
        <ul class="tt-facts">
          <li><b>The Turtles:</b> roughly <b>80% average annual compound return</b> across the
          1984&ndash;88 program, with combined profits reported between $100M and $175M. None of
          it is publicly audited, and it is <b>survivorship-biased</b> — traders who performed
          badly were cut from the program.</li>
          <li><b>Richard Dennis:</b> reportedly turned about $1,600 into roughly $200M over about
          ten years, and made about $80M in 1986 alone. Also unaudited.</li>
          <li><b>The drawdowns:</b> Dennis was <b>down about 55% by April 1988</b> and shut the
          program down. He lost more than half his assets across 1987&ndash;88, about $50M.
          30&ndash;50% peak-to-trough drawdowns were <b>routine</b> for individual Turtles, not
          exceptional. System testing of the two systems blended produced a worst case nearer
          <b>&minus;80%</b> than the &minus;50% expected.</li>
          <li><b>The window:</b> 1984&ndash;88 contained an extraordinary run of trends — the
          dollar's collapse after the 1985 Plaza Accord, the 1987 bond and equity moves. Donchian
          breakout performance degraded markedly from the late 1980s as the approach spread.
          Jerry Parker's Chesapeake, founded 1988, is the longest live continuation and has
          compounded at a small fraction of 80%.</li>
        </ul>
        <p class="tt-note">Stated plainly: an 80% return with 50&ndash;80% drawdowns is not a safe
        system. It is a high-variance system, run at institutional size, with a de-gearing rule,
        by traders funded with someone else's money and screened for the temperament to hold
        through it.</p>
      </section>

      <section class="tt-card">
        <h3>What this build replicates — and what it cannot</h3>
        <table class="tt-table"><thead><tr><th></th><th>Here</th></tr></thead><tbody>
          <tr><td>N, the channels, the ${P.stop_n}N stop, the ${P.pyramid_step_n}N pyramid and its stop raise</td>
              <td class="tt-yes">implemented exactly</td></tr>
          <tr><td>The System 1 filter and the ${P.s2_entry}-day failsafe</td>
              <td class="tt-yes">implemented exactly</td></tr>
          <tr><td>Unit sizing and the drawdown rule</td>
              <td class="tt-yes">computed, on the SIZING view</td></tr>
          <tr><td>The correlation and direction limits</td>
              <td class="tt-part">stated, not enforced — there is no correlation matrix here</td></tr>
          <tr><td>The market portfolio</td>
              <td class="tt-no">the Turtles traded ~20 liquid futures across currencies, rates,
              metals, energy and softs. This scans ASX and NASDAQ equities and crypto —
              plus a fixed futures sleeve on continuous <code>=F</code> series
              (its caveats are the card below).</td></tr>
          <tr><td>Leverage</td>
              <td class="tt-no">futures margin is what made 1% risk per unit across 12 units
              possible on a cash account. Equities do not offer it on the same terms.</td></tr>
          <tr><td>Intraday execution</td>
              <td class="tt-part">the replay fills at the breakout level or the open, whichever is
              worse. Real resting stop orders would fill at the level, plus slippage.</td></tr>
        </tbody></table>
        <p class="tt-note"><b>The market list is not a detail.</b> The Turtle return distribution is
        extremely fat-tailed: a handful of trades in a handful of markets produce nearly all the
        profit, and there is no way to know in advance which. Diversification across uncorrelated
        markets is the mechanism that makes the expectancy positive, not a garnish on top of it.
        A Turtle system run on one instrument, or on a set of names that all move with the same
        index, is a materially different and worse strategy — whatever the rules on the page say.</p>
      </section>

      <section class="tt-card">
        <h3>The futures sleeve, plainly</h3>
        <ul class="tt-facts">
          <li><b>The scan's stamp is one session, not seven.</b> The futures job
          runs at 23:00 UTC on weekdays — after the 17:00 ET CME Globex daily
          break that ends the <b>equity-index</b> session. FX and metals trade
          nearly 24 hours and WTI crude settles at 14:30 ET, so "after the
          close" is literally true only for the index group: every contract's
          daily bar is the feed's calendar-day bar for the full electronic
          session, read as of that one stamp, not each market's own settlement
          window.</li>
          <li><b>The publish gate on this sleeve is absolute, not a share.</b>
          The equity markets refuse to publish below ${pct(P.min_coverage_pct, 0)}
          of their universe — a rule sized for a 2,000-name directory that would
          pass this fixed table with a third of its contracts missing. So a
          universe of ${P.small_universe_max} names or fewer refuses to publish
          when more than ${P.small_universe_max_missing} contracts return no
          usable bars: yesterday's file stands, and every missing contract is
          named in the payload rather than counted, because each absence here is
          an asset group. The equity markets keep their own
          ${pct(P.min_coverage_pct, 0)} floor unchanged.</li>
          <li><b>The price series is a continuous, back-adjusted
          <code>=F</code> chain</b> — sound for channel and N arithmetic, not a
          tradeable instrument. The roll caveat on each SIGNALS row is the
          per-name disclosure; nothing here re-derives it.</li>
        </ul>
      </section>

      ${portfolioCardHTML()}

      <section class="tt-card">
        <h3>How to read the per-name records on the SIGNALS view</h3>
        <p>Every row's record is a replay of these rules over the last ${esc(P.period)} of that name's
        own bars. Four things it is not:</p>
        <ul class="tt-facts">
          <li><b>Out of sample.</b> It is the same history the rules are being displayed against.</li>
          <li><b>Survivor-free.</b> The universe is today's listed names, so anything delisted over
          the window is missing, and delistings are not random.</li>
          <li><b>A portfolio.</b> Each name is replayed alone with no position limits, no shared
          capital and no correlation. Summing the winners is not a strategy you could have run.</li>
          <li><b>A ranking.</b> The list is deliberately ordered by what is actionable today —
          signal, then open position, then proximity — and never by the record, because sorting a
          scanner by its own backtest is how a page becomes a curve fit.</li>
        </ul>
      </section>`;
  }

  // ── shell ──────────────────────────────────────────────────────────────────
  const VIEWS = [
    ["signals", "SIGNALS"], ["book", "BOOK"], ["rules", "THE RULES"],
    ["sizing", "SIZING"], ["evidence", "EVIDENCE"],
  ];

  function render() {
    // The market switcher is static markup in turtle.html (ASX hardcoded
    // is-active) and, unlike the deck/tabs/controls below, is never rebuilt
    // from scratch -- only imperatively toggled. Before Phase 3 that was
    // harmless because MARKET could only ever change via the button that
    // owns this exact toggle. A deep link or a popstate can now set MARKET
    // to anything before this first runs, so render() has to own it too.
    syncMarketButtons();
    const deck = document.getElementById("tt-deck");
    if (deck) deck.innerHTML = deckHTML();
    const tabs = document.getElementById("tt-views");
    if (tabs) {
      tabs.innerHTML = VIEWS.map(([k, label]) =>
        '<button class="view-tab' + (VIEW === k ? " is-active" : "") + '" data-view="' +
        k + '">' + label + "</button>").join("");
    }
    const ctl = document.getElementById("tt-controls");
    if (ctl) {
      ctl.hidden = VIEW !== "signals";
      if (VIEW === "signals") {
        // Same five buckets, same order as deckPillsHTML() above -- "Active
        // pill === active seg" is a promise about POSITION as well as state.
        const counts = filterCounts() || { fired: 0, held: 0, near: 0, blocked: 0, all: 0 };
        ctl.innerHTML = '<div class="control-group"><div class="seg" role="group" aria-label="Filter">' +
          [["fired", "FIRED TODAY"], ["held", "IN A POSITION"], ["near", "APPROACHING"],
            ["blocked", "S1 BLOCKED"], ["all", "ALL"]]
            .map(([k, l]) => '<button class="seg-btn' + (FILTER === k ? " is-active" : "") +
              '" data-filter="' + k + '">' + l + ' <span class="seg-count">' + big(counts[k]) +
              "</span></button>").join("") +
          "</div></div>" +
          '<div class="control-group"><button type="button" class="seg-btn" data-sort-cycle="1" ' +
          'title="Cycle sort: FIRED, DISTANCE, N, SYMBOL">SORT ' + SORT_LABELS[SORT] +
          "</button></div>" +
          '<input class="pm-search" id="tt-search" type="search" placeholder="Ticker…" ' +
          'autocomplete="off" spellcheck="false" value="' + esc(QUERY) + '" />';
      }
    }
    const body = document.getElementById("tt-body");
    if (!body) return;
    body.innerHTML = VIEW === "rules" ? rulesHTML()
      : VIEW === "signals" ? signalsHTML()
      : VIEW === "book" ? bookHTML()
      : VIEW === "sizing" ? sizingHTML()
      : evidenceHTML();
    const eq = document.getElementById("tt-equity");
    if (eq) {
      eq.addEventListener("change", () => {
        const v = parseFloat(eq.value);
        if (isFinite(v) && v > 0) { EQUITY = v; render(); }
      });
    }
    const search = document.getElementById("tt-search");
    if (search) {
      search.addEventListener("input", () => { QUERY = search.value.trim(); renderBody(); });
    }
  }

  function renderBody() {
    const body = document.getElementById("tt-body");
    if (body && VIEW === "signals") body.innerHTML = signalsHTML();
  }

  // ── URL state (Phase 2 of the UI runbook — helpers only) ───────────────────
  // Back/forward is a data contract, so it is written and tested before any
  // click is wired to it — wire the clicks first and you "test" by eye and
  // miss the hostile symbol. Nothing below reads or writes the DOM, touches
  // history.pushState/popstate, or is called from mount() yet; that wiring is
  // Phase 3. Both functions are pure and MUST NEVER THROW: unknown, missing,
  // or malformed input always resolves to the defaults below, and a caller
  // can never push an invalid value into the address bar.
  const URL_MARKETS = ["asx", "nasdaq", "crypto", "futures"];
  const URL_VIEWS = ["signals", "book", "rules", "sizing", "evidence"];
  const URL_FILTERS = ["all", "fired", "held", "near", "blocked"];
  const URL_SORTS = ["fired", "distance", "n", "symbol"];
  const URL_DEFAULTS = { m: "asx", v: "signals", f: "fired", s: "", sort: "fired" };

  // search: a location.search-shaped string ("?m=nasdaq&v=book", the same
  // without the leading "?", "", null, undefined, or garbage of any type).
  // Returns a plain {m,v,f,s,sort} object. s is free text (an expanded
  // symbol, or "" if none) — URLSearchParams decodes it for us, so any
  // decoded value, including one carrying a quote, a bracket, or an
  // ampersand, is accepted as-is; every other field is checked against its
  // allowed list above and falls back to the default if it is missing,
  // misspelled, or hostile. Extra query keys (?debug=1 etc.) are read from
  // and never copied onto the result, so a parse -> serialise round trip
  // always drops them rather than resurrecting them inconsistently.
  function parseTurtleURL(search) {
    const out = Object.assign({}, URL_DEFAULTS);
    try {
      const params = new URLSearchParams(search || "");
      const m = params.get("m");
      const v = params.get("v");
      const f = params.get("f");
      const sort = params.get("sort");
      const s = params.get("s");
      if (URL_MARKETS.indexOf(m) !== -1) out.m = m;
      if (URL_VIEWS.indexOf(v) !== -1) out.v = v;
      if (URL_FILTERS.indexOf(f) !== -1) out.f = f;
      if (URL_SORTS.indexOf(sort) !== -1) out.sort = sort;
      if (s != null) out.s = s;
      return out;
    } catch (_) {
      // A hostile or exotic `search` (e.g. a bare Symbol, which throws on
      // implicit ToString) must default cleanly rather than crash the page.
      return Object.assign({}, URL_DEFAULTS);
    }
  }

  // state: a {m,v,f,s,sort} object — typically parseTurtleURL's own output,
  // or a UI-derived equivalent once Phase 3 wires this up. Same allowed
  // lists and the same never-throw, garbage-defaults contract as the parser,
  // applied independently per field. Hostile s is escaped with
  // encodeURIComponent so it round-trips through URLSearchParams' decoding
  // on the way back in; an empty s is omitted entirely rather than
  // serialised as a bare "&s=".
  function serialiseTurtleURL(state) {
    try {
      const st = state || {};
      const m = URL_MARKETS.indexOf(st.m) !== -1 ? st.m : URL_DEFAULTS.m;
      const v = URL_VIEWS.indexOf(st.v) !== -1 ? st.v : URL_DEFAULTS.v;
      const f = URL_FILTERS.indexOf(st.f) !== -1 ? st.f : URL_DEFAULTS.f;
      const sort = URL_SORTS.indexOf(st.sort) !== -1 ? st.sort : URL_DEFAULTS.sort;
      const s = st.s == null ? "" : String(st.s);
      const parts = [
        "m=" + encodeURIComponent(m),
        "v=" + encodeURIComponent(v),
        "f=" + encodeURIComponent(f),
      ];
      if (s !== "") parts.push("s=" + encodeURIComponent(s));
      parts.push("sort=" + encodeURIComponent(sort));
      return "?" + parts.join("&");
    } catch (_) {
      return "?m=" + URL_DEFAULTS.m + "&v=" + URL_DEFAULTS.v + "&f=" + URL_DEFAULTS.f +
        "&sort=" + URL_DEFAULTS.sort;
    }
  }

  // ── URL state wiring (Phase 3) ──────────────────────────────────────────
  // window.history / window.location are used explicitly below, never the
  // bare globals -- this file runs both in a real browser and inside
  // test/turtle.test.js's synthetic window, and only the injected `window`
  // parameter exists in the latter.

  // The live app state, shaped like the URL contract plus one field the URL
  // itself never carries (touched). Not itself the {m,v,f,s,sort} contract
  // parseTurtleURL/serialiseTurtleURL exchange -- read this, then pass it
  // through serialiseTurtleURL, when you need the URL string.
  function getTurtleState() {
    return { m: MARKET, v: VIEW, f: FILTER, s: OPEN || "", sort: SORT, touched: TOUCHED };
  }

  // parsed: parseTurtleURL's own output shape. Sets every piece of state the
  // URL is allowed to carry. TOUCHED is set whenever any field differs from
  // the URL contract's own defaults -- a deep link is reader-directed
  // exactly like a click, so load()'s "no scan yet -> RULES" fallback above
  // must not paper over a view the URL already chose.
  function applyState(parsed) {
    MARKET = parsed.m;
    VIEW = parsed.v;
    FILTER = parsed.f;
    OPEN = parsed.s ? parsed.s : null;
    SORT = parsed.sort;
    TOUCHED = parsed.m !== URL_DEFAULTS.m || parsed.v !== URL_DEFAULTS.v ||
      parsed.f !== URL_DEFAULTS.f || parsed.s !== URL_DEFAULTS.s ||
      parsed.sort !== URL_DEFAULTS.sort;
  }

  function pushURLState() {
    window.history.pushState(null, "", serialiseTurtleURL(getTurtleState()));
  }

  function replaceURLState() {
    window.history.replaceState(null, "", serialiseTurtleURL(getTurtleState()));
  }

  // Never pushes or replaces -- back/forward must not grow or rewrite the
  // history it is navigating. Re-parses window.location.search rather than
  // trusting the popstate event's own .state, so the URL string alone stays
  // the single source of truth on every path (first paint, click, and back).
  function onPopState() {
    const prevMarket = MARKET;
    applyState(parseTurtleURL(window.location.search));
    if (MARKET !== prevMarket) load().then(render);
    else render();
  }

  // The market switcher is static markup (turtle.html hardcodes ASX
  // is-active) that render() cannot rebuild wholesale the way it rebuilds
  // #tt-views/#tt-controls, so MARKET's current value has to be synced onto
  // it imperatively. Called from render() (deep link / popstate / first
  // paint) and, for the instant feedback a fetch-then-render would delay,
  // from the market click handler directly.
  function syncMarketButtons() {
    document.querySelectorAll("#tt-market .market-btn").forEach((b) => {
      const on = b.dataset.market === MARKET;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
  }

  // Open-position / skip-row symbol click (Phase 7): jump to that symbol's
  // market on SIGNALS with the row expanded. Shared by the click delegate
  // and the keydown handler below so the fetch-then-verify logic exists
  // exactly once. mkt is already normalised to a real scan market (see
  // scanMarketFor) -- this never tries to load a BOOK-only sleeve key.
  // FILTER is forced to "all" because the destination row's signal state is
  // unknown until the fetch resolves, and a narrower filter could hide it
  // even when it IS there. If the symbol is not in that market's scan, the
  // navigation is undone -- back to wherever the click came from, where the
  // reason is already on screen -- rather than a SIGNALS view with nothing
  // to expand.
  function jumpToBookSymbol(sym, mkt) {
    const prevView = VIEW, prevMarket = MARKET, prevFilter = FILTER, prevOpen = OPEN;
    if (mkt) { MARKET = mkt; syncMarketButtons(); }
    VIEW = "signals"; FILTER = "all"; OPEN = sym; TOUCHED = true;
    pushURLState();
    load().then(() => {
      if (DATA && DATA.results.some((r) => r.symbol === sym)) { render(); return; }
      VIEW = prevView; MARKET = prevMarket; FILTER = prevFilter; OPEN = prevOpen;
      syncMarketButtons();
      pushURLState();
      render();
    });
  }

  function mount() {
    applyState(parseTurtleURL(window.location.search));
    replaceURLState();
    window.addEventListener("popstate", onPopState);
    // #search-trigger (Phase 4): reuse the one command palette the shared
    // nav already exposes on every page (window.GBSPalette, opened by
    // ⌘K/Ctrl-K) rather than building a second search surface. Static
    // markup, wired once here -- never inside render(), which would stack a
    // duplicate listener on this same persistent button every re-render.
    const searchTrigger = document.getElementById("search-trigger");
    if (searchTrigger) {
      searchTrigger.addEventListener("click", () => {
        window.GBSPalette && window.GBSPalette.open();
      });
    }
    document.addEventListener("click", (e) => {
      // Scoped to #tt-views on purpose: an unscoped closest() on this same
      // attribute would also catch any future match outside the tab strip
      // (Phase 5's deck pills are exactly that risk) and steal this handler.
      const v = e.target.closest("#tt-views [data-view]");
      if (v) { VIEW = v.dataset.view; TOUCHED = true; OPEN = null; pushURLState(); render(); return; }
      const g = e.target.closest("[data-goto]");
      if (g) { e.preventDefault(); VIEW = g.dataset.goto; TOUCHED = true; pushURLState(); render(); return; }
      // The deck's SKIPS pill (Phase 5): jumps to BOOK and scrolls its
      // skip-reason table into view. Not a FILTER value and not a 6th
      // view -- its own attribute (data-skips) so it can never collide
      // with the filter delegate or the scoped view-tab delegate above.
      const sk = e.target.closest("[data-skips]");
      if (sk) {
        e.preventDefault();
        VIEW = "book"; TOUCHED = true; pushURLState(); render();
        const skipsEl = document.getElementById("tt-skips");
        if (skipsEl && skipsEl.scrollIntoView) skipsEl.scrollIntoView({ block: "start" });
        return;
      }
      const f = e.target.closest("[data-filter]");
      // Phase 5: this one attribute now drives two surfaces (the deck pills,
      // visible on every view, and the SIGNALS segs, visible only there), so
      // the handler also has to own switching TO signals -- the segs are
      // already only clickable when VIEW is "signals", so this is a no-op
      // for them and the whole reason a deck pill on RULES/SIZING/EVIDENCE
      // does anything at all.
      if (f) { FILTER = f.dataset.filter; VIEW = "signals"; TOUCHED = true; pushURLState(); render(); return; }
      // Sort cycle (Phase 6): one button, four stops, FIRED -> DISTANCE ->
      // N -> SYMBOL -> FIRED. render(), not renderBody(), because the
      // button's own label has to repaint with the new sort name too.
      const sc = e.target.closest("[data-sort-cycle]");
      if (sc) {
        SORT = SORT_CYCLE[(SORT_CYCLE.indexOf(SORT) + 1) % SORT_CYCLE.length];
        pushURLState();
        render();
        return;
      }
      const m = e.target.closest("#tt-market [data-market]");
      if (m) {
        MARKET = m.dataset.market;
        syncMarketButtons();
        pushURLState();
        load().then(render);
        return;
      }
      // A symbol inside the BOOK view (Phase 7): an open position or a skip
      // row, never a scan row -- those already toggle via .tt-row below.
      const os = e.target.closest("[data-open-symbol]");
      if (os) {
        e.preventDefault();
        jumpToBookSymbol(os.dataset.openSymbol, os.dataset.openMarket);
        return;
      }
      // The HEAD toggles; a click inside the expanded detail does not. Without
      // the second test you cannot select a number out of the pyramid table or
      // scroll it sideways without the row shutting under you — and the
      // is-open cursor already promises the detail is not a button.
      const row = e.target.closest(".tt-row");
      if (row && !e.target.closest(".tt-detail")) {
        OPEN = OPEN === row.dataset.sym ? null : row.dataset.sym;
        pushURLState();
        renderBody();
      }
    });
    // Enter and Space on a focused row do what a click on its head does,
    // history included.
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const os = e.target.closest && e.target.closest("[data-open-symbol]");
      if (os) {
        e.preventDefault();
        jumpToBookSymbol(os.dataset.openSymbol, os.dataset.openMarket);
        return;
      }
      const row = e.target.closest && e.target.closest(".tt-row");
      if (!row) return;
      e.preventDefault();
      OPEN = OPEN === row.dataset.sym ? null : row.dataset.sym;
      pushURLState();
      renderBody();
      // Find the replacement node by COMPARING dataset, never by building a
      // selector out of it: dataset.sym is the DECODED symbol, so a name
      // carrying a quote or a bracket makes the selector invalid and
      // querySelector throws. Caught by rendering a hostile fixture, which is
      // the only way this surfaces -- real tickers never contain one.
      const rows = document.querySelectorAll(".tt-row");
      for (let i = 0; i < rows.length; i++) {
        if (rows[i].dataset.sym === row.dataset.sym) { rows[i].focus(); break; }
      }
    });
    load().then(render);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }

  // Exposed for test/turtle.test.js, which drives the REAL functions rather
  // than a re-typed copy of them.
  window.GBSTurtle = {
    esc, unitShares, ladder, ddEquity, yearsTo, FALLBACK,
    parseTurtleURL, serialiseTurtleURL, applyState, getTurtleState, chartHref,
    setParams: (p) => { P = Object.assign({}, FALLBACK, p || {}); },
  };
})();
