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


def summarize(j: dict) -> dict:
    closed = j["closed"]
    rs = np.array([c["r"] for c in closed], dtype=float) if closed else np.array([])
    wins = rs[rs > 0]
    open_unreal = sum(p.get("unreal_r", 0) or 0 for p in j["open"])
    return {
        "open": len(j["open"]),
        "closed": len(closed),
        "win_rate": round(len(wins) / len(rs) * 100, 1) if len(rs) else 0.0,
        "avg_r": round(float(rs.mean()), 3) if len(rs) else 0.0,
        "total_r": round(float(rs.sum()), 2) if len(rs) else 0.0,
        "open_unrealised_r": round(open_unreal, 2),
    }


def _save(j: dict) -> None:
    j["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    JOURNAL_FILE.write_text(json.dumps(j, indent=2), encoding="utf-8")

    PUBLIC_JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_JOURNAL.write_text(json.dumps({
        "updated_at": j["updated_at"],
        "stats": summarize(j),
        "open": j["open"],
        "closed": j["closed"][-100:],
    }, indent=2), encoding="utf-8")


def _close(pos: dict, price: float, date: str, reason: str, bars: int) -> dict:
    risk = pos["entry"] - pos["stop"]
    return {**pos, "status": "closed", "exit": round(price, 4),
            "exit_date": date, "reason": reason, "bars": bars,
            "r": round((price - pos["entry"]) / risk, 2) if risk > 0 else 0.0}


def _walk(df, pos: dict) -> dict:
    """Advance one open position against fresh data; returns it open or closed."""
    if df is None or len(df) < 2:
        return pos
    entry, stop, target = pos["entry"], pos["stop"], pos["target"]
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
        pos["unreal_r"] = round((closes[-1] - entry) / risk, 2)
        return pos

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
    return pos


def update_market(market_key: str, j: dict, progress: bool = True) -> dict:
    market = config.MARKETS[market_key]
    data_file = ROOT / "public" / "data" / f"{market_key}.json"
    if not data_file.exists():
        print(f"  {market.label}: no scan file yet — run the scanner first.")
        return j
    scan = json.loads(data_file.read_text(encoding="utf-8"))
    scan_date = scan["generated_at"][:10]

    # 1) open a paper position for each new A+/A setup
    open_keys = {(p["market"], p["symbol"]) for p in j["open"]}
    opened_now = 0
    for r in scan["results"]:
        if r["grade"] in config.TRADEABLE_GRADES and (market_key, r["symbol"]) not in open_keys:
            j["open"].append({
                "market": market_key, "symbol": r["symbol"], "name": r["name"],
                "grade": r["grade"], "score": r["score"],
                "entry": r["price"], "stop": r["stop"], "target": r["target"], "rr": r["rr"],
                "opened": scan_date, "status": "open",
            })
            open_keys.add((market_key, r["symbol"]))
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
    print(f"\nJournal: {s['open']} open ({s['open_unrealised_r']:+.1f}R unrealised) | "
          f"{s['closed']} closed | win {s['win_rate']}% | "
          f"realised {s['total_r']:+.1f}R")
    print(f"Saved -> {JOURNAL_FILE}\n")


if __name__ == "__main__":
    main()
