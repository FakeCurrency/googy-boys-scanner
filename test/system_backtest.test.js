#!/usr/bin/env node
/* The SYSTEM page's live backtest panel (public/js/system-backtest.js).
 *
 * Owner, 2026-09-20: "Every time we run a back test I want the results to be
 * seen on the HOW THE SYSTEM works page" — in the context that he trades high
 * conviction longs on live accounts off exactly this evidence.
 *
 * So the properties worth pinning are about HONESTY, not layout: a missing
 * number must read as missing rather than as zero, the sample size must always
 * be stated, and the page must not be able to drift back to hard-coded claims.
 *
 * Runs the REAL shipped file against the REAL published reports.
 */
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");

let passed = 0, failed = 0;
const Q = [];
const test = (n, f) => Q.push({ n, f });
const suite = (n) => Q.push({ s: n });
async function run() {
  for (const i of Q) {
    if (i.s) { console.log(`\n── ${i.s} ──`); continue; }
    try { await i.f(); console.log(`  ✓  ${i.n}`); passed++; }
    catch (e) { console.error(`  ✗  ${i.n}\n     ${e.message}`); failed++; }
  }
}

const ROOT = path.resolve(__dirname, "..");
const SRC = fs.readFileSync(path.join(ROOT, "public/js/system-backtest.js"), "utf8");
const readJSON = (f) => { try { return JSON.parse(fs.readFileSync(path.join(ROOT, f), "utf8")); }
                          catch (_) { return null; } };

/* Render the panel in a tiny DOM stub against whatever reports we hand it. */
function render(longonly, both) {
  let html = null;
  const el = { set innerHTML(v) { html = v; }, get innerHTML() { return html; } };
  const sandbox = {
    document: { querySelector: (s) => (s === "#sys-backtest" ? el : null) },
    fetch: (f) => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(f.includes("longonly") ? longonly : both),
    }),
    Promise, JSON, Math, String, Number, Object, isFinite, console,
  };
  new Function("document", "fetch", "Promise", "JSON", "Math", "String", "Number",
               "Object", "isFinite", "console", SRC)(
    sandbox.document, sandbox.fetch, Promise, JSON, Math, String, Number, Object,
    isFinite, console);
  return new Promise((res) => setTimeout(() => res(html), 5));
}

const M = (o) => Object.assign({ n: 10, win_rate: 50, avg_r: 0.1, profit_factor: 1.2 }, o);
const REPORT = (over) => Object.assign({
  generated_at: "2026-09-20T01:02:03Z",
  params: { period: "5y", timeframes: ["1D", "3D", "1W"], limit: 600 },
  coverage: { asx: { symbols: 600, universe: 1710, sampled_pct: 35.1 } },
  results: {
    overall: M({ n: 1940 }),
    by_conviction_long: { high: M({ n: 120, win_rate: 58.3, avg_r: 0.42 }), rest: M({ n: 1820, avg_r: -0.02 }) },
    by_timeframe_long: { "1W": M(), "3D": M(), "1D": M({ avg_r: -0.04 }) },
    by_grade: { "A+": M(), A: M({ avg_r: 0 }) },
    by_entry_type_long: { reclaim: M(), retest: M(), break: M() },
  },
}, over || {});

suite("what it shows");

test("the high-conviction cohort leads, because that is what gets traded", async () => {
  const h = await render(REPORT(), null);
  assert.ok(/High conviction/.test(h));
  assert.ok(h.indexOf("High conviction") < h.indexOf("By timeframe"),
    "the traded cohort must come before the general breakdowns");
  assert.ok(/58\.3%/.test(h) && /\+0\.420/.test(h));
});

test("the cohort row names the RULE that produced it, old or new", async () => {
  // A report written before 2026-09-20 carries no conviction_rule: it must be
  // labelled as the OLD rule, never dressed as the widened one.
  const old = await render(REPORT(), null);
  assert.ok(/rule BEFORE 2026-09-20/.test(old), "an old report must say it predates the widened rule");
  const r = REPORT();
  r.results.conviction_rule = "1W reclaim/break, 3D reclaim or 1D break - armed, grade A/A+";
  r.results.by_conviction_cell_long = { "1W reclaim": M({ n: 691, avg_r: 0.299 }), "1W break": M({ n: 122 }),
                                        "3D reclaim": M({ n: 1309 }), "1D break": M({ n: 281 }) };
  const h = await render(r, null);
  assert.ok(/1W reclaim\/break, 3D reclaim or 1D break/.test(h), "the shipped rule text is printed");
  assert.ok(!/rule BEFORE 2026-09-20/.test(h));
  assert.ok(/By conviction cell/.test(h) && /\+0\.299/.test(h) && /691/.test(h), "the per-cell table renders");
  const noCells = await render(REPORT(), null);
  assert.ok(!/By conviction cell/.test(noCells), "no per-cell block when the report has none");
});

test("the long-only report leads the both-directions one", async () => {
  const h = await render(REPORT(), REPORT());
  assert.ok(h.indexOf("Long-only replay") < h.indexOf("Both directions"));
});

test("the sample size and coverage are ALWAYS stated", async () => {
  const h = await render(REPORT(), null);
  assert.ok(/600\/1710/.test(h), "coverage counts missing");
  assert.ok(/35\.1%/.test(h), "coverage share missing");
  assert.ok(/SLICE of each market/.test(h), "the panel must say it is a sample");
});

test("the run date is shown, so a stale report is visible as stale", async () => {
  const h = await render(REPORT(), null);
  assert.ok(/run 2026-09-20/.test(h));
});

suite("honesty under missing data");

test("a missing cohort reads as missing, never as zero", async () => {
  const r = REPORT();
  delete r.results.by_conviction_long;
  const h = await render(r, null);
  assert.ok(/predates the high-conviction cohort/.test(h));
  assert.ok(!/>0<\/td>/.test(h), "an absent cohort must not render as a 0-trade row");
});

test("a missing metric renders a dash", async () => {
  const r = REPORT();
  r.results.overall = { n: 5 };               // no win_rate / avg_r / pf
  const h = await render(r, null);
  assert.ok(/—/.test(h), "absent fields must show as a dash");
});

test("no reports at all says so rather than rendering an empty shell", async () => {
  const h = await render(null, null);
  assert.ok(/No backtest report is published yet/.test(h));
});

test("only expectancy is coloured — a 45% win rate is not a failure", async () => {
  const r = REPORT();
  r.results.by_conviction_long.high = M({ win_rate: 44.4, avg_r: 0.079 });
  const h = await render(r, null);
  assert.ok(/bt-pos[^>]*>\+0\.079/.test(h), "positive expectancy must be marked positive");
  assert.ok(!/bt-neg[^>]*>44\.4%/.test(h), "win rate must not be coloured red");
});

suite("the page cannot drift back to hand-typed claims");

test("the old fixed '~65% win, +0.85R' claim is gone", async () => {
  const html = fs.readFileSync(path.join(ROOT, "public/system.html"), "utf8");
  assert.ok(!/65% win/.test(html), "a hard-coded backtest number came back");
  assert.ok(!/\+0\.85R/.test(html));
});

test("the page hosts the panel and loads the script", () => {
  const html = fs.readFileSync(path.join(ROOT, "public/system.html"), "utf8");
  assert.ok(/id="sys-backtest"/.test(html));
  assert.ok(/js\/system-backtest\.js\?v=/.test(html));
});

test("it renders against the REAL published reports without throwing", async () => {
  const lo = readJSON("public/data/vivek_backtest_longonly.json");
  const both = readJSON("public/data/vivek_backtest.json");
  if (!lo && !both) return;                    // nothing committed yet — nothing to check
  const h = await render(lo, both);
  assert.ok(h && h.length > 200, "the real reports produced no panel");
  assert.ok(!/undefined|NaN/.test(h), "a real report leaked undefined/NaN into the page");
});

run().then(() => {
  console.log(`\nsystem_backtest.test.js: ${passed}/${passed + failed} passed`);
  if (failed) process.exit(1);
});
