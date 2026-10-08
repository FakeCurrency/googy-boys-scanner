#!/usr/bin/env node
/* The lens pages (PhaseMap, Specs, Momentum): which market a load belongs to,
 * and what PhaseMap's FLASHED cue compares against. Audit 2026-10-08.
 *
 *   #51  phasemap.js load() kept no record of the market it was started for.
 *        Tap CRYPTO while ASX's ~1 MB scan is still in flight and whichever
 *        answer landed LAST was drawn under the market selected NOW: ASX cards
 *        under the CRYPTO tab, chart links of m=crypto&s=<ASX ticker>, and
 *        pm-seen:crypto (the "since you last checked" memory) overwritten with
 *        ASX keys. The confluence fetch had the same gap.
 *   #52  FLASHED compared event dates with run_date, the MELBOURNE date the
 *        nightly job ran. The job lands after Melbourne midnight, so no event
 *        date ever equalled it and the cue never rendered.
 *   #83  specs.js: the same missing guard on the spec file and its confluence.
 *   #84  momentum.js guarded only its success path: a late FAILURE of the
 *        previous market wiped the market now shown, and the previous market's
 *        "scanned ..." stamp survived on a loading or no-data page.
 *
 * Everything here EXECUTES the shipped page scripts (and the real
 * phasemap-shared.js under them) against a fake DOM and a fake network whose
 * every fetch waits until the test answers it, so the tests can land answers
 * in exactly the order a slow phone does. Sandboxes are `new Function`, not
 * vm (same realm, so no cross-realm surprises), per the repo's JS-suite rule.
 */
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const JS = (f) => fs.readFileSync(path.join(ROOT, "public", "js", f), "utf8");
const SHARED = JS("phasemap-shared.js");

let passed = 0, failed = 0;
const Q = [];
const test = (n, f) => Q.push({ n, f });
const suite = (n) => Q.push({ s: n });

/* ── a network that answers only when told to ────────────────────────────── */
function makeNet() {
  const pending = [];
  const fetch = (url) => new Promise((resolve, reject) =>
    pending.push({ url: String(url).split("?")[0], resolve, reject }));
  const pick = (url, last) => {
    const urls = pending.map((p) => p.url);
    const i = last ? urls.lastIndexOf(url) : urls.indexOf(url);
    if (i < 0) throw new Error(`no fetch of ${url} is waiting (waiting: ${urls.join(", ") || "none"})`);
    return pending.splice(i, 1)[0];
  };
  const reply = (status, body) => ({
    ok: status >= 200 && status < 300, status,
    json: () => Promise.resolve(JSON.parse(JSON.stringify(body == null ? {} : body))),
  });
  return {
    fetch,
    waiting: (url) => pending.filter((p) => p.url === url).length,
    ok(url, body, last) { pick(url, last).resolve(reply(200, body)); },
    status(url, code, last) { pick(url, last).resolve(reply(code, {})); },
  };
}
// setImmediate runs after the microtask queue drains; a few rounds settle any
// await chain the pages build (fetch -> json -> narrations -> ...).
const flush = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r)); };

/* ── a DOM just big enough for these pages ──────────────────────────────────
 * Every selector resolves to ONE memoised stub, so the test can read what the
 * page wrote into "#pm-sub" or "#conf-banner". querySelectorAll answers only
 * for the button groups a test needs to click; everything else is empty. */
function makeDom(groups) {
  const els = new Map();
  const el = (key) => {
    if (els.has(key)) return els.get(key);
    const on = {};
    const cls = new Set();
    const e = {
      key, innerHTML: "", textContent: "", className: "", title: "", value: "",
      hidden: false, disabled: false, dataset: {}, style: {},
      classList: {
        toggle: (c, force) => ((force === undefined ? !cls.has(c) : force) ? cls.add(c) : cls.delete(c)),
        add: (c) => cls.add(c), remove: (c) => cls.delete(c), contains: (c) => cls.has(c),
      },
      setAttribute() {}, getAttribute: () => null,
      addEventListener(t, fn) { (on[t] = on[t] || []).push(fn); },
      removeEventListener() {},
      fire(t, ev) {
        (on[t] || []).forEach((fn) => fn(ev || {
          target: { closest: () => null }, preventDefault() {}, stopPropagation() {} }));
      },
      querySelector: (s) => el(key + " " + s),
      querySelectorAll: () => [],
      parentNode: { insertBefore() {} },
      remove() { e.innerHTML = ""; },
      focus() {}, blur() {}, select() {}, scrollIntoView() {},
    };
    els.set(key, e);
    return e;
  };
  const group = {};
  for (const [sel, items] of Object.entries(groups || {})) {
    group[sel] = items.map(([k, v]) => { const b = el(`${sel}[${k}=${v}]`); b.dataset[k] = v; return b; });
  }
  let n = 0;
  const document = {
    readyState: "complete",
    querySelector: (s) => el(s),
    querySelectorAll: (s) => group[s] || [],
    getElementById: (id) => el("#" + id),
    createElement: (tag) => el(`<new ${tag} ${n++}>`),
    addEventListener() {},
    body: el("body"),
    activeElement: null,
  };
  return { document, el, group };
}

function makeStorage(seed) {
  const m = new Map(Object.entries(seed || {}));
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    dump: () => Object.fromEntries(m),
  };
}

/* Boot phasemap-shared.js, then the page, in one realm. `fetch` is the only
 * network seam: PM.fetchTimeout and PM.loadConfluence both end in it.
 * AbortSignal is passed as undefined so fetchTimeout arms no real timers. */
function boot(page, { groups, storage, location, extra } = {}) {
  const net = makeNet();
  const dom = makeDom(groups);
  const ls = makeStorage(storage);
  const win = {};
  new Function("window", "document", "fetch", "AbortSignal", "localStorage", SHARED)(
    win, dom.document, net.fetch, undefined, ls);
  const names = ["window", "document", "localStorage", "PM", "CSS", "prompt", "fetch",
                 "AbortSignal", "location", "history"];
  const vals = [win, dom.document, ls, win.PM, { escape: (s) => s }, () => null, net.fetch,
                undefined, location || { search: "", href: "https://x.test/" },
                { replaceState() {} }];
  new Function(...names, JS(page))(...vals);
  return Object.assign({ net, dom, ls, el: dom.el, PM: win.PM }, extra || {});
}

/* ── PhaseMap fixtures ───────────────────────────────────────────────────── */
const pmRec = (ticker, metrics, over) => Object.assign({
  ticker, direction: "bullish", state: "RUNNING", tier: "A", tags: [], regime: "ROTATION",
  zones: [], next: "", name: ticker + " Ltd", sector: "",
  metrics: Object.assign({ close: 1, sweep_date: "2026-10-01", displacement_date: "2026-10-02" }, metrics),
}, over || {});
const pmScan = (run_date, universe, results) =>
  ({ run_date, ruleset_version: "1.3.1", universe_size: universe, results });
const ASX_SCAN = pmScan("2026-10-08", 1923, [pmRec("ASXA"), pmRec("ASXB")]);
const CRY_SCAN = pmScan("2026-10-08", 201, [pmRec("CRYA")]);
const NARR = (rd) => ({ run_date: rd, narrations: {} });

const PM_GROUPS = {
  "#pm-market .market-btn": [["market", "asx"], ["market", "nasdaq"], ["market", "crypto"]],
  "#pm-tabs .pm-tab": [["view", "all"]],
};
const pmBoot = (storage) => {
  const p = boot("phasemap.js", { groups: PM_GROUPS, storage });
  p.click = (m) => p.dom.group["#pm-market .market-btn"].find((b) => b.dataset.market === m).fire("click");
  p.tab = (v) => p.dom.group["#pm-tabs .pm-tab"].find((b) => b.dataset.view === v).fire("click");
  p.land = (m, scan, last) => {
    p.net.ok(`data/phasemap/${m}/latest.json`, scan, last);
    p.net.ok(`data/phasemap/${m}/narrations.json`, NARR(scan.run_date), last);
  };
  p.sub = () => p.el("#pm-sub").innerHTML || p.el("#pm-sub").textContent;
  p.list = () => p.el("#pm-list").innerHTML;
  p.cards = () => p.list().split("<article").slice(1);
  return p;
};

suite("#51 PhaseMap: an answer is applied only to the load that asked for it");

test("a slow ASX scan landing AFTER crypto's does not take over the CRYPTO tab", async () => {
  const p = pmBoot();
  p.click("crypto");                       // ASX load still in flight
  p.land("crypto", CRY_SCAN);
  await flush();
  assert.ok(/CRYPTO/.test(p.sub()) && /201 tickers/.test(p.sub()), `crypto header first: ${p.sub()}`);
  p.land("asx", ASX_SCAN);                 // the old, larger payload lands last
  await flush();
  assert.ok(/CRYPTO · scan 2026-10-08/.test(p.sub()), `the header must stay crypto's: ${p.sub()}`);
  assert.ok(/201 tickers scanned · 1 results/.test(p.sub()),
    `ASX's universe/result count must not appear under CRYPTO: ${p.sub()}`);
  assert.ok(/CRYA/.test(p.list()) && !/ASXA|ASXB/.test(p.list()),
    "the cards must stay crypto's — ASX cards under CRYPTO link to m=crypto&s=<ASX ticker>");
  assert.ok(!/m=crypto&s=ASX/.test(p.list()));
});

test("the late ASX answer never overwrites crypto's 'since you last checked' memory", async () => {
  const p = pmBoot();
  p.click("crypto");
  p.land("crypto", CRY_SCAN);
  await flush();
  p.land("asx", ASX_SCAN);
  await flush();
  const seen = JSON.parse(p.ls.getItem("pm-seen:crypto") || "null");
  assert.ok(seen, "crypto's own load records what it saw");
  assert.deepEqual(Object.keys(seen.states), ["CRYA|bullish"],
    "pm-seen:crypto holds crypto's keys only — ASX keys there mark every crypto row NEW next visit");
  assert.equal(p.ls.getItem("pm-seen:asx"), null,
    "an abandoned ASX load must not record an ASX visit the owner never saw");
});

test("a late ASX FAILURE does not replace crypto's loaded page with ASX's error", async () => {
  const p = pmBoot();
  p.click("crypto");
  p.land("crypto", CRY_SCAN);
  await flush();
  p.net.status("data/phasemap/asx/latest.json", 503);
  p.net.status("data/phasemap/asx/narrations.json", 503);
  await flush();
  assert.ok(/CRYPTO · scan/.test(p.sub()), `crypto's header survives: ${p.sub()}`);
  assert.ok(!/Couldn't load the ASX/.test(p.sub() + p.list()));
  assert.ok(/CRYA/.test(p.list()), "and so do crypto's cards");
});

test("an older ASX confluence landing after the switch does not fill crypto's banner", async () => {
  const p = pmBoot();
  p.land("asx", ASX_SCAN);                 // ASX renders; its confluence is now in flight
  await flush();
  p.click("crypto");
  p.land("crypto", CRY_SCAN);
  await flush();
  p.net.ok("data/crypto_vivek.json", { results: [] });
  p.net.ok("data/phasemap/crypto/latest.json", CRY_SCAN);
  await flush();
  // ASX's confluence finally resolves: AS1 is VIVEK long + PhaseMap RUNNING bullish.
  p.net.ok("data/asx_vivek.json", { results: [{ symbol: "AS1", dir: "LONG", grade: "A" }] });
  p.net.ok("data/phasemap/asx/latest.json", pmScan("2026-10-08", 1923, [pmRec("AS1")]));
  p.net.ok("data/asx_spec.json", { results: [] });
  await flush();
  const banner = p.el("#conf-banner").innerHTML;
  assert.ok(!/AS1/.test(banner),
    `crypto's multi-lens banner must not list ASX names (each would link m=crypto&s=AS1): ${banner}`);
});

test("ASX -> crypto -> ASX: the FIRST ASX answer landing last does not erase the NEW badges", async () => {
  // Why the guard is a load SEQUENCE and not a market check: the first and
  // third loads are both ASX, so a market check lets the first one re-run the
  // since-you-last-checked diff against the snapshot the third just stored —
  // same run_date, so every NEW badge and the catch-up banner vanish.
  const p = pmBoot({ "pm-seen:asx": JSON.stringify({ run_date: "2026-10-07", states: { "OLD|bullish": "RUNNING" } }) });
  p.click("crypto");
  p.click("asx");
  p.land("asx", ASX_SCAN, true);           // the third load lands first
  await flush();
  assert.ok(/pm-tag-new/.test(p.list()), "the newest ASX load marks names NEW");
  assert.ok(/SINCE YOU LAST CHECKED/.test(p.el("#pm-since").innerHTML));
  p.land("asx", ASX_SCAN);                 // the first, abandoned ASX load
  p.land("crypto", CRY_SCAN);              // and the abandoned crypto one
  await flush();
  assert.ok(/pm-tag-new/.test(p.list()), "the NEW badges survive the stale answer");
  assert.ok(/SINCE YOU LAST CHECKED/.test(p.el("#pm-since").innerHTML), "and so does the banner");
  assert.ok(/ASX · scan/.test(p.sub()) && /ASXA/.test(p.list()), "and the page is still ASX's");
});

test("a switch during the narrations refetch still drops the old market's answer", async () => {
  // The mismatched-sidecar path awaits one more fetch AFTER latest.json has
  // landed: the answer must be checked again after that await, not only before.
  const p = pmBoot();
  p.net.ok("data/phasemap/asx/latest.json", ASX_SCAN);
  p.net.ok("data/phasemap/asx/narrations.json", NARR("2026-10-07"));   // previous scan's sidecar
  await flush();
  assert.equal(p.net.waiting("data/phasemap/asx/narrations.json"), 1, "the page refetches the sidecar");
  p.click("crypto");
  p.land("crypto", CRY_SCAN);
  await flush();
  p.net.ok("data/phasemap/asx/narrations.json", NARR("2026-10-08"));   // the refetch lands last
  await flush();
  assert.ok(/CRYPTO · scan/.test(p.sub()) && /CRYA/.test(p.list()) && !/ASXA/.test(p.list()),
    `the refetch must not carry ASX onto the CRYPTO tab: ${p.sub()}`);
});

test("an abandoned load does not go on to refetch its sidecar", async () => {
  const p = pmBoot();
  p.click("crypto");
  p.net.ok("data/phasemap/asx/latest.json", ASX_SCAN);
  p.net.ok("data/phasemap/asx/narrations.json", NARR("2026-10-07"));
  await flush();
  assert.equal(p.net.waiting("data/phasemap/asx/narrations.json"), 0,
    "nobody is looking at ASX any more — no second request for it");
});

test("while the next market loads, a re-render does not draw the previous market's cards", async () => {
  const p = pmBoot();
  p.land("asx", ASX_SCAN);
  await flush();
  assert.ok(/ASXA/.test(p.list()));
  p.click("crypto");                       // crypto in flight; skeleton on screen
  p.tab("all");                            // any filter click calls render()
  assert.ok(!/ASXA|ASXB/.test(p.list()),
    "ASX cards must not be redrawn under the CRYPTO tab (their links would read m=crypto)");
});

suite("#52 PhaseMap: FLASHED is the scan's newest bar, not the Melbourne run date");

test("rows whose sweep or displacement printed on the newest bar are FLASHED", async () => {
  // run_date 2026-10-08 is the Melbourne date the job ran; the newest bar in
  // the scan is 2026-10-07. Under the old comparison nothing could ever match.
  const scan = pmScan("2026-10-08", 1923, [
    pmRec("DISP", { sweep_date: "2026-10-03", displacement_date: "2026-10-07" }),
    pmRec("SWEP", { sweep_date: "2026-10-07", displacement_date: undefined }, { state: "SWEPT" }),
    pmRec("OLDR", { sweep_date: "2026-10-01", displacement_date: "2026-10-06" }),
  ]);
  const p = pmBoot({ "pm-view": "all" });
  p.land("asx", scan);
  await flush();
  const flashed = (t) => p.cards().find((c) => c.includes(`pm-ticker">${t}<`)).includes("FLASHED");
  assert.ok(flashed("DISP"), "a displacement on the newest bar is FLASHED");
  assert.ok(flashed("SWEP"), "so is a sweep on the newest bar");
  assert.ok(!flashed("OLDR"), "an event one bar older is not");
});

test("a scan with no dated events flashes nothing and does not throw", async () => {
  const scan = pmScan("2026-10-08", 10, [pmRec("NODT", { sweep_date: undefined, displacement_date: undefined })]);
  const p = pmBoot({ "pm-view": "all" });
  p.land("asx", scan);
  await flush();
  assert.equal(p.cards().length, 1);
  assert.ok(!/FLASHED/.test(p.list()));
});

test("the cue fires on today's REAL published scans (it never did against run_date)", async () => {
  // Sorted FRESH over every state, the first card carries the scan's newest
  // event, so it must be FLASHED whenever the file has a dated event at all.
  for (const m of ["asx", "nasdaq", "crypto"]) {
    const f = path.join(ROOT, "public", "data", "phasemap", m, "latest.json");
    if (!fs.existsSync(f)) continue;
    const scan = JSON.parse(fs.readFileSync(f, "utf8"));
    const dated = (scan.results || []).some((r) => r.metrics && (r.metrics.sweep_date || r.metrics.displacement_date));
    if (!dated) continue;
    const p = pmBoot({ "pm-market": m, "pm-view": "all", "pm-sort": "fresh" });
    p.land(m, scan);
    await flush();
    assert.ok(p.cards().length > 0, `${m}: no cards rendered`);
    assert.ok(/FLASHED/.test(p.cards()[0]), `${m}: the freshest card is not FLASHED`);
  }
});

/* ── Specs fixtures ──────────────────────────────────────────────────────── */
const spRow = (symbol) => ({ symbol, name: symbol + " Ltd", sector: "", grade: "A", score: 7,
  score_max: 11, spike_ratio: 3.4, price: 0.2, entry: 0.2, stop: 0.17, target: 0.3, rr: 2.5, chips: [] });
const spScan = (universe, cur, rows) => ({ generated_at: "2026-10-08T00:00:00Z", universe_size: universe,
  currency_symbol: cur, results: rows });
const ASX_SPEC = spScan(2047, "A$", [spRow("CXZ")]);
const NAS_SPEC = spScan(1430, "$", [spRow("NVX")]);
const spBoot = (market) => {
  const p = boot("specs.js", {
    groups: { "#sp-market .market-btn": [["market", "asx"], ["market", "nasdaq"]] },
    storage: market ? { "sp-market": market } : {},
  });
  p.click = (m) => p.dom.group["#sp-market .market-btn"].find((b) => b.dataset.market === m).fire("click");
  p.title = () => p.el("#sp-title").textContent;
  p.sub = () => p.el("#sp-sub").innerHTML || p.el("#sp-sub").textContent;
  p.list = () => p.el("#sp-list").innerHTML;
  p.pills = () => p.el("#sp-pills").innerHTML;
  return p;
};

suite("#83 Specs: the same guard on the spec file and its confluence");

test("the old NASDAQ spec file landing after ASX's does not replace the ASX page", async () => {
  const p = spBoot("nasdaq");
  p.click("asx");
  p.net.ok("data/asx_spec.json", ASX_SPEC);
  await flush();
  assert.equal(p.title(), "SPECS · ASX · 1 setups");
  p.net.ok("data/nasdaq_spec.json", NAS_SPEC);
  await flush();
  assert.equal(p.title(), "SPECS · ASX · 1 setups");
  assert.ok(/2047 names scanned/.test(p.sub()), `ASX's universe stays in the subtitle: ${p.sub()}`);
  assert.ok(/CXZ/.test(p.list()) && !/NVX/.test(p.list()),
    "ASX's rows stay — NASDAQ rows under ASX link to m=asx&s=NVX in the wrong currency");
});

test("an older NASDAQ confluence landing late does not strip ASX's multi-lens marks", async () => {
  const p = spBoot("nasdaq");
  p.net.ok("data/nasdaq_spec.json", NAS_SPEC);   // NASDAQ renders; its confluence is in flight
  await flush();
  p.click("asx");
  p.net.ok("data/asx_spec.json", ASX_SPEC);
  await flush();
  // ASX's confluence: CXZ is VIVEK long + a spec -> a 2-lens alignment.
  p.net.ok("data/asx_vivek.json", { results: [{ symbol: "CXZ", dir: "LONG", grade: "A" }] });
  p.net.ok("data/phasemap/asx/latest.json", { results: [] });
  p.net.ok("data/asx_spec.json", ASX_SPEC);
  await flush();
  assert.ok(/Multi-lens <b>1<\/b>/.test(p.pills()), `ASX's pill counts CXZ: ${p.pills()}`);
  assert.ok(/2-LENS/.test(p.list()));
  // ...then NASDAQ's slower (~1.9 MB) confluence resolves.
  p.net.ok("data/nasdaq_vivek.json", { results: [] });
  p.net.ok("data/phasemap/nasdaq/latest.json", { results: [] });
  p.net.ok("data/nasdaq_spec.json", NAS_SPEC);
  await flush();
  assert.ok(/Multi-lens <b>1<\/b>/.test(p.pills()), `the pill must stay ASX's: ${p.pills()}`);
  assert.ok(/2-LENS/.test(p.list()), "and CXZ keeps its 2-LENS chip");
});

test("a late NASDAQ failure does not wipe the loaded ASX page", async () => {
  const p = spBoot("nasdaq");
  p.click("asx");
  p.net.ok("data/asx_spec.json", ASX_SPEC);
  await flush();
  p.net.status("data/nasdaq_spec.json", 503);
  await flush();
  assert.equal(p.title(), "SPECS · ASX · 1 setups");
  assert.ok(!/NASDAQ/.test(p.sub()), `no NASDAQ error under ASX: ${p.sub()}`);
  assert.ok(/CXZ/.test(p.list()));
});

test("ASX -> NASDAQ -> ASX: the first ASX request failing last does not wipe the third's page", async () => {
  // Same market, older request — why the guard is a load sequence, not a market check.
  const p = spBoot("asx");
  p.click("nasdaq");
  p.click("asx");
  p.net.ok("data/asx_spec.json", ASX_SPEC, true);   // the newest ASX load
  await flush();
  assert.equal(p.title(), "SPECS · ASX · 1 setups");
  p.net.status("data/asx_spec.json", 503);          // the first, abandoned ASX load
  await flush();
  assert.equal(p.title(), "SPECS · ASX · 1 setups");
  assert.ok(/CXZ/.test(p.list()) && !/connection problem/.test(p.sub()));
});

/* ── Momentum fixtures ───────────────────────────────────────────────────── */
const moRow = (symbol) => ({ symbol, name: symbol + " Inc", rule_b: true, rule_b_direction: "bull",
  rule_b_score: 2, rule_b_bars_ago: 0, direction: "bull", close: 1, rsi: 50, dollar_adv_20: 1 });
const moScan = (rows, gen) => ({ generated_at: gen || "2026-10-07T06:18:00Z", mode: "A",
  last_closed_bar: "2026-10-07", summary: { scanned: rows.length, skipped_gates: 0 }, results: rows });
const moBoot = (m) => {
  const p = boot("momentum.js", {
    groups: { "#mo-market .market-btn": [["market", "asx"], ["market", "nasdaq"], ["market", "crypto"]] },
    location: { search: `?m=${m || "asx"}`, href: `https://x.test/momentum.html?m=${m || "asx"}` },
  });
  p.click = (mk) => {
    const b = p.dom.group["#mo-market .market-btn"].find((x) => x.dataset.market === mk);
    p.el("#mo-market").fire("click", { target: { closest: (s) => (s === ".market-btn" ? b : null) } });
  };
  p.title = () => p.el("#mo-title").textContent;
  p.stamp = () => p.el("#mo-stamp").textContent;
  p.list = () => p.el("#mo-list").innerHTML;
  return p;
};

suite("#84 Momentum: a late failure, and the stamp a market leaves behind");

test("a late ASX failure does not wipe NASDAQ's loaded page", async () => {
  const p = moBoot("asx");
  p.click("nasdaq");
  p.net.ok("data/momentum/nasdaq.json", moScan([moRow("NQ1")]));
  await flush();
  assert.equal(p.title(), "MOMENTUM · 1 name");
  p.net.status("data/momentum/asx.json", 503);   // e.g. the 20 s fetchTimeout abort
  await flush();
  assert.equal(p.title(), "MOMENTUM · 1 name", "NASDAQ's page must survive ASX's late failure");
  assert.ok(/NQ1/.test(p.list()) && !/connection problem/.test(p.list()));
});

test("a late ASX SUCCESS does not replace NASDAQ's page either (the guard that was already there)", async () => {
  const p = moBoot("asx");
  p.click("nasdaq");
  p.net.ok("data/momentum/nasdaq.json", moScan([moRow("NQ1")]));
  await flush();
  p.net.ok("data/momentum/asx.json", moScan([moRow("AX1"), moRow("AX2")]));
  await flush();
  assert.equal(p.title(), "MOMENTUM · 1 name");
  assert.ok(/NQ1/.test(p.list()) && !/AX1/.test(p.list()));
});

test("ASX -> NASDAQ -> ASX: the first ASX request failing last does not wipe the second's data", async () => {
  const p = moBoot("asx");
  p.click("nasdaq");
  p.click("asx");
  p.net.ok("data/momentum/asx.json", moScan([moRow("AX1")]), true);   // the newest ASX load
  await flush();
  assert.ok(/AX1/.test(p.list()));
  p.net.status("data/momentum/asx.json", 503);   // the first ASX load, abandoned
  await flush();
  assert.ok(/AX1/.test(p.list()), "same market, older request: still not allowed to touch the page");
  assert.equal(p.title(), "MOMENTUM · 1 name");
});

test("switching market clears the previous market's stamp and rows while loading, and on no-data", async () => {
  const p = moBoot("asx");
  p.net.ok("data/momentum/asx.json", moScan([moRow("AX1")]));
  await flush();
  assert.ok(/^scanned /.test(p.stamp()), "ASX shows its scan time");
  p.click("crypto");
  assert.equal(p.title(), "MOMENTUM · loading…");
  assert.equal(p.stamp(), "", "the loading page must not carry ASX's 'scanned ...' time");
  assert.ok(!/AX1/.test(p.list()),
    "nor ASX's rows — under the CRYPTO tab their chart links read m=crypto&s=AX1");
  p.net.status("data/momentum/crypto.json", 404);
  await flush();
  assert.equal(p.title(), "MOMENTUM · no data");
  assert.equal(p.stamp(), "", "a no-data page has no scan time to show");
  assert.equal(p.el("#mo-stamp").title, "");
});

(async () => {
  for (const i of Q) {
    if (i.s) { console.log(`\n── ${i.s} ──`); continue; }
    try { await i.f(); console.log(`  ✓  ${i.n}`); passed++; }
    catch (e) { console.error(`  ✗  ${i.n}\n     ${e.message}`); failed++; }
  }
  console.log(`\nlens_pages.test.js: ${passed}/${passed + failed} passed`);
  if (failed) process.exit(1);
})();
