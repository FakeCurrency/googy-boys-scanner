"""Measure the per-day base rate of each screen rule on synthetic price series.

These are geometric random walks with a realistic daily volatility, NOT real
market data (the sandbox cannot reach a data provider). Real markets trend and
mean-revert, so real rates will differ - but the ORDER OF MAGNITUDE from a
random walk is the right sanity check for "did I implement the cross as an
event or as a state".
"""
import numpy as np
import pandas as pd

rng = np.random.default_rng(20260922)
N_SYMBOLS, N_BARS = 3000, 900
L = R = 5
RANGE_MIN, RANGE_MAX = 5, 60

def ema(s, span):
    return s.ewm(span=span, adjust=False).mean()

def rma(s, period):
    return s.ewm(alpha=1 / period, adjust=False).mean()

def rsi_w(close, period=14):
    d = close.diff()
    gain = rma(d.clip(lower=0), period)
    loss = rma((-d).clip(lower=0), period)
    rs = gain / loss
    out = 100 - 100 / (1 + rs)
    return out.mask((loss == 0) & (gain > 0), 100.0)

def pivots_confirmed(s, L, R, low_side=True):
    """Boolean Series, True on bar i when bar i-R was a pivot."""
    w = L + R + 1
    ext = s.rolling(w, center=True).min() if low_side else s.rolling(w, center=True).max()
    at_k = (s == ext)
    # strictness on the left, non-strict on the right (Pine's comparison)
    left_ok = s.rolling(L + 1).min().shift(0) if low_side else s.rolling(L + 1).max()
    return at_k.shift(R).fillna(False)

results = {"bull_div": 0, "bear_div": 0, "cross": 0,
           "score1": 0, "score2": 0, "score3": 0, "bars": 0}

for _ in range(N_SYMBOLS):
    vol = rng.uniform(0.012, 0.045)              # 1.2% - 4.5% daily sigma
    drift = rng.normal(0.0002, 0.0006)
    r = rng.normal(drift, vol, N_BARS)
    close = pd.Series(100 * np.exp(np.cumsum(r)))
    # crude OHLC around the close
    high = close * (1 + np.abs(rng.normal(0, vol / 2, N_BARS)))
    low = close * (1 - np.abs(rng.normal(0, vol / 2, N_BARS)))

    rsi = rsi_w(close)
    fast, mid, slow = ema(close, 20), ema(close, 50), ema(close, 200)
    macd = ema(close, 12) - ema(close, 26)
    hist = macd - ema(macd, 9)

    # --- Rule B: crosses and scores
    up = (fast > mid) & (fast.shift(1) <= mid.shift(1))
    dn = (fast < mid) & (fast.shift(1) >= mid.shift(1))
    valid = slow.notna() & (close.index >= 250)
    up, dn = up & valid, dn & valid
    bs = 1 + (hist > 0).astype(int) + (close > slow).astype(int)
    ss = 1 + (hist < 0).astype(int) + (close < slow).astype(int)
    for mask, sc in ((up, bs), (dn, ss)):
        v = sc[mask]
        results["cross"] += int(mask.sum())
        results["score1"] += int((v == 1).sum())
        results["score2"] += int((v == 2).sum())
        results["score3"] += int((v == 3).sum())

    # --- Rule A: divergences
    pl = pivots_confirmed(rsi, L, R, True)
    ph = pivots_confirmed(rsi, L, R, False)
    for found, price, rsi_cmp, price_cmp in (
            (pl, low, "gt", "lt"), (ph, high, "lt", "gt")):
        idx = list(found[found & valid].index)
        prev = None
        n = 0
        for i in idx:
            if prev is not None and i - R >= 0 and prev - R >= 0:
                rv, rp = rsi.iloc[i - R], rsi.iloc[prev - R]
                pv, pp = price.iloc[i - R], price.iloc[prev - R]
                ok_r = rv > rp if rsi_cmp == "gt" else rv < rp
                ok_p = pv < pp if price_cmp == "lt" else pv > pp
                gap = i - (prev + 1)
                if ok_r and ok_p and RANGE_MIN <= gap <= RANGE_MAX:
                    n += 1
            prev = i
        results["bull_div" if rsi_cmp == "gt" else "bear_div"] += n

    results["bars"] += int(valid.sum())

sym_days = results["bars"]
print(f"simulated {N_SYMBOLS} symbols x ~{N_BARS-250} usable bars = "
      f"{sym_days:,} symbol-days\n")

def pct(n):
    return 100.0 * n / sym_days

print(f"{'event':<28} {'count':>9} {'per symbol-day':>16} "
      f"{'expected in 2200 names/day':>28}")
for k, label in (("cross", "any 20/50 cross"),
                 ("score1", "  score 1 (excluded)"),
                 ("score2", "  score 2"),
                 ("score3", "  score 3"),
                 ("bull_div", "bullish RSI divergence"),
                 ("bear_div", "bearish RSI divergence")):
    n = results[k]
    print(f"{label:<28} {n:>9,} {pct(n):>15.3f}% {pct(n)/100*2200:>27.1f}")

rb = results["score2"] + results["score3"]
ra = results["bull_div"] + results["bear_div"]
print()
print(f"RULE A (either direction)  : {pct(ra):.3f}% of symbol-days "
      f"-> ~{pct(ra)/100*2200:.0f} of 2200 ASX names per day")
print(f"RULE B (score >= 2)        : {pct(rb):.3f}% of symbol-days "
      f"-> ~{pct(rb)/100*2200:.0f} of 2200 ASX names per day")
print(f"score mix among crosses    : 1={100*results['score1']/results['cross']:.0f}%  "
      f"2={100*results['score2']/results['cross']:.0f}%  "
      f"3={100*results['score3']/results['cross']:.0f}%")
print()
print("With a 3-bar freshness window, multiply the per-day figures by ~3 "
      "(events rarely repeat on a symbol within 3 bars).")
