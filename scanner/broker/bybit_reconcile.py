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

from . import bybit_client as bc
from .bybit_bracket import to_bybit_symbol
from scanner.scalp_journal import BROK_RT


def _now_ts() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


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
        print(f"  bybit_reconcile: could not fetch positions — {e}")
        return j

    # Fetch recent closed PnL for exit detection (last 50 records per call)
    try:
        closed_pnl_records = bc.get_closed_pnl(limit=50)
    except Exception as e:
        print(f"  bybit_reconcile: could not fetch closed PnL — {e}")
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
            # Position still open at Bybit — update unrealised P&L
            unreal = float(live.get("unrealisedPnl", 0))
            survivors.append({
                **pos,
                "unreal_pnl":    round(unreal, 2),
                "broker_status": "open",
            })
            continue

        # Position is gone from Bybit — find out why via closed_pnl
        closed_rec = _find_closed_pnl(bybit_sym, direction, closed_pnl_records)

        if closed_rec:
            closed_pnl   = float(closed_rec.get("closedPnl", 0))
            exit_type    = closed_rec.get("exitType", "unknown")
            # Bybit exitType values: "takeProfit", "StopLoss", "Liq", "BustTrade", "PartialTakeProfit"
            reason_map   = {
                "takeProfit":         "target",
                "StopLoss":           "stop",
                "Liq":                "liquidated",
                "BustTrade":          "liquidated",
                "PartialTakeProfit":  "target",
            }
            reason       = reason_map.get(exit_type, exit_type.lower())
            # Net P&L from broker already includes fee; subtract our brokerage constant
            # to keep consistent with the paper journal model
            pnl          = round(closed_pnl - BROK_RT, 2)

            entry = float(pos.get("fill_price") or pos["entry"])
            stop  = float(pos["stop"])
            risk  = abs(entry - stop)
            # Approximate R from PnL (actual fill may differ from planned entry)
            r_val = round((closed_pnl / (risk * float(pos.get("units", 1)))), 2) if risk > 0 else 0.0

            print(f"  bybit_reconcile: {pos['symbol']} {direction} → {reason} "
                  f"pnl=${pnl:.2f}")

            j["closed"].append({
                **pos,
                "status":        "closed",
                "exit_ts":       now_ts,
                "reason":        reason,
                "pnl":           pnl,
                "r":             r_val,
                "broker_status": "closed",
            })
        else:
            # No closed record found yet — order may not have filled
            # Keep it open, flag the ambiguity
            print(f"  bybit_reconcile: {pos['symbol']} not in live positions "
                  "and no closed record — keeping open (may be pending entry)")
            survivors.append({**pos, "broker_status": "pending"})

    j["open"] = survivors
    return j
