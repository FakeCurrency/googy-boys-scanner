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
 *   UI100        (2026-10-20) a phone opens COMPACT unless a density is saved;
 *                COMPACT builds the head line only; the engine's closing
 *                "not financial advice" sentence never reaches the screen;
 *                engine tags left the head for "Why flagged" while ILLIQUID
 *                stays on it (spec: the tag can never be disabled).
 *
 * Sandboxed with `new Function(...)` (same realm), per the repo's JS-suite rule.
 */
"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(__dirname, "..", "public", "js", "phasemap.js"), "utf8");
const SHARED_SRC = fs.readFileSync(path.join(__dirname, "..", "public", "js", "phasemap-shared.js"), "utf8");
// the real shared helpers (window.PM), for the UI100 pins below
const REAL = (() => { const w = {}; new Function("window", SHARED_SRC)(w); return w.PM; })();

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

// The multi-lens strip is the one element phasemap.js creates, inserts and
// removes itself: a live node that remembers every body it was given. Its
// width (opts.strip.fit) is a function of the names drawn into it.
function stripEl(byId, log, fit) {
  const node = {
    id: "", className: "", _html: "", more: null, children: [],
    classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
    get innerHTML() { return this._html; },
    set innerHTML(v) {
      this._html = v; log.push(v);
      this.more = /data-conf-more/.test(v) ? stubEl("conf-more") : null;
    },
    querySelector(sel) { return sel === "[data-conf-more]" ? this.more : null; },
    remove() { if (byId[this.id] === this) delete byId[this.id]; },
    get scrollWidth() { return fit ? fit((this._html.match(/<a /g) || []).length, !!this.more) : 0; },
    get clientWidth() { return fit ? 266 : 0; },
  };
  return node;
}

function boot(initialMarket, opts = {}) {
  const els = {};
  const byId = {};
  const stripLog = [];
  const el = (sel) => (els[sel] = els[sel] || stubEl(sel));
  if (opts.strip) el("#pm-tabs").parentNode = { insertBefore: (n) => { byId[n.id] = n; } };
  const buttons = ["asx", "nasdaq", "crypto"].map((m) => {
    const b = stubEl(`btn-${m}`);
    b.dataset.market = m;
    return b;
  });
  const store = new Map([...(initialMarket ? [["pm-market", initialMarket]] : []),
                         ...Object.entries(opts.store || {})]);
  const localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
  };
  const document = {
    querySelector: (sel) => el(sel),
    querySelectorAll: (sel) => (sel === "#pm-market .market-btn" ? buttons : []),
    getElementById: (id) => byId[id] || null,
    createElement: (tag) => (opts.strip ? stripEl(byId, stripLog, opts.strip.fit) : stubEl(tag)),
    addEventListener() {},
    body: stubEl("body"),
    activeElement: null,
  };
  // every data fetch parks until the test resolves it (a status other than
  // 200 answers like a failed CDN request)
  const pending = {};
  const json = (body, status = 200) => ({ ok: status === 200, status, json: async () => body });
  const PM = {
    esc: (s) => String(s == null ? "" : s),
    fetchTimeout: (url) => new Promise((resolve) => { pending[url] = (body, status) => resolve(json(body, status)); }),
    loadConfluence: () => Promise.resolve({ of: () => null, all: () => [] }),
    staleBadgeHTML: () => "", loadFailKind: () => "unreachable", retryHTML: () => "",
    confluenceChipHTML: () => "", confluenceBannerHTML: () => "", headBadgesHTML: () => "",
    identityHTML: () => "", stepperHTML: () => "", ladderHTML: () => "", whyHTML: () => "",
    metricsHTML: () => "", glossaryHTML: () => "", toggleSpeak() {},
    warnTagsHTML: () => "", confluenceMarkHTML: () => "", stripDisclaimer: REAL.stripDisclaimer,
    ...(opts.PM || {}),
  };
  const winListeners = {};
  const window = { location: { href: "" }, innerWidth: 390,
    addEventListener: (ev, fn) => { winListeners[ev] = fn; } };
  if ("phone" in opts) window.matchMedia = (q) => ({ matches: !!opts.phone && /max-width: 680px/.test(q) });
  new Function("window", "document", "localStorage", "PM", SRC)(window, document, localStorage, PM);
  const click = (m) => buttons.find((b) => b.dataset.market === m).listeners.click[0]();
  return { els, store, pending, click, byId, stripLog, window, winListeners };
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

  // 5. UI100 #67: a phone with no saved density opens COMPACT; a saved pick
  //    wins; a PC (or no matchMedia) keeps FULL.
  {
    const dens = async (opts) => {
      const app = boot("asx", opts);
      await deliver(app, "asx", payload("asx", ["BHP"], { as_of: "2026-10-13" }));
      return app.els["#pm-list"].className;
    };
    ok((await dens({ phone: true })).includes("pm-density-compact"), "a phone opens COMPACT");
    ok((await dens({ phone: true, store: { "pm-density": "full" } })).includes("pm-density-full"),
      "a saved density wins on a phone");
    ok((await dens({ phone: false })).includes("pm-density-full"), "a PC keeps FULL");
    ok((await dens({})).includes("pm-density-full"), "no matchMedia: FULL");
  }

  // 6. UI100 #68/#71: COMPACT builds the head line only; FULL shows the
  //    narrative without the engine's closing disclaimer sentence.
  {
    const narr = "Displacement confirmed on 2026-10-13. Analysis only — not financial advice.";
    const run = async (density) => {
      const app = boot("asx", { store: { "pm-density": density } });
      app.pending["data/phasemap/asx/latest.json"](payload("asx", ["BHP"], { as_of: "2026-10-13" }));
      app.pending["data/phasemap/asx/narrations.json"]({ run_date: "2026-10-14", narrations: { "BHP|bullish": narr } });
      await settle(); await settle();
      return app.els["#pm-list"].innerHTML;
    };
    const compact = await run("compact");
    ok(compact.includes("BHP") && compact.includes("pm-card-head"), "COMPACT renders the head line");
    ok(!/pm-ladder|pm-narration|pm-metrics|pm-why/.test(compact), "COMPACT builds nothing under the head");
    const full = await run("full");
    ok(full.includes("Displacement confirmed on 2026-10-13.") && /pm-metrics/.test(full), "FULL shows the narrative and stats");
    ok(!/financial advice/i.test(full), "the disclaimer sentence never reaches the screen");
    ok(!/pm-metrics/.test(await run("cozy")), "COZY skips the stats line it never showed");
  }

  // 7. UI100 shared helpers: the head keeps side · state · grade; engine tags
  //    and the regime moved into "Why flagged"; ILLIQUID keeps a head chip
  //    outside the extras box that may drop a chip (spec: never disabled).
  {
    const rec = { ticker: "X", direction: "bullish", state: "RUNNING", tier: "A+", regime: "ROTATION",
                  tags: ["FAST_FLIP", "ANCHOR_CONTEXT", "ILLIQUID", "SOME_NEW_TAG"], metrics: {}, zones: [] };
    const head = REAL.headBadgesHTML(rec);
    ok(/LONG/.test(head) && /RUNNING/.test(head) && /A\+/.test(head), "head: side, state, grade");
    ok(!/FAST_FLIP|ANCHOR_CONTEXT|ROTATION|ILLIQUID/.test(head), "head: no engine tags, no regime");
    const warn = REAL.warnTagsHTML(rec);
    ok(/ILLIQUID/.test(warn) && !/FAST_FLIP|ANCHOR/.test(warn), "warnings: ILLIQUID only");
    const why = REAL.whyListHTML(rec);
    ["FAST_FLIP", "ANCHOR_CONTEXT", "ROTATION", "ILLIQUID", "SOME_NEW_TAG"].forEach((t) =>
      ok(why.includes(t), `"Why flagged" carries ${t}`));
    ok(!/<ul>/.test(REAL.whyHTML(rec, true)) && /<ul>/.test(REAL.whyHTML(rec)), "whyHTML(rec, true) is the summary only");
    ok(/headBadgesHTML\(rec\)\}\$\{PM\.warnTagsHTML\(rec\)\}/.test(SRC) && !/pm-head-extra[^`]*warnTagsHTML/.test(SRC),
      "phasemap.js puts the warnings beside the grade, outside the extras box");
    eq(REAL.stripDisclaimer("A. B. Analysis only — not financial advice."), "A. B.", "the closing sentence goes");
    eq(REAL.stripDisclaimer("No advice talk here."), "No advice talk here.", "other text is untouched");
  }

  // 8. UI100 #75: the strip and the compact mark keep the evidence note.
  {
    const rows = [{ ticker: "A", side: "long", lenses: ["VIVEK", "PHASEMAP"], count: 2 },
                  { ticker: "B", side: "long", lenses: ["VIVEK", "PHASEMAP"], count: 2 }];
    const strip = REAL.confluenceBannerHTML(rows, "asx", 1);
    ok(strip.includes(REAL.CONFLUENCE_UNPROVEN), "the strip carries CONFLUENCE_UNPROVEN");
    ok(/data-conf-more[^>]*>\+1 more</.test(strip), "+N more is a button");
    ok(REAL.confluenceMarkHTML(rows[0], "PHASEMAP").includes(REAL.CONFLUENCE_UNPROVEN),
      "the compact multi-lens mark carries CONFLUENCE_UNPROVEN");
  }

  // ── UI100 review (2026-10-20): the defects two verifiers reproduced ─────
  const conflFor = (m) => {
    const rows = Array.from({ length: 12 }, (_, i) =>
      ({ ticker: `${m.toUpperCase()}${i}`, side: "long", lenses: ["VIVEK", "PHASEMAP"], count: 2 }));
    return { of: (t) => rows.find((r) => r.ticker === t) || null, all: () => rows };
  };
  const stripPM = { loadConfluence: (m) => Promise.resolve(conflFor(m)),
                    confluenceBannerHTML: REAL.confluenceBannerHTML };

  // 9. #3 (race guard): the multi-lens strip belongs to the market it was
  //    read for. state.confl outlived a failed switch, so "+N more" or a
  //    rotate after ASX -> NASDAQ (NASDAQ's file failing) redrew 39 ASX
  //    names linking to chart.html?m=nasdaq&s=ADH.
  {
    const app = boot("asx", { strip: {}, PM: stripPM });
    await deliver(app, "asx", payload("asx", ["BHP"], { as_of: "2026-10-13" }));
    const strip = app.byId["conf-banner"];
    ok(strip && strip.innerHTML.includes("m=asx&s=ASX0") && strip.more, "the ASX strip draws, with its +N more");
    const tapMore = strip.more.listeners.click[0];
    app.click("nasdaq");
    ok(!app.byId["conf-banner"], "a market switch takes the other market's strip down at once");
    app.pending["data/phasemap/nasdaq/latest.json"](null, 503);
    app.pending["data/phasemap/nasdaq/narrations.json"](null, 503);
    await settle(); await settle();
    ok(/Couldn't load the NASDAQ/.test(app.els["#pm-sub"].textContent), "NASDAQ's load failed");
    tapMore();
    ok(!app.byId["conf-banner"], '"+N more" after the failed load draws no strip');
    app.window.innerWidth = 360;
    app.winListeners.resize();
    await new Promise((r) => setTimeout(r, 260));
    ok(!app.byId["conf-banner"], "nor does a rotate");
    ok(!app.stripLog.some((h) => /m=nasdaq[^"]*s=ASX/.test(h)), "an ASX name never links to the NASDAQ chart");
  }

  // 10. #2: the one-line phone strip drops whole names until "+N more"
  //     fits (at 320px it sat past the clip: 75 NASDAQ names unreachable).
  //     Here a name is 80px, the label 70, the opener 60, the strip 266.
  {
    const fit = (names, more) => 70 + 80 * names + (more ? 60 : 0);
    const app = boot("asx", { phone: true, strip: { fit }, store: { "pm-density": "compact" }, PM: stripPM });
    await deliver(app, "asx", payload("asx", ["BHP"], { as_of: "2026-10-13" }));
    const html = app.byId["conf-banner"].innerHTML;
    eq((html.match(/<a /g) || []).length, 1, "the strip keeps the names that fit beside the opener");
    ok(/data-conf-more[^>]*>\+11 more</.test(html), "and the opener counts every name it folded");
    ok(html.includes(REAL.CONFLUENCE_UNPROVEN), "the strip keeps CONFLUENCE_UNPROVEN");
  }

  // CSS rules as {sel, body}, comments out, @media bodies flattened
  const CSS = fs.readFileSync(path.join(__dirname, "..", "public", "css", "phasemap.css"), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "");
  const RULES = [...CSS.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .map((m) => ({ sel: m[1].trim(), body: m[2] }));
  const targets = (re) => RULES.filter((r) => r.sel.split(",").some((s) => re.test(s.trim())));

  // 11. #1 (spec: the ILLIQUID tag can never be hidden): the COMPACT head
  //     wraps rather than run a warning past the card edge (the nowrap line
  //     clipped it on 200 of 466 ASX warning rows at 320px), nothing hides
  //     or clips a warning chip, and the extras box -- the only place a chip
  //     may drop -- holds CHART → but never a warning.
  {
    const head = targets(/\.pm-density-compact\b.*\.pm-card-head$/);
    ok(head.some((r) => /flex-wrap:\s*wrap\b/.test(r.body)), "the COMPACT head line wraps");
    ok(!head.some((r) => /nowrap/.test(r.body)), "no rule pins the COMPACT head to one line");
    const warn = targets(/(\.pm-tag-illiquid|\.pm-tag-halt|\.pm-card-head\s*>\s*\.pm-tag)$/);
    ok(warn.length >= 3, `the warning chip rules are found (${warn.length})`);
    ok(!warn.some((r) => /display:\s*none|visibility:\s*hidden|overflow:|max-width|text-overflow/.test(r.body)),
      "no rule hides, clips or shortens a warning chip");
    ok(/pm-head-extra">\$\{extra\}\$\{cue\}/.test(SRC), "COMPACT puts CHART → last in the extras box");
    const extra = targets(/\.pm-density-compact \.pm-head-extra$/);
    ok(extra.some((r) => /flex:\s*1 1 0\b/.test(r.body)), "the extras box never opens a line of its own (basis 0)");
  }

  // 12. #4: below 381px the stepper keeps the step before the current one,
  //     the current one and the next (the whole path ran past the card at
  //     360-375px: "… RUNNING › COM…"); the rest stay in the markup, marked.
  {
    const rec = (state, metrics = {}) => ({ state, metrics });
    const cases = [rec("TRAP_SET"), rec("SWEPT"), rec("DISPLACED"), rec("RUNNING"), rec("COMPLETE"),
      rec("STALLED", { sweep_date: "x", displacement_date: "y" }), rec("DEAD", { sweep_date: "x" }), rec("STALLED")];
    for (const r of cases) {
      const html = REAL.stepperHTML(r);
      const steps = html.match(/class="pm-step [^"]*"/g);
      const shown = steps.filter((c) => !/\bis-(far|later)\b/.test(c));
      ok(shown.length <= 3 && shown.some((c) => /\bis-now\b/.test(c)),
        `${r.state}: at most 3 steps on a narrow phone, the current one among them (${shown.length})`);
      const folds = (html.match(/pm-step-fold/g) || []).length;
      const arrows = (html.match(/class="pm-step-arrow"/g) || []).length;
      eq(arrows, shown.length - 1 + folds, `${r.state}: one arrow between each shown step (and in each "…")`);
    }
    eq(REAL.stepperHTML(rec("RUNNING")).match(/class="pm-step /g).length, 5, "every step stays in the markup");
    ok(/@media \(max-width: 380px\)\s*\{[^@]*\.pm-step\.is-far[^}]*display:\s*none/.test(CSS),
      "phasemap.css folds is-far / is-later steps below 381px");
  }

  // 13. #7: the stepper dims by colour, never opacity (muted-2 at 0.6 read
  //     3.8:1 on the card, under the 4.5:1 the contrast gate holds text to).
  {
    const step = targets(/\.pm-step(per|-arrow|-fold)?\b/);
    ok(step.length >= 6, `the stepper rules are found (${step.length})`);
    ok(!step.some((r) => /opacity/.test(r.body)), "no stepper text carries an opacity");
  }

  // 14. #5: two-up, the loading skeletons take a whole row each.
  ok(/@media \(min-width: 1100px\)\s*\{[^@]*\.pm-list > \.pm-skel\s*\{\s*grid-column:\s*1 \/ -1/.test(CSS),
    "the loading skeletons span the 2-up grid");

  console.log(`phasemap_page.test.js: ${checks} checks passed`);
})().catch((e) => { console.error(e); process.exit(1); });
