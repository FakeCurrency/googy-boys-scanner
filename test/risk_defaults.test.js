#!/usr/bin/env node
/* The browser risk engine's defaults, pinned against the Python that owns them
   — plus the Size Calculator's instrument list, pinned against the engine that
   has to resolve it.  (TOP100 #34 / #35.)

   TWO DRIFTS, ONE FILE, and they are the same shape: a number or a name typed
   out twice, with nothing comparing the copies.

   #34 — `public/js/risk_manager.js` carries PUBLISHED_DEFAULTS, a hand-typed
   mirror of five scanner/config.py constants. It is a real fallback, not dead
   code: bot.js fetches data/bot_rules.json and only falls through to the mirror
   when that fetch fails (offline, first paint, a cached page). So the mirror is
   what the page shows exactly when nobody is in a position to notice it is
   wrong. It had already drifted once and lived that way for months — Python
   risked 0.35% over 30 positions while the JS said 0.25% over 5 — and the only
   reason anyone found out was somebody reading both files on the same day.

   #35 — the Size Calculator's instruments are a `<select>` in public/bot.html
   whose option VALUES are engine keys. A typo there is not a rendering bug: it
   surfaces as `Unknown instrument "STOCK.AXX"` in a result cell at runtime, on
   the one instrument nobody clicks, and nowhere else. #35 added three new
   option values, which is three new chances to have made exactly that mistake.

   Both halves compare the SHIPPED artefacts — the real config.py source, the
   real bot.html, the real engine loaded through require(). Nothing here is
   re-typed, because a re-typed fixture drifts in step with the bug.

   Run with: node test/risk_defaults.test.js
*/
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const RiskManager = require(path.join(ROOT, "public/js/risk_manager.js"));

// `verbose: false` or the constructor prints its whole risk state to stdout for
// every engine built, which here is once per instrument and buries the results.
// No storage stub is needed: the engine degrades to in-memory when localStorage
// is absent, and nothing in this file tests persistence.
function mk(cfg) { return new RiskManager(Object.assign({ equity: 10000, verbose: false }, cfg)); }

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓  ${name}`); passed++; }
  catch (e) {
    const loc = (e.stack || "").split("\n").slice(1).find((l) => l.includes("risk_defaults.test.js"));
    console.error(`  ✗  ${name}\n     ${e.message}${loc ? "\n     " + loc.trim() : ""}`);
    failed++;
  }
}
function suite(name) { console.log(`\n── ${name} ──`); }

// ── read the Python, without importing it ────────────────────────────────────
// A regex over config.py rather than a python subprocess: this suite runs in
// the JS job of test.yml, which has node and no guarantee of a configured
// interpreter, and shelling out would make a missing python look like a drift.
// The patterns are deliberately anchored to `^NAME` at column zero so a mention
// inside a comment or a nested dict cannot satisfy them.
const CONFIG_SRC = fs.readFileSync(path.join(ROOT, "scanner/config.py"), "utf8");

function pyNumber(name) {
  const m = CONFIG_SRC.match(new RegExp(`^${name}\\s*=\\s*(-?[0-9.]+)`, "m"));
  assert.ok(m, `scanner/config.py no longer defines a bare numeric ${name} at column 0 — ` +
    `if it moved into a dict or an expression this test must be taught the new shape, ` +
    `not deleted, because the mirror in risk_manager.js still claims to track it`);
  return Number(m[1]);
}
function pyListFirst(name) {
  const m = CONFIG_SRC.match(new RegExp(`^${name}\\s*=\\s*\\[\\s*(-?[0-9.]+)`, "m"));
  assert.ok(m, `scanner/config.py no longer defines ${name} as a bare list literal at column 0`);
  return Number(m[1]);
}

suite("PUBLISHED_DEFAULTS mirrors scanner/config.py (TOP100 #34)");

const D = RiskManager.PUBLISHED_DEFAULTS;

test("maxRiskPerTradePct === VIVEK_BOT_RISK_PCT", () => {
  assert.equal(D.maxRiskPerTradePct, pyNumber("VIVEK_BOT_RISK_PCT"));
});

test("maxConsecutiveLosses === CONSEC_LOSS_PAUSE", () => {
  assert.equal(D.maxConsecutiveLosses, pyNumber("CONSEC_LOSS_PAUSE"));
});

test("maxPortfolioRiskPct === PORTFOLIO_HEAT_LIMIT * 100", () => {
  // The unit change is the whole hazard here. Python stores a FRACTION (0.07)
  // and every JS consumer wants a PERCENT (7.0), so the mirror is the one entry
  // that is not a straight copy — which is exactly how it ended up at 2.0, a
  // number that was neither 0.07 nor 7 and had been a plausible cap once.
  assert.equal(D.maxPortfolioRiskPct, +(pyNumber("PORTFOLIO_HEAT_LIMIT") * 100).toFixed(4));
});

test("scaleOutPct === VIVEK_TP_SCALE_LONG[0]", () => {
  assert.equal(D.scaleOutPct, pyListFirst("VIVEK_TP_SCALE_LONG"));
});

test("maxPositions === VIVEK_BOT_MAX_POSITIONS", () => {
  assert.equal(D.maxPositions, pyNumber("VIVEK_BOT_MAX_POSITIONS"));
});

test("the mirror is frozen — a caller cannot rewrite everyone else's fallback", () => {
  // Not pedantry: PUBLISHED_DEFAULTS is read at CONSTRUCTION time by every
  // RiskManager built after it, so one page mutating it to "try something" would
  // silently re-default every engine made later in that session.
  assert.ok(Object.isFrozen(D));
  const before = D.maxPositions;
  try { D.maxPositions = 999; } catch (_) { /* strict mode throws; sloppy is silent */ }
  assert.equal(D.maxPositions, before);
});

test("every mirrored key is actually PUBLISHED by scanner/run.py", () => {
  // The mirror is only ever correct because a live fetch normally overrides it.
  // If run.py stops publishing one of these keys, bot.js falls through to the
  // mirror for that key on EVERY load, not just offline — the fallback becomes
  // the value, permanently and invisibly. So the publication is the thing under
  // test here, not the number.
  const RUN_SRC = fs.readFileSync(path.join(ROOT, "scanner/run.py"), "utf8");
  const published = [
    '"risk_pct": config.VIVEK_BOT_RISK_PCT',
    '"consec_loss_pause": config.CONSEC_LOSS_PAUSE',
    '"portfolio_heat_limit_pct": round(config.PORTFOLIO_HEAT_LIMIT * 100',
    '"max_positions": config.VIVEK_BOT_MAX_POSITIONS',
    '"tp_scale"',
  ];
  for (const frag of published) {
    assert.ok(RUN_SRC.includes(frag),
      `scanner/run.py no longer publishes ${frag} into bot_rules.json — the JS mirror ` +
      `would become the permanent value for that rule instead of an offline fallback`);
  }
});

// ── the Size Calculator's instrument list ────────────────────────────────────
suite("every #sz-instrument option resolves through the engine (TOP100 #35)");

const BOT_HTML = fs.readFileSync(path.join(ROOT, "public/bot.html"), "utf8");

// Slice the ONE select, not every <option> on the page — bot.html has other
// dropdowns and matching them all would make this suite fail for reasons that
// have nothing to do with instruments.
function sizeCalcOptionValues() {
  const start = BOT_HTML.indexOf('id="sz-instrument"');
  assert.ok(start > -1, "public/bot.html has no #sz-instrument select — the Size Calculator " +
    "was renamed or removed, and this suite is now testing nothing");
  const end = BOT_HTML.indexOf("</select>", start);
  assert.ok(end > start, "#sz-instrument select is unterminated in public/bot.html");
  const block = BOT_HTML.slice(start, end);
  const out = [];
  const re = /<option\s+value="([^"]*)"/g;
  let m;
  while ((m = re.exec(block)) !== null) out.push(m[1]);
  return out;
}

const OPTION_VALUES = sizeCalcOptionValues();

test("the select is not empty (a passing loop over zero options proves nothing)", () => {
  assert.ok(OPTION_VALUES.length >= 9,
    `expected at least the 3 traded + 6 futures rows, found ${OPTION_VALUES.length}`);
});

test("no duplicate option values", () => {
  const seen = new Set();
  for (const v of OPTION_VALUES) {
    assert.ok(!seen.has(v), `#sz-instrument lists "${v}" twice — the second is unreachable`);
    seen.add(v);
  }
});

for (const value of OPTION_VALUES) {
  test(`"${value}" resolves to an instrument spec`, () => {
    // Through getInstrumentSpec, NOT a direct DEFAULT_INSTRUMENTS lookup: the
    // real calculator goes exact -> uppercased -> ALIASES, so an option keyed on
    // an alias is legitimate and a direct-table assertion would reject it.
    const spec = mk().getInstrumentSpec(value);
    assert.ok(spec, `#sz-instrument offers "${value}" and the engine answers ` +
      `Unknown instrument "${value}" — the calculator shows an error string in the ` +
      `result cell for anyone who picks that row`);
    assert.ok(spec.dollarsPerPoint > 0, `"${value}" resolves but has no usable dollarsPerPoint`);
  });
}

test("the three instruments this system ACTUALLY trades are all offered", () => {
  // The point of #35. The table shipped six futures contracts and none of the
  // three asset classes the scanner has ever sent an order for, so the
  // calculator was fluent about trades that will never happen and returned an
  // error for the ones that do. A future edit tidying the list must not quietly
  // take these back out.
  for (const key of ["STOCK", "STOCK.AX", "CRYPTO"]) {
    assert.ok(OPTION_VALUES.includes(key),
      `#sz-instrument no longer offers ${key} — the calculator cannot size the ` +
      `instruments the bot books positions in`);
  }
});

test("the traded rows carry a unitStep; the futures rows deliberately do not", () => {
  // bot.js discriminates cash-vs-futures on `r.unitStep != null` rather than on
  // a symbol list of its own, so this property IS the display contract. Break it
  // and an equity silently starts sizing in 0.1-share lots again with no error
  // anywhere — the original #35 defect, restored.
  const eng = mk();
  for (const key of ["STOCK", "STOCK.AX", "CRYPTO"]) {
    const s = eng.getInstrumentSpec(key);
    assert.ok(s.unitStep > 0, `${key} must carry a unitStep — bot.js reads its presence as ` +
      `"this is cash, print whole units and a currency stop label"`);
    assert.ok(s.unitLabel, `${key} must carry a unitLabel — it is printed beside the size`);
  }
  assert.equal(eng.getInstrumentSpec("/NQ").unitStep, undefined,
    "/NQ must keep NO unitStep — its absence is what routes futures down the legacy " +
    "0.1-lot rounding path that 50+ tests in risk_manager.test.js still assert");
});


// ── bot.js DEFAULT_RULES — the THIRD copy, found unpinned and drifted ────────
// This suite was written for risk_manager.js's PUBLISHED_DEFAULTS (TOP100 #34)
// on the argument that "the mirror is what the page shows exactly when the
// person reading it is least able to verify it". public/js/bot.js carries a
// SECOND mirror of the same four numbers, and nothing read it: it shipped
// risk 0.25% / 5 positions / min_rr 2 against an engine at 0.35 / 30 / 1.5.
//
// `rulesDefaults()` overlays the server values only when the bot_rules.json
// fetch SUCCEEDS. `loadRules()` spreads DEFAULT_RULES unconditionally and is
// what seeds RULES on every load — so the drift was live on precisely the
// offline / first-paint / cached path the original finding was about.
suite("bot.js DEFAULT_RULES mirrors the engine");

const BOT_SRC = fs.readFileSync(path.join(ROOT, "public/js/bot.js"), "utf8");
function botDefault(key) {
  const block = BOT_SRC.slice(BOT_SRC.indexOf("const DEFAULT_RULES = {"));
  const m = new RegExp(`\\b${key}\\s*:\\s*(-?[0-9.]+)`).exec(block.slice(0, block.indexOf("};")));
  assert.ok(m, `bot.js DEFAULT_RULES no longer declares ${key}`);
  return Number(m[1]);
}

test("risk_pct matches VIVEK_BOT_RISK_PCT", () => {
  assert.equal(botDefault("risk_pct"), pyNumber("VIVEK_BOT_RISK_PCT"));
});

test("max_positions matches VIVEK_BOT_MAX_POSITIONS", () => {
  // 5 vs 30 was the loudest of the three: the page's whole capacity story.
  assert.equal(botDefault("max_positions"), pyNumber("VIVEK_BOT_MAX_POSITIONS"));
});

test("loss_limit matches CONSEC_LOSS_PAUSE", () => {
  assert.equal(botDefault("loss_limit"), pyNumber("CONSEC_LOSS_PAUSE"));
});

test("min_rr matches what the scan actually publishes", () => {
  // The one number with no config.py twin — it reaches the page through
  // bot_rules.json, so the committed artefact is the source of truth.
  const rules = JSON.parse(fs.readFileSync(path.join(ROOT, "public/data/bot_rules.json"), "utf8"));
  assert.equal(typeof rules.min_rr, "number", "bot_rules.json stopped publishing min_rr");
  assert.equal(botDefault("min_rr"), rules.min_rr);
});

test("and bot.js still OVERLAYS the server values when the fetch works", () => {
  // The mirror is the fallback, not the source. If rulesDefaults stopped
  // overlaying, a correct mirror today would silently become the value forever.
  assert.ok(/const rulesDefaults = \(\) => \{[\s\S]{0,200}srvValue\(k\)/.test(BOT_SRC),
    "rulesDefaults no longer overlays the published rules over DEFAULT_RULES");
  assert.ok(/SRV_KEYS = \["risk_pct", "max_positions", "min_rr", "loss_limit"\]/.test(BOT_SRC),
    "the four overlaid keys changed — check they still match the four pinned above");
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
