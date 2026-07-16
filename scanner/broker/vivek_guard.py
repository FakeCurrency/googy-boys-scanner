"""VIVEK loss guardrails (per market) — daily stop + weekly circuit breaker.

A small, pure helper the runner consults BEFORE opening new entries. It sums the
session's damage — today's realised P&L on closed positions plus the current
unrealised P&L on open positions — and reports whether it has breached
VIVEK_BOT_MAX_DAILY_LOSS_PCT of equity. Because that guard resets at midnight,
it also runs a WEEKLY breaker: realised P&L over the trailing 7 calendar days
plus open unrealised against VIVEK_BOT_MAX_WEEKLY_LOSS_PCT — five max-loss days
in a row no longer sail through. Either breach halts new entries (open
positions are still managed/closed).

Kept broker-agnostic and side-effect-free so it is fully unit-testable: it never
touches a file or a broker. The runner owns persistence and any alerting.
"""

import datetime as _dt

from .. import config


def _unreal_r(pos: dict, price: float) -> float:
    """Current unrealised R of an open position at `price` (0 on bad risk)."""
    risk = pos.get("risk") or 0.0
    if risk <= 0:
        return 0.0
    entry = pos["entry"]
    return (price - entry) / risk if pos.get("direction") == "long" else (entry - price) / risk


def session_pnl(book: dict, market: str, day: str, price_of) -> dict:
    """Today's P&L for `market`: realised on positions closed today + open unrealised.

    `price_of(symbol)` returns the current price or None. P&L is in account
    currency, derived from each position's R and its sized `risk_usd`.
    """
    realised = sum(
        (t.get("realized_r", 0.0) or 0.0) * (t.get("risk_usd", 0.0) or 0.0)
        for t in book.get("closed", [])
        if t.get("market") == market and t.get("exit_date") == day
    )
    unrealised, open_n = 0.0, 0
    for p in book.get("open", []):
        if p.get("market") != market:
            continue
        open_n += 1
        price = price_of(p.get("symbol"))
        if price is None:
            continue
        unrealised += _unreal_r(p, price) * (p.get("risk_usd", 0.0) or 0.0)
    return {
        "realised_usd": round(realised, 2),
        "unrealised_usd": round(unrealised, 2),
        "session_usd": round(realised + unrealised, 2),
        "open": open_n,
    }


def week_pnl(book: dict, market: str, day: str, unrealised_usd: float) -> float:
    """Trailing-7-day P&L: realised on trades closed in the window + open
    unrealised (already computed by session_pnl — passed in, not re-priced)."""
    try:
        cutoff = (_dt.date.fromisoformat(day) - _dt.timedelta(days=7)).isoformat()
    except ValueError:
        return 0.0
    realised = sum(
        (t.get("realized_r", 0.0) or 0.0) * (t.get("risk_usd", 0.0) or 0.0)
        for t in book.get("closed", [])
        if t.get("market") == market and cutoff <= str(t.get("exit_date") or "") <= day
    )
    return round(realised + unrealised_usd, 2)


def check(book: dict, market: str, day: str, equity: float, price_of) -> dict:
    """Evaluate the loss guards for `market`.

    Returns {breached, breach_kind, session_usd, limit_usd, week_usd, ...}.
    `breached` is True once session P&L ≤ -(equity × MAX_DAILY_LOSS_PCT%) OR
    trailing-7-day P&L ≤ -(equity × MAX_WEEKLY_LOSS_PCT%).
    """
    pnl = session_pnl(book, market, day, price_of)
    pct = getattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 0.0) or 0.0
    limit = round(equity * (pct / 100.0), 2)
    daily_breach = limit > 0 and pnl["session_usd"] <= -limit

    wpct = getattr(config, "VIVEK_BOT_MAX_WEEKLY_LOSS_PCT", 0.0) or 0.0
    wlimit = round(equity * (wpct / 100.0), 2)
    wusd = week_pnl(book, market, day, pnl["unrealised_usd"])
    weekly_breach = wlimit > 0 and wusd <= -wlimit

    return {
        "market": market, "day": day,
        "breached": daily_breach or weekly_breach,
        "breach_kind": ("daily" if daily_breach else "weekly" if weekly_breach else None),
        "limit_usd": limit, "limit_pct": pct,
        "week_usd": wusd, "week_limit_usd": wlimit, "week_limit_pct": wpct,
        **pnl,
    }
