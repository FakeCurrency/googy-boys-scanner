"""Zone buffer function (spec Section 3.1) — deterministic, price-scaled.

All zone padding in the entire product derives from buffer(). Never pad a
zone any other way.
"""

from phasemap.config import CONFIG


def asx_tick(price: float) -> float:
    """ASX equity price steps."""
    if price < 0.10:
        return 0.001
    if price < 2.00:
        return 0.005
    return 0.01


def pct_floor(price: float) -> float:
    """Wider minimum bands for cents stocks."""
    if price < 0.10:
        return CONFIG.pct_floor_sub10c
    if price < 1.00:
        return CONFIG.pct_floor_sub1
    return CONFIG.pct_floor_default


def buffer(close: float, atr20: float) -> float:
    """Master zone padding: max of half-ATR, two ticks, and a % floor."""
    return max(
        CONFIG.buffer_atr_mult * atr20,
        CONFIG.buffer_tick_mult * asx_tick(close),
        pct_floor(close) * close,
    )
