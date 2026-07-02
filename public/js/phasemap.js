/* PHASEMAP tab — renders public/data/phasemap/latest.json.
   Read-only view of the nightly scan snapshot; no live queries.
   Guardrail: everything shown is a computed zone/state — nothing freestyle. */
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

  const state = { data: null, view: "setups", tier: "all", dir: "all", q: "", shown: PAGE };

  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

  /* ---------------------------------------------------------- formatting */
  const fmtPrice = (x) => {
    if (x == null || !isFinite(x)) return "—";
    if (x < 0.1) return x.toFixed(4);
    if (x < 2) return x.toFixed(3);
    return x.toFixed(2);
  };
  const fmtPct = (x) => (x == null ? "—" : (x * 100).toFixed(1) + "%");
  const fmtTurnover = (x) => {
    if (x == null) return "—";
    if (x >= 1e6) return "$" + (x / 1e6).toFixed(1) + "M";
    return "$" + Math.round(x / 1e3) + "k";
  };
  const esc = (s) => String(s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const SOURCE_LABELS = {
    box_high: "box high", box_low: "box low",
    equal_highs: "equal highs", equal_lows: "equal lows",
    prior_high: "prior high", prior_low: "prior low",
    yearly_open: "yearly open", quarterly_open: "quarterly open",
    monthly_open: "monthly open", prior_yearly_close: "prior yearly close",
    fib_ext_10: "fib ext 1.0–1.272", fib_ext_1618: "fib ext 1.618–2.0",
    sweep_wick: "sweep wick",
  };
  const srcText = (z) => (z.sources || []).map((s) => SOURCE_LABELS[s] || s).join(" + ");

  const BAND_CLASS = {
    TARGET: "pm-band-target",
    ENTRY_CONTINUATION: "pm-band-entry",
    INVALIDATION_HARD: "pm-band-kill",
    INVALIDATION_MOMENTUM: "pm-band-kill",
    DEMAND: "pm-band-trap",
    SUPPLY: "pm-band-trap",
  };
  const BAND_LABEL = {
    TARGET: "TARGET",
    ENTRY_CONTINUATION: "ENTRY",
    INVALIDATION_HARD: "HARD INVALID.",
    INVALIDATION_MOMENTUM: "50% INVALID.",
    DEMAND: "DEMAND",
    SUPPLY: "SUPPLY",
  };

  /* ------------------------------------------------------------- ladder */
  function ladderHTML(rec) {
    const close = rec.metrics && rec.metrics.close;
    const rows = rec.zones.map((z) => ({ kind: "zone", z, mid: (z.low + z.high) / 2 }));
    if (close != null) rows.push({ kind: "price", mid: close });
    rows.sort((a, b) => b.mid - a.mid);   // highest price at the top

    return rows.map((row) => {
      if (row.kind === "price") {
        return `<div class="pm-price-row">
          <span class="pm-price-label">${fmtPrice(close)}</span>
          <span class="pm-price-line"><span>CURRENT</span></span>
        </div>`;
      }
      const z = row.z;
      const cls = BAND_CLASS[z.type] || "pm-band-trap";
      const done = z.status === "CONSUMED" ? " pm-band-consumed"
        : z.status === "VIOLATED" ? " pm-band-violated" : "";
      const label = z.type === "TARGET" ? z.id.toUpperCase() : (BAND_LABEL[z.type] || z.type);
      const conf = z.confluence > 1 ? ` ×${z.confluence}` : "";
      return `<div class="pm-rung">
        <span class="pm-rung-prices">${fmtPrice(z.low)}–${fmtPrice(z.high)}</span>
        <span class="pm-band ${cls}${done}">
          <span class="pm-band-label">${esc(label)}${conf}</span>
          <span class="pm-band-status">${esc(z.status)}</span>
          <span class="pm-band-sources">${esc(srcText(z))}</span>
        </span>
      </div>`;
    }).join("");
  }

  /* --------------------------------------------------------------- card */
  const TIER_CLASS = { "A+": "pm-tier-aplus", A: "pm-tier-a", Watch: "pm-tier-watch" };

  function metricsHTML(rec) {
    const m = rec.metrics || {};
    const bits = [];
    if (m.retrace_pct != null) bits.push(`retrace <b>${fmtPct(m.retrace_pct)}</b>`);
    if (m.dist_to_yearly_open_pct != null)
      bits.push(`vs yearly open <b>${fmtPct(m.dist_to_yearly_open_pct)}</b>`);
    const warn = m.avg_turnover_20d != null && rec.tags.includes("ILLIQUID");
    bits.push(`<span class="${warn ? "pm-metric-warn" : ""}">turnover <b>${fmtTurnover(m.avg_turnover_20d)}</b></span>`);
    if (m.sweep_date) bits.push(`swept <b>${esc(m.sweep_date)}</b>`);
    if (m.displacement_date) bits.push(`displaced <b>${esc(m.displacement_date)}</b>`);
    if (m.bars_in_box != null) bits.push(`in box <b>${m.bars_in_box} bars</b>`);
    return bits.map((b) => `<span>${b}</span>`).join("");
  }

  function cardHTML(rec, idx) {
    const long = rec.direction === "bullish";
    const tier = rec.tier
      ? `<span class="pm-tier ${TIER_CLASS[rec.tier] || ""}">${esc(rec.tier)}</span>` : "";
    const tags = rec.tags.map((t) => {
      const extra = t === "ILLIQUID" ? " pm-tag-illiquid" : t === "HALT_RISK" ? " pm-tag-halt" : "";
      return `<span class="pm-tag${extra}">${esc(t)}</span>`;
    }).join("");
    const speak = window.speechSynthesis
      ? `<button class="pm-speak" data-speak="${idx}" title="Read aloud" aria-label="Read analysis aloud">▶ READ</button>`
      : "";
    return `<article class="pm-card">
      <div class="pm-card-head">
        <span class="pm-ticker">${esc(rec.ticker)}</span>
        <span class="pm-dir ${long ? "pm-dir-long" : "pm-dir-short"}">${long ? "LONG" : "SHORT"}</span>
        <span class="pm-state pm-state-${esc(rec.state)}">${esc(rec.state.replace("_", " "))}</span>
        ${tier}
        <span class="pm-regime">${esc(rec.regime)}</span>
        ${tags}
        ${speak}
      </div>
      <div class="pm-ladder">${ladderHTML(rec)}</div>
      <p class="pm-narration">${esc(rec.narration)}</p>
      <div class="pm-metrics">${metricsHTML(rec)}</div>
    </article>`;
  }

  /* ---------------------------------------------------------- read aloud */
  let speakingBtn = null;
  function toggleSpeak(btn, text) {
    const synth = window.speechSynthesis;
    if (!synth) return;                       // feature-flag: degrade silently
    if (speakingBtn === btn && synth.speaking) {
      synth.cancel();
      btn.classList.remove("is-speaking");
      speakingBtn = null;
      return;
    }
    synth.cancel();
    if (speakingBtn) speakingBtn.classList.remove("is-speaking");
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "en-AU";
    u.onend = u.onerror = () => { btn.classList.remove("is-speaking"); speakingBtn = null; };
    btn.classList.add("is-speaking");
    speakingBtn = btn;
    synth.speak(u);
  }

  /* ------------------------------------------------------------- filters */
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
    const rows = filtered();
    const shown = rows.slice(0, state.shown);
    list.innerHTML = shown.length
      ? shown.map(cardHTML).join("")
      : `<div class="pm-empty">Nothing matches this view right now.</div>`;
    $("#pm-more").hidden = rows.length <= state.shown;

    $$(".pm-speak", list).forEach((btn) => {
      btn.addEventListener("click", () => {
        const rec = shown[+btn.dataset.speak];
        if (rec) toggleSpeak(btn, rec.narration);
      });
    });
  }

  function renderCounts() {
    const counts = {};
    for (const [view, states] of Object.entries(VIEWS)) {
      counts[view] = state.data.results.filter((r) => states.includes(r.state)).length;
    }
    $$("[data-count]").forEach((el) => { el.textContent = counts[el.dataset.count] ?? 0; });
  }

  function wire() {
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

  async function load() {
    try {
      const res = await fetch("data/phasemap/latest.json", { cache: "no-cache" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      state.data = await res.json();
      $("#pm-sub").textContent =
        `Scan ${state.data.run_date} · ruleset v${state.data.ruleset_version} · ` +
        `${state.data.universe_size} tickers scanned · ${state.data.results.length} results`;
      renderCounts();
      render();
    } catch (err) {
      $("#pm-sub").textContent = "No PhaseMap scan found yet — run: python -m phasemap.run";
      $("#pm-list").innerHTML = `<div class="pm-empty">latest.json not available (${esc(err.message)})</div>`;
    }
  }

  wire();
  load();
})();
