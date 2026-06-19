"""Sync Alpaca order/position state into the scalp journal.

Alpaca is ground truth. The journal mirrors it, never leads it.

Called at the start of every paper_run invocation so the journal
always reflects what the broker actually holds before new orders go in.

State transitions handled:
  new / pending_new / accepted → keep as open, update broker_status
  filled (entry only)          → mark filled, update fill_price
  filled (exit leg)            → close position, compute R and P&L
  canceled / rejected / expired → close with 0 P&L and reason = broker status
"""

import datetime as dt

from . import alpaca_client as ac

_TERMINAL = {"filled", "canceled", "expired", "rejected", "done_for_day", "replaced"}


def _fetch_all_orders() -> dict:
    """Fetch open + recent closed orders, indexed by id and client_order_id."""
    by_id, by_coid = {}, {}
    for batch in (ac.open_orders, ac.closed_orders):
        try:
            for o in batch():
                by_id[o["id"]]                 = o
                by_coid[o["client_order_id"]]  = o
        except Exception as e:
            print(f"  reconcile: warning — could not fetch orders ({batch.__name__}): {e}")
    return by_id


def _close_from_broker(pos: dict, exit_price: float, reason: str, now_ts: str) -> dict:
    """Close a journal position using a broker-confirmed exit price (no extra slippage)."""
    from ..scalp_journal import BROK_RT

    direction = pos["direction"]
    entry     = float(pos.get("fill_price") or pos["entry"])
    stop      = float(pos["stop"])
    risk      = abs(entry - stop)
    units     = int(pos.get("units") or 0)

    if direction == "long":
        r_val = round((exit_price - entry) / risk, 2) if risk > 0 else 0.0
        gross = units * (exit_price - entry)
    else:
        r_val = round((entry - exit_price) / risk, 2) if risk > 0 else 0.0
        gross = units * (entry - exit_price)

    pnl = round(gross - BROK_RT, 2)

    return {
        **pos,
        "status":        "closed",
        "fill_price":    round(entry, 8),
        "exit":          round(exit_price, 8),
        "exit_ts":       now_ts,
        "reason":        reason,
        "bars":          0,
        "r":             r_val,
        "pnl":           pnl,
        "broker_status": "filled_exit",
    }


def reconcile_journal(j: dict) -> dict:
    """Mutates the journal in-place: sync every broker-tracked position."""
    orders_by_id = _fetch_all_orders()
    now_ts = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"

    survivors = []
    for pos in j.get("open", []):
        oid = pos.get("broker_order_id")
        if not oid:
            # Paper-only position — not submitted to broker
            survivors.append(pos)
            continue

        order = orders_by_id.get(oid)
        if order is None:
            # Not found in recent history — leave alone to avoid phantom closes
            survivors.append(pos)
            continue

        status = order.get("status", "")

        if status not in _TERMINAL:
            # Still live — update status field only
            survivors.append({**pos, "broker_status": status})
            continue

        if status in ("canceled", "expired", "rejected", "done_for_day", "replaced"):
            print(f"  reconcile: {pos['symbol']} {pos['direction']} → {status}, removing")
            j["closed"].append({
                **pos,
                "status":        "closed",
                "exit":          pos["entry"],
                "exit_ts":       now_ts,
                "reason":        status,
                "bars":          0,
                "r":             0.0,
                "pnl":           0.0,
                "broker_status": status,
            })
            continue

        if status == "filled":
            # Entry filled. Check if an exit leg also fired.
            legs        = order.get("legs") or []
            filled_legs = [l for l in legs if l.get("status") == "filled"]

            if filled_legs:
                # An exit leg closed the position
                leg        = filled_legs[0]
                exit_price = float(leg.get("filled_avg_price") or leg.get("limit_price") or pos["target"])
                leg_type   = leg.get("type", "")
                reason     = "target" if "limit" in leg_type else "stop"
                closed     = _close_from_broker(pos, exit_price, reason, now_ts)
                j["closed"].append(closed)
                print(f"  reconcile: {pos['symbol']} {pos['direction']} → {reason} @ {exit_price:.4f}")
            else:
                # Entry only filled — position is now open
                fill_price = float(order.get("filled_avg_price") or pos["entry"])
                survivors.append({
                    **pos,
                    "fill_price":    round(fill_price, 8),
                    "filled":        True,
                    "broker_status": "filled_entry",
                })

    j["open"] = survivors
    return j
