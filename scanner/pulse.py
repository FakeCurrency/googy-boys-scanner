"""PULSE — fetch the macro market indicators shown in the top bar.

Returns a list of {key, label, value, day_pct, d5_pct, spark[], dir} dicts.
Anything that fails to download is simply omitted.
"""

import pandas as pd
import yfinance as yf

from . import config


def _series(df) -> pd.Series | None:
    """Extract a clean Close series from a yfinance frame (single or grouped)."""
    try:
        if isinstance(df.columns, pd.MultiIndex):
            close = df.xs("Close", axis=1, level=-1).iloc[:, 0]
        else:
            close = df["Close"]
        close = close.dropna()
        return close if len(close) >= 6 else None
    except Exception:
        return None


def fetch() -> list[dict]:
    tickers = [row[2] for row in config.PULSE]
    try:
        data = yf.download(tickers, period="2mo", interval="1d",
                           group_by="ticker", auto_adjust=False,
                           threads=True, progress=False)
    except Exception:
        return []

    out: list[dict] = []
    for key, label, ticker, divide, decimals in config.PULSE:
        try:
            sub = data if len(tickers) == 1 else data[ticker]
            close = _series(sub)
            if close is None:
                continue
            # Yahoo sometimes quotes ^TNX (10Y) as yield×10; normalise to a real %.
            div = divide * 10 if (ticker == "^TNX" and float(close.iloc[-1]) > 15) else divide
            last = float(close.iloc[-1]) / div
            prev = float(close.iloc[-2]) / div
            ref5 = float(close.iloc[-6]) / div
            day_pct = (last - prev) / prev * 100 if prev else 0.0
            d5_pct = (last - ref5) / ref5 * 100 if ref5 else 0.0
            spark = [round(float(v) / div, 4) for v in close.iloc[-22:].tolist()]
            out.append({
                "key": key,
                "label": label,
                "ticker": ticker,
                "divide": div,
                "value": round(last, decimals),
                "decimals": decimals,
                "day_pct": round(day_pct, 2),
                "d5_pct": round(d5_pct, 2),
                "spark": spark,
                "dir": "up" if day_pct >= 0 else "down",
            })
        except Exception:
            continue
    return out
