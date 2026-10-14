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
  // `async function` included, so an awaiting body still parses on its own.
  const at = src.search(new RegExp(`\\b(async\\s+)?function\\s+${name}\\s*\\(`));
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

/* ═══════════════ #104 Momentum's prev/next reads the Momentum list ═══════════ */
suite("#104 a Momentum chart steps the Momentum list, not a 404");

const sourceFor = (market, mode) => new Function("market", "mode", "isMomentum",
  `${fnSrc("scanSource")} return scanSource();`)(market, mode, mode === "momentum");

test("each mode reads the file that exists", () => {
  assert.equal(sourceFor("asx", "momentum").file, "data/momentum/asx.json", "was data/asx.json (404)");
  assert.equal(sourceFor("nasdaq", "momentum").file, "data/momentum/nasdaq.json");
  assert.equal(sourceFor("asx", "vivek").file, "data/asx_vivek.json");
  assert.equal(sourceFor("nasdaq", "spec").file, "data/nasdaq_spec.json");
  assert.equal(sourceFor("scalp", "scalp").file, "data/scalp.json");
  assert.equal(sourceFor("asx", "momentum").sOf({ symbol: "EOS" }), "EOS");
  for (const [m, mode] of [["asx", "momentum"], ["asx", "vivek"], ["nasdaq", "spec"]]) {
    assert.ok(fs.existsSync(path.join(ROOT, "public", sourceFor(m, mode).file)), `${m}/${mode} file is published`);
  }
});

test("the arrows keep the reader in Momentum, and the dead lens suffixes are gone", () => {
  const nav = fnSrc("wireScanNav");
  assert.match(nav, /let \{ file, sOf \} = scanSource\(\);/);
  assert.match(nav, /isMomentum \? `chart\.html\?m=\$\{market\}&s=\$\{encodeURIComponent\(s\)\}&src=momentum`/);
  assert.match(fnSrc("fetchResultMeta"), /const \{ file, sOf \} = scanSource\(\);/, "one answer for both readers");
  assert.ok(!/_reversal|"_short"/.test(CODE), "reversal/short lenses were removed months ago");
});

test("a crypto Momentum chart keeps its own timeframes (no 15M/30M/1H stream)", () => {
  assert.match(CODE, /const pair = \(!d\._vivek && !d\._heldPlan && !d\._pm && !d\._momentum &&/,
    "measured: BTC&src=momentum drew 15M/30M/1H scalp bars with two empty panes");
});

/* ═══════════════ #116 one request per data file ═══════════════ */
suite("#116 opening a chart fetches each scan file once");

test("fetchJsonOnce: one request per URL, shared; a failure resolves null", async () => {
  const calls = [];
  const fetch = (u) => { calls.push(u); return Promise.resolve(u.includes("bad")
    ? { ok: false, status: 404 } : { ok: true, json: () => Promise.resolve({ u }) }); };
  const once = new Function("fetch", `${constSrc("_jsonOnce")} ${fnSrc("fetchJsonOnce")} return fetchJsonOnce;`)(fetch);
  const [a, b, c] = await Promise.all([once("data/asx_vivek.json"), once("data/asx_vivek.json"), once("data/asx_vivek.json")]);
  assert.equal(calls.length, 1, "three readers, one request");
  assert.ok(a === b && b === c, "and one parsed object");
  assert.equal(await once("data/bad.json"), null);
  const boom = new Function("fetch", `${constSrc("_jsonOnce")} ${fnSrc("fetchJsonOnce")} return fetchJsonOnce;`)(
    () => Promise.reject(new Error("offline")));
  assert.equal(await boom("x"), null, "a network failure must not reject into a second reader");
});

test("the summary, the book and the momentum file have no direct fetch left", () => {
  assert.ok(!/fetch\(\s*`data\/\$\{market\}_vivek\.json`/.test(CODE), "<market>_vivek.json fetched outside fetchJsonOnce");
  assert.ok(!/fetch\(\s*"data\/vivek_bot_book\.json"/.test(CODE), "the bot book fetched outside fetchJsonOnce");
  assert.ok(!/fetch\(\s*`data\/momentum\//.test(CODE), "the momentum file fetched twice (row + arrows)");
  for (const fn of ["fetchResultMeta", "wireScanNav", "wireBotPosBanner", "momentumRow", "pmChartBars"]) {
    assert.match(fnSrc(fn), /fetchJsonOnce\(/, `${fn} must share the request`);
  }
});

test("fetchResultMeta stamps currency on a COPY, never on the shared row", () => {
  const f = fnSrc("fetchResultMeta");
  assert.ok(!/row\.currency_symbol = /.test(f), "mutating the shared parsed file leaks into other readers");
  assert.match(f, /Object\.assign\(\{\}, found, \{ currency_symbol:/);
});

/* ═══════════════ #71 a chart reads ONE PhaseMap record, not the market ═══════════ */
suite("#71 the PhaseMap record comes from the per-ticker file when it carries one");

function pmHarness(files, dir = "") {
  const calls = [];
  const fetch = (u) => {
    calls.push(u);
    const key = u.replace(/\?.*$/, "");
    return Promise.resolve(key in files
      ? { ok: true, json: () => Promise.resolve(JSON.parse(JSON.stringify(files[key]))) }
      : { ok: false, status: 404, json: () => Promise.reject(new Error("404")) });
  };
  const api = new Function("fetch", "market", "symbol", "isMomentum", "params", "pmDirWanted",
    `${constSrc("_jsonOnce")} ${fnSrc("fetchJsonOnce")} ${constSrc("pmTickerUrl")}
     ${fnSrc("pmRecFromTickerFile")} ${fnSrc("pmRecFromLatest")} ${fnSrc("fetchPhaseMapRec")}
     return { fetchPhaseMapRec, pmRecFromTickerFile };`)(
    fetch, "asx", "abc", false, new URLSearchParams(""), dir);
  return { api, calls };
}
const PMREC = (dir, extra) => Object.assign({ ticker: "ABC", direction: dir, state: "RUNNING", zones: [] }, extra || {});

test("a per-ticker file WITH the record: one small request, no 1 MB market file", async () => {
  const h = pmHarness({ "data/phasemap/charts/asx/ABC.json":
    { ticker: "ABC", candles: [], records: [PMREC("bullish"), PMREC("bearish")],
      narrations: { "ABC|bullish": "up story", "ABC|bearish": "down story" } } }, "bearish");
  const rec = await h.api.fetchPhaseMapRec();
  assert.equal(rec.direction, "bearish", "?dir= still picks the side");
  assert.equal(rec.narration, "down story");
  assert.deepEqual(h.calls, ["data/phasemap/charts/asx/ABC.json"]);
});

test("the record shapes the writer may use all read", () => {
  const { api } = pmHarness({});
  const one = api.pmRecFromTickerFile({ record: PMREC("bullish"), narration: "n" }, "ABC", "");
  assert.equal(one.narration, "n");
  const keyed = api.pmRecFromTickerFile({ record: [PMREC("bullish")], narration: { bullish: "b" } }, "ABC", "");
  assert.equal(keyed.narration, "b");
  const inline = api.pmRecFromTickerFile({ records: [PMREC("bullish", { narration: "own" })] }, "ABC", "");
  assert.equal(inline.narration, "own");
  assert.equal(api.pmRecFromTickerFile({ record: null }, "ABC", ""), null, "the file says: no record");
  assert.equal(api.pmRecFromTickerFile({ ticker: "ABC", candles: [] }, "ABC", ""), undefined,
    "a file from before the record keys -> the caller reads latest.json");
  const src = { records: [PMREC("bullish")] };
  api.pmRecFromTickerFile(src, "ABC", "");
  assert.ok(!("narration" in src.records[0]), "the shared parsed file is not mutated");
});

test("an old per-ticker file falls back to latest.json + narrations, as before", async () => {
  const h = pmHarness({
    "data/phasemap/charts/asx/ABC.json": { ticker: "ABC", candles: [] },
    "data/phasemap/asx/latest.json": { run_date: "2026-10-14", results: [PMREC("bullish")] },
    "data/phasemap/asx/narrations.json": { run_date: "2026-10-14", narrations: { "ABC|bullish": "old path" } },
  });
  const rec = await h.api.fetchPhaseMapRec();
  assert.equal(rec.narration, "old path");
  assert.deepEqual(h.calls.slice(1).sort(), ["data/phasemap/asx/latest.json", "data/phasemap/asx/narrations.json"]);
});

test("no per-ticker file = no PhaseMap record, and nothing else is downloaded", async () => {
  const h = pmHarness({ "data/phasemap/asx/latest.json": { results: [PMREC("bullish")] } });
  assert.equal(await h.api.fetchPhaseMapRec(), null);
  assert.deepEqual(h.calls, ["data/phasemap/charts/asx/ABC.json"],
    "phasemap/run.py writes the file for every ticker with a record and prunes the rest");
});

runQueue().then(() => {
  console.log(`\nchart_refine.test.js: ${passed}/${passed + failed} passed`);
  if (failed) process.exit(1);
});
