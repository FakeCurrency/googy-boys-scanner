"""TURTLE forward paper book — the only honest test this lens can run.

The scan republishes a five-year replay every night. That replay cannot answer
"does this work", and waiting will not make it answerable, because every
number in it is contaminated the same way: the universe is TODAY's listed
names, so it was selected on outcomes the system could not have known. On
crypto that is not a quibble -- the top twenty trades hold ~84% of all profit
and the universe is today's top-100 coin list, which is the set of assets we
know after the fact went up the most.

A FORWARD BOOK has none of that. It starts flat, takes only what fires from
the day it starts, pays modelled costs, and cannot have selected anything on
information it does not yet have. It will be slow and it will be small, and it
is the only number here that will ever mean what it appears to mean.

  journal/turtle_book.<market>.json   canonical, one per market
  journal/turtle_book.json            derived combined view

COMPLETELY SEPARATE FROM THE PAPER BOT. Own file, own equity, own slot pool,
own sizing. This module does not import anything under scanner/broker/ and a
test fails the push if it ever does. It shares the vivek_bot_book's SHAPE
because that shape is well understood here; it shares none of its state.

Order of operations per run, and it matters:
    mark -> exit -> add -> enter -> persist
Exits are settled before adds so a position cannot pyramid on the same bar it
was stopped out on, and entries come last so a slot freed today is available
today. Persistence is atomic (temp + os.replace), per project rule 7.
"""

from __future__ import annotations

import datetime
import os
import pathlib

from . import config
from .journal_common import atomic_write

try:                                            # stdlib json is enough here
    import json
except ImportError:                             # pragma: no cover
    raise

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOK_DIR = os.path.join(ROOT, "journal")
SCHEMA = 1

STOP = "stop"
CHANNEL = "channel"

# THE SKIP ENUM IS CLOSED, and that is the point. Silent drops are how a scan
# lost 95% of its universe and reported `errors: 0`; a book that quietly
# declines half its signals looks identical to one that had no signals. Every
# refusal names itself from this list, so "why is the book only three
# positions" always has an answer, and an unknown reason is a bug rather than
# a shrug.
SKIP_DIRECTION_CAP = "direction_cap"      # the 12-unit one-way ceiling
SKIP_CLOSE_CORR_CAP = "close_corr_cap"    # the 6-unit correlated-group ceiling
SKIP_LOOSE_CORR_CAP = "loose_corr_cap"    # declared, see the note below
SKIP_PER_MARKET_CAP = "per_market_cap"    # the 4-unit per-name ceiling
SKIP_CASH = "cash"                        # no room on a cash account
SKIP_UNIT_LT_ONE = "unit_lt_one"          # futures: a unit is under one contract
SKIP_SAME_BAR_REENTRY = "same_bar_reentry"
SKIP_S1_FILTER = "s1_skip_after_win"      # never emitted here, see the note
SKIP_REASONS = (
    SKIP_DIRECTION_CAP, SKIP_CLOSE_CORR_CAP, SKIP_LOOSE_CORR_CAP,
    SKIP_PER_MARKET_CAP, SKIP_CASH, SKIP_UNIT_LT_ONE,
    SKIP_SAME_BAR_REENTRY, SKIP_S1_FILTER,
)
# Two of these are deliberately never emitted BY THIS MODULE, and saying so
# beats an enum with unexplained dead entries:
#   loose_corr_cap  -- the 10-unit loosely-correlated ceiling is not wired on
#     EITHER path. "Loosely correlated" needs a taxonomy this repo does not
#     have; sector is already spent on the close-correlated bucket and reusing
#     it would just be the same cap twice under two names. Declared, displayed,
#     honestly not enforced.
#   s1_skip_after_win -- the System 1 filter runs in the ENGINE, before a
#     signal is ever published, so the book never sees a filtered breakout to
#     decline. The value exists so the enum matches the rules rather than the
#     plumbing.


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def book_path(market: str) -> str:
    return os.path.join(BOOK_DIR, f"turtle_book.{market}.json")


def empty_book(market: str) -> dict:
    return {"schema_version": SCHEMA, "market": market, "generated_at": "",
            "started": "", "equity_start": config.TURTLE_BOOK_EQUITY,
            "open": [], "closed": [], "summary": {}}


def load_book(market: str) -> dict:
    try:
        with open(book_path(market), encoding="utf-8") as fh:
            b = json.load(fh)
    except (OSError, ValueError):
        return empty_book(market)
    for k, v in empty_book(market).items():
        b.setdefault(k, v)
    return b


def save_book(book: dict) -> str:
    os.makedirs(BOOK_DIR, exist_ok=True)
    path = pathlib.Path(book_path(book["market"]))
    atomic_write(path, json.dumps(book, indent=1, ensure_ascii=False,
                                  allow_nan=False) + "\n", newline="\n")
    return str(path)


# ---------------------------------------------------------------------------
# arithmetic
# ---------------------------------------------------------------------------

def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def realized_equity(book: dict) -> float:
    """Starting equity plus every closed trade's dollar result.

    R alone cannot size the next trade -- a 1% unit is 1% of what the account
    is NOW -- so the book tracks dollars as well, and the drawdown rule reads
    this number.
    """
    eq = float(book.get("equity_start") or config.TURTLE_BOOK_EQUITY)
    for t in book.get("closed", []):
        eq += _f(t.get("pnl")) or 0.0
    return eq


def peak_equity(book: dict) -> float:
    eq = float(book.get("equity_start") or config.TURTLE_BOOK_EQUITY)
    peak = eq
    for t in book.get("closed", []):
        eq += _f(t.get("pnl")) or 0.0
        peak = max(peak, eq)
    return peak


def sizing_equity(book: dict) -> float:
    """Equity after the Turtles' drawdown rule, which COMPOUNDS: cut what you
    size from by 20% for every 10% below the peak."""
    eq, peak = realized_equity(book), peak_equity(book)
    if peak <= 0 or eq >= peak:
        return max(eq, 0.0)
    steps = int((100.0 * (peak - eq) / peak) // config.TURTLE_DRAWDOWN_STEP_PCT)
    return max(eq * ((1.0 - config.TURTLE_DRAWDOWN_CUT_PCT / 100.0) ** steps), 0.0)


def unit_units(equity: float, n: float) -> float:
    if not (n and n > 0 and equity > 0):
        return 0.0
    return (config.TURTLE_RISK_PCT * equity) / n


def _cost(price: float, units: float) -> float:
    return abs(price * units) * (config.TURTLE_COST_BPS / 10_000.0)


def _skip(day: str, market: str, symbol: str, action: str, reason: str,
          detail: dict | None = None) -> dict:
    """A refusal, recorded so it can be reproduced rather than guessed at."""
    assert reason in SKIP_REASONS, f"unknown skip reason {reason!r}"
    rec = {"as_of": day, "market": market, "symbol": symbol,
           "action": action, "reason": reason}
    rec.update(detail or {})
    return rec


def _bucket(row: dict, market: str) -> str:
    """The correlation bucket a name counts against.

    THIS IS A DECLARED PROXY, NOT A CORRELATION MATRIX. There is no covariance
    estimate in this repo and inventing one would be worse than saying so.
    Sector is a poor proxy -- two ASX miners are far more correlated than the
    label admits -- and for crypto it is barely a proxy at all, which is why
    crypto collapses to ONE bucket: it behaves like one market, and pretending
    otherwise is how a book ends up holding twelve units of the same bet.
    """
    if market == "crypto":
        return "crypto"
    return (row.get("sector") or "").strip().lower() or "unclassified"


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

def _open_position(row: dict, market: str, side: str, system: int,
                   fill: float, units: float, n: float, day: str) -> dict:
    stop_n = config.TURTLE_STOP_N
    sign = 1.0 if side == "long" else -1.0
    return {
        "symbol": row["symbol"], "market": market, "name": row.get("name", ""),
        "sector": row.get("sector", ""), "side": side, "system": system,
        "n": round(n, 8), "units": round(units, 8), "fills": [round(fill, 8)],
        "cost_basis": round(fill * units, 6),
        "stop": round(fill - sign * stop_n * n, 8),
        "last_fill": round(fill, 8),
        "opened": day, "last_mark": round(fill, 8), "mark_date": day,
        "fees": round(_cost(fill, units), 6),
        "mfe_r": 0.0, "mae_r": 0.0,
    }


def _close_position(pos: dict, price: float, reason: str, day: str) -> dict:
    sign = 1.0 if pos["side"] == "long" else -1.0
    units = pos["units"]
    gross = sign * (price - pos["cost_basis"] / units) * units if units else 0.0
    fees = (_f(pos.get("fees")) or 0.0) + _cost(price, units)
    risk = config.TURTLE_STOP_N * pos["n"] * units
    pnl = gross - fees
    return {
        **{k: pos[k] for k in ("symbol", "market", "name", "sector", "side",
                               "system", "n", "units", "opened")},
        "closed": day, "exit": round(price, 8), "reason": reason,
        "entry_avg": round(pos["cost_basis"] / units, 8) if units else None,
        "gross": round(gross, 4), "fees": round(fees, 4), "pnl": round(pnl, 4),
        "r": round(pnl / risk, 4) if risk > 0 else None,
        "gross_r": round(gross / risk, 4) if risk > 0 else None,
        "mfe_r": pos.get("mfe_r", 0.0), "mae_r": pos.get("mae_r", 0.0),
        "fills": pos.get("fills", []),
    }


def update(market: str, rows: list[dict], day: str | None = None) -> dict:
    """Advance the book one session. Returns the saved book."""
    day = day or datetime.date.today().isoformat()
    book = load_book(market)
    if not book.get("started"):
        book["started"] = day
    by_sym = {r["symbol"]: r for r in rows}
    stop_n = config.TURTLE_STOP_N
    step_n = config.TURTLE_PYRAMID_STEP_N
    events: list[str] = []
    skips: list[dict] = []

    still_open: list[dict] = []
    open_list = list(book.get("open", []))
    for idx, pos in enumerate(open_list):
        row = by_sym.get(pos["symbol"])
        if row is None:                       # not in today's scan: carry, unpriced
            pos["unpriced_runs"] = int(pos.get("unpriced_runs", 0)) + 1
            still_open.append(pos)
            continue
        pos["unpriced_runs"] = 0
        bar = row.get("bar") or {}
        ex = row.get("exits") or {}
        hi, lo = _f(bar.get("h")), _f(bar.get("l"))
        op, cl = _f(bar.get("o")), _f(bar.get("c"))
        if None in (hi, lo, op, cl):
            still_open.append(pos)
            continue
        sign = 1.0 if pos["side"] == "long" else -1.0
        avg = pos["cost_basis"] / pos["units"] if pos["units"] else cl
        risk_px = stop_n * pos["n"]

        # ---- mark ---------------------------------------------------------
        pos["last_mark"], pos["mark_date"] = round(cl, 8), day
        if risk_px > 0:
            pos["mfe_r"] = round(max(pos.get("mfe_r", 0.0),
                                     sign * ((hi if sign > 0 else lo) - avg) / risk_px), 4)
            pos["mae_r"] = round(min(pos.get("mae_r", 0.0),
                                     sign * ((lo if sign > 0 else hi) - avg) / risk_px), 4)

        # ---- exit, before any add ------------------------------------------
        chan = (ex.get("x1_lo") if pos["system"] == 1 else ex.get("x2_lo")) \
            if pos["side"] == "long" else \
            (ex.get("x1_hi") if pos["system"] == 1 else ex.get("x2_hi"))
        chan = _f(chan)
        exit_px = reason = None
        if pos["side"] == "long":
            if lo <= pos["stop"]:
                exit_px, reason = min(pos["stop"], op), STOP
            elif chan is not None and lo <= chan:
                exit_px, reason = min(chan, op), CHANNEL
        else:
            if hi >= pos["stop"]:
                exit_px, reason = max(pos["stop"], op), STOP
            elif chan is not None and hi >= chan:
                exit_px, reason = max(chan, op), CHANNEL
        if exit_px is not None:
            t = _close_position(pos, float(exit_px), reason, day)
            book.setdefault("closed", []).append(t)
            events.append(f"EXIT {pos['symbol']} {reason} {t['r']}R")
            continue

        # ---- add ------------------------------------------------------------
        eq = sizing_equity(book)
        if pos["units"] > 0 and len(pos["fills"]) >= config.TURTLE_MAX_UNITS:
            wants = (sign > 0 and hi >= pos["last_fill"] + step_n * pos["n"]) or \
                    (sign < 0 and lo <= pos["last_fill"] - step_n * pos["n"])
            if wants:
                skips.append(_skip(day, market, pos["symbol"], "add",
                                   SKIP_PER_MARKET_CAP,
                                   {"units_held": len(pos["fills"]),
                                    "cap": config.TURTLE_MAX_UNITS,
                                    "system": pos.get("system")}))
        while pos["units"] > 0 and len(pos["fills"]) < config.TURTLE_MAX_UNITS:
            level = pos["last_fill"] + sign * step_n * pos["n"]
            if (sign > 0 and hi < level) or (sign < 0 and lo > level):
                break
            fill = max(level, op) if sign > 0 else min(level, op)
            add_units = unit_units(eq, pos["n"])
            if add_units <= 0 or not _room_for(book, still_open, fill * add_units):
                skips.append(_skip(day, market, pos["symbol"], "add", SKIP_CASH,
                                   {"units_held": len(pos["fills"]),
                                    "want_notional": round(fill * add_units, 2),
                                    "equity": round(realized_equity(book), 2)}))
                break
            # The ceilings count UNITS, so a pyramid rung is checked exactly
            # as a new name is. Without this, twelve names each adding to four
            # hold 48 units against a 12-unit cap.
            # Count EVERY open unit, not just the positions already managed
            # this session. Counting only `still_open` let each position see
            # the ones processed before it and none of the ones after, so a
            # 12-unit cap still admitted 21. The tail may exit later in this
            # same session and free units, but that is not knowable here, and
            # declining to add is the conservative side of the ambiguity.
            ok, why, detail = _caps_allow(book, still_open + open_list[idx + 1:],
                                          pos, market, pos["side"], extra=pos)
            if not ok:
                skips.append(_skip(day, market, pos["symbol"], "add", why,
                                   dict(detail, units_held=len(pos["fills"]),
                                        system=pos.get("system"))))
                break
            pos["fills"].append(round(fill, 8))
            pos["cost_basis"] = round(pos["cost_basis"] + fill * add_units, 6)
            pos["units"] = round(pos["units"] + add_units, 8)
            pos["last_fill"] = round(fill, 8)
            pos["stop"] = round(fill - sign * stop_n * pos["n"], 8)
            pos["fees"] = round((_f(pos.get("fees")) or 0.0) + _cost(fill, add_units), 6)
            events.append(f"ADD {pos['symbol']} u{len(pos['fills'])} @ {fill:.6g}")

        # ---- the stop an add just raised, on the same bar -------------------
        if (sign > 0 and lo <= pos["stop"]) or (sign < 0 and hi >= pos["stop"]):
            px = min(pos["stop"], op) if sign > 0 else max(pos["stop"], op)
            t = _close_position(pos, float(px), STOP, day)
            book.setdefault("closed", []).append(t)
            events.append(f"EXIT {pos['symbol']} stop-after-add {t['r']}R")
            continue
        still_open.append(pos)

    # ---- enter, last, so a slot freed today is usable today -----------------
    held = {p["symbol"] for p in still_open}
    # A name this session already EXITED cannot be re-entered this session.
    # The manage loop can flatten a name and the entry loop would then see it
    # flat and refill the very breakout that just stopped out -- the rules
    # wait for a NEW channel break, not the same one still standing.
    exited_today = {t["symbol"] for t in book.get("closed", [])
                    if t.get("closed") == day}
    fired = [r for r in rows if r.get("signal")
             and r["symbol"] not in held and r["symbol"] not in exited_today]
    for r in rows:
        if r.get("signal") and r["symbol"] in exited_today:
            skips.append(_skip(day, market, r["symbol"], "entry",
                               SKIP_SAME_BAR_REENTRY, {"signal": r["signal"]}))
    fired.sort(key=lambda r: -(_f(r.get("dvol")) or 0.0))
    for row in fired:
        sig = row["signal"]
        side = "long" if sig.endswith("long") else "short"
        if side == "short" and not config.TURTLE_ALLOW_SHORTS:
            continue
        system = 1 if sig.startswith("s1") else 2
        n = _f(row.get("n"))
        bar = row.get("bar") or {}
        px = _f(bar.get("c")) or _f(row.get("price"))
        if not n or n <= 0 or not px or px <= 0:
            continue
        ok, why, detail = _caps_allow(book, still_open, row, market, side)
        if not ok:
            skips.append(_skip(day, market, row["symbol"], "entry", why,
                               dict(detail, system=system)))
            continue
        # FUTURES: a unit under one contract cannot be taken. Rounding 0.025
        # contracts up to 1 is roughly 40x the intended size, which is the
        # commonest way a small account destroys itself while believing it is
        # following rules. The refusal is the honest output.
        contracts = row.get("contracts")
        if contracts and not contracts.get("unit_fits"):
            skips.append(_skip(day, market, row["symbol"], "entry",
                               SKIP_UNIT_LT_ONE,
                               {"full_contracts": contracts.get("full_contracts"),
                                "micro_contracts": contracts.get("micro_contracts"),
                                "one_contract_risk_pct": contracts.get("one_contract_risk_pct"),
                                "equity": round(realized_equity(book), 2)}))
            continue
        # FUTURES SIZE IN CONTRACTS, NOT SHARES. `units` is carried as the
        # dollar-per-point multiplier (contracts x dpp) so every downstream
        # calculation -- P&L, risk, R -- stays correct arithmetic without
        # special-casing. A whole number of contracts, never a fraction.
        if contracts:
            dpp = contracts.get("micro_dpp") or contracts.get("dpp") or 0
            kind = contracts.get("micro") or "full"
            whole = int((config.TURTLE_RISK_PCT * sizing_equity(book)) / (n * dpp)) \
                if (dpp and n > 0) else 0
            if whole < 1:
                skips.append(_skip(day, market, row["symbol"], "entry",
                                   SKIP_UNIT_LT_ONE, {"contracts": whole}))
                continue
            units = whole * dpp
            # NO CASH CHECK HERE, deliberately. A futures position consumes
            # MARGIN, not notional, and this repo has no margin data; testing
            # notional against equity would refuse every legitimate contract
            # and call it prudence. The real constraint for a small account is
            # the one above -- whether a unit is a whole contract at all.
            pos = _open_position(row, market, side, system, px, units, n, day)
            pos["contracts"] = whole
            pos["contract"] = kind
            pos["dpp"] = dpp
            still_open.append(pos)
            events.append(f"ENTER {row['symbol']} S{system} {side} "
                          f"{whole}x{kind} @ {px:.6g}")
            continue

        units = unit_units(sizing_equity(book), n)
        if units <= 0 or not _room_for(book, still_open, px * units):
            skips.append(_skip(day, market, row["symbol"], "entry", SKIP_CASH,
                               {"want_notional": round(px * units, 2),
                                "equity": round(realized_equity(book), 2),
                                "system": system}))
            continue
        pos = _open_position(row, market, side, system, px, units, n, day)
        still_open.append(pos)
        events.append(f"ENTER {row['symbol']} S{system} {side} @ {px:.6g}")

    book["open"] = still_open
    book["generated_at"] = datetime.datetime.now(
        datetime.timezone.utc).isoformat(timespec="seconds")
    book["events"] = events[-200:]
    book["skips"] = skips
    # Counted by reason as well as listed, so "why is the book small" is one
    # glance rather than a scroll.
    counts = {r: 0 for r in SKIP_REASONS}
    for sk in skips:
        counts[sk["reason"]] = counts.get(sk["reason"], 0) + 1
    book["skip_counts"] = {k: v for k, v in counts.items() if v}
    book["skip_counts"]["total"] = len(skips)
    book["summary"] = summarize_book(book)
    save_book(book)
    return book


def _room_for(book: dict, open_rows: list[dict], notional: float) -> bool:
    """Cash constraint. THE BACKTEST HAS NO EQUIVALENT AND THAT IS A REAL GAP
    IN IT: crypto's median unit is ~30% of a $5,000 account, so a four-unit
    position is ~119% of the book -- impossible without margin, and the
    replay happily records it anyway. A forward book that did the same would
    inherit the flaw it exists to escape."""
    cap = realized_equity(book) * (config.TURTLE_BOOK_MAX_NOTIONAL_PCT / 100.0)
    used = sum(abs(_f(p.get("cost_basis")) or 0.0) for p in open_rows)
    return (used + abs(notional)) <= cap


def _caps_allow(book: dict, open_rows: list[dict], row: dict, market: str,
                side: str, extra: dict | None = None) -> tuple[bool, str, dict]:
    """The Turtles' unit ceilings, counted over EVERY unit including pyramids.

    THE CEILINGS ARE ON TOTAL UNITS, NOT ON POSITIONS. Checking them only when
    a new NAME is opened -- which is what this did until 2026-08-21 -- lets
    twelve names each pyramid to four and hold 48 units one way against a
    12-unit cap. That is the largest silent way this book could stop being the
    Turtle system while still looking like it, so the add path calls the same
    counter the entry path does.

    `extra` is the position being added to, which during the manage loop has
    not yet been returned to `open_rows` and so must be counted explicitly.
    """
    rows = list(open_rows) + ([extra] if extra is not None else [])
    same_side = [p for p in rows if p["side"] == side]
    units_side = sum(len(p.get("fills", [])) for p in same_side)
    if units_side + 1 > config.TURTLE_MAX_UNITS_DIRECTION:
        return False, SKIP_DIRECTION_CAP, {
            "units_on_book": units_side, "cap": config.TURTLE_MAX_UNITS_DIRECTION,
            "side": side}
    bucket = _bucket(row, market)
    units_bucket = sum(len(p.get("fills", [])) for p in same_side
                       if _bucket(p, market) == bucket)
    if units_bucket + 1 > config.TURTLE_MAX_UNITS_CLOSE_CORR:
        return False, SKIP_CLOSE_CORR_CAP, {
            "units_on_book": units_bucket, "cap": config.TURTLE_MAX_UNITS_CLOSE_CORR,
            "bucket": bucket, "side": side}
    return True, "", {}


def write_combined(markets=("asx", "nasdaq", "crypto")) -> str:
    """The DERIVED all-markets view. Per-market files stay canonical -- a
    market's run can only ever write its own, so a cross-market clobber is
    impossible by construction -- and this is regenerated from them."""
    combined = {"schema_version": SCHEMA, "market": "all",
                "generated_at": datetime.datetime.now(
                    datetime.timezone.utc).isoformat(timespec="seconds"),
                "equity_start": 0.0, "open": [], "closed": [], "by_market": {}}
    started = []
    for m in markets:
        if not os.path.exists(book_path(m)):
            continue
        b = load_book(m)
        combined["open"].extend(b.get("open", []))
        combined["closed"].extend(b.get("closed", []))
        combined["equity_start"] += float(b.get("equity_start") or 0.0)
        combined["by_market"][m] = b.get("summary", {})
        for sk in b.get("skips", []):
            combined.setdefault("skips", []).append(sk)
        if b.get("started"):
            started.append(b["started"])
    combined["started"] = min(started) if started else ""
    counts = {}
    for sk in combined.get("skips", []):
        counts[sk["reason"]] = counts.get(sk["reason"], 0) + 1
    counts["total"] = len(combined.get("skips", []))
    combined["skip_counts"] = counts
    combined["summary"] = summarize_book(combined)
    path = pathlib.Path(os.path.join(BOOK_DIR, "turtle_book.json"))
    os.makedirs(BOOK_DIR, exist_ok=True)
    atomic_write(path, json.dumps(combined, indent=1, ensure_ascii=False,
                                  allow_nan=False) + "\n", newline="\n")
    # and a public twin so the page can read it without a journal fetch
    pub = pathlib.Path(os.path.join(ROOT, "public", "data", "turtle_book.json"))
    atomic_write(pub, json.dumps(combined, indent=1, ensure_ascii=False,
                                 allow_nan=False) + "\n", newline="\n")
    return str(path)


def summarize_book(book: dict) -> dict:
    closed = book.get("closed", [])
    rs = [_f(t.get("r")) for t in closed]
    rs = [r for r in rs if r is not None]
    pnl = sum(_f(t.get("pnl")) or 0.0 for t in closed)
    fees = sum(_f(t.get("fees")) or 0.0 for t in closed)
    eq = realized_equity(book)
    start = float(book.get("equity_start") or config.TURTLE_BOOK_EQUITY)
    open_units = sum(len(p.get("fills", [])) for p in book.get("open", []))
    wins = sum(1 for r in rs if r > 0)
    srt = sorted(rs)
    med = None
    if srt:
        m = len(srt) // 2
        med = srt[m] if len(srt) % 2 else 0.5 * (srt[m - 1] + srt[m])
    return {
        "started": book.get("started", ""),
        "equity_start": round(start, 2),
        "equity": round(eq, 2),
        "return_pct": round(100.0 * (eq - start) / start, 3) if start else None,
        "open_positions": len(book.get("open", [])),
        "open_units": open_units,
        "closed": len(closed),
        "wins": wins,
        "win_pct": round(100.0 * wins / len(rs), 1) if rs else None,
        "total_r": round(sum(rs), 3) if rs else 0.0,
        "avg_r": round(sum(rs) / len(rs), 4) if rs else None,
        "median_r": round(med, 4) if med is not None else None,
        "realized_pnl": round(pnl, 2),
        "fees_paid": round(fees, 2),
        "sizing_equity": round(sizing_equity(book), 2),
    }
