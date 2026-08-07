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
   This file shipped read-only by construction and no longer is: each row now
   carries a Close button. What changed is the ERGONOMICS of a decision the
   owner could already make — close_position.yml with journal_type=bot, by
   hand, in the Actions tab — not who makes it. The distinction that must
   survive every future edit:

     * NOTHING HERE DECIDES. No threshold, no timer, no condition in this file
       closes anything. It defines no thresholds at all — a row is stalled if
       and only if the engine stamped it — and the button does nothing until a
       human clicks it TWICE.
     * The write is exactly one call, POST /api/close, with journal_type
       hard-coded "bot". That endpoint is the pre-existing, validated,
       rate-limited dispatcher (1 close per symbol per minute, 60/day); this
       file adds a caller, not a capability.
     * It books at the row's OWN last_mark — the same number the Open R beside
       it is computed from, so what you read is what you book — and the
       confirm step prints that price before it is sent. A row with no usable
       mark cannot be closed from here at all (fail-closed: no honest price,
       no button).
     * Still no localStorage, no sessionStorage, no KV, no second endpoint.

   The surface remains a place to SEE what is squatting capacity; it is now
   also the shortest path from seeing it to acting on it. test/stalled.test.js
   pins every clause above against the shipped source. */
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

  // The price a close from this strip books at. The row's OWN last_mark, which
  // is the number `unreal_r` beside it was computed from — so the R you are
  // looking at when you decide is the R you get. FAIL-CLOSED: no finite
  // positive mark means no honest price, which means no button, not a guess.
  const closePrice = (pos) => {
    const v = pos && pos.last_mark;
    return (typeof v === "number" && isFinite(v) && v > 0) ? v : null;
  };
  const fmtPx = (v) => "$" + v.toFixed(v < 1 ? 4 : 2);

  const tipFor = (sym, px) => "Close " + sym + " in the bot book at its last mark, " +
    fmtPx(px) + ". Click once to arm, again to send - nothing is sent on the first click.";

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
    return `<div class="st-row st-${f.kind}">
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

  // ── the close control ──────────────────────────────────────────────────────
  // TWO CLICKS, ALWAYS. The first only arms the button and prints the price it
  // would send; the second sends it. A single mis-click next to a "your call"
  // chip must never be able to close a real position, and the armed state
  // disarms itself after ARM_MS so a button left hot in a background tab goes
  // cold on its own. Only one row can be armed at a time — two live confirms
  // side by side is how the wrong one gets clicked.
  const ARM_MS = 6000;
  let armedBtn = null, armTimer = null;

  const disarm = (btn) => {
    if (!btn) return;
    clearTimeout(armTimer);
    if (armedBtn === btn) armedBtn = null;
    btn.classList.remove("st-arm");
    btn.textContent = "Close";
  };

  const arm = (btn) => {
    disarm(armedBtn);
    armedBtn = btn;
    btn.classList.add("st-arm");
    btn.textContent = "Confirm " + fmtPx(parseFloat(btn.dataset.px));
    armTimer = setTimeout(() => disarm(btn), ARM_MS);
  };

  // ONE CLOSE AT A TIME, and this is not politeness — it is the only thing that
  // makes a ROW of Close buttons safe. Learned the hard way on the first real
  // use, 2026-08-07: seven rows were clicked in about ten seconds and exactly
  // ONE landed. The close pipeline is serial in two independent ways and this
  // surface was the first thing ever able to outrun it.
  //
  //   1. close_position.yml sits in the `scan` concurrency group, and GitHub
  //      keeps only ONE pending run per group — a new arrival CANCELS the
  //      previously-pending one. Five dispatches evicted each other in flight.
  //   2. Even the runs that do execute rebase onto a book another close has
  //      already rewritten, and two closes touch the same JSON arrays in the
  //      same three files. Git cannot auto-merge that: the last one conflicted
  //      on all five rebase attempts and refused to push, correctly, leaving
  //      the position open rather than corrupting the book.
  //
  // Neither is new; nothing else could ever reach them, because closing used
  // to mean dispatching a workflow by hand, minutes apart. The UI enforced the
  // constraint through friction. This restores it deliberately: while a close
  // is in flight every other button is held, and it is released only when the
  // published book actually shows the position gone.
  const WAIT_WHY = "One close at a time — the book is a single file, and two closes at " +
    "once collide on the merge. This unlocks when the one in flight lands.";
  let inFlight = null;

  const otherBtns = (except) => Array.prototype.slice
    .call(host.querySelectorAll("button.st-x")).filter((b) => b !== except);

  const holdOthers = (except, on) => {
    otherBtns(except).forEach((b) => {
      if (on && !b.classList.contains("st-sent") && !b.classList.contains("st-wait")) {
        b.disabled = true; b.classList.add("st-wait");
        b.textContent = "waiting…"; b.title = WAIT_WHY;
      } else if (!on && b.classList.contains("st-wait")) {
        b.disabled = false; b.classList.remove("st-wait");
        b.textContent = "Close";
        b.title = tipFor(b.dataset.sym, parseFloat(b.dataset.px));
      }
    });
  };

  // Watch the PUBLISHED book rather than trusting the 202. A queued dispatch is
  // not a landed close — that gap is exactly where the six went missing — so
  // "closed" is only claimed once the artifact the whole page reads no longer
  // carries the position.
  const POLL_MS = 8000, POLL_TRIES = 24;   // ~3 min: dispatch + run + Pages deploy
  const settle = (btn, landed) => {
    inFlight = null;
    btn.disabled = true;
    btn.classList.remove("st-fail");
    btn.classList.add(landed ? "st-sent" : "st-fail");
    btn.textContent = landed ? "closed ✓" : "check the book";
    btn.title = landed
      ? btn.dataset.sym + " is closed in the bot book. It drops off this list on the next page load."
      : "The close was accepted but has not appeared in the published book yet. Reload in a minute; " +
        "if it is still listed, the run failed — check close_position in Actions.";
    holdOthers(btn, false);
  };

  const watchLanding = (btn) => {
    const sym = String(btn.dataset.sym || "").toUpperCase();
    let tries = 0;
    const tick = () => {
      tries += 1;
      fetch("data/vivek_bot_book.json?t=" + tries + "_" + sym, { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null))
        .then((bk) => {
          const stillOpen = !bk || ((bk.open || []).some((p) =>
            p && p.status === "open" && String(p.symbol || "").toUpperCase() === sym));
          if (bk && !stillOpen) return settle(btn, true);
          if (tries >= POLL_TRIES) return settle(btn, false);
          setTimeout(tick, POLL_MS);
        })
        .catch(() => { if (tries >= POLL_TRIES) settle(btn, false); else setTimeout(tick, POLL_MS); });
    };
    setTimeout(tick, POLL_MS);
  };

  const send = (btn) => {
    clearTimeout(armTimer);
    armedBtn = null;
    btn.classList.remove("st-arm");
    btn.disabled = true;
    btn.textContent = "sending…";
    inFlight = btn.dataset.sym;
    holdOthers(btn, true);
    // journal_type is hard-coded "bot" and must stay that way: "swing"/"scalp"
    // would write the legacy localStorage journals instead of the ONE track
    // record, silently, and the row would still be sitting here afterwards.
    fetch("/api/close", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        symbol: btn.dataset.sym,
        market: btn.dataset.mkt,
        direction: btn.dataset.dir,
        price: parseFloat(btn.dataset.px),
        journal_type: "bot",
      }),
    })
      .then((r) => r.json().catch(() => ({})).then((b) => ({ ok: r.ok, b })))
      .then(({ ok, b }) => {
        if (ok) {
          btn.textContent = "queued…";
          btn.title = (b && b.message) || "Close queued — waiting for it to appear in the book.";
          watchLanding(btn);           // the others stay held until it lands
        } else {
          // Re-enable: a rejected close (rate limit, bad market, dispatch
          // failure) is a thing to retry, not a dead row. The reason goes in
          // the title rather than an alert — a modal dialog over a trading
          // page is the last thing anyone needs.
          inFlight = null; holdOthers(btn, false);
          btn.disabled = false;
          btn.classList.add("st-fail");
          btn.textContent = "failed — retry";
          btn.title = (b && b.message) || "The close request was rejected.";
        }
      })
      .catch(() => {
        inFlight = null; holdOthers(btn, false);
        btn.disabled = false;
        btn.classList.add("st-fail");
        btn.textContent = "failed — retry";
        btn.title = "Could not reach /api/close. Check the connection and try again.";
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
      <div class="st-rows">
        <div class="st-row st-cols"><span>Name</span><span>Stall</span><span>Open R</span><span>Grade</span><span>Your call</span><span>Act</span></div>
        ${ordered.map((p) => rowHTML(p, day, maxHold)).join("")}
      </div>
      <p class="st-foot">Flagged by the stale probe (≥2 weeks open, minimal movement) — going nowhere is
        a decision too. Tap a ticker for its chart. <b>Close</b> books that row in the bot book at its own
        last mark (the price the Open R beside it uses) — one click arms it and shows the price, a second
        sends it. Closes go ONE AT A TIME — the rest wait while one is in flight, and a button only reads
        <b>closed \u2713</b> once the position is actually gone from the published book. Nothing here closes anything
        on its own.</p>`;
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
    // leaked) on every repaint. Anything that is not a live Close button falls
    // straight through — clicking the ticker link must never be intercepted.
    host.addEventListener("click", (ev) => {
      const btn = ev.target.closest && ev.target.closest("button.st-x");
      if (!btn || btn.disabled || !host.contains(btn)) return;
      if (inFlight) return;            // belt and braces: the others are already disabled
      if (btn.classList.contains("st-arm")) send(btn); else arm(btn);
    });
    // Clicking anywhere else, or pressing Escape, stands the button down. An
    // armed control should never outlive the attention that armed it.
    document.addEventListener("click", (ev) => {
      if (armedBtn && !(ev.target.closest && ev.target.closest("button.st-x"))) disarm(armedBtn);
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && armedBtn) disarm(armedBtn);
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
