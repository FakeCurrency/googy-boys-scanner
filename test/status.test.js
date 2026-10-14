#!/usr/bin/env node
/* Tests for public/js/status.js — the top-bar STATUS lamp and its sheet.
 *
 * Three properties matter here and each has its own block below:
 *
 *   1. READ-ONLY IS THE PRODUCT. The control must never POST, never touch the
 *      healer (/api/heartbeat DISPATCHES a scan), never touch the watcher or
 *      the close path, and never write storage. A status surface that mutates
 *      its subject is not a status surface, and this is the only place that
 *      promise can be enforced rather than remembered.
 *   2. NO INVENTED NUMBERS. Uptime is measured off the committed scan ledger,
 *      the window is clamped to the ledger's span, and the CURRENT gap counts
 *      — otherwise a dead pipeline would keep reporting 100%.
 *   3. THE STATES MATRIX. Red means "the evidence is not arriving"; a loss
 *      guard breach is AMBER because it is the machine working. That
 *      distinction is the heartbeat.js lesson and is pinned, not assumed.
 *
 * Runs the REAL functions, sliced out of the shipped file (house pattern — a
 * re-typed copy drifts in step with the bug it is supposed to catch).
 * Run with: node test/status.test.js
 */
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");

let passed = 0, failed = 0;
const PENDING = [];
function report(name, e) {
  if (!e) { console.log(`  ✓  ${name}`); passed++; return; }
  const loc = (e.stack || "").split("\n").slice(1).find((l) => l.includes("status.test.js"));
  console.error(`  ✗  ${name}\n     ${e.message}${loc ? "\n     " + loc.trim() : ""}`);
  failed++;
}
// An async test is queued and awaited in order before the summary prints, so
// the count can never go green ahead of a test still running.
function test(name, fn) {
  let r;
  try { r = fn(); } catch (e) { report(name, e); return; }
  if (r && typeof r.then === "function") PENDING.push(() => r.then(() => report(name), (e) => report(name, e)));
  else report(name);
}
function suite(name) { console.log(`\n── ${name} ──`); }

const SRC_PATH = path.resolve(__dirname, "../public/js/status.js");
const SRC = fs.readFileSync(SRC_PATH, "utf8");

// Ask the PARSER where each definition ends rather than matching an end marker
// (the extractConst pattern from escaping.test.js / stalled.test.js).
function sliceConst(name) {
  const at = SRC.search(new RegExp(`\\bconst\\s+${name}\\s*=`));
  assert.ok(at >= 0, `status.js no longer defines "${name}" — was it renamed?`);
  const start = SRC.indexOf("=", at) + 1;
  for (let i = SRC.indexOf(";", start); i > 0 && i - start < 12000; i = SRC.indexOf(";", i + 1)) {
    const candidate = SRC.slice(start, i).trim();
    try { new Function(`return (${candidate});`); return `const ${name} = ${candidate};`; }
    catch (_) { /* unbalanced — keep walking */ }
  }
  assert.fail(`could not slice "${name}" out of status.js`);
}

// Function declarations, sliced the same way: the parser decides which `}`
// closes the body.
function sliceFn(name) {
  const at = SRC.search(new RegExp(`\\n  function\\s+${name}\\s*\\(`));
  assert.ok(at >= 0, `status.js no longer declares function "${name}" — was it renamed?`);
  const start = at + 1;
  for (let i = SRC.indexOf("}", start); i > 0 && i - start < 20000; i = SRC.indexOf("}", i + 1)) {
    const candidate = SRC.slice(start, i + 1);
    try { new Function(`return (${candidate});`); return candidate; }
    catch (_) { /* unbalanced — keep walking */ }
  }
  assert.fail(`could not slice function "${name}" out of status.js`);
}

const NAMES = ["HEALTH_MAX_H", "HEAL_STALE_MIN", "FALLBACK_CAP", "CYCLE_TAG", "MECHANICAL_EXITS",
               "esc", "agoText", "bookState", "cycleTagOf", "cohort", "mergeStamps", "marketAges",
               "uptime", "overall", "triggerMix", "integrity", "healthBreaches"];
const body = NAMES.map(sliceConst).join("\n") + `\nreturn { ${NAMES.join(", ")} };`;
const { HEALTH_MAX_H, HEAL_STALE_MIN, FALLBACK_CAP, CYCLE_TAG, MECHANICAL_EXITS,
        esc, agoText, bookState, cycleTagOf, cohort, mergeStamps, marketAges,
        uptime, overall, triggerMix, integrity, healthBreaches } = new Function(body)();

// CODE-only view: every ban below asks whether status.js DOES something, and
// the reasoning for each ban is written into the source beside it — the header
// explaining why /api/heartbeat must never be called contains the string
// "/api/heartbeat". Ask about code, read code.
const CODE = SRC.split("\n")
  .filter((l) => { const t = l.trim(); return t && !t.startsWith("//") && !t.startsWith("*") && !t.startsWith("/*"); })
  .join("\n");

const H = 36e5, D = 864e5;

// ── 1. read-only ─────────────────────────────────────────────────────────────
suite("read-only — the control must not move what it measures");

// Every URL this file actually REQUESTS. Extracted from the call sites rather
// than grepped out of the whole source, because the sheet legitimately NAMES
// /api/heartbeat in the "not visible from here" note — the prose explaining why
// an endpoint is never called contains its path, and a substring ban reads the
// justification as the offence (the Tier 3 trap).
const FETCHED = [...CODE.matchAll(/(?:getJSON|fetch)\(\s*"([^"]+)"/g)].map((m) => m[1]);

test("never calls the healer: /api/heartbeat dispatches a scan", () => {
  // heartbeat.js returns 200 "dispatched" when the book is overdue and spends
  // one of its 24/day heal budget doing it. A lamp that polled it on every
  // page load would fire workflows off page views.
  assert.ok(FETCHED.length > 0, "no fetch call sites found — did the extractor break?");
  assert.ok(!FETCHED.some((u) => u.includes("/api/heartbeat")), "status.js requests the healer");
});

test("never calls the watcher, the scan dispatcher or the close path", () => {
  ["/api/tick", "/api/scan", "/api/close"].forEach((u) => {
    assert.ok(!FETCHED.some((f) => f.includes(u)), `status.js requests ${u}`);
    assert.ok(!CODE.includes(u), `status.js mentions ${u} in code`);
  });
});

test("issues no non-GET request anywhere", () => {
  assert.ok(!/method\s*:/i.test(CODE), "a fetch init in status.js sets a method");
  assert.ok(!/\bXMLHttpRequest\b|\bnavigator\.sendBeacon\b/.test(CODE), "status.js uses a non-fetch transport");
});

test("writes no storage at all — not even a 'last opened' flag", () => {
  assert.ok(!/localStorage|sessionStorage|indexedDB|document\.cookie/.test(CODE),
    "status.js touches storage; the read-only promise has an exception");
});

test("the only /api/ endpoint it requests is health", () => {
  const apis = [...new Set(FETCHED.filter((u) => u.includes("/api/")))];
  assert.deepEqual(apis, ["/api/health"]);
});

// ── 2. the states matrix ─────────────────────────────────────────────────────
suite("states matrix — worst first, first match wins");

const sig = (over) => Object.assign({
  healthReachable: true, healthOk: true, bookAgeH: 0.5,
  bookReadable: true, breached: [], stalled: [],
}, over || {});

test("green when the pipeline is fresh and nothing is flagged", () => {
  assert.equal(overall(sig()).level, "green");
});

test("red when /api/health cannot be reached — unseen is not healthy", () => {
  assert.equal(overall(sig({ healthReachable: false })).level, "red");
});

test("red when health says not ok (the book is past the 4h alarm)", () => {
  const o = overall(sig({ healthOk: false, bookAgeH: 6.2 }));
  assert.equal(o.level, "red");
  assert.ok(o.why.includes(String(HEALTH_MAX_H)), "the red reason must cite the threshold it tripped");
});

test("red when the book carries no readable age — a missing number is not zero", () => {
  assert.equal(overall(sig({ bookAgeH: null })).level, "red");
  assert.equal(overall(sig({ bookAgeH: NaN })).level, "red");
});

test("a not-ok probe with NO age never invents one", () => {
  // A missing /api/health Function 404s and the body does not parse, so the
  // probe is "not ok" with nothing to report an age from. The old ordering
  // printed "no scan committed for 0.0h", which is a fabricated figure in the
  // one sentence a person would act on.
  const o = overall(sig({ healthOk: false, bookAgeH: null }));
  assert.equal(o.level, "red");
  assert.ok(!/0\.0h|NaN/.test(o.why), `the reason invented a number: "${o.why}"`);
  assert.ok(/no readable scan age/.test(o.why));
});

test("a not-ok probe WITH an age still reports the age it was given", () => {
  const o = overall(sig({ healthOk: false, bookAgeH: 6.2 }));
  assert.ok(o.why.includes("6.2"), `expected the real age in "${o.why}"`);
});

test("amber past the 90-minute overdue mark, still short of the alarm", () => {
  const o = overall(sig({ bookAgeH: 2 }));
  assert.equal(o.level, "amber");
  assert.ok(o.why.includes(String(HEAL_STALE_MIN)));
});

test("A LOSS GUARD BREACH IS AMBER, NOT RED — AND THAT IS THE POINT", () => {
  // The breach is the machine working: it has stopped taking new entries
  // exactly as designed. heartbeat.js paid for this lesson already ("an alarm
  // that fires on success is the fastest way to teach someone to ignore it").
  // Red is reserved for "the evidence you trade on is not arriving". Do not
  // 'fix' this to red without re-reading that argument.
  const o = overall(sig({ breached: [{ market: "asx", kind: "daily" }] }));
  assert.equal(o.level, "amber");
  assert.ok(/asx/.test(o.why));
});

test("stalled rows do NOT light the lamp — they are routine (REFINE200 #189)", () => {
  // 35 of 60 open rows carried stale_pinged, most waiting on the 28-day
  // time-stop the rules apply, and the lamp read CHECK on every page for days.
  // Same lesson as the breach: an alarm that fires on routine operation gets
  // muted. The sheet still lists them under Book.
  const o = overall(sig({ stalled: ["CAKE", "RHC"] }));
  assert.equal(o.level, "green");
  assert.ok(!/stall/.test(o.why), `the reason still talks about stalls: "${o.why}"`);
});

test("a fresh pipeline with an unreadable book is amber, not green", () => {
  assert.equal(overall(sig({ bookReadable: false })).level, "amber");
});

test("a book the page never tried to read is not 'unreadable' (the lamp reads health)", () => {
  assert.equal(overall(sig({ bookReadable: null })).level, "green");
});

test("staleness outranks a breach — the older fault is named first", () => {
  const o = overall(sig({ bookAgeH: 3, breached: [{ market: "asx", kind: "daily" }] }));
  assert.ok(o.why.includes(String(HEAL_STALE_MIN)), "the staler condition must be the one reported");
});

test("every level carries a plain-English reason", () => {
  [sig(), sig({ healthReachable: false }), sig({ bookAgeH: 3 }), sig({ stalled: ["X"] })]
    .forEach((s) => { const o = overall(s); assert.ok(o.why && o.why.length > 12, "empty reason"); });
});

// ── 3. uptime is measured, never asserted ────────────────────────────────────
suite("uptime — derived from the committed scan ledger");

const now = Date.parse("2026-08-18T20:00:00Z");
const every = (hours, count, endMs) =>
  Array.from({ length: count }, (_, i) => endMs - (count - 1 - i) * hours * H);

test("an unbroken hourly ledger reads 100%", () => {
  const u = uptime(every(1, 24 * 10, now), now, 7, HEALTH_MAX_H);
  assert.equal(Math.round(u.pct), 100);
  assert.equal(u.clamped, false);
});

test("a gap longer than the threshold is charged, the excess only", () => {
  // 10 days hourly, then one 10h hole ending at `now - 1h`.
  const base = every(1, 24 * 10, now - 11 * H);
  const stamps = base.concat([now - 1 * H, now]);
  const u = uptime(stamps, now, 7, HEALTH_MAX_H);
  // The hole is 10h; only the part beyond the 4h alive threshold counts.
  assert.ok(Math.abs(u.downH - 6) < 0.01, `expected 6h down, got ${u.downH}`);
});

test("THE CURRENT GAP COUNTS — a dead pipeline erodes the number live", () => {
  // Without closing the sequence at `now`, a pipeline that stopped a day ago
  // still reads 100% because nothing after the last scan is measured. That is
  // the failure this control exists to avoid.
  const stamps = every(1, 24 * 10, now - 24 * H);
  const u = uptime(stamps, now, 7, HEALTH_MAX_H);
  assert.ok(u.downH > 19, `the open gap must be charged, got ${u.downH}h`);
  assert.ok(u.pct < 89, `expected a visibly degraded figure, got ${u.pct}`);
});

test("the window is CLAMPED to the ledger's span and says so", () => {
  const stamps = every(1, 24 * 10, now);            // 240 hourly points = 239h of span
  const u = uptime(stamps, now, 30, HEALTH_MAX_H);
  assert.equal(u.clamped, true);
  assert.ok(Math.abs(u.windowDays - 239 / 24) < 0.01, `window should collapse to the span, got ${u.windowDays}`);
  assert.equal(u.askedDays, 30);
});

test("a 30d ask over 10d of history is NOT flattered by the dark before it", () => {
  // The trap: divide 10 days of perfect uptime by a 30-day window and the 20
  // unrecorded days count as healthy. Clamping is what stops that.
  const stamps = every(1, 24 * 10, now);
  const u = uptime(stamps, now, 30, HEALTH_MAX_H);
  assert.equal(Math.round(u.pct), 100);
  assert.ok(u.windowDays < 11, "the window must not exceed the evidence");
});

test("a gap straddling the window start is charged from the start, not from the pre-window scan", () => {
  // One scan 9 days ago, silence, then hourly for the last ~6 days. The hole
  // runs from day 9 to day 5.96, so ~25h of it lies inside a 7d window. The
  // outside part must NOT be charged (it is not in the window) and the inside
  // part MUST be (the pipeline really was down for it) — which together is
  // what stops the figure jumping as old rows age out of the window.
  const stamps = [now - 9 * D].concat(every(1, 24 * 6, now));
  const u = uptime(stamps, now, 7, HEALTH_MAX_H);
  const insideH = 7 * 24 - 143;      // window start -> first hourly stamp
  assert.ok(Math.abs(u.downH - insideH) < 0.05, `expected ~${insideH}h of in-window down, got ${u.downH}`);
  assert.ok(u.downH < 3 * 24, "the pre-window part of the hole must not be charged");
});

test("an empty or unusable ledger returns null, never a number", () => {
  assert.equal(uptime([], now, 7, 4), null);
  assert.equal(uptime(null, now, 7, 4), null);
  assert.equal(uptime([now + D], now, 7, 4), null);   // span <= 0
});

test("the threshold is a parameter, not a constant baked into the maths", () => {
  const stamps = every(6, 40, now);   // a scan every 6h
  assert.ok(uptime(stamps, now, 7, 4).downH > 0, "at a 4h threshold a 6h cadence has gaps");
  assert.ok(uptime(stamps, now, 7, 8).downH === 0, "at an 8h threshold the same cadence is continuous");
});

// ── 4. ledger readers ────────────────────────────────────────────────────────
suite("ledger — markets merged for uptime, split for ages");

const FUNNEL = {
  markets: {
    asx:    { t: ["2026-08-17T01:00:00Z", "2026-08-18T01:00:00Z"], scanned: [2100, 2113], published: [340, 335] },
    crypto: { t: ["2026-08-18T18:00:00Z", "2026-08-18T19:00:00Z"], scanned: [120, 120], published: [12, 14] },
  },
};

test("stamps from every market merge into one ascending series", () => {
  const s = mergeStamps(FUNNEL);
  assert.equal(s.length, 4);
  assert.deepEqual(s, s.slice().sort((a, b) => a - b));
});

test("unparseable stamps are dropped rather than becoming NaN in the series", () => {
  const s = mergeStamps({ markets: { asx: { t: ["not a date", "2026-08-18T01:00:00Z"] } } });
  assert.equal(s.length, 1);
});

test("a missing or malformed ledger yields an empty series, never a throw", () => {
  assert.deepEqual(mergeStamps(null), []);
  assert.deepEqual(mergeStamps({}), []);
  assert.deepEqual(mergeStamps({ markets: { asx: { t: "nope" } } }), []);
});

test("per-market age reads the LAST publish and the counts it carried", () => {
  const ages = marketAges(FUNNEL, Date.parse("2026-08-18T20:00:00Z"));
  const asx = ages.find((a) => a.market === "asx");
  assert.equal(asx.published, 335);
  assert.equal(asx.scanned, 2113);
  assert.equal(asx.runs, 2);
  assert.ok(Math.abs(asx.ageMs - 19 * H) < 1000);
});

test("age ladder: minutes, then hours, then days", () => {
  assert.equal(agoText(12 * 6e4), "12m ago");
  assert.equal(agoText(3 * H), "3h ago");
  assert.equal(agoText(4 * D), "4d ago");
  assert.equal(agoText(NaN), "—");
  assert.equal(agoText(-5), "—");
});

// ── 5. the book ──────────────────────────────────────────────────────────────
suite("book — slots, stalls and guards straight off the published file");

const BOOK = {
  updated_at: "2026-08-18T19:44:48+00:00",
  open: [
    { symbol: "CAKE", stale_pinged: "2026-08-14", cycle: "w3-1" },
    { symbol: "RHC", cycle: "w3-1" },
    { symbol: "OLD" },
  ],
  closed: [
    { symbol: "SGP", cycle: "w3-1", exit_reason: "manual", realized_r: -0.077 },
    { symbol: "AIA", cycle: "w3-1", exit_reason: "", realized_r: -0.049 },
    { symbol: "XYZ", cycle: "w3-1", exit_reason: "stop", realized_r: -1 },
    { symbol: "PRE", exit_reason: "target", realized_r: 2 },
  ],
  guard: { asx: { breached: false }, nasdaq: { breached: true, breach_kind: "weekly" } },
};

test("free slots come from the published cap, not a number typed here", () => {
  assert.equal(bookState(BOOK, 30).free, 27);
  assert.equal(bookState(BOOK, 5).free, 2);
});

test("an unreadable cap falls back rather than reporting infinite room", () => {
  assert.equal(bookState(BOOK, NaN).cap, FALLBACK_CAP);
  assert.equal(bookState(BOOK, 0).cap, FALLBACK_CAP);
});

test("free never goes negative when the book is over its cap", () => {
  assert.equal(bookState(BOOK, 1).free, 0);
});

test("the stalled cohort is the engine's stamp, listed by symbol", () => {
  assert.deepEqual(bookState(BOOK, 30).stalled, ["CAKE"]);
});

test("a breached guard is reported with its market and kind", () => {
  assert.deepEqual(bookState(BOOK, 30).breached, [{ market: "nasdaq", kind: "weekly" }]);
});

test("a missing book yields zeros and no throw", () => {
  const s = bookState(null, 30);
  assert.equal(s.open, 0); assert.deepEqual(s.breached, []); assert.deepEqual(s.stalled, []);
});

// ── 6. the w3-1 cohort ───────────────────────────────────────────────────────
suite("w3-1 — the audit tag is the whole definition");

test("rows written before the gate carry no cycle key and are excluded", () => {
  const c = cohort(BOOK, "w3-1");
  assert.equal(c.open, 2);
  assert.equal(c.closed, 3, "the pre-gate close must not be counted into the cohort");
});

test("the decider split follows journal.js: absent exit_reason is a human act", () => {
  const c = cohort(BOOK, "w3-1");
  assert.equal(c.byRules, 1);
  assert.equal(c.byOwner, 2, "an empty exit_reason was not closed by a mechanism");
});

test("R is summed per side so the two cohorts can be read apart", () => {
  const c = cohort(BOOK, "w3-1");
  assert.ok(Math.abs(c.ownerR - -0.126) < 1e-9);
  assert.equal(c.rulesR, -1);
});

test("MECHANICAL_EXITS agrees with journal.js — the mirror is gated, not trusted", () => {
  const jr = fs.readFileSync(path.resolve(__dirname, "../public/js/journal.js"), "utf8");
  const m = /const\s+MECHANICAL_EXITS\s*=\s*(\[[^\]]*\])/.exec(jr);
  assert.ok(m, "journal.js no longer declares MECHANICAL_EXITS");
  assert.deepEqual(MECHANICAL_EXITS, JSON.parse(m[1].replace(/'/g, '"')),
    "status.js and journal.js disagree about which exits are mechanical");
});

test("an unknown tag matches nothing rather than everything", () => {
  const c = cohort(BOOK, "w9-9");
  assert.equal(c.open, 0); assert.equal(c.closed, 0);
});

// ── 7. escaping ──────────────────────────────────────────────────────────────
suite("escaping — book fields reach innerHTML");

test("esc neutralises the five HTML-significant characters", () => {
  assert.equal(esc(`<img src=x onerror="y">&'`), "&lt;img src=x onerror=&quot;y&quot;&gt;&amp;&#39;");
  assert.equal(esc(null), "");
  assert.equal(esc(undefined), "");
});

test("symbols and guard kinds are escaped before they are interpolated", () => {
  // Both come from a committed JSON file, which is trusted-ish — but the
  // pattern is what stops the next field from being the exception.
  assert.ok(/esc\(b\.market\)/.test(CODE) || /esc\(/.test(CODE), "no escaping in the render path");
});

// ── 8. the thresholds are the system's, cited ────────────────────────────────
suite("thresholds — borrowed, never invented");

test("4h matches functions/api/health.js's max_h default", () => {
  const health = fs.readFileSync(path.resolve(__dirname, "../functions/api/health.js"), "utf8");
  const m = /maxH\s*<\s*1\s*\|\|\s*maxH\s*>\s*48\)\s*maxH\s*=\s*(\d+)/.exec(health);
  assert.ok(m, "health.js no longer sets a max_h default the way this pin reads it");
  assert.equal(HEALTH_MAX_H, Number(m[1]));
});

test("the 90m mark is labelled the WHOLE-PIPELINE line, approximate for one market", () => {
  // heartbeat floors each market's stale_min (asx 15 / nasdaq 15 / crypto 45),
  // so a single market heals well before 90m; the sheet must not present the
  // combined line as any market's heal trigger, nor cite a 24/day budget.
  assert.ok(/whole pipeline's \$\{HEAL_STALE_MIN\}m overdue mark/.test(CODE), "the amber reason lost its scope");
  assert.ok(/each market's own heal ping uses a shorter line/.test(CODE), "the sheet no longer says 90m is approximate");
  assert.ok(!/24\/day/.test(SRC), "the retired 24/day heal budget is cited again (it is 30 per market)");
});

test("90m matches functions/api/heartbeat.js's DEFAULT_STALE_MIN", () => {
  const hb = fs.readFileSync(path.resolve(__dirname, "../functions/api/heartbeat.js"), "utf8");
  const m = /const\s+DEFAULT_STALE_MIN\s*=\s*(\d+)/.exec(hb);
  assert.ok(m, "heartbeat.js no longer declares DEFAULT_STALE_MIN");
  assert.equal(HEAL_STALE_MIN, Number(m[1]));
});

test("the position cap is read from bot_rules.json, not typed into the render", () => {
  assert.ok(/max_open_total/.test(CODE), "status.js does not read the published cap");
});

// ── 9. the asset is actually shipped ─────────────────────────────────────────
suite("wiring — a control nobody loads is not a control");

test("every page carrying the shared nav also loads status.js and status.css", () => {
  const dir = path.resolve(__dirname, "../public");
  const pages = fs.readdirSync(dir).filter((f) => f.endsWith(".html"));
  const missing = [];
  pages.forEach((f) => {
    const s = fs.readFileSync(path.join(dir, f), "utf8");
    if (!/js\/nav\.js\?v=\d+/.test(s)) return;         // not a nav page
    if (!/js\/status\.js\?v=\d+/.test(s)) missing.push(f + " (js)");
    if (!/css\/status\.css\?v=\d+/.test(s)) missing.push(f + " (css)");
  });
  assert.deepEqual(missing, []);
});

test("the lamp is not mounted inside .nav-pills — that strip is hidden on phones", () => {
  assert.ok(/deck-top-right/.test(CODE), "status.js no longer prefers the breakpoint-surviving host");
  assert.ok(!/appendChild\(btn\)[\s\S]{0,40}site-nav/.test(CODE));
});


// ── trigger mix (batch-100 WS-J) ────────────────────────────────────────────
suite("trigger mix — what started the scans, from the funnel ledger");

const tmFunnel = (blocks) => ({ markets: blocks });
const NOW_TM = Date.parse("2026-08-20T00:00:00Z");
const dAgo = (d) => new Date(NOW_TM - d * 864e5).toISOString();

test("no market carries the trigger column yet -> null, not an invented all-cron", () => {
  const f = tmFunnel({ asx: { t: [dAgo(1), dAgo(0.5)] } });
  assert.equal(triggerMix(f, NOW_TM, 7), null);
});

test("counts the window only, by category, '' as unstamped", () => {
  const f = tmFunnel({
    crypto: { t: [dAgo(9), dAgo(3), dAgo(2), dAgo(1)],
              trigger: ["cron", "cron", "heartbeat", ""] },
  });
  const m = triggerMix(f, NOW_TM, 7);
  assert.deepEqual(m, { cron: 1, manual: 0, heartbeat: 1, unknown: 1, total: 3 },
    "the 9-day-old row is outside the 7d window");
});

test("a pre-migration market is silent, not a pile of unknowns", () => {
  const f = tmFunnel({
    asx: { t: [dAgo(1)] },                                   // no trigger column
    crypto: { t: [dAgo(1)], trigger: ["cron"] },
  });
  const m = triggerMix(f, NOW_TM, 7);
  assert.equal(m.total, 1, "only the stamped market counts");
  assert.equal(m.unknown, 0);
});

test("mismatched lengths align from the END, where the fresh stamps are", () => {
  // Three timestamps, two trigger entries, and the OLDEST timestamp is
  // outside the window — chosen so front-alignment and end-alignment give
  // DIFFERENT counts (a symmetric fixture let a front-aligned mutant pass).
  // End-aligned: dAgo(2)->manual, dAgo(1)->heartbeat. Front-aligned would
  // read dAgo(2)->heartbeat, dAgo(1)->unstamped.
  const f = tmFunnel({
    crypto: { t: [dAgo(9), dAgo(2), dAgo(1)], trigger: ["manual", "heartbeat"] },
  });
  const m = triggerMix(f, NOW_TM, 7);
  assert.deepEqual(m, { cron: 0, manual: 1, heartbeat: 1, unknown: 0, total: 2 });
});

test("an all-outside-window ledger reads null — a mix of nothing is not a mix", () => {
  const f = tmFunnel({ crypto: { t: [dAgo(30)], trigger: ["cron"] } });
  assert.equal(triggerMix(f, NOW_TM, 7), null);
});

test("the sheet does not describe the stop watcher (removed 2026-09-21)", () => {
  // stop_watcher.yml and /api/tick went with the manual journal. A "not visible
  // from here" note describing it as running every 5 min told the owner a
  // component existed that does not.
  assert.ok(!/<b>Stop watcher<\/b>/i.test(CODE) && !/runs every 5 min/i.test(CODE),
    "the status sheet describes the removed stop watcher again");
  assert.ok(/<b>Scheduler<\/b>/.test(CODE), "the 'not visible from here' block moved -- pin would be vacuous");
});

test("heartbeat-dispatched scans read as the primary clock, never as a missed cron (REFINE200 #189)", () => {
  // Since 2026-10-06 cron-job.org pings /api/heartbeat as THE scheduler; 86%
  // of a week's scans were heartbeat-dispatched and the sheet called every one
  // of them "self-heal = the cron missed", in amber.
  assert.ok(!/self-heal = the cron missed/.test(CODE), "the old 'cron missed' gloss is back");
  assert.ok(!/sys-amber">\$\{tm\.heartbeat\}/.test(CODE), "the heartbeat count is amber again");
  assert.ok(/cron-job\.org = the primary clock/.test(CODE), "the count must still carry its meaning");
  assert.ok(/GitHub cron/.test(CODE), "GitHub's crons must be named as the backup");
});

// ── cycle tag (REFINE200 #125) ──────────────────────────────────────────────
suite("cycle tag — read from bot_rules.json, the literal is only the fallback");

test("the published cycle_tag wins", () => {
  assert.equal(cycleTagOf({ cycle_tag: "hc5-1" }), "hc5-1");
});

test("no rules, or a rules file without the key, falls back to the config literal", () => {
  assert.equal(cycleTagOf(null), CYCLE_TAG);
  assert.equal(cycleTagOf({}), CYCLE_TAG);
  assert.equal(cycleTagOf({ cycle_tag: "  " }), CYCLE_TAG, "a blank tag is not a tag");
  assert.equal(cycleTagOf({ cycle_tag: 7 }), CYCLE_TAG);
});

test("the sheet counts and titles the cohort with the PUBLISHED tag", () => {
  assert.ok(/const tag = cycleTagOf\(STATE\.rules\)/.test(CODE), "the sheet no longer reads the published tag");
  assert.ok(/cohort\(STATE\.book, tag\)/.test(CODE));
  assert.ok(!/cohort\(STATE\.book, CYCLE_TAG\)/.test(CODE), "the cohort is counted off the literal again");
});

// ── integrity + the unloaded book (REFINE200 #188) ─────────────────────────
suite("an unloaded book is unknown, never an all-clear");

const NOW_I = Date.parse("2026-10-14T08:00:00Z");

test("integrity passes only for a loaded book inside the 4h alarm", () => {
  assert.equal(integrity({ updated_at: "2026-10-14T07:00:00Z" }, NOW_I).passed, true);
  const old = integrity({ updated_at: "2026-10-14T02:00:00Z" }, NOW_I);
  assert.equal(old.passed, false, "a 6h-old book cannot vouch for the last verify");
  assert.ok(/past the 4h alarm/.test(old.why), old.why);
  assert.equal(integrity(null, NOW_I).passed, false);
  assert.equal(integrity({ updated_at: "garbage" }, NOW_I).passed, false);
});

// The real sheet, sliced with everything it reads, rendered against a page
// whose book failed to load while /api/health is fresh and clean.
const SHEET_NAMES = ["CYCLE_TARGET", "REPO", "pct1", "WORD"];
const sheetBody = NAMES.map(sliceConst).join("\n") + "\n" + SHEET_NAMES.map(sliceConst).join("\n") + "\n" +
  "let STATE = null;\n" + sliceFn("row") + "\n" + sliceFn("sheetHTML") + "\n" +
  "return (st) => { STATE = st; return sheetHTML(); };";
const renderSheet = new Function(sheetBody)();

const sheetFor = (book, hj) => renderSheet({
  sig: { healthReachable: true, healthOk: true, bookAgeH: 0.3, bookReadable: book ? true : false,
         breached: [], stalled: [] },
  book, rules: { max_open_total: 60, cycle_tag: "hc4-1" },
  health: { ok: true, status: 200, json: hj }, funnel: null,
  book_state: book ? bookState(book, 60) : null,
});

test("a failed book read prints UNKNOWN, not '0 / 60 · 60 slots free' and 'passed'", () => {
  const h = sheetFor(null, { ok: true, age_h: 0.3, breached: [] });
  assert.ok(!/<b>0<\/b> \/ 60/.test(h), "the sheet invented an empty book");
  assert.ok(!/60 slots free/.test(h), "the sheet invented 60 free slots");
  assert.ok(!/<b>passed<\/b>/.test(h), "Integrity 'passed' over a book that never loaded");
  assert.ok(!/Gated open<\/span><span class="sys-v"><b>0<\/b>/.test(h), "the cycle invented zero opens");
  assert.ok((h.match(/<b>unknown<\/b>/g) || []).length >= 3, "open / integrity / cycle must read unknown");
  assert.ok(/<b>clear<\/b>/.test(h), "health read the book server-side, so its clean guards still count");
});

test("with no health breaches either, the guards are unknown too", () => {
  const h = sheetFor(null, { ok: true, age_h: 0.3 });
  assert.ok(!/<b>clear<\/b>/.test(h), "'clear' printed with no source for it");
});

test("a loaded, fresh book still reads the real figures and 'passed'", () => {
  const book = { updated_at: new Date(Date.now() - 10 * 6e4).toISOString(),
    open: [{ symbol: "CAKE", stale_pinged: "2026-10-01", cycle: "hc4-1" }], closed: [] };
  const h = sheetFor(book, { ok: true, age_h: 0.2, breached: [] });
  assert.ok(/<b>1<\/b> \/ 60/.test(h), h);
  assert.ok(/<b>passed<\/b>/.test(h));
  assert.ok(/hc4-1 cycle/.test(h));
  assert.ok(/CAKE/.test(h) && !/sys-amber">1</.test(h), "stalled is listed as information, not amber");
});

// ── the lamp's reads (REFINE200 #68) ────────────────────────────────────────
suite("one book read per page — the lamp reads health, the sheet reads the book");

function lampHarness(healthJson) {
  const calls = [];
  const VB = {
    get: (o) => { calls.push(["book", !!(o && o.fresh)]); return Promise.resolve({ updated_at: "x", open: [], closed: [] }); },
    rules: (o) => { calls.push(["rules", !!(o && o.fresh)]); return Promise.resolve({ max_open_total: 60 }); },
  };
  const bodyL = ["HEALTH_MAX_H", "HEAL_STALE_MIN", "FALLBACK_CAP", "bookState", "healthBreaches"].map(sliceConst).join("\n") +
    "\nconst window = { VivekBook: VB };\n" +
    "const getJSON = (u) => { calls.push([u]); return Promise.resolve({ ok: true, status: 200, json: HJ }); };\n" +
    sliceConst("STATE") + "\n" + sliceConst("shared") + "\n" + sliceFn("loadLight") + "\n" +
    "return { loadLight, STATE };";
  const h = new Function("VB", "calls", "HJ", bodyL)(VB, calls, healthJson);
  return { calls, ...h };
}

test("the lamp does NOT download the book when health reports the guards", async () => {
  const { calls, loadLight, STATE } = lampHarness({ ok: true, age_h: 0.2,
    breached: [{ market: "nasdaq", kind: "weekly" }] });
  await loadLight();
  assert.ok(!calls.some((c) => c[0] === "book"), "the lamp fetched the book: " + JSON.stringify(calls));
  assert.ok(!calls.some((c) => /vivek_bot_book/.test(c[0])), "the lamp fetched the book directly");
  assert.deepEqual(STATE.sig.breached, [{ market: "nasdaq", kind: "weekly" }]);
  assert.equal(STATE.sig.bookReadable, null, "a book never asked for is not 'unreadable'");
});

test("an older health answer without `breached` falls back to the shared book read", async () => {
  const { calls, loadLight } = lampHarness({ ok: true, age_h: 0.2 });
  await loadLight();
  assert.deepEqual(calls.filter((c) => c[0] === "book"), [["book", false]]);
});

test("opening the sheet re-reads the book and the rules FRESH, through the shared loader", async () => {
  const { calls, loadLight, STATE } = lampHarness({ ok: true, age_h: 0.2, breached: [] });
  await loadLight(true);
  assert.deepEqual(calls.filter((c) => c[0] === "book"), [["book", true]]);
  assert.deepEqual(calls.filter((c) => c[0] === "rules"), [["rules", true]]);
  assert.equal(STATE.sig.bookReadable, true);
});

test("the sheet open path asks for the book; the mount path does not", () => {
  assert.ok(/loadLight\(true\)\.then\(paintLamp\)/.test(CODE), "openSheet no longer reads the book fresh");
  assert.ok(/\n    loadLight\(\)\.then\(paintLamp\)/.test(CODE), "mount no longer lights the lamp off health alone");
});

(async () => {
  for (const t of PENDING) await t();
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
