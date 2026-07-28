/* Unbounded growth and unbounded retry (TOP100 #80, #81, #82, #83).
 *
 * Four leaks that share one shape: something accumulates with nothing on the
 * other end of it. None of them announce themselves — a leaked interval, a
 * duplicated tick subscriber and a tombstone list that only grows all look
 * exactly like a working page right up until they don't.
 *
 *   #80  Repeating timers with no `document.hidden` guard, and — the half that
 *        actually leaks — timers/listeners wired per RENDER on a page whose
 *        render() is re-entrant. Every timeframe button is a call site, so a
 *        chart left open through ten clicks was running ten copies of the same
 *        interval painting into nine detached nodes.
 *
 *   #81  `onLiveTick` pushed a handler into a module-level array that nothing
 *        ever removed, so one price tick fanned out to N copies of the same
 *        handler. The teardown registry is the fix and it is registered INSIDE
 *        the helper, so a caller added later inherits it for free.
 *
 *   #82  The WebSocket reconnect waited a flat 3 s for ever. A feed that is
 *        down (or a laptop asleep for the weekend) hammered it 1,200 times an
 *        hour, per open tab, in lockstep across every tab on the network.
 *
 *   #83  `deleted` — the tombstone list — was append-only and round-tripped
 *        through localStorage AND the KV store on every sync, so it grew for
 *        the life of the journal across every device. The end of that road is a
 *        QuotaExceeded on `saveLocal`, i.e. the trade you just typed not
 *        persisting. In the same file, `_putBudgetOk()` incremented the daily
 *        cloud-write counter BEFORE the PUT was attempted, so a phone editing
 *        trades in a tunnel spent the whole day's budget on fetches that threw
 *        and came back online unable to sync at all.
 *
 * The rules live in the shipped files as named constants and named helpers,
 * precisely so this suite can pull them out and test the BEHAVIOUR rather than
 * grep for a `setTimeout` and hope the number in it means what it says.
 */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");

const P = (f) => path.join(__dirname, "..", "public", "js", f);

// EVERY structural assertion below runs against COMMENT-STRIPPED source, and
// that is not tidiness — it is the difference between a wiring test and a
// decoration. `grep`-shaped assertions have one systematic hole: commenting a
// line OUT leaves the text in the file, so `/if \(document\.hidden\) return;/`
// matches `// if (document.hidden) return;` just as happily. Mutation-testing
// this suite found exactly that: deleting the clock guard and deleting render's
// teardown call BOTH stayed green, because the mutation a human actually makes
// is to comment the line out rather than to retype the file without it. Two of
// the four items in this suite were protected by nothing.
//
// Line-oriented on purpose: it drops lines that are ENTIRELY a comment and
// leaves trailing `// ...` alone, so no expression is ever truncated mid-line.
// A JS line can never legitimately begin with `*` or `/*`, so block comments
// fall out too without parsing anything.
const codeOnly = (src) =>
  src.split("\n").filter((l) => {
    const t = l.trim();
    return !(t.startsWith("//") || t.startsWith("/*") || t.startsWith("*"));
  }).join("\n");

// The RAW bytes are kept for exactly one job: `(0, eval)(SYNC_RAW)` further
// down must run the file as shipped, not a version this test file edited.
const SYNC_RAW = fs.readFileSync(P("gbs-sync.js"), "utf8");
const CHART = codeOnly(fs.readFileSync(P("chart.js"), "utf8"));
const APP = codeOnly(fs.readFileSync(P("app.js"), "utf8"));
const SYNC_SRC = codeOnly(SYNC_RAW);

// Same extraction approach as test/escaping.test.js and test/staleview.test.js:
// walk the candidate `;` terminators and let the JS parser say which one closes
// the expression. A hand-rolled brace balancer desyncs on the first regex
// literal it meets; the parser cannot.
function extractConst(src, name) {
  const at = src.search(new RegExp(`\\bconst\\s+${name}\\s*=`));
  if (at < 0) return null;
  const start = src.indexOf("=", at) + 1;
  for (let i = src.indexOf(";", start); i > 0 && i - start < 4000; i = src.indexOf(";", i + 1)) {
    const candidate = src.slice(start, i).trim();
    try { new Function(`return (${candidate});`); return candidate; } catch (_) { /* keep walking */ }
  }
  return null;
}
function pullFrom(src, name, label) {
  const expr = extractConst(src, name);
  assert.ok(expr, `${label} no longer defines ${name}`);
  return eval(`(${expr})`); // eslint-disable-line no-eval
}

let passed = 0;
const test = (name, fn) => {
  try { fn(); passed++; console.log("PASS  " + name); }
  catch (e) { console.error("FAIL  " + name + "\n      " + e.message); process.exitCode = 1; }
};
// The gbs-sync half is all promises. Registered here, run at the bottom, so the
// output stays in a fixed order rather than interleaving with the sync tests.
const deferred = [];
const atest = (name, fn) => { deferred.push([name, fn]); };

// ===========================================================================
// #82 — the reconnect backs off, and the cap is a cap.
//
// The three constants are declared here under their REAL names on purpose: the
// two helpers below are eval'd out of the shipped file and close over this
// scope, so they resolve `WS_BACKOFF_MAX_MS` etc. through the scope chain. Move
// or rename one in chart.js and this suite fails at load rather than testing a
// stale copy of the numbers.
// ===========================================================================
const WS_BACKOFF_BASE_MS = pullFrom(CHART, "WS_BACKOFF_BASE_MS", "chart.js");
const WS_BACKOFF_MAX_MS = pullFrom(CHART, "WS_BACKOFF_MAX_MS", "chart.js");
const WS_STABLE_MS = pullFrom(CHART, "WS_STABLE_MS", "chart.js");
const wsBackoffMs = pullFrom(CHART, "wsBackoffMs", "chart.js");
const wsNextFails = pullFrom(CHART, "wsNextFails", "chart.js");

const ceilFor = (fails) => Math.min(WS_BACKOFF_MAX_MS, WS_BACKOFF_BASE_MS * Math.pow(2, fails));

test("the constants are ordered sanely — base below cap, cap above base", () => {
  assert.ok(WS_BACKOFF_BASE_MS > 0, "base must be positive");
  assert.ok(WS_BACKOFF_MAX_MS > WS_BACKOFF_BASE_MS,
    "a cap at or below the base is not a backoff, it is a fixed wait wearing one");
  assert.ok(WS_STABLE_MS > 0, "stable-uptime threshold must be positive");
});

test("the first retry lands in [base/2, base] — the old fixed wait is the CEILING", () => {
  // Equal jitter: the delay is drawn from [ceil/2, ceil]. The old behaviour
  // (a flat 3 s) is now the worst case of the FIRST retry, not of every retry.
  assert.strictEqual(wsBackoffMs(0, 0), WS_BACKOFF_BASE_MS / 2);
  assert.strictEqual(wsBackoffMs(0, 1), WS_BACKOFF_BASE_MS);
  assert.strictEqual(wsBackoffMs(0, 0.5), Math.round(WS_BACKOFF_BASE_MS * 0.75));
});

test("the ceiling doubles per consecutive failure until it saturates", () => {
  let sawCap = false;
  for (let f = 0; f < 20; f++) {
    const top = wsBackoffMs(f, 1);
    assert.strictEqual(top, Math.round(ceilFor(f)), `fails=${f}`);
    if (top === WS_BACKOFF_MAX_MS) sawCap = true;
  }
  assert.ok(sawCap, "20 consecutive failures must reach the cap, or the cap is unreachable");
});

test("the delay NEVER exceeds the cap, for any failure count and any jitter", () => {
  // The whole point of a cap is that it is one. A ±25% scheme around the
  // ceiling would overshoot it; equal jitter cannot.
  for (let f = -5; f <= 60; f++) {
    for (const r of [0, 0.001, 0.5, 0.999, 1, 1.5, 42, -1, -Infinity, Infinity, NaN, undefined, null, "x"]) {
      const v = wsBackoffMs(f, r);
      assert.ok(Number.isFinite(v), `fails=${f} rnd=${String(r)} gave a non-finite delay: ${v}`);
      assert.ok(v <= WS_BACKOFF_MAX_MS, `fails=${f} rnd=${String(r)} exceeded the cap: ${v}`);
    }
  }
});

test("THE NaN TRAP: a non-numeric jitter must not produce an IMMEDIATE retry", () => {
  // `Math.min(1, Math.max(0, rnd))` looks like a clamp and is not a total one —
  // it returns NaN for a NaN input, the delay comes back NaN, and
  // `setTimeout(fn, NaN)` fires immediately. That is a reconnect storm wearing
  // a backoff's clothes: the exact failure the function exists to prevent,
  // reached through the argument nobody checks. Unreachable from the single
  // live call site (`Math.random()`), which is why it has to be a test — the
  // next call site is the one that would find it in production.
  const floor = WS_BACKOFF_BASE_MS / 2;
  for (const r of [NaN, undefined, null, "x", {}, -1, -0.5]) {
    const v = wsBackoffMs(0, r);
    assert.ok(v >= floor, `rnd=${String(r)} gave ${v}, under the ${floor}ms floor`);
  }
});

test("a negative or fractional failure count clamps to the first step, never below it", () => {
  // `retry()` calls `wsBackoffMs(wsFails - 1, ...)`, so a counter that somehow
  // reads 0 arrives here as -1. It must not produce a shorter wait than the
  // first retry, and it must not produce a NEGATIVE one.
  for (const f of [-1, -10, -0.5, 0.9]) {
    assert.ok(wsBackoffMs(f, 1) <= WS_BACKOFF_BASE_MS, `fails=${f} exceeded the first step`);
    assert.ok(wsBackoffMs(f, 0) >= WS_BACKOFF_BASE_MS / 2, `fails=${f} fell under the floor`);
  }
});

test("jitter is monotone in rnd — more randomness, never less delay", () => {
  let prev = -1;
  for (let r = 0; r <= 1.00001; r += 0.05) {
    const v = wsBackoffMs(3, Math.min(1, r));
    assert.ok(v >= prev, `rnd=${r} went backwards`);
    prev = v;
  }
});

test("a STABLE connection resets the counter; anything shorter does not", () => {
  for (const f of [0, 1, 7, 40]) {
    assert.strictEqual(wsNextFails(f, WS_STABLE_MS), 0, `exactly stable, fails=${f}`);
    assert.strictEqual(wsNextFails(f, WS_STABLE_MS + 1), 0, `beyond stable, fails=${f}`);
    assert.strictEqual(wsNextFails(f, WS_STABLE_MS - 1), f + 1, `one ms short, fails=${f}`);
    assert.strictEqual(wsNextFails(f, 0), f + 1, `failed handshake, fails=${f}`);
  }
});

test("an unmeasurable uptime counts as a FAILURE, not as stability", () => {
  // Fail-safe direction: NaN fails the `>=` and increments. Backing off too
  // much on a healthy feed costs one extra reconnect; backing off too little on
  // a dead one is the storm.
  for (const up of [NaN, undefined, null, -1, "x"]) {
    assert.strictEqual(wsNextFails(2, up), 3, `upMs=${String(up)}`);
  }
});

test("THE REASONING TEST: accept-then-hang-up ten times must climb, not sit flat", () => {
  // The classic wrong version of this fix resets the counter in `onopen`. A
  // server that accepts the handshake and immediately closes would then zero it
  // on every single cycle and put the 3-second storm straight back — with a
  // backoff in the file to prove it had been fixed. The reset is on a stable
  // CLOSE for exactly this reason.
  let fails = 0;
  const waits = [];
  for (let i = 0; i < 10; i++) {
    fails = wsNextFails(fails, 0);                 // opened, then closed instantly
    waits.push(wsBackoffMs(fails - 1, 1));
  }
  assert.strictEqual(fails, 10, "ten instant hang-ups must count as ten failures");
  assert.ok(waits[9] > waits[0], "the wait must grow across the ten cycles");
  assert.strictEqual(waits[9], WS_BACKOFF_MAX_MS, "and must have reached the cap by ten");
  // The number that matters in aggregate: an hour of a dead feed.
  const flat = 3600000 / WS_BACKOFF_BASE_MS;                    // old behaviour, ~1200 tries
  const backedOff = 3600000 / (WS_BACKOFF_MAX_MS / 2 + WS_BACKOFF_MAX_MS) * 2;  // rough, at the cap
  assert.ok(backedOff * 5 < flat, "the backoff must cut a dead feed's retry rate by an order of magnitude");
});

test("one genuinely stable session wipes the whole penalty, immediately", () => {
  // Backoff must not punish a feed that recovers. Ten failures then one good
  // connection returns to the first step, not to a decayed halfway house.
  let fails = 0;
  for (let i = 0; i < 10; i++) fails = wsNextFails(fails, 0);
  fails = wsNextFails(fails, WS_STABLE_MS + 5000);
  assert.strictEqual(fails, 0);
  assert.strictEqual(wsBackoffMs(fails - 1, 1), WS_BACKOFF_BASE_MS);
});

// The wiring: the helpers exist AND the reconnect path goes through them.
test("the reconnect loop calls both helpers and keeps no flat wait", () => {
  assert.ok(/const\s+wait\s*=\s*wsBackoffMs\(\s*wsFails\s*-\s*1\s*,\s*Math\.random\(\)\s*\)/.test(CHART),
    "retry() must compute its wait from wsBackoffMs with real jitter");
  assert.ok(/wsFails\s*=\s*wsNextFails\(\s*wsFails\s*,\s*0\s*\)/.test(CHART),
    "a constructor throw must count as a failure");
  assert.ok(/wsFails\s*=\s*wsNextFails\(\s*wsFails\s*,\s*upAt\s*\?/.test(CHART),
    "onclose must feed the measured uptime to wsNextFails");
  assert.ok(!/wsFails\s*=\s*0/.test(CHART.slice(CHART.indexOf("sock.onopen"), CHART.indexOf("sock.onmessage"))),
    "onopen must NOT reset the failure counter — that is the storm in disguise");
  const retryFn = CHART.slice(CHART.indexOf("function retry(gen)"), CHART.indexOf("function connect()"));
  assert.ok(/clearTimeout\(wsTimer\)/.test(retryFn),
    "retry() must clear the previous timer or two retries can be armed at once");
});

// ===========================================================================
// #80 / #81 — nothing survives a re-render that the re-render did not re-wire.
// ===========================================================================
test("tearDownPreviousRender is the FIRST thing render() does", () => {
  const head = CHART.slice(CHART.indexOf("function render(d) {") + "function render(d) {".length,
    CHART.indexOf("tearDownPreviousRender();"));
  const code = head.split("\n").map((l) => l.trim()).filter((l) => l && !l.startsWith("//")).join("");
  assert.strictEqual(code, "",
    `render() executes something before tearing down the previous pass: ${JSON.stringify(code.slice(0, 120))}`);
});

test("the teardown registry pops as it goes, LIFO, and survives a thrower", () => {
  const reg = CHART.slice(CHART.indexOf("function tearDownPreviousRender()"),
    CHART.indexOf("const params = new URLSearchParams"));
  assert.ok(/while\s*\(_renderTeardown\.length\)/.test(reg),
    "must drain the list, not iterate a snapshot of it");
  assert.ok(/_renderTeardown\.pop\(\)\(\)/.test(reg),
    "must pop BEFORE calling, or a thrower is retried by the next render");
  assert.ok(/try\s*\{[^}]*pop\(\)\(\)[^}]*\}\s*catch/.test(reg),
    "one teardown that throws must not strand the ones queued behind it");
  // Behaviour, not just shape: run the real thing over a stub registry.
  const order = [];
  const _renderTeardown = [
    () => order.push("a"),
    () => { order.push("boom"); throw new Error("x"); },
    () => order.push("c"),
  ];
  const drain = new Function("_renderTeardown", reg.slice(0, reg.lastIndexOf("}") + 1) + "\nreturn tearDownPreviousRender();");
  drain(_renderTeardown);
  assert.deepStrictEqual(order, ["c", "boom", "a"], "LIFO, and the thrower must not stop the rest");
  assert.strictEqual(_renderTeardown.length, 0, "the list must be empty afterwards");
});

test("onLiveTick registers its OWN unsubscribe — no call site has to remember", () => {
  const fn = CHART.slice(CHART.indexOf("const onLiveTick = (fn) => {"), CHART.indexOf("const posId ="));
  assert.ok(/onRenderTeardown\(/.test(fn), "the subscription must register its own teardown");
  assert.ok(/listeners\.splice\(i, 1\)/.test(fn), "and the teardown must actually remove the handler");
  assert.ok(/indexOf\(fn\)/.test(fn), "removal must target THIS handler, not clear the whole list");
});

test("nothing subscribes to live ticks except through onLiveTick", () => {
  // The helper only protects the call sites that use it. One direct push and
  // that handler is back to living for ever.
  const pushes = (CHART.match(/liveState\.listeners\.push\(/g) || []).length;
  assert.strictEqual(pushes, 1,
    `${pushes} pushes into liveState.listeners — exactly one (inside onLiveTick) may exist`);
});

test("every per-render timer and window listener is registered for teardown", () => {
  const regs = (CHART.match(/onRenderTeardown\(/g) || []).length;
  assert.ok(regs >= 5,
    `only ${regs} teardown registrations — the live interval, the socket, the drag sweep, the ` +
    `duration timer and the tick unsubscribe are the floor, not the target`);
  // The drag helper is the one that leaks onto WINDOW, which outlives the box.
  assert.ok(/window\.addEventListener\("resize", restore\)/.test(CHART));
  assert.ok(/window\.removeEventListener\("resize", restore\)/.test(CHART),
    "the per-box resize handler must be removed, or every timeframe click adds one");
});

test("no beforeunload listener survives anywhere in public/js", () => {
  // They were doing nothing useful (page teardown clears intervals anyway) and
  // were worse than inert: a beforeunload listener disqualifies the page from
  // the bfcache, so it cost back-navigation performance to achieve nothing.
  const dir = path.join(__dirname, "..", "public", "js");
  const offenders = fs.readdirSync(dir).filter((f) => f.endsWith(".js")).filter((f) =>
    /addEventListener\(\s*["']beforeunload/.test(fs.readFileSync(path.join(dir, f), "utf8")) ||
    /onbeforeunload\s*=/.test(fs.readFileSync(path.join(dir, f), "utf8")));
  assert.deepStrictEqual(offenders, [], `beforeunload is back in: ${offenders.join(", ")}`);
});

test("the clock interval is guarded AND catches up — one without the other is worse", () => {
  const fn = APP.slice(APP.indexOf("function updateClocks()"), APP.indexOf("setInterval(updateClocks"));
  assert.ok(/if\s*\(document\.hidden\)\s*return;/.test(fn),
    "updateClocks must return early on a hidden tab");
  const body = fn.slice(fn.indexOf("if (document.hidden) return;"));
  assert.ok(/const now = new Date\(\)/.test(body),
    "the guard must sit ABOVE the work, not below it");
  assert.ok(/setInterval\(updateClocks, 1000\)/.test(APP),
    "the guard must not have been 'fixed' by deleting the timer");
  assert.ok(/visibilitychange[\s\S]{0,160}updateClocks\(\)/.test(APP),
    "without a catch-up on return, the guard leaves a clock showing when you LEFT");
});

// ===========================================================================
// #83 — the tombstone ceiling and the cloud-write budget.
//
// Runs the REAL gbs-sync.js against a Map-backed localStorage and a stubbed
// fetch, rather than a re-typed copy of it. A mirrored fixture drifts in step
// with the bug it is supposed to catch.
// ===========================================================================
function makeStorage() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)); },
    removeItem: (k) => { m.delete(k); },
    clear: () => m.clear(),
  };
}

const TOMBSTONE_MAX = pullFrom(SYNC_SRC, "TOMBSTONE_MAX", "gbs-sync.js");
const PUT_BUDGET = pullFrom(SYNC_SRC, "PUT_BUDGET", "gbs-sync.js");
const BUDGET_KEY = pullFrom(SYNC_SRC, "BUDGET_KEY", "gbs-sync.js");
const KEY = pullFrom(SYNC_SRC, "KEY", "gbs-sync.js");
const CODE_KEY = pullFrom(SYNC_SRC, "CODE_KEY", "gbs-sync.js");

globalThis.window = globalThis;
globalThis.localStorage = makeStorage();
let fetchCount = 0;
let fetchImpl = async () => ({ ok: true, json: async () => ({ configured: true }) });
globalThis.fetch = (...a) => { fetchCount++; return fetchImpl(...a); };
// Indirect eval so the IIFE runs in global scope and its `window.GBSSync = {...}`
// lands somewhere this module can reach.
(0, eval)(SYNC_RAW); // eslint-disable-line no-eval
const Sync = globalThis.GBSSync;

const ids = (n, pre = "t") => Array.from({ length: n }, (_, i) => `${pre}${i}`);
const reset = () => {
  globalThis.localStorage.clear();
  fetchCount = 0;
  fetchImpl = async () => ({ ok: true, json: async () => ({ configured: true }) });
};

test("gbs-sync.js loaded and still exports the surface the pages use", () => {
  assert.ok(Sync, "window.GBSSync missing — the IIFE did not run");
  for (const k of ["load", "saveLocal", "normalize", "merge", "getCode", "setCode", "pull", "put",
    "syncIn", "syncOut", "syncOutDebounced", "enabled"]) {
    assert.strictEqual(typeof Sync[k], "function", `GBSSync.${k} is missing`);
  }
});

test("the tombstone cap is far above any plausible journal, and finite", () => {
  // The manual journal tops out at 30 open positions. A cap anywhere near that
  // would be a working limit people hit; a cap that is absent is the leak.
  assert.ok(Number.isFinite(TOMBSTONE_MAX) && TOMBSTONE_MAX > 100,
    `TOMBSTONE_MAX=${TOMBSTONE_MAX} — this is a backstop, not a working limit`);
});

test("a list under the cap is returned untouched, in order", () => {
  const d = Sync.normalize({ deleted: ids(TOMBSTONE_MAX - 1) });
  assert.deepStrictEqual(d.deleted, ids(TOMBSTONE_MAX - 1));
});

test("the cap boundary is exclusive — exactly at the cap is not trimmed", () => {
  const at = Sync.normalize({ deleted: ids(TOMBSTONE_MAX) });
  assert.strictEqual(at.deleted.length, TOMBSTONE_MAX);
  const over = Sync.normalize({ deleted: ids(TOMBSTONE_MAX + 1) });
  assert.strictEqual(over.deleted.length, TOMBSTONE_MAX);
});

test("trimming keeps the NEWEST ids and drops from the front", () => {
  const all = ids(TOMBSTONE_MAX * 3);
  const d = Sync.normalize({ deleted: all });
  assert.deepStrictEqual(d.deleted, all.slice(-TOMBSTONE_MAX),
    "an old tombstone has had the longest time to reach every device — it is the safe one to lose");
});

test("normalize is idempotent — a second pass must not trim again", () => {
  // It runs on EVERY read and EVERY write. A pass that shortened the list each
  // time would erode a healthy journal's tombstones down to nothing.
  let d = Sync.normalize({ deleted: ids(TOMBSTONE_MAX + 250) });
  const first = d.deleted.slice();
  for (let i = 0; i < 5; i++) d = Sync.normalize(d);
  assert.deepStrictEqual(d.deleted, first);
});

test("every element stays a BARE STRING — the schema older clients still read", () => {
  // A device mid-flight on the previous build runs `deleted.includes(id)` and
  // `new Set([...a.deleted])` against this array. That ruled out the obvious
  // {id, ts} schema that would have made the trim exactly chronological.
  const d = Sync.normalize({ deleted: ids(TOMBSTONE_MAX + 10) });
  assert.ok(d.deleted.every((x) => typeof x === "string"), "a tombstone stopped being a plain id");
  assert.ok(d.deleted.includes(`t${TOMBSTONE_MAX + 9}`), "includes() must still find a live tombstone");
});

test("a non-array deleted field is replaced, not trimmed into nonsense", () => {
  for (const bad of [null, undefined, 0, "abc", {}]) {
    assert.deepStrictEqual(Sync.normalize({ deleted: bad }).deleted, [], `deleted=${String(bad)}`);
  }
});

test("the cap applies through load(), so an oversized stored journal self-heals", () => {
  // No migration step anywhere: normalize() is the one function every read and
  // write path goes through, so a journal already over the cap is trimmed on
  // its next load.
  reset();
  globalThis.localStorage.setItem(KEY, JSON.stringify({ trades: [], deleted: ids(TOMBSTONE_MAX + 900) }));
  assert.strictEqual(Sync.load().deleted.length, TOMBSTONE_MAX);
});

test("the cap applies through saveLocal(), so it cannot grow back on disk", () => {
  reset();
  Sync.saveLocal({ trades: [], deleted: ids(TOMBSTONE_MAX + 400) });
  const stored = JSON.parse(globalThis.localStorage.getItem(KEY));
  assert.strictEqual(stored.deleted.length, TOMBSTONE_MAX);
});

test("the cap applies to merge() output — the path that actually unions them", () => {
  const a = { trades: [], deleted: ids(TOMBSTONE_MAX, "a") };
  const b = { trades: [], deleted: ids(TOMBSTONE_MAX, "b") };
  const m = Sync.merge(a, b);
  assert.strictEqual(m.deleted.length, TOMBSTONE_MAX,
    "two capped journals must not merge into a double-length one");
});

test("a live tombstone still suppresses its trade through a merge", () => {
  const a = { trades: [], deleted: ["gone"] };
  const b = { trades: [{ id: "gone", mtime: 9 }, { id: "kept", mtime: 9 }] };
  const m = Sync.merge(a, b);
  assert.deepStrictEqual(m.trades.map((t) => t.id), ["kept"]);
});

test("THE STATED TRADE-OFF: a trimmed tombstone can resurrect ONE trade", () => {
  // Named rather than hidden. A device offline across more than TOMBSTONE_MAX
  // deletions can re-introduce a deleted trade on its next merge. That is
  // strictly better than the failure it replaces — the whole journal failing to
  // save — and unlike that one it is visible and recoverable, by deleting the
  // row again. If this test ever starts failing, the cap has been removed.
  const a = { trades: [], deleted: ["old-victim", ...ids(TOMBSTONE_MAX, "n")] };
  assert.ok(!Sync.normalize({ ...a }).deleted.includes("old-victim"),
    "the oldest tombstone is the one trimmed");
  const b = { trades: [{ id: "old-victim", mtime: 5 }] };
  assert.deepStrictEqual(Sync.merge(a, b).trades.map((t) => t.id), ["old-victim"]);
});

test("nothing else normalize() guarantees was disturbed by the trim", () => {
  const d = Sync.normalize({ deleted: ids(TOMBSTONE_MAX + 5) });
  assert.strictEqual(d.capital, 10000);
  assert.strictEqual(d.brokerage, 10);
  assert.strictEqual(d.crypto_brokerage, 5);
  assert.deepStrictEqual(d.trades, []);
  assert.deepStrictEqual(d.watchlists, {});
  assert.strictEqual(d.updated_at, 0);
});

// --- the daily cloud-write budget ------------------------------------------
const budget = () => {
  const raw = globalThis.localStorage.getItem(BUDGET_KEY);
  return raw ? JSON.parse(raw) : null;
};

atest("no sync code means no fetch and no spend", async () => {
  reset();
  const r = await Sync.put({ trades: [] });
  assert.strictEqual(r.ok, false);
  assert.strictEqual(fetchCount, 0);
  assert.strictEqual(budget(), null, "an unsent request must not touch the counter");
});

atest("an OK response spends exactly one slot", async () => {
  reset();
  Sync.setCode("abc");
  const r = await Sync.put({ trades: [] });
  assert.strictEqual(r.ok, true);
  assert.strictEqual(fetchCount, 1);
  assert.strictEqual(budget().n, 1, "one answered request, one slot");
  globalThis.localStorage.removeItem(CODE_KEY);
});

atest("a NON-OK response also spends, because the server may still have written", async () => {
  // functions/api/journal.js writes KV inside the request — the journal itself
  // plus the rate-limit counters that run before it — so a 429 or a 500 can
  // still have cost quota. A ceiling is only a ceiling if it counts
  // conservatively.
  reset();
  Sync.setCode("abc");
  fetchImpl = async () => ({ ok: false, json: async () => ({ configured: true }) });
  const r = await Sync.put({ trades: [] });
  assert.strictEqual(r.ok, false);
  assert.strictEqual(budget().n, 1, "a rejected write may still have moved the quota");
  globalThis.localStorage.removeItem(CODE_KEY);
});

atest("THE BUG: a request that never reached the server spends NOTHING", async () => {
  // The old `_putBudgetOk()` incremented and then the caller attempted the PUT,
  // so an offline device burned the whole day's budget on fetches that threw —
  // and came back onto the network with nothing left to sync with until UTC
  // midnight. The offline stretch consumed the quota it was meant to protect
  // and bought no writes at all.
  reset();
  Sync.setCode("abc");
  fetchImpl = async () => { throw new Error("offline"); };
  for (let i = 0; i < PUT_BUDGET + 50; i++) {
    const r = await Sync.put({ trades: [] });
    assert.strictEqual(r.ok, false);
  }
  assert.strictEqual(budget(), null, "a whole day in a tunnel must not spend a single slot");
  // ...and the moment the network returns, the budget is intact.
  fetchImpl = async () => ({ ok: true, json: async () => ({ configured: true }) });
  const back = await Sync.put({ trades: [] });
  assert.strictEqual(back.ok, true, "coming back online must be able to sync");
  assert.strictEqual(budget().n, 1);
  globalThis.localStorage.removeItem(CODE_KEY);
});

atest("an exhausted budget refuses WITHOUT calling fetch, and says why", async () => {
  reset();
  Sync.setCode("abc");
  const today = new Date().toISOString().slice(0, 10);
  globalThis.localStorage.setItem(BUDGET_KEY, JSON.stringify({ day: today, n: PUT_BUDGET }));
  const r = await Sync.put({ trades: [] });
  assert.deepStrictEqual(r, { ok: false, skipped: "budget" });
  assert.strictEqual(fetchCount, 0, "the whole point is not to make the request");
  assert.strictEqual(budget().n, PUT_BUDGET, "a refused request must not increment either");
  globalThis.localStorage.removeItem(CODE_KEY);
});

atest("the last slot is spendable — the check is `<`, not `<=`", async () => {
  reset();
  Sync.setCode("abc");
  const today = new Date().toISOString().slice(0, 10);
  globalThis.localStorage.setItem(BUDGET_KEY, JSON.stringify({ day: today, n: PUT_BUDGET - 1 }));
  const r = await Sync.put({ trades: [] });
  assert.strictEqual(r.ok, true);
  assert.strictEqual(budget().n, PUT_BUDGET);
  globalThis.localStorage.removeItem(CODE_KEY);
});

atest("yesterday's counter does not carry over", async () => {
  reset();
  Sync.setCode("abc");
  globalThis.localStorage.setItem(BUDGET_KEY, JSON.stringify({ day: "2000-01-01", n: 99999 }));
  const r = await Sync.put({ trades: [] });
  assert.strictEqual(r.ok, true, "a stale day must reset to zero used");
  const b = budget();
  assert.strictEqual(b.n, 1);
  assert.strictEqual(b.day, new Date().toISOString().slice(0, 10), "and re-stamp to today");
  globalThis.localStorage.removeItem(CODE_KEY);
});

atest("a corrupt counter reads as UNUSED, never as exhausted", async () => {
  // This budget guards a COST, not a correctness property. A device whose
  // storage is unreadable must still be able to sync; failing closed here would
  // silently un-sync it instead, which is the expensive failure.
  reset();
  Sync.setCode("abc");
  globalThis.localStorage.setItem(BUDGET_KEY, "{not json");
  const r = await Sync.put({ trades: [] });
  assert.strictEqual(r.ok, true);
  globalThis.localStorage.removeItem(CODE_KEY);
});

atest("the budget sits well inside the free KV tier it exists to protect", async () => {
  // Workers KV free tier is 1000 writes/day. The gap between PUT_BUDGET and
  // that ceiling is deliberate headroom: it absorbs the one case this design
  // undercounts (a connection dropped after the server had already written) and
  // the check-then-spend race between two tabs.
  assert.ok(PUT_BUDGET > 0 && PUT_BUDGET <= 600,
    `PUT_BUDGET=${PUT_BUDGET} leaves too little headroom under the 1000/day KV limit`);
});

atest("the whole journal still round-trips through a real syncOut", async () => {
  // End-to-end over the shipped module: local save, merge with a remote copy,
  // push. Proves the two edits did not break the path they live on.
  reset();
  Sync.setCode("abc");
  Sync.saveLocal({ trades: [{ id: "local", mtime: 2 }], deleted: ["x"] });
  let sent = null;
  fetchImpl = async (url, opt) => {
    if (opt && opt.method === "PUT") { sent = JSON.parse(opt.body); return { ok: true, json: async () => ({ configured: true }) }; }
    return { ok: true, json: async () => ({ configured: true, data: { trades: [{ id: "remote", mtime: 3 }], deleted: ["y"], updated_at: 5 } }) };
  };
  const merged = await Sync.syncOut();
  assert.deepStrictEqual(merged.trades.map((t) => t.id).sort(), ["local", "remote"]);
  assert.deepStrictEqual(merged.deleted.sort(), ["x", "y"]);
  assert.ok(sent, "the PUT never happened");
  assert.deepStrictEqual(sent.deleted.sort(), ["x", "y"], "the pushed copy must carry the merged tombstones");
  assert.strictEqual(budget().n, 1);
  globalThis.localStorage.removeItem(CODE_KEY);
});

// The wiring, source-side: the trim and the split must be where they claim.
test("the trim lives in normalize(), the one choke point every path uses", () => {
  const norm = SYNC_SRC.slice(SYNC_SRC.indexOf("function normalize(d)"), SYNC_SRC.indexOf("function load()"));
  assert.ok(/d\.deleted\.length\s*>\s*TOMBSTONE_MAX/.test(norm) && /slice\(-TOMBSTONE_MAX\)/.test(norm),
    "the cap must be applied inside normalize, or a path exists that bypasses it");
});

test("checking the budget and spending it are separate functions", () => {
  assert.ok(/function _putBudgetCheck\(\)/.test(SYNC_SRC), "the read-only check is missing");
  assert.ok(/function _putBudgetSpend\(\)/.test(SYNC_SRC), "the writer is missing");
  // `SYNC_SRC` is comment-stripped (see codeOnly at the top), which matters in
  // BOTH directions here. The shipped file explains the old helper BY NAME in
  // the block above `_putBudgetCheck`, and that prose is the reason the split
  // survives a future reader — asserted against raw source this would force the
  // explanation to be deleted to stay green.
  assert.ok(!/_putBudgetOk/.test(SYNC_SRC), "the old check-and-increment helper is back");
  const check = SYNC_SRC.slice(SYNC_SRC.indexOf("function _putBudgetCheck()"),
    SYNC_SRC.indexOf("function _putBudgetSpend()"));
  assert.ok(!/setItem/.test(check), "the check must never write — that is the entire fix");
  const put = SYNC_SRC.slice(SYNC_SRC.indexOf("async function put(d)"));
  const body = put.slice(0, put.indexOf("\n  }\n"));
  assert.ok(body.indexOf("await fetch") < body.indexOf("_putBudgetSpend()"),
    "the spend must come AFTER the server has answered, not before the attempt");
  assert.ok(body.indexOf("_putBudgetSpend()") < body.indexOf("} catch"),
    "a fetch that REJECTED must skip the spend entirely");
});

// ---------------------------------------------------------------------------
(async () => {
  for (const [name, fn] of deferred) {
    try { await fn(); passed++; console.log("PASS  " + name); }
    catch (e) { console.error("FAIL  " + name + "\n      " + e.message); process.exitCode = 1; }
  }
  console.log(process.exitCode ? "\nSOME LEAK TESTS FAILED" : `\nALL ${passed} leak tests passed`);
})();
