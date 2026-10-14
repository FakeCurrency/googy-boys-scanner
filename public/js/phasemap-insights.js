/* Insights page — live numbers (2026-07-03). The findings render from the
   LATEST weekly backtest artefacts (public/data/phasemap/stats/*.json)
   instead of hand-written figures that silently rot. If the stats files are
   missing, the static text (last committed run) stays as the fallback. */
(() => {
  "use strict";

  const grab = (url) => fetch(url, { cache: "no-cache" })
    .then((r) => (r.ok ? r.json() : null)).catch(() => null);
  const spct = (x) => (x == null ? "—" : (x >= 0 ? "+" : "") + (x * 100).toFixed(1) + "%");
  const hit = (c) => (c && c.t1_hit_pct != null ? c.t1_hit_pct + "%" : "—");
  const set = (id, term, html) => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = `<span class="pm-lg-term">${term}</span>${html}`;
  };

  // VIVEK walk-forward replay — fills independently of the PhaseMap stats.
  // REFINE200 #193: the LONG-ONLY report leads, because it is the population
  // the bot trades (long-only since 2026-09-21); the both-directions report
  // (shorts included) is only the fallback, and the card says which it read.
  Promise.all([grab("data/vivek_backtest_longonly.json"), grab("data/vivek_backtest.json")])
    .then(([lo, both]) => {
      const pickVb = [[lo, "long-only, the trades the bot takes"], [both, "both directions, shorts included"]]
        .find(([d]) => d && d.results && d.results.overall && d.results.overall.n);
      if (!pickVb) return;
      const [vb, which] = pickVb;
      const r = vb.results;
      const o = r.overall;
      const lv = r.by_level_tf || {};
      const cohort = (m, label) => (m && m.n
        ? `${label}: ${m.n} trades, ${m.win_rate}% win, ${m.expectancy_r >= 0 ? "+" : ""}${m.expectancy_r}R exp` : null);
      const parts = [cohort(lv.weekly, "Weekly-200"), cohort(lv["3d"], "3-Day-200"),
                     cohort(lv.h4, "Daily-200 (H4 proxy)")].filter(Boolean).join(" · ");
      const pf = o.profit_factor === null ? "∞" : o.profit_factor;
      set("fi-vivek", "VIVEK, replayed with real management",
        `${o.n} walk-forward trades (${which}; ${(vb.params && vb.params.period) || ""}, real engine, ` +
        `next-bar-open fills, stop-first, costs included): ${o.win_rate}% win rate, ` +
        `${o.expectancy_r >= 0 ? "+" : ""}${o.expectancy_r}R expectancy, profit factor ${pf}, ` +
        `${o.total_r >= 0 ? "+" : ""}${o.total_r}R total. By signal level — ${parts || "n/a"}. ` +
        `Where a level's expectancy holds up is where its badge earns a place on the chart.`);
    });

  // REFINE200 #193: the section heading's signal count is the sum of the
  // stats files' all.n (it was a typed "17,180" while the files said 29,008).
  const yearsOf = (p) => { const m = /^(\d+)y$/.exec(String(p || "")); return m ? `${m[1]}-YEAR` : ""; };
  function signalHeading(stats) {
    const live = stats.filter((d) => d && d.all && typeof d.all.n === "number");
    if (!live.length) return null;
    const total = live.reduce((a, d) => a + d.all.n, 0);
    const yrs = yearsOf(live[0].period);
    return `WHAT THE ${yrs ? yrs + " " : ""}REPLAY MEASURED (${total.toLocaleString("en-AU")} SIGNALS ` +
      `ACROSS ${live.length} MARKET${live.length === 1 ? "" : "S"})`;
  }
  Promise.all(["asx", "nasdaq", "crypto"].map((m) => grab(`data/phasemap/stats/${m}.json`)))
    .then((stats) => {
      const h = document.getElementById("fi-heading");
      const text = signalHeading(stats);
      if (h && text) h.textContent = text;
    });

  Promise.all([
    grab("data/phasemap/stats/asx.json"),
    grab("data/phasemap/stats/nasdaq.json"),
    grab("data/phasemap/stats/specs_asx.json"),
  ]).then(([asx, nas, sp]) => {
    if (!asx || !asx.cohorts) return;   // no artefacts yet — keep static text
    const c = asx.cohorts, n = (nas && nas.cohorts) || {};

    const gen = document.getElementById("fi-generated");
    if (gen) gen.textContent = `${asx.generated}, ruleset v${asx.ruleset_version}`;

    if (c["liquid"] && c["illiquid"])
      set("fi-liquidity", "Liquidity is the edge, not the enemy",
        `ASX liquid names: ${hit(c["liquid"])} reached T1 inside 20 sessions with ` +
        `${spct(c["liquid"].mae)} average worst drawdown. Illiquid names: ` +
        `${hit(c["illiquid"])} and ${spct(c["illiquid"].mae)}. Stocks ≥$1: ` +
        `${hit(c["price >= $1"])} hit. Cents stocks: ${hit(c["cents (<$1)"])}. ` +
        `The methodology scans everything; the measured edge lives at the liquid ` +
        `end. That's what the HIDE ILLIQUID toggle is for.`);

    if (n["tier A+"] && c["tier A+"])
      set("fi-aplus", "A+ means different things per market",
        `NASDAQ: A+ (anchor-context) setups hit T1 ${hit(n["tier A+"])} vs ` +
        `${hit(n["tier A"])} for plain A. ASX: A+ ${hit(c["tier A+"])} vs A ` +
        `${hit(c["tier A"])}. Same rules — watch whether each market's badge ` +
        `earns its keep in the latest replay.`);

    const rb = (asx.baselines && asx.baselines.random) || {};
    const nrb = (nas && nas.baselines && nas.baselines.random) || {};
    set("fi-frontload", "The edge vs random, horizon by horizon",
      `ASX signals vs random entry — 5 sessions: ${spct(asx.all.fwd_5)} vs ` +
      `${spct(rb.fwd_5)} · 10: ${spct(asx.all.fwd_10)} vs ${spct(rb.fwd_10)} · ` +
      `20: ${spct(asx.all.fwd_20)} vs ${spct(rb.fwd_20)}. NASDAQ at 20: ` +
      `${spct(nas && nas.all && nas.all.fwd_20)} vs ${spct(nrb.fwd_20)}. ` +
      `Where the signal line beats the random line is where this pattern pays.`);

    if (asx.stall)
      set("fi-fifty", "The 50% rule, measured",
        `Of ${asx.stall.stalled.toLocaleString()} ASX signals that touched the 50% ` +
        `zone: the stall saved capital ${asx.stall.saved_capital.toLocaleString()} ` +
        `times and cut a winner ${asx.stall.cut_winner.toLocaleString()} times. ` +
        `A momentum-quality filter, not a profit switch — its job is routing slow ` +
        `setups out of the continuation playbook.`);

    if (c["in-sample"] && c["out-of-sample"])
      set("fi-oos", "In-sample vs out-of-sample",
        `ASX fwd-20: ${spct(c["in-sample"].fwd_20)} in-sample vs ` +
        `${spct(c["out-of-sample"].fwd_20)} out-of-sample (hit rates ` +
        `${hit(c["in-sample"])} vs ${hit(c["out-of-sample"])}). Expect live ` +
        `results closer to the out-of-sample column than the headline.`);

    if (sp && sp.all)
      set("fi-specs", "Specs is a discovery lens, not an entry system",
        `${sp.all.n.toLocaleString()} replayed spec signals (${sp.period} ASX): ` +
        `buying the signal close returned ${spct(sp.all.fwd_5)} / ` +
        `${spct(sp.all.fwd_10)} / ${spct(sp.all.fwd_20)} at 5/10/20 sessions vs ` +
        `${spct(sp.baseline_random && sp.baseline_random.fwd_20)} for random entry ` +
        `on the same cheap universe. Use SPECS ⚡ to find names waking up, then ` +
        `demand structure (a trap, a reclaim, a level) before anything else.`);
  });
})();
