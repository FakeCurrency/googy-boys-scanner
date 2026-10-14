#!/usr/bin/env node
/* The journal's money arithmetic — TOP100 Tier 2 (#30, #33; #25 and #26 went
   with the manual journal, 2026-09-21 — their history is kept below).

   Four fixes, one theme: every one of them was a number the page reported with
   full confidence that was quietly measuring something other than what its
   label said. None of them threw, none of them rendered a dash, and none of
   them disagreed with any other number on the page — which is exactly why they
   survived. A wrong total that contradicts the chart beside it gets noticed in
   an afternoon; a wrong total that the chart agrees with gets trusted for
   months.

     #25  Closed-trade R dropped the un-booked remainder of the position. The
          FULL ladder sums to 0.90, so even a perfect winner left a 10% runner
          unpriced — every completed VIVEK winner on the page was under-reported.
          And `computeCloseOutcome` clones the trade through the SAME resolver,
          so the close preview was wrong by precisely the same amount as the
          outcome it predicted. The two never disagreed.
     #26  `_init` was an enumerable boolean, so it round-tripped through
          localStorage and KV and froze `risk_usd` at whatever constants the
          first device to open the row happened to be holding. Forever, on every
          device, because the early return fired before any sizing ran.
     #30  Max drawdown walked `closed` in store order. For the bot book that is
          market-by-market, so every NASDAQ trade of the year lands before the
          first ASX one and the "worst drawdown" described a sequence of trades
          that never happened in that order.
     #33  The TP ladder was a hand-typed JS copy of VIVEK_TP_SCALE_LONG/SHORT
          with nothing comparing them — the one sizing constant on the page that
          structurally could not raise the drift warning the others could.

   Like test/journal_review.test.js and test/journal_stale.test.js, this runs the
   REAL functions sliced out of the shipped file. Re-typing them here
   would produce a suite that passes forever against a copy of the bug.

   Run with: node test/journal_money.test.js
*/
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(path.resolve(__dirname, "../public/js/journal.js"), "utf8");

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓  ${name}`); passed++; }
  catch (e) {
    const loc = (e.stack || "").split("\n").slice(1).find((l) => l.includes("journal_money.test.js"));
    console.error(`  ✗  ${name}\n     ${e.message}${loc ? "\n     " + loc.trim() : ""}`);
    failed++;
  }
}
function suite(name) { console.log(`\n── ${name} ──`); }

function slice(startMarker, endMarker) {
  const a = SRC.indexOf(startMarker);
  assert.ok(a >= 0, `journal.js no longer contains "${startMarker}" — was it renamed?`);
  const b = SRC.indexOf(endMarker, a);
  assert.ok(b > a, `could not find the end of "${startMarker}"`);
  return SRC.slice(a, b + endMarker.length);
}

// ── the real money path, lifted whole ────────────────────────────────────────
// Everything below the constants is SHIPPED CODE. The constants are declared
// here because in the file they are `let`s mutated by an async fetch, and this
// suite is about the arithmetic, not about the fetch. They are set to the
// file's own fallbacks so a test that reasons about dollars reasons about the
// same numbers the offline page would show.
const ctx = vm.createContext({ console });
vm.runInContext(
  "let EQUITY = 150000, POSITION_NOTIONAL = 2500, RISK_PCT = 0.35;\n"
  + "let SCALE = { long: [0.25, 0.50, 0.15], short: [0.50, 0.25, 0.15] };\n"
  + "const isCryptoTrade = (t) => (t.market || t.asset_type) === 'crypto';\n"
  + "let FX_AUDUSD = 0.66;\n"
  + slice("const round = (v, n)", ";\n") + "\n"
  + slice("function marketOf(t) {", "\n  }") + "\n"
  + slice("const rOf = (price, entry, risk, isLong)", ";\n") + "\n"
  + "let RULES_GEN = 1;\n"
  + slice("const isAudRow = (t) =>", ";\n") + "\n"
  + slice("const fxOf = (t) =>", ";\n") + "\n"
  + slice("const dollarsOf = (t) =>", ";\n") + "\n"
  + slice("function exitMs(t) {", "\n  }") + "\n"
  + slice("const byExit = (closed) =>", ";\n") + "\n"
  + slice("function stats(closed, openN) {", "\n  }") + "\n"
  // ── the open-positions sort (2026-08-07) ──
  // paintOpen is the DOM half and is stubbed; everything that
  // DECIDES an order is real code lifted out of the shipped file.
  + slice("const scanPrice = new Map()", ";\n") + "\n"
  + slice("function openedMs(t) {", "\n  }") + "\n"
  + slice("const OPEN_SORT_KEYS =", ";\n") + "\n"
  + slice("let openSort = {", ";") + "\n"
  + slice("function openMetric(t, side) {", "\n  }") + "\n"
  + slice("const openSortValue = (t, side, key) =>", ";\n") + "\n"
  + slice("function sortedOpen(list, side) {", "\n  }") + "\n"
  + "let painted = [];\n"
  + "function paintOpen(side) { painted.push(side); }\n"
  + slice("function setOpenSort(key) {", "\n  }") + "\n"
  + "this.stats = stats; this.byExit = byExit;"
  + "this.bumpGen = () => { RULES_GEN++; }; this.gen = () => RULES_GEN;"
  + "this.openMetric = openMetric; this.sortedOpen = sortedOpen;"
  + "this.setOpenSort = setOpenSort; this.scanPrice = scanPrice;"
  + "this.sortState = () => ({ ...openSort });"
  + "this.resetSort = () => { openSort = { key: 'opened', dir: -1 }; painted = []; };"
  + "this.painted = () => painted.slice();",
  ctx);
const { stats, byExit } = ctx;
const { openMetric, sortedOpen, setOpenSort, scanPrice, sortState, resetSort, painted } = ctx;

// CODE-only view of the source. A substring ban that reads its own explanatory
// comment as the offence passes forever against the bug it describes — this
// file's comments name `localStorage` and `.sort(` deliberately.
const CODE = SRC.split("\n")
  .filter((l) => !/^\s*(\/\/|\/\*|\*)/.test(l))
  .join("\n");

// A closed VIVEK long with round numbers: entry 100, stop 90, so 1R = 10 points.
// Exit at 130 is +3R gross on whatever fraction of the position is still on.
function closedLong(over) {
  return Object.assign({
    id: "t1", market: "nasdaq", direction: "long", status: "closed",
    entry: 100, stop: 90, risk: 10, risk_stop: 90,
    tp1: 110, tp2: 120, tp3: 125,
    exit: 130, exit_date: "2026-07-20",
    gross_r: 0, booked_pct: 0, exits: [],
  }, over);
}

// ── #25 — the un-booked remainder ────────────────────────────────────────────
// (#25 — the manual close that booked only the last ladder rung — and #26 —
//  the per-row sizing cache `_init` — tested derivations that existed only for
//  hand-logged trades. The manual journal was removed 2026-09-21; the bot book
//  arrives with realized_r and risk_usd already on the row, so there is
//  nothing left to derive or to cache.)

suite("#30 — max drawdown walks exit order, like the chart beside it");

// Same three trades, two store orders. risk_usd is forced so the $ figures are
// exact and the test is about sequencing rather than about the sizer.
function tr(id, r, exitDate) {
  return { id, market: "nasdaq", realized_r: r, risk_usd: 100,
           status: "closed", exit_date: exitDate, exit_time: "16:00" };
}
const WIN_FIRST = [tr("a", +5, "2026-07-01"), tr("b", -3, "2026-07-02"), tr("c", -1, "2026-07-03")];

test("the same set in a different store order gives the same drawdown", () => {
  const shuffled = [WIN_FIRST[2], WIN_FIRST[0], WIN_FIRST[1]];
  assert.equal(stats(WIN_FIRST, 0).maxDD, stats(shuffled, 0).maxDD);
});

test("and that drawdown is the real one: peak +$500, trough +$100, so -$400", () => {
  // Walked in store order, the shuffled array reads -1, +5, -3 → peak 400,
  // trough -100 at the start, and reports a drawdown of -$300. Neither number
  // is absurd, which is why nobody caught it.
  assert.equal(stats(WIN_FIRST, 0).maxDD, -400);
});

test("byExit does not mutate the caller's array", () => {
  // stats() and series() both call it on the same live `closed` list. If it
  // sorted in place, the first render would silently reorder the store.
  const orig = [WIN_FIRST[2], WIN_FIRST[0], WIN_FIRST[1]];
  const snapshot = orig.slice();
  byExit(orig);
  assert.deepEqual(orig.map((t) => t.id), snapshot.map((t) => t.id));
});

test("rows with an unparseable exit date sort as 0 rather than throwing", () => {
  const messy = [tr("x", -2, "not-a-date"), tr("y", +1, "2026-07-02")];
  const s = stats(messy, 0);
  assert.ok(Number.isFinite(s.maxDD));
  assert.ok(Number.isFinite(s.totalD));
});

test("totals and win rate are order-independent too (the sanity check)", () => {
  const a = stats(WIN_FIRST, 0), b = stats([...WIN_FIRST].reverse(), 0);
  assert.equal(a.totalR, b.totalR);
  assert.equal(a.totalD, b.totalD);
  assert.equal(a.win, b.win);
});

test("ASX dollars are converted before they enter the curve", () => {
  // Not a #30 fix, but it shares the code path and the drawdown is a DOLLAR
  // curve: mixing A$ and US$ at face value would overstate an ASX leg ~50%.
  const asx = [{ id: "a", market: "asx", realized_r: 1, risk_usd: 100,
                 status: "closed", exit_date: "2026-07-01", exit_time: "16:00" }];
  assert.equal(stats(asx, 0).totalD, 66);
});

// ── #33 — the ladder is adopted, not re-typed ────────────────────────────────
suite("#33 — the TP ladder comes from the engine");

test("SCALE is mutable, because loadBotRules replaces it from bot_rules.json", () => {
  // A `const` array of three literals is what the bug looked like. The shipped
  // shape is a const OBJECT whose per-side arrays loadBotRules overwrites in
  // place; if someone freezes it or stops the in-place write, adoption silently
  // becomes a no-op and the drift warning never fires again. (This used to
  // reassign the harness's own `let SCALE`, which proved nothing about
  // journal.js -- it now reads the shipped code.)
  assert.ok(/const SCALE = \{ long: \[[^\]]+\], short: \[[^\]]+\] \};/.test(CODE),
    "journal.js SCALE is no longer a per-side object of arrays");
  assert.ok(!/Object\.freeze\(\s*SCALE/.test(CODE), "journal.js freezes SCALE, so adoption is a no-op");
  assert.ok(/SCALE\[side\] = v\.slice\(\);/.test(CODE),
    "loadBotRules no longer writes the published ladder into SCALE");
  // and the write really lands on the shipped shape
  const shipped = new Function(CODE.match(/const SCALE = \{[^;]+\};/)[0] + " return SCALE;")();
  shipped.long = [0.3, 0.4, 0.2];
  assert.deepEqual(shipped.long, [0.3, 0.4, 0.2], "the shipped SCALE rejected an in-place write");
});

test("journal.js adopts bot_rules.tp_scale and shouts when it differs", () => {
  // Source-pin: the adoption lives inside an async fetch handler that this
  // harness does not run. Deleting the block would leave every test above
  // passing against a ladder nothing publishes to.
  assert.ok(/j\.tp_scale/.test(SRC),
    "journal.js no longer reads bot_rules.tp_scale — the ladder is a hand-typed copy again");
  assert.ok(/drift\["tp_scale\." \+ side\]/.test(SRC),
    "the ladder no longer reports drift, so a divergence from scanner/config.py is silent");
  assert.ok(/RULES_GEN\+\+/.test(SRC),
    "adopting live constants no longer bumps the generation, so anything derived " +
    "from the old ones is silently kept (TOP100 #26)");
});

// ── #74 — the cost model's exit test ───────────────────────────────────────
// (costR — the JS mirror of vivek_journal._cost_r — had no caller on the page
// after the manual journal went, 2026-09-21, and was deleted with its pins,
// REFINE200 #94. The Python deny-list it mirrored is still pinned in
// tests/test_vivek_journal.py; hygiene.test.js keeps the JS copy from coming
// back without a caller.)

// ── the open-positions sort ──────────────────────────────────────────────────
// Owner-requested 2026-08-07: "toggle by which one is currently in the BEST $
// or R". The ordering itself is cosmetic; what is NOT cosmetic is what a row
// claims while being ordered, which is why these pins are here in the money
// suite rather than a view suite of their own.
suite("open sort — the two books do not carry the same numbers");

// A non-bot row: no unreal_r, no unreal_usd, so openMetric's non-bot branch
// re-derives them from the scan price. (That branch served the manual "Me"
// book, removed 2026-09-21; journal.js now only ever passes side "bot", so
// these pins exercise code the page no longer reaches -- listed in
// reviews/2026-09-23-validate.md rather than deleted here.)
const mePos = (over) => Object.assign({
  id: "x", market: "asx", direction: "long", status: "open",
  entry: 10, stop: 9, risk: 1, risk_stop: 9, risk_usd: 500,
  opened_at: "2026-07-20T01:00:00Z",
}, over);
// A bot position: marked server-side, arrives with both numbers on it.
const botPos = (over) => Object.assign({
  id: "b", market: "nasdaq", direction: "long", status: "open",
  entry: 100, stop: 90, risk: 10, unreal_r: 0.5, unreal_usd: 250,
  opened_at: "2026-07-20T01:00:00Z",
}, over);

test("the bot side reads the numbers the scan already computed", () => {
  const m = openMetric(botPos({ unreal_r: 1.25, unreal_usd: 600 }), "bot");
  assert.equal(m.r, 1.25);
  assert.equal(m.usd, 600);          // nasdaq → fx 1
});

test("the me side derives from the scan price, because nothing on the row has it", () => {
  resetSort(); scanPrice.clear();
  const t = mePos({ symbol: "AAA" });
  // Sorting off the RENDERED cell would sort the literal "—": a non-bot row
  // carries no R at all, so openMetric has to derive it from the scan price.
  assert.equal(t.unreal_r, undefined);
  scanPrice.set("asx:AAA", 12);      // +2R on a 1-point risk
  const m = openMetric(t, "me");
  assert.equal(m.r, 2);
  assert.equal(m.usd, 2 * 500 * 0.66, "ASX dollars must be FX-converted, not taken at face value");
});

test("a short is measured in its own direction", () => {
  resetSort(); scanPrice.clear();
  scanPrice.set("asx:BBB", 8);
  const m = openMetric(mePos({ symbol: "BBB", direction: "short" }), "me");
  assert.equal(m.r, 2, "price 8 against a short entered at 10 is +2R, not -2R");
});

test("an unpriced row is UNKNOWN, never a flat zero", () => {
  resetSort(); scanPrice.clear();
  // Zero would be a lie that sorts into the middle of the table, where it reads
  // as a real number someone might act on.
  assert.equal(openMetric(mePos({ symbol: "GONE" }), "me").r, null);
  assert.equal(openMetric(botPos({ unreal_r: undefined }), "bot").r, null);
  assert.equal(openMetric(botPos({ unreal_usd: undefined }), "bot").usd, null);
});

test("a zero-risk row cannot divide its way to Infinity", () => {
  resetSort(); scanPrice.clear();
  scanPrice.set("asx:FLAT", 11);
  const m = openMetric(mePos({ symbol: "FLAT", risk: 0, stop: 10 }), "me");
  assert.equal(m.r, null);
});

test("a row with no risk_usd still sorts by R, it just has no dollars", () => {
  resetSort(); scanPrice.clear();
  scanPrice.set("asx:CCC", 11);
  const m = openMetric(mePos({ symbol: "CCC", risk_usd: null }), "me");
  assert.equal(m.r, 1);
  assert.equal(m.usd, null);
});

suite("open sort — ordering");

const book = () => {
  scanPrice.clear();
  scanPrice.set("asx:WIN", 12);      // +2.0R · risk_usd 100 → $132
  scanPrice.set("asx:BIG", 10.5);    // +0.5R · risk_usd 900 → $297
  scanPrice.set("asx:LOSE", 9.5);    // -0.5R · risk_usd 200 → -$66
  return [
    mePos({ id: "win", symbol: "WIN", risk_usd: 100, opened_at: "2026-07-01T00:00:00Z" }),
    mePos({ id: "big", symbol: "BIG", risk_usd: 900, opened_at: "2026-07-02T00:00:00Z" }),
    mePos({ id: "lose", symbol: "LOSE", risk_usd: 200, opened_at: "2026-07-03T00:00:00Z" }),
    mePos({ id: "dark", symbol: "DARK", risk_usd: 300, opened_at: "2026-07-04T00:00:00Z" }),
  ];
};
const ids = (list) => list.map((t) => t.id).join(",");

test("default is newest opened first — unchanged from before the sort existed", () => {
  resetSort();
  assert.equal(ids(sortedOpen(book(), "me")), "dark,lose,big,win");
});

test("R descending puts the best R at the top", () => {
  resetSort(); const b = book(); setOpenSort("r");
  assert.equal(ids(sortedOpen(b, "me")), "win,big,lose,dark");
});

test("$ descending is a DIFFERENT order to R — that is the point of two keys", () => {
  resetSort(); const b = book(); setOpenSort("usd");
  // BIG is only +0.5R but carries 9x the size, so it is the bigger dollar win.
  // If this ever equals the R order, one of the two keys has stopped working.
  assert.equal(ids(sortedOpen(b, "me")), "big,win,lose,dark");
});

test("UNKNOWN sinks to the bottom in BOTH directions", () => {
  // The one that actually matters. Reversing the sort must not promote "we
  // don't know what this is worth" to the top of the table, where it sits in
  // the position reserved for the worst loser and reads as one.
  resetSort(); const b = book();
  setOpenSort("r");
  assert.equal(ids(sortedOpen(b, "me")).split(",").pop(), "dark", "descending");
  setOpenSort("r");                                     // reverse
  assert.equal(sortState().dir, 1);
  assert.equal(ids(sortedOpen(b, "me")), "lose,big,win,dark", "ascending — dark STILL last");
});

test("ties break by newest, so the order cannot jitter between renders", () => {
  resetSort(); scanPrice.clear();
  const same = [
    mePos({ id: "old", symbol: "T1", opened_at: "2026-07-01T00:00:00Z" }),
    mePos({ id: "new", symbol: "T2", opened_at: "2026-07-05T00:00:00Z" }),
  ];
  scanPrice.set("asx:T1", 11); scanPrice.set("asx:T2", 11);   // identical +1R
  setOpenSort("r");
  assert.equal(ids(sortedOpen(same, "me")), "new,old");
});

test("sortedOpen does not mutate the caller's array", () => {
  // Same house rule byExit is held to above: state.bot.open is the LIVE book,
  // and reordering it reorders every other surface that reads it — silently,
  // and only for whoever clicked.
  resetSort(); const b = book(); const before = ids(b);
  setOpenSort("usd");
  sortedOpen(b, "me");
  assert.equal(ids(b), before);
});

suite("open sort — the toggle");

// sortState()/painted() cross the vm boundary and carry the CONTEXT's
// prototype, so strict deepEqual fails on structurally identical values.
// Compare what the values ARE, not which realm made them.
const sortStr = () => { const s = sortState(); return s.key + ":" + s.dir; };

test("a new column always opens best-first, and re-clicking reverses it", () => {
  resetSort();
  assert.equal(sortStr(), "opened:-1");
  setOpenSort("r");
  assert.equal(sortStr(), "r:-1", "a new column opens BEST-first");
  setOpenSort("r");
  assert.equal(sortStr(), "r:1", "re-clicking the live column reverses");
  setOpenSort("usd");
  assert.equal(sortStr(), "usd:-1", "switching columns resets to best-first");
});

test("an unknown key is ignored rather than sorting by undefined", () => {
  resetSort(); setOpenSort("r");
  setOpenSort("../../etc/passwd");
  assert.equal(sortStr(), "r:-1");
});

test("one click repaints the book", () => {
  // Was "BOTH books ... and re-runs the live fill": the Me side's R/$ cells
  // were painted by refreshLive rather than by openRows. Both went with the
  // manual journal on 2026-09-21; the bot book arrives already marked.
  resetSort(); setOpenSort("usd");
  assert.equal(painted().join(","), "bot");
});

suite("open sort — pins on the shipped file");

test("openRows sorts through sortedOpen, not an inline comparator", () => {
  assert.ok(/const rows = sortedOpen\(list, side\)/.test(CODE),
    "openRows has gone back to sorting inline, so the toggle no longer reaches it");
});

test("both affordances are the same attribute, so they cannot drift apart", () => {
  // The section-title buttons and the clickable column headers are one control
  // wearing two hats. Two attributes would be two code paths and one of them
  // would rot.
  assert.ok(/data-osort="\$\{k\}"/.test(CODE), "the section-title control lost data-osort");
  assert.ok(/data-osort="\$\{key\}"/.test(CODE), "the column headers lost data-osort");
  assert.ok(/closest\("\[data-osort\]"\)/.test(CODE), "nothing listens for data-osort any more");
});

test("the header cell is reachable by a screen reader as a sort control", () => {
  assert.ok(/aria-sort=/.test(CODE), "the sortable headers no longer announce their state");
});

test("the sort is NOT persisted", () => {
  // Deliberate. A sort is a question you are asking right now, not a setting;
  // sticky "$ descending" would bury the newest position — the one most likely
  // to still need a decision — under a choice made weeks ago and forgotten.
  assert.ok(!/openSort[\s\S]{0,200}localStorage/.test(CODE),
    "the open sort is being persisted — see the note on openSort for why it is not");
  assert.ok(!/(jr_open_sort|open_sort|osort)["']\s*[,)]/.test(CODE.replace(/data-osort/g, "")),
    "a storage key for the open sort has appeared");
});

test("the sort control survives a re-render", () => {
  // openSort is module-scoped for exactly this reason: renderAll() re-enters
  // openRows from scratch every 3 minutes and a local would be thrown away.
  // Module scope inside the page's IIFE is exactly two spaces of indent;
  // anything nested inside a function is four or more.
  assert.ok(/\n  let openSort = /.test(CODE),
    "openSort is no longer at module scope — a re-render will throw the choice away");
  assert.ok(!/\n {4,}let openSort = /.test(CODE),
    "openSort has been moved inside a function and will not survive a re-render");
});

// ── the version gate ─────────────────────────────────────────────────────────
suite("cache-busting");

test("journal.html requests a journal.js at or past the version these fixes shipped in", () => {
  // Project rule 2. Every one of the fixes above is invisible to a browser
  // holding the old file, and journal.js is cache-first on `?v=` — so a missed
  // bump means the money arithmetic silently stays wrong for existing users
  // while every test here passes.
  const html = fs.readFileSync(path.resolve(__dirname, "../public/journal.html"), "utf8");
  const m = html.match(/js\/journal\.js\?v=(\d+)/);
  assert.ok(m, "journal.html no longer version-stamps journal.js");
  assert.ok(Number(m[1]) >= 89,
    `journal.js?v=${m[1]} predates the rules refresh in the 3-minute poll (need >= 89)`);
});

test("the 3-minute refresh re-reads bot_rules.json, not just the book", () => {
  // Review RR-2 (2026-09-28): a tab that read the rules once at init and then
  // picked up a restated book marked every restated row "held at $2,500 - the
  // book now sizes each position at $5,000" until it was reloaded.
  const i = SRC.indexOf("setInterval(async () => {");
  assert.ok(i >= 0, "the refresh interval is gone");
  const body = SRC.slice(i, SRC.indexOf("}, 180000);", i));
  // `true` = a FRESH read through the shared loader (REFINE200 #68): without
  // it the refresh would be handed the page's first, memoised copy for ever.
  assert.ok(/loadBotRules\(true\)/.test(body), "the refresh no longer re-reads the rules fresh");
  assert.ok(/loadBot\(true\)/.test(body), "the refresh no longer re-reads the book fresh");
});

test("the book and the rules come from the page's ONE shared read (REFINE200 #68)", () => {
  // nav.js window.VivekBook: stalled.js and the status sheet read the same
  // promise, so the ~370 KB book crosses the network once per page.
  assert.ok(/VB\.get\(\{ fresh \}\)/.test(CODE) && /VB\.rules\(\{ fresh \}\)/.test(CODE),
    "journal.js no longer reads through the shared loader");
  assert.ok(/await sharedRead\("book", fresh\)/.test(CODE), "loadBot bypasses the shared read");
  assert.ok(/await sharedRead\("rules", fresh\)/.test(CODE), "loadBotRules bypasses the shared read");
  assert.ok(!/fetch\("data\/vivek_bot_book\.json", \{ cache: "no-cache" \}\)\)/.test(CODE.replace(/sharedRead[\s\S]*?\n  \};/, "")),
    "a second direct book fetch is back outside the fallback");
});

test("the full-scan price fallback is gone — the slim <m>_prices.json is the source (REFINE200 #72)", () => {
  assert.ok(!/_vivek\.json/.test(CODE), "journal.js reads a full <m>_vivek.json again");
  assert.ok(/data\/\$\{mkt\}_prices\.json/.test(CODE), "the slim prices read is gone");
});

test("journal.html requests a journal.css new enough to style the sort control", () => {
  // Without it the control renders as three unstyled words in the section
  // title — still clickable, but it does not read as a control.
  const html = fs.readFileSync(path.resolve(__dirname, "../public/journal.html"), "utf8");
  const m = html.match(/css\/journal\.css\?v=(\d+)/);
  assert.ok(m, "journal.html no longer version-stamps journal.css");
  assert.ok(Number(m[1]) >= 33, `journal.css?v=${m[1]} predates the sort control (need >= 33)`);
});

test("the sort hosts exist in the markup the control paints into", () => {
  const html = fs.readFileSync(path.resolve(__dirname, "../public/journal.html"), "utf8");
  assert.ok(html.includes('id="bot-open-sort"'),
    "#bot-open-sort is gone — paintOpen silently no-ops and the control never appears");
  assert.ok(!html.includes('id="me-open-sort"'),
    "the manual side is back in the markup");
});

test("the control is reachable on a phone, where the column headers are not", () => {
  // .jr-cardable thead is clipped to 1px below 680px, so the headers are
  // physically untappable there and this control is the ONLY way to sort.
  const css = fs.readFileSync(path.resolve(__dirname, "../public/css/journal.css"), "utf8");
  const code = css.replace(/\/\*[\s\S]*?\*\//g, "");
  assert.ok(/\.jr-osort-b/.test(code), "the sort control has no styling at all");
  const mobile = code.slice(code.indexOf("@media (max-width: 680px)"));
  assert.ok(/\.jr-osort-b\s*\{[^}]*min-height/.test(mobile),
    "the mobile tap target is back to its unpadded 23x21px, which is a miss waiting to happen");
});


// ── WHO DECIDED THE EXIT (2026-08-13) ────────────────────────────────────────
// The bot book is meant to be evidence about the FROZEN RULES. On the live book
// 21 of 40 closes are `manual` — the owner clicking Close — and every aggregate
// on the page pools them with the 19 the rules made. The two halves do not
// resemble each other: rules -6.97R over 19, owner +0.16R over 21. Read as one
// number they cancel into a shrug, and the strategy-review checkpoint has
// already been declared satisfied on the blend.
//
// These pins are about a CAVEAT, not a calculation: nothing here changes what
// stats() returns. What must not silently regress is the classification.
suite("who decided the exit");

const dctx = vm.createContext({ console });
vm.runInContext(
  "const esc = (s) => String(s);\n"
  + slice("const MECHANICAL_EXITS =", "];\n") + "\n"
  + slice("function deciderSplit(list) {", "\n  }") + "\n"
  + slice("function deciderHTML(list) {", "\n  }") + "\n"
  + slice("function exitMechSplit(list) {", "\n  }") + "\n"
  + slice("function exitMechHTML(list) {", "\n  }") + "\n"
  + slice("function tfSplit(list) {", "\n  }") + "\n"
  + slice("function tfLineHTML(list) {", "\n  }") + "\n"
  + slice("const excursionTip = (t)", "\n  };") + "\n"
  + slice("const wrongFromEntry = (t)", ";\n") + "\n"
  + slice("const wfeMark = (t)", ";\n") + "\n"
  + slice("const REASON_TIP = {", "};\n") + "\n"
  + slice("const reasonTip = (r)", ";\n") + "\n"
  + slice("let TIDE = null", ";\n") + "\n"
  + slice("function tideHTML(t, open) {", "\n  }") + "\n"
  + "this.deciderSplit = deciderSplit; this.deciderHTML = deciderHTML;\n"
  + "this.exitMechSplit = exitMechSplit; this.exitMechHTML = exitMechHTML;\n"
  + "this.tfSplit = tfSplit; this.tfLineHTML = tfLineHTML;\n"
  + "this.wrongFromEntry = wrongFromEntry; this.excursionTip = excursionTip;\n"
  + "this.reasonTip = reasonTip; this.tideHTML = tideHTML;\n"
  + "this.MECHANICAL_EXITS = MECHANICAL_EXITS;\n", dctx);
const { deciderSplit, deciderHTML, exitMechSplit, exitMechHTML, MECHANICAL_EXITS } = dctx;
const { tfSplit, tfLineHTML, wrongFromEntry, excursionTip, reasonTip, tideHTML } = dctx;

const cl = (reason, r) => ({ status: "closed", exit_reason: reason, realized_r: r });

test("the four mechanical reasons are exactly the four the engine writes", () => {
  // stop / time / trail / target are the frozen rules acting. Adding "manual"
  // to this list would erase the entire distinction in one edit, which is why
  // it is asserted by value rather than by length.
  assert.deepEqual([...MECHANICAL_EXITS].sort(), ["stop", "target", "time", "trail"]);
});

test("a stop-out is the rules, a manual close is not", () => {
  const s = deciderSplit([cl("stop", -1), cl("manual", 0.1)]);
  assert.equal(s.bot, 1); assert.equal(s.own, 1);
  assert.equal(s.botR, -1); assert.ok(Math.abs(s.ownR - 0.1) < 1e-9);
});

test("the 28-day time-stop counts as the BOT — it is the rule firing, not a human", () => {
  const s = deciderSplit([cl("time", 0.2)]);
  assert.equal(s.bot, 1, "a time-stop is a mechanical exit");
  assert.equal(s.own, 0);
});

test("an ABSENT exit_reason counts as manual, matching how the row renders", () => {
  // closedRows falls back to "manual" for a missing value; the split must agree
  // or the caveat would describe a different set than the table beneath it.
  const s = deciderSplit([{ status: "closed", realized_r: 0.5 }]);
  assert.equal(s.own, 1); assert.equal(s.bot, 0);
});

test("case and whitespace do not smuggle a manual close into the bot's evidence", () => {
  assert.equal(deciderSplit([cl("STOP", -1)]).bot, 1);
  assert.equal(deciderSplit([cl(" Time ", 1)]).bot, 0, "a padded value is not silently trusted");
});

test("open rows are never counted — this is a caveat on the CLOSED table", () => {
  const s = deciderSplit([{ status: "open", exit_reason: "stop", realized_r: 9 }, cl("stop", -1)]);
  assert.equal(s.n, 1); assert.equal(s.botR, -1);
});

test("a missing realized_r contributes 0 rather than NaN-ing the whole sum", () => {
  // A NaN here would make every later comparison false and the caveat would
  // read "+NaNR" — the same disarm-by-NaN failure the guards fixed in Tier 1.
  const s = deciderSplit([cl("stop", undefined), cl("stop", -2)]);
  assert.equal(s.botR, -2);
});

test("the CAVEAT is silent when the book is one-sided (the mech shape may still show)", () => {
  // A caveat that always shows stops being read. Nothing to disambiguate when
  // every close came from the same decider — but an all-mechanical book is
  // exactly where the by-exit shape matters (the Sep-4+ world), so the
  // jr-decider line disappearing must not take jr-mech with it.
  const allMech = deciderHTML([cl("stop", -1), cl("time", 1)]);
  assert.ok(!allMech.includes("jr-decider"), "all-mechanical needs no who-closed caveat");
  assert.ok(allMech.includes("jr-mech"), "the by-exit shape still renders for an all-rules book");
  assert.equal(deciderHTML([cl("manual", 1)]), "", "all-manual needs neither line");
  assert.equal(deciderHTML([]), "");
});

test("and it SPEAKS, with both counts and both R totals, when they are mixed", () => {
  const h = deciderHTML([cl("stop", -3), cl("stop", -1), cl("manual", 0.5)]);
  assert.ok(h.includes("<b>2</b>") && h.includes("-4.00R"), `bot side missing: ${h}`);
  assert.ok(h.includes("<b>1</b>") && h.includes("+0.50R"), `owner side missing: ${h}`);
  assert.ok(/pool both/.test(h), "must say the stats below pool both");
});

test("renderSide actually prints it above the closed table", () => {
  // A caveat computed and never rendered is not a caveat.
  assert.ok(/deciderHTML\(d\.closed\) \+ closedRows\(d\.closed, side\)/.test(SRC),
    "renderSide no longer prefixes the closed table with the decider split");
});

// ── the rules-by-exit shape (2026-08-20) ─────────────────────────────────────
// deciderSplit says WHO closed; exitMechSplit says HOW the rules side closed.
// Display-only: same rows, broken down by exit_reason so the rules' one
// aggregate R stops hiding whether the loss lives in stops or time-stops.
suite("rules by exit mechanism");

test("mechanisms come back in MECHANICAL_EXITS order with W-L and R each", () => {
  const s = exitMechSplit([cl("time", -0.5), cl("stop", -1), cl("stop", 2), cl("trail", 1.2)]);
  assert.equal(s.map((b) => b.reason).join(","), "stop,time,trail", "canonical order, zeros omitted");
  const stop = s[0];
  assert.equal(stop.n, 2); assert.equal(stop.wins, 1); assert.equal(stop.losses, 1);
  assert.ok(Math.abs(stop.r - 1) < 1e-9);
});

test("manual and ABSENT-reason closes never enter the shape — it is the RULES' shape", () => {
  const s = exitMechSplit([cl("manual", 5), { status: "closed", realized_r: 3 }, cl("stop", -1)]);
  assert.equal(s.map((b) => b.reason).join(","), "stop");
  assert.equal(s[0].r, -1, "the manual +5R and undated +3R must not leak in");
});

test("open rows and missing realized_r follow the decider's own rules", () => {
  const s = exitMechSplit([{ status: "open", exit_reason: "stop", realized_r: 9 },
                           cl("stop", undefined), cl("stop", -2)]);
  assert.equal(s[0].n, 2, "the open row is not counted");
  assert.equal(s[0].r, -2, "a missing realized_r contributes 0, never NaN");
  assert.equal(s[0].losses, 1, "an unpriced close is neither a win nor a loss");
});

test("one mechanism is not a shape — the line stays silent below two", () => {
  assert.equal(exitMechHTML([cl("stop", -1), cl("stop", -2)]), "",
    "a single mechanism repeats the aggregate; say nothing");
  assert.equal(exitMechHTML([cl("manual", 1)]), "");
  assert.equal(exitMechHTML([]), "");
});

test("with two or more mechanisms every bucket is printed with its count, W-L and R", () => {
  const h = exitMechHTML([cl("stop", -1), cl("stop", -3), cl("time", 0.5), cl("target", 2)]);
  assert.ok(h.includes("jr-mech"), h);
  assert.ok(h.includes("stop <b>2</b> (0W–2L)") && h.includes("-4.00R"), `stop bucket: ${h}`);
  assert.ok(h.includes("time <b>1</b> (1W–0L)") && h.includes("+0.50R"), `time bucket: ${h}`);
  assert.ok(h.includes("target <b>1</b>") && h.includes("+2.00R"), `target bucket: ${h}`);
});

// ── batch-100 WS-C/WS-D: excursions, timeframe line, tide line ──────────────
suite("excursion honesty + timeframe split + tide line");

test("wrong-from-entry fires ONLY on a stop whose MFE never cleared the noise floor", () => {
  assert.equal(wrongFromEntry({ exit_reason: "stop", mfe_r: 0.0 }), true);
  assert.equal(wrongFromEntry({ exit_reason: "stop", mfe_r: 0.009 }), true);
  assert.equal(wrongFromEntry({ exit_reason: "stop", mfe_r: 0.3 }), false, "gave-back is a different lesson");
  assert.equal(wrongFromEntry({ exit_reason: "time", mfe_r: 0.0 }), false, "only full stops carry the dagger");
  assert.equal(wrongFromEntry({ exit_reason: "stop" }), false, "no MFE recorded -> no claim made");
});

test("the excursion tooltip carries high-water and worst, and vanishes without data", () => {
  const tip = excursionTip({ mfe_r: 0.683, mae_r: -0.21 });
  assert.ok(tip.includes("+0.68R") && tip.includes("-0.21R"));
  assert.equal(excursionTip({}), "");
});

test("every mechanism chip has a static definition and none names a live number", () => {
  for (const r of [...MECHANICAL_EXITS, "manual"]) {
    const tip = reasonTip(r);
    assert.ok(tip.length > 10, `${r} needs a definition`);
    assert.ok(!/\d+\.\d+R|[+-]\d+R/.test(tip), `${r} tip must not embed a live figure that can stale: ${tip}`);
  }
});

test("tfSplit conserves R — the timeframe buckets sum to the book's own total", () => {
  // Numeric parity (batch-100 item 77) against the REAL e2e fixture book.
  const book = JSON.parse(fs.readFileSync(
    path.resolve(__dirname, "e2e/fixtures/data/vivek_bot_book.json"), "utf8"));
  const by = tfSplit(book.closed);
  const sumTf = Object.values(by).reduce((n, b) => n + b.r, 0);
  const direct = book.closed.reduce((n, t) => n + (typeof t.realized_r === "number" ? t.realized_r : 0), 0);
  assert.ok(Math.abs(sumTf - direct) < 1e-9, `tf buckets ${sumTf} != book total ${direct}`);
  const nTf = Object.values(by).reduce((n, b) => n + b.n, 0);
  assert.equal(nTf, book.closed.length, "every closed row lands in exactly one bucket");
});

test("the timeframe line is silent below two timeframes and speaks above", () => {
  assert.equal(tfLineHTML([cl("stop", -1)]), "", "one unknown-tf bucket is not a split");
  const rows = [
    { status: "closed", timeframe: "1D", realized_r: -1, exit_reason: "stop" },
    { status: "closed", timeframe: "1W", realized_r: 0.5, exit_reason: "time" },
  ];
  const h = tfLineHTML(rows);
  assert.ok(h.includes("by timeframe:"), h);
  assert.ok(h.includes("1W") && h.includes("1D"));
  assert.ok(h.indexOf("1W") < h.indexOf("1D"), "canonical 1W/3D/1D order");
  assert.ok(h.includes("-1.00R") && h.includes("+0.50R"));
});

test("the mech line now carries the median hold in days", () => {
  const rows = [
    { status: "closed", exit_reason: "stop", realized_r: -1, hold_days: 9 },
    { status: "closed", exit_reason: "stop", realized_r: -1.2, hold_days: 22 },
    { status: "closed", exit_reason: "time", realized_r: 0.2, hold_days: 29 },
  ];
  const h = dctx.exitMechHTML(rows);
  assert.ok(h.includes("~22d") || h.includes("~9d"), `stop bucket median hold missing: ${h}`);
  assert.ok(h.includes("~29d"), `time bucket hold missing: ${h}`);
});

const TIDE_FIXTURE = {
  n_long: 30, n_short_untouched: 0, n_skipped_unpriced: 2, base_unreal_r: 8.65,
  method: "uniform beta-1 shock",
  shocks: [
    { shock_pct: 3.0, stopped: 0, unreal_r: 3.7, given_back_r: 5.0 },
    { shock_pct: 5.0, stopped: 2, unreal_r: -0.9, given_back_r: 9.5 },
    { shock_pct: 8.0, stopped: 3, unreal_r: -7.2, given_back_r: 15.8 },
  ],
};

test("the tide line states base, W/L split, the first two shocks, and unpriced rows", () => {
  const open = [{ unreal_r: 1 }, { unreal_r: -0.2 }, { unreal_r: 0.4 }];
  const h = tideHTML(TIDE_FIXTURE, open);
  assert.ok(h.includes("tide check:"), h);
  assert.ok(h.includes("+8.7R") && h.includes("30 longs"));
  assert.ok(h.includes("(2W/1L)"), "the winners/losers split of the same total");
  assert.ok(h.includes("+3.7R") && h.includes("(0 stops)"));
  assert.ok(h.includes("−0.9R") || h.includes("-0.9R"));
  assert.ok(h.includes("2 unpriced rows uncounted"), "skipped rows are named, never hidden");
  assert.ok(h.includes("-8%:"), "the full table rides the tooltip");
});

test("the tide line is INERT and hides without the artefact", () => {
  const h = tideHTML(TIDE_FIXTURE, []);
  assert.ok(!/<button|<a |href=/.test(h), "no control, no link - reporting, not advice");
  assert.equal(tideHTML(null, []), "");
  assert.equal(tideHTML({ shocks: [], n_long: 0 }, []), "");
});

test("the mixed-book decider line carries the shape BESIDE the split, not instead of it", () => {
  const h = deciderHTML([cl("stop", -1), cl("time", 1), cl("manual", 0.5)]);
  assert.ok(h.includes("jr-decider"), "the who-closed split stays intact");
  assert.ok(h.includes("jr-mech"), "the by-exit shape renders alongside it");
  assert.ok(h.indexOf("jr-decider") < h.indexOf("jr-mech"), "who first, how second");
});

// ── legacy-sizing marker (2026-08-20) ────────────────────────────────────────
// The 2026-07-28 resize left CLOSED rows at their real historical size (~$256
// avg notional) while everything current is fixed-notional at the published
// size — the marker is the only on-page admission that those dollars are a
// different scale. R is comparable; dollars are not. The 2026-09-27 resize
// ($5,000 -> $2,500, owner) did the same to the fixed-notional $5,000 closes,
// which the sizing_mode test cannot see — hence the off-scale half below.
suite("legacy sizing marker");

const lctx = vm.createContext({ console });
vm.runInContext(
  "const esc = (s) => String(s);\n"
  // The PUBLISHED size (as loadBotRules leaves it once bot_rules.json lands).
  + "let POSITION_NOTIONAL = 2500, NOTIONAL_LIVE = true, FX_AUDUSD = 0.66;\n"
  + slice("const money0 = (v) =>", ";\n") + "\n"
  + slice("const isAudRow = (t) =>", ";\n") + "\n"
  + slice("const fxOf = (t) =>", ";\n") + "\n"
  + slice("const offNotional = (t) =>", ";\n") + "\n"
  + slice("const legacySized = (t, side)", ";\n") + "\n"
  + slice("const LEGACY_TIP =", ";\n") + "\n"
  + slice("const faceMoney0 = (t, v) =>", ";\n") + "\n"
  + slice("const offScaleTip = (t) =>", ";\n") + "\n"
  + slice("const legacyCell = (t, side)", ";\n") + "\n"
  + "this.setLive = (v) => { NOTIONAL_LIVE = v; };\n"
  + "this.fxOf = fxOf;\n"
  + "this.legacySized = legacySized; this.legacyCell = legacyCell; this.LEGACY_TIP = LEGACY_TIP;\n",
  lctx);

test("risk_pct and ABSENT sizing_mode both mark a BOT row; fixed_notional AT the published size never does", () => {
  assert.equal(lctx.legacySized({ sizing_mode: "risk_pct" }, "bot"), true);
  assert.equal(lctx.legacySized({}, "bot"), true,
    "absent = written before the field existed = the same pre-resize cohort");
  assert.equal(lctx.legacySized({ sizing_mode: "fixed_notional", notional: 2500 }, "bot"), false);
  assert.equal(lctx.legacySized({ sizing_mode: "fixed_notional" }, "bot"), false,
    "no notional on the row = no evidence it is off-scale");
});

test("a fixed_notional row held at a DIFFERENT notional is marked (owner, 2026-09-27)", () => {
  // The 92 closed $5,000 rows beside a restated $2,500 open book: same mode
  // stamp, half the scale. Unmarked, their dollars read as like-for-like.
  assert.equal(lctx.legacySized({ sizing_mode: "fixed_notional", notional: 5000 }, "bot"), true);
  assert.equal(lctx.legacySized({ sizing_mode: "fixed_notional", notional: 1250 }, "bot"), true,
    "smaller-than-published is off-scale too");
  // 1% band = $25 at $2,500 — a rounding cent must never light the marker.
  assert.equal(lctx.legacySized({ sizing_mode: "fixed_notional", notional: 2525 }, "bot"), false, "at the band edge");
  assert.equal(lctx.legacySized({ sizing_mode: "fixed_notional", notional: 2526 }, "bot"), true, "just past it");
  assert.equal(lctx.legacySized({ sizing_mode: "fixed_notional", notional: 5000 }, "me"), false,
    "still bot rows only");
});

test("the off-scale tip names BOTH figures and is not the pre-2026-07-28 wording", () => {
  const m = lctx.legacyCell({ sizing_mode: "fixed_notional", notional: 5000 }, "bot");
  assert.ok(m.cls.includes("jr-oldsize"), "same quiet class as the pre-resize cohort");
  assert.ok(m.tip.includes("$5,000") && m.tip.includes("$2,500"), m.tip);
  assert.ok(m.tip.includes("Compare R"), "the tip must say what IS comparable");
  assert.ok(!m.tip.includes("pre-2026-07-28"), "a $5,000 row was not sized under the risk-% rules");
  // ...while a risk-% row keeps the old explanation, which must not claim the
  // current rows are $5,000 any more.
  const old = lctx.legacyCell({ sizing_mode: "risk_pct" }, "bot");
  assert.ok(old.tip.includes("pre-2026-07-28"), old.tip);
  assert.ok(!/\$5,000/.test(lctx.LEGACY_TIP), "LEGACY_TIP still states $5,000 as the current size");
});

test("an ASX row's off-scale tip labels BOTH figures A$ - they are face value, not the US$ cell beside it", () => {
  // Review FE-2 (2026-09-28). The $ cell next to the tip is US$-converted
  // (dollarsOf / unreal_usd x fxOf) and the page header says "$ figures in
  // US$", but the bot books an ASX row's notional at FACE VALUE in A$ (#61).
  // A bare "$5,000" there read as US$5,000 - an A$ holding overstated by the
  // FX rate, beside a cell that had already been converted.
  for (const row of [{ market: "asx" }, { asset_type: "asx" }]) {
    const m = lctx.legacyCell({ ...row, sizing_mode: "fixed_notional", notional: 5000 }, "bot");
    assert.ok(m.cls.includes("jr-oldsize"), JSON.stringify(row));
    assert.ok(m.tip.includes("Held at A$5,000 notional"), m.tip);
    assert.ok(m.tip.includes("position at A$2,500,"), `the PUBLISHED size is A$ on an ASX row too: ${m.tip}`);
    assert.ok(!/[^A]\$\d/.test(m.tip), `a bare $ figure survived on an ASX row: ${m.tip}`);
  }
});

test("a NASDAQ (or crypto) row's off-scale tip keeps a bare $ - its figures ARE US$", () => {
  for (const market of ["nasdaq", "crypto"]) {
    const m = lctx.legacyCell({ market, sizing_mode: "fixed_notional", notional: 5000 }, "bot");
    assert.ok(m.tip.includes("Held at $5,000 notional"), m.tip);
    assert.ok(m.tip.includes("position at $2,500,"), m.tip);
    assert.ok(!m.tip.includes("A$"), `a ${market} row is not A$: ${m.tip}`);
  }
});

test("the tip says A$ exactly when the $ cell is FX-converted - one predicate, two readers", () => {
  // The label is only honest if it agrees with fxOf, row for row, including
  // the manual-row asset_type field and a bot market that wins over it.
  const rows = [
    { market: "asx" }, { asset_type: "asx" }, { market: "nasdaq" }, { market: "crypto" },
    { market: "nasdaq", asset_type: "asx" }, { market: "", asset_type: "asx" }, {},
  ];
  for (const row of rows) {
    const tip = lctx.legacyCell({ ...row, sizing_mode: "fixed_notional", notional: 5000 }, "bot").tip;
    assert.equal(tip.includes("A$"), lctx.fxOf(row) !== 1,
      `tip and fxOf disagree about ${JSON.stringify(row)}: ${tip}`);
  }
  assert.ok(/const fxOf = \(t\) => \(isAudRow\(t\)/.test(SRC)
    && /const faceMoney0 = \(t, v\) => \(isAudRow\(t\)/.test(SRC),
    "fxOf and faceMoney0 must both read isAudRow, or the two can drift apart");
});

test("the off-scale half is OFF until the notional is PUBLISHED (the e2e fixture publishes none)", () => {
  // The fixture book's fixed_notional rows carry $36-$872; driven by the
  // hand-typed fallback, every one of them would be underlined and the
  // journal screenshots would move.
  lctx.setLive(false);
  try {
    assert.equal(lctx.legacySized({ sizing_mode: "fixed_notional", notional: 36.66 }, "bot"), false);
    assert.equal(lctx.legacySized({ sizing_mode: "fixed_notional", notional: 5000 }, "bot"), false);
    assert.equal(lctx.legacySized({ sizing_mode: "risk_pct" }, "bot"), true,
      "the pre-2026-07-28 cohort is marked unconditionally");
  } finally { lctx.setLive(true); }
});

test("manual ('me') rows are hand-sized and NEVER marked", () => {
  assert.equal(lctx.legacySized({ sizing_mode: "risk_pct" }, "me"), false);
  assert.equal(lctx.legacySized({}, "me"), false);
});

test("the marked cell carries the class and the why, an unmarked cell carries neither", () => {
  const m = lctx.legacyCell({ sizing_mode: "risk_pct" }, "bot");
  assert.ok(m.cls.includes("jr-oldsize"));
  assert.ok(m.tip.includes("not") && m.tip.includes("like-for-like"));
  assert.ok(m.tip.includes("Compare R"), "the tip must say what IS comparable");
  const clean = lctx.legacyCell({ sizing_mode: "fixed_notional" }, "bot");
  assert.equal(clean.cls, ""); assert.equal(clean.tip, "");
});

test("both dollar cells consult it and the CSS class exists", () => {
  // closed table + live open cells — a marker rendered in one table and not
  // the other would read as two different claims about the same row.
  const cells = (SRC.match(/legacyCell\(t, side\)/g) || []).length;
  assert.ok(cells >= 3, `expected the closed $ cell and both open $ branches to consult it, saw ${cells}`);
  const css = fs.readFileSync(path.resolve(__dirname, "../public/css/journal.css"), "utf8");
  assert.ok(/\.jr-oldsize\s*\{/.test(css), ".jr-oldsize has no CSS rule");
});

test("the marker is quiet by construction - no pulse, no colour override in its rule", () => {
  const css = fs.readFileSync(path.resolve(__dirname, "../public/css/journal.css"), "utf8");
  const rule = css.match(/\.jr-oldsize\s*\{[^}]*\}/)[0];
  assert.ok(!/animation|color\s*:/.test(rule),
    "a legibility fix, not a warning - match the .jr-stale restraint");
});

test("journal.css gives BOTH previously-unstyled reasons a rule", () => {
  // Before this, .jr-reason-manual and .jr-reason-time did not exist, so the
  // bot's time-stop and the owner's click rendered as the same grey chip.
  const css = fs.readFileSync(path.resolve(__dirname, "../public/css/journal.css"), "utf8");
  assert.ok(/\.jr-reason-time\s*\{/.test(css), ".jr-reason-time has no rule");
  assert.ok(/\.jr-reason-manual\s*\{/.test(css), ".jr-reason-manual has no rule");
  for (const c of ["target", "trail", "stop"]) {
    assert.ok(new RegExp(`\\.jr-reason-${c}\\s*\\{`).test(css), `.jr-reason-${c} was dropped`);
  }
});


// ── w3-1 progress line (2026-08-15) ─────────────────────────────────────────
// The one number that decides everything — the pre-registered cycle's progress
// to its 30-close readout — lived only in raw book JSON. One quiet line now
// renders above the bot stats. These pins hold its honesty properties.
suite("w3-1 progress line");

// Session B (2026-08-19): the line became a strip that names WHO took each
// gated exit, so it now pulls in the shared exit-classifier, the tag/target
// constants and the row builder. All four are sliced from the shipped file —
// re-typing the classifier here is exactly the drift this suite exists to
// catch, since a mirrored copy would agree with a broken original.
const w3ctx = vm.createContext({ console });
vm.runInContext(
  slice("const MECHANICAL_EXITS =", "];")
  + "\n" + slice("const W3_TAG =", ";")
  + "\n" + slice("const W3_TARGET =", ";")
  + "\n" + slice("const W3_ENDED =", ";")
  + "\n" + slice("const W3_BAND =", ";")
  + "\nlet LIVE_CYCLE = 'hc4-1';"
  + "\n" + slice("const esc =", "[c]));")
  + "\n" + slice("function w3Readout(d) {", "\n  }")
  + "\n" + slice("const w3Verdict = (x) =>", ");\n")
  + "\n" + slice("function w3Rows(d) {", "\n  }")
  + "\n" + slice("function w3Line(d) {", "\n  }")
  + "\nthis.w3Line = w3Line; this.w3Rows = w3Rows; this.w3Readout = w3Readout;"
  + "\nthis.setCycle = (t) => { LIVE_CYCLE = t; };", w3ctx);
const { w3Line, w3Rows, w3Readout } = w3ctx;
const w3row = (cycle) => (cycle ? { cycle } : {});
const w3close = (o) => Object.assign(
  { cycle: "w3-1", symbol: "SGP", market: "asx", exit_reason: "manual",
    realized_r: -0.077, hold_days: 15, exit_date: "2026-08-18" }, o || {});

test("counts stamped open and stamped closes, and states the /30 target", () => {
  const h = w3Line({ open: [w3row("w3-1"), w3row("w3-1"), w3row()], closed: [w3row("w3-1"), w3row()] });
  assert.ok(h.includes("<b>2</b>"), "stamped-open count wrong");
  assert.ok(h.includes("<b>1/30</b>"), "gated-close count must be stated against the 30-close readout");
});

test("SILENT when nothing carries the stamp — fixtures, pre-cycle books, the manual side", () => {
  assert.equal(w3Line({ open: [w3row()], closed: [w3row()] }), "");
  assert.equal(w3Line({ open: [], closed: [] }), "");
});

test("a different cycle tag is not counted as w3-1", () => {
  // The audit-tag design (config: VIVEK_BOT_CYCLE_TAG) allows future cycles;
  // a w4 row leaking into the w3 line would blur exactly the cohorts the
  // stamp exists to keep apart.
  assert.equal(w3Line({ open: [w3row("w4-1")], closed: [] }), "");
});

test("renderSide injects it above the bot stats, and re-render does not duplicate", () => {
  assert.ok(/document\.querySelectorAll\("#bot-w3, #bot-hc"\)\.forEach\(\(el\) => el\.remove\(\)\);/.test(SRC),
    "the remove-before-insert guard is gone - every refresh would stack another line");
  assert.ok(/host\.insertAdjacentHTML\("beforebegin", cycleLine\(d\)\)/.test(SRC),
    "renderSide no longer renders the current-cycle scoreboard");
  assert.ok(/host\.insertAdjacentHTML\("beforebegin", w3Line\(d\)\)/.test(SRC),
    "renderSide no longer renders the w3 line");
});

// ---------------------------------------------------------------------------
test("the fired review checkpoint states the BLEND, and reads as the owner's call", () => {
  // Lane A (2026-08-16). It used to read "✅ Review checkpoint reached — time
  // to review", which celebrates a threshold and invites reading ONE combined
  // record. A 30+ close book is two records: measured at head, 19 closes by
  // the rules at -6.97R against 23 owner closes at -0.15R. Judging the blend
  // as if one system produced it is how a rules problem gets blamed on the
  // market. Pre-30 wording is deliberately untouched — nothing is decided yet.
  const src = fs.readFileSync(path.join(__dirname, "..", "public", "js", "journal.js"), "utf8");
  const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  assert.ok(/const sp = deciderSplit\(state\.bot\.closed\)/.test(code),
    "the checkpoint must derive the split from the SHIPPED deciderSplit, not recount");
  assert.ok(/\$\{sp\.bot\} by the rules, \$\{sp\.own\} closed by you/.test(code),
    "the fired line must name both records");
  assert.ok(/your call, nothing is locked now/.test(code),
    "it must hand the decision back rather than instruct");
  assert.ok(!/✅ Review checkpoint reached/.test(code),
    "the celebratory tick is back on the one line that needs careful reading");
  assert.ok(/stay locked until then/.test(code),
    "the PRE-30 wording must be untouched — the gate itself has not moved");
});


// ── UI PASS 2026-08-18: condense the journal without losing a number ───────
suite("UI pass — condensation");

test("prices are formatted by MAGNITUDE, not at six decimals", () => {
  // Measured on the live open table before this: ENTRY 34.279999 / 182.589996,
  // STOP 21.934136 / 108.716691. Six decimals on a stop reads as machine
  // output. Display only — nothing stored, no R, no sizing.
  const px = new Function("return " + slice("const px   = (v) =>", "};").replace(/^const px\s*=\s*/, "") + ";")();
  assert.strictEqual(px(34.279999), "34.28", "a $34 stock quotes in cents");
  assert.strictEqual(px(182.589996), "182.59");
  assert.strictEqual(px(21.934136), "21.93", "a stop is a price, not a float dump");
  assert.strictEqual(px(1.455), "1.455", "a $1.45 ASX name keeps tenths of a cent");
  assert.strictEqual(px(0.029), "0.029", "sub-dollar names keep their resolution");
  assert.strictEqual(px(0.00001234), "0.000012", "a micro-cap still gets its tail");
  assert.strictEqual(px(null), "—");
  assert.strictEqual(px(NaN), "—");
});

test("the closed table previews 10 and keeps every row in the DOM", () => {
  // 1,884px for 45 rows was 36% of the page and grows with every close. Rows
  // past the preview are HIDDEN, never sliced: data-card="side:idx" indexes
  // into cardReg[side], so dropping rows would silently point every share-card
  // button at the wrong trade.
  const src = SRC;
  assert.ok(/const CLOSED_PREVIEW = 10;/.test(src), "the preview size is gone");
  assert.ok(/i >= CLOSED_PREVIEW \? ' class="jr-row-more"' : ""/.test(src),
    "rows past the preview must be marked, not removed");
  assert.ok(/sorted\.map\(\(t, i\)/.test(src), "indices must still come from the FULL sorted list");
  assert.ok(!/sorted\.slice\(0, CLOSED_PREVIEW\)/.test(src),
    "slicing the array would desync every share-card button");
  assert.ok(/jr-closed-wrap/.test(src) && /data-more/.test(src), "the reveal control is gone");
  assert.ok(/Show all \$\{sorted\.length\} closed trades/.test(src),
    "the button must say how many are behind it");
});

test("the reveal toggles in place and never re-renders the table", () => {
  // A re-render would collapse the list under the 3-minute refresh while the
  // owner is reading it.
  const code = SRC.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  assert.ok(/const wrap = more\.closest\("\.jr-closed-wrap"\)/.test(code));
  assert.ok(/wrap\.classList\.toggle\("is-open"\)/.test(code), "must toggle, not re-render");
  assert.ok(/more\.setAttribute\("aria-expanded"/.test(code), "state must reach assistive tech");
});

test("the realised figure is said ONCE — the header sparkline is retired", () => {
  // -$1,358 / -6.88R appeared three times: this header row, the TOTAL $ and
  // TOTAL R tiles, and the end labels of the full equity curve below.
  const html = fs.readFileSync(path.join(__dirname, "..", "public", "journal.html"), "utf8");
  assert.ok(!/id="jr-pnl-track"/.test(html), "the duplicate realised row is back");
  assert.ok(!/jr-pnl-spark/.test(SRC), "journal.js still renders the retired sparkline");
  // drawEquity is what draws the per-book curves. This line used to assert
  // /drawMiniEquity/, the retired header sparkline -- a function with no
  // caller -- so it passed while testing nothing (hygiene map section 8).
  assert.ok(/\bdrawEquity\(pre \+ "-equity", series\(d\.closed\)/.test(SRC),
    "the per-book equity curves must still be drawn (drawEquity, called per book)");
  assert.ok(/id="jr-pnl-total"/.test(html), "the UNREALISED headline must stay — it is this block's job");
});

test("the four analytics panels fold, and every one still exists", () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "public", "journal.html"), "utf8");
  const fold = html.indexOf('id="jr-perf-fold"');
  assert.ok(fold > 0, "the performance fold is gone");
  const close = html.indexOf("</details>", fold);
  const inside = html.slice(fold, close);
  for (const id of ["jr-digest", "jr-rdist", "jr-xq", "jr-edge-card"]) {
    assert.ok(inside.includes(`id="${id}"`), `${id} must still exist, inside the fold`);
  }
});

test("what must stay visible WITHOUT a click stays visible", () => {
  // The guardrails from the audit: condensing may fold or deduplicate, never
  // hide the two numbers that answer "is the system working".
  const html = fs.readFileSync(path.join(__dirname, "..", "public", "journal.html"), "utf8");
  const fold = html.indexOf('id="jr-perf-fold"');
  const close = html.indexOf("</details>", fold);
  const inside = html.slice(fold, close);
  assert.ok(!inside.includes('id="stalled-strip"'), "the stalled strip must not be folded away");
  assert.ok(!inside.includes('id="jr-pnl"'), "the P&L headline must not be folded away");
  assert.ok(/id="stalled-strip"/.test(html) && /id="jr-pnl"/.test(html));
  // the w3-1 line and the decider split are rendered by journal.js, unfolded
  assert.ok(/bot-w3/.test(SRC), "the w3-1 experiment line must still render");
  assert.ok(/deciderSplit/.test(SRC), "the rules-vs-owner split must still render");
});

test("the stalled explainer moved to a tooltip — words kept, weight gone", () => {
  const st = fs.readFileSync(path.join(__dirname, "..", "public", "js", "stalled.js"), "utf8");
  assert.ok(!/class="st-foot"/.test(st), "the permanent paragraph is back");
  assert.ok(/class="st-tag" title="/.test(st), "the explainer did not land in the tooltip");
  assert.ok(/stale probe/.test(st), "the words themselves must survive somewhere");
});


// ── w3-1 EXIT EVIDENCE (Session B, 2026-08-19) ──────────────────────────────
// The cycle counts to 30 closes and the count implies the 30 will measure the
// RULESET. At head every gated close is the owner's, so the number is measuring
// hand-timing instead. These pins hold the three properties that make the strip
// worth having: it states the split, it says the zero case in words, and it
// stays inert — a surface that nudged more manual closes would manufacture the
// very confound it exists to report.
suite("w3-1 exit evidence");

test("the headline states WHO closed, not just how many", () => {
  const h = w3Line({
    open: [w3row("w3-1"), w3row("w3-1")],
    closed: [w3close({ symbol: "SGP" }), w3close({ symbol: "XYZ", exit_reason: "stop" })],
  });
  assert.ok(h.includes("<b>2</b> gated open"), "open count missing");
  assert.ok(h.includes("<b>2/30</b>"), "close count missing");
  assert.ok(/<b>1<\/b> by the rules/.test(h), "rules-side count missing");
  assert.ok(/<b>1<\/b> by you/.test(h), "owner-side count missing");
});

test("no closes yet -> the split clause is OMITTED, not printed as two zeros", () => {
  // "0 by the rules · 0 by you" before anything has closed is noise that
  // teaches the eye to skip the line it will later need to read.
  const h = w3Line({ open: [w3row("w3-1")], closed: [] });
  assert.ok(h.includes("<b>0/30</b>"), "the progress must still show");
  assert.ok(!/by the rules/.test(h), "the split clause must not render at zero closes");
});

test("ZERO RULES-SIDE CLOSES IS SAID IN WORDS — the whole reason this exists", () => {
  const h = w3Line({ open: [], closed: [w3close(), w3close({ symbol: "AIA" })] });
  assert.ok(/jr-w3-flag/.test(h), "the zero-rules callout is missing");
  assert.ok(/measures your timing, not the ruleset/.test(h),
    "the callout must name what the sample can and cannot support");
});

test("one rules-side close and the callout goes away", () => {
  const h = w3Line({ open: [], closed: [w3close(), w3close({ exit_reason: "trail" })] });
  assert.ok(!/jr-w3-flag/.test(h), "the callout must not survive a real rules exit");
});

test("an ABSENT exit_reason counts as yours, exactly as deciderSplit reads it", () => {
  // Two readers of the same field must not disagree about a row: a close with
  // no recorded mechanism was not closed by one.
  const rows = w3Rows({ closed: [w3close({ exit_reason: undefined }), w3close({ exit_reason: "" })] });
  assert.deepEqual(rows.map((r) => r.who), ["you", "you"]);
  assert.deepEqual(rows.map((r) => r.path), ["unrecorded", "unrecorded"]);
});

test("only stamped CLOSED rows are listed — opens and other cycles are not exits", () => {
  const rows = w3Rows({ closed: [
    w3close({ symbol: "IN" }),
    w3close({ symbol: "OUT", cycle: "w4-1" }),
    w3close({ symbol: "NONE", cycle: undefined }),
  ] });
  assert.deepEqual(rows.map((r) => r.symbol), ["IN"]);
});

test("exits are listed newest first — the last thing that happened reads first", () => {
  const rows = w3Rows({ closed: [
    w3close({ symbol: "OLD", exit_date: "2026-08-01" }),
    w3close({ symbol: "NEW", exit_date: "2026-08-18" }),
    w3close({ symbol: "MID", exit_date: "2026-08-09" }),
  ] });
  assert.deepEqual(rows.map((r) => r.symbol), ["NEW", "MID", "OLD"]);
});

test("THE STRIP IS INERT — no control that could invite another manual close", () => {
  const h = w3Line({ open: [w3row("w3-1")], closed: [w3close()] });
  assert.ok(!/<button|<a\s|<form|onclick=/i.test(h),
    "the evidence strip grew a control; it must never read as a call to act");
  assert.ok(!/\bclose\s+(?:these|them|it|now)\b/i.test(h), "wording invites closing");
  assert.ok(/<details class="jr-w3-fold">/.test(h) && !/<details[^>]*\bopen\b/.test(h),
    "the exit list must be folded shut by default");
});

test("R renders signed, two-dp, and coloured by sign", () => {
  const h = w3Line({ open: [], closed: [
    w3close({ symbol: "WIN", realized_r: 0.367 }),
    w3close({ symbol: "LOSS", realized_r: -0.077 }),
  ] });
  assert.ok(/<span class="w3-r pos">\+0\.37R<\/span>/.test(h), "winner not rendered as a positive");
  assert.ok(/<span class="w3-r neg">-0\.08R<\/span>/.test(h), "loser not rendered as a negative");
});

test("a missing R is a dash, never a zero", () => {
  const h = w3Line({ open: [], closed: [w3close({ realized_r: null })] });
  assert.ok(/>—</.test(h), "an unpriced exit must not be drawn as breakeven");
});

test("symbol and exit path are escaped before they reach innerHTML", () => {
  const h = w3Line({ open: [], closed: [w3close({ symbol: '<img src=x>', exit_reason: '"evil"' })] });
  assert.ok(!/<img src=x>/.test(h), "symbol reached the DOM unescaped");
  assert.ok(!/"evil"/.test(h) || /&quot;evil&quot;/.test(h), "exit path reached the DOM unescaped");
});

// ── w3-1 ENDED, AND ITS READOUT (REFINE200 #194) ────────────────────────────
suite("w3-1 — the cycle ended, and its 30-close readout is printed");

// 30+ closes: the first 30 in EXIT order are the pre-registered readout.
const w3book = (n, rOf, extra) => ({ open: [w3row("w3-1")], closed: Array.from({ length: n }, (_, i) =>
  w3close(Object.assign({ symbol: "S" + i, exit_date: `2026-09-${String(1 + Math.floor(i / 3)).padStart(2, "0")}`,
    realized_r: rOf(i), exit_reason: i % 4 === 0 ? "stop" : "manual" }, (extra || {})[i] || {}))) });

test("the strip says the cycle ENDED and names the current one", () => {
  const h = w3Line({ open: [w3row("w3-1")], closed: [w3close()] });
  assert.ok(/ended 2026-09-21/.test(h), "the strip still reads like a live cycle");
  assert.ok(/hc4-1 is current/.test(h), "the current cycle is not named");
  w3ctx.setCycle("hc5-1");
  try { assert.ok(/hc5-1 is current/.test(w3Line({ open: [w3row("w3-1")], closed: [] })),
    "the current cycle must follow the published tag, not a literal"); }
  finally { w3ctx.setCycle("hc4-1"); }
});

test("below 30 closes there is no readout, only the counter", () => {
  const h = w3Line(w3book(29, () => -0.2));
  assert.equal(w3Readout(w3book(29, () => -0.2)), null);
  assert.ok(/<b>29\/30<\/b>/.test(h) && !/jr-w3-readout/.test(h));
});

test("past 30 closes the counter becomes the readout, measured on the FIRST 30 in exit order", () => {
  // First 30 average -0.20R; the 10 later closes are +1R each, so the all-close
  // average (+0.10R) differs and a readout computed on everything would show.
  const book = w3book(40, (i) => (i < 30 ? -0.2 : 1));
  const shuffled = { open: book.open, closed: book.closed.slice().reverse() };
  const ro = w3Readout(shuffled);
  assert.ok(Math.abs(ro.readout - -0.2) < 1e-9, `readout ${ro.readout} is not the first 30's average`);
  assert.ok(Math.abs(ro.all - ((30 * -0.2 + 10) / 40)) < 1e-9, String(ro.all));
  assert.equal(ro.at, "2026-09-10", "the readout date is the 30th close's exit date");
  const h = w3Line(shuffled);
  assert.ok(!/\/30<\/b> closes/.test(h), "the strip still counts toward a target it passed");
  assert.ok(/<b>40<\/b> closes/.test(h));
  assert.ok(/Readout at 30 closes \(2026-09-10\): <b>-0\.20R<\/b> a trade/.test(h), h);
  assert.ok(/at or past the -0\.05 kill line/.test(h), "the band verdict is missing");
  assert.ok(/All 40 closes to date: \+0\.10R/.test(h), h);
  assert.ok(/the rules' own 10 exits/.test(h), "the rules-only figure is missing");
});

test("the readout is placed against the band in plain words, at every level", () => {
  const at = (r) => w3Line(w3book(30, () => r));
  assert.ok(/below the band \(pess \+0\.056\)\./.test(at(0.0)), at(0.0));
  assert.ok(/inside the band/.test(at(0.08)));
  assert.ok(/at or above the band's mid/.test(at(0.2)));
});

test("the readout is still inert — a result, not an instruction", () => {
  const h = w3Line(w3book(35, () => -0.5));
  assert.ok(!/<button|<a\s|<form|onclick=/i.test(h));
  assert.ok(!/\b(kill it|stop the|you should|switch off)\b/i.test(h), "the readout tells the owner what to do");
});

// ── the current cycle's per-cell scoreboard (REFINE200 #37) ─────────────────
suite("current-cycle scoreboard — per entry cell");

const hcctx = vm.createContext({ console });
vm.runInContext(
  slice("const MECHANICAL_EXITS =", "];")
  + "\n" + slice("const esc =", "[c]));")
  + "\n" + slice("const rcls = (r) =>", ";\n")
  + "\n" + slice("const TF_NAME =", ";\n")
  + "\n" + slice("const CYCLE_TAG =", ";")
  + "\n" + slice("let LIVE_CYCLE =", ";")
  + "\n" + slice("let ENTRY_CELLS =", ";\n")
  + "\n" + slice("const cellsOf = (ec) =>", "\n  };")
  + "\n" + slice("function cycleCells(d, tag, cells) {", "\n  }")
  + "\n" + slice("function cycleLine(d) {", "\n  }")
  + "\nthis.cycleCells = cycleCells; this.cycleLine = cycleLine; this.cellsOf = cellsOf;"
  + "\nthis.setLive = (t, c) => { LIVE_CYCLE = t; if (c) ENTRY_CELLS = c; };"
  + "\nthis.cells = () => ENTRY_CELLS;", hcctx);
const hcRow = (o) => Object.assign({ cycle: "hc4-1", timeframe: "3D", entry_type: "reclaim" }, o || {});
const HC_BOOK = {
  open: [hcRow(), hcRow({ timeframe: "1W" }), hcRow({ timeframe: "1D", entry_type: "break" }), hcRow({ cycle: "w3-1" })],
  closed: [
    hcRow({ exit_reason: "stop", realized_r: -1.1 }), hcRow({ exit_reason: "trail", realized_r: 0.05 }),
    hcRow({ exit_reason: "manual", realized_r: 0.3 }), hcRow({ timeframe: "1W", exit_reason: "time", realized_r: -0.2 }),
    hcRow({ cycle: "w3-1", exit_reason: "stop", realized_r: -1 }),
  ],
};
const CELLS4 = [["1W", "reclaim"], ["1W", "break"], ["3D", "reclaim"], ["1D", "break"]];

test("each cell counts its own opens, closes, rules R and hand closes", () => {
  const c = hcctx.cycleCells(HC_BOOK, "hc4-1", CELLS4);
  const by = Object.fromEntries(c.map((x) => [x.tf + " " + x.et, x]));
  assert.equal(c.length, 4, "no 'other' bucket when every row fits a cell");
  assert.deepEqual([by["3D reclaim"].open, by["3D reclaim"].closed, by["3D reclaim"].rules, by["3D reclaim"].hand], [1, 3, 2, 1]);
  assert.ok(Math.abs(by["3D reclaim"].rulesR - -1.05) < 1e-9, "rules R is the stop + the trail only");
  assert.ok(Math.abs(by["3D reclaim"].handR - 0.3) < 1e-9, "the hand close is kept apart");
  assert.deepEqual([by["1W reclaim"].open, by["1W reclaim"].rules], [1, 1]);
  assert.equal(by["1D break"].open, 1);
  assert.deepEqual([by["1W break"].open, by["1W break"].closed], [0, 0]);
});

test("only rows stamped with the CURRENT tag are counted", () => {
  const c = hcctx.cycleCells(HC_BOOK, "hc4-1", CELLS4);
  assert.equal(c.reduce((n, x) => n + x.open + x.closed, 0), 7, "a w3-1 row leaked into the hc4-1 board");
});

test("a stamped row outside every cell lands in 'other', never vanishes", () => {
  const c = hcctx.cycleCells({ open: [hcRow({ timeframe: "4H" })], closed: [] }, "hc4-1", CELLS4);
  assert.equal(c.length, 5);
  assert.equal(c[4].et, "other");
  assert.equal(c[4].open, 1);
});

test("the board renders per cell with avg R, and is INERT", () => {
  const h = hcctx.cycleLine(HC_BOOK);
  assert.ok(/hc4-1 · current cycle · <b>3<\/b> open · <b>4<\/b> closed · <b>3<\/b> by the rules · <b>1<\/b> by hand/.test(h), h);
  assert.ok(/3-Day reclaim<\/td><td class="num">1<\/td><td class="num">3<\/td>/.test(h), h);
  assert.ok(/-0\.53R/.test(h), "the 3D reclaim rules average (-1.05 / 2) is missing");
  assert.ok(/Weekly break<\/td><td class="num">0<\/td><td class="num">0<\/td><td class="num">—<\/td>/.test(h),
    "an empty cell must read as a dash, never a fake +0.00R");
  assert.ok(!/<button|<a\s|<form|onclick=|<details[^>]*\bopen\b/i.test(h), "the scoreboard grew a control");
});

test("silent until a row carries the current tag", () => {
  assert.equal(hcctx.cycleLine({ open: [hcRow({ cycle: "w3-1" })], closed: [] }), "");
  assert.equal(hcctx.cycleLine({ open: [], closed: [] }), "");
});

test("the tag and the cells come from bot_rules.json when published", () => {
  assert.deepEqual(JSON.parse(JSON.stringify(hcctx.cellsOf({ "1W": ["reclaim", "break"], "3D": ["reclaim"], "1D": ["break"] }))),
    CELLS4, "entry_cells must flatten in the order the bot walks them");
  assert.equal(hcctx.cellsOf(null), null);
  assert.equal(hcctx.cellsOf({ "1W": "reclaim" }), null, "a malformed table keeps the fallback");
  hcctx.setLive("hc5-1", [["3D", "reclaim"]]);
  try {
    const h = hcctx.cycleLine({ open: [hcRow({ cycle: "hc5-1" })], closed: [] });
    assert.ok(/hc5-1 · current cycle/.test(h), h);
    assert.equal((h.match(/<tr><td>/g) || []).length, 1, "the board must follow the published cells");
  } finally { hcctx.setLive("hc4-1", CELLS4); }
});

test("the fallback cells equal config's VIVEK_BOT_ENTRY_CELLS (order included)", () => {
  const cfg = fs.readFileSync(path.resolve(__dirname, "../scanner/config.py"), "utf8");
  const m = /VIVEK_BOT_ENTRY_CELLS\s*=\s*\{([\s\S]*?)\}/.exec(cfg);
  assert.ok(m, "config.VIVEK_BOT_ENTRY_CELLS moved — this pin needs re-pointing");
  const pairs = [];
  for (const mm of m[1].matchAll(/"(\w+)"\s*:\s*\(([^)]*)\)/g))
    for (const et of mm[2].matchAll(/"(\w+)"/g)) pairs.push([mm[1], et[1]]);
  assert.deepEqual(JSON.parse(JSON.stringify(hcctx.cells())), pairs);
});


// ── closes carry a DATE, not a time (REFINE200 #187) ────────────────────────
// No closed row records when in the day it closed. exitMs used to parse
// `${exit_date}T16:00`, so every closed trade read "04:00 PM" — for crypto and
// NASDAQ closes alike — and the hold column was measured to that invented time.
suite("close time — the date only, holds counted in days from dates");

const tctx = vm.createContext({ console });
vm.runInContext(
  slice("function exitMs(t) {", "\n  }") + "\n"
  + slice("const ymd = (d) =>", ";\n") + "\n"
  + slice("function exitDay(t) {", "\n  }") + "\n"
  + slice("function holdText(t) {", "\n  }") + "\n"
  + slice("function stamp(ms) {", "\n  }") + "\n"
  + slice("function closeStamp(t) {", "\n  }") + "\n"
  + slice("function weekBounds(off) {", "\n  }") + "\n"
  + "this.exitMs = exitMs; this.exitDay = exitDay; this.holdText = holdText;"
  + "this.closeStamp = closeStamp; this.weekBounds = weekBounds;", tctx);

test("a date-only close is ordered at its local midnight — never at an invented 16:00", () => {
  const ms = tctx.exitMs({ exit_date: "2026-09-17" });
  const d = new Date(ms);
  assert.deepEqual([d.getFullYear(), d.getMonth(), d.getDate(), d.getHours(), d.getMinutes()], [2026, 8, 17, 0, 0]);
  assert.equal(tctx.exitMs({ exit_date: "" }), null);
  assert.equal(tctx.exitMs({}), null);
});

test("the Closed cell prints the DATE alone for a date-only row", () => {
  const txt = tctx.closeStamp({ exit_date: "2026-09-17" });
  assert.ok(/17/.test(txt), txt);
  assert.ok(!/:|AM|PM|04/.test(txt), `an invented time is back on the close: "${txt}"`);
  assert.equal(tctx.closeStamp({}), "—");
});

test("a row that DOES carry closed_at keeps its real time", () => {
  const at = "2026-09-17T05:30:00Z";
  assert.equal(tctx.exitMs({ closed_at: at, exit_date: "2026-09-17" }), Date.parse(at));
  assert.ok(/:/.test(tctx.closeStamp({ closed_at: at })), "a real close time must still be shown");
});

test("hold is whole days from the dates — the engine's hold_days first", () => {
  assert.equal(tctx.holdText({ hold_days: 15, entry_date: "2026-01-01", exit_date: "2026-01-02" }), "15d");
  assert.equal(tctx.holdText({ entry_date: "2026-09-01", exit_date: "2026-09-17" }), "16d");
  assert.equal(tctx.holdText({ entry_date: "2026-09-17", exit_date: "2026-09-17" }), "0d");
  assert.equal(tctx.holdText({ entry_date: "2026-09-17" }), "—");
});

test("the week review buckets closes by DATE against the week's seven local dates", () => {
  const wb = tctx.weekBounds(0);
  assert.equal(wb.days.length, 7);
  const mon = wb.mon;
  assert.equal(wb.days[0], `${mon.getFullYear()}-${String(mon.getMonth() + 1).padStart(2, "0")}-${String(mon.getDate()).padStart(2, "0")}`);
  assert.equal(tctx.exitDay({ exit_date: wb.days[6] }), wb.days[6], "Sunday's date-only close lands on Sunday");
  assert.ok(/weekDays\.includes\(exitDay\(t\)\)/.test(CODE), "the week filter went back to millisecond windows");
  assert.ok(/weekDays\.indexOf\(exitDay\(t\)\)/.test(CODE), "the day dots went back to millisecond arithmetic");
});

test("no render path measures a close against an invented time any more", () => {
  assert.ok(!/T\$\{t\.exit_time \|\| "16:00"\}/.test(CODE), "the 16:00 default is back");
  assert.ok(!/durText\(openedMs\(t\), exitMs\(t\)\)/.test(CODE), "a hold is measured to exitMs again");
  assert.ok(/\$\{closeStamp\(t\)\}<span class="num-sub"> · \$\{holdText\(t\)\}/.test(CODE), "the Closed cell lost its date/hold");
});

// ── exit quality + the R-distribution caption (REFINE200 #186) ─────────────
suite("exit quality — slippage is a STOP measure; the caption tracks the average");

const xqctx = vm.createContext({ console });
vm.runInContext(
  "const els = {}; const $ = (sel) => (els[sel] = els[sel] || { innerHTML: '', textContent: '', hidden: true });\n"
  + "let state = { bot: { closed: [] } };\n"
  + slice("const esc =", "[c]));") + "\n"
  + slice("const up  = (s) =>", ";\n") + "\n"
  + slice("const rcls = (r) =>", ";\n") + "\n"
  + slice("const rfmt = (r) =>", ";\n") + "\n"
  + slice("const MECHANICAL_EXITS =", "];") + "\n"
  + slice("const SLIP_EPS =", ";") + "\n"
  + slice("function renderExitQuality() {", "\n  }") + "\n"
  + slice("function rdistNote(counts, n, extra) {", "\n  }") + "\n"
  + "this.run = (closed) => { state = { bot: { closed } }; renderExitQuality();"
  + " return { grid: $('#jr-xq-grid').innerHTML, verdict: $('#jr-xq-verdict').textContent }; };"
  + "this.rdistNote = rdistNote;", xqctx);
const xc = (reason, r, o) => Object.assign({ symbol: "S", exit_reason: reason, realized_r: r, mfe_r: 0.1, mae_r: Math.min(r, 0) }, o || {});
// The live shape that bit: 4 stops past -1R, and many small hand-closed losers.
const XQ = [xc("stop", -1.2), xc("stop", -1.25), xc("stop", -1.15), xc("stop", -1.2, { symbol: "WHC" }),
  ...Array.from({ length: 12 }, () => xc("manual", -0.2)), xc("time", -0.3), xc("target", 2.1)];

test("slippage reads off the stop exits — not '≈none' beside a column of stop breaches", () => {
  const { grid, verdict } = xqctx.run(XQ);
  assert.ok(!/≈none/.test(grid), "the stop exits average -1.20R; slippage is not 'none'");
  assert.ok(/Stop slippage<\/span><span class="jr-dg-val neg">-0\.20R avg past plan/.test(grid), grid);
  assert.ok(/Stop exits only \(4, average -1\.20R\)/.test(grid), "the cell must say what it averaged");
  assert.ok(/4 of 17 losers closed past the −1R stop/.test(verdict), verdict);
  assert.ok(/Stop exits average -1\.20R over 4 — about 0\.20R past plan/.test(verdict), verdict);
  assert.ok(/12 of 17 closed by hand/.test(verdict), "the hand closes behind the average loser must be named");
  assert.ok(!/× the planned 1R/.test(verdict), "the all-losers risk multiple is back");
});

test("stops that land AT the plan read ≈none, and the verdict agrees", () => {
  // A hand close past -1R is a breach, but it is not slippage: the stop exits
  // themselves average -1.02R, inside the 0.05R noise band.
  const { grid, verdict } = xqctx.run([xc("stop", -1.0), xc("stop", -1.02), xc("stop", -1.03),
    xc("manual", -1.3), xc("target", 2)]);
  assert.ok(/Stop slippage<\/span><span class="jr-dg-val ">≈none/.test(grid), grid);
  assert.ok(/Stop exits average -1\.02R over 3 — at the plan\./.test(verdict), verdict);
  assert.ok(!/past plan/.test(verdict), "the verdict contradicts the ≈none cell");
});

test("no stop exit yet says so instead of inventing a slippage figure", () => {
  const { grid } = xqctx.run([xc("manual", -0.3), xc("manual", -0.2), xc("time", -0.1), xc("target", 1.5)]);
  assert.ok(/no stop exits yet/.test(grid), grid);
});

test("the R-distribution caption never approves a book that loses money on average", () => {
  // counts: <=-2, -2..-1, -1..0, 0..1, 1..2, 2..3, >3
  const counts = [0, 19, 49, 37, 3, 2, 1];
  const neg = xqctx.rdistNote(counts, 111, { avg: -0.13, handInside: 40 });
  assert.ok(!/built to produce/.test(neg), `a -0.13R book was told it has the intended shape: ${neg}`);
  assert.ok(/19 closed at or past −1R and 49 between −1R and 0 \(40 of them closed by hand\)/.test(neg), neg);
  assert.ok(/-0\.13R a trade on average/.test(neg), neg);
  assert.ok(!/68 losses at the stop/.test(neg));
  const pos = xqctx.rdistNote(counts, 111, { avg: 0.21, handInside: 0 });
  assert.ok(/built to produce/.test(pos), "a positive book keeps the approving sentence");
  assert.ok(/\+0\.21R a trade on average/.test(pos), pos);
  const unknown = xqctx.rdistNote(counts, 111);
  assert.ok(!/built to produce/.test(unknown), "no average, no approval");
});

test("renderRDist hands the caption the average and the hand closes inside -1R", () => {
  assert.ok(/rdistNote\(counts, closed\.length, \{ avg, handInside \}\)/.test(CODE),
    "the caption no longer sees the average it must branch on");
});


// ── loadBotRules sets the off-scale gate (owner, 2026-09-27) ─────────────────
// The flag must follow the PUBLISHED key, not the drift loop: that loop only
// writes when live and fallback DIFFER, and from 2026-09-27 they agree (2500),
// so a flag set inside it would never switch on and the $5,000 closes would
// sit unmarked beside the $2,500 book. Async, so it runs last.
async function atest(name, fn) {
  try { await fn(); console.log(`  ✓  ${name}`); passed++; }
  catch (e) {
    const loc = (e.stack || "").split("\n").slice(1).find((l) => l.includes("journal_money.test.js"));
    console.error(`  ✗  ${name}\n     ${e.message}${loc ? "\n     " + loc.trim() : ""}`);
    failed++;
  }
}
const rctx = vm.createContext({ console: { warn() {}, log() {}, error() {} } });
vm.runInContext(
  "let EQUITY = 150000, POSITION_NOTIONAL = 2500, RISK_PCT = 0.35, NOTIONAL_LIVE = false, RULES_GEN = 1;\n"
  + "let LIVE_CYCLE = 'hc4-1', ENTRY_CELLS = [['1W', 'reclaim']];\n"
  + "const SCALE = { long: [0.25, 0.50, 0.15], short: [0.50, 0.25, 0.15] };\n"
  + "const LEVERAGE = { asx: 5, nasdaq: 5, crypto: 3 };\n"
  + "const COMMISSION_BPS = { asx: 2, nasdaq: 1, crypto: 6, default: 2 };\n"
  + "const SLIPPAGE_BPS   = { asx: 5, nasdaq: 4, crypto: 8, default: 5 };\n"
  + "let RULES = {};\n"
  + "const fetch = async () => ({ ok: true, json: async () => RULES });\n"
  + slice("const sharedRead = (kind, fresh) =>", "\n  };") + "\n"
  + slice("const cellsOf = (ec) =>", "\n  };") + "\n"
  + slice("async function loadBotRules(fresh) {", "\n  }") + "\n"
  + "this.load = async (rules) => { RULES = rules; NOTIONAL_LIVE = false; POSITION_NOTIONAL = 2500;"
  + " await loadBotRules(); return { live: NOTIONAL_LIVE, notional: POSITION_NOTIONAL,"
  + " cycle: LIVE_CYCLE, cells: JSON.stringify(ENTRY_CELLS) }; };",
  rctx);

(async () => {
  suite("loadBotRules — the off-scale gate");
  await atest("a published notional EQUAL to the fallback still switches the gate on", async () => {
    const r = await rctx.load({ position_notional: 2500 });
    assert.equal(r.live, true, "live === fallback must still count as published");
    assert.equal(r.notional, 2500);
  });
  await atest("a published notional that differs is adopted AND switches the gate on", async () => {
    const r = await rctx.load({ position_notional: 5000 });
    assert.deepEqual([r.live, r.notional], [true, 5000]);
  });
  await atest("no published notional (a pre-2026-07-28 file, the e2e fixture) leaves it off", async () => {
    const r = await rctx.load({ max_open_total: 30 });
    assert.deepEqual([r.live, r.notional], [false, 2500]);
    const s = await rctx.load({ position_notional: "2500" });
    assert.equal(s.live, false, "only a NUMBER is a published notional");
  });
  await atest("the published cycle_tag and entry_cells are adopted (REFINE200 #37/#125)", async () => {
    const r = await rctx.load({ cycle_tag: "hc5-1", entry_cells: { "3D": ["reclaim"], "1D": ["break"] } });
    assert.equal(r.cycle, "hc5-1");
    assert.equal(r.cells, JSON.stringify([["3D", "reclaim"], ["1D", "break"]]));
    const k = await rctx.load({ cycle_tag: "  ", entry_cells: "nope" });
    assert.equal(k.cycle, "hc5-1", "a blank tag must not replace a good one");
    assert.equal(k.cells, JSON.stringify([["3D", "reclaim"], ["1D", "break"]]), "a malformed table keeps the last good one");
  });

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();

