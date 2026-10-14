#!/usr/bin/env node
/* Chart refinements, REFINE200 #101-#118 (2026-10-14).

   Eighteen chart findings, each reproduced in a headless browser before it was
   fixed. Every test here runs the SHIPPED code: functions are sliced out of
   public/js/chart.js by asking the parser where a declaration ends (the
   momentum/deep_history pattern), never re-typed, so a fixture cannot drift in
   step with the bug it is meant to catch. Where a fix is wiring rather than
   arithmetic, the pin reads the line that does the work.

   Run with: node test/chart_refine.test.js
*/
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");

let passed = 0, failed = 0;
const QUEUE = [];
function test(name, fn) { QUEUE.push({ name, fn }); }
const suite = (name) => QUEUE.push({ suite: name });
async function runQueue() {
  for (const item of QUEUE) {
    if (item.suite) { console.log(`\n── ${item.suite} ──`); continue; }
    try { await item.fn(); console.log(`  ✓  ${item.name}`); passed++; }
    catch (e) { console.error(`  ✗  ${item.name}\n     ${e.stack || e.message}`); failed++; }
  }
}

const ROOT = path.join(__dirname, "..");
const CHART = fs.readFileSync(path.join(ROOT, "public", "js", "chart.js"), "utf8");
const CSS = fs.readFileSync(path.join(ROOT, "public", "css", "chart.css"), "utf8");
// Comments stripped, for pins that must not pass on prose.
const CODE = CHART.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/[^\n]*/g, "$1");

function fnSrc(name, src = CHART) {
  const at = src.search(new RegExp(`\\bfunction\\s+${name}\\s*\\(`));
  assert.ok(at >= 0, `chart.js no longer defines ${name}`);
  for (let i = src.indexOf("{", at); i < src.length; i++) {
    if (src[i] !== "}") continue;
    const cand = src.slice(at, i + 1);
    try { new Function("return (" + cand + ");"); return cand; } catch (_) { /* keep walking */ }
  }
  throw new Error("slice " + name);
}
function constSrc(name, src = CHART) {
  const at = src.search(new RegExp(`\\bconst\\s+${name}\\s*=`));
  assert.ok(at >= 0, `chart.js no longer declares ${name}`);
  for (let i = src.indexOf(";", at); i > 0; i = src.indexOf(";", i + 1)) {
    const cand = src.slice(at, i + 1);
    try { new Function(cand); return cand; } catch (_) { /* keep walking */ }
  }
  throw new Error("slice const " + name);
}
// The body of a render()-scoped function (nested, so fnSrc's file-wide search
// still finds it -- names are unique in chart.js).
const body = (name) => fnSrc(name);

/* ═══════════════ #101 the 200-SMA tag names the timeframe it is ═══════════ */
suite("#101 the 200-SMA line and the TF tooltips say which plan is drawn");

test("the on-chart tag and the footer share one rule: W / 3D / 4H / D, or D·ref", () => {
  const f = new Function(`${constSrc("SMA_TF_CODE")} ${constSrc("smaTfCode")} return smaTfCode;`)();
  assert.equal(f("1W", false), "W");
  assert.equal(f("3D", false), "3D", "a REAL 3-Day plan was labelled D");
  assert.equal(f("4H", false), "4H", "a REAL 4H plan was labelled D (ref)");
  assert.equal(f("1D", false), "D");
  assert.equal(f("4H", true), "D·ref", "a 4H view that borrowed the Daily plan says so");
  assert.equal(f("3D", true), "D·ref");
  assert.match(body("applyVivekLevels"), /const lvlLabel = "200 SMA·" \+ smaTfCode\(key, !!\(tfs\[key\] \|\| \{\}\)\.approx\);/);
  assert.match(body("renderVivekFooter"), /200 SMA \(\$\{smaTfCode\(tfKey, isRef\)\}\)/,
    "the footer reads the same helper, so the two cannot disagree again");
});

test("'trade levels are the Daily plan' is said only where it is true", () => {
  const f = new Function(`${constSrc("TF_TITLE")} ${fnSrc("tfTitle")} return tfTitle;`)();
  assert.ok(!/Daily plan/.test(f("4H", { approx: false }, false)), "a real 4H plan is its own");
  assert.ok(!/Daily plan/.test(f("3D", { approx: false }, false)), "a real 3-Day plan is its own");
  assert.match(f("4H", { approx: true }, false), /trade levels are the Daily plan/);
  assert.match(f("3D", { approx: true }, false), /^3-day candles · trade levels are the Daily plan$/);
  assert.match(f("4H", null, false), /^≈2y max history/);
  assert.equal(f("1D", { approx: false }, false), "", "no tooltip where there is nothing to say");
  assert.match(f("3D", {}, true), /3-session/, "Momentum's 3D counts sessions, and says so");
  assert.ok(!Object.values(new Function(`${constSrc("TF_TITLE")} return TF_TITLE;`)())
    .some((t) => /Daily plan/.test(t)), "no fixed tooltip claims the Daily plan");
});

/* ═══════════════ #107 the FUND / REIT chip honours is_product ═══════════════ */
suite("#107 the chart's FUND / REIT chip reads the scanner's verdict first");

// The real PM factory in a DOM-less sandbox, as staleview.test.js does.
const SHARED = fs.readFileSync(path.join(ROOT, "public", "js", "phasemap-shared.js"), "utf8");
const PM = (() => {
  const sandbox = { window: {}, localStorage: { getItem: () => null, setItem: () => {} },
    document: undefined, fetch: () => Promise.reject(new Error("no net in tests")),
    console, JSON, Math, Date, String, Number, Array, Object, Promise, RegExp, parseFloat, parseInt };
  sandbox.globalThis = sandbox;
  require("vm").createContext(sandbox);
  require("vm").runInContext(SHARED, sandbox);
  return sandbox.window.PM;
})();
const chartFund = (pm) => new Function("window", `${fnSrc("isFundReit")} return isFundReit;`)({ PM: pm });

test("is_product false beats a fund-looking name: TRMK (Trustmark) is a bank", () => {
  const f = chartFund(PM);
  assert.equal(f({ symbol: "TRMK", name: "Trustmark Corporation - Common Stock", is_product: false }), false,
    "the old substring rule matched TRUST inside Trustmark");
});

test("is_product true beats a clean name: the A+ preferreds and LICs wear the chip", () => {
  const f = chartFund(PM);
  for (const [symbol, name] of [["STRK", "Strategy Inc - 8.00% Series A Perpetual Strike Preferred Stock"],
                                 ["HBANP", "Huntington Bancshares Incorporated - Depositary Shares"],
                                 ["AFI", "Australian Foundation Investment Company Limited"]]) {
    assert.equal(f({ symbol, name, is_product: true }), true, symbol);
  }
});

test("absent verdict -> WORD-BOUNDARY keywords (NETFLIX is not an ETF)", () => {
  const f = chartFund(PM);
  assert.equal(f({ symbol: "NFLX", name: "Netflix, Inc. - Common Stock" }), false);
  assert.equal(f({ symbol: "CQR", name: "Charter Hall Retail REIT" }), true);
  assert.equal(f({ symbol: "XYZ", name: "XYZ", sector: "Real Estate Investment Trust" }), true);
  assert.equal(f({ symbol: "EVT", name: "EVT" }), false, "a held position with only a ticker");
});

test("no shared helpers loaded -> only an explicit true is a product", () => {
  const f = chartFund(undefined);
  assert.equal(f({ name: "Charter Hall Retail REIT" }), false, "no guessing without the shared rule");
  assert.equal(f({ name: "x", is_product: true }), true);
});

test("the chart keeps no keyword list of its own, and every fallback carries the flag", () => {
  assert.ok(!/FUND_NAME_KW|FUND_SECTOR_HINTS|NON_OP_SECTORS/.test(CODE), "a second keyword copy drifts");
  for (const fb of ["vivekFallback", "pmOnlyFallback", "momentumFallback", "liveFallback"]) {
    assert.match(fnSrc(fb), /is_product: /, `${fb} must copy is_product onto d`);
  }
  const html = fs.readFileSync(path.join(ROOT, "public", "chart.html"), "utf8");
  assert.ok(html.indexOf("js/phasemap-shared.js") > 0 &&
            html.indexOf("js/phasemap-shared.js") < html.indexOf("js/chart.js"),
    "PM must load before chart.js for the shared rule to be there");
});

/* ═══════════════ #109 one TradingView link for every mode ═══════════════ */
suite("#109 'Open in TradingView' is set on every chart, exchange-prefixed");

test("footer() sets #cf-tv before any branch returns, from tvSymbolFor", () => {
  const f = fnSrc("footer");
  const set = f.indexOf("tvSymbolFor(d.symbol, d.asset_type)");
  assert.ok(set > 0, "footer must build the link from tvSymbolFor");
  assert.ok(set < f.indexOf("if (d._vivek)") && set < f.indexOf("if (d._momentum)"),
    "the Momentum and VIVEK branches return early; the link must be set first");
  assert.ok(!/tv_symbol/.test(CODE), "no payload carries tv_symbol; the fallback linked bare BHP (the NYSE ADR)");
});

test("the link a PhaseMap-only ASX chart and a Momentum chart now get", () => {
  const run = (market, d) => {
    const el = { href: null };
    const $ = (sel) => (sel === "#cf-tv" ? el : { set innerHTML(_) {}, set textContent(_) {}, hidden: true });
    const fn = new Function("market", "$", "renderVivekFooter", "renderMomentumFooter", "fmt",
      `const isCryptoMarket = (t) => t === "crypto" || market === "crypto";
       ${fnSrc("tvSymbolFor")} ${fnSrc("footer")} return footer;`)(market, $, () => {}, () => {}, String);
    fn(d);
    return el.href;
  };
  assert.equal(run("asx", { symbol: "BHP", asset_type: null, _pm: true }),
    "https://www.tradingview.com/chart/?symbol=ASX%3ABHP");
  assert.equal(run("asx", { symbol: "EOS", asset_type: null, _momentum: true }),
    "https://www.tradingview.com/chart/?symbol=ASX%3AEOS", "Momentum used to leave href unset");
  assert.equal(run("crypto", { symbol: "JUP", asset_type: "crypto", _vivek: true }),
    "https://www.tradingview.com/chart/?symbol=CRYPTO%3AJUPUSD");
  assert.equal(run("nasdaq", { symbol: "AAPL", asset_type: null }),
    "https://www.tradingview.com/chart/?symbol=AAPL");
});

runQueue().then(() => {
  console.log(`\nchart_refine.test.js: ${passed}/${passed + failed} passed`);
  if (failed) process.exit(1);
});
