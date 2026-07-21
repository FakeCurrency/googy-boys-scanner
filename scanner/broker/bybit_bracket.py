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
    """Fallback quantity precision — used ONLY when the instrument spec is
    unavailable (see _quantize)."""
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
    """Fallback price precision — used ONLY when the instrument spec is
    unavailable (see _quantize)."""
    if price >= 10_000:
        return f"{price:.1f}"
    if price >= 100:
        return f"{price:.2f}"
    if price >= 1:
        return f"{price:.4f}"
    return f"{price:.6f}"


def _snap(value: float, step: float, mode: str = "round") -> float:
    """Snap value onto a step grid (floor for qty — never oversize)."""
    if step <= 0:
        return value
    n = value / step
    n = int(n) if mode == "floor" else round(n)
    # re-quantise through the step's own decimal places to kill float dust
    dp = max(0, -_decimal_exp(step))
    return round(n * step, dp)


def _decimal_exp(x: float) -> int:
    s = f"{x:.10f}".rstrip("0")
    return -(len(s.split(".")[1])) if "." in s and s.split(".")[1] else 0


def _quantize(symbol: str, units: float, prices: dict[str, float]) -> tuple[str, dict[str, str], str | None]:
    """Quantise qty/prices to the instrument's REAL qtyStep/tickSize.

    Bybit rejects any qty not a multiple of qtyStep and any price off the
    tickSize grid — the old guessed decimal ladders produced exactly such
    orders (e.g. BTCUSDT qtyStep 0.001). Falls back to the ladder formatting
    if the spec lookup fails (fail-open: a spec outage must not block paper).
    Returns (qty_str, {name: price_str}, skip_reason|None)."""
    try:
        spec = bc.get_instrument_spec(symbol)
    except Exception as e:
        log.warning("no instrument spec for %s (%s) — falling back to ladder "
                    "formatting", symbol, e)
        return _fmt_qty(units), {k: _fmt_price(v) for k, v in prices.items()}, None
    qty = _snap(units, spec["qty_step"], mode="floor")
    if spec["min_qty"] and qty < spec["min_qty"]:
        return "", {}, (f"qty {qty:g} below minOrderQty {spec['min_qty']:g} "
                        f"(step {spec['qty_step']:g})")
    return (f"{qty:g}",
            {k: f"{_snap(v, spec['tick_size']):g}" for k, v in prices.items()},
            None)


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

    qty_str, px, skip = _quantize(symbol, units,
                                  {"entry": entry, "stop": stop, "target": target})
    if skip:
        return {"skipped": True, "reason": skip}

    order_kwargs = dict(
        category="linear",
        symbol=symbol,
        side=side,
        orderType="Limit",
        qty=qty_str,
        price=px["entry"],
        timeInForce="GTC",
        orderLinkId=order_link_id,
        takeProfit=px["target"],
        stopLoss=px["stop"],
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
            # AMBIGUOUS-TIMEOUT GUARD: a timeout/network error can land AFTER Bybit
            # accepted the order — blind retry would double-enter. Before any
            # retry, ask Bybit whether our deterministic client id already
            # exists; if it does, that IS our order.
            try:
                existing = bc.find_order_by_link_id(symbol, order_link_id)
            except Exception:
                existing = {}
            if existing.get("orderId"):
                log.warning("order attempt %d errored (%s) but orderLinkId %s "
                            "already exists at Bybit — adopting it, NOT retrying",
                            attempt, e, order_link_id)
                result = existing
                break
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
