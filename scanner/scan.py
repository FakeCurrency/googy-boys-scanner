"""Orchestration: download -> indicators -> signals -> grade -> rank, per market."""

import datetime as dt
import json
import logging
import pathlib
import shutil
import time as _time
import uuid as _uuid
from collections import Counter
from zoneinfo import ZoneInfo

from . import analysis, charts, config, levels, pulse, reversal, scalp, short, signals, spec
from .data import download, validate_bars, DataQualityError
from .universe import load_scalp_universe, load_universe

log = logging.getLogger(__name__)

GRADE_RANK = {"A+": 0, "A": 1, "B": 2, "C": 3}


def _pct(new: float, old: float, dp: int = 2) -> float:
    """Percent change of `new` vs `old`, rounded; 0.0 when `old` is missing/zero."""
    return round((new - old) / old * 100, dp) if old else 0.0


def _dir_pcts(entry: float, stop: float, target: float, direction: str) -> tuple[float, float | None]:
    """Return (stop_pct, p2_pct) measured from entry, signed for the trade direction.

    Long: stop is below entry, target above. Short: the mirror. p2_pct is None
    when entry is missing/zero (matches the live JSON the site already consumes).
    """
    if not entry:
        return 0.0, None
    if direction == "long":
        return round((entry - stop) / entry * 100, 1), round((target - entry) / entry * 100, 1)
    return round((stop - entry) / entry * 100, 1), round((entry - target) / entry * 100, 1)


def _finalize(results: list[dict]) -> Counter:
    """Attach per-row sector counts, then rank by grade -> score -> R:R (in place).

    Returns the sector Counter so the caller can embed it in the payload.
    """
    counts = Counter(r["sector"] for r in results if r["sector"])
    for r in results:
        r["sector_count"] = counts.get(r["sector"], 0)
    results.sort(key=lambda r: (GRADE_RANK.get(r["grade"], 9), -r["score"], -r["rr"]))
    return counts


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


def _write_extended_charts(
    pending: list[tuple],
    scan_frames: dict,
    chart_key: str,
    out_root: str,
    builder,
    market,
) -> None:
    """Fetch extended history for chart-qualifying tickers, then write chart files.

    Uses config.CHART_PERIOD so weekly/monthly/quarterly frames get full history.
    Falls back silently to the scan-period data if the extended download fails.
    """
    if not pending:
        return
    tickers = [t for t, *_ in pending]
    try:
        ext = download(tickers, period=config.CHART_PERIOD)
    except Exception:
        ext = {}
    for yf_ticker, sig, lv, row in pending:
        df_chart = ext.get(yf_ticker) or scan_frames.get(yf_ticker)
        if df_chart is None or len(df_chart) < 6:
            continue
        try:
            charts.write_chart(builder(df_chart, sig, lv, row, market), out_root, chart_key)
        except Exception:
            pass


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
    pending_charts: list[tuple] = []
    scanned = 0
    for yf_ticker, df in frames.items():
        scanned += 1
        try:
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
            stop_pct, p2_pct = _dir_pcts(entry, lv["stop"], lv["target"], "long")

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
                "open_pct": _pct(open_, y_close),
                "current_pct": _pct(close, open_),
                "day_pct": _pct(close, y_close),
                "entry": entry,
                "stop": lv["stop"],
                "target": lv["target"],
                "rr": lv["rr"],
                "trail": lv["trail"],
                # Stop% = risk to stop, P2% = reward to target — both from entry (R:R = P2/Stop).
                "stop_pct": stop_pct,
                "p2_pct": p2_pct,
                "target_basis": lv["target_basis"],
                "spark": _spark(df),
                "trend": "green" if points >= config.TREND_THRESHOLDS["pullback"] else "blue",
                "turnover": round(turnover),
                "detail": detail,
                "analysis": analysis.narrative(info.get("symbol", yf_ticker), sig, lv, detail,
                                               market.currency_symbol),
            }
            results.append(row)
            if write_charts and out_root:
                pending_charts.append((yf_ticker, sig, lv, row))
        except Exception as e:
            print(f"  warning: {yf_ticker} → {e}", flush=True)

    if write_charts and out_root:
        _write_extended_charts(pending_charts, frames, market_key, out_root,
                               charts.build_chart, market)

    # Sector counts across all results, attached to each row (e.g. "MATERIALS x16").
    sector_counts = _finalize(results)

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
    pending_charts: list[tuple] = []
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
        stop_pct, p2_pct = _dir_pcts(entry, lv["stop"], lv["target"], "long")

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
            "open_pct": _pct(open_, y_close),
            "current_pct": _pct(close, open_),
            "day_pct": _pct(close, y_close),
            "entry": entry,
            "stop": lv["stop"],
            "target": lv["target"],
            "rr": lv["rr"],
            "trail": lv["trail"],
            "stop_pct": stop_pct,
            "p2_pct": p2_pct,
            "target_basis": lv["target_basis"],
            "spark": _spark(df),
            "trend": "green" if points >= config.TREND_THRESHOLDS["reversal"] else "blue",
            "turnover": round(turnover),
            "detail": detail,
            "analysis": reversal.narrative(info.get("symbol", yf_ticker), sig, lv, detail,
                                           market.currency_symbol),
        }
        results.append(row)
        if write_charts and out_root:
            pending_charts.append((yf_ticker, sig, lv, row))

    if write_charts and out_root:
        _write_extended_charts(pending_charts, frames, chart_key, out_root,
                               charts.build_chart_reversal, market)

    sector_counts = _finalize(results)

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
    pending_charts: list[tuple] = []
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
        stop_pct, p2_pct = _dir_pcts(entry, lv["stop"], lv["target"], "long")

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
            "open_pct": _pct(open_, y_close),
            "current_pct": _pct(close, open_),
            "day_pct": _pct(close, y_close),
            "entry": entry,
            "stop": lv["stop"],
            "target": lv["target"],
            "rr": lv["rr"],
            "trail": lv["trail"],
            "stop_pct": stop_pct,
            "p2_pct": p2_pct,
            "target_basis": lv["target_basis"],
            "spark": _spark(df),
            "trend": "green" if points >= config.TREND_THRESHOLDS["spec"] else "blue",
            "turnover": round(turnover),
            "detail": detail,
            "analysis": spec.spec_narrative(info.get("symbol", yf_ticker), sig, lv, detail,
                                            market.currency_symbol),
        }
        results.append(row)
        if write_charts and out_root:
            pending_charts.append((yf_ticker, sig, lv, row))

    if write_charts and out_root:
        _write_extended_charts(pending_charts, frames, chart_key, out_root,
                               charts.build_chart_reversal, market)

    sector_counts = _finalize(results)

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
                      write_charts: bool = True, out_root: str | None = None,
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

    chart_key = market_key + "_short"
    if write_charts and out_root:
        charts.reset_dir(out_root, chart_key)

    results: list[dict] = []
    pending_charts: list[tuple] = []
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
        stop_pct, p2_pct = _dir_pcts(entry, lv["stop"], lv["target"], "short")

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
            "open_pct": _pct(open_, y_close),
            "current_pct": _pct(close, open_),
            "day_pct": _pct(close, y_close),
            "entry": entry,
            "stop": lv["stop"],
            "target": lv["target"],
            "rr": lv["rr"],
            "trail": lv["trail"],
            "stop_pct": stop_pct,
            "p2_pct": p2_pct,
            "target_basis": lv["target_basis"],
            "spark": _spark(df),
            "trend": "green" if points >= config.TREND_THRESHOLDS["short"] else "blue",
            "turnover": round(turnover),
            "detail": [],
            "analysis": short.narrative(info.get("symbol", yf_ticker), sig, lv,
                                        market.currency_symbol),
        }
        results.append(row)
        if write_charts and out_root:
            pending_charts.append((yf_ticker, sig, lv, row))

    if write_charts and out_root:
        _write_extended_charts(pending_charts, frames, chart_key, out_root,
                               charts.build_chart_short, market)

    sector_counts = _finalize(results)

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


def scan_scalp(progress: bool = True, out_root: str | None = None,
               type_filter: str | None = None) -> dict:
    """Cross-asset intraday scalp scan on 1h bars (commodities + ASX + NASDAQ + Crypto).

    Pass ``type_filter="crypto"`` to restrict the universe to crypto tickers only,
    which produces a separate payload suitable for writing to ``scalp_crypto.json``.
    """
    t_start  = _time.monotonic()
    trace_id = _uuid.uuid4().hex[:8]
    log.info("scan_scalp start  trace_id=%s  type_filter=%s", trace_id, type_filter)

    universe = load_scalp_universe(type_filter=type_filter)
    tickers  = [u["yf"] for u in universe]
    meta     = {u["yf"]: u for u in universe}

    if progress:
        print(f"  downloading {len(tickers)} scalp tickers (1h) ...", flush=True)
    frames = download(tickers, period="60d", interval="1h", chunk=30)

    if out_root:
        chart_dir = pathlib.Path(out_root) / "charts" / "scalp"
        if chart_dir.exists():
            shutil.rmtree(chart_dir, ignore_errors=True)
        chart_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    scanned = 0
    quality_skipped = 0
    for yf_ticker, df in frames.items():
        scanned += 1
        info = meta.get(yf_ticker, {})
        asset_type = info.get("type", "")
        sym = info.get("symbol", yf_ticker)

        # ── Data quality gate ──────────────────────────────────────────────────
        try:
            validate_bars(df, symbol=sym, interval="1h",
                          min_bars=config.SCALP_DATA_MIN_BARS,
                          staleness_hours=config.DATA_STALENESS_HOURS)
        except DataQualityError as e:
            log.warning("data quality: %s", e)
            quality_skipped += 1
            continue

        for direction in ("long", "short"):
            sig = scalp.evaluate(df, direction=direction, symbol=sym)
            if sig is None:
                continue
            points, grade, fired = scalp.score_and_grade(sig)
            if grade is None:
                log.debug("%s %s: score=%d → no grade", sym, direction, points)
                continue
            lv = scalp.compute_levels(df, sig)
            if lv["rr"] <= 0:
                continue

            entry = lv["entry"]
            stop_pct, p2_pct = _dir_pcts(entry, lv["stop"], lv["target"], direction)

            cur = "$" if asset_type != "asx" else "A$"
            close = sig["close"]
            spark = [round(float(c), 8) for c in df["Close"].iloc[-30:].tolist()]

            log.info("SIGNAL  %s %s  grade=%s  score=%d/%d  rr=%.1f  atr=%.6f  regime=%s",
                     sym, direction.upper(), grade, points, scalp.SCALP_SCORE_MAX,
                     lv["rr"], lv.get("atr", 0), lv.get("market_regime", "unknown"))

            results.append({
                "symbol":        info.get("symbol", yf_ticker),
                "name":          info.get("name", yf_ticker),
                "sector":        info.get("sector", ""),
                "asset_type":    asset_type,
                "dir":           direction.upper(),
                "grade":         grade,
                "score":         points,
                "score_max":     scalp.SCALP_SCORE_MAX,
                "chips":         scalp.build_chips(fired, sig),
                "weekly":        sig.get("squeeze_fired", False),
                "low_rr":        lv["rr"] < 1.5,
                "rr_text":       f"{lv['rr']:.1f}:1",
                "target_2r":     False,
                "liquidity":     "LIQUID",
                "price":         round(close, 8),
                "y_close":       round(close, 8),
                "open":          round(close, 8),
                "open_pct":      0.0,
                "current_pct":   0.0,
                "day_pct":       0.0,
                "entry":         entry,
                "stop":          lv["stop"],
                "target":        lv["target"],
                "rr":            lv["rr"],
                "atr":           lv.get("atr", 0.0),
                "adx":           lv.get("adx", 0.0),
                "market_regime": lv.get("market_regime", "unknown"),
                "trail":         lv["stop"],
                "stop_pct":      stop_pct,
                "p2_pct":        p2_pct,
                "target_basis":  "atr",
                "spark":         spark,
                "trend":         "green" if points >= config.TREND_THRESHOLDS["scalp"] else "blue",
                "turnover":      0,
                "detail":        scalp.build_detail(df, sig, lv),
                "analysis":      scalp.narrative(
                    info.get("symbol", yf_ticker), sig, lv, asset_type, cur),
            })

            if out_root:
                chips = scalp.build_chips(fired, sig)
                cd = scalp.build_chart_data(df, sig, lv, info, points, grade, chips)
                chart_name = f"{info.get('symbol', yf_ticker)}_{direction}"
                try:
                    (chart_dir / f"{chart_name}.json").write_text(
                        json.dumps(cd), encoding="utf-8")
                except OSError:
                    pass

    results.sort(key=lambda r: (GRADE_RANK.get(r["grade"], 9), -r["score"], -r["rr"]))

    # Keep only the best direction per symbol (highest score first after sort)
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in results:
        if r["symbol"] not in seen:
            seen.add(r["symbol"])
            deduped.append(r)
    results = deduped

    tradeable    = sum(1 for r in results if r["grade"] in ("A+", "A"))
    elapsed_s    = round(_time.monotonic() - t_start, 2)
    log.info("scan_scalp done  trace_id=%s  scanned=%d  quality_skipped=%d  "
             "signals=%d  tradeable=%d  elapsed=%.2fs",
             trace_id, scanned, quality_skipped, len(results), tradeable, elapsed_s)

    market_key   = "scalp_crypto" if type_filter == "crypto" else "scalp"
    market_label = "CRYPTO SCALP" if type_filter == "crypto" else "SCALP"

    now = dt.datetime.now(dt.timezone.utc)

    if out_root:
        _write_health(pathlib.Path(out_root), market_key, now, scanned,
                      quality_skipped, tradeable, trace_id=trace_id, elapsed_s=elapsed_s)

    return {
        "market":           market_key,
        "label":            market_label,
        "setup_type":       "scalp",
        "currency":         "USD",
        "currency_symbol":  "$",
        "timezone":         "UTC",
        "tz_label":         "UTC",
        "generated_at":     now.isoformat(timespec="seconds"),
        "timeframe":        "1h",
        "scanned":          scanned,
        "quality_skipped":  quality_skipped,
        "universe_size":    len(universe),
        "score_max":        scalp.SCALP_SCORE_MAX,
        "brokerage":        config.SCALP_BROKERAGE_EACH_WAY,
        "position_size":    config.SCALP_POSITION_SIZE,
        "leverage":         config.SCALP_LEVERAGE,
        "risk_per_trade":   config.SCALP_RISK_PER_TRADE,
        "max_daily_trades": config.SCALP_MAX_TRADES_PER_DAY,
        "trace_id":         trace_id,
        "scanner_version":  config.SCANNER_VERSION,
        "scan_elapsed_s":   elapsed_s,
        "pulse":            [],
        "results":          results,
    }


def _write_health(out_root: pathlib.Path, scan_key: str,
                  now: dt.datetime, scanned: int, quality_skipped: int, tradeable: int,
                  trace_id: str = "", elapsed_s: float = 0.0) -> None:
    """Append/update health.json with the latest scan metadata and rolling history."""
    health_file = out_root / "health.json"
    try:
        health = json.loads(health_file.read_text()) if health_file.exists() else {}
    except Exception:
        health = {}

    # Rolling history of tradeable (A+/A) signal counts — used by anomaly detection
    prev_entry = health.get(scan_key, {})
    history = list(prev_entry.get("setup_count_history", []))
    history.append(tradeable)
    if len(history) > 20:
        history = history[-20:]

    health[scan_key] = {
        "generated_at":        now.isoformat(timespec="seconds"),
        "scanned":             scanned,
        "quality_skipped":     quality_skipped,
        "tradeable":           tradeable,
        "age_minutes":         0,
        "trace_id":            trace_id,
        "scan_elapsed_s":      elapsed_s,
        "scanner_version":     config.SCANNER_VERSION,
        "setup_count_history": history,
    }
    health["updated_at"] = now.isoformat(timespec="seconds")
    try:
        health_file.write_text(json.dumps(health, indent=2))
    except Exception as e:
        log.warning("could not write health.json: %s", e)
