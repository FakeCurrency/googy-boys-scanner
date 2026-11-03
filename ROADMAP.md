# Vivek 5.0 — Roadmap

*(Repo: `googy-boys-scanner`. Brand/product name everywhere: **Vivek 5.0**.)*

This is an **honest** roadmap, not a feature wishlist. The goal is a
**profitable, maintainable** system, and the ordering principle is unchanged
from day one: **prove the edge before building on top of it.**

Last updated: 2026-11-03 (hc4-2 live, NEXT100 under way. Supersedes the
2026-08-07 version, written while cycle w3-1 was still running).

---

## 1. Current state (the honest version)

| Area | Reality |
|------|---------|
| **Edge / profitability** | 🟡 **No live edge shown yet: iterate, do not scale.** The ONLY track record is the bot book (A/A+ longs in four entry cells, $2,500 x 60 open across all markets, one per symbol, 6 per sector per market, daily/weekly loss guards; no hand closes since 2026-10-14). The n=30 read (2026-08-01, [`docs/archive/DECISION-PACK-N30.md`](docs/archive/DECISION-PACK-N30.md)) found the full rule-set negative (parity −0.033R/trade, n=613). Cycle **w3-1** (2026-08-02 → 2026-09-21, the weekly/3-day gate) ended a **KILL** at n=30 (−0.192R/trade). Cycle **hc4-1** (2026-09-21 → 2026-11-02, the four high-conviction cells) ended with **PR-0** (−0.271R/trade at 41 rules closes, line −0.25R), **PR-1** (3D reclaim −0.433R at 21, line −0.30R) and **PR-6** (the High-conviction badge) tripped, 27–28 Oct. Cycle **hc4-2** is live from 2026-11-02 with the owner-approved items 2, 3, 4, 6 and 7 of the decision pack (1 and 5 not). The 3 Nov decision replay on the hc4-2 code: +0.059R/trade over 1,251 trades, 0.0345R per slot-month. Compare R, not dollars (restated rows carry `resized_at`). |
| Scanners | ✅ **Three lenses live.** VIVEK (200-SMA reaction, W/3D/D plans, A+/A/B+ grades), PhaseMap (sweep→displacement zones, nightly, spec doc is source of truth), Specs (3× volume-spike base breakouts, discovery-only per its own backtest). Multi-lens confluence banners + ALERTS log (labelled unproven — no edge found; the Discord alert channel was removed 2026-08-27). Report-only MOMENTUM and IGNITION sit outside every signal path. |
| Universes | ✅ ASX full (~2,000) · NASDAQ Global Select (~1,430, expanded from 99 on 2026-07-10) · crypto top-200 (pegs out) + pinned extras, priced from exchange klines since 2026-09-28. |
| Backtests | ✅ Weekly walk-forward (lens_backtest.yml, owns `vivek_backtest.json`, feeds Insights) + monthly long-only evidence file (vivek_backtest.yml). PhaseMap + Specs replays weekly. `decision_replay.yml` replays the live bot rules for the decision pack (read-only). All still **survivor-biased on yfinance** — see priority 2. |
| Execution bot | 🟡 Paper mode per market via crypto_bot.yml + scan.yml. The Bybit execution path (bracket/reconcile) was **removed 2026-09-17** with the AI BOT page; only the kill switch's flatten clients remain. Live capital is **not enabled**: PAPER ONLY is the owner's ruling. |
| Tests / CI | ✅ pytest + the JS suites + e2e run on **every push** (test.yml); no test reaches the network. Dependencies pinned exactly (`requirements.txt` production, `requirements-dev.txt` tooling). |
| Data | 🟡 yfinance only: ~15 min delayed, no delisted history. Fine for operating; not fine for *publishable* backtest numbers. |
| Strategy identity | ✅ Resolved: this is a **swing/position system** (the old "scalp on a 30-min cron" incoherence is dead). |
| Site | 🟡 Public. Manual scan/close endpoints now rate-limited, but anyone can read positions. Cloudflare Access pending (owner action). |

---

## 2. Priorities (ordered)

### P1 — Let hc4-2 run untouched to its own checkpoints
The discipline has not changed since the first read: **rules frozen for the
whole cycle**, read only at pre-registered checkpoints. w3-1 answered its
question with a KILL; hc4-1 tripped three of its lines, and the owner's
answer to them is hc4-2 (approved Mon 2 Nov; `docs/DECISIONS_2026-10-14.md`,
"Approved, Mon 2 Nov: hc4-2 starts"). hc4-2 now runs to its own frozen
register, PR-9..PR-16, each line read once on the day its n-th hc4-2 rules
close lands (`python scripts/decision_pack.py` prints the verdicts; the
journal's checkpoint strip mirrors it). Mid-cycle rule changes reset the clock
and throw away the only evidence this system produces, so anything
trade-affecting goes to the **hc4-3 candidates** ("Next-cycle candidates" in
the same pack) and lands together at the hc4-2 → hc4-3 boundary. Which trades
get taken is always the owner's call. Mirrored shorts, confluence C1 and
filter stacking were tested and **killed** (`docs/archive/RESEARCH-LEDGER.md`);
none of them gets proposed again.

**Under way: NEXT100 (3 Nov 2026, owner: "Do it all please").** 100 items in
seven stages: 1 lock hc4-2's record · 2 the replay overhaul · 3 evidence
ledgers · 4 deck and chart, phone first · 5 journal, pages and digest · 6 data
and alarms · 7 the hc4-3 decision-pack write-ups with replay results.
Report-only work, integrity checks, docs and alarms ship as they are done;
every trade-affecting item goes to the hc4-3 decision pack, never into hc4-2.

### P2 — Data provider decision (OWNER: EODHD ~US$20/mo or Norgate ~A$40/mo)
Unlocks delisted-aware (honest) backtests, better intraday data, and removes
the single-provider risk. Everything numeric on the Insights page carries a
survivorship warning until this happens.

### P3 — Execution: PAPER ONLY (owner ruling)
The Bybit order path (bracket/reconcile) was removed on 2026-09-17 with the AI
BOT page. `bybit_client.py` / `alpaca_client.py` survive only as the kill
switch's flatten path, and no keys are set. There is no live-trading step on
this roadmap; reopening one is the owner's call, and only after a cycle shows
a real edge.

### P4 — Site privacy (OWNER: Cloudflare Access)
The journal and book are public reading today. One toggle in the Cloudflare
dashboard puts the whole site behind a login.

### P5 — IBKR for ASX (+ futures) — parked with P3
`ib_insync` + IB Gateway on a VPS would double the operational surface.
Nothing here starts while the book is PAPER ONLY, and not before a cycle shows
the edge is real (w3-1 ended a KILL; hc4-1 tripped PR-0).

---

## 3. Standing owner actions

- **Data provider** subscription (P2).
- **Cloudflare Access** (P4).
- **An alert channel** (an SMTP secret) — today the only alarms are GitHub's
  red-run emails and run-page annotations.
- **The decision pack** (`docs/DECISIONS_2026-10-14.md`): hc4-2's frozen
  register (PR-9..PR-16) decides what changes at cycle hc4-3; the hc4-3
  candidates wait for the owner's call at that boundary.
- **yfinance 1.4.1 → 1.7.0** (#84) and **widening Ignition NASDAQ past Global
  Select** are open owner decisions.
- (Orphaned, safe to delete: the old Discord alert webhook secret,
  `TICK_SECRET`, `GBS_SYNC_CODE`.)

---

## 4. What was deliberately retired

| Thing | When | Why |
|---|---|---|
| Track-record journal (every A+/A, uncapped) | 2026-07-09 | 203 open / 12 closed → headline expectancy was structural noise. Bot book is the only track record. |
| PULSE macro bar (+ its per-scan Yahoo fetches) | 2026-07-03 / 09 | Owner never used it. |
| Pullback / reversal / short / scalp as scheduled scans | 2026-06 | VIVEK-only pipeline; engines remain for Specs + backtests. |
| `core/` parallel engine, firebase relic, Grok build docs | 2026-07-09 | Dead weight. |
| "Scalp bot" identity | 2026-06 | Structurally impossible on cron + delayed data. |
| Discord ALERT router · AI BOT page + Bybit execution · TURTLE · HORIZON + REGIME · Reversals/Fib engine · RECS page | 2026-08-27 → 2026-10-20 | Owner calls; CLAUDE.md "Removed features stay removed" lists each, with write-ups in `docs/claude-history.md`. |

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
