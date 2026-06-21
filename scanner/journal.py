"""Paper-trade journal — a bias-free forward test.

Each run it (1) opens a paper position for every new A+/A setup in the latest
scan, and (2) walks every open position forward against fresh prices, closing it
when the stop / target / SuperTrend-trail is hit. Outcomes are recorded in R
multiples, building a real track record over time. No orders are ever placed.

    python -m scanner.journal                 # update from the latest scans
    python -m scanner.journal --market asx     # one market

Stored in journal/journal.json (full history) and mirrored to
public/data/journal.json so a UI can show the track record.
"""

import argparse
import datetime as dt
import json
import pathlib

import numpy as np

from . import config
from .data import download
from .indicators import supertrend

ROOT = pathlib.Path(__file__).resolve().parents[1]
JOURNAL_FILE = ROOT / "journal" / "journal.json"
PUBLIC_JOURNAL = ROOT / "public" / "data" / "journal.json"


def _load() -> dict:
    if JOURNAL_FILE.exists():
        try:
            return json.loads(JOURNAL_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"open": [], "closed": []}


def _kelly(rs: np.ndarray) -> float | None:
    """Half-Kelly position size as % of account. Returns None if < 20 closed trades."""
    if len(rs) < 20:
        return None
    wins = rs[rs > 0]
    losses = rs[rs < 0]
    if not len(wins) or not len(losses):
        return None
    p = len(wins) / len(rs)
    avg_win = float(wins.mean())
    avg_loss = float(abs(losses.mean()))
    b = avg_win / avg_loss
    full_kelly = (p * b - (1 - p)) / b
    return round(max(0.0, full_kelly * 0.5) * 100, 1)  # half-Kelly, as %


def _dir_stats(closed_list: list, open_list: list) -> dict:
    rs = np.array([c["r"] for c in closed_list], dtype=float) if closed_list else np.array([])
    wins = rs[rs > 0]
    return {
        "open": len(open_list),
        "closed": len(closed_list),
        "win_rate": round(len(wins) / len(rs) * 100, 1) if len(rs) else 0.0,
        "total_r": round(float(rs.sum()), 2) if len(rs) else 0.0,
        "total_pnl": round(sum(c.get("pnl", 0) or 0 for c in closed_list), 2),
        "open_unrealised_r": round(sum(p.get("unreal_r", 0) or 0 for p in open_list), 2),
        "open_unrealised_pnl": round(sum(p.get("unreal_pnl", 0) or 0 for p in open_list), 2),
        "kelly_pct": _kelly(rs),
    }


def summarize(j: dict) -> dict:
    long_open   = [p for p in j["open"]   if p.get("direction", "long") == "long"]
    short_open  = [p for p in j["open"]   if p.get("direction", "long") == "short"]
    long_closed = [c for c in j["closed"] if c.get("direction", "long") == "long"]
    short_closed= [c for c in j["closed"] if c.get("direction", "long") == "short"]
    return {
        "position_size": config.POSITION_SIZE_USD,
        "brokerage": config.BROKERAGE_EACH_WAY,
        "max_positions_long": config.MAX_POSITIONS_LONG,
        "max_positions_short": config.MAX_POSITIONS_SHORT,
        "longs": _dir_stats(long_closed, long_open),
        "shorts": _dir_stats(short_closed, short_open),
    }


def _save(j: dict) -> None:
    j["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    JOURNAL_FILE.write_text(json.dumps(j, indent=2), encoding="utf-8")

    open_longs  = [p for p in j["open"]   if p.get("direction", "long") == "long"]
    open_shorts = [p for p in j["open"]   if p.get("direction", "long") == "short"]
    cl_longs    = [c for c in j["closed"] if c.get("direction", "long") == "long"]
    cl_shorts   = [c for c in j["closed"] if c.get("direction", "long") == "short"]

    PUBLIC_JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_JOURNAL.write_text(json.dumps({
        "updated_at": j["updated_at"],
        "stats": summarize(j),
        "open_longs":    open_longs,
        "open_shorts":   open_shorts,
        "closed_longs":  cl_longs[-100:],
        "closed_shorts": cl_shorts[-100:],
    }, indent=2), encoding="utf-8")


SLIP = config.SWING_FILL_SLIPPAGE_PCT


def _close(pos: dict, price: float, date: str, reason: str, bars: int) -> dict:
    direction = pos.get("direction", "long")
    shares = pos.get("shares", 0)
    brokerage = pos.get("brokerage", config.BROKERAGE_EACH_WAY)
    # Risk & P&L use the pessimistic fill price (entry slippage), falling back to
    # the signal entry for legacy positions opened before slippage modelling.
    entry = pos.get("fill_price", pos["entry"])
    # Market exits (stop / trail / invalid) slip worse; limit exits (target) don't.
    is_market_exit = reason not in ("target", "target-gap")
    if is_market_exit:
        exit_px = price * (1 - SLIP) if direction == "long" else price * (1 + SLIP)
    else:
        exit_px = price
    if direction == "short":
        risk = pos["stop"] - entry
        r_val = round((entry - exit_px) / risk, 2) if risk > 0 else 0.0
        pnl = round(shares * (entry - exit_px) - 2 * brokerage, 2)
    else:
        risk = entry - pos["stop"]
        r_val = round((exit_px - entry) / risk, 2) if risk > 0 else 0.0
        pnl = round(shares * (exit_px - entry) - 2 * brokerage, 2)
    return {**pos, "status": "closed", "exit": round(exit_px, 4),
            "exit_date": date, "reason": reason, "bars": bars,
            "r": r_val, "pnl": pnl}


def _walk(df, pos: dict) -> dict:
    """Advance one open position against fresh data; returns it open or closed.

    Honest fill model (mirrors the scalp journal):
    - P&L uses ``fill_price`` (entry + slippage), set once when the position is
      opened; falls back to the signal ``entry`` for legacy positions.
    - Gap-through: if a bar OPENS beyond the stop (or target) we fill at the bar
      open, not the level — so a gap-down through a stop books the real, larger
      loss instead of the optimistic stop price.
    - The SuperTrend trail is ratcheted using a bar's close but only applied to
      LATER bars (ratchet happens at the end of the loop body), removing the
      same-bar trail-then-test intrabar lookahead.
    """
    if df is None or len(df) < 2:
        return pos
    entry = pos.get("fill_price", pos["entry"])
    stop, target = pos["stop"], pos["target"]
    direction = pos.get("direction", "long")
    shares = pos.get("shares", 0)

    if direction == "short":
        risk = stop - entry  # stop is above entry for shorts
    else:
        risk = entry - stop
    if risk <= 0:
        return _close(pos, entry, pos["opened"], "invalid", 0)

    dates = [d.date().isoformat() for d in df.index]
    closes = df["Close"].to_numpy()
    highs = df["High"].to_numpy()
    lows = df["Low"].to_numpy()
    opens = df["Open"].to_numpy()
    st_arr = supertrend(df, config.ATR_PERIOD, config.SUPERTREND_MULT).to_numpy()

    start = next((k for k, ds in enumerate(dates) if ds > pos["opened"]), None)
    if start is None:  # opened on the latest bar; nothing to evaluate yet
        pos["current"] = round(float(closes[-1]), 4)
        if direction == "short":
            pos["unreal_r"] = round((entry - closes[-1]) / risk, 2)
            pos["unreal_pnl"] = round(shares * (entry - closes[-1]), 2)
        else:
            pos["unreal_r"] = round((closes[-1] - entry) / risk, 2)
            pos["unreal_pnl"] = round(shares * (closes[-1] - entry), 2)
        return pos

    if direction == "short":
        current_stop = stop  # trail ratchets DOWN as price falls
        for j in range(start, len(df)):
            trailing = current_stop < stop
            if opens[j] >= current_stop:        # gapped up through stop (unfavourable)
                return _close(pos, float(opens[j]), dates[j],
                              "trail-gap" if trailing else "stop-gap", j - start + 1)
            if opens[j] <= target:              # gapped down through target (windfall)
                return _close(pos, float(opens[j]), dates[j], "target-gap", j - start + 1)
            if highs[j] >= current_stop:
                return _close(pos, current_stop, dates[j],
                              "trail" if trailing else "stop", j - start + 1)
            if lows[j] <= target:
                return _close(pos, target, dates[j], "target", j - start + 1)
            st = st_arr[j]                       # ratchet AFTER tests → applies next bar only
            if np.isfinite(st) and closes[j] < st < current_stop:
                current_stop = st
        pos["current"] = round(float(closes[-1]), 4)
        pos["trail_stop"] = round(current_stop, 4)
        pos["unreal_r"] = round((entry - closes[-1]) / risk, 2)
        pos["unreal_pnl"] = round(shares * (entry - closes[-1]), 2)
    else:
        current_stop = stop
        for j in range(start, len(df)):
            trailing = current_stop > stop
            if opens[j] <= current_stop:        # gapped down through stop (unfavourable)
                return _close(pos, float(opens[j]), dates[j],
                              "trail-gap" if trailing else "stop-gap", j - start + 1)
            if opens[j] >= target:              # gapped up through target (windfall)
                return _close(pos, float(opens[j]), dates[j], "target-gap", j - start + 1)
            if lows[j] <= current_stop:
                return _close(pos, current_stop, dates[j],
                              "trail" if trailing else "stop", j - start + 1)
            if highs[j] >= target:
                return _close(pos, target, dates[j], "target", j - start + 1)
            st = st_arr[j]                       # ratchet AFTER tests → applies next bar only
            if np.isfinite(st) and closes[j] > st > current_stop:
                current_stop = st
        pos["current"] = round(float(closes[-1]), 4)
        pos["trail_stop"] = round(current_stop, 4)
        pos["unreal_r"] = round((closes[-1] - entry) / risk, 2)
        pos["unreal_pnl"] = round(shares * (closes[-1] - entry), 2)
    return pos


def update_market(market_key: str, j: dict, progress: bool = True) -> dict:
    market = config.MARKETS[market_key]
    data_file = ROOT / "public" / "data" / f"{market_key}.json"
    if not data_file.exists():
        print(f"  {market.label}: no scan file yet — run the scanner first.")
        return j
    scan = json.loads(data_file.read_text(encoding="utf-8"))
    scan_date = scan["generated_at"][:10]

    # Also ingest short setups from <market>_short.json if it exists
    short_file = ROOT / "public" / "data" / f"{market_key}_short.json"
    short_results = []
    if short_file.exists():
        try:
            short_scan = json.loads(short_file.read_text(encoding="utf-8"))
            short_results = short_scan.get("results", [])
        except Exception:
            pass

    # 1) open a paper position for each new A+/A setup
    open_keys = {(p["market"], p["symbol"], p.get("direction", "long")) for p in j["open"]}
    open_long_count  = sum(1 for p in j["open"] if p.get("direction", "long")  == "long")
    open_short_count = sum(1 for p in j["open"] if p.get("direction", "long") == "short")
    opened_now = 0

    for r in scan["results"]:
        if open_long_count >= config.MAX_POSITIONS_LONG:
            break
        if r["grade"] in config.TRADEABLE_GRADES and (market_key, r["symbol"], "long") not in open_keys:
            entry_price = r["entry"]
            fill_price = round(entry_price * (1 + SLIP), 6)   # long pays slightly worse
            shares = int(config.POSITION_SIZE_USD / fill_price) if fill_price > 0 else 0
            j["open"].append({
                "market": market_key, "symbol": r["symbol"], "name": r["name"],
                "grade": r["grade"], "score": r["score"],
                "entry": entry_price, "fill_price": fill_price,
                "stop": r["stop"], "target": r["target"], "rr": r["rr"],
                "opened": scan_date, "status": "open",
                "direction": "long",
                "shares": shares,
                "brokerage": config.BROKERAGE_EACH_WAY,
                "size_usd": config.POSITION_SIZE_USD,
            })
            open_keys.add((market_key, r["symbol"], "long"))
            open_long_count += 1
            opened_now += 1

    # open short positions from the short scan file
    for r in short_results:
        if open_short_count >= config.MAX_POSITIONS_SHORT:
            break
        if r["grade"] in config.TRADEABLE_GRADES and (market_key, r["symbol"], "short") not in open_keys:
            entry_price = r["entry"]
            fill_price = round(entry_price * (1 - SLIP), 6)   # short fills slightly worse (lower)
            shares = int(config.POSITION_SIZE_USD / fill_price) if fill_price > 0 else 0
            j["open"].append({
                "market": market_key, "symbol": r["symbol"], "name": r["name"],
                "grade": r["grade"], "score": r["score"],
                "entry": entry_price, "fill_price": fill_price,
                "stop": r["stop"], "target": r["target"], "rr": r["rr"],
                "opened": scan_date, "status": "open",
                "direction": "short",
                "shares": shares,
                "brokerage": config.BROKERAGE_EACH_WAY,
                "size_usd": config.POSITION_SIZE_USD,
            })
            open_keys.add((market_key, r["symbol"], "short"))
            open_short_count += 1
            opened_now += 1

    # 2) walk this market's open positions against fresh prices
    pos_this = [p for p in j["open"] if p["market"] == market_key]
    tickers = sorted({p["symbol"] + market.suffix for p in pos_this})
    if progress and tickers:
        print(f"  {market.label}: {opened_now} new, checking {len(tickers)} open ...", flush=True)
    frames = download(tickers, period="1y") if tickers else {}

    survivors, closed_now = [], 0
    for p in j["open"]:
        if p["market"] != market_key:
            survivors.append(p)
            continue
        res = _walk(frames.get(p["symbol"] + market.suffix), p)
        if res.get("status") == "closed":
            j["closed"].append(res)
            closed_now += 1
        else:
            survivors.append(res)
    j["open"] = survivors
    if progress:
        print(f"  {market.label}: +{opened_now} opened, {closed_now} closed this run")
    return j


def main() -> None:
    ap = argparse.ArgumentParser(description="Forward-test paper-trade journal")
    ap.add_argument("--market", action="append", choices=list(config.MARKETS))
    args = ap.parse_args()

    j = _load()
    for mk in (args.market or list(config.MARKETS)):
        j = update_market(mk, j)
    _save(j)

    s = summarize(j)
    sl, ss = s["longs"], s["shorts"]
    print(f"\nJournal 1 — LONGS:  {sl['open']} open ({sl['open_unrealised_r']:+.1f}R unrealised) | "
          f"{sl['closed']} closed | win {sl['win_rate']}% | realised {sl['total_r']:+.1f}R")
    print(f"Journal 2 — SHORTS: {ss['open']} open ({ss['open_unrealised_r']:+.1f}R unrealised) | "
          f"{ss['closed']} closed | win {ss['win_rate']}% | realised {ss['total_r']:+.1f}R")
    print(f"Saved -> {JOURNAL_FILE}\n")


if __name__ == "__main__":
    main()
