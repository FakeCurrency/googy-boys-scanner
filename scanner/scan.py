"""Orchestration: download -> indicators -> signals -> grade -> rank, per market."""

import datetime as dt
import json
import logging
import pathlib
import shutil
import time as _time
import uuid as _uuid
from collections import Counter
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from . import analysis, charts, config, googy, levels, pulse, reversal, short, signals, spec
from .data import download, validate_bars, DataQualityError
from .universe import load_universe

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
        # NB: never use `ext.get(t) or scan_frames.get(t)` — `bool(DataFrame)`
        # raises "truth value is ambiguous", which would crash this whole pass
        # *after* reset_dir() already wiped the chart dir, deleting good charts.
        df_chart = ext.get(yf_ticker)
        if df_chart is None:
            df_chart = scan_frames.get(yf_ticker)
        if df_chart is None or len(df_chart) < 6:
            continue
        try:
            charts.write_chart(builder(df_chart, sig, lv, row, market), out_root, chart_key)
        except Exception:
            pass


@dataclass(frozen=True)
class EngineSpec:
    """Per-engine differences for the shared scan driver (_scan_engine).

    Everything that varies between the pullback / reversal / spec / short / googy
    scanners is captured here as data + small callables, so the download → score
    → row-build → envelope skeleton lives in exactly one place. Adding a result
    field or changing the schema is now a single edit instead of five.
    """
    setup_type: str
    direction: str                 # "long" | "short"
    score_max: int
    trend_key: str                 # key into config.TREND_THRESHOLDS
    periods_field: str             # "ema_periods" | "sma_periods"
    periods_value: list
    chart_suffix: str              # "" | "_rev" | "_spec" | "_short" | "_googy"
    chart_builder: "object"        # charts.build_chart* callable
    evaluate: "object"             # (df, market) -> sig | None
    is_valid: "object"             # (sig) -> bool
    score_and_grade: "object"      # (sig) -> (points, grade, fired)
    compute_levels: "object"       # (df, sig) -> lv
    make_chips: "object"           # (fired, sig, turnover, market_key) -> list[str]
    weekly_of: "object"            # (sig) -> bool
    build_detail: "object"         # (df, sig, lv) -> dict
    make_narrative: "object"       # (symbol, sig, lv, detail, currency_symbol) -> str
    liquidity_min: "object"        # (market, market_key) -> float
    extra_row: "object"            # (turnover, market_key) -> dict (extra row fields)
    demote_low_rr: bool = False
    row_setup_type: bool = True
    include_universe_tickers: bool = False
    verbose_progress: bool = False
    catch_errors: bool = False


def _googy_chips(fired: list[str], sig: dict, turnover: float, market_key: str) -> list[str]:
    chips = googy.build_chips(fired, sig)
    if turnover < config.GOOGY_LOW_LIQ_TURNOVER.get(market_key, 200_000):
        chips.insert(0, "LOW LIQUIDITY")
    return chips


# ── One spec per scanner tab. The driver below is engine-agnostic. ────────────
_PULLBACK = EngineSpec(
    setup_type="pullback", direction="long",
    score_max=config.SCORE_MAX, trend_key="pullback",
    periods_field="ema_periods", periods_value=config.EMA_PERIODS,
    chart_suffix="", chart_builder=charts.build_chart,
    evaluate=lambda df, market: signals.evaluate(df),
    is_valid=lambda sig: sig is not None and sig["uptrend"],
    score_and_grade=signals.score_and_grade,
    compute_levels=levels.compute_levels,
    make_chips=lambda fired, sig, turnover, mk: _build_chips(fired, sig),
    weekly_of=lambda sig: sig["weekly"],
    build_detail=analysis.build_detail,
    make_narrative=lambda s, sig, lv, detail, cur: analysis.narrative(s, sig, lv, detail, cur),
    liquidity_min=lambda market, mk: market.liquidity_min,
    extra_row=lambda turnover, mk: {},
    demote_low_rr=True, row_setup_type=False,
    include_universe_tickers=True, verbose_progress=True, catch_errors=True,
)

_REVERSAL = EngineSpec(
    setup_type="reversal", direction="long",
    score_max=config.REV_SCORE_MAX, trend_key="reversal",
    periods_field="sma_periods", periods_value=config.REV_SMAS,
    chart_suffix="_rev", chart_builder=charts.build_chart_reversal,
    evaluate=lambda df, market: reversal.evaluate(df),
    is_valid=lambda sig: sig is not None and sig.get("ok"),
    score_and_grade=reversal.score_and_grade,
    compute_levels=reversal.compute_levels,
    make_chips=lambda fired, sig, turnover, mk: reversal.build_chips(fired, sig),
    weekly_of=lambda sig: False,
    build_detail=reversal.build_detail,
    make_narrative=lambda s, sig, lv, detail, cur: reversal.narrative(s, sig, lv, detail, cur),
    liquidity_min=lambda market, mk: market.liquidity_min,
    extra_row=lambda turnover, mk: {},
)

_SPEC = EngineSpec(
    setup_type="spec", direction="long",
    score_max=config.SPEC_SCORE_MAX, trend_key="spec",
    periods_field="sma_periods", periods_value=config.SPEC_SMAS,
    chart_suffix="_spec", chart_builder=charts.build_chart_reversal,
    evaluate=lambda df, market: spec.evaluate(
        df, max_price=None if getattr(market, "volume_is_usd", False) else config.SPEC_MAX_PRICE),
    is_valid=lambda sig: sig is not None and sig.get("ok"),
    score_and_grade=spec.score_and_grade,
    compute_levels=spec.compute_levels,
    make_chips=lambda fired, sig, turnover, mk: spec.build_chips(fired, sig),
    weekly_of=lambda sig: False,
    build_detail=spec.build_detail,
    make_narrative=lambda s, sig, lv, detail, cur: spec.spec_narrative(s, sig, lv, detail, cur),
    liquidity_min=lambda market, mk: market.liquidity_min,
    extra_row=lambda turnover, mk: {},
)

_SHORT = EngineSpec(
    setup_type="short", direction="short",
    score_max=short.SHORT_SCORE_MAX, trend_key="short",
    periods_field="ema_periods", periods_value=config.EMA_PERIODS,
    chart_suffix="_short", chart_builder=charts.build_chart_short,
    evaluate=lambda df, market: short.evaluate(df),
    is_valid=lambda sig: sig is not None,
    score_and_grade=short.score_and_grade,
    compute_levels=short.compute_levels,
    make_chips=lambda fired, sig, turnover, mk: short.build_chips(fired, sig),
    weekly_of=lambda sig: sig["weekly_bearish"],
    build_detail=lambda df, sig, lv: {},
    make_narrative=lambda s, sig, lv, detail, cur: short.narrative(s, sig, lv, cur),
    liquidity_min=lambda market, mk: market.liquidity_min,
    extra_row=lambda turnover, mk: {},
    demote_low_rr=True,
)

_GOOGY = EngineSpec(
    setup_type="googy", direction="long",
    score_max=config.GOOGY_SCORE_MAX, trend_key="googy",
    periods_field="sma_periods", periods_value=[config.GOOGY_SMA_FAST, config.GOOGY_SMA_SLOW],
    chart_suffix="_googy", chart_builder=charts.build_chart_reversal,
    evaluate=lambda df, market: googy.evaluate(df),
    is_valid=lambda sig: sig is not None and sig.get("ok"),
    score_and_grade=googy.score_and_grade,
    compute_levels=googy.compute_levels,
    make_chips=_googy_chips,
    weekly_of=lambda sig: False,
    build_detail=googy.build_detail,
    make_narrative=lambda s, sig, lv, detail, cur: googy.narrative(s, sig, lv, detail, cur),
    liquidity_min=lambda market, mk: config.GOOGY_MIN_TURNOVER.get(mk, 5_000),
    extra_row=lambda turnover, mk: {"low_liquidity": turnover < config.GOOGY_LOW_LIQ_TURNOVER.get(mk, 200_000)},
    demote_low_rr=True,
)


def _scan_engine(eng: EngineSpec, market_key: str, limit: int | None = None, full: bool = True,
                 write_charts: bool = True, out_root: str | None = None,
                 progress: bool = True, frames: dict | None = None,
                 pulse_data: list | None = None, universe: list | None = None) -> dict:
    """Engine-agnostic scan driver. The per-engine `eng` spec supplies the only
    parts that differ; everything else (download, liquidity, scoring, row schema,
    charts, ranking, envelope) is shared."""
    market = config.MARKETS[market_key]
    liquid_tier = config.LIQUID_TIER.get(market_key, float("inf"))
    if universe is None:
        universe = load_universe(market_key, full=full)
        if limit:
            universe = universe[:limit]

    meta = {u["yf"]: u for u in universe}
    if frames is None:
        if eng.verbose_progress and progress:
            print(f"  downloading {len(universe)} {market.label} tickers ...", flush=True)
        frames = download([u["yf"] for u in universe])

    chart_key = market_key + eng.chart_suffix
    if write_charts and out_root:
        charts.reset_dir(out_root, chart_key)

    liq_min = eng.liquidity_min(market, market_key)
    results: list[dict] = []
    pending_charts: list[tuple] = []
    scanned = 0
    for yf_ticker, df in frames.items():
        scanned += 1
        try:
            sig = eng.evaluate(df, market)
            if not eng.is_valid(sig):
                continue

            turnover = _liquidity(df, market)
            if turnover < liq_min:
                continue

            points, grade, fired = eng.score_and_grade(sig)
            if grade is None:
                continue

            lv = eng.compute_levels(df, sig)
            if lv["rr"] <= 0:
                continue

            # Tuning toward R:R — a tradeable grade must clear the minimum reward-to-risk,
            # otherwise it's a strong pattern but a poor trade, so demote it to the watch list.
            if eng.demote_low_rr and grade in config.TRADEABLE_GRADES \
                    and lv["rr"] < config.MIN_TRADEABLE_RR:
                grade = "B"

            info = meta.get(yf_ticker, {})
            close = sig["close"]
            open_ = float(df["Open"].iloc[-1])
            y_close = float(df["Close"].iloc[-2])
            entry = lv["entry"]
            stop_pct, p2_pct = _dir_pcts(entry, lv["stop"], lv["target"], eng.direction)
            chips = eng.make_chips(fired, sig, turnover, market_key)
            detail = eng.build_detail(df, sig, lv)

            # Built in the exact field order the live JSON already uses. setup_type
            # is omitted for pullback; googy inserts low_liquidity after low_rr.
            row = {
                "symbol": info.get("symbol", yf_ticker),
                "name": info.get("name", yf_ticker),
                "sector": info.get("sector", ""),
                "dir": "SHORT" if eng.direction == "short" else "LONG",
            }
            if eng.row_setup_type:
                row["setup_type"] = eng.setup_type
            row["grade"] = grade
            row["score"] = points
            row["score_max"] = eng.score_max
            row["chips"] = chips
            row["weekly"] = eng.weekly_of(sig)
            row["low_rr"] = lv["rr"] < config.LOW_RR_THRESHOLD
            row.update(eng.extra_row(turnover, market_key))
            row["rr_text"] = f"{lv['rr']:.1f}:1"
            row["target_2r"] = lv["target_basis"] == "measured"
            row["liquidity"] = "LIQUID" if turnover >= liquid_tier else "OK"
            row["price"] = round(close, 8)
            row["y_close"] = round(y_close, 8)
            row["open"] = round(open_, 8)
            row["open_pct"] = _pct(open_, y_close)
            row["current_pct"] = _pct(close, open_)
            row["day_pct"] = _pct(close, y_close)
            row["entry"] = entry
            row["stop"] = lv["stop"]
            row["target"] = lv["target"]
            row["rr"] = lv["rr"]
            row["trail"] = lv["trail"]
            row["stop_pct"] = stop_pct
            row["p2_pct"] = p2_pct
            row["target_basis"] = lv["target_basis"]
            row["spark"] = _spark(df)
            row["trend"] = "green" if points >= config.TREND_THRESHOLDS[eng.trend_key] else "blue"
            row["turnover"] = round(turnover)
            row["detail"] = detail
            row["analysis"] = eng.make_narrative(
                info.get("symbol", yf_ticker), sig, lv, detail, market.currency_symbol)

            results.append(row)
            if write_charts and out_root:
                pending_charts.append((yf_ticker, sig, lv, row))
        except Exception as e:
            if not eng.catch_errors:
                raise
            print(f"  warning: {yf_ticker} → {e}", flush=True)

    if write_charts and out_root:
        _write_extended_charts(pending_charts, frames, chart_key, out_root,
                               eng.chart_builder, market)

    # Sector counts across all results, attached to each row (e.g. "MATERIALS x16").
    sector_counts = _finalize(results)

    if pulse_data is None:
        if eng.verbose_progress and progress:
            print("  fetching market pulse ...", flush=True)
        pulse_data = pulse.fetch()

    now = dt.datetime.now(ZoneInfo(market.timezone))
    payload = {
        "market": market.key,
        "label": market.label,
        "setup_type": eng.setup_type,
        "currency": market.currency,
        "currency_symbol": market.currency_symbol,
        "timezone": market.timezone,
        "tz_label": market.tz_label,
        "generated_at": now.isoformat(timespec="seconds"),
        "scanned": scanned,
        "universe_size": len(universe),
    }
    if eng.include_universe_tickers:
        payload["universe_tickers"] = [u.get("symbol", u.get("yf", "")) for u in universe]
    payload["score_max"] = eng.score_max
    payload[eng.periods_field] = eng.periods_value
    payload["pulse"] = pulse_data
    payload["sector_counts"] = dict(sector_counts.most_common())
    payload["results"] = results
    return payload


def scan_market(market_key: str, limit: int | None = None, full: bool = True,
                write_charts: bool = True, out_root: str | None = None,
                progress: bool = True, frames: dict | None = None,
                pulse_data: list | None = None, universe: list | None = None) -> dict:
    """Daily Fib-EMA pullback scanner (the main 'Pullbacks' tab)."""
    return _scan_engine(_PULLBACK, market_key, limit, full, write_charts,
                        out_root, progress, frames, pulse_data, universe)


def scan_reversal_market(market_key: str, limit: int | None = None, full: bool = True,
                         write_charts: bool = True, out_root: str | None = None,
                         progress: bool = True, frames: dict | None = None,
                         pulse_data: list | None = None, universe: list | None = None) -> dict:
    """Scan a market for early reversal / base-breakout setups (the 'Reversals' tab)."""
    return _scan_engine(_REVERSAL, market_key, limit, full, write_charts,
                        out_root, progress, frames, pulse_data, universe)


def scan_spec_market(market_key: str, limit: int | None = None, full: bool = True,
                     write_charts: bool = True, out_root: str | None = None,
                     progress: bool = True, frames: dict | None = None,
                     pulse_data: list | None = None, universe: list | None = None) -> dict:
    """Scan a market for speculative volume-spike breakouts (the 'Specs' tab)."""
    return _scan_engine(_SPEC, market_key, limit, full, write_charts,
                        out_root, progress, frames, pulse_data, universe)


def scan_short_market(market_key: str, limit: int | None = None, full: bool = True,
                      write_charts: bool = True, out_root: str | None = None,
                      progress: bool = True, frames: dict | None = None,
                      pulse_data: list | None = None, universe: list | None = None) -> dict:
    """Scan a market for bearish pullback (short) setups — the Shorts tab."""
    return _scan_engine(_SHORT, market_key, limit, full, write_charts,
                        out_root, progress, frames, pulse_data, universe)


def scan_googy_market(market_key: str, limit: int | None = None, full: bool = True,
                      write_charts: bool = True, out_root: str | None = None,
                      progress: bool = True, frames: dict | None = None,
                      pulse_data: list | None = None, universe: list | None = None) -> dict:
    """Scan a market for consolidation breakout setups (the 'Googy Scan' tab).

    More tolerant of low-liquidity names than other daily scanners. Low-turnover
    results appear with a LOW LIQUIDITY chip rather than being filtered out.
    """
    return _scan_engine(_GOOGY, market_key, limit, full, write_charts,
                        out_root, progress, frames, pulse_data, universe)


# VIVEK grade ordering (A+/A/B+/WATCH — distinct from the A+/A/B/C scanners).
_VIVEK_RANK = {"A+": 0, "A": 1, "B+": 2, "WATCH": 3}


def scan_vivek_market(market_key: str, limit: int | None = None, full: bool = True,
                      out_root: str | None = None, progress: bool = True,
                      universe: list | None = None,
                      frames: dict | None = None) -> dict:
    """VIVEK (5.0-style) scan: 200 SMA reactions on the higher timeframes.

    Uses a long (VIVEK_DATA_PERIOD) daily history so a real Weekly 200 SMA can be
    computed. Produces rows carrying Entry / SL / TP1 / TP2 / TP3 + scale-outs and
    an A+/A/B+/WATCH grade with a plain-English reason.

    `frames` (deep daily history) may be passed in by the caller to AVOID a second
    Yahoo download — the runner already pulls this market's 5y history for the
    daily scanners, so VIVEK reuses it instead of fetching the same data again.
    """
    from . import vivek
    market = config.MARKETS[market_key]
    liquid_tier = config.LIQUID_TIER.get(market_key, float("inf"))
    if universe is None:
        universe = load_universe(market_key, full=full)
        if limit:
            universe = universe[:limit]
    meta = {u["yf"]: u for u in universe}

    if frames is None:
        if progress:
            print(f"  downloading {len(universe)} {market.label} tickers "
                  f"({config.VIVEK_DATA_PERIOD}) for VIVEK ...", flush=True)
        frames = download([u["yf"] for u in universe], period=config.VIVEK_DATA_PERIOD)

    results: list[dict] = []
    scanned = 0
    for yf_ticker, df in frames.items():
        scanned += 1
        try:
            sig = vivek.evaluate(df)
            if sig is None:
                continue
            turnover = _liquidity(df, market)
            if turnover < market.liquidity_min:
                continue
            points, grade, fired = vivek.score_and_grade(sig)
            if grade is None:
                continue
            lv = vivek.compute_levels(df, sig)
            if lv.get("rr", 0) <= 0:
                continue
            # Selectivity gate: demote A/A+ that lack a clean reaction or enough
            # room to TP2 (keeps the tradeable list short and trustworthy).
            grade, gate_notes = vivek.gate_grade(grade, sig, lv["rr"])
            fired = fired + gate_notes

            info = meta.get(yf_ticker, {})
            close = sig["close"]
            detail = vivek.build_detail(df, sig, lv)
            is_long = sig["direction"] == "long"
            results.append({
                "symbol": info.get("symbol", yf_ticker),
                "name": info.get("name", yf_ticker),
                "sector": info.get("sector", ""),
                "dir": "LONG" if is_long else "SHORT",
                "setup_type": "vivek",
                "grade": grade,
                "score": points,
                "score_max": config.VIVEK_SCORE_MAX,
                "chips": fired,
                "level_tf": sig["level_tf"],
                "level": sig["level"],
                "at_level": sig["at_level"],
                "reaction": sig["reaction"],
                "entry_types": vivek.entry_types(sig),
                "confluence": sig["confluence"],
                "price": round(close, 8),
                "entry": lv["entry"], "stop": lv["stop"],
                "tp1": lv["tp1"], "tp2": lv["tp2"], "tp3": lv["tp3"],
                "scale": lv["scale"], "risk": lv["risk"],
                "rr": lv["rr"],
                "rr_text": f"{lv['rr']:.1f}:1",
                "liquidity": "LIQUID" if turnover >= liquid_tier else "OK",
                "turnover": round(turnover),
                "spark": _spark(df),
                "detail": detail,
                "analysis": vivek.narrative(info.get("symbol", yf_ticker), sig, lv,
                                            detail, market.currency_symbol),
            })
        except Exception as e:
            if progress:
                print(f"  warning: VIVEK {yf_ticker} → {e}", flush=True)

    # Rank by VIVEK grade, then score, then R:R.
    counts = _finalize_vivek(results)
    now = dt.datetime.now(ZoneInfo(market.timezone))
    return {
        "market": market.key,
        "label": market.label,
        "setup_type": "vivek",
        "currency": market.currency,
        "currency_symbol": market.currency_symbol,
        "timezone": market.timezone,
        "tz_label": market.tz_label,
        "generated_at": now.isoformat(timespec="seconds"),
        "scanned": scanned,
        "universe_size": len(universe),
        "score_max": config.VIVEK_SCORE_MAX,
        "sma": config.VIVEK_SMA,
        "sector_counts": dict(counts.most_common()),
        "results": results,
    }


def _finalize_vivek(results: list[dict]) -> Counter:
    counts = Counter(r["sector"] for r in results if r["sector"])
    for r in results:
        r["sector_count"] = counts.get(r["sector"], 0)
    results.sort(key=lambda r: (_VIVEK_RANK.get(r["grade"], 9), -r["score"], -r["rr"]))
    return counts


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
