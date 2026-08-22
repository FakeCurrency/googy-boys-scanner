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
LIQUIDATION = "liquidation"     # a levered position's posted margin ran out

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
SKIP_NO_MARGIN = "no_margin"              # levered book: posted would exceed free
SKIP_UNIT_LT_ONE = "unit_lt_one"          # futures: a unit is under one contract
SKIP_NO_MARGIN_FILE = "no_margin_file"    # futures: no real margin data exists
SKIP_ROLL_WINDOW = "roll_window"          # futures: a roll suspect sits in N's window
SKIP_SAME_BAR_REENTRY = "same_bar_reentry"
SKIP_S1_FILTER = "s1_skip_after_win"      # never emitted here, see the note
SKIP_REASONS = (
    SKIP_DIRECTION_CAP, SKIP_CLOSE_CORR_CAP, SKIP_LOOSE_CORR_CAP,
    SKIP_PER_MARKET_CAP, SKIP_CASH, SKIP_NO_MARGIN, SKIP_UNIT_LT_ONE,
    SKIP_NO_MARGIN_FILE, SKIP_ROLL_WINDOW,
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
    otherwise is how a book ends up holding twelve units of the same bet. The
    5x sleeve is the same tape at different margin, so it is the same bucket.
    """
    if market in ("crypto", "crypto5x"):
        return "crypto"
    return (row.get("sector") or "").strip().lower() or "unclassified"


def _lev_cfg(market: str) -> dict | None:
    """The leverage config for a levered book, None for every cash book.

    Exactly one levered market exists (crypto5x) and the lookup is keyed on
    the config's own `market` field so a second sleeve cannot be added by
    editing this function -- it is added by declaring it in config, where the
    disclosure lives beside the numbers.
    """
    cfg = getattr(config, "TURTLE_5X", None)
    if cfg and market == cfg.get("market"):
        return cfg
    return None


def _exit_trigger(pos: dict) -> tuple[float, str]:
    """(price that takes the position out first, reason).

    For a cash position that is simply the 2N stop. For a levered position
    the ISOLATED-MARGIN liquidation line -- the price at which adverse MTM
    equals the posted margin -- competes with it, and whichever sits CLOSER
    to the market is hit first: max(stop, liq) for a long, min for a short.
    On a continuous 24/7 tape price passes the nearer line before the farther
    one, so the nearer line names the exit. With crypto's typical N a 2N stop
    sits well inside the 20% liquidation line and the stop fires first; the
    liquidation line binds when N is fat enough that 2N > posted/notional --
    which is exactly the position a levered account most needs to be honest
    about.
    """
    stop = float(pos["stop"])
    posted = _f(pos.get("posted"))
    units = _f(pos.get("units")) or 0.0
    if not posted or units <= 0:
        return stop, STOP
    avg = pos["cost_basis"] / units
    if pos["side"] == "long":
        liq = avg - posted / units
        return (liq, LIQUIDATION) if liq > stop else (stop, STOP)
    liq = avg + posted / units
    return (liq, LIQUIDATION) if liq < stop else (stop, STOP)


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

def _margin_room(book: dict, open_rows: list[dict], posted_new: float) -> bool:
    """The levered book's room check: posted margin, not notional.

    free = realised equity - every open position's posted margin. The same
    every-open-dollar discipline as the cash `_room_for` -- the caller hands
    it the SAME extended row list (managed + tail + self) so the two checks
    cannot drift apart in what they count.
    """
    free = realized_equity(book) - sum(_f(p.get("posted")) or 0.0
                                       for p in open_rows)
    return posted_new <= free + 1e-9


def _load_margin_file() -> dict | None:
    """The futures margin data, or None -- and None means NO NEW OPENS.

    The repo has no margin numbers and inventing them is on the kill list.
    Until a real file exists at config.TURTLE_FUTURES_MARGIN_FILE (schema:
    {"as_of": ..., "source": ..., "contracts": {"MES": {"initial": ...,
    "maintenance": ...}}}), every futures entry is refused with
    `no_margin_file` -- the sleeve stays 0/0 and says why.
    """
    path = os.path.join(ROOT, config.TURTLE_FUTURES_MARGIN_FILE)
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("contracts"), dict):
        return None
    return d


def _futures_gates(row: dict, margins: dict | None) -> tuple[bool, str, dict]:
    """The three hard gates on a NEW futures open (2026-08-22). Opens only --
    an already-held position keeps managing its exits; refusing to EXIT over
    a roll suspect would be backwards.

    (1) No roll suspect inside the current 20-bar N window: a back-adjusted
        roll step inflates today's N 13-22%, and N sets the size, the stop
        and the pyramid spacing all at once. The tape is refused, never
        winsorised -- the true-range formula is frozen law.
    (2) A REAL margin file must exist and carry this contract. No file, no
        open. Inventing initial margin is on the kill list.
    (unit >= 1 contract is gate three, checked where it always was.)
    """
    rolls = row.get("rolls") or {}
    if rolls.get("in_n_window"):
        return False, SKIP_ROLL_WINDOW, {
            "last_roll": rolls.get("last"),
            "note": "a roll suspect sits inside the current N window; "
                    "today's N is contaminated"}
    m = (margins or {}).get("contracts", {}).get(row["symbol"])
    if not m or not _f(m.get("initial")):
        return False, SKIP_NO_MARGIN_FILE, {
            "margin_file": config.TURTLE_FUTURES_MARGIN_FILE,
            "file_present": bool(margins)}
    return True, "", {"initial_margin": float(m["initial"])}


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


def _close_position(pos: dict, price: float, reason: str, day: str,
                    bar_date: str | None = None) -> dict:
    sign = 1.0 if pos["side"] == "long" else -1.0
    units = pos["units"]
    gross = sign * (price - pos["cost_basis"] / units) * units if units else 0.0
    fees = (_f(pos.get("fees")) or 0.0) + _cost(price, units)
    risk = config.TURTLE_STOP_N * pos["n"] * units
    pnl = gross - fees
    return {
        **{k: pos[k] for k in ("symbol", "market", "name", "sector", "side",
                               "system", "n", "units", "opened")},
        "closed": day, "closed_bar": bar_date or day,
        "exit": round(price, 8), "reason": reason,
        "entry_avg": round(pos["cost_basis"] / units, 8) if units else None,
        "gross": round(gross, 4), "fees": round(fees, 4), "pnl": round(pnl, 4),
        "r": round(pnl / risk, 4) if risk > 0 else None,
        "gross_r": round(gross / risk, 4) if risk > 0 else None,
        "mfe_r": pos.get("mfe_r", 0.0), "mae_r": pos.get("mae_r", 0.0),
        "fills": pos.get("fills", []),
        # audit fields for the levered book; absent on cash rows
        **({"posted": pos["posted"]} if pos.get("posted") else {}),
    }


def update(market: str, rows: list[dict], day: str | None = None) -> dict:
    """Advance the book one session. Returns the saved book."""
    day = day or datetime.date.today().isoformat()
    book = load_book(market)
    if not book.get("started"):
        book["started"] = day
    lev = _lev_cfg(market)
    if lev:
        # The disclosure travels WITH the data: the page renders these
        # numbers from the payload, so the sentence about what 5x means can
        # never describe a book running something else.
        book["params"] = {k: v for k, v in lev.items() if k != "market"}
    margins = _load_margin_file() if market == "futures" else None
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
        # For a cash position the trigger IS the 2N stop. For a levered one
        # the isolated-margin liquidation line competes with it and the
        # nearer line names the exit -- see _exit_trigger.
        trigger, trig_reason = _exit_trigger(pos)
        exit_px = reason = None
        if pos["side"] == "long":
            if lo <= trigger:
                exit_px, reason = min(trigger, op), trig_reason
            elif chan is not None and lo <= chan:
                exit_px, reason = min(chan, op), CHANNEL
        else:
            if hi >= trigger:
                exit_px, reason = max(trigger, op), trig_reason
            elif chan is not None and hi >= chan:
                exit_px, reason = max(chan, op), CHANNEL
        # A LIQUIDATION FILLS AT THE LIQUIDATION PRICE, never at a gap.
        # Isolated margin cannot lose more than it posted -- the exchange
        # takes the position at the bankruptcy price -- and crypto trades
        # continuously, so a daily-bar "gap" through the liq line is a
        # sampling artefact, not an untradeable jump. Stops keep the gap
        # convention (an equity genuinely can gap through a resting stop).
        if reason == LIQUIDATION:
            exit_px = trigger
        if exit_px is not None:
            t = _close_position(pos, float(exit_px), reason, day,
                                bar_date=row.get("date"))
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
            # THE ROOM CHECK MUST COUNT EVERY OPEN DOLLAR, exactly as the unit
            # ceilings below count every open unit. Handing it only
            # `still_open` excluded the position BEING ADDED TO and the
            # unmanaged tail -- so DOGE's third unit on 2026-08-22 passed a
            # check that ignored DOGE's own ~$2.5k of basis plus GT's $1.5k,
            # and the crypto book ended the run holding $5,239 of basis on a
            # $4,186 cap. Same conservative reading as `_caps_allow`: the tail
            # may exit later this session and free cash, but that is not
            # knowable here, and declining the add is the safe side. The
            # levered book runs the same discipline over POSTED MARGIN.
            all_open = still_open + open_list[idx + 1:] + [pos]
            if lev:
                posted_add = abs(fill * add_units) / float(lev["leverage"])
                room = add_units > 0 and _margin_room(book, all_open, posted_add)
                room_skip = _skip(day, market, pos["symbol"], "add",
                                  SKIP_NO_MARGIN,
                                  {"units_held": len(pos["fills"]),
                                   "posted_want": round(posted_add, 2),
                                   "equity": round(realized_equity(book), 2)})
            else:
                room = add_units > 0 and _room_for(book, all_open,
                                                   fill * add_units)
                room_skip = _skip(day, market, pos["symbol"], "add", SKIP_CASH,
                                  {"units_held": len(pos["fills"]),
                                   "want_notional": round(fill * add_units, 2),
                                   "equity": round(realized_equity(book), 2)})
            if not room:
                skips.append(room_skip)
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
            if lev:
                pos["posted"] = round((_f(pos.get("posted")) or 0.0)
                                      + abs(fill * add_units)
                                      / float(lev["leverage"]), 6)
            events.append(f"ADD {pos['symbol']} u{len(pos['fills'])} @ {fill:.6g}")

        # ---- the stop an add just raised, on the same bar -------------------
        # (or, on the levered book, the liquidation line the add just moved)
        trigger, trig_reason = _exit_trigger(pos)
        if (sign > 0 and lo <= trigger) or (sign < 0 and hi >= trigger):
            px = min(trigger, op) if sign > 0 else max(trigger, op)
            if trig_reason == LIQUIDATION:
                px = trigger        # isolated margin caps the loss (above)
            t = _close_position(pos, float(px), trig_reason, day,
                                bar_date=row.get("date"))
            book.setdefault("closed", []).append(t)
            events.append(f"EXIT {pos['symbol']} {t['reason']}-after-add {t['r']}R")
            continue
        still_open.append(pos)

    # ---- enter, last, so a slot freed today is usable today -----------------
    held = {p["symbol"] for p in still_open}
    # A name that exited on a bar cannot be re-entered WHILE THAT BAR IS STILL
    # THE SIGNAL BAR. The manage loop can flatten a name and the entry loop
    # would then see it flat and refill the very breakout that just stopped
    # out -- the rules wait for a NEW channel break, not the same one still
    # standing. The identity of "the same bar" is the row's OWN bar date, not
    # the run date: this book runs many times per bar (crypto every four
    # hours; the daily all-markets pass re-reads Friday's NASDAQ bar on
    # Saturday and Sunday), and keying on the run date let a Friday stop
    # refill off the SAME Friday bar at Saturday's run because the calendar
    # had moved while the tape had not. Closed rows written before this fix
    # carry no `closed_bar`; they fall back to the run date they were closed
    # on, which is exactly the old rule's behaviour for them.
    closed_bars: dict[str, set] = {}
    for t in book.get("closed", []):
        if t.get("symbol"):        # a malformed row can refuse nothing
            closed_bars.setdefault(t["symbol"], set()).add(
                t.get("closed_bar") or t.get("closed"))

    def _same_bar_blocked(r: dict) -> bool:
        return (r.get("date") or day) in closed_bars.get(r["symbol"], ())

    fired = [r for r in rows if r.get("signal")
             and r["symbol"] not in held and not _same_bar_blocked(r)]
    for r in rows:
        if r.get("signal") and r["symbol"] not in held and _same_bar_blocked(r):
            skips.append(_skip(day, market, r["symbol"], "entry",
                               SKIP_SAME_BAR_REENTRY,
                               {"signal": r["signal"],
                                "bar": r.get("date") or day}))
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
            # FUTURES HARD GATES (2026-08-22), after the sizing honesty above:
            # no roll suspect inside the current N window, and a REAL margin
            # file -- no file, no open. The sleeve stays 0/0 and says why.
            gate_ok, gate_why, gate_detail = _futures_gates(row, margins)
            if not gate_ok:
                skips.append(_skip(day, market, row["symbol"], "entry",
                                   gate_why, dict(gate_detail, system=system)))
                continue
            units = whole * dpp
            # A futures position consumes MARGIN, not notional. With no
            # margin file the gates above already refused; when a real file
            # exists, the initial margin it states must fit the free equity
            # -- counted over every open futures position's own posted IM,
            # same discipline as the cash and 5x room checks.
            need_im = whole * float(gate_detail.get("initial_margin") or 0.0)
            held_im = sum(_f(p.get("im")) or 0.0 for p in still_open)
            if need_im > 0 and need_im > realized_equity(book) - held_im:
                skips.append(_skip(day, market, row["symbol"], "entry",
                                   SKIP_NO_MARGIN,
                                   {"need_im": round(need_im, 2),
                                    "free": round(realized_equity(book)
                                                  - held_im, 2),
                                    "system": system}))
                continue
            pos = _open_position(row, market, side, system, px, units, n, day)
            pos["contracts"] = whole
            pos["contract"] = kind
            pos["dpp"] = dpp
            if need_im > 0:
                pos["im"] = round(need_im, 2)
            still_open.append(pos)
            events.append(f"ENTER {row['symbol']} S{system} {side} "
                          f"{whole}x{kind} @ {px:.6g}")
            continue

        units = unit_units(sizing_equity(book), n)
        if lev:
            # THE UNIT FORMULA DOES NOT MOVE -- 1% of equity per N, fractional
            # coins. What leverage changes is only what the unit COSTS to
            # hold: posted margin of notional/leverage instead of the full
            # notional in cash. That is the entire vehicle difference, and it
            # is why the cash book saturated at 3 units while this one runs
            # into the Turtle ceilings instead.
            posted_new = abs(px * units) / float(lev["leverage"])
            if units <= 0 or not _margin_room(book, still_open, posted_new):
                skips.append(_skip(day, market, row["symbol"], "entry",
                                   SKIP_NO_MARGIN,
                                   {"posted_want": round(posted_new, 2),
                                    "equity": round(realized_equity(book), 2),
                                    "system": system}))
                continue
        elif units <= 0 or not _room_for(book, still_open, px * units):
            skips.append(_skip(day, market, row["symbol"], "entry", SKIP_CASH,
                               {"want_notional": round(px * units, 2),
                                "equity": round(realized_equity(book), 2),
                                "system": system}))
            continue
        pos = _open_position(row, market, side, system, px, units, n, day)
        if lev:
            pos["posted"] = round(abs(px * units) / float(lev["leverage"]), 6)
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


def write_combined(markets=("asx", "nasdaq", "crypto", "crypto5x",
                            "futures")) -> str:
    """The DERIVED all-markets view. Per-market files stay canonical -- a
    market's run can only ever write its own, so a cross-market clobber is
    impossible by construction -- and this is regenerated from them.

    FUTURES IS IN THE DEFAULT, and it matters: the page's BOOK view reads
    ONLY this combined file, so a futures book missing here is a futures book
    that exists on disk and renders nowhere -- including the cash-unconstrained
    disclosure turtle.js keys off open futures positions. A market with no
    file yet contributes nothing (the loop skips absent paths), so the default
    is safe before the first futures run ever lands."""
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
        # A levered sleeve travels WITH its disclosure: the page renders the
        # leverage sentence from these params, so the combined view can never
        # present the 5x series as one more cash book.
        summ = b.get("summary", {})
        if b.get("params"):
            summ = {**summ, "params": b["params"]}
        combined["by_market"][m] = summ
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
    out = {
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
    # Margin visibility, ONLY on a book that declares leverage in its own
    # params -- the combined view's open list mixes cash and levered rows, and
    # a "free margin" figure computed against a pooled face-value equity would
    # be exactly the kind of number this repo exists to refuse.
    if (book.get("params") or {}).get("leverage"):
        posted = sum(_f(p.get("posted")) or 0.0 for p in book.get("open", []))
        out["leverage"] = book["params"]["leverage"]
        out["posted_margin"] = round(posted, 2)
        out["free_margin"] = round(eq - posted, 2)
    return out
