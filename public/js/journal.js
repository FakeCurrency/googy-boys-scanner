/* Paper-trade journal — Claude (bot) vs Me (manual), head to head.
 *
 *  • Claude  = the autonomous bot's paper book  (data/vivek_bot_book.json),
 *              written server-side every scan. Read-only here.
 *  • Me      = the trades you take from the charts (the shared manual store,
 *              localStorage + optional cross-device sync). Sized + managed by
 *              the SAME VIVEK rules as the bot: risk 0.35% of a $10k book,
 *              5× stocks / 3× crypto leverage cap, scale at TP1/2/3, SL → BE at
 *              TP1 → locked structure at TP2, close on the stop. You pick the
 *              setup; the rules run the trade. $ P&L uses 1R = the $ risked.
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
  const pcls = (v) => (v >= 0 ? "r-pos" : "r-neg");
  const dfmt = (v) => (v == null || isNaN(v) ? "—" : (v >= 0 ? "+" : "-") + "$" + Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0, minimumFractionDigits: 0 }));
  const d2   = (v) => (v == null || isNaN(v) ? "—" : (v >= 0 ? "+" : "-") + "$" + Math.abs(v).toFixed(2));
  const px   = (v) => (v == null || isNaN(v) ? "—" : (+v).toLocaleString(undefined, { maximumFractionDigits: 6 }));
  const round = (v, n) => +(+v).toFixed(n);

  // SYMBOL → { grade, entry_type } from the live scans, used only as a fallback
  // for older manual trades that were logged before grade/setup were captured.
  const scanMeta = new Map();

  // ── VIVEK sizing + cost model (mirrors scanner/broker/vivek_bot.py + config) ──
  // Each market is sized off its own $10k book; the account spans all three, so
  // the starting capital shown to the user is 3 × $10k = $30k.
  const EQUITY = 10000, RISK_PCT = 0.35, RISK_MIN = 0.25, RISK_MAX = 0.5;
  const START_CAPITAL = EQUITY * 3;        // $30k — ASX + NASDAQ + Crypto books
  const money0 = (v) => "$" + Math.round(v).toLocaleString();
  const LEVERAGE = { asx: 5, nasdaq: 5, crypto: 3 };
  const SCALE = { long: [0.25, 0.50, 0.15], short: [0.50, 0.25, 0.15] };
  const COMMISSION_BPS = { asx: 2, nasdaq: 1, crypto: 6, default: 2 };
  const SLIPPAGE_BPS   = { asx: 5, nasdaq: 4, crypto: 8, default: 5 };

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

  // Risk-based size: risk a slice of equity, cap notional at the market leverage.
  // 1R in dollars === risk_usd, so $ P&L for any VIVEK trade = R × risk_usd.
  function sizeOf(market, entry, stop) {
    const riskPct = Math.min(Math.max(RISK_PCT, RISK_MIN), RISK_MAX) / 100;
    const dist = Math.abs(entry - stop);
    if (!(dist > 0) || !(entry > 0)) return { units: 0, risk_usd: 0, notional: 0, leverage: 0 };
    let risk_usd = EQUITY * riskPct, units = risk_usd / dist, notional = units * entry;
    const maxN = EQUITY * (LEVERAGE[market] || LEVERAGE.asx);
    if (notional > maxN) { units = maxN / entry; notional = units * entry; risk_usd = units * dist; }
    return { units, risk_usd, notional, leverage: notional / EQUITY };
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
  // Returns true if the trade changed state (so the store should be persisted).
  function manage(t, price) {
    if (t.status !== "open" || !isVivek(t) || price == null) return false;
    ensureInit(t);
    const isLong = t.direction !== "short", risk = t.risk;
    if (!(risk > 0)) return false;
    let changed = false;
    const nmfe = isLong ? Math.max(t.mfe, price) : Math.min(t.mfe, price);
    const nmae = isLong ? Math.min(t.mae, price) : Math.max(t.mae, price);
    if (nmfe !== t.mfe) { t.mfe = nmfe; changed = true; }
    if (nmae !== t.mae) { t.mae = nmae; changed = true; }

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
      changed = true;
    } else {
      const scale = t.scale, reached = (lvl) => (isLong ? price >= lvl : price <= lvl);
      // A TP only counts if it's a genuine profit target BEYOND the entry. This
      // stops a chased entry (taken above the plan's TP1) from instantly booking
      // "TP1" and trailing the stop to break-even on the entry bar.
      const valid = (lvl) => (isLong ? lvl > t.entry : lvl < t.entry);
      if (!t.tp1_hit && t.tp1 != null && valid(t.tp1) && reached(t.tp1)) {
        t.tp1_hit = true; book(t, "tp1", t.tp1, scale[0], isLong);
        if (fav(t.entry, t.stop, isLong)) t.stop = t.entry;        // SL → break-even
        changed = true;
      }
      if (!t.tp2_hit && t.tp2 != null && valid(t.tp2) && reached(t.tp2)) {
        t.tp2_hit = true; book(t, "tp2", t.tp2, scale[1], isLong);
        if (fav(t.tp1, t.stop, isLong)) t.stop = t.tp1;            // SL → locked structure
        changed = true;
      }
      if (!t.tp3_hit && t.tp3 != null && valid(t.tp3) && reached(t.tp3)) {
        t.tp3_hit = true; book(t, "tp3", t.tp3, scale[2], isLong); changed = true;
      }
    }
    if (changed) finalizeR(t);
    return changed;
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

  const dollarsOf = (t) => (t.realized_r != null && t.risk_usd != null ? t.realized_r * t.risk_usd : null);

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
    const equity = START_CAPITAL + s.totalD;          // realised account value
    host.innerHTML =
      cell("Account value", `${money0(equity)}<span class="stat-sub"> from ${money0(START_CAPITAL)}</span>`, pcls(s.totalD)) +
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

  // ── tables ────────────────────────────────────────────────────────────────
  const gradeChip = (g) => g ? `<span class="g ${GRADE_CLS[g] || "g-c"}">${esc(g)}</span>` : "—";
  const dirChip = (d) => `<span class="dir ${d === "short" ? "dir-s" : "dir-l"}">${d === "short" ? "S" : "L"}</span>`;
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
    `<td class="jr-sym"><a class="jr-symlink" href="chart.html?s=${esc(t.symbol)}&m=${marketOf(t)}" title="Open ${up(t.symbol)} chart">` +
    `${dirChip(t.direction)} ${up(t.symbol)}</a>${marketChip(t)}${setupChip(t)}</td>`;
  // Date + time stamp from a parsed epoch (opened / closed).
  function stamp(ms) {
    if (ms == null) return "—";
    const d = new Date(ms); if (isNaN(d)) return "—";
    return `${d.toLocaleDateString(undefined, { day: "numeric", month: "short" })} ${d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
  }

  // Per-section (Claude / Me) tables sit in half-width side-by-side columns, so
  // they carry only the per-side essentials — the full-width combined tables in
  // the comparison overview above show entry/stop/targets/timestamps in full.
  function openRows(list, side, nowMs) {
    if (!list.length) return `<div class="jr-empty">No open positions.</div>`;
    const head = `<tr><th>Symbol</th><th>Gr</th><th class="num">Entry</th><th class="num">Now</th>
      <th class="num">R</th><th class="num">$</th>${side === "me" ? "<th></th>" : ""}</tr>`;
    const rows = list.map((t) => {
      const isLong = t.direction !== "short";
      const actions = side === "me"
        ? `<td class="num jr-actions"><button class="jr-close-btn" data-close="${esc(t.id)}">Close</button>` +
          `<button class="jr-del-btn" data-del="${esc(t.id)}" title="Remove from journal (no P&L logged)">✕</button></td>` : "";
      return `<tr data-tid="${esc(t.id)}" data-side="${side}">
        ${symCell(t)}
        <td>${gradeChip(gradeOf(t))}</td>
        <td class="num">${px(t.entry)}</td>
        <td class="num jr-now" data-entry="${t.entry}" data-stop="${t.stop ?? ""}" data-long="${isLong}" data-ru="${t.risk_usd ?? ""}">…</td>
        <td class="num jr-ur">—</td>
        <td class="num jr-ud">—</td>${actions}</tr>`;
    }).join("");
    return `<table class="jr-table"><thead>${head}</thead><tbody>${rows}</tbody></table>`;
  }

  function closedRows(list) {
    if (!list.length) return `<div class="jr-empty">No closed trades yet.</div>`;
    const head = `<tr><th>Symbol</th><th>Gr</th><th class="num">R</th><th class="num">$</th>
      <th class="num">Closed</th><th>Reason</th></tr>`;
    const rows = list.slice().sort((a, b) => (exitMs(b) || 0) - (exitMs(a) || 0)).map((t) => {
      const d = dollarsOf(t);
      return `<tr>
        ${symCell(t)}
        <td>${gradeChip(gradeOf(t))}</td>
        <td class="num ${t.realized_r == null ? "" : rcls(t.realized_r)}">${rfmt(t.realized_r)}</td>
        <td class="num ${d == null ? "" : pcls(d)}">${d == null ? "—" : d2(d)}</td>
        <td class="num jr-stamp">${stamp(exitMs(t))}</td>
        <td><span class="jr-reason jr-reason-${esc(t.exit_reason || "manual")}">${esc(t.exit_reason || "manual")}</span></td></tr>`;
    }).join("");
    return `<table class="jr-table"><thead>${head}</thead><tbody>${rows}</tbody></table>`;
  }

  // Combined tables (Claude + Me together) for the comparison overview.
  const ownerChip = (side) => side === "bot"
    ? `<span class="own own-bot" title="Claude (bot)">🤖</span>`
    : `<span class="own own-me" title="Me (manual)">✏️</span>`;

  function combinedOpen(nowMs) {
    const rows = [...state.bot.open.map((t) => ["bot", t]), ...state.me.open.map((t) => ["me", t])];
    if (!rows.length) return `<div class="jr-empty">No open positions on either side.</div>`;
    const head = `<tr><th>Who</th><th>Symbol</th><th>Gr</th><th class="num">Entry</th><th class="num">Stop</th>
      <th class="num">Targets</th><th class="num">Now</th><th class="num">Opened</th><th class="num">In&nbsp;trade</th>
      <th class="num">Unreal R</th><th class="num">Unreal $</th><th></th></tr>`;
    const body = rows.map(([side, t]) => {
      const isLong = t.direction !== "short";
      const tps = [t.tp1, t.tp2, t.tp3].filter((v) => v != null).map((v) => px(v)).join(" / ") || "—";
      const actions = side === "me"
        ? `<button class="jr-close-btn" data-close="${esc(t.id)}">Close</button>` +
          `<button class="jr-del-btn" data-del="${esc(t.id)}" title="Remove from journal (no P&L logged)">✕</button>` : "";
      return `<tr data-tid="${esc(t.id)}" data-side="${side}">
        <td>${ownerChip(side)}</td>
        ${symCell(t)}
        <td>${gradeChip(gradeOf(t))}</td>
        <td class="num">${px(t.entry)}</td>
        <td class="num">${px(t.stop)}</td>
        <td class="num"><span class="num-sub">${tps}</span></td>
        <td class="num jr-now" data-entry="${t.entry}" data-stop="${t.stop ?? ""}" data-long="${isLong}" data-ru="${t.risk_usd ?? ""}">…</td>
        <td class="num jr-stamp">${stamp(openedMs(t))}</td>
        <td class="num jr-dur">${durText(openedMs(t), nowMs)}</td>
        <td class="num jr-ur">—</td>
        <td class="num jr-ud">—</td>
        <td class="num jr-actions">${actions}</td></tr>`;
    }).join("");
    return `<table class="jr-table"><thead>${head}</thead><tbody>${body}</tbody></table>`;
  }

  function combinedClosed() {
    const rows = [...state.bot.closed.map((t) => ["bot", t]), ...state.me.closed.map((t) => ["me", t])]
      .sort((a, b) => (exitMs(b[1]) || 0) - (exitMs(a[1]) || 0));
    if (!rows.length) return `<div class="jr-empty">No closed trades yet on either side.</div>`;
    const head = `<tr><th>Who</th><th>Symbol</th><th>Gr</th><th class="num">Entry</th><th class="num">Exit</th>
      <th class="num">R</th><th class="num">$</th><th class="num">Opened</th><th class="num">Closed</th><th class="num">In&nbsp;trade</th><th>Reason</th></tr>`;
    const body = rows.map(([side, t]) => {
      const dd = dollarsOf(t);
      return `<tr>
        <td>${ownerChip(side)}</td>
        ${symCell(t)}
        <td>${gradeChip(gradeOf(t))}</td>
        <td class="num">${px(t.entry)}</td>
        <td class="num">${px(t.exit)}</td>
        <td class="num ${t.realized_r == null ? "" : rcls(t.realized_r)}">${rfmt(t.realized_r)}</td>
        <td class="num ${dd == null ? "" : pcls(dd)}">${dd == null ? "—" : d2(dd)}</td>
        <td class="num jr-stamp">${stamp(openedMs(t))}</td>
        <td class="num jr-stamp">${stamp(exitMs(t))}</td>
        <td class="num">${durText(openedMs(t), exitMs(t))}</td>
        <td><span class="jr-reason jr-reason-${esc(t.exit_reason || "manual")}">${esc(t.exit_reason || "manual")}</span></td></tr>`;
    }).join("");
    return `<table class="jr-table"><thead>${head}</thead><tbody>${body}</tbody></table>`;
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
    return { open, closed };
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
    $("#" + pre + "-closed").innerHTML = closedRows(d.closed);
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
      row("Account value", START_CAPITAL + sb.totalD, START_CAPITAL + sm.totalD, money0, true) +
      row("Total R", sb.totalR, sm.totalR, rfmt, true) +
      row("Total $", sb.totalD, sm.totalD, dfmt, true) +
      row("Win rate", sb.win || 0, sm.win || 0, (v) => v ? v.toFixed(0) + "%" : "—", true) +
      row("Trades", sb.n, sm.n, (v) => String(v), null) +
      row("Open now", sb.open, sm.open, (v) => String(v), null) +
      row("Max DD", sb.maxDD, sm.maxDD, dfmt, null);

    // Combined open + closed trades (both sides together) under the overview.
    $("#cmp-open").innerHTML = combinedOpen(Date.now());
    $("#cmp-closed").innerHTML = combinedClosed();
    const on = state.bot.open.length + state.me.open.length;
    const cn = state.bot.closed.length + state.me.closed.length;
    $("#cmp-open-n").textContent = on ? `(${on})` : "";
    $("#cmp-closed-n").textContent = cn ? `(${cn})` : "";
  }

  function renderAll() {
    const sb = renderSide("bot"), sm = renderSide("me");
    renderComparison(sb, sm);
    const note = $("#bot-note");
    if (note) note.textContent = (state.bot.open.length || state.bot.closed.length)
      ? "" : "Autonomous bot is in dry-run — its trades appear here once enabled.";
  }

  // Run async work in small waves so we never burst dozens of quote requests at
  // once (Yahoo throttles bursts, which made the "Now" column fall back to "—").
  async function inBatches(items, size, fn) {
    for (let i = 0; i < items.length; i += size) {
      await Promise.all(items.slice(i, i + size).map(fn));
    }
  }

  // ── live refresh: mark opens to live price, auto-manage Me, update cells ────
  async function refreshLive() {
    let meChanged = false;
    const data = mjLoad();
    const byId = new Map((data.trades || []).map((t) => [t.id, t]));

    // Every open position is rendered in TWO tables (combined overview + its
    // per-section table), so GROUP rows by symbol — fetch each symbol's price
    // once and paint all its rows as soon as it returns (so one slow symbol
    // can't freeze the whole column).
    const trs = $$("tbody tr[data-tid]");
    const keyOf = (t) => marketOf(t) + ":" + String(t.symbol || "").toUpperCase();
    const groups = new Map();            // key -> { src, rows:[{tr,src}], manual }
    for (const tr of trs) {
      const side = tr.getAttribute("data-side");
      const id = tr.getAttribute("data-tid");
      const src = side === "bot" ? state.bot.open.find((t) => t.id === id) : byId.get(id);
      if (!src) continue;
      const key = keyOf(src);
      let g = groups.get(key);
      if (!g) { g = { src, rows: [], manual: null }; groups.set(key, g); }
      g.rows.push({ tr, src });
      if (side === "me" && !g.manual) g.manual = src;
    }

    const paint = (g, price) => {
      if (g.manual && price != null && manage(g.manual, price)) meChanged = true;
      for (const { tr, src } of g.rows) {
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
          if (ru != null && udCell) { const ud = ur * ru; udCell.textContent = d2(ud); udCell.className = "num jr-ud " + pcls(ud); }
        }
      }
    };

    // Fetch each unique symbol once (≤6 in flight), painting as each resolves.
    await inBatches([...groups.values()], 6, async (g) => { paint(g, await priceFor(g.src)); });

    if (meChanged) { mjSave(data); loadMe(data); renderAll(); }
  }

  // ── loaders ───────────────────────────────────────────────────────────────
  function loadMe(data) { state.me = splitMe(data || mjLoad()); }
  async function loadBot() {
    try {
      const r = await fetch("data/vivek_bot_book.json", { cache: "no-cache" });
      if (r.ok) state.bot = splitBot(await r.json());
    } catch (_) { /* keep empty */ }
  }
  // Pull grade + entry trigger per symbol from the live scans (fallback only).
  async function loadScanMeta() {
    const files = ["asx_vivek.json", "nasdaq_vivek.json", "crypto_vivek.json"];
    await Promise.all(files.map(async (f) => {
      try {
        const r = await fetch("data/" + f, { cache: "no-cache" });
        if (!r.ok) return;
        const j = await r.json();
        for (const row of (j.results || [])) {
          const sym = String(row.symbol || "").toUpperCase();
          if (sym && !scanMeta.has(sym)) scanMeta.set(sym, { grade: row.grade || null, entry_type: row.entry_trigger || null });
        }
      } catch (_) { /* skip a missing/blocked file */ }
    }));
  }

  // ── close modal (Me) ──────────────────────────────────────────────────────
  let closeId = null;
  function openCloseModal(id) {
    const t = mjLoad().trades.find((x) => x.id === id);
    if (!t) return;
    closeId = id;
    $("#jr-modal-title").textContent = "Close " + String(t.symbol || "").toUpperCase();
    $("#jr-exit-price").value = "";
    $("#jr-price-tag").textContent = "loading live…";
    $("#jr-close-overlay").hidden = false;
    priceFor(t).then((p) => { if (p != null) { $("#jr-exit-price").value = +(+p).toFixed(6); $("#jr-price-tag").textContent = "live"; } else $("#jr-price-tag").textContent = ""; });
  }
  function closeModal() { $("#jr-close-overlay").hidden = true; closeId = null; }

  // Remove a manual trade entirely (no P&L logged) — for setups you logged but
  // didn't actually take (e.g. a fund/REIT not listed on your broker). Records a
  // tombstone so the deletion propagates across synced devices.
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
    };
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
      } catch (_) { syncStatus("Couldn't reach the sync server — trades are still saved on this device.", "neg"); }
    };
    const syncedAt = () => syncStatus("Synced at " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), "live");
    if (onBtn) onBtn.addEventListener("click", enable);
    if (offBtn) offBtn.addEventListener("click", () => { window.GBSSync.setCode(""); reflect(); syncStatus("Sync off — this device keeps its own copy."); });
    if (nowBtn) nowBtn.addEventListener("click", async () => { syncStatus("Syncing…"); try { await window.GBSSync.syncOut(); afterStoreChange(); syncedAt(); } catch (_) { syncStatus("Sync failed — will retry on the next change.", "neg"); } });
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
      const btn = e.target.closest("[data-close]");
      if (btn) openCloseModal(btn.getAttribute("data-close"));
    });
    $("#jr-modal-x").addEventListener("click", closeModal);
    $("#jr-modal-cancel").addEventListener("click", closeModal);
    $("#jr-modal-save").addEventListener("click", saveClose);
    $("#jr-close-overlay").addEventListener("click", (e) => { if (e.target.id === "jr-close-overlay") closeModal(); });
    // react to manual trades opened on another tab/device
    window.addEventListener("storage", (e) => { if (e.key === MJ_KEY) { loadMe(); renderAll(); refreshLive(); } });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshLive(); });
    setInterval(() => { if (!document.hidden) refreshLive(); }, 20000);
  }

  async function init() {
    loadMe();
    renderAll();                 // paint Me immediately
    await Promise.all([loadBot(), loadScanMeta()]);
    renderAll();                 // repaint with Claude + grade/setup fallback
    wire();
    wireSync();
    refreshLive();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
