"""Backtest vs live execution reconciliation.

Compares actual journal fills against what the scalp backtest would have
predicted for the same signals. Surfaces fill slippage, win-rate delta,
and avg-R delta so we can see if live results track the backtest.

Writes public/data/live_vs_backtest.json consumed by the frontend.

Backtest data comes from public/data/backtest_results.json (written by
the weekly backtest workflow). If that file doesn't exist yet, this
module skips gracefully.
"""

import json
import logging
import pathlib

from scanner.journal_common import atomic_write as _atomic_write

log = logging.getLogger(__name__)

ROOT          = pathlib.Path(__file__).resolve().parents[2]
BACKTEST_FILE = ROOT / "public" / "data" / "backtest_results.json"
LVB_FILE      = ROOT / "public" / "data" / "live_vs_backtest.json"


def _load_json(path: pathlib.Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("could not read %s: %s", path.name, e)
        return None


def reconcile(j: dict) -> dict:
    """Compare live journal against backtest expectations.

    Returns a summary dict and writes it to live_vs_backtest.json.
    """
    bt = _load_json(BACKTEST_FILE)
    if not bt:
        log.debug("backtest_results.json not found — skipping live vs backtest reconciliation")
        return {"status": "no_backtest_data"}

    bt_trades   = bt.get("trades", [])
    live_trades = [t for t in j.get("closed", []) if not t.get("skip_daily_count")]

    if not live_trades or not bt_trades:
        return {
            "status":   "insufficient_data",
            "live":     len(live_trades),
            "backtest": len(bt_trades),
        }

    # Index backtest trades by (symbol, direction, session_day)
    bt_index: dict[tuple, dict] = {}
    for t in bt_trades:
        key = (t.get("symbol"), t.get("direction"), t.get("session_day"))
        bt_index[key] = t

    matched = []
    for lt in live_trades:
        key  = (lt.get("symbol"), lt.get("direction"), lt.get("session_day"))
        bt_t = bt_index.get(key)
        if not bt_t:
            continue

        slip = 0.0
        fill  = lt.get("fill_price")
        entry = bt_t.get("entry")
        if fill and entry and float(entry) > 0:
            slip = (float(fill) - float(entry)) / float(entry)

        matched.append({
            "symbol":         lt["symbol"],
            "direction":      lt.get("direction"),
            "session_day":    lt.get("session_day"),
            "live_pnl":       lt.get("pnl", 0),
            "bt_pnl":         bt_t.get("pnl", 0),
            "live_r":         lt.get("r", 0),
            "bt_r":           bt_t.get("r", 0),
            "entry_slip_pct": round(slip * 100, 3),
        })

    if not matched:
        return {
            "status":   "no_matched_trades",
            "live":     len(live_trades),
            "backtest": len(bt_trades),
        }

    avg_slip   = round(sum(m["entry_slip_pct"] for m in matched) / len(matched), 3)
    live_wr    = round(sum(1 for m in matched if m["live_pnl"] > 0) / len(matched) * 100, 1)
    bt_wr      = round(sum(1 for m in matched if m["bt_pnl"] > 0) / len(matched) * 100, 1)
    live_avg_r = round(sum(m["live_r"] for m in matched) / len(matched), 2)
    bt_avg_r   = round(sum(m["bt_r"]   for m in matched) / len(matched), 2)

    result = {
        "status":              "ok",
        "matched_trades":      len(matched),
        "live_trades_total":   len(live_trades),
        "bt_trades_total":     len(bt_trades),
        "avg_entry_slip_pct":  avg_slip,
        "live_win_rate":       live_wr,
        "backtest_win_rate":   bt_wr,
        "win_rate_delta":      round(live_wr - bt_wr, 1),
        "live_avg_r":          live_avg_r,
        "backtest_avg_r":      bt_avg_r,
        "r_delta":             round(live_avg_r - bt_avg_r, 2),
        "trades":              matched,
    }

    payload = json.dumps(result, indent=2)
    LVB_FILE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(LVB_FILE, payload)
    log.info("live_vs_backtest: matched=%d  slip=%.2f%%  wr_delta=%.1f%%  r_delta=%.2f",
             len(matched), avg_slip, result["win_rate_delta"], result["r_delta"])
    return result
