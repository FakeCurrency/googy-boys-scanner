"""VIVEK-native paper-trade journal — realistic intraday forward test.

This measures the trigger-based system the way it would actually be traded:

  * Trades are only OPENED during the live (delayed) market session — ASX
    10:00–16:00 AEST shifted +15 min for the ~15-min feed delay, etc.
  * Entry is the DELAYED INTRADAY PRICE at the moment the setup is taken during
    the session — not the historical trigger-bar close. The structural stop and
    TP1/TP2/TP3 come from the same per-timeframe plan the row/chart/bot use.
  * Every market-hours scan then marks each open trade to the observed intraday
    price: it books a scale-out when price reaches a TP, moves the SL by the 5.0
    rules (BE at TP1, locked structure at TP2, never adverse), and closes at the
    observed price when the stop is hit. MAE/MFE and realized R are recorded.

So entries and exits both use the delayed intraday prices a manual trader would
actually see and act on — there is no look-ahead into a daily bar's full range.

Single source of truth: it consumes the SAME per-timeframe plans the row, chart
and bot use (row["plans"][tf]) — it never recomputes a level.
"""

import datetime as dt
import json
import logging
import pathlib
from zoneinfo import ZoneInfo

from . import config
from .broker.vivek_bot import manage_position
from .journal_common import atomic_write

log = logging.getLogger(__name__)

ROOT = pathlib.Path(__file__).resolve().parents[1]
JOURNAL_FILE = ROOT / "journal" / "vivek_journal.json"
PUBLIC_FILE = ROOT / "public" / "data" / "vivek_journal.json"

JOURNAL_VERSION = 2                 # v2 = intraday entry/exit pricing + market-hours gate
TIMEFRAMES = ("1D", "1W")          # 4H is browser-only (no server-side intraday)
MAX_CLOSED = 4000


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


def _trade_id(symbol: str, direction: str, tf: str, entry_day: str) -> str:
    return f"{symbol}:{direction}:{tf}:{entry_day}"


def market_open(market_key: str, now: dt.datetime) -> bool:
    """Is `market_key` inside its delay-adjusted trading session at `now`?

    `now` must be timezone-aware in the market's own timezone. Crypto (session
    None) is always open; stock markets are closed on weekends.
    """
    if not config.VIVEK_JOURNAL_MARKET_HOURS:
        return True
    sess = config.VIVEK_JOURNAL_SESSION.get(market_key)
    if sess is None:
        return True                                  # 24/7 (crypto)
    if now.weekday() >= 5:
        return False                                 # weekend
    oh, om, ch, cm = sess
    delay = config.VIVEK_JOURNAL_FEED_DELAY_MIN
    open_min = oh * 60 + om + delay
    close_min = ch * 60 + cm + delay
    cur = now.hour * 60 + now.minute
    return open_min <= cur <= close_min


def _r_of(price, entry, risk, is_long):
    return (price - entry) / risk if is_long else (entry - price) / risk


def _snapshot(row: dict, tf: str, plan: dict, market: str,
              entry_price: float, day: str) -> dict | None:
    """Open a paper trade at the current delayed intraday price.

    Returns None to "not chase" — when the move has already played out (price at
    or beyond TP1) or the entry would be on the wrong side of the stop.
    """
    direction = "short" if str(row.get("dir", "LONG")).upper() == "SHORT" else "long"
    is_long = direction == "long"
    stop = plan["stop"]
    tp1, tp2, tp3 = plan["tp1"], plan["tp2"], plan["tp3"]
    if is_long:
        if entry_price <= stop or entry_price >= tp1:
            return None
    else:
        if entry_price >= stop or entry_price <= tp1:
            return None
    risk = abs(entry_price - stop)
    if risk <= 0:
        return None
    entry_type = plan.get("entry_trigger") or (row.get("entry_types") or [None])[0]
    return {
        "id": _trade_id(row["symbol"], direction, tf, day),
        "symbol": row["symbol"], "name": row.get("name", row["symbol"]),
        "sector": row.get("sector", ""), "market": market,
        "direction": direction, "grade": row["grade"], "entry_type": entry_type,
        "timeframe": tf,
        "entry": round(entry_price, 8), "stop": stop,
        "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "scale": plan["scale"], "risk": round(risk, 8),
        "rr": round(abs(tp2 - entry_price) / risk, 2),
        "trigger_bar": plan.get("trigger_bar"),       # the bar the trigger fired on (reference)
        "entry_date": day, "opened_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "status": "open",
        "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
        "booked_pct": 0.0, "realized_r": 0.0, "exits": [],
        "mae": round(entry_price, 8), "mfe": round(entry_price, 8),
        "mae_r": 0.0, "mfe_r": 0.0,
    }


def _mark(trade: dict, price: float, day: str) -> None:
    """Mark an open trade to the observed intraday `price` for this scan.

    Single-price observation (no intrabar range), so there's no ambiguity: at
    most one of {stop, TP scale-outs} resolves per scan. Books TPs at the TP
    level (a resting limit), closes the stop at the observed price (so an
    overnight gap fills at the gapped price), and moves the SL by the 5.0 rules.
    """
    is_long = trade["direction"] == "long"
    entry, risk = trade["entry"], trade["risk"]
    if risk <= 0:
        return
    # running MAE/MFE from the prices we actually observe
    trade["mfe"] = max(trade["mfe"], price) if is_long else min(trade["mfe"], price)
    trade["mae"] = min(trade["mae"], price) if is_long else max(trade["mae"], price)

    pos = {"symbol": trade["symbol"], "direction": trade["direction"], "entry": entry,
           "stop": trade["stop"], "tp1": trade["tp1"], "tp2": trade["tp2"],
           "tp3": trade["tp3"], "scale": trade["scale"],
           "tp1_hit": trade["tp1_hit"], "tp2_hit": trade["tp2_hit"], "tp3_hit": trade["tp3_hit"]}

    stop_hit = price <= pos["stop"] if is_long else price >= pos["stop"]
    if stop_hit:
        remaining = round(1.0 - trade["booked_pct"], 6)
        if remaining > 1e-9:
            trade["exits"].append({"reason": "stop", "price": round(price, 8), "pct": remaining, "date": day})
            trade["realized_r"] = round(trade["realized_r"] + remaining * _r_of(price, entry, risk, is_long), 4)
            trade["booked_pct"] = 1.0
        trade["status"] = "closed"
        trade["exit_price"] = round(price, 8)
        trade["exit_date"] = day
        trade["exit_reason"] = ("target" if pos["tp3_hit"]
                                else "trail" if pos["tp1_hit"] else "stop")
    else:
        for a in manage_position(pos, price):          # books TPs reached + moves SL
            if a["action"] == "scale":
                name = a["tp"].lower()
                pct, px = a["book_pct"], pos[name]
                trade["exits"].append({"reason": name, "price": px, "pct": pct, "date": day})
                trade["realized_r"] = round(trade["realized_r"] + pct * _r_of(px, entry, risk, is_long), 4)
                trade["booked_pct"] = round(trade["booked_pct"] + pct, 6)
        trade["tp1_hit"], trade["tp2_hit"], trade["tp3_hit"] = pos["tp1_hit"], pos["tp2_hit"], pos["tp3_hit"]
        trade["stop"] = pos["stop"]

    trade["mae_r"] = round(_r_of(trade["mae"], entry, risk, is_long), 3)
    trade["mfe_r"] = round(_r_of(trade["mfe"], entry, risk, is_long), 3)
    if trade["status"] == "closed":
        try:
            d0 = dt.date.fromisoformat(trade["entry_date"])
            d1 = dt.date.fromisoformat(trade["exit_date"])
            trade["hold_days"] = (d1 - d0).days
        except Exception:
            trade["hold_days"] = None


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
        "expectancy_r": round(sum(rs) / n, 3),
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
        "by_entry_type": split("entry_type", config.VIVEK_TRIGGER_PRIORITY),
        "by_timeframe": split("timeframe", ["1D", "1W", "4H"]),
    }


def _current_price(frames: dict, yf_ticker: str | None):
    df = frames.get(yf_ticker) if yf_ticker else None
    if df is None or len(df) == 0:
        return None
    try:
        return float(df["Close"].iloc[-1])
    except Exception:
        return None


def update(market: str, results: list[dict], frames: dict, universe: list[dict],
           now: dt.datetime | None = None) -> dict:
    """Open newly-armed A/A+ setups at the current intraday price (market hours
    only), mark this market's open trades to the observed price, and save.

    `frames` is the deep daily history keyed by yfinance ticker — its last bar's
    close is the latest (delayed) price during the session. `now` is injectable
    for testing; it defaults to the market's local wall clock.
    """
    mkt = config.MARKETS[market]
    if now is None:
        now = dt.datetime.now(ZoneInfo(mkt.timezone))
    day = now.strftime("%Y-%m-%d")
    is_open = market_open(market, now)

    j = _load()
    known = {t["id"] for t in j["open"]} | {t["id"] for t in j["closed"]}
    open_keys = {(t["symbol"], t["direction"], t["timeframe"])
                 for t in j["open"] if t.get("market") == market}
    yf_map = {u["symbol"]: u["yf"] for u in universe}

    # 1) open new ARMED A/A+ setups at the current intraday price (session only).
    added = 0
    if is_open:
        for row in results:
            if row.get("grade") not in ("A+", "A"):
                continue
            price = _current_price(frames, yf_map.get(row["symbol"]))
            if price is None:
                continue
            direction = "short" if str(row.get("dir", "LONG")).upper() == "SHORT" else "long"
            plans = row.get("plans") or {}
            for tf in TIMEFRAMES:
                plan = plans.get(tf)
                if not plan or not plan.get("armed"):
                    continue
                tid = _trade_id(row["symbol"], direction, tf, day)
                if tid in known or (row["symbol"], direction, tf) in open_keys:
                    continue
                snap = _snapshot(row, tf, plan, market, price, day)
                if snap is None:                       # don't chase / bad risk
                    continue
                j["open"].append(snap)
                known.add(tid)
                open_keys.add((row["symbol"], direction, tf))
                added += 1

    # 2) mark this market's open trades to the observed price (session only).
    still_open, closed_now = [], 0
    for t in j["open"]:
        if t.get("market") != market:
            still_open.append(t)
            continue
        price = _current_price(frames, yf_map.get(t["symbol"]))
        if is_open and price is not None:
            _mark(t, price, day)
        if t["status"] == "closed":
            j["closed"].append(t)
            closed_now += 1
        else:
            still_open.append(t)
    j["open"] = still_open

    _save(j)
    log.info("vivek journal [%s]: %s · +%d new, %d closed this run (%d open, %d closed total)",
             market, "OPEN" if is_open else "closed-session",
             added, closed_now, len(j["open"]), len(j["closed"]))
    return j
