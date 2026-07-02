/* PHASEMAP shared helpers — used by phasemap.js (list) and phasemap-chart.js.
   Everything rendered comes straight from the scan snapshot — nothing freestyle. */
window.PM = (() => {
  "use strict";

  const fmtPrice = (x) => {
    if (x == null || !isFinite(x)) return "—";
    if (x >= 1000) return x.toLocaleString("en-AU", { maximumFractionDigits: 0 });
    if (x < 0.001) return x.toFixed(8).replace(/0+$/, "");
    if (x < 0.1) return x.toFixed(4);
    if (x < 2) return x.toFixed(3);
    return x.toFixed(2);
  };
  const fmtPct = (x) => (x == null ? "—" : (x * 100).toFixed(1) + "%");
  const fmtTurnover = (x) => {
    if (x == null) return "—";
    if (x >= 1e9) return "$" + (x / 1e9).toFixed(1) + "B";
    if (x >= 1e6) return "$" + (x / 1e6).toFixed(1) + "M";
    return "$" + Math.round(x / 1e3) + "k";
  };
  const esc = (s) => String(s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const SOURCE_LABELS = {
    box_high: "box high", box_low: "box low",
    equal_highs: "equal highs", equal_lows: "equal lows",
    prior_high: "prior high", prior_low: "prior low",
    yearly_open: "yearly open", quarterly_open: "quarterly open",
    monthly_open: "monthly open", prior_yearly_close: "prior yearly close",
    fib_ext_10: "fib ext 1.0–1.272", fib_ext_1618: "fib ext 1.618–2.0",
    sweep_wick: "sweep wick",
  };
  const srcText = (z) => (z.sources || []).map((s) => SOURCE_LABELS[s] || s).join(" + ");

  const BAND_CLASS = {
    TARGET: "pm-band-target",
    ENTRY_CONTINUATION: "pm-band-entry",
    INVALIDATION_HARD: "pm-band-kill",
    INVALIDATION_MOMENTUM: "pm-band-kill",
    DEMAND: "pm-band-trap",
    SUPPLY: "pm-band-trap",
  };
  const BAND_LABEL = {
    TARGET: "TARGET",
    ENTRY_CONTINUATION: "ENTRY",
    INVALIDATION_HARD: "HARD INVALID.",
    INVALIDATION_MOMENTUM: "50% INVALID.",
    DEMAND: "DEMAND",
    SUPPLY: "SUPPLY",
  };
  const zoneLabel = (z) =>
    z.type === "TARGET" ? z.id.toUpperCase() : (BAND_LABEL[z.type] || z.type);

  function ladderHTML(rec) {
    const close = rec.metrics && rec.metrics.close;
    const rows = rec.zones.map((z) => ({ kind: "zone", z, mid: (z.low + z.high) / 2 }));
    if (close != null) rows.push({ kind: "price", mid: close });
    rows.sort((a, b) => b.mid - a.mid);
    return rows.map((row) => {
      if (row.kind === "price") {
        return `<div class="pm-price-row">
          <span class="pm-price-label">${fmtPrice(close)}</span>
          <span class="pm-price-line"><span>CURRENT</span></span>
        </div>`;
      }
      const z = row.z;
      const cls = BAND_CLASS[z.type] || "pm-band-trap";
      const done = z.status === "CONSUMED" ? " pm-band-consumed"
        : z.status === "VIOLATED" ? " pm-band-violated" : "";
      const conf = z.confluence > 1 ? ` ×${z.confluence}` : "";
      return `<div class="pm-rung">
        <span class="pm-rung-prices">${fmtPrice(z.low)}–${fmtPrice(z.high)}</span>
        <span class="pm-band ${cls}${done}">
          <span class="pm-band-label">${esc(zoneLabel(z))}${conf}</span>
          <span class="pm-band-status">${esc(z.status)}</span>
          <span class="pm-band-sources">${esc(srcText(z))}</span>
        </span>
      </div>`;
    }).join("");
  }

  function metricsHTML(rec) {
    const m = rec.metrics || {};
    const bits = [];
    if (m.retrace_pct != null) bits.push(`retrace <b>${fmtPct(m.retrace_pct)}</b>`);
    if (m.dist_to_yearly_open_pct != null)
      bits.push(`vs yearly open <b>${fmtPct(m.dist_to_yearly_open_pct)}</b>`);
    const warn = rec.tags.includes("ILLIQUID");
    bits.push(`<span class="${warn ? "pm-metric-warn" : ""}">turnover <b>${fmtTurnover(m.avg_turnover_20d)}</b></span>`);
    if (m.sweep_date) bits.push(`swept <b>${esc(m.sweep_date)}</b>`);
    if (m.displacement_date) bits.push(`displaced <b>${esc(m.displacement_date)}</b>`);
    if (m.bars_in_box != null) bits.push(`in box <b>${m.bars_in_box} bars</b>`);
    return bits.map((b) => `<span>${b}</span>`).join("");
  }

  const TIER_CLASS = { "A+": "pm-tier-aplus", A: "pm-tier-a", Watch: "pm-tier-watch" };

  function headBadgesHTML(rec) {
    const long = rec.direction === "bullish";
    const tier = rec.tier
      ? `<span class="pm-tier ${TIER_CLASS[rec.tier] || ""}">${esc(rec.tier)}</span>` : "";
    const tags = rec.tags.map((t) => {
      const extra = t === "ILLIQUID" ? " pm-tag-illiquid" : t === "HALT_RISK" ? " pm-tag-halt" : "";
      return `<span class="pm-tag${extra}">${esc(t)}</span>`;
    }).join("");
    return `
      <span class="pm-dir ${long ? "pm-dir-long" : "pm-dir-short"}">${long ? "LONG" : "SHORT"}</span>
      <span class="pm-state pm-state-${esc(rec.state)}">${esc(rec.state.replace("_", " "))}</span>
      ${tier}
      <span class="pm-regime">${esc(rec.regime)}</span>
      ${tags}`;
  }

  /* read-aloud (Web Speech API) — degrades silently where unsupported */
  let speakingBtn = null;
  function toggleSpeak(btn, text) {
    const synth = window.speechSynthesis;
    if (!synth) return;
    if (speakingBtn === btn && synth.speaking) {
      synth.cancel();
      btn.classList.remove("is-speaking");
      speakingBtn = null;
      return;
    }
    synth.cancel();
    if (speakingBtn) speakingBtn.classList.remove("is-speaking");
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "en-AU";
    u.onend = u.onerror = () => { btn.classList.remove("is-speaking"); speakingBtn = null; };
    btn.classList.add("is-speaking");
    speakingBtn = btn;
    synth.speak(u);
  }

  return { fmtPrice, fmtPct, fmtTurnover, esc, srcText, zoneLabel,
           ladderHTML, metricsHTML, headBadgesHTML, toggleSpeak };
})();
