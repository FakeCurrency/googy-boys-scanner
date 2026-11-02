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
  + slice("function prEvaluate(pr, closed) {", "\n  }") + "\n"
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
  + "this.api = { PREREG, PREREG_COHORT, pyRound, prEvaluate, markOf, roomOf, timeStopOf, marketDay,"
  + " rulesHandSeries, cycleStarts, rulesHandByCycle, setHold: (n) => { MAX_HOLD_DAYS = n; } };",
  ctx);
const J = ctx.api;

// Python's keys only: the mirror may add `second` (which read it was) for the
// strip's wording, nothing else.
const PY_KEYS = ["id", "n", "avg", "min_n", "verdict", "read_on", "read_n", "read_avg", "versus_avg"];
const same = (a, b) => (a === b) || (a == null && b == null);   // 0 === -0 on purpose

// ── 6. the checkpoints ───────────────────────────────────────────────────────
suite("6 · prEvaluate == decision_pack.evaluate on every shared case");

test("pyRound is Python's round() on every rounding case", () => {
  for (const [x, nd, want] of CASES.round_cases) {
    assert.ok(same(J.pyRound(x, nd), want), `round(${x}, ${nd}): JS ${J.pyRound(x, nd)} vs Python ${want}`);
  }
});

test("the shared cases are all present and every live checkpoint is covered", () => {
  assert.ok(CASES.cases.length >= 10, "the shared case file shrank");
  const live = J.PREREG.filter((p) => p.kind === "live").map((p) => p.id);
  assert.equal(live.join(","), "PR-0,PR-1,PR-2,PR-3");
  for (const c of CASES.cases) for (const id of live) assert.ok(c.expect[id], `${c.name}: no ${id}`);
});

for (const c of CASES.cases) {
  test(`case: ${c.name}`, () => {
    for (const pr of J.PREREG.filter((p) => p.kind === "live")) {
      const got = J.prEvaluate(pr, c.closed);
      const want = c.expect[pr.id];
      for (const k of PY_KEYS) {
        assert.ok(same(got[k], want[k]), `${pr.id}.${k}: JS ${JSON.stringify(got[k])} vs decision_pack ${JSON.stringify(want[k])}`);
      }
      for (const k of Object.keys(got)) {
        assert.ok(PY_KEYS.includes(k) || k === "second", `${pr.id}: the mirror grew a key decision_pack does not have: ${k}`);
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
  const body = slice("function checkpointLine(d) {", "\n  }");
  assert.ok(!/<button|<a\s|onclick|data-osort|data-closeall|addEventListener/.test(body),
    "a control appeared in the checkpoint strip — it must stay a record, never a prompt");
  assert.ok(/<details class="jr-pr-fold">/.test(body) && !/<details[^>]*\bopen\b/.test(body), "the fold must ship shut");
});

test("renderSide draws it beside the cycle board and keeps the fold's state over a repaint", () => {
  const body = slice("function renderSide(side) {", "\n  }");
  assert.ok(/host\.insertAdjacentHTML\("beforebegin", checkpointLine\(d\)\)/.test(body), "renderSide no longer draws the strip");
  assert.ok(/document\.querySelectorAll\("#bot-pr"\)\.forEach\(\(el\) => el\.remove\(\)\)/.test(body),
    "no remove-before-insert for #bot-pr — every 3-minute refresh would stack another strip");
  assert.ok(/const prOpen = !!document\.querySelector\("#bot-pr details\[open\]"\)/.test(body),
    "the open fold would snap shut on every repaint");
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
  const cellRecord = new Function("return (" + sliceFrom(APP, "const cellRecord = (b, tag) => {", "\n  };")
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
  assert.ok(/High conviction<\/span>`;/.test(badge), "the badge's visible label changed — the phone's two-chip fit (UI100 #32) rides on it");
  const detail = sliceFrom(APP, "function detailHtmlVivek(r) {", "\n  }");
  assert.ok(/cellRecordNote\(cell, true\)/.test(detail) && /vk-cellrec/.test(detail),
    "the expanded panel lost its per-cell record chip");
});

test("no rules file, no note: the cycle is never guessed", () => {
  assert.ok(/const tag = rules && typeof rules\.cycle_tag === "string" \? rules\.cycle_tag\.trim\(\) : "";/.test(APP));
  assert.ok(/const rec = tag \? \{ tag, cells: cellRecord\(b, tag\) \} : null;/.test(APP));
});

// ─────────────────────────────── summary ─────────────────────────────────────
console.log(`\n${"─".repeat(48)}`);
if (failed) {
  console.error(`FAILED  ${failed} test(s) failed, ${passed} passed`);
  process.exit(1);
} else {
  console.log(`ALL ${passed} tests passed`);
}
