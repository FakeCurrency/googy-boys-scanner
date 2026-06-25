"""Portfolio-level risk management engine (Phase 5).

Functions:
  account_size()               — effective account size (config or live wallet)
  current_equity_and_peak()    — reconstruct equity curve from closed trades
  current_drawdown()           — current drawdown as a fraction (0.0–1.0)
  portfolio_heat()             — total open risk as a fraction of account size
  check_portfolio_heat()       — {ok, heat, limit, reason}
  check_drawdown()             — {ok, dd, action, reason}
  dynamic_size_multiplier()    — combined drawdown + regime size multiplier
  sector_exposure_usd()        — {sector: total_risk_usd}
  check_sector_cap()           — {ok, sector, exposure, limit, reason}
  check_max_positions()        — {ok, open, cap, reason}
  check_order_size()           — {ok, notional, reason}  fat-finger guard
"""

import logging
from scanner import config as _cfg

log = logging.getLogger(__name__)


# ── account size ─────────────────────────────────────────────────────────────

def account_size() -> float:
    """Effective account size for risk calculations.

    Uses ACCOUNT_OVERRIDE_USD if set (> 0), otherwise SCALP_STARTING_CAPITAL.
    In production, callers can pass the live wallet_balance() result instead.
    """
    override = float(getattr(_cfg, "ACCOUNT_OVERRIDE_USD", 0))
    if override > 0:
        return override
    return float(getattr(_cfg, "SCALP_STARTING_CAPITAL", 20_000))


# ── equity curve ─────────────────────────────────────────────────────────────

def current_equity_and_peak(journal: dict) -> tuple[float, float]:
    """Reconstruct equity curve from closed trades.

    Returns (current_equity, peak_equity).  Starts from account_size() as the
    baseline and applies each closed trade's realised P&L in chronological order.
    """
    closed = sorted(
        journal.get("closed", []),
        key=lambda x: (x.get("session_day", ""), x.get("opened_ts", "")),
    )
    equity = account_size()
    peak   = equity
    for t in closed:
        equity += t.get("pnl", 0)
        if equity > peak:
            peak = equity
    return equity, peak


def current_drawdown(journal: dict) -> float:
    """Current drawdown as a fraction (0.0 = no drawdown, 0.15 = 15% below peak)."""
    equity, peak = current_equity_and_peak(journal)
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - equity) / peak)


# ── portfolio heat ────────────────────────────────────────────────────────────

def portfolio_heat(open_positions: list[dict]) -> float:
    """Total open risk as a fraction of account size.

    Positions that have moved to break-even (stop_at_breakeven=True, or whose
    recorded stop equals their entry) contribute zero — their runner is risk-free
    and the freed budget is available for new entries.  This mirrors the JS
    engine's getPositionOpenRisk() which returns 0 when stop == entry.
    """
    total_risk = 0.0
    for p in open_positions:
        at_be = p.get("stop_at_breakeven") or (
            p.get("stop") is not None
            and p.get("entry") is not None
            and float(p.get("stop", 0)) == float(p.get("entry", 0))
        )
        if not at_be:
            total_risk += p.get("risk_per_trade", 0)
    return total_risk / max(account_size(), 1)


def check_portfolio_heat(open_positions: list[dict]) -> dict:
    heat  = portfolio_heat(open_positions)
    limit = float(getattr(_cfg, "PORTFOLIO_HEAT_LIMIT", 0.07))
    ok    = heat < limit
    if not ok:
        log.warning("portfolio heat %.1f%% >= limit %.1f%%", heat * 100, limit * 100)
    return {
        "ok":     ok,
        "heat":   round(heat, 4),
        "limit":  limit,
        "reason": f"portfolio heat {heat:.1%} ≥ limit {limit:.1%}" if not ok else "",
    }


# ── drawdown circuit breaker ──────────────────────────────────────────────────

def check_drawdown(journal: dict) -> dict:
    """Return circuit-breaker decision based on drawdown from equity peak.

    action: "none" | "pause" | "close_all"
    """
    dd       = current_drawdown(journal)
    pause_at = float(getattr(_cfg, "MAX_DRAWDOWN_PAUSE", 0.12))
    close_at = float(getattr(_cfg, "MAX_DRAWDOWN_CLOSE", 0.15))

    action = "none"
    ok     = True
    if dd >= close_at:
        action, ok = "close_all", False
        log.critical("DRAWDOWN %.1f%% >= close threshold %.1f%% → close_all",
                     dd * 100, close_at * 100)
    elif dd >= pause_at:
        action, ok = "pause", False
        log.warning("DRAWDOWN %.1f%% >= pause threshold %.1f%% → pausing new trades",
                    dd * 100, pause_at * 100)

    return {
        "ok":              ok,
        "dd":              round(dd, 4),
        "action":          action,
        "pause_threshold": pause_at,
        "close_threshold": close_at,
        "reason":          f"drawdown {dd:.1%} — {action}" if not ok else "",
    }


# ── dynamic sizing ────────────────────────────────────────────────────────────

def dynamic_size_multiplier(journal: dict, regime: str = "trending") -> float:
    """Return a combined size multiplier based on drawdown level and market regime.

    The multiplier is floored at 0.25 to avoid near-zero order sizes.
    """
    dd       = current_drawdown(journal)
    halve_at = float(getattr(_cfg, "DRAWDOWN_HALVE_SIZE_AT", 0.08))
    mult     = 1.0

    if dd >= halve_at:
        mult *= 0.5
        log.info("drawdown %.1f%% ≥ halve threshold %.1f%% → 0.5× size",
                 dd * 100, halve_at * 100)

    if regime == "ranging":
        ranging_mult = float(getattr(_cfg, "REGIME_RANGING_RISK_MULT", 0.5))
        mult *= ranging_mult

    return max(mult, 0.25)


# ── sector exposure ───────────────────────────────────────────────────────────

def sector_exposure_usd(open_positions: list[dict]) -> dict[str, float]:
    """Return {sector_label: total_risk_usd} for all open positions."""
    exp: dict[str, float] = {}
    for p in open_positions:
        sector = p.get("sector") or p.get("corr_group") or "unknown"
        exp[sector] = exp.get(sector, 0) + p.get("risk_per_trade", 0)
    return exp


def check_sector_cap(open_positions: list[dict], new_pos: dict) -> dict:
    """Check whether adding new_pos would breach the per-sector exposure limit."""
    cap_pct   = float(getattr(_cfg, "SECTOR_EXPOSURE_CAP", 0.40))
    cap_usd   = account_size() * cap_pct
    sector    = new_pos.get("sector") or new_pos.get("corr_group") or "unknown"
    current   = sector_exposure_usd(open_positions).get(sector, 0)
    new_total = current + new_pos.get("risk_per_trade", 0)
    ok        = new_total <= cap_usd
    if not ok:
        log.warning("sector '%s' exposure $%.0f > cap $%.0f",
                    sector, new_total, cap_usd)
    return {
        "ok":      ok,
        "sector":  sector,
        "exposure": round(new_total, 2),
        "limit":   round(cap_usd, 2),
        "reason":  f"sector '{sector}' exposure ${new_total:.0f} > cap ${cap_usd:.0f}" if not ok else "",
    }


# ── position count ────────────────────────────────────────────────────────────

def check_max_positions(journal: dict) -> dict:
    n   = len(journal.get("open", []))
    cap = int(getattr(_cfg, "MAX_OPEN_POSITIONS", 10))
    ok  = n < cap
    if not ok:
        log.warning("max open positions (%d) reached (currently %d)", cap, n)
    return {
        "ok":     ok,
        "open":   n,
        "cap":    cap,
        "reason": f"max open positions ({cap}) reached" if not ok else "",
    }


# ── order size validation ─────────────────────────────────────────────────────

def check_max_capital(journal: dict) -> dict:
    """Check whether total open notional is within the MAX_MANAGED_CAPITAL_USD cap.

    Computes total notional as the sum of (units × entry) for all open positions.
    This is a rough proxy for deployed capital that catches over-funding before
    an order is submitted.

    Returns {"ok": True} when the cap is disabled (MAX_MANAGED_CAPITAL_USD = 0).
    """
    cap = float(getattr(_cfg, "MAX_MANAGED_CAPITAL_USD", 50_000))
    if cap <= 0:
        return {"ok": True, "deployed": 0.0, "cap": 0.0, "reason": ""}

    open_positions = journal.get("open", [])
    deployed = sum(
        float(p.get("units", 0)) * float(p.get("entry", 0))
        for p in open_positions
    )
    ok = deployed < cap
    if not ok:
        log.warning(
            "MAX CAPITAL CAP: open notional $%.0f ≥ cap $%.0f — blocking new order",
            deployed, cap,
        )
    return {
        "ok":       ok,
        "deployed": round(deployed, 2),
        "cap":      cap,
        "reason":   f"open notional ${deployed:.0f} ≥ max capital cap ${cap:.0f}" if not ok else "",
    }


def check_htf_bias(symbol: str, direction: str, bias_map: dict) -> dict:
    """Verify Weekly + 3D bias aligns with the intended trade direction.

    bias_map format:  { "BTCUSDT": {"weekly": "bull", "threeDay": "bear"}, ... }

    Returns {ok, aligned, strength, reason}.  Blocks ("ok": False) when either
    HTF timeframe explicitly opposes the direction — mirrors JS checkBiasAlignment().
    If no bias data exists for the symbol, the check passes (unknown = no block).

    Controlled by config.HTF_BIAS_REQUIRED.
    """
    if not getattr(_cfg, "HTF_BIAS_REQUIRED", True):
        return {"ok": True, "aligned": True, "strength": "disabled", "reason": ""}

    bias = bias_map.get(symbol)
    if not bias:
        return {"ok": True, "aligned": True, "strength": "unknown",
                "reason": "no bias data — assuming aligned"}

    d         = direction.lower()
    weekly    = (bias.get("weekly") or "").lower()
    three_day = (bias.get("threeDay") or bias.get("three_day") or "").lower()

    w_opposes  = (d == "long" and weekly == "bear") or (d == "short" and weekly == "bull")
    td_opposes = (d == "long" and three_day == "bear") or (d == "short" and three_day == "bull")

    if w_opposes or td_opposes:
        log.warning(
            "HTF bias BLOCKED  %s %s  weekly=%s  3d=%s",
            symbol, direction, weekly, three_day,
        )
        return {
            "ok":      False,
            "aligned": False,
            "strength": "counter",
            "reason":  (
                f"HTF bias conflict — Weekly={bias.get('weekly')} "
                f"3D={bias.get('threeDay')} vs {direction}"
            ),
        }

    w_aligned  = (d == "long" and weekly == "bull") or (d == "short" and weekly == "bear")
    td_aligned = (d == "long" and three_day == "bull") or (d == "short" and three_day == "bear")
    strength   = "aligned" if (w_aligned and td_aligned) else "partial"
    return {"ok": True, "aligned": True, "strength": strength, "reason": ""}


def check_order_size(units: float, entry: float) -> dict:
    """Validate order notional value is within sane bounds.

    Catches fat-finger errors and data anomalies before they reach the broker.
    """
    notional = units * entry
    min_usd  = float(getattr(_cfg, "ORDER_SIZE_MIN_USD", 10))
    max_usd  = float(getattr(_cfg, "ORDER_SIZE_MAX_USD", 5_000))
    if notional < min_usd:
        return {
            "ok": False, "notional": round(notional, 4),
            "reason": f"order notional ${notional:.4f} < minimum ${min_usd:.0f}",
        }
    if notional > max_usd:
        log.error("FAT-FINGER GUARD: order notional $%.2f > maximum $%.0f", notional, max_usd)
        return {
            "ok": False, "notional": round(notional, 2),
            "reason": f"order notional ${notional:.2f} > maximum ${max_usd:.0f} (fat-finger guard)",
        }
    return {"ok": True, "notional": round(notional, 2), "reason": ""}
