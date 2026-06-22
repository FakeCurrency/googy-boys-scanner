# Vivek's Beta Scanner — Roadmap

Phases toward a fully autonomous scalp trading bot.

---

## Phase 1 — Foundation ✅ Complete

| Item | Status |
|------|--------|
| Daily scanners: Pullback, Reversal, Spec, Short | ✅ |
| Scalp 1h TTM-Squeeze scanner (crypto + NASDAQ + ASX) | ✅ |
| Paper-trade journal (swing + scalp) | ✅ |
| Pessimistic fill model (next-bar open + slippage + gap detection) | ✅ |
| Correlation group caps (max 2 open per group) | ✅ |
| AEST daily reset (midnight Sydney, DST-aware via `zoneinfo`) | ✅ |
| Kill switch + daily loss circuit breaker | ✅ |
| Cloud stop/target watcher (GitHub Actions) | ✅ |
| Scalp backtest (out-of-sample) | ✅ |
| Email digest alerts | ✅ |

---

## Phase 2 — Live Execution: Crypto via Bybit 🔜 In Progress

| Item | Status |
|------|--------|
| Bybit V5 API client (RSA auth, USDT perpetuals) | ✅ |
| Bracket orders: entry + embedded TP/SL | ✅ |
| Reconciliation: pull fills + closed PnL from Bybit | ✅ |
| ATR/stop-based position sizing (consistent dollar risk per trade) | ✅ |
| Market regime tagging (ADX trending/ranging per trade) | ✅ |
| Structured logging (decisions, qty, PnL, gate reasons) | ✅ |
| Data quality gates (bar count, staleness, NaN checks) | ✅ |
| System health dashboard (scan age, quality-skip count, A+/A count) | ✅ |
| Unit test suite (sizing, grading, fill model, data quality, AEST) | ✅ |
| **Testnet validation: ≥2 weeks, ≥20 trades, confirm reconcile loop** | 🔜 |
| **Live capital enable** (`BYBIT_TESTNET=false` in GitHub Secrets) | 🔜 |

**Next steps for Phase 2:**
1. Watch journal for testnet fills + reconcile cycles — confirm PnL math is correct
2. Check ATR-sized qty makes sense for each crypto (BTC needs tiny qty, SOL needs more)
3. Confirm Bybit doesn't reject orders for min-qty reasons (`BYBIT_MIN_QTY_USD`)
4. Enable live capital once ≥2 weeks of clean testnet execution confirmed

---

## Phase 3 — ASX + Commodity Futures via IBKR 📅 Planned

| Item | Status |
|------|--------|
| IBKR account + IB Gateway on VPS (always-on) | ⬜ |
| `ib_insync` client: connect, place bracket orders, receive fills | ⬜ |
| Symbol mapping: ASX stocks (e.g. `BHP.AX`), CME futures (e.g. `GC1!`) | ⬜ |
| Reconcile IBKR fills into swing journal | ⬜ |
| ASX scalp execution (1h CFD-style via IBKR) | ⬜ |
| Commodity futures execution: Gold (GC), Oil (CL), NatGas (NG) | ⬜ |
| Cross-broker correlation cap (Bybit crypto + IBKR combined exposure) | ⬜ |

---

## Phase 4 — Real-Time Data + Signal Improvement 📅 Planned

| Item | Status |
|------|--------|
| Real-time crypto prices via Bybit WebSocket | ⬜ |
| Real-time NASDAQ/ASX prices via IBKR streaming | ⬜ |
| Replace yfinance 1h bars with live streaming for tighter entry | ⬜ |
| News/economic calendar filter (avoid FOMC, CPI, RBA days) | ⬜ |
| ATR-based trailing stop (tighten SL as trade moves in favour) | ⬜ |
| Performance tracking by market regime (trending vs ranging edge) | 🟡 partial |
| Multi-timeframe confirmation (4h trend + 1h entry) | ⬜ |

---

## Phase 5 — Site Privacy + Multi-User 📅 Future

| Item | Status |
|------|--------|
| Cloudflare Access: password-protect the dashboard | ⬜ |
| KV-backed manual journal sync (already wired, needs CF KV setup) | ⬜ |
| Push alerts: Telegram / Discord webhook on new A+/A signals | ⬜ |

---

## Risk Management Principles

- **Max 5 trades per AEST day** — resets at midnight Sydney time
- **Max $100 USD risk per trade** — ATR/stop-distance sized, not fixed notional
- **Max $500 USD daily loss** — kill switch flattens all positions if breached
- **Max 2 open positions per correlation group** — prevents stacking correlated bets
- **Testnet-first always** — `BYBIT_TESTNET=true` by default; live requires explicit opt-in
- **Reconcile on every run** — journal never drifts from broker state

---

*Last updated: 2026-06-22*
