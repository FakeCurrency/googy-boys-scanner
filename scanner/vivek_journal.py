"""VIVEK-native paper-trade journal — measures the trigger-based system.

Every scan, this snapshots ARMED A/A+ setups at their TRIGGER price (per
timeframe) and then resolves the open paper trades bar-by-bar using the SAME
rules the autonomous bot uses (`vivek_bot.manage_position`): scale out at
TP1/TP2/TP3, move the SL to break-even at TP1 and to locked structure at TP2,
never against the trade. On top of that it adds the things a journal needs that
the bot's live manager doesn't: stop-out detection, MAE/MFE, realized R and
hold time — recorded per closed trade with its grade, entry_type and timeframe.

The point is expectancy: once enough trades close we can compare reclaim vs
retest vs break, A+ vs A, and 1D vs 1W with real numbers instead of intuition.

Single source of truth: this consumes the SAME per-timeframe plans the row, the
chart and the bot use (row["plans"][tf]) — it never recomputes a level.
"""

import datetime as dt
import json
import logging
import pathlib

from . import vivek
from .broker.vivek_bot import manage_position
from .journal_common import atomic_write

log = logging.getLogger(__name__)

ROOT = pathlib.Path(__file__).resolve().parents[1]
JOURNAL_FILE = ROOT / "journal" / "vivek_journal.json"
PUBLIC_FILE = ROOT / "public" / "data" / "vivek_journal.json"

JOURNAL_VERSION = 1
TIMEFRAMES = ("1D", "1W")          # 4H is browser-only (no server-side intraday)
MAX_CLOSED = 4000                  # keep the file bounded; oldest trades roll off


def _load() -> dict:
    if JOURNAL_FILE.exists():
        try:
            j = json.loads(JOURNAL_FILE.read_text(encoding="utf-8"))
            j.setdefault("open", [])
            j.setdefault("closed", [])
            return j
        except Exception:
            pass
    return {"version": JOURNAL_VERSION, "open": [], "closed": []}


def _save(j: dict) -> None:
    j["version"] = JOURNAL_VERSION
    j["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    if len(j["closed"]) > MAX_CLOSED:
        j["closed"] = j["closed"][-MAX_CLOSED:]
    j["expectancy"] = expectancy(j["closed"])
    payload = json.dumps(j, indent=2)
    atomic_write(JOURNAL_FILE, payload)
    atomic_write(PUBLIC_FILE, payload)


def _trade_id(symbol: str, direction: str, tf: str, entry_bar: str) -> str:
    return f"{symbol}:{direction}:{tf}:{entry_bar}"


def _frame_to_bars(df, tf: str) -> list[dict]:
    """OHLC frame -> ascending [{date, high, low, close}] for resolution.
    For 1W the daily frame is resampled to the same W-FRI bars the plan used."""
    if tf == "1W":
        df = vivek._resample_weekly_ohlc(df)
        if df is None:
            return []
    out = []
    for ts, row in df.iterrows():
        try:
            out.append({"date": ts.strftime("%Y-%m-%d"),
                        "high": float(row["High"]), "low": float(row["Low"]),
                        "close": float(row["Close"])})
        except Exception:
            continue
    return out


def _snapshot(row: dict, tf: str, plan: dict, market: str) -> dict:
    direction = "short" if str(row.get("dir", "LONG")).upper() == "SHORT" else "long"
    entry_type = plan.get("entry_trigger") or (row.get("entry_types") or [None])[0]
    entry = plan["entry"]
    return {
        "id": _trade_id(row["symbol"], direction, tf, plan["trigger_bar"]),
        "symbol": row["symbol"], "name": row.get("name", row["symbol"]),
        "sector": row.get("sector", ""), "market": market,
        "direction": direction, "grade": row["grade"], "entry_type": entry_type,
        "timeframe": tf,
        "entry": entry, "stop": plan["stop"],
        "tp1": plan["tp1"], "tp2": plan["tp2"], "tp3": plan["tp3"],
        "scale": plan["scale"], "risk": plan["risk"], "rr": plan.get("rr"),
        "entry_date": plan["trigger_bar"],
        "opened_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "status": "open",
        "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
        "booked_pct": 0.0, "realized_r": 0.0, "exits": [],
        "mae": entry, "mfe": entry, "_last_bar": None,
    }


def _resolve(trade: dict, bars: list[dict]) -> dict:
    """Advance an open paper trade through any bars after its last-processed bar.

    Pessimistic intrabar ordering: the stop is checked against the bar's adverse
    extreme BEFORE booking any target on the favourable extreme, so a bar that
    spans both resolves as a stop. Scale-outs + SL moves come from the bot's
    manage_position (the same 5.0 rules); we add the stop-out + R accounting.
    """
    direction = trade["direction"]
    is_long = direction == "long"
    entry, risk = trade["entry"], trade["risk"]
    if risk <= 0:
        return trade

    pos = {"symbol": trade["symbol"], "direction": direction, "entry": entry,
           "stop": trade["stop"], "tp1": trade["tp1"], "tp2": trade["tp2"],
           "tp3": trade["tp3"], "scale": trade["scale"],
           "tp1_hit": trade["tp1_hit"], "tp2_hit": trade["tp2_hit"],
           "tp3_hit": trade["tp3_hit"]}
    booked = trade["booked_pct"]
    realized = trade["realized_r"]
    exits = list(trade["exits"])
    mae, mfe = trade["mae"], trade["mfe"]
    last = trade["_last_bar"]
    start = trade["entry_date"]

    def r_of(price):
        return (price - entry) / risk if is_long else (entry - price) / risk

    closed = False
    for b in bars:
        if b["date"] <= start:              # entry bar and earlier — skip
            continue
        if last is not None and b["date"] <= last:
            continue
        adverse = b["low"] if is_long else b["high"]
        favorable = b["high"] if is_long else b["low"]
        mae = min(mae, adverse) if is_long else max(mae, adverse)
        mfe = max(mfe, favorable) if is_long else min(mfe, favorable)
        last = b["date"]

        stop_hit = (adverse <= pos["stop"]) if is_long else (adverse >= pos["stop"])
        if stop_hit:
            remaining = round(1.0 - booked, 6)
            if remaining > 1e-9:
                px = pos["stop"]
                exits.append({"reason": "stop", "price": px, "pct": remaining, "date": b["date"]})
                realized += remaining * r_of(px)
                booked += remaining
            closed = True
            trade["exit_price"] = pos["stop"]
            trade["exit_date"] = b["date"]
            break

        for a in manage_position(pos, favorable):     # books TPs reached + moves SL
            if a["action"] == "scale":
                name = a["tp"].lower()                # "TP1" -> "tp1"
                pct, px = a["book_pct"], pos[name]
                exits.append({"reason": name, "price": px, "pct": pct, "date": b["date"]})
                realized += pct * r_of(px)
                booked += pct

    trade["_last_bar"] = last
    trade["exits"] = exits
    trade["booked_pct"] = round(booked, 6)
    trade["realized_r"] = round(realized, 4)
    trade["mae"], trade["mfe"] = round(mae, 8), round(mfe, 8)
    trade["mae_r"], trade["mfe_r"] = round(r_of(mae), 3), round(r_of(mfe), 3)
    trade["tp1_hit"], trade["tp2_hit"], trade["tp3_hit"] = pos["tp1_hit"], pos["tp2_hit"], pos["tp3_hit"]
    trade["stop"] = pos["stop"]
    if closed:
        trade["status"] = "closed"
        trade["exit_reason"] = ("target" if pos["tp3_hit"]
                                else "trail" if pos["tp1_hit"] else "stop")
        try:
            d0 = dt.date.fromisoformat(trade["entry_date"])
            d1 = dt.date.fromisoformat(trade["exit_date"])
            trade["hold_days"] = (d1 - d0).days
        except Exception:
            trade["hold_days"] = None
    return trade


def _stats(trades: list[dict]) -> dict:
    n = len(trades)
    if not n:
        return {"n": 0, "win_rate": 0.0, "expectancy_r": 0.0, "total_r": 0.0,
                "avg_win_r": 0.0, "avg_loss_r": 0.0, "avg_hold_days": 0.0,
                "avg_mae_r": 0.0, "avg_mfe_r": 0.0}
    rs = [t.get("realized_r", 0.0) for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    holds = [t["hold_days"] for t in trades if t.get("hold_days") is not None]
    maes = [t["mae_r"] for t in trades if t.get("mae_r") is not None]
    mfes = [t["mfe_r"] for t in trades if t.get("mfe_r") is not None]
    return {
        "n": n,
        "win_rate": round(100 * len(wins) / n, 1),
        "expectancy_r": round(sum(rs) / n, 3),       # the headline number
        "total_r": round(sum(rs), 2),
        "avg_win_r": round(sum(wins) / len(wins), 3) if wins else 0.0,
        "avg_loss_r": round(sum(losses) / len(losses), 3) if losses else 0.0,
        "avg_hold_days": round(sum(holds) / len(holds), 1) if holds else 0.0,
        "avg_mae_r": round(sum(maes) / len(maes), 3) if maes else 0.0,
        "avg_mfe_r": round(sum(mfes) / len(mfes), 3) if mfes else 0.0,
    }


def expectancy(closed: list[dict]) -> dict:
    """Expectancy overall and split by grade, entry_type and timeframe."""
    def split(key, values):
        return {v: _stats([t for t in closed if t.get(key) == v]) for v in values}
    return {
        "overall": _stats(closed),
        "by_grade": split("grade", ["A+", "A"]),
        "by_entry_type": split("entry_type", vivek.ENTRY_TYPES),
        "by_timeframe": split("timeframe", ["1D", "1W", "4H"]),
    }


def update(market: str, results: list[dict], frames: dict, universe: list[dict]) -> dict:
    """Snapshot newly-armed A/A+ setups, resolve this market's open trades, save.

    `frames` is the deep daily history keyed by yfinance ticker (reused from the
    scan — no extra download); `universe` maps display symbol -> yf ticker.
    """
    j = _load()
    known = {t["id"] for t in j["open"]} | {t["id"] for t in j["closed"]}
    open_keys = {(t["symbol"], t["direction"], t["timeframe"])
                 for t in j["open"] if t.get("market") == market}
    yf_map = {u["symbol"]: u["yf"] for u in universe}

    # 1) snapshot new ARMED A/A+ setups at their trigger price (per timeframe).
    added = 0
    for row in results:
        if row.get("grade") not in ("A+", "A"):
            continue
        direction = "short" if str(row.get("dir", "LONG")).upper() == "SHORT" else "long"
        plans = row.get("plans") or {}
        for tf in TIMEFRAMES:
            plan = plans.get(tf)
            if not plan or not plan.get("armed") or not plan.get("trigger_bar"):
                continue
            tid = _trade_id(row["symbol"], direction, tf, plan["trigger_bar"])
            if tid in known:
                continue
            if (row["symbol"], direction, tf) in open_keys:   # no pyramiding
                continue
            j["open"].append(_snapshot(row, tf, plan, market))
            known.add(tid)
            open_keys.add((row["symbol"], direction, tf))
            added += 1

    # 2) resolve this market's open trades against the freshly-downloaded bars.
    still_open, closed_now = [], 0
    for t in j["open"]:
        if t.get("market") != market:
            still_open.append(t)
            continue
        df = frames.get(yf_map.get(t["symbol"]))
        if df is None:
            still_open.append(t)
            continue
        _resolve(t, _frame_to_bars(df, t["timeframe"]))
        if t["status"] == "closed":
            j["closed"].append(t)
            closed_now += 1
        else:
            still_open.append(t)
    j["open"] = still_open

    _save(j)
    log.info("vivek journal [%s]: +%d new, %d closed this run (%d open, %d closed total)",
             market, added, closed_now, len(j["open"]), len(j["closed"]))
    return j
