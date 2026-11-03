#!/usr/bin/env node
/* THE TIME STOP's day-29 boundary, on the journal's countdown (NEXT100 #3).

   tests/fixtures/time_stop_cases.json is ONE case table with three readers:
   scanner/time_stop.py time_stop_due and the engine itself
   (scanner/broker/vivek_run.run_market, which really closes the row) in
   tests/test_time_stop_cases.py, and the shipped public/js/journal.js
   timeStopOf here. For every case the countdown must name the table's due
   day; for every run it must count the engine's days held, read the market's
   own calendar date, and say "due" (left <= 0) on exactly the in-session runs
   the engine closes on. So the journal cannot promise a close on a day the
   engine holds, or the reverse, without one of the two suites going red.

   Every function is sliced out of public/js/journal.js -- re-typing them here
   would test a copy.

   Run with: node test/time_stop_cases.test.js
*/
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(path.resolve(__dirname, "../public/js/journal.js"), "utf8");
const TABLE = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../tests/fixtures/time_stop_cases.json"), "utf8"));

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓  ${name}`); passed++; }
  catch (e) { console.error(`  ✗  ${name}\n     ${e.message}`); failed++; }
}
function slice(startMarker, endMarker) {
  const a = SRC.indexOf(startMarker);
  assert.ok(a >= 0, `journal.js no longer contains "${startMarker}" — was it renamed?`);
  const b = SRC.indexOf(endMarker, a + startMarker.length);
  assert.ok(b > a, `could not find the end of "${startMarker}"`);
  return SRC.slice(a, b + endMarker.length);
}

const ctx = vm.createContext({ console, Intl, Date, Math, Number, String, Set, isFinite });
vm.runInContext(
  slice("const MARKET_TZ =", ";\n") + "\n"
  + slice("let MAX_HOLD_DAYS =", ";\n") + "\n"
  + slice("const STOCK_TYPES =", ";\n") + "\n"
  + slice("const NONCRYPTO =", ";\n") + "\n"
  + slice("function isCryptoTrade(t) {", "\n  }") + "\n"
  + slice("function marketOf(t) {", "\n  }") + "\n"
  + slice("function marketDay(mkt, ms) {", "\n  }") + "\n"
  + slice("function timeStopOf(t, ms) {", "\n  }") + "\n"
  + "this.api = { timeStopOf, marketDay, marketOf, hold: () => MAX_HOLD_DAYS,"
  + " setHold: (n) => { MAX_HOLD_DAYS = n; } };",
  ctx);
const J = ctx.api;
const SHIPPED_HOLD = J.hold();

// A bot row as the book stores it: market + entry_date + tp1_hit are all the
// countdown reads; the rest is the shape every open row carries.
const row = (c) => ({ symbol: "TSC", market: c.market, direction: "long", entry: 100, stop: 96,
  risk: 4, tp1: 106, tp2: 112, tp3: 120, entry_date: c.entry_date, tp1_hit: c.tp1_hit });
const withHold = (n, fn) => { J.setHold(n); try { return fn(); } finally { J.setHold(SHIPPED_HOLD); } };

console.log("\n── the journal's time-stop countdown == the engine's close day ──");

test("the table is the one the Python suite reads, and it still has cases on every edge", () => {
  const cases = TABLE.cases;
  assert.ok(Array.isArray(cases) && cases.length >= 8, "the shared case table shrank");
  const runs = cases.flatMap((c) => c.runs.map((r) => [c, r]));
  assert.ok(runs.some(([c, r]) => r.closes && r.held === c.max_hold + 1), "no day-29 close in the table");
  assert.ok(runs.some(([c, r]) => !r.closes && r.session && c.due && r.held === c.max_hold), "no day-28 hold in the table");
  assert.ok(cases.some((c) => c.market === "crypto" && c.due), "no crypto case");
  assert.ok(runs.some(([, r]) => new Date(Date.parse(r.at)).toISOString().slice(0, 10) !== r.at.slice(0, 10)),
    "no run whose market date differs from the UTC date (a UTC-calendar countdown would pass)");
  assert.ok(cases.some((c) => c.tp1_hit && c.due === null) && cases.some((c) => c.max_hold === 0 && c.due === null),
    "the runner / rule-off cases are gone");
});

// (The shipped MAX_HOLD_DAYS fallback is held to config by
// tests/test_js_config_mirrors.py; every case here sets its own max_hold.)
for (const c of TABLE.cases) {
  test(`case: ${c.name}`, () => withHold(c.max_hold, () => {
    const t = row(c);
    // a case with no runs (no entry date) is still read once
    const instants = c.runs.length ? c.runs.map((r) => r.at) : ["2026-11-11T12:00:00Z"];
    for (const at of instants) {
      const ms = Date.parse(at);
      assert.ok(isFinite(ms), `${at} does not parse`);
      const ts = J.timeStopOf(t, ms);
      if (c.due === null) {
        assert.equal(ts, null, `${at}: the countdown shows a time stop the engine never applies`);
        continue;
      }
      assert.ok(ts, `${at}: no countdown on a row the engine will time-stop`);
      assert.equal(ts.due, c.due, `${at}: the countdown names ${ts.due}, the engine's day is ${c.due}`);
    }
    for (const r of c.runs) {
      const ms = Date.parse(r.at), day = r.at.slice(0, 10);
      assert.equal(J.marketDay(c.market, ms), day, `${r.at}: not read in ${c.market}'s own calendar`);
      const ts = J.timeStopOf(t, ms);
      if (ts === null) {
        assert.equal(r.closes, false, `${r.at}: the engine closes here but the journal shows no time stop`);
        continue;
      }
      assert.equal(ts.held, r.held, `${r.at}: held ${ts.held} on the journal, ${r.held} in the engine`);
      assert.equal(ts.left <= 0, day >= c.due, `${r.at}: left ${ts.left} disagrees with the due day ${c.due}`);
      assert.equal(r.closes, r.session && ts.left <= 0,
        `${r.at}: the engine ${r.closes ? "closes" : "holds"} (session ${r.session}) but the countdown reads left ${ts.left}`);
    }
  }));
}

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
