"""Orchestration for the VIVEK scan: download -> 200-SMA reaction -> trigger ->
per-timeframe plan -> grade -> rank, per market."""

import datetime as dt
import json
import logging
import os
import pathlib
import subprocess
from collections import Counter
from zoneinfo import ZoneInfo

from . import config, scanerrors   # (pulse import removed 2026-07-20 — module retired & deleted)
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


def _load_prev_grades(out_root: str | None, market_key: str) -> dict:
    """{symbol: {grade, dir, held}} from the PREVIOUS scan's JSON (read before
    it's overwritten) so grade hysteresis can hold a borderline name's prior
    grade across scans — direction-aware and with a bounded hold count."""
    if not out_root:
        return {}
    p = pathlib.Path(out_root) / f"{market_key}_vivek.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {r["symbol"]: {"grade": r["grade"], "dir": r.get("dir"),
                              "held": int(r.get("grade_held_runs") or 0)}
                for r in data.get("results", [])
                if r.get("symbol") and r.get("grade")}
    except Exception:
        return {}


def _bar_is_forming(market_key: str, last_date, now: dt.datetime) -> bool:
    """Is the trailing daily bar still forming (the current session's incomplete
    bar)? True only when the last bar is TODAY in the market tz and today's session
    has not yet closed; crypto (no session) forms until UTC midnight (all day)."""
    if last_date != now.date():
        return False                       # a prior, completed day's bar
    sess = config.VIVEK_JOURNAL_SESSION.get(market_key)
    if not sess:
        return True                        # crypto: today's bar forms until UTC midnight
    ch, cm = sess[2], sess[3]
    return (now.hour * 60 + now.minute) < (ch * 60 + cm)


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

    now = dt.datetime.now(ZoneInfo(market.timezone))
    prev_grades = _load_prev_grades(out_root, market_key)   # for grade hysteresis

    results: list[dict] = []
    prices: dict[str, float] = {}        # last close for EVERY scanned symbol
    # ...and how old each of those closes is, in the MARKET's own calendar
    # (TOP100 #24). SPARSE ON PURPOSE: only symbols with age > 0 are recorded.
    # A scan publishes ~2,200 ASX marks and on a healthy run every one of them
    # is 0, so writing the zeros would roughly double the slim prices file to
    # say nothing. Absent therefore means fresh, which is also what every
    # existing reader assumes today — so an old page keeps working unchanged.
    price_age: dict[str, int] = {}
    # Per-ticker failures used to print behind `if progress:` and the only
    # production caller (run.py) passes progress=False, so a scheduled scan said
    # NOTHING about a name that threw every session (TOP100 #60). The print
    # below is kept for interactive runs; this counts them for the log line and
    # the payload regardless of who is watching.
    errors = scanerrors.ErrorLog(f"vivek [{market_key}]")
    # Separate log, because it is a separate failure with a separate blast
    # radius. A throw here does not cost a SETUP — the name is still scored
    # below — it costs the published MARK, and a held position with no mark is
    # priced off a stale one by the journal without saying so. A column rename
    # would empty `prices` for all 2,212 names at once and publish `{}`.
    price_errors = scanerrors.ErrorLog(f"vivek prices [{market_key}]")
    scanned = 0
    # Pipeline funnel (2026-07-29): how many names each stage dropped, so "is
    # a filter too restrictive?" is a number instead of a feeling. Counted at
    # the loop's own `continue` points — pure observation, no gate moves. The
    # stages are SEQUENTIAL (a name dropped for no_setup was never liquidity-
    # checked), so illiquid_setup counts names that HAD a setup and were too
    # thin — the exact rows a too-tight liquidity floor would be killing.
    funnel = {"no_setup": 0, "illiquid_setup": 0, "below_score": 0, "no_plan": 0}
    for yf_ticker, df in frames.items():
        scanned += 1
        symbol = meta.get(yf_ticker, {}).get("symbol", yf_ticker)
        # Freshness measured on the RAW frame, in the MARKET's calendar
        # (TOP100 #23) — `now` above is already the market's local time.
        # Computed BEFORE the price snapshot (TOP100 #24) so that the mark and
        # its age are stamped from the same frame in the same breath. It used to
        # live below, inside the scoring block, which meant a name that failed
        # `evaluate` published a price and NO age — and a held position that has
        # dropped out of the setup list is exactly the row that gets priced off
        # cache for weeks. The mark's age must not depend on whether the name
        # happens to be a setup today.
        age = _frame_age_days(df, market.timezone)
        # Snapshot the latest close for the whole universe (not just setups), so
        # the journal can price any open position — including held names that are
        # no longer a current setup — straight from the scan, every run.
        try:
            if len(df):
                prices[symbol] = round(float(df["Close"].iloc[-1]), 8)
                if age > 0:
                    price_age[symbol] = age
        except Exception as e:
            price_errors.record(symbol, e)   # was a bare `pass` (TOP100 #60)
        try:
            # Pin to COMPLETED bars: drop a still-forming trailing bar so a name's
            # grade/plan doesn't wobble as the current session's bar fills in.
            if (config.VIVEK_DROP_FORMING_BAR and len(df)
                    and _bar_is_forming(market_key, df.index[-1].date(), now)):
                df = df.iloc[:-1]
            sig = vivek.evaluate(df)
            if sig is None:
                funnel["no_setup"] += 1
                continue
            turnover = _liquidity(df, market)
            if turnover < market.liquidity_min:
                funnel["illiquid_setup"] += 1
                continue
            points, raw_grade, fired = vivek.score_and_grade(sig)
            if raw_grade is None:
                funnel["below_score"] += 1
                continue
            # Hysteresis: hold the prior (higher) grade through small score wobble.
            # Applied BEFORE the gate so a genuine un-arm / low-R:R still demotes.
            # Direction-aware (a LONG badge never survives onto a SHORT read) and
            # bounded (a hold can't renew itself forever off its own output).
            # DISPLAY-ONLY as of 2026-07-20 (review H2): the held grade is what
            # the row shows, but the bot buys off grade_raw below — a smoothing
            # device must never authorise an entry on a decayed setup.
            prev = prev_grades.get(symbol) or {}
            grade, held_runs = vivek.apply_grade_hysteresis(
                points, raw_grade, prev.get("grade"),
                prev_dir=prev.get("dir"),
                cur_dir="LONG" if sig["direction"] == "long" else "SHORT",
                held_runs=prev.get("held", 0))
            # Per-timeframe plans (Daily + 3-Day + Weekly) from the ONE engine.
            plans = vivek.build_plans(df, sig)
            lv = plans.get("1D")
            gate_tf = next((tf for tf in ("1W", "3D", "1D")
                            if (plans.get(tf) or {}).get("armed")), None)
            gate_plan = plans.get(gate_tf) if gate_tf else None
            armed = gate_plan is not None
            # H1 (2026-07-20): the row HEADLINE is the plan the system actually
            # trades — the gated timeframe when armed (1W > 3D > 1D, the same
            # order the bot prefers), falling back to the Daily plan when merely
            # watching. Before this the row always showed 1D numbers while the
            # gate/bot read the armed TF: a weekly-armed A+ displayed a different
            # entry/stop/R:R than the trade actually taken, and a weekly-armed
            # setup whose 1D plan was missing/bad was dropped from the scan
            # entirely.
            hp = gate_plan or lv
            if not hp or float(hp.get("rr") or 0) <= 0:
                funnel["no_plan"] += 1
                continue
            gate_rr = float(hp.get("rr") or 0)
            markers = vivek.build_markers(plans)
            # Selectivity gate: only ARMED setups (a trigger fired) earn A/A+;
            # otherwise the setup is WATCHING and capped at B+. Also demote on low
            # R:R. Applied to BOTH grades: `grade` (held, displayed) and
            # `grade_raw` (unsmoothed — what the bot is allowed to buy).
            grade, gate_notes = vivek.gate_grade(grade, sig, gate_rr, armed)
            grade_raw, _ = vivek.gate_grade(raw_grade, sig, gate_rr, armed)
            fired = fired + gate_notes
            # Entry-type chips reflect the FIRED trigger when armed; fall back to
            # the descriptive heuristic for watching setups.
            entry_types = ([gate_plan["entry_trigger"]] if armed and gate_plan.get("entry_trigger")
                           else vivek.entry_types(sig))

            info = meta.get(yf_ticker, {})
            close = sig["close"]
            detail = vivek.build_detail(df, sig, hp)
            is_long = sig["direction"] == "long"
            results.append({
                "symbol": info.get("symbol", yf_ticker),
                "name": info.get("name", yf_ticker),
                "sector": info.get("sector", ""),
                "dir": "LONG" if is_long else "SHORT",
                "setup_type": "vivek",
                "grade": grade,                    # displayed (hysteresis-held, gated)
                "grade_raw": grade_raw,            # unsmoothed, gated — the bot buys off THIS
                "score": points,
                "score_max": config.VIVEK_SCORE_MAX,
                "chips": fired,
                "level_tf": sig["level_tf"],
                "level": sig["level"],
                "at_level": sig["at_level"],
                "reaction": sig["reaction"],
                "entry_types": entry_types,
                "armed": armed,
                "armed_tf": gate_tf,               # which plan fired the gate (1W/3D/1D)
                "grade_held_runs": held_runs,      # hysteresis state, read back next scan
                "entry_trigger": hp.get("entry_trigger"),
                "trigger_bar": hp.get("trigger_bar"),
                # TOP100 #72 — is this row's HEADLINE level a real 200 SMA, or a
                # short-history stand-in? Taken from `hp`, the plan the row shows
                # and the bot reads, not from 1D, so it describes the number on
                # screen. The payload's top-level "sma": 200 is a config echo and
                # was the only thing saying 200 before this.
                "sma_proxy": bool(hp.get("sma_proxy")),
                "sma_window": hp.get("sma_window"),
                "plans": plans,
                "markers": markers,
                "confluence": sig["confluence"],
                "price": round(close, 8),
                # Headline numbers = the TRADED plan (hp): gated TF when armed,
                # 1D fallback when watching. headline_tf labels the source.
                "headline_tf": gate_tf or "1D",
                "entry": hp["entry"], "stop": hp["stop"],
                "tp1": hp["tp1"], "tp2": hp["tp2"], "tp3": hp["tp3"],
                "scale": hp["scale"], "risk": hp["risk"],
                "rr": hp["rr"],
                "rr_text": f"{hp['rr']:.1f}:1",
                "liquidity": "LIQUID" if turnover >= liquid_tier else "OK",
                "turnover": round(turnover),
                "data_age_days": age,   # 0 = fresh; >0 = reused cache (raw-frame age)
                "spark": _spark(df),
                "detail": detail,
                "analysis": vivek.narrative(info.get("symbol", yf_ticker), sig, hp,
                                            detail, market.currency_symbol),
            })
        except Exception as e:
            errors.record(symbol, e)
            if progress:
                print(f"  warning: VIVEK {yf_ticker} -> {e}", flush=True)

    # Printed on EVERY run, including a clean one: "no line" and "the accounting
    # never ran" look identical in a log, and a standing `0 failed of 2212` is
    # what makes a jump to `41 failed` legible at a glance (TOP100 #60).
    errors.report(scanned)
    price_errors.report(scanned)
    _report_sma_proxies(results)

    # Rank by VIVEK grade, then score, then R:R.
    counts = _finalize_vivek(results)
    if pulse_data is None:
        # PULSE retired from the UI 2026-07-03; stopped fetching 2026-07-09 —
        # it was still hitting Yahoo for macro quotes on every scheduled scan.
        # Restore by swapping [] back to pulse.fetch().
        pulse_data = []
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
        # Pipeline funnel (2026-07-29, additive like `errors` below — no schema
        # bump). Self-contained on purpose: a reader gets the whole story from
        # this one key without joining scanned/downloaded/errors themselves.
        # Identity, pinned by tests: with_data = no_setup + illiquid_setup +
        # below_score + no_plan + errors + setups.
        "funnel": {
            "universe": len(universe),
            "with_data": downloaded,
            **funnel,
            "errors": errors.payload()["errors"],
            "setups": len(results),
            "grades": dict(Counter(r["grade"] for r in results)),
        },
        "pulse": pulse_data,
        "results": results,
        "prices": prices,                 # universe-wide last-close snapshot
        # Sparse {symbol: days} for the marks above that are NOT from today's
        # session (TOP100 #24). Absent symbol = fresh. Lets the journal say a
        # mark is stale instead of drawing a cache-reused close as a live price.
        "price_age": price_age,
        # `errors` (int) + `error_sample` (capped list) — TOP100 #60. Additive,
        # so no VIVEK_SCHEMA_VERSION bump: the CI schema gates read
        # `schema_version` alone and every consumer reads named keys. Bumping
        # would mark every already-committed scan file as a build behind and
        # show a stale-data warning on the site until all three markets rescan.
        # Published even at zero, because "present and 0" is what distinguishes
        # "accounted for, none failed" from "this file predates the accounting".
        **errors.payload(),
        **price_errors.payload("price_"),
    }


def _report_sma_proxies(results: list[dict]) -> None:
    """Say how many of this market's levels are a real 200 SMA and how many aren't.

    TOP100 #72. `build_tf_plan` falls back to `min(VIVEK_SMA, bars)` when a frame
    is short, so a "200 SMA" level can be a 30-period one and the payload's
    top-level `"sma": 200` is a config echo that cannot contradict it. The count
    is printed on EVERY run, clean ones included: a standing `0 use a shorter
    proxy` is what makes the day it becomes 300 legible, and a line that only
    appears when something is wrong is a line nobody has a baseline for.

    The WARNING is scoped to `grade_raw` in TRADEABLE_GRADES rather than to every
    proxy, because that is the set the bot is allowed to buy — a WATCH-grade
    short-history name is a curiosity, an A+ one is a position sized off a level
    that is not the level the strategy is named after. Reporting only; nothing
    here filters, demotes or reorders anything.
    """
    if not results:
        return
    proxies = [r for r in results if r.get("sma_proxy")]
    print(f"  sma: {len(results) - len(proxies)}/{len(results)} setups key off a full "
          f"{config.VIVEK_SMA}-period level; {len(proxies)} use a shorter proxy")
    if not proxies:
        return
    windows = [int(r.get("sma_window") or 0) for r in proxies]
    buyable = sorted({str(r.get("symbol") or "?") for r in proxies
                      if r.get("grade_raw") in config.TRADEABLE_GRADES})
    print(f"    proxy windows {min(windows)}-{max(windows)} bars")
    if buyable:
        shown = ", ".join(buyable[:12]) + (" ..." if len(buyable) > 12 else "")
        print(f"    WARNING {len(buyable)} tradeable-grade setup(s) priced off a "
              f"proxy level: {shown}")


def _finalize_vivek(results: list[dict]) -> Counter:
    counts = Counter(r["sector"] for r in results if r["sector"])
    for r in results:
        r["sector_count"] = counts.get(r["sector"], 0)
    results.sort(key=lambda r: (_VIVEK_RANK.get(r["grade"], 9), -r["score"], -r["rr"]))
    return counts


