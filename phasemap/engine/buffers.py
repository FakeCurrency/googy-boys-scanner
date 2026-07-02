"""Zone buffer function (spec Section 3.1) — deterministic, price-scaled.

All zone padding in the entire product derives from buffer(). Never pad a
zone any other way.

Market-aware tick sizes (ruleset 1.1.0): the ASX bands are the spec's
originals; NASDAQ uses cent ticks (sub-$1 stocks quote to $0.0001); crypto
has no exchange tick, so a relative 1-basis-point step is used — the ATR and
percentage-floor terms dominate there anyway.
"""

from phasemap.config import CONFIG


def asx_tick(price: float) -> float:
    """ASX equity price steps."""
    if price < 0.10:
        return 0.001
    if price < 2.00:
        return 0.005
    return 0.01


def tick_size(price: float, market: str = "asx") -> float:
    if market == "nasdaq":
        return 0.0001 if price < 1.00 else 0.01
    if market == "crypto":
        return max(price * 0.0001, 1e-9)
    return asx_tick(price)


def pct_floor(price: float) -> float:
    """Wider minimum bands for cents stocks (price-relative, so it scales
    to sub-cent crypto too)."""
    if price < 0.10:
        return CONFIG.pct_floor_sub10c
    if price < 1.00:
        return CONFIG.pct_floor_sub1
    return CONFIG.pct_floor_default


def buffer(close: float, atr20: float, market: str = "asx") -> float:
    """Master zone padding: max of half-ATR, two ticks, and a % floor."""
    return max(
        CONFIG.buffer_atr_mult * atr20,
        CONFIG.buffer_tick_mult * tick_size(close, market),
        pct_floor(close) * close,
    )
