"""REFINE200 #97 -- the VIVEK resamples, made cheaper and proven unchanged.

Two speed-ups, both required to be BIT-IDENTICAL (a plan sets real stops):

1. Each OHLCV resample is one `.agg` pass instead of five per-column
   resamples (W-FRI 37ms -> 8ms on a 5-year frame -- most of build_plans).
2. `evaluate()` hands its 3-Day frame to `build_plans()` for the same frame
   instead of both building it.

The old resamplers are FROZEN below, copied from the pre-#97 vivek.py, and
the new code is compared against them -- comparing the new code with itself
would prove nothing.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

import scanner.vivek as vivek
from scanner import config, scan


# ── frozen pre-#97 implementations ───────────────────────────────────────────

def old_weekly(df):
    try:
        wk = pd.DataFrame({
            "Open":   df["Open"].resample("W-FRI").first(),
            "High":   df["High"].resample("W-FRI").max(),
            "Low":    df["Low"].resample("W-FRI").min(),
            "Close":  df["Close"].resample("W-FRI").last(),
            "Volume": df["Volume"].resample("W-FRI").sum(),
        }).dropna()
        return wk if len(wk) else None
    except Exception:
        return None


def old_3day(df):
    try:
        d3 = pd.DataFrame({
            "Open":   df["Open"].resample("72h", origin="epoch").first(),
            "High":   df["High"].resample("72h", origin="epoch").max(),
            "Low":    df["Low"].resample("72h", origin="epoch").min(),
            "Close":  df["Close"].resample("72h", origin="epoch").last(),
            "Volume": df["Volume"].resample("72h", origin="epoch").sum(),
        }).dropna()
        return d3 if len(d3) else None
    except Exception:
        return None


def old_4h(df):
    try:
        h4 = pd.DataFrame({
            "Open":   df["Open"].resample("4h").first(),
            "High":   df["High"].resample("4h").max(),
            "Low":    df["Low"].resample("4h").min(),
            "Close":  df["Close"].resample("4h").last(),
            "Volume": df["Volume"].resample("4h").sum(),
        }).dropna()
        return h4 if len(h4) else None
    except Exception:
        return None


# ── fixture frames ───────────────────────────────────────────────────────────

def walk(n, seed, freq="B", int_vol=False, start="2020-01-01", drift=0.0003):
    rng = np.random.default_rng(seed)
    c = 50 * np.exp(np.cumsum(rng.normal(drift, 0.02, n)))
    o = c * (1 + rng.normal(0, 0.005, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.01, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.01, n)))
    v = rng.integers(10_000, 1_000_000, n)
    idx = pd.date_range(start, periods=n, freq=freq)
    return pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c,
                         "Volume": v if int_vol else v.astype(float)}, index=idx)


def holey(df, seed):
    """NaNs in single columns, a whole NaN row, and a missing fortnight."""
    rng = np.random.default_rng(seed)
    df = df.copy()
    for col in ("Open", "High", "Low", "Close", "Volume"):
        df.loc[df.index[rng.integers(0, len(df), 6)], col] = np.nan
    df.iloc[len(df) // 3] = np.nan
    return df.drop(df.index[len(df) // 2: len(df) // 2 + 10])


FRAMES = {
    "daily_float": walk(1300, 1),
    "daily_int_volume": walk(1300, 2, int_vol=True),
    "daily_holey": holey(walk(1300, 3), 3),
    "daily_7day_crypto": walk(1800, 4, freq="D"),
    "daily_short": walk(5, 5),
    "daily_one": walk(1, 6),
    "daily_empty": walk(3, 7).iloc[:0],
    "daily_all_nan_close": walk(40, 8).assign(Close=np.nan),
}
HOURLY = {
    "hourly": walk(2000, 9, freq="h"),
    "hourly_holey": holey(walk(2000, 10, freq="h"), 10),
}


@pytest.mark.parametrize("name", sorted(FRAMES))
def test_weekly_and_3day_are_bit_identical_to_the_five_pass_versions(name):
    df = FRAMES[name]
    for old, new in ((old_weekly, vivek._resample_weekly_ohlc),
                     (old_3day, vivek._resample_3day_ohlc)):
        a, b = old(df), new(df)
        if a is None:
            assert b is None
        else:
            pd.testing.assert_frame_equal(a, b, check_exact=True, check_freq=True)


@pytest.mark.parametrize("name", sorted(HOURLY))
def test_4h_is_bit_identical_to_the_five_pass_version(name):
    a, b = old_4h(HOURLY[name]), vivek._resample_4h_ohlc(HOURLY[name])
    pd.testing.assert_frame_equal(a, b, check_exact=True, check_freq=True)


def test_a_frame_missing_a_column_still_degrades_to_none():
    df = walk(100, 11).drop(columns=["Volume"])
    assert old_weekly(df) is None and vivek._resample_weekly_ohlc(df) is None
    assert old_3day(df) is None and vivek._resample_3day_ohlc(df) is None


# ── the plans and the scan payload, before and after ─────────────────────────

def _old_engine(monkeypatch):
    real_build = vivek.build_plans
    monkeypatch.setattr(vivek, "_resample_weekly_ohlc", old_weekly)
    monkeypatch.setattr(vivek, "_resample_3day_ohlc", old_3day)
    monkeypatch.setattr(vivek, "build_plans",
                        lambda df, sig, resampled=None: real_build(df, sig))


@pytest.mark.parametrize("name", ["daily_float", "daily_int_volume", "daily_holey",
                                  "daily_7day_crypto"])
@pytest.mark.parametrize("direction", ["long", "short"])
def test_build_plans_output_is_unchanged(name, direction, monkeypatch):
    df = FRAMES[name].dropna()
    rs: dict = {}
    vivek.evaluate(df, resampled=rs)
    new = json.dumps(vivek.build_plans(df, {"direction": direction}, resampled=rs),
                     sort_keys=True)
    with monkeypatch.context() as m:
        _old_engine(m)
        old = json.dumps(vivek.build_plans(df, {"direction": direction}), sort_keys=True)
    assert new == old


def _universe(n):
    frames, uni = {}, []
    for i in range(n):
        f = walk(1300, 100 + i, drift=0.0006 if i % 2 else -0.0002)
        f.index = pd.bdate_range(end="2026-10-09", periods=len(f))
        t = f"T{i}.AX"
        frames[t] = f
        uni.append({"yf": t, "symbol": f"T{i}", "name": f"T{i}", "sector": "Materials"})
    return frames, uni


def test_a_whole_scan_payload_is_byte_identical(monkeypatch):
    """60 random-walk names through the REAL engine: the published rows (grades,
    plans, every number) with the #97 code against the frozen five-pass code
    and no 3-Day hand-off."""
    monkeypatch.setattr(config, "VIVEK_H4_PLANS", False)
    frames, uni = _universe(60)

    def run():
        out = scan.scan_vivek_market("asx", universe=uni, frames=frames,
                                     pulse_data=[], progress=False)
        out = scan.published(out, "asx", caps={}, sectors={})
        for k in ("generated_at", "code_sha"):
            out.pop(k, None)
        return json.dumps(out, sort_keys=True, default=str)

    new = run()
    with monkeypatch.context() as m:
        _old_engine(m)
        old = run()
    assert json.loads(new)["results"], "the fixture must produce setups to compare"
    assert new == old


def test_the_scan_builds_each_3day_frame_once(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_H4_PLANS", False)
    frames, uni = _universe(30)
    calls = {"n": 0}
    real = vivek._resample_3day_ohlc

    def counting(df):
        calls["n"] += 1
        return real(df)
    monkeypatch.setattr(vivek, "_resample_3day_ohlc", counting)
    out = scan.scan_vivek_market("asx", universe=uni, frames=frames,
                                 pulse_data=[], progress=False)
    assert out["results"], "need setups for build_plans to run"
    assert calls["n"] == len(frames), "one 3-Day resample per name, not two per setup"
