/* EYES store — shared by the deck (app.js) and the chart (chart.js).
 *
 * Owner, 2026-09-19: "Once ive clicked a chart under that window, that window
 * should no longer show that."
 * Owner, 2026-09-20: "that arrow back and forward; this should continue down
 * the chain of FOR MY EYES. So once i've clicked forward or back a few times it
 * marks off the LIST."
 * Owner, 2026-09-21: "how many times am i going to have to see the same shit
 * again and again?"
 *
 * WHAT NEEDS MY EYES is a worklist you walk: open a chip, step through with the
 * chart's arrows, and each name you land on comes off the strip. Two pages have
 * to agree about that, which is why this is one file rather than a copy in each
 * -- the repo has been bitten by mirror drift before (MECHANICAL_EXITS in three
 * files), and a chart marking a name under a key the deck does not read would
 * look like it worked and do nothing.
 *
 * DISMISSED UNTIL IT CHANGES — the rule, and the third attempt at it.
 *   v1 (2026-09-20) keyed the reviewed set to the scan's generated_at. ASX
 *      re-scans hourly, so every refresh wiped the list and names the owner had
 *      just worked through came back within the hour.
 *   v2 (2026-09-20) keyed it to the Melbourne DAY. Midnight brought everything
 *      back, on every device, every night.
 *   v3 (2026-09-20) made it a 7-day window. Still a treadmill: a weekly setup
 *      that sits aligned for a fortnight re-appeared on day 8 having done
 *      nothing, and 16 names meant 16 chart opens to clear a list that refills.
 *   v4 (THIS FILE, owner-ruled): a dismissal lasts until the name's ALIGNMENT
 *      MATERIALLY CHANGES. Each mark stores a FINGERPRINT of why the name was
 *      on the strip; the name returns only when today's fingerprint differs.
 *      Same setup for three weeks = you see it once. A dual that becomes a
 *      triple, or flips direction, or is upgraded to A+, is new information and
 *      comes back. That is an inbox, not a treadmill.
 *
 * THE FINGERPRINT IS DELIBERATELY NARROW — lenses + direction + VIVEK grade
 * (app.js `eyesFingerprint`). PhaseMap's state advancing SWEPT -> DISPLACED ->
 * RUNNING is real movement but it churns on its own, and re-surfacing on it
 * would walk straight back into the complaint this version exists to answer.
 * If that turns out to be too tight, widening it is one string.
 *
 * `"*"` IS THE UNKNOWN FINGERPRINT, and it is what makes this survivable. The
 * chart marks a name on arrival without knowing why it was aligned, and the
 * migration below inherits marks made before fingerprints existed. Both store
 * `"*"`, which matches ANY current state (so nothing already reviewed comes
 * back), and the deck UPGRADES it to the real fingerprint the next time it
 * renders that name — so it tracks changes from then on.
 *
 * PER DEVICE, by owner ruling 2026-09-21: the synced journal store was deleted
 * with the manual journal, and the sync pill had always read "Local only"
 * anyway (no sync code was ever set), so the cross-device promise v3 made was
 * never actually being kept. localStorage only. A private window or blocked
 * site data degrades to "nothing is dismissed and there is no chain", which is
 * the safe direction: the strip shows everything, the arrows fall back.
 */
(function () {
  "use strict";

  var SEEN_KEY = "gbs:eyes_seen";
  var CHAIN_KEY = "gbs:eyes_chain";
  var UNKNOWN = "*";           // dismissed, but we do not know at what state
  var MAX_MARKS = 400;         // bounded memory; oldest dropped first
  var MAX_AGE_DAYS = 90;       // garbage collection only, not a re-surface timer
  var DAY_MS = 86400000;

  function read(k) {
    try { var r = localStorage.getItem(k); return r ? JSON.parse(r) : null; }
    catch (_) { return null; }
  }
  function write(k, v) {
    try { localStorage.setItem(k, JSON.stringify(v)); return true; }
    catch (_) { return false; }        // quota / private window — forget, never throw
  }

  /* Read the mark map, MIGRATING whatever shape is on disk.
   *
   * Three shapes have shipped and all three are honoured, because the whole
   * point of this version is that the owner stops losing work he has already
   * done — losing it once (v2 -> v3 shipped with no migration and every
   * reviewed name came back) is what produced the complaint.
   *
   *   v1  {stamp, keys: [k, ...]}        -> each key at UNKNOWN
   *   v2/v3 {marks: {k: ts}, reset}      -> each key at UNKNOWN, ts kept
   *   v4  {marks: {k: {f, t}}}           -> as-is
   */
  function loadMarks() {
    var o = read(SEEN_KEY);
    var now = Date.now();
    var out = {};
    if (!o || typeof o !== "object") return out;
    if (Array.isArray(o.keys)) {                       // v1
      for (var i = 0; i < o.keys.length; i++) out[o.keys[i]] = { f: UNKNOWN, t: now };
      return out;
    }
    var m = o.marks;
    if (!m || typeof m !== "object") return out;
    for (var k in m) {
      if (!Object.prototype.hasOwnProperty.call(m, k)) continue;
      var v = m[k];
      if (typeof v === "number") out[k] = { f: UNKNOWN, t: v };            // v2/v3
      else if (v && typeof v === "object")                                  // v4
        out[k] = { f: typeof v.f === "string" ? v.f : UNKNOWN, t: Number(v.t) || now };
    }
    return out;
  }

  function saveMarks(marks) {
    var now = Date.now();
    var keys = [];
    for (var k in marks) {
      if (!Object.prototype.hasOwnProperty.call(marks, k)) continue;
      if (now - (Number(marks[k].t) || 0) > MAX_AGE_DAYS * DAY_MS) continue;
      keys.push(k);
    }
    // Newest first, then cap. Age is the right axis for eviction: the oldest
    // dismissal is the one whose name is least likely to still be aligned.
    keys.sort(function (a, b) { return (Number(marks[b].t) || 0) - (Number(marks[a].t) || 0); });
    var kept = {};
    for (var i = 0; i < keys.length && i < MAX_MARKS; i++) kept[keys[i]] = marks[keys[i]];
    return write(SEEN_KEY, { marks: kept });
  }

  var EYES = {
    SEEN_KEY: SEEN_KEY,
    CHAIN_KEY: CHAIN_KEY,
    UNKNOWN: UNKNOWN,
    MAX_MARKS: MAX_MARKS,

    /** Today in MELBOURNE, as YYYY-MM-DD. Scopes the CHAIN only — the
     *  dismissals are scoped by fingerprint, not by any calendar. Melbourne
     *  rather than the device's zone so a trip abroad does not roll the chain
     *  over mid-session. Falls back to the local date if Intl throws. */
    day: function () {
      try {
        return new Intl.DateTimeFormat("en-CA", { timeZone: "Australia/Melbourne" })
          .format(new Date());
      } catch (_) {
        var d = new Date();
        return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
               "-" + String(d.getDate()).padStart(2, "0");
      }
    },

    /** Market-scoped so an ASX LINK and a crypto LINK never collide. */
    key: function (market, ticker) {
      return String(market || "") + ":" + String(ticker || "").toUpperCase();
    },

    /** Every dismissal, as {key: fingerprint}. */
    marks: function () {
      var m = loadMarks(), out = {};
      for (var k in m) if (Object.prototype.hasOwnProperty.call(m, k)) out[k] = m[k].f;
      return out;
    },

    /** Is this name dismissed AT ITS CURRENT STATE?
     *  UNKNOWN matches anything — see the header. */
    isDismissed: function (market, ticker, fingerprint) {
      var f = EYES.marks()[EYES.key(market, ticker)];
      if (f === undefined) return false;
      return f === UNKNOWN || f === String(fingerprint == null ? UNKNOWN : fingerprint);
    },

    /** Dismiss one name. An absent fingerprint stores UNKNOWN — which is what
     *  the chart does, since it knows the name but not why it was aligned. */
    mark: function (market, ticker, fingerprint) {
      return EYES.markAll(market, [{ ticker: ticker, fp: fingerprint }]);
    },

    /** Dismiss several at once — the strip's "clear all". */
    markAll: function (market, items) {
      var m = loadMarks(), now = Date.now();
      (items || []).forEach(function (it) {
        if (!it || !it.ticker) return;
        m[EYES.key(market, it.ticker)] =
          { f: it.fp == null ? UNKNOWN : String(it.fp), t: now };
      });
      saveMarks(m);
      return EYES.marks();
    },

    /** Fill in the real fingerprint for marks stored as UNKNOWN, WITHOUT
     *  touching their timestamp or un-dismissing anything. The deck calls this
     *  for the names it can see, so a mark made by the chart (or inherited from
     *  an older build) starts tracking changes from the next render on.
     *  Returns how many were upgraded, so a caller can skip the write. */
    upgrade: function (market, items) {
      var m = loadMarks(), n = 0;
      (items || []).forEach(function (it) {
        if (!it || !it.ticker || it.fp == null) return;
        var k = EYES.key(market, it.ticker);
        if (m[k] && m[k].f === UNKNOWN) { m[k] = { f: String(it.fp), t: m[k].t }; n++; }
      });
      if (n) saveMarks(m);
      return n;
    },

    /** Bring everything back. */
    reset: function () {
      try { localStorage.removeItem(SEEN_KEY); return true; }
      catch (_) { return false; }
    },

    /** Remember the strip's order so the chart's arrows can walk it. */
    saveChain: function (market, day, tickers) {
      return write(CHAIN_KEY, {
        market: String(market || ""), stamp: String(day || ""),
        tickers: (tickers || []).map(function (t) { return String(t).toUpperCase(); }),
      });
    },

    /** The chain, but ONLY if it belongs to this market and today.
     *  Yesterday's order is no chain: it would walk names that have since
     *  stopped being aligned. */
    chain: function (market, day) {
      var o = read(CHAIN_KEY);
      if (!o || o.market !== String(market || "") || o.stamp !== String(day || "")) return [];
      return Array.isArray(o.tickers) ? o.tickers : [];
    },
  };

  if (typeof window !== "undefined") window.EYES = EYES;
  if (typeof module !== "undefined" && module.exports) module.exports = EYES;
})();
