"""TOP100 Tier 4c — the backtest's arithmetic, pinned where it used to lie.

Every test here corresponds to a published number that was WRONG in a specific
direction, and each asserts the direction as well as the value. That matters
more than usual in this file: a backtest has no ground truth to check itself
against, so a metric that drifts optimistic is indistinguishable from an edge.
Where a fix could plausibly have been written the other way (and the other way
would have looked fine on the page), the test says why this way.

Covers #59 (liquidity parity), #61 (currency), #68 (bot gates), #69 (risk on a
trailed row), #74 (cost of a forced close).
"""

import json
import math

import numpy as np
import pandas as pd
import pytest

from scanner import config, vivek_backtest as bt
from scanner import scan as scan_mod
from scanner.vivek_journal import _cost_r


# ---------------------------------------------------------------- helpers

def _trade(**kw) -> dict:
    """A minimal CLOSED backtest trade. Overridable field by field."""
    tr = {"symbol": "TEST", "market": "nasdaq", "direction": "long",
          "entry": 100.0, "stop": 90.0, "risk": 10.0,
          "entry_date": "2026-01-05", "exit_date": "2026-02-05",
          "grade": "A+", "entry_type": "reclaim", "timeframe": "1D",
          "realized_r": 1.0, "exits": []}
    tr.update(kw)
    return tr


@pytest.fixture(autouse=True)
def _clear_fx_memo(tmp_path):
    """`fx_rates` memoises per process — reset it around every test.

    Without this the FIRST test to touch a dollar figure would freeze the rate
    for the whole session, and the tests below would pass or fail depending on
    collection order. Pointed at an empty tmp dir by default so the fallback
    path is what an unrelated test gets, never whatever happens to be sitting
    in the developer's `public/data`.
    """
    bt.set_fx_path(tmp_path / "report.json")
    yield
    bt.set_fx_path(bt.OUT_FILE)


# ------------------------------------------------------- #74 forced closes

def test_an_eod_exit_pays_slippage_because_it_is_a_market_fill():
    """A forced end-of-sample close is a market exit and must be priced as one.

    The old test was an allow-list of market reasons — `("stop","time","manual")`
    — and `"eod"` was not in it, so every trade still open when the data ran out
    was charged commission ONLY. That is not a rounding difference on a niche
    path: `_force_close` fires on every open position at the end of the replay.
    """
    slip, comm = 0.0005, 0.0002
    eod = _trade(exits=[{"reason": "eod", "price": 110.0, "pct": 1.0}])
    tp = _trade(exits=[{"reason": "tp1", "price": 110.0, "pct": 1.0}])
    assert _cost_r(eod, slip, comm) > _cost_r(tp, slip, comm)
    # And by exactly one leg of slippage on the exit's booked fraction.
    assert _cost_r(eod, slip, comm) - _cost_r(tp, slip, comm) == pytest.approx(
        1.0 * 110.0 * slip / 10.0)


def test_the_cost_test_is_an_inverted_limit_list_not_a_market_allow_list():
    """An UNKNOWN exit reason must be charged as a market fill.

    This is the whole point of #74 and the reason it was not fixed by appending
    `"eod"` to the old tuple. An allow-list of market fills fails CHEAP: a new
    exit path silently under-charges, which overstates every R, win rate and
    expectancy derived from it, invisibly. The resting-limit set is closed by
    construction (one branch of one function writes tp1/tp2/tp3), so the
    unknown case can safely land on the expensive side, where it shows up as a
    cost that is too high rather than an edge that is not there.
    """
    slip, comm = 0.0005, 0.0002
    novel = _trade(exits=[{"reason": "some_future_exit", "price": 110.0, "pct": 1.0}])
    market = _trade(exits=[{"reason": "stop", "price": 110.0, "pct": 1.0}])
    assert _cost_r(novel, slip, comm) == pytest.approx(_cost_r(market, slip, comm))


def test_every_tp_rung_still_fills_as_a_resting_limit():
    slip, comm = 0.0005, 0.0002
    base = _cost_r(_trade(exits=[]), slip, comm)
    for rung in ("tp1", "tp2", "tp3"):
        tr = _trade(exits=[{"reason": rung, "price": 110.0, "pct": 1.0}])
        assert _cost_r(tr, slip, comm) == pytest.approx(base + 1.0 * 110.0 * comm / 10.0)


def test_a_trailed_stop_close_was_never_the_gap():
    """Guards the claim in `_cost_r`'s docstring, which was wrong on first pass.

    `_mark` writes `{"reason": "stop"}` for EVERY stop hit including a trailed
    one — only the trade-level `exit_reason` becomes `"trail"` — so trailed
    closes always paid slippage. If a later refactor moves that reason string to
    `"trail"`, this fails and the docstring's enumeration gets revisited rather
    than silently becoming fiction.
    """
    slip, comm = 0.0005, 0.0002
    trailed = _trade(exit_reason="trail", exits=[{"reason": "stop", "price": 100.0, "pct": 1.0}])
    assert _cost_r(trailed, slip, comm) > _cost_r(
        _trade(exits=[{"reason": "tp1", "price": 100.0, "pct": 1.0}]), slip, comm)


# ------------------------------------------------------------- #69 sizing

def test_risk_is_sized_off_the_original_stop_not_the_trailed_one():
    """A breakeven-trailed winner must not size to zero dollars.

    `stop` trails: a trade that took TP1 carries a stop AT ENTRY, so
    `size_position(equity, entry, stop)` divides by a zero distance and books
    the trade at $0. Every trade that trailed is a trade that reached TP1 —
    i.e. a WINNER — so the bug deleted the dollar contribution of winners
    specifically, which flatters nothing and understates everything.
    """
    trailed = _trade(entry=100.0, stop=100.0, risk=10.0)   # stop moved to breakeven
    untrailed = _trade(entry=100.0, stop=90.0, risk=10.0)
    assert bt._risk_usd(trailed) > 0
    assert bt._risk_usd(trailed) == pytest.approx(bt._risk_usd(untrailed))
    assert bt._dollars(trailed) == pytest.approx(bt._dollars(untrailed))


def test_a_short_reconstructs_its_original_stop_on_the_correct_side():
    short = _trade(direction="short", entry=100.0, stop=100.0, risk=10.0)
    ref = _trade(direction="short", entry=100.0, stop=110.0, risk=10.0)
    assert bt._risk_usd(short) == pytest.approx(bt._risk_usd(ref))


def test_a_pre_69_record_with_no_risk_key_is_not_repriced():
    """A merged file mixing old and new slim records must not rewrite history."""
    legacy = _trade(entry=100.0, stop=90.0)
    legacy.pop("risk")
    assert bt._risk_usd(legacy) > 0


# ----------------------------------------------------------- #61 currency

def test_an_asx_trade_is_converted_and_a_nasdaq_one_is_not(tmp_path):
    """The two legs of a combined total were being added at face value.

    An ASX position is sized off an A$ entry price, so its "usd" was A$ and the
    sum overstated that leg by 1/rate (~43% at 0.70). R was immune — it divides
    by the position's own risk, so the currency cancels — which is exactly why
    the R figures looked sane while the dollar ones did not.
    """
    (tmp_path / "fx.json").write_text(json.dumps({"audusd": 0.70}), encoding="utf-8")
    bt.set_fx_path(tmp_path / "report.json")
    asx = _trade(market="asx")
    nas = _trade(market="nasdaq")
    assert bt._risk_usd(nas) == pytest.approx(bt._risk_usd(asx) / 0.70)
    assert bt.fx_rates()["source"] == "fx.json"


def test_r_is_unchanged_by_the_conversion():
    """The invariant that makes the fix safe to ship: no R figure moves."""
    trades = [_trade(market="asx", realized_r=1.5), _trade(market="nasdaq", realized_r=-1.0)]
    assert bt._metrics(trades)["total_r"] == pytest.approx(0.5)


def test_the_drawdown_curve_is_converted_too_not_just_the_pnl():
    """`_metrics` multiplies `_risk_usd` by `mae_r` as well as by `realized_r`.

    Converting inside `_dollars` alone would have left the open-drawdown curve
    summing A$ troughs into a US$ equity line — a NEW currency-mixing bug
    introduced by the fix for currency mixing. The conversion therefore lives in
    `_risk_usd`, the single point where a trade's local dollars are produced,
    and this test is what stops it being moved back out.
    """
    asx = [_trade(market="asx", realized_r=-1.0, mae_r=-1.0, exit_date="2026-02-05")]
    nas = [_trade(market="nasdaq", realized_r=-1.0, mae_r=-1.0, exit_date="2026-02-05")]
    a, n = bt._metrics(asx), bt._metrics(nas)
    assert a["max_dd_open_usd"] and n["max_dd_open_usd"]
    assert abs(a["max_dd_open_usd"]) < abs(n["max_dd_open_usd"])


def test_an_unreadable_or_absurd_rate_falls_back_and_says_so(tmp_path):
    """A mis-parsed 6969 would multiply the ASX leg by four thousand.

    That failure is not visibly wrong on a page, so both the unreadable file and
    the out-of-band rate land on the same declared fallback rather than on a
    number the report would present as real.
    """
    bt.set_fx_path(tmp_path / "missing" / "report.json")
    assert bt.fx_rates() == {"audusd": pytest.approx(config.FX_AUDUSD_FALLBACK),
                             "source": "fallback", "currency": config.REPORT_CURRENCY}
    (tmp_path / "fx.json").write_text(json.dumps({"audusd": 6969}), encoding="utf-8")
    bt.set_fx_path(tmp_path / "report.json")
    assert bt.fx_rates()["source"] == "fallback"


def test_the_python_fallback_matches_the_one_the_journal_page_uses():
    """An offline page and an offline report must not disagree about the rate.

    Both claim US$, so two different hard-coded rates would silently produce two
    different US$ totals for the same book. Read out of the shipped JS rather
    than re-typed, so a change there fails here.
    """
    src = (bt.ROOT / "public" / "js" / "journal.js").read_text(encoding="utf-8", errors="ignore")
    import re
    m = re.search(r"FX_AUDUSD\s*=\s*([0-9.]+)", src)
    assert m, "journal.js no longer declares an FX_AUDUSD fallback"
    assert float(m.group(1)) == pytest.approx(config.FX_AUDUSD_FALLBACK)


def test_an_unknown_market_is_not_converted_and_does_not_raise():
    """A merged file can carry a market this build does not know about."""
    assert bt._fx_of("some_new_market") == 1.0


def test_set_fx_path_clears_the_memo(tmp_path):
    """A path set after the first `fx_rates()` call must not be silently ignored."""
    bt.set_fx_path(tmp_path / "report.json")
    assert bt.fx_rates()["source"] == "fallback"
    (tmp_path / "fx.json").write_text(json.dumps({"audusd": 0.71}), encoding="utf-8")
    bt.set_fx_path(tmp_path / "report.json")
    assert bt.fx_rates()["audusd"] == pytest.approx(0.71)


# -------------------------------------------------------------- #68 gates

def test_stop_pct_reads_risk_not_the_trailed_stop():
    """The obvious fallback would have culled winners and improved every metric.

    `abs(entry - stop)` reads 0% on any trade that trailed to breakeven, which
    the `min_stop_pct` gate rejects as `stop_too_tight`. Trailed trades are by
    definition winners, so that version of `_stop_pct` would have deleted
    winners specifically — and the resulting report would have looked BETTER.
    """
    trailed = _trade(entry=100.0, stop=100.0, risk=10.0)
    assert bt._stop_pct(trailed) == pytest.approx(10.0)
    assert bt._bot_gate(trailed) is None


def test_an_unknown_stop_is_not_gated_rather_than_guessed():
    legacy = _trade()
    legacy.pop("risk")
    assert bt._stop_pct(legacy) is None
    assert bt._bot_gate(legacy) is None


def test_the_three_replayed_gates_reject_what_the_live_bot_rejects():
    wide = _trade(entry=100.0, risk=100.0 * (config.VIVEK_BOT_MAX_STOP_PCT + 5) / 100.0)
    tight = _trade(entry=100.0, risk=100.0 * (config.VIVEK_BOT_MIN_STOP_PCT / 2) / 100.0)
    cheap = _trade(market="asx", entry=config.VIVEK_BOT_MIN_PRICE["asx"] / 2, risk=0.005)
    assert bt._bot_gate(wide) == "wide_stop"
    assert bt._bot_gate(tight) == "stop_too_tight"
    assert bt._bot_gate(cheap) == "min_price"


def test_gate_order_mirrors_the_live_bot_so_attribution_matches_the_log():
    """A trade failing two gates must be attributed to the same one live names.

    `evaluate_setup` runs the stop-distance tests and `plan_trade` runs the
    price floor AFTER it, so a cheap micro-cap with a 90% stop is a `wide_stop`
    in the live log and must be one here too.
    """
    both = _trade(market="asx", entry=config.VIVEK_BOT_MIN_PRICE["asx"] / 2,
                  risk=config.VIVEK_BOT_MIN_PRICE["asx"] / 2 * 0.9)
    assert bt._bot_gate(both) == "wide_stop"


def test_gated_trades_shrink_eligible_not_just_the_portfolio():
    """`eligible` means "every signal the bot would have taken", so it shrinks.

    The gates run in the eligibility filter because that is where they run live
    — both reject before a slot is ever considered. A 95%-stop plan was never a
    signal the bot was willing to take, so counting it in the unconstrained
    baseline would overstate what the rules cost.
    """
    good = [_trade(symbol=f"G{i}", entry_date=f"2026-01-{i:02d}", exit_date=f"2026-02-{i:02d}")
            for i in range(1, 4)]
    bad = _trade(symbol="WIDE", entry=100.0, risk=95.0)
    clean = bt.portfolio_sim(good)
    dirty = bt.portfolio_sim(good + [bad])
    assert dirty["eligible"]["n"] == clean["eligible"]["n"]
    assert dirty["gated"] == {"wide_stop": 1}
    assert clean["gated"] == {}


def test_the_report_states_what_it_does_simulate_not_only_what_it_does_not():
    """An incomplete caveat is worse than none — it is read INSTEAD of the code."""
    sim = bt.portfolio_sim([_trade(symbol=f"G{i}", entry_date=f"2026-01-{i:02d}",
                                   exit_date=f"2026-02-{i:02d}") for i in range(1, 4)])
    params = sim["params"]
    assert {"min_price", "max_stop_pct", "min_stop_pct"} <= set(params["simulated_gates"])
    # ...and nothing may be claimed in both lists at once.
    assert not (set(params["simulated_gates"]) & set(params["not_simulated"]))


def test_records_with_no_risk_are_counted_rather_than_hidden():
    """A non-zero count means part of the population is reported on OLD rules."""
    legacy = _trade(symbol="OLD")
    legacy.pop("risk")
    sim = bt.portfolio_sim([legacy, _trade(symbol="NEW", entry_date="2026-01-06",
                                           exit_date="2026-02-06")])
    assert sim["gated_unknown_stop"] == 1


# --------------------------------------------------- #59 liquidity parity

def _liq_frame(vols) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=len(vols), freq="D")
    return pd.DataFrame({"Close": [10.0] * len(vols), "Volume": vols,
                         "Open": [10.0] * len(vols), "High": [10.0] * len(vols),
                         "Low": [10.0] * len(vols)}, index=idx)


def test_turnover_matches_scan_pys_liquidity_bar_for_bar():
    n = config.LIQUIDITY_LOOKBACK * 3
    df = _liq_frame([1000.0 + i for i in range(n)])
    series = bt._turnover_series(df, "nasdaq")
    for j in (config.LIQUIDITY_LOOKBACK, n - 5, n - 1):
        assert series[j] == pytest.approx(scan_mod._liquidity(df.iloc[: j + 1], "nasdaq"))


def test_a_single_missing_bar_does_not_drop_a_name_the_live_scan_keeps():
    """`min_periods=1` is parity, not slack.

    Bare `.mean()` in `_liquidity` skips NaNs and divides by what survived;
    rolling's default `min_periods=window` returns NaN for a window holding ONE
    missing bar, which would turn a name the live scan passes into one the
    backtest silently drops.
    """
    n = config.LIQUIDITY_LOOKBACK * 3
    vols = [1e9] * n
    vols[n - 3] = np.nan
    df = _liq_frame(vols)
    j = n - 1
    assert bt._turnover_series(df, "nasdaq")[j] == pytest.approx(
        scan_mod._liquidity(df.iloc[: j + 1], "nasdaq"))


def test_a_name_with_no_volume_at_all_passes_in_both_files():
    """NaN < liq_min is False in both, so an all-NaN name keeps passing."""
    n = config.LIQUIDITY_LOOKBACK * 3
    df = _liq_frame([np.nan] * n)
    live = scan_mod._liquidity(df, "nasdaq")
    replay = bt._turnover_series(df, "nasdaq")[n - 1]
    assert math.isnan(replay) and (live is None or math.isnan(live))
    liq_min = float(getattr(config.MARKETS["nasdaq"], "liquidity_min", 0) or 0)
    assert not (replay < liq_min)


def test_crypto_volume_is_already_dollars():
    """Yahoo reports crypto Volume in USD, so multiplying by Close double-counts."""
    n = config.LIQUIDITY_LOOKBACK * 3
    df = _liq_frame([1e6] * n)
    assert bt._turnover_series(df, "crypto")[n - 1] == pytest.approx(1e6)
    assert bt._turnover_series(df, "nasdaq")[n - 1] == pytest.approx(1e7)
