"""Orchestration for the VIVEK scan: download -> 200-SMA reaction -> trigger ->
per-timeframe plan -> grade -> rank, per market."""

import datetime as dt
import logging
import os
import pathlib
import subprocess
from collections import Counter
from zoneinfo import ZoneInfo

from . import config, pulse
from .data import download, _frame_age_days
from .universe import load_universe

log = logging.getLogger(__name__)


def _code_sha() -> str:
    """Short commit SHA the scan ran at, stamped into output so the frontend can
    tell whether the data was produced by the current build. GITHUB_SHA is set in
    Actions; fall back to a local `git rev-parse` for manual runs."""
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha[:7]
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=3,
                             cwd=pathlib.Path(__file__).resolve().parents[1])
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _liquidity(df, market) -> float:
    # Crypto: Yahoo "Volume" is already USD dollar-volume; stocks: price * shares.
    if getattr(market, "volume_is_usd", False):
        return float(df["Volume"].iloc[-config.LIQUIDITY_LOOKBACK:].mean())
    turnover = (df["Close"] * df["Volume"]).iloc[-config.LIQUIDITY_LOOKBACK:].mean()
    return float(turnover)


def _spark(df) -> list[float]:
    closes = df["Close"].iloc[-config.SPARK_BARS:].tolist()
    return [round(float(c), 8) for c in closes]


# VIVEK grade ordering (A+/A/B+/WATCH).
_VIVEK_RANK = {"A+": 0, "A": 1, "B+": 2, "WATCH": 3}


def scan_vivek_market(market_key: str, limit: int | None = None, full: bool = True,
                      out_root: str | None = None, progress: bool = True,
                      universe: list | None = None,
                      frames: dict | None = None,
                      pulse_data: list | None = None,
                      from_cache: int = 0) -> dict:
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
            # Per-timeframe plans (Daily + Weekly) from the ONE engine — the Daily
            # plan is the row/bot headline; both feed the chart so the row, chart
            # and bot read identical numbers. The Daily plan also carries the
            # trigger state (armed / entry_trigger / trigger_bar).
            plans = vivek.build_plans(df, sig)
            lv = plans.get("1D")
            if not lv or lv.get("rr", 0) <= 0:
                continue
            armed = bool(lv.get("armed"))
            markers = vivek.build_markers(plans)
            # Selectivity gate: only ARMED setups (a trigger fired) earn A/A+;
            # otherwise the setup is WATCHING and capped at B+. Also demote on low
            # R:R. Keeps the tradeable list short and genuinely actionable.
            grade, gate_notes = vivek.gate_grade(grade, sig, lv["rr"], armed)
            fired = fired + gate_notes
            # Entry-type chips reflect the FIRED trigger when armed; fall back to
            # the descriptive heuristic for watching setups.
            entry_types = ([lv["entry_trigger"]] if armed and lv.get("entry_trigger")
                           else vivek.entry_types(sig))

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
                "entry_types": entry_types,
                "armed": armed,
                "entry_trigger": lv.get("entry_trigger"),
                "trigger_bar": lv.get("trigger_bar"),
                "plans": plans,
                "markers": markers,
                "confluence": sig["confluence"],
                "price": round(close, 8),
                "entry": lv["entry"], "stop": lv["stop"],
                "tp1": lv["tp1"], "tp2": lv["tp2"], "tp3": lv["tp3"],
                "scale": lv["scale"], "risk": lv["risk"],
                "rr": lv["rr"],
                "rr_text": f"{lv['rr']:.1f}:1",
                "liquidity": "LIQUID" if turnover >= liquid_tier else "OK",
                "turnover": round(turnover),
                "data_age_days": _frame_age_days(df),   # 0 = fresh; >0 = reused cache
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
    if pulse_data is None:
        pulse_data = pulse.fetch()
    downloaded = len(frames)
    return {
        "market": market.key,
        "label": market.label,
        "setup_type": "vivek",
        # Freshness + version stamp so the UI can show data age / coverage and
        # detect when committed data is a build behind the running code, instead
        # of silently hiding features that depend on newer fields.
        "schema_version": config.VIVEK_SCHEMA_VERSION,
        "code_sha": _code_sha(),
        "currency": market.currency,
        "currency_symbol": market.currency_symbol,
        "timezone": market.timezone,
        "tz_label": market.tz_label,
        "generated_at": now.isoformat(timespec="seconds"),
        "scanned": scanned,
        "downloaded": downloaded,
        "from_cache": from_cache,                 # tickers reused from last-good cache
        "fresh": max(0, downloaded - from_cache),
        "universe_size": len(universe),
        "coverage_pct": round(100 * downloaded / max(len(universe), 1)),
        "score_max": config.VIVEK_SCORE_MAX,
        "sma": config.VIVEK_SMA,
        "sector_counts": dict(counts.most_common()),
        "pulse": pulse_data,
        "results": results,
    }


def _finalize_vivek(results: list[dict]) -> Counter:
    counts = Counter(r["sector"] for r in results if r["sector"])
    for r in results:
        r["sector_count"] = counts.get(r["sector"], 0)
    results.sort(key=lambda r: (_VIVEK_RANK.get(r["grade"], 9), -r["score"], -r["rr"]))
    return counts


