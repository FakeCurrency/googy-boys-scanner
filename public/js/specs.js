/* SPECS tab — volume-spike breakouts from a base (sub-$0.50 names).
   Renders public/data/<market>_spec.json. Cards click through to the chart
   page in spec mode (EMA overlay + entry/stop/target lines). */
(() => {
  "use strict";

  const MARKETS = ["asx", "nasdaq"];
  const GRADE_CLASS = { "A+": "pm-tier-aplus", A: "pm-tier-a", B: "pm-tier-watch" };

  const state = {
    data: null, grade: "all", q: "",
    market: (() => {
      try {
        const m = localStorage.getItem("sp-market");
        return MARKETS.includes(m) ? m : "asx";
      } catch (_) { return "asx"; }
    })(),
  };

  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fp = (x) => {
    if (x == null || !isFinite(x)) return "—";
    return x < 0.1 ? x.toFixed(4) : x < 2 ? x.toFixed(3) : x.toFixed(2);
  };

  function cardHTML(r) {
    const cur = state.data.currency_symbol || "$";
    const chips = (r.chips || []).map((c) => `<span class="pm-tag">${esc(c)}</span>`).join("");
    return `<article class="pm-card pm-card-link" data-sym="${esc(r.symbol)}" title="Open chart">
      <div class="pm-card-head">
        <span class="pm-ticker">${esc(r.symbol)}</span>
        <span class="pm-tier ${GRADE_CLASS[r.grade] || ""}">${esc(r.grade)}</span>
        <span class="pm-regime">${r.score}/${r.score_max}</span>
        <span class="pm-tag sp-spike">⚡ ${r.spike_ratio}× VOL</span>
        <span class="pm-tag">${r.off_high_pct}% OFF HIGH</span>
        ${r.low_rr ? '<span class="pm-tag pm-tag-illiquid">LOW R:R</span>' : ""}
        <span class="pm-chart-cue" aria-hidden="true">CHART →</span>
      </div>
      <div class="pm-identity">${esc(r.name)}${r.sector ? ` · <span class="pm-sector">${esc(r.sector)}</span>` : ""}</div>
      <div class="pm-metrics sp-levels">
        <span>price <b>${cur}${fp(r.price)}</b></span>
        <span>entry <b>${cur}${fp(r.entry)}</b></span>
        <span>stop <b class="sp-stop">${cur}${fp(r.stop)}</b></span>
        <span>target <b class="sp-target">${cur}${fp(r.target)}</b></span>
        <span>R:R <b>${r.rr != null ? r.rr.toFixed(1) : "—"}</b></span>
      </div>
      <div class="pm-card-head">${chips}</div>
      <p class="pm-narration">${esc(r.analysis || "")}</p>
    </article>`;
  }

  function render() {
    const list = $("#sp-list");
    if (!state.data) { list.innerHTML = ""; return; }
    const q = state.q.trim().toUpperCase();
    const rows = state.data.results.filter((r) =>
      (state.grade === "all" || r.grade === state.grade) &&
      (!q || r.symbol.toUpperCase().includes(q)));
    list.innerHTML = rows.length
      ? rows.map(cardHTML).join("")
      : `<div class="pm-empty">No spec setups in this view — the gates are strict (3× volume spike + base + breakout, all mandatory).</div>`;
    $$(".pm-card-link", list).forEach((card) => {
      card.addEventListener("click", () => {
        window.location.href =
          `chart.html?m=${state.market}&s=${encodeURIComponent(card.dataset.sym)}&mode=spec`;
      });
    });
  }

  function syncMarketButtons() {
    $$("#sp-market .market-btn").forEach((b) => {
      const on = b.dataset.market === state.market;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-selected", String(on));
    });
  }

  async function load() {
    $("#sp-sub").textContent = "Loading latest scan…";
    try {
      const res = await fetch(`data/${state.market}_spec.json`, { cache: "no-cache" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      state.data = await res.json();
      $("#sp-sub").textContent =
        `${state.market.toUpperCase()} · ${state.data.generated_at.slice(0, 16).replace("T", " ")} · ` +
        `${state.data.universe_size} names scanned · ${state.data.results.length} spec setups`;
    } catch (err) {
      state.data = null;
      $("#sp-sub").textContent = `No ${state.market.toUpperCase()} specs scan yet (${err.message})`;
      $("#sp-list").innerHTML =
        `<div class="pm-empty">Run: python -m scanner.spec_run --market ${esc(state.market)}</div>`;
      return;
    }
    render();
  }

  $$("#sp-market .market-btn").forEach((btn) => btn.addEventListener("click", () => {
    if (btn.dataset.market === state.market) return;
    state.market = btn.dataset.market;
    try { localStorage.setItem("sp-market", state.market); } catch (_) {}
    syncMarketButtons();
    load();
  }));
  $$("#sp-grade-filter .pm-chip").forEach((chip) => chip.addEventListener("click", () => {
    $$("#sp-grade-filter .pm-chip").forEach((c) => c.classList.toggle("is-active", c === chip));
    state.grade = chip.dataset.grade;
    render();
  }));
  $("#sp-search").addEventListener("input", (e) => { state.q = e.target.value; render(); });

  syncMarketButtons();
  load();
})();
