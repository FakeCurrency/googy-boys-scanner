"""Thin wrapper around the Bybit V5 Unified Trading API.

Auth via env vars:
  BYBIT_API_KEY       Bybit key ID (always required)

  RSA auth (new Bybit API keys — paste public key on Bybit, store private key here):
  BYBIT_PRIVATE_KEY   Full PEM content of your private key
                      (-----BEGIN RSA PRIVATE KEY----- ... -----END RSA PRIVATE KEY-----)

  HMAC auth (older keys that have an API secret):
  BYBIT_API_SECRET    Bybit secret key

  RSA is used when BYBIT_PRIVATE_KEY is set; HMAC otherwise.

Mode:
  BYBIT_TESTNET=false  → live endpoint (api.bybit.com)
  default              → testnet endpoint (api-testnet.bybit.com)  ← safe default

Create testnet API keys at: https://testnet.bybit.com/app/user/api-management
Create live API keys at:    https://www.bybit.com/app/user/api-management

Permissions needed on the key (Unified Trading, Read-Write):
  - Orders + Positions
DO NOT grant Withdrawal permissions.
"""

import logging
import os
import time

from pybit.unified_trading import HTTP

from scanner import config as _cfg

log = logging.getLogger(__name__)


def _testnet() -> bool:
    return os.environ.get("BYBIT_TESTNET", "true").lower() != "false"


def _session() -> HTTP:
    api_key     = os.environ["BYBIT_API_KEY"]
    private_key = os.environ.get("BYBIT_PRIVATE_KEY", "").strip()
    api_secret  = os.environ.get("BYBIT_API_SECRET", "").strip()

    if private_key:
        # RSA auth — new Bybit API keys use RSA public/private key pairs
        return HTTP(
            testnet=_testnet(),
            api_key=api_key,
            private_key=private_key,
        )
    else:
        # HMAC auth — older Bybit API keys with an API secret
        return HTTP(
            testnet=_testnet(),
            api_key=api_key,
            api_secret=api_secret,
        )


def _retry(fn, *args, **kwargs):
    """Call fn(*args, **kwargs) with exponential-backoff retry on failure.

    Reads ORDER_RETRY_ATTEMPTS (default 3) and ORDER_RETRY_BACKOFF_BASE
    (default 2) from config.  Sleep schedule: 2s, 4s, 8s for base=2.
    Re-raises the final exception if all attempts are exhausted.
    """
    attempts = int(getattr(_cfg, "ORDER_RETRY_ATTEMPTS", 3))
    base     = float(getattr(_cfg, "ORDER_RETRY_BACKOFF_BASE", 2.0))

    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt == attempts:
                log.error(
                    "Bybit API failed after %d attempt(s): %s",
                    attempts, exc,
                )
                raise
            wait = base ** attempt
            log.warning(
                "Bybit API error (attempt %d/%d): %s — retrying in %.0fs",
                attempt, attempts, exc, wait,
            )
            time.sleep(wait)

    raise last_exc  # unreachable; satisfies type checkers


# ── order management ──────────────────────────────────────────────────────────

def place_order(**kwargs) -> dict:
    return _retry(lambda: _session().place_order(**kwargs))["result"]


def cancel_order(symbol: str, order_id: str) -> dict:
    return _retry(
        lambda: _session().cancel_order(
            category="linear", symbol=symbol, orderId=order_id
        )
    )["result"]


def cancel_all_orders(symbol: str | None = None) -> dict:
    kwargs = {"category": "linear", "settleCoin": "USDT"}
    if symbol:
        kwargs["symbol"] = symbol
    return _retry(lambda: _session().cancel_all_orders(**kwargs))["result"]


# ── position management ───────────────────────────────────────────────────────

def get_positions(symbol: str | None = None) -> list[dict]:
    kwargs = {"category": "linear", "settleCoin": "USDT"}
    if symbol:
        kwargs["symbol"] = symbol
    return _retry(lambda: _session().get_positions(**kwargs))["result"].get("list", [])


def close_position(symbol: str, side: str, qty: str) -> dict:
    """Close an open position with a market order (reduceOnly).

    side: "Buy" or "Sell" — must be the OPPOSITE of the position's side.
    """
    return _retry(
        lambda: _session().place_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=qty,
            reduceOnly=True,
            timeInForce="IOC",
        )
    )["result"]


def close_all_positions() -> list[dict]:
    """Flatten every open linear position with a market reduceOnly order."""
    positions = get_positions()
    results = []
    for p in positions:
        size = p.get("size", "0")
        if float(size) == 0:
            continue
        pos_side   = p.get("side", "")
        close_side = "Sell" if pos_side == "Buy" else "Buy"
        symbol     = p["symbol"]
        try:
            r = close_position(symbol, close_side, size)
            results.append({"symbol": symbol, "result": r})
            log.info("bybit: closed %s %s %s", symbol, pos_side, size)
        except Exception as e:
            results.append({"symbol": symbol, "error": str(e)})
            log.error("bybit: ERROR closing %s: %s", symbol, e)
    return results


# ── order status ─────────────────────────────────────────────────────────────

def get_order_status(symbol: str, order_id: str) -> dict:
    """Fetch current status of a specific order (open or historical)."""
    sess = _session()

    def _fetch():
        resp = sess.get_open_orders(category="linear", symbol=symbol, orderId=order_id)
        orders = resp["result"].get("list", [])
        if orders:
            return orders[0]
        resp2 = sess.get_order_history(
            category="linear", symbol=symbol, orderId=order_id, limit=1
        )
        hist = resp2["result"].get("list", [])
        return hist[0] if hist else {}

    return _retry(_fetch)


# ── closed P&L history ────────────────────────────────────────────────────────

def get_closed_pnl(symbol: str | None = None, limit: int = 50) -> list[dict]:
    """Recent closed position P&L records — used by reconcile to detect exits."""
    kwargs = {"category": "linear", "limit": limit}
    if symbol:
        kwargs["symbol"] = symbol
    return _retry(lambda: _session().get_closed_pnl(**kwargs))["result"].get("list", [])


# ── account info ──────────────────────────────────────────────────────────────

def wallet_balance() -> dict:
    def _fetch():
        resp  = _session().get_wallet_balance(accountType="UNIFIED")
        coins = resp["result"].get("list", [{}])[0].get("coin", [])
        usdt  = next((c for c in coins if c["coin"] == "USDT"), {})
        return {
            "equity":     float(usdt.get("equity", 0)),
            "available":  float(usdt.get("availableToWithdraw", 0)),
            "unrealised": float(usdt.get("unrealisedPnl", 0)),
        }

    return _retry(_fetch)


def mode() -> str:
    return "TESTNET" if _testnet() else "LIVE ⚠️"



def _testnet() -> bool:
    return os.environ.get("BYBIT_TESTNET", "true").lower() != "false"


def _session() -> HTTP:
    api_key     = os.environ["BYBIT_API_KEY"]
    private_key = os.environ.get("BYBIT_PRIVATE_KEY", "").strip()
    api_secret  = os.environ.get("BYBIT_API_SECRET", "").strip()

    if private_key:
        # RSA auth — new Bybit API keys use RSA public/private key pairs
        return HTTP(
            testnet=_testnet(),
            api_key=api_key,
            private_key=private_key,
        )
    else:
        # HMAC auth — older Bybit API keys with an API secret
        return HTTP(
            testnet=_testnet(),
            api_key=api_key,
            api_secret=api_secret,
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


# ── order status ─────────────────────────────────────────────────────────────

def get_order_status(symbol: str, order_id: str) -> dict:
    """Fetch current status of a specific order (open or historical)."""
    sess = _session()
    resp = sess.get_open_orders(category="linear", symbol=symbol, orderId=order_id)
    orders = resp["result"].get("list", [])
    if orders:
        return orders[0]
    # Not in open orders — look up in order history
    resp2 = sess.get_order_history(category="linear", symbol=symbol, orderId=order_id, limit=1)
    hist = resp2["result"].get("list", [])
    return hist[0] if hist else {}


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
