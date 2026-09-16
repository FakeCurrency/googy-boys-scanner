/* Five pieces of front-end state that were being thrown away, recomputed, or
 * read at the wrong moment (TOP100 #84–#88).
 *
 * They look like five unrelated files. They are one failure shape: something
 * that should have been HELD was not, or something that was held went STALE,
 * and in every case the page carried on drawing a plausible number.
 *
 *   #84  `updateClosePreview` runs on every `input` event in the exit-price
 *        field and did a full localStorage read + JSON.parse + normalize() of
 *        the whole journal, per character, to find one row. Typing "1234.56"
 *        did it seven times. The memo is keyed on a GENERATION counter, not on
 *        the id alone, because a sync pull or a cross-tab write landing while
 *        the modal is open must invalidate it — a stale preview is a worse bug
 *        than a slow one.
 *
 *   #85  (risk_manager.js — removed with the AI BOT page, 2026-09-17)
 *
 *   #86  `ensureActiveVisible()` read `scrollWidth` / `getBoundingClientRect()`
 *        synchronously from inside render, forcing a layout mid-render, twice
 *        per click. Now deferred to a frame and coalesced.
 *
 *   #87  (bot.js — removed with the AI BOT page, 2026-09-17)
 *
 *   #88  The `.catch()` sat AFTER `.then(mount)`, so a renderer that threw was
 *        handled by the branch whose job is "the JSON isn't there yet" — and
 *        since mount draws the panel first, a strip that threw on one bad row
 *        hid a panel that had rendered perfectly.
 *
 * Everything below is sliced out of the SHIPPED files and executed. Nothing is
 * re-typed into a fixture: a fixture drifts in step with the bug it is meant to
 * catch, and four of these five items are invisible to a `grep`-shaped test
 * because the broken version and the fixed version look almost identical.
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

const JOURNAL_SRC = codeOnly(fs.readFileSync(P("journal.js"), "utf8"));
const APP_SRC = codeOnly(fs.readFileSync(P("app.js"), "utf8"));
const HORIZON_SRC = codeOnly(fs.readFileSync(P("horizon.js"), "utf8"));
const REGIME_SRC = codeOnly(fs.readFileSync(P("regime.js"), "utf8"));

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

// ===========================================================================
suite("#84 · journal.js — the close-modal row memo");
// ===========================================================================
function mkCloseSandbox() {
  return build("journal.js #84", [
    "var closeId = null;",
    "var mjGen = 0;",
    "var TRADES = [];",
    "var reads = 0;",
    // Stands in for the real mjLoad: a localStorage read + JSON.parse +
    // normalize(). It returns a FRESH wrapper each time, as the real one does,
    // so a test that passes cannot be passing because the object was reused.
    "function mjLoad() { reads++; return { trades: TRADES }; }",
    declSrc(JOURNAL_SRC, /let closeRow = null, closeRowGen = -1;/, "journal.js"),
    fnSrc(JOURNAL_SRC, "closeRowNow", "journal.js"),
  ], `return {
    closeRowNow: closeRowNow,
    reads: function () { return reads; },
    setId: function (id) { closeId = id; },
    setTrades: function (t) { TRADES = t; },
    bumpGen: function () { mjGen++; },
    clear: function () { closeId = null; closeRow = null; closeRowGen = -1; },
    peek: function () { return { row: closeRow, gen: closeRowGen, mjGen: mjGen }; },
  };`);
}

test("a seven-keystroke burst reads the store ONCE, not seven times", () => {
  const s = mkCloseSandbox();
  const row = { id: "t1", symbol: "BHP", entry: 40 };
  s.setTrades([row, { id: "t2", symbol: "CBA" }]);
  s.setId("t1");
  const seen = [];
  for (let i = 0; i < 7; i++) seen.push(s.closeRowNow());   // "1234.56"
  assert.strictEqual(s.reads(), 1,
    `typing 7 characters caused ${s.reads()} full journal reads — the memo is not holding`);
  seen.forEach((r) => assert.strictEqual(r, row, "the memo returned something other than the row"));
});

test("a store write invalidates the memo AND the next read returns the NEW row", () => {
  // The half that matters. A memo that merely goes fast is not the requirement;
  // the requirement is that it shows what a fresh read would have shown, so a
  // sync pull landing while the modal is open must reach the preview.
  const s = mkCloseSandbox();
  s.setTrades([{ id: "t1", stop: 38 }]);
  s.setId("t1");
  assert.strictEqual(s.closeRowNow().stop, 38);
  assert.strictEqual(s.reads(), 1);

  s.setTrades([{ id: "t1", stop: 39.5 }]);   // a cross-tab write / sync pull
  s.bumpGen();
  const fresh = s.closeRowNow();
  assert.strictEqual(s.reads(), 2, "a generation bump did not force a re-read");
  assert.strictEqual(fresh.stop, 39.5,
    "the preview would still be pricing the OLD stop after the store changed");
});

test("switching the row being closed invalidates it within one generation", () => {
  // The id is half the key. Without it, closing A then B inside one generation
  // would preview B's outcome against A's numbers.
  const s = mkCloseSandbox();
  s.setTrades([{ id: "t1", symbol: "BHP" }, { id: "t2", symbol: "CBA" }]);
  s.setId("t1");
  assert.strictEqual(s.closeRowNow().symbol, "BHP");
  s.setId("t2");
  assert.strictEqual(s.closeRowNow().symbol, "CBA", "the memo answered for the previous row");
  assert.strictEqual(s.reads(), 2);
});

test("with no row selected it returns null and touches the store at all", () => {
  const s = mkCloseSandbox();
  s.setTrades([{ id: "t1" }]);
  s.clear();
  assert.strictEqual(s.closeRowNow(), null);
  assert.strictEqual(s.reads(), 0, "a closed modal still read the whole journal");
});

test("a row that vanished from the store resolves to null, not to the held copy", () => {
  const s = mkCloseSandbox();
  s.setTrades([{ id: "t1" }]);
  s.setId("t1");
  assert.ok(s.closeRowNow());
  s.setTrades([]);            // deleted on another device, pulled in by sync
  s.bumpGen();
  assert.strictEqual(s.closeRowNow(), null,
    "a deleted trade would keep previewing from a row that no longer exists");
  assert.strictEqual(s.peek().row, null, "the stale row is still being held");
});

test("every path that writes the store bumps the generation", () => {
  // The memo is only as good as the invalidation, and the invalidation is only
  // as good as its coverage. Miss one writer and the bug comes back scoped to
  // that writer, which is strictly harder to find than the original.
  ["mjSaveLocal", "mjSave", "afterStoreChange"].forEach((name) => {
    const body = fnSrc(JOURNAL_SRC, name, "journal.js");
    assert.ok(/mjGen\s*\+\+/.test(body),
      `${name}() writes the store without bumping mjGen — the close preview would go stale after it`);
  });
});

test("the cross-tab `storage` listener routes through afterStoreChange", () => {
  // Another TAB writing is the case a same-tab bump cannot see, and it is also
  // the case where the modal is most likely to be open.
  assert.ok(/addEventListener\("storage",[\s\S]{0,160}?afterStoreChange\(\)/.test(JOURNAL_SRC),
    "the storage listener no longer goes through afterStoreChange, so a cross-tab write cannot invalidate the memo");
});

test("the modal seeds the memo on open and clears it on close", () => {
  const open = fnSrc(JOURNAL_SRC, "openCloseModal", "journal.js");
  assert.ok(/closeRow\s*=\s*t;\s*closeRowGen\s*=\s*mjGen;/.test(open),
    "openCloseModal no longer seeds the memo from the read it just did — the first keystroke re-reads for nothing");
  const close = fnSrc(JOURNAL_SRC, "closeModal", "journal.js");
  assert.ok(/closeRow\s*=\s*null/.test(close) && /closeRowGen\s*=\s*-1/.test(close),
    "closeModal lets the held row outlive the modal");
});

test("updateClosePreview goes through the memo and no longer reads the store itself", () => {
  const body = fnSrc(JOURNAL_SRC, "updateClosePreview", "journal.js");
  assert.ok(/closeRowNow\(\)/.test(body), "updateClosePreview no longer calls closeRowNow()");
  assert.ok(!/mjLoad\(/.test(body),
    "updateClosePreview is reading the whole journal again — the per-keystroke read is back");
});

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

// ===========================================================================
suite("#88 · horizon.js + regime.js — a renderer fault is reported, not disguised");
// ===========================================================================
const SURFACES = [
  { file: "horizon.js", src: HORIZON_SRC, panel: "horizon-panel", strip: "horizon-strip" },
  { file: "regime.js", src: REGIME_SRC, panel: "regime-panel", strip: "regime-strip" },
];

function mkSurfaceSandbox(S) {
  return build(`${S.file} #88`, [
    "var drawn = [], boom = {}, timers = [], els = {}, buttons = [], handlers = [];",
    "function setTimeout(fn) { timers.push(fn); return timers.length; }",
    "var document = { getElementById: function (id) { return els[id] || null; },",
    "                 querySelectorAll: function () { return buttons; } };",
    "function renderPanel(el, data) { if (boom.panel) throw new Error('panel boom'); drawn.push(['panel', data]); }",
    "function renderStrip(el, data) { if (boom.strip) throw new Error('strip boom'); drawn.push(['strip', data]); }",
    declSrc(S.src, /let DATA = null;/, S.file),
    declSrc(S.src, /let BOUND = false;/, S.file),
    fnSrc(S.src, "report", S.file),
    fnSrc(S.src, "draw", S.file),
    fnSrc(S.src, "render", S.file),
    fnSrc(S.src, "mount", S.file),
  ], `return {
    mount: mount, render: render,
    drawn: function () { return drawn; },
    surfaces: function () { return drawn.map(function (d) { return d[0]; }); },
    payloads: function () { return drawn.map(function (d) { return d[1]; }); },
    reset: function () { drawn.length = 0; },
    boom: function (k) { boom[k] = true; },
    host: function (id) { els[id] = { id: id, hidden: false }; },
    hidden: function (id) { return els[id] ? els[id].hidden : null; },
    withButtons: function (n) {
      buttons.length = 0;
      for (var i = 0; i < n; i++) {
        buttons.push({ addEventListener: function (ev, fn) { handlers.push([ev, fn]); } });
      }
    },
    handlers: function () { return handlers; },
    click: function () { handlers.forEach(function (h) { h[1](); }); },
    flush: function () {
      var q = timers.slice(); timers.length = 0;
      var errs = [];
      q.forEach(function (fn) { try { fn(); } catch (e) { errs.push(e); } });
      return errs;
    },
    data: function () { return DATA; },
    bound: function () { return BOUND; },
  };`);
}

SURFACES.forEach((S) => {
  test(`${S.file}: render() before any payload is a no-op`, () => {
    const s = mkSurfaceSandbox(S);
    s.host(S.panel); s.host(S.strip);
    s.render();
    assert.deepStrictEqual(s.surfaces(), [], "render() drew from a null payload");
  });

  test(`${S.file}: a strip that throws does not hide a panel that rendered fine`, () => {
    // The literal #88 failure. mount draws the panel FIRST, so before the fix a
    // throwing strip reached the fetch's .catch, which hid both surfaces.
    const s = mkSurfaceSandbox(S);
    s.host(S.panel); s.host(S.strip);
    s.boom("strip");
    s.mount({ v: 1 });
    assert.deepStrictEqual(s.surfaces(), ["panel"], "the panel was taken down with the strip");
    assert.strictEqual(s.hidden(S.panel), false, "the panel was hidden by a fault in the other surface");
  });

  test(`${S.file}: a panel that throws does not stop the strip from drawing`, () => {
    // The direction the ordering does NOT give you for free: the panel is drawn
    // first, so only a real per-surface try/catch saves the strip.
    const s = mkSurfaceSandbox(S);
    s.host(S.panel); s.host(S.strip);
    s.boom("panel");
    s.mount({ v: 1 });
    assert.deepStrictEqual(s.surfaces(), ["strip"], "one bad row in the panel took the strip down with it");
  });

  test(`${S.file}: the fault is RE-RAISED asynchronously, not swallowed`, () => {
    // telemetry.js beacons window.onerror into a ring buffer that survives the
    // glitch. A console.error would isolate the surface at the cost of dropping
    // the fault out of the one record anyone can read back afterwards.
    const s = mkSurfaceSandbox(S);
    s.host(S.panel); s.host(S.strip);
    s.boom("panel");
    s.mount({ v: 1 });
    const errs = s.flush();
    assert.strictEqual(errs.length, 1, `expected exactly one re-raised fault, got ${errs.length}`);
    assert.strictEqual(errs[0].message, "panel boom");
  });

  test(`${S.file}: a host element that is not on this page is skipped silently`, () => {
    // index.html ships the strip and no panel; sectors.html ships the panel.
    const s = mkSurfaceSandbox(S);
    s.host(S.strip);
    s.mount({ v: 1 });
    assert.deepStrictEqual(s.surfaces(), ["strip"]);
    assert.deepStrictEqual(s.flush(), [], "a missing host was reported as a fault");
  });

  test(`${S.file}: mount() twice binds the switch once but refreshes the payload`, () => {
    const s = mkSurfaceSandbox(S);
    s.host(S.panel); s.host(S.strip);
    s.withButtons(3);
    s.mount({ v: 1 });
    assert.strictEqual(s.handlers().length, 3, "the market switch was not bound");
    s.reset();
    s.mount({ v: 2 });
    assert.strictEqual(s.handlers().length, 3, "a second mount stacked a second listener on every button");
    assert.deepStrictEqual(s.data(), { v: 2 }, "a second mount did not refresh DATA");
  });

  test(`${S.file}: a market switch redraws from the CURRENT payload`, () => {
    const s = mkSurfaceSandbox(S);
    s.host(S.panel); s.host(S.strip);
    s.withButtons(1);
    s.mount({ v: 1 });
    s.mount({ v: 2 });
    s.reset();
    s.click();
    assert.deepStrictEqual(s.surfaces(), [], "the switch redrew synchronously, inside app.js's own click handler");
    s.flush();
    assert.deepStrictEqual(s.surfaces(), ["panel", "strip"]);
    s.payloads().forEach((p) => assert.deepStrictEqual(p, { v: 2 }, "the switch redrew a stale payload"));
  });

  test(`${S.file}: a page with no market switch binds nothing and still draws`, () => {
    const s = mkSurfaceSandbox(S);
    s.host(S.panel);
    s.withButtons(0);
    s.mount({ v: 1 });
    assert.deepStrictEqual(s.surfaces(), ["panel"]);
    assert.strictEqual(s.bound(), false, "BOUND was latched on a page that has no buttons to bind");
  });

  test(`${S.file}: the .catch is scoped to the fetch and parse ONLY`, () => {
    // The one-line statement of #88: the catch must sit BETWEEN the parse and
    // the mount, so "the file isn't there" and "a renderer threw" stop sharing a
    // handler.
    const iParse = S.src.indexOf(".then((r) =>");
    const iCatch = S.src.indexOf(".catch(");
    const iMount = S.src.indexOf(".then((data) =>");
    assert.ok(iParse > 0, `${S.file}: the fetch chain's parse step moved`);
    assert.ok(iCatch > iParse, `${S.file}: the .catch no longer follows the parse`);
    assert.ok(iMount > iCatch,
      `${S.file}: the .catch is back AFTER mount — a renderer fault is being handled as a missing file again`);
    assert.ok(!/\.then\(mount\)/.test(S.src), `${S.file}: mount is back in a bare .then, ahead of the catch`);
  });

  test(`${S.file}: draw() reports rather than hides, and hides nothing`, () => {
    const body = fnSrc(S.src, "draw", S.file);
    assert.ok(/catch\s*\(\s*err\s*\)\s*\{\s*report\(err\);/.test(body),
      `${S.file}: draw() no longer reports the fault it caught`);
    assert.ok(!/hidden/.test(body),
      `${S.file}: draw() hides a surface on a render fault — that is the "missing file" answer to the wrong question`);
    const rep = fnSrc(S.src, "report", S.file);
    assert.ok(/setTimeout\(/.test(rep) && /throw err;/.test(rep),
      `${S.file}: report() no longer re-raises asynchronously, so telemetry.js never sees the fault`);
    assert.ok(!/console\.(error|warn)/.test(rep),
      `${S.file}: report() logs instead of re-raising — the fault drops out of the ring buffer`);
  });

  test(`${S.file}: the switch listener re-runs render(), not one surface`, () => {
    const body = fnSrc(S.src, "mount", S.file);
    assert.ok(/addEventListener\("click",\s*\(\)\s*=>\s*setTimeout\(render,\s*0\)\)/.test(body),
      `${S.file}: the market-switch listener no longer defers a full render()`);
  });
});

// ---------------------------------------------------------------------------
console.log(process.exitCode
  ? "\nSOME STATEKEEP TESTS FAILED"
  : `\nALL ${passed} statekeep tests passed`);
