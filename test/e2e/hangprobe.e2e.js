/* Hang-probe (owner-ruled, 2026-07-31) — the permanent e2e for Phase B.
 *
 * A NETWORK FAILURE rejects and every cold-load catch path handles it. A HUNG
 * connection neither resolves nor rejects, and before 2026-07-29 it stranded
 * the deck on "Loading latest scan…" forever — no rejection to catch, nothing
 * for a unit test to slice, only a real browser waiting on a socket that will
 * never speak. Phase B's answer was an AbortSignal.timeout on every data
 * fetch (PM.DATA_FETCH_TIMEOUT_MS = 20s, plus the inline twin in index.html's
 * head-start preload). THIS file is the proof that the answer still works: it
 * HOLDS the deck's market payload request open — Playwright route handler
 * that never fulfills, a genuinely hung connection, not a fast error dressed
 * as one — and asserts in a real browser that:
 *
 *   1. the deck shows the honest loading state while the hang is live
 *      (skeleton + "Loading latest scan…", no premature error),
 *   2. the timeout actually fires and the REAL retry state appears — the
 *      "Tap to retry" button (#retry-load), wired, and only after at least
 *      one full timeout window has genuinely elapsed,
 *   3. the rest of the page stays usable: the market switch paints another
 *      market's rows from fixtures while the hung request is still pending,
 *      and the nav is intact,
 *   4. zero uncaught page errors — every abort lands in a handled catch.
 *
 * The >= 19s lower bound on the retry's arrival is load-bearing: if the retry
 * state ever shows up FASTER than a timeout window, this probe is no longer
 * testing a hang (someone made the route abort, or a refactor turned the hang
 * into a fast failure) and it fails rather than quietly testing less than it
 * claims. Expected arrival is ~40s — the preload burns its own 20s window
 * (resolving null), then app.js's own fetch burns another. That wall-clock
 * wait is the point: the timeout under test is real, not mocked.
 *
 * TEST-ONLY by ruling: no production fetch logic is touched. /data/ is served
 * from test/e2e/fixtures (the same set lighthouse + screenshot-diff pin), so
 * the usability assertion can never fail on a quiet live tape.
 *
 * CI: test.yml's e2e job runs this file. Local:
 *   PW_CHROMIUM=/opt/pw-browsers/chromium node test/e2e/hangprobe.e2e.js
 */
const { spawn } = require("child_process");
const fs = require("fs");
const net = require("net");
const path = require("path");

let chromium;
try { ({ chromium } = require("playwright")); }
catch (_) { ({ chromium } = require("/home/claude/.npm-global/lib/node_modules/playwright")); }

const PUBLIC = path.join(__dirname, "..", "..", "public");
const FIXTURES = path.join(__dirname, "fixtures");
const PORT = 8947;
const BASE = `http://localhost:${PORT}`;
const HUNG_FILE = "nasdaq_vivek.json";   // the deck's cold-load payload for ?m=nasdaq
// NASDAQ is hung (its fixture is a stub anyway); ASX is the usability
// market because it is the one fixture with real rows (204) to paint.

const waitPort = (port, tries = 50) => new Promise((res, rej) => {
  const poke = (n) => {
    const s = net.connect(port, "127.0.0.1");
    s.once("connect", () => { s.destroy(); res(); });
    s.once("error", () => { s.destroy(); n ? setTimeout(() => poke(n - 1), 200) : rej(new Error("server never came up")); });
  };
  poke(tries);
});

let failures = 0;
const check = (ok, label) => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}`);
  if (!ok) failures++;
};

(async () => {
  const srv = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"],
    { cwd: PUBLIC, stdio: "ignore" });
  let browser;
  try {
    await waitPort(PORT);
    const opts = process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {};
    browser = await chromium.launch(opts);
    // serviceWorkers blocked, same as smoke: SW-initiated fetches bypass
    // ctx.route in Playwright, and a cache-serving SW would let the page dodge
    // the very hang this probe exists to inject.
    const ctx = await browser.newContext({ viewport: { width: 1500, height: 950 }, serviceWorkers: "block" });
    const pageErrors = [];
    let hung = 0;

    // /data/ pinned to fixtures — EXCEPT the market payload under test, whose
    // requests are held open forever. Never fulfilled, never aborted: the
    // socket-that-never-speaks case, which is the one a fast error cannot
    // stand in for.
    await ctx.route("**/data/**", (route) => {
      const rel = new URL(route.request().url()).pathname.replace(/^\/+/, "");
      if (rel.endsWith("/" + HUNG_FILE) || rel === "data/" + HUNG_FILE) { hung++; return; }
      const fix = path.join(FIXTURES, rel);
      if (fs.existsSync(fix)) {
        route.fulfill({ status: 200, contentType: "application/json", body: fs.readFileSync(fix) });
      } else {
        route.fulfill({ status: 404, contentType: "text/plain", body: "no fixture" });
      }
    });

    const page = await ctx.newPage();
    await page.addInitScript(() => {
      try {
        localStorage.setItem("gbs:onboarded", "1");   // tour scrim off
        localStorage.setItem("gbs:prefs", JSON.stringify({ market: "nasdaq" }));
      } catch (_) {}
    });
    page.on("pageerror", (e) => pageErrors.push(`${page.url()}: ${e.message}`));

    // ── 1. the hang is live: honest loading state, no premature error ─────
    const t0 = Date.now();
    await page.goto(`${BASE}/index.html?m=nasdaq`, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForTimeout(2500);
    const mid = await page.evaluate(() => ({
      title: document.getElementById("scan-title").textContent,
      skeletons: document.querySelectorAll("#results .skeleton").length,
      rows: document.querySelectorAll(".row-wrap").length,
      retry: !!document.getElementById("retry-load"),
      marketBtns: document.querySelectorAll(".market-switch .market-btn").length,
    }));
    check(/Loading latest scan/.test(mid.title), `mid-hang: honest loading title ("${mid.title}")`);
    check(mid.skeletons === 8, `mid-hang: skeleton placeholders render (${mid.skeletons})`);
    check(mid.rows === 0 && !mid.retry, "mid-hang: no rows painted, no premature retry state");
    check(mid.marketBtns === 3, "mid-hang: page shell alive (market switch rendered)");
    check(hung >= 1, `the hung route is really being exercised (${hung} request(s) held)`);

    // ── 2. the timeout fires; the real retry state appears ────────────────
    await page.waitForSelector("#retry-load", { timeout: 60000 });
    const elapsed = Date.now() - t0;
    const failState = await page.evaluate(() => ({
      title: document.getElementById("scan-title").textContent,
      h3: (document.querySelector("#results .placeholder h3") || {}).textContent || "",
      btnText: document.getElementById("retry-load").textContent.trim(),
      btnClass: document.getElementById("retry-load").className,
    }));
    check(elapsed >= 19000,
      `the retry state waited for a REAL timeout window (${(elapsed / 1000).toFixed(1)}s >= 19s — ` +
      "faster would mean the probe is no longer testing a hang)");
    check(/Couldn't load the scan/.test(failState.title), `failure title ("${failState.title}")`);
    check(/Couldn't reach the NASDAQ data/.test(failState.h3), `failure names the market ("${failState.h3}")`);
    check(failState.btnText === "Tap to retry", `the button is the real one ("${failState.btnText}")`);
    check(/pm-retry/.test(failState.btnClass), "the button carries the shared .pm-retry control class");
    check(hung >= 2, `both the head-start preload and the app fetch hit the hang (${hung} held)`);

    // ── 3. the retry button is genuinely wired ────────────────────────────
    await page.click("#retry-load");
    await page.waitForFunction(
      () => /Loading latest scan/.test(document.getElementById("scan-title").textContent),
      { timeout: 5000 });
    check(true, "Tap to retry re-enters the loading state (button is wired to load())");

    // ── 4. the rest of the page is usable while the hang is still live ────
    const navLinks = await page.evaluate(() => document.querySelectorAll("#site-nav a").length);
    check(navLinks > 0, `site nav is intact in the failure state (${navLinks} links)`);
    await page.click('.market-switch .market-btn[data-market="asx"]');
    await page.waitForSelector(".row-wrap", { timeout: 15000 });
    const other = await page.evaluate(() => ({
      title: document.getElementById("scan-title").textContent,
      rows: document.querySelectorAll(".row-wrap").length,
      pills: document.querySelectorAll("#deck-pills .fpill").length,
    }));
    check(other.rows > 0, `market switch paints ASX fixture rows mid-hang (${other.rows})`);
    check(!/Couldn't load|Loading latest scan/.test(other.title),
      `ASX shows a real scan title ("${other.title.slice(0, 40)}…")`);
    check(other.pills >= 3, `deck pills recover with the working market (${other.pills})`);

    check(pageErrors.length === 0,
      `zero uncaught page errors — every abort was handled (${pageErrors.length ? pageErrors.join(" | ") : "clean"})`);

    await browser.close();
  } catch (e) {
    console.error("FAIL  hang-probe crashed:", e.message);
    failures++;
    if (browser) await browser.close().catch(() => {});
  } finally {
    srv.kill();
  }
  console.log(failures ? `\n${failures} HANG-PROBE CHECK(S) FAILED` : "\nALL HANG-PROBE CHECKS PASSED");
  process.exit(failures ? 1 : 0);
})();
