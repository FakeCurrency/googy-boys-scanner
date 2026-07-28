# Memo — how an entire sector ran without the book touching it

**To:** Viv
**Date:** 28 July 2026
**Subject:** Consumer Discretionary, June–July 2026 — what actually blocked participation, and what to probe so it does not repeat

---

## The short version

The scanner did not miss Consumer Discretionary. It graded it, tagged it correctly, and
put armed A+ setups on the board. **The book simply had nowhere to put them.**

The ASX book hit its 10-position ceiling on **30 June** and did not fall below it on a
single trading day until **28 July**. NASDAQ hit 10 on **9 July** and has been pinned
there ever since. Between 9 July and 20 July the entire book — all three markets — did
not move at all: no entries, no exits, twenty-four positions, thirteen consecutive
trading days. That is precisely the window you are describing.

So the ranking of causes is not the one the question implies. Sector blindness is real
and it is worth fixing, but it is cause number two. Cause number one is that the book
was full of June and could not buy July.

---

## What I checked, and what the data says

**Your 30 names are clean in the system.** All thirty are in the ASX universe roster
(2,212 names), and the universe file tags all thirty as `Consumer Discretionary` — one
taxonomy, no synonym mess, nothing unclassified. Whatever went wrong, it was not the
reference data for these names.

**The scanner saw them.** Today's ASX scan produced 336 setups from 2,133 symbols
scanned. Eight of your thirty appear in it: SNL, SUL and BRG at A+, ALL and PWH at A,
and TLC, PMV and FLT at B+. Six of the eight are armed with a live entry trigger and a
full three-target plan. This is not a detection failure.

**But the book never had a slot.** Here is the daily open-position count reconstructed
from entry and exit dates:

| Date | ASX | NASDAQ | Crypto | Total | |
|---|---|---|---|---|---|
| 29 Jun | 8 | 1 | 1 | 10 | |
| 30 Jun | 10 | 2 | 1 | 13 | ASX at cap |
| 3 Jul | 10 | 3 | 4 | 17 | ASX at cap |
| 8 Jul | 10 | 4 | 4 | 18 | ASX at cap |
| **9 Jul** | **10** | **10** | **4** | **24** | **both at cap** |
| 10–24 Jul | 10 | 10 | 4 | 24 | both at cap, unchanged |
| 27 Jul | 10 | 10 | 3 | 23 | both at cap |
| 28 Jul | 11 | 10 | 3 | 24 | 30-position rule ships |

Twenty consecutive ASX sessions at the ceiling. In that period the bot took two ASX
entries (20 July) and two more (23 July), each one only because something had just
stopped out. Every other candidate — including your sector — was declined with
`book_full` before a single quality check ran.

**Why nothing closed is the other half of the story.** Of the twelve completed trades,
six exited on a stop and six exited on the 28-day time limit. The stops were clustered
in early July; after 23 July nothing resolved on its own at all. The survivors are not
winning or losing, they are sitting still — median unrealised result across the
eighteen positions older than a day is **+0.03R**. That is the chop you are describing,
and in a full book chop is not a flat month, it is a *closed* month: capital is locked
in setups that will neither pay nor release until the 28-day timer expires.

Note the timing. `VIVEK_BOT_MAX_HOLD_DAYS = 28`, and the 29 June cohort was opened on
29 June. The earliest that cohort could possibly be released was 27 July. **Five ASX
positions closed this morning with `reason=time`, all of them 29 days old, all of them
opened 29 June.** The book unfroze today — by the calendar, not by the market.

**Participation, for the record.** Since the book opened on 28 June it has taken 36
trades. Exactly one of your thirty names was ever held: PMV, opened 29 June, closed
this morning on the time stop at −0.24R. Two of the twelve completed ASX trades were
Consumer Discretionary. Right now the book holds **zero**.

---

## The four things that actually need to change

### 1. Capacity and turnover — already half-fixed, today

The 30-position global book you authorised is the single biggest thing you have changed,
and this analysis is the reason why. It shipped this morning and immediately took six new
ASX entries — the first meaningful movement in the book since 9 July.

What is still unaddressed is turnover. A 28-day time stop on a 30-slot book sets a
throughput ceiling of roughly one entry per day *in the worst case where nothing else
resolves* — which is exactly the case that occurred. Whether 28 days is right is a
trading judgement, not a code question, and it is squarely yours. The thing worth
knowing is that in a sideways tape the time stop stops being a safety net and becomes
**the only rotation mechanism the book has**.

### 2. There is no sector-level signal anywhere in the decision path

`decide()` ranks candidates by grade and score, symbol by symbol, and then applies a
sector *ceiling* of three. There is no sector floor, no sector tilt, no notion that one
sector is behaving better than another. A sector can only enter the book as a
side-effect of individual names scoring well. Nothing in the pipeline is capable of
forming the sentence "Consumer Discretionary is leading" — not the scanner, not the bot,
not the dashboard.

### 3. The one sector number you can see points the wrong way

The scan publishes `sector_counts`, and the dashboard's SECTOR view renders it. It is a
**raw count of setups**, which is dominated by how many companies are listed in each
sector, not by how they are behaving. Today it reads:

| Sector | Names in universe | Setups | Setup rate | A+/A | **A+/A rate** |
|---|---|---|---|---|---|
| Real Estate | 62 | 20 | 32.3% | 14 | **22.58%** |
| Financials | 198 | 52 | 26.3% | 33 | **16.67%** |
| **Consumer Discretionary** | **104** | **14** | **13.5%** | **11** | **10.58%** |
| Industrials | 145 | 16 | 11.0% | 11 | 7.59% |
| Health Care | 163 | 13 | 8.0% | 10 | 6.13% |
| Energy | 116 | 8 | 6.9% | 5 | 4.31% |
| Materials | 766 | 52 | 6.8% | 30 | **3.92%** |
| Info Tech | 138 | 3 | 2.2% | 3 | 2.17% |

On raw counts Consumer Discretionary ranks **sixth**, tied well behind Materials and
Financials at 52 each. Normalised by sector size it ranks **third**, at nearly three
times the Materials rate. Materials has 766 listed names and will out-count every other
sector on every scan forever, regardless of what it is doing. **The number you have been
able to eyeball has been actively misleading you**, and it is one division away from
being useful.

### 4. The sector tape is already downloaded, then thrown away

`public/data/sectors.json` fetches the twelve ASX GICS sector indices every scan. Right
now it holds XDJ (Consumer Discretionary) at **+1.79%, the strongest of the twelve**, and
on the US side XLY at +1.91%. This is display-only. Nothing reads it, nothing stores it,
and it carries a single day's change — so it can tell you about today and can never tell
you about a rotation.

That generalises. The longest sector-shaped memory anywhere in this system is the
seven-day PhaseMap archive. I tried to reconstruct the July rotation from it and could
not: seven usable days, one of them corrupt, far too short to show a three-week move.
**A rotation that started in early July is not merely undetected, it is unrecoverable
after the fact.** Every day this stays unfixed is another day of history that does not
exist.

---

## What I am shipping now, without asking

All report-only. None of it changes which trades get taken.

The per-sector **rate** — A+/A setups divided by names listed in that sector — computed
each scan for each market and published alongside the existing raw counts, so the SECTOR
view can rank by behaviour instead of by listing count.

A **persisted sector history**: one small append-only row per sector per scan, with real
retention rather than a seven-day window. Twelve sectors and a handful of floats is
nothing on disk, and it is the difference between seeing today and seeing a rotation.
This is the time-sensitive one — it can only start accumulating from the moment it ships.

The **sector index tape captured** from the `sectors.json` fetch you already pay for, so
relative strength against XJO over one week, one month and three months becomes
computable rather than lost each scan.

And a **held-versus-leading line**: sectors ranked in the top three by breadth where the
book holds zero positions. That single line, printed every scan, is the alarm that would
have fired every day since early July.

Separately I found and fixed two real defects while doing this. The $150,000 portfolio
ceiling was not counting the current market's own open notional against itself — the
runner strips the `notional` field before `decide()` sees the book — so the effective
ceiling was looser than the one you set. And the ASX universe file, which has 100% sector
coverage, was not being used to back-fill sectors onto held positions; sixteen of the
twenty-four open rows currently carry no sector at all, which means they are **exempt
from the correlation cap entirely**.

---

## What needs your call

None of these are mine to make, because every one of them changes which trades get taken.

**The three-per-sector cap.** Even with perfect detection, three of thirty slots is a
10% maximum allocation to the best sector on the board. Options: leave it, raise it, or
make it conditional — three normally, five when the sector ranks top-two on breadth.

**Sector tilt in the ranking.** Today a leading sector confers no advantage on its
members. A score bonus for names in a top-ranked sector would change the composition of
every scan's take list.

**REFINEMENTS #112 and #113**, both already written up. #113: the sector cap is the only
limit still enforced per-market, so six of one real sector can sit in a thirty-slot book
with every check passing. #112: two held ASX positions carry a taxonomy the cap cannot
reconcile. Both fixes tighten, never loosen, and both are small and ready.

**Whether "zero held in a top-three sector" should page you** or just sit in the log.

---

## What I cannot tell you from here

I cannot backtest the counterfactual. The sandbox has no market-data access, so I cannot
pull price history for your thirty names and tell you what participating would have been
worth. That question belongs in `vivek_backtest.py`, which can be pointed at a sector
tilt once you decide whether you want one.

I also have not verified your read that the broad market has been poor since July — I
have today's index snapshot and no history. I have taken it as given, and nothing in the
analysis above depends on it: the book was frozen either way.

---

## The one-line answer

You did not miss the sector because the scanner could not see it. You missed it because
the book was full from 30 June, nothing resolved for three weeks, and the only exit
mechanism available was a 28-day timer that could not fire until 27 July. Fixing the
sector signal is worth doing and I am doing it — but **capacity and turnover are what
decide whether you can act on it at all.**
