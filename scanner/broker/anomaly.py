"""Scan-result and journal anomaly detection.

Flags unusual conditions that may indicate data issues or system problems:
  - Sudden drought in A+/A setups vs rolling history
  - High data-quality skip rate (possible feed issue)
  - Consecutive loss streak
  - Abnormal fill slippage

Fires alert_dispatch events when anomalies are detected.
"""

import logging
import statistics

log = logging.getLogger(__name__)

_MIN_HISTORY_RUNS    = 5     # need this many prior scan runs before comparing
_SETUP_DROP_THRESH   = 0.25  # alert if A+/A count < 25% of rolling average
_DQ_SKIP_RATIO_MAX   = 0.50  # alert if >50% of scanned symbols fail data quality
_CONSEC_LOSS_LIMIT   = 4     # alert after this many consecutive losses
_FILL_SLIP_PCT_LIMIT = 0.03  # alert if fill is >3% off the intended entry price


def check_scan_anomalies(scan: dict, history_counts: list[int]) -> list[str]:
    """Check the latest scan result for anomalies vs historical distribution.

    scan:           the scan result dict (from scalp.json / scalp_crypto.json)
    history_counts: A+/A counts from recent scan runs (oldest first), up to 20 entries.
                    Pass an empty list if no history is available yet.

    Returns a list of anomaly description strings (empty = no anomalies).
    """
    anomalies: list[str] = []

    current_count = sum(
        1 for r in scan.get("results", []) if r.get("grade") in ("A+", "A")
    )

    if len(history_counts) >= _MIN_HISTORY_RUNS:
        avg = statistics.mean(history_counts)
        if avg > 0 and current_count < avg * _SETUP_DROP_THRESH:
            anomalies.append(
                f"setup drought: {current_count} A+/A signals vs "
                f"rolling avg {avg:.1f} ({current_count/avg*100:.0f}% of normal)"
            )

    quality_skipped = scan.get("quality_skipped", 0)
    total_scanned   = len(scan.get("results", [])) + quality_skipped
    if total_scanned > 0 and quality_skipped / total_scanned > _DQ_SKIP_RATIO_MAX:
        anomalies.append(
            f"data quality: {quality_skipped}/{total_scanned} symbols skipped "
            "— possible data feed issue"
        )

    for a in anomalies:
        log.warning("scan anomaly: %s", a)
    return anomalies


def check_journal_anomalies(j: dict) -> list[str]:
    """Check the journal for abnormal P&L patterns or fill discrepancies.

    Returns a list of anomaly description strings (empty = no anomalies).
    """
    anomalies: list[str] = []
    closed = [t for t in j.get("closed", []) if not t.get("skip_daily_count")]

    # Consecutive loss streak
    consec = 0
    for t in reversed(closed):
        if t.get("pnl", 0) < 0:
            consec += 1
        else:
            break
    if consec >= _CONSEC_LOSS_LIMIT:
        anomalies.append(
            f"consecutive losses: {consec} in a row — "
            "consider reviewing regime or reducing position size"
        )

    # Fill-price divergence (live trades only, where fill_price is recorded)
    for pos in list(j.get("open", [])) + closed:
        fill  = pos.get("fill_price")
        entry = pos.get("entry")
        if fill and entry and float(entry) > 0:
            slip = abs(float(fill) - float(entry)) / float(entry)
            if slip > _FILL_SLIP_PCT_LIMIT:
                anomalies.append(
                    f"fill slippage: {pos.get('symbol','?')} filled at "
                    f"{float(fill):.6f} vs intended {float(entry):.6f} "
                    f"({slip*100:.1f}% off)"
                )

    for a in anomalies:
        log.warning("journal anomaly: %s", a)
    return anomalies


def run_checks(scan: dict, j: dict, history_counts: list[int]) -> bool:
    """Run all anomaly checks, dispatch alerts for any found.

    Returns True if any anomaly was detected (circuit_breaker can use this
    to pause new orders when ANOMALY_PAUSE_ON_TRIGGER is enabled).
    """
    from .alert_dispatch import send as _send

    fired = False
    for issue in check_scan_anomalies(scan, history_counts):
        _send("anomaly", "Scan anomaly detected", issue)
        fired = True

    for issue in check_journal_anomalies(j):
        _send("anomaly", "Journal anomaly detected", issue)
        fired = True

    return fired
