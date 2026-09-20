/* EYES store — shared by the deck (app.js) and the chart (chart.js).
 *
 * Owner, 2026-09-19: "Once ive clicked a chart under that window, that window
 * should no longer show that."
 * Owner, 2026-09-20: "that arrow back and forward; this should continue down
 * the chain of FOR MY EYES. So once i've clicked forward or back a few times it
 * marks off the LIST."
 *
 * So WHAT NEEDS MY EYES is a worklist you walk: open the first chip, then step
 * through with the chart's own arrows, and each name you land on comes off the
 * strip. Two pages have to agree about that, which is why this is one file
 * rather than a copy in each -- the repo has been bitten by mirror drift before
 * (MECHANICAL_EXITS in three files), and a chart that marks a name with a key
 * the deck does not read would silently do nothing at all.
 *
 * TWO PIECES OF STATE, both per viewer, both localStorage, both scoped to the
 * TRADING DAY (Melbourne):
 *   seen  — which names have been reviewed today.
 *   chain — the ordered ticker list the strip was showing when a chip was
 *           clicked, so the chart's arrows can walk exactly that order rather
 *           than the full 200-name deck.
 *
 * SCOPED TO THE DAY, NOT THE SCAN — and the first version got this wrong
 * (2026-09-20). It keyed both to the scan's generated_at, reasoning that a name
 * reviewed against yesterday's tape has not been reviewed against today's. That
 * argument is sound for a daily scan and wrong for this one: ASX re-scans
 * roughly hourly, so every refresh wiped the list and the owner watched names
 * he had just worked through reappear within the hour. A worklist that empties
 * itself every hour is not a worklist.
 *
 * The day is the unit that matches how this is actually used ("I went through
 * these today"), it is predictable, and it still resets — tomorrow, once.
 *
 * Every read and write is wrapped. A private window or blocked site data
 * degrades to "nothing is reviewed and there is no chain", which is the safe
 * direction: the strip shows everything and the arrows fall back to the deck.
 */
(function () {
  "use strict";

  var SEEN_KEY = "gbs:eyes_seen";
  var CHAIN_KEY = "gbs:eyes_chain";

  function read(k) {
    try { var r = localStorage.getItem(k); return r ? JSON.parse(r) : null; }
    catch (_) { return null; }
  }
  function write(k, v) {
    try { localStorage.setItem(k, JSON.stringify(v)); return true; }
    catch (_) { return false; }        // quota / private window — forget, never throw
  }

  var EYES = {
    SEEN_KEY: SEEN_KEY,
    CHAIN_KEY: CHAIN_KEY,

    /** Today in MELBOURNE, as YYYY-MM-DD. The scope for everything below.
     *  Melbourne rather than the device's zone so a trip abroad does not roll
     *  the worklist over in the middle of a session. Falls back to the local
     *  date if Intl is unavailable or throws. */
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

    /** {key: true} for this DAY, or {} once the day rolls over. */
    seen: function (day) {
      var o = read(SEEN_KEY);
      if (!o || o.stamp !== String(day || "")) return {};
      var out = {};
      for (var i = 0; i < (o.keys || []).length; i++) out[o.keys[i]] = true;
      return out;
    },

    /** Record one name as reviewed. Returns the updated map. */
    mark: function (market, ticker, day) {
      var m = EYES.seen(day);
      m[EYES.key(market, ticker)] = true;
      write(SEEN_KEY, { stamp: String(day || ""), keys: Object.keys(m) });
      return m;
    },

    reset: function () {
      try { localStorage.removeItem(SEEN_KEY); } catch (_) { /* nothing to clear */ }
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
