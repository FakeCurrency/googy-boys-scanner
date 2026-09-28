"""IGNITION -- an independent, adversarial behavioural suite for the engine,
the replay and the CLI (scanner/ignition/engine.py, backtest.py, run.py).

WRITTEN AGAINST THE SPEC, NOT THE CODE. The rule is stated three times -- the
config block (`IGNITION_*`), the engine docstring (the coil / trigger / plan
table) and `simulate()`'s per-bar ordering -- and every expectation below is
derived from those statements, then checked against numbers computed by hand
or by an independent re-implementation inside this file. Nothing here imports
a helper from the package to compute an EXPECTED value.

THE MOST IMPORTANT TEST IS CAUSALITY. The lens publishes a live row off the
last bar and a backtest off every bar of the same series, so a single
look-ahead anywhere (a centred window, a missing `shift(1)`, a bfill) would
make the replay's evidence describe a rule nobody could have traded. It is
proved the only way that counts: truncate the frame at bar k and the
truncated computation must reproduce row k of the full one EXACTLY, column
for column, for many k -- and the page's state at k must agree with an
independent replay of the spec off the full frame.

THE FIXTURES are synthetic and deterministic (numpy default_rng, fixed seeds):
a long volatile decline, a long quiet base whose volatility and volume
CONTRACT into the break (so the 2-year ATR% and volume ranks really are at
the bottom), a breakout bar on a volume multiple, then a run. Variants remove
one ingredient at a time. Network is never touched.

BUGS were pinned as `xfail(strict=True)` while they stood; the three this
suite found (gap-through-stop MFE/MAE, the second clock in the staleness
gate, an all-stale screen overwriting the last good file) were fixed on
2026-09-28 and their tests now run as ordinary regressions.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import zlib
from functools import lru_cache
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from scanner import config, output
from scanner.ignition import backtest as BT
from scanner.ignition import engine as E
from scanner.ignition import run as RUN

MARKET = "crypto"
NB = int(config.IGNITION_BASE_BARS)
KEEP = int(config.IGNITION_KEEP_BARS)
FRESH = int(config.IGNITION_FRESH_BARS)

# ---------------------------------------------------------------------------
# the synthetic tape
# ---------------------------------------------------------------------------

N_DECLINE, N_BASE = 380, 300
T = N_DECLINE + N_BASE          # the designed trigger bar of every default-shape fixture

# close-to-close returns after the trigger: a clean run, then one -15% day
DEFAULT_RUN = tuple([0.05, 0.06, 0.05, 0.04, 0.03] + [0.02] * 19 + [-0.15] + [0.01] * 5)
TRAIL_EARLY = (0.05, 0.06, 0.05, 0.04, 0.03, 0.02, 0.02, -0.15) + (0.01,) * 22
FAILED = (0.01, -0.05, -0.06, -0.02, 0.0) + (0.0,) * 10
GAP_THROUGH = (0.01, -0.12, 0.0, 0.0, 0.0, 0.0)
STOP_FAST = (-0.12, 0.0, 0.0, 0.0)


def build(seed=7, *, n_decline=N_DECLINE, n_base=N_BASE, run=DEFAULT_RUN, gaps=None,
          trig_mult=1.10, trig_vol_mult=6.0, run_vol_mult=5.0, later_vol_mult=3.0,
          chop=False, top=300.0, a_noise=0.04, base_level=80.0, vol_scale=1.0,
          start="2021-01-01") -> pd.DataFrame:
    """OHLCV: decline -> base -> ONE designed breakout bar at n_decline+n_base -> run.

    * decline: geometric drift top -> base_level, `a_noise` daily noise, 3% wicks,
      volume uniform 6-12M (crypto volume is dollars).
    * base: a sine wobble around base_level whose amplitude, noise and wicks all
      CONTRACT towards the break, and whose volume falls 4M -> 1.6M (the 20-bar
      average before the break sits ~1.7M: above the 1M base-turnover floor).
      `chop=True` swaps it for loud, heavy-volume chop.
    * trigger bar: opens at the last base close, closes `trig_mult` x the highest
      high of the previous IGNITION_BASE_BARS bars, on `trig_vol_mult` x the prior
      20-bar average volume.
    * run: `run` close-to-close returns; `gaps={k: ratio}` opens run bar k at
      ratio x the previous close (k=0 is the bar after the trigger).
    """
    rng = np.random.default_rng(seed)
    drift = (base_level / top) ** (1.0 / n_decline)
    lvl, a = top, []
    for _ in range(n_decline):
        lvl *= drift * (1.0 + rng.normal(0.0, a_noise))
        a.append(lvl)
    a = np.array(a) * (base_level / a[-1])
    a_open = np.concatenate([[a[0]], a[:-1]])
    a_wick = np.full(n_decline, 0.03)
    a_vol = rng.uniform(6e6, 1.2e7, n_decline)
    i = np.arange(n_base)
    frac = i / max(n_base - 1, 1)
    if chop:
        amp, noise, wick = np.full(n_base, 0.06), np.full(n_base, 0.04), np.full(n_base, 0.03)
        b_vol = rng.uniform(6e6, 1.2e7, n_base)
    else:
        amp = 0.03 + (0.006 - 0.03) * frac
        noise = 0.010 + (0.0015 - 0.010) * frac
        wick = 0.010 + (0.002 - 0.010) * frac
        b_vol = (4e6 + (1.6e6 - 4e6) * frac) * (1.0 + rng.normal(0.0, 0.03, n_base))
    b = (base_level * (1.0 + amp * np.sin(2 * np.pi * i / 23.0))
         * (1.0 + rng.normal(0.0, 1.0, n_base) * noise))
    b_open = np.concatenate([[a[-1]], b[:-1]])
    close = np.concatenate([a, b])
    opn = np.concatenate([a_open, b_open])
    wk = np.concatenate([a_wick, wick])
    high = np.maximum(opn, close) * (1.0 + wk)
    low = np.minimum(opn, close) * (1.0 - wk)
    vol = np.concatenate([a_vol, b_vol])
    t = n_decline + n_base
    base_high = high[t - NB:t].max()
    prior = vol[t - 20:t].mean()
    t_open, t_close = close[-1], base_high * trig_mult
    ro, rh, rl, rc, rv = [t_open], [t_close * 1.005], [t_open * 0.998], [t_close], [trig_vol_mult * prior]
    prev = t_close
    gaps = gaps or {}
    for k, r in enumerate(run):
        o = prev * gaps.get(k, 1.0)
        c = prev * (1.0 + r)
        ro.append(o)
        rh.append(max(o, c) * 1.01)
        rl.append(min(o, c) * 0.99)
        rc.append(c)
        rv.append((run_vol_mult if k == 0 else later_vol_mult) * prior)
        prev = c
    df = pd.DataFrame({
        "Open": np.concatenate([opn, ro]), "High": np.concatenate([high, rh]),
        "Low": np.concatenate([low, rl]), "Close": np.concatenate([close, rc]),
        "Volume": np.concatenate([vol, rv]) * vol_scale})
    df.index = pd.date_range(start, periods=len(df), freq="D")
    return df


def _btc(n: int, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = 20000.0 * np.cumprod(1.0 + 0.001 + rng.normal(0.0, 0.02, n))
    return pd.DataFrame({"Open": np.r_[c[0], c[:-1]], "High": c * 1.01, "Low": c * 0.99,
                         "Close": c, "Volume": np.full(n, 3e10)},
                        index=pd.date_range("2021-01-01", periods=n, freq="D"))


_VARIANTS = {
    "base": {},
    "trail_early": {"run": TRAIL_EARLY},
    "failed": {"run": FAILED},
    "gap_through": {"run": GAP_THROUGH, "gaps": {1: 0.84}},
    "stop_fast": {"run": STOP_FAST},
    "gap_up": {"gaps": {0: 1.02}},              # the entry bar opens ABOVE the trigger close
    "gap_below": {"gaps": {0: 0.85}},           # the entry bar opens UNDER the stop
    "chop": {"chop": True},                     # no coil: loud chop, then the same breakout
    "novol": {"trig_vol_mult": 2.0, "run_vol_mult": 2.0, "later_vol_mult": 2.0},
    "overext": {"trig_mult": 2.0},              # breakout candle already >60% over the 9-SMA
    "thin": {"vol_scale": 0.25},                # base 20d avg ~0.42M, trigger day ~2.5M
    "shallow": {"top": 40.0, "a_noise": 0.02},  # a RISE into the base: no drawdown
    "mm_live": {"trig_mult": 1.01},             # a small candle: measured move above entry
    "short": {"n_decline": 200, "n_base": 200},  # 400 bars before the trigger
}


@lru_cache(maxsize=None)
def _frame(name: str) -> pd.DataFrame:
    return build(**_VARIANTS[name])


def fx(name: str) -> pd.DataFrame:
    """A fresh copy of a named fixture (the cache is never handed out to mutate)."""
    return _frame(name).copy()


def redate(df: pd.DataFrame, end) -> pd.DataFrame:
    out = df.copy()
    out.index = pd.date_range(end=pd.Timestamp(end), periods=len(out), freq="D")
    return out


@lru_cache(maxsize=None)
def _compute(name: str) -> pd.DataFrame:
    return E.compute(_frame(name), MARKET)


def P(**kw) -> E.Params:
    p = E.Params.from_config(MARKET)
    return p.replace(**kw) if kw else p


def trig_bars(df: pd.DataFrame, p=None) -> list:
    return [int(i) for i in np.flatnonzero(E.compute(df, MARKET, p)["trigger"].to_numpy())]


# ---------------------------------------------------------------------------
# independent re-implementations (for EXPECTED values only)
# ---------------------------------------------------------------------------

def wilder_atr(df: pd.DataFrame, n: int) -> np.ndarray:
    h, lo, c = (df[k].to_numpy(float) for k in ("High", "Low", "Close"))
    tr = np.empty(len(c))
    tr[0] = h[0] - lo[0]
    for j in range(1, len(c)):
        tr[j] = max(h[j] - lo[j], abs(h[j] - c[j - 1]), abs(lo[j] - c[j - 1]))
    out = np.empty(len(c))
    out[0] = tr[0]
    for j in range(1, len(c)):
        out[j] = out[j - 1] + (tr[j] - out[j - 1]) / n
    return out


def avg_pct_rank(window: np.ndarray, x: float) -> float:
    """'average' percentile rank of x inside `window` (NaNs dropped)."""
    w = window[np.isfinite(window)]
    return ((w < x).sum() + ((w == x).sum() + 1) / 2.0) / len(w)


def walk_exit(df: pd.DataFrame, t0: int, stop: float, k: int):
    """The spec's exit, re-implemented: bars t0+1..k, stop intrabar first (a gap
    through it fills at the open), else a CLOSE under the 9-SMA exits at the
    next open -- or is 'pending' when that close is the last bar we can see."""
    o, lo, c = (df[x].to_numpy(float) for x in ("Open", "Low", "Close"))
    n_trail = int(config.IGNITION_TRAIL_SMA)
    for j in range(t0 + 1, k + 1):
        if lo[j] <= stop:
            return ("stop", j, o[j] if o[j] <= stop else stop, False)
        if j >= n_trail - 1 and c[j] < c[j - n_trail + 1:j + 1].mean():
            if j < k:
                return ("trail", j + 1, o[j + 1], False)
            return ("trail", j, c[j], True)
    return None


def replay_state(df: pd.DataFrame, full: pd.DataFrame, k: int):
    """What the page SHOULD say at bar k, read off the FULL-frame columns."""
    trig = np.flatnonzero(full["trigger"].to_numpy()[:k + 1])
    recent = trig[trig >= k - KEEP + 1]
    if len(recent):
        t0 = int(recent[-1])
        ex = walk_exit(df, t0, float(full["stop"].iloc[t0]), k)
        if ex is not None:
            return {"state": "CLOSED", "t0": t0, "exit": ex}
        return {"state": "IGNITING" if k - t0 < FRESH else "RUNNING", "t0": t0}
    lb = int(config.IGNITION_COIL_LOOKBACK)
    if full["coiled"].to_numpy()[max(0, k - lb + 1):k + 1].any():
        return {"state": "COILED"}
    return None


def _date(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


# ===========================================================================
# 1. CAUSALITY -- the test that matters most
# ===========================================================================

def _causal_ks(n: int) -> list:
    warm = [0, 1, 8, 9, 13, 14, 19, 20, 59, 60, 61, 199, 200, 364, 365, 383, 384,
            400, 483, 484, 485, 500, 600, 650]
    return sorted({k for k in warm + list(range(T - 12, n)) if k < n})


@pytest.mark.parametrize("name", ["base", "chop", "trail_early"])
def test_compute_on_a_truncated_frame_reproduces_every_row_exactly(name):
    """compute(df[:k+1]) == compute(df)[:k+1] for every column, bit for bit,
    at the warm-up edges (SMA 9/26/200, ATR, base 60, rank min-periods 365,
    vol-rank 383) and at EVERY bar from 12 before the trigger to the end."""
    df = fx(name)
    full = E.compute(df, MARKET)
    for k in _causal_ks(len(df)):
        part = E.compute(df.iloc[:k + 1], MARKET)
        pd.testing.assert_frame_equal(part, full.iloc[:k + 1], check_exact=True,
                                      obj=f"{name} truncated at bar {k}")


def test_rewriting_the_future_never_moves_the_past():
    """The same property from the other side: scramble every bar after k and
    rows <= k must not change -- a centred window or a bfill would move them."""
    df = fx("base")
    full = E.compute(df, MARKET)
    for k in (T - 1, T, T + 1, T + 10):
        fut = df.copy()
        fut.iloc[k + 1:, :4] *= 3.7
        fut.iloc[k + 1:, 4] *= 0.01
        pd.testing.assert_frame_equal(E.compute(fut, MARKET).iloc[:k + 1],
                                      full.iloc[:k + 1], check_exact=True)


@pytest.mark.parametrize("name", ["base", "trail_early", "failed", "gap_through", "stop_fast"])
def test_screen_state_at_every_bar_matches_an_independent_replay(name):
    """The live row at bar k (screen_frame on bars <= k) must be exactly what
    the spec says off the FULL frame at k: IGNITING / RUNNING / CLOSED / COILED
    / None, with the same trigger, and for CLOSED the same exit bar and price."""
    df = fx(name)
    full = E.compute(df, MARKET)
    ks = sorted(set(list(range(T - 3, len(df))) + [482, 483, 484, 485, 600]))
    seen = set()
    for k in ks:
        got = E.screen_frame(df.iloc[:k + 1], MARKET)
        want = replay_state(df, full, k)
        if want is None:
            assert got is None, f"{name}@{k}: expected no row, got {got and got['state']}"
            seen.add(None)
            continue
        assert got is not None, f"{name}@{k}: expected {want['state']}, got None"
        assert got["state"] == want["state"], f"{name}@{k}"
        assert got["provisional"] is False
        assert got["last_bar"] == _date(df.index[k])
        seen.add(want["state"])
        if want["state"] == "COILED":
            continue
        t0 = want["t0"]
        assert got["trigger_date"] == _date(df.index[t0])
        assert got["bars_since"] == k - t0
        assert got["trigger_close"] == pytest.approx(df["Close"].iloc[t0], abs=1e-8)
        assert got["stop"] == pytest.approx(full["stop"].iloc[t0], abs=1e-8)
        if want["state"] == "CLOSED":
            reason, bar, px, pending = want["exit"]
            assert got["exit_reason"] == reason
            assert got["exit_date"] == _date(df.index[bar])
            assert got["exit_price"] == pytest.approx(px, abs=1e-8)
            assert got["exit_pending"] is pending
        else:
            assert "exit_reason" not in got
    # the fixtures really do walk the page through its states
    assert "IGNITING" in seen and "COILED" in seen
    if name == "base":
        assert {"RUNNING", None} <= seen
    if name in ("trail_early", "failed", "gap_through", "stop_fast"):
        assert "CLOSED" in seen


# ===========================================================================
# 2. the features, by hand
# ===========================================================================

def test_features_at_the_trigger_are_the_spec_formulas_by_hand():
    df = fx("base")
    f = _compute("base")
    O, H, L, C, V = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close", "Volume"))
    atr = wilder_atr(df, int(config.IGNITION_ATR_LEN))
    ap = (f["atr"] / f["close"]).to_numpy()
    vavg = pd.Series(V).rolling(20).mean().to_numpy()
    w = int(config.IGNITION_RANK_WINDOW)
    for t in (T - 30, T - 1, T, T + 3):
        r = f.iloc[t]
        bh, bl = H[t - NB:t].max(), L[t - NB:t].min()
        assert r["base_high"] == bh          # the base EXCLUDES bar t (a rolling max is exact)
        assert r["base_low"] == bl
        assert r["rvol"] == pytest.approx(V[t] / V[t - 20:t].mean(), rel=1e-12)
        assert r["turnover_day"] == V[t]      # crypto: Yahoo volume IS dollars
        assert r["turnover_base"] == pytest.approx(V[t - 20:t].mean(), rel=1e-12)
        assert r["ext"] == pytest.approx(C[t] / C[t - 8:t + 1].mean() - 1, rel=1e-9, abs=1e-12)
        smas = [C[t - n + 1:t + 1].mean() for n in config.IGNITION_RIBBON_SMAS]
        assert r["ribbon"] == pytest.approx(max(smas) / min(smas) - 1, rel=1e-9, abs=1e-12)
        assert r["atr"] == pytest.approx(atr[t], rel=1e-9)
        assert r["atr_prev"] == pytest.approx(atr[t - 1], rel=1e-9)
        assert r["atr_rank"] == pytest.approx(avg_pct_rank(ap[max(0, t - w + 1):t + 1], ap[t]),
                                              rel=1e-12)
        assert r["vol_rank"] == pytest.approx(avg_pct_rank(vavg[max(0, t - w + 1):t + 1], vavg[t]),
                                              rel=1e-12)
        hmax = H[max(0, t - int(config.IGNITION_DD_LOOKBACK) + 1):t + 1].max()
        assert r["drawdown"] == pytest.approx(1 - C[t] / hmax, rel=1e-12)
        assert r["stop"] == pytest.approx(max(bl, bh - config.IGNITION_STOP_ATR_MULT * atr[t - 1]),
                                          rel=1e-9)
        assert r["mm_target"] == pytest.approx(bh + (bh - bl), rel=1e-12)
        assert r["trail"] == pytest.approx(C[t - 8:t + 1].mean(), rel=1e-12)


def test_the_fixture_is_the_shape_the_lens_describes():
    """Guard the guard: if the generator ever stops producing a real coil the
    rest of the suite would pass vacuously."""
    f = _compute("base")
    w = f.iloc[T - 10:T]
    assert w["coiled"].all()
    assert (w["ribbon"] <= config.IGNITION_RIBBON_MAX).all()
    assert (w["atr_rank"] <= 0.01).all() and (w["vol_rank"] <= 0.01).all()
    assert (w["drawdown"] >= 0.9).all()
    assert f["rvol"].iloc[T] == pytest.approx(6.0)


def test_warm_up_bars_can_never_be_coiled_or_trigger():
    f = _compute("base")
    # the 200-SMA ribbon does not exist before bar 199: a max over 9/26/43 alone
    # would read as a tight ribbon
    assert f["ribbon"].iloc[:199].isna().all()
    assert f["ribbon"].iloc[199:].notna().all()
    first_vol_rank = 20 - 1 + int(config.IGNITION_RANK_MIN_PERIODS) - 1
    assert f["vol_rank"].iloc[:first_vol_rank].isna().all()
    assert np.isfinite(f["vol_rank"].iloc[first_vol_rank])
    assert not f["coiled"].iloc[:first_vol_rank].any()
    assert not f["trigger"].iloc[:first_vol_rank].any()


def test_dollar_volume_is_volume_for_crypto_and_close_times_volume_for_shares():
    df = fx("base")
    crypto = E.base_features(df, "crypto")
    shares = E.base_features(df, "nasdaq")
    pd.testing.assert_series_equal(E.dollar_volume(df, "crypto"), df["Volume"], check_names=False)
    np.testing.assert_array_equal(crypto["turnover_day"].to_numpy(), df["Volume"].to_numpy())
    np.testing.assert_allclose(shares["turnover_day"].to_numpy(),
                               (df["Close"] * df["Volume"]).to_numpy(), rtol=1e-15)
    t = T
    assert shares["turnover_base"].iloc[t] == pytest.approx(
        (df["Close"] * df["Volume"]).iloc[t - 20:t].mean(), rel=1e-12)


def test_thin_crypto_turnover_blocks_even_though_close_x_volume_would_clear_it():
    """At ~$80 a coin, Close x Volume is 80x the real dollar turnover: if the
    engine multiplied a crypto volume by price, this thin tape would clear both
    floors easily. It must not trigger -- and each floor blocks on its own."""
    df = fx("thin")
    f = E.compute(df, MARKET)
    assert f["turnover_base"].iloc[T] < config.IGNITION_MIN_BASE_TURNOVER[MARKET]
    assert f["turnover_day"].iloc[T] < config.IGNITION_MIN_TRIGGER_TURNOVER[MARKET]
    assert (f["close"].iloc[T] * f["turnover_base"].iloc[T]
            > config.IGNITION_MIN_TRIGGER_TURNOVER[MARKET])
    assert trig_bars(df) == []
    assert trig_bars(df, P(min_base_turnover=0.0)) == []          # trigger floor still blocks
    assert trig_bars(df, P(min_trigger_turnover=0.0)) == []       # base floor still blocks
    assert trig_bars(df, P(min_base_turnover=0.0, min_trigger_turnover=0.0)) == [T]


def test_params_from_config_carry_the_crypto_floors_and_are_frozen():
    p = P()
    assert p.min_base_turnover == 1_000_000
    assert p.min_trigger_turnover == 3_000_000
    assert p.rvol_min == config.IGNITION_RVOL_MIN and p.coil_lookback == config.IGNITION_COIL_LOOKBACK
    q = p.replace(rvol_min=9.0)
    assert q.rvol_min == 9.0 and p.rvol_min == config.IGNITION_RVOL_MIN
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.rvol_min = 1.0  # type: ignore[misc]
    assert p.require_coil is True and p.require_rvol is True


def test_clean_sorts_dedupes_drops_dead_closes_and_floors_the_rest():
    idx = pd.to_datetime(["2024-01-03", "2024-01-01", "2024-01-02", "2024-01-02",
                          "2024-01-04", "2024-01-05"])
    raw = pd.DataFrame({
        "Open": [3.0, 1.0, 2.0, 2.5, np.nan, 5.0],
        "High": [3.5, 1.5, 2.2, np.nan, 4.5, 5.5],
        "Low": [2.5, 0.5, 1.8, 2.1, 3.5, 4.5],
        "Close": [3.2, 1.2, 2.0, 2.4, 4.0, 0.0],
        "Volume": [10.0, np.nan, 5.0, -7.0, 9.0, 1.0],
        "Extra": [0] * 6}, index=idx)
    out = E.clean(raw)
    assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert list(out.index) == list(pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03",
                                                   "2024-01-04"]))
    d2 = out.loc["2024-01-02"]
    assert d2["Close"] == 2.4                    # duplicate date: the LAST row wins
    assert d2["High"] == 2.4                     # NaN high reads as the close
    assert d2["Volume"] == 0.0                   # negative volume floored
    assert out.loc["2024-01-01", "Volume"] == 0.0   # NaN volume floored
    assert out.loc["2024-01-04", "Open"] == 4.0     # NaN open reads as the close
    assert pd.Timestamp("2024-01-05") not in out.index   # zero close dropped
    empty = E.clean(raw.drop(columns=["Volume"]))
    assert len(empty) == 0 and list(empty.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(E.clean(None)) == 0


# ===========================================================================
# 3. the trigger on the real-shaped tape
# ===========================================================================

def test_the_trigger_fires_on_the_designed_bar_and_nowhere_else():
    f = _compute("base")
    assert [int(i) for i in np.flatnonzero(f["trigger"].to_numpy())] == [T]
    # nothing in 680 bars of decline and base comes close to the rvol bar
    assert f["rvol"].iloc[:T].max() < config.IGNITION_RVOL_MIN
    assert f["breakout"].iloc[T] and not f["breakout"].iloc[T - 1]


def test_rearm_suppresses_the_next_day_of_the_same_move():
    """Bar T+1 is a genuine raw trigger (coiled window, breakout, rvol ~4x,
    under the ext cap) -- and must not re-fire: one trigger per move."""
    f = _compute("base")
    assert bool(f["raw_trigger"].iloc[T + 1]) and not bool(f["trigger"].iloc[T + 1])
    assert f["rvol"].iloc[T + 1] >= config.IGNITION_RVOL_MIN
    assert bool(f["coil_window"].iloc[T + 1]) and f["ext"].iloc[T + 1] <= config.IGNITION_MAX_EXT
    # the suppression is the rearm and nothing else: the raw legs all pass at T+1
    assert bool(f["breakout"].iloc[T + 1])


@pytest.mark.parametrize("leg,col,kind", [
    ("ribbon_max", "ribbon", "max"),
    ("atr_pctl_max", "atr_rank", "max"),
    ("vol_pctl_max", "vol_rank", "max"),
    ("min_drawdown", "drawdown", "min"),
])
def test_each_coil_leg_alone_blocks_the_trigger_and_its_bound_is_inclusive(leg, col, kind):
    """Tighten ONE leg by one ulp past its value on every bar of the lookback
    window (T-L..T-1): no trigger anywhere. Set it exactly AT that value: the
    trigger comes back (<= / >= are inclusive)."""
    df = fx("base")
    w = _compute("base")[col].iloc[T - int(config.IGNITION_COIL_LOOKBACK):T]
    if kind == "max":
        edge = float(w.min())
        tight = float(np.nextafter(edge, -np.inf))
    else:
        edge = float(w.max())
        tight = float(np.nextafter(edge, np.inf))
    assert trig_bars(df, P(**{leg: tight})) == []
    assert trig_bars(df, P(**{leg: edge})) == [T]


def test_no_coil_no_trigger_but_the_breakout_only_ablation_takes_it():
    df = fx("chop")
    f = E.compute(df, MARKET)
    assert not f["coil_window"].iloc[T]
    assert f["atr_rank"].iloc[T - 10:T].min() > config.IGNITION_ATR_PCTL_MAX
    assert trig_bars(df) == []
    assert trig_bars(df, P(require_coil=False)) == [T]


def test_a_rise_into_the_base_is_not_deep_enough():
    df = fx("shallow")
    f = E.compute(df, MARKET)
    assert f["drawdown"].iloc[T - 10:T].max() < config.IGNITION_MIN_DRAWDOWN
    assert trig_bars(df) == []
    dd = float(f["drawdown"].iloc[T - 10:T].max())
    assert trig_bars(df, P(min_drawdown=dd)) == [T]     # drawdown was the ONLY missing leg


def test_a_breakout_without_volume_is_not_an_ignition():
    df = fx("novol")
    f = E.compute(df, MARKET)
    assert f["rvol"].iloc[T] == pytest.approx(2.0)
    assert f["turnover_day"].iloc[T] >= config.IGNITION_MIN_TRIGGER_TURNOVER[MARKET]
    assert trig_bars(df) == []
    assert trig_bars(df, P(require_rvol=False)) == [T]
    assert trig_bars(df, P(rvol_min=float(f["rvol"].iloc[T]))) == [T]   # rvol >= is inclusive


def test_an_over_extended_candle_is_refused_as_a_chase():
    df = fx("overext")
    f = E.compute(df, MARKET)
    assert f["ext"].iloc[T] > config.IGNITION_MAX_EXT
    assert trig_bars(df) == []
    assert trig_bars(df, P(max_ext=float(f["ext"].iloc[T]))) == [T]   # <= is inclusive


# ===========================================================================
# 4. the rules on a hand-built feature frame (every boundary, exactly)
# ===========================================================================

_BF_COLS = dict(open=100.0, high=101.0, low=99.0, close=100.0, ribbon=0.05, atr=4.0,
                atr_prev=4.0, atr_rank=0.10, vol_rank=0.10, drawdown=0.80,
                base_high=110.0, base_low=90.0, rvol=5.0, turnover_base=2e6,
                turnover_day=1e7, ext=0.10, trail=95.0)
TB = 50   # the breakout bar of the hand-built frame


def bf_frame(n: int = 90, **cols) -> pd.DataFrame:
    """Every bar coiled and passing every trigger leg EXCEPT the breakout
    (close 100 under a base high of 110). Tests flip exactly what they test."""
    vals = {**_BF_COLS, **cols}
    return pd.DataFrame({k: np.full(n, v, dtype=float) for k, v in vals.items()},
                        index=pd.date_range("2024-01-01", periods=n, freq="D"))


def put(bf: pd.DataFrame, col: str, bar: int, value: float) -> pd.DataFrame:
    bf.iloc[bar, bf.columns.get_loc(col)] = value
    return bf


def breakout_at(bf: pd.DataFrame, *bars: int) -> pd.DataFrame:
    for b in bars:
        put(bf, "close", b, 120.0)
    return bf


def rules(bf: pd.DataFrame, **kw) -> pd.DataFrame:
    return E.apply_rules(bf, P(**kw))


def fired(bf: pd.DataFrame, **kw) -> list:
    return [int(i) for i in np.flatnonzero(rules(bf, **kw)["trigger"].to_numpy())]


def test_hand_frame_baseline_one_breakout_one_trigger():
    assert fired(breakout_at(bf_frame(), TB)) == [TB]
    assert fired(bf_frame()) == []


def test_coiled_on_the_trigger_bar_itself_does_not_count():
    """The coil must be on t-L..t-1. A bar that is coiled only on the day it
    breaks out is not a coil-then-ignition -- it is the ignition."""
    bf = breakout_at(bf_frame(ribbon=0.50), TB)
    put(bf, "ribbon", TB, 0.05)
    r = rules(bf)
    assert bool(r["coiled"].iloc[TB]) and not bool(r["coil_window"].iloc[TB])
    assert not bool(r["trigger"].iloc[TB])


@pytest.mark.parametrize("d", list(range(0, 13)))
def test_coil_lookback_window_is_exactly_t_minus_L_to_t_minus_1(d):
    L = int(config.IGNITION_COIL_LOOKBACK)
    bf = breakout_at(bf_frame(ribbon=0.50), TB)
    put(bf, "ribbon", TB - d, 0.05)          # coiled on exactly ONE bar, d bars back
    assert fired(bf) == ([TB] if 1 <= d <= L else [])


def test_coil_open_says_whether_the_NEXT_bar_could_trigger():
    """coil_open at bar k == 'a trigger on k+1 would count' == coiled on k-L+1..k."""
    L = int(config.IGNITION_COIL_LOOKBACK)
    for d in range(0, L + 2):
        bf = bf_frame(ribbon=0.50)
        put(bf, "ribbon", TB - d, 0.05)
        r = rules(bf)
        assert bool(r["coil_open"].iloc[TB]) is (d <= L - 1), d
        assert bool(r["coil_open"].iloc[TB]) is bool(r["coil_window"].iloc[TB + 1]), d


@pytest.mark.parametrize("col,bad", [("ribbon", 0.50), ("atr_rank", 0.90),
                                     ("vol_rank", 0.90), ("drawdown", 0.10)])
def test_each_coil_leg_failing_everywhere_blocks_on_its_own(col, bad):
    bf = breakout_at(bf_frame(**{col: bad}), TB)
    assert not rules(bf)["coiled"].any()
    assert fired(bf) == []
    assert fired(bf, require_coil=False) == [TB]


@pytest.mark.parametrize("col", ["ribbon", "atr_rank", "vol_rank", "drawdown"])
def test_a_missing_coil_input_is_never_coiled(col):
    bf = breakout_at(bf_frame(**{col: np.nan}), TB)
    assert not rules(bf)["coiled"].any()
    assert fired(bf) == []


def test_coil_bounds_are_inclusive_on_the_hand_frame():
    p = P()
    bf = breakout_at(bf_frame(ribbon=p.ribbon_max, atr_rank=p.atr_pctl_max,
                              vol_rank=p.vol_pctl_max, drawdown=p.min_drawdown), TB)
    assert fired(bf) == [TB]


def test_breakout_is_strictly_above_the_base_high():
    bf = bf_frame()
    put(bf, "close", TB, 110.0)                             # == base high
    assert fired(bf) == []
    put(bf, "close", TB, float(np.nextafter(110.0, np.inf)))
    assert fired(bf) == [TB]
    # the tolerance lifts the bar the close must clear
    bf2 = bf_frame()
    put(bf2, "close", TB, 110.0 * 1.05)
    assert fired(bf2, breakout_tol=0.05) == []
    put(bf2, "close", TB, 110.0 * 1.05 + 1e-9)
    assert fired(bf2, breakout_tol=0.05) == [TB]


def test_rvol_threshold_is_inclusive_and_can_be_ablated():
    bf = breakout_at(bf_frame(), TB)
    put(bf, "rvol", TB, 3.0)
    assert fired(bf) == [TB]
    put(bf, "rvol", TB, float(np.nextafter(3.0, 0.0)))
    assert fired(bf) == []
    assert fired(bf, require_rvol=False) == [TB]
    put(bf, "rvol", TB, np.nan)                  # no prior volume: never confirmed
    assert fired(bf) == []


def test_ext_cap_is_inclusive():
    bf = breakout_at(bf_frame(), TB)
    put(bf, "ext", TB, 0.60)
    assert fired(bf) == [TB]
    put(bf, "ext", TB, float(np.nextafter(0.60, 1.0)))
    assert fired(bf) == []


@pytest.mark.parametrize("col,floor", [("turnover_base", 1_000_000.0),
                                       ("turnover_day", 3_000_000.0)])
def test_turnover_floors_are_inclusive(col, floor):
    bf = breakout_at(bf_frame(), TB)
    put(bf, col, TB, floor)
    assert fired(bf) == [TB]
    put(bf, col, TB, float(np.nextafter(floor, 0.0)))
    assert fired(bf) == []


def test_rearm_window_boundary():
    R = int(config.IGNITION_REARM_BARS)
    assert fired(breakout_at(bf_frame(), TB, TB + R)) == [TB]          # R bars later: same move
    assert fired(breakout_at(bf_frame(), TB, TB + R + 1)) == [TB, TB + R + 1]


def test_rearm_counts_RAW_triggers_so_a_continuous_move_fires_once():
    """'no raw trigger in the REARM bars before t': a breakout repeated every
    15 bars is one long move -- each raw trigger re-arms the suppression."""
    bf = breakout_at(bf_frame(n=120), TB, TB + 15, TB + 30, TB + 45)
    r = rules(bf)
    assert [int(i) for i in np.flatnonzero(r["raw_trigger"].to_numpy())] == [TB, TB + 15, TB + 30, TB + 45]
    assert fired(bf) == [TB]


def test_stop_is_the_higher_of_base_low_and_base_high_minus_atr():
    bf = breakout_at(bf_frame(), TB)
    assert rules(bf)["stop"].iloc[TB] == 106.0                     # 110 - 1 x 4 > 90
    put(bf, "atr_prev", TB, 30.0)
    assert rules(bf)["stop"].iloc[TB] == 90.0                      # 110 - 30 < 90 -> base low
    put(bf, "atr_prev", TB, 4.0)
    assert rules(bf, stop_atr_mult=2.5)["stop"].iloc[TB] == 100.0  # 110 - 2.5 x 4


def test_measured_move_target_is_base_high_plus_base_range():
    bf = breakout_at(bf_frame(), TB)
    assert rules(bf)["mm_target"].iloc[TB] == 130.0               # 110 + (110 - 90)


def test_coiled_run_counts_consecutive_coiled_bars():
    bf = bf_frame(ribbon=0.50)
    for b in (10, 11, 12, 20):
        put(bf, "ribbon", b, 0.05)
    run = rules(bf)["coiled_run"].to_numpy()
    assert list(run[9:14]) == [0, 1, 2, 3, 0]
    assert run[20] == 1 and run[21] == 0


# ===========================================================================
# 5. simulate() -- the one exit walk, by hand
# ===========================================================================

def arrays(rows):
    a = np.array(rows, dtype=float)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


def nan_trail(n):
    return np.full(n, np.nan)


# bar 0 is BEFORE the entry: absurd high/low so any leak of it into mfe/mae shows
PRE = (100.0, 500.0, 1.0, 100.0)


def test_stop_intrabar_fills_at_the_stop():
    o, h, lo, c = arrays([PRE, (100, 105, 95, 102), (101, 103, 89, 92), (92, 93, 91, 92)])
    out = E.simulate(o, h, lo, c, nan_trail(4), start=1, entry=100.0, stop=90.0)
    assert out["reason"] == "stop" and out["exit_bar"] == 2 and out["bars"] == 2
    assert out["exit_price"] == 90.0 and out["pending"] is False
    assert out["gross_r"] == pytest.approx(-1.0)
    assert out["mfe_r"] == pytest.approx(0.5)            # 105, never bar 0's 500
    assert out["fills"] == [(1.0, 90.0, 2, "stop")]


def test_a_gap_through_the_stop_fills_at_the_open():
    o, h, lo, c = arrays([PRE, (100, 105, 95, 102), (85, 88, 84, 86)])
    out = E.simulate(o, h, lo, c, nan_trail(3), start=1, entry=100.0, stop=90.0)
    assert out["reason"] == "stop" and out["exit_price"] == 85.0
    assert out["gross_r"] == pytest.approx(-1.5)


def test_a_low_exactly_on_the_stop_is_a_stop():
    o, h, lo, c = arrays([PRE, (100, 105, 90, 102)])
    out = E.simulate(o, h, lo, c, nan_trail(2), start=1, entry=100.0, stop=90.0)
    assert out["reason"] == "stop" and out["exit_price"] == 90.0


def test_the_stop_is_checked_before_a_target_on_the_same_bar():
    o, h, lo, c = arrays([PRE, (100, 150, 85, 120)])
    out = E.simulate(o, h, lo, c, nan_trail(2), start=1, entry=100.0, stop=90.0,
                     ladder=((0.5, 110.0), (0.5, 130.0)))
    assert out["reason"] == "stop"
    assert out["fills"] == [(1.0, 90.0, 1, "stop")]
    assert out["gross_r"] == pytest.approx(-1.0)


def test_a_close_under_the_trail_exits_at_the_NEXT_open_and_lives_only_that_open():
    o, h, lo, c = arrays([PRE, (100, 104, 99, 100), (100, 103, 98, 100),
                          (103, 150, 97, 120), (120, 121, 119, 120)])
    trail = np.array([np.nan, 99.0, 101.0, 90.0, 90.0])
    out = E.simulate(o, h, lo, c, trail, start=1, entry=100.0, stop=90.0)
    assert out["reason"] == "trail" and out["pending"] is False
    assert out["exit_bar"] == 3 and out["bars"] == 3
    assert out["exit_price"] == 103.0
    assert out["gross_r"] == pytest.approx(0.3)
    assert out["mfe_r"] == pytest.approx(0.4)     # 104 -- NOT the exit bar's 150
    assert out["mae_r"] == pytest.approx(0.2)     # 98 -- NOT the exit bar's 97


def test_a_trail_signal_on_the_last_bar_is_pending_at_the_close():
    o, h, lo, c = arrays([PRE, (100, 104, 99, 100), (100, 103, 98, 99)])
    trail = np.array([np.nan, 99.0, 101.0])
    out = E.simulate(o, h, lo, c, trail, start=1, entry=100.0, stop=90.0)
    assert out["reason"] == "trail" and out["pending"] is True
    assert out["exit_bar"] == 2 and out["exit_price"] == 99.0
    assert out["gross_r"] == pytest.approx(-0.1)


def test_a_nan_trail_never_exits():
    o, h, lo, c = arrays([PRE, (100, 101, 99, 95), (95, 96, 94, 95)])
    out = E.simulate(o, h, lo, c, nan_trail(3), start=1, entry=100.0, stop=90.0)
    assert out["reason"] == "open" and out["exit_bar"] == 2 and out["exit_price"] == 95.0


def test_ladder_fills_at_the_price_or_at_a_gap_open_and_the_rest_rides():
    o, h, lo, c = arrays([PRE,
                          (100, 112, 99, 111),     # 0.25 @ 110
                          (135, 140, 133, 138),    # gap over 130 -> 0.50 @ 135 (the open)
                          (138, 151, 137, 150),    # 0.15 @ 150
                          (150, 152, 149, 151)])   # 0.10 rides -> open at the last close
    out = E.simulate(o, h, lo, c, nan_trail(5), start=1, entry=100.0, stop=90.0,
                     ladder=((0.25, 110.0), (0.50, 130.0), (0.15, 150.0)))
    assert out["fills"] == [(0.25, 110.0, 1, "target"), (0.5, 135.0, 2, "target"),
                            (0.15, 150.0, 3, "target"), (pytest.approx(0.1), 151.0, 4, "open")]
    # 0.25x10 + 0.5x35 + 0.15x50 + 0.1x51 = 32.6 -> 3.26R
    assert out["gross_r"] == pytest.approx(3.26)
    assert out["exit_price"] == pytest.approx(132.6)
    assert out["reason"] == "open"
    assert out["mfe_r"] == pytest.approx(5.2)


def test_a_ladder_covering_everything_ends_as_target():
    o, h, lo, c = arrays([PRE, (100, 125, 99, 121), (121, 122, 120, 121)])
    out = E.simulate(o, h, lo, c, nan_trail(3), start=1, entry=100.0, stop=90.0,
                     ladder=((0.5, 110.0), (0.5, 120.0)))
    assert out["reason"] == "target" and out["exit_bar"] == 1 and out["bars"] == 1
    assert out["gross_r"] == pytest.approx(1.5)


def test_max_hold_exits_at_the_close_of_the_Nth_bar():
    o, h, lo, c = arrays([PRE] + [(100, 101, 99, 100 + j) for j in range(1, 7)])
    out = E.simulate(o, h, lo, c, nan_trail(7), start=1, entry=100.0, stop=90.0, max_hold=3)
    assert out["reason"] == "time" and out["exit_bar"] == 3 and out["bars"] == 3
    assert out["exit_price"] == 103.0 and out["gross_r"] == pytest.approx(0.3)


def test_running_off_the_end_is_open_marked_at_the_last_close():
    o, h, lo, c = arrays([PRE, (100, 108, 97, 104), (104, 109, 103, 106)])
    out = E.simulate(o, h, lo, c, nan_trail(3), start=1, entry=100.0, stop=90.0)
    assert out["reason"] == "open" and out["exit_bar"] == 2 and out["bars"] == 2
    assert out["exit_price"] == 106.0
    assert out["gross_r"] == pytest.approx(0.6)
    assert out["mfe_r"] == pytest.approx(0.9) and out["mae_r"] == pytest.approx(0.3)


def test_no_risk_means_no_R():
    o, h, lo, c = arrays([PRE, (100, 101, 99, 100)])
    out = E.simulate(o, h, lo, c, nan_trail(2), start=1, entry=100.0, stop=100.0)
    assert np.isnan(out["gross_r"])


# WAS A BUG (fixed 2026-09-28): simulate() folds the high/low of a bar that
# GAPS THROUGH the stop into mfe/mae before exiting at that bar's open. The
# position was out at the open, so nothing after it was lived through -- the
# exact principle the trail branch states ('only the OPEN of the exit bar
# was lived through'). A trade that gapped straight to a loss reports +2R
# MFE.
def test_a_gap_through_stop_bar_contributes_only_its_open_to_mfe_and_mae():
    o, h, lo, c = arrays([PRE, (85, 120, 80, 88)])
    out = E.simulate(o, h, lo, c, nan_trail(2), start=1, entry=100.0, stop=90.0)
    assert out["reason"] == "stop" and out["exit_price"] == 85.0
    assert out["mfe_r"] == pytest.approx(0.0)
    assert out["mae_r"] == pytest.approx(1.5)


# ===========================================================================
# 6. screen_frame -- the live row
# ===========================================================================

def screen(name, k, **kw):
    return E.screen_frame(fx(name).iloc[:k + 1], MARKET, **kw)


def test_igniting_on_the_trigger_bar_and_the_next_then_running():
    df = fx("base")
    f = _compute("base")
    r0 = screen("base", T)
    assert r0["state"] == "IGNITING" and r0["bars_since"] == 0 and r0["provisional"] is False
    assert r0["mfe_r"] == 0.0
    entry, stop = df["Close"].iloc[T], f["stop"].iloc[T]
    assert r0["trigger_close"] == pytest.approx(entry, abs=1e-8)
    assert r0["risk_pct"] == pytest.approx(round((entry - stop) / entry * 100, 1))
    assert r0["wide_stop"] is False
    assert r0["rvol"] == pytest.approx(6.0)
    assert r0["base"]["high"] == pytest.approx(f["base_high"].iloc[T], abs=1e-8)
    assert r0["base"]["bars"] == NB
    # the coil block describes the bar BEFORE the trigger
    assert r0["coil"]["coiled"] is True
    assert r0["coil"]["coiled_bars"] == int(f["coiled_run"].iloc[T - 1])
    assert r0["price"] == pytest.approx(entry, abs=1e-8) and r0["r_now"] == 0.0

    r1 = screen("base", T + 1)
    assert r1["state"] == "IGNITING" and r1["bars_since"] == 1
    assert r1["mfe_r"] == pytest.approx(round((df["High"].iloc[T + 1] - entry) / (entry - stop), 2))
    r2 = screen("base", T + 2)
    assert r2["state"] == "RUNNING" and r2["bars_since"] == 2
    assert r2["change_pct"] == pytest.approx(round((df["Close"].iloc[T + 2] / entry - 1) * 100, 1))
    assert r2["r_now"] == pytest.approx(round((df["Close"].iloc[T + 2] - entry) / (entry - stop), 2))
    assert r2["trail"] == pytest.approx(df["Close"].iloc[T - 6:T + 3].mean(), abs=1e-6)


def test_the_keep_window_holds_a_row_for_exactly_KEEP_bars():
    assert screen("base", T + KEEP - 1)["state"] == "RUNNING"
    assert screen("base", T + KEEP) is None
    assert screen("trail_early", T + KEEP - 1)["state"] == "CLOSED"
    assert screen("trail_early", T + KEEP) is None


def test_the_keep_constant_is_what_drives_expiry(monkeypatch):
    monkeypatch.setattr(config, "IGNITION_KEEP_BARS", 15)
    assert screen("base", T + 14)["state"] == "RUNNING"
    assert screen("base", T + 15) is None
    # a keep window SHORTER than the coil lookback hands the name back to COILED:
    # the ignition bars themselves still read as coiled (the ranks lag), and
    # COILED only asks whether a trigger on the NEXT bar would count
    monkeypatch.setattr(config, "IGNITION_KEEP_BARS", 5)
    r = screen("base", T + 5)
    assert r["state"] == "COILED" and "trigger_date" not in r


def test_closed_by_trail_is_pending_on_the_signal_bar_then_filled_at_the_next_open():
    df = fx("trail_early")
    sig = T + 8                                     # the -15% close under the 9-SMA
    r = screen("trail_early", sig)
    assert r["state"] == "CLOSED" and r["exit_reason"] == "trail" and r["exit_pending"] is True
    assert r["exit_price"] == pytest.approx(df["Close"].iloc[sig], abs=1e-8)
    r = screen("trail_early", sig + 1)
    assert r["state"] == "CLOSED" and r["exit_pending"] is False
    assert r["exit_date"] == _date(df.index[sig + 1])
    assert r["exit_price"] == pytest.approx(df["Open"].iloc[sig + 1], abs=1e-8)
    assert screen("trail_early", sig - 1)["state"] == "RUNNING"


def test_closed_by_stop_and_by_a_gap_through_it():
    f = _compute("failed")
    stop = f["stop"].iloc[T]
    r = screen("failed", T + 5)
    assert r["state"] == "CLOSED" and r["exit_reason"] == "stop"
    assert r["exit_price"] == pytest.approx(stop, abs=1e-8) and r["exit_r"] == -1.0
    g = fx("gap_through")
    r = screen("gap_through", T + 4)
    assert r["state"] == "CLOSED" and r["exit_reason"] == "stop"
    assert r["exit_date"] == _date(g.index[T + 2])
    assert r["exit_price"] == pytest.approx(g["Open"].iloc[T + 2], abs=1e-8)
    assert r["exit_r"] < -1.0


def test_a_fresh_trigger_already_stopped_is_CLOSED_not_IGNITING():
    r = screen("stop_fast", T + 1)
    assert r["bars_since"] == 1 < FRESH
    assert r["state"] == "CLOSED" and r["exit_reason"] == "stop"


def test_coiled_row_names_the_level_the_next_bar_must_clear():
    k = 399                                          # 'short': the trigger is bar 400
    df = fx("short")
    r = E.screen_frame(df.iloc[:k + 1], MARKET)
    assert r["state"] == "COILED" and r["provisional"] is False
    nxt = E.compute(df.iloc[:k + 2], MARKET)
    assert r["breakout_level"] == pytest.approx(nxt["base_high"].iloc[k + 1], abs=1e-8)
    assert r["breakout_level"] == pytest.approx(df["High"].iloc[k + 1 - NB:k + 1].max(), abs=1e-8)
    f = E.compute(df.iloc[:k + 1], MARKET)
    assert r["base"]["high"] == pytest.approx(f["base_high"].iloc[k], abs=1e-8)
    assert r["coil"]["coiled"] is bool(f["coiled"].iloc[k])
    assert r["coil"]["coiled_bars"] == int(f["coiled_run"].iloc[k])
    assert r["coil"]["last_coiled"] == _date(df.index[np.flatnonzero(f["coiled"].to_numpy())[-1]])
    assert r["price"] == pytest.approx(df["Close"].iloc[k], abs=1e-8)
    assert "trigger_date" not in r


def test_a_forming_trigger_is_provisional_IGNITING_and_matches_the_confirmed_row():
    df = fx("short")
    k = 400
    prov = E.screen_frame(df.iloc[:k], MARKET, forming=df.iloc[k:k + 1])
    conf = E.screen_frame(df.iloc[:k + 1], MARKET)
    assert prov["state"] == "IGNITING" and prov["provisional"] is True
    assert conf["state"] == "IGNITING" and conf["provisional"] is False
    for key in ("trigger_date", "trigger_close", "stop", "risk_pct", "rvol", "ext_pct",
                "turnover_trigger", "turnover_base", "base", "mm_target", "mm_passed", "mm_r"):
        assert prov[key] == conf[key], key
    assert prov["last_bar"] == _date(df.index[k - 1])       # completed bars only
    assert prov["price"] == pytest.approx(df["Close"].iloc[k], abs=1e-8)


def test_a_forming_bar_that_does_not_trigger_leaves_the_coil_and_moves_the_price():
    df = fx("short")
    k = 400
    quiet = df.iloc[k - 1:k].copy()
    quiet.index = df.index[k:k + 1]
    quiet["Close"] = quiet["Close"] * 1.001
    r = E.screen_frame(df.iloc[:k], MARKET, forming=quiet)
    assert r["state"] == "COILED" and r["provisional"] is False
    assert r["price"] == pytest.approx(quiet["Close"].iloc[0], abs=1e-8)


def test_a_forming_bar_never_overrides_a_live_trigger():
    df = fx("base")
    r = E.screen_frame(df.iloc[:T + 6], MARKET, forming=df.iloc[T + 6:T + 7])
    assert r["state"] == "RUNNING" and r["provisional"] is False
    assert r["trigger_date"] == _date(df.index[T])
    assert r["price"] == pytest.approx(df["Close"].iloc[T + 6], abs=1e-8)
    assert r["last_bar"] == _date(df.index[T + 5])


def test_nothing_coiling_and_nothing_firing_is_no_row():
    assert E.screen_frame(fx("chop").iloc[:T], MARKET) is None
    assert E.screen_frame(fx("chop").iloc[:T], MARKET, forming=fx("base").iloc[T - 1:T]) is None
    assert E.screen_frame(fx("base").iloc[:450], MARKET) is None     # decline, no coil yet


def test_short_history_is_no_row_and_it_is_the_length_gate(monkeypatch):
    df = fx("short")
    assert E.screen_frame(df.iloc[:400], MARKET)["state"] == "COILED"   # exactly MIN_BARS
    assert E.screen_frame(df.iloc[1:400], MARKET) is None               # one bar short
    monkeypatch.setattr(config, "IGNITION_MIN_BARS", 399)
    assert E.screen_frame(df.iloc[1:400], MARKET)["state"] == "COILED"


def test_measured_move_passed_vs_live():
    r = screen("base", T)
    assert r["mm_passed"] is True and r["mm_r"] is None     # the candle outran its own base
    assert r["mm_target"] < r["trigger_close"]
    m = screen("mm_live", T)
    assert m["state"] == "IGNITING" and m["mm_passed"] is False
    assert m["mm_target"] > m["trigger_close"]
    assert m["mm_r"] == pytest.approx(round((m["mm_target"] - m["trigger_close"])
                                            / (m["trigger_close"] - m["stop"]), 2), abs=0.011)


def test_a_wide_stop_is_flagged_never_skipped():
    r = E.screen_frame(fx("chop").iloc[:T + 1], MARKET,
                       p=P(require_coil=False, stop_atr_mult=100.0))
    assert r["state"] == "IGNITING"
    assert r["risk_pct"] > config.IGNITION_WIDE_STOP_PCT and r["wide_stop"] is True
    assert r["stop"] == r["base"]["low"]


def test_state_rank_orders_the_page():
    rows = [
        {"state": "COILED", "coil": {"coiled_bars": 3, "ribbon_pct": 2.0}},
        {"state": "CLOSED", "bars_since": 3, "rvol": 5},
        {"state": "COILED", "coil": {"coiled_bars": 9, "ribbon_pct": 5.0}},
        {"state": "IGNITING", "provisional": True, "bars_since": 0, "rvol": 9},
        {"state": "RUNNING", "bars_since": 4, "rvol": 3},
        {"state": "IGNITING", "provisional": False, "bars_since": 1, "rvol": 4},
        {"state": "IGNITING", "provisional": False, "bars_since": 0, "rvol": 4},
    ]
    order = sorted(rows, key=E.state_rank)
    assert [(r["state"], r.get("provisional"), r.get("bars_since")) for r in order[:3]] == [
        ("IGNITING", False, 0), ("IGNITING", False, 1), ("IGNITING", True, 0)]
    assert [r["state"] for r in order[3:]] == ["RUNNING", "CLOSED", "COILED", "COILED"]
    assert order[5]["coil"]["coiled_bars"] == 9          # the longer coil first


# ===========================================================================
# 7. the replay
# ===========================================================================

def prepared(name, symbol="QNT", df=None):
    return BT.Prepared(symbol, E.clean(fx(name) if df is None else df), MARKET)


def test_entry_is_the_NEXT_open_never_the_trigger_close():
    df = fx("gap_up")
    pr = prepared("gap_up")
    ru = E.apply_rules(pr.bf, P())
    trades = BT.trades_for(pr, ru)
    assert len(trades) == 1
    t = trades[0]
    assert t["trigger_date"] == _date(df.index[T])
    assert t["entry_date"] == _date(df.index[T + 1])
    assert t["entry"] == df["Open"].iloc[T + 1]
    assert t["entry"] != pytest.approx(df["Close"].iloc[T], rel=1e-6)
    stop = ru["stop"].iloc[T]
    assert t["stop"] == stop
    reason, bar, px, pending = walk_exit(df, T, stop, len(df) - 1)
    assert (t["reason"], t["exit_date"]) == (reason, _date(df.index[bar]))
    risk = t["entry"] - stop
    assert t["gross_r"] == pytest.approx(round((px - t["entry"]) / risk, 4), abs=1e-4)
    assert t["risk_pct"] == round(risk / t["entry"] * 100, 2)
    assert t["bars"] == bar - (T + 1) + 1


def test_costs_subtract_cost_pct_of_entry_over_risk():
    pr = prepared("gap_up")
    ru = E.apply_rules(pr.bf, P())
    t = BT.trades_for(pr, ru, cost_pct=0.5)[0]
    risk = t["entry"] - t["stop"]
    assert t["cost_r"] == pytest.approx(round(0.005 * t["entry"] / risk, 4), abs=1e-12)
    assert t["net_r"] == pytest.approx(t["gross_r"] - t["cost_r"], abs=2e-4)
    free = BT.trades_for(pr, ru, cost_pct=0.0)[0]
    assert free["cost_r"] == 0.0 and free["net_r"] == free["gross_r"]
    dflt = BT.trades_for(pr, ru)[0]
    assert dflt["cost_r"] == pytest.approx(
        round(config.IGNITION_BT_COST_PCT / 100 * t["entry"] / risk, 4), abs=1e-12)


def test_a_next_open_under_the_stop_is_a_counted_skip_not_a_trade():
    df = fx("gap_below")
    pr = prepared("gap_below")
    ru = E.apply_rules(pr.bf, P())
    assert df["Open"].iloc[T + 1] < ru["stop"].iloc[T]
    trades = BT.trades_for(pr, ru)
    assert trades == [{"symbol": "QNT", "skipped": "gap_below_stop", "_t0": T,
                       "trigger_date": _date(df.index[T])}]
    s = BT.stats(trades)
    assert s == {"n": 0, "skipped": 1, "open": 0, "open_mtm_r": 0.0,
                 "open_at_end": 0, "pending": 0}


def test_a_trigger_on_the_last_bar_has_no_entry_yet():
    pr = prepared("base", df=fx("base").iloc[:T + 1])
    assert BT.trades_for(pr, E.apply_rules(pr.bf, P())) == []


def test_one_position_per_symbol():
    df = fx("base")
    pr = prepared("base")
    ru = E.apply_rules(pr.bf, P()).copy()
    first = BT.trades_for(pr, ru)[0]
    exit_bar = list(df.index.strftime("%Y-%m-%d")).index(first["exit_date"])
    trig = np.zeros(len(df), dtype=bool)
    for b in (T, T + 3, exit_bar, exit_bar + 1):
        trig[b] = True
    ru["trigger"] = trig
    stop_col = ru.columns.get_loc("stop")
    ru.iloc[exit_bar + 1, stop_col] = float(df["Open"].iloc[exit_bar + 2]) * 0.9
    trades = BT.trades_for(pr, ru)
    assert [t["trigger_date"] for t in trades] == [_date(df.index[T]), _date(df.index[exit_bar + 1])]
    assert not any(t.get("skipped") for t in trades)     # the blocked ones are not 'skips'


def test_exit_variants_on_the_same_entry():
    df = fx("base")
    pr = prepared("base")
    ru = E.apply_rules(pr.bf, P())
    trail9 = BT.trades_for(pr, ru)[0]
    hold = BT.trades_for(pr, ru, exit_spec="hold_20")[0]
    assert hold["reason"] == "time" and hold["bars"] == 20
    assert hold["exit_date"] == _date(df.index[T + 20])
    # the measured move sits UNDER the fill here, so 'half at mm' rides whole
    assert ru["mm_target"].iloc[T] < trail9["entry"]
    half = BT.trades_for(pr, ru, exit_spec="half_mm_trail9")[0]
    assert (half["reason"], half["exit_date"], half["gross_r"]) == \
        (trail9["reason"], trail9["exit_date"], trail9["gross_r"])
    t26 = BT.trades_for(pr, ru, exit_spec="trail26")[0]
    assert t26["exit_date"] >= trail9["exit_date"]
    floor = BT.trades_for(pr, ru, stop_spec="floor")[0]
    assert floor["stop"] == pr.bf["base_low"].iloc[T]
    lad = BT.trades_for(pr, ru, exit_spec="ladder_1_3_5")[0]
    assert lad["entry"] == trail9["entry"]


STATS_TRADES = [
    {"net_r": 2.0, "exit_date": "2024-01-05", "reason": "trail", "bars": 10},
    {"net_r": -1.0, "exit_date": "2024-01-01", "reason": "stop", "bars": 2},
    {"net_r": -1.0, "exit_date": "2024-01-02", "reason": "stop", "bars": 3},
    {"net_r": 10.0, "exit_date": "2024-01-07", "reason": "trail", "bars": 40},
    {"net_r": 0.5, "exit_date": "2024-01-04", "reason": "time", "bars": 5},
    {"net_r": -0.5, "exit_date": "2024-01-03", "reason": "trail", "bars": 4},
    {"net_r": 3.0, "exit_date": "2024-01-06", "reason": "open", "bars": 6},
    {"symbol": "X", "skipped": "gap_below_stop", "trigger_date": "2024-01-01"},
]


def test_stats_by_hand():
    """REALISED trades only (audit 2026-09-28): the +3R 'open' mark is counted
    and marked BESIDE the numbers, never inside them -- a headline that moves
    with one coin's price every day is not a result."""
    s = BT.stats(STATS_TRADES)
    assert s["n"] == 6 and s["skipped"] == 1
    assert s["open"] == 1 and s["open_mtm_r"] == 3.0 and s["open_at_end"] == 1
    assert s["pending"] == 0
    assert (s["wins"], s["losses"], s["flat"]) == (3, 3, 0)
    assert s["win_pct"] == 50.0                             # 3/6
    assert s["exp_r"] == 1.667                              # 10/6
    assert s["median_r"] == 0.0                             # (-0.5 + 0.5) / 2
    assert s["total_r"] == 10.0
    assert s["pf"] == 5.0 and s["pf_note"] is None          # 12.5 / 2.5
    assert s["avg_win_r"] == 4.167 and s["avg_loss_r"] == -0.833
    assert (s["pct_ge_3r"], s["pct_ge_5r"], s["pct_ge_10r"]) == (16.7, 16.7, 16.7)
    assert s["max_r"] == 10.0
    assert s["top5_share_pct"] == 110.0                     # (10+2+0.5-0.5-1)/10
    assert s["exp_r_ex_top5"] == -1.0                       # the -1 left over
    assert s["avg_bars"] == 10.7                            # 64/6
    assert s["stop_pct"] == 33.3                            # 2/6


def test_a_pending_trail_exit_is_a_mark_not_a_result():
    rows = [{"net_r": 1.0, "exit_date": "2024-01-01", "reason": "trail", "bars": 3},
            {"net_r": 5.0, "exit_date": "2024-01-02", "reason": "trail", "bars": 3,
             "pending": True}]
    s = BT.stats(rows)
    assert s["n"] == 1 and s["exp_r"] == 1.0
    assert s["open"] == 1 and s["pending"] == 1 and s["open_mtm_r"] == 5.0


def test_max_drawdown_is_walked_in_EXIT_order_not_list_order():
    # exit order: -1 -1 -0.5 +0.5 +2 +3 +10 -> equity -1 -2 -2.5 ... -> -2.5R.
    # the list order (2, -1, -1, 10, ...) would read -2.0R.
    assert BT.stats(STATS_TRADES)["max_dd_r"] == -2.5
    shuffled = list(reversed(STATS_TRADES))
    assert BT.stats(shuffled)["max_dd_r"] == -2.5


def test_same_day_exits_are_netted_before_the_drawdown():
    """Audit 2026-09-28: sorted by exit date alone, two trades closing on one
    day kept their (alphabetical) list order and created an intraday peak a
    daily equity curve never had: -5R one way, -4R the other."""
    a = [{"net_r": 0.0, "exit_date": "d1", "reason": "trail", "bars": 1},
         {"net_r": 4.0, "exit_date": "d2", "reason": "trail", "bars": 1},
         {"net_r": -1.0, "exit_date": "d2", "reason": "stop", "bars": 1},
         {"net_r": -4.0, "exit_date": "d3", "reason": "stop", "bars": 1}]
    b = [a[0], a[2], a[1], a[3]]
    assert BT.stats(a)["max_dd_r"] == BT.stats(b)["max_dd_r"] == -4.0


def test_stats_edge_cases():
    assert BT.stats([]) == {"n": 0, "skipped": 0, "open": 0, "open_mtm_r": 0.0,
                            "open_at_end": 0, "pending": 0}
    losers = [{"net_r": -1.0, "exit_date": "2024-01-0%d" % i, "bars": 1, "reason": "stop"}
              for i in range(1, 4)]
    s = BT.stats(losers)
    assert s["pf"] == 0.0 and s["top5_share_pct"] is None and s["exp_r_ex_top5"] is None
    assert s["max_dd_r"] == -3.0 and s["win_pct"] == 0.0
    winners = [{"net_r": 1.0, "exit_date": "2024-01-01", "bars": 1}]
    w = BT.stats(winners)
    assert w["pf"] is None and w["pf_note"] == "no losing trades"   # PF infinite, SAID
    assert "inf (no losses)" in BT._brief(w)
    zero = [{"net_r": 0.0, "exit_date": "2024-01-01", "bars": 1}]
    z = BT.stats(zero)
    assert (z["wins"], z["losses"], z["flat"]) == (0, 0, 1)   # breakeven: neither
    assert z["pf"] is None and z["pf_note"] is None and z["avg_loss_r"] is None
    nan = [{"net_r": float("nan"), "exit_date": "2024-01-01", "bars": 1},
           {"net_r": None, "exit_date": "2024-01-02", "bars": 1},
           {"net_r": 2.0, "exit_date": "2024-01-03", "bars": 1}]
    assert BT.stats(nan)["n"] == 1


BOOT_TRADES = [
    {"net_r": r, "entry_date": f"2024-{m:02d}-10", "exit_date": f"2024-{m:02d}-20",
     "reason": "trail", "bars": 5}
    for m, r in [(1, 3.0), (1, -1.0), (2, -1.0), (3, 6.0), (4, -1.0), (5, 0.5),
                 (6, -1.0), (7, 2.0), (8, -1.0), (9, 1.5)]]


def test_bootstrap_band_is_seeded_and_brackets_the_mean():
    a = BT.stats(BOOT_TRADES, boot=500, seed=11)
    b = BT.stats(BOOT_TRADES, boot=500, seed=11)
    c = BT.stats(BOOT_TRADES, boot=500, seed=12)
    assert a == b
    assert a["exp_r_ci90"] != c["exp_r_ci90"]
    lo, hi = a["exp_r_ci90"]
    assert lo <= a["exp_r"] <= hi
    assert 0.0 <= a["boot_p_exp_le_0"] <= 1.0
    assert "cluster" in a["ci_method"]
    assert "exp_r_ci90" not in BT.stats(BOOT_TRADES[:4], boot=500, seed=11)   # n < 5


def test_the_bootstrap_resamples_entry_months_WHOLE():
    """Alt ignitions bunch in alt seasons, so trades are not independent: a
    month is resampled as a block. With month A = four +1R trades and month
    B = one -1R trade, the only achievable means are AA (+1.0), AB (+0.6)
    and BB (-1.0) -- an iid bootstrap would also produce 0.2, -0.2, ..."""
    rows = [{"net_r": 1.0, "entry_date": "2024-01-0%d" % i} for i in range(1, 5)]
    rows.append({"net_r": -1.0, "entry_date": "2024-02-01"})
    means = BT._boot_means(rows, "net_r", 400, 3)
    assert set(np.round(means, 6)) <= {1.0, 0.6, -1.0}
    assert len(set(np.round(means, 6))) == 3


def test_versus_is_the_difference_statistic():
    worse = [{**t, "net_r": t["net_r"] - 1.0} for t in BOOT_TRADES]
    v = BT.versus(BOOT_TRADES, worse, boot=500, seed=4)
    assert v["diff_r"] == 1.0 and v["n_primary"] == v["n_baseline"] == 10
    lo, hi = v["diff_ci90"]
    assert lo <= 1.0 <= hi and 0.0 <= v["p_diff_le_0"] <= 1.0
    assert BT.versus(BOOT_TRADES[:3], worse, boot=100, seed=4) == \
        {"n_primary": 3, "n_baseline": 10}                     # too few: no statistic
    # open marks are not results on EITHER side
    opened = BOOT_TRADES + [{"net_r": 50.0, "entry_date": "2024-10-01", "reason": "open"}]
    assert BT.versus(opened, worse, boot=100, seed=4)["diff_r"] == 1.0


def test_random_draws_only_land_on_bars_the_rule_could_have_traded():
    """Audit 2026-09-28: the baseline used to draw from bar ~60 -- a coin's
    launch year and its illiquid stretches, regimes the rule can never trade.
    Every draw must now satisfy the rule's own preconditions (every input
    exists, both turnover floors pass, the screen could see the bar) and sit
    in the SAME season as the real trigger."""
    pr = prepared("gap_up")
    real = [t for t in BT.trades_for(pr, E.apply_rules(pr.bf, P())) if not t.get("skipped")]
    draws = BT.random_timing([pr], real, draws=200, seed=9, p=P())
    bf, p = pr.bf, P()
    assert draws
    for d in draws:
        t0 = d["_t0"]
        r = bf.iloc[t0]
        assert all(np.isfinite(r[k]) for k in ("ribbon", "atr_rank", "vol_rank", "drawdown",
                                                "base_high", "rvol", "ext", "trail"))
        assert r["turnover_base"] >= p.min_base_turnover
        assert r["turnover_day"] >= p.min_trigger_turnover
        assert t0 >= config.IGNITION_MIN_BARS - 1
        assert abs(t0 - real[0]["_t0"]) <= config.IGNITION_BT_RANDOM_WINDOW
    anyt = BT.random_timing([pr], real, draws=200, seed=9, p=P(), window=0)
    assert set(d["_t0"] for d in anyt) <= set(BT.eligible_bars(pr, P()).tolist())


def test_random_timing_is_seeded_per_symbol_and_trigger_by_crc32():
    df = fx("gap_up")
    pr = prepared("gap_up")
    real = [t for t in BT.trades_for(pr, E.apply_rules(pr.bf, P())) if not t.get("skipped")]
    a = BT.random_timing([pr], real, draws=7, seed=5, p=P())
    assert a == BT.random_timing([pr], real, draws=7, seed=5, p=P())
    assert a != BT.random_timing([pr], real, draws=7, seed=6, p=P())
    assert len(a) == 7 and all(r["symbol"] == "QNT" for r in a)
    # the documented seeding, reproduced: identical in ANY process (crc32, not hash())
    ok = BT.eligible_bars(pr, P())
    near = ok[np.abs(ok - real[0]["_t0"]) <= config.IGNITION_BT_RANDOM_WINDOW]
    rng = np.random.default_rng(5 + zlib.crc32(f"QNT|{real[0]['trigger_date']}".encode()))
    want = [_date(df.index[t0 + 1]) for t0 in rng.choice(near, size=7, replace=True)]
    assert [r["entry_date"] for r in a] == want
    # a symbol the replay never prepared is skipped, not an error
    assert BT.random_timing([pr], [{**real[0], "symbol": "ZZZ"}], draws=3, seed=5) == []


# ---------------------------------------------------------------------------
# the whole replay, through run.backtest_market with injected frames
# ---------------------------------------------------------------------------

BT_END = pd.Timestamp("2026-01-10")
BT_NOW = dt.datetime(2026, 1, 10, 12, 0, tzinfo=dt.timezone.utc)   # the 10th is still forming


def _bt_inputs():
    q = redate(fx("gap_up"), BT_END)
    a = redate(fx("gap_below"), BT_END)
    b = redate(_btc(len(q)), BT_END)
    frames = {"QNT-USD": q, "AAA-USD": a, "BTC-USD": b}
    rows = [{"yf": "QNT-USD", "symbol": "QNT"}, {"yf": "AAA-USD", "symbol": "AAA"},
            {"yf": "BTC-USD", "symbol": "BTC"}]
    return frames, rows


@pytest.fixture(scope="module")
def bt_payload():
    frames, rows = _bt_inputs()
    return RUN.backtest_market(MARKET, frames=frames, rows=rows, now=BT_NOW)


def test_backtest_market_replays_completed_bars_only(bt_payload):
    frames, _ = _bt_inputs()
    q = frames["QNT-USD"]
    assert bt_payload["lens"] == "ignition" and bt_payload["market"] == MARKET
    assert bt_payload["ruleset_version"] == config.IGNITION_RULESET_VERSION
    assert bt_payload["generated_at"] == BT_NOW.isoformat(timespec="seconds")
    # the forming bar of the run day is not history
    assert bt_payload["date_range"][1] == _date(BT_END - pd.Timedelta(days=1))
    assert bt_payload["universe"] == 3 and bt_payload["symbols_replayed"] == 3
    trades = bt_payload["trades"]
    assert [t["symbol"] for t in trades] == ["QNT"]
    t = trades[0]
    assert t["entry"] == q["Open"].iloc[T + 1] and t["entry_date"] == _date(q.index[T + 1])
    assert t["btc_up"] in (True, False)
    P_ = bt_payload["primary"]
    assert P_["n"] == 1 and P_["skipped"] == 1        # AAA's gap under the stop is COUNTED
    assert set(bt_payload["exits"]) == set(BT.EXIT_SPECS)
    assert bt_payload["sensitivity"]["full_grid"]["cells"] == 3 ** 5
    assert set(P_["by_btc_regime"]) <= {"btc_above_200", "btc_below_200", "unknown"}
    assert set(P_["by_split"]) <= {"in_sample", "out_of_sample", "forward"}
    assert "forward" in P_["by_split"]
    assert bt_payload["scoring"]["realised_only"] is True
    assert set(bt_payload["versus"]) >= {"random_timing", "breakout_only", "no_rvol",
                                         "random_timing_any", "random_timing_out_of_sample"}
    assert set(bt_payload["exit_specs"]) == set(BT.EXIT_SPECS)
    assert all(t["design_case"] is False for t in trades)     # 2022 trigger: before the window
    case = bt_payload["cases"]["QNT"]
    assert case["trades"] == trades
    assert len(case["recent_bars"]) == 30
    assert case["recent_bars"][-1]["date"] == _date(BT_END - pd.Timedelta(days=1))
    assert bt_payload["caveats"] and "SURVIVORSHIP" in bt_payload["caveats"][0]


def test_backtest_payload_is_publishable_json_with_no_nan(bt_payload):
    text = output.dumps(bt_payload)
    assert "NaN" not in text and "Infinity" not in text
    back = json.loads(text)
    assert back["trades"][0]["symbol"] == "QNT"
    lines = BT.summary_lines(bt_payload)
    assert lines and all(line.isascii() for line in lines)


def test_the_backtest_is_deterministic(bt_payload):
    frames, rows = _bt_inputs()
    again = RUN.backtest_market(MARKET, frames=frames, rows=rows, now=BT_NOW)
    strip = lambda p: {k: v for k, v in p.items() if k != "elapsed_s"}   # noqa: E731
    assert output.dumps(strip(again)) == output.dumps(strip(bt_payload))


def test_backtest_market_with_no_frames_is_none():
    assert RUN.backtest_market(MARKET, frames={}, rows=[], now=BT_NOW) is None


# ===========================================================================
# 8. run.py -- forming bars, the screen payload, the CLI
# ===========================================================================

def test_split_forming_for_crypto_is_the_UTC_date():
    df = redate(fx("base").iloc[:T + 1], "2026-09-27")
    done, forming = RUN.split_forming(df, MARKET, dt.datetime(2026, 9, 27, 23, 59, 59,
                                                              tzinfo=dt.timezone.utc))
    assert len(done) == T and len(forming) == 1 and forming.index[0] == pd.Timestamp("2026-09-27")
    done, forming = RUN.split_forming(df, MARKET, dt.datetime(2026, 9, 28, 0, 0, 0,
                                                              tzinfo=dt.timezone.utc))
    assert forming is None and len(done) == T + 1
    # 09:00 on the 28th in Melbourne is still the 27th in UTC: the bar is forming
    mel = dt.datetime(2026, 9, 28, 9, 0, tzinfo=ZoneInfo("Australia/Melbourne"))
    done, forming = RUN.split_forming(df, MARKET, mel)
    assert forming is not None and len(done) == T


def test_bar_is_forming_for_a_stock_session_ends_at_its_close():
    syd = ZoneInfo("Australia/Sydney")
    d = pd.Timestamp("2026-09-28")
    assert RUN.bar_is_forming("asx", d, dt.datetime(2026, 9, 28, 15, 59, tzinfo=syd)) is True
    assert RUN.bar_is_forming("asx", d, dt.datetime(2026, 9, 28, 16, 0, tzinfo=syd)) is False
    assert RUN.bar_is_forming("asx", d, dt.datetime(2026, 9, 29, 11, 0, tzinfo=syd)) is False


def _fresh_frames():
    """Frames whose last bar is YESTERDAY in UTC by the real clock (the tests
    that use them also pass the real clock as `now`)."""
    end = pd.Timestamp((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).date())
    frames = {
        "IGN-USD": redate(fx("base").iloc[:T + 1], end),
        "RUN-USD": redate(fx("base").iloc[:T + 6], end),
        "CLS-USD": redate(fx("failed").iloc[:T + 6], end),
        "COI-USD": redate(fx("short").iloc[:400], end),
        "NIL-USD": redate(fx("chop").iloc[:T], end),
        "YNG-USD": redate(fx("base").iloc[:300], end),
        "OLD-USD": redate(fx("base").iloc[:T + 1], "2021-06-01"),
    }
    rows = [{"yf": yf, "symbol": yf.split("-")[0] + "X", "name": "Name " + yf} for yf in frames]
    return frames, rows


def test_screen_market_with_injected_frames():
    frames, rows = _fresh_frames()
    now = dt.datetime.now(dt.timezone.utc)
    pl = RUN.screen_market(MARKET, frames=frames, rows=rows, now=now)
    assert [r["symbol"] for r in pl["results"]] == ["IGNX", "RUNX", "CLSX", "COIX"]
    assert [r["state"] for r in pl["results"]] == ["IGNITING", "RUNNING", "CLOSED", "COILED"]
    assert pl["results"][0]["name"] == "Name IGN-USD" and pl["results"][0]["yf"] == "IGN-USD"
    s = pl["summary"]
    assert s["screened"] == 5 and s["downloaded"] == 7 and s["universe"] == 7
    assert s["skipped"] == {"short history": 1, "stale frame": 1}
    assert s["counts"] == {"IGNITING": 1, "RUNNING": 1, "CLOSED": 1, "COILED": 1,
                           "provisional": 0, "igniting_confirmed": 1}
    assert s["errors"] == 0
    assert pl["report_only"] is True and pl["lens"] == "ignition"
    assert pl["last_closed_bar"] == _date(frames["IGN-USD"].index[-1])
    text = output.dumps(pl)
    assert "NaN" not in text and json.loads(text)["results"][0]["state"] == "IGNITING"


def test_screen_market_isolates_a_symbol_that_throws(monkeypatch):
    frames, rows = _fresh_frames()
    real = E.screen_frame

    poison = float(frames["RUN-USD"]["Close"].iloc[-1])

    def boom(df, market, **kw):
        if float(df["Close"].iloc[-1]) == poison:    # RUN-USD's frame only
            raise ValueError("synthetic failure")
        return real(df, market, **kw)

    monkeypatch.setattr(RUN.E, "screen_frame", boom)
    pl = RUN.screen_market(MARKET, frames=frames, rows=rows, now=dt.datetime.now(dt.timezone.utc))
    assert pl["summary"]["errors"] == 1
    assert "RUNX" not in [r["symbol"] for r in pl["results"]]
    assert "IGNX" in [r["symbol"] for r in pl["results"]]


def test_screen_market_with_no_frames_is_none():
    assert RUN.screen_market(MARKET, frames={}, rows=[]) is None


# WAS A BUG (fixed 2026-09-28): screen_market() takes an injectable `now`
# (used for the forming-bar split and generated_at) but its staleness gate
# reads the WALL CLOCK via data._frame_age_days, so a screen at an injected
# time skips every frame dated then as 'stale frame' -- the two clocks
# disagree inside one call.
def test_screen_market_judges_staleness_by_the_injected_clock():
    now = dt.datetime(2026, 1, 11, 6, 0, tzinfo=dt.timezone.utc)
    frames = {"IGN-USD": redate(fx("base").iloc[:T + 1], "2026-01-10")}
    pl = RUN.screen_market(MARKET, frames=frames, rows=[], now=now)
    assert pl["summary"]["screened"] == 1
    assert [r["state"] for r in pl["results"]] == ["IGNITING"]


# WAS A BUG (fixed 2026-09-28): run.py promises 'the page never says nothing
# is coiling when the truth is we could not look' (exit 3, last good file
# kept), but when EVERY frame is refused as stale -- e.g. a multi-day Yahoo
# outage served from the frame cache -- screen_market still returns a
# payload with 0 screened / 0 results, which main() publishes over the last
# good file.
def test_every_frame_stale_keeps_the_last_good_file():
    frames = {"OLD-USD": redate(fx("base").iloc[:T + 1], "2021-06-01"),
              "OLE-USD": redate(fx("short").iloc[:400], "2021-06-01")}
    assert RUN.screen_market(MARKET, frames=frames, rows=[],
                             now=dt.datetime.now(dt.timezone.utc)) is None


# ---------------------------------------------------------------------------
# run.main -- exit codes and the write-set
# ---------------------------------------------------------------------------

@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point the CLI's output at a temp tree so nothing in public/ is touched."""
    monkeypatch.setattr(RUN, "ROOT", tmp_path)
    monkeypatch.setattr(RUN, "OUT_DIR", tmp_path / "public" / "data" / "ignition")
    return tmp_path / "public" / "data" / "ignition"


def _files(d):
    return sorted(p.name for p in d.glob("*")) if d.exists() else []


def test_main_exit_3_when_screen_market_returns_none(sandbox, monkeypatch):
    monkeypatch.setattr(RUN, "screen_market", lambda *a, **k: None)
    assert RUN.main(["--market", MARKET]) == 3
    assert _files(sandbox) == []


def test_main_exit_3_when_the_download_is_empty(sandbox, monkeypatch):
    monkeypatch.setattr(RUN, "_download", lambda *a, **k: ([{"yf": "X-USD", "symbol": "X"}], {}, {}))
    assert RUN.main(["--market", MARKET]) == 3
    assert RUN.main(["--market", MARKET, "--backtest"]) == 3
    assert _files(sandbox) == []


def test_main_exit_1_on_an_exception(sandbox, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("yahoo on fire")
    monkeypatch.setattr(RUN, "_download", boom)
    assert RUN.main(["--market", MARKET]) == 1
    assert RUN.main(["--market", MARKET, "--backtest"]) == 1
    assert "::error::" in capsys.readouterr().out
    assert _files(sandbox) == []


def test_main_dry_run_screens_and_writes_nothing(sandbox, monkeypatch, capsys):
    frames, rows = _fresh_frames()
    monkeypatch.setattr(RUN, "_download", lambda *a, **k: (rows, frames, {}))
    monkeypatch.setattr(RUN.sdata, "merge_with_cache", lambda key, fr, t: (dict(fr), {}))

    def no_write(*a, **k):
        raise AssertionError("--dry-run wrote a file")
    monkeypatch.setattr(RUN.output, "write_json", no_write)
    assert RUN.main(["--market", MARKET, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "IGNITING 1" in out and "dry run" in out
    assert _files(sandbox) == []


def test_main_publishes_exactly_one_screen_file(sandbox, monkeypatch):
    frames, rows = _fresh_frames()
    monkeypatch.setattr(RUN, "_download", lambda *a, **k: (rows, frames, {}))
    monkeypatch.setattr(RUN.sdata, "merge_with_cache", lambda key, fr, t: (dict(fr), {}))
    assert RUN.main(["--market", MARKET]) == 0
    assert _files(sandbox) == [f"{MARKET}.json"]
    text = (sandbox / f"{MARKET}.json").read_text(encoding="utf-8")
    assert text.endswith("\n") and "NaN" not in text
    assert [r["state"] for r in json.loads(text)["results"]] == \
        ["IGNITING", "RUNNING", "CLOSED", "COILED"]


def test_main_backtest_publishes_only_the_backtest_file(sandbox, monkeypatch, bt_payload, capsys):
    monkeypatch.setattr(RUN, "backtest_market", lambda *a, **k: bt_payload)
    assert RUN.main(["--market", MARKET, "--backtest", "--dry-run"]) == 0
    assert "IGNITION backtest" in capsys.readouterr().out
    assert _files(sandbox) == []
    assert RUN.main(["--market", MARKET, "--backtest"]) == 0
    assert _files(sandbox) == [f"{MARKET}_backtest.json"]
    assert json.loads((sandbox / f"{MARKET}_backtest.json").read_text())["trades"][0]["symbol"] == "QNT"


def test_main_refuses_a_market_the_lens_does_not_cover():
    with pytest.raises(SystemExit) as e:
        RUN.main(["--market", "asx"])
    assert e.value.code == 2


# ---------------------------------------------------------------------------
# bar freshness -- measured, never assumed (first real run, 2026-09-28)
# ---------------------------------------------------------------------------

def test_bar_freshness_says_when_the_data_is_a_day_behind():
    """At 02:00 UTC on 28 Sep the first real screen was complete only through
    26 Sep: Yahoo had not yet served a usable 27 Sep row. The payload must
    SAY that, so the page can, instead of quietly screening a day late."""
    def f(end, n=5):
        idx = pd.date_range(end=end, periods=n, freq="D")
        return pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0,
                             "Volume": 1.0}, index=idx)
    now = dt.datetime(2026, 9, 28, 2, 0, tzinfo=dt.timezone.utc)
    frames = {"A-USD": f("2026-09-26"), "B-USD": f("2026-09-26"), "C-USD": f("2026-09-27")}
    forming = {"A-USD": f("2026-09-28", 1)}
    b = RUN.bar_freshness(frames, forming, MARKET, now)
    assert b["expected_completed"] == "2026-09-27"
    assert b["completed_last"] == "2026-09-27" and b["lagging"] == 2
    assert b["raw_last"] == "2026-09-28"
    assert b["completed_dist"] == {"2026-09-27": 1, "2026-09-26": 2}
    # a stock market's calendar is not this function's business
    assert RUN.bar_freshness(frames, {}, "asx", now)["expected_completed"] is None
    # A frame too old to be screened at all is the screen's "stale frame"
    # skip, not a coin "a day behind": it stays in the distribution only.
    frames["D-USD"] = f("2022-01-17")
    b = RUN.bar_freshness(frames, forming, MARKET, now)
    assert b["lagging"] == 2 and b["completed_dist"]["2022-01-17"] == 1


def test_the_screen_payload_carries_the_freshness_block():
    frames, rows = _fresh_frames()
    pl = RUN.screen_market(MARKET, frames=frames, rows=rows, now=dt.datetime.now(dt.timezone.utc))
    b = pl["summary"]["bars"]
    assert set(b) == {"completed_last", "raw_last", "expected_completed", "lagging",
                      "completed_dist", "raw_dist"}


def test_btc_regime_is_context_from_the_last_completed_bar():
    n = 260
    idx = pd.date_range(end="2026-09-27", periods=n, freq="D")
    up = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0,
                       "Close": np.linspace(100, 200, n), "Volume": 1.0}, index=idx)
    r = RUN.btc_regime({"BTC-USD": up})
    assert r["btc_above_200"] is True and r["as_of"] == "2026-09-27"
    assert r["btc_sma200"] == round(float(up["Close"].iloc[-200:].mean()), 2)
    down = up.assign(Close=np.linspace(200, 100, n))
    assert RUN.btc_regime({"BTC-USD": down})["btc_above_200"] is False
    assert RUN.btc_regime({}) is None
    assert RUN.btc_regime({"BTC-USD": up.iloc[:150]}) is None


def test_the_data_caveat_names_the_real_source():
    """The first exchange-data backtest still printed "Yahoo daily crypto
    bars" -- a hard-coded caveat describing the wrong feed. It is now written
    from the fetch report, and says what exchange volume does to the floors."""
    ex = RUN.data_note({"mode": "exchange",
                        "by_source": {"yahoo": 33, "binance_vision": 113, "coinbase": 13}})
    assert "binance_vision 113, yahoo 33, coinbase 13" in ex
    assert "one venue's" in ex and "Yahoo daily" not in ex
    assert RUN.data_note({"mode": "yahoo", "by_source": {"yahoo": 100}}).startswith("Yahoo daily")
    assert RUN.data_note({}).startswith("Yahoo daily")


def test_backtest_market_threads_the_data_note_into_the_caveats(monkeypatch):
    frames, rows = _bt_inputs()
    monkeypatch.setattr(RUN, "data_note", lambda sources: "NOTE-X")
    payload = RUN.backtest_market(MARKET, frames=frames, rows=rows, now=BT_NOW)
    assert "NOTE-X" in payload["caveats"]
    assert not any("Yahoo daily" in c for c in payload["caveats"])
