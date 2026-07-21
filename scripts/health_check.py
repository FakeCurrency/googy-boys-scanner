#!/usr/bin/env python3
"""System health check — Phase 7 Operational Automation.

Usage:
  python scripts/health_check.py           # human-readable report
  python scripts/health_check.py --json    # machine-readable JSON
  python scripts/health_check.py --alert   # also fire smart_send if CRITICAL/WARNING

Exit codes:
  0  OK       system is running normally
  1  WARNING  degraded but not immediately critical
  2  CRITICAL needs immediate attention

Checks:
  1. scan_freshness    — health.json generated_at age vs config thresholds
  2. journal           — scalp_journal.json exists, open positions within limits
  3. circuit_breakers  — non-destructive check_all() on the live journal
  4. log_sizes         — warn/critical if log files exceed size thresholds
  5. fill_analysis     — warn if avg entry slippage exceeds the warn threshold
"""

import argparse
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner import config as _cfg

_OK   = 0
_WARN = 1
_CRIT = 2

STALE_WARN_H = float(getattr(_cfg, "HEALTH_SCAN_STALE_WARN_H", 2))
STALE_CRIT_H = float(getattr(_cfg, "HEALTH_SCAN_STALE_CRIT_H", 4))
LOG_WARN_MB  = float(getattr(_cfg, "HEALTH_LOG_SIZE_WARN_MB", 50))
LOG_CRIT_MB  = float(getattr(_cfg, "HEALTH_LOG_SIZE_CRIT_MB", 200))


# ── individual checks ─────────────────────────────────────────────────────────

def _check_scan_freshness() -> tuple[int, str]:
    health_file = ROOT / "public" / "data" / "health.json"
    if not health_file.exists():
        return _WARN, "health.json not found — system may not have run yet"
    try:
        h   = json.loads(health_file.read_text())
        gen = h.get("generated_at", "")
        ts  = dt.datetime.fromisoformat(gen)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        age_h = (dt.datetime.now(dt.timezone.utc) - ts).total_seconds() / 3600
        if age_h > STALE_CRIT_H:
            return _CRIT, (
                f"scan stale: health.json is {age_h:.1f}h old "
                f"(critical threshold {STALE_CRIT_H:.0f}h)"
            )
        if age_h > STALE_WARN_H:
            return _WARN, (
                f"scan aging: health.json is {age_h:.1f}h old "
                f"(warn threshold {STALE_WARN_H:.0f}h)"
            )
        return _OK, f"scan fresh — {age_h:.1f}h old"
    except Exception as e:
        return _WARN, f"health.json parse error: {e}"


def _check_journal() -> tuple[int, str]:
    jf = ROOT / "journal" / "scalp_journal.json"
    if not jf.exists():
        return _WARN, "scalp_journal.json not found — no trades recorded yet"
    try:
        j      = json.loads(jf.read_text())
        open_n = len(j.get("open", []))
        closed = len(j.get("closed", []))
        cap    = int(getattr(_cfg, "MAX_OPEN_POSITIONS", 10))
        if open_n >= cap:
            return _WARN, f"open positions at hard cap: {open_n}/{cap}"
        return _OK, f"journal OK — {open_n} open, {closed} closed"
    except Exception as e:
        return _CRIT, f"journal parse error: {e}"


def _check_circuit_breakers() -> tuple[int, str]:
    jf = ROOT / "journal" / "scalp_journal.json"
    if not jf.exists():
        return _OK, "circuit breakers: journal absent (first run)"
    try:
        j  = json.loads(jf.read_text())
        from scanner.broker.circuit_breaker import check_all
        cb = check_all(j, last_anomaly_fired=False)
        if not cb["ok"]:
            return _WARN, f"circuit breaker(s) active: {cb['reason']}"
        return _OK, "circuit breakers: all clear"
    except Exception as e:
        return _WARN, f"circuit breaker check failed: {e}"


def _check_log_sizes() -> tuple[int, str]:
    log_files = [
        ROOT / "journal" / "bybit_run.log",
        ROOT / "journal" / "scan.log",
        ROOT / "journal" / "paper_run.log",
    ]
    issues: list[tuple[int, str]] = []
    for lf in log_files:
        if not lf.exists():
            continue
        mb = lf.stat().st_size / 1_048_576
        if mb > LOG_CRIT_MB:
            issues.append((_CRIT, f"{lf.name}: {mb:.0f} MB > {LOG_CRIT_MB:.0f} MB limit"))
        elif mb > LOG_WARN_MB:
            issues.append((_WARN, f"{lf.name}: {mb:.0f} MB > {LOG_WARN_MB:.0f} MB limit"))
    if not issues:
        return _OK, "log sizes: all within limits"
    worst = max(issues, key=lambda x: x[0])
    return worst[0], "; ".join(m for _, m in issues)


def _check_fill_analysis() -> tuple[int, str]:
    fa_file = ROOT / "public" / "data" / "fill_analysis.json"
    if not fa_file.exists():
        return _OK, "fill analysis: no data yet"
    try:
        fa      = json.loads(fa_file.read_text())
        summary = fa.get("all_time", {})
        avg     = summary.get("avg_slip_pct")
        trades  = summary.get("filled_trades", 0)
        if avg is None or trades == 0:
            return _OK, "fill analysis: no filled trades yet"
        warn_pct = float(getattr(_cfg, "SLIPPAGE_WARN_PCT", 0.003)) * 100
        if avg > warn_pct:
            return _WARN, (
                f"avg entry slippage {avg:.3f}% > warn threshold {warn_pct:.3f}% "
                f"over {trades} trades — consider reviewing position sizing"
            )
        return _OK, f"fill analysis: avg slip {avg:.3f}% ({trades} trades)"
    except Exception as e:
        return _WARN, f"fill analysis parse error: {e}"


# ── aggregator ────────────────────────────────────────────────────────────────

def run_all_checks() -> dict:
    """Run every check and return an aggregated health report."""
    raw = {
        "scan_freshness":   _check_scan_freshness(),
        "journal":          _check_journal(),
        "circuit_breakers": _check_circuit_breakers(),
        "log_sizes":        _check_log_sizes(),
        "fill_analysis":    _check_fill_analysis(),
    }
    overall = max(code for code, _ in raw.values())
    return {
        "status":       ["OK", "WARNING", "CRITICAL"][overall],
        "code":         overall,
        "checks":       {
            name: {"code": code, "message": msg}
            for name, (code, msg) in raw.items()
        },
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Vivek's Beta Scanner — system health check")
    ap.add_argument("--json",  action="store_true", help="Output JSON instead of human text")
    ap.add_argument("--alert", action="store_true", help="Fire smart_send if WARNING/CRITICAL")
    args = ap.parse_args()

    result = run_all_checks()

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        icons = {_OK: "✓", _WARN: "⚠", _CRIT: "✗"}
        print(f"\n=== Vivek's Beta Scanner — Health Check  {result['generated_at']} ===")
        print(f"Overall status: {result['status']}\n")
        for name, info in result["checks"].items():
            print(f"  {icons.get(info['code'], '?')}  {name:<22}  {info['message']}")
        print()

    if args.alert and result["code"] >= _WARN:
        try:
            from scanner.broker.alert_router import smart_send
            issues = "; ".join(
                info["message"]
                for info in result["checks"].values()
                if info["code"] >= _WARN
            )
            smart_send(
                "health",
                f"System health: {result['status']}",
                issues,
            )
        except Exception as e:
            print(f"Alert dispatch failed: {e}", file=sys.stderr)

    sys.exit(result["code"])
