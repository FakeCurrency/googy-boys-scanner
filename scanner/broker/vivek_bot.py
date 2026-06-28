"""VIVEK autonomous-bot decision engine — strict VIVEK 5.0 rules.

Pure decision logic (no broker calls) so it is fully testable and auditable. A
runner feeds it VIVEK scan rows + the account equity, PER MARKET; this module
decides what to trade and how big. Wiring it to Bybit/IBKR bracket orders is a
thin layer on top — this module never places an order itself.

The rules it enforces (locked-in, audited on every decision):

  1. A+ ONLY. It will not take A, B+ or WATCH under any circumstances.
  2. ENTRY TYPE is labelled on every trade — reclaim / retest / break — in both
     the logs and the returned ticket, with the full human description.
  3. TIMEFRAME: Weekly plans are primary (less noise); it falls back to the
     Daily plan only if the Weekly one has no armed trigger. The timeframe it
     traded is recorded on the ticket. A runner can override the preference
     (e.g. to mirror the timeframe the user has selected on the chart).
  4. SIZING: risk 0.25–0.5% of equity per trade; leverage is 5× for stocks
     (ASX/NASDAQ) and 3× for crypto. Effective size + leverage are logged.
  5. BOOK (per market): at most 10 open, of which AT LEAST 4 must be short — so
     at most 6 longs. The bot reserves the short slots to hold a deliberate
     short bias and never lets the book run long-heavy. One position per symbol.

Single source of truth: it reads the SAME per-timeframe plans the row, chart and
journal use (row["plans"][tf]) — it never recomputes a level.
"""

import logging

from scanner import config as _cfg

log = logging.getLogger("vivek_bot")

_LEVEL_KEYS = ("entry", "stop", "tp1", "tp2", "tp3")

# Rule 2 — the three (and only three) allowed entry types, with auditable labels.
ENTRY_TYPE_LABEL = {
    "reclaim": "Close back above the 200 SMA after rejection",
    "retest":  "Retest of the level with confirmation",
    "break":   "Break of small structure near the 200 SMA",
}


def _direction(row: dict) -> str:
    return "short" if str(row.get("dir", "LONG")).upper() == "SHORT" else "long"


# Non-operating vehicles the bot should not trade (REITs / ETFs / LICs / funds).
# A REIT or fund hugs its 200 SMA, so it over-produces "reactions" without being
# a real momentum/trend trade. Detected by sector + name so it catches funds that
# sit under an operating-sector label (e.g. a real-estate income fund tagged
# "Financial Services") as well as the ETFs/LICs that have no GICS sector at all.
_FUND_NAME_KEYWORDS = ("REIT", "TRUST", "FUND", "ETF", "SPDR", "ISHARES",
                       "VANGUARD", "BETASHARES", "VANECK", "GLOBAL X")
_FUND_SECTOR_HINTS = ("reit", "real estate investment trust")
_NON_OPERATING_SECTORS = {"not applicable", "not applic", "n/a"}   # the ETF/LIC/fund tag


def _is_fund_or_reit(row: dict) -> bool:
    name = str(row.get("name") or "").upper()
    sector = str(row.get("sector") or "").strip().lower()
    if any(h in sector for h in _FUND_SECTOR_HINTS):
        return True
    if sector in _NON_OPERATING_SECTORS:              # ETFs / LICs carry no operating sector
        return True
    return any(kw in name for kw in _FUND_NAME_KEYWORDS)


def _pick_plan(row: dict, prefer_tf: str) -> tuple[str | None, dict | None]:
    """Rule 3 — choose the timeframe plan to trade.

    Weekly (or the runner-supplied `prefer_tf`) is primary; fall back to the
    other timeframe. Only an ARMED plan with a complete level set qualifies.
    Returns (timeframe, plan) or (None, None).
    """
    plans = row.get("plans") or {}
    order = [prefer_tf] + [tf for tf in ("1W", "1D") if tf != prefer_tf]
    for tf in order:
        p = plans.get(tf)
        if p and p.get("armed") and all(p.get(k) is not None for k in _LEVEL_KEYS):
            return tf, p
    return None, None


# ── 1. should we take it? (A+ only, armed, ordered, R:R, labelled) ────────────

def evaluate_setup(row: dict, prefer_tf: str | None = None, min_rr: float | None = None) -> dict:
    """Decide whether a VIVEK row is takeable, on the preferred timeframe's plan.

    Returns a decision dict; on a take it carries the timeframe, the entry-type
    label, and the plan it will trade. Every skip carries an auditable code.
    """
    prefer_tf = prefer_tf or _cfg.VIVEK_BOT_PREFER_TF
    min_rr = _cfg.VIVEK_BOT_MIN_RR if min_rr is None else min_rr
    sym = row.get("symbol", "?")
    grade = row.get("grade")

    def skip(code, reason):
        log.info("SKIP  %-8s [%s] %s", sym, code, reason)
        return {"take": False, "grade": grade, "reason": reason, "code": code}

    # Long-only: shorts lost on every market in the backtest, so the bot skips
    # them while VIVEK_BOT_ALLOW_SHORTS is False.
    if not getattr(_cfg, "VIVEK_BOT_ALLOW_SHORTS", True) and _direction(row) == "short":
        return skip("shorts_disabled", f"{sym} is a short — bot is long-only")

    # Don't trade REITs / ETFs / LICs / managed funds (they hug the 200 SMA).
    if getattr(_cfg, "VIVEK_BOT_EXCLUDE_FUNDS", True) and _is_fund_or_reit(row):
        return skip("fund_reit", f"{sym} is a REIT/ETF/fund — excluded from bot trading")

    # Rule 1 — A+ ONLY.
    if grade != _cfg.VIVEK_BOT_MIN_GRADE:
        return skip("not_a_plus", f"grade {grade} — bot trades {_cfg.VIVEK_BOT_MIN_GRADE} only")

    # Rule 3 — pick the timeframe plan (Weekly primary).
    tf, plan = _pick_plan(row, prefer_tf)
    if plan is None:
        return skip("no_armed_plan", f"no armed {prefer_tf}/1D plan to trade")

    direction = _direction(row)
    e, s = float(plan["entry"]), float(plan["stop"])
    t1, t2, t3 = float(plan["tp1"]), float(plan["tp2"]), float(plan["tp3"])
    ordered = (s < e < t1 < t2 < t3) if direction == "long" else (s > e > t1 > t2 > t3)
    if not ordered:
        return skip("bad_level_order", f"{tf} levels not ordered for {direction}")

    rr = float(plan.get("rr", 0) or 0)
    if rr < min_rr:
        return skip("low_rr", f"{tf} R:R {rr:.1f} < min {min_rr:.1f}")

    # Rule 2 — entry-type label (must be one of the three known triggers).
    et = plan.get("entry_trigger") or (row.get("entry_types") or [None])[0]
    # Favour the strongest trigger — skip the entry types the backtest flagged
    # weak (default: retest). Reclaim carries the edge.
    if et in set(getattr(_cfg, "VIVEK_BOT_SKIP_ENTRY_TYPES", ()) or ()):
        return skip("weak_entry_type", f"{et} entry — backtest weak; bot favours reclaim")
    et_label = ENTRY_TYPE_LABEL.get(et)
    if et_label is None:
        return skip("unknown_entry_type", f"entry type {et!r} not one of reclaim/retest/break")

    why = f"A+ {direction} · {tf} · {et}: {et_label} · entry {e:g} SL {s:g} · R:R {rr:.1f}"
    log.info("TAKE  %-8s %s", sym, why)
    return {"take": True, "grade": grade, "direction": direction, "timeframe": tf,
            "entry_type": et, "entry_type_label": et_label, "rr": rr,
            "reason": why, "code": "OK", "_plan": plan}


# ── 2. position sizing (0.25–0.5% risk; 5× stocks / 3× crypto) ────────────────

def _leverage_for(market: str | None) -> float:
    return float(_cfg.VIVEK_BOT_LEVERAGE.get(market, _cfg.VIVEK_BOT_LEVERAGE["asx"]))


def size_position(equity: float, entry: float, stop: float,
                  risk_pct: float | None = None, max_leverage: float | None = None) -> dict:
    """Risk-based size: risk a small % of equity, cap implied leverage at the
    per-market leverage. Risk % is clamped to the 0.25–0.5 band."""
    risk_pct = _cfg.VIVEK_BOT_RISK_PCT if risk_pct is None else risk_pct
    risk_pct = min(max(risk_pct, 0.25), _cfg.VIVEK_RISK_PCT_MAX)      # 0.25–0.5 band
    max_lev = _cfg.VIVEK_MAX_LEVERAGE if max_leverage is None else max_leverage

    stop_dist = abs(entry - stop)
    if stop_dist <= 0 or entry <= 0 or equity <= 0:
        return {"units": 0.0, "notional": 0.0, "risk_usd": 0.0,
                "risk_pct": risk_pct, "leverage": 0.0, "stop_dist": stop_dist,
                "leverage_capped": False}

    risk_usd = equity * (risk_pct / 100.0)
    units = risk_usd / stop_dist
    notional = units * entry

    # Cap notional so implied leverage never exceeds the per-market max.
    max_notional = equity * max_lev
    capped = False
    if notional > max_notional:
        capped = True
        units = max_notional / entry
        notional = units * entry
        risk_usd = units * stop_dist

    return {
        "units": round(units, 8), "notional": round(notional, 2),
        "risk_usd": round(risk_usd, 2), "risk_pct": risk_pct,
        "leverage": round(notional / equity if equity else 0.0, 2),
        "stop_dist": round(stop_dist, 8), "leverage_capped": capped,
    }


# ── 3. full trade plan ────────────────────────────────────────────────────────

def plan_trade(row: dict, equity: float, market: str | None = None,
               prefer_tf: str | None = None, risk_pct: float | None = None,
               min_rr: float | None = None) -> dict:
    """Combine evaluate + size into a ready-to-place ticket (or a skip)."""
    decision = evaluate_setup(row, prefer_tf, min_rr)
    if not decision["take"]:
        return {**decision, "plan": None}

    plan = decision["_plan"]
    tf = decision["timeframe"]
    direction = decision["direction"]
    entry, stop = float(plan["entry"]), float(plan["stop"])
    tps = [float(plan["tp1"]), float(plan["tp2"]), float(plan["tp3"])]
    max_lev = _leverage_for(market)
    sizing = size_position(equity, entry, stop, risk_pct, max_lev)
    scale = plan.get("scale") or (
        _cfg.VIVEK_TP_SCALE_LONG if direction == "long" else _cfg.VIVEK_TP_SCALE_SHORT)

    ticket = {
        "symbol": row.get("symbol"),
        "market": market,
        "direction": direction,
        "timeframe": tf,                              # Rule 3 — recorded per trade
        "entry_type": decision["entry_type"],         # Rule 2 — labelled per trade
        "entry_type_label": decision["entry_type_label"],
        "grade": "A+",
        "entry": entry, "stop": stop,
        "tp1": tps[0], "tp2": tps[1], "tp3": tps[2],
        "tp_plan": [
            {"level": tps[0], "book_pct": scale[0], "sl_move": "breakeven"},
            {"level": tps[1], "book_pct": scale[1], "sl_move": "below_support"},
            {"level": tps[2], "book_pct": scale[2], "sl_move": "hold"},
        ],
        "scale": scale, "rr": decision["rr"], "leverage_target": max_lev,
        **sizing,
    }
    log.info("PLAN  %-8s A+ %-5s %s · %s · entry %g SL %g · %g units  $%.0f notional  "
             "risk $%.2f (%.2f%%)  lev %.1fx%s",
             ticket["symbol"], direction, tf, ticket["entry_type"], entry, stop,
             ticket["units"], ticket["notional"], ticket["risk_usd"], ticket["risk_pct"],
             ticket["leverage"], "  [lev-capped]" if ticket["leverage_capped"] else "")
    return {**decision, "plan": ticket}


# ── 4. live management: scale-outs + SL movement (never adverse) ──────────────

def _favourable(new_sl: float, cur_sl: float, is_long: bool) -> bool:
    """A long's SL may only move UP; a short's only DOWN. Never against the trade."""
    return new_sl > cur_sl if is_long else new_sl < cur_sl


def manage_position(pos: dict, price: float, support: float | None = None) -> list[dict]:
    """Apply the 5.0 management rules to an open position at `price`.

    Mutates `pos` (sets tp*_hit flags, advances `stop`) and returns the actions
    taken: book at TP1/TP2/TP3, SL → break-even at TP1, SL → new support at TP2.
    SL is only ever moved in the trade's favour.
    """
    is_long = pos.get("direction", "long") == "long"
    scale = pos.get("scale") or (
        _cfg.VIVEK_TP_SCALE_LONG if is_long else _cfg.VIVEK_TP_SCALE_SHORT)
    reached = (lambda lvl: price >= lvl) if is_long else (lambda lvl: price <= lvl)
    sym = pos.get("symbol", "?")
    actions: list[dict] = []

    if not pos.get("tp1_hit") and pos.get("tp1") is not None and reached(pos["tp1"]):
        pos["tp1_hit"] = True
        actions.append({"action": "scale", "tp": "TP1", "book_pct": scale[0], "price": price})
        be = pos["entry"]
        if _favourable(be, pos["stop"], is_long):
            pos["stop"] = be
            actions.append({"action": "sl", "to": "breakeven", "price": be})
        log.info("MANAGE %-8s TP1 @ %g → book %d%%, SL → break-even (%g)",
                 sym, price, round(scale[0] * 100), be)

    if not pos.get("tp2_hit") and pos.get("tp2") is not None and reached(pos["tp2"]):
        pos["tp2_hit"] = True
        actions.append({"action": "scale", "tp": "TP2", "book_pct": scale[1], "price": price})
        new_sl = support if support is not None else pos.get("tp1", pos["stop"])
        if new_sl is not None and _favourable(new_sl, pos["stop"], is_long):
            pos["stop"] = new_sl
            actions.append({"action": "sl", "to": "support", "price": new_sl})
        log.info("MANAGE %-8s TP2 @ %g → book %d%%, SL → %g (locked structure)",
                 sym, price, round(scale[1] * 100), pos["stop"])

    if not pos.get("tp3_hit") and pos.get("tp3") is not None and reached(pos["tp3"]):
        pos["tp3_hit"] = True
        actions.append({"action": "scale", "tp": "TP3", "book_pct": scale[2], "price": price})
        log.info("MANAGE %-8s TP3 @ %g → book %d%% (runner trails)",
                 sym, price, round(scale[2] * 100))

    return actions


# ── 5. process one market's scan into plans, with the book rules ──────────────

def decide(rows: list[dict], equity: float, market: str | None = None,
           prefer_tf: str | None = None, open_book: list[dict] | None = None, **kw) -> dict:
    """Run the engine over ONE market's VIVEK scan and apply the book rules.

    Rows are expected best-first (the scan sorts by grade → score → R:R). The
    book caps (Rule 5) are evaluated against the CURRENT open book passed in via
    `open_book` (a list of {symbol, direction} already held in this market), so
    the limits hold ACROSS RUNS, not just within one scan: at most
    VIVEK_BOT_MAX_POSITIONS (10) open, at most (10 − VIVEK_BOT_MIN_SHORTS) = 6
    long so ≥4 short slots stay reserved, and one position per symbol.

    Returns {plans, skipped, summary}; `plans` are the NEW entries this run.
    """
    from collections import Counter

    max_pos = kw.get("max_positions", _cfg.VIVEK_BOT_MAX_POSITIONS)
    min_shorts = kw.get("min_shorts", _cfg.VIVEK_BOT_MIN_SHORTS)
    max_long = max(0, max_pos - min_shorts)          # reserve the short slots
    plans, skipped = [], []
    reasons: Counter = Counter()

    # Seed the counters from the positions ALREADY open in this market, so new
    # entries can only fill the remaining capacity.
    book = open_book or []
    open_syms: set[str] = {str(p.get("symbol") or "").upper() for p in book}
    existing = len(book)
    longs = sum(1 for p in book if str(p.get("direction")) == "long")
    shorts = sum(1 for p in book if str(p.get("direction")) == "short")

    def drop(out, code, reason):
        log.info("SKIP  %-8s [%s] %s", (out.get("plan") or out).get("symbol", "?"), code, reason)
        reasons[code] += 1
        skipped.append({**out, "take": False, "code": code, "reason": reason, "plan": None})

    for row in rows:
        out = plan_trade(row, equity, market=market, prefer_tf=prefer_tf, **{
            k: kw[k] for k in ("risk_pct", "min_rr") if k in kw})
        if not out.get("plan"):
            reasons[out.get("code", "skip")] += 1
            skipped.append(out)
            continue
        sym = str(row.get("symbol") or "").upper()
        direction = out["direction"]
        if sym in open_syms:
            drop(out, "dup_symbol", f"already holding {sym}")
        elif longs + shorts >= max_pos:                 # existing + taken so far
            drop(out, "book_full", f"already at the {max_pos}-position cap for {market}")
        elif direction == "long" and longs >= max_long:
            drop(out, "long_cap", f"long cap {max_long} reached — reserving the ≥{min_shorts}-short slots")
        else:
            plans.append(out)
            open_syms.add(sym)
            if direction == "long":
                longs += 1
            else:
                shorts += 1

    short_bias_met = shorts >= min_shorts
    summary = {
        "market": market, "setups": len(rows), "existing": existing,
        "taken": len(plans), "total_open": longs + shorts,
        "longs": longs, "shorts": shorts, "min_shorts": min_shorts,
        "short_bias_met": short_bias_met,
        "skipped": len(skipped), "skip_reasons": dict(reasons),
    }
    log.info("VIVEK bot [%s]: +%d new (book %d→%d) — %d long / %d short%s · skips: %s",
             market, summary["taken"], existing, summary["total_open"], longs, shorts,
             "" if short_bias_met else f"  ⚠ short bias unmet (<{min_shorts})",
             summary["skip_reasons"] or "none")
    return {"plans": plans, "skipped": skipped, "summary": summary}
