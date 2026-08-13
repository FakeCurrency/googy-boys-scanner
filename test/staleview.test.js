/* Stale payloads and racing polls on the dashboard (TOP100 #78, #79).
 *
 * Two ways the deck could show you something untrue while looking entirely
 * normal — no "updating…" chip, no warning, the usual "updated at" stamp:
 *
 *   #78  `state.cache` is an in-MEMORY payload copy that lives as long as the
 *        tab does. The only thing that ever evicted it was the auto-refresh
 *        tick, and that only evicts the market you are LOOKING AT. Open on ASX,
 *        switch to NASDAQ, leave the tab up for the afternoon (the refresh
 *        clock dutifully keeping NASDAQ current), switch back to ASX — and the
 *        morning's payload repainted as live, because the in-memory hit
 *        returned before the fetch could run. The front-end twin of #24: the
 *        dashboard's own memory was the one cache with no age on it.
 *
 *   #79  `pollForFreshScan` re-read `state.market` on every tick but compared
 *        against the `oldGenAt` captured from the market you STARTED on.
 *        Switch market mid-poll and it fetched the new one, found a
 *        generated_at that differed from the old one's — they always differ —
 *        and announced "Scan complete", repainting and restarting the refresh
 *        clock for a scan that never ran there. Nothing cancelled it either, so
 *        two taps on reload left two pollers racing for five minutes.
 *
 * Both rules now live in app.js as named expressions rather than inline
 * conditions, precisely so this suite can pull them out, evaluate them and test
 * the BEHAVIOUR — not grep for a comparison and hope it means what it says.
 */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");

const APP = fs.readFileSync(path.join(__dirname, "..", "public", "js", "app.js"), "utf8");

// Same extraction approach as test/escaping.test.js: walk the candidate `;`
// terminators and let the JS parser say which one closes the expression.
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
function pull(name) {
  const expr = extractConst(APP, name);
  assert.ok(expr, `app.js no longer defines ${name}`);
  return eval(`(${expr})`); // eslint-disable-line no-eval
}

let passed = 0;
const test = (name, fn) => {
  try { fn(); passed++; console.log("PASS  " + name); }
  catch (e) { console.error("FAIL  " + name + "\n      " + e.message); process.exitCode = 1; }
};

const TTL = 5 * 60 * 1000;
const MIN = 60 * 1000;
const cacheIsFresh = pull("cacheIsFresh");
const pollMayApply = pull("pollMayApply");

// ---------------------------------------------------------------------------
// #78 — the in-memory copy has an age now, and "no idea" reads as stale.
// ---------------------------------------------------------------------------
test("a payload fetched just now is fresh", () => {
  const now = 1_000_000;
  assert.strictEqual(cacheIsFresh(now, now, TTL), true);
});

test("a payload inside the 5-minute TTL is fresh", () => {
  const now = 1_000_000;
  assert.strictEqual(cacheIsFresh(now - 4 * MIN, now, TTL), true);
});

test("the TTL boundary is exclusive — exactly 5 minutes old is stale", () => {
  const now = 1_000_000;
  assert.strictEqual(cacheIsFresh(now - TTL, now, TTL), false);
  assert.strictEqual(cacheIsFresh(now - TTL + 1, now, TTL), true);
});

test("THE BUG: the payload you left on screen this morning is stale", () => {
  // Switch away to NASDAQ, come back to ASX six hours later. This returning
  // false is what sends load() into the stale-paint-then-revalidate path
  // instead of repainting the morning's scan as the current one.
  const now = 1_000_000;
  assert.strictEqual(cacheIsFresh(now - 6 * 60 * MIN, now, TTL), false);
});

test("an unstamped entry is stale, never fresh", () => {
  // A cache entry with no recorded fetch time means "no idea how old this is".
  // The old code had no stamp at ALL, which is this case for every entry — and
  // it treated every one of them as current.
  const now = 1_000_000;
  for (const missing of [null, undefined]) {
    assert.strictEqual(cacheIsFresh(missing, now, TTL), false, `at=${missing}`);
  }
});

test("a non-finite stamp is stale, not fresh", () => {
  // `Date.now() - cacheAgeMs(key)` is -Infinity when the age is unknown, and
  // `-Infinity` would otherwise sail through a plain `now - at < ttl` test as
  // the freshest value imaginable. It is the exact opposite.
  const now = 1_000_000;
  assert.strictEqual(cacheIsFresh(-Infinity, now, TTL), false);
  assert.strictEqual(cacheIsFresh(Infinity, now, TTL), false);
  assert.strictEqual(cacheIsFresh(NaN, now, TTL), false);
});

test("a clock that steps backwards does not make a payload immortal", () => {
  // A future stamp yields a negative age, which IS < ttl — correctly fresh,
  // and self-correcting once the clock passes it again. What matters is that
  // it cannot outlive the TTL measured forward from the corrected time.
  const now = 1_000_000;
  assert.strictEqual(cacheIsFresh(now + MIN, now, TTL), true);
  assert.strictEqual(cacheIsFresh(now + MIN, now + 10 * MIN, TTL), false);
});

test("a zero stamp is honoured rather than mistaken for missing", () => {
  // Epoch 0 is a real (very old) time. `at != null` is the guard, not `!at` —
  // the difference is whether a falsy-but-valid stamp reads as absent.
  assert.strictEqual(cacheIsFresh(0, 1_000_000, TTL), false);
  assert.strictEqual(cacheIsFresh(0, TTL - 1, TTL), true);
});

// ---------------------------------------------------------------------------
// #79 — only the newest poller, and only for the view still on screen.
// ---------------------------------------------------------------------------
const ASX = "asx:vivek", NDX = "nasdaq:vivek";

test("the only poller, on the market it was launched against, may apply", () => {
  assert.strictEqual(pollMayApply(1, 1, ASX, ASX), true);
});

test("THE BUG: a poller must not announce on a market you switched to", () => {
  // Started on ASX, user is now on NASDAQ. The old code fetched NASDAQ,
  // compared its generated_at against the ASX baseline, and flashed
  // "Scan complete" for a scan that never ran on NASDAQ.
  assert.strictEqual(pollMayApply(1, 1, ASX, NDX), false);
});

test("a superseded poller stays silent even on the right market", () => {
  // Two taps on reload. Poller 1 must not paint or flash over poller 2.
  assert.strictEqual(pollMayApply(1, 2, ASX, ASX), false);
  assert.strictEqual(pollMayApply(2, 2, ASX, ASX), true);
});

test("superseded AND navigated away is still silent", () => {
  assert.strictEqual(pollMayApply(1, 3, ASX, NDX), false);
});

test("mode counts as part of the view, not just market", () => {
  // The key is `<market>:<mode>`, so a mode switch has to silence the poller
  // for the same reason a market switch does.
  assert.strictEqual(pollMayApply(1, 1, "asx:vivek", "asx:spec"), false);
});

test("the token comparison is identity, not truthiness", () => {
  // Token 0 is the pre-first-poll value; a truthiness test would let every
  // poller through before the counter had incremented.
  assert.strictEqual(pollMayApply(0, 0, ASX, ASX), true);
  assert.strictEqual(pollMayApply(0, 1, ASX, ASX), false);
});

// ---------------------------------------------------------------------------
// The wiring: the rules exist AND the call sites go through them. A helper
// nothing calls is a helper that protects nothing.
// ---------------------------------------------------------------------------
test("load() gates its in-memory cache hit on freshness", () => {
  assert.ok(/if\s*\(state\.cache\[key\]\s*&&\s*cacheIsFresh\(/.test(APP),
    "load() must age-gate the in-memory cache hit");
  // and no ungated early return survives
  assert.ok(!/if\s*\(state\.cache\[key\]\)\s*\{\s*applyPayload\(state\.cache\[key\]\);\s*return;/.test(APP),
    "the ungated in-memory cache hit is back");
});

test("pollForFreshScan pins its target and gates on pollMayApply", () => {
  const body = APP.slice(APP.indexOf("async function pollForFreshScan"));
  const fn = body.slice(0, body.indexOf("\n    }\n") + 6);
  assert.ok(/const\s+token\s*=\s*\+\+_pollToken/.test(fn), "poller must take a token");
  assert.ok(/const\s+market\s*=\s*state\.market,\s*mode\s*=\s*state\.mode/.test(fn),
    "poller must pin market/mode at start, not re-read them per tick");
  assert.ok(/dataFile\(market,\s*mode\)/.test(fn),
    "poller must fetch its PINNED target, not the live one");
  assert.ok(!/dataFile\(state\.market/.test(fn),
    "poller re-read state.market — that is the bug");
  assert.ok(/pollMayApply\(token,\s*_pollToken,\s*key,/.test(fn),
    "poller must gate applyPayload/flashScan on pollMayApply");
});

test("every in-memory cache write records when it was fetched", () => {
  // A write without a stamp reads as "no idea" => stale => an extra fetch. Not
  // wrong, but it quietly gives up the cache, so pin that they stay in step.
  const writes = (APP.match(/state\.cache\[[^\]]+\]\s*=\s*(?!=)/g) || []).length;
  const stamps = (APP.match(/state\.cacheAt\[[^\]]+\]\s*=\s*(?!=)/g) || []).length;
  assert.strictEqual(writes, stamps,
    `${writes} state.cache writes but ${stamps} state.cacheAt stamps — they must pair`);
  const drops = (APP.match(/delete\s+state\.cache\[/g) || []).length;
  const dropStamps = (APP.match(/delete\s+state\.cacheAt\[/g) || []).length;
  assert.strictEqual(drops, dropStamps,
    `${drops} cache deletes but ${dropStamps} cacheAt deletes — they must pair`);
});

// ---------------------------------------------------------------------------
// Cold-load failure honesty (2026-07-29): only a 404 is "missing" — every
// other first-load failure is the CONNECTION, where "run the scanner" was
// wrong twice over and the page must offer a retry instead.
// ---------------------------------------------------------------------------
const SHARED = fs.readFileSync(path.join(__dirname, "..", "public", "js", "phasemap-shared.js"), "utf8");

// Run the real PM factory in a minimal DOM-less sandbox and take the real
// loadFailKind — not a re-typed copy of it.
const loadFailKind = (() => {
  const sandbox = { window: {}, localStorage: { getItem: () => null, setItem: () => {} },
    document: undefined, fetch: () => Promise.reject(new Error("no net in tests")),
    console, JSON, Math, Date, String, Number, Array, Object, Promise, RegExp, parseFloat, parseInt };
  sandbox.globalThis = sandbox;
  require("vm").createContext(sandbox);
  try { require("vm").runInContext(SHARED, sandbox); } catch (e) {
    assert.fail("phasemap-shared.js no longer evaluates in a bare context: " + e.message);
  }
  assert.ok(sandbox.window.PM && typeof sandbox.window.PM.loadFailKind === "function",
    "PM.loadFailKind is missing — the cold-fail split lost its shared classifier");
  return sandbox.window.PM.loadFailKind;
})();

test("both real throw shapes classify: bare status (app.js) and 'HTTP N' (lens pages)", () => {
  assert.strictEqual(loadFailKind(new Error("404")), "missing");
  assert.strictEqual(loadFailKind(new Error("HTTP 404")), "missing");
  assert.strictEqual(loadFailKind(new Error("500")), "unreachable");
  assert.strictEqual(loadFailKind(new Error("HTTP 503")), "unreachable");
});

test("a network throw is unreachable — TypeError('Failed to fetch') has no status", () => {
  assert.strictEqual(loadFailKind(new TypeError("Failed to fetch")), "unreachable");
  assert.strictEqual(loadFailKind(new TypeError("NetworkError when attempting to fetch resource.")), "unreachable");
});

test("garbage input degrades to unreachable (retry-able), never to missing", () => {
  // "missing" suppresses the retry button, so it is the claim that needs
  // evidence; anything unparseable must fall to the retry-able side.
  for (const bad of [null, undefined, {}, new Error(""), new Error("weird")]) {
    assert.strictEqual(loadFailKind(bad), "unreachable", `input: ${String(bad)}`);
  }
});

test("a 404 buried in prose does not read as missing — the status must END the message", () => {
  // "Failed to fetch data/404_names.json: timeout" is a NETWORK failure that
  // happens to contain digits; only a trailing status token counts.
  assert.strictEqual(loadFailKind(new Error("404 names failed to load")), "unreachable");
});

test("every cold-fail page renders a wired retry, not an onclick string", () => {
  const pages = {
    "app.js": APP,
    "phasemap.js": fs.readFileSync(path.join(__dirname, "..", "public", "js", "phasemap.js"), "utf8"),
    "specs.js": fs.readFileSync(path.join(__dirname, "..", "public", "js", "specs.js"), "utf8"),
  };
  for (const [name, src] of Object.entries(pages)) {
    assert.ok(/loadFailKind/.test(src), `${name} no longer consults PM.loadFailKind`);
    assert.ok(/retryHTML|pm-retry/.test(src), `${name} lost its retry control`);
    assert.ok(/addEventListener\("click",[^)]*load\(\)/.test(src.replace(/\s+/g, " ")) ||
              /addEventListener\("click", \(\) => \{ b\.disabled = true; load\(\); \}\)/.test(src.replace(/\s+/g, " ")),
      `${name}'s retry button is not wired back to load()`);
  }
  // and the shared control never uses an inline onclick (an eval sink)
  assert.ok(!/onclick=/.test(SHARED.slice(SHARED.indexOf("function retryHTML"))),
    "retryHTML must not emit inline onclick handlers");
});

// ---------------------------------------------------------------------------
// The funnel disclosure (2026-07-29): rendered from the published funnel key,
// with the honesty split between "sample absent" (older payload — say nothing)
// and "sample present and empty" (allowed to say none show unusual volume).
// ---------------------------------------------------------------------------
test("renderFunnel exists, is wired into applyPayload, and escapes what it interpolates", () => {
  const APP2 = fs.readFileSync(path.join(__dirname, "..", "public", "js", "app.js"), "utf8");
  assert.ok(/function renderFunnel\(/.test(APP2), "renderFunnel is gone");
  assert.ok(/renderFreshness\(d\);\s*\n\s*renderFunnel\(d\);/.test(APP2),
    "renderFunnel must render wherever a payload is applied, beside renderFreshness");
  const body = APP2.slice(APP2.indexOf("function renderFunnel("), APP2.indexOf("function renderEntryFilters("));
  assert.ok(/esc\(r\.symbol\)/.test(body), "chip symbols must go through esc()");
  assert.ok(/encodeURIComponent\(r\.symbol\)/.test(body), "chip hrefs must URI-encode the symbol");
  assert.ok(/esc\(summary\)/.test(body), "the summary line must be escaped");
  assert.ok(/hasSample/.test(body) && /Array\.isArray\(f\.illiquid_sample\)/.test(body),
    "absent sample (older payload) must not be presented as 'none show volume'");
  assert.ok(/rvol\s*\|\|\s*0\)\s*>=\s*2/.test(body),
    "chips are the UNUSUAL-volume names — a >=2x floor keeps 1.0x noise out");
  // The arriving list (owner-ruled, 2026-07-30): count in the summary, rows
  // lazily fetched from the FENCED file — through the timeout helper, escaped,
  // and only when the payload advertises a count.
  assert.ok(/liquidity arriving/.test(body), "the summary lost the arriving count");
  assert.ok(/fetchT\(`data\/\$\{slot\.dataset\.market\}_arriving\.json`/.test(body),
    "arriving rows must load lazily from the fenced file via the timeout helper");
  assert.ok(/n\(f\.arriving\)\s*\?\s*`<div class="sf-arriving"/.test(body),
    "the lazy slot must be gated on the payload's arriving count");
  assert.ok(/encodeURIComponent\(r\.symbol\)/.test(body.slice(body.indexOf("sf-arriving"))),
    "arriving chip hrefs must URI-encode the symbol");
});

// ---------------------------------------------------------------------------
// Fetch timeouts (2026-07-29, Phase B): a HUNG connection neither resolves nor
// rejects — the one mechanism that could strand the deck on the skeleton
// forever. Every scan/data load must carry the abort signal so a hang becomes
// a rejection and takes the same retry path as any failure.
// ---------------------------------------------------------------------------
test("PM.fetchTimeout attaches a real abort signal and classifies as retry-able", () => {
  // Synchronous on purpose: this suite's runner does not await async fns, so
  // an async body here would false-PASS. The call SHAPE is asserted (the stub
  // records what fetch was handed); the real end-to-end abort is proven by
  // the browser hang-probe run before every ship of this path.
  const seen = [];
  const sandbox = { window: {}, localStorage: { getItem: () => null, setItem: () => {} },
    console, JSON, Math, Date, String, Number, Array, Object, Promise, RegExp,
    parseFloat, parseInt, AbortSignal, setTimeout, clearTimeout,
    fetch: (url, opts) => { seen.push({ url, opts }); return new Promise(() => {}); } };
  sandbox.globalThis = sandbox;
  require("vm").createContext(sandbox);
  require("vm").runInContext(SHARED, sandbox);
  const PM = sandbox.window.PM;
  assert.ok(typeof PM.fetchTimeout === "function", "PM.fetchTimeout is missing");
  assert.ok(PM.DATA_FETCH_TIMEOUT_MS >= 10000,
    "a tight timeout aborts real slow-3G progress on a ~0.5MB payload");
  PM.fetchTimeout("data/x.json", { cache: "no-cache" }, 50);
  assert.strictEqual(seen.length, 1);
  assert.ok(seen[0].opts && seen[0].opts.signal instanceof AbortSignal,
    "fetchTimeout must hand fetch an AbortSignal — without it a hang is forever");
  assert.strictEqual(seen[0].opts.cache, "no-cache", "caller opts must survive the wrap");
  // ...and a timeout rejection classifies as retry-able, never as 'missing'
  assert.strictEqual(PM.loadFailKind(Object.assign(new Error("signal timed out"),
    { name: "TimeoutError" })), "unreachable");
  assert.strictEqual(PM.loadFailKind(Object.assign(new Error("The operation was aborted."),
    { name: "AbortError" })), "unreachable");
});

test("the index.html preload timeout stays in step with PM's constant", () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "public", "index.html"), "utf8");
  const inline = /AbortSignal\.timeout\((\d+)\)/.exec(html);
  assert.ok(inline, "the head-start preload lost its timeout — app.js AWAITS " +
    "that promise, so a hung preload strands the deck before app.js even fetches");
  const shared = /DATA_FETCH_TIMEOUT_MS = (\d+)/.exec(SHARED);
  assert.ok(shared, "PM's DATA_FETCH_TIMEOUT_MS constant is gone");
  assert.strictEqual(inline[1], shared[1],
    "index.html inline timeout and PM.DATA_FETCH_TIMEOUT_MS have drifted apart");
});

test("every data fetch in the deck's scripts goes through the timeout helper", () => {
  // app.js: fetchT wraps PM.fetchTimeout; no bare fetch( may remain.
  const APP2 = fs.readFileSync(path.join(__dirname, "..", "public", "js", "app.js"), "utf8");
  assert.ok(/const fetchT = /.test(APP2), "app.js lost its fetchT wrapper");
  const bare = (APP2.match(/[^.\w]fetch\(/g) || []).length;
  // exactly ONE bare fetch( is allowed: the fallback inside fetchT itself
  assert.strictEqual(bare, 1,
    `app.js has ${bare} bare fetch( sites — every data load must go through fetchT`);
  for (const [file, min] of [["phasemap.js", 3], ["specs.js", 1]]) {
    const src = fs.readFileSync(path.join(__dirname, "..", "public", "js", file), "utf8");
    const wrapped = (src.match(/PM\.fetchTimeout\(/g) || []).length;
    assert.ok(wrapped >= min, `${file}: expected >=${min} PM.fetchTimeout call(s), found ${wrapped}`);
    assert.ok(!/[^.\w]fetch\(`data\//.test(src), `${file} still fetches data/ without a timeout`);
  }
  for (const file of ["horizon.js", "regime.js"]) {
    const src = fs.readFileSync(path.join(__dirname, "..", "public", "js", file), "utf8");
    assert.ok(/PM\.fetchTimeout/.test(src), `${file} (deck strip) is not timeout-wrapped`);
  }
});

// ---------------------------------------------------------------------------
// The paper-book deck strip (owner-ordered 2026-07-30): the scoreboard made
// unavoidable. bookFacts is the pure half — extracted and driven here with
// synthetic books; the stall count comes from the probe's OWN stale_pinged
// stamps, so the deck re-types no thresholds.
// ---------------------------------------------------------------------------
const bookFacts = pull("bookFacts");

test("bookFacts: split, unrealized sum, record and stall flags from a real-shaped book", () => {
  const b = {
    open: [
      { symbol: "BGA", market: "asx", unreal_r: 0.32, stale_pinged: "2026-07-30" },
      { symbol: "AIA", market: "asx", unreal_r: -0.1 },
      { symbol: "MDB", market: "nasdaq", unreal_r: 1.4, stale_pinged: "2026-07-29" },
      { symbol: "XLM", market: "crypto", unreal_r: 0.0 },
    ],
    closed: [{ realized_r: 2.0 }, { realized_r: -1.0 }, { realized_r: -1.5 }],
  };
  const f = bookFacts(b);
  assert.deepStrictEqual(f.mkts, { asx: 2, nasdaq: 1, crypto: 1 });
  assert.strictEqual(f.open, 4);
  assert.ok(Math.abs(f.unreal - 1.62) < 1e-9);
  assert.strictEqual(f.wins, 1); assert.strictEqual(f.losses, 2);
  assert.ok(Math.abs(f.realized - -0.5) < 1e-9);
  assert.deepStrictEqual(f.stalled, ["BGA", "MDB"],
    "stalled = the probe's stamps, in book order — nothing recomputed");
});

test("bookFacts: honesty at the edges — no priced rows means unreal is null, not 0", () => {
  const f = bookFacts({ open: [{ symbol: "X", market: "asx" }], closed: [] });
  assert.strictEqual(f.unreal, null, "'+0.0R' would claim a measurement nobody made");
  assert.strictEqual(f.realized, null, "no closed trades = no record, not 0R");
  assert.deepStrictEqual(bookFacts(null).stalled, []);
  assert.strictEqual(bookFacts({}).open, 0);
});

test("bookFacts: a zero-R close counts as a loss, never a win", () => {
  // Costs make a flat exit negative in practice, but the boundary must not
  // flatter the record if one ever lands exactly on zero.
  const f = bookFacts({ open: [], closed: [{ realized_r: 0 }] });
  assert.strictEqual(f.wins, 0); assert.strictEqual(f.losses, 1);
});

if (bookFacts({ open: [], closed: [] }, { max_open_total: 30 }).maxOpen === 30) {
// transitional: these run only once bookFacts carries the cap
test("bookFacts: capacity — open of cap, free, and FULL, from the PUBLISHED rules", () => {
  // The number that decides whether hunting is useful at all. Derived the same
  // way stalled.js derives it so the deck and the Journal can never print
  // different free-slot counts.
  const book = { open: [{ symbol: "A", market: "asx" }, { symbol: "B", market: "asx" }], closed: [] };
  const f = bookFacts(book, { max_open_total: 30 });
  assert.strictEqual(f.open, 2);
  assert.strictEqual(f.maxOpen, 30);
  assert.strictEqual(f.free, 28);
  assert.strictEqual(f.atCap, false);
});

test("bookFacts: a full book reads atCap, and an over-full one never reads negative free", () => {
  const rows = (n) => Array.from({ length: n }, (_, i) => ({ symbol: "S" + i, market: "asx" }));
  const full = bookFacts({ open: rows(30), closed: [] }, { max_open_total: 30 });
  assert.strictEqual(full.atCap, true);
  assert.strictEqual(full.free, 0);
  // Over-cap is possible in principle (a cap lowered under a live book) and
  // "-2 free" would be nonsense on a cockpit.
  const over = bookFacts({ open: rows(32), closed: [] }, { max_open_total: 30 });
  assert.strictEqual(over.free, 0);
  assert.strictEqual(over.atCap, true);
});

test("bookFacts: rules are a DEGRADE, not a dependency", () => {
  // Without bot_rules.json the strip must still report the book. Capacity goes
  // absent — never 0 free, which would read as a full book and stop the owner
  // hunting for no reason.
  for (const rules of [undefined, null, {}, { max_open_total: null }, "junk"]) {
    const f = bookFacts({ open: [{ symbol: "A", market: "asx" }], closed: [] }, rules);
    assert.strictEqual(f.open, 1, "the book itself must still be reported");
    assert.strictEqual(f.maxOpen, null, "rules: " + JSON.stringify(rules));
    assert.strictEqual(f.free, null, "absent capacity must be null, never 0");
    assert.strictEqual(f.atCap, false);
  }
});

test("bookFacts: max_positions is accepted as the cap when max_open_total is absent", () => {
  const f = bookFacts({ open: [{ symbol: "A" }], closed: [] }, { max_positions: 10 });
  assert.strictEqual(f.maxOpen, 10);
  assert.strictEqual(f.free, 9);
});

test("bookFacts: capacity is READ-ONLY — the caller's book is never touched", () => {
  const book = { open: [{ symbol: "A", market: "asx" }], closed: [] };
  const snapshot = JSON.stringify(book);
  bookFacts(book, { max_open_total: 30 });
  assert.strictEqual(JSON.stringify(book), snapshot);
});

}

test("the strip renders the stall line only when the probe flagged something, escaped, to the journal", () => {
  const APP3 = fs.readFileSync(path.join(__dirname, "..", "public", "js", "app.js"), "utf8");
  const body = APP3.slice(APP3.indexOf("async function loadBotActivity"), APP3.indexOf("function startClocks") > 0 ? APP3.indexOf("function startClocks") : undefined);
  // Signature widened 2026-08-13 to carry the cap (bookFacts(b, rules)); the
  // INTENT of this pin is unchanged — the strip renders from the one tested
  // function, never from sums assembled inline where nothing can reach them.
  assert.ok(/const facts = bookFacts\(b(, rules)?\)/.test(body),
    "the strip must render from bookFacts, not ad-hoc sums");
  if (/bookFacts\(b, rules\)/.test(body)) {   // transitional: capacity landed
    assert.ok(/data\/bot_rules\.json/.test(body),
      "the strip no longer reads the cap, so it cannot show free slots");
    assert.ok(/facts\.atCap \? "FULL"/.test(body),
      "a full book must say FULL rather than quietly reading '0 free'");
  }
  assert.ok(/facts\.stalled\.length\s*\?/.test(body) || /stallTxt \?/.test(body),
    "the stall line must be GATED on the probe having flagged something");
  assert.ok(/esc\(stallTxt\)/.test(body), "the stall line text must go through esc()");
  assert.ok(/class="ba-stall" href="journal\.html"/.test(body), "the stall line must link to the journal");
  assert.ok(/never closes anything; the decision is yours/.test(body),
    "the title must keep saying the probe is report-only");
});


/* ── Funnel-history trend (owner-ruled Task 2) ──────────────────────────────
 * The five counts the summary line already shows, drawn across the committed
 * history file. Both helpers are pure and pulled from the SHIPPED app.js —
 * a malformed file must render as NOTHING, never as rows whose timestamp
 * belongs to a different scan's counts. */
const funnelSeries = pull("funnelSeries");
const sparkline = pull("sparkline");

const HIST = { markets: { asx: {
  t: ["2026-07-28T01:00:00+00:00", "2026-07-28T05:00:00+00:00", "2026-07-29T01:00:00+00:00"],
  scanned: [2200, 2210, 2212], with_data: [2100, 2105, 2120],
  published: [300, 310, 328], floor_killed: [280, 290, 299], arriving: [4, 7, 9],
} } };

test("funnelSeries buckets to one row per day and the day's LAST scan wins", () => {
  const s = funnelSeries(HIST, "asx", 60);
  assert.deepStrictEqual(s.days, ["2026-07-28", "2026-07-29"]);
  assert.deepStrictEqual(s.series.scanned, [2210, 2212]);
  assert.deepStrictEqual(s.series.floor_killed, [290, 299]);
  assert.deepStrictEqual(s.series.arriving, [7, 9]);
});
test("funnelSeries returns null for a market with no rows (and for no file)", () => {
  assert.strictEqual(funnelSeries(HIST, "nasdaq", 60), null);
  assert.strictEqual(funnelSeries(null, "asx", 60), null);
});
test("funnelSeries refuses a column that does not zip with t", () => {
  const bad = JSON.parse(JSON.stringify(HIST));
  bad.markets.asx.arriving = [1];
  assert.strictEqual(funnelSeries(bad, "asx", 60), null);
});
test("funnelSeries maxDays keeps only the newest days", () => {
  const s = funnelSeries(HIST, "asx", 1);
  assert.deepStrictEqual(s.days, ["2026-07-29"]);
  assert.deepStrictEqual(s.series.published, [328]);
});
test("sparkline draws one point per value and nothing under two values", () => {
  const svg = sparkline([1, 5, 3]);
  assert.ok(svg.includes("<polyline"));
  assert.strictEqual(svg.match(/[\d.]+,[\d.]+/g).length, 3);
  assert.strictEqual(sparkline([7]), "");
  assert.strictEqual(sparkline([]), "");
  assert.strictEqual(sparkline(null), "");
});
test("sparkline survives a flat series without dividing by zero", () => {
  const svg = sparkline([4, 4, 4, 4]);
  assert.ok(svg.includes("<polyline") && !svg.includes("NaN"));
});


/* ── v5 payload split: the deck's lazy detail layer (owner-ruled) ─────────── */
const needsDetail = pull("needsDetail");
const mergeDetail = pull("mergeDetail");

test("needsDetail: only a v5+ summary asks for the sidecar", () => {
  assert.strictEqual(needsDetail({ schema_version: 5 }), true);
  assert.strictEqual(needsDetail({ schema_version: 4 }), false);
  assert.strictEqual(needsDetail(null), false);
});
test("mergeDetail passes a pre-split row straight through", () => {
  const r = { symbol: "BHP", analysis: "inline" };
  assert.strictEqual(mergeDetail(r, null, false), r);
});
test("mergeDetail returns null while the sidecar is needed but absent", () => {
  assert.strictEqual(mergeDetail({ symbol: "BHP" }, null, true), null);
});
test("mergeDetail overlays the heavy fields and leaves the summary intact", () => {
  const r = { symbol: "BHP", grade: "A+", plans: { "1W": { armed: true } } };
  const drows = { BHP: { analysis: "full", plans: { "1W": { armed: true, entry: 41 } } } };
  const m = mergeDetail(r, drows, true);
  assert.strictEqual(m.analysis, "full");
  assert.strictEqual(m.plans["1W"].entry, 41);
  assert.strictEqual(m.grade, "A+");
  assert.strictEqual(r.analysis, undefined, "the summary row must not be mutated");
});
test("mergeDetail: a symbol absent from the sidecar merges to itself", () => {
  const r = { symbol: "QUIET" };
  assert.strictEqual(mergeDetail(r, { OTHER: {} }, true), r);
});

// THE OWNER'S DRIFT-PIN, behavioural half: the REAL isHighConviction pulled
// from the shipped file must return true on a plan carrying ONLY the five
// lite fields — proof the summary keeps everything the list logic reads.
function pullFn(name) {
  const at = APP.search(new RegExp("function\\s+" + name + "\\s*\\("));
  assert.ok(at >= 0, "app.js no longer defines function " + name);
  for (let i = APP.indexOf("}", at); i > 0 && i - at < 4000; i = APP.indexOf("}", i + 1)) {
    const cand = APP.slice(at, i + 1);
    try { new Function("return (" + cand + ");"); return eval("(" + cand + ")"); } // eslint-disable-line no-eval
    catch (_) { /* keep walking */ }
  }
  assert.fail("could not slice function " + name);
}
test("isHighConviction passes on a LITE-only plan (the five drift-pin fields)", () => {
  const isHighConviction = pullFn("isHighConviction");
  const litePlan = { armed: true, entry_trigger: "reclaim", structural_tps: 2,
                    level_tf: "weekly", direction: "long" };
  assert.strictEqual(isHighConviction({ grade: "B+", plans: { "1W": litePlan } }), true);
  assert.strictEqual(isHighConviction({ grade: "A+", plans: { "1W": { ...litePlan, entry_trigger: "retest" } } }), false);
});

// ---------------------------------------------------------------------------
// deckCounts — what the cockpit CLAIMS is opportunity (owner-ordered 2026-08-13)
//
// The defect, measured on the committed scans rather than argued: the deck
// computed `tradeable`/`top` over products-excluded rows and `nAplus`/`nA`/the
// toolbar tab counts over EVERY row. ASX read **A+ 96** while 44 of those were
// cash/bond/ETF products (1GOV, AAA, FLOT, BILL…) the bot cannot trade — two
// numbers on one screen, computed over different universes, and the inflated
// one was the headline. After: A+ 52, with the 129 products reported beside it.
//
// Extracted as a pure function precisely so this is testable: renderDeckPills
// reads the DOM and `state`, so none of this arithmetic could be reached by a
// test before. DISPLAY ONLY — vivek_bot._is_fund_or_reit already governs what
// the bot takes, and nothing here touches it.
// ---------------------------------------------------------------------------
if (extractConst(APP, "deckCounts")) {   // transitional: item-1 surface
const deckCounts = pull("deckCounts");

// The real shape: an ETF at A+, a real company at A+, an A, a WATCH, and a
// product that is NOT A+ (so `products` and `aplusProducts` cannot be confused).
const ROWS = [
  { symbol: "1GOV", name: "VanEck 1-5 Year Australian Government Bond ETF", grade: "A+", at_level: true },
  { symbol: "FMG", name: "Fortescue Ltd", grade: "A+", at_level: true },
  { symbol: "BHP", name: "BHP Group Limited", grade: "A" },
  { symbol: "CQE", name: "Charter Hall Social Infrastructure REIT", grade: "A" },
  { symbol: "XYZ", name: "Some Operating Co", grade: "WATCH" },
  { symbol: "AAA", name: "Betashares Australian High Interest Cash ETF", grade: "B" },
];
const isProd = (r) => /\b(REIT|TRUST|FUND|ETF|SPDR|ISHARES|VANGUARD|BETASHARES|VANECK|GLOBAL X)\b/
  .test(String(r.name || "").toUpperCase());

test("deckCounts: grade counts are TRADEABLE-only — products never inflate A+", () => {
  const c = deckCounts(ROWS, isProd);
  assert.strictEqual(c.aplus, 1, "1GOV must not count toward A+ opportunity");
  assert.strictEqual(c.a, 1, "CQE (REIT) must not count toward A");
  assert.strictEqual(c.watch, 1, "AAA (cash ETF) must not count toward WATCH");
  assert.strictEqual(c.atLevel, 1, "at-level counts exclude products too");
  assert.strictEqual(c.tradeable, 2, "FMG + BHP");
});

test("deckCounts: nothing is hidden — the products it set aside are reported", () => {
  const c = deckCounts(ROWS, isProd);
  assert.strictEqual(c.products, 3, "1GOV, CQE, AAA");
  assert.strictEqual(c.aplusProducts, 1, "the A+ ones specifically — the size of the correction");
  assert.strictEqual(c.total, 6, "the raw row count is still available");
  assert.strictEqual(c.real.length, 3);
});

test("deckCounts: a scan with no products is completely unaffected", () => {
  // The change must be invisible where it should be — NASDAQ has 10 products
  // against ASX's 129, so this is the common case on two of three markets.
  const clean = ROWS.filter((r) => !isProd(r));
  const c = deckCounts(clean, isProd);
  assert.strictEqual(c.products, 0);
  assert.strictEqual(c.aplusProducts, 0);
  assert.strictEqual(c.aplus, 1);
  assert.strictEqual(c.tradeable, 2);
});

test("deckCounts: pure — it never reorders or mutates the caller's rows", () => {
  const rows = ROWS.slice();
  const before = rows.map((r) => r.symbol).join(",");
  const snapshot = JSON.stringify(rows);
  deckCounts(rows, isProd);
  assert.strictEqual(rows.map((r) => r.symbol).join(","), before);
  assert.strictEqual(JSON.stringify(rows), snapshot);
});

test("deckCounts: junk input degrades to zeros rather than throwing", () => {
  // renderDeckPills runs on every repaint, including before the first scan
  // lands; a throw here takes the whole pills bar out.
  for (const bad of [null, undefined, "not an array", 42, {}]) {
    const c = deckCounts(bad, isProd);
    assert.strictEqual(c.total, 0, "bad input: " + String(bad));
    assert.strictEqual(c.aplus, 0);
    assert.strictEqual(c.products, 0);
  }
  const holes = deckCounts([null, undefined, { grade: "A+" }], () => false);
  assert.strictEqual(holes.aplus, 1, "a null row must not throw or be counted");
});

test("deckCounts: the deck's fund test uses WORD BOUNDARIES, like PM's", () => {
  // app.js was still on the includes() that phasemap-shared.js fixed on
  // 2026-08-01, so `includes("ETF")` matched inside "N-ETF-LIX" and the deck
  // dimmed NETFLIX and cut it from `tradeable` — while the Eyes chip beside
  // it, reading PM's fixed copy, correctly called it an operating company.
  // Measured on the committed scans, NFLX was the ONLY row they disagreed on.
  // FUND_KW_RE is BUILT from FUND_NAME_KEYWORDS, so both come out of the
  // shipped file — evaluating a re-typed keyword list here would test a copy.
  const KW = extractConst(APP, "FUND_NAME_KEYWORDS");
  const RE = extractConst(APP, "FUND_KW_RE");
  assert.ok(KW && RE, "app.js no longer defines FUND_NAME_KEYWORDS / FUND_KW_RE");
  const re = eval(`(function(){const FUND_NAME_KEYWORDS=${KW};return (${RE});})()`); // eslint-disable-line no-eval
  assert.strictEqual(re.test("NETFLIX, INC. - COMMON STOCK"), false, "Netflix is not a fund");
  assert.strictEqual(re.test("TRUSTEE HOLDINGS LTD"), false, "TRUSTEE is not TRUST");
  assert.strictEqual(re.test("CHARTER HALL SOCIAL INFRASTRUCTURE REIT"), true);
  assert.strictEqual(re.test("BETASHARES AUSTRALIAN HIGH INTEREST CASH ETF"), true);
  assert.strictEqual(re.test("VANECK 1-5 YEAR AUSTRALIAN GOVERNMENT BOND ETF"), true);
  // The shipped source must not have slipped back to includes()
  assert.ok(/FUND_KW_RE\.test\(name\)/.test(APP),
    "app.js isFundReit no longer uses the word-boundary regex");
});

test("deckCounts: renderDeckPills actually USES it, and reports the products", () => {
  // A pure function nothing calls is a pure function that fixes nothing.
  assert.ok(/const c = deckCounts\(res, isFundReit\);/.test(APP),
    "renderDeckPills no longer routes its counts through deckCounts");
  assert.ok(/deck-products/.test(APP), "the products chip is gone — the correction is now silent");
  assert.ok(/\$\("#count-aplus"\)\.textContent = nAplus;/.test(APP),
    "the toolbar tab count no longer tracks the corrected A+ number");
});

}

console.log(process.exitCode ? "\nSOME STALE-VIEW TESTS FAILED" : `\nALL ${passed} stale-view tests passed`);
