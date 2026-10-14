# PhaseMap — zone-based AMD scanner

Second scanner category alongside the Fib/EMA engines. Built from the
"PHASEMAP — MASTER BUILD PROMPT" spec (single source of truth for detection
math and zone definitions — **do not change either without the owner's
sign-off**). Product name lives in one constant: `config.PRODUCT_NAME`.

Hard product rule: every actionable level is a ZONE (price band), never a
single price. Analysis tool only — no advice language; every narration ends
with the disclaimer line.

## Status

| Milestone | State |
|---|---|
| M1 detection engine (modules 0–5, zones, state machine, JSON writer) | ✅ built, all 8 spec fixtures pass |
| M2 narration engine (full state × direction template set) | ✅ built, coverage-tested |
| M3 frontend (tab, cards, zone ladder, legend + SVG diagrams) | ✅ built as vanilla-JS pages (`public/phasemap.html`, `phasemap-legend.html`, `js/phasemap.js`, `css/phasemap.css`) — owner chose a separate tab in the existing app over the spec's React scaffold |
| M4 backtest & proof harness (fills the `{stats}` slot) | ✅ built — `python -m phasemap.backtest --market asx --period 5y --write-stats`; reports in `backtest/reports/`, stats artefacts in `backtest/stats/` (run.py refuses them unless sample ≥ 30 AND ruleset matches). **All numbers are survivor-biased until the data moves off yfinance** — the report banner says so |
| M5 SMT divergence module | 🔜 deferred (Phase 2) — `smt` publishes null; nothing grades on it |
| M6 chop/liquidity heatmap | 🔜 deferred (Phase 3) |

## Running

Nightly refresh is automated: `.github/workflows/phasemap.yml` is scheduled
for 08:30 UTC, but GitHub runs it hours late — it usually lands between
midnight and ~4am Melbourne, so `run_date` (the Melbourne date it ran) is
normally the day AFTER the bars it read. `as_of` in each snapshot is the
newest completed bar the results were computed on; the page shows both. It
validates every snapshot against the writer's schema gate and commits the
data (Cloudflare redeploys). Manual trigger: Actions → "PhaseMap nightly
scan" → Run workflow, or `gh workflow run phasemap.yml`.

- **No unfinished bar is ever scanned.** Crypto drops the forming UTC candle;
  ASX and NASDAQ drop today's bar until its bar-final time
  (`scanner.config.IGNITION_BAR_FINAL`: 16:40 Sydney / 16:30 New York) — a
  late cron otherwise read a mid-session NASDAQ candle (`data/session.py`).
- **No new bar, no rescan.** When a stock market has no newly completed bar
  since the last snapshot (weekends, a pre-final run), the last scan's
  records are re-published under today's `run_date` with `carried_from` set
  and `as_of` unchanged; exit code 3. `--force` rescans anyway.
- **An outage keeps the last good files.** Below `PUBLISH_MIN_COVERAGE` of the
  universe fetched, nothing is written or pruned and the run exits 4.
- **A quick test never touches the live data.** `--limit`/`--tickers` write to
  a scratch dir unless `--publish` is given, and a partial run never prunes.

```bash
python -m phasemap.run                    # all markets: asx + nasdaq + crypto
python -m phasemap.run --market asx       # one market (full ASX directory ~2,000 names)
python -m phasemap.run --market nasdaq --limit 50
python -m phasemap.run --tickers BHP,CBA
python -m pytest phasemap/tests -q       # acceptance + unit suite
```

Output per market: `public/data/phasemap/<market>/latest.json` (slim,
compact — the page reads it), `narrations.json` (the narration sidecar),
`confluence.json` (ticker/direction/state only, for the multi-lens chips),
and the two newest dated full-schema snapshots `YYYY-MM-DD.json`; plus
`public/data/phasemap/charts/<market>/<TICKER>.json` (candles + that
ticker's published record and narration) for the chart page, rewritten only
when their bytes change. Deterministic: same bars + same
`config.RULESET_VERSION` → byte-identical JSON (confluence.json carries a
`generated_at` stamp). Crypto turnover uses Volume directly (Yahoo quotes
crypto volume in USD already); tick sizes are market-aware (`engine/buffers.py`).

## Layout

```
config.py       every tunable parameter + RULESET_VERSION (bump on any change)
data/           provider-agnostic bar source (yfinance = PROTOTYPE ONLY)
engine/         buffers, indicators, zones, setup_engine (state machine), scanner
narrate/        deterministic templates + renderer (no LLM in the scan path)
output/         JSON snapshot writer + hand-rolled schema validator
tests/          synth.py fixture builders + the 8 M1 acceptance fixtures
```

## Spec deviations / interpretations (flagged to owner)

1. **Displacement window = 5 bars** (Module 3 + state machine + fixture 3),
   not the "10 bars" line in Module 2 — the 10 is kept as a re-detection
   cooldown (`sweep_active_bars`), which a *deeper* sweep may override.
2. Config is `config.py` not YAML (spec allows either; repo convention, no
   PyYAML dependency).
3. Output dir is `public/data/phasemap/` (the static dir Cloudflare Pages
   serves) rather than the spec's `scans/phasemap/`.
4. ATR20 = simple mean of True Range including the current bar (documented in
   `engine/indicators.py`); ATR is NOT Wilder-smoothed by spec.
5. TRAP_SET records only surface when a resting equal-lows/highs cluster
   exists (the Watch-tier pre-alert condition); the compression state still
   tracks internally without one.
6. Data: yfinance is the prototyping provider only. Production needs
   EODHD/Norgate (full microcap coverage + delisted history for M4).

## Guardrails (non-negotiable, from the spec)

Zones never single prices · template-only narration, disclaimer always
appended · states after evidence, never predictions · original artwork only
(M3) · no performance claims until M4 fills `{stats}` · every parameter in
config with `RULESET_VERSION` bumped on change · ILLIQUID tag can never be
disabled.
