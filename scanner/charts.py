"""Per-ticker chart data for the candlestick view.

For each setup we write public/data/charts/<market>/<SYMBOL>.json containing the
recent daily candles, the key EMAs, the SuperTrend line, marked price levels, and
the analysis text — everything the chart page needs, loaded on demand.
"""

import json
import pathlib
import shutil

from . import config
from .indicators import ema, supertrend

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


def chart_dir(out_root: str | pathlib.Path, market_key: str) -> pathlib.Path:
    return pathlib.Path(out_root) / "charts" / market_key


def reset_dir(out_root: str | pathlib.Path, market_key: str) -> None:
    """Clear stale chart files for a market before a fresh scan writes new ones."""
    d = chart_dir(out_root, market_key)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)


def write_chart(chart: dict, out_root: str | pathlib.Path, market_key: str) -> None:
    d = chart_dir(out_root, market_key)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{chart['symbol']}.json").write_text(json.dumps(chart), encoding="utf-8")
