/* HTML-escaping contract for every shipped front-end module (TOP100 #75-#77).
 *
 * There is no build step and no module system on this site, so `esc` is not
 * imported from anywhere — it is hand-copied into each IIFE. Ten copies had
 * already drifted into THREE different character classes:
 *
 *     sectors.js            [&<>]        <- the real hole
 *     horizon.js regime.js  [&<>"]
 *     the other seven       [&<>"']
 *
 * and sectors.js interpolated straight into a double-quoted attribute
 * (`data-countdown="${esc(ev.when)}"`), so a `"` in that value closed the
 * attribute and everything after it was parsed as markup.
 *
 * The obvious fix — one shared `public/js/esc.js` — is the wrong one HERE. With
 * no bundler, every page would gain a script-load-order dependency, and one
 * HTML file missing the tag is not a subtle bug: that page dies on the first
 * `esc` call. So the copies stay copies, and this suite is what keeps them
 * honest. It reads the SHIPPED files (not a mirror of them), pulls each `esc`
 * out by source text, evaluates it, and tests the BEHAVIOUR rather than
 * matching the regex literal — a copy that spells the class differently but
 * escapes the same five characters passes, and one that quietly drops a
 * character fails no matter how it is written.
 */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");

const JS_DIR = path.join(__dirname, "..", "public", "js");
const files = fs.readdirSync(JS_DIR).filter((f) => f.endsWith(".js")).sort();
assert.ok(files.length >= 10, `expected the shipped public/js modules, found ${files.length}`);

let checks = 0;
const ok = (cond, msg) => { assert.ok(cond, msg); checks++; };
const eq = (a, b, msg) => { assert.strictEqual(a, b, msg); checks++; };

// ---------------------------------------------------------------------------
// Pull `const <name> = <expr>;` out of a file.
//
// Deliberately NOT a hand-rolled brace balancer: the very thing being extracted
// is `/[&<>"']/g`, a regex literal holding both quote characters, and a scanner
// that treats `"` as a string delimiter desyncs on it immediately (the first
// attempt at this did). Instead, walk the candidate `;` terminators and let the
// JS parser itself say which one closes the expression — the short candidates
// are unbalanced and throw, so the first that parses is the definition.
// ---------------------------------------------------------------------------
function extractConst(src, name) {
  const at = src.search(new RegExp(`\\bconst\\s+${name}\\s*=`));
  if (at < 0) return null;
  const start = src.indexOf("=", at) + 1;
  for (let i = src.indexOf(";", start); i > 0 && i - start < 4000; i = src.indexOf(";", i + 1)) {
    const candidate = src.slice(start, i).trim();
    try {
      new Function(`return (${candidate});`); // parse-only
      return candidate;
    } catch (_) { /* unbalanced — keep walking */ }
  }
  return null;
}

// The five characters that can break out of text or a quoted attribute, and
// what each must become. `'` matters because a value can land in a
// single-quoted attribute; `"` matters because most of this codebase's
// attributes are double-quoted.
const MUST_ESCAPE = [
  ["&", "&amp;"],
  ["<", "&lt;"],
  [">", "&gt;"],
  ['"', "&quot;"],
  ["'", "&#39;"],
];

// ---------------------------------------------------------------------------
// 1. Every module that defines `esc` escapes all five, and is null-safe.
// ---------------------------------------------------------------------------
const definers = [];
for (const f of files) {
  const src = fs.readFileSync(path.join(JS_DIR, f), "utf8");
  const expr = extractConst(src, "esc");
  if (!expr) continue;
  // `const esc = PM.esc;` (mynames.js) is an alias, not a definition — the
  // real one is tested when phasemap-shared.js comes round, and section 2
  // below is what proves the alias resolves.
  if (/^[\w$]+(\.[\w$]+)*$/.test(expr)) continue;
  definers.push(f);

  let esc;
  try {
    esc = eval(`(${expr})`); // eslint-disable-line no-eval
  } catch (e) {
    assert.fail(`${f}: could not evaluate its esc definition — ${e.message}\n${expr}`);
  }
  ok(typeof esc === "function", `${f}: esc is not a function`);

  for (const [raw, want] of MUST_ESCAPE) {
    eq(esc(raw), want, `${f}: esc(${JSON.stringify(raw)}) must be ${want}`);
  }

  // The whole set at once, so a copy that escapes each character in isolation
  // but mangles them together (a bad replacer, a missing /g) still fails.
  eq(esc(`&<>"'`), "&amp;&lt;&gt;&quot;&#39;", `${f}: esc must handle all five together`);

  // Repeats: a missing /g flag escapes only the first occurrence.
  eq(esc("<<"), "&lt;&lt;", `${f}: esc must be global`);

  // The classic payload, in the two contexts this codebase actually builds.
  ok(!esc(`" onmouseover="alert(1)`).includes(`"`),
    `${f}: esc leaves a double quote that breaks out of a quoted attribute`);
  ok(!esc(`<img src=x onerror=alert(1)>`).match(/[<>]/),
    `${f}: esc leaves angle brackets that open a tag`);

  // Null-safety. Nine copies guarded; phasemap-shared.js was `String(s)`, so
  // `esc(null)` rendered the literal word "null" into the page — which is why
  // several of ITS call sites carry a defensive `|| ""`.
  eq(esc(null), "", `${f}: esc(null) must be empty, not the word "null"`);
  eq(esc(undefined), "", `${f}: esc(undefined) must be empty`);

  // Non-strings still come back as strings — attributes get numbers and
  // booleans too (data-long, the chip counts).
  eq(esc(0), "0", `${f}: esc(0) must be "0", not ""`);
  eq(esc(false), "false", `${f}: esc(false) must stringify`);
  eq(esc(12.5), "12.5", `${f}: esc(number) must stringify`);
}
ok(definers.length >= 10, `expected >=10 esc definitions, found ${definers.length}`);

// ---------------------------------------------------------------------------
// 2. Nobody calls `esc` without having one. A file that uses `esc(` must either
//    define it or take `PM.esc` off the shared PhaseMap object — otherwise it
//    throws a ReferenceError the first time it renders.
// ---------------------------------------------------------------------------
for (const f of files) {
  const src = fs.readFileSync(path.join(JS_DIR, f), "utf8");
  if (!/\besc\(/.test(src)) continue;
  const defines = definers.includes(f);
  const borrows = /\bconst\s+esc\s*=\s*PM\.esc\b/.test(src) || /\bPM\.esc\(/.test(src);
  ok(defines || borrows, `${f}: calls esc() but neither defines it nor uses PM.esc`);
}

// PM.esc has to actually be exported, since three modules depend on it.
{
  const shared = fs.readFileSync(path.join(JS_DIR, "phasemap-shared.js"), "utf8");
  ok(/return\s*\{[^}]*\besc\b/.test(shared),
    "phasemap-shared.js must export esc on the PM object");
}

// ---------------------------------------------------------------------------
// 3. #75 regression pin, named so the failure says what it is: the sectors
//    countdown attribute is the site that was exploitable.
// ---------------------------------------------------------------------------
{
  const src = fs.readFileSync(path.join(JS_DIR, "sectors.js"), "utf8");
  const esc = eval(`(${extractConst(src, "esc")})`); // eslint-disable-line no-eval
  const line = (src.match(/^.*data-countdown="\$\{[^\n]*$/m) || [])[0];
  ok(line, "sectors.js no longer has the data-countdown attribute this pins");
  ok(/data-countdown="\$\{esc\(/.test(line),
    "sectors.js must escape the value it puts in data-countdown");
  eq(esc(`x" onload="alert(1)`), "x&quot; onload=&quot;alert(1)",
    "sectors.js esc must neutralise an attribute break-out (TOP100 #75)");
}

// ---------------------------------------------------------------------------
// 4. `numAttr` — the OTHER half. A number bound for an attribute that is read
//    back with `+` must not go through `esc`: esc renders a missing value as
//    "", and `+""` is 0 — a silent, plausible zero in a position-size
//    calculation. numAttr emits digits (attribute-safe by construction) or
//    empty, and app.js's numAttrOf turns empty back into NaN.
// ---------------------------------------------------------------------------
for (const f of ["app.js", "journal.js"]) {
  const src = fs.readFileSync(path.join(JS_DIR, f), "utf8");
  const expr = extractConst(src, "numAttr");
  ok(expr, `${f}: numAttr is missing`);
  const numAttr = eval(`(${expr})`); // eslint-disable-line no-eval

  eq(numAttr(12.5), "12.5", `${f}: numAttr passes a finite number through`);
  eq(numAttr(0), "0", `${f}: numAttr must keep a real zero`);
  eq(numAttr(-3), "-3", `${f}: numAttr keeps the sign`);
  eq(numAttr(null), "", `${f}: numAttr(null) is empty`);
  eq(numAttr(undefined), "", `${f}: numAttr(undefined) is empty`);
  eq(numAttr(NaN), "", `${f}: numAttr(NaN) is empty`);
  eq(numAttr(Infinity), "", `${f}: numAttr(Infinity) is empty`);

  // The point of the whole helper: nothing it emits can escape an attribute,
  // for ANY input — including a string carrying a payload.
  for (const hostile of [`1" onload="alert(1)`, `<img>`, `'`, `&`, "1e3", "abc"]) {
    ok(!/["'<>&]/.test(numAttr(hostile)),
      `${f}: numAttr(${JSON.stringify(hostile)}) leaked an attribute-breaking character`);
  }
}

// The round trip: absent must survive as NaN, not arrive as 0.
{
  const src = fs.readFileSync(path.join(JS_DIR, "app.js"), "utf8");
  const numAttr = eval(`(${extractConst(src, "numAttr")})`);   // eslint-disable-line no-eval
  const numAttrOf = eval(`(${extractConst(src, "numAttrOf")})`); // eslint-disable-line no-eval

  eq(numAttrOf(numAttr(42)), 42, "numAttr -> numAttrOf round-trips a number");
  eq(numAttrOf(numAttr(0)), 0, "a real zero round-trips as zero");
  ok(Number.isNaN(numAttrOf(numAttr(null))), "a missing number must read back NaN, not 0");
  ok(Number.isNaN(numAttrOf(numAttr(undefined))), "undefined must read back NaN, not 0");
  ok(Number.isNaN(numAttrOf("")), "an empty attribute must read back NaN, not 0");
  ok(Number.isNaN(numAttrOf(null)), "an absent attribute must read back NaN, not 0");

  // And the guard that consumes it still rejects the missing case: the size
  // box only prints when dist > 0, and NaN > 0 is false.
  const dist = Math.abs(numAttrOf(numAttr(null)) - numAttrOf(numAttr(10)));
  ok(!(dist > 0), "a missing entry must not produce a printable stop distance");
}

console.log(`escaping.test.js: ${checks} assertions across ${definers.length} esc definitions OK`);
