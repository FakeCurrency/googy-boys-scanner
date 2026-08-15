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
  5. BOOK: the binding ceiling is GLOBAL — config.VIVEK_BOT_MAX_OPEN_TOTAL open
     positions across every market combined (30, owner 2026-07-28), free to sit
     wherever the A+ setups actually are. decide() only ever sees one market, so
     the runner passes the other markets' count in as `open_elsewhere`; the
     per-market cap is set equal to the global one and is no longer what binds.
     One position per symbol, at most config.VIVEK_BOT_MAX_PER_SECTOR (3) per
     sector — the correlation control that stops the book becoming one macro
     bet. If VIVEK_BOT_MIN_SHORTS is non-zero the bot also reserves that many
     short slots and caps longs accordingly (it is 0 today: long-only).

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

    Weekly (or the runner-supplied `prefer_tf`) is primary; fall back through
    3-Day then Daily. (3D was silently invisible here even though the engine
    builds a 3D plan and the 3D-200 level was added for exactly the moves the
    other frames missed.) Only an ARMED plan with a complete level set
    qualifies. Returns (timeframe, plan) or (None, None).
    """
    plans = row.get("plans") or {}
    order = [prefer_tf] + [tf for tf in ("1W", "3D", "1D") if tf != prefer_tf]
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
    # H2 (2026-07-20): buy off the RAW gated grade. row["grade"] is smoothed by
    # display hysteresis — it can hold a decayed setup at A+ for up to 3 scans,
    # and a smoothing device must never authorise an entry. Old scan JSONs
    # without grade_raw fall back to the displayed grade.
    grade = row.get("grade_raw") or row.get("grade")

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

    # Data freshness (2026-07-20): a row computed off a cache-reused frame is
    # days old — its "armed" trigger and prices describe a market that has
    # since moved. Never open a position on stale data.
    max_age = int(getattr(_cfg, "VIVEK_BOT_MAX_DATA_AGE_DAYS", 0) or 0)
    age = int(row.get("data_age_days") or 0)
    if max_age > 0 and age > max_age:
        return skip("stale_data", f"{sym} data is {age}d old (cache reuse) — max {max_age}d")

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

    # Tradeability: a structural stop miles from entry (e.g. −95% on a weekly
    # crypto plan) makes risk-based sizing meaningless — units go microscopic and
    # the "trade" is a lottery ticket. Cap the stop distance as a % of entry.
    max_stop_pct = float(getattr(_cfg, "VIVEK_BOT_MAX_STOP_PCT", 0) or 0)
    if max_stop_pct > 0 and e > 0:
        stop_pct = abs(e - s) / e * 100.0
        if stop_pct > max_stop_pct:
            return skip("wide_stop",
                        f"{tf} stop {stop_pct:.0f}% from entry > max {max_stop_pct:.0f}%")

    # The inverse pathology: a stop <1% from entry is a dead/pegged instrument
    # (stablecoin-likes, defensives glued to the SMA). Risk sizing then buys a
    # leverage-capped MAX position in something that doesn't move — a slot
    # squatter, not a trade.
    min_stop_pct = float(getattr(_cfg, "VIVEK_BOT_MIN_STOP_PCT", 0) or 0)
    if min_stop_pct > 0 and e > 0:
        stop_pct = abs(e - s) / e * 100.0
        if stop_pct < min_stop_pct:
            return skip("stop_too_tight",
                        f"{tf} stop {stop_pct:.2f}% from entry < min {min_stop_pct:g}% — "
                        f"dead/pegged instrument")

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


# ── 2. position sizing (fixed notional; 5× stocks / 3× crypto leverage cap) ───

def _leverage_for(market: str | None) -> float:
    return float(_cfg.VIVEK_BOT_LEVERAGE.get(market, _cfg.VIVEK_BOT_LEVERAGE["asx"]))


def size_position(equity: float, entry: float, stop: float,
                  risk_pct: float | None = None, max_leverage: float | None = None,
                  notional_target: float | None = None) -> dict:
    """Size one position. TWO modes, selected by config, both leverage-capped.

    FIXED NOTIONAL (default since 2026-07-28, owner decision): every entry buys
    the same dollar amount, `VIVEK_BOT_POSITION_NOTIONAL`. Units fall out of the
    price and the DOLLAR RISK becomes the variable — risk_usd = notional x
    (stop_dist / entry) — bounded by the MIN/MAX_STOP_PCT gates to roughly
    $50–$1,250 on a $5,000 position. `risk_pct` is then a *derived, reported*
    number, not an input, and is deliberately NOT clamped to the 0.25–0.5 band:
    clamping a figure nothing consumes would only misreport the real exposure.

    RISK-BASED (the original path, used when VIVEK_BOT_POSITION_NOTIONAL is 0):
    risk a fixed % of equity per trade and let the stop distance set the units.
    Risk % is clamped to the 0.25–0.5 band.

    Pass `notional_target` to force fixed mode explicitly (>0) or force the risk
    path (0) regardless of config — used by the tests to pin both behaviours.
    """
    max_lev = _cfg.VIVEK_MAX_LEVERAGE if max_leverage is None else max_leverage
    fixed = (getattr(_cfg, "VIVEK_BOT_POSITION_NOTIONAL", 0)
             if notional_target is None else notional_target)
    fixed = float(fixed or 0)

    stop_dist = abs(entry - stop)
    if stop_dist <= 0 or entry <= 0 or equity <= 0:
        # Degenerate input: report the CONFIGURED risk_pct in risk mode (what
        # would have been used) and 0.0 in fixed mode (nothing was risked).
        rp = 0.0 if fixed > 0 else min(
            max(_cfg.VIVEK_BOT_RISK_PCT if risk_pct is None else risk_pct, 0.25),
            _cfg.VIVEK_RISK_PCT_MAX)
        return {"units": 0.0, "notional": 0.0, "risk_usd": 0.0,
                "risk_pct": rp, "leverage": 0.0, "stop_dist": stop_dist,
                "leverage_capped": False,
                "sizing_mode": "fixed_notional" if fixed > 0 else "risk_pct"}

    if fixed > 0:
        mode = "fixed_notional"
        notional = fixed
        units = notional / entry
        risk_usd = units * stop_dist
    else:
        mode = "risk_pct"
        risk_pct = _cfg.VIVEK_BOT_RISK_PCT if risk_pct is None else risk_pct
        risk_pct = min(max(risk_pct, 0.25), _cfg.VIVEK_RISK_PCT_MAX)   # 0.25–0.5 band
        risk_usd = equity * (risk_pct / 100.0)
        units = risk_usd / stop_dist
        notional = units * entry

    # Cap notional so implied leverage never exceeds the per-market max. In
    # fixed mode this can only bite on an absurdly small equity (a $5,000
    # position needs just 0.03x of a $150,000 book), but it stays as the
    # backstop that makes the two modes share one invariant.
    max_notional = equity * max_lev
    capped = False
    if notional > max_notional:
        capped = True
        units = max_notional / entry
        notional = units * entry
        risk_usd = units * stop_dist

    if mode == "fixed_notional":
        risk_pct = round(risk_usd / equity * 100.0, 4) if equity else 0.0

    return {
        "units": round(units, 8), "notional": round(notional, 2),
        "risk_usd": round(risk_usd, 2), "risk_pct": risk_pct,
        "leverage": round(notional / equity if equity else 0.0, 2),
        "stop_dist": round(stop_dist, 8), "leverage_capped": capped,
        "sizing_mode": mode,
    }


# ── 2b. review flags — REPORT-ONLY, never a gate ──────────────────────────────
#
# Added 2026-07-28 on the owner's instruction: "flag this in the future so I can
# verify whether Claude or I should take the position or not."
#
# READ THIS BEFORE EDITING. Everything in this section runs AFTER every rule has
# already returned take=True and after the ticket is fully sized. It adds a key
# and returns. It must never skip, resize, or reorder anything — which trades get
# taken, and how big they are, is the owner's call, and a flag exists precisely
# so that call stays his instead of being pre-empted by code. If a future change
# makes a flag suppress a trade, that is a rule change wearing a flag's clothes
# and it needs asking first.
#
# What it measures: a plan's 1R loss against the DAILY LOSS GUARD, not against
# equity. Equity-relative risk stopped being the interesting number when sizing
# went fixed-notional — every position is $5,000, so what varies is the stop
# width, and the stop width is exactly what decides how much of a day's loss
# budget one name can eat.

def daily_loss_limit() -> float:
    """Dollars the daily guard trips at: equity x MAX_DAILY_LOSS_PCT.

    Same two config values vivek_guard.check and kill_switch read, deliberately
    recomputed here rather than imported from either — this is a display figure
    on a plan, and it must not become a reason for the guard and the flag to
    share a code path that a later edit could make circular.
    """
    equity = float(getattr(_cfg, "VIVEK_BOT_ACCOUNT_EQUITY", 0) or 0)
    pct = float(getattr(_cfg, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 0) or 0)
    if equity <= 0 or pct <= 0:
        return 0.0
    return round(equity * pct / 100.0, 2)


def review_flags(ticket: dict) -> list[dict]:
    """Annotations on a ticket the bot has ALREADY decided to take.

    Returns a possibly-empty list. An empty list is the normal case and means
    nothing needed a human look — not that the trade was checked and cleared.
    """
    flags: list[dict] = []
    limit = daily_loss_limit()
    thresh = float(getattr(_cfg, "VIVEK_BOT_REVIEW_DAILY_LOSS_PCT", 0) or 0)
    risk = float(ticket.get("risk_usd") or 0)
    if limit > 0 and thresh > 0 and risk > 0:
        share = risk / limit * 100.0
        if share >= thresh:
            entry = float(ticket.get("entry") or 0)
            stop = float(ticket.get("stop") or 0)
            spct = abs(entry - stop) / entry * 100.0 if entry > 0 else 0.0
            flags.append({
                "code": "heavy_risk",
                "share_pct": round(share, 1),
                "stop_pct": round(spct, 1),
                "risk_usd": round(risk, 2),
                "limit_usd": limit,
                "note": (f"a 1R loss here is ${risk:,.0f} - {share:.0f}% of the "
                         f"${limit:,.0f} daily loss guard, on a {spct:.0f}% stop"),
            })
    return flags


# ── 3. full trade plan ────────────────────────────────────────────────────────

def plan_trade(row: dict, equity: float, market: str | None = None,
               prefer_tf: str | None = None, risk_pct: float | None = None,
               min_rr: float | None = None) -> dict:
    """Combine evaluate + size into a ready-to-place ticket (or a skip)."""
    decision = evaluate_setup(row, prefer_tf, min_rr)
    if not decision["take"]:
        return {**decision, "plan": None}

    # Tradeability: sub-floor prices (e.g. a $0.021 ASX micro-cap) carry spreads
    # worth multiple R — a paper fill at "the price" is fiction. Per-market floor.
    floors = getattr(_cfg, "VIVEK_BOT_MIN_PRICE", None) or {}
    floor = float(floors.get(market, floors.get("default", 0)) or 0)
    px = float(row.get("price") or 0)
    if floor > 0 and 0 < px < floor:
        sym = row.get("symbol", "?")
        reason = f"price {px:g} below the {market} tradeability floor {floor:g}"
        log.info("SKIP  %-8s [min_price] %s", sym, reason)
        return {"take": False, "grade": decision.get("grade"), "reason": reason,
                "code": "min_price", "plan": None}

    plan = decision["_plan"]
    tf = decision["timeframe"]
    direction = decision["direction"]
    entry, stop = float(plan["entry"]), float(plan["stop"])
    tps = [float(plan["tp1"]), float(plan["tp2"]), float(plan["tp3"])]
    max_lev = _leverage_for(market)
    sizing = size_position(equity, entry, stop, risk_pct, max_lev)

    # Liquidity honesty (row["adv_usd"] = 20-day average dollar volume in the
    # market's quote currency, enriched by the runner; unknown = exempt):
    # below the ADV floor a real fill eats multiple R in spread/impact, and
    # even above it the position must stay a sliver of the daily tape.
    adv = row.get("adv_usd")
    if adv is not None and adv > 0:
        sym = row.get("symbol", "?")
        floors = getattr(_cfg, "VIVEK_BOT_MIN_ADV", None) or {}
        min_adv = float(floors.get(market, floors.get("default", 0)) or 0)
        if min_adv > 0 and adv < min_adv:
            reason = (f"20d avg dollar volume {adv:,.0f} below the {market} "
                      f"liquidity floor {min_adv:,.0f}")
            log.info("SKIP  %-8s [illiquid] %s", sym, reason)
            return {"take": False, "grade": decision.get("grade"), "reason": reason,
                    "code": "illiquid", "plan": None}
        max_adv_pct = float(getattr(_cfg, "VIVEK_BOT_MAX_NOTIONAL_PCT_ADV", 0) or 0)
        if max_adv_pct > 0 and sizing["notional"] > adv * (max_adv_pct / 100.0):
            reason = (f"notional {sizing['notional']:,.0f} is "
                      f"{sizing['notional'] / adv * 100:.1f}% of ADV {adv:,.0f} "
                      f"— max {max_adv_pct:g}%")
            log.info("SKIP  %-8s [size_vs_adv] %s", sym, reason)
            return {"take": False, "grade": decision.get("grade"), "reason": reason,
                    "code": "size_vs_adv", "plan": None}
    scale = plan.get("scale") or (
        _cfg.VIVEK_TP_SCALE_LONG if direction == "long" else _cfg.VIVEK_TP_SCALE_SHORT)

    ticket = {
        "symbol": row.get("symbol"),
        "name": row.get("name", row.get("symbol")),
        "sector": row.get("sector", ""),   # persisted on the position so the
        "market": market,                  # sector cap holds ACROSS runs
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
    # REPORT-ONLY (section 2b). The trade is already decided at this point; this
    # only marks the ones worth the owner's eye before they are taken.
    ticket["review"] = review_flags(ticket)
    marks = "".join(f"  [{f['code']}]" for f in ticket["review"])
    log.info("PLAN  %-8s A+ %-5s %s · %s · entry %g SL %g · %g units  $%.0f notional  "
             "risk $%.2f (%.2f%%)  lev %.1fx%s%s",
             ticket["symbol"], direction, tf, ticket["entry_type"], entry, stop,
             ticket["units"], ticket["notional"], ticket["risk_usd"], ticket["risk_pct"],
             ticket["leverage"], "  [lev-capped]" if ticket["leverage_capped"] else "",
             marks)
    for f in ticket["review"]:
        log.warning("REVIEW %-8s %s", ticket["symbol"], f["note"])
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

def _side(direction) -> str | None:
    """`direction` as one of "long" / "short", or None when it is neither.

    Every writer in the tree emits the exact lowercase string, so this is not
    about the happy path — it is about the rows that arrive from somewhere else:
    a hand-edited book, an import, a future broker adapter that says "Buy". The
    counters used to compare with `==` against a raw `str()`, so `"LONG"` was
    silently a third side that no cap counted (TOP100 #22).

    None is returned rather than a guess. The rest of the tree already
    disagrees with itself about what an unreadable direction means —
    `vivek_bot._direction` defaults it to LONG, `vivek_run`'s marking path
    treats it as SHORT — so inventing a side here would just add a third
    opinion. The caller's job is to say so out loud and count the slot.
    """
    s = str(direction or "").strip().lower()
    return s if s in ("long", "short") else None


def _sector_key(symbol: str, sector: str | None, market: str | None) -> str:
    """Sector bucket for the correlation cap. Crypto has no GICS sector, so
    coins get synthetic buckets: the configured majors are 'crypto-major',
    everything else is 'crypto-alt' — 4 alts are usually ONE beta-to-BTC bet."""
    s = str(sector or "").strip().lower()
    if s:
        return s
    if market == "crypto":
        majors = {m.upper() for m in getattr(_cfg, "VIVEK_BOT_CRYPTO_MAJORS", ()) or ()}
        return "crypto-major" if str(symbol or "").upper() in majors else "crypto-alt"
    return ""


def decide(rows: list[dict], equity: float, market: str | None = None,
           prefer_tf: str | None = None, open_book: list[dict] | None = None, **kw) -> dict:
    """Run the engine over ONE market's VIVEK scan and apply the book rules.

    Rows are expected best-first (the scan sorts by grade → score → R:R). The
    book caps (Rule 5) are evaluated against the CURRENT open book passed in via
    `open_book` (a list of {symbol, direction} already held in this market), so
    the limits hold ACROSS RUNS, not just within one scan: at most
    VIVEK_BOT_MAX_POSITIONS open in this market, at most
    (max_positions − VIVEK_BOT_MIN_SHORTS) long so the reserved short slots stay
    free, and one position per symbol. Numbers are deliberately not quoted here
    — scanner/config.py is the single source of truth and this docstring has
    already gone stale once.

    A GLOBAL ceiling across markets is also supported: pass `max_open_total`
    together with `open_elsewhere` (how many positions the OTHER markets are
    holding right now) and the book stops at that total no matter which market
    the setups land in. decide() only ever sees one market, so the runner is
    responsible for counting the others — see vivek_run._open_elsewhere.
    Omit either and the global gate is simply off.

    A DOLLAR ceiling rides alongside it: pass `max_portfolio_notional` together
    with `notional_elsewhere` and total open exposure — this market's book, plus
    everything taken this run, plus the other markets — stops at that figure. It
    is the exposure twin of the position cap, is off unless asked for in the
    same way, and fails closed through the same unreadable-sibling gate.

    Returns {plans, skipped, summary}; `plans` are the NEW entries this run.
    """
    from collections import Counter

    max_pos = kw.get("max_positions", _cfg.VIVEK_BOT_MAX_POSITIONS)
    max_total = int(kw.get("max_open_total", 0) or 0)
    # open_elsewhere=None means the runner could not read a sibling market's
    # book. A global risk cap that quietly ignores the markets it cannot see is
    # worse than one that pauses, so unknown = take nothing (see the gate below).
    _oe = kw.get("open_elsewhere", 0)
    open_elsewhere = 0 if _oe is None else int(_oe or 0)
    # Dollar twin of the position ceiling (2026-07-28): total OPEN NOTIONAL
    # across every market may not exceed this. OFF unless the caller asks,
    # exactly like max_open_total above — both are CROSS-MARKET figures that
    # decide() cannot compute for itself, so defaulting them from config would
    # mean silently enforcing a ceiling against a number (0 elsewhere) that only
    # the runner can actually supply. The backtester and tooling call decide()
    # without either kwarg and must keep getting plain per-market behaviour;
    # vivek_run passes both from config on every real run.
    max_notional_total = float(kw.get("max_portfolio_notional", 0) or 0)
    _ne = kw.get("notional_elsewhere", 0)
    notional_elsewhere = 0.0 if _ne is None else float(_ne or 0)
    # EITHER cross-market figure coming back unknown fails BOTH gates closed —
    # a risk cap that quietly ignores the markets it cannot see is worse than
    # one that pauses. Only the ceiling actually configured can trip this: with
    # the dollar cap off, an unknown notional is irrelevant and vice versa.
    elsewhere_unknown = bool((max_total and _oe is None)
                             or (max_notional_total and _ne is None))
    min_shorts = kw.get("min_shorts", _cfg.VIVEK_BOT_MIN_SHORTS)
    max_long = max(0, max_pos - min_shorts)          # reserve the short slots
    plans, skipped = [], []
    reasons: Counter = Counter()

    # Seed the counters from the positions ALREADY open in this market, so new
    # entries can only fill the remaining capacity.
    book = open_book or []
    open_syms: set[str] = {str(p.get("symbol") or "").upper() for p in book}
    existing = len(book)
    # THE POSITION CAP COUNTS ROWS; THE SIDE CAP COUNTS SIDES (2026-07-28,
    # TOP100 #22). These used to be the same number: the ceiling was tested
    # against `longs + shorts`, so any row whose `direction` was not the exact
    # lowercase string counted as NEITHER and the book was allowed to run one
    # position over its own limit per malformed row. `_side` now reads the field
    # the way every other consumer means it (stripped, case-folded) and
    # `open_count` tracks the rows themselves, so a row nobody can classify
    # still occupies the slot it is actually occupying.
    #
    # This can only ever TIGHTEN: every counter it changes goes up, never down,
    # so no trade blocked today becomes takeable. It moves no threshold and
    # touches no filter, grade or ordering — the caps simply count what they
    # have always claimed to count.
    # `test_the_direction_repair_can_only_ever_block_more_never_fewer` pins that.
    unclassified = [p for p in book if _side(p.get("direction")) is None]
    longs = sum(1 for p in book if _side(p.get("direction")) == "long")
    shorts = sum(1 for p in book if _side(p.get("direction")) == "short")
    open_count = existing                      # rows held, whatever side they are
    if unclassified:
        # Never silent. A side cap that cannot see a position is a real hole,
        # and the row is far more likely to be a hand edit or an import than
        # anything the runner wrote — so name the symbols, not just the count.
        log.warning("vivek_bot [%s]: %d of %d open rows carry an unreadable "
                    "`direction` (%s) - they hold slots against the position cap "
                    "but cannot be counted by the long/short caps",
                    market, len(unclassified), existing,
                    ", ".join(sorted(str(p.get("symbol") or "?")
                                     for p in unclassified)[:8]))
    # Notional already committed in THIS market. Rows written before the
    # fixed-notional switch all carry `notional`; a row that somehow doesn't
    # contributes 0, which errs toward taking a trade rather than blocking one
    # — the position-count cap is the hard stop and is never estimated.
    open_notional = sum(float(p.get("notional") or 0) for p in book)

    # Correlation control: positions per sector (existing + taken this run), so
    # the book can't quietly become one macro bet. Unknown sectors are exempt —
    # except crypto, which gets synthetic major/alt buckets via _sector_key.
    max_sector = int(kw.get("max_per_sector", getattr(_cfg, "VIVEK_BOT_MAX_PER_SECTOR", 0)) or 0)
    sector_counts: Counter = Counter()
    for p in book:
        sk = _sector_key(p.get("symbol"), p.get("sector"), market)
        if sk:
            sector_counts[sk] += 1

    # The cap above exempts rows with no sector, so a market whose universe
    # carries no sector data has NO correlation control at all -- it merely
    # looks like it does. NASDAQ is exactly that today (universe._fetch_nasdaq
    # has no sector column to read: 0 of ~1,400 names carry one), and that
    # matters far more since the book became a 30-position ceiling that any
    # single market is allowed to fill on its own. Report it loudly instead of
    # letting it stay invisible. This deliberately does NOT change what gets
    # taken -- that is an owner decision on the risk path, not an autonomous one.
    sector_known = sum(1 for r in rows
                       if _sector_key(r.get("symbol"), r.get("sector"), market))
    sector_cov = round(sector_known / len(rows), 3) if rows else 1.0
    if max_sector and rows and sector_cov < 0.5:
        log.warning("vivek_bot [%s]: the %d-per-sector cap is configured but only "
                    "%d/%d scanned rows carry a sector - the cap cannot bind on "
                    "the rest, so this market has no correlation control",
                    market, max_sector, sector_known, len(rows))

    # Re-entry cooldown: symbols recently stopped out (supplied by the runner
    # from the closed book) are untouchable — no churning the same level.
    cooldown_syms = {str(s).upper() for s in (kw.get("cooldown_syms") or ())}

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
        sector = _sector_key(sym, row.get("sector"), market)
        if sym in open_syms:
            drop(out, "dup_symbol", f"already holding {sym}")
        elif sym in cooldown_syms:
            drop(out, "cooldown", f"{sym} stopped out recently — re-entry cooldown active")
        elif open_count >= max_pos:                     # existing + taken so far
            drop(out, "book_full", f"already at the {max_pos}-position cap for {market}")
        elif elsewhere_unknown:
            drop(out, "global_cap_unknown",
                 "another market's book is unreadable — the global cap cannot "
                 "be evaluated, so no new entries this run")
        elif max_total and open_elsewhere + open_count >= max_total:
            drop(out, "global_cap",
                 f"{open_elsewhere + open_count} open across all markets "
                 f"({open_elsewhere} elsewhere) — global cap {max_total}")
        elif (max_notional_total
              and (notional_elsewhere + open_notional
                   + float(out["plan"].get("notional") or 0)) > max_notional_total):
            drop(out, "notional_cap",
                 f"${notional_elsewhere + open_notional:,.0f} open notional across all "
                 f"markets (${notional_elsewhere:,.0f} elsewhere) + "
                 f"${float(out['plan'].get('notional') or 0):,.0f} for this entry "
                 f"exceeds the ${max_notional_total:,.0f} portfolio ceiling")
        elif direction == "long" and longs >= max_long:
            drop(out, "long_cap", f"long cap {max_long} reached — reserving the ≥{min_shorts}-short slots")
        elif max_sector and sector and sector_counts[sector] >= max_sector:
            drop(out, "sector_cap",
                 f"already {sector_counts[sector]} open in '{sector}' — cap {max_sector}/sector")
        else:
            plans.append(out)
            open_syms.add(sym)
            open_count += 1
            open_notional += float(out["plan"].get("notional") or 0)
            if sector:
                sector_counts[sector] += 1
            if direction == "long":
                longs += 1
            else:
                shorts += 1

    short_bias_met = shorts >= min_shorts
    summary = {
        "market": market, "setups": len(rows), "existing": existing,
        "taken": len(plans), "total_open": open_count,
        # Rows the side caps could not classify (TOP100 #22). 0 on every healthy
        # book; non-zero means `longs + shorts` is short of `total_open` and the
        # long/short reservation is partially blind. Published rather than only
        # logged, because a log line inside a finished Actions run is not
        # somewhere a discrepancy gets noticed.
        "unclassified_direction": len(unclassified),
        # Global-cap context: what the OTHER markets were holding when this ran,
        # and the ceiling they share. max_open_total 0 = the gate is off;
        # open_elsewhere None = a sibling book was unreadable.
        "open_elsewhere": None if elsewhere_unknown else open_elsewhere,
        "max_open_total": max_total,
        # Exposure twin of the two above (2026-07-28). open_notional is the
        # WHOLE-BOOK figure after this run — what was already held here, plus
        # everything taken this run, plus the other markets — so it can be read
        # straight off against the ceiling without re-adding the parts.
        "notional_elsewhere": None if elsewhere_unknown else round(notional_elsewhere, 2),
        "open_notional": (None if elsewhere_unknown
                          else round(notional_elsewhere + open_notional, 2)),
        "max_portfolio_notional": max_notional_total,
        "longs": longs, "shorts": shorts, "min_shorts": min_shorts,
        "short_bias_met": short_bias_met,
        # Fraction of this scan's rows the sector cap could actually see. Below
        # 1.0 the correlation control is partially blind; at 0.0 it is off.
        "sector_coverage": sector_cov, "max_per_sector": max_sector,
        "skipped": len(skipped), "skip_reasons": dict(reasons),
    }
    log.info("VIVEK bot [%s]: +%d new (book %d→%d%s) — %d long / %d short%s · skips: %s",
             market, summary["taken"], existing, summary["total_open"],
             ("" if not max_total else
              f", ?/{max_total} all markets" if elsewhere_unknown else
              f", {open_elsewhere + longs + shorts}/{max_total} all markets"),
             longs, shorts,
             "" if short_bias_met else f"  ⚠ short bias unmet (<{min_shorts})",
             summary["skip_reasons"] or "none")
    return {"plans": plans, "skipped": skipped, "summary": summary}
