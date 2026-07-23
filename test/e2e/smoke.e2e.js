/* E2E smoke (UI backlog #8) — plain Node + Playwright, no test runner.
 *
 * Serves public/ statically, then walks the flows a human hits daily:
 *   1. deck paints (title + filter pills from committed scan data)
 *   2. pill filtering (⨂ Multi-lens click-to-filter narrows the list)
 *   3. row expand (horizontal SL→IN→TP1→TP2→TP3 ladder renders)
 *   4. sort control (label cycles, arrow flips)
 *   5. recommendations page (market cards render)
 *   6. 390px mobile: zero horizontal overflow, toolbar + price visible
 * Any uncaught page error on any page fails the run.
 *
 * CI: test.yml installs playwright + chromium and runs this file.
 * Local: set PW_CHROMIUM=/path/to/chromium if playwright's own browser
 * download is unavailable.
 */
const { spawn } = require("child_process");
const net = require("net");
const path = require("path");

let chromium;
try { ({ chromium } = require("playwright")); }
catch (_) { ({ chromium } = require("/home/claude/.npm-global/lib/node_modules/playwright")); }

const ROOT = path.join(__dirname, "..", "..", "public");
const PORT = 8943;
const BASE = `http://localhost:${PORT}`;

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
  const srv = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: ROOT, stdio: "ignore" });
  try {
    await waitPort(PORT);
    const opts = process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {};
    const browser = await chromium.launch(opts);
    const pageErrors = [];
    const newPage = async (vp) => {
      const ctx = await browser.newContext({ viewport: vp, serviceWorkers: "block" });
      const page = await ctx.newPage();
      page.on("pageerror", (e) => pageErrors.push(`${vp.width}px ${page.url()}: ${e.message}`));
      return page;
    };

    // ── Desktop dashboard ────────────────────────────────────────────────
    let page = await newPage({ width: 1500, height: 950 });
    await page.goto(`${BASE}/index.html`, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForSelector(".row-wrap", { timeout: 30000 });

    // 1. deck paint
    const deck = await page.evaluate(() => ({
      title: document.getElementById("scan-title").textContent,
      pills: document.querySelectorAll("#deck-pills .fpill").length,
    }));
    check(!/Loading latest scan/.test(deck.title), `deck paints a real title ("${deck.title.slice(0, 40)}…")`);
    check(deck.pills >= 3, `deck filter pills render (${deck.pills})`);

    // 2. pill filtering — ⨂ Multi-lens narrows (or at minimum activates)
    const before = await page.$$eval(".row-wrap", (n) => n.length);
    await page.click('#deck-pills [data-pill="confl"]');
    await page.waitForTimeout(400);
    const after = await page.$$eval(".row-wrap", (n) => n.length);
    const pillActive = await page.$eval('#deck-pills [data-pill="confl"]', (b) => b.classList.contains("is-active"));
    check(pillActive && after <= before, `multi-lens pill filters the list (${before} → ${after})`);
    await page.click('#deck-pills [data-pill="confl"]');
    await page.waitForTimeout(300);

    // 3. expand → horizontal ladder
    await page.click(".row-wrap .row-expand");
    await page.waitForSelector(".vk-ladder-h .vk-cell", { timeout: 10000 });
    const keys = await page.$$eval(".vk-ladder-h .vk-cell-key", (els) => els.map((e) => e.textContent.trim().replace(/\s*→$/, "")));
    check(JSON.stringify(keys) === JSON.stringify(["SL", "IN", "TP1", "TP2", "TP3"]), `ladder cells in trade order (${keys.join(" → ")})`);
    const chks = await page.$$eval(".vk-checks .vk-chk", (n) => n.length);
    check(chks === 6, `checklist renders as 6 chips (${chks})`);

    // 4. sort control — label cycles, arrow flips
    const s0 = await page.$eval("#sort-cycle", (b) => b.textContent);
    await page.click("#sort-cycle");
    const s1 = await page.$eval("#sort-cycle", (b) => b.textContent);
    const d0 = await page.$eval("#sort-dir", (b) => b.textContent);
    await page.click("#sort-dir");
    const d1 = await page.$eval("#sort-dir", (b) => b.textContent);
    check(s0 !== s1, `sort label cycles (${s0} → ${s1})`);
    check(d0 !== d1, `sort direction flips (${d0} → ${d1})`);
    const rowsAfterSort = await page.$$eval(".row-wrap", (n) => n.length);
    check(rowsAfterSort > 0, `rows still render after sorting (${rowsAfterSort})`);
    await page.context().close();

    // ── Recommendations page ─────────────────────────────────────────────
    page = await newPage({ width: 1500, height: 950 });
    await page.goto(`${BASE}/recommendations.html`, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForSelector(".rec-card", { timeout: 30000 });
    const recCards = await page.$$eval(".rec-card", (n) => n.length);
    check(recCards >= 3, `recommendations market cards render (${recCards})`);
    await page.context().close();

    // ── 390px mobile dashboard ───────────────────────────────────────────
    page = await newPage({ width: 390, height: 844 });
    await page.goto(`${BASE}/index.html`, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForSelector(".row-wrap", { timeout: 30000 });
    const mob = await page.evaluate(() => ({
      overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      toolbar: !!document.getElementById("toolbar"),
      priceVisible: (() => {
        const el = document.querySelector(".row-price .rprice");
        if (!el) return false;
        const b = el.getBoundingClientRect();
        return b.width > 0 && b.right <= innerWidth;
      })(),
    }));
    check(!mob.overflowX, "mobile 390px: no horizontal page overflow");
    check(mob.toolbar, "mobile 390px: toolbar present");
    check(mob.priceVisible, "mobile 390px: row price fully visible");
    await page.context().close();

    // ── 320px (narrowest phone) zero-overflow guard across pages (#38) ───────
    for (const path of ["index.html", "recommendations.html", "phasemap.html", "specs.html", "journal.html"]) {
      const pg = await newPage({ width: 320, height: 720 });
      await pg.goto(`${BASE}/${path}`, { waitUntil: "domcontentloaded", timeout: 30000 });
      await pg.waitForTimeout(1200);   // let the app paint
      const over = await pg.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
      check(!over, `320px: no horizontal overflow on ${path}`);
      await pg.context().close();
    }

    await browser.close();

    // ── Page errors gate ─────────────────────────────────────────────────
    check(pageErrors.length === 0, pageErrors.length ? `page errors:\n  ${pageErrors.join("\n  ")}` : "zero uncaught page errors");
  } finally {
    srv.kill();
  }
  console.log(failures ? `\n${failures} FAILURE(S)` : "\nALL E2E CHECKS PASSED");
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error("E2E harness error:", e.message); process.exit(1); });
