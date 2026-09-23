// THROWAWAY production smoke (validate 2026-09-23, V2). Read-only GETs of the
// public site; writes results + screenshots into diag/validate/ on this branch only.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const BASE = process.env.PROBE_BASE || "https://googy-boys-scanner.pages.dev";
const OUT = "diag/validate"; fs.mkdirSync(OUT, { recursive: true });
setTimeout(() => { console.log("WATCHDOG"); finish(); }, 780000).unref();
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
const getText = async (url) => { const r = await fetch(url, { cache: "no-store" }); return { status: r.status, text: await r.text() }; };
const vrefs = (html) => [...html.matchAll(/(?:src|href)="([^"]+\?v=[^"]+)"/g)].map((m) => m[1]).sort();

(async () => {
  // ── V5 skew: served build vs this checkout ──
  const localVer = JSON.parse(fs.readFileSync("public/version.json", "utf8")).version;
  try {
    const r = JSON.parse((await getText(BASE + "/version.json")).text);
    rec("deploy", "served version.json == repo version.json", r.version === localVer, `served ${r.version} / repo ${localVer}`);
  } catch (e) { rec("deploy", "version.json served", false, e); }
  for (const f of fs.readdirSync("public").filter((x) => x.endsWith(".html"))) {
    try {
      const s = await getText(`${BASE}/${f}`);
      const served = vrefs(s.text), local = vrefs(fs.readFileSync(path.join("public", f), "utf8"));
      const same = JSON.stringify(served) === JSON.stringify(local);
      rec("deploy", `${f}: served ?v= refs == repo`, s.status === 200 && same, same ? `${local.length} refs` : `served ${served.join(",")} | repo ${local.join(",")}`);
    } catch (e) { rec("deploy", `${f} served`, false, e); }
  }
  try {
    const s = await getText(BASE + "/sw.js"); const local = fs.readFileSync("public/sw.js", "utf8");
    const c = (t) => (/const CACHE\s*=\s*["']([^"']+)/.exec(t) || [])[1];
    rec("deploy", "sw.js CACHE served == repo", c(s.text) && c(s.text) === c(local), `served ${c(s.text)} / repo ${c(local)}`);
  } catch (e) { rec("deploy", "sw.js served", false, e); }

  browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
  const open = async (url, vp) => {
    const ctx = await browser.newContext(vp === "desk" ? { viewport: { width: 1400, height: 950 } } : { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const page = await ctx.newPage(); const errs = [];
    await page.addInitScript(() => { try { localStorage.setItem("gbs:onboarded", "1"); } catch (_) {} });
    page.on("pageerror", (e) => errs.push(String(e).slice(0, 200)));
    await page.goto(BASE + url, { waitUntil: "domcontentloaded", timeout: 60000 });
    return { ctx, page, errs };
  };

  // ── / 5.0 deck + nav contract ──
  for (const vp of ["desk", "phone"]) {
    const P = `/ deck ${vp}`;
    const { ctx, page, errs } = await open("/", vp);
    await page.waitForSelector(".row-wrap", { timeout: 60000 }).catch(() => {});
    await page.waitForTimeout(1500);
    const r = await page.evaluate(() => ({
      title: (document.getElementById("scan-title") || {}).textContent || "",
      pills: document.querySelectorAll("#deck-pills .fpill").length,
      rows: document.querySelectorAll(".row-wrap").length,
      aplus: [...document.querySelectorAll(".row-wrap .row-grade")].filter((g) => /^A\+/.test(g.textContent.trim())).length,
      over: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      navPills: [...document.querySelectorAll(".nav-pills .howto-link")].map((a) => a.textContent.trim()),
      moColor: (() => { const a = document.querySelector('.nav-pills .howto-link[href="momentum.html"]'); return a ? getComputedStyle(a).borderTopColor + " / " + getComputedStyle(a).backgroundColor : ""; })(),
      tabs: [...document.querySelectorAll(".site-tabs a.site-tab")].map((a) => a.dataset.tabkey),
      more: !!document.querySelector(".site-tabs .site-tab-more"),
    }));
    rec(P, "deck title painted (not loading)", r.title && !/Loading latest scan/.test(r.title), r.title.slice(0, 80));
    rec(P, "filter pills (.fpill) >= 3", r.pills >= 3, r.pills);
    rec(P, "A+ cards present", r.aplus > 0, `${r.aplus} A+ of ${r.rows} rows`);
    if (vp === "desk") {
      const i = r.navPills.findIndex((t) => /^SPECS/.test(t));
      rec(P, "nav: MOMENTUM pill straight after SPECS", i >= 0 && r.navPills[i + 1] === "MOMENTUM", r.navPills.join(" · "));
      rec(P, "nav: MOMENTUM pill is purple (--purple rgb 191,90,242 border + fill)", (r.moColor.match(/191,\s*90,\s*242/g) || []).length === 2, r.moColor);
    } else {
      rec(P, "nav: TABS === 5 (+ MORE), momentum off-tab", r.tabs.length === 5 && r.more && !r.tabs.includes("momentum"), `${r.tabs.join(",")} + MORE ${r.more}`);
      rec(P, "no horizontal overflow", !r.over, r.over);
    }
    rec(P, "no page error", errs.length === 0, errs.join(" ; ") || "none");
    await page.screenshot({ path: `${OUT}/deck-${vp}.png` });
    await ctx.close();
  }
  // phone MORE sheet carries MOMENTUM
  {
    const P = "/ phone MORE sheet";
    const { ctx, page, errs } = await open("/", "phone");
    await page.waitForSelector(".site-tab-more", { timeout: 30000 }).catch(() => {});
    await page.tap(".site-tab-more").catch(() => {});
    await page.waitForTimeout(800);
    const rows = await page.evaluate(() => [...document.querySelectorAll(".more-sheet-row")].map((a) => a.getAttribute("href")));
    rec(P, "MORE sheet lists momentum.html", rows.includes("momentum.html"), rows.join(","));
    rec(P, "no page error", errs.length === 0, errs.join(" ; ") || "none");
    await ctx.close();
  }

  // ── /momentum (default ASX) + /momentum?m=nasdaq ──
  for (const [url, m] of [["/momentum", "asx"], ["/momentum?m=nasdaq", "nasdaq"]]) {
    const P = url;
    let want = NaN;
    try { want = (JSON.parse((await getText(`${BASE}/data/momentum/${m}.json`)).text).results || []).length; } catch (_) {}
    const { ctx, page, errs } = await open(url, "phone");
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
      over: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    }));
    const n = num(/MOMENTUM · (\d+)/, r.title);
    rec(P, "no page error", errs.length === 0, errs.join(" ; ") || "none");
    rec(P, "header: title + scanned/gated/last bar", /MOMENTUM ·/.test(r.title) && /scanned/.test(r.sub) && /gated/.test(r.sub) && /last bar \d{4}-\d{2}-\d{2}/.test(r.sub), `${r.title} || ${r.sub}`);
    rec(P, `rows == served ${m}.json results`, Number.isFinite(want) && r.rows === want && n === want, `header ${n}, .mo-row ${r.rows}, json ${want}`);
    rec(P, "pills are .fpill with <b> count, no .deck-pill", r.fpills.length >= 1 && r.fpillB === r.fpills.length && r.deckPill === 0, r.fpills.join(" | "));
    rec(P, "every row ?s=...&src=momentum, never ?symbol=", r.hrefs.length === r.rows && r.hrefs.every((h) => /[?&]s=/.test(h) && /src=momentum/.test(h) && !/[?&]symbol=/.test(h)), `${r.hrefs.length} links, e.g. ${r.hrefs[0] || "-"}`);
    rec(P, "no horizontal overflow", !r.over, r.over);
    await page.screenshot({ path: `${OUT}/momentum-${m}.png` });
    await ctx.close();
  }

  // ── ELS Momentum chart, D + 4H ──
  const readChart = (page) => page.evaluate(() => {
    const txt = (sel) => ((document.querySelector(sel) || {}).innerText || "").replace(/\s+/g, " ").trim();
    return { tfs: [...document.querySelectorAll("#tf-toggle .tf-btn[data-tf]")].map((b) => b.dataset.tf + (b.classList.contains("is-active") ? "*" : "")),
      chip: txt(".mom-bars"), panes: document.querySelectorAll(".mom-pane").length,
      metrics: txt("#cf-metrics"), top: txt(".chart-top"), legend: txt("#chart-legend"),
      pm: !!document.querySelector(".pm-chart-strip"), back: (document.querySelector(".back-link") || {}).getAttribute?.("href") || "" };
  });
  const lv = (s) => ({ e: num(/Entry\s*A\$([\d.]+)/i, s), sl: num(/SL\s*A\$([\d.]+)/i, s), t1: num(/TP1\s*A\$([\d.]+)/i, s), t2: num(/TP2\s*A\$([\d.]+)/i, s), t3: num(/TP3\s*A\$([\d.]+)/i, s) });
  {
    const P = "chart ELS src=momentum";
    const { ctx, page, errs } = await open("/chart.html?s=ELS&m=asx&src=momentum", "phone");
    await page.waitForSelector("#tf-toggle .tf-btn[data-tf]", { timeout: 70000 }).catch(() => {});
    await page.waitForTimeout(2500);
    const d = await readChart(page);
    const D = lv(d.metrics);
    rec(P, "D: SHORT", /SHORT/.test(d.metrics), d.metrics.slice(0, 80));
    rec(P, "D: 5.88/6.76/4.998/4.116/3.234 +-0.01", near(D.e, 5.88, 0.01) && near(D.sl, 6.76, 0.01) && near(D.t1, 4.998, 0.01) && near(D.t2, 4.116, 0.01) && near(D.t3, 3.234, 0.01), JSON.stringify(D));
    rec(P, "D: price + MACD + RSI panes", d.panes === 2, `${d.panes} oscillator panes`);
    rec(P, "D: bars chip", /\d+ daily bars/.test(d.chip), d.chip);
    rec(P, "D: no SCORE 0/8", !/SCORE\s*0\s*\/\s*8/i.test(d.metrics + " " + d.top), "ok");
    rec(P, "D: no PhaseMap without ?pm=1", !d.pm, `pm strip ${d.pm}`);
    rec(P, "back-link -> momentum.html", /momentum\.html/.test(d.back), d.back);
    await page.screenshot({ path: `${OUT}/els-D.png` });
    if (d.tfs.some((t) => t.startsWith("4H"))) {
      await page.tap('#tf-toggle .tf-btn[data-tf="4H"]'); await page.waitForTimeout(2500);
      const x = await readChart(page); const H = lv(x.metrics);
      rec(P, "4H: ~6.46 / ~7.38 (+-0.01)", near(H.e, 6.46, 0.01) && near(H.sl, 7.38, 0.01), JSON.stringify(H));
      rec(P, "4H: not Daily's numbers copied on", Number.isFinite(H.e) && Math.abs(H.e - D.e) > 0.05 && Math.abs(H.sl - D.sl) > 0.05, `4H ${H.e}/${H.sl} vs D ${D.e}/${D.sl}`);
      rec(P, "4H: price + MACD + RSI panes", x.panes === 2, x.panes);
      rec(P, "4H: chip is real history (> 187)", num(/(\d+) 4H bars/, x.chip) > 187, x.chip);
      await page.screenshot({ path: `${OUT}/els-4H.png` });
    } else rec(P, "4H button present", false, d.tfs.join(" "));
    rec(P, "no page error", errs.length === 0, errs.join(" ; ") || "none");
    await ctx.close();
  }

  // ── BHP 5.0 chart, no src ──
  {
    const P = "chart BHP no src";
    const { ctx, page, errs } = await open("/chart.html?s=BHP&m=asx", "phone");
    await page.waitForSelector("#tf-toggle .tf-btn[data-tf]", { timeout: 70000 }).catch(() => {});
    await page.waitForTimeout(2500);
    const r = await page.evaluate(() => ({ legend: ((document.getElementById("chart-legend") || {}).innerText || "").replace(/\s+/g, " "),
      metrics: ((document.getElementById("cf-metrics") || {}).innerText || "").replace(/\s+/g, " "),
      body: document.body.innerText, panes: document.querySelectorAll(".mom-pane").length,
      back: (document.querySelector(".back-link") || {}).getAttribute?.("href") || "" }));
    rec(P, "SMA 10 / 20 / 43 in the legend", /SMA 10/.test(r.legend) && /SMA 20/.test(r.legend) && /SMA 43/.test(r.legend), r.legend.slice(0, 140));
    rec(P, "5.0 footer family, not the Momentum PLAN strip", (/Setup/i.test(r.metrics) || /ENTRY/i.test(r.metrics)) && !/\bPLAN\b/i.test(r.metrics) && !/SIGNAL/i.test(r.metrics), r.metrics.slice(0, 160));
    rec(P, "no Pine caption, no Momentum panes", !/Pine template/.test(r.body) && r.panes === 0, `panes ${r.panes}`);
    rec(P, "back-link is not momentum.html", !/momentum\.html/.test(r.back), r.back);
    rec(P, "no page error", errs.length === 0, errs.join(" ; ") || "none");
    await page.screenshot({ path: `${OUT}/bhp.png` });
    await ctx.close();
  }

  // ── fail() / emptyState() keep src ──
  {
    const P = "chart emptyState src=momentum";
    const { ctx, page, errs } = await open("/chart.html?src=momentum", "phone");
    await page.waitForSelector("#ce-form", { timeout: 30000 }).catch(() => {});
    const back = await page.evaluate(() => (document.querySelector(".back-link") || {}).getAttribute?.("href") || "");
    rec(P, "back-link -> momentum.html", /momentum\.html/.test(back), back);
    await page.fill("#ce-sym", "ELS").catch(() => {});
    await Promise.all([page.waitForURL(/chart\.html\?.*s=ELS/, { timeout: 20000 }).catch(() => {}), page.click("#ce-form button[type=submit]").catch(() => {})]);
    rec(P, "search keeps src=momentum and uses ?s=", /src=momentum/.test(page.url()) && /[?&]s=ELS/.test(page.url()), page.url().replace(BASE, ""));
    rec(P, "no page error", errs.length === 0, errs.join(" ; ") || "none");
    await ctx.close();
  }
  {
    const P = "chart fail() src=momentum";
    const { ctx, page, errs } = await open("/chart.html?s=ZZQXJ&m=asx&src=momentum", "phone");
    await page.waitForSelector(".chart-error", { timeout: 70000 }).catch(() => {});
    const r = await page.evaluate(() => ({ err: !!document.querySelector(".chart-error"), back: (document.querySelector(".back-link") || {}).getAttribute?.("href") || "", h: ((document.querySelector(".chart-error h2") || {}).textContent || "") }));
    rec(P, "bogus symbol reaches fail()", r.err, r.h);
    rec(P, "fail() back-link -> momentum.html", /momentum\.html/.test(r.back), r.back);
    rec(P, "no page error", errs.length === 0, errs.join(" ; ") || "none");
    await ctx.close();
  }

  // ── other pages load ──
  const PAGES = { "/journal": "#bot-open, .jr-table, #jr-bot, main", "/alerts": "main", "/phasemap": "main", "/specs": "main", "/recommendations": ".rec-card" };
  for (const [url, sel] of Object.entries(PAGES)) {
    for (const vp of ["desk", "phone"]) {
      const P = `${url} ${vp}`;
      const { ctx, page, errs } = await open(url, vp);
      await page.waitForLoadState("load", { timeout: 60000 }).catch(() => {});
      await page.waitForSelector(sel, { timeout: 30000 }).catch(() => {});
      await page.waitForTimeout(3000);
      const r = await page.evaluate((sel) => ({ ok: !!document.querySelector(sel), n: document.querySelectorAll(sel).length, text: document.body.innerText.length, loading: /Loading…|Loading\.\.\./.test(document.body.innerText), over: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1 }), sel);
      rec(P, "loads, has content, no page error, no overflow", errs.length === 0 && r.ok && r.text > 200 && !r.over, `${sel} x${r.n}, text ${r.text}ch, still-loading ${r.loading}, overflow ${r.over}; ${errs.join(" ; ") || "no errors"}`);
      await page.screenshot({ path: `${OUT}/page${url.replace(/\//g, "-")}-${vp}.png` });
      await ctx.close();
    }
  }
})().catch((e) => rec("probe", "ran to completion", false, e && e.stack || e)).finally(finish);
