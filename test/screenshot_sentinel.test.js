/* The screenshot gate's baseline has to prove where it came from (out of band).
 *
 * This is the suite for the half of the fix that a regex test cannot reach.
 * `tests/test_screenshot_determinism.py` pins that the clock is frozen, read
 * from the fixtures, and installed before the page loads — all of which are
 * visible in the source. What is NOT visible in the source is what the gate
 * DOES when it meets a baseline drawn by a different clock, and that behaviour
 * is the whole point of the item:
 *
 *   discard and re-cut, never fail.
 *
 * Why that asymmetry is worth a suite of its own. This gate has been the
 * recurring failure email. With /data/ pinned to fixtures so the clock was the
 * only moving part, journal-desktop measured 2.39% drift against a 2% budget
 * the moment its cached baseline was two days old — and flat at 2.39% for 2, 3,
 * 5 and 7 days, i.e. a day-bucket boundary rather than decay. `actions/cache@v4`
 * on an exact key persists and refreshes on access, so that was not a phase; it
 * was every subsequent run, permanently, on commits that changed nothing. The
 * repo's answer for ten months was to bump the cache key (v1 -> v10), which
 * re-cuts the baseline, buys a day, and goes red again.
 *
 * Freezing the clock stops the baseline aging. It does not stop a baseline
 * being OLDER THAN THE FREEZE, and that is the state every cached baseline was
 * in on the run right after the fix. `.clock` is how the baseline answers for
 * itself; the tests below are what stop the answer being "fail" again.
 *
 * Everything is sliced out of the SHIPPED e2e file and executed against real
 * temp directories. Nothing is re-typed: a re-typed copy of this function would
 * pass while the shipped one deleted the wrong files.
 */
"use strict";
const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");

const SRC_PATH = path.join(__dirname, "e2e", "screenshot-diff.e2e.js");

// Line-oriented comment stripper, same as test/leaks.test.js and
// test/statekeep.test.js: the mutation a human actually makes is to comment a
// line OUT, which leaves the text in the file for any regex to match.
const codeOnly = (src) =>
  src.split("\n").filter((l) => {
    const t = l.trim();
    return !(t.startsWith("//") || t.startsWith("/*") || t.startsWith("*"));
  }).join("\n");

const SRC = codeOnly(fs.readFileSync(SRC_PATH, "utf8"));

// Slicers: walk candidate terminators and let the JS PARSER decide which one
// closes the construct. A hand-rolled brace balancer desyncs on the first
// regex literal or brace-inside-a-string, and this file has both.
function extractConst(src, name) {
  const at = src.search(new RegExp(`\\bconst\\s+${name}\\s*=`));
  assert.ok(at >= 0, `screenshot-diff.e2e.js no longer defines const ${name}`);
  const start = src.indexOf("=", at) + 1;
  for (let i = src.indexOf(";", start); i > 0 && i - start < 4000; i = src.indexOf(";", i + 1)) {
    const cand = src.slice(start, i).trim();
    try { new Function(`return (${cand});`); return cand; } catch (_) { /* keep walking */ }
  }
  assert.fail(`could not slice const ${name} — has its shape changed?`);
}
function fnSrc(src, name) {
  const at = src.search(new RegExp(`\\bfunction\\s+${name}\\s*\\(`));
  assert.ok(at >= 0, `screenshot-diff.e2e.js no longer declares function ${name}()`);
  for (let i = src.indexOf("}", at); i > 0 && i - at < 12000; i = src.indexOf("}", i + 1)) {
    const cand = src.slice(at, i + 1);
    try { new Function(`return (${cand});`); return cand; } catch (_) { /* keep walking */ }
  }
  assert.fail(`could not slice ${name}() — has its brace shape changed?`);
}

const CLOCK_EXPR = extractConst(SRC, "CLOCK");
const RECONCILE = fnSrc(SRC, "reconcileBaselineClock");

// The sandbox is `new Function`, not `vm`: same realm, so values built inside
// compare normally against values built out here. BASE and FROZEN_MS are
// injected because they are the two inputs under test; CLOCK and the function
// itself are the SHIPPED source, so a change to where the sentinel lives or to
// what counts as a mismatch fails here rather than in production.
function mk(BASE, FROZEN_MS) {
  const logs = [];
  const body = [
    "const fs = FS, path = PATH, BASE = B, FROZEN_MS = F;",
    "const console = { log: LOG };",
    `const CLOCK = ${CLOCK_EXPR};`,
    RECONCILE,
    "return { run: reconcileBaselineClock, clockPath: CLOCK };",
  ].join("\n\n");
  let made;
  try { made = new Function("FS", "PATH", "B", "F", "LOG", body)(fs, path, BASE, FROZEN_MS, (m) => logs.push(m)); }
  catch (e) { assert.fail(`sandbox failed to build — ${e.message}`); }
  return { ...made, logs };
}

// The shipped module mkdirs BASE at load (`for (const d of [BASE, SHOTS, DIFF])`),
// so reconcileBaselineClock is always entered with the directory present. The
// harness reproduces that rather than the function growing a redundant mkdir.
let TMP_ROOT = null;
function freshBase() {
  if (!TMP_ROOT) TMP_ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "gbs-clock-"));
  const d = fs.mkdtempSync(path.join(TMP_ROOT, "base-"));
  return d;
}
const png = (base, name) => fs.writeFileSync(path.join(base, name + ".png"), Buffer.from([0x89, 0x50, 0x4e, 0x47]));
const pngs = (base) => fs.readdirSync(base).filter((f) => f.endsWith(".png")).sort();
const stamp = (base) => {
  const p = path.join(base, ".clock");
  return fs.existsSync(p) ? fs.readFileSync(p, "utf8") : null;
};

let passed = 0;
const test = (name, fn) => {
  try { fn(); passed++; console.log("PASS  " + name); }
  catch (e) { console.error("FAIL  " + name + "\n      " + e.message); process.exitCode = 1; }
};
const suite = (n) => console.log(`\n── ${n} ──`);

const NOW = 1769000000000;   // an arbitrary fixed instant; nothing here reads a real clock

// ===========================================================================
suite("the sentinel travels with the pictures it describes");
// ===========================================================================

test("`.clock` is written INSIDE the baseline directory, not beside it", () => {
  const base = freshBase();
  const { clockPath } = mk(base, NOW);
  // If the sentinel lived outside __baseline__ it would not be in the cached
  // path, so it would be absent on every restore and present on every fresh
  // runner — the baselines would arrive with no provenance at all and the
  // check below would fire on every single run, which is a different way of
  // being useless.
  assert.strictEqual(path.dirname(path.resolve(clockPath)), path.resolve(base),
    "the .clock sentinel is no longer inside __baseline__, so it will not be cached with the baselines it describes");
  assert.strictEqual(path.basename(clockPath), ".clock");
});

test("a dotfile name keeps the sentinel out of the baseline's own file list", () => {
  const base = freshBase();
  const { clockPath } = mk(base, NOW);
  // Not cosmetic: the discard walks the directory. A sentinel named
  // `clock.png` would delete itself and be counted as a baseline.
  assert.ok(!clockPath.endsWith(".png"), "the sentinel must not be a .png — the discard walks *.png");
});

// ===========================================================================
suite("first run in an environment");
// ===========================================================================

test("an empty baseline directory is stamped, not reset", () => {
  const base = freshBase();
  const { run } = mk(base, NOW);
  assert.strictEqual(run(), 0, "nothing existed, so nothing can have been discarded");
  assert.strictEqual(stamp(base), String(NOW), "the clock that is about to draw the baselines was not recorded");
});

test("the stamp is the frozen instant itself, so it moves when the fixtures do", () => {
  const base = freshBase();
  mk(base, NOW).run();
  const first = stamp(base);
  const other = freshBase();
  mk(other, NOW + 86400000).run();
  assert.notStrictEqual(stamp(other), first,
    "two different frozen instants wrote the same stamp — the sentinel is not derived from FROZEN_MS");
});

// ===========================================================================
suite("a baseline drawn by THIS clock is left alone");
// ===========================================================================

test("matching stamp: nothing is discarded and nothing is deleted", () => {
  const base = freshBase();
  const { run } = mk(base, NOW);
  png(base, "index-desktop"); png(base, "journal-desktop");
  fs.writeFileSync(path.join(base, ".clock"), String(NOW));
  assert.strictEqual(run(), 0);
  assert.deepStrictEqual(pngs(base), ["index-desktop.png", "journal-desktop.png"],
    "baselines drawn by the current clock were deleted — the gate now compares nothing");
});

test("a trailing newline in the stamp is not a mismatch", () => {
  const base = freshBase();
  const { run } = mk(base, NOW);
  png(base, "index-desktop");
  fs.writeFileSync(path.join(base, ".clock"), String(NOW) + "\n");
  // Anything that rewrites this file by hand or through an editor adds one.
  // Treating whitespace as a mismatch would retire a perfectly good baseline
  // on every run and silently disable the gate.
  assert.strictEqual(run(), 0, "the stamp comparison is no longer trimmed");
  assert.deepStrictEqual(pngs(base), ["index-desktop.png"]);
});

test("running twice in a row is a no-op the second time", () => {
  const base = freshBase();
  const { run } = mk(base, NOW);
  png(base, "index-desktop"); png(base, "journal-390");
  fs.writeFileSync(path.join(base, ".clock"), "999");
  assert.strictEqual(run(), 2, "the stale baselines were not discarded");
  png(base, "index-desktop"); png(base, "journal-390");   // stands in for the capture loop re-cutting them
  assert.strictEqual(run(), 0, "the freshly re-cut baselines were discarded again — this loops forever");
  assert.deepStrictEqual(pngs(base), ["index-desktop.png", "journal-390.png"]);
});

// ===========================================================================
suite("a baseline drawn by a clock that no longer exists");
// ===========================================================================

test("a disagreeing stamp discards the baselines and re-stamps", () => {
  const base = freshBase();
  const { run } = mk(base, NOW);
  png(base, "index-desktop"); png(base, "index-390"); png(base, "journal-desktop");
  fs.writeFileSync(path.join(base, ".clock"), String(NOW - 2 * 86400000));
  assert.strictEqual(run(), 3, "all three stale baselines should have been discarded");
  assert.deepStrictEqual(pngs(base), [], "a stale baseline survived and will be diffed against");
  assert.strictEqual(stamp(base), String(NOW), "the sentinel was not moved to the clock now in force");
});

test("PNGs with NO stamp are treated as pre-freeze and discarded", () => {
  const base = freshBase();
  const { run } = mk(base, NOW);
  png(base, "journal-desktop"); png(base, "journal-390");
  // This is precisely the shape of a v10 baseline restored from cache: drawn
  // before the sentinel existed, therefore drawn by the runner's wall clock.
  // Reading "no stamp" as "fine" is the single change that would put the
  // recurring failure email back, so it gets its own test.
  assert.strictEqual(run(), 2, "an unstamped baseline was accepted — that is a pre-freeze picture");
  assert.deepStrictEqual(pngs(base), []);
  assert.strictEqual(stamp(base), String(NOW));
});

test("the discard is scoped to baselines and touches nothing else", () => {
  const base = freshBase();
  const { run } = mk(base, NOW);
  png(base, "index-desktop");
  fs.writeFileSync(path.join(base, "notes.txt"), "keep me");
  fs.writeFileSync(path.join(base, ".clock"), "1");
  assert.strictEqual(run(), 1, "the count should be baselines discarded, not files in the directory");
  assert.ok(fs.existsSync(path.join(base, "notes.txt")), "the discard deleted a non-baseline file");
});

// ===========================================================================
suite("the reset is a soft failure — this is the item");
// ===========================================================================

test("a reset returns a count and does not throw", () => {
  const base = freshBase();
  const { run } = mk(base, NOW);
  png(base, "journal-desktop");
  assert.strictEqual(typeof run(), "number",
    "the reset path must report a count the caller can print, not signal by throwing");
});

test("nothing in the reconcile can register a failure", () => {
  // The behavioural tests above prove it does not throw. This one closes the
  // other route: quietly incrementing the run's failure counter, which would
  // send the email while looking, in every log line, like a clean re-baseline.
  assert.ok(!/\bfailures\b/.test(RECONCILE),
    "reconcileBaselineClock now touches `failures` — a stale baseline must be re-cut, never reported as a fault");
  assert.ok(!/\bprocess\.exit\b/.test(RECONCILE), "reconcileBaselineClock now exits the process");
  assert.ok(!/console\.error/.test(RECONCILE),
    "the reset is announced with console.error — it is not an error, and CI surfacing makes it read as one");
});

test("the reset says out loud how to break a discard loop", () => {
  const base = freshBase();
  const { run, logs } = mk(base, NOW);
  png(base, "journal-desktop");
  run();
  assert.strictEqual(logs.length, 1, "a silent discard leaves no way to tell a re-baseline from a comparison");
  const msg = String(logs[0]);
  // cache@v4 does not re-save on a key hit, so a discard does not persist: if
  // the cached baseline keeps coming back, this line is the only thing that
  // tells you the gate has stopped comparing and what to do about it.
  assert.ok(/test\.yml/.test(msg) && /bump/i.test(msg),
    "the reset message no longer names the cache key as the fix for a repeating discard");
  assert.ok(/PASSING|re-baselin/i.test(msg), "the message no longer says the run is passing");
});

// ===========================================================================
suite("the call site");
// ===========================================================================

test("the reconcile runs before anything is captured", () => {
  const call = SRC.search(/reset\s*=\s*reconcileBaselineClock\(\)/);
  assert.ok(call >= 0, "reconcileBaselineClock() is defined but never called — the sentinel does nothing");
  const loop = SRC.indexOf("for (const [name, page, w, h] of VIEWS)");
  assert.ok(loop > 0, "the capture loop has moved — this test needs re-pointing");
  assert.ok(call < loop,
    "the baselines are reconciled after the capture loop starts, so the first views diff against a stale baseline");
});

console.log(`\n${passed} passed`);
