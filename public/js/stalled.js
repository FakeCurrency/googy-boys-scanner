/* STALLED — the position decision surface (2026-08-01).

   Renders the positions the stale probe has already flagged (`stale_pinged`,
   stamped by scanner/broker/vivek_run._stale_probe) into #stalled-strip at the
   top of journal.html, so the owner can see exactly what is locking capacity
   and make an explicit call.

   WHY IT EXISTS. The probe's Discord ping is a moment; this is the standing
   answer to "what is squatting my slots right now". The two automatic rules
   leave a gap on purpose — MAX_HOLD_DAYS only time-stops pre-TP1 stalls, and a
   runner past TP1 is exempt from it forever — so a +0.1R runner can hold one
   of 30 scarce slots for months with nothing on any page saying so. With the
   book at its global cap, every stalled row is a new A+ the bot must decline.

   READ-ONLY BY CONSTRUCTION. This file fetches two published artifacts
   (data/vivek_bot_book.json, data/bot_rules.json) and writes DOM. It defines
   no thresholds of its own — a row is stalled if and only if the engine
   stamped it — and it has no write path into the bot, the book, or any store:
   no POST, no dispatch, no localStorage. Closing anything stays 100% manual
   (close_position.yml, journal_type=bot). test/stalled.test.js pins all of
   this against the shipped source. */
(() => {
  "use strict";

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ── the cohort ─────────────────────────────────────────────────────────────
  // The engine's mark is the whole definition. `status === "open"` is belt and
  // braces (the probe only stamps open rows, and a close never carries the
  // stamp forward), and a row that started moving again LOSES its stamp on the
  // next scan — so this list is exactly the probe's current cohort, never a
  // memory of it.
  const stalledRows = (book) =>
    ((book && book.open) || []).filter((p) => p && p.status === "open" && p.stale_pinged);

  // Day arithmetic in the BOOK's own calendar, not the browser's. The probe
  // computed "held" against the scan day, and `summary.updated_day` is that
  // day as of the last time the engine touched the book — so the numbers here
  // reproduce the probe's rather than drifting overnight with the viewer's
  // clock. Date-only ISO strings parse as UTC midnight by spec, so the
  // subtraction is timezone-proof.
  const daysBetween = (a, b) => {
    const ta = Date.parse(String(a || "")), tb = Date.parse(String(b || ""));
    if (!isFinite(ta) || !isFinite(tb)) return null;
    return Math.round((tb - ta) / 86400000);
  };

  const bookDay = (book) => {
    const d = book && book.summary && book.summary.updated_day;
    if (d && isFinite(Date.parse(d))) return d;
    return new Date().toISOString().slice(0, 10);   // first-load fallback only
  };

  // ── "your call" framing ────────────────────────────────────────────────────
  // Three outcomes exist and all three are the owner's: keep it, let the 28d
  // time-stop take it (pre-TP1 only), or close it in the book to free the
  // slot. This function only says which of those apply to a row — it does
  // nothing about any of them.
  const framing = (pos, held, maxHold) => {
    if (pos.tp1_hit) {
      return {
        kind: "runner",
        label: "runner · no auto-exit",
        detail: "Past TP1, so the " + (maxHold || 28) + "d time-stop never applies. " +
          "Keep it, or close it in the book — a manual close is the only thing that frees this slot.",
      };
    }
    const left = (maxHold != null && held != null) ? maxHold - held : null;
    const due = left != null && left <= 0;
    return {
      kind: due ? "due" : "timed",
      label: due ? "time-stop due" : ("time-stop in " + left + "d"),
      detail: "Pre-TP1. Keep it, let the " + (maxHold || 28) + "d time-stop close it" +
        (due ? " (due now)" : " in " + left + " day" + (left === 1 ? "" : "s")) +
        ", or close it in the book now to free the slot.",
    };
  };

  // ── the summary line ───────────────────────────────────────────────────────
  // Slots are the number that matters: the cap is global, so a full book
  // declines every new A+ before a quality check runs, and the stalled rows
  // are the reclaimable share of it. Risk is stated in both currencies the
  // book itself uses — combined R (comparable across the 2026-07-28 resize)
  // and dollars-at-risk as a share of equity.
  const summarize = (rows, book, rules) => {
    const fin = (v) => (typeof v === "number" && isFinite(v)) ? v : null;
    const totalR = rows.reduce((s, p) => s + (fin(p.unreal_r) || 0), 0);
    const riskUsd = rows.reduce((s, p) => s + (fin(p.risk_usd) || 0), 0);
    const equity = fin(rules && rules.account_equity);
    const maxOpen = fin(rules && rules.max_open_total) || fin(rules && rules.max_positions);
    const open = ((book && book.open) || []).filter((p) => p && p.status === "open").length;
    const free = maxOpen != null ? Math.max(0, maxOpen - open) : null;
    return {
      n: rows.length, totalR, riskUsd,
      riskPct: equity ? 100 * riskUsd / equity : null,
      open, maxOpen, free, atCap: maxOpen != null && open >= maxOpen,
    };
  };

  // ── render ─────────────────────────────────────────────────────────────────
  const fmtR = (v) => (typeof v === "number" && isFinite(v))
    ? (v >= 0 ? "+" : "") + v.toFixed(2) + "R" : "—";
  const money = (n) => "$" + Math.round(n).toLocaleString("en-US");
  const MKT = { asx: "ASX", nasdaq: "NASDAQ", crypto: "CRYPTO" };

  const slotsClause = (s) => {
    if (s.maxOpen == null) return "occupying " + s.n + " book slot" + (s.n === 1 ? "" : "s");
    const base = "occupying <b>" + s.n + " of " + s.maxOpen + "</b> A+ slots";
    if (s.atCap) {
      return base + " — book <b>FULL</b>, so these are the only slots a new A+ can come from";
    }
    return base + " (" + s.free + " free besides)";
  };

  const rowHTML = (pos, day, maxHold) => {
    const held = daysBetween(pos.entry_date, day);
    const marked = daysBetween(pos.stale_pinged, day);
    const f = framing(pos, held, maxHold);
    const ur = (typeof pos.unreal_r === "number" && isFinite(pos.unreal_r)) ? pos.unreal_r : null;
    return `<div class="st-row st-${f.kind}">
      <span class="st-sym"><b>${esc(String(pos.symbol || "?").toUpperCase())}</b>
        <em>${esc(MKT[pos.market] || String(pos.market || "").toUpperCase())}</em></span>
      <span class="st-days" title="Held ${held == null ? "?" : held} days since entry on ${esc(pos.entry_date || "?")}; the stale probe last flagged it ${marked == null ? "?" : marked} day(s) ago (${esc(pos.stale_pinged)}).">
        ${held == null ? "—" : held + "d"} <em>held</em> · flagged ${marked == null ? "—" : marked + "d"} ago</span>
      <span class="st-r ${ur == null ? "" : ur >= 0 ? "st-up" : "st-down"}">${fmtR(ur)}</span>
      <span class="st-grade">${esc(pos.grade || "—")}</span>
      <span class="st-call" title="${esc(f.detail)}">${esc(f.label)}</span>
    </div>`;
  };

  function render(host, book, rules) {
    const rows = stalledRows(book);
    if (!rows.length) { host.hidden = true; host.innerHTML = ""; return; }
    const day = bookDay(book);
    const maxHold = rules && typeof rules.max_hold_days === "number" ? rules.max_hold_days : 28;
    const s = summarize(rows, book, rules);
    // Longest-held first: the row that has been asking for a decision longest
    // is the one the summary is really about.
    const ordered = rows.slice().sort((a, b) =>
      (daysBetween(b.entry_date, day) || 0) - (daysBetween(a.entry_date, day) || 0));
    host.hidden = false;
    host.innerHTML = `
      <div class="st-head">
        <span class="st-tag">⏳ STALLED</span>
        <span class="st-sum"><b>${s.n}</b> position${s.n === 1 ? "" : "s"} sitting still
          · <b>${fmtR(s.totalR)}</b> combined
          · <b>${money(s.riskUsd)}</b> at risk${s.riskPct != null ? " (" + s.riskPct.toFixed(1) + "% of equity)" : ""}
          · ${slotsClause(s)}</span>
      </div>
      <div class="st-rows">
        <div class="st-row st-cols"><span>Name</span><span>Stall</span><span>Open R</span><span>Grade</span><span>Your call</span></div>
        ${ordered.map((p) => rowHTML(p, day, maxHold)).join("")}
      </div>
      <p class="st-foot">Flagged by the stale probe (≥2 weeks open, minimal movement) — going nowhere is
        a decision too. Read-only: nothing here closes anything. Keep a name, let a pre-TP1 time-stop
        take it, or free the slot yourself via <b>Close position</b> (journal_type=bot).</p>`;
  }

  // ── mount ──────────────────────────────────────────────────────────────────
  // #88 discipline: the catch is scoped to the fetch and parse only — hiding
  // the strip is the right answer to "the file is not there", and the wrong
  // answer to a renderer fault, which must reach window.onerror instead.
  const report = (err) => { setTimeout(() => { throw err; }, 0); };

  const host = document.getElementById("stalled-strip");
  if (host) {
    const get = (url) => ((window.PM && PM.fetchTimeout) ? PM.fetchTimeout : fetch)(url, { cache: "no-cache" })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });
    Promise.all([
      get("data/vivek_bot_book.json"),
      // Rules are a degrade, not a dependency: without them the strip still
      // lists the cohort, it just cannot name the cap or the equity share.
      get("data/bot_rules.json").catch(() => null),
    ])
      .catch(() => { host.hidden = true; return null; })
      .then((got) => {
        if (!got) return;
        try { render(host, got[0], got[1]); } catch (err) { host.hidden = true; report(err); }
      });
  }
})();
