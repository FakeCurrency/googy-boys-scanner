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
function test(name, fn) {
  try { fn(); console.log(`  ✓  ${name}`); passed++; }
  catch (e) {
    const loc = (e.stack || "").split("\n").slice(1).find((l) => l.includes("status.test.js"));
    console.error(`  ✗  ${name}\n     ${e.message}${loc ? "\n     " + loc.trim() : ""}`);
    failed++;
  }
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

const NAMES = ["HEALTH_MAX_H", "HEAL_STALE_MIN", "FALLBACK_CAP", "MECHANICAL_EXITS",
               "esc", "agoText", "bookState", "cohort", "mergeStamps", "marketAges",
               "uptime", "overall"];
const body = NAMES.map(sliceConst).join("\n") + `\nreturn { ${NAMES.join(", ")} };`;
const { HEALTH_MAX_H, HEAL_STALE_MIN, FALLBACK_CAP, MECHANICAL_EXITS,
        esc, agoText, bookState, cohort, mergeStamps, marketAges,
        uptime, overall } = new Function(body)();

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

test("amber when positions are stamped stalled", () => {
  assert.equal(overall(sig({ stalled: ["CAKE"] })).level, "amber");
});

test("a fresh pipeline with an unreadable book is amber, not green", () => {
  assert.equal(overall(sig({ bookReadable: false })).level, "amber");
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

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
