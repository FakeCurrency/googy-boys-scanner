# Decisions for Viv - 14 Oct 2026

REFINE200 found 200 things to fix, and most of them are fixed in this batch.
The 20 below would change which trades the paper bot takes, how big they are, or when
they close, or they touch the PhaseMap spec. Those are yours to decide. This
pack gives each one: what it is, the evidence, the options, Claude's
recommendation, and what would change that recommendation.

On 14 Oct you decided to stop closing positions by hand. That makes the
current cycle, **hc4-1**, the first clean test of the bot's rules on their
own. So the main recommendation is the same throughout: **don't change the
entry rules in the middle of hc4-1**. Each question gets a checkpoint instead,
written down now with exact numbers, so the answer comes from the data and
the line can't be moved after the data arrives.

- **R** is a trade's result divided by what it risked at entry. -1R is a full
  stop-out; +1R made back the amount risked.
- **hc4-1** is the bot's current rule set (since Mon 21 Sep). It takes A and
  A+ longs in four "cells" (1W reclaim, 1W break, 3D reclaim, 1D break). The
  row must be reacting at a weekly or 3-day 200-SMA. Positions are $2,500, up
  to 60 open, with a 28-day time stop.
- **Rules closes** are the bot's own exits: stop, time stop, trail or target.
  **Hand closes** are everything you closed yourself.
- The numbers come from the committed files as of the 14 Oct 18:26 Melbourne
  scan (commit `5e6091d`). Run `python scripts/decision_pack.py` to recompute
  every live-book figure on any later day.

---

## One-screen summary

| # | Decision | Claude's recommendation | Decided by |
|---|---|---|---|
| 1 | Keep trading the ASX? | **Keep.** ASX is clearly worse in only one of five sources. | PR-2 at 15 ASX closes |
| 2 | Drop the 3D-reclaim cell? | **Keep for now.** Drop at hc4-2 if it averages -0.30R or worse at 20 hc4-1 closes. On today's marks that read (~26 Oct) comes in at about -0.44R, so it would trip. | PR-1 (~26 Oct) |
| 3 | Keep taking A grades? | **Keep.** In stocks, A and A+ do the same. | PR-3 |
| 4 | Weekly-level only? | **No change.** The evidence goes both ways. | Replay (PR-4) |
| 7 | Grade rows on the plan the bot will actually trade | **Fix at the next cycle (hc4-2).** Rare: 0 rows on today's scans. | hc4-2 |
| 11 | Sector cap per market or across markets | **Keep per market.** Count it on proper sectors (see 13 / 143). | hc4-2 |
| 12 | Cap of one position per company | **Add at hc4-2.** FWONA + FWONK are one company. | hc4-2 |
| 13 / 143 | Sector names don't match (ASX uses industry groups) | **Map both markets to the 11 GICS sectors at hc4-2.** | hc4-2 |
| 30 | Re-stamp old ASX forward returns | **Don't.** All 10,777 that can be checked are already right. | Closed |
| 42 | Retire Specs | **Retire it** if you don't use the page. Otherwise keep the page and take it out of confluence. | You |
| 43 | PhaseMap A+ does worst | **Show each tier's measured result on the page.** Revisit the grading in the spec. | You (spec) |
| 44 | PhaseMap crypto stats are corrupt | **Move PhaseMap crypto onto the exchange data feed.** | You (spec provider) |
| 47 | Ignition's 3x volume rule adds little | **Keep it.** The forward test decides. | PR-8 |
| 84 | Upgrade yfinance 1.4.1 to 1.7.0 | **Upgrade on a weekend after a dry-run check.** | You |
| 137 / 153 | 1W/3D triggers fire on candles that haven't finished | **No change mid-cycle.** Publish a "candle complete?" flag and let the replay decide. | Replay (PR-5) |
| 145 | Confluence counts B+/WATCH rows | **Keep counting them.** Their results are no worse. | Closed |
| 148 | The "W+H4 confluence" point is checked wrongly | **Fix at hc4-2.** Changes 0 bot trades today. | hc4-2 |
| 152 | Break entries fill above the planned price | **At hc4-2, re-check R:R and TP1 from the actual fill.** | hc4-2 |

Reports (no decision needed, unless you want one):

| # | Report | One line |
|---|---|---|
| 32 | 28-day time stop | +2.55R over 16 exits. It is the rules' only positive exit. Keep it. |
| 33 | Trail and target readout (P12) | 4 trades hit TP1, all came back to breakeven, and the breakeven move saved about 1R on 2 of the 3 we can check. Nothing to tune. |
| 34 | Live drawdowns vs the backtest | The 10-year backtest has no time stop. That one difference explains most of the gap. |
| 35 | Review flags | They mark 53% of the book and don't predict worse R, only bigger dollar swings. |
| 36 | High-conviction 20-session check | First stock results land Tue 20 Oct. Read on 27 Oct. |
| 39 | Breadth (P15) | Closed. The engine was removed and the data that exists can't answer it. |

**The one thing to know.** On today's prices, hc4-1 is on course to fail its
own first checkpoints in the last week of October. The whole cycle would read
-0.25R at 40 closes, right on its line, and 3D reclaim -0.44R at 22 closes,
past its line. The lines were set before that projection was run. See "Where
they are heading" below.

**hc4-2** is the next cycle. Every change you approve lands together at its
start, so hc4-1 stays a clean test to the end. The earliest sensible start is
the PR-0 read, around Tue 27 Oct.

---

## The headline: why the clean sample matters

The whole closed book is **112 closes, -15.16R** (38% won). Split by who
closed them:

| Closed by | Closes | Total R | Avg R | Won |
|---|---|---|---|---|
| The rules (stop, time, trail, target) | 40 | **-21.28R** | -0.53R | 28% |
| You, by hand | 72 | **+6.12R** | +0.09R | 44% |

(PMT stopped out today for -1.11R. Before that, the rules column read 39
closes, -20.17R.)

It looks as though the rules lose and your hand closes win. Neither is proven:

1. **The split picks the losers for the rules column.** Your hand closes
   mostly cut trades early, close to flat. The trades left to the rules are
   the ones you didn't touch, and the rules only close a trade at its stop
   (-1R), at 28 days, or after TP1. So the rules column is full of stop-outs
   by construction, and the hand column is full of scratches.
2. **On the ASX, letting the rules run would not have done worse.** The
   completed-bar archive can replay 24 of your ASX hand closes. Those 24
   finished at **-1.02R** by hand. Left to the rules they would have made
   **+0.24R** (17 time stops, 2 stops, 5 still open at the end of the
   archive). That is a gap of +1.26R over 24 trades, about +0.05R a trade,
   which is within noise. NASDAQ and crypto can't be replayed because the
   archive holds only ASX bars.
3. **By cycle**, the hand closes and the rules closes have been mixed together
   from the start:

| Cycle | Rules closes | Hand closes |
|---|---|---|
| Before the cycles (opened 28 Jun - 1 Aug) | 20, -6.97R | 28, +8.82R |
| w3-1 (opened 3 Aug - 18 Sep) | 14, -8.91R | 44, -2.70R |
| **hc4-1 (opened from 21 Sep)** | **6, -5.40R** | **0** |

**hc4-1 has had no hand closes at all**, and from today it never will. It is
the first sample that measures the rules alone. It has 58 rows: 6 closed by
the rules and 52 still open. The book is full (60 of 60). The 8 w3-1 rows
reach their time stops on Thu 15 and Fri 16 Oct. The 46 open hc4-1 rows that
haven't reached TP1 hit 28 days on these dates:

| Time stop due | Rows | hc4-1 closes by then, if nothing stops out first |
|---|---|---|
| Mon 19 Oct | 5 | 11 |
| Tue 20 Oct | 10 | 21 |
| Mon 26 Oct | 10 | 31 |
| **Tue 27 Oct** | **9** | **40** |
| 28-30 Oct | 7 | 47 |
| 4-11 Nov | 5 | 52 |

So hc4-1 will have about **40 rules closes by Tue 27 Oct**, and more if stops
hit first. That date is when most of the checkpoints below come due.

**One caution about the sample.** Almost every hc4-1 row was opened between 21
Sep and 2 Oct, all in the same market conditions. Forty trades from one
fortnight carry less information than forty trades spread over a year. That
is why each live checkpoint below is paired with the replay.

---

## How the checkpoints work

- **Cohort.** Only hc4-1 rows closed by the rules count. Any row you close by
  hand, any w3-1 row and any older row is left out.
- **Lines.** Each line is set so that a cell that really earns what the
  backtest says (about 0 to +0.1R a trade) would cross it by chance less than
  about 1 time in 20. Live results spread about 0.8R per trade, so after 20
  closes the average is uncertain by roughly +/-0.2R.
- **Replay veto.** If a live line trips but the decision_replay shows the same
  cohort at +0.05R a trade or better (stocks, with the time stop), hold and
  read again at twice the number of closes. One fortnight of live data
  shouldn't overrule ten years on its own, and ten years shouldn't overrule a
  live result that is clearly bad.
- **One boundary.** Approved changes all land together as the next cycle,
  **hc4-2**, with its own cycle tag. Nothing changes row by row in the middle
  of hc4-1. The earliest sensible boundary is the PR-0 read, around 27 Oct.
- **Read once, not every day.** Each checkpoint is read once, on the day its
  n-th close lands, over every rules close up to that day. If that read
  lands between the lines, there is one more read at the second n. A number
  checked every day until it happens to cross a line would make the line
  meaningless.
- **Reading them.** `python scripts/decision_pack.py` prints every checkpoint
  with its current n and average, the day it was read, and NOT DUE, HOLD,
  CLEAR or TRIPPED. Because each read is tied to the day it happened, the
  verdict stays the same whenever the script is run.

### Pre-registration register (frozen 14 Oct 2026)

| ID | Item | Measure | Read when | Line | If it trips |
|---|---|---|---|---|---|
| PR-0 | cycle | avg R of all hc4-1 rules closes | n >= 40 (~27 Oct) | trips at -0.25R or worse; passes at 0.00R or better; in between, read again at n >= 80 | owner review of the whole rule set before anything else changes |
| PR-1 | #2 | avg R of hc4-1 3D-reclaim rules closes | n >= 20 (~26 Oct) | -0.30R or worse; if between -0.30R and 0, second read at n >= 40 with the line at -0.15R | drop 3D reclaim from the entry cells (new entries only) |
| PR-2 | #1 | avg R of hc4-1 ASX rules closes vs NASDAQ over the same days | n >= 15 ASX closes; if it doesn't trip, second read at n >= 30 | ASX at -0.30R or worse AND at least 0.30R below NASDAQ (same line at both reads) | stop new ASX entries; open ASX positions run to their exits |
| PR-3 | #3 | avg R of hc4-1 A vs A+ rules closes, rows opened from 24 Sep | n >= 15 A closes; if it doesn't trip, second read at n >= 30 | A at -0.30R or worse AND at least 0.30R below A+ (same line at both reads) | bot back to A+ only |
| PR-4 | #4 | replay: weekly-level only vs weekly + 3-day | the decision_replay run | weekly-only better by +0.05R/trade or more, in ASX and NASDAQ separately and in both halves of the sample | weekly-level only |
| PR-5 | #137/#153 | replay: 1W/3D triggers on completed vs still-forming candles | the decision_replay run, n >= 200 trades in each group | completed better by +0.10R/trade or more | arm 1W/3D on completed candles only |
| PR-6 | #36 | rosters: High-conviction vs other A+ longs, 20 sessions, first sighting per name, base days from 21 Sep | first read Tue 27 Oct, n >= 40 HC names | HC at least 1.0pp below the others: demote the badge. 1.0pp above: keep. In between: read again Tue 17 Nov | demote the badge to a plain tag (display only) |
| PR-7 | #32 | replay: time stop at 21 / 42 days / off vs 28 | the decision_replay run | an alternative better by +0.03R/trade or more, in ASX and NASDAQ separately | change the time stop |
| PR-8 | #47 | Ignition forward bucket: as-is vs no volume rule | n >= 30 forward trades in a market | the no-volume version does at least as well | drop the 3x volume rule in that market |

**Where they stand today:** PR-0 has 6 of 40 closes (avg -0.90R). PR-1 has 6
of 20 (avg -0.90R). PR-2 has 4 of 15 ASX closes (avg -1.08R). PR-3 has 0 A
closes. All are NOT DUE. The replay and forward checkpoints wait on their
data.

**Where they are heading.** The what-if below assumes every open hc4-1 row
closes at today's price on its time-stop day. It ignores stops and new
entries, so it shows which way each checkpoint is leaning, not the result.
The lines above were set before this what-if was run.

| Checkpoint | Likely read | On today's marks |
|---|---|---|
| PR-0, whole cycle | Tue 27 Oct, 40 closes | **-0.253R: trips** (line -0.25R) |
| PR-1, 3D reclaim | Mon 26 Oct, 22 closes | **-0.438R: trips** (line -0.30R) |
| PR-2, ASX vs NASDAQ | Thu 29 Oct, 15 ASX closes | -0.287R: hold for the second read |
| PR-3, A vs A+ | not before November | 12 A rows in total |

So at the end of October the rules may well fail their own test. The
reason to write the lines down today is that the result then decides,
instead of being explained away afterwards.

---

## #1 - Keep trading the ASX?

**What it is.** The ASX looked weakest in several places. The question is
whether to stop opening new ASX positions, or keep the ASX to a single cell.
24 of the 60 open positions are ASX, 18 of them hc4-1.

**Evidence.** These are hc4-1-style long trades unless noted:

| Source | ASX | NASDAQ | Crypto |
|---|---|---|---|
| 10-year replay, 60 names per market, no time stop | **-0.30R** (n=94) | +0.04R (258) | +0.31R (137) |
| 5-year replay | +0.03R (35) | +0.14R (58) | -0.13R (58) |
| Parity replays: A+ only, w3 rules incl. the time stop (in-sample / out-of-sample / C3) | -0.11 / +0.09 / +0.13 (61 / 78 / 86) | +0.12 / +0.03 / +0.03 (210 / 215 / 258) | - |
| Live, all closes | -0.21R (50) | -0.20R (55) | +0.88R (7) |
| Live, rules closes only | -0.53R (21) | -0.73R (14) | +0.02R (5) |
| hc4-1 so far | 4 closed -4.33R; 18 open +2.80R | 2 closed -1.07R; 34 open -1.53R | - |
| A+ longs, 20-session return (first sighting) | -3.69% (310) | -3.82% (291) | +9.57% (25) |

**What it says.** Only the 10-year replay shows the ASX clearly behind
NASDAQ. In the live book and the rosters, NASDAQ did just as badly over the
same weeks. That points to the market as a whole: A+ longs lost about 3.7% in
20 sessions in both markets. Two of the three parity samples have the ASX
positive. "ASX loses everywhere" doesn't hold up once every source is in one
table. Keeping the ASX to one cell doesn't help either: in the 10-year replay
every ASX cell is negative (3D reclaim -0.35R n=44, 1W reclaim -0.26R n=30,
1D break -0.27R n=16).

**Options.** (a) Keep the ASX as it is. (b) Stop new ASX entries. (c) ASX in
one cell only.

**Recommendation: (a) keep the ASX for hc4-1, with PR-2 as the exit.**

**What would change it.** PR-2 trips: after at least 15 ASX rules closes the
ASX averages -0.30R or worse and sits 0.30R or more below NASDAQ. The replay
would also need to show the ASX at 0 or below.

**Replay results (pending the decision_replay run).** Variants: hc4-1 with no
ASX; hc4-1 with ASX in 3D reclaim only. Report R per trade and R per
slot-month for each market, with the time stop on.

---

## #2 - Drop the 3D-reclaim cell?

**What it is.** A 3D reclaim is a close back above the 3-day 200-SMA. It is
the cell with the biggest live losses. The task was to set, in advance, the
line at which it gets dropped.

**Evidence.**

| Source | 3D reclaim |
|---|---|
| Live, all cycles, all closes | 41 closes, **-16.16R** (avg -0.39R, 27% won) |
| Live, rules closes | 18, -14.46R (avg -0.80R), 12 of them stops |
| hc4-1 | 6 closes, all by the rules, -5.40R (5 stops, 1 breakeven trail); 29 open at +0.36R; 6 of the 29 are past -0.5R |
| 10-year replay | +0.06R (266). Stocks only -0.09R (193); ASX -0.35R (44); NASDAQ -0.01R (149) |
| 5-year replay | +0.09R (69) |
| Parity, weekly/3d rows (in-sample / out-of-sample / C3) | +0.16R (139) / +0.06R (274) / -0.03R (235) |
| The 600-name replay behind the four-cell rule (not committed; item 5) | +0.20R (1,309) |

**What it says.** History ranges from slightly negative (stocks, 10-year) to
clearly positive (the 600-name run). The live result is clearly negative, but
23 of the 41 live closes were hand closes in earlier cycles. hc4-1 has only 6
so far.

**Where PR-1 is heading.** The first read comes when the 20th 3D-reclaim
close lands, around Mon 26 Oct, once 16 more rows reach their time stop. Those
16 are the early entries (21-22 and 28-29 Sep). Between them they are
**-4.23R** under water today, and all 6 rows past -0.5R are among them. The
13 rows due later are **+4.59R** up. On today's marks the read is 22 closes
at about **-0.44R**, so it would trip. The replay veto then decides between
dropping the cell at hc4-2 and holding for the second read at 40 closes
(line -0.15R), which the later, healthier entries would reach.

**Options.** (a) Keep it, with PR-1 as the exit. (b) Drop it now.

**Recommendation: (a).** Dropping it now would end hc4-1 on 6 trades.

**What would change it.** PR-1 trips at -0.30R or worse after 20 closes, or
at -0.15R or worse after 40.

**Replay results (pending the decision_replay run).** Variants: hc4-1 without
3D reclaim; 3D reclaim alone, by market, with the time stop.

---

## #3 - Keep taking A grades?

**What it is.** Since 21 Sep the bot takes A grades as well as A+. 12 of the
60 open positions are labelled A. There were more A takes, but rows opened
before 24 Sep were recorded as A+ by mistake.

**Evidence.**

| Source | A+ | A |
|---|---|---|
| 10-year replay, all markets | +0.14R (283) | -0.06R (206) |
| 10-year replay, **stocks only** | **-0.04R (216)** | **-0.06R (136)** |
| 5-year replay | +0.14R (82) | -0.15R (69) |
| 600-name replay (config notes) | A+ only +0.216R (1,423) | A and A+ together +0.212R (2,403), so A alone is about +0.21R (about 980) |
| Confluence ledger, longs, 20 sessions | -3.68% (82) | -2.91% (87) |
| hc4-1 open | 40 rows, +1.24R | 12 rows, +0.03R |

**What it says.** A+ leads A only once crypto is mixed in. In stocks, where
59 of the 60 positions are, the two are the same. The bigger replay found no
gap at all.

**Recommendation: keep A, with PR-3 as the exit.** With only about 12 A rows,
PR-3 probably won't have 15 A closes until November. Until then the replay
answers it.

**What would change it.** PR-3 trips, or the decision_replay shows stock A
trades at least 0.10R below A+ on 300 or more trades.

**Replay results (pending the decision_replay run).** Variant: hc4-1 with A+
only. Report it for stocks and crypto separately.

---

## #4 - Only trade rows at the weekly level?

**What it is.** The bot only takes rows reacting at a weekly or 3-day 200-SMA.
In August's parity replay, "weekly only" was the best variant. The question is
whether to narrow to weekly.

**Evidence.**

| Source | Weekly | 3-day |
|---|---|---|
| Parity in-sample, weekly-only variant vs all levels | **+0.105R (197)**. It failed the pass test because the ASX got slightly worse. | baseline -0.033R (613) |
| Parity by level (in-sample / out-of-sample / C3) | +0.06 / +0.04 / +0.07 | +0.07 / +0.05 / +0.04 |
| 10-year replay | -0.02R (206) | +0.11R (283) |
| Live, all closes | -0.06R (34) | -0.29R (52) |
| hc4-1 | 23 open +0.44R, 0 closed | 29 open +0.83R, 6 closed -5.40R |

**What it says.** Head to head, the 3-day level beats weekly in three of the
four historical reads (by 0.005R to 0.12R a trade), and weekly wins the
fourth (C3). The +0.105R weekly-only figure was measured against *all*
levels, including the daily ("h4") level (-0.11R) that the current gate
already excludes. Most of that advantage came from dropping the daily level,
and the bot already does that. The live 3-day losses are the same rows as #2.

**Recommendation: no change. PR-4 decides on the replay.**

**What would change it.** Weekly-only beats weekly + 3-day by +0.05R a trade
or more, in the ASX and NASDAQ separately and in both halves of the sample.

**Replay results (pending the decision_replay run).** Variant: hc4-1 with the
level gate set to weekly only.

---

## #7 - Grade the row on the plan the bot will actually trade

**What it is.** The scanner grades a row on the first armed plan it finds,
checking 1W, then 3D, then 1D. Suppose that plan is a 1W retest, which isn't
a cell, with a poor R:R. The row is marked down to B+, and the bot never sees
the valid 3D reclaim underneath it. It also works the other way: a row can be
graded A+ on a 1W retest while the bot trades its 3D plan.

**Evidence.** On today's three scans, 2 long rows have a headline plan that
isn't a cell with an armed cell plan underneath. Neither was marked down. The
problem is real but rare.

**Options.** (a) Grade on the first armed cell plan, the one the bot walks
to. (b) Leave it.

**Recommendation: (a), at hc4-2.** It can only add takes, and only rarely.
The next boundary is about two weeks away.

**What would change it.** Nothing urgent. If a counter showed it costing more
than one take a week, it would still wait for the boundary.

**Replay results (pending the decision_replay run).** How many rows are
marked down, and the R of the takes they would have added.

---

## #11, #13, #143 - Sector caps and sector names

**What it is.** The bot allows at most 6 positions per sector in each market.
Three problems sit underneath that:

- **#11:** the cap is counted per market, so 6 ASX financials plus 6 NASDAQ
  financials is allowed.
- **#13:** the names don't match. NASDAQ uses Yahoo's names ("Financial
  Services", "Healthcare"), while other sources say "Financials" and "Health
  Care".
- **#143:** the ASX "sector" is really a GICS *industry group*, giving 27
  labels where there should be 11 sectors. Banks, Insurance and Financial
  Services are one sector split into three buckets. 285 ASX names labelled
  "Not Applic" share a single bucket, and all 704 Materials names share
  another.

**Evidence (open book today).**

- **ASX financials:** NAB (Banks); ASX, CCP, NGI and PPM (Financial
  Services); AUB and NHF (Insurance). That is **7 positions, $17,500**. Counted
  as one sector it is over the cap of 6. Counted as three buckets it is under.
- **NASDAQ Financial Services:** 4 more (BHF, HBAN, INTR, LKFN). Across both
  markets that is **11 financials, $27,500, 18% of the book**.
- **NASDAQ Healthcare:** 6, at the cap.

**Options.**

- (a) Leave it as it is.
- (b) Map the ASX industry groups to the 11 GICS sectors and NASDAQ's Yahoo
  names to the same 11, and keep 6 per market. "Not Applic" and "Class Pend"
  become blank, and blank rows are exempt from the cap, which loosens it for
  those 306 names.
- (c) As (b), plus a cap across markets (for example 9 per sector, $22,500).

**Recommendation: (b), at hc4-2.** The cap would then mean the same thing in
both markets. Mostly it tightens. The cap across markets (c) stays your call:
you ruled per-market in REFINEMENTS #113, and nothing new argues against it.

**What would change it.** A correlated hit: 4 or more positions in one GICS
sector stopping out in the same week would argue for (c).

**Replay results (pending the decision_replay run).** Variants: the
normalised sector cap; the normalised cap plus a 9-per-sector cap across
markets. Report how many takes each would have refused and their R.

---

## #12 - Cap of one position per company

**What it is.** Nothing stops the bot holding two share classes of the same
company. **FWONA and FWONK are both open**. They are two lines of Liberty
Media (Formula One): $5,000 and 2 slots on one company. In the NASDAQ
universe, 85 companies have more than one listed line. Most are preferreds or
warrants, but there are ordinary pairs too: GOOG/GOOGL, FOX/FOXA, FWONA/FWONK,
BATRA/BATRK.

**Options.** (a) Allow one position per company. (b) Leave it.

**Recommendation: (a), at hc4-2.** It only tightens, and it would have
refused 1 of the 58 hc4-1 entries.

**What would change it.** You decide a dual-class double is a bet you want.

**Replay results (pending the decision_replay run).** Not a replay question.
The count above is the evidence.

---

## #30 - Re-stamp the old ASX forward returns?

**What it is.** Before 5 Oct, the edge pipeline was thought to have recorded
some ASX forward returns from still-forming intraday bars. The estimate was
about 1,900 alert stamps and 7,700 roster stamps. The question was whether to
clear or re-stamp them.

**Evidence (new, measured for this pack).** The history archive
(`data/history/asx`) keeps completed bars only, and each scan that lists a
name rebuilds that name's file from Yahoo's latest data. So it is an
independent record of final closes.
**Every pre-5-Oct ASX stamp it can check matches the final close to 6 decimal
places: 7,851 roster stamps and 2,926 alert stamps, with 0 differences.**
About 3,300 roster stamps and 800 alert stamps can't be checked, because
the archive stops updating a name once it leaves the scan.

The check can find bad stamps. It found 64 roster stamps and 3 alert stamps
that differ, all made after the fix and all reading the **13 Oct** bar. The
likely cause is that Yahoo revised that day's ASX bar after the stamp was
taken. It is worth a look on its own.

**Recommendation: don't re-stamp.** There is nothing to fix in the stamps
that can be checked. The `stamped_at` field shipped in this batch covers the
future.

**What would change it.** Finding a pre-5-Oct stamp that disagrees with the
archive.

**Replay results (pending the decision_replay run).** Not a replay question.

---

## #42 - Retire Specs?

**What it is.** Specs flags names under $0.50 that break out of a base on 3x
or more volume. Its own documentation calls it a shortlist, not an entry
system, and its backtest agrees.

**Evidence (5-year replay).**

| | ASX |
|---|---|
| All trades | 9,068 trades, **-0.077R** each (profit factor 0.84). With stops filled at the bar's worst price, -0.141R |
| By grade | A+ -0.062R (6,500); A -0.112R (2,323); B -0.125R (245) |
| 20-session return | -1.07%, against +2.36% on random dates for the same names |
| NASDAQ | 10 trades, too few to say anything |
| In confluence | a leg in 51 of 3,357 alignment rows (1.5%) |

**Options.** (a) Retire it completely: page, nightly step and confluence leg.
(b) Keep the page as a shortlist and take it out of confluence. (c) Keep
everything.

**Recommendation: (a) if you don't open the Specs page; (b) if you do.** The
bot never reads Specs, so no trade changes either way.

**What would change it.** You use the list to find names you then trade.

**Replay results (pending the decision_replay run).** Not a replay question.

---

## #43 - PhaseMap's A+ tier does worst

**What it is.** PhaseMap grades its setups A+, A or Watch. In its own
backtest the order comes out upside down.

**Evidence (5-year PhaseMap backtest, R per trade).**

| | A+ | A | Watch |
|---|---|---|---|
| ASX bullish | **-0.18R** (885) | -0.13R (4,058) | -0.11R (2,281) |
| ASX bearish | **-0.15R** (1,000) | -0.12R (4,138) | -0.07R (2,267) |
| NASDAQ bullish | **-0.02R** (689) | +0.03R (3,309) | +0.05R (1,806) |
| NASDAQ bearish | **-0.15R** (778) | -0.08R (3,581) | -0.07R (2,210) |

20-session returns tell the same story. ASX: A+ +0.38%, A +0.74%, random
dates +1.89%. NASDAQ: A+ +1.31%, A +2.14%, random dates +2.32%. Every tier
trails random dates, and A+ trails the most. PhaseMap is a leg in 99.4% of
all confluence alignments (3,338 of 3,357), so this matters for the
multi-lens pill too.

**Options.** (a) You revise the grade ladder in the spec. (b) Show each
tier's measured result on the page and stop ranking A+ first. (c) Nothing.

**Recommendation: (b) now, as a display change. Put (a) on your spec list.**
Claude won't touch the detection maths.

**What would change it.** A rerun after this batch's PhaseMap fixes (no more
weekend reruns, no more mid-session NASDAQ bars) shows A+ at least level with
A.

**Replay results (pending the decision_replay run).** Not part of the VIVEK
replay. The weekly lens backtest reruns it.

---

## #44 - PhaseMap's crypto statistics are corrupt

**What it is.** PhaseMap still reads Yahoo's `<SYM>-USD` prices. For some
tickers that is a different coin from the one the scanner trades; the same
problem was found and fixed for VIVEK on 28 Sep.

**Evidence.** The crypto stats are impossible. Random dates show a 5-day
return of **+1,770%**. The A tier shows **-136%** at 20 sessions. Bullish
Watch shows **+10.9R a trade**, with a profit factor of 25.

**Options.** (a) Move PhaseMap crypto onto the exchange feed with its
identity check. Only the price bars change, not the detection maths. (b) Hide
the crypto stats. (c) Leave the data as it is and keep the crypto stats
labelled unreliable on the page.

**Recommendation: (a).** The spec governs the data provider, so it needs your
OK.

**What would change it.** You want PhaseMap kept on Yahoo for spec reasons.
In that case, (b).

**Replay results (pending the decision_replay run).** Not a replay question.

---

## #47 - Ignition's 3x volume rule

**What it is.** Ignition only counts a breakout if the day's volume is at
least 3 times its 20-day average. Its replay can drop that rule and keep
everything else the same.

**Evidence.**

| Market | As is | Without the volume rule | Difference (90% range), chance of no real gain |
|---|---|---|---|
| Crypto | +1.19R (94) | +0.99R (145) | +0.20R (-1.39 to +1.89), 0.44 |
| ASX | +0.24R (203) | +0.20R (363) | +0.04R (-0.34 to +0.43), 0.43 |
| NASDAQ | -0.02R (390) | -0.09R (1,018) | +0.08R (-0.08 to +0.23), 0.21 |

Setting the threshold at 2x / 3x / 5x gives: crypto +0.99 / +1.19 / +2.31R;
ASX +0.11 / +0.24 / +0.18R; NASDAQ +0.04 / -0.02 / -0.06R. The forward
bucket, the only truly unseen data, has **0 trades** in every market.

**What it says.** The volume rule makes the list shorter. It doesn't
measurably make it better.

**Recommendation: keep 3x.** It was set before the first run, and changing it
now would restart the forward test. Ignition is report-only, so no trades are
affected. PR-8 decides.

**What would change it.** PR-8: over 30 or more forward trades in a market,
the no-volume version does at least as well.

**Replay results (pending the decision_replay run).** Not part of the VIVEK
replay. Ignition's own weekly replay (item 48) fills the forward bucket.

---

## #84 - Upgrade yfinance 1.4.1 to 1.7.0?

**What it is.** Every stock price the scanner and the bot read comes through
yfinance, pinned at 1.4.1. Version 1.7.0 is out.

**Evidence.** Nothing is broken on 1.4.1 today. The risk of upgrading is a
quiet change in adjusted prices, timestamps or columns, which would move
every mark at once.

**Options.** (a) Upgrade now. (b) Upgrade on a weekend after a dry-run check:
run all three scans on the new version without publishing, and compare row
counts, grades and last closes (within 0.5%) against the live scans. (c) Hold
until something breaks.

**Recommendation: (b), on a Saturday.** If the comparison is clean, hc4-1
isn't disturbed. If Yahoo breaks 1.4.1 first, that forces the upgrade anyway.

**What would change it.** The comparison shows differences. Stay on 1.4.1
and investigate.

**Replay results (pending the decision_replay run).** Not a replay question.

---

## #137 and #153 - Weekly and 3-day candles that haven't finished

**What it is.** A 1W or 3D trigger can fire on a candle that is still
forming. Tuesday's scan sees a week that so far holds only Monday's session.

- **#137 (price):** a "weekly reclaim" can arm on Tuesday and be gone by the
  Friday close.
- **#153 (volume):** the volume test compares that part-week's volume with
  full weeks. A 1W break, which needs high volume, almost only arms late in
  the week. A retest, which needs quiet volume, arms easily early in the week.

**Evidence.**

- **Archive replay, 120 liquid ASX names:** 824 weeks armed a 1W reclaim on
  some day, and **241 of them (29%) were not a reclaim at the Friday close**.
  Where a week armed on several days, the entry moved by up to 7.2% (the 90th
  percentile).
- **Volume:** 1W break arms by day: Mon 40, Tue 115, Wed 253, Thu 490, Fri
  775, a 19x difference.
- **Live:** a Monday scan sees a *completed* week, because the forming day is
  dropped. 1W closes from Monday entries (completed week) average -0.09R
  (n=14). Tue-Fri entries (week still forming) average -0.01R (n=27). Open
  rows: Monday entries are at -1.27R across 6 rows, Tue-Fri at +1.44R across
  20. **So far the live book shows no penalty for entering on a forming
  week**, though the samples are small.
- **hc4-1 has 0 1W-break entries.** In practice the cell only arms on
  Fridays.

**Options.** (a) Leave it. (b) Arm 1W/3D only on completed candles. (c) Freeze
the entry on the first day a plan arms. (d) Scale the volume test by how much
of the candle has formed.

**Recommendation: no change mid-cycle.** Publish an "is the trigger candle
complete?" field on 1W/3D plans and in the backtest trades. That is a label,
not a rule, so it is safe mid-cycle, and it lets the question be measured.
PR-5 decides (b) on the replay. Do (d) at hc4-2 if PR-5 shows the 1W-break cell
behaving differently once volume is scaled.

**What would change it.** PR-5: completed-candle triggers beat forming ones
by +0.10R a trade or more, over 200 or more trades in each group.

**Replay results (pending the decision_replay run).** Split 1W/3D trades by
whether the trigger candle was complete. Run a variant that arms on completed
candles only, and one with the volume test scaled.

---

## #145 - Confluence counts B+ and WATCH rows

**What it is.** A VIVEK row counts as a confluence leg whatever its grade,
including B+ and WATCH rows that haven't triggered.

**Evidence.** 669 of the 1,688 graded alignment rows (40%) have a B+ (600)
or WATCH (69) VIVEK leg, as do 29 of the 77 live alignments. Signed 20-session
returns, all rows: A+ +0.20% (233), A -0.98% (216), **B+ +0.75% (270)**, WATCH
-0.03% (21). Longs only, first sighting: A+ -3.68% (82), A -2.91% (87), B+
-2.75% (113).

**What it says.** B+ legs do no worse than A+ legs. Removing them would shrink
the evidence without improving it.

**Recommendation: keep counting them.** From this batch every alignment
records the VIVEK grade at alert time (#139), so the split can be read on
any day. No trades are affected: the bot never
reads confluence.

**What would change it.** At 20 sessions, B+ legs end up clearly behind A+
on 200 or more rows each.

**Replay results (pending the decision_replay run).** Not a replay question.

---

## #148 - The "W+H4 confluence" point

**What it is.** One scoring point is meant for "the weekly and the daily
200-SMA are both near the price". The code only checks that the two averages
are near *each other*, and both can be far from the price.

**Evidence (today's scans).** 49 rows score the point. In 29 of them one of
the two averages is more than 4% from the price, and in 9 both are. On 9 rows
the point decides the grade: 7 are A+ at exactly 8 (DEV, WERN, DNLI and STNE
long; ACF, AGIO and SAIA short), and 2 are A at exactly 6 (DXI and LF1, both
short). The bot takes A as well as A+, so the point only changes what the bot
can take at the A/B+ line (a score of 6). **Today that is 0 long rows.**

**Options.** Fix it now, fix it at hc4-2, or leave it.

**Recommendation: fix it at hc4-2.** It is a bug, but today it costs the bot
nothing, so there is no reason to break the cycle for it.

**What would change it.** A long row the bot would take sitting at score 6
because of the point. The fix would then still wait for hc4-2, but it moves
to the top of the list.

**Replay results (pending the decision_replay run).** Variant: the point
requires both averages within 4% of the price. Report the grade changes and
their R.

---

## #152 - Break entries fill above the planned price

**What it is.** A break plan's entry is the level that was broken. But the
trigger candle has already closed above it, so the real fill is higher, and
the plan's R:R overstates what you actually get.

**Evidence.**

- **Live:** 8 break fills. The median fill was **3.96% above the plan entry**
  (the most was 6.7%).
- **WBC** filled at $38.36 with TP1 at $38.46, only 0.03R away. It hit TP1 at
  once, the stop moved to breakeven, and it closed at -0.06R.
- **Archive (40 ASX names):** 40% of 1D break arms with a plan R:R of 1.5 or
  more are below 1.5 at the trigger close. 15% close at or above TP1 and are
  still marked armed.
- **hc4-1:** 2 open 1D breaks (CVLT and ZS) and no 1W breaks.

**Options.** (a) Re-measure R:R and TP1 from the actual fill, and skip the
trade if R:R is below 1.5 or the fill is past TP1. (b) Disarm plans whose
close is already past TP1. (c) Leave it.

**Recommendation: (a), at hc4-2.** It only tightens, and affects few trades.

**What would change it.** Break cells becoming a large share of entries
would make this more urgent.

**Replay results (pending the decision_replay run).** Variant: re-check R:R
and TP1 at the fill. Report how many takes it refuses and their R.

---

# Reports

## #32 - The 28-day time stop

**Live.** 16 time-stop exits: **+2.55R**, 8 of them winners, averaging
+0.16R. On 4 Sep, P11 recorded +2.14R over 11. The time stop is still the
rules' only positive exit.

**What happened after (8 ASX exits the archive covers).** In the next 28
sessions (19 for the September exits), 3 went on to touch TP1 and none
touched the original stop. At the end of that window they averaged **+0.36R**,
against the +0.12R the time stop took. KLS touched TP1 the next day but ended
at -0.66R. Eight trades suggest the stop might cut slightly early. They don't
show it is wrong.

**Parity replays (with the time stop).** Time exits are about two-thirds of
all exits and average +0.04R, +0.04R and +0.08R (in-sample, out-of-sample, C3). In the
in-sample test of hold lengths, 28 days was best: -0.033R a trade, against
-0.055R at 42 days, -0.059R at 56 and -0.061R with no time stop.

**The 10-year replay has no time stop.** Its trades are held a median of 151
days, so it can't answer this question (see #34).

**Verdict: keep 28 days.** P11 stands. PR-7 runs 21 days, 42 days and no
time stop under the hc4-1 rules.

## #33 - Trail and target readout (P12, due at 30 rules closes; now 40)

| P12 question | Answer |
|---|---|
| (a) What does taking 25% at TP1 leave on the table? | 4 rules closes hit TP1 (WBC, IGL, HM1, GLBE). On average they peaked at +0.72R and **realised 0.00R**. All four gave the rest back to the breakeven stop. |
| (b) How often does a winner turn into a scratch (peak +1R or more, exit +0.2R or less)? | 4 of the 40 peaked at +1R or more. **One** (IGL: peak +1.36R, exit 0.00R) became a scratch. KHC (+1.11R), BTC (+1.23R) and VVA (+0.29R) were time exits. |
| (c) How often does moving the stop to breakeven save money? | 3 of the 4 are ASX and can be checked. **WBC and IGL fell through their original stop within 3-4 sessions of the breakeven exit** (12 Aug and 1 Sep), so the move saved about 1R each. HM1 drifted to -0.65R over 24 sessions without touching it. That is 2 clear saves out of 3. |

TP1 sits a median 1.03R from entry (10th percentile 0.68R). Only 7 of 172
rows had a TP1 closer than 0.5R. WBC's was 0.03R, but that is the
break-fill problem (#152), not the ladder. 6 open rows are past TP1 and
protected at breakeven.

**Verdict: nothing to tune.** Four TP1 trades is too few to judge the ladder,
and the breakeven move is earning its keep. Read again at 20 TP1 hits.

## #34 - Live drawdowns vs the backtest (report only)

**Live.** 29 closes went to -0.5R or worse at some point, and **none of them
won** (20 stops, 8 hand closes, 1 time stop). **Backtest** (10-year,
hc4-1-style): 310 of 489 trades went to -0.5R or worse, and **75 (24%) still
won**.

Why they disagree, in order of size:

1. **The 10-year backtest has no time stop.** 74 of those 75 winners were held
   more than 28 days, a median of **395 days**. The live bot would have
   closed most of them at 28 days, before they recovered. Parity replays that
   do include the time stop show 13-20% of deep-drawdown trades still winning,
   mostly as small positive time exits (in-sample 20 of 101, out-of-sample 21
   of 119, C3 19 of 143).
2. **Hand closes cut the recoveries short.** 8 of the 29 were closed by hand
   at between -0.31R and -0.88R, before they could either recover or stop
   out.
3. **The recoveries are still open.** A trade that dips and comes back takes
   longer, so it is still in the book. 14 open rows have been at -0.5R or
   worse, and 2 of them are now positive. Closed rows over-represent the fast
   losers.
4. **Different measurement.** Live MAE is the worst price seen at a scan, a
   few snapshots a day. The backtest uses each bar's low, so the same price
   path reads deeper in the backtest.

Even against parity, live is worse than history would suggest. If about 17%
of deep-drawdown trades should win, 0 out of 21 rules closes would happen
about 2% of the time. Part of that is the market: A+ longs lost about 3.2% in
20 sessions across all markets.

**Verdict: don't tighten stops on this.** The comparison mostly measured the
missing time stop. The decision_replay, with the time stop on, is the fair
comparison.

## #35 - Review flags

The flag marks a plan when a full stop-out would cost 7.5% or more of the
$4,500 daily loss guard ($337.50, which is a stop about 13.5% wide on
$2,500).

| | Flagged | Not flagged | Before flags existed |
|---|---|---|---|
| Closed rows | 46: -8.24R (avg -0.18R) | 30: -4.05R (avg -0.135R) | 36: -2.87R |
| Median stop width | 19% | 10% | 15% |
| Closed P&L, at the size held | **-$5,705** | -$95 | +$1,334 |
| Open rows | **32 of 60 (53%)**, $14,639 at risk | 28, $6,334 at risk | - |
| hc4-1 entries | 29 of 58 (50%) | 29 | - |

**What it says.** The flag doesn't predict worse R; flagged and unflagged
trades lose about the same per trade. What it does predict is bigger dollar
swings: about twice the risk per trade, and 70% of the open book's dollars at
risk. It was built to ask "should Claude take this, or should I?" From today
you don't close by hand, so nobody acts on it.

**Verdict: no change for hc4-1.** It is a label, and it describes size
accurately. If amber on half the rows is just noise to you, the clean option
is to retire it at hc4-2. That would be a display-only change.

## #36 - High-conviction 20-session checkpoint (~20 Oct)

**The test (PR-6).** Take A+ long roster rows from Mon 21 Sep, when the
four-cell High-conviction rule started. Keep the first sighting per name.
Compare the 20-session return of High-conviction names against the other A+
names.

| Horizon | High conviction | Other A+ |
|---|---|---|
| 5 sessions | -0.92% (n=131, SE 0.65) | -1.64% (n=290, SE 0.36) |
| 10 sessions | -2.01% (n=87, SE 1.12) | -1.97% (n=200, SE 0.58) |
| 20 sessions | 1 crypto name | 1 crypto name |

No difference so far. **The first 20-session results for stocks land on Tue
20 Oct**: 21 Sep plus 20 ASX sessions is the Mon 19 Oct close, recorded the
next morning. The first real read is **Tue 27 Oct**, when more than 40 HC
names will have matured. The badge is display-only. But the bot's cells *are*
the HC cells, so a bad result here is also an early signal for PR-0 to PR-3.

## #39 - Breadth (P15): closed

P15 proposed recording each market's breadth (the share of stocks above their
200-day average) on every entry, to test whether entries in stretched markets
do worse. The breadth engine was removed on 20 Sep at your request, and
ledger rows since 19 Sep carry no breadth. The stamps that do exist (20 Aug to
18 Sep) cover one narrow stretch (ASX 47-53%, NASDAQ 57-67%), which is too
narrow to test anything. The last read: NASDAQ A+ longs after 20 sessions,
split into breadth thirds, returned -2.86%, -3.93% and -4.69% from low to
high. That is the direction P15 expected, but within noise (SE about 1.0-1.4pp
each).

**Verdict: close P15.** If you want it back, the minimum is a single number
per market per scan (the share above the 200-SMA), recorded on new book rows,
with no page.

---

*Regenerate the live-book figures with `python scripts/decision_pack.py`. It
is read-only and stdlib-only, and `tests/test_decision_pack.py` checks that the
register above matches its frozen thresholds.*
