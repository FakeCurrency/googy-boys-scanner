"""Thin wrapper around the Bybit V5 Unified Trading API.

Auth via env vars — both must be set:
  BYBIT_API_KEY      Bybit key ID
  BYBIT_API_SECRET   Bybit secret key

Mode:
  BYBIT_TESTNET=false  → live endpoint (api.bybit.com)
  default              → testnet endpoint (api-testnet.bybit.com)  ← safe default

Create testnet API keys at: https://testnet.bybit.com/app/user/api-management
Create live API keys at:    https://www.bybit.com/app/user/api-management

Scopes needed on the key:
  - Contract: Order, Position (Read + Write)
  - Unified Trade: Order, Position (Read + Write)
DO NOT grant withdrawal permissions.
"""

import os

from pybit.unified_trading import HTTP


def _testnet() -> bool:
    return os.environ.get("BYBIT_TESTNET", "true").lower() != "false"


def _session() -> HTTP:
    return HTTP(
        testnet=_testnet(),
        api_key=os.environ["BYBIT_API_KEY"],
        api_secret=os.environ["BYBIT_API_SECRET"],
    )


# ── order management ──────────────────────────────────────────────────────────

def place_order(**kwargs) -> dict:
    resp = _session().place_order(**kwargs)
    return resp["result"]


def cancel_order(symbol: str, order_id: str) -> dict:
    resp = _session().cancel_order(category="linear", symbol=symbol, orderId=order_id)
    return resp["result"]


def cancel_all_orders(symbol: str | None = None) -> dict:
    kwargs = {"category": "linear", "settleCoin": "USDT"}
    if symbol:
        kwargs["symbol"] = symbol
    resp = _session().cancel_all_orders(**kwargs)
    return resp["result"]


# ── position management ───────────────────────────────────────────────────────

def get_positions(symbol: str | None = None) -> list[dict]:
    kwargs = {"category": "linear", "settleCoin": "USDT"}
    if symbol:
        kwargs["symbol"] = symbol
    resp = _session().get_positions(**kwargs)
    return resp["result"].get("list", [])


def close_position(symbol: str, side: str, qty: str) -> dict:
    """Close an open position with a market order (reduceOnly).

    side: "Buy" or "Sell" — must be the OPPOSITE of the position's side.
    """
    resp = _session().place_order(
        category="linear",
        symbol=symbol,
        side=side,
        orderType="Market",
        qty=qty,
        reduceOnly=True,
        timeInForce="IOC",
    )
    return resp["result"]


def close_all_positions() -> list[dict]:
    """Flatten every open linear position with a market reduceOnly order."""
    positions = get_positions()
    results = []
    for p in positions:
        size = p.get("size", "0")
        if float(size) == 0:
            continue
        pos_side = p.get("side", "")
        # Flip the side to close
        close_side = "Sell" if pos_side == "Buy" else "Buy"
        symbol = p["symbol"]
        try:
            r = close_position(symbol, close_side, size)
            results.append({"symbol": symbol, "result": r})
            print(f"  bybit: closed {symbol} {pos_side} {size}")
        except Exception as e:
            results.append({"symbol": symbol, "error": str(e)})
            print(f"  bybit: ERROR closing {symbol}: {e}")
    return results


# ── closed P&L history ────────────────────────────────────────────────────────

def get_closed_pnl(symbol: str | None = None, limit: int = 50) -> list[dict]:
    """Recent closed position P&L records — used by reconcile to detect exits."""
    kwargs = {"category": "linear", "limit": limit}
    if symbol:
        kwargs["symbol"] = symbol
    resp = _session().get_closed_pnl(**kwargs)
    return resp["result"].get("list", [])


# ── account info ──────────────────────────────────────────────────────────────

def wallet_balance() -> dict:
    resp = _session().get_wallet_balance(accountType="UNIFIED")
    coins = resp["result"].get("list", [{}])[0].get("coin", [])
    usdt = next((c for c in coins if c["coin"] == "USDT"), {})
    return {
        "equity":       float(usdt.get("equity", 0)),
        "available":    float(usdt.get("availableToWithdraw", 0)),
        "unrealised":   float(usdt.get("unrealisedPnl", 0)),
    }


def mode() -> str:
    return "TESTNET" if _testnet() else "LIVE ⚠️"
