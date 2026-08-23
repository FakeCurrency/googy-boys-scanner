# Phase 0: Turtle Money Surface Inventory

**Date:** 2026-08-23  
**Branch:** turtle-money-readouts  
**Scope:** Money rows, calculations, and Phase 7+ readout specs

This document is **PHASE 0 INVENTORY ONLY** — no code, no commit. It names every field, every calculated column, and every displayed fact on the Turtle money surface, then specifies the four readout designs (headroom, cap board, pyramid spacing, margin breathing room) that Phase 1+ will implement.

---

## 1. Position Row Fields (Book Data)

A position object `p` in `turtle_book.<market>.json` carries these fields. All are populated by `turtle_run.py` at entry; some change on each scan (last_mark, mark_date, mfe_r, mae_r); none are deleted or renamed after initial write.

### Entry & Identity
- **symbol**: ticker (string, ASCII)
- **market**: "asx" | "nasdaq" | "crypto" | "crypto5x" | "futures"
- **name**: human-readable name (e.g., "Zcash")
- **sector**: sector tag (string, empty if unclassified)
- **side**: "long" | "short"
- **system**: 1 (20-day, S1 filtered) | 2 (55-day failsafe)

### Position Sizing & Pyramid
- **n**: ATR-based stop distance scalar (float, e.g., 39.51)
- **units**: Turtle pyramid count (1–4, integer; cumulative fills count)
- **fills**: array of fill prices (length = units; e.g., [787.81, 812.5, 837.72, 900])
- **cost_basis**: sum of (fill price × qty), total notional at entry (float, e.g., 996.95)
- **last_fill**: price of the most recent pyramid add (float, e.g., 787.81)

### Stops & Levels
- **stop**: stop price, raised on each add but NOT to breakeven (float, e.g., 708.79)
  - Computed as: breakout - (units[1] - 1 + 0.5) × N = first level minus trailing 0.5N per add
  - Formula: "one shared stop, 0.5N under the most recent unit"
  - NOT trailed to breakeven on this page; trailed in the live account, but book stops show the engine's stop

### Timing & Valuation
- **opened**: date string (YYYY-MM-DD, e.g., "2026-08-22")
- **last_mark**: current price (float, e.g., 837.72)
- **mark_date**: date string of last_mark (e.g., "2026-08-22")
- **fees**: cumulative trading fees charged on fills (float, e.g., 1.50)

### Performance (Snapshot & Realized)
- **mfe_r**: max favorable excursion, in risk units (float, e.g., 0.8091 = 0.8091R gain)
- **mae_r**: max adverse excursion, in risk units (float, e.g., -0.6953 = -0.6953R loss)
- **posted**: margin posted for this position (levered sleeves only; float, e.g., 199.39)
  - Formula: notional / leverage = (cost_basis × current price weight) / leverage
  - Isolated margin: cannot lose more than posted
- **unpriced_runs**: count of scans where last_mark was unavailable (int; used for stale detection)

### For Closed Rows (in book.closed)
- **reason**: "stop" | "liquidation" | "manual" | (TBD: other exit types)
- **exit_date**: date of close (YYYY-MM-DD)
- **pnl**: realized P&L in dollars (float, signed: negative = loss, positive = gain)
- **r**: realized R (risk-adjusted return; float, signed)
- Plus all open fields except unpriced_runs

---

## 2. Calculated / Derived Columns (Shown on Money Table)

Every column below is computed in turtle.js on the fly from book fields. Never re-typed or stored; computed once per render.

### Open Positions Table — Cash Sleeve
| Column | Field Source | Formula | Example | Used For |
|--------|--------------|---------|---------|----------|
| **Symbol** | p.symbol | — | ZEC | row ID |
| **Market** | p.market | .toUpperCase() | CRYPTO5X | sleeve ID |
| **Side** | p.side | esc() | long | direction |
| **Units** | p.units | integer 1–4 | 1 | pyramid count |
| **Qty** | p.units | (u < 10) ? num(u,4) : num(u,2) | 1.2655 | actual share/coin count |
| **Avg fill** | p.cost_basis / p.units | num(avg, 4) | 787.8100 | entry price |
| **Stop** | p.stop | num(p.stop, 4) | 708.7878 | exit trigger level |
| **Next add** | nextAddStr(p) | p.last_fill + sign × P.pyramid_step_n × p.n; max_units check | 787.81 | next pyramid price |
| **Open R** | derived from n, units, last_mark | sign × (last_mark−avg) × units / (P.stop_n × n × units) | +0.81R | unrealized risk units |
| **Since** | p.opened | date string | 2026-08-22 | days held |

### Open Positions Table — Levered Sleeve (5×, futures)
Same as above PLUS:
| Column | Field Source | Formula | Example | Used For |
|--------|--------------|---------|---------|----------|
| **Posted** | p.posted | money(p.posted) or "—" | $199 | margin at risk |
| **Liq dist.** | liqDistanceR(p) | \|last_mark − liq_price\| / (P.stop_n × p.n) | 0.50R | price room to liq |

**liqDistanceR(p) computation:**
```javascript
const avg = p.cost_basis / p.units;
const liq = p.side === "short" ? avg + p.posted / p.units : avg - p.posted / p.units;
return Math.abs(p.last_mark - liq) / (P.stop_n * p.n);
```
- For long: liq = avg − posted/units = price where posted margin runs out
- For short: liq = avg + posted/units = (same logic, opposite direction)
- Distance in units of (P.stop_n × n) — the same units the stop uses

### Closed Positions Table
| Column | Source | Formula | Example | Used For |
|--------|--------|---------|---------|----------|
| **Symbol** | t.symbol | — | ZEC | row ID |
| **Side** | t.side | — | long | direction |
| **Reason** | t.reason | — | stop | exit type |
| **R** | t.r | sgnR(r) with color class | +1.23R | realized risk units |
| **P&L** | t.pnl | money(t.pnl) | $123 | dollar profit/loss |
| **Fees** | t.fees | money(t.fees) | $1.50 | trading cost |
| **Opened** | t.opened | — | 2026-08-22 | entry date |
| **Closed** | t.closed | — | 2026-08-23 | exit date |

---

## 3. By-Market Summary Row (Summary Card)

From `BOOK.by_market[market]` object.

| Column | Field | Example | Calculation | Used For |
|--------|-------|---------|-------------|----------|
| **Market** | key | CRYPTO5X | — | sleeve ID |
| **Vehicle** | params.leverage | 5× margin | if leverage > 1 then leverage × margin; else cash | sleeve type |
| **Equity** | equity | $5,000 | initial_equity (if first run) or prior summary | account size |
| **Open** | open_positions | 4 | count of rows in .open[] | position count |
| **Closed** | closed | 1 | count of rows in .closed[] | history count |
| **Total R** | total_r | +1.23R | sum of all realized R on closed + current unrealized | book performance |

**For levered sleeves, also show:**
| Additional | Field | Example | Used For |
|---|---|---|---|
| Posted margin | posted_margin | $649 | capital at risk across all positions |
| Free margin | free_margin | $4,351 | remaining margin available for new positions |

---

## 4. Skip Rows (Not Taken, And Why)

From `BOOK.skips[]` array. Each skip is a declined signal with a reason.

### Skip Row Fields
- **symbol**: ticker
- **market**: "asx" | "nasdaq" | "crypto" | "crypto5x" | "futures"
- **reason**: one of the skip reasons below
- **as_of**: date/time bar closed (used to group cash skips by bar)
- **units_on_book**: pyramid count already held on this symbol (if known)
- **cap**: the ceiling that is binding (if known)
- **want_notional**: cash that would have been needed for this unit (cash skips only)

### Skip Reasons & Meanings

| Reason | Meaning | Impact |
|--------|---------|--------|
| **cash** | cash available < notional needed for one unit | cash sleeve refused; revise down or wait |
| **no_margin** | free margin < posted margin needed | levered sleeve refused; close a position or reduce leverage |
| **direction_cap** | one-way ceiling (12 units) would be exceeded | no more one-way exposure |
| **close_corr_cap** | correlated-group ceiling (6 units) would be exceeded | no more correlated pairs |
| **loose_corr_cap** | loosely-correlated ceiling (10 units) would be exceeded | broader correlation bound reached |
| **per_market_cap** | per-market ceiling (4 units) would be exceeded | this market is full |
| **unit_lt_one** | one contract is > 1 pyramid unit (futures only) | futures position too large |
| **no_margin_file** | `TURTLE_FUTURES_MARGIN_FILE` missing | futures opens are OFF (deliberate default) |
| **roll_window** | a roll-suspect bar sits in today's 20-bar N window | wait for the window to clear |
| **same_bar_reentry** | exited on this bar; S1 filter blocks re-entry | wait for a new breakout bar |
| **s1_skip_after_win** | System 1 filter: last breakout in this market won | wait for the next breakout |

**Display rule:** Shows why each signal was declined, grouped by reason and by market.

---

## 5. Constants & Parameters (P object, from config.py via bot_rules.json)

These live in `public/data/bot_rules.json.turtle` and are validated against hardcoded constants in turtle.js.

| Constant | Value | Meaning |
|----------|-------|---------|
| **stop_n** | 0.5 | stop is 0.5N below the breakout |
| **pyramid_step_n** | 1.0 | each add is 1N apart |
| **risk_pct** | 0.01 (1%) | risk per unit = risk_pct × equity / (units ÷ N) |
| **max_units** | 4 | pyramid ceiling per position |
| **max_units_close_corr** | 6 | correlated-group ceiling (same sector, close-moving) |
| **max_units_loose_corr** | 10 | loosely-correlated ceiling (same sector, broader) |
| **max_units_direction** | 12 | one-way ceiling (long or short, any market) |
| **cost_bps** | 15 | trading cost in basis points per side (published as 15 bps = 0.15%) |
| **leverage_5x** | 5 | posted margin = notional / 5 |

---

## 6. Phase 2–3 Additions (Already Shipped)

From the earlier work, the money surface now includes:

### **Sleeve Strip** (top of SIGNALS view)
Shows per-sleeve state: open units vs cap, equity, total R. Located in `#tt-body` before the posible tables.

### **Days Column** (open positions table)
Days held, computed as: `Math.max(1, Math.round((generated_at − opened) / 864e5))`
- generated_at: scan timestamp from book.generated_at
- opened: entry date from position.opened
- Displayed as "Since" on the table (the date itself) — but the math is available for phase 7 to use

### **Posted & Liq Distance Columns** (levered rows only)
- Posted: p.posted in dollars
- Liq dist: liqDistanceR(p) in R units, showing price room to liquidation

### **Honesty Banners** (levered sleeves, futures)
- Levered sleeve: < 30 closes: "this sleeve is new, not yet a track record"
- Futures: 0/0 case: "futures opens are OFF (no margin data)"

---

## 7. Phase 7+ Readout Specifications

Four new money surfaces to implement, one per phase. Each is **read-only display of existing calculations**, not a new model.

### **Phase 1: Headroom Readout**

**Purpose:** Show how much adverse move each position can absorb before hitting stop or liq.

**Data source:**
- Cash sleeve: compare cost_basis × price move to (equity − sum(open_notional))
- Levered sleeve: compare posted_margin to adverse_move_in_dollars

**Display location:** Separate card in BOOK view, titled "Headroom to breach"

**Rows:**
- Per position: symbol, market, current distance to stop (in %), current distance to liq (in %), days to expiration (stock-only, if known)
- Per sleeve: total margin at risk, free margin, % of free margin in use

**Cards/Breakouts:**
- Green: > 20% distance to stop, > 50% distance to liq
- Yellow: 10–20% distance to stop, 25–50% distance to liq
- Red: < 10% distance to stop, < 25% distance to liq

**Phase 1 scope:** Render the grid, compute the percents, color-code the cells.

---

### **Phase 2: Cap Board Readout**

**Purpose:** Show which ceiling is binding (cap vs cash vs margin) and how close.

**Data source:**
- Open book.skips[] by reason
- Open book.open[] by market/symbol/system
- By-market params (leverage, posted_margin, free_margin)

**Display location:** Separate card in BOOK view, titled "Position ceilings"

**Rows:**
- Per market: ceiling names (1-way, correlated, loose, per-market, cash, margin, unit)
- Units on book, cap, % used, which symbol(s) are filling it

**Text callouts:**
- "Correlated-group binding at 6/6 (BTC+ETH)
  → why this add is declined" (one line per binding cap)
- "Cash $X remaining; next unit costs $Y; ${Y−X} more needed"
- "Free margin $M; next unit uses $P; ${P−M} overage"

**Phase 2 scope:** Render the grid, identify which cap is binding (from skip reasons), compute room to cap.

---

### **Phase 3: Pyramid Spacing**

**Purpose:** Show the next-add ladder and margin/cash cost at each rung.

**Data source:**
- Per position: last_fill, n, side, units, cost_basis, p.posted (for levered), P.pyramid_step_n
- Per market params: leverage, free_margin, equity_remaining

**Display location:** Expandable detail grid per position (on hover / click "Next add" cell)

**Rows:**
- Current fill (u1): price, notional, posted_margin (if levered), cash cost
- Next add (u2): price, notional cost, posted cost, cash cost, feasible? (yes/no)
- u3: same
- u4: same, mark as "pyramid complete"

**Phase 3 scope:** Render the ladder for a clicked position, compute costs at each rung, check feasibility.

---

### **Phase 4: Margin Breathing Room**

**Purpose:** Show time-to-liquidation under various adverse-move scenarios (5%, 10%, 20% adverse move).

**Data source:**
- Per position (levered only): posted, units, last_mark, cost_basis, stop
- Per sleeve: free_margin, leverage

**Display location:** Detail grid under "Liq dist" column (on hover)

**Scenarios:**
- "At 5% adverse move: $X left before liq; Y days at current volatility"
- "At 10% adverse move: $X left; Y days"
- "At 20% adverse move: liquidated"

**Phase 4 scope:** Render the scenario table, compute time-to-liq from implied volatility (if available) or use a fixed assumption (e.g., 2% daily move = N days).

---

## 8. Test Assertions (Phase 0 Inventory Validation)

These assertions hold for all four readout phases:

- [ ] Every position field that a phase reads is present on the test fixture (no missing .posted, .n, etc.)
- [ ] Every calculation (avg, liqDistanceR, nextAddStr) is deterministic given the input fields
- [ ] Every derived value (days, posted_margin, free_margin) has a single place where it is computed (no re-derivation)
- [ ] No phase reads journal/turtle_book*.json inside a decision (all reads are for display only)
- [ ] Every skip reason in the book exists in the WHY lookup table
- [ ] Book.by_market[market].params is always present for levered sleeves, absent for cash

---

## 9. Summary: Files & Touchpoints

| File | Phase 0 Reads | Phases 1–4 Read/Write |
|------|---------------|----------------------|
| `journal/turtle_book.*.json` | schema structure, field names | read-only (position, skip, market data) |
| `public/js/turtle.js` | existing calculations (liqDistanceR, nextAddStr) | add four new render functions |
| `public/css/turtle.css` | spacing & color tokens | add classes for readout grids (.tt-headroom, .tt-cap-board, etc.) |
| `test/turtle.test.js` | position row rendering, money calculations | add assertions for four readout calculations |
| `tests/test_turtle.py` | (none — Python doesn't render UI) | (none) |

---

## 10. Handoff to Phase 1

**This Phase 0 inventory is complete and ready for approval.**

On approval:
1. Phase 1 begins: implement **Headroom Readout**
2. Phase 2: implement **Cap Board Readout**
3. Phase 3: implement **Pyramid Spacing**
4. Phase 4: implement **Margin Breathing Room**

Each phase: commit with gate (tests + journal validation), ready to land under standing merge law.

No code written yet. Ready for your review.
