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

   ONE WRITE PATH, AND IT IS THE OWNER'S FINGER (owner-ruled 2026-08-07).
   Nothing here decides. No threshold, no timer, no condition in this file
   closes anything — a row is stalled if and only if the engine stamped it,
   and nothing is sent until a human has done TWO deliberate things: picked
   the row(s), then pressed the one confirm control that names exactly what
   it is about to do.

   ONE RUN FOR THE LOT (2026-08-13, owner: "close each one FAST"). The first
   version sent one workflow run per close and serialised them, which was
   correct about the collision and wrong about the unit of work: the collision
   was never between CLOSES, it was between concurrent RUNS racing the same
   book files through the scan mutex. Nine closes as nine runs is nine
   dispatch->run->deploy round trips (~half an hour of watching "waiting…");
   nine closes as ONE batch run is one checkout, one commit, one deploy —
   roughly the wall-clock of one. So the strip now collects picks and sends
   them as a single POST, and the pipeline closes them sequentially
   in-process where there is no race to lose.

   The clauses every future edit must preserve:

     * NOTHING HERE DECIDES — see above. Picking is a human act per row; the
       confirm states the count and the prices come from the rows themselves.
     * The write is exactly one call, POST /api/close, with journal_type
       hard-coded "bot". One request regardless of how many rows are picked.
       That endpoint is the pre-existing, validated, rate-limited dispatcher;
       this file adds a caller, not a capability.
     * Each row books at its OWN last_mark — the number the Open R beside it
       is computed from, so what you read is what you book — and the confirm
       bar totals are derived from those same marks. A row with no usable
       mark cannot be picked at all (fail-closed: no honest price, no pick).
     * "closed ✓" is only ever claimed once the symbol is actually gone from
       the PUBLISHED book. A 202 is an accepted dispatch, not a landed close —
       that gap is where six closes went missing on 2026-08-07 — so the strip
       polls the same artifact the whole page reads and settles each row
       individually. Entries the batch run skipped (say a time-stop beat us
       to one) never leave the open book and honestly time out to
       "check the book".
     * Still no localStorage, no sessionStorage, no KV, no second endpoint.

   test/stalled.test.js pins every clause above against the shipped source. */
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

  // ── render helpers ─────────────────────────────────────────────────────────
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

  // The price a close from this strip books at. The row's OWN last_mark, which
  // is the number `unreal_r` beside it was computed from — so the R you are
  // looking at when you decide is the R you get. FAIL-CLOSED: no finite
  // positive mark means no honest price, which means no pick, not a guess.
  const closePrice = (pos) => {
    const v = pos && pos.last_mark;
    return (typeof v === "number" && isFinite(v) && v > 0) ? v : null;
  };
  const fmtPx = (v) => "$" + v.toFixed(v < 1 ? 4 : 2);

  const tipFor = (sym, px) => "Pick " + sym + " to close in the bot book at its last mark, " +
    fmtPx(px) + ". Nothing is sent by picking - only the Close bar's confirm sends, " +
    "as ONE batch for everything picked.";

  const closeCell = (pos) => {
    const px = closePrice(pos);
    if (px == null) {
      return `<span class="st-x st-x-off" title="This row carries no usable last mark, so there is no honest price to book a close at. Close it via the close_position workflow (journal_type=bot) instead.">no price</span>`;
    }
    const sym = String(pos.symbol || "").toUpperCase();
    return `<button type="button" class="st-x" data-sym="${esc(sym)}"
      data-mkt="${esc(String(pos.market || "").toLowerCase())}"
      data-dir="${esc(pos.direction === "short" ? "short" : "long")}"
      data-px="${esc(String(px))}"
      title="${esc(tipFor(sym, px))}">Close</button>`;
  };

  const rowHTML = (pos, day, maxHold) => {
    const held = daysBetween(pos.entry_date, day);
    const marked = daysBetween(pos.stale_pinged, day);
    const f = framing(pos, held, maxHold);
    const ur = (typeof pos.unreal_r === "number" && isFinite(pos.unreal_r)) ? pos.unreal_r : null;
    const sym = String(pos.symbol || "?").toUpperCase();
    // The ticker opens the chart, same convention as every other surface in the
    // app (app.js, alerts.js): chart.html?m=<market>&s=<SYM>&mode=vivek.
    const href = `chart.html?m=${encodeURIComponent(String(pos.market || ""))}&s=${encodeURIComponent(sym)}&mode=vivek`;
    return `<div class="st-row st-${f.kind}" data-row="${esc(sym)}">
      <span class="st-sym"><a class="st-chart" href="${esc(href)}" title="Open the ${esc(sym)} chart"><b>${esc(sym)}</b></a>
        <em>${esc(MKT[pos.market] || String(pos.market || "").toUpperCase())}</em></span>
      <span class="st-days" title="Held ${held == null ? "?" : held} days since entry on ${esc(pos.entry_date || "?")}; the stale probe last flagged it ${marked == null ? "?" : marked} day(s) ago (${esc(pos.stale_pinged)}).">
        ${held == null ? "—" : held + "d"} <em>held</em> · flagged ${marked == null ? "—" : marked + "d"} ago</span>
      <span class="st-r ${ur == null ? "" : ur >= 0 ? "st-up" : "st-down"}">${fmtR(ur)}</span>
      <span class="st-grade">${esc(pos.grade || "—")}</span>
      <span class="st-call" title="${esc(f.detail)}">${esc(f.label)}</span>
      ${closeCell(pos)}
    </div>`;
  };

  // ── the close control: pick rows → ONE confirm → ONE request ───────────────
  // Two deliberate acts before anything is sent, same safety property the old
  // two-click design had, but the second act is now shared by the whole batch:
  // picking arms a ROW (visibly, reversibly), and only the bar's confirm —
  // which states the count — sends. A single mis-click can pick, never close.
  const picked = new Map();            // "mkt:SYM" -> {sym, mkt, dir, px}
  let inFlight = null;                 // null | { pending:Set<sym>, total, t0, timer }

  const keyOf = (btn) => btn.dataset.mkt + ":" + btn.dataset.sym;

  const pickedR = (host) => {
    // Combined OPEN R of the picked rows, read from the rendered cells so the
    // bar can never disagree with the column beside it.
    let sum = 0, any = false;
    picked.forEach((p) => {
      const row = host.querySelector('.st-row[data-row="' + p.sym + '"] .st-r');
      const v = row ? parseFloat(String(row.textContent).replace(/[+R]/g, "")) : NaN;
      if (isFinite(v)) { sum += v; any = true; }
    });
    return any ? sum : null;
  };

  const barHTML = (host) => {
    if (inFlight) {
      const secs = Math.round((Date.now() - inFlight.t0) / 1000);
      const mins = Math.floor(secs / 60);
      const landed = inFlight.total - inFlight.pending.size;
      return `<span class="st-bar-msg">landing… ${mins ? mins + "m " : ""}${secs % 60}s
        — one run closes all ${inFlight.total}; each row confirms against the published book
        (${landed}/${inFlight.total} landed). A run queued behind a scan can take ~15 min.</span>`;
    }
    const n = picked.size;
    if (!n) return "";
    const r = pickedR(host);
    return `<span class="st-bar-msg"><b>${n}</b> picked${r == null ? "" : " · combined <b>" + fmtR(r) + "</b>"}
        · books each at its own last mark</span>
      <button type="button" class="st-go" data-go="1">Close ${n} now — one run</button>
      <button type="button" class="st-clear" data-clear="1">clear</button>`;
  };

  const paintBar = (host) => {
    const bar = host.querySelector(".st-bar");
    if (!bar) return;
    const inner = barHTML(host);
    bar.innerHTML = inner;
    bar.hidden = !inner;
  };

  const paintPicks = (host) => {
    host.querySelectorAll("button.st-x").forEach((b) => {
      if (b.classList.contains("st-sent") || b.classList.contains("st-wait")) return;
      const on = picked.has(keyOf(b));
      b.classList.toggle("st-pick", on);
      b.textContent = on ? "✓ picked" : "Close";
    });
    paintBar(host);
  };

  const clearPicks = (host) => { picked.clear(); paintPicks(host); };

  // ── landing watch: poll the PUBLISHED book, settle each row as it lands ────
  // A 202 is an accepted dispatch, not a landed close. One fetch per tick
  // covers every pending symbol. The window is sized for the WORST honest
  // case, not the best: close_position holds the `scan` mutex and a scan run
  // takes up to ~13 minutes, so a close legitimately queues that long before
  // its own ~1-2 min of work — the old 3-minute window read that as failure
  // and flipped healthy closes to "check the book" (2026-08-13, the lesson of
  // the all-waiting screenshot).
  const POLL_MS = 10000, POLL_TRIES = 96;   // 16 min

  const settleRow = (host, sym, landed) => {
    const btn = host.querySelector('button.st-x[data-sym="' + sym + '"]');
    if (!btn) return;
    btn.disabled = true;
    btn.classList.remove("st-wait", "st-pick", "st-fail");
    btn.classList.add(landed ? "st-sent" : "st-fail");
    btn.textContent = landed ? "closed ✓" : "check the book";
    btn.title = landed
      ? sym + " is closed in the bot book. It drops off this list on the next page load."
      : "The batch was accepted but " + sym + " is still in the published book. If the " +
        "close_position run skipped it (already closed another way) this row resolves on " +
        "reload; otherwise check the run in Actions.";
    if (landed) {
      const row = host.querySelector('.st-row[data-row="' + sym + '"]');
      if (row) { row.classList.add("st-gone"); setTimeout(() => { row.remove(); }, 900); }
    }
  };

  const releaseHolds = (host) => {
    host.querySelectorAll("button.st-x.st-wait").forEach((b) => {
      b.disabled = false;
      b.classList.remove("st-wait");
      b.textContent = "Close";
      b.title = tipFor(b.dataset.sym, parseFloat(b.dataset.px));
    });
  };

  const finishFlight = (host) => {
    const flight = inFlight;
    inFlight = null;
    // Anything still pending after the window is an honest unknown.
    flight.pending.forEach((sym) => settleRow(host, sym, false));
    releaseHolds(host);
    paintBar(host);
  };

  const watchLanding = (host) => {
    let tries = 0;
    const tick = () => {
      if (!inFlight) return;
      tries += 1;
      fetch("data/vivek_bot_book.json?t=" + tries + "_" + inFlight.pending.size, { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null))
        .then((bk) => {
          if (!inFlight) return;
          if (bk) {
            const open = new Set(((bk.open || []))
              .filter((p) => p && p.status === "open")
              .map((p) => String(p.symbol || "").toUpperCase()));
            Array.from(inFlight.pending).forEach((sym) => {
              if (!open.has(sym)) { inFlight.pending.delete(sym); settleRow(host, sym, true); }
            });
          }
          if (inFlight.pending.size === 0) {
            const total = inFlight.total;
            inFlight = null;
            releaseHolds(host);
            const bar = host.querySelector(".st-bar");
            if (bar) bar.innerHTML = `<span class="st-bar-msg">all <b>${total}</b> closed ✓ — slots freed.</span>`;
            return;
          }
          paintBar(host);   // elapsed + landed count stay live
          if (tries >= POLL_TRIES) return finishFlight(host);
          setTimeout(tick, POLL_MS);
        })
        .catch(() => {
          if (!inFlight) return;
          if (tries >= POLL_TRIES) return finishFlight(host);
          setTimeout(tick, POLL_MS);
        });
    };
    setTimeout(tick, POLL_MS);
  };

  const send = (host) => {
    if (inFlight || !picked.size) return;
    const entries = Array.from(picked.values());
    inFlight = {
      pending: new Set(entries.map((e) => e.sym)),
      total: entries.length,
      t0: Date.now(),
    };
    picked.clear();
    entries.forEach((e) => {
      const btn = host.querySelector('button.st-x[data-sym="' + e.sym + '"]');
      if (btn) {
        btn.disabled = true;
        btn.classList.remove("st-pick");
        btn.textContent = "queued…";
        btn.title = "In the batch — waiting for it to leave the published book.";
      }
    });
    // Every unpicked live button is held for the duration of the ONE flight —
    // a second batch racing the first is exactly the two-runs collision the
    // batch exists to remove.
    host.querySelectorAll("button.st-x").forEach((b) => {
      if (b.disabled || b.classList.contains("st-sent")) return;
      b.disabled = true; b.classList.add("st-wait");
      b.textContent = "waiting…";
      b.title = "A batch is in flight. It unlocks when that run lands in the published book.";
    });
    paintBar(host);
    // journal_type is hard-coded "bot" and must stay that way: this strip
    // writes the ONE track record or nothing.
    fetch("/api/close", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        journal_type: "bot",
        closes: entries.map((e) => ({ symbol: e.sym, market: e.mkt, direction: e.dir, price: e.px })),
      }),
    })
      .then((r) => r.json().catch(() => ({})).then((b) => ({ ok: r.ok, b })))
      .then(({ ok, b }) => {
        if (ok) { watchLanding(host); return; }
        // Rejected batch: nothing was dispatched. Restore the picks so one fix
        // (say, a rate-limit minute) doesn't cost the whole selection.
        const flight = inFlight; inFlight = null;
        entries.forEach((e) => picked.set(e.mkt + ":" + e.sym, e));
        host.querySelectorAll("button.st-x").forEach((btn) => {
          if (btn.classList.contains("st-sent")) return;
          btn.disabled = false; btn.classList.remove("st-wait");
        });
        paintPicks(host);
        const bar = host.querySelector(".st-bar");
        if (bar) bar.insertAdjacentHTML("afterbegin",
          `<span class="st-bar-err">${esc((b && b.message) || "The batch was rejected — try again.")}</span> `);
        void flight;
      })
      .catch(() => {
        const flight = inFlight; inFlight = null;
        entries.forEach((e) => picked.set(e.mkt + ":" + e.sym, e));
        host.querySelectorAll("button.st-x").forEach((btn) => {
          if (btn.classList.contains("st-sent")) return;
          btn.disabled = false; btn.classList.remove("st-wait");
        });
        paintPicks(host);
        const bar = host.querySelector(".st-bar");
        if (bar) bar.insertAdjacentHTML("afterbegin",
          `<span class="st-bar-err">Could not reach /api/close. Check the connection and try again.</span> `);
        void flight;
      });
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
      <div class="st-bar" hidden></div>
      <div class="st-rows">
        <div class="st-row st-cols"><span>Name</span><span>Stall</span><span>Open R</span><span>Grade</span><span>Your call</span><span>Act</span></div>
        ${ordered.map((p) => rowHTML(p, day, maxHold)).join("")}
      </div>
      <p class="st-foot">Flagged by the stale probe (≥2 weeks open, minimal movement) — going nowhere is
        a decision too. Tap a ticker for its chart. <b>Close</b> picks that row — pick as many as you
        want out, then the bar's <b>Close N now</b> sends them as <b>ONE</b> run: one commit, one deploy,
        every row booked at its own last mark (the price its Open R uses). Nothing is sent by picking,
        and a row only reads <b>closed ✓</b> once it is actually gone from the published book. Nothing
        here closes anything on its own.</p>`;
  }

  // ── mount ──────────────────────────────────────────────────────────────────
  // #88 discipline: the catch is scoped to the fetch and parse only — hiding
  // the strip is the right answer to "the file is not there", and the wrong
  // answer to a renderer fault, which must reach window.onerror instead.
  const report = (err) => { setTimeout(() => { throw err; }, 0); };

  const host = document.getElementById("stalled-strip");
  if (host) {
    // Delegated, bound ONCE at mount rather than per render: render() replaces
    // innerHTML wholesale, so per-button listeners would be re-attached (and
    // leaked) on every repaint. Anything that is not a live control falls
    // straight through — clicking the ticker link must never be intercepted.
    host.addEventListener("click", (ev) => {
      const go = ev.target.closest && ev.target.closest("button.st-go");
      if (go && host.contains(go)) { send(host); return; }
      const clr = ev.target.closest && ev.target.closest("button.st-clear");
      if (clr && host.contains(clr)) { clearPicks(host); return; }
      const btn = ev.target.closest && ev.target.closest("button.st-x");
      if (!btn || btn.disabled || !host.contains(btn)) return;
      if (inFlight) return;            // belt and braces: they are already disabled
      const k = keyOf(btn);
      if (picked.has(k)) picked.delete(k);
      else picked.set(k, {
        sym: btn.dataset.sym,
        mkt: btn.dataset.mkt,
        dir: btn.dataset.dir,
        px: parseFloat(btn.dataset.px),
      });
      paintPicks(host);
    });
    // Escape empties the basket (never mid-flight — that train has left).
    // Deliberately NOT on outside-click: a multi-row selection is minutes of
    // reading; losing it to a stray click elsewhere on the page would be the
    // new way to hate this strip.
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && !inFlight && picked.size) clearPicks(host);
    });
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