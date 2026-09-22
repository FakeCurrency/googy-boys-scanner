# /momentum list — what to borrow from the 5.0 card, and what not to

The owner's two screenshots: the 5.0 deck is dense and the Momentum page is four
skinny rows. The ask is that Momentum **feel** like the deck without **becoming**
it. So this reads the shipped 5.0 row (`app.js`, `rowHTML`) element by element
and says, for each, whether Momentum has an honest equivalent.

The rule applied throughout: **structure is copyable, verdicts are not.** A grade,
a conviction count and a paper-book slot are claims this lens does not make, and
importing the shape of them would mean inventing the claim.

| 5.0 card element | Momentum equivalent | copy structure? |
|---|---|---|
| `.row-grade` A+ / A / B+ badge | **rules that fired** — `A`, `B`, `A+B` | **Y** — same slot, different content. Never a letter grade. |
| `--grade-color` rail | direction rail: bull / bear / **conflict** | **Y** — already shipped |
| `.tkr` symbol → chart | same, `?s=SYM&m=MARKET&src=momentum` | **Y** |
| `.rdir` ▲/▼ | plan side from the row's own direction | **Y** |
| `tfDots()` per-timeframe dots | **N** — the scan is daily-only; dots would imply timeframes it never ran |
| `heldChip()` HELD | **N** — no paper book on this lens |
| `sectorCapChip()` SECTOR n/3 | **N** — that is a bot-book limit |
| `mcapBadge` | **N** — not in the payload |
| `.cname` company name | `row.name` | **Y** |
| `.row-chips` | rule, side, `knew Nb`, `label Nb back`, RSI, ADV | **Y** — all already on the row |
| `.row-price` + day change | `close`; no day change in the payload | **partial** — price yes, day move no |
| `.row-spark` 64×28 svg | **RESERVED SLOT, no line.** See below. | **Y (slot only)** |
| `.rk-score n/max` | **N** — this lens publishes no score out of a maximum |
| `.rk-rr` | **N** — the R:R lives on the chart's Auto box, not the list |
| `.row-expand` + detail panel | **N for now** — the chart is the detail view |

## The spark, and why it is an empty slot

`public/data/momentum/<market>.json` carries `close` and `n_bars` but **no price
series**. The three ways to get one are all worse than a blank:

1. read `<market>_vivek.json` — that is another lens's payload, and reading it
   here would make the Momentum card depend on a scan it does not own;
2. fetch `data/history/asx/<SYM>.json` per row — real bars, but ASX-only and one
   request per card;
3. synthesise from `close` — a drawn line that is not the price.

So the card reserves the 64×28 box and prints `no spark`, which keeps the row
height matching the deck and states the absence instead of filling it. If the
scanner ever publishes a `spark` array the slot is already there.

## Header strip

`N hits · M scanned · G gated · last bar DATE`, straight from `summary`. The deck's
equivalent line counts A+ and paper-book slots; neither exists here.
