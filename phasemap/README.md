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
| M4 backtest & proof harness (fills the `{stats}` slot) | 🔜 not started |
| M5 SMT divergence module | 🔜 deferred (Phase 2) |
| M6 chop/liquidity heatmap | 🔜 deferred (Phase 3) |

## Running

```bash
python -m phasemap.run                    # full ASX directory (~2,000 names)
python -m phasemap.run --limit 50
python -m phasemap.run --tickers BHP,CBA
python -m pytest phasemap/tests -q       # acceptance + unit suite
```

Output: `public/data/phasemap/YYYY-MM-DD.json` + `latest.json` (the frontend
reads `latest.json` only). Deterministic: same bars + same
`config.RULESET_VERSION` → byte-identical JSON.

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
