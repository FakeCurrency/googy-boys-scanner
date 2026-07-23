/* =========================================================================
   Vivek 5.0 — RECOMMENDATIONS page (owner request 2026-07-22)
   Daily market consensus in two layers, kept deliberately OUTSIDE the
   signal path:
     1. CONSENSUS — computed client-side, deterministically, from the same
        published artifacts the rest of the site reads (slim per-market
        price/dir files + the paper bot book). No LLM, no new data source;
        as fresh as the latest scan every time the page opens.
     2. CLAUDE'S NOTE — a dated, hand-written read (data/reco_note.json)
        refreshed by the daily Claude session. Commentary only.
   Nothing here feeds the bot or the scanners — CLAUDE.md rules apply.
   ========================================================================= */
(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const MARKETS = [
    { key: "asx", label: "ASX" },
    { key: "nasdaq", label: "NASDAQ" },
    { key: "crypto", label: "CRYPTO" },
  ];

  const grab = (url) => fetch(url, { cache: "no-cache" })
    .then((r) => (r.ok ? r.json() : null)).catch(() => null);

  const rfmt = (v) => (v == null || isNaN(v) ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}R`);
  const rcls = (v) => (v >= 0 ? "pos" : "neg");

  // ── Consensus history (backlog #10+#11) ──────────────────────────────────
  // Client-side ONLY (by design): each visit records today's per-market long
  // breadth to localStorage, building a day-over-day trend the page can show
  // as delta arrows and a mini history strip. No server round-trip, no new
  // data file — it fills in as the owner opens the page across days. Starts
  // sparse and honest (one bar day one), never invents prior days.
  const HIST_KEY = "gbs:reco:hist";
  const HIST_CAP = 30;
  // Today's date in MELBOURNE (the site's one on-screen timezone) as YYYY-MM-DD.
  function melbDay() {
    try { return new Date().toLocaleDateString("en-CA", { timeZone: "Australia/Melbourne" }); }
    catch (_) { return new Date().toISOString().slice(0, 10); }
  }
  function readHist() {
    try {
      const h = JSON.parse(localStorage.getItem(HIST_KEY) || "{}");
      return (h && typeof h === "object" && !Array.isArray(h)) ? h : {};
    } catch (_) { return {}; }
  }
  // Record today's breadth for a market. Same-day repeat visits UPDATE today's
  // bar (breadth shifts as fresh scans land) rather than appending duplicates.
  function recordSnapshot(hist, marketKey, pl, n) {
    if (n <= 0) return hist;                     // don't log an empty/no-scan day
    const day = melbDay();
    const arr = Array.isArray(hist[marketKey]) ? hist[marketKey] : [];
    const last = arr[arr.length - 1];
    if (last && last.d === day) { last.pl = pl; last.n = n; }
    else arr.push({ d: day, pl, n });
    hist[marketKey] = arr.slice(-HIST_CAP);
    return hist;
  }
  function saveHist(hist) {
    try { localStorage.setItem(HIST_KEY, JSON.stringify(hist)); } catch (_) {}
  }
  // Delta vs the most recent PRIOR day (never today's own bar).
  function priorDelta(arr, todayPl) {
    if (!Array.isArray(arr)) return null;
    const day = melbDay();
    for (let i = arr.length - 1; i >= 0; i--) {
      if (arr[i].d !== day) return { pp: Math.round(todayPl - arr[i].pl), from: arr[i].d };
    }
    return null;   // no prior day yet
  }
  // "Breadth shifting" chip. >3pp move = a real shift; else steady.
  function deltaChip(delta) {
    if (!delta) return `<span class="rec-delta flat" title="No prior day recorded yet — the trend fills in as you check back">first read</span>`;
    const { pp } = delta;
    if (pp >= 3) return `<span class="rec-delta up" title="Long breadth up ${pp}pp vs ${esc(delta.from)}">▲ shifting long +${pp}pp</span>`;
    if (pp <= -3) return `<span class="rec-delta down" title="Long breadth down ${Math.abs(pp)}pp vs ${esc(delta.from)}">▼ shifting short ${pp}pp</span>`;
    return `<span class="rec-delta flat" title="Breadth roughly steady vs ${esc(delta.from)} (${pp >= 0 ? "+" : ""}${pp}pp)">◆ steady ${pp >= 0 ? "+" : ""}${pp}pp</span>`;
  }
  // 14-day mini bar strip: bar height = long %, colour = lean.
  function historyStrip(arr) {
    const recent = (Array.isArray(arr) ? arr : []).slice(-14);
    if (recent.length < 2) return "";   // one bar reads as noise — wait for a trend
    const bars = recent.map((s) => {
      const cls = s.pl >= 62 ? "up" : s.pl <= 38 ? "down" : "flat";
      const h = Math.max(8, Math.min(100, s.pl));
      return `<i class="rec-hbar ${cls}" style="height:${h}%" title="${esc(s.d)}: ${s.pl}% long (${s.n} setups)"></i>`;
    }).join("");
    return `<div class="rec-hist" title="Long-breadth over the last ${recent.length} days you've checked">
      <div class="rec-hist-bars">${bars}</div>
      <span class="rec-hist-lbl">${recent.length}-day breadth</span>
    </div>`;
  }

  function agoText(iso) {
    const t = Date.parse(iso);
    if (!isFinite(t)) return "";
    const m = Math.max(0, Math.round((Date.now() - t) / 60000));
    if (m < 60) return `${m}m ago`;
    if (m < 48 * 60) return `${Math.round(m / 60)}h ago`;
    return `${Math.round(m / 1440)}d ago`;
  }
  function fmtMelb(iso) {
    return window.PM && PM.fmtMelb ? PM.fmtMelb(iso) : String(iso || "");
  }

  // Verdict from setup breadth + bot positioning. Thresholds are DISPLAY
  // heuristics only (commentary, not signals): >=62% one-sided = bias.
  function verdict(longs, shorts, botR) {
    const n = longs + shorts;
    if (!n) return { cls: "mixed", label: "◆ No read", line: "No qualifying setups in the latest scan." };
    const pl = longs / n;
    if (n < 8) return { cls: "mixed", label: "◆ Thin", line: `Only ${n} qualifying setups — too thin to call a trend.` };
    if (pl >= 0.62) return {
      cls: "up", label: "▲ Uptrend bias",
      line: `${Math.round(pl * 100)}% of qualifying setups lean long` +
        (botR > 0.15 ? " and the bot's book here is green — bias confirmed." :
         botR < -0.15 ? ", but the bot's open book here is red — respect the divergence." : "."),
    };
    if (pl <= 0.38) return {
      cls: "down", label: "▼ Downtrend bias",
      line: `${Math.round((1 - pl) * 100)}% of qualifying setups lean short` +
        (botR < -0.15 ? " — and open longs are paying for it." :
         botR > 0.15 ? ", though the bot's book here is still green — mixed tape." : "."),
    };
    return {
      cls: "mixed", label: "◆ Two-sided",
      line: `Setups split ${longs} long / ${shorts} short — pick names, not direction.`,
    };
  }

  function marketCard(m, prices, botPos, histArr) {
    const rows = (prices && prices.rows) || {};
    const list = Object.values(rows);
    const longs = list.filter((r) => r.dir === "LONG").length;
    const shorts = list.filter((r) => r.dir === "SHORT").length;
    const aplus = list.filter((r) => r.grade === "A+").length;
    const botR = botPos.reduce((s, p) => s + (p.unreal_r || 0), 0);
    const v = verdict(longs, shorts, botR);
    const n = longs + shorts;
    const pl = n ? Math.round((longs / n) * 100) : 50;
    const gen = prices && prices.generated_at;
    const delta = n ? priorDelta(histArr, pl) : null;   // #10
    return `<article class="rec-card" data-market="${esc(m.key)}">
      <div class="rec-card-hd">
        <h3>${m.label}</h3>
        <span class="rec-verdict ${v.cls}">${v.label}</span>
      </div>
      <div class="rec-breadth" title="Direction of qualifying setups in the latest scan">
        <i style="width:${pl}%"></i>
        <span class="rec-breadth-lbl">▲ ${longs} long · ${shorts} short ▼</span>
      </div>
      ${n ? `<div class="rec-delta-row">${deltaChip(delta)}</div>` : ""}
      <p class="rec-line">${esc(v.line)}</p>
      ${historyStrip(histArr)}
      <div class="rec-nums" data-nums="${esc(m.key)}">
        <span title="A+ setups in the latest scan">A+ <b>${aplus}</b></span>
        <span title="Bot's open positions in this market">Bot open <b>${botPos.length}</b></span>
        <span title="Sum of unrealised R on the bot's open positions here">Book <b class="${rcls(botR)}">${rfmt(botR)}</b></span>
      </div>
      <div class="rec-enrich" data-enrich="${esc(m.key)}"></div>
      <div class="rec-age">${gen ? `scan ${agoText(gen)}` : "no scan data"}</div>
    </article>`;
  }

  // ── Lazy card enrichment (backlog #13+#14) ───────────────────────────────
  // The slim price files carry only grade+dir. At-level, multi-lens and sector
  // live in the FULL scan JSON (1-2MB each), so we fetch those AFTER the base
  // cards paint — the page is useful instantly and deepens a beat later.
  // Cached per market by the scan's generated_at so the 5-min re-render and
  // repeated loads don't refetch the same megabytes.
  const vkCache = {};   // key -> { gen, results }
  async function fetchVivek(key, gen) {
    if (vkCache[key] && vkCache[key].gen === gen) return vkCache[key].results;
    const d = await grab(`data/${key}_vivek.json`);
    const results = (d && d.results) || null;
    if (results) vkCache[key] = { gen, results };
    return results;
  }
  // Sectors worth naming: drop the non-informative buckets the scanner emits
  // for names without a clean GICS sector.
  const SKIP_SECTOR = /^(not applic|not applicable|n\/?a|\?|)$/i;
  const SECTOR_SHORT = (s) => String(s || "")
    .replace(/Equity Real Estate Investment Trusts \(REITs\)/i, "REITs")
    .replace(/Information Technology/i, "InfoTech")
    .replace(/Consumer Discretionary/i, "Consumer Disc.")
    .replace(/Communication Services/i, "Comms")
    .replace(/Financial Services/i, "Financials")
    .slice(0, 22);
  function sectorBreadth(results) {
    const byS = {};
    for (const r of results) {
      const s = String(r.sector || "").trim();
      if (SKIP_SECTOR.test(s)) continue;
      const e = byS[s] || (byS[s] = { n: 0, longs: 0, shorts: 0 });
      e.n++;
      if (r.dir === "LONG") e.longs++; else if (r.dir === "SHORT") e.shorts++;
    }
    return Object.entries(byS)
      .map(([name, v]) => ({ name, ...v }))
      .sort((a, b) => b.n - a.n)
      .slice(0, 3);
  }
  function enrichBlock(results, multi) {
    const atLevel = results.filter((r) => r.at_level).length;
    const secs = sectorBreadth(results);
    const secRows = secs.map((s) => {
      const lean = s.longs > s.shorts ? "up" : s.shorts > s.longs ? "down" : "flat";
      const arrow = lean === "up" ? "▲" : lean === "down" ? "▼" : "◆";
      return `<div class="rec-sec" title="${esc(s.name)}: ${s.longs} long / ${s.shorts} short">
        <span class="rec-sec-nm">${esc(SECTOR_SHORT(s.name))}</span>
        <span class="rec-sec-lean ${lean}">${arrow} ${s.longs}L·${s.shorts}S</span>
      </div>`;
    }).join("");
    return `<div class="rec-enrich-nums">
        <span title="Setups sitting ON a 200-SMA right now — the moment before the reaction">◎ At level <b>${atLevel}</b></span>
        <span title="Names with 2+ lenses aligned right now">⨂ Multi-lens <b>${multi}</b></span>
      </div>
      ${secs.length ? `<div class="rec-sec-list"><div class="rec-sec-hd">Sectors in play</div>${secRows}</div>` : ""}`;
  }
  // Same confluence engine the dashboard's ⨂ pill uses (PM.loadConfluence),
  // so "Multi-lens" is ONE number across the site. Falls back to the vivek
  // row's own confluence flag if the shared helper isn't present.
  async function multiLensCount(market, results) {
    try {
      if (window.PM && PM.loadConfluence) {
        const c = await PM.loadConfluence(market, { results });
        return c.all().length;
      }
    } catch (_) {}
    return results.filter((r) => r.confluence).length;
  }
  async function enrichCards(prices) {
    await Promise.all(MARKETS.map(async (m) => {
      const p = prices[m.key];
      if (!p || !p.generated_at) return;
      const results = await fetchVivek(m.key, p.generated_at);
      if (!results) return;
      const multi = await multiLensCount(m.key, results);
      const slot = document.querySelector(`.rec-enrich[data-enrich="${m.key}"]`);
      if (!slot) return;                       // card re-rendered underneath us
      slot.innerHTML = enrichBlock(results, multi);
    }));
  }

  function moversCard(open) {
    const movers = open.filter((p) => p.unreal_r != null)
      .sort((a, b) => Math.abs(b.unreal_r) - Math.abs(a.unreal_r)).slice(0, 6);
    if (!movers.length) return "";
    return `<article class="rec-card rec-movers">
      <div class="rec-card-hd"><h3>What moved — bot book</h3>
        <a class="rec-link" href="journal.html">Journal →</a></div>
      <div class="rec-mv-list">
        ${movers.map((p) => `
          <a class="rec-mv" href="chart.html?m=${esc(p.market)}&s=${encodeURIComponent(p.symbol)}&mode=vivek"
             title="${esc(p.timeframe || "")} ${esc(p.entry_type || "")} — open the chart">
            <b>${esc(p.symbol)}</b>
            <span class="rec-mv-mkt">${esc(String(p.market || "").toUpperCase())}</span>
            <span class="rec-mv-r ${rcls(p.unreal_r)}">${rfmt(p.unreal_r)}</span>
          </a>`).join("")}
      </div>
      <div class="rec-age">unrealised R since entry, marked at the last book update</div>
    </article>`;
  }

  function noteCard(note) {
    if (!note || !note.note) return "";
    return `<article class="rec-card rec-note">
      <div class="rec-card-hd">
        <h3>${note.author === "Claude" ? "🤖 Claude's note" : "🤖 Daily note · auto"}</h3>
        <span class="rec-age">${esc(note.date || "")}${note.updated_at ? ` · ${agoText(note.updated_at)}` : ""}</span>
      </div>
      <p class="rec-note-body">${esc(note.note)}</p>
      <div class="rec-age">${esc(note.basis || "")}</div>
    </article>`;
  }

  async function load() {
    const [pa, pn, pc, book, note] = await Promise.all([
      grab("data/asx_prices.json"), grab("data/nasdaq_prices.json"), grab("data/crypto_prices.json"),
      grab("data/vivek_bot_book.json"), grab("data/reco_note.json"),
    ]);
    const prices = { asx: pa, nasdaq: pn, crypto: pc };
    const open = (book && book.open) || [];
    const perMkt = (k) => open.filter((p) => p.market === k);
    const stamps = MARKETS.map((m) => prices[m.key] && prices[m.key].generated_at).filter(Boolean)
      .sort((a, b) => Date.parse(b) - Date.parse(a));
    const sub = $("#rec-sub");
    if (sub && stamps[0]) {
      sub.textContent = `Consensus recomputed from the latest published scans · freshest ${agoText(stamps[0])}`;
      sub.title = `Freshest scan: ${fmtMelb(stamps[0])}`;
    }
    // Record today's breadth per market, THEN render (so today's bar shows in
    // the strip and the delta compares against a genuine prior day).
    const hist = readHist();
    MARKETS.forEach((m) => {
      const rows = (prices[m.key] && prices[m.key].rows) || {};
      const list = Object.values(rows);
      const longs = list.filter((r) => r.dir === "LONG").length;
      const shorts = list.filter((r) => r.dir === "SHORT").length;
      const n = longs + shorts;
      if (n) recordSnapshot(hist, m.key, Math.round((longs / n) * 100), n);
    });
    saveHist(hist);

    $("#rec-note-slot").innerHTML = noteCard(note);
    $("#rec-markets").innerHTML = MARKETS.map((m) => marketCard(m, prices[m.key], perMkt(m.key), hist[m.key])).join("");
    $("#rec-movers-slot").innerHTML = moversCard(open);

    // #13+#14: deepen the cards once the base view is on screen (non-blocking).
    enrichCards(prices).catch(() => {});
  }

  load();
  // Re-derive on the site's usual cadence while the tab stays open.
  setInterval(() => { if (!document.hidden) load(); }, 5 * 60 * 1000);
})();
