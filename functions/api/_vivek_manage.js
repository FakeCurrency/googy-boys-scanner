/* Shared VIVEK scale-out management — used by the cloud watcher (tick.js)
 * and unit-tested in CI (test/vivek_manage.test.js). Underscore files are
 * not routed by Cloudflare Pages, same as _prices.js. */

/* ── VIVEK scale-out management (parity with public/js/journal.js manage()) ───
 * A VIVEK trade (has stop + tp1) must NOT be full-closed at a single "target":
 * the rules book partials at TP1/TP2/TP3, trail the SL (break-even at TP1, TP1
 * at TP2) and close the remainder on the stop. Before this, a trade whose page
 * was closed got legacy handling — full exit at tp2, untrailed stop — so the
 * journal diverged from the rules whenever nobody had a chart open. The
 * constants mirror the client exactly; drift between the two = wrong P&L.   */
export const VK = {
  EQUITY: 10000, RISK_PCT: 0.35, RISK_MIN: 0.25, RISK_MAX: 0.5,
  LEVERAGE: { asx: 5, nasdaq: 5, crypto: 3 },
  SCALE: { long: [0.25, 0.50, 0.15], short: [0.50, 0.25, 0.15] },
  COMMISSION_BPS: { asx: 2, nasdaq: 1, crypto: 6, default: 2 },
  SLIPPAGE_BPS: { asx: 5, nasdaq: 4, crypto: 8, default: 5 },
};
export const isVivek = (t) => t && t.stop != null && t.tp1 != null;
export const vkMarket = (t) => {
  const a = t.market || t.asset_type;
  if (a === "crypto") return "crypto";
  if (a === "asx") return "asx";
  return "nasdaq";               // nasdaq + commodity/index use nasdaq-tier costs
};
export function vkSizeRiskUsd(market, entry, stop) {
  const riskPct = Math.min(Math.max(VK.RISK_PCT, VK.RISK_MIN), VK.RISK_MAX) / 100;
  const dist = Math.abs(entry - stop);
  if (!(dist > 0) || !(entry > 0)) return 0;
  let riskUsd = VK.EQUITY * riskPct;
  const maxN = VK.EQUITY * (VK.LEVERAGE[market] || VK.LEVERAGE.asx);
  if ((riskUsd / dist) * entry > maxN) riskUsd = (maxN / entry) * dist;
  return riskUsd;
}
export function vkInit(t) {
  const isLong = t.direction !== "short";
  if (!(t.risk > 0)) t.risk = Math.abs(t.entry - t.stop);
  if (t.risk_usd == null) t.risk_usd = vkSizeRiskUsd(vkMarket(t), t.entry, t.stop);
  if (!Array.isArray(t.scale)) t.scale = VK.SCALE[isLong ? "long" : "short"];
  if (!Array.isArray(t.exits)) t.exits = [];
  if (t.gross_r == null) t.gross_r = 0;
  if (t.booked_pct == null) t.booked_pct = 0;
  if (t.tp1_hit == null) { t.tp1_hit = false; t.tp2_hit = false; t.tp3_hit = false; }
}
export const vkR = (price, entry, risk, isLong) => (isLong ? price - entry : entry - price) / risk;
export function vkFinalize(t) {
  const m = vkMarket(t);
  const slip = (VK.SLIPPAGE_BPS[m] ?? VK.SLIPPAGE_BPS.default) / 1e4;
  const comm = (VK.COMMISSION_BPS[m] ?? VK.COMMISSION_BPS.default) / 1e4;
  let cp = t.entry * (slip + comm);
  for (const ex of t.exits) {
    const market = /^(stop|manual)/.test(ex.reason || "");
    cp += (ex.pct || 0) * (ex.price || t.entry) * (comm + (market ? slip : 0));
  }
  t.cost_r = +(cp / t.risk).toFixed(4);
  t.realized_r = +((t.gross_r || 0) - t.cost_r).toFixed(4);
}
// Returns "close" | "book" | false. np = {date, time} for close stamps.
export function manageVivek(t, px, np) {
  if (t.status !== "open" || px == null) return false;
  vkInit(t);
  const isLong = t.direction !== "short", risk = t.risk;
  if (!(risk > 0)) return false;
  let booked = false;

  const stopHit = isLong ? px <= t.stop : px >= t.stop;
  if (stopHit) {
    // Honest gap fill: never better than the stop.
    const fill = isLong ? Math.min(t.stop, px) : Math.max(t.stop, px);
    const remaining = +(1 - (t.booked_pct || 0)).toFixed(6);
    if (remaining > 1e-9) {
      t.exits.push({ reason: "stop", price: +fill.toFixed(8), pct: remaining, date: np.date });
      t.gross_r = +((t.gross_r || 0) + remaining * vkR(fill, t.entry, risk, isLong)).toFixed(4);
      t.booked_pct = 1;
    }
    t.status = "closed"; t.exit = +fill.toFixed(8);
    t.exit_date = np.date; t.exit_time = np.time;
    t.exit_reason = t.tp3_hit ? "target" : (t.tp1_hit ? "trail" : "stop");
    t.auto_closed = "stop"; t.closed_by = "cloud-watcher"; t.mtime = Date.now();
    vkFinalize(t);
    return "close";
  }

  const scale = t.scale;
  const reached = (lvl) => (isLong ? px >= lvl : px <= lvl);
  const valid = (lvl) => (isLong ? lvl > t.entry : lvl < t.entry);   // chased-entry guard
  const fav = (nsl, csl) => (isLong ? nsl > csl : nsl < csl);        // SL only in our favour
  const book = (name, lvl, pct) => {
    t.exits.push({ reason: name, price: +lvl.toFixed(8), pct, date: np.date });
    t.gross_r = +((t.gross_r || 0) + pct * vkR(lvl, t.entry, risk, isLong)).toFixed(4);
    t.booked_pct = +((t.booked_pct || 0) + pct).toFixed(6);
    booked = true;
  };
  if (!t.tp1_hit && t.tp1 != null && valid(t.tp1) && reached(t.tp1)) {
    t.tp1_hit = true; book("tp1", t.tp1, scale[0]);
    if (fav(t.entry, t.stop)) t.stop = t.entry;                      // SL → break-even
  }
  if (!t.tp2_hit && t.tp2 != null && valid(t.tp2) && reached(t.tp2)) {
    t.tp2_hit = true; book("tp2", t.tp2, scale[1]);
    if (t.tp1 != null && fav(t.tp1, t.stop)) t.stop = t.tp1;         // SL → locked structure
  }
  if (!t.tp3_hit && t.tp3 != null && valid(t.tp3) && reached(t.tp3)) {
    t.tp3_hit = true; book("tp3", t.tp3, scale[2]);
  }
  if (booked) { t.mtime = Date.now(); vkFinalize(t); return "book"; }
  return false;
}

