// THROWAWAY diagnostic (2026-09-23): does the Momentum 4H chip load bars on
// ELS in PRODUCTION? Read-only: GETs the public site, writes nothing. Lives
// only on branch diag-els-4h-2026-09-23, which is deleted after the run.
const { chromium } = require("playwright");
const BASE = process.env.PROBE_BASE || "https://googy-boys-scanner.pages.dev";
// Hard stop: a probe that hangs tells nobody anything.
setTimeout(() => { console.log("WATCHDOG: probe exceeded 120s"); process.exit(0); }, 120000).unref();
let browser = null;
(async () => {
  browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 },
    isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  const prices = [], errs = [];
  page.on("pageerror", (e) => errs.push(String(e)));
  page.on("response", async (r) => {
    if (!r.url().includes("/api/price")) return;
    const row = { url: r.url().replace(BASE, ""), status: r.status() };
    try {
      const j = await r.json();
      const c = j.candles || [];
      Object.assign(row, { ok: j.ok, candles: c.length, bars: j.bars, degraded: j.degraded, basis: j.basis,
        first: c.length ? new Date(c[0].time * 1000).toISOString() : null,
        last: c.length ? new Date(c[c.length - 1].time * 1000).toISOString() : null });
    } catch (e) { row.parse = String(e); }
    prices.push(row);
  });
  // NOT networkidle: the page polls a live quote, so the network may never go
  // quiet. The timeframe buttons render only after BOTH the daily and the
  // hourly pulls resolve (momentumFallback -> intradayP -> render), so their
  // appearance is the real "loaded" signal.
  const t0 = Date.now();
  await page.goto(BASE + "/chart.html?s=ELS&m=asx&src=momentum", { waitUntil: "domcontentloaded", timeout: 60000 });
  try {
    await page.waitForSelector("#tf-toggle .tf-btn[data-tf]", { timeout: 70000 });
    console.log("tf buttons rendered after", Date.now() - t0, "ms");
  } catch (e) { console.log("tf buttons NEVER rendered within 70s:", String(e).slice(0, 160)); }
  await page.waitForTimeout(1500);
  const read = () => page.evaluate(() => ({
    chartJs: (document.querySelector('script[src*="js/chart.js"]') || {}).src || null,
    buttons: [...document.querySelectorAll("#tf-toggle .tf-btn[data-tf]")]
      .map((b) => b.dataset.tf + (b.classList.contains("is-active") ? "*" : "")),
    chip: ((document.querySelector(".mom-bars") || {}).textContent || "").trim() || null,
    notice: ((document.querySelector(".tf-notice") || {}).textContent || "").trim().slice(0, 200) || null,
    foot: ((document.querySelector(".chart-foot") || {}).innerText || "").replace(/\s+/g, " ").trim().slice(0, 400),
  }));
  const before = await read();
  console.log("BEFORE", JSON.stringify(before, null, 1));
  if (before.buttons.some((b) => b.startsWith("4H"))) {
    await page.tap('#tf-toggle .tf-btn[data-tf="4H"]');
    await page.waitForTimeout(2000);
    console.log("AFTER 4H TAP", JSON.stringify(await read(), null, 1));
  } else {
    console.log("NO 4H BUTTON on the live page");
  }
  console.log("PRICE RESPONSES", JSON.stringify(prices, null, 1));
  console.log("PAGE ERRORS", JSON.stringify(errs));
})().catch((e) => { console.log("PROBE FAILED", String(e)); })
  .finally(async () => { try { if (browser) await browser.close(); } catch (_) {} process.exit(0); });
