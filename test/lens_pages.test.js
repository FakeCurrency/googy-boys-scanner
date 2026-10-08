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

(async () => {
  for (const i of Q) {
    if (i.s) { console.log(`\n── ${i.s} ──`); continue; }
    try { await i.f(); console.log(`  ✓  ${i.n}`); passed++; }
    catch (e) { console.error(`  ✗  ${i.n}\n     ${e.message}`); failed++; }
  }
  console.log(`\nlens_pages.test.js: ${passed}/${passed + failed} passed`);
  if (failed) process.exit(1);
})();
