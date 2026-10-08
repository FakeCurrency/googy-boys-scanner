"""Zone system (spec Section 3). Every actionable level is a band.

Zone lifecycle: UNTESTED -> TESTED (any wick touch) -> RESPECTED (touch +
close back away in >=1 bar) -> CONSUMED (targets: daily close beyond the far
edge) or VIOLATED (invalidations). Zones never resurrect once
CONSUMED/VIOLATED.

`side` records where the zone sits relative to the approach:
  "below" — price approaches from above (bull demand/invalidations, bear targets)
  "above" — price approaches from below (bull targets, bear supply/invalidations)
"""

import math
from dataclasses import dataclass, field

from phasemap.config import CONFIG

_MAX_PRICE_DECIMALS = 12   # the harness's precision; nothing finer is meaningful


def _price_decimals(x: float) -> int:
    """CONFIG.price_decimals, widened to CONFIG.price_sig_figs significant
    figures for small prices (audit #28). Unchanged at/above $0.10."""
    nd = CONFIG.price_decimals
    if x and math.isfinite(x):
        nd = max(nd, CONFIG.price_sig_figs - 1 - math.floor(math.log10(abs(x))))
    return min(nd, _MAX_PRICE_DECIMALS)


def price_round(x: float) -> float:
    """Round one published price (zone edge, close, box/cluster level)."""
    return round(x, _price_decimals(x))


def band_round(low: float, high: float) -> tuple:
    """Round a band's two edges for publishing. A band the engine built with
    width is never published as one price: when rounding would collapse it,
    both edges take more decimals until they differ (audit #26/#28)."""
    lo, hi = price_round(low), price_round(high)
    if low < high and lo >= hi:
        nd = max(_price_decimals(low), _price_decimals(high))
        while nd < _MAX_PRICE_DECIMALS and round(low, nd) >= round(high, nd):
            nd += 1
        lo, hi = round(low, nd), round(high, nd)
    return lo, hi


@dataclass
class Zone:
    id: str
    type: str                 # DEMAND | SUPPLY | INVALIDATION_HARD | INVALIDATION_MOMENTUM
    #                           | ENTRY_CONTINUATION | TARGET
    low: float
    high: float
    side: str                 # "below" | "above" (relative to price approach)
    rule: str = ""            # e.g. close_below_low, touch — the kill rule, if any
    status: str = "UNTESTED"  # UNTESTED | TESTED | RESPECTED | CONSUMED | VIOLATED
    confluence: int = 1
    sources: list = field(default_factory=list)
    created_date: str = ""
    _touched: bool = False

    def terminal(self) -> bool:
        return self.status in ("CONSUMED", "VIOLATED")

    def touches(self, bar_high: float, bar_low: float) -> bool:
        """Any wick overlap with the band."""
        return bar_low <= self.high and bar_high >= self.low

    def update(self, bar_open: float, bar_high: float, bar_low: float,
               bar_close: float) -> None:
        """Generic per-bar status update. Momentum-touch and hard-close kills
        are decided by the engine (they drive state transitions); this method
        handles the shared touch/respect/consume ladder."""
        if self.terminal():
            return
        if self.touches(bar_high, bar_low):
            self._touched = True
            if self.status == "UNTESTED":
                self.status = "TESTED"
        # consumed: daily close beyond the FAR edge (targets only)
        if self.type == "TARGET" and self._touched:
            if self.side == "above" and bar_close > self.high:
                self.status = "CONSUMED"
                return
            if self.side == "below" and bar_close < self.low:
                self.status = "CONSUMED"
                return
        # respected: has been touched and price closed back away from the band
        if self._touched and self.status in ("TESTED", "RESPECTED"):
            if self.side == "below" and bar_close > self.high:
                self.status = "RESPECTED"
            elif self.side == "above" and bar_close < self.low:
                self.status = "RESPECTED"

    def to_dict(self) -> dict:
        low, high = band_round(self.low, self.high)
        d = {
            "id": self.id,
            "type": self.type,
            "low": low,
            "high": high,
            "status": self.status,
        }
        if self.confluence > 1 or self.sources:
            d["confluence"] = self.confluence
            d["sources"] = list(self.sources)
        if self.rule:
            d["rule"] = self.rule
        d["created_date"] = self.created_date
        return d


def cluster_levels(levels: list, tol: float) -> list:
    """Group price levels within `tol` of each other (chained on sorted order).
    Returns list of (min, max, count) tuples, deterministic."""
    if not levels:
        return []
    vals = sorted(levels)
    clusters = []
    lo = hi = vals[0]
    count = 1
    for v in vals[1:]:
        if v - hi <= tol:
            hi = v
            count += 1
        else:
            clusters.append((lo, hi, count))
            lo = hi = v
            count = 1
    clusters.append((lo, hi, count))
    return clusters


def merge_targets(zones: list) -> list:
    """Confluence merging (spec 3.3): overlapping TARGET bands merge into one
    zone — band = union, confluence = number of source bands, sources = all."""
    if not zones:
        return []
    zs = sorted(zones, key=lambda z: (z.low, z.high))
    merged = [zs[0]]
    for z in zs[1:]:
        last = merged[-1]
        if z.low <= last.high:   # overlap (touching counts)
            last.high = max(last.high, z.high)
            last.low = min(last.low, z.low)
            last.sources = last.sources + [s for s in z.sources
                                           if s not in last.sources]
            last.confluence = len(last.sources)
        else:
            merged.append(z)
    return merged
