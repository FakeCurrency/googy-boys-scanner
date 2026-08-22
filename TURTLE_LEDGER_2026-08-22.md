# TURTLE LEDGER — corrected, 2026-08-22

The money-document of record for the Turtle lens as of this date. Supersedes
the 2026-08-22 morning explainer's §07 and patches its §02/§05/§06. The tab
(`/turtle.html`) renders the same facts FROM the published payloads; where
this file and a payload disagree, the payload is newer.

## The rules at a glance (the frozen law — none of it moves)

| Parameter | Value |
|---|---|
| N | Wilder ATR, 20-day (`indicators.atr(df, 20)` IS N) |
| System 1 | 20-day breakout in / 10-day channel out — filtered |
| System 2 | 55-day breakout in / 20-day channel out — never filtered |
| **Both break one bar** | **tagged System 2 — failsafe first; S2 owns the 20-day exit** |
| Stop | 2N below the most recent actual fill, whole position |
| Pyramid | +½N per add, max 4 units, entry-time N for the life of the trade |
| Unit | 1% of equity per N — the formula that does not move |
| **Unit ceilings** | **4 per market · 6 close-correlated · 10 loose (declared, unwired) · 12 one direction** |
| Drawdown | 0.8^floor(dd%/10) of equity — 20% DD sizes off 64%, not 60% |
| Costs | 15 bps a side; gaps fill at the open; exits before adds |
| Re-entry | same Yahoo BAR cannot refill after an exit — across any number of cron runs |
| Clock | **daily bars. The 4-hour crypto cron is a scan cadence, not a 4-hour Donchian.** |

The 6-unit close bucket counts ALL crypto as ONE bucket (both the cash and
the 5× book). The loose-10 stays declared and honestly unenforced — no
taxonomy for "loosely correlated" exists here and faking one would be worse.

## What changed on 2026-08-22 (all shipped, all mutation-tested)

1. **Re-entry guard keys on the BAR, not the calendar** (`closed_bar` stamped
   on every close). The old run-date key let a Friday NASDAQ stop refill at
   Saturday's 09:30 pass off the SAME Friday bar. Latent (0 equity closes);
   closed before it fired.
2. **The add-path cash check counts every open dollar** (self + tail). DOGE's
   u3 (and the cron's u4) passed the old undercount; the book sits at ~$5.9k
   basis on a $4.2k cap. Those rows stand — append-only — and the next add
   meets the correct check.
3. **Crypto 5× forward series** — `journal/turtle_book.crypto5x.json`,
   started 2026-08-22, $5,000, flat until its first cron. Posted margin =
   notional/5 (perp analogue, isolated — NOT Dennis's futures IM); unit still
   1%/N, fractional; refuse when posted > free (`no_margin`); liquidation at
   the liq price when adverse MTM reaches posted (capped loss — isolated
   margin cannot lose more than it posted). Yahoo collisions corrected for
   this sleeve only (APT/ARB/SUI/UNI/TON → real suffixed ids; cash universe
   untouched — it is a running experiment). ASX/NASDAQ stay cash at 1×.
4. **Futures hard gates**: no new open unless unit ≥ 1 whole contract AND no
   roll suspect in the current 20-bar N window AND a REAL margin file exists
   at `data/futures_margins.json` (absent → `no_margin_file`; the file is
   never invented). Fit table published on the futures payload. KC dpp
   37,500 → 375 (ICE cents rule; the prior figure traced to a vacuous audit).
5. **Portfolio replay** (`scanner/turtle_portfolio.py`, 09:30 cron): one
   shared equity per sleeve — crypto 5× $5k, NASDAQ-100-proxy cash $5k and
   $100k, futures-21 $5k (gated; publishes its refusals), ASX $5k control.
   Deterministic ordering (bar dollar volume desc, then symbol — in the
   payload). NOT walk-forward, NOT the Turtle return — the payload says so
   itself.

## Reading the books (the standing rules)

- **Realized vs MTM**: book equity headlines are REALIZED ONLY; open
  positions are not marked into them.
- **The combined figure adds A$ and US$ at face value** — no FX anywhere in
  `turtle_book.py`. Read per-market rows for anything actionable.
- **A first print is a print, not evidence**: no sleeve's record means
  anything until ≥ 30 closed trades AND ≥ 20 trading days. Day one's five
  same-session crypto stops are a verdict on the CASH VEHICLE, not on
  expectancy.
- **Binding constraint enum** (every refusal names itself):
  `cash | no_margin | direction_cap | close_corr_cap | per_market_cap |
  unit_lt_one | no_margin_file | roll_window | same_bar_reentry` — and
  `liquidation` as an exit reason on the 5× book.

## §07 — the vehicle verdict (the law of this document)

**Equities are a control.** One factor wearing thousands of tickers. The
replay already said no (ASX −0.55R net, NASDAQ −0.47R net, ~70k trades); the
live cash books will not overturn that, and Donchian-on-ASX is not Dennis.

**Crypto cash is one factor with no margin.** Day one: five longs, five 2N
stops, −16.3% / −6.70R, 0 wins — a VEHICLE result, not a 20-day sample of
expectancy. A $5k spot book cannot pyramid without spending the account: 37
cash skips on the combined tape are a binding constraint the original rules
never had.

**Futures are the historical mechanism and are untradeable honestly at $5k**
until (C1) a micro contract fits unit ≥ 1 at 1%/N, (C2) no roll suspect sits
in the current 20-bar N window, and (C3) a real margin file exists. All three
are now hard gates in the code. Until then futures stay 0/0, and the
replay's +0.15R gross / −0.22R net is labelled: `=F`, costs on, rolls
unhandled, not a fill, not a reason to arm.

**The only $5k path that can take a legal 1%/N unit without rounding up into
extra risk is crypto 5×**: posted = notional/5, fractional coins, liquidation
if MTM ≤ −posted, crypto = one 6-unit bucket, daily bars, 15 bps, compounding
DD. A perp analogue, not original Turtle futures IM — and it gets a NEW
forward book. The cash crypto book stays on disk as the cash experiment.

**What the $5k account is allowed to take tomorrow morning**: whatever the
crypto 5× book's next cron admits under posted margin and the 4/6/12 caps —
and nothing else. ASX/NASDAQ cash books keep managing their opens; futures
opens are refused by construction; nothing is sized off crypto's replay mean
or futures' gross.
