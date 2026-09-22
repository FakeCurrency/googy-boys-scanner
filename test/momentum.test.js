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

console.log(`momentum: ${checks} checks passed`);
