"""Per-ticker chart data for the candlestick view.

For each setup we write public/data/charts/<market>/<SYMBOL>.json containing the
recent daily candles, the key EMAs, the SuperTrend line, marked price levels, and
the analysis text — everything the chart page needs, loaded on demand.
"""

import json
import pathlib
import shutil

from . import config
from .indicators import ema, sma, supertrend

CHART_BARS = 320   # ~14 months of daily candles


def build_chart(df, sig: dict, lv: dict, result: dict, market) -> dict:
    win = df.iloc[-CHART_BARS:]
    times = [d.date().isoformat() for d in win.index]

    def line(series):
        vals = series.iloc[-CHART_BARS:]
        return [{"time": t, "value": round(float(v), 4)}
                for t, v in zip(times, vals) if v == v]  # skip NaN

    candles = [{"time": t,
                "open": round(float(o), 4), "high": round(float(h), 4),
                "low": round(float(l), 4), "close": round(float(c), 4)}
               for t, o, h, l, c in zip(times, win["Open"], win["High"], win["Low"], win["Close"])]
    volume = [{"time": t, "value": int(v),
               "color": "rgba(47,208,127,0.5)" if c >= o else "rgba(255,91,91,0.5)"}
              for t, v, o, c in zip(times, win["Volume"], win["Open"], win["Close"])]

    levels = {
        "high": round(float(win["High"].max()), 4),
        "low": round(float(win["Low"].min()), 4),
        "resistance": lv["target"],
        "ema_watch": round(sig["ema_last"][sig["pullback_ema"]], 4),
        "stop": lv["stop"],
        "leg_low": round(float(df["Low"].iloc[-config.SWING_LOOKBACK:].min()), 4),
        "entry": lv["entry"],
        "target": lv["target"],
    }

    return {
        "symbol": result["symbol"], "name": result["name"], "market": market.key,
        "currency_symbol": market.currency_symbol, "sector": result.get("sector", ""),
        "grade": result["grade"], "dir": result["dir"], "price": result["price"],
        "chips": result["chips"], "score": result["score"], "score_max": result["score_max"],
        "rr": result["rr"], "low_rr": result["low_rr"], "rr_text": result["rr_text"],
        "risk_pct": result.get("detail", {}).get("risk_pct"),
        "analysis": result.get("analysis", ""),
        "tv_symbol": f"{market.label}:{result['symbol']}",
        "candles": candles,
        "volume": volume,
        "ema34": line(ema(df["Close"], 34)),
        "ema55": line(ema(df["Close"], 55)),
        "ema89": line(ema(df["Close"], 89)),
        "supertrend": line(supertrend(df, config.ATR_PERIOD, config.SUPERTREND_MULT)),
        "levels": levels,
    }


def build_chart_reversal(df, sig: dict, lv: dict, result: dict, market) -> dict:
    """Chart data for a reversal setup — SMA 9/26/43/200 lines + breakout levels."""
    win = df.iloc[-CHART_BARS:]
    times = [d.date().isoformat() for d in win.index]

    def line(series):
        vals = series.iloc[-CHART_BARS:]
        return [{"time": t, "value": round(float(v), 4)}
                for t, v in zip(times, vals) if v == v]

    candles = [{"time": t, "open": round(float(o), 4), "high": round(float(h), 4),
                "low": round(float(l), 4), "close": round(float(c), 4)}
               for t, o, h, l, c in zip(times, win["Open"], win["High"], win["Low"], win["Close"])]
    volume = [{"time": t, "value": int(v),
               "color": "rgba(47,208,127,0.5)" if c >= o else "rgba(255,91,91,0.5)"}
              for t, v, o, c in zip(times, win["Volume"], win["Open"], win["Close"])]

    lines = [
        {"name": "SMA 9", "color": "#e5e9f0", "data": line(sma(df["Close"], 9))},
        {"name": "SMA 26", "color": "#ffd23f", "data": line(sma(df["Close"], 26))},
        {"name": "SMA 43", "color": "#af52de", "data": line(sma(df["Close"], 43))},
        {"name": "SMA 200", "color": "#ff5b5b", "data": line(sma(df["Close"], 200))},
        {"name": "SuperTrend", "color": "#30b0c7", "data": line(supertrend(df, config.ATR_PERIOD, config.SUPERTREND_MULT))},
    ]
    level_lines = [
        {"price": lv["target"], "color": "#2fd07f", "title": "TARGET"},
        {"price": round(sig["base_high"], 4), "color": "#4d9fff", "title": "BASE HIGH"},
        {"price": lv["entry"], "color": "#cbd5e1", "title": "ENTRY"},
        {"price": round(sig["sma"][200], 4), "color": "#ff9500", "title": "200 SMA"},
        {"price": lv["stop"], "color": "#ff5b5b", "title": "STOP"},
    ]
    return {
        "symbol": result["symbol"], "name": result["name"], "market": market.key,
        "currency_symbol": market.currency_symbol, "sector": result.get("sector", ""),
        "grade": result["grade"], "dir": result["dir"], "price": result["price"],
        "chips": result["chips"], "score": result["score"], "score_max": result["score_max"],
        "rr": result["rr"], "low_rr": result["low_rr"], "rr_text": result["rr_text"],
        "risk_pct": result.get("detail", {}).get("risk_pct"),
        "analysis": result.get("analysis", ""),
        "tv_symbol": f"{market.label}:{result['symbol']}",
        "candles": candles, "volume": volume,
        "lines": lines, "level_lines": level_lines,
    }


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
        return  # can't write e.g. CON.json on Windows; skip its chart
    d = chart_dir(out_root, market_key)
    d.mkdir(parents=True, exist_ok=True)
    try:
        (d / f"{symbol}.json").write_text(json.dumps(chart), encoding="utf-8")
    except OSError:
        pass  # best-effort: a bad filename just means no chart for that ticker
