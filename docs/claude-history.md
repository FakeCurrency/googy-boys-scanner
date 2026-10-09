# CLAUDE.md history — write-ups of code that no longer exists

Moved out of CLAUDE.md verbatim, so the always-loaded file carries current
rules only. Each section's lessons still stand; the code it describes is
gone. `git log -S` on any symbol below finds the removal commit.

---

<!-- moved from CLAUDE.md: The tick endpoint (`/api/tick`, `stop_watcher.yml`) -->

### The tick endpoint — and why a 503 must NOT fail the job (2026-07-28) — HISTORY ONLY

> **`/api/tick` and stop_watcher.yml were REMOVED 2026-09-21** with the manual
> journal they watched (see MY JOURNAL). Everything below is the record of a
> blackout and of a verdict taxonomy worth re-reading BEFORE writing the next
> polled endpoint — nothing in it describes code that still exists.

**2026-08-27 — THE 5-MINUTE CRON WAS NEVER DELIVERING 5 MINUTES.** A run
audit measured stop_watcher at ~31 STARTS/day against its */5 cron (gaps
20–115 min — GitHub coalesces busy repos' schedules; kill_switch showed the
same shape at ~27/48). So the effective stop/target latency was ~46 min
average, ~2h worst. Fixed in-repo, twice over: (1) each stop_watcher run is
now a 4-tick LOOP at 5-min spacing — GitHub throttles how often runs START,
not what a run does while alive — and (2) kill_switch.yml + crypto_bot.yml
fire one best-effort piggyback tick per run, because the union of interleaved
schedules is what restores cadence (combined ≈ every ~8 min). Deliberately
NOT a resident self-chaining loop (cron-as-a-service invites harder
throttling). For a guaranteed 5-min beat the honest fix remains an external
cron (Cloudflare Worker cron trigger / any uptime pinger) hitting /api/tick
with the bearer secret — owner's infrastructure, owner's call. The piggyback
steps are `continue-on-error` with no fatal branch (pinned): stop_watcher
owns every verdict, and a dead beat must never block the kill switch.

**`/api/tick` IS LIVE (corrected 2026-08-18).** The owner set `TICK_SECRET` in both halves at some point after this section was written, and the endpoint proves it: an unauthenticated probe now returns **401** (`tick.js` returns 503 only when the secret is unset), and stop_watcher.yml — the only caller that holds the secret — has been green for hundreds of consecutive runs, which a mismatch could not be. **The cloud stop/target watcher is armed; paper stops no longer depend on a chart page being open.** The paragraph below is kept as the historical record of the blackout and of why the 503 branch exists; its claim that the secret is unset is FALSE as of this correction.

HISTORICAL: `TICK_SECRET` was not set in the
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
- **000 (NO ANSWER) IS NO LONGER FATAL (2026-08-18, run #776).** The taxonomy
  below drew its line in the wrong place: it treated "the server said 5xx" and
  "nothing answered at all" as the same evidence, and they are not. Every other
  code here is a statement Cloudflare made about its own state, which one runner
  can trust; 000 is the ABSENCE of a statement, and from a single vantage point
  it cannot distinguish a site outage from that runner's egress hiccuping for
  two minutes. Empirically it has been the latter every single time — #277,
  #372, #406 and #776, four for four, with the endpoint answering 401 normally
  throughout #776. Four false "DOWN" alarms on a job that runs 288 times a day
  is precisely how a channel gets muted, which is the blackout this whole
  section exists to prevent. So 000 now behaves like 503: `::warning::` plus a
  step summary, exit 0. **The alarm is not dropped, it moves to the component
  with a SECOND VANTAGE POINT** — `watchdog.probe_endpoints()` in
  kill_switch.yml probes the same URL half-hourly from a different runner and
  raises `tick_unreachable` through the state machine that can say it once,
  remind every `WATCHDOG_RENOTIFY_HOURS`, and **announce recovery** (a red run
  structurally cannot). A blip only this runner saw finds the watchdog seeing
  401 and stays correctly silent; a real outage is seen by both. Stated cost:
  detection of a genuine outage moves from ~5 min to at most 30 — the deliberate
  price of an alarm that is believed when it fires. 401 and 5xx stay fatal.
  Pinned behaviourally in `tests/test_workflow_hardening.py` (000 → exit 0 and
  names the watchdog; 401/500/502 → exit 1; 503 → exit 0; plus a pin that the
  watchdog really does still raise `tick_unreachable`, because a handoff to a
  receiver that stopped listening alerts nobody).
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
- **The 200/503/other taxonomy above was never reachable on a curl-level
  failure, and that was the whole of run #372 (2026-08-04).** `Process completed
  with exit code 28` — curl's "operation timed out", not any exit this workflow
  writes. GitHub's default shell is `bash -e {0}`, so the bare
  `code=$(curl ...)` assignment ABORTED THE STEP the instant curl failed:
  upstream of the 3-digit normalisation, of the retry loop, of the 503 branch
  and of the `exit 1` branch alike. The log is the proof — not one `attempt N`
  line printed. So the three tries that exist to absorb a transient were
  unreachable by the most common transient there is, and a single 30-second
  stall was emailed as "stop watcher DOWN" (run #277 on Jul 28 is the same
  signature; those two are the ONLY failures this job has ever had). Fixed with
  `|| true` on that one assignment — which neutralises curl's STATUS without
  appending a second value to its OUTPUT, the distinction from the `|| echo 000`
  that caused the earlier "000000" bug. This job judges on the HTTP code, never
  on curl's exit code. Pinned behaviourally (the shipped run block executed under
  `bash -e` against a curl stubbed to fail exactly as #372's did, asserting it
  reaches `exit 1` and prints `attempt 3` rather than dying with 28) plus two
  source pins, in `tests/test_workflow_hardening.py`.
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

<!-- moved from CLAUDE.md: HORIZON, BACKFILL and REGIME (removed 2026-09-20) -->

## HORIZON — the rotation surface (2026-07-28) — REMOVED ENTIRELY 2026-09-20, HISTORY ONLY

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
- **The sustained-run alarm pushes through the NOTICE tier** (2026-07-28,
  owner decision; channel-less since the 2026-08-27 Discord removal —
  `sectorbreadth.notify()`). A dashboard only works on the days you open it, and
  the raw ingredients of the July rotation were on the page for four weeks while
  the miss happened anyway. `notify()` fires the first time a sector enters
  `horizon()["sustained"]`, then at most once every
  `SECTOR_BREADTH_RUN_ALERT_REPEAT_DAYS` (7) for as long as the run lasts.
  - **Its own `NOTICE` severity tier** (routed to `["discord"]` until the
    2026-08-27 removal; now `[]`). INFO is
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

### BACKFILL — filling the memory backwards (2026-07-28) — REMOVED 2026-09-20, HISTORY ONLY

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

## REGIME — is the index telling the truth? (2026-07-28) — REMOVED ENTIRELY 2026-09-20, HISTORY ONLY

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

---

<!-- moved from CLAUDE.md: Tier 1 #16 — the consecutive-loss breaker (risk_manager, removed 2026-09-17) -->

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

---

<!-- moved from CLAUDE.md: Tier 1 #19/#20 — Bybit reconcile (removed 2026-09-17) -->

### Reconcile: stale `units`, and a time floor on closed-PnL matching (#19/#20)

`reconcile_journal` never copied the broker's filled `size` into `pos["units"]`,
so a partial fill booked full-size R. Separately, a vanished position was matched
against the account's last 50 closed-PnL records with **no time filter**, so
re-entering a symbol you had traded before resolved the NEW position against the
PREVIOUS trade's record. The floor is the position's own `opened_ts` minus
`BYBIT_RECONCILE_SKEW_MIN` (5 min) for runner-vs-exchange clock skew. Records
Bybit did not date, and pre-2026 rows with no `opened_ts`, bypass the filter
entirely rather than becoming uncloseable.

---

<!-- moved from CLAUDE.md: Tier 2 #25/#26 — manual-journal R and sizing (removed 2026-09-21) -->

### A hand-closed partial booked only the last rung (#25)

`ensureClosedR` guarded on `if (!t.exits.length && t.exit != null)`, so a trade
that scaled 0.25 at tp1 and was then closed by hand booked **0.25 of its move and
discarded the other 0.75**. Not a display bug: `computeCloseOutcome` reads the
same resolver, so the understated R went into the stats, the equity curve and the
win rate. Direction is asymmetric and therefore worse than a wash — a
partially-scaled WINNER is under-reported (the good part is the tail you cut off)
while a partially-scaled LOSER is flattered.

- The fix sums `exits.map(e => e.frac)` and appends a synthetic exit for the
  `1 - booked` remainder. **The full ladder sums to 0.90 by design**, so even a
  trade that took all three rungs has a 10% runner that was never priced.
- **It is idempotent because it runs on EVERY load, not once at close.** A second
  pass must find the remainder already booked and do nothing; the test that pins
  this calls it six times.
- A legacy row carrying `booked_pct` but an EMPTY `exits` array is NOT booked
  twice — that combination is how rows written before the ladder existed look.

### `_init` is a session cache, and it used to be persisted (#26)

`_init` memoises the per-row sizing derivation. `mjSaveLocal` stringified it, so
it rode out to localStorage AND to the KV sync store — permanently freezing
`risk_usd` at whatever constants happened to be loaded at the moment the row was
first painted. Compounded by the first-paint ordering (#40): that was reliably
the FALLBACK constants, not the published ones.

- Now **non-enumerable** (so `JSON.stringify` cannot see it) and stamped with
  `RULES_GEN`, which `loadBotRules()` bumps. A rules change invalidates every
  cached derivation instead of leaving the page showing sizing from a previous
  ruleset. The `loadMe()` immediately after the bump is what makes the
  invalidation visible rather than merely correct.
- **1R is pinned to the PLAN stop (`risk_stop`), not the CURRENT stop.** Trailing
  a stop to breakeven used to rescale R that had already been banked, which makes
  a trade look better the moment you protect it. Legacy rows with no `risk_stop`
  recover the plan stop exactly from `entry ∓ risk`, on the correct side for
  shorts.

---

<!-- moved from CLAUDE.md: Tier 2 #34/#27 — risk_manager.js defaults and the bot.html kill button (removed 2026-09-17) -->

### The offline fallback had drifted, and only shows when nobody can check (#34)

`risk_manager.js` carries `PUBLISHED_DEFAULTS`, a hand-typed mirror of five
`config.py` constants. It is a real fallback, not dead code — `bot.js` fetches
`data/bot_rules.json` and falls through to the mirror only when that fetch fails.
**So the mirror is what the page shows exactly when the person reading it is
least able to verify it.** It had drifted and lived that way for months: Python
risked 0.35% over 30 positions while the JS said 0.25% over 5, and the portfolio
cap read **2.0% against a live `PORTFOLIO_HEAT_LIMIT` of 7%**.

- **The portfolio cap moving 2 → 7 is the one number here worth stating out
  loud.** It is not a loosening of a limit that was binding — nothing in
  `broker/` reads this engine (see Tier 1, the `risk_manager` wiring gap), so no
  trade was ever blocked or allowed by it. It is a *display* correcting to the
  Python that actually governs the book. If the wiring gap is ever closed, this
  is the number that starts binding, at 7%.
- **`maxPortfolioRiskPct` is the only entry that is not a straight copy** —
  Python stores a fraction (0.07), every JS consumer wants a percent (7.0) — and
  the unit conversion is precisely how it ended up at 2.0, a value that was
  neither and had been a plausible cap once.
- `test/risk_defaults.test.js` also asserts **`run.py` still PUBLISHES each
  mirrored key**, which is the half a mirror test normally misses: stop
  publishing one and `bot.js` falls through to the mirror for that key on EVERY
  load rather than only offline, so the fallback silently becomes the value.

### #27 was relabelled, not wired — deliberately

The KILL SWITCH button on bot.html called `risk.activateKillSwitch()` and dimmed
itself. No fetch, no dispatch, nothing server-side. Making it real is a
live-trading gate and therefore **never autonomous**, so the fix went the other
way: the button, its tooltip, its log line and its modal now all say what it
actually does — blocks new entries **in this browser only**, does not close
positions, does not reach a broker, does not stop the server bot — and name
`kill_switch.yml` as the thing that does. A control that looks like it flattens
the book and does not is worse than no control; a control that states its own
scope is honest at the size it really is.

---

<!-- moved from CLAUDE.md: Tier 5 #84/#85 — the close-preview memo and risk_manager.js (removed) -->

### #84 — a memo keyed on a generation counter, not on a timestamp

The close preview re-parsed the entire journal out of localStorage on **every
keystroke**. The fix is a one-row memo (`closeRow` + `closeRowGen`) invalidated
by a `mjGen` counter that every writer bumps.

- **The generation counter is what makes it safe, and the discipline is that
  every writer must bump it.** `mjSaveLocal`, `mjSave` and `afterStoreChange`
  each start with `mjGen++`; the cross-tab `storage` listener routes through
  `afterStoreChange` rather than doing its own thing. Add a fourth writer that
  forgets to bump and the modal shows a row that no longer exists in the store —
  a test asserts all three still contain the bump, so the omission fails a push
  rather than surfacing as an unreproducible stale-preview report.
- **The memo is cleared on `closeModal()`, not merely invalidated.** It must not
  outlive the modal: a held row plus a matching generation is indistinguishable
  from a fresh read, so the next open of a DIFFERENT row within the same
  generation would answer from the previous one. `openCloseModal` seeds it from
  the read it just did rather than forcing a second.

### #85 — common-subexpression elimination, and the cache that was deliberately refused

`getCurrentRiskState()` walked the open book **six times per read**, and it is the
most-called method on the engine (`_emit()` after every mutation, every
`subscribe()`, and bot.js's 30s `loadData()`). Now two walks.

- **It is CSE, NOT a cache, and that distinction is the whole design.** No value
  is held across calls, so nothing can go stale. The alternative — memoising the
  result — was rejected because `getPositionUnrealized` reads `pos.current`,
  which `onPrice()`/`onPrices()` move **without any signal a memo could key on**:
  they only `_emit()` when TP1 actually fires, so an ordinary tick moves the
  number and announces nothing. A risk read answering with a price from a minute
  ago is a worse failure than a slow one. `test/statekeep.test.js` pins this
  behaviourally (a price move must land on the very next read) *and* pins the
  comment that says so, because the comment is what stands between the next
  reader and re-introducing the memo.
- **Bit-identical, not merely close.** A risk figure that drifts in the last cent
  is a support ticket nobody can reproduce. The accumulator preserves the exact
  key order the old `reduce` summed in and still rounds once at the end.
- **The hoist made the calls strictly FEWER, never more.** The old
  `atBE || this.getPositionOpenRisk(p) <= 0` short-circuited, so a break-even
  position skipped its second call; hoisting means one call per position instead
  of one *or* two. A test pins the direction with a fixture that deliberately
  contains a break-even row — without one the property is vacuous.
- **The item's "called from bot.js:828 (1s)" is FALSE.** The only 1-second
  interval is `startClocks`'s `tick`, which touches nothing on this engine. The
  real cadence is 30s plus every mutation. The cost per read was real; the
  frequency in the item was not, and the comment in the source now says so, so
  nobody re-derives the urgency from the item.
- **The comment above the method named `updatePrice`/`updatePrices` for months.
  Neither has ever existed.** Corrected to `onPrice()`/`onPrices()`. A test now
  asserts every method the comment cites in backticks is a real method on
  `RiskManager.prototype` — the general form, since the two named regexes beside
  it only catch the instance we already knew about.

---

<!-- moved from CLAUDE.md: Tier 5 #87/#88 — bot.js and the HORIZON/REGIME catch (removed) -->

### #87 — the feed's rows and this session's rows are different things

`bot.js` assigned the status fetch straight onto `LOG` and `JOURNAL` every 30
seconds, so **anything that happened in this browser was erased on the next
refresh** — including the kill-switch confirmation line, which is the one log
entry a person goes looking for to check that the thing they just clicked
actually happened.

- The two halves are now held apart (`FEED_*` / `LOCAL_*`) and composed
  newest-first into the rendered `LOG` / `JOURNAL`. `_ms` maps an unparseable or
  absent timestamp to **0, not NaN**, so undated rows sort to the BACK; NaN would
  make every comparison False and scatter them unpredictably through the list.
  Ties keep the local row first — `concat` puts local first and `Array.prototype
  .sort` is stable, which is spec-required since ES2019 and not an accident of V8.
- **They are merged, never deduped**, deliberately: a locally-closed trade and
  its feed twin are the same trade seen from two sides and will differ in their
  fields, so a dedupe would have to pick a winner and would sometimes pick the
  staler one. The duplicate is visible and self-correcting on the next scan; a
  wrong single row is neither.
- **A failed fetch clears `FEED_LOG` and re-renders the merge** rather than
  blanking the panel, so an outage costs you the server's lines and keeps your
  own. The item called `LOG`/`JOURNAL` "globals" — they are module-scoped `let`s
  inside the page IIFE. The defect was real; the word was not.

### #88 — the `.catch` was catching the wrong thing

`horizon.js` and `regime.js` chained `.then(mount)` **before** `.catch(...)`, so
the catch that exists to handle *"the JSON is not there yet"* was also swallowing
every fault thrown by the renderers inside `mount` — and its handler hides both
hosts. A renderer bug therefore made the surface silently vanish, which is
indistinguishable from the market simply never having run, and it is the failure
mode that keeps a broken panel invisible for weeks.

- **The catch is now scoped to the fetch and the parse only**, with `mount` after
  it. A test asserts the ordering by index and that `.then(mount)` no longer
  precedes it.
- **A renderer fault is REPORTED, not disguised**: `draw()` wraps each surface so
  a throwing strip cannot stop a panel that rendered fine, and `report()`
  re-raises asynchronously via `setTimeout(() => { throw err; }, 0)` rather than
  `console.error`. The async re-raise reaches `window.onerror` and the telemetry
  behind it; a `console.error` reaches a devtools panel nobody has open.
- **`DATA` is module-scoped and `render()` reads it, so the market switch redraws
  from the CURRENT payload.** The item's claim that the buttons get re-bound over
  a stale snapshot is wrong twice over — `mount` binds once behind a `BOUND`
  flag, and the buttons are static HTML — but the stale-snapshot risk it was
  pointing at is real and this is what closes it. `host.hidden = false` was
  already present in all four renderers.
- Both files are covered by **the same parameterised suite**, so the two surfaces
  cannot diverge silently — which is the actual risk with a file pair this close.

**RETRACTED, and must not be re-propagated: "sectors.html has no market
switcher" is NOT a defect.** `renderPanel` columns every market via
`Object.keys(MARKETS)` and never calls `activeMarket()` — the panel is
market-independent by construction. Do not "fix" it by adding a switcher.

---

<!-- moved from CLAUDE.md: Tier 4 #61 — the risk_manager.js front-end twin (removed 2026-09-17) -->

**#61 has a front-end twin, found 2026-07-28 and also flagged rather than
fixed** — `dollarsPerPoint` in `public/js/risk_manager.js` falls back to `1` for
a bare ASX ticker with no `STOCK.AX` class, which is ~43% overstated at 0.6969.
The engine now RECORDS which source it used but changes no arithmetic; see "The
Lighthouse budget was measuring the TAPE" below.

---

<!-- moved from CLAUDE.md: Lighthouse batch — dollarsPerPoint provenance in risk_manager.js (removed 2026-09-17) -->

- **`dollarsPerPoint` provenance is now recorded** in `public/js/risk_manager.js`
  — `"feed"` / `spec:<symbol>` / `"fallback"` — with a warn log and
  `getUnpricedPositions()`. **The arithmetic is byte-for-byte unchanged**, and
  that is the point: a bare ASX ticker has no `STOCK.AX` class, falls back to
  `1`, and is ~43% overstated at 0.6969. That is the front-end twin of #61's
  live half and it is **position sizing**, so it is FLAGGED FOR VIV, not fixed.
  Latent today only because `vivek_bot_book.json` holds zero positions — it
  becomes real the moment one is opened. `test/risk_manager.test.js` 54 → 65
  (suite 9, with a `captureLog` helper); `bot.html` bumped `risk_manager.js?v=9`
  → `?v=10` per the asset-version rule.

---

<!-- moved from CLAUDE.md: WHAT NEEDS MY EYES (removed 2026-10-09) -->

## WHAT NEEDS MY EYES — the deck's confluence strip (2026-08-01) — REMOVED ENTIRELY 2026-10-09, HISTORY ONLY

> **Removed 2026-10-09** (owner: *"Get rid of the what needs my eyes. Its
> annoying"*). Nothing below describes code that still exists; the ⨂
> Multi-lens pill, the row confluence chips, which names `PM.loadConfluence`
> qualifies, and the ALERTS page are untouched (the loader's `detail` /
> `pmBest` / `pmLegQuality` display payload went with the strip, its only
> reader). `git log -S renderEyes` finds the removal commit.

From "Two owner-ruled surfaces, 2026-08-01":

- **WHAT NEEDS MY EYES — confluence prominence on the deck** (`renderEyes()`
  in app.js + `eyes.css`, `#eyes-strip` inside `#deck`, ABOVE the pills).
  Owner: "make dual/triple lens agreement and any name that is both A+ and
  multi-lens the loudest thing on the main deck." Ranked chips from the same
  client-computed confluence set the ⨂ pill counts — triple beats dual, A+
  first inside each tier, triples pulse, a triple turns the strip amber-hot,
  "+N more" engages the Multi-lens filter. Partially reverses the Wave 3
  banner retirement BY OWNER RULING (the pill and row chips stay; this is
  additive). The A+ tag claims the DISPLAYED grade — the bot buys grade_raw.
  `test/eyes.test.js`.

From "is_product — LIC / preferred honesty" (2026-08-19, Session C):

- **Eyes strip**: the marker tag now reads **PRODUCT** (STRF is not a "FUND"),
  and leg-strength ranking is completed — the VIVEK leg's SCORE breaks the
  last tie inside a grade band, strictly AFTER count → product penalty →
  grade → PM leg quality. Missing score reads 0 (old payloads degrade to the
  previous order).

Later (2026-09-19 → 09-21, recorded in the removed `js/eyes-store.js` header
and app.js's Eyes block — see the removal commit): products were filtered out of the strip entirely; a chip click, or an arrow step on the
chart (`src=eyes` walked the strip's order), dismissed a name; "clear all"
dismissed the lot. The dismissal rule took four attempts — keyed to the scan's
`generated_at` (every hourly ASX rescan brought the list back), to the
Melbourne day (midnight brought it back), to a 7-day window (a fortnight-long
setup came back on day 8), and finally to a FINGERPRINT of why the name was
there (lenses + direction + VIVEK grade): dismissed until its alignment
materially changed. Per device, localStorage only (`gbs:eyes_seen`,
`gbs:eyes_chain`; cleared on removal by app.js `purgeLegacyKeys`, marker
`gbs:purged:v2`).

**Found on the way out:** `.eyes { display: flex }` beat the `hidden`
attribute (the site has no global `[hidden]` rule), so whenever the strip had
nothing to show it still drew an empty blue box above the deck pills —
while the page loaded, and whenever the list was empty or fully dismissed
(the screenshot gate's fixtures photographed it every run). Removing it
shortened the 390px deck by 44px (screenshot baselines v22 → v23: index-390
5.82%, the other three views 0.00%). Any element that is `hidden` by default
AND has a class-level `display` rule needs its own `.x[hidden] { display:
none; }` (ignition.css does this for `.ig-panel`).
