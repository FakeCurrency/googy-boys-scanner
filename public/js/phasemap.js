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
    // User-controlled view filter only — the ILLIQUID tag itself can never be
    // disabled (spec guardrail 7). Defaults to showing everything.
    hideIlliquid: (() => {
      try { return localStorage.getItem("pm-hide-illiquid") === "1"; }
      catch (_) { return false; }
    })(),
  };

  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

  function chartURL(rec) {
    // The ORIGINAL chart page — full VIVEK-grade charting (multi-timeframe,
    // SMAs, drawing tools, live price, TradingView link) + the zones overlaid.
    return `chart.html?m=${state.market}&s=${encodeURIComponent(rec.ticker)}&pm=1&dir=${rec.direction}`;
  }

  function cardHTML(rec, idx) {
    const speak = window.speechSynthesis
      ? `<button class="pm-speak" data-speak="${idx}" title="Read aloud" aria-label="Read analysis aloud">▶ READ</button>`
      : "";
    // FLASH cue: the event printed on THIS scan's date — review the chart now
    const m = rec.metrics || {};
    const rd = state.data && state.data.run_date;
    const flashed = rd && (m.displacement_date === rd || m.sweep_date === rd);
    const starred = PM.watch.has("phasemap", state.market, rec.ticker);
    return `<article class="pm-card pm-card-link" data-idx="${idx}" title="Open chart">
      <div class="pm-card-head">
        <span class="pm-ticker">${PM.esc(rec.ticker)}</span>
        ${flashed ? '<span class="pm-tag sp-spike" title="The sweep or displacement printed on the latest scan day — fresh evidence, review the chart">⚡ FLASHED</span>' : ""}
        ${rec._stale ? `<span class="pm-tag pm-tag-stale" title="Starred while a setup was live — it has since left the scan, shown from its last snapshot so you can keep monitoring">NO ACTIVE SETUP · last seen ${PM.esc(rec._staleDate || "")}</span>` : ""}
        ${PM.headBadgesHTML(rec)}
        ${PM.starHTML(starred, rec.ticker)}
        ${speak}
        <span class="pm-chart-cue" aria-hidden="true">CHART →</span>
      </div>
      ${PM.identityHTML(rec)}
      <div class="pm-ladder">${PM.ladderHTML(rec)}</div>
      ${rec.next ? `<div class="pm-next"><span class="pm-next-label">WANTED NEXT</span> ${PM.esc(rec.next)}</div>` : ""}
      <p class="pm-narration">${PM.esc(rec.narration)}</p>
      <div class="pm-metrics">${PM.metricsHTML(rec)}</div>
    </article>`;
  }

  function filtered() {
    const q = state.q.trim().toUpperCase();
    if (state.view === "watchlist") {
      // Starred names: live records where a setup still exists, snapshot
      // placeholders where it doesn't — the watch NEVER silently drops one.
      const wl = PM.watch.map("phasemap", state.market);
      const out = [];
      for (const [ticker, entry] of Object.entries(wl).sort()) {
        if (q && !ticker.toUpperCase().includes(q)) continue;
        const live = state.data.results.filter((r) => r.ticker === ticker);
        if (live.length) {
          out.push(...live);
        } else if (entry.snap) {
          out.push({ ...entry.snap, _stale: true, _staleDate: entry.date });
        } else {
          out.push({ ticker, direction: "bullish", state: "TRAP_SET", tier: null,
                     tags: [], regime: "ROTATION", zones: [], metrics: {},
                     narration: "", next: "", _stale: true, _staleDate: entry.date });
        }
      }
      return out;
    }
    const states = VIEWS[state.view];
    return state.data.results.filter((r) =>
      states.includes(r.state) &&
      (state.tier === "all" || r.tier === state.tier) &&
      (state.dir === "all" || r.direction === state.dir) &&
      (!state.hideIlliquid || !r.tags.includes("ILLIQUID")) &&
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
        if (e.target.closest(".pm-speak") || e.target.closest(".pm-star")) return;
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
    $$(".pm-star", list).forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const ticker = btn.dataset.star;
        const rec = state.data.results.find((r) => r.ticker === ticker) || null;
        PM.watch.toggle("phasemap", state.market, ticker, rec);
        renderCounts();
        render();
      });
    });
  }

  function renderCounts() {
    const counts = { watchlist: PM.watch.count("phasemap", state.market) };
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
    const liqBtn = $("#pm-liq-filter .pm-chip");
    if (liqBtn) {
      liqBtn.classList.toggle("is-active", state.hideIlliquid);
      liqBtn.addEventListener("click", () => {
        state.hideIlliquid = !state.hideIlliquid;
        liqBtn.classList.toggle("is-active", state.hideIlliquid);
        try { localStorage.setItem("pm-hide-illiquid", state.hideIlliquid ? "1" : "0"); } catch (_) {}
        state.shown = PAGE;
        render();
      });
    }
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
      // keep starred snapshots fresh while their setups are still live
      const wl = PM.watch.map("phasemap", state.market);
      for (const ticker of Object.keys(wl)) {
        const live = state.data.results.find((r) => r.ticker === ticker);
        if (live) PM.watch.refresh("phasemap", state.market, ticker, live);
      }
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
