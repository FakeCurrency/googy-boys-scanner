"""Zone system (spec Section 3). Every actionable level is a band.

Zone lifecycle: UNTESTED -> TESTED (any wick touch) -> RESPECTED (touch +
close back away in >=1 bar) -> CONSUMED (targets: daily close beyond the far
edge) or VIOLATED (invalidations). Zones never resurrect once
CONSUMED/VIOLATED.

`side` records where the zone sits relative to the approach:
  "below" — price approaches from above (bull demand/invalidations, bear targets)
  "above" — price approaches from below (bull targets, bear supply/invalidations)
"""

from dataclasses import dataclass, field

from phasemap.config import CONFIG


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
        nd = CONFIG.price_decimals
        d = {
            "id": self.id,
            "type": self.type,
            "low": round(self.low, nd),
            "high": round(self.high, nd),
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
