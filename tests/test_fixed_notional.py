"""Fixed-notional sizing + the portfolio-notional ceiling (owner, 2026-07-28).

The owner's words: "5k position moving forward on each 30 stocks and a cap of
150k". So every entry now buys a FIXED dollar amount instead of a risk-derived
one, and total open exposure is capped at 30 x $5,000.

The thing these tests exist to hold down is the TRADE-OFF, not just the maths:
under fixed sizing the dollars risked per trade is an OUTPUT (it falls out of
the stop distance), where it used to be the input. A tight stop now risks less
and a wide stop risks more, bounded only by the 1%/25% stop-width rules. That
is the accepted cost of the change and it must not be "fixed" by someone later
re-clamping risk_pct in fixed mode — test_fixed_mode_does_not_clamp_the_derived_
risk_pct pins exactly that.

The old risk-% path is retained intact and reachable (set the config constant to
0, or pass notional_target=0); tests/test_vivek.py covers it in that mode.
"""

import json

import pytest

from scanner import config
from scanner.broker import vivek_bot as vb
from scanner.broker import vivek_run as vr

pytestmark = pytest.mark.risk


def _plan(**kw):
    p = {"armed": True, "entry_trigger": "reclaim",
         "entry": 100.0, "stop": 96.0, "tp1": 106.0, "tp2": 112.0, "tp3": 120.0,
         "rr": 3.0, "scale": [0.25, 0.50, 0.15]}
    p.update(kw)
    return p


SECTORS = ["Banks", "Materials", "Energy", "Utilities", "Real Estate",
           "Retailing", "Insurance", "Transportation", "Media", "Software",
           "Pharmaceuticals"]


def _rows(n, **plan_kw):
    """n distinct A+ long setups, each in its own sector (sector cap not the point)."""
    return [{"symbol": f"S{i:02d}", "name": f"S{i:02d} Ltd", "sector": SECTORS[i % len(SECTORS)],
             "dir": "LONG", "grade": "A+", "entry_types": ["reclaim"],
             "price": 100.0, "plans": {"1W": _plan(**plan_kw)}}
            for i in range(n)]


# ── the owner's numbers, pinned ──────────────────────────────────────────────

def test_the_owner_s_sizing_decision():
    # These two are the owner's, not an implementation detail. Change them only
    # on his say-so, and update this test in the same commit.
    assert config.VIVEK_BOT_POSITION_NOTIONAL == 5_000
    assert config.VIVEK_BOT_MAX_PORTFOLIO_NOTIONAL == 150_000
    # The ceiling is exactly the full book at full size — 30 x $5,000. If these
    # ever disagree, one of the two caps is dead weight and the book can't
    # actually fill.
    assert (config.VIVEK_BOT_MAX_OPEN_TOTAL * config.VIVEK_BOT_POSITION_NOTIONAL
            == config.VIVEK_BOT_MAX_PORTFOLIO_NOTIONAL)


def test_equity_scales_the_loss_guards_not_the_position_size():
    # Equity moved 10k -> 150k WITH the sizing switch, because vivek_guard's
    # limits are equity x pct: at 10k the 3% daily stop would have been $300,
    # less than one ordinary 1R loss under $5,000 positions, and the bot would
    # have sat halted. It no longer influences size at all in fixed mode.
    assert config.VIVEK_BOT_ACCOUNT_EQUITY == 150_000
    a = vb.size_position(150_000, entry=100, stop=96)
    b = vb.size_position(10_000, entry=100, stop=96)
    assert a["notional"] == b["notional"] == pytest.approx(5_000.0)
    assert a["units"] == b["units"]


# ── size_position(): fixed mode ──────────────────────────────────────────────

def test_fixed_mode_buys_the_configured_dollar_amount():
    s = vb.size_position(150_000, entry=100, stop=96)
    assert s["sizing_mode"] == "fixed_notional"
    assert s["notional"] == pytest.approx(5_000.0)
    assert s["units"] == pytest.approx(50.0)          # $5,000 / $100
    assert s["risk_usd"] == pytest.approx(200.0)      # 50 units x $4 stop
    assert not s["leverage_capped"]


def test_dollars_risked_now_varies_with_the_stop_distance():
    """THE trade-off of fixed sizing, stated as a test so it can't be lost.

    Same $5,000 position; a 2% stop risks $100, a 12% stop risks $600. Under
    the old risk-% path both would have risked an identical 0.35% of equity.
    """
    tight = vb.size_position(150_000, entry=100, stop=98)     # 2% stop
    wide = vb.size_position(150_000, entry=100, stop=88)      # 12% stop
    assert tight["notional"] == wide["notional"] == pytest.approx(5_000.0)
    assert tight["risk_usd"] == pytest.approx(100.0)
    assert wide["risk_usd"] == pytest.approx(600.0)
    assert wide["risk_usd"] > tight["risk_usd"] * 5


def test_risk_stays_inside_the_band_the_stop_width_rules_imply():
    # MIN_STOP_PCT / MAX_STOP_PCT bound the stop, so they bound 1R too:
    # $5,000 x 1% = $50 at the tightest, $5,000 x 25% = $1,250 at the widest.
    at_min = vb.size_position(150_000, entry=100,
                              stop=100 * (1 - config.VIVEK_BOT_MIN_STOP_PCT / 100))
    at_max = vb.size_position(150_000, entry=100,
                              stop=100 * (1 - config.VIVEK_BOT_MAX_STOP_PCT / 100))
    assert at_min["risk_usd"] == pytest.approx(50.0)
    assert at_max["risk_usd"] == pytest.approx(1_250.0)


def test_fixed_mode_does_not_clamp_the_derived_risk_pct():
    # risk_pct is REPORTING in fixed mode, not an input. Clamping it to the
    # 0.25-0.5 band would make it a lie about what was actually risked.
    s = vb.size_position(150_000, entry=100, stop=88)         # $600 = 0.4%
    assert s["risk_pct"] == pytest.approx(0.4)
    tiny = vb.size_position(150_000, entry=100, stop=99)      # $50 = 0.0333%
    assert tiny["risk_pct"] == pytest.approx(0.0333, abs=1e-4)
    assert tiny["risk_pct"] < 0.25                            # below the old floor


def test_notional_target_forces_either_mode_regardless_of_config():
    forced_risk = vb.size_position(10_000, 100, 96, risk_pct=0.35, notional_target=0)
    assert forced_risk["sizing_mode"] == "risk_pct"
    assert forced_risk["risk_usd"] == pytest.approx(35.0)
    forced_fixed = vb.size_position(10_000, 100, 96, notional_target=2_000)
    assert forced_fixed["sizing_mode"] == "fixed_notional"
    assert forced_fixed["notional"] == pytest.approx(2_000.0)


def test_zeroing_the_config_constant_restores_the_old_path(monkeypatch):
    # The off-switch has to keep working — it is the revert route if fixed
    # sizing turns out badly, and reverting must not need a code change.
    monkeypatch.setattr(config, "VIVEK_BOT_POSITION_NOTIONAL", 0)
    s = vb.size_position(10_000, entry=100, stop=96, risk_pct=0.35)
    assert s["sizing_mode"] == "risk_pct"
    assert s["risk_usd"] == pytest.approx(35.0)


def test_leverage_cap_still_binds_in_fixed_mode(monkeypatch):
    # A $5,000 position against a $150,000 book can't reach 5x, but the cap must
    # still be live for a small book or a large notional_target.
    s = vb.size_position(500, entry=100, stop=96, max_leverage=5, notional_target=5_000)
    assert s["leverage_capped"]
    assert s["notional"] == pytest.approx(2_500.0)            # 500 x 5
    assert s["risk_usd"] == pytest.approx(100.0)              # 25 units x $4
    assert s["sizing_mode"] == "fixed_notional"


def test_degenerate_inputs_return_a_zero_position_in_fixed_mode():
    for kw in ({"entry": 100, "stop": 100}, {"entry": 0, "stop": 5}):
        s = vb.size_position(150_000, **kw)
        assert s["units"] == 0.0 and s["notional"] == 0.0 and s["risk_usd"] == 0.0
        assert s["sizing_mode"] == "fixed_notional"
        assert s["risk_pct"] == 0.0        # nothing was risked; don't report 0.35


# ── decide(): the portfolio-notional ceiling ─────────────────────────────────

def test_the_notional_ceiling_stops_entries_once_exposure_is_full():
    # $145,000 already open elsewhere leaves room for exactly one $5,000 entry.
    d = vb.decide(_rows(6), equity=150_000, market="asx", open_book=[],
                  max_portfolio_notional=150_000, notional_elsewhere=145_000)
    assert len(d["plans"]) == 1
    assert d["summary"]["skip_reasons"]["notional_cap"] == 5
    assert d["summary"]["open_notional"] == pytest.approx(150_000.0)


def test_positions_already_held_here_consume_the_same_ceiling():
    # The book carries its own notional; it must not be double-counted as
    # "elsewhere" nor ignored.
    held = [{"symbol": "H1", "direction": "long", "sector": "Banks", "notional": 100_000.0}]
    d = vb.decide(_rows(4), equity=150_000, market="asx", open_book=held,
                  max_portfolio_notional=120_000, notional_elsewhere=0)
    assert len(d["plans"]) == 4                       # 100k + 4 x 5k = 120k exactly
    d2 = vb.decide(_rows(5), equity=150_000, market="asx", open_book=held,
                   max_portfolio_notional=120_000, notional_elsewhere=0)
    assert len(d2["plans"]) == 4                      # the 5th would breach
    assert d2["summary"]["skip_reasons"]["notional_cap"] == 1


def test_the_ceiling_is_a_ceiling_not_a_trigger():
    # Landing exactly ON the cap is allowed; only exceeding it is refused.
    d = vb.decide(_rows(2), equity=150_000, market="asx", open_book=[],
                  max_portfolio_notional=10_000, notional_elsewhere=0)
    assert len(d["plans"]) == 2
    assert "notional_cap" not in d["summary"]["skip_reasons"]


def test_an_unreadable_sibling_book_stops_entries_on_the_notional_gate_too():
    # notional_elsewhere=None means the runner could not total the other
    # markets. Failing OPEN would let exposure blow through the ceiling.
    d = vb.decide(_rows(3), equity=150_000, market="asx", open_book=[],
                  max_portfolio_notional=150_000, notional_elsewhere=None)
    assert d["plans"] == []
    assert d["summary"]["skip_reasons"]["global_cap_unknown"] == 3
    assert d["summary"]["notional_elsewhere"] is None
    assert d["summary"]["open_notional"] is None


def test_the_notional_gate_fails_closed_even_with_the_position_cap_off():
    # The hole this pins: `elsewhere_unknown` used to be gated on max_open_total
    # alone, so a config with the POSITION cap off and the NOTIONAL cap on would
    # have failed OPEN on an unreadable sibling — no cap of either kind.
    d = vb.decide(_rows(3), equity=150_000, market="asx", open_book=[],
                  max_open_total=0, notional_elsewhere=None,
                  max_portfolio_notional=150_000)
    assert d["plans"] == []
    assert d["summary"]["skip_reasons"]["global_cap_unknown"] == 3


def test_an_unknown_position_count_still_fails_closed_with_notional_off():
    d = vb.decide(_rows(3), equity=150_000, market="asx", open_book=[],
                  max_open_total=30, open_elsewhere=None,
                  max_portfolio_notional=0)
    assert d["plans"] == []
    assert d["summary"]["skip_reasons"]["global_cap_unknown"] == 3


def test_the_notional_gate_is_off_unless_the_runner_asks_for_it():
    # Back-compat: the backtester and older callers pass no notional kwargs and
    # must keep getting the plain behaviour.
    d = vb.decide(_rows(12), equity=150_000, market="asx", open_book=[])
    assert len(d["plans"]) == 12
    assert "notional_cap" not in d["summary"]["skip_reasons"]
    assert d["summary"]["max_portfolio_notional"] == 0


def test_both_ceilings_bind_together_and_the_tighter_one_wins():
    # 28 open elsewhere (2 slots left) but only $5,000 of notional room (1
    # position). Whichever is tighter must be what stops it.
    d = vb.decide(_rows(6), equity=150_000, market="nasdaq", open_book=[],
                  max_open_total=30, open_elsewhere=28,
                  max_portfolio_notional=150_000, notional_elsewhere=145_000)
    assert len(d["plans"]) == 1
    r = d["summary"]["skip_reasons"]
    assert r.get("notional_cap", 0) + r.get("global_cap", 0) == 5


# ── vivek_run._book_elsewhere(): counts AND exposure in one read ─────────────

def _write_book(tmp_path, market, positions):
    (tmp_path / f"vivek_bot_book.{market}.json").write_text(json.dumps({
        "version": 2, "mode": "paper", "market": market,
        "open": positions, "closed": []}), encoding="utf-8")


def _pos(sym, notional=5_000.0, market=None):
    p = {"symbol": sym, "direction": "long", "notional": notional}
    if market:
        p["market"] = market
    return p


@pytest.fixture
def book_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(vr, "BOOK_DIR", tmp_path)
    monkeypatch.setattr(vr, "UNASSIGNED_FILE", tmp_path / "vivek_bot_book.unassigned.json")
    return tmp_path


def test_book_elsewhere_returns_both_the_count_and_the_notional(book_dir):
    _write_book(book_dir, "asx", [_pos("BHP"), _pos("CBA", 3_000.0)])
    _write_book(book_dir, "nasdaq", [_pos("AAPL"), _pos("MSFT"), _pos("NVDA")])
    seen = vr._book_elsewhere("crypto")
    assert seen == {"count": 5, "notional": pytest.approx(23_000.0)}
    # ...and our own market is excluded from both halves.
    assert vr._book_elsewhere("asx") == {"count": 3, "notional": pytest.approx(15_000.0)}


def test_a_position_with_no_notional_counts_as_a_slot_but_zero_exposure(book_dir):
    # Legacy rows predate the field. They must not vanish from the position
    # count, and must not be guessed at for the exposure figure.
    _write_book(book_dir, "nasdaq", [{"symbol": "OLD", "direction": "long"}, _pos("AAPL")])
    assert vr._book_elsewhere("asx") == {"count": 2, "notional": pytest.approx(5_000.0)}


def test_an_unreadable_sibling_makes_both_halves_unknown(book_dir):
    _write_book(book_dir, "nasdaq", [_pos("AAPL")])
    (book_dir / "vivek_bot_book.crypto.json").write_text("{ truncated", encoding="utf-8")
    assert vr._book_elsewhere("asx") is None
    assert vr._open_elsewhere("asx") is None       # the compat wrapper agrees


def test_the_count_wrapper_still_answers_for_callers_that_only_want_slots(book_dir):
    _write_book(book_dir, "nasdaq", [_pos("AAPL"), _pos("MSFT")])
    assert vr._open_elsewhere("asx") == 2
