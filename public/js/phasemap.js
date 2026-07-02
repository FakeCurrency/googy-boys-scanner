/* PHASEMAP tab — renders public/data/phasemap/<market>/latest.json.
   Read-only view of the nightly scan snapshot; no live queries.
   Cards click through to phasemap-chart.html with every zone on the chart. */
(() => {
  "use strict";

  const VIEWS = {
    setups:   ["RUNNING", "DISPLACED"],
    watch:    ["TRAP_SET", "SWEPT"],
    rotation: ["STALLED"],
    ended:    ["COMPLETE", "DEAD"],
    all:      ["TRAP_SET", "SWEPT", "DISPLACED", "RUNNING", "STALLED", "COMPLETE", "DEAD"],
  };
  const PAGE = 60;
  const MARKETS = ["asx", "nasdaq", "crypto"];

  const state = {
    data: null, view: "setups", tier: "all", dir: "all", q: "", shown: PAGE,
    market: (() => {
      try {
        const m = localStorage.getItem("pm-market");
        return MARKETS.includes(m) ? m : "asx";
      } catch (_) { return "asx"; }
    })(),
  };

  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

  function chartURL(rec) {
    return `phasemap-chart.html?m=${state.market}&t=${encodeURIComponent(rec.ticker)}&d=${rec.direction}`;
  }

  function cardHTML(rec, idx) {
    const speak = window.speechSynthesis
      ? `<button class="pm-speak" data-speak="${idx}" title="Read aloud" aria-label="Read analysis aloud">▶ READ</button>`
      : "";
    return `<article class="pm-card pm-card-link" data-idx="${idx}" title="Open chart">
      <div class="pm-card-head">
        <span class="pm-ticker">${PM.esc(rec.ticker)}</span>
        ${PM.headBadgesHTML(rec)}
        ${speak}
        <span class="pm-chart-cue" aria-hidden="true">CHART →</span>
      </div>
      <div class="pm-ladder">${PM.ladderHTML(rec)}</div>
      <p class="pm-narration">${PM.esc(rec.narration)}</p>
      <div class="pm-metrics">${PM.metricsHTML(rec)}</div>
    </article>`;
  }

  function filtered() {
    const states = VIEWS[state.view];
    const q = state.q.trim().toUpperCase();
    return state.data.results.filter((r) =>
      states.includes(r.state) &&
      (state.tier === "all" || r.tier === state.tier) &&
      (state.dir === "all" || r.direction === state.dir) &&
      (!q || r.ticker.toUpperCase().includes(q)));
  }

  function render() {
    const list = $("#pm-list");
    if (!state.data) { list.innerHTML = ""; return; }
    const rows = filtered();
    const shown = rows.slice(0, state.shown);
    list.innerHTML = shown.length
      ? shown.map(cardHTML).join("")
      : `<div class="pm-empty">Nothing matches this view right now.</div>`;
    $("#pm-more").hidden = rows.length <= state.shown;

    $$(".pm-card-link", list).forEach((card) => {
      card.addEventListener("click", (e) => {
        if (e.target.closest(".pm-speak")) return;    // READ button, not a nav
        const rec = shown[+card.dataset.idx];
        if (rec) window.location.href = chartURL(rec);
      });
    });
    $$(".pm-speak", list).forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const rec = shown[+btn.dataset.speak];
        if (rec) PM.toggleSpeak(btn, rec.narration);
      });
    });
  }

  function renderCounts() {
    const counts = {};
    for (const [view, states] of Object.entries(VIEWS)) {
      counts[view] = state.data
        ? state.data.results.filter((r) => states.includes(r.state)).length : 0;
    }
    $$("[data-count]").forEach((el) => { el.textContent = counts[el.dataset.count] ?? 0; });
  }

  function wire() {
    $$("#pm-market .market-btn").forEach((btn) => btn.addEventListener("click", () => {
      if (btn.dataset.market === state.market) return;
      state.market = btn.dataset.market;
      try { localStorage.setItem("pm-market", state.market); } catch (_) {}
      syncMarketButtons();
      state.shown = PAGE;
      load();
    }));
    $$("#pm-tabs .pm-tab").forEach((tab) => tab.addEventListener("click", () => {
      $$("#pm-tabs .pm-tab").forEach((t) => {
        t.classList.toggle("is-active", t === tab);
        t.setAttribute("aria-selected", String(t === tab));
      });
      state.view = tab.dataset.view;
      state.shown = PAGE;
      render();
    }));
    const chipGroup = (rootSel, key, dataKey) =>
      $$(rootSel + " .pm-chip").forEach((chip) => chip.addEventListener("click", () => {
        $$(rootSel + " .pm-chip").forEach((c) => c.classList.toggle("is-active", c === chip));
        state[key] = chip.dataset[dataKey];
        state.shown = PAGE;
        render();
      }));
    chipGroup("#pm-tier-filter", "tier", "tier");
    chipGroup("#pm-dir-filter", "dir", "dir");
    $("#pm-search").addEventListener("input", (e) => {
      state.q = e.target.value;
      state.shown = PAGE;
      render();
    });
    $("#pm-more").addEventListener("click", () => { state.shown += PAGE; render(); });
  }

  function syncMarketButtons() {
    $$("#pm-market .market-btn").forEach((b) => {
      const on = b.dataset.market === state.market;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-selected", String(on));
    });
  }

  async function load() {
    $("#pm-sub").textContent = "Loading latest scan…";
    try {
      const res = await fetch(`data/phasemap/${state.market}/latest.json`, { cache: "no-cache" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      state.data = await res.json();
      $("#pm-sub").textContent =
        `${state.market.toUpperCase()} · scan ${state.data.run_date} · ruleset v${state.data.ruleset_version} · ` +
        `${state.data.universe_size} tickers scanned · ${state.data.results.length} results`;
    } catch (err) {
      state.data = null;
      $("#pm-sub").textContent =
        `No ${state.market.toUpperCase()} PhaseMap scan yet (${err.message})`;
      $("#pm-list").innerHTML = `<div class="pm-empty">Run: python -m phasemap.run --market ${PM.esc(state.market)}</div>`;
      renderCounts();
      $("#pm-more").hidden = true;
      return;
    }
    renderCounts();
    render();
  }

  syncMarketButtons();
  wire();
  load();
})();
