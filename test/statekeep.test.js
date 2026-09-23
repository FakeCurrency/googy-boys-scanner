/* Front-end state that was being thrown away, recomputed, or read at the
 * wrong moment (TOP100 #84–#88). ONE of the five items still has code to pin.
 *
 *   #86  `ensureActiveVisible()` read `scrollWidth` / `getBoundingClientRect()`
 *        synchronously from inside render, forcing a layout mid-render, twice
 *        per click. Now deferred to a frame and coalesced. Pinned below.
 *
 * The other four left with the code they guarded, so nothing here tests them:
 *   #84  the close-modal row memo (`updateClosePreview`) -- the modal went with
 *        the manual journal, 2026-09-21
 *   #85  risk_manager.js -- removed with the AI BOT page, 2026-09-17
 *   #87  bot.js -- removed with the AI BOT page, 2026-09-17
 *   #88  horizon.js + regime.js renderer-fault scoping -- removed with the
 *        HORIZON / REGIME surfaces, 2026-09-20
 *
 * Everything below is sliced out of the SHIPPED file and executed. Nothing is
 * re-typed into a fixture: a fixture drifts in step with the bug it is meant to
 * catch, and the broken and fixed versions of #86 look almost identical to a
 * `grep`-shaped test.
 */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");

const P = (f) => path.join(__dirname, "..", "public", "js", f);

// Same comment-stripper as test/leaks.test.js, and for the same reason: the
// mutation a human actually makes is to comment a line OUT, which leaves the
// text in the file for any regex to match. Line-oriented, so it drops lines
// that are ENTIRELY a comment and leaves trailing `// ...` alone — no
// expression is ever truncated mid-line.
const codeOnly = (src) =>
  src.split("\n").filter((l) => {
    const t = l.trim();
    return !(t.startsWith("//") || t.startsWith("/*") || t.startsWith("*"));
  }).join("\n");

const APP_SRC = codeOnly(fs.readFileSync(P("app.js"), "utf8"));

// ---------------------------------------------------------------------------
// Slicers. Both walk candidate terminators and let the JS PARSER say which one
// closes the construct, rather than counting braces by hand — a hand-rolled
// balancer desyncs on the first regex literal or brace-in-a-string it meets,
// and both of those exist in these files.
// ---------------------------------------------------------------------------
function extractConst(src, name) {
  const at = src.search(new RegExp(`\\bconst\\s+${name}\\s*=`));
  if (at < 0) return null;
  const start = src.indexOf("=", at) + 1;
  for (let i = src.indexOf(";", start); i > 0 && i - start < 4000; i = src.indexOf(";", i + 1)) {
    const candidate = src.slice(start, i).trim();
    try { new Function(`return (${candidate});`); return candidate; } catch (_) { /* keep walking */ }
  }
  return null;
}
function pullFrom(src, name, label) {
  const expr = extractConst(src, name);
  assert.ok(expr, `${label} no longer defines ${name}`);
  return expr;
}
// A whole function DECLARATION, source and all, so the sandbox runs the shipped
// bytes. Wrapping the slice in parens turns the declaration into an expression,
// which is a parse error unless the slice is exactly balanced — that is the
// whole test for "did I cut in the right place".
function fnSrc(src, name, label) {
  const at = src.search(new RegExp(`\\bfunction\\s+${name}\\s*\\(`));
  assert.ok(at >= 0, `${label} no longer declares function ${name}()`);
  for (let i = src.indexOf("}", at); i > 0 && i - at < 12000; i = src.indexOf("}", i + 1)) {
    const cand = src.slice(at, i + 1);
    try { new Function(`return (${cand});`); return cand; } catch (_) { /* keep walking */ }
  }
  assert.fail(`${label}: could not slice ${name}() — has its brace shape changed?`);
}
// A single declaration line, matched verbatim. Deliberately exact: these are
// the lines that hold the state under test, and a change to one of them is
// something a reader of this suite should be made to look at.
function declSrc(src, re, label) {
  const m = src.match(re);
  assert.ok(m, `${label}: could not find the declaration ${re}`);
  return m[0];
}

// The sandbox is `new Function`, not `vm`. Same realm, so an object built
// inside compares normally against one built out here — a vm context is a
// separate realm whose Array.prototype is a different object, and every
// deepStrictEqual across that boundary fails for a reason that has nothing to
// do with the code under test. Top-level `var`/`function`/`let` in a Function
// body are scoped to that body, so nothing leaks either way.
function build(label, parts, expose) {
  const body = parts.join("\n\n") + "\n\n" + expose;
  try { return new Function(body)(); }
  catch (e) { assert.fail(`${label}: sandbox failed to build — ${e.message}`); }
}

let passed = 0;
const test = (name, fn) => {
  try { fn(); passed++; console.log("PASS  " + name); }
  catch (e) { console.error("FAIL  " + name + "\n      " + e.message); process.exitCode = 1; }
};
const suite = (n) => console.log(`\n── ${n} ──`);

// (#84 — the close-modal row memo — went with the modal itself on 2026-09-21
//  when the manual journal was removed. No modal, no memo, nothing to pin.)

// ===========================================================================
suite("#86 · app.js — the layout read is deferred and coalesced");
// ===========================================================================
function mkVisSandbox() {
  return build("app.js #86", [
    "var frames = [];",
    "var scrolls = 0;",
    "function requestAnimationFrame(cb) { frames.push(cb); return frames.length; }",
    "function _scrollActiveIntoStrip() { scrolls++; }",
    declSrc(APP_SRC, /let _visRaf = 0;/, "app.js"),
    fnSrc(APP_SRC, "ensureActiveVisible", "app.js"),
  ], `return {
    ensureActiveVisible: ensureActiveVisible,
    pending: function () { return frames.length; },
    scrolls: function () { return scrolls; },
    frame: function () { var q = frames; frames = []; q.forEach(function (cb) { cb(); }); },
  };`);
}

test("five calls in one frame schedule ONE rAF and force ZERO layouts", () => {
  const s = mkVisSandbox();
  for (let i = 0; i < 5; i++) s.ensureActiveVisible();
  assert.strictEqual(s.pending(), 1, `${s.pending()} frames queued for one burst — the coalescing is gone`);
  assert.strictEqual(s.scrolls(), 0, "the layout read happened synchronously, which is the whole bug");
});

test("the frame does the work once, and releases the guard for the next burst", () => {
  const s = mkVisSandbox();
  s.ensureActiveVisible();
  s.ensureActiveVisible();
  s.frame();
  assert.strictEqual(s.scrolls(), 1, "a coalesced pair must produce exactly one scroll");
  s.ensureActiveVisible();
  assert.strictEqual(s.pending(), 1, "the guard was never released — every later call is now a no-op");
  s.frame();
  assert.strictEqual(s.scrolls(), 2);
});

test("ensureActiveVisible itself performs no layout read", () => {
  const body = fnSrc(APP_SRC, "ensureActiveVisible", "app.js");
  [/getBoundingClientRect/, /scrollWidth/, /clientWidth/, /scrollBy/, /querySelector/].forEach((re) => {
    assert.ok(!re.test(body),
      `ensureActiveVisible still touches ${re.source} — that read belongs after the frame, not inside render`);
  });
});

test("nothing bypasses the coalescing — _scrollActiveIntoStrip has exactly one caller", () => {
  const hits = APP_SRC.split("_scrollActiveIntoStrip").length - 1;
  assert.strictEqual(hits, 2,
    `_scrollActiveIntoStrip appears ${hits}x in app.js; expected exactly 2 (its declaration and the rAF callback). ` +
    "A third mention is a caller that skipped the frame.");
});

test("the render path still calls the deferred entry point, not the reader", () => {
  const callers = APP_SRC.split("ensureActiveVisible").length - 1;
  assert.ok(callers >= 3,
    `ensureActiveVisible has ${callers - 1} call sites left; the render path stopped calling it`);
});

// (#88 — horizon.js + regime.js renderer-fault suite — left with the surfaces, 2026-09-20)

// ---------------------------------------------------------------------------
console.log(process.exitCode
  ? "\nSOME STATEKEEP TESTS FAILED"
  : `\nALL ${passed} statekeep tests passed`);
