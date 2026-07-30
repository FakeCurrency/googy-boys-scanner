# Design note — Payload diet (owner-selected; NO CODE in this commit)

Scope: the three `<market>_vivek.json` scan payloads only — the deck's first
paint. PhaseMap is already slim (narrations sidecar, the precedent this
follows); every other file on the page is small.

Measured before designing (live ASX file, the worst case): **1.29 MB
minified / 2.08 MB on disk, and `results` is 96% of it.** Inside the rows,
four field groups are expanded-row-only content: `plans` 513 KB, `detail`
152 KB, `analysis` 131 KB, `markers` 55 KB — **~850 KB (66%) that first
paint parses and never shows.** `spark` (113 KB) IS first-paint (the row
sparklines and the day-change estimator read it) and must stay.

## 1. The split

One file becomes two, same directory, per market:

- **`<m>_vivek.json` (summary — what the deck loads first, ~0.4 MB min):**
  everything except the four heavy groups. Top-level keys unchanged
  (`funnel`, `pulse`, `prices`, `price_age`, `sector_counts`, counters,
  stamps). Rows keep every list-path field — including `spark` — and keep a
  key named `plans`, **same shape, pruned to the lite fields** each
  timeframe: `armed`, `entry_trigger`, `structural_tps`, `level_tf`,
  `direction` (~60 KB total). This is the load-bearing trick: the filter
  pills, the high-conviction rule (app.js + recs.js read exactly
  `p.armed / p.entry_trigger / p.structural_tps`), mynames, journal's
  scanMeta and the cross-lens confluence checks all keep working with
  ZERO logic changes, because every field they touch is still there under
  the same name.
- **`<m>_vivek_detail.json` (detail — fetched lazily, ~0.9 MB min):**
  `{schema_version, market, generated_at, rows: {SYMBOL: {plans(full),
  detail, analysis, markers}}}`. Keyed by symbol so consumers join in O(1).

Writer: `scan.py` builds the full payload exactly as today; `output.write`
publishes the summary (heavy groups stripped) and the detail sidecar in the
same publish step. The bot is untouched by construction — `run_market`
receives the IN-MEMORY rows before any of this, so the split cannot change
what the bot sees (same fence argument as `output._finite`, and a test pins
that the in-memory rows still carry full plans).

## 2. How the deck loads them

1. First paint: fetch summary (unchanged path, unchanged cold-fail/retry
   behaviour, unchanged 3-minute refresh loop). Rows, pills, sparklines,
   funnel disclosure, sort, filters — all fully functional from summary.
2. First row-expand (or CSV export): fetch `data/<m>_vivek_detail.json`
   once via the existing `fetchT` timeout wrapper, cache it in state keyed
   by the summary's `generated_at`, then render the ladder/analysis exactly
   as today. Chart page fetches the detail file itself for its plan lines
   (it is a per-symbol page; lazy by nature).
3. Failure behaviour: summary failure = today's behaviour, unchanged.
   Detail failure = the expanded panel shows the standard retry chip
   (`PM.retryHTML` pattern from the timeout work) — the LIST stays fully
   usable; nothing else on the page degrades. A scan landing between the
   two fetches (skew) is tolerated exactly as the prices sidecar is today:
   the detail's own `generated_at` is displayed, and the refresh loop
   reconciles within one cycle; the state cache invalidates whenever the
   summary stamp moves.
4. Service worker: no change — `data/` is network-first and unversioned.

## 3. Same-commit obligations (the "schema + fixtures move together" risk)

- `VIVEK_SCHEMA_VERSION` bumps once; BOTH files carry it. The scan.yml
  schema gate extends from "summary at version N" to "summary at N, its
  detail sidecar readable, at N, **and generated_at matches the summary**"
  — the pairing check is what catches a run that pushed one file and lost
  the other. Same scope rule as today (single-market runs gate only their
  own pair).
- Staging lists: per-market `PATHS` in scan.yml and crypto_bot.yml gain
  `public/data/${m}_vivek_detail.json` (written-by-this-run invariant
  holds).
- e2e fixtures: the three fixture `_vivek.json` files are regenerated as
  summaries and three `_vivek_detail.json` fixtures are added. The
  screenshot-diff cache key digests the fixture set (`hashFiles`), so the
  baseline legitimately re-cuts itself in the same push; smoke.e2e's
  row-expand step now exercises the real detail fetch; the Lighthouse
  fixture transfer number drops well under the 2.5 MB budget (the budget
  itself does not move in this commit).
- staleview/unit suites that pull list-path helpers keep passing untouched
  (their fields all live in summary); the expanded-row and CSV paths gain
  tests for the lazy fetch + retry + skew rules.

## 4. Impact on the other fetches — none, by construction

- **Arriving list** (`<m>_arriving.json`): separate fenced file, untouched;
  its count stays in the summary's `funnel` object.
- **Funnel history** (`funnel_history.json`): separate file, untouched; the
  disclosure reads `d.funnel` from the SUMMARY (kept) and its trend file
  lazily (unchanged).
- **Paper-book strip / bookFacts**: reads `vivek_bot_book.json` — untouched.
- **Journal**: reads summary-level `prices`/`price_age` (kept) and the
  `_prices.json` sidecar — untouched.
- **Health probes / gates / watchdog**: read `_prices.json` and run
  history — untouched.

Rollout: one commit (writer + gate + fixtures + front-end), pushed while no
scan is mid-flight; the first scan after it publishes the pair. Old cached
summaries in browsers degrade gracefully (rows carry MORE fields than the
new code needs — wait, the reverse: new code reading an OLD full payload
simply finds the heavy fields already present and skips the detail fetch;
an old page reading a NEW summary shows rows and pills fine and an empty
ladder until refresh — the `?v=` bump forces the new code anyway).

Estimated effect: deck first-paint file 2.08 MB → ~0.55 MB on disk (~73%
cut) for ASX, proportional for NASDAQ/crypto; the ~1.5 MB of detail is paid
only by the first row a person actually opens.
