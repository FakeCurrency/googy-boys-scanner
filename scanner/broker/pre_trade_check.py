"""Pre-trade risk gate — runs before every order submission (Phase 5).

Single entry point: pre_trade_check(pos, journal, sess_day) returns
{ok, reason, checks, failed} so bybit_run.py makes one go/no-go call.

Checks (in order):
  1.  portfolio_heat   — total open risk % of account (PORTFOLIO_HEAT_LIMIT)
  2.  max_positions    — hard cap on concurrent open positions (MAX_OPEN_POSITIONS)
  3.  drawdown         — equity drawdown circuit breaker (MAX_DRAWDOWN_PAUSE/CLOSE)
  4.  consec_losses    — consecutive loss circuit breaker (CONSEC_LOSS_PAUSE)
  5.  daily_loss       — session P&L vs daily loss cap (SCALP_MAX_DAILY_LOSS)
  6.  daily_cap        — trade count vs daily trade cap (SCALP_MAX_TRADES_PER_DAY)
  7.  corr_cap         — correlation group position limit (SCALP_MAX_PER_GROUP)
  8.  sector_cap       — sector/theme exposure limit (SECTOR_EXPOSURE_CAP)
  9.  order_size       — fat-finger / minimum notional guard
  10. max_capital      — total open notional vs MAX_MANAGED_CAPITAL_USD cap
  11. slippage         — expected slippage tolerance (warn/reject)

bybit_run.py still owns the "already_open" and "not_crypto" gates since those
are signal-selection concerns, not portfolio risk.
"""

import logging
from scanner import config as _cfg
from scanner.scalp_journal import _session_day, _corr_group, MAX_GROUP
from scanner.broker.risk_manager import (
    check_portfolio_heat,
    check_drawdown,
    check_sector_cap,
    check_max_positions,
    check_order_size,
    check_max_capital,
    check_htf_bias,
)
from scanner.broker.circuit_breaker import check_consecutive_losses

log = logging.getLogger(__name__)


def pre_trade_check(
    pos: dict,
    journal: dict,
    sess_day: str = "",
    submitted_this_run: int = 0,
    bias_map: dict | None = None,
) -> dict:
    """Return {ok, reason, checks, failed} for a candidate position.

    pos  — proposed position dict; must include at minimum:
             symbol, direction, entry, stop, units, risk_per_trade,
             sector (or corr_group), asset_type
    journal — live scalp journal dict (open + closed lists)
    sess_day — optional session-day override (YYYY-MM-DD); defaults to today
    submitted_this_run — orders already submitted in the current bybit_run loop
    bias_map — optional {symbol: {weekly, threeDay}} HTF bias map; pass None to
               skip the bias check (treated as "no data — allowed")
    """
    if not sess_day:
        sess_day = _session_day()

    today_closed = [
        c for c in journal.get("closed", [])
        if c.get("session_day") == sess_day and not c.get("skip_daily_count")
    ]
    # today_open filters by session_day intentionally: overnight holds opened on a
    # previous session day are NOT counted here because the daily trade cap (check 6)
    # tracks new trades entered today, not total open positions.  Those older
    # positions ARE counted by portfolio_heat (check 1) and max_positions (check 2),
    # which use all open positions regardless of when they were opened.
    today_open  = [p for p in journal.get("open", []) if p.get("session_day") == sess_day]
    today_pnl   = sum(c.get("pnl", 0) for c in today_closed)
    trades_used = len(today_closed) + len(today_open) + submitted_this_run

    symbol    = pos.get("symbol", "?")
    direction = pos.get("direction", "?")
    entry     = float(pos.get("entry", 0))
    units     = float(pos.get("units", 0))
    checks: dict[str, dict] = {}

    # 1. Portfolio heat
    checks["portfolio_heat"] = check_portfolio_heat(journal.get("open", []))

    # 2. Max open positions
    checks["max_positions"] = check_max_positions(journal)

    # 3. Drawdown circuit breaker
    checks["drawdown"] = check_drawdown(journal)

    # 4. Consecutive loss circuit breaker
    checks["consec_losses"] = check_consecutive_losses(journal)

    # 5. Daily session loss
    max_loss = float(_cfg.SCALP_MAX_DAILY_LOSS)
    if today_pnl < -max_loss:
        checks["daily_loss"] = {
            "ok": False,
            "reason": f"session P&L ${today_pnl:.2f} < -${max_loss:.0f}",
        }
    else:
        checks["daily_loss"] = {"ok": True}

    # 6. Daily trade cap
    max_daily = int(_cfg.SCALP_MAX_TRADES_PER_DAY)
    if trades_used >= max_daily:
        checks["daily_cap"] = {
            "ok": False,
            "reason": f"daily cap ({max_daily}) reached — {trades_used} trades used",
        }
    else:
        checks["daily_cap"] = {"ok": True}

    # 7. Correlation group cap
    group = _corr_group(symbol, pos.get("asset_type", ""), pos.get("sector", ""))
    group_n = sum(
        1 for p in journal.get("open", [])
        if (p.get("corr_group") or _corr_group(
            p["symbol"], p.get("asset_type", ""), p.get("sector", "")
        )) == group
    )
    if group_n >= MAX_GROUP:
        checks["corr_cap"] = {
            "ok": False,
            "reason": f"corr group '{group}' at cap ({group_n}/{MAX_GROUP})",
        }
    else:
        checks["corr_cap"] = {"ok": True}

    # 8. Sector exposure cap
    checks["sector_cap"] = check_sector_cap(journal.get("open", []), pos)

    # 9. Order size validation
    checks["order_size"] = check_order_size(units, entry)

    # 10. Max managed capital cap
    checks["max_capital"] = check_max_capital(journal)

    # 11. Slippage tolerance
    slippage_pct  = float(pos.get("slippage_pct", 0))
    reject_slip   = float(_cfg.SLIPPAGE_REJECT_PCT)
    warn_slip     = float(_cfg.SLIPPAGE_WARN_PCT)
    if slippage_pct > reject_slip:
        checks["slippage"] = {
            "ok": False,
            "reason": f"slippage {slippage_pct:.2%} > reject threshold {reject_slip:.2%}",
        }
    elif slippage_pct > warn_slip:
        log.warning("slippage warn: %s %.2f%% > warn threshold %.2f%%",
                    symbol, slippage_pct * 100, warn_slip * 100)
        checks["slippage"] = {"ok": True}
    else:
        checks["slippage"] = {"ok": True}

    # 12. HTF bias alignment (Weekly + 3D must not oppose direction)
    checks["htf_bias"] = check_htf_bias(symbol, direction, bias_map or {})

    # Aggregate
    failed = {k: v for k, v in checks.items() if not v.get("ok")}
    ok     = len(failed) == 0

    if ok:
        log.info("pre-trade OK  %s %s  trades_used=%d  heat=%.1f%%  dd=%.1f%%",
                 symbol, direction, trades_used,
                 checks["portfolio_heat"].get("heat", 0) * 100,
                 checks["drawdown"].get("dd", 0) * 100)
    else:
        reasons = "; ".join(v.get("reason", k) for k, v in failed.items())
        log.warning("pre-trade BLOCKED  %s %s  — %s", symbol, direction, reasons)

    return {
        "ok":     ok,
        "checks": checks,
        "failed": list(failed.keys()),
        "reason": "; ".join(v.get("reason", "") for v in failed.values()) if not ok else "",
    }
