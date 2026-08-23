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
//
// Phase 3 adds history.pushState/replaceState/popstate, so the stub window
// now needs a working location.search, a history with a real length, and an
// addEventListener that actually stores the popstate listener turtle.js
// registers in mount() -- mount() calls all of these unconditionally and
// synchronously, so every boot(), including the module-level one below, goes
// through this path whether or not a given test cares about history.
//
// initialSearch seeds window.location.search before mount() runs, so a test
// can boot as if the page had been loaded from a particular URL. __goto
// simulates a browser Back/Forward: it sets location.search to the target
// entry and fires the popstate listener(s) turtle.js registered, exactly
// what a real back-navigation does from the app code's point of view (it is
// never told "this is a back" -- it just sees location change and popstate
// fire). fetchCalls records every URL fetched, in call order, so a test can
// assert a market change fetched exactly the right file without waiting on
// the stubbed promise to settle.
function boot(initialSearch) {
  const fetchCalls = [];
  const win = {
    location: { search: initialSearch || "" },
    history: {
      length: 1,
      pushState(state, title, url) {
        win.history.length++;
        if (typeof url === "string") win.location.search = url;
      },
      replaceState(state, title, url) {
        if (typeof url === "string") win.location.search = url;
      },
    },
    _popstateListeners: [],
    addEventListener(type, fn) {
      if (type === "popstate") win._popstateListeners.push(fn);
    },
    removeEventListener(type, fn) {
      if (type !== "popstate") return;
      const i = win._popstateListeners.indexOf(fn);
      if (i !== -1) win._popstateListeners.splice(i, 1);
    },
    __goto(search) {
      win.location.search = search;
      win._popstateListeners.forEach((fn) => fn({}));
    },
  };
  const doc = {
    readyState: "complete",
    addEventListener() {},
    getElementById() { return null; },
    querySelectorAll() { return []; },
  };
  const fetchStub = (url) => {
    fetchCalls.push(url);
    return Promise.resolve({ ok: false, json: () => Promise.resolve(null) });
  };
  new Function("window", "document", "fetch", SRC)(win, doc, fetchStub);
  assert.ok(win.GBSTurtle, "turtle.js did not export GBSTurtle — was the IIFE renamed?");
  return { T: win.GBSTurtle, win, fetchCalls };
}

const { T, win: BOOT_WIN } = boot();

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

test("never reaches the shared watchlist / MY NAMES store", () => {
  // Every other lens (mynames.js, phasemap.js, specs.js, recs.js) stars a
  // name through window.PM.watch, which writes localStorage's
  // gbs:manual_journal .watchlists under the hood. The test above bans the
  // storage primitive directly; it would NOT catch a future star button
  // wired to PM.watch instead, since that call never types the word
  // "localStorage" in this file at all. Ban the API and the key, not just
  // the primitive one happens to sit on -- this is the fence a "star this
  // into MY NAMES" regression would actually have to cross.
  assert.ok(!/PM\.watch|window\.PM\b/.test(CODE),
    "turtle.js must never call the shared watchlist API");
  assert.ok(!/mynames|watchlist|gbs:manual_journal/i.test(CODE),
    "turtle.js must never reference MY NAMES or its storage key");
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

test("a chart opened from Turtle says so on the way back (Phase B)", () => {
  // Regression for the residual Phase 10 found and deliberately left alone:
  // SRC_BACK had no turtle entry, so a Turtle-sourced chart silently showed
  // the generic dashboard back-link. Fixed in chart.js, pinned here.
  const chart = fs.readFileSync(path.resolve(__dirname, "../public/js/chart.js"), "utf8");
  assert.ok(/turtle:\s*\[/.test(chart),
    "chart.js's SRC_BACK is missing a turtle entry");
  assert.ok(/"turtle\.html\?m="\s*\+\s*encodeURIComponent\(market\)/.test(chart),
    "the turtle back-link must be built from the validated market, not a literal string");
  assert.ok(/\+\s*symbol\s*\)/.test(chart) || /symbol\s*\?/.test(chart),
    "the turtle back-link must carry the symbol through, not just the market");
  assert.ok(/"←\s*Turtle"/.test(chart), "the back-link label must say Turtle");
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

test("the combined book states its sleeve count, not one pooled account", () => {
  assert.ok(/\$\{mk\.length\}\s*separate sleeve/.test(SRC),
    "the count must be read live from by_market, not hardcoded");
  assert.ok(/not one account/.test(SRC),
    "four (or five, once crypto5x exists) $5k books must never read as one");
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

// ── 10. URL state (Phase 2) ─────────────────────────────────────────────────
suite("URL state — back/forward is a data contract, written before any click uses it");

const LEGAL_COMBOS = [
  { m: "asx", v: "signals", f: "fired", s: "", sort: "fired" },
  { m: "nasdaq", v: "book", f: "held", s: "AAPL", sort: "n" },
  { m: "crypto", v: "rules", f: "near", s: "DOGE", sort: "distance" },
  { m: "futures", v: "sizing", f: "blocked", s: "CL", sort: "symbol" },
  { m: "asx", v: "evidence", f: "all", s: "", sort: "fired" },
];

test("round-trips every legal combo, serialise then parse", () => {
  LEGAL_COMBOS.forEach((combo) => {
    const qs = T.serialiseTurtleURL(combo);
    const back = T.parseTurtleURL(qs);
    assert.deepEqual(back, combo,
      `combo ${JSON.stringify(combo)} -> ${qs} -> ${JSON.stringify(back)}`);
  });
});

test("a bare query string (no leading '?') parses identically to one with it", () => {
  const withQ = T.parseTurtleURL("?m=nasdaq&v=book&f=held&sort=n");
  const bare = T.parseTurtleURL("m=nasdaq&v=book&f=held&sort=n");
  assert.deepEqual(withQ, bare);
});

test("garbage m/v/f/sort fall back to their defaults, one field at a time", () => {
  const defaults = T.parseTurtleURL("");
  assert.deepEqual(T.parseTurtleURL("?m=bogus"), defaults);
  assert.deepEqual(T.parseTurtleURL("?v=xyz"), defaults);
  assert.deepEqual(T.parseTurtleURL("?f=whatever"), defaults);
  assert.deepEqual(T.parseTurtleURL("?sort=nope"), defaults);
  // all four wrong at once must not throw, and must still be all-defaults
  assert.deepEqual(T.parseTurtleURL("?m=x&v=y&f=z&sort=w"), defaults);
});

test("default f is fired, not all — SIGNALS/ALL is 400 names, not a filtered view", () => {
  assert.equal(T.parseTurtleURL("").f, "fired");
  assert.notEqual(T.parseTurtleURL("").f, "all");
});

test("empty, missing, and garbage-typed search all default cleanly, never throwing", () => {
  const defaults = { m: "asx", v: "signals", f: "fired", s: "", sort: "fired" };
  assert.deepEqual(T.parseTurtleURL(""), defaults);
  assert.deepEqual(T.parseTurtleURL(undefined), defaults);
  assert.deepEqual(T.parseTurtleURL(null), defaults);
  assert.deepEqual(T.parseTurtleURL(42), defaults, "a number must not throw");
  assert.deepEqual(T.parseTurtleURL(Symbol("x")), defaults, "a Symbol must not throw");
});

test("hostile s (quote, brackets) round-trips through encodeURIComponent", () => {
  const hostile = 'AAA"><';
  const qs = T.serialiseTurtleURL({ m: "asx", v: "signals", f: "fired", s: hostile, sort: "fired" });
  assert.ok(!qs.includes('"') && !qs.includes("<") && !qs.includes(">"),
    `raw hostile characters leaked into the query string: ${qs}`);
  assert.equal(T.parseTurtleURL(qs).s, hostile);
});

test("hostile s (ampersand, quote — the classic query-string breakers)", () => {
  const hostile = 'A&B"C';
  const qs = T.serialiseTurtleURL({ m: "asx", v: "signals", f: "fired", s: hostile, sort: "fired" });
  assert.equal(T.parseTurtleURL(qs).s, hostile);
});

test("serialise omits an empty s instead of writing a bare '&s='", () => {
  const qs = T.serialiseTurtleURL({ m: "asx", v: "signals", f: "fired", s: "", sort: "fired" });
  assert.ok(!qs.includes("s="), qs);
  const qsDefault = T.serialiseTurtleURL({});
  assert.ok(!qsDefault.includes("s="), qsDefault);
});

test("serialise never throws and defaults an invalid state object, field by field", () => {
  assert.doesNotThrow(() => T.serialiseTurtleURL(null));
  assert.doesNotThrow(() => T.serialiseTurtleURL(undefined));
  assert.doesNotThrow(() => T.serialiseTurtleURL({ m: "bogus", v: 123, f: [], sort: {} }));
  const qs = T.serialiseTurtleURL({ m: "bogus", v: 123, f: [], sort: {} });
  assert.deepEqual(T.parseTurtleURL(qs),
    { m: "asx", v: "signals", f: "fired", s: "", sort: "fired" },
    "every invalid field must fall back independently, not abort the whole call");
});

test("extra query keys are read from but never appear on the parsed result", () => {
  const out = T.parseTurtleURL("?m=nasdaq&debug=1&foo=bar&lite=true");
  assert.deepEqual(Object.keys(out).sort(), ["f", "m", "s", "sort", "v"]);
  assert.equal(out.m, "nasdaq");
  // the drop is consistent on the way back out too: re-serialising never
  // resurrects a key that was never part of the {m,v,f,s,sort} contract
  const qs = T.serialiseTurtleURL(out);
  assert.ok(!qs.includes("debug") && !qs.includes("foo") && !qs.includes("lite"), qs);
});

test("parseTurtleURL/serialiseTurtleURL touch no DOM, no history API, and no journal", () => {
  // A permanent invariant, not a Phase-2-only one: these two stay pure even
  // after Phase 3 adds real history wiring right below them. Scoped to just
  // these two functions (not the whole file up to mount()) precisely
  // because Phase 3's getTurtleState/applyState/pushURLState/onPopState
  // legitimately live in that later span and legitimately touch history.
  const fnBody = SRC.slice(SRC.indexOf("function parseTurtleURL"),
                            SRC.indexOf("function getTurtleState"));
  assert.ok(!/pushState|popstate|history\.(back|forward|go)/.test(fnBody),
    "parseTurtleURL/serialiseTurtleURL must never touch history");
  assert.ok(!/innerHTML|getElementById|querySelector/.test(fnBody),
    "parseTurtleURL/serialiseTurtleURL must not touch the DOM");
  assert.ok(!/journal\//.test(fnBody), "the URL helpers must not reference journal/");
});

test("both helpers are exported on window.GBSTurtle", () => {
  assert.equal(typeof T.parseTurtleURL, "function");
  assert.equal(typeof T.serialiseTurtleURL, "function");
});

// ── 11. history wiring (Phase 3) ────────────────────────────────────────────
suite("applyState — the URL becomes live app state");

test("applyState sets MARKET/VIEW/FILTER/OPEN/SORT from a parsed URL", () => {
  T.applyState({ m: "nasdaq", v: "book", f: "held", s: "AAPL", sort: "n" });
  assert.deepEqual(T.getTurtleState(),
    { m: "nasdaq", v: "book", f: "held", s: "AAPL", sort: "n", touched: true });
});

test("an all-default parsed URL leaves TOUCHED false, and f is fired not all", () => {
  T.applyState(T.parseTurtleURL(""));
  const st = T.getTurtleState();
  assert.equal(st.touched, false);
  assert.equal(st.f, "fired", "the URL contract's default replaces the old live FILTER=all");
});

test("any single non-default field marks TOUCHED true, not just v", () => {
  T.applyState({ m: "asx", v: "book", f: "fired", s: "", sort: "fired" });
  assert.equal(T.getTurtleState().touched, true, "v alone must touch");
  T.applyState({ m: "nasdaq", v: "signals", f: "fired", s: "", sort: "fired" });
  assert.equal(T.getTurtleState().touched, true, "m alone must touch");
  T.applyState({ m: "asx", v: "signals", f: "fired", s: "JBH", sort: "fired" });
  assert.equal(T.getTurtleState().touched, true, "s alone must touch");
});

test("an empty s applies to OPEN=null, and getTurtleState reports it back as ''", () => {
  T.applyState({ m: "asx", v: "signals", f: "fired", s: "", sort: "fired" });
  assert.equal(T.getTurtleState().s, "");
});

test("a garbage m applies to asx without throwing (applyState trusts parseTurtleURL's output)", () => {
  assert.doesNotThrow(() => T.applyState(T.parseTurtleURL("?m=foo")));
  assert.equal(T.getTurtleState().m, "asx");
});

test("a futures+rules deep link is TOUCHED, so load()'s no-data fallback cannot override it", () => {
  T.applyState(T.parseTurtleURL("?m=futures&v=rules"));
  const st = T.getTurtleState();
  assert.equal(st.m, "futures");
  assert.equal(st.v, "rules");
  assert.equal(st.touched, true);
});

test("load()'s no-data fallback is still gated on TOUCHED, unmodified by Phase 3", () => {
  assert.ok(/if \(!TOUCHED\) VIEW = DATA \? "signals" : "rules";/.test(SRC),
    "the pre-existing no-scan-yet fallback must still exist and still be TOUCHED-gated " +
    "-- that gate, not new logic in load(), is what keeps a deep-linked VIEW from being stomped");
});

suite("popstate — Back/Forward replay the URL, and only the URL");

test("first paint applies location.search before the first fetch, and replaceState's, not pushState's", () => {
  const { T: T2, win } = boot("");
  assert.deepEqual(T2.getTurtleState(),
    { m: "asx", v: "signals", f: "fired", s: "", sort: "fired", touched: false });
  assert.equal(win.history.length, 1, "first paint must replaceState, not pushState");
  assert.equal(win.location.search, "?m=asx&v=signals&f=fired&sort=fired",
    "first paint must normalise the address bar to the resolved defaults");
});

test("popstate to a different market re-applies state and fetches that market once, without pushing", () => {
  const { win, fetchCalls } = boot("?m=asx&v=signals&f=fired&sort=fired");
  const lenAfterBoot = win.history.length;
  const callsBefore = fetchCalls.length;
  win.__goto("?m=nasdaq&v=signals&f=fired&sort=fired");
  const newCalls = fetchCalls.slice(callsBefore);
  assert.equal(newCalls.filter((u) => u === "data/nasdaq_turtle.json").length, 1,
    "a market-changing popstate must fetch the new market exactly once");
  assert.equal(win.history.length, lenAfterBoot, "popstate must not grow history.length");
});

test("popstate to the same market with a different view does not touch the network", () => {
  const { win, fetchCalls } = boot("?m=asx&v=signals&f=fired&sort=fired");
  const callsBefore = fetchCalls.length;
  win.__goto("?m=asx&v=book&f=fired&sort=fired");
  assert.equal(fetchCalls.length, callsBefore, "view-only popstate must not re-fetch");
  assert.equal(win.history.length, 1, "popstate must not grow history.length");
});

test("popstate restores market, view, filter and row together (a simulated Back to baseline)", () => {
  const { T: T2, win } = boot("?m=nasdaq&v=book&f=held&s=AAPL&sort=n");
  assert.equal(T2.getTurtleState().m, "nasdaq");
  win.__goto("?m=asx&v=signals&f=fired&sort=fired");
  assert.deepEqual(T2.getTurtleState(),
    { m: "asx", v: "signals", f: "fired", s: "", sort: "fired", touched: false });
});

test("popstate on a hostile s does not throw and restores it exactly", () => {
  const { T: T2, win } = boot("");
  const hostile = 'AAA"><';
  assert.doesNotThrow(() => win.__goto("?m=asx&v=signals&f=fired&s=" +
    encodeURIComponent(hostile) + "&sort=fired"));
  assert.equal(T2.getTurtleState().s, hostile);
});

test("popstate never calls pushState or replaceState itself", () => {
  const body = SRC.slice(SRC.indexOf("function onPopState"), SRC.indexOf("function syncMarketButtons"));
  assert.ok(!/pushState|replaceState/.test(body),
    "the popstate handler must only applyState/load/render — writing history from inside " +
    "a popstate handler is how Back and Forward stop working");
});

suite("the click handlers push exactly one history entry each, in state -> push -> render order");

test("the view-tab delegate is scoped to #tt-views, not document-wide", () => {
  // mount() is the last function before the window.GBSTurtle export, so
  // slicing to that export is the whole function body -- robust to mount()
  // growing in later phases, unlike a fixed character count that a later
  // phase's own new click branch can silently push past (Phase 6 did,
  // fixing what used to be a hardcoded +3500 here).
  const mountBody = SRC.slice(SRC.indexOf("function mount("), SRC.indexOf("window.GBSTurtle = {"));
  assert.ok(!/closest\("\[data-view\]"\)/.test(mountBody),
    "a document-wide [data-view] delegate would let a future deck pill steal the view-tab handler");
  assert.ok(/closest\("#tt-views \[data-view\]"\)/.test(mountBody),
    "the view-tab delegate must be scoped under #tt-views");
});

test("market, view, filter, goto and row handlers each call pushURLState", () => {
  // mount() is the last function before the window.GBSTurtle export, so
  // slicing to that export is the whole function body -- robust to mount()
  // growing in later phases, unlike a fixed character count that a later
  // phase's own new click branch can silently push past (Phase 6 did,
  // fixing what used to be a hardcoded +3500 here).
  const mountBody = SRC.slice(SRC.indexOf("function mount("), SRC.indexOf("window.GBSTurtle = {"));
  assert.ok(/VIEW = v\.dataset\.view;[\s\S]{0,80}pushURLState\(\)/.test(mountBody),
    "the view-tab handler must push before it renders");
  assert.ok(/VIEW = g\.dataset\.goto;[\s\S]{0,80}pushURLState\(\)/.test(mountBody),
    "the data-goto handler must push before it renders");
  assert.ok(/FILTER = f\.dataset\.filter;[\s\S]{0,60}pushURLState\(\)/.test(mountBody),
    "the filter-seg handler must push before it renders");
  assert.ok(/MARKET = m\.dataset\.market;[\s\S]{0,300}pushURLState\(\)/.test(mountBody),
    "the market handler must push before it fetches");
  assert.ok(/OPEN = OPEN === row\.dataset\.sym[\s\S]{0,60}pushURLState\(\)/.test(mountBody),
    "the row-head click handler must push before it renders");
});

test("Enter/Space on a row head pushes too, the same as a click on it", () => {
  const keydownBody = SRC.slice(SRC.indexOf('addEventListener("keydown"'), SRC.indexOf("window.GBSTurtle = {"));
  assert.ok(/OPEN = OPEN === row\.dataset\.sym[\s\S]{0,60}pushURLState\(\)/.test(keydownBody),
    "keyboard row-toggle must push history exactly like the click handler does");
});

test("hostile row symbols still cannot break the keyboard focus-restore selector", () => {
  // Unchanged since Phase 0 -- re-asserted here because Phase 3 is the first
  // phase where OPEN can arrive already set (from a URL) before any keydown
  // fires, so this guarantee now matters on more paths than it used to.
  assert.ok(!/querySelector\([^)]*\+\s*row\.dataset/.test(CODE));
  assert.ok(/rows\[i\]\.dataset\.sym === row\.dataset\.sym/.test(CODE));
});

test("the Phase 3 code stays out of the shared site nav entirely", () => {
  const phase3 = SRC.slice(SRC.indexOf("function getTurtleState"), SRC.length);
  assert.ok(!/nav\.js/.test(phase3), "history wiring is scoped to turtle.js and its own test file");
});

// ── 12. deck pills + default FIRED (Phase 5) ────────────────────────────────
// The click-handler suite above already proved every state -> push -> render
// wire is in the right order; this suite is about the two NEW surfaces built
// on top of that wiring (the deck pills, and the fired -> held -> all default)
// rather than the wiring itself. document.getElementById returns null and
// document.addEventListener("click", ...) is a no-op in this harness (see the
// harness comment at the top of the file), so — exactly like the Phase 3
// scoping/nav checks above — anything that would need a real click or a real
// rendered DOM is asserted structurally against the shipped source instead of
// simulated. The async fired/held/all fallback itself (load() resolving a
// real payload) was traced with a throwaway script against the real fetch
// path, pasted into the Phase 5 handoff, rather than folded in here — this
// suite's job is to lock the shape of the code that trace exercised.
suite("deck pills — one FILTER, two surfaces, plus the fired -> held -> all default");

test("rowsFor gained a blocked branch — S1 BLOCKED was reachable in the URL since Phase 2 but never wired to a filter", () => {
  const body = SRC.slice(SRC.indexOf("function rowsFor("), SRC.indexOf("function stateChip("));
  assert.ok(/FILTER === "blocked"[\s\S]{0,40}r\.s1_blocked/.test(body),
    "must filter on the same s1_blocked boolean the scan publishes per row");
});

test("blocked round-trips through applyState/getTurtleState now that a control actually sets it", () => {
  T.applyState(T.parseTurtleURL("?f=blocked"));
  assert.equal(T.getTurtleState().f, "blocked");
  assert.ok(T.serialiseTurtleURL(T.getTurtleState()).includes("f=blocked"));
});

test("the deck pills and the SIGNALS segs list the same five FILTER values, in the same order", () => {
  const pillsBody = SRC.slice(SRC.indexOf("function deckPillsHTML("), SRC.indexOf("function deckHTML("));
  const segsBody = SRC.slice(SRC.indexOf("function render("), SRC.indexOf("function renderBody("));
  const order = ["fired", "held", "near", "blocked", "all"];
  const pillKeys = [...pillsBody.matchAll(/\["(\w+)", "[^"]+", /g)].map((m) => m[1]);
  const segKeys = [...segsBody.matchAll(/\["(\w+)", "[^"]+"\]/g)].map((m) => m[1]);
  assert.deepEqual(pillKeys, order, "deck pill order must be FIRED TODAY / IN A POSITION / APPROACHING / S1 BLOCKED / ALL");
  assert.deepEqual(segKeys, order, "\"Active pill === active seg\" only holds if position matches too");
  assert.deepEqual(pillKeys.slice().sort(), ["all", "blocked", "fired", "held", "near"],
    "must be exactly the URL contract's five URL_FILTERS values, no more, no fewer");
});

test("both surfaces derive is-active/aria-pressed from the same FILTER comparison", () => {
  const pillsBody = SRC.slice(SRC.indexOf("function deckPillsHTML("), SRC.indexOf("function deckHTML("));
  assert.ok(/const active = FILTER === k/.test(pillsBody));
  assert.ok(/aria-pressed/.test(pillsBody), "pills are buttons with real pressed state, not styled links");
});

test("IN A POSITION is aggregate.long + aggregate.short, never a filter over the truncated results array", () => {
  const body = SRC.slice(SRC.indexOf("function filterCounts("), SRC.indexOf("const NEXT_CRON"));
  assert.ok(/held:\s*\(a\.long \|\| 0\) \+ \(a\.short \|\| 0\)/.test(body),
    "DATA.results is truncated on large markets and keeps only a sample of the flat rows, so " +
    "counting the array under-counts held positions the moment a market is big enough to truncate");
});

test("the deck renders unconditionally — pills are not gated to the SIGNALS view", () => {
  const body = SRC.slice(SRC.indexOf("function render("), SRC.indexOf("function renderBody("));
  const deckLine = body.slice(body.indexOf("const deck ="), body.indexOf("const tabs ="));
  assert.ok(!/VIEW ===/.test(deckLine),
    "pills must be visible on RULES/SIZING/EVIDENCE too, per the phase spec");
});

test("a pill click switches VIEW to signals as well as FILTER, so a pill works from any view", () => {
  // mount() is the last function before the window.GBSTurtle export, so
  // slicing to that export is the whole function body -- robust to mount()
  // growing in later phases, unlike a fixed character count that a later
  // phase's own new click branch can silently push past (Phase 6 did,
  // fixing what used to be a hardcoded +3500 here).
  const mountBody = SRC.slice(SRC.indexOf("function mount("), SRC.indexOf("window.GBSTurtle = {"));
  assert.ok(/FILTER = f\.dataset\.filter; VIEW = "signals";/.test(mountBody),
    "clicking a deck pill from RULES/SIZING/EVIDENCE must land on SIGNALS with that filter live");
});

test("SKIPS is its own attribute — not a ninth view, not a FILTER value", () => {
  // mount() is the last function before the window.GBSTurtle export, so
  // slicing to that export is the whole function body -- robust to mount()
  // growing in later phases, unlike a fixed character count that a later
  // phase's own new click branch can silently push past (Phase 6 did,
  // fixing what used to be a hardcoded +3500 here).
  const mountBody = SRC.slice(SRC.indexOf("function mount("), SRC.indexOf("window.GBSTurtle = {"));
  assert.ok(/closest\("\[data-skips\]"\)/.test(mountBody));
  assert.ok(/VIEW = "book";[\s\S]{0,40}pushURLState\(\)/.test(mountBody),
    "SKIPS must push the existing book view onto the URL like any other view change");
  assert.ok(/getElementById\("tt-skips"\)/.test(mountBody), "must scroll the skip table into view");
  const start = SRC.indexOf("const VIEWS = [");
  const viewsBody = SRC.slice(start, SRC.indexOf("];", start) + 2);
  assert.ok(!/skips/i.test(viewsBody), "VIEWS must not gain a ninth tab for this");
  const tabCount = (viewsBody.match(/\["\w+",/g) || []).length;
  assert.equal(tabCount, 8, "signals/held/closed/summary/book/rules/sizing/evidence");
});

test("#tt-skips exists on the skip-reason section so the SKIPS pill has something to scroll to", () => {
  const bookBody = SRC.slice(SRC.indexOf("function bookHTML("), SRC.indexOf("function portfolioCardHTML("));
  assert.ok(/id="tt-skips"[\s\S]{0,40}Not taken, and why/.test(bookBody),
    "the id must land on the skip-reason card specifically, not somewhere unrelated");
});

test("no grade language reached the deck — Turtle has no A+", () => {
  const body = SRC.slice(SRC.indexOf("function filterCounts("), SRC.indexOf("function rulesHTML("));
  assert.ok(!/\bgrade\b|A\+|fpill top/i.test(body));
});

test("the default FILTER falls fired -> held -> all, gated on TOUCHED so a URL or click always wins", () => {
  const loadBody = SRC.slice(SRC.indexOf("function load("), SRC.indexOf("function deckHTML("));
  assert.ok(/if \(!TOUCHED && DATA && FILTER === "fired"\)/.test(loadBody),
    "must never override a filter the URL or a click already chose");
  assert.ok(/if \(!a\.fired_today\)/.test(loadBody), "only falls through when FIRED TODAY is truly empty");
  assert.ok(/FILTER = \(a\.long \|\| a\.short\) \? "held" : "all"/.test(loadBody),
    "held next, then all — never straight to all while any position is open");
});

// ── 13. rows, chart links and book facts (Phase 6) ──────────────────────────
// chartHref is pure and now exported, so it gets real functional tests, the
// same as parseTurtleURL/serialiseTurtleURL. Everything that needs BOOK/DATA
// state (the vehicle badge, the sort cycle actually reordering rows, the
// book-open/skip panels) is asserted structurally for the same reason as the
// Phase 5 suite above: this harness cannot simulate a real click or read
// rendered HTML. The dynamic proof (real fetch fixtures, real clicks, real
// innerHTML) went through a throwaway script — deleted after its output was
// pasted into the phase report — covering: an ASX/CRYPTO row's chart <a>,
// a FUTURES row's honest no-link text, the vehicle badge appearing only on
// a symbol actually open in a levered sleeve (never on a cash-only open
// position or a name that isn't open anywhere), all four sort stops
// actually reordering a populated fixture, the book-open detail panel
// (units/avg/stop/open R, plus posted margin + a re-derived liquidation
// distance on a levered sleeve), the skip line showing the raw reason code,
// and a hostile symbol breaking neither the href nor the row toggle.
suite("chartHref — asx/nasdaq/crypto get a real link, futures never gets a dead one");

test("chartHref builds chart.html?m=<market>&s=<sym>&src=turtle for a cash market", () => {
  assert.equal(T.chartHref("asx", "TLC"), "chart.html?m=asx&s=TLC&src=turtle");
  assert.equal(T.chartHref("nasdaq", "AAPL"), "chart.html?m=nasdaq&s=AAPL&src=turtle");
  assert.equal(T.chartHref("crypto", "BTC"), "chart.html?m=crypto&s=BTC&src=turtle");
});

test("chartHref returns null for futures — chart.html cannot take a continuous contract symbol", () => {
  assert.equal(T.chartHref("futures", "6E"), null);
  assert.equal(T.chartHref("futures", "=F"), null);
});

test("chartHref encodes a hostile symbol rather than splicing it into the query string raw", () => {
  const href = T.chartHref("asx", 'A"><script>alert(1)</script>');
  assert.ok(!href.includes("<script>") && !href.includes('"') && !href.includes("<"));
});

suite("row head + detail — stop figure, vehicle badge, chart link, book facts, sort cycle");

test("the row head shows a stop figure from the published unit_stop_loss, guarded on its presence", () => {
  const body = SRC.slice(SRC.indexOf("function rowHTML("), SRC.indexOf("const kv ="));
  assert.ok(/r\.unit_stop_loss != null/.test(body), "must not render a stop line the payload never sent");
});

test("the vehicle badge is derived from params.leverage, never a hardcoded multiplier", () => {
  const body = SRC.slice(SRC.indexOf("function vehicleBadgeHTML("), SRC.indexOf("function bookOpenHTML("));
  assert.ok(/leverageOf\(positions\[i\]\.market\)/.test(body),
    "must look up the sleeve's own params, not assume which market is levered");
  assert.ok(/big\(lev\)/.test(body), "the displayed multiplier must come from the params value");
});

test("the vehicle badge only matches a symbol actually open in a levered sleeve", () => {
  const body = SRC.slice(SRC.indexOf("function bookOpenPositions("), SRC.indexOf("function leverageOf("));
  assert.ok(/BOOK\.open\.filter\(\(p\) => p\.symbol === symbol\)/.test(body),
    "must filter BOOK.open by this exact symbol, not assume a match");
});

test("the detail panel links to a real chart for asx/nasdaq/crypto and never a dead futures link", () => {
  const body = SRC.slice(SRC.indexOf("function rowHTML("), SRC.indexOf("const kv ="));
  assert.ok(/const href = chartHref\(MARKET, r\.symbol\)/.test(body));
  assert.ok(/no chart for this contract\./.test(body), "the futures fallback text, verbatim");
  assert.ok(!/<a[^>]*href="[^"]*"[^>]*>\s*<\/a>|href=""/.test(body), "never an empty or dead <a>");
});

test("book-open facts (units/avg/stop/open R) never invent a missing field", () => {
  const openRBody = SRC.slice(SRC.indexOf("function openR("), SRC.indexOf("function liqDistanceR("));
  assert.ok(/if \(!p \|\| !p\.n \|\| !p\.units \|\| p\.last_mark == null \|\| p\.cost_basis == null\) return null;/
    .test(openRBody), "openR must return null, not a guess, when a required field is missing");
  const bookOpenBody = SRC.slice(SRC.indexOf("function bookOpenHTML("), SRC.indexOf("function bookSkipHTML("));
  assert.ok(/avg != null \? kv\("Avg fill"/.test(bookOpenBody));
  assert.ok(/p\.stop != null \? kv\("Stop"/.test(bookOpenBody));
  assert.ok(/r != null \? kv\("Open R"/.test(bookOpenBody));
});

test("posted margin and liquidation distance only render on a levered sleeve, liq distance re-derived from published fields only", () => {
  const liqBody = SRC.slice(SRC.indexOf("function liqDistanceR("), SRC.indexOf("function bookOpenPositions("));
  assert.ok(/if \(!p \|\| !p\.posted \|\| !p\.units \|\| p\.cost_basis == null \|\| p\.last_mark == null \|\| !p\.n\) return null;/
    .test(liqBody), "must omit rather than fabricate when posted/units/cost_basis/last_mark/n is missing");
  assert.ok(!/pos\[["']liq/i.test(liqBody) && !/\.liq_price|\.liquidation_price/.test(liqBody),
    "the payload never publishes a liq price field — must be computed, not read from a field that doesn't exist");
  const bookOpenBody = SRC.slice(SRC.indexOf("function bookOpenHTML("), SRC.indexOf("function bookSkipHTML("));
  assert.ok(/if \(lev\) \{/.test(bookOpenBody), "posted/liq lines must be gated on the sleeve actually being levered");
});

test("the skip line shows the book's raw reason code, verbatim, not a translated phrase", () => {
  const body = SRC.slice(SRC.indexOf("function bookSkipHTML("), SRC.indexOf("const SORT_CYCLE"));
  assert.ok(/<code>" \+ esc\(last\.reason \|\| ""\) \+ "<\/code>/.test(body));
});

test("the sort cycle is FIRED -> DISTANCE -> N -> SYMBOL, default FIRED, persisted via the sort URL key", () => {
  assert.deepEqual(T.parseTurtleURL("").sort, "fired");
  const body = SRC.slice(SRC.indexOf("const SORT_CYCLE"), SRC.indexOf("function distanceOf("));
  assert.ok(/const SORT_CYCLE = \["fired", "distance", "n", "symbol"\];/.test(body));
});

test("the sort-cycle button advances SORT and repaints its own label (render, not renderBody)", () => {
  const mountBody = SRC.slice(SRC.indexOf("function mount("), SRC.indexOf("window.GBSTurtle = {"));
  assert.ok(/closest\("\[data-sort-cycle\]"\)/.test(mountBody));
  assert.ok(/SORT = SORT_CYCLE\[\(SORT_CYCLE\.indexOf\(SORT\) \+ 1\) % SORT_CYCLE\.length\];[\s\S]{0,40}pushURLState\(\);[\s\S]{0,20}render\(\);/
    .test(mountBody), "must call the full render(), or the button's own displayed sort name never updates");
});

test("distance-sort never invents a value: fired is 0, otherwise the payload's own nearest/stop distance, else last", () => {
  const body = SRC.slice(SRC.indexOf("function distanceOf("), SRC.indexOf("function sortRows("));
  assert.ok(/if \(r\.signal\) return 0;/.test(body));
  assert.ok(/r\.nearest\.distance_pct/.test(body));
  assert.ok(/r\.stop_distance_pct/.test(body));
  assert.ok(/return Infinity;/.test(body), "unsortable rows must sort last, not be given a fake distance");
});

test("rowsFor copies before it sorts — DATA.results itself is never mutated", () => {
  const rowsForBody = SRC.slice(SRC.indexOf("function rowsFor("), SRC.indexOf("function stateChip("));
  assert.ok(/let rows = DATA\.results\.slice\(\);/.test(rowsForBody), "must copy before any filtering or sorting");
  assert.ok(/return sortRows\(rows\);/.test(rowsForBody), "must sort the local copy, never DATA.results directly");
  const sortBody = SRC.slice(SRC.indexOf("function sortRows("), SRC.indexOf("function rowHTML("));
  assert.ok(!/DATA\.results/.test(sortBody), "sortRows must not reach back into DATA.results at all");
});

test("hostile row symbols still cannot break the keyboard focus-restore selector (Phase 6 unchanged)", () => {
  // Re-asserted here because Phase 6 is the first phase where a row's own
  // detail can throw on missing fields if openR/liqDistanceR/bookOpenHTML
  // aren't careful -- this guards the OLDER, unrelated selector-safety
  // guarantee stays intact alongside the new code, not the new code itself.
  assert.ok(!/querySelector\([^)]*\+\s*row\.dataset/.test(CODE));
  assert.ok(/rows\[i\]\.dataset\.sym === row\.dataset\.sym/.test(CODE));
});

// ── 13. BOOK is the money surface (Phase 7) ─────────────────────────────────
// Open positions and closed trades are facts and now lead the view; by-market
// and skips are still fact, one level more aggregated; the headline essay and
// the portfolio replay are context FOR those facts and now read last. A
// symbol in either the open-positions or the skip-reason table is now a real
// click/keyboard target (jumpToBookSymbol) that jumps to that symbol's market
// on SIGNALS with the row expanded -- reverting to the prior view if the
// symbol turns out not to be in that market's scan, rather than landing on
// an empty expansion. Like Phase 5/6, document.getElementById returns null
// and document.addEventListener("click", ...) is a no-op in this harness, so
// the dynamic jump/revert behaviour was traced with a throwaway script
// against the real fetch path (pasted into the Phase 7 handoff) rather than
// folded in here -- this suite locks the shape of the code that trace
// exercised.
suite("BOOK is the money surface (Phase 7) — order, clickable symbols, portfolio card last");

test("bookHTML puts open positions and closed trades before by-market, skips, the essay and the portfolio card", () => {
  const body = SRC.slice(SRC.indexOf("function bookHTML("), SRC.indexOf("function portfolioCardHTML("));
  const iOpen = body.indexOf("<h3>Open positions</h3>");
  const iClosed = body.indexOf("<h3>Closed, most recent first</h3>");
  const iByMarket = body.indexOf("<h3>By market</h3>");
  const iSkips = body.indexOf('id="tt-skips"');
  const iEssay = body.indexOf("the only honest number here");
  const iPortfolioCall = body.indexOf("portfolioCardHTML()");
  assert.ok([iOpen, iClosed, iByMarket, iSkips, iEssay, iPortfolioCall].every((i) => i !== -1),
    "all six sections must still be present");
  assert.ok(iOpen < iClosed && iClosed < iByMarket && iByMarket < iSkips &&
    iSkips < iEssay && iEssay < iPortfolioCall,
    "order must be: open, closed, by-market, skips, essay, portfolio card");
});

test("BOOK now calls portfolioCardHTML() too, without duplicating EVIDENCE's existing call site", () => {
  const bookCalls = SRC.match(/h \+= portfolioCardHTML\(\);/g) || [];
  const evidenceCalls = SRC.match(/\$\{portfolioCardHTML\(\)\}/g) || [];
  assert.equal(bookCalls.length, 1, "BOOK must call portfolioCardHTML() exactly once");
  assert.equal(evidenceCalls.length, 1, "EVIDENCE's pre-existing call site must be untouched, not duplicated");
});

test("scanMarketFor strips a leverage suffix generically and falls back to the real market list", () => {
  assert.ok(/function scanMarketFor\(market\) \{/.test(SRC));
  const body = SRC.slice(SRC.indexOf("function scanMarketFor("), SRC.indexOf("function scanMarketFor(") + 400);
  assert.ok(/\.replace\(\/\\d\+x\$\/i, ""\)/.test(body),
    "must strip a trailing <digits>x suffix generically, never name a sleeve");
  assert.ok(/MARKETS\.indexOf\(base\) !== -1 \? base : market/.test(body),
    "an unrecognised key must fall back to itself, never be guessed at");
});

test("open-position and skip-row symbols are real click/keyboard targets, not plain text", () => {
  assert.ok(/openSymbolHTML\(p\.symbol, p\.market\)/.test(SRC),
    "posRow must route the symbol cell through openSymbolHTML");
  assert.ok(/openSymbolHTML\(k\.symbol, k\.market\)/.test(SRC),
    "the skip table's symbol cell must route through openSymbolHTML too");
  const body = SRC.slice(SRC.indexOf("const openSymbolHTML"), SRC.indexOf("const posRow"));
  assert.ok(/data-open-symbol="/.test(body) && /data-open-market="/.test(body),
    "both attributes the click/keydown delegate reads must be emitted");
  assert.ok(/scanMarketFor\(market\)/.test(body),
    "the market attribute must be normalised, never a raw BOOK sleeve key");
  assert.ok(/tabindex="0"/.test(body) && /role="button"/.test(body),
    "a <span> click target must be keyboard-reachable and announce itself");
});

test("jumpToBookSymbol forces SIGNALS + FILTER=all and marks TOUCHED before pushing", () => {
  const body = SRC.slice(SRC.indexOf("function jumpToBookSymbol("), SRC.indexOf("function jumpToBookSymbol(") + 1400);
  assert.ok(/VIEW = "signals"; FILTER = "all"; OPEN = sym; TOUCHED = true;/.test(body),
    "FILTER must be forced to all -- a narrower filter could hide the very row being jumped to");
  assert.ok(/pushURLState\(\);[\s\S]{0,20}load\(\)\.then/.test(body),
    "state must be pushed before the fetch, matching every other handler in this file");
});

test("a symbol not found in the destination market's scan reverts the jump instead of stranding the reader", () => {
  const body = SRC.slice(SRC.indexOf("function jumpToBookSymbol("), SRC.indexOf("function jumpToBookSymbol(") + 1400);
  assert.ok(/DATA\.results\.some\(\(r\) => r\.symbol === sym\)/.test(body),
    "membership must be checked against the freshly loaded scan, not assumed");
  assert.ok(/VIEW = prevView; MARKET = prevMarket; FILTER = prevFilter; OPEN = prevOpen;/.test(body),
    "an unfound symbol must restore the exact prior view/market/filter/open state");
});

test("the click delegate and the keydown handler both wire [data-open-symbol] to jumpToBookSymbol, exactly once each", () => {
  const mountBody = SRC.slice(SRC.indexOf("function mount("), SRC.indexOf("window.GBSTurtle = {"));
  const kwIdx = mountBody.indexOf('addEventListener("keydown"');
  const clickBranch = mountBody.slice(0, kwIdx);
  const keydownBranch = mountBody.slice(kwIdx);
  assert.ok(/e\.target\.closest\("\[data-open-symbol\]"\)/.test(clickBranch), "click delegate missing the selector");
  assert.ok(/e\.target\.closest && e\.target\.closest\("\[data-open-symbol\]"\)/.test(keydownBranch),
    "keydown handler missing the selector");
  const clickCalls = clickBranch.match(/jumpToBookSymbol\(os\.dataset\.openSymbol, os\.dataset\.openMarket\)/g) || [];
  const keydownCalls = keydownBranch.match(/jumpToBookSymbol\(os\.dataset\.openSymbol, os\.dataset\.openMarket\)/g) || [];
  assert.equal(clickCalls.length, 1, "click delegate must call jumpToBookSymbol exactly once");
  assert.equal(keydownCalls.length, 1, "keydown handler must call jumpToBookSymbol exactly once");
});

test("N is still read live from by_market and the futures warning is still conditional", () => {
  assert.ok(/const mk = Object\.keys\(BOOK\.by_market \|\| \{\}\);/.test(SRC));
  assert.ok(/\$\{mk\.length\} separate sleeve/.test(SRC));
  assert.ok(/const anyFutures = open\.some\(\(p\) => p\.market === "futures"\);/.test(SRC));
});

test("the levered sleeve is never spelled out literally and never gets its own market button", () => {
  assert.ok(!/crypto5x/i.test(SRC), "turtle.js must never spell the levered sleeve's key literally");
  assert.ok(!/data-market="[^"]*5x/.test(SRC), "no market button may target a levered sleeve directly");
});

test("the portfolio card still avoids grading language from its new BOOK call site", () => {
  const body = SRC.slice(SRC.indexOf("function portfolioCardHTML("), SRC.indexOf("function evidenceHTML("));
  assert.ok(!/expectancy/i.test(body), 'the portfolio card must not claim to answer "does this work"');
  assert.ok(!/does this work/i.test(body));
});

// ── the 5x print on the book (Phase C, 2026-08-23) ──────────────────────────
// Structural, same convention as suite 13 above: posRow/capSkipBadgeHTML/the
// skip-board dedup are not on the exported GBSTurtle surface, so this pins
// the SOURCE shape rather than executing them against fixture data. The
// concrete numbers (a real crypto5x row showing "1u" beside its real coin
// quantity, the skip summary actually reading "N skips: 70 cash · 12
// close-corr...") were traced live against tonight's real journal data with
// a throwaway Playwright script, per the same Phase 7 precedent -- not
// folded in here.
suite("the 5x print on the book (Phase C) — qty vs units, two table shapes, cap badge, skip summary, single-sleeve caveat");

test("posRow renders the Turtle-unit count and the coin/share quantity as two adjacent, distinct cells", () => {
  const body = SRC.slice(SRC.indexOf("const qtyStr ="), SRC.indexOf("const posRow =") + 1400);
  assert.ok(/const qtyStr = \(u\) => \(u == null \? "—" : u < 10 \? num\(u, 4\) : num\(u, 2\)\);/.test(body),
    "qtyStr must format the real quantity at 4dp under 10 and 2dp at/above -- a ZEC-sized 1.2655 and a UNI-sized 213.65 both need real precision, never rounded to an integer");
  const fillsIdx = body.indexOf('(p.fills || []).length + "u');
  const qtyIdx = body.indexOf("qtyStr(p.units)");
  assert.ok(fillsIdx !== -1,
    "the Units cell must come from fills.length (the Turtle pyramid count, 1-4) -- p.units is coin/contract quantity, so a UNI-shaped {units: 213.65, fills: [4.14]} position must render 1u, never 214u");
  assert.ok(qtyIdx !== -1, "the Qty cell must come from qtyStr(p.units), as a column of its own");
  assert.ok(fillsIdx !== -1 && qtyIdx !== -1 && qtyIdx > fillsIdx && qtyIdx - fillsIdx < 60,
    "Units and Qty must be two adjacent cells in the same row, in that order, not merged or separated by unrelated markup");
});

// Pre-upload gate fixture (2026-08-23): the previous test pins the SHAPE of
// the qtyStr/fills.length split; this one actually RUNS the real posRow (not
// a retyped copy) against the literal UNI-shaped position the gate names --
// units:213.65, a single fill -- and reads back the rendered cells.
test("posRow fixture: {units:213.65, fills:[4.14]} renders 1u and 213.65, never 214u", () => {
  const grab = (a, b) => SRC.slice(SRC.indexOf(a), SRC.indexOf(b));
  const numSrc = grab("const num = (v, d) =>", "const money = (v, d) =>");
  const sgnRSrc = grab("const sgnR = (v) =>", "const cls = (v) =>");
  const clsSrc = grab("const cls = (v) =>", "const big = (v) =>");
  const scanMarketForSrc = grab("function scanMarketFor(", "function vehicleBadgeHTML(");
  const openSymbolHTMLSrc = grab("const openSymbolHTML = (symbol, market) =>", "const qtyStr =");
  const qtyStrSrc = grab("const qtyStr =", "const posRow =");
  const posRowSrc = grab("const posRow = (p, levered) => {", "// BOOK IS THE MONEY SURFACE");
  const nextAddStrSrc = grab("function nextAddStr(p) {", "// A symbol can be open in more than one sleeve");

  const rig = new Function("MARKETS", "esc", "P",
    `${scanMarketForSrc}\n${numSrc}\n${sgnRSrc}\n${clsSrc}\n${openSymbolHTMLSrc}\n${qtyStrSrc}\n${nextAddStrSrc}\n${posRowSrc}
     return (p) => posRow(p, false);`
  )(["asx", "nasdaq", "crypto", "futures"], T.esc, T.FALLBACK);

  const rowHTML = rig({ units: 213.65, fills: [4.14] });
  assert.ok(/<td class="mono">1u<\/td>/.test(rowHTML), "the real posRow must render 1u for a single-fill UNI-shaped position");
  assert.ok(!/214u/.test(rowHTML), "must never render fills-count as if it were the coin quantity");
  assert.ok(/<td class="mono">213\.65<\/td>/.test(rowHTML), "the qty cell must show the real 213.65 quantity, 2dp at/above 10");
});

test("open positions split into two table shapes by leverage, never one table with blank Posted/Liq cells", () => {
  assert.ok(/const posRow = \(p, levered\) => \{/.test(SRC),
    "posRow must take a levered flag so cash/levered rendering diverges from one function, not two copies");
  const body = SRC.slice(SRC.indexOf("if (open.length) {"), SRC.indexOf("const closed = (BOOK.closed"));
  assert.ok(/const openCash = open\.filter\(\(p\) => !leverageOf\(p\.market\)\);/.test(body),
    "cash rows must be filtered by leverageOf(p.market), never a market-name check");
  assert.ok(/const openLevered = open\.filter\(\(p\) => leverageOf\(p\.market\)\);/.test(body),
    "levered rows must be filtered by leverageOf(p.market), never a market-name check");
  assert.ok(/<h3>Open positions<\/h3>/.test(body) && /<h3>Open positions — levered sleeve<\/h3>/.test(body),
    "both section headings must be present");
  const cashSection = body.slice(body.indexOf("if (openCash.length)"), body.indexOf("if (openLevered.length)"));
  const leveredSection = body.slice(body.indexOf("if (openLevered.length)"));
  assert.ok(!/<th>Posted<\/th>/.test(cashSection) && !/<th>Liq dist\.<\/th>/.test(cashSection),
    "the cash table's <thead> must not carry Posted/Liq columns at all -- a blank cell reads as almost-levered");
  assert.ok(/<th>Posted<\/th>/.test(leveredSection) && /<th>Liq dist\.<\/th>/.test(leveredSection),
    "the levered table's <thead> must carry Posted/Liq columns");
  assert.ok(/openCash\.map\(\(p\) => posRow\(p, false\)\)/.test(cashSection),
    "cash rows must call posRow with levered=false");
  assert.ok(/openLevered\.map\(\(p\) => posRow\(p, true\)\)/.test(leveredSection),
    "levered rows must call posRow with levered=true");
});

test("capSkipBadgeHTML is scoped to close_corr_cap, derived from the matched skip row, and never names a sleeve or multiplier literally", () => {
  const body = SRC.slice(SRC.indexOf("function capSkipBadgeHTML("), SRC.indexOf("function bookOpenHTML("));
  assert.ok(/k\.reason === "close_corr_cap"/.test(body),
    "must scope to close_corr_cap skips only, not a general skip-reason display");
  assert.ok(/scanMarketFor\(k\.market\) === MARKET/.test(body),
    "must cross-reference the skip's market to this row's market via scanMarketFor -- the same generic suffix-strip Phase 7 uses for the open-position jump -- never a hardcoded sleeve key");
  assert.ok(/big\(last\.units_on_book \|\| 0\)/.test(body) && /big\(last\.cap \|\| 0\)/.test(body),
    "the badge's title must be derived from the matched skip row's own units_on_book/cap, never a hardcoded number");
  assert.ok(/leverageOf\(last\.market\)/.test(body),
    "the badge's multiplier label must come from the matched skip's own leverage, never a literal '5x'/'5×'");
  assert.ok(!/["']5[x×]["']/i.test(body), "must never hardcode a '5x'/'5×' string literal");
});

test("capSkipBadgeHTML is wired into the row head, right after the vehicle badge", () => {
  const body = SRC.slice(SRC.indexOf("function rowHTML("), SRC.indexOf("function rowHTML(") + 2000);
  assert.ok(/vehicleBadgeHTML\(r\.symbol\)\s*\+\s*capSkipBadgeHTML\(r\.symbol\)/.test(body),
    "capSkipBadgeHTML must be called immediately after vehicleBadgeHTML in the row head");
});

test("the skip board deduplicates by symbol×reason×action with a count, and sorts by reason rarity so structural caps surface before the numerous cash rows", () => {
  const body = SRC.slice(SRC.indexOf("const skips = BOOK.skips || [];"),
    SRC.indexOf("<h3>The forward book — the only honest number here</h3>"));
  assert.ok(/const dedup = new Map\(\);/.test(body), "must dedup via a Map");
  assert.ok(/\(k\.symbol \|\| ""\) \+ "\|" \+ \(k\.reason \|\| ""\) \+ "\|" \+ \(k\.action \|\| ""\)/.test(body),
    "dedup key must be symbol|reason|action, matching the spec's symbol×reason×action");
  assert.ok(/existing\.n \+= 1/.test(body), "a repeat must increment a count, not be dropped or duplicated");
  assert.ok(/rows\.slice\(0, 40\)/.test(body) && !/skips\.slice\(0, 40\)/.test(body),
    "the table must iterate the deduped, sorted rows -- not the raw skips array, which buries the 12 close_corr_cap rows under 40 consecutive ASX cash rows");
  assert.ok(/\(counts\[a\.reason\] \|\| 0\) - \(counts\[b\.reason\] \|\| 0\)/.test(body),
    "rows must sort by ascending reason frequency so the rarer, structural reasons surface first");
  assert.ok(/k\.n > 1 \? " &times;" \+ big\(k\.n\)/.test(body),
    "a deduped row's count must render in the Action cell when it collapsed more than one skip");
});

test("the skip board has a one-line summary sentence built live from skip_counts, and its closing note distinguishes cash skips from close-corr skips", () => {
  const body = SRC.slice(SRC.indexOf("const skips = BOOK.skips || [];"),
    SRC.indexOf("<h3>The forward book — the only honest number here</h3>"));
  assert.ok(/const summaryLine = big\(counts\.total \|\| 0\) \+ " skips: "/.test(body),
    "the summary must be built from skip_counts.total, never a hardcoded '83'");
  assert.ok(/\$\{esc\(summaryLine\)\}/.test(body), "the summary sentence must actually render into the section, not just be computed");
  assert.ok(/counts\.cash \? `The <b>\$\{big\(counts\.cash\)\} cash<\/b>/.test(body),
    "the closing note must call out cash skips by their own live count, as its own sentence");
  assert.ok(/counts\.close_corr_cap \? `The <b>\$\{big\(counts\.close_corr_cap\)\}/.test(body),
    "the closing note must call out close-corr skips by their own live count, as a SEPARATE sentence from the cash one -- the two must never be read as one story");
  assert.ok(!/the book is broke/i.test(body), 'the copy must never say "the book is broke"');
});

test("the combined headline flags when only some sleeves have closed a trade, derived from by_market rather than a named sleeve", () => {
  const body = SRC.slice(SRC.indexOf("const mk = Object.keys"), SRC.indexOf("const openSymbolHTML ="));
  assert.ok(/const closedSleeves = mk\.filter\(\(m\) => \(BOOK\.by_market\[m\] \|\| \{\}\)\.closed > 0\);/.test(body),
    "closedSleeves must be derived from by_market's own closed counts, never a hardcoded sleeve name");
  assert.ok(/closedSleeves\.length && closedSleeves\.length < mk\.length/.test(body),
    "the caveat must only fire when SOME but not all sleeves have closed a trade");
  assert.ok(/closedSleeves\.map\(\(m\) => esc\(m\.toUpperCase\(\)\)\)\.join\(", "\)/.test(body),
    "the caveat must name whichever sleeve(s) actually carry the total, read from the data, not written in prose");
});

test("the face-value sentence divides equity_start by the real sleeve count, and the single-sleeve caveat actually renders", () => {
  const start = SRC.indexOf('<p class="tt-note">Equity here is');
  assert.ok(start !== -1, "the realised-only paragraph must still exist");
  const body = SRC.slice(start, SRC.indexOf("</section>", start) + 10);
  assert.ok(/Equity here is <b>realised only<\/b>/.test(body), "the realised-only rule itself must stay untouched");
  assert.ok(/mk\.length > 1 \?/.test(body),
    "the sleeve-count sentence must be conditioned on the real mk.length, not assumed always-plural");
  assert.ok(/money\(s\.equity_start \/ mk\.length, 0\)/.test(body),
    "must divide the real equity_start by the real sleeve count, never a hardcoded $5,000 or fixed divisor");
  assert.ok(/\$\{singleSleeveNote\}/.test(body),
    "the single-sleeve caveat computed above must actually be appended to this paragraph, not just computed and discarded");
});

// ── cash-skip dollars + next-stop from payload (Phase D, 2026-08-23) ────────
// Same structural convention as Phase C above: nextAddStr/fitsOnLeveredHTML
// are not on the exported GBSTurtle surface, so this pins source shape. The
// concrete numbers (today's real cash-skip total, a real crypto5x row's
// Next add figure, a real "fits on Nx" chip) were traced live against
// tonight's actual journal data with a throwaway Playwright script, per the
// same Phase 7/C precedent -- not folded in here.
suite("cash-skip dollars + next-stop from payload (Phase D) — partial-data honesty, shared next-add, never an order");

test("nextAddStr computes the next 0.5N pyramid level from published fields only, shared by BOOK and the SIGNALS detail", () => {
  const body = SRC.slice(SRC.indexOf("function nextAddStr("), SRC.indexOf("function nextAddStr(") + 600);
  assert.ok(/if \(!p \|\| \(p\.fills \|\| \[\]\)\.length >= P\.max_units\) return "max units";/.test(body),
    "must read 'max units' once fills.length reaches P.max_units, never a hardcoded 4");
  assert.ok(/if \(p\.last_fill == null \|\| p\.n == null\) return "—";/.test(body),
    "must omit rather than guess when last_fill or n is missing");
  assert.ok(/num\(p\.last_fill \+ sign \* P\.pyramid_step_n \* p\.n, 4\)/.test(body),
    "must compute last_fill + sign*pyramid_step_n*n -- Turtle's own 0.5N pyramid rule -- never call into turtle_book.py's math");
  assert.ok(/p\.side === "short" \? -1 : 1/.test(body), "the add direction must flip sign for a short");
  const defCount = (SRC.match(/function nextAddStr\(/g) || []).length;
  assert.equal(defCount, 1, "nextAddStr must be defined once and shared, never a second copy for posRow vs bookOpenHTML");
  assert.ok(/'<\/td><td class="mono">' \+ nextAddStr\(p\) \+ "<\/td>";/.test(SRC),
    "posRow must render its Next add cell through the shared helper");
  assert.ok(/const nextAdd = nextAddStr\(p\);/.test(SRC) && /nextAdd !== "—" \? kv\("Next add", nextAdd\) : ""/.test(SRC),
    "bookOpenHTML must call the same shared helper and omit the row entirely when there is nothing to say, never show a bare dash");
});

test("both open-position tables gained a Next add column, in the same place relative to Stop", () => {
  const body = SRC.slice(SRC.indexOf("if (open.length) {"), SRC.indexOf("const closed = (BOOK.closed"));
  const cashSection = body.slice(body.indexOf("if (openCash.length)"), body.indexOf("if (openLevered.length)"));
  const leveredSection = body.slice(body.indexOf("if (openLevered.length)"));
  assert.ok(/<th>Stop<\/th><th>Next add<\/th><th>Open R<\/th>/.test(cashSection),
    "the cash table's Next add column must sit between Stop and Open R");
  assert.ok(/<th>Stop<\/th><th>Next add<\/th><th>Posted<\/th>/.test(leveredSection),
    "the levered table's Next add column must sit between Stop and Posted");
});

test("the cash-skip dollar sentence sums want_notional on the latest bar only, honest about rows missing the field", () => {
  const body = SRC.slice(SRC.indexOf("const latestAsOf ="), SRC.indexOf("if (skips.length) {"));
  assert.ok(/const latestAsOf = skips\.reduce\(\(mx, k\) => \(k\.as_of && \(!mx \|\| k\.as_of > mx\) \? k\.as_of : mx\), null\);/.test(body),
    "latestAsOf must be derived from the real skip rows, never today's wall-clock date");
  assert.ok(/const cashToday = skips\.filter\(\(k\) => k\.reason === "cash" && k\.as_of === latestAsOf\);/.test(body),
    "must restrict to cash-reason skips on the latest bar, so a mid-session re-run cannot double count");
  assert.ok(/const cashTodayPriced = cashToday\.filter\(\(k\) => k\.want_notional != null\);/.test(body),
    "must split out rows that actually carry want_notional before summing");
  assert.ok(/money\(cashTodayPriced\.reduce\(\(sum, k\) => sum \+ k\.want_notional, 0\), 0\)/.test(body),
    "the dollar total must be summed live from want_notional, never a hardcoded figure");
  assert.ok(/cashTodayPriced\.length < cashToday\.length[\s\S]{0,120}without a notional figure on the row/.test(body),
    "a cash skip missing want_notional must be disclosed, never silently dropped from the count or folded into the total");
});

test("the cash-skip sentence reaches the combined card, gated on there being anything to say", () => {
  const start = SRC.indexOf('<p class="tt-note">Equity here is');
  const body = SRC.slice(start, SRC.indexOf("</section>", start) + 10);
  assert.ok(/cashSkipSentence \? `<p class="tt-note">\$\{esc\(cashSkipSentence\)\}/.test(body),
    "the combined card must render the cash-skip sentence through esc(), and only when cashSkipSentence is non-empty");
});

test("fitsOnLeveredHTML only renders for a cash skip with want_notional and an actual levered sibling, comparing against real free_margin", () => {
  const body = SRC.slice(SRC.indexOf("const fitsOnLeveredHTML ="),
    SRC.indexOf('h += `<section class="tt-card" id="tt-skips">'));
  assert.ok(/if \(k\.reason !== "cash" \|\| k\.want_notional == null\) return "";/.test(body),
    "must require both a cash reason and a real want_notional before attempting anything");
  assert.ok(/scanMarketFor\(m\) === k\.market/.test(body),
    "the levered sibling must be found via scanMarketFor's own suffix rule -- never a hardcoded sleeve key");
  assert.ok(/\.params \|\| \{\}\)\.leverage > 1/.test(body),
    "the candidate sibling must actually carry leverage > 1, not just a different key");
  assert.ok(/if \(b\.free_margin == null\) return "";/.test(body),
    "must omit rather than guess when the sibling sleeve has no free_margin published");
  assert.ok(/const posted = k\.want_notional \/ lev;/.test(body) && /const fits = posted <= b\.free_margin;/.test(body),
    "the comparison must be want_notional/leverage against the sibling's real free_margin");
  assert.ok(!/\bbuy\b|\border\b|\bplace\b/i.test(body),
    "the chip's own code and labels must read as a display comparison, never as an instruction to act");
  assert.ok(/esc\(d\.join\(" · "\)\) \+ fitsOnLeveredHTML\(k\) \+ "<\/td><\/tr>";/.test(SRC),
    "the chip must be appended after the escaped detail text in the skip table's Detail cell");
});

// fitsOnLeveredHTML is a closure over mk/BOOK, not a top-level export, so this
// pulls its REAL source text (plus the real money/big/scanMarketFor it calls)
// out of the shipped file and wires them together with new Function -- same
// "run the real file" principle as boot() above, just at closure grain
// instead of whole-IIFE grain. This is the fixture pair from the pre-upload
// gate: posted = want_notional/leverage must be what's compared to
// free_margin, never want_notional itself, or the first case below would
// wrongly fit (25000 vs 3840 is a false fit; 5000 vs 3840 correctly is not).
test("fitsOnLeveredHTML fixture: 25000/5x/3840-free does not fit, 10000/5x/3840-free does", () => {
  const grab = (a, b) => SRC.slice(SRC.indexOf(a), SRC.indexOf(b));
  const moneySrc = grab("const money = (v, d) =>", "const pct = (v, d) =>");
  const bigSrc = grab("const big = (v) =>", "// ── the arithmetic");
  const scanMarketForSrc = grab("function scanMarketFor(", "function vehicleBadgeHTML(");
  const fitsSrc = grab("const fitsOnLeveredHTML =", 'h += `<section class="tt-card" id="tt-skips">');

  const rig = new Function("MARKETS", "CUR", "MARKET", "esc",
    `${moneySrc}\n${bigSrc}\n${scanMarketForSrc}\nlet mk, BOOK;\n${fitsSrc}
     return (m, b, k) => { mk = m; BOOK = b; return fitsOnLeveredHTML(k); };`
  )(["asx", "nasdaq", "crypto", "futures"], { asx: "A$", nasdaq: "$", crypto: "$", futures: "$" }, "crypto", T.esc);

  const mk = ["crypto", "crypto5x"];
  const byMarket = { crypto: { params: {} }, crypto5x: { params: { leverage: 5 }, free_margin: 3840 } };

  const tooBig = rig(mk, { by_market: byMarket }, { reason: "cash", market: "crypto", want_notional: 25000 });
  assert.ok(/is-blocked/.test(tooBig) && /would not fit on 5&times;/.test(tooBig),
    "want_notional=25000, lev=5 -> posted=$5,000 > $3,840 free -> must NOT fit");

  const fits = rig(mk, { by_market: byMarket }, { reason: "cash", market: "crypto", want_notional: 10000 });
  assert.ok(!/is-blocked/.test(fits) && /fits on 5&times;/.test(fits),
    "want_notional=10000, lev=5 -> posted=$2,000 <= $3,840 free -> must fit");
});

// ── 14. mobile 320px (Phase 8) ───────────────────────────────────────────────
// This suite is structural (CSS text), same reasoning as the JS structural
// tests above: it locks the RULE being present, not the rendered pixel
// value -- that was measured live with a real Chromium/Playwright audit
// (real turtle.html, real committed data, four viewports, an actually
// expanded row) and pasted into the Phase 8 commit/handoff, then deleted.
// test/e2e/smoke.e2e.js already asserts turtle.html has zero page-level
// horizontal overflow at 320px across its own run (its own #38 loop) --
// deliberately not duplicated or extended here, per the phase spec's own
// instruction to use the existing 320px check rather than invent a new one.
suite("mobile 320px (Phase 8) — 44px tap targets, scoped to touch widths only");

test("market buttons, view tabs and deck pills get a 44px floor, scoped to the same mobile breakpoint the shared .fpill rule already uses", () => {
  const css = fs.readFileSync(path.resolve(__dirname, "../public/css/turtle.css"), "utf8");
  const start = css.indexOf("@media (max-width: 680px)");
  const end = css.indexOf("@media (max-width: 480px)");
  assert.ok(start !== -1 && end !== -1 && start < end, "the existing 680px responsive block must still exist");
  const block = css.slice(start, end);
  assert.ok(/#tt-market \.market-btn,[\s\S]{0,40}#tt-views \.view-tab,[\s\S]{0,40}#tt-deck \.fpill \{ min-height: 44px; \}/.test(block),
    "market/view/pill must share one 44px min-height rule, scoped to Turtle's own instances");
  // Scoped, not leaked onto the shared component's OTHER pages: nothing
  // before this media block may set a 44px floor unconditionally.
  assert.ok(!/min-height: 44px/.test(css.slice(0, start)),
    "a 44px min-height outside the mobile block would apply to Turtle at every width");
});

test("the chart link becomes a real tap target only where it is its own paragraph, never touching the unrelated sizing-calculator link", () => {
  const css = fs.readFileSync(path.resolve(__dirname, "../public/css/turtle.css"), "utf8");
  const block = css.slice(css.indexOf("@media (max-width: 680px)"), css.indexOf("@media (max-width: 480px)"));
  assert.ok(/\.tt-note > \.tt-link:only-child \{/.test(block),
    "must be scoped to a .tt-link that is the ONLY child of a .tt-note -- the chart link's exact shape");
  assert.ok(/display: inline-flex;[\s\S]{0,20}align-items: center;[\s\S]{0,20}min-height: 44px;/.test(block),
    "min-height alone does nothing on an inline <a> -- display must change too, or the rule is a no-op");
  // The "Work it out for your account" link (rowsFor/sizing goto) sits in a
  // bare <p>, not a .tt-note, so :only-child under .tt-note must never
  // reach it -- checked directly against the real markup, not assumed.
  assert.ok(/<p><a class="tt-link" href="#" data-goto="sizing">/.test(SRC),
    "the sizing-calculator link's markup shape must stay a bare <p>, or the CSS scoping assumption above is wrong");
});

test("the ladder/skip/closed tables keep their own horizontal scrollbox, unchanged", () => {
  const css = fs.readFileSync(path.resolve(__dirname, "../public/css/turtle.css"), "utf8");
  assert.ok(/\.tt-tablewrap \{ overflow-x: auto;/.test(css),
    "a wide table (e.g. the pyramid ladder) must scroll inside its own box, never the page");
});

console.log(`\nturtle.test.js: ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
