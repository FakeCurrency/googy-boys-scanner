// THROWAWAY production smoke (2026-09-23 sweep, S1). Read-only GETs of the
// public site; writes results + screenshots into diag/sweep/ on this branch only.
const { chromium } = require("playwright");
const fs = require("fs");
const BASE = process.env.PROBE_BASE || "https://googy-boys-scanner.pages.dev";
const OUT = "diag/sweep"; fs.mkdirSync(OUT, { recursive: true });
setTimeout(() => { console.log("WATCHDOG"); finish(); }, 420000).unref();
const results = [];
const rec = (page, check, pass, detail) => { results.push({ page, check, pass: !!pass, detail: String(detail) }); console.log(pass ? "PASS" : "FAIL", page, "|", check, "|", detail); };
let browser;
const num = (re, s) => { const m = re.exec(s || ""); return m ? +m[1] : NaN; };
const near = (a, b, tol) => Number.isFinite(a) && Math.abs(a - b) <= tol;
async function finish() {
  fs.writeFileSync(`${OUT}/results.json`, JSON.stringify({ base: BASE, at: new Date().toISOString(), pass: results.filter((r) => r.pass).length, fail: results.filter((r) => !r.pass).length, results }, null, 1) + "\n");
  try { if (browser) await browser.close(); } catch (_) {}
  process.exit(0);
}
(async () => {
  browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
  const open = async (url, vp) => {
    const ctx = await browser.newContext(vp === "desk" ? { viewport: { width: 1400, height: 950 } } : { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const page = await ctx.newPage(); const errs = [];
    await page.addInitScript(() => { try { localStorage.setItem("gbs:onboarded", "1"); } catch (_) {} });
    page.on("pageerror", (e) => errs.push(String(e).slice(0, 200)));
    await page.goto(BASE + url, { waitUntil: "domcontentloaded", timeout: 60000 });
    return { ctx, page, errs };
  };
  // served build vs this branch's HTML
  try {
    const r = await (await fetch(BASE + "/version.json", { cache: "no-store" })).json();
    rec("deploy", "version.json served", !!r.version, r.version);
  } catch (e) { rec("deploy", "version.json served", false, e); }

  // ── / 5.0 deck ──
  for (const vp of ["desk", "phone"]) {
    const P = `deck ${vp}`;
    const { ctx, page, errs } = await open("/index.html", vp);
    await page.waitForSelector(".row-wrap", { timeout: 60000 }).catch(() => {});
    await page.waitForTimeout(1500);
    const r = await page.evaluate(() => ({
      title: (document.getElementById("scan-title") || {}).textContent || "",
      pills: document.querySelectorAll("#deck-pills .fpill").length,
      rows: document.querySelectorAll(".row-wrap").length,
      aplus: [...document.querySelectorAll(".row-wrap .row-grade")].filter((g) => /^A\+/.test(g.textContent.trim())).length,
      over: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    }));
    rec(P, "deck title painted (not loading)", r.title && !/Loading latest scan/.test(r.title), r.title.slice(0, 80));
    rec(P, "filter pills (.fpill) >= 3", r.pills >= 3, r.pills);
    rec(P, "A+ cards present", r.aplus > 0, `${r.aplus} A+ of ${r.rows} rows`);
    if (vp === "phone") rec(P, "no horizontal overflow", !r.over, r.over);
    rec(P, "no page error", errs.length === 0, errs.join(" ; ") || "none");
    await page.screenshot({ path: `${OUT}/deck-${vp}.png` });
    await ctx.close();
  }

  // ── /momentum ASX + NASDAQ ──
  for (const m of ["asx", "nasdaq"]) {
    const P = `momentum ${m}`;
    const { ctx, page, errs } = await open(`/momentum.html?m=${m}`);
    await page.waitForFunction(() => !/loading/i.test((document.getElementById("mo-title") || {}).textContent || "loading"), null, { timeout: 45000 }).catch(() => {});
    await page.waitForTimeout(1500);
    const r = await page.evaluate(() => ({
      title: (document.getElementById("mo-title") || {}).textContent || "",
      sub: (document.getElementById("mo-sub") || {}).textContent || "",
      rows: document.querySelectorAll(".mo-row").length,
      hrefs: [...document.querySelectorAll("a.mo-sym")].map((a) => a.getAttribute("href")),
      fpills: [...document.querySelectorAll(".fpill")].map((b) => b.textContent.trim()),
      fpillB: document.querySelectorAll(".fpill b").length,
      deckPill: document.querySelectorAll(".deck-pill").length,
      fpillRadius: (() => { const b = document.querySelector(".fpill"); return b ? getComputedStyle(b).borderRadius : ""; })(),
      over: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    }));
    const n = num(/MOMENTUM · (\d+)/, r.title);
    rec(P, "no page error", errs.length === 0, errs.join(" ; ") || "none");
    rec(P, "header: title + scanned/gated/last bar", /MOMENTUM ·/.test(r.title) && /scanned/.test(r.sub) && /gated/.test(r.sub) && /last bar \d{4}-\d{2}-\d{2}/.test(r.sub), `${r.title} || ${r.sub}`);
    rec(P, "pills are .fpill with <b> count, no .deck-pill", r.fpills.length >= 1 && r.fpillB === r.fpills.length && r.deckPill === 0, `${r.fpills.join(" | ")} (radius ${r.fpillRadius})`);
    rec(P, "cards = header count", Number.isFinite(n) && r.rows === n, `header ${n}, .mo-row ${r.rows}`);
    rec(P, "every card link ?s=...&src=momentum, never ?symbol=", r.hrefs.length === r.rows && r.hrefs.every((h) => /[?&]s=/.test(h) && /src=momentum/.test(h) && !/[?&]symbol=/.test(h)), `${r.hrefs.length} links, e.g. ${r.hrefs[0] || "-"}`);
    rec(P, "no horizontal overflow", !r.over, r.over);
    await page.screenshot({ path: `${OUT}/momentum-${m}.png` });
    await ctx.close();
  }

  // ── ELS Momentum chart, D + 4H ──
  const readChart = (page) => page.evaluate(() => {
    const txt = (sel) => ((document.querySelector(sel) || {}).innerText || "").replace(/\s+/g, " ").trim();
    return { chartJs: (document.querySelector('script[src*="js/chart.js"]') || {}).src || "",
      tfs: [...document.querySelectorAll("#tf-toggle .tf-btn[data-tf]")].map((b) => b.dataset.tf + (b.classList.contains("is-active") ? "*" : "")),
      chip: txt(".mom-bars"), panes: document.querySelectorAll(".mom-pane").length,
      metrics: txt("#cf-metrics"), top: txt(".chart-top"), legend: txt("#chart-legend"),
      pm: !!document.querySelector(".pm-chart-strip"), back: (document.querySelector(".back-link") || {}).getAttribute?.("href") || "" };
  });
  const lv = (s) => ({ e: num(/Entry\s*A\$([\d.]+)/i, s), sl: num(/SL\s*A\$([\d.]+)/i, s), t1: num(/TP1\s*A\$([\d.]+)/i, s), t2: num(/TP2\s*A\$([\d.]+)/i, s), t3: num(/TP3\s*A\$([\d.]+)/i, s) });
  {
    const P = "ELS momentum chart";
    const { ctx, page, errs } = await open("/chart.html?s=ELS&m=asx&src=momentum");
    await page.waitForSelector("#tf-toggle .tf-btn[data-tf]", { timeout: 70000 }).catch(() => {});
    await page.waitForTimeout(2000);
    const d = await readChart(page);
    const D = lv(d.metrics);
    rec(P, "serves chart.js >= v123", num(/chart\.js\?v=(\d+)/, d.chartJs) >= 123, d.chartJs.replace(BASE, ""));
    rec(P, "D: SHORT", /SHORT/.test(d.metrics), d.metrics.slice(0, 60));
    rec(P, "D: 5.88/6.76/4.998/4.116/3.234 +-0.01", near(D.e, 5.88, 0.01) && near(D.sl, 6.762, 0.01) && near(D.t1, 4.998, 0.01) && near(D.t2, 4.116, 0.01) && near(D.t3, 3.234, 0.01), JSON.stringify(D));
    rec(P, "D: 3 panes (price + MACD + RSI)", d.panes === 2, `${d.panes} oscillator panes`);
    rec(P, "D: bars chip", /\d+ daily bars/.test(d.chip), d.chip);
    rec(P, "D: no SCORE 0/8", !/SCORE\s*0\s*\/\s*8/i.test(d.metrics + " " + d.top), d.metrics.slice(0, 160));
    rec(P, "D: no PhaseMap without ?pm=1", !d.pm && !/phasemap/i.test(d.top + " " + d.legend), `pm strip ${d.pm}`);
    rec(P, "back-link -> momentum.html", /momentum\.html/.test(d.back), d.back);
    await page.screenshot({ path: `${OUT}/els-D.png` });
    if (d.tfs.some((t) => t.startsWith("4H"))) {
      await page.tap('#tf-toggle .tf-btn[data-tf="4H"]'); await page.waitForTimeout(2000);
      const x = await readChart(page); const H = lv(x.metrics);
      rec(P, "4H: 6.46/7.384 +-0.01 (TV 6.46/7.39 +-0.02)", near(H.e, 6.46, 0.01) && near(H.sl, 7.384, 0.01) && near(H.sl, 7.39, 0.02), JSON.stringify(H));
      rec(P, "4H: not Daily's numbers glued on", Number.isFinite(H.e) && Math.abs(H.e - D.e) > 0.05, `4H ${H.e} vs D ${D.e}`);
      rec(P, "4H: 3 panes", x.panes === 2, x.panes);
      rec(P, "4H: chip is real history (> 187)", num(/(\d+) 4H bars/, x.chip) > 187, x.chip);
      rec(P, "4H: no SCORE 0/8", !/SCORE\s*0\s*\/\s*8/i.test(x.metrics), "ok");
      await page.screenshot({ path: `${OUT}/els-4H.png` });
    } else rec(P, "4H button present", false, d.tfs.join(" "));
    rec(P, "no page error", errs.length === 0, errs.join(" ; ") || "none");
    await ctx.close();
  }
  // ?pm=1 opt-in still allowed (informational: PhaseMap may have no ELS record)
  {
    const P = "ELS momentum chart ?pm=1";
    const { ctx, page, errs } = await open("/chart.html?s=ELS&m=asx&src=momentum&pm=1");
    await page.waitForSelector("#tf-toggle .tf-btn[data-tf]", { timeout: 70000 }).catch(() => {});
    await page.waitForTimeout(2000);
    const d = await readChart(page);
    rec(P, "loads with the plan, no page error", errs.length === 0 && /Entry/i.test(d.metrics), `pm strip ${d.pm}; ${errs.join(" ; ") || "no errors"}`);
    await ctx.close();
  }

  // ── BHP 5.0 chart, no src ──
  {
    const P = "BHP 5.0 chart";
    const { ctx, page, errs } = await open("/chart.html?s=BHP&m=asx");
    await page.waitForSelector("#tf-toggle .tf-btn[data-tf]", { timeout: 70000 }).catch(() => {});
    await page.waitForTimeout(2000);
    const r = await page.evaluate(() => ({ legend: ((document.getElementById("chart-legend") || {}).innerText || "").replace(/\s+/g, " "),
      metrics: ((document.getElementById("cf-metrics") || {}).innerText || "").replace(/\s+/g, " "),
      body: document.body.innerText, panes: document.querySelectorAll(".mom-pane").length }));
    rec(P, "SMA 10 / 20 / 43 in the legend", /SMA 10/.test(r.legend) && /SMA 20/.test(r.legend) && /SMA 43/.test(r.legend), r.legend.slice(0, 140));
    rec(P, "5.0 footer (Setup + 200 SMA)", /Setup/i.test(r.metrics) && /200 SMA/.test(r.metrics), r.metrics.slice(0, 160));
    rec(P, "no Pine caption, no Momentum panes", !/Pine template/.test(r.body) && r.panes === 0, `panes ${r.panes}`);
    rec(P, "no page error", errs.length === 0, errs.join(" ; ") || "none");
    await page.screenshot({ path: `${OUT}/bhp-5.png` });
    await ctx.close();
  }

  // ── fail() / emptyState() keep src ──
  {
    const P = "chart empty state src=momentum";
    const { ctx, page, errs } = await open("/chart.html?src=momentum");
    await page.waitForSelector("#ce-form", { timeout: 30000 }).catch(() => {});
    const back = await page.evaluate(() => (document.querySelector(".back-link") || {}).getAttribute?.("href") || "");
    rec(P, "back-link -> momentum.html", /momentum\.html/.test(back), back);
    await page.fill("#ce-sym", "ELS").catch(() => {});
    await Promise.all([page.waitForURL(/chart\.html\?.*s=ELS/, { timeout: 20000 }).catch(() => {}), page.click("#ce-form button[type=submit]").catch(() => {})]);
    rec(P, "search keeps src=momentum", /src=momentum/.test(page.url()), page.url().replace(BASE, ""));
    rec(P, "no page error", errs.length === 0, errs.join(" ; ") || "none");
    await ctx.close();
  }
  {
    const P = "chart fail() src=momentum";
    const { ctx, page, errs } = await open("/chart.html?s=ZZQXJ&m=asx&src=momentum");
    await page.waitForSelector(".chart-error", { timeout: 70000 }).catch(() => {});
    const r = await page.evaluate(() => ({ err: !!document.querySelector(".chart-error"), back: (document.querySelector(".back-link") || {}).getAttribute?.("href") || "", h: ((document.querySelector(".chart-error h2") || {}).textContent || "") }));
    rec(P, "bogus symbol reaches fail()", r.err, r.h);
    rec(P, "fail() back-link -> momentum.html", /momentum\.html/.test(r.back), r.back);
    rec(P, "no page error", errs.length === 0, errs.join(" ; ") || "none");
    await ctx.close();
  }

  // ── other pages load ──
  const PAGES = { journal: ["/journal.html", "#bot-open, .jr-table, #jr-bot, main"], alerts: ["/alerts.html", "main"], phasemap: ["/phasemap.html", "main"], specs: ["/specs.html", "main"] };
  for (const [k, [url, sel]] of Object.entries(PAGES)) {
    const P = `page ${k}`;
    const { ctx, page, errs } = await open(url);
    await page.waitForLoadState("load", { timeout: 60000 }).catch(() => {});
    await page.waitForTimeout(3000);
    const r = await page.evaluate((sel) => ({ ok: !!document.querySelector(sel), text: document.body.innerText.length, loading: /Loading…|Loading\.\.\./.test(document.body.innerText), over: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1 }), sel);
    rec(P, "loads, has content, no page error", errs.length === 0 && r.ok && r.text > 200, `text ${r.text}ch, still-loading ${r.loading}, overflow ${r.over}; ${errs.join(" ; ") || "no errors"}`);
    await page.screenshot({ path: `${OUT}/page-${k}.png` });
    await ctx.close();
  }
})().catch((e) => rec("probe", "ran to completion", false, e && e.stack || e)).finally(finish);
