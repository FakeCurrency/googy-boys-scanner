"""Build and submit Alpaca OCO bracket orders from scalp journal positions.

Alpaca covers US equities (NASDAQ/NYSE) in paper and live mode.
ASX stocks, commodities, and crypto are NOT supported here — they require IBKR
or a CFD provider and are skipped with a logged reason.

Bracket structure submitted:
  ENTRY  limit @ entry price (GTC)
    ├── TAKE-PROFIT  limit  @ target price          ─┐ linked:
    └── STOP-LOSS    stop-limit @ stop / stop−0.1%  ─┘ one fill cancels the other

The client_order_id is deterministic: {symbol}_{direction}_{session_day}
so retried scans never double-submit the same signal.
"""

from . import alpaca_client as ac

# Alpaca paper/live API supports US equities. Expand when IBKR integration lands.
_SUPPORTED = {"nasdaq"}

# Stop-limit offset: limit price sits 0.1% through the stop so the order fills
# quickly after triggering instead of becoming a resting limit that never fills.
_STOP_LIMIT_OFFSET = 0.001


def _client_order_id(symbol: str, direction: str, session_day: str) -> str:
    return f"{symbol}_{direction}_{session_day}"


def build_bracket(pos: dict) -> dict:
    """Return the Alpaca POST /orders body for a bracket order."""
    symbol    = pos["symbol"]
    direction = pos["direction"]
    entry     = pos["entry"]
    stop      = pos["stop"]
    target    = pos["target"]
    units     = pos["units"]
    sess_day  = pos["session_day"]

    side = "buy" if direction == "long" else "sell"

    # Stop-limit: triggered at stop price, fills at stop ± 0.1% buffer
    if direction == "long":
        stop_limit = round(stop * (1 - _STOP_LIMIT_OFFSET), 4)
    else:
        stop_limit = round(stop * (1 + _STOP_LIMIT_OFFSET), 4)

    return {
        "symbol":          symbol,
        "qty":             str(units),
        "side":            side,
        "type":            "limit",
        "time_in_force":   "gtc",
        "limit_price":     str(round(entry, 4)),
        "order_class":     "bracket",
        "client_order_id": _client_order_id(symbol, direction, sess_day),
        "take_profit": {
            "limit_price": str(round(target, 4)),
        },
        "stop_loss": {
            "stop_price":  str(round(stop, 4)),
            "limit_price": str(round(stop_limit, 4)),
        },
    }


def submit(pos: dict) -> dict:
    """Submit a bracket order for a scalp position.

    Returns a dict with order_id / status on success, or skipped=True if the
    asset type is not supported by Alpaca.
    """
    asset_type = pos.get("asset_type", "").lower()
    if asset_type not in _SUPPORTED:
        return {
            "skipped": True,
            "reason":  f"asset_type='{asset_type}' not supported by Alpaca "
                       "(use IBKR for ASX/commodities)",
        }

    body = build_bracket(pos)
    resp = ac.post("/orders", body)
    return {
        "order_id":        resp["id"],
        "client_order_id": resp.get("client_order_id", ""),
        "status":          resp.get("status", "new"),
    }
