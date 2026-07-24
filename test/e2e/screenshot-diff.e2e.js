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
  let failures = 0, created = 0, diffed = 0;
  try {
    await waitPort(PORT);
    const opts = process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM }
      : process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {};
    const browser = await chromium.launch(opts);
    for (const [name, page, w, h] of VIEWS) {
      const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1, reducedMotion: "reduce" });
      const p = await ctx.newPage();
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
  console.log(`\n${created} baselined, ${diffed} compared, ${failures} failure(s)`);
  process.exit(failures ? 1 : 0);
})();
