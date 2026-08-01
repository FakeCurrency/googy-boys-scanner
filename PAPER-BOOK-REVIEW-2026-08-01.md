# Paper Book & Decision Quality Review — 2026-08-01

*(Saturday deep work, owner-ordered. Read-only against the book and live
artifacts at `bfa0ed87`, computed Sat 2026-08-01 ~07:15 UTC / 17:15
Melbourne. No recommendations anywhere in this document — facts and
structure only. Sample-size warning up front: 21 closed trades, all one
grade class, is a thin base for any pattern claim; patterns below are
reported as observed, not as edges.)*

---

## 1. Closed cohort — all 21, and what actually separated them

Every close in the book's life was **grade A+ at entry** (the bot takes
nothing else), so entry grade has zero discriminating power within this
sample — the separation lives entirely in *how positions ended*:

| Exit path | n | Total R | Mean R | Wins |
|---|---|---|---|---|
| **Stop hit** | 7 | **−9.05R** | −1.29 | 0/7 |
| **28d time-stop** | 10 | **+1.66R** | +0.17 | 5/10 |
| **Manual close** (BGA, AIA, ADUS, GLBE) | 4 | **+0.98R** | +0.24 | 4/4 |

- **Every dollar of realised loss came through stops, and no stopped name
  ever reached TP1 first.** The seven stops were full-size losses (−1.02
  to −2.10R) at 9–26 days held. The entire positive side of the ledger —
  +2.64R across 14 closes — was harvested by the time-stop rule and by
  owner cuts.
- **The three cut today, with fade measured** (realised vs the position's
  own peak `mfe_r`): AIA +0.13R realised vs +0.34R peak (gave back
  0.21R), ADUS +0.40R vs +0.61R peak (gave back 0.21R), GLBE +0.17R vs
  +0.19R peak (cut essentially at its high-water mark). BGA yesterday:
  +0.28R vs +0.53R peak. All four were past their best when cut — the
  cuts converted fading positions into locked gains.
- **Was the stall mark predictive?** Yes, of *dead money* — not of
  losses. The 17 closes that were stalled (≥14d, no TP1) at close netted
  −2.22R total, mean **−0.13R**: on average a stalled name went nowhere,
  which is the mark doing exactly what it claims. It did NOT predict
  blow-ups (those were the young stops) and it did not preclude wins —
  7 of 17 stalled closes were positive, topped by KHC +1.11R, which the
  time-stop closed within 0.01R of its all-time peak.
- **The pattern separating workers from capital locks, as observed:**
  peak excursion early. Every stalled/time-stopped close that finished
  meaningfully positive had printed **mfe_r ≥ ~0.5** at some point (KHC
  1.12, FWD 0.99, CCP 0.68, ADUS 0.61, BGA 0.53); every capital lock
  never printed mfe_r above ~0.25 (EVT 0.004, PMV 0.04, XLM 0.12, TSLA
  0.00, MDB 0.20, BDX 0.18). In this sample, **a name that never got
  ~half an R onside in its first weeks never became a winner.** n=17;
  observed, not proven.

## 2. Remaining stalled cohort — ADP, AXON, CLAR, RNW (snapshot only)

All four A+ at entry, all NASDAQ, all pre-TP1. The frozen 28-day
time-stop reaches each of them **this coming week** absent any action —
stated as the standing rule's arithmetic, not as advice:

| Name | Held | To 28d time-stop | Unreal R | Peak mfe_r | To TP1 | Stop below mark |
|---|---|---|---|---|---|---|
| ADP | 23d | **5d** | **+0.40R** | 0.61 | +15.4% (+0.67R) | 32.3% |
| AXON | 22d | 6d | −0.26R | **0.00** | +79.3% (+1.95R) | 30.1% |
| CLAR | 22d | 6d | −0.15R | 0.35 | +13.5% (+1.02R) | 11.3% |
| RNW | 22d | 6d | +0.06R | 0.11 | +23.6% (+0.92R) | 27.3% |

Factual read against section 1's pattern: ADP is the one carrying a
≥0.5 peak (0.61, since faded to +0.40 — the same shape ADUS had when
cut); AXON has never traded onside for a single mark (mfe_r 0.00) and
needs +79% to its structural TP1; CLAR and RNW sit in the
never-got-going band (0.35 / 0.11). ADP and AXON are two of the
pre-gate wide-stop legacy rows — their stops sit ~30% below mark, which
is why they carry outsized `risk_usd` relative to the book.

## 3. Capacity & opportunity cost

- **Free slots: 4 of 30** (first free capacity in six sessions;
  cap_streak was 5 when the board flagged it).
- **Visible A+ armed candidates not already held, per Friday's closing
  scans: ASX 97, NASDAQ 76, crypto 2 (BDX, BTC) — 175 total.** None of
  the 175 is blocked by the 3-per-sector cap today. These counts are
  what the deck actually shows now; Monday's scans will re-grade, so
  treat them as indicative breadth, not a Monday shopping list.
- **What the free slots unlock right now, literally:** it is Saturday —
  only crypto scans this weekend, so until Monday's opens the bot's
  entire actionable universe for the 4 free slots is the two crypto A+
  names. The 173 stock candidates become reachable at Monday's first
  scans.
- **"How many were previously blocked by the cap"** cannot be
  reconstructed precisely — `decide()`'s per-scan skip decisions are not
  committed anywhere (honest gap, stated rather than estimated). What
  the artifacts do support: the book sat at 30/30 for five consecutive
  sessions while the deck showed A+ armed counts of this order of
  magnitude every scan, so the cap — not signal scarcity — was the
  binding constraint at every one of those scans.

## 4. Decision-surface effectiveness (observational)

- **What changed:** before yesterday, "what is squatting my slots" lived
  in raw book JSON and ad-hoc session reports; the deck said 30/30 but
  named nobody. The STALLED strip on journal.html now lists the
  engine-flagged names with held-days and flagged-days — and the
  observable sequence was: surface went live, owner reviewed charts,
  three of its members were cut within hours, +0.70R locked and 3 slots
  freed. Whatever the counterfactual, the decision that had been
  available for ~3 weeks happened the day the information surfaced.
  Note an honest definitional detail: the strip renders the *engine's*
  stall mark (`stale_pinged`, which also covers post-TP1 runners the
  28d rule deliberately exempts), while this review's tables use the
  ≥14d-no-TP1 cut; on today's book the two definitions agree on the
  same names.
- **WHAT NEEDS MY EYES** (entry-side attention: multi-lens agreements
  ranked A+-first with chart links) went live into a closed-market
  weekend — its effectiveness is untested by construction until Monday;
  nothing that happened today used it. Zero observations, reported as
  zero.
- **Friction still present, purely observed:** executing a cut still
  means leaving the surface, opening the Actions workflow, and typing
  six fields — including the exit price, which the operator must fetch
  from the book themselves (today's three used each row's last mark;
  the strip shows days, not marks). The two surfaces also live on two
  different pages (journal vs deck), and the Daily Evidence Brief lands
  on a third channel (Discord). Facts about the current workflow, not
  proposals.

## 5. Track-record honesty check

- **Open 26 / closed 21. Cumulative realised: −6.40R. Wins 8/21
  (38%).** Open unrealised: +0.69R. Composition of the realised line:
  −9.05R from 7 stops, +1.66R from 10 time-stops, +0.98R from 4 manual
  closes. (Prior reports said −7.39R over 17 — the last four closes
  added +0.98R; the two lines reconcile exactly.)
- **The three ordered closes are correctly booked**: each carries
  `exit_reason: manual`, an explicit `exit_price` (7.24 / 115.48 /
  39.31 — the last marks at execution), 100% booked, realised R
  +0.1319 / +0.4011 / +0.1693, exit date 2026-08-01, present in the
  canonical per-market files, the combined book, and the public twin.
  `vivek_run --verify` green.
- **The kept four are untouched**: ADP, RNW, AXON, CLAR each
  byte-identical to the snapshot taken before the first dispatch —
  every field, not merely still-open.
- **Book-keeping inconsistencies: none found.** Checked: summary counts
  vs row counts, realised R present on every closed row, no duplicate
  open symbols, exit_price present on every manual close, cross-file
  agreement via the workflows' own verify gate. One schema note that is
  a convention rather than an inconsistency: ladder-closed rows carry
  their prices inside `exits[]` (top-level `exit` stays null) — true of
  all four manual closes and consistent with the schema's design.
- Standing honesty caveats that belong next to any track-record number:
  dollar P&L is not comparable across the 2026-07-28 resize (R is — all
  figures above are R); and the 21-trade sample spans one month of one
  regime. Direct reading of the line as it stands: the book's losses
  have come fast and full-sized through stops, its recoveries slow and
  partial through time-stops and owner cuts, and it has not yet paid
  for its stops.

---

*Next observable events for this review's threads: Monday's ASX open
(first graduation-eligible scans + the 173 stock candidates vs 4 free
slots) and the four time-stop expiries falling Thu–Fri this week.*
