# Scanner specification (handover pack)

A complete technical specification for building a daily-timeframe screener over ASX,
NASDAQ and crypto, derived from the chart template in the parent folder. Written to be
handed to another AI or engineer who has never seen this repository.

**Nothing here is wired into the scanner.** It is a specification and a reference
implementation, not a running lens. No module under `scanner/` imports any of it.

| File | What it is |
|---|---|
| `VIVEK_5.0_SCANNER_SPEC.md` | The full document. 16 parts, ~83,000 words. Rule inventory, verified Pine built-in semantics with citations, the Pine source, the screen specification, a tested reference implementation, an adversarial review of it, repository integration, validation plan, base-rate study. |
| `VIVEK_5.0_SCANNER_SPEC_CORE.md` | The implementable subset, ~16,000 words. Sized to paste into a single model context. The screen, the traps, and the code. |
| `reference/vivek50_screen.py` | Pure pandas/numpy port of the indicator maths and the screen. Pine-faithful seeding. |
| `reference/vivek50_selftest.py` | 28 assertions including a no-look-ahead causality proof. All pass. |
| `reference/vivek50_scan_cli.py` | End-to-end runner: gates, screen, ranking, atomic JSON publish. Verified on synthetic frames; the download path has never run against a live provider. |
| `reference/baserate.py` | The simulation behind the hit-volume figures (Appendix D). |
| `reference/worked_example.py` | The divergence-timing worked example (Part 4B). |

## Running the reference implementation

```bash
pip install pandas numpy
cd tradingview/scanner-spec/reference
python3 vivek50_selftest.py      # 28/28
python3 worked_example.py        # the bar-by-bar divergence timing
python3 baserate.py              # the base-rate measurement (slow, ~3 min)
```

`reference/` is outside `pytest.ini`'s `testpaths` and outside `test.yml`'s path filter, so
none of it runs in CI. That is deliberate: it is a handover artefact, not a gate.

## The two findings worth knowing without reading the whole thing

1. **RSI divergence carries a 5-bar detection lag.** The label is drawn at the pivot bar
   but is only knowable five bars later. A screener that treats the drawn position as the
   detection time looks into the future.
2. **"Score >= 2" filters almost nothing.** Measured over 1.95 million simulated
   symbol-days, score 1 is 2% of crosses. The scoring terms are correlated with the cross
   by construction, so raising the threshold cannot make the rule selective.
