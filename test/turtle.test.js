#!/usr/bin/env node
/* TURTLE lens front end (public/js/turtle.js), added 2026-08-21.
 *
 * Runs the REAL shipped file — the whole IIFE, executed against stub globals,
 * so the exported helpers are the ones the page actually uses rather than a
 * re-typed copy that would drift in step with any bug.
 *
 * `new Function`, not `vm.runInContext`: a vm context is a separate realm with
 * its own Array.prototype, and every cross-realm deepStrictEqual then fails
 * for reasons that have nothing to do with the code under test.
 *
 * The suite's most load-bearing test is the LAST section: turtle.js carries a
 * hand-typed mirror of config.py's constants as its offline fallback, and a
 * fallback is what the page shows exactly when the reader is least able to
 * check it. PUBLISHED_DEFAULTS in risk_manager.js drifted for months that way
 * (TOP100 #34) — so the mirror is parsed out of the real config.py here.
 */
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.resolve(__dirname, "../public/js/turtle.js"), "utf8");
const CONFIG = fs.readFileSync(path.resolve(__dirname, "../scanner/config.py"), "utf8");

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓  ${name}`); passed++; }
  catch (e) { console.error(`  ✗  ${name}\n     ${e.message}`); failed++; }
}
function suite(name) { console.log(`\n${name}`); }

// ── harness ─────────────────────────────────────────────────────────────────
// The page mounts on load, so the stubs have to be complete enough for mount()
// and render() to run to completion. getElementById returning null is the
// interesting case: every renderer must survive a missing host, which is also
// what happens on a page that ships only some of the sections.
function boot() {
  const win = {};
  const doc = {
    readyState: "complete",
    addEventListener() {},
    getElementById() { return null; },
    querySelectorAll() { return []; },
  };
  const fetchStub = () => Promise.resolve({ ok: false, json: () => Promise.resolve(null) });
  new Function("window", "document", "fetch", SRC)(win, doc, fetchStub);
  assert.ok(win.GBSTurtle, "turtle.js did not export GBSTurtle — was the IIFE renamed?");
  return win.GBSTurtle;
}

const T = boot();

// ── 1. escaping ─────────────────────────────────────────────────────────────
suite("esc — the page renders symbols and names it did not write");

test("escapes all five characters, every occurrence", () => {
  assert.equal(T.esc(`<a href="x">&'`), "&lt;a href=&quot;x&quot;&gt;&amp;&#39;");
  assert.equal(T.esc("<<>>"), "&lt;&lt;&gt;&gt;", "must be a global replace");
});

test("null-safe, and does not swallow a zero", () => {
  assert.equal(T.esc(null), "");
  assert.equal(T.esc(undefined), "");
  assert.equal(T.esc(0), "0");
});

// ── 2. sizing ───────────────────────────────────────────────────────────────
suite("sizing — one unit is 1% of the account per N");

test("unit = (risk% x equity) / N", () => {
  // $5,000 at N = 2.50 -> $50 of risk -> 20 units of stock
  assert.equal(T.unitShares(5000, 2.5), 20);
});

test("one unit moving one N is exactly one percent, at any scale", () => {
  [[5000, 0.37], [137500, 2], [1e6, 88.125]].forEach(([eq, n]) => {
    assert.ok(Math.abs(T.unitShares(eq, n) * n - 0.01 * eq) < 1e-6, `${eq} / ${n}`);
  });
});

test("an unpriceable N sizes to nothing rather than to infinity", () => {
  [0, -1, NaN, Infinity, null, undefined].forEach((bad) => {
    assert.equal(T.unitShares(5000, bad), 0, `N=${bad}`);
  });
});

test("the whipsaw risk override really overrides", () => {
  const std = T.unitShares(5000, 2);
  const whip = T.unitShares(5000, 2, T.FALLBACK.whipsaw_risk_pct);
  assert.equal(whip, std / 2, "half a percent is half of one percent");
});

// ── 3. the pyramid ──────────────────────────────────────────────────────────
suite("the pyramid — and the stop raise that halves its risk");

test("four units, spaced half an N, each issued its own 2N stop", () => {
  const lad = T.ladder(100, 2, "long");
  assert.equal(lad.length, 4);
  assert.deepEqual(lad.map((r) => r.price), [100, 101, 102, 103]);
  assert.deepEqual(lad.map((r) => r.ownStop), [96, 97, 98, 99]);
});

test("every unit ends on ONE shared stop, under the most recent fill", () => {
  const lad = T.ladder(100, 2, "long");
  assert.deepEqual(lad.map((r) => r.shared), [99, 99, 99, 99],
    "an add drags every earlier unit's stop up with it");
});

test("shorts mirror exactly", () => {
  const lad = T.ladder(100, 2, "short");
  assert.deepEqual(lad.map((r) => r.price), [100, 99, 98, 97]);
  assert.deepEqual(lad.map((r) => r.ownStop), [104, 103, 102, 101]);
  assert.deepEqual(lad.map((r) => r.shared), [101, 101, 101, 101]);
});

test("a full four-unit position risks 5% of the account, not 8%", () => {
  // The number the half-N stop raise exists to produce. 2% and 4% are both
  // plausible-looking wrong answers, which is why this is pinned in the JS as
  // well as in tests/test_turtle.py — the page PRINTS this figure.
  const equity = 100000, n = 2;
  const lad = T.ladder(100, n, "long");
  const u = T.unitShares(equity, n);
  const risked = lad.reduce((a, r) => a + u * (r.price - r.shared), 0);
  assert.ok(Math.abs(risked - 0.05 * equity) < 1e-6, `got ${risked}`);
  const unstepped = lad.reduce((a, r) => a + u * (r.price - r.ownStop), 0);
  assert.ok(Math.abs(unstepped - 0.08 * equity) < 1e-6, `got ${unstepped}`);
});

test("the page prints that 5% figure, so the two cannot disagree silently", () => {
  assert.ok(/0\.05 \* EQUITY/.test(SRC), "the rendered figure must be derived, not typed");
});

// ── 4. the drawdown rule ────────────────────────────────────────────────────
suite("the drawdown rule — it compounds");

test("two ten-percent steps is 0.8 x 0.8, not 1 - 0.4", () => {
  // A tolerance, not an equality: 0.8 * 0.8 * 100000 is 64000.000000000015 in
  // binary floating point. Rounding inside ddEquity to make the test pretty
  // would round a SIZING number for the sake of a test, so the test bends.
  assert.ok(Math.abs(T.ddEquity(100000, 20) - 64000) < 1e-6, T.ddEquity(100000, 20));
  assert.ok(Math.abs(T.ddEquity(100000, 20) - 60000) > 1, "additive would give 60,000");
});

test("a partial step does not round up, and the peak is a no-op", () => {
  assert.equal(T.ddEquity(100000, 0), 100000);
  assert.equal(T.ddEquity(100000, 9.9), 100000);
  assert.equal(T.ddEquity(100000, 10), 80000);
});

test("it never goes negative however deep the drawdown", () => {
  assert.ok(T.ddEquity(100000, 95) > 0);
});

// ── 5. the compounding arithmetic on the EVIDENCE view ──────────────────────
suite("years-to-target — the headline claim as arithmetic");

test("5k to 10M is a 2000x, and 2000x at 100% a year takes 11 years", () => {
  assert.ok(Math.abs(T.yearsTo(2000, 1.0) - 11.0) < 0.05);
});

test("at the Turtles' reported 80% it is ~12.9 years, at a good 30% ~29", () => {
  assert.ok(Math.abs(T.yearsTo(2000, 0.8) - 12.93) < 0.05);
  assert.ok(Math.abs(T.yearsTo(2000, 0.3) - 28.97) < 0.05);
});

test("a zero or negative rate never arrives", () => {
  assert.equal(T.yearsTo(2000, 0), Infinity);
  assert.equal(T.yearsTo(2000, -0.1), Infinity);
});

// ── 6. published params beat the mirror ─────────────────────────────────────
suite("the published params win over the built-in mirror");

test("setParams changes the arithmetic, so the payload really drives the page", () => {
  T.setParams({ max_units: 2, pyramid_step_n: 1.0, stop_n: 3.0 });
  const lad = T.ladder(100, 2, "long");
  assert.equal(lad.length, 2);
  assert.deepEqual(lad.map((r) => r.price), [100, 102]);
  assert.deepEqual(lad.map((r) => r.ownStop), [94, 96]);
  T.setParams(null);                       // back to the mirror
  assert.equal(T.ladder(100, 2, "long").length, 4);
});

test("a payload wins over the mirror in the loader, not the other way round", () => {
  assert.ok(/PARAMS_ARE_LIVE \? Object\.assign\(\{\}, FALLBACK, DATA\.params\)/.test(SRC),
    "published params must override the mirror, key by key");
});

// ── 7. THE MIRROR vs config.py ──────────────────────────────────────────────
suite("the offline mirror must equal scanner/config.py");

function pyConst(name) {
  const m = new RegExp("^" + name + "\\s*=\\s*([^#\\n]+)", "m").exec(CONFIG);
  assert.ok(m, `config.py has no ${name}`);
  const raw = m[1].trim().replace(/_/g, "");
  if (raw === "True") return true;
  if (raw === "False") return false;
  const v = Number(raw);
  assert.ok(!Number.isNaN(v), `${name} is not a scalar: ${m[1]}`);
  return v;
}

const MIRROR = [
  ["n_period", "TURTLE_N_PERIOD"],
  ["s1_entry", "TURTLE_S1_ENTRY"], ["s1_exit", "TURTLE_S1_EXIT"],
  ["s2_entry", "TURTLE_S2_ENTRY"], ["s2_exit", "TURTLE_S2_EXIT"],
  ["stop_n", "TURTLE_STOP_N"], ["pyramid_step_n", "TURTLE_PYRAMID_STEP_N"],
  ["max_units", "TURTLE_MAX_UNITS"], ["risk_pct", "TURTLE_RISK_PCT"],
  ["max_units_close_corr", "TURTLE_MAX_UNITS_CLOSE_CORR"],
  ["max_units_loose_corr", "TURTLE_MAX_UNITS_LOOSE_CORR"],
  ["max_units_direction", "TURTLE_MAX_UNITS_DIRECTION"],
  ["drawdown_step_pct", "TURTLE_DRAWDOWN_STEP_PCT"],
  ["drawdown_cut_pct", "TURTLE_DRAWDOWN_CUT_PCT"],
  ["whipsaw_risk_pct", "TURTLE_WHIPSAW_RISK_PCT"],
  ["whipsaw_stop_n", "TURTLE_WHIPSAW_STOP_N"],
  ["account_equity", "TURTLE_ACCOUNT_EQUITY"],
  ["allow_shorts", "TURTLE_ALLOW_SHORTS"],
  ["min_bars", "TURTLE_MIN_BARS"],
  ["approach_pct", "TURTLE_APPROACH_PCT"],
  ["min_coverage_pct", "TURTLE_MIN_COVERAGE_PCT"],
  ["small_universe_max", "TURTLE_SMALL_UNIVERSE_MAX"],
  ["small_universe_max_missing", "TURTLE_SMALL_UNIVERSE_MAX_MISSING"],
];

MIRROR.forEach(([jsKey, pyName]) => {
  test(`${jsKey} matches ${pyName}`, () => {
    assert.equal(T.FALLBACK[jsKey], pyConst(pyName));
  });
});

test("the mirror covers every key the renderers read", () => {
  // A key the page reads but the mirror lacks renders as `undefined` on the
  // offline path only -- the failure mode that hides until the fetch breaks.
  const read = new Set();
  const re = /\bP\.([a-z0-9_]+)/g;
  let m;
  while ((m = re.exec(SRC))) read.add(m[1]);
  const missing = [...read].filter((k) => !(k in T.FALLBACK));
  assert.deepEqual(missing, [], "keys read from P but absent from FALLBACK");
});

// ── 8. read-only ────────────────────────────────────────────────────────────
suite("the futures sleeve's honesty sentences are ON THE PAGE (2026-08-21)");

test("the coverage rule renders from live params, not from a docstring", () => {
  // The rule lives in turtle_run.py; a rule stated only in Python is
  // invisible to the person reading the sleeve. The EVIDENCE card must
  // carry it, and must build it from P.* so the sentence cannot drift from
  // the constants the way a hand-typed number would.
  assert.ok(/The publish gate on this sleeve is absolute, not a share/.test(SRC),
    "the small-universe floor sentence is missing from the page");
  assert.ok(/P\.small_universe_max_missing/.test(SRC),
    "the ceiling must be rendered from params, not hardcoded prose");
  assert.ok(/named in the payload/.test(SRC),
    "the page must say the missing contracts are NAMED, because they are");
});

test("the session sentence states which close 23:00 UTC actually is", () => {
  // One cron cannot be 'after the close' for seven contract groups: FX and
  // metals trade nearly 24h and CL settles 14:30 ET. The page says which
  // session the stamp means rather than implying all of them.
  assert.ok(/one session, not seven/.test(SRC));
  assert.ok(/23:00 UTC/.test(SRC), "the actual stamp must be stated");
  assert.ok(/14:30 ET/.test(SRC),
    "the CL counter-example is what makes the sentence honest");
});


suite("read-only — a rules page must not move anything");

const CODE = SRC.split("\n")
  .filter((l) => { const t = l.trim(); return t && !t.startsWith("//") && !t.startsWith("*") && !t.startsWith("/*"); })
  .join("\n");

test("fetches published data files and nothing else", () => {
  const urls = [...CODE.matchAll(/fetch\(\s*"([^"]+)"/g)].map((m) => m[1]);
  const built = [...CODE.matchAll(/fetch\(\s*"([^"]*)"\s*\+/g)].map((m) => m[1]);
  const all = urls.concat(built);
  assert.ok(all.length > 0, "no fetch call sites found — did the extractor break?");
  assert.ok(all.some((u) => u.indexOf("turtle_book") >= 0),
    "the forward book must be fetched -- it is the only honest number here");
  all.forEach((u) => {
    assert.ok(u.startsWith("data/"), `turtle.js fetches ${u}`);
    assert.ok(!u.includes("/api/"), `turtle.js reaches an endpoint: ${u}`);
  });
});

test("issues no non-GET request and uses no other transport", () => {
  assert.ok(!/method\s*:/i.test(CODE), "a fetch init sets a method");
  assert.ok(!/XMLHttpRequest|sendBeacon/.test(CODE));
});

test("writes no browser storage — the account size is not persisted", () => {
  assert.ok(!/localStorage|sessionStorage|indexedDB|document\.cookie/.test(CODE),
    "an account size stored here would outlive the tab that typed it");
  assert.ok(/stored\s+nowhere and sent nowhere/.test(SRC),
    "and the page must say so where the number is typed");
});

// ── 8b. keyboard + injection ────────────────────────────────────────────────
suite("rows are real controls, and hostile data cannot reach a selector");

test("rows carry tabindex, role and aria-expanded like the main deck's rows", () => {
  assert.ok(/tabindex="0" role="button"/.test(SRC));
  assert.ok(/aria-expanded="' \+ \(open \? "true" : "false"\)/.test(SRC),
    "aria-expanded must track the actual open state, not be hard-coded");
  assert.ok(/Enter for details/.test(SRC), "the row needs an announceable label");
});

test("Enter and Space toggle a focused row", () => {
  assert.ok(/e\.key !== "Enter" && e\.key !== " "/.test(CODE));
  assert.ok(/preventDefault/.test(CODE), "Space must not scroll the page instead");
});

test("focus is restored by COMPARING dataset, never by building a selector", () => {
  // dataset.sym is the DECODED symbol. Interpolating it into a selector makes
  // querySelector throw on any value carrying a quote or a bracket — found by
  // rendering a hostile fixture, and invisible to every test that uses real
  // tickers. The ban is on the construct, so it cannot come back.
  assert.ok(!/querySelector\([^)]*\+\s*row\.dataset/.test(CODE),
    "a selector is being built from row data");
  assert.ok(!/querySelector\([^)]*data-sym="' \+/.test(CODE),
    "a selector is being built from row data");
  assert.ok(/rows\[i\]\.dataset\.sym === row\.dataset\.sym/.test(CODE),
    "the replacement node must be found by comparison");
});

test("a click inside an expanded detail does not collapse the row", () => {
  assert.ok(/!e\.target\.closest\("\.tt-detail"\)/.test(CODE),
    "the detail is content, not a button — you must be able to select a number in it");
});

// ── 8c. every untrusted field is escaped where it is rendered ───────────────
suite("escaping is APPLIED, not merely available");

test("every payload string that reaches innerHTML goes through esc()", () => {
  // Found by mutation: the suite tested esc() in isolation and never asserted
  // it was CALLED, so deleting it from the row name left everything green --
  // while `name` comes from a third-party listings directory and is the one
  // field an attacker could influence.
  const UNTRUSTED = ["r.symbol", "r.name", "r.state", "p.entry_date", "P.period"];
  const bare = [];
  UNTRUSTED.forEach((field) => {
    const re = new RegExp(field.replace(".", "\\.") + "\\b", "g");
    let m;
    while ((m = re.exec(CODE))) {
      const before = CODE.slice(Math.max(0, m.index - 30), m.index);
      // esc(x), esc(x || ""), esc(String(x)...) all count; a bare reference does not
      if (!/esc\(\s*(String\(\s*)?$/.test(before) && !/esc\(\s*$/.test(before)) {
        // allow non-render uses: comparisons, assignments, dataset lookups
        const line = CODE.slice(CODE.lastIndexOf("\n", m.index) + 1,
                                CODE.indexOf("\n", m.index));
        if (/innerHTML|return '|\+ '|" \+|'<|<span|<b |<article/.test(line)) {
          bare.push(field + "  ->  " + line.trim().slice(0, 90));
        }
      }
    }
  });
  assert.deepEqual(bare, [], "unescaped untrusted field(s) reaching markup");
});

test("the row name specifically is escaped", () => {
  assert.ok(/tt-name">' \+ esc\(r\.name/.test(CODE),
    "r.name must be escaped at its render site");
});

// ── 9. the freeze fence ─────────────────────────────────────────────────────
suite("the fence — a fourth lens must not touch the other three");

test("never reads the paper book, the bot rules or any other lens's data", () => {
  ["vivek_bot_book", "bot_rules", "_vivek.json", "_spec.json", "phasemap",
   "alert_history", "journal"].forEach((f) => {
    assert.ok(!CODE.includes(f), `turtle.js reads ${f}`);
  });
});

test("the page ships the shared nav, status lamp and its own stylesheet", () => {
  const html = fs.readFileSync(path.resolve(__dirname, "../public/turtle.html"), "utf8");
  [/js\/nav\.js\?v=\d+/, /js\/status\.js\?v=\d+/, /css\/status\.css\?v=\d+/,
   /css\/styles\.css\?v=\d+/, /css\/turtle\.css\?v=\d+/, /js\/turtle\.js\?v=\d+/,
   /deck-top-right/, /id="site-nav"/].forEach((re) => {
    assert.ok(re.test(html), `turtle.html is missing ${re}`);
  });
});

test("the disclaimer says the lens feeds nothing else", () => {
  const html = fs.readFileSync(path.resolve(__dirname, "../public/turtle.html"), "utf8");
  assert.ok(/nothing on this page feeds the paper book/i.test(html));
});

test("nav.js lists it, so the tab is reachable", () => {
  const nav = fs.readFileSync(path.resolve(__dirname, "../public/js/nav.js"), "utf8");
  assert.ok(/href:\s*"turtle\.html"/.test(nav));
  assert.ok(/key:\s*"turtle"/.test(nav));
});

// ── the 5x sleeve, the gates, and the portfolio surface (2026-08-22) ───────
suite("5x / gates / portfolio surfaces");

test("the WHY map covers every skip reason the book can emit", () => {
  // Parity with the Python enum, parsed from the real source: a new skip
  // reason that renders as its raw slug is a refusal nobody can read.
  const tbSrc = fs.readFileSync(
    path.resolve(__dirname, "../scanner/turtle_book.py"), "utf8");
  const reasons = [...tbSrc.matchAll(/^SKIP_[A-Z_]+ = "([a-z_]+)"/gm)]
    .map((m) => m[1]);
  assert.ok(reasons.length >= 10, "enum extraction broke");
  const whyBlock = SRC.slice(SRC.indexOf("const WHY = {"),
                             SRC.indexOf("};", SRC.indexOf("const WHY = {")));
  for (const r of reasons) {
    assert.ok(whyBlock.includes(r + ":"),
      `the WHY map is missing "${r}" — it would render as a raw slug`);
  }
});

test("the 5x disclosure renders FROM params, with no hardcoded sleeve name", () => {
  assert.ok(/b\.params\s*&&\s*b\.params\.leverage\s*>\s*1/.test(SRC),
    "the by-market table must discover a levered sleeve from its params");
  assert.ok(/not<\/b>\s*Dennis's\s*futures\s*IM/.test(SRC),
    "the perp-analogue sentence must be on the page");
  assert.ok(/posted margin/.test(SRC));
  assert.ok(!/crypto5x/i.test(SRC),
    "turtle.js must not hardcode the sleeve name — params are the contract");
});

test("liquidation and the margin refusals reach the reader in words", () => {
  assert.ok(/liquidation/.test(SRC));
  assert.ok(/no free margin for the posted amount/.test(SRC));
  assert.ok(/no real margin data — futures opens are OFF/.test(SRC));
  assert.ok(/roll suspect sits in today's N window/.test(SRC));
});

test("the first-print rule and the face-value warning are on the BOOK view", () => {
  assert.ok(/A first print is a print, not evidence/.test(SRC));
  assert.ok(/30 closed trades AND 20 trading days/.test(SRC));
  assert.ok(/at face value/.test(SRC), "the A$+US$ mix must be admitted");
  assert.ok(/scan cadence, not a four-hour Donchian/.test(SRC),
    "the 4h cron vs daily bars distinction must be stated");
});

test("the portfolio card renders the payload's own caveat, lazily fetched", () => {
  assert.ok(/data\/turtle_portfolio\.json/.test(SRC),
    "the portfolio surface must be fetched from data/");
  assert.ok(/PORTFOLIO\.caveat/.test(SRC),
    "the caveat must come from the payload, not from page copy that can " +
    "drift from what the file itself claims");
  assert.ok(/PORTFOLIO\.ordering/.test(SRC),
    "the declared entry ordering must reach the reader");
});

test("S2-first when both channels break is stated in the rules copy", () => {
  assert.ok(/tagged System 2/.test(SRC));
  assert.ok(/failsafe is tested first/.test(SRC));
});

console.log(`\nturtle.test.js: ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
