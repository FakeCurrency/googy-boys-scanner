"""Pine-compatible MACD.

THE REPO HAS NONE. A case-insensitive search for "macd" across `scanner/`,
`phasemap/`, `scripts/`, `public/js/`, `test/` and `tests/` returns nothing, so
this is not a duplicate of an existing helper -- it is the first one, and it
lives inside the lens rather than in `scanner/indicators.py` so that deleting
the lens takes it with it.

12/26/9 on `close`, EMA-based end to end with Pine's SMA seeding, returned in
Pine's own order (macd, signal, hist) with `hist = macd - signal`. Note the
signal line is an EMA OF THE MACD LINE -- an EMA of a difference of EMAs, not
an EMA of price -- which is why its first valid bar is 33 and not 26.

Rule B reads the HISTOGRAM SIGN ONLY, strictly: a histogram of exactly zero
scores neither side. The magnitude is never used.

# PORTED VERBATIM from tradingview/scanner-spec/reference/vivek50_screen.py.
# The function bodies below were EXTRACTED, not retyped: a hand-transcription
# of trading maths drifts silently, and `tests/test_momentum_screen.py` proves
# bit-identity against the reference rather than trusting this comment. The
# only edits are namespace ones, and they are listed at each site:
#   ScreenConfig    -> MomentumConfig      (scanner/momentum/config.py)
#   DEFAULT_CONFIG  -> config.DEFAULTS
#   cfg.mode == 1   -> cfg.mode == "A"     (letters, per spec 5.4)
#   cfg.mode == 2   -> cfg.mode != "A"     (B and C both screen the union; C is
#                                           a post-filter on the same
#                                           computation, not a third screen)
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

import pandas as pd

from .ema import ema_pine

__all__ = ["macd_pine"]


def macd_pine(close: Any, fast: int = 12, slow: int = 26, signal: int = 9,
              seed: Optional[str] = None) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Pine `[macdLine, signalLine, histLine] = ta.macd(src, fast, slow, sig)`.

    Returned in Pine's order: (macd, signal, hist). hist = macd - signal.
    Both panes of the template use 12 / 26 / 9 on close, and the Top script's
    score reads `macdHist` from exactly this call.
    """
    macd = ema_pine(close, fast, seed) - ema_pine(close, slow, seed)
    macd = macd.rename("macd")
    sig = ema_pine(macd, signal, seed).rename("macd_signal")
    hist = (macd - sig).rename("macd_hist")
    return macd, sig, hist
