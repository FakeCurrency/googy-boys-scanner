/* Lighthouse budget gate (UI backlog #70).
 *
 * Serves the dashboard from a staging root whose /data/ is the COMMITTED
 * FIXTURE SET, runs Lighthouse against it, and fails the run if page weight or
 * layout stability regress past a budget.
 *
 * THE FIXTURE PIN IS THE POINT (2026-07-28). This gate used to serve public/
 * wholesale, so `total-byte-weight` was measuring the live scan JSON -- the
 * ~20 scheduled data commits a day that test.yml's path filter deliberately
 * does NOT trigger on. The budget was therefore keyed to how many ASX names
 * happened to set up that morning: a quiet tape passed, a broad tape failed,
 * and it failed on whatever unrelated CODE push landed next, which is a red
 * nobody can act on. Measured at 9d6221fe: 5.00MB against a 5.0MB budget, of
 * which 4.15MB was committed scan data -- and the growth was legitimate market
 * breadth (204 -> 343 ASX rows, same schema, per-field sizes proportional),
 * not a bloat regression. That is the same defect class that made the
 * screenshot gate fail on the calendar, and a worse one, because a date is at
 * least predictable and market breadth is not.
 *
 * So /data/ is pinned to test/e2e/fixtures/data -- the SAME set
 * screenshot-diff.e2e.js routes to -- and unfixtured files 404 exactly as they
 * do there, so the two e2e gates measure the same page and cannot drift apart.
 * Playwright's ctx.route() is unavailable here (lighthouse drives
 * chrome-launcher, not Playwright), so the pin is done at the SERVER ROOT: a
 * temp dir symlinking every top-level public/ entry, with data -> fixtures.
 *
 * WHAT IS AND IS NOT COVERED. Covered: the weight and layout stability of the
 * COMMIT -- js, css, fonts, markup, and the panels the fixture set feeds. NOT
 * covered: the phasemap, regime, backtest and prices panels, whose payloads
 * have no fixture and 404 here, so a CLS regression inside one of them is
 * invisible to this gate (screenshot-diff carries the same blind spot for the
 * same reason -- widen it by adding fixtures, in both places at once).
 *
 * THE REAL PAYLOAD IS REPORTED, NEVER GATED. 5MB uncompressed on a dashboard is
 * a genuine user-facing cost, and losing sight of it would be the wrong way to
 * fix a false-failing budget. So every run stats the REAL files behind the
 * /data/ URLs the page actually requested and prints the live weight; past
 * LIVE_PAYLOAD_WARN_MB it escalates to a ::warning:: on the run page. It never
 * touches `failures`, on the same asymmetry as the screenshot sentinel's
 * discard-don't-fail: an alarm that cannot stop ringing gets muted, and a muted
 * channel is what makes the next genuine red invisible. Slimming public/data/
 * is a product decision; this reports the number the decision needs.
 *
 * The URL list is derived from the run's OWN `network-requests` audit rather
 * than hard-coded, and unfixtured 404s still appear there -- so a new /data/
 * file the page starts fetching is counted the day it lands, with no manifest
 * to keep in sync.
 *
 * Served over an UNCOMPRESSED python http.server (no CDN, no brotli, no
 * HTTP/2), so the absolute numbers are pessimistic against the Cloudflare-served
 * reality. The page is loaded with ?lite=1 (measurement mode: no idle
 * cross-market prefetch, no auto-refresh countdown, no background polls) so
 * deferred work cannot land inside the trace at random.
 *
 * Budgets, measured over three consecutive fixture-pinned runs (2026-07-28:
 * transfer 1.850 / 1.861 / 1.861 MB, CLS 0.123 / 0.123 / 0.123):
 *   total transfer weight    < 2.5 MB   (~34% headroom over the 1.86MB baseline)
 *   cumulative-layout-shift  < 0.50     (unchanged -- see note)
 *   live /data/ payload      INFO, ::warning:: past 7.0MB, NEVER fails
 *   interactive (TTI)        INFO only (runner-variable)
 *
 * CLS stays at 0.50 even though the pin made it bit-identical across runs. It
 * was not the metric failing, and moving two budgets in one change makes the
 * next failure ambiguous about which one moved. The determinism is banked;
 * tightening it is a deliberate follow-up, not a freebie.
 *
 * Local: node test/e2e/lighthouse.e2e.js   (PW_CHROMIUM points at chromium)
 */
const { spawn } = require("child_process");
const fs = require("fs");
const net = require("net");
const os = require("os");
const path = require("path");

const PUBLIC = path.join(__dirname, "..", "..", "public");
const FIXTURES = path.join(__dirname, "fixtures", "data");
const PORT = 8945;
const MB = 1024 * 1024;

// --- Budgets -------------------------------------------------------------- //
// GATED. Sized above the fixture-pinned baseline, not above whatever the tape
// did today -- that was the bug. Both move only when a human decides they move.
const TRANSFER_BUDGET_MB = 2.5;
const CLS_BUDGET = 0.5;
// NOT gated. Above today's real 5.00MB so it does not cry wolf from day one,
// well below the ~13MB the payload could reach before anyone would call it
// pathological. This is a notice line, not a limit.
const LIVE_PAYLOAD_WARN_MB = 7.0;

// ?lite=1 puts app.js in measurement mode: no idle cross-market prefetch, no
// auto-refresh countdown, no background polls. That removes the deferred work
// that used to land inside the trace at random; the fixture pin below removes
// the other half, which was the data itself.
const URL_UNDER_TEST = `http://localhost:${PORT}/index.html?lite=1`;

const waitPort = (port, tries = 50) => new Promise((res, rej) => {
  const poke = (n) => {
    const s = net.connect(port, "127.0.0.1");
    s.once("connect", () => { s.destroy(); res(); });
    s.once("error", () => { s.destroy(); n ? setTimeout(() => poke(n - 1), 200) : rej(new Error("server never came up")); });
  };
  poke(tries);
});

/* The fixture pin, done at the server root.
 *
 * SYMLINKS, not copies: public/ carries megabytes of scan JSON and the entire
 * point is not to move it, and a symlinked tree cannot go stale against the
 * files it points at. `data` is the one entry that is redirected; everything
 * else -- js, css, fonts, html, icons, vendor -- is the real thing, because the
 * commit is what this gate exists to measure.
 *
 * A file with no fixture 404s naturally out of the fixtures directory, which is
 * exactly what screenshot-diff.e2e.js's route handler does for the same set. Do
 * not "helpfully" fall through to public/data for a missing one: that would put
 * the live scan JSON back inside the budget for whichever file happened to be
 * unfixtured, which is the bug wearing a smaller hat.
 */
function stageRoot() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "lh-root-"));
  for (const entry of fs.readdirSync(PUBLIC)) {
    if (entry === "data") continue;
    fs.symlinkSync(path.join(PUBLIC, entry), path.join(dir, entry));
  }
  fs.symlinkSync(FIXTURES, path.join(dir, "data"));
  return dir;
}

/* Unlink each entry explicitly, then rmdir. `fs.rmSync(recursive)` would also
 * be safe (it lstats, so it removes links rather than following them), but the
 * blast radius of being wrong about that is public/ and the fixture set, so the
 * staging dir is torn down one link at a time where it is obvious.
 */
function unstageRoot(dir) {
  if (!dir) return;
  try {
    for (const entry of fs.readdirSync(dir)) fs.unlinkSync(path.join(dir, entry));
    fs.rmdirSync(dir);
  } catch (_) { /* a leaked temp dir is not worth failing a gate over */ }
}

/* What the page would REALLY weigh, measured off the run that just happened.
 *
 * Every /data/ URL the page requested is mapped back to the real file under
 * public/ and stat()ed; everything else keeps the transfer size Lighthouse
 * measured. Requests are counted individually rather than deduped, to match
 * `total-byte-weight`'s own semantics.
 *
 * Returns null rather than a guess when the audit is not present, because a
 * fabricated payload figure is worse than an absent one -- this number exists
 * to be quoted at a product decision.
 */
function livePayload(audits) {
  const det = audits["network-requests"] && audits["network-requests"].details;
  const items = det && det.items;
  if (!Array.isArray(items) || !items.length) return null;
  let code = 0, servedData = 0, liveData = 0, requests = 0;
  const absent = new Set();
  for (const it of items) {
    let pathname;
    try { pathname = new URL(it.url).pathname; } catch (_) { continue; }
    const bytes = Number(it.transferSize) || 0;
    if (!pathname.startsWith("/data/")) { code += bytes; continue; }
    requests++;
    servedData += bytes;
    const real = path.resolve(PUBLIC, "." + pathname);
    if (!real.startsWith(PUBLIC + path.sep)) continue;
    try { liveData += fs.statSync(real).size; } catch (_) { absent.add(pathname); }
  }
  return { code, servedData, liveData, requests, absent: [...absent].sort() };
}

const CHROME = process.env.PW_CHROMIUM || process.env.CHROME_PATH || undefined;

(async () => {
  let lighthouse, launch;
  try {
    lighthouse = (await import("lighthouse")).default;
    ({ launch } = await import("chrome-launcher"));
  } catch (_) {
    try { lighthouse = (await import("/tmp/node_modules/lighthouse/core/index.js")).default;
      ({ launch } = await import("/tmp/node_modules/chrome-launcher/dist/index.js")); }
    catch (e) { console.error("lighthouse not installed:", e.message); process.exit(1); }
  }
  let root = null, srv = null, failures = 0;
  try {
    root = stageRoot();
    srv = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: root, stdio: "ignore" });
    await waitPort(PORT);
    const chrome = await launch({ chromePath: CHROME, chromeFlags: ["--headless=new", "--no-sandbox", "--disable-gpu"] });
    const runner = await lighthouse(URL_UNDER_TEST, { port: chrome.port, output: "json", logLevel: "error",
      onlyCategories: ["performance"], formFactor: "desktop", screenEmulation: { disabled: true } });
    await chrome.kill();
    const a = runner.lhr.audits;
    const cls = a["cumulative-layout-shift"].numericValue;
    const tti = a["interactive"].numericValue;
    const bytes = a["total-byte-weight"].numericValue;
    const check = (ok, label) => { console.log(`${ok ? "PASS" : "FAIL"}  ${label}`); if (!ok) failures++; };

    // GATED. Both numbers are functions of the COMMIT now: /data/ is pinned to
    // test/e2e/fixtures/data, so nothing a scheduled scan commits can move them.
    check(bytes < TRANSFER_BUDGET_MB * MB,
      `transfer ${(bytes / MB).toFixed(2)}MB < ${TRANSFER_BUDGET_MB.toFixed(1)}MB ` +
      `(fixture-pinned /data/, deterministic 1.86MB baseline - if this moved and no ` +
      `asset did, test/e2e/fixtures/data/ was refreshed)`);
    check(cls < CLS_BUDGET,
      `CLS ${cls.toFixed(3)} < ${CLS_BUDGET.toFixed(2)} ` +
      `(fixture-pinned, observed 0.123 across three runs after the #1 CLS pass)`);

    // INFORMATIONAL. TTI swings 2x on shared CI runners - reported, NOT gated,
    // so a noisy runner can't red-fail the build and re-trigger the emails.
    console.log(`INFO  TTI ${Math.round(tti)}ms · perf score ${Math.round(runner.lhr.categories.performance.score * 100)} (not gated — runner-variable)`);

    // INFORMATIONAL, and deliberately so. See the header: the real payload is a
    // product decision, not a reason to fail a push nobody can act on.
    const live = livePayload(a);
    if (!live) {
      console.log("INFO  live payload not measured (this run carries no network-requests audit)");
    } else {
      const estimate = live.code + live.liveData;
      console.log(
        `INFO  live payload ~${(estimate / MB).toFixed(2)}MB uncompressed = ` +
        `${(live.liveData / MB).toFixed(2)}MB real public/data across ${live.requests} request(s) + ` +
        `${(live.code / MB).toFixed(2)}MB code/assets ` +
        `(fixtures served ${(live.servedData / MB).toFixed(2)}MB here) — reported, NEVER gated`);
      if (live.absent.length) {
        console.log(`INFO  ${live.absent.length} /data/ path(s) requested with no file in public/: ${live.absent.join(", ")}`);
      }
      if (estimate > LIVE_PAYLOAD_WARN_MB * MB) {
        console.log(
          `::warning::Dashboard ships ~${(estimate / MB).toFixed(2)}MB uncompressed, past the ` +
          `${LIVE_PAYLOAD_WARN_MB.toFixed(1)}MB notice line (${(live.liveData / MB).toFixed(2)}MB of it committed ` +
          `scan data). This does NOT fail the build - slimming public/data/ is a product decision, not a CI fix.`);
      }
    }
    console.log(`\nperf score: ${Math.round(runner.lhr.categories.performance.score * 100)} (informational)`);
  } catch (e) {
    console.error("lighthouse run error:", e.message); failures++;
  } finally {
    if (srv) srv.kill();
    unstageRoot(root);
  }
  console.log(failures ? `\n${failures} budget FAILURE(S)` : "\nAll Lighthouse budgets passed");
  process.exit(failures ? 1 : 0);
})();
