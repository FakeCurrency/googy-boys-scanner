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
import os
import pathlib
import tempfile
from zoneinfo import ZoneInfo

import numpy as np

from . import config

ROOT                 = pathlib.Path(__file__).resolve().parents[1]
SCALP_JOURNAL_FILE   = ROOT / "journal" / "scalp_journal.json"
PUBLIC_SCALP_JOURNAL = ROOT / "public" / "data" / "scalp_journal.json"

NOTIONAL   = config.SCALP_POSITION_SIZE * config.SCALP_LEVERAGE  # $5,000
BROK_RT    = config.SCALP_BROKERAGE_EACH_WAY * 2                  # $40
MAX_DAILY  = config.SCALP_MAX_TRADES_PER_DAY                       # 5
MAX_LOSS   = config.SCALP_MAX_DAILY_LOSS                           # $500
SLIP       = config.SCALP_FILL_SLIPPAGE_PCT                        # 0.03% one-way
DAY_ANCHOR = config.SCALP_DAY_ANCHOR_UTC                           # kept for compat
MAX_GROUP  = config.SCALP_MAX_PER_GROUP                            # correlated positions cap
_AEST      = ZoneInfo(config.SCALP_DAY_TZ)                        # Australia/Sydney


def _session_day(ts: str | None = None) -> str:
    """Trading-day key expressed as the calendar date in AEST (Australia/Sydney).

    Pass an ISO timestamp (UTC) or None for 'now'. The day rolls over at midnight
    Sydney time — naturally avoids bisecting the ASX or crypto sessions.
    """
    if ts:
        try:
            t = dt.datetime.fromisoformat(ts.replace("Z", "")[:19]).replace(
                tzinfo=dt.timezone.utc
            )
        except ValueError:
            t = dt.datetime.now(dt.timezone.utc)
    else:
        t = dt.datetime.now(dt.timezone.utc)
    return t.astimezone(_AEST).strftime("%Y-%m-%d")


def _corr_group(symbol: str, asset_type: str = "", sector: str = "") -> str:
    """Correlation bucket for a symbol — explicit override, else <type>:<sector>.

    When both type and sector are unknown every symbol would share "?:?" and hit
    the correlation cap against each other. Fall back to a per-symbol bucket so
    unknown tickers are treated as uncorrelated (no cap applied between them).
    """
    g = config.SCALP_CORRELATION_GROUPS.get(symbol)
    if g:
        return g
    if asset_type or sector:
        return f"{asset_type or '?'}:{sector or '?'}".lower()
    return f"solo:{symbol.lower()}"


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


def _trade_day(item: dict) -> str:
    """Session-day a position belongs to — stored at open, else derived from opened_ts."""
    return item.get("session_day") or _session_day(item.get("opened_ts"))


def summarize(j: dict) -> dict:
    today        = _session_day()
    today_closed = [c for c in j["closed"]
                    if _trade_day(c) == today and not c.get("skip_daily_count")]
    today_open   = [p for p in j["open"]   if _trade_day(p) == today]
    today_pnl    = round(sum(c.get("pnl", 0) for c in today_closed), 2)
    trades_used  = len(today_closed) + len(today_open)
    long_open    = [p for p in j["open"]   if p["direction"] == "long"]
    short_open   = [p for p in j["open"]   if p["direction"] == "short"]
    long_closed  = [c for c in j["closed"] if c["direction"] == "long"]
    short_closed = [c for c in j["closed"] if c["direction"] == "short"]

    # Live correlation-group exposure (open positions only)
    group_exposure: dict[str, int] = {}
    for p in j["open"]:
        g = p.get("corr_group") or _corr_group(p["symbol"], p.get("asset_type", ""), p.get("sector", ""))
        group_exposure[g] = group_exposure.get(g, 0) + 1

    return {
        "notional":          NOTIONAL,
        "brokerage_rt":      BROK_RT,
        "max_daily_trades":  MAX_DAILY,
        "max_daily_loss":    MAX_LOSS,
        "max_per_group":     MAX_GROUP,
        "session_day":       today,
        "today_trades":      trades_used,
        "today_pnl":         today_pnl,
        "trades_left_today": max(0, MAX_DAILY - trades_used),
        "group_exposure":    dict(sorted(group_exposure.items(), key=lambda kv: -kv[1])),
        "longs":  _dir_stats(long_closed,  long_open),
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
    j["updated_at"] = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    _atomic_write(SCALP_JOURNAL_FILE, json.dumps(j, indent=2))

    long_open    = [p for p in j["open"]   if p["direction"] == "long"]
    short_open   = [p for p in j["open"]   if p["direction"] == "short"]
    long_closed  = [c for c in j["closed"] if c["direction"] == "long"]
    short_closed = [c for c in j["closed"] if c["direction"] == "short"]

    all_closed = sorted(j["closed"], key=lambda c: c.get("opened_ts", ""))

    _atomic_write(PUBLIC_SCALP_JOURNAL, json.dumps({
        "updated_at":    j["updated_at"],
        "broker_mode":   j.get("broker_mode", ""),
        "stats":         summarize(j),
        "open_longs":    long_open,
        "open_shorts":   short_open,
        "closed_longs":  long_closed[-200:],
        "closed_shorts": short_closed[-200:],
        "all_closed":    all_closed[-400:],
    }, indent=2))


def _close_pos(pos: dict, price: float, ts: str, reason: str, bars: int) -> dict:
    direction = pos["direction"]
    units     = pos["units"]
    # use pessimistic fill_price if set, else original entry
    entry     = pos.get("fill_price", pos["entry"])
    # apply exit slippage — makes the exit worse (lower for long, higher for short)
    exit_px   = price * (1 - SLIP) if direction == "long" else price * (1 + SLIP)
    if direction == "short":
        risk  = pos["stop"] - entry
        r_val = round((entry - exit_px) / risk, 2) if risk > 0 else 0.0
        gross = units * (entry - exit_px)
    else:
        risk  = entry - pos["stop"]
        r_val = round((exit_px - entry) / risk, 2) if risk > 0 else 0.0
        gross = units * (exit_px - entry)
    pnl = round(gross - BROK_RT, 2)
    return {**pos, "status": "closed", "exit": round(float(exit_px), 8),
            "exit_ts": ts, "reason": reason, "bars": bars, "r": r_val, "pnl": pnl}


def _walk_1h(df, pos: dict) -> dict:
    """Walk a scalp position forward on 1h bars using a pessimistic fill model.

    Pessimistic rules:
    - Entry fills at the OPEN of the first 1h bar after the scan timestamp, plus slippage.
      This is more realistic than filling at the last bar's close (scan price).
    - Gap-through on stop: if a bar opens beyond the stop, we fill at the bar open
      (not the stop level) — models the real cost of a gap.
    - Gap-through on target: same — if price gaps through target we take the bar open
      (which is actually better than expected, a windfall).
    - Exit slippage applied in _close_pos.
    """
    if df is None or len(df) < 2:
        return pos

    direction = pos["direction"]
    stop      = pos["stop"]
    target    = pos["target"]
    units     = pos["units"]

    if getattr(df.index, "tz", None) is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)

    ts_list = [t.isoformat() for t in df.index]
    closes  = df["Close"].to_numpy(dtype=float)
    highs   = df["High"].to_numpy(dtype=float)
    lows    = df["Low"].to_numpy(dtype=float)
    opens   = df["Open"].to_numpy(dtype=float)

    opened = pos["opened_ts"][:19]
    start  = next((k for k, ts in enumerate(ts_list) if ts > opened), None)

    # ── Pessimistic entry fill (first time only) ─────────────────────────────
    if not pos.get("filled"):
        if start is None:
            # No new bars since scan — not yet filled; show zero unrealised
            pos["unreal_r"]   = 0.0
            pos["unreal_pnl"] = 0.0
            return pos

        raw_open = float(opens[start])
        # Slippage makes entry worse: long fills higher, short fills lower
        fill_px = raw_open * (1 + SLIP) if direction == "long" else raw_open * (1 - SLIP)

        # Gapped straight through stop on the fill bar → immediate stop-out.
        # Mark skip_daily_count=True so this phantom trade doesn't consume a daily slot.
        if direction == "long" and fill_px <= stop:
            closed = _close_pos({**pos, "fill_price": round(fill_px, 8)},
                                raw_open, ts_list[start], "stop-gap", 0)
            closed["skip_daily_count"] = True
            return closed
        if direction == "short" and fill_px >= stop:
            closed = _close_pos({**pos, "fill_price": round(fill_px, 8)},
                                raw_open, ts_list[start], "stop-gap", 0)
            closed["skip_daily_count"] = True
            return closed

        pos   = {**pos, "entry": round(fill_px, 8), "fill_price": round(fill_px, 8), "filled": True}

    # ── Use pessimistic entry for all P&L from here ──────────────────────────
    entry = pos["entry"]
    risk  = (stop - entry) if direction == "short" else (entry - stop)
    if risk <= 0:
        return _close_pos(pos, entry, pos["opened_ts"], "invalid", 0)

    if start is None:
        # Already filled in a prior run — update unrealised from latest close
        c = float(closes[-1])
        pos["current"]    = round(c, 8)
        pos["unreal_r"]   = round(((c - entry) if direction == "long" else (entry - c)) / risk, 2)
        pos["unreal_pnl"] = round(units * ((c - entry) if direction == "long" else (entry - c)) - BROK_RT, 2)
        return pos

    # ── Walk bars: check gap-through first, then intrabar high/low ───────────
    if direction == "short":
        for i in range(start, len(df)):
            if opens[i] >= stop:                 # gapped through stop (unfavorable)
                return _close_pos(pos, float(opens[i]), ts_list[i], "stop-gap",    i - start + 1)
            if opens[i] <= target:               # gapped through target (bonus)
                return _close_pos(pos, float(opens[i]), ts_list[i], "target-gap",  i - start + 1)
            if highs[i] >= stop:
                return _close_pos(pos, stop,   ts_list[i], "stop",   i - start + 1)
            if lows[i]  <= target:
                return _close_pos(pos, target, ts_list[i], "target", i - start + 1)
    else:
        for i in range(start, len(df)):
            if opens[i] <= stop:                 # gapped through stop (unfavorable)
                return _close_pos(pos, float(opens[i]), ts_list[i], "stop-gap",    i - start + 1)
            if opens[i] >= target:               # gapped through target (bonus)
                return _close_pos(pos, float(opens[i]), ts_list[i], "target-gap",  i - start + 1)
            if lows[i]  <= stop:
                return _close_pos(pos, stop,   ts_list[i], "stop",   i - start + 1)
            if highs[i] >= target:
                return _close_pos(pos, target, ts_list[i], "target", i - start + 1)

    c = float(closes[-1])
    pos["current"]    = round(c, 8)
    pos["unreal_r"]   = round(((c - entry) if direction == "long" else (entry - c)) / risk, 2)
    pos["unreal_pnl"] = round(units * ((c - entry) if direction == "long" else (entry - c)) - BROK_RT, 2)
    return pos


def close_manual(j: dict, symbol: str, direction: str, price: float, exit_date: str) -> bool:
    """Manually close a scalp position by symbol+direction. Returns True if found."""
    import datetime as _dt
    ts = (exit_date + "T00:00:00Z") if exit_date else (_dt.datetime.utcnow().isoformat(timespec="seconds") + "Z")
    for i, p in enumerate(j["open"]):
        if (p["symbol"].upper() == symbol.upper()
                and p.get("direction", "long") == direction):
            closed = _close_pos(p, price, ts, "manual", 0)
            j["closed"].append(closed)
            j["open"].pop(i)
            return True
    return False


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

    # Daily caps are scoped to the SESSION day (anchored at 08:00 UTC), derived
    # from the scan timestamp so a scan never resets the count mid-session.
    sess_day     = _session_day(scan_ts)
    # Exclude stop-gap phantom trades (gapped through stop on fill bar) from the cap —
    # those never had real market exposure so shouldn't burn a daily trade slot.
    today_closed = [c for c in j["closed"]
                    if _trade_day(c) == sess_day and not c.get("skip_daily_count")]
    today_open   = [p for p in j["open"]   if _trade_day(p) == sess_day]
    today_pnl    = sum(c.get("pnl", 0) for c in today_closed)
    trades_used  = len(today_closed) + len(today_open)

    open_keys  = {(p["symbol"], p["direction"]) for p in j["open"]}
    # Live correlation-group exposure across ALL open positions
    group_count: dict[str, int] = {}
    for p in j["open"]:
        g = p.get("corr_group") or _corr_group(p["symbol"], p.get("asset_type", ""), p.get("sector", ""))
        group_count[g] = group_count.get(g, 0) + 1

    opened_now = 0
    skipped_group = 0

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

        # Portfolio risk: don't pile into correlated names (metals, energy, us_tech…)
        group = _corr_group(r["symbol"], r.get("asset_type", ""), r.get("sector", ""))
        if group_count.get(group, 0) >= MAX_GROUP:
            skipped_group += 1
            continue

        entry = r["entry"]
        units = int(NOTIONAL / entry) if entry > 0 else 0
        if units == 0:
            continue

        j["open"].append({
            "symbol":      r["symbol"],
            "name":        r["name"],
            "asset_type":  r.get("asset_type", ""),
            "sector":      r.get("sector", ""),
            "corr_group":  group,
            "direction":   direction,
            "grade":       r["grade"],
            "score":       r["score"],
            "entry":       entry,
            "stop":        r["stop"],
            "target":      r["target"],
            "rr":          r["rr"],
            "units":       units,
            "yf_ticker":   sym_to_yf.get(r["symbol"], r["symbol"]),
            "opened_ts":   scan_ts,
            "session_day": sess_day,
            "status":      "open",
        })
        open_keys.add((r["symbol"], direction))
        group_count[group] = group_count.get(group, 0) + 1
        opened_now += 1

    if progress and skipped_group:
        print(f"  scalp journal: {skipped_group} setups skipped (correlation cap, max {MAX_GROUP}/group)")

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
