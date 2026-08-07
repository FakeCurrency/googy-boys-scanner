# Vivek 5.0 — Roadmap

*(Repo: `googy-boys-scanner`. Brand/product name everywhere: **Vivek 5.0**.)*

This is an **honest** roadmap, not a feature wishlist. The goal is a
**profitable, maintainable** system, and the ordering principle is unchanged
from day one: **prove the edge before building on top of it.**

Last updated: 2026-08-07 (P1 answered — see below. Supersedes the 2026-07-10
version, which was written before the bot book had any closes to read).

---

## 1. Current state (the honest version)

| Area | Reality |
|------|---------|
| **Edge / profitability** | 🟡 **Read once, and the answer was "iterate, do not scale."** The firehose journal was retired 2026-07-09; the ONLY track record is the bot book (A+ only, 30 open across all markets, one per symbol, 3 per sector, daily loss guards). It reached n=30 and was read on 2026-08-01 — see [`DECISION-PACK-N30.md`](DECISION-PACK-N30.md). The full live rule-set is **negative** (parity −0.033R/trade, n=613). One cohort survived three disjoint samples: **weekly + 3-day, +0.056R/trade**, and that is what cycle **w3-1** is now testing forward, pre-registered, 30 closes, rules frozen. |
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

### P1 — ✅ ANSWERED 2026-08-01, and re-opened as cycle w3-1
The first read is done. `DECISION-PACK-N30.md`: **do not scale, iterate.** The
exact live rule-set is negative over history (−0.033R/trade, −0.019 R/slot-month,
n=613 parity trades) and the live book agreed in shape (21 closed, −6.40R, 38%
win). Mirrored shorts, confluence C1 and filter stacking were all tested and
**killed** — `RESEARCH-LEDGER.md` has the numbers so none of them get proposed
again.

What survived three disjoint samples is the **weekly + 3-day** cohort
(+0.056R/trade pooled, holds at 2× costs). The w3-only level gate was enabled
with owner sign-off on 2026-08-02, opening pre-registered cycle **w3-1**: 30
closes, band pess +0.056 / mid +0.10 R/trade, **rules frozen for the duration**.

So P1 is now the same discipline as before, pointed at a narrower question:
**let w3-1 reach n=30 untouched.** Mid-cycle rule changes reset the clock and
throw away the only evidence this system produces. `scripts/evidence_brief.py`
prints the cycle counter off the entry-time stamp, never inferred from dates.

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

### P5 — IBKR for ASX (+ futures) — only after w3-1 says the edge is real
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
