"""The committed slim summary of a decision replay + its pinned inputs
(NEXT100 #14, 2026-11-03). SIMULATION ONLY: read by scripts/decision_pack.py
and by people, never by a trade path.

Every hc4-3 candidate rests on the decision replay, whose full report is a
90-day artifact nobody can recompute, while yfinance's auto_adjust re-bases
prices on every run. So each replay now also writes two SMALL files that
decision_replay.yml's commit-summary job commits under
config.VIVEK_PARITY_SUMMARY_DIR:

  summary.json  schema 1, EXACTLY as scripts/decision_pack.py documents it
                (the pack's replay_same_weeks reads it): the LIVE-RULES arm's
                taken trades, one slim row each, a `run` block with the commit
                SHA, period, limit, markets and the rules/params the replay
                used, and a `variants` block with each variant's verdict and
                R per slot-month.
  inputs.json   per market, the sample's names and, per priced name, the
                first bar date, the last bar date, the bar count and a short
                digest of the close series -- so a later run can tell whether
                the rules or the DATA moved a verdict.

Both go through scanner.output.write_json (atomic, non-finite floats nulled).
Nothing here reaches scanner/broker/ and nothing in a trade path imports it.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
import os
import pathlib

from . import config, output

SUMMARY_FILE = "summary.json"
INPUTS_FILE = "inputs.json"
_EPOCH = dt.date(1970, 1, 1)
# The trade row, key for key, as the pack's docstring and
# tests/fixtures/decision_replay_summary.json spell it.
TRADE_KEYS = ("m", "s", "cell", "grade", "entry", "exit", "r", "reason")


# ── the inputs digest ────────────────────────────────────────────────────────

def close_digest(closes) -> str:
    """sha1 of the close series rounded to VIVEK_PARITY_INPUT_DIGEST_DP
    decimals, its first VIVEK_PARITY_INPUT_DIGEST_HEX hex chars. The same
    tape digests the same; a re-based (adjusted) tape digests differently;
    float noise under the rounding does not move it. NaN prints as 'nan'."""
    dp = int(config.VIVEK_PARITY_INPUT_DIGEST_DP)
    parts = []
    for x in closes:
        v = float(x)
        parts.append("nan" if math.isnan(v) else format(round(v, dp), f".{dp}f"))
    return hashlib.sha1(",".join(parts).encode("ascii")).hexdigest()[:int(config.VIVEK_PARITY_INPUT_DIGEST_HEX)]


def _iso_of(days, k: int) -> str | None:
    try:
        return (_EPOCH + dt.timedelta(days=int(days[k]))).isoformat()
    except (IndexError, TypeError, ValueError, OverflowError):
        return None


def series_inputs(series_by_market, sampled: dict | None = None) -> dict:
    """{market: {"names": [...], "series": {symbol: {first, last, n, digest}}}}.

    `series_by_market` is {market: [SymbolSeries]} or a flat list of them
    (anything with .market, .symbol, .days and .c). `sampled` ({market:
    [symbols]}, the report's sampled_symbols) lists the names the replay
    DREW, priced or not; a name under `names` but not `series` was drawn and
    not priced."""
    groups: dict[str, list] = {}
    if isinstance(series_by_market, dict):
        for mk, ss in series_by_market.items():
            groups.setdefault(str(mk), []).extend(list(ss or []))
    else:
        for s in series_by_market or []:
            groups.setdefault(str(getattr(s, "market", "")), []).append(s)
    markets = set(groups) | set((sampled or {}).keys())
    out = {}
    for mk in sorted(markets):
        series = {}
        for s in sorted(groups.get(mk, []), key=lambda z: str(getattr(z, "symbol", ""))):
            c = getattr(s, "c", None)
            days = getattr(s, "days", None)
            n = 0 if c is None else len(c)
            series[str(s.symbol)] = {
                "first": _iso_of(days, 0) if n else None,
                "last": _iso_of(days, n - 1) if n else None,
                "n": int(n),
                "digest": close_digest(c) if n else None,
            }
        names = [str(x) for x in ((sampled or {}).get(mk) or [])] or sorted(series)
        out[mk] = {"names": names, "series": series}
    return out


# ── the summary ──────────────────────────────────────────────────────────────

def _num(v, nd: int = 4):
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, nd) if math.isfinite(f) else None


EOD_REASON = "eod"   # vivek_backtest._force_close's end-of-data marker


def trade_row(t: dict) -> dict:
    """One slim row from a published parity trade (vivek_parity._slim_parity).

    The replay FORCE-CLOSES every trade still open on its last bar
    (vivek_backtest._force_close: exit_date = the last day, exit_reason =
    "eod", realized_r = the MARK). That is not a close: the pack's
    replay_same_weeks counts any row with `exit` set as CLOSED and averages
    its r, and the live cycle's ISO weeks are the newest bars of the tape,
    so an eod row written as closed would build the same-weeks figure from
    marks. An eod trade is therefore written as the docstring's open row:
    exit null, reason "open", r = the mark. A RUNNER whose remainder is
    force-closed at eod is labelled "trail" / "target" by _force_close
    (pre-existing: it booked TP1 / TP3 for real) and so still counts as
    closed."""
    exit_day = t.get("exit_date") or None
    reason = t.get("exit_reason")
    if reason == EOD_REASON:
        exit_day, reason = None, "open"
    return {
        "m": t.get("market"),
        "s": t.get("symbol"),
        "cell": t.get("cell"),
        "grade": t.get("grade"),
        "entry": t.get("entry_date"),
        "exit": exit_day,
        "r": _num(t.get("realized_r")),
        "reason": str(reason) if reason else ("open" if exit_day is None else None),
    }


def summary_trades(report: dict) -> list[dict]:
    """The LIVE-RULES arm's taken trades only (the baseline book), in the
    report's order; the unconstrained population is not the record."""
    return [trade_row(t) for t in (report.get("trades") or [])
            if isinstance(t, dict) and t.get("taken")]


def _psm(port: dict | None) -> dict:
    port = port or {}
    return {"taken": port.get("taken"),
            "slot_months": _num(port.get("slot_months")),
            "r_per_slot_month": _num(port.get("r_per_slot_month")),
            "r_per_slot_month_house": _num(port.get("r_per_slot_month_house"))}


def variants_block(report: dict) -> dict:
    """Each variant's verdict and R per slot-month, beside the baseline's,
    so the pack can show them without the 90-day artifact."""
    base = (report.get("baseline") or {}).get("portfolio") or {}
    out = {"baseline": _psm(base), "by_name": {}}
    for name, vr in sorted((report.get("variants") or {}).items()):
        if not isinstance(vr, dict):
            continue
        verdict = vr.get("verdict") or {}
        checks = {}
        for key, c in (verdict.get("checks") or {}).items():
            if isinstance(c, dict):
                checks[key] = {"baseline": _num(c.get("baseline")), "variant": _num(c.get("variant")),
                               "delta": _num(c.get("delta")), "pass": c.get("pass")}
        out["by_name"][name] = {
            "delta": vr.get("delta"),
            "kind": vr.get("kind"),
            "pass": bool(verdict.get("pass")),
            "split_entry_date": verdict.get("split_entry_date"),
            "checks": checks,
            **_psm(vr.get("portfolio")),
        }
    best = report.get("best_variant") or {}
    out["best"] = best.get("name")
    return out


def run_block(report: dict) -> dict:
    """The run: commit SHA (GITHUB_SHA when set), run id, period, limit,
    markets, and the rules and params the replay used."""
    params = dict(report.get("params") or {})
    rules = dict(((report.get("baseline") or {}).get("rules")) or {})
    cov = report.get("coverage") or {}
    coverage = {mk: {k: c.get(k) for k in ("symbols", "universe", "priced", "replayed", "signals")}
                for mk, c in cov.items() if isinstance(c, dict)}
    return {
        "id": os.environ.get("GITHUB_RUN_ID") or None,
        "sha": os.environ.get("GITHUB_SHA") or None,
        "ref": os.environ.get("GITHUB_REF_NAME") or None,
        "mode": report.get("mode"),
        "cycle_tag": config.VIVEK_BOT_CYCLE_TAG,
        "period": params.get("period"),
        "limit": params.get("limit"),
        "markets": list(params.get("markets") or sorted(cov)),
        "replay_generated_at": report.get("generated_at"),
        "runtime_minutes": report.get("runtime_minutes"),
        "rules": rules,
        "params": params,
        "coverage": coverage,
    }


def build_summary(report: dict) -> dict:
    return {
        "schema": int(config.VIVEK_PARITY_SUMMARY_SCHEMA),
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run": run_block(report),
        "trades": summary_trades(report),
        "variants": variants_block(report),
    }


def build_inputs(report: dict, series_by_market) -> dict:
    return {
        "schema": int(config.VIVEK_PARITY_SUMMARY_SCHEMA),
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha": os.environ.get("GITHUB_SHA") or None,
        "digest": {"of": "close series", "dp": int(config.VIVEK_PARITY_INPUT_DIGEST_DP),
                   "hex": int(config.VIVEK_PARITY_INPUT_DIGEST_HEX), "algo": "sha1"},
        "markets": series_inputs(series_by_market, report.get("sampled_symbols") or {}),
    }


def write_summary(report: dict, series_by_market, out_dir) -> tuple[pathlib.Path, pathlib.Path]:
    """Write summary.json + inputs.json under `out_dir` (created) through
    scanner.output.write_json. Returns the two paths."""
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / SUMMARY_FILE
    inputs_path = out_dir / INPUTS_FILE
    output.write_json(summary_path, build_summary(report), indent=1, newline=True)
    output.write_json(inputs_path, build_inputs(report, series_by_market), indent=1, newline=True)
    return summary_path, inputs_path
