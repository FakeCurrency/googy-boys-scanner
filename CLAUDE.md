# Vivek 5.0 — CLAUDE.md

This file is read automatically at the start of every Claude Code session.
Read it fully before touching any code. (Rewritten 2026-07-10 — the previous
version predated the three-lens pivot and half its claims were stale.)

---

## What this project is

A **three-lens trading scanner** + paper-trade journal + execution bot
(paper today, Bybit-gated live path built). Owner: Vivek (Melbourne,
Australia). Brand name everywhere: **Vivek 5.0** — never "Googy Boys
Scanner", never "Vivek's Beta Scanner" as the primary name ("BETA SCANNER"
as a subtitle under the wordmark is fine).

**The three lenses** (see ROADMAP.md for the honest project state):

1. **VIVEK** (`scanner/vivek.py` + `scan.py`) — the core lens. Price
   *reacting* at its 200-SMA on Weekly / 3-Day / Daily(H4-proxy) levels.
   Grades A+/A/B+/WATCH; per-timeframe plans (entry/SL/TP1-3); three entry
   types (reclaim / retest / break); armed vs watching.
2. **PhaseMap** (`phasemap/` package) — the trap lens. Liquidity sweep →
   displacement, zone-based (zones are ALWAYS bands, never single prices).
   **The owner's master spec doc is the single source of truth — NEVER
   change detection maths or zone definitions without asking him.** Bump
   `RULESET_VERSION` in `phasemap/config.py` on ANY parameter change.
   Deterministic output; no LLM anywhere in the scan path.
3. **Specs** (`scanner/spec.py` via `spec_run.py`) — the discovery lens.
   Sub-$0.50 names breaking out of a base on a ≥3× volume spike. Its own
   backtest says it's a shortlist generator, NOT an entry system.

**Multi-lens confluence** is the headline feature: direction-aligned 2+/3-lens
agreements get banners everywhere, Discord pings (`scanner/confluence_alert.py`,
triples mention @here; state-deduped), a permanent ALERTS page log, and the
★ MY NAMES page.

---

## Tech stack

| Layer | What |
|-------|------|
| Scanner engines | Python (`scanner/`, `phasemap/`) — run in GitHub Actions |
| Frontend | Vanilla JS + CSS — static site on **Cloudflare Pages** (`public/`), iOS-style dark theme, PWA with service worker |
| Backend API | Cloudflare Pages Functions (`functions/api/*.js`) — CF **Workers runtime, NOT Node** (no `require`, no fs; env via `context.env`) |
| Scheduler | GitHub Actions cron (`.github/workflows/`) |
| Data source | `yfinance` (pinned) — free, ~15 min delayed, survivor-biased history. Production-grade provider (EODHD/Norgate) is an open owner decision |
| Broker | **Bybit** USDT perps: client/bracket/reconcile/kill-switch BUILT + tested, paper/testnet only, live double-gated. IBKR for ASX later |

---

## Repository layout (current)

```
scanner/               VIVEK + Specs engines, bot, alerts
  config.py            ALL tunable constants — never hardcode magic numbers
  vivek.py             VIVEK 5.0 engine (levels W/3D/D, plans, grading, narrative)
  scan.py              scan_vivek_market → public/data/<m>_vivek.json
  run.py               CLI: python -m scanner.run [--market ...]; publishes bot_rules.json
  spec.py + spec_run.py    Specs lens (asx+nasdaq) → <m>_spec.json
  confluence_alert.py  multi-lens Discord pings + ALERTS page history log
  vivek_backtest.py    walk-forward replay (1D/3D/1W, level_tf cohorts)
  vivek_journal.py     RETIRED as a journal (2026-07-09) — module kept: the
                       backtester + bot runner import its trade primitives
                       (notify/alerts/pulse + broker paper_run/bracket_order/
                       reconcile DELETED 2026-07-20 — see git history)
  universe.py          ASX full (~2,000) · NASDAQ Global Select (~1,430) · crypto top-100+extras
  sectorbreadth.py     HORIZON — sector participation + rotation (see below).
                       REPORT-ONLY: it never touches which trades get taken.
  regime.py            REGIME — participation, index-vs-median divergence,
                       sector relative strength, basing counts. Also REPORT-ONLY.
  broker/              vivek_bot.py (decision engine: A+ only, 30 open TOTAL
                       across all markets, one/symbol, 3/sector PER MARKET), vivek_run.py (paper book),
                       bybit_client/bybit_bracket/bybit_reconcile, kill_switch,
                       circuit_breaker, pre_trade_check, ...
phasemap/              PhaseMap package (engine/narrate/output/backtest/tests)
public/                the site (see "Frontend rules")
functions/api/         scan.js + close.js (Actions dispatch, KV rate-limited),
                       journal.js (KV sync store), price/quote/tick proxies
tests/ + phasemap/tests/ + test/*.test.js   670 pytest + 190 JS — run on EVERY push (test.yml)
journal/               bot book + state files committed by Actions
data_universe/         bundled ticker CSVs (fallbacks)
scripts/               CI-side one-offs and helpers, NOT imported by the engine
  reco_note.py         daily auto-written commentary (reco_note.yml)
  backfill_sector_history.py   replays the engine backwards to rebuild
                       data/sector_history.json (backfill_history.yml)
```

## Workflows (current)

| Workflow | Schedule | Does |
|---|---|---|
| test.yml | every push/PR | pytest + JS tests + syntax gate |
| scan.yml | market-hours crons, SEQUENTIAL markets (weekend = crypto-only); `:47` ASX freshness backstop | VIVEK scans + bot book + confluence alert |
| crypto_bot.yml | `:22` + `:52` all days; the `:22` fire skips weekday scan.yml windows (scan.yml already scans crypto then), `:52` is a freshness backstop that skips when fresh | crypto scan + crypto slice of the bot book |
| confluence.yml | daily 08:45 UTC | post-nightly confluence ping (scan group SOLELY owns the dedupe state) |
| backup_book.yml | daily 21:35 UTC | snapshots the bot book + journal state into `backups/` (keep 30) + uploads the set as a 90-day run artifact (off-tree copy, 2026-07-21) |
| reco_note.yml | daily 08:52 UTC | auto-writes `public/data/reco_note.json` from committed scan data (`scripts/reco_note.py`, author "auto"); never overwrites a same-day hand-written Claude note; commentary only, outside every signal path (2026-07-23 — cloud scheduled Claude sessions can't reach the push token, so CI owns the daily cadence) |
| phasemap.yml | nightly 08:30 UTC | PhaseMap + Specs + schema gate (SLIM latest.json + narrations sidecar); no confluence here |
| lens_backtest.yml | weekly Sun | PhaseMap/Specs/VIVEK replays → owns `public/data/vivek_backtest.json` (Insights reads it) |
| vivek_backtest.yml | monthly 1st | LONG-ONLY evidence → `vivek_backtest_longonly.json` ONLY |
| kill_switch.yml | half-hourly 24/7 | loss check on the BOT BOOK per market, open positions re-priced with LIVE quotes (fallback: last-scan marks); broker flatten only if keys set. Hosts the freshness watchdog (scanner/watchdog.py) |
| stop_watcher.yml | 5-min 24/7 | curls /api/tick (cloud watcher for the KV manual journal) |
| close_position.yml | manual | journal_type=bot closes a BOT BOOK position (the real track record); swing/scalp = legacy journals. Auto re-dispatches itself (max 3) if the scan mutex evicts it — 2026-07-28, see below |
| test_alerts.yml | manual | alert-path self-test: forces one test message through every configured channel (`watchdog --test-alert`); run after any alert-secret change, read the job summary |
| backfill_history.yml | manual | replays the real engine backwards to rebuild `data/sector_history.json` (`scripts/backfill_sector_history.py`). `dry_run` defaults TRUE — run that first, the printed post-mortem IS the deliverable. In the `scan` group because it writes a file every scan also writes. Not scheduled: once the gap is filled there is nothing left to fill (2026-07-28, see HORIZON → BACKFILL) |

(Table refreshed 2026-07-20 — discord_digest.yml deleted; notify/alerts/pulse/
paper_run/bracket_order/reconcile modules deleted.)

**The `scan` mutex is JOB-scoped, deliberately (2026-07-28 — REFINEMENTS #108,
#109).** scan.yml, crypto_bot.yml and close_position.yml share concurrency
`group: scan` so two writers can never touch the paper book at once
(load-bearing: the 30-position cap is global, so concurrent writers could each
read "23 open" and both open). That group sits on the *scan* / *crypto* / *close*
JOBS, not at workflow level. GitHub keeps only ONE pending run per group and
cancels the previously-pending one, so workflow-level scoping put the cheap gate
jobs in the same queue — every `:47` ASX backstop was being evicted by the `:52`
crypto arrival five minutes later, before it could probe, and a manual close
dispatched behind a running scan was deleted outright, run and all. Do not move
these blocks back up to workflow level; `tests/test_workflow_mutex.py` fails if
you do.

**close_position.yml re-dispatches itself if evicted** (owner decision). Because
the mutex is on the job, an eviction now cancels that job and leaves the run
alive, so the `redispatch` job — deliberately OUTSIDE the group — can see it and
`gh workflow run` the same inputs again. Capped at 3 attempts via the `attempt`
input; only fires when the close executed zero steps (an eviction never starts
the job, whereas a human Cancel leaves finished steps behind); waits for the
group's pending slot to clear first so the retry does not evict its evictor.

**Silent-failure protection (2026-07-20, Phase 5):** the committing workflows
(scan/crypto_bot/phasemap/backup_book) run `scripts/assert_staged.sh` after
staging — a scheduled run that stages none of its must-change outputs FAILS
loudly instead of finishing green (the Phase 3 staging bug ran green 5x while
committing nothing). `scanner/watchdog.py` (hosted in kill_switch.yml +
crypto_bot.yml) additionally probes content timestamps + GitHub run history
and alerts on staleness with strict noise rules (first / 6h reminder /
recovery; red runs are GitHub's to email about). Thresholds: config
WATCHDOG_*. When adding a workflow that commits data, give it an
assert_staged call and a WATCHDOG_RUNS entry.

---

## Journals & track record — IMPORTANT

- **The bot book is the ONE AND ONLY track record.** Layout v2 (2026-07-20):
  CANONICAL per-market files `journal/vivek_bot_book.<market>.json` (a market's
  run can only write its own file — cross-market clobber impossible by
  construction); `journal/vivek_bot_book.json` + the public twin are a DERIVED
  combined view (same old schema; regenerate with
  `python -m scanner.broker.vivek_run --rebuild-combined`; audit with
  `--verify` — the scan/close workflows run it as a failing gate). A+ only (grade_raw,
  unsmoothed), **max 30 open across ALL markets combined** (owner, 2026-07-28 —
  `VIVEK_BOT_MAX_OPEN_TOTAL`; the per-market cap is set equal to it so one market
  CAN hold the whole book, and `vivek_run._open_elsewhere` counts the sibling
  market files before each decision — fail-closed if one is unreadable), one per
  symbol, **3 per sector PER MARKET** (not global — see below), daily+weekly loss
  guards, manual close via close_position.yml journal_type=bot.
- **The correlation cap is the only limit that is still per-market**
  (REFINEMENTS #113, owner decision). Positions (30), notional ($150,000) and
  one-per-symbol are all cross-market; `decide()` seeds `sector_counts` from the
  single market's `open_book`, so 3 ASX financials + 3 NASDAQ financials is six
  of one real sector with every check passing. Not repaired — tightening what
  gets taken is the owner's call — but `sectorcache.global_sector_load` logs a
  per-scan WARNING naming any sector over the cap once all markets are counted.
  The fix, if wanted, is a `sectors` Counter on `_book_elsewhere` plus a
  `sector_elsewhere` kwarg, mirroring the two ceilings exactly.
- **`data/sector_map.json` IS A SIGNAL PATH** (2026-07-28, owner-authorised —
  REFINEMENTS #38). It used to be display-only, which is why the 3-per-sector
  cap never bound on NASDAQ: `universe._fetch_nasdaq` has no sector column, rows
  with no sector are exempt from the cap, and 0 of 269 scanned rows carried one.
  `vivek_run.run_market` now merges the cache into the rows `decide()` sees
  (`sectorcache.enrich_rows`, straight after the ADV enrichment), and
  `sectorcache._scan_symbols` seeds the fetch list from the OPEN BOOK first
  (rank `-1`) so held sector-less names — which had dropped out of the scan and
  could never acquire a sector — get backfilled. **The book back-fill has three
  sources, in order: today's scan rows → this market's UNIVERSE file → the
  cache** (2026-07-28). The universe leg was missing and it is the only source
  with full coverage — a scan lists the ~336 ASX names that set up, the universe
  carries a sector for all 2,212 — which is why BGA/FPH/AIA sat sector-less
  through every scan while occupying slots and, blank, staying exempt from the
  very cap they should have been filling. **Enrichment only ever writes
  into a blank field:** a sector shipped with the universe (all ASX rows carry
  GICS) wins, and an empty/unreadable cache is a no-op, never a clear. A wrong
  sector here now changes which trades get taken, so treat cache edits as trade
  changes. Crypto is still rescued by synthetic `crypto-major`/`crypto-alt`
  buckets. `decide()` publishes `summary["sector_coverage"]`; expect ~1.0.
  **Open (REFINEMENTS #112, owner decision):** SUN and AFG hold Yahoo-style
  `Insurance` / `Financial Services` where the ASX universe says `Financials`,
  so the cap reads three buckets where there is one. Reported by
  `sectorcache.diverging` as a scan warning; NOT repaired, because overwriting
  a non-blank sector is a trade change.
- **Position sizing is FIXED NOTIONAL** (2026-07-28, owner: "5k position moving
  forward on each 30 stocks and a cap of 150k"): `VIVEK_BOT_POSITION_NOTIONAL`
  = $5,000 a position, `VIVEK_BOT_MAX_PORTFOLIO_NOTIONAL` = $150,000 (the dollar
  twin of the 30-slot cap), `VIVEK_BOT_ACCOUNT_EQUITY` = $150,000. Equity no
  longer sizes positions — it scales the loss guards and the leverage ceiling,
  which is why it had to move with the book. **The dollars RISKED now vary with
  the stop distance** (~$50–$1,250, typically $250–$500); position COUNT is the
  risk dial, not position size. Do not "fix" that by re-clamping `risk_pct` in
  fixed mode — see `tests/test_fixed_notional.py`. Set
  `VIVEK_BOT_POSITION_NOTIONAL = 0` to restore the old 0.35%-risk path exactly.
  The `open_book` projection `run_market` hands `decide()` carries `notional`
  (2026-07-28): `decide()` seeds `open_notional` from it, so omitting the field
  made the $150,000 ceiling count every market's exposure EXCEPT the one it was
  deciding for. Latent while every position is $5,000 and the 30-slot cap binds
  first at exactly $150,000 — but it is a risk cap reading a number it believes
  is complete, so it is fixed rather than noted.
- The old "track-record journal" (every armed A+/A, every timeframe, no cap —
  it hit 203 open / 12 closed) was **retired 2026-07-09** along with the
  dashboard strip and TRACK page. Do not resurrect it as a headline number.
- Manual journals ("Me" side) live in browser localStorage, synced via
  Cloudflare KV (`gbs-sync.js`, `/api/journal?code=...`). The unified
  watchlist (stars from all lenses) lives INSIDE that store
  (`watchlists`, keys `<lens>:<market>:<TICKER>`, tombstoned un-stars).

---

## HORIZON — the rotation surface (2026-07-28)

**Why it exists.** Owner post-mortem: ASX consumer discretionaries ran for four
weeks while the market was "SHIT to trade", and the book held none of them. Two
separate failures let that happen and the module addresses both.
(1) The only published sector number was a RAW SETUP COUNT — Materials lists 766
of the ASX's 2,212 names and out-counts everything on every scan regardless of
what it is doing, so the count could never surface a 104-name sector waking up.
(2) The book sat at its 10-slot ceiling for 20 straight sessions, so nothing
could have been taken even had it been seen. A leaderboard alone would have been
half an answer; the panel therefore always shows CAPACITY beside the leaders.

**REPORT-ONLY, deliberately.** `sectorbreadth` is imported by `scanner/run.py`
only, never by `broker/`. It reads the book; nothing reads it back. Every
question it raises — raise the 3-per-sector cap? tilt the ranking? page on
"leading sector, zero held"? — changes which trades get taken and is therefore
the owner's call, not a refactor. Keep it that way.

- **`scanner/sectorbreadth.py`** — `compute()` per market, `update()` publishes.
  Participation rate = A+/A setups ÷ names in the sector; ranked descending by
  rate, then by A+/A count. `run.py` fills `breadth_inputs[market]` only for
  `("asx", "nasdaq")`, so a crypto-only weekend run never calls `update()`.
- **The denominator is NOT the same on both markets** (`names_source`). ASX
  divides by names LISTED in the sector (the universe carries GICS for all
  2,212) — a true participation rate. NASDAQ's symbol file ships no sector
  column, so it divides by the names a scan has CLASSIFIED so far via
  `data/sector_map.json`. Ranking within NASDAQ is sound; the LEVEL is not
  comparable to ASX and drifts down as coverage fills in. The page says so.
- **Unranked rows are published, never ranked, and always carry a reason.**
  `real: false` = not a sector (Unclassified/None — 389 ASX names; on the first
  run that bucket topped the board at 23.4%, the exact failure the module
  exists to correct wearing a different hat). `thin · N` = under
  `SECTOR_BREADTH_MIN_NAMES` (15). `off-directory` = held under a label the
  market's directory does not use, so there is no listing count to divide by —
  this is REFINEMENTS #112 surfacing on the page (ASX `Financial Services` and
  `Insurance` each hold 1 under Yahoo-style labels, and the 3-per-sector cap
  counts them as separate buckets). Bars scale off RANKED rows only.
- **Capacity is stated in BOTH currencies, because they disagree.** 24 of 30
  slots used reads 80% full; $6.1k of the $150k notional ceiling reads 4%
  invested. Both are true — the 24 legacy holdings average ~$250 each, sized off
  the old $10,000 equity. The number that answers "how much can I put to work"
  is free slots × `VIVEK_BOT_POSITION_NOTIONAL` ($30k today), so `book_state()`
  publishes `position_notional` and the panel prints the reconciliation whenever
  the dollar headroom exceeds the slot headroom by more than 25%. Slots bind
  first; do not read the notional bar as spare room.
- **Coverage is stated, not hidden.** 91 of 216 ASX A+/A sit in names carrying
  no sector at all, so the footnote prints what share of the day's A+/A the
  ranked sectors actually account for whenever the off-rank share tops 10%.
  "Leading sector" is a claim about the part of the tape this board can see.
- **`data/sector_history.json` is the only long sector memory in the system**
  (the 7-day PhaseMap archive was too short to reconstruct July after the
  fact). One row per market per day, capped at 2,000; feeds the trend column.
- **The STREAK is the number that separates a shrug from a miss in progress**
  (2026-07-28). "Consumer Discretionary is third and you hold none" is a fact
  you can wave off once; "for the 19th session running" is not the same
  sentence, and the gap between them is the entire four weeks.
  `unheld_streak()` counts consecutive most-recent SESSIONS a sector led on
  rate while the book held zero of it, rebuilt from history rather than kept as
  a counter so a re-run, a backfill or a skipped day cannot corrupt it. Rows
  exist only for days the scan ran, so a weekend does not break a run.
  `append_history` is called BEFORE `horizon()`, so a first-day leader reads 1.
  - **A run stops at a session whose `held` is null**, not just at a held
    position. Null means reconstructed from before the bot book existed, where
    "held nothing" cannot be told apart from "no book to hold anything" — so the
    streak reports only the part of the run we can stand behind. See BACKFILL.
  - The reconstruction MUST re-apply all three of `compute()`'s exclusions —
    `_NOT_A_SECTOR`, `MIN_NAMES`, rate > 0 — because history stores every
    bucket that had listed names. Today's real ASX row is led by "Unclassified"
    at 91/389 = 23.4%, above every genuine sector. Omitting the `_NOT_A_SECTOR`
    test (the version this shipped with, caught pre-commit) hands it rank 1
    every day, pushes the real third-place sector out of the top three, and
    reports a streak of ZERO for the one sector the surface exists to catch —
    silently, and only for the sector that mattered. Tie-break is
    `(-rate, -ag, name)`, identical to the live sort, so a reconstructed rank
    can never disagree with the rank that was displayed.
- **`SECTOR_BREADTH_RUN_ALERT` (5 sessions) is when the surface stops
  describing and starts shouting**, and it widened `expand`. The old rule fired
  only when the book could not act; a fortnight of leading-with-nothing-held
  and 30 slots FREE is the worse reading — being capped out is at least an
  explanation — and it now raises the banner too. Because both states raise it,
  `horizon()` publishes `expand_why` and the banner prints that instead of the
  old hard-coded "it can barely act", which was a lie in the new case. The
  sustained note is `notes.insert(0, ...)` on purpose: the dashboard strip
  renders only `notes[0]`. Still report-only — it changes the volume, never the
  trades.
- **Both files must stay in `scan.yml`'s scoped `SHARED` staging list.**
  `public/data/sector_breadth.json` is shared, not per-market: a run recomputes
  only the market it scanned and MERGES it in, so an ASX-only run must stage
  the whole file or the NASDAQ block it just carried forward is dropped. Leave
  the history file unstaged and every session starts from day one forever.
- **Front end:** `public/js/horizon.js` + `public/css/horizon.css`, one
  vocabulary in two skins — the full board `#horizon-panel` on sectors.html
  (follows the market buttons) and the compact strip `#horizon-strip` on
  index.html. Both hide themselves silently if the JSON is missing, so a
  market that has never run degrades to nothing rather than to an error.
- Constants: `SECTOR_BREADTH_*` in `scanner/config.py`.
- **The sustained-run alarm pushes to Discord** (2026-07-28, owner decision —
  `sectorbreadth.notify()`). A dashboard only works on the days you open it, and
  the raw ingredients of the July rotation were on the page for four weeks while
  the miss happened anyway. `notify()` fires the first time a sector enters
  `horizon()["sustained"]`, then at most once every
  `SECTOR_BREADTH_RUN_ALERT_REPEAT_DAYS` (7) for as long as the run lasts.
  - **Its own `NOTICE` severity tier**, routed to `["discord"]` only. INFO is
    silent and WARNING would file a market observation beside kill switches and
    order failures at the same volume. Nothing is *wrong* when this fires.
  - **The ping memory lives in `data/sector_history.json`** under
    `hist["alerts"]["sector_run"]`, NOT in `journal/alert_state.json`. The
    router's own state file is not in scan.yml's staging list, so it dies with
    the Actions container — every scan would read "never pinged" and re-fire,
    which for a run that lasts weeks means a ping every scan for a fortnight.
    The history file is committed by the same step that commits the streak the
    alert is derived from, so the memory and the number can never disagree about
    what day it is.
  - **`ALERT_RATE_LIMITS["sector_run"] = 0` on purpose.** The router's limit is
    per EVENT TYPE and scan.yml runs markets sequentially in one job, so ASX
    firing would silently swallow NASDAQ. `notify()` owns the dedupe per market
    AND per sector, which is strictly tighter everywhere it differs.
  - A sector that stops leading, or that the book finally buys, is FORGOTTEN —
    scoped to the market in hand, so a crypto-only weekend cannot wipe ASX
    memory. Report-only: it changes what gets SAID, never what gets taken.

### BACKFILL — filling the memory backwards (2026-07-28)

`scripts/backfill_sector_history.py` + `.github/workflows/backfill_history.yml`.
History only started being written on 2026-07-28, a week after the ASX Consumer
Discretionary rotation it exists to catch had already run: until the gap is
filled the streak can only ever say "1" and the trend column has nothing to
trend. The script replays the REAL engine — `evaluate` → liquidity gate →
`score_and_grade` → hysteresis → `build_plans` → `gate_grade`, scan.py's order,
on frames truncated to each session — and writes rows marked `"r": 1`.

- **UNKNOWN IS NOT ZERO — the one rule the whole thing rests on.** The bot
  book's earliest entry is 2026-06-28; before that, whether the book held a
  sector is not merely unrecorded but *unknowable* — there was no book. Those
  `held` cells are written `null`, never `0`, and **`unheld_streak` now stops at
  a null exactly as it stops at a held position** (`sectorbreadth.py`). Counting
  through a null the way we count through a zero would have manufactured streaks
  of up to six months the first time a backfill landed and fired the Discord
  alarm on every sector at once — the one failure mode that costs that number
  its credibility permanently.
- **Honest about its own error bars.** REAL: the per-name grade, the liquidity
  gate recomputed per session, the sector denominator from the same universe
  file. KNOWN WRONG and bounded: survivorship (today's universe, so delisted
  names are missing), and hysteresis chains once per DAY where live chains once
  per SCAN — which skews A+/A LOW, i.e. wrong in the conservative direction.
  The first `--warmup` sessions are computed then DISCARDED because their
  hysteresis is cold. The still-forming trailing bar is dropped using
  `_bar_is_forming` with **market-local** time (it compares the wall clock
  against the market's own close, so handing it UTC would misjudge every ASX
  session).
- **The replay never writes the repo.** `--rows-out` parks the reconstruction in
  `$RUNNER_TEMP`; `--merge-only` folds it into the history file as it stands
  now. That split is what makes the push retry safe: each attempt re-merges the
  parked rows against a freshly-reset `origin/main`, so a scan that landed
  mid-replay is folded in rather than reverted, and attempt 1 and attempt 5 run
  identical code. Real rows always beat reconstructed ones; a re-run is
  idempotent.
- **Manual only (`workflow_dispatch`), `dry_run` defaulting TRUE**, in the
  `scan` concurrency group. Not scheduled because it is not maintenance — the
  live scan writes today's row every session, so once the gap is filled there is
  nothing left to fill, and a re-run costs ~25 min of a runner for a result that
  does not change. Run the dry pass first: the printed post-mortem (which
  sectors led, for how long, between which dates) is the actual deliverable; the
  file is what keeps it true tomorrow.

---

## REGIME — is the index telling the truth? (2026-07-28)

The owner's framing: *"this scanner and this scanner alone is INSUFFICIENT."*
HORIZON answers "which sector is running"; REGIME answers the question that sits
underneath it — whether the index level is representative of the names in it,
and which sectors are outperforming rather than merely numerous. Built to say,
in one line, the thing the scanner could not previously express: *the index is up
while the median name is down.*

- **`scanner/regime.py`** — `compute(market, frames, universe, bench=...)` per
  market, `publish()` merges and writes `public/data/regime.json`, `report()`
  prints. Computed INSIDE `run.py`'s market loop because it reads `deep_frames`
  (five years of bars for every name, the largest object in the scan) and that is
  the only point at which they exist; only the finished block travels out.
- **Four things, one payload.** (1) Participation — % above the 200-day and the
  50-day, net highs-minus-lows. (2) Divergence — benchmark return vs the MEDIAN
  name's return over the same window; `REGIME_DIVERGENCE_MIN` (2%) is where the
  gap is called wide and the page says the index is being carried by its biggest
  names. (3) Relative strength — each sector's median return against the market
  median, with a top-3 streak so a one-day leader reads differently from a
  thirty-session one. (4) Basing/coiling counts — names compressing but not yet
  triggering, which is the pre-setup population a grade filter cannot show.
- **Benchmarks are per market** (`REGIME_BENCHMARK`: ASX `^AXJO`, NASDAQ
  `^IXIC`). Crypto has no index worth the name here and is not computed.
- **REPORT-ONLY, same as HORIZON.** Nothing in `broker/` imports it. Whether a
  narrow tape should change position sizing or the ranking is the owner's call.
- **Front end:** `public/js/regime.js` + `public/css/regime.css`, two skins from
  one vocabulary — `#regime-panel` on sectors.html (under the HORIZON board) and
  `#regime-strip` on index.html. Both hide silently when the JSON is absent, so
  the surface is invisible until the first scan writes it.
- `public/data/regime.json` is in scan.yml's SHARED staging list (merged
  per-market like sector_breadth.json). It has no history file — it recomputes
  six months from bars every run, so there is nothing to lose.
- Constants: `REGIME_*` in `scanner/config.py` (note: the older
  `REGIME_ADX_THRESHOLD` / `REGIME_RANGING_*` trio belongs to the bot's
  trend/range filter and is unrelated).

---

## Development rules

1. **Git first, always:** other sessions + CI push constantly. Before ANY
   commit: `git stash -q -u; git pull -q --rebase origin main; git stash pop -q`.
   `journal/alert_state.json` gets polluted by local test runs —
   `git checkout -- journal/alert_state.json`, never commit it.
2. **Version bump:** every edit to ANY `public/js/*.js` or `public/css/*.css`
   bumps its `?v=` in every referencing HTML page. Don't record the numbers
   in docs — read them from the HTML.
3. **Config first:** any new threshold/constant goes in `scanner/config.py`
   (or `phasemap/config.py`) before use. Bot rule constants are published to
   `public/data/bot_rules.json` each scan — the dashboard reads them; never
   hardcode the numbers twice (bot.js warns on drift).
4. **PhaseMap spec is law** (see above). Schema note: published
   `latest.json` is SLIM (narrations in `narrations.json` sidecar); the
   dated snapshot keeps the full spec schema.
5. **Tests gate everything:** `python -m pytest -q` (+ `node test/*.test.js`)
   must be green; CI runs them on every push.
6. **Pinned deps:** `requirements.txt` pins the trade-path packages exactly.
   Bump deliberately (edit pin → pytest → push), never loosen to `>=`.
7. **Atomic writes** for any journal/state JSON (temp + `os.replace`).
8. **Push to `main`** — Cloudflare Pages deploys it; feature branches don't.
9. **ASCII-only prints** in scanner code — Windows consoles are cp1252 and
   choke on arrows/em-dashes.
10. **CF Functions** are Workers runtime: no Node builtins; KV binding
    `JOURNAL_KV` backs sync + the scan/close rate limits.

## Frontend rules

- iOS-style dark theme: tokens in `styles.css :root` (system-blue/green/red,
  radius 18/14/10, soft shadows, frosted top bar). Old terminal values are
  documented in the :root comment for revert.
- One timestamp convention: **Melbourne on screen**, market-local/UTC in
  tooltips (`PM.fmtMelb`).
- Preview: launch config "fib-scanner" (port 8765). `preview_screenshot`
  TIMES OUT on canvas-heavy pages (chart) — verify via `preview_eval` DOM
  checks instead.
- PWA: `sw.js` (network-first for `data/` + HTML, cache-first for `?v=`
  assets; never caches `/api/`). Bump its `CACHE` name on breaking changes.

---

## Secrets

Set: `DISCORD_WEBHOOK_URL` (private #alerts, triples-only via
`DISCORD_CONF_MIN_LENSES`), `BYBIT_*` (testnet), `ALPACA_*` (legacy),
`TELEGRAM_*`, `GH_DISPATCH_TOKEN` (in Cloudflare, not GitHub).
**Pending owner:** `GBS_SYNC_CODE` (activates watchlist-aware pings),
data-provider key, Cloudflare Access.

---

## Running locally

```bash
pip install -r requirements.txt
python -m pytest -q                      # full gate (670 tests)
python -m scanner.run --market asx       # VIVEK scan
python -m phasemap.run --market asx      # PhaseMap scan
python -m scanner.spec_run --market asx  # Specs scan
python -m scanner.vivek_backtest --market asx --limit 10 --period 3y
python serve.py                          # local frontend
```
Local venv: `.venv/Scripts/python.exe` (3.14; CI is 3.12).

**Repo home (2026-07-21): `C:\\dev\\googy-boys-scanner`** — moved OFF OneDrive
after a sync rollback corrupted the working tree + git index mid-session.
Never keep this repo inside a OneDrive/Dropbox-synced path. (The old copy at
Documents is RETIRED; the local `.venv` must be recreated in the new home
when needed: `pip install -r requirements.txt`.)
