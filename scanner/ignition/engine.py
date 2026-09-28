"""IGNITION engine -- pure maths shared by the live screen AND the replay.

ONE IMPLEMENTATION, TWO READERS, ON PURPOSE. The screen reads the LAST bar of
these series and the backtest reads EVERY bar of the same series, so the rule
the page shows and the rule the evidence measures cannot drift apart: there is
no second copy to drift. `simulate()` is shared the same way -- the page's
"RUNNING / CLOSED" outcome and the replay's trade outcome are one function.

CAUSAL BY CONSTRUCTION. Every column at row t is computed from bars <= t:
rolling windows end at t, `shift(1)` is used wherever a quantity must describe
the bars BEFORE the trigger (the base, the prior volume average, the
pre-trigger ATR), and the percentile ranks are rolling ranks of the current
value inside its trailing window. `tests/test_ignition.py` proves it the only
way that counts: truncate a frame at every bar and assert the truncated
computation reproduces the full one exactly.

No clock, no network, no file I/O (fenced by tests/test_ignition_fences.py).
Every threshold is a `config.IGNITION_*` constant, carried in `Params` so the
backtest can vary one without editing the rule.

The coil (all four on one bar):
    ribbon   max/min of SMA 9/26/43/200 - 1          <= IGNITION_RIBBON_MAX
    quiet    ATR%-of-price, percentile in its year   <= IGNITION_ATR_PCTL_MAX
    dry      20d avg volume, percentile in its year  <= IGNITION_VOL_PCTL_MAX
    deep     1 - close / 3y max High                 >= IGNITION_MIN_DRAWDOWN

The trigger (on a completed bar t):
    coiled on any of bars t-L .. t-1 (L = IGNITION_COIL_LOOKBACK)
    close > the base's highest high (base = the IGNITION_BASE_BARS before t)
    volume >= IGNITION_RVOL_MIN x its average over the 20 bars before t
    close <= (1 + IGNITION_MAX_EXT) x 9-SMA              (not already chased)
    20d avg $ volume before t, and $ volume on t, clear the market's floors
    no raw trigger in the IGNITION_REARM_BARS before t   (one per move)

The plan:
    stop   = max(base low, base high - IGNITION_STOP_ATR_MULT x ATR at t-1)
    target = base high + (base high - base low)          (measured move, shown)
    exit   = the stop intrabar, else the next open after a daily close below
             the IGNITION_TRAIL_SMA -- no fixed ladder (see config for why)
"""

from __future__ import annotations

import dataclasses
from typing import Optional

import numpy as np
import pandas as pd

from scanner import config
from scanner.indicators import atr as calc_atr
from scanner.indicators import sma

_COLS = ("Open", "High", "Low", "Close", "Volume")


@dataclasses.dataclass(frozen=True)
class Params:
    """Every rule threshold, defaulted from config. Frozen: a variant is a
    `dataclasses.replace`, never a mutation, so a grid cell cannot leak into
    the next one."""
    ribbon_max: float
    atr_pctl_max: float
    vol_pctl_max: float
    min_drawdown: float
    coil_lookback: int
    breakout_tol: float
    rvol_min: float
    max_ext: float
    min_base_turnover: float
    min_trigger_turnover: float
    rearm_bars: int
    stop_atr_mult: float
    require_coil: bool = True      # False = the "breakout-only" ablation
    require_rvol: bool = True      # False = the "no volume confirmation" ablation

    @classmethod
    def from_config(cls, market: str) -> "Params":
        floor = float(getattr(config.MARKETS.get(market), "liquidity_min", 0.0) or 0.0)
        return cls(
            ribbon_max=float(config.IGNITION_RIBBON_MAX),
            atr_pctl_max=float(config.IGNITION_ATR_PCTL_MAX),
            vol_pctl_max=float(config.IGNITION_VOL_PCTL_MAX),
            min_drawdown=float(config.IGNITION_MIN_DRAWDOWN),
            coil_lookback=int(config.IGNITION_COIL_LOOKBACK),
            breakout_tol=float(config.IGNITION_BREAKOUT_TOL),
            rvol_min=float(config.IGNITION_RVOL_MIN),
            max_ext=float(config.IGNITION_MAX_EXT),
            min_base_turnover=float(config.IGNITION_MIN_BASE_TURNOVER.get(market, floor)),
            min_trigger_turnover=float(config.IGNITION_MIN_TRIGGER_TURNOVER.get(market, floor)),
            rearm_bars=int(config.IGNITION_REARM_BARS),
            stop_atr_mult=float(config.IGNITION_STOP_ATR_MULT),
        )

    def replace(self, **kw) -> "Params":
        return dataclasses.replace(self, **kw)

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCV as float, sorted, de-duplicated, rows without a usable close
    dropped. A frame lacking a column is returned EMPTY rather than guessed."""
    if df is None or len(df) == 0 or any(col not in df.columns for col in _COLS):
        return pd.DataFrame(columns=list(_COLS))
    out = df.loc[:, list(_COLS)].astype(float)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    good = np.isfinite(out["Close"].to_numpy()) & (out["Close"].to_numpy() > 0)
    out = out[good]
    out["Volume"] = out["Volume"].fillna(0.0).clip(lower=0.0)
    # A missing O/H/L on an otherwise good bar reads as the close: a doji is a
    # truthful floor, a NaN would silently fail every comparison it meets.
    for col in ("Open", "High", "Low"):
        out[col] = out[col].where(np.isfinite(out[col]), out["Close"])
    return out


def dollar_volume(df: pd.DataFrame, market: str) -> pd.Series:
    """Traded value per bar in the quote currency. Crypto's Yahoo volume is
    ALREADY dollars (config.MARKETS[...].volume_is_usd); a stock's is shares."""
    mkt = config.MARKETS.get(market)
    vol = df["Volume"].astype(float)
    if mkt is not None and getattr(mkt, "volume_is_usd", False):
        return vol
    return df["Close"].astype(float) * vol


def base_features(df: pd.DataFrame, market: str) -> pd.DataFrame:
    """Every threshold-FREE series the rules read, one row per bar, causal.

    Split from `apply_rules` so the backtest's sensitivity grid re-thresholds
    these without recomputing the rolling ranks (the expensive part).
    """
    c, h, lo, v = df["Close"], df["High"], df["Low"], df["Volume"]
    smas = pd.concat({n: sma(c, n) for n in config.IGNITION_RIBBON_SMAS}, axis=1)
    # skipna=False: during the 200-SMA warm-up the ribbon does not EXIST yet;
    # a max over the three short SMAs alone would read as a tight ribbon.
    ribbon = smas.max(axis=1, skipna=False) / smas.min(axis=1, skipna=False) - 1.0

    a = calc_atr(df, config.IGNITION_ATR_LEN)
    atr_pct = a / c
    w, mp = config.IGNITION_RANK_WINDOW, config.IGNITION_RANK_MIN_PERIODS
    atr_rank = atr_pct.rolling(w, min_periods=mp).rank(pct=True)
    vavg = v.rolling(config.IGNITION_VOL_AVG_LEN,
                     min_periods=config.IGNITION_VOL_AVG_LEN).mean()
    vol_rank = vavg.rolling(w, min_periods=mp).rank(pct=True)

    hmax = h.rolling(config.IGNITION_DD_LOOKBACK,
                     min_periods=config.IGNITION_DD_MIN_PERIODS).max()
    drawdown = 1.0 - c / hmax

    nb = config.IGNITION_BASE_BARS
    base_high = h.shift(1).rolling(nb, min_periods=nb).max()
    base_low = lo.shift(1).rolling(nb, min_periods=nb).min()

    n = config.IGNITION_RVOL_LEN
    prev_vavg = v.shift(1).rolling(n, min_periods=n).mean()
    rvol = v / prev_vavg.where(prev_vavg > 0)

    dv = dollar_volume(df, market)
    turnover_base = dv.shift(1).rolling(n, min_periods=n).mean()

    return pd.DataFrame({
        "open": df["Open"], "high": h, "low": lo, "close": c,
        "ribbon": ribbon, "atr": a, "atr_prev": a.shift(1),
        "atr_rank": atr_rank, "vol_rank": vol_rank, "drawdown": drawdown,
        "base_high": base_high, "base_low": base_low,
        "rvol": rvol, "turnover_base": turnover_base, "turnover_day": dv,
        "ext": c / sma(c, config.IGNITION_EXT_SMA) - 1.0,
        "trail": sma(c, config.IGNITION_TRAIL_SMA),
    }, index=df.index)


def _any_prior(flags: pd.Series, lookback: int) -> pd.Series:
    """True at t when `flags` was True on any of bars t-lookback .. t-1."""
    prior = flags.astype(float).shift(1).rolling(max(int(lookback), 1),
                                                 min_periods=1).max()
    return prior.fillna(0.0) > 0


def _run_length(flags: pd.Series) -> pd.Series:
    """Consecutive True count ending at each bar (0 where False)."""
    f = flags.astype(int)
    groups = (f != f.shift()).cumsum()
    return f.groupby(groups).cumsum() * f


def apply_rules(bf: pd.DataFrame, p: Params) -> pd.DataFrame:
    """The coil / trigger booleans and the plan levels for every bar.

    NaN comparisons are False in pandas, so a warm-up bar can never be coiled
    and never trigger -- the rule is silent until every input exists.
    """
    coiled = ((bf["ribbon"] <= p.ribbon_max)
              & (bf["atr_rank"] <= p.atr_pctl_max)
              & (bf["vol_rank"] <= p.vol_pctl_max)
              & (bf["drawdown"] >= p.min_drawdown))
    coil_window = _any_prior(coiled, p.coil_lookback)
    # "coil_open" at T: a trigger on bar T+1 would count (coiled on T+1-L..T).
    coil_open = coiled.astype(float).rolling(max(p.coil_lookback, 1),
                                             min_periods=1).max().fillna(0.0) > 0

    # Every coil INPUT exists (not: the coil holds). Applied to every rule,
    # so the breakout-only ablation drops the coil CONDITION and nothing else
    # -- without it the ablation also trades a coin's launch year, which the
    # rule can never reach, and "does the coil matter?" would mix two effects.
    inputs_ready = (bf["ribbon"].notna() & bf["atr_rank"].notna()
                    & bf["vol_rank"].notna() & bf["drawdown"].notna())
    breakout = bf["close"] > bf["base_high"] * (1.0 + p.breakout_tol)
    raw = (breakout
           & inputs_ready
           & (bf["ext"] <= p.max_ext)
           & (bf["turnover_base"] >= p.min_base_turnover)
           & (bf["turnover_day"] >= p.min_trigger_turnover))
    if p.require_rvol:
        raw &= bf["rvol"] >= p.rvol_min
    if p.require_coil:
        raw &= coil_window
    trigger = raw & ~_any_prior(raw, p.rearm_bars)

    stop = np.maximum(bf["base_low"], bf["base_high"] - p.stop_atr_mult * bf["atr_prev"])
    return pd.DataFrame({
        "inputs_ready": inputs_ready,
        "coiled": coiled, "coil_window": coil_window, "coil_open": coil_open,
        "coiled_run": _run_length(coiled),
        "breakout": breakout, "raw_trigger": raw, "trigger": trigger,
        "stop": stop,
        "mm_target": bf["base_high"] + (bf["base_high"] - bf["base_low"]),
    }, index=bf.index)


def compute(df: pd.DataFrame, market: str, p: Optional[Params] = None) -> pd.DataFrame:
    """base_features + apply_rules, joined. The one call the screen makes."""
    p = p or Params.from_config(market)
    bf = base_features(df, market)
    return bf.join(apply_rules(bf, p))


# ── the exit walk: ONE function for the page's outcome and the replay's ──────

def simulate(o, h, lo, c, trail, *, start: int, entry: float, stop: float,
             ladder: tuple = (), max_hold: int = 0, stop_first: bool = True) -> dict:
    """Walk bars start.. forward from a long entry and return how it ended.

    Arrays are plain numpy (speed: the replay calls this thousands of times).
    `ladder` is ((fraction, price), ...) take-profits; whatever fraction they
    do not cover rides the trail. Per bar, in this order:

      1. the stop, intrabar: low <= stop fills at the stop, or at the open when
         the bar opens THROUGH it (a gap is not the stop's price). Checked
         before any target on the same bar -- the conservative ordering; a bar
         that touches both is booked as the stop.
      2. ladder targets: high >= price fills at the price, or at the open when
         the bar gaps above it.
      3. the trail: a CLOSE below trail[j] exits the rest at the NEXT open.
         On the last bar there is no next open -> `pending` (the page says
         "exit signal"; the replay books the close and says so).
      4. max_hold (bars since start, 0 = none): exit the rest at the close.
    Runs off the end of the data -> reason "open", marked at the last close.
    """
    n = len(c)
    remaining = 1.0
    fills = []                   # (fraction, price, bar, reason)
    hit = [False] * len(ladder)
    mfe, mae = entry, entry
    j = start
    while j < n:
        if lo[j] <= stop:
            px = o[j] if o[j] <= stop else stop
            # The stop bar: the order of events inside it is unknowable, and
            # the stop-first rule already assumed the worst. So only the OPEN
            # (a price certainly traded while held) can lift MFE, and MAE
            # ends at the FILL -- a low beyond the stop was never lived
            # through. Counting the bar's high here once booked a gap-to-loss
            # as "+2R MFE".
            mfe = max(mfe, o[j])
            mae = min(mae, px)
            fills.append((remaining, px, j, "stop"))
            return _outcome(fills, entry, stop, j, "stop", mfe, mae, start)
        mfe = max(mfe, h[j])
        mae = min(mae, lo[j])
        for k, (frac, price) in enumerate(ladder):
            if not hit[k] and h[j] >= price and remaining > 1e-12:
                take = min(frac, remaining)
                fills.append((take, max(price, o[j]) if o[j] >= price else price, j, "target"))
                remaining -= take
                hit[k] = True
        if remaining <= 1e-12:
            return _outcome(fills, entry, stop, j, "target", mfe, mae, start)
        tj = trail[j]
        if np.isfinite(tj) and c[j] < tj:
            if j + 1 < n:
                fills.append((remaining, o[j + 1], j + 1, "trail"))
                # Out at the open: only the OPEN of the exit bar was lived
                # through, never its high or low.
                mfe = max(mfe, o[j + 1])
                mae = min(mae, o[j + 1])
                return _outcome(fills, entry, stop, j + 1, "trail", mfe, mae, start)
            fills.append((remaining, c[j], j, "trail"))
            out = _outcome(fills, entry, stop, j, "trail", mfe, mae, start)
            out["pending"] = True
            return out
        if max_hold and (j - start + 1) >= max_hold:
            fills.append((remaining, c[j], j, "time"))
            return _outcome(fills, entry, stop, j, "time", mfe, mae, start)
        j += 1
    last = n - 1
    fills.append((remaining, c[last] if n else entry, last, "open"))
    return _outcome(fills, entry, stop, last, "open", mfe, mae, start)


def _outcome(fills, entry, stop, exit_bar, reason, mfe, mae, start) -> dict:
    risk = entry - stop
    gross = sum(frac * (px - entry) for frac, px, _, _ in fills)
    avg_exit = sum(frac * px for frac, px, _, _ in fills) / max(sum(f for f, *_ in fills), 1e-12)
    return {
        "exit_bar": int(exit_bar), "reason": reason, "pending": False,
        "exit_price": float(avg_exit),
        "gross_r": float(gross / risk) if risk > 0 else float("nan"),
        "mfe_r": float((mfe - entry) / risk) if risk > 0 else float("nan"),
        "mae_r": float((entry - mae) / risk) if risk > 0 else float("nan"),
        "bars": int(exit_bar - start + 1),
        "fills": [(float(f), float(px), int(b), r) for f, px, b, r in fills],
    }


# ── the live row ─────────────────────────────────────────────────────────────

def _f(x, nd=6):
    """float -> rounded float, non-finite -> None (the publisher nulls NaN
    anyway; doing it here keeps the row honest for in-memory readers too)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return (round(x, nd) + 0.0) if np.isfinite(x) else None   # + 0.0: no "-0.0"


def _coil_block(feat: pd.DataFrame, i: int) -> dict:
    r = feat.iloc[i]
    return {
        "ribbon_pct": _f(r["ribbon"] * 100, 2),
        "atr_pctl": _f(r["atr_rank"] * 100, 1),
        "vol_pctl": _f(r["vol_rank"] * 100, 1),
        "drawdown_pct": _f(r["drawdown"] * 100, 1),
        "coiled": bool(r["coiled"]),
        "coiled_bars": int(r["coiled_run"]),
    }


def _date(idx) -> str:
    try:
        return pd.Timestamp(idx).strftime("%Y-%m-%d")
    except Exception:
        return str(idx)


def _trigger_row(df: pd.DataFrame, feat: pd.DataFrame, t0: int, market: str) -> dict:
    """Everything the page says about a trigger at bar t0, plus how the
    primary exit rule has treated it since (completed bars only).

    THE ENTRY IS THE REPLAY'S ENTRY. Once the bar after the trigger exists,
    the trade is priced from ITS OPEN -- the fill the backtest books -- so the
    R on the page and the R in the evidence are one number, not two (the
    audit measured up to 0.36R between them when the page used the trigger
    close). Until that bar exists the trigger close is the only reference,
    and `entry_basis` says which one a row is using. A next open at or under
    the stop is no trade at all, exactly as the replay skips it.
    """
    r = feat.iloc[t0]
    trig_close, stop = float(r["close"]), float(r["stop"])
    o, h, lo, c = (feat[k].to_numpy() for k in ("open", "high", "low", "close"))
    trail = feat["trail"].to_numpy()
    T = len(feat) - 1
    if T > t0:
        entry, basis = float(o[t0 + 1]), "next_open"
    else:
        entry, basis = trig_close, "trigger_close"
    risk = entry - stop
    mm = float(r["mm_target"])
    out = {
        "trigger_date": _date(feat.index[t0]),
        "trigger_close": _f(trig_close, 8),
        "entry": _f(entry, 8),
        "entry_basis": basis,
        "entry_date": _date(feat.index[t0 + 1]) if T > t0 else None,
        "bars_since": int(T - t0),
        "rvol": _f(r["rvol"], 2),
        "ext_pct": _f(r["ext"] * 100, 1),
        "turnover_trigger": _f(r["turnover_day"], 0),
        "turnover_base": _f(r["turnover_base"], 0),
        "base": {"high": _f(r["base_high"], 8), "low": _f(r["base_low"], 8),
                 "bars": int(config.IGNITION_BASE_BARS),
                 "range_pct": _f((r["base_high"] / r["base_low"] - 1) * 100, 1)},
        "stop": _f(stop, 8),
        "risk_pct": _f(risk / entry * 100, 1) if entry > 0 and risk > 0 else None,
        "wide_stop": bool(entry > 0 and risk / entry * 100 > config.IGNITION_WIDE_STOP_PCT),
        "mm_target": _f(mm, 8),
        # A trigger candle taller than the base overshoots its own measured
        # move; a "target" under the entry is not a target, so say so plainly.
        "mm_passed": bool(np.isfinite(mm) and mm <= entry),
        "mm_r": (_f((mm - entry) / risk, 2)
                 if risk > 0 and np.isfinite(mm) and mm > entry else None),
        "coil": _coil_block(feat, max(t0 - 1, 0)),
    }
    if not risk > 0:
        # Gapped to (or through) the stop at the open: the setup failed
        # before it could be entered. The replay counts it as skipped.
        out["mfe_r"] = None
        out["exit_reason"] = "gap_below_stop"
        out["exit_date"] = out["entry_date"]
        out["exit_price"] = _f(entry, 8)
        out["exit_r"] = None
        out["exit_pending"] = False
        return out
    if T > t0:
        sim = simulate(o, h, lo, c, trail, start=t0 + 1, entry=entry, stop=stop)
        out["mfe_r"] = _f(sim["mfe_r"], 2)
        if sim["reason"] in ("stop", "trail"):
            out["exit_reason"] = sim["reason"]
            out["exit_date"] = _date(feat.index[sim["exit_bar"]])
            out["exit_price"] = _f(sim["exit_price"], 8)
            out["exit_r"] = _f(sim["gross_r"], 2)
            out["exit_pending"] = bool(sim["pending"])
    else:
        out["mfe_r"] = 0.0
    return out


def screen_frame(df: pd.DataFrame, market: str, *, forming: Optional[pd.DataFrame] = None,
                 p: Optional[Params] = None) -> Optional[dict]:
    """The live row for one symbol, or None when it is none of the states.

    `df` must hold COMPLETED bars only; the caller drops the forming bar and
    may pass it as `forming` (one row). States, first match wins:

      IGNITING  a trigger on one of the last IGNITION_FRESH_BARS completed bars
                that the exit rule has not closed
      RUNNING   a trigger 2..IGNITION_KEEP_BARS-1 bars back, still open
      CLOSED    a trigger inside the keep window that the rule has closed --
                kept on the page ON PURPOSE: a list of only the winners is the
                survivorship this lens was built to stop fooling us with
      COILED    no recent trigger, and a trigger on the NEXT bar would count

    `provisional` = the FORMING bar is the trigger. Never a confirmed state:
    QNT's own 23 Sep poke above the base closed back inside it.
    """
    p = p or Params.from_config(market)
    df = clean(df)
    if len(df) < config.IGNITION_MIN_BARS:
        return None
    feat = compute(df, market, p)
    T = len(feat) - 1
    keep = max(int(config.IGNITION_KEEP_BARS), 1)
    trig_pos = np.flatnonzero(feat["trigger"].to_numpy()[max(0, T - keep + 1):])
    row: Optional[dict] = None
    if len(trig_pos):
        t0 = max(0, T - keep + 1) + int(trig_pos[-1])
        row = _trigger_row(df, feat, t0, market)
        if "exit_reason" in row:
            row["state"] = "CLOSED"
        elif T - t0 < int(config.IGNITION_FRESH_BARS):
            row["state"] = "IGNITING"
        else:
            row["state"] = "RUNNING"
    elif bool(feat["coil_open"].iloc[-1]):
        row = {"state": "COILED", "coil": _coil_block(feat, T)}
        last_coiled = np.flatnonzero(feat["coiled"].to_numpy())
        row["coil"]["last_coiled"] = _date(feat.index[last_coiled[-1]]) if len(last_coiled) else None
        row["base"] = {"high": _f(feat["base_high"].iloc[-1], 8),
                       "low": _f(feat["base_low"].iloc[-1], 8),
                       "bars": int(config.IGNITION_BASE_BARS)}
        # The base the NEXT bar would have to clear: this bar's high joins it.
        nb = int(config.IGNITION_BASE_BARS)
        nxt = df["High"].iloc[-nb:].max() if len(df) >= nb else np.nan
        row["breakout_level"] = _f(nxt, 8)

    price = float(df["Close"].iloc[-1])
    provisional = False
    if forming is not None and len(forming) and (row is None or row["state"] in ("COILED", "CLOSED")):
        both = clean(pd.concat([df, clean(forming)]))
        if len(both) == len(df) + 1:
            f2 = compute(both, market, p)
            price = float(both["Close"].iloc[-1])
            if bool(f2["trigger"].iloc[-1]):
                row = _trigger_row(both, f2, len(f2) - 1, market)
                row["state"] = "IGNITING"
                provisional = True
    elif forming is not None and len(forming):
        fc = clean(forming)
        if len(fc):
            price = float(fc["Close"].iloc[-1])

    if row is None:
        return None
    row["provisional"] = provisional
    row["last_bar"] = _date(df.index[-1])
    row["price"] = _f(price, 8)
    if row["state"] in ("IGNITING", "RUNNING", "CLOSED") and row.get("entry"):
        en, st = row["entry"], row.get("stop")
        row["change_pct"] = _f((price / en - 1) * 100, 1)
        if st is not None and en - st > 0:
            row["r_now"] = _f((price - en) / (en - st), 2)
        row["trail"] = _f(feat["trail"].iloc[-1], 8)
    return row


def state_rank(row: dict) -> tuple:
    """Page order: IGNITING, RUNNING, CLOSED, COILED; freshest / strongest first."""
    order = {"IGNITING": 0, "RUNNING": 1, "CLOSED": 2, "COILED": 3}
    st = row.get("state")
    if st in ("IGNITING", "RUNNING", "CLOSED"):
        return (order[st], int(row.get("provisional", False)), row.get("bars_since", 99),
                -(row.get("rvol") or 0))
    coil = row.get("coil") or {}
    return (order.get(st, 9), 0, -(coil.get("coiled_bars") or 0), coil.get("ribbon_pct") or 99)
