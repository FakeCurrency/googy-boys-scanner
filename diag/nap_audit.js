// THROWAWAY production audit (2026-09-23 nap run). Read-only GETs of the
// public site at 390x844; writes results + screenshots into diag/audit/ on
// this branch only.
const { chromium } = require("playwright");
const fs = require("fs");
const BASE = process.env.PROBE_BASE || "https://googy-boys-scanner.pages.dev";
const OUT = "diag/audit"; fs.mkdirSync(OUT, { recursive: true });
setTimeout(() => { console.log("WATCHDOG"); process.exit(0); }, 240000).unref();
const results = []; const rec = (page, check, pass, detail) => { results.push({ page, check, pass: !!pass, detail }); console.log(pass ? "PASS" : "FAIL", page, "|", check, "|", detail); };
let browser;
(async () => {
  browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
  const open = async (url, shot) => {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const page = await ctx.newPage(); const errs = [];
    page.on("pageerror", (e) => errs.push(String(e).slice(0, 200)));
    await page.goto(BASE + url, { waitUntil: "domcontentloaded", timeout: 60000 });
    return { ctx, page, errs };
  };
  // ── /momentum ASX + NASDAQ ──
  for (const m of ["asx", "nasdaq"]) {
    const P = `momentum ${m}`;
    const { ctx, page, errs } = await open(`/momentum.html?m=${m}`);
    await page.waitForFunction(() => !/loading/i.test((document.getElementById("mo-title") || {}).textContent || "loading"), null, { timeout: 45000 }).catch(() => {});
    await page.waitForTimeout(1500);
    const r = await page.evaluate(() => ({
      title: (document.getElementById("mo-title") || {}).textContent || "",
      sub: (document.getElementById("mo-sub") || {}).textContent || "",
      stamp: (document.getElementById("mo-stamp") || {}).textContent || "",
      rows: document.querySelectorAll(".mo-row").length,
      hrefs: [...document.querySelectorAll("a.mo-sym")].map((a) => a.getAttribute("href")),
      empty: [...document.querySelectorAll(".mo-empty")].map((e) => e.textContent.trim()).join(" | "),
      tabs: [...document.querySelectorAll(".site-tab, .bottom-tab, [data-tabkey]")].map((t) => t.dataset.tabkey || t.textContent.trim()).filter(Boolean),
    }));
    const n = +((/MOMENTUM · (\d+)/.exec(r.title) || [])[1]);
    rec(P, "loads with no page error", errs.length === 0, errs.join(" ; ") || "none");
    rec(P, "header: title + scanned/gated/last bar", /MOMENTUM ·/.test(r.title) && /scanned/.test(r.sub) && /gated/.test(r.sub) && /last bar \d{4}-\d{2}-\d{2}/.test(r.sub), `${r.title} || ${r.sub} || ${r.stamp}`);
    rec(P, "rows rendered = header count", Number.isFinite(n) && r.rows === n, `header ${n}, .mo-row ${r.rows}${r.empty ? " | " + r.empty : ""}`);
    rec(P, "every row link is ?s=...&m=...&src=momentum, never ?symbol=", r.hrefs.length === r.rows && r.hrefs.every((h) => /[?&]s=/.test(h) && /src=momentum/.test(h) && !/[?&]symbol=/.test(h)), `${r.hrefs.length} links, e.g. ${r.hrefs[0] || "-"}`);
    await page.screenshot({ path: `${OUT}/momentum-${m}.png` });
    await ctx.close();
  }
  // ── ELS Momentum chart ──
  {
    const P = "ELS momentum chart";
    const { ctx, page, errs } = await open("/chart.html?s=ELS&m=asx&src=momentum");
    await page.waitForSelector("#tf-toggle .tf-btn[data-tf]", { timeout: 70000 }).catch(() => {});
    await page.waitForTimeout(1500);
    const read = () => page.evaluate(() => {
      const txt = (sel) => ((document.querySelector(sel) || {}).innerText || "").replace(/\s+/g, " ").trim();
      return { chartJs: (document.querySelector('script[src*="js/chart.js"]') || {}).src || "",
        tfs: [...document.querySelectorAll("#tf-toggle .tf-btn[data-tf]")].map((b) => b.dataset.tf + (b.classList.contains("is-active") ? "*" : "")),
        chip: txt(".mom-bars"), panes: document.querySelectorAll(".mom-pane").length,
        foot: txt(".chart-foot"), top: txt(".chart-top"), legend: txt("#chart-legend"),
        tfbarTop: Math.round(document.getElementById("tf-toggle").getBoundingClientRect().top), vh: innerHeight };
    });
    const d = await read();
    const num = (re, s) => { const m = re.exec(s); return m ? +m[1] : NaN; };
    const eD = num(/ENTRY A\$([\d.]+)/, d.foot), sD = num(/SL A\$([\d.]+)/, d.foot);
    rec(P, "serves the aligned build", /chart\.js\?v=(\d+)/.test(d.chartJs) && +/chart\.js\?v=(\d+)/.exec(d.chartJs)[1] >= 121, d.chartJs.replace(BASE, ""));
    rec(P, "D: SHORT 5.88 / 6.76 family", /SHORT/.test(d.foot) && Math.abs(eD - 5.88) <= 0.01 && Math.abs(sD - 6.762) <= 0.01, `entry ${eD} sl ${sD} | ${d.foot.slice(0, 110)}`);
    rec(P, "D: 3 panes (price + MACD + RSI)", d.panes === 2, `${d.panes} oscillator panes`);
    rec(P, "D: bars chip", /\d+ daily bars/.test(d.chip), d.chip);
    rec(P, "D: no PhaseMap, no SCORE 0/8", !/phasemap/i.test(d.top + " " + d.legend + " " + d.foot) && !/SCORE 0\/8/.test(d.foot + d.top), `top: ${d.top.slice(0, 120)}`);
    rec(P, "timeframe bar on screen (phone)", d.tfbarTop > 0 && d.tfbarTop + 40 < d.vh, `bar top ${d.tfbarTop} / viewport ${d.vh}`);
    await page.screenshot({ path: `${OUT}/els-D.png` });
    for (const tf of ["4H", "3D", "1W"]) {
      if (!d.tfs.some((t) => t.startsWith(tf))) { rec(P, `${tf}: button present`, false, d.tfs.join(" ")); continue; }
      await page.tap(`#tf-toggle .tf-btn[data-tf="${tf}"]`); await page.waitForTimeout(1200);
      const x = await read();
      if (tf === "4H") {
        const n4 = num(/(\d+) 4H bars/, x.chip), e4 = num(/ENTRY A\$([\d.]+)/, x.foot), s4 = num(/SL A\$([\d.]+)/, x.foot);
        rec(P, "4H: chip is real history (not 187)", n4 > 187, x.chip);
        rec(P, "4H: own plan, not Daily's numbers", isFinite(e4) && Math.abs(e4 - eD) > 0.05 && Math.abs(s4 - sD) > 0.05, `entry ${e4} sl ${s4} (daily ${eD}/${sD})`);
        rec(P, "4H: within $0.02 of TV 6.46 / 7.39", Math.abs(e4 - 6.46) <= 0.02 && Math.abs(s4 - 7.39) <= 0.02, `entry ${e4} sl ${s4}`);
        await page.screenshot({ path: `${OUT}/els-4H.png` });
      } else {
        rec(P, `${tf}: own plan or honest no-cross`, /ENTRY A\$/.test(x.foot) || /no scored cross in 60 bars/i.test(x.foot), `${x.chip} | ${x.foot.slice(0, 100)}`);
      }
    }
    rec(P, "no page errors", errs.length === 0, errs.join(" ; ") || "none");
    await ctx.close();
  }
  // ── BHP 5.0 chart ──
  {
    const P = "BHP 5.0 chart";
    const { ctx, page, errs } = await open("/chart.html?s=BHP&m=asx");
    await page.waitForSelector("#tf-toggle .tf-btn[data-tf]", { timeout: 70000 }).catch(() => {});
    await page.waitForTimeout(1500);
    const r = await page.evaluate(() => ({ legend: ((document.getElementById("chart-legend") || {}).innerText || "").replace(/\s+/g, " "),
      body: document.body.innerText, panes: document.querySelectorAll(".mom-pane").length }));
    rec(P, "SMA 10 / 20 / 43 in the legend", /SMA 10/.test(r.legend) && /SMA 20/.test(r.legend) && /SMA 43/.test(r.legend), r.legend.slice(0, 140));
    rec(P, "no Pine caption, no Momentum panes", !/Pine template/.test(r.body) && r.panes === 0, `panes ${r.panes}`);
    rec(P, "no page errors", errs.length === 0, errs.join(" ; ") || "none");
    await page.screenshot({ path: `${OUT}/bhp-5.png` });
    await ctx.close();
  }
})().catch((e) => rec("probe", "ran to completion", false, String(e)))
  .finally(async () => {
    fs.writeFileSync(`${OUT}/results.json`, JSON.stringify({ base: BASE, at: new Date().toISOString(), results }, null, 1) + "\n");
    try { if (browser) await browser.close(); } catch (_) {}
    process.exit(0);
  });
