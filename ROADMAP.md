# Vivek 5.0 — Roadmap

*(Repo: `googy-boys-scanner`. Brand/product name everywhere: **Vivek 5.0**.)*

An honest roadmap, not a feature wishlist. This is a **personal** trading tool:
the owner trades real accounts by hand, and Claude runs the scanner and a paper
book. The ordering principle is unchanged: **prove the edge before building on
top of it.**

Last updated: 2026-09-28.

---

## 1. Current state

| Area | Reality |
|------|---------|
| **Edge** | 🟡 **Being measured.** The bot book is the only track record. Since 2026-09-21 it trades the four high-conviction cells (1W reclaim, 1W break, 3D reclaim, 1D break) at grade A/A+, long only, behind the weekly/3-day level gate — cycle **hc4-1**. The replay behind that rule: +0.212R/trade, n=2,403, PF 1.47. The previous live rule-set was negative over history, which is why the rules changed. hc4-1 has to earn it on its own closes. |
| **Book** | Paper only. 60 open × $2,500 across all markets since the SIZING 2 merge (2026-09-27), one per symbol, 6 per sector per market, daily and weekly loss guards, kill switch half-hourly. Split any hc4-1 read at the resize commit. |
| **Lenses** | ✅ VIVEK (200-SMA reaction), PhaseMap (sweep → displacement zones), Specs (volume-spike base breakouts) feed confluence. MOMENTUM (EMA + RSI divergence) and IGNITION (crypto coil → breakout) are report-only. |
| **Universes** | ✅ ASX full (~2,000) · NASDAQ Global Select (~1,430) · crypto top-200 with pegs and tokenised funds filtered. |
| **Data** | 🟡 Stocks: yfinance (~15 min delayed, no delisted history). Crypto: exchange daily candles (Binance's mirror first, then Coinbase, Yahoo only as a fallback), identity-checked against CoinGecko, since 2026-09-28. |
| **Delivery** | ✅ The site (Cloudflare Pages) and a daily Discord digest of high-conviction plays, ASX after its close and NASDAQ + crypto the next morning. |
| **Backtests** | ✅ Weekly walk-forward (lens_backtest.yml), monthly long-only evidence file (vivek_backtest.yml), PhaseMap/Specs replays, and IGNITION's replay against random timing. Stock results are still survivor-biased (see P2). |
| **Tests / CI** | ✅ pytest and every JS suite on every push (test.yml). Dependencies pinned exactly. |
| **Site** | 🟡 Public to read. The scan and close endpoints are rate-limited and access-logged. Cloudflare Access is still an owner action (P4). |

---

## 2. Priorities (ordered)

### P1 — Let hc4-1 run
The rules changed on 2026-09-21. Every mid-cycle change resets the clock and
throws away the only live evidence the system produces, so the rules stay put
while hc4-1 accumulates closes. `scripts/evidence_brief.py` prints the cycle
counter off the entry-time stamp. `RESEARCH-LEDGER.md` records what has already
been tested and killed (mirrored shorts, confluence C1, filter stacking), so
none of it gets proposed again.

### P2 — Data provider decision (owner: EODHD ~US$20/mo or Norgate ~A$40/mo)
Unlocks delisted-aware backtests for stocks and removes the single-provider
risk. Every stock backtest number carries a survivorship caveat until this
happens.

### P3 — IGNITION forward read (report-only)
The historical replay is borderline: +1.19R/trade over 94 trades, and +1.15R
against random timing with P(no edge) 0.062. The top five trades carry more
than the whole total. The forward bucket started 2026-09-28 and is the only
unseen data. Trading it is the owner's call, and only if the forward bucket
beats random timing on its own.

### P4 — Site privacy (owner: Cloudflare Access)
One toggle in the Cloudflare dashboard puts the whole site behind a login.

---

## 3. Standing owner actions

- **Data provider** subscription (P2).
- **Cloudflare Access** (P4).
- **Delete orphaned secrets** from GitHub and Cloudflare: `DISCORD_WEBHOOK_URL`,
  `TICK_SECRET`, `GBS_SYNC_CODE`. Nothing reads them. The full secrets list
  lives in CLAUDE.md.

---

## 4. What was deliberately retired

| Thing | When | Why |
|---|---|---|
| Track-record journal (every A+/A, uncapped) | 2026-07-09 | 203 open / 12 closed made the headline expectancy structural noise. The bot book is the only track record. |
| PULSE macro bar | 2026-07-03 / 09 | Owner never used it. |
| Pullback / reversal / short / scalp as scheduled scans | 2026-06 | VIVEK-only pipeline; engines remain for Specs and backtests. |
| `core/` parallel engine, firebase relic, Grok build docs | 2026-07-09 | Dead weight. |
| "Scalp bot" identity | 2026-06 | Structurally impossible on cron and delayed data. |
| Discord alert channel | 2026-08-27 | Owner ruling. The morning digest is a separate, sanctioned channel. |
| TURTLE lens | 2026-09-17 | Owner never used it. |
| AI BOT page, Bybit execution path, scalp risk stack | 2026-09-17 | Owner never used it. The kill switch keeps its flatten clients. |
| HORIZON and REGIME | 2026-09-20 | Owner never looked at them. |
| Manual journal, stars, stop watcher | 2026-09-21 | Owner trades real accounts by hand. |
| Cycle w3-1 | 2026-09-21 | Replaced by hc4-1 when the bot moved to the four cells. |
| Live-execution rollout (Bybit testnet drill, IBKR for ASX, futures) | 2026-09-28 | The execution path was removed; the owner places real trades by hand. |
| Paid / Discord business goal | 2026-09-28 | Owner ruling: personal use only. |
| Old planning docs and Windows launchers | 2026-09-28 | Outdated. Git history keeps them. |

---

## 5. Development invariants (CLAUDE.md has the full rules)

- Never change PhaseMap detection maths without the owner: the spec doc is
  the source of truth; bump `RULESET_VERSION` on any parameter change.
- Bot rule constants live in `scanner/config.py` and are published to
  `public/data/bot_rules.json` every scan. The dashboard reads them; the
  numbers are never hardcoded twice.
- Every push runs the test gate. If it's red, nothing ships.
- **Python is the single source of truth** for rules and risk; the JS
  dashboard reads engine state and never re-implements the numbers.
- Trade-affecting changes are the owner's call.
