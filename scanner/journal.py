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
import os
import pathlib
import tempfile

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


def _atomic_write(path: pathlib.Path, payload: str) -> None:
    """Write payload to path atomically via a temp file + rename (POSIX-safe)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, delete=False, suffix=".tmp", encoding="utf-8"
    ) as f:
        f.write(payload)
        tmp = f.name
    os.replace(tmp, path)


def _save(j: dict) -> None:
    # UTC to stay consistent with scalp_journal — a naive local timestamp here
    # would be silently offset by ~10h vs the scalp journal's UTC stamps.
    j["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    _atomic_write(JOURNAL_FILE, json.dumps(j, indent=2))

    open_longs  = [p for p in j["open"]   if p.get("direction", "long") == "long"]
    open_shorts = [p for p in j["open"]   if p.get("direction", "long") == "short"]
    cl_longs    = [c for c in j["closed"] if c.get("direction", "long") == "long"]
    cl_shorts   = [c for c in j["closed"] if c.get("direction", "long") == "short"]

    _atomic_write(PUBLIC_JOURNAL, json.dumps({
        "updated_at": j["updated_at"],
        "stats": summarize(j),
        "open_longs":    open_longs,
        "open_shorts":   open_shorts,
        "closed_longs":  cl_longs[-100:],
        "closed_shorts": cl_shorts[-100:],
    }, indent=2))


def _close(pos: dict, price: float, date: str, reason: str, bars: int) -> dict:
    direction = pos.get("direction", "long")
    shares = pos.get("shares", 0)
    brokerage = pos.get("brokerage", config.BROKERAGE_EACH_WAY)
    if direction == "short":
        risk = pos["stop"] - pos["entry"]
        r_val = round((pos["entry"] - price) / risk, 2) if risk > 0 else 0.0
        pnl = round(shares * (pos["entry"] - price) - 2 * brokerage, 2)
    else:
        risk = pos["entry"] - pos["stop"]
        r_val = round((price - pos["entry"]) / risk, 2) if risk > 0 else 0.0
        pnl = round(shares * (price - pos["entry"]) - 2 * brokerage, 2)
    return {**pos, "status": "closed", "exit": round(price, 4),
            "exit_date": date, "reason": reason, "bars": bars,
            "r": r_val, "pnl": pnl}


def _walk(df, pos: dict) -> dict:
    """Advance one open position against fresh data; returns it open or closed."""
    if df is None or len(df) < 2:
        return pos
    entry, stop, target = pos["entry"], pos["stop"], pos["target"]
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
            st = st_arr[j]
            if np.isfinite(st) and closes[j] < st < current_stop:
                current_stop = st
            if highs[j] >= current_stop:
                return _close(pos, current_stop, dates[j],
                              "trail" if current_stop < stop else "stop", j - start + 1)
            if lows[j] <= target:
                return _close(pos, target, dates[j], "target", j - start + 1)
        pos["current"] = round(float(closes[-1]), 4)
        pos["trail_stop"] = round(current_stop, 4)
        pos["unreal_r"] = round((entry - closes[-1]) / risk, 2)
        pos["unreal_pnl"] = round(shares * (entry - closes[-1]), 2)
    else:
        current_stop = stop
        for j in range(start, len(df)):
            st = st_arr[j]
            if np.isfinite(st) and closes[j] > st > current_stop:
                current_stop = st
            if lows[j] <= current_stop:
                return _close(pos, current_stop, dates[j],
                              "trail" if current_stop > stop else "stop", j - start + 1)
            if highs[j] >= target:
                return _close(pos, target, dates[j], "target", j - start + 1)
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
            shares = int(config.POSITION_SIZE_USD / entry_price) if entry_price > 0 else 0
            j["open"].append({
                "market": market_key, "symbol": r["symbol"], "name": r["name"],
                "yf_ticker": r["symbol"] + market.suffix,
                "grade": r["grade"], "score": r["score"],
                "entry": entry_price, "stop": r["stop"], "target": r["target"], "rr": r["rr"],
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
            shares = int(config.POSITION_SIZE_USD / entry_price) if entry_price > 0 else 0
            j["open"].append({
                "market": market_key, "symbol": r["symbol"], "name": r["name"],
                "yf_ticker": r["symbol"] + market.suffix,
                "grade": r["grade"], "score": r["score"],
                "entry": entry_price, "stop": r["stop"], "target": r["target"], "rr": r["rr"],
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


def close_manual(j: dict, symbol: str, direction: str, market: str,
                 price: float, exit_date: str) -> bool:
    """Manually close a swing position by symbol+direction+market. Returns True if found."""
    import datetime as _dt
    date_str = exit_date or _dt.date.today().isoformat()
    for i, p in enumerate(j["open"]):
        if (p["symbol"].upper() == symbol.upper()
                and p.get("direction", "long") == direction
                and (not market or p.get("market", "") == market)):
            closed = _close(p, price, date_str, "manual", 0)
            j["closed"].append(closed)
            j["open"].pop(i)
            return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Forward-test paper-trade journal")
    ap.add_argument("--market", action="append", choices=list(config.MARKETS))
    # Manual close subcommand (used by the close_position GitHub Actions workflow)
    ap.add_argument("--close-manual", action="store_true", help="Manually close one open position")
    ap.add_argument("--symbol",       default="",    help="Symbol to close (--close-manual)")
    ap.add_argument("--direction",    default="long", choices=["long", "short"])
    ap.add_argument("--price",        type=float,    default=0.0,  help="Exit price")
    ap.add_argument("--date",         default="",    help="Exit date YYYY-MM-DD (default: today)")
    ap.add_argument("--journal-type", default="swing", choices=["swing", "scalp"])
    args = ap.parse_args()

    if args.close_manual:
        if not args.symbol or args.price <= 0:
            print("--close-manual requires --symbol and a positive --price")
            raise SystemExit(1)

        if args.journal_type == "scalp":
            from . import scalp_journal as _sj
            sj = _sj._load()
            found = _sj.close_manual(sj, args.symbol, args.direction, args.price, args.date)
            if found:
                _sj._save(sj)
                print(f"Scalp journal: closed {args.symbol} {args.direction} @ {args.price}")
            else:
                print(f"Scalp journal: no open {args.symbol} {args.direction} found — nothing changed")
        else:
            j = _load()
            mk = (args.market or [None])[0]
            found = close_manual(j, args.symbol, args.direction, mk or "", args.price, args.date)
            if found:
                _save(j)
                print(f"Swing journal: closed {args.symbol} {args.direction} @ {args.price}")
            else:
                print(f"Swing journal: no open {args.symbol} {args.direction} found — nothing changed")
        return

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
