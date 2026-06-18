"""Orchestration: download -> indicators -> signals -> grade -> rank, per market."""

import datetime as dt
from collections import Counter
from zoneinfo import ZoneInfo

from . import analysis, charts, config, levels, pulse, reversal, scalp, short, signals, spec
from .data import download
from .universe import load_scalp_universe, load_universe

GRADE_RANK = {"A+": 0, "A": 1, "B": 2, "C": 3}


def _liquidity(df, market) -> float:
    # Crypto: Yahoo "Volume" is already USD dollar-volume; stocks: price * shares.
    if getattr(market, "volume_is_usd", False):
        return float(df["Volume"].iloc[-config.LIQUIDITY_LOOKBACK:].mean())
    turnover = (df["Close"] * df["Volume"]).iloc[-config.LIQUIDITY_LOOKBACK:].mean()
    return float(turnover)


def _build_chips(fired: list[str], sig: dict) -> list[str]:
    """Turn fired signal keys into display chips, with dynamic detail where shown."""
    chips: list[str] = []
    for key in fired:
        if key == "pullback":
            chips.append(f"CORE FIB PULLBACK EMA_{sig['pullback_ema']}")
        elif key == "confluence" and sig.get("confluence_level"):
            chips.append(f"STRONG FIB CONFLUENCE @ {round(sig['confluence_level'], 8)}")
        else:
            chips.append(signals.CHIP_BASE[key])
    return chips


def _spark(df) -> list[float]:
    closes = df["Close"].iloc[-config.SPARK_BARS:].tolist()
    return [round(float(c), 8) for c in closes]


def scan_market(market_key: str, limit: int | None = None, full: bool = True,
                write_charts: bool = True, out_root: str | None = None,
                progress: bool = True, frames: dict | None = None,
                pulse_data: list | None = None, universe: list | None = None) -> dict:
    market = config.MARKETS[market_key]
    liquid_tier = config.LIQUID_TIER.get(market_key, float("inf"))
    if universe is None:
        universe = load_universe(market_key, full=full)
        if limit:
            universe = universe[:limit]

    tickers = [u["yf"] for u in universe]
    meta = {u["yf"]: u for u in universe}

    if frames is None:
        if progress:
            print(f"  downloading {len(tickers)} {market.label} tickers ...", flush=True)
        frames = download(tickers)

    if write_charts and out_root:
        charts.reset_dir(out_root, market_key)

    results: list[dict] = []
    scanned = 0
    for yf_ticker, df in frames.items():
        scanned += 1
        sig = signals.evaluate(df)
        if sig is None or not sig["uptrend"]:
            continue

        turnover = _liquidity(df, market)
        if turnover < market.liquidity_min:
            continue

        points, grade, fired = signals.score_and_grade(sig)
        if grade is None:
            continue

        lv = levels.compute_levels(df, sig)
        if lv["rr"] <= 0:
            continue

        # Tuning toward R:R — a tradeable grade must clear the minimum reward-to-risk,
        # otherwise it's a strong pattern but a poor trade, so demote it to the watch list.
        if config.DEMOTE_LOW_RR and grade in config.TRADEABLE_GRADES \
                and lv["rr"] < config.MIN_TRADEABLE_RR:
            grade = "B"

        info = meta.get(yf_ticker, {})
        close = sig["close"]
        open_ = float(df["Open"].iloc[-1])
        y_close = float(df["Close"].iloc[-2])
        entry = lv["entry"]

        detail = analysis.build_detail(df, sig, lv)
        row = {
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
            "price": round(close, 8),
            "y_close": round(y_close, 8),
            "open": round(open_, 8),
            "open_pct": round((open_ - y_close) / y_close * 100, 2) if y_close else 0.0,
            "current_pct": round((close - open_) / open_ * 100, 2) if open_ else 0.0,
            "day_pct": round((close - y_close) / y_close * 100, 2) if y_close else 0.0,
            "entry": entry,
            "stop": lv["stop"],
            "target": lv["target"],
            "rr": lv["rr"],
            "trail": lv["trail"],
            # Stop% = risk to stop, P2% = reward to target — both from entry (R:R = P2/Stop).
            "stop_pct": round((entry - lv["stop"]) / entry * 100, 1) if entry else 0.0,
            "p2_pct": round((lv["target"] - entry) / entry * 100, 1) if entry else None,
            "target_basis": lv["target_basis"],
            "spark": _spark(df),
            "trend": "green" if points >= 10 else "blue",
            "turnover": round(turnover),
            "detail": detail,
            "analysis": analysis.narrative(info.get("symbol", yf_ticker), sig, lv, detail,
                                           market.currency_symbol),
        }
        results.append(row)

        if write_charts and out_root:
            charts.write_chart(charts.build_chart(df, sig, lv, row, market), out_root, market_key)

    # Sector counts across all results, attached to each row (e.g. "MATERIALS x16").
    sector_counts = Counter(r["sector"] for r in results if r["sector"])
    for r in results:
        r["sector_count"] = sector_counts.get(r["sector"], 0)

    results.sort(key=lambda r: (GRADE_RANK.get(r["grade"], 9), -r["score"], -r["rr"]))

    if pulse_data is None:
        if progress:
            print("  fetching market pulse ...", flush=True)
        pulse_data = pulse.fetch()

    now = dt.datetime.now(ZoneInfo(market.timezone))
    return {
        "market": market.key,
        "label": market.label,
        "setup_type": "pullback",
        "currency": market.currency,
        "currency_symbol": market.currency_symbol,
        "timezone": market.timezone,
        "tz_label": market.tz_label,
        "generated_at": now.isoformat(timespec="seconds"),
        "scanned": scanned,
        "universe_size": len(universe),
        "universe_tickers": [u.get("symbol", u.get("yf", "")) for u in universe],
        "score_max": config.SCORE_MAX,
        "ema_periods": config.EMA_PERIODS,
        "pulse": pulse_data,
        "sector_counts": dict(sector_counts.most_common()),
        "results": results,
    }


def scan_reversal_market(market_key: str, limit: int | None = None, full: bool = True,
                         write_charts: bool = True, out_root: str | None = None,
                         progress: bool = True, frames: dict | None = None,
                         pulse_data: list | None = None, universe: list | None = None) -> dict:
    """Scan a market for early reversal / base-breakout setups (the 'Reversals' tab)."""
    market = config.MARKETS[market_key]
    liquid_tier = config.LIQUID_TIER.get(market_key, float("inf"))
    if universe is None:
        universe = load_universe(market_key, full=full)
        if limit:
            universe = universe[:limit]

    meta = {u["yf"]: u for u in universe}
    if frames is None:
        frames = download([u["yf"] for u in universe])

    chart_key = f"{market_key}_rev"
    if write_charts and out_root:
        charts.reset_dir(out_root, chart_key)

    results: list[dict] = []
    scanned = 0
    for yf_ticker, df in frames.items():
        scanned += 1
        sig = reversal.evaluate(df)
        if sig is None or not sig.get("ok"):
            continue

        turnover = _liquidity(df, market)
        if turnover < market.liquidity_min:
            continue

        points, grade, fired = reversal.score_and_grade(sig)
        if grade is None:
            continue

        lv = reversal.compute_levels(df, sig)
        if lv["rr"] <= 0:
            continue

        info = meta.get(yf_ticker, {})
        close = sig["close"]
        open_ = float(df["Open"].iloc[-1])
        y_close = float(df["Close"].iloc[-2])
        entry = lv["entry"]

        detail = reversal.build_detail(df, sig, lv)
        row = {
            "symbol": info.get("symbol", yf_ticker),
            "name": info.get("name", yf_ticker),
            "sector": info.get("sector", ""),
            "dir": "LONG",
            "setup_type": "reversal",
            "grade": grade,
            "score": points,
            "score_max": config.REV_SCORE_MAX,
            "chips": reversal.build_chips(fired, sig),
            "weekly": False,
            "low_rr": lv["rr"] < config.LOW_RR_THRESHOLD,
            "rr_text": f"{lv['rr']:.1f}:1",
            "target_2r": lv["target_basis"] == "measured",
            "liquidity": "LIQUID" if turnover >= liquid_tier else "OK",
            "price": round(close, 8),
            "y_close": round(y_close, 8),
            "open": round(open_, 8),
            "open_pct": round((open_ - y_close) / y_close * 100, 2) if y_close else 0.0,
            "current_pct": round((close - open_) / open_ * 100, 2) if open_ else 0.0,
            "day_pct": round((close - y_close) / y_close * 100, 2) if y_close else 0.0,
            "entry": entry,
            "stop": lv["stop"],
            "target": lv["target"],
            "rr": lv["rr"],
            "trail": lv["trail"],
            "stop_pct": round((entry - lv["stop"]) / entry * 100, 1) if entry else 0.0,
            "p2_pct": round((lv["target"] - entry) / entry * 100, 1) if entry else None,
            "target_basis": lv["target_basis"],
            "spark": _spark(df),
            "trend": "green" if points >= 11 else "blue",
            "turnover": round(turnover),
            "detail": detail,
            "analysis": reversal.narrative(info.get("symbol", yf_ticker), sig, lv, detail,
                                           market.currency_symbol),
        }
        results.append(row)

        if write_charts and out_root:
            charts.write_chart(charts.build_chart_reversal(df, sig, lv, row, market),
                               out_root, chart_key)

    sector_counts = Counter(r["sector"] for r in results if r["sector"])
    for r in results:
        r["sector_count"] = sector_counts.get(r["sector"], 0)

    results.sort(key=lambda r: (GRADE_RANK.get(r["grade"], 9), -r["score"], -r["rr"]))

    if pulse_data is None:
        pulse_data = pulse.fetch()

    now = dt.datetime.now(ZoneInfo(market.timezone))
    return {
        "market": market.key,
        "label": market.label,
        "setup_type": "reversal",
        "currency": market.currency,
        "currency_symbol": market.currency_symbol,
        "timezone": market.timezone,
        "tz_label": market.tz_label,
        "generated_at": now.isoformat(timespec="seconds"),
        "scanned": scanned,
        "universe_size": len(universe),
        "score_max": config.REV_SCORE_MAX,
        "sma_periods": config.REV_SMAS,
        "pulse": pulse_data,
        "sector_counts": dict(sector_counts.most_common()),
        "results": results,
    }


def scan_spec_market(market_key: str, limit: int | None = None, full: bool = True,
                     write_charts: bool = True, out_root: str | None = None,
                     progress: bool = True, frames: dict | None = None,
                     pulse_data: list | None = None, universe: list | None = None) -> dict:
    """Scan a market for speculative volume-spike breakouts (the 'Specs' tab)."""
    market = config.MARKETS[market_key]
    liquid_tier = config.LIQUID_TIER.get(market_key, float("inf"))
    if universe is None:
        universe = load_universe(market_key, full=full)
        if limit:
            universe = universe[:limit]

    meta = {u["yf"]: u for u in universe}
    if frames is None:
        frames = download([u["yf"] for u in universe])

    chart_key = f"{market_key}_spec"
    if write_charts and out_root:
        charts.reset_dir(out_root, chart_key)

    # price cap applies to real stocks; disabled for crypto (per-coin price is meaningless)
    max_price = None if getattr(market, "volume_is_usd", False) else config.SPEC_MAX_PRICE

    results: list[dict] = []
    scanned = 0
    for yf_ticker, df in frames.items():
        scanned += 1
        sig = spec.evaluate(df, max_price=max_price)
        if sig is None or not sig.get("ok"):
            continue

        turnover = _liquidity(df, market)
        if turnover < market.liquidity_min:
            continue

        points, grade, fired = spec.score_and_grade(sig)
        if grade is None:
            continue

        lv = spec.compute_levels(df, sig)
        if lv["rr"] <= 0:
            continue

        info = meta.get(yf_ticker, {})
        close = sig["close"]
        open_ = float(df["Open"].iloc[-1])
        y_close = float(df["Close"].iloc[-2])
        entry = lv["entry"]

        detail = spec.build_detail(df, sig, lv)
        row = {
            "symbol": info.get("symbol", yf_ticker),
            "name": info.get("name", yf_ticker),
            "sector": info.get("sector", ""),
            "dir": "LONG",
            "setup_type": "spec",
            "grade": grade,
            "score": points,
            "score_max": config.SPEC_SCORE_MAX,
            "chips": spec.build_chips(fired, sig),
            "weekly": False,
            "low_rr": lv["rr"] < config.LOW_RR_THRESHOLD,
            "rr_text": f"{lv['rr']:.1f}:1",
            "target_2r": lv["target_basis"] == "measured",
            "liquidity": "LIQUID" if turnover >= liquid_tier else "OK",
            "price": round(close, 8),
            "y_close": round(y_close, 8),
            "open": round(open_, 8),
            "open_pct": round((open_ - y_close) / y_close * 100, 2) if y_close else 0.0,
            "current_pct": round((close - open_) / open_ * 100, 2) if open_ else 0.0,
            "day_pct": round((close - y_close) / y_close * 100, 2) if y_close else 0.0,
            "entry": entry,
            "stop": lv["stop"],
            "target": lv["target"],
            "rr": lv["rr"],
            "trail": lv["trail"],
            "stop_pct": round((entry - lv["stop"]) / entry * 100, 1) if entry else 0.0,
            "p2_pct": round((lv["target"] - entry) / entry * 100, 1) if entry else None,
            "target_basis": lv["target_basis"],
            "spark": _spark(df),
            "trend": "green" if points >= 8 else "blue",
            "turnover": round(turnover),
            "detail": detail,
            "analysis": spec.spec_narrative(info.get("symbol", yf_ticker), sig, lv, detail,
                                            market.currency_symbol),
        }
        results.append(row)

        if write_charts and out_root:
            charts.write_chart(charts.build_chart_reversal(df, sig, lv, row, market),
                               out_root, chart_key)

    sector_counts = Counter(r["sector"] for r in results if r["sector"])
    for r in results:
        r["sector_count"] = sector_counts.get(r["sector"], 0)

    results.sort(key=lambda r: (GRADE_RANK.get(r["grade"], 9), -r["score"], -r["rr"]))

    if pulse_data is None:
        pulse_data = pulse.fetch()

    now = dt.datetime.now(ZoneInfo(market.timezone))
    return {
        "market": market.key,
        "label": market.label,
        "setup_type": "spec",
        "currency": market.currency,
        "currency_symbol": market.currency_symbol,
        "timezone": market.timezone,
        "tz_label": market.tz_label,
        "generated_at": now.isoformat(timespec="seconds"),
        "scanned": scanned,
        "universe_size": len(universe),
        "score_max": config.SPEC_SCORE_MAX,
        "sma_periods": config.SPEC_SMAS,
        "pulse": pulse_data,
        "sector_counts": dict(sector_counts.most_common()),
        "results": results,
    }


def scan_short_market(market_key: str, limit: int | None = None, full: bool = True,
                      write_charts: bool = False, out_root: str | None = None,
                      progress: bool = True, frames: dict | None = None,
                      pulse_data: list | None = None, universe: list | None = None) -> dict:
    """Scan a market for bearish pullback (short) setups — the Shorts tab."""
    market = config.MARKETS[market_key]
    liquid_tier = config.LIQUID_TIER.get(market_key, float("inf"))
    if universe is None:
        universe = load_universe(market_key, full=full)
        if limit:
            universe = universe[:limit]

    meta = {u["yf"]: u for u in universe}
    if frames is None:
        frames = download([u["yf"] for u in universe])

    results: list[dict] = []
    scanned = 0
    for yf_ticker, df in frames.items():
        scanned += 1
        sig = short.evaluate(df)
        if sig is None:
            continue

        turnover = _liquidity(df, market)
        if turnover < market.liquidity_min:
            continue

        points, grade, fired = short.score_and_grade(sig)
        if grade is None:
            continue

        lv = short.compute_levels(df, sig)
        if lv["rr"] <= 0:
            continue

        if config.DEMOTE_LOW_RR and grade in config.TRADEABLE_GRADES \
                and lv["rr"] < config.MIN_TRADEABLE_RR:
            grade = "B"

        info = meta.get(yf_ticker, {})
        close = sig["close"]
        open_ = float(df["Open"].iloc[-1])
        y_close = float(df["Close"].iloc[-2])
        entry = lv["entry"]

        row = {
            "symbol": info.get("symbol", yf_ticker),
            "name": info.get("name", yf_ticker),
            "sector": info.get("sector", ""),
            "dir": "SHORT",
            "setup_type": "short",
            "grade": grade,
            "score": points,
            "score_max": short.SHORT_SCORE_MAX,
            "chips": short.build_chips(fired, sig),
            "weekly": sig["weekly_bearish"],
            "low_rr": lv["rr"] < config.LOW_RR_THRESHOLD,
            "rr_text": f"{lv['rr']:.1f}:1",
            "target_2r": lv["target_basis"] == "measured",
            "liquidity": "LIQUID" if turnover >= liquid_tier else "OK",
            "price": round(close, 8),
            "y_close": round(y_close, 8),
            "open": round(open_, 8),
            "open_pct": round((open_ - y_close) / y_close * 100, 2) if y_close else 0.0,
            "current_pct": round((close - open_) / open_ * 100, 2) if open_ else 0.0,
            "day_pct": round((close - y_close) / y_close * 100, 2) if y_close else 0.0,
            "entry": entry,
            "stop": lv["stop"],
            "target": lv["target"],
            "rr": lv["rr"],
            "trail": lv["trail"],
            "stop_pct": round((lv["stop"] - entry) / entry * 100, 1) if entry else 0.0,
            "p2_pct": round((entry - lv["target"]) / entry * 100, 1) if entry else None,
            "target_basis": lv["target_basis"],
            "spark": _spark(df),
            "trend": "green" if points >= 10 else "blue",
            "turnover": round(turnover),
            "detail": [],
            "analysis": short.narrative(info.get("symbol", yf_ticker), sig, lv,
                                        market.currency_symbol),
        }
        results.append(row)

    sector_counts = Counter(r["sector"] for r in results if r["sector"])
    for r in results:
        r["sector_count"] = sector_counts.get(r["sector"], 0)

    results.sort(key=lambda r: (GRADE_RANK.get(r["grade"], 9), -r["score"], -r["rr"]))

    if pulse_data is None:
        pulse_data = pulse.fetch()

    now = dt.datetime.now(ZoneInfo(market.timezone))
    return {
        "market": market.key,
        "label": market.label,
        "setup_type": "short",

        "currency": market.currency,
        "currency_symbol": market.currency_symbol,
        "timezone": market.timezone,
        "tz_label": market.tz_label,
        "generated_at": now.isoformat(timespec="seconds"),
        "scanned": scanned,
        "universe_size": len(universe),
        "score_max": short.SHORT_SCORE_MAX,
        "ema_periods": config.EMA_PERIODS,
        "pulse": pulse_data,
        "sector_counts": dict(sector_counts.most_common()),
        "results": results,
    }


def scan_scalp(progress: bool = True, out_root: str | None = None) -> dict:
    """Cross-asset intraday scalp scan on 1h bars (commodities + ASX + NASDAQ)."""
    import json as _json
    import pathlib as _pathlib
    import shutil as _shutil

    universe = load_scalp_universe()
    tickers  = [u["yf"] for u in universe]
    meta     = {u["yf"]: u for u in universe}

    if progress:
        print(f"  downloading {len(tickers)} scalp tickers (1h) ...", flush=True)
    frames = download(tickers, period="60d", interval="1h", chunk=30)

    if out_root:
        chart_dir = _pathlib.Path(out_root) / "charts" / "scalp"
        if chart_dir.exists():
            _shutil.rmtree(chart_dir, ignore_errors=True)
        chart_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    scanned = 0
    for yf_ticker, df in frames.items():
        scanned += 1
        info = meta.get(yf_ticker, {})
        asset_type = info.get("type", "")

        for direction in ("long", "short"):
            sig = scalp.evaluate(df, direction=direction)
            if sig is None:
                continue
            points, grade, fired = scalp.score_and_grade(sig)
            if grade is None:
                continue
            lv = scalp.compute_levels(df, sig)
            if lv["rr"] <= 0:
                continue

            entry = lv["entry"]
            if direction == "long":
                stop_pct = round((entry - lv["stop"]) / entry * 100, 1) if entry else 0.0
                p2_pct   = round((lv["target"] - entry) / entry * 100, 1) if entry else None
            else:
                stop_pct = round((lv["stop"] - entry) / entry * 100, 1) if entry else 0.0
                p2_pct   = round((entry - lv["target"]) / entry * 100, 1) if entry else None

            cur = "$" if asset_type != "asx" else "A$"
            close = sig["close"]
            spark = [round(float(c), 8) for c in df["Close"].iloc[-30:].tolist()]

            results.append({
                "symbol":      info.get("symbol", yf_ticker),
                "name":        info.get("name", yf_ticker),
                "sector":      info.get("sector", ""),
                "asset_type":  asset_type,
                "dir":         direction.upper(),
                "grade":       grade,
                "score":       points,
                "score_max":   scalp.SCALP_SCORE_MAX,
                "chips":       scalp.build_chips(fired, sig),
                "weekly":      sig.get("squeeze_fired", False),
                "low_rr":      lv["rr"] < 1.5,
                "rr_text":     f"{lv['rr']:.1f}:1",
                "target_2r":   False,
                "liquidity":   "LIQUID",
                "price":       round(close, 8),
                "y_close":     round(close, 8),
                "open":        round(close, 8),
                "open_pct":    0.0,
                "current_pct": 0.0,
                "day_pct":     0.0,
                "entry":       entry,
                "stop":        lv["stop"],
                "target":      lv["target"],
                "rr":          lv["rr"],
                "trail":       lv["stop"],
                "stop_pct":    stop_pct,
                "p2_pct":      p2_pct,
                "target_basis": "atr",
                "spark":       spark,
                "trend":       "green" if points >= 8 else "blue",
                "turnover":    0,
                "detail":      scalp.build_detail(df, sig, lv),
                "analysis":    scalp.narrative(
                    info.get("symbol", yf_ticker), sig, lv, asset_type, cur),
            })

            if out_root:
                chips = scalp.build_chips(fired, sig)
                cd = scalp.build_chart_data(df, sig, lv, info, points, grade, chips)
                chart_name = f"{info.get('symbol', yf_ticker)}_{direction}"
                try:
                    (chart_dir / f"{chart_name}.json").write_text(
                        _json.dumps(cd), encoding="utf-8")
                except OSError:
                    pass

    results.sort(key=lambda r: (GRADE_RANK.get(r["grade"], 9), -r["score"], -r["rr"]))

    now = dt.datetime.now(dt.timezone.utc)
    return {
        "market":         "scalp",
        "label":          "SCALP",
        "setup_type":     "scalp",
        "currency":       "USD",
        "currency_symbol": "$",
        "timezone":       "UTC",
        "tz_label":       "UTC",
        "generated_at":   now.isoformat(timespec="seconds"),
        "timeframe":      "1h",
        "scanned":        scanned,
        "universe_size":  len(universe),
        "score_max":      scalp.SCALP_SCORE_MAX,
        "brokerage":      config.SCALP_BROKERAGE_EACH_WAY,
        "position_size":  config.SCALP_POSITION_SIZE,
        "leverage":       config.SCALP_LEVERAGE,
        "max_daily_trades": config.SCALP_MAX_TRADES_PER_DAY,
        "pulse":          [],
        "results":        results,
    }
