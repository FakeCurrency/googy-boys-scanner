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

  // Filter state persists across reloads (like pm-market always has) so the
  // tab reopens exactly how it was left. q stays ephemeral on purpose.
  const lsGet = (k, fallback, ok) => {
    try {
      const v = localStorage.getItem(k);
      return v != null && (!ok || ok(v)) ? v : fallback;
    } catch (_) { return fallback; }
  };
  const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (_) {} };

  const state = {
    data: null, q: "", shown: PAGE,
    view: lsGet("pm-view", "setups", (v) => v in VIEWS || v === "watchlist"),
    tier: lsGet("pm-tier", "all"),
    dir:  lsGet("pm-dir", "all"),
    sort: lsGet("pm-sort", "default"),
    density: lsGet("pm-density", "full", (v) => ["full", "cozy", "compact"].includes(v)),
    focusIdx: -1,   // keyboard-focused card
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

  // Zone-native R:R — distance to the first live target vs distance to the
  // hard invalidation edge. The zone system's answer to the dashboard's R:R.
  function zoneRR(rec) {
    const c = rec.metrics && rec.metrics.close;
    if (c == null) return null;
    const hard = rec.zones.find((z) => z.id === "inv_hard");
    const tgt = rec.zones.find((z) => z.type === "TARGET" && z.status !== "CONSUMED");
    if (!hard || !tgt) return null;
    const bull = rec.direction !== "bearish";
    const reward = bull ? (tgt.low + tgt.high) / 2 - c : c - (tgt.low + tgt.high) / 2;
    const risk = bull ? c - hard.low : hard.high - c;
    if (risk <= 0 || reward <= 0) return null;
    return reward / risk;
  }

  function eventDate(rec) {   // most recent evidence bar — the FLASH sort key
    const m = rec.metrics || {};
    return m.displacement_date > (m.sweep_date || "") ? m.displacement_date
         : (m.sweep_date || "");
  }

  function applySort(rows) {
    const bynum = (fn) => (a, b) => (fn(b) ?? -Infinity) - (fn(a) ?? -Infinity)
      || a.ticker.localeCompare(b.ticker);
    if (state.sort === "fresh")
      return [...rows].sort((a, b) => String(eventDate(b)).localeCompare(String(eventDate(a)))
        || a.ticker.localeCompare(b.ticker));
    if (state.sort === "turnover")
      return [...rows].sort(bynum((r) => r.metrics && r.metrics.avg_turnover_20d));
    if (state.sort === "zrr")
      return [...rows].sort(bynum(zoneRR));
    return rows;   // default: tier/state order from the scan file
  }

  function chartURL(rec) {
    // The ORIGINAL chart page — full VIVEK-grade charting (multi-timeframe,
    // SMAs, drawing tools, live price, TradingView link) + the zones overlaid.
    // src=phasemap lets the chart's prev/next arrows step through THIS list —
    // flt carries the tab's filters + sort so stepping matches what you see.
    const flt = encodeURIComponent([state.view, state.tier, state.dir,
      state.hideIlliquid ? 1 : 0, state.sort].join("~"));
    return `chart.html?m=${state.market}&s=${encodeURIComponent(rec.ticker)}&dir=${rec.direction}&src=phasemap&flt=${flt}`;
  }

  // "Since you last checked" — a per-market snapshot of what the last visit
  // saw ("TICKER|direction" → state). Purely presentational: it only powers
  // the NEW / state-change badges and the catch-up banner.
  function seenKey() { return `pm-seen:${state.market}`; }
  function loadSeen() {
    try { return JSON.parse(localStorage.getItem(seenKey()) || "null"); }
    catch (_) { return null; }
  }
  function diffSinceLastVisit() {
    const prev = loadSeen();
    const cur = { run_date: state.data.run_date, states: {} };
    state.data.results.forEach((r) => { cur.states[`${r.ticker}|${r.direction}`] = r.state; });
    // same scan as last visit → nothing is "since you last checked"
    const fresh = prev && prev.run_date !== cur.run_date;
    state.sinceInfo = fresh ? { date: prev.run_date, added: 0, changed: 0 } : null;
    state.newKeys = new Set();
    state.changedFrom = {};
    if (fresh) {
      for (const [k, st] of Object.entries(cur.states)) {
        if (!(k in prev.states)) { state.newKeys.add(k); state.sinceInfo.added++; }
        else if (prev.states[k] !== st) { state.changedFrom[k] = prev.states[k]; state.sinceInfo.changed++; }
      }
    }
    lsSet(seenKey(), JSON.stringify(cur));
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
    const ci = state.confl ? state.confl.of(rec.ticker) : null;
    const aligned = ci && ci.side === (rec.direction === "bearish" ? "short" : "long");
    const key = `${rec.ticker}|${rec.direction}`;
    const isNew = state.newKeys && state.newKeys.has(key);
    const was = state.changedFrom && state.changedFrom[key];
    return `<article class="pm-card pm-card-link${aligned && ci.count >= 3 ? " pm-card-triple" : ""}" data-idx="${idx}" title="Open chart" tabindex="0">
      <div class="pm-card-head">
        <span class="pm-ticker">${PM.esc(rec.ticker)}</span>
        ${isNew ? '<span class="pm-tag pm-tag-new" title="Appeared since your last visit">NEW</span>' : ""}
        ${was ? `<span class="pm-tag pm-tag-new" title="State changed since your last visit">${PM.esc(was.replace("_", " "))} → ${PM.esc(rec.state.replace("_", " "))}</span>` : ""}
        ${aligned ? PM.confluenceChipHTML(ci, "PHASEMAP") : ""}
        ${flashed ? '<span class="pm-tag sp-spike" title="The sweep or displacement printed on the latest scan day — fresh evidence, review the chart">⚡ FLASHED</span>' : ""}
        ${rec._stale ? `<span class="pm-tag pm-tag-stale" title="Starred while a setup was live — it has since left the scan, shown from its last snapshot so you can keep monitoring">NO ACTIVE SETUP · last seen ${PM.esc(rec._staleDate || "")}</span>` : ""}
        ${PM.headBadgesHTML(rec)}
        ${PM.starHTML(starred, rec.ticker)}
        ${speak}
        <span class="pm-chart-cue" aria-hidden="true">CHART →</span>
      </div>
      ${PM.identityHTML(rec)}
      ${PM.stepperHTML(rec)}
      <div class="pm-ladder">${PM.ladderHTML(rec)}</div>
      ${rec.next ? `<div class="pm-next"><span class="pm-next-label">WANTED NEXT</span> ${PM.esc(rec.next)}</div>` : ""}
      ${PM.whyHTML(rec)}
      <p class="pm-narration">${PM.esc(rec.narration)}</p>
      <div class="pm-metrics">${PM.metricsHTML(rec)}</div>
    </article>`;
  }

  // Fuzzy ticker search: substring beats all, else the query chars must appear
  // in order (subsequence) — "CB A" finds CBA, "wtc" finds WTC, "bhp" B-H-P.
  // Names match on substring only (subsequence over long names = noise).
  function fuzzyHit(q, s) {
    s = String(s || "").toUpperCase();
    if (s.includes(q)) return true;
    let i = 0;
    for (const ch of s) { if (ch === q[i]) { i++; if (i === q.length) return true; } }
    return false;
  }
  const matchRec = (rec, q) => !q || fuzzyHit(q, rec.ticker) ||
    String(rec.name || "").toUpperCase().includes(q);

  function filtered() {
    const q = state.q.trim().toUpperCase();
    if (state.view === "watchlist") {
      // Starred names: live records where a setup still exists, snapshot
      // placeholders where it doesn't — the watch NEVER silently drops one.
      const wl = PM.watch.map("phasemap", state.market);
      const out = [];
      for (const [ticker, entry] of Object.entries(wl).sort()) {
        if (q && !fuzzyHit(q, ticker)) continue;
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
    return applySort(state.data.results.filter((r) =>
      states.includes(r.state) &&
      (state.tier === "all" || r.tier === state.tier) &&
      (state.dir === "all" || r.direction === state.dir) &&
      (!state.hideIlliquid || !r.tags.includes("ILLIQUID")) &&
      matchRec(r, q)));
  }

  function render() {
    const list = $("#pm-list");
    list.className = `pm-list pm-density-${state.density}`;
    renderActiveChips();
    renderSinceBanner();
    if (!state.data) { list.innerHTML = ""; return; }
    const rows = filtered();
    const shown = rows.slice(0, state.shown);
    list.innerHTML = shown.length
      ? shown.map(cardHTML).join("")
      : `<div class="pm-empty">Nothing matches this view right now.</div>`;
    $("#pm-more").hidden = rows.length <= state.shown;
    state.focusIdx = -1;

    $$(".pm-card-link", list).forEach((card) => {
      card.addEventListener("click", (e) => {
        if (e.target.closest(".pm-speak") || e.target.closest(".pm-star")
          || e.target.closest(".pm-why") || e.target.closest(".pm-term")) return;
        const rec = shown[+card.dataset.idx];
        if (rec) window.location.href = chartURL(rec);
      });
      // Enter opens the focused card (full keyboard path through the list)
      card.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" || e.target.closest(".pm-why")) return;
        const rec = shown[+card.dataset.idx];
        if (rec) window.location.href = chartURL(rec);
      });
    });
    $$(".pm-term", list).forEach((btn) => {
      btn.addEventListener("click", (e) => { e.stopPropagation(); openGlossary(btn.dataset.term); });
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

  function renderConfBanner() {
    let el = document.getElementById("conf-banner");
    const rows = state.confl ? state.confl.all() : [];
    if (!rows.length) { if (el) el.remove(); return; }
    if (!el) {
      el = document.createElement("section");
      el.id = "conf-banner";
      el.className = "conf-banner";
      const anchor = document.querySelector("#pm-tabs");
      if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(el, anchor);
      else return;
    }
    el.innerHTML = PM.confluenceBannerHTML(rows, state.market);
  }

  function renderCounts() {
    const counts = { watchlist: PM.watch.count("phasemap", state.market) };
    for (const [view, states] of Object.entries(VIEWS)) {
      counts[view] = state.data
        ? state.data.results.filter((r) => states.includes(r.state)).length : 0;
    }
    $$("[data-count]").forEach((el) => { el.textContent = counts[el.dataset.count] ?? 0; });
  }

  /* ── active-filter chips: everything non-default, each removable ───────── */
  const FILTER_DEFAULTS = { view: "setups", tier: "all", dir: "all", sort: "default" };
  function renderActiveChips() {
    const host = $("#pm-active");
    if (!host) return;
    const chips = [];
    const add = (label, reset) => chips.push({ label, reset });
    if (state.view !== FILTER_DEFAULTS.view) add(`view: ${state.view}`, () => setFilter("view", FILTER_DEFAULTS.view));
    if (state.tier !== "all") add(`tier: ${state.tier}`, () => setFilter("tier", "all"));
    if (state.dir !== "all") add(state.dir === "bullish" ? "longs only" : "shorts only", () => setFilter("dir", "all"));
    if (state.sort !== "default") add(`sort: ${state.sort}`, () => setFilter("sort", "default"));
    if (state.hideIlliquid) add("illiquid hidden", () => { state.hideIlliquid = false; lsSet("pm-hide-illiquid", "0"); syncFilterButtons(); state.shown = PAGE; render(); });
    if (state.q.trim()) add(`“${state.q.trim()}”`, () => { state.q = ""; $("#pm-search").value = ""; state.shown = PAGE; render(); });
    host.innerHTML = chips.length
      ? chips.map((c, i) => `<button class="pm-active-chip" data-i="${i}" title="Remove this filter">${PM.esc(c.label)} ✕</button>`).join("")
        + `<button class="pm-active-clear" title="Reset every filter">CLEAR ALL</button>`
      : "";
    host.hidden = !chips.length;
    $$(".pm-active-chip", host).forEach((b) => b.addEventListener("click", () => chips[+b.dataset.i].reset()));
    const clear = $(".pm-active-clear", host);
    if (clear) clear.addEventListener("click", () => {
      Object.assign(state, { ...FILTER_DEFAULTS, hideIlliquid: false, q: "" });
      ["view", "tier", "dir", "sort"].forEach((k) => lsSet(`pm-${k}`, FILTER_DEFAULTS[k]));
      lsSet("pm-hide-illiquid", "0");
      $("#pm-search").value = "";
      syncFilterButtons(); state.shown = PAGE; render();
    });
  }

  function setFilter(key, value) {
    state[key] = value;
    lsSet(`pm-${key}`, value);
    syncFilterButtons();
    state.shown = PAGE;
    render();
  }

  /* ── presets: one-click filter combos; customs saved in localStorage ───── */
  const BUILTIN_PRESETS = [
    { name: "⚡ FRESH", view: "setups", tier: "all", dir: "all", sort: "fresh", hideIlliquid: false },
    { name: "A+ LONGS", view: "all", tier: "A+", dir: "bullish", sort: "default", hideIlliquid: false },
    { name: "LIQUID SETUPS", view: "setups", tier: "all", dir: "all", sort: "turnover", hideIlliquid: true },
  ];
  function customPresets() {
    try { return JSON.parse(localStorage.getItem("pm-presets") || "[]"); }
    catch (_) { return []; }
  }
  function applyPreset(p) {
    Object.assign(state, { view: p.view, tier: p.tier, dir: p.dir, sort: p.sort,
      hideIlliquid: !!p.hideIlliquid });
    ["view", "tier", "dir", "sort"].forEach((k) => lsSet(`pm-${k}`, state[k]));
    lsSet("pm-hide-illiquid", state.hideIlliquid ? "1" : "0");
    syncFilterButtons(); state.shown = PAGE; render();
  }
  function renderPresets() {
    const host = $("#pm-presets");
    if (!host) return;
    const customs = customPresets();
    host.innerHTML =
      [...BUILTIN_PRESETS.map((p, i) => `<button class="pm-chip pm-preset" data-b="${i}">${PM.esc(p.name)}</button>`),
       ...customs.map((p, i) => `<button class="pm-chip pm-preset" data-c="${i}">★ ${PM.esc(p.name)}<span class="pm-preset-x" data-x="${i}" title="Delete preset">✕</span></button>`),
       `<button class="pm-chip pm-preset-save" id="pm-preset-save" title="Save the current view/tier/direction/sort/liquidity combo as a preset">+ SAVE</button>`].join("");
    $$(".pm-preset[data-b]", host).forEach((b) => b.addEventListener("click", () => applyPreset(BUILTIN_PRESETS[+b.dataset.b])));
    $$(".pm-preset[data-c]", host).forEach((b) => b.addEventListener("click", (e) => {
      if (e.target.closest(".pm-preset-x")) return;
      applyPreset(customPresets()[+b.dataset.c]);
    }));
    $$(".pm-preset-x", host).forEach((x) => x.addEventListener("click", (e) => {
      e.stopPropagation();
      const cs = customPresets(); cs.splice(+x.dataset.x, 1);
      lsSet("pm-presets", JSON.stringify(cs)); renderPresets();
    }));
    $("#pm-preset-save").addEventListener("click", () => {
      const name = (prompt("Name this preset:") || "").trim().slice(0, 24);
      if (!name) return;
      const cs = customPresets().filter((p) => p.name !== name);
      cs.push({ name, view: state.view, tier: state.tier, dir: state.dir,
        sort: state.sort, hideIlliquid: state.hideIlliquid });
      lsSet("pm-presets", JSON.stringify(cs)); renderPresets();
    });
    // Freshly (re)built chips carry no active state — sync immediately so a
    // matching preset is highlighted from first paint (and after deletes).
    syncFilterButtons();
  }

  /* ── "since you last checked" banner ───────────────────────────────────── */
  function renderSinceBanner() {
    let el = $("#pm-since");
    const info = state.sinceInfo;
    if (!info || (!info.added && !info.changed) || state.sinceDismissed) { if (el) el.remove(); return; }
    if (!el) {
      el = document.createElement("div");
      el.id = "pm-since"; el.className = "pm-since";
      const list = $("#pm-list");
      list.parentNode.insertBefore(el, list);
    }
    const bits = [];
    if (info.added) bits.push(`<b>${info.added}</b> new name${info.added === 1 ? "" : "s"}`);
    if (info.changed) bits.push(`<b>${info.changed}</b> state change${info.changed === 1 ? "" : "s"}`);
    el.innerHTML = `<span>SINCE YOU LAST CHECKED (scan ${PM.esc(info.date)}): ${bits.join(" · ")} — look for the NEW / → badges.</span>` +
      `<button class="pm-since-x" title="Dismiss" aria-label="Dismiss">✕</button>`;
    $(".pm-since-x", el).addEventListener("click", () => { state.sinceDismissed = true; el.remove(); });
  }

  /* ── glossary drawer ───────────────────────────────────────────────────── */
  function openGlossary(term) {
    const drawer = $("#pm-gloss");
    if (!drawer) return;
    $("#pm-gloss-body").innerHTML = PM.glossaryHTML();
    drawer.hidden = false;
    document.body.classList.add("pm-gloss-open");
    if (term) {
      const target = $(`#gloss-${CSS.escape(term)}`, drawer);
      if (target) { target.scrollIntoView({ block: "start" }); target.classList.add("is-hit"); }
    }
  }
  function closeGlossary() {
    const drawer = $("#pm-gloss");
    if (drawer) drawer.hidden = true;
    document.body.classList.remove("pm-gloss-open");
  }

  /* ── keyboard: "/" search · arrows move · Enter open · Esc out ─────────── */
  function wireKeyboard() {
    document.addEventListener("keydown", (e) => {
      const inField = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
      if (e.key === "Escape") {
        closeGlossary();
        if (inField) document.activeElement.blur();
        return;
      }
      if (e.key === "/" && !inField) {
        e.preventDefault(); $("#pm-search").focus(); $("#pm-search").select();
        return;
      }
      if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !inField) {
        const cards = $$("#pm-list .pm-card-link");
        if (!cards.length) return;
        e.preventDefault();
        state.focusIdx = Math.min(cards.length - 1,
          Math.max(0, state.focusIdx + (e.key === "ArrowDown" ? 1 : -1)));
        cards[state.focusIdx].focus();
        cards[state.focusIdx].scrollIntoView({ block: "nearest" });
      }
    });
  }

  const SKELETON = `<div class="pm-card pm-skel">
    <div class="pm-skel-line w40"></div><div class="pm-skel-line w70"></div>
    <div class="pm-skel-line"></div><div class="pm-skel-line w55"></div>
  </div>`;

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
      state.view = tab.dataset.view;
      lsSet("pm-view", state.view);
      syncFilterButtons();
      state.shown = PAGE;
      render();
    }));
    const chipGroup = (rootSel, key, dataKey) =>
      $$(rootSel + " .pm-chip").forEach((chip) => chip.addEventListener("click", () => {
        state[key] = chip.dataset[dataKey];
        lsSet(`pm-${key}`, state[key]);
        // One sync path for every chip class (2026-07-23): the old per-group
        // toggle here left PRESET chips stale — drifting off "A+ LONGS" via a
        // manual filter kept the preset lit. syncFilterButtons owns all of it.
        syncFilterButtons();
        state.shown = PAGE;
        render();
      }));
    chipGroup("#pm-tier-filter", "tier", "tier");
    chipGroup("#pm-dir-filter", "dir", "dir");
    chipGroup("#pm-sort-filter", "sort", "sort");
    chipGroup("#pm-density-filter", "density", "density");
    const liqBtn = $("#pm-liq-filter .pm-chip");
    if (liqBtn) {
      liqBtn.classList.toggle("is-active", state.hideIlliquid);
      liqBtn.addEventListener("click", () => {
        state.hideIlliquid = !state.hideIlliquid;
        try { localStorage.setItem("pm-hide-illiquid", state.hideIlliquid ? "1" : "0"); } catch (_) {}
        syncFilterButtons();   // covers this chip + preset match state
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
    const glossBtn = $("#pm-gloss-btn");
    if (glossBtn) glossBtn.addEventListener("click", () => openGlossary());
    const glossX = $("#pm-gloss-x");
    if (glossX) glossX.addEventListener("click", closeGlossary);
    const glossDrawer = $("#pm-gloss");
    if (glossDrawer) glossDrawer.addEventListener("click", (e) => {
      if (e.target === glossDrawer) closeGlossary();   // backdrop click
    });
  }

  function syncMarketButtons() {
    $$("#pm-market .market-btn").forEach((b) => {
      const on = b.dataset.market === state.market;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-selected", String(on));
    });
  }

  // Reflect restored/preset state into every control — the HTML's hardcoded
  // is-active defaults only match a first-ever visit.
  function syncFilterButtons() {
    $$("#pm-tabs .pm-tab").forEach((t) => {
      const on = t.dataset.view === state.view;
      t.classList.toggle("is-active", on);
      t.setAttribute("aria-selected", String(on));
    });
    const syncGroup = (rootSel, dataKey, value) =>
      $$(rootSel + " .pm-chip").forEach((c) => c.classList.toggle("is-active", c.dataset[dataKey] === value));
    syncGroup("#pm-tier-filter", "tier", state.tier);
    syncGroup("#pm-dir-filter", "dir", state.dir);
    syncGroup("#pm-sort-filter", "sort", state.sort);
    syncGroup("#pm-density-filter", "density", state.density);
    const liq = $("#pm-liq-filter .pm-chip");
    if (liq) liq.classList.toggle("is-active", state.hideIlliquid);
    // Preset chips light up while the CURRENT combo exactly matches what
    // they'd apply (owner 2026-07-23: "when i click on A+ longs i want it
    // to be highlighted so i know i'm on A+ longs") — and dim again the
    // moment any single filter drifts off that combo.
    const presetMatches = (p) => !!p && p.view === state.view && p.tier === state.tier &&
      p.dir === state.dir && p.sort === state.sort && !!p.hideIlliquid === !!state.hideIlliquid;
    $$("#pm-presets .pm-preset").forEach((b) => {
      const p = b.dataset.b != null ? BUILTIN_PRESETS[+b.dataset.b] : customPresets()[+b.dataset.c];
      b.classList.toggle("is-active", presetMatches(p));
    });
  }

  async function load() {
    $("#pm-sub").textContent = "Loading latest scan…";
    $("#pm-list").innerHTML = SKELETON.repeat(4);   // shimmer, not a blank page
    try {
      // narrations ship in a sidecar file (latest.json is ~25% lighter);
      // fetched in parallel and merged back. Old full payloads still work.
      const [res, narrRes] = await Promise.all([
        fetch(`data/phasemap/${state.market}/latest.json`, { cache: "no-cache" }),
        fetch(`data/phasemap/${state.market}/narrations.json`, { cache: "no-cache" }).catch(() => null),
      ]);
      if (!res.ok) throw new Error("HTTP " + res.status);
      state.data = await res.json();
      try {
        let nj = narrRes && narrRes.ok ? await narrRes.json() : null;
        // The pair ships together but is fetched in parallel — a deploy landing
        // between the two requests can leave the sidecar on the PREVIOUS scan
        // (review H5). run_date-match the pair and refetch the sidecar once,
        // cache-busted by the wanted run_date (shared, CDN-friendly buster).
        if (nj && nj.run_date && state.data.run_date && nj.run_date !== state.data.run_date) {
          try {
            const r2 = await fetch(
              `data/phasemap/${state.market}/narrations.json?rd=${encodeURIComponent(state.data.run_date)}`,
              { cache: "reload" });
            if (r2.ok) nj = await r2.json();
          } catch (_) { /* keep the mismatched sidecar — better than nothing */ }
        }
        const nm = (nj && nj.narrations) || {};
        state.data.results.forEach((r) => {
          if (r.narration == null) r.narration = nm[`${r.ticker}|${r.direction}`] || "";
        });
      } catch (_) {
        state.data.results.forEach((r) => { if (r.narration == null) r.narration = ""; });
      }
      $("#pm-sub").innerHTML = PM.esc(
        `${state.market.toUpperCase()} · scan ${state.data.run_date} · ruleset v${state.data.ruleset_version} · ` +
        `${state.data.universe_size} tickers scanned · ${state.data.results.length} results`)
        + PM.staleBadgeHTML(state.data.run_date);
      state.sinceDismissed = false;
      diffSinceLastVisit();
      // keep starred snapshots fresh while their setups are still live
      const wl = PM.watch.map("phasemap", state.market);
      for (const ticker of Object.keys(wl)) {
        const live = state.data.results.find((r) => r.ticker === ticker);
        if (live) PM.watch.refresh("phasemap", state.market, ticker, live);
      }
      // multi-lens confluence badges + banner (async — re-render when known)
      state.confl = null;
      renderConfBanner();
      PM.loadConfluence(state.market).then((c) => {
        state.confl = c;
        render();
        renderConfBanner();
      });
    } catch (err) {
      state.data = null;
      // 404 = the artefact is genuinely missing; anything else is a
      // connection/CDN failure where the scan EXISTS and deserves a retry
      // button, not a "run the scanner" shrug (2026-07-29).
      if (PM.loadFailKind(err) === "missing") {
        $("#pm-sub").textContent =
          `No ${state.market.toUpperCase()} PhaseMap scan yet (${err.message})`;
        $("#pm-list").innerHTML = `<div class="pm-empty">Run: python -m phasemap.run --market ${PM.esc(state.market)}</div>`;
      } else {
        $("#pm-sub").textContent =
          `Couldn't load the ${state.market.toUpperCase()} PhaseMap scan — connection problem.`;
        $("#pm-list").innerHTML =
          `<div class="pm-empty">The scan is there; this device couldn't fetch it. ${PM.retryHTML("pm-retry-load")}</div>`;
        const b = document.getElementById("pm-retry-load");
        if (b) b.addEventListener("click", () => { b.disabled = true; load(); });
      }
      renderCounts();
      $("#pm-more").hidden = true;
      return;
    }
    renderCounts();
    render();
  }

  syncMarketButtons();
  syncFilterButtons();
  wire();
  renderPresets();
  wireKeyboard();
  load();
  // pull remote stars (unified watchlist) so phone/desktop agree
  if (window.GBSSync && GBSSync.enabled()) {
    GBSSync.syncIn().then(() => { renderCounts(); render(); }).catch(() => {});
  }
})();
