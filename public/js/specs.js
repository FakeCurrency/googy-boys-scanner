/* SPECS tab — volume-spike breakouts from a base (sub-$0.50 names).
   Dense dashboard-style rows (grade block · ticker · identity · spike ·
   price · score) that expand for the full plan + analysis. Stars persist
   a snapshot, so watchlisted names survive losing the setup. */
(() => {
  "use strict";

  const MARKETS = ["asx", "nasdaq"];
  const GRADE_COLOR = { "A+": "var(--grade-aplus)", A: "var(--grade-a)", B: "var(--grade-b)" };

  const state = {
    data: null, grade: "all", q: "", view: "results", sort: "default",
    market: (() => {
      try {
        const m = localStorage.getItem("sp-market");
        return MARKETS.includes(m) ? m : "asx";
      } catch (_) { return "asx"; }
    })(),
  };

  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
  const fp = (x) => {
    if (x == null || !isFinite(x)) return "—";
    return x < 0.1 ? x.toFixed(4) : x < 2 ? x.toFixed(3) : x.toFixed(2);
  };

  function rowHTML(r, idx) {
    const cur = (state.data && state.data.currency_symbol) || "A$";
    const starred = PM.watch.has("specs", state.market, r.symbol);
    const ci = state.confl ? state.confl.of(r.symbol) : null;
    const aligned = ci && ci.side === "long";   // specs are long-only
    const gc = GRADE_COLOR[r.grade] || "var(--grade-c)";
    const chips = (r.chips || []).map((c) => `<span class="pm-tag">${PM.esc(c)}</span>`).join("");
    const fund = PM.isFundReit({ name: r.name, sector: r.sector, ticker: r.symbol })
      ? '<span class="pm-tag pm-tag-fund">FUND / REIT</span>' : "";
    return `<article class="sp-row" data-idx="${idx}">
      <div class="sp-row-main" role="button" tabindex="0" title="Expand">
        <span class="sp-grade" style="background:${gc}22;border-left-color:${gc};color:${gc}">${PM.esc(r.grade)}</span>
        <span class="pm-ticker">${PM.esc(r.symbol)}</span>
        <span class="pm-dir pm-dir-long">LONG</span>
        <span class="sp-name">${PM.esc(r.name)}${r.sector ? ` <span class="pm-sector">${PM.esc(r.sector)}</span>` : ""} ${fund}</span>
        ${aligned ? PM.confluenceChipHTML(ci, "SPECS") : ""}
        ${r._stale ? `<span class="pm-tag pm-tag-stale">NO ACTIVE SETUP · last seen ${PM.esc(r._staleDate || "")}</span>` : `<span class="pm-tag sp-spike">⚡ ${r.spike_ratio}×</span>`}
        <span class="sp-row-price">${cur}${fp(r.price)}</span>
        <span class="sp-row-score">${r.score}/${r.score_max}<b>${r.rr != null ? " · " + r.rr.toFixed(1) + "R" : ""}</b></span>
        ${PM.starHTML(starred, r.symbol)}
        <span class="sp-chev" aria-hidden="true">▾</span>
      </div>
      <div class="sp-row-detail" hidden>
        <div class="pm-metrics sp-levels">
          <span>entry <b>${cur}${fp(r.entry)}</b></span>
          <span>stop <b class="sp-stop">${cur}${fp(r.stop)}</b></span>
          <span>target <b class="sp-target">${cur}${fp(r.target)}</b></span>
          <span>R:R <b>${r.rr != null ? r.rr.toFixed(1) : "—"}</b></span>
          <span>off high <b>${r.off_high_pct != null ? r.off_high_pct + "%" : "—"}</b></span>
          ${r.low_rr ? '<span class="pm-metric-warn"><b>LOW R:R</b></span>' : ""}
        </div>
        <div class="sp-detail-chips">${chips}</div>
        <p class="pm-narration">${PM.esc(r.analysis || "No saved analysis — this snapshot predates the current scan.")}</p>
        <a class="pm-chart-cue sp-chart-link" href="chart.html?m=${state.market}&s=${encodeURIComponent(r.symbol)}&mode=spec&src=specs&flt=${encodeURIComponent(state.grade + '~' + state.sort)}">OPEN CHART →</a>
      </div>
    </article>`;
  }

  function visibleRows() {
    const q = state.q.trim().toUpperCase();
    if (state.view === "watchlist") {
      const wl = PM.watch.map("specs", state.market);
      const out = [];
      for (const [sym, entry] of Object.entries(wl).sort()) {
        if (q && !sym.toUpperCase().includes(q)) continue;
        const live = state.data && state.data.results.find((r) => r.symbol === sym);
        if (live) out.push(live);
        else if (entry.snap) out.push({ ...entry.snap, _stale: true, _staleDate: entry.date });
        else out.push({ symbol: sym, name: sym, sector: "", grade: "B", score: 0,
                        score_max: 11, chips: [], price: null, entry: null, stop: null,
                        target: null, rr: null, analysis: "",
                        _stale: true, _staleDate: entry.date });
      }
      return out;
    }
    if (!state.data) return [];
    const rows = state.data.results.filter((r) =>
      (state.grade === "all" || r.grade === state.grade) &&
      (!q || r.symbol.toUpperCase().includes(q)));
    const bynum = (fn, asc) => (a, b) => (asc ? 1 : -1) *
      ((fn(a) ?? (asc ? Infinity : -Infinity)) - (fn(b) ?? (asc ? Infinity : -Infinity)))
      || a.symbol.localeCompare(b.symbol);
    if (state.sort === "spike") return [...rows].sort(bynum((r) => r.spike_ratio));
    if (state.sort === "rr") return [...rows].sort(bynum((r) => r.rr));
    if (state.sort === "price") return [...rows].sort(bynum((r) => r.price, true));
    return rows;   // default: grade / score / R:R order from the scan file
  }

  function render() {
    const list = $("#sp-list");
    const rows = visibleRows();
    list.innerHTML = rows.length
      ? rows.map(rowHTML).join("")
      : `<div class="pm-empty">${state.view === "watchlist"
          ? "Nothing starred yet — hit ☆ on any row and it stays here even after the setup ends."
          : "No spec setups in this view — the gates are strict (3× volume spike + base + breakout, all mandatory)."}</div>`;

    $$(".sp-row", list).forEach((row) => {
      const main = $(".sp-row-main", row);
      const detail = $(".sp-row-detail", row);
      const openIt = (e) => {
        if (e.target.closest(".pm-star") || e.target.closest(".sp-chart-link")) return;
        detail.hidden = !detail.hidden;
        row.classList.toggle("is-open", !detail.hidden);
      };
      main.addEventListener("click", openIt);
      main.addEventListener("keydown", (e) => { if (e.key === "Enter") openIt(e); });
    });
    $$(".pm-star", list).forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const sym = btn.dataset.star;
        const rec = (state.data && state.data.results.find((r) => r.symbol === sym)) || null;
        PM.watch.toggle("specs", state.market, sym, rec);
        renderCounts();
        render();
      });
    });
    renderCounts();
  }

  function renderConfBanner() {
    let el = document.getElementById("conf-banner");
    const rows = state.confl ? state.confl.all() : [];
    if (!rows.length) { if (el) el.remove(); return; }
    if (!el) {
      el = document.createElement("section");
      el.id = "conf-banner";
      el.className = "conf-banner";
      const anchor = document.querySelector("#sp-tabs");
      if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(el, anchor);
      else return;
    }
    el.innerHTML = PM.confluenceBannerHTML(rows, state.market);
  }

  function renderCounts() {
    $("#sp-count-results").textContent = state.data ? state.data.results.length : 0;
    $("#sp-count-watchlist").textContent = PM.watch.count("specs", state.market);
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
      $("#sp-sub").innerHTML = PM.esc(
        `${state.market.toUpperCase()} · ${PM.fmtMelb(state.data.generated_at)} · ` +
        `${state.data.universe_size} names scanned · ${state.data.results.length} spec setups`)
        + PM.staleBadgeHTML(state.data.generated_at);
      const wl = PM.watch.map("specs", state.market);
      for (const sym of Object.keys(wl)) {
        const live = state.data.results.find((r) => r.symbol === sym);
        if (live) PM.watch.refresh("specs", state.market, sym, live);
      }
      state.confl = null;
      renderConfBanner();
      PM.loadConfluence(state.market).then((c) => {
        state.confl = c;
        render();
        renderConfBanner();
      });
    } catch (err) {
      state.data = null;
      $("#sp-sub").textContent = `No ${state.market.toUpperCase()} specs scan yet (${err.message})`;
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
  $$("#sp-tabs .pm-tab").forEach((tab) => tab.addEventListener("click", () => {
    $$("#sp-tabs .pm-tab").forEach((t) => {
      t.classList.toggle("is-active", t === tab);
      t.setAttribute("aria-selected", String(t === tab));
    });
    state.view = tab.dataset.view;
    render();
  }));
  $$("#sp-grade-filter .pm-chip").forEach((chip) => chip.addEventListener("click", () => {
    $$("#sp-grade-filter .pm-chip").forEach((c) => c.classList.toggle("is-active", c === chip));
    state.grade = chip.dataset.grade;
    render();
  }));
  $$("#sp-sort-filter .pm-chip").forEach((chip) => chip.addEventListener("click", () => {
    $$("#sp-sort-filter .pm-chip").forEach((c) => c.classList.toggle("is-active", c === chip));
    state.sort = chip.dataset.sort;
    render();
  }));
  $("#sp-search").addEventListener("input", (e) => { state.q = e.target.value; render(); });

  syncMarketButtons();
  load();
  // pull remote stars (unified watchlist) so phone/desktop agree
  if (window.GBSSync && GBSSync.enabled()) {
    GBSSync.syncIn().then(() => render()).catch(() => {});
  }
})();
