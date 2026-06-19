# Roadmap — path to real capital

Status of the work needed before the Scalp engine could trade real money, plus
the broader backlog. The scanner + paper journals are a **forward test**; nothing
here places real orders yet.

Legend: 🔴 blocker · 🟠 important · 🟡 nice-to-have · ✅ done · 🚧 in progress

---

## High priority — required before real capital

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | **Out-of-sample scalp backtest** with the live pessimistic fill model | ✅ | `scanner/scalp_backtest.py` + weekly `backtest.yml`. Re-evaluates the engine bar-by-bar (no look-ahead); same next-bar-open + slippage + gap-through fills; reports win rate, profit factor, max drawdown, expectancy. **Next:** review the numbers once the first CI run publishes `scalp_backtest.json`, then decide if the edge survives costs. |
| 2 | **Session-boundary daily reset** | ✅ | Daily trade/loss limits reset at a fixed **08:00 UTC** anchor (quiet window between NASDAQ close and ASX open), so they never reset mid-session — even during AEDT when the ASX session straddles 00:00 UTC. |
| 3 | **Portfolio correlation caps** | ✅ | Max 2 open positions per correlation group (metals, energy, materials_au, ags, au_financials, us_tech…). Stops Gold + Silver + GLD + a miner counting as one oversized bet. |
| 4 | **Resting bracket orders at the broker** | 🔴 | Design captured below. Stops currently live in code and are only enforced when a scan runs (~every 30 min). For real money the stop **must rest at the broker** and execute while the system is asleep. Not yet built. |
| 5 | **Walk-forward / out-of-sample split** | 🟠 | The backtest is a single in-sample pass. Before sizing up, split into train/validate windows (or rolling walk-forward) so the grade cut-offs aren't overfit. |

## Medium priority

| # | Item | Status | Notes |
|---|------|--------|-------|
| 6 | Momentum histogram / TTM-squeeze visual on the 1H chart | 🟡 | Chart shows BB/KC bands + EMAs but not the squeeze momentum histogram. |
| 7 | Clearer entry/stop/target labels with % distance on the chart | 🟡 | Lines are drawn but unlabelled with R / % distance. |
| 8 | Scalp-output dedup (same asset, both directions) | ✅ | Highest-scoring direction per **symbol** kept in `scan_scalp` (scanner output) and the journal. Correlated **cross-symbol** exposure handled by #3. |
| 9 | Alert dedup (highest-scoring direction per asset) | 🟡 | `alerts.py` keys by symbol only — can email the same name long *and* short. |
| 10 | SCAN button robustness | 🟡 | Better error handling / status feedback when manually dispatching a scan via the Cloudflare Function. |

## Lower priority

| # | Item | Status | Notes |
|---|------|--------|-------|
| 11 | Combined journal dashboard (overall equity + stats, not just per tab) | 🟡 | |
| 12 | This `ROADMAP.md` | ✅ | |
| 13 | Shorts scanner refinement | 🟡 | Known weak; deferred. |

---

## Broker integration design — resting bracket orders (item #4)

### The problem with today's model

The paper journals "manage" exits by re-checking price each time a scan runs
(~every 30 minutes). That is fine for a forward test but **unsafe for real
money**: a stop hit at 14:11 would not be acted on until the 14:30 scan, and
nothing protects the position if the scanner is down. Live trading needs the
exit orders to **rest at the broker** so they fire on the exchange in real time,
independent of our cron.

### Target order model — OCO bracket

Each entry is submitted as a **bracket** (a.k.a. OCO — one-cancels-other):

```
ENTRY  (limit @ pessimistic price, or market-on-next-bar)
  ├── STOP-LOSS   (stop / stop-limit @ ATR stop)      ─┐ linked:
  └── TAKE-PROFIT (limit @ ATR target)                 ─┘ filling one cancels the other
```

- The stop and target are submitted **with** the entry and live at the broker.
- When either fills, the other is auto-cancelled (OCO), so there's no orphaned
  resting order and no double-fill.
- The daily loss limit and per-group caps are enforced **before** submission
  (pre-trade risk gate) and a separate kill-switch flattens everything if the
  account breaches the daily loss limit.

### Broker requirements / candidates

| Need | Requirement |
|------|-------------|
| Native bracket / OCO orders | So stop+target rest atomically |
| REST + streaming API | REST to submit/cancel; websocket to know fills immediately |
| CFD or margin for 5× leverage | Current model assumes $1k margin → $5k notional |
| Cross-asset (metals, energy, US equities) | Universe spans futures-like + equities |
| Sandbox / paper endpoint | Run live-paper in parallel with the JSON journal to reconcile before real funds |

Candidates: **Alpaca** (US equities + crypto, native brackets, free paper API —
best for a first cut), **Interactive Brokers** (broadest asset coverage incl.
futures/CFD, native brackets, but heavier API), or a CFD provider with an API
(IG / OANDA) for the leveraged commodities legs.

### State machine to build

```
PENDING_ENTRY → OPEN → (PENDING_EXIT) → CLOSED
                  └────────────────────→ CANCELLED
```

- **Idempotency:** every order tagged with a `client_order_id` derived from
  `{symbol}_{direction}_{session_day}` so a retried scan never double-submits.
- **Reconciliation:** on every run, fetch the broker's actual positions/orders
  and treat *that* as truth — the local JSON mirrors it, never leads it.
- **Kill-switch:** a scheduled check (independent of the scanner) that flattens
  all positions and halts new entries if the session loss limit is breached.

### Staged rollout (do not skip steps)

1. ✅ Harden the forward test with pessimistic fills *(done)*.
2. ✅ Build the backtest with the same fills *(done)* — **review the numbers**.
3. 🔴 Wire a **broker paper/sandbox** account; submit real bracket orders against
   it and run it **in parallel** with the JSON journal for ≥1 month. The two
   must agree.
4. 🔴 Add the pre-trade risk gate + kill-switch as broker-enforced, not code-only.
5. 🔴 Go live with **tiny** size; scale only if live results track the paper +
   backtest numbers.
