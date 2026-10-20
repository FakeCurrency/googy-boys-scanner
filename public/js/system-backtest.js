/* Live backtest evidence on the SYSTEM page (owner, 2026-09-20).
 *
 * "Every time we run a back test I want the results to be seen on the HOW THE
 * SYSTEM works page."
 *
 * Context that sets the bar: this scanner exists to narrow down plays taken on
 * real money, and the owner trades HIGH CONVICTION LONGS because a backtest
 * said that cohort had the edge. So the page must show what the CURRENT report
 * says, not a number typed in once. Before this, section 4 asserted "~65% win,
 * +0.85R avg" for high conviction while the shipped long-only file put the
 * whole weekly cohort at 51.9% and +0.178R. A hard-coded claim cannot be wrong
 * loudly; it just ages.
 *
 * Reads the two published reports and renders whichever are present:
 *   vivek_backtest_longonly.json  the LONG-ONLY replay — the one that matches
 *                                 how the owner actually trades, so it leads.
 *   vivek_backtest.json           both directions, the canonical record.
 *
 * Honest by construction: every table states its own sample size and the share
 * of the universe it covers, because these replays run a slice, not the market.
 * Missing files, missing cohorts and missing fields all render as a dash — an
 * absent number is shown as absent rather than as a zero.
 */
(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const host = $("#sys-backtest");
  if (!host) return;

  const num = (v) => (typeof v === "number" && isFinite(v) ? v : null);
  const pct = (v) => (num(v) == null ? "—" : `${v.toFixed(1)}%`);
  const r2 = (v) => (num(v) == null ? "—" : (v >= 0 ? "+" : "") + v.toFixed(3));
  const int = (v) => (num(v) == null ? "—" : String(Math.round(v)));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /* Positive expectancy is the only thing that matters here, so it is the only
   * thing coloured. Win rate is deliberately NOT coloured: a 45% win rate with
   * a positive R is a good system and colouring it red would teach the wrong
   * lesson every time the page is read. */
  const rCls = (v) => (num(v) == null ? "" : v > 0.0005 ? "bt-pos" : v < -0.0005 ? "bt-neg" : "bt-flat");

  const row = (label, m, note) => {
    if (!m) return `<tr><td>${esc(label)}</td><td colspan="4" class="bt-none">not in this report</td></tr>`;
    return `<tr><td>${esc(label)}${note ? ` <span class="bt-note">${esc(note)}</span>` : ""}</td>` +
      `<td>${int(m.n)}</td><td>${pct(m.win_rate)}</td>` +
      `<td class="${rCls(m.avg_r)}">${r2(m.avg_r)}</td>` +
      `<td>${num(m.profit_factor) == null ? "—" : m.profit_factor.toFixed(2)}</td></tr>`;
  };

  const table = (title, rows) =>
    `<table class="sys-t bt-t"><tr><th>${esc(title)}</th><th>trades</th><th>win</th>` +
    `<th>avg R</th><th>profit factor</th></tr>${rows}</table>`;

  function coverageLine(d) {
    const cov = d.coverage || {};
    const parts = Object.keys(cov).sort().map((m) => {
      const c = cov[m] || {};
      const p = num(c.sampled_pct);
      return `${esc(m.toUpperCase())} ${int(c.symbols)}/${int(c.universe)}` +
             (p == null ? "" : ` (${p.toFixed(1)}%)`);
    });
    const p = d.params || {};
    return `<p class="bt-cov"><strong>Sample:</strong> ${parts.join(" · ") || "—"} ` +
      `over ${esc(p.period || "?")}, ${esc(p.timeframes ? p.timeframes.join("/") : "?")}. ` +
      `This is a SLICE of each market, not the whole of it — the percentages above are the coverage.</p>`;
  }

  /* REFINE200 #184: one report, one population. The long-only report reads
   * the *_long cohorts (falling back to the unsuffixed ones, which in that
   * file ARE long-only); the both-directions report reads the unsuffixed,
   * both-direction cohorts. Before this, the both-directions block read the
   * *_long keys first, so its conviction / timeframe / trigger tables summed
   * to the 837 longs while its grade table and Overall counted all 1,457 —
   * one table set whose rows did not add up to its own total. The per-cell
   * table is long-only by construction and says so in that block. */
  const pick = (res, key, longOnly) =>
    (longOnly ? (res[key + "_long"] || res[key]) : res[key]) || {};

  function block(d, title, lead, longOnly) {
    const res = d.results || {};
    const conv = pick(res, "by_conviction", longOnly);
    const gen = d.generated_at ? String(d.generated_at).slice(0, 10) : "—";

    let html = `<h3 class="bt-h">${esc(title)} <span class="bt-when">run ${esc(gen)}</span></h3>`;
    html += `<p class="bt-lead">${lead}</p>`;
    html += coverageLine(d);

    // The cohort the owner actually trades leads the panel. The rule that
    // produced it travels with the report (conviction_rule, since 2026-09-20):
    // a file written under the old "weekly reclaim, A/A+ or strong structure"
    // definition says so beside the row instead of wearing the new label.
    const rule = res.conviction_rule ||
      "weekly reclaim, A/A+ or strong structure (the rule BEFORE 2026-09-20 — next run re-measures the widened one)";
    html += table("High conviction", [
      row("🎯 High conviction", conv.high, rule),
      row("Everything else", conv.rest),
    ].join(""));
    if (!conv.high) {
      html += `<p class="bt-none">This report predates the high-conviction cohort. ` +
        `The next backtest run fills it in.</p>`;
    }
    // The four cells the widened rule is built from, one at a time (long only).
    const cells = res.by_conviction_cell_long;
    if (cells && Object.keys(cells).length) {
      html += table(longOnly ? "By conviction cell" : "By conviction cell (longs)",
        Object.keys(cells).map((k) => row(k, cells[k])).join(""));
    }

    const byTf = pick(res, "by_timeframe", longOnly);
    html += table("By timeframe", ["1W", "3D", "1D"].map((k) => row(k, byTf[k])).join(""));

    const byGrade = res.by_grade || {};
    html += table("By grade", ["A+", "A"].map((k) => row(k, byGrade[k])).join(""));

    const byEt = pick(res, "by_entry_type", longOnly);
    html += table("By entry trigger",
      ["reclaim", "retest", "break"].map((k) => row(k, byEt[k])).join(""));

    html += table("Overall", row("all trades in this report", res.overall));
    return html;
  }

  const load = (f) => fetch(f, { cache: "no-cache" })
    .then((r) => (r.ok ? r.json() : null)).catch(() => null);

  function show() {
    return Promise.all([
      load("data/vivek_backtest_longonly.json"),
      load("data/vivek_backtest.json"),
    ]).then(render).catch(() => {
      paint(`<p class="bt-none">The backtest reports could not be loaded.</p>`);
    });
  }

  /* UI100 review (2026-10-20): the reader's place survives the swap. The
   * tables are ~1,700-2,400px taller than the "Loading…" line, and the
   * browser's own scroll anchoring keeps the TOP of the viewport still --
   * which, for a reader who came back UP into section 8 from section 9, is
   * section 8's last paragraph, so section 9 (what they were reading) went
   * ~2,000px down the page with scrollY unchanged (overflow-anchor on the
   * host does not help; the host sat ~+195px down the screen). So when the
   * "Loading…" line is above the top third of the screen -- or above the
   * screen altogether -- most of what is being read is BELOW it: the element
   * after it (the next section) is held where it was and the tables open
   * above it. Lower down the screen (a reader scrolling down into section 8,
   * or one who scrolled up past the line and is reading section 8's opening)
   * and after a jump to #backtest, the plain behaviour stays: the tables
   * grow below what is being read. The browser's anchoring is off for the
   * one swap so the page is moved once, by us, not twice. */
  const READ_LINE = 1 / 3;     // of the viewport's height, from its top
  let keepBelow = false;       // false for a #backtest jump: its heading stays put
  const nextAfter = (el) => {
    while (el && !el.nextElementSibling) el = el.parentElement;
    return el ? el.nextElementSibling : null;
  };
  function paint(html) {
    const next = keepBelow ? nextAfter(host) : null;
    let before = null;
    if (next && host.getBoundingClientRect().top < window.innerHeight * READ_LINE) {
      before = next.getBoundingClientRect().top;
    }
    const root = before == null ? null : (document.scrollingElement || document.documentElement);
    const anchor = root ? root.style.overflowAnchor : "";
    if (root) root.style.overflowAnchor = "none";
    host.innerHTML = html;
    if (root) {
      const moved = next.getBoundingClientRect().top - before;
      if (moved) window.scrollBy(0, moved);
      root.style.overflowAnchor = anchor;
    }
  }

  function render([lo, both]) {
    if (!lo && !both) {
      paint(`<p class="bt-none">No backtest report is published yet.</p>`);
      return;
    }
    let html = "";
    if (lo) {
      html += block(lo, "Long-only replay",
        "The one that matches how these plays are actually traded: longs only, " +
        "no shorts. Read this first.", true);
    }
    if (both) {
      html += block(both, "Both directions",
        "The canonical record, longs and shorts together. Kept because it is the " +
        "full picture, not because it is the one being traded.", false);
    }
    paint(html);
  }

  // UI100 #99 (2026-10-20): the two reports are ~1.8 MB together and sit in
  // section 8 of 12, so they load as the section comes within ~1.5 screens
  // BELOW the viewport (or into it), not on page open. The margin is below
  // only, and the top 150px (the sticky header) does not count: a contents
  // jump to section 9 leaves section 8's last few pixels under the header,
  // and loading there would push the section the reader jumped to ~2,000px
  // down the page. A link straight to #backtest (or a jump to it) loads them
  // at once; no IntersectionObserver (old browser, the test sandbox) means
  // load now, as before. UI100 review (2026-10-20): coming back UP into
  // section 8 still loads them (the reader is reaching the section), and
  // paint() above keeps the section they came from where it was.
  let started = false;
  const start = () => { if (!started) { started = true; show(); } };
  const atBacktest = () => typeof location !== "undefined" && location.hash === "#backtest";
  const IO = typeof window !== "undefined" ? window.IntersectionObserver : undefined;
  if (!IO || atBacktest()) { start(); return; }
  keepBelow = true;
  const io = new IO((entries) => {
    if (entries.some((e) => e.isIntersecting)) { io.disconnect(); start(); }
  }, { rootMargin: "-150px 0px 1200px 0px" });
  io.observe(host);
  window.addEventListener("hashchange", () => {
    if (atBacktest()) { keepBelow = false; io.disconnect(); start(); }
  });
})();
