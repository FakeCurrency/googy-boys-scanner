"""Circuit breakers — safety layers beyond the daily kill-switch (Phase 5).

check_consecutive_losses()   — pause after N consecutive losing trades
check_drawdown_breaker()     — pause/close at drawdown thresholds (wraps risk_manager)
check_anomaly_breaker()      — pause if anomaly detector has fired
check_all()                  — run all circuit breakers and return aggregated result

Self-healing notifications: check_all() persists breaker state in
journal/alert_state.json["cb_state"] and logs INFO (+ smart_send) whenever a
previously-fired breaker transitions back to ok=True.
"""

import json
import logging
import pathlib

from scanner import config as _cfg
from scanner.scalp_journal import _atomic_write

log  = logging.getLogger(__name__)
ROOT = pathlib.Path(__file__).resolve().parents[2]
_STATE_FILE = ROOT / "journal" / "alert_state.json"


def _load_cb_state() -> dict:
    if _STATE_FILE.exists():
        try:
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            return data.get("cb_state", {})
        except Exception:
            pass
    return {}


def _save_cb_state(cb_state: dict) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        if _STATE_FILE.exists():
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        else:
            data = {}
    except Exception:
        data = {}
    data["cb_state"] = cb_state
    try:
        _atomic_write(_STATE_FILE, json.dumps(data, indent=2))
    except Exception as e:
        log.warning("circuit_breaker: could not save state: %s", e)


def check_consecutive_losses(journal: dict) -> dict:
    """Pause if the last N closed trades are all losses.

    N is controlled by config.CONSEC_LOSS_PAUSE (default 4).
    Trades flagged skip_daily_count (stop-gaps) are excluded.
    """
    n_required = int(getattr(_cfg, "CONSEC_LOSS_PAUSE", 4))
    closed = [t for t in journal.get("closed", []) if not t.get("skip_daily_count")]

    if len(closed) < n_required:
        return {"ok": True, "consec_losses": 0, "threshold": n_required, "reason": ""}

    recent   = closed[-n_required:]
    n_losses = sum(1 for t in recent if t.get("pnl", 0) < 0)
    fired    = n_losses >= n_required

    if fired:
        log.warning("CONSECUTIVE LOSS BREAKER — last %d trades all losses (threshold %d)",
                    n_losses, n_required)
        try:
            from .alert_dispatch import send as _alert
            _alert(
                "anomaly",
                f"Consecutive loss circuit breaker fired",
                f"Last {n_required} trades were all losses. New orders paused until reviewed.",
            )
        except Exception:
            pass

    return {
        "ok":            not fired,
        "consec_losses": n_losses,
        "threshold":     n_required,
        "reason":        f"last {n_losses} consecutive losses ≥ threshold {n_required}" if fired else "",
    }


def check_drawdown_breaker(journal: dict) -> dict:
    """Drawdown circuit breaker — delegates to risk_manager.check_drawdown and
    fires an alert when it triggers."""
    from .risk_manager import check_drawdown
    result = check_drawdown(journal)
    if not result["ok"]:
        try:
            from .alert_dispatch import send as _alert
            _alert(
                "anomaly",
                f"Drawdown circuit breaker: {result['action']}",
                f"Drawdown {result['dd']:.1%} — "
                f"pause threshold {result['pause_threshold']:.0%}, "
                f"close threshold {result['close_threshold']:.0%}.",
            )
        except Exception:
            pass
    return result


def check_anomaly_breaker(last_anomaly_fired: bool = False) -> dict:
    """Block new trades if the anomaly detector has recently fired.

    Controlled by config.ANOMALY_PAUSE_ON_TRIGGER (default True).
    Pass last_anomaly_fired=True when the anomaly module returned alerts on
    the current run.
    """
    if not getattr(_cfg, "ANOMALY_PAUSE_ON_TRIGGER", True):
        return {"ok": True, "paused": False, "reason": ""}
    if last_anomaly_fired:
        log.warning("ANOMALY CIRCUIT BREAKER — anomaly detected, pausing new trades")
        return {
            "ok":     False,
            "paused": True,
            "reason": "anomaly detection fired — pausing new trades until next scan",
        }
    return {"ok": True, "paused": False, "reason": ""}


def check_all(journal: dict, last_anomaly_fired: bool = False) -> dict:
    """Run all circuit breakers; return aggregated {ok, checks, failed, reason}.

    All three checks always run unconditionally so the caller gets a complete
    picture of every active breaker in a single call.  Alerts may fire in
    multiple checks on the same run — that is intentional (each breaker owns its
    own alert so the log contains a full diagnosis).

    Self-healing: when a breaker that was previously fired is now clear, an INFO
    log + smart_send("info", ...) is emitted so the operator knows the condition
    resolved without manual intervention.
    """
    prev_state = _load_cb_state()

    checks: dict[str, dict] = {}
    checks["consecutive_losses"] = check_consecutive_losses(journal)
    checks["drawdown"]           = check_drawdown_breaker(journal)
    checks["anomaly"]            = check_anomaly_breaker(last_anomaly_fired)

    # Detect cleared breakers (was fired → now ok)
    for name, result in checks.items():
        was_fired = prev_state.get(name, False)
        now_ok    = result.get("ok", True)
        if was_fired and now_ok:
            log.info("CIRCUIT BREAKER CLEARED: %s — trading may resume", name)
            try:
                from .alert_router import smart_send
                smart_send(
                    "info",
                    f"Circuit breaker cleared: {name}",
                    "The condition that triggered this breaker has resolved. Trading may resume.",
                )
            except Exception:
                pass

    # Persist current fired-state for next run
    _save_cb_state({name: not r.get("ok", True) for name, r in checks.items()})

    failed = {k: v for k, v in checks.items() if not v.get("ok")}
    ok     = len(failed) == 0
    if not ok:
        reasons = "; ".join(v.get("reason", k) for v in failed.values())
        log.warning("circuit breaker(s) active: %s", reasons)

    return {
        "ok":     ok,
        "checks": checks,
        "failed": list(failed.keys()),
        "reason": "; ".join(v.get("reason", "") for v in failed.values()) if not ok else "",
    }
