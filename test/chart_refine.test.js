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

/* ═══════════════ #103 the Auto box shows on the day its signal fires ═══════════ */
suite("#103 a signal on the newest bar still draws its box");

test("momBoxSpan never returns a one-point span", () => {
  const span = new Function(`${fnSrc("momBoxSpan")} return momBoxSpan;`)();
  const cs = [10, 20, 30, 40].map((time) => ({ time }));
  assert.deepEqual(span({ bar: { time: 20 } }, cs), [20, 40], "an older signal: signal bar -> last bar");
  assert.deepEqual(span({ bar: { time: 40 } }, cs), [30, 40],
    "age 0: x0 === xN drew NOTHING (LWC renders a one-point series as no line)");
  assert.deepEqual(span({}, cs), [10, 40]);
  assert.deepEqual(span({ bar: { time: 10 } }, []), [null, null]);
  for (const fn of ["applyMomentumPlan", "paintMomentumZones"]) {
    assert.match(fnSrc(fn), /= momBoxSpan\(pl, cs\);/, `${fn} must use the same span`);
  }
});

/* ═══════════════ #102 the MACD / RSI panes follow the window ═══════════ */
suite("#102 the Momentum panes resize with the page");

test("a ResizeObserver resizes both panes and is torn down with the render", () => {
  const at = CHART.indexOf("let macdHistS = null");   // bound FORWARD: the heading also names shadeRows earlier
  const pane = CHART.slice(at, CHART.indexOf("// ── Session / weekend shading", at));
  assert.ok(pane.length > 1000, "the pane slice is non-empty");
  assert.match(pane, /const paneRo = new ResizeObserver\(/);
  assert.match(pane, /\[\[macdChart, macdBox\], \[rsiChart, rsiBox\]\]\.forEach\(\(\[c, b\]\) => \{\s*try \{ c\.applyOptions\(\{ width: b\.clientWidth, height: b\.clientHeight \}\);/);
  assert.match(pane, /paneRo\.observe\(macdBox\);\s*paneRo\.observe\(rsiBox\);/);
  assert.match(pane, /onRenderTeardown\(\(\) => paneRo\.disconnect\(\)\);/);
  assert.match(CODE, /onRenderTeardown\(\(\) => ro\.disconnect\(\)\);/, "the price chart's observer too");
  assert.match(CODE, /onRenderTeardown\(\(\) => cro\.disconnect\(\)\);/, "and the drawing layer's");
});

/* ═══════════════ #110 My size and ⧉ Plan follow the Momentum timeframe ═══════════ */
suite("#110 Momentum: the size and the plan copy belong to the timeframe on screen");

test("applyMomentumPlan names the TF and recomputes the size on EVERY timeframe", () => {
  const f = fnSrc("applyMomentumPlan");
  const tf = f.indexOf("d._activeTf = key;"), noPlan = f.indexOf("if (!pl) {");
  assert.ok(tf > 0 && tf < noPlan, "the TF must be set before the no-plan branch returns");
  assert.equal((f.match(/d\._recalcMySize\(\)/g) || []).length, 2, "both branches recompute My size");
  assert.match(f, /dir: pl\.dir === 1 \? "LONG" : "SHORT"/, "a TF's box can face the other way from the 1D header");
});

test("no plan on this TF sizes nothing and copies nothing; no disclaimer, no '· ·'", () => {
  assert.match(fnSrc("wireSizeCalc"), /if \(d\._activeTf && d\._activeLevels === null\) \{\s*out\.textContent = `No plan on \$\{d\._activeTf\}/);
  const click = CHART.slice(CHART.indexOf("if (planBtn) planBtn.onclick"), CHART.indexOf("// ── Drawing tools + measure"));
  assert.match(click, /const noPlanHere = !!d\._activeTf && d\._activeLevels === null;/);
  assert.match(click, /`— no plan on \$\{d\._activeTf\}`/);
  assert.ok(!/not advice/.test(CHART), "the owner ruled disclaimers out (2026-09-28)");
  assert.match(click, /\.filter\(Boolean\)\s*\.join\(" · "\)/, "an empty grade leaves no empty slot");
  assert.match(click, /\(lv\.dir \|\| d\.dir \|\| "LONG"\)/);
});

/* ═══════════════ #111 "confirmed" counts back from the SCAN's last bar ═══════════ */
suite("#111 the Rule A confirmation mark sits on a session the scan evaluated");

test("a live feed one session ahead does not move the confirmation", () => {
  const barAtDate = new Function(`return (${fnSrc("barAtDate")});`)();
  const mm = new Function("barAtDate", `${fnSrc("momentumMarkers")} return momentumMarkers;`)(barAtDate);
  const DAY = 86400, t0 = Date.UTC(2026, 9, 1) / 1000;
  const bars = Array.from({ length: 14 }, (_, i) => ({ time: t0 + i * DAY, close: 1 }));   // 1..14 Oct
  const iso = (t) => new Date(t * 1000).toISOString().slice(0, 10);
  // EOS on the committed scan: last bar 13 Oct, confirmed 0 bars ago, pivot 5 back.
  const row = { rule_a: true, rule_a_direction: "bear", rule_a_bars_ago: 0, rule_a_pivot_bars_ago: 5,
                rule_a_pivot_bar: "2026-10-08 00:00:00", last_bar: "2026-10-13 00:00:00" };
  const m = mm(row, bars);
  assert.deepEqual(m.map((x) => [x.text, iso(x.time)]), [["BEAR DIV", "2026-10-08"], ["confirmed", "2026-10-13"]],
    "was 'confirmed' on 14 Oct, a session the scan never saw");
  const noDate = Object.assign({}, row, { rule_a_pivot_bar: "" });
  assert.equal(iso(mm(noDate, bars)[0].time), "2026-10-08", "the pivot COUNT anchors on last_bar too");
  const old = Object.assign({}, row, { last_bar: undefined });
  assert.equal(iso(mm(old, bars)[1].time), "2026-10-14", "no last_bar: the chart's last bar, as before");
  const behind = mm(row, bars.slice(0, 12));                                        // chart ends 12 Oct
  assert.equal(iso(behind[1].time), "2026-10-12", "a chart BEHIND the scan snaps to its newest bar");
});

/* ═══════════════ #114 3D groups do not move when the window slides ═══════════ */
suite("#114 Momentum 3D candles are anchored, so a new day regroups nothing");

test("two loads one session apart build the SAME 3D candles", () => {
  const sg = new Function(`${constSrc("MOM_3D_ANCHOR")} ${fnSrc("sessionGroups")} return { sessionGroups, MOM_3D_ANCHOR };`)();
  const days = [];
  for (let t = Date.UTC(2001, 9, 15); t <= Date.UTC(2026, 9, 13); t += 86400000) {
    const d = new Date(t).getUTCDay();
    if (d && d !== 6) days.push({ time: t / 1000, open: t, high: t, low: t, close: t, volume: 1 });
  }
  const iso = (b) => new Date(b.time * 1000).toISOString().slice(0, 10);
  const a = sg.sessionGroups(days.slice(0, -1), 3, sg.MOM_3D_ANCHOR);   // the load on 12 Oct
  const b = sg.sessionGroups(days.slice(1), 3, sg.MOM_3D_ANCHOR);       // 13 Oct: start slid one session
  const recent = (g) => g.filter((x) => iso(x) >= "2025-01-01" && iso(x) <= "2026-10-01").map(iso);
  assert.deepEqual(recent(a), recent(b), "every shared 3D candle starts on the same session");
  const old = (w) => sg.sessionGroups(w, 3).slice(-3).map(iso);
  assert.notDeepEqual(old(days.slice(0, -1)), old(days.slice(1)), "the un-anchored count did regroup (the bug)");
  assert.ok(b.every((x) => x.volume <= 3), "still at most three sessions a candle");
  const young = days.filter((x) => iso(x) >= "2023-03-01");
  assert.deepEqual(sg.sessionGroups(young, 3, sg.MOM_3D_ANCHOR).map(iso), sg.sessionGroups(young, 3).map(iso),
    "a series that starts after the anchor counts from its own (fixed) first bar");
  assert.match(fnSrc("momentumFallback"), /sessionGroups\(daily, 3, MOM_3D_ANCHOR\)/);
});

/* ═══════════════ #112 REPLAY on a Momentum chart shows only the knowable ═══════════ */
suite("#112 Momentum replay clips the panes, tags, labels, box and ATH");

function momMarksHarness(tfs) {
  return new Function("tfs", "el", `const NARROW_CHART_PX = 560;
    ${constSrc("MOM_VIEW_MONTHS")} ${constSrc("MOM_REGIME_MULT")} ${constSrc("MOM_VIEW_MIN_BARS")}
    ${fnSrc("momentumViewStart")} ${fnSrc("momRsiMarks")} ${fnSrc("momPriceMarks")}
    return { momRsiMarks, momPriceMarks };`)(tfs, { clientWidth: 1200 });
}

test("a divergence appears only once its confirming pivot has closed", () => {
  const cs = Array.from({ length: 40 }, (_, i) => ({ time: 1000 + i, close: 1 }));
  const h = momMarksHarness({ "1D": { candles: cs, divs: [
    { bull: true, pivot: 10, confirm: 15 }, { bull: false, pivot: 30, confirm: 35 }] } });
  assert.equal(h.momRsiMarks("1D").length, 2, "outside replay: every divergence");
  assert.deepEqual(h.momRsiMarks("1D", 1033).map((m) => m.text), ["Bull"],
    "at bar 33 the Bear pivot (30) exists but is not CONFIRMED until bar 35");
  assert.deepEqual(h.momRsiMarks("1D", 1035).map((m) => m.text), ["Bull", "Bear"]);
});

test("cross labels stop at the cut; the Rule A pair waits for its confirmation", () => {
  const cs = Array.from({ length: 40 }, (_, i) => ({ time: 1000 + i, close: 1 }));
  const ruleA = [{ time: 1020, text: "BULL DIV" }, { time: 1025, text: "confirmed" }];
  const h = momMarksHarness({ "1D": { candles: cs, markers: ruleA,
    crosses: [{ i: 5, bull: true, score: 2 }, { i: 22, bull: false, score: 3 }, { i: 38, bull: true, score: 1 }] } });
  const at = (t) => h.momPriceMarks("1D", t).map((m) => m.time);
  assert.deepEqual(at(undefined), [1005, 1020, 1022, 1025, 1038], "no cut: everything");
  assert.deepEqual(at(1023), [1005, 1022], "Rule A not yet confirmed at 1023; the 1038 cross not yet printed");
  assert.deepEqual(at(1030), [1005, 1020, 1022, 1025]);
});

test("rApply re-cuts every Momentum series and recomputes the box and ATH at the scrub point", () => {
  const r = fnSrc("rApply");
  for (const s of ["macdHistS", "macdLineS", "macdSigS", "rsiSigS"]) {
    assert.match(r, new RegExp(`${s}\\.setData\\(pn \\? upTo\\(`), `${s} must be clipped in replay`);
  }
  assert.match(r, /rsiS\.setData\(pn \? upTo\(pn\.rsi\) : \[\]\)/);
  assert.match(r, /rsiS\.setMarkers\(momRsiMarks\(curTF, tCut\)\)/);
  assert.match(r, /candle\.setMarkers\(momPriceMarks\(curTF, tCut\)\)/);
  assert.match(r, /applyMomentumPlan\(curTF, idx\)/);
  const a = fnSrc("applyMomentumPlan");
  assert.match(a, /const pl = upto \? momentumPlan\(cs, tfNow\.mp\) : tfNow\.plan;/, "the box as of the cut");
  assert.match(a, /const ath = upto \? cs\.reduce\(/, "the high as of the cut");
  assert.match(fnSrc("momentumFallback"), /tf\.mp = mp;/, "the replay plan uses the scan's own params");
});

/* ═══════════════ #113 the phone sheet survives a rotation ═══════════════ */
suite("#113 the tools FAB follows the sheet, not the viewport width");

test("the sheet marks the body, and the FAB rule keys off that mark", () => {
  assert.match(fnSrc("initMobileSheet"), /document\.body\.classList\.add\("ct-has-sheet"\);/);
  const css = CSS.replace(/\/\*[\s\S]*?\*\//g, "");
  assert.match(css, /body\.ct-has-sheet:not\(\.is-replay\) #ct-fab \{ display: grid; place-items: center; \}/);
  const phone = css.slice(css.indexOf("@media (max-width: 560px) {", css.indexOf("#ct-sheet .draw-btn.is-active::after")));
  assert.ok(!/^\s*#ct-fab \{ display: grid/m.test(phone.slice(0, 400)),
    "a width-only FAB rule hid it in landscape (844x390) with every tool moved into the sheet");
  assert.match(css, /body\.is-replay #ct-fab \{ display: none; \}/, "replay still hides it");
});

/* ═══════════════ #117 the DIV-ADJ chip reads the daily response ═══════════ */
suite("#117 no second Yahoo pull for the dividend chip");

function divHarness(recentDiv, withKey = true) {
  const calls = [];
  const fetch = (url) => {
    calls.push(url);
    const j = { ok: true, bars: 2, candles: [{ time: 1790000000, open: 1, high: 1, low: 1, close: 1 }] };
    if (withKey) j.recent_div = recentDiv;
    return Promise.resolve({ ok: true, json: () => Promise.resolve(url.includes("1mo")
      ? { ok: true, candles: [], recent_div: { date: 1790000000, amount: 0.5 } } : j) });
  };
  const el = { textContent: "", title: "", hidden: true };
  const fns = ["sessionClock", "exchangeDay", "tickerSession", "toExchangeDates", "yahooBars", "yfTickerFor", "checkRecentDividend"];
  const api = new Function("fetch", "market", "$", `let DATA_META = null;
    ${["MOM_SESSION", "_sessFmt", "DAILY_UP_INTERVAL", "YF_TICKER"].map((n) => constSrc(n)).join("\n")}
    ${fns.map((n) => fnSrc(n)).join("\n")}
    return { yahooBars, checkRecentDividend, meta: () => DATA_META };`)(fetch, "asx", (sel) => (sel === "#ct-divadj" ? el : null));
  return { api, calls, el };
}
const tick = () => new Promise((r) => setTimeout(r, 0));

test("the 25y daily response's recent_div drives the chip -- one request, not two", async () => {
  const h = divHarness({ date: Date.parse("2026-10-04T23:00:00Z") / 1000, amount: 0.26 });
  await h.api.yahooBars("BHP.AX", "25y", "1d", true);
  h.api.checkRecentDividend({ symbol: "BHP", asset_type: null });
  await tick(); await tick();
  assert.deepEqual(h.calls, ["/api/price?symbol=BHP.AX&range=25y&interval=1d"], "the 1mo pull is gone");
  assert.equal(h.el.textContent, "Ⓓ DIV-ADJ 5 Oct", "still named on the exchange's calendar");
  assert.equal(h.el.hidden, false);
});

test("an explicit null means no recent dividend: no chip and no second request", async () => {
  const h = divHarness(null);
  await h.api.yahooBars("BHP.AX", "25y", "1d", true);
  h.api.checkRecentDividend({ symbol: "BHP", asset_type: null });
  await tick(); await tick();
  assert.equal(h.calls.length, 1);
  assert.equal(h.el.hidden, true);
});

test("a response that did not say (old payload), or another ticker's capture, still asks", async () => {
  let h = divHarness(null, false);
  await h.api.yahooBars("BHP.AX", "25y", "1d", true);
  h.api.checkRecentDividend({ symbol: "BHP", asset_type: null });
  await tick(); await tick();
  assert.deepEqual(h.calls.slice(1), ["/api/price?symbol=BHP.AX&range=1mo&interval=1d"]);
  h = divHarness(null);
  await h.api.yahooBars("RIO.AX", "25y", "1d", true);
  h.api.checkRecentDividend({ symbol: "BHP", asset_type: null });
  await tick(); await tick();
  assert.equal(h.calls.length, 2, "a capture of a different ticker is not this ticker's answer");
});

/* ═══════════════ #118 ENTRY's distance is measured from the live quote ═══════════ */
suite("#118 the ENTRY tag's '% vs live' follows the live quote");

test("vsLive measures from the live price, says 'scan' until one lands", () => {
  const at = CHART.indexOf("const vsLive = (price) =>");
  assert.ok(at > 0, "render() no longer defines vsLive");
  const src = CHART.slice(at, CHART.indexOf("};", at) + 2);
  const mk = (live, scan) => new Function("liveState", "d", `${src} return vsLive;`)({ price: live }, { price: scan });
  assert.equal(mk(null, 10)(11), " +10.00% vs scan", "before the first quote it is the scan price, and says so");
  assert.equal(mk(12.5, 10)(11), " -12.00% vs live", "after a quote, the quote the header shows");
  assert.equal(mk(11, 10)(11), "", "on the price: nothing to say");
  assert.equal(mk(null, null)(11), "");
});

test("every ENTRY line is re-titled on each tick, through onLiveTick", () => {
  assert.match(CODE, /onLiveTick\(\(\) => entryTags\.forEach\(\(t\) => \{\s*try \{ t\.handle\.applyOptions\(\{ title: t\.base \+ vsLive\(t\.price\) \}\);/);
  const lv = fnSrc("applyVivekLevels");
  assert.match(lv, /entryTags\.length = 0;/, "a TF switch drops the old line's tag");
  assert.match(lv, /if \(isEntry\) entryTags\.push\(\{ handle, price, base: t \}\);/);
  assert.ok(!/\(price - d\.price\) \/ d\.price/.test(CODE) && !/\(L\.price - d\.price\) \/ d\.price/.test(CODE),
    "no ENTRY distance is computed from the frozen scan price any more");
});

/* ═══ (coordinator, from WP5) the browser Binance series reads QUOTE volume ═══ */
test("binanceDirectBars takes k[7] (USD volume), as the proxy and the scan do", () => {
  const f = fnSrc("binanceDirectBars");
  assert.match(f, /volume: \+k\[7\] \|\| 0/);
  assert.ok(!/volume: \+k\[5\]/.test(f), "k[5] is the coin count, not dollars");
});

runQueue().then(() => {
  console.log(`\nchart_refine.test.js: ${passed}/${passed + failed} passed`);
  if (failed) process.exit(1);
});
