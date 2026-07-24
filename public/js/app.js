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
      // Deliberately DO NOT restore p.mode: VIVEK 5.0 is the only scanner now,
      // and a stale mode persisted from an older build (e.g. "pullback") would
      // silently disable every VIVEK filter (all gated on mode === "vivek") —
      // the bug where Longs/Shorts + High conviction toggled but didn't filter.
      state.mode = "vivek";
      if (p.tab)    state.tab    = p.tab;
      if (p.sort)   state.sort   = p.sort;
      if (p.sortDir) state.sortDir = p.sortDir;
      state.dimFunds = p.dimFunds !== false;   // v2 #47: dim FUND/REIT rows, default ON
    } catch (_) {}
  }
  function savePrefs() {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify({
        market: state.market, mode: state.mode,
        tab: state.tab, sort: state.sort, sortDir: state.sortDir,
        dimFunds: state.dimFunds !== false,
      }));
    } catch (_) {}
  }

  // ---- localStorage scan cache with TTL -----------------------------------
  function cacheSet(key, data) {
    try {
      const payload = JSON.stringify({ ts: Date.now(), data });
      // Size cap (2026-07-20): full NASDAQ/ASX scans are 1-2MB each; three of
      // them squeezed localStorage's ~5MB origin quota and could make the
      // manual journal's save FAIL — a silently lost trade. Oversized scans
      // skip the cache (cold loads just refetch); small markets still cache.
      if (payload.length > 500_000) return;
      localStorage.setItem(CACHE_PREFIX + key, payload);
    }
    catch (_) {}
  }
  function cacheGet(key) {
    try {
      const item = JSON.parse(localStorage.getItem(CACHE_PREFIX + key) || "null");
      if (item && Date.now() - item.ts < CACHE_TTL_MS) return item.data;
    } catch (_) {}
    return null;
  }

  // ── Stale-while-revalidate cache additions (UI Wave 1, 2026-07-22) ────────
  // cacheGetStale returns an EXPIRED full payload (cacheGet hides those) so a
  // cold paint can show the last-known scan instantly while the fresh fetch
  // runs in the background. The slim "head" cache is a second, always-written
  // entry — stats + the first HEAD_ROWS rows with the heavy per-row fields
  // (spark/detail/plans/analysis) stripped — so a market whose full payload
  // exceeds the 500KB cacheSet cap (kept: it protects the manual journal's
  // localStorage quota) still paints instantly. Head payloads are marked
  // _head, shown only under the "updating…" flag, and NEVER enter state.cache.
  const HEAD_PREFIX = "gbs:cache:head:";
  const HEAD_ROWS   = 60;
  function cacheGetStale(key) {
    try {
      const item = JSON.parse(localStorage.getItem(CACHE_PREFIX + key) || "null");
      if (item && item.data) return item.data;
    } catch (_) {}
    return null;
  }
  function cacheSetHead(key, data) {
    try {
      const rows = ((data && data.results) || []).slice(0, HEAD_ROWS)
        .map(({ spark, detail, plans, analysis, ...slim }) => slim);
      const head = { ...data, results: rows, _head: true,
                     _full_count: ((data && data.results) || []).length };
      const payload = JSON.stringify({ ts: Date.now(), data: head });
      if (payload.length > 500_000) return;   // same cap as cacheSet — never raised
      localStorage.setItem(HEAD_PREFIX + key, payload);
    } catch (_) {}
  }
  function cacheGetHead(key) {
    try {
      const item = JSON.parse(localStorage.getItem(HEAD_PREFIX + key) || "null");
      if (item && item.data) return item.data;
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
    dataKey: null,      // "<market>:<mode>" the on-screen data belongs to
    staleView: false,   // true = SWR paint awaiting fresh · "failed" = refresh failed
    cache: {},
    cur: "$",
    caps: {},           // "<market>:<symbol>" -> raw market cap (float)
    vkEntry: new Set(), // VIVEK entry-type filter; empty = All
    vkRecent: false,    // VIVEK "triggered recently" filter toggle
    vkHighConv: false,  // VIVEK "high conviction" filter (weekly reclaim + A/strong structure)
    vkDir: null,        // direction filter: null = both · "LONG" · "SHORT"
    vkConfl: false,     // deck pill (Wave 3): only rows with 2+ lens alignment
    vkAtLevel: false,   // deck pill (Wave 3): only rows sitting ON a 200-SMA now
  };

  // Sort direction. Each sort has a natural default (numeric → descending,
  // alphabetical → ascending); clicking the already-active sort flips it. The
  // active button shows a ↑ / ↓ arrow for the current direction.
  const SORT_DEFAULT_DIR = { score: "desc", price: "desc", rr: "desc", mcap: "desc", az: "asc" };
  const defaultDir = (sort) => SORT_DEFAULT_DIR[sort] || "desc";
  const sortDirOf  = () => state.sortDir || defaultDir(state.sort);
  // Compact cycling sort (backlog #2): one control instead of five buttons.
  // The label advances through the cycle; the arrow flips direction.
  const SORT_CYCLE = ["score", "price", "rr", "mcap", "az"];
  const SORT_LABEL = { score: "SCORE", price: "PRICE", rr: "R:R", mcap: "M.C", az: "A-Z" };
  function updateSortButtons() {
    const label = document.getElementById("sort-cycle");
    const dir = document.getElementById("sort-dir");
    if (label) label.textContent = SORT_LABEL[state.sort] || String(state.sort).toUpperCase();
    if (dir) dir.textContent = sortDirOf() === "asc" ? "↑" : "↓";
  }
  // ★ watch toggle (backlog #1): the old Results/Watch tab pair as one chip.
  function syncWatchToggle() {
    const b = document.getElementById("watch-toggle");
    if (!b) return;
    const on = state.view === "watch";
    b.classList.toggle("is-active", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");
  }
  // ⚠ FUNDS chip (v2 #47): active = FUND/REIT rows dimmed.
  function syncFundDim() {
    const b = document.getElementById("fund-dim");
    if (!b) return;
    const on = state.dimFunds !== false;
    b.classList.toggle("is-active", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");
  }

  loadPrefs();
  // Deep link (backlog #16): ?m=asx|nasdaq|crypto opens the dashboard already
  // switched to that market (e.g. the RECS cards' "Open scan →"). Overrides
  // the saved pref and persists, so a refresh keeps you where the link put you.
  try {
    const qm = new URLSearchParams(location.search).get("m");
    if (qm && ["asx", "nasdaq", "crypto"].includes(qm.toLowerCase())) {
      state.market = qm.toLowerCase();
      savePrefs();
    }
  } catch (_) {}
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
    syncWatchToggle();
    syncFundDim();
  })();

  // Sticky toolbar (backlog #1+3): pin the merged filter line right under the
  // topbar (whose height varies by breakpoint — measure it into a CSS var)
  // and condense to a slim variant once the deck has scrolled away.
  (function stickyToolbar() {
    const bar = document.getElementById("toolbar");
    if (!bar) return;
    const top = document.querySelector(".topbar");
    const setH = () =>
      document.documentElement.style.setProperty("--topbar-h", `${top ? top.offsetHeight : 0}px`);
    setH();
    window.addEventListener("resize", setH, { passive: true });
    let raf = 0;
    window.addEventListener("scroll", () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        bar.classList.toggle("is-slim", window.scrollY > 120);
        raf = 0;
      });
    }, { passive: true });
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
  // Since 2026-07-03 stars live in the UNIFIED synced store (PM.watch inside
  // the GBSSync journal — mirrors to Cloudflare KV with a sync code, so stars
  // follow phone <-> desktop). The legacy localStorage set migrates itself.
  const _pmWatch = () => (window.PM && PM.watch) || null;
  const isStarred = (sym) => {
    const w = _pmWatch();
    if (w) return w.has("vivek", state.market, sym);
    try { return new Set(JSON.parse(localStorage.getItem(WATCH_KEY) || "[]")).has(`${state.market}:${sym}`); }
    catch (_) { return false; }
  };
  // #55: cross-lens watch — which lenses have starred this name (current
  // market). Powers the ★ watch view's per-lens badges + inclusion.
  const LENS_TAG = [["vivek", "V"], ["phasemap", "P"], ["specs", "S"]];
  const LENS_NAME = { V: "VIVEK", P: "PhaseMap", S: "Specs" };
  function lensStars(sym) {
    const w = _pmWatch();
    if (!w) return isStarred(sym) ? ["V"] : [];
    return LENS_TAG.filter(([ns]) => w.has(ns, state.market, sym)).map(([, t]) => t);
  }
  const isWatchedAny = (sym) => lensStars(sym).length > 0;
  function toggleStar(sym) {
    const w = _pmWatch();
    if (w) {
      const r = (state.data && state.data.results || []).find((x) => x.symbol === sym) || null;
      w.toggle("vivek", state.market, sym,
        r ? { symbol: sym, name: r.name, grade: r.grade, dir: r.dir, price: r.price } : null);
      return;
    }
    try {
      const s = new Set(JSON.parse(localStorage.getItem(WATCH_KEY) || "[]"));
      const k = `${state.market}:${sym}`;
      s.has(k) ? s.delete(k) : s.add(k);
      localStorage.setItem(WATCH_KEY, JSON.stringify([...s]));
    } catch (_) {}
  }

  // Long-press quick actions (#45): a scrimmed sheet with Chart / Star /
  // Journal for one ticker. Built lazily, reused across presses.
  function openQuickActions(sym) {
    if (!sym) return;
    const r = (state.data && state.data.results || []).find((x) => x.symbol === sym) || {};
    const starred = isStarred(sym);
    let scrim = document.getElementById("qa-scrim");
    if (!scrim) {
      scrim = document.createElement("div");
      scrim.id = "qa-scrim";
      scrim.className = "qa-scrim";
      document.body.appendChild(scrim);
      scrim.addEventListener("click", (e) => { if (e.target === scrim) closeQuickActions(); });
    }
    const chartHref = `chart.html?m=${state.market}&s=${encodeURIComponent(sym)}&mode=vivek`;
    scrim.innerHTML =
      `<div class="qa-sheet" role="dialog" aria-modal="true" aria-label="Actions for ${esc(sym)}">` +
        `<div class="more-sheet-grip" aria-hidden="true"></div>` +
        `<div class="qa-hd"><b>${esc(sym)}</b>${r.name ? `<span>${esc(r.name)}</span>` : ""}</div>` +
        `<a class="qa-act" href="${chartHref}"><span class="qa-ico">📈</span> View chart</a>` +
        `<button class="qa-act" type="button" data-act="star"><span class="qa-ico">${starred ? "★" : "☆"}</span> ${starred ? "Remove from watchlist" : "Add to watchlist"}</button>` +
        `<a class="qa-act" href="journal.html"><span class="qa-ico">📒</span> Open journal</a>` +
        `<button class="qa-act qa-cancel" type="button">Cancel</button>` +
      `</div>`;
    scrim.hidden = false;
    requestAnimationFrame(() => scrim.classList.add("is-open"));
    scrim.querySelector('[data-act="star"]').addEventListener("click", () => {
      toggleStar(sym);
      if (navigator.vibrate) { try { navigator.vibrate(12); } catch (_) {} }
      const nowStar = isStarred(sym);
      // reflect on the underlying row without a full re-render
      const rowStar = document.querySelector(`.row-wrap[data-sym="${CSS.escape(sym)}"] .t-star`);
      if (rowStar) { rowStar.classList.toggle("starred", nowStar); const svg = rowStar.querySelector("svg"); if (svg) svg.setAttribute("fill", nowStar ? "currentColor" : "none"); }
      const wc = $("#watch-count"); if (wc && state.data) wc.textContent = (state.data.results || []).filter((x) => isStarred(x.symbol)).length;
      closeQuickActions();
    });
    scrim.querySelector(".qa-cancel").addEventListener("click", closeQuickActions);
    document.addEventListener("keydown", _qaEsc);
  }
  function _qaEsc(e) { if (e.key === "Escape") closeQuickActions(); }
  function closeQuickActions() {
    const scrim = document.getElementById("qa-scrim");
    if (!scrim) return;
    scrim.classList.remove("is-open");
    document.removeEventListener("keydown", _qaEsc);
    setTimeout(() => { scrim.hidden = true; }, 200);
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
    const x = (i) => (i * step);
    const y = (v) => (h - ((v - min) / rng) * h);
    const pts = vals.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    // #54: min/max markers — a hollow dot at the low and high of the window,
    // each carrying an SVG <title> so a hover/tap reveals the exact value.
    const iMax = vals.indexOf(max), iMin = vals.indexOf(min);
    const dot = (i, v, c) => `<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="1.8" fill="${c}" stroke="var(--bg)" stroke-width="0.8"><title>${v}</title></circle>`;
    const markers = `${dot(iMax, max, "var(--green)")}${dot(iMin, min, "var(--red)")}`;
    return `<svg class="${cls || ""}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>${markers}</svg>`;
  }

  // PULSE fully removed (2026-07-20, hygiene): the UI section went 2026-07-03,
  // the scanner stopped publishing data 2026-07-09, but ~75 lines of render +
  // a 90-second /api/quote polling interval were still shipped and ARMED
  // whenever old cached data carried a non-empty pulse array. Payloads keep an
  // empty "pulse" key for one release; nothing reads it here anymore.

  // Offline visibility (2026-07-20): the service worker serves cached /data
  // when the network is gone — fine for reading, but it must never READ as
  // live on a trading dashboard. Persistent amber banner while offline.
  function _netBanner(off) {
    let el = document.getElementById("gbs-offline-banner");
    if (!off) { if (el) el.remove(); return; }
    if (!el) {
      el = document.createElement("div");
      el.id = "gbs-offline-banner";
      el.style.cssText = "position:fixed;bottom:14px;left:50%;transform:translateX(-50%);"
        + "z-index:9999;background:#ff9500;color:#000;padding:8px 16px;border-radius:10px;"
        + "font-weight:600;font-size:12.5px;box-shadow:0 6px 24px rgba(0,0,0,.4)";
      el.textContent = "OFFLINE — showing the last cached scan, not live data.";
      document.body.appendChild(el);
    }
  }
  window.addEventListener("offline", () => _netBanner(true));
  window.addEventListener("online", () => _netBanner(false));
  if (navigator.onLine === false) _netBanner(true);

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

  // ------------------------------------------------- deck pills (Wave 3)
  // Replaces the 4 stat cards + at-level strip + confluence banner. A+/A are
  // shortcuts to the grade tabs; Multi-lens and At-level are FILTER TOGGLES
  // (the old banners' content, now one click away instead of two strips).
  // Fund/REIT-excluded logic for the tradeable count is unchanged.
  function renderDeckPills(d) {
    const box = $("#deck-pills");
    if (!box) return;
    const res = (d && d.results) || [];
    const real = res.filter((r) => !isFundReit(r));
    const tradeable = real.filter((r) => r.grade === "A+" || r.grade === "A");
    const top = real.slice()
      .sort((a, b) => (GRADE_RANK[a.grade] - GRADE_RANK[b.grade]) || (b.score - a.score))[0];
    const nAplus = res.filter((r) => r.grade === "A+").length;
    const nA = res.filter((r) => r.grade === "A").length;
    const nAt = res.filter((r) => r.at_level).length;
    const nConf = state.confl ? state.confl.all().length : null;
    const pill = (attrs, cls, label, n, title, active) =>
      `<button class="fpill ${cls}${active ? " is-active" : ""}" ${attrs} title="${esc(title)}">` +
      `${label}${n == null ? "" : ` <b>${n}</b>`}</button>`;
    box.innerHTML =
      pill(`data-goto="aplus"`, "g", "A+", nAplus, "Show the A+ tab", state.view === "results" && state.tab === "aplus") +
      pill(`data-goto="a"`, "", "A", nA, "Show the A tab", state.view === "results" && state.tab === "a") +
      pill(`data-pill="confl"`, "o", "⨂ Multi-lens", nConf ?? "…",
        "Names with 2+ lenses aligned right now — click to filter the list to them", state.vkConfl) +
      pill(`data-pill="atlevel"`, "t", "◎ At level", nAt,
        "Sitting ON a 200-SMA right now — the moment before the reaction. Click to filter.", state.vkAtLevel) +
      (top ? `<a class="fpill top" href="chart.html?m=${state.market}&s=${encodeURIComponent(top.symbol)}&mode=vivek" ` +
        `title="Top tradeable pick (funds/REITs excluded) — open the chart">★ ${esc(top.symbol)} ${fmtPrice(top.price)}</a>` : "") +
      `<span class="deck-npick" title="A+/A setups excluding funds/REITs — what's actually tradeable">${tradeable.length} tradeable</span>`;
    box.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => {
      state.view = "results";
      state.tab = b.dataset.goto;
      syncWatchToggle();
      document.querySelectorAll("#tabs .seg-btn").forEach((x) => x.classList.toggle("is-active", x.dataset.tab === state.tab));
      savePrefs();
      renderDeckPills(state.data);
      renderRows();
    }));
    box.querySelectorAll("[data-pill]").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.pill === "confl") state.vkConfl = !state.vkConfl;
      if (b.dataset.pill === "atlevel") state.vkAtLevel = !state.vkAtLevel;
      renderDeckPills(state.data);
      renderRows();
    }));
    // Grade-tab counts + watch count live in the toolbar as before
    $("#count-aplus").textContent = nAplus;
    $("#count-a").textContent = nA;
    $("#count-watch").textContent = res.filter((r) => ["B", "C", "B+", "WATCH"].includes(r.grade)).length;
    $("#watch-count").textContent = res.filter((r) => isStarred(r.symbol)).length;
  }

  // ----------------------------------------------------------- a row
  // ── VIVEK screening helpers ────────────────────────────────────────────────
  const RECENT_DAYS = 3;                       // trigger within this many days = "recent"
  const TRIG_LABEL = { reclaim: "Reclaim", retest: "Retest", break: "Break" };

  // REIT / ETF / LIC / managed fund detector — mirrors scanner/broker/vivek_bot.py
  // (_is_fund_or_reit). These hug the 200 SMA, so they over-produce "reactions"
  // without being real trades; the bot already skips them, and most CFD brokers
  // (e.g. CMC) don't list them — so the dashboard flags them as a heads-up.
  const FUND_NAME_KEYWORDS = ["REIT", "TRUST", "FUND", "ETF", "SPDR", "ISHARES",
    "VANGUARD", "BETASHARES", "VANECK", "GLOBAL X"];
  const FUND_SECTOR_HINTS = ["reit", "real estate investment trust"];
  const NON_OPERATING_SECTORS = new Set(["not applicable", "not applic", "n/a"]);
  function isFundReit(r) {
    const sector = String((r && r.sector) || "").trim().toLowerCase();
    if (FUND_SECTOR_HINTS.some((h) => sector.includes(h))) return true;
    if (NON_OPERATING_SECTORS.has(sector)) return true;
    const name = String((r && r.name) || "").toUpperCase();
    return FUND_NAME_KEYWORDS.some((kw) => name.includes(kw));
  }

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
  // Compact, scannable badges for the VIVEK list — what moved + why it
  // matters. Returns an ARRAY; rowHtml caps the row at 3 chips + a "+N"
  // overflow chip (UI Wave 1) — the expanded panel still shows everything.
  function vkBadges(r) {
    if (state.mode !== "vivek") return [];
    const out = [];
    // Multi-lens confluence (dog-balls mode): another lens has an ACTIVE
    // aligned setup on this exact name right now
    const ci = window.PM && state.confl ? state.confl.of(r.symbol) : null;
    if (ci && ci.side === (String(r.dir || "LONG").toUpperCase() === "SHORT" ? "short" : "long"))
      out.push(PM.confluenceChipHTML(ci, "VIVEK"));
    if (isFundReit(r))
      out.push(`<span class="rbadge fundwarn" title="REIT / ETF / LIC / managed fund — the bot won't trade these and most CFD brokers (e.g. CMC) don't list them">⚠ FUND / REIT</span>`);
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
    return out;
  }

  // Row chip strip capped at 3 + "+N" (UI Wave 1): warnings (FUND/REIT,
  // LOW R:R, WIDE STOP) always outrank decorative badges so the cap can never
  // hide a risk flag. The full set stays in the expanded detail panel.
  const CHIP_CAP = 3;
  // Day change % (backlog #7). Prefer a scan-provided field; fall back to the
  // spark's last two closes (≈ daily cadence) flagged as an estimate.
  function dayPct(r) {
    const v = (typeof r.current_pct === "number") ? r.current_pct
            : (typeof r.day_pct === "number") ? r.day_pct : null;
    if (v != null && isFinite(v)) return { v, est: false };
    const sp = r.spark;
    if (Array.isArray(sp) && sp.length >= 2) {
      const a = +sp[sp.length - 2], b = +sp[sp.length - 1];
      if (a > 0 && isFinite(b)) return { v: ((b - a) / a) * 100, est: true };
    }
    return null;
  }

  function rowChips(r, extras) {
    const all = [...vkBadges(r), ...extras].filter(Boolean);
    const isWarn = (h) => /fundwarn|chip warn/.test(h);
    const ordered = [...all.filter(isWarn), ...all.filter((h) => !isWarn(h))];
    const shown = ordered.slice(0, CHIP_CAP);
    const hidden = ordered.length - shown.length;
    if (hidden > 0)
      shown.push(`<span class="rbadge chip-more" title="${hidden} more — expand the row for every chip">+${hidden}</span>`);
    return shown.join("");
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

    // Day change (backlog #7): the price block shows today's % beneath the
    // price. Scan-provided fields win when the publisher ships them; until
    // then it is derived from the spark's last two closes and marked ~.
    const dp = dayPct(r);
    const isShort = r.dir === "SHORT";
    const dayHTML = dp == null ? "" :
      `<span class="rday ${dp.v >= 0 ? "up" : "down"}${dp.est ? " est" : ""}" ` +
      `title="${dp.est ? "≈ change vs the previous spark close (day-change isn't in the scan data yet)" : "Day change"}">` +
      `${dp.est ? "~" : ""}${dp.v >= 0 ? "+" : ""}${dp.v.toFixed(1)}%</span>`;

    const chartHref = `chart.html?m=${state.market}&s=${encodeURIComponent(r.symbol)}${state.mode !== "pullback" ? `&mode=${state.mode}` : ""}`;
    // v2 #47: FUND/REIT rows dim (default on) — the bot never trades them and
    // they crowd the A+ list. Toggled by the ⚠ FUNDS chip; hover/open restores.
    const dimCls = (state.dimFunds !== false && isFundReit(r)) ? " row-dim" : "";
    return `<div class="row-wrap${dimCls}" data-sym="${esc(r.symbol)}" tabindex="0" role="button" aria-expanded="false" aria-label="${esc(r.symbol)} ${esc(r.grade)} ${isShort ? "short" : "long"} — Enter for details" style="--grade-color:${GRADE_VAR[r.grade] || "var(--grade-c)"};--row-i:${stagger}">
     <div class="row">
      <div class="row-grade">${esc(r.grade)}</div>
      <div class="row-main">
        <div class="row-line1">
          <a class="tkr" href="${chartHref}" title="Open chart">${esc(r.symbol)}</a>
          <span class="rdir ${isShort ? "short" : "long"}" title="${isShort ? "SHORT" : "LONG"} setup" aria-label="${isShort ? "SHORT" : "LONG"}">${isShort ? "▼" : "▲"}</span>
          ${mcapBadge}
          ${state.view === "watch" ? lensStars(r.symbol).map((l) => `<span class="lens-badge lens-${l}" title="Starred in ${LENS_NAME[l]}">${l}</span>`).join("") : ""}
          <span class="cname">${esc(r.name || "")}</span>
        </div>
        <div class="row-chips">${rowChips(r, [assetBadge, lowrr, widestop, t2r])}</div>
      </div>
      <div class="row-price">
        <span class="rprice">${fmtPrice(r.price)}</span>
        ${dayHTML}
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
        <button class="row-expand" title="Details" aria-label="Toggle details">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="6 9 12 15 18 9"/></svg>
        </button>
      </div>
     </div>
     <div class="detail-anim">
       <div class="detail-inner"></div>
     </div>
    </div>`;
  }

  // #53: re-stamp every open panel's "scanned Xm ago" chip so a long-open row
  // can't silently age into reading as fresh. Same maths as scanAge() above.
  function refreshScanAgeChips() {
    const g = state.data && state.data.generated_at;
    if (!g) return;
    const mins = Math.max(0, Math.round((Date.now() - new Date(g).getTime()) / 60000));
    const txt = mins < 60 ? `${mins}m ago` : mins < 1440 ? `${Math.round(mins / 60)}h ago` : `${Math.round(mins / 1440)}d ago`;
    document.querySelectorAll(".detail-inner .vk-fresh").forEach((el) => {
      el.textContent = `⟳ scanned ${txt}`;
      el.classList.toggle("stale", mins > 1440);
    });
  }

  // #52: warm the chart candle file for a symbol on hover so tapping through
  // to the chart paints instantly. Once per symbol per session; silent.
  const _prefetched = new Set();
  function prefetchChart(sym) {
    if (!sym || _prefetched.has(sym)) return;
    _prefetched.add(sym);
    const modeDir = state.mode === "reversal" ? "_rev" : state.mode === "spec" ? "_spec" : state.mode === "short" ? "_short" : "";
    fetch(`data/charts/${state.market}${modeDir}/${encodeURIComponent(sym)}.json`, { cache: "force-cache" }).catch(() => {});
  }

  // Lazy detail (Wave 2, 2026-07-22): the expanded panel used to be rendered
  // for EVERY row up-front — the bulk of the list's HTML for content almost
  // never opened. Now it's built on first expand (and gets a fresher scan-age
  // stamp as a bonus). dataset.filled makes repeat opens free.
  function fillDetail(wrap) {
    const inner = wrap.querySelector(".detail-inner");
    if (!inner || inner.dataset.filled) return;
    const r = ((state.data && state.data.results) || [])
      .find((x) => x.symbol === wrap.dataset.sym);
    if (!r) return;
    // #51: copy-debug lives in the expanded panel now (off the row) — one
    // clean tap target per row, the developer tool tucked where it belongs.
    const copyBtn = `<button class="dp-copy row-copy-debug" data-sym="${esc(r.symbol)}" title="Copy this setup's raw data">` +
      `<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy raw data</button>`;
    inner.innerHTML = detailHtml(r) + debugDetailHtml(r) + `<div class="dp-tools">${copyBtn}</div>`;
    inner.dataset.filled = "1";
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
    const tfTxt = r.level_tf === "weekly" ? "Weekly 200 SMA" : r.level_tf === "3d" ? "3-Day 200 SMA" : "H4 200 SMA";
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
    // Backlog #6: pass/fail as compact inline chips — the note rides in the
    // tooltip instead of a third column, so six criteria read in one glance.
    const chk = (ok, label, note) =>
      `<span class="vk-chk ${ok ? "ok" : "no"}" title="${esc(note)}">` +
      `<b>${ok ? "✓" : "✕"}</b> ${label}</span>`;
    const checklist = [
      chk(true, "200 SMA level", r.level_tf === "weekly" ? "Weekly (strongest)" : r.level_tf === "3d" ? "3-Day" : "H4 / daily proxy"),
      chk(!!r.at_level, "At the level", r.at_level ? "price on the SMA" : "still approaching"),
      chk(reactClean, "Clean reaction", r.reaction === "bounce" ? "bounced" : r.reaction === "reject" ? "rejected" : "no clear turn yet"),
      chk(struct >= 0.5, "Structure", struct >= 0.8 ? "clean" : struct >= 0.5 ? "workable" : "thin"),
      chk(rrOk, "R:R ≥ 1.5", `${(r.rr || 0).toFixed(1)} to TP2`),
      chk(nStruct > 0, "Real targets", nStruct > 0 ? `${nStruct}/3 at structure` : "R-multiples only"),
    ].join("");

    // Backlog #5: HORIZONTAL trade ladder — Stop → Entry → TP1 → TP2 → TP3
    // as cells reading left to right in trade order (both directions), each
    // with its %-from-entry and the scale-out note.
    const cell = (key, label, val, cls, sub) => `
      <div class="vk-cell vk-${cls}" title="${esc(label)}">
        <span class="vk-cell-key">${key}</span>
        <span class="vk-cell-price num">${cur}${num(val)}</span>
        <span class="vk-cell-sub">${sub}</span>
      </div>`;
    const ladder = [
      cell("SL",  "Stop loss",     r.stop,  "sl",    `${sgn(pctFrom(r.stop))} · risk ${cur}${num(r.risk)}`),
      cell("IN",  "Entry",         r.entry, "entry", `${tfTxt} reaction`),
      cell("TP1", "Take profit 1", r.tp1,   "tp",    `${sgn(pctFrom(r.tp1))} · book ${scale[0]}% · SL → BE`),
      cell("TP2", "Take profit 2", r.tp2,   "tp",    `${sgn(pctFrom(r.tp2))} · book ${scale[1]}% · SL → support`),
      cell("TP3", "Take profit 3", r.tp3,   "tp",    `${sgn(pctFrom(r.tp3))} · book ${scale[2]}%`),
    ];

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
            ${r.headline_tf && r.headline_tf !== "1D"
              ? `<span class="vk-tf-chip" title="Entry/SL/TP and R:R shown are the ${esc(r.headline_tf)} plan — the timeframe the trigger armed on (and the one the bot trades)">${esc(r.headline_tf)} PLAN</span>` : ""}
            <span class="vk-rr">${r.rr_text || (r.rr + ":1")} <span class="vk-rr-sub">to TP2</span></span>
            ${scanAge()}
            <a class="vk-chart-btn" href="${chartHref}">View chart →</a>
          </div>
          <p class="vk-why">${esc(r.analysis || "")}</p>
        </div>
      </div>

      <div class="vk-ladder vk-ladder-h">${ladder.join("")}</div>

      <div class="vk-checklist-wrap">
        <div class="vk-section-lbl">5.0 checklist</div>
        <div class="vk-checks">${checklist}</div>
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
      list = all.filter((r) => isWatchedAny(r.symbol));   // #55: any lens, not just VIVEK
    } else if (state.tab === "aplus") {
      list = all.filter((r) => r.grade === "A+");
    } else if (state.tab === "a") {
      list = all.filter((r) => r.grade === "A");
    } else {
      // Watch tab: B/C for the daily scanners; B+/WATCH for VIVEK.
      list = all.filter((r) => ["B", "C", "B+", "WATCH"].includes(r.grade));
    }
    // The scan is always VIVEK now, so these apply purely on their toggle state
    // (no `mode` gate — a stale persisted mode must never disable them).
    // Entry-type filter (200 SMA interaction) — union of selected types.
    if (state.vkEntry && state.vkEntry.size) {
      list = list.filter((r) => (r.entry_types || []).some((t) => state.vkEntry.has(t)));
    }
    // "Triggered recently" — only setups that just moved.
    if (state.vkRecent) {
      list = list.filter(triggeredRecently);
    }
    // "High conviction" — weekly reclaims (A / strong structure).
    if (state.vkHighConv) {
      list = list.filter(isHighConviction);
    }
    // Direction — Longs / Shorts. Combines (AND) with every filter above.
    if (state.vkDir) {
      list = list.filter((r) => r.dir === state.vkDir);
    }
    // Deck pills (Wave 3): multi-lens alignment / at-the-level. View filters
    // only — no signal logic; same data the retired banner strips showed.
    if (state.vkConfl) {
      list = list.filter((r) => {
        const ci = state.confl && state.confl.of(r.symbol);
        return ci && ci.side === (String(r.dir || "LONG").toUpperCase() === "SHORT" ? "short" : "long");
      });
    }
    if (state.vkAtLevel) {
      list = list.filter((r) => r.at_level);
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
  // Labels are compact so the merged toolbar keeps its single line (backlog
  // #1) — the full wording lives in each chip's tooltip.
  const VK_ENTRY = [
    ["reclaim", "Reclaim", "Reclaim after rejection — close back above 200 SMA after rejection"],
    ["retest",  "Retest",  "Retest + confirmation"],
    ["break",   "Break",   "Break of small structure near 200 SMA"],
  ];
  // Backtest quality per trigger — populated at RUNTIME from the live artifact
  // (vivek_backtest_longonly.json → results.by_entry_type). Numbers are never
  // hardcoded here: until the fetch lands (or if it fails) chips read "no
  // backtest data" with no tint. Tint = expectancy_r: >0.3 green, 0–0.3 amber,
  // <0 red.
  const VK_ENTRY_Q = {
    reclaim: { tier: null, note: "no backtest data" },
    retest:  { tier: null, note: "no backtest data" },
    break:   { tier: null, note: "no backtest data" },
  };
  async function loadEntryQuality() {
    try {
      const bt = await sessFetch("data/vivek_backtest_longonly.json");   // #67
      if (!bt) return;
      const by = ((bt.results) || {}).by_entry_type || {};
      let touched = false;
      for (const code in VK_ENTRY_Q) {
        const s = by[code];
        if (!s || typeof s.expectancy_r !== "number") continue;
        const e = s.expectancy_r;
        VK_ENTRY_Q[code] = {
          tier: e > 0.3 ? "green" : e >= 0 ? "amber" : "red",
          note: `Backtest (long-only): ${e >= 0 ? "+" : ""}${e.toFixed(2)}R avg over ${s.n} trades` +
                (s.win_rate != null ? ` · ${s.win_rate}% win` : "") +
                (s.profit_factor != null ? ` · PF ${s.profit_factor}` : ""),
        };
        touched = true;
      }
      if (touched && state.data) renderEntryFilters(state.data);   // repaint chips with real numbers
    } catch (_) { /* fetch failed — neutral wording stands, never stale claims */ }
  }
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
    // Relative age on screen → exact Melbourne time in the tooltip (UI Wave 1)
    const melb = window.PM ? PM.fmtMelb(d.generated_at) : fmtTime(d.generated_at, d.tz_label);
    box.title = `Generated ${melb}` + (d.code_sha ? ` · built from ${d.code_sha}` : "");
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
      const cls = q && q.tier ? ` q-${q.tier}` : "";
      const title = q ? `${full} — ${q.note}` : full;
      return `<button class="vkf-chip${cls}${active ? " is-active" : ""}" data-type="${esc(code)}" title="${esc(title)}">${esc(label)} <b>${n}</b></button>`;
    };
    // Direction chip. If a direction has 0 matches in the CURRENT view (common
    // once High conviction narrows things), render it disabled + dimmed so it
    // reads as "nothing here" instead of a button that empties the list. The
    // active direction is never disabled, so you can always toggle it back off.
    const dirChipHTML = (dir, label, n) => {
      const active = state.vkDir === dir;
      const off = n === 0 && !active;
      const cls = dir === "LONG" ? "vkf-long" : "vkf-short";
      const title = off ? `No ${dir.toLowerCase()} setups in this view` : `Show only ${dir.toLowerCase()} setups`;
      return `<button class="vkf-chip ${cls}${active ? " is-active" : ""}${off ? " vkf-off" : ""}" ` +
        `data-dir="${dir}"${off ? " disabled" : ""} title="${title}">${label} <b>${n}</b></button>`;
    };
    const nRecent = all.filter(triggeredRecently).length;
    const nHigh = all.filter(isHighConviction).length;
    // Longs/Shorts counts stay in sync with the OTHER active filters, so the
    // numbers reflect what you'll actually see as you stack them.
    let dirBase = all;
    if (state.vkEntry.size) dirBase = dirBase.filter((r) => (r.entry_types || []).some((t) => state.vkEntry.has(t)));
    if (state.vkRecent) dirBase = dirBase.filter(triggeredRecently);
    if (state.vkHighConv) dirBase = dirBase.filter(isHighConviction);
    const nLong = dirBase.filter((r) => r.dir === "LONG").length;
    const nShort = dirBase.filter((r) => r.dir === "SHORT").length;
    box.innerHTML =
      `<span class="vkf-label">200 SMA interaction</span>` +
      chip("all", "All", "Every VIVEK setup", all.length) +
      VK_ENTRY.map(([c, l, f]) => chip(c, l, f, count(c))).join("") +
      `<span class="vkf-legend" title="Chip colour = backtest edge (avg R)">🟢 best · 🟠 ok · 🔴 weak</span>` +
      `<span class="vkf-sep"></span>` +
      `<button class="vkf-chip vkf-highconv${state.vkHighConv ? " is-active" : ""}" data-high="1" ` +
        `title="The best cell in the backtest: weekly reclaims that are A/A+ or have strong structure">🎯 High conviction <b>${nHigh}</b></button>` +
      `<button class="vkf-chip vkf-recent${state.vkRecent ? " is-active" : ""}" data-recent="1" ` +
        `title="Triggered recently — setups whose trigger fired on or near the latest scanned bar">⚡ Triggered <b>${nRecent}</b></button>` +
      `<span class="vkf-sep"></span>` +
      dirChipHTML("LONG", "▲ Longs", nLong) +
      dirChipHTML("SHORT", "▼ Shorts", nShort);
    box.querySelectorAll(".vkf-chip").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.dir) {
        state.vkDir = state.vkDir === b.dataset.dir ? null : b.dataset.dir;   // toggle; click again = both
      } else if (b.dataset.recent) {
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
      ensureActiveVisible();   // #41: keep the just-activated pill on screen
    }));
    ensureActiveVisible();     // #41: reveal a restored/active filter on (re)render
  }

  // #41: nudge the active filter chip into view WITHIN the mobile toolbar strip
  // (horizontal-only — never scrolls the page vertically). No-op when the strip
  // isn't overflowing (desktop / few chips).
  function ensureActiveVisible() {
    const line = document.querySelector("#toolbar .tb-line");
    if (!line || line.scrollWidth <= line.clientWidth) return;
    const el = document.querySelector("#vk-filters .vkf-chip.is-active")
            || document.querySelector("#tabs .seg-btn.is-active");
    if (!el) return;
    const lr = line.getBoundingClientRect(), er = el.getBoundingClientRect();
    if (er.left < lr.left + 8) line.scrollBy({ left: er.left - lr.left - 8, behavior: "smooth" });
    else if (er.right > lr.right - 8) line.scrollBy({ left: er.right - lr.right + 8, behavior: "smooth" });
  }

  let _rowsToken = 0;   // invalidates in-flight rAF batches when a newer render starts
  function renderRows() {
    const wrap = $("#results");
    const list = buildList();
    _rowsToken++;
    if (!list.length) {
      // Are active toggle-filters the reason it's empty? Point that out so an
      // empty list reads as "these filters have no match" rather than "broken".
      const activeFilters = [
        state.vkConfl && "⨂ Multi-lens",
        state.vkAtLevel && "◎ At level",
        state.vkHighConv && "High conviction",
        state.vkRecent && "Triggered recently",
        state.vkDir && (state.vkDir === "LONG" ? "Longs only" : "Shorts only"),
        state.vkEntry && state.vkEntry.size ? [...state.vkEntry].join("/") : null,
      ].filter(Boolean);
      const msg = state.view === "watch"
        ? { h: "Your watchlist is empty", p: "Tap the ☆ on any setup to add it here." }
        : activeFilters.length
          ? { h: "No setups match these filters", p: `${activeFilters.join(" + ")} has no matches in ${state.market ? state.market.toUpperCase() : "this market"} on this tab — tap a pill or filter to widen, or switch market/tab.` }
          : { h: "No setups in this tab", p: "Try another grade tab or market, or check back after the next scan." };
      wrap.innerHTML = `<div class="placeholder"><h3>${msg.h}</h3><p>${msg.p}</p></div>`;
      return;
    }
    // Sticky grade-group headers (#48): shown when the list is in grade order
    // (the default SCORE sort). Most useful on the multi-grade views — the
    // WATCH tab (B+/WATCH) and the ★ watchlist (all grades mixed) — but a
    // single labelled section header on a single-grade tab reads fine too.
    const showGroups = state.sort === "score";
    const groupAt = {};
    if (showGroups) {
      let prev = null;
      list.forEach((r, idx) => { if (r.grade !== prev) { groupAt[idx] = r.grade; prev = r.grade; } });
    }
    const GROUP_NAME = { "A+": "A+ SETUPS", "A": "A SETUPS", "B+": "B+ SETUPS", "B": "B SETUPS", "WATCH": "WATCH", "C": "C SETUPS" };
    const gradeCount = (g) => list.reduce((n, r) => n + (r.grade === g ? 1 : 0), 0);
    const rowOrGroup = (r, idx) =>
      (groupAt[idx] ? `<div class="row-group" data-grade="${esc(groupAt[idx])}" style="--grade-color:${GRADE_VAR[groupAt[idx]] || "var(--grade-c)"}"><span>${esc(GROUP_NAME[groupAt[idx]] || groupAt[idx])}</span><span class="row-group-n">${gradeCount(groupAt[idx])}</span></div>` : "")
      + rowHtml(r, idx);

    // Incremental render (UI Wave 1): the first chunk paints synchronously so
    // the list is instantly usable; the tail streams in rAF batches so a
    // 400-row NASDAQ list can't block the first paint. Delegated row handlers
    // keep working on appended rows; the token kills a superseded stream.
    const FIRST = 40, BATCH = 60;
    wrap.innerHTML = list.slice(0, FIRST).map((r, idx) => rowOrGroup(r, idx)).join("");
    // Entrance cascade on the FIRST paint only — later renders (filters,
    // sorts, pills) swap instantly, which reads as much snappier.
    if (!wrap.dataset.painted) requestAnimationFrame(() => { wrap.dataset.painted = "1"; });
    // #55: the other-lens strip lives at the end of the watch view — append it
    // here (before the small-list early return, so short watchlists get it too).
    if (state.view === "watch") appendOtherLensWatched(wrap, list);
    if (list.length <= FIRST) return;
    const token = _rowsToken;
    let i = FIRST;
    const step = () => {
      if (token !== _rowsToken || !wrap.isConnected) return;
      // keep the other-lens strip last as rows stream in
      const olw = wrap.querySelector(".olw");
      const html = list.slice(i, i + BATCH).map((r, j) => rowOrGroup(r, i + j)).join("");
      if (olw) olw.insertAdjacentHTML("beforebegin", html);
      else wrap.insertAdjacentHTML("beforeend", html);
      i += BATCH;
      if (i < list.length) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // #55: starred names in PhaseMap/Specs for this market that AREN'T in the
  // VIVEK scan get a compact "also watched" strip below the rows — so the ★
  // view is the true, whole watchlist, not just its VIVEK slice.
  function appendOtherLensWatched(wrap, shownList) {
    const w = _pmWatch();
    if (!w) return;
    const shown = new Set(shownList.map((r) => r.symbol));
    const extras = {};   // symbol -> lenses
    [["phasemap", "P"], ["specs", "S"]].forEach(([ns, tag]) => {
      const m = w.map(ns, state.market) || {};
      Object.keys(m).forEach((sym) => {
        if (shown.has(sym)) return;
        (extras[sym] = extras[sym] || { lenses: [], snap: m[sym] && m[sym].snap }).lenses.push(tag);
      });
    });
    const syms = Object.keys(extras);
    if (!syms.length) return;
    const chips = syms.slice(0, 40).map((sym) => {
      const e = extras[sym];
      const href = `chart.html?m=${state.market}&s=${encodeURIComponent(sym)}&pm=1`;
      const badges = e.lenses.map((l) => `<span class="lens-badge lens-${l}">${l}</span>`).join("");
      return `<a class="olw-chip" href="${href}" title="Open ${esc(sym)} — not in the current VIVEK scan">${badges}<b>${esc(sym)}</b></a>`;
    }).join("");
    wrap.insertAdjacentHTML("beforeend",
      `<div class="olw"><div class="olw-hd">Also on your watchlist — other lenses, not in the current VIVEK scan</div>` +
      `<div class="olw-row">${chips}</div></div>`);
  }

  // AT-LEVEL banner strip retired (Wave 3, 2026-07-22): the deck's ◎ At-level
  // pill filters the real rows instead — same data, one click, no extra band.

  // ----------------------------------------------------------- apply
  // Relative "Last scanned" (UI Wave 1): "4m ago" on screen; the exact
  // Melbourne time (the ONE display convention) + market-local ride the
  // tooltip. A stale-while-revalidate paint is flagged "updating…" so a
  // cached copy can never read as live on a trading dashboard.
  function updateScanTitle(d) {
    const el = $("#scan-title");
    if (!el || !d) return;
    const t = Date.parse(d.generated_at);
    const melb = window.PM ? PM.fmtMelb(d.generated_at) : fmtTime(d.generated_at, d.tz_label);
    const rel = isFinite(t) ? (Date.now() - t < 60000 ? "just now" : agoText(t)) : melb;
    const suffix = state.staleView === "failed" ? "  ·  update failed — showing cached"
                 : state.staleView ? "  ·  updating…" : "";
    el.textContent = `Last scanned: ${rel}${suffix}`;
    el.title = `Melbourne: ${melb}  ·  Market-local: ${fmtTime(d.generated_at, d.tz_label)}`;
    // Deck freshness dot (Wave 3): green = live · pulsing = updating a stale
    // paint · amber = last refresh failed (matches the title suffix).
    const dot = document.getElementById("deck-dot");
    if (dot) dot.className = "deck-dot" +
      (state.staleView === "failed" ? " warn" : state.staleView ? " sync" : "");
  }

  function applyPayload(d, stale = false) {
    state.data = d;
    state.dataKey = `${state.market}:${state.mode}`;
    state.staleView = stale;
    state.cur = d.currency_symbol || "$";
    updateScanTitle(d);
    const dqNote = d.quality_skipped ? `  ·  ${d.quality_skipped} skipped (data quality)` : "";
    const riskNote = d.risk_per_trade ? `  ·  $${d.risk_per_trade} risk/trade` : "";
    const nSetups = d._head && d._full_count != null ? d._full_count : d.results.length;
    $("#scan-sub").textContent = `${d.label} · ${d.universe_size ?? d.scanned} in universe · ${nSetups} setups${dqNote}${riskNote} · auto-refreshes hourly`;
    renderFreshness(d);
    renderEntryFilters(d);
    renderLegend(d);
    renderDeckPills(d);
    renderRows();
    // Multi-lens confluence: fetch the other lenses' latest files, then
    // re-render rows with chips + refresh the deck's Multi-lens pill count.
    if (window.PM && PM.loadConfluence) {
      state.confl = null;
      // Pass the payload we just rendered so the vivek file isn't fetched
      // twice (Wave 2). A head-cache paint is truncated — let it fetch full.
      PM.loadConfluence(state.market, d._head ? null : d).then((c) => {
        if (state.data !== d) return;   // view moved on while lenses loaded
        state.confl = c;
        renderRows();
        renderDeckPills(d);
        notifyTriples(c.all());
      });
    }
  }

  // Confluence banner strip retired (Wave 3, 2026-07-22): the deck's
  // ⨂ Multi-lens pill filters the rows to aligned names instead — the rows
  // themselves carry the confluence chip, so nothing is lost, one band is.

  function skeleton() {
    // 8 shimmer placeholders sized like real row cards (see .skeleton CSS)
    $("#results").innerHTML = Array.from({ length: 8 }, () => `<div class="skeleton"></div>`).join("");
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

  // Track record RETIRED (owner 2026-07-09): the firehose journal that fed
  // this strip logged every A+/A on every timeframe uncapped — the bot book
  // on journal.html is the only track record now.
  // ── bot activity strip — what Claude did while you weren't looking ────────
  function agoText(ms) {
    if (!isFinite(ms)) return "";
    const m = Math.max(0, Math.round((Date.now() - ms) / 60000));
    if (m < 60) return `${m}m ago`;
    if (m < 48 * 60) return `${Math.round(m / 60)}h ago`;
    return `${Math.round(m / 1440)}d ago`;
  }
  async function loadBotActivity() {
    const box = $("#bot-activity");
    if (!box) return;
    try {
      const res = await fetch("data/vivek_bot_book.json", { cache: "no-cache" });
      if (!res.ok) return;
      const b = await res.json();
      const evts = [];
      for (const p2 of b.open || []) {
        const t = Date.parse(p2.opened_at || "");
        if (isFinite(t)) evts.push({ t, kind: "open", sym: p2.symbol,
          txt: `Opened ${p2.symbol}`, sub: `${p2.timeframe || ""} ${p2.entry_type || ""}`.trim() });
      }
      for (const p2 of (b.closed || []).slice(-12)) {
        const t = Date.parse(p2.closed_at || `${p2.exit_date || ""}T${p2.exit_time || "00:00"}:00Z`);
        const r = p2.realized_r;
        if (isFinite(t)) evts.push({ t, kind: "close", sym: p2.symbol, r,
          txt: `Closed ${p2.symbol} ${r != null ? `${r >= 0 ? "+" : ""}${(+r).toFixed(2)}R` : ""}`.trim(),
          sub: p2.exit_reason || "" });
      }
      evts.sort((a, b2) => b2.t - a.t);
      const recent = evts.slice(0, 4);
      if (!recent.length) { box.hidden = true; return; }
      // One summary line (UI Wave 1): open count · today's realised R (Melbourne
      // day) · last action age. Click expands the event list; the 3-min
      // re-render keeps an expanded list expanded. Journal → link stays put.
      const wasOpen = !!box.querySelector(".ba-events:not([hidden])");
      const nOpen = (b.open || []).length;
      const melbDay = (t) => new Intl.DateTimeFormat("en-CA",
        { timeZone: "Australia/Melbourne", year: "numeric", month: "2-digit", day: "2-digit" }).format(t);
      const today = melbDay(Date.now());
      const closedToday = evts.filter((e) => e.kind === "close" && isFinite(e.t) && melbDay(e.t) === today);
      const rSum = closedToday.reduce((s, e) => s + (isFinite(+e.r) ? +e.r : 0), 0);
      const rTxt = closedToday.length ? `${rSum >= 0 ? "+" : ""}${rSum.toFixed(1)}R today` : "no closes today";
      const sumTxt = `Bot: ${nOpen} open · ${rTxt} · last action ${agoText(recent[0].t)}`;
      box.hidden = false;
      box.innerHTML =
        `<button class="ba-sum" type="button" aria-expanded="${wasOpen}" ` +
          `title="The paper bot book — click for the recent events">🤖 ${esc(sumTxt)}` +
          `<span class="ba-chev" aria-hidden="true">▾</span></button>` +
        `<a class="ba-more" href="journal.html">Journal →</a>` +
        `<div class="ba-events"${wasOpen ? "" : " hidden"}>` +
        recent.map((e) =>
          `<a class="ba-item" href="journal.html" title="${esc(e.sub)}">` +
          `<span class="ba-kind-${e.kind}${e.kind === "close" ? (e.r >= 0 ? " pos" : " neg") : ""}">${esc(e.txt)}</span>` +
          `<span class="ba-ago">${agoText(e.t)}</span></a>`).join("") +
        `</div>`;
      box.classList.toggle("ba-open", wasOpen);
      const sumBtn = box.querySelector(".ba-sum");
      const list = box.querySelector(".ba-events");
      if (sumBtn && list) sumBtn.addEventListener("click", () => {
        const open = !list.hidden;
        list.hidden = open;
        sumBtn.setAttribute("aria-expanded", String(!open));
        box.classList.toggle("ba-open", !open);
      });
    } catch (_) { /* the strip is optional — never block the dashboard */ }
  }

  // #67: session cache for slow-changing artifacts (market caps, backtest
  // stats). They refresh at most daily, so a soft reload within the same tab
  // session serves them from sessionStorage instead of re-fetching. A fresh
  // session (new tab) still pulls the latest.
  async function sessFetch(url) {
    const key = "gbs:sess:" + url;
    try { const c = sessionStorage.getItem(key); if (c) return JSON.parse(c); } catch (_) {}
    try {
      const res = await fetch(url, { cache: "no-cache" });
      if (!res.ok) return null;
      const j = await res.json();
      try { sessionStorage.setItem(key, JSON.stringify(j)); } catch (_) {}
      return j;
    } catch (_) { return null; }
  }

  async function loadCaps() {
    try {
      const raw = await sessFetch("data/market_caps.json");
      if (!raw) return;
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
    // Check localStorage cache first (5-min TTL)
    if (!state.cache[key]) {
      const lsCached = cacheGet(key);
      if (lsCached) state.cache[key] = lsCached;
    }
    if (state.cache[key]) { applyPayload(state.cache[key]); return; }
    // Stale-while-revalidate (UI Wave 1): if this market/mode isn't already on
    // screen, paint the best cached copy NOW — expired full payload first,
    // else the slim head cache — marked "updating…", then fetch fresh and swap.
    // If it IS already on screen (auto-refresh / reload), keep the current
    // view rather than degrading to a stale/head repaint while we fetch.
    const alreadyShowing = state.data && state.dataKey === key;
    let painted = alreadyShowing;
    if (!alreadyShowing) {
      const stale = cacheGetStale(key) || cacheGetHead(key);
      if (stale) { applyPayload(stale, true); painted = true; }
      else if (!silent) {
        $("#scan-title").textContent = "Loading latest scan…";
        skeleton();
      }
    }
    try {
      // The head of index.html starts this fetch before any script loads;
      // consume it (once) instead of fetching the same payload twice.
      let d = null;
      const pre = window.__scanPreload;
      if (pre && pre.market === market && mode === "vivek") {
        window.__scanPreload = null;
        d = await pre.promise.catch(() => null);
      }
      if (!d) {
        const res = await fetch(dataFile(market, mode), { cache: "no-cache" });
        if (!res.ok) throw new Error(res.status);
        d = await res.json();
      }
      state.cache[key] = d;
      cacheSet(key, d);
      cacheSetHead(key, d);
      // If the user switched market while this fetch was in flight, keep the
      // result cached but don't stomp the view they're now looking at.
      if (key === `${state.market}:${state.mode}`) applyPayload(d);
    } catch (e) {
      if (key !== `${state.market}:${state.mode}`) return;   // view moved on
      if (painted && state.data) {
        // Keep the stale view but say the refresh failed — never fake liveness.
        state.staleView = "failed";
        updateScanTitle(state.data);
      } else if (!silent) {
        $("#scan-title").textContent = "No scan data yet";
        $("#results").innerHTML = `<div class="placeholder"><h3>No ${mode} data for ${market.toUpperCase()}</h3>
          <p>Run the scanner to generate the data, then refresh.</p></div>`;
      }
    }
  }

  // ----------------------------------------------------------- search overlay
  // Recent tickers (#32): the last handful of names opened from search, so a
  // phone user can re-open them in a tap instead of retyping. Client-side only.
  const RECENT_KEY = "gbs:recent";
  function getRecent() {
    try { const a = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]"); return Array.isArray(a) ? a.slice(0, 10) : []; }
    catch (_) { return []; }
  }
  function recordRecent(sym, market) {
    if (!sym) return;
    try {
      const a = getRecent().filter((x) => !(x.s === sym && x.m === market));
      a.unshift({ s: sym, m: market || state.market });
      localStorage.setItem(RECENT_KEY, JSON.stringify(a.slice(0, 10)));
    } catch (_) {}
  }
  function renderRecent() {
    const res = document.getElementById("search-results");
    if (!res) return;
    const recent = getRecent();
    if (!recent.length) { res.innerHTML = `<div class="sr-hint">Type a ticker or name — searches VIVEK, PhaseMap and Specs.</div>`; return; }
    res.innerHTML =
      `<div class="sr-recent"><div class="sr-recent-hd">Recent</div><div class="sr-recent-row">` +
      recent.map((x) =>
        `<a class="sr-recent-chip" href="chart.html?m=${esc(x.m)}&s=${encodeURIComponent(x.s)}&mode=vivek" data-sym="${esc(x.s)}" data-mkt="${esc(x.m)}">` +
        `${esc(x.s)} <span class="sr-recent-mkt">${esc(String(x.m).toUpperCase())}</span></a>`).join("") +
      `</div></div>`;
    res.querySelectorAll(".sr-recent-chip").forEach((a) =>
      a.addEventListener("click", () => { recordRecent(a.dataset.sym, a.dataset.mkt); closeSearch(); }));
  }

  function openSearch() {
    const overlay = document.getElementById("search-overlay");
    const input   = document.getElementById("search-input");
    if (!overlay) return;
    overlay.removeAttribute("hidden");
    document.body.classList.add("search-open");
    if (input) { input.value = ""; input.focus(); }
    renderRecent();   // #32: surface recent tickers the moment it opens
  }
  function closeSearch() {
    const overlay = document.getElementById("search-overlay");
    if (!overlay) return;
    overlay.setAttribute("hidden", "");
    document.body.classList.remove("search-open");
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
            cacheSet(key, d);
            cacheSetHead(key, d);
            applyPayload(d);
            startAutoRefresh();
            flashScan(`Scan complete — updated to ${window.PM ? PM.fmtMelb(d.generated_at) : fmtTime(d.generated_at, d.tz_label)}.`, "ok");
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

    const watchToggle = document.getElementById("watch-toggle");
    if (watchToggle) watchToggle.addEventListener("click", () => {
      state.view = state.view === "watch" ? "results" : "watch";
      syncWatchToggle();
      renderRows();
    });

    // ⚠ FUNDS dim toggle (v2 #47) — active chip = funds dimmed (the default).
    const fundDim = document.getElementById("fund-dim");
    if (fundDim) fundDim.addEventListener("click", () => {
      state.dimFunds = state.dimFunds === false;
      savePrefs();
      syncFundDim();
      renderRows();
    });

    document.querySelectorAll("#tabs .seg-btn").forEach((b) => b.addEventListener("click", () => {
      state.tab = b.dataset.tab;
      savePrefs();
      if (state.view !== "results") {
        state.view = "results";
        syncWatchToggle();
      }
      document.querySelectorAll("#tabs .seg-btn").forEach((x) => x.classList.toggle("is-active", x === b));
      renderRows();
    }));

    const sortCycleBtn = document.getElementById("sort-cycle");
    if (sortCycleBtn) sortCycleBtn.addEventListener("click", () => {
      const i = SORT_CYCLE.indexOf(state.sort);
      state.sort = SORT_CYCLE[(i + 1) % SORT_CYCLE.length];   // unknown sort → SCORE
      state.sortDir = defaultDir(state.sort);
      savePrefs();
      updateSortButtons();
      renderRows();
    });
    const sortDirBtn = document.getElementById("sort-dir");
    if (sortDirBtn) sortDirBtn.addEventListener("click", () => {
      state.sortDir = (sortDirOf() === "asc" ? "desc" : "asc");
      savePrefs();
      updateSortButtons();
      renderRows();
    });

    // Search overlay wiring
    const searchTrigger = document.getElementById("search-trigger");
    const searchInput   = document.getElementById("search-input");
    const searchResults = document.getElementById("search-results");
    const searchOverlay = document.getElementById("search-overlay");
    if (searchTrigger) searchTrigger.addEventListener("click", openSearch);
    if (searchOverlay) searchOverlay.addEventListener("click", (e) => {
      if (e.target === searchOverlay) closeSearch();
    });
    const searchCancel = document.getElementById("search-cancel");   // #32
    if (searchCancel) searchCancel.addEventListener("click", closeSearch);
    // ── cross-lens search (2026-07-03): "/" searches VIVEK + PhaseMap +
    // Specs for the current market, each hit badged by lens and linking to
    // the right chart view. Lens files are fetched lazily on first search
    // and re-fetched when the market changes.
    let lensIdx = { market: null, phasemap: [], specs: [] };
    async function loadLensIndex() {
      if (lensIdx.market === state.market) return lensIdx;
      const grab = (url) => fetch(url, { cache: "no-cache" })
        .then((r) => (r.ok ? r.json() : null)).catch(() => null);
      const [pm, sp] = await Promise.all([
        grab(`data/phasemap/${state.market}/latest.json`),
        grab(`data/${state.market}_spec.json`),
      ]);
      lensIdx = { market: state.market,
                  phasemap: (pm && pm.results) || [],
                  specs: (sp && sp.results) || [] };
      return lensIdx;
    }
    const runSearch = async () => {
      const q = searchInput.value.trim().toLowerCase();
      if (!q) { renderRecent(); return; }   // #32: empty query → recent tickers
      const idx = await loadLensIndex();
      if (searchInput.value.trim().toLowerCase() !== q) return;   // stale keystroke
      const match = (sym, name) =>
        String(sym).toLowerCase().includes(q) || String(name || "").toLowerCase().includes(q);

      const vHits = ((state.data && state.data.results) || [])
        .filter((r) => match(r.symbol, r.name)).slice(0, 8);
      const pHits = idx.phasemap.filter((r) => match(r.ticker, r.name)).slice(0, 6);
      const sHits = idx.specs.filter((r) => match(r.symbol, r.name)).slice(0, 6);
      if (!vHits.length && !pHits.length && !sHits.length) {
        searchResults.innerHTML = `<div class="sr-empty">No results for "${esc(searchInput.value)}" in any lens</div>`;
        return;
      }
      const rows = [];
      vHits.forEach((r) => {
        const href = `chart.html?m=${state.market}&s=${encodeURIComponent(r.symbol)}${state.mode !== "pullback" ? `&mode=${state.mode}` : ""}`;
        rows.push(`<a class="sr-row" href="${href}">
          <span class="sr-grade" style="color:${GRADE_VAR[r.grade] || "var(--grade-c)"}">${esc(r.grade)}</span>
          <span class="sr-sym">${esc(r.symbol)}</span>
          <span class="sr-name">${esc(r.name || "")}</span>
          <span class="sr-price">${fmtPrice(r.price)}</span>
        </a>`);
      });
      pHits.forEach((r) => {
        const dir = r.direction === "bearish" ? "bearish" : "bullish";
        const href = `chart.html?m=${state.market}&s=${encodeURIComponent(r.ticker)}&dir=${dir}&src=phasemap`;
        rows.push(`<a class="sr-row" href="${href}">
          <span class="sr-grade" style="color:var(--teal)">PM</span>
          <span class="sr-sym">${esc(r.ticker)}</span>
          <span class="sr-name">${esc(r.name || "")} · ${esc(r.state)} ${esc(r.tier || "")} ${dir === "bearish" ? "▼" : "▲"}</span>
          <span class="sr-price">${r.metrics && r.metrics.close != null ? fmtPrice(r.metrics.close) : ""}</span>
        </a>`);
      });
      sHits.forEach((r) => {
        const href = `chart.html?m=${state.market}&s=${encodeURIComponent(r.symbol)}&mode=spec&src=specs`;
        rows.push(`<a class="sr-row" href="${href}">
          <span class="sr-grade" style="color:var(--orange)">⚡</span>
          <span class="sr-sym">${esc(r.symbol)}</span>
          <span class="sr-name">${esc(r.name || "")} · SPEC ${esc(r.grade)} · ${r.spike_ratio}× vol</span>
          <span class="sr-price">${fmtPrice(r.price)}</span>
        </a>`);
      });
      // Starred names (any lens, this market) — the watchlist is searchable
      if (window.PM && PM.watch) {
        const seen = new Set(rows.map(() => 0));
        ["vivek", "phasemap", "specs"].forEach((ns) => {
          Object.keys(PM.watch.map(ns, state.market))
            .filter((t) => t.toLowerCase().includes(q)).slice(0, 4)
            .forEach((t) => rows.push(`<a class="sr-row" href="chart.html?m=${state.market}&s=${encodeURIComponent(t)}&pm=1">
              <span class="sr-grade" style="color:var(--orange)">★</span>
              <span class="sr-sym">${esc(t)}</span>
              <span class="sr-name">on your ${esc(ns.toUpperCase())} watchlist</span>
              <span class="sr-price"></span>
            </a>`));
        });
      }
      // Open journal positions — a name you're IN should always be findable
      if (window.GBSSync) {
        const mFor = (t) => t.asset_type === "crypto" ? "crypto"
          : t.asset_type === "asx" ? "asx" : "nasdaq";
        GBSSync.load().trades
          .filter((t) => t.status === "open" &&
            ((t.symbol || "").toLowerCase().includes(q)))
          .slice(0, 5)
          .forEach((t) => rows.push(`<a class="sr-row" href="chart.html?m=${mFor(t)}&s=${encodeURIComponent(t.symbol)}&pm=1">
            <span class="sr-grade" style="color:var(--purple)">📓</span>
            <span class="sr-sym">${esc(t.symbol)}</span>
            <span class="sr-name">OPEN ${esc(String(t.direction || "").toUpperCase())} @ ${t.entry}${t.lens ? " · " + esc(t.lens) : ""}</span>
            <span class="sr-price"></span>
          </a>`));
      }
      searchResults.innerHTML = rows.join("");
      // Record the ticker into Recent, then close, when a result is picked (#32).
      searchResults.querySelectorAll(".sr-row").forEach((a) => a.addEventListener("click", () => {
        try { const u = new URL(a.href, location.href); recordRecent(u.searchParams.get("s"), u.searchParams.get("m")); } catch (_) {}
        closeSearch();
      }));
    };
    // Debounced ~150ms (UI Wave 1): one search per typing pause, not one per
    // keystroke — the stale-keystroke guard above still drops late responses.
    let _searchT = null;
    if (searchInput) searchInput.addEventListener("input", () => {
      clearTimeout(_searchT);
      _searchT = setTimeout(runSearch, 150);
    });

    // Touch-slop guard (v2 #34): a scroll that starts on a row must never
    // expand it. Track finger travel and swallow the click that follows a drag.
    // Also hosts long-press detection (#45): hold ~480ms on a row without
    // moving → a Chart/Star/Journal quick-action sheet, and the click that
    // follows the release is swallowed so the row doesn't also expand.
    const rowsHost = $("#results");
    let _slop = 0, _sx = 0, _sy = 0, _lpT = null, _lpFired = false;
    const cancelLongPress = () => { if (_lpT) { clearTimeout(_lpT); _lpT = null; } };
    rowsHost.addEventListener("touchstart", (e) => {
      const t = e.touches[0]; _slop = 0; _sx = t.clientX; _sy = t.clientY; _lpFired = false;
      const wrap = e.target.closest(".row-wrap");
      if (!wrap || e.target.closest(".t-star, .row-expand, .row-copy-debug, a")) return;
      cancelLongPress();
      _lpT = setTimeout(() => {
        _lpFired = true;
        if (navigator.vibrate) { try { navigator.vibrate(15); } catch (_) {} }
        openQuickActions(wrap.dataset.sym);
      }, 480);
    }, { passive: true });
    rowsHost.addEventListener("touchmove", (e) => {
      const t = e.touches[0];
      _slop = Math.max(_slop, Math.hypot(t.clientX - _sx, t.clientY - _sy));
      if (_slop > 10) cancelLongPress();
    }, { passive: true });
    rowsHost.addEventListener("touchend", cancelLongPress, { passive: true });
    rowsHost.addEventListener("touchcancel", cancelLongPress, { passive: true });
    // #52: prefetch chart data for the hovered row (desktop pointer only).
    rowsHost.addEventListener("mouseover", (e) => {
      const w = e.target.closest && e.target.closest(".row-wrap");
      if (w && w.dataset.sym) prefetchChart(w.dataset.sym);
    });

    // Row interactions (delegated): star toggle, copy-debug, chart link, expand details.
    $("#results").addEventListener("click", (e) => {
      if (_slop > 12) { _slop = 0; return; }   // drag, not a tap (v2 #34)
      if (_lpFired) { _lpFired = false; return; }   // long-press opened the sheet (#45)
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
        // #44: haptic tick + a bounce only when STARRING (not un-starring).
        if (on && navigator.vibrate) { try { navigator.vibrate(12); } catch (_) {} }
        if (on) { star.classList.remove("pop"); void star.offsetWidth; star.classList.add("pop"); }
        return;
      }
      if (e.target.closest("a.tkr") || e.target.closest("a.row-spark")) return;  // -> chart page
      // #49: the "+N" overflow chip expands the row directly (explicit — it
      // also fell through before, but now it's an obvious affordance).
      const wrap = e.target.closest(".row-wrap");
      if (wrap) toggleRowOpen(wrap);
    });

    // #50: keyboard — Enter/Space expands the focused row; ←/→ switch grade
    // tabs (skipped while typing in the search field).
    $("#results").addEventListener("keydown", (e) => {
      const wrap = e.target.closest && e.target.closest(".row-wrap");
      if (!wrap) return;
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleRowOpen(wrap); }
    });
    document.addEventListener("keydown", (e) => {
      if (["INPUT", "TEXTAREA"].includes((document.activeElement || {}).tagName)) return;
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      const order = ["aplus", "a", "watch"];
      const i = order.indexOf(state.tab);
      if (i < 0) return;
      const next = order[(i + (e.key === "ArrowRight" ? 1 : order.length - 1)) % order.length];
      const btn = document.querySelector(`#tabs .seg-btn[data-tab="${next}"]`);
      if (btn) { e.preventDefault(); btn.click(); }
    });
  }

  // Shared row expand/collapse (#49/#50): fills the lazy panel on first open
  // and keeps aria-expanded honest for a11y.
  function toggleRowOpen(wrap) {
    if (!wrap.classList.contains("open")) fillDetail(wrap);
    const open = wrap.classList.toggle("open");
    wrap.setAttribute("aria-expanded", open ? "true" : "false");
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
    // Wave 3: the quote left the topbar (single-row deck header) — it now
    // lives quietly in the footer.
    const el = document.getElementById("footer-quote") || document.getElementById("topbar-quote");
    if (!el) return;
    const show = () => {
      const idx = Math.floor(Date.now() / 3600000) % TRADER_QUOTES.length;   // rotates hourly
      const [text, author] = TRADER_QUOTES[idx];
      el.textContent = `"${text}" — ${author}`;
      el.title = `"${text}" — ${author}`;
    };
    show();
    setInterval(show, 60000);   // roll to the new quote the moment the hour ticks over
  }

  // City clocks: Melbourne · New York (left) and China · London (right).
  const _clockFmt = (tz) => new Intl.DateTimeFormat("en-GB", { timeZone: tz, weekday: "short", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const _dateFmt  = (tz) => new Intl.DateTimeFormat("en-GB", { timeZone: tz, day: "2-digit", month: "short", year: "numeric" });
  const CLOCKS = [
    { id: "mel",    fmt: _clockFmt("Australia/Melbourne"), date: _dateFmt("Australia/Melbourne") },
    { id: "ny",     fmt: _clockFmt("America/New_York"),    date: _dateFmt("America/New_York") },
    { id: "china",  fmt: _clockFmt("Asia/Shanghai"),       date: _dateFmt("Asia/Shanghai") },
    { id: "london", fmt: _clockFmt("Europe/London"),       date: _dateFmt("Europe/London") },
  ];

  function _fmtClock(fmt, dateFmt, now) {
    const parts = fmt.formatToParts(now);
    const get = (t) => (parts.find((p) => p.type === t) || {}).value || "";
    const time = `${get("weekday")} ${get("hour")}:${get("minute")}:${get("second")}`;
    const date = dateFmt.format(now);
    return [time, date];
  }

  function updateClocks() {
    // All FOUR cities visible (owner 2026-07-22: "I wanna be able to see
    // london/china without hovering"). 2×2 grid: MEL/NY with seconds in the
    // left column, China/London HH:MM in the right; dates ride the tooltip.
    const now = new Date();
    const parts = {};
    for (const c of CLOCKS) parts[c.id] = _fmtClock(c.fmt, c.date, now);
    const hms = (id) => (parts[id][0].split(" ")[1] || parts[id][0]);   // "13:33:53"
    const hm  = (id) => hms(id).slice(0, 5);                            // "13:33"
    const put = (elId, txt) => { const el = document.getElementById(elId); if (el) el.textContent = txt; };
    put("clk-mel-time", `MELBOURNE ${hms("mel")}`);
    put("clk-ny-time",  `NEW YORK ${hms("ny")}`);
    put("clk-china-time",  `CHINA ${hm("china")}`);
    put("clk-london-time", `LONDON ${hm("london")}`);
    const box = document.getElementById("microclock");
    if (box) box.title = `Melbourne ${parts.mel[0]} · ${parts.mel[1]}\nNew York ${parts.ny[0]} · ${parts.ny[1]}\nChina ${parts.china[0]} · ${parts.china[1]}\nLondon ${parts.london[0]} · ${parts.london[1]}`;
  }

  initDailyQuote();
  updateClocks();
  setInterval(updateClocks, 1000);

  // Warm the other markets in the background after first paint so the
  // ASX / NASDAQ / CRYPTO toggle renders instantly from cache.
  function prefetchMarkets() {
    for (const m of ["asx", "nasdaq", "crypto"]) {
      const key = `${m}:${state.mode}`;
      if (m === state.market || state.cache[key]) continue;
      fetch(dataFile(m, state.mode), { cache: "no-cache" })
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          if (d && !state.cache[key]) { state.cache[key] = d; cacheSet(key, d); cacheSetHead(key, d); }
        })
        .catch(() => {});
    }
  }

  // Browser notifications for triple-lens alignments (2026-07-03). Opt-in
  // via the bell; dedupe in localStorage so a refresh doesn't re-ping.
  function notifyEnabled() {
    try { return localStorage.getItem("gbs:notify") === "1" &&
      "Notification" in window && Notification.permission === "granted"; }
    catch (_) { return false; }
  }
  function notifyTriples(rows) {
    if (!notifyEnabled()) return;
    let seen = {};
    try { seen = JSON.parse(localStorage.getItem("gbs:notified") || "{}"); } catch (_) {}
    const day = new Date().toISOString().slice(0, 10);
    (rows || []).filter((x) => x.count >= 3).forEach((x) => {
      const k = `${day}:${state.market}:${x.ticker}:${x.side}`;
      if (seen[k]) return;
      seen[k] = 1;
      try {
        new Notification("🎯 Triple-lens alignment", {
          body: `${x.ticker} ${x.side.toUpperCase()} · ${state.market.toUpperCase()} — ${x.lenses.join(" + ")}`,
          icon: "icons/icon-192.png", tag: k,
        });
      } catch (_) {}
    });
    try {
      const pruned = Object.fromEntries(Object.entries(seen).filter(([k]) => k.startsWith(day)));
      localStorage.setItem("gbs:notified", JSON.stringify(pruned));
    } catch (_) {}
  }
  function wireNotifyBell() {
    const btn = document.getElementById("notify-btn");
    if (!btn || !("Notification" in window)) { if (btn) btn.hidden = true; return; }
    const paint = () => {
      const on = notifyEnabled();
      btn.style.opacity = on ? "1" : "0.45";
      btn.title = on ? "Browser alerts ON for triple-lens alignments — click to turn off"
                     : "Click to get a browser alert when a TRIPLE-lens alignment appears";
    };
    btn.addEventListener("click", async () => {
      try {
        if (notifyEnabled()) { localStorage.setItem("gbs:notify", "0"); paint(); return; }
        const perm = await Notification.requestPermission();
        if (perm === "granted") localStorage.setItem("gbs:notify", "1");
      } catch (_) {}
      paint();
    });
    paint();
  }
  wireNotifyBell();

  initKeyboard();
  bind();
  loadCaps();
  loadEntryQuality();
  loadBotActivity();
  setInterval(() => { if (!document.hidden) loadBotActivity(); }, 180000);
  // Keep the relative "Last scanned" + freshness badge honest while the tab
  // sits open — a "4m ago" that silently ages to 40m would read as live.
  setInterval(() => {
    if (document.hidden || !state.data) return;
    updateScanTitle(state.data);
    renderFreshness(state.data);
    refreshScanAgeChips();   // #53: keep open panels' "scanned Xm ago" honest
  }, 30000);
  // #61: idle-time prefetch of the other markets (requestIdleCallback with a
  // timer fallback) — was a fixed 300ms that could contend with first paint.
  const whenIdle = (fn) => (window.requestIdleCallback
    ? requestIdleCallback(fn, { timeout: 2000 }) : setTimeout(fn, 400));
  load().then(() => {
    startAutoRefresh();
    whenIdle(prefetchMarkets);
    // #66: defer the watchlist sync-in until AFTER the first rows are on
    // screen — the star reconcile is not first-paint-critical.
    if (window.GBSSync && GBSSync.enabled()) {
      whenIdle(() => GBSSync.syncIn().then(() => {
        if (state.data) {
          renderRows();
          const el = document.getElementById("watch-count");
          if (el) el.textContent = (state.data.results || []).filter((r) => isStarred(r.symbol)).length;
        }
      }).catch(() => {}));
    }
    // #69: first-paint→interactive timing beacon (console only) — before/after
    // evidence for the perf program, zero UI cost.
    try {
      const nav = performance.getEntriesByType("navigation")[0];
      const fp = (performance.getEntriesByName("first-contentful-paint")[0] || {}).startTime;
      requestAnimationFrame(() => console.info(
        `[perf] rows painted @ ${Math.round(performance.now())}ms` +
        (fp ? ` · FCP ${Math.round(fp)}ms` : "") +
        (nav ? ` · DOMContentLoaded ${Math.round(nav.domContentLoadedEventEnd)}ms` : "")));
    } catch (_) {}
  });

  // #60: one-time purge of legacy localStorage keys left by retired features —
  // reclaims quota so the manual journal's save can never fail silently.
  (function purgeLegacyKeys() {
    try {
      if (localStorage.getItem("gbs:purged:v1")) return;
      const DEAD = ["gbs:pulse", "gbs:cache:pullback", "gbs:cache:reversal", "gbs:cache:short",
        "gbs:scalp", "gbs:track", "gbs:mode", "gbs:debug:pulse"];
      DEAD.forEach((k) => localStorage.removeItem(k));
      // Old per-mode scan caches (gbs:cache:<market>:pullback etc.) — only the
      // vivek ones are live now.
      for (let i = localStorage.length - 1; i >= 0; i--) {
        const k = localStorage.key(i);
        if (k && /^gbs:cache:.*:(pullback|reversal|short|scalp)$/.test(k)) localStorage.removeItem(k);
      }
      localStorage.setItem("gbs:purged:v1", "1");
    } catch (_) {}
  })();
})();
