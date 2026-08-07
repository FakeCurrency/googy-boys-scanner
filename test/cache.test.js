/* Unit tests for the dashboard SWR scan cache (public/js/cache.js, #97).
 *
 * Runs under plain node — installs a mock localStorage on globalThis and stubs
 * Date.now so TTL expiry is deterministic, then exercises the real module.
 */
"use strict";
const assert = require("assert");

// ---- mock localStorage (Map-backed, with an optional throw-on-set) ----------
function makeStorage() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)); },
    removeItem: (k) => { m.delete(k); },
    clear: () => m.clear(),
    _map: m,
  };
}
globalThis.localStorage = makeStorage();

// ---- controllable clock ------------------------------------------------------
let NOW = 1_000_000;
const realNow = Date.now;
Date.now = () => NOW;

const C = require("../public/js/cache.js");

let passed = 0;
const test = (name, fn) => {
  try { fn(); passed++; console.log("PASS  " + name); }
  catch (e) { console.error("FAIL  " + name + "\n      " + e.message); process.exitCode = 1; }
};
const reset = () => { globalThis.localStorage.clear(); NOW = 1_000_000; };

// ---- set / get roundtrip -----------------------------------------------------
test("set then get returns the same data", () => {
  reset();
  C.set("asx:aplus", { results: [{ symbol: "BHP" }], stat: 1 });
  assert.deepStrictEqual(C.get("asx:aplus"), { results: [{ symbol: "BHP" }], stat: 1 });
});

test("get returns null for a missing key", () => {
  reset();
  assert.strictEqual(C.get("nope"), null);
});

// ---- TTL expiry --------------------------------------------------------------
test("get returns data just under the 5-min TTL", () => {
  reset();
  C.set("k", { a: 1 });
  NOW += C.CACHE_TTL_MS - 1;                 // one ms under the window
  assert.deepStrictEqual(C.get("k"), { a: 1 });
});

test("get returns null once the TTL has elapsed", () => {
  reset();
  C.set("k", { a: 1 });
  NOW += C.CACHE_TTL_MS + 1;                 // just past the window
  assert.strictEqual(C.get("k"), null);
});

// ---- stale-while-revalidate --------------------------------------------------
test("getStale returns an EXPIRED payload that get() hides", () => {
  reset();
  C.set("k", { a: 2 });
  NOW += C.CACHE_TTL_MS * 10;                // long expired
  assert.strictEqual(C.get("k"), null, "get must hide the expired entry");
  assert.deepStrictEqual(C.getStale("k"), { a: 2 }, "getStale must still return it");
});

test("getStale returns null when nothing was ever cached", () => {
  reset();
  assert.strictEqual(C.getStale("k"), null);
});

// ---- head cache: strips heavy fields, caps rows, marks _head ------------------
test("setHead strips heavy per-row fields but keeps the rest", () => {
  reset();
  C.setHead("k", { generated_at: "t", results: [
    { symbol: "AAA", grade: "A+", confluence: { n: 2 }, spark: [1, 2, 3], detail: {}, plans: {}, analysis: "x", chips: [], entry_types: [], markers: [] },
  ] });
  const head = C.getHead("k");
  const row = head.results[0];
  assert.strictEqual(row.symbol, "AAA");
  assert.strictEqual(row.grade, "A+");
  assert.deepStrictEqual(row.confluence, { n: 2 }, "confluence must be kept (deck pill counts)");
  for (const heavy of ["spark", "detail", "plans", "analysis", "chips", "entry_types", "markers"]) {
    assert.ok(!(heavy in row), `${heavy} must be stripped from the head cache`);
  }
  assert.strictEqual(head._head, true);
  assert.strictEqual(head.generated_at, "t", "top-level scan fields survive");
});

test("setHead caps the head cache at HEAD_ROWS rows and records the full count", () => {
  reset();
  const many = Array.from({ length: C.HEAD_ROWS + 40 }, (_, i) => ({ symbol: "S" + i }));
  C.setHead("k", { results: many });
  const head = C.getHead("k");
  assert.strictEqual(head.results.length, C.HEAD_ROWS, "capped to HEAD_ROWS");
  assert.strictEqual(head._full_count, C.HEAD_ROWS + 40, "full count preserved");
});

test("getHead returns null for a missing key", () => {
  reset();
  assert.strictEqual(C.getHead("k"), null);
});

// ---- 500KB safety cap (protects the manual journal's localStorage quota) -----
test("set skips an oversized payload (never evicts the journal)", () => {
  reset();
  const huge = { results: [{ blob: "x".repeat(600_000) }] };
  C.set("big", huge);
  assert.strictEqual(C.get("big"), null, "oversized full payload must not be stored");
  assert.strictEqual(globalThis.localStorage.getItem(C.CACHE_PREFIX + "big"), null);
});

test("setHead also honours the 500KB cap", () => {
  reset();
  const huge = { results: [{ symbol: "A", note: "y".repeat(600_000) }] };
  C.setHead("big", huge);
  assert.strictEqual(C.getHead("big"), null, "oversized head payload must not be stored");
});

// ---- corruption resilience ---------------------------------------------------
test("get / getStale / getHead survive corrupt JSON in storage", () => {
  reset();
  globalThis.localStorage.setItem(C.CACHE_PREFIX + "bad", "{not json");
  globalThis.localStorage.setItem(C.HEAD_PREFIX + "bad", "]also broken[");
  assert.strictEqual(C.get("bad"), null);
  assert.strictEqual(C.getStale("bad"), null);
  assert.strictEqual(C.getHead("bad"), null);
});

// ---- head and full caches use distinct keys ----------------------------------
test("head and full caches do not collide", () => {
  reset();
  C.set("m", { results: [{ symbol: "FULL" }] });
  C.setHead("m", { results: [{ symbol: "HEAD" }] });
  assert.strictEqual(C.get("m").results[0].symbol, "FULL");
  assert.strictEqual(C.getHead("m").results[0].symbol, "HEAD");
});

// ---- ageMs: the real stored age, which `get` cannot express (TOP100 #78) -----
// app.js holds a payload in memory for as long as the tab lives, so it needs
// "how old is the copy I already have?" — a question `get` (fresh-enough-or-
// nothing) cannot answer. Without it, a payload read back out of localStorage
// four minutes old was stamped fresh and handed another full TTL.
test("ageMs reports the stored age, not zero", () => {
  reset();
  C.set("asx:vivek", { results: [] });
  assert.strictEqual(C.ageMs("asx:vivek"), 0);
  NOW += 4 * 60 * 1000;
  assert.strictEqual(C.ageMs("asx:vivek"), 4 * 60 * 1000);
});

test("ageMs keeps counting past the TTL, when get() has gone blind", () => {
  reset();
  C.set("k", { results: [] });
  NOW += 90 * 60 * 1000;
  assert.strictEqual(C.get("k"), null);                  // expired: get hides it
  assert.ok(C.getStale("k"), "getStale still has the payload");
  assert.strictEqual(C.ageMs("k"), 90 * 60 * 1000);      // ...and this says how old
});

test("ageMs is Infinity for a key that was never stored", () => {
  reset();
  assert.strictEqual(C.ageMs("never:seen"), Infinity);
});

test("ageMs is Infinity for an oversized payload the cache refused", () => {
  reset();
  // set() skips anything over 500KB, so there is no stored ts to age. Infinity
  // is the honest answer: app.js must not treat "not written" as "brand new".
  C.set("big", { results: [{ pad: "x".repeat(600000) }] });
  assert.strictEqual(C.get("big"), null);
  assert.strictEqual(C.ageMs("big"), Infinity);
});

test("ageMs survives corrupt or ts-less entries", () => {
  reset();
  globalThis.localStorage.setItem(C.CACHE_PREFIX + "bad", "{not json");
  globalThis.localStorage.setItem(C.CACHE_PREFIX + "nots", JSON.stringify({ data: { results: [] } }));
  assert.strictEqual(C.ageMs("bad"), Infinity);
  assert.strictEqual(C.ageMs("nots"), Infinity);
});

test("ageMs never goes negative when the clock steps backwards", () => {
  reset();
  C.set("k", { results: [] });
  NOW -= 60 * 1000;   // DST shift / NTP correction
  assert.strictEqual(C.ageMs("k"), 0);
});

// ── HTTP cache-busting: one asset, one version, across every page ───────────
// Added 2026-08-07 after finding this live. index.html asked for
// `js/horizon.js?v=6` while sectors.html still asked for `?v=5`, and the same
// for regime.js (v3 / v2). `public/_headers` puts /js/* and /css/* on
// `max-age=86400`, so sectors.html was pinning a 24-hour-stale body of two
// shared scripts — the exact failure the ?v= scheme exists to prevent, caused
// by the scheme itself being applied per-page.
//
// This lives in the cache suite because it IS a cache bug: nothing else in the
// repo checks an asset's version across pages, only that a version exists. A
// per-page check cannot see a skew by construction.
{
  const fs = require("fs");
  const path = require("path");
  const dir = path.resolve(__dirname, "../public");

  const versions = new Map();   // "js/horizon.js" -> Map(version -> [pages])
  for (const file of fs.readdirSync(dir).filter((f) => f.endsWith(".html"))) {
    const html = fs.readFileSync(path.join(dir, file), "utf8");
    for (const m of html.matchAll(/(?:src|href)="((?:js|css)\/[A-Za-z0-9._-]+)\?v=(\d+)"/g)) {
      if (!versions.has(m[1])) versions.set(m[1], new Map());
      const byV = versions.get(m[1]);
      if (!byV.has(m[2])) byV.set(m[2], []);
      byV.get(m[2]).push(file);
    }
  }

  test("no asset is requested at two different ?v= across pages", () => {
    const skewed = [];
    for (const [asset, byV] of versions) {
      if (byV.size > 1) {
        const detail = [...byV.entries()]
          .sort((a, b) => Number(b[0]) - Number(a[0]))
          .map(([v, pages]) => `v=${v} (${pages.join(", ")})`)
          .join("  vs  ");
        skewed.push(`${asset}: ${detail}`);
      }
    }
    assert.strictEqual(skewed.length, 0,
      "an asset is cache-busted to different versions on different pages, so the\n" +
      "      lower page pins a stale copy for max-age (86400s on /js/* and /css/*):\n        " +
      skewed.join("\n        "));
  });

  test("every versioned asset reference points at a file that exists", () => {
    const missing = [];
    for (const asset of versions.keys()) {
      if (!fs.existsSync(path.join(dir, asset))) missing.push(asset);
    }
    assert.strictEqual(missing.length, 0,
      "versioned reference(s) to files that do not exist: " + missing.join(", "));
  });

  test("the guard is actually looking at something", () => {
    // A regex that quietly stops matching would make both tests above pass
    // forever against any amount of skew.
    assert.ok(versions.size >= 10,
      `only ${versions.size} versioned assets found across public/*.html — the ` +
      "scan regex has probably stopped matching");
  });
}

Date.now = realNow;
console.log(process.exitCode ? "\nSOME CACHE TESTS FAILED" : `\nALL ${passed} cache tests passed`);
