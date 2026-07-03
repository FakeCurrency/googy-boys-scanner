/* Insights page — live numbers (2026-07-03). The findings render from the
   LATEST weekly backtest artefacts (public/data/phasemap/stats/*.json)
   instead of hand-written figures that silently rot. If the stats files are
   missing, the static text (last committed run) stays as the fallback. */
(() => {
  "use strict";

  const grab = (url) => fetch(url, { cache: "no-cache" })
    .then((r) => (r.ok ? r.json() : null)).catch(() => null);
  const pct = (x, dp = 1) => (x == null ? "—" : (x * 100).toFixed(dp) + "%");
  const spct = (x) => (x == null ? "—" : (x >= 0 ? "+" : "") + (x * 100).toFixed(1) + "%");
  const hit = (c) => (c && c.t1_hit_pct != null ? c.t1_hit_pct + "%" : "—");
  const set = (id, term, html) => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = `<span class="pm-lg-term">${term}</span>${html}`;
  };

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
