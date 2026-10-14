/* Vivek 5.0 — STATUS control (2026-08-19, owner-ruled Session 1).
 *
 * One lamp in the top bar on every nav page, and a tap sheet behind it that
 * answers "is the machine working?" without making the owner open GitHub.
 *
 * READ-ONLY BY CONSTRUCTION, and that is the whole design brief:
 *
 *   - It issues GET requests only, to published assets and to /api/health.
 *   - It NEVER touches /api/heartbeat. That endpoint is the scheduler's door:
 *     cron-job.org pings it and, when a market's prices are stale, it
 *     DISPATCHES a scan and spends one of that market's daily heal budget (30).
 *     A status light that polled it would start moving the thing it measures —
 *     every page load a possible workflow dispatch, and a monitor that mutates
 *     its subject is not a monitor. Its condition is instead DERIVED from the
 *     book age, and the sheet says so rather than implying it probed.
 *   - It never touches /api/scan or /api/close (or the removed /api/tick), and it writes
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
 *   90m = functions/api/heartbeat.js DEFAULT_STALE_MIN — the WHOLE-PIPELINE
 *         (market=all) line at which the healer considers the book overdue.
 *         Used here for AMBER, against the combined book's age. It is
 *         APPROXIMATE for any one market: each cron-job.org ping passes its
 *         own stale_min, and heartbeat floors those per market (asx 15 /
 *         nasdaq 15 / crypto 45 minutes; all 90), so a single market heals on
 *         a shorter line than this. The sheet says so beside the number.
 *
 * ONE BOOK READ PER PAGE (REFINE200 #68). The LAMP no longer downloads the
 * ~370 KB bot book at all: /api/health already reads it server-side and
 * answers with the breached loss guards, which is the one thing the lamp
 * wanted from it. The book is read only when the SHEET opens, through nav.js's
 * shared window.VivekBook loader, so a page that also shows the book (the
 * journal) pays for it once. A health answer without `breached` (an older
 * deploy) falls back to reading the book for the lamp, as before.
 *
 * STALLED ROWS DO NOT LIGHT THE LAMP (REFINE200 #189). A stale_pinged row is
 * routine — most are waiting on the 28-day time-stop the rules apply — and
 * with half the book stamped the lamp read CHECK on every page for days. The
 * same argument as the guard breach below: an alarm that fires on the machine
 * doing what it was built to do is an alarm that gets muted. The sheet still
 * lists them under Book, as information.
 *   60  = the position cap, read from data/bot_rules.json rather than typed
 *         (project rule 3 — never hardcode a published constant twice). 30
 *         until the owner's 2026-09-27 resize to 60 × $2,500.
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
 * probeable read-only, and CI failures live in GitHub's API. (The 5-minute
 * stop-watcher was listed here until it was removed, 2026-09-21.) "View latest failure" is a deep
 * link to the authoritative list rather than a number this file made up.
 */
(() => {
  "use strict";

  // ── constants, each one sourced ────────────────────────────────────────────
  const HEALTH_MAX_H = 4;      // functions/api/health.js (max_h default)
  const HEAL_STALE_MIN = 90;   // functions/api/heartbeat.js (DEFAULT_STALE_MIN) — whole pipeline only
  // = config VIVEK_BOT_MAX_OPEN_TOTAL (60 since 2026-09-27); pinned to it by
  // tests/test_close_ceiling_parity.py so the offline sheet cannot read
  // "Open 45 / 30" on a 60-slot book.
  const FALLBACK_CAP = 60;     // only if bot_rules.json is unreachable
  // = config VIVEK_BOT_CYCLE_TAG (w3-1 ended 2026-09-21). The LIVE tag is read
  // from bot_rules.json's cycle_tag (REFINE200 #125) so the next cycle cannot
  // keep counting the dead cohort under the old heading; this literal is the
  // offline fallback only, pinned to config by tests/test_close_ceiling_parity.py.
  const CYCLE_TAG = "hc4-1";
  const CYCLE_TARGET = 30;     // the pre-registered close count for the cohort
  const REPO = "FakeCurrency/googy-boys-scanner";
  // Mirrors journal.js MECHANICAL_EXITS. test/status.test.js parses BOTH files
  // and fails if they diverge, so this copy cannot drift silently.
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

  // The cycle the bot is in now: bot_rules.json's cycle_tag, else the fallback.
  const cycleTagOf = (rules) =>
    (rules && typeof rules.cycle_tag === "string" && rules.cycle_tag.trim()) || CYCLE_TAG;

  // The live cycle's cohort, straight off the audit tag vivek_run stamps on each row.
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
  // is cron", which is an answer, not an absence. Since 2026-10-06 `heartbeat`
  // is the NORMAL clock: cron-job.org pings /api/heartbeat on each market's own
  // schedule and it dispatches the scan, with GitHub's own crons as the backup
  // (REFINE200 #189) — so a heartbeat count is the healthy majority, not a
  // missed cron.
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
    if (s.bookAgeH * 60 > HEAL_STALE_MIN) return { level: "amber", why: `last scan ${agoText(s.bookAgeH * 36e5)} — past the whole pipeline's ${HEAL_STALE_MIN}m overdue mark` };
    if (s.breached && s.breached.length) return { level: "amber", why: `loss guard breached: ${s.breached.map((b) => b.market).join(", ")} — new entries halted` };
    // (Stalled rows are not a lamp level — see REFINE200 #189 in the header.)
    if (s.bookReadable === false) return { level: "amber", why: "pipeline fresh, but the book file didn't load here" };
    return { level: "green", why: `scanning normally — last scan ${agoText(s.bookAgeH * 36e5)}` };
  };

  // "Integrity passed" is a claim about a SPECIFIC book: vivek_run --verify
  // gates every commit, so a book that loaded and is inside the 4h alarm was
  // verified when it landed. A book that did not load, or one older than the
  // alarm, cannot vouch for anything — the sheet says unknown rather than
  // printing a constant "passed" over a book it never saw (REFINE200 #188).
  const integrity = (book, nowMs) => {
    const t = Date.parse(String((book && book.updated_at) || ""));
    if (!book || !isFinite(t)) return { passed: false, why: "the book didn't load here, so there is nothing to vouch for" };
    if (nowMs - t > HEALTH_MAX_H * 36e5) {
      return { passed: false, why: `the book is ${agoText(nowMs - t)} old — past the ${HEALTH_MAX_H}h alarm` };
    }
    return { passed: true, why: "vivek_run --verify gates the commit — a failed book never lands, so a fresh commit IS a passed verify" };
  };

  const pct1 = (n) => (isFinite(n) ? (Math.round(n * 100) / 100).toFixed(2) : "—");
  const LAMP = { green: "●", amber: "●", red: "●" };
  const WORD = { green: "OK", amber: "CHECK", red: "DOWN" };

  // ── data ──────────────────────────────────────────────────────────────────
  const getJSON = (url, opts) => fetch(url, opts || { cache: "no-cache" })
    .then((r) => (r.ok ? r.json().then((j) => ({ ok: true, status: r.status, json: j }))
                       : r.json().then((j) => ({ ok: false, status: r.status, json: j }), () => ({ ok: false, status: r.status, json: null }))))
    .catch(() => null);

  const STATE = { sig: null, book: null, bookTried: false, funnel: null, rules: null, health: null, loadedAt: 0 };

  // The page's ONE read of the book / the rules (nav.js window.VivekBook,
  // REFINE200 #68), shaped like getJSON's answer so the code below reads both
  // the same way. getJSON is the fallback for a page without the shared
  // loader.
  const shared = (kind, fresh) => {
    const VB = window.VivekBook;
    if (!VB) return getJSON(kind === "book" ? "data/vivek_bot_book.json" : "data/bot_rules.json");
    return (kind === "book" ? VB.get({ fresh }) : VB.rules({ fresh })).then(
      (j) => ({ ok: true, status: 200, json: j }),
      (e) => (e && e.status ? { ok: false, status: e.status, json: null } : null));
  };

  // Breaches as /api/health reports them (it reads the book server-side), or
  // null when the answer predates the field.
  const healthBreaches = (hj) => (hj && Array.isArray(hj.breached)
    ? hj.breached.filter((b) => b && b.market)
      .map((b) => ({ market: String(b.market), kind: String(b.kind || "loss limit") }))
    : null);

  // The LIGHT reads /api/health (a small answer to the exact question the
  // lamp asks — is a scan fresher than the alarm threshold, and is any loss
  // guard breached — computed server-side and never cached) and
  // bot_rules.json for the cap. The book itself is read only when `withBook`
  // (the sheet is opening) or when health did not say about breaches.
  function loadLight(withBook) {
    return Promise.all([getJSON("/api/health"), shared("rules", withBook)]).then(([h, r]) => {
      STATE.health = h;
      STATE.rules = r && r.ok ? r.json : null;
      const hj = h && h.json ? h.json : null;
      const fromHealth = healthBreaches(hj);
      const needBook = withBook || !fromHealth;
      return (needBook ? shared("book", withBook) : Promise.resolve(undefined)).then((b) => {
        if (b !== undefined) { STATE.book = b && b.ok ? b.json : null; STATE.bookTried = true; }
        const cap = STATE.rules && typeof STATE.rules.max_open_total === "number"
          ? STATE.rules.max_open_total : NaN;
        const bs = bookState(STATE.book, cap);
        STATE.sig = {
          healthReachable: !!h,
          healthOk: h ? !!(hj && hj.ok) : null,
          bookAgeH: hj && typeof hj.age_h === "number" ? hj.age_h : null,
          // Only a book this page actually TRIED to read can be unreadable.
          bookReadable: STATE.bookTried ? !!STATE.book : null,
          breached: STATE.book ? bs.breached : (fromHealth || []),
          stalled: bs.stalled,
        };
        STATE.book_state = bs;
        STATE.loadedAt = Date.now();
        return STATE;
      });
    });
  }

  // The funnel ledger (~120 KB, growing to 2,000 rows per market) is fetched
  // ONLY when the sheet opens. It is the
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
    const tag = cycleTagOf(STATE.rules);
    const ch = cohort(STATE.book, tag);
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
      `whole pipeline: overdue at ${HEAL_STALE_MIN}m · alarm at ${HEALTH_MAX_H}h (each market's own heal ping uses a shorter line)`);
    const ledgerFrom = stamps.length ? String(new Date(stamps[0]).toISOString().slice(0, 10)) : "";
    h += row("Uptime · 7d", upVal(u7), upNote(u7, `measured on committed scans`));
    h += row("Uptime · 30d", upVal(u30),
      upNote(u30, u30 && u30.clamped && ledgerFrom ? `the ledger starts ${ledgerFrom}` : ""));
    // Trigger mix (7d): hidden until the trigger column exists on some market
    // — an invented "all cron" is worse than silence. Plain text, no amber:
    // heartbeat-dispatched scans are the primary clock (cron-job.org), not a
    // missed cron (REFINE200 #189).
    const tm = triggerMix(STATE.funnel, now, 7);
    if (tm) {
      const bits = [`<b>${tm.heartbeat} cron-job.org</b>`, `${tm.cron} GitHub cron`];
      if (tm.manual) bits.push(`${tm.manual} manual`);
      if (tm.unknown) bits.push(`${tm.unknown} unstamped`);
      h += row("Scan triggers · 7d", bits.join(" · "),
        "cron-job.org = the primary clock: it pings /api/heartbeat on each market's schedule and a stale market gets its scan. GitHub's own crons are the backup.");
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

    // A book that did not load is UNKNOWN, never an all-clear row of zeros
    // (REFINE200 #188 — the journal stopped painting a fake empty book on
    // 2026-10-13; this sheet was still doing it). Breaches can still be named
    // when /api/health reported them, because health read the book itself.
    const book = STATE.book;
    const unknown = `<b>unknown</b>`;
    const guards = book ? bs.breached : healthBreaches(STATE.health && STATE.health.json);
    h += `<h3 class="sys-h">Book</h3>`;
    if (book) {
      h += row("Open", `<b>${bs.open}</b> / ${bs.cap}`, `${bs.free} slot${bs.free === 1 ? "" : "s"} free · ${bs.closed} closed`);
      // Information, not a warning: a stamped row is usually waiting on the
      // 28-day time-stop the rules apply (REFINE200 #189).
      h += row("Stalled", `<b>${bs.stalled.length}</b>`,
        bs.stalled.length ? `stamped by the stale probe — routine; the rules' time-stop handles them: ${bs.stalled.join(", ")}`
                          : "no positions stamped by the stale probe");
    } else {
      h += row("Open", unknown, "the book file didn't load here — open positions, stalls and the cycle can't be read");
    }
    h += row("Loss guards", !guards ? unknown : guards.length
      ? `<b class="sys-amber">${guards.map((b) => esc(b.market) + " " + esc(b.kind)).join(", ")}</b>`
      : `<b>clear</b>`, !guards ? "the book didn't load" : guards.length ? "new entries halted for that market" : "daily + trailing-week, per market");
    const iv = integrity(book, now);
    h += row("Integrity", iv.passed ? `<b>passed</b>` : unknown, iv.why);

    h += `<h3 class="sys-h">${esc(tag)} cycle</h3>`;
    h += row("Gated open", book ? `<b>${ch.open}</b>` : unknown, "opened under the A/A+ four-cell rules (weekly/3d level gate)");
    h += row("Closes", book ? `<b>${ch.closed}</b> of ${CYCLE_TARGET}` : unknown,
      !book ? "the book didn't load" : ch.closed ? `${ch.byRules} by the rules · ${ch.byOwner} by you` : "readout at the pre-registered count");
    if (book && ch.closed && !ch.byRules) {
      // Same sentence the journal's w3-1 strip uses, deliberately, so the two
      // surfaces read alike. Note the cohorts differ since 2026-09-21: this
      // line is the current hc4-1 cycle, the journal's strip lists w3-1 exits.
      h += `<p class="sys-flag">Every gated close so far is one you took by hand. Until the rules take an exit of their own, this sample measures your timing, not the ruleset's.</p>`;
    }

    h += `<h3 class="sys-h">Not visible from here</h3>`;
    h += `<p class="sys-note"><b>Scheduler</b> — cron-job.org pings /api/heartbeat, which dispatches a market's scan when its prices are stale (each ping carries that market's own staleness line, and each market has a daily heal budget of 30), so probing it from here would move what it measures. The ${HEAL_STALE_MIN}m mark above is the whole-pipeline line and only approximates any one market's. Whether a given ping dispatched is only in cron-job.org's history and the Actions log.</p>`;
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
  let hideTimer = 0;

  // Page scroll lock while the sheet is open — a wheel or a swipe on the scrim
  // used to scroll the page behind it. A CLASS on <html> (status.css), not an
  // inline overflow, so closeSheet releases it with one remove whichever way
  // the sheet was closed, and nothing another script set on <html> is
  // overwritten. The width of the scrollbar it hides is handed to the CSS as
  // --sys-sbw so the page does not jump sideways. A style property: nothing is
  // stored, so the read-only promise above still holds.
  function lockScroll(on) {
    const html = document.documentElement;
    if (on) {
      const sbw = window.innerWidth - html.clientWidth;
      html.style.setProperty("--sys-sbw", `${sbw > 0 ? sbw : 0}px`);
      html.classList.add("sys-lock");
    } else {
      html.classList.remove("sys-lock");
      html.style.removeProperty("--sys-sbw");
    }
  }

  function buildSheet() {
    if (scrim) return scrim;
    scrim = document.createElement("div");
    scrim.className = "sys-scrim";
    scrim.hidden = true;
    scrim.innerHTML =
      `<section class="sys-sheet" role="dialog" aria-modal="true" aria-label="System status">` +
      `<div class="sys-grip"></div>` +
      `<button class="sys-x" type="button" aria-label="Close">✕</button>` +
      `<div class="sys-body" id="sys-body" tabindex="0"></div>` +
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
    // A reopen inside the 200ms close must not be hidden by that close's timer
    // (it would vanish the sheet and leave the page locked).
    clearTimeout(hideTimer);
    s.hidden = false;
    lockScroll(true);
    // Focus goes INTO the dialog (aria-modal tells assistive tech the page
    // behind is inert), onto the one control every state of the sheet has.
    s.querySelector(".sys-x").focus({ preventScroll: true });
    requestAnimationFrame(() => s.classList.add("is-open"));
    // Refresh the light's own inputs on open — a sheet opened on a tab that
    // has sat for an hour must not describe the hour-old fetch. This is also
    // the one place the sheet reads the book itself (the lamp does not).
    loadLight(true).then(paintLamp).catch(() => {})
      .then(loadSheet)
      .then(() => { body.innerHTML = sheetHTML(); })
      .catch(() => { body.innerHTML = `<p class="sys-empty">status unavailable — check your connection.</p>`; });
  }

  // Every close path (Escape, a click on the scrim, the ✕) ends here, so the
  // scroll lock is released here and nowhere else.
  function closeSheet() {
    if (!scrim || scrim.hidden) return;
    scrim.classList.remove("is-open");
    lockScroll(false);
    const btn = document.getElementById("sysdot");
    if (btn) btn.setAttribute("aria-expanded", "false");
    // Focus back to the lamp — but only from inside the sheet, or from <body>
    // where a click on the scrim drops it; never away from somewhere the
    // reader has since put it.
    const a = document.activeElement;
    if (btn && (!a || a === document.body || scrim.contains(a))) btn.focus({ preventScroll: true });
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => { if (scrim) scrim.hidden = true; }, 200);
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
})();
