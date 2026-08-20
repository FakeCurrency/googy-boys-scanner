/* REGIME — what the tape is doing underneath the index, and who is beating it.

   Renders public/data/regime.json in two places from one implementation:

     · #regime-strip (index.html)  — one line: the participation state, whether
       the index is lying about it, and the relative-strength leader with the
       number of straight sessions it has led for.
     · #regime-panel (sectors.html) — the full board: participation, the
       divergence between the median name and the index, every sector ranked by
       RELATIVE strength, and how many names in each are coiling at their
       200-day average without having triggered yet.

   WHY IT EXISTS, and why it is not part of HORIZON. HORIZON ranks sectors by
   PARTICIPATION RATE: how many of a sector's names are set up right now. That
   is an absolute measure. It cannot express "the market has been shit to trade
   yet consumer discretionaries went up", because nothing in it compares a
   sector to the rest of the market — and that sentence is what a rotation IS.
   These two boards are deliberately separate and deliberately ordered
   differently: merging them into one table with extra columns would imply a
   single ranking, and there isn't one. A sector can lead on RS while its own
   setups are thin (it has already run) or lead on participation while lagging
   on RS (everything is basing because everything fell).

   THE NUMBER THIS SURFACE EXISTS FOR is the streak: not "consumer
   discretionaries are strong today" but "they have been top three for
   thirty-one straight sessions". Unlike HORIZON's streaks, which had to start
   counting the day that module shipped, this one is recomputed from six months
   of bars on every run — so it was correct about June on its first execution.

   Report-only, like the module behind it: it changes what is visible, never
   what gets taken. */
(() => {
  "use strict";

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (v) => v == null ? "—" : Math.round(100 * v) + "%";
  const sgn = (v) => v == null ? "—" : (v >= 0 ? "+" : "") + (100 * v).toFixed(1) + "%";
  const cls = (v) => v == null ? "" : (v >= 0 ? "rg-up" : "rg-down");

  const MARKETS = { asx: "ASX", nasdaq: "NASDAQ" };

  // The three-way read, spelled out. A label nobody can translate is a label
  // nobody acts on, so each carries the instruction it implies rather than
  // leaving "NARROW" to be interpreted at the moment it matters least.
  const STATE = {
    BROAD:   { tag: "BROAD",   say: "most of the market is participating" },
    MIXED:   { tag: "MIXED",   say: "participation is patchy — the average name is not the story" },
    NARROW:  { tag: "NARROW",  say: "few names are in uptrends; leadership is thin" },
    UNKNOWN: { tag: "NO READ", say: "not enough history to judge participation yet" },
  };

  function activeMarket() {
    try {
      const q = new URLSearchParams(location.search).get("m");
      if (q && MARKETS[q.toLowerCase()]) return q.toLowerCase();
    } catch (_) {}
    const btn = document.querySelector(".market-btn.is-active");
    const fromBtn = btn && String(btn.dataset.market || "").toLowerCase();
    if (fromBtn) return fromBtn;
    try {
      return String(JSON.parse(localStorage.getItem("gbs:prefs") || "{}").market || "asx").toLowerCase();
    } catch (_) { return "asx"; }
  }

  // Sectors ranked by rs21, most recent session. Unranked sectors (too few
  // listed names, or no return window yet) are dropped rather than shown at the
  // bottom: on this board a missing rank means "not measurable", which is a
  // different thing from "last", and the leaderboard is short enough that the
  // distinction would be lost.
  function ranked(blk) {
    return Object.entries(blk.sectors || {})
      .filter(([, v]) => v.rank && v.latest && v.latest.rs21 != null)
      .sort((a, b) => a[1].rank - b[1].rank)
      .map(([name, v]) => ({ name, ...v }));
  }

  // ── divergence: the July sentence as a number ──────────────────────────────
  function divergenceHTML(blk) {
    const lat = blk.latest || {};
    if (lat.divergence == null) return "";
    const wide = Math.abs(lat.divergence) >= 0.02;
    const lead = lat.divergence > 0
      ? "The index is understating the tape"
      : "The index is being carried by its biggest names";
    return `<div class="rg-div${wide ? " is-wide" : ""}">
      <span class="rg-div-lbl">${esc(lead)}</span>
      <span class="rg-div-num">median name <b class="${cls(lat.median_ret21)}">${sgn(lat.median_ret21)}</b>
        · ${esc(blk.bench || "index")} <b class="${cls(lat.bench_ret21)}">${sgn(lat.bench_ret21)}</b>
        · gap <b class="${cls(lat.divergence)}">${sgn(lat.divergence)}</b></span>
    </div>`;
  }

  // ── participation meters ───────────────────────────────────────────────────
  // Breadth STRETCH (batch-100 WS-E). "67% above the 200-day" reads as a
  // fact; against its own published history it reads as a position: the
  // 2026-08-20 tide analysis measured that a plain reversion of breadth to
  // its mean takes back over half the open book's unrealized R without one
  // stop firing — so how stretched the tape is belongs beside the meter.
  // Computed client-side from the SAME series the panel already ships;
  // silent below 40 sessions (a percentile over a fortnight is a guess).
  function stretchHTML(blk) {
    const s = (blk.above200 || []).filter((v) => typeof v === "number" && isFinite(v));
    const cur = (blk.latest || {}).above200;
    if (s.length < 40 || typeof cur !== "number") return "";
    const mean = s.reduce((a, b) => a + b, 0) / s.length;
    // Midrank percentile: ties count half. A `<=` rank reads a FLAT series as
    // being at its own 90th+ percentile, which is how a calm tape would get
    // painted STRETCHED — found by test, not by reading.
    const below = s.filter((v) => v < cur).length;
    const equal = s.filter((v) => v === cur).length;
    const pctl = Math.round(100 * (below + 0.5 * equal) / s.length);
    const word = pctl >= 90 ? "STRETCHED" : pctl >= 70 ? "elevated"
      : pctl <= 10 ? "washed out" : pctl <= 30 ? "soft" : "ordinary";
    return `<div class="rg-stretch${pctl >= 90 ? " is-hot" : ""}" ` +
      `title="Share of names above their 200-day, ranked inside this panel's own ${s.length}-session history. High percentile = most names already repaired = less fuel and more tide under the open book; the reversion-to-mean cost is what the journal's tide line prices.">` +
      `breadth stretch: <b>${pct(cur)}</b> now vs <b>${pct(mean)}</b> ${s.length}-session mean · ` +
      `<b>${pctl}th</b> percentile — ${word}</div>`;
  }

  function metersHTML(blk) {
    const lat = blk.latest || {};
    const w = blk.windows || {};
    const bars = [
      ["Above the " + (w.sma_slow || 200) + "-day", lat.above200],
      ["Above the " + (w.sma_fast || 50) + "-day", lat.above50],
    ];
    return `<div class="rg-meters">
      ${bars.map(([label, v]) => `<div class="rg-meter">
        <div class="rg-meter-top"><span>${esc(label)}</span><b>${pct(v)}</b></div>
        <div class="rg-meter-bar"><i style="width:${Math.max(0, Math.min(100, 100 * (v || 0)))}%"></i></div>
      </div>`).join("")}
      <div class="rg-meter">
        <div class="rg-meter-top"><span>New ${w.hl || 20}-day highs − lows</span>
          <b class="${cls(lat.net_hl)}">${sgn(lat.net_hl)}</b></div>
        <div class="rg-meter-bar rg-meter-mid"><i class="${cls(lat.net_hl)}"
          style="width:${Math.min(50, Math.abs(100 * (lat.net_hl || 0)))}%;${
            (lat.net_hl || 0) >= 0 ? "left:50%" : "right:50%"}"></i></div>
      </div>
    </div>`;
  }

  // ── the RS leaderboard ─────────────────────────────────────────────────────
  function rowsHTML(blk) {
    const rows = ranked(blk);
    if (!rows.length) {
      return `<p class="rg-empty">No sector has enough listed names and history to rank yet.</p>`;
    }
    const top = Math.max(...rows.map((r) => Math.abs(r.latest.rs21 || 0)), 0.0001);
    const w = blk.windows || {};
    return `<div class="rg-rows">
      <div class="rg-row rg-head">
        <span></span><span>Sector</span><span>vs market (1m)</span>
        <span>3m</span><span>Coiling</span><span>Run</span>
      </div>
      ${rows.map((r) => {
        const rs = r.latest.rs21 || 0;
        const run = r.streak || 0;
        const width = Math.min(48, 48 * Math.abs(rs) / top);
        return `<div class="rg-row${r.rank <= 3 ? " is-lead" : ""}">
          <span class="rg-rank">${r.rank}</span>
          <span class="rg-sec"><b>${esc(r.name)}</b></span>
          <span class="rg-bar" title="${esc(r.name)} median name ${sgn(r.latest.ret21)} over the last month, against the market median">
            <i class="${cls(rs)}" style="width:${width}%;${rs >= 0 ? "left:50%" : "right:50%"}"></i>
            <b class="${cls(rs)}">${sgn(rs)}</b></span>
          <span class="rg-num ${cls(r.latest.rs63)}">${sgn(r.latest.rs63)}</span>
          <span class="rg-coil" title="${esc(r.latest.near)} of ${esc(r.names)} names within ${
            Math.round(100 * (w.near_tol || 0.04))}% of their ${w.sma_slow || 200}-day average and not yet triggered">
            ${r.latest.near || 0}<em>/${r.names}</em></span>
          <span class="rg-run${run > 4 ? " is-hot" : ""}">${run > 1 ? run + "d" : "—"}</span>
        </div>`;
      }).join("")}
    </div>`;
  }

  function notesHTML(blk) {
    const notes = blk.notes || [];
    if (!notes.length) return "";
    return `<div class="rg-notes">${notes.map((n, i) =>
      `<p class="rg-note${i === 0 ? " rg-lead-note" : ""}">${esc(n)}</p>`).join("")}</div>`;
  }

  // ── full panel (sectors.html) ──────────────────────────────────────────────
  function renderPanel(host, data) {
    const blocks = data.markets || {};
    const keys = Object.keys(MARKETS).filter((k) => blocks[k] && (blocks[k].days || []).length);
    if (!keys.length) { host.hidden = true; return; }
    host.hidden = false;
    const w0 = (blocks[keys[0]] || {}).windows || {};
    const worst = keys.map((k) => (blocks[k].latest || {}).state);
    host.className = "rg-panel" + (worst.includes("NARROW") ? " is-narrow"
      : worst.every((s) => s === "BROAD") ? " is-broad" : "");
    host.innerHTML = `
      <div class="rg-top">
        <h3 class="rg-title">REGIME <span>— what the tape is doing underneath the index</span></h3>
        <p class="rg-sub">Participation, the gap between the median name and the index, and
          sectors ranked by <b>relative</b> strength — how each is doing against the rest of the
          market, not on its own. Recomputed from six months of bars every run.</p>
      </div>
      <div class="rg-cols">${keys.map((k) => {
        const blk = blocks[k];
        const st = STATE[(blk.latest || {}).state] || STATE.UNKNOWN;
        return `<section class="rg-col">
          <div class="rg-col-head">
            <span>${k === "asx" ? "🇦🇺" : "🇺🇸"}</span>
            <h4>${esc(MARKETS[k])}</h4>
            <span class="rg-state rg-${String((blk.latest || {}).state || "unknown").toLowerCase()}">${esc(st.tag)}</span>
            <span class="rg-col-meta">${esc(st.say)}</span>
          </div>
          ${divergenceHTML(blk)}
          ${metersHTML(blk)}
          ${stretchHTML(blk)}
          ${rowsHTML(blk)}
          ${notesHTML(blk)}
          <p class="rg-src">${blk.covered} of ${blk.universe_size} names priced ·
            ${(blk.days || []).length} sessions to ${esc((blk.days || []).slice(-1)[0] || "")}</p>
        </section>`;
      }).join("")}</div>
      <p class="rg-disclaimer">Report-only — nothing here changes which trades the bot takes.
        <b>Coiling</b> counts names sitting within ${Math.round(100 * (w0.near_tol || 0.04))}%
        of their ${w0.sma_slow || 200}-day average that have <em>not</em> triggered yet — the pool
        every setup is drawn from, so it leads the setup count rather than tracking it.
        <b>Run</b> is consecutive sessions in the top ${w0.top_n || 3} on one-month relative
        strength. Universe is today's listed names, so delisted companies are absent from
        historical readings — which flatters them slightly.</p>`;
  }

  // ── compact strip (index.html) ─────────────────────────────────────────────
  function renderStrip(host, data) {
    const blk = (data.markets || {})[activeMarket()];
    if (!blk || !(blk.days || []).length) { host.hidden = true; host.innerHTML = ""; return; }
    const lat = blk.latest || {};
    const st = STATE[lat.state] || STATE.UNKNOWN;
    const lead = ranked(blk)[0];
    const wide = lat.divergence != null && Math.abs(lat.divergence) >= 0.02;
    host.hidden = false;
    host.className = "rg-strip" + (lat.state === "NARROW" ? " is-narrow"
      : lat.state === "BROAD" ? " is-broad" : "");
    host.innerHTML = `
      <div class="rg-strip-line">
        <span class="rg-strip-tag rg-${String(lat.state || "unknown").toLowerCase()}">${esc(st.tag)}</span>
        <span class="rg-strip-part"><b>${pct(lat.above200)}</b> above the
          ${(blk.windows || {}).sma_slow || 200}-day${(() => {
            // the strip gets the percentile only — one number, hover for words
            const s = (blk.above200 || []).filter((v) => typeof v === "number" && isFinite(v));
            if (s.length < 40 || typeof lat.above200 !== "number") return "";
            // midrank, same as stretchHTML — ties count half
            const p = Math.round(100 * (s.filter((v) => v < lat.above200).length
              + 0.5 * s.filter((v) => v === lat.above200).length) / s.length);
            return ` <i class="rg-strip-pctl${p >= 90 ? " is-hot" : ""}" title="Percentile of today's breadth inside this panel's own ${s.length}-session history — high means stretched, and stretched is what the journal's tide line prices.">p${p}</i>`;
          })()}</span>
        ${wide ? `<span class="rg-strip-div ${cls(lat.divergence)}"
          title="The median name against ${esc(blk.bench || "the index")} over the last month">
          median name <b>${sgn(lat.median_ret21)}</b> vs ${esc(blk.bench || "index")}
          <b>${sgn(lat.bench_ret21)}</b></span>` : ""}
        ${lead ? `<a class="rg-strip-lead" href="sectors.html#regime-panel"
          title="${esc(lead.name)} is beating the market median by ${sgn(lead.latest.rs21)} over the last month">
          <em>leads</em> ${esc(lead.name)} <b>${sgn(lead.latest.rs21)}</b>${
            (lead.streak || 0) > 1 ? `<i>${lead.streak} sessions</i>` : ""}</a>` : ""}
        <a class="rg-strip-more" href="sectors.html#regime-panel">Regime →</a>
      </div>
      ${(blk.notes || []).length ? `<div class="rg-strip-note">${esc(blk.notes[0])}</div>` : ""}`;
  }

  // ── mount ──────────────────────────────────────────────────────────────────
  // TOP100 #88, identical shape and identical cause to horizon.js — see the
  // long note there. In short: the payload is module-scoped rather than
  // captured by the listener closure, a renderer fault is reported instead of
  // being mistaken for a missing file, and the two surfaces fail independently
  // (mount draws the panel first, so a strip that threw used to hide a panel
  // that had rendered fine).
  let DATA = null;
  let BOUND = false;

  // Async re-raise so telemetry.js's window.onerror beacon records it, while
  // staying outside this call stack and outside the fetch chain.
  function report(err) { setTimeout(() => { throw err; }, 0); }

  function draw(id, fn) {
    const el = document.getElementById(id);
    if (!el) return;
    try { fn(el, DATA); } catch (err) { report(err); }
  }

  function render() {
    if (!DATA) return;
    // Panel columns every market in the payload and never reads activeMarket();
    // only the strip moves on a switch. Drawn together anyway so render() means
    // "everything, from DATA" and stays right when DATA is what changes.
    draw("regime-panel", renderPanel);
    draw("regime-strip", renderStrip);
  }

  function mount(data) {
    DATA = data;
    render();
    if (BOUND) return;
    const btns = document.querySelectorAll(".market-btn");
    if (!btns.length) return;   // sectors.html ships no switch; its panel needs none
    BOUND = true;
    btns.forEach((b) => b.addEventListener("click", () => setTimeout(render, 0)));
  }

  ((window.PM && PM.fetchTimeout) ? PM.fetchTimeout : fetch)("data/regime.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    // Scoped to the FETCH AND PARSE ONLY — hiding the surface answers "the file
    // is not there", and nothing else.
    .catch(() => {
      // Silent: a secondary surface must never disturb the page it sits on, and
      // this file does not exist until the first scan after it shipped.
      ["regime-panel", "regime-strip"].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.hidden = true;
      });
      return null;
    })
    .then((data) => { if (data) mount(data); });
})();
