/* Paper-trade journal — Claude (bot) vs Me (manual), head to head.
 *
 *  • Claude  = the autonomous bot's paper book  (data/vivek_bot_book.json),
 *              written server-side every scan. Read-only here.
 *  • Me      = the trades you take from the charts (the shared manual store,
 *              localStorage + optional cross-device sync). Sized + managed by
 *              the SAME VIVEK rules as the bot: a fixed $5,000 of notional per
 *              position out of a $150,000 book (30 slots), 5× stocks / 3×
 *              crypto leverage cap, scale at TP1/2/3, SL → BE at TP1 → locked
 *              structure at TP2, close on the stop. You pick the setup; the
 *              rules run the trade. $ P&L uses 1R = the $ risked — which under
 *              fixed sizing VARIES per trade with the stop distance, instead of
 *              being the same 0.35% of equity every time.
 *
 *  All R/$ and equity curves are computed at render time and refreshed against
 *  live prices, so both sides update as trades open and close.
 */
(() => {
  "use strict";
  const $  = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const up  = (s) => esc(String(s == null ? "" : s).toUpperCase());

  const GRADE_CLS = { "A+": "g-aplus", "A": "g-a", "B+": "g-b", "B": "g-b", "WATCH": "g-c", "C": "g-c" };
  const rcls = (r) => (r >= 0 ? "r-pos" : "r-neg");
  const rfmt = (r) => (r == null || isNaN(r) ? "—" : (r >= 0 ? "+" : "") + (+r).toFixed(2) + "R");
  // #81: bucket a realised-R into a colour-scale class. Wins run open-ended
  // (+3R happens); losses are capped near the -1R stop, so the scale is
  // asymmetric — deeper green the bigger the win, red past the full stop.
  const rBucket = (r) =>
    r == null || isNaN(r) ? "rc-na"
    : r >= 2 ? "rc-p3" : r >= 1 ? "rc-p2" : r > 0 ? "rc-p1"
    : r === 0 ? "rc-flat" : r > -1 ? "rc-n1" : "rc-n2";
  // A realised-R rendered as a filled colour-scale chip (#81).
  const rChip = (r) => `<span class="jr-rchip ${rBucket(r)}">${rfmt(r)}</span>`;
  const pcls = (v) => (v >= 0 ? "r-pos" : "r-neg");
  const dfmt = (v) => (v == null || isNaN(v) ? "—" : (v >= 0 ? "+" : "-") + "$" + Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0, minimumFractionDigits: 0 }));
  const d2   = (v) => (v == null || isNaN(v) ? "—" : (v >= 0 ? "+" : "-") + "$" + Math.abs(v).toFixed(2));
  const px   = (v) => (v == null || isNaN(v) ? "—" : (+v).toLocaleString(undefined, { maximumFractionDigits: 6 }));
  const round = (v, n) => +(+v).toFixed(n);

  // SYMBOL → { grade, entry_type } from the live scans, used only as a fallback
  // for older manual trades that were logged before grade/setup were captured.
  const scanMeta = new Map();
  // "market:SYMBOL" → last scan price. The scan refreshes this every run, so it's
  // the reliable "Now" source for manual trades (no flaky live-quote fetch).
  const scanPrice = new Map();

  // ── VIVEK sizing + cost model (live source: data/bot_rules.json) ───────────
  // ONE book of 30 slots across all three markets, $5,000 a position, $150,000
  // total (owner, 2026-07-28). Was 3 × $10k risk-% books; the account is now a
  // single $150k pool, so starting capital is EQUITY, not 3 × EQUITY (the old
  // START_CAPITAL constant was exactly that 3× product and is now gone).
  // Everything below is an OFFLINE FALLBACK only — loadBotRules() overrides
  // from bot_rules.json (published from scanner/config.py every scan), so this
  // file can never drift from the executing bot silently again.
  const RISK_MIN = 0.25, RISK_MAX = 0.5;
  let EQUITY = 150000;                     // fallback — bot_rules.account_equity wins
  let POSITION_NOTIONAL = 5000;            // fallback — 0 would mean risk-% mode
  let RISK_PCT = 0.35;                     // only consulted when POSITION_NOTIONAL is 0
  const money0 = (v) => "$" + Math.round(v).toLocaleString();
  // Starting capital shown to the user. Derived, never hardcoded, so it tracks
  // whatever the bot publishes.
  const startCapital = () => EQUITY;
  const LEVERAGE = { asx: 5, nasdaq: 5, crypto: 3 };                    // fallback
  const SCALE = { long: [0.25, 0.50, 0.15], short: [0.50, 0.25, 0.15] };
  const COMMISSION_BPS = { asx: 2, nasdaq: 1, crypto: 6, default: 2 };  // fallback
  const SLIPPAGE_BPS   = { asx: 5, nasdaq: 4, crypto: 8, default: 5 };  // fallback

  // Adopt the EXECUTING bot's numbers; warn when the JS fallbacks have drifted.
  async function loadBotRules() {
    try {
      const r = await fetch("data/bot_rules.json", { cache: "no-cache" });
      if (!r.ok) return;
      const j = await r.json();
      const drift = {};
      // account_equity + position_notional joined the published set on
      // 2026-07-28 with the fixed-notional switch. A bot_rules.json older than
      // that omits them, so `typeof === "number"` (not `!= null`) is what keeps
      // the fallbacks standing rather than zeroing the book on a stale file.
      for (const [key, cur, set] of [
        ["risk_pct", () => RISK_PCT, (v) => { RISK_PCT = v; }],
        ["account_equity", () => EQUITY, (v) => { EQUITY = v; }],
        ["position_notional", () => POSITION_NOTIONAL, (v) => { POSITION_NOTIONAL = v; }],
      ]) {
        if (typeof j[key] === "number" && j[key] !== cur()) {
          drift[key] = { fallback: cur(), live: j[key] };
          set(j[key]);
        }
      }
      for (const [key, tgt] of [["leverage", LEVERAGE], ["commission_bps", COMMISSION_BPS], ["slippage_bps", SLIPPAGE_BPS]]) {
        const src = j[key];
        if (!src || typeof src !== "object") continue;
        for (const k in tgt) {
          if (typeof src[k] === "number" && src[k] !== tgt[k]) {
            drift[key + "." + k] = { fallback: tgt[k], live: src[k] };
            tgt[k] = src[k];
          }
        }
      }
      if (Object.keys(drift).length) {
        console.warn("[journal] sizing fallbacks drifted from bot_rules.json (scanner/config.py) — live values now in effect:", drift);
        loadMe();     // re-derive manual sizing with the live constants
      }
    } catch (_) { /* offline — fallbacks stand */ }
  }

  const STOCK_TYPES = new Set(["asx", "nasdaq", "commodity", "index"]);
  const NONCRYPTO = new Set(["NAS100","US30","SPX500","GER40","UK100","JP225",
    "GOLD","SILVER","OIL","WTI","BRENT","NATGAS","COPPER","PLATINUM","PALLADIUM","WHEAT","COFFEE"]);
  const YF_TICKER = {
    NAS100:"^NDX",US30:"^DJI",SPX500:"^GSPC",GER40:"^GDAXI",UK100:"^FTSE",JP225:"^N225",
    GOLD:"GC=F",SILVER:"SI=F",COPPER:"HG=F",PLATINUM:"PL=F",PALLADIUM:"PA=F",
    OIL:"CL=F",WTI:"CL=F",BRENT:"BZ=F",NATGAS:"NG=F",WHEAT:"ZW=F",COFFEE:"KC=F",
  };

  function isCryptoTrade(t) {
    // Bot trades carry `market` ("asx"/"nasdaq"/"crypto"); manual trades from the
    // chart carry `asset_type`. Prefer whichever is set so a bot ASX position is
    // never mistaken for crypto (which would misprice + misclassify it).
    const a = (t && (t.market || t.asset_type)) || null;
    if (a === "crypto") return true;
    if (STOCK_TYPES.has(a)) return false;
    if (a == null || a === "") return !NONCRYPTO.has(String((t && t.symbol) || "").toUpperCase());
    return false;
  }
  // Market key for sizing/costs: crypto / asx / nasdaq (stocks default to nasdaq fees).
  function marketOf(t) {
    if (isCryptoTrade(t)) return "crypto";
    if (t.market === "asx" || t.asset_type === "asx") return "asx";
    return "nasdaq";
  }

  // Position size — the exact mirror of vivek_bot.size_position, two modes:
  //
  //   FIXED NOTIONAL (default since 2026-07-28): buy POSITION_NOTIONAL dollars
  //     of the thing. risk_usd falls out of the stop distance instead of being
  //     set by it, so 1R is NOT constant across trades — a tight 2% stop risks
  //     $100 on a $5,000 position, a wide 12% stop risks $600. R-multiples are
  //     unaffected (they were always stop-relative); the $ column is what now
  //     varies. That is the accepted trade-off of fixed sizing.
  //   RISK % (POSITION_NOTIONAL === 0): the original path, unchanged — risk a
  //     clamped slice of equity and derive the size from the stop.
  //
  // Both are capped at the market's leverage ceiling. 1R in dollars ===
  // risk_usd either way, so $ P&L for any VIVEK trade stays R × risk_usd.
  function sizeOf(market, entry, stop) {
    const dist = Math.abs(entry - stop);
    if (!(dist > 0) || !(entry > 0)) return { units: 0, risk_usd: 0, notional: 0, leverage: 0 };
    const fixed = +POSITION_NOTIONAL || 0;
    let units, notional, risk_usd;
    if (fixed > 0) {
      notional = fixed; units = notional / entry; risk_usd = units * dist;
    } else {
      const riskPct = Math.min(Math.max(RISK_PCT, RISK_MIN), RISK_MAX) / 100;
      risk_usd = EQUITY * riskPct; units = risk_usd / dist; notional = units * entry;
    }
    const maxN = EQUITY * (LEVERAGE[market] || LEVERAGE.asx);
    if (notional > maxN) { units = maxN / entry; notional = units * entry; risk_usd = units * dist; }
    return { units, risk_usd, notional, leverage: EQUITY ? notional / EQUITY : 0 };
  }

  const costsFor = (market) => [
    (SLIPPAGE_BPS[market]   ?? SLIPPAGE_BPS.default)   / 1e4,
    (COMMISSION_BPS[market] ?? COMMISSION_BPS.default) / 1e4,
  ];
  // Round-trip cost in R: entry is a market fill; a stop/manual close pays
  // slippage, a resting TP limit does not. Mirrors vivek_journal._cost_r.
  function costR(t, slip, comm) {
    const entry = t.entry, risk = t.risk;
    if (!(risk > 0) || !entry) return 0;
    let cp = entry * (slip + comm);
    for (const ex of t.exits || []) {
      const market = /^(stop|manual)/.test(ex.reason || "");
      cp += (ex.pct || 0) * (ex.price || entry) * (comm + (market ? slip : 0));
    }
    return cp / risk;
  }

  const rOf = (price, entry, risk, isLong) => (isLong ? (price - entry) : (entry - price)) / risk;
  const fav = (nsl, csl, isLong) => (isLong ? nsl > csl : nsl < csl);
  const isVivek = (t) => t && t.stop != null && t.tp1 != null;

  // ── auto-management of a manual position (mirror of vivek_journal._mark) ──────
  function ensureInit(t) {
    if (t._init) return;
    t.market = marketOf(t);
    const isLong = t.direction !== "short";
    if (isVivek(t)) {
      t.risk = Math.abs(t.entry - t.stop);
      t.risk_usd = sizeOf(t.market, t.entry, t.stop).risk_usd;
      if (!Array.isArray(t.scale)) t.scale = SCALE[isLong ? "long" : "short"];
    }
    if (t.gross_r == null) t.gross_r = 0;
    if (t.booked_pct == null) t.booked_pct = 0;
    if (!Array.isArray(t.exits)) t.exits = [];
    if (t.tp1_hit == null) { t.tp1_hit = false; t.tp2_hit = false; t.tp3_hit = false; }
    if (t.mae == null) t.mae = t.entry;
    if (t.mfe == null) t.mfe = t.entry;
    t._init = true;
  }
  function finalizeR(t) {
    const [slip, comm] = costsFor(t.market);
    t.cost_r = round(costR(t, slip, comm), 4);
    t.realized_r = round((t.gross_r || 0) - t.cost_r, 4);
  }
  function book(t, name, price, pct, isLong) {
    t.exits.push({ reason: name, price: round(price, 8), pct, date: today() });
    t.gross_r = round((t.gross_r || 0) + pct * rOf(price, t.entry, t.risk, isLong), 4);
    t.booked_pct = round((t.booked_pct || 0) + pct, 6);
  }
  // Returns the kind of change so the caller can decide whether to PERSIST:
  //   false   — nothing material (or only MAE/MFE drift)
  //   "book"  — a TP scaled out / stop trailed (still open)
  //   "close" — the position closed
  // MAE/MFE high-water marks are tracked in memory only — they moved on almost
  // every tick and were burning the KV write quota; they ride along on the next
  // material save.
  function manage(t, price) {
    if (t.status !== "open" || !isVivek(t) || price == null) return false;
    ensureInit(t);
    const isLong = t.direction !== "short", risk = t.risk;
    if (!(risk > 0)) return false;
    t.mfe = isLong ? Math.max(t.mfe, price) : Math.min(t.mfe, price);
    t.mae = isLong ? Math.min(t.mae, price) : Math.max(t.mae, price);

    let material = false;
    const stopHit = isLong ? price <= t.stop : price >= t.stop;
    if (stopHit) {
      const remaining = round(1 - (t.booked_pct || 0), 6);
      if (remaining > 1e-9) {
        t.exits.push({ reason: "stop", price: round(price, 8), pct: remaining, date: today() });
        t.gross_r = round((t.gross_r || 0) + remaining * rOf(price, t.entry, risk, isLong), 4);
        t.booked_pct = 1;
      }
      t.status = "closed"; t.exit = round(price, 8);
      t.exit_date = today(); t.exit_time = nowTime();
      t.exit_reason = t.tp3_hit ? "target" : (t.tp1_hit ? "trail" : "stop");
      material = true;
    } else {
      const scale = t.scale, reached = (lvl) => (isLong ? price >= lvl : price <= lvl);
      // A TP only counts if it's a genuine profit target BEYOND the entry. This
      // stops a chased entry (taken above the plan's TP1) from instantly booking
      // "TP1" and trailing the stop to break-even on the entry bar.
      const valid = (lvl) => (isLong ? lvl > t.entry : lvl < t.entry);
      if (!t.tp1_hit && t.tp1 != null && valid(t.tp1) && reached(t.tp1)) {
        t.tp1_hit = true; book(t, "tp1", t.tp1, scale[0], isLong);
        if (fav(t.entry, t.stop, isLong)) t.stop = t.entry;        // SL → break-even
        material = true;
      }
      if (!t.tp2_hit && t.tp2 != null && valid(t.tp2) && reached(t.tp2)) {
        t.tp2_hit = true; book(t, "tp2", t.tp2, scale[1], isLong);
        if (fav(t.tp1, t.stop, isLong)) t.stop = t.tp1;            // SL → locked structure
        material = true;
      }
      if (!t.tp3_hit && t.tp3 != null && valid(t.tp3) && reached(t.tp3)) {
        t.tp3_hit = true; book(t, "tp3", t.tp3, scale[2], isLong); material = true;
      }
    }
    if (material) finalizeR(t);
    return material ? (t.status === "closed" ? "close" : "book") : false;
  }
  // Make sure a CLOSED manual trade has its realized R/$ resolved once.
  function ensureClosedR(t) {
    if (t.status !== "closed") return;
    ensureInit(t);
    if (!isVivek(t)) { t.realized_r = null; return; }
    if (!t.exits.length && t.exit != null) {       // a manual full close from the chart
      const isLong = t.direction !== "short";
      t.gross_r = round(rOf(t.exit, t.entry, t.risk, isLong), 4);
      t.exits = [{ reason: "manual", price: t.exit, pct: 1, date: t.exit_date || today() }];
      t.booked_pct = 1;
    }
    finalizeR(t);
  }

  // FX honesty: ASX positions are priced in A$ while NASDAQ/crypto are US$.
  // Every $ AGGREGATE on this page converts ASX P&L to US$ at the scan's
  // published AUD/USD rate (data/fx.json) so the head-to-head totals stop
  // mixing currencies at face value (~50% overstatement of ASX P&L).
  let FX_AUDUSD = 0.66;                       // fallback until fx.json loads
  const fxOf = (t) => ((t.market || t.asset_type) === "asx" ? FX_AUDUSD : 1);
  const dollarsOf = (t) => (t.realized_r != null && t.risk_usd != null
    ? t.realized_r * t.risk_usd * fxOf(t) : null);
  async function loadFx() {
    try {
      const r = await fetch("data/fx.json", { cache: "no-cache" });
      if (r.ok) { const j = await r.json(); if (j && j.audusd > 0) FX_AUDUSD = +j.audusd; }
    } catch (_) { /* keep fallback */ }
  }

  // ── time helpers ──────────────────────────────────────────────────────────
  const pad = (n) => String(n).padStart(2, "0");
  const today = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
  const nowTime = () => { const d = new Date(); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
  function openedMs(t) {
    const ms = Date.parse(t.opened_at || `${t.entry_date || ""}T${t.entry_time || "10:00"}`);
    return isNaN(ms) ? null : ms;
  }
  function exitMs(t) {
    const ms = Date.parse(t.closed_at || `${t.exit_date || ""}T${t.exit_time || "16:00"}`);
    return isNaN(ms) ? null : ms;
  }
  function durText(fromMs, toMs) {
    if (fromMs == null || toMs == null || toMs < fromMs) return "—";
    const h = (toMs - fromMs) / 3.6e6;
    if (h < 24) return `${Math.max(0, Math.round(h))}h`;
    const d = h / 24;
    return d < 10 ? `${d.toFixed(1)}d` : `${Math.round(d)}d`;
  }

  // ── stats + equity ────────────────────────────────────────────────────────
  function stats(closed, openN) {
    const rs = closed.map((t) => t.realized_r).filter((r) => r != null);
    const ds = closed.map((t) => dollarsOf(t)).filter((v) => v != null);
    const wins = rs.filter((r) => r > 0).length;
    // max drawdown on the cumulative $ curve
    let cum = 0, peak = 0, dd = 0;
    for (const v of ds) { cum += v; peak = Math.max(peak, cum); dd = Math.min(dd, cum - peak); }
    return {
      n: closed.length, open: openN,
      totalR: rs.reduce((a, b) => a + b, 0),
      totalD: ds.reduce((a, b) => a + b, 0),
      win: rs.length ? (100 * wins / rs.length) : null,
      maxDD: dd,
    };
  }
  // Equity series ordered by exit time: cumulative R and cumulative $.
  function series(closed) {
    const sorted = closed.slice().filter((t) => t.realized_r != null)
      .sort((a, b) => (exitMs(a) || 0) - (exitMs(b) || 0));
    let r = 0, d = 0;
    const pts = [{ r: 0, d: 0, date: sorted.length ? sorted[0].entry_date || null : null }];
    for (const t of sorted) { r += t.realized_r; d += (dollarsOf(t) || 0); pts.push({ r: round(r, 3), d: round(d, 2), date: t.exit_date || null }); }
    return pts;
  }

  function statCards(host, s, accent) {
    const cell = (label, val, cls) =>
      `<div class="stat-card"><div class="stat-label">${label}</div><div class="stat-value ${cls || ""}">${val}</div></div>`;
    const equity = startCapital() + s.totalD;         // realised account value
    host.innerHTML =
      cell("Account value", `${money0(equity)}<span class="stat-sub"> from ${money0(startCapital())}</span>`, pcls(s.totalD)) +
      cell("Total $", dfmt(s.totalD), pcls(s.totalD)) +
      cell("Total R", rfmt(s.totalR), rcls(s.totalR)) +
      cell("Win rate", s.win == null ? "—" : s.win.toFixed(0) + "%", "") +
      cell("Trades", `${s.n}<span class="stat-sub"> closed · ${s.open} open</span>`, "") +
      cell("Max drawdown", dfmt(s.maxDD), s.maxDD < 0 ? "r-neg" : "");
  }

  // Dual-line equity chart: cumulative $ (filled) + cumulative R (line), each
  // normalised to its own range inside the same box, with end-value labels.
  function drawEquity(elId, pts, label) {
    const el = $("#" + elId);
    if (!el) return;
    if (!pts || pts.length < 2) {
      el.innerHTML = `<div class="jr-empty">No closed trades yet${label ? ` for ${label}` : ""} — the curve appears here.</div>`;
      return;
    }
    const w = 1000, h = 120, pad = 8;
    const norm = (vals) => {
      const mn = Math.min(0, ...vals), mx = Math.max(0, ...vals), rng = (mx - mn) || 1;
      return (v) => h - pad - ((v - mn) / rng) * (h - 2 * pad);
    };
    const xs = (i) => pad + (i / (pts.length - 1)) * (w - 2 * pad);
    const ds = pts.map((p) => p.d), rs = pts.map((p) => p.r);
    const yD = norm(ds), yR = norm(rs);
    const lineD = pts.map((p, i) => `${xs(i).toFixed(1)},${yD(p.d).toFixed(1)}`).join(" ");
    const lineR = pts.map((p, i) => `${xs(i).toFixed(1)},${yR(p.r).toFixed(1)}`).join(" ");
    const area = `${pad},${yD(0).toFixed(1)} ${lineD} ${xs(pts.length - 1).toFixed(1)},${yD(0).toFixed(1)}`;
    const endD = ds[ds.length - 1], endR = rs[rs.length - 1];
    // Softer, muted up/down colours + a fade-to-transparent gradient fill.
    const col = endD >= 0 ? "#3fb784" : "#d07070";
    const gid = elId + "-g";
    const dated = pts.filter((p) => p.date);
    const dlabel = (s) => s ? new Date(s + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "";
    const first = dated.length ? dlabel(dated[0].date) : "";
    const last = dated.length ? dlabel(dated[dated.length - 1].date) : "";
    el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" class="jr-eqsvg">
      <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="${col}" stop-opacity="0.16"/><stop offset="1" stop-color="${col}" stop-opacity="0"/>
      </linearGradient></defs>
      <line x1="0" y1="${yD(0).toFixed(1)}" x2="${w}" y2="${yD(0).toFixed(1)}" stroke="#222a38" stroke-width="1" stroke-dasharray="2 4"/>
      <polygon points="${area}" fill="url(#${gid})"/>
      <polyline points="${lineD}" fill="none" stroke="${col}" stroke-width="1.6" stroke-linejoin="round"/>
      <polyline points="${lineR}" fill="none" stroke="#7aa7e6" stroke-width="1.1" stroke-dasharray="4 5" opacity="0.5"/>
    </svg>
    <div class="jr-eqaxis"><span>${first}</span><span>${last}</span></div>
    <div class="jr-eqtags"><span class="${pcls(endD)}">${dfmt(endD)}</span><span class="lg-r">${rfmt(endR)}</span></div>`;
  }

  // #80: a compact cumulative-$ sparkline for the P&L headline — bot book only
  // (the honest realised record). Just the $ line + a soft fill; no axis/tags.
  function drawMiniEquity(elId, pts) {
    const el = $("#" + elId);
    if (!el) return false;
    if (!pts || pts.length < 2) { el.innerHTML = ""; return false; }
    const w = 240, h = 44, pad = 4;
    const ds = pts.map((p) => p.d);
    const mn = Math.min(0, ...ds), mx = Math.max(0, ...ds), rng = (mx - mn) || 1;
    const y = (v) => h - pad - ((v - mn) / rng) * (h - 2 * pad);
    const x = (i) => pad + (i / (pts.length - 1)) * (w - 2 * pad);
    const line = pts.map((p, i) => `${x(i).toFixed(1)},${y(p.d).toFixed(1)}`).join(" ");
    const endD = ds[ds.length - 1];
    const col = endD >= 0 ? "#3fb784" : "#d07070";
    const area = `${pad},${y(0).toFixed(1)} ${line} ${x(pts.length - 1).toFixed(1)},${y(0).toFixed(1)}`;
    const gid = elId + "-g";
    el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" class="jr-mini-eqsvg" role="img" aria-label="Bot book realised equity curve">
      <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${col}" stop-opacity="0.20"/><stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>
      <line x1="0" y1="${y(0).toFixed(1)}" x2="${w}" y2="${y(0).toFixed(1)}" stroke="#222a38" stroke-width="1" stroke-dasharray="2 4"/>
      <polygon points="${area}" fill="url(#${gid})"/>
      <polyline points="${line}" fill="none" stroke="${col}" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
    return true;
  }

  // ── tables ────────────────────────────────────────────────────────────────
  const gradeChip = (g) => g ? `<span class="g ${GRADE_CLS[g] || "g-c"}">${esc(g)}</span>` : "—";
  // Full-word, dog-balls direction pill (owner 2026-07-10): a trade's
  // AT-ENTRY direction must be unmissable, because the scan's read can flip
  // after entry and the chart may show the opposite setup today.
  const dirChip = (d) => `<span class="dir ${d === "short" ? "dir-s" : "dir-l"}">${d === "short" ? "▼ SHORT" : "▲ LONG"}</span>`;
  // Warn chip when the CURRENT scan reads the opposite way to an open trade.
  const flipChip = (t) => {
    if (t.status === "closed") return "";
    const now = (scanMeta.get(symKey(t)) || {}).dir;
    if (!now) return "";
    const trade = String(t.direction || "long").toUpperCase() === "SHORT" ? "SHORT" : "LONG";
    if (String(now).toUpperCase() === trade) return "";
    return `<span class="jr-flip" title="The scanner's read on this chart flipped AFTER entry — the position was taken as ${trade}">⚠ CHART NOW READS ${esc(String(now).toUpperCase())}</span>`;
  };
  // Grade + setup type: the bot logs these; manual trades now do too. For trades
  // taken before that, fall back to the live scan's grade/trigger for the symbol
  // so older rows aren't blank (scanMeta is filled from *_vivek.json at load).
  const symKey = (t) => String((t && t.symbol) || "").toUpperCase();
  const gradeOf = (t) => t.grade || (scanMeta.get(symKey(t)) || {}).grade || null;
  const entryTypeOf = (t) => t.entry_type || (scanMeta.get(symKey(t)) || {}).entry_type || null;

  // Setup chip: the timeframe + entry trigger of the trade — e.g. "Weekly
  // reclaim" — coloured by trigger (reclaim green / retest red / break amber).
  const SETUP_CLS = { reclaim: "su-reclaim", retest: "su-retest", break: "su-break" };
  const TF_NAME = { "1W": "Weekly", "1D": "Daily", "3D": "3-Day", "4H": "4-Hour" };
  function setupChip(t) {
    const et = String(entryTypeOf(t) || "").toLowerCase();
    const tf = t.timeframe || "";
    if (!et && !tf) return "";
    const tfn = TF_NAME[tf] || tf;
    const label = et ? `${tfn} ${et}` : tfn;
    return `<span class="jr-setup ${SETUP_CLS[et] || ""}" title="Setup">${esc(label)}</span>`;
  }
  // Market chip: which book the ticker belongs to — ASX / NASDAQ / Crypto —
  // colour-coded to match the dashboard's market accents.
  const MKT_LABEL = { asx: "ASX", nasdaq: "NASDAQ", crypto: "CRYPTO" };
  function marketChip(t) {
    const m = marketOf(t);
    return `<span class="jr-mkt jr-mkt-${m}" title="Market">${MKT_LABEL[m] || up(m)}</span>`;
  }
  // Symbol cell links to the chart for that ticker, with market + setup chips after it.
  const symCell = (t) =>
    `<td class="jr-sym" data-label="Position"><a class="jr-symlink" href="chart.html?s=${esc(t.symbol)}&m=${marketOf(t)}&src=journal" title="Open ${up(t.symbol)} chart">` +
    `${dirChip(t.direction)} ${up(t.symbol)}</a>${marketChip(t)}${setupChip(t)}${flipChip(t)}</td>`;
  // Date + time stamp from a parsed epoch (opened / closed).
  function stamp(ms) {
    if (ms == null) return "—";
    const d = new Date(ms); if (isNaN(d)) return "—";
    return `${d.toLocaleDateString(undefined, { day: "numeric", month: "short" })} ${d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
  }

  // Now / Unreal-R / Unreal-$ cells (returned separately — some tables put other
  // columns between Now and the R/$ pair).
  //  • Bot positions are marked to market by the scan SERVER-SIDE every run
  //    (unreal_r / unreal_usd live in the book JSON), so render those straight
  //    away — reliable, refreshed each scan, no client fetch.
  //  • Manual positions are filled by refreshLive (scan-price snapshot first,
  //    then a live quote) — these carry the data-* hooks it reads.
  function liveCellParts(t, side) {
    const isLong = t.direction !== "short";
    if (side === "bot") {
      const risk = t.risk != null ? t.risk : Math.abs(t.entry - (t.stop ?? t.entry));
      const now = (t.unreal_r != null && risk > 0)
        ? (isLong ? t.entry + t.unreal_r * risk : t.entry - t.unreal_r * risk) : null;
      const ur = t.unreal_r, ud = t.unreal_usd != null ? t.unreal_usd * fxOf(t) : null;
      return {
        now: `<td class="num jr-now" data-label="Now">${now != null ? px(now) : "—"}</td>`,
        ur: `<td class="num jr-ur ${ur != null ? rcls(ur) : ""}" data-label="R">${ur != null ? rfmt(ur) : "—"}</td>`,
        ud: `<td class="num jr-ud ${ud != null ? pcls(ud) : ""}" data-label="$">${ud != null ? d2(ud) : "—"}</td>`,
      };
    }
    return {
      now: `<td class="num jr-now" data-label="Now" data-entry="${t.entry}" data-stop="${t.stop ?? ""}" data-long="${isLong}" data-ru="${t.risk_usd ?? ""}">…</td>`,
      ur: `<td class="num jr-ur" data-label="R">—</td>`,
      ud: `<td class="num jr-ud" data-label="$">—</td>`,
    };
  }
  // Now+R+$ as three adjacent cells (for the per-section tables).
  function liveCells(t, side) {
    const p = liveCellParts(t, side);
    return p.now + p.ur + p.ud;
  }

  // Per-section (Claude / Me) tables sit in half-width side-by-side columns, so
  // they carry only the per-side essentials — the full-width combined tables in
  // the comparison overview above show entry/stop/targets/timestamps in full.
  function openRows(list, side, nowMs) {
    if (!list.length) return `<div class="jr-empty">No open positions.</div>`;
    const head = `<tr><th>Symbol</th><th>Gr</th><th class="num">Entry</th><th class="num">Stop</th><th class="num">Now</th>
      <th class="num">R</th><th class="num">$</th><th class="num">Opened</th>${side === "me" ? "<th></th>" : ""}</tr>`;
    // Newest position at the top.
    const rows = list.slice().sort((a, b) => (openedMs(b) || 0) - (openedMs(a) || 0)).map((t) => {
      const isLong = t.direction !== "short";
      const actions = side === "me"
        ? `<td class="num jr-actions"><button class="jr-close-btn" data-close="${esc(t.id)}">Close</button>` +
          `<button class="jr-note-btn${t.note ? " has-note" : ""}" data-note="${esc(t.id)}" ` +
          `title="${t.note ? esc(t.note) : "Add a note — why did you take this trade?"}">📝</button>` +
          `<button class="jr-del-btn" data-del="${esc(t.id)}" title="Remove from journal (no P&L logged)">✕</button></td>` : "";
      return `<tr data-tid="${esc(t.id)}" data-side="${side}">
        ${symCell(t)}
        <td data-label="Grade">${gradeChip(gradeOf(t))}</td>
        <td class="num" data-label="Entry">${px(t.entry)}</td>
        <td class="num" data-label="Stop">${px(t.stop)}</td>
        ${liveCells(t, side)}
        <td class="num jr-stamp" data-label="Opened">${stamp(openedMs(t))}<span class="num-sub"> · ${durText(openedMs(t), nowMs)}</span></td>${actions}</tr>`;
    }).join("");
    return `<table class="jr-table jr-cardable"><thead>${head}</thead><tbody>${rows}</tbody></table>`;
  }

  // UX-20 #13: registry backing the per-row 📤 trade-card buttons — rebuilt on
  // every render so data-card="side:idx" always resolves to the row it sits on.
  const cardReg = { bot: [], me: [] };
  function closedRows(list, side) {
    if (!list.length) return `<div class="jr-empty">No closed trades yet.</div>`;
    const head = `<tr><th>Symbol</th><th>Gr</th><th class="num">R</th><th class="num">$</th>
      <th class="num">Opened</th><th class="num">Closed</th><th>Reason</th></tr>`;
    const sorted = list.slice().sort((a, b) => (exitMs(b) || 0) - (exitMs(a) || 0));
    if (side) cardReg[side] = sorted;
    const rows = sorted.map((t, i) => {
      const d = dollarsOf(t);
      return `<tr>
        ${symCell(t)}
        <td data-label="Grade">${gradeChip(gradeOf(t))}</td>
        <td class="num" data-label="R">${t.realized_r == null ? "—" : rChip(t.realized_r)}</td>
        <td class="num ${d == null ? "" : pcls(d)}" data-label="$">${d == null ? "—" : d2(d)}</td>
        <td class="num jr-stamp" data-label="Opened">${stamp(openedMs(t))}</td>
        <td class="num jr-stamp" data-label="Closed">${stamp(exitMs(t))}<span class="num-sub"> · ${durText(openedMs(t), exitMs(t))}</span></td>
        <td data-label="Reason"><span class="jr-reason jr-reason-${esc(t.exit_reason || "manual")}">${esc(t.exit_reason || "manual")}</span>${t.note ? ` <span class="jr-note-tag" title="${esc(t.note)}">📝</span>` : ""}${side && t.realized_r != null ? ` <button class="jr-card-btn" type="button" data-card="${side}:${i}" title="Download this trade as a shareable card image">📤</button>` : ""}</td></tr>`;
    }).join("");
    return `<table class="jr-table jr-cardable"><thead>${head}</thead><tbody>${rows}</tbody></table>`;
  }

  // UX-20 #13: render a closed trade as a 1000×525 dark PNG card (canvas —
  // no libs) and download it. Symbol, side, grade, entry→exit, the R multiple
  // as the hero number, $ P&L, dates/duration/reason, brand + disclaimer.
  function downloadTradeCard(key) {
    const [side, idx] = String(key).split(":");
    const t = (cardReg[side] || [])[+idx];
    if (!t || t.realized_r == null) return;
    const W = 1000, H = 525, dpr = 2;
    const cv = document.createElement("canvas");
    cv.width = W * dpr; cv.height = H * dpr;
    const x = cv.getContext("2d");
    x.scale(dpr, dpr);
    const r = t.realized_r, win = r > 0;
    const col = win ? "#2fd07f" : r < 0 ? "#ff5b5b" : "#aab4c5";
    // backdrop: near-black with a soft tinted glow from the result side
    x.fillStyle = "#0b0f16"; x.fillRect(0, 0, W, H);
    const glow = x.createRadialGradient(W - 190, H / 2, 40, W - 190, H / 2, 430);
    glow.addColorStop(0, win ? "rgba(47,208,127,0.16)" : r < 0 ? "rgba(255,91,91,0.14)" : "rgba(120,130,150,0.10)");
    glow.addColorStop(1, "rgba(0,0,0,0)");
    x.fillStyle = glow; x.fillRect(0, 0, W, H);
    x.strokeStyle = "rgba(110,125,150,0.28)"; x.lineWidth = 2;
    x.strokeRect(1, 1, W - 2, H - 2);
    const mono = "'JetBrains Mono', ui-monospace, monospace";
    const sans = "Inter, system-ui, sans-serif";
    // header: brand + book + paper tag
    x.fillStyle = "#5b6577"; x.font = `800 20px ${sans}`;
    x.fillText("VIVEK 5.0", 48, 62);
    x.font = `600 15px ${sans}`;
    x.fillText(`${side === "bot" ? "🤖 CLAUDE'S BOT" : "✏️ MANUAL BOOK"} · PAPER TRADE`, 158, 61);
    // symbol + direction + grade
    const sym = up(t.symbol);
    x.fillStyle = "#e5e9f0"; x.font = `800 58px ${sans}`;
    x.fillText(sym, 46, 148);
    const symW = x.measureText(sym).width;
    const dirShort = (t.direction || "long") === "short";
    x.fillStyle = dirShort ? "#ff5b5b" : "#2fd07f"; x.font = `800 24px ${sans}`;
    x.fillText(dirShort ? "▼ SHORT" : "▲ LONG", 58 + symW, 146);
    const g = gradeOf(t);
    if (g) { x.fillStyle = "#ffb020"; x.font = `700 22px ${mono}`; x.fillText(g, 62 + symW + (dirShort ? 118 : 108), 146); }
    x.fillStyle = "#8b96a9"; x.font = `600 17px ${sans}`;
    x.fillText(`${(marketOf(t) || "").toUpperCase()}${t.entry_type ? " · " + String(t.entry_type_label || t.entry_type).toLowerCase() : ""}${t.timeframe ? " · " + (TF_NAME[t.timeframe] || t.timeframe) : ""}`, 48, 182);
    // entry → exit (magnitude-scaled precision — no float noise on the card)
    const exit = t.exit_price ?? t.exit;
    const fp = (v) => v == null || !isFinite(v) ? "—"
      : Math.abs(v) >= 100 ? (+v).toFixed(2) : Math.abs(v) >= 1 ? (+v).toFixed(3)
      : Math.abs(v) >= 0.01 ? (+v).toFixed(4) : (+v).toFixed(6);
    x.fillStyle = "#aab4c5"; x.font = `600 21px ${mono}`;
    x.fillText(`${fp(t.entry)}  →  ${fp(exit)}`, 48, 262);
    x.fillStyle = "#5b6577"; x.font = `600 15px ${sans}`;
    x.fillText("entry → exit", 48, 288);
    // dates + duration + reason
    x.fillStyle = "#8b96a9"; x.font = `600 16px ${mono}`;
    x.fillText(`${stamp(openedMs(t))} → ${stamp(exitMs(t))}  ·  ${durText(openedMs(t), exitMs(t))}  ·  ${t.exit_reason || "manual"}`, 48, 344);
    // the hero number: realised R (+ $ underneath when known)
    x.textAlign = "right";
    x.fillStyle = col; x.font = `800 96px ${mono}`;
    x.fillText(`${r >= 0 ? "+" : ""}${r.toFixed(2)}R`, W - 52, 200);
    const d = dollarsOf(t);
    if (d != null) { x.font = `700 34px ${mono}`; x.fillText(`${d >= 0 ? "+" : "−"}US$${Math.abs(d).toFixed(2)}`, W - 54, 250); }
    x.textAlign = "left";
    // footer rule + disclaimers
    x.strokeStyle = "rgba(110,125,150,0.22)"; x.beginPath(); x.moveTo(48, H - 92); x.lineTo(W - 48, H - 92); x.stroke();
    x.fillStyle = "#5b6577"; x.font = `600 14px ${sans}`;
    x.fillText("Three-lens 200-SMA scanner · paper journal — every trade logged, wins and losses alike.", 48, H - 58);
    x.fillText("General information only — not financial advice.", 48, H - 34);
    cv.toBlob(async (blob) => {
      if (!blob) return;
      const doDownload = () => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `vivek-trade-${sym}-${(t.exit_date || "").replaceAll("-", "") || "card"}.png`;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      };
      // Fix-10 #5: clipboard-first — paste straight into Discord/chat; the
      // toast offers the file too. Falls back to a plain download wherever
      // the clipboard image API isn't available.
      let copied = false;
      try {
        if (navigator.clipboard && window.ClipboardItem) {
          await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
          copied = true;
        }
      } catch (_) {}
      if (copied) gbsToast("📋 Trade card copied — paste it anywhere · tap here to download the file too", doDownload);
      else { doDownload(); gbsToast("⬇ Trade card downloaded"); }
    }, "image/png");
  }

  // Small bottom toast (shared by the trade-card copy + future notices).
  function gbsToast(msg, onTap) {
    document.querySelectorAll(".gbs-toast").forEach((x) => x.remove());
    const el = document.createElement("div");
    el.className = "gbs-toast" + (onTap ? " tappable" : "");
    el.textContent = msg;
    if (onTap) el.addEventListener("click", () => { try { onTap(); } catch (_) {} el.remove(); });
    document.body.appendChild(el);
    setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 400); }, 5600);
  }

  // ── Same positions: you and Claude in the same trade, head to head ─────────
  // A trade "matches" when both sides hold the same symbol, in the same market,
  // the same way (long/short). One shared Now column (same live price for both);
  // Claude's R/$ are marked server-side each scan, yours update live.
  const tradeKey = (t) => `${marketOf(t)}:${symKey(t)}:${t.direction === "short" ? "S" : "L"}`;

  function renderBoth() {
    const openHost = $("#both-open");
    if (!openHost) return;

    // open overlaps — every (Claude, me) pair currently open on the same key
    const meByKey = new Map();
    for (const t of state.me.open) {
      const k = tradeKey(t);
      if (!meByKey.has(k)) meByKey.set(k, []);
      meByKey.get(k).push(t);
    }
    const pairs = [];
    for (const b of state.bot.open) {
      for (const m of meByKey.get(tradeKey(b)) || []) pairs.push([b, m]);
    }
    pairs.sort((a, b) => (openedMs(b[1]) || 0) - (openedMs(a[1]) || 0));
    const nEl = $("#both-open-n");
    if (nEl) nEl.textContent = pairs.length ? `(${pairs.length})` : "";

    if (!pairs.length) {
      openHost.innerHTML = `<div class="jr-empty">No overlap right now — when you and Claude hold the
        same position, it lines up here head to head.</div>`;
    } else {
      const head = `<tr><th>Symbol</th><th class="num">Now</th>
        <th class="num h-bot bsep">🤖 Entry</th><th class="num h-bot">🤖 Opened</th><th class="num h-bot">🤖 R</th><th class="num h-bot">🤖 $</th>
        <th class="num h-me bsep">✏️ Entry</th><th class="num h-me">✏️ Opened</th><th class="num h-me">✏️ R</th><th class="num h-me">✏️ $</th></tr>`;
      const body = pairs.map(([b, m]) => {
        // Claude's cells are static (marked by the scan) — plain classes so
        // refreshLive only drives the Me cells (.jr-ur/.jr-ud) + shared Now.
        const ur = b.unreal_r, ud = b.unreal_usd != null ? b.unreal_usd * fxOf(b) : null;
        const me = liveCellParts(m, "me");
        return `<tr data-tid="${esc(m.id)}" data-side="me">
          ${symCell(b)}
          ${me.now}
          <td class="num bsep">${px(b.entry)}</td>
          <td class="num jr-stamp">${stamp(openedMs(b))}</td>
          <td class="num ${ur != null ? rcls(ur) : ""}">${ur != null ? rfmt(ur) : "—"}</td>
          <td class="num ${ud != null ? pcls(ud) : ""}">${ud != null ? d2(ud) : "—"}</td>
          <td class="num bsep">${px(m.entry)}</td>
          <td class="num jr-stamp">${stamp(openedMs(m))}</td>
          ${me.ur}${me.ud}</tr>`;
      }).join("");
      openHost.innerHTML = `<table class="jr-table jr-cardable"><thead>${head}</thead><tbody>${body}</tbody></table>`;
    }

    // settled head-to-heads — same symbol+direction, both sides fully closed.
    // Totals per symbol (either side may have traded it more than once).
    const agg = (list) => {
      const out = new Map();
      for (const t of list) {
        if (t.realized_r == null) continue;
        const k = tradeKey(t);
        const a = out.get(k) || { n: 0, r: 0, d: 0, t };
        a.n += 1; a.r += t.realized_r; a.d += (dollarsOf(t) || 0);
        out.set(k, a);
      }
      return out;
    };
    const bAgg = agg(state.bot.closed), mAgg = agg(state.me.closed);
    const settled = [];
    for (const [k, b] of bAgg) { const m = mAgg.get(k); if (m) settled.push([b, m]); }
    settled.sort((x, y) => Math.abs(y[0].r + y[1].r) - Math.abs(x[0].r + x[1].r));

    const wrap = $("#both-closed-wrap");
    if (wrap) wrap.hidden = !settled.length;
    if (settled.length) {
      const win = (b, m) => b.r > m.r + 1e-9
        ? `<span class="both-win w-bot">🤖 Claude</span>`
        : m.r > b.r + 1e-9 ? `<span class="both-win w-me">✏️ Me</span>`
        : `<span class="both-win">Tie</span>`;
      const head = `<tr><th>Symbol</th>
        <th class="num h-bot bsep">🤖 R</th><th class="num h-bot">🤖 $</th>
        <th class="num h-me bsep">✏️ R</th><th class="num h-me">✏️ $</th>
        <th class="num">Trades</th><th class="num">Winner</th></tr>`;
      const body = settled.map(([b, m]) => `<tr>
        ${symCell(b.t)}
        <td class="num bsep ${rcls(b.r)}">${rfmt(b.r)}</td>
        <td class="num ${pcls(b.d)}">${d2(b.d)}</td>
        <td class="num bsep ${rcls(m.r)}">${rfmt(m.r)}</td>
        <td class="num ${pcls(m.d)}">${d2(m.d)}</td>
        <td class="num"><span class="num-sub">${b.n} vs ${m.n}</span></td>
        <td class="num">${win(b, m)}</td></tr>`).join("");
      $("#both-closed").innerHTML = `<table class="jr-table jr-cardable"><thead>${head}</thead><tbody>${body}</tbody></table>`;
    }
  }

  // ── live prices (reused from the manual-journal helpers) ──────────────────
  // Hard client-side timeout so a slow/hanging upstream can never leave the
  // "Now" cell stuck on the "…" placeholder — it aborts and we fall back to "—".
  async function fetchJSON(url, ms = 6000) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), ms);
    try {
      const r = await fetch(url, { cache: "no-store", signal: ctrl.signal });
      return r.ok ? await r.json() : null;
    } catch (_) { return null; }
    finally { clearTimeout(t); }
  }
  async function cryptoPrice(sym) {
    const pair = encodeURIComponent(String(sym || "").toUpperCase() + "USDT");
    let j = await fetchJSON(`https://api.binance.com/api/v3/ticker/price?symbol=${pair}`);
    if (j && j.price != null) return +j.price;
    // Binance doesn't list every coin (e.g. BDX/Beldex) — fall back to Yahoo's
    // <base>-USD via our quote proxy so those still get a live price.
    j = await fetchJSON(`/api/quote?sym=${encodeURIComponent(String(sym || "").toUpperCase() + "-USD")}`);
    return j && j.price != null ? +j.price : null;
  }
  async function stockPrice(sym, market) {
    const up_ = String(sym || "").toUpperCase();
    const ticket = YF_TICKER[up_] || (market === "asx" && !String(sym).includes(".") ? sym + ".AX" : sym);
    const j = await fetchJSON(`/api/quote?sym=${encodeURIComponent(ticket)}`);
    return j && j.price != null ? +j.price : null;
  }
  const priceFor = (t) => (marketOf(t) === "crypto" ? cryptoPrice(t.symbol) : stockPrice(t.symbol, marketOf(t)));

  // ── store (manual side) ───────────────────────────────────────────────────
  const MJ_KEY = "gbs:manual_journal";
  function mjLoad() {
    if (window.GBSSync) return window.GBSSync.load();
    try { const r = localStorage.getItem(MJ_KEY); if (r) return JSON.parse(r); } catch (_) {}
    return { trades: [], deleted: [] };
  }
  // Local-only save: for changes the rules COMPUTE (TP scale-outs, stop trails,
  // auto-closes). Every device re-derives these from the same entry/targets +
  // price, so they must NEVER be pushed to the shared cloud store — doing so on
  // every price move is what burned the KV write quota.
  function mjSaveLocal(d) {
    if (window.GBSSync) { window.GBSSync.saveLocal(d); return; }
    localStorage.setItem(MJ_KEY, JSON.stringify(d));
  }
  // Cloud save: ONLY for genuine user actions (take / close / delete / import).
  function mjSave(d) {
    if (window.GBSSync) { window.GBSSync.saveLocal(d); window.GBSSync.syncOutDebounced(); return; }
    localStorage.setItem(MJ_KEY, JSON.stringify(d));
  }

  // ── state + render ────────────────────────────────────────────────────────
  const state = { bot: { open: [], closed: [] }, me: { open: [], closed: [] } };

  function splitBot(book) {
    const open = (book.open || []).slice();
    const closed = (book.closed || []).slice();
    // Bot trades already carry net realized_r + risk_usd from the server.
    // updated_at rides along so the UI can show how fresh the bot's marks are.
    return { open, closed, updated_at: book.updated_at || null };
  }
  function splitMe(data) {
    const trades = (data.trades || []).filter((t) => t && t.status);
    const open = [], closed = [];
    for (const t of trades) {
      if (t.status === "open") { ensureInit(t); open.push(t); }
      else if (t.status === "closed") { ensureClosedR(t); closed.push(t); }
    }
    return { open, closed };
  }

  function renderSide(side) {
    const d = state[side], pre = side;
    const s = stats(d.closed, d.open.length);
    statCards($("#" + pre + "-stats"), s);
    drawEquity(pre + "-equity", series(d.closed), side === "bot" ? "Claude" : "you");
    $("#" + pre + "-open").innerHTML = openRows(d.open, side, Date.now());
    $("#" + pre + "-closed").innerHTML = closedRows(d.closed, side);
    $("#" + pre + "-open-n").textContent = d.open.length ? `(${d.open.length})` : "";
    $("#" + pre + "-closed-n").textContent = d.closed.length ? `(${d.closed.length})` : "";
    return s;
  }

  function renderComparison(sb, sm) {
    drawEquity("cmp-eq-bot", series(state.bot.closed), "Claude");
    drawEquity("cmp-eq-me", series(state.me.closed), "you");
    const row = (label, b, m, fmt, better) => {
      const bv = fmt(b), mv = fmt(m);
      const lead = better == null ? "" : (b > m ? "lead-bot" : m > b ? "lead-me" : "");
      return `<div class="cmp-row ${lead}">
        <span class="cmp-k">${label}</span>
        <span class="cmp-v cmp-bot">${bv}</span>
        <span class="cmp-vs">vs</span>
        <span class="cmp-v cmp-me">${mv}</span></div>`;
    };
    $("#cmp-stats").innerHTML =
      `<div class="cmp-head"><span></span><span class="cmp-bot">🤖 Claude</span><span></span><span class="cmp-me">✏️ Me</span></div>` +
      row("Account value", startCapital() + sb.totalD, startCapital() + sm.totalD, money0, true) +
      row("Total R", sb.totalR, sm.totalR, rfmt, true) +
      row("Total $", sb.totalD, sm.totalD, dfmt, true) +
      row("Win rate", sb.win || 0, sm.win || 0, (v) => v ? v.toFixed(0) + "%" : "—", true) +
      row("Trades", sb.n, sm.n, (v) => String(v), null) +
      row("Open now", sb.open, sm.open, (v) => String(v), null) +
      row("Max DD", sb.maxDD, sm.maxDD, dfmt, null);
  }

  // ── Edge tracker: forward expectancy per setup cell (timeframe × trigger) ──
  // This is the table that eventually says which setups ACTUALLY make money
  // forward — the backtest's answer (weekly reclaim best) checked against real
  // closed trades. Cells need ~20 trades before the numbers mean anything.
  // Bot and manual trades are aggregated in SEPARATE sections (🤖 / ✏️) so the
  // bot's evidence is never contaminated by manual discretion.
  const TRACKER_SIDES = () => [["🤖 Claude", state.bot.closed], ["✏️ Me", state.me.closed]];

  // ── Edge headline card (UX top-10 #8, 2026-07-26) ─────────────────────────
  // The edge tracker's single most important row, surfaced ABOVE the fold:
  // the best-performing setup cell across BOTH books (min 4 closed trades so
  // one lucky fill can't crown itself), plus a caution line when a cell with
  // 4+ trades is bleeding. Same aggregation the folded tracker uses — one
  // number, zero new data.
  function renderEdgeCard() {
    const box = $("#jr-edge-card");
    if (!box) return;
    const closed = TRACKER_SIDES().flatMap(([, list]) => list).filter((t) => t.realized_r != null);
    const cells = new Map();
    for (const t of closed) {
      const tf = TF_NAME[t.timeframe] || t.timeframe || "?";
      const et = String(entryTypeOf(t) || "—").toLowerCase();
      const key = `${tf} ${et}`;
      let c = cells.get(key);
      if (!c) { c = { key, n: 0, wins: 0, sumR: 0 }; cells.set(key, c); }
      c.n += 1; c.sumR += t.realized_r; if (t.realized_r > 0) c.wins += 1;
    }
    const qual = [...cells.values()].filter((c) => c.n >= 4);
    if (!qual.length) { box.hidden = true; return; }
    const best = qual.reduce((a, b) => (b.sumR / b.n > a.sumR / a.n ? b : a));
    const worst = qual.reduce((a, b) => (b.sumR / b.n < a.sumR / a.n ? b : a));
    const avg = best.sumR / best.n, win = Math.round(100 * best.wins / best.n);
    box.hidden = false;
    box.innerHTML =
      `<span class="jr-ec-lbl">📈 What's working</span>` +
      `<span class="jr-ec-cell">${esc(best.key)}</span>` +
      `<b class="jr-ec-r ${rcls(avg)}">${rfmt(avg)} avg</b>` +
      `<span class="jr-ec-sub">${win}% win · ${best.n} closed</span>` +
      (worst !== best && worst.sumR / worst.n < -0.2
        ? `<span class="jr-ec-warn">⚠ leaking: ${esc(worst.key)} ${rfmt(worst.sumR / worst.n)} over ${worst.n}</span>` : "");
  }
  const sideRow = (label, cols) =>
    `<tr><td colspan="${cols}" style="text-align:left;font-weight:700;padding:12px 8px 6px;color:var(--muted)">${label}</td></tr>`;
  const sideEmptyRow = (cols) =>
    `<tr><td colspan="${cols}" style="text-align:left;color:var(--muted)">No closed trades yet.</td></tr>`;
  const thinMark = (n) => n < 20 ? ` <span class="num-sub" title="Fewer than 20 trades — read directionally only">⚠</span>` : "";

  function renderEdgeTracker() {
    const host = $("#edge-tracker");
    if (!host) return;
    const sides = TRACKER_SIDES();
    if (!sides.some(([, list]) => list.some((t) => t.realized_r != null))) {
      host.innerHTML = `<div class="jr-empty">No closed trades yet — as positions close, this breaks down
        win rate and average R by setup (e.g. Weekly reclaim vs Daily reclaim), so you can see which
        cells carry the edge forward, not just in the backtest.</div>`;
      return;
    }
    const section = (label, list) => {
      const closed = list.filter((t) => t.realized_r != null);
      if (!closed.length) return sideRow(label, 5) + sideEmptyRow(5);
      const cells = new Map();
      for (const t of closed) {
        const tf = TF_NAME[t.timeframe] || t.timeframe || "?";
        const et = String(entryTypeOf(t) || "—").toLowerCase();
        const key = `${tf} ${et}`;
        let c = cells.get(key);
        if (!c) { c = { key, et, n: 0, wins: 0, sumR: 0 }; cells.set(key, c); }
        c.n += 1; c.sumR += t.realized_r;
        if (t.realized_r > 0) c.wins += 1;
      }
      return sideRow(label, 5) + [...cells.values()].sort((a, b) => (b.sumR / b.n) - (a.sumR / a.n)).map((c) => {
        const avg = c.sumR / c.n, win = 100 * c.wins / c.n;
        return `<tr>
          <td><span class="jr-setup ${SETUP_CLS[c.et] || ""}">${esc(c.key)}</span></td>
          <td class="num">${c.n}${thinMark(c.n)}</td>
          <td class="num">${win.toFixed(0)}%</td>
          <td class="num ${rcls(avg)}">${rfmt(avg)}</td>
          <td class="num ${rcls(c.sumR)}">${rfmt(c.sumR)}</td></tr>`;
      }).join("");
    };
    host.innerHTML = `<table class="jr-table"><thead><tr>
      <th>Setup</th><th class="num">Trades</th><th class="num">Win %</th>
      <th class="num">Avg R</th><th class="num">Total R</th></tr></thead>
      <tbody>${sides.map(([l, list]) => section(l, list)).join("")}</tbody></table>`;
  }

  // ── Lens tracker: same idea as the edge tracker, but split by which LENS
  // produced the trade (chart.js stamps `lens` on every sim trade since
  // 2026-07-05; vivek_run stamps bot trades since 2026-07-20; older trades
  // group under "untagged"). Bot vs Me aggregated separately, like above.
  function renderLensTracker() {
    const host = $("#lens-tracker");
    if (!host) return;
    const sides = TRACKER_SIDES();
    if (!sides.some(([, list]) => list.some((t) => t.realized_r != null))) {
      host.innerHTML = `<div class="jr-empty">No closed trades yet — as positions close, this shows
        win rate and expectancy per LENS (VIVEK vs PhaseMap vs Specs), so the three-lens system gets
        judged by results, not vibes.</div>`;
      return;
    }
    const section = (label, list) => {
      const closed = list.filter((t) => t.realized_r != null);
      if (!closed.length) return sideRow(label, 6) + sideEmptyRow(6);
      const cells = new Map();
      for (const t of closed) {
        const key = String(t.lens || "untagged").toLowerCase();
        let c = cells.get(key);
        if (!c) { c = { key, n: 0, wins: 0, sumR: 0, sumD: 0 }; cells.set(key, c); }
        c.n += 1; c.sumR += t.realized_r;
        c.sumD += (dollarsOf(t) || 0);
        if (t.realized_r > 0) c.wins += 1;
      }
      return sideRow(label, 6) + [...cells.values()].sort((a, b) => (b.sumR / b.n) - (a.sumR / a.n)).map((c) => {
        const avg = c.sumR / c.n, win = 100 * c.wins / c.n;
        return `<tr>
          <td><span class="jr-setup">${esc(c.key.toUpperCase())}</span></td>
          <td class="num">${c.n}${thinMark(c.n)}</td>
          <td class="num">${win.toFixed(0)}%</td>
          <td class="num ${rcls(avg)}">${rfmt(avg)}</td>
          <td class="num ${rcls(c.sumR)}">${rfmt(c.sumR)}</td>
          <td class="num ${pcls(c.sumD)}">${dfmt(c.sumD)}</td></tr>`;
      }).join("");
    };
    host.innerHTML = `<table class="jr-table"><thead><tr>
      <th>Lens</th><th class="num">Trades</th><th class="num">Win %</th>
      <th class="num">Avg R</th><th class="num">Total R</th><th class="num">Total $</th></tr></thead>
      <tbody>${sides.map(([l, list]) => section(l, list)).join("")}</tbody></table>`;
  }

  // ── NEW POSITIONS RECENTLY TAKEN (owner 2026-07-05): one small box per
  // side at the top of the page — every position opened in the last 7 days,
  // newest first, so the daily check-in is a single glance.
  const NEW_POS_WINDOW_MS = 7 * 24 * 3.6e6;
  function renderNewPositions() {
    const now = Date.now();
    const ago = (ms) => {
      const h = (now - ms) / 3.6e6;
      if (h < 1) return "just now";
      if (h < 24) return Math.round(h) + "h ago";
      const d = Math.floor(h / 24);
      return d === 1 ? "1d ago" : d + "d ago";
    };
    const paint = (hostId, side, label) => {
      const host = $("#" + hostId);
      if (!host) return;
      const recent = [...side.open, ...side.closed]
        .map((t) => ({ t, ms: openedMs(t) }))
        .filter((x) => x.ms != null && now - x.ms <= NEW_POS_WINDOW_MS)
        .sort((a, b) => b.ms - a.ms)
        .slice(0, 6);
      const rows = recent.map(({ t, ms }) =>
        `<a class="jr-new-row" href="chart.html?m=${marketOf(t)}&s=${encodeURIComponent(t.symbol)}&src=journal">
          ${dirChip(t.direction)}
          <b class="jr-new-sym">${esc(t.symbol)}</b>
          <span class="jr-new-entry">@ ${px(t.entry)}</span>
          ${setupChip(t)}
          ${t.lens ? `<span class="jr-new-lens">${up(t.lens)}</span>` : ""}
          ${t.status === "closed" ? `<span class="jr-new-closed">closed</span>` : ""}
          ${flipChip(t)}
          <span class="jr-new-ago">${ago(ms)}</span>
        </a>`).join("");
      host.innerHTML = `<div class="jr-new-hd">${label} <span class="jr-new-n">${recent.length}</span></div>` +
        (rows || `<div class="jr-new-empty">No new positions in the last 7 days.</div>`);
    };
    paint("new-bot", state.bot, "🤖 Claude · new positions");
    paint("new-me", state.me, "✏️ Me · new positions");
  }

  // ── OPEN POSITIONS P&L headline (owner 2026-07-22): the total $ up/down on
  // current positions, before anything else on the page. Bot side comes marked
  // from the book JSON (last scan / kill-switch pricing); the Me side uses the
  // same scan-price snapshot the tables use and re-renders after refreshLive
  // upgrades marks to live quotes. All US$ per the page convention (fx-note).
  function renderPnlHeadline() {
    const box = $("#jr-pnl");
    if (!box) return;
    const botOpen = state.bot.open || [];
    const botU = botOpen.reduce((s, t) => s + (t.unreal_usd != null ? t.unreal_usd * fxOf(t) : 0), 0);
    let meU = 0, meN = 0, mePriced = 0;
    for (const t of state.me.open || []) {
      meN++;
      const price = scanPrice.get(marketOf(t) + ":" + String(t.symbol || "").toUpperCase());
      const isLong = t.direction !== "short";
      const risk = t.risk != null ? t.risk : Math.abs(t.entry - (t.stop ?? t.entry));
      if (price != null && risk > 0 && t.risk_usd != null) {
        meU += rOf(price, t.entry, risk, isLong) * t.risk_usd * fxOf(t);
        mePriced++;
      }
    }
    const total = botU + meU;
    const nOpen = botOpen.length + meN;
    if (!nOpen) { box.hidden = true; return; }
    box.hidden = false;
    const totEl = $("#jr-pnl-total");
    totEl.textContent = d2(total);
    totEl.className = "jr-pnl-total " + pcls(total);
    const t = Date.parse(state.bot.updated_at || "");
    const m = isFinite(t) ? Math.max(0, Math.round((Date.now() - t) / 60000)) : null;
    const age = m == null ? "" : m < 60 ? ` · marked ${m}m ago` : m < 2880 ? ` · marked ${Math.round(m / 60)}h ago` : ` · marked ${Math.round(m / 1440)}d ago`;
    const unpriced = meN - mePriced;
    $("#jr-pnl-sub").textContent =
      `${nOpen} open position${nOpen === 1 ? "" : "s"} · US$${age}` +
      (unpriced > 0 ? ` · ${unpriced} of yours awaiting a price` : "");
    $("#jr-pnl-split").innerHTML =
      `<span class="jr-pnl-chip"><span class="ts-who">🤖 Claude</span> <b class="${pcls(botU)}">${d2(botU)}</b> <span class="ts-who">· ${botOpen.length} open</span></span>` +
      (meN ? `<span class="jr-pnl-chip"><span class="ts-who">✏️ Me</span> <b class="${pcls(meU)}">${d2(meU)}</b> <span class="ts-who">· ${meN} open</span></span>` : "");
    // #80: the bot book's realised equity curve alongside the headline.
    const hasCurve = drawMiniEquity("jr-pnl-spark", series(state.bot.closed));
    const track = $("#jr-pnl-track");
    if (track) track.hidden = !hasCurve;
    if (hasCurve) {
      const bs = stats(state.bot.closed, botOpen.length);
      const tv = $("#jr-pnl-track-val");
      if (tv) { tv.textContent = `${dfmt(bs.totalD)} · ${rfmt(bs.totalR)}`; tv.className = "jr-pnl-track-val " + pcls(bs.totalD); }
    }
  }

  // UX-20 #11 (supersedes #84's rolling bot digest): WEEK REVIEW — calendar
  // weeks (Mon–Sun, local), BOTH books, with ‹ › paging back through history
  // and a per-day dot strip. The ritual it enables: every Friday, page the
  // last few weeks and watch net R by week — the only trend that matters.
  let wkOffset = 0;   // 0 = this week, 1 = last week, …
  function weekBounds(off) {
    const now = new Date();
    const dow = (now.getDay() + 6) % 7;              // Mon=0 … Sun=6
    const mon = new Date(now.getFullYear(), now.getMonth(), now.getDate() - dow - off * 7);
    const start = mon.getTime();
    return { start, end: start + 7 * 86400e3, mon };
  }
  function renderWeeklyDigest() {
    const box = $("#jr-digest");
    if (!box) return;
    const anyEver = (state.bot.closed || []).some((t) => t.realized_r != null) ||
                    (state.me.closed || []).some((t) => t.realized_r != null);
    if (!anyEver) { box.hidden = true; return; }
    box.hidden = false;
    const { start, end, mon } = weekBounds(wkOffset);
    const inWeek = (t) => { const ms = exitMs(t); return ms != null && ms >= start && ms < end && t.realized_r != null; };
    const bot = (state.bot.closed || []).filter(inWeek);
    const me  = (state.me.closed  || []).filter(inWeek);
    const closes = [...bot, ...me];
    const fmtD = (d) => d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
    const range = $("#jr-digest-range");
    if (range) range.textContent = wkOffset === 0
      ? `this week · from ${fmtD(mon)}`
      : `${fmtD(mon)} – ${fmtD(new Date(start + 6 * 86400e3))}`;
    const nextB = $("#jr-wk-next");
    if (nextB) nextB.disabled = wkOffset === 0;
    const grid = $("#jr-digest-grid");
    const days = $("#jr-wk-days");
    if (!closes.length) {
      grid.innerHTML = `<div class="jr-empty jr-wk-empty">No closes this week${wkOffset ? "" : " yet"} — ‹ pages back through past weeks.</div>`;
      if (days) days.innerHTML = "";
      return;
    }
    const totalR = closes.reduce((s, t) => s + t.realized_r, 0);
    const totalD = closes.reduce((s, t) => s + (dollarsOf(t) || 0), 0);
    const wins = closes.filter((t) => t.realized_r > 0).length;
    const best  = closes.reduce((a, b) => (a == null || b.realized_r > a.realized_r ? b : a), null);
    const worst = closes.reduce((a, b) => (a == null || b.realized_r < a.realized_r ? b : a), null);
    const cell = (label, val, cls) =>
      `<div class="jr-dg-cell"><span class="jr-dg-label">${label}</span><span class="jr-dg-val ${cls || ""}">${val}</span></div>`;
    grid.innerHTML =
      cell("Closes", `${closes.length} <span class="num-sub">🤖${bot.length} ✏️${me.length}</span>`, "") +
      cell("Net R", rfmt(totalR), rcls(totalR)) +
      cell("Net $", dfmt(totalD), pcls(totalD)) +
      cell("Win rate", Math.round((wins / closes.length) * 100) + "%", "") +
      (best ? cell("Best", up(best.symbol) + " " + rfmt(best.realized_r), rcls(best.realized_r)) : "") +
      (worst && worst !== best ? cell("Worst", up(worst.symbol) + " " + rfmt(worst.realized_r), rcls(worst.realized_r)) : "");
    if (days) {
      const byDay = Array.from({ length: 7 }, () => []);
      closes.forEach((t) => {
        const i = Math.floor((exitMs(t) - start) / 86400e3);
        if (i >= 0 && i < 7) byDay[i].push(t);
      });
      const names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
      days.innerHTML = byDay.map((list, i) =>
        `<span class="jr-wk-day"><i>${names[i]}</i><span class="jr-wk-dots">${list.map((t) =>
          `<b class="${t.realized_r > 0 ? "dot-win" : t.realized_r < 0 ? "dot-loss" : "dot-flat"}" title="${up(t.symbol)} ${rfmt(t.realized_r)}"></b>`).join("") || `<b class="dot-none"></b>`}</span></span>`).join("");
    }
  }

  // Fix-10 #1: EXIT QUALITY — the bot book records every trade's best (MFE)
  // and worst (MAE) excursion in R. Comparing those to what was actually
  // booked answers the questions a raw win rate can't: are winners being cut
  // early, are stops honest (slippage), and how many losers were green first
  // (a tighter break-even rule would have saved them). Bot book only — the
  // manual side has no excursion marks.
  // A close within this much of -1R counts as "at the stop" — marking is
  // ~15-min delayed, so demanding an exact -1.00R would flag rounding as gaps.
  const SLIP_EPS = 0.05;

  function renderExitQuality() {
    const box = $("#jr-xq");
    if (!box) return;
    const closed = (state.bot.closed || []).filter((t) => t.realized_r != null && t.mfe_r != null && t.mae_r != null);
    if (closed.length < 4) { box.hidden = true; return; }
    const winners = closed.filter((t) => t.realized_r > 0);
    const losers = closed.filter((t) => t.realized_r < 0);
    const avg = (arr, f) => arr.length ? arr.reduce((s, t) => s + f(t), 0) / arr.length : null;
    const cell = (label, val, cls, title) =>
      `<div class="jr-dg-cell" title="${esc(title || "")}"><span class="jr-dg-label">${label}</span><span class="jr-dg-val ${cls || ""}">${val}</span></div>`;
    let cells = "", verdicts = [];
    // winners: peak vs booked
    if (winners.length) {
      const wR = avg(winners, (t) => t.realized_r), wMFE = avg(winners, (t) => t.mfe_r);
      const giveback = wMFE - wR;
      cells += cell("Winners", `${winners.length} · avg ${rfmt(wR)}`, rcls(wR));
      cells += cell("Peak vs booked", `${rfmt(wMFE)} → ${rfmt(wR)}`, giveback > 0.8 ? "neg" : "",
        "Average best excursion (MFE) vs what the exits actually booked");
      if (wMFE > 0) cells += cell("Capture", Math.round((wR / wMFE) * 100) + "%", "",
        "Booked R as a share of the average peak — 100% would mean top-ticking every exit");
      verdicts.push(giveback > 0.8
        ? `Winners peak ${rfmt(wMFE)} on average but book ${rfmt(wR)} — the ladder is giving back ${giveback.toFixed(1)}R; a wider trail past TP2 may pay.`
        : `Exits are capturing most of the winners' move (peak ${rfmt(wMFE)}, booked ${rfmt(wR)}).`);
    } else {
      cells += cell("Winners", "0 yet", "");
    }
    // losers: stop honesty + saveable. The average alone lies when one gap
    // dominates (six exits near -1R plus a single -2.1R read as "-1.15R avg",
    // which used to slip under a 0.25R verdict gate while the cell above it
    // shouted "past plan"). Count how many actually breached the stop and name
    // the worst one, and drive the verdict off the SAME threshold as the cell
    // so the panel can never contradict itself.
    if (losers.length) {
      const lR = avg(losers, (t) => t.realized_r);
      const slip = -1 - lR;                        // how far past -1R the average loss lands
      const worst = losers.reduce((w, t) => (t.realized_r < w.realized_r ? t : w), losers[0]);
      const breached = losers.filter((t) => t.realized_r < -1 - SLIP_EPS);
      const saveable = losers.filter((t) => t.mfe_r >= 0.5);
      cells += cell("Losers", `${losers.length} · avg ${rfmt(lR)}`, rcls(lR));
      cells += cell("Stop slippage", `${slip <= SLIP_EPS ? "≈none" : rfmt(-slip) + " avg past plan"}`, slip > SLIP_EPS ? "neg" : "",
        "Average loser vs the -1R plan — gaps/slippage make losses land beyond the stop");
      cells += cell("Worst loss", `${up(worst.symbol)} ${rfmt(worst.realized_r)}`, rcls(worst.realized_r),
        "The single deepest close — the tail the average hides");
      cells += cell("Past the stop", `${breached.length}/${losers.length}`, breached.length ? "neg" : "",
        "Losers that closed beyond -1R rather than at it");
      cells += cell("Were green first", `${saveable.length}/${losers.length} ≥ +0.5R`, "",
        "Losers whose best excursion reached +0.5R before stopping out");
      if (breached.length) {
        verdicts.push(`${breached.length} of ${losers.length} losers closed past the −1R stop` +
          ` (worst ${up(worst.symbol)} at ${rfmt(worst.realized_r)}, avg ${rfmt(lR)}) — gap/slippage rather than a rule` +
          ` problem, but real risk per losing trade is running about ${(1 + slip).toFixed(2)}× the planned 1R.`);
      } else {
        verdicts.push("Losses are landing where the plan says they should — every loser closed at or inside −1R.");
      }
      if (saveable.length >= 2) verdicts.push(`${saveable.length} losers were up ≥ +0.5R before stopping — evidence for an earlier break-even move.`);
    }
    const sub = $("#jr-xq-sub");
    if (sub) sub.textContent = `${closed.length} closed with excursion marks`;
    $("#jr-xq-grid").innerHTML = cells;
    $("#jr-xq-verdict").textContent = verdicts.join(" ");
    box.hidden = false;
  }

  // UX-20 #10: R-distribution histogram — every closed trade from both books
  // bucketed by realised R. Pure CSS bars; hidden until 5 closes exist.
  function renderRDist() {
    const box = $("#jr-rdist");
    if (!box) return;
    const closed = [...(state.bot.closed || []), ...(state.me.closed || [])]
      .filter((t) => t.realized_r != null);
    if (closed.length < 5) { box.hidden = true; return; }
    const BUCKETS = [
      { lbl: "≤−2R", lo: -Infinity, hi: -2 }, { lbl: "−2…−1", lo: -2, hi: -1 },
      { lbl: "−1…0", lo: -1, hi: 0 }, { lbl: "0…1", lo: 0, hi: 1 },
      { lbl: "1…2", lo: 1, hi: 2 }, { lbl: "2…3", lo: 2, hi: 3 }, { lbl: ">3R", lo: 3, hi: Infinity },
    ];
    const counts = BUCKETS.map((b) => closed.filter((t) => t.realized_r > b.lo && t.realized_r <= b.hi).length);
    const max = Math.max(...counts, 1);
    const avg = closed.reduce((s, t) => s + t.realized_r, 0) / closed.length;
    const sub = $("#jr-rdist-sub");
    if (sub) sub.textContent = `${closed.length} closed · both books · avg ${rfmt(avg)}`;
    $("#jr-rdist-bars").innerHTML = BUCKETS.map((b, i) => {
      const h = counts[i] ? Math.max(6, Math.round((counts[i] / max) * 64)) : 2;
      return `<div class="jr-rd-col" title="${counts[i]} trade${counts[i] === 1 ? "" : "s"} closed ${b.lbl}">
        <span class="jr-rd-n">${counts[i] || ""}</span>
        <i class="jr-rd-bar ${b.hi <= 0 ? "neg" : "pos"}" style="height:${h}px"></i>
        <span class="jr-rd-lbl">${b.lbl}</span></div>`;
    }).join("");
    // Describe the histogram that is actually on screen. The old caption was
    // static prose about an idealised curve ("losses clustered at -1R with a
    // right tail past +2R") and read as a description of the bars beneath it —
    // so a book with no right tail at all still claimed to have one.
    const note = $("#jr-rdist-note");
    if (note) note.textContent = rdistNote(counts, closed.length);
    box.hidden = false;
  }

  // counts index: 0 = <=-2R, 1 = -2..-1, 2 = -1..0, 3 = 0..1, 4 = 1..2, 5 = 2..3, 6 = >3R
  // Phrasing tracks the buckets exactly — bucket 1 is "at or just past -1R"
  // (it spans -2R..-1R inclusive), NOT "inside the stop", or this caption would
  // contradict the exit-quality panel's past-the-stop count sitting above it.
  function rdistNote(counts, n) {
    const deepLoss = counts[0], nearStop = counts[1], insideStop = counts[2];
    const losses = deepLoss + nearStop + insideStop;
    const wins = counts[3] + counts[4] + counts[5] + counts[6];
    const rightTail = counts[4] + counts[5] + counts[6];   // better than +1R
    const want = " A healthy curve clusters losses at −1R and earns a right tail past +2R.";
    if (!wins) {
      const parts = [];
      if (insideStop) parts.push(`${insideStop} stopped inside −1R`);
      if (nearStop) parts.push(`${nearStop} at or just past it`);
      if (deepLoss) parts.push(`${deepLoss} beyond −2R`);
      return `All ${n} closes sit left of zero — ${parts.join(", ")}.` +
        ` There is no right tail yet, and the right tail is where the expectancy lives:` +
        ` this system's edge assumes a handful of +2R and better winners pay for a majority of −1R losses.`;
    }
    if (!rightTail) {
      return `${wins} of ${n} closes are green but none has cleared +1R, against ${losses} losses` +
        `${deepLoss ? ` (${deepLoss} deeper than −2R)` : ""}.` +
        ` Winners are being booked before they can pay for a full loss.` + want;
    }
    if (deepLoss >= Math.max(1, Math.round(losses * 0.25))) {
      return `${deepLoss} of ${losses} losses landed past −2R — a fat left tail means stops are being` +
        ` overrun or overridden, and each one costs two-plus winners to repair.` + want;
    }
    return `${losses} losses at the stop against ${rightTail} winners past +1R` +
      ` — that is the shape the rules are built to produce.`;
  }

  function renderAll() {
    const sb = renderSide("bot"), sm = renderSide("me");
    renderPnlHeadline();
    renderWeeklyDigest();
    renderRDist();               // UX-20 #10
    renderExitQuality();         // Fix-10 #1
    renderEdgeCard();
    renderNewPositions();
    renderComparison(sb, sm);
    renderBoth();
    renderEdgeTracker();
    renderLensTracker();
    const note = $("#bot-note");
    if (note) {
      if (state.bot.open.length || state.bot.closed.length) {
        // Freshness instead of blank: how old are the bot's marks? Amber >2h.
        const t = Date.parse(state.bot.updated_at || "");
        const m = isFinite(t) ? Math.max(0, Math.round((Date.now() - t) / 60000)) : null;
        note.textContent = m == null ? "" :
          m < 60 ? `marked ${m}m ago` : m < 48 * 60 ? `marked ${Math.round(m / 60)}h ago` : `marked ${Math.round(m / 1440)}d ago`;
        note.style.color = m != null && m > 120 ? "var(--orange)" : "";
      } else {
        note.textContent = "Autonomous bot is in dry-run — its trades appear here once enabled.";
      }
    }
    // Always-visible account summary in the sticky topbar: who's where, at a glance.
    const ts = $("#jr-topsum");
    if (ts) {
      const cell = (who, st, openN) =>
        `<span class="ts-who">${who}</span><span class="${pcls(st.totalD)}">${money0(startCapital() + st.totalD)}</span>` +
        `<span class="ts-who">· ${openN} open</span>`;
      ts.innerHTML = cell("🤖", sb, state.bot.open.length) + cell("✏️", sm, state.me.open.length);
    }
    const fxn = $("#fx-note");
    if (fxn) fxn.textContent = ` · $ figures in US$ — ASX P&L converted at AUD/USD ${FX_AUDUSD.toFixed(4)}`;
    // Strategy-review checkpoint (owner decision, locked until the evidence
    // exists): NASDAQ slot weighting + confluence priority get reviewed at 30
    // closed bot trades — not before, so the forward test isn't reset mid-run.
    const chk = $("#review-checkpoint");
    if (chk) {
      const n = state.bot.closed.length;
      chk.textContent = n >= 30
        ? `✅ Review checkpoint reached — ${n}/30 closed bot trades: time to review NASDAQ allocation & confluence priority.`
        : `Strategy review checkpoint: ${n}/30 closed bot trades. NASDAQ allocation & confluence-priority decisions stay locked until then.`;
    }
  }

  // Run async work in small waves so we never burst dozens of quote requests at
  // once (Yahoo throttles bursts, which made the "Now" column fall back to "—").
  async function inBatches(items, size, fn) {
    for (let i = 0; i < items.length; i += size) {
      await Promise.all(items.slice(i, i + size).map(fn));
    }
  }

  // ── live refresh: price the MANUAL opens, auto-manage them, update cells ────
  // Bot rows are already marked to market by the scan (rendered from the book
  // JSON), so this only touches Me rows. Each Me symbol's price comes from the
  // latest scan snapshot first (reliable, refreshes every scan); a live quote is
  // only fetched as a fallback when the symbol isn't in the current scan.
  async function refreshLive() {
    let meChanged = false;   // any persisted change (MAE/MFE, scale-out, close)
    let meClosed = false;    // a position actually CLOSED → rows move tables
    const data = mjLoad();
    const byId = new Map((data.trades || []).map((t) => [t.id, t]));

    // Each Me position is rendered in TWO tables (combined + per-section), so
    // GROUP rows by symbol and resolve each symbol's price once.
    const trs = $$("tbody tr[data-tid][data-side='me']");
    const keyOf = (t) => marketOf(t) + ":" + String(t.symbol || "").toUpperCase();
    const groups = new Map();            // key -> { src, rows:[tr], manual }
    for (const tr of trs) {
      const id = tr.getAttribute("data-tid");
      const src = byId.get(id);
      if (!src) continue;
      const key = keyOf(src);
      let g = groups.get(key);
      if (!g) { g = { src, key, rows: [], manual: src }; groups.set(key, g); }
      g.rows.push(tr);
    }

    const paint = (g, price) => {
      // Remember the freshest mark so the P&L headline uses live quotes too.
      if (price != null) scanPrice.set(g.key, price);
      if (g.manual && price != null) {
        const r = manage(g.manual, price);   // false | "book" | "close"
        if (r) { meChanged = true; if (r === "close") meClosed = true; }
      }
      const src = g.src;
      for (const tr of g.rows) {
        const nowCell = tr.querySelector(".jr-now");
        if (!nowCell || !document.body.contains(nowCell)) continue;
        const urCell = tr.querySelector(".jr-ur");
        const udCell = tr.querySelector(".jr-ud");
        if (price == null) { nowCell.textContent = "—"; continue; }
        const isLong = src.direction !== "short";
        const risk = src.risk != null ? src.risk : Math.abs(src.entry - (src.stop ?? src.entry));
        const ru = src.risk_usd;
        nowCell.textContent = px(price);
        if (src.status === "closed") { nowCell.textContent = "closed"; continue; }
        if (risk > 0) {
          const ur = rOf(price, src.entry, risk, isLong);
          if (urCell) { urCell.textContent = rfmt(ur); urCell.className = "num jr-ur " + rcls(ur); }
          if (ru != null && udCell) { const ud = ur * ru * fxOf(src); udCell.textContent = d2(ud); udCell.className = "num jr-ud " + pcls(ud); }
        }
      }
    };

    // Scan price first (reliable, every scan); live quote only if absent.
    await inBatches([...groups.values()], 6, async (g) => {
      const price = scanPrice.has(g.key) ? scanPrice.get(g.key) : await priceFor(g.src);
      paint(g, price);
    });

    // Persist rule-computed changes (scale-outs, auto-close) LOCALLY only — never
    // to the cloud (each device re-derives them, so cloud pushes here just burned
    // the KV quota). Only RE-RENDER when a position actually closed (rows move
    // between the open/closed tables).
    if (meChanged) mjSaveLocal(data);
    if (meClosed) { loadMe(data); renderAll(); }
    // Live quotes may have upgraded manual marks — refresh the P&L headline.
    renderPnlHeadline();
  }

  // ── loaders ───────────────────────────────────────────────────────────────
  function loadMe(data) { state.me = splitMe(data || mjLoad()); }
  async function loadBot() {
    try {
      const r = await fetch("data/vivek_bot_book.json", { cache: "no-cache" });
      if (r.ok) state.bot = splitBot(await r.json());
    } catch (_) { /* keep empty */ }
  }
  // Pull per-symbol grade/trigger (fallback) + the scan's last price (the Now
  // source for manual trades) from the live scans. Re-runnable: prices overwrite.
  async function loadScanMeta() {
    // Prefer the SLIM per-market companion (2026-07-20, perf): ~5% the size of
    // the full scan files this page used to download (~3MB across markets)
    // just to build a price/grade map. Falls back to the full file per market
    // until the first post-deploy scan publishes the slim ones.
    const markets = ["asx", "nasdaq", "crypto"];
    await Promise.all(markets.map(async (mkt) => {
      try {
        const r = await fetch(`data/${mkt}_prices.json`, { cache: "no-cache" });
        if (r.ok) {
          const j = await r.json();
          const rows = j.rows || {};
          for (const sym in rows) {
            const s = String(sym).toUpperCase(), row = rows[sym] || {};
            if (!scanMeta.has(s)) scanMeta.set(s, { grade: row.grade || null, entry_type: null, dir: row.dir || null });
          }
          const pm = j.prices || {};
          for (const sym in pm) {
            if (pm[sym] != null) scanPrice.set(mkt + ":" + String(sym).toUpperCase(), +pm[sym]);
          }
          return;
        }
      } catch (_) { /* fall through to the full file */ }
      try {
        const r = await fetch(`data/${mkt}_vivek.json`, { cache: "no-cache" });
        if (!r.ok) return;
        const j = await r.json();
        for (const row of (j.results || [])) {
          const sym = String(row.symbol || "").toUpperCase();
          if (!sym) continue;
          if (!scanMeta.has(sym)) scanMeta.set(sym, { grade: row.grade || null, entry_type: row.entry_trigger || null, dir: row.dir || null });
          if (row.price != null) scanPrice.set(mkt + ":" + sym, +row.price);
        }
        // Universe-wide last-close snapshot — covers held names that are no longer
        // a current setup (so any open position can be priced from the scan).
        const pm = j.prices || {};
        for (const sym in pm) {
          if (pm[sym] != null) scanPrice.set(mkt + ":" + String(sym).toUpperCase(), +pm[sym]);
        }
      } catch (_) { /* skip a missing/blocked file */ }
    }));
  }

  // Surface quota-lost saves (2026-07-20): gbs-sync dispatches gbs:save-error
  // when localStorage rejects a write — previously NOTHING listened, so a
  // just-closed trade could vanish silently. Loud, persistent red banner.
  window.addEventListener("gbs:save-error", () => {
    let el = document.getElementById("gbs-save-error");
    if (!el) {
      el = document.createElement("div");
      el.id = "gbs-save-error";
      el.style.cssText = "position:fixed;top:12px;left:50%;transform:translateX(-50%);"
        + "z-index:9999;background:#ff453a;color:#fff;padding:10px 18px;border-radius:12px;"
        + "font-weight:600;font-size:13px;max-width:520px;box-shadow:0 6px 24px rgba(0,0,0,.45)";
      document.body.appendChild(el);
    }
    el.textContent = "STORAGE FULL — this device could NOT save your last change. "
      + "Export a backup now (Backup button), then reload; if it repeats, clear old site data.";
  });

  // ── close modal (Me) ──────────────────────────────────────────────────────
  let closeId = null;
  // #82: what closing at `exit` WOULD book — realised R + $ impact. Clones the
  // trade and runs the exact same resolver the load path uses (ensureClosedR
  // via the same field-sets saveClose does), so the preview equals the outcome.
  function computeCloseOutcome(t, exit) {
    if (!(exit > 0)) return null;
    let c;
    try { c = JSON.parse(JSON.stringify(t)); } catch (_) { return null; }
    c.status = "closed"; c.exit = exit; c.exit_date = today(); c.exit_time = nowTime();
    c.exit_reason = "manual"; delete c._init;
    ensureClosedR(c);
    const r = c.realized_r;
    const dollars = (r != null && c.risk_usd != null) ? r * c.risk_usd * fxOf(c) : null;
    return { r, dollars };
  }
  function updateClosePreview() {
    const box = $("#jr-close-preview");
    if (!box) return;
    const t = closeId && mjLoad().trades.find((x) => x.id === closeId);
    const exit = parseFloat($("#jr-exit-price").value);
    const out = t ? computeCloseOutcome(t, exit) : null;
    if (!out || out.r == null) { box.hidden = true; return; }
    box.hidden = false;
    const rEl = $("#jr-cp-r"), dEl = $("#jr-cp-d");
    rEl.textContent = rfmt(out.r); rEl.className = "jr-cp-val " + rcls(out.r);
    if (out.dollars == null) { dEl.textContent = ""; }
    else { dEl.textContent = dfmt(out.dollars); dEl.className = "jr-cp-val " + pcls(out.dollars); }
    const note = $("#jr-cp-note");
    if (note) note.textContent = out.r >= 0 ? "This is a winning close." : "This books a loss.";
  }

  function openCloseModal(id) {
    const t = mjLoad().trades.find((x) => x.id === id);
    if (!t) return;
    closeId = id;
    $("#jr-modal-title").textContent = "Close " + String(t.symbol || "").toUpperCase();
    $("#jr-exit-price").value = "";
    $("#jr-price-tag").textContent = "loading live…";
    const box = $("#jr-close-preview"); if (box) box.hidden = true;
    $("#jr-close-overlay").hidden = false;
    priceFor(t).then((p) => {
      if (p != null) { $("#jr-exit-price").value = +(+p).toFixed(6); $("#jr-price-tag").textContent = "live"; }
      else $("#jr-price-tag").textContent = "";
      updateClosePreview();
    });
  }
  function closeModal() { $("#jr-close-overlay").hidden = true; closeId = null; }

  // Remove a manual trade entirely (no P&L logged) — for setups you logged but
  // didn't actually take (e.g. a fund/REIT not listed on your broker). Records a
  // tombstone so the deletion propagates across synced devices.
  // Post-trade review needs the WHY, not just the numbers — a free-text note
  // per manual trade (cloud-synced: adding/editing one is a genuine user action).
  function editNote(id) {
    const data = mjLoad();
    const t = data.trades.find((x) => x.id === id);
    if (!t) return;
    const note = prompt(`Note for ${String(t.symbol || "").toUpperCase()} — why did you take it?`,
                        t.note || "");
    if (note == null) return;                      // cancelled
    t.note = note.trim();
    if (!t.note) delete t.note;
    t.mtime = Date.now();
    mjSave(data);
    renderAll();
    refreshLive();
  }

  function removeTrade(id) {
    const data = mjLoad();
    const t = (data.trades || []).find((x) => x.id === id);
    if (!t) return;
    const sym = String(t.symbol || "").toUpperCase();
    if (!confirm(`Remove ${sym} from your journal?\n\nThis deletes the trade entirely — no profit/loss is logged. Use this for setups you didn't actually take.`)) return;
    data.trades = (data.trades || []).filter((x) => x.id !== id);
    if (!Array.isArray(data.deleted)) data.deleted = [];
    if (!data.deleted.includes(id)) data.deleted.push(id);
    mjSave(data); loadMe(data); renderAll(); refreshLive();
  }
  function saveClose() {
    if (!closeId) return;
    const data = mjLoad();
    const t = data.trades.find((x) => x.id === closeId);
    const exit = parseFloat($("#jr-exit-price").value);
    if (!t || !(exit > 0)) return;
    t.status = "closed"; t.exit = exit; t.exit_date = today(); t.exit_time = nowTime();
    t.exit_reason = "manual"; t.mtime = Date.now();
    delete t._init;                              // force a clean re-resolve
    mjSave(data); closeModal(); loadMe(data); renderAll(); refreshLive();
  }

  // ── cross-device sync + backup/restore (Cloudflare KV via gbs-sync) ────────
  function syncStatus(msg, cls) {
    const el = $("#mj-sync-status");
    if (el) { el.textContent = msg || ""; el.className = "mj-sync-status" + (cls ? " " + cls : ""); }
  }
  // #83: the always-visible header pill — synced / local-only / error. `error`
  // sticks until the next successful reflect() clears it.
  function reflectSyncPill(errored) {
    const pill = $("#jr-sync-pill");
    if (!pill) return;
    const on = !!(window.GBSSync && window.GBSSync.enabled());
    let cls, txt;
    if (errored) { cls = "err"; txt = "⚠ Sync error"; }
    else if (on) { cls = "on"; txt = "☁ Synced"; }
    else { cls = "off"; txt = "📴 Local only"; }
    pill.className = "jr-sync-pill " + cls;
    pill.textContent = txt;
  }
  function afterStoreChange() { loadMe(); renderAll(); refreshLive(); }
  function wireSync() {
    // Backup / Restore
    const exportBtn = $("#mj-export-btn");
    if (exportBtn) exportBtn.addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(mjLoad(), null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = Object.assign(document.createElement("a"), { href: url, download: `my-trades-${today()}.json` });
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    // CSV of BOTH books (open + closed) — for tax time and Excel analysis.
    // $ P&L column is US$-converted like the page; native risk/prices as-is.
    const csvBtn = $("#mj-csv-btn");
    if (csvBtn) csvBtn.addEventListener("click", () => {
      const cols = ["side", "symbol", "market", "direction", "grade", "entry_type",
                    "timeframe", "status", "entry", "stop", "exit", "entry_date",
                    "exit_date", "exit_reason", "realized_r", "risk_usd",
                    "pnl_usd", "note"];
      const csvEsc = (v) => {
        const s = v == null ? "" : String(v);
        return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
      };
      const rows = [];
      const push = (t, side) => rows.push(cols.map((c) => csvEsc(
        c === "side" ? side
        : c === "pnl_usd" ? (dollarsOf(t) == null ? "" : dollarsOf(t).toFixed(2))
        : c === "market" ? marketOf(t)
        : t[c])).join(","));
      for (const t of [...state.bot.open, ...state.bot.closed]) push(t, "claude");
      for (const t of [...state.me.open, ...state.me.closed]) push(t, "me");
      const blob = new Blob([cols.join(",") + "\n" + rows.join("\n") + "\n"], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = Object.assign(document.createElement("a"), { href: url, download: `vivek-journal-${today()}.csv` });
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    const importBtn = $("#mj-import-btn"), importInput = $("#mj-import-input");
    if (importBtn && importInput) {
      importBtn.addEventListener("click", () => importInput.click());
      importInput.addEventListener("change", () => {
        const file = importInput.files && importInput.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = () => {
          let incoming;
          try { incoming = JSON.parse(reader.result); } catch (_) { alert("That file isn't valid trade backup JSON."); return; }
          if (!incoming || !Array.isArray(incoming.trades)) { alert("That file doesn't look like a trades backup."); return; }
          const merged = window.GBSSync ? window.GBSSync.merge(mjLoad(), incoming) : incoming;
          mjSave(merged); afterStoreChange();
          alert(`Imported — ${merged.trades.length} trade(s) now in your journal.`);
        };
        reader.readAsText(file); importInput.value = "";
      });
    }
    // Cloud sync (private code)
    const codeEl = $("#mj-sync-code"), onBtn = $("#mj-sync-on"), offBtn = $("#mj-sync-off"), nowBtn = $("#mj-sync-now");
    if (!codeEl || !window.GBSSync) return;
    const reflect = () => {
      const on = window.GBSSync.enabled();
      codeEl.value = on ? window.GBSSync.getCode() : "";
      if (onBtn) onBtn.classList.toggle("mj-hidden", on);
      if (offBtn) offBtn.classList.toggle("mj-hidden", !on);
      if (nowBtn) nowBtn.classList.toggle("mj-hidden", !on);
      syncStatus(on ? "Sync ON — same trades on every device with this code." : "", on ? "live" : "");
      reflectSyncPill(false);   // #83
    };
    // #83: the header pill opens the (folded) sync settings; a save/sync error
    // anywhere flips it to the error state until the next clean reflect().
    const pill = $("#jr-sync-pill");
    if (pill) pill.addEventListener("click", () => {
      const fold = codeEl.closest("details.jr-fold");
      if (fold) { fold.open = true; fold.scrollIntoView({ behavior: "smooth", block: "center" }); }
      codeEl.focus();
    });
    window.addEventListener("gbs:save-error", () => reflectSyncPill(true));
    const enable = async () => {
      const code = (codeEl.value || "").trim();
      if (code.length < 4) { syncStatus("Pick a code with at least 4 characters.", "neg"); return; }
      window.GBSSync.setCode(code); syncStatus("Connecting…");
      try {
        const probe = await window.GBSSync.pull();
        if (probe.configured === false) {
          window.GBSSync.setCode(""); reflect();
          syncStatus("Cloud sync isn't set up on the server yet — use Backup/Restore for now.", "neg"); return;
        }
        await window.GBSSync.syncOut(); afterStoreChange(); reflect();
      } catch (_) { syncStatus("Couldn't reach the sync server — trades are still saved on this device.", "neg"); reflectSyncPill(true); }
    };
    const syncedAt = () => syncStatus("Synced at " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), "live");
    if (onBtn) onBtn.addEventListener("click", enable);
    if (offBtn) offBtn.addEventListener("click", () => { window.GBSSync.setCode(""); reflect(); syncStatus("Sync off — this device keeps its own copy."); });
    if (nowBtn) nowBtn.addEventListener("click", async () => { syncStatus("Syncing…"); try { await window.GBSSync.syncOut(); afterStoreChange(); syncedAt(); } catch (_) { syncStatus("Sync failed — will retry on the next change.", "neg"); reflectSyncPill(true); } });
    codeEl.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); enable(); } });
    const silentPull = async () => { if (!window.GBSSync.enabled()) return; try { await window.GBSSync.syncIn(); afterStoreChange(); syncedAt(); } catch (_) {} };
    document.addEventListener("visibilitychange", () => { if (!document.hidden) silentPull(); });
    setInterval(() => { if (!document.hidden) silentPull(); }, 60000);
    reflect();
    if (window.GBSSync.enabled()) silentPull();
  }

  // ── wire-up ───────────────────────────────────────────────────────────────
  function wire() {
    document.addEventListener("click", (e) => {
      const del = e.target.closest("[data-del]");
      if (del) { removeTrade(del.getAttribute("data-del")); return; }
      const noteBtn = e.target.closest("[data-note]");
      if (noteBtn) { editNote(noteBtn.getAttribute("data-note")); return; }
      const card = e.target.closest("[data-card]");
      if (card) { downloadTradeCard(card.getAttribute("data-card")); return; }   // UX-20 #13
      const btn = e.target.closest("[data-close]");
      if (btn) openCloseModal(btn.getAttribute("data-close"));
    });
    // UX-20 #11: page the week review back / forward
    const wp = $("#jr-wk-prev"), wn = $("#jr-wk-next");
    if (wp) wp.addEventListener("click", () => { wkOffset++; renderWeeklyDigest(); });
    if (wn) wn.addEventListener("click", () => { if (wkOffset > 0) { wkOffset--; renderWeeklyDigest(); } });
    $("#jr-modal-x").addEventListener("click", closeModal);
    $("#jr-modal-cancel").addEventListener("click", closeModal);
    $("#jr-modal-save").addEventListener("click", saveClose);
    $("#jr-exit-price").addEventListener("input", updateClosePreview);   // #82 live R/$ preview
    $("#jr-close-overlay").addEventListener("click", (e) => { if (e.target.id === "jr-close-overlay") closeModal(); });
    // react to manual trades opened on another tab/device
    window.addEventListener("storage", (e) => { if (e.key === MJ_KEY) { loadMe(); renderAll(); refreshLive(); } });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshLive(); });
    setInterval(() => { if (!document.hidden) refreshLive(); }, 20000);
    // Pick up a fresh scan while the page is open: re-pull the bot book + scan
    // prices every few minutes and re-render (the bot side + manual Now update).
    setInterval(async () => {
      if (document.hidden) return;
      await Promise.all([loadBot(), loadScanMeta()]);
      renderAll();
      refreshLive();
    }, 180000);
  }

  async function init() {
    loadMe();
    renderAll();                 // paint Me immediately
    await Promise.all([loadBot(), loadScanMeta(), loadFx(), loadBotRules()]);
    renderAll();                 // repaint with Claude + live rules + grade/setup fallback
    wire();
    wireSync();
    refreshLive();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
