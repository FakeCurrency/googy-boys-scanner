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
| **Edge / profitability** | 🟡 **Read once, and the answer was "iterate, do not scale."** The firehose journal was retired 2026-07-09; the ONLY track record is the bot book (A/A+ four-cell longs since 2026-09-21; 60 open x $2,500 across all markets from the sizing-change merge, approved 2026-09-27 — was 30 x $5,000; one per symbol, 6 per sector per market; daily loss guards). It reached n=30 and was read on 2026-08-01 — see [`docs/archive/DECISION-PACK-N30.md`](docs/archive/DECISION-PACK-N30.md). The full live rule-set is **negative** (parity −0.033R/trade, n=613). One cohort survived three disjoint samples: **weekly + 3-day, +0.056R/trade**, and that cohort (the weekly/3-day level gate, still in force) was tested forward as cycle **w3-1** until 2026-09-21, when the bot moved to the four high-conviction cells; new rows carry cycle **hc4-1** (split any hc4-1 read at the 60 x $2,500 capacity change — the merge / resize commit; restated rows carry `resized_at`). |
| Scanners | ✅ **Three lenses live.** VIVEK (200-SMA reaction, W/3D/D plans, A+/A/B+ grades), PhaseMap (sweep→displacement zones, nightly, spec doc is source of truth), Specs (3× volume-spike base breakouts, discovery-only per its own backtest). Multi-lens confluence banners + ALERTS log (labelled unproven — no edge found; the Discord alert channel was removed 2026-08-27). Report-only MOMENTUM and IGNITION sit outside every signal path. |
| Universes | ✅ ASX full (~2,000) · NASDAQ Global Select (~1,430, expanded from 99 on 2026-07-10) · crypto top-200 (pegs out) + pinned extras, priced from exchange klines since 2026-09-28. |
| Backtests | ✅ Weekly walk-forward (lens_backtest.yml, owns `vivek_backtest.json`, feeds Insights) + monthly long-only evidence file (vivek_backtest.yml). PhaseMap + Specs replays weekly. All still **survivor-biased on yfinance** — see priority 2. |
| Execution bot | 🟡 Paper mode per market via crypto_bot.yml + scan.yml. The Bybit execution path (bracket/reconcile) was **removed 2026-09-17** with the AI BOT page; only the kill switch's flatten clients remain. Live capital is **not enabled**. |
| Tests / CI | ✅ pytest + the JS suites + e2e run on **every push** (test.yml); no test reaches the network. Dependencies pinned exactly (`requirements.txt` production, `requirements-dev.txt` tooling). |
| Data | 🟡 yfinance only: ~15 min delayed, no delisted history. Fine for operating; not fine for *publishable* backtest numbers. |
| Strategy identity | ✅ Resolved: this is a **swing/position system** (the old "scalp on a 30-min cron" incoherence is dead). |
| Site | 🟡 Public. Manual scan/close endpoints now rate-limited, but anyone can read positions. Cloudflare Access pending (owner action). |

---

## 2. Priorities (ordered)

### P1 — ✅ ANSWERED 2026-08-01, and re-opened as cycle w3-1
The first read is done. `docs/archive/DECISION-PACK-N30.md`: **do not scale, iterate.** The
exact live rule-set is negative over history (−0.033R/trade, −0.019 R/slot-month,
n=613 parity trades) and the live book agreed in shape (21 closed, −6.40R, 38%
win). Mirrored shorts, confluence C1 and filter stacking were all tested and
**killed** — `docs/archive/RESEARCH-LEDGER.md` has the numbers so none of them get proposed
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

- **Data provider** subscription (P2).
- **Cloudflare Access** (P4).
- **An alert channel** (an SMTP secret) — today the only alarms are GitHub's
  red-run emails and run-page annotations.
- **The decision pack** (`docs/DECISIONS_2026-10-14.md`): its pre-registered
  checkpoints decide what changes at cycle hc4-2.
- (`GBS_SYNC_CODE` is orphaned since the watchlist went, 2026-09-21; safe to
  delete.)

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
