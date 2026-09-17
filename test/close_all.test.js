#!/usr/bin/env node
/* "Close all" tests for public/js/journal.js.

   Owner ask, 2026-09-17: "I want the ability to Close all trades i've taken and
   also all trades Claude has taken — i want a button for each."

   This is the most destructive control on the journal page: one click can close a
   whole book. So this file is mostly about what the two handlers REFUSE to do —
   the same emphasis as tests/test_resize_book_notional.py, for the same reason.

   It runs the REAL handlers, sliced out of the shipped file at load time rather
   than re-typed here (the house pattern from journal_review / journal_stale /
   journal_money). journal.js is one big IIFE with no export surface, so the whole
   CLOSE ALL block is lifted between two markers and executed against injected
   stubs. If someone renames the block's first or last symbol this file fails to
   load and says so, which is the alarm we want: a re-typed copy of a close path
   would drift silently, and a close path that silently sends the wrong body is
   exactly the 2026-08-07 "six closes went missing" failure.

   Run with: node test/close_all.test.js
*/
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");
const vm = require("vm");

/* Tests are QUEUED and run strictly in order. The first draft ran them
 * concurrently, which raced the summary line ahead of the async cases: it
 * printed a green count while three tests were still failing behind it. A
 * harness that can report green mid-run is worse than no harness. */
let passed = 0, failed = 0;
const QUEUE = [];
function test(name, fn) { QUEUE.push({ name, fn }); }
const suite = (name) => QUEUE.push({ suite: name });
async function runQueue() {
  for (const item of QUEUE) {
    if (item.suite) { console.log(`\n── ${item.suite} ──`); continue; }
    try { await item.fn(); console.log(`  ✓  ${item.name}`); passed++; }
    catch (e) { console.error(`  ✗  ${item.name}\n     ${e.message}`); failed++; }
  }
}

// ── lift the real CLOSE ALL block out of the shipped file ────────────────────
const SRC = fs.readFileSync(path.resolve(__dirname, "../public/js/journal.js"), "utf8");
function between(startMarker, endMarker) {
  const a = SRC.indexOf(startMarker);
  assert.ok(a >= 0, `journal.js no longer contains "${startMarker}" — renamed?`);
  const b = SRC.indexOf(endMarker, a);
  assert.ok(b > a, `could not find "${endMarker}" after "${startMarker}"`);
  return SRC.slice(a, b);
}
const BLOCK = between("const CLOSE_ALL_MAX =", "\n  function saveClose() {");

/* A fresh sandbox per test: every handler mutates module state (closeAllBusy)
 * and the stubs record calls, so sharing one would let tests leak into each
 * other in exactly the direction that hides a double-send. */
function load({ botOpen = [], meOpen = [], confirmAnswer = true, prices = {},
                fetchImpl, store } = {}) {
  const log = { alerts: [], confirms: [], posts: [], saved: [], painted: [] };
  const data = store || { trades: [] };
  const ctx = vm.createContext({
    console,
    JSON, Date, Number, String, Object, Array, Promise, isFinite, parseFloat,
    state: { bot: { open: botOpen, closed: [] }, me: { open: meOpen, closed: [] } },
    alert: (m) => log.alerts.push(String(m)),
    confirm: (m) => { log.confirms.push(String(m)); return confirmAnswer; },
    paintOpen: (side) => log.painted.push(side),
    mjLoad: () => data,
    mjSave: (d) => log.saved.push(d),
    loadMe: () => {}, renderAll: () => {}, refreshLive: () => {},
    today: () => "2026-09-17",
    nowTime: () => "10:30",
    priceFor: (t) => Promise.resolve(
      Object.prototype.hasOwnProperty.call(prices, t.symbol) ? prices[t.symbol] : null),
    fetch: fetchImpl || ((url, opts) => {
      log.posts.push({ url, body: JSON.parse(opts.body), method: opts.method });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
    }),
  });
  vm.runInContext(
    BLOCK + "\nthis.botMark = botMark; this.closeAllControl = closeAllControl;" +
    "\nthis.closeAllBot = closeAllBot; this.closeAllMine = closeAllMine;" +
    "\nthis.CLOSE_ALL_MAX = CLOSE_ALL_MAX;", ctx);
  return { ctx, log, data };
}

const botRow = (over) => Object.assign(
  { symbol: "FPH", market: "asx", direction: "long", last_mark: 33.5 }, over || {});
const meRow = (over) => Object.assign(
  { id: "m1", symbol: "BHP", market: "asx", direction: "long", status: "open" }, over || {});

// ═══════════════════════════ the price rule ═══════════════════════════════════
suite("botMark — fail-closed, no honest price means no close");

test("a finite positive mark is the close price", () => {
  assert.equal(load().ctx.botMark({ last_mark: 12.5 }), 12.5);
});

test("absent, zero, negative, NaN, Infinity and string marks all refuse", () => {
  const { ctx } = load();
  for (const v of [undefined, null, 0, -1, NaN, Infinity, "12.5", {}]) {
    assert.equal(ctx.botMark({ last_mark: v }), null, `last_mark ${String(v)} must refuse`);
  }
  assert.equal(ctx.botMark(null), null);
});

// ═══════════════════════════ the button ═══════════════════════════════════════
suite("closeAllControl — nothing to close, nothing to click");

test("an empty book renders NO button at all", () => {
  assert.equal(load().ctx.closeAllControl("bot", []), "");
});

test("the button states the exact count and carries its side", () => {
  const html = load().ctx.closeAllControl("bot", [botRow(), botRow()]);
  assert.ok(html.includes("Close all 2"), html);
  assert.ok(html.includes('data-closeall="bot"'), html);
  assert.ok(html.includes("jr-close-all"), html);
});

test("each side names whose positions it closes, so the two cannot be confused", () => {
  const { ctx } = load();
  assert.ok(/Claude's/.test(ctx.closeAllControl("bot", [botRow()])));
  assert.ok(/your/.test(ctx.closeAllControl("me", [meRow()])));
});

// ═══════════════════════════ Claude's side ════════════════════════════════════
suite("closeAllBot — the bot book is the real track record");

test("declining the confirm sends NOTHING", async () => {
  const { ctx, log } = load({ botOpen: [botRow()], confirmAnswer: false });
  await ctx.closeAllBot();
  assert.equal(log.posts.length, 0);
  assert.equal(log.confirms.length, 1);
});

test("the confirm names the exact count before anything is sent", async () => {
  const { ctx, log } = load({ botOpen: [botRow(), botRow({ symbol: "BHP" })], confirmAnswer: false });
  await ctx.closeAllBot();
  assert.match(log.confirms[0], /Close ALL 2 of Claude's open positions/);
});

test("it posts ONE batch to /api/close, journal_type bot, each at its own last_mark", async () => {
  const { ctx, log } = load({ botOpen: [
    botRow({ symbol: "FPH", last_mark: 33.5 }),
    botRow({ symbol: "MDB", market: "nasdaq", last_mark: 210.25 }),
  ] });
  await ctx.closeAllBot();
  assert.equal(log.posts.length, 1, "exactly one request, however many closes");
  const { url, method, body } = log.posts[0];
  assert.equal(url, "/api/close");
  assert.equal(method, "POST");
  assert.equal(body.journal_type, "bot");
  assert.deepEqual(body.closes, [
    { symbol: "FPH", market: "asx", direction: "long", price: 33.5 },
    { symbol: "MDB", market: "nasdaq", direction: "long", price: 210.25 },
  ]);
});

test("a row with no usable mark is SKIPPED, NAMED in the confirm, and left open", async () => {
  const { ctx, log } = load({ botOpen: [
    botRow({ symbol: "FPH", last_mark: 33.5 }),
    botRow({ symbol: "GHOST", last_mark: null }),
  ] });
  await ctx.closeAllBot();
  assert.match(log.confirms[0], /SKIPPED/);
  assert.match(log.confirms[0], /GHOST/);
  assert.deepEqual(log.posts[0].body.closes.map((c) => c.symbol), ["FPH"]);
});

test("when NOTHING is closable it says so and sends nothing", async () => {
  const { ctx, log } = load({ botOpen: [botRow({ last_mark: 0 })] });
  await ctx.closeAllBot();
  assert.equal(log.posts.length, 0);
  assert.equal(log.confirms.length, 0, "never ask about a close it cannot make");
  assert.match(log.alerts[0], /usable last mark/);
});

test("an empty book says Claude holds nothing, and sends nothing", async () => {
  const { ctx, log } = load({ botOpen: [] });
  await ctx.closeAllBot();
  assert.equal(log.posts.length, 0);
  assert.match(log.alerts[0], /no open positions/);
});

test("over the batch ceiling it REFUSES rather than truncating", async () => {
  // Silently sending the first 30 of 31 is the 2026-08-07 failure: closes that
  // nobody was told went missing. Refusing is loud and loses nothing.
  const many = Array.from({ length: 31 }, (_, i) => botRow({ symbol: "S" + i }));
  const { ctx, log } = load({ botOpen: many });
  await ctx.closeAllBot();
  assert.equal(log.posts.length, 0, "nothing may be sent");
  assert.equal(log.confirms.length, 0);
  assert.match(log.alerts[0], /31 closable positions is over the 30-per-run limit/);
  assert.match(log.alerts[0], /Nothing was sent/);
});

test("exactly the ceiling is allowed — a full 30-slot book closes in one run", async () => {
  const many = Array.from({ length: 30 }, (_, i) => botRow({ symbol: "S" + i }));
  const { ctx, log } = load({ botOpen: many });
  await ctx.closeAllBot();
  assert.equal(log.posts.length, 1);
  assert.equal(log.posts[0].body.closes.length, 30);
});

test("a rejected dispatch is reported as NOT queued and never claimed as closed", async () => {
  const { ctx, log } = load({
    botOpen: [botRow()],
    fetchImpl: () => Promise.resolve({ ok: false, json: () => Promise.resolve({ message: "token dead" }) }),
  });
  await ctx.closeAllBot();
  assert.match(log.alerts[0], /NOT queued/);
  assert.match(log.alerts[0], /token dead/);
});

test("a network failure is reported, not swallowed", async () => {
  const { ctx, log } = load({ botOpen: [botRow()], fetchImpl: () => Promise.reject(new Error("offline")) });
  await ctx.closeAllBot();
  assert.match(log.alerts[0], /NOT queued/);
});

test("success says QUEUED, not closed — a 202 is a dispatch, not a landed close", async () => {
  const { ctx, log } = load({ botOpen: [botRow()] });
  await ctx.closeAllBot();
  assert.match(log.alerts[0], /queued/i);
  assert.ok(!/\bclosed\b/.test(log.alerts[0]), log.alerts[0]);
});

// ═══════════════════════════ my side ══════════════════════════════════════════
suite("closeAllMine — the manual journal, closed at the live price");

test("declining the confirm writes nothing", async () => {
  const store = { trades: [meRow()] };
  const { ctx, log } = load({ meOpen: [meRow()], store, confirmAnswer: false, prices: { BHP: 40 } });
  await ctx.closeAllMine();
  assert.equal(log.saved.length, 0);
  assert.equal(store.trades[0].status, "open");
});

test("it writes exactly the fields a one-by-one close writes", async () => {
  const store = { trades: [meRow({ _init: { stale: true } })] };
  const { ctx, log } = load({ meOpen: [meRow()], store, prices: { BHP: 41.5 } });
  await ctx.closeAllMine();
  const t = store.trades[0];
  assert.equal(t.status, "closed");
  assert.equal(t.exit, 41.5);
  assert.equal(t.exit_date, "2026-09-17");
  assert.equal(t.exit_time, "10:30");
  assert.equal(t.exit_reason, "manual");
  assert.ok(typeof t.mtime === "number");
  assert.ok(!("_init" in t), "_init must be dropped so R re-resolves cleanly");
  assert.equal(log.saved.length, 1, "the store is written ONCE, not once per row");
});

test("a row with no live price is skipped, named, and left OPEN", async () => {
  const store = { trades: [meRow({ id: "m1", symbol: "BHP" }), meRow({ id: "m2", symbol: "NOPRICE" })] };
  const { ctx, log } = load({
    meOpen: [meRow({ id: "m1", symbol: "BHP" }), meRow({ id: "m2", symbol: "NOPRICE" })],
    store, prices: { BHP: 41.5 },
  });
  await ctx.closeAllMine();
  assert.equal(store.trades[0].status, "closed");
  assert.equal(store.trades[1].status, "open");
  assert.match(log.alerts[0], /NOPRICE/);
});

test("when no price comes back for anything, nothing is written", async () => {
  const store = { trades: [meRow()] };
  const { ctx, log } = load({ meOpen: [meRow()], store, prices: {} });
  await ctx.closeAllMine();
  assert.equal(log.saved.length, 0);
  assert.equal(store.trades[0].status, "open");
  assert.match(log.alerts[0], /Nothing was closed/);
});

test("a row closed under us is left alone rather than re-closed", async () => {
  // The store is the truth; state.me.open is a render snapshot that can lag.
  const store = { trades: [meRow({ status: "closed", exit: 99, exit_reason: "stop" })] };
  const { ctx } = load({ meOpen: [meRow()], store, prices: { BHP: 41.5 } });
  await ctx.closeAllMine();
  assert.equal(store.trades[0].exit, 99, "must not overwrite a close that already happened");
  assert.equal(store.trades[0].exit_reason, "stop");
});

test("an empty book says so and writes nothing", async () => {
  const { ctx, log } = load({ meOpen: [] });
  await ctx.closeAllMine();
  assert.equal(log.saved.length, 0);
  assert.match(log.alerts[0], /no open positions/);
});

// ═══════════════════════════ wiring ══════════════════════════════════════════
suite("wiring — the shipped page can actually reach these");

test("both hosts exist in journal.html, one per side", () => {
  const html = fs.readFileSync(path.resolve(__dirname, "../public/journal.html"), "utf8");
  assert.ok(html.includes('id="bot-close-all"'), "bot host missing");
  assert.ok(html.includes('id="me-close-all"'), "me host missing");
});

test("the delegated click handler routes both sides", () => {
  assert.match(SRC, /data-closeall/, "no delegated hook for the buttons");
  assert.match(SRC, /closeAllBot\(\)/);
  assert.match(SRC, /closeAllMine\(\)/);
});

test("paintOpen renders the control, so it survives every re-paint", () => {
  // The open table is re-rendered on a 3-minute timer; a button injected once
  // outside paintOpen would vanish on the next refresh.
  const paint = between("function paintOpen(side) {", "\n  // Per-section");
  assert.match(paint, /close-all/);
  assert.match(paint, /closeAllControl/);
});

test("the in-flight button is disabled, so a second click cannot race the first", () => {
  const paint = between("function paintOpen(side) {", "\n  // Per-section");
  assert.match(paint, /closeAllBusy/);
  assert.match(paint, /disabled/);
});

test("the CSS class the buttons use is actually styled", () => {
  const css = fs.readFileSync(path.resolve(__dirname, "../public/css/journal.css"), "utf8");
  assert.match(css, /\.jr-close-all\s*\{/);
  assert.match(css, /\.jr-close-all\[disabled\]/);
});

runQueue().then(() => {
  console.log(`\nclose_all.test.js: ${passed}/${passed + failed} passed`);
  if (failed) process.exit(1);
});
