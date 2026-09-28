#!/usr/bin/env node
/* IGNITION — the deck pill + panel (public/js/ignition.js), report-only.
 *
 * Runs the REAL functions, sliced out of the shipped file at load time rather
 * than re-typed here (house pattern — a mirrored copy drifts in step with the
 * bug it is supposed to catch), plus the WHOLE module evaluated against a
 * stubbed fetch/document for the lazy-load and hide-when-absent behaviour.
 *
 * What is pinned, and why each matters:
 *   1. The pill's N is the PUBLISHED confirmed count. A break on the forming
 *      bar is a "+p" marker, never part of N; the pill still shows at N = 0
 *      when rows exist so the coiled watchlist stays reachable.
 *   2. States render in the engine's order, provisional after confirmed, and
 *      CLOSED rows are drawn (misses stay visible — survivorship is the enemy).
 *   3. Every interpolated value is escaped: a hostile symbol/name cannot open
 *      a tag or break out of an attribute.
 *   4. The evidence line never invents: a missing field is a dash, an absent
 *      backtest says "Backtest pending".
 *   5. An absent file hides silently (no console.error, no page error); the
 *      live file is only fetched on an Ignition market and the backtest only
 *      once the panel opens; a fault AFTER the fetch is re-raised, not
 *      swallowed by the fetch's catch (TOP100 #88).
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

// ── pull the real declarations out of the shipped file ───────────────────────
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
function fnSrc(name) {
  const at = SRC.indexOf(`function ${name}(`);
  assert.ok(at >= 0, `ignition.js no longer defines function ${name}`);
  for (let i = SRC.indexOf("{", at); i < SRC.length; i++) {
    if (SRC[i] !== "}") continue;
    const cand = SRC.slice(at, i + 1);
    try { new Function("return (" + cand + ");"); return cand; } catch (_) { /* keep walking */ }
  }
  throw new Error(`could not slice function ${name}`);
}

const CONSTS = ["IGNITION_MARKETS", "esc", "DASH", "STATE_ORDER", "EXIT_TEXT", "CAVEAT_FALLBACK"];
const FNS = ["isMarket", "liveUrl", "btUrl", "num", "fmtPx", "fmtPct", "fmtR", "fmtX", "fmtN",
  "toneOf", "rowRank", "groupRows", "countsOf", "pillInfo", "melb", "utcText", "chartHref",
  "kv", "tag", "cardHead", "triggerCardHTML", "coiledCardHTML", "entryStatus", "evidenceHTML",
  "headHTML", "sectionHTML", "panelHTML"];
const build = (win) => new Function("window",
  CONSTS.map(sliceConst).join("\n") + "\n" + FNS.map(fnSrc).join("\n") +
  `\nreturn { ${CONSTS.concat(FNS).join(", ")} };`)(win);
const I = build({ PM: { fmtMelb: (iso) => "MELB[" + iso + "]" } });

// CODE-only view: the reasoning for each ban is written into the source beside
// it, so a naive includes() would read the justification as the offence.
const CODE = SRC.replace(/\/\*[\s\S]*?\*\//g, "").split("\n")
  .filter((l) => !l.trim().startsWith("//")).join("\n");

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
const RUNNING = trig({ symbol: "AAA", name: "AAA Coin", state: "RUNNING", trigger_date: "2026-09-19",
  bars_since: 8, rvol: 5.75, mfe_r: 9.13, price: 219.39, change_pct: 169.6, r_now: 9.36, trail: 167.05 });
const CLOSED = trig({ symbol: "BBB", name: "BBB Coin", state: "CLOSED", trigger_date: "2026-09-17",
  bars_since: 10, mfe_r: 8.52, exit_reason: "trail", exit_date: "2026-09-27",
  exit_price: 151.61902449, exit_r: 4.85, exit_pending: false, r_now: 3.44 });
const PROV = trig({ symbol: "PRV", name: "Prov Coin", provisional: true, rvol: 9.9 });
const payload = (results, counts) => ({
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
});
const SAMPLE = payload([trig(), RUNNING, CLOSED, coiled(),
  coiled({ symbol: "DDD", name: "DDD Coin", coil: { ribbon_pct: 1.68, atr_pctl: 32.9, vol_pctl: 0.1,
    drawdown_pct: 74.8, coiled: false, coiled_bars: 0, last_coiled: "2026-09-26" },
    breakout_level: 67.64, price: 66.77 })]);
const BT = {
  schema_version: 1, lens: "ignition", market: "crypto", ruleset_version: "1.0.0",
  generated_at: "2026-09-28T06:00:00+00:00", date_range: ["2020-01-01", "2026-09-27"],
  caveats: ["SURVIVORSHIP: today's top ~200 coins only.", "Per-trade R, not a portfolio."],
  primary: { n: 8, exp_r: 9.956, median_r: 10.61, pf: 3.4, top5_share_pct: 69.4,
             by_split: { in_sample: { n: 6, exp_r: 10.96 }, out_of_sample: { n: 2, exp_r: 6.943 } } },
  baselines: { random_timing: { n: 40, exp_r: 0.29 } },
};
const noJunk = (html, what) => {
  for (const bad of ["undefined", "NaN", "null", "[object Object]"]) {
    assert.ok(!html.includes(bad), `${what} leaked "${bad}": ${html.slice(0, 300)}`);
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

test("provisional > 0 appends a +p marker whose title says forming bar, unconfirmed", () => {
  const info = I.pillInfo(payload([PROV]));
  assert.ok(info, "a provisional-only day still produces a pill");
  assert.equal(info.n, 0, "a forming-bar break is never counted");
  assert.match(info.mark, /class="ig-pmark"/);
  assert.match(info.mark, />\+p</);
  assert.match(info.mark, /title="[^"]*forming bar, unconfirmed/);
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

// ════════════════════════════════════════════════════════════════════════════
suite("trigger rows");

test("a trigger card carries every field the owner reads", () => {
  const h = I.triggerCardHTML(trig(), "crypto", { wide_stop_pct: 35 });
  for (const s of ["Triggered", "2026-09-27", "Trigger close", "$83.18", "Price", "$103.97",
                   "Since trigger", "+25.0%", "R now", "+1.24R", "Stop", "$66.47", "Risk", "20.1%",
                   "RVOL", "5.8×", "Over 9-SMA", "+23.6%", "MFE", "0.00R", "Measured move",
                   "day 1", "9-SMA trail", "$67.30"]) {
    assert.ok(h.includes(s), `trigger card lost "${s}"`);
  }
  noJunk(h, "trigger card");
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

// ════════════════════════════════════════════════════════════════════════════
suite("escaping — every interpolated value goes through esc");

test("a hostile symbol and name cannot open a tag or break an attribute", () => {
  const evil = `<img src=x onerror=alert(1)>"'&`;
  const rows = [trig({ symbol: evil, name: evil, trigger_date: evil, exit_reason: evil }),
                trig({ symbol: evil, state: "CLOSED", exit_reason: evil, exit_date: evil }),
                coiled({ symbol: evil, name: evil, coil: { coiled: false, last_coiled: evil } })];
  const h = I.panelHTML(payload(rows), "ok",
    Object.assign({}, BT, { caveats: [evil], ruleset_version: evil, date_range: [evil, evil] }), "crypto", true);
  assert.ok(!/<img/i.test(h), "a raw tag reached the panel");
  assert.ok(!/onerror=alert\(1\)>/.test(h.replace(/&lt;img src=x onerror=alert\(1\)&gt;/g, "")),
    "a raw attribute break-out reached the panel");
  assert.ok(h.includes("&lt;img src=x onerror=alert(1)&gt;&quot;&#39;&amp;"), "the name is shown, escaped");
  // The href: percent-encoded, so no quote can close it.
  const hrefs = [...h.matchAll(/href="([^"]*)"/g)].map((m) => m[1]);
  assert.ok(hrefs.length >= 3);
  hrefs.forEach((u) => assert.ok(!/[<>"']/.test(u), `unsafe href ${u}`));
});

test("the +p marker and the pill title are escaped too", () => {
  const info = I.pillInfo(payload([PROV]));
  assert.ok(!/<img|"\s*on\w+=/.test(info.mark));
});

test("esc escapes all five characters and is null-safe", () => {
  assert.equal(I.esc(`&<>"'`), "&amp;&lt;&gt;&quot;&#39;");
  assert.equal(I.esc(null), "");
  assert.equal(I.esc(0), "0");
});

// ════════════════════════════════════════════════════════════════════════════
suite("the evidence line — read, never invented");

test("a full backtest prints every number off the file", () => {
  const h = I.evidenceHTML("ok", BT, { ruleset_version: "1.0.0" });
  for (const s of ["trades <b>8</b>", "expectancy <b>+9.96R</b>", "median <b>+10.61R</b>",
                   "PF <b>3.40</b>", "out-of-sample exp <b>+6.94R</b>", "random-timing exp <b>+0.29R</b>",
                   "top-5 share <b>69.4%</b>", "survivor-biased universe"]) {
    assert.ok(h.includes(s), `evidence lost "${s}"`);
  }
  assert.match(h, /class="ig-ev-cav" title="SURVIVORSHIP: today&#39;s top ~200 coins only\.\n\nPer-trade R, not a portfolio\."/);
  assert.ok(!/ig-ev-warn/.test(h), "same ruleset, no drift warning");
});

test("missing fields render as a dash — PF null (no losing trade) is a dash, not infinity or 0", () => {
  const h = I.evidenceHTML("ok", { primary: { n: 8, pf: null }, caveats: [] }, null);
  noJunk(h, "sparse evidence");
  assert.match(h, /PF <b>—<\/b>/);
  assert.match(h, /out-of-sample exp <b>—<\/b>/);
  assert.match(h, /random-timing exp <b>—<\/b>/);
  assert.match(h, /trades <b>8<\/b>/);
  assert.match(h, /survivor-biased universe/, "the caveat is never dropped, even with no caveats array");
  noJunk(I.evidenceHTML("ok", {}, null), "empty backtest object");
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

// Evaluate the WHOLE shipped file against stubs. `fetch`, `document`,
// `console` and `setTimeout` are parameters, so they shadow the globals.
function runModule(respond) {
  const calls = [];
  const errors = [];
  const timers = [];
  const listeners = [];
  const host = { hidden: true, innerHTML: "", querySelector: () => null };
  const doc = {
    getElementById: (id) => (id === "ignition-panel" ? host : null),
    addEventListener: (t, fn) => listeners.push([t, fn]),
  };
  const fetchStub = (url, opts) => { calls.push({ url, opts }); return respond(url); };
  const win = { PM: { fetchTimeout: fetchStub, fmtMelb: (iso) => "MELB[" + iso + "]" } };
  const con = { error: (...a) => errors.push(a), warn: (...a) => errors.push(a), log: () => {} };
  new Function("window", "document", "fetch", "console", "setTimeout", SRC)(
    win, doc, fetchStub, con, (fn) => timers.push(fn));
  return { Ig: win.Ignition, calls, errors, timers, host, listeners };
}
const ok200 = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
const r404 = () => Promise.resolve({ ok: false, status: 404, json: () => Promise.reject(new Error("no")) });
const flush = () => new Promise((r) => setImmediate(r));

test("the module exports window.Ignition and binds one delegated click listener", () => {
  const m = runModule(() => r404());
  assert.deepEqual(Object.keys(m.Ig).sort(), ["MARKETS", "isMarket", "pill", "sync", "toggle"]);
  assert.deepEqual(m.Ig.MARKETS, ["crypto"]);
  assert.deepEqual(m.listeners.map((l) => l[0]), ["click"]);
});

test("a non-Ignition market fetches nothing and gets no pill", async () => {
  const m = runModule(() => ok200(SAMPLE));
  assert.equal(m.Ig.pill("asx", () => {}), null);
  assert.equal(m.Ig.pill("nasdaq", () => {}), null);
  await flush();
  assert.equal(m.calls.length, 0);
});

test("an ABSENT live file (404) hides silently: no pill, no console.error, no page error", async () => {
  const m = runModule(() => r404());
  let ready = 0;
  assert.equal(m.Ig.pill("crypto", () => { ready++; }), null, "no pill before the load settles");
  await flush(); await flush();
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
    await flush(); await flush();
    assert.equal(m.Ig.pill("crypto"), null);
    assert.deepEqual(m.errors, []);
    assert.equal(m.timers.length, 0);
  }
});

test("the live file is fetched once through PM.fetchTimeout with no-cache, then served from cache", async () => {
  const m = runModule((url) => ok200(url.endsWith("_backtest.json") ? BT : SAMPLE));
  m.Ig.pill("crypto", () => {});
  m.Ig.pill("crypto", () => {});          // in flight: no second request
  await flush(); await flush();
  const info = m.Ig.pill("crypto", () => {});
  assert.equal(info.n, 1);
  assert.equal(m.calls.length, 1);
  assert.equal(m.calls[0].opts.cache, "no-cache");
});

test("the backtest is fetched ONLY when the panel opens, and the panel then renders", async () => {
  const m = runModule((url) => ok200(url.endsWith("_backtest.json") ? BT : SAMPLE));
  m.Ig.pill("crypto", () => {});
  await flush(); await flush();
  m.Ig.sync("crypto");
  assert.equal(m.host.hidden, true, "closed panel stays hidden");
  assert.equal(m.calls.length, 1, "no backtest fetch while closed");
  assert.equal(m.Ig.toggle("crypto"), true);
  m.Ig.sync("crypto");
  assert.equal(m.host.hidden, false);
  assert.match(m.host.innerHTML, /Backtest loading/);
  assert.deepEqual(m.calls.map((c) => c.url), ["data/ignition/crypto.json", "data/ignition/crypto_backtest.json"]);
  await flush(); await flush();
  assert.match(m.host.innerHTML, /expectancy <b>\+9\.96R<\/b>/, "the evidence line repaints when the file lands");
  assert.equal(m.Ig.pill("crypto").open, true, "the pill reports the panel as open");
  // Switching market hides it; switching back shows it again without refetching.
  m.Ig.sync("asx");
  assert.equal(m.host.hidden, true);
  m.Ig.sync("crypto");
  assert.equal(m.host.hidden, false);
  assert.equal(m.calls.length, 2);
  assert.equal(m.Ig.toggle("crypto"), false);
  m.Ig.sync("crypto");
  assert.equal(m.host.hidden, true);
  assert.deepEqual(m.errors, []);
});

test("an absent backtest renders 'Backtest pending' in an open panel", async () => {
  const m = runModule((url) => (url.endsWith("_backtest.json") ? r404() : ok200(SAMPLE)));
  m.Ig.pill("crypto", () => {});
  await flush(); await flush();
  m.Ig.toggle("crypto");
  m.Ig.sync("crypto");
  await flush(); await flush();
  assert.match(m.host.innerHTML, />Backtest pending</);
  assert.deepEqual(m.errors, []);
});

test("a fault AFTER the fetch is re-raised to window.onerror, not swallowed as 'absent'", async () => {
  const m = runModule(() => ok200(SAMPLE));
  m.Ig.pill("crypto", () => { throw new Error("renderer bug"); });
  await flush(); await flush();
  assert.equal(m.timers.length, 1, "the fault must be re-raised asynchronously");
  assert.throws(() => m.timers[0](), /renderer bug/);
  assert.ok(m.Ig.pill("crypto"), "and the data it loaded is still there — the fault was not mistaken for a 404");
});

test("source order: the catch sits on the fetch+parse, the callback runs after it", () => {
  const load = fnSrc("load");
  const c = load.indexOf(".catch(");
  const cb = load.indexOf("cb(market)");
  assert.ok(c > 0 && cb > c, "the onReady callback must run AFTER the fetch's catch");
  assert.equal((load.match(/\.catch\(/g) || []).length, 1, "exactly one catch, on the fetch");
});

// ════════════════════════════════════════════════════════════════════════════
suite("wiring + fences");

test("app.js places the pill straight after ◎ At level and routes it through pill()", () => {
  const fn = APP.slice(APP.indexOf("function renderDeckPills("), APP.indexOf("// ----------------------------------------------------------- a row"));
  const at = fn.indexOf(`"◎ At level"`);
  const ig = fn.indexOf(`"⚡ Ignition"`);
  const top = fn.indexOf(`(top ? `);
  assert.ok(at > 0 && ig > at && top > ig, "Ignition must sit after At level and before the top pick");
  assert.match(fn, /pill\(`data-ignition="1"[^`]*`, "ig", "⚡ Ignition", ign\.n, ign\.title, ign\.open, ign\.mark\)/);
  assert.match(fn, /window\.Ignition\.pill\(state\.market,/);
  assert.match(fn, /window\.Ignition\.toggle\(state\.market\)/);
  assert.match(fn, /window\.Ignition\.sync\(state\.market\)/);
  assert.ok(!/data-pill="ignition"/.test(fn),
    "it is not a list filter: a data-pill would re-render the rows on every tap");
  assert.match(fn, /\$\{extra \|\| ""\}<\/button>/, "pill() appends the +p marker after the count");
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

test("the CSS lets [hidden] win and styles the pill", () => {
  assert.match(CSS, /\.ig-panel\[hidden\]\s*\{\s*display:\s*none;/);
  assert.match(CSS, /\.fpill\.ig\s*\{/);
  assert.match(CSS, /\.ig-pmark\s*\{/);
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
