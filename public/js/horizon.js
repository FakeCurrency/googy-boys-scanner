/* HORIZON — the rotation surface (2026-07-28).

   Renders public/data/sector_breadth.json in two places from one implementation:

     · #horizon-panel (sectors.html) — the full board: every sector ranked by
       participation rate, how many of them the book holds, the sector index on
       the day, the 5-day trend, and the book's remaining capacity.
     · #horizon-strip (index.html)   — a compact market-aware strip under the
       deck, so the answer is on the page that actually gets opened daily.

   WHY IT EXISTS. Between 30 June and 27 July 2026 ASX Consumer Discretionary
   ran for four weeks and the book held none of it. The scanner GRADED those
   names — the book was at its ceiling for ~20 straight sessions and declined
   every one of them `book_full` before a quality check ran. So this surface
   deliberately shows two things at once: what is running (by RATE, because raw
   setup counts just rank sectors by how many names they list) and whether there
   is room to act on it. Either number alone is what let the miss happen.

   Report-only, like the module behind it: it changes what is visible, never
   what gets taken. */
(() => {
  "use strict";

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const pct = (v) => v == null ? "—" : (100 * v).toFixed(1) + "%";
  const signed = (v) => v == null ? "" : (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
  const cls = (v) => v == null ? "" : (v >= 0 ? "hz-up" : "hz-down");

  // sector_breadth.json is keyed by SCAN market; index.html's switch uses the
  // same words except for crypto, which has no sectors and gets nothing.
  const MARKETS = { asx: "ASX", nasdaq: "NASDAQ" };

  function activeMarket() {
    try {
      const q = new URLSearchParams(location.search).get("m");
      if (q && MARKETS[q.toLowerCase()]) return q.toLowerCase();
    } catch (_) {}
    const btn = document.querySelector(".market-btn.is-active");
    const fromBtn = btn && String(btn.dataset.market || "").toLowerCase();
    if (fromBtn) return fromBtn;
    try {
      return String(JSON.parse(localStorage.getItem("gbs:prefs") || "{}").market || "asx").toLowerCase();
    } catch (_) { return "asx"; }
  }

  // ── capacity ───────────────────────────────────────────────────────────────
  // The July miss was a capacity failure, not a detection one, so the book bar
  // is never optional — it sits beside the leaderboard on both surfaces.
  function money(n) {
    if (!isFinite(n)) return "—";
    if (n >= 1000) return "$" + Math.round(n / 1000) + "k";
    return "$" + Math.round(n);
  }

  // Slots and dollars are two different capacity stories and right now they
  // point OPPOSITE ways: 24 of 30 slots used reads 80% full, while $6.1k of
  // $150k deployed reads 4% invested. Both are true — the 24 legacy holdings
  // average ~$250 each because they were sized off the old $10k equity. Showing
  // only slots understates the room; showing only dollars wildly overstates it.
  // What is actually deployable is free slots x the fixed position size, and
  // saying so is the whole point of a panel built after a capacity miss.
  function deployNote(book) {
    const free = book.free, per = book.position_notional || 0;
    if (!free || !per) return "";
    const room = free * per;
    const dollarFree = (book.max_notional || 0) - (book.notional || 0);
    if (dollarFree <= room * 1.25) return "";   // the two caps agree; nothing to reconcile
    return `<b>${money(room)}</b> is what those ${free} slots can actually take
      (${free} × ${money(per)}). The dollar ceiling has ${money(dollarFree)} unused,
      but slots are what bind — the ${book.open} you hold are mostly small
      pre-transition positions totalling just ${money(book.notional)}.`;
  }

  function bookHTML(book, compact) {
    if (!book) return "";
    const open = book.open || 0, max = book.max_open || 0;
    const w = max ? Math.min(100, 100 * open / max) : 0;
    const state = book.at_cap ? "full" : (book.free <= 3 ? "tight" : "ok");
    const label = book.at_cap ? "FULL" : `${book.free} free`;
    if (compact) {
      const per = book.position_notional || 0;
      const room = book.free && per ? ` · ${money(book.free * per)} to deploy` : "";
      return `<span class="hz-book-mini hz-${state}" title="Open positions across all markets — the cap is global. ${book.free || 0} free slots at ${money(per)} each.">
        <b>${open}/${max}</b> <span>${esc(label)}${room}</span></span>`;
    }
    const deploy = deployNote(book);
    return `<div class="hz-book hz-${state}">
      <div class="hz-book-top">
        <span class="hz-book-lbl">Book capacity</span>
        <span class="hz-book-num"><b>${open}</b> / ${max} open · ${esc(label)}</span>
      </div>
      <div class="hz-book-bar"><i style="width:${w.toFixed(1)}%"></i></div>
      ${book.max_notional ? `<div class="hz-book-sub">
        <b>${money(book.notional)}</b> of ${money(book.max_notional)} deployed</div>` : ""}
      <div class="hz-book-note">${deploy ? deploy + " " : ""}Positions are capped
        across ALL markets, so a full book declines every new setup — the best one
        included — before any quality check runs. That, not detection, is what cost
        the July rotation.</div>
    </div>`;
  }

  // ── the leaderboard ────────────────────────────────────────────────────────
  function trendArrow(t) {
    if (!t || t.chg == null) return `<span class="hz-tr flat" title="No prior session yet">·</span>`;
    const up = t.chg > 0.005, down = t.chg < -0.005;
    const arrow = up ? "▲" : down ? "▼" : "→";
    const k = up ? "hz-up" : down ? "hz-down" : "flat";
    return `<span class="hz-tr ${k}" title="${(100 * t.chg).toFixed(1)} pts vs the ${t.days}-session mean">${arrow}</span>`;
  }

  // Why a row carries no rank. A blank rank with a long bar beside it is the
  // single most misleading thing this panel could show — NASDAQ Real Estate is
  // 6 A+/A of the 7 names classified so far, which prints 85.7% and means
  // nothing. Each unranked row says which kind of nothing it is.
  function unrankedFlag(b, minNames) {
    if (b.rank) return "";
    if (b.real === false) {
      return `<em class="hz-flag" title="Not a sector — names the data carries no classification for. Shown because it is worth knowing how much of the tape is invisible to this panel, but never ranked.">unranked</em>`;
    }
    if (!b.names) {
      return `<em class="hz-flag warn" title="Held under a sector label this market's directory does not use, so it has no listing count to divide by — and the per-sector position cap counts it as its own bucket. Worth reconciling.">off-directory</em>`;
    }
    return `<em class="hz-flag" title="Only ${b.names} names carry this sector, under the ${minNames} needed to rank. A rate over a handful of names is noise, not breadth.">thin · ${b.names}</em>`;
  }

  function rowsHTML(blk) {
    const list = (blk.sectors || []).filter((b) => b.rank || b.ag > 0 || b.held > 0);
    if (!list.length) return `<p class="hz-empty">No sector data for this market yet.</p>`;
    const minNames = blk.min_names || 15;
    // Scale off RANKED rows only: a 7-name bucket at 85.7% would otherwise set
    // the axis and squash every sector that actually has breadth behind it.
    const top = Math.max(0.01, ...list.filter((b) => b.rank).map((b) => b.rate || 0));
    return `<div class="hz-rows">
      <div class="hz-row hz-head">
        <span>#</span><span>Sector</span><span>Participation</span>
        <span title="A+/A setups over names in the sector">A+/A</span>
        <span title="Positions the book holds in this sector">Held</span>
        <span>Index</span><span title="vs this sector's 5-session mean">5d</span>
      </div>
      ${list.map((b) => {
        const w = Math.min(100, 100 * (b.rate || 0) / top);
        const lead = b.rank && b.rank <= 3 && (b.rate || 0) > 0;
        const blind = lead && !b.held;
        const flag = unrankedFlag(b, minNames);
        return `<div class="hz-row${lead ? " is-lead" : ""}${blind ? " is-blind" : ""}${flag ? " is-unranked" : ""}">
          <span class="hz-rank">${b.rank || "·"}</span>
          <span class="hz-sec"><b>${esc(b.sector)}</b>${flag}</span>
          <span class="hz-bar"><i style="width:${w.toFixed(1)}%"></i><b>${pct(b.rate)}</b></span>
          <span class="hz-ag">${b.ag}<em>/${b.names}</em></span>
          <span class="hz-held${blind ? " zero" : ""}">${b.held}</span>
          <span class="hz-idx ${cls(b.index_chg)}">${b.index ? esc(b.index) + " " + signed(b.index_chg) : "—"}</span>
          ${trendArrow(b.trend)}
        </div>`;
      }).join("")}
    </div>`;
  }

  function notesHTML(hz, compact) {
    const notes = (hz && hz.notes) || [];
    if (!notes.length) {
      return compact ? "" : `<div class="hz-note hz-quiet">Nothing flagged: the leading
        sectors are ones the book is already in, and there is room to act.</div>`;
    }
    return notes.map((n) => `<div class="hz-note${hz.expand ? " hz-loud" : ""}">${esc(n)}</div>`).join("");
  }

  // How much of the day's A+/A the ranked sectors actually account for. Worth
  // saying out loud: on ASX today 91 of 216 setups sit in names carrying no
  // sector at all, so "leading sector" is a statement about 58% of the tape.
  function coverageNote(blk) {
    const total = blk.ag || 0;
    if (!total) return "";
    const off = (blk.sectors || []).filter((b) => !b.rank).reduce((n, b) => n + (b.ag || 0), 0);
    if (off / total < 0.1) return "";
    return ` <b>${Math.round(100 * (1 - off / total))}%</b> of today's ${total} A+/A
      sit in a ranked sector — the rest are unclassified or in buckets too thin to rank,
      and this board cannot see them.`;
  }

  function sourceNote(blk) {
    if (blk.names_source === "none") {
      return `<p class="hz-foot">No sector taxonomy available for this market yet.</p>`;
    }
    const body = blk.names_source === "classified"
      ? `US rates divide by the <b>${blk.universe_size}</b> NASDAQ names a scan has
         classified so far, not the full listing count — the symbol file ships no sector
         column. Ranking within this market is sound; the level is not comparable to ASX,
         and it drifts down as coverage fills in.`
      : `Participation = A+/A setups ÷ names <b>listed</b> in the sector. Raw setup counts
         rank sectors by how many names they list — Materials lists 766 of the ASX's 2,212
         and out-counts everything on every scan regardless of what it is doing.`;
    return `<p class="hz-foot">${body}${coverageNote(blk)}</p>`;
  }

  // ── full panel (sectors.html) ──────────────────────────────────────────────
  function renderPanel(host, data) {
    const blocks = data.markets || {};
    const keys = Object.keys(MARKETS).filter((k) => blocks[k]);
    if (!keys.length) { host.hidden = true; return; }
    const expand = keys.some((k) => (blocks[k].horizon || {}).expand);
    host.hidden = false;
    host.className = "hz-panel" + (expand ? " is-expand" : "");
    host.innerHTML = `
      <div class="hz-top">
        <div>
          <h3 class="hz-title">HORIZON <span>— where the market is actually running</span></h3>
          <p class="hz-sub">Sectors ranked by <b>participation rate</b>, against what the book
            holds and whether it has room. ${expand
              ? `<b class="hz-alarm">LOOK WIDER — something is running that the book is not in, and it can barely act.</b>`
              : ""}</p>
        </div>
        ${bookHTML(data.book, false)}
      </div>
      <div class="hz-cols">${keys.map((k) => {
        const blk = blocks[k];
        return `<section class="hz-col">
          <div class="hz-col-head"><span>${k === "asx" ? "🇦🇺" : "🇺🇸"}</span>
            <h4>${esc(MARKETS[k])}</h4>
            <span class="hz-col-meta">${blk.ag} A+/A · ${blk.held} held</span></div>
          ${notesHTML(blk.horizon, false)}
          ${rowsHTML(blk)}
          ${sourceNote(blk)}
        </section>`;
      }).join("")}</div>
      <p class="hz-disclaimer">Report-only — nothing here changes which trades the bot takes.
        History starts ${esc(data.day || "")}; the trend column fills in as sessions accumulate.</p>`;
  }

  // ── compact strip (index.html) ─────────────────────────────────────────────
  function renderStrip(host, data) {
    const market = activeMarket();
    const blk = (data.markets || {})[market];
    if (!blk) { host.hidden = true; host.innerHTML = ""; return; }
    const hz = blk.horizon || {};
    const leaders = (blk.sectors || []).filter((b) => b.rank && b.rank <= 3 && (b.rate || 0) > 0);
    host.hidden = false;
    host.className = "hz-strip" + (hz.expand ? " is-expand" : (hz.unheld_leaders || []).length ? " is-warn" : "");
    host.innerHTML = `
      <div class="hz-strip-line">
        <span class="hz-strip-tag">${hz.expand ? "LOOK WIDER" : "HORIZON"}</span>
        <span class="hz-strip-leads">${leaders.length
          ? leaders.map((b) => `<a class="hz-lead${b.held ? "" : " zero"}" href="sectors.html#horizon-panel"
              title="${esc(b.sector)} — ${b.ag} A+/A of ${b.names} names, ${b.held} held">
              ${esc(b.sector)} <b>${pct(b.rate)}</b>
              <em>${b.held ? b.held + " held" : "0 held"}</em></a>`).join("")
          : `<span class="hz-lead flat">No sector is leading on breadth today.</span>`}</span>
        ${bookHTML(data.book, true)}
        <a class="hz-strip-more" href="sectors.html#horizon-panel">Full board →</a>
      </div>
      ${(hz.notes || []).length
        ? `<div class="hz-strip-note">${esc(hz.notes[0])}</div>` : ""}`;
  }

  // ── mount ──────────────────────────────────────────────────────────────────
  function mount(data) {
    const panel = document.getElementById("horizon-panel");
    const strip = document.getElementById("horizon-strip");
    if (panel) renderPanel(panel, data);
    if (strip) {
      renderStrip(strip, data);
      // app.js owns the market switch and broadcasts nothing, so listen on the
      // buttons directly and re-render after it has flipped is-active.
      document.querySelectorAll(".market-btn").forEach((b) =>
        b.addEventListener("click", () => setTimeout(() => renderStrip(strip, data), 0)));
    }
  }

  fetch("data/sector_breadth.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(mount)
    .catch(() => {
      // Silent: this is a secondary surface and a missing file must never
      // disturb the page it sits on.
      ["horizon-panel", "horizon-strip"].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.hidden = true;
      });
    });
})();
