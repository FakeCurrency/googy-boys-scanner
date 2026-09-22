# Momentum morning audit — 2026-09-23

Read-only pass over everything that shipped, then a live check of the pages.
**No product code changed: every check passed, so there was nothing to fix.**

## What landed

| PR | merged | SHA on main | what it claimed |
|---|---|---|---|
| #19 | Y | `70967c966` | report-only Momentum lens v1 (nine rebased commits) |
| #20 | Y | `6211fcfe8` | row link `?s=`, not `?symbol=` |
| #21 | Y | `b5fadd21d` | chart mode: own MA stack, Rule A marks |
| #22 | Y | `92dd5ba26` | Pine Auto box + MACD/RSI panes; ELS Daily = TradingView |
| #23 | Y | `5178509b6` | per-timeframe recompute, 4H tab |
| #24 | Y | `008970aa9` | TV look: three real panes, palette, clean tags |
| #25 | Y | `34b983ccd` | overnight notes |
| #26 | Y | `34f51abdc` | crop to the live move, time-bounded box, label diet |
| #27 | Y | `0e77574ca` | list cards, bars chip, hourly cap no longer flat 750 |
| #28 | Y | `64cd537d4` | why only four ASX names (merged this morning) |

## Live check (public/ served locally; pages.dev is unreachable from the sandbox)

| check | result |
|---|---|
| /momentum ASX — cards, not skinny rows | PASS — 4 cards, 73px (deck 76px) |
| spark slot on every card | PASS — 4/4, labelled `no spark` |
| header `N names · scanned · gated · last bar` | PASS — `298 scanned · 867 gated · last bar 2026-09-22` |
| row href `?s=` + `src=momentum` | PASS |
| /momentum?m=nasdaq | PASS — 20 cards, no errors |
| ELS Daily SHORT 5.88 / 6.76 | PASS — footer `ENTRY 5.880 · SL 6.762` |
| three panes | PASS — price + 2 oscillator charts |
| daily bars chip | PASS — `1265 daily bars` |
| no PhaseMap, no SCORE x/8 | PASS |
| 4H bars chip not ~187 | PASS — `1100 4H bars` |
| BHP 5.0 unchanged | PASS — SMA 10/20/43/200, no caption, no panes |

Gates: pytest 1467/83, 23 JS suites, e2e smoke (3 momentum checks), fences —
all green. ELS pin worst error **$0.0040**. Hourly cap is the range-aware one;
the single remaining `return 750` is the 1m/5m/15m/30m scalp branch.

## One correction to #27

#27 said the hourly fix took 4H from 187 to **825** candles. That was wrong
arithmetic: I divided 3,300 hourly bars by 4. An ASX session is six hours and
straddles two epoch-anchored 4H buckets, so it is ~2 candles per session, and
~550 sessions is **~1,100** 4H candles — which is what the chip now shows. The
fix was right; the number I quoted for it was not.

## Coverage (observe only)

`asx.json` has been written exactly once — the manual dispatch at 07:25 UTC on
the 22nd — with 1,165 of 2,047 downloaded and `reused: 0`. The first
**scheduled** ASX run is the 06:30 UTC weekday cron, which has not fired yet, so
whether coverage recovers on a warm cache cannot be judged this morning. Check
the next `data: momentum asx` commit's `downloaded` and `cache.reused`.
