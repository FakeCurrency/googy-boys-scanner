/* Screenshot-diff gate (UI backlog #98).
 *
 * Captures key views at desktop + 390px and fails if more than 2% of pixels
 * drift from the baseline — an unreviewed visual regression (a broken layout, a
 * vanished component) can't ship silently.
 *
 * Determinism, so the gate isn't flaky:
 *   - Baselines are SELF-CAPTURED per environment (GitHub Actions cache in CI),
 *     never committed — so cross-environment font rendering can't false-fail.
 *     First run in an env writes the baseline and passes; later runs diff.
 *   - Every time-based element (clocks, countdown, "scanned Xm ago", the update
 *     nudge) is masked before the shot; animations/transitions are frozen.
 *   - The page CLOCK is frozen to the fixtures' own instant (see FROZEN_MS), and
 *     the baseline has to prove it was drawn by that same clock (see the
 *     `.clock` sentinel) or it is discarded rather than diffed.
 *   - pixelmatch runs with a per-pixel threshold that ignores anti-aliasing, so
 *     only STRUCTURAL differences count toward the 2%.
 *
 * To accept an intentional visual change: bust the baseline cache (bump the
 * cache key in test.yml) so the next run re-baselines.
 *
 * Local: PW_CHROMIUM=/path/to/chromium node test/e2e/screenshot-diff.e2e.js
 *        (first local run self-baselines into test/e2e/__baseline__)
 */
"use strict";
const { spawn } = require("child_process");
const net = require("net");
const path = require("path");
const fs = require("fs");

let chromium;
try { ({ chromium } = require("playwright")); }
catch (_) { ({ chromium } = require("/home/claude/.npm-global/lib/node_modules/playwright")); }
const PM = require("pixelmatch");
const pixelmatch = PM.default || PM;
const { PNG } = require("pngjs");

const ROOT = path.join(__dirname, "..", "..", "public");
const BASE = path.join(__dirname, "__baseline__");
const SHOTS = path.join(__dirname, "__shots__");
const DIFF = path.join(__dirname, "__diff__");
const PORT = 8947;
const BUDGET = 0.02;   // 2% of pixels

for (const d of [BASE, SHOTS, DIFF]) fs.mkdirSync(d, { recursive: true });

// FROZEN CLOCK (2026-07-28) — the second half of the FROZEN DATA fix below, and
// the half that was still live. Pinning /data/ stopped the fixtures moving; it
// did NOT stop the PAGE moving, because journal.js renders the fixture set
// through `Date.now()`: `renderNewPositions` prints "3h ago"/"2d ago" per row
// (:1155-1160), `markStale` badges a close by its age in days, and the week grid
// re-buckets by day. So the same bytes rendered a different picture every hour,
// against a baseline that — by design — never re-saves.
//
// That was not slow decay, it was a dated fuse. `NEW_POS_WINDOW_MS` is 7 days
// and the newest position in the fixture book opened 2026-07-23T17:46Z, so on
// 2026-07-30 both "new positions" panels would have collapsed to a single
// "No new positions in the last 7 days." line and taken the journal shots well
// past the 2% budget — a red gate caused by the calendar, on a commit that
// changed nothing. Measured drift the day before this fix: 1.41%/1.42% on the
// journal pages, 22 hours after the baseline was cut. Index was 0.03%, because
// index.html has no relative-time rendering.
//
// The instant is READ FROM THE FIXTURE, never hard-coded: refresh the fixtures
// and the clock follows them, so the two can never drift apart again. A fixture
// with no parseable timestamp throws here rather than silently falling back to
// the real clock, because a silent fallback rebuilds the exact bug.
const BOOK_FIXTURE = path.join(__dirname, "fixtures", "data", "vivek_bot_book.json");
const FROZEN_MS = (() => {
  const raw = JSON.parse(fs.readFileSync(BOOK_FIXTURE, "utf8"));
  const t = Date.parse(raw && raw.updated_at);
  if (!isFinite(t)) throw new Error(`cannot freeze the clock: ${BOOK_FIXTURE} has no parseable updated_at`);
  return t;
})();

// Installed before any page script runs. A Proxy rather than `class extends
// Date` so that a bare `Date()` call (no `new`) still works, `Date.parse` and
// `Date.UTC` stay reachable, and `x instanceof Date` still answers true —
// constructed instances are real Dates, only the zero-argument construction and
// `now()` are pinned. Explicit arguments are passed straight through, so
// `new Date(t.opened_at)` still parses the fixture's own timestamps.
function freezeClock(FIXED) {
  const _Date = Date;
  window.Date = new Proxy(_Date, {
    construct: (target, args) => (args.length ? new target(...args) : new target(FIXED)),
    apply: () => new _Date(FIXED).toString(),
    get: (target, prop, recv) => (prop === "now" ? () => FIXED : Reflect.get(target, prop, recv)),
  });
}

// BASELINE PROVENANCE (2026-07-28) — the sentinel that makes the frozen clock
// safe to move. Freezing the clock stops the baseline aging; it does not stop
// the baseline being OLDER THAN THE FREEZE. Those are different failures and
// only the first one is fixed above.
//
// The cached baseline outlives the code that drew it, so on the run right after
// this change every PNG in the cache was drawn by the real wall clock while
// today's shot is drawn at FROZEN_MS — a repaint of every relative-time row at
// once, well past the budget, on a commit whose only change was to make the gate
// deterministic. The v10 -> v11 key bump in test.yml handles that one instance.
// A key bump is a human remembering, though, and this gate's entire history is
// nine of them (v1 -> v10), each buying about a day. So the baseline is made to
// answer for itself instead.
//
// `.clock` records the instant that drew the baseline, and lives INSIDE
// `__baseline__` so it travels with the pictures it describes — in the same
// cache entry, restored or missed as one unit. Two states mean "these were not
// drawn by this clock": the stamp disagrees with today's FROZEN_MS (the
// fixtures were refreshed, which moves the clock with them), or there is no
// stamp at all beside PNGs that plainly exist, which is exactly the shape of a
// pre-freeze baseline restored from an old cache.
//
// Both DISCARD and re-cut rather than fail. That asymmetry is the point: a
// re-baseline costs one run of comparison, while a red costs a person's
// attention on a push they cannot act on, and a channel that cries wolf gets
// muted — which is the failure this gate has actually been producing.
//
// It is a floor, not the mechanism. `actions/cache@v4` does not re-save on a
// key HIT, so a discard here does not persist: if the fixtures move without the
// cache key moving, every run discards, re-cuts and passes, and the gate stops
// comparing anything until someone bumps the key. The log line below says so in
// those words, and test.yml's key carries a digest of the fixtures precisely so
// the ordinary case cuts a fresh cache entry instead of leaning on this.
const CLOCK = path.join(BASE, ".clock");

function reconcileBaselineClock() {
  const shots = fs.existsSync(BASE) ? fs.readdirSync(BASE).filter((f) => f.endsWith(".png")) : [];
  const stamped = fs.existsSync(CLOCK) ? fs.readFileSync(CLOCK, "utf8").trim() : null;
  const want = String(FROZEN_MS);
  // No pictures yet: this run cuts them, so stamp the clock that will draw them.
  if (!shots.length) { fs.writeFileSync(CLOCK, want); return 0; }
  if (stamped === want) return 0;
  for (const f of shots) fs.unlinkSync(path.join(BASE, f));
  fs.writeFileSync(CLOCK, want);
  console.log(
    `BASELINE RESET — discarded ${shots.length} baseline(s) drawn at ` +
    `${stamped ? new Date(Number(stamped)).toISOString() : "an unrecorded instant (pre-freeze baseline)"}; ` +
    `this run renders at ${new Date(FROZEN_MS).toISOString()}. Re-baselining and PASSING, because a ` +
    `baseline drawn by a clock that no longer exists can only produce a failure nobody can act on. ` +
    `If you see this line on EVERY run, the cached baseline is being restored and re-discarded in a ` +
    `loop — bump the screenshot-baselines key in .github/workflows/test.yml to cut a fresh cache entry.`
  );
  return shots.length;
}

// Views: [name, path, width, height]
const VIEWS = [
  ["index-desktop", "index.html", 1280, 800],
  ["index-390", "index.html", 390, 844],
  ["journal-desktop", "journal.html", 1280, 900],
  ["journal-390", "journal.html", 390, 844],
];

// Everything time-based, plus a freeze of all motion, so the shot is stable.
const MASK = `
  #microclock, #refresh-timer, .refresh-timer, .scan-fresh, [id^="clk-"],
  #gbs-update-nudge, #gbs-offline-banner, .jr-pnl-sub, #bot-note, .side-note,
  #scan-sub, .deck-dot { visibility: hidden !important; }
  *, *::before, *::after { animation: none !important; transition: none !important;
    caret-color: transparent !important; }
`;

const waitPort = (port, tries = 50) => new Promise((res, rej) => {
  const poke = (n) => {
    const s = net.connect(port, "127.0.0.1");
    s.once("connect", () => { s.destroy(); res(); });
    s.once("error", () => { s.destroy(); n ? setTimeout(() => poke(n - 1), 200) : rej(new Error("server never came up")); });
  };
  poke(tries);
});

(async () => {
  const srv = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: ROOT, stdio: "ignore" });
  let failures = 0, created = 0, diffed = 0, reset = 0;
  try {
    // Before anything is captured: are the baselines we are about to diff
    // against even from this clock? See CLOCK above.
    reset = reconcileBaselineClock();
    await waitPort(PORT);
    const opts = process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM }
      : process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {};
    const browser = await chromium.launch(opts);
    for (const [name, page, w, h] of VIEWS) {
      const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1, reducedMotion: "reduce" });
      // Context-level, so iframes get it too, and BEFORE newPage so nothing can
      // read the real clock first. See FROZEN_MS above.
      await ctx.addInitScript(freezeClock, FROZEN_MS);
      const p = await ctx.newPage();
      // Onboarding tour + status pill are session-dependent — keep shots deterministic.
      await p.addInitScript(() => { try { localStorage.setItem("gbs:onboarded", "1"); } catch (_) {} });
      // FROZEN DATA (2026-07-26): live scan JSON changes with every scheduled
      // commit, which slowly drifts the shots until the gate false-fails on a
      // code push that changed nothing visual (observed: index 2.99% pure-data
      // drift). Every /data/ request is served from the committed fixture set
      // instead, so the diff only ever sees UI changes.
      await ctx.route("**/data/**", (route) => {
        const rel = new URL(route.request().url()).pathname.replace(/^\/+/, "");
        const fix = path.join(__dirname, "fixtures", rel);
        if (fs.existsSync(fix)) {
          route.fulfill({ status: 200, contentType: "application/json", body: fs.readFileSync(fix) });
        } else {
          route.fulfill({ status: 404, contentType: "text/plain", body: "no fixture" });
        }
      });
      await p.goto(`http://localhost:${PORT}/${page}`, { waitUntil: "networkidle", timeout: 30000 }).catch(() => {});
      await p.addStyleTag({ content: MASK }).catch(() => {});
      await p.waitForTimeout(1200);
      const shotPath = path.join(SHOTS, name + ".png");
      await p.screenshot({ path: shotPath, fullPage: false });
      await ctx.close();

      const basePath = path.join(BASE, name + ".png");
      if (!fs.existsSync(basePath)) {
        fs.copyFileSync(shotPath, basePath);
        created++;
        console.log(`BASELINE  ${name} (${w}x${h}) — created, no prior baseline`);
        continue;
      }
      const a = PNG.sync.read(fs.readFileSync(basePath));
      const b = PNG.sync.read(fs.readFileSync(shotPath));
      if (a.width !== b.width || a.height !== b.height) {
        failures++;
        console.error(`FAIL  ${name} — size changed ${a.width}x${a.height} -> ${b.width}x${b.height}`);
        continue;
      }
      const diff = new PNG({ width: a.width, height: a.height });
      const changed = pixelmatch(a.data, b.data, diff.data, a.width, a.height, { threshold: 0.2, includeAA: false });
      const pct = changed / (a.width * a.height);
      diffed++;
      if (pct > BUDGET) {
        failures++;
        fs.writeFileSync(path.join(DIFF, name + ".png"), PNG.sync.write(diff));
        console.error(`FAIL  ${name} — ${(pct * 100).toFixed(2)}% drift > ${(BUDGET * 100)}% (diff image in __diff__)`);
      } else {
        console.log(`PASS  ${name} — ${(pct * 100).toFixed(2)}% drift (<= ${(BUDGET * 100)}%)`);
      }
    }
    await browser.close();
  } catch (e) {
    console.error("screenshot-diff error:", e.message); failures++;
  } finally {
    srv.kill();
  }
  console.log(`\n${created} baselined, ${diffed} compared, ${reset} discarded as pre-freeze, ${failures} failure(s)`);
  process.exit(failures ? 1 : 0);
})();
