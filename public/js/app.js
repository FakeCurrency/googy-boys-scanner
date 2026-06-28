/* =========================================================================
   Vivek 5.0 — frontend logic
   Renders the PULSE bar, stat cards, and the dense results table from
   data/<market>.json. Handles market toggle, Results/Watch views, grade
   sub-tabs, sorting, and a localStorage watchlist (stars).
   ========================================================================= */
(() => {
  "use strict";

  // ---- constants -----------------------------------------------------------
  const CACHE_PREFIX   = "gbs:cache:";
  const CACHE_TTL_MS   = 5 * 60 * 1000;   // 5 min localStorage cache
  const PREFS_KEY      = "gbs:prefs";
  const AUTO_REFRESH_S = 5 * 60;           // auto-refresh interval in seconds
  const DEBUG_KEY      = "gbs:debug";

  const COLOR = { green: "#2fd07f", blue: "#4d9fff", red: "#ff5b5b" };
  const EMA_COLOR = {
    8: "#ff5c8a", 13: "#ff9f43", 21: "#ffd23f", 34: "#2fd07f",
    55: "#2fd0c4", 89: "#4d9fff", 144: "#a78bfa",
  };
  const SMA_COLOR = { 9: "#e5e9f0", 26: "#ffd23f", 43: "#a78bfa", 200: "#ff5b5b" };
  const GRADE_VAR = { "A+": "var(--grade-aplus)", "A": "var(--grade-a)", "B+": "var(--grade-b)", "B": "var(--grade-b)", "WATCH": "var(--grade-c)", "C": "var(--grade-c)" };
  const GRADE_RANK = { "A+": 0, "A": 1, "B+": 2, "B": 2, "WATCH": 3, "C": 3 };
  const WATCH_KEY = "gbs:watch";

  // ---- persistent preferences (survive page refresh) ----------------------
  function loadPrefs() {
    try {
      const p = JSON.parse(localStorage.getItem(PREFS_KEY) || "{}");
      if (p.market) state.market = p.market;
      if (p.mode)   state.mode   = p.mode;
      if (p.tab)    state.tab    = p.tab;
      if (p.sort)   state.sort   = p.sort;
      if (p.sortDir) state.sortDir = p.sortDir;
    } catch (_) {}
  }
  function savePrefs() {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify({
        market: state.market, mode: state.mode,
        tab: state.tab, sort: state.sort, sortDir: state.sortDir,
      }));
    } catch (_) {}
  }

  // ---- localStorage scan cache with TTL -----------------------------------
  function cacheSet(key, data) {
    try { localStorage.setItem(CACHE_PREFIX + key, JSON.stringify({ ts: Date.now(), data })); }
    catch (_) {}
  }
  function cacheGet(key) {
    try {
      const item = JSON.parse(localStorage.getItem(CACHE_PREFIX + key) || "null");
      if (item && Date.now() - item.ts < CACHE_TTL_MS) return item.data;
    } catch (_) {}
    return null;
  }

  // ---- debug mode ---------------------------------------------------------
  const isDebug = () =>
    new URLSearchParams(location.search).has("debug") ||
    localStorage.getItem(DEBUG_KEY) === "1";
  function toggleDebug() {
    const next = isDebug() ? null : "1";
    if (next) localStorage.setItem(DEBUG_KEY, "1"); else localStorage.removeItem(DEBUG_KEY);
    document.body.classList.toggle("debug-mode", Boolean(next));
    if (state.data) renderRows();
  }
  if (isDebug()) document.body.classList.add("debug-mode");

  // ---- auto-refresh -------------------------------------------------------
  let _refreshTimer = null;
  let _refreshRemaining = AUTO_REFRESH_S;
  function _updateRefreshBadge() {
    const el = document.getElementById("refresh-timer");
    if (!el) return;
    const m = Math.floor(_refreshRemaining / 60);
    const s = String(_refreshRemaining % 60).padStart(2, "0");
    el.textContent = `${m}:${s}`;
    el.title = `Auto-refresh in ${m}m ${_refreshRemaining % 60}s`;
  }
  function startAutoRefresh() {
    if (_refreshTimer) clearInterval(_refreshTimer);
    _refreshRemaining = AUTO_REFRESH_S;
    _updateRefreshBadge();
    _refreshTimer = setInterval(() => {
      _refreshRemaining -= 1;
      _updateRefreshBadge();
      if (_refreshRemaining <= 0) {
        _refreshRemaining = AUTO_REFRESH_S;
        const key = `${state.market}:${state.mode}`;
        delete state.cache[key];
        localStorage.removeItem(CACHE_PREFIX + key);
        load(true);
      }
    }, 1000);
  }

  const state = {
    market: "asx",
    mode: "vivek",      // VIVEK (5.0) is the only scanner now
    view: "results",    // results | watch
    tab: "aplus",       // aplus | a | watch
    sort: "score",      // score | price | rr | mcap | az
    sortDir: null,      // "asc" | "desc"; null = the sort's natural default
    data: null,
    cache: {},
    cur: "$",
    caps: {},           // "<market>:<symbol>" -> raw market cap (float)
    vkEntry: new Set(), // VIVEK entry-type filter; empty = All
    vkRecent: false,    // VIVEK "triggered recently" filter toggle
    vkHighConv: false,  // VIVEK "high conviction" filter (weekly reclaim + A/strong structure)
  };

  // Sort direction. Each sort has a natural default (numeric → descending,
  // alphabetical → ascending); clicking the already-active sort flips it. The
  // active button shows a ↑ / ↓ arrow for the current direction.
  const SORT_DEFAULT_DIR = { score: "desc", price: "desc", rr: "desc", mcap: "desc", az: "asc" };
  const defaultDir = (sort) => SORT_DEFAULT_DIR[sort] || "desc";
  const sortDirOf  = () => state.sortDir || defaultDir(state.sort);
  function updateSortButtons() {
    document.querySelectorAll("#sorts .seg-btn").forEach((b) => {
      const active = b.dataset.sort === state.sort;
      b.classList.toggle("is-active", active);
      const arrow = b.querySelector(".sort-arrow");
      if (arrow) arrow.textContent = active ? (sortDirOf() === "asc" ? " ↑" : " ↓") : "";
    });
  }

  loadPrefs();
  // Sync UI controls to restored preferences
  (function syncPrefsUI() {
    document.querySelectorAll(".market-btn").forEach((b) => {
      b.classList.toggle("is-active", b.dataset.market === state.market);
      b.setAttribute("aria-selected", b.dataset.market === state.market ? "true" : "false");
    });
    document.querySelectorAll(".scan-btn").forEach((b) => {
      b.classList.toggle("is-active", b.dataset.mode === state.mode);
      b.setAttribute("aria-selected", b.dataset.mode === state.mode ? "true" : "false");
    });
    document.querySelectorAll("#tabs .seg-btn").forEach((b) => b.classList.toggle("is-active", b.dataset.tab === state.tab));
    updateSortButtons();
  })();

  const SMALLCAP = 750e6;   // sub-750M = small/spec bucket
  const HOTCAP   = 500e6;   // sub-500M = 🔥 micro-cap spec sweet spot

  const $ = (s) => document.querySelector(s);

  // Escape data-derived strings before injecting into innerHTML (incl. quotes
  // so values are safe inside quoted attributes too).
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const up = (s) => esc(String(s == null ? "" : s).toUpperCase());

  // ----------------------------------------------------------- watchlist
  function loadWatch() { try { return new Set(JSON.parse(localStorage.getItem(WATCH_KEY) || "[]")); } catch (_) { return new Set(); } }
  let watch = loadWatch();
  const wkey = (sym) => `${state.market}:${sym}`;
  const isStarred = (sym) => watch.has(wkey(sym));
  function toggleStar(sym) {
    const k = wkey(sym);
    if (watch.has(k)) watch.delete(k); else watch.add(k);
    localStorage.setItem(WATCH_KEY, JSON.stringify([...watch]));
  }

  // ----------------------------------------------------------- formatting
  function decimals(v) {
    const a = Math.abs(v);
    return a >= 100 ? 2 : a >= 1 ? 3 : a >= 0.1 ? 4 : a >= 0.01 ? 5 : a >= 0.001 ? 6 : 8;
  }
  function fmtPrice(v) {
    if (v == null || isNaN(v)) return "—";
    const dp = decimals(v);
    return state.cur + v.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
  }
  function fmtPct(v) {
    if (v == null || isNaN(v)) return "";
    return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
  }
  const pctCls = (v) => (v >= 0 ? "pct-up" : "pct-down");

  function fmtTurn(v) {
    if (v == null) return "";
    if (v >= 1e9) return state.cur + (v / 1e9).toFixed(1) + "B";
    if (v >= 1e6) return state.cur + (v / 1e6).toFixed(1) + "M";
    if (v >= 1e3) return state.cur + Math.round(v / 1e3) + "k";
    return state.cur + v;
  }
  function num(v) {
    if (v == null || isNaN(v)) return "—";
    const dp = decimals(v);
    return v.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
  }
  function fmtK(v) {
    if (v == null) return "—";
    if (v >= 1e9) return (v / 1e9).toFixed(1) + "B";
    if (v >= 1e6) return (v / 1e6).toFixed(1) + "M";
    if (v >= 1e3) return Math.round(v / 1e3) + "K";
    return String(v);
  }
  function fmtMcap(v) {
    if (!v || v <= 0) return "";
    if (v >= 1e12) return (v / 1e12).toFixed(1) + "T";
    if (v >= 1e9)  return (v / 1e9).toFixed(1) + "B";
    if (v >= 1e6)  return Math.round(v / 1e6) + "M";
    return Math.round(v / 1e3) + "K";
  }
  const mcapOf = (sym) => state.caps[`${state.market}:${sym}`] || 0;

  const TZ_MAP = { AEST: "Australia/Sydney", ET: "America/New_York", UTC: "UTC" };
  function fmtTime(iso, tz) {
    try {
      const d = new Date(iso);
      const zone = TZ_MAP[tz];
      const opts = {
        weekday: "short", day: "numeric", month: "short",
        hour: "numeric", minute: "2-digit",
        ...(zone ? { timeZone: zone } : {}),
      };
      return `${d.toLocaleString(undefined, opts)} ${tz || ""}`.trim();
    } catch (_) { return iso; }
  }

  // ----------------------------------------------------------- sparkline
  function spark(vals, w, h, color, cls) {
    if (!vals || vals.length < 2) return "";
    const min = Math.min(...vals), max = Math.max(...vals), rng = (max - min) || 1;
    const step = w / (vals.length - 1);
    const pts = vals.map((v, i) => `${(i * step).toFixed(1)},${(h - ((v - min) / rng) * h).toFixed(1)}`).join(" ");
    return `<svg class="${cls || ""}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  }

  // ----------------------------------------------------------- PULSE
  function renderPulse(pulse) {
    const sec = $("#pulse"), track = $("#pulse-track");
    if (!pulse || !pulse.length) { sec.style.display = "none"; return; }
    sec.style.display = "";
    track.innerHTML = pulse.map((p) => {
      const val = p.value == null ? "—"
        : p.value.toLocaleString(undefined, { minimumFractionDigits: p.decimals, maximumFractionDigits: p.decimals });
      const dir = p.dir === "up" ? "up" : "down";
      const day = p.day_pct == null ? "" : (p.day_pct >= 0 ? "+" : "") + p.day_pct.toFixed(2) + "%";
      const d5 = p.d5_pct == null ? "" : "5D " + (p.d5_pct >= 0 ? "+" : "") + p.d5_pct.toFixed(2) + "%";
      return `<div class="pulse-item" data-pkey="${esc(p.key)}">
        <div class="pi-head"><span class="pi-key">${esc(p.key)}</span><span class="pi-val">${val}</span></div>
        <div class="pi-change ${dir}">${day}<span class="pi-5d">${d5}</span></div>
        ${spark(p.spark, 120, 22, p.dir === "up" ? COLOR.green : COLOR.red, "pi-spark")}
      </div>`;
    }).join("");
  }

  // Refresh PULSE values from Yahoo Finance after the static scan data renders,
  // then keep them current on a slow interval. Staggers requests so we don't
  // hammer the proxy, retries once on a transient failure, and reveals a visible
  // "~15m delayed" badge once at least one live value lands (Yahoo isn't
  // real-time for indices / futures / FX).
  let _pulseTimer = null;
  async function _pulseQuote(ticker) {
    // One retry — Yahoo/proxy occasionally returns a transient non-200.
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const res = await fetch(`/api/quote?sym=${encodeURIComponent(ticker)}`, { cache: "no-store" });
        if (res.ok) {
          const j = await res.json();
          if (j && j.price != null) return j;
        }
      } catch (_) { /* fall through to retry */ }
      if (attempt === 0) await new Promise((r) => setTimeout(r, 600));
    }
    return null;
  }
  async function _pulsePass(pulse) {
    const track = $("#pulse-track");
    if (!track) return;
    let anyLive = false;
    for (let i = 0; i < pulse.length; i++) {
      const p = pulse[i];
      if (!p.ticker) continue;
      await new Promise((r) => setTimeout(r, i * 350));
      const j = await _pulseQuote(p.ticker);
      if (!j) continue;
      const divide = p.divide || 1;
      const price = j.price / divide;
      const decimals = p.decimals ?? 2;
      const valStr = price.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
      const item = track.querySelector(`[data-pkey="${CSS.escape(p.key)}"]`);
      if (!item) continue;
      const valEl = item.querySelector(".pi-val");
      if (valEl && valEl.textContent !== valStr) {
        valEl.textContent = valStr;
        const refreshedAt = j.time ? new Date(j.time * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
        valEl.title = refreshedAt ? `~15min delayed · as of ${refreshedAt}` : "~15min delayed";
      }
      anyLive = true;
    }
    if (anyLive) {
      const badge = $("#pulse-delayed");
      if (badge) badge.hidden = false;
    }
  }
  function refreshPulseLive(pulse) {
    if (!pulse || !pulse.length) return;
    if (_pulseTimer) { clearInterval(_pulseTimer); _pulseTimer = null; }
    _pulsePass(pulse);
    // Keep the macro row live without reloading the page (Yahoo is ~15m delayed,
    // so a 90s cadence is plenty fresh and gentle on the proxy).
    _pulseTimer = setInterval(() => _pulsePass(pulse), 90000);
  }

  // ------------------------------------------------------- EMA / SMA legend
  function renderLegend(d) {
    let periods, colors, label;
    if (d.setup_type === "vivek") {
      // VIVEK lines: fast SMA 10 (white) / 20 (yellow), 43 (purple) for trend
      // structure, and 200 (amber) — the level — matching the chart overlays.
      periods = [10, 20, 43, 200];
      colors = { 10: "#e5e9f0", 20: "#ffd23f", 43: "#a78bfa", 200: "#ffb020" };
      label = "SMA";
    } else {
      const smaSetup = d.setup_type === "reversal" || d.setup_type === "spec" || d.setup_type === "googy";
      periods = smaSetup ? (d.sma_periods || []) : (d.ema_periods || []);
      colors = smaSetup ? SMA_COLOR : EMA_COLOR;
      label = smaSetup ? "SMA" : "EMA";
    }
    $("#ema-legend").innerHTML = `<span class="legend-tag">${label}</span>` +
      periods.map((p) => `<span class="ema-dot"><i style="background:${colors[p] || "#888"}"></i>${p}</span>`).join("");
  }

  // ----------------------------------------------------------- stats
  function renderStats(d) {
    const res = d.results || [];
    const tradeable = res.filter((r) => r.grade === "A+" || r.grade === "A");
    $("#stat-scanned").textContent = d.scanned ?? "—";
    $("#stat-setups").textContent = tradeable.length;
    const top = res.slice().sort((a, b) => (GRADE_RANK[a.grade] - GRADE_RANK[b.grade]) || (b.score - a.score))[0];
    $("#stat-toppick").textContent = top ? `${top.symbol} ${fmtPrice(top.price)}` : "—";
    const bestRR = (tradeable.length ? tradeable : res).reduce((m, r) => Math.max(m, r.rr || 0), 0);
    $("#stat-rr").textContent = bestRR > 0 ? `${bestRR.toFixed(1)}:1` : "—";

    $("#count-aplus").textContent = res.filter((r) => r.grade === "A+").length;
    $("#count-a").textContent = res.filter((r) => r.grade === "A").length;
    $("#count-watch").textContent = res.filter((r) => ["B", "C", "B+", "WATCH"].includes(r.grade)).length;
    $("#watch-count").textContent = res.filter((r) => isStarred(r.symbol)).length;
  }

  // ----------------------------------------------------------- a row
  // ── VIVEK screening helpers ────────────────────────────────────────────────
  const RECENT_DAYS = 3;                       // trigger within this many days = "recent"
  const TRIG_LABEL = { reclaim: "Reclaim", retest: "Retest", break: "Break" };

  function scanDateMs() {
    const t = state.data && state.data.generated_at ? Date.parse(state.data.generated_at) : NaN;
    return isFinite(t) ? t : Date.now();
  }
  // A setup's trigger fired on (or within a few days of) the latest scanned bar —
  // i.e. it has just moved, vs an older trigger still sitting in play.
  function triggeredRecently(r) {
    if (!r || !r.trigger_bar) return false;
    const tb = Date.parse(`${r.trigger_bar}T00:00:00`);
    if (!isFinite(tb)) return false;
    return (scanDateMs() - tb) / 86400000 <= RECENT_DAYS + 0.5;
  }

  // High conviction (from the walk-forward backtest): a WEEKLY reclaim that's
  // also A/A+ or has strong structure — the cleanest, lowest-drawdown cell.
  function isHighConviction(r) {
    const p = r && r.plans && r.plans["1W"];
    if (!p || !p.armed || p.entry_trigger !== "reclaim") return false;
    const goodGrade = r.grade === "A+" || r.grade === "A";
    const strongStructure = (p.structural_tps || 0) >= 2;
    return goodGrade || strongStructure;
  }
  // Compact, scannable badges for the VIVEK list (max 3) — what moved + why it matters.
  function vkBadges(r) {
    if (state.mode !== "vivek") return "";
    const out = [];
    if (isHighConviction(r))
      out.push(`<span class="rbadge hiconv" title="Weekly reclaim, A/strong structure — the best-performing setup in the backtest">🎯 High conviction</span>`);
    if (triggeredRecently(r))
      out.push(`<span class="rbadge fresh" title="Trigger fired on/near the latest bar">⚡ Triggered recently</span>`);
    const trig = r.entry_trigger || (r.armed && (r.entry_types || [])[0]) || null;
    if (trig) out.push(`<span class="rbadge trig" title="Entry trigger">${esc(TRIG_LABEL[trig] || trig)}</span>`);
    if (r.level_tf === "weekly")
      out.push(`<span class="rbadge wk" title="Reaction at the Weekly 200 SMA (higher timeframe)">Weekly 200</span>`);
    else if ((r.chips || []).includes("STRONG STRUCTURE"))
      out.push(`<span class="rbadge struct" title="Recent swings stacking in the trade's favour">Strong structure</span>`);
    return out.join("");
  }

  function rowHtml(r, i) {
    // Stagger index drives the entrance animation delay (capped so long lists
    // don't trail off into a slow cascade).
    const stagger = Math.min(i || 0, 12);
    // Row view shows NO regular signal chips — only critical warnings below.
    // All chips appear in the expanded detail panel via chipsBar().
    const lowrr = r.low_rr ? `<span class="chip warn">LOW R:R (${esc(r.rr_text)})</span>` : "";
    const widestop = (r.stop_pct != null && r.stop_pct > 20)
      ? `<span class="chip warn">WIDE STOP (${r.stop_pct}%)</span>` : "";
    const t2r = r.target_2r
      ? `<span class="chip info">${(r.setup_type === "reversal" || r.setup_type === "spec") ? "MEASURED TARGET" : "TARGET = 2R FALLBACK"}</span>`
      : "";
    const hasSectorCount = r.sector && r.sector_count > 1;
    const sector = (r.sector && !hasSectorCount) ? `<span class="badge sector">${esc(r.sector)}</span>` : "";
    const seccount = hasSectorCount
      ? `<span class="badge seccount">${up(r.sector)} ×${r.sector_count}</span>` : "";
    const assetBadge = "";
    const rawMcap = mcapOf(r.symbol);
    const mcapTxt = fmtMcap(rawMcap);
    const mcapCls = rawMcap <= 0 ? "" : rawMcap < HOTCAP ? "mcap-hot"
      : rawMcap < SMALLCAP ? "mcap-small" : "mcap";
    // Show the market-cap pill for EVERY ticker that has cap data (not just the
    // hot/small-cap buckets) — it rides on the same line as the ticker + name.
    const mcapBadge = mcapTxt
      ? `<span class="badge ${mcapCls || "mcap"}" title="Market cap">${rawMcap < HOTCAP ? "🔥" : ""}${mcapTxt}</span>`
      : "";
    const rrStar = r.target_2r ? "*" : "";
    const rrCls = r.low_rr ? "low" : "";
    const starred = isStarred(r.symbol);

    const chartHref = `chart.html?m=${state.market}&s=${encodeURIComponent(r.symbol)}${state.mode !== "pullback" ? `&mode=${state.mode}` : ""}`;
    return `<div class="row-wrap" data-sym="${esc(r.symbol)}" style="--grade-color:${GRADE_VAR[r.grade] || "var(--grade-c)"};--row-i:${stagger}">
     <div class="row">
      <div class="row-grade">${esc(r.grade)}</div>
      <div class="row-main">
        <div class="row-line1">
          <a class="tkr" href="${chartHref}" title="Open chart">${esc(r.symbol)}</a>
          <span class="badge dir ${r.dir === "SHORT" ? "short" : "long"}">${esc(r.dir)}</span>
          ${mcapBadge}
          <span class="cname">${esc(r.name || "")}</span>
          <span class="rprice">${fmtPrice(r.price)}</span>
        </div>
        <div class="row-chips">${vkBadges(r)}${assetBadge}${lowrr}${widestop}${t2r}</div>
      </div>
      <div class="row-right">
        <a class="row-spark" href="${chartHref}" title="Open chart">
          ${spark(r.spark, 64, 28, COLOR[r.trend] || COLOR.blue)}
        </a>
        <div class="row-kpis">
          <span class="rk-score">${r.score}<span class="rk-max">/${r.score_max}</span></span>
          <span class="rk-rr ${rrCls}">${r.rr == null ? "—" : r.rr.toFixed(1) + rrStar}</span>
        </div>
        <button class="t-star ${starred ? "starred" : ""}" data-sym="${esc(r.symbol)}" title="Watchlist" aria-label="Toggle watchlist">
          <svg viewBox="0 0 24 24" width="17" height="17" fill="${starred ? "currentColor" : "none"}" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
        </button>
        <button class="row-copy-debug" data-sym="${esc(r.symbol)}" title="Copy debug info" aria-label="Copy raw data">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
        </button>
        <button class="row-expand" title="Details" aria-label="Toggle details">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="6 9 12 15 18 9"/></svg>
        </button>
      </div>
     </div>
     <div class="detail-anim">
       <div class="detail-inner">
         ${detailHtml(r)}
         ${debugDetailHtml(r)}
       </div>
     </div>
    </div>`;
  }

  function priceStrip(r) {
    const openPct  = r.open_pct    != null ? ` <span class="pcell-pct ${pctCls(r.open_pct)}">${fmtPct(r.open_pct)}</span>`    : "";
    const currPct  = r.current_pct != null ? ` <span class="pcell-pct ${pctCls(r.current_pct)}">${fmtPct(r.current_pct)}</span>` : "";
    return `<div class="detail-prices">
      <div class="dp-cell"><span class="dp-lbl">Y Close</span><span class="dp-val">${fmtPrice(r.y_close)}</span></div>
      <div class="dp-cell"><span class="dp-lbl">Open</span><span class="dp-val">${fmtPrice(r.open)}${openPct}</span></div>
      <div class="dp-cell"><span class="dp-lbl">Current</span><span class="dp-val">${fmtPrice(r.price)}${currPct}</span></div>
      <div class="dp-cell"><span class="dp-lbl">Day</span><span class="dp-val ${pctCls(r.day_pct)}">${fmtPct(r.day_pct)}</span></div>
    </div>`;
  }

  // Hero trade card — full-color grade badge (left) + 4 key metrics (right).
  // Grade letter + score live in the badge; Entry / Stop / Target / R:R get
  // their own metric cells with colour-coded backgrounds for instant scanning.
  function heroStrip(r, cur, entry, stop, target, stopPct, targetPct) {
    const rrTxt  = r.rr == null ? "—" : r.rr.toFixed(1);
    const rrCls  = r.low_rr ? "low" : "";
    const rrUnit = r.rr == null ? "" : `<span class="dh-unit">:1</span>`;
    const sp = stopPct   != null && stopPct   !== "" ? Math.abs(+stopPct).toFixed(1)   : null;
    const tp = targetPct != null && targetPct !== "" ? Math.abs(+targetPct).toFixed(1) : null;
    const gColor    = GRADE_VAR[r.grade] || "var(--grade-c)";
    const scoreTxt  = r.score != null ? r.score : "—";
    const scoreMax  = r.score_max ? `/${r.score_max}` : "";
    return `<div class="detail-hero">
      <div class="dh-grade-block" style="--gc:${gColor};background:${gColor}">
        <span class="dh-grade-lbl">GRADE</span>
        <span class="dh-grade-val">${esc(r.grade)}</span>
        <span class="dh-score-val">${scoreTxt}${scoreMax}</span>
      </div>
      <div class="dh-metrics">
        <div class="dh-metric">
          <span class="dh-lbl">Entry</span>
          <span class="dh-val">${cur}${num(entry)}</span>
        </div>
        <div class="dh-metric dh-stop">
          <span class="dh-lbl">Stop</span>
          <span class="dh-val">${cur}${num(stop)}</span>
          ${sp ? `<span class="dh-sub neg">−${sp}%</span>` : ""}
        </div>
        <div class="dh-metric dh-target">
          <span class="dh-lbl">Target</span>
          <span class="dh-val">${cur}${num(target)}</span>
          ${tp ? `<span class="dh-sub pos">+${tp}%</span>` : ""}
        </div>
        <div class="dh-metric dh-rr">
          <span class="dh-lbl">R:R</span>
          <span class="dh-val ${rrCls}">${rrTxt}${rrUnit}</span>
        </div>
      </div>
    </div>`;
  }

  // Quiet metadata row shown below the hero in the detail panel.
  // Sector, market cap, sector-count — kept out of the row card for cleanliness.
  function metaBar(r) {
    const parts = [];
    if (r.sector) parts.push(`<span class="meta-item">${esc(r.sector)}</span>`);
    const rawMcap = mcapOf(r.symbol);
    const mcapTxt = fmtMcap(rawMcap);
    if (mcapTxt) parts.push(`<span class="meta-item">${mcapTxt} mkt cap</span>`);
    if (r.sector_count > 1) parts.push(`<span class="meta-item accent-orange">${r.sector_count} setups in sector</span>`);
    return parts.length ? `<div class="detail-meta">${parts.join("")}</div>` : "";
  }

  // Render all signal chips for the detail panel — shows every chip, not just
  // the 3 shown in the row card. Returns empty string if no chips.
  function chipsBar(r) {
    const all = r.chips || [];
    if (!all.length) return "";
    return `<div class="detail-chips">${all.map((c) =>
      `<span class="chip${c.startsWith("WEEKLY") ? " weekly" : ""}">${esc(c)}</span>`
    ).join("")}</div>`;
  }

  function debugDetailHtml(r) {
    const d = r.detail || {};
    const fields = [
      ["Score", `${r.score} / ${r.score_max}`],
      ["Grade", r.grade],
      ["R:R", r.rr],
      ["ATR", r.atr],
      ["ADX", r.adx],
      ["Regime", r.market_regime],
      ["Entry", r.entry],
      ["Stop", r.stop],
      ["Target", r.target],
      ["Momentum", d.mom_val],
      ["Squeeze", d.sq_state],
      ["BB Mid", d.bb_mid],
      ["Volume ratio", d.volume_ratio],
      ["Chips", (r.chips || []).join(", ")],
    ].filter(([, v]) => v != null && v !== "");
    const rows = fields.map(([k, v]) =>
      `<div class="dbg-row"><span class="dbg-k">${esc(k)}</span><span class="dbg-v">${esc(String(v))}</span></div>`
    ).join("");
    return `<div class="debug-panel"><div class="dbg-title">DEBUG</div>${rows}</div>`;
  }

  // ── VIVEK (5.0 style) detail — Entry / SL / TP1 / TP2 / TP3 front & centre ──
  function detailHtmlVivek(r) {
    const cur = state.cur;
    const d = r.detail || {};
    const isLong = r.dir !== "SHORT";
    const scale = (r.scale || d.scale || [0.25, 0.50, 0.15]).map((x) => Math.round(x * 100));
    const gColor = GRADE_VAR[r.grade] || "var(--grade-c)";
    const tfTxt = r.level_tf === "weekly" ? "Weekly 200 SMA" : "H4 200 SMA";
    const pctFrom = (v) => (r.entry ? ((v - r.entry) / r.entry) * 100 : 0);
    const sgn = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(1) + "%";
    const chartHref = `chart.html?m=${state.market}&s=${encodeURIComponent(r.symbol)}&mode=vivek`;

    // How long ago was this scan? (helps judge whether the price is actionable)
    const scanAge = () => {
      const g = state.data && state.data.generated_at;
      if (!g) return "";
      const mins = Math.max(0, Math.round((Date.now() - new Date(g).getTime()) / 60000));
      const txt = mins < 60 ? `${mins}m ago` : mins < 1440 ? `${Math.round(mins / 60)}h ago` : `${Math.round(mins / 1440)}d ago`;
      const stale = mins > 1440;
      return `<span class="vk-fresh${stale ? " stale" : ""}" title="When this setup was last scanned">⟳ scanned ${txt}</span>`;
    };

    // 5.0 trade checklist — the mechanical criteria, pass/fail at a glance.
    const reactClean = r.reaction === "bounce" || r.reaction === "reject";
    const struct = d.structure != null ? d.structure : 0;
    const nStruct = d.structural_tps != null ? d.structural_tps : 0;
    const rrOk = (r.rr || 0) >= 1.5;
    const chk = (ok, label, note) => `
      <div class="vk-check ${ok ? "ok" : "no"}">
        <span class="vk-check-ic">${ok ? "✓" : "✕"}</span>
        <span class="vk-check-lbl">${label}</span>
        <span class="vk-check-note">${note}</span>
      </div>`;
    const checklist = [
      chk(true, "200 SMA level", r.level_tf === "weekly" ? "Weekly (strongest)" : "H4 / daily proxy"),
      chk(!!r.at_level, "At the level", r.at_level ? "price on the SMA" : "still approaching"),
      chk(reactClean, "Clean reaction", r.reaction === "bounce" ? "bounced" : r.reaction === "reject" ? "rejected" : "no clear turn yet"),
      chk(struct >= 0.5, "Structure", struct >= 0.8 ? "clean" : struct >= 0.5 ? "workable" : "thin"),
      chk(rrOk, "R:R ≥ 1.5", `${(r.rr || 0).toFixed(1)} to TP2`),
      chk(nStruct > 0, "Real targets", nStruct > 0 ? `${nStruct}/3 at structure` : "R-multiples only"),
    ].join("");

    // A vertical price ladder: SL → Entry → TP1 → TP2 → TP3 (ordered by price).
    const lvl = (key, label, val, cls, sub) => `
      <div class="vk-lvl vk-${cls}">
        <span class="vk-lvl-key">${key}</span>
        <span class="vk-lvl-label">${label}</span>
        <span class="vk-lvl-price num">${cur}${num(val)}</span>
        <span class="vk-lvl-sub">${sub}</span>
      </div>`;
    const tps = [
      lvl("TP3", "Take profit 3", r.tp3, "tp", `${sgn(pctFrom(r.tp3))} · book ${scale[2]}%`),
      lvl("TP2", "Take profit 2", r.tp2, "tp", `${sgn(pctFrom(r.tp2))} · book ${scale[1]}% · SL → support`),
      lvl("TP1", "Take profit 1", r.tp1, "tp", `${sgn(pctFrom(r.tp1))} · book ${scale[0]}% · SL → break-even`),
      lvl("IN",  "Entry", r.entry, "entry", `${tfTxt} reaction`),
      lvl("SL",  "Stop loss", r.stop, "sl", `${sgn(pctFrom(r.stop))} · risk ${cur}${num(r.risk)}`),
    ];
    // Longs read top-down TP3→SL; shorts invert so price still descends visually.
    const ladder = isLong ? tps : tps.slice().reverse();

    return `<div class="row-detail vk-detail">
      <div class="vk-hero" style="--gc:${gColor}">
        <div class="vk-grade-block">
          <span class="vk-grade-lbl">GRADE</span>
          <span class="vk-grade-val">${esc(r.grade)}</span>
          <span class="vk-grade-score">${r.score}/${r.score_max}</span>
        </div>
        <div class="vk-hero-body">
          <div class="vk-hero-top">
            <span class="vk-dir ${isLong ? "dir-long" : "dir-short"}">${isLong ? "LONG" : "SHORT"}</span>
            <span class="vk-tf-chip">${tfTxt}${r.confluence ? " · W+H4 confluence" : ""}</span>
            <span class="vk-rr">${r.rr_text || (r.rr + ":1")} <span class="vk-rr-sub">to TP2</span></span>
            ${scanAge()}
            <a class="vk-chart-btn" href="${chartHref}">View chart →</a>
          </div>
          <p class="vk-why">${esc(r.analysis || "")}</p>
        </div>
      </div>

      <div class="vk-ladder">${ladder.join("")}</div>

      <div class="vk-checklist-wrap">
        <div class="vk-section-lbl">5.0 checklist</div>
        <div class="vk-checklist">${checklist}</div>
        <div class="vk-plan-note">Risk 0.25–0.5% of equity · ≤3× leverage · SL → break-even at TP1, → below new support at TP2 · never moved against the trade.</div>
      </div>

      <div class="vk-chips">${(r.chips || []).map((c) => `<span class="chip">${esc(c)}</span>`).join("")}</div>
    </div>`;
  }

  function detailHtml(r) {
    const stype = (r.detail || {}).setup_type;
    if (stype === "vivek") return detailHtmlVivek(r);
    if (stype === "reversal" || stype === "spec") return detailHtmlReversal(r);
    if (stype === "googy") return detailHtmlGoogy(r);
    const d = r.detail || {};
    const cur = state.cur;
    const lvl = (label, val, pct, cls) =>
      `<div class="dl-row"><span class="dl-label ${cls || ""}">${label}</span>
        <span class="dl-val">${cur}${num(val)}</span>
        <span class="dl-pct ${pct >= 0 ? "pct-up" : "pct-down"}">${fmtPct(pct)}</span></div>`;
    const ladder = (state.data.ema_periods || []).map((p, i, a) =>
      `<span class="el-ema" style="color:${EMA_COLOR[p]}">${p}</span>${i < a.length - 1 ? '<span class="el-gt">›</span>' : ""}`).join("");
    const fast = (d.fast_levels || []).map((f) =>
      `<div class="fl-row"><span class="fl-label">${f.label} <span class="fl-ema" style="color:${EMA_COLOR[f.ema]}">· EMA ${f.ema}</span></span>
        <span class="fl-val">${cur}${num(f.value)}</span><span class="fl-pct ${f.pct >= 0 ? "pct-up" : "pct-down"}">${fmtPct(f.pct)}</span></div>`).join("");
    const st = d.structure || {};
    const trend = st.trend || "";
    const trendCls = trend.includes("Up") ? "green" : trend.includes("Down") ? "pct-down" : "muted";
    const series = (arr) => (arr || []).map((v) => `${cur}${num(v)}`).join(" → ");

    return `<div class="row-detail">
      ${heroStrip(r, cur, r.entry, r.stop, r.target, r.stop_pct, r.p2_pct)}
      ${chipsBar(r)}
      ${metaBar(r)}
      <div class="rd-analysis"><p>${esc(r.analysis || "")}</p></div>
      ${priceStrip(r)}

      <div class="rd-group">
        <div class="rd-section">Key levels</div>
        <div class="rd-levels">
          ${lvl("Swing low", d.swing_low, d.swing_low_pct, "red")}
          ${lvl("EMA 55", d.ema55, d.ema55_pct)}
          ${lvl("EMA 89", d.ema89, d.ema89_pct)}
          ${lvl("Swing high", d.swing_high, d.swing_high_pct, "green")}
        </div>
        <div class="rd-trail">
          <span class="rd-trail-label">Trailing stop</span>
          <span class="rd-trail-val">${cur}${num(d.trailing_stop)}</span>
          <span class="rd-trail-note">${d.trailing_label || ""}</span>
          <span class="dl-pct ${d.trailing_pct >= 0 ? "pct-up" : "pct-down"}">${fmtPct(d.trailing_pct)}</span>
        </div>
      </div>

      <div class="rd-group">
        <div class="rd-section">Trend &amp; structure
          <span class="rd-section-note ${d.ema_aligned ? "green" : "muted"}">${d.ema_aligned ? "Aligned ✓" : "Not aligned"}</span>
          <span class="rd-section-note">${d.ema_spread_pct}% spread</span></div>
        <div class="rd-ladder">${ladder}</div>
        <div class="rd-fast">${fast}</div>
        <div class="rd-volume rd-volume-bare">
          <span class="rd-k">Volume</span>
          <span class="rd-vol ${d.volume_expanding ? "green" : ""}">${d.volume_ratio}× ${d.volume_expanding ? "Expanding" : "Normal"}</span>
          <span class="rd-vol-note">${fmtK(d.volume_today)} today vs ${fmtK(d.volume_avg)} avg</span>
        </div>
        <div class="rd-structure">
          <span class="rd-k">Structure</span> <span class="${trendCls}">${trend}</span>
          <div class="rd-swings"><span class="muted">Swing highs:</span> ${series(st.swing_highs)}
            <span class="muted" style="margin-left:18px">Swing lows:</span> ${series(st.swing_lows)}</div>
        </div>
      </div>
    </div>`;
  }

  function detailHtmlReversal(r) {
    const d = r.detail || {};
    const cur = state.cur;
    const sma = (p, val, pct) =>
      `<div class="dl-row"><span class="dl-label" style="color:${SMA_COLOR[p]}">SMA ${p}</span>
        <span class="dl-val">${cur}${num(val)}</span>
        <span class="dl-pct ${pct >= 0 ? "pct-up" : "pct-down"}">${fmtPct(pct)}</span></div>`;
    const st = d.structure || {};
    const trend = st.trend || "";
    const trendCls = trend.includes("Up") ? "green" : trend.includes("Down") ? "pct-down" : "muted";
    const series = (arr) => (arr || []).map((v) => `${cur}${num(v)}`).join(" → ");

    return `<div class="row-detail">
      ${heroStrip(r, cur, r.entry, r.stop, r.target, r.stop_pct, r.p2_pct)}
      ${chipsBar(r)}
      ${metaBar(r)}
      <div class="rd-analysis"><p>${esc(r.analysis || "")}</p></div>
      ${priceStrip(r)}

      <div class="rd-group">
        <div class="rd-section">Moving averages</div>
        <div class="rd-levels">
          ${sma(9, d.sma9, d.sma9_pct)}${sma(26, d.sma26, d.sma26_pct)}
          ${sma(43, d.sma43, d.sma43_pct)}${sma(200, d.sma200, d.sma200_pct)}
        </div>
      </div>

      <div class="rd-group">
        <div class="rd-section">Momentum &amp; volume</div>
        <div class="rd-volume rd-volume-bare">
          <span class="rd-k">RSI 14</span>
          <span class="rd-vol ${d.rsi_up ? "green" : ""}">${d.rsi} ${d.rsi_up ? "↑ rising" : "flat"}</span>
          <span class="rd-vol-note">signal MA ${d.rsi_ma}</span>
        </div>
        <div class="rd-volume rd-volume-bare">
          <span class="rd-k">Volume</span>
          <span class="rd-vol ${d.volume_surge ? "green" : ""}">${d.volume_ratio}× ${d.volume_surge ? "Surge" : "Normal"}</span>
          <span class="rd-vol-note">${fmtK(d.volume_today)} today vs ${fmtK(d.volume_avg)} avg</span>
        </div>
        <div class="rd-volume rd-volume-bare">
          <span class="rd-k">Base</span>
          <span class="rd-vol">${d.off_high_pct}% off 1-year high</span>
          <span class="rd-vol-note">base high ${cur}${num(d.base_high)}${d.broken ? " · broken ✓" : ""}</span>
        </div>
        <div class="rd-trail">
          <span class="rd-trail-label">Trailing stop</span>
          <span class="rd-trail-val">${cur}${num(d.trailing_stop)}</span>
          <span class="rd-trail-note">${d.trailing_label || ""}</span>
          <span class="dl-pct ${d.trailing_pct >= 0 ? "pct-up" : "pct-down"}">${fmtPct(d.trailing_pct)}</span>
        </div>
        <div class="rd-structure">
          <span class="rd-k">Structure</span> <span class="${trendCls}">${trend}</span>
          <div class="rd-swings"><span class="muted">Swing highs:</span> ${series(st.swing_highs)}
            <span class="muted" style="margin-left:18px">Swing lows:</span> ${series(st.swing_lows)}</div>
        </div>
      </div>
    </div>`;
  }

  function detailHtmlGoogy(r) {
    const d = r.detail || {};
    const cur = state.cur;
    const smRow = (p, val, pct, color) =>
      val != null
        ? `<div class="dl-row"><span class="dl-label" style="color:${color}">SMA ${p}</span>
            <span class="dl-val">${cur}${num(val)}</span>
            <span class="dl-pct ${pct >= 0 ? "pct-up" : "pct-down"}">${fmtPct(pct)}</span></div>`
        : "";
    const volCls = d.volume_ratio >= 2.5 ? "green" : d.volume_ratio >= 1.5 ? "accent-orange" : "";
    const boPct = d.bo_pct != null ? `+${d.bo_pct.toFixed(1)}%` : "—";
    const boLabel = d.bo_pct >= 7 ? "Surge" : d.bo_pct >= 3 ? "Strong" : "Clean";
    const rsiNum = d.rsi != null ? d.rsi.toFixed(1) : "—";
    const rsiCls = d.rsi >= 60 ? "green" : d.rsi >= 50 ? "accent-orange" : "";
    const rsiNote = d.rsi >= 60 ? "Strong momentum" : "Positive momentum";
    const freshBars = d.bars_since_high != null ? d.bars_since_high : "—";
    const freshNote = d.bars_since_high <= 2 ? "Very fresh" : d.bars_since_high <= 5 ? "Recent" : "Older";
    const freshCls = d.bars_since_high <= 2 ? "green" : d.bars_since_high <= 5 ? "accent-orange" : "";
    const comprNote = d.compression ? `ATR ${d.atr_before_rel}% → ${d.atr_now_rel}% · coiling` : `ATR ${d.atr_now_rel || "—"}% · no contraction`;
    const comprCls = d.compression ? "green" : "muted";
    const adxVal = d.adx != null ? d.adx.toFixed(1) : "—";
    const adxCls = d.adx_strong && d.adx_rising ? "green" : d.adx_strong ? "accent-orange" : "";
    const adxNote = d.adx_strong && d.adx_rising ? "Strong + rising" : d.adx_strong ? "Strong (flat)" : "Below threshold";

    return `<div class="row-detail">
      ${heroStrip(r, cur, r.entry, r.stop, r.target, r.stop_pct, r.p2_pct)}
      ${chipsBar(r)}
      ${metaBar(r)}
      <div class="rd-analysis"><p>${esc(r.analysis || "")}</p></div>
      ${priceStrip(r)}

      <div class="rd-group">
        <div class="rd-section">Breakout quality</div>
        <div class="rd-levels">
          <div class="dl-row"><span class="dl-label green">Range high (breakout level)</span>
            <span class="dl-val">${cur}${num(d.range_high)}</span>
            <span class="dl-pct pct-up">${boPct} above · ${boLabel}</span></div>
          <div class="dl-row"><span class="dl-label red">Range low / stop zone</span>
            <span class="dl-val">${cur}${num(d.range_low)}</span>
            <span class="dl-pct muted">${d.consol_bars || "—"} bar base · ${d.range_span_pct || "—"}% range</span></div>
          <div class="dl-row"><span class="dl-label ${freshCls}">Freshness</span>
            <span class="dl-val">${freshBars} bar${freshBars === 1 ? "" : "s"} ago</span>
            <span class="dl-pct ${freshCls}">${freshNote}</span></div>
          <div class="dl-row"><span class="dl-label ${comprCls}">Volatility compression</span>
            <span class="dl-val">${d.compression ? "Yes" : "No"}</span>
            <span class="dl-pct muted">${comprNote}</span></div>
        </div>
        <div class="rd-trail">
          <span class="rd-trail-label">Trailing stop</span>
          <span class="rd-trail-val">${cur}${num(d.trailing_stop)}</span>
          <span class="rd-trail-note">${d.trailing_label || ""}</span>
          <span class="dl-pct ${d.trailing_pct >= 0 ? "pct-up" : "pct-down"}">${fmtPct(d.trailing_pct)}</span>
        </div>
      </div>

      <div class="rd-group">
        <div class="rd-section">Moving averages</div>
        <div class="rd-levels">
          ${smRow(20, d.sma20, d.sma20_pct, "#4d9fff")}
          ${smRow(50, d.sma50, d.sma50_pct, "#a78bfa")}
        </div>
      </div>

      <div class="rd-group">
        <div class="rd-section">Momentum &amp; volume</div>
        <div class="rd-volume rd-volume-bare">
          <span class="rd-k">RSI 14</span>
          <span class="rd-vol ${rsiCls}">${rsiNum}</span>
          <span class="rd-vol-note">${rsiNote}</span>
        </div>
        <div class="rd-volume rd-volume-bare">
          <span class="rd-k">Volume</span>
          <span class="rd-vol ${volCls}">${d.volume_ratio != null ? d.volume_ratio.toFixed(1) : "—"}×</span>
          <span class="rd-vol-note">${fmtK(d.volume_today)} today vs ${fmtK(d.volume_avg)} avg</span>
        </div>
        <div class="rd-volume rd-volume-bare">
          <span class="rd-k">ADX 14</span>
          <span class="rd-vol ${adxCls}">${adxVal}</span>
          <span class="rd-vol-note">${adxNote}</span>
        </div>
      </div>
    </div>`;
  }

  // ----------------------------------------------------------- list build
  function buildList() {
    const all = (state.data && state.data.results) || [];
    let list;
    if (state.view === "watch") {
      list = all.filter((r) => isStarred(r.symbol));
    } else if (state.tab === "aplus") {
      list = all.filter((r) => r.grade === "A+");
    } else if (state.tab === "a") {
      list = all.filter((r) => r.grade === "A");
    } else {
      // Watch tab: B/C for the daily scanners; B+/WATCH for VIVEK.
      list = all.filter((r) => ["B", "C", "B+", "WATCH"].includes(r.grade));
    }
    // VIVEK entry-type filter (200 SMA interaction) — union of selected types.
    if (state.mode === "vivek" && state.vkEntry.size) {
      list = list.filter((r) => (r.entry_types || []).some((t) => state.vkEntry.has(t)));
    }
    // VIVEK "triggered recently" filter — only setups that just moved.
    if (state.mode === "vivek" && state.vkRecent) {
      list = list.filter(triggeredRecently);
    }
    // VIVEK "high conviction" filter — weekly reclaims (A / strong structure).
    if (state.mode === "vivek" && state.vkHighConv) {
      list = list.filter(isHighConviction);
    }
    const s = state.sort;
    list = list.slice();
    const n = (v) => (v == null || isNaN(v) ? 0 : v);   // null-safe numeric key
    // Each branch sorts in its NATURAL default direction; flipping the direction
    // (clicking the active sort again) just reverses the result.
    if (s === "price") list.sort((a, b) => n(b.price) - n(a.price));
    else if (s === "rr") list.sort((a, b) => n(b.rr) - n(a.rr));
    else if (s === "mcap") list.sort((a, b) => mcapOf(b.symbol) - mcapOf(a.symbol));   // largest cap first
    else if (s === "az") list.sort((a, b) => String(a.symbol || "").localeCompare(String(b.symbol || "")));
    else list.sort((a, b) => (GRADE_RANK[a.grade] - GRADE_RANK[b.grade]) || (n(b.score) - n(a.score)) || (n(b.rr) - n(a.rr)));
    if (sortDirOf() !== defaultDir(s)) list.reverse();
    return list;
  }

  // VIVEK entry-type filter chips (200 SMA interaction). Shows live counts so
  // the user can read market behaviour: how many setups are reclaiming /
  // retesting / breaking structure at the level. Multi-select; "All" clears.
  const VK_ENTRY = [
    ["reclaim", "Reclaim after rejection", "Close back above 200 SMA after rejection"],
    ["retest",  "Retest + confirmation",   "Retest with confirmation"],
    ["break",   "Break of structure",      "Break of small structure near 200 SMA"],
  ];
  // Backtest quality tier per trigger (long-only walk-forward): reclaim is the
  // edge, break is middling, retest is flat-to-negative. Colour = overall edge
  // (avg R), with the win-rate shown in the tooltip.
  const VK_ENTRY_Q = {
    reclaim: { tier: "green", note: "Best trigger — backtest ≈+1.6R avg, ~56% win (long-only)" },
    break:   { tier: "amber", note: "Middling — positive but rare (small sample)" },
    retest:  { tier: "red",   note: "Weakest — flat-to-negative; the bot skips these" },
  };
  // Data freshness + version badge. Surfaces scan age, coverage and schema so a
  // stale/old-build dataset is visible at a glance instead of silently dropping
  // features. Turns amber when coverage is low, the scan is old, or the committed
  // data was produced by an older build than the frontend expects.
  function renderFreshness(d) {
    const box = $("#scan-fresh");
    if (!box) return;
    if (!d || d.setup_type !== "vivek") { box.hidden = true; box.innerHTML = ""; return; }
    const age = timeAgo(d.generated_at);
    const cov = d.coverage_pct;
    const ver = d.schema_version;
    const behind = ver != null && ver < EXPECTED_SCHEMA;
    const tooOld = /\dd ago/.test(age) && parseInt(age) >= 2;            // ≥2 days stale
    const lowCov = typeof cov === "number" && cov < 80 && (d.universe_size || 0) > 50;
    const warn = behind || tooOld || lowCov;
    const bits = [];
    if (age) bits.push(`⟳ ${age}`);
    if (typeof cov === "number") {
      // Show how much of the coverage is fresh vs reused from the last-good cache.
      const cached = d.from_cache || 0;
      bits.push(cached > 0 ? `${cov}% coverage (${d.fresh ?? "?"} fresh · ${cached} cached)`
                           : `${cov}% coverage`);
    }
    if (ver != null) bits.push(`schema v${ver}`);
    if (behind) bits.push("rescan to enable latest features");
    box.hidden = false;
    box.className = `scan-fresh${warn ? " warn" : ""}`;
    box.textContent = bits.join("  ·  ");
    box.title = d.code_sha ? `Built from ${d.code_sha}` : "";
  }

  function renderEntryFilters(d) {
    const box = $("#vk-filters");
    if (!box) return;
    if (!d || d.setup_type !== "vivek") { box.hidden = true; box.innerHTML = ""; return; }
    const all = d.results || [];
    // If the scan hasn't categorised setups (data from an older build), don't
    // silently vanish — tell the user a rescan unlocks the filters.
    if (!all.some((r) => Array.isArray(r.entry_types) && r.entry_types.length)) {
      if (all.length) {
        box.hidden = false;
        box.innerHTML = `<span class="vkf-label">200 SMA interaction</span>` +
          `<span class="vkf-note">Entry-type filters unlock after the next scan</span>`;
      } else {
        box.hidden = true; box.innerHTML = "";
      }
      return;
    }
    box.hidden = false;
    const count = (code) => all.filter((r) => (r.entry_types || []).includes(code)).length;
    const sel = state.vkEntry;
    const chip = (code, label, full, n) => {
      const active = code === "all" ? sel.size === 0 : sel.has(code);
      const q = VK_ENTRY_Q[code];
      const cls = q ? ` q-${q.tier}` : "";
      const title = q ? `${full} — ${q.note}` : full;
      return `<button class="vkf-chip${cls}${active ? " is-active" : ""}" data-type="${esc(code)}" title="${esc(title)}">${esc(label)} <b>${n}</b></button>`;
    };
    const nRecent = all.filter(triggeredRecently).length;
    const nHigh = all.filter(isHighConviction).length;
    box.innerHTML =
      `<span class="vkf-label">200 SMA interaction</span>` +
      chip("all", "All", "Every VIVEK setup", all.length) +
      VK_ENTRY.map(([c, l, f]) => chip(c, l, f, count(c))).join("") +
      `<span class="vkf-legend" title="Chip colour = backtest edge (avg R)">🟢 best · 🟠 ok · 🔴 weak</span>` +
      `<span class="vkf-sep"></span>` +
      `<button class="vkf-chip vkf-highconv${state.vkHighConv ? " is-active" : ""}" data-high="1" ` +
        `title="The best cell in the backtest: weekly reclaims that are A/A+ or have strong structure">🎯 High conviction <b>${nHigh}</b></button>` +
      `<button class="vkf-chip vkf-recent${state.vkRecent ? " is-active" : ""}" data-recent="1" ` +
        `title="Setups whose trigger fired on or near the latest scanned bar">⚡ Triggered recently <b>${nRecent}</b></button>`;
    box.querySelectorAll(".vkf-chip").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.recent) {
        state.vkRecent = !state.vkRecent;
      } else if (b.dataset.high) {
        state.vkHighConv = !state.vkHighConv;
      } else {
        const t = b.dataset.type;
        if (t === "all") sel.clear();
        else if (sel.has(t)) sel.delete(t);
        else sel.add(t);
      }
      renderEntryFilters(d);   // refresh active states + counts
      renderRows();            // re-filter the list
    }));
  }

  function renderRows() {
    const wrap = $("#results");
    const list = buildList();
    if (!list.length) {
      const msg = state.view === "watch"
        ? { h: "Your watchlist is empty", p: "Tap the ☆ on any setup to add it here." }
        : { h: "No setups in this tab", p: "Try another grade tab or market, or check back after the next scan." };
      wrap.innerHTML = `<div class="placeholder"><h3>${msg.h}</h3><p>${msg.p}</p></div>`;
      return;
    }
    wrap.innerHTML = list.map(rowHtml).join("");
  }

  // ----------------------------------------------------------- apply
  function applyPayload(d) {
    state.data = d;
    state.cur = d.currency_symbol || "$";
    $("#scan-title").textContent = `Last scanned: ${fmtTime(d.generated_at, d.tz_label)}`;
    const dqNote = d.quality_skipped ? `  ·  ${d.quality_skipped} skipped (data quality)` : "";
    const riskNote = d.risk_per_trade ? `  ·  $${d.risk_per_trade} risk/trade` : "";
    $("#scan-sub").textContent = `${d.label} · ${d.universe_size ?? d.scanned} in universe · ${d.results.length} setups${dqNote}${riskNote} · auto-refreshes hourly`;
    renderFreshness(d);
    renderPulse(d.pulse);
    refreshPulseLive(d.pulse);
    renderEntryFilters(d);
    renderLegend(d);
    renderStats(d);
    renderRows();
  }

  function skeleton() {
    $("#results").innerHTML = Array.from({ length: 6 }, () => `<div class="skeleton"></div>`).join("");
  }

  // The app is VIVEK-only; the retired pullback/reversal/spec/short/googy feeds
  // are no longer produced or read.
  const dataFile = (market /* , mode */) => `data/${market}_vivek.json`;

  // Schema the frontend expects. When committed data stamps an older version (a
  // scan ran on an older build), we tell the user to rescan rather than silently
  // dropping features that depend on newer fields.
  const EXPECTED_SCHEMA = 3;

  // "2h ago" / "just now" / "3d ago" from an ISO timestamp, for the freshness badge.
  function timeAgo(iso) {
    const t = Date.parse(iso);
    if (!isFinite(t)) return "";
    const s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 90) return "just now";
    if (s < 3600) return `${Math.round(s / 60)}m ago`;
    if (s < 86400) return `${Math.round(s / 3600)}h ago`;
    return `${Math.round(s / 86400)}d ago`;
  }

  // VIVEK paper-trade track record (expectancy). Read-only summary written by the
  // server-side journal; shows whether the trigger system actually has an edge,
  // broken down by entry type / grade / timeframe. Hidden until trades close.
  async function loadTrackRecord() {
    const box = $("#track");
    if (!box) return;
    try {
      const res = await fetch("data/vivek_journal.json", { cache: "no-cache" });
      if (!res.ok) return;
      const j = await res.json();
      const e = j.expectancy || {};
      const ov = e.overall || { n: 0 };
      const nOpen = (j.open || []).length;
      if (!ov.n && !nOpen) { box.hidden = true; return; }   // nothing to show yet
      const rTone = (r) => (r > 0.05 ? "pos" : r < -0.05 ? "neg" : "");
      const pillRow = (label, s) => {
        if (!s || !s.n) return "";
        return `<div class="trk-pill"><span class="trk-k">${esc(label)}</span>` +
          `<span class="trk-r ${rTone(s.expectancy_r)}">${s.expectancy_r >= 0 ? "+" : ""}${s.expectancy_r}R</span>` +
          `<span class="trk-sub">${s.win_rate}% · n=${s.n}</span></div>`;
      };
      const group = (title, obj, keys) => {
        const inner = keys.map((k) => pillRow(k, obj[k])).join("");
        return inner ? `<div class="trk-group"><div class="trk-title">${esc(title)}</div>${inner}</div>` : "";
      };
      box.hidden = false;
      box.innerHTML =
        `<div class="trk-head">` +
          `<span class="trk-label">Track record · paper</span>` +
          `<span class="trk-headline ${rTone(ov.expectancy_r || 0)}">` +
            `${ov.n ? `${(ov.expectancy_r >= 0 ? "+" : "")}${ov.expectancy_r}R expectancy · ${ov.win_rate}% win · ${ov.n} closed` : "no closed trades yet"}` +
          `</span>` +
          `<span class="trk-open">${nOpen} open</span>` +
          `<a class="trk-more" href="track.html">Full track record →</a>` +
        `</div>` +
        `<div class="trk-groups">` +
          group("Entry type", e.by_entry_type || {}, ["reclaim", "retest", "break"]) +
          group("Grade", e.by_grade || {}, ["A+", "A"]) +
          group("Timeframe", e.by_timeframe || {}, ["1D", "1W", "4H"]) +
        `</div>` +
        `<div class="trk-note">Paper trades from ARMED A+/A setups — opened during market hours at the delayed intraday price and marked-to-market by the 5.0 scale-out/SL rules. Early data — read directionally.</div>`;
    } catch (_) { /* track record is optional */ }
  }

  async function loadCaps() {
    try {
      const res = await fetch("data/market_caps.json", { cache: "no-cache" });
      if (!res.ok) return;
      const raw = await res.json();
      // Cache stores {"asx:BHP": {"mcap": 1.2e9, "ts": "..."}}; flatten to floats.
      const flat = {};
      for (const k in raw) {
        const v = raw[k];
        const mc = v && typeof v === "object" ? v.mcap : v;
        if (mc) flat[k] = +mc;
      }
      state.caps = flat;
      if (state.data) renderRows();   // re-render if rows are already on screen
    } catch (_) { /* caps are optional */ }
  }

  async function load(silent = false) {
    const { market, mode } = state;
    const key = `${market}:${mode}`;
    if (!silent) {
      $("#scan-title").textContent = "Loading latest scan…";
      skeleton();
    }
    // Check localStorage cache first (5-min TTL)
    if (!state.cache[key]) {
      const lsCached = cacheGet(key);
      if (lsCached) state.cache[key] = lsCached;
    }
    if (state.cache[key]) { applyPayload(state.cache[key]); return; }
    try {
      const res = await fetch(dataFile(market, mode), { cache: "no-cache" });
      if (!res.ok) throw new Error(res.status);
      const d = await res.json();
      state.cache[key] = d;
      cacheSet(key, d);
      applyPayload(d);
    } catch (e) {
      if (!silent) {
        $("#scan-title").textContent = "No scan data yet";
        $("#results").innerHTML = `<div class="placeholder"><h3>No ${mode} data for ${market.toUpperCase()}</h3>
          <p>Run the scanner to generate the data, then refresh.</p></div>`;
      }
    }
  }

  // ----------------------------------------------------------- search overlay
  function openSearch() {
    const overlay = document.getElementById("search-overlay");
    const input   = document.getElementById("search-input");
    if (!overlay) return;
    overlay.removeAttribute("hidden");
    if (input) { input.value = ""; input.focus(); }
    const res = document.getElementById("search-results");
    if (res) res.innerHTML = "";
  }
  function closeSearch() {
    const overlay = document.getElementById("search-overlay");
    if (!overlay) return;
    overlay.setAttribute("hidden", "");
    const input = document.getElementById("search-input");
    if (input) input.value = "";
    const res = document.getElementById("search-results");
    if (res) res.innerHTML = "";
  }

  // ----------------------------------------------------------- keyboard
  function initKeyboard() {
    document.addEventListener("keydown", (e) => {
      const overlay = document.getElementById("search-overlay");
      const isSearchOpen = overlay && !overlay.hasAttribute("hidden");
      const inInput = ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName);

      if (e.key === "/" && !isSearchOpen && !inInput) {
        e.preventDefault(); openSearch(); return;
      }
      if (e.key === "Escape") {
        if (isSearchOpen) { closeSearch(); return; }
        document.querySelectorAll(".row-wrap.open").forEach((w) => w.classList.remove("open"));
        return;
      }
      if (e.key === "D" && e.ctrlKey && e.shiftKey) {
        e.preventDefault(); toggleDebug(); return;
      }
      if ((e.key === "j" || e.key === "ArrowDown") && !isSearchOpen && !inInput) {
        e.preventDefault();
        const rows = [...document.querySelectorAll(".row-wrap")];
        const cur = document.querySelector(".row-wrap:focus");
        const idx = cur ? rows.indexOf(cur) : -1;
        const next = rows[idx + 1];
        if (next) { next.setAttribute("tabindex", "0"); next.focus(); }
        return;
      }
      if ((e.key === "k" || e.key === "ArrowUp") && !isSearchOpen && !inInput) {
        e.preventDefault();
        const rows = [...document.querySelectorAll(".row-wrap")];
        const cur = document.querySelector(".row-wrap:focus");
        const idx = cur ? rows.indexOf(cur) : rows.length;
        const prev = rows[idx - 1];
        if (prev) { prev.setAttribute("tabindex", "0"); prev.focus(); }
        return;
      }
    });
  }

  // ----------------------------------------------------------- events
  function bind() {
    function syncMarketUI() {
      document.querySelectorAll(".market-btn").forEach((x) => {
        const on = x.dataset.market === state.market;
        x.classList.toggle("is-active", on);
        x.setAttribute("aria-selected", on ? "true" : "false");
      });
    }

    document.querySelectorAll(".market-btn").forEach((b) => b.addEventListener("click", () => {
      if (b.classList.contains("is-active")) return;
      document.querySelectorAll(".market-btn").forEach((x) => {
        x.classList.toggle("is-active", x === b);
        x.setAttribute("aria-selected", x === b ? "true" : "false");
      });
      state.market = b.dataset.market;
      savePrefs();
      load();
    }));

    // Poll for a new generated_at after triggering a cloud scan.
    // Checks every 30s for up to 5 minutes, then gives up quietly.
    async function pollForFreshScan(oldGenAt) {
      for (let i = 0; i < 10; i++) {
        await new Promise(r => setTimeout(r, 30000));
        try {
          const url = dataFile(state.market, state.mode);
          const r = await fetch(url, { cache: "no-cache" });
          if (!r.ok) continue;
          const d = await r.json();
          if (d.generated_at && d.generated_at !== oldGenAt) {
            const key = `${state.market}:${state.mode}`;
            state.cache[key] = d;
            applyPayload(d);
            startAutoRefresh();
            flashScan(`Scan complete — updated to ${fmtTime(d.generated_at, d.tz_label)}.`, "ok");
            return;
          }
        } catch (_) {}
      }
    }

    $("#reload-btn").addEventListener("click", async () => {
      const btn = $("#reload-btn");
      if (btn.disabled) return;
      btn.classList.add("spinning");
      btn.disabled = true;
      const oldGenAt = state.data && state.data.generated_at;
      // Scan only the market currently being viewed — fast, targeted refresh.
      const mkt = state.market || "all";
      flashScan(`Requesting a fresh ${mkt.toUpperCase()} scan…`, "info");
      // Kick off a fresh cloud scan. Falls back gracefully if not configured.
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 12000);
      let scanTriggered = false;
      try {
        const res = await fetch("/api/scan", {
          method: "POST", signal: ctrl.signal,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ market: mkt }),
        });
        const data = await res.json().catch(() => ({}));
        const kind = res.ok ? "ok" : (res.status === 503 || data.configured === false) ? "info" : "warn";
        flashScan(data.message || (res.ok ? "Scan started — results will update in ~3 min." : "Couldn't start a scan — reloaded latest data."), kind);
        scanTriggered = res.ok;
      } catch (err) {
        flashScan(err && err.name === "AbortError"
          ? "Scan service timed out — reloaded latest data instead."
          : "Couldn't reach the scan service — reloaded latest data.", "warn");
      } finally {
        clearTimeout(timer);
      }
      // Show current data immediately; then poll for the fresh data in the background
      delete state.cache[`${state.market}:${state.mode}`];
      await load();
      setTimeout(() => {
        btn.classList.remove("spinning");
        btn.disabled = false;
      }, 800);
      if (scanTriggered) pollForFreshScan(oldGenAt);
    });

    function flashScan(msg, kind) {
      let el = document.getElementById("scan-toast");
      if (!el) {
        el = document.createElement("div");
        el.id = "scan-toast";
        el.className = "scan-toast";
        document.body.appendChild(el);
      }
      el.textContent = msg;
      el.classList.toggle("warn", kind === "warn");
      el.classList.toggle("info", kind === "info");
      el.classList.add("show");
      clearTimeout(el._t);
      el._t = setTimeout(() => el.classList.remove("show"), 6000);
    }

    document.querySelectorAll(".scan-btn").forEach((b) => b.addEventListener("click", () => {
      if (b.classList.contains("is-active")) return;
      document.querySelectorAll(".scan-btn").forEach((x) => {
        x.classList.toggle("is-active", x === b);
        x.setAttribute("aria-selected", x === b ? "true" : "false");
      });
      state.mode = b.dataset.mode;
      savePrefs();
      syncMarketUI();
      load();
    }));

    document.querySelectorAll(".view-tab").forEach((b) => b.addEventListener("click", () => {
      state.view = b.dataset.view;
      document.querySelectorAll(".view-tab").forEach((x) => {
        x.classList.toggle("is-active", x === b);
        x.setAttribute("aria-selected", x === b ? "true" : "false");
      });
      renderRows();
    }));

    document.querySelectorAll("#tabs .seg-btn").forEach((b) => b.addEventListener("click", () => {
      state.tab = b.dataset.tab;
      savePrefs();
      if (state.view !== "results") {
        state.view = "results";
        document.querySelectorAll(".view-tab").forEach((x) => x.classList.toggle("is-active", x.dataset.view === "results"));
      }
      document.querySelectorAll("#tabs .seg-btn").forEach((x) => x.classList.toggle("is-active", x === b));
      renderRows();
    }));

    document.querySelectorAll("#sorts .seg-btn").forEach((b) => b.addEventListener("click", () => {
      const s = b.dataset.sort;
      if (state.sort === s) state.sortDir = (sortDirOf() === "asc" ? "desc" : "asc");  // toggle direction
      else { state.sort = s; state.sortDir = defaultDir(s); }                          // new sort → its default
      savePrefs();
      updateSortButtons();
      renderRows();
    }));

    // Search overlay wiring
    const searchTrigger = document.getElementById("search-trigger");
    const searchInput   = document.getElementById("search-input");
    const searchResults = document.getElementById("search-results");
    const searchOverlay = document.getElementById("search-overlay");
    if (searchTrigger) searchTrigger.addEventListener("click", openSearch);
    if (searchOverlay) searchOverlay.addEventListener("click", (e) => {
      if (e.target === searchOverlay) closeSearch();
    });
    if (searchInput) searchInput.addEventListener("input", () => {
      const q = searchInput.value.trim().toLowerCase();
      if (!q) { searchResults.innerHTML = ""; return; }
      const all = (state.data && state.data.results) || [];
      const hits = all.filter((r) =>
        r.symbol.toLowerCase().includes(q) || (r.name || "").toLowerCase().includes(q)
      ).slice(0, 12);
      if (!hits.length) {
        searchResults.innerHTML = `<div class="sr-empty">No results for "${esc(searchInput.value)}"</div>`;
        return;
      }
      searchResults.innerHTML = hits.map((r) => {
        const href = `chart.html?m=${state.market}&s=${encodeURIComponent(r.symbol)}${state.mode !== "pullback" ? `&mode=${state.mode}` : ""}`;
        return `<a class="sr-row" href="${href}">
          <span class="sr-grade" style="color:${GRADE_VAR[r.grade] || "var(--grade-c)"}">${esc(r.grade)}</span>
          <span class="sr-sym">${esc(r.symbol)}</span>
          <span class="sr-name">${esc(r.name || "")}</span>
          <span class="sr-price">${fmtPrice(r.price)}</span>
        </a>`;
      }).join("");
      // Close overlay when user clicks a result link
      searchResults.querySelectorAll(".sr-row").forEach((a) => a.addEventListener("click", closeSearch));
    });

    // Row interactions (delegated): star toggle, copy-debug, chart link, expand details.
    $("#results").addEventListener("click", (e) => {
      const copyBtn = e.target.closest(".row-copy-debug");
      if (copyBtn) {
        const sym = copyBtn.dataset.sym;
        const r = (state.data && state.data.results || []).find((x) => x.symbol === sym);
        if (r && navigator.clipboard) {
          navigator.clipboard.writeText(JSON.stringify(r, null, 2)).then(() => {
            copyBtn.style.color = "var(--green)";
            setTimeout(() => { copyBtn.style.color = ""; }, 1400);
          }).catch(() => {});
        }
        e.stopPropagation();
        return;
      }
      const star = e.target.closest(".t-star");
      if (star) {
        toggleStar(star.dataset.sym);
        $("#watch-count").textContent = (state.data.results || []).filter((r) => isStarred(r.symbol)).length;
        if (state.view === "watch") { renderRows(); return; }
        const on = isStarred(star.dataset.sym);
        star.classList.toggle("starred", on);
        const svg = star.querySelector("svg");
        if (svg) svg.setAttribute("fill", on ? "currentColor" : "none");
        return;
      }
      if (e.target.closest("a.tkr") || e.target.closest("a.row-spark")) return;  // -> chart page
      const wrap = e.target.closest(".row-wrap");
      if (wrap) wrap.classList.toggle("open");
    });
  }

  // ---- daily rotating quote + live clocks --------------------------------
  const TRADER_QUOTES = [
    ["The big money is not in the individual fluctuations but in the main movements.", "Jesse Livermore"],
    ["The market is never wrong — opinions often are.", "Jesse Livermore"],
    ["There is only one side of the market, and it is not the bull side or the bear side, but the right side.", "Jesse Livermore"],
    ["Profits always take care of themselves but losses never do.", "Jesse Livermore"],
    ["There is a time to go long, a time to go short, and a time to go fishing.", "Jesse Livermore"],
    ["I'm always thinking about losing money as opposed to making money.", "Paul Tudor Jones"],
    ["The most important rule of trading is to play great defence, not great offence.", "Paul Tudor Jones"],
    ["Every day I assume every position I have is wrong.", "Paul Tudor Jones"],
    ["Be fearful when others are greedy, and greedy when others are fearful.", "Warren Buffett"],
    ["Price is what you pay. Value is what you get.", "Warren Buffett"],
    ["It's not whether you're right or wrong, but how much money you make when you're right.", "George Soros"],
    ["Markets are constantly in a state of uncertainty. Money is made by discounting the obvious and betting on the unexpected.", "George Soros"],
    ["The trend is your friend until the end when it bends.", "Ed Seykota"],
    ["Win or lose, everybody gets what they want out of the market.", "Ed Seykota"],
    ["If you can't take a small loss, sooner or later you will take the mother of all losses.", "Ed Seykota"],
    ["Ride your winners and cut your losers.", "Ed Seykota"],
    ["Know what you own and know why you own it.", "Peter Lynch"],
    ["In this business, if you're good, you're right six times out of ten. You're never going to be right nine times out of ten.", "Peter Lynch"],
    ["The key to trading success is emotional discipline. If intelligence were the key, there would be a lot more people making money trading.", "Victor Sperandeo"],
    ["The whole secret to winning in the stock market is to lose the least amount possible when you're wrong.", "William O'Neil"],
    ["I buy on the way up, not on the way down.", "Nicolas Darvas"],
    ["Don't try to buy at the bottom and sell at the top. It can't be done except by liars.", "Bernard Baruch"],
    ["Whenever I enter a position, I have a predetermined stop. That's the only way I can sleep.", "Bruce Kovner"],
    ["I just wait until there is money lying in the corner, and all I have to do is go over there and pick it up.", "Jim Rogers"],
    ["The time of maximum pessimism is the best time to buy, and the time of maximum optimism is the best time to sell.", "John Templeton"],
    ["Preserve capital. You can't trade if you don't have any capital.", "Stan Druckenmiller"],
    ["Risk comes from not knowing what you're doing.", "Warren Buffett"],
    ["Markets can remain irrational longer than you can remain solvent.", "John Maynard Keynes"],
    ["Trading is a waiting game. You sit, you wait, and you make a lot of money all at once.", "Jim Rogers"],
    ["The goal of a successful trader is to make the best trades. Money is secondary.", "Alexander Elder"],
    ["An investment in knowledge pays the best interest.", "Benjamin Franklin"],
    ["The stock market is filled with individuals who know the price of everything, but the value of nothing.", "Philip Fisher"],
    ["In the short run the market is a voting machine, but in the long run it is a weighing machine.", "Benjamin Graham"],
    ["Compound interest is the eighth wonder of the world. He who understands it, earns it; he who doesn't, pays it.", "Albert Einstein"],
    ["The four most dangerous words in investing are: 'This time it's different.'", "John Templeton"],
    ["Successful investing is about managing risk, not avoiding it.", "Benjamin Graham"],
  ];

  function initDailyQuote() {
    const el = document.getElementById("topbar-quote");
    if (!el) return;
    const idx = Math.floor(Date.now() / 86400000) % TRADER_QUOTES.length;
    const [text, author] = TRADER_QUOTES[idx];
    el.textContent = `"${text}" — ${author}`;
    el.title = `"${text}" — ${author}`;
  }

  const _melFmt  = new Intl.DateTimeFormat("en-AU", { timeZone: "Australia/Melbourne", weekday: "short", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const _melDate = new Intl.DateTimeFormat("en-AU", { timeZone: "Australia/Melbourne", day: "2-digit", month: "short", year: "numeric" });
  const _nyFmt   = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York",    weekday: "short", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const _nyDate  = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York",    day: "2-digit",   month: "short", year: "numeric" });

  function _fmtClock(fmt, dateFmt, now) {
    const parts = fmt.formatToParts(now);
    const get = (t) => (parts.find((p) => p.type === t) || {}).value || "";
    const time = `${get("weekday")} ${get("hour")}:${get("minute")}:${get("second")}`;
    const date = dateFmt.format(now);
    return [time, date];
  }

  function updateClocks() {
    const now = new Date();
    const [melTime, melDate] = _fmtClock(_melFmt, _melDate, now);
    const [nyTime,  nyDate]  = _fmtClock(_nyFmt,  _nyDate,  now);
    const mt = document.getElementById("clk-mel-time"); if (mt) mt.textContent = melTime;
    const md = document.getElementById("clk-mel-date"); if (md) md.textContent = melDate;
    const nt = document.getElementById("clk-ny-time");  if (nt) nt.textContent = nyTime;
    const nd = document.getElementById("clk-ny-date");  if (nd) nd.textContent = nyDate;
  }

  initDailyQuote();
  updateClocks();
  setInterval(updateClocks, 1000);

  initKeyboard();
  bind();
  loadCaps();
  loadTrackRecord();
  load().then(() => startAutoRefresh());
})();
