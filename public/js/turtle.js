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
        return DATA;
      });
  }

  // ── deck ───────────────────────────────────────────────────────────────────
  function deckHTML() {
    if (!DATA) {
      return '<div class="deck-status"><span class="deck-dot" data-state="idle"></span>' +
        '<span class="deck-title">Turtle rules</span></div>' +
        '<p class="deck-sub">No scan file for ' + esc(MARKET.toUpperCase()) +
        ' yet — the rules, the calculator and the evidence below work without one.</p>';
    }
    const a = DATA.aggregate || {};
    const bits = [
      '<span class="tt-pill' + (a.fired_today ? " is-hot" : "") + '">' +
        big(a.fired_today) + " fired today</span>",
      '<span class="tt-pill">' + big(a.long) + " long &middot; " + big(a.short) + " short</span>",
      '<span class="tt-pill">' + big(a.approaching) + " approaching</span>",
      '<span class="tt-pill">' + big(a.s1_blocked) + " S1 blocked</span>",
    ];
    return '<div class="deck-status"><span class="deck-dot" data-state="ok"></span>' +
      '<span class="deck-title">Turtle &mdash; ' + esc(MARKET.toUpperCase()) + "</span></div>" +
      '<p class="deck-sub">' + big(a.names) + " names evaluated of " + big(DATA.universe_size) +
      " in the universe &middot; scanned " + esc(String(DATA.generated_at || "").slice(0, 16).replace("T", " ")) +
      "</p>" + '<div class="deck-pills">' + bits.join("") + "</div>";
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
    if (QUERY) {
      const q = QUERY.toUpperCase();
      rows = rows.filter((r) => (r.symbol || "").toUpperCase().indexOf(q) >= 0 ||
        (r.name || "").toUpperCase().indexOf(q) >= 0);
    }
    return rows;
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
        "</div>" +
        '<div class="tt-nums"><span class="mono">' + money(r.price) + "</span>" +
          '<span class="mono tt-dim">N ' + num(r.n) + " (" + pct(r.n_pct) + ")</span></div>" +
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

    const posRow = (p) => {
      const sign = p.side === "short" ? -1 : 1;
      const avg = p.units ? p.cost_basis / p.units : 0;
      const r = (p.n && p.units) ? sign * (p.last_mark - avg) * p.units /
        (P.stop_n * p.n * p.units) : null;
      return "<tr><td class=\"mono\">" + esc(p.symbol) + "</td><td>" +
        esc((p.market || "").toUpperCase()) + "</td><td>" + esc(p.side) +
        " S" + esc(String(p.system)) + '</td><td class="mono">' +
        (p.fills || []).length + "u</td><td class=\"mono\">" + num(avg, 4) +
        '</td><td class="mono">' + num(p.stop, 4) + '</td><td class="mono ' +
        cls(r) + '">' + sgnR(r) + "</td><td>" + esc(p.opened) + "</td></tr>";
    };

    let h = `
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
        — one book per market, own equity, own slot pool — and the combined
        figures add A$ and US$ <b>at face value</b> (no FX conversion): read
        the per-market rows for anything you would act on. The crypto books run
        every four hours, but the BARS are daily — the cron is a scan cadence, not a four-hour Donchian.</p>
</section>`;

    if (mk.length) {
      // A levered sleeve travels with its own params (turtle_book stamps
      // them), and the disclosure below renders FROM those params -- this
      // page cannot describe a 5x book the engine is not running.
      const lev5 = mk.map((m) => [m, (BOOK.by_market[m] || {}).params])
        .find(([, p]) => p && p.leverage > 1);
      h += `<section class="tt-card"><h3>By market</h3>
        <div class="tt-tablewrap"><table class="tt-table">
        <thead><tr><th>Market</th><th>Vehicle</th><th>Equity</th><th>Open</th><th>Closed</th><th>Total R</th></tr></thead>
        <tbody>${mk.map((m) => {
          const b = BOOK.by_market[m] || {};
          const veh = b.params && b.params.leverage > 1
            ? big(b.params.leverage) + "&times; margin" : "cash";
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
        book, never a restatement of it.</p>` : ""}</section>`;
    }

    if (open.length) {
      const anyFutures = open.some((p) => p.market === "futures");
      h += `<section class="tt-card"><h3>Open positions</h3>
        <div class="tt-tablewrap"><table class="tt-table">
        <thead><tr><th>Symbol</th><th>Market</th><th>Side</th><th>Units</th>
        <th>Avg fill</th><th>Stop</th><th>Open R</th><th>Since</th></tr></thead>
        <tbody>${open.map(posRow).join("")}</tbody></table></div>
        <p class="tt-note">One shared stop per position, ${P.stop_n}N under the most
        recent unit. On the equity and crypto books the cash constraint binds
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

    // NOT TAKEN, AND WHY. A book that quietly declines half its signals looks
    // identical to one that had no signals, and which ceiling is binding is
    // the whole story -- especially at $5,000, where cash binds long before
    // any Turtle rule does.
    const skips = BOOK.skips || [];
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
      const counts = BOOK.skip_counts || {};
      const byReason = Object.keys(counts).filter((k) => k !== "total")
        .sort((a, b) => counts[b] - counts[a]);
      h += `<section class="tt-card"><h3>Not taken, and why</h3>
        <div class="tt-detail-grid">${byReason.map((r) =>
          kv(esc(WHY[r] || r), big(counts[r]))).join("")}</div>
        <div class="tt-tablewrap"><table class="tt-table">
        <thead><tr><th>Symbol</th><th>Market</th><th>Action</th><th>Reason</th><th>Detail</th></tr></thead>
        <tbody>${skips.slice(0, 40).map((k) => {
          const d = [];
          if (k.units_on_book != null) d.push(k.units_on_book + " on book vs cap " + k.cap);
          if (k.units_held != null && k.units_on_book == null) d.push(k.units_held + " units held");
          if (k.want_notional != null) d.push("wanted " + money(k.want_notional, 0));
          if (k.posted_want != null) d.push("posted " + money(k.posted_want, 0) + " wanted");
          if (k.need_im != null) d.push("IM " + money(k.need_im, 0) + " vs free " + money(k.free, 0));
          if (k.one_contract_risk_pct != null) d.push("one contract = " + pct(k.one_contract_risk_pct) + " of the account");
          if (k.bucket) d.push(esc(k.bucket));
          if (k.bar) d.push("bar " + esc(k.bar));
          return "<tr><td class=\"mono\">" + esc(k.symbol) + "</td><td>" +
            esc((k.market || "").toUpperCase()) + "</td><td>" + esc(k.action) +
            "</td><td>" + esc(WHY[k.reason] || k.reason) + '</td><td class="mono">' +
            esc(d.join(" · ")) + "</td></tr>";
        }).join("")}</tbody></table></div>
        <p class="tt-note">These are decisions, not failures. A cap that binds is
        the system working; cash binding at ${money(s.equity_start, 0)} is the
        futures-margin gap this account does not have, and it is the finding
        rather than something to tune away.</p></section>`;
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
        ctl.innerHTML = '<div class="control-group"><div class="seg" role="group" aria-label="Filter">' +
          [["all", "ALL"], ["fired", "FIRED TODAY"], ["held", "IN A POSITION"], ["near", "APPROACHING"]]
            .map(([k, l]) => '<button class="seg-btn' + (FILTER === k ? " is-active" : "") +
              '" data-filter="' + k + '">' + l + "</button>").join("") +
          "</div></div>" +
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

  function mount() {
    document.addEventListener("click", (e) => {
      const v = e.target.closest("[data-view]");
      if (v) { VIEW = v.dataset.view; TOUCHED = true; OPEN = null; render(); return; }
      const g = e.target.closest("[data-goto]");
      if (g) { e.preventDefault(); VIEW = g.dataset.goto; TOUCHED = true; render(); return; }
      const f = e.target.closest("[data-filter]");
      if (f) { FILTER = f.dataset.filter; render(); return; }
      const m = e.target.closest("#tt-market [data-market]");
      if (m) {
        MARKET = m.dataset.market;
        document.querySelectorAll("#tt-market .market-btn").forEach((b) => {
          const on = b.dataset.market === MARKET;
          b.classList.toggle("is-active", on);
          b.setAttribute("aria-selected", on ? "true" : "false");
        });
        load().then(render);
        return;
      }
      // The HEAD toggles; a click inside the expanded detail does not. Without
      // the second test you cannot select a number out of the pyramid table or
      // scroll it sideways without the row shutting under you — and the
      // is-open cursor already promises the detail is not a button.
      const row = e.target.closest(".tt-row");
      if (row && !e.target.closest(".tt-detail")) {
        OPEN = OPEN === row.dataset.sym ? null : row.dataset.sym;
        renderBody();
      }
    });
    // Enter and Space on a focused row do what a click on its head does.
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const row = e.target.closest && e.target.closest(".tt-row");
      if (!row) return;
      e.preventDefault();
      OPEN = OPEN === row.dataset.sym ? null : row.dataset.sym;
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
    setParams: (p) => { P = Object.assign({}, FALLBACK, p || {}); },
  };
})();
