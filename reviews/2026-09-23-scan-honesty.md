# Honest schedules + honest coverage — 2026-09-23

Branch `scan-honesty-2026-09-23` off `origin/main` `570ab8aea`. No trade logic
touched. Not touched: `vivek.py`, `scan.py`, `conviction.py`,
`scanner/broker/**`, `journal/`, `data/`, `bot_rules.json`, and the momentum
screen's rules and window.

**Headline.** The last `momentum.yml` run was **35820262321** (#4, scheduled,
crypto, 04:54 UTC). ASX coverage in the file on main is **1,165 of 2,047
downloaded**.

---

## 1. Actions: why the 06:30 UTC ASX run never started

`momentum.yml` has only ever run four times:

| Run | # | Event | Market | Created (UTC) | Cron clock | Conclusion |
|---|---|---|---|---|---|---|
| 35699038728 | 1 | workflow_dispatch | asx | 09-22 07:19:36 | — | success |
| 35700065335 | 2 | workflow_dispatch | asx | 09-22 07:31:54 | — | success (wrote `asx.json` 07:25) |
| 35798716770 | 3 | schedule | nasdaq | 09-22 23:42:45 | `30 21 * * 1-5`, **2h13m late** | success |
| 35820262321 | 4 | schedule | crypto | 09-23 04:54:53 | `30 0 * * *`, **4h25m late** | success |

No asx/nasdaq/crypto momentum jobs exist anywhere else.
`test_no_other_workflow_learned_about_the_lens` pins that.

**The workflow was not the problem.** Everything was checked and fine:

- The workflow is active.
- The cron syntax is valid.
- There is no path filter; schedules ignore path filters anyway.
- Concurrency cancelled nothing: all four runs succeeded, and no run was
  pending when 06:30 passed.
- GitHub had not disabled anything.

**GitHub's scheduler dropped the event.** It created almost no scheduled runs
repo-wide from about 06:46 to 09:53 UTC:

- `crypto_bot.yml`, a `:22`/`:52` cron, fired 4 times in about 11 hours.
- `kill_switch.yml` fired 3 times.
- The two momentum crons that did fire were 2h13m and 4h25m late.

A dropped cron leaves no run, no failure and nothing to retry. That is why
nothing visible happened.

**What kept firing:** `morning_plays.yml`, every 30 minutes all afternoon
(06:15, 06:45, 07:15 … 10:45 UTC). Those runs are `workflow_dispatch` events
from the cron-job.org pinger, so GitHub's scheduler plays no part in them.

### The fix: cron fix **Y**

`momentum.yml` no longer maps a cron string to a market. Every wake-up runs
`scripts/momentum_due.py` against the files as they are on main at that
moment (`git fetch` plus `git show origin/main:…`, because a run that waited
behind another was created at an older SHA).

A market is **due** when both of these hold:

- its `generated_at` predates the close it owes:
  - ASX / NASDAQ: 16:00 local + 30 min, weekdays, in the market's own
    timezone;
  - crypto: 00:30 UTC daily;
- and its next session has **not** opened yet.

The screen does not drop a forming bar (spec 5.11), so the gate never sends an
equity market into its own session. A missed window waits for the next close.

Other gate details:

- **One market per run, newest-due first.** A market stuck on a failure cannot
  starve one that has just become due.
- **Nothing due:** the run stops before `pip install`. The gate runs on the
  runner's system `python3` and is stdlib-only (pinned).
- **Manual dispatch** still screens the market it names, with no due check.

Wake-ups, deliberately redundant:

- the three original crons, unchanged;
- a new backstop, `41 */3 * * *`;
- `workflow_run` on **Morning plays (Discord)**, completed, branch `main`.
  This is the wake-up that would have caught today. Replaying today's
  recorded stamps: the 06:15 UTC Morning plays run finds nothing due, and the
  **06:45 UTC run picks ASX**. That is pinned as a test.

What the screen selects is unchanged. `screen.py` is untouched, and the rules,
window, mode, period, cache namespace, write-set and exit codes are all the
same. The new constants `PUBLISH_AFTER_CLOSE_MIN` and `CRYPTO_DUE_UTC` live in
`scanner/momentum/config.py`. The gate is the only thing that reads them, so
`RULESET_VERSION` does not move. Session hours are not restated anywhere: the
gate reads `scanner.config.VIVEK_JOURNAL_SESSION` and each market's timezone.

Tests:

- **`tests/test_momentum_due.py`** (new):
  - due instants in AEST, AEDT, EST, EDT and across weekends;
  - a full-week, 10-minute sweep in both DST regimes proving an equity market
    is never picked inside its session;
  - the incident replay;
  - newest-first / no starvation;
  - missing or corrupt files count as due;
  - the CLI's `$GITHUB_OUTPUT`;
  - stdlib-only imports.
- **`tests/test_momentum_workflow.py`**: the old cron→market pins are replaced
  with:
  - no `github.event.schedule` case;
  - every post-gate step is skipped when nothing is due;
  - the gate reads a fresh main before any install;
  - the `workflow_run` name exists and is dispatch-driven;
  - the crons ALONE deliver every market within 3h of its close, never before
    the close, in both halves of the DST year (computed by running the
    shipped crons through the shipped gate);
  - the three original crons are kept.
- **Mutations**: 4, all caught:
  - session check removed;
  - oldest-first;
  - zero publish lag;
  - weekend skip removed.

The first real proof comes after merge: the next ASX close (Thursday 24 Sep,
16:30 Sydney = 06:30 UTC) should produce a momentum run whose gate step
prints `picked: asx`. That will come from whichever of the cron, the backstop
or the 06:45 Morning plays run arrives first.

## 2. Coverage on the page

`public/data/momentum/*.json` on main:

| Market | Generated (UTC) | Downloaded / universe | Scanned | Gated | Cache reused | Hits |
|---|---|---|---|---|---|---|
| ASX | 09-22 07:25 | **1,165 / 2,047** | 298 | 867 | **0** (cold) | 4 |
| NASDAQ | 09-22 23:45 | 1,428 / 1,428 | 1,160 | 268 | 0 | 42 |
| crypto | 09-23 04:56 | 60 / 86 | 49 | 11 | 0 | 0 |

The /momentum header used to read `mode A · 1-bar window · 298 scanned · 867
gated · last bar 2026-09-22`. That looks like the whole market. It now reads:

> mode A · 1-bar window · **1,165 of 2,047 downloaded** · 298 scanned · 867 gated · last bar 2026-09-22
>
> 882 of 2,047 names returned no daily bars and the frame cache was cold (0 reused), so there was no earlier copy to fall back on — this screen covers 1,165 names, not the whole market.

How the header behaves now:

- **Counts only.** No percentage anywhere, so no fake 100%. NASDAQ shows
  `1,428 of 1,428` and gets no sentence.
- **The sentence appears only when names are missing.** It names the cache
  state:
  - cold → as quoted above;
  - warm → "even after N were filled from the frame cache";
  - absent → says it does not know.
- **The deck dot turns amber** for a partial file.

Found while doing this: the dot's `is-stale`/`is-fresh` classes had no CSS, so
the dot was **green even on "no data"**. It now carries the deck's `warn`
class in both cases.

Where it is pinned:

- `momentum.test.js` 389 → 411: runs the shipped `coverage()` against the ASX, NASDAQ,
  warm, unknown and empty summaries.
- e2e smoke +3: reads the committed `asx.json` and checks the header and
  sentence in a real browser.

Versions: `momentum.js?v=6`, `momentum.css?v=4`; `version.json` digest
replayed.

## 3. Crypto: **Y**, the tab stays

`public/data/momentum/crypto.json` exists: 60 of 86 downloaded, run #4. The
workflow's claim is real, so nothing was removed and no pairs were invented.
It now also gets the coverage line and sentence (26 names missing, cold cache).

**Observed, not changed** (it would change what the screen selects):

- Crypto's `last_closed_bar` is `2026-09-23` for a run at 04:56 UTC. That is
  the **forming** UTC day, about five hours in. The screen does not drop a
  forming bar, and a 24/7 market has no close to wait for.
- The old 00:30 cron already screened a 30-minute-old bar. Today's 4h25m delay
  made it five hours.
- The gate keeps crypto due from 00:30 UTC, the same instant as before, and does
  not make this better or worse.
- Dropping the forming crypto bar is a screen change and the owner's call.

## 4. 5.0 freshness

**Last 5.0 scans** on main, as of 11:21 UTC 2026-09-23 (commit `62c3d27f5`,
"data: scan 2026-09-23 11:18 UTC"):

| Market | `generated_at` (market-local) | UTC | Melbourne |
|---|---|---|---|
| ASX | 2026-09-23 21:17:21 AEST | 11:17Z | Wed 9:17 pm |
| NASDAQ | 2026-09-23 07:10:29 EDT | 11:10Z | Wed 9:10 pm |
| crypto | — | 11:12Z | Wed 9:12 pm |

These came from `workflow_dispatch` scans. Before them, the 09:35 commit
`c548d0c7e` (run 35842848005) carried ASX 19:33 AEST and NASDAQ 05:28 EDT.

`scan.yml` had no scheduled run between 04:37 and 09:53 UTC, so the ASX closing
scan at 06:37 was lost in the same scheduler gap. Dispatched runs covered it:
35832798743 started at 07:38 and landed at 07:55.

**Session + 2h rule, now on the deck** (`app.js`, display only). An ASX or
NASDAQ payload is marked stale when:

- a session has been open **2h** with no scan from inside it; or
- a session has been closed **2h** with no scan from after its close.

The weekday rule could not see a scan that stopped at 11:00 on a Wednesday;
nothing read stale until Thursday.

The rule is marked the same way the other stale numbers are:

- the `#scan-fresh` box goes `warn` (amber) and says, for example, *"no scan
  since the close (Wed 23 Sept, 4:00 pm Melb)"*;
- the deck dot turns amber;
- the row `⟳ scanned` chips go `stale`, through one shared `rowScanStale()`
  (the weekday rule OR the session rule), so the chip and its re-stamp cannot
  disagree.

Crypto keeps the wall-clock rule. Grades are untouched.

Other details:

- **Hours are not a third copy.** `app.js SESSION_STALE` mirrors
  `scanner/config.py VIVEK_JOURNAL_SESSION` plus the new
  `VIVEK_DECK_SESSION_GRACE_H = 2`. `tests/test_deck_session_stale.py` parses
  the literal out of the shipped file and holds them in step, including the
  zones.
- **The grace clears the scan cadence.** First scan is about 1h07 after the
  open; the last is 7–30 min after the close. A test also pins that.
- **Today's payloads read fresh under the rule.** ASX owes the 16:00 AEST close
  and was generated at 21:17. NASDAQ at 07:10 New York owes Tuesday's close
  and has it. The 19:33 / 05:28 pair before it is pinned as a test and reads
  fresh too.
- **Holidays are not modelled.** On one, "no scan since the open" is still
  literally true.

Tests and checks:

- `staleview.test.js` 134 → 142, executing the real functions:
  - `zonedInstant` in AEST, AEDT, EST, EDT and on both switch days, plus the
    second DST pass;
  - today's recorded payloads;
  - a scan that stopped mid-session;
  - no scan since the open;
  - the Friday → Monday weekend;
  - NASDAQ in both regimes;
  - crypto and unknown markets, and unreadable stamps;
  - the deck wiring.
- **Mutations**: 3, all caught. The third (single-pass `zonedInstant`)
  survived at first. The second-DST-pass assertion was added, and it is now
  caught.
- **Screenshot gate: 0.00% drift** on all four images. Measured against
  baselines cut from `origin/main` in a worktree: the e2e fixtures' ASX
  payload was scanned after Friday's close, so it reads fresh under the
  frozen clock.
- `app.js?v=137`, `version.json` replayed.

## 5. Paper book snapshot (read-only)

From `journal/vivek_bot_book.json` on main (`updated_at`
2026-09-23T11:18:29Z). It is quoted here, not rewritten, and `journal/` is not
staged.

| | Count | W / L | R |
|---|---|---|---|
| **Open** | **30** (NASDAQ 16 · ASX 13 · crypto 1; hc4-1 20 · w3-1 10) | — | **−0.02R** unrealized (+$244.07), $150,000 notional, $22,401 at risk to stops |
| **Closed** | **104** (NASDAQ 52 · ASX 45 · crypto 7) | 42 / 62 | **−7.52R** |
| — by the rules (stop 13 · time 16 · trail 3) | 32 | 10 / 22 | −13.64R |
| — by hand (manual) | 72 | 32 / 40 | +6.12R |

The **last 10 closed** are below. The latest exit date is 2026-09-17, when 16
positions were closed by hand. The book carries no intraday exit time, so the
ten shown are the last ten of those sixteen in book order.

| # | Symbol | Market | Grade | Entry | Exit | How | R | Days |
|---|---|---|---|---|---|---|---|---|
| 1 | CAKE | CRYPTO | A+ | 2026-08-01 | 2026-09-17 | manual | +3.25 | 47 |
| 2 | OKB | CRYPTO | A+ | 2026-07-29 | 2026-09-17 | manual | +2.84 | 50 |
| 3 | EVT | ASX | A+ | 2026-09-16 | 2026-09-17 | manual | −0.05 | 1 |
| 4 | CCV | ASX | A+ | 2026-09-16 | 2026-09-17 | manual | −0.29 | 1 |
| 5 | ACF | ASX | A+ | 2026-09-16 | 2026-09-17 | manual | +0.14 | 1 |
| 6 | ELD | ASX | A+ | 2026-09-10 | 2026-09-17 | manual | +0.03 | 7 |
| 7 | JHX | ASX | A+ | 2026-09-07 | 2026-09-17 | manual | −0.47 | 10 |
| 8 | AIA | ASX | A+ | 2026-09-01 | 2026-09-17 | manual | −0.88 | 16 |
| 9 | HLO | ASX | A+ | 2026-08-31 | 2026-09-17 | manual | −0.53 | 17 |
| 10 | WHI | ASX | A+ | 2026-08-26 | 2026-09-17 | manual | −0.38 | 22 |

Open R and open dollars disagree in sign: −0.02R, but +$244. That is
expected. A position's dollar weight is its stop width, while R divides by
each position's own risk (CLAUDE.md, RESIZE). Read R.

No rule changes.

## 6. Gate

Run locally on the branch; `journal/` and `data/` were never staged.

- **pytest**: green, about 1,500 tests (`rc=0`).
- **JS**: all 24 `test/*.test.js` suites green, read from node's own exit
  code rather than a pipe. `node --check` passes on every `public/js/*.js`.
- **e2e**, all four CI steps:
  - **smoke**: all checks, including the three new coverage checks; zero
    uncaught page errors.
  - **screenshots**: 18 shots, zero overflow.
  - **screenshot-diff**: 0.00% drift on four images against baselines cut
    from `origin/main`.
  - **Lighthouse**: passes, transfer 1.14 MB (< 1.7 MB).

**CLS in this sandbox is bimodal on BOTH trees**, so it is not caused by this
change:

- Branch readings: 0.167–0.407.
- `origin/main` readings: 0.153–0.392.
- Main hits the same 0.392 reading, byte-identical.
- A branch variant with the new freshness text removed also read 0.392.
- Every reading is under the 0.50 budget.
- CI's own figure is in the PR checks.

See the land note below for the CI record.

## Land note

- **Cron fix: Y.** The market is now chosen by the data, not by which cron
  fired. There is a new backstop cron, and a `workflow_run` piggyback on the
  externally dispatched Morning plays runs. Replayed on today's stamps, it
  picks ASX at 06:45 UTC.
- **ASX coverage:** 1,165 of 2,047 downloaded (298 scanned, 867 gated, 0
  reused from a cold cache). The header now says so in counts, plus one
  sentence. NASDAQ is 1,428 of 1,428; crypto is 60 of 86.
- **Crypto: Y.** The file exists, the tab stays, and it now gets the same
  coverage line. The forming-bar observation is flagged above and not
  changed.
- **5.0 last scans:**
  - ASX 21:17 AEST (11:17Z);
  - NASDAQ 07:10 EDT (11:10Z);
  - crypto 11:12Z.

  All three are fresh under the new session + 2h deck rule.
- **Book:** 30 open (−0.02R / +$244, full $150k), 104 closed 42W/62L −7.52R (rules
  −13.64R over 32, hand +6.12R over 72).
