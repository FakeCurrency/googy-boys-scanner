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
    dead: ["inBatches", "fav", "nowTime", "tradeKey", "priceFor", "cryptoPrice", "stockPrice", "fetchJSON", "YF_TICKER"],
  },
  "js/app.js": {
    live: "function isHighConviction(",
    dead: ["fmtTurn", "VIEW_KEYS"],
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

ok(!/\bisLong\b/.test(fnBody(code("js/journal.js"), "openRows")),
   "js/journal.js openRows: the unused `isLong` row local was deleted 2026-09-23 (liveCells " +
   "derives direction itself)");

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
