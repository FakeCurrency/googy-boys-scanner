# Evidence surfaces — the report-only layer

*(2026-07-31. Covers the four owner-ruled evidence surfaces: the arriving
list, the funnel history, the Specs → VIVEK graduation watch, and the HORIZON
sector history with its backfill caveats. Documentation only — nothing in this
file changes behaviour, and nothing described here may grow into a decision
path without the owner's explicit ruling.)*

---

## The one rule they all share

Every surface in this document is **evidence about the system, never input to
it**. Each exists because a question kept being asked from memory ("does the
liquidity floor tighten into rallies?", "does the discovery lens actually feed
the core lens?") and memory is not evidence. Each was green-lit individually
by the owner with the same standing constraint, quoted from the rulings:

> Reads published artifacts only. Feeds nothing — no influence on grades,
> bot, or what is taken.

Mechanically that means four things, and each surface pins all four with
tests so the guarantee outlives everyone's attention span:

1. **One writer, on the publish side.** The module is imported by exactly one
   publish-path file (`run.py` or `spec_run.py`) — never by `scanner/broker/`,
   never by the engines that grade or plan.
2. **Written AFTER the publish, under a narrow `try`.** The artifact records
   what actually shipped, and a report failure prints a warning and the scan
   walks on. A report file must degrade to nothing, never take a scan down.
3. **Nothing reads it back.** No file in `scanner/` or `scanner/broker/`
   opens the artifact (the writer module and the `config.py` constant comment
   are the only scanner-side mentions of its name). The display is exactly
   one front-end file.
4. **The bot's inputs are unchanged by construction.** `vivek_run.run_market`
   receives the in-memory scan rows; these files are serialized on the side.
   Deleting all four artifacts tonight would change nothing about tomorrow's
   entries, exits, grades, or sizing.

**What the bot can never see, in one sentence: all four artifacts, and the
modules that write them.** The bot reads scan rows (in memory), the bot book,
`bot_rules` constants, and the sector cache — never these files.

If a future change needs one of these surfaces to *influence* anything — a
filter, a ranking, an alert that gates an entry — that is a trade change and
therefore the owner's call. Stop and ask; do not refactor toward it.

---

## 1. The arriving list — "what did the floor kill that volume is entering?"

**Purpose.** The liquidity floor kills sub-floor setups before publication
(`illiquid_setup` in the funnel). That is right for the bot and invisible for
the owner: a name whose turnover is *arriving* — today's dollars alone clear
the floor on a genuine volume spike — is exactly the kind of early mover the
floor exists to hide. The list publishes WHO the floor killed today among
names where liquidity is showing up, so the kill is a fact you can inspect
rather than a number you must trust.

**The rule (owner-ruled 2026-07-30, "Green-light, narrow implementation
only"), two legs, both mandatory, applied ONLY to names the floor killed:**

* **Leg A** — today's turnover ALONE clears the market's existing floor
  (`market.liquidity_min`, byte-untouched by this feature). Load-bearing:
  rvol alone is the pump signature (an 18× day on A$500 of dust).
* **Leg B** — today's volume ≥ `SCAN_ARRIVING_MIN_RVOL` (3.0) × the name's
  own 20-day average.

Capped at `SCAN_ARRIVING_MAX` (12), sorted by today's turnover
(participation, not multiple — the multiple is the pump smell).

**Locations.**

| What | Where |
|---|---|
| Writer | `scanner/scan.py` (rows collected in the scan loop; published as its own file in the publish block) |
| Artifact | `public/data/<market>_arriving.json` |
| Row shape | `symbol, name, sector, dir, fund, price, rvol, adv_usd, turnover_today, turnover_avg20` — **no grade, no plan, no entry/stop/target, by construction** |
| Workflow | scan.yml / crypto_bot.yml (per-market PATHS staging) |
| Display | `public/js/app.js` — the funnel disclosure's `.sf-arriving` block on the deck |
| Config | `SCAN_ARRIVING_MIN_RVOL`, `SCAN_ARRIVING_MAX` in `scanner/config.py` |
| Tests | `tests/test_scan_pipeline.py` (two-leg qualification, dust exclusion, ordinary-volume exclusion, fences) |

**What the bot can never see.** The file, and the names on it. Qualifying
names are still DROPPED from the scan exactly as before — they are never fed
to Specs/VIVEK/PhaseMap, never re-graded, never handed to `decide()`. The
funnel payload carries only the COUNT (`funnel.arriving`); the rows live in
the fenced file that nothing in `scanner/` or `broker/` opens.

**How to interpret.** Each row answers "the floor killed this name today,
and real dollars were entering it anyway". A name that recurs here across
sessions is building the liquidity to cross the floor for real — the
graduation watch (section 3) and this list are two ends of the same story.
`rvol` is the spike multiple; `turnover_today` vs `turnover_avg20` is the
size of the arrival in dollars; `fund` marks REIT/ETF/LIC vehicles whose
volume spikes usually mean distributions, not discovery. An empty list on a
quiet day is the honest common case, not a failure.

---

## 2. The funnel history — "does the floor tighten into rallies?"

**Purpose.** Every scan publishes a one-shot funnel (scanned → with-data →
published → floor-killed → arriving). One snapshot cannot answer trend
questions — "is the floor killing more than it used to?", "is the setup
count drying up?". The history is the same five counts, appended per scan,
so the snapshot gains a past (owner-ruled Task 2, 2026-07-30).

**Locations.**

| What | Where |
|---|---|
| Writer | `scanner/funnelhistory.py` — `append(market, vk, out_root)`, called from `run.py` AFTER `output.write_vivek_pair`, under a narrow `try` |
| Artifact | `public/data/funnel_history.json` — **columnar per market** (`t`, `scanned`, `with_data`, `published`, `floor_killed`, `arriving` arrays) to keep the committed file small |
| Cap | `SCAN_FUNNEL_HISTORY_MAX` (2000 rows PER MARKET — crypto ~40 days at 48 scans/day, ASX ~8 months at 8/day; uneven on purpose, the cap is a size guard and the chart buckets by day) |
| Workflow | scan.yml (SHARED staging list) + crypto_bot.yml |
| Display | `public/js/app.js` only — sparkline series inside the deck's funnel disclosure (`.sf-hist`) |
| Config | `SCAN_FUNNEL_HISTORY_FILE`, `SCAN_FUNNEL_HISTORY_MAX` |
| Tests | `tests/test_funnel_history.py` (13 — row derivation, append mechanics, corrupt-file recovery, unequal-column truncation, and four fences) |

**What the bot can never see.** The file. `funnelhistory` is imported by
`run.py` alone (regex-pinned); no file in `scanner/` or `broker/` other than
the writer and the config comment even contains the string `funnel_history`;
the append happens after the publish so the history can never disagree with
the funnel the deck shows for the same scan, and it sits under a narrow
`except` so its failure cannot kill a scan.

**How to interpret.** It is **append-only and derived** — each row is
computed from the published payload at publish time, and
`test_append_never_rewrites_earlier_rows` pins that history is never
restated. Timestamps are the payloads' own `generated_at` stamps
(market-local), never the runner clock. Rows exist only for scans that ran:
a weekend gap in ASX rows is the calendar, not a failure. Because crypto
scans ~48×/day and ASX ~8×/day, compare shapes within a market, not row
counts across markets. `published` here is the payload's `setups` count and
`floor_killed` is `illiquid_setup` — renamed at the API boundary to the
owner's vocabulary.

---

## 3. The Specs → VIVEK graduation watch — "does the discovery lens feed the core lens?"

**Purpose.** Specs exists to surface sub-$0.50 names before they matter. The
only honest measure of that claim is a tally: how many names Specs surfaced
FIRST later crossed the 50-cent line and/or the liquidity floor into VIVEK
eligibility and set up there. The registry keeps that tally as recorded
crossing events rather than a number recalled from memory (owner-ruled
2026-07-31).

**Mechanics worth knowing before reading the file.**

* Per market, `seen` is the watch: names Specs surfaced that were NOT in
  that day's published VIVEK results. A name VIVEK already publishes has
  nothing to graduate into, so it is never watched — Specs did not surface
  it first.
* A watched name **graduates** when it appears in a VIVEK payload dated
  STRICTLY after its `first_seen`. Strictness is what makes "previously
  surfaced" true, and it also makes a same-night re-run idempotent.
* Graduation **removes the name from the watch**, so the tally counts
  crossing EVENTS, not appearances. A graduate that falls back under 50c
  re-enters the watch the next time Specs surfaces it — and can honestly
  graduate again.
* `graduated_total` is the lifetime tally and survives the list cap. All
  dates come from the payloads' own `generated_at` stamps, never the wall
  clock, so a replay writes exactly what the live run wrote.

**Locations.**

| What | Where |
|---|---|
| Writer | `scanner/specgrad.py` — `update(market, out_dir, spec_payload)`, called from `spec_run.py`'s market loop AFTER the specs publish, under a narrow `try` |
| Artifact | `public/data/spec_graduation.json` — per-market `seen` / `graduates` / `graduated_total` |
| Reads | published artifacts only: the spec payload it is handed (already on disk) and the committed `<m>_vivek.json` summary. No downloads, no engine calls, detail sidecar not consulted |
| Caps | `SPEC_GRAD_SEEN_MAX` (2000/market watch, oldest `first_seen` trimmed), `SPEC_GRAD_MAX` (400/market graduations, newest kept; the tally survives trims) |
| Workflow | phasemap.yml nightly 08:30 UTC (PATHS staging; deliberately NOT in the must-change gate — specgrad failures are swallowed by design, so a must-change assert would turn a tolerated report failure into a red nightly) |
| Display | `public/js/specs.js` only — the `.spg` strip on specs.html, hidden until it has something to say |
| Config | `SPEC_GRAD_FILE`, `SPEC_GRAD_SEEN_MAX`, `SPEC_GRAD_MAX` |
| Tests | `tests/test_specgrad.py` (21 — mechanics, date strictness, idempotency, caps, payload non-mutation, corrupt-registry recovery, fences both directions) |

**What the bot can never see.** The registry file and the module. Imported
by `spec_run.py` alone; nothing in `scanner/` or `broker/` reads
`spec_graduation.json` back; the graduation check reads the PUBLISHED vivek
summary, so it observes what shipped without touching how it was produced.
Watching a name changes nothing about that name's treatment anywhere.

**How to interpret.** A graduate row reads as a story: `spec_price` (what it
cost when Specs flagged it) → `vivek_price` at `graduated`, `grade` on
graduation day, `days` in between. The tally headline is `graduated_total`;
`watching N` is the live population the next graduation can come from. Two
honest caveats: appearing in VIVEK results requires a SETUP, so a name that
crossed 50c but never set up will not register — the tally measures
graduations into the published VIVEK world, not price crossings in the
abstract; and the registry started 2026-07-31, so early months will read
low while the first watch cohort matures. Zero graduates with a growing
watch is the expected early state, not a broken surface.

---

## 4. HORIZON sector history — the rotation memory (and the backfill's error bars)

**Purpose.** The July post-mortem: ASX consumer discretionaries ran for four
weeks while the book held none of them, and nothing on any page could say
"for the 19th session running". `data/sector_history.json` is the only long
sector memory in the system — one row per market per day of the sector
participation board — and it feeds the two numbers that separate a shrug
from a miss in progress: the trend column and the **unheld streak**
(consecutive sessions a sector led on participation rate while the book held
zero of it).

**Locations.**

| What | Where |
|---|---|
| Writer | `scanner/sectorbreadth.py` — `append_history()` inside `update()`, from `run.py` only (asx/nasdaq scans; a crypto-only weekend run never touches it) |
| Artifact | `data/sector_history.json` — note: **repo `data/`, not `public/data/`** — it is memory, not a page payload. Capped 2000 rows/market. Also holds the Discord ping memory (`hist["alerts"]["sector_run"]`) so the alert dedupe and the streak it derives from can never disagree about what day it is |
| Published panel | `public/data/sector_breadth.json` (the board the pages render; merged per-market — both files must stay in scan.yml's SHARED staging list) |
| Display | `public/js/horizon.js` — `#horizon-panel` on sectors.html, `#horizon-strip` on index.html; both hide silently when the JSON is missing |
| Backfill | `scripts/backfill_sector_history.py` via backfill_history.yml (manual only, `dry_run` defaults TRUE) |
| Config | `SECTOR_BREADTH_*` in `scanner/config.py` |
| Tests | `tests/test_sector_breadth.py`, `tests/test_backfill_sector_history.py`, `tests/test_backup_completeness.py` (the history file is in the daily backup set) |

**The fence, stated honestly — this one is shaped differently.** Unlike the
three surfaces above, the history IS read back by its own writer:
`sectorbreadth` re-reads it to rebuild the streak and the trend column each
scan (rebuilt from history rather than kept as a counter, so a re-run or a
backfill cannot corrupt it). What holds is the fence that matters: **nothing
in `scanner/broker/` imports `sectorbreadth` or opens either file**, no
grade, filter, ranking or sizing consults them, and the sustained-run
Discord ping changes what gets SAID, never what gets taken. Every question
the surface raises — raise the sector cap? tilt the ranking? — is
explicitly the owner's, not a refactor.

**How to interpret — the caveats are the content here.**

* **Two kinds of rows.** Live rows are written by the scan that day.
  Backfilled rows carry `"r": 1` — reconstructed by replaying the REAL
  engine (evaluate → liquidity gate → score/grade → hysteresis → plans →
  gate, scan.py's order) on frames truncated to each session. Real rows
  always beat reconstructed ones on merge; a re-run of the backfill is
  idempotent.
* **UNKNOWN IS NOT ZERO — the rule the streak rests on.** The bot book's
  earliest entry is 2026-06-28; before that, "did the book hold this
  sector" is not unrecorded but *unknowable*. Those `held` cells are
  `null`, never `0`, and the streak STOPS at a null exactly as it stops at
  a held position. Counting through nulls would have manufactured
  six-month streaks the day the backfill landed and fired the Discord
  alarm on every sector at once. A streak that ends at the backfill
  horizon is the honest maximum, not the true length.
* **The reconstruction's known error bars, both conservative.**
  Survivorship: the replay uses today's universe, so delisted names are
  missing from the denominators. Hysteresis cadence: the replay chains
  grades once per DAY where live chains once per SCAN, which skews A+/A
  counts LOW. Both make backfilled participation read slightly weaker than
  live rows would have — trend direction across the boundary is
  trustworthy; exact level comparisons across it are not.
* **The first `--warmup` sessions of a replay are computed then DISCARDED**
  (cold hysteresis), and the still-forming trailing bar is dropped using
  market-local time.
* **Denominators differ by market** (`names_source`): ASX divides by names
  LISTED per sector (full GICS coverage), a true participation rate;
  NASDAQ divides by names CLASSIFIED so far in `data/sector_map.json`, so
  NASDAQ ranking is sound but its LEVEL is not comparable to ASX and
  drifts as coverage fills.
* **The streak only counts what the board can rank.** The reconstruction
  re-applies all three of `compute()`'s exclusions (not-a-sector, minimum
  names, rate > 0) with the identical tie-break, so a reconstructed rank
  can never disagree with the rank that was displayed.

---

## Quick reference

| Surface | Module (writer) | Artifact | Runs | Shown on | Bot visibility |
|---|---|---|---|---|---|
| Arriving list | `scanner/scan.py` | `public/data/<m>_arriving.json` | every scan | deck funnel disclosure (app.js) | none — names still dropped from the scan |
| Funnel history | `scanner/funnelhistory.py` | `public/data/funnel_history.json` | every scan, after publish | deck funnel sparklines (app.js) | none — never read back |
| Specs → VIVEK graduation | `scanner/specgrad.py` | `public/data/spec_graduation.json` | nightly (phasemap.yml) | SPECS page strip (specs.js) | none — reads published artifacts only |
| HORIZON sector history | `scanner/sectorbreadth.py` | `data/sector_history.json` (+ published `public/data/sector_breadth.json`) | every asx/nasdaq scan | sectors.html panel + deck strip (horizon.js) | none in `broker/`; self-read by its own writer for streak/trend |

*Related but out of scope here: REGIME (`scanner/regime.py` →
`public/data/regime.json`) follows the same report-only rule with no history
file — it recomputes from bars every run. The CLAUDE.md HORIZON/REGIME
sections carry the design arguments; this document is the operating map.*
