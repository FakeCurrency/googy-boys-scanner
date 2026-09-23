/* HYGIENE (2026-09-23) -- symbols proven dead and deleted.
 *
 * Each symbol below was referenced by NOTHING but its own declaration across
 * public/ (js + html), test/, tests/, phasemap/tests/, functions/, scripts/,
 * scanner/ and .github/workflows/, with comments stripped before counting.
 * The proof table lives in reviews/2026-09-23-hygiene-map.md.
 *
 * These pins keep them gone: re-adding one without a caller is dead code
 * again. The check reads CODE (comments stripped) so history prose may still
 * name a symbol, but a string literal carrying the name DOES fail -- that is
 * the mutation each pin was verified against.
 *
 * Each file is also required to still carry a known-live symbol, so a moved
 * or emptied file cannot make these pins pass vacuously.
 */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");

const PUB = path.join(__dirname, "..", "public");
let checks = 0;
const ok = (cond, msg) => { assert.ok(cond, msg); checks++; };

// Block comments first, then line comments that do not follow a ':' (so a
// "https://" inside a string survives).
const code = (rel) => fs.readFileSync(path.join(PUB, rel), "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/(^|[^:])\/\/[^\n]*/g, "$1");

const GONE = {
  "js/phasemap-insights.js": {
    live: "const spct = ",
    dead: ["pct"],
  },
  "js/journal.js": {
    live: "function splitBot(",
    dead: ["inBatches", "fav", "nowTime", "tradeKey", "priceFor", "cryptoPrice", "stockPrice", "fetchJSON", "YF_TICKER", "drawMiniEquity", "today"],
  },
  "js/app.js": {
    live: "function isHighConviction(",
    dead: ["fmtTurn", "VIEW_KEYS", "HEAD_PREFIX", "HEAD_ROWS", "hasSectorCount", "seccount"],
  },
  "js/chart.js": {
    live: "function momentumViewStart(",
    dead: ["MOM_FIRST_PAINT_BARS", "entryRelTargets", "fetchStockQuote", "levTag", "SIM_CRYPTO_MARGIN", "SIM_CRYPTO_LEVERAGE", "SIM_STOCK_SIZE", "restURL"],
  },
};

for (const [rel, { live, dead }] of Object.entries(GONE)) {
  const src = code(rel);
  ok(src.includes(live), `${rel} no longer carries ${live} -- pins would be vacuous`);
  for (const sym of dead)
    ok(!new RegExp(`\\b${sym}\\b`).test(src),
       `${rel}: ${sym} was proven dead and deleted 2026-09-23; re-adding it needs a caller`);
}

// CSS: the floating live-P&L box went with the manual journal (2026-09-21);
// its .live-pos-box / .lpb-* rules styled markup nothing creates.
{
  const css = code("css/chart.css");
  ok(css.includes("@keyframes ctLivePulse"), "css/chart.css moved -- pin would be vacuous");
  ok(!/\.live-pos-box\b|\.lpb-[\w-]/.test(css),
     "css/chart.css: .live-pos-box / .lpb-* rules were proven dead and deleted 2026-09-23");
}

// SWEEP (2026-09-23) -- journal.css rules for the manual "Me" journal, which
// was removed 2026-09-21: its modal, form, tabs, Claude-vs-Me scoreboard,
// row action buttons, close preview, sync pill and the retired header
// sparkline (drawMiniEquity's .jr-mini-eqsvg). No JS/HTML/data creates any of
// these classes. Pinned as SELECTORS, so a comment may still name one.
{
  const css = code("css/journal.css");
  ok(css.includes(".jr-close-all {"), "css/journal.css moved -- pin would be vacuous");
  const JOURNAL_CSS_GONE = [
    "both-win",
    "bsep",
    "cmp", "cmp-bot", "cmp-head", "cmp-k", "cmp-me", "cmp-row", "cmp-v", "cmp-vs",
    "dir-chip",
    "h-bot", "h-me",
    "has-note",
    "hl",
    "jr-actions", "jr-chart-ico", "jr-chart-link", "jr-close-btn", "jr-close-preview", "jr-cp-label", "jr-cp-note", "jr-cp-row", "jr-cp-val", "jr-del-btn", "jr-equity", "jr-grade", "jr-hidden", "jr-modal-input", "jr-modal-row", "jr-note-btn", "jr-pnl-spark", "jr-pnl-track", "jr-pnl-track-label", "jr-pnl-track-val", "jr-price-tag", "jr-price-wrap", "jr-scoreboard", "jr-sync-pill", "jr-tab", "jr-tab-arrow", "jr-tab-crypto", "jr-tab-label", "jr-tab-mine", "jr-tab-short", "jr-tab-stocks", "jr-tabs", "jr-tf", "jr-mini-eqsvg",
    "lead-bot", "lead-me",
    "mj-actions", "mj-asset-active", "mj-asset-asx", "mj-asset-btn", "mj-asset-crypto", "mj-asset-nasdaq", "mj-asset-switch", "mj-btn-danger", "mj-close-btn", "mj-currency-wrap", "mj-del-btn", "mj-dir-active", "mj-dir-btn", "mj-dir-long", "mj-dir-short", "mj-dir-switch", "mj-field", "mj-form", "mj-full", "mj-hidden", "mj-label", "mj-leverage-row", "mj-modal", "mj-modal-head", "mj-modal-title", "mj-modal-x", "mj-overlay", "mj-preview", "mj-row", "mj-setting", "mj-settings", "mj-sync", "mj-sync-status",
    "side-cta",
    "w-bot", "w-me",
    // second pass: common-word classes the literal scan could not see
    "reason", "both", "me",
  ];
  for (const c of JOURNAL_CSS_GONE)
    ok(!new RegExp(`\\.${c}(?![\\w-])`).test(css),
       `css/journal.css: .${c} styled markup nothing creates and was deleted 2026-09-23`);
  ok(!/--me\s*:/.test(css), "css/journal.css: --me coloured only the Me side's badge (deleted 2026-09-23)");
}

// SWEEP (2026-09-23) -- styles.css rules for markup nothing creates any more:
// the old two-row topbar (row1/row2, clocks, brand, nav, SET UPS title),
// the stars/watchlist (t-star, starred, watched, tb-watch -- removed
// 2026-09-21, with the star-pop keyframes), the retired VIVEK level rows and
// checklist (vk-lvl*, vk-check*; the live ladder is vk-cell/vk-sl/entry/tp),
// the retired EMA/tag detail blocks, and assorted orphans. Pinned as
// SELECTORS; a comment may still name one.
{
  const css = code("css/styles.css");
  ok(css.includes(".fpill.is-active {"), "css/styles.css moved -- pin would be vacuous");
  const STYLES_CSS_GONE = [
    // second pass: the retired track-record strip (2026-07-09) and PULSE (2026-07-20)
    "track", "pulse",
    // third pass: ids the markup uses, never classes (#vk-filters is .tb-chips,
    // #bot-activity is .deck-bot, and no element carries topbar-quote at all)
    "topbar-quote", "vk-filters", "bot-activity",
    "accent-green",
    "ba-label",
    "control-label",
    "deck-npick",
    "grade-A", "grade-Ap",
    "liq-liquid", "liq-ok",
    "nav-minor",
    "olw-row",
    "pm-topnav",
    "pmx",
    "rd-ema", "rd-ema-head", "rd-spread", "rd-tag",
    "scan-switch",
    "seccount",
    "setups-title",
    "sort-arrow",
    "starred",
    "t-star",
    "tb-dim", "tb-watch",
    "topbar-brand", "topbar-clocks", "topbar-clocks-left", "topbar-clocks-right", "topbar-nav", "topbar-row1", "topbar-row2",
    "vk-check", "vk-check-ic", "vk-check-lbl", "vk-check-note", "vk-checklist", "vk-lvl", "vk-lvl-key", "vk-lvl-label", "vk-lvl-price", "vk-lvl-sub",
    "watched",
  ];
  for (const c of STYLES_CSS_GONE)
    ok(!new RegExp(`\\.${c}(?![\\w-])`).test(css),
       `css/styles.css: .${c} styled markup nothing creates and was deleted 2026-09-23`);
  ok(!/@keyframes\s+star-pop\b/.test(css), "css/styles.css: star-pop animated only the deleted .t-star");
  ok(!/--bg-grad\s*:/.test(css),
     "css/styles.css: --bg-grad had no var() reader anywhere and was deleted 2026-09-23 (validate)");
}

// SWEEP (2026-09-23) -- phasemap.css rules for markup nothing creates: the
// old dense Specs rows (sp-row-main/grade/name/price/score/chev/detail,
// sp-levels; specs.js now renders the deck's row classes), the watchlist
// star and tab (removed with the stars), the old standalone PhaseMap chart
// page (pm-chart-head/box/note, #pm-chart), pm-topnav and pm-more-btn.
{
  const css = code("css/phasemap.css");
  ok(css.includes(".pm-chart-cue {"), "css/phasemap.css moved -- pin would be vacuous");
  for (const c of ["is-on", "pm-chart-box", "pm-chart-head", "pm-chart-note", "pm-more-btn", "pm-star", "pm-tab-watchlist", "pm-topnav", "sp-chev", "sp-detail-chips", "sp-grade", "sp-levels", "sp-name", "sp-row-detail", "sp-row-main", "sp-row-price", "sp-row-score", "sp-stop", "sp-target", "sp-list"])
    ok(!new RegExp(`\\.${c}(?![\\w-])`).test(css),
       `css/phasemap.css: .${c} styled markup nothing creates and was deleted 2026-09-23`);
  ok(!/#pm-chart(?![\w-])/.test(css), "css/phasemap.css: no element carries id pm-chart (deleted 2026-09-23)");
}

// SWEEP (2026-09-23) -- css/sectors.css: the per-sector table the NEWS page no longer draws.
{
  const css = code("css/sectors.css");
  ok(css.includes(".sec-up {"), "css/sectors.css moved -- pin would be vacuous");
  for (const c of ["sec-table-wrap", "sec-table", "sec-sym", "sec-name", "sec-bar"])
    ok(!new RegExp(`\\.${c}(?![\\w-])`).test(css),
       `css/sectors.css: .${c} styled markup nothing creates and was deleted 2026-09-23`);
}

// SWEEP (2026-09-23) -- css/stalled.css: the old two-click armed state and a footer the strip no longer renders.
{
  const css = code("css/stalled.css");
  ok(css.includes(".st-x.st-sent {"), "css/stalled.css moved -- pin would be vacuous");
  for (const c of ["st-arm", "st-foot"])
    ok(!new RegExp(`\\.${c}(?![\\w-])`).test(css),
       `css/stalled.css: .${c} styled markup nothing creates and was deleted 2026-09-23`);
}

// SWEEP (2026-09-23) -- css/status.css: sys-dim, which no status markup carries.
{
  const css = code("css/status.css");
  ok(css.includes(".sysdot {"), "css/status.css moved -- pin would be vacuous");
  for (const c of ["sys-dim"])
    ok(!new RegExp(`\\.${c}(?![\\w-])`).test(css),
       `css/status.css: .${c} styled markup nothing creates and was deleted 2026-09-23`);
}

// SWEEP (2026-09-23) -- css/about.css: the EMA-ladder illustration about.html no longer has.
{
  const css = code("css/about.css");
  ok(css.includes(".doc-section"), "css/about.css moved -- pin would be vacuous");
  for (const c of ["ema-ladder"])
    ok(!new RegExp(`\\.${c}(?![\\w-])`).test(css),
       `css/about.css: .${c} styled markup nothing creates and was deleted 2026-09-23`);
}

// STYLESHEET COMMENTS CLOSE (2026-09-23). A regex deletion on 2026-09-20
// (5ac425b2a) glued two comment openers in chart.css onto the rule bodies
// below them, so each comment ran on to the NEXT comment's "*/" -- silently
// disabling the market chip, the loading skeleton, its shimmer keyframes and
// the offline banner on production for three days. CSS reports no parse error
// for this; the only trace is a "/*" nested inside a comment. So: every
// comment in every stylesheet must close before another one opens.
for (const f of fs.readdirSync(path.join(PUB, "css")).filter((x) => x.endsWith(".css"))) {
  const src = fs.readFileSync(path.join(PUB, "css", f), "utf8");
  for (const m of src.matchAll(/\/\*([\s\S]*?)\*\//g)) {
    const line = src.slice(0, m.index).split("\n").length;
    ok(!m[1].includes("/*"),
       `css/${f}: the comment opened at line ${line} never closes before the next "/*" -- ` +
       "every rule between them is silently commented out");
  }
}
{
  const css = code("css/chart.css");
  for (const sel of [".ct-market {", ".chart-skeleton {", "@keyframes sk-shimmer", ".offline-banner {", ".chart-error.is-offline h2"])
    ok(css.includes(sel), `css/chart.css: ${sel} must be live CSS, not swallowed by a comment`);
}

// Locals are pinned inside the function that held them: a two-letter name is
// too common for a whole-file pin. The slice ends where the PARSER says the
// declaration closes, not at a guessed brace.
function fnBody(src, name) {
  const at = src.indexOf(`function ${name}(`);
  ok(at > 0, `${name} moved -- pin would be vacuous`);
  for (let i = src.indexOf("{", at); i < src.length; i++) {
    if (src[i] !== "}") continue;
    const cand = src.slice(at, i + 1);
    try { new Function("return (" + cand + ");"); return cand; } catch (_) { /* keep walking */ }
  }
  throw new Error(`could not slice ${name}`);
}
ok(!/\bep\b/.test(fnBody(code("js/chart.js"), "applyMomentumPlan")),
   "js/chart.js applyMomentumPlan: the unused `ep` local was deleted 2026-09-23 (P2 made the " +
   "rungs line series and dropped the %-label that read it)");

// SWEEP (2026-09-23) -- unused parameters and locals, pinned inside the
// function that held them (reviews/2026-09-23-sweep.md has the proof).
ok(!/\brec\b/.test(fnBody(code("js/chart.js"), "momentumFallback")),
   "js/chart.js momentumFallback: the unused `rec` parameter was deleted 2026-09-23 (the " +
   "caller keeps its own `rec` for pmRec; the PhaseMap record never reached this function)");

ok(!/\baccent\b/.test(fnBody(code("js/journal.js"), "statCards")),
   "js/journal.js statCards: the unused `accent` parameter was deleted 2026-09-23 (its one " +
   "caller never passed it)");

// VALIDATE (2026-09-23) -- the welcome tour must not send a new user to the
// stars / watchlists removed 2026-09-21.
ok(code("js/app.js").includes('"Tap a row for the plan"'), "js/app.js welcome tour moved -- pin would be vacuous");
ok(!/Star \(☆\)|★ watchlist/.test(code("js/app.js")),
   "js/app.js: the welcome tour tells the user to star names; stars were removed 2026-09-21");

// VALIDATE (2026-09-23) -- same rule, second pass (reviews/2026-09-23-validate.md).
ok(code("js/chart.js").includes("const hard = rec.zones.find("), "js/chart.js zone plan moved -- pin would be vacuous");
ok(fnBody(code("js/chart.js"), "momentumFallback").includes("_momentum: true"), "momentumFallback moved -- pin would be vacuous");
ok(!/\b_momRow\b|\b_momParams\b/.test(code("js/chart.js")),
   "js/chart.js momentumFallback: d._momRow / d._momParams were set and never read, deleted " +
   "2026-09-23 (the row and params are used directly inside momentumFallback)");
ok(!/\b_zonePlan\b/.test(code("js/chart.js")),
   "js/chart.js: d._zonePlan was set and never read (its reader, the Simulate buttons, went " +
   "2026-09-21) and was deleted 2026-09-23");
ok(code("js/app.js").includes('mode: "vivek",'), "js/app.js state moved -- pin would be vacuous");
ok(!/\bview\s*:\s*"results"/.test(code("js/app.js")) && !/state\.view\b/.test(code("js/app.js")),
   "js/app.js: state.view was read by nothing once the watch view went (2026-09-21) and was " +
   "deleted 2026-09-23; re-adding it needs a reader");
ok(!/function renderTFSetups\(\s*d\s*,/.test(code("js/chart.js")) && /function renderTFSetups\(tfs,/.test(code("js/chart.js")),
   "js/chart.js renderTFSetups: the unused `d` parameter was deleted 2026-09-23 (the body reads " +
   "only tfs / pickTF / getCurTF; its one caller in render() keeps its own `d`)");

ok(!/\bkey\b/.test(fnBody(code("js/sectors.js"), "macroCardHTML")),
   "js/sectors.js macroCardHTML: the unused `key` parameter was deleted 2026-09-23 (the card " +
   "reads only the macro block m; columnHTML keeps its own key for the news id)");

ok(!/\bisLong\b/.test(fnBody(code("js/journal.js"), "openRows")),
   "js/journal.js openRows: the unused `isLong` row local was deleted 2026-09-23 (liveCells " +
   "derives direction itself)");

// rowHtml's unrendered sector badges. `sector` and `up` are too common to pin
// by name (r.sector is live data; "up" is a class string), so pin the shapes.
ok(!/(?:const|let|var)\s+sector\s*=/.test(fnBody(code("js/app.js"), "rowHtml")),
   "js/app.js rowHtml: the unrendered `sector` badge local was deleted 2026-09-23");
ok(!/(?:const|let|var)\s+up\s*=|\bup\s*\(/.test(code("js/app.js")),
   "js/app.js: the up() helper (read only by the dead seccount badge) was deleted 2026-09-23");

// journal.js's IIFE-level pad() fed only today(); drawEquity keeps its own
// numeric `pad` local, so pin the helper's shape, not the name.
ok(!/const\s+pad\s*=\s*\(/.test(code("js/journal.js")),
   "js/journal.js: the pad() helper (read only by the dead today()) was deleted 2026-09-23");

// window.PM exported fmtPct, srcText and zoneLabel that no page, script or
// test reads (app.js, chart.js and sectors.js each declare their OWN fmtPct).
// The locals stay -- phasemap-shared.js still uses all three itself -- so the
// pin reads the returned object only.
{
  const src = code("js/phasemap-shared.js");
  const at = src.lastIndexOf("return {");
  ok(at > 0 && src.includes("window.PM = "), "js/phasemap-shared.js moved -- pin would be vacuous");
  const api = src.slice(at, src.indexOf("}", at));
  ok(api.includes("esc") && api.includes("loadConfluence"), "PM export object not found -- pin would be vacuous");
  for (const name of ["fmtPct", "srcText", "zoneLabel"])
    ok(!new RegExp(`\\b${name}\\b`).test(api),
       `js/phasemap-shared.js: PM.${name} had no reader and was dropped from the export 2026-09-23`);
}

// window.EYES exported its two storage-key names, which nothing outside
// eyes-store.js reads (app.js, chart.js and eyes.test.js use the methods).
// The vars stay; the pin reads the EYES object literal only.
{
  const src = code("js/eyes-store.js");
  const at = src.indexOf("var EYES = {");
  ok(at > 0, "js/eyes-store.js moved -- pin would be vacuous");
  const head = src.slice(at, src.indexOf("MAX_MARKS", at));
  ok(head.includes("UNKNOWN"), "EYES object head not found -- pin would be vacuous");
  for (const name of ["SEEN_KEY", "CHAIN_KEY"])
    ok(!new RegExp(`\\b${name}\\s*:`).test(head),
       `js/eyes-store.js: EYES.${name} had no reader and was dropped from the export 2026-09-23`);
}

// status.js published window.GBSStatus as a "test hook", but its own comment
// said nothing read it: status.test.js slices the eight functions out of the
// source. The functions stay (status.js calls every one of them).
ok(code("js/status.js").includes("const overall = "), "js/status.js moved -- pin would be vacuous");
ok(!/\bGBSStatus\b/.test(code("js/status.js")),
   "js/status.js: window.GBSStatus had no reader and was deleted 2026-09-23");

// `dark` cannot be pinned by name: sectors.js legitimately writes the string
// "dark" as the TradingView widget theme. Pin the helper's shape instead.
ok(code("js/sectors.js").includes("const SECTOR_INFO = {"), "js/sectors.js moved -- pin would be vacuous");
ok(!/(?:const|let|var)\s+dark\s*=|function\s+dark\s*\(|\bdark\s*\(\s*\)/.test(code("js/sectors.js")),
   "js/sectors.js: the unused dark() prefers-color-scheme helper was deleted 2026-09-23 " +
   "(the site is dark-only; nothing called it)");

// `$$` cannot be pinned by name: the two characters legitimately occur in
// `US$${...}` template text on the journal page. Pin the declaration instead.
ok(!/(?:const|let|var)\s+\$\$\s*=|function\s+\$\$\s*\(/.test(code("js/journal.js")),
   "js/journal.js: $$ was proven dead and deleted 2026-09-23; re-adding it needs a caller");

console.log(`hygiene: ${checks} checks passed`);
