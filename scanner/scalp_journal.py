"""Scalp paper-trade journal — intraday forward test on 1h bars.

Different from the swing journal:
  • 1h bar resolution — positions can close the same day
  • Fixed ATR stop (no SuperTrend trailing) — scalp is short-duration
  • Dollar P&L with $40 round-trip brokerage baked in
  • Daily trade cap (5/day) and daily loss limit ($500) enforced
  • $1,000 margin × 5× leverage = $5,000 notional per trade
"""

import datetime as dt
import json
import pathlib

import numpy as np

from . import config

ROOT                 = pathlib.Path(__file__).resolve().parents[1]
SCALP_JOURNAL_FILE   = ROOT / "journal" / "scalp_journal.json"
PUBLIC_SCALP_JOURNAL = ROOT / "public" / "data" / "scalp_journal.json"

NOTIONAL  = config.SCALP_POSITION_SIZE * config.SCALP_LEVERAGE  # $5,000
BROK_RT   = config.SCALP_BROKERAGE_EACH_WAY * 2                  # $40
MAX_DAILY = config.SCALP_MAX_TRADES_PER_DAY                       # 5
MAX_LOSS  = config.SCALP_MAX_DAILY_LOSS                           # $500


def _load() -> dict:
    if SCALP_JOURNAL_FILE.exists():
        try:
            return json.loads(SCALP_JOURNAL_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"open": [], "closed": []}


def _dir_stats(closed: list, open_: list) -> dict:
    rs   = np.array([c["r"]   for c in closed], dtype=float) if closed else np.array([])
    pnls = np.array([c["pnl"] for c in closed], dtype=float) if closed else np.array([])
    wins = rs[rs > 0]
    return {
        "open":                len(open_),
        "closed":              len(closed),
        "win_rate":            round(len(wins) / len(rs) * 100, 1) if len(rs) else 0.0,
        "total_r":             round(float(rs.sum()),   2) if len(rs)   else 0.0,
        "total_pnl":           round(float(pnls.sum()), 2) if len(pnls) else 0.0,
        "open_unrealised_pnl": round(sum(p.get("unreal_pnl", 0) or 0 for p in open_), 2),
    }


def summarize(j: dict) -> dict:
    today        = dt.datetime.utcnow().strftime("%Y-%m-%d")
    today_closed = [c for c in j["closed"] if (c.get("opened_ts") or "")[:10] == today]
    today_pnl    = round(sum(c.get("pnl", 0) for c in today_closed), 2)
    trades_used  = len(today_closed) + len(j["open"])
    long_open    = [p for p in j["open"]   if p["direction"] == "long"]
    short_open   = [p for p in j["open"]   if p["direction"] == "short"]
    long_closed  = [c for c in j["closed"] if c["direction"] == "long"]
    short_closed = [c for c in j["closed"] if c["direction"] == "short"]
    return {
        "notional":          NOTIONAL,
        "brokerage_rt":      BROK_RT,
        "max_daily_trades":  MAX_DAILY,
        "max_daily_loss":    MAX_LOSS,
        "today_trades":      trades_used,
        "today_pnl":         today_pnl,
        "trades_left_today": max(0, MAX_DAILY - trades_used),
        "longs":  _dir_stats(long_closed,  long_open),
        "shorts": _dir_stats(short_closed, short_open),
    }


def _save(j: dict) -> None:
    j["updated_at"] = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    SCALP_JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCALP_JOURNAL_FILE.write_text(json.dumps(j, indent=2), encoding="utf-8")

    long_open    = [p for p in j["open"]   if p["direction"] == "long"]
    short_open   = [p for p in j["open"]   if p["direction"] == "short"]
    long_closed  = [c for c in j["closed"] if c["direction"] == "long"]
    short_closed = [c for c in j["closed"] if c["direction"] == "short"]

    all_closed = sorted(j["closed"], key=lambda c: c.get("opened_ts", ""))

    PUBLIC_SCALP_JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_SCALP_JOURNAL.write_text(json.dumps({
        "updated_at":    j["updated_at"],
        "stats":         summarize(j),
        "open_longs":    long_open,
        "open_shorts":   short_open,
        "closed_longs":  long_closed[-200:],
        "closed_shorts": short_closed[-200:],
        "all_closed":    all_closed[-400:],
    }, indent=2), encoding="utf-8")


def _close_pos(pos: dict, price: float, ts: str, reason: str, bars: int) -> dict:
    direction = pos["direction"]
    units     = pos["units"]
    if direction == "short":
        risk  = pos["stop"] - pos["entry"]
        r_val = round((pos["entry"] - price) / risk, 2) if risk > 0 else 0.0
        gross = units * (pos["entry"] - price)
    else:
        risk  = pos["entry"] - pos["stop"]
        r_val = round((price - pos["entry"]) / risk, 2) if risk > 0 else 0.0
        gross = units * (price - pos["entry"])
    pnl = round(gross - BROK_RT, 2)
    return {**pos, "status": "closed", "exit": round(float(price), 8),
            "exit_ts": ts, "reason": reason, "bars": bars, "r": r_val, "pnl": pnl}


def _walk_1h(df, pos: dict) -> dict:
    """Walk a scalp position forward on 1h bars; close on stop or target."""
    if df is None or len(df) < 2:
        return pos
    entry, stop, target = pos["entry"], pos["stop"], pos["target"]
    direction = pos["direction"]
    units     = pos["units"]

    risk = (stop - entry) if direction == "short" else (entry - stop)
    if risk <= 0:
        return _close_pos(pos, entry, pos["opened_ts"], "invalid", 0)

    if getattr(df.index, "tz", None) is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    ts_list = [t.isoformat() for t in df.index]
    closes  = df["Close"].to_numpy(dtype=float)
    highs   = df["High"].to_numpy(dtype=float)
    lows    = df["Low"].to_numpy(dtype=float)

    opened = pos["opened_ts"][:19]
    start  = next((k for k, ts in enumerate(ts_list) if ts > opened), None)
    if start is None:
        c = float(closes[-1])
        pos["current"]    = round(c, 8)
        pos["unreal_r"]   = round((c - entry) / risk if direction == "long" else (entry - c) / risk, 2)
        pos["unreal_pnl"] = round((units * (c - entry) if direction == "long" else units * (entry - c)) - BROK_RT, 2)
        return pos

    if direction == "short":
        for i in range(start, len(df)):
            if highs[i] >= stop:
                return _close_pos(pos, stop,   ts_list[i], "stop",   i - start + 1)
            if lows[i]  <= target:
                return _close_pos(pos, target, ts_list[i], "target", i - start + 1)
    else:
        for i in range(start, len(df)):
            if lows[i]  <= stop:
                return _close_pos(pos, stop,   ts_list[i], "stop",   i - start + 1)
            if highs[i] >= target:
                return _close_pos(pos, target, ts_list[i], "target", i - start + 1)

    c = float(closes[-1])
    pos["current"]    = round(c, 8)
    pos["unreal_r"]   = round((c - entry) / risk if direction == "long" else (entry - c) / risk, 2)
    pos["unreal_pnl"] = round((units * (c - entry) if direction == "long" else units * (entry - c)) - BROK_RT, 2)
    return pos


def update_scalp(j: dict, progress: bool = True) -> dict:
    """Open new scalp paper-trades from scalp.json; walk existing ones on 1h data."""
    from .data import download
    from .universe import load_scalp_universe

    scalp_file = ROOT / "public" / "data" / "scalp.json"
    if not scalp_file.exists():
        if progress:
            print("  scalp journal: no scalp.json — run the scanner first.")
        return j

    scan    = json.loads(scalp_file.read_text(encoding="utf-8"))
    scan_ts = scan.get("generated_at", "")

    universe  = load_scalp_universe()
    sym_to_yf = {u["symbol"]: u["yf"] for u in universe}

    today        = scan_ts[:10]
    today_closed = [c for c in j["closed"] if (c.get("opened_ts") or "")[:10] == today]
    today_pnl    = sum(c.get("pnl", 0) for c in today_closed)
    trades_used  = len(today_closed) + len(j["open"])

    open_keys  = {(p["symbol"], p["direction"]) for p in j["open"]}
    opened_now = 0

    for r in scan["results"]:
        if r["grade"] not in ("A+", "A"):
            continue
        direction = r["dir"].lower()
        if (r["symbol"], direction) in open_keys:
            continue
        if trades_used + opened_now >= MAX_DAILY:
            break
        if today_pnl < -MAX_LOSS:
            break

        entry = r["entry"]
        units = int(NOTIONAL / entry) if entry > 0 else 0
        if units == 0:
            continue

        j["open"].append({
            "symbol":     r["symbol"],
            "name":       r["name"],
            "asset_type": r.get("asset_type", ""),
            "direction":  direction,
            "grade":      r["grade"],
            "score":      r["score"],
            "entry":      entry,
            "stop":       r["stop"],
            "target":     r["target"],
            "rr":         r["rr"],
            "units":      units,
            "yf_ticker":  sym_to_yf.get(r["symbol"], r["symbol"]),
            "opened_ts":  scan_ts,
            "status":     "open",
        })
        open_keys.add((r["symbol"], direction))
        opened_now += 1

    yf_tickers = sorted({p.get("yf_ticker", p["symbol"]) for p in j["open"]})
    if progress and (yf_tickers or opened_now):
        print(f"  scalp journal: {opened_now} new, walking {len(yf_tickers)} open ...", flush=True)

    frames = download(yf_tickers, period="5d", interval="1h", chunk=30) if yf_tickers else {}

    survivors, closed_now = [], 0
    for p in j["open"]:
        yf  = p.get("yf_ticker", p["symbol"])
        df  = frames.get(yf)
        res = _walk_1h(df, p)
        if res.get("status") == "closed":
            j["closed"].append(res)
            closed_now += 1
        else:
            survivors.append(res)
    j["open"] = survivors

    if progress:
        print(f"  scalp journal: +{opened_now} opened, {closed_now} closed this run")
    return j
