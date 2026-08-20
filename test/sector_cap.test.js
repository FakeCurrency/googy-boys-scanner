#!/usr/bin/env node
/* Sector-cap marking on the deck (2026-08-20, Task 10).
 *
 * bot_rules publishes max_per_sector (3) and decide() blocks an entry once a
 * market's open book holds that many of a sector — likely the most common
 * reason a specific A+ cannot be taken, previously invisible on the hunt
 * screen. These tests slice the REAL sectorKeyOf / sectorCapChip out of the
 * shipped app.js.
 *
 * PARITY NOTE: sectorKeyOf must mirror scanner/broker/vivek_bot.py's
 * _sector_key (lower-cased real sector wins; crypto falls back to synthetic
 * major/alt buckets; sector-less rows return "" and are EXEMPT). The case
 * table below IS that contract — if _sector_key ever changes, this table and
 * the mirror must move together (the bot file is ringfenced, so in practice
 * the mirror follows it, never the reverse).
 */
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(path.resolve(__dirname, "../public/js/app.js"), "utf8");
const CSS = fs.readFileSync(path.resolve(__dirname, "../public/css/styles.css"), "utf8");
const RUNPY = fs.readFileSync(path.resolve(__dirname, "../scanner/run.py"), "utf8");
const BOTPY = fs.readFileSync(path.resolve(__dirname, "../scanner/broker/vivek_bot.py"), "utf8");

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓  ${name}`); passed++; }
  catch (e) { console.error(`  ✗  ${name}\n     ${e.message}`); failed++; }
}

function slice(startMarker, endMarker) {
  const a = SRC.indexOf(startMarker);
  assert.ok(a >= 0, `app.js no longer contains "${startMarker}"`);
  const b = SRC.indexOf(endMarker, a);
  assert.ok(b > a, `could not find the end of "${startMarker}"`);
  return SRC.slice(a, b + endMarker.length);
}

// state is a sandbox `let` the tests mutate per case.
const ctx = vm.createContext({ console });
vm.runInContext(
  "const esc = (s) => String(s);\n"
  + "let state = { market: 'asx', sectorCap: 0, sectorLoad: null, heldSyms: null, cryptoMajors: new Set() };\n"
  + slice("const sectorKeyOf = (symbol, sector, market, majors)", "\n  };") + "\n"
  + slice("function sectorCapChip(r) {", "\n  }") + "\n"
  + slice("const sectorCapped = (r)", ";\n") + "\n"
  + "this.sectorKeyOf = sectorKeyOf; this.sectorCapChip = sectorCapChip;\n"
  + "this.sectorCapped = sectorCapped;\n"
  + "this.setState = (s) => { state = s; };\n", ctx);
const { sectorKeyOf, sectorCapChip, sectorCapped, setState } = ctx;

console.log("\n── sectorKeyOf mirrors _sector_key ──");

test("a real sector wins, lower-cased and trimmed — every market", () => {
  assert.equal(sectorKeyOf("BHP", " Materials ", "asx", new Set()), "materials");
  assert.equal(sectorKeyOf("AAPL", "Technology", "nasdaq", new Set()), "technology");
  assert.equal(sectorKeyOf("BTC", "DeFi", "crypto", new Set(["BTC"])), "defi",
    "even crypto: a stored sector beats the synthetic bucket, matching _sector_key");
});

test("crypto with no sector buckets to major/alt off the published majors", () => {
  const majors = new Set(["BTC", "ETH"]);
  assert.equal(sectorKeyOf("BTC", "", "crypto", majors), "crypto-major");
  assert.equal(sectorKeyOf("eth", null, "crypto", majors), "crypto-major", "case-folded like the bot");
  assert.equal(sectorKeyOf("DOGE", "", "crypto", majors), "crypto-alt");
});

test("a sector-less stock row is EXEMPT — empty key, never a bucket", () => {
  assert.equal(sectorKeyOf("XYZ", "", "nasdaq", new Set()), "");
  assert.equal(sectorKeyOf("XYZ", null, "asx", new Set()), "");
});

test("the python _sector_key still has the shape this mirrors", () => {
  // Cheap drift tripwire on the ringfenced original: the three branches the
  // mirror reproduces must still exist in vivek_bot.py.
  assert.ok(/def _sector_key\(/.test(BOTPY));
  assert.ok(BOTPY.includes('"crypto-major" if'), "majors branch moved");
  assert.ok(BOTPY.includes("crypto-alt"), "alt branch moved");
  assert.ok(/s = str\(sector or ""\)\.strip\(\)\.lower\(\)/.test(BOTPY), "sector normalisation moved");
});

console.log("\n── sectorCapChip — when the row is marked ──");

const AT_CAP = () => ({
  market: "asx", sectorCap: 3, cryptoMajors: new Set(["BTC", "ETH"]),
  sectorLoad: { asx: { materials: 3, financials: 1 }, crypto: { "crypto-alt": 3 } },
  heldSyms: { asx: new Set(["HELDCO"]) },
});

test("a row in an at-cap sector gets the chip with count and cap", () => {
  setState(AT_CAP());
  const h = sectorCapChip({ symbol: "BHP", sector: "Materials" });
  assert.ok(h.includes("SECTOR 3/3"), h);
  assert.ok(h.includes("sector_cap"), "the tip names the bot's own skip code");
  assert.equal(sectorCapped({ symbol: "BHP", sector: "Materials" }), true);
});

test("below the cap, no chip", () => {
  setState(AT_CAP());
  assert.equal(sectorCapChip({ symbol: "CBA", sector: "Financials" }), "");
});

test("a HELD row is never marked — it IS one of the counted positions", () => {
  setState(AT_CAP());
  assert.equal(sectorCapChip({ symbol: "HELDCO", sector: "Materials" }), "");
});

test("sector-less rows are exempt exactly like the bot exempts them", () => {
  setState(AT_CAP());
  assert.equal(sectorCapChip({ symbol: "NOSEC", sector: "" }), "");
});

test("crypto alt-bucket at cap marks an alt and spares a major", () => {
  const s = AT_CAP(); s.market = "crypto"; setState(s);
  assert.ok(sectorCapChip({ symbol: "DOGE", sector: "" }).includes("SECTOR 3/3"));
  assert.equal(sectorCapChip({ symbol: "BTC", sector: "" }), "");
});

test("no rules loaded (cap 0) degrades to NO marking, never a wrong one", () => {
  const s = AT_CAP(); s.sectorCap = 0; setState(s);
  assert.equal(sectorCapChip({ symbol: "BHP", sector: "Materials" }), "");
});

console.log("\n── wiring ──");

test("the row template renders the chip and the gentle dim class", () => {
  assert.ok(SRC.includes("${heldChip(r)}${sectorCapChip(r)}"), "chip must ride beside HELD");
  assert.ok(/const capCls = sectorCapped\(r\) \? " row-capdim" : ""/.test(SRC));
  assert.ok(SRC.includes('class="row-wrap${dimCls}${capCls}"'));
});

test("loadBotActivity builds the load from the book with the rules' majors and cap", () => {
  assert.ok(SRC.includes("rules.crypto_majors"), "majors come from the published rules");
  assert.ok(SRC.includes("rules.max_per_sector"));
  assert.ok(/state\.sectorLoad = load/.test(SRC));
});

test("both CSS classes exist and the dim is its own class, not row-dim", () => {
  assert.ok(/\.row-secfull\s*\{/.test(CSS), ".row-secfull missing");
  assert.ok(/\.row-capdim\s*\{/.test(CSS), ".row-capdim missing");
});

test("run.py publishes crypto_majors from config — the deck never re-types the list", () => {
  assert.ok(RUNPY.includes('"crypto_majors": list(config.VIVEK_BOT_CRYPTO_MAJORS)'));
});

console.log("\n── held-grade honesty (batch-100 WS-G) ──");

test("a hysteresis-held grade carries the ring, an earned grade does not", () => {
  const m = SRC.match(/\$\{r\.grade_raw && r\.grade !== r\.grade_raw \? `([^`]*)` : ""\}/);
  assert.ok(m, "the row-grade cell must gate the ring on grade !== grade_raw");
  assert.ok(m[1].includes("rg-held"));
});

test("the ring's tooltip says who buys what and embeds no live number", () => {
  const at = SRC.indexOf("rg-held");
  const tip = SRC.slice(at, at + 300);
  assert.ok(/HELD by hysteresis/.test(tip), "must name the mechanism");
  assert.ok(/bot buys grade_raw/.test(tip), "must say the bot ignores the badge");
  assert.ok(!/\b\d{2,} (ASX|NASDAQ|rows)/.test(tip), "no live counts in a static tooltip");
});

test("the ring has a CSS rule and stays quiet (no animation, no colour claim)", () => {
  const rule = CSS.match(/\.rg-held\s*\{[^}]*\}/);
  assert.ok(rule, ".rg-held has no rule in styles.css");
  assert.ok(!/animation|color\s*:/.test(rule[0]), "the softest possible correction - keep it that way");
});

console.log(`\nsector_cap.test.js: ${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
