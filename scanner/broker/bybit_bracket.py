"""Build and submit Bybit USDT-perpetual bracket orders from scalp signals.

Bybit V5 supports embedded TP/SL on the entry order — cleaner than Alpaca's
separate OCO legs. One order call does everything:
  entry (limit or market)
    ├── takeProfit  →  limit order auto-placed by Bybit on fill
    └── stopLoss    →  stop-market auto-placed by Bybit on fill

Only crypto signals (asset_type="crypto") are submitted here.
NASDAQ and ASX signals are skipped — those go via IBKR (future).

Symbol mapping: yfinance "BTC-USD" → Bybit "BTCUSDT" (drop "-USD", add "USDT").
"""

import logging
import os
import time

from . import bybit_client as bc
from scanner import config

log = logging.getLogger(__name__)

_CRYPTO_ASSET_TYPE = "crypto"


# ── symbol utilities ──────────────────────────────────────────────────────────

def to_bybit_symbol(yf_ticker: str) -> str:
    """Convert a yfinance crypto ticker to a Bybit linear perpetual symbol.

    "BTC-USD"  → "BTCUSDT"
    "ETH-USD"  → "ETHUSDT"
    "SOL-USD"  → "SOLUSDT"
    """
    base = yf_ticker.upper().replace("-USD", "").replace("-USDT", "")
    return base + "USDT"


def _fmt_qty(qty: float) -> str:
    """Format quantity to a reasonable precision for Bybit."""
    if qty >= 1000:
        return f"{qty:.1f}"
    if qty >= 100:
        return f"{qty:.2f}"
    if qty >= 10:
        return f"{qty:.3f}"
    if qty >= 1:
        return f"{qty:.4f}"
    return f"{qty:.5f}"


def _fmt_price(price: float) -> str:
    """Format price to a reasonable precision for Bybit."""
    if price >= 10_000:
        return f"{price:.1f}"
    if price >= 100:
        return f"{price:.2f}"
    if price >= 1:
        return f"{price:.4f}"
    return f"{price:.6f}"


def calc_qty(entry: float, notional: float) -> float:
    """Position size in base-asset units given notional dollar exposure (legacy)."""
    return notional / entry if entry > 0 else 0.0


def calc_qty_risk(entry: float, stop: float, risk_per_trade: float) -> float:
    """ATR/stop-based position sizing: risk a fixed dollar amount per trade.

    qty = risk_per_trade / |entry - stop|

    This gives consistent dollar risk per trade regardless of instrument
    volatility, unlike fixed-notional sizing which lets risk vary with ATR.
    Falls back to 0.0 if stop == entry (zero risk distance) or entry <= 0.
    """
    stop_dist = abs(entry - stop)
    if stop_dist <= 0 or entry <= 0:
        return 0.0
    return risk_per_trade / stop_dist


def _order_link_id(symbol: str, direction: str, session_day: str) -> str:
    """Deterministic client order ID — prevents double-submission on retried scans."""
    raw = f"{symbol}_{direction}_{session_day}"
    return raw[:36]   # Bybit max = 36 chars


# ── order submission ──────────────────────────────────────────────────────────

def submit(pos: dict) -> dict:
    """Submit a bracket entry order to Bybit with embedded TP and SL.

    pos keys expected:
      symbol, direction, entry, stop, target, units, session_day, asset_type

    Returns:
      {"order_id": ..., "order_link_id": ..., "status": "New"}  on success
      {"skipped": True, "reason": "..."}                         on skip/error
    """
    asset_type = pos.get("asset_type", "").lower()
    if asset_type != _CRYPTO_ASSET_TYPE:
        return {
            "skipped": True,
            "reason":  f"asset_type='{asset_type}' not supported by Bybit broker "
                       "(only crypto; use IBKR for ASX/commodities)",
        }

    direction = pos["direction"].lower()
    symbol    = to_bybit_symbol(pos["symbol"])
    side      = "Buy" if direction == "long" else "Sell"
    entry     = float(pos["entry"])
    stop      = float(pos["stop"])
    target    = float(pos["target"])
    units     = float(pos.get("units", 0))
    sess_day  = pos.get("session_day", "")

    if units <= 0:
        return {"skipped": True, "reason": "units=0, position too small"}

    order_link_id = _order_link_id(symbol, direction, sess_day)

    order_kwargs = dict(
        category="linear",
        symbol=symbol,
        side=side,
        orderType="Limit",
        qty=_fmt_qty(units),
        price=_fmt_price(entry),
        timeInForce="GTC",
        orderLinkId=order_link_id,
        takeProfit=_fmt_price(target),
        stopLoss=_fmt_price(stop),
        tpTriggerBy="LastPrice",
        slTriggerBy="LastPrice",
        tpslMode="Full",
    )

    result   = None
    last_exc = None
    attempts = config.ORDER_RETRY_ATTEMPTS
    for attempt in range(1, attempts + 1):
        try:
            result = bc.place_order(**order_kwargs)
            break
        except Exception as e:
            last_exc = e
            if attempt < attempts:
                wait = config.ORDER_RETRY_BACKOFF_BASE ** attempt
                log.warning("order attempt %d/%d failed (%s) — retrying in %ds",
                            attempt, attempts, e, wait)
                time.sleep(wait)

    if result is None:
        return {"skipped": True, "reason": f"Bybit API error after {attempts} attempts: {last_exc}"}

    return {
        "order_id":      result.get("orderId", ""),
        "order_link_id": result.get("orderLinkId", order_link_id),
        "bybit_symbol":  symbol,
        "status":        result.get("orderStatus", "New"),
    }
