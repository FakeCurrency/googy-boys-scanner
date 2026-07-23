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

  function marketCard(m, prices, botPos) {
    const rows = (prices && prices.rows) || {};
    const list = Object.values(rows);
    const longs = list.filter((r) => r.dir === "LONG").length;
    const shorts = list.filter((r) => r.dir === "SHORT").length;
    const aplus = list.filter((r) => r.grade === "A+").length;
    const botR = botPos.reduce((s, p) => s + (p.unreal_r || 0), 0);
    const v = verdict(longs, shorts, botR);
    const pl = longs + shorts ? Math.round((longs / (longs + shorts)) * 100) : 50;
    const gen = prices && prices.generated_at;
    return `<article class="rec-card">
      <div class="rec-card-hd">
        <h3>${m.label}</h3>
        <span class="rec-verdict ${v.cls}">${v.label}</span>
      </div>
      <div class="rec-breadth" title="Direction of qualifying setups in the latest scan">
        <i style="width:${pl}%"></i>
        <span class="rec-breadth-lbl">▲ ${longs} long · ${shorts} short ▼</span>
      </div>
      <p class="rec-line">${esc(v.line)}</p>
      <div class="rec-nums">
        <span title="A+ setups in the latest scan">A+ <b>${aplus}</b></span>
        <span title="Bot's open positions in this market">Bot open <b>${botPos.length}</b></span>
        <span title="Sum of unrealised R on the bot's open positions here">Book <b class="${rcls(botR)}">${rfmt(botR)}</b></span>
      </div>
      <div class="rec-age">${gen ? `scan ${agoText(gen)}` : "no scan data"}</div>
    </article>`;
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
    $("#rec-note-slot").innerHTML = noteCard(note);
    $("#rec-markets").innerHTML = MARKETS.map((m) => marketCard(m, prices[m.key], perMkt(m.key))).join("");
    $("#rec-movers-slot").innerHTML = moversCard(open);
  }

  load();
  // Re-derive on the site's usual cadence while the tab stays open.
  setInterval(() => { if (!document.hidden) load(); }, 5 * 60 * 1000);
})();
