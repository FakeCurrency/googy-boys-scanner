"""VIVEK daily-loss guardrail (per market).

A small, pure helper the runner consults BEFORE opening new entries. It sums the
session's damage — today's realised P&L on closed positions plus the current
unrealised P&L on open positions — and reports whether it has breached
VIVEK_BOT_MAX_DAILY_LOSS_PCT of equity. When breached the runner stops adding
risk for the rest of the session (it keeps managing/closing what's already open).

Kept broker-agnostic and side-effect-free so it is fully unit-testable: it never
touches a file or a broker. The runner owns persistence and any alerting.
"""

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


def check(book: dict, market: str, day: str, equity: float, price_of) -> dict:
    """Evaluate the daily-loss guard for `market`.

    Returns {breached, session_usd, limit_usd, realised_usd, unrealised_usd, ...}.
    `breached` is True once session P&L ≤ -(equity × MAX_DAILY_LOSS_PCT%).
    """
    pnl = session_pnl(book, market, day, price_of)
    pct = getattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 0.0) or 0.0
    limit = round(equity * (pct / 100.0), 2)
    breached = limit > 0 and pnl["session_usd"] <= -limit
    return {
        "market": market, "day": day, "breached": breached,
        "limit_usd": limit, "limit_pct": pct, **pnl,
    }
