"""Deterministic synthetic OHLCV builders for the M1 acceptance fixtures.

No randomness anywhere — every fixture is a hand-designed sequence with
known-correct expected outputs. Dates are consecutive weekdays starting on a
Monday, so bar i falls on ISO weekday (i % 5) + 1.
"""

import datetime

import pandas as pd

MONDAY = datetime.date(2024, 9, 23)   # anchor start — a Monday


def weekday_dates(n: int, start: datetime.date = MONDAY) -> list:
    out, d = [], start
    while len(out) < n:
        if d.isoweekday() <= 5:
            out.append(d)
        d += datetime.timedelta(days=1)
    return out


def bars_df(bars: list, start: datetime.date = MONDAY) -> pd.DataFrame:
    """bars: list of (open, high, low, close, volume) tuples."""
    dates = weekday_dates(len(bars), start)
    return pd.DataFrame(
        [(d, o, h, l, c, v) for d, (o, h, l, c, v) in zip(dates, bars)],
        columns=["Date", "Open", "High", "Low", "Close", "Volume"],
    )


def trend(n: int, start_price: float, step: float, rng: float,
          volume: float) -> list:
    """Steady drift with healthy bar ranges (the 'normal volatility' regime)."""
    bars, c_prev = [], start_price
    for _ in range(n):
        o = c_prev
        c = o + step
        h = max(o, c) + rng
        l = min(o, c) - rng
        bars.append((o, h, l, c, volume))
        c_prev = c
    return bars


# One compression cycle: mid-price path inside the box. Lows print 0.01 below
# the mid, highs 0.01 above, so a cycle over these mids sweeps the box edges
# exactly once each — giving clean fractal swing lows/highs at the extremes.
BOX_MIDS = [0.97, 0.99, 1.01, 1.03, 1.01, 0.99, 0.975, 0.98]


def box(n: int, volume: float, scale: float = 1.0, mids=None) -> list:
    """Tight oscillating range: box extremes = [min(mids)-0.01, max(mids)+0.01]."""
    mids = mids or BOX_MIDS
    bars = []
    for i in range(n):
        m = mids[i % len(mids)] * scale
        o = m - 0.005 * scale
        c = m + 0.005 * scale
        h = m + 0.01 * scale
        l = m - 0.01 * scale
        bars.append((o, h, l, c, volume))
    return bars


def flat(n: int, price: float, rng: float, volume: float) -> list:
    return [(price, price + rng, price - rng, price, volume)] * n


# ---------------------------------------------------------------------------
# Fixture 1 skeleton (shared by fixtures 3-7 with different endings):
# 200 trend bars 0.70 -> ~1.00, then a 60-bar box 0.96-1.04. Bar 260 (a
# Monday) is the sweep bar; bar 261 the displacement candle.
# ---------------------------------------------------------------------------
VOL = 400_000.0

SWEEP_BAR = (0.98, 0.985, 0.945, 0.972, VOL)          # runs 0.96 lows, reclaims
DISPLACEMENT_BAR = (0.975, 1.038, 0.970, 1.032, VOL)  # 1.75x range, tiny wick
RUN_BARS = [
    (1.033, 1.045, 1.028, 1.042, VOL),
    (1.042, 1.055, 1.036, 1.050, VOL),
    (1.050, 1.065, 1.045, 1.060, VOL),
    (1.060, 1.076, 1.054, 1.072, VOL),   # closes through T1's far edge
    (1.072, 1.080, 1.065, 1.075, VOL),
]


def base_to_box() -> list:
    return trend(200, 0.70, 0.0015, 0.020, VOL) + box(60, VOL)


def fixture1() -> pd.DataFrame:
    """Clean sweep + displacement + run to T1."""
    return bars_df(base_to_box() + [SWEEP_BAR, DISPLACEMENT_BAR] + RUN_BARS)


def fixture2() -> pd.DataFrame:
    """Equal-lows double tap on a $0.05 stock (cluster sweep + ILLIQUID)."""
    vol = 500_000.0
    bars = trend(240, 0.060, -0.00003, 0.0008, vol)     # gentle drift ~0.053
    bars += flat(5, 0.0520, 0.0008, vol)                # 240-244
    bars.append((0.0510, 0.0512, 0.0480, 0.0490, vol))  # 245: swing low A 0.0480
    bars += flat(6, 0.0505, 0.0008, vol)                # 246-251
    bars.append((0.0505, 0.0507, 0.0485, 0.0495, vol))  # 252: swing low B 0.0485
    bars += flat(7, 0.0500, 0.0008, vol)                # 253-259
    bars.append((0.0500, 0.0502, 0.0480, 0.0495, vol))  # 260: taps 0.0480, reclaims
    bars += flat(2, 0.0495, 0.0008, vol)                # 261-262
    return bars_df(bars)


def fixture3() -> pd.DataFrame:
    """Sweep with no displacement inside the window -> revert to NEUTRAL."""
    return bars_df(base_to_box() + [SWEEP_BAR] + flat(7, 0.972, 0.007, VOL))


def fixture4() -> pd.DataFrame:
    """Sweep depth ~20% below keyLow -> breakdown rejection."""
    crash = (0.98, 0.985, 0.768, 0.970, VOL)   # 20% under the 0.96 shelf
    return bars_df(base_to_box() + [crash] + flat(2, 0.968, 0.007, VOL))


def fixture5() -> pd.DataFrame:
    """Valid run that then touches the 50% momentum zone -> STALLED."""
    pullback = [
        (1.033, 1.045, 1.028, 1.042, VOL),
        (1.035, 1.040, 1.005, 1.010, VOL),
        (1.008, 1.015, 0.990, 1.000, VOL),   # low 0.990 tags the 50% area
    ]
    return bars_df(base_to_box() + [SWEEP_BAR, DISPLACEMENT_BAR] + pullback)


def fixture6() -> pd.DataFrame:
    """Wick through the hard floor (test only), then a close below it (DEAD)."""
    ending = [
        (0.980, 0.985, 0.932, 0.975, VOL),   # wick through floor, closes back in
        (0.970, 0.975, 0.920, 0.925, VOL),   # daily close below the floor
    ]
    return bars_df(base_to_box() + [SWEEP_BAR, DISPLACEMENT_BAR] + ending)


def mirror_df(df: pd.DataFrame, pivot: float = 2.0) -> pd.DataFrame:
    """Exact price mirror: reflects every bar around `pivot` (spec 3.6)."""
    out = df.copy()
    out["Open"] = pivot - df["Open"]
    out["Close"] = pivot - df["Close"]
    out["High"] = pivot - df["Low"]
    out["Low"] = pivot - df["High"]
    return out


def fixture7() -> pd.DataFrame:
    """Full bearish mirror of fixture 1."""
    return mirror_df(fixture1())


def fixture8() -> pd.DataFrame:
    """Fib-extension + equal-highs + quarterly-open bands all overlapping ->
    one merged target zone with confluence 3.

    Dates run so that bar 200 opens a new quarter at 1.06; price then declines
    into a box, sweeps, and displaces back up toward that anchor.
    """
    vol = VOL
    bars = trend(200, 0.80, 0.0011, 0.018, vol)          # ends ~1.02
    decline = [
        (1.060, 1.062, 1.040, 1.045, vol),               # 200: quarterly open 1.06
        (1.045, 1.050, 1.030, 1.035, vol),               # 201
        (1.040, 1.055, 1.028, 1.032, vol),               # 202: swing high 1.055
        (1.030, 1.038, 1.015, 1.020, vol),               # 203
        (1.018, 1.025, 1.005, 1.010, vol),               # 204
        (1.012, 1.030, 1.000, 1.025, vol),               # 205
        (1.024, 1.048, 1.010, 1.015, vol),               # 206: swing high 1.048
        (1.014, 1.020, 1.000, 1.005, vol),               # 207
        (1.005, 1.012, 0.992, 0.998, vol),               # 208
        (0.998, 1.005, 0.985, 0.990, vol),               # 209
        (0.990, 0.998, 0.982, 0.988, vol),               # 210
    ]
    bars += decline
    bars += box(40, vol)                                  # 211-250: box 0.96-1.04
    bars.append(SWEEP_BAR)                                # 251
    bars.append(DISPLACEMENT_BAR)                         # 252
    bars += flat(2, 1.030, 0.006, vol)                    # 253-254
    return bars_df(bars, start=datetime.date(2024, 9, 23))


def fixture_complete() -> pd.DataFrame:
    """Fixture 1 extended until every target zone is consumed -> COMPLETE."""
    surge = [
        (1.076, 1.100, 1.070, 1.095, VOL),
        (1.096, 1.120, 1.090, 1.115, VOL),
        (1.116, 1.150, 1.110, 1.145, VOL),   # closes through the final far edge
    ]
    return bars_df(base_to_box() + [SWEEP_BAR, DISPLACEMENT_BAR] + RUN_BARS + surge)


def fixture_trap_only() -> pd.DataFrame:
    """Fixture 1 truncated before the sweep -> TRAP_SET pre-alert."""
    return bars_df(base_to_box())
