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

from scanner import config as _cfg

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


def check_strategy_degradation(journal: dict) -> list[str]:
    """Detect degradation in recent performance vs the all-time baseline.

    Fires when the rolling win rate or expectancy over the last
    ANOMALY_WIN_RATE_WINDOW trades drops materially below all-time values.
    Requires at least EXPECTANCY_MIN_TRADES closed trades before comparing.

    Returns a list of anomaly description strings (empty = no degradation).
    """
    from scanner.broker.expectancy import calc_expectancy

    min_t   = int(getattr(_cfg, "EXPECTANCY_MIN_TRADES", 20))
    window  = int(getattr(_cfg, "ANOMALY_WIN_RATE_WINDOW", 20))
    wr_drop = float(getattr(_cfg, "ANOMALY_WIN_RATE_DROP", 15.0))   # percentage points
    e_drop  = float(getattr(_cfg, "ANOMALY_EXPECTANCY_DROP", 0.3))  # R units

    closed = [t for t in journal.get("closed", []) if not t.get("skip_daily_count")]
    if len(closed) < min_t:
        return []

    all_time = calc_expectancy(closed)
    recent   = calc_expectancy(closed[-window:])
    anomalies: list[str] = []

    drop_wr = all_time["win_rate"] - recent["win_rate"]
    if drop_wr > wr_drop:
        anomalies.append(
            f"strategy degradation: rolling win rate {recent['win_rate']:.0f}% "
            f"vs all-time {all_time['win_rate']:.0f}% "
            f"(drop {drop_wr:.0f}pp over last {window} trades)"
        )

    drop_e = all_time["expectancy_r"] - recent["expectancy_r"]
    if drop_e > e_drop and all_time["expectancy_r"] > 0:
        anomalies.append(
            f"strategy degradation: rolling expectancy {recent['expectancy_r']:.4f}R "
            f"vs all-time {all_time['expectancy_r']:.4f}R "
            f"(drop {drop_e:.4f}R over last {window} trades)"
        )

    for a in anomalies:
        log.warning("strategy degradation: %s", a)
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

    for issue in check_strategy_degradation(j):
        _send("anomaly", "Strategy degradation detected", issue)
        fired = True

    return fired
