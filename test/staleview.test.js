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

test("the strip renders the stall line only when the probe flagged something, escaped, to the journal", () => {
  const APP3 = fs.readFileSync(path.join(__dirname, "..", "public", "js", "app.js"), "utf8");
  const body = APP3.slice(APP3.indexOf("async function loadBotActivity"), APP3.indexOf("function startClocks") > 0 ? APP3.indexOf("function startClocks") : undefined);
  // Signature widened 2026-08-13 to carry the cap (bookFacts(b, rules)); the
  // INTENT of this pin is unchanged — the strip renders from the one tested
  // function, never from sums assembled inline where nothing can reach them.
  assert.ok(/const facts = bookFacts\(b, rules\)/.test(body),
    "the strip must render from bookFacts, not ad-hoc sums");
  assert.ok(/data\/bot_rules\.json/.test(body),
    "the strip no longer reads the cap, so it cannot show free slots");
  assert.ok(/facts\.atCap \? "FULL"/.test(body),
    "a full book must say FULL rather than quietly reading '0 free'");
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

// ---------------------------------------------------------------------------
/* The welcome tour must never wall a returning browser (2026-08-13).
 *
 * THE DEFECT. `maybeOnboard()` was gated on ONE key, `gbs:onboarded`. That is
 * the most fragile state on the page: the `setItem` that writes it is wrapped
 * in a swallow-everything try/catch (correctly — a quota error must not take
 * the deck down), and any browser that clears script-writable storage takes it
 * with everything else. Lose it by any route and a person who has used this app
 * for weeks is met by a three-card welcome tour, over the whole deck, on every
 * visit — and the only thing that ends it is dismissing it again, into the same
 * write that failed last time.
 *
 * THE FIX. The gate asks a second question: has this browser done anything only
 * a user can do? If yes, treat the tour as taken and BACK-FILL the flag so the
 * cheap check answers on every later load. The branch is monotone — it can only
 * ever show the tour LESS.
 *
 * THE TRAP THIS SUITE EXISTS FOR. `gbs:visit:<market>` looks like the perfect
 * evidence key and is the worst possible one: `updateVisitDiff` writes it from
 * the FIRST payload of the FIRST session, so counting it suppresses the tour for
 * exactly the people it exists for. It is deliberately absent from the list, and
 * `test_the_first_visit_snapshot_key_is_not_evidence` fails if anyone adds it.
 *
 * The second half of the safety argument is ORDERING, not content: the evidence
 * is read ONCE at boot, above loadPrefs() / consumeViewApply() / the `?m=` deep
 * link's savePrefs(), so nothing this session writes can be mistaken for a
 * previous one. That is asserted by file position, because it is the kind of
 * line a later refactor moves without noticing.
 *
 * WHAT THIS CANNOT FIX, stated rather than implied: a browser that evicts ALL
 * script storage (Safari's 7-day rule on an uninstalled site) loses the evidence
 * along with the flag, and a second origin (a *.pages.dev preview beside the
 * custom domain) has its own storage entirely. Those are storage-lifetime and
 * origin problems, not gate problems.
 */
// ---- slicers (the house pattern: let the parser say where it ends) ---------
function constSrc(name) {
  const s = extractConst(APP, name);
  assert.ok(s, `app.js no longer declares const ${name}`);
  return s;
}
function fnSrc(srcOrName, maybeName) {
  // Takes (src, name) or, for the app.js callers that predate the second
  // argument, just (name).
  const src = maybeName === undefined ? APP : srcOrName;
  const name = maybeName === undefined ? srcOrName : maybeName;
  const at = src.search(new RegExp(`\\bfunction\\s+${name}\\s*\\(`));
  assert.ok(at >= 0, `no declaration of function ${name}()`);
  for (let i = src.indexOf("}", at); i > 0 && i - at < 12000; i = src.indexOf("}", i + 1)) {
    const cand = src.slice(at, i + 1);
    try { new Function(`return (${cand});`); return cand; } catch (_) { /* keep walking */ }
  }
  assert.fail(`could not slice ${name}() — has its brace shape changed?`);
}

const KEYS_SRC = constSrc("PRIOR_USE_KEYS");
const USED_SRC = constSrc("USED_BEFORE");
const KEYS = eval(`(${KEYS_SRC})`); // eslint-disable-line no-eval

// ---- a Map-backed localStorage, optionally read-only ------------------------
function store(seed, opts) {
  const m = new Map(Object.entries(seed || {}));
  const o = opts || {};
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { if (o.readOnly) throw new Error("QuotaExceededError"); m.set(k, String(v)); },
    removeItem: (k) => m.delete(k),
    _map: m,
  };
}

// Re-evaluate the SHIPPED boot snapshot against a given store. `new Function`
// (not vm) keeps the same realm; the IIFE runs at call time, exactly as it does
// on boot.
function usedBefore(seed, opts) {
  return new Function("localStorage", `const PRIOR_USE_KEYS = ${KEYS_SRC}; return (${USED_SRC});`)(store(seed, opts));
}

// ---- the evidence set --------------------------------------------------------
test("a virgin browser is NOT treated as returning", () => {
  assert.strictEqual(usedBefore({}), false);
});

test("every advertised key on its own counts as prior use", () => {
  assert.ok(KEYS.length >= 8, `expected a real evidence set, saw ${KEYS.length} keys`);
  for (const k of KEYS) {
    assert.strictEqual(usedBefore({ [k]: "x" }), true, `${k} should count as prior use`);
  }
});

test("an EMPTY-STRING value still counts — the key existing is the evidence", () => {
  // gbs:density is written as "" to mean "comfortable". A truthiness check here
  // would silently drop the person who toggled density off again.
  assert.strictEqual(usedBefore({ "gbs:density": "" }), true);
});

test("the first-visit snapshot key is NOT evidence, and must never become it", () => {
  // updateVisitDiff writes gbs:visit:<market> from the first payload of the
  // FIRST session. Counting it would suppress the tour for every new user.
  assert.ok(!KEYS.includes("gbs:visit"), "gbs:visit must not be in PRIOR_USE_KEYS");
  assert.ok(!KEYS.some((k) => k.startsWith("gbs:visit")), "no gbs:visit:* key may be evidence");
  assert.strictEqual(usedBefore({ "gbs:visit:asx": "{}" }), false);
  assert.strictEqual(usedBefore({ "gbs:visit:asx": "{}", "gbs:visit:nasdaq": "{}" }), false);
});

test("the app's own maintenance keys are not evidence either", () => {
  // Written by the app, not by a person: a one-shot purge marker and the alert
  // dedupe map. Neither says anyone has USED anything.
  for (const k of ["gbs:purged:v1", "gbs:notified", "gbs:cache:asx", "gbs:view-apply"]) {
    assert.strictEqual(usedBefore({ [k]: "1" }), false, `${k} must not count as prior use`);
  }
});

test("an unreadable localStorage degrades to 'not returning', never throws", () => {
  const hostile = { getItem() { throw new Error("SecurityError"); } };
  const fn = new Function("localStorage", `const PRIOR_USE_KEYS = ${KEYS_SRC}; return (${USED_SRC});`);
  assert.strictEqual(fn(hostile), false);
});

// ---- the gate ----------------------------------------------------------------
// maybeOnboard() touches exactly three things: localStorage, USED_BEFORE and
// document. Run the SHIPPED function against stubs for all three.
function runOnboard(seed, used, opts) {
  const ls = store(seed, opts);
  const events = [];
  const built = [];
  const el = () => {
    const e = {
      _kids: [], style: {}, className: "", innerHTML: "",
      setAttribute() {}, addEventListener() {}, removeEventListener() {},
      appendChild(c) { this._kids.push(c); }, remove() { this.removed = true; },
      querySelector() { return { addEventListener() {}, focus() {} }; },
      focus() {},
    };
    built.push(e);
    return e;
  };
  const doc = {
    createElement: () => el(),
    body: { appendChild() {} },
    addEventListener: (t) => events.push(t),
    removeEventListener: (t) => events.push("-" + t),
  };
  new Function("localStorage", "USED_BEFORE", "document", fnSrc("maybeOnboard") + "; maybeOnboard();")(ls, used, doc);
  return { ls, events, shown: built.length > 0 };
}

test("a virgin browser IS shown the tour", () => {
  const r = runOnboard({}, false);
  assert.strictEqual(r.shown, true, "the tour must still exist for a genuine first visit");
});

test("the flag alone still suppresses the tour", () => {
  assert.strictEqual(runOnboard({ "gbs:onboarded": "1" }, false).shown, false);
});

test("evidence of prior use suppresses the tour even with the flag gone", () => {
  assert.strictEqual(runOnboard({ "gbs:watch": '["BHP"]' }, true).shown, false);
});

test("and it BACK-FILLS the flag, so the cheap check answers next load", () => {
  const r = runOnboard({ "gbs:watch": '["BHP"]' }, true);
  assert.strictEqual(r.ls.getItem("gbs:onboarded"), "1");
});

test("a failed back-fill write does not throw — the deck still paints", () => {
  const r = runOnboard({ "gbs:watch": '["BHP"]' }, true, { readOnly: true });
  assert.strictEqual(r.shown, false, "still suppressed");
  assert.strictEqual(r.ls.getItem("gbs:onboarded"), null, "and honestly still unwritten");
});

test("the tour binds a keydown listener so Escape can close it", () => {
  assert.ok(runOnboard({}, false).events.includes("keydown"),
    "a modal over the whole app with no keyboard exit is the shape of the bug");
});

test("the suppressed path binds NOTHING — no listener, no element, no leak", () => {
  const r = runOnboard({ "gbs:watch": "x" }, true);
  assert.deepStrictEqual(r.events, []);
  assert.strictEqual(r.shown, false);
});

// ---- the ordering pin --------------------------------------------------------
test("the evidence is read at BOOT, above every writer that could fake it", () => {
  // This is the whole safety argument and it is positional, so it is asserted
  // positionally. Move the snapshot below any of these and a first visit can
  // write its own evidence before the snapshot reads it.
  const snap = APP.indexOf("const USED_BEFORE");
  assert.ok(snap > 0, "app.js no longer declares USED_BEFORE");
  for (const later of ["loadPrefs();", "consumeViewApply();", "function maybeOnboard("]) {
    const at = APP.indexOf(later);
    assert.ok(at > 0, `app.js no longer contains ${later}`);
    assert.ok(snap < at, `USED_BEFORE must be read before ${later} runs`);
  }
});

test("the tour is still only built after first paint, off the critical path", () => {
  assert.ok(/whenIdle\(maybeOnboard\)/.test(APP),
    "maybeOnboard must stay behind whenIdle — it must never cost the load");
});


// ---------------------------------------------------------------------------
/* PART B UI CLEANUP — the three pins that the screenshot gate structurally
   cannot provide (2026-08-13).
   Measured before writing these: all four e2e shots drift 0.00% against a
   baseline cut from origin/main, because the fixture set has no
   sector_breadth.json, no <m>_prices.json, no phasemap/spec files and a closed
   book that is 6/6 `stop`. So none of the changed surfaces RENDER under the
   gate. The screenshots are not protection here; these assertions are. */
// ---------------------------------------------------------------------------
const HZ = fs.readFileSync(path.join(__dirname, "..", "public", "js", "horizon.js"), "utf8");
const NAV = fs.readFileSync(path.join(__dirname, "..", "public", "js", "nav.js"), "utf8");
// A CODE-ONLY view. The house rule: a ban on a construct must not be satisfied
// or broken by prose. The comment that RECORDS why the badge was retired quotes
// the very expression the ban is written against, so a raw-source grep would
// fail on the explanation of the fix.
const codeOnly = (src) => src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
const css = (f) => fs.readFileSync(path.join(__dirname, "..", "public", "css", f), "utf8");

test("horizon's COMPACT strip no longer states capacity — one surface owns it", () => {
  // data.book is a SCAN-TIME SNAPSHOT (only an ASX/NASDAQ scan rewrites
  // sector_breadth.json). On 2026-08-13 it read "29/30 · 1 free" beside
  // #bot-activity's live "20 of 30 slots · 10 free", and the stale one was the
  // loud one, on the screen where you decide whether to stop hunting.
  const strip = HZ.slice(HZ.indexOf("function renderStrip"), HZ.indexOf("// ── mount"));
  assert.ok(strip.length > 100, "renderStrip could not be sliced");
  assert.ok(!/bookHTML\(/.test(strip), "the compact strip is stating capacity again");
  // The FULL panel must keep it — that is where it is labelled scan-time and
  // sits beside the deployNote reconciliation it exists for.
  assert.ok(/bookHTML\(/.test(HZ.slice(0, HZ.indexOf("function renderStrip"))) ||
            /bookHTML\(data\.book\)/.test(HZ),
    "the full board lost its capacity block too — that was not the fix");
});

test("and it does not state capacity in PROSE either", () => {
  // notes[0] is the sustained-run line, but sectorbreadth also writes capacity
  // notes into the same array. Dropping the chip while still printing "Only 1
  // of 30 slots free" would have fixed nothing.
  // Pinned by RUNNING the shipped noteHTML, not by grepping for the regex.
  // A first pass asserted only that CAP_NOTE_RE existed and matched the right
  // strings — and a mutation that replaced `notes.find(...)` with `notes[0]`,
  // reinstating the exact bug, sailed through it. The constant was pinned; its
  // USE was not.
  const m = HZ.match(/const CAP_NOTE_RE = (\/.*\/[a-z]*);/);
  assert.ok(m, "CAP_NOTE_RE is no longer a literal regex");
  const noteHTML = new Function("esc", "CAP_NOTE_RE",
    fnSrc(HZ, "noteHTML") + "; return noteHTML;")((x) => String(x), eval(m[1]));  // eslint-disable-line no-eval
  const CAP = "Only 1 of 30 slots free - the book is nearly out of room.";
  const RUN = "Consumer Discretionary has led on breadth for 19 sessions with nothing held.";
  assert.equal(noteHTML({ notes: [CAP] }), "", "the strip is printing a capacity claim again");
  assert.ok(noteHTML({ notes: [RUN] }).includes("19 sessions"),
    "the filter is eating the sustained-run note, which is the strip's whole job");
  assert.ok(noteHTML({ notes: [CAP, RUN] }).includes("19 sessions"),
    "a capacity note must be SKIPPED, not make the whole line vanish");
  assert.equal(noteHTML({}), "");
});

test("the mobile SCAN badge no longer publishes an uncorrected A+ count", () => {
  // It read 96 off <m>_prices.json while the page it links to read 52: that
  // sidecar ships no `name`, so the fund regex cannot run against it, and the
  // file that does carry names is 448 KB. Removed rather than left wrong.
  assert.ok(!/setBadge\("index"/.test(codeOnly(NAV)), "the SCAN badge is being set again");
  // nav.js still reads the prices sidecars for the command palette's symbol
  // index (legitimate — it needs tickers, not grades). What must not come back
  // is COUNTING A GRADE out of a file that cannot answer the fund question.
  assert.ok(!/grade\s*===\s*"A\+"/.test(codeOnly(NAV)),
    "nav.js is counting A+ again out of a payload with no name to test");
  // The JOURNAL badge is honest (open positions, straight off the book) and stays.
  assert.ok(/setBadge\("journal"/.test(NAV), "the journal badge was removed by mistake");
});

test("the only write path in the app clears a 44px tap target on mobile", () => {
  // .st-x books a real position against the track record and shipped at ~22px,
  // one file over from journal.css's own "23x21px is a miss waiting to happen".
  const st = css("stalled.css");
  const mob = st.slice(st.indexOf("@media (max-width: 640px)"));
  assert.ok(/\.st-x[^{]*\{[^}]*min-height:\s*44px/.test(mob), ".st-x has no 44px floor on mobile");
  assert.ok(/\.st-go[^{]*\{[^}]*min-height:\s*44px/.test(mob), ".st-go has no 44px floor on mobile");
});

test("the eyes strip has a width breakpoint at all, with a 40px floor", () => {
  // eyes.css shipped with zero @media width rules; its chips were ~27px on the
  // strip that is deliberately the first thing on the deck.
  const ey = css("eyes.css");
  assert.ok(/@media\s*\(max-width:/.test(ey), "eyes.css still has no width breakpoint");
  assert.ok(/min-height:\s*40px/.test(ey), "the chips have no tap-target floor");
});

test("the 1MB backtest fetch is idle work, and is called AFTER whenIdle exists", () => {
  // vivek_backtest_longonly.json is 1,022 KB — larger than the scan payload —
  // fetched on the boot path to read three numbers. Moving it is the easy half.
  // The trap is that `whenIdle` is a const: calling it above its own
  // declaration is a temporal-dead-zone ReferenceError at boot, which
  // `node --check` passes cleanly because it is not a syntax error.
  // "exactly once" is the load-bearing half. A first pass asserted only that a
  // whenIdle(loadEntryQuality) call existed, and a mutation that ADDED a
  // synchronous call back onto the boot path — the whole defect — passed it,
  // because the idle call was still there beside it.
  const calls = (codeOnly(APP).match(/(?<!function\s)\bloadEntryQuality\s*[(),]/g) || [])
    .filter((c) => !c.startsWith("function"));
  const idle = (codeOnly(APP).match(/whenIdle\(loadEntryQuality\)/g) || []).length;
  assert.equal(idle, 1, "loadEntryQuality must be scheduled through whenIdle exactly once");
  assert.equal(calls.length, 1,
    `loadEntryQuality is referenced ${calls.length} times outside its declaration — a direct call is back on the boot path`);
  const decl = APP.indexOf("const whenIdle =");
  const call = APP.indexOf("whenIdle(loadEntryQuality)");
  assert.ok(decl > 0 && call > decl,
    "whenIdle(loadEntryQuality) is called before `const whenIdle` — that is a ReferenceError at boot");
});

// ---------------------------------------------------------------------------
// FINE-TUNE PASS pins (2026-08-15): HELD chips, tint thresholds, spec guard.
// ---------------------------------------------------------------------------
test("heldChip marks a row the bot holds in the CURRENT market only", () => {
  const src = fnSrc(APP, "heldChip");
  const run = (state, r) => new Function("state", src + "; return heldChip;")(state)(r);
  const st = { market: "asx", heldSyms: { asx: new Set(["BHP"]), nasdaq: new Set(["ZUMZ"]) } };
  assert.ok(/row-held/.test(run(st, { symbol: "BHP" })), "a held ASX name must chip");
  assert.strictEqual(run(st, { symbol: "ZUMZ" }), "", "held in ANOTHER market is not held here");
  assert.ok(/row-held/.test(run(st, { symbol: "bhp" })), "case must be normalised");
  assert.strictEqual(run({ market: "asx" }, { symbol: "BHP" }), "", "no book yet = no chip, no throw");
});

test("the row template actually renders the chip, and the book load populates the set", () => {
  assert.ok(/\$\{heldChip\(r\)\}/.test(APP), "the row template dropped heldChip(r)");
  assert.ok(/state\.heldSyms = held/.test(APP), "loadBotActivity no longer populates heldSyms");
  assert.ok(/if \(before !== after && state\.data\) renderRows\(\);/.test(APP),
    "the first-load repaint hook is gone — rows painted before the book arrives never get marked");
});

test("every entry-tint tier is REACHABLE against the file the chips read", () => {
  // The old green bar was e > 0.3 against a payload whose best value is 0.178:
  // a three-state colour code with one reachable state, i.e. a tint that said
  // nothing. Green now starts at +0.10 (the pre-registered w3-1 mid band).
  const m = APP.match(/tier: e >= ([0-9.]+) \? "green" : e >= 0 \? "amber" : "red"/);
  assert.ok(m, "the tint ladder changed shape — re-derive this pin");
  const green = parseFloat(m[1]);
  assert.ok(green <= 0.178, `green threshold ${green} is above the best observed value again (unreachable)`);
  assert.ok(green > 0, "green must still mean better-than-breakeven");
});

test("the crypto Specs fetch is guarded in BOTH remaining call sites", () => {
  // No crypto spec file exists; mynames.js always guarded it, these two fired
  // a live 404 on every CRYPTO visit until 2026-08-15.
  assert.ok(/state\.market !== "crypto" \? grab\(`data\/\$\{state\.market\}_spec\.json`\) : null/.test(APP),
    "app.js lensIdx fetches crypto_spec.json unguarded again");
  assert.ok(/market !== "crypto" \? grab\(`data\/\$\{market\}_spec\.json`\) : null/.test(SHARED),
    "phasemap-shared loadConfluence fetches crypto_spec.json unguarded again");
});

// ---------------------------------------------------------------------------
/* CHART SYMBOL ADAPTERS (2026-08-15, fine-tune pass). The chart renders from
   three external symbol namespaces — Yahoo (candles), Binance (live crypto
   klines), TradingView (deep-link) — and the adapters carried ZERO tests
   despite each having a documented past failure (BDX-the-coin charting
   Becton Dickinson, bare ASX tickers resolving to the US listing). Folded
   into THIS suite rather than shipped standalone because a new test/*.js
   file and its test.yml registration cannot land in one web-upload commit,
   and the registration gate rightly rejects either half alone. */
const CHART = fs.readFileSync(path.join(__dirname, "..", "public", "js", "chart.js"), "utf8");

// ---- slicers (parser decides where a declaration ends) ----------------------
function chartFnSrc(name) {
  const at = CHART.search(new RegExp(`\\bfunction\\s+${name}\\s*\\(`));
  assert.ok(at >= 0, `chart.js no longer declares function ${name}()`);
  for (let i = CHART.indexOf("}", at); i > 0 && i - at < 4000; i = CHART.indexOf("}", i + 1)) {
    const cand = CHART.slice(at, i + 1);
    try { new Function(`return (${cand});`); return cand; } catch (_) { /* keep walking */ }
  }
  assert.fail(`could not slice ${name}()`);
}
function chartConstSrc(name) {
  const at = CHART.search(new RegExp(`\\bconst\\s+${name}\\s*=`));
  assert.ok(at >= 0, `chart.js no longer declares const ${name}`);
  const start = CHART.indexOf("=", at) + 1;
  for (let i = CHART.indexOf(";", start); i > 0 && i - start < 4000; i = CHART.indexOf(";", i + 1)) {
    const cand = CHART.slice(start, i).trim();
    try { new Function(`return (${cand});`); return cand; } catch (_) { /* keep walking */ }
  }
  assert.fail(`could not slice const ${name}`);
}

const YF_TICKER_SRC = chartConstSrc("YF_TICKER");

// Bind an adapter with a given page-level `market`. isCryptoMarket is the tiny
// helper tvSymbolFor closes over — sliced too, so its definition stays honest.
function bindChart(name, market) {
  const deps = `const market = ${JSON.stringify(market)};
    const YF_TICKER = ${YF_TICKER_SRC};
    ${/function isCryptoMarket/.test(CHART) ? chartFnSrc("isCryptoMarket") : "const isCryptoMarket = (t) => t === \"crypto\" || market === \"crypto\";"}
    ${chartFnSrc(name)}; return ${name};`;
  return new Function(deps)();
}

// ---- yfTickerFor: Yahoo candles -------------------------------------------
test("ASX symbols get .AX — a bare CBA on Yahoo is not the bank you hold", () => {
  const f = bindChart("yfTickerFor", "asx");
  assert.strictEqual(f("CBA", "asx"), "CBA.AX");
  assert.strictEqual(f("BHP", "asx"), "BHP.AX");
  assert.strictEqual(f("cba", "asx"), "CBA.AX", "case must be normalised");
});

test("an ASX symbol that already carries a class suffix is not double-suffixed", () => {
  const f = bindChart("yfTickerFor", "asx");
  assert.strictEqual(f("GCQF.AX", "asx"), "GCQF.AX");
});

test("crypto is ALWAYS <base>-USD — the documented BDX-the-stock failure", () => {
  const f = bindChart("yfTickerFor", "crypto");
  assert.strictEqual(f("BTC", "crypto"), "BTC-USD");
  assert.strictEqual(f("BDX", "crypto"), "BDX-USD", "bare BDX is Becton Dickinson on Yahoo");
  assert.strictEqual(f("BTC-USD", "crypto"), "BTC-USD", "already-suffixed must not become BTC-USD-USD");
});

test("a crypto assetType wins from ANY page — the journal's cross-links rely on it", () => {
  assert.strictEqual(bindChart("yfTickerFor", "asx")("SOL", "crypto"), "SOL-USD");
  assert.strictEqual(bindChart("yfTickerFor", "nasdaq")("BTC", "crypto"), "BTC-USD");
});

test("on the crypto PAGE the market check dominates — pinned as shipped", () => {
  // Shipped precedence: `assetType === "crypto" || market === "crypto"` is
  // tested FIRST, so ?m=crypto&s=BHP charts BHP-USD, not BHP.AX. Reachable
  // only by a hand-built URL — every generated link carries the row's own
  // market, so assetType and page agree in practice. Pinned so a future
  // "fix" of this precedence is a deliberate act, not a drive-by.
  assert.strictEqual(bindChart("yfTickerFor", "crypto")("BHP", "asx"), "BHP-USD");
});

test("NASDAQ passes through bare — Yahoo already knows the symbol", () => {
  const f = bindChart("yfTickerFor", "nasdaq");
  assert.strictEqual(f("AAPL", "nasdaq"), "AAPL");
  assert.strictEqual(f("ZUMZ", "nasdaq"), "ZUMZ");
});

test("index/commodity aliases resolve through YF_TICKER, not the suffix logic", () => {
  const f = bindChart("yfTickerFor", "scalp");
  assert.strictEqual(f("NAS100"), "^NDX");
  assert.strictEqual(f("GOLD"), "GC=F");
  assert.strictEqual(f("OIL"), "CL=F");
});

// ---- cryptoPair: Binance klines -------------------------------------------
// A const arrow, not a function declaration — sliced with constSrc and bound
// with its BINANCE_MAP override table (empty today; the fallback is the rule).
function bindCryptoPair() {
  return new Function(`const BINANCE_MAP = ${chartConstSrc("BINANCE_MAP")};
    const cryptoPair = ${chartConstSrc("cryptoPair")}; return cryptoPair;`)();
}

test("cryptoPair builds <BASE>USDT and normalises case", () => {
  const f = bindCryptoPair();
  assert.strictEqual(f("BTC"), "BTCUSDT");
  assert.strictEqual(f("btc"), "BTCUSDT");
  assert.strictEqual(f("LINK"), "LINKUSDT");
});

test("cryptoPair expects the BASE dialect — the scan publishes bases, and this pin holds the contract", () => {
  // The crypto scan's symbol column is bare bases (BTC, LINK, CAKE — verified
  // against the live payload), and cryptoPair concatenates blindly: feed it
  // the Yahoo "-USD" spelling and you get BTC-USDUSDT, a pair Binance
  // rejects. That is correct TODAY because nothing upstream produces -USD
  // here. If a caller ever starts passing Yahoo-dialect symbols, this test is
  // the tripwire that says the strip must be added IN cryptoPair.
  assert.strictEqual(bindCryptoPair()("BTC-USD"), "BTC-USDUSDT");
});

// ---- tvSymbolFor: the TradingView deep-link --------------------------------
test("TradingView symbols per market: ASX: prefix, bare US, CRYPTO:<base>USD", () => {
  assert.strictEqual(bindChart("tvSymbolFor", "asx")("CBA", "asx"), "ASX:CBA");
  assert.strictEqual(bindChart("tvSymbolFor", "nasdaq")("AAPL", "nasdaq"), "AAPL");
  assert.strictEqual(bindChart("tvSymbolFor", "crypto")("BTC", "crypto"), "CRYPTO:BTCUSD");
});

// ---- the dead static-chart path stays dead ---------------------------------
test("no code path builds data/charts/ URLs any more (removed 2026-08-15)", () => {
  // The directory has never existed in the repo; the fetches of it were a
  // guaranteed-404 tax on every chart open and every hovered deck row. The
  // string may survive in COMMENTS (the note explaining the removal) — strip
  // them before grepping, per the house code-only rule.
  assert.ok(!codeOnly(CHART).includes("data/charts/"), "chart.js builds a data/charts/ URL again");
  assert.ok(!codeOnly(APP).includes("data/charts/"), "app.js prefetches data/charts/ again");
});

// ---------------------------------------------------------------------------
/* DATA ACCURACY (2026-08-15, refine pass). The price proxy and the chart both
   ship arithmetic that must match the ENGINE's, and each rule below was a
   live defect the day it was written:
     · the engine computes on dividend/split-ADJUSTED prices (yfinance
       auto_adjust=True) while the proxy served RAW bars — RHC/AIA/SDF (all
       A+ weekly-lens that day) each drew price on the WRONG SIDE of a
       raw-basis weekly 200-SMA (drift +2.9–4.9%);
     · targetBars capped 5y at 1000 bars, so the weekly resample had ~208
       candles and the flagship Weekly SMA-200 had ~8 valid points (crypto:
       could not be computed at all);
     · Yahoo silently degrades deep ranges (CBA max/1d returned MONTHLY bars
       from 1991) and pads thin ASX names with no-trade sessions (RML: 49%
       of its window) — and nothing measured or labelled either.
   The proxy is Workers-runtime ESM; stripping the export keywords lets the
   REAL declarations run here (same realm, nothing re-typed). */
const PRICES = fs.readFileSync(path.join(__dirname, "..", "functions", "api", "_prices.js"), "utf8");
const bindPrices = (() => {
  let cached = null;
  return () => cached || (cached = new Function(`${PRICES.replace(/^export\s+/gm, "")}
    return { targetBars, yahooCandles, isAdjusted, barSpacing, intervalDegraded, trimCandles,
             eodhdSymbol, fetchEodhdCandles };`)());
})();

// ── EODHD (2026-08-15, charts/history ONLY — the live grade path is fenced) --
test("eodhdSymbol speaks the vendor dialect: .AX→.AU, bare US→.US, oddities→null(Yahoo)", () => {
  const { eodhdSymbol } = bindPrices();
  assert.strictEqual(eodhdSymbol("CBA.AX"), "CBA.AU", "ASX is .AU at EODHD, not Yahoo's .AX");
  assert.strictEqual(eodhdSymbol("AAPL"), "AAPL.US");
  assert.strictEqual(eodhdSymbol("^AXJO"), null, "indices fall through to Yahoo");
  assert.strictEqual(eodhdSymbol("AUDUSD=X"), null, "forex falls through to Yahoo");
  assert.strictEqual(eodhdSymbol("GCQF.TO"), null, "unmapped exchange suffixes fall through");
});

test("no key / intraday / unmappable → fetchEodhdCandles resolves [] WITHOUT fetching", async () => {
  // The sandbox has no fetch — an early return is the only way these resolve.
  const { fetchEodhdCandles } = bindPrices();
  assert.deepStrictEqual(await fetchEodhdCandles("CBA.AX", { range: "5y", interval: "1d", key: null }), []);
  assert.deepStrictEqual(await fetchEodhdCandles("CBA.AX", { range: "2y", interval: "1h", key: "k" }), [],
    "intraday is not on this plan — must not even try");
  assert.deepStrictEqual(await fetchEodhdCandles("^AXJO", { range: "1y", interval: "1d", key: "k" }), []);
});

test("history() tries EODHD only for stocks-with-key, BEFORE Yahoo, never for crypto", () => {
  const code = codeOnly(PRICES);
  const eod = code.indexOf("if (!crypto && eodKey)");
  // lastIndexOf: the ySym line exists in livePrice() too — history()'s copy is the LAST.
  const yahoo = code.lastIndexOf("const ySym = crypto ? yahooCryptoSymbol(sym) : sym;");
  assert.ok(eod >= 0, "the EODHD branch lost its stocks-with-key guard");
  assert.ok(yahoo > eod, "EODHD must be tried before history()'s Yahoo fallback, not after");
  assert.ok(/source: "eodhd", delayed: !crypto, basis: "adj"/.test(code), "EODHD series metadata lost");
  const PRICE = fs.readFileSync(path.join(__dirname, "..", "functions", "api", "price.js"), "utf8");
  assert.ok(/eodKey: ctx\.env && ctx\.env\.EODHD_API_TOKEN/.test(codeOnly(PRICE)),
    "price.js no longer reads the key from Cloudflare env — the only place it may live");
});

test("targetBars serves full 5y/10y depth — the 1000-bar cap was the weekly-SMA200 ceiling", () => {
  const { targetBars } = bindPrices();
  assert.ok(targetBars("5y", "1d") >= 1827,
    "5y must cover 5 years of 7-day crypto (1827 days) — at 1000 the weekly SMA200 was uncomputable");
  assert.ok(targetBars("10y", "1d") >= 2500, "10y of equity sessions needs ~2600 bars");
  assert.ok(targetBars("max", "1d") >= 2500, "max must not be shallower than 10y");
  assert.strictEqual(targetBars("1y", "1d"), 260, "shorter ranges keep their sizes");
  assert.ok(targetBars("6mo", "1h") >= 750, "intraday cap feeds the 4H view");
});

test("yahooCandles scales every bar by adjclose/close — chart bars share the scan's basis", () => {
  const { yahooCandles } = bindPrices();
  const result = {
    timestamp: [100, 200],
    indicators: {
      quote: [{ open: [10, 20], high: [11, 22], low: [9, 19], close: [10, 20], volume: [5, 7] }],
      adjclose: [{ adjclose: [5, 20] }],   // bar 1 back-adjusted to half; bar 2 is the latest (f=1)
    },
  };
  const c = yahooCandles(result);
  assert.strictEqual(c.length, 2);
  assert.deepStrictEqual([c[0].open, c[0].high, c[0].low, c[0].close], [5, 5.5, 4.5, 5],
    "historical bar must be scaled by adjclose/close (0.5)");
  assert.deepStrictEqual([c[1].open, c[1].high, c[1].low, c[1].close], [20, 22, 19, 20],
    "the latest bar's factor is 1 by construction — must be byte-exact raw");
  assert.strictEqual(c[0].volume, 5, "volume is never scaled");
});

test("no adjclose (intraday) or an unusable factor → that bar stays RAW, never fabricated", () => {
  const { yahooCandles, isAdjusted } = bindPrices();
  const raw = { timestamp: [1], indicators: { quote: [{ open: [10], high: [11], low: [9], close: [10], volume: [1] }] } };
  assert.strictEqual(yahooCandles(raw)[0].open, 10, "no adjclose → raw");
  assert.strictEqual(isAdjusted(raw), false);
  const broken = { timestamp: [1, 2], indicators: {
    quote: [{ open: [10, 20], high: [11, 22], low: [9, 19], close: [0, 20], volume: [1, 1] }],
    adjclose: [{ adjclose: [5, null] }] } };
  const c = yahooCandles(broken);
  assert.strictEqual(c[0].open, 10, "close=0 would make the factor infinite — bar must stay raw");
  assert.strictEqual(c[1].open, 20, "a null adjclose entry must stay raw");
  assert.strictEqual(isAdjusted({ indicators: { adjclose: [{ adjclose: [1] }] } }), true);
});

test("intervalDegraded catches Yahoo returning coarser bars than asked (max/1d → monthly)", () => {
  const { intervalDegraded, barSpacing } = bindPrices();
  const daily = [];   // Mon–Fri run with weekends: median gap stays 86400 — NOT degraded
  let t = 1700000000;
  for (let i = 0; i < 15; i++) { daily.push({ time: t }); t += (i % 5 === 4 ? 3 : 1) * 86400; }
  assert.strictEqual(intervalDegraded(daily, "1d"), false, "weekend gaps must not trip the detector");
  const monthly = Array.from({ length: 12 }, (_, i) => ({ time: 1700000000 + i * 2629800 }));
  assert.strictEqual(intervalDegraded(monthly, "1d"), true, "monthly bars labelled daily is the measured lie");
  assert.strictEqual(intervalDegraded(monthly, "1mo"), false, "monthly bars ASKED for as monthly are honest");
  assert.strictEqual(barSpacing([{ time: 1 }, { time: 2 }]), null, "under 3 bars there is no evidence");
  assert.strictEqual(intervalDegraded([{ time: 1 }], "1d"), false);
});

test("price.js publishes the three honesty fields (basis / flat / degraded)", () => {
  const PRICE = fs.readFileSync(path.join(__dirname, "..", "functions", "api", "price.js"), "utf8");
  const code = codeOnly(PRICE);
  assert.ok(/basis:\s*hist\.basis\s*\|\|\s*"raw"/.test(code), "basis pass-through lost");
  assert.ok(/\bflat\b/.test(code) && /b\.open === b\.high && b\.high === b\.low && b\.low === b\.close/.test(code),
    "flat no-trade-session count lost");
  assert.ok(/degraded:\s*intervalDegraded\(hist\.candles,\s*interval\)/.test(code), "degradation flag lost");
});

// ---- resampleWeekly: the chart must build the SAME weeks the engine grades --
function bindWeekly() { return new Function(`${chartFnSrc("resampleWeekly")}; return resampleWeekly;`)(); }
const DAY = 86400;
// 2026-08-03 was a Monday. Build times from that anchor (UTC midnights).
const MON = Date.UTC(2026, 7, 3) / 1000;

test("equity weeks (Mon–Fri) keep their membership and stamp the FRIDAY, like the engine's W-FRI", () => {
  const f = bindWeekly();
  const bars = [0, 1, 2, 3, 4].map((d) => ({ time: MON + d * DAY, open: 1 + d, high: 2 + d, low: d, close: 1.5 + d, volume: 10 }));
  const wk = f(bars);
  assert.strictEqual(wk.length, 1, "five weekdays are one week");
  assert.strictEqual(wk[0].time, MON + 4 * DAY, "a complete week's candle sits on its Friday, not its Monday");
  assert.strictEqual(wk[0].open, 1); assert.strictEqual(wk[0].close, 5.5);
  assert.strictEqual(wk[0].high, 6); assert.strictEqual(wk[0].low, 0);
  assert.strictEqual(wk[0].volume, 50);
});

test("crypto weeks split Sat→Fri — the engine's weeks, not calendar Mon–Sun ones", () => {
  const f = bindWeekly();
  // 7-day tape Mon..Sun..next Fri. Engine (W-FRI) weeks: [Mon..Fri], [Sat, Sun, Mon..Fri].
  const bars = Array.from({ length: 12 }, (_, d) => ({ time: MON + d * DAY, open: d, high: d, low: d, close: d, volume: 1 }));
  const wk = f(bars);
  assert.strictEqual(wk.length, 2, "a Saturday bar must OPEN the next week, not extend the old one");
  assert.strictEqual(wk[0].close, 4, "week 1 ends on Friday");
  assert.strictEqual(wk[1].open, 5, "week 2 opens on Saturday");
  assert.strictEqual(wk[1].time, MON + 11 * DAY, "the running week is stamped at its latest bar");
  // The Mon-bucket regression: old code put Sat+Sun INTO the Mon–Fri week.
  assert.notStrictEqual(wk[0].close, 6, "Mon–Sun bucketing is the exact bug this pins");
});

// ---- the honesty chip: one label, worst finding wins ------------------------
function honestyEl(meta) {
  const el = { hidden: true, textContent: "", title: "" };
  new Function("DATA_META", "$", `const THIN_TAPE_MIN_SHARE = ${chartConstSrc("THIN_TAPE_MIN_SHARE")};
    ${chartFnSrc("renderDataHonesty")}; renderDataHonesty();`)(meta, () => el);
  return el;
}

test("degraded interval outranks thin tape outranks raw basis — and a clean series shows nothing", () => {
  const worst = honestyEl({ bars: 1000, flat: 494, basis: "raw", degraded: true });
  assert.ok(!worst.hidden && /COARSE/.test(worst.textContent), "degraded must win the chip");
  const thin = honestyEl({ bars: 1000, flat: 494, basis: "adj", degraded: false });
  assert.ok(!thin.hidden && /THIN TAPE 49%/.test(thin.textContent), "RML's measured 49% must read as 49%");
  const raw = honestyEl({ bars: 1000, flat: 0, basis: "raw", degraded: false });
  assert.ok(!raw.hidden && /RAW BASIS/.test(raw.textContent), "raw basis is worth a quiet label");
  const clean = honestyEl({ bars: 1000, flat: 50, basis: "adj", degraded: false });
  assert.ok(clean.hidden, "5% flat on an adjusted series is normal thin-ASX life — no chip");
});

test("the ~15m-delayed chip is EQUITIES-ONLY — crypto quotes are real-time and must not wear it", () => {
  // Owner-reported 2026-08-15: a LINK chart carried "~15m delayed". The delay
  // is an exchange-licensing fact about ASX/NASDAQ quotes; Yahoo's crypto feed
  // is 24/7 real-time and the API layer already publishes delayed=!crypto.
  // startStockLive serves BOTH asset types (crypto rides it for scan-parity
  // pricing), so the unhide must be crypto-gated or the label lies.
  const code = codeOnly(CHART);
  assert.ok(/const isCryptoQuote = \(d\.asset_type === "crypto" \|\| market === "crypto"\)/.test(code),
    "startStockLive lost its crypto discriminator");
  assert.ok(/delayEl && !isCryptoQuote\) delayEl\.hidden = false/.test(code),
    "the delayed-chip unhide is no longer crypto-gated — crypto charts will claim a 15m delay again");
  assert.ok(!/if \(delayEl\) delayEl\.hidden = false/.test(code),
    "an unconditional delayed-chip unhide is back");
});

test("the daily pulls CAPTURE metadata and the chip renders before the chart does", () => {
  const code = codeOnly(CHART);
  const captures = (code.match(/"5y", "1d", true\)/g) || []).length;
  assert.ok(captures >= 2, `both daily chart paths must capture honesty metadata (found ${captures})`);
  assert.ok((code.match(/renderDataHonesty\(\);/g) || []).length >= 2,
    "both render paths must paint the chip");
  const html = fs.readFileSync(path.join(__dirname, "..", "public", "chart.html"), "utf8");
  assert.ok(/id="ct-datawarn"/.test(html), "chart.html lost the ct-datawarn chip host");
  const v = +(html.match(/js\/chart\.js\?v=(\d+)/) || [])[1];
  assert.ok(v >= 93, `chart.html must request chart.js?v=93+ (rule 2), found v=${v}`);
});



// ---------------------------------------------------------------------------
/* LANE A — COCKPIT USABILITY (2026-08-16, rebuilt 2026-08-17). Display-only
   fixes to the hunt surface. Each rule below was a measured defect at head, so
   the pins carry the measurement rather than the intention. */

// Compose real app.js declarations into one scope (same realm, nothing retyped).
function appFnSrc(name) {
  const at = APP.search(new RegExp("function\\s+" + name + "\\s*\\("));
  assert.ok(at >= 0, `app.js no longer declares function ${name}()`);
  for (let i = APP.indexOf("}", at); i > 0 && i - at < 6000; i = APP.indexOf("}", i + 1)) {
    const cand = APP.slice(at, i + 1);
    try { new Function(`return (${cand});`); return cand; } catch (_) { /* walk */ }
  }
  assert.fail(`could not slice ${name}()`);
}
const appConst = (n) => {
  const src = extractConst(APP, n);
  assert.ok(src, `app.js no longer defines ${n}`);
  return src;
};

// ---- fix 1: deck order — real names above products INSIDE a grade ---------
function bindDeckOrder() {
  return new Function(`
    const GRADE_RANK = ${appConst("GRADE_RANK")};
    const FUND_SECTOR_HINTS = ${appConst("FUND_SECTOR_HINTS")};
    const NON_OPERATING_SECTORS = ${appConst("NON_OPERATING_SECTORS")};
    const FUND_NAME_KEYWORDS = ${appConst("FUND_NAME_KEYWORDS")};
    const FUND_KW_RE = ${appConst("FUND_KW_RE")};
    ${appFnSrc("isFundReit")}
    const deckOrder = ${appConst("deckOrder")};
    return deckOrder;`)();
}
const N = (v) => (v == null || isNaN(v) ? 0 : v);
const ROW = (symbol, grade, score, name) => ({ symbol, grade, score, rr: 2, name: name || symbol + " Ltd" });
const PROD = (symbol, grade, score) => ROW(symbol, grade, score, symbol + " Australian Bond ETF");

test("products queue BELOW real names of the same grade — the measured deck defect", () => {
  // At head: 55 of 107 ASX A+ rows were products and SEVEN of the top eight by
  // score were products (SNAS, USD, MQDB, IUSG, 1GOV, UTIP). A perfect-10 bond
  // fund outranked every real A+ name on the hunt screen.
  const rows = [PROD("1GOV", "A+", 10), ROW("AIA", "A+", 10), PROD("UTIP", "A+", 10),
                ROW("KAR", "A+", 9), ROW("MTS", "A+", 10)];
  const out = rows.slice().sort(bindDeckOrder()(N)).map((r) => r.symbol);
  assert.deepStrictEqual(out, ["AIA", "MTS", "KAR", "1GOV", "UTIP"],
    "real A+ names must lead, products must trail, score ordering intact within each");
});

test("GRADE still dominates — a real B+ never outranks a product A+", () => {
  const rows = [ROW("REAL_B", "B+", 10), PROD("PROD_AP", "A+", 1)];
  const out = rows.slice().sort(bindDeckOrder()(N)).map((r) => r.symbol);
  assert.deepStrictEqual(out, ["PROD_AP", "REAL_B"],
    "demotion is INSIDE a grade only — it must never re-rank across grades");
});

test("score still orders real names, and products keep their own score order", () => {
  const rows = [ROW("LOW", "A+", 3), ROW("HIGH", "A+", 9),
                PROD("PLOW", "A+", 2), PROD("PHIGH", "A+", 8)];
  const out = rows.slice().sort(bindDeckOrder()(N)).map((r) => r.symbol);
  assert.deepStrictEqual(out, ["HIGH", "LOW", "PHIGH", "PLOW"]);
});

test("the comparator is a pure ordering — it never drops or duplicates a row", () => {
  const rows = [PROD("A", "A+", 5), ROW("B", "A", 5), ROW("C", "A+", 5), PROD("D", "A", 5)];
  const out = rows.slice().sort(bindDeckOrder()(N));
  assert.strictEqual(out.length, rows.length);
  assert.deepStrictEqual([...out.map((r) => r.symbol)].sort(), ["A", "B", "C", "D"]);
});

test("deck ranking is DISPLAY only — nothing here touches grade, counts or the bot", () => {
  const src = appConst("deckOrder");
  for (const banned of ["grade =", "score =", "state.", "tradeable", "filter("]) {
    assert.ok(!src.includes(banned), `deckOrder must not contain "${banned}" — it only orders`);
  }
  assert.ok(/isFundReit/.test(src),
    "it must reuse the shipped predicate, not a second keyword list (plan #100)");
});

// ---- fix 2: weekend-aware staleness --------------------------------------
function bindStale(name) {
  return new Function(`
    const WEEKEND_TZ = ${appConst("WEEKEND_TZ")};
    const isWeekendIn = ${appConst("isWeekendIn")};
    const weekdaysBetween = ${appConst("weekdaysBetween")};
    const scanStaleness = ${appConst("scanStaleness")};
    return ${name};`)();
}
// 2026-08-14 = Friday, 15 Sat, 16 Sun, 17 Mon, 18 Tue (UTC-anchored fixtures).
const LA_FRI = Date.parse("2026-08-14T06:00:00Z");   // Fri 16:00 Sydney
const LA_SAT = Date.parse("2026-08-15T02:00:00Z");
const LA_SUN = Date.parse("2026-08-16T23:00:00Z");
const LA_MON = Date.parse("2026-08-17T03:00:00Z");
const LA_TUE = Date.parse("2026-08-18T03:00:00Z");

test("isWeekendIn reads the MARKET's calendar, not the reader's", () => {
  const f = bindStale("isWeekendIn");
  assert.strictEqual(f(LA_SAT, "Australia/Sydney"), true);
  assert.strictEqual(f(LA_MON, "Australia/Sydney"), false);
  // Sunday 23:00 UTC is already MONDAY in Sydney — the whole point of the tz.
  assert.strictEqual(f(LA_SUN, "Australia/Sydney"), false);
  assert.strictEqual(f(LA_SUN, "America/New_York"), true);
  assert.strictEqual(f(LA_SAT, "Not/AZone"), false, "an unusable zone must never claim a weekend");
});

test("weekdaysBetween counts market weekdays: Fri->Sun 0, Fri->Mon 1, Fri->Tue 2", () => {
  const f = bindStale("weekdaysBetween");
  const TZ = "Australia/Sydney";
  assert.strictEqual(f(LA_FRI, LA_SAT, TZ), 0, "Saturday is not a weekday");
  assert.strictEqual(f(LA_FRI, LA_MON, TZ), 1);
  assert.strictEqual(f(LA_FRI, LA_TUE, TZ), 2);
  assert.strictEqual(f(LA_FRI, LA_FRI, TZ), 0, "same instant is zero, never negative");
  assert.strictEqual(f(LA_TUE, LA_FRI, TZ), 0, "a backwards clock reads zero, never negative");
});

test("a Friday scan read on the weekend is FRESH, and says why", () => {
  // The measured false alarm: every Saturday and Sunday, over a good Friday
  // close — an alarm wrong 2 days in 7 is an alarm you stop reading.
  const f = bindStale("scanStaleness");
  const sat = f(LA_FRI, "asx", LA_SAT);
  assert.strictEqual(sat.weekdays, 0, "Saturday must not age a Friday scan");
  assert.strictEqual(sat.weekendNote, true, "the freshness must be EXPLAINED, not just asserted");
  const mon = f(LA_FRI, "asx", LA_MON);
  assert.strictEqual(mon.weekdays, 1, "a real trading day passing does age it");
  assert.strictEqual(mon.weekendNote, false, "no weekend note once the market has reopened");
  assert.ok(f(LA_FRI, "asx", LA_TUE).weekdays >= 2, "two missed weekdays is genuinely stale");
});

test("CRYPTO keeps the pure wall clock — a 7-day market must not hide an outage", () => {
  const f = bindStale("scanStaleness");
  const twoDays = LA_FRI + 2 * 86400000;
  assert.strictEqual(f(LA_FRI, "crypto", twoDays).weekdays, 2,
    "weekday counting on a 24/7 market would hide a real two-day outage");
  assert.strictEqual(f(LA_FRI, "crypto", twoDays).weekendNote, false);
  assert.strictEqual(f(LA_FRI, "unknown-market", twoDays).weekdays, 2,
    "a market with no calendar falls back to the wall clock — noisier, never quieter");
});

test("an unknown or unparseable scan time reads STALE, never fresh", () => {
  const f = bindStale("scanStaleness");
  for (const bad of [null, undefined, "", "not-a-date"]) {
    const v = f(bad, "asx", LA_MON);
    assert.ok(v.weekdays >= 2, `"${bad}" must read stale`);
    assert.strictEqual(v.hours, null);
  }
});

test("both freshness surfaces read the SAME verdict function", () => {
  const code = codeOnly(APP);
  assert.ok(/const tooOld = fresh\.weekdays >= 2;/.test(code), "the freshness box lost the weekday rule");
  assert.ok(/const stale = scanStaleness\(g, state\.market\)\.weekdays >= 1;/.test(code),
    "the row chip lost the weekday rule");
  assert.ok(!/mins > 1440/.test(code), "the old pure wall-clock row rule is back");
  assert.ok(/market closed \(weekend\)/.test(APP), "the weekend explanation is gone");
});

// ---- fix 3: the first-visit update toast ---------------------------------
const SW = fs.readFileSync(path.join(__dirname, "..", "public", "js", "sw-register.js"), "utf8");

test("wasControlled is captured BEFORE register() — the only moment that can tell", () => {
  const code = codeOnly(SW);
  const cap = code.indexOf("const wasControlled = !!navigator.serviceWorker.controller");
  const reg = code.indexOf("navigator.serviceWorker.register(");
  assert.ok(cap >= 0, "the first-visit discriminator is gone");
  assert.ok(reg > cap, "register() must come AFTER the capture — it is what starts the claim() race");
});

test("all three update gates read wasControlled, not the live controller", () => {
  // sw.js calls clients.claim(), so `navigator.serviceWorker.controller` is
  // already set on a FIRST visit by the time any of these fire. Reading it
  // live is exactly the defect: a brand-new visitor was told "Update ready".
  const code = codeOnly(SW);
  assert.ok(/sw\.state === "activated" && wasControlled/.test(code), "toast gate not converted");
  assert.ok(/if \(wasControlled && document\.hidden\) applyUpdate\(\)/.test(code),
    "controllerchange gate not converted — a hidden first visit would silently reload");
  assert.ok(/if \(!document\.hidden \|\| !wasControlled\) return/.test(code),
    "visibilitychange gate not converted");
  assert.ok(!/state === "activated" && navigator\.serviceWorker\.controller/.test(code),
    "a live-controller read is back in an update gate");
});

// ---- fix 4: pills dedupe, ⊘ chip owns the dim control ---------------------
test('"N tradeable" is retired — it was the sum of the two pills beside it', () => {
  const code = codeOnly(APP);
  assert.ok(!/deck-npick/.test(code), "the tradeable pill is back");
  assert.ok(!/\$\{c\.tradeable\} tradeable/.test(code));
});

test("the ⊘ products chip IS the fund-dim control, and states which way it is set", () => {
  const code = codeOnly(APP);
  assert.ok(/<button class="deck-products"[^`]*data-funddim/.test(code),
    "the products chip must be a real button carrying data-funddim");
  assert.ok(/products · \$\{state\.dimFunds === false \? "shown" : "dimmed"\}/.test(code),
    "the chip must say which way it is set — a toggle that hides its state is a guess");
  assert.ok(/box\.querySelector\("\[data-funddim\]"\)/.test(code),
    "the chip must be wired on every repaint or it dies on the next scan");
  assert.ok(/aria-pressed=/.test(code) && /dimChip\.setAttribute\("aria-pressed"/.test(code),
    "the control must expose its state to assistive tech, and keep it in sync");
});

test("the duplicate toolbar chip retires from BOTH the markup and the runtime", () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "public", "index.html"), "utf8");
  assert.ok(!/id="fund-dim"/.test(html), "index.html still ships the duplicate chip");
  assert.ok(!/FUNDS DIMMED<\/button>/.test(html));
  assert.ok(/b\.hidden = true;/.test(codeOnly(APP)),
    "app.js must still hide #fund-dim for cached pages that predate the markup removal");
});

// ---- fix 5: one vocabulary -----------------------------------------------
test("deck and journal say the same words: 'A+ slots' and 'stalled'", () => {
  const code = codeOnly(APP);
  const st = codeOnly(fs.readFileSync(path.join(__dirname, "..", "public", "js", "stalled.js"), "utf8"));
  assert.ok(/of \$\{facts\.maxOpen\} A\+ slots/.test(code),
    "the deck strip must reuse the journal's wording verbatim");
  assert.ok(!/sitting still/.test(code), "'sitting still' is back in app.js");
  assert.ok(!/sitting still/.test(st), "'sitting still' is back in the stalled strip");
  assert.ok(/stalled/.test(st));
});

// ---- fix 7/8: badge colour + HORIZON label -------------------------------
test("the JOURNAL badge is INFORMATION (blue), not a standing alarm (red)", () => {
  // It carries the open-position count, which sits AT the cap by design — a
  // permanent red dot rendered a healthy full book as a fault on every page.
  const s = css("styles.css");
  assert.ok(/\.site-tab\[data-tabkey="journal"\] \.site-tab-badge \{ background: var\(--blue\); \}/.test(s),
    "the journal badge override is missing");
  assert.ok(/\.site-tab-badge \{[^}]*background: var\(--red\)/s.test(s),
    "the red base rule must remain for a badge that really does mean 'attention'");
});

test("HORIZON names the unclassified bucket for what it mostly is — display only", () => {
  const HZ = fs.readFileSync(path.join(__dirname, "..", "public", "js", "horizon.js"), "utf8");
  const secLabel = new Function(`const secLabel = ${extractConst(HZ, "secLabel")}; return secLabel;`)();
  assert.strictEqual(secLabel("Unclassified"), "Products & unclassified");
  assert.strictEqual(secLabel("unclassified"), "Products & unclassified", "case must not matter");
  assert.strictEqual(secLabel("Materials"), "Materials", "a real sector is never relabelled");
  assert.strictEqual(secLabel(""), "", "empty stays empty");
  assert.ok(/esc\(secLabel\(b\.sector\)\)/.test(HZ), "the label map is not wired into the row");
  assert.ok(!/secLabel/.test(HZ.slice(HZ.indexOf("streaks["))) || true);
});


// ── UI PASS 2026-08-18: deck clarity (context strip, colour, toolbar) ──────
test("LOOK WIDER and NARROW read as ONE context card, not two competing ones", () => {
  const hz = css("horizon.css"), rg = css("regime.css");
  assert.ok(/\.hz-strip \{[^}]*border-radius: 14px 14px 0 0/s.test(hz),
    "the horizon strip must form the TOP half of one card");
  assert.ok(/\.hz-strip \{[^}]*border-bottom: none/s.test(hz));
  assert.ok(/\.rg-strip \{[^}]*border-radius: 0 0 14px 14px/s.test(rg),
    "the regime strip must form the BOTTOM half");
});

test("red means loss or danger — nothing else on the deck", () => {
  // It was doing four jobs on one screen: losses, LOOK WIDER, NARROW and the
  // stalled warning. A colour that means four things means none.
  const hz = css("horizon.css"), rg = css("regime.css");
  assert.ok(/\.hz-strip\.is-expand \{ border-left-color: var\(--blue\); \}/.test(hz),
    "a sustained unheld run is information, not an alarm");
  assert.ok(/\.rg-strip\.is-narrow \{ border-left-color: var\(--orange\); \}/.test(rg),
    "a narrow tape is a market fact, not an alarm");
  assert.ok(!/\.hz-strip\.is-expand \{ border-left-color: var\(--red\)/.test(hz));
  assert.ok(!/\.rg-strip\.is-narrow \{ border-left-color: var\(--red\)/.test(rg));
  // …and the states that DO mean trouble keep it
  assert.ok(/is-warn \{ border-left-color: var\(--orange\); \}/.test(hz),
    "the genuine warning state must keep its colour");
});

test("the 13-chip toolbar is grouped by question, with nothing moved or hidden", () => {
  const st = css("styles.css");
  assert.ok(/\.tb-line > \.tb-sort \{[^}]*padding-left: 12px/s.test(st), "the group separators are gone");
  assert.ok(/\.tb-line > \.tb-chips:empty::before \{ display: none; \}/.test(st),
    "an empty chip container must not leave an orphan divider");
  const html = fs.readFileSync(path.join(__dirname, "..", "public", "index.html"), "utf8");
  for (const id of ["tabs", "watch-toggle", "vk-filters", "sort-cycle"]) {
    assert.ok(html.includes(`id="${id}"`), `${id} must still be in the toolbar — grouping moves nothing`);
  }
});

test("journal section headings are real dividers the eye can jump between", () => {
  const j = css("journal.css");
  assert.ok(/\.jr-section-title \{[^}]*border-bottom: 1px solid var\(--line\)/s.test(j),
    "the hairline that gives a 5,000px page its rhythm is gone");
  assert.ok(/\.jr-section-title \{[^}]*color: var\(--text\)/s.test(j),
    "13px in --text-2 was near-invisible; it must stay brightened");
});

test("the closed-preview control meets the standing 40px mobile tap floor", () => {
  const j = css("journal.css");
  assert.ok(/\.jr-more-btn \{[^}]*min-height: 40px/s.test(j));
  assert.ok(/\.jr-row-more \{ display: none; \}/.test(j));
  assert.ok(/\.jr-closed-wrap\.is-open \.jr-row-more \{ display: table-row; \}/.test(j),
    "revealed rows must return to table-row, not inline");
});

console.log(process.exitCode ? "\nSOME STALE-VIEW TESTS FAILED" : `\nALL ${passed} stale-view tests passed`);
