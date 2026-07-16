"""Tradeability + risk gates added 2026-07-16: liquidity (ADV floor and
size-vs-ADV), volatility floor (min stop %), re-entry cooldown, crypto
synthetic-sector cap, cross-run sector persistence, weekly loss breaker,
time stop, and the signal-vs-fill slippage metric."""

import datetime as dt

import pytest

from scanner import config
from scanner.broker import vivek_bot as vb
from scanner.broker import vivek_guard, vivek_run

pytestmark = pytest.mark.risk

TODAY = "2026-07-16"


def _plan(**kw):
    p = {"armed": True, "entry_trigger": "reclaim",
         "entry": 100.0, "stop": 96.0, "tp1": 106.0, "tp2": 112.0, "tp3": 120.0,
         "rr": 3.0, "scale": [0.25, 0.50, 0.15]}
    p.update(kw)
    return p


def _row(symbol="XYZ", **kw):
    r = {"symbol": symbol, "name": f"{symbol} Ltd",
         "sector": "Health Care Equipment & Services", "dir": "LONG",
         "grade": "A+", "entry_types": ["reclaim"], "price": 100.0,
         "plans": {"1W": _plan()}}
    r.update(kw)
    return r


# ── volatility floor ──────────────────────────────────────────────────────────

def test_min_stop_pct_skips_pegged_instruments():
    # stop 0.5% from entry — a dead/pegged name (floor is 1%)
    row = _row(plans={"1W": _plan(stop=99.5, tp1=100.6, tp2=101.2, tp3=102.0, rr=2.4)})
    d = vb.evaluate_setup(row)
    assert d["take"] is False and d["code"] == "stop_too_tight"


def test_normal_stop_distance_passes_the_floor():
    d = vb.evaluate_setup(_row())      # stop 4% from entry
    assert d["take"] is True


# ── liquidity gates ───────────────────────────────────────────────────────────

def test_adv_floor_blocks_illiquid_names():
    row = _row(adv_usd=100_000.0)      # < the 250k ASX floor
    out = vb.plan_trade(row, equity=10_000, market="asx")
    assert out["plan"] is None and out["code"] == "illiquid"


def test_size_vs_adv_blocks_oversized_positions():
    # Crypto has no ADV floor, so the %-of-tape cap is the binding gate there:
    # a 1%-stop plan sizes to ~$3.5k notional, >2% of a $100k/day tail alt.
    row = _row(adv_usd=100_000.0,
               plans={"1W": _plan(stop=99.0, tp1=106.0, tp2=112.0, tp3=120.0, rr=6.0)})
    out = vb.plan_trade(row, equity=10_000, market="crypto")
    assert out["plan"] is None and out["code"] == "size_vs_adv"


def test_unknown_adv_is_exempt_fail_open():
    out = vb.plan_trade(_row(), equity=10_000, market="asx")
    assert out["plan"] is not None


def test_deep_liquidity_passes_both_gates():
    row = _row(adv_usd=50_000_000.0)
    out = vb.plan_trade(row, equity=10_000, market="asx")
    assert out["plan"] is not None
    assert out["plan"]["sector"]        # sector persisted on the ticket


# ── re-entry cooldown ─────────────────────────────────────────────────────────

def test_decide_skips_symbols_on_cooldown():
    d = vb.decide([_row("ABC")], 10_000, market="asx", cooldown_syms={"ABC"})
    assert not d["plans"]
    assert d["summary"]["skip_reasons"].get("cooldown") == 1


def test_cooldown_symbols_from_recent_stop_outs_only():
    book = {"closed": [
        {"symbol": "ABC", "market": "asx", "exit_reason": "stop", "exit_date": "2026-07-14"},
        {"symbol": "OLD", "market": "asx", "exit_reason": "stop", "exit_date": "2026-06-01"},
        {"symbol": "TGT", "market": "asx", "exit_reason": "target", "exit_date": "2026-07-15"},
        {"symbol": "NAS", "market": "nasdaq", "exit_reason": "stop", "exit_date": "2026-07-15"},
    ]}
    assert vivek_run._cooldown_symbols(book, "asx", TODAY) == {"ABC"}


# ── crypto synthetic sectors ──────────────────────────────────────────────────

def test_crypto_alts_share_one_synthetic_sector():
    assert vb._sector_key("BTC", "", "crypto") == "crypto-major"
    assert vb._sector_key("SOL", "", "crypto") == "crypto-alt"
    assert vb._sector_key("XYZ", "", "asx") == ""          # stocks stay exempt when unknown

    open_book = [{"symbol": s, "direction": "long", "sector": ""}
                 for s in ("SOL", "AVAX", "LINK")]
    d = vb.decide([_row("DOGE", sector="")], 10_000, market="crypto",
                  open_book=open_book)
    assert not d["plans"]
    assert d["summary"]["skip_reasons"].get("sector_cap") == 1


def test_crypto_major_not_blocked_by_alt_cap():
    open_book = [{"symbol": s, "direction": "long", "sector": ""}
                 for s in ("SOL", "AVAX", "LINK")]
    d = vb.decide([_row("BTC", sector="")], 10_000, market="crypto",
                  open_book=open_book)
    assert len(d["plans"]) == 1


# ── weekly circuit breaker ────────────────────────────────────────────────────

def _closed(r, day, risk=35.0):
    return {"market": "asx", "exit_date": day, "realized_r": r, "risk_usd": risk}


def test_weekly_breaker_trips_on_trailing_losses():
    # 5 losing days, each ~-3.5R*35 = -$122/day → -$612 over the week (>6% of 10k)
    book = {"closed": [_closed(-3.5, f"2026-07-{d:02d}") for d in range(11, 16)],
            "open": []}
    g = vivek_guard.check(book, "asx", TODAY, 10_000, lambda s: None)
    assert g["breached"] and g["breach_kind"] == "weekly"


def test_daily_guard_still_reports_daily_kind():
    book = {"closed": [_closed(-9.0, TODAY)], "open": []}   # -$315 today > 3% of 10k
    g = vivek_guard.check(book, "asx", TODAY, 10_000, lambda s: None)
    assert g["breached"] and g["breach_kind"] == "daily"


def test_quiet_week_no_breach():
    book = {"closed": [_closed(1.0, "2026-07-14")], "open": []}
    g = vivek_guard.check(book, "asx", TODAY, 10_000, lambda s: None)
    assert not g["breached"] and g["breach_kind"] is None


# ── time stop ─────────────────────────────────────────────────────────────────

def _open_pos(entry_date, tp1_hit=False):
    return {"symbol": "XYZ", "market": "asx", "direction": "long", "status": "open",
            "entry": 100.0, "stop": 96.0, "risk": 4.0,
            "tp1": 106.0, "tp2": 112.0, "tp3": 120.0, "scale": [0.25, 0.5, 0.15],
            "tp1_hit": tp1_hit, "tp2_hit": False, "tp3_hit": False,
            "booked_pct": 0.0, "realized_r": 0.0, "gross_r": 0.0, "cost_r": 0.0,
            "exits": [], "entry_date": entry_date,
            "mae": 100.0, "mfe": 100.0, "mae_r": 0.0, "mfe_r": 0.0}


def test_time_stop_closes_stalled_position_with_honest_r():
    pos = _open_pos("2026-06-01")               # 45 days ago, never hit TP1
    vivek_run._close_time_stop(pos, 101.0, TODAY, None)
    assert pos["status"] == "closed" and pos["exit_reason"] == "time"
    assert pos["exit_price"] == 101.0
    assert pos["realized_r"] == pytest.approx(0.25)     # (101-100)/4
    assert pos["hold_days"] == 45
    assert pos["exits"][-1]["reason"] == "time" and pos["exits"][-1]["pct"] == 1.0


def test_held_days_helper():
    assert vivek_run._held_days(_open_pos("2026-07-01"), TODAY) == 15
    assert vivek_run._held_days({"entry_date": "garbage"}, TODAY) is None


# ── signal-vs-fill metric ─────────────────────────────────────────────────────

def test_fill_slippage_recorded_on_new_positions():
    out = vb.plan_trade(_row(), equity=10_000, market="asx")
    pos = vivek_run._ticket_to_position(out, 100.8, "asx", TODAY)
    assert pos is not None
    assert pos["signal_entry"] == 100.0
    assert pos["fill_slip_bps"] == pytest.approx(80.0)   # paid up 0.8% on a long
    assert pos["sector"]                                  # sector persisted on the book


def test_config_constants_exist():
    assert config.VIVEK_BOT_MIN_STOP_PCT > 0
    assert config.VIVEK_BOT_MIN_ADV["asx"] > 0
    assert config.VIVEK_BOT_MAX_NOTIONAL_PCT_ADV > 0
    assert config.VIVEK_BOT_MAX_HOLD_DAYS > 0
    assert config.VIVEK_BOT_REENTRY_COOLDOWN_DAYS > 0
    assert config.VIVEK_BOT_MAX_WEEKLY_LOSS_PCT > 0
    assert config.VIVEK_BOT_EARNINGS_BUFFER_DAYS > 0
