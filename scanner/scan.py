"""Orchestration: download -> indicators -> signals -> grade -> rank, per market."""

import datetime as dt
from collections import Counter
from zoneinfo import ZoneInfo

from . import config, levels, pulse, signals
from .data import download
from .universe import load_universe

GRADE_RANK = {"A+": 0, "A": 1, "B": 2, "C": 3}


def _liquidity(df) -> float:
    turnover = (df["Close"] * df["Volume"]).iloc[-config.LIQUIDITY_LOOKBACK:].mean()
    return float(turnover)


def _build_chips(fired: list[str], sig: dict) -> list[str]:
    """Turn fired signal keys into display chips, with dynamic detail where shown."""
    chips: list[str] = []
    for key in fired:
        if key == "pullback":
            chips.append(f"CORE FIB PULLBACK EMA_{sig['pullback_ema']}")
        elif key == "confluence" and sig.get("confluence_level"):
            chips.append(f"STRONG FIB CONFLUENCE @ {round(sig['confluence_level'], 4)}")
        else:
            chips.append(signals.CHIP_BASE[key])
    return chips


def _spark(df) -> list[float]:
    closes = df["Close"].iloc[-config.SPARK_BARS:].tolist()
    return [round(float(c), 4) for c in closes]


def scan_market(market_key: str, limit: int | None = None,
                full: bool = True, progress: bool = True) -> dict:
    market = config.MARKETS[market_key]
    liquid_tier = config.LIQUID_TIER.get(market_key, float("inf"))
    universe = load_universe(market_key, full=full)
    if limit:
        universe = universe[:limit]

    tickers = [u["yf"] for u in universe]
    meta = {u["yf"]: u for u in universe}

    if progress:
        print(f"  downloading {len(tickers)} {market.label} tickers ...", flush=True)
    frames = download(tickers)

    results: list[dict] = []
    scanned = 0
    for yf_ticker, df in frames.items():
        scanned += 1
        sig = signals.evaluate(df)
        if sig is None or not sig["uptrend"]:
            continue

        turnover = _liquidity(df)
        if turnover < market.liquidity_min:
            continue

        points, grade, fired = signals.score_and_grade(sig)
        if grade is None:
            continue

        lv = levels.compute_levels(df, sig)
        if lv["rr"] <= 0:
            continue

        info = meta.get(yf_ticker, {})
        close = sig["close"]
        open_ = float(df["Open"].iloc[-1])
        y_close = float(df["Close"].iloc[-2])
        trail = lv["trail"]

        results.append({
            "symbol": info.get("symbol", yf_ticker),
            "name": info.get("name", yf_ticker),
            "sector": info.get("sector", ""),
            "dir": "LONG",
            "grade": grade,
            "score": points,
            "score_max": config.SCORE_MAX,
            "chips": _build_chips(fired, sig),
            "weekly": sig["weekly"],
            "low_rr": lv["rr"] < config.LOW_RR_THRESHOLD,
            "rr_text": f"{lv['rr']:.1f}:1",
            "target_2r": lv["target_basis"] == "measured",
            "liquidity": "LIQUID" if turnover >= liquid_tier else "OK",
            "price": round(close, 4),
            "y_close": round(y_close, 4),
            "open": round(open_, 4),
            "open_pct": round((open_ - y_close) / y_close * 100, 2) if y_close else 0.0,
            "current_pct": round((close - open_) / open_ * 100, 2) if open_ else 0.0,
            "day_pct": round((close - y_close) / y_close * 100, 2) if y_close else 0.0,
            "entry": lv["entry"],
            "stop": lv["stop"],
            "target": lv["target"],
            "rr": lv["rr"],
            "trail": trail,
            "stop_pct": round((close - lv["stop"]) / close * 100, 1) if close else 0.0,
            "p2_pct": round((close - trail) / close * 100, 1) if (close and trail < close) else None,
            "target_basis": lv["target_basis"],
            "spark": _spark(df),
            "trend": "green" if points >= 10 else "blue",
            "turnover": round(turnover),
        })

    # Sector counts across all results, attached to each row (e.g. "MATERIALS x16").
    sector_counts = Counter(r["sector"] for r in results if r["sector"])
    for r in results:
        r["sector_count"] = sector_counts.get(r["sector"], 0)

    results.sort(key=lambda r: (GRADE_RANK.get(r["grade"], 9), -r["score"], -r["rr"]))

    if progress:
        print("  fetching market pulse ...", flush=True)
    pulse_data = pulse.fetch()

    now = dt.datetime.now(ZoneInfo(market.timezone))
    return {
        "market": market.key,
        "label": market.label,
        "currency": market.currency,
        "currency_symbol": market.currency_symbol,
        "timezone": market.timezone,
        "tz_label": market.tz_label,
        "generated_at": now.isoformat(timespec="seconds"),
        "scanned": scanned,
        "universe_size": len(universe),
        "score_max": config.SCORE_MAX,
        "ema_periods": config.EMA_PERIODS,
        "pulse": pulse_data,
        "sector_counts": dict(sector_counts.most_common()),
        "results": results,
    }
