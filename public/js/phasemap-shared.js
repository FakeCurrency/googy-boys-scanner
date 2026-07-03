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

  /* REIT / ETF / LIC / managed fund — mirrors chart.js isFundReit so the same
     names get flagged on cards and charts alike. */
  const FUND_NAME_KW = ["REIT", "TRUST", "FUND", "ETF", "SPDR", "ISHARES",
    "VANGUARD", "BETASHARES", "VANECK", "GLOBAL X"];
  const FUND_SECTOR_HINTS = ["reit", "real estate investment trust"];
  const NON_OP_SECTORS = ["not applicable", "not applic", "n/a"];
  function isFundReit(rec) {
    const sector = String(rec.sector || "").trim().toLowerCase();
    if (FUND_SECTOR_HINTS.some((h) => sector.includes(h))) return true;
    if (NON_OP_SECTORS.includes(sector)) return true;
    const name = String(rec.name || rec.ticker || "").toUpperCase();
    return FUND_NAME_KW.some((kw) => name.includes(kw));
  }

  function identityHTML(rec) {
    const bits = [];
    if (rec.name && rec.name !== rec.ticker) bits.push(esc(rec.name));
    if (rec.sector) bits.push(`<span class="pm-sector">${esc(rec.sector)}</span>`);
    const fund = isFundReit(rec)
      ? `<span class="pm-tag pm-tag-fund">FUND / REIT</span>` : "";
    if (!bits.length && !fund) return "";
    return `<div class="pm-identity">${bits.join(" · ")} ${fund}</div>`;
  }

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

  /* ── Watchlist (VIVEK + PhaseMap + Specs, ONE synced store) ─────────────
     Starring stores a SNAPSHOT of the record, so a name stays monitorable
     even after it drops out of the scan. Since 2026-07-03 the store lives
     INSIDE the GBSSync journal object (localStorage `gbs:manual_journal`,
     mirrored to Cloudflare KV when a sync code is set) — stars follow you
     from desktop to phone exactly like paper trades do. Keys:
     "<lens>:<market>:<TICKER>"; un-stars are tombstones so they propagate. */
  const LEGACY_LENS_KEY = "gbs-lens-watchlist";
  const LEGACY_VIVEK_KEY = "gbs:watch";
  const MIGRATED_KEY = "gbs:watch_migrated_v1";

  function _sync() { return window.GBSSync || null; }

  function _migrateOnce(d) {
    try {
      if (localStorage.getItem(MIGRATED_KEY)) return d;
      const now = Date.now();
      // old lens store: { ns: { market: { TICKER: {snap, date} } } }
      try {
        const old = JSON.parse(localStorage.getItem(LEGACY_LENS_KEY) || "{}");
        for (const [ns, mkts] of Object.entries(old || {})) {
          for (const [mkt, ticks] of Object.entries(mkts || {})) {
            for (const [t, e] of Object.entries(ticks || {})) {
              const k = `${ns}:${mkt}:${t}`;
              if (!d.watchlists[k]) d.watchlists[k] =
                { snap: (e && e.snap) || null, date: (e && e.date) || "", mtime: now };
            }
          }
        }
      } catch (_) {}
      // old VIVEK star set: [ "market:SYM", ... ]
      try {
        const old = JSON.parse(localStorage.getItem(LEGACY_VIVEK_KEY) || "[]");
        for (const mk of old || []) {
          const i = String(mk).indexOf(":");
          if (i > 0) {
            const k = `vivek:${mk.slice(0, i)}:${mk.slice(i + 1)}`;
            if (!d.watchlists[k]) d.watchlists[k] =
              { snap: null, date: "", mtime: now };
          }
        }
      } catch (_) {}
      localStorage.setItem(MIGRATED_KEY, "1");
      const s = _sync();
      if (s) { s.saveLocal(d); s.syncOutDebounced(); }
    } catch (_) {}
    return d;
  }

  function _store() {
    const s = _sync();
    if (!s) return { watchlists: {} };            // no sync layer on this page
    return _migrateOnce(s.load());
  }

  const watch = {
    map(ns, market) {
      const pre = `${ns}:${market}:`;
      const out = {};
      for (const [k, v] of Object.entries(_store().watchlists)) {
        if (k.startsWith(pre) && v && !v.del) out[k.slice(pre.length)] = v;
      }
      return out;
    },
    has(ns, market, ticker) { return !!this.map(ns, market)[ticker]; },
    count(ns, market) { return Object.keys(this.map(ns, market)).length; },
    toggle(ns, market, ticker, snap) {
      const s = _sync();
      if (!s) return false;
      const d = _store();
      const k = `${ns}:${market}:${ticker}`;
      const live = d.watchlists[k] && !d.watchlists[k].del;
      d.watchlists[k] = live
        ? { del: Date.now() }
        : { snap: snap || null, date: new Date().toISOString().slice(0, 10),
            mtime: Date.now() };
      s.saveLocal(d);
      s.syncOutDebounced();
      return !live;
    },
    refresh(ns, market, ticker, snap) {   // keep the stored snapshot current
      const s = _sync();
      if (!s) return;
      const d = _store();
      const k = `${ns}:${market}:${ticker}`;
      const e = d.watchlists[k];
      if (e && !e.del) { e.snap = snap; s.saveLocal(d); }
    },
  };

  /* ── Multi-lens confluence ──────────────────────────────────────────────
     The rare event: the SAME name with an ACTIVE setup on more than one
     lens, direction-aligned (VIVEK LONG + PhaseMap bullish + Specs = the
     full house). Computed client-side from the three latest scan files so
     it's always as fresh as whatever each lens last published. */
  const PM_ACTIVE_STATES = ["SWEPT", "DISPLACED", "RUNNING"];
  async function loadConfluence(market) {
    const grab = (url) => fetch(url, { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const [vivek, pm, spec] = await Promise.all([
      grab(`data/${market}_vivek.json`),
      grab(`data/phasemap/${market}/latest.json`),
      grab(`data/${market}_spec.json`),
    ]);
    const map = {};
    const ent = (t) => (map[t] = map[t] || { long: [], short: [], detail: {} });
    ((vivek && vivek.results) || []).forEach((r) => {
      const e = ent(r.symbol);
      const side = String(r.dir || "LONG").toUpperCase() === "SHORT" ? "short" : "long";
      if (!e[side].includes("VIVEK")) e[side].push("VIVEK");
      e.detail.vivek = { grade: r.grade, side };
    });
    ((pm && pm.results) || []).forEach((r) => {
      if (!PM_ACTIVE_STATES.includes(r.state)) return;
      const e = ent(r.ticker);
      const side = r.direction === "bearish" ? "short" : "long";
      if (!e[side].includes("PHASEMAP")) e[side].push("PHASEMAP");
      e.detail.phasemap = { state: r.state, tier: r.tier, side };
    });
    ((spec && spec.results) || []).forEach((r) => {
      const e = ent(r.symbol);
      if (!e.long.includes("SPECS")) e.long.push("SPECS");
      e.detail.specs = { grade: r.grade };
    });
    return {
      of(ticker) {
        const e = map[ticker];
        if (!e) return null;
        const side = e.long.length >= e.short.length ? "long" : "short";
        const lenses = e[side];
        if (lenses.length < 2) return null;
        return { ticker, lenses, side, count: lenses.length, detail: e.detail };
      },
      all() {
        return Object.keys(map)
          .map((t) => this.of(t))
          .filter(Boolean)
          .sort((a, b) => b.count - a.count || a.ticker.localeCompare(b.ticker));
      },
    };
  }

  /* Banner body shared by the dashboard and the lens pages: capped list of
     aligned names, triples as pulsing beacons, links to the combined chart. */
  function confluenceBannerHTML(rows, market, cap = 10) {
    if (!rows || !rows.length) return "";
    return `<span class="conf-banner-label">⨂ MULTI-LENS ALIGNMENT</span>` +
      rows.slice(0, cap).map((x) => {
        const dir = x.side === "short" ? "&dir=bearish" : "&dir=bullish";
        const arrow = x.side === "short" ? "▼" : "▲";
        const cls = x.count >= 3 ? "pm-conf pm-conf-3" : "";
        const tag = x.count >= 3 ? "🎯 " : "";
        return `<a class="${cls}" title="${x.lenses.join(" + ")} — open the combined chart" ` +
          `href="chart.html?m=${market}&s=${encodeURIComponent(x.ticker)}&pm=1${dir}">` +
          `${tag}${esc(x.ticker)} ${arrow}${x.count >= 3 ? " ×3" : ""}</a>`;
      }).join("") +
      (rows.length > cap ? `<span style="color:var(--muted)">+${rows.length - cap} more</span>` : "");
  }

  /* Staleness: lens data refreshes nightly — shout when it's older than that.
     Accepts 'YYYY-MM-DD' (PhaseMap run_date) or a full ISO stamp (Specs). */
  function staleBadgeHTML(stamp) {
    if (!stamp) return "";
    const t = Date.parse(String(stamp).length <= 10 ? stamp + "T00:00:00" : stamp);
    if (!isFinite(t)) return "";
    const hours = (Date.now() - t) / 3600000;
    const limit = String(stamp).length <= 10 ? 48 : 30;   // date-only gets a day's grace
    if (hours < limit) return "";
    const days = Math.floor(hours / 24);
    const age = days >= 2 ? `${days} DAYS` : `${Math.round(hours)}H`;
    return ` <span class="pm-stale-badge" title="This lens refreshes nightly — the last ` +
      `successful scan is older than expected. Check the GitHub Actions runs.">` +
      `⚠ SCAN ${age} OLD</span>`;
  }

  function confluenceChipHTML(info, currentLens) {
    if (!info) return "";
    const others = info.lenses.filter((l) => l !== currentLens);
    if (!others.length) return "";
    const triple = info.count >= 3;
    return `<span class="pm-conf${triple ? " pm-conf-3" : ""}" ` +
      `title="Multiple independent lenses have an ACTIVE ${info.side} setup on this ` +
      `name right now — rare alignment, review every view">` +
      `${triple ? "🎯 " : "⨂ "}${info.count}-LENS · +${others.join(" +")}</span>`;
  }

  function starHTML(on, ticker) {
    return `<button class="pm-star${on ? " is-on" : ""}" data-star="${esc(ticker)}" ` +
      `title="${on ? "Remove from" : "Add to"} watchlist — starred names stay ` +
      `monitored even after the setup ends" aria-label="Toggle watchlist">` +
      `${on ? "★" : "☆"}</button>`;
  }

  return { fmtPrice, fmtPct, fmtTurnover, esc, srcText, zoneLabel,
           ladderHTML, metricsHTML, headBadgesHTML, identityHTML,
           isFundReit, toggleSpeak, watch, starHTML,
           loadConfluence, confluenceChipHTML, confluenceBannerHTML,
           staleBadgeHTML };
})();
