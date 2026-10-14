/* SPECS tab — volume-spike breakouts from a base (sub-$0.50 names).
   Deck layout (backlog #19-20, owner 2026-07-22): the page now uses the SAME
   command-bar + pill + row-card language as the SCAN dashboard — grade rail
   rows that expand, filter pills with live counts (Multi-lens is a
   click-to-filter, like SCAN), seg toolbar for grade/sort. Logic unchanged.
   (Stars and the watchlist view were removed 2026-09-21.) */
(() => {
  "use strict";

  const MARKETS = ["asx", "nasdaq"];
  const GRADE_VAR = { "A+": "var(--grade-aplus)", A: "var(--grade-a)", B: "var(--grade-b)" };

  const state = {
    data: null, grade: "all", q: "", sort: "default",
    confOnly: false,   // deck pill: only rows with 2+ lens alignment
    confl: null,
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
  const alignedOf = (r) => {
    const ci = state.confl ? state.confl.of(r.symbol) : null;
    return ci && ci.side === "long" ? ci : null;   // specs are long-only
  };

  function rowHTML(r, idx) {
    const cur = (state.data && state.data.currency_symbol) || "A$";
    const ci = alignedOf(r);
    const gc = GRADE_VAR[r.grade] || "var(--grade-c)";
    const fund = PM.isFundReit({ name: r.name, sector: r.sector, ticker: r.symbol });
    const chartHref = `chart.html?m=${state.market}&s=${encodeURIComponent(r.symbol)}&mode=spec&src=specs&flt=${encodeURIComponent(state.grade + "~" + state.sort)}`;
    const chips = [
      fund ? `<span class="rbadge fundwarn" title="REIT / ETF / LIC / managed fund">⚠ FUND / REIT</span>` : "",
      ci ? PM.confluenceChipHTML(ci, "SPECS") : "",
      `<span class="rbadge wk" title="Volume vs 20-day average on the breakout">⚡ ${PM.esc(String(r.spike_ratio))}× volume</span>`,
      r.low_rr ? `<span class="chip warn">LOW R:R</span>` : "",
    ].filter(Boolean);
    const detailChips = (r.chips || []).map((c) => `<span class="chip">${PM.esc(c)}</span>`).join("");
    return `<div class="row-wrap sp-row" data-idx="${idx}" style="--grade-color:${gc};--row-i:${Math.min(idx, 12)}">
      <div class="row">
        <div class="row-grade">${PM.esc(r.grade)}</div>
        <div class="row-main">
          <div class="row-line1">
            <a class="tkr" href="${chartHref}" title="Open chart">${PM.esc(r.symbol)}</a>
            <span class="badge dir long">LONG</span>
            ${r.sector ? `<span class="badge sector" title="${PM.esc(r.sector)}">${PM.esc(r.sector)}</span>` : ""}
            <span class="cname">${PM.esc(r.name)}</span>
            <span class="rprice">${cur}${fp(r.price)}</span>
          </div>
          <div class="row-chips">${chips.join("")}</div>
        </div>
        <div class="row-right">
          <div class="row-kpis">
            <span class="rk-score">${r.score}<span class="rk-max">/${r.score_max}</span></span>
            <span class="rk-rr ${r.low_rr ? "low" : ""}">${r.rr != null ? r.rr.toFixed(1) + "R" : "—"}</span>
          </div>
          <button class="row-expand" title="Details" aria-label="Toggle details" aria-expanded="false">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="6 9 12 15 18 9"/></svg>
          </button>
        </div>
      </div>
      <div class="detail-anim">
        <div class="detail-inner">
          <div class="row-detail sp-detail">
            <div class="detail-prices">
              <div class="dp-cell"><span class="dp-lbl">Entry</span><span class="dp-val">${cur}${fp(r.entry)}</span></div>
              <div class="dp-cell"><span class="dp-lbl">Stop</span><span class="dp-val pct-down">${cur}${fp(r.stop)}</span></div>
              <div class="dp-cell"><span class="dp-lbl">Target</span><span class="dp-val pct-up">${cur}${fp(r.target)}</span></div>
              <div class="dp-cell"><span class="dp-lbl">Off high</span><span class="dp-val">${r.off_high_pct != null ? r.off_high_pct + "%" : "—"}</span></div>
            </div>
            ${detailChips ? `<div class="detail-chips">${detailChips}</div>` : ""}
            ${r.analysis ? `<div class="rd-analysis"><p>${PM.esc(r.analysis)}</p></div>` : ""}
            <a class="vk-chart-btn sp-chart-link" href="${chartHref}">View chart →</a>
          </div>
        </div>
      </div>
    </div>`;
  }

  function visibleRows() {
    const q = state.q.trim().toUpperCase();
    if (!state.data) return [];
    let rows = state.data.results.filter((r) =>
      (state.grade === "all" || r.grade === state.grade) &&
      (!q || r.symbol.toUpperCase().includes(q)));
    if (state.confOnly) rows = rows.filter((r) => alignedOf(r));
    const bynum = (fn, asc) => (a, b) => (asc ? 1 : -1) *
      ((fn(a) ?? (asc ? Infinity : -Infinity)) - (fn(b) ?? (asc ? Infinity : -Infinity)))
      || a.symbol.localeCompare(b.symbol);
    if (state.sort === "spike") return [...rows].sort(bynum((r) => r.spike_ratio));
    if (state.sort === "rr") return [...rows].sort(bynum((r) => r.rr));
    if (state.sort === "price") return [...rows].sort(bynum((r) => r.price, true));
    return rows;   // default: grade / score / R:R order from the scan file
  }

  // Deck pills (backlog #19): grade counts as tab shortcuts, Multi-lens as a
  // click-to-filter toggle — the SCAN page pattern, replacing the old banner.
  function renderPills() {
    const box = $("#sp-pills");
    if (!box) return;
    const res = (state.data && state.data.results) || [];
    const n = (g) => res.filter((r) => r.grade === g).length;
    const nConf = state.confl ? res.filter((r) => alignedOf(r)).length : null;
    const pill = (attrs, cls, label, count, title, active) =>
      `<button class="fpill ${cls}${active ? " is-active" : ""}" ${attrs} aria-pressed="${active ? "true" : "false"}" title="${PM.esc(title)}">` +
      `${label}${count == null ? "" : ` <b>${count}</b>`}</button>`;
    box.innerHTML =
      pill(`data-g="A+"`, "g", "A+", n("A+"), "Filter to A+ specs", state.grade === "A+") +
      pill(`data-g="A"`, "", "A", n("A"), "Filter to A specs", state.grade === "A") +
      pill(`data-g="B"`, "", "B", n("B"), "Filter to B specs", state.grade === "B") +
      pill(`data-pill="confl"`, "o", "⨂ Multi-lens", nConf ?? "…",
        "Specs that another lens agrees with right now — click to filter", state.confOnly);
    box.querySelectorAll("[data-g]").forEach((b) => b.addEventListener("click", () => {
      state.grade = state.grade === b.dataset.g ? "all" : b.dataset.g;
      $$("#sp-grade-filter .seg-btn").forEach((c) => c.classList.toggle("is-active", c.dataset.grade === state.grade));
      renderPills(); render();
    }));
    box.querySelectorAll("[data-pill]").forEach((b) => b.addEventListener("click", () => {
      state.confOnly = !state.confOnly;
      renderPills(); render();
    }));
  }

  function render() {
    const list = $("#sp-list");
    // No scan loaded (a failed load): #sp-sub already says why and offers a
    // retry, so do not ALSO claim "no setups / the gates are strict".
    if (!state.data) {
      list.innerHTML = "";
      return;
    }
    const rows = visibleRows();
    list.innerHTML = rows.length
      ? rows.map(rowHTML).join("")
      : `<div class="placeholder"><h3>No spec setups in this view</h3>
         <p>${state.confOnly
          ? "No multi-lens agreement among these specs right now — tap the pill to widen."
          : "The gates are strict (3× volume spike + base + breakout, all mandatory)."}</p></div>`;

    $$(".row-wrap", list).forEach((row) => {
      row.querySelector(".row").addEventListener("click", (e) => {
        if (e.target.closest("a.tkr")) return;
        const open = row.classList.toggle("open");
        const btn = row.querySelector(".row-expand");
        if (btn) btn.setAttribute("aria-expanded", String(open));
      });
    });
  }

  // ── Specs → VIVEK graduates (owner-ruled, 2026-07-31) ────────────────────
  // Report-only evidence strip: names this lens surfaced FIRST that later
  // appeared in the published VIVEK scan — the discovery lens feeding the
  // core lens, counted. Reads data/spec_graduation.json (written nightly by
  // scanner/specgrad.py); absent, broken or empty → the strip stays hidden.
  // Nothing here feeds grades, filters or the bot — display only.
  async function loadGrads() {
    const host = $("#sp-grads");
    if (!host) return;
    host.hidden = true;
    const m = state.market;                   // the market this fetch is FOR
    try {
      const res = await PM.fetchTimeout("data/spec_graduation.json", { cache: "no-cache" });
      if (!res.ok) return;                    // no registry yet — invisible
      const reg = await res.json();
      if (m !== state.market) return;         // switched while in flight
      const mk = (reg && reg.markets && reg.markets[state.market]) || {};
      const grads = Array.isArray(mk.graduates) ? mk.graduates : [];
      const total = Number(mk.graduated_total) || grads.length;
      const watching = mk.seen && typeof mk.seen === "object"
        ? Object.keys(mk.seen).length : 0;
      // From the market alone — state.data may still hold the PREVIOUS
      // market's payload when this fires at the top of a market switch.
      const cur = state.market === "asx" ? "A$" : "$";
      if (!total && !watching) {
        // The registry exists but this market has nothing recorded yet —
        // say so instead of vanishing, so "no graduates" reads as the
        // surface's honest state rather than a broken strip (owner item 3;
        // still display-only, still fed by the same report file).
        host.innerHTML = `<div class="spg-head">
            <span class="spg-title">SPECS → VIVEK GRADUATES</span>
            <b class="spg-count">0</b>
            <span class="spg-note">none yet for ${PM.esc(state.market.toUpperCase())} — Specs names enter the watch on first appearance and are counted when they later cross into the published VIVEK scan</span>
          </div>`;
        host.hidden = false;
        return;
      }
      const rows = grads.slice(-6).reverse().map((g) => `<div class="spg-row">
          <b class="spg-sym">${PM.esc(g.symbol || "")}</b>
          <span class="spg-name">${PM.esc(g.name || "")}</span>
          <span class="spg-path">${PM.esc(cur)}${fp(g.spec_price)} → ${PM.esc(cur)}${fp(g.vivek_price)}</span>
          ${g.grade ? `<span class="spg-grade" title="VIVEK grade on graduation day">${PM.esc(g.grade)}</span>` : ""}
          <span class="spg-days" title="Days from first Specs appearance to VIVEK graduation">${PM.esc(g.days != null ? g.days + "d" : "—")}</span>
        </div>`).join("");
      host.innerHTML = `<div class="spg-head">
          <span class="spg-title">SPECS → VIVEK GRADUATES</span>
          <b class="spg-count">${Number(total) || 0}</b>
          <span class="spg-note">names this lens surfaced first that later crossed into the published VIVEK scan · watching ${Number(watching) || 0}</span>
        </div>${rows ? `<div class="spg-rows">${rows}</div>` : ""}`;
      host.hidden = false;
    } catch (_) { /* report-only strip — it never breaks the page */ }
  }

  function syncMarketButtons() {
    $$("#sp-market .market-btn").forEach((b) => {
      const on = b.dataset.market === state.market;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-selected", String(on));
    });
  }

  // "1,732 of 1,928 downloaded" when the file says how much the night saw
  // (REFINE200 #179); an older file only carries the universe size, which is
  // NOT how many names were scanned, so it is named as what it is.
  function coverageText(d) {
    const n = (v) => (typeof v === "number" && isFinite(v) ? v : null);
    const fmt = (v) => v.toLocaleString("en-AU");
    const got = n(d && d.downloaded), all = n(d && d.universe_size);
    if (got != null && all != null) return `${fmt(got)} of ${fmt(all)} downloaded`;
    return all != null ? `universe ${fmt(all)}` : "";
  }

  async function load() {
    // The market this call is FOR. A switch can land while the fetch is in
    // flight; applying the old answer would put ASX rows under the NASDAQ
    // heading and join NASDAQ confluence onto them (Tier 5 #79's app.js bug,
    // REFINE200 #175). Both the success and the failure path check it.
    const m = state.market;
    $("#sp-title").textContent = `SPECS · ${m.toUpperCase()} · loading…`;
    loadGrads();   // graduation strip rides beside the scan, never gates it
    try {
      const res = await PM.fetchTimeout(`data/${m}_spec.json`, { cache: "no-cache" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      if (m !== state.market) return;
      state.data = data;
      $("#sp-title").textContent =
        `SPECS · ${m.toUpperCase()} · ${state.data.results.length} setups`;
      const cov = coverageText(state.data);
      $("#sp-sub").innerHTML = PM.esc(
        `${PM.fmtMelb(state.data.generated_at)} · ${cov ? cov + " · " : ""}` +
        `volume-spike breakouts · sub-$0.50 · the discovery lens`)
        + PM.staleBadgeHTML(state.data.generated_at);
      state.confl = null;
      renderPills();
      PM.loadConfluence(m).then((c) => {
        if (m !== state.market) return;
        state.confl = c;
        renderPills();
        render();
      });
    } catch (err) {
      if (m !== state.market) return;
      state.data = null;
      $("#sp-title").textContent = `SPECS · ${state.market.toUpperCase()}`;
      // Same split as the other lens pages (2026-07-29): only a 404 means the
      // scan is missing; a network/CDN failure gets the truth and a retry.
      if (PM.loadFailKind(err) === "missing") {
        $("#sp-sub").textContent = `No ${state.market.toUpperCase()} specs scan yet (${err.message})`;
      } else {
        $("#sp-sub").innerHTML =
          PM.esc(`Couldn't load the ${state.market.toUpperCase()} specs scan — connection problem. `) +
          PM.retryHTML("sp-retry-load");
        const b = document.getElementById("sp-retry-load");
        if (b) b.addEventListener("click", () => { b.disabled = true; load(); });
      }
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
  $$("#sp-grade-filter .seg-btn").forEach((chip) => chip.addEventListener("click", () => {
    $$("#sp-grade-filter .seg-btn").forEach((c) => c.classList.toggle("is-active", c === chip));
    state.grade = chip.dataset.grade;
    renderPills();
    render();
  }));
  $$("#sp-sort-filter .seg-btn").forEach((chip) => chip.addEventListener("click", () => {
    $$("#sp-sort-filter .seg-btn").forEach((c) => c.classList.toggle("is-active", c === chip));
    state.sort = chip.dataset.sort;
    render();
  }));
  $("#sp-search").addEventListener("input", (e) => { state.q = e.target.value; render(); });

  syncMarketButtons();
  load();
})();
