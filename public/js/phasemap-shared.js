/* PHASEMAP shared helpers — used by phasemap.js (list) and phasemap-chart.js.
   Everything rendered comes straight from the scan snapshot — nothing freestyle. */
window.PM = (() => {
  "use strict";

  const fmtPrice = (x) => {
    if (x == null || !isFinite(x)) return "—";
    if (x >= 1000) return x.toLocaleString("en-AU", { maximumFractionDigits: 0 });
    if (x < 0.001) return x.toFixed(8).replace(/0+$/, "");
    if (x < 0.1) return x.toFixed(4);
    if (x < 2) return x.toFixed(3);
    return x.toFixed(2);
  };
  const fmtPct = (x) => (x == null ? "—" : (x * 100).toFixed(1) + "%");
  const fmtTurnover = (x) => {
    if (x == null) return "—";
    if (x >= 1e9) return "$" + (x / 1e9).toFixed(1) + "B";
    if (x >= 1e6) return "$" + (x / 1e6).toFixed(1) + "M";
    return "$" + Math.round(x / 1e3) + "k";
  };
  // Null-safe like the other nine copies. This one was `String(s)`, so
  // `esc(null)` rendered the literal word "null" into the page — which is why
  // several call sites here and in phasemap.js/specs.js/mynames.js carry a
  // defensive `|| ""`. The guard belongs in one place, not at every caller.
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
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
  const zoneLabel = (z) =>
    z.type === "TARGET" ? z.id.toUpperCase() : (BAND_LABEL[z.type] || z.type);

  function ladderHTML(rec) {
    const close = rec.metrics && rec.metrics.close;
    const rows = rec.zones.map((z) => ({ kind: "zone", z, mid: (z.low + z.high) / 2 }));
    if (close != null) rows.push({ kind: "price", mid: close });
    rows.sort((a, b) => b.mid - a.mid);
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
      const conf = z.confluence > 1 ? ` ×${z.confluence}` : "";
      return `<div class="pm-rung">
        <span class="pm-rung-prices">${fmtPrice(z.low)}–${fmtPrice(z.high)}</span>
        <span class="pm-band ${cls}${done}">
          <span class="pm-band-label">${esc(zoneLabel(z))}${conf}</span>
          <span class="pm-band-status">${esc(z.status)}</span>
          <span class="pm-band-sources">${esc(srcText(z))}</span>
        </span>
      </div>`;
    }).join("");
  }

  function metricsHTML(rec) {
    const m = rec.metrics || {};
    const bits = [];
    if (m.retrace_pct != null) bits.push(`retrace <b>${fmtPct(m.retrace_pct)}</b>`);
    if (m.dist_to_yearly_open_pct != null)
      bits.push(`vs yearly open <b>${fmtPct(m.dist_to_yearly_open_pct)}</b>`);
    const warn = rec.tags.includes("ILLIQUID");
    bits.push(`<span class="${warn ? "pm-metric-warn" : ""}">turnover <b>${fmtTurnover(m.avg_turnover_20d)}</b></span>`);
    if (m.sweep_date) bits.push(`swept <b>${esc(m.sweep_date)}</b>`);
    if (m.displacement_date) bits.push(`displaced <b>${esc(m.displacement_date)}</b>`);
    if (m.bars_in_box != null) bits.push(`in box <b>${m.bars_in_box} bars</b>`);
    return bits.map((b) => `<span>${b}</span>`).join("");
  }

  const TIER_CLASS = { "A+": "pm-tier-aplus", A: "pm-tier-a", Watch: "pm-tier-watch" };

  /* REIT / ETF / LIC / managed fund — mirrors chart.js isFundReit so the same
     names get flagged on cards and charts alike. */
  const FUND_NAME_KW = ["REIT", "TRUST", "FUND", "ETF", "SPDR", "ISHARES",
    "VANGUARD", "BETASHARES", "VANECK", "GLOBAL X"];
  const FUND_SECTOR_HINTS = ["reit", "real estate investment trust"];
  const NON_OP_SECTORS = ["not applicable", "not applic", "n/a"];
  // (2026-08-01, owner display fix) WORD-BOUNDARY keyword matching. The old
  // includes() matched "ETF" INSIDE "N-ETF-LIX" and badged Netflix as a fund.
  // \b keeps "CHARTER HALL TRUST" caught while leaving NETFLIX/TRUSTEE-class
  // names alone. The keyword LIST is unchanged — only how it is matched.
  const FUND_KW_RE = new RegExp("\\b(" + FUND_NAME_KW
    .map((kw) => kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")\\b");

  function isFundReit(rec) {
    const sector = String(rec.sector || "").trim().toLowerCase();
    if (FUND_SECTOR_HINTS.some((h) => sector.includes(h))) return true;
    if (NON_OP_SECTORS.includes(sector)) return true;
    const name = String(rec.name || rec.ticker || "").toUpperCase();
    return FUND_KW_RE.test(name);
  }

  function identityHTML(rec) {
    const bits = [];
    if (rec.name && rec.name !== rec.ticker) bits.push(esc(rec.name));
    if (rec.sector) bits.push(`<span class="pm-sector">${esc(rec.sector)}</span>`);
    const fund = isFundReit(rec)
      ? `<span class="pm-tag pm-tag-fund">FUND / REIT</span>` : "";
    if (!bits.length && !fund) return "";
    return `<div class="pm-identity">${bits.join(" · ")} ${fund}</div>`;
  }

  /* Non-color glyph per state — direction/state must survive greyscale and
     red-green colorblindness (WCAG 1.4.1: color is never the only signal). */
  const STATE_GLYPH = {
    TRAP_SET: "◎", SWEPT: "◉", DISPLACED: "▲", RUNNING: "▶",
    STALLED: "⏸", COMPLETE: "✓", DEAD: "✕",
  };

  function headBadgesHTML(rec) {
    const long = rec.direction === "bullish";
    const tier = rec.tier
      ? `<span class="pm-tier ${TIER_CLASS[rec.tier] || ""}">${esc(rec.tier)}</span>` : "";
    const tags = rec.tags.map((t) => {
      const extra = t === "ILLIQUID" ? " pm-tag-illiquid" : t === "HALT_RISK" ? " pm-tag-halt" : "";
      return `<span class="pm-tag${extra}">${esc(t)}</span>`;
    }).join("");
    return `
      <span class="pm-dir ${long ? "pm-dir-long" : "pm-dir-short"}">${long ? "▲ LONG" : "▼ SHORT"}</span>
      <span class="pm-state pm-state-${esc(rec.state)}">${STATE_GLYPH[rec.state] || ""} ${esc(rec.state.replace("_", " "))}</span>
      ${tier}
      <span class="pm-regime">${esc(rec.regime)}</span>
      ${tags}`;
  }

  /* ── Phase stepper ───────────────────────────────────────────────────────
     The lens's lifecycle as a horizontal progress strip. Steps are marked
     reached ONLY from printed evidence (state + sweep/displacement dates) —
     the stepper never claims progress the scan hasn't reported. STALLED and
     DEAD are off-path terminals appended after the furthest reached step. */
  const PHASE_PATH = ["TRAP_SET", "SWEPT", "DISPLACED", "RUNNING", "COMPLETE"];
  function stepperHTML(rec) {
    const m = rec.metrics || {};
    const onPath = PHASE_PATH.indexOf(rec.state);
    // furthest step with evidence: state itself if on-path, else dates
    let reached = onPath >= 0 ? onPath
      : m.displacement_date ? 2
      : m.sweep_date ? 1 : 0;
    const terminal = onPath === -1 ? rec.state : null;   // STALLED | DEAD
    const steps = PHASE_PATH.map((s, i) => {
      const cls = i < reached ? "is-done" : i === reached && !terminal ? "is-now"
        : i === reached ? "is-done" : "";
      return `<span class="pm-step ${cls}" data-term="${esc(s.toLowerCase())}">` +
        `<span class="pm-step-dot">${STATE_GLYPH[s]}</span>${esc(s.replace("_", " "))}</span>`;
    });
    if (terminal) {
      steps.splice(reached + 1, 0,
        `<span class="pm-step is-now is-terminal pm-step-${esc(terminal)}" data-term="${esc(terminal.toLowerCase())}">` +
        `<span class="pm-step-dot">${STATE_GLYPH[terminal]}</span>${esc(terminal)}</span>`);
      steps.length = reached + 2;   // the path beyond a terminal never happens
    }
    return `<div class="pm-stepper" title="Where this name sits in the trap lifecycle">` +
      steps.join(`<span class="pm-step-arrow">›</span>`) + `</div>`;
  }

  /* ── "Why flagged" panel ─────────────────────────────────────────────────
     Plain-language restatement of the fields the scan actually printed —
     state semantics mirror the KEY & LEGEND page; every bullet is tied to a
     datum in the record. Nothing here computes or predicts anything. */
  const STATE_WHY = {
    TRAP_SET: "The map is drawn: a liquidity pool and its zones are identified, but price has not swept it yet. Nothing is confirmed at this stage.",
    SWEPT: "Price ran through the mapped liquidity pool — the sweep printed. Now waiting for displacement to confirm intent.",
    DISPLACED: "After the sweep, price displaced away with conviction — the confirmation evidence this lens waits for has printed.",
    RUNNING: "Displacement confirmed and price is travelling toward its target zones — the setup is live.",
    STALLED: "The move lost momentum before completing — rotation, not trend. It can resume or die from here.",
    COMPLETE: "The final target zone was reached — this setup has fully played out.",
    DEAD: "Price violated the hard invalidation zone — the idea is invalidated and the setup is finished.",
  };
  function whyHTML(rec) {
    const m = rec.metrics || {};
    const rows = [];
    const term = (label, key) => `<button class="pm-term" data-term="${esc(key)}" ` +
      `title="What does '${esc(label)}' mean?">${esc(label)}<sup>?</sup></button>`;
    rows.push(STATE_WHY[rec.state] || "");
    if (m.sweep_date) rows.push(`${term("Sweep", "swept")} printed on <b>${esc(m.sweep_date)}</b>.`);
    if (m.displacement_date) rows.push(`${term("Displacement", "displaced")} printed on <b>${esc(m.displacement_date)}</b>.`);
    if (m.retrace_pct != null) rows.push(`Retrace so far: <b>${fmtPct(m.retrace_pct)}</b>.`);
    if (m.bars_in_box != null) rows.push(`<b>${m.bars_in_box}</b> bars spent in the ${term("box", "box")}.`);
    const live = rec.zones.filter((z) => z.status !== "CONSUMED" && z.status !== "VIOLATED").length;
    if (rec.zones.length) rows.push(`<b>${rec.zones.length}</b> ${term("zones", "zone")} mapped, <b>${live}</b> still live — every one a price band, never a single price.`);
    if (rec.tier) rows.push(`Scan ${term("tier", "tier")}: <b>${esc(rec.tier)}</b>.`);
    if (rec.tags.includes("ILLIQUID")) rows.push(`<b>ILLIQUID</b> — average turnover is below the $200k/day floor; fills and exits will be harder than the chart implies.`);
    if (rec.tags.includes("HALT_RISK")) rows.push(`<b>HALT RISK</b> — this name carries a trading-halt risk flag from the scan.`);
    return `<details class="pm-why"><summary>WHY FLAGGED <span class="pm-why-chev">▾</span></summary>
      <ul>${rows.filter(Boolean).map((r) => `<li>${r}</li>`).join("")}</ul></details>`;
  }

  /* ── Glossary (plain-language, mirrors the KEY & LEGEND page) ───────────── */
  const GLOSSARY = [
    ["zone", "Zone", "A price BAND with an upper and lower bound — never a single price. Every level PhaseMap draws is a zone."],
    ["trap_set", "Trap set", "The starting state: a liquidity pool and its zones are mapped, but price hasn't swept them yet."],
    ["swept", "Sweep", "Price runs through a mapped liquidity pool (e.g. equal lows), taking out the resting orders there. The trap springs — but a sweep alone confirms nothing."],
    ["displaced", "Displacement", "A decisive move away after the sweep. This is the confirmation evidence the lens waits for before a setup counts."],
    ["box", "Box", "The consolidation range price built before the event — its high and low are the liquidity zones most likely to be swept."],
    ["tier", "Tier", "The scan's quality bucket for the setup (A+ / A / Watch), from the ruleset — not a prediction."],
    ["regime", "Regime", "The broader behaviour the scan reads this name in (e.g. ROTATION) — context, not a signal."],
    ["target", "Target zone", "Where the move is headed if the setup plays out. Consumed targets are greyed out."],
    ["hard_invalidation", "Hard invalidation", "The zone that proves the idea wrong. Price closing through it kills the setup (DEAD)."],
    ["momentum_invalidation", "50% invalidation", "The softer warning level — losing it means momentum has failed even if the hard line survives."],
    ["confluence", "Confluence (×N)", "N independent sources land on the same band (e.g. box low + fib extension) — the band is merged and marked ×N."],
    ["flashed", "⚡ FLASHED", "The sweep or displacement printed on the latest scan day — fresh evidence worth reviewing now."],
    ["stalled", "Stalled", "The move lost momentum before completing — rotation, not trend."],
    ["dead", "Dead", "The hard invalidation was violated — the setup is finished."],
    ["complete", "Complete", "The final target zone was reached — the setup fully played out."],
    ["running", "Running", "Displacement confirmed and price is travelling toward its targets — the setup is live."],
    ["trap", "Trap (demand/supply)", "The amber zones where the liquidity grab happens — accumulation territory in the spec's colour system."],
  ];
  function glossaryHTML() {
    return GLOSSARY.map(([key, name, body]) =>
      `<div class="pm-gloss-item" id="gloss-${esc(key)}"><b>${esc(name)}</b><p>${esc(body)}</p></div>`).join("");
  }

  /* read-aloud (Web Speech API) — degrades silently where unsupported */
  let speakingBtn = null;
  function toggleSpeak(btn, text) {
    const synth = window.speechSynthesis;
    if (!synth) return;
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

  /* ── Watchlist (VIVEK + PhaseMap + Specs, ONE synced store) ─────────────
     Starring stores a SNAPSHOT of the record, so a name stays monitorable
     even after it drops out of the scan. Since 2026-07-03 the store lives
     INSIDE the GBSSync journal object (localStorage `gbs:manual_journal`,
     mirrored to Cloudflare KV when a sync code is set) — stars follow you
     from desktop to phone exactly like paper trades do. Keys:
     "<lens>:<market>:<TICKER>"; un-stars are tombstones so they propagate. */
  const LEGACY_LENS_KEY = "gbs-lens-watchlist";
  const LEGACY_VIVEK_KEY = "gbs:watch";
  const MIGRATED_KEY = "gbs:watch_migrated_v1";

  function _sync() { return window.GBSSync || null; }

  function _migrateOnce(d) {
    try {
      if (localStorage.getItem(MIGRATED_KEY)) return d;
      const now = Date.now();
      // old lens store: { ns: { market: { TICKER: {snap, date} } } }
      try {
        const old = JSON.parse(localStorage.getItem(LEGACY_LENS_KEY) || "{}");
        for (const [ns, mkts] of Object.entries(old || {})) {
          for (const [mkt, ticks] of Object.entries(mkts || {})) {
            for (const [t, e] of Object.entries(ticks || {})) {
              const k = `${ns}:${mkt}:${t}`;
              if (!d.watchlists[k]) d.watchlists[k] =
                { snap: (e && e.snap) || null, date: (e && e.date) || "", mtime: now };
            }
          }
        }
      } catch (_) {}
      // old VIVEK star set: [ "market:SYM", ... ]
      try {
        const old = JSON.parse(localStorage.getItem(LEGACY_VIVEK_KEY) || "[]");
        for (const mk of old || []) {
          const i = String(mk).indexOf(":");
          if (i > 0) {
            const k = `vivek:${mk.slice(0, i)}:${mk.slice(i + 1)}`;
            if (!d.watchlists[k]) d.watchlists[k] =
              { snap: null, date: "", mtime: now };
          }
        }
      } catch (_) {}
      localStorage.setItem(MIGRATED_KEY, "1");
      const s = _sync();
      if (s) { s.saveLocal(d); s.syncOutDebounced(); }
    } catch (_) {}
    return d;
  }

  function _store() {
    const s = _sync();
    if (!s) return { watchlists: {} };            // no sync layer on this page
    return _migrateOnce(s.load());
  }

  const watch = {
    map(ns, market) {
      const pre = `${ns}:${market}:`;
      const out = {};
      for (const [k, v] of Object.entries(_store().watchlists)) {
        if (k.startsWith(pre) && v && !v.del) out[k.slice(pre.length)] = v;
      }
      return out;
    },
    has(ns, market, ticker) { return !!this.map(ns, market)[ticker]; },
    count(ns, market) { return Object.keys(this.map(ns, market)).length; },
    toggle(ns, market, ticker, snap) {
      const s = _sync();
      if (!s) return false;
      const d = _store();
      const k = `${ns}:${market}:${ticker}`;
      const live = d.watchlists[k] && !d.watchlists[k].del;
      d.watchlists[k] = live
        ? { del: Date.now() }
        : { snap: snap || null, date: new Date().toISOString().slice(0, 10),
            mtime: Date.now() };
      s.saveLocal(d);
      s.syncOutDebounced();
      return !live;
    },
    refresh(ns, market, ticker, snap) {   // keep the stored snapshot current
      const s = _sync();
      if (!s) return;
      const d = _store();
      const k = `${ns}:${market}:${ticker}`;
      const e = d.watchlists[k];
      if (e && !e.del) { e.snap = snap; s.saveLocal(d); }
    },
  };

  /* ── Multi-lens confluence ──────────────────────────────────────────────
     The rare event: the SAME name with an ACTIVE setup on more than one
     lens, direction-aligned (VIVEK LONG + PhaseMap bullish + Specs = the
     full house). Computed client-side from the three latest scan files so
     it's always as fresh as whatever each lens last published. */
  const PM_ACTIVE_STATES = ["SWEPT", "DISPLACED", "RUNNING"];

  // PM leg quality — DISPLAY ORDERING ONLY (2026-08-01, owner fix #1): a
  // stronger state outranks a stronger tier, mirroring the engine's own
  // escalation. NOT part of qualification — a SWEPT/Watch leg still aligns;
  // it just sorts after RUNNING/A+ when a surface orders its chips.
  const PM_STATE_RANK = { RUNNING: 3, DISPLACED: 2, SWEPT: 1 };
  const PM_TIER_RANK = { "A+": 3, A: 2, B: 1, Watch: 0 };
  function pmLegQuality(leg) {
    if (!leg) return -1;
    return (PM_STATE_RANK[leg.state] || 0) * 10 + (PM_TIER_RANK[leg.tier] || 0);
  }
  async function loadConfluence(market, vivekData = null) {
    const grab = (url) => fetchTimeout(url, { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null)).catch(() => null);
    // Wave 2 (2026-07-22): the dashboard already holds the full VIVEK payload
    // it just rendered — callers can pass it in so the same file isn't
    // downloaded twice per load. Callers that pass nothing behave as before.
    const [vivek, pm, spec] = await Promise.all([
      vivekData ? Promise.resolve(vivekData) : grab(`data/${market}_vivek.json`),
      grab(`data/phasemap/${market}/latest.json`),
      // No crypto Specs file exists — same guard mynames.js has always used.
      market !== "crypto" ? grab(`data/${market}_spec.json`) : null,
    ]);
    const map = {};
    const ent = (t) => (map[t] = map[t] || { long: [], short: [], detail: {} });
    ((vivek && vivek.results) || []).forEach((r) => {
      const e = ent(r.symbol);
      const side = String(r.dir || "LONG").toUpperCase() === "SHORT" ? "short" : "long";
      if (!e[side].includes("VIVEK")) e[side].push("VIVEK");
      // name + sector ride along for DISPLAY (fund badge on chips) — the
      // qualification rule reads none of this.
      e.detail.vivek = { grade: r.grade, side, name: r.name, sector: r.sector };
    });
    ((pm && pm.results) || []).forEach((r) => {
      if (!PM_ACTIVE_STATES.includes(r.state)) return;
      const e = ent(r.ticker);
      const side = r.direction === "bearish" ? "short" : "long";
      if (!e[side].includes("PHASEMAP")) e[side].push("PHASEMAP");
      const leg = { state: r.state, tier: r.tier, side };
      // ~97 ASX names carry ACTIVE rows in BOTH directions. Keep the best
      // leg PER SIDE so of() can hand back the ALIGNED one — a long chip's
      // tooltip used to cite whichever row happened to load last, including
      // the bearish read (2026-08-01 fix; qualification untouched).
      e.pmBest = e.pmBest || {};
      if (pmLegQuality(leg) > pmLegQuality(e.pmBest[side])) e.pmBest[side] = leg;
      e.detail.phasemap = leg;
    });
    ((spec && spec.results) || []).forEach((r) => {
      const e = ent(r.symbol);
      if (!e.long.includes("SPECS")) e.long.push("SPECS");
      e.detail.specs = { grade: r.grade };
    });
    return {
      of(ticker) {
        const e = map[ticker];
        if (!e) return null;
        const side = e.long.length >= e.short.length ? "long" : "short";
        const lenses = e[side];
        if (lenses.length < 2) return null;
        const detail = e.pmBest && e.pmBest[side]
          ? Object.assign({}, e.detail, { phasemap: e.pmBest[side] })
          : e.detail;
        return { ticker, lenses, side, count: lenses.length, detail };
      },
      all() {
        return Object.keys(map)
          .map((t) => this.of(t))
          .filter(Boolean)
          .sort((a, b) => b.count - a.count || a.ticker.localeCompare(b.ticker));
      },
    };
  }

  /* Banner body shared by the dashboard and the lens pages: capped list of
     aligned names, triples as pulsing beacons, links to the combined chart. */
  function confluenceBannerHTML(rows, market, cap = 10) {
    if (!rows || !rows.length) return "";
    return `<span class="conf-banner-label">⨂ MULTI-LENS ALIGNMENT</span>` +
      rows.slice(0, cap).map((x) => {
        const dir = x.side === "short" ? "&dir=bearish" : "&dir=bullish";
        const arrow = x.side === "short" ? "▼" : "▲";
        const cls = x.count >= 3 ? "pm-conf pm-conf-3" : "";
        const tag = x.count >= 3 ? "🎯 " : "";
        return `<a class="${cls}" title="${esc(x.lenses.join(" + "))} — open the combined chart" ` +
          `href="chart.html?m=${market}&s=${encodeURIComponent(x.ticker)}&pm=1${dir}">` +
          `${tag}${esc(x.ticker)} ${arrow}${x.count >= 3 ? " ×3" : ""}</a>`;
      }).join("") +
      (rows.length > cap ? `<span style="color:var(--muted)">+${rows.length - cap} more</span>` : "");
  }

  /* ONE timestamp convention (2026-07-05): every scan stamp renders in
     Melbourne time — the owner's clock. Market-local time goes in tooltips
     via the caller, never as the primary display. */
  function fmtMelb(iso) {
    try {
      const d = new Date(iso);
      if (isNaN(d)) return String(iso || "");
      return d.toLocaleString("en-AU", {
        timeZone: "Australia/Melbourne",
        weekday: "short", day: "numeric", month: "short",
        hour: "numeric", minute: "2-digit",
      }) + " Melb";
    } catch (_) { return String(iso || ""); }
  }

  /* Staleness: lens data refreshes nightly — shout when it's older than that.
     Accepts 'YYYY-MM-DD' (PhaseMap run_date) or a full ISO stamp (Specs). */
  function staleBadgeHTML(stamp) {
    if (!stamp) return "";
    const t = Date.parse(String(stamp).length <= 10 ? stamp + "T00:00:00" : stamp);
    if (!isFinite(t)) return "";
    const hours = (Date.now() - t) / 3600000;
    const limit = String(stamp).length <= 10 ? 48 : 30;   // date-only gets a day's grace
    if (hours < limit) return "";
    const days = Math.floor(hours / 24);
    const age = days >= 2 ? `${days} DAYS` : `${Math.round(hours)}H`;
    return ` <span class="pm-stale-badge" title="This lens refreshes nightly — the last ` +
      `successful scan is older than expected. A weekend or market holiday is ` +
      `the usual benign cause; if it is a weekday, check the GitHub Actions runs.">` +
      `⚠ SCAN ${age} OLD</span>`;
  }

  function confluenceChipHTML(info, currentLens) {
    if (!info) return "";
    const others = info.lenses.filter((l) => l !== currentLens);
    if (!others.length) return "";
    const triple = info.count >= 3;
    return `<span class="pm-conf${triple ? " pm-conf-3" : ""}" ` +
      `title="Multiple independent lenses have an ACTIVE ${info.side} setup on this ` +
      `name right now — rare alignment, review every view">` +
      `${triple ? "🎯 " : "⨂ "}${info.count}-LENS · +${others.join(" +")}</span>`;
  }

  function starHTML(on, ticker) {
    return `<button class="pm-star${on ? " is-on" : ""}" data-star="${esc(ticker)}" ` +
      `title="${on ? "Remove from" : "Add to"} watchlist — starred names stay ` +
      `monitored even after the setup ends" aria-label="Toggle watchlist">` +
      `${on ? "★" : "☆"}</button>`;
  }

  /* Data-fetch timeout (2026-07-29, Phase B). A NETWORK FAILURE rejects and
   * lands in the cold-load retry states below — but a HUNG connection neither
   * resolves nor rejects, and was the one remaining mechanism that could
   * leave the deck on "Loading latest scan…" forever. Every scan/data load
   * now carries an abort signal so a hang BECOMES a rejection and takes the
   * same honest retry path as any other failure.
   *
   * 20s: the ASX payload is ~2MB (≈0.5MB compressed) and a slow-3G phone
   * legitimately needs 10–15s — a tighter limit would abort real progress on
   * the exact devices that most need the data. Feature-detected: a browser
   * without AbortSignal.timeout gets the old no-timeout behaviour rather
   * than a synchronous throw on every fetch.
   *
   * KEEP IN STEP with the inline copy in index.html's head-start preload —
   * that script runs before this file loads and cannot use PM; a test pins
   * the two numbers to each other. */
  const DATA_FETCH_TIMEOUT_MS = 20000;

  function fetchTimeout(url, opts, ms) {
    const t = ms || DATA_FETCH_TIMEOUT_MS;
    const canTime = typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function";
    return fetch(url, canTime ? { ...(opts || {}), signal: AbortSignal.timeout(t) } : (opts || {}));
  }

  /* Cold-load failure classification (2026-07-29). Every lens page's
   * first-load catch used to say "No scan yet — run the scanner", which
   * misdiagnoses the failures that actually happen in the field: the USER'S
   * connection is down (phone, train, cafe wifi) or the CDN hiccuped — cases
   * where the data exists and "run the scanner" is wrong twice over, and where
   * the honest answer is a retry button, not a shrug. Only a 404 means the
   * artefact is genuinely missing; everything else — network throw, 5xx,
   * empty message — is "unreachable" and worth retrying.
   *
   * The two message shapes it has to read (both real, do not "simplify"):
   *   app.js               throw new Error(res.status)   → "404"
   *   phasemap.js/specs.js throw new Error("HTTP " + s)  → "HTTP 404"
   */
  function loadFailKind(err) {
    const m = /(\d{3})$/.exec(String((err && err.message) || "").trim());
    return m && +m[1] === 404 ? "missing" : "unreachable";
  }

  // One retry control everywhere (reuses the market-btn pill so no CSS ships).
  // Pages wire the click themselves — an onclick string would be an eval sink.
  function retryHTML(id) {
    return `<button type="button" class="market-btn pm-retry" id="${esc(id)}">` +
      `Tap to retry</button>`;
  }

  return { fmtPrice, fmtPct, fmtTurnover, esc, srcText, zoneLabel,
           ladderHTML, metricsHTML, headBadgesHTML, identityHTML,
           stepperHTML, whyHTML, glossaryHTML,
           isFundReit, toggleSpeak, watch, starHTML,
           loadConfluence, confluenceChipHTML, confluenceBannerHTML,
           staleBadgeHTML, fmtMelb, loadFailKind, retryHTML,
           fetchTimeout, DATA_FETCH_TIMEOUT_MS, pmLegQuality };
})();
