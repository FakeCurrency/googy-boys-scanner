# Vivek's Beta Scanner — Roadmap

*(Repo: `googy-boys-scanner`. Brand/product name: **Vivek's Beta Scanner**.)*

This is an **honest** roadmap. It is deliberately not a feature wishlist. The goal
is a **profitable, maintainable** system — and right now we cannot claim either.
Everything below is ordered around proving an edge first and not building more on
top of an unproven base.

Last updated: 2026-06-27.

---

## 1. Current state (the honest version)

| Area | Reality |
|------|---------|
| **Edge / profitability** | ❌ **Unproven and currently negative.** Recent testnet/paper scalp expectancy ≈ **−0.37R**, win rate ~27% (small sample). The system does not yet demonstrate it makes money. |
| Scanner | ✅ Live. Hourly multi-market scans (ASX / NASDAQ / crypto), engines for pullback, reversal, spec, short, scalp, googy. Solid and well-tested. |
| Paper journals | ✅ Working (swing + scalp), with pessimistic fills, correlation caps, AEST reset. |
| Execution bot (Python, `scanner/broker/`) | 🟡 Running on **Bybit testnet** (`broker_mode: TESTNET`), deployment **Stage 1**, 0 open positions. 12-check pre-trade gate, circuit breakers, kill switch, reconcile all present. Real capital is double-gated (`BYBIT_TESTNET=false` **and** `BYBIT_LIVE_CONFIRMED=true`) and **not enabled**. |
| Dashboard bot (JS, `bot.html` + `risk_manager.js`) | 🟡 Separate engine enforcing the same rules + a Portfolio Intelligence layer. **Paper/visual only — does not place orders.** |
| Tests | 🟡 155 passing (risk, breakers, journal P&L, pre-trade gate, sizing, data quality). **But the real order path is untested.** |
| Data | 🟡 Scanner relies **entirely on yfinance** (~15 min delayed, flaky). Live prices now have a Binance/Yahoo fallback; *decision* data does not. |
| Strategy identity | ❌ **Misaligned.** Marketed as a "scalp" bot but runs on GitHub-Actions cron (best-effort, can be late/skipped) with delayed data. You cannot scalp on this stack. |

**One-line summary:** the *plumbing* is in good shape; the *edge* is not, and the
*identity* (scalp vs swing) is incoherent. We fix those before anything else.

---

## 2. Top problems (prioritized)

| # | Severity | Problem |
|---|----------|---------|
| **P0** | 🔴 Critical | **No proven edge** — current expectancy is negative. Adding features to a −EV system is wasted effort. |
| **P1** | 🔴 Critical | **No defined target strategy.** We want to mirror trader **"5.0"** (X / YouTube / Discord trade log), but 5.0's setups are not yet codified into concrete, testable rules. |
| **P2** | 🟠 High | **Identity mismatch.** "Scalp" framing + hourly cron + delayed data are structurally incompatible. Must pick a lane: real-time scalper (VPS + websocket) **or** swing/position system mirroring 5.0. |
| **P3** | 🟠 High | **Two rule engines** (Python executor + JS dashboard) with duplicated, drifting logic. The dashboard is *more* sophisticated than the thing actually trading. |
| **P4** | 🟡 Medium | **Order path untested.** `bybit_bracket.submit` + `reconcile` have no integration tests / recorded fixtures. |
| **P5** | 🟡 Medium | **Journal not persisted server-side.** Dashboard journal is ephemeral; `setPersistHook` is a stub. |
| **P6** | 🟡 Medium | **Single data vendor (yfinance).** Fragile and delayed; one outage blinds the scanner. |

---

## 3. Guiding principles (read before adding anything)

1. **No new features until P0 is answered.** If it doesn't help prove or improve the edge, it waits.
2. **Python is the single source of truth** for rules and risk. The JS dashboard *reads* engine state; it never re-implements it.
3. **Every phase has an exit gate.** We do not advance until the gate passes. A failed gate is allowed to send us *backward* or *kill the approach* — that's the point.
4. **Measure honestly.** Expectancy, win rate, R-distribution, and slippage are reported on every run. No vanity metrics.
5. **Real capital is the last step, not a milestone to rush.**

---

## 4. Phased plan

Timelines assume part-time, solo effort and are **effort-driven, not date-driven** —
the gates matter, the weeks are guidance.

---

### Phase 0 — Freeze & Instrument · *~1 week*

Stop digging. Make the system measurable before judging it.

**Goals**
- Freeze net-new features (bug fixes + this roadmap's work only).
- Build a single **edge report**: expectancy (R), win rate, avg win / avg loss, R-distribution, profit factor, max drawdown, and slippage vs intended fill — per engine, per regime, per market. (`expectancy.py` / `attribution.py` already cover most of this — consolidate into one honest view.)
- Snapshot the current paper + testnet track record as the **baseline** to beat.

**Exit gate**
- ✅ A one-screen report exists that answers "is any engine positive, and where does it bleed?" with real numbers.

---

### Phase 1 — Define "5.0" & answer *does an edge exist?* · *~3–4 weeks* · **make-or-break**

This is the whole project. Everything else is secondary.

**Goals**
- **Codify 5.0's strategy** from the shared material (X posts, YouTube content, Discord trade log) into **explicit, testable rules**: instruments, timeframe(s), entry trigger, invalidation/stop, target & scale logic, bias filters, risk per trade, and — critically — *when 5.0 does NOT trade*.
- Translate those rules into a scanner engine (new or adapted), kept separate from the existing scalp logic.
- **Backtest honestly** on out-of-sample data with realistic fills/slippage, and compare against:
  - the current scalp engine (the −0.37R baseline), and
  - 5.0's *actual* published results where available (sanity-check that the codified rules reproduce reality).
- Decide per engine: **keep / fix / kill.**

**Success criteria (the gate)**
- ✅ 5.0's approach is written down as concrete rules a stranger could follow.
- ✅ A backtest of those rules shows **positive out-of-sample expectancy** (target: **≥ +0.2R**, profit factor **> 1.3**, over a meaningful sample of **≥ 100 trades**), **OR** there's a clear, documented reason the approach can't be mechanised — in which case we pivot or stop.
- ❌ If nothing clears a positive-expectancy bar, **we do not proceed toward live capital. Full stop.** We iterate here or shelve the bot.

---

### Phase 2 — Pick a lane & unify the engine · *~2–3 weeks* (can overlap Phase 1)

Resolve the identity crisis and the two-engine problem.

**Goals**
- **Decision: scalper vs swing.** Based on what 5.0 actually does and what's realistic on our infrastructure:
  - **Path A — Real-time scalper:** requires an **always-on VPS + websocket feed** (Bybit/Binance) and sub-minute reaction. Higher cost/complexity. Only choose if 5.0 is genuinely intraday *and* Phase 1 proved an intraday edge.
  - **Path B — Swing / position (recommended default):** reframe the product as a **daily/4H swing system that mirrors 5.0**, runs fine on cron + less-delayed data, and stops pretending to scalp. Lower risk, matches current infra.
- **Unify rules into Python** as the single source of truth: pre-trade gate, sizing, TP1→breakeven, bias filter, loss limits, **and** the dashboard's Portfolio Intelligence posture all live in `scanner/broker/`. The JS dashboard becomes a *thin reader* of engine state (served as JSON), not a parallel implementation.

**Success criteria (the gate)**
- ✅ A written decision (Path A or B) with rationale, and README/CLAUDE.md updated so the system is no longer mislabelled.
- ✅ One rules engine. Dashboard and executor produce **identical** decisions for the same input (verified by a shared test fixture).

---

### Phase 3 — Foundations: data + persistence · *~2–3 weeks*

Make the base trustworthy. Worth doing only once the strategy is chosen (Phases 1–2),
so we harden the *right* data path.

**Goals**
- **Second data source** for scanning (e.g. Bybit/Binance candles for crypto; a stock API such as Tiingo / Polygon / Alpha Vantage for ASX/NASDAQ) with automatic failover when yfinance is down or stale. The resilient `functions/api/_prices.js` pattern from the live-data work is the template.
- **Server-side journal persistence.** Wire `setPersistHook` → a Cloudflare Function (or have the Python side own the canonical journal) so closed paper/live trades are durable and the dashboard reflects them across devices and reloads.

**Success criteria (the gate)**
- ✅ Scanner completes a full run with yfinance forced offline (failover proven).
- ✅ A trade closed in the dashboard survives a reload and appears in the server-side journal.

---

### Phase 4 — Trust the order path · *~1–2 weeks*

Before we risk even testnet *conclusions* on it, prove the execution code is correct.

**Goals**
- **Integration tests for the real order path** using recorded Bybit responses (fixtures): `bybit_bracket.submit` (entry + linked SL/TP), partial fills, rejects, and `reconcile` syncing fills / closed-PnL back into the journal.
- Add a **divergence alert**: if the broker's open positions and the journal disagree beyond what reconcile fixes, fire an alert.

**Success criteria (the gate)**
- ✅ Order-submit and reconcile paths are covered by tests against realistic fixtures (including a reject and a partial fill).
- ✅ A deliberately induced journal/broker mismatch triggers the divergence alert.

---

### Phase 5 — Forward-test the chosen strategy on testnet · *≥4 weeks of live testnet*

Backtests lie; forward results don't. Run the Phase-1-validated strategy on testnet
with the unified engine.

**Goals**
- Run continuously on testnet with the chosen strategy + unified engine.
- Track forward expectancy vs the backtest, and **fill quality** (actual vs intended price) — the gap between backtest and reality is usually slippage and timing.

**Success criteria (the gate)**
- ✅ **≥ 4 weeks** and **≥ 30 trades** on testnet.
- ✅ Forward expectancy **positive** and **within a reasonable band of the backtest** (retains, say, ≥ 60% of the backtested edge — not a collapse).
- ✅ Reconcile loop is clean: every testnet fill is accounted for in the journal.
- ❌ If forward results go negative or diverge wildly from backtest, **back to Phase 1** — the edge wasn't real.

---

### Phase 6 — Gradual live capital · *only after every gate above passes*

The reward for proving the system — approached slowly.

**Goals**
- Enable real capital at the **smallest meaningful size** (existing Stage 1 → Stage 4 framework in `scanner/broker/scaling_advisor.py`).
- Advance size **only** on each stage's documented exit criteria (profitable-weeks streak, drawdown limits).
- Keep testnet running in parallel as a control.

**Success criteria (per stage)**
- ✅ The stage's profitability + drawdown criteria are met before increasing capital.
- 🔒 **Hard rule:** API keys are **trade-only — Withdrawal permission is never granted.** Kill switch and daily-loss breaker verified live before each size increase.

---

## 5. Explicitly out of scope (for now)

Real ideas, but **distractions until the edge is proven**. Parked:

- IBKR integration (ASX + commodity futures).
- More scanner engines / new tabs / more chart timeframes.
- Further UI polish beyond what's shipped.
- Multi-account / multi-strategy orchestration.
- Real-time WS streaming **unless** Phase 2 chooses Path A.

---

## 6. The one number that matters

Until **forward-tested expectancy is reliably positive**, this is an interesting
research project, not a trading system. Every decision should be judged against:
*does this get us closer to a proven, positive edge — or is it just more code?*

---

*Supersedes the previous feature-phase roadmap (2026-06-22), which assumed an edge
that has not been demonstrated.*
