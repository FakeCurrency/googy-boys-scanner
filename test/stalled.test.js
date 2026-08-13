#!/usr/bin/env node
/* Tests for public/js/stalled.js — the stalled-position decision surface.
 *
 * The surface exists to show, read-only, exactly the cohort the stale probe
 * (scanner/broker/vivek_run._stale_probe) has already stamped `stale_pinged`.
 * These tests pin the three things that matter:
 *
 *   1. The cohort is the ENGINE's, not this file's — a row is listed iff it is
 *      open and carries the stamp. No threshold lives here.
 *   2. The numbers are honest: day arithmetic in the book's own calendar,
 *      summary R/dollars/slots from the rows and rules as published.
 *   3. It has exactly ONE write path (POST /api/close, journal_type=bot),
 *      it takes two clicks, and nothing in the file can trigger it alone.
 *
 * Runs the REAL functions, sliced out of the shipped file at load time rather
 * than re-typed here (house pattern — a mirrored copy drifts in step with the
 * bug it is supposed to catch). Run with: node test/stalled.test.js
 */
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓  ${name}`); passed++; }
  catch (e) {
    const loc = (e.stack || "").split("\n").slice(1).find((l) => l.includes("stalled.test.js"));
    console.error(`  ✗  ${name}\n     ${e.message}${loc ? "\n     " + loc.trim() : ""}`);
    failed++;
  }
}
function suite(name) { console.log(`\n── ${name} ──`); }

// ── pull the real functions out of the shipped file ──────────────────────────
const SRC_PATH = path.resolve(__dirname, "../public/js/stalled.js");
const SRC = fs.readFileSync(SRC_PATH, "utf8");

// Ask the PARSER where each definition ends rather than matching an end
// marker: an arrow body full of `return {...};` has many plausible `;`
// terminators, and only the parser knows which one closes the expression
// (the house pattern from test/escaping.test.js's extractConst).
function sliceConst(name) {
  const at = SRC.search(new RegExp(`\\bconst\\s+${name}\\s*=`));
  assert.ok(at >= 0, `stalled.js no longer defines "${name}" — was it renamed?`);
  const start = SRC.indexOf("=", at) + 1;
  for (let i = SRC.indexOf(";", start); i > 0 && i - start < 8000; i = SRC.indexOf(";", i + 1)) {
    const candidate = SRC.slice(start, i).trim();
    try {
      new Function(`return (${candidate});`); // parse-only
      return `const ${name} = ${candidate};`;
    } catch (_) { /* unbalanced — keep walking */ }
  }
  assert.fail(`could not slice "${name}" out of stalled.js`);
}

// Same-realm sandbox (new Function, not vm) per the Tier 5 note: a vm context
// is a separate realm and cross-realm deepStrictEqual fails on Array.prototype.
const NAMES = ["esc", "stalledRows", "daysBetween", "bookDay", "framing",
               "summarize", "fmtR", "slotsClause", "closePrice", "fmtPx"];
const body = NAMES.map(sliceConst).join("\n") +
  `\nreturn { ${NAMES.join(", ")} };`;
const { esc, stalledRows, daysBetween, bookDay, framing, summarize, fmtR, slotsClause,
        closePrice, fmtPx } = new Function(body)();

// CODE-only view of the shipped file. Every ban below asks whether stalled.js
// DOES something, and a plain substring cannot answer that here: the reasoning
// for each ban is written into the source beside it, so the header's promise
// "no localStorage" contains the string "localStorage", and the note explaining
// why journal_type must never be "swing" contains "swing". A naive `includes`
// reads the justification as the offence — the exact trap the workflow tests
// hit (CLAUDE.md, Tier 3). Ask about code, read code.
const CODE = SRC.split("\n")
  .filter((l) => { const t = l.trim(); return t && !t.startsWith("//") && !t.startsWith("*") && !t.startsWith("/*"); })
  .join("\n");

const row = (over) => Object.assign({
  symbol: "GLBE", market: "nasdaq", direction: "long", status: "open",
  entry_date: "2026-07-09", stale_pinged: "2026-07-28",
  unreal_r: 0.172, risk_usd: 1830.93, grade: "A+", tp1_hit: false,
}, over || {});

// ── 1. the cohort is the engine's ────────────────────────────────────────────
suite("cohort — the stamp is the whole definition");

test("only open rows carrying stale_pinged are listed", () => {
  const book = { open: [
    row(),
    row({ symbol: "MOVING", stale_pinged: undefined }),
    row({ symbol: "CLOSED", status: "closed" }),
    null,
  ] };
  assert.deepEqual(stalledRows(book).map((p) => p.symbol), ["GLBE"]);
});

test("no threshold lives in this file — a stamp is listed regardless of R or age", () => {
  // A row the probe stamped yesterday at +0.49R and one it stamped months ago
  // at -0.49R are both the engine's cohort. The surface must not re-filter.
  const book = { open: [
    row({ symbol: "FRESH", stale_pinged: "2026-08-01", unreal_r: 0.49 }),
    row({ symbol: "OLD", stale_pinged: "2026-05-01", unreal_r: -0.49 }),
  ] };
  assert.equal(stalledRows(book).length, 2);
});

test("an empty or absent book yields an empty cohort, never a throw", () => {
  assert.deepEqual(stalledRows({}), []);
  assert.deepEqual(stalledRows(null), []);
  assert.deepEqual(stalledRows({ open: null }), []);
});

// ── 2. the numbers ───────────────────────────────────────────────────────────
suite("day arithmetic — the book's calendar, not the browser's");

test("held and mark-age are whole days between ISO dates", () => {
  assert.equal(daysBetween("2026-07-09", "2026-08-01"), 23);
  assert.equal(daysBetween("2026-07-28", "2026-08-01"), 4);
  assert.equal(daysBetween("2026-08-01", "2026-08-01"), 0);
});

test("an unparseable date is null, not NaN", () => {
  // NaN propagates through comparisons as false and would sort rows
  // unpredictably; null renders as an em-dash.
  assert.equal(daysBetween(null, "2026-08-01"), null);
  assert.equal(daysBetween("garbage", "2026-08-01"), null);
});

test("the day is the book's own updated_day when it carries one", () => {
  assert.equal(bookDay({ summary: { updated_day: "2026-08-01" } }), "2026-08-01");
  // Fallback only when the book cannot say: shape must be an ISO date.
  assert.match(bookDay({}), /^\d{4}-\d{2}-\d{2}$/);
});

suite("summary — R, dollars, slots");

const BOOK = { open: [
  row(), row({ symbol: "AXON", unreal_r: -0.259, risk_usd: 1836.94 }),
  row({ symbol: "HELD", stale_pinged: undefined }),
] };
const RULES = { max_open_total: 30, max_hold_days: 28, account_equity: 150000 };

test("combined R and dollars-at-risk sum over the stalled rows only", () => {
  const s = summarize(stalledRows(BOOK), BOOK, RULES);
  assert.equal(s.n, 2);
  assert.ok(Math.abs(s.totalR - (0.172 - 0.259)) < 1e-9, String(s.totalR));
  assert.ok(Math.abs(s.riskUsd - (1830.93 + 1836.94)) < 1e-9, String(s.riskUsd));
  assert.ok(Math.abs(s.riskPct - 100 * s.riskUsd / 150000) < 1e-9, String(s.riskPct));
});

test("slots blocked are counted against the GLOBAL cap from bot_rules", () => {
  const s = summarize(stalledRows(BOOK), BOOK, RULES);
  assert.equal(s.maxOpen, 30);
  assert.equal(s.open, 3);
  assert.equal(s.free, 27);
  assert.equal(s.atCap, false);
});

test("a full book reads FULL and names the stalled rows as the only source of slots", () => {
  const open = Array.from({ length: 30 }, (_, i) => row({ symbol: "S" + i, stale_pinged: i < 8 ? "2026-07-28" : undefined }));
  const s = summarize(stalledRows({ open }), { open }, RULES);
  assert.equal(s.atCap, true);
  assert.equal(s.free, 0);
  const clause = slotsClause(s);
  assert.ok(clause.includes("8 of 30"), clause);
  assert.ok(clause.includes("FULL"), clause);
  assert.ok(clause.includes("only slots a new A+ can come from"), clause);
});

test("missing rules degrade the summary, never break it", () => {
  const s = summarize(stalledRows(BOOK), BOOK, null);
  assert.equal(s.maxOpen, null);
  assert.equal(s.riskPct, null);
  assert.ok(!slotsClause(s).includes("null"), slotsClause(s));
});

test("a NaN or missing unreal_r contributes zero, not NaN, to the totals", () => {
  // A NaN in a sum makes every later comparison false — the Tier 4 lesson.
  const b = { open: [row({ unreal_r: NaN, risk_usd: undefined })] };
  const s = summarize(stalledRows(b), b, RULES);
  assert.ok(isFinite(s.totalR) && s.totalR === 0, String(s.totalR));
  assert.ok(isFinite(s.riskUsd) && s.riskUsd === 0, String(s.riskUsd));
});

// ── 3. the framing ───────────────────────────────────────────────────────────
suite("your call — keep / time-stop / free capacity");

test("a pre-TP1 stall names the time-stop and the days remaining", () => {
  const f = framing(row(), 23, 28);
  assert.equal(f.kind, "timed");
  assert.ok(f.label.includes("time-stop in 5d"), f.label);
  assert.ok(f.detail.includes("Keep it"), f.detail);
  assert.ok(f.detail.includes("free the slot"), f.detail);
});

test("a pre-TP1 stall past the hold limit reads due", () => {
  const f = framing(row(), 30, 28);
  assert.equal(f.kind, "due");
  assert.ok(f.label.includes("due"), f.label);
});

test("a runner past TP1 says the time-stop never applies and only a manual close frees the slot", () => {
  const f = framing(row({ tp1_hit: true }), 33, 28);
  assert.equal(f.kind, "runner");
  assert.ok(f.detail.includes("never applies"), f.detail);
  assert.ok(f.detail.includes("manual close"), f.detail);
});

test("the framing never claims an action was or will be taken by this surface", () => {
  for (const f of [framing(row(), 23, 28), framing(row({ tp1_hit: true }), 33, 28)]) {
    assert.ok(!/\b(closed|closing now|will close|I will)\b/i.test(f.label + " " + f.detail),
      f.label + " / " + f.detail);
  }
});

// ── 4. the ONE write path, and its guards ────────────────────────────────────
// This surface shipped read-only and no longer is (owner-ruled 2026-08-07): a
// Close button per row. What did NOT change is who decides — nothing in this
// file closes anything on a condition, a timer or a threshold. These tests
// pin that distinction, because it is the only thing standing between "a
// button the owner presses" and "a surface that started trading".
suite("write path — exactly one, owner-initiated, and nothing else");

test("the only endpoint it writes to is /api/close, exactly once", () => {
  const posts = [...SRC.matchAll(/fetch\(\s*"([^"]+)"[\s\S]{0,120}?method:\s*"POST"/g)]
    .map((m) => m[1]);
  assert.deepEqual(posts, ["/api/close"],
    "a second write endpoint appeared, or the close moved: " + JSON.stringify(posts));
  assert.equal((SRC.match(/method:\s*"POST"/g) || []).length, 1, "more than one POST in the file");
});

test("journal_type is hard-coded bot — swing and scalp never appear", () => {
  assert.ok(/journal_type:\s*"bot"/.test(SRC), "the close must name journal_type bot explicitly");
  // A wrong journal_type would silently write the RETIRED localStorage swing
  // or scalp journals instead of the one track record, return a cheerful 202,
  // and leave the row sitting here — the worst possible failure, because it
  // looks like it worked.
  for (const bad of ['"swing"', "'swing'", '"scalp"', "'scalp'"]) {
    assert.ok(!CODE.includes(bad), `stalled.js sends ${bad} — the bot book is the only target`);
  }
});

test("no store writes and no second transport were smuggled in", () => {
  for (const bad of ["localStorage", "sessionStorage", "indexedDB", "XMLHttpRequest",
                     "sendBeacon", "workflow_dispatch", "/api/scan", "/api/journal",
                     "/api/tick", "/api/heartbeat"]) {
    assert.ok(!CODE.includes(bad), `stalled.js contains "${bad}"`);
  }
});

test("it still READS only the two published artifacts", () => {
  const urls = [...SRC.matchAll(/get\("([^"]+)"\)/g)].map((m) => m[1]);
  assert.deepEqual(urls.sort(), ["data/bot_rules.json", "data/vivek_bot_book.json"]);
  // The landing watcher re-reads the SAME book artifact and nothing else.
  const polled = [...SRC.matchAll(/fetch\("(data\/[^"?]+)/g)].map((m) => m[1]);
  assert.deepEqual([...new Set(polled)], ["data/vivek_bot_book.json"]);
});

if (/st-go/.test(SRC)) {   // transitional: pre-batch source skips this pin
test("N picks become ONE request — the batch IS the concurrency fix", () => {
  // 2026-08-07: six of seven rapid closes were lost because each was its own
  // workflow run and the runs raced each other (mutex eviction + book rebase
  // conflicts). 2026-08-13: nine serial runs proved safe but unusably slow.
  // The batch removes the race by construction: the collision was only ever
  // between RUNS, so N closes ride in one run, one commit, one deploy.
  assert.ok(/closes:\s*entries\.map/.test(SRC), "the POST body no longer carries the closes array");
  assert.ok(/let inFlight = null;/.test(SRC), "the in-flight lock is gone");
  assert.ok(/if \(inFlight\) return;/.test(SRC), "the pick handler no longer refuses mid-flight");
  // While the ONE flight is up, every live button is held — a second batch
  // racing the first is exactly the two-runs collision the batch removed.
  assert.ok(/st-wait/.test(SRC), "the held state is gone");
  // Every terminal path must restore the strip: the two rejection paths
  // re-enable and RESTORE THE PICKS (one rate-limit minute must not cost the
  // whole selection), and the timeout path releases the holds.
  assert.equal((SRC.match(/picked\.set\(e\.mkt/g) || []).length, 2,
    "a rejected batch no longer restores the selection on every failure path");
  assert.ok(/releaseHolds\(host\)/.test(SRC), "nothing releases the held buttons");
});
}

if (/st-go/.test(SRC)) {   // transitional: pre-batch source skips this pin
test("'closed' is only claimed once the BOOK says so, never off the 202", () => {
  // A queued dispatch is not a landed close — that gap is exactly where the
  // six went missing, each one reporting success it never achieved. The batch
  // settles PER ROW: each symbol earns its ✓ by leaving the published book,
  // and a symbol the run skipped honestly times out to "check the book".
  assert.ok(/watchLanding\(host\)/.test(SRC));
  assert.ok(/landed \? "closed ✓"/.test(SRC));
  // In CODE (comments stripped), "closed ✓" may appear in three places, all
  // legitimate: the per-row settle ternary, the all-landed bar line that only
  // renders inside the pending.size === 0 branch (after the book confirmed
  // everything), and the st-foot explainer PROSE describing the rule itself.
  const allLanded = CODE.indexOf("pending.size === 0");
  assert.ok(allLanded > 0, "the all-landed branch is gone");
  const foot = CODE.indexOf('class="st-foot"');
  assert.ok(foot > 0, "the explainer paragraph is gone");
  const scrubbed = CODE.replace(/landed \? "closed ✓"/, "")
    .replace(CODE.slice(allLanded, CODE.indexOf("return;", allLanded)), "")
    .replace(CODE.slice(foot, CODE.indexOf("</p>", foot)), "");
  assert.ok(!/closed ✓/.test(scrubbed),
    "something claims 'closed' without consulting the book");
  // The poll window must survive the WORST honest case: close_position holds
  // the scan mutex and a scan takes ~13 min, so a healthy batch can sit
  // queued that long. The old 3-minute window read that as failure — the
  // all-waiting screenshot of 2026-08-13 — and flipped healthy closes to
  // "check the book" while they were still queued.
  const ms = SRC.match(/POLL_MS\s*=\s*(\d+)/), tries = SRC.match(/POLL_TRIES\s*=\s*(\d+)/);
  assert.ok(ms && tries, "the poll constants are gone");
  assert.ok(Number(ms[1]) * Number(tries[1]) >= 15 * 60 * 1000,
    "the landing watch gives up before a mutex-queued run can finish (needs >= 15 min)");
});
}

if (/st-go/.test(SRC)) {   // transitional: pre-batch source skips this pin
test("nothing is sent by picking — only the bar's confirm calls send()", () => {
  // The two-act property the old two-click design had, kept across the batch
  // redesign: a row click only toggles a pick (visible, reversible), and the
  // ONE control that sends states the count it is about to close. A single
  // mis-click beside a "time-stop due" chip can pick, never close.
  const rowHandler = SRC.slice(SRC.indexOf('closest("button.st-x")'), SRC.indexOf("paintPicks(host);"));
  assert.ok(!/send\(/.test(rowHandler),
    "the row-button handler can reach send() — a single click may now be closing positions");
  assert.ok(/closest\("button\.st-go"\)/.test(SRC), "the confirm control is gone");
  assert.equal((SRC.match(/send\(host\)/g) || []).length, 1,
    "send() must be reachable from exactly one place: the bar's confirm");
  assert.ok(/Close \$\{n\} now/.test(SRC), "the confirm no longer states the count it will close");
  assert.ok(/key === "Escape"/.test(SRC), "Escape must empty the basket");
});
}

test("the price is the row's own last_mark, and no mark means no close", () => {
  assert.equal(closePrice({ last_mark: 19.335 }), 19.335);
  // FAIL-CLOSED, every way a mark can be missing or nonsense. Guessing a price
  // here writes a wrong number into the only track record the system has.
  for (const bad of [undefined, null, 0, -1, NaN, Infinity, "19.33", {}]) {
    assert.equal(closePrice({ last_mark: bad }), null, "accepted a bad mark: " + String(bad));
  }
  assert.equal(closePrice(null), null);
  assert.equal(closePrice({}), null);
});

if (/st-go/.test(SRC)) {   // transitional: pre-batch source skips this pin
test("the numbers the owner reads before confirming come from the rows themselves", () => {
  // Sub-dollar names need the extra places or a crypto mark reads as $0.00.
  assert.equal(fmtPx(19.335), "$19.34");
  assert.equal(fmtPx(0.33367), "$0.3337");
  // The bar's combined R is read back from the RENDERED cells, so the confirm
  // can never disagree with the column sitting beside it.
  assert.ok(/\.st-r/.test(SRC) && /pickedR/.test(SRC),
    "the bar no longer derives its total from the rendered rows");
  // And what is SENT is each row's own data attributes — the same mark its
  // Open R was computed from.
  assert.ok(/px:\s*parseFloat\(btn\.dataset\.px\)/.test(SRC),
    "the pick no longer captures the row's own last mark");
  assert.ok(/price:\s*e\.px/.test(SRC),
    "the POST no longer sends the captured mark as the close price");
});
}

test("nothing in this file decides to close anything", () => {
  // The whole ruling in one assertion: send() may only be reached from a click
  // handler. No timer, no threshold, no auto-retry may call it.
  const autoSend = /set(Timeout|Interval)\([^)]*\bsend\(/.test(SRC);
  assert.ok(!autoSend, "send() is reachable from a timer — this surface must never close on its own");
  assert.ok(!/if\s*\([^)]*unreal_r[^)]*\)\s*send\(/.test(SRC), "a condition calls send()");
});

test("the ticker opens the chart with the house URL convention", () => {
  assert.ok(/chart\.html\?m=\$\{encodeURIComponent/.test(SRC),
    "the symbol link must follow chart.html?m=<market>&s=<SYM>&mode=vivek");
  assert.ok(/mode=vivek/.test(SRC));
  // Same escaping discipline as every other cell: the href is built from book
  // data, so it is encoded going in and escaped going into the attribute.
  assert.ok(/href="\$\{esc\(href\)\}"/.test(SRC), "the href must be attribute-escaped");
});

test("esc escapes all five breakout characters and is null-safe", () => {
  assert.equal(esc(`&<>"'`), "&amp;&lt;&gt;&quot;&#39;");
  assert.equal(esc(null), "");
});

// ── 5. the page actually loads it ────────────────────────────────────────────
suite("wiring — a surface nobody sees is not a surface");

test("journal.html hosts #stalled-strip and requests stalled.js and stalled.css", () => {
  const html = fs.readFileSync(path.resolve(__dirname, "../public/journal.html"), "utf8");
  assert.ok(html.includes('id="stalled-strip"'), "host section missing from journal.html");
  assert.match(html, /js\/stalled\.js\?v=\d+/, "script tag missing or unversioned");
  assert.match(html, /css\/stalled\.css\?v=\d+/, "stylesheet missing or unversioned");
});

test("the host section starts hidden, so a missing file costs nothing", () => {
  const html = fs.readFileSync(path.resolve(__dirname, "../public/journal.html"), "utf8");
  assert.match(html, /id="stalled-strip"[^>]*hidden|hidden[^>]*id="stalled-strip"/,
    "the strip must ship hidden and only appear when the book carries a mark");
});

// ─────────────────────────────── summary ─────────────────────────────────────
console.log(`\n${"─".repeat(48)}`);
if (failed) {
  console.error(`FAILED  ${failed} test(s) failed, ${passed} passed`);
  process.exit(1);
} else {
  console.log(`ALL ${passed} tests passed`);
}
