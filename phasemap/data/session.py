"""Session clocks for the stock markets — when is a daily bar FINAL?

REFINE200 #131: phasemap.yml's 08:30 UTC cron lands hours late (15:00-18:00
UTC most nights, inside the 13:30-20:00 UTC NASDAQ session), and the nightly
assumed equity bars were complete. They were not: 586-757 published NASDAQ
closes a night differed from the final close, so sweeps, displacement and
tiers were read off a partial candle. 24/7 markets have engine.scanner's
drop_forming_bar (v1.3.0); this module is the same rule for session
markets, keyed off each market's BAR-FINAL time.

The bar-final table is scanner.config.IGNITION_BAR_FINAL — the repo's one
"when is today's stock bar final" answer (ASX 16:40 Sydney: the auction plus
Yahoo's ~20 min lag; NASDAQ 16:30 New York: closing cross plus the delayed
feed), shared with the morning digest gate, alert_returns and the Ignition
backstops. Read, never retyped. A market missing from it is treated as 24/7.

Data hygiene only — nothing here touches detection maths: the engine simply
never sees a bar that is not finished yet.
"""

import datetime as dt
import zoneinfo


def bar_final(market: str):
    """(tz, hour, minute) when `market`'s daily bar is final, or None."""
    try:
        from scanner.config import IGNITION_BAR_FINAL
    except Exception:                       # the engine stays importable alone
        return None
    v = IGNITION_BAR_FINAL.get(market)
    if not v:
        return None
    tz, hh, mm = v
    return zoneinfo.ZoneInfo(tz), int(hh), int(mm)


def latest_final_session(market: str, now: dt.datetime = None):
    """The newest weekday (market-local) whose daily bar is final at `now`,
    or None for a market with no session clock. Holidays are not modelled:
    on one this names a session Yahoo will never print, which only means the
    caller rescans (fail-open)."""
    fin = bar_final(market)
    if fin is None:
        return None
    tz, hh, mm = fin
    now = now or dt.datetime.now(dt.timezone.utc)
    local = now.astimezone(tz)
    day = local.date()
    if not (local.isoweekday() <= 5 and (local.hour, local.minute) >= (hh, mm)):
        day -= dt.timedelta(days=1)
    while day.isoweekday() > 5:
        day -= dt.timedelta(days=1)
    return day


def _bar_date(v):
    return v.date() if hasattr(v, "date") else v


def drop_unfinal_bar(df, market: str, now: dt.datetime = None):
    """Drop trailing rows dated after the latest FINAL session — the bar a
    mid-session (or pre-final) run would otherwise scan as complete."""
    if df is None or not len(df):
        return df
    final = latest_final_session(market, now)
    if final is None:
        return df
    n = len(df)
    while n and _bar_date(df["Date"].iloc[n - 1]) > final:
        n -= 1
    return df if n == len(df) else df.iloc[:n]
