# RESEARCH LEDGER — the edge program (2026-08-01 → 2026-08-02) and cycle w3-1

The permanent record of what was tested, what died, what survived, and under
what rules the one survivor is now being traded. Written at program close so
no future session re-litigates a killed idea without new evidence, and no
number gets quoted without its caveat. Method first, because the method is
the reason the numbers can be trusted.

## Method (the rules every result below was produced under)

- **Pre-registered gates.** Every confirmation run had its pass/fail
  thresholds fixed and written down BEFORE the run. No post-hoc cell
  promotion: a cohort that looked good in a slice it was not pre-registered
  on was treated as a hypothesis for the NEXT disjoint sample, never as a
  result.
- **Disjoint samples.** IS / OOS / C3 share no symbols (each run excludes
  every symbol any earlier sample used — the `--exclude-from` union). Three
  positives in a row cannot be the same lucky names three times.
- **R units only.** The 2026-07-28 notional resize makes dollar series
  incomparable across it; R divides by each trade's own initial risk and
  survives. Every expectancy below is R/trade; capacity-adjusted numbers are
  R/slot-month (total_r ÷ Σ calendar-days-held/30.4375), because 30 slots —
  not signal supply — are the binding constraint.
- **Pessimistic fills are the default.** Stop-first on ambiguous bars, gap
  pricing on gaps, slippage + commission charged (2× cost stress on every
  survivor). Midpoint/optimistic re-sims exist only to bound fill-model
  sensitivity, never as headline numbers.
- **Survivorship caveat on everything.** yfinance history is today's
  universe; delisted names are missing. Every positive number below is
  pre-survivorship and should be read as an upper bound until a
  survivorship-clean provider is wired (open owner decision).
- **"Done" = pushed + CI green + independently recomputable from committed
  artifacts.** Anything less is a claim, not a result.

## The evidence artifacts (all committed, all recomputable)

| Artifact (public/data/) | What it is |
|---|---|
| `vivek_backtest_parity.json` | IS parity run: 763 candidates, 613 taken, baseline live rules |
| `vivek_backtest_parity_oos.json` | OOS confirmation: 1,125 / 587 taken, symbol-disjoint |
| `vivek_backtest_parity_c3.json` | C3 final confirmation: 1,101 / 686 taken, disjoint from both |
| `vivek_parity_is/oos/c3_symbols.json` | The exact symbol samples (exclusion inputs) |
| `vivek_fill_sensitivity.json` | 3,600 re-sim rows across pessimistic/midpoint/optimistic fills |
| `vivek_confluence_study.json` | 1,200 rows: PhaseMap ALIGNED / OPPOSED / NONE at entry |

## KILLED (do not reopen without new out-of-sample evidence)

- **The full live rule-set as an edge.** IS −0.033 R/trade on 613 taken
  trades. The machine as a whole does not pay for its costs.
- **Level split as "weekly is better" (first form).** Failed pre-registered
  G2 out-of-sample. (The narrower weekly+3d COHORT later survived three
  samples — see below. The distinction is the pre-registration.)
- **Confluence alignment as an entry filter (C1).** Sign flipped across
  samples: ALIGNED +0.0103 (n=229) vs NONE +0.0098 (n=780) — no additive
  edge, and the earlier-sample advantage did not replicate.
- **PhaseMap opposition as a hard veto.** OPPOSED is mildly negative
  (−0.0906, n=191) — real but small and thin; ruled a soft caution, not an
  entry rule. C2 passed; economic weight does not justify a gate.
- **Stop redesign as an edge source.** The "stop hole" was substantially a
  fill-model artifact: pess −0.0013 / mid +0.0405 / opt +0.0090 on the same
  3,600 trades. Perfect-execution ceiling ≈ +0.04 R/trade — that is the
  MOST any exit engineering can recover, before costs of achieving it.
- **Shorts via mirrored logic.** −0.373 R/trade, PF 0.41, on
  survivorship-FLATTERED data; PhaseMap short zones tested adverse.
  Markets are not symmetric: drift, downside-vol asymmetry, gap/borrow
  costs all live on the short side. Chart-inversion is a de-biasing lens,
  not a signal source.
- **Crypto as a cohort.** Negative across samples; no tested edge.
- **Thin-liquidity names.** Negative after honest fills; the liquidity gate
  exists for a reason.
- **Filter stacking.** The canonical overfit exhibit: IS +0.131 → OOS
  −0.009. Stacked conditions manufacture in-sample edge at the exact rate
  they destroy out-of-sample edge.

## SURVIVED — the weekly+3d cohort (thrice-replicated)

Candidate entries whose headline plan level_tf ∈ {weekly, 3d}:

- Per-sample R/trade: IS +0.066 · OOS +0.043 · C3 +0.059
- C3 pre-registered gates: W-1 pooled +0.0589 R/t, +0.0336 R/sm (n=344) ·
  W-2 NASDAQ-alone +0.0342 / +0.0203 (n=258) · W-3 both survive 2× cost
  (+0.0285 / +0.0156). ALL PASS.
- Three-sample pooled: n=918, **+0.0559 R/trade, +0.0308 R/slot-month**;
  at 2× cost +0.0260 R/sm.
- Honest economics: ≈ +0.9R/month book-wide ≈ +11R/yr ≈ **$3–7k/yr
  equivalent** at current sizing on the $150k paper book. Real, small,
  pre-survivorship. Not a business by itself; the smallest honest edge
  worth live slot-time.
- Descriptive only (n=21): of the real closes to date, the gate would have
  kept 7 (−1.01R) and dropped 14 (−5.39R).
- Throughput: fill rate 0.99–1.00 in every sim; slots bind, not signals.

## LIVE — cycle w3-1 (owner-signed 2026-08-02, rules frozen)

- **Mechanics:** `VIVEK_BOT_LEVEL_TF_ALLOW = ("weekly", "3d")` — candidate
  rows outside the allowlist never reach `decide()`; FAIL-CLOSED on a
  missing/blank level_tf. Entries only: held positions, exits, time-stops,
  guards untouched. Ringfenced `vivek_bot.py` unmodified. New rows are
  stamped `cycle: "w3-1"` at entry. Revert = empty tuple (byte-identical
  prior behaviour, pinned by test). Enablement commits: 29d3ea1c →
  1a195cec → 090c9272 (gate live) → 2042438f. `tests/test_level_gate.py`.
- **The read at n=30 closed cycle trades:** PASS = expectancy ≥ 0 R/trade
  AND ≥ 0 R/slot-month → continue (scale question may reopen under a new
  protocol). KILL = expectancy ≤ −0.05 R/trade → revert the gate. Between →
  one more 30-close cycle, no tuning of any kind.
- **No other changes ride along.** V2 off, shorts off, no live capital
  regardless of outcome (separate, later ruling).
- **Where to watch:** the daily evidence brief prints
  `cycle w3-1: n/30 closed (exp ...) | k open gated | band pess +0.056 /
  mid +0.10 R/t`. Counted ONLY on the entry-time cycle stamp, so pre-gate
  history can never blur in.

## Open questions (parked, not killed)

- **Survivorship-clean data** (EODHD/Norgate) — would firm up or shrink
  every number above; owner decision, costs money.
- **Owner discretion as a selection layer** — his manual take was
  profitable while the machine's full set was not; unmeasurable from
  committed artifacts alone (no counterfactual log of what he saw).
- **Long+short architecture** — feasible in the engine (direction fields
  exist end-to-end), but the short side must first show ANY positive
  cohort under honest fills. Nothing does today.
- **ASX FX sizing (#61 live half)** — A$5,000 ≠ US$5,000; makes every ASX
  position ~30% smaller than intended. One line, ringfenced file, owner
  sign-off required.

*Maintained by Claude. Update this file when a cycle concludes or a new
pre-registered result lands — and never mid-cycle to move a threshold.*
