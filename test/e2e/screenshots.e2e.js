/* Mobile screenshot matrix (UI backlog #40).
 *
 * Captures every key page at the three phone widths the owner actually uses
 * (360 / 390 / 430) so a human — or a future diffing step — can eyeball the
 * mobile layout each run. In CI these land as an uploaded artifact
 * (test.yml). Also asserts zero horizontal overflow at each width and fails
 * the run if any page overflows, so a regression can't slip through silently.
 *
 * Local: node test/e2e/screenshots.e2e.js  (writes to test/e2e/__shots__/)
 *   PW_CHROMIUM=/path/to/chromium to point at a prebuilt browser.
 */
const { spawn } = require("child_process");
const net = require("net");
const fs = require("fs");
const path = require("path");

let chromium;
try { ({ chromium } = require("playwright")); }
catch (_) { ({ chromium } = require("/home/claude/.npm-global/lib/node_modules/playwright")); }

const ROOT = path.join(__dirname, "..", "..", "public");
const OUT = path.join(__dirname, "__shots__");
const PORT = 8944;
const BASE = `http://localhost:${PORT}`;
const WIDTHS = [360, 390, 430];
const PAGES = ["index.html", "recommendations.html", "journal.html", "phasemap.html", "specs.html", "chart.html"];

const waitPort = (port, tries = 50) => new Promise((res, rej) => {
  const poke = (n) => {
    const s = net.connect(port, "127.0.0.1");
    s.once("connect", () => { s.destroy(); res(); });
    s.once("error", () => { s.destroy(); n ? setTimeout(() => poke(n - 1), 200) : rej(new Error("server never came up")); });
  };
  poke(tries);
});

let failures = 0;
(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const srv = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: ROOT, stdio: "ignore" });
  try {
    await waitPort(PORT);
    const opts = process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {};
    const browser = await chromium.launch(opts);
    for (const w of WIDTHS) {
      const ctx = await browser.newContext({ viewport: { width: w, height: 900 }, isMobile: true, hasTouch: true, serviceWorkers: "block" });
      const page = await ctx.newPage();
      await page.addInitScript(() => { try { localStorage.setItem("gbs:onboarded", "1"); } catch (_) {} });
      for (const pg of PAGES) {
        try {
          await page.goto(`${BASE}/${pg}`, { waitUntil: "domcontentloaded", timeout: 30000 });
          await page.waitForTimeout(1600);
          const over = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
          const name = `${pg.replace(".html", "")}_${w}.png`;
          await page.screenshot({ path: path.join(OUT, name), fullPage: false });
          console.log(`${over ? "OVERFLOW" : "ok  "}  ${name}`);
          if (over) failures++;
        } catch (e) {
          console.log(`ERROR   ${pg} @${w}: ${e.message}`);
          failures++;
        }
      }
      await ctx.close();
    }
    await browser.close();
  } finally {
    srv.kill();
  }
  console.log(failures ? `\n${failures} overflow/error(s)` : `\nAll ${WIDTHS.length * PAGES.length} shots captured, zero overflow`);
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error("matrix harness error:", e.message); process.exit(1); });
