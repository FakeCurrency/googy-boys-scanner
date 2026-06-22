# Phase 6 — Live Validation & Capital Deployment Protocol
## Code Review Brief for Grok

This document covers everything built or modified during Phase 6 of Vivek's Beta Scanner.
The goal of Phase 6 was to move from pure testnet/simulation toward real capital deployment
with structured safety gates, slippage tracking, and milestone-driven scaling.

---

## High-Level Summary

Phase 6 added five new concerns on top of the Phase 5 risk engine:

1. **Stage tracking** — A `LIVE_DEPLOYMENT_STAGE` config integer (1–4) controls how aggressively
   the system sizes positions. Stage 1/2 use full dynamic sizing; Stage 3 applies an extra 35%
   multiplier cut; Stage 4 is the "graduate to normal parameters" milestone.

2. **Fill slippage analysis** (`scanner/broker/fill_analysis.py`) — Reads `entry_slip_pct`
   recorded by the reconciler, computes weekly and all-time summaries, writes
   `public/data/fill_analysis.json`.

3. **Scaling advisor** (`scanner/broker/scaling_advisor.py`) — Checks milestone conditions for
   each capital-scaling level using profitable-week streak and drawdown, emits a recommendation
   string in the log every run.

4. **`intended_entry_price` traceability field** — Added to every new position dict in
   `bybit_run.py` so slippage can be computed post-fill by the reconciler.

5. **Stage 3 sizing in `bybit_run.py`** — `size_mult` is multiplied by
   `LIVE_STAGE3_POSITION_MULT` (0.35) when `LIVE_DEPLOYMENT_STAGE == 3`.

**New files:**
- `scanner/broker/fill_analysis.py`
- `scanner/broker/scaling_advisor.py`

**Modified files:**
- `scanner/config.py` — new Stage 3/4 constants
- `scanner/broker/bybit_run.py` — Stage 3 sizing, `intended_entry_price`, fill analysis + scaling advisor calls at end of run
- `scanner/broker/performance_report.py` — `write_report()` now calls `write_expectancy()`

---

## File-by-File Breakdown

---

### `scanner/config.py` — Phase 6 additions

```python
LIVE_DEPLOYMENT_STAGE        = 1      # 1=testnet, 2=fill analysis, 3=small live, 4=scaling
LIVE_STAGE3_CAPITAL_MAX_USD  = 8_000  # max live capital at Stage 3
LIVE_STAGE3_POSITION_MULT    = 0.35   # reduce position size to 35% in Stage 3
LIVE_STAGE3_RISK_PCT_MAX     = 0.005  # cap risk per trade at 0.5% of capital at Stage 3
LIVE_STAGE4_L1_MIN_WEEKS     = 4      # profitable weeks needed to unlock Level 1
LIVE_STAGE4_L1_MAX_DD        = 0.05   # max drawdown allowed at Level 1 threshold
LIVE_STAGE4_L1_BUMP          = 0.375  # capital increase at Level 1 (~37.5%)
LIVE_STAGE4_L2_MIN_WEEKS     = 4      # additional weeks needed for Level 2
LIVE_STAGE4_L2_MAX_DD        = 0.06   # max drawdown at Level 2 threshold
LIVE_STAGE4_L2_BUMP          = 0.375  # capital increase at Level 2 (~37.5%)
FILL_ANALYSIS_MIN_TRADES     = 5      # min trades per week to compute avg slippage
```

**Design decision:** `LIVE_STAGE3_RISK_PCT_MAX` is defined in config but is not actively enforced
in the current codebase — only `LIVE_STAGE3_POSITION_MULT` is applied. This is a potential gap.

---

### `scanner/broker/fill_analysis.py` — NEW

**Purpose:** Stage 2 of the deployment protocol — tracks how well bracket orders are filled
relative to the scan signal price.

**Key functions:**

```python
def _iso_week(day: str) -> str:
    # Converts YYYY-MM-DD → "YYYY-WNN"
    # Used for weekly bucketing

def _slip_in_r(slip_pct: float, entry: float, stop: float) -> float | None:
    # Normalises slippage against trade risk distance
    # slip_in_r = entry_slip_pct / (|entry - stop| / entry × 100)
    # Returns None if entry/stop are invalid or zero

def compute_trade_metrics(pos: dict) -> dict | None:
    # Returns None if entry_slip_pct is absent (simulated trades have no fill data)
    # Extracts: symbol, direction, session_day, entry, fill_price,
    #           entry_slip_pct, slip_in_r, pnl, r

def weekly_fill_report(closed: list[dict]) -> list[dict]:
    # Groups filled trades by ISO week
    # Sets avg_slip_pct/avg_slip_r to None and note="insufficient_trades"
    #   if week has fewer than FILL_ANALYSIS_MIN_TRADES (5) trades
    # Returns list sorted most-recent-first

def all_time_summary(closed: list[dict]) -> dict:
    # Computes: filled_trades, avg_slip_pct, avg_slip_r, max_slip_pct,
    #           p50_slip_pct, stdev_slip_pct
    # Uses statistics.median() and statistics.stdev()

def write_fill_analysis(journal: dict) -> dict:
    # Orchestrator: calls weekly_fill_report + all_time_summary
    # Writes public/data/fill_analysis.json via _atomic_write
    # Logs a WARNING if avg_slip_pct > SLIPPAGE_WARN_PCT * 100
    # Returns the report dict
```

**Data source:** `entry_slip_pct` is computed and stored on closed positions by
`bybit_reconcile.py` during position close. `fill_analysis.py` is read-only with respect to
the journal — it never modifies it.

**Design decision:** `skip_daily_count` trades (stop-gapped positions) are excluded from all
fill analysis, consistent with journal conventions.

**Potential review areas:**
- `_slip_in_r()` returns `None` on any zero/invalid input, and callers silently skip it. The
  `stdev_slip_pct` in `all_time_summary` requires `len(slips) > 1` — if only 1 trade, it's
  `None`. This is correct but worth verifying downstream consumers handle `None` gracefully.
- `FILL_ANALYSIS_MIN_TRADES` applies only to `avg_slip_pct`/`avg_slip_r` in weekly rows, but
  `max_slip_pct` and `min_slip_pct` are always populated even for 1-trade weeks. Intentional,
  but could mislead if the frontend shows a "max slippage" for a single-trade week.

---

### `scanner/broker/scaling_advisor.py` — NEW

**Purpose:** Milestone-driven capital scaling advisor. Runs after every bybit_run cycle and logs
a recommendation. Does not change any config or take automated action — advisory only for
Levels 3/4; Levels 1/2 are where the user is expected to manually increase capital.

**Key functions:**

```python
def _iso_week(day: str) -> str:     # same pattern as fill_analysis.py
def _current_iso_week() -> str:     # today's ISO week key

def _weekly_pnl(closed: list[dict]) -> dict[str, float]:
    # Aggregates realised PnL per ISO week
    # Excludes skip_daily_count trades

def profitable_weeks_streak(journal: dict) -> int:
    # Counts consecutive profitable completed weeks from most recent backward
    # ALWAYS excludes the current (incomplete) week
    # Breaks on first week with pnl <= 0

def total_completed_weeks(journal: dict) -> int:
    # Count of distinct past ISO weeks with any trade data
    # Used for time-based milestones (Level 3: ≥13 weeks, Level 4: ≥26 weeks)

def check_stage4_milestones(journal: dict) -> dict:
    # Evaluates all 4 levels:
    #   L1: streak ≥ 4 weeks AND dd < 5%
    #   L2: streak ≥ 8 weeks (cumulative) AND dd < 6%   (requires L1 already met)
    #   L3: total weeks ≥ 13 AND current_level ≥ 2      (time-gated AND perf-gated)
    #   L4: total weeks ≥ 26 AND current_level ≥ 3
    # Returns dict with recommendation string
```

**Key design decision:** Levels 3/4 require `current_level >= 2` and `>= 3` respectively —
they cannot be reached by time alone without first earning performance-based levels. This prevents
gaming by waiting without trading.

**Potential review areas:**
- `profitable_weeks_streak()` uses a simple `sorted(past.keys(), reverse=True)` and iterates
  weeks linearly. A gap (week with no trades) would *not* break the streak because the week
  simply doesn't appear in the dict. This is debatable — a trading gap arguably should reset
  the streak.
- `_iso_week()` is duplicated identically in `fill_analysis.py` and `scaling_advisor.py`.
  Could be extracted to a shared utility, though the duplication is currently minimal.
- `LIVE_STAGE3_RISK_PCT_MAX` is defined in config but `check_stage4_milestones` doesn't
  enforce it — it only computes the streak and drawdown. The Stage 3 risk cap is applied in
  `bybit_run.py` via `LIVE_STAGE3_POSITION_MULT` but the more precise per-trade % cap is unimplemented.

---

### `scanner/broker/bybit_run.py` — Phase 6 modifications

**Changes:**
1. `intended_entry_price` field added to every position dict
2. Stage 3 sizing applied in the signal loop
3. `write_fill_analysis()` called after every run (step 9)
4. `check_stage4_milestones()` called at end of run (step 10)

**Stage 3 sizing (lines 260–264):**
```python
if live_stage == 3:
    s3_mult   = float(getattr(_cfg, "LIVE_STAGE3_POSITION_MULT", 0.35))
    size_mult = size_mult * s3_mult
    log.info("Stage 3 sizing  %s  stage3_mult=%.2f  combined_mult=%.3f",
             symbol, s3_mult, size_mult)
```

`live_stage` is correctly hoisted before the signal loop (line 219):
```python
submitted  = skipped_cap = skipped_asset = skipped_regime = 0
live_stage = int(getattr(_cfg, "LIVE_DEPLOYMENT_STAGE", 1))
log.info("live_deployment_stage=%d", live_stage)
```

**`intended_entry_price` field (line 296):**
```python
"intended_entry_price":  entry,   # Stage 2: preserved for fill-analysis comparison
```

This is the scan-signal entry price at time of submission. The reconciler later computes
`entry_slip_pct = (fill_price - intended_entry) / intended_entry × 100` when the position closes.

**End-of-run steps (lines 388–410):**
```python
# Step 9: Fill analysis
from scanner.broker.fill_analysis import write_fill_analysis
write_fill_analysis(j)

# Step 10: Scaling advisor
from scanner.broker.scaling_advisor import check_stage4_milestones
advice = check_stage4_milestones(j)
```

**Potential review areas:**
- `live_stage` is only used for `== 3` branching. Stages 1, 2, 4 currently produce identical
  sizing behaviour (only the multiplier differs). A reviewer might expect Stage 2 to gate on
  fill analysis results being present, but this is advisory not enforced.
- The `LIVE_STAGE3_RISK_PCT_MAX = 0.005` cap in config is never checked. Only the positional
  multiplier (0.35) is applied. If base risk is high and `size_mult` is already small, the
  effective risk may still exceed 0.5% of capital.

---

## Deep Dives

### Environment Modes

Three operating modes, determined purely by env var presence:

| Mode | Condition | Behaviour |
|------|-----------|-----------|
| SIMULATED | `BYBIT_API_KEY` not set | Positions added to journal with `"broker_status": "SIMULATED"`. No API calls. Reconcile skipped. |
| TESTNET | `BYBIT_API_KEY` set AND `BYBIT_TESTNET=true` (default) | Real API calls to testnet endpoint. Orders and fills are fake. Reconcile runs. |
| LIVE | `BYBIT_API_KEY` set AND `BYBIT_TESTNET=false` AND `BYBIT_LIVE_CONFIRMED=true` | Real capital. Requires two separate deliberate env vars. |

**Safety guard (bybit_run.py:136–145):**
```python
if not bc._testnet() and getattr(_cfg, "REQUIRE_LIVE_CONFIRMED", True):
    confirmed = os.environ.get("BYBIT_LIVE_CONFIRMED", "").lower() == "true"
    if not confirmed:
        log.error("LIVE MODE SAFETY GUARD ...")
        dry_run = True
```

If the guard triggers, the run continues as `dry_run=True` (logging but no submissions) rather
than hard-aborting. This is intentional — the journal is still saved, performance reports still
run, and the operator sees the log warning.

---

### Pre-Trade Check System

The 10-check gate in `scanner/broker/pre_trade_check.py`:

| # | Check | Config key | Failure action |
|---|-------|-----------|----------------|
| 1 | Portfolio heat | `PORTFOLIO_HEAT_LIMIT` = 7% | Block |
| 2 | Max open positions | `MAX_OPEN_POSITIONS` = 10 | Block |
| 3 | Drawdown CB | `MAX_DRAWDOWN_PAUSE` = 12% / `MAX_DRAWDOWN_CLOSE` = 15% | Block |
| 4 | Consecutive losses CB | `CONSEC_LOSS_PAUSE` = 4 | Block |
| 5 | Daily loss cap | `SCALP_MAX_DAILY_LOSS` = $500 | Block |
| 6 | Daily trade cap | `SCALP_MAX_TRADES_PER_DAY` = 5 | Block |
| 7 | Correlation group cap | `MAX_GROUP` = 2 | Block |
| 8 | Sector cap | `SECTOR_EXPOSURE_CAP` = 40% | Block |
| 9 | Order size (fat-finger) | `ORDER_SIZE_MIN_USD` = $10, `ORDER_SIZE_MAX_USD` = $5000 | Block |
| 10 | Slippage tolerance | `SLIPPAGE_WARN_PCT` = 0.3%, `SLIPPAGE_REJECT_PCT` = 1% | Warn / Block |

**`submitted_this_run` parameter:**
The daily cap check must account for orders submitted in the current run that aren't in the
journal yet (journal only updates after the broker confirms). Solved with:
```python
trades_used = len(today_closed) + len(today_open) + submitted_this_run
```

**Potential issue — double-counting:** `bybit_run.py` checks `trades_used >= MAX_DAILY` itself
(line 238) AND `pre_trade_check` checks `daily_cap` (check 6). Both use the same counter logic
but maintain separate state. They should agree, but if the early-exit in `bybit_run.py`
triggers a `break`, `pre_trade_check` is never reached for that iteration — which is fine, but
the redundancy could confuse a reader.

**Potential issue — `today_open` session day filter:**
In `pre_trade_check.py` (line 59):
```python
today_open = [p for p in journal.get("open", []) if p.get("session_day") == sess_day]
```
If a position opened yesterday is still in `open[]` (e.g. overnight hold), it won't count
against today's cap. This is probably intentional (today's cap = today's new trades), but
trades_used could undercount against the portfolio heat check (check 1), which counts ALL open
positions regardless of session day.

---

### Circuit Breakers

Three circuit breakers in `scanner/broker/circuit_breaker.py`, run once via `check_all()`
before the signal loop:

```python
def check_all(journal, last_anomaly_fired=False) -> dict:
    checks["consecutive_losses"] = check_consecutive_losses(journal)
    checks["drawdown"]           = check_drawdown_breaker(journal)
    checks["anomaly"]            = check_anomaly_breaker(last_anomaly_fired)
    # Returns {ok, checks, failed, reason}
```

**Note on comment vs behaviour:** The docstring says "stops short of running drawdown if
consecutive-loss breaker fires", but the implementation runs all three checks unconditionally.
The `check_all` aggregation simply `break`s the run if any check is `ok=False`. The docstring
is inaccurate — all three always run.

**Anomaly breaker design:** `last_anomaly_fired` is a bool passed in from `bybit_run.py`. It's
`True` only for the duration of the current run. Between runs it resets. This means if an anomaly
fires on run N, it blocks run N+1 only if run N+1 also detects the same anomaly. There is no
persistent "paused until manual review" state — just a within-run gate. This is by design but
worth flagging: automated recovery happens naturally on the next clean scan.

---

### Position Sizing Chain

Full sizing chain for a new signal in `bybit_run.py`:

```
1. base_units = calc_qty_risk(entry, stop, SCALP_RISK_PER_TRADE)
   # = SCALP_RISK_PER_TRADE / abs(entry - stop)

2. size_mult = dynamic_size_multiplier(journal, regime)
   # from risk_manager.py:
   #   mult = 1.0
   #   if dd >= DRAWDOWN_HALVE_SIZE_AT (8%): mult *= 0.5
   #   if regime == "ranging":              mult *= REGIME_RANGING_RISK_MULT (0.5)
   #   return max(mult, 0.25)  ← floor at 25%

3. if live_stage == 3:
       size_mult *= LIVE_STAGE3_POSITION_MULT (0.35)
   # Note: floor in step 2 already applied; Stage 3 multiplier can push below 0.25
   # Example: 0.25 * 0.35 = 0.0875 — the floor is NOT re-applied after Stage 3

4. units = base_units * size_mult
5. effective_risk = SCALP_RISK_PER_TRADE * size_mult
```

**Potential bug:** The floor of 0.25 in `dynamic_size_multiplier()` is applied before Stage 3.
So `dynamic_size_multiplier` returns at minimum 0.25, but then `* 0.35` = 0.0875. The
resulting effective risk is 8.75% of `SCALP_RISK_PER_TRADE`. This is probably acceptable (very
small position), but the floor's intent — preventing near-zero orders — is undermined. The
`check_order_size` gate (check 9) will catch truly tiny orders (< $10 notional), but the floor
could be moved or re-applied post-Stage-3.

---

### Fill Slippage Tracking

**Data flow:**

```
bybit_run.py          →  opens position with intended_entry_price = entry (scan price)
bybit_reconcile.py    →  on close: computes entry_slip_pct = (fill_price - intended_entry)
                                             / intended_entry × 100
                          stores entry_slip_pct on the closed position dict
fill_analysis.py      →  reads entry_slip_pct from closed positions
                          computes slip_in_r, weekly/all-time aggregates
                          writes public/data/fill_analysis.json
```

`fill_analysis.py` is purely read-only — it never modifies the journal. This is a good
separation of concerns.

**Positive vs negative slippage:** By convention, positive `entry_slip_pct` means filled at a
worse price (paid more on a long / received less on a short). Negative means a better fill than
expected. The module computes averages including negative values, so a true average over time
reflects whether slippage is systematically adverse.

**`slip_in_r` normalisation:** Divides slippage % by the trade's risk distance %:
```python
risk_dist_pct = abs(entry - stop) / entry * 100
slip_in_r = slip_pct / risk_dist_pct
```
This is a useful normalisation — a 0.1R slippage on a tight stop is much worse than on a wide
stop in absolute terms.

---

## Areas That May Need Review

### 1. `LIVE_STAGE3_RISK_PCT_MAX` is unused
Defined in `config.py` but never enforced. Only the position multiplier is applied.
If the intent is to cap risk at 0.5% of capital per trade, a check should be added in
`bybit_run.py` after computing `effective_risk`:
```python
if live_stage == 3:
    max_risk = account_size() * float(getattr(_cfg, "LIVE_STAGE3_RISK_PCT_MAX", 0.005))
    if effective_risk > max_risk:
        effective_risk = max_risk
        units = effective_risk / abs(entry - stop) if abs(entry - stop) > 0 else 0
```

### 2. Floor bypass in Stage 3 sizing
`dynamic_size_multiplier()` floors at 0.25, but Stage 3 applies an additional 0.35× after
the floor. The combined minimum is 0.0875×, which may produce orders below $10 notional (caught
by the fat-finger gate, but wastes a pre-trade check cycle).

### 3. Gap weeks don't break the profitable-week streak
`profitable_weeks_streak()` only iterates over weeks that have trade data. A week with no trades
is invisible. Whether a trading gap should reset the streak is a product decision.

### 4. Circuit breaker docstring vs behaviour
`check_all()` docstring says "stops short of running drawdown if consecutive-loss breaker fires"
but all three checks always run unconditionally. The docstring should be corrected.

### 5. `_iso_week()` duplication
Identical function in both `fill_analysis.py` and `scaling_advisor.py`. Low risk but a minor
DRY violation.

### 6. `today_open` session-day filter in `pre_trade_check`
Open positions from yesterday (overnight holds) don't count against today's daily cap check,
but DO count against portfolio heat (check 1) and max positions (check 2). This is likely
correct behaviour but the inconsistency could confuse debugging.

### 7. Weekly slippage rows always populate `max_slip_pct` and `min_slip_pct`
Even for weeks with a single trade (where `avg_slip_pct = None`), the max/min are always
computed. A frontend consuming this JSON should not infer statistical significance from these
fields when `note == "insufficient_trades"`.

### 8. Scaling advisor advisory level vs automated enforcement
Levels 1 and 2 are advisory (operator must manually increase capital). There is no automated
enforcement that the operator has actually increased capital before the system keeps treating
it as Stage 3. The `LIVE_DEPLOYMENT_STAGE` config integer must be manually changed — which is
intentional, but creates a divergence between the advisor's `current_level` output and the
actual stage being executed.

---

## Summary

Phase 6 is well-structured, with clean separation of concerns:

- `fill_analysis.py` is read-only relative to the journal — good
- `scaling_advisor.py` is fully advisory with no side effects — good
- `intended_entry_price` adds a minimal audit trail field without changing existing logic — good
- All constants in `config.py` — consistent with project standards

The main concerns for a reviewer to focus on are:
1. The `LIVE_STAGE3_RISK_PCT_MAX` config constant that's defined but never enforced
2. The Stage 3 sizing floor bypass
3. The circuit breaker docstring inaccuracy
4. The advisory-only nature of scaling levels vs actual config update requirement

These are design gaps rather than bugs — the system will not lose money incorrectly due to
them, but they represent incomplete implementation of stated safety features.
