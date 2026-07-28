"""VIVEK loss guardrails (per market) — daily stop + weekly circuit breaker.

A small, pure helper the runner consults BEFORE opening new entries. It sums the
damage done *inside a window* — realised P&L on positions closed in it, R banked
by partial exits inside it, and the change in unrealised P&L on what is still
open — and reports whether that breaches VIVEK_BOT_MAX_DAILY_LOSS_PCT of equity
over today, or VIVEK_BOT_MAX_WEEKLY_LOSS_PCT over the trailing 7 calendar days.
Either breach halts new entries (open positions are still managed/closed).

Kept broker-agnostic and side-effect-free so it is fully unit-testable: it never
touches a file or a broker. The runner owns persistence and any alerting.

WHAT CHANGED, AND WHY (2026-07-28) — TOP100 #13/#14/#15
=======================================================
The closed leg always filtered `exit_date == day`. The OPEN leg never had a day
filter at all: it charged each open position's WHOLE-LIFE unrealised P&L, plus
its whole-life banked partial-exit R, to today. So a daily loss guard was being
asked to fire on losses that were weeks old, every single day, until the
position closed.

The live book said so out loud. On 2026-07-28 the crypto guard read
`session_usd = -1827.46` — 41% of a $4,500 daily limit spent before the session
had done anything at all — while ASX read *+*$692.88, meaning a market holding
old winners could take a genuinely catastrophic day and still not breach. Both
directions are the same bug: the number was not a day's P&L.

The fix is a REFERENCE PRICE per window. Every position now records the mark it
started each session at (`day_marks`, stamped by `vivek_run._stamp_day_ref` from
the PREVIOUS run's `last_mark`, so an overnight gap is charged to the day it
gapped into, not to the day before it). P&L for a window is then measured from
that reference rather than from entry:

    window_R = SUM over exits inside the window of  pct x (exit_px - ref)/risk
             + remaining_now x (price - ref)/risk

which telescopes exactly: summing every day's window over a position's life
returns its total P&L, no more and no less. A position opened inside the window
uses its own entry as the reference, so its first day counts in full.

DIRECTION OF THE CHANGE, STATED PLAINLY: for a book full of older positions this
makes the daily guard LOOSER (it no longer arrives pre-breached) and the weekly
guard TIGHTER on names that have been bleeding for a fortnight (their older
losses used to be double-counted into the window every day, and are now counted
once). It does not change any position, size, stop or rule. It changes when the
guard says "stop adding risk", which is the one thing it was built to say.

`open_total_usd` still publishes the whole-life open P&L, so nothing that wants
the old number has to reconstruct it.
"""

import datetime as _dt

from .. import config


def _unreal_r(pos: dict, price: float) -> float:
    """WHOLE-LIFE unrealised R of an open position at `price` (0 on bad risk).

    This is the number stamped on the book for display (`unreal_r`/`unreal_usd`)
    and read by the kill switch — "how is this position doing", measured from
    entry. The loss guard does NOT use it any more; see `_window_r`.

    Scaled by the REMAINING open fraction (2026-07-20, review C6): once a
    position has booked partial profits (`booked_pct` > 0) only the un-booked
    remainder is still exposed — valuing the full original size overstated
    runners' unrealised P&L. The R already BANKED by those partial exits is
    counted separately, so nothing is dropped or double-counted.
    """
    risk = pos.get("risk") or 0.0
    if risk <= 0:
        return 0.0
    remaining = _remaining(pos)
    if remaining <= 0.0:
        return 0.0
    entry = pos["entry"]
    per_unit = (price - entry) / risk if pos.get("direction") == "long" else (entry - price) / risk
    return per_unit * remaining


def _remaining(pos: dict) -> float:
    """Fraction of the original size still exposed (0.0 - 1.0)."""
    return min(1.0, max(0.0, 1.0 - (pos.get("booked_pct") or 0.0)))


def _num(v, default: float = 0.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if f == f else default          # NaN -> default


def ref_price(pos: dict, since: str) -> float:
    """The price this position started the window opening at `since` from.

    Resolution order, each step a strict improvement on the next:
      1. opened inside the window -> its own entry (the whole life IS the window)
      2. `day_marks[<first stored day >= since>]` -> the mark it carried into
         the window, stamped by the runner from the previous run's last_mark
      3. the OLDEST stored mark, when every stored mark predates the window
         (a position nothing has been able to mark for over a week); charges
         MORE of its life to the window, never less
      4. `last_mark`, then `entry` — legacy rows and hand-built tickets that
         have never been through a stamping run. This is the pre-2026-07-28
         behaviour, kept as the floor so an un-stamped book degrades to the old
         numbers rather than to zero.
    """
    entry = _num(pos.get("entry"))
    entry_date = str(pos.get("entry_date") or "")
    if entry_date and since and entry_date >= since:
        return entry

    marks = pos.get("day_marks")
    if isinstance(marks, dict) and marks:
        clean = {str(k): _num(v) for k, v in marks.items()}
        clean = {k: v for k, v in clean.items() if v > 0}
        if clean:
            eligible = sorted(k for k in clean if not since or k >= since)
            return clean[eligible[0]] if eligible else clean[sorted(clean)[0]]

    last = _num(pos.get("last_mark"))
    return last if last > 0 else entry


def _r_from(pos: dict, price: float, ref: float, risk: float) -> float:
    """Per-unit R moved between `ref` and `price`, signed by direction."""
    if pos.get("direction") == "long":
        return (price - ref) / risk
    return (ref - price) / risk


def _window_r(pos: dict, since: str, day: str, price: float | None) -> dict:
    """P&L attributable to the window [since..day] for ONE position, in R.

    Returns {"banked": R, "unrealised": R, "cost": R, "worst": R, "priced": bool}
    where `worst` is the unrealised leg re-valued at the position's own STOP —
    the floor on what an UNPRICED position can still cost this window, used by
    `check` to fail closed instead of open (TOP100 #15).
    """
    out = {"banked": 0.0, "unrealised": 0.0, "cost": 0.0, "worst": 0.0,
           "priced": price is not None}
    risk = _num(pos.get("risk"))
    if risk <= 0:
        return out
    ref = ref_price(pos, since)
    if ref <= 0:
        return out

    entry_date = str(pos.get("entry_date") or "")
    exits = pos.get("exits") or []
    booked_in_window = 0.0
    booked_total = 0.0
    if exits:
        for e in exits:
            pct = _num((e or {}).get("pct"))
            px = _num((e or {}).get("price"))
            if pct <= 0 or px <= 0:
                continue
            booked_total += pct
            date = str((e or {}).get("date") or "")
            if since <= date <= day:
                booked_in_window += pct
                out["banked"] += pct * _r_from(pos, px, ref, risk)
    else:
        # No exit ledger — a legacy row, a hand-built ticket, the pre-dates book
        # format, or (overwhelmingly the common case) a position that has simply
        # never scaled out. Split on whether anything was actually booked:
        #   * nothing booked -> `realized_r` can ONLY be the entry cost, which
        #     was paid on the entry day. Date it, exactly like an exit. Live
        #     evidence for why this matters: every open row in the book carries
        #     about -0.006R of entry cost, ~$3.50 at a $5,000 notional, and the
        #     undated version charged all 24 of them to every session forever —
        #     the same bug as #14 wearing a smaller hat.
        #   * something booked -> the dates are genuinely unknown, so keep the
        #     pre-2026-07-28 undated behaviour. It over-counts, which is the
        #     conservative direction for a loss guard.
        booked_total = booked_in_window = (pos.get("booked_pct") or 0.0)
        if booked_total > 0 or not entry_date or since <= entry_date <= day:
            out["banked"] = _num(pos.get("realized_r"))

    remaining = 0.0 if pos.get("status") == "closed" else _remaining(pos)
    if remaining > 0:
        if price is not None:
            out["unrealised"] = remaining * _r_from(pos, price, ref, risk)
        stop = _num(pos.get("stop"))
        if stop > 0:
            # A stop can only ever be a loss relative to where the window
            # opened; clamp so a trailed stop above the reference cannot be
            # booked as a worst-case PROFIT.
            out["worst"] = min(0.0, remaining * _r_from(pos, stop, ref, risk))

    # Execution costs: the entry pays on the full size on the ENTRY day, each
    # exit pays on its own fraction on its own day (see vivek_journal._cost_r).
    # Only the total lands on the position, so it is attributed by the share of
    # that activity which happened inside the window. Approximate by
    # construction; exact whenever the whole position lives inside one window.
    cost_total = _num(pos.get("cost_r"))
    if cost_total and exits:
        activity_all = 1.0 + booked_total
        activity_win = booked_in_window + (
            1.0 if (entry_date and since <= entry_date <= day) else 0.0
        )
        if activity_all > 0:
            out["cost"] = cost_total * (activity_win / activity_all)
    return out


def _window_pnl(book: dict, market: str, since: str, day: str, price_of) -> dict:
    """Aggregate `_window_r` across a market's open + closed positions.

    `since` == `day` gives the session; `since` == day-7 gives the week.
    """
    banked = unrealised = worst = 0.0
    realised = 0.0
    open_n = 0
    unpriced: list[str] = []

    for p in book.get("open", []):
        if p.get("market") != market:
            continue
        open_n += 1
        price = price_of(p.get("symbol"))
        w = _window_r(p, since, day, price)
        risk_usd = _num(p.get("risk_usd"))
        banked += (w["banked"] - w["cost"]) * risk_usd
        unrealised += w["unrealised"] * risk_usd
        if not w["priced"]:
            unpriced.append(str(p.get("symbol") or "?"))
            worst += w["worst"] * risk_usd

    for t in book.get("closed", []):
        if t.get("market") != market:
            continue
        exit_date = str(t.get("exit_date") or "")
        if not (since <= exit_date <= day):
            continue
        risk_usd = _num(t.get("risk_usd"))
        total = _num(t.get("realized_r")) * risk_usd
        if t.get("exits"):
            # Subtract the R this trade banked BEFORE the window opened — those
            # partial exits were charged to their own days while it was still
            # open, and counting the closing row's whole-life R would book them
            # a second time (TOP100 #14).
            prior = 0.0
            entry = _num(t.get("entry"))
            risk = _num(t.get("risk"))
            if risk > 0:
                for e in t["exits"]:
                    pct = _num((e or {}).get("pct"))
                    px = _num((e or {}).get("price"))
                    if pct <= 0 or px <= 0:
                        continue
                    if str((e or {}).get("date") or "") < since:
                        prior += pct * _r_from(t, px, entry, risk)
            total -= prior * risk_usd
        realised += total

    return {
        "realised_usd": round(realised, 2),
        "open_realised_usd": round(banked, 2),
        "unrealised_usd": round(unrealised, 2),
        "session_usd": round(realised + banked + unrealised, 2),
        "unpriced": unpriced,
        "unpriced_worst_usd": round(worst, 2),
        "open": open_n,
    }


def session_pnl(book: dict, market: str, day: str, price_of) -> dict:
    """TODAY's P&L for `market` — see the module docstring for the window maths.

    `price_of(symbol)` returns the current price or None. P&L is in account
    currency, derived from each position's R and its sized `risk_usd`.
    Also reports `open_total_usd`: the whole-life open P&L, which is what this
    function used to return as its unrealised leg.
    """
    out = _window_pnl(book, market, day, day, price_of)
    total = 0.0
    for p in book.get("open", []):
        if p.get("market") != market:
            continue
        price = price_of(p.get("symbol"))
        if price is None:
            continue
        risk_usd = _num(p.get("risk_usd"))
        total += (_unreal_r(p, price) + _num(p.get("realized_r"))) * risk_usd
    out["open_total_usd"] = round(total, 2)
    return out


def week_pnl(book: dict, market: str, day: str, price_of) -> dict:
    """Trailing-7-calendar-day P&L for `market`, same maths over a wider window.

    Returns the same shape as `session_pnl` (minus `open_total_usd`), or None
    when `day` is not a parseable date — an unknown window must not be reported
    as a zero one.
    """
    try:
        cutoff = (_dt.date.fromisoformat(day) - _dt.timedelta(days=7)).isoformat()
    except (ValueError, TypeError):
        return {}
    return _window_pnl(book, market, cutoff, day, price_of)


def check(book: dict, market: str, day: str, equity: float, price_of) -> dict:
    """Evaluate the loss guards for `market`.

    Returns {breached, breach_kind, session_usd, limit_usd, week_usd, ...}.
    `breached` is True once session P&L <= -(equity x MAX_DAILY_LOSS_PCT%), OR
    trailing-7-day P&L <= -(equity x MAX_WEEKLY_LOSS_PCT%), OR the guard cannot
    rule out either breach because open positions could not be priced.

    THE UNMEASURED CASE FAILS CLOSED (2026-07-28, TOP100 #15). The old loop did
    `if price is None: continue` — a data outage silently DISARMED the daily
    stop, which is the one moment you would want it armed. It now re-values every
    unpriced position at its own STOP (the worst the system's own rules allow
    before the stop fires) and halts new entries if that could breach. When
    everything prices, `unpriced_worst_usd` is 0.00 and the verdict is
    bit-identical to the measured one; the halt is not a blanket outage rule but
    "the part I cannot see is big enough to matter".

    The bound is the position's stop rather than infinity on purpose: an
    unbounded worst case would halt the book permanently the first time a name
    became unpriceable (MDB did exactly that for weeks — see CLAUDE.md), and a
    guard that never lifts is a guard nobody leaves switched on.
    """
    pnl = session_pnl(book, market, day, price_of)
    pct = getattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 0.0) or 0.0
    limit = round(equity * (pct / 100.0), 2)
    daily_breach = limit > 0 and pnl["session_usd"] <= -limit

    wpct = getattr(config, "VIVEK_BOT_MAX_WEEKLY_LOSS_PCT", 0.0) or 0.0
    wlimit = round(equity * (wpct / 100.0), 2)
    week = week_pnl(book, market, day, price_of)
    wusd = week.get("session_usd", 0.0)
    weekly_breach = wlimit > 0 and wusd <= -wlimit

    # Fail closed: could the part we could not measure carry either window over?
    worst_day = round(pnl["session_usd"] + pnl["unpriced_worst_usd"], 2)
    worst_week = round(wusd + week.get("unpriced_worst_usd", 0.0), 2)
    unmeasured_breach = bool(pnl["unpriced"]) and not (daily_breach or weekly_breach) and (
        (limit > 0 and worst_day <= -limit) or (wlimit > 0 and worst_week <= -wlimit)
    )

    return {
        "market": market, "day": day,
        "breached": daily_breach or weekly_breach or unmeasured_breach,
        "breach_kind": ("daily" if daily_breach else
                        "weekly" if weekly_breach else
                        "unmeasured" if unmeasured_breach else None),
        "limit_usd": limit, "limit_pct": pct,
        "week_usd": wusd, "week_limit_usd": wlimit, "week_limit_pct": wpct,
        "week_unpriced_worst_usd": week.get("unpriced_worst_usd", 0.0),
        "worst_session_usd": worst_day, "worst_week_usd": worst_week,
        **pnl,
    }
