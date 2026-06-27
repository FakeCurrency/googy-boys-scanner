"""VIVEK autonomous-bot decision engine — trades 5.0Trading.Bull-style setups.

Pure decision logic (no broker calls) so it is fully testable and portable. A
runner feeds it VIVEK scan rows + live prices; this module decides:

  1. evaluate_setup() — should the bot take this setup at all? (grade, levels,
     R:R, real 200-SMA reaction). Returns a clear take/skip reason for the log.
  2. size_position()  — how big? 0.25–0.5% risk, leverage capped at 5×.
  3. plan_trade()     — the full ticket: direction, entry, SL, TP1/TP2/TP3 with
     the 5.0 scale-outs and the SL-movement plan.
  4. manage_position()— as price hits TP1/TP2/TP3: book the scale-outs and move
     the SL (BE at TP1, below new support at TP2) — NEVER against the position.

Everything logs why it acted so the testnet run is auditable. This is the
foundation for autonomous demo trading; wiring it to Bybit bracket orders is a
thin layer on top (see scanner/broker/bybit_bracket.py).
"""

import logging

from scanner import config as _cfg

log = logging.getLogger("vivek_bot")

_GRADE_RANK = {"A+": 0, "A": 1, "B+": 2, "WATCH": 3}
_LEVEL_KEYS = ("entry", "stop", "tp1", "tp2", "tp3")


# ── 1. should we take it? ─────────────────────────────────────────────────────

def evaluate_setup(row: dict, min_grade: str | None = None, min_rr: float | None = None) -> dict:
    """Decide whether a VIVEK scan row is takeable by the bot.

    Returns {take: bool, grade, reason, code}. The bot only takes strong 5.0
    matches with a complete, sane set of levels and a real 200-SMA reaction.
    """
    min_grade = min_grade or _cfg.VIVEK_BOT_MIN_GRADE
    min_rr = _cfg.VIVEK_BOT_MIN_RR if min_rr is None else min_rr
    sym = row.get("symbol", "?")
    grade = row.get("grade")

    def skip(code, reason):
        log.info("SKIP  %s  [%s] %s", sym, code, reason)
        return {"take": False, "grade": grade, "reason": reason, "code": code}

    if grade not in _GRADE_RANK:
        return skip("unknown_grade", f"unknown grade {grade!r}")
    if _GRADE_RANK[grade] > _GRADE_RANK.get(min_grade, 1):
        return skip("grade_below_min", f"grade {grade} below bot minimum {min_grade}")

    # Every level must be present and ordered correctly for the direction.
    if not all(row.get(k) not in (None, "") for k in _LEVEL_KEYS):
        return skip("incomplete_levels", "missing entry/stop/tp1/tp2/tp3")
    direction = "long" if str(row.get("dir", "LONG")).upper() != "SHORT" else "short"
    e, s = float(row["entry"]), float(row["stop"])
    t1, t2, t3 = float(row["tp1"]), float(row["tp2"]), float(row["tp3"])
    ordered = (s < e < t1 < t2 < t3) if direction == "long" else (s > e > t1 > t2 > t3)
    if not ordered:
        return skip("bad_level_order", "levels not ordered for the trade direction")

    rr = float(row.get("rr", 0) or 0)
    if rr < min_rr:
        return skip("low_rr", f"R:R {rr:.1f} < min {min_rr:.1f}")

    # Must be a genuine reaction at the 200 SMA, not just "near it".
    if not (row.get("at_level") or row.get("reaction") in ("bounce", "reject")):
        return skip("no_clean_reaction", "not at the level / no clean 200-SMA reaction")

    why = (f"{grade} {direction} · {row.get('level_tf', '?')} 200 SMA "
           f"{row.get('reaction', '?')} · R:R {rr:.1f}")
    log.info("TAKE  %s  %s", sym, why)
    return {"take": True, "grade": grade, "reason": why, "code": "OK", "direction": direction}


# ── 2. position sizing (0.25–0.5% risk, ≤5× leverage) ────────────────────────

def size_position(equity: float, entry: float, stop: float,
                  risk_pct: float | None = None, max_leverage: float | None = None) -> dict:
    """Risk-based size. Risk a small % of equity per trade, cap implied leverage."""
    risk_pct = _cfg.VIVEK_RISK_PCT_DEFAULT if risk_pct is None else risk_pct
    risk_pct = min(max(risk_pct, 0.0), _cfg.VIVEK_RISK_PCT_MAX)
    max_lev = _cfg.VIVEK_MAX_LEVERAGE if max_leverage is None else max_leverage

    stop_dist = abs(entry - stop)
    if stop_dist <= 0 or entry <= 0 or equity <= 0:
        return {"units": 0.0, "notional": 0.0, "risk_usd": 0.0,
                "risk_pct": risk_pct, "leverage": 0.0, "stop_dist": stop_dist}

    risk_usd = equity * (risk_pct / 100.0)
    units = risk_usd / stop_dist
    notional = units * entry

    # Cap notional so implied leverage never exceeds the max (risk shrinks if so).
    max_notional = equity * max_lev
    capped = False
    if notional > max_notional:
        capped = True
        units = max_notional / entry
        notional = units * entry
        risk_usd = units * stop_dist

    leverage = notional / equity if equity else 0.0
    return {
        "units": round(units, 8), "notional": round(notional, 2),
        "risk_usd": round(risk_usd, 2), "risk_pct": risk_pct,
        "leverage": round(leverage, 2), "stop_dist": round(stop_dist, 8),
        "leverage_capped": capped,
    }


# ── 3. full trade plan ────────────────────────────────────────────────────────

def plan_trade(row: dict, equity: float, **kw) -> dict:
    """Combine evaluate + size into a ready-to-place ticket (or a skip)."""
    decision = evaluate_setup(row, kw.get("min_grade"), kw.get("min_rr"))
    if not decision["take"]:
        return {**decision, "plan": None}

    direction = decision["direction"]
    entry, stop = float(row["entry"]), float(row["stop"])
    # Conservative by default: the bot operates at ≤ target leverage (3×), not the
    # 5× hard cap — closer to 5.0's 2.5–3× preference.
    max_lev = kw.get("max_leverage")
    if max_lev is None:
        max_lev = _cfg.VIVEK_BOT_TARGET_LEVERAGE
    sizing = size_position(equity, entry, stop, kw.get("risk_pct"), max_lev)
    scale = row.get("scale") or (
        _cfg.VIVEK_TP_SCALE_LONG if direction == "long" else _cfg.VIVEK_TP_SCALE_SHORT)
    tps = [float(row["tp1"]), float(row["tp2"]), float(row["tp3"])]
    plan = {
        "symbol": row.get("symbol"),
        "direction": direction,
        "entry": entry, "stop": stop,
        "tp1": tps[0], "tp2": tps[1], "tp3": tps[2],
        "tp_plan": [
            {"level": tps[0], "book_pct": scale[0], "sl_move": "breakeven"},
            {"level": tps[1], "book_pct": scale[1], "sl_move": "below_support"},
            {"level": tps[2], "book_pct": scale[2], "sl_move": "hold"},
        ],
        "scale": scale,
        **sizing,
    }
    log.info("PLAN  %s  %s  units=%.6f  notional=$%.2f  risk=$%.2f (%.2f%%)  lev=%.1fx",
             plan["symbol"], direction, plan["units"], plan["notional"],
             plan["risk_usd"], plan["risk_pct"], plan["leverage"])
    return {**decision, "plan": plan}


# ── 4. live management: scale-outs + SL movement (never adverse) ──────────────

def _favourable(new_sl: float, cur_sl: float, is_long: bool) -> bool:
    """A long's SL may only move UP; a short's only DOWN. Never against the trade."""
    return new_sl > cur_sl if is_long else new_sl < cur_sl


def manage_position(pos: dict, price: float, support: float | None = None) -> list[dict]:
    """Apply the 5.0 management rules to an open position at `price`.

    Mutates `pos` (sets tp*_hit flags, advances `stop`) and returns the list of
    actions taken this tick: {action: "scale"|"sl", ...}. SL is only ever moved
    in the trade's favour.
    """
    is_long = pos.get("direction", "long") == "long"
    scale = pos.get("scale") or (
        _cfg.VIVEK_TP_SCALE_LONG if is_long else _cfg.VIVEK_TP_SCALE_SHORT)
    reached = (lambda lvl: price >= lvl) if is_long else (lambda lvl: price <= lvl)
    sym = pos.get("symbol", "?")
    actions: list[dict] = []

    # TP1 → book first tranche + SL to break-even.
    if not pos.get("tp1_hit") and pos.get("tp1") is not None and reached(pos["tp1"]):
        pos["tp1_hit"] = True
        actions.append({"action": "scale", "tp": "TP1", "book_pct": scale[0], "price": price})
        be = pos["entry"]
        if _favourable(be, pos["stop"], is_long):
            pos["stop"] = be
            actions.append({"action": "sl", "to": "breakeven", "price": be})
        log.info("MANAGE %s  TP1 hit @ %.6f → book %d%%, SL → break-even (%.6f)",
                 sym, price, round(scale[0] * 100), be)

    # TP2 → book second tranche + SL below new support (fallback: lock TP1).
    if not pos.get("tp2_hit") and pos.get("tp2") is not None and reached(pos["tp2"]):
        pos["tp2_hit"] = True
        actions.append({"action": "scale", "tp": "TP2", "book_pct": scale[1], "price": price})
        new_sl = support if support is not None else pos.get("tp1", pos["stop"])
        if new_sl is not None and _favourable(new_sl, pos["stop"], is_long):
            pos["stop"] = new_sl
            actions.append({"action": "sl", "to": "support", "price": new_sl})
        log.info("MANAGE %s  TP2 hit @ %.6f → book %d%%, SL → %.6f (below new support)",
                 sym, price, round(scale[1] * 100), pos["stop"])

    # TP3 → book third tranche; runner left to trail.
    if not pos.get("tp3_hit") and pos.get("tp3") is not None and reached(pos["tp3"]):
        pos["tp3_hit"] = True
        actions.append({"action": "scale", "tp": "TP3", "book_pct": scale[2], "price": price})
        log.info("MANAGE %s  TP3 hit @ %.6f → book %d%% (runner trails)",
                 sym, price, round(scale[2] * 100))

    return actions


# ── 5. process a whole VIVEK scan into plans + skip reasons ───────────────────

def decide(rows: list[dict], equity: float, **kw) -> dict:
    """Run the decision engine over a VIVEK scan, applying 5.0-style portfolio
    discipline: a few uncorrelated positions, best setups first.

    Rows are expected best-first (the scan sorts by grade → score → R:R). On top
    of the per-setup take/skip rules, the book caps: at most VIVEK_BOT_MAX_POSITIONS
    open, VIVEK_BOT_MAX_PER_SECTOR per sector, and one position per symbol.
    Returns {plans, skipped, summary} — every skip carries an auditable code.
    """
    from collections import Counter

    max_pos = kw.get("max_positions", _cfg.VIVEK_BOT_MAX_POSITIONS)
    max_sector = kw.get("max_per_sector", _cfg.VIVEK_BOT_MAX_PER_SECTOR)
    plans, skipped = [], []
    reasons: Counter = Counter()
    open_syms: set[str] = set()
    sector_n: Counter = Counter()

    def drop(out, code, reason):
        log.info("SKIP  %s  [%s] %s", (out.get("plan") or out).get("symbol", "?"), code, reason)
        reasons[code] += 1
        skipped.append({**out, "take": False, "code": code, "reason": reason, "plan": None})

    for row in rows:
        out = plan_trade(row, equity, **kw)
        if not out.get("plan"):
            reasons[out.get("code", "skip")] += 1
            skipped.append(out)
            continue
        sym = str(row.get("symbol") or "").upper()
        sector = row.get("sector") or ""
        if len(plans) >= max_pos:
            drop(out, "book_full", f"already at the {max_pos}-position cap")
        elif sym in open_syms:
            drop(out, "dup_symbol", f"already holding {sym}")
        elif sector and sector_n[sector] >= max_sector:
            drop(out, "sector_full", f"already {max_sector} positions in {sector}")
        else:
            plans.append(out)
            open_syms.add(sym)
            if sector:
                sector_n[sector] += 1

    summary = {"setups": len(rows), "taken": len(plans),
               "skipped": len(skipped), "skip_reasons": dict(reasons)}
    log.info("VIVEK bot: took %d / %d setups (skips: %s)",
             summary["taken"], summary["setups"], summary["skip_reasons"] or "none")
    return {"plans": plans, "skipped": skipped, "summary": summary}
