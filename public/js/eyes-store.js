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
 * SCAN they were formed against:
 *   seen  — which names have been reviewed. A new scan clears it, because a
 *           name reviewed against yesterday's tape has not been reviewed
 *           against today's.
 *   chain — the ordered ticker list the strip was showing when a chip was
 *           clicked, so the chart's arrows can walk exactly that order rather
 *           than the full 200-name deck.
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

    /** Market-scoped so an ASX LINK and a crypto LINK never collide. */
    key: function (market, ticker) {
      return String(market || "") + ":" + String(ticker || "").toUpperCase();
    },

    /** {key: true} for this scan, or {} when the stamp moved on. */
    seen: function (stamp) {
      var o = read(SEEN_KEY);
      if (!o || o.stamp !== String(stamp || "")) return {};
      var out = {};
      for (var i = 0; i < (o.keys || []).length; i++) out[o.keys[i]] = true;
      return out;
    },

    /** Record one name as reviewed. Returns the updated map. */
    mark: function (market, ticker, stamp) {
      var m = EYES.seen(stamp);
      m[EYES.key(market, ticker)] = true;
      write(SEEN_KEY, { stamp: String(stamp || ""), keys: Object.keys(m) });
      return m;
    },

    reset: function () {
      try { localStorage.removeItem(SEEN_KEY); } catch (_) { /* nothing to clear */ }
    },

    /** Remember the strip's order so the chart's arrows can walk it. */
    saveChain: function (market, stamp, tickers) {
      return write(CHAIN_KEY, {
        market: String(market || ""), stamp: String(stamp || ""),
        tickers: (tickers || []).map(function (t) { return String(t).toUpperCase(); }),
      });
    },

    /** The chain, but ONLY if it belongs to this market and this scan.
     *  A stale chain is no chain: stepping through yesterday's order on today's
     *  data would walk names that are no longer aligned. */
    chain: function (market, stamp) {
      var o = read(CHAIN_KEY);
      if (!o || o.market !== String(market || "") || o.stamp !== String(stamp || "")) return [];
      return Array.isArray(o.tickers) ? o.tickers : [];
    },
  };

  if (typeof window !== "undefined") window.EYES = EYES;
  if (typeof module !== "undefined" && module.exports) module.exports = EYES;
})();
