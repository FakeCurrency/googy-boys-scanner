# DECISION-PACK-N30 — Parity Backtest Evidence
**Issued:** 2026-08-01  
**Repo:** `googy-boys-scanner` @ main  
**Purpose:** Owner iterate-or-scale ruling (ROADMAP.md P1) when the live book reaches n≥30.  
**Units:** R only (primary). Dollar figures secondary under fixed-notional $5k.  
**Caveat on every table:** survivorship bias — today's universe, yfinance history, no delisteds.

---

## 0. One-page verdict

### Do not scale. Iterate.

| Question | Answer |
|---|---|
| Does the **exact live rule-set** have positive expectancy over history? | **No.** Portfolio parity: **−0.033R/trade**, **−0.019R per slot-month** (n=613 taken). |
| Does that match the live book? | **Yes in shape.** Live 21 closed: **−6.40R**, 38% win. All −9.05R of stop losses were full-size; the +2.64R gain side was 28d time-stops + manual cuts. Parity reproduces the same exit anatomy at scale. |
| Which **single** rule change most improves R/slot-month under the formal PASS gate? | **V2 — early momentum cut at day 14 if peak mfe_r < 0.5.** Only variant that PASSed ASX **and** NASDAQ **and** both time halves. Lift is real but **small** (+0.0036 R/sm) and the book remains **net negative** (−0.015 R/sm). |
| Best economic candidate that failed the formal gate? | **V3 — weekly `level_tf` only.** +0.074 R/sm overall, **+0.105R/trade**, PF 1.50, n=197 — but ASX R/sm did not improve (−0.0522 → −0.0535). Not a PASS. |
| What should the 30 × $5k slots do next month? | **Do not raise size or go live.** Keep paper. Prefer **iterate**: (1) trial V2 early-cut as a paper overlay or next rule candidate once n≥30 is logged; (2) instrument and watch **weekly-level** vs h4 splits on the live book (now stamped); (3) do **not** lengthen/remove the 28d time-stop on current evidence. |

**Survivorship caveat:** every historical number below excludes delisted names and uses yfinance dividend-adjusted dailies. Treat magnitudes as directional evidence, not investable edge.

---

## 1. Live book vs parity baseline

### 1a. Live bot book (track record — n=21 closed, 2026-08-01)

| Exit path | n | Total R | Mean R | Wins |
|---|---|---|---|---|
| **Stop** | 7 | **−9.05R** | −1.29 | 0/7 |
| **28d time-stop** | 10 | **+1.66R** | +0.17 | 5/10 |
| **Manual** | 4 | **+0.98R** | +0.24 | 4/4 |
| **All** | 21 | **−6.40R** | −0.305 | 8/21 (38%) |

- Stops never reached TP1 first. Entire gain side is time-stop + owner cuts.
- After `level_tf` audit backfill (45/48 rows): closed mix **h4 12 / 3d 4 / weekly 3 / missing 2**. Live closed R by level: h4 **−4.11R**, 3d −0.86R, weekly −0.15R (tiny n).

### 1b. Parity baseline (exact live lifecycle, sim)

**Config mirrored:** A+ only · long-only · funds out · skip retest · prefer_tf one plan (1W>3D>1D) · TP ladder + trail · 28d pre-TP1 time-stop · min price / stop width / ADV gates · global 30 slots · one-per-symbol · sector cap 3 · 7d stop cooldown.  
**Not replayed:** earnings buffer, daily/weekly loss guards.

**Coverage (this run):** stratified sample **120 ASX + 120 NASDAQ + 95 crypto (full)** over **5y**  
(ASX 6.7% of 1,792 liquid non-fund names; NASDAQ 8.7% of 1,372; crypto 100%).  
Artefact: `public/data/vivek_backtest_parity.json`.

| Cohort | n | Win% | Exp R | Total R | R / slot-month | Slot-months |
|---|---|---|---|---|---|---|
| Eligible signals (pre-slot) | 764 | 49.0 | −0.012 | −9.28 | — | — |
| **Portfolio taken (live caps)** | **614** | **48.0** | **−0.033** | **−20.21** | **−0.0191** | 1056.5 |
| Peak open | 30 | | | | skips: cooldown 11, sector 88, book_full 51 | |

### 1c. Exit anatomy (portfolio taken) — the smoking gun, scaled

| Exit | n | Win% | Exp R | Total R | Avg hold |
|---|---|---|---|---|---|
| **stop** | 139 | 0.0 | **−1.287** | **−178.87** | 14.0d |
| **time** (28d pre-TP1) | 314 | 51.0 | +0.044 | +13.89 | 29.5d |
| **trail** | 119 | 80.7 | +0.477 | +56.78 | 44.7d |
| **target** | 35 | 100.0 | +2.514 | +88.00 | 234.6d |
| eod | 7 | 57.1 | ~0 | ~0 | — |

**Read:** the system does not pay for its stops. Winners that reach the ladder pay; time-stop is approximately flat-to-slightly-positive slot hygiene; stops are a −179R hole. This is the same structure as the live 21.

### 1d. By market / level / entry (portfolio taken)

| Slice | n | Exp R | Total R | R/sm |
|---|---|---|---|---|
| ASX | 132 | −0.095 | −12.49 | −0.052 |
| NASDAQ | 423 | +0.001 | +0.39 | +0.001 |
| crypto | 59 | −0.137 | −8.10 | −0.055 |
| **level weekly** | 179 | **+0.064** | **+11.47** | — |
| **level 3d** | 102 | **+0.069** | **+7.02** | — |
| **level h4** | 333 | **−0.116** | **−38.69** | — |
| entry reclaim | 581 | −0.028 | −15.99 | — |
| entry break | 33 | −0.128 | −4.21 | — |

| Time half (split entry 2024-04-10) | n | Exp R | R/sm |
|---|---|---|---|
| First | 307 | −0.065 | −0.033 |
| Second | 307 | −0.001 | −0.0005 |

Second half is less bad, not good. No half is a clean positive book under live rules.

### 1e. Published Insights backtest vs parity (why the old number lied)

| | Published walk-forward (pre-parity) | Parity (this pack) |
|---|---|---|
| Grades | A+ **and A** | **A+ only** |
| Direction | longs + shorts (unless flagged) | **long-only** |
| Plans / symbol | up to 3 TF slots | **one** prefer_tf plan |
| Time-stop | **not simulated** | **28d pre-TP1** |
| ADV / stop-width gates | partial / none historically | **on** |
| Claimed edge | portfolio sim ~+0.5R/trade on a different machine | **−0.033R/trade** on the live machine |

The raw multi-grade signal underneath was already weak; stripping to the live bot removes the optimistic gap.

---

## 2. Variant grid (same entry population, one delta)

**PASS rule (frozen):** variant R/slot-month must beat baseline on **overall**, on **ASX**, on **NASDAQ**, and on **both time halves**. Crypto reported, not a gate.

| Variant | Delta | R/sm base → var | Δ | PASS? | Notes |
|---|---|---|---|---|---|
| V1 hold 42d | longer time-stop | −0.019 → −0.0273 | **−0.0083** | fail | worse everywhere |
| V1 hold 56d | longer | −0.019 → −0.0260 | **−0.0070** | fail | worse everywhere |
| V1 hold off | no time-stop | −0.019 → −0.0195 | **−0.0005** | fail | ASX much worse (−0.066) |
| V2 cut d10 mfe&lt;0.25 | early cut | −0.019 → −0.0189 | +0.0001 | fail | |
| V2 cut d10 mfe&lt;0.5 | early cut | −0.019 → −0.0194 | −0.0004 | fail | |
| V2 cut d14 mfe&lt;0.25 | early cut | −0.019 → −0.0158 | +0.0032 | fail | half/market gate |
| **V2 cut d14 mfe&lt;0.5** | **early cut** | **−0.019 → −0.0154** | **+0.0036** | **PASS** | **Only formal PASS** |
| V3 weekly level only | entry filter | −0.019 → **+0.0549** | **+0.074** | **fail** | ASX R/sm −0.0522 → −0.0535 |
| V4 break only | entry filter | −0.019 → −0.0645 | −0.045 | fail | worse |
| V4 reclaim+break | = baseline entries | −0.019 → −0.019 | 0 | fail | control |

### V2 PASS detail (best formal delta)

| Check | Baseline R/sm | Variant R/sm | Δ | Pass |
|---|---|---|---|---|
| Overall | −0.019 | −0.0154 | +0.0036 | ✓ |
| ASX | −0.0522 | −0.0499 | +0.0023 | ✓ |
| NASDAQ | +0.0008 | +0.0091 | +0.0083 | ✓ |
| Half 1 | −0.0328 | −0.0300 | +0.0028 | ✓ |
| Half 2 | −0.0005 | +0.0046 | +0.0051 | ✓ |

Still **negative expectancy** after the cut (−0.022R/trade). It frees dead slots earlier; it does not create an edge.

### V3 near-miss (best economics, failed ASX gate)

| | n | Exp R | Total R | R/sm | PF |
|---|---|---|---|---|---|
| Weekly-only portfolio | 197 | **+0.105** | **+20.72** | **+0.0549** | **1.50** |

Fails only because ASX R/sm does not improve (essentially flat-to-worse on thin ASX weekly n). NASDAQ and both halves improve hard. **Not a PASS under the pre-committed rule** — but the highest-leverage research lead in the pack.

---

## 3. Book instrumentation shipped

| Item | Status |
|---|---|
| Stamp `level_tf` on **new** tickets | Done in `vivek_run._ticket_to_position` (audit-only; `vivek_bot.py` untouched) |
| Backfill existing 48 rows | Done via `scripts/backfill_level_tf.py --apply` — **45/48** filled (3 failed evaluate/download); frozen-field verify clean; combined book **27 open / 21 closed**; closed R still **−6.404** |
| Distribution now | h4 23 · 3d 14 · weekly 8 · missing 3 |

---

## 4. What the 30 slots × $150k should do next month

1. **Do not scale** size, leverage, or live capital. Parity says the live machine is negative; the live book agrees in structure.
2. **Do not kill** on n=21 alone — but n=614 parity trades is enough to reject “scale now.”
3. **Iterate candidates (priority order):**
   1. **Watch weekly vs h4 on the live book** now that `level_tf` is stamped — if live weekly continues to dominate, V3 becomes the next rule trial (accept ASX thin-n risk explicitly).
   2. **V2 day-14 / mfe&lt;0.5 early cut** — only formal PASS; implement as paper overlay only after owner sign-off (rule change resets the n clock).
   3. **Do not** remove or lengthen the 28d time-stop — V1 (42d / 56d / off) is **strictly worse** on R/slot-month (Δ −0.0005 to −0.0083). The 28d cut is already earning its keep as slot hygiene.
4. **Capacity:** book is still the binding constraint. Until expectancy is positive, filling empty slots with the same machine increases the rate of learning, not the rate of profit.

---

## 5. Reproducibility

```bash
# Parity + variant grid → public/data/vivek_backtest_parity.json
python -m scanner.vivek_backtest --parity --market all --limit 120 --period 5y

# Full universe (slow; same code path, limit 0)
python -m scanner.vivek_backtest --parity --market all --limit 0 --period 5y

# level_tf backfill (dry then apply)
python -m scripts.backfill_level_tf
python -m scripts.backfill_level_tf --apply
```

Constants: `scanner/config.py` → `VIVEK_PARITY_*` (simulation-only; live bot reads `VIVEK_BOT_*` only).  
Tests: `tests/test_vivek_parity.py`.

---

## 6. Bottom line for the owner

> **No demonstrated positive edge under the live rule-set. Do not scale. The single formal PASS is an early-momentum cut at day 14 if mfe_r never reached 0.5 — it improves R/slot-month slightly but leaves expectancy negative. The largest economic lift in sample is restricting to weekly levels, which fails the ASX half of the PASS gate. Iterate on exit quality and level_tf mix; keep the 30×$5k paper book as the clock, not as a production allocator.**

*Survivorship bias applies to every historical cell in this memo.*
