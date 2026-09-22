"""Produce a hand-checkable worked example of the RSI divergence timing.

Builds a tiny RSI series by hand (not from price) so the pivot arithmetic is
inspectable, then runs the exact Pine logic and prints a bar-by-bar table.
"""
import numpy as np
import pandas as pd

L, R = 5, 5
RANGE_MIN, RANGE_MAX = 5, 60

# A hand-built RSI series with two troughs: a deeper one at bar 8, a shallower
# (higher) one at bar 26. Price will make a LOWER low at the second trough.
rsi = np.array([
    52, 48, 44, 40, 36, 33, 31, 29, 27, 30,   # 0-9   trough (27) at bar 8
    34, 39, 44, 48, 52, 55, 57, 54, 50, 46,   # 10-19
    42, 39, 36, 34, 32, 31, 30, 33, 37, 42,   # 20-29 trough (30) at bar 26
    47, 51, 54, 56, 58, 57, 55, 52, 49, 47,   # 30-39
], dtype=float)

# Price: lower low at the second trough (95 < 100) => bullish divergence setup
low = np.array([
    120, 116, 112, 108, 104, 102, 101, 100.5, 100, 102,
    105, 109, 113, 117, 121, 124, 126, 123, 119, 115,
    111, 108, 105, 102,  99,  97,  95,  98, 102, 107,
    112, 116, 119, 121, 123, 122, 120, 117, 114, 112,
], dtype=float)

s = pd.Series(rsi)
lo = pd.Series(low)

# --- Pine ta.pivotlow(rsi, L, R): non-NaN on bar i when bar i-R is a pivot low.
# A bar k is a pivot low when s[k] is STRICTLY less than all L bars before it
# AND strictly less than all R bars after it. Strict on both sides: a tie kills
# the pivot, so a flat region produces none. (Verified in Part 4.)
def pivot_low_confirmed(s, L, R):
    n = len(s)
    out = pd.Series(np.nan, index=s.index, dtype=float)
    for k in range(L, n - R):
        w_left = s.iloc[k - L:k]
        w_right = s.iloc[k + 1:k + R + 1]
        if (s.iloc[k] < w_left).all() and (s.iloc[k] < w_right).all():
            out.iloc[k + R] = s.iloc[k]      # reported on the CONFIRMATION bar
    return out

piv = pivot_low_confirmed(s, L, R)
plFound = piv.notna()

conf_bars = list(plFound[plFound].index)
print("RSI pivot lows -> (pivot bar, confirmation bar, rsi at pivot, low at pivot)")
for i in conf_bars:
    print(f"   pivot bar {i-R:>3}   confirmed on bar {i:>3}   "
          f"rsi[{i-R}]={s.iloc[i-R]:>5.1f}   low[{i-R}]={lo.iloc[i-R]:>7.2f}")

print()
print("Divergence test on each confirmation bar after the first:")
prev = None
for i in conf_bars:
    if prev is None:
        print(f"   bar {i}: first pivot, no previous pivot to compare against -> no signal")
        prev = i
        continue
    rsi_now,  rsi_prev = s.iloc[i - R],  s.iloc[prev - R]
    low_now,  low_prev = lo.iloc[i - R], lo.iloc[prev - R]
    rsiHL   = rsi_now > rsi_prev
    priceLL = low_now < low_prev
    # Pine: ta.barssince(plFound[1]) on bar i, where the previous plFound was at `prev`
    barssince = i - (prev + 1)
    inRange = RANGE_MIN <= barssince <= RANGE_MAX
    fired = rsiHL and priceLL and inRange
    print(f"   bar {i}:")
    print(f"      rsiHL   : rsi[{i-R}]={rsi_now:.1f} > rsi[{prev-R}]={rsi_prev:.1f}  -> {rsiHL}")
    print(f"      priceLL : low[{i-R}]={low_now:.2f} < low[{prev-R}]={low_prev:.2f}  -> {priceLL}")
    print(f"      inRange : barssince(plFound[1]) = {i} - ({prev} + 1) = {barssince}, "
          f"need {RANGE_MIN}..{RANGE_MAX} -> {inRange}")
    print(f"      => bullDiv on bar {i}: {fired}"
          f"{'   (label DRAWN at bar ' + str(i - R) + ')' if fired else ''}")
    prev = i

print()
print("Bar table (the two pivots and the confirmation bars are marked):")
print(f"{'bar':>4} {'rsi':>6} {'low':>8}  {'note':<40}")
for i in range(len(s)):
    note = ""
    if i in (8, 26):
        note = "PIVOT LOW of RSI"
    if i in conf_bars:
        note = (note + "  " if note else "") + f"confirms pivot at bar {i-R}"
    if i == 31:
        note += "   <== bullDiv TRUE here"
    print(f"{i:>4} {s.iloc[i]:>6.1f} {lo.iloc[i]:>8.2f}  {note:<40}")
