#!/usr/bin/env node
/* The journal's owner items 6-9 (2026-11-02), run on the SHIPPED code.

   6  the pre-registered checkpoint strip: journal.js prEvaluate is a mirror of
      scripts/decision_pack.py evaluate(). Both are held to ONE file of shared
      cases, tests/fixtures/checkpoint_cases.json (expected verdicts produced
      by decision_pack; tests/test_checkpoint_mirror.py re-derives them in
      Python, this suite runs the JS over the same file).
   7  the cumulative-R chart, rules vs by hand, with cycle-start markers.
   8  the open table's time-stop countdown, counted the way the engine counts
      (vivek_run: a pre-TP1 row closes once it has been held MORE than
      max_hold_days in its market's calendar -- day 29, never day 28).
   9  the room to the stop and to the next target, in R of the entry risk, and
      the Now price read from the row's own mark.

   Every function is sliced out of public/js/journal.js -- re-typing them here
   would test a copy.

   Run with: node test/journal_checkpoints.test.js
*/
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(path.resolve(__dirname, "../public/js/journal.js"), "utf8");
const CASES = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../tests/fixtures/checkpoint_cases.json"), "utf8"));

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓  ${name}`); passed++; }
  catch (e) { console.error(`  ✗  ${name}\n     ${e.message}`); failed++; }
}
function suite(name) { console.log(`\n── ${name} ──`); }
function slice(startMarker, endMarker) {
  const a = SRC.indexOf(startMarker);
  assert.ok(a >= 0, `journal.js no longer contains "${startMarker}" — was it renamed?`);
  const b = SRC.indexOf(endMarker, a + startMarker.length);
  assert.ok(b > a, `could not find the end of "${startMarker}"`);
  return SRC.slice(a, b + endMarker.length);
}

const ctx = vm.createContext({ console, Intl, Date, Math, Number, String, JSON, BigInt });
vm.runInContext(
  slice("/* PREREG-BEGIN */", "/* PREREG-END */") + "\n"
  + slice("const PREREG_COHORT =", ";\n") + "\n"
  + slice("const MECHANICAL_EXITS =", ";\n") + "\n"
  + slice("function pyRound(x, nd) {", "\n  }") + "\n"
  + slice("const prR = ", ";\n") + "\n"
  + slice("const prIsRules = ", ";\n") + "\n"
  + slice("const prStr = ", ";\n") + "\n"
  + slice("const prDay = ", ";\n") + "\n"
  + slice("function prStats(rows) {", "\n  }") + "\n"
  + slice("function prSelect(rows, spec) {", "\n  }") + "\n"
  + slice("function prRead(rows, n) {", "\n  }") + "\n"
  + slice("function prTrips(pr, pool, rows, cutoff, line) {", "\n  }") + "\n"
  + slice("const prCycle = ", ";\n") + "\n"
  + slice("function prEvaluate(pr, closed) {", "\n  }") + "\n"
  + slice("const SHADOW_MARKETS = ", ";\n") + "\n"
  + slice("function prWhatifD14(r, floor) {", "\n  }") + "\n"
  + slice("function prEvaluateShadow(pr, closed) {", "\n  }") + "\n"
  // items 8/9 + the chart's series
  + "let MAX_HOLD_DAYS = 28;\n"
  + slice("const MARKET_TZ =", ";\n") + "\n"
  + "const STOCK_TYPES = new Set(['asx', 'nasdaq']); const NONCRYPTO = new Set();\n"
  + slice("function isCryptoTrade(t) {", "\n  }") + "\n"
  + slice("function marketOf(t) {", "\n  }") + "\n"
  + slice("const finiteOr = ", ";\n") + "\n"
  + slice("function markOf(t) {", "\n  }") + "\n"
  + slice("function roomOf(t) {", "\n  }") + "\n"
  + slice("function marketDay(mkt, ms) {", "\n  }") + "\n"
  + slice("function timeStopOf(t, ms) {", "\n  }") + "\n"
  + slice("const round = (v, n)", ";\n") + "\n"
  + slice("const ymd = (d) =>", ";\n") + "\n"
  + slice("function exitMs(t) {", "\n  }") + "\n"
  + slice("function exitDay(t) {", "\n  }") + "\n"
  + slice("const byExit = (closed) =>", ";\n") + "\n"
  + slice("const isMechanical = ", ";\n") + "\n"
  + slice("function rulesHandSeries(closed) {", "\n  }") + "\n"
  + slice("function cycleStarts(d) {", "\n  }") + "\n"
  + slice("function rulesHandByCycle(closed) {", "\n  }") + "\n"
  + "this.api = { PREREG, PREREG_COHORT, pyRound, prEvaluate, prEvaluateShadow, markOf, roomOf, timeStopOf, marketDay,"
  + " rulesHandSeries, cycleStarts, rulesHandByCycle, setHold: (n) => { MAX_HOLD_DAYS = n; } };",
  ctx);
const J = ctx.api;

// Every key decision_pack returns must match; the mirror may add `second`
// (which read it was) for the strip's wording, nothing else.
const same = (a, b) => (a === b) || (a == null && b == null);   // 0 === -0 on purpose
const deepSame = (a, b) => (a && typeof a === "object" && b && typeof b === "object")
  ? Object.keys(b).every((k) => deepSame(a[k], b[k])) && Object.keys(a).every((k) => k in b)
  : same(a, b);
const judgedEntries = () => J.PREREG.filter((p) => p.kind === "live" || p.kind === "shadow");
const runJs = (pr, closed) => (pr.kind === "shadow" ? J.prEvaluateShadow(pr, closed) : J.prEvaluate(pr, closed));

// ── 6. the checkpoints ───────────────────────────────────────────────────────
suite("6 · prEvaluate == decision_pack.evaluate on every shared case");

test("pyRound is Python's round() on every rounding case", () => {
  for (const [x, nd, want] of CASES.round_cases) {
    assert.ok(same(J.pyRound(x, nd), want), `round(${x}, ${nd}): JS ${J.pyRound(x, nd)} vs Python ${want}`);
  }
});

test("the shared cases are all present and every judged checkpoint is covered", () => {
  assert.ok(CASES.cases.length >= 20, "the shared case file shrank");
  const ids = judgedEntries().map((p) => p.id);
  assert.equal(ids.join(","), "PR-0,PR-1,PR-2,PR-3,PR-9,PR-10,PR-11,PR-12,PR-13,PR-14,PR-15,PR-16");
  for (const c of CASES.cases) for (const id of ids) assert.ok(c.expect[id], `${c.name}: no ${id}`);
  assert.ok(CASES.cases.some((c) => c.expect["PR-16"].verdict === "TRIPPED"), "no case trips the day-14 shadow");
});

for (const c of CASES.cases) {
  test(`case: ${c.name}`, () => {
    for (const pr of judgedEntries()) {
      const got = runJs(pr, c.closed);
      const want = c.expect[pr.id];
      for (const k of Object.keys(want)) {
        assert.ok(deepSame(got[k], want[k]), `${pr.id}.${k}: JS ${JSON.stringify(got[k])} vs decision_pack ${JSON.stringify(want[k])}`);
      }
      for (const k of Object.keys(got)) {
        assert.ok(k in want || k === "second", `${pr.id}: the mirror grew a key decision_pack does not have: ${k}`);
      }
    }
  });
}

test("the checkpoints judge hc4-1 whatever cycle is current", () => {
  assert.equal(J.PREREG_COHORT.tag, "hc4-1");
  const rows = Array.from({ length: 25 }, (_, i) => ({ symbol: "S" + i, cycle: "hc4-2", timeframe: "3D",
    entry_type: "reclaim", exit_reason: "stop", realized_r: -1, exit_date: "2026-12-01", market: "asx" }));
  assert.equal(J.prEvaluate(J.PREREG[1], rows).verdict, "NOT DUE", "an hc4-2 close leaked into an hc4-1 checkpoint");
});

test("the strip is inert: no button, link or handler in checkpointLine", () => {
  const body = slice("function checkpointLine(d) {", "\n  }") + slice("function checkpointFold(d, tag) {", "\n  }");
  assert.ok(!/<button|<a\s|onclick|data-osort|data-closeall|addEventListener/.test(body),
    "a control appeared in the checkpoint strip — it must stay a record, never a prompt");
  assert.ok(/<details class="jr-pr-fold" data-cycle=/.test(body) && !/<details[^>]*\bopen\b/.test(body), "the fold must ship shut");
});

test("renderSide draws it beside the cycle board and keeps the fold's state over a repaint", () => {
  const body = slice("function renderSide(side) {", "\n  }");
  // d0 = the whole book: the cycle switch (2 Nov) narrows the stats, the
  // curve and the closed table, never the checkpoints.
  assert.ok(/host\.insertAdjacentHTML\("beforebegin", checkpointLine\(d0\)\)/.test(body), "renderSide no longer draws the strip");
  assert.ok(/document\.querySelectorAll\("#bot-pr"\)\.forEach\(\(el\) => el\.remove\(\)\)/.test(body),
    "no remove-before-insert for #bot-pr — every 3-minute refresh would stack another strip");
  assert.ok(/const prOpen = \[\.\.\.document\.querySelectorAll\("#bot-pr details\[open\]"\)\]\.map\(\(f\) => f\.dataset\.cycle\)/.test(body),
    "an open fold would snap shut on every repaint");
});

test("the dead n/30 review line is gone, host and all", () => {
  const code = SRC.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  assert.ok(!/review-checkpoint/.test(code), "the #review-checkpoint writer is back");
  assert.ok(!/Strategy review checkpoint:/.test(code), "the n/30 wording is back");
  const html = fs.readFileSync(path.resolve(__dirname, "../public/journal.html"), "utf8");
  assert.ok(!/review-checkpoint/.test(html));
});

// ── 8. the time stop ─────────────────────────────────────────────────────────
suite("8 · the time-stop countdown counts the way the engine does");

// 2026-11-02 12:00 UTC: 23:00 Sydney (Nov 2), 07:00 New York (Nov 2).
const NOW = Date.parse("2026-11-02T12:00:00Z");
const pos = (o) => Object.assign({ symbol: "X", market: "nasdaq", direction: "long", entry: 10, stop: 9,
  risk: 1, tp1: 11, tp2: 12, tp3: 13, last_mark: 10.5, entry_date: "2026-10-13" }, o || {});

test("day 29 is the time-stop day, not day 28", () => {
  // entered Tue 13 Oct: day 28 is Tue 10 Nov (held, not closed), day 29 Wed 11 Nov
  const t = J.timeStopOf(pos(), NOW);
  assert.equal(t.due, "2026-11-11");
  assert.equal(t.left, 9);
  assert.equal(t.held, 20);
});

test("a stock whose day 29 is a weekend goes at the next session", () => {
  // entered Fri 2 Oct: day 29 is Sat 31 Oct -> Mon 2 Nov
  assert.equal(J.timeStopOf(pos({ entry_date: "2026-10-02" }), NOW).due, "2026-11-02");
  // crypto has no weekend
  assert.equal(J.timeStopOf(pos({ market: "crypto", entry_date: "2026-10-02" }), NOW).due, "2026-10-31");
});

test("past the day it reads due (left <= 0)", () => {
  assert.ok(J.timeStopOf(pos({ entry_date: "2026-10-02" }), NOW).left <= 0);
});

test("a runner past TP1 has no time stop, and 0 switches it off", () => {
  assert.equal(J.timeStopOf(pos({ tp1_hit: true }), NOW), null);
  J.setHold(0);
  try { assert.equal(J.timeStopOf(pos(), NOW), null); } finally { J.setHold(28); }
});

test("days are counted in the MARKET's calendar, not the viewer's", () => {
  // 2026-11-02T14:00Z is already 3 Nov in Sydney but still 2 Nov in New York
  const at = Date.parse("2026-11-02T14:00:00Z");
  assert.equal(J.marketDay("asx", at), "2026-11-03");
  assert.equal(J.marketDay("nasdaq", at), "2026-11-02");
  const asx = J.timeStopOf(pos({ market: "asx" }), at), us = J.timeStopOf(pos(), at);
  assert.equal(asx.left, us.left - 1);
});

test("the time sort and the stalled strip agree on the day (held > max, not >=)", () => {
  const st = fs.readFileSync(path.resolve(__dirname, "../public/js/stalled.js"), "utf8");
  assert.ok(/maxHold \+ 1 - held/.test(st), "stalled.js counts to day 28 again — the two surfaces would disagree");
});

// ── 9. room to the stop and the target ───────────────────────────────────────
suite("9 · room to the stop / next target, in R of the entry risk");

test("a fresh long: price room to the stop and to TP1", () => {
  const r = J.roomOf(pos());
  assert.equal(r.stop, 1.5);
  assert.equal(r.target, 0.5);
  assert.equal(r.tp, "TP1");
});

test("past TP1 the target is TP2 and the stop distance is to the moved stop", () => {
  const r = J.roomOf(pos({ tp1_hit: true, stop: 10, last_mark: 11.5 }));
  assert.equal(r.tp, "TP2");
  assert.equal(r.target, 0.5);
  assert.equal(r.stop, 1.5);
});

test("past TP3 there is no target left", () => {
  const r = J.roomOf(pos({ tp1_hit: true, tp2_hit: true, tp3_hit: true, last_mark: 14 }));
  assert.equal(r.target, null);
  assert.equal(r.tp, null);
});

test("no mark or no risk is UNKNOWN (null), never zero", () => {
  const r = J.roomOf(pos({ last_mark: null, unreal_r: null }));
  assert.equal(r.stop, null);
  assert.equal(J.roomOf(pos({ risk: 0 })).stop, null);
});

test("Now is the row's own mark — not entry + unreal_r x risk, which shrinks a part-booked runner", () => {
  // booked 25% at TP1: unreal_r is scaled to the 75% still open
  const t = pos({ last_mark: 12, unreal_r: 1.5, booked_pct: 0.25, tp1_hit: true });
  assert.equal(J.markOf(t), 12);
  // without a mark, the fallback undoes the scaling instead of reading 11.5
  assert.equal(J.markOf(Object.assign({}, t, { last_mark: null })), 12);
});

// ── 7. the chart's series ────────────────────────────────────────────────────
suite("7 · cumulative R, rules vs by hand");

const cl = (sym, r, reason, exit, cycle, entry) => ({ symbol: sym, realized_r: r, exit_reason: reason,
  exit_date: exit, cycle, entry_date: entry || exit, status: "closed" });

test("one point per exit day, both running totals, the journal's own rules/hand split", () => {
  const pts = J.rulesHandSeries([
    cl("A", -1, "stop", "2026-09-01"), cl("B", 0.5, "manual", "2026-09-01"),
    cl("C", 0.25, "time", "2026-09-03"), cl("D", 1, undefined, "2026-09-04"),
  ]);
  // compared as JSON: arrays built inside the vm carry its realm's prototype
  assert.equal(JSON.stringify(pts.map((p) => [p.day, p.rules, p.hand, p.rn, p.hn])), JSON.stringify([
    ["2026-09-01", -1, 0.5, 1, 1], ["2026-09-03", -0.75, 0.5, 2, 1], ["2026-09-04", -0.75, 1.5, 2, 2]]));
});

test("cycle starts are each tag's first entry date, read off the rows", () => {
  const s = J.cycleStarts({ open: [{ cycle: "hc4-1", entry_date: "2026-09-22" }],
    closed: [cl("A", 0, "stop", "2026-09-30", "hc4-1", "2026-09-21"), cl("B", 0, "stop", "2026-08-20", "w3-1", "2026-08-03"),
             cl("C", 0, "stop", "2026-07-20", null, "2026-07-01")] });
  assert.equal(JSON.stringify(s.map((x) => [x.tag, x.day])), JSON.stringify([["w3-1", "2026-08-03"], ["hc4-1", "2026-09-21"]]));
});

test("the table view totals each cycle (untagged rows = before the cycles)", () => {
  const t = J.rulesHandByCycle([cl("A", -1, "stop", "2026-09-01", "w3-1"), cl("B", 2, "manual", "2026-09-02", "w3-1"),
                                cl("C", 0.5, "time", "2026-07-02", null)]);
  const w3 = t.find((x) => x.cycle === "w3-1"), pre = t.find((x) => x.cycle === "");
  assert.deepEqual([w3.rn, w3.rr, w3.hn, w3.hr], [1, -1, 1, 2]);
  assert.deepEqual([pre.rn, pre.rr], [1, 0.5]);
});

test("one R axis: the chart draws no $ and no second scale", () => {
  const body = slice("function drawRulesHand(elId, d) {", "\n  }");
  assert.ok(!/dollarsOf|risk_usd|unreal_usd/.test(body), "a $ series crept into the R chart");
  assert.equal((body.match(/const Y = /g) || []).length, 1, "a second y-scale appeared");
});

test("the hover layer reads both lines, and builds its text with textContent", () => {
  const body = slice("function rhShow(i) {", "\n  }");
  assert.ok(/\["rules", "rules"/.test(body) && /\["hand", "by hand"/.test(body));
  assert.ok(!/innerHTML/.test(body), "the tooltip must not build markup from strings");
});

// ── 10. the deck's per-cell record ───────────────────────────────────────────
suite("10 · the deck's live per-cell record == the journal's cycle board");

const APP = fs.readFileSync(path.resolve(__dirname, "../public/js/app.js"), "utf8");
function sliceFrom(src, startMarker, endMarker) {
  const a = src.indexOf(startMarker);
  assert.ok(a >= 0, `missing "${startMarker}"`);
  const b = src.indexOf(endMarker, a + startMarker.length);
  return src.slice(a, b + endMarker.length);
}

test("app.js cellRecord counts exactly what journal.js cycleCells counts, cell by cell", () => {
  const cellRecord = new Function("return (" + sliceFrom(APP, "const cellRecord = (b, tag, rules) => {", "\n  };")
    .replace("const cellRecord = ", "").slice(0, -1) + ");")();
  const board = new Function(
    sliceFrom(SRC, "const MECHANICAL_EXITS =", ";\n") + "\n"
    + sliceFrom(SRC, "function cycleCells(d, tag, cells) {", "\n  }") + "\nreturn cycleCells;")();
  const live = CASES.cases.find((c) => c.name.startsWith("live book")).closed;
  const extra = [   // what the board must ignore too: other cycles, hand closes, no reason
    { cycle: "hc4-1", timeframe: "3D", entry_type: "reclaim", exit_reason: "manual", realized_r: 5 },
    { cycle: "hc4-1", timeframe: "1W", entry_type: "reclaim", realized_r: 3 },
    { cycle: "w3-1", timeframe: "3D", entry_type: "reclaim", exit_reason: "stop", realized_r: -1 },
  ];
  const book = { open: [], closed: live.concat(extra) };
  const cells = [["1W", "reclaim"], ["1W", "break"], ["3D", "reclaim"], ["1D", "break"]];
  const rec = cellRecord(book, "hc4-1");
  const rows = board(book, "hc4-1", cells);
  for (const c of rows.filter((x) => x.tf)) {
    const k = `${c.tf} ${c.et}`;
    const mine = rec[k] || { n: 0, r: 0 };
    assert.equal(mine.n, c.rules, `${k}: deck n=${mine.n} vs board ${c.rules}`);
    assert.ok(Math.abs(mine.r - c.rulesR) < 1e-9, `${k}: deck ${mine.r} vs board ${c.rulesR}`);
  }
  // and the live numbers the owner was given: 3D reclaim 30 rules closes, -10.78R
  assert.equal(rec["3D reclaim"].n, 30);
  assert.ok(Math.abs(rec["3D reclaim"].r - -10.78) < 0.01, String(rec["3D reclaim"].r));
});

test("the record rides the High-conviction badge's title and the expanded panel, not the chip strip", () => {
  const badge = sliceFrom(APP, "function hiconvBadge(r) {", "\n  }");
  assert.ok(/cellRecordNote\(cell\)/.test(badge), "the badge title no longer carries the live record");
  // PR-6 (owner, 2026-11-02): the badge is a plain "Bot cell" tag -- no gold,
  // no stacked marks -- and it is SHORTER than the old label, so the phone's
  // two-whole-chip fit (UI100 #32) only gets easier.
  assert.ok(/`Bot cell\$\{cells\.length > 1 \? ` ×\$\{cells\.length\}` : ""\}\$\{nt \? ` · \$\{esc\(nt\.short\)\}` : ""\}<\/span>`;/.test(badge),
    "the bot-cell tag's visible label changed");
  // 2 Nov: the "not taken" reason rides INSIDE the tag (no new chip), so its
  // words stay short enough for the phone's two whole chips.
  const nt = sliceFrom(APP, "const NOT_TAKEN = {", "\n  };");
  const shorts = [...nt.matchAll(/^\s+\w+: \["([^"]+)",/gm)].map((m) => m[1]);
  assert.ok(shorts.length >= 10 && shorts.every((w) => w.length <= 12), JSON.stringify(shorts));
  assert.ok(!/🎯|High conviction<\/span>/.test(badge.replace(/\/\/[^\n]*/g, "")),
    "the demoted badge is gold again");
  const detail = sliceFrom(APP, "function detailHtmlVivek(r) {", "\n  }");
  assert.ok(/cellRecordNote\(cell, true\)/.test(detail) && /vk-cellrec/.test(detail),
    "the expanded panel lost its per-cell record chip");
});

test("no rules file, no note: the cycle is never guessed", () => {
  assert.ok(/const tag = rules && typeof rules\.cycle_tag === "string" \? rules\.cycle_tag\.trim\(\) : "";/.test(APP));
  assert.ok(/const rec = tag \? \{ tag, cells: cellRecord\(b, tag, rules\) \} : null;/.test(APP));
});

test("the deck's cell record counts the PUBLISHED rules exits (NEXT100 #9)", () => {
  const cellRecord = new Function("return (" + sliceFrom(APP, "const cellRecord = (b, tag, rules) => {", "\n  };")
    .replace("const cellRecord = ", "").slice(0, -1) + ");")();
  const row = (exit_reason, realized_r) => ({ cycle: "hc4-3", timeframe: "3D", entry_type: "reclaim",
    exit_reason, realized_r });
  const book = { closed: [row("stop", -1), row("d14", 0.25), row("manual", 2)] };
  // no rules file: the fallback list -- a new reason is not yet a rules exit
  assert.deepEqual(cellRecord(book, "hc4-3")["3D reclaim"], { n: 1, r: -1 });
  // a published list that names it: counted, and "manual" still never is
  const pub = { rules_exits: ["stop", "time", "trail", "target", "d14"] };
  assert.deepEqual(cellRecord(book, "hc4-3", pub)["3D reclaim"], { n: 2, r: -0.75 });
  // empty, malformed or blank lists keep the fallback rather than count nothing
  for (const bad of [[], "stop", [1, 2], [" "], null]) {
    assert.deepEqual(cellRecord(book, "hc4-3", { rules_exits: bad })["3D reclaim"], { n: 1, r: -1 },
      JSON.stringify(bad));
  }
});

// ── the owner's "20 more" (2 Nov): slots, sectors, day 14, the cycle switch ──
suite("20 more · the slots line, the sector-load fold, the day-14 sub-line, the cycle switch");
{
  const cx = vm.createContext({ console, Intl, Date, Math, Number, String, JSON, Object, Array, isFinite });
  vm.runInContext(
    slice("const esc = (s) =>", ";\n") + "\n" + slice("const rfmt = (r) =>", ";\n") + "\n"
    + slice("/* PREREG-BEGIN */", "/* PREREG-END */") + "\n"
    + "var MAX_OPEN = 60, CAPACITY = null, SECTOR_CAP = 6, LIVE_CYCLE = 'hc4-2', cycleView = 'all';\n"
    + slice("const fmtDue = (iso) => {", "\n  };") + "\n"
    + slice("function capacityText(nOpen) {", "\n  }") + "\n"
    + slice("function sectorLoadHTML() {", "\n  }") + "\n"
    + slice("function d14Sub(t) {", "\n  }") + "\n"
    + slice("function cyclesIn(d) {", "\n  }") + "\n"
    + slice("function cyclePick(d) {", "\n  }") + "\n"
    + slice("const inView = ", ";\n") + "\n"
    + "this.J2 = { capacityText, sectorLoadHTML, d14Sub, cyclesIn, cyclePick, inView,"
    + " set: (k, v) => { eval(k + ' = v'); } };", cx);
  const J2 = cx.J2;
  const DUE = [["2026-11-11", 2], ["2026-11-12", 1], ["2026-11-16", 9], ["2026-11-18", 3], ["2026-11-19", 5], ["2026-11-25", 7]];

  test("a full book says when slots free, on the engine's days, and what takes the first one", () => {
    J2.set("CAPACITY", { time_stops_due: DUE });
    const t = J2.capacityText(60);
    assert.ok(t.startsWith("60 of 60 slots · full. Slots free as time stops fall due: Wed 11 Nov (2) · Thu 12 Nov (1) · Mon 16 Nov (9) · Wed 18 Nov (3) · 12 more by Wed 25 Nov"), t);
    assert.ok(/unless a stop or TP1 comes first\. hc4-2 takes its first trade in the first free slot\.$/.test(t), t);
    assert.equal(J2.capacityText(57), "3 of 60 slots free.");
    J2.set("CAPACITY", null);
    assert.equal(J2.capacityText(60), "60 of 60 slots · full.", "no capacity block: no guessed day");
    J2.set("MAX_OPEN", null);
    assert.equal(J2.capacityText(60), "", "no cap known: nothing at all");
    J2.set("MAX_OPEN", 60);
  });

  test("the sector fold marks every GICS sector at the cap, per market", () => {
    J2.set("CAPACITY", { sector_load: { nasdaq: { "health care": 6, financials: 6, industrials: 5 }, asx: { materials: 5 } } });
    const { html, full } = J2.sectorLoadHTML();
    assert.equal(full, 2);
    assert.ok(html.indexOf("<b>ASX</b>") < html.indexOf("<b>NASDAQ</b>"));
    assert.match(html, /<span class="jr-sec jr-sec-full">financials 6\/6<\/span> · <span class="jr-sec jr-sec-full">health care 6\/6<\/span> · <span class="jr-sec">industrials 5\/6<\/span>/);
    J2.set("SECTOR_CAP", 0);
    assert.equal(J2.sectorLoadHTML().html, "", "no cap published: no fold");
    J2.set("SECTOR_CAP", 6);
  });

  test("the day-14 sub-line reads the engine's stamp and says whether PR-16's cut would have closed it", () => {
    assert.equal(J2.d14Sub({}), "");
    const kept = J2.d14Sub({ d14: { day: "2026-11-02", held: 15, mfe_r: 0.624, r: 0.596, tp1_hit: false } });
    assert.match(kept, /^<span class="num-sub jr-d14" title="[^"]*would have kept it\.">d14 \+0\.60R<\/span>$/);
    const cut = J2.d14Sub({ d14: { day: "2026-11-02", held: 14, mfe_r: 0.31, r: -0.2, tp1_hit: false } });
    assert.match(cut, /jr-d14 jr-d14-cut/);
    assert.match(cut, /best under \+0\.5R/);
    assert.ok(!/jr-d14-cut/.test(J2.d14Sub({ d14: { day: "x", held: 14, mfe_r: 0.2, r: 1.1, tp1_hit: true } })),
      "past TP1 the cut never applies");
  });

  test("the cycle switch lists the book's cycles oldest first and filters only when one is picked", () => {
    const book = { closed: [{ cycle: "hc4-1", entry_date: "2026-09-22" }, { cycle: "w3-1", entry_date: "2026-08-02" }, { entry_date: "2026-07-01" }],
                   open: [{ cycle: "hc4-2", entry_date: "2026-11-03" }] };
    assert.deepEqual(JSON.parse(JSON.stringify(J2.cyclesIn(book))), ["w3-1", "hc4-1", "hc4-2"]);
    const pick = J2.cyclePick(book);
    assert.match(pick, /data-cyc="all" aria-pressed="true">All<\/button><button type="button" class="jr-cyc-b" data-cyc="w3-1"/);
    assert.equal(J2.inView(book.closed).length, 3);
    J2.set("cycleView", "hc4-1");
    assert.equal(J2.inView(book.closed).length, 1);
    J2.set("cycleView", "gone");
    J2.cyclePick(book);
    assert.equal(J2.inView(book.closed).length, 3, "a remembered cycle the book no longer has falls back to all");
    assert.equal(J2.cyclePick({ closed: [{ cycle: "hc4-1" }], open: [] }), "", "one cycle: no switch");
  });

  test("the four displays are inert: no call, no fetch, no storage beyond the switch's own memory", () => {
    const body = slice("function capacityText(nOpen) {", "\n  }") + slice("function sectorLoadHTML() {", "\n  }")
      + slice("function paintCapacity(open) {", "\n  }") + slice("function d14Sub(t) {", "\n  }");
    assert.ok(!/fetch\(|\/api\/|localStorage|<button|onclick/.test(body), body.slice(0, 200));
  });
}

suite("20 more · the deck's \"not taken\" reason and next free slot (app.js)");
{
  const APP2 = fs.readFileSync(path.resolve(__dirname, "../public/js/app.js"), "utf8");
  const cut = (a, b) => { const i = APP2.indexOf(a); assert.ok(i >= 0, a); return APP2.slice(i, APP2.indexOf(b, i + a.length) + b.length); };
  const cx = vm.createContext({ console, Intl, Date, Math, Number, String, JSON, Object, Array, isFinite });
  vm.runInContext("var state = {}, PM = { fmtMelb: (iso) => 'Tue 3 Nov, 11:10 am AEDT' };\n"
    + cut("const NOT_TAKEN = {", "\n  };") + "\n" + cut("function notTaken(r) {", "\n  }") + "\n"
    + cut("function nextSlots(rules) {", "\n  }") + "\nthis.A = { notTaken, nextSlots, state };", cx);
  const A = cx.A;

  test("a row the bot refused carries the bot's own reason; a held one, or one it never saw, carries none", () => {
    A.state.market = "nasdaq";
    A.state.heldSyms = { nasdaq: new Set(["HELD"]) };
    A.state.skips = { nasdaq: { at: "2026-11-02T15:41:00Z", reasons: { AAPL: "sector_cap", HELD: "dup_symbol", X: "mystery" } } };
    const nt = A.notTaken({ symbol: "aapl" });
    assert.equal(nt.short, "sector full");
    assert.match(nt.long, /GICS sector/);
    assert.equal(nt.at, "Tue 3 Nov, 11:10 am AEDT");
    assert.equal(A.notTaken({ symbol: "HELD" }), null);
    assert.equal(A.notTaken({ symbol: "NEW" }), null);
    assert.equal(A.notTaken({ symbol: "X" }).short, "not taken", "an unknown code says so, never a guess");
    A.state.market = "asx";
    assert.equal(A.notTaken({ symbol: "AAPL" }), null, "another market's record never leaks");
  });

  test("the book fold's next free slot is the first day with any, or nothing", () => {
    assert.equal(A.nextSlots({ capacity: { time_stops_due: [["2026-11-11", 2], ["2026-11-12", 1]] } }), "Wed 11 Nov (2)");
    assert.equal(A.nextSlots({ capacity: { time_stops_due: [] } }), "");
    assert.equal(A.nextSlots(null), "");
  });
}

// ─────────────────────────────── summary ─────────────────────────────────────
console.log(`\n${"─".repeat(48)}`);
if (failed) {
  console.error(`FAILED  ${failed} test(s) failed, ${passed} passed`);
  process.exit(1);
} else {
  console.log(`ALL ${passed} tests passed`);
}
