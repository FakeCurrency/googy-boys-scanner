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

console.log(`hygiene: ${checks} checks passed`);
