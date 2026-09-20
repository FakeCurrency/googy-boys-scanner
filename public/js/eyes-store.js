/* EYES store — shared by the deck (app.js) and the chart (chart.js).
 *
 * Owner, 2026-09-19: "Once ive clicked a chart under that window, that window
 * should no longer show that."
 * Owner, 2026-09-20: "that arrow back and forward; this should continue down
 * the chain of FOR MY EYES. So once i've clicked forward or back a few times it
 * marks off the LIST."
 * Owner, 2026-09-21 (phone screenshot): "what needs my eyes is still showing
 * on my mobile phone despite refreshing."
 *
 * So WHAT NEEDS MY EYES is a worklist you walk: open the first chip, then step
 * through with the chart's own arrows, and each name you land on comes off the
 * strip. Two pages have to agree about that, which is why this is one file
 * rather than a copy in each -- the repo has been bitten by mirror drift before
 * (MECHANICAL_EXITS in three files), and a chart that marks a name with a key
 * the deck does not read would silently do nothing at all.
 *
 * TWO PIECES OF STATE:
 *   seen  — which names have been reviewed. A 7-DAY WINDOW per name, and it
 *           FOLLOWS THE OWNER ACROSS DEVICES: the map lives inside the synced
 *           journal store (gbs-sync.js, `eyes_seen`), so with a sync code set
 *           a name reviewed on the desktop is gone from the phone on its next
 *           sync, and a name stays reviewed until the window passes — not
 *           until midnight. localStorage is the fallback when the sync layer
 *           is not on the page.
 *   chain — the ordered ticker list the strip was showing when a chip was
 *           clicked, so the chart's arrows can walk exactly that order rather
 *           than the full 200-name deck. Per device, per Melbourne day: an
 *           order from yesterday would walk names no longer aligned.
 *
 * THE SCOPE HAS BEEN WRONG TWICE, and both lessons are kept here:
 *   v1 (2026-09-20) keyed `seen` to the scan's generated_at. ASX re-scans
 *      roughly hourly, so every refresh wiped the list and the owner watched
 *      names he had just worked through reappear within the hour.
 *   v2 (2026-09-20) keyed it to the Melbourne DAY, per device. The owner
 *      reviewed the list, and the next morning — on his phone — it was all
 *      back: a device that had never seen the marks, plus a midnight reset.
 *   v3 (this file): a name is reviewed for SEEN_DAYS (7) from the moment
 *      it was opened, on every device that shares the sync store. Same window
 *      the morning digest uses for the same reason — a weekly setup persists
 *      for days and re-showing it daily is noise, not news. `reset()` brings
 *      everything back and is itself synced (a reset stamp; marks older than
 *      it do not count), so a restore on one device is a restore everywhere.
 *
 * Every read and write is wrapped. A private window or blocked site data
 * degrades to "nothing is reviewed and there is no chain", which is the safe
 * direction: the strip shows everything and the arrows fall back to the deck.
 */
(function () {
  "use strict";

  var SEEN_KEY = "gbs:eyes_seen";          // localStorage fallback (no sync layer)
  var CHAIN_KEY = "gbs:eyes_chain";
  var SEEN_DAYS = 7;
  var DAY_MS = 86400000;

  function read(k) {
    try { var r = localStorage.getItem(k); return r ? JSON.parse(r) : null; }
    catch (_) { return null; }
  }
  function write(k, v) {
    try { localStorage.setItem(k, JSON.stringify(v)); return true; }
    catch (_) { return false; }        // quota / private window — forget, never throw
  }
  function sync() {
    try { return (typeof window !== "undefined" && window.GBSSync) || null; }
    catch (_) { return null; }
  }

  // {marks: {key: ts}, reset: ts} — from the synced store when it is on the
  // page, else the localStorage fallback. Never throws.
  function loadSeen() {
    var s = sync();
    if (s) {
      try {
        var d = s.load();
        return { marks: (d && d.eyes_seen) || {}, reset: (d && d.eyes_reset) || 0, store: d };
      } catch (_) { /* fall through to local */ }
    }
    var o = read(SEEN_KEY) || {};
    return { marks: o.marks || {}, reset: o.reset || 0, store: null };
  }
  function saveSeen(state) {
    var s = sync();
    if (s && state.store) {
      try {
        state.store.eyes_seen = state.marks;
        state.store.eyes_reset = state.reset;
        s.saveLocal(state.store);
        s.syncOutDebounced();
        return true;
      } catch (_) { /* fall through to local */ }
    }
    return write(SEEN_KEY, { marks: state.marks, reset: state.reset });
  }

  var EYES = {
    SEEN_KEY: SEEN_KEY,
    CHAIN_KEY: CHAIN_KEY,
    SEEN_DAYS: SEEN_DAYS,
    /** Overridable clock, so tests can move time without faking Date. */
    now: function () { return Date.now(); },

    /** Today in MELBOURNE, as YYYY-MM-DD. Scopes the CHAIN only. Melbourne
     *  rather than the device's zone so a trip abroad does not roll the
     *  chain over mid-session. Falls back to the local date if Intl throws. */
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

    /** {key: true} for every name reviewed inside the window. The `day`
     *  argument is accepted for the callers' sake and ignored: the window
     *  is what scopes this now, not the calendar. */
    seen: function (_day) {
      var st = loadSeen();
      var now = EYES.now();
      var out = {};
      for (var k in st.marks) {
        if (!Object.prototype.hasOwnProperty.call(st.marks, k)) continue;
        var ts = Number(st.marks[k]) || 0;
        if (ts <= st.reset) continue;                    // restored since
        if (now - ts > SEEN_DAYS * DAY_MS) continue;     // window passed
        out[k] = true;
      }
      return out;
    },

    /** Record one name as reviewed, now. Returns the updated map. */
    mark: function (market, ticker, _day) {
      var st = loadSeen();
      var now = EYES.now();
      var marks = {};
      // prune while we are here, so the synced map cannot grow without bound
      for (var k in st.marks) {
        if (!Object.prototype.hasOwnProperty.call(st.marks, k)) continue;
        var ts = Number(st.marks[k]) || 0;
        if (ts > st.reset && now - ts <= SEEN_DAYS * DAY_MS) marks[k] = ts;
      }
      // strictly after any reset stamp, or a mark made in the same millisecond
      // as a restore would be discounted by it
      marks[EYES.key(market, ticker)] = Math.max(now, (Number(st.reset) || 0) + 1);
      st.marks = marks;
      saveSeen(st);
      return EYES.seen();
    },

    /** Bring everything back, everywhere: a reset STAMP, so it syncs the same
     *  way a mark does and a mark from before it no longer counts. */
    reset: function () {
      var st = loadSeen();
      st.reset = EYES.now();
      st.marks = {};
      saveSeen(st);
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
