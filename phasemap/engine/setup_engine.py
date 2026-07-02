"""SetupEngine — one instance per (ticker, direction). Implements Modules 1-5
and the state machine (spec Section 5), processing daily bars strictly in
order with zero lookahead.

States: NEUTRAL -> TRAP_SET -> SWEPT -> DISPLACED -> RUNNING -> COMPLETE
        SWEPT --(no displacement in window)--> NEUTRAL
        RUNNING --(momentum zone touched)--> STALLED (route to fib category)
        any active state --(close through hard floor)--> DEAD
DEAD and COMPLETE are terminal; the ticker re-enters at NEUTRAL next bar.

The bearish engine is the exact mirror (spec 3.6): sweep of prior HIGHS with a
close back below, displacement closes near the LOW, leg measured high->low,
SUPPLY zone instead of DEMAND, targets below.
"""

import math
from dataclasses import dataclass, field

from phasemap.config import CONFIG
from phasemap.engine.buffers import buffer
from phasemap.engine.indicators import IndicatorSet
from phasemap.engine.zones import Zone, cluster_levels, merge_targets

ACTIVE_STATES = ("TRAP_SET", "SWEPT", "DISPLACED", "RUNNING", "STALLED")


@dataclass
class SetupEngine:
    ind: IndicatorSet
    bull: bool

    state: str = "NEUTRAL"
    state_log: list = field(default_factory=list)   # (bar_index, state)

    # box / trap
    box_low: float = math.nan
    box_high: float = math.nan
    bars_in_box: int = 0
    trap_cluster: tuple = None      # (low, high, members) resting liquidity

    # sweep
    sweep_index: int = -1
    sweep_extreme: float = math.nan  # sweepLow (bull) / sweepHigh (bear)
    key_level: float = math.nan      # keyLow / keyHigh (or cluster edge)
    sweep_depth_pct: float = math.nan
    sweep_variant: str = ""          # "wick" | "equal_lows" | "equal_highs"
    sweep_buffer: float = math.nan
    reclaim_box: bool = False
    reclaim_mid: bool = False
    swept_below_anchor: dict = field(default_factory=dict)  # anchor -> reclaimed?
    cooldown_until: int = -1
    prev_sweep_extreme: float = math.nan   # survives resets — cooldown baseline

    # displacement / leg
    displacement_index: int = -1
    last_dq_index: int = -1          # most recent displacement-quality bar
    leg_extreme: float = math.nan    # running legHigh (bull) / legLow (bear)
    displacement_flags: list = field(default_factory=list)
    flip_tag: str = ""               # FAST_FLIP | SLOW_FLIP | ""

    # zones
    demand: Zone = None              # DEMAND (bull) / SUPPLY (bear)
    inv_hard: Zone = None
    inv_soft: Zone = None            # INVALIDATION_MOMENTUM — dynamic band
    entry: Zone = None               # ENTRY_CONTINUATION — dynamic band
    targets: list = field(default_factory=list)
    momentum_touched: bool = False

    # bookkeeping
    stalled_index: int = -1
    terminal_index: int = -1
    route_to: str = None
    anchor_context: bool = False
    anchor_caution: bool = False
    last_sweep_period: tuple = None  # (year, quarter) a sweep printed in

    # ------------------------------------------------------------------ helpers
    def _set_state(self, i: int, state: str) -> None:
        if state != self.state:
            self.state = state
            self.state_log.append((i, state))

    def _buffer(self, i: int) -> float:
        a = self.ind.atr20[i]
        return buffer(float(self.ind.close[i]), 0.0 if math.isnan(a) else float(a))

    def _leg(self) -> float:
        return abs(self.leg_extreme - self.sweep_extreme)

    def _fifty(self) -> float:
        if self.bull:
            return self.leg_extreme - 0.5 * self._leg()
        return self.leg_extreme + 0.5 * self._leg()

    def _max_depth(self, price: float) -> float:
        if price >= CONFIG.sweep_depth_price_split:
            return CONFIG.sweep_max_depth_pct
        return CONFIG.sweep_max_depth_pct_sub1

    def _anchors_at(self, i: int) -> dict:
        ind = self.ind
        out = {}
        for name, arr in (("yearly_open", ind.yearly_open),
                          ("quarterly_open", ind.quarterly_open),
                          ("monthly_open", ind.monthly_open),
                          ("prior_yearly_close", ind.prior_yearly_close)):
            v = arr[i]
            if not math.isnan(v):
                out[name] = float(v)
        return out

    # ---------------------------------------------------------------- main loop
    def process(self) -> None:
        for i in range(len(self.ind.close)):
            self.on_bar(i)

    def on_bar(self, i: int) -> None:
        ind = self.ind
        # terminal states reset to NEUTRAL on the NEXT bar (re-entry)
        if self.state in ("DEAD", "COMPLETE") and i > self.terminal_index:
            self._reset(i)
        # DISPLACED is the day-of state; it becomes RUNNING from the next bar
        if self.state == "DISPLACED" and i > self.displacement_index:
            self._set_state(i, "RUNNING")

        warm = max(CONFIG.box_lookback + 1, CONFIG.atr_period)
        if i < warm or math.isnan(ind.atr20[i]):
            return

        o, h, l, c = (float(ind.open[i]), float(ind.high[i]),
                      float(ind.low[i]), float(ind.close[i]))

        if self.state in ("NEUTRAL", "TRAP_SET"):
            self._module1_consolidation(i)
            self._module2_sweep(i, o, h, l, c)
            self._anchor_caution(i, c)
        elif self.state == "SWEPT":
            # keep the expansion high-water mark honest while awaiting displacement
            if self.bull:
                self.leg_extreme = max(self.leg_extreme, h)
            else:
                self.leg_extreme = min(self.leg_extreme, l)
            self._update_static_zones(i, o, h, l, c)
            if self._dead_check(i, c):
                return
            if not self._module3_displacement(i, o, h, l, c):
                if i - self.sweep_index >= CONFIG.displacement_window_bars:
                    self._reset(i)   # sweep expired — no displacement, no setup
        elif self.state in ("DISPLACED", "RUNNING", "STALLED"):
            self._module4_run(i, o, h, l, c)

    # -------------------------------------------------------------- Module 1
    def _module1_consolidation(self, i: int) -> None:
        ind = self.ind
        if ind.compressed[i]:
            self.box_low = float(ind.box_low[i])
            self.box_high = float(ind.box_high[i])
            self.bars_in_box = self.bars_in_box + 1 if self.state == "TRAP_SET" else 1
            self.trap_cluster = self._resting_cluster(i)
            self._set_state(i, "TRAP_SET")
        elif self.state == "TRAP_SET":
            self._set_state(i, "NEUTRAL")
            self.bars_in_box = 0
            self.trap_cluster = None

    def _resting_cluster(self, i: int):
        """Equal-lows (bull) / equal-highs (bear) cluster resting at/beyond the
        shelf — the pre-alert liquidity pool for the Watch tier."""
        buf = self._buffer(i)
        swings = self.ind.swing_lows if self.bull else self.ind.swing_highs
        lo_bar = i - CONFIG.sweep_lookback
        levels = [s.price for s in swings if s.confirm <= i and s.index >= lo_bar]
        shelf = self.box_low if self.bull else self.box_high
        best = None
        for lo, hi, n in cluster_levels(levels, buf):
            if n < CONFIG.cluster_min_members:
                continue
            near_shelf = (hi <= shelf + buf) if self.bull else (lo >= shelf - buf)
            if near_shelf:
                best = (lo, hi, n)
        return best

    # -------------------------------------------------------------- Module 2
    def _module2_sweep(self, i: int, o, h, l, c) -> None:
        ind = self.ind
        key = float(ind.key_low[i]) if self.bull else float(ind.key_high[i])
        if math.isnan(key):
            return
        buf = self._buffer(i)

        swept, extreme, key_level, variant = False, math.nan, math.nan, ""
        if self.bull:
            if l < key and c > key:
                swept, extreme, key_level, variant = True, l, key, "wick"
        else:
            if h > key and c < key:
                swept, extreme, key_level, variant = True, h, key, "wick"

        if not swept:
            # equal-lows / equal-highs cluster variant (illiquid double taps)
            swings = ind.swing_lows if self.bull else ind.swing_highs
            lo_bar = i - CONFIG.sweep_lookback
            levels = [s.price for s in swings if s.confirm <= i and s.index >= lo_bar]
            for clo, chi, n in cluster_levels(levels, buf):
                if n < CONFIG.cluster_min_members:
                    continue
                if self.bull and l <= clo and c > chi:
                    swept, extreme, key_level = True, l, chi
                    variant = "equal_lows"
                elif not self.bull and h >= chi and c < clo:
                    swept, extreme, key_level = True, h, clo
                    variant = "equal_highs"
        if not swept:
            return

        # re-detection cooldown after an expired sweep — only a DEEPER
        # manipulation (a genuinely new extreme) may override it
        if i <= self.cooldown_until and not math.isnan(self.prev_sweep_extreme):
            deeper = extreme < self.prev_sweep_extreme if self.bull \
                else extreme > self.prev_sweep_extreme
            if not deeper:
                return

        depth = (abs(key_level - extreme)) / key_level
        if depth > self._max_depth(c):
            return   # breakdown/blow-off, not a sweep — reject

        # the 40-bar box is always defined, even when the sweep fires without
        # a prior TRAP_SET (compression is not a precondition for a sweep)
        if math.isnan(self.box_low):
            self.box_low = float(ind.box_low[i])
            self.box_high = float(ind.box_high[i])

        d = self.ind.dates[i]
        self.sweep_index = i
        self.sweep_extreme = extreme
        self.prev_sweep_extreme = extreme
        self.key_level = key_level
        self.sweep_depth_pct = depth
        self.sweep_variant = variant
        self.sweep_buffer = buf
        self.cooldown_until = i + CONFIG.sweep_active_bars
        self.leg_extreme = h if self.bull else l
        self.last_sweep_period = (d.year, (d.month - 1) // 3)
        if self.bull:
            self.reclaim_box = c > self.box_low if not math.isnan(self.box_low) else False
            mid = (self.box_low + self.box_high) / 2 if not math.isnan(self.box_low) else math.nan
            self.reclaim_mid = c > mid if not math.isnan(mid) else False
        else:
            self.reclaim_box = c < self.box_high if not math.isnan(self.box_high) else False
            mid = (self.box_low + self.box_high) / 2 if not math.isnan(self.box_low) else math.nan
            self.reclaim_mid = c < mid if not math.isnan(mid) else False

        # anchors the manipulation printed beyond (Module 5 context)
        self.swept_below_anchor = {}
        for name, v in self._anchors_at(i).items():
            if name == "monthly_open":
                continue
            beyond = extreme < v if self.bull else extreme > v
            if beyond:
                self.swept_below_anchor[name] = (c > v) if self.bull else (c < v)

        created = d.isoformat()
        if self.bull:
            self.demand = Zone(id="demand", type="DEMAND", low=extreme,
                               high=key_level, side="below",
                               sources=["sweep_wick"], created_date=created)
            self.inv_hard = Zone(id="inv_hard", type="INVALIDATION_HARD",
                                 low=extreme - buf, high=extreme, side="below",
                                 rule="close_below_low", created_date=created)
        else:
            self.demand = Zone(id="supply", type="SUPPLY", low=key_level,
                               high=extreme, side="above",
                               sources=["sweep_wick"], created_date=created)
            self.inv_hard = Zone(id="inv_hard", type="INVALIDATION_HARD",
                                 low=extreme, high=extreme + buf, side="above",
                                 rule="close_above_high", created_date=created)
        # demand/supply confluence with anchor levels sitting inside the band
        for name, v in self._anchors_at(i).items():
            if self.demand.low <= v <= self.demand.high:
                self.demand.sources.append(name)
        self.demand.confluence = len(self.demand.sources)

        self._set_state(i, "SWEPT")
        # the sweep bar itself may be its own displacement bar (V-flip)
        self._module3_displacement(i, o, h, l, c)

    # -------------------------------------------------------------- Module 3
    def _dq_bar(self, i: int, o, h, l, c) -> bool:
        """Displacement-quality bar test (used day-of and for regime upkeep)."""
        rng = h - l
        atr = float(self.ind.atr20[i])
        if rng <= 0 or math.isnan(atr) or atr <= 0:
            return False
        if float(self.ind.tr[i]) < CONFIG.displacement_tr_mult * atr:
            return False
        if self.bull:
            close_pos = (c - l) / rng
            wick = (min(o, c) - l) / rng
        else:
            close_pos = (h - c) / rng
            wick = (h - max(o, c)) / rng
        return close_pos >= CONFIG.displacement_close_pos and \
            wick <= CONFIG.displacement_wick_max

    def _module3_displacement(self, i: int, o, h, l, c) -> bool:
        if not self._dq_bar(i, o, h, l, c):
            return False
        self.displacement_index = i
        self.last_dq_index = i
        self.leg_extreme = max(self.leg_extreme, h) if self.bull else min(self.leg_extreme, l)

        flags = []
        if self.bull and not math.isnan(self.box_low) and c > self.box_low:
            flags.append("close_above_box_low")
        if not self.bull and not math.isnan(self.box_high) and c < self.box_high:
            flags.append("close_below_box_high")
        if i > 0:
            gap_go = o > float(self.ind.close[i - 1]) if self.bull \
                else o < float(self.ind.close[i - 1])
            if gap_go:
                flags.append("gap_and_go")
        self.displacement_flags = flags

        # weekly fast-flip: which weekday did the manipulation extreme print on
        wd = self.ind.dates[self.sweep_index].isoweekday()
        if wd in CONFIG.fast_flip_days:
            self.flip_tag = "FAST_FLIP"
        elif wd in CONFIG.slow_flip_days:
            self.flip_tag = "SLOW_FLIP"

        self._build_targets(i, c)
        self._refresh_dynamic_zones(i)
        self._set_state(i, "DISPLACED")
        return True

    # ---------------------------------------------------------- target zones
    def _build_targets(self, i: int, close: float) -> None:
        buf = self._buffer(i)
        created = self.ind.dates[i].isoformat()
        half = 0.5 * buf
        cands = []   # (low, high, source)

        def beyond(level):   # target must sit in the expansion direction
            return level > close if self.bull else level < close

        box_edge = self.box_high if self.bull else self.box_low
        if not math.isnan(box_edge) and beyond(box_edge):
            cands.append((box_edge - half, box_edge + half,
                          "box_high" if self.bull else "box_low"))

        # equal / prior highs (bull) or lows (bear) clusters
        swings = self.ind.swing_highs if self.bull else self.ind.swing_lows
        lo_bar = i - CONFIG.target_swing_lookback
        levels = [s.price for s in swings
                  if s.confirm <= i and s.index >= lo_bar and beyond(s.price)]
        for clo, chi, n in cluster_levels(levels, buf):
            src = ("equal_highs" if self.bull else "equal_lows") if n >= 2 else \
                ("prior_high" if self.bull else "prior_low")
            cands.append((clo - half, chi + half, src))

        # anchor bands (padded +/- one FULL buffer per spec 3.2)
        for name, v in self._anchors_at(i).items():
            if name == "monthly_open":
                continue
            if beyond(v):
                cands.append((v - buf, v + buf, name))

        # fib extension bands of the manipulation -> expansion leg
        leg = self._leg()
        if leg > 0:
            for lo_m, hi_m in CONFIG.fib_ext_bands:
                if self.bull:
                    b_lo = self.sweep_extreme + lo_m * leg
                    b_hi = self.sweep_extreme + hi_m * leg
                else:
                    b_hi = self.sweep_extreme - lo_m * leg
                    b_lo = self.sweep_extreme - hi_m * leg
                edge = b_hi if self.bull else b_lo
                if beyond(edge):
                    tag = f"fib_ext_{str(lo_m).replace('.', '')}"
                    cands.append((b_lo - half, b_hi + half, tag))

        zones = [Zone(id="t", type="TARGET", low=lo, high=hi,
                      side="above" if self.bull else "below",
                      sources=[src], created_date=created)
                 for lo, hi, src in cands]
        merged = merge_targets(zones)
        # nearest objective first: ascending for bull, descending for bear
        merged.sort(key=lambda z: z.low if self.bull else -z.high)
        merged = merged[:CONFIG.max_targets]
        for n, z in enumerate(merged, start=1):
            z.id = f"t{n}"
        self.targets = merged

    def _refresh_dynamic_zones(self, i: int) -> None:
        """INVALIDATION_MOMENTUM and ENTRY_CONTINUATION move with legHigh/legLow."""
        buf = self._buffer(i)
        fifty = self._fifty()
        created = self.ind.dates[self.displacement_index].isoformat()
        leg = self._leg()
        lo_r, hi_r = CONFIG.entry_retrace_band
        keep_status = (self.inv_soft.status, self.inv_soft._touched) if self.inv_soft else None
        if self.bull:
            self.inv_soft = Zone(id="inv_soft", type="INVALIDATION_MOMENTUM",
                                 low=fifty - 0.5 * buf, high=fifty, side="below",
                                 rule="touch", created_date=created)
            self.entry = Zone(id="entry", type="ENTRY_CONTINUATION",
                              low=self.leg_extreme - hi_r * leg,
                              high=self.leg_extreme - lo_r * leg,
                              side="below", created_date=created)
        else:
            self.inv_soft = Zone(id="inv_soft", type="INVALIDATION_MOMENTUM",
                                 low=fifty, high=fifty + 0.5 * buf, side="above",
                                 rule="touch", created_date=created)
            self.entry = Zone(id="entry", type="ENTRY_CONTINUATION",
                              low=self.leg_extreme + lo_r * leg,
                              high=self.leg_extreme + hi_r * leg,
                              side="above", created_date=created)
        if keep_status:
            self.inv_soft.status, self.inv_soft._touched = keep_status

    # -------------------------------------------------------------- Module 4
    def _module4_run(self, i: int, o, h, l, c) -> None:
        # extend the expansion leg's high-water mark first, then re-anchor zones
        if self.bull:
            self.leg_extreme = max(self.leg_extreme, h)
        else:
            self.leg_extreme = min(self.leg_extreme, l)
        self._refresh_dynamic_zones(i)
        self._update_static_zones(i, o, h, l, c)
        for z in self.targets:
            z.update(o, h, l, c)

        if self._dq_bar(i, o, h, l, c):
            self.last_dq_index = i

        # hard structural kill overrides everything else this bar
        if self._dead_check(i, c):
            if self.state == "RUNNING" and self.inv_soft.touches(h, l):
                self.inv_soft.status = "VIOLATED"
                self.momentum_touched = True
            return

        if self.state == "RUNNING" and not self.momentum_touched \
                and self.inv_soft.touches(h, l):
            self.inv_soft.status = "VIOLATED"
            self.momentum_touched = True
            self.stalled_index = i
            self.route_to = "fib_reversal"
            self._set_state(i, "STALLED")
            return

        if self.state == "STALLED":
            if i - self.stalled_index >= CONFIG.stalled_expiry_bars:
                self._reset(i)
            return

        # anchor context: manipulation printed beyond an anchor, since reclaimed
        for name, reclaimed in list(self.swept_below_anchor.items()):
            if not reclaimed:
                v = self._anchors_at(i).get(name)
                if v is not None and ((c > v) if self.bull else (c < v)):
                    self.swept_below_anchor[name] = True
        self.anchor_context = any(
            self.swept_below_anchor.get(k) for k in ("yearly_open", "quarterly_open"))

        # COMPLETE: final target consumed (daily close through its far edge)
        if self.targets and all(z.status == "CONSUMED" for z in self.targets):
            self.terminal_index = i
            self._set_state(i, "COMPLETE")

    def _update_static_zones(self, i: int, o, h, l, c) -> None:
        for z in (self.demand, self.inv_hard):
            if z is not None:
                z.update(o, h, l, c)

    def _dead_check(self, i: int, c: float) -> bool:
        """Structural kill: daily CLOSE through the hard zone's outer floor.
        Wicks through are a test only."""
        if self.inv_hard is None:
            return False
        killed = c < self.inv_hard.low if self.bull else c > self.inv_hard.high
        if killed:
            self.inv_hard.status = "VIOLATED"
            self.terminal_index = i
            self._set_state(i, "DEAD")
        return killed

    def _anchor_caution(self, i: int, c: float) -> None:
        """Approaching an anchor with no manipulation leg yet this period."""
        d = self.ind.dates[i]
        period = (d.year, (d.month - 1) // 3)
        if self.last_sweep_period == period:
            self.anchor_caution = False
            return
        buf = self._buffer(i)
        caution = False
        for name, v in self._anchors_at(i).items():
            if name == "prior_yearly_close":
                continue
            gap = (v - c) if self.bull else (c - v)
            if 0 < gap <= buf:
                caution = True
        self.anchor_caution = caution

    # ---------------------------------------------------------------- lifecycle
    def _reset(self, i: int) -> None:
        self._set_state(i, "NEUTRAL")
        self.bars_in_box = 0
        self.trap_cluster = None
        self.sweep_index = -1
        self.sweep_extreme = math.nan
        self.key_level = math.nan
        self.sweep_variant = ""
        self.displacement_index = -1
        self.last_dq_index = -1
        self.leg_extreme = math.nan
        self.displacement_flags = []
        self.flip_tag = ""
        self.demand = None
        self.inv_hard = None
        self.inv_soft = None
        self.entry = None
        self.targets = []
        self.momentum_touched = False
        self.stalled_index = -1
        self.route_to = None
        self.anchor_context = False
        self.swept_below_anchor = {}

    # ---------------------------------------------------------------- metrics
    def retrace_pct(self, i: int) -> float:
        leg = self._leg()
        if math.isnan(leg) or leg <= 0 or math.isnan(self.leg_extreme):
            return math.nan
        c = float(self.ind.close[i])
        if self.bull:
            return (self.leg_extreme - c) / leg
        return (c - self.leg_extreme) / leg

    def regime(self, i: int) -> str:
        if self.displacement_index < 0:
            return "ROTATION"
        recent = (i - self.last_dq_index) <= CONFIG.regime_displacement_lookback
        return "EXPANSION" if recent and not self.momentum_touched else "ROTATION"
