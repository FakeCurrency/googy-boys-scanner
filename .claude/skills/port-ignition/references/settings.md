# Choosing the per-market settings

Every value is set BEFORE the first replay and written into the config
comment with its reason. The thresholds of the rule itself never change:
the ribbon, ATR and volume percentiles, drawdown, RVOL, the 60-bar base,
max extension, rearm, stop and trail. Only these per-market values do.
Each section gives the rule, then what the ASX and NASDAQ ports chose and
why.

## Bars per year (`IGNITION_BARS_PER_YEAR`)

The exchange's trading days a year. This converts the calendar windows,
written in crypto bars, into this market's bars. It does not touch the
chart windows.

- ASX 252, NASDAQ 252. At 252 the windows come out as: rank 504, warm-up
  252, drawdown lookback 756, drawdown warm-up 252, min history 276, max
  hold 124, random-timing window 126.
- Most stock markets trade 245–253 days. Use the exchange's own calendar
  count when you know it, else 252.

## Data-age ceiling (`IGNITION_MAX_DATA_AGE_DAYS_BY_MARKET`)

The longest calendar gap between two trading days, plus slack. A frame
older than this is skipped, not screened.

- ASX 5 (Easter: Thursday's bar read on Tuesday).
- NASDAQ 5 (holiday-next-to-weekend gaps peak at 4; 5 also clears a
  two-day closure like Sandy in 2012).
- Markets with Golden Week (Japan) or Lunar New Year (HK, China) need 8–10.

## Turnover floors (`IGNITION_MIN_BASE_TURNOVER`, `IGNITION_MIN_TRIGGER_TURNOVER`)

These are in the market's own money, as Close x Volume.

- Base: the 20-day average before the trigger. Use the market's VIVEK
  floor when it has one (`MARKETS[m].liquidity_min`). For an Ignition-only
  market, use the closest comparable market's floor: US markets use
  NASDAQ's US$1M.
- Trigger: the trigger day itself, at 3x the base.
- ASX A$100k / A$300k: a crypto-sized $1M/$3M would drop nearly every small
  cap, where coils live.
- NASDAQ US$1M / US$3M: equal to crypto's by coincidence, but set
  explicitly anyway.
- **Units trap:** Yahoo quotes most LSE lines in pence (GBp), so Close x
  Volume is in pence. Floors there must be x100, or the frame converted.
  Check the currency Yahoo reports before you register a floor.

## Replay cost (`IGNITION_BT_COST_PCT_BY_MARKET`)

The round-trip cost in %: a flat broker fee both ways as a share of a
~US$2,500 ticket, plus the spread, which is roughly one tick over the
typical price of a beaten-down name.

- crypto 0.30: taker fees plus slippage.
- NASDAQ 0.5: a 1c tick is 0.1–0.5% of a $2–10 price.
- ASX 1.0: a 0.1c tick is ~1% of a 9c price.
- Pick the closest analogue. The published `cost_stress` doubles it
  anyway. Write the reason into `COST_WHY[m]` too.

## Design and named cases (`IGNITION_BT_CASES_BY_MARKET`, `IGNITION_BT_DESIGN_CASES_BY_MARKET`)

- A specific chart that prompted the port is a design case, never scored.
  The ASX had DTR from 2026-09-01, and crypto has QNT.
- Otherwise use `()` and `{}`, set explicitly. NASDAQ had none, so every
  trigger is scored and the caveat says so in words.

## Forward bucket (`IGNITION_BT_REGISTERED_DATE_BY_MARKET`)

The port date (merge day). Triggers from that date on are the only truly
unseen data.

## Regime line (`IGNITION_REGIME_INDEX`)

A broad benchmark on Yahoo, with long history, that includes small caps.
It is context only, never a filter.

- ASX: `("^AXJO", "ASX 200")`.
- NASDAQ: `("^IXIC", "NASDAQ Composite")`. Not `^NDX`, which is 100
  mega-caps, where coils do not live.
- Candidates: NYSE `("^NYA", "NYSE Composite")` (broader than `^GSPC`), TSX
  `("^GSPTSE", "S&P/TSX Composite")`, LSE `("^FTAS", "FTSE All-Share")`.
  Probe the ticker on a runner (see new-market.md) before relying on it.

## Bar-final time (`IGNITION_BAR_FINAL`)

When the free (Yahoo, ~15–20 min delayed) daily bar is final: the closing
auction, plus the feed delay, plus slack.

- ASX: 16:40 Sydney (auction ~16:10, Yahoo shows it ~20 min late).
- NASDAQ: 16:30 New York (closing cross plus the delayed feed).
- Derive it from existing constants. For a market with
  `ALERT_RETURNS_BAR_FINAL`, use `(tz,) + tuple(ALERT_RETURNS_BAR_FINAL[m])`.
  For an Ignition-only market, use a session table plus an explicit
  `(tz, h, m)` with a comment (e.g. NYSE `("America/New_York", 16, 30)`).
- Also add the market to `IGNITION_FORMING_UNTIL_BAR_FINAL`.

## Crons (the workflow twin)

GitHub cron is UTC only. Pick UTC times that are right under every DST
offset, and let the `due` gate decide in local time.

- **Primary:** the first UTC minute past bar-final under BOTH offsets.
  NASDAQ `34 21` = 17:34 EDT / 16:34 EST. If no single UTC time clears
  bar-final in both regimes (the ASX's `24 6` does not under AEST), the
  gated backstop an hour later re-screens on final bars.
- **Backstops:** +1h and +2h, still before UTC midnight, so `1-5` remains
  the close's weekday. A post-midnight backstop would need `2-6` to cover
  Friday.
- **Intraday (3 runs):** inside the session and at least 60 min before the
  close in BOTH regimes. The gate skips one that GitHub delays past close
  − 30.
- **Minutes in use:** crypto :14/:44, ASX :24/:54, NASDAQ :34/:54. Pick
  free minutes and avoid :00/:30, where GitHub's scheduler is busiest.
- **Southern-hemisphere DST runs the other way.** Test at 2026-07-15 and
  2026-12-15 local.

## Universe scope

State exactly what is replayed in `UNIVERSE_WHY`, CLAUDE.md and the owner
summary. NASDAQ replays Global Select only; the smaller tiers, where many
small-cap bases live, are left out. Widening a universe is the owner's
call, so name the gap rather than closing it silently.
