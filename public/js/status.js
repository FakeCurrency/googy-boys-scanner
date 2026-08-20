/* Vivek 5.0 — STATUS control (2026-08-19, owner-ruled Session 1).
 *
 * One lamp in the top bar on every nav page, and a tap sheet behind it that
 * answers "is the machine working?" without making the owner open GitHub.
 *
 * READ-ONLY BY CONSTRUCTION, and that is the whole design brief:
 *
 *   - It issues GET requests only, to published assets and to /api/health.
 *   - It NEVER touches /api/heartbeat. That endpoint is the HEALER: when the
 *     book is overdue it DISPATCHES a scan and spends one of its 24/day heal
 *     budget. A status light that polled it would start moving the thing it
 *     measures — every page load a possible workflow dispatch, and a monitor
 *     that mutates its subject is not a monitor. The healer's condition is
 *     instead DERIVED from the book age the healer itself reads, and the sheet
 *     says so rather than implying it probed.
 *   - It never touches /api/tick, /api/scan or /api/close, and it writes
 *     nothing — no POST, no localStorage. There is deliberately not even a
 *     "last opened" flag: a read-only promise with one exception is a
 *     read-only promise nobody can check at a glance.
 *
 * NO INVENTED NUMBERS. Every threshold below is one the system already owns
 * and acts on somewhere else, cited at its definition:
 *
 *   4h  = functions/api/health.js max_h default (= WATCHDOG_BOOK_MAX_AGE_H).
 *         The point at which the external uptime monitor is told the pipeline
 *         is DOWN. Used here for RED and as the uptime "alive" threshold.
 *   90m = functions/api/heartbeat.js DEFAULT_STALE_MIN. The point at which the
 *         system itself considers a scan overdue and heals. Used here for
 *         AMBER.
 *   30  = the position cap, read from data/bot_rules.json rather than typed
 *         (project rule 3 — never hardcode a published constant twice).
 *
 * Uptime is measured, not asserted: public/data/funnel_history.json carries a
 * wall-clock stamp for every successful scan publish (scanner/run.py appends
 * one immediately after output.write_vivek_pair), so the ledger IS the
 * evidence. The window is CLAMPED to the ledger's own span and labelled when
 * clamped — a 30d figure computed over 19d of history would read as five
 * nines of a fortnight that never happened.
 *
 * What this control deliberately does NOT claim to know is listed on the sheet
 * itself, with the reason, rather than being quietly omitted: the healer is not
 * probeable read-only, the 5-minute stop-watcher commits nothing a browser can
 * read, and CI failures live in GitHub's API. "View latest failure" is a deep
 * link to the authoritative list rather than a number this file made up.
 */
(() => {
  "use strict";

  // ── constants, each one sourced ────────────────────────────────────────────
  const HEALTH_MAX_H = 4;      // functions/api/health.js (max_h default)
  const HEAL_STALE_MIN = 90;   // functions/api/heartbeat.js (DEFAULT_STALE_MIN)
  const FALLBACK_CAP = 30;     // only if bot_rules.json is unreachable
  const CYCLE_TAG = "w3-1";    // scanner/config.py VIVEK_BOT_CYCLE_TAG
  const CYCLE_TARGET = 30;     // the pre-registered close count for the cohort
  const REPO = "FakeCurrency/googy-boys-scanner";
  // Mirrors journal.js MECHANICAL_EXITS. test/status.test.js parses BOTH files
  // and fails if they diverge, so this copy cannot drift silently — the same
  // treatment risk_defaults.test.js gives the offline rules mirror.
  const MECHANICAL_EXITS = ["stop", "time", "trail", "target"];

  const esc = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

  // ── pure helpers (sliced by the test suite — keep them const arrows) ───────

  // Humanised age. Minutes under an hour, hours under two days, then days —
  // the same ladder system.html's coverage table uses, so two surfaces reading
  // the same stamp cannot describe it differently.
  const agoText = (ms) => {
    if (!isFinite(ms) || ms < 0) return "—";
    const m = Math.round(ms / 6e4);
    if (m < 60) return `${m}m ago`;
    if (m < 2880) return `${Math.round(m / 60)}h ago`;
    return `${Math.round(m / 1440)}d ago`;
  };

  // Book shape the light and the sheet both read. `free` is slots, which is
  // the number that answers "can it take another one" — the dollar headroom
  // disagrees whenever the notional is retuned (see HORIZON in CLAUDE.md), so
  // it is deliberately not shown as capacity here.
  const bookState = (book, cap) => {
    const b = book && typeof book === "object" ? book : {};
    const open = Array.isArray(b.open) ? b.open : [];
    const guard = b.guard && typeof b.guard === "object" ? b.guard : {};
    const breached = Object.keys(guard)
      .filter((m) => guard[m] && guard[m].breached)
      .map((m) => ({ market: m, kind: String((guard[m] && guard[m].breach_kind) || "loss limit") }));
    const limit = isFinite(cap) && cap > 0 ? cap : FALLBACK_CAP;
    return {
      open: open.length,
      cap: limit,
      free: Math.max(0, limit - open.length),
      stalled: open.filter((r) => r && r.stale_pinged).map((r) => String(r.symbol || "?")),
      breached,
      updatedAt: String(b.updated_at || ""),
      closed: Array.isArray(b.closed) ? b.closed.length : 0,
    };
  };

  // The w3-1 cohort, straight off the audit tag vivek_run stamps on each row.
  // Rows written before the gate carry no `cycle` key at all, so absent means
  // out-of-cohort rather than "unknown" — the same absent-is-not-empty
  // convention the review flags use.
  const cohort = (book, tag) => {
    const b = book && typeof book === "object" ? book : {};
    const opens = (Array.isArray(b.open) ? b.open : []).filter((r) => r && r.cycle === tag);
    const closes = (Array.isArray(b.closed) ? b.closed : []).filter((r) => r && r.cycle === tag);
    const mech = (r) => MECHANICAL_EXITS.indexOf(String((r && r.exit_reason) || "").toLowerCase()) >= 0;
    const byRules = closes.filter(mech);
    const byOwner = closes.filter((r) => !mech(r));
    const sumR = (a) => a.reduce((n, r) => n + (typeof r.realized_r === "number" ? r.realized_r : 0), 0);
    return {
      open: opens.length, closed: closes.length,
      byRules: byRules.length, byOwner: byOwner.length,
      rulesR: sumR(byRules), ownerR: sumR(byOwner),
    };
  };

  // Every successful scan publish, all markets merged, ascending ms.
  // Merged because the question uptime answers is "was the PIPELINE alive",
  // and crypto is the only 24/7 leg — an ASX-only ledger would read as 16
  // hours of nightly downtime that is simply the market being shut.
  const mergeStamps = (funnel) => {
    const mk = (funnel && funnel.markets) || {};
    const out = [];
    Object.keys(mk).forEach((m) => {
      const ts = (mk[m] && mk[m].t) || [];
      if (!Array.isArray(ts)) return;
      ts.forEach((s) => { const v = Date.parse(s); if (isFinite(v)) out.push(v); });
    });
    return out.sort((a, b) => a - b);
  };

  // Per-market last publish + the counts that publish carried.
  const marketAges = (funnel, nowMs) => {
    const mk = (funnel && funnel.markets) || {};
    return Object.keys(mk).sort().map((m) => {
      const blk = mk[m] || {};
      const ts = Array.isArray(blk.t) ? blk.t : [];
      const last = ts.length ? Date.parse(ts[ts.length - 1]) : NaN;
      const tail = (k) => {
        const a = Array.isArray(blk[k]) ? blk[k] : [];
        return a.length ? a[a.length - 1] : null;
      };
      return {
        market: m,
        at: ts.length ? String(ts[ts.length - 1]) : "",
        ageMs: isFinite(last) ? nowMs - last : NaN,
        scanned: tail("scanned"),
        published: tail("published"),
        runs: ts.length,
      };
    });
  };

  // What started the scans (batch-100 WS-J): counts of the last-N-days
  // publishes by trigger source, from the funnel ledger's `trigger` column
  // (funnelhistory.py stamps cron / manual / heartbeat; "" = stamped before
  // the column existed, or a local run). Returns null when NO market carries
  // the column yet — a mix invented from absent data would read as "everything
  // is cron", which is an answer, not an absence. Heartbeat matters most: each
  // one is a self-heal dispatch spending the healer's 24/day budget, and a
  // rising count is a dying cron wearing a green lamp.
  const triggerMix = (funnel, nowMs, windowDays) => {
    const mk = (funnel && funnel.markets) || {};
    const start = nowMs - windowDays * 864e5;
    const mix = { cron: 0, manual: 0, heartbeat: 0, unknown: 0, total: 0 };
    let sawColumn = false;
    Object.keys(mk).forEach((m) => {
      const blk = mk[m] || {};
      const ts = Array.isArray(blk.t) ? blk.t : [];
      const tr = Array.isArray(blk.trigger) ? blk.trigger : null;
      if (!tr) return;                 // pre-migration block: silent, not "unknown"
      sawColumn = true;
      // The migration pads the FRONT, so equal lengths align by index; if they
      // ever differ, align from the END — the newest rows are the ones a
      // 7-day window reads, and the tail is where fresh stamps land.
      const off = ts.length - tr.length;
      for (let i = 0; i < ts.length; i++) {
        const v = Date.parse(ts[i]);
        if (!isFinite(v) || v <= start || v > nowMs) continue;
        const t = i - off >= 0 ? String(tr[i - off] || "") : "";
        mix.total += 1;
        if (t === "cron" || t === "manual" || t === "heartbeat") mix[t] += 1;
        else mix.unknown += 1;
      }
    });
    return sawColumn && mix.total ? mix : null;
  };

  // TIME-WEIGHTED uptime: the share of the window during which the newest scan
  // was no older than `thrH`. Three properties make it honest rather than
  // decorative:
  //
  //   1. The window is clamped to the ledger's own span and reports both, so a
  //      30d ask against 19d of history reads as 19d instead of silently
  //      counting the pre-history dark as healthy.
  //   2. `nowMs` closes the sequence, so the CURRENT gap counts. A pipeline
  //      that died an hour ago erodes this number live; a figure computed only
  //      between recorded scans would keep reporting 100% while nothing ran.
  //   3. A gap straddling the window start is charged only for its in-window
  //      part (the seed walk below), so the number does not jump as old rows
  //      fall out of the window.
  const uptime = (stamps, nowMs, windowDays, thrH) => {
    const list = Array.isArray(stamps) ? stamps.filter((t) => isFinite(t)) : [];
    if (!list.length) return null;
    const spanMs = nowMs - list[0];
    if (!(spanMs > 0)) return null;
    const useMs = Math.min(windowDays * 864e5, spanMs);
    const start = nowMs - useMs;
    const thr = thrH * 36e5;
    let prev = null;
    for (let i = 0; i < list.length; i++) { if (list[i] <= start) prev = list[i]; else break; }
    if (prev === null) prev = start;
    let down = 0;
    const seq = list.filter((t) => t > start).concat([nowMs]);
    for (let i = 0; i < seq.length; i++) {
      const gapStart = Math.max(prev + thr, start);
      const gapEnd = Math.min(seq[i], nowMs);
      if (gapEnd > gapStart) down += gapEnd - gapStart;
      prev = seq[i];
    }
    return {
      pct: 100 * (1 - down / useMs),
      downH: down / 36e5,
      windowDays: useMs / 864e5,
      askedDays: windowDays,
      clamped: windowDays * 864e5 > spanMs,
      spanDays: spanMs / 864e5,
      thrH,
    };
  };

  // THE STATES MATRIX. First match wins, worst first.
  //
  // RED is reserved for "the pipeline is not running, or cannot be seen at
  // all". A LOSS GUARD BREACH IS AMBER, NOT RED, on purpose: a breach is the
  // machine working correctly and refusing new entries, and heartbeat.js
  // already paid for the lesson that an alarm which fires on successful
  // self-protection is an alarm that gets muted. Amber says look; red says the
  // evidence you trade on is not arriving.
  const overall = (sig) => {
    const s = sig || {};
    if (s.healthReachable === false) return { level: "red", why: "can't reach /api/health — the pipeline can't be seen from here" };
    // ORDER MATTERS: the "how stale" sentence needs an age, and a health probe
    // can answer NOT-OK without one (a 404 from a missing Function, an
    // unreadable asset, a book with no parseable stamp). Reporting "no scan
    // committed for 0.0h" in those cases would be a fabricated number wearing
    // an alarm's clothes — the exact failure this control exists not to commit.
    // So a missing age is named as a missing age, whatever the probe said.
    if (s.bookAgeH == null || !isFinite(s.bookAgeH)) {
      return { level: "red", why: s.healthOk === false
        ? "the health probe answered, but with no readable scan age"
        : "the book carries no readable timestamp" };
    }
    if (s.healthOk === false) return { level: "red", why: `no scan committed for ${s.bookAgeH.toFixed(1)}h — past the ${HEALTH_MAX_H}h alarm` };
    if (s.bookAgeH * 60 > HEAL_STALE_MIN) return { level: "amber", why: `last scan ${agoText(s.bookAgeH * 36e5)} — past the ${HEAL_STALE_MIN}m overdue mark` };
    if (s.breached && s.breached.length) return { level: "amber", why: `loss guard breached: ${s.breached.map((b) => b.market).join(", ")} — new entries halted` };
    if (s.stalled && s.stalled.length) return { level: "amber", why: `${s.stalled.length} position${s.stalled.length === 1 ? "" : "s"} stamped stalled` };
    if (s.bookReadable === false) return { level: "amber", why: "pipeline fresh, but the book file didn't load here" };
    return { level: "green", why: `scanning normally — last scan ${agoText(s.bookAgeH * 36e5)}` };
  };

  const pct1 = (n) => (isFinite(n) ? (Math.round(n * 100) / 100).toFixed(2) : "—");
  const LAMP = { green: "●", amber: "●", red: "●" };
  const WORD = { green: "OK", amber: "CHECK", red: "DOWN" };

  // ── data ──────────────────────────────────────────────────────────────────
  const getJSON = (url, opts) => fetch(url, opts || { cache: "no-cache" })
    .then((r) => (r.ok ? r.json().then((j) => ({ ok: true, status: r.status, json: j }))
                       : r.json().then((j) => ({ ok: false, status: r.status, json: j }), () => ({ ok: false, status: r.status, json: null }))))
    .catch(() => null);

  const STATE = { sig: null, book: null, funnel: null, rules: null, health: null, loadedAt: 0 };

  // The LIGHT's budget is one 150-byte request. /api/health answers the exact
  // question the lamp asks (is a scan fresher than the alarm threshold), it is
  // computed server-side off the published asset, and it is never cached.
  function loadLight() {
    return Promise.all([
      getJSON("/api/health"),
      getJSON("data/vivek_bot_book.json"),
      getJSON("data/bot_rules.json"),
    ]).then(([h, b, r]) => {
      STATE.health = h;
      STATE.book = b && b.ok ? b.json : null;
      STATE.rules = r && r.ok ? r.json : null;
      const hj = h && h.json ? h.json : null;
      const cap = STATE.rules && typeof STATE.rules.max_open_total === "number"
        ? STATE.rules.max_open_total : NaN;
      const bs = bookState(STATE.book, cap);
      STATE.sig = {
        healthReachable: !!h,
        healthOk: h ? !!(hj && hj.ok) : null,
        bookAgeH: hj && typeof hj.age_h === "number" ? hj.age_h : null,
        bookReadable: !!STATE.book,
        breached: bs.breached,
        stalled: bs.stalled,
      };
      STATE.book_state = bs;
      STATE.loadedAt = Date.now();
      return STATE;
    });
  }

  // The 33 KB funnel ledger is fetched ONLY when the sheet opens. It is the
  // uptime evidence and the per-market ages in one file, which is why the
  // sheet does not also call /api/health?market=<m> three times.
  function loadSheet() {
    if (STATE.funnel) return Promise.resolve(STATE.funnel);
    return getJSON("data/funnel_history.json").then((f) => {
      STATE.funnel = f && f.ok ? f.json : null;
      return STATE.funnel;
    });
  }

  // ── render ────────────────────────────────────────────────────────────────
  function lampHTML(level, why) {
    return `<span class="sysdot-lamp" data-level="${esc(level)}" aria-hidden="true">${LAMP[level] || "●"}</span>` +
           `<span class="sysdot-lbl">${esc(WORD[level] || "—")}</span>` +
           `<span class="sysdot-sr">System status: ${esc(WORD[level] || "unknown")} — ${esc(why)}</span>`;
  }

  function paintLamp() {
    const btn = document.getElementById("sysdot");
    if (!btn) return;
    const o = overall(STATE.sig);
    btn.innerHTML = lampHTML(o.level, o.why);
    btn.dataset.level = o.level;
    btn.title = `System status — ${WORD[o.level]}: ${o.why}`;
  }

  function row(label, value, note) {
    return `<div class="sys-row"><span class="sys-k">${esc(label)}</span>` +
           `<span class="sys-v">${value}</span>` +
           (note ? `<span class="sys-n">${esc(note)}</span>` : "") + `</div>`;
  }

  function sheetHTML() {
    const o = overall(STATE.sig);
    const bs = STATE.book_state || bookState(null, NaN);
    const now = Date.now();
    const ch = cohort(STATE.book, CYCLE_TAG);
    const stamps = mergeStamps(STATE.funnel);
    const u7 = uptime(stamps, now, 7, HEALTH_MAX_H);
    const u30 = uptime(stamps, now, 30, HEALTH_MAX_H);
    const ages = marketAges(STATE.funnel, now);

    // The value carries the number and, when the window had to be cut down to
    // the evidence, the warning that says so. The arithmetic behind it goes on
    // the note line — a value cell holding three facts is a value cell nobody
    // reads to the end.
    const upVal = (u) => {
      if (!u) return `<b>insufficient history</b>`;
      const lab = u.clamped
        ? ` <span class="sys-warn">only ${u.windowDays.toFixed(0)}d of history</span>`
        : "";
      return `<b>${pct1(u.pct)}%</b>${lab}`;
    };
    const upNote = (u, extra) => {
      if (!u) return extra || "";
      const gaps = u.downH < 0.05
        ? `no gap longer than ${u.thrH}h`
        : `${u.downH.toFixed(1)}h beyond the ${u.thrH}h line`;
      return extra ? `${gaps} · ${extra}` : gaps;
    };

    let h = "";
    h += `<div class="sys-hd"><span class="sys-hd-lamp" data-level="${esc(o.level)}">●</span>` +
         `<span class="sys-hd-t">${esc(WORD[o.level])}</span></div>`;
    h += `<p class="sys-why">${esc(o.why)}</p>`;

    h += `<h3 class="sys-h">Pipeline</h3>`;
    h += row("Last scan committed", bs.updatedAt
      ? `<b>${esc(agoText(now - Date.parse(bs.updatedAt)))}</b>`
      : (STATE.sig && STATE.sig.bookAgeH != null ? `<b>${STATE.sig.bookAgeH.toFixed(1)}h ago</b>` : "—"),
      `overdue at ${HEAL_STALE_MIN}m · alarm at ${HEALTH_MAX_H}h`);
    const ledgerFrom = stamps.length ? String(new Date(stamps[0]).toISOString().slice(0, 10)) : "";
    h += row("Uptime · 7d", upVal(u7), upNote(u7, `measured on committed scans`));
    h += row("Uptime · 30d", upVal(u30),
      upNote(u30, u30 && u30.clamped && ledgerFrom ? `the ledger starts ${ledgerFrom}` : ""));
    // Trigger mix (7d): hidden until the trigger column exists on some market
    // — an invented "all cron" is worse than silence. Heartbeat count is the
    // one to watch: every heal is a cron that failed to fire on its own.
    const tm = triggerMix(STATE.funnel, now, 7);
    if (tm) {
      const bits = [`<b>${tm.cron} cron</b>`];
      if (tm.manual) bits.push(`${tm.manual} manual`);
      if (tm.heartbeat) bits.push(`<span class="sys-amber">${tm.heartbeat} self-heal</span>`);
      if (tm.unknown) bits.push(`${tm.unknown} unstamped`);
      h += row("Scan triggers · 7d", bits.join(" · "),
        tm.heartbeat ? "self-heal = the cron missed and /api/heartbeat re-dispatched it"
                     : "no self-heal dispatches — the crons are firing on their own");
    }

    h += `<h3 class="sys-h">Scans by market</h3>`;
    if (!ages.length) {
      h += `<p class="sys-empty">funnel_history.json didn't load — per-market ages unavailable.</p>`;
    } else {
      ages.forEach((a) => {
        h += row(a.market.toUpperCase(),
          `<b>${esc(agoText(a.ageMs))}</b>`,
          a.published != null ? `${a.published} published of ${a.scanned} scanned · ${a.runs} runs on file` : "");
      });
    }

    h += `<h3 class="sys-h">Book</h3>`;
    h += row("Open", `<b>${bs.open}</b> / ${bs.cap}`, `${bs.free} slot${bs.free === 1 ? "" : "s"} free · ${bs.closed} closed`);
    h += row("Stalled", bs.stalled.length ? `<b class="sys-amber">${bs.stalled.length}</b>` : `<b>0</b>`,
      bs.stalled.length ? bs.stalled.join(", ") : "no positions stamped by the stale probe");
    h += row("Loss guards", bs.breached.length
      ? `<b class="sys-amber">${bs.breached.map((b) => esc(b.market) + " " + esc(b.kind)).join(", ")}</b>`
      : `<b>clear</b>`, bs.breached.length ? "new entries halted for that market" : "daily + trailing-week, per market");
    h += row("Integrity", `<b>passed</b>`,
      "vivek_run --verify gates the commit — a failed book never lands, so a fresh commit IS a passed verify");

    h += `<h3 class="sys-h">w3-1 cycle</h3>`;
    h += row("Gated open", `<b>${ch.open}</b>`, "opened under the weekly/3d gate");
    h += row("Closes", `<b>${ch.closed}</b> of ${CYCLE_TARGET}`,
      ch.closed ? `${ch.byRules} by the rules · ${ch.byOwner} by you` : "readout at the pre-registered count");
    if (ch.closed && !ch.byRules) {
      // Same sentence the journal's w3-1 strip uses, deliberately: two
      // surfaces describing one cohort in two vocabularies reads as two
      // findings. The journal is where the exits are listed; this is the
      // one-line version of the same fact.
      h += `<p class="sys-flag">Every gated close so far is one you took by hand. Until the rules take an exit of their own, this sample measures your timing, not the ruleset's.</p>`;
    }

    h += `<h3 class="sys-h">Not visible from here</h3>`;
    h += `<p class="sys-note"><b>Healer</b> — /api/heartbeat dispatches a scan when the book is overdue, so probing it would move what it measures. Its condition is the ${HEAL_STALE_MIN}m mark above; whether it actually fired is only in the Actions log.</p>`;
    h += `<p class="sys-note"><b>Stop watcher</b> — runs every 5 min in Actions and commits nothing, so a browser has no read-only view of its freshness. Making it visible needs a committed heartbeat or a KV stamp; neither exists yet.</p>`;
    h += `<p class="sys-note"><b>CI failures</b> — live in GitHub's API, not in any published file. The link below is the authoritative list rather than a count made up here.</p>`;
    h += `<div class="sys-acts">` +
      `<a class="sys-act" href="https://github.com/${REPO}/actions?query=is%3Afailure" target="_blank" rel="noopener">View latest failure ↗</a>` +
      `<a class="sys-act" href="/api/health" target="_blank" rel="noopener">/api/health ↗</a>` +
      `<a class="sys-act" href="system.html">System doc</a>` +
      `</div>`;
    h += `<p class="sys-foot">Read-only. This panel issues GET requests to published files and /api/health, and changes nothing.</p>`;
    return h;
  }

  // ── sheet plumbing ────────────────────────────────────────────────────────
  let scrim = null;

  function buildSheet() {
    if (scrim) return scrim;
    scrim = document.createElement("div");
    scrim.className = "sys-scrim";
    scrim.hidden = true;
    scrim.innerHTML =
      `<section class="sys-sheet" role="dialog" aria-modal="true" aria-label="System status">` +
      `<div class="sys-grip"></div>` +
      `<button class="sys-x" type="button" aria-label="Close">✕</button>` +
      `<div class="sys-body" id="sys-body"></div>` +
      `</section>`;
    document.body.appendChild(scrim);
    scrim.addEventListener("click", (e) => { if (e.target === scrim) closeSheet(); });
    scrim.querySelector(".sys-x").addEventListener("click", closeSheet);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheet(); });
    return scrim;
  }

  function openSheet() {
    const s = buildSheet();
    const body = s.querySelector("#sys-body");
    const btn = document.getElementById("sysdot");
    if (btn) btn.setAttribute("aria-expanded", "true");
    body.innerHTML = `<p class="sys-empty">reading…</p>`;
    s.hidden = false;
    requestAnimationFrame(() => s.classList.add("is-open"));
    // Refresh the light's own inputs on open — a sheet opened on a tab that
    // has sat for an hour must not describe the hour-old fetch.
    loadLight().then(paintLamp).catch(() => {})
      .then(loadSheet)
      .then(() => { body.innerHTML = sheetHTML(); })
      .catch(() => { body.innerHTML = `<p class="sys-empty">status unavailable — check your connection.</p>`; });
  }

  function closeSheet() {
    if (!scrim || scrim.hidden) return;
    scrim.classList.remove("is-open");
    const btn = document.getElementById("sysdot");
    if (btn) btn.setAttribute("aria-expanded", "false");
    setTimeout(() => { if (scrim) scrim.hidden = true; }, 200);
  }

  // ── mount ─────────────────────────────────────────────────────────────────
  // The lamp goes in the TOP BAR on every page that carries the shared nav.
  // It cannot live inside #site-nav itself: .nav-pills is display:none under
  // 680px, which would hide the control on precisely the device the owner
  // asked for it on. .deck-top-right survives the breakpoint, so that is the
  // preferred host and the header is the fallback.
  function mount() {
    if (document.getElementById("sysdot")) return;
    const nav = document.getElementById("site-nav");
    const header = (nav && nav.closest("header")) || document.querySelector("header.topbar");
    if (!header) return;
    const btn = document.createElement("button");
    btn.id = "sysdot";
    btn.className = "sysdot";
    btn.type = "button";
    btn.setAttribute("aria-haspopup", "dialog");
    btn.setAttribute("aria-expanded", "false");
    btn.dataset.level = "unknown";
    btn.innerHTML = lampHTML("green", "reading…");
    btn.addEventListener("click", openSheet);
    const right = header.querySelector(".deck-top-right");
    if (right) right.insertBefore(btn, right.firstChild);
    else { btn.classList.add("sysdot-solo"); header.appendChild(btn); }
    loadLight().then(paintLamp).catch(() => {});
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();

  // Test hook only — the suite slices these out of the file and runs them.
  // Nothing on the page reads window.GBSStatus.
  window.GBSStatus = { overall, uptime, bookState, cohort, mergeStamps, marketAges, triggerMix, agoText };
})();
