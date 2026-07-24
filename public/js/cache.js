/* Vivek 5.0 — dashboard scan cache (extracted from app.js 2026-07-24, #97).
 *
 * The stale-while-revalidate cache layer, pulled into its own module so it can
 * be unit-tested (test/cache.test.js) with a mocked localStorage + clock. The
 * behaviour is byte-for-byte the same as the inline version app.js used; app.js
 * now aliases these (cacheSet = GBSCache.set, …).
 *
 *   set(key,data) / get(key)      — 5-min TTL full cache (get hides expired)
 *   getStale(key)                 — returns an EXPIRED full payload for the
 *                                   instant SWR cold paint
 *   setHead(key,data)/getHead     — slim always-written entry: stats + the
 *                                   first HEAD_ROWS rows with the heavy per-row
 *                                   fields stripped, so a >500KB market still
 *                                   paints instantly
 *
 * Storage + clock are read from the ambient globals (localStorage, Date.now),
 * so tests just install a mock localStorage on globalThis and stub Date.now.
 * Dual export: window.GBSCache in the browser, module.exports under node. */
(function () {
  "use strict";

  var CACHE_PREFIX = "gbs:cache:";
  var CACHE_TTL_MS = 5 * 60 * 1000;     // 5 min localStorage cache
  var HEAD_PREFIX  = "gbs:cache:head:";
  var HEAD_ROWS    = 60;

  function store() {
    try { return (typeof localStorage !== "undefined") ? localStorage : null; }
    catch (_) { return null; }
  }

  function set(key, data) {
    var s = store(); if (!s) return;
    try {
      var payload = JSON.stringify({ ts: Date.now(), data: data });
      // Size cap: full NASDAQ/ASX scans are 1-2MB each; three of them squeezed
      // localStorage's ~5MB origin quota and could make the manual journal's
      // save FAIL — a silently lost trade. Oversized scans skip the cache.
      if (payload.length > 500000) return;
      s.setItem(CACHE_PREFIX + key, payload);
    } catch (_) {}
  }

  function get(key) {
    var s = store(); if (!s) return null;
    try {
      var item = JSON.parse(s.getItem(CACHE_PREFIX + key) || "null");
      if (item && Date.now() - item.ts < CACHE_TTL_MS) return item.data;
    } catch (_) {}
    return null;
  }

  // Returns an EXPIRED full payload (get() hides those) so a cold paint can show
  // the last-known scan instantly while the fresh fetch runs in the background.
  function getStale(key) {
    var s = store(); if (!s) return null;
    try {
      var item = JSON.parse(s.getItem(CACHE_PREFIX + key) || "null");
      if (item && item.data) return item.data;
    } catch (_) {}
    return null;
  }

  function setHead(key, data) {
    var s = store(); if (!s) return;
    try {
      // Strip the heaviest per-row fields so more of a big NASDAQ payload fits
      // under the untouched 500KB cap; confluence is KEPT so the deck pills
      // don't flash a wrong count.
      var HEAVY = { spark: 1, detail: 1, plans: 1, analysis: 1, chips: 1, entry_types: 1, markers: 1 };
      var rows = (((data && data.results) || []).slice(0, HEAD_ROWS)).map(function (r) {
        var slim = {};
        for (var k in r) { if (Object.prototype.hasOwnProperty.call(r, k) && !HEAVY[k]) slim[k] = r[k]; }
        return slim;
      });
      var head = {};
      for (var kk in data) { if (Object.prototype.hasOwnProperty.call(data, kk)) head[kk] = data[kk]; }
      head.results = rows; head._head = true;
      head._full_count = ((data && data.results) || []).length;
      var payload = JSON.stringify({ ts: Date.now(), data: head });
      if (payload.length > 500000) return;   // same cap as set — never raised
      s.setItem(HEAD_PREFIX + key, payload);
    } catch (_) {}
  }

  function getHead(key) {
    var s = store(); if (!s) return null;
    try {
      var item = JSON.parse(s.getItem(HEAD_PREFIX + key) || "null");
      if (item && item.data) return item.data;
    } catch (_) {}
    return null;
  }

  var api = {
    set: set, get: get, getStale: getStale, setHead: setHead, getHead: getHead,
    CACHE_PREFIX: CACHE_PREFIX, CACHE_TTL_MS: CACHE_TTL_MS,
    HEAD_PREFIX: HEAD_PREFIX, HEAD_ROWS: HEAD_ROWS,
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window !== "undefined") window.GBSCache = api;
})();
