# LENS-DECISION — Fill truth + confluence (owner one-pager)
**Issued:** 2026-08-01  
**Repo:** `googy-boys-scanner` @ main  
**Inputs (committed, recomputable):**  
- `public/data/vivek_backtest_parity.json` + `vivek_backtest_parity_oos.json` (1,200 taken trades)  
- `public/data/vivek_fill_sensitivity.json`  
- `public/data/vivek_confluence_study.json`  
**Units:** R only. **Caveat on every number:** survivorship bias (today’s universe, yfinance).  
**Ringfence:** `vivek_bot.py` and PhaseMap detection maths untouched. Simulation only.

---

## 0. The decision in one breath

| Question | Measured answer |
|---|---|
| Is the stop hole mostly a **pessimistic fill artefact**? | **Yes, enough to trip the pre-registered bar.** Midpoint − pessimistic = **+0.0418R/trade** (≥ +0.04). Stop redesign is **deprioritised**. |
| Does **PhaseMap alignment** add entry edge? | **No (C1 failed).** Aligned − none gap pooled **+0.0005R** (need ≥ +0.10); IS sign is **negative**. |
| Does **PhaseMap opposition** hurt? | **Yes (C2 passed).** Opposed − none gap pooled **−0.10R**, negative in both IS and OOS. |
| Is there a **tested, shippable edge** in this system today? | **No positive entry filter cleared pre-registered gates.** Paper book stays frozen. Do not scale. |

---

## 1. Fill-model sensitivity (Part 1)

**Method:** Re-manage all 1,200 taken IS+OOS trades from committed entry/TP/stop under three intrabar assumptions. Entry price held fixed; only path fills change.

| Fill model | n | Exp R | Total R | Stop n | Stop total R |
|---|---|---|---|---|---|
| **Pessimistic** (stop before target — live parity default) | 1200 | **−0.001** | −1.6 | 267 | **−340.7** |
| **Midpoint** ((H+L)/2) | 1200 | **+0.041** | +48.6 | 215 | **−272.8** |
| **Optimistic** (target before stop) | 1200 | **+0.009** | +10.9 | 267 | **−326.5** |

| Pre-registered read | Result |
|---|---|
| If midpoint − pessimistic ≥ **+0.04R/trade** → sim overstated the stop problem | **TRIGGERED (+0.0418)** |

**By sample (exp R):**

| | Pessimistic | Midpoint | Δ mid−pess |
|---|---|---|---|
| IS | −0.024 | +0.016 | +0.040 |
| OOS | +0.023 | +0.066 | +0.044 |

**Implication for the prize of “stop redesign”:**  
Under midpoint fills the pooled book is slightly positive and the stop hole shrinks by ~**68R** (~20%), not ~zero. Stops still lose money — but the **headline “−179R stop hole” was inflated by the sim’s stop-first rule**. Commissioning a large stop-redesign programme is **not** the highest-EV next move on this evidence.

*Survivorship caveat. Re-sim entry fixed at artefact fill.*

---

## 2. The confluence question (Part 2)

**Method:** For each taken trade, run the existing PhaseMap engine on history **sliced to entry_date** (no look-ahead).  
**ALIGNED** = same-direction state ∈ `{SWEPT, DISPLACED, RUNNING}` (same active set as `confluence_alert.PM_ACTIVE`).  
**OPPOSED** = active state in the other direction. **NONE** = else. Detection maths not modified.

| Class | n | Exp R | Total R |
|---|---|---|---|
| ALIGNED | 229 | +0.010 | +2.4 |
| OPPOSED | 191 | **−0.091** | **−17.3** |
| NONE | 780 | +0.010 | +7.6 |

### Pre-registered gates

| Gate | Rule | Result |
|---|---|---|
| **C1** | aligned − none ≥ **+0.10R**, n_aligned ≥ 80, **sign > 0 in IS and OOS** | **FAIL** — pooled gap **+0.0005**; n=229 OK; **IS −0.112 / OOS +0.124** (sign flips) |
| **C2** | opposed − none ≤ 0 in IS, OOS, pooled | **PASS** — IS −0.182 · OOS −0.014 · pooled −0.100 |

**Implication:**  
- **Cannot** sell “multi-lens alignment” as a positive entry filter on this test.  
- **Can** say trading *into* an active opposed PhaseMap state is associated with worse outcomes — a possible **veto**, not a reason to enter.  
- Any opposed-veto would need its own pre-registered shadow protocol before live use (not proposed as a ship gate here).

*Survivorship caveat. Engine read-only.*

---

## 3. Three options for the owner

### Option A — Commission stop redesign  
**Prize (quantified):** even under midpoint fills, stops still book **−273R** on 1,200 trades (~−1.27R per stop). Fixing *true* gap/overshoot still has a ceiling on the order of **tens of R**, not the full −340R pessimistic figure.  
**Cost:** high engineering + resets the n-clock if rules change.  
**Recommendation on this pack:** **Deprioritise.** Fill study tripped the “overstated hole” bar. Revisit only after a midpoint-fill (or tick) baseline is the default evidence standard.

### Option B — Pursue confluence as an entry filter  
**Prize if C1 had passed:** +0.10R/trade on ≥80 aligned names.  
**Measured:** C1 **failed**; aligned ≈ none pooled.  
**Opposed veto (C2):** removes 191 trades at −0.09R → about **+17R** on the historical pool if simply dropped (upper bound; ignores replacement fills).  
**Recommendation:** **Do not ship an “aligned-only” entry filter.** Optional later research: **opposed veto only**, with a fresh pre-registered shadow (success = next 30 closed expR improvement ≥ +0.05 without killing fill rate). Not enabled now.

### Option C — Accept that no tested edge exists in this system  
**What cleared gates across the full programme?**  
- Live rules: negative IS, mixed OOS — **do not scale** (prior packs).  
- Level_tf split: **not confirmed** (G2 failed).  
- V2 alone: tiny PASS, still net-negative — owner: do not enable alone.  
- Fill truth: stop story was partly sim.  
- Confluence long: **not confirmed**.  

**Recommendation:** **Default.** Keep the **30 × $5k paper book under frozen rules**. Treat the product as an **instrumented research platform**, not a proven allocator. Next work is either (i) better fill realism in the evidence stack, or (ii) a *new* entry hypothesis with gates written first — not more polishing of a zero-information long filter.

---

## 4. What the 30 slots should do next month

1. **No scale. No live. No V2. No level_tf gate. No aligned-only filter.**  
2. Paper book continues **frozen**.  
3. Evidence stack default for future stop claims: report **pessimistic and midpoint** side by side.  
4. Optional low-cost shadow (owner must sign a separate protocol first): **veto new entries when PhaseMap is OPPOSED** — not on by default.  
5. Stale `n=614` in the decision pack corrected to **n=613** (artefact truth).

---

## 5. Reproducibility

```bash
python -m scripts.lens_fill_confluence
# → public/data/vivek_fill_sensitivity.json
# → public/data/vivek_confluence_study.json
```

---

## 6. Bottom line

> **The stop hole is partly how we fill bars. PhaseMap alignment is not a proven entry edge; opposition is a mild warning. Nothing in this pack authorises scaling or a rule change. Accept “no tested edge” as the working state, keep the frozen paper book, and only open a new cycle with gates written before the data.**

*Survivorship bias applies to every historical cell.*
