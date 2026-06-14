/* =========================================================================
   Googy Boys Scanner — frontend logic
   Renders the PULSE bar, stat cards, and the dense results table from
   data/<market>.json. Handles market toggle, Results/Watch views, grade
   sub-tabs, sorting, and a localStorage watchlist (stars).
   ========================================================================= */
(() => {
  "use strict";

  const COLOR = { green: "#2fd07f", blue: "#4d9fff", red: "#ff5b5b" };
  const EMA_COLOR = {
    8: "#ff5c8a", 13: "#ff9f43", 21: "#ffd23f", 34: "#2fd07f",
    55: "#2fd0c4", 89: "#4d9fff", 144: "#a78bfa",
  };
  const GRADE_VAR = { "A+": "var(--grade-aplus)", "A": "var(--grade-a)", "B": "var(--grade-b)", "C": "var(--grade-c)" };
  const GRADE_RANK = { "A+": 0, "A": 1, "B": 2, "C": 3 };
  const WATCH_KEY = "gbs:watch";

  const state = {
    market: "asx",
    view: "results",   // results | watch
    tab: "aplus",      // aplus | a | watch
    sort: "score",     // score | price | rr | az
    data: null,
    cache: {},
    cur: "$",
  };

  const $ = (s) => document.querySelector(s);

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
  function fmtPrice(v) {
    if (v == null || isNaN(v)) return "—";
    const dp = Math.abs(v) >= 100 ? 2 : Math.abs(v) >= 1 ? 3 : 4;
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

  function fmtTime(iso, tz) {
    try {
      const d = new Date(iso);
      const date = d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
      const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
      return `${date}, ${time} ${tz || ""}`.trim();
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
      const val = p.value.toLocaleString(undefined, { minimumFractionDigits: p.decimals, maximumFractionDigits: p.decimals });
      const dir = p.dir === "up" ? "up" : "down";
      const day = (p.day_pct >= 0 ? "+" : "") + p.day_pct.toFixed(2) + "%";
      const d5 = "5D " + (p.d5_pct >= 0 ? "+" : "") + p.d5_pct.toFixed(2) + "%";
      return `<div class="pulse-item">
        <div class="pi-head"><span class="pi-key">${p.key}</span><span class="pi-val">${val}</span></div>
        <div class="pi-change ${dir}">${day}<span class="pi-5d">${d5}</span></div>
        ${spark(p.spark, 120, 22, p.dir === "up" ? COLOR.green : COLOR.red, "pi-spark")}
      </div>`;
    }).join("");
  }

  // ----------------------------------------------------------- EMA legend
  function renderLegend(periods) {
    $("#ema-legend").innerHTML = (periods || []).map((p) =>
      `<span class="ema-dot"><i style="background:${EMA_COLOR[p] || "#888"}"></i>${p}</span>`).join("");
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
    $("#count-watch").textContent = res.filter((r) => r.grade === "B" || r.grade === "C").length;
    $("#watch-count").textContent = res.filter((r) => isStarred(r.symbol)).length;
  }

  // ----------------------------------------------------------- a row
  function rowHtml(r) {
    const chips = (r.chips || []).map((c) =>
      `<span class="chip${c.startsWith("WEEKLY") ? " weekly" : ""}">${c}</span>`).join("");
    const lowrr = r.low_rr ? `<span class="chip warn">LOW R:R (${r.rr_text})</span>` : "";
    const t2r = r.target_2r ? `<span class="chip info">TARGET = 2R FALLBACK</span>` : "";
    const sector = r.sector ? `<span class="badge sector">${r.sector}</span>` : "";
    const seccount = (r.sector && r.sector_count > 1)
      ? `<span class="badge seccount">${r.sector.toUpperCase()} ×${r.sector_count}</span>` : "";
    const liqCls = r.liquidity === "LIQUID" ? "liq-liquid" : "liq-ok";
    const p2 = r.p2_pct == null ? "—" : `${r.p2_pct}%`;
    const rrStar = r.target_2r ? "*" : "";
    const rrCls = r.low_rr ? "red" : "green";
    const starred = isStarred(r.symbol);

    return `<div class="row" style="--grade-color:${GRADE_VAR[r.grade] || "var(--grade-c)"}">
      <div class="row-grade">${r.grade}</div>
      <div class="row-main">
        <div class="row-line1">
          <span class="tkr">${r.symbol}</span>
          <span class="badge dir">${r.dir}</span>
          <span class="cname">${r.name || ""}</span>
          ${sector}
          <span class="rprice">${fmtPrice(r.price)}</span>
          <span class="badge ${liqCls}">${r.liquidity}</span>
          ${seccount}
        </div>
        <div class="row-chips">${chips}${lowrr}${t2r}</div>
      </div>
      <div class="row-spark">
        ${spark(r.spark, 120, 30, COLOR[r.trend] || COLOR.blue)}
        <div class="trend-bar ${r.trend}"></div>
      </div>
      <div class="row-prices">
        <div class="pcell"><div class="pcell-label">Y Close</div><div class="pcell-val">${fmtPrice(r.y_close)}</div></div>
        <div class="pcell"><div class="pcell-label">Open</div><div class="pcell-val">${fmtPrice(r.open)} <span class="pcell-pct ${pctCls(r.open_pct)}">${fmtPct(r.open_pct)}</span></div></div>
        <div class="pcell"><div class="pcell-label">Current</div><div class="pcell-val">${fmtPrice(r.price)} <span class="pcell-pct ${pctCls(r.current_pct)}">${fmtPct(r.current_pct)}</span></div></div>
        <div class="pcell"><div class="pcell-label">Day</div><div class="pcell-val ${pctCls(r.day_pct)}">${fmtPct(r.day_pct)}</div></div>
      </div>
      <div class="row-trade">
        <span class="t-badge">T1</span>
        <div class="t-metric"><span class="tm-label">Stop</span><span class="tm-val red">${r.stop_pct}%</span></div>
        <div class="t-metric"><span class="tm-label">P2</span><span class="tm-val amber">${p2}</span></div>
        <div class="t-metric"><span class="tm-label">R:R</span><span class="tm-val ${rrCls}">${r.rr.toFixed(2)}${rrStar}</span></div>
        <span class="t-score">${r.score}/${r.score_max}</span>
        <button class="t-star ${starred ? "starred" : ""}" data-sym="${r.symbol}" title="Watchlist" aria-label="Toggle watchlist">
          <svg viewBox="0 0 24 24" width="17" height="17" fill="${starred ? "currentColor" : "none"}" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
        </button>
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
      list = all.filter((r) => r.grade === "B" || r.grade === "C");
    }
    const s = state.sort;
    list = list.slice();
    if (s === "price") list.sort((a, b) => b.price - a.price);
    else if (s === "rr") list.sort((a, b) => b.rr - a.rr);
    else if (s === "az") list.sort((a, b) => a.symbol.localeCompare(b.symbol));
    else list.sort((a, b) => (GRADE_RANK[a.grade] - GRADE_RANK[b.grade]) || (b.score - a.score) || (b.rr - a.rr));
    return list;
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
    wrap.querySelectorAll(".t-star").forEach((btn) => {
      btn.addEventListener("click", () => {
        toggleStar(btn.dataset.sym);
        renderStats(state.data);
        renderRows();
      });
    });
  }

  // ----------------------------------------------------------- apply
  function applyPayload(d) {
    state.data = d;
    state.cur = d.currency_symbol || "$";
    $("#scan-title").textContent = `Last scanned: ${fmtTime(d.generated_at, d.tz_label)}`;
    $("#scan-sub").textContent = `${d.label} · ${d.universe_size ?? d.scanned} in universe · ${d.results.length} setups · updates after each market close`;
    renderPulse(d.pulse);
    renderLegend(d.ema_periods);
    renderStats(d);
    renderRows();
  }

  function skeleton() {
    $("#results").innerHTML = Array.from({ length: 6 }, () => `<div class="skeleton"></div>`).join("");
  }

  async function loadMarket(market) {
    state.market = market;
    $("#scan-title").textContent = "Loading latest scan…";
    skeleton();
    if (state.cache[market]) { applyPayload(state.cache[market]); return; }
    try {
      const res = await fetch(`data/${market}.json`, { cache: "no-cache" });
      if (!res.ok) throw new Error(res.status);
      const d = await res.json();
      state.cache[market] = d;
      applyPayload(d);
    } catch (e) {
      $("#scan-title").textContent = "No scan data yet";
      $("#results").innerHTML = `<div class="placeholder"><h3>No data for ${market.toUpperCase()}</h3>
        <p>Run the scanner to generate <code>data/${market}.json</code>, then refresh.</p></div>`;
    }
  }

  // ----------------------------------------------------------- events
  function bind() {
    document.querySelectorAll(".market-btn").forEach((b) => b.addEventListener("click", () => {
      if (b.classList.contains("is-active")) return;
      document.querySelectorAll(".market-btn").forEach((x) => {
        x.classList.toggle("is-active", x === b);
        x.setAttribute("aria-selected", x === b ? "true" : "false");
      });
      loadMarket(b.dataset.market);
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
      if (state.view !== "results") {
        state.view = "results";
        document.querySelectorAll(".view-tab").forEach((x) => x.classList.toggle("is-active", x.dataset.view === "results"));
      }
      document.querySelectorAll("#tabs .seg-btn").forEach((x) => x.classList.toggle("is-active", x === b));
      renderRows();
    }));

    document.querySelectorAll("#sorts .seg-btn").forEach((b) => b.addEventListener("click", () => {
      state.sort = b.dataset.sort;
      document.querySelectorAll("#sorts .seg-btn").forEach((x) => x.classList.toggle("is-active", x === b));
      renderRows();
    }));
  }

  bind();
  loadMarket(state.market);
})();
