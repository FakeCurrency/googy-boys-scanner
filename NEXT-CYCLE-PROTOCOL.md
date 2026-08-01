# NEXT-CYCLE-PROTOCOL — Pre-registered after OOS level-split test
**Issued:** 2026-08-01  
**Repo:** `googy-boys-scanner` @ main  
**Inputs:** `public/data/vivek_backtest_parity.json` (IS), `public/data/vivek_backtest_parity_oos.json` (OOS), `public/data/vivek_parity_oos_gates.json`  
**Units:** R only. **Caveat on every number:** survivorship bias (today’s universe, yfinance, no delisteds).  
**Constraint:** simulation + proposal only. `vivek_bot.py` untouched. No live rule change until the owner signs this protocol.

---

## 0. One-line ruling this pack supports

### Level split is **NOT CONFIRMED** out-of-sample. Do not ship a `level_tf` gate. Do not enable V2 alone. Do not scale.

G1 and G3 passed; **G2 failed** (NASDAQ h4 was *not* worse than weekly+3d OOS). Pre-registered rule: all three gates required. Failed → redesign entries, not a concentrated book.

---

## 1. Pre-registered gates (written before looking at OOS) — results

| Gate | Rule | Result | Detail |
|---|---|---|---|
| **G1** | weekly+3d pooled R/slot-month > 0 overall **and** on NASDAQ alone | **PASS** | overall **+0.0207** (n=293); NASDAQ **+0.0118** (n=215) |
| **G2** | h4 R/sm < weekly+3d R/sm on **ASX and NASDAQ separately** | **FAIL** | ASX: h4 **−0.068** < w3 **+0.058** ✓ · NASDAQ: h4 **+0.019** ≰ w3 **+0.012** ✗ |
| **G3** | G1’s NASDAQ weekly+3d survives **2× cost_r** | **PASS** | NASDAQ w3 @2× cost R/sm **+0.0087** |
| **Bundle** | G1 ∧ G2 ∧ G3 | **FAIL** | Level split **not confirmed** |

**Disjointness:** OOS sample excluded the deterministic IS 120+120 symbols. Overlap = 0. ASX OOS 240 / NASDAQ OOS 240. Period 5y. Artefact: `vivek_backtest_parity_oos.json`.

**Survivorship caveat:** both IS and OOS use today’s listed universe.

---

## 2. What the OOS sample actually said (context, not gates)

| Cohort (portfolio taken) | n | Exp R | Total R | R/sm |
|---|---|---|---|---|
| OOS overall | 587 | **+0.022** | +12.73 | +0.0095 |
| OOS weekly | 173 | +0.038 | +6.62 | +0.020 |
| OOS 3d | 120 | +0.050 | +5.94 | +0.022 |
| OOS h4 | 294 | +0.001 | +0.17 | +0.000 |
| OOS ASX | 150 | −0.027 | −4.04 | −0.015 |
| OOS NASDAQ | 437 | +0.038 | +16.77 | +0.016 |
| OOS weekly+3d (surviving set) | 293 | +0.043 | +12.56 | +0.021 |

Stops remain the hole OOS (n=130, **−164R**). Time-stop ~flat; trail/target carry wins — same anatomy as IS and the live 21.

IS had painted h4 as a large negative. OOS paints h4 as **flat**, and on NASDAQ slightly **better** than weekly+3d on R/sm. That is exactly why G2 fails and why a level gate must not ship.

---

## 3. ASX diagnosis (one page)

**Sample:** IS+OOS ASX taken, n=282, totalR **−16.5**.

| Factor | Finding |
|---|---|
| **Cost vs move** | grossR −12.8 · costR +3.7 · cost is **22%** of \|gross\|+\|cost\| mass — material but not the whole loss |
| **Stop overshoot** | 61 stops; **80%** finish &lt; −1.05R (mean stop −1.20R) — gap/pathology, not clean 1R |
| **Liquidity** | thin (ADV&lt;$0.5m): −0.27R/n=18 · mid ~flat · **deep (ADV≥$5m): +0.015R/n=64** |
| **Fund leakage** | **0** residual fund-like names in the ASX taken set |
| **By level (ASX pooled)** | weekly +0.025 (n=97) · 3d −0.053 (n=42) · h4 **−0.117 (n=143)** |

**Conclusion:** ASX is a **mixed artefact**, not pure edgelessness.  
- Level mix and stop overshoot dominate the red.  
- Deep-liquidity ASX is roughly flat-to-slightly positive.  
- Costs matter (22%) but do not alone explain −16R.  
- **Do not suspend ASX solely on IS h4 drag** — OOS ASX weekly is positive; OOS ASX overall still red via h4/stops.  
- **Do not treat ASX as “fixed by dropping h4”** until a redesign addresses stop quality.

*Survivorship caveat applies.*

---

## 4. Capacity under concentration (weekly+3d only)

Even though the level gate is **not** confirmed for shipping, capacity of the G1 set is reported for completeness:

| Book | Eligible | Taken | Fill rate | Peak open | R/sm |
|---|---|---|---|---|---|
| OOS weekly+3d | 293 | 293 | **1.00** | 22 / 30 | +0.021 |
| IS+OOS weekly+3d | 574 | 568 | **0.99** | 30 / 30 | +0.028 |

**Read:** a weekly+3d-only book does **not** starve the 30 slots in this history (peak 22 OOS; full only when IS+OOS pooled). Capacity is not the binding objection — **confirmation failure is**.

---

## 5. Bundled config proposal

### 5a. What is **not** proposed (gates failed)

| Change | Why rejected now |
|---|---|
| `level_tf in {weekly, 3d}` gate | **G2 failed** — NASDAQ h4 not worse OOS |
| V2 early-cut alone | Prior pack: only formal PASS but still net-negative; owner ruling: do not enable alone |
| ASX full suspension | Diagnosis = mixed artefact, not proven edgeless; deep ASX ~flat |
| Scale / live capital | Edge not confirmed under live rules |

### 5b. What **is** proposed — redesign cycle (no rule constants to flip)

Because the pre-registered bundle failed, the next cycle is an **entry/exit redesign research cycle**, not a config diff:

1. **Stop quality work (primary):** 80% of ASX stops overshoot −1.05R. Investigate gap handling, max-stop already at 25%, earnings buffer coverage, and whether h4 plans systematically set stops the market runs.  
2. **Liquidity honesty on ASX:** thin band is −0.27R; consider raising ASX `VIVEK_BOT_MIN_ADV` in a *future* sim grid (not shipped now).  
3. **Re-test level split only after stop fix** — G2 may have failed because NASDAQ h4 winners are real, or because noise; do not gate on one OOS draw.  
4. **Keep 28d time-stop** (V1 already failed in IS pack).  
5. **Keep paper 30×$5k**; do not scale.

### 5c. If the owner later forces a *minimal* sim-only shadow bundle (not live)

Only after a written override of G2:

```python
# SHADOW ONLY — not for vivek_bot.py until owner override of G2
VIVEK_BOT_LEVEL_TF_ALLOW = ("weekly", "3d")   # would need new code path
# V2 still off unless separately approved
# ASX still on
```

Success/kill for that shadow (pre-registered **if** override happens):

| Metric | Success (continue) | Kill (revert) |
|---|---|---|
| Next 30 closed under shadow | Exp R > 0 **and** R/sm > 0 | Exp R ≤ 0 after n=30 |
| Stop mean R | > −1.15 | ≤ −1.25 |
| NASDAQ alone | Exp R ≥ 0 | Exp R < −0.05 |

**Default path: do not enable the shadow.** Redesign first.

---

## 6. Counterfactual on the 21 real closes

| Filter | n kept | Total R | vs live −6.40R |
|---|---|---|---|
| Live (all) | 21 | **−6.40** | — |
| Keep weekly+3d only | 7 | **−1.01** | +5.39R saved by dropping 14 names (mostly h4) |
| weekly+3d + V2 approx | 7 | **−1.01** | V2 did not change this tiny set (no extra cut signal in the simplified CF) |

**Dropped symbols (level filter):** WHC, MVF, CCP, PMV, KLS, BGA, TSLA, AMSF, KHC, MDB, BDX, WLD, XLM, WBT.

This is **not** permission to ship the filter — it is what the filter would have done to one small live path. OOS G2 says the filter’s premise is unstable on NASDAQ.

*Survivorship / small-n caveat: n=21.*

---

## 7. Owner checklist (sign before any rule touch)

- [ ] Accept **NOT CONFIRMED** — no `level_tf` gate, no V2 alone, no scale  
- [ ] Accept next work is **stop-quality + ASX liquidity diagnosis**, not a config flip  
- [ ] Paper book continues under **frozen** live rules until a new protocol is signed  
- [ ] Optional: commission a stop-overshoot deep-dive with its own pre-registered gates  

---

## 8. Reproducibility

```bash
# IS sample map (deterministic rebuild of limit=120 sample)
python -c "from scanner.vivek_parity import reconstruct_is_sample; import json; ..."

# OOS run (already committed artefact)
python -m scanner.vivek_backtest --parity --market asx --market nasdaq \
  --limit 240 --period 5y --no-variants \
  --exclude-from public/data/vivek_parity_is_symbols.json \
  --tag parity_oos --out public/data/vivek_backtest_parity_oos.json

# Gates
python -m scripts.parity_oos_analysis
```

Artefacts:  
- `public/data/vivek_backtest_parity.json`  
- `public/data/vivek_backtest_parity_oos.json`  
- `public/data/vivek_parity_is_symbols.json`  
- `public/data/vivek_parity_oos_symbols.json`  
- `public/data/vivek_parity_oos_gates.json`  
- `DECISION-PACK-N30.md` (tables regenerated from IS artefact)

---

## 9. Bottom line

> **G1/G3 say weekly+3d has a positive OOS footprint. G2 says we cannot blame h4 as a stable drag on NASDAQ. Pre-registered confirmation failed. Do not concentrate the book on level_tf. Do not scale. Redesign stops and re-test — that is the next cycle.**

*Survivorship bias applies to every historical cell in this protocol.*
