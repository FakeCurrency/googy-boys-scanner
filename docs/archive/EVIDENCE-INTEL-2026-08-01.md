# Evidence Intelligence — 2026-08-01

*(Fast-track observation report. Read-only against live artifacts at
`d2bd7116`; computed 2026-07-31 23:50 UTC / Sat 09:50 Melbourne. Nothing here
feeds the bot. Where the sample is thin — and most of it is 2–3 days old —
that is stated rather than smoothed over.)*

---

## 1. Funnel

History depth: **2 calendar days per market** (ASX 16 scans, NASDAQ 16,
crypto 28). Everything below is a baseline snapshot, not a trend.

| Market | Data coverage | Gross setups / with-data | Floor kills / gross setups | Published | Arriving / floor-kills |
|---|---|---|---|---|---|
| ASX | 100% of ~2,126 | **30.4%** (~647) | **47.5%** (~307) | ~340 | 2.7% (~8.2 names) |
| NASDAQ | 100% of ~1,424 | 25.5% (~363) | 23.9% (~87) | ~276 | 2.0% (~1.8) |
| Crypto | 100% of 91 | 15.0% (~14) | 29.2% (~4) | ~10 | 0.0% (0 ever) |

- **The floor's bite is structural, not moving.** Day-over-day: ASX kills
  46.9% → 47.5% of gross setups (+0.6pp), NASDAQ 24.7% → 23.9% (−0.8pp),
  crypto 30.8% → 29.2%. All inside noise on a 2-day sample. Verdict on
  "tighter or looser": **flat — no evidence of movement either way yet.**
  The structural fact is that the ASX floor removes nearly **half** of
  everything that sets up (micro-cap breadth vs an A$100k floor), roughly
  twice NASDAQ's share.
- **Arriving rate**: ASX steady at ~2.4–2.7% of kills (7–9 names a scan).
  NASDAQ moved 0.6% → 2.0% of kills — but that is one event (LUNG, below),
  not a shift. Crypto has **never produced an arriving name** — a $3M floor
  on a top-~100 universe means anything killed is dust with no path in; the
  zero is structural and expected to persist.
- Setup breadth itself was stable both days on all three markets (ASX gross
  ~647 both days). Nothing in the funnel moved outside single-digit noise.

## 2. Arriving list

All-time population (the file is 3 sessions old): **ASX 21 distinct
symbols across 22 payloads, NASDAQ 4, crypto 0.**

**Signal vs noise, counted.** 8 of the 21 ASX names carry `fund: true` with
Unclassified sectors — ETFs/listed funds (MOGL, DBBF, A300, INIF, IHEB,
IGRO, ULTB, GOVT) whose spike days are creations/distributions, not
discovery. That is **38% of the list = residual noise**, including the
flashiest print (ULTB 18.0× rvol on 0.19× ADV — a fund flow, not a base
breakout). The remaining **13 look like real participation**, and they
cluster:

- **Materials, 5 of 13**: **VKA** (the standout — present in *every* one of
  the file's 3 sessions, 20 appearances, 5.3× rvol, day turnover 2.1× the
  floor on 0.39× ADV), **ELT** (arrived Sat with the biggest dollar day of
  the set: A$547k = 5.5× floor, 6.7× rvol), ZMI (2 days), MGU (2 days),
  AUQ (1 day).
- Financials/REITs: NSC (2 days), FRI (2 days), BFL, CIN, GDF (single-day).
- One-offs: A3D (Industrials, 2 days), VGL (IT, 2 days), FSA.
- **Repeat names**: 14 of 21 have appeared on ≥2 distinct days. The
  non-fund multi-day set — **VKA, ZMI, MGU, ELT, NSC, FRI, A3D, VGL** — is
  the genuine watch population: liquidity arriving on consecutive sessions
  is the pattern that precedes crossing the floor for real.
- **NASDAQ**: LUNG is the only multi-day name and the only real event —
  10.6× rvol, **$7.7M day against a $1M floor** on 0.68× ADV, present both
  days. The other three (WSBCO, CHSCL, BPYPM) are preferred-share tickers,
  single-day — noise.

By construction every name here still has ADV under its floor (0.19–0.82×)
— that is what being floor-killed means. The question the file exists to
answer is which of them are *building* toward it: today the honest answer
is VKA and ELT on the ASX, LUNG on NASDAQ.

## 3. Specs → VIVEK graduation

- **Watch: ASX 22, NASDAQ 0. Graduates: 0 — explicit zero, both markets.**
- Age distribution is degenerate: all 22 entries carry `first_seen
  2026-07-31` (the registry's first two nights fell on the same calendar
  date — 10 from the first run, 12 added by the scheduled nightly). Watch
  prices span A$0.002–A$0.365.
- **Time-to-graduate: no data exists.** Zero events, one day of watch age.
  The first *possible* graduation signal is a watched name appearing in a
  VIVEK payload dated ≥ 2026-08-01; the ASX is closed until Monday, so the
  earliest real observation window opens with Monday's scans. Note the
  Specs (sub-50¢, spike-gated) and arriving (floor-killed, turnover-gated)
  populations do not currently overlap — no symbol is on both lists — so
  the two surfaces are watching genuinely different candidate pools.
- NASDAQ has produced **zero spec results two nights running**, hence an
  empty watch. That is the lens's strict gates on the current tape, reported
  as zero.

## 4. Paper book

**State: 30/30 slots, $150,000/$150,000 notional — at both caps, 5 straight
sessions (ASX cap_streak).** All 30 open rows are `fixed_notional`.

| | n | Open R | Open P&L | Open risk |
|---|---|---|---|---|
| ASX | 13 | **+1.68** | +$702 | $7,866 |
| NASDAQ | 16 | −0.24 | +$239 | $15,283 |
| Crypto | 1 | +0.17 | +$83 | $500 |
| **Total** | 30 | **+1.60** | +$1,025 | $23,649 |

- **Closed (lifetime): 17 trades, −7.39R, 4 wins (23.5%).** By market: ASX
  9 closes −4.84R, NASDAQ 4 closes −1.41R, crypto 4 closes −1.14R. This
  week is better than the lifetime line: **11 closes, +0.65R net** (best
  CCP +0.58, worst WLD −1.02). Delta since yesterday's backup: one close
  (WBT +0.17), one new open (AUB — the freed slot refilled the same day).
- **Stalled cohort (≥14d open, no TP1): 7 positions — ADP, ADUS, AIA,
  AXON, CLAR, GLBE, RNW — all 22–23 days old.** Together: $35,000 notional
  (23% of the book), +0.77R unrealized (they are not losing — they are
  *going nowhere*), and **$8,628 of open risk = 36% of the book's total**,
  concentrated because four of the seven (ADP, AXON, GLBE, RNW) are the
  pre-gate wide-stop legacy rows.
- **What the stall costs, stated precisely:** the cost is not P&L — the
  cohort is +0.77R — it is **capacity**. With the book pinned at 30/30 for
  five sessions, every new A+ either market prints is passed untaken, and
  the seven stalled slots are the standing reason. The non-stalled 23
  positions carry +0.83R, so roughly half the book's open R sits in the 7
  oldest names that have not reached a single target in three weeks.
  (Whether that warrants a time-stop or manual closes is a frozen-rules /
  owner question; this paragraph is the evidence, not a proposal.)

## 5. HORIZON

**Current boards.** ASX: Real Estate 21.0% participation (rank 1, 1 held),
Financials 17.2% (2 held), Consumer Staples 8.8% — the biggest positive
trend mover (+3.5pp vs its 128-day mean). NASDAQ: Communication Services
40.5% (rank 1, **0 held, unheld streak 4 — one session short of the
5-session alert**), Financial Services 38.8%, Consumer Cyclical 36.4%,
Healthcare 36.0%.

**History vs the last five sessions** (128 backfilled sessions per market;
reconstruction re-applies the live board's exclusions):

- **ASX is a one-sector regime**: Real Estate has been rank-1 in **91%**
  of all 128 sessions and top-3 in 100% — the book holds 1 of its 62 names.
  The genuine rotation signals sit below it: **Utilities was top-3 in 50%
  of history and has not appeared in the last five sessions** (the clearest
  faded-in-history rotation on either board), Consumer Discretionary
  27% → 0 (the July run is fully over), and **Consumer Staples 7% of
  history → 3 of the last 5** — the one ASX sector genuinely emerging
  right now, which the last-few-sessions tape alone would undersell.
- **NASDAQ is where the rotation is live**: Financial Services was top-3 in
  **86% of history but only 1 of the last 5 sessions** (its live trend
  chg −8.4pp is the largest decline on the board) — a dominant six-month
  leader visibly fading. Its replacement: **Healthcare, top-3 in only 27%
  of history but 4 of the last 5** (+4.7pp trend). Communication Services
  stays persistent (74% history, 4 of 5) — and is the one leader the book
  holds none of, streak 4.

---

*Sample-size honesty: funnel and arriving surfaces are 2–3 days old;
graduation is 1 day old; only HORIZON (128 backfilled sessions, error bars
per EVIDENCE-SURFACES.md) and the paper book (34 days) support historical
claims. Next meaningful check-in: the Sunday weekly review, and Monday's
ASX open for the first graduation-eligible scans.*
