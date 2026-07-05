/* ★ MY NAMES — one page for every name the owner is tracking anywhere:
   stars from all three lenses (all markets) + open journal positions.
   Each row shows what every lens says about that name RIGHT NOW, pulled
   from the same scan files the lens pages read. */
(() => {
  "use strict";

  const MARKETS = ["asx", "nasdaq", "crypto"];
  const LENSES = ["vivek", "phasemap", "specs"];
  const esc = PM.esc;
  const $ = (sel) => document.querySelector(sel);

  const grab = (url) => fetch(url, { cache: "no-cache" })
    .then((r) => (r.ok ? r.json() : null)).catch(() => null);

  function collectNames() {
    // market -> ticker -> { stars:Set(lens), trade: t|null, starDates: {lens: date} }
    const names = {};
    const ent = (m, t) => {
      names[m] = names[m] || {};
      return (names[m][t] = names[m][t] ||
        { stars: new Set(), trade: null, starDates: {} });
    };
    for (const m of MARKETS) {
      for (const lens of LENSES) {
        const wl = PM.watch.map(lens, m);
        for (const [sym, e] of Object.entries(wl)) {
          const x = ent(m, sym);
          x.stars.add(lens);
          if (e.date) x.starDates[lens] = e.date;
        }
      }
    }
    if (window.GBSSync) {
      const mFor = (t) => t.asset_type === "crypto" ? "crypto"
        : t.asset_type === "asx" ? "asx" : "nasdaq";
      (GBSSync.load().trades || [])
        .filter((t) => t.status === "open" && t.symbol)
        .forEach((t) => { ent(mFor(t), String(t.symbol).toUpperCase()).trade = t; });
    }
    return names;
  }

  function lensChips(m, t, scans) {
    const chips = [];
    const v = scans[m].vivek && scans[m].vivek.find((r) => r.symbol === t);
    if (v) {
      const short = String(v.dir || "LONG").toUpperCase() === "SHORT";
      chips.push(`<span class="mn-lens mn-lens-on">VIVEK · ${esc(v.grade || "")} ` +
        `<b class="${short ? "pm-dir-short" : "pm-dir-long"}">${short ? "▼" : "▲"}</b></span>`);
    } else chips.push(`<span class="mn-lens">VIVEK · quiet</span>`);
    const p = scans[m].pm && scans[m].pm.find((r) => r.ticker === t);
    if (p) {
      const short = p.direction === "bearish";
      chips.push(`<span class="mn-lens mn-lens-on">PHASEMAP · ${esc(p.state)}` +
        `${p.tier ? " " + esc(p.tier) : ""} ` +
        `<b class="${short ? "pm-dir-short" : "pm-dir-long"}">${short ? "▼" : "▲"}</b></span>`);
    } else chips.push(`<span class="mn-lens">PHASEMAP · quiet</span>`);
    if (m !== "crypto") {
      const s = scans[m].spec && scans[m].spec.find((r) => r.symbol === t);
      if (s) chips.push(`<span class="mn-lens mn-lens-on">SPECS · ${esc(s.grade || "")} ⚡${s.spike_ratio != null ? s.spike_ratio + "×" : ""}</span>`);
      else chips.push(`<span class="mn-lens">SPECS · quiet</span>`);
    }
    return chips.join("");
  }

  function rowHTML(m, t, x, scans, ci) {
    const stars = [...x.stars].map((lens) =>
      `<span class="mn-star-chip" title="Starred on ${lens.toUpperCase()}${x.starDates[lens] ? " " + x.starDates[lens] : ""}">★ ${lens.toUpperCase()}` +
      `<button class="mn-unstar" data-lens="${lens}" data-market="${m}" data-ticker="${esc(t)}" title="Remove this star" aria-label="Unstar">✕</button></span>`).join("");
    const trade = x.trade
      ? `<span class="mn-star-chip mn-trade-chip" title="Open paper position">📓 OPEN ${esc(String(x.trade.direction || "").toUpperCase())} @ ${esc(String(x.trade.entry))}${x.trade.lens ? " · " + esc(String(x.trade.lens).toUpperCase()) : ""}</span>`
      : "";
    const conf = ci ? PM.confluenceChipHTML(ci, "") : "";
    return `<article class="mn-row">
      <div class="mn-row-top">
        <span class="pm-ticker">${esc(t)}</span>
        ${conf}
        ${stars}${trade}
        <a class="pm-chart-cue mn-chart-link" href="chart.html?m=${m}&s=${encodeURIComponent(t)}&pm=1">OPEN CHART →</a>
      </div>
      <div class="mn-row-lenses">${lensChips(m, t, scans)}</div>
    </article>`;
  }

  async function build() {
    // sync remote stars in first, so phone/desktop agree before we render
    if (window.GBSSync && GBSSync.enabled()) {
      try { await GBSSync.syncIn(); } catch (_) {}
    }
    const names = collectNames();
    const activeMarkets = MARKETS.filter((m) => Object.keys(names[m] || {}).length);
    const total = activeMarkets.reduce((n, m) => n + Object.keys(names[m]).length, 0);
    if (!total) {
      $("#mn-sub").textContent = "Nothing tracked yet.";
      $("#mn-list").innerHTML = `<div class="pm-empty">Star any name on VIVEK, PHASEMAP or SPECS (☆) — or open a journal trade — and it shows up here with live lens status.</div>`;
      return;
    }
    $("#mn-sub").textContent = `${total} name(s) tracked · lens status refreshes with every scan`;

    const scans = {};
    const confl = {};
    await Promise.all(activeMarkets.map(async (m) => {
      const [v, p, s, c] = await Promise.all([
        grab(`data/${m}_vivek.json`),
        grab(`data/phasemap/${m}/latest.json`),
        m !== "crypto" ? grab(`data/${m}_spec.json`) : null,
        PM.loadConfluence(m),
      ]);
      scans[m] = {
        vivek: (v && v.results) || [],
        pm: (p && p.results) || [],
        spec: (s && s.results) || [],
      };
      confl[m] = c;
    }));

    $("#mn-list").innerHTML = activeMarkets.map((m) => {
      const rows = Object.keys(names[m]).sort()
        .map((t) => rowHTML(m, t, names[m][t], scans, confl[m] ? confl[m].of(t) : null))
        .join("");
      return `<section class="pm-lg-section"><h3>${m.toUpperCase()}</h3>${rows}</section>`;
    }).join("");

    document.querySelectorAll(".mn-unstar").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        PM.watch.toggle(btn.dataset.lens, btn.dataset.market, btn.dataset.ticker, null);
        build();   // re-render from the updated store
      });
    });
  }

  build();
})();
