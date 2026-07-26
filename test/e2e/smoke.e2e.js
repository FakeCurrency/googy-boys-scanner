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
      // UX #3: mark as already-onboarded so the first-visit tour scrim never
      // intercepts the suite's clicks.
      await page.addInitScript(() => { try { localStorage.setItem("gbs:onboarded", "1"); } catch (_) {} });
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

    // #57: input-latency budget — the synchronous cost of a sort interaction
    // (buildList + first-chunk paint) on the largest list must stay snappy.
    await page.evaluate(() => { const b = document.querySelector('.market-btn[data-market="nasdaq"]'); if (b) b.click(); });
    await page.waitForTimeout(1500);
    const nRows = await page.$$eval(".row-wrap", (n) => n.length);
    const sortMs = await page.evaluate(() => {
      const t0 = performance.now();
      document.getElementById("sort-cycle").click();   // sync handler → first-chunk render
      return performance.now() - t0;
    });
    check(sortMs < 80, `sort interaction paints fast on ${nRows} rows (${sortMs.toFixed(1)}ms sync, budget 80)`);
    await page.context().close();

    // ── Recommendations page ─────────────────────────────────────────────
    page = await newPage({ width: 1500, height: 950 });
    await page.goto(`${BASE}/recommendations.html`, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForSelector(".rec-card", { timeout: 30000 });
    const recCards = await page.$$eval(".rec-card", (n) => n.length);
    check(recCards >= 3, `recommendations market cards render (${recCards})`);
    await page.context().close();

    // Wait until a list's rendered count settles (async fetch + render) so the
    // filter assertions can't race a still-painting page — flaky e2e = red CI
    // runs = failure emails, which we do not ship.
    const settledCount = async (pg, sel) => {
      let last = -1, stable = 0;
      for (let i = 0; i < 40; i++) {           // up to ~8s
        const n = await pg.$$eval(sel, (els) => els.length).catch(() => 0);
        if (n === last && n > 0) { if (++stable >= 3) return n; } else { stable = 0; last = n; }
        await pg.waitForTimeout(200);
      }
      return last;
    };

    // ── Specs page (#24): paints rows + grade filter narrows ─────────────
    // DATA-AWARE (2026-07-26): the Specs gates are strict — a session can
    // legitimately pass ZERO setups (both spec files were empty after Friday's
    // close, which timed this block out and red-failed the run). The correct
    // behaviour with empty data is the EMPTY STATE, so that's what's asserted
    // when the committed JSON has no results; the row assertions only run when
    // there is data to paint. A quiet market must never fail CI.
    const specData = (() => {
      try { return require(path.join(ROOT, "data", "asx_spec.json")); } catch (_) { return null; }
    })();
    const specN = ((specData && specData.results) || []).length;
    page = await newPage({ width: 1500, height: 950 });
    await page.goto(`${BASE}/specs.html`, { waitUntil: "networkidle", timeout: 30000 });
    if (specN === 0) {
      await page.waitForSelector("#sp-list .placeholder", { timeout: 30000 });
      check(true, "specs: committed data has 0 setups — empty state renders (correct)");
    } else {
      await page.waitForSelector("#sp-list .row-wrap", { timeout: 30000 });
      const spBefore = await settledCount(page, "#sp-list .row-wrap");
      check(spBefore > 0, `specs page paints rows (${spBefore})`);
      const spGrade = await page.$("#sp-grade-filter .seg-btn[data-grade='A+']");
      if (spGrade) {
        await spGrade.click();
        await page.waitForTimeout(500);
        const spAfter = await page.$$eval("#sp-list .row-wrap", (n) => n.length);
        check(spAfter <= spBefore, `specs grade filter narrows (${spBefore} → ${spAfter})`);
      } else { check(false, "specs A+ grade filter present"); }
    }
    await page.context().close();

    // ── PhaseMap page (#24): paints cards + tier filter narrows ──────────
    page = await newPage({ width: 1500, height: 950 });
    await page.goto(`${BASE}/phasemap.html`, { waitUntil: "networkidle", timeout: 30000 });
    await page.waitForSelector("#pm-list .pm-card", { timeout: 30000 });
    const pmBefore = await settledCount(page, "#pm-list .pm-card");
    check(pmBefore > 0, `phasemap page paints cards (${pmBefore})`);
    const pmTier = await page.$("#pm-tier-filter .pm-chip[data-tier='A+']");
    if (pmTier) {
      await pmTier.click();
      await page.waitForTimeout(500);
      const pmAfter = await page.$$eval("#pm-list .pm-card", (n) => n.length);
      check(pmAfter <= pmBefore, `phasemap tier filter narrows (${pmBefore} → ${pmAfter})`);
    } else { check(false, "phasemap A+ tier filter present"); }
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
