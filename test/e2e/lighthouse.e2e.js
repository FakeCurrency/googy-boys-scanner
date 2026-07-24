/* Lighthouse budget gate (UI backlog #70).
 *
 * Runs Lighthouse against the dashboard served from public/ and fails the CI
 * run if layout stability or interactivity regress past a budget. Thresholds
 * are deliberately GENEROUS on the timing metric (CI runners are noisy, and a
 * flaky perf gate would just resurrect the failure-email problem we killed) —
 * they catch an egregious regression, not a 200ms jitter. CLS is near-
 * deterministic (self-hosted fonts → ~0) so it gets a tight budget.
 *
 * These run against an UNCOMPRESSED python http.server (no CDN, no brotli, no
 * HTTP/2) with the full ~1.5MB scan JSON and the 30s live tickers running —
 * so the absolute numbers are pessimistic vs the Cloudflare-served reality.
 * The budgets are therefore REGRESSION TRIPWIRES sized above today's baseline:
 * they catch an egregious regression (a huge blocking script, a runaway
 * payload) without false-failing on runner noise. The page is loaded with
 * ?lite=1 (measurement mode) so the idle prefetch + background polls don't
 * land inside the trace at random. That makes TRANSFER deterministic (pins at
 * 3.50MB — the ~1.6MB prefetch swing is gone). CLS still swings 0.55–1.06 from
 * the core async data-paint (not suppressible without touching render logic),
 * so its gate carries CI headroom above that max. TTI swings 9–20s run-to-run
 * and stays informational.
 * NOTE: CLS in the 0.5–1.0 band is a real finding flagged for a dedicated pass
 * — this gate makes it visible + stops it getting WORSE; it doesn't claim it's
 * fixed.
 *
 * Budgets:
 *   total transfer weight    < 5.0 MB  (tight — deterministic 3.50MB baseline)
 *   cumulative-layout-shift  < 1.60    (tripwire above the ~1.06 observed max)
 *   interactive (TTI)        INFO only (swings 9–20s on a local server)
 *
 * Local: node test/e2e/lighthouse.e2e.js   (PW_CHROMIUM points at chromium)
 */
const { spawn } = require("child_process");
const net = require("net");
const path = require("path");

const ROOT = path.join(__dirname, "..", "..", "public");
const PORT = 8945;
// ?lite=1 puts app.js in measurement mode: no idle cross-market prefetch, no
// auto-refresh countdown, no background polls. That makes total-byte-weight +
// CLS DETERMINISTIC (they otherwise swing run-to-run as deferred work lands
// inside the trace at random) so the budget is a real tripwire, not a dice
// roll that would resurrect the flaky failure-emails.
const URL = `http://localhost:${PORT}/index.html?lite=1`;

const waitPort = (port, tries = 50) => new Promise((res, rej) => {
  const poke = (n) => {
    const s = net.connect(port, "127.0.0.1");
    s.once("connect", () => { s.destroy(); res(); });
    s.once("error", () => { s.destroy(); n ? setTimeout(() => poke(n - 1), 200) : rej(new Error("server never came up")); });
  };
  poke(tries);
});

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
  const srv = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: ROOT, stdio: "ignore" });
  let failures = 0;
  try {
    await waitPort(PORT);
    const chrome = await launch({ chromePath: CHROME, chromeFlags: ["--headless=new", "--no-sandbox", "--disable-gpu"] });
    const runner = await lighthouse(URL, { port: chrome.port, output: "json", logLevel: "error",
      onlyCategories: ["performance"], formFactor: "desktop", screenEmulation: { disabled: true } });
    await chrome.kill();
    const a = runner.lhr.audits;
    const cls = a["cumulative-layout-shift"].numericValue;
    const tti = a["interactive"].numericValue;
    const bytes = a["total-byte-weight"].numericValue;
    const check = (ok, label) => { console.log(`${ok ? "PASS" : "FAIL"}  ${label}`); if (!ok) failures++; };
    // GATED. Transfer is deterministic in ?lite mode (tight budget); CLS still
    // has runner variance so its budget is a looser tripwire above the max.
    check(bytes < 5.0 * 1024 * 1024, `transfer ${(bytes / 1024 / 1024).toFixed(2)}MB < 5.0MB (deterministic ~3.50)`);
    check(cls < 1.60, `CLS ${cls.toFixed(3)} < 1.60 (observed max ~1.06)`);
    // INFORMATIONAL (TTI swings 2x on shared CI runners — reported, NOT gated,
    // so a noisy runner can't red-fail the build and re-trigger the emails).
    console.log(`INFO  TTI ${Math.round(tti)}ms · perf score ${Math.round(runner.lhr.categories.performance.score * 100)} (not gated — runner-variable)`);
    console.log(`\nperf score: ${Math.round(runner.lhr.categories.performance.score * 100)} (informational)`);
  } catch (e) {
    console.error("lighthouse run error:", e.message); failures++;
  } finally {
    srv.kill();
  }
  console.log(failures ? `\n${failures} budget FAILURE(S)` : "\nAll Lighthouse budgets passed");
  process.exit(failures ? 1 : 0);
})();
