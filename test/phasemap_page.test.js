/* PHASEMAP page — the market-switch race and the FLASHED/bars-to header.
 *
 * Runs the SHIPPED public/js/phasemap.js end to end under a stub DOM: its IIFE
 * boots, wires the market buttons and calls load(); the test clicks the
 * buttons and resolves each market's fetches in the order a phone sees them
 * (the 1 MB ASX file lands after the 150 KB crypto one). A re-typed copy of
 * load() would drift in step with the bug it exists to catch.
 *
 *   folded #127  whichever fetch resolved LAST won state.data: tap NASDAQ then
 *                CRYPTO, crypto lands first, NASDAQ second -> the crypto tab
 *                showed NASDAQ cards and wrote them into pm-seen:crypto, so
 *                the next crypto visit badged everything NEW.
 *   #196         FLASHED compared evidence dates with run_date (the Melbourne
 *                date the nightly published, a day after the bar) and fired
 *                0 times in 21 snapshots; it now keys off as_of.
 *
 * Sandboxed with `new Function(...)` (same realm), per the repo's JS-suite rule.
 */
"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(__dirname, "..", "public", "js", "phasemap.js"), "utf8");

let checks = 0;
const ok = (cond, msg) => { assert.ok(cond, msg); checks++; };
const eq = (a, b, msg) => { assert.strictEqual(a, b, msg); checks++; };

// ── a stub DOM: every selector maps to one remembered element ─────────────
function stubEl(name) {
  const t = { name, textContent: "", innerHTML: "", hidden: false, className: "",
              dataset: {}, style: {}, listeners: {}, parentNode: null };
  const self = new Proxy(t, {
    get(o, k) {
      if (k in o) return o[k];
      if (k === "querySelector") return () => null;
      if (k === "querySelectorAll") return () => [];
      if (k === "classList") return { toggle() {}, add() {}, remove() {}, contains: () => false };
      if (k === "addEventListener") return (ev, fn) => { (o.listeners[ev] = o.listeners[ev] || []).push(fn); };
      if (typeof k === "symbol") return undefined;
      return () => self;
    },
    set(o, k, v) { o[k] = v; return true; },
  });
  return self;
}

function boot(initialMarket) {
  const els = {};
  const el = (sel) => (els[sel] = els[sel] || stubEl(sel));
  const buttons = ["asx", "nasdaq", "crypto"].map((m) => {
    const b = stubEl(`btn-${m}`);
    b.dataset.market = m;
    return b;
  });
  const store = new Map(initialMarket ? [["pm-market", initialMarket]] : []);
  const localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
  };
  const document = {
    querySelector: (sel) => el(sel),
    querySelectorAll: (sel) => (sel === "#pm-market .market-btn" ? buttons : []),
    getElementById: () => null,
    createElement: (tag) => stubEl(tag),
    addEventListener() {},
    body: stubEl("body"),
    activeElement: null,
  };
  // every data fetch parks until the test resolves it
  const pending = {};
  const json = (body) => ({ ok: true, status: 200, json: async () => body });
  const PM = {
    esc: (s) => String(s == null ? "" : s),
    fetchTimeout: (url) => new Promise((resolve) => { pending[url] = (body) => resolve(json(body)); }),
    loadConfluence: () => Promise.resolve({ of: () => null, all: () => [] }),
    staleBadgeHTML: () => "", loadFailKind: () => "unreachable", retryHTML: () => "",
    confluenceChipHTML: () => "", confluenceBannerHTML: () => "", headBadgesHTML: () => "",
    identityHTML: () => "", stepperHTML: () => "", ladderHTML: () => "", whyHTML: () => "",
    metricsHTML: () => "", glossaryHTML: () => "", toggleSpeak() {},
  };
  const window = { location: { href: "" } };
  new Function("window", "document", "localStorage", "PM", SRC)(window, document, localStorage, PM);
  const click = (m) => buttons.find((b) => b.dataset.market === m).listeners.click[0]();
  return { els, store, pending, click };
}

const settle = () => new Promise((r) => setImmediate(r));

function payload(market, tickers, extra = {}) {
  return {
    run_date: "2026-10-14", ruleset_version: "1.3.1", universe_size: 100, ...extra,
    results: tickers.map((t) => ({
      ticker: t, direction: "bullish", state: "DISPLACED", tier: "A", tags: [],
      regime: "EXPANSION", zones: [], next: "", name: t, sector: "",
      metrics: { displacement_date: extra.as_of || "2026-10-13", sweep_date: "2026-10-10" },
    })),
  };
}

async function deliver(app, market, body) {
  app.pending[`data/phasemap/${market}/latest.json`](body);
  app.pending[`data/phasemap/${market}/narrations.json`]({ run_date: body.run_date, narrations: {} });
  await settle(); await settle();
}

(async () => {
  // 1. The race: NASDAQ then CRYPTO tapped, crypto lands first, NASDAQ and the
  //    boot-time ASX load land after it. The crypto tab must stay crypto.
  {
    const app = boot("asx");
    app.click("nasdaq");
    app.click("crypto");
    await deliver(app, "crypto", payload("crypto", ["BTC"], { as_of: "2026-10-13" }));
    await deliver(app, "nasdaq", payload("nasdaq", ["AAPL"], { as_of: "2026-10-13" }));
    await deliver(app, "asx", payload("asx", ["BHP"], { as_of: "2026-10-13" }));
    const sub = app.els["#pm-sub"].innerHTML;
    ok(sub.startsWith("CRYPTO · "), `the header names the market on screen: ${sub}`);
    const list = app.els["#pm-list"].innerHTML;
    ok(list.includes("BTC") && !list.includes("AAPL") && !list.includes("BHP"),
      "a slow, superseded market's cards never paint over the current one");
    eq(app.store.get("pm-market"), "crypto", "the remembered market is the tapped one");
    ok(app.store.has("pm-seen:crypto"), "the current market's memory is written");
    ok(!app.store.has("pm-seen:nasdaq") && !app.store.has("pm-seen:asx"),
      "a superseded load writes no 'since you last checked' memory");
    ok(Object.keys(JSON.parse(app.store.get("pm-seen:crypto")).states).every((k) => k.startsWith("BTC|")),
      "pm-seen:crypto holds crypto names only");
  }

  // 2. FLASHED keys off as_of (the bar date), not run_date.
  {
    const app = boot("asx");
    await deliver(app, "asx", payload("asx", ["BHP"], { as_of: "2026-10-13", fetched: 1712,
                                                        universe_size: 1924 }));
    const list = app.els["#pm-list"].innerHTML;
    ok(list.includes("⚡ FLASHED"), "a displacement on the newest completed bar is FLASHED");
    const sub = app.els["#pm-sub"].innerHTML;
    ok(sub.includes("scan 2026-10-14 · bars to 2026-10-13"), `header shows both dates: ${sub}`);
    ok(sub.includes("1,712 of 1,924 tickers fetched"),
      `header says how much was fetched: ${sub}`);
  }
  {
    const app = boot("asx");
    const old = payload("asx", ["BHP"]);        // pre-as_of payload: run_date reading kept
    old.results[0].metrics.displacement_date = "2026-10-13";
    await deliver(app, "asx", old);
    ok(!app.els["#pm-list"].innerHTML.includes("⚡ FLASHED"),
      "an old payload without as_of falls back to run_date (no false flash)");
    ok(app.els["#pm-sub"].innerHTML.includes("100 tickers scanned"), "old header wording kept");
  }

  // 3. A carried snapshot says so.
  {
    const app = boot("asx");
    await deliver(app, "asx", payload("asx", ["BHP"], { as_of: "2026-10-09",
                                                        carried_from: "2026-10-10" }));
    ok(app.els["#pm-sub"].innerHTML.includes("bars to 2026-10-09 (no new bar since the 2026-10-10 scan)"),
      "a carried-forward snapshot names the scan it carries");
  }

  // 4. Insights (REFINE200 #200): ALL SIGNALS pools longs with signed
  //    shorts, so its random comparator is the draws signed to the same mix,
  //    not the long-only drift (+0.9% read as a loss to +1.9%).
  {
    const INS = fs.readFileSync(path.join(__dirname, "..", "public", "js", "phasemap-insights.js"), "utf8");
    const stats = (all20, rnd20, matched20) => ({
      generated: "2026-10-11", ruleset_version: "1.3.1", cohorts: {},
      all: { fwd_5: 0.001, fwd_10: 0.002, fwd_20: all20 },
      baselines: { random: { fwd_5: 0.004, fwd_10: 0.009, fwd_20: rnd20,
        ...(matched20 == null ? {} : { matched: { fwd_5: 0, fwd_10: 0, fwd_20: matched20 } }) } },
    });
    const run = async (asx, nas) => {
      const els = {};
      const document = { getElementById: (id) => (els[id] = els[id] || { innerHTML: "", textContent: "" }) };
      const files = { "data/phasemap/stats/asx.json": asx, "data/phasemap/stats/nasdaq.json": nas };
      const fetch = (url) => Promise.resolve({ ok: url in files, json: async () => files[url] });
      new Function("fetch", "document", INS)(fetch, document);
      await settle(); await settle(); await settle();
      return els["fi-frontload"].innerHTML;
    };
    const line = await run(stats(0.0086, 0.0189, 0.0003), stats(0.01, 0.02, 0.001));
    ok(line.includes("20: +0.9% vs +0.0%"), `ASX compares with the matched mix: ${line}`);
    ok(line.includes("NASDAQ at 20: +1.0% vs +0.1%"), "NASDAQ too");
    const old = await run(stats(0.0086, 0.0189, null), null);
    ok(old.includes("20: +0.9% vs +1.9%"), "an older stats file without `matched` keeps working");
  }

  console.log(`phasemap_page.test.js: ${checks} checks passed`);
})().catch((e) => { console.error(e); process.exit(1); });
