"""TURTLE portfolio replay -- one shared equity per sleeve, frozen rules.

The nightly per-name replay answers "what did these rules do on this name".
It structurally CANNOT answer "would a $5,000 account have made money",
because every name is replayed with its own private equity: no competition
for slots, no shared drawdown, no cash or margin ceiling, no unit caps
binding across names. This module runs the missing experiment: every symbol
in a sleeve walks the SAME calendar against the SAME equity, entries compete
for the same 4/6/12 unit ceilings, losses shrink the next unit for everyone,
and the vehicle's own constraint (cash notional at 1x, posted margin at 5x,
whole contracts + real margin data for futures) binds exactly as the forward
book enforces it.

WHAT THIS IS NOT, stated here and in the payload: it is NOT walk-forward
(one pass, no out-of-sample), NOT the Turtle return (the universe is today's
surviving names, selected on outcomes the system could not have known), and
NOT evidence that outranks the forward books -- it is the portfolio-shaped
upper bound the per-name replay was being misread as.

Frozen law, unchanged from scanner/turtle.py: Wilder ATR-20 N, 20/10 + 55/20
channels shifted one bar, S2 tested first (failsafe), the S1 filter from the
shadow chain, entry-time N for the life of the trade, 2N shared stop raised
by every 1/2N add to max 4 units, exits before adds, entry-bar and add-raised
stops tested on their own bar, gaps fill at the open, 15 bps a side,
compounding drawdown step-down. Nothing here retunes anything.

Determinism: same-day entries are ordered by THAT BAR's dollar volume
descending, then symbol ascending -- declared in the payload, because a
portfolio replay whose tie-break is dict order is a random number generator
with a caption.

Writes public/data/turtle_portfolio.json and NOTHING else (test-pinned).
"""

from __future__ import annotations

import datetime
import json
import os

import numpy as np

from . import config, output, turtle

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(ROOT, "public", "data", "turtle_portfolio.json")

CAVEAT = ("Shared-equity replay of the frozen Turtle rules over TODAY'S "
          "surviving universe. One in-sample pass: not walk-forward, not a "
          "forward record, not 'the Turtle return'. The forward books are "
          "the evidence; this is the portfolio-shaped context for them.")

ORDERING = "same-day entries by that bar's dollar volume desc, then symbol"

# refusal keys (a sleeve's skip vocabulary; the forward book's enum, minus
# same_bar_reentry which a single pass per bar cannot produce)
R_CASH = "cash"
R_NO_MARGIN = "no_margin"
R_DIRECTION = "direction_cap"
R_CLOSE_CORR = "close_corr_cap"
R_PER_MARKET = "per_market_cap"
R_UNIT_LT_ONE = "unit_lt_one"
R_NO_MARGIN_FILE = "no_margin_file"
R_ROLL_WINDOW = "roll_window"


def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _prep(df, market: str) -> dict | None:
    """One symbol's arrays: bars, N, shifted channels, the S1 filter's
    per-bar verdict, per-bar dollar volume, the liquidity start index, and
    (for futures frames) whether a roll suspect sits in each bar's N window.

    The filter verdict is the engine's own `_Shadow`, stepped bar by bar
    exactly as `turtle.replay` steps it: blocked[i] is the state AFTER the
    shadow has seen bar i, which is the state the engine's entry test reads.
    """
    if df is None or len(df) < config.TURTLE_MIN_BARS:
        return None
    for col in ("Open", "High", "Low", "Close"):
        if col not in df.columns:
            return None
    ch = turtle.channels(df)
    nn = turtle.compute_n(df).to_numpy(dtype="float64")
    o = df["Open"].to_numpy(dtype="float64")
    h = df["High"].to_numpy(dtype="float64")
    lo = df["Low"].to_numpy(dtype="float64")
    cl = df["Close"].to_numpy(dtype="float64")
    dates = [str(d)[:10] for d in (df["Date"] if "Date" in df.columns
                                   else df.index)]
    start_i, _share = turtle.tradeable_from(df, market)
    start = max(config.TURTLE_S2_ENTRY, config.TURTLE_N_PERIOD) + 1
    start = max(start, int(start_i))

    shadow = turtle._Shadow()
    blocked = np.zeros(len(df), dtype=bool)
    s1_hi = ch["s1_hi"].to_numpy(dtype="float64")
    s1_lo = ch["s1_lo"].to_numpy(dtype="float64")
    x1_lo = ch["x1_lo"].to_numpy(dtype="float64")
    x1_hi = ch["x1_hi"].to_numpy(dtype="float64")
    for i in range(len(df)):
        n_prev = nn[i - 1] if i else float("nan")
        shadow.step(o[i], h[i], lo[i], n_prev, s1_hi[i], s1_lo[i],
                    x1_lo[i], x1_hi[i])
        blocked[i] = shadow.last_was_winner is True

    if "Volume" in df.columns:
        dvol = (df["Close"] * df["Volume"]).to_numpy(dtype="float64")
    else:
        dvol = np.zeros(len(df))

    roll_win = np.zeros(len(df), dtype=bool)
    rolls = turtle.roll_suspects(df)
    if rolls["bars"]:
        gap = (df["Open"] - df["Close"].shift(1)).abs()
        rng = (df["High"] - df["Low"]).replace(0, np.nan)
        flag = ((gap / rng) > config.TURTLE_ROLL_GAP_RATIO).fillna(False) \
            .to_numpy()
        w = config.TURTLE_N_PERIOD
        for i in range(len(df)):
            roll_win[i] = bool(flag[max(0, i - w + 1):i + 1].any())

    return {"o": o, "h": h, "l": lo, "c": cl, "nn": nn, "dates": dates,
            "idx": {d: i for i, d in enumerate(dates)},
            "s1_hi": s1_hi, "s2_hi": ch["s2_hi"].to_numpy(dtype="float64"),
            "s1_lo": s1_lo, "s2_lo": ch["s2_lo"].to_numpy(dtype="float64"),
            "x1_lo": x1_lo, "x1_hi": x1_hi,
            "x2_lo": ch["x2_lo"].to_numpy(dtype="float64"),
            "x2_hi": ch["x2_hi"].to_numpy(dtype="float64"),
            "blocked": blocked, "dvol": dvol, "start": start,
            "roll_win": roll_win}


def _dd_equity(equity: float, peak: float) -> float:
    return turtle.drawdown_equity(equity, peak)


def replay_sleeve(frames: dict, *, market: str, equity_start: float,
                  leverage: float = 1.0, contracts: dict | None = None,
                  margins: dict | None = None,
                  allow_shorts: bool | None = None,
                  keep_trades: bool = False) -> dict:
    """Walk every symbol's frame against ONE shared equity under the frozen
    rules. `contracts` (futures) maps symbol -> {dpp, micro, micro_dpp};
    `margins` is the parsed real margin file or None (None = nothing opens).
    """
    allow_shorts = (config.TURTLE_ALLOW_SHORTS if allow_shorts is None
                    else allow_shorts)
    lev = float(leverage)
    stop_n = config.TURTLE_STOP_N
    step_n = config.TURTLE_PYRAMID_STEP_N
    max_units = config.TURTLE_MAX_UNITS
    bps = config.TURTLE_COST_BPS / 10_000.0

    prepped = {}
    for sym, df in frames.items():
        p = _prep(df, market)
        if p is not None:
            prepped[sym] = p
    calendar = sorted({d for p in prepped.values() for d in p["dates"]})

    equity = float(equity_start)
    peak_marked = equity
    max_dd_pct = 0.0
    open_pos: dict[str, dict] = {}
    trades: list[dict] = []
    refused: dict[str, int] = {}
    fees_paid = 0.0
    last_close: dict[str, float] = {}

    def _refuse(reason):
        refused[reason] = refused.get(reason, 0) + 1

    def _units_side(side):
        return sum(p["fills"] for p in open_pos.values() if p["side"] == side)

    # ONE close-correlation bucket per non-futures sleeve, deliberately:
    # crypto because it moves as one market (the forward book's own rule),
    # equities because a single-market sleeve IS one factor -- the repo's own
    # finding about these tapes. Futures buckets by contract group, the only
    # sleeve with a real taxonomy to bucket by.
    def _bucket_of(sym):
        return (contracts or {}).get(sym, {}).get("group", "one") \
            if contracts else "one"

    def _units_in_bucket(side, bucket):
        if not contracts:
            return _units_side(side)
        return sum(p["fills"] for s, p in open_pos.items()
                   if p["side"] == side and _bucket_of(s) == bucket)

    def _room_ok(notional):
        if lev > 1.0:
            posted_new = abs(notional) / lev
            posted_held = sum(p.get("posted") or 0.0
                              for p in open_pos.values())
            return posted_new <= equity - posted_held + 1e-9, R_NO_MARGIN
        used = sum(abs(p["cost"]) for p in open_pos.values())
        cap = equity * (config.TURTLE_BOOK_MAX_NOTIONAL_PCT / 100.0)
        return (used + abs(notional)) <= cap + 1e-9, R_CASH

    def _sizing_equity():
        pk = max(equity_start, max(
            (t["equity_after"] for t in trades), default=equity_start))
        return _dd_equity(equity, pk)

    def _unit_size(n):
        """1% of the drawdown-adjusted SHARED equity per N -- the formula
        that does not move. Shared is the whole experiment: a loss anywhere
        in the sleeve shrinks the next unit everywhere in it."""
        if not (np.isfinite(n) and n > 0):
            return 0.0
        return (config.TURTLE_RISK_PCT * _sizing_equity()) / n

    def _close(sym, pos, px, reason, date):
        nonlocal equity, fees_paid
        sign = 1.0 if pos["side"] == "long" else -1.0
        avg = pos["cost"] / pos["units"] if pos["units"] else px
        gross = sign * (px - avg) * pos["units"]
        fee = pos["fees"] + abs(px * pos["units"]) * bps
        pnl = gross - fee
        risk = stop_n * pos["n"] * pos["units"]
        equity += pnl
        fees_paid += fee
        trades.append({
            "symbol": sym, "side": pos["side"], "system": pos["system"],
            "entry_date": pos["entry_date"], "exit_date": date,
            "units": pos["fills"], "reason": reason,
            "r": round(pnl / risk, 4) if risk > 0 else 0.0,
            "pnl": round(pnl, 2), "equity_after": round(equity, 2),
        })
        del open_pos[sym]

    def _trigger(pos):
        stop = pos["stop"]
        if lev <= 1.0 or not pos.get("posted") or pos["units"] <= 0:
            return stop, "stop"
        avg = pos["cost"] / pos["units"]
        if pos["side"] == "long":
            liq = avg - pos["posted"] / pos["units"]
            return (liq, "liquidation") if liq > stop else (stop, "stop")
        liq = avg + pos["posted"] / pos["units"]
        return (liq, "liquidation") if liq < stop else (stop, "stop")

    for date in calendar:
        # ---- manage holdings: exits before adds, add-raised stop retested --
        for sym in list(open_pos):
            p = prepped.get(sym)
            i = p["idx"].get(date) if p else None
            if i is None:
                continue
            pos = open_pos[sym]
            o, h, l = p["o"][i], p["h"][i], p["l"][i]
            last_close[sym] = p["c"][i]
            sign = 1.0 if pos["side"] == "long" else -1.0
            x_lo = p["x1_lo"][i] if pos["system"] == 1 else p["x2_lo"][i]
            x_hi = p["x1_hi"][i] if pos["system"] == 1 else p["x2_hi"][i]
            trig, trig_why = _trigger(pos)
            exit_px = why = None
            if pos["side"] == "long":
                if l <= trig:
                    exit_px, why = min(trig, o), trig_why
                elif np.isfinite(x_lo) and l <= x_lo:
                    exit_px, why = min(x_lo, o), "channel"
            else:
                if h >= trig:
                    exit_px, why = max(trig, o), trig_why
                elif np.isfinite(x_hi) and h >= x_hi:
                    exit_px, why = max(x_hi, o), "channel"
            if exit_px is not None:
                # a liquidation fills AT the liq price -- isolated margin
                # cannot lose more than it posted (see turtle_book)
                if why == "liquidation":
                    exit_px = trig
                _close(sym, pos, float(exit_px), why, date)
                continue
            # adds: 1/2N rungs off the LAST FILL at entry-time N
            while pos["fills"] < max_units:
                level = pos["last_fill"] + sign * step_n * pos["n"]
                if (sign > 0 and h < level) or (sign < 0 and l > level):
                    break
                fill = max(level, o) if sign > 0 else min(level, o)
                if contracts:
                    info = contracts.get(sym) or {}
                    dpp = info.get("micro_dpp") or info.get("dpp") or 0
                    whole = int((config.TURTLE_RISK_PCT * _sizing_equity())
                                / (pos["n"] * dpp)) if dpp else 0
                    if whole < 1:
                        _refuse(R_UNIT_LT_ONE)
                        break
                    add_units = float(whole * dpp)
                else:
                    add_units = _unit_size(pos["n"])
                if add_units <= 0:
                    break
                ok, why_room = _room_ok(fill * add_units)
                if not ok:
                    _refuse(why_room)
                    break
                side_u = _units_side(pos["side"])
                if side_u + 1 > config.TURTLE_MAX_UNITS_DIRECTION:
                    _refuse(R_DIRECTION)
                    break
                bkt = _bucket_of(sym)
                if _units_in_bucket(pos["side"], bkt) + 1 \
                        > config.TURTLE_MAX_UNITS_CLOSE_CORR:
                    _refuse(R_CLOSE_CORR)
                    break
                fee = abs(fill * add_units) * bps
                pos["cost"] += fill * add_units
                pos["units"] += add_units
                pos["fills"] += 1
                pos["last_fill"] = float(fill)
                pos["stop"] = float(fill - sign * stop_n * pos["n"])
                pos["fees"] += fee
                if lev > 1.0:
                    pos["posted"] = (pos.get("posted") or 0.0) \
                        + abs(fill * add_units) / lev
            if sym in open_pos and pos["fills"] >= max_units:
                want = (sign > 0 and h >= pos["last_fill"] + step_n * pos["n"]) \
                    or (sign < 0 and l <= pos["last_fill"] - step_n * pos["n"])
                if want:
                    _refuse(R_PER_MARKET)
            # the stop (or liq line) an add just raised, on the same bar
            if sym in open_pos:
                trig, trig_why = _trigger(pos)
                if (sign > 0 and l <= trig) or (sign < 0 and h >= trig):
                    px = min(trig, o) if sign > 0 else max(trig, o)
                    if trig_why == "liquidation":
                        px = trig
                    _close(sym, pos, float(px), trig_why, date)

        # ---- entries, deterministic order --------------------------------
        cands = []
        for sym, p in prepped.items():
            if sym in open_pos:
                continue
            i = p["idx"].get(date)
            if i is None or i < p["start"]:
                continue
            last_close[sym] = p["c"][i]
            n_prev = p["nn"][i - 1] if i else float("nan")
            if not (np.isfinite(n_prev) and n_prev > 0):
                continue
            # a symbol that exited on THIS bar cannot re-enter on it
            if any(t["symbol"] == sym and t["exit_date"] == date
                   for t in trades):
                continue
            o, h, l = p["o"][i], p["h"][i], p["l"][i]
            side = sysno = None
            fill = 0.0
            if np.isfinite(p["s2_hi"][i]) and h > p["s2_hi"][i]:
                side, sysno, fill = "long", 2, max(p["s2_hi"][i], o)
            elif (not p["blocked"][i] and np.isfinite(p["s1_hi"][i])
                  and h > p["s1_hi"][i]):
                side, sysno, fill = "long", 1, max(p["s1_hi"][i], o)
            elif allow_shorts and np.isfinite(p["s2_lo"][i]) \
                    and l < p["s2_lo"][i]:
                side, sysno, fill = "short", 2, min(p["s2_lo"][i], o)
            elif (allow_shorts and not p["blocked"][i]
                  and np.isfinite(p["s1_lo"][i]) and l < p["s1_lo"][i]):
                side, sysno, fill = "short", 1, min(p["s1_lo"][i], o)
            if side is None:
                continue
            cands.append((-float(p["dvol"][i]), sym, side, sysno,
                          float(fill), float(n_prev), i))
        cands.sort()

        for _neg_dvol, sym, side, sysno, fill, n_prev, i in cands:
            p = prepped[sym]
            sign = 1.0 if side == "long" else -1.0
            side_u = _units_side(side)
            if side_u + 1 > config.TURTLE_MAX_UNITS_DIRECTION:
                _refuse(R_DIRECTION)
                continue
            bkt = _bucket_of(sym)
            if _units_in_bucket(side, bkt) + 1 \
                    > config.TURTLE_MAX_UNITS_CLOSE_CORR:
                _refuse(R_CLOSE_CORR)
                continue
            if contracts:
                info = contracts.get(sym) or {}
                dpp = info.get("micro_dpp") or info.get("dpp") or 0
                if p["roll_win"][i]:
                    _refuse(R_ROLL_WINDOW)
                    continue
                m = (margins or {}).get("contracts", {}).get(sym)
                if not m or not _f(m.get("initial")):
                    _refuse(R_NO_MARGIN_FILE)
                    continue
                whole = int((config.TURTLE_RISK_PCT * _sizing_equity())
                            / (n_prev * dpp)) if (dpp and n_prev > 0) else 0
                if whole < 1:
                    _refuse(R_UNIT_LT_ONE)
                    continue
                need_im = whole * float(m["initial"])
                held_im = sum(q.get("im") or 0.0 for q in open_pos.values())
                if need_im > equity - held_im:
                    _refuse(R_NO_MARGIN)
                    continue
                units = whole * dpp
                im = need_im
            else:
                units = _unit_size(n_prev)
                if units <= 0:
                    continue
                ok, why_room = _room_ok(fill * units)
                if not ok:
                    _refuse(why_room)
                    continue
                im = 0.0
            fee = abs(fill * units) * bps
            pos = {"side": side, "system": sysno, "n": float(n_prev),
                   "units": float(units), "cost": float(fill * units),
                   "last_fill": float(fill), "fills": 1,
                   "stop": float(fill - sign * stop_n * n_prev),
                   "entry_date": date, "fees": fee}
            if lev > 1.0:
                pos["posted"] = abs(fill * units) / lev
            if im:
                pos["im"] = im
            open_pos[sym] = pos
            # THE ENTRY BAR CAN ALSO TAKE YOU OUT -- same law as the engine.
            trig, trig_why = _trigger(pos)
            if (sign > 0 and p["l"][i] <= trig) \
                    or (sign < 0 and p["h"][i] >= trig):
                px = min(trig, p["o"][i]) if sign > 0 \
                    else max(trig, p["o"][i])
                if trig_why == "liquidation":
                    px = trig
                _close(sym, pos, float(px), trig_why, date)

        # ---- the marked curve, for an honest drawdown --------------------
        marked = equity
        for sym, pos in open_pos.items():
            c = last_close.get(sym)
            if c is None:
                continue
            sign = 1.0 if pos["side"] == "long" else -1.0
            avg = pos["cost"] / pos["units"] if pos["units"] else c
            marked += sign * (c - avg) * pos["units"]
        peak_marked = max(peak_marked, marked)
        if peak_marked > 0:
            max_dd_pct = max(max_dd_pct,
                             100.0 * (peak_marked - marked) / peak_marked)

    # ---- summarise -------------------------------------------------------
    rs = [t["r"] for t in trades]
    wins = sum(1 for r in rs if r > 0)
    srt = sorted(rs)
    med = None
    if srt:
        m = len(srt) // 2
        med = srt[m] if len(srt) % 2 else 0.5 * (srt[m - 1] + srt[m])
    total = sum(rs)
    top = sorted(rs, reverse=True)[:10]
    marked_end = equity
    for sym, pos in open_pos.items():
        c = last_close.get(sym)
        if c is None:
            continue
        sign = 1.0 if pos["side"] == "long" else -1.0
        avg = pos["cost"] / pos["units"] if pos["units"] else c
        marked_end += sign * (c - avg) * pos["units"]
    out_extra = {"trade_rows": trades} if keep_trades else {}
    return {
        **out_extra,
        "market": market,
        "equity_start": round(equity_start, 2),
        "leverage": lev,
        "universe_size": len(prepped),
        "equity_realized": round(equity, 2),
        "equity_marked": round(marked_end, 2),
        "return_pct_marked": round(100.0 * (marked_end - equity_start)
                                   / equity_start, 2) if equity_start else None,
        "max_dd_pct_marked": round(max_dd_pct, 2),
        "trades": len(trades),
        "wins": wins,
        "win_pct": round(100.0 * wins / len(rs), 1) if rs else None,
        "total_r": round(total, 2),
        "mean_r": round(total / len(rs), 4) if rs else None,
        "median_r": round(med, 4) if med is not None else None,
        "top10_share": (round(sum(top) / total, 3) if total > 0 else None),
        "open_at_end": {"positions": len(open_pos),
                        "units": sum(p["fills"] for p in open_pos.values()),
                        "symbols": sorted(open_pos)},
        "refused_units": refused,
        "fees_paid": round(fees_paid, 2),
        "ordering": ORDERING,
        "caveat": CAVEAT,
    }


def write_sleeves(computed: dict[str, dict]) -> str:
    """Merge this run's sleeves into the published file (the sector_breadth
    pattern: a run computes only its own markets' sleeves and must not drop
    a sibling's block)."""
    existing = {}
    try:
        with open(OUT_PATH, encoding="utf-8") as fh:
            existing = json.load(fh).get("sleeves", {})
    except (OSError, ValueError):
        existing = {}
    existing.update(computed)
    payload = {
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(timespec="seconds"),
        "caveat": CAVEAT,
        "ordering": ORDERING,
        "sleeves": existing,
    }
    output.write_json(OUT_PATH, payload, indent=1, ensure_ascii=False,
                      newline=True)
    return OUT_PATH
