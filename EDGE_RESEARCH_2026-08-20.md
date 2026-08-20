# Edge research — 2026-08-20 (profitability batch)

Research-only pass over the live evidence: the confluence forward-return ledger
(first harvest), the paper book's 45 closed / 30 open positions, both backtest
files, and ~22 committed daily scan snapshots (2026-07-20 → 2026-08-20)
reconstructed from git history. **Nothing live was changed.** Reproduce the
ledger analyses any day with `python scripts/alert_edge_report.py [--baseline]`.

Conventions: returns are 5-TRADING-SESSION forward moves, SIGNED by the call
(long → +r, short → −r), so positive always means "went the way the system
said". "Dedup" = first occurrence per (market, ticker, side) — the same name
re-fires day after day while a setup lasts, and counting re-fires
pseudo-replicates one bet. SE beside every mean. Window caveat applies to
EVERYTHING here: ~4 weeks of a rising tape (NASDAQ names above their 200-day:
67%, vs 59% 6-month mean) — none of this is out-of-sample, and the short-side
findings especially may be regime, not truth.

---

## 1. Multi-lens confluence: the aligned badge adds nothing detectable — direction is the live wire

Ledger at analysis time: 800 alignments, 344 matured at 5 sessions (177 ASX /
155 NASDAQ / 12 crypto; every matured row dual-lens, 338 of them
PHASEMAP+VIVEK). 10-session n=3, 20-session n=0 — only the 5-session horizon
is answerable today.

**Aligned vs single-lens A+, identical scan-snapshot price plumbing (dedup):**

| cohort | n | mean 5s signed | SE | win |
|---|---|---|---|---|
| aligned (2-lens) | 314 | **+0.18%** | 0.31pp | 51% |
| A+ not aligned | 1100 | **+0.12%** | 0.20pp | 51% |

Difference 0.06pp on a combined SE of ~0.37pp — **nothing**. The ledger's own
independent Yahoo-close plumbing agrees (344 matured: −0.16% ± 0.31 all,
+0.13% ± 0.39 dedup). Day-clustered means (the honest serial-correlation
control) stay consistent and equally unable to separate the cohorts.

**The split that IS large, in both cohorts:**

| cohort | n | mean 5s signed | SE | win |
|---|---|---|---|---|
| A+ LONGS (unaligned) | 622 | **+1.58%** | 0.26pp | 62% |
| A+ SHORTS (unaligned) | 478 | **−1.78%** | 0.31pp | 38% |
| aligned LONGS | 111 | +0.06% | 0.55pp | 40% |
| aligned SHORTS | 203 | +0.25% | 0.37pp | 57% |

Read: in this window the LONG signal worked and the SHORT signal was actively
wrong. Alignment interacts with that: it roughly NEUTRALISES both — aligned
shorts stop bleeding (+0.25 vs −1.78, ~4 SE apart), aligned longs stop winning
(+0.06 vs +1.58, ~2.5 SE apart). A defensible summary: **PhaseMap agreement is
a filter against trending continuation in either direction** — good for the
short book, costly for the long book. With one regime and n=111 aligned longs,
treat as strong hypothesis, not law.

Sector splits exist in the report output; every bucket is n=13–34 and the
signs flip between price plumbings — TOO THIN, reported descriptively only.
Crypto: n=10–12, +2.5–3.4% means, TOO THIN.

**Bottom line for the deck**: the ⨂ aligned badge, as evidence of extra
5-session edge, is currently DECORATIVE in aggregate. Its one defensible use
today is on SHORTS (where it marks the ones that don't bleed) — which is
precisely the side the bot doesn't trade.

---

## 2. Live book vs the backtest's per-pattern claims: live matches the CANONICAL file, not the one the deck shows

Live closed book: 45 trades — **43 reclaim, 2 break, 0 retest** (the bot skips
retest by rule: `skip_entry_types: ["retest"]`). So live evidence exists for
exactly one pattern; the deck's three-way comparison cannot be validated
pattern-by-pattern from live data, and says nothing about retest at all.

| source | reclaim expectancy | n | win |
|---|---|---|---|
| deck's tint file (`vivek_backtest_longonly.json`, 10y, longs) | **+0.178R** | 1099 | 48.7% |
| canonical weekly (`vivek_backtest.json`, 5y, blended) | **−0.096R** | 525 | 45.5% |
| canonical weekly, LONGS overall | −0.031R | 835 | 44.8% |
| **LIVE, all reclaim closes** | **−0.153R** | 43 | 37% |
| LIVE, rules-only reclaim closes | −0.393R | 17 | 29% |

Live is **3.6 SE below the +0.178R claim** (SE 0.092) — not sample noise — and
sits right on the canonical file's numbers. Whatever is steering the deck's
green "best cell" chip, live reality has been voting for the other file.
Confounds stated: 26 of 45 closes were the owner's (their reclaim record is
+0.003R vs the rules' −0.393R), and the window is one regime. But direction
and magnitude both favour the canonical file.

Also notable (live, all closes): timeframe split — 1D entries −6.82R total
(n=20), 1W entries +0.88R (n=20), 3D −0.94R (n=5).

---

## 3. Where the rules-side R bleeds: one cell — full stops on 1D entries

Rules-only closes: n=19, −6.97R total.

| mechanism | n | total R | mean R |
|---|---|---|---|
| stop | 7 | **−9.05R** | −1.29R |
| time (28d) | 11 | **+2.14R** | +0.19R |
| trail | 1 | −0.06R | — |

- **All 7 full stop-outs were 1D-timeframe entries.** No 1W entry has ever hit
  a full stop; the 1W cohort's only mechanical exits are time-stops (+0.38R
  over 7).
- **The stopped trades were wrong from entry, not winners given back**: 3 of 7
  never ticked positive at all (MFE exactly 0.0R — WHC −2.1, TSLA −1.4, MVF
  −1.3), and the other four peaked at +0.15R to +0.29R before dying. No stop
  width or trail tuning rescues a trade whose MFE is zero — this is an ENTRY
  quality problem on the 1D/H4-proxy level, not an exit tuning problem.
- **The 28-day time-stop is not a bleed — it has been a harvester** (+2.14R,
  and its 11 exits' MFE shapes show it collecting modest winners/scratches).
  Post-freeze instinct to "fix" the time-stop first would aim at the one
  mechanism that's working.
- Sector conditioning on this cohort is IMPOSSIBLE today: the rules-side
  stop-outs carry no sector field on their closed rows (all pre-enrichment).
  Said plainly rather than approximated.
- Sample honesty: 7 stops. The concentration (7/7 = 1D) has a binomial
  probability of ~0.4% if stops were equally likely across the 20/5/20
  1D/3D/1W closed mix — real-looking, but one regime.

**Post-freeze proposal shape (NOT for now): the evidence points at 1D-proxy
entry quality (or a 1D-specific confirmation requirement), and explicitly NOT
at loosening stops or shortening the time-stop.**

---

## 4. The open book's +8.65R unrealized: majority tide, held in few names

Open book: 30 longs (allow_shorts off), +8.65R unrealized (17 winners / 13
losers). Concentration: crypto 3 positions = **+4.09R (47%)**; Materials 3
positions = +2.13R (25%). Six positions carry ~72% of the paper profit.

**Tide sensitivity, measured not assumed** — regress the current holdings'
equal-weight daily returns (22 overlapping days of committed snapshots)
against daily changes in the same market's above-200-day share:
corr **0.67** (ASX) / **0.50** (NASDAQ), beta ≈ 0.36–0.41% book move per
1.00pp breadth change.

Breadth mean-reversion scenario (to each market's own 6-month mean: NASDAQ
67.2% → 58.7%, ASX 47.5% → 37.7%): implied book mark move ≈ **−3.5%**. Applying
a uniform −3% to every mark against real stops: **0 of 30 positions stop out,
but unrealized goes +8.7R → +3.7R (58% of the paper profit gone)**. At −5%:
2 stop-outs, book ≈ 0R. At −10% (the February trough revisited): 5 stop-outs,
−10.9R.

Plain-English answer: **a bit under half of the current unrealized R survives
an ordinary reversion of breadth to its 6-month average; the stops protect the
capital but not the paper profit, and roughly half the profit is three crypto
marks.** Selection is real (see §7) but the current +8.65R headline is mostly
regime. Calibrate post-freeze confidence accordingly.

(The handoff's "67% above 200-day" is the NASDAQ number; ASX reads 47.5% now
vs its 37.7% mean — stretched on both, more so on NASDAQ.)

---

## 5. The backtest-tint conflict: every setup disagrees, and the window drives more of it than the shorts do

The two files disagree on ALL THREE patterns, including a rank inversion:

| pattern | tint file (longonly, **10y**, Aug 1) | canonical (blended, **5y**, Aug 16) | deck tint today |
|---|---|---|---|
| reclaim | **+0.178R** (n=1099, PF 1.32) | **−0.096R** (n=525, PF 0.84) | GREEN |
| retest | +0.026R (n=737) | −0.163R (n=825) | AMBER |
| break | +0.014R (n=206) | **+0.084R** (n=183, 57.9% win, PF 1.24) | AMBER |

Ranking flips: tint says reclaim ≫ retest > break; canonical says
**break > reclaim > retest**. The bot trades reclaim almost exclusively.

**Which difference drives it — long-only vs blended, or the window?** Both are
material, and the files decompose it: canonical overall −0.111R; canonical
LONGS-only −0.031R; tint (longs, 10y) +0.107R. So removing shorts recovers
+0.080R, while moving the window/vintage (5y↔10y, Aug 16↔Aug 1 engine) is
worth **+0.138R** — **the window/vintage gap is the bigger driver.** The
long-only file's edge substantially lives in the older half of its 10-year
window; on the last 5 years even longs are ~breakeven in the canonical replay.
(Third confound, stated: the two files were generated 15 days apart across a
fortnight of engine changes — cadence alone can move numbers.)

**Recommendation, plainly**: the tint should read numbers that are (a)
LONG-ONLY — that is what the bot and Vivek actually trade (`allow_shorts:
false`), so blended-with-shorts numbers answer the wrong question — but (b)
from the CANONICAL 5y window and weekly cadence. Today's files force a choice
between right-methodology-stale-window (tint file) and
right-window-wrong-population (canonical). Neither is correct as-is. The clean
fix after the freeze: have the weekly `lens_backtest.yml` run publish a
long-only `by_entry_type` block (or a direction × entry-type cross-tab) and
point `loadEntryQuality()` at that. Until then, know that the live book's own
43 reclaims (−0.15R) side with the canonical file, and the green reclaim chip
is standing on 2016–2021.

Also worth knowing while deciding: BOTH files run `limit: 60` symbols per
market — the evidence base for every per-pattern claim is ~4% of the universe
the bot actually trades (TOP100 #58's caveat still bites both files).

---

## 6. Score and tags vs 5-session forward returns: two decorative, one actively suspicious

Method: every A+/A row from 22 daily scan snapshots, dedup first-occurrence,
5-session signed scan-price returns (n=1,695; ASX+NASDAQ).

- **SMA score (within grade A+, isolating its increment): NOISE.** Spearman
  ρ = **+0.012** (n=795). Buckets: score 8 → −0.17% (n=303), score 9 → +0.35%
  (n=381), score 10 → **−0.75%, 42% win** (n=111). Not even monotonic. At the
  5-session horizon the 8-vs-10 distinction the deck displays carries no
  information.
- **🎯 High conviction (weekly reclaim + A/strong structure): does NOT
  outperform — suggestively the opposite.** Tagged −0.62% (n=170, 41% win) vs
  untagged +0.12% (n=1,525). Longs only: tagged +0.36% (n=107) vs untagged
  **+1.44%** (n=813) — ~1.6 SE apart, same direction as §1's aligned-longs
  result and §2's live reclaim record. Three independent measurements now
  point the same way: **the weekly-reclaim cell the badge celebrates is not
  where the current edge is.**
- **Strong structure chip: no incremental signal.** Longs: chip +1.23%
  (n=406) vs no chip +1.38% (n=514) — indistinguishable. Its raw split is
  direction composition, nothing more.

Fairness caveat: these tags claim full-trade merit from a multi-year backtest;
this test is 5-session forward returns in one month. A tag could fail here and
still matter at 30 sessions — but nothing measurable TODAY supports the
attention they cost, and High conviction fails in the same direction live.

---

## 7. Stretch finding: the LONG side carries real selection alpha; the SHORT side is inverted in this regime

Control: each day's MEDIAN name return (price ≥ 10¢ — a plain mean control is
garbage here; ASX micro-caps alone made the naive mean read +3.9%/5s).

| cohort (dedup, grade_raw A+) | n | excess over median name | SE | win |
|---|---|---|---|---|
| ASX longs | 293 | **+1.09%/5s** | 0.33pp | 63% |
| NASDAQ longs | 323 | **+1.02%/5s** | 0.39pp | 54% |
| ASX shorts (signed) | 237 | **−1.56%/5s** | 0.36pp | 40% |
| NASDAQ shorts (signed) | 243 | −0.96%/5s | 0.47pp | 51% |

- **The long-side result replicates independently in two markets at ~3 SE
  each, above the tide.** That's the strongest positive statement this batch
  can make: A+ long selection is not just beta — roughly +1% per week of
  excess over the median name in this window.
- **The short-side signed excess is NEGATIVE in both markets** — names marked
  as A+ shorts have been OUTPERFORMING the median name. Not "shorts fight a
  rising tape" (the control removes the tide) — the short signal itself has
  been anti-predictive this month. The bot doesn't trade shorts (good); the
  deck displays them as opportunity and 65% of confluence alerts are shorts —
  attention currently spent on an inverted signal. Whether it inverts back in
  a down-tape is untested and untestable from this window.
- Day-of-week sweep: nothing (all buckets within ±1 SE of zero). Looked,
  nothing real.

Honest labels: in-sample, one regime, 5-session horizon, scan-price plumbing.
The long-alpha number is the one worth re-running monthly as the snapshot
history grows (`alert_edge_report.py --baseline` covers the aligned-vs-A+
half; the excess-over-median control is documented here and trivially
re-derived from the same snapshots).

---

## What to actually take from this batch (one paragraph)

The system's measurable edge right now is **plain A+ LONG selection**
(~+1%/week over the median name, both markets) — not the aligned badge (§1:
no aggregate edge), not the High-conviction cell (§6: underperforms), not the
score digits (§6: noise), and not the short signal (§7: inverted this month).
The realized bleed is **entirely 1D-entry full stops that were wrong from
entry** (§3), while the much-maligned time-stop has been quietly harvesting.
The +8.65R of open profit is majority tide and half-carried by three crypto
positions (§4). And the deck's green reclaim chip reads a 10-year long-only
file whose claim the live book contradicts at 3.6 SE, while the canonical 5y
file — which live matches — says break > reclaim > retest (§5): resolving that
tint is the single highest-leverage decision on the table for Sep 4.
