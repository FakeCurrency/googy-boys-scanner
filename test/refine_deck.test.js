/* REFINE200 WP7 — the deck, the shared PhaseMap helper, the service worker and
 * the smaller pages (ALERTS, NEWS), as the SHIPPED files run them.
 *
 *   #69  the entry-trigger tints come out of bot_rules.json, never a 1MB fetch
 *        stashed in sessionStorage
 *   #70  confluence prefers PhaseMap's slim confluence.json, latest.json is the
 *        fallback
 *   #41  the multi-lens chip / pill carry the "unproven" evidence note
 *   #51  sma_proxy rows wear an "SMA proxy · N bars" chip, warning tier
 *   #73  caps / sectors read off the row first; sidecars only for an
 *        unstamped payload  ·  #157 a cap older than 30 days says so
 *   #74  the service worker keys data by path, caps it, evicts old ?v= copies
 *   #94  no glued `}@media`, no focus rule that kills the keyboard ring
 *   #169 the SCAN poll waits ~25 min, not 5
 *   #192 the ALERTS sub-line states how far back the rolling log reaches
 *   #142 the NEWS box says "Today so far" for a mid-session stamp
 *
 * Every function is sliced out of the shipped file (the standing rule: a
 * re-typed copy drifts in step with the bug it should catch).
 */
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), "utf8");
const APP = read("public/js/app.js");
const PMS = read("public/js/phasemap-shared.js");
const SW = read("public/sw.js");
const ALERTS = read("public/js/alerts.js");
const SECTORS = read("public/js/sectors.js");

let passed = 0;
const Q = [];
const test = (n, f) => Q.push([n, f]);

// The parser decides where a declaration ends (a brace counter desyncs on the
// first regex literal). `async` is kept when the declaration carries it.
function fnSrc(src, name) {
  let at = src.search(new RegExp(`\\bfunction\\s+${name}\\s*\\(`));
  assert.ok(at >= 0, `no declaration of function ${name}()`);
  if (src.slice(Math.max(0, at - 6), at) === "async ") at -= 6;
  for (let i = src.indexOf("}", at); i > 0 && i - at < 20000; i = src.indexOf("}", i + 1)) {
    const cand = src.slice(at, i + 1);
    try { new Function(`return (${cand});`); return cand; } catch (_) { /* keep walking */ }
  }
  assert.fail(`could not slice ${name}()`);
}
function constSrc(src, name) {
  const at = src.search(new RegExp(`\\bconst\\s+${name}\\s*=`));
  assert.ok(at >= 0, `no const ${name}`);
  const start = src.indexOf("=", at) + 1;
  for (let i = src.indexOf(";", start); i > 0 && i - start < 6000; i = src.indexOf(";", i + 1)) {
    const cand = src.slice(start, i).trim();
    try { new Function(`return (${cand});`); return `const ${name} = ${cand};\n`; } catch (_) { /* keep walking */ }
  }
  assert.fail(`could not slice const ${name}`);
}

// ---------------------------------------------------------------------------
// #69 — entry quality from bot_rules.json
// ---------------------------------------------------------------------------
function entryQualityHarness(responses) {
  const asked = [];
  const sess = [];
  const body = constSrc(APP, "VK_ENTRY_Q") + fnSrc(APP, "applyEntryQuality") +
    constSrc(APP, "getJSON") + fnSrc(APP, "loadEntryQuality") +
    "return { load: loadEntryQuality, Q: VK_ENTRY_Q };";
  const fetchT = (url) => {
    asked.push(url);
    const v = responses[url];
    return Promise.resolve({ ok: v !== undefined, json: () => Promise.resolve(v) });
  };
  const sessionStorage = { setItem: (k) => sess.push(k), getItem: () => null };
  const state = { data: null };
  // UI100 #100: the rules come through the page's shared read (nav.js's
  // VivekBook via app.js's readShared), which rejects on a failed read —
  // stood in for here by the same fetchT, so `asked` still logs the file.
  const readShared = (kind) => fetchT(kind === "rules" ? "data/bot_rules.json" : "data/vivek_bot_book.json")
    .then((r) => { if (!r.ok) throw new Error("HTTP 404"); return r.json(); });
  const h = new Function("fetchT", "sessionStorage", "state", "renderEntryFilters", "readShared", body)(
    fetchT, sessionStorage, state, () => {}, readShared);
  return { ...h, asked, sess };
}
const RULES_EQ = { entry_quality: { by_entry_type: {
  reclaim: { n: 1031, expectancy_r: -0.027, win_rate: 47.5, profit_factor: 0.95 },
  retest: { n: 648, expectancy_r: -0.035, win_rate: 45.7, profit_factor: 0.93 },
  break: { n: 217, expectancy_r: 0.12, win_rate: 53.0, profit_factor: 1.16 },
} } };

test("#69 the chips are tinted from bot_rules.entry_quality and the 1MB file is never asked for", async () => {
  const h = entryQualityHarness({ "data/bot_rules.json": RULES_EQ });
  await h.load();
  assert.deepEqual(h.asked, ["data/bot_rules.json"]);
  assert.equal(h.Q.reclaim.tier, "red");
  assert.equal(h.Q.break.tier, "green");
  assert.ok(/-0\.03R avg over 1031 trades/.test(h.Q.reclaim.note), h.Q.reclaim.note);
  assert.deepEqual(h.sess, [], "nothing goes into sessionStorage");
});

test("#69 an old rules file falls back to the backtest, fetched plainly (no sessionStorage stash)", async () => {
  const h = entryQualityHarness({
    "data/bot_rules.json": { grades: ["A+"] },
    "data/vivek_backtest_longonly.json": { results: { by_entry_type: RULES_EQ.entry_quality.by_entry_type } },
  });
  await h.load();
  assert.deepEqual(h.asked, ["data/bot_rules.json", "data/vivek_backtest_longonly.json"]);
  assert.equal(h.Q.retest.tier, "red");
  assert.deepEqual(h.sess, []);
  assert.ok(!/sessFetch\(/.test(fnSrc(APP, "loadEntryQuality")), "loadEntryQuality must not use sessFetch");
});

test("#69 no file at all leaves the neutral wording", async () => {
  const h = entryQualityHarness({});
  await h.load();
  assert.equal(h.Q.reclaim.tier, null);
  assert.equal(h.Q.reclaim.note, "no backtest data");
});

// ---------------------------------------------------------------------------
// #73 / #157 — caps and sectors off the row
// ---------------------------------------------------------------------------
const capFns = (state) => new Function("state", constSrc(APP, "capKey") + constSrc(APP, "rowCap") +
  constSrc(APP, "mcapOf") + constSrc(APP, "capAsOf") + constSrc(APP, "CAP_STALE_DAYS") +
  fnSrc(APP, "capAge") + constSrc(APP, "rowsStamped") +
  "return { mcapOf, capAge, rowsStamped };")(state);
const DAY = 86400000;
const NOW = Date.parse("2026-10-14T00:00:00Z");

test("#73 the row's own cap wins over the sidecar; the sidecar fills an unstamped row", () => {
  const f = capFns({ market: "asx", caps: { "asx:BHP": 9e9, "asx:XYZ": 4e8 }, capTs: {} });
  assert.equal(f.mcapOf({ symbol: "BHP", mcap: 1.5e11 }), 1.5e11);
  assert.equal(f.mcapOf({ symbol: "XYZ" }), 4e8);
  assert.equal(f.mcapOf({ symbol: "NONE", mcap: null }), 0);
});

test("#73 a payload the scan stamped (even with null caps) skips the sidecars", () => {
  const f = capFns({ market: "asx", caps: {}, capTs: {} });
  assert.equal(f.rowsStamped({ results: [{ symbol: "A", mcap: null, mcap_asof: null }] }), true);
  assert.equal(f.rowsStamped({ results: [{ symbol: "A", sector: "Energy" }] }), false);
  assert.equal(f.rowsStamped(null), false);
  // and the boot path no longer fetches them unconditionally
  const boot = APP.slice(APP.indexOf("  initKeyboard();"), APP.indexOf("  initKeyboard();") + 400);
  assert.ok(!/loadCaps\(\)|loadSectors\(\)/.test(boot), "the sidecars are fetched at boot again");
  assert.ok(/ensureSidecars\(d\)/.test(fnSrc(APP, "applyPayload")), "applyPayload must route through ensureSidecars");
});

test("#157 a cap older than 30 days carries its date; a fresh one does not", () => {
  const f = capFns({ market: "nasdaq", caps: { "nasdaq:OLD": 2e9 }, capTs: { "nasdaq:OLD": "2026-06-24T00:00:00Z" } });
  const old = f.capAge({ symbol: "VRTX", mcap: 1e11, mcap_asof: "2026-06-24" }, NOW);
  assert.deepEqual(old, { days: 112, date: "2026-06-24" });
  assert.equal(f.capAge({ symbol: "X", mcap: 1e9, mcap_asof: new Date(NOW - 5 * DAY).toISOString() }, NOW), null);
  assert.equal(f.capAge({ symbol: "OLD" }, NOW).date, "2026-06-24", "the sidecar's ts ages a sidecar cap");
  assert.equal(f.capAge({ symbol: "X", mcap: 1e9 }, NOW), null, "no date: no claim");
  const row = fnSrc(APP, "rowHtml");
  assert.ok(/mcap-old/.test(row) && /cap as of/.test(row), "the row badge must surface the age");
});

// ---------------------------------------------------------------------------
// #51 — the SMA proxy chip
// ---------------------------------------------------------------------------
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const smaProxyChip = new Function("esc", fnSrc(APP, "smaProxyChip") + "return smaProxyChip;")(esc);

test("#51 sma_proxy rows wear the chip with their window; others do not", () => {
  const h = smaProxyChip({ symbol: "GGP", sma_proxy: true, sma_window: 69 });
  assert.ok(/SMA proxy · 69 bars/.test(h), h);
  assert.ok(/proxywarn/.test(h));
  assert.equal(smaProxyChip({ sma_proxy: false, sma_window: 200 }), "");
  assert.equal(smaProxyChip({ sma_window: 69 }), "", "absent flag = no chip");
  assert.ok(/SMA proxy</.test(smaProxyChip({ sma_proxy: true })), "no window: no number invented");
  assert.ok(/proxywarn/.test(fnSrc(APP, "rowChips")), "the chip must rank with the warnings so the cap cannot hide it");
});

// ---------------------------------------------------------------------------
// #169 — the SCAN poll window
// ---------------------------------------------------------------------------
test("#169 the poll waits 5 min, then probes every minute, out to ~25 min", () => {
  const body = constSrc(APP, "SCAN_POLL") + constSrc(APP, "scanPollDelays") + "return scanPollDelays();";
  const d = new Function(body)();
  const total = d.reduce((a, b) => a + b, 0);
  assert.equal(d[0], 5 * 60000);
  assert.ok(d.slice(1).every((x) => x === 60000));
  assert.ok(total >= 24 * 60000 && total <= 25 * 60000, `total ${total / 60000} min`);
  const poll = fnSrc(APP, "pollForFreshScan");
  assert.ok(/_prices\.json/.test(poll), "probes must read the slim prices file");
  assert.ok(/scanPollDelays\(\)/.test(poll));
  assert.ok(/No new scan after 25 min/.test(poll), "a give-up must say so");
  assert.ok(/10–20 min/.test(APP), "the fallback toast ETA");
  const scanJs = read("functions/api/scan.js");
  assert.ok(/~10–20 minutes/.test(scanJs) && !/~2–4 minutes/.test(scanJs), "the endpoint's ETA");
});

// ---------------------------------------------------------------------------
// #70 / #41 — PhaseMap rows for confluence, and the evidence note
// ---------------------------------------------------------------------------
const loadPhaseMapRows = new Function(fnSrc(PMS, "loadPhaseMapRows") + "return loadPhaseMapRows;")();
const grabber = (files) => {
  const asked = [];
  return { asked, grab: (u) => { asked.push(u); return Promise.resolve(files[u] === undefined ? null : files[u]); } };
};

test("#70 the slim confluence.json is preferred and latest.json is never fetched", async () => {
  const g = grabber({ "data/phasemap/asx/confluence.json": { schema_version: 1, rows: [{ ticker: "BHP", direction: "bullish", state: "SWEPT" }] } });
  const pm = await loadPhaseMapRows("asx", g.grab);
  assert.deepEqual(pm.results, [{ ticker: "BHP", direction: "bullish", state: "SWEPT" }]);
  assert.deepEqual(g.asked, ["data/phasemap/asx/confluence.json"]);
});

test("#70 a missing or malformed slim file falls back to latest.json", async () => {
  for (const slim of [undefined, { rows: "nope" }, { schema_version: 1 }]) {
    const g = grabber({ "data/phasemap/nasdaq/confluence.json": slim, "data/phasemap/nasdaq/latest.json": { results: [{ ticker: "X" }] } });
    const pm = await loadPhaseMapRows("nasdaq", g.grab);
    assert.deepEqual(pm, { results: [{ ticker: "X" }] });
    assert.deepEqual(g.asked, ["data/phasemap/nasdaq/confluence.json", "data/phasemap/nasdaq/latest.json"]);
  }
  assert.ok(/loadPhaseMapRows\(market, grab\)/.test(fnSrc(PMS, "loadConfluence")), "loadConfluence must use it");
});

test("#41 the chip and the deck pill carry the unproven note", () => {
  const note = new Function(constSrc(PMS, "CONFLUENCE_UNPROVEN") + "return CONFLUENCE_UNPROVEN;")();
  assert.ok(/^Unproven: multi-lens alignment has not beaten plain A\+/.test(note));
  const chip = new Function("esc", constSrc(PMS, "CONFLUENCE_UNPROVEN") + fnSrc(PMS, "confluenceChipHTML") +
    "return confluenceChipHTML;")(esc);
  assert.ok(chip({ lenses: ["VIVEK", "PHASEMAP"], side: "long", count: 2 }, "VIVEK").includes(note));
  assert.ok(/PM\.CONFLUENCE_UNPROVEN/.test(fnSrc(APP, "renderDeckPills")), "the deck pill must read the shared note");
  assert.ok(/CONFLUENCE_UNPROVEN,/.test(PMS.slice(PMS.lastIndexOf("return {"))), "PM must export the note");
});

// ---------------------------------------------------------------------------
// #74 — the service worker cache
// ---------------------------------------------------------------------------
function swHarness() {
  const store = new Map();     // url -> body, insertion-ordered like the Cache API
  const norm = (k) => (typeof k === "string" ? new URL(k, "https://x.test/").href : k.url);
  const cache = {
    put: async (k, res) => { const u = norm(k); store.delete(u); store.set(u, res.body); },
    keys: async () => [...store.keys()].map((url) => ({ url })),
    delete: async (k) => store.delete(norm(k)),
    match: async (k) => (store.has(norm(k)) ? { body: store.get(norm(k)) } : undefined),
  };
  const caches = { open: async () => cache, match: (k) => cache.match(k), keys: async () => [], delete: async () => true };
  let online = true;
  const fetch = async (req) => {
    if (!online) throw new Error("offline");
    return { ok: true, body: "body:" + req.url, clone() { return this; } };
  };
  const self = { location: { origin: "https://x.test" }, addEventListener() {}, skipWaiting() {}, clients: { claim() {} } };
  const api = new Function("self", "caches", "fetch", "URL",
    SW + "\nreturn { put, networkFirst, keyOf, DATA_MAX };")(self, caches, fetch, URL);
  return { ...api, store, setOnline: (v) => { online = v; } };
}
const req = (u) => ({ url: "https://x.test" + u, method: "GET" });

test("#74 cache-busted data reads share one entry, and the offline fallback finds it", async () => {
  const h = swHarness();
  await h.networkFirst(req("/data/asx_vivek.json?t=1"));
  await h.networkFirst(req("/data/asx_vivek.json?t=2"));
  assert.deepEqual([...h.store.keys()], ["https://x.test/data/asx_vivek.json"]);
  h.setOnline(false);
  const hit = await h.networkFirst(req("/data/asx_vivek.json?t=99"));
  assert.equal(hit.body, "body:https://x.test/data/asx_vivek.json?t=2");
});

test("#74 /data/ is capped at DATA_MAX, oldest write first out", async () => {
  const h = swHarness();
  for (let i = 0; i < h.DATA_MAX + 5; i++) await h.networkFirst(req(`/data/f${i}.json`));
  const keys = [...h.store.keys()];
  assert.equal(keys.length, h.DATA_MAX);
  assert.ok(!keys.includes("https://x.test/data/f0.json") && keys.includes(`https://x.test/data/f${h.DATA_MAX + 4}.json`));
});

test("#74 a new ?v= copy evicts the old one; other assets are untouched", async () => {
  const h = swHarness();
  await h.put(req("/js/app.js?v=144"), { body: "a", clone() { return this; } });
  await h.put(req("/js/nav.js?v=28"), { body: "n", clone() { return this; } });
  await h.put(req("/js/app.js?v=145"), { body: "b", clone() { return this; } });
  assert.deepEqual([...h.store.keys()].sort(), ["https://x.test/js/app.js?v=145", "https://x.test/js/nav.js?v=28"]);
  assert.ok(/const CACHE = "vivek5-v9"/.test(SW), "the CACHE name must move with the change");
});

// ---------------------------------------------------------------------------
// #192 — ALERTS window note
// ---------------------------------------------------------------------------
test("#192 the sub-line says how far back the rolling log reaches", () => {
  const windowNote = new Function(constSrc(ALERTS, "melbShort") + fnSrc(ALERTS, "windowNote") + "return windowNote;")();
  // oldest in the MIDDLE: the window is the minimum, not whichever comes last
  const entries = [{ date: "2026-10-14T05:47:18+00:00" }, { date: "2026-09-25T20:05:20+00:00" },
                   { date: "junk" }, { date: "2026-10-01T00:00:00+00:00" }];
  // UI100 #95 (2026-10-20): shorter words, same window ("newest N kept").
  assert.ok(/^ · newest 4 kept, back to 26 Sep/.test(windowNote(entries)), windowNote(entries));
  assert.equal(windowNote([]), "");
  const html = read("public/alerts.html");
  assert.ok(!/durable record|being rebuilt|queued for it|every multi-lens alignment/.test(html), "the old claims are back");
});

// ---------------------------------------------------------------------------
// UI100 review (2026-10-20) — ALERTS day groups, sub-line, prior-use marker
// ---------------------------------------------------------------------------
/* The shipped render() + onDayToggle() against a list stub that parses the
 * <details> tags render() writes and, like Chrome, fires `toggle` for every
 * group inserted already open. `reader(day)` is a tap on that day's summary. */
function alertsHarness(entries) {
  let groups = [];
  const dataset = (attrs) => {
    const ds = {};
    for (const m of attrs.matchAll(/data-([\w-]+)="([^"]*)"/g))
      ds[m[1].replace(/-(\w)/g, (_, c) => c.toUpperCase())] = m[2];
    return ds;
  };
  const list = {
    set innerHTML(v) {
      groups = [...v.matchAll(/<details\b([^>]*)>[\s\S]*?<div class="al-day">([\s\S]*?)<\/div>\s*<\/details>/g)]
        .map(([, attrs, rows]) => {
          const g = { open: /\sopen(\s|$)/.test(attrs), dataset: dataset(attrs), drawn: rows.trim() !== "",
                      classList: { contains: (c) => c === "al-day-group" } };
          g.querySelector = () => ({ get firstElementChild() { return g.drawn ? {} : null; },
                                     set innerHTML(h) { g.drawn = h.trim() !== ""; } });
          return g;
        });
      // Chrome: a <details open> inserted by the parser fires `toggle` too
      for (const g of groups) if (g.open) h.onDayToggle({ target: g });
    },
    get innerHTML() { return ""; },
  };
  const sub = { textContent: "", title: "" };
  const document = { getElementById: (id) => (id === "al-list" ? list : id === "al-sub" ? sub : null) };
  const h = new Function("document", "location",
    constSrc(ALERTS, "esc") + constSrc(ALERTS, "state") +
    "const rowHTML = (e) => `<a class=\"al-row\">${e.ticker}</a>`;\n" +
    constSrc(ALERTS, "melbFmtD") + constSrc(ALERTS, "melbDay") + constSrc(ALERTS, "melbShort") +
    fnSrc(ALERTS, "windowNote") + constSrc(ALERTS, "OPEN_ALL_MAX") +
    fnSrc(ALERTS, "dayGroupHTML") + fnSrc(ALERTS, "onDayToggle") + fnSrc(ALERTS, "render") +
    "return { state, render, onDayToggle };")(document, {});
  h.state.entries = entries;
  h.render();
  h.group = (day) => groups.find((g) => g.dataset.day === day);
  h.reader = (day) => { const g = h.group(day); g.open = !g.open; h.onDayToggle({ target: g }); };
  h.search = (q) => { h.state.q = q; h.render(); };
  h.sub = sub;
  return h;
}
// five Melbourne days, newest first, one distinct ticker each
const ALERT_DAYS = ["2026-10-20", "2026-10-19", "2026-10-16", "2026-10-15", "2026-10-14"];
const alertEntries = () => ALERT_DAYS.map((d, i) => ({ date: `${d}T03:00:00+00:00`, ticker: `TK${i}`,
  market: i % 2 ? "nasdaq" : "asx", side: "long", count: 2, lenses: ["PHASEMAP", "VIVEK"] }));

test("ALERTS: Chrome's own toggle for a rendered-open day is not mistaken for the reader's choice", () => {
  const a = alertsHarness(alertEntries());
  assert.deepEqual(a.state.toggled, {}, "the newest day's parser-fired toggle was recorded as a choice");
  assert.ok(a.group(ALERT_DAYS[0]).open && !a.group(ALERT_DAYS[3]).open, "only the newest day starts open");
  // the repro: open the 4th day, search a ticker in it, clear the search
  a.reader(ALERT_DAYS[3]);
  assert.ok(a.group(ALERT_DAYS[3]).drawn, "an opened day draws its rows");
  assert.equal(a.state.toggled[ALERT_DAYS[3]], true);
  a.search("TK3");
  assert.ok(a.group(ALERT_DAYS[3]).open, "a narrow search opens the day it matches");
  a.search("");
  assert.ok(a.group(ALERT_DAYS[3]).open, "the day the reader opened closed itself after a search");
  assert.ok(a.group(ALERT_DAYS[0]).open && !a.group(ALERT_DAYS[1]).open, "the other days keep their defaults");
});

test("ALERTS: a choice that matches the default is kept, and a narrow search opens every matching day", () => {
  const a = alertsHarness(alertEntries());
  // close the newest, open it again: the reader's explicit "open" is stored
  a.reader(ALERT_DAYS[0]);
  assert.equal(a.state.toggled[ALERT_DAYS[0]], false);
  a.reader(ALERT_DAYS[0]);
  assert.equal(a.state.toggled[ALERT_DAYS[0]], true, "a choice equal to the default must be stored, not deleted");
  // a remembered close never hides a search match
  a.reader(ALERT_DAYS[0]);
  a.search("TK");
  for (const d of ALERT_DAYS) assert.ok(a.group(d).open, `${d}: a narrow search must open every matching day`);
  a.search("");
  assert.ok(!a.group(ALERT_DAYS[0]).open, "the reader's close comes back once the search is cleared");
});

test("ALERTS: the sub-line keeps the window date in reach on a phone, whatever the filter", () => {
  const a = alertsHarness(alertEntries());
  a.state.market = "nasdaq";
  a.render();
  assert.ok(/^2 alignments · newest 5 kept, back to 14 Oct$/.test(a.sub.textContent), a.sub.textContent);
  a.search("NOPE");
  assert.ok(/match[\s\S]* · newest 5 kept, back to 14 Oct$/.test(a.sub.textContent),
    "a search that finds nothing still says how far back the log reaches: " + a.sub.textContent);
  const css = read("public/css/phasemap.css").replace(/\/\*[\s\S]*?\*\//g, "");
  for (const m of css.matchAll(/([^{}]*\.al-sub[^{}]*)\{([^}]*)\}/g))
    assert.ok(!/ellipsis|nowrap/.test(m[2]), `${m[1].trim()} clips the sub-line again: ${m[2].trim()}`);
});

test("ALERTS: the page still writes gbs:alerts-seen, the tour's prior-use marker", () => {
  const keys = constSrc(APP, "PRIOR_USE_KEYS");
  assert.ok(/"gbs:alerts-seen"/.test(keys), "app.js no longer reads it: drop this pin with the write");
  assert.ok(/localStorage\.setItem\("gbs:alerts-seen"/.test(ALERTS),
    "the alerts page must write the key app.js counts as prior use (the first-visit tour gate)");
});

// ---------------------------------------------------------------------------
// #142 — NEWS session title
// ---------------------------------------------------------------------------
test("#142 a stamp inside the session reads 'Today so far'; after the close it does not", () => {
  const SYD = "Australia/Sydney";
  const f = new Function("SYD", constSrc(SECTORS, "SESSION") + fnSrc(SECTORS, "sessionLive") +
    "return sessionLive;")(SYD);
  assert.equal(f("2026-10-14T01:26:00Z", "asx"), true, "12:26 AEDT Wed");
  assert.equal(f("2026-10-14T07:26:00Z", "asx"), false, "18:26 AEDT");
  assert.equal(f("2026-10-14T05:35:00Z", "asx"), true, "16:35 AEDT: the delayed feed is not final yet");
  assert.equal(f("2026-10-17T01:26:00Z", "asx"), false, "Saturday");
  assert.equal(f("2026-10-14T15:00:00Z", "us"), true, "11:00 New York");
  assert.equal(f("2026-10-14T21:00:00Z", "us"), false, "17:00 New York");
  assert.equal(f("not a date", "asx"), false);
  assert.ok(/Today so far/.test(fnSrc(SECTORS, "columnHTML")));
});

// ---------------------------------------------------------------------------
// #94 — CSS hygiene in the files this package owns
// ---------------------------------------------------------------------------
test("#94 no rule is glued onto an @media, and no :focus rule drops the outline", () => {
  for (const f of ["styles.css", "about.css", "sectors.css"]) {
    const css = read(`public/css/${f}`).replace(/\/\*[\s\S]*?\*\//g, "");
    assert.ok(!/\}[ \t]*@media/.test(css), `${f}: a rule is glued onto an @media`);
    assert.ok(!/:focus\s*\{[^}]*outline:\s*(none|0)/.test(css), `${f}: a :focus rule kills the keyboard ring`);
  }
  assert.ok(!/doc-disclaimer/.test(read("public/css/about.css")), ".doc-disclaimer had no producer");
  assert.ok(!/app-build|>V1</.test(read("public/index.html")), "the never-bumping V1 badge is back");
});

(async () => {
  for (const [n, f] of Q) {
    try { await f(); passed++; console.log("PASS  " + n); }
    catch (e) { console.error("FAIL  " + n + "\n      " + e.message); process.exitCode = 1; }
  }
  console.log(process.exitCode ? "\nSOME refine_deck TESTS FAILED" : `\nALL ${passed} refine_deck tests passed`);
})();
