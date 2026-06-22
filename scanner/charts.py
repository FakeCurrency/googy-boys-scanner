"""Per-ticker chart data for the candlestick view.

For each setup we write public/data/charts/<market>/<SYMBOL>.json with the price
candles and the *user's own indicators* (EMA/SMA + SuperTrend) computed on every
timeframe — Daily, 3-Day, Weekly, Monthly, 3-Month — by resampling the daily
data, plus the marked entry/stop/target levels. The chart page switches between
timeframes client-side, always showing the same system.
"""

import json
import pathlib
import shutil

from . import config
from .indicators import ema, sma, supertrend

# (label, pandas resample rule [None = daily], max candles to send)
TIMEFRAMES = [
    ("1D", None, 500),    # ≈ 2 years of daily bars
    ("3D", "3D", 320),    # ≈ 2.6 years
    ("1W", "W-FRI", 260), # ≈ 5 years
    ("1M", "ME", 150),    # ≈ 12.5 years
    ("3M", "QE", 80),     # ≈ 20 years
]
_AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


def _tv(market, symbol: str) -> str:
    """TradingView symbol for the Open-in-TradingView link."""
    if market.key == "crypto":
        return f"CRYPTO:{symbol}USD"
    return f"{market.label}:{symbol}"


def _resample(df, rule):
    if rule is None:
        return df
    return df.resample(rule).agg(_AGG).dropna(subset=["Open", "High", "Low", "Close"])


def _tf_block(df, rule, n_bars, kind):
    """Candles + volume + the user's indicator lines for one timeframe."""
    r = _resample(df, rule)
    if len(r) < 6:
        return None
    times = [d.date().isoformat() for d in r.index][-n_bars:]
    win = r.iloc[-n_bars:]

    candles = [{"time": t, "open": round(float(o), 8), "high": round(float(h), 8),
                "low": round(float(l), 8), "close": round(float(c), 8)}
               for t, o, h, l, c in zip(times, win["Open"], win["High"], win["Low"], win["Close"])]
    volume = [{"time": t, "value": int(v),
               "color": "rgba(47,208,127,0.5)" if c >= o else "rgba(255,91,91,0.5)"}
              for t, v, o, c in zip(times, win["Volume"], win["Open"], win["Close"])]

    close = r["Close"]

    def line(name, color, series):
        s = series.iloc[-n_bars:]
        return {"name": name, "color": color,
                "data": [{"time": t, "value": round(float(v), 8)}
                         for t, v in zip(times, s) if v == v]}

    st = line("SuperTrend", "#30b0c7", supertrend(r, config.ATR_PERIOD, config.SUPERTREND_MULT))
    if kind == "pullback":
        lines = [line("EMA 34", "#2fd07f", ema(close, 34)),
                 line("EMA 55", "#4d9fff", ema(close, 55)),
                 line("EMA 89", "#a78bfa", ema(close, 89)), st]
    else:
        lines = [line("SMA 9", "#e5e9f0", sma(close, 9)),
                 line("SMA 26", "#ffd23f", sma(close, 26)),
                 line("SMA 43", "#a78bfa", sma(close, 43)),
                 line("SMA 200", "#ff5b5b", sma(close, 200)), st]
    return {"candles": candles, "volume": volume, "lines": lines}


def _timeframes(df, kind):
    out = {}
    for label, rule, n in TIMEFRAMES:
        blk = _tf_block(df, rule, n, kind)
        if blk:
            out[label] = blk
    return out


def _meta(result, market):
    return {
        "symbol": result["symbol"], "name": result["name"], "market": market.key,
        "currency_symbol": market.currency_symbol, "sector": result.get("sector", ""),
        "grade": result["grade"], "dir": result["dir"], "price": result["price"],
        "chips": result["chips"], "score": result["score"], "score_max": result["score_max"],
        "rr": result["rr"], "low_rr": result["low_rr"], "rr_text": result["rr_text"],
        "risk_pct": result.get("detail", {}).get("risk_pct"),
        "analysis": result.get("analysis", ""),
        "tv_symbol": _tv(market, result["symbol"]),
        "entry": result["entry"], "stop": result["stop"], "target": result["target"],
        "default_tf": "1D",
    }


def build_chart(df, sig: dict, lv: dict, result: dict, market) -> dict:
    """Pullback setup chart — EMA 34/55/89 + SuperTrend across timeframes."""
    win = df.iloc[-config.SWING_LOOKBACK:]
    level_lines = [
        {"price": round(float(df["High"].iloc[-260:].max()), 8), "color": "#2fd0c4", "title": "HIGH"},
        {"price": lv["target"], "color": "#4d9fff", "title": "RESISTANCE"},
        {"price": round(sig["ema_last"][sig["pullback_ema"]], 8), "color": "#cbd5e1", "title": "EMA WATCH"},
        {"price": lv["entry"], "color": "#e5e9f0", "title": "ENTRY"},
        {"price": round(float(win["Low"].min()), 8), "color": "#f5a623", "title": "LEG LOW"},
        {"price": lv["stop"], "color": "#ff5b5b", "title": "STOP"},
    ]
    return {**_meta(result, market), "level_lines": level_lines, "timeframes": _timeframes(df, "pullback")}


def build_chart_reversal(df, sig: dict, lv: dict, result: dict, market) -> dict:
    """Reversal setup chart — SMA 9/26/43/200 + SuperTrend across timeframes."""
    level_lines = [
        {"price": lv["target"], "color": "#2fd07f", "title": "TARGET"},
        {"price": round(sig["base_high"], 8), "color": "#4d9fff", "title": "BASE HIGH"},
        {"price": lv["entry"], "color": "#e5e9f0", "title": "ENTRY"},
        {"price": round(sig["sma"][200], 8), "color": "#ff9500", "title": "200 SMA"},
        {"price": lv["stop"], "color": "#ff5b5b", "title": "STOP"},
    ]
    return {**_meta(result, market), "level_lines": level_lines, "timeframes": _timeframes(df, "reversal")}


def build_chart_short(df, sig: dict, lv: dict, result: dict, market) -> dict:
    """Short pullback chart — EMA 34/55/89 + SuperTrend. Stop above entry, target below."""
    win = df.iloc[-config.SWING_LOOKBACK:]
    level_lines = [
        {"price": round(float(win["High"].max()), 8), "color": "#ff9500", "title": "LEG HIGH"},
        {"price": lv["stop"],   "color": "#ff5b5b", "title": "STOP"},
        {"price": lv["entry"],  "color": "#e5e9f0", "title": "ENTRY"},
        {"price": round(float(df["Low"].iloc[-260:].min()), 8), "color": "#2fd0c4", "title": "LOW"},
        {"price": lv["target"], "color": "#2fd07f", "title": "TARGET"},
    ]
    return {**_meta(result, market), "level_lines": level_lines, "timeframes": _timeframes(df, "pullback")}


def chart_dir(out_root: str | pathlib.Path, market_key: str) -> pathlib.Path:
    return pathlib.Path(out_root) / "charts" / market_key


def reset_dir(out_root: str | pathlib.Path, market_key: str) -> None:
    """Clear stale chart files for a market before a fresh scan writes new ones."""
    d = chart_dir(out_root, market_key)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)


# Windows reserved device names — a ticker that matches one can't be a filename.
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL",
                 *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def write_chart(chart: dict, out_root: str | pathlib.Path, market_key: str) -> None:
    symbol = str(chart["symbol"])
    if symbol.upper() in _WIN_RESERVED:
        return
    d = chart_dir(out_root, market_key)
    d.mkdir(parents=True, exist_ok=True)
    try:
        (d / f"{symbol}.json").write_text(json.dumps(chart), encoding="utf-8")
    except OSError:
        pass
