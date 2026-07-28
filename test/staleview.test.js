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

console.log(process.exitCode ? "\nSOME STALE-VIEW TESTS FAILED" : `\nALL ${passed} stale-view tests passed`);
