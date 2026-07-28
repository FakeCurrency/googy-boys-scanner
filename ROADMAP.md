# Vivek 5.0 — Roadmap

*(Repo: `googy-boys-scanner`. Brand/product name everywhere: **Vivek 5.0**.)*

This is an **honest** roadmap, not a feature wishlist. The goal is a
**profitable, maintainable** system, and the ordering principle is unchanged
from day one: **prove the edge before building on top of it.**

Last updated: 2026-07-10 (supersedes the 2026-06-27 version, which predated
the three-lens pivot).

---

## 1. Current state (the honest version)

| Area | Reality |
|------|---------|
| **Edge / profitability** | ❓ **Still unproven — but now honestly instrumented.** The firehose track-record journal (200+ uncapped positions, noise expectancy) was retired 2026-07-09. The ONLY track record is now the bot book: A+ only, 30 open across all markets combined (owner raised it from 10/market on 2026-07-28), one per symbol, 3 per sector, daily loss guards. It has ~23 open / 7 closed — **too early to read. The single most valuable thing right now is letting it accumulate 20–30 closed trades untouched.** |
| Scanners | ✅ **Three lenses live.** VIVEK (200-SMA reaction, W/3D/D plans, A+/A/B+ grades), PhaseMap (sweep→displacement zones, nightly, spec doc is source of truth), Specs (3× volume-spike base breakouts, discovery-only per its own backtest). Multi-lens confluence banners + Discord pings + ALERTS log. |
| Universes | ✅ ASX full (~2,000) · NASDAQ Global Select (~1,430, expanded from 99 on 2026-07-10) · crypto top-100 + pinned extras. |
| Backtests | ✅ Weekly walk-forward (lens_backtest.yml, owns `vivek_backtest.json`, feeds Insights) + monthly long-only evidence file (vivek_backtest.yml). PhaseMap + Specs replays weekly. All still **survivor-biased on yfinance** — see priority 2. |
| Execution bot | 🟡 Paper mode per market via crypto_bot.yml + scan.yml. Bybit client/bracket/reconcile/kill-switch **built and now covered by order-path tests** (submit→fill→reconcile→flatten, 19 tests). Live capital remains double-gated and **not enabled**. |
| Tests / CI | ✅ ~290 tests (Python risk/breaker/journal/pretrade/order-path + PhaseMap + JS risk engine) run on **every push** (test.yml). Dependencies pinned exactly. |
| Data | 🟡 yfinance only: ~15 min delayed, no delisted history. Fine for operating; not fine for *publishable* backtest numbers. |
| Strategy identity | ✅ Resolved: this is a **swing/position system** (the old "scalp on a 30-min cron" incoherence is dead). |
| Site | 🟡 Public. Manual scan/close endpoints now rate-limited, but anyone can read positions. Cloudflare Access pending (owner action). |

---

## 2. Priorities (ordered)

### P1 — Let the bot book prove or kill the edge (patience, not code)
The bot book is the experiment. Don't touch its rules while n < ~30 closed;
every tweak resets the sample. When n ≥ 30, read expectancy by entry type /
level_tf against the weekly backtest and decide: iterate rules, or scale.

### P2 — Data provider decision (OWNER: EODHD ~US$20/mo or Norgate ~A$40/mo)
Unlocks delisted-aware (honest) backtests, better intraday data, and removes
the single-provider risk. Everything numeric on the Insights page carries a
survivorship warning until this happens.

### P3 — Bybit testnet round-trip drill, then staged live
The order path is unit/integration tested against recorded shapes; the last
gap is one supervised end-to-end drill on testnet: place → fill → reconcile →
kill-switch flatten. After that, live with tiny risk (0.1%/trade), crypto
only, for ≥2 weeks in parallel with paper before normal sizing.
Gates stay: `BYBIT_TESTNET=false` **and** live-confirm flag **and**
per-market mode flip in config.py.

### P4 — Site privacy (OWNER: Cloudflare Access)
The journal and book are public reading today. One toggle in the Cloudflare
dashboard puts the whole site behind a login.

### P5 — IBKR for ASX (+ futures) — only after P1 says the edge is real
`ib_insync` + IB Gateway on a VPS. Do not start this before the crypto loop
has proven itself end to end; it doubles the operational surface.

---

## 3. Standing owner actions

- **GBS_SYNC_CODE** GitHub secret (your site sync code) → activates
  watchlist-aware Discord pings (starred names ping at 2-lens). Built
  2026-07-05, still dormant.
- **Data provider** subscription (P2).
- **Cloudflare Access** (P4).

---

## 4. What was deliberately retired

| Thing | When | Why |
|---|---|---|
| Track-record journal (every A+/A, uncapped) | 2026-07-09 | 203 open / 12 closed → headline expectancy was structural noise. Bot book is the only track record. |
| PULSE macro bar (+ its per-scan Yahoo fetches) | 2026-07-03 / 09 | Owner never used it. |
| Pullback / reversal / short / scalp as scheduled scans | 2026-06 | VIVEK-only pipeline; engines remain for Specs + backtests. |
| `core/` parallel engine, firebase relic, Grok build docs | 2026-07-09 | Dead weight. |
| "Scalp bot" identity | 2026-06 | Structurally impossible on cron + delayed data. |

---

## 5. Development invariants (see CLAUDE.md for the full rules)

- Never change PhaseMap detection maths without the owner: the spec doc is
  the source of truth; bump `RULESET_VERSION` on any parameter change.
- Bot rule constants live in `scanner/config.py` and are published to
  `public/data/bot_rules.json` every scan — the dashboard reads them; the
  numbers must never be hardcoded twice.
- Every push runs the test gate. If it's red, nothing ships.
- **Python is the single source of truth** for rules and risk; the JS
  dashboard reads engine state, it never re-implements the numbers.
- **Real capital is the last step, not a milestone to rush.**
