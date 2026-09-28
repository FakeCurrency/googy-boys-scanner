#!/usr/bin/env node
/* IGNITION — the deck pill + panel (public/js/ignition.js), report-only.
 *
 * Runs the REAL functions, sliced out of the shipped file at load time rather
 * than re-typed here (house pattern — a mirrored copy drifts in step with the
 * bug it is supposed to catch), plus the WHOLE module evaluated against a
 * stubbed fetch/document/clock for the lazy-load and hide-when-absent
 * behaviour, plus app.js's REAL renderDeckPills run against a DOM stub for the
 * pill's placement, placeholder, aria state and focus.
 *
 * What is pinned, and why each matters:
 *   1. The pill's N is the PUBLISHED confirmed count. A break on the forming
 *      bar is a "+N forming" marker (visible text), never part of N; the
 *      panel's IGNITING heading prints the same N. The pill still shows at
 *      N = 0 when rows exist so the coiled watchlist stays reachable.
 *   2. States render in the engine's order, provisional after confirmed, and
 *      CLOSED rows are drawn (misses stay visible — survivorship is the enemy).
 *      A state that is not an OWN key of the table ("toString", "__proto__")
 *      is dropped, never thrown on.
 *   3. Every interpolated value is escaped: a hostile symbol/name cannot open
 *      a tag or break out of an attribute.
 *   4. The evidence line never invents: a missing field is a dash, an absent
 *      backtest says "Backtest pending", and no statistic is computed here.
 *   5. An absent file hides silently (no console.error, no page error); the
 *      live file is only fetched on an Ignition market and the backtest only
 *      once the panel opens; a fault AFTER the fetch is re-raised, not
 *      swallowed by the fetch's catch (TOP100 #88) — in ignition.js AND in
 *      app.js, where a lens fault may not abort the deck.
 *   6. Stale data says so, on the pill and in the panel header.
 *
 * Sandboxes use `new Function(body)()`, NOT vm.runInContext: a vm context is a
 * separate realm and cross-realm deepStrictEqual fails on Array.prototype.
 * Run with: node test/ignition.test.js
 */
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");

const PUB = path.join(__dirname, "..", "public");
const SRC = fs.readFileSync(path.join(PUB, "js", "ignition.js"), "utf8");
const APP = fs.readFileSync(path.join(PUB, "js", "app.js"), "utf8");
const HTML = fs.readFileSync(path.join(PUB, "index.html"), "utf8");
const CSS = fs.readFileSync(path.join(PUB, "css", "ignition.css"), "utf8");
const readReal = (name) => {
  const f = path.join(PUB, "data", "ignition", name);
  return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, "utf8")) : null;
};
const REAL_LIVE = readReal("crypto.json");
const REAL_BT = readReal("crypto_backtest.json");

let passed = 0, failed = 0;
const pending = [];
function test(name, fn) {
  const done = (e) => {
    if (!e) { console.log(`  ✓  ${name}`); passed++; return; }
    const loc = (e.stack || "").split("\n").slice(1).find((l) => l.includes("ignition.test.js"));
    console.error(`  ✗  ${name}\n     ${e.message}${loc ? "\n     " + loc.trim() : ""}`);
    failed++;
  };
  try {
    const out = fn();
    if (out && typeof out.then === "function") pending.push(out.then(() => done(), done));
    else done();
  } catch (e) { done(e); }
}
function suite(name) { console.log(`\n── ${name} ──`); }

// ── pull the real declarations out of the shipped files ─────────────────────
// Ask the PARSER where each one ends rather than balancing braces by hand,
// which desyncs on the first regex literal or brace inside a string.
function sliceConst(name) {
  const at = SRC.search(new RegExp(`\\bconst\\s+${name}\\s*=`));
  assert.ok(at >= 0, `ignition.js no longer defines const "${name}" — was it renamed?`);
  const start = SRC.indexOf("=", at) + 1;
  for (let i = SRC.indexOf(";", start); i > 0 && i - start < 8000; i = SRC.indexOf(";", i + 1)) {
    const cand = SRC.slice(start, i).trim();
    try { new Function(`return (${cand});`); return `const ${name} = ${cand};`; } catch (_) { /* keep walking */ }
  }
  assert.fail(`could not slice const "${name}"`);
}
function fnSrc(name, src) {
  const text = src || SRC;
  const at = text.indexOf(`function ${name}(`);
  assert.ok(at >= 0, `${src ? "app.js" : "ignition.js"} no longer defines function ${name}`);
  for (let i = text.indexOf("{", at); i < text.length; i++) {
    if (text[i] !== "}") continue;
    const cand = text.slice(at, i + 1);
    try { new Function("return (" + cand + ");"); return cand; } catch (_) { /* keep walking */ }
  }
  throw new Error(`could not slice function ${name}`);
}

const CONSTS = ["IGNITION_MARKETS", "esc", "own", "DASH", "LIVE_TTL_MS", "STALE_GEN_H", "STALE_BAR_GRACE_H", "BAR_24_7",
  "STATE_ORDER", "EXIT_TEXT", "SOURCE_LABEL", "SOURCE_TIP", "CAVEAT_FALLBACK"];
const FNS = ["isMarket", "liveUrl", "btUrl", "num", "obj", "fmtPx", "signed", "fmtPct", "fmtR", "fmtX",
  "fmtN", "toneOf", "isDay", "utcDay", "staleOf", "rowRank", "groupRows", "countsOf", "provNote",
  "pillInfo", "loadingInfo", "melb", "utcText", "chartHref", "kv", "tag", "sourceHTML", "cardHead",
  "entryTip", "triggerCardHTML", "coiledCardHTML", "entryStatus", "fmtP", "fmtCI", "evidenceHTML",
  "sourcesText", "regimeHTML", "lagHTML", "headHTML", "sectionHTML", "ignitingHTML", "panelHTML"];
const build = (win) => new Function("window",
  CONSTS.map(sliceConst).join("\n") + "\n" + FNS.map((n) => fnSrc(n)).join("\n") +
  `\nreturn { ${CONSTS.concat(FNS).join(", ")} };`)(win);
const I = build({ PM: { fmtMelb: (iso) => "MELB[" + iso + "]" } });

// CODE-only view: the reasoning for each ban is written into the source beside
// it, so a naive includes() would read the justification as the offence.
const CODE = SRC.replace(/\/\*[\s\S]*?\*\//g, "").split("\n")
  .filter((l) => !l.trim().startsWith("//")).join("\n");

// The clock every deterministic test reads: one hour after the fixture run.
const NOW = Date.parse("2026-09-28T07:00:00Z");
const text = (html) => html.replace(/<[^>]*>/g, "");

// ── fixtures: the shape scanner/ignition/run.py publishes ────────────────────
const trig = (over) => Object.assign({
  symbol: "QNT", name: "QNT Coin", yf: "QNT-USD", state: "IGNITING",
  trigger_date: "2026-09-27", trigger_close: 83.17501216, bars_since: 0, rvol: 5.83, ext_pct: 23.6,
  base: { high: 67.585, low: 62.36, bars: 60, range_pct: 8.4 },
  stop: 66.47277982, risk_pct: 20.1, wide_stop: false, mm_target: 72.81, mm_passed: true, mm_r: null,
  coil: { ribbon_pct: 1.93, atr_pctl: 12.6, vol_pctl: 0.1, drawdown_pct: 60.8, coiled: true, coiled_bars: 4 },
  mfe_r: 0.0, provisional: false, last_bar: "2026-09-27", price: 103.9687652, change_pct: 25.0,
  r_now: 1.24, trail: 67.29697347,
}, over || {});
const coiled = (over) => Object.assign({
  symbol: "CCC", name: "CCC Coin", yf: "CCC-USD", state: "COILED",
  coil: { ribbon_pct: 1.5, atr_pctl: 1.4, vol_pctl: 0.3, drawdown_pct: 83.8, coiled: true,
          coiled_bars: 16, last_coiled: "2026-09-27" },
  base: { high: 68.639066, low: 62.72, bars: 60 }, breakout_level: 68.639066,
  provisional: false, last_bar: "2026-09-27", price: 65.31853038,
}, over || {});
// A schema-2 engine row: priced from the NEXT OPEN, source recorded.
const trig2 = (over) => trig(Object.assign({
  symbol: "AXS", name: "Axie Infinity", source: "binance_vision", state: "RUNNING",
  trigger_date: "2026-09-25", trigger_close: 1.189, entry: 1.188, entry_basis: "next_open",
  entry_date: "2026-09-26", bars_since: 2, stop: 1.09774192, risk_pct: 7.6, mm_passed: false,
  mm_target: 1.521, mm_r: 3.69, price: 1.158, change_pct: -2.5, r_now: -0.33, trail: 1.09988889,
}, over || {}));
const RUNNING = trig({ symbol: "AAA", name: "AAA Coin", state: "RUNNING", trigger_date: "2026-09-19",
  bars_since: 8, rvol: 5.75, mfe_r: 9.13, price: 219.39, change_pct: 169.6, r_now: 9.36, trail: 167.05 });
const CLOSED = trig({ symbol: "BBB", name: "BBB Coin", state: "CLOSED", trigger_date: "2026-09-17",
  bars_since: 10, mfe_r: 8.52, exit_reason: "trail", exit_date: "2026-09-27",
  exit_price: 151.61902449, exit_r: 4.85, exit_pending: false, r_now: 3.44 });
const PROV = trig({ symbol: "PRV", name: "Prov Coin", provisional: true, rvol: 9.9 });
const payload = (results, counts, extra) => Object.assign({
  schema_version: 1, lens: "ignition", market: "crypto", ruleset_version: "1.0.0",
  generated_at: "2026-09-28T06:00:00+00:00", last_closed_bar: "2026-09-27", report_only: true,
  rules: { fresh_bars: 2, keep_bars: 20, base_bars: 60, trail_sma: 9, wide_stop_pct: 35.0 },
  summary: counts === undefined ? { counts: {
    IGNITING: results.filter((r) => r.state === "IGNITING").length,
    RUNNING: results.filter((r) => r.state === "RUNNING").length,
    CLOSED: results.filter((r) => r.state === "CLOSED").length,
    COILED: results.filter((r) => r.state === "COILED").length,
    provisional: results.filter((r) => r.provisional).length,
    igniting_confirmed: results.filter((r) => r.state === "IGNITING" && !r.provisional).length,
  } } : counts,
  results,
}, extra || {});
const SAMPLE = payload([trig(), RUNNING, CLOSED, coiled(),
  coiled({ symbol: "DDD", name: "DDD Coin", coil: { ribbon_pct: 1.68, atr_pctl: 32.9, vol_pctl: 0.1,
    drawdown_pct: 74.8, coiled: false, coiled_bars: 0, last_coiled: "2026-09-26" },
    breakout_level: 67.64, price: 66.77 })]);
// Schema 1 backtest: NONE of the schema-2 fields (versus, scoring, open, CIs).
const BT = {
  schema_version: 1, lens: "ignition", market: "crypto", ruleset_version: "1.0.0",
  generated_at: "2026-09-28T06:00:00+00:00", date_range: ["2020-01-01", "2026-09-27"],
  caveats: ["SURVIVORSHIP: today's top ~200 coins only.", "Per-trade R, not a portfolio."],
  primary: { n: 8, exp_r: 9.956, median_r: 10.61, pf: 3.4, top5_share_pct: 69.4,
             by_split: { in_sample: { n: 6, exp_r: 10.96 }, out_of_sample: { n: 2, exp_r: 6.943 } } },
  baselines: { random_timing: { n: 40, exp_r: 0.29 } },
};
// Schema 2, frozen here so the exact strings are pinned whatever the next
// replay publishes (the real file is checked separately, value-for-value).
const BT2 = {
  schema_version: 2, lens: "ignition", market: "crypto", ruleset_version: "1.0.0",
  generated_at: "2026-09-28T02:21:01+00:00", date_range: ["2017-08-17", "2026-09-27"],
  caveats: ["SURVIVORSHIP: today's top ~200 coins only.", "Realised trades only."],
  scoring: { realised_only: true, design_cases_excluded: { QNT: "2026-09-01" }, design_trades_excluded: 1,
             decision_statistic: "versus.random_timing: primary minus baseline expectancy, cluster-bootstrapped by entry month" },
  primary: { n: 87, open: 4, open_mtm_r: 0.06, exp_r: 1.317, median_r: -0.713, pf: 3.33, pf_note: null,
             top5_share_pct: 105.0, exp_r_ex_top5: -0.069, exp_r_ci90: [0.017, 2.872], boot_p_exp_le_0: 0.045,
             ci_method: "cluster bootstrap, entry months resampled whole",
             by_split: { in_sample: { n: 40, exp_r: 0.088 }, out_of_sample: { n: 47, exp_r: 2.364 },
                         forward: { n: 0 } } },
  versus: { random_timing: { n_primary: 87, n_baseline: 451, diff_r: 1.262, diff_ci90: [-0.054, 2.769], p_diff_le_0: 0.063 } },
  baselines: { random_timing: { n: 451, exp_r: 0.056 } },
};
const noJunk = (html, what) => {
  for (const bad of ["undefined", "NaN", "null", "[object Object]"]) {
    assert.ok(!html.includes(bad), `${what} leaked "${bad}": ${html.slice(0, 300)}`);
  }
};
// For REAL data, whose coin names/caveats are free text: flag junk only where
// a VALUE would print (a cell, a price, an R, a count), never inside prose.
const noJunkValues = (html, what) => {
  for (const re of [/>\s*(undefined|NaN|null)\s*</, /(undefined|NaN|null)(%|R\b|×)/, /\$(undefined|NaN|null)/,
                    /\[object Object\]/, /\(n (undefined|NaN|null)\)/, /<b>(undefined|NaN|null)<\/b>/]) {
    const m = re.exec(html);
    assert.ok(!m, `${what} leaked ${m && m[0]}`);
  }
};

// ════════════════════════════════════════════════════════════════════════════
suite("markets — mirrored from config.IGNITION_MARKETS");

test("the shipped constant is crypto only, and isMarket reads it", () => {
  assert.deepEqual(I.IGNITION_MARKETS, ["crypto"]);
  assert.equal(I.isMarket("crypto"), true);
  assert.equal(I.isMarket("CRYPTO"), true);
  assert.equal(I.isMarket("asx"), false);
  assert.equal(I.isMarket("nasdaq"), false);
  assert.equal(I.isMarket(null), false);
});

test("the two URLs are exactly the files scanner/ignition/run.py writes", () => {
  assert.equal(I.liveUrl("crypto"), "data/ignition/crypto.json");
  assert.equal(I.btUrl("crypto"), "data/ignition/crypto_backtest.json");
});

// ════════════════════════════════════════════════════════════════════════════
suite("grouping + ordering (engine state_rank)");

test("IGNITING · RUNNING · CLOSED · COILED, unknown states dropped", () => {
  const g = I.groupRows([coiled(), CLOSED, { symbol: "ZZZ", state: "EXPLODED" }, RUNNING, trig(), null, "x"]);
  assert.deepEqual(Object.keys(g), ["IGNITING", "RUNNING", "CLOSED", "COILED"]);
  assert.deepEqual(g.IGNITING.map((r) => r.symbol), ["QNT"]);
  assert.deepEqual(g.RUNNING.map((r) => r.symbol), ["AAA"]);
  assert.deepEqual(g.CLOSED.map((r) => r.symbol), ["BBB"]);
  assert.deepEqual(g.COILED.map((r) => r.symbol), ["CCC"]);
});

test("a state that is not an OWN key (toString, __proto__, constructor, ...) is dropped, never thrown on", () => {
  // JSON.parse gives "__proto__" as a real own string value, exactly as a
  // fetched payload would.
  const hostile = JSON.parse('[{"symbol":"P1","state":"__proto__"},{"symbol":"P2","state":"toString"},' +
    '{"symbol":"P3","state":"constructor"},{"symbol":"P4","state":"hasOwnProperty"},' +
    '{"symbol":"P5","state":"valueOf"},{"symbol":"P6","state":"isPrototypeOf"}]');
  for (const r of hostile) assert.equal(I.rowRank(r), null, `rowRank must reject state "${r.state}"`);
  assert.equal(I.rowRank({ symbol: "X", state: { toString: () => "IGNITING" } }), null, "a non-string state is unknown");
  let g;
  assert.doesNotThrow(() => { g = I.groupRows(hostile.concat([trig()])); });
  assert.deepEqual(g.IGNITING.map((r) => r.symbol), ["QNT"]);
  assert.equal(g.RUNNING.length + g.CLOSED.length + g.COILED.length, 0);
  // Every consumer downstream of the grouping survives it too.
  const p = payload(hostile.concat([coiled()]), null);
  assert.doesNotThrow(() => I.pillInfo(p, false, null));
  assert.equal(I.pillInfo(p, false, null).n, 0);
  assert.doesNotThrow(() => I.panelHTML(p, "ok", BT, "crypto", false, null));
});

test("exit reasons and sources are own-key lookups too (no Object.prototype member leaks)", () => {
  const h = I.triggerCardHTML(trig({ state: "CLOSED", exit_reason: "toString", exit_date: "2026-09-20",
    exit_price: 66.4, exit_r: -1.01, source: "constructor" }), "crypto", {});
  assert.match(h, /Closed · toString/);
  assert.ok(!/function|native code/.test(h), "a prototype member rendered as text");
  assert.match(h, /class="ig-src"[^>]*>constructor</);
});

test("confirmed IGNITING rows come before provisional ones, whatever their RVOL", () => {
  const g = I.groupRows([PROV, trig({ symbol: "LOW", rvol: 3.1 }), trig({ symbol: "HI", rvol: 7 })]);
  assert.deepEqual(g.IGNITING.map((r) => r.symbol), ["HI", "LOW", "PRV"]);
});

test("inside a state: freshest first, then strongest RVOL; COILED by coiled bars then ribbon", () => {
  const g = I.groupRows([
    trig({ symbol: "OLD", state: "RUNNING", bars_since: 9, rvol: 9 }),
    trig({ symbol: "NEW", state: "RUNNING", bars_since: 3, rvol: 3 }),
    coiled({ symbol: "C1", coil: { coiled_bars: 4, ribbon_pct: 1 } }),
    coiled({ symbol: "C2", coil: { coiled_bars: 20, ribbon_pct: 5 } }),
    coiled({ symbol: "C3", coil: { coiled_bars: 4, ribbon_pct: 0.5 } }),
  ]);
  assert.deepEqual(g.RUNNING.map((r) => r.symbol), ["NEW", "OLD"]);
  assert.deepEqual(g.COILED.map((r) => r.symbol), ["C2", "C3", "C1"]);
});

test("a non-array results field groups to four empty lists, never a throw", () => {
  const g = I.groupRows(undefined);
  assert.equal(g.IGNITING.length + g.RUNNING.length + g.CLOSED.length + g.COILED.length, 0);
});

// ════════════════════════════════════════════════════════════════════════════
suite("the count rule — N is summary.counts.igniting_confirmed");

test("N is the published confirmed count; provisional is NOT in it", () => {
  const p = payload([trig(), PROV, RUNNING]);
  const info = I.pillInfo(p, false);
  assert.equal(info.n, 1);
  assert.equal(info.provisional, 1);
});

test("the published number wins over a count of the rows (it is the engine's statement)", () => {
  const p = payload([trig()], { counts: { igniting_confirmed: 3, provisional: 0 } });
  assert.equal(I.pillInfo(p).n, 3);
});

test("a payload without summary.counts falls back to counting the rows", () => {
  const p = payload([trig(), trig({ symbol: "Q2" }), PROV], null);
  const info = I.pillInfo(p);
  assert.equal(info.n, 2);
  assert.equal(info.provisional, 1);
});

test("N = 0 still shows the pill when COILED or RUNNING rows exist (watchlist reachable)", () => {
  const onlyCoiled = I.pillInfo(payload([coiled()]));
  assert.ok(onlyCoiled, "a coiled-only day must still produce a pill");
  assert.equal(onlyCoiled.n, 0);
  const onlyRunning = I.pillInfo(payload([RUNNING]));
  assert.ok(onlyRunning && onlyRunning.n === 0);
});

test("no rows and N = 0 means no pill; an unreadable payload means no pill", () => {
  assert.equal(I.pillInfo(payload([])), null);
  assert.equal(I.pillInfo(null), null);
  assert.equal(I.pillInfo({}), null);
  assert.equal(I.pillInfo({ results: "nope" }), null);
});

test("provisional > 0 appends a '+N forming' marker as VISIBLE text, with a title that says unconfirmed", () => {
  const info = I.pillInfo(payload([PROV]));
  assert.ok(info, "a provisional-only day still produces a pill");
  assert.equal(info.n, 0, "a forming-bar break is never counted");
  assert.match(info.mark, /class="ig-pmark"/);
  assert.equal(text(info.mark), "+1 forming", "the marker must carry text, not only a title");
  assert.match(info.mark, /title="[^"]*forming bar, unconfirmed/);
  assert.equal(text(I.pillInfo(payload([PROV, trig({ symbol: "P2", provisional: true })])).mark), "+2 forming");
  assert.equal(I.pillInfo(payload([trig()])).mark, "", "no provisional, no marker");
});

test("the pill title says report-only and not traded", () => {
  const t = I.pillInfo(SAMPLE, false).title;
  assert.match(t, /report-only/i);
  assert.match(t, /not traded by the bot/i);
  assert.match(I.pillInfo(SAMPLE, true).title, /close the panel/);
});

test("the count survives hostile summary values (NaN, strings, negatives)", () => {
  const p = payload([trig()], { counts: { igniting_confirmed: "7", provisional: NaN } });
  const info = I.pillInfo(p);
  assert.equal(info.n, 1, "a string is not a count; fall back to the rows");
  assert.equal(info.provisional, 0);
  assert.equal(I.pillInfo(payload([trig()], { counts: { igniting_confirmed: -4 } })).n, 0);
});

test("the loading placeholder holds the slot and says it is loading", () => {
  const l = I.loadingInfo();
  assert.equal(l.loading, true);
  assert.equal(l.n, "…");
  assert.equal(l.open, false);
  assert.match(l.title, /report-only, not traded by the bot/);
  assert.match(l.title, /Loading/);
});

// ════════════════════════════════════════════════════════════════════════════
suite("the IGNITING heading prints the pill's N");

const headingN = (html) => {
  const m = /<section class="ig-sec ig-sec-igniting"><h4 class="ig-h">Igniting <b>(\d+)<\/b>/.exec(html);
  assert.ok(m, "no IGNITING heading with a number");
  return Number(m[1]);
};

test("confirmed + forming: heading N == pill N, and the forming count is a separate note", () => {
  const p = payload([trig(), PROV, trig({ symbol: "PR2", provisional: true }), RUNNING]);
  const h = I.panelHTML(p, "ok", BT, "crypto", false, null);
  assert.equal(headingN(h), I.pillInfo(p).n);
  assert.equal(headingN(h), 1);
  assert.match(h, /class="ig-note ig-prov-note">\+2 forming \(unconfirmed\)</);
});

test("the heading reads the PUBLISHED count exactly as the pill does, even when the rows disagree", () => {
  for (const counts of [{ counts: { igniting_confirmed: 3, provisional: 0 } },
                        { counts: { igniting_confirmed: 0, provisional: 2 } }, null]) {
    const p = payload([trig(), PROV], counts);
    assert.equal(headingN(I.panelHTML(p, "ok", BT, "crypto", false, null)), I.pillInfo(p).n,
      "the panel heading and the pill disagree about N: " + JSON.stringify(counts));
  }
});

test("provisional rows stay LISTED, under their own label, drawn dashed and tagged", () => {
  const p = payload([trig(), PROV]);
  const h = I.panelHTML(p, "ok", BT, "crypto", false, null);
  const sec = h.slice(h.indexOf("ig-sec-igniting"), h.indexOf("</section>", h.indexOf("ig-sec-igniting")));
  const sub = sec.indexOf("Forming bar · unconfirmed · not in the count");
  assert.ok(sub > 0, "the forming-bar sub-label is missing");
  assert.ok(sec.indexOf(">QNT</a>") < sub && sec.indexOf(">PRV</a>") > sub, "forming rows sit under the label");
  assert.match(sec, /ig-cards ig-cards-prov/);
  assert.match(sec, /class="ig-card ig-igniting is-prov"/);
  assert.match(sec, /forming bar · unconfirmed/);
});

test("a forming-only day: heading 0, 'Nothing confirmed', and the forming row still listed", () => {
  const p = payload([PROV, coiled()]);
  const h = I.panelHTML(p, "ok", BT, "crypto", false, null);
  assert.equal(headingN(h), 0);
  assert.equal(I.pillInfo(p).n, 0);
  assert.match(h, /Nothing confirmed on the last completed daily bar/);
  assert.match(h, />PRV<\/a>/);
  assert.match(h, /\+1 forming \(unconfirmed\)/);
});

test("the REAL committed screen: heading N == pill N", () => {
  if (!REAL_LIVE) { console.log("     (no public/data/ignition/crypto.json — skipped)"); return; }
  const h = I.panelHTML(REAL_LIVE, "ok", REAL_BT, "crypto", true, I.staleOf(REAL_LIVE, "crypto", NOW));
  assert.equal(headingN(h), I.pillInfo(REAL_LIVE).n);
});

// ════════════════════════════════════════════════════════════════════════════
suite("staleness — said out loud");

const staleP = (over) => payload([trig(), coiled()], undefined, over);

test("fresh: bars through UTC-yesterday and a run under 26h old", () => {
  assert.equal(I.staleOf(staleP(), "crypto", NOW), null);
  // One minute before the next UTC midnight the 27th is still yesterday's bar.
  assert.equal(I.staleOf(staleP({ generated_at: "2026-09-28T23:00:00Z" }), "crypto",
    Date.parse("2026-09-28T23:59:00Z")), null);
});

test("stale: newest completed bar older than UTC-yesterday (crypto), as of that bar", () => {
  const s = I.staleOf(staleP({ last_closed_bar: "2026-09-26" }), "crypto", NOW);
  assert.ok(s, "a 26 Sep screen on 28 Sep must be stale");
  assert.equal(s.asOf, "2026-09-26");
  assert.match(s.reasons.join(" "), /2026-09-26.*2026-09-27.*by 6:00 UTC/);
});

test("the bar rule waits STALE_BAR_GRACE_H past 00:00 UTC: a run that is merely DUE is not stale", () => {
  // Re-review, 2026-09-28: flagging from 00:00 lit STALE every morning at
  // 10-11am Melbourne until the 00:14 cron (often hours late) landed.
  assert.equal(I.STALE_BAR_GRACE_H, 6);
  const p = staleP({ generated_at: "2026-09-28T23:30:00Z" });      // bars through the 27th
  assert.equal(I.staleOf(p, "crypto", Date.parse("2026-09-29T00:30:00Z")), null, "00:30 UTC: the run is due");
  assert.equal(I.staleOf(p, "crypto", Date.parse("2026-09-29T05:59:00Z")), null, "05:59 UTC: still inside the grace");
  const s = I.staleOf(p, "crypto", Date.parse("2026-09-29T06:01:00Z"));
  assert.ok(s, "06:01 UTC with no 28 Sep bar: stale");
  assert.equal(s.asOf, "2026-09-27");
});

test("the bar rule falls back to summary.bars.completed_last when last_closed_bar is absent", () => {
  const p = staleP({ last_closed_bar: null });
  p.summary.bars = { completed_last: "2026-09-25", lagging: 0 };
  assert.equal(I.staleOf(p, "crypto", NOW).asOf, "2026-09-25");
});

test("stale: a run over 26h old, or no readable run time at all (unknown is never fresh)", () => {
  const old = I.staleOf(staleP({ generated_at: "2026-09-27T04:00:00Z" }), "crypto", NOW);
  assert.ok(old, "27h since the last run must be stale");
  assert.match(old.reasons.join(" "), /over 26h ago/);
  assert.equal(I.staleOf(staleP({ generated_at: "2026-09-27T06:00:00Z" }), "crypto", NOW), null, "25h is not");
  assert.ok(I.staleOf(staleP({ generated_at: undefined }), "crypto", NOW));
  assert.ok(I.staleOf(staleP({ generated_at: "garbage" }), "crypto", NOW));
});

test("the bar rule is for 24/7 markets only; a stock market's weekend is not 'stale'", () => {
  assert.equal(I.staleOf(staleP({ last_closed_bar: "2026-09-25" }), "asx", NOW), null);
  assert.equal(I.staleOf(null, "crypto", NOW), null);
});

test("a stale pill carries a visible marker and its title says 'as of <date>'", () => {
  const p = staleP({ last_closed_bar: "2026-09-26" });
  const info = I.pillInfo(p, false, I.staleOf(p, "crypto", NOW));
  assert.equal(info.stale, true);
  assert.match(info.title, /as of 2026-09-26/);
  assert.match(info.mark, /class="ig-smark"[^>]*>⚠/);
  assert.match(text(info.mark), /stale, as of 2026-09-26/, "screen readers get the words, not just a glyph");
  const fresh = I.pillInfo(p, false, null);
  assert.equal(fresh.stale, false);
  assert.ok(!/ig-smark|as of/.test(fresh.mark + fresh.title), "a fresh pill carries no stale marker");
});

test("a stale panel header shows the badge; a fresh one does not", () => {
  const p = staleP({ last_closed_bar: "2026-09-26" });
  const h = I.headHTML(p, I.staleOf(p, "crypto", NOW));
  assert.match(h, /class="ig-stale" title="This screen is behind: [^"]*2026-09-26/);
  assert.match(h, />⚠ STALE · as of 2026-09-26</);
  assert.ok(!/ig-stale/.test(I.headHTML(staleP(), null)));
});

test("lagging > 0 says 'N coins behind yesterday's close', with the detail in the tooltip", () => {
  const p = staleP();
  p.summary.bars = { completed_last: "2026-09-27", expected_completed: "2026-09-27", lagging: 39,
                     completed_dist: { "2026-09-27": 129, "2026-09-26": 36 } };
  const h = I.headHTML(p, null);
  assert.match(h, /class="ig-lag" title="39 screened coin\(s\) had no completed 2026-09-27 bar[^"]*2026-09-26 ×36"/);
  assert.match(h, />39 coins behind yesterday&#39;s close</);
  p.summary.bars.lagging = 1;
  assert.match(I.headHTML(p, null), />1 coin behind yesterday&#39;s close</);
  p.summary.bars.lagging = 0;
  assert.ok(!/ig-lag/.test(I.headHTML(p, null)), "no lag, no line");
  assert.ok(!/ig-lag/.test(I.headHTML(payload([trig()]), null)), "a payload without summary.bars has no line");
});

// ════════════════════════════════════════════════════════════════════════════
suite("trigger rows");

test("a trigger card carries every field the owner reads", () => {
  const h = I.triggerCardHTML(trig(), "crypto", { wide_stop_pct: 35 });
  for (const s of ["Triggered", "2026-09-27", "Trigger close", "$83.18", "Price", "$103.97",
                   "Since trigger", "+25.0%", "R now", "+1.24R", "Stop", "$66.47", "Risk", "20.1%",
                   "RVOL", "5.8×", "Over 9-SMA", "+23.6%", "MFE", "0.00R", "Measured move",
                   "day 1", "9-SMA trail", "$67.30", "Entry"]) {
    assert.ok(h.includes(s), `trigger card lost "${s}"`);
  }
  noJunk(h, "trigger card");
});

test("schema 2: Entry is shown with its basis; R now / Risk are measured from the entry", () => {
  const h = I.triggerCardHTML(trig2(), "crypto", {});
  assert.match(h, /title="Entry: the next open after the trigger \(2026-09-26\)[^"]*"><dt>Entry<\/dt><dd>\$1\.188<\/dd>/);
  assert.match(h, /title="Measured from the entry against the stop"><dt>R now<\/dt><dd>-0\.33R/);
  assert.match(h, /title="Stop distance as a % of the entry"><dt>Risk<\/dt>/);
  assert.match(h, /<dt>Since entry<\/dt><dd>-2\.5%<\/dd>/, "change_pct is measured from the entry now");
  const tc = I.triggerCardHTML(trig2({ entry: 1.189, entry_basis: "trigger_close", entry_date: null }), "crypto", {});
  assert.match(tc, /title="Entry: the trigger close, until the next bar opens[^"]*"><dt>Entry<\/dt>/);
  assert.match(I.triggerCardHTML(trig2({ state: "CLOSED", exit_reason: "trail" }), "crypto", {}),
    /title="Today&#39;s price against the entry and stop, had it not been exited/);
  const wide = I.triggerCardHTML(trig2({ wide_stop: true, risk_pct: 41.2 }), "crypto", { wide_stop_pct: 35 });
  assert.match(wide, /Risk 41\.2% of the entry/);
});

test("AXS: a $1.19 trigger and a $1.10 stop are distinguishable (4 significant figures under $10)", () => {
  const h = I.triggerCardHTML(trig2(), "crypto", {});
  assert.match(h, /<dt>Trigger close<\/dt><dd>\$1\.189<\/dd>/);
  assert.match(h, /<dt>Stop<\/dt><dd>\$1\.098<\/dd>/);
});

test("gap_below_stop renders as 'no trade' with the R as a dash — even if a number rides along", () => {
  const row = trig2({ state: "CLOSED", exit_reason: "gap_below_stop", exit_date: "2026-09-26",
    exit_price: 1.05, exit_r: -1.5, exit_pending: false, mfe_r: null, risk_pct: null, r_now: undefined });
  const h = I.triggerCardHTML(row, "crypto", {});
  assert.match(h, /Closed · gapped under the stop at the open - no trade/);
  const ex = h.slice(h.indexOf('class="ig-exit"'));
  assert.match(ex, /opened \$1\.050/);
  assert.match(ex, /<b>—<\/b>/, "a gap is no trade: its R is a dash");
  assert.ok(!/-1\.50R/.test(ex), "a stray exit_r must not print for a gap");
  assert.match(h, /<dt>R if held<\/dt><dd>—<\/dd>/);
  noJunk(h, "gap card");
});

test("each row shows its data source compactly; absent source, no label", () => {
  const cases = { binance_vision: "Binance", binance: "Binance", bybit: "Bybit", coinbase: "Coinbase",
                  yahoo: "Yahoo", cache: "Cached" };
  for (const [src, label] of Object.entries(cases)) {
    const h = I.triggerCardHTML(trig2({ source: src }), "crypto", {});
    assert.match(h, new RegExp(`<span class="ig-src" title="Data: [^"]+">${label}</span>`), src);
    assert.match(I.coiledCardHTML(coiled({ source: src }), "crypto"), new RegExp(`class="ig-src"[^>]*>${label}<`));
  }
  assert.match(I.triggerCardHTML(trig2({ source: "kraken" }), "crypto", {}), /class="ig-src"[^>]*>kraken</,
    "an unknown source is shown as itself, not hidden");
  assert.ok(!/ig-src/.test(I.triggerCardHTML(trig(), "crypto", {})), "no source field, no label");
});

test("the symbol links to chart.js's real query params (m + s), not ?symbol=", () => {
  const h = I.triggerCardHTML(trig(), "crypto", {});
  const href = (/class="ig-sym" href="([^"]+)"/.exec(h) || [])[1] || "";
  assert.ok(href.startsWith("chart.html?"), href);
  // Served as HTML: &amp; decodes to & before chart.js ever sees the URL.
  const q = new URLSearchParams(href.replace(/&amp;/g, "&").split("?")[1]);
  assert.equal(q.get("m"), "crypto");
  assert.equal(q.get("s"), "QNT");
});

test("a provisional row is tagged 'forming bar · unconfirmed' and drawn dashed", () => {
  const h = I.triggerCardHTML(PROV, "crypto", {});
  assert.match(h, /forming bar · unconfirmed/);
  assert.match(h, /class="ig-card ig-igniting is-prov"/);
  assert.ok(!/forming bar/.test(I.triggerCardHTML(trig(), "crypto", {})), "a confirmed row is not tagged");
});

test("wide stop is flagged (with the published threshold), never hidden", () => {
  const h = I.triggerCardHTML(trig({ wide_stop: true, risk_pct: 41.2 }), "crypto", { wide_stop_pct: 35 });
  assert.match(h, />wide stop</);
  assert.match(h, /41\.2%/);
  assert.match(h, /35\.0% wide-stop flag/);
});

test("measured move: 'passed' when mm_passed, else the target and its R", () => {
  assert.match(I.triggerCardHTML(trig(), "crypto", {}), /<dd>passed<\/dd>/);
  const h = I.triggerCardHTML(trig({ mm_passed: false, mm_target: 120.5, mm_r: 2.2 }), "crypto", {});
  assert.match(h, /\$120\.50 · \+2\.20R/);
});

test("'day N' is bars_since + 1", () => {
  assert.match(I.triggerCardHTML(RUNNING, "crypto", {}), />day 9</);
});

test("missing numbers render as a dash, never 0/NaN/null", () => {
  const bare = { symbol: "BARE", state: "RUNNING" };
  const h = I.triggerCardHTML(bare, "crypto", {});
  noJunk(h, "bare trigger card");
  assert.ok((h.match(/—/g) || []).length >= 8, "missing fields must read as dashes");
  assert.ok(!/\$0|0\.00R/.test(h), "a missing value must never read as a plausible zero");
});

// ════════════════════════════════════════════════════════════════════════════
suite("formatting — prices, percentages, R");

test("fmtPx: thousands separator from $1,000, including a price that ROUNDS to it", () => {
  assert.equal(I.fmtPx(84472), "$84,472.00");
  assert.equal(I.fmtPx(1234.5), "$1,234.50");
  assert.equal(I.fmtPx(1000), "$1,000.00");
  assert.equal(I.fmtPx(999.996), "$1,000.00", "999.996 rounds to 1,000.00 and must carry the separator");
  assert.equal(I.fmtPx(999.994), "$999.99");
  assert.equal(I.fmtPx(319.4), "$319.40");
});

test("fmtPx: 4 significant figures from $1 to $10", () => {
  assert.equal(I.fmtPx(1.189), "$1.189");
  assert.equal(I.fmtPx(1.09774192), "$1.098");
  assert.equal(I.fmtPx(9.9951), "$9.995");
  assert.equal(I.fmtPx(9.9996), "$10.00", "rounds INTO the $10 band and takes its format");
  assert.equal(I.fmtPx(1), "$1.000");
});

test("fmtPx: sub-dollar keeps 4 significant figures as a plain decimal, never an exponent", () => {
  assert.equal(I.fmtPx(0.0991), "$0.0991");
  assert.equal(I.fmtPx(0.08911224), "$0.08911");
  assert.equal(I.fmtPx(0.01838), "$0.01838");
  assert.equal(I.fmtPx(0.5), "$0.5");
  assert.equal(I.fmtPx(0.9999), "$0.9999");
  assert.equal(I.fmtPx(0.99996), "$1.000", "rounds up into the $1 band");
  assert.equal(I.fmtPx(4.77e-6), "$0.00000477");
  assert.equal(I.fmtPx(4.28e-6), "$0.00000428");
  assert.equal(I.fmtPx(9.12e-7), "$0.000000912");
  assert.ok(!/e/i.test(I.fmtPx(1.234e-12)), "no exponent at any magnitude: " + I.fmtPx(1.234e-12));
  assert.equal(I.fmtPx(0), "$0");
  assert.equal(I.fmtPx(NaN), "—");
  assert.equal(I.fmtPx("1.2"), "—");
});

test("fmtPct / fmtR never print a negative (or signed) zero", () => {
  assert.equal(I.fmtPct(-0.04), "0.0%");
  assert.equal(I.fmtPct(-0.04, true), "0.0%");
  assert.equal(I.fmtPct(0.04, true), "0.0%");
  assert.equal(I.fmtPct(-0.06, true), "-0.1%");
  assert.equal(I.fmtPct(2.44, true), "+2.4%");
  assert.equal(I.fmtR(-0.001), "0.00R");
  assert.equal(I.fmtR(0.004), "0.00R");
  assert.equal(I.fmtR(-0.33), "-0.33R");
  assert.equal(I.fmtR(1.317), "+1.32R");
});

// ════════════════════════════════════════════════════════════════════════════
suite("the panel — every state, CLOSED kept on purpose");

test("the panel renders every state in the sample, in page order", () => {
  const h = I.panelHTML(SAMPLE, "ok", BT, "crypto", false);
  const at = (s) => h.indexOf(s);
  for (const s of ["ig-sec-igniting", "ig-sec-running", "ig-sec-closed", "ig-coiled"]) {
    assert.ok(at(s) > 0, `panel lost ${s}`);
  }
  assert.ok(at("ig-sec-igniting") < at("ig-sec-running") && at("ig-sec-running") < at("ig-sec-closed") &&
            at("ig-sec-closed") < at("ig-coiled"), "sections out of order");
  for (const sym of ["QNT", "AAA", "BBB", "CCC", "DDD"]) assert.ok(h.includes(`>${sym}</a>`), sym);
  noJunk(h, "sample panel");
});

test("the header says report-only, not traded, daily bars, and the Melbourne time", () => {
  const h = I.panelHTML(SAMPLE, "ok", BT, "crypto", false);
  assert.match(h, /⚡ IGNITION · coil → ignition/);
  assert.match(h, /Report-only · not traded by the bot · daily bars · updated MELB\[2026-09-28T06:00:00\+00:00\]/);
  assert.match(h, /title="Market-local\/UTC: 2026-09-28 06:00 UTC/, "UTC belongs in the tooltip");
});

test("the header shows the BTC regime as CONTEXT, not a filter", () => {
  const up = I.headHTML(payload([trig()], undefined, { regime: { btc_close: 84472.0, btc_sma200: 71109.18,
    btc_above_200: true, btc_vs_200_pct: 18.8, as_of: "2026-09-27" } }), null);
  assert.match(up, /class="ig-regime is-up" title="Context, not a filter: the replay&#39;s edge came from periods with BTC above its 200-SMA[^"]*\$84,472\.00 vs 200-SMA \$71,109\.18, as of 2026-09-27\.">BTC above its 200-SMA \(\+18\.8%\)</);
  const down = I.headHTML(payload([trig()], undefined, { regime: { btc_above_200: false, btc_vs_200_pct: -4.2 } }), null);
  assert.match(down, /class="ig-regime is-down"[^>]*>BTC below its 200-SMA \(-4\.2%\)</);
  assert.ok(!/ig-regime/.test(I.headHTML(payload([trig()], undefined, { regime: null }), null)), "null regime, no line");
  assert.ok(!/ig-regime/.test(I.headHTML(payload([trig()]), null)), "absent regime, no line");
});

test("the header tooltip names where the bars came from", () => {
  const p = payload([trig()]);
  p.summary.sources = { mode: "exchange", by_source: { binance_vision: 117, yahoo: 36, coinbase: 15 },
                        dead: { binance: "HTTP 451", bybit: "HTTP 403" }, identity_rejected: { LINK: ["bybit"] } };
  const h = I.headHTML(p, null);
  assert.match(h, /bars: Binance 117 · Yahoo 36 · Coinbase 15 · unreachable from the runner: binance \(HTTP 451\), bybit \(HTTP 403\) · 1 same-ticker listing\(s\) rejected/);
});

test("CLOSED rows are drawn with reason, date, exit price and exit R — and say why they are there", () => {
  const h = I.panelHTML(SAMPLE, "ok", BT, "crypto", false);
  assert.match(h, /kept on purpose so misses stay visible/);
  const card = h.slice(h.indexOf("ig-card ig-closed"));
  assert.match(card, /Closed · closed under the 9-SMA/);
  assert.match(card, /2026-09-27/);
  assert.match(card, /exit \$151\.62/);
  assert.match(card, /\+4\.85R/);
  assert.match(card, /R if held/, "a closed row's r_now is not its result and must not read as 'R now'");
  assert.ok(!/<dt>R now<\/dt>/.test(card.slice(0, card.indexOf("</article>"))));
  const stop = I.triggerCardHTML(trig({ state: "CLOSED", exit_reason: "stop", exit_date: "2026-09-20",
    exit_price: 66.4, exit_r: -1.01, exit_pending: true }), "crypto", {});
  assert.match(stop, /stop hit/);
  assert.match(stop, /class="is-down">-1\.01R/);
  assert.match(stop, /exits next open/);
});

test("COILED sits in a collapsed <details> with its count; the open state survives a repaint", () => {
  const h = I.panelHTML(SAMPLE, "ok", BT, "crypto", false);
  assert.match(h, /<details class="ig-coiled"><summary[^>]*>Coiled <b>2<\/b>/);
  assert.match(I.panelHTML(SAMPLE, "ok", BT, "crypto", true), /<details class="ig-coiled" open>/);
});

test("a COILED card shows ribbon, ATR/vol percentiles, drawdown, coiled bars, breakout", () => {
  const h = I.coiledCardHTML(coiled(), "crypto");
  for (const s of ["Ribbon", "1.50%", "ATR pctl", "1.4", "Vol pctl", "0.3", "Drawdown", "83.8% off high",
                   "Coiled bars", "16", "Breakout", "$68.64", "To breakout", "+5.1%", "coiled 16 bars"]) {
    assert.ok(h.includes(s), `coiled card lost "${s}"`);
  }
  assert.match(I.coiledCardHTML(coiled({ coil: { coiled: false, last_coiled: "2026-09-26" } }), "crypto"),
    /last coiled 2026-09-26/);
  noJunk(I.coiledCardHTML({ symbol: "X", state: "COILED" }, "crypto"), "bare coiled card");
});

test("no IGNITING rows says so in words rather than dropping the section", () => {
  const h = I.panelHTML(payload([coiled()]), "absent", null, "crypto", false);
  assert.match(h, /Igniting <b>0<\/b>/);
  assert.match(h, /Nothing igniting on the last completed daily bar/);
  assert.ok(!/ig-sec-running|ig-sec-closed/.test(h), "empty RUNNING/CLOSED sections are omitted");
});

test("the REAL committed screen renders without a junk value, every row drawn", () => {
  if (!REAL_LIVE) { console.log("     (no public/data/ignition/crypto.json — skipped)"); return; }
  const stale = I.staleOf(REAL_LIVE, "crypto", NOW);
  const h = I.panelHTML(REAL_LIVE, "ok", REAL_BT, "crypto", true, stale);
  noJunkValues(h, "real panel");
  for (const r of REAL_LIVE.results) {
    if (I.rowRank(r)) assert.ok(h.includes(`>${I.esc(r.symbol)}</a>`), `real row ${r.symbol} not drawn`);
  }
  if (REAL_LIVE.regime && typeof REAL_LIVE.regime.btc_above_200 === "boolean") assert.match(h, /class="ig-regime/);
  const withSrc = REAL_LIVE.results.filter((r) => typeof r.source === "string" && r.source).length;
  assert.equal((h.match(/class="ig-src"/g) || []).length, withSrc, "every row with a source shows it");
});

// ════════════════════════════════════════════════════════════════════════════
suite("escaping — every interpolated value goes through esc");

test("a hostile symbol and name cannot open a tag or break an attribute", () => {
  const evil = `<img src=x onerror=alert(1)>"'&`;
  const rows = [trig({ symbol: evil, name: evil, trigger_date: evil, exit_reason: evil, source: evil,
                       entry_basis: "next_open", entry_date: evil }),
                trig({ symbol: evil, state: "CLOSED", exit_reason: evil, exit_date: evil }),
                coiled({ symbol: evil, name: evil, coil: { coiled: false, last_coiled: evil } })];
  const p = payload(rows, undefined, { regime: { btc_above_200: true, as_of: evil } });
  p.summary.bars = { lagging: 3, expected_completed: evil, completed_dist: { [evil]: 3 } };
  p.summary.sources = { by_source: { [evil]: 3 }, dead: { [evil]: evil } };
  const bt = Object.assign({}, BT2, { caveats: [evil], ruleset_version: evil, date_range: [evil, evil],
    scoring: { realised_only: true, design_cases_excluded: { [evil]: evil }, decision_statistic: evil } });
  const h = I.panelHTML(p, "ok", bt, "crypto", true, { asOf: evil, reasons: [evil] });
  assert.ok(!/<img/i.test(h), "a raw tag reached the panel");
  assert.ok(!/onerror=alert\(1\)>/.test(h.replace(/&lt;img src=x onerror=alert\(1\)&gt;/g, "")),
    "a raw attribute break-out reached the panel");
  assert.ok(h.includes("&lt;img src=x onerror=alert(1)&gt;&quot;&#39;&amp;"), "the name is shown, escaped");
  // The href: percent-encoded, so no quote can close it.
  const hrefs = [...h.matchAll(/href="([^"]*)"/g)].map((m) => m[1]);
  assert.ok(hrefs.length >= 3);
  hrefs.forEach((u) => assert.ok(!/[<>"']/.test(u), `unsafe href ${u}`));
});

test("the +N marker, the stale marker and the pill title are escaped too", () => {
  const info = I.pillInfo(payload([PROV]), false, { asOf: `"><img src=x>`, reasons: [`<b onmouseover=x>`] });
  assert.ok(!/<img|<b onmouseover|"\s*on\w+=/.test(info.mark));
});

test("esc escapes all five characters and is null-safe", () => {
  assert.equal(I.esc(`&<>"'`), "&amp;&lt;&gt;&quot;&#39;");
  assert.equal(I.esc(null), "");
  assert.equal(I.esc(0), "0");
});

// ════════════════════════════════════════════════════════════════════════════
suite("the evidence line — read, never invented");

test("schema 1 still renders: every number it carries, a dash for every field it lacks", () => {
  const h = I.evidenceHTML("ok", BT, { ruleset_version: "1.0.0" });
  for (const s of ["trades <b>8</b>", "expectancy <b>+9.96R</b>", "median <b>+10.61R</b>",
                   "PF <b>3.40</b>", "out-of-sample exp <b>+6.94R</b> (n 2)", "random-timing exp <b>+0.29R</b> (n 40)",
                   "top-5 share <b>69.4%</b>", "survivor-biased universe", "vs random timing <b>—</b>"]) {
    assert.ok(h.includes(s), `evidence lost "${s}"`);
  }
  assert.ok(!/realised trades|not counted|90% CI/.test(h), "schema 1 fields must not be invented");
  assert.match(h, /class="ig-ev-cav" title="SURVIVORSHIP: today&#39;s top ~200 coins only\.\n\nPer-trade R, not a portfolio\."/);
  assert.ok(!/ig-ev-warn/.test(h), "same ruleset, no drift warning");
  noJunk(h, "schema-1 evidence");
});

test("schema 2: realised n, open N (not counted), OOS n, THE DECISION STAT, random-timing n", () => {
  const h = I.evidenceHTML("ok", BT2, { ruleset_version: "1.0.0" });
  for (const s of ["realised trades <b>87</b>", "open <b>4</b> (not counted)", "expectancy <b>+1.32R</b>",
                   "median <b>-0.71R</b>", "PF <b>3.33</b>", "out-of-sample exp <b>+2.36R</b> (n 47)",
                   "vs random timing <b>+1.26R</b> (90% CI -0.05..+2.77, P(no edge) 0.063)",
                   "random-timing exp <b>+0.06R</b> (n 451)", "top-5 share <b>105.0%</b>"]) {
    assert.ok(h.includes(s), `evidence lost "${s}"`);
  }
  assert.match(h, /class="ig-ev-i ig-ev-dec" title="THE DECISION NUMBER: versus\.random_timing[^"]*n 87 vs baseline n 451/);
  assert.match(h, /title="Still open \(or exit pending\)[^"]*\+0\.06R/);
  assert.match(h, /title="90% CI \+0\.02\.\.\+2\.87R[^"]*P\(exp ≤ 0\) 0\.045"/);
  noJunk(h, "schema-2 evidence");
});

test("the tooltip keeps the caveats and names the design-case exclusion", () => {
  const h = I.evidenceHTML("ok", BT2, null);
  const tip = (/class="ig-ev-k" title="([^"]*)"/.exec(h) || [])[1] || "";
  assert.match(tip, /Design case\(s\) excluded from every scored number: QNT \(from 2026-09-01\)/);
  const cav = (/class="ig-ev-cav" title="([^"]*)"/.exec(h) || [])[1] || "";
  assert.match(cav, /SURVIVORSHIP/);
  assert.match(cav, /Realised trades only\./);
  assert.match(cav, /QNT \(from 2026-09-01\)/);
});

test("PF null with pf_note is infinity (no losses); PF null without it is a dash", () => {
  const withNote = I.evidenceHTML("ok", { primary: { n: 3, pf: null, pf_note: "no losing trades" } }, null);
  assert.match(withNote, /PF <b>∞ \(no losses\)<\/b>/);
  const h = I.evidenceHTML("ok", { primary: { n: 8, pf: null }, caveats: [] }, null);
  noJunk(h, "sparse evidence");
  assert.match(h, /PF <b>—<\/b>/);
  assert.match(h, /out-of-sample exp <b>—<\/b> \(n —\)/);
  assert.match(h, /random-timing exp <b>—<\/b> \(n —\)/);
  assert.match(h, /trades <b>8<\/b>/);
  assert.match(h, /survivor-biased universe/, "the caveat is never dropped, even with no caveats array");
  noJunk(I.evidenceHTML("ok", {}, null), "empty backtest object");
});

test("NEVER computes a statistic: no diff_r published means a dash, not exp - random exp", () => {
  const bt = JSON.parse(JSON.stringify(BT2));
  delete bt.versus.random_timing.diff_r;
  const h = I.evidenceHTML("ok", bt, null);
  assert.match(h, /vs random timing <b>—<\/b>/);
  assert.ok(!/1\.26R|1\.2[0-9]R/.test(h.slice(h.indexOf("vs random timing"))), "a difference was computed in JS");
  const bt2 = JSON.parse(JSON.stringify(BT2));
  bt2.versus = {};
  assert.match(I.evidenceHTML("ok", bt2, null), /vs random timing <b>—<\/b><\/span>/, "no versus block, no parenthetical");
  const noOpen = JSON.parse(JSON.stringify(BT2));
  noOpen.primary.open = 0;
  assert.ok(!/not counted/.test(I.evidenceHTML("ok", noOpen, null)), "open 0: nothing to say");
});

test("the REAL committed backtest renders value-for-value off the file", () => {
  if (!REAL_BT) { console.log("     (no public/data/ignition/crypto_backtest.json — skipped)"); return; }
  const h = I.evidenceHTML("ok", REAL_BT, REAL_LIVE);
  noJunkValues(h, "real evidence");
  // An oracle written here, independently of the shipped formatters.
  const R = (x) => (typeof x === "number" ? (Number(x.toFixed(2)) === 0 ? "0.00" : (x > 0 ? "+" : "") + x.toFixed(2)) + "R" : "—");
  const P = REAL_BT.primary || {};
  const oos = ((P.by_split || {}).out_of_sample) || {};
  const vs = ((REAL_BT.versus || {}).random_timing) || {};
  const rnd = ((REAL_BT.baselines || {}).random_timing) || {};
  const nTxt = (n) => (typeof n === "number" ? String(n) : "—");
  assert.ok(h.includes(`trades <b>${nTxt(P.n)}</b>`), "trades n");
  if (P.open > 0) assert.ok(h.includes(`open <b>${P.open}</b> (not counted)`), "open N");
  assert.ok(h.includes(`expectancy <b>${R(P.exp_r)}</b>`), "expectancy");
  assert.ok(h.includes(`median <b>${R(P.median_r)}</b>`), "median");
  assert.ok(h.includes(`out-of-sample exp <b>${R(oos.exp_r)}</b> (n ${nTxt(oos.n)})`), "OOS with its n");
  assert.ok(h.includes(`vs random timing <b>${R(vs.diff_r)}</b>`), "the decision stat");
  if (Array.isArray(vs.diff_ci90)) {
    const b = (x) => (Number(x.toFixed(2)) === 0 ? "0.00" : (x > 0 ? "+" : "") + x.toFixed(2));
    assert.ok(h.includes(`(90% CI ${b(vs.diff_ci90[0])}..${b(vs.diff_ci90[1])}, P(no edge) ${vs.p_diff_le_0.toFixed(3)})`),
      "decision CI + P");
  }
  assert.ok(h.includes(`random-timing exp <b>${R(rnd.exp_r)}</b> (n ${nTxt(rnd.n)})`), "random timing with its n");
  if (typeof P.pf === "number") assert.ok(h.includes(`PF <b>${P.pf.toFixed(2)}</b>`));
  else if (P.pf_note) assert.ok(h.includes("PF <b>∞ (no losses)</b>"));
});

test("absent backtest => 'Backtest pending'; still fetching => loading", () => {
  assert.match(I.evidenceHTML("absent", null, null), />Backtest pending</);
  assert.match(I.evidenceHTML("ok", null, null), />Backtest pending</);
  assert.match(I.evidenceHTML("loading", null, null), /Backtest loading/);
  assert.equal(I.entryStatus(null), "loading");
  assert.equal(I.entryStatus({ at: null, data: null }), "loading");
  assert.equal(I.entryStatus({ at: 1, data: null }), "absent");
  assert.equal(I.entryStatus({ at: 1, data: {} }), "ok");
});

test("a backtest from a different ruleset than the live screen says so", () => {
  const h = I.evidenceHTML("ok", Object.assign({}, BT, { ruleset_version: "0.9.0" }), { ruleset_version: "1.0.0" });
  assert.match(h, /backtest ruleset 0\.9\.0 ≠ live 1\.0\.0/);
});

// ════════════════════════════════════════════════════════════════════════════
suite("the module — lazy fetch, hide-when-absent, fault reporting");

// A Date whose clock the test owns: `now()` and a zero-argument `new Date()`
// read it; explicit arguments pass straight through.
function makeClock(start) {
  const clock = { t: start };
  class FakeDate extends Date {
    constructor(...a) { if (a.length) super(...a); else super(clock.t); }
    static now() { return clock.t; }
  }
  return { clock, FakeDate };
}
function pillEl() {
  const el = { attrs: { "aria-pressed": "true", "aria-expanded": "true" }, cls: new Set(["fpill", "ig", "is-active"]) };
  el.setAttribute = (k, v) => { el.attrs[k] = String(v); };
  el.classList = { remove: (c) => el.cls.delete(c) };
  return el;
}
// Evaluate the WHOLE shipped file against stubs. `fetch`, `document`,
// `console`, `setTimeout` and `Date` are parameters, so they shadow the globals.
function runModule(respond, opts) {
  const o = opts || {};
  const calls = [];
  const errors = [];
  const timers = [];
  const listeners = [];
  const pills = [pillEl()];
  const host = { hidden: true, innerHTML: "", querySelector: () => null };
  const doc = {
    getElementById: (id) => (id === "ignition-panel" ? host : null),
    addEventListener: (t, fn) => listeners.push([t, fn]),
    querySelectorAll: (sel) => (sel === "[data-ignition]" ? pills : []),
  };
  const fetchStub = (url, opts2) => { calls.push({ url, opts: opts2 }); return respond(url, calls.length); };
  const win = { PM: { fetchTimeout: fetchStub, fmtMelb: o.fmtMelb || ((iso) => "MELB[" + iso + "]") } };
  const con = { error: (...a) => errors.push(a), warn: (...a) => errors.push(a), log: () => {} };
  const { clock, FakeDate } = makeClock(o.now == null ? NOW : o.now);
  new Function("window", "document", "fetch", "console", "setTimeout", "Date", SRC)(
    win, doc, fetchStub, con, (fn) => timers.push(fn), FakeDate);
  return { Ig: win.Ignition, calls, errors, timers, host, listeners, clock, win, pills };
}
const ok200 = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
const r404 = () => Promise.resolve({ ok: false, status: 404, json: () => Promise.reject(new Error("no")) });
const flush = () => new Promise((r) => setImmediate(r));
const settle = async () => { await flush(); await flush(); };
const both = (live, bt) => (url) => ok200(url.endsWith("_backtest.json") ? bt : live);

test("the module exports window.Ignition and binds one delegated click listener", () => {
  const m = runModule(() => r404());
  assert.deepEqual(Object.keys(m.Ig).sort(), ["MARKETS", "isMarket", "pill", "sync", "toggle"]);
  assert.deepEqual(m.Ig.MARKETS, ["crypto"]);
  assert.deepEqual(m.listeners.map((l) => l[0]), ["click"]);
});

test("a non-Ignition market fetches nothing and gets no pill (not even a placeholder)", async () => {
  const m = runModule(() => ok200(SAMPLE));
  assert.equal(m.Ig.pill("asx", () => {}), null);
  assert.equal(m.Ig.pill("nasdaq", () => {}), null);
  await flush();
  assert.equal(m.calls.length, 0);
});

test("while the first fetch is in flight the pill is a PLACEHOLDER; once loaded, the real pill", async () => {
  const m = runModule(both(SAMPLE, BT));
  const first = m.Ig.pill("crypto", () => {});
  assert.equal(first.loading, true, "the first call holds the slot with a placeholder");
  assert.equal(first.n, "…");
  await settle();
  const info = m.Ig.pill("crypto");
  assert.ok(info && !info.loading, "the loaded pill is not a placeholder");
  assert.equal(info.n, 1);
});

test("an ABSENT live file (404) hides silently: placeholder, then no pill, no console.error, no page error", async () => {
  const m = runModule(() => r404());
  let ready = 0;
  assert.equal(m.Ig.pill("crypto", () => { ready++; }).loading, true, "only a placeholder before the load settles");
  await settle();
  assert.equal(ready, 1, "the deck is told the load settled");
  assert.equal(m.Ig.pill("crypto", () => {}), null, "an absent file never produces a pill");
  m.Ig.toggle("crypto");
  m.Ig.sync("crypto");
  assert.equal(m.host.hidden, true, "the panel stays hidden with no data");
  assert.deepEqual(m.errors, [], "nothing may reach the console");
  assert.equal(m.timers.length, 0, "nothing may be re-raised as a page error");
  assert.deepEqual(m.calls.map((c) => c.url), ["data/ignition/crypto.json"],
    "the backtest is never fetched for a panel that cannot open");
});

test("a dead connection (fetch rejects) and a non-JSON body hide just as silently", async () => {
  for (const respond of [() => Promise.reject(new TypeError("Failed to fetch")),
                         () => Promise.resolve({ ok: true, json: () => Promise.reject(new SyntaxError("bad")) }),
                         () => ok200([1, 2, 3])]) {
    const m = runModule(respond);
    m.Ig.pill("crypto", () => {});
    await settle();
    assert.equal(m.Ig.pill("crypto"), null);
    assert.deepEqual(m.errors, []);
    assert.equal(m.timers.length, 0);
  }
});

test("the live file is fetched once through PM.fetchTimeout with no-cache, then served from cache", async () => {
  const m = runModule(both(SAMPLE, BT));
  m.Ig.pill("crypto", () => {});
  m.Ig.pill("crypto", () => {});          // in flight: no second request
  await settle();
  const info = m.Ig.pill("crypto", () => {});
  assert.equal(info.n, 1);
  assert.equal(m.calls.length, 1);
  assert.equal(m.calls[0].opts.cache, "no-cache");
});

test("the live file REFRESHES after LIVE_TTL_MS, and not before", async () => {
  const updated = payload([trig(), trig({ symbol: "NEW2" })]);
  const m = runModule((url, n) => ok200(n === 1 ? SAMPLE : updated));
  m.Ig.pill("crypto", () => {});
  await settle();
  m.clock.t += I.LIVE_TTL_MS - 1000;
  assert.equal(m.Ig.pill("crypto").n, 1);
  await settle();
  assert.equal(m.calls.length, 1, "still inside the TTL: no refetch");
  m.clock.t += 2000;
  const during = m.Ig.pill("crypto", () => {});
  assert.equal(during.n, 1, "the on-screen copy stays up while the refresh is in flight (no placeholder flash)");
  await settle();
  assert.equal(m.calls.length, 2, "past the TTL the file is re-read");
  assert.equal(m.Ig.pill("crypto").n, 2, "and the refreshed copy is what the pill shows");
});

test("a FAILED refresh keeps the copy already on screen", async () => {
  const m = runModule((url, n) => (n === 1 ? ok200(SAMPLE) : r404()));
  m.Ig.pill("crypto", () => {});
  await settle();
  m.clock.t += I.LIVE_TTL_MS + 1;
  m.Ig.pill("crypto", () => {});
  await settle();
  assert.equal(m.calls.length, 2);
  const info = m.Ig.pill("crypto");
  assert.ok(info, "a failed refresh must not blank the pill");
  assert.equal(info.n, 1);
  assert.deepEqual(m.errors, []);
});

test("the backtest is fetched ONLY when the panel opens, and the panel then renders", async () => {
  const m = runModule(both(SAMPLE, BT));
  m.Ig.pill("crypto", () => {});
  await settle();
  m.Ig.sync("crypto");
  assert.equal(m.host.hidden, true, "closed panel stays hidden");
  assert.equal(m.calls.length, 1, "no backtest fetch while closed");
  assert.equal(m.Ig.toggle("crypto"), true);
  m.Ig.sync("crypto");
  assert.equal(m.host.hidden, false);
  assert.match(m.host.innerHTML, /Backtest loading/);
  assert.deepEqual(m.calls.map((c) => c.url), ["data/ignition/crypto.json", "data/ignition/crypto_backtest.json"]);
  await settle();
  assert.match(m.host.innerHTML, /expectancy <b>\+9\.96R<\/b>/, "the evidence line repaints when the file lands");
  assert.equal(m.Ig.pill("crypto").open, true, "the pill reports the panel as open");
  assert.equal(m.Ig.toggle("crypto"), false);
  m.Ig.sync("crypto");
  assert.equal(m.host.hidden, true);
  assert.deepEqual(m.errors, []);
});

test("a market switch CLOSES the panel: coming back does not re-open it unasked", async () => {
  const m = runModule(both(SAMPLE, BT));
  m.Ig.pill("crypto", () => {});
  await settle();
  m.Ig.toggle("crypto");
  m.Ig.sync("crypto");
  await settle();
  assert.equal(m.host.hidden, false);
  m.Ig.sync("asx");
  assert.equal(m.host.hidden, true, "switching market hides it");
  m.Ig.sync("crypto");
  assert.equal(m.host.hidden, true, "returning to crypto must not re-open the panel");
  assert.equal(m.Ig.pill("crypto").open, false, "and the pill is not drawn pressed");
  assert.equal(m.calls.length, 2, "no refetch");
});

test("the market-switch LISTENER hides an open panel at once", async () => {
  const m = runModule(both(SAMPLE, BT));
  m.Ig.pill("crypto", () => {});
  await settle();
  m.Ig.toggle("crypto");
  m.Ig.sync("crypto");
  assert.equal(m.host.hidden, false);
  const click = m.listeners.find((l) => l[0] === "click")[1];
  const btn = { getAttribute: (k) => (k === "data-market" ? "asx" : null) };
  click({ target: { closest: (sel) => (sel === ".market-btn[data-market]" ? btn : null) } });
  assert.equal(m.host.hidden, true, "the delegated market-switch listener must hide the panel");
  assert.equal(m.host.innerHTML, "");
  click({ target: { closest: () => null } });           // an unrelated click is a no-op
  assert.equal(m.host.hidden, true);
});

test("the COILED <details> open state survives a repaint through sync()", async () => {
  const m = runModule(both(SAMPLE, BT));
  m.Ig.pill("crypto", () => {});
  await settle();
  m.Ig.toggle("crypto");
  m.Ig.sync("crypto");                                   // painted with the backtest still loading
  assert.match(m.host.innerHTML, /<details class="ig-coiled">/);
  m.host.querySelector = (sel) => (sel === "details.ig-coiled" ? { open: true } : null);   // the user opened it
  await settle();                                        // the backtest lands -> repaint
  assert.match(m.host.innerHTML, /expectancy/, "the repaint happened");
  assert.match(m.host.innerHTML, /<details class="ig-coiled" open>/, "the open disclosure must stay open");
});

test("an absent backtest renders 'Backtest pending' in an open panel", async () => {
  const m = runModule((url) => (url.endsWith("_backtest.json") ? r404() : ok200(SAMPLE)));
  m.Ig.pill("crypto", () => {});
  await settle();
  m.Ig.toggle("crypto");
  m.Ig.sync("crypto");
  await settle();
  assert.match(m.host.innerHTML, />Backtest pending</);
  assert.deepEqual(m.errors, []);
});

test("a fault AFTER the fetch is re-raised to window.onerror, not swallowed as 'absent'", async () => {
  const m = runModule(() => ok200(SAMPLE));
  m.Ig.pill("crypto", () => { throw new Error("renderer bug"); });
  await settle();
  assert.equal(m.timers.length, 1, "the fault must be re-raised asynchronously");
  assert.throws(() => m.timers[0](), /renderer bug/);
  assert.ok(m.Ig.pill("crypto"), "and the data it loaded is still there — the fault was not mistaken for a 404");
});

test("a RENDER fault in sync() is re-raised, the host hidden, and the pill not left pressed", async () => {
  const m = runModule(both(SAMPLE, BT), { fmtMelb: () => { throw new Error("render boom"); } });
  m.Ig.pill("crypto", () => {});
  await settle();
  m.Ig.toggle("crypto");
  m.host.hidden = false;                                 // as if a previous paint had shown it
  m.host.innerHTML = "<p>old</p>";
  m.Ig.sync("crypto");
  assert.equal(m.host.hidden, true, "a panel that failed to render is hidden");
  assert.equal(m.host.innerHTML, "");
  assert.equal(m.timers.length, 1, "the fault is re-raised asynchronously");
  assert.throws(() => m.timers[0](), /render boom/);
  assert.equal(m.Ig.pill("crypto").open, false, "openFor was reset: the next deck render draws it closed");
  const el = m.pills[0];
  assert.equal(el.attrs["aria-pressed"], "false", "the pill on screen is un-pressed in place");
  assert.equal(el.attrs["aria-expanded"], "false");
  assert.ok(!el.cls.has("is-active"));
});

test("a payload value that THROWS while being read takes the same path as a render fault", async () => {
  // Re-review, 2026-09-28: staleOf() and the paint key were computed OUTSIDE
  // sync()'s try, so a generated_at that cannot be coerced left the old
  // panel up, still open, with no pill on the deck to close it.
  const bad = payload([trig()], undefined, { generated_at: { toString: 1 } });
  const m = runModule(both(bad, BT2));
  m.Ig.pill("crypto", () => {});                        // placeholder while loading
  await settle();
  assert.throws(() => m.Ig.pill("crypto"), /primitive/, "the pill itself throws (app.js's ignCall reports it)");
  m.Ig.toggle("crypto");
  m.host.hidden = false;                                 // as if a previous paint had shown it
  m.host.innerHTML = "<p>old</p>";
  m.Ig.sync("crypto");                                   // must not throw
  assert.equal(m.host.hidden, true, "the old panel is taken down");
  assert.equal(m.host.innerHTML, "");
  assert.equal(m.timers.length, 1, "the fault is re-raised asynchronously");
  assert.throws(() => m.timers[0](), /primitive/);
  assert.equal(m.Ig.toggle("crypto"), true, "openFor was reset, so the next toggle OPENS");
});

test("a stale live file marks the pill and the panel header through the real module clock", async () => {
  const old = payload([trig()], undefined, { last_closed_bar: "2026-09-26" });
  const m = runModule(both(old, BT2));
  m.Ig.pill("crypto", () => {});
  await settle();
  const info = m.Ig.pill("crypto");
  assert.equal(info.stale, true);
  assert.match(info.title, /as of 2026-09-26/);
  m.Ig.toggle("crypto");
  m.Ig.sync("crypto");
  assert.match(m.host.innerHTML, /⚠ STALE · as of 2026-09-26/);
  // The same file, read on the 27th (a day earlier), is current.
  const m2 = runModule(both(old, BT2), { now: Date.parse("2026-09-27T12:00:00Z") });
  m2.Ig.pill("crypto", () => {});
  await settle();
  assert.equal(m2.Ig.pill("crypto").stale, false);
});

test("source order: the catch sits on the fetch+parse, the callback runs after it", () => {
  const load = fnSrc("load");
  const c = load.indexOf(".catch(");
  const cb = load.indexOf("cb(market)");
  assert.ok(c > 0 && cb > c, "the onReady callback must run AFTER the fetch's catch");
  assert.equal((load.match(/\.catch\(/g) || []).length, 1, "exactly one catch, on the fetch");
});

// ════════════════════════════════════════════════════════════════════════════
suite("app.js — the REAL renderDeckPills against a DOM stub");

// A tiny stand-in for #deck-pills: innerHTML is a string, and
// querySelector("[attr]") hands back a fresh element stub per render for any
// attribute the markup carries — which is all renderDeckPills asks of it.
function makeBox() {
  const box = { html: "", els: {} };
  Object.defineProperty(box, "innerHTML", {
    get() { return box.html; },
    set(v) { box.html = String(v); box.els = {}; },
  });
  box.querySelector = (sel) => {
    const m = /^\[([\w-]+)\]$/.exec(sel);
    if (!m || !new RegExp(`\\s${m[1]}(=|\\s|>)`).test(box.html)) return null;
    if (!box.els[sel]) {
      const el = { sel, listeners: {}, focused: 0, focusArg: null, attrs: {}, dataset: {}, textContent: "" };
      el.addEventListener = (t, fn) => { (el.listeners[t] = el.listeners[t] || []).push(fn); };
      el.focus = (arg) => { el.focused++; el.focusArg = arg; };
      el.setAttribute = (k, v) => { el.attrs[k] = v; };
      box.els[sel] = el;
    }
    return box.els[sel];
  };
  box.querySelectorAll = (sel) => { const e = box.querySelector(sel); return e ? [e] : []; };
  return box;
}
function deckHarness(ignition, market) {
  const src = fnSrc("renderDeckPills", APP);
  const timers = [];
  const counts = {};
  const box = makeBox();
  const $ = (sel) => (sel === "#deck-pills" ? box : (counts[sel] || (counts[sel] = { textContent: "" })));
  const state = { market: market || "crypto", data: { results: [] }, tab: "aplus", confl: null,
                  vkConfl: false, vkAtLevel: false, dimFunds: true };
  const deckCounts = () => ({ real: [], aplus: 7, a: 3, atLevel: 2, products: 0, aplusProducts: 0, watch: 5 });
  const noop = () => {};
  const render = new Function("$", "state", "deckCounts", "isFundReit", "GRADE_RANK", "esc", "fmtPrice",
    "savePrefs", "syncFundDim", "renderRows", "document", "window", "setTimeout",
    src + "\nreturn renderDeckPills;")(
    $, state, deckCounts, () => false, {}, I.esc, String, noop, noop, noop,
    { querySelectorAll: () => [] }, { Ignition: ignition }, (fn) => timers.push(fn));
  return { render: () => render(state.data), box, state, timers, counts };
}
const pillTag = (html, attr) => {
  const at = html.indexOf(attr);
  if (at < 0) return "";
  return html.slice(html.lastIndexOf("<button", at), html.indexOf("</button>", at) + 9);
};

test("crypto: a PLACEHOLDER pill in the third slot while loading, the real pill in the same slot after", async () => {
  const m = runModule(both(SAMPLE, BT));
  const d = deckHarness(m.Ig);
  d.render();
  const ph = pillTag(d.box.html, "data-ignition-wait");
  assert.ok(ph, "no placeholder pill while the file loads");
  assert.match(ph, /aria-busy="true"/);
  assert.match(ph, /class="fpill ig is-loading"/);
  assert.match(ph, /⚡ Ignition <b>…<\/b>/);
  assert.ok(!/\sdata-ignition=/.test(ph), "the placeholder is inert (no toggle bound to it)");
  const order = (html, ig) => [html.indexOf('data-goto="aplus"'), html.indexOf('data-goto="a"'),
    html.indexOf(ig), html.indexOf('data-pill="confl"'), html.indexOf('data-pill="atlevel"')];
  const o1 = order(d.box.html, "data-ignition-wait");
  assert.deepEqual(o1.slice().sort((a, b) => a - b), o1, "placeholder must sit A+, A, ⚡, Multi-lens, At level");
  await settle();                                        // the file lands -> onReady -> re-render
  const real = pillTag(d.box.html, 'data-ignition="1"');
  assert.ok(real, "the loaded file did not re-render the strip into the real pill");
  assert.ok(!/data-ignition-wait/.test(d.box.html), "the placeholder is replaced, not duplicated");
  const o2 = order(d.box.html, 'data-ignition="1"');
  assert.ok(o2.every((x) => x >= 0), "a pill went missing");
  assert.deepEqual(o2.slice().sort((a, b) => a - b), o2, "the Ignition pill must be THIRD, straight after A");
  assert.match(real, /⚡ Ignition <b>1<\/b>/);
});

test("the loaded pill carries aria-controls, aria-pressed AND aria-expanded", async () => {
  const m = runModule(both(SAMPLE, BT));
  const d = deckHarness(m.Ig);
  d.render();
  await settle();
  const p = pillTag(d.box.html, 'data-ignition="1"');
  assert.match(p, /aria-controls="ignition-panel"/);
  assert.match(p, /aria-pressed="false"/);
  assert.match(p, /aria-expanded="false"/);
});

test("clicking the pill opens the panel, flips aria-expanded, and RESTORES focus to the new pill", async () => {
  const m = runModule(both(SAMPLE, BT));
  const d = deckHarness(m.Ig);
  d.render();
  await settle();
  const before = d.box.querySelector("[data-ignition]");
  before.listeners.click[0]();
  const after = d.box.querySelector("[data-ignition]");
  assert.notEqual(after, before, "the strip was re-rendered (a new element)");
  assert.equal(after.focused, 1, "focus must go back to the re-rendered Ignition pill");
  const p = pillTag(d.box.html, 'data-ignition="1"');
  assert.match(p, /aria-expanded="true"/);
  assert.match(p, /aria-pressed="true"/);
  assert.match(p, /is-active/);
  assert.equal(m.host.hidden, false, "the panel opened");
  after.listeners.click[0]();
  assert.match(pillTag(d.box.html, 'data-ignition="1"'), /aria-expanded="false"/);
  assert.equal(d.box.querySelector("[data-ignition]").focused, 1);
  assert.equal(m.host.hidden, true);
});

test("an absent file: placeholder while loading, then NO pill", async () => {
  const m = runModule(() => r404());
  const d = deckHarness(m.Ig);
  d.render();
  assert.ok(pillTag(d.box.html, "data-ignition-wait"));
  await settle();
  assert.ok(!/data-ignition/.test(d.box.html), "an absent file must leave no pill at all");
});

test("a non-Ignition market gets no placeholder and no pill", () => {
  const m = runModule(both(SAMPLE, BT));
  const d = deckHarness(m.Ig, "asx");
  d.render();
  assert.ok(!/data-ignition/.test(d.box.html));
  assert.equal(m.calls.length, 0);
});

test("a stale file puts the ⚠ marker on the deck pill and 'as of' in its title", async () => {
  const m = runModule(both(payload([trig()], undefined, { last_closed_bar: "2026-09-26" }), BT));
  const d = deckHarness(m.Ig);
  d.render();
  await settle();
  const p = pillTag(d.box.html, 'data-ignition="1"');
  assert.match(p, /title="STALE, as of 2026-09-26/);
  assert.match(p, /class="ig-smark"/);
});

test("a THROWING lens cannot abort renderDeckPills: the deck renders and the fault is re-raised", () => {
  for (const which of ["pill", "sync"]) {
    const boom = new Error("lens boom " + which);
    const ign = { pill: () => null, toggle: () => false, sync: () => {} };
    ign[which] = () => { throw boom; };
    const d = deckHarness(ign);
    assert.doesNotThrow(() => d.render(), `a throwing Ignition.${which} escaped renderDeckPills`);
    assert.match(d.box.html, /⨂ Multi-lens/, "the rest of the strip still rendered");
    assert.match(d.box.html, /◎ At level/);
    assert.equal(d.counts["#count-aplus"].textContent, 7, "the toolbar counts after it still ran");
    assert.equal(d.counts["#count-watch"].textContent, 5);
    assert.equal(d.timers.length, 1, "the fault must be re-raised asynchronously, not swallowed");
    assert.throws(() => d.timers[0](), (e) => e === boom);
    if (which === "pill") assert.ok(!/data-ignition/.test(d.box.html), "a failed lens draws no pill");
  }
});

// ════════════════════════════════════════════════════════════════════════════
suite("wiring + fences");

test("app.js places the pill THIRD (straight after A) and routes it through pill()", () => {
  const fn = APP.slice(APP.indexOf("function renderDeckPills("), APP.indexOf("// ----------------------------------------------------------- a row"));
  const inner = fn.indexOf("box.innerHTML =");
  const a = fn.indexOf(`"A", nA,`, inner);
  const ig = fn.indexOf("ignPillHTML +", inner);
  const conf = fn.indexOf(`"⨂ Multi-lens"`, inner);
  assert.ok(inner > 0 && a > inner && ig > a && conf > ig, "Ignition must sit after A and before Multi-lens");
  assert.match(fn, /pill\(`data-ignition="1" aria-controls="ignition-panel" aria-expanded="\$\{ign\.open \? "true" : "false"\}"`,\s*"ig", "⚡ Ignition", ign\.n, ign\.title, ign\.open, ign\.mark\)/);
  assert.match(fn, /pill\(`data-ignition-wait="1" aria-busy="true"[^`]*`, "ig is-loading", "⚡ Ignition", ign\.n, ign\.title, false, ""\)/);
  assert.match(fn, /window\.Ignition\.pill\(state\.market,/);
  assert.match(fn, /window\.Ignition\.toggle\(state\.market\)/);
  assert.match(fn, /window\.Ignition\.sync\(state\.market\)/);
  assert.match(fn, /box\.querySelector\("\[data-ignition\]"\)[\s\S]*\.focus\(/);
  assert.ok(!/data-pill="ignition"/.test(fn),
    "it is not a list filter: a data-pill would re-render the rows on every tap");
  assert.match(fn, /\$\{extra \|\| ""\}<\/button>/, "pill() appends the +N marker after the count");
});

test("app.js keeps no Ignition logic of its own (no market list, no data path)", () => {
  assert.ok(!/data\/ignition/.test(APP), "only ignition.js knows the file path");
  assert.ok(!/IGNITION_MARKETS/.test(APP), "only ignition.js holds the market list");
});

test("index.html loads ignition.css and ignition.js (before app.js) and hosts the panel after the pills", () => {
  assert.match(HTML, /<link rel="stylesheet" href="css\/ignition\.css\?v=\d+" \/>/);
  const js = HTML.search(/<script src="js\/ignition\.js\?v=\d+"><\/script>/);
  const app = HTML.search(/<script src="js\/app\.js\?v=\d+"><\/script>/);
  assert.ok(js > 0 && app > js, "ignition.js must load before app.js");
  const pills = HTML.indexOf('id="deck-pills"');
  const panel = HTML.indexOf('id="ignition-panel"');
  assert.ok(pills > 0 && panel > pills && panel < HTML.indexOf('id="bot-activity"'),
    "the panel lives inside the deck, directly under the pills");
  assert.match(HTML, /<div class="ig-panel" id="ignition-panel" hidden/);
});

test("the asset versions moved with this change (?v= floor: ignition.js/css 2, app.js 139)", () => {
  const v = (re) => Number((re.exec(HTML) || [])[1] || 0);
  assert.ok(v(/js\/ignition\.js\?v=(\d+)/) >= 2, "ignition.js edited without a ?v= bump");
  assert.ok(v(/css\/ignition\.css\?v=(\d+)/) >= 2, "ignition.css edited without a ?v= bump");
  assert.ok(v(/js\/app\.js\?v=(\d+)/) >= 139, "app.js edited without a ?v= bump");
});

test("the CSS lets [hidden] win, styles the pill, and lets a long tag wrap inside its card", () => {
  assert.match(CSS, /\.ig-panel\[hidden\]\s*\{\s*display:\s*none;/);
  assert.match(CSS, /\.fpill\.ig\s*\{/);
  assert.match(CSS, /\.ig-pmark\s*\{/);
  assert.match(CSS, /\.fpill\.ig\.is-loading\s*\{/);
  assert.match(CSS, /\.ig-stale\s*\{/);
  assert.match(CSS, /\.ig-vh\s*\{[^}]*clip/);
  const tagRule = (/\.ig-tag\s*\{([^}]*)\}/.exec(CSS) || [])[1] || "";
  assert.match(tagRule, /max-width:\s*100%/);
  assert.match(tagRule, /overflow-wrap:\s*anywhere/);
  assert.ok(!/white-space:\s*nowrap/.test(tagRule), "nowrap would stop overflow-wrap from ever wrapping");
});

test("report-only by construction: no storage, no write, no second endpoint", () => {
  assert.ok(!/localStorage|sessionStorage|indexedDB/.test(CODE), "no browser storage");
  assert.ok(!/method\s*:/.test(CODE), "GET only");
  assert.ok(!/\/api\//.test(CODE), "no API endpoint");
  assert.ok(!/beforeunload/.test(CODE));
  const urls = [...CODE.matchAll(/`(data\/[^`]+)`/g)].map((m) => m[1]).sort();
  assert.deepEqual(urls, ["data/ignition/${market}.json", "data/ignition/${market}_backtest.json"]);
  assert.ok(!/vivek_bot_book|bot_rules|conviction|confluence/.test(CODE),
    "the lens must not read the book, the rules or the confluence machinery");
});

Promise.all(pending).then(() => {
  console.log(`\n${failed ? "✗" : "✓"} ignition.test.js: ${passed} passed, ${failed} failed`);
  if (failed) process.exit(1);
});
