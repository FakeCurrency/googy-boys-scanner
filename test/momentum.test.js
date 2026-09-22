/* MOMENTUM — the nav contract, the purple, and the page's honest failures.
 *
 * Everything here reads the SHIPPED files. The nav arrays are EXECUTED out of
 * public/js/nav.js rather than re-declared, and the row/empty-state helpers are
 * sliced out of public/js/momentum.js and run for real — a re-typed fixture
 * drifts in step with the bug it is supposed to catch, which is this repo's
 * standing rule for JS suites.
 *
 * Sandboxes are built with `new Function(body)()`, NOT vm.runInContext: a vm
 * context is a separate realm, so its Array.prototype differs and every
 * cross-realm deepStrictEqual fails for reasons unrelated to the code under
 * test. `new Function` keeps the realm while still function-scoping every
 * top-level declaration in the body.
 */
"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const PUB = path.join(__dirname, "..", "public");
const NAV = fs.readFileSync(path.join(PUB, "js", "nav.js"), "utf8");
const MOM = fs.readFileSync(path.join(PUB, "js", "momentum.js"), "utf8");
const CSS = fs.readFileSync(path.join(PUB, "css", "styles.css"), "utf8");
const MOCSS = fs.readFileSync(path.join(PUB, "css", "momentum.css"), "utf8");
const HTML = fs.readFileSync(path.join(PUB, "momentum.html"), "utf8");

let checks = 0;
const ok = (cond, msg) => { assert.ok(cond, msg); checks++; };
const eq = (a, b, msg) => { assert.strictEqual(a, b, msg); checks++; };

/* ── the nav arrays, executed out of the shipped file ───────────────────── */

function navLists() {
  const from = NAV.indexOf("const PRIMARY");
  const to = NAV.indexOf("// (debug.html retired");
  assert.ok(from > 0 && to > from, "nav.js no longer has the PRIMARY..debug region");
  return new Function(NAV.slice(from, to) +
    "; return { PRIMARY, TABS, MORE, SHEET, OFF_TAB };")();
}

const NAVL = navLists();

/* THE constraint, and it is a CSS one. `.site-tabs` is
 * `grid-template-columns: repeat(6, 1fr)` = 5 tabs + the MORE button, so a 6th
 * tab becomes a 7th grid child and overflows on every phone. Nothing in nav.js
 * states the 5; this asserts both halves so neither can move alone. */
eq(NAVL.TABS.length, 5, "the bottom tab bar fits exactly 5");
ok(/\.site-tabs\s*\{[^}]*grid-template-columns:\s*repeat\(6,\s*1fr\)/.test(CSS),
   "styles.css no longer declares the 6-column tab grid this 5 depends on");

ok(NAVL.PRIMARY.some((x) => x.key === "momentum"), "momentum is a desktop pill");
ok(NAVL.SHEET.some((x) => x.key === "momentum"), "momentum is in the mobile MORE sheet");
ok(!NAVL.TABS.some((x) => x.key === "momentum"), "momentum is NOT a bottom tab");

/* Every PRIMARY key must be reachable on a phone. The pill row is display:none
 * under 680px, so a key in neither TABS nor SHEET is a shipped page with no
 * mobile entry point at all — and nothing else would fail. */
NAVL.PRIMARY.forEach((it) => {
  ok(NAVL.TABS.concat(NAVL.SHEET).some((x) => x.key === it.key),
     `${it.key} is unreachable on mobile: in neither TABS nor SHEET`);
});

/* ONE source for both derivations. They used to be two independent predicates
 * keyed on the literal "alerts", which is how adding a PRIMARY entry could
 * widen TABS to six AND drop the new key out of the sheet in the same edit. */
ok(NAVL.OFF_TAB instanceof Set, "OFF_TAB must be the single source for TABS and SHEET");
ok(NAVL.OFF_TAB.has("momentum") && NAVL.OFF_TAB.has("alerts"), "OFF_TAB holds both");
ok(/TABS = PRIMARY\.filter\(\(x\) => !OFF_TAB\.has\(x\.key\)\)/.test(NAV),
   "TABS must be derived from OFF_TAB");
ok(/PRIMARY\.filter\(\(x\) => OFF_TAB\.has\(x\.key\)\)/.test(NAV),
   "SHEET must be derived from the same set");

const mom = NAVL.PRIMARY.find((x) => x.key === "momentum");
eq(mom.href, "momentum.html", "the key must equal the filename base, or pageKey never matches");
eq(mom.label, "MOMENTUM", "label");
eq(mom.tab, "🟣", "the purple glyph");
eq(NAVL.PRIMARY.findIndex((x) => x.key === "momentum"),
   NAVL.PRIMARY.findIndex((x) => x.key === "specs") + 1,
   "MOMENTUM sits immediately after SPECS");

/* pageKey(), executed, not read. */
(() => {
  const src = NAV.slice(NAV.indexOf("function pageKey"), NAV.indexOf("function paCount"));
  const pageKey = new Function("location", src + "; return pageKey;");
  eq(pageKey({ pathname: "/momentum.html" })(), "momentum", "pageKey maps the page");
  eq(pageKey({ pathname: "/MOMENTUM.HTML" })(), "momentum", "case-insensitive");
  eq(pageKey({ pathname: "/momentum" })(), "momentum", "extensionless too");
  eq(pageKey({ pathname: "/phasemap-legend.html" })(), "phasemap",
     "the one special case still wins");
})();

/* The command palette is derived, so the entry is free — assert that it stays
 * derived rather than becoming a hardcoded list we would have to maintain. */
ok(/\[\.\.\.PRIMARY, \.\.\.MORE\]\.map/.test(NAV),
   "the palette must stay derived from PRIMARY+MORE");
/* ...and that nothing made the new destination fetch a payload on every page
 * load. decorateTabBadges runs on all 12 nav pages. */
ok(!/setBadge\(\s*["']momentum["']/.test(NAV),
   "no per-page badge fetch for this lens");
ok(!/momentum[^"']*\.json/.test(NAV),
   "nav.js must not load the lens's data on every page view");

/* ── the purple ─────────────────────────────────────────────────────────── */

/* Three states, each needing its own specificity because the existing cascade
 * sets color:var(--green) on :hover at (0,3,0) and background:var(--blue) on
 * .is-here at (0,3,0). */
ok(/\.nav-pills \.howto-link\[href="momentum\.html"\]\s*\{/.test(CSS), "rest state");
ok(/\.nav-pills \.howto-link\[href="momentum\.html"\]:hover\s*\{/.test(CSS),
   "hover must be overridden or the pill flickers green");
ok(/\.nav-pills \.howto-link\[href="momentum\.html"\]\.is-here\s*\{/.test(CSS),
   "is-here must be overridden or the pill illuminates blue");
ok(/\.more-sheet-row\[href="momentum\.html"\]\.is-here/.test(CSS),
   "the mobile MORE sheet row illuminates too");

/* Every purple nav rule is momentum-scoped, so no other pill can be touched. */
(() => {
  const block = CSS.slice(CSS.indexOf("MOMENTUM — the one purple destination"));
  const selectors = block.match(/^[.#][^{\n]*\{/gm) || [];
  ok(selectors.length >= 4, "the purple block lost its rules");
  selectors.forEach((sel) => {
    ok(/momentum\.html/.test(sel),
       `a rule in the momentum block is not momentum-scoped: ${sel.trim()}`);
  });
})();

/* --purple must not be REDEFINED: it is byte-identical to --ema-144 and is
 * already inside contrast.test.js's gate, so moving it would repaint a chart
 * line, PhaseMap's fund tag, a journal exit chip and the SPECS label. */
(() => {
  const defs = CSS.match(/--purple:\s*[^;]+;/g) || [];
  eq(defs.length, 1, "--purple must be declared exactly once");
  ok(/#bf5af2/.test(defs[0]), "--purple must keep its shipped value");
  ok(!/--purple\s*:/.test(MOCSS), "momentum.css must not redefine --purple");
})();

/* The page's own tint is an rgba at the house strength, not a new :root hex —
 * a hex token here would slip past contrast.test.js, whose regex requires #. */
ok(/rgba\(191,\s*90,\s*242,\s*0\.16\)/.test(MOCSS),
   "the soft tint must use the house 0.16 strength");

/* ── the page ───────────────────────────────────────────────────────────── */

ok(/js\/nav\.js\?v=\d+/.test(HTML), "the page carries the shared nav");
["js/status.js", "css/status.css", "css/styles.css", "css/fonts.css",
 "css/momentum.css", "js/momentum.js", "js/phasemap-shared.js"].forEach((a) => {
  ok(new RegExp(a.replace(/[./]/g, "\\$&") + "\\?v=\\d+").test(HTML),
     `momentum.html must load ${a} with a version`);
});
/* Checked on the MARKUP, with comments stripped. The first version of this
 * test scanned the raw file and went red on the HTML COMMENT explaining why
 * there is no scan button — the same false-positive class as a fence that bans
 * a word instead of a reference, and the third time it bit in this build. */
const MARKUP = HTML.replace(/<!--[\s\S]*?-->/g, "");
ok(!/api\/scan/.test(MARKUP) && !/id="scan-btn"/.test(MARKUP),
   "no SCAN button: the scan endpoint does not know this lens's markets, so " +
   "one here would be a control that looks like it does something and does not");
ok(/class="topbar deck-top"/.test(HTML) && /id="site-nav"/.test(HTML),
   "the deck header and the nav mount");
["asx", "nasdaq", "crypto"].forEach((m) =>
  ok(new RegExp(`data-market="${m}"`).test(HTML), `${m} market button`));

/* The lens must not have joined the confluence machinery — v1 is forbidden
 * from it, and the shared helper is right there to be called by accident. */
["loadConfluence", "confluenceChipHTML", "confluenceBannerHTML"].forEach((fn) =>
  ok(!new RegExp("\\b" + fn + "\\b").test(MOM),
     `momentum.js must not touch ${fn} — confluence is out of scope for v1`));

/* Data path and hygiene. */
ok(/data\/momentum\/\$\{market\}\.json/.test(MOM),
   "the page reads the lens's own directory");
ok(/fetchTimeout\(/.test(MOM), "a hung connection must become a rejection");
ok(/cache:\s*"no-cache"/.test(MOM), "data must not be served from the HTTP cache");
ok(/const esc = PM\.esc/.test(MOM), "one shared, null-safe escaper");
ok(!/beforeunload/.test(MOM), "a beforeunload listener disqualifies the bfcache");
ok(!/innerHTML\s*=\s*[^;]*\+\s*r\.(name|symbol)\b/.test(MOM),
   "raw interpolation of a payload field into innerHTML");

// The same property as a source pin, because the executed check above can only
// see the ONE href rowHTML renders. If a second link is ever added to this file
// it must not reintroduce the dead key, and this catches it without needing a
// fixture for whatever new row renders it.
ok(!/chart\.html\?symbol=/.test(MOM),
   "chart.html?symbol= is read by nothing — chart.js reads ?s=");
ok(!/[?&]symbol=/.test(MOM), "no ?symbol= query key anywhere in the page");

// chart.js must know where a Momentum row came from, or the back link on the
// chart page falls back to the dashboard and the trip is one-way.
const CHARTJS = fs.readFileSync(path.join(PUB, "js", "chart.js"), "utf8");
const SRCBACK = CHARTJS.slice(CHARTJS.indexOf("const SRC_BACK"),
                              CHARTJS.indexOf("const back = SRC_BACK"));
ok(/momentum:\s*\["momentum\.html"/.test(SRCBACK),
   "chart.js SRC_BACK carries a momentum entry for src=momentum");

/* ── the honest failures, executed ──────────────────────────────────────── */

function slice(name) {
  const at = MOM.indexOf(`function ${name}(`);
  assert.ok(at > 0, `momentum.js no longer defines ${name}`);
  // Ask the PARSER where the function ends rather than balancing braces by
  // hand, which desyncs on the first regex literal or brace inside a string.
  for (let i = MOM.indexOf("{", at); i < MOM.length; i++) {
    if (MOM[i] !== "}") continue;
    const cand = MOM.slice(at, i + 1);
    try { new Function("return (" + cand + ");"); return cand; } catch (_) { /* keep going */ }
  }
  throw new Error(`could not slice ${name}`);
}

(() => {
  // Run the real emptyHTML against the real loadFailKind.
  const loadFailKind = (err) => {
    const m = /(\d{3})$/.exec(String((err && err.message) || "").trim());
    return m && +m[1] === 404 ? "missing" : "unreachable";
  };
  const make = (state) => new Function(
    "state", "esc", "loadFailKind", "retryHTML",
    slice("emptyHTML") + "; return emptyHTML();")(
      state, (s) => String(s == null ? "" : s), loadFailKind,
      (id) => `<button id="${id}">Tap to retry</button>`);

  const missing = make({ loading: false, err: new Error("HTTP 404"), market: "asx", data: null });
  ok(/No ASX momentum scan yet/i.test(missing), "a 404 says the scan has not run");
  ok(!/retry/i.test(missing), "and does NOT offer a retry — there is nothing to retry");

  const down = make({ loading: false, err: new Error("HTTP 503"), market: "nasdaq", data: null });
  ok(/connection problem/i.test(down),
     "a non-404 blames the connection, not the scanner — 'run the scanner' is " +
     "wrong twice over when the user's phone is simply offline");
  ok(/Tap to retry/.test(down), "and offers a retry");

  const empty = make({ loading: false, err: null, market: "asx", data: { results: [] } });
  ok(/Nothing fired/i.test(empty) && /not a fault/i.test(empty),
     "an empty scan is an ordinary day, and says so");

  const filtered = make({ loading: false, err: null, market: "asx", data: { results: [{}] } });
  ok(/No name matches this filter/i.test(filtered),
     "a filter with no match is a different sentence from an empty scan");

  ok(/Loading/i.test(make({ loading: true, market: "asx", data: null })), "loading state");
})();

/* ── the row: both ages, and the conflict ───────────────────────────────── */

(() => {
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const env = (state) => new Function(
    "state", "esc", "fmtPrice", "fmtTurnover",
    slice("dirOf") + "\n" + slice("chip") + "\n" + slice("rulesBadge") + "\n" +
    slice("rowHTML") + "; return rowHTML;")(
      state, esc, (x) => String(x), (x) => String(x));

  const rowHTML = env({ market: "asx" });

  const a = rowHTML({ symbol: "AAA", name: "Alpha Ltd", rule_a: true, rule_b: false,
                      rule_a_direction: "bull", rule_a_bars_ago: 1,
                      rule_a_pivot_bars_ago: 6, rule_a_pivot_bar: "2026-09-12 00:00:00",
                      direction: "bull", close: 1, rsi: 40, dollar_adv_20: 1 });
  // THE property this whole page exists to get right.
  ok(/knew 1b/.test(a), "the row shows when the scanner could KNOW");
  ok(/label 6b back/.test(a), "and the bar the chart label sits on");
  ok(/2026-09-12/.test(a) && !/00:00:00/.test(a),
     "the pivot date is shown without the time component the engine carries");
  eq((a.match(/mo-chip/g) || []).length >= 2, true, "both chips render");
  ok(/class="[^"]*is-bull/.test(a), "the rail is tinted by direction");
  ok(/>A</.test(a), "the badge names the rule that fired");

  /* THE CHART LINK — the 2026-09-22 shipped bug, and why this is executed.
   *
   * v1 wrote `chart.html?symbol=ELS&m=asx`. chart.js reads `params.get("s")`,
   * so the symbol arrived as an unread query key, chart.js saw an empty symbol
   * and rendered its "Pick a ticker" placeholder. Every Momentum row led to a
   * dead end, and nothing caught it because no test had ever OPENED the href
   * the row renders. Asserting on the rendered attribute is the whole point:
   * a source grep for "chart.html" would have passed against the broken file.
   */
  const href = (/href="([^"]+)"/.exec(a) || [])[1] || "";
  ok(href.startsWith("chart.html?"), `the symbol links to the chart, saw "${href}"`);
  // The page is served as HTML, so the row's `&amp;` are entities; a browser
  // hands chart.js the decoded form. Decode before parsing, or this asserts
  // against a string no URLSearchParams will ever see.
  const q = new URLSearchParams(href.replace(/&amp;/g, "&").split("?")[1] || "");
  eq(q.get("s"), "AAA", "chart.js reads ?s= — ?symbol= is the bug, and is silent");
  ok(!q.has("symbol"), "no ?symbol= key, under any spelling");
  eq(q.get("m"), "asx", "the market rides along so the chart loads the right file");
  eq(q.get("src"), "momentum", "src= drives chart.js's back link");

  const both = rowHTML({ symbol: "BBB", rule_a: true, rule_b: true,
                         rule_a_direction: "bull", rule_b_direction: "bull",
                         rule_a_bars_ago: 0, rule_a_pivot_bars_ago: 5,
                         rule_b_score: 3, rule_b_bars_ago: 0, direction: "bull",
                         close: 1, rsi: 50, dollar_adv_20: 1 });
  ok(/>A\+B</.test(both), "both rules firing is its own badge");

  const conflict = rowHTML({ symbol: "CCC", rule_a: true, rule_b: true,
                             rule_a_direction: "bull", rule_b_direction: "bear",
                             rule_a_bars_ago: 0, rule_a_pivot_bars_ago: 5,
                             rule_b_score: 2, rule_b_bars_ago: 0,
                             direction: "conflict", close: 1, rsi: 50, dollar_adv_20: 1 });
  ok(/CONFLICT/.test(conflict), "a disagreement is SHOWN");
  ok(/is-conflict/.test(conflict), "and styled as itself");
  ok(!/is-bull|is-bear/.test(conflict),
     "and NOT collapsed to a direction — surfacing it is the point");

  const short = rowHTML({ symbol: "DDD", rule_b: true, rule_b_direction: "bull",
                          rule_b_score: 2, rule_b_bars_ago: 0, slow_ready: false,
                          direction: "bull", close: 1, rsi: 50, dollar_adv_20: 1 });
  ok(/NO 200/.test(short),
     "a capped score is flagged, not left looking like a weak signal");

  const product = rowHTML({ symbol: "EEE", rule_a: true, rule_a_direction: "bull",
                            rule_a_bars_ago: 0, rule_a_pivot_bars_ago: 5,
                            is_product: true, direction: "bull", close: 1,
                            rsi: 50, dollar_adv_20: 1 });
  ok(/PRODUCT/.test(product), "a non-operating listing says so");

  // Escaping, on the field an attacker would reach: the published name.
  const nasty = rowHTML({ symbol: 'X"><img src=x onerror=1>', name: "<script>bad()</script>",
                          rule_a: true, rule_a_direction: "bull", rule_a_bars_ago: 0,
                          rule_a_pivot_bars_ago: 5, direction: "bull", close: 1,
                          rsi: 50, dollar_adv_20: 1 });
  ok(!/<img src=x/.test(nasty) && !/<script>bad/.test(nasty),
     "payload fields are escaped before they reach innerHTML");
})();

/* ── CHART MODE (2026-09-22) ────────────────────────────────────────────────
 * The lens screens a 20/50/200 stack and an RSI divergence. 5.0's chart draws
 * 10/20/43/200 SMAs and a trade ladder. Opening a Momentum row on the 5.0
 * chart therefore showed averages no Momentum rule consults, so the chart
 * takes a `momentum` mode. The pins below are about the SEAM: the row asks for
 * it, the chart honours it, and a 5.0 link never trips it.
 */
const CHART = fs.readFileSync(path.join(PUB, "js", "chart.js"), "utf8");
const APP = fs.readFileSync(path.join(PUB, "js", "app.js"), "utf8");

// --- the ask: the row sends what the chart reads -----------------------------
ok(/src=momentum/.test(MOM), "the row asks for the momentum chart");

// --- the honour: chart.js resolves that ask ----------------------------------
{
  // Execute the real resolution rather than grepping it: the bug class here is
  // a mode that is spelled right and never reached.
  // Slice ONLY the mode statement: the block after it touches `document`
  // (the back-link), which has no business in a node-side parity check.
  const MODE_END = '? "momentum" : "vivek";';
  ok(CHART.includes(MODE_END),
     "chart.js no longer resolves a momentum mode — every Momentum row would " +
     "fall back to the 5.0 chart and its 10/20/43 stack");
  const src = CHART.slice(CHART.indexOf("const urlMode"),
                          CHART.indexOf(MODE_END) + MODE_END.length);
  const resolve = (q) => new Function("search", `
    const params = new URLSearchParams(search);
    const market = (params.get("m") || "asx").toLowerCase();
    ${src.replace(/const market =[^\n]*\n/, "")}
    return mode;`)(q);
  eq(resolve("?s=ELS&m=asx&src=momentum"), "momentum", "src=momentum enters momentum mode");
  eq(resolve("?s=ELS&m=asx&mode=momentum"), "momentum", "mode=momentum enters momentum mode");
  eq(resolve("?s=ELS&m=asx&SRC=MOMENTUM".toLowerCase()), "momentum", "the match is case-folded");
  // REQUIREMENT 6 — the default must be untouched.
  eq(resolve("?s=BHP&m=asx"), "vivek", "a bare link is still a 5.0 chart");
  eq(resolve("?s=BHP&m=asx&mode=vivek"), "vivek", "an explicit 5.0 link is still 5.0");
  eq(resolve("?s=BHP&m=asx&src=journal"), "vivek", "another lens's src does not divert");
  eq(resolve("?s=X&m=asx&mode=spec"), "spec", "specs still wins its own mode");
}

// --- a 5.0 deck link must not carry it ---------------------------------------
{
  const links = APP.match(/chart\.html\?[^`"']*/g) || [];
  ok(links.length >= 3, `expected several deck chart links, saw ${links.length}`);
  const bad = links.filter((l) => /src=momentum|mode=momentum/.test(l));
  eq(bad.length, 0, `no 5.0 deck link may request momentum mode, saw ${bad.join(" ")}`);
}

// --- the stack: Pine seeding, executed ---------------------------------------
{
  const slc = (name) => {
    const at = CHART.indexOf(`function ${name}(`);
    assert.ok(at > 0, `chart.js no longer defines ${name}`);
    for (let i = CHART.indexOf("{", at); i < CHART.length; i++) {
      if (CHART[i] !== "}") continue;
      const cand = CHART.slice(at, i + 1);
      try { new Function("return (" + cand + ");"); return cand; } catch (_) {}
    }
    throw new Error("slice " + name);
  };
  const emaPine = new Function("return (" + slc("emaPine") + ");")();
  // Pine returns na before `length` bars and seeds on the SMA of the first
  // `length` values. pandas' ewm(adjust=False) seeds on the FIRST value and
  // emits from bar 0 — the difference decays as (1-alpha)^n, i.e. it is
  // largest exactly on the 200 the trend filter tests `close > slow` against.
  const flat = new Array(300).fill(5);
  const e = emaPine(flat, 200);
  ok(!isFinite(e[198]), "na before the seed window closes — not a flat guess");
  ok(isFinite(e[199]), "the first value lands on bar length-1");
  ok(Math.abs(e[199] - 5) < 1e-12, "seeded with the SMA of the first `length` values");
  const ramp = Array.from({ length: 260 }, (_, i) => i + 1);
  const r = emaPine(ramp, 200);
  const sma200 = ramp.slice(0, 200).reduce((a, b) => a + b, 0) / 200;
  ok(Math.abs(r[199] - sma200) < 1e-9, "the seed is the SMA, on a ramp too");
  eq(emaPine(new Array(50).fill(1), 200).every((x) => !isFinite(x)), true,
     "a history shorter than the span yields no line at all");
  // The warm-up must not be back-filled: a drawn line before the seed would
  // claim a 200 EMA on a name that has never had 200 bars.
  eq(r.slice(0, 199).some(isFinite), false, "nothing is drawn before the seed");
}

// --- Rule A marks: pivot loud, confirmation quiet ----------------------------
{
  const slc = (name) => {
    const at = CHART.indexOf(`function ${name}(`);
    assert.ok(at > 0, `chart.js no longer defines ${name}`);
    for (let i = CHART.indexOf("{", at); i < CHART.length; i++) {
      if (CHART[i] !== "}") continue;
      const cand = CHART.slice(at, i + 1);
      try { new Function("return (" + cand + ");"); return cand; } catch (_) {}
    }
    throw new Error("slice " + name);
  };
  const barAtDate = new Function("return (" + slc("barAtDate") + ");")();
  const momentumMarkers = new Function("barAtDate",
    slc("momentumMarkers") + "; return momentumMarkers;")(barAtDate);

  const DAY = 86400;
  const t0 = Math.floor(Date.UTC(2026, 8, 22) / 1000) - 20 * DAY;
  const bars = Array.from({ length: 21 }, (_, i) => ({ time: t0 + i * DAY, close: 1 }));
  const iso = (t) => new Date(t * 1000).toISOString().slice(0, 10);

  const m = momentumMarkers({ rule_a: true, rule_a_direction: "bull",
    rule_a_bars_ago: 0, rule_a_pivot_bars_ago: 5,
    rule_a_pivot_bar: iso(bars[15].time) + " 00:00:00" }, bars);
  eq(m.length, 2, "both the pivot and the confirmation are marked");
  eq(m[0].time, bars[15].time, "the pivot mark sits on the pivot bar");
  eq(m[1].time, bars[20].time, "the confirmation mark sits on the confirming bar");
  ok(/DIV/.test(m[0].text), "the pivot mark names the divergence");
  ok(m[0].shape === "arrowUp" && m[1].shape === "circle",
     "the confirmation is quieter than the pivot — it is the bookkeeping half");
  ok(m[0].color !== m[1].color, "and visually subordinate");

  // The DATE wins over the count. A live feed can be a session ahead of the
  // committed scan, and counting back N bars then lands on the wrong candle —
  // silently, which is the worst way for a chart to be wrong.
  const ahead = bars.concat([{ time: bars[20].time + DAY, close: 1 }]);
  const m2 = momentumMarkers({ rule_a: true, rule_a_direction: "bull",
    rule_a_bars_ago: 0, rule_a_pivot_bars_ago: 5,
    rule_a_pivot_bar: iso(bars[15].time) + " 00:00:00" }, ahead);
  eq(m2[0].time, bars[15].time, "the pivot stays on its DATE when the feed runs ahead");

  // No date → fall back to the count rather than dropping the mark.
  const m3 = momentumMarkers({ rule_a: true, rule_a_direction: "bear",
    rule_a_bars_ago: 1, rule_a_pivot_bars_ago: 6 }, bars);
  eq(m3.length, 2, "a payload with no pivot date still marks both");
  eq(m3[0].time, bars[14].time, "counted back from the last bar");
  ok(m3[0].shape === "arrowDown", "a bear divergence points down");

  eq(momentumMarkers({ rule_a: false }, bars).length, 0, "no Rule A, no marks");
  eq(momentumMarkers(null, bars).length, 0, "no row, no marks");
  // Coincident bars must not stack two marks on one candle.
  const m4 = momentumMarkers({ rule_a: true, rule_a_direction: "bull",
    rule_a_bars_ago: 3, rule_a_pivot_bars_ago: 3 }, bars);
  eq(m4.length, 1, "a coincident pivot and confirmation render once");
}

// --- the plan is the PINE template's, not vivek.py's -------------------------
{
  const fb = CHART.slice(CHART.indexOf("function momentumFallback("),
                         CHART.indexOf("// ── Held-plan chart"));
  ok(/momentumPlan\(/.test(fb), "the chart asks momentumPlan for the ladder");
  ok(/Final_Top_Script\.pine/.test(CHART),
     "the port names the file it came from");
  // The fence that matters: this ladder must not be sourced from the 5.0 scan.
  ok(!/_vivek\.json/.test(fb) && !/fetchResultMeta/.test(fb),
     "a Momentum plan must never be read out of the 5.0 scan payload");
  ok(/Auto plan from the Pine template/.test(CHART),
     "the caption names the plan's source — five ENTRY/SL/TP lines look exactly " +
     "like a 5.0 ladder and are a different system");
  ok(/mom-caption/.test(CHART), "and chart.js applies the caption class");
  {
    const css = fs.readFileSync(path.join(PUB, "css", "chart.css"), "utf8");
    const rule = /\.mom-caption\s*\{([^}]*)\}/.exec(css);
    ok(rule, "chart.css defines a .mom-caption rule");
    ok(!/position:\s*absolute/.test(rule[1]), "the caption is a header chip, not an overlay");
  }
}

/* --- THE ACCEPTANCE TEST, executed -------------------------------------------
 * The owner's TradingView ELS 1D layout reads
 *   Entry 5.88 / SL 6.76 / TP1 5.00 / TP2 4.12 / TP3 3.23.
 * This drives the SHIPPED momentumPlan over the committed ELS daily series and
 * asserts it lands on those numbers. It is the difference between "the port
 * looks right" and "the port reproduces his chart", and it is cheap to keep.
 */
{
  const slc = (name) => {
    const at = CHART.indexOf(`function ${name}(`);
    assert.ok(at > 0, `chart.js no longer defines ${name}`);
    for (let i = CHART.indexOf("{", at); i < CHART.length; i++) {
      if (CHART[i] !== "}") continue;
      const cand = CHART.slice(at, i + 1);
      try { new Function("return (" + cand + ");"); return cand; } catch (_) {}
    }
    throw new Error("slice " + name);
  };
  const TVSRC = CHART.slice(CHART.indexOf("const TV_PLAN = {"),
                            CHART.indexOf("};", CHART.indexOf("const TV_PLAN = {")) + 2);
  const env = new Function(`
    const MOM_MA_DEFAULTS = { ma_type:'EMA', fast_len:20, mid_len:50, slow_len:200 };
    ${TVSRC}
    ${slc("emaPine")} ${slc("rmaPine")} ${slc("rsiPine")}
    ${slc("macdPine")} ${slc("atrPine")} ${slc("momentumPlan")}
    return { momentumPlan, TV_PLAN };`)();

  // The Pine inputs, pinned. Changing one of these changes his chart.
  const T = env.TV_PLAN;
  eq(T.swingLen, 5, "5-bar swing"); eq(T.atrPad, 0.25, "quarter-ATR pad");
  eq(T.maxStopPct, 15, "the 15% stop cap"); eq(T.autoMaxAge, 60, "60-bar freshness");
  eq(T.minScore, 1, "minimum score 1"); eq(T.useRsi, false, "RSI is OFF in the score");
  eq(T.r.join(","), "1,2,3", "TP ladder at 1R/2R/3R");

  const hist = path.join(__dirname, "..", "data", "history", "asx", "ELS.json");
  if (fs.existsSync(hist)) {
    const raw = JSON.parse(fs.readFileSync(hist, "utf8"));
    const bars = raw.bars.map((r) => ({
      time: Math.floor(Date.parse(r[0] + "T00:00:00Z") / 1000),
      open: r[1], high: r[2], low: r[3], close: r[4], volume: r[5],
    }));
    const pl = env.momentumPlan(bars, null);
    ok(pl, "a plan is produced for ELS");
    eq(pl.dir, -1, "the ELS signal is a SHORT, as his chart shows");
    ok(pl.capped, "and its swing stop is cut by the 15% cap");
    const TV = { entry: 5.88, stop: 6.76, tp1: 5.00, tp2: 4.12, tp3: 3.23 };
    for (const k of Object.keys(TV)) {
      const err = Math.abs(pl[k] - TV[k]);
      ok(err <= 0.005,
         `${k}: computed ${pl[k].toFixed(4)} vs TradingView ${TV[k].toFixed(2)} ` +
         `— error $${err.toFixed(4)} (tolerance is TV's 2-decimal display rounding)`);
    }
  }
}

// --- the panes are momentum-only ---------------------------------------------
{
  // Search FORWARD from the pane start: "Session / weekend shading" also names
  // the shadeRows section hundreds of lines earlier, and slicing to the first
  // occurrence produced an EMPTY string that passed nothing. (Caught by the
  // suite going red, not by reading — the same slice-boundary trap as the
  // SRC_BACK block above.)
  const paneAt = CHART.indexOf("let macdHistS = null");
  ok(paneAt > 0, "the momentum pane block is still in render()");
  const pane = CHART.slice(paneAt, CHART.indexOf("// ── Session / weekend shading", paneAt));
  ok(pane.length > 200, "the pane slice is non-empty");
  ok(/if \(d\._momentum\) \{/.test(pane), "the panes are built only for a momentum chart");
  // SUPERSEDED 2026-09-22: these were `priceScaleId: "macd"/"rsi"` bands on the
  // PRICE chart. That is exactly the shape the TV-look pass removed -- a band
  // claiming 0-100 on a price axis is why a $5 stock scaled to -8 -- so the
  // pin now asserts the two are their OWN charts. Kept rather than deleted
  // because the old assertion, left as it was, would have DEMANDED the bug.
  for (const id of ["macdChart", "rsiChart"]) ok(pane.includes(id), `${id} is its own chart`);
  const before = CHART.slice(0, paneAt);
  ok(!/priceScale\("macd"\)|priceScale\("rsi"\)/.test(before),
     "no oscillator scale is touched outside the momentum branch");
}

// --- history is NOT capped by momentum ---------------------------------------
{
  // The Daily pull must be the SHARED constant, not a momentum-only number.
  const fb = CHART.slice(CHART.indexOf("function momentumFallback("),
                         CHART.indexOf("// ── Held-plan chart"));
  // The real property is not "no literals" -- the crypto branch legitimately
  // says "5y", exactly as pmOnlyFallback does -- but that the daily pull is the
  // SAME ONE 5.0 uses. Compared against the shipped pmOnlyFallback rather than
  // a retyped expectation, so retuning the shared range moves both or fails.
  const pmfb = CHART.slice(CHART.indexOf("function pmOnlyFallback("),
                           CHART.indexOf("// ── Held-plan chart"));
  const liveDailyOf = (body) => {
    const at = body.indexOf("const liveDaily");
    return body.slice(at, body.indexOf(";", body.indexOf("DAILY_RANGE", at)))
               .replace(/\s+/g, " ").trim();
  };
  ok(/DAILY_RANGE/.test(fb), "the momentum chart pulls the shared DAILY_RANGE");
  // The constant itself, so "same as 5.0" is anchored to a value and not just
  // to a name: momentum Daily requests range=25y&interval=1d, like 5.0.
  ok(/const DAILY_RANGE = "25y";/.test(CHART), "the shared daily range is 25y");
  ok(/DAILY_RANGE, "1d"/.test(fb), "momentum asks for DAILY bars at that range");
  eq(liveDailyOf(fb), liveDailyOf(pmfb),
     "momentum's daily history pull is byte-identical to the 5.0 fallback's -- " +
     "a Momentum-only history cap is exactly what this forbids");
  ok(!/setVisibleRange|setVisibleLogicalRange/.test(fb),
     "and it sets no momentum-only zoom — render() fits content for every mode");
}

/* ── DAILY FIRST PAINT (2026-09-22) ─────────────────────────────────────────
 * The Daily pull is 25y and the stitcher really serves it
 * (deep_history.test.js pins targetBars("25y","1d") >= 6300), so fitContent()
 * on a long-listed name squeezes 6,000+ bars into the canvas. The lens screens
 * recent structure, so first paint windows to the last ~750 sessions. The full
 * series stays loaded -- this is a VIEW, not a fetch cap, and the test below
 * asserts the data is never truncated.
 */
{
  // P1 (2026-09-22) SUPERSEDED the 750-bar window: first paint is now the LIVE
  // MOVE -- the later of twelve months back and the end of the dead regime --
  // and it applies to every momentum timeframe, not just 1D. The old pins
  // asserted `key === "1D"` and a 750 constant; left as they were they would
  // have demanded the penny-chart back.
  const slc2 = (name) => {
    const at = CHART.indexOf(`function ${name}(`);
    assert.ok(at > 0, `chart.js no longer defines ${name}`);
    for (let i = CHART.indexOf("{", at); i < CHART.length; i++) {
      if (CHART[i] !== "}") continue;
      const cand = CHART.slice(at, i + 1);
      try { new Function("return (" + cand + ");"); return cand; } catch (_) {}
    }
    throw new Error("slice " + name);
  };
  const MONTHS = +(/const MOM_VIEW_MONTHS = (\d+);/.exec(CHART) || [])[1];
  const MULT = +(/const MOM_REGIME_MULT = ([\d.]+);/.exec(CHART) || [])[1];
  const MIN = +(/const MOM_VIEW_MIN_BARS = (\d+);/.exec(CHART) || [])[1];
  eq(MONTHS, 12, "twelve months of context");
  eq(MULT, 1.5, "1.5x the 5th-percentile close ends the dead regime");
  const viewStart = new Function("MOM_VIEW_MONTHS", "MOM_REGIME_MULT", "MOM_VIEW_MIN_BARS",
    "return (" + slc2("momentumViewStart") + ");")(MONTHS, MULT, MIN);

  const hist = path.join(__dirname, "..", "data", "history", "asx", "ELS.json");
  if (fs.existsSync(hist)) {
    const raw = JSON.parse(fs.readFileSync(hist, "utf8"));
    const bars = raw.bars.map((r) => ({
      time: Math.floor(Date.parse(r[0] + "T00:00:00Z") / 1000), close: r[4] }));
    const i = viewStart(bars);
    const leftDate = raw.bars[i][0];
    ok(!/^2021|^2022|^2023|^2024/.test(leftDate),
       `ELS first paint must skip the penny regime, left edge was ${leftDate}`);
    ok(bars.length - i >= MIN, "and still shows a readable number of bars");
    ok(i > 0, "a five-year series is not shown whole on first paint");
    // It is a VIEW: every bar stays loaded.
    ok(!/slice\(|splice\(/.test(slc2("momentumViewStart")),
       "the view rule must not truncate the series — panning reaches all of it");
  }
  // A short series is shown whole rather than padded.
  const shortBars = Array.from({ length: 40 }, (_, k) => ({ time: k * 86400, close: 10 }));
  eq(viewStart(shortBars), 0, "a young listing is shown whole");

  // Applies to the momentum chart only, and to every one of its timeframes.
  const hook = CHART.slice(CHART.indexOf("chart.timeScale().fitContent();"),
                           CHART.indexOf("legend(tf);"));
  ok(/if \(d\._momentum\) \{/.test(hook), "gated on momentum");
  ok(/momentumViewStart\(cs\)/.test(hook), "and driven by the view rule");
  ok(!/key === "1D"/.test(hook), "no longer 1D-only");
  eq((hook.match(/setVisibleLogicalRange|setVisibleRange/g) || []).length, 1,
     "exactly one visible-range call in the TF hook");
  ok(/fitContent\(\);/.test(hook), "fitContent still runs first, for every mode");
}

// P2 — the Auto box and its rungs are TIME-BOUNDED.
{
  const ladder = CHART.slice(CHART.indexOf("function applyMomentumPlan"),
                             CHART.indexOf("// VIVEK: per-timeframe trade levels"));
  ok(/const x0 = pl\.bar/.test(ladder), "the ladder starts at the signal bar");
  // Scoped to the RUNG HELPER: the slice also holds paintMomentumAth, which
  // legitimately keeps createPriceLine (a single all-time high really does
  // apply across the whole axis).
  const rung = ladder.slice(ladder.indexOf("const line = ("), ladder.indexOf("line(pl.stop"));
  ok(/addLineSeries/.test(rung) && !/createPriceLine/.test(rung),
     "rungs are clipped line series, not full-width price lines — a price line " +
     "spans the whole axis and drew the SL back across bars it was never " +
     "measured against");
  ok(/setData\(\[\{ time: x0[\s\S]{0,80}time: xN/.test(rung),
     "each rung runs signal-bar -> last-bar only");
  ok(/removeSeries/.test(ladder), "and is removed as a series on redraw");
}

/* A 1y default on the 5.0 path would be the same bug in reverse: the owner's
 * 2026-09-19 deep-history work exists precisely so the weekly 200-SMA has bars
 * to stand on. This fails if anyone windows the shared path. */
{
  const hook = CHART.slice(CHART.indexOf("chart.timeScale().fitContent();"),
                           CHART.indexOf("legend(tf);"));
  const ranges = hook.match(/setVisibleLogicalRange|setVisibleRange/g) || [];
  eq(ranges.length, 1, "exactly one visible-range call in the TF hook");
  ok(/d\._momentum/.test(hook), "and it is gated on momentum");
  ok(/fitContent\(\);/.test(hook), "fitContent still runs first, for every mode");
}

/* ── A-GRADE CHART (2026-09-22) ─────────────────────────────────────────────
 * Eight owner-specified behaviours. The ones with maths behind them are
 * EXECUTED against the shipped functions; the wiring ones are read off the
 * source at the point that actually does the work.
 */
{
  const slc = (name) => {
    const at = CHART.indexOf(`function ${name}(`);
    assert.ok(at > 0, `chart.js no longer defines ${name}`);
    for (let i = CHART.indexOf("{", at); i < CHART.length; i++) {
      if (CHART[i] !== "}") continue;
      const cand = CHART.slice(at, i + 1);
      try { new Function("return (" + cand + ");"); return cand; } catch (_) {}
    }
    throw new Error("slice " + name);
  };
  const TVSRC = CHART.slice(CHART.indexOf("const TV_PLAN = {"),
                            CHART.indexOf("};", CHART.indexOf("const TV_PLAN = {")) + 2);
  const env = new Function(`
    const MOM_MA_DEFAULTS = { ma_type:'EMA', fast_len:20, mid_len:50, slow_len:200 };
    ${TVSRC}
    ${slc("emaPine")} ${slc("rmaPine")} ${slc("rsiPine")} ${slc("macdPine")}
    ${slc("atrPine")} ${slc("momentumPlan")} ${slc("pivotIdx")}
    ${slc("momentumDivs")} ${slc("momentumCrosses")}
    return { momentumPlan, pivotIdx, momentumDivs, momentumCrosses, rsiPine };`)();

  const hist = path.join(__dirname, "..", "data", "history", "asx", "ELS.json");
  const bars = fs.existsSync(hist)
    ? JSON.parse(fs.readFileSync(hist, "utf8")).bars.map((r) => ({
        time: Math.floor(Date.parse(r[0] + "T00:00:00Z") / 1000),
        open: r[1], high: r[2], low: r[3], close: r[4], volume: r[5] }))
    : null;

  // 6 — EVERY timeframe recomputes. Resampling to 3D must move the plan, or the
  // Daily box has been glued onto a chart whose candles are a different size.
  if (bars) {
    const daily = env.momentumPlan(bars, null);
    const b3 = [];
    for (let i = 0; i < bars.length; i += 3) {
      const g = bars.slice(i, i + 3);
      if (!g.length) continue;
      b3.push({ time: g[0].time, open: g[0].open, close: g[g.length - 1].close,
                high: Math.max(...g.map((x) => x.high)), low: Math.min(...g.map((x) => x.low)),
                volume: 0 });
    }
    const three = env.momentumPlan(b3, null);
    ok(daily, "the daily plan exists");
    ok(!three || three.entry !== daily.entry,
       "a 3D series must not reproduce the Daily entry — that would mean the " +
       "box was glued on rather than recomputed");
    // and the Daily numbers must not have moved (the standing acceptance test)
    const TV = { entry: 5.88, stop: 6.76, tp1: 5.00, tp2: 4.12, tp3: 3.23 };
    for (const k of Object.keys(TV)) {
      ok(Math.abs(daily[k] - TV[k]) <= 0.01,
         `${k} stays within $0.01 of TradingView (${daily[k].toFixed(4)} vs ${TV[k]})`);
    }
  }
  {
    // Scoped to the BUILDER, not the whole file: `momentumPlan(bars` is also
    // the function's own declaration, so a file-wide includes() was satisfied
    // by the definition and stayed green when the call was changed to
    // momentumPlan(daily, ...) — i.e. when the Daily box WAS glued onto every
    // timeframe, the exact thing this section exists to forbid. Found by
    // mutation; a source check must look where the work happens.
    const bAt = CHART.indexOf("const build = (bars) =>");
    ok(bAt > 0, "one builder runs per timeframe");
    const body = CHART.slice(bAt, CHART.indexOf("d.timeframes[\"1D\"] = build(daily)", bAt));
    ok(body.length > 100 && body.length < 1200, "the builder slice is bounded");
    for (const f of ["momentumPanes(bars", "momentumPlan(bars", "momentumCrosses(bars", "momentumDivs(bars"])
      ok(body.includes(f), `the builder recomputes ${f.split("(")[0]} on ITS OWN bars`);
    ok(!/\b(daily|d3|wk|h4)\b/.test(body),
       "the builder must not reach for another timeframe's series");
  }

  // 4H — where the owner actually trades this template. Built from hourly
  // history bucketed to 4H, exactly as the 5.0 chart does it, and put through
  // the SAME builder: his 4H reads Entry 6.46 / SL 7.39 against the Daily's
  // 5.88 / 6.76, so a borrowed Daily box would be wrong by more than a dollar.
  {
    const fb = CHART.slice(CHART.indexOf("function momentumFallback("),
                           CHART.indexOf("// ── Held-plan chart"));
    ok(/bucketBars\(intraday, 4 \* 3600\)/.test(fb), "4H is bucketed from hourly bars");
    ok(/d\.timeframes\["4H"\] = build\(h4\)/.test(fb),
       "and goes through the same builder — never a Daily borrow");
    ok(!/makeTF\(h4|approx/.test(fb),
       "momentum has no approx/reference timeframe: every pane is computed");
    ok(/\.catch\(\(\) => \[\]\)/.test(fb),
       "a market with no hourly feed loses the tab rather than the chart");
    ok(/intraday\.length >= 24/.test(fb), "and a thin intraday feed is refused");
  }

  // 3 — scored-cross labels, signed, on price.
  if (bars) {
    const xs = env.momentumCrosses(bars, null);
    ok(xs.length > 5, `several crosses over five years, saw ${xs.length}`);
    ok(xs.every((x) => x.score >= 1 && x.score <= 3), "each carries its 1-3 score");
    ok(xs.some((x) => x.bull) && xs.some((x) => !x.bull), "both directions occur");
  }
  ok(/\$\{x\.bull \? "\+" : "-"\}\$\{x\.score\}/.test(CHART),
     "the label is signed, so direction reads without the word");
  {
    // P5 LABEL DIET: text only inside the opening window, one per bar; older
    // crosses keep their dot. A five-year tape wore a pile-up of labels that
    // hid the bars under them.
    const mk = CHART.slice(CHART.indexOf("const base = ((tfs[key] || {}).markers"),
                           CHART.indexOf("candle.setMarkers(base)"));
    ok(/momentumViewStart\(cs\)/.test(mk), "the diet uses the same window as first paint");
    ok(/titled\.has\(b\.time\)/.test(mk), "one text per bar — no stacked \"BeaBear\"");
    ok(/x\.score !== 0/.test(mk), "a zero score gets no text");
    ok(/text: inWindow \?/.test(mk), "out-of-window crosses keep the dot, lose the words");
  }
  ok(/Bullish/.test(CHART) && /Bearish/.test(CHART), "and names the direction");

  // 4 — the RSI pane shows HISTORY, not just the newest divergence.
  if (bars) {
    const rsi = env.rsiPine(bars.map((b) => b.close), 14);
    const dv = env.momentumDivs(bars, rsi, null);
    ok(dv.length > 5, `several divergences over five years, saw ${dv.length}`);
    ok(dv.some((x) => x.bull) && dv.some((x) => !x.bull), "both bull and bear");
    // The pivot must precede its confirmation by piv_right bars.
    ok(dv.every((x) => x.confirm - x.pivot === 5), "each tag knows its own 5-bar lag");
    // THE GAP RULE: 6..61 between confirmations, not 5..60. Inherited from
    // TradingView's own indicator via plFound[1]; screen.py carries the note.
    ok(/6\.\.61/.test(CHART), "the off-by-one gap is written down where it is used");
  }
  ok(/\(\(tfs\[key\] \|\| \{\}\)\.divs \|\| \[\]\)\.map/.test(CHART),
     "the pane maps EVERY divergence, not just the latest");

  // 5 — ATH.
  ok(/title: "ATH"/.test(CHART), "an ATH line is drawn");
  ok(/tf\.ath = bars\.reduce/.test(CHART), "from the highest high the timeframe can see");

  // 2 — the shaded zones, not only hairlines.
  ok(/momRiskBand/.test(CHART) && /momRewardBand/.test(CHART), "both zones exist");
  ok(/addBaselineSeries/.test(CHART.slice(CHART.indexOf("const mkBand"))),
     "drawn as filled bands");

  // 1 — the footer is the Auto box, never the empty 5.0 strip.
  const ft = CHART.slice(CHART.indexOf("function renderMomentumFooter"),
                         CHART.indexOf("function footer(d)"));
  ok(ft.length > 400, "renderMomentumFooter exists");
  for (const k of ["Entry", "SL", "TP1", "TP2", "TP3"]) ok(ft.includes(`"${k}"`), `the footer shows ${k}`);
  ok(!/score_max/.test(ft), "and never the 5.0 SCORE x/8 strip");
  ok(/no scored cross in/.test(ft),
     "a timeframe with no plan says WHY rather than printing blanks");
  ok(/if \(d\._momentum\) \{\n      renderMomentumFooter/.test(CHART),
     "footer() routes a momentum chart to it");

  // 7 — PhaseMap off unless ?pm=1.
  const pmFn = CHART.slice(CHART.indexOf("function fetchPhaseMapRec"),
                           CHART.indexOf("function fetchPhaseMapRec") + 900);
  ok(/isMomentum && params\.get\("pm"\) !== "1"/.test(pmFn),
     "a momentum chart fetches no PhaseMap record unless ?pm=1");

  // 8 — 5.0 untouched: every new surface is inside the momentum branch.
  for (const sym of ["momRiskBand = mkBand", "renderMomentumFooter(d, key)"])
    ok(CHART.includes(sym), `${sym} is wired`);
  // Bound at renderMomentumFooter, which now sits BETWEEN renderVivekFooter and
  // footer() — slicing to footer() swallowed the momentum one and made this
  // assert the opposite of what it says. Third time this file has hit a bad
  // slice boundary; the lesson is to bound at the next thing, not a later one.
  const vfStart = CHART.indexOf("function renderVivekFooter");
  const vfEnd = CHART.indexOf("function renderMomentumFooter");
  ok(vfStart > 0 && vfEnd > vfStart, "renderVivekFooter still precedes the momentum footer");
  const vivekFooter = CHART.slice(vfStart, vfEnd);
  ok(!/momRiskBand|renderMomentumFooter|TV_PLAN/.test(vivekFooter),
     "the 5.0 footer is untouched by any of it");
}

/* ── TV LOOK (2026-09-22) ───────────────────────────────────────────────────
 * The page had the right numbers and the wrong face: 5.0's MA palette, 5.0's
 * chrome, and oscillators painted as scaleMargins bands on the PRICE scale --
 * which is why a $5 stock's axis ran to -8. These pin the shape, not the pixels.
 */
{
  // THREE REAL PANES. lightweight-charts 4.1.3 has no multi-pane API, so the
  // oscillators are their own chart instances. A band on the price chart is
  // the failure this forbids.
  const pAt = CHART.indexOf("let macdHistS = null");
  ok(pAt > 0, "the momentum pane block is present");
  const pane = CHART.slice(pAt, CHART.indexOf("// ── Session / weekend shading", pAt));
  ok(/LC\.createChart\(macdBox/.test(pane), "MACD gets its own chart");
  ok(/LC\.createChart\(rsiBox/.test(pane), "RSI gets its own chart");
  ok(!/priceScaleId: "macd"|priceScaleId: "rsi"/.test(CHART),
     "no oscillator rides the PRICE chart's scale any more — that is what made " +
     "a $5 stock's axis run to -8");
  ok(/subscribeVisibleLogicalRangeChange/.test(pane), "the panes are time-synced");
  // `if (syncing` specifically, not just the word: the flag is declared and
  // cleared elsewhere, so a bare /syncing/ stayed green when the GUARD ITSELF
  // was deleted from the handler — the mutation that matters most here,
  // because the recursion it prevents blows the stack on the first pan.
  ok(/if \(syncing[ ,|)]/.test(pane),
     "behind a re-entrancy guard — each handler sets the others, so without it " +
     "the first pan recurses");
  ok((pane.match(/if \(syncing[ ,|)]/g) || []).length >= 2,
     "both the range and the crosshair handlers are guarded");
  ok(/onRenderTeardown\(/.test(pane),
     "and torn down per render — render() re-runs on every timeframe click");
  ok(/autoscaleInfoProvider/.test(pane) && /maxValue: 100/.test(pane),
     "the RSI pane is pinned to 0-100 rather than autoscaling past it");
  ok(/rsiSigS/.test(CHART), "the RSI pane carries its MA, as RSI+ draws it");

  // TV PALETTE on the price stack, not the 5.0 one.
  const mas = CHART.slice(CHART.indexOf("function momentumMAs"),
                          CHART.indexOf("function barsToMomentumTF"));
  ok(/#2196f3/.test(mas), "fast is TV blue");
  ok(/#26a69a/.test(mas), "slow is TV green");
  for (const c of ["#ffd23f", "#a78bfa", "#e5e9f0"])
    ok(!mas.includes(c), `the 5.0 palette colour ${c} is gone from the momentum stack`);

  // TAGS: the name, with the price in the axis label. TV shows "SL 6.76", not
  // "SL +15.00% · 1.0R".
  const ladder = CHART.slice(CHART.indexOf("function applyMomentumPlan"),
                             CHART.indexOf("// VIVEK: per-timeframe trade levels"));
  // The whole `line(` helper, comments stripped, must mention no percent and no
  // R at all. The first version banned one SPELLING (`toFixed(2)}%`) and stayed
  // green when the clutter came back as string concatenation.
  const ladderCode = ladder.replace(/\/\/[^\n]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "");
  const lineFn = ladderCode.slice(ladderCode.indexOf("const line = ("),
                                  ladderCode.indexOf("line(pl.stop"));
  ok(/title: label\b/.test(lineFn), "a ladder tag is just its name");
  ok(!lineFn.includes("%"), "no percent clutter on the tags, in any spelling");
  ok(!/\bR\b/.test(lineFn.replace(/LineStyle|\bLC\b/g, "")), "and no R multiple");
  ok(/lastValueVisible: true/.test(lineFn), "the axis carries the price, via the series last-value label");
  for (const k of ['"SL"', '"ENTRY"', '"TP1"', '"TP2"', '"TP3"'])
    ok(ladder.includes(k), `the box is tagged ${k}`);

  // CHROME that must be off on this mode.
  const dh = CHART.slice(CHART.indexOf("function renderDataHonesty"),
                         CHART.indexOf("function renderDataHonesty") + 700);
  ok(/if \(suppress\)/.test(dh), "renderDataHonesty can be suppressed");
  ok(/renderDataHonesty\(true\)/.test(CHART), "and the momentum chart suppresses it");
  ok(/!d\._heldPlan && !d\._momentum\)/.test(CHART),
     "no 'live fallback' badge — every momentum chart is live-built, so it " +
     "fires on all of them and distinguishes nothing");
  const flash = CHART.slice(CHART.indexOf("function setFlashes"),
                            CHART.indexOf("function setFlashes") + 500);
  ok(/d\._momentum/.test(flash), "no 5.0 FLASH bands on this mode");

  // VOLUME as a thin strip at the foot of the PRICE pane.
  ok(/top: 0\.90, bottom: 0 \}/.test(CHART), "volume is a slim bottom strip here");

  // FOOTER shape: PLAN / ENTRY / SL / TP1-3 / R:R / TF, and never SCORE x/8.
  const ft = CHART.slice(CHART.indexOf("function renderMomentumFooter"),
                         CHART.indexOf("function footer(d)"));
  for (const k of ['"Plan"', '"Entry"', '"SL"', '"TP1"', '"TP2"', '"TP3"', '"R:R"', '"TF"'])
    ok(ft.includes(k), `the footer carries ${k}`);
  // Comments stripped first. The check matched the COMMENT that explains why
  // TRAIL is absent -- the fourth prose collision in this file (the others:
  // "momentum" as existing prose, the `?symbol=` explainer, the `vivek-frames`
  // note). The rule that keeps emerging: assert against code, never against a
  // file that also DESCRIBES the thing being forbidden.
  const ftCode = ft.replace(/\/\/[^\n]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "");
  ok(!/score_max|TRAIL/.test(ftCode), "and neither SCORE x/8 nor 5.0's TRAIL row");
  ok(/No Auto box on this TF/.test(ft), "a plan-less timeframe says so in words");

  // 5.0 IS UNTOUCHED — every new surface is inside the momentum branch.
  const vfStart = CHART.indexOf("function renderVivekFooter");
  const vfEnd = CHART.indexOf("function renderMomentumFooter");
  ok(vfStart > 0 && vfEnd > vfStart, "renderVivekFooter still precedes it");
  ok(!/macdBox|rsiBox|mom-pane|TV_PLAN/.test(CHART.slice(vfStart, vfEnd)),
     "the 5.0 footer knows nothing about any of it");
  ok(/if \(d\._momentum\) \{\n      const host = el\.parentNode;/.test(CHART) ||
     /let subCharts = \[\];\n    if \(d\._momentum\) \{/.test(CHART),
     "the panes are created only for a momentum chart");
  // and the 5.0 stack survives
  ok(/mkSma\(10,  "SMA 10"/.test(CHART) && /mkSma\(43,  "SMA 43"/.test(CHART),
     "the 5.0 chart still draws SMA 10/20/43");
  ok(/function applyVivekLevels/.test(CHART), "and still has its own level ladder");

  // PhaseMap still gated.
  ok(/isMomentum && params\.get\("pm"\) !== "1"/.test(CHART),
     "PhaseMap is still opt-in on this mode");
}

/* ── overnight audit pins (2026-09-22) ─────────────────────────────────────── */
{
  // C — the 5.0 chart must never speak the momentum caption. Asserted on the
  // SHIPPED 5.0 render path, not on the file (chart.js holds both modes), so
  // the check is "the vivek branch cannot reach it", not "the string is absent".
  const vf = CHART.slice(CHART.indexOf("function vivekFallback"),
                         CHART.indexOf("function vivekCryptoBars"));
  ok(vf.length > 200, "the 5.0 fallback slice is bounded");
  ok(!/MOM_CAPTION|mom-caption|Pine template/.test(vf),
     "the 5.0 chart path never sets the momentum caption");
  ok(!/_momentum/.test(vf), "and never flags itself as one");

  // D — PhaseMap is not merely hidden, it is NOT FETCHED unless ?pm=1, so the
  // zones cannot be drawn at all. Asserted at the fetch, which is the only
  // place a record can enter.
  const pm = CHART.slice(CHART.indexOf("function fetchPhaseMapRec"),
                         CHART.indexOf("function fetchPhaseMapRec") + 900);
  ok(/isMomentum && params\.get\("pm"\) !== "1"[\s\S]{0,40}return Promise\.resolve\(null\)/.test(pm),
     "a momentum chart returns a null PhaseMap record before any fetch");

  // The footer never prints the 5.0 SCORE x/8 strip on this mode.
  const mf = CHART.slice(CHART.indexOf("function renderMomentumFooter"),
                         CHART.indexOf("function footer(d)"))
                  .replace(/\/\/[^\n]*/g, "");
  ok(!/score_max|"Score"/.test(mf), "no SCORE x/8 on a momentum footer");

  // One caption, not two.
  eq((CHART.match(/className = "mom-caption"/g) || []).length, 1,
     "exactly one caption element is ever created");
}

console.log(`momentum: ${checks} checks passed`);
