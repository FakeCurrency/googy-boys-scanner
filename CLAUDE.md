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
tests/ + phasemap/tests/ + test/*.test.js   878 pytest + 212 JS — run on EVERY push (test.yml)
journal/               bot book + state files committed by Actions
data_universe/         bundled ticker CSVs (fallbacks)
scripts/               CI-side one-offs and helpers, NOT imported by the engine
  reco_note.py         daily auto-written commentary (reco_note.yml)
  backfill_sector_history.py   replays the engine backwards to rebuild
                       data/sector_history.json (backfill_history.yml)
  resize_book_notional.py      one-off: restates the OPEN book at the current
                       fixed notional. Dry by default, idempotent, --apply
```

## Workflows (current)

| Workflow | Schedule | Does |
|---|---|---|
| test.yml | every push/PR | pytest + 8 JS suites + syntax gate. A new `test/*.test.js` needs its own step here or it never runs — the newest is `journal_stale.test.js` (TOP100 #24) |
| scan.yml | market-hours crons, SEQUENTIAL markets (weekend = crypto-only); `:47` ASX freshness backstop | VIVEK scans + bot book + confluence alert |
| crypto_bot.yml | `:22` + `:52` all days; the `:22` fire skips weekday scan.yml windows (scan.yml already scans crypto then), `:52` is a freshness backstop that skips when fresh | crypto scan + crypto slice of the bot book |
| confluence.yml | daily 08:45 UTC | post-nightly confluence ping (scan group SOLELY owns the dedupe state) |
| backup_book.yml | daily 21:35 UTC | snapshots the bot book + journal state into `backups/` (keep 30) + uploads the set as a 90-day run artifact (off-tree copy, 2026-07-21) |
| reco_note.yml | daily 08:52 UTC | auto-writes `public/data/reco_note.json` from committed scan data (`scripts/reco_note.py`, author "auto"); never overwrites a same-day hand-written Claude note; commentary only, outside every signal path (2026-07-23 — cloud scheduled Claude sessions can't reach the push token, so CI owns the daily cadence) |
| phasemap.yml | nightly 08:30 UTC | PhaseMap + Specs + schema gate (SLIM latest.json + narrations sidecar); no confluence here |
| lens_backtest.yml | weekly Sun | PhaseMap/Specs/VIVEK replays → owns `public/data/vivek_backtest.json` (Insights reads it) |
| vivek_backtest.yml | monthly 1st | LONG-ONLY evidence → `vivek_backtest_longonly.json` ONLY |
| kill_switch.yml | half-hourly 24/7 | loss check on the BOT BOOK per market, open positions re-priced with LIVE quotes (fallback: last-scan marks); broker flatten only if keys set. Hosts the freshness watchdog (scanner/watchdog.py) |
| stop_watcher.yml | 5-min 24/7 | curls /api/tick (cloud watcher for the KV manual journal). Fails the job on a non-200 EXCEPT 503 — see "The tick endpoint" below |
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

### The tick endpoint — and why a 503 must NOT fail the job (2026-07-28)

**`/api/tick` has never run in production.** `TICK_SECRET` is not set in the
Cloudflare Pages project, and `functions/api/tick.js` fails closed: no secret →
**503**, configured-but-unauthenticated → **401**. An unauthenticated probe of
the live URL returns 503, which is proof of the unset secret rather than an
inference. Consequence, and it is the important half of this section: **paper
stops and targets only fire while a chart page is open on some device.** Closing
it is the owner's action — set `TICK_SECRET` in Cloudflare Pages → Settings →
Environment variables and mirror the identical value as the `TICK_SECRET`
GitHub Actions secret. It is a credential; do not generate or handle one.

- **stop_watcher.yml used to exit 0 on every non-200**, so all 288 daily runs
  showed green against an endpoint that had never worked. Nothing else watched
  it, so "green" was the entire signal and it meant nothing. Making it `exit 1`
  fixed the blind spot and immediately created a worse one: a failure email
  every five minutes, for ever, about a fact only the owner can change. An alarm
  that cannot stop ringing gets muted, and a muted channel is how the original
  blackout happened.
- **The split is the fix: one icon was being asked two questions.** 503 means
  *never switched on* (a standing setup gap) — the job stays green and says so
  loudly on the run page via `::warning::` plus a step summary carrying the
  exact Cloudflare steps. Every OTHER non-200 means *was configured and has now
  broken* (401 = secret mismatch between Cloudflare and GitHub, 000 =
  unreachable, 5xx = down) — still `exit 1`, still an email, because that is a
  real regression worth hearing about the moment it happens.
- **401 stays fatal even though it floods too, and the reason is not symmetry.**
  This job is the ONLY caller that holds the secret, so it is the only thing
  that can see a half-configured setup. To the watchdog's deliberately
  anonymous probe a 401 reads as "configured and correctly refusing an
  anonymous caller" = healthy — right for the prober, wrong for the system,
  because `TICK_SECRET` set in Cloudflare and absent in GitHub means the
  watcher still is not running. Make 401 green and that state goes invisible to
  every channel at once, which is the original blackout in a better disguise.
  It is also the one flood that follows immediately from an action the owner
  just took, so it is feedback rather than ambience. **Set both halves in one
  sitting**; the 503 step summary says so at the point of action.
- **Endpoint health moved to `watchdog.probe_endpoints()`**, which inherits the
  same state machine as every other finding: say it once, remind every
  `WATCHDOG_RENOTIFY_HOURS`, and — the thing a red run structurally cannot do —
  **announce recovery**. Three states, deliberately: 401 → healthy (configured
  and correctly refusing an anonymous caller), 503 → WARNING, 200 → **CRITICAL**,
  because an unauthenticated 200 means the watcher is open to anyone who knows
  the URL and every synced journal is reachable through it. That is a security
  finding, not a freshness one.
- **The probe is UNAUTHENTICATED BY CONSTRUCTION and must stay that way.**
  Sending the real secret to "probe it properly" would make the monitor fire an
  extra unscheduled tick every 30 minutes — the monitor would start moving the
  thing it monitors. `tests/test_watchdog.py::test_tick_probe_is_never_sent_a_credential`
  fails if a credential ever reaches the URL.
- **`WATCHDOG_RUNS["stop_watcher.yml"]` is retained but re-scoped** to one
  question — "is the 5-minute cron still firing at all?" — since a green run no
  longer implies a healthy endpoint. Note the two mechanisms cancelled rather
  than complemented each other while this was broken: `probe_runs` stays silent
  when a workflow's latest run FAILED (on the rule that GitHub emailed already),
  so the watchdog was mute for exactly as long as the inbox was flooded.

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
  - **The book WAS a mixture; the owner chose to end it (2026-07-28).** The
    config landed at 03:34 UTC; the scan already running had checked out before
    it, so the six ASX positions filled at 03:39 were still sized by the old
    path (risk-% off a $10,000 equity: ~$300 notional, $35 risk). All 24 open
    rows were legacy-sized, averaging $256 against the intended $5,000 — an open
    book of $6.1k against a $150,000 target, and because each legacy row still
    occupied a full slot, filling the 6 free slots at $5,000 only reached ~$36k;
    the remaining ~$114k was hostage to those rows closing one at a time over
    weeks. Asked to choose, the owner said **resize now**. Run by
    `scripts/resize_book_notional.py` — see the RESIZE section below for what it
    restated and what it refused to touch. The book is now uniformly
    `fixed_notional`, 24 × $5,000 = **$120,000 of the $150,000 cap**.
  - **Dollar P&L is not a like-for-like series across 2026-07-28. R is.** This
    is not a caveat, it is arithmetic: R divides by the position's own initial
    risk, so scaling the size cancels out of it. The live proof from the resize
    — total open P&L went **+$50.84 → −$715.16 while total open R did not move
    off +1.452R**. Not one price changed. Under the old flat-$35 risk every
    position contributed to the dollar sum equally, so the dollar total tracked
    the R total; under fixed notional a position's dollar weight is its STOP
    WIDTH, and the widest stops in the book happen to be the losers. Read R.
  - **`sizing_mode` is recorded on every new book row** (`"fixed_notional"` /
    `"risk_pct"`, empty on hand-built tickets). `size_position` always returned
    it and `decide()` splats it onto the ticket, but `_ticket_to_position` was
    not copying it down, so the book kept the numbers of a sizing decision
    without which mode produced them. Audit field only — nothing reads it to
    decide anything, and it is the one honest way to tell a legacy row from a
    new one once either number is retuned.

### RESIZE — restating the legacy book (2026-07-28, `scripts/resize_book_notional.py`)

- **It is a restatement, not a trade.** Nothing was bought, sold or re-marked.
  Every row kept the price it was actually filled at and the stop it was
  actually given; only the size attached to those prices moved. Restated:
  `units`, `notional`, `risk_usd`, `unreal_usd`, `risk_pct`, `leverage`,
  `sizing_mode`. Frozen and verified byte-identical afterwards across 38 fields
  × 24 rows: `entry`, `stop`, `risk`, `tp1/2/3`, `scale`, `last_mark`,
  `mae`/`mfe`, `exits`, `booked_pct`, `tp*_hit`, and every `_r` field.
- **The 12 CLOSED positions were not touched and must never be.** They are the
  only clean dollar track record the book has — the record of what was really
  held at the size it was really held. `resize_market` does not even iterate
  them, and a test asserts the closed list comes back byte-for-byte.
- **It sizes off `entry - risk`, NOT the row's `stop`.** `stop` trails. BGA had
  already taken tp1 and had its stop moved to breakeven, so sizing off the
  stored stop would divide by a zero distance. `risk` is the per-unit risk
  measured at fill and `entry - risk` reproduces the ORIGINAL stop exactly —
  checked against every un-trailed row in the live book, and kept honest by a
  test that asserts the property on whatever book is in the checkout.
- **The numbers come from `vivek_bot.size_position`**, called with
  `notional_target`, not from a scale factor computed in the script. A restated
  row is therefore sized by the same code that sizes a new one and cannot drift
  from it as the sizer is retuned.
- **DRY BY DEFAULT and idempotent.** It writes nothing without `--apply`, and a
  row already at the size the run would give it is skipped, so a second
  `--apply` is a no-op rather than a compounding rescale. It refuses to write at
  all if a frozen field moved (`AssertionError`, per market), then rebuilds the
  DERIVED combined book + public twin via `vivek_run._write_combined()` and runs
  `verify_books()`.
- **WIDE STOPS — the consequence the notional figure hides, and the reason the
  daily guard is now live.** Seven open rows (XLM 49.8%, MDB 45.5%, AXON 36.7%,
  GLBE 36.6%, WLD 27.6%, RNW 26.1%, ADP 25.3%) have stops beyond the
  `VIVEK_BOT_MAX_STOP_PCT = 25` gate every NEW entry must pass — they were
  opened before it bound them. At a flat $5,000 each now risks $1,266–$2,489,
  i.e. **28–55% of the $4,500 daily loss limit in a single name**. Book-wide,
  open risk went **$840 → $23,500 (15.7% of equity)**. Before the resize a
  whole-market stop-out cost ASX $385, 8.6% of its daily limit — the guard was
  mathematically unreachable and therefore decorative. Now ASX $6,478 (144% of
  it), NASDAQ $12,175 (271%), CRYPTO $4,847 (108%). The guard only halts NEW
  entries for the session, it does not liquidate — but it is armed for the first
  time and will fire. `--max-stop-pct 25` trims those seven back to $1,250 risk
  each (the top of the band `size_position`'s own docstring names) for a
  $111.3k book; it is **OFF by default because trimming is an exposure decision
  and therefore the owner's**, not a migration detail.
- **ASKED AND DECLINED — the seven keep full size (2026-07-28, owner: "Disregard
  the daily stop for the positiosn that have already been taken").** Do NOT run
  `--max-stop-pct`, and do not re-raise the trim as a suggestion. The position
  he took is that these were opened under the rules in force at the time and are
  not to be re-cut because a later gate would have stopped them; the guard
  applies to what is taken NEXT. What he asked for instead was to be TOLD before
  the next one — see the review flag below. The consequence stays exactly as
  measured above and is now a known, accepted exposure rather than an oversight:
  a whole-market stop-out still costs ASX 144% / NASDAQ 271% / crypto 108% of a
  day's guard, and the guard still only halts new entries rather than
  liquidating.
- Tests: `tests/test_resize_book_notional.py` (30). Most of them test what the
  script refuses to do, because that is where its whole defence lives.

### REVIEW FLAGS — "should Claude take this, or should I?" (2026-07-28)

Owner, in the same breath as declining the trim: *"Flag this in the future so i
can verify whether claude or I should take the position or not."* A plan whose
1R loss is a large share of the daily loss guard now arrives marked.

- **A FLAG IS NOT A GATE, and that is the whole design.** `review_flags()` runs
  in `vivek_bot.plan_trade` AFTER every rule has said take; it adds a key and
  returns. Nothing skips, resizes, reorders or closes because of it —
  `evaluate_setup`, the `wide_stop` / `stop_too_tight` / `min_price` /
  `illiquid` / `size_vs_adv` skips and `decide()` are untouched. Changing which
  trades get taken is the owner's call, so the flag tells him there is a
  decision to make and then gets out of the way.
  `tests/test_review_flags.py::test_a_flagged_plan_is_still_taken_because_a_flag_is_not_a_gate`
  pins it, and is the one test in there that must never be "fixed" to agree with
  a future gate.
- **`VIVEK_BOT_REVIEW_DAILY_LOSS_PCT = 15.0`** — flag when `risk_usd` is ≥ this
  % of `daily_loss_limit()` ($4,500 = equity × `MAX_DAILY_LOSS_PCT`). The number
  sits between two others and cannot sensibly be moved without checking both:
  `MAX_STOP_PCT` caps any NEW position at 25% × $5,000 = $1,250 of risk = **27.8%
  of the guard**, so any threshold ≥ ~28 is dead code that would never fire and
  nobody would notice; a typical A+ plan runs a 5–12% stop = $250–$600 = 6–13%.
  15 flags the genuinely wide half without crying wolf. A test asserts
  `0 < threshold < ceiling` so the dead-code case fails loudly. 0 = off.
- **Three hops, because a flag nobody sees is not a flag.** The ticket carries
  `review` (a list, empty when clean); `_ticket_to_position` copies it onto the
  book row; `vivek_run._notify_reviews` pushes it to Discord. Skip any hop and
  the mark survives only in a log line inside a finished Actions run, which is
  not a place a decision gets made.
- **The push is `trade_review`, NOTICE → Discord only, rate limit 0**
  (`VIVEK_BOT_REVIEW_PUSH`, ON — unlike `VIVEK_BOT_NOTIFY_TRADES` beside it,
  which digests every open/close through every channel including email and stays
  off). Fires AFTER `_save_market_book`, so a dry run is silent and nothing is
  announced that failed to persist. One message per run, not per position,
  because the number worth the message is the COMBINED share: three flagged
  opens at 27% each is 80% of the day gone in one run and nobody sums that by
  hand across three notifications. Rate limit 0 for the same per-EVENT-TYPE
  reason as `sector_run` — markets run sequentially in one job, so a limit could
  only ever drop the second market's flagged open, and losing one is the entire
  failure mode.
- **The message says the trade is already TAKEN.** The choice on offer is not
  take-or-skip but *whose position it is*: leave it and it is the bot's at
  $5,000, or close it in the book and take it yourself sized your own way. A
  message that read like a pre-trade approval request would misdescribe what the
  system actually does, and a test asserts the wording.
- **Front end:** `reviewChip` in `public/js/journal.js` (`.jr-review`,
  journal.css) — amber, outlined, no pulse, deliberately quieter than `.jr-flip`,
  which is a live warning that the chart turned. **It renders on CLOSED rows
  too, on purpose**: the flag records what was known at entry, and how the
  flagged trades actually went is the only evidence that will ever say whether
  15.0 is set sensibly. An absent `review` key (row written before flags
  existed) and an empty list (checked, clean) both render nothing but are NOT the
  same thing — do not collapse them by defaulting the key server-side.
- Tests: `tests/test_review_flags.py` (27) + `test/journal_review.test.js` (9,
  which slices the real `reviewChip` out of the shipped file rather than
  mirroring it, so a rename fails the suite instead of silently testing a copy).

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
- **Capacity is stated in BOTH currencies, because they can disagree.** Slots
  and dollars are two different readings of "how full is the book", and the
  panel prints the reconciliation whenever the dollar headroom exceeds the slot
  headroom by more than 25%. That gap was enormous before the resize — 24 of 30
  slots read 80% full while $6.1k of the $150k ceiling read 4% invested,
  because the 24 legacy holdings averaged ~$250 each, sized off the old $10,000
  equity. **The 2026-07-28 resize closed it**: 24 × $5,000 = $120,000, so 80% of
  the slots is now 80% of the notional and the two agree. Keep the divergence
  logic — it is the general case, and the next retune of
  `VIVEK_BOT_POSITION_NOTIONAL` reopens the gap on every row already held. The
  number that answers "how much can I put to work" is still free slots ×
  `VIVEK_BOT_POSITION_NOTIONAL` ($30k today), which `book_state()` publishes as
  `position_notional`. Slots bind first; do not read the notional bar as spare
  room.
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

## Risk arithmetic — TOP100 Tier 1 (2026-07-28)

`TOP100.md` is a 100-item audit of the live tree, ranked not by severity but by
what has to be true before the next fix can be trusted. **Tier 0 (1–12)** was
every alert path that could fire into silence; **Tier 1 (13–24)** is the layer
underneath it — the numbers the guards are computed from. Both are shipped. The
items below are the ones that changed a MODEL rather than a line, so reading the
code without them is misleading.

### The guard measures a WINDOW now, off `day_marks` (#13/#14/#15)

`vivek_guard.session_pnl` charged each open position's **whole-life** unrealised
P&L, plus its whole-life banked partial-exit R, to today — every day, until it
closed. The closed leg had always filtered `exit_date == day`; the open leg had
no day filter at all. The live book said so out loud: crypto read
`session_usd = -1827.46` (41% of a $4,500 daily limit spent before the session
had done anything), while ASX read **+**$692.88, meaning a market holding old
winners could take a catastrophic day and not breach. Both directions are the
same bug — the number was not a day's P&L.

- **The fix is a reference price per window.** Every position records the mark it
  carried into each session in `day_marks`, and P&L is measured from that instead
  of from entry. It telescopes exactly: summing every day's window over a
  position's life returns its total P&L, no more and no less.
- **`_stamp_day_ref` must be called BEFORE `_mark_sanity`, and the order is
  load-bearing.** The reference has to be the PREVIOUS run's `last_mark`, so an
  overnight gap is charged to the session it gapped *into*. Stamp it after the
  mark and the gap lands between the two references and escapes the daily guard
  entirely — precisely the move the guard exists to catch. Written once per day
  and never overwritten (crypto runs 48 scans a day), on unpriced runs too.
  `_DAY_MARK_KEEP = 9` covers the widest window (trailing 7 CALENDAR days) on
  crypto with slack and nearly twice over on ASX/NASDAQ.
- **Direction of the change, plainly:** for a book of older positions the daily
  guard gets LOOSER (it no longer arrives pre-breached) and the weekly guard gets
  TIGHTER on names bleeding for a fortnight (their old losses were being counted
  into the window every day and are now counted once). No position, size, stop or
  rule moved. `open_total_usd` still publishes the whole-life number.
- **#15: it fails CLOSED now.** `if price is None: continue` silently disarmed
  the guard during a data outage — the one moment you most want it armed. An
  unpriced position is re-valued at its own STOP (the floor on what it can still
  cost this window) and, if that is enough to breach, the guard halts new entries
  and says `unmeasured` rather than saying all-clear about a book it cannot see.

### The consecutive-loss breaker had never been able to trip (#16)

`check_consecutive_losses` read `t.get("pnl", 0)`. The bot book writes
`realized_r` / `gross_r` / `cost_r` / `risk_usd` and **no `pnl` at all**, so every
closed trade read as exactly breakeven. Now centralised in
`risk_manager.trade_pnl`, which takes an explicit `pnl` when it is a real number
and otherwise derives dollars from `realized_r × risk_usd`. None-safe and
NaN-safe on purpose: `None < 0` raises (taking down the whole pre-trade check),
and a NaN propagates silently through a sum making every comparison False — it
*disarms* a guard rather than tripping it, which is the worse way to fail.

- **The larger finding, unrepaired because it is a trade decision:** every
  consumer of `risk_manager` (`pre_trade_check`, `circuit_breaker`, `bybit_run`,
  `scaling_advisor`, `performance_report`) is handed the SCALP journal. Nothing
  in `vivek_run.py` or `vivek_bot.py` calls any of it, so **the bot book — the one
  and only track record — is guarded by none of these limits**: not portfolio
  heat, not the drawdown breaker, not the consecutive-loss breaker. Wiring that
  up changes which trades get taken, so it is the owner's call.
  `scripts/health_check.py` now REPORTS what those guards would say about the bot
  book without arming any of them.
- `check_consecutive_losses(journal, notify=False)` exists for exactly that
  reporter: a read-only caller must not push "circuit breaker fired — new orders
  paused" to Discord about a book whose entries were never paused.
- **"The last N" means list order, not exit-date order, and is left that way.**
  Same thing for the scalp journal; not the same thing for the bot book, where
  three markets append into one file. Changing what "consecutive" means changes
  when it fires, so it is noted in the docstring, not silently altered.

### `VIVEK_KILL_SWITCH_BROKERS` — a book breach is per-market, a flatten is not (#17)

`kill_switch.run_standalone` checks the bot book PER MARKET (three limits, three
verdicts) but a broker flatten is ACCOUNT-WIDE: `close_all_positions()` closes
everything on the account and `cancel_all_orders()` kills every resting order. So
an ASX **paper**-book breach called cancel-all + close-all on Bybit — liquidating
a live crypto book that was inside its own limit, over a loss that happened
somewhere Bybit cannot see. Losing money on the ASX is not a reason to sell your
crypto. The map says which broker actually holds each market (`asx: ()` paper
only, `nasdaq: ("alpaca",)`, `crypto: ("bybit",)`); `()` still alerts, logs and
counts as triggered, it just does not reach for an account holding none of the
positions. **A market missing from the dict falls back to the legacy
try-Bybit-then-Alpaca flatten and logs a WARNING** — deliberately the
over-protective default, so a new market added without a line here is noisy
rather than quietly unguarded.

### Mark-sanity runs only while the market is open (#18)

`_mark_sanity` gives a suspicious mark `ACCEPT_RUNS = 3` challenges before it is
accepted. It was called outside the `is_open` gate, so three closed-market scans
burned the entire budget on prices nobody was quoting — and a genuinely bad mark
on the next open was accepted unchallenged.

### Reconcile: stale `units`, and a time floor on closed-PnL matching (#19/#20)

`reconcile_journal` never copied the broker's filled `size` into `pos["units"]`,
so a partial fill booked full-size R. Separately, a vanished position was matched
against the account's last 50 closed-PnL records with **no time filter**, so
re-entering a symbol you had traded before resolved the NEW position against the
PREVIOUS trade's record. The floor is the position's own `opened_ts` minus
`BYBIT_RECONCILE_SKEW_MIN` (5 min) for runner-vs-exchange clock skew. Records
Bybit did not date, and pre-2026 rows with no `opened_ts`, bypass the filter
entirely rather than becoming uncloseable.

### `_restamp` — one writer for `summary` and `guard` (#21)

`close_bot_position` and `_close_time_stop` moved a row from `open` to `closed`,
realised its R and persisted — while `summary` still counted the closed position
as open and `guard` still described a session whose realised total had just
changed. Meant to be brief (the next scan recomputes both), but nothing
guarantees a next scan: close the last position of the day on a Friday and the
book contradicts its own rows all weekend, which is what the dashboard, the
health check and any human reading the file actually see. **Not a trade change** —
`run_market` recomputes the guard itself before `decide()` is ever called, so no
entry decision was ever made against the stale copy. Priced off each position's
own `last_mark` (the same fallback `kill_switch` uses between scans), because a
`price_of` returning None would mark the whole book unpriced and manufacture an
`unmeasured` breach out of a routine close. `notified` is carried forward
verbatim so the recompute cannot re-announce a breach already announced. It never
raises: a stale guard is worse than a fresh one, but a book that failed to save
is worse than both.

### `_side` / `open_count` — the position cap counts ROWS (#22)

**This one touched `scanner/broker/vivek_bot.py`, a file the owner has ringfenced
as never-autonomous. It is flagged, and the argument for shipping it is that it
is monotonically tightening.** The ceiling was tested against `longs + shorts`,
each counted with `==` against a raw `str()`, so any row whose `direction` was not
the exact lowercase string counted as NEITHER — and the book was allowed to run
one position over its own limit per malformed row. `_side()` now reads the field
the way every other consumer means it (stripped, case-folded) and `open_count`
tracks the rows themselves. **Every counter it changes goes UP, never down: no
trade blocked today becomes takeable.** It moves no threshold and touches no
filter, grade or ordering — the caps simply count what they always claimed to.
Pinned by `test_the_direction_repair_can_only_ever_block_more_never_fewer`.
`_side` returns None rather than guessing, because the tree already disagrees with
itself about an unreadable direction (`_exit_hits` defaults LONG,
`_mark_position` defaults SHORT) and a third opinion helps nobody; unclassified
rows are named in a WARNING, not just counted.

### Frame age is measured in the MARKET's calendar, and a cache expires (#23/#24)

- **#23:** `_frame_age_days` used the runner's naive local date, understating ASX
  staleness by a day against `MAX_DATA_AGE_DAYS = 3`. It now takes the market's
  `timezone`, which is what `scan.py` had always done one file over. The tz
  fallback fails CLOSED — an unusable zone must not return 0 ("perfectly fresh").
- **#24, the ceiling:** `merge_with_cache` back-fills tickers Yahoo dropped this
  run from the last-good cache, which is right for the ordinary case. It had NO
  limit, so a ticker Yahoo has not returned since March was handed to the scanner
  as if it were today's bars — its last close published as a live mark, used to
  mark held positions and test their stops. **A fossil price can fabricate a
  stop-out as easily as it can hide one.** `FRAME_CACHE_MAX_AGE_DAYS = 10`,
  generous on purpose (it must clear a multi-day Yahoo gap plus a long weekend;
  only a suspension or delisting should reach it), reported as
  `stats["stale_dropped"]` and a WARNING that NAMES the fossils. Refusing a frame
  can only ever REMOVE a name from the scan, never add one, and a held position
  that loses its frame is counted by `vivek_run`'s `unpriced_runs` (alerting at
  3/10/30) — visibly unpriced beats silently wrong. `0 = off`.
  - `save_frame_cache` refuses to write an EMPTY dict, so a run where Yahoo
    returned nothing leaves the fossil on disk rather than wiping a cache that
    will be useful the moment Yahoo comes back. That guard wins on purpose: the
    fossil is refused at READ time on every later run regardless, so nothing
    reaches the scanner off it and the only cost is disk.
- **#24, the visibility half.** Everything INSIDE the ceiling is still a past
  close presented as a live mark, so the age now travels with the price:
  `scan.py` publishes a sparse `price_age` → `run.py` carries it in the slim
  `<market>_prices.json` → `journal.js` loads it into `scanAge` and badges both
  the manual and the bot `Now` cell (`.jr-stale` — dotted underline, deliberately
  the quietest mark on the page, because the price is still the best number
  available), and the P&L headline counts them.
  - **SPARSE, and the `delete` is the load-bearing half.** Absent means fresh, so
    a healthy ASX run does not write ~2,200 zeros and an old cached page keeps
    working unchanged. But `loadScanMeta` re-runs every three minutes against
    cells that persist, so a name coming back into the scan must actively LOSE
    its key — a badge that never clears is worse than none, because it teaches
    you to read past the ones that are real.
  - The age is computed BEFORE the price snapshot, outside the scoring block. It
    used to sit inside it, so a name that failed `evaluate` published a price and
    NO age — and a held position that has dropped out of the setup list is
    exactly the row that gets priced off cache for weeks.
  - A live quote carries no age BY CONSTRUCTION (it was just fetched), so the
    badge only travels with the scan-snapshot branch of `refreshLive`.
- Tests: `tests/test_data_download.py` (17) + `test/journal_stale.test.js` (13,
  which slices the real helpers out of the shipped file rather than mirroring
  them). **`_ohlc()` in the download tests defaults to TODAY** — it used to be a
  hard-coded past date, harmless until the ceiling existed and then a trap that
  made every reuse test silently exercise the fossil path instead.

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
python -m pytest -q                      # full gate (878 tests)
node test/risk_manager.test.js           # + 7 more JS suites, 212 total; see test.yml
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
