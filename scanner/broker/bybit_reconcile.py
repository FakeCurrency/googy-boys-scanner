"""Sync Bybit position and closed-PnL state into the scalp journal.

Bybit is ground truth. The journal mirrors it, never leads it.

Called at the start of every bybit_run invocation so the journal always
reflects what the broker actually holds before new orders go in.

State transitions handled:
  position exists at Bybit, size > 0  → keep open, update unrealised PnL
  position closed (not in Bybit list)  → look up closed_pnl, mark closed
  order still pending (not filled yet) → keep as open with broker_status="pending"
"""

import datetime as dt
import logging

from . import bybit_client as bc
from .bybit_bracket import to_bybit_symbol
from scanner.scalp_journal import BROK_RT

log = logging.getLogger(__name__)


def _now_ts() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _positions_by_symbol(positions: list[dict]) -> dict[str, dict]:
    """Index Bybit positions by symbol, ignoring zero-size entries."""
    out = {}
    for p in positions:
        if float(p.get("size", 0)) != 0:
            out[p["symbol"]] = p
    return out


def _find_closed_pnl(symbol: str, direction: str, closed_records: list[dict]) -> dict | None:
    """Find the most recent closed-PnL record matching symbol + direction."""
    wanted_side = "Buy" if direction == "long" else "Sell"
    matches = [
        r for r in closed_records
        if r.get("symbol") == symbol and r.get("side") == wanted_side
    ]
    if not matches:
        return None
    # Bybit returns records newest-first
    return matches[0]


def reconcile_journal(j: dict) -> dict:
    """Mutate the journal in-place: sync every Bybit-tracked open position."""

    # Fetch current state once
    try:
        live_positions = bc.get_positions()
    except Exception as e:
        log.error("could not fetch Bybit positions: %s", e)
        return j

    try:
        closed_pnl_records = bc.get_closed_pnl(limit=50)
    except Exception as e:
        log.warning("could not fetch Bybit closed PnL: %s", e)
        closed_pnl_records = []

    pos_index = _positions_by_symbol(live_positions)
    now_ts    = _now_ts()
    survivors = []

    for pos in j.get("open", []):
        # Journal positions without a Bybit order ID are paper-only — leave untouched
        if not pos.get("broker_order_id"):
            survivors.append(pos)
            continue

        bybit_sym = pos.get("bybit_symbol") or to_bybit_symbol(pos["symbol"])
        direction = pos.get("direction", "long")
        live      = pos_index.get(bybit_sym)

        if live:
            # Position still open at Bybit — update P&L and position-level risk metrics
            unreal     = float(live.get("unrealisedPnl", 0))
            avg_price  = float(live.get("avgPrice", 0))   # actual average fill price
            mark_price = float(live.get("markPrice", 0))  # current mark price

            entry    = float(pos.get("entry", 0))
            stop_p   = float(pos["stop"])
            target_p = float(pos["target"])
            risk_usd = float(pos.get("risk_per_trade") or
                             abs(entry - stop_p) * float(pos.get("units", 1)))

            stop_dist_pct   = (abs(mark_price - stop_p) / mark_price * 100
                               if mark_price > 0 else 0.0)
            target_dist_pct = (abs(target_p - mark_price) / mark_price * 100
                               if mark_price > 0 else 0.0)
            current_r       = round(unreal / risk_usd, 2) if risk_usd > 0 else 0.0

            fill_price = avg_price if avg_price > 0 else pos.get("fill_price")

            survivors.append({
                **pos,
                "unreal_pnl":       round(unreal, 2),
                "broker_status":    "open",
                "fill_price":       (round(fill_price, 8) if fill_price else pos.get("fill_price")),
                "mark_price":       (round(mark_price, 6) if mark_price else None),
                "current_r":        current_r,
                "stop_dist_pct":    round(stop_dist_pct, 2),
                "target_dist_pct":  round(target_dist_pct, 2),
            })
            continue

        # Position is gone from Bybit — find out why via closed_pnl
        closed_rec = _find_closed_pnl(bybit_sym, direction, closed_pnl_records)

        if closed_rec:
            closed_pnl = float(closed_rec.get("closedPnl", 0))
            exit_type  = closed_rec.get("exitType", "unknown")
            reason_map = {
                "takeProfit":        "target",
                "StopLoss":          "stop",
                "Liq":               "liquidated",
                "BustTrade":         "liquidated",
                "PartialTakeProfit": "target",
            }
            reason = reason_map.get(exit_type, exit_type.lower())
            pnl    = round(closed_pnl - BROK_RT, 2)

            fill_price = float(pos.get("fill_price") or pos["entry"])
            stop       = float(pos["stop"])
            risk       = abs(fill_price - stop)
            r_val      = (round(closed_pnl / (risk * float(pos.get("units", 1))), 2)
                          if risk > 0 else 0.0)

            # Detect fill-price divergence from intended entry
            intended = float(pos["entry"])
            slip_pct = abs(fill_price - intended) / intended * 100 if intended > 0 else 0.0

            log.info("%s %s → %s  pnl=$%.2f  r=%.2f  slip=%.2f%%",
                     pos["symbol"], direction, reason, pnl, r_val, slip_pct)

            j["closed"].append({
                **pos,
                "status":        "closed",
                "exit_ts":       now_ts,
                "reason":        reason,
                "pnl":           pnl,
                "r":             r_val,
                "fill_price":    pos.get("fill_price"),
                "entry_slip_pct": round(slip_pct, 3),
                "broker_status": "closed",
            })
        else:
            # No closed record found yet — order may not have filled
            log.warning("%s not in live positions and no closed record "
                        "— keeping open (may be pending entry)", pos["symbol"])
            survivors.append({**pos, "broker_status": "pending"})

    j["open"] = survivors
    return j
