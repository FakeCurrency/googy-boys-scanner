"""TURTLE lens (scanner/turtle.py + turtle_run.py), added 2026-08-21.

This lens states a 40-year-old published rule set exactly, so the tests are
about FIDELITY rather than about taste: every number here is hand-computed
from the Original Turtle Trading Rules, and the two rules the popular short
version drops (the System 1 filter and the 55-day failsafe) get their own
named pins so a later reader cannot simplify them away without going red.

The fixtures use a deliberate construction: a bar whose high is mid+1, low
mid-1 and close mid has True Range EXACTLY 2 as long as consecutive mids move
by at most 1 -- max(H-L, |H-PDC|, |L-PDC|) = max(2, |d+1|, |d-1|) = 2 for
|d| <= 1. So N is exactly 2.0 everywhere in these frames and every stop,
add level and R below is arithmetic a reader can check by hand.
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
import pandas as pd
import pytest

from scanner import config, turtle, turtle_run

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _never_write_the_real_journal(tmp_path, monkeypatch):
    """scan_market advances the FORWARD BOOK, which writes journal/ and
    public/data/. Without this the integration tests below -- which feed it
    synthetic frames called FIRE, HELD, NEAR and SHRT -- write a real paper
    book full of invented positions, and `git add -A` ships it.

    That is not hypothetical: it happened on 2026-08-21 and a book holding a
    fixture symbol reached main before being removed. Fabricated rows in an
    artefact that is supposed to BE the honest record is the worst possible
    failure for this feature, so the isolation is autouse and repo-wide rather
    than remembered per test.
    """
    from scanner import turtle_book
    monkeypatch.setattr(turtle_book, "BOOK_DIR", str(tmp_path / "journal"))
    monkeypatch.setattr(turtle_book, "ROOT", str(tmp_path))
    (tmp_path / "public" / "data").mkdir(parents=True, exist_ok=True)
    yield


def test_no_test_run_may_leave_a_paper_book_behind():
    """The guard for the guard: after any test run the real book must contain
    only symbols a real scan could have produced. Fixture names are banned."""
    real = ROOT / "journal"
    for f in list(real.glob("turtle_book*.json")) + \
            [ROOT / "public" / "data" / "turtle_book.json"]:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        for fixture in ('"FIRE"', '"HELD"', '"NEAR"', '"SHRT"', '"NOTRIG"',
                        '"NULLS"', '"AAA"', '"BBB"', '"T0"', '"S0"'):
            assert fixture not in text, \
                f"{f.name} contains the fixture symbol {fixture} - a test wrote it"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def band(mids, opens=None) -> pd.DataFrame:
    """A frame whose True Range is exactly 2 on every bar (see module docstring).

    `opens` defaults to the mid, so an entry that fills at max(level, open)
    fills at the level rather than at a gap -- gap behaviour is tested
    separately and on purpose.
    """
    mids = np.asarray(mids, dtype="float64")
    ops = mids if opens is None else np.asarray(opens, dtype="float64")
    return pd.DataFrame(
        {"Open": ops, "High": mids + 1.0, "Low": mids - 1.0, "Close": mids,
         "Volume": np.full(len(mids), 5e7)},
        index=pd.bdate_range("2015-01-01", periods=len(mids)),
    )


def ramp(start, end, hold=0):
    """Mids stepping by at most 1 from start to end, then held."""
    step = 1 if end >= start else -1
    out = list(range(int(start), int(end) + step, step))
    return out + [end] * hold


FLAT = [100.0] * 260


# ---------------------------------------------------------------------------
# N
# ---------------------------------------------------------------------------

def test_n_is_the_rules_recurrence_not_a_simple_mean():
    """N = (19 * PDN + TR) / 20 over max(H-L, H-PDC, PDC-L).

    Driven against a frame with VARYING true range, because on the constant-TR
    fixtures every smoothing scheme agrees and the test would be vacuous.
    """
    rs = np.random.RandomState(7)
    mids = 100 + np.cumsum(rs.normal(0, 1.5, 400))
    widths = 1.0 + rs.rand(400) * 3.0
    df = pd.DataFrame(
        {"Open": mids, "High": mids + widths, "Low": mids - widths, "Close": mids,
         "Volume": np.full(400, 1e7)},
        index=pd.bdate_range("2015-01-01", periods=400))
    got = turtle.compute_n(df)

    high, low, close = df["High"], df["Low"], df["Close"]
    pdc = close.shift(1)
    tr = pd.concat([high - low, (high - pdc).abs(), (low - pdc).abs()], axis=1).max(axis=1)
    # the literal recurrence, seeded the way pandas seeds it
    want = [float(tr.iloc[0])]
    for t in tr.iloc[1:]:
        want.append((19.0 * want[-1] + float(t)) / 20.0)
    assert np.allclose(got.to_numpy(), np.array(want), rtol=0, atol=1e-9)


def test_a_simple_20_day_mean_would_be_a_different_number():
    """Guards the choice above: if someone swaps atr() for a rolling mean the
    test suite must not stay green just because both are 'a 20-day ATR'."""
    rs = np.random.RandomState(3)
    mids = 100 + np.cumsum(rs.normal(0, 2.0, 400))
    w = 1.0 + rs.rand(400) * 4.0
    df = pd.DataFrame({"Open": mids, "High": mids + w, "Low": mids - w, "Close": mids,
                       "Volume": np.full(400, 1e7)},
                      index=pd.bdate_range("2015-01-01", periods=400))
    wilder = float(turtle.compute_n(df).iloc[-1])
    pdc = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pdc).abs(),
                    (df["Low"] - pdc).abs()], axis=1).max(axis=1)
    simple = float(tr.rolling(20).mean().iloc[-1])
    assert abs(wilder - simple) > 1e-6, "the two smoothings must be distinguishable"


def test_the_fixture_really_does_have_n_exactly_two():
    df = band(FLAT + ramp(100, 110) + [110.0] * 30)
    assert float(turtle.compute_n(df).iloc[-1]) == pytest.approx(2.0, abs=1e-12)


# ---------------------------------------------------------------------------
# channels: the look-ahead that would make every number here a lie
# ---------------------------------------------------------------------------

def test_entry_channels_exclude_the_signal_bar():
    df = band(FLAT + ramp(100, 130))
    ch = turtle.channels(df)
    i = len(df) - 1
    assert float(ch["s1_hi"].iloc[i]) == pytest.approx(
        float(df["High"].iloc[i - config.TURTLE_S1_ENTRY:i].max()))
    assert float(ch["s2_hi"].iloc[i]) == pytest.approx(
        float(df["High"].iloc[i - config.TURTLE_S2_ENTRY:i].max()))
    assert float(ch["s1_hi"].iloc[i]) < float(df["High"].iloc[i]), \
        "a channel that contains its own bar can never be broken by it"


def test_a_flat_band_never_breaks_out_because_the_test_is_strictly_greater():
    """The high EQUALS the channel on every bar of a flat band. Turning `>`
    into `>=` here would fire a breakout every single day in a dead range."""
    rep = turtle.replay(band([100.0] * 300))
    assert rep["trades"] == []
    assert rep["state"] == "flat"


# ---------------------------------------------------------------------------
# sizing
# ---------------------------------------------------------------------------

def test_unit_size_is_one_percent_over_n():
    # $5,000 account, N = 2.50 -> risk $50 -> 20 shares, and 20 shares moving
    # 2N ($5) is exactly the $100 a full 2N stop-out costs at one unit.
    assert turtle.unit_size(5000.0, 2.50) == pytest.approx(20.0)
    assert turtle.unit_size(5000.0, 2.50) * 2 * 2.50 == pytest.approx(100.0)


def test_unit_size_refuses_an_unpriceable_n_instead_of_exploding():
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        assert turtle.unit_size(5000.0, bad) == 0.0


def test_the_drawdown_rule_compounds():
    # 20% down = two 10% steps = 0.8 * 0.8, NOT 1 - 2*0.2.
    assert turtle.drawdown_equity(8000.0, 10000.0) == pytest.approx(8000.0 * 0.64)
    assert turtle.drawdown_equity(8000.0, 10000.0) != pytest.approx(8000.0 * 0.60)
    # at a new peak it is a no-op, and a fractional step does not round up
    assert turtle.drawdown_equity(10000.0, 10000.0) == 10000.0
    assert turtle.drawdown_equity(9500.0, 10000.0) == pytest.approx(9500.0)


def test_a_full_four_unit_position_risks_five_percent_not_eight():
    """The number the 1/2 N stop-raise exists to produce, computed end to end.

    Entries sit at 0, +1/2N, +1N, +3/2N above the breakout; the single shared
    stop lands 2N under the last of them, i.e. 1/2N BELOW the breakout. The
    four units lose 1/2N + 1N + 3/2N + 2N = 5N = 5% of the account, against
    8N = 8% if each unit kept the stop it was issued.

    Worth a named test because the arithmetic is easy to get wrong in either
    direction -- 2% (forgetting the units are stacked) and 4% (dropping a
    unit) are both plausible-looking wrong answers.
    """
    equity, n = 100_000.0, 2.0
    lad = turtle.pyramid_ladder(100.0, n, "long")
    shares = turtle.unit_size(equity, n)
    shared_stop = lad[-1]["stop"]
    risked = sum(shares * (u["price"] - shared_stop) for u in lad)
    assert risked == pytest.approx(0.05 * equity)
    unstepped = sum(shares * (u["price"] - u["stop"]) for u in lad)
    assert unstepped == pytest.approx(0.08 * equity)


def test_one_unit_moving_one_N_is_exactly_one_percent_of_the_account():
    """The link that lets every other Turtle number be read in equity terms."""
    for equity in (5_000.0, 137_500.0):
        for n in (0.37, 2.0, 88.125):
            assert turtle.unit_size(equity, n) * n == pytest.approx(0.01 * equity)


def test_the_pyramid_ladder_walks_the_stop_up_under_every_earlier_unit():
    lad = turtle.pyramid_ladder(100.0, 2.0, "long")
    assert [u["price"] for u in lad] == [100.0, 101.0, 102.0, 103.0]
    assert [u["stop"] for u in lad] == [96.0, 97.0, 98.0, 99.0]
    assert lad[0]["add_at"] is None and lad[3]["add_at"] == 103.0
    short = turtle.pyramid_ladder(100.0, 2.0, "short")
    assert [u["price"] for u in short] == [100.0, 99.0, 98.0, 97.0]
    assert [u["stop"] for u in short] == [104.0, 103.0, 102.0, 101.0]


# ---------------------------------------------------------------------------
# THE SYSTEM 1 FILTER — the rule the short version drops
# ---------------------------------------------------------------------------

def test_a_breakout_that_never_moved_2N_against_is_a_WINNER_even_at_a_loss():
    """The counterintuitive pin, and it is the rule as written.

    'A breakout is a LOSING breakout if the price moved 2N against the
    position before a profitable 10-day exit.' So a trade that drifts out at
    the 10-day channel a little below entry never moved 2N against, counts as
    a winner, and BLOCKS the next System 1 entry. Do not 'fix' this to mean
    'exited below entry' -- that is a different system.
    """
    sh = turtle._Shadow()
    # enter long: high 102 clears a 20-day high of 101, N = 2 -> stop 97
    sh.step(o=101.0, h=102.0, l=100.0, n_prev=2.0, s1_hi=101.0, s1_lo=90.0,
            x1_lo=99.0, x1_hi=999.0)
    assert sh.active and sh.entry == 101.0 and sh.stop == pytest.approx(97.0)
    # leave via the 10-day channel at 99 -- a $2 LOSS that never touched 97
    sh.step(o=100.0, h=100.5, l=98.5, n_prev=2.0, s1_hi=101.0, s1_lo=90.0,
            x1_lo=99.0, x1_hi=999.0)
    assert sh.active is False
    assert sh.last_was_winner is True, "no 2N adverse move == winner, by the rule"


def test_a_breakout_stopped_at_2N_is_a_LOSER_and_reopens_system_one():
    sh = turtle._Shadow()
    sh.step(o=101.0, h=102.0, l=100.0, n_prev=2.0, s1_hi=101.0, s1_lo=90.0,
            x1_lo=95.0, x1_hi=999.0)
    assert sh.stop == pytest.approx(97.0)
    sh.step(o=100.0, h=100.0, l=96.0, n_prev=2.0, s1_hi=101.0, s1_lo=90.0,
            x1_lo=95.0, x1_hi=999.0)
    assert sh.last_was_winner is False


def test_the_shadow_watches_both_directions_EVEN_IN_A_LONG_ONLY_RUN():
    """'the last breakout in that particular market, regardless of whether it
    was actually taken' -- so a DOWNSIDE breakout is still the last breakout
    even for a book that only ever goes long.

    Until 2026-08-21 the shadow took an allow_shorts flag and skipped short
    breakouts when it was False, which quietly gave a long-only run a
    DIFFERENT filter chain than the rules describe. The flag is gone: the
    shadow is a property of the market, not of what you happen to trade.
    """
    sh = turtle._Shadow()
    sh.step(o=99.0, h=100.0, l=98.0, n_prev=2.0, s1_hi=110.0, s1_lo=99.0,
            x1_lo=0.0, x1_hi=999.0)
    assert sh.active and sh.dir == -1
    import inspect
    assert "allow_shorts" not in inspect.signature(turtle._Shadow.step).parameters, \
        "the filter chain must not depend on which side you trade"


def test_a_winning_prior_breakout_BLOCKS_the_next_system_one_entry():
    """End to end on a constructed frame, not on the shadow in isolation.

    Bars 220-227 ramp up to mid 104 and back: that prints a 20-day breakout
    which leaves at the 10-day channel without ever moving 2N against, i.e. a
    winner. The later 20-day breakout at bar ~251 must therefore be skipped.
    """
    mids = ([100.0] * 260 + ramp(101, 104) + ramp(103, 100)
            + [100.0] * 23 + ramp(101, 103) + [103.0] * 5)
    rep = turtle.replay(band(mids), allow_shorts=False)
    assert rep["s1_filter_known"] is True
    assert rep["s1_blocked"] is True, "the prior 20-day breakout was a filter-winner"
    # BOTH the closed trades AND the open position. Until 2026-08-21 this
    # asserted over rep["trades"] only, so deleting the filter from the S1
    # branch left the illicit entry sitting in rep["position"] and the test
    # green -- the single most important rule in the system, guarded by
    # nothing but a regex over source text.
    entered = [t["system"] for t in rep["trades"]]
    if rep["position"]:
        entered.append(rep["position"]["system"])
    assert entered, "the fixture must actually produce an entry to be meaningful"
    assert 1 not in entered, \
        "no System 1 entry may be taken while the filter blocks -- closed OR open"


def test_the_55_day_FAILSAFE_takes_the_trade_system_one_was_not_allowed_to():
    """The other dropped rule. Same blocked filter state as above, but the
    move continues past the 55-day level -- System 2 must pick it up."""
    mids = ([100.0] * 260 + ramp(101, 104) + ramp(103, 100)
            + [100.0] * 23 + ramp(101, 120) + [120.0] * 5)
    rep = turtle.replay(band(mids), allow_shorts=False)
    assert rep["s1_blocked"] is True
    entered = [t["system"] for t in rep["trades"]] + (
        [rep["position"]["system"]] if rep["position"] else [])
    assert 2 in entered, "a blocked System 1 must still be rescued at 55 days"


def test_system_two_is_never_filtered():
    """System 2 has no equivalent of the System 1 filter, and the failsafe
    depends on that. Pinned structurally: the System 1 entry branch must
    consult the filter and the System 2 branch must not."""
    import re
    src = (ROOT / "scanner" / "turtle.py").read_text(encoding="utf-8")
    entry = src[src.index("side = sysno = None"):src.index("if side is None")]
    # Branches, not physical lines: a wrapped condition puts the channel and
    # the filter on different lines and a line-wise test reads that as absent.
    flat = " ".join(entry.split())
    branches = [b for b in re.split(r"\belif\b|\bif\b", flat) if b.strip()]
    s1 = [b for b in branches if "s1_hi[i]" in b or "s1_lo[i]" in b]
    s2 = [b for b in branches if "s2_hi[i]" in b or "s2_lo[i]" in b]
    assert len(s1) == 2 and len(s2) == 2, "one long and one short branch each"
    assert all("last_was_winner" in b for b in s1), "System 1 must consult the filter"
    assert not any("last_was_winner" in b for b in s2), \
        "filtering System 2 would destroy the failsafe"
    # and the ordering that MAKES it a failsafe: System 2 is tested first
    assert flat.index("s2_hi[i]") < flat.index("s1_hi[i]")


# ---------------------------------------------------------------------------
# entries, adds, exits
# ---------------------------------------------------------------------------

def test_a_position_is_entered_at_the_level_and_stopped_2N_below_it():
    mids = [100.0] * 260 + ramp(101, 103) + [103.0] * 3
    rep = turtle.replay(band(mids), allow_shorts=False)
    pos = rep["position"]
    assert pos is not None and pos["side"] == "long"
    # 20-day high is 101 and N is 2 -> fill 101, first stop 97
    assert pos["entry"] == pytest.approx(101.0)
    assert pos["n"] == pytest.approx(2.0)


def test_units_are_added_every_half_N_and_the_whole_position_moves_its_stop():
    """N = 2 so a half-N step is 1.00. Entry 101 -> adds at 102, 103, 104;
    after the fourth unit the single shared stop is 104 - 2N = 100, which is
    ABOVE where the first unit's stop started (97)."""
    mids = [100.0] * 260 + ramp(101, 112) + [112.0] * 3
    rep = turtle.replay(band(mids), allow_shorts=False)
    pos = rep["position"]
    assert pos is not None
    assert pos["units"] == config.TURTLE_MAX_UNITS == 4
    assert pos["entry"] == pytest.approx(101.0)
    assert pos["avg"] == pytest.approx((101.0 + 102.0 + 103.0 + 104.0) / 4)
    assert pos["stop"] == pytest.approx(100.0)
    assert pos["next_add"] is None, "the fourth unit is the last one"


def test_the_pyramid_spaces_off_the_ENTRY_N_not_todays_N():
    """The rules fix N at entry and use it for the whole position -- the add
    spacing, the stop distance and the size all come from one number. Re-reading
    N each bar would move the rungs under a live position.

    Found by mutation, twice over. Every other fixture here holds N at exactly
    2.0, so entry-N and current-N are identical and the mutation was invisible;
    and a first attempt at this test asserted on `next_add`, which is computed
    in the OUTPUT block from pos["n"] and so is not touched by a mutation to the
    add loop. It has to assert on a REALIZED fill.

    The frame: 260 flat bars set N to exactly 2.0, a narrow breakout bar enters
    one unit at 101 without adding, fifteen quiet bars decay N to about 1.38,
    then one wider bar reaches up past the add level. The add must fill at
    101 + 1/2 x 2.0 = 102.00 (entry-N) and NOT at 101 + 1/2 x 1.38 = 101.69.
    """
    mids = [100.0] * 260 + [101.0] + [101.0] * 15 + [101.2]
    hws = [1.0] * 260 + [0.6] + [0.4] * 15 + [1.0]
    m, hw = np.asarray(mids), np.asarray(hws)
    df = pd.DataFrame(
        {"Open": m, "High": m + hw, "Low": m - hw, "Close": m,
         "Volume": np.full(len(m), 5e7)},
        index=pd.bdate_range("2015-01-01", periods=len(m)))

    rep = turtle.replay(df, allow_shorts=False)
    pos = rep["position"]
    assert pos is not None and pos["units"] == 2
    assert pos["n"] == pytest.approx(2.0), "N is frozen at the entry bar"
    assert rep["n"] < 1.5, "and today's N really has drifted away from it"

    entry = pos["entry"]
    step = config.TURTLE_PYRAMID_STEP_N
    assert entry == pytest.approx(101.0)
    # the realized second fill, recovered from the average
    second = 2 * pos["avg"] - entry
    assert second == pytest.approx(entry + step * pos["n"]), \
        "the rung is half of the ENTRY N above the first fill"
    assert second != pytest.approx(entry + step * rep["n"]), \
        "today's N would have put the rung somewhere else"
    # and the shared stop hangs off that same fill
    assert pos["stop"] == pytest.approx(second - config.TURTLE_STOP_N * pos["n"])


def test_the_unit_ceiling_actually_binds():
    mids = [100.0] * 260 + ramp(101, 200)
    rep = turtle.replay(band(mids), allow_shorts=False)
    assert rep["position"]["units"] == config.TURTLE_MAX_UNITS


def test_the_entering_system_owns_the_exit():
    """A System 2 position uses the 20-day exit. If it borrowed System 1's
    10-day exit it would leave every trend a fortnight early -- which is the
    behaviour the popular indicator explicitly codes around."""
    mids = [100.0] * 260 + ramp(101, 160) + [160.0] * 3
    rep = turtle.replay(band(mids), allow_shorts=False)
    assert rep["position"]["system"] == 2
    assert rep["position"]["exit_channel"] == config.TURTLE_S2_EXIT == 20


def test_an_exit_beats_an_add_inside_the_same_bar():
    """Stated in the docstring and pinned here: a daily bar cannot say which
    came first, so the conservative reading is booked. The pin is that the
    exit branch runs before the add loop in the source."""
    src = (ROOT / "scanner" / "turtle.py").read_text(encoding="utf-8")
    exit_at = src.index("# ---- exits first")
    add_at = src.index("# ---- adds ---")
    assert exit_at < add_at


def test_the_REPLAY_also_forbids_a_same_bar_re_entry():
    """Replay and forward book must agree, so the book's rule is not a
    behaviour the backtest lacks.

    Here one bar stops the position out AND prints far through the 20-day
    high. The replay moves to the next bar after an exit, so a refill on the
    same bar is structurally impossible -- but it is pinned rather than left
    to the shape of a loop, because rearranging that loop is exactly how it
    would quietly become possible.
    """
    rows = _BASE + [
        (101.0, 102.0, 100.5, 101.5, 5e7),      # enter at 101
        (101.0, 140.0, 95.0, 96.0, 5e7),        # stops out, and breaks out again
        (96.0, 97.0, 95.0, 96.0, 5e7),
    ]
    rep = turtle.replay(_bars(rows), allow_shorts=False)
    assert len(rep["trades"]) == 1 and rep["trades"][0]["reason"] == turtle.STOP
    assert rep["state"] == "flat", \
        "the bar that stopped it out must not also refill it"


def test_a_gap_through_the_stop_books_the_gap_not_the_stop():
    """Entry 101, N 2, stop 97. The frame then opens at 90 -- an honest replay
    fills at 90, a dishonest one fills at 97 and flatters every result."""
    mids = [100.0] * 260 + [101.0, 102.0] + [90.0] + [90.0] * 5
    opens = list(mids)
    opens[222] = 90.0
    rep = turtle.replay(band(mids, opens), allow_shorts=False)
    stops = [t for t in rep["trades"] if t["reason"] == turtle.STOP]
    assert stops, "the gap must stop the position out"
    assert stops[0]["exit"] == pytest.approx(90.0)
    assert stops[0]["r"] < -1.0, "a gapped stop costs MORE than 1R, and says so"


def test_a_gap_above_the_trigger_fills_at_the_open_not_at_the_trigger():
    mids = [100.0] * 260 + [130.0] + [130.0] * 5
    opens = list(mids)
    rep = turtle.replay(band(mids, opens), allow_shorts=False)
    assert rep["position"] is not None
    assert rep["position"]["entry"] == pytest.approx(130.0), \
        "you cannot buy a gap at yesterday's channel"


def _bars(rows):
    o, h, l, c, v = zip(*rows)
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v},
                        index=pd.bdate_range("2015-01-01", periods=len(rows)))


# 260 bars of a 99-101 band: N is exactly 2.0 and both entry channels sit at 101.
_BASE = [(100.0, 101.0, 99.0, 100.0, 5e7)] * 260


def test_the_ENTRY_BAR_checks_its_own_stop():
    """Until 2026-08-21 it did not, and the loss was simply invisible.

    A bar that breaks out at 101 (stop 97) and then trades to 95 booked NO
    trade at all -- the position was opened and the replay moved on, so the
    record never saw it. Every such bar flattered the result.

    A daily bar cannot say whether the low came before or after the breakout
    tick. Booking the stop is the conservative reading, and the DIRECTION of
    the error is the point: it can only ever make the record worse.
    """
    rep = turtle.replay(_bars(_BASE + [(101.0, 102.0, 95.0, 96.0, 5e7)]
                              + [(96.0, 97.0, 95.0, 96.0, 5e7)] * 3),
                        allow_shorts=False)
    stops = [t for t in rep["trades"] if t["reason"] == turtle.STOP]
    assert len(stops) == 1, "the entry bar's own stop must be booked"
    assert stops[0]["entry_date"] == stops[0]["exit_date"], "opened and closed same bar"
    assert stops[0]["r"] < 0


def test_an_ADD_RAISES_the_stop_and_the_same_bar_is_re_tested_against_it():
    """The companion hole: an add walks the stop up under the whole position,
    and the bar that did the adding was never re-checked against the stop it
    had just created.

    Here the fourth unit fills at 104, which moves the shared stop to 100, and
    that same bar's low is 99.5 -- half a point through it. Before the fix the
    replay recorded nothing at all for that bar.
    """
    rows = _BASE + [
        (101.0, 102.0, 100.5, 101.5, 5e7),   # enter 101, add 102 -> stop 98
        (102.0, 103.0, 101.5, 102.5, 5e7),   # add 103 -> stop 99
        (103.0, 104.0, 99.5, 100.0, 5e7),    # add 104 -> stop 100, low 99.5 breaks it
        (100.0, 101.0, 99.5, 100.0, 5e7),
    ]
    rep = turtle.replay(_bars(rows), allow_shorts=False)
    stops = [t for t in rep["trades"] if t["reason"] == turtle.STOP]
    assert len(stops) == 1, "the raised stop must be tested on its own bar"
    assert stops[0]["units"] == config.TURTLE_MAX_UNITS
    assert stops[0]["exit"] == pytest.approx(100.0), "filled at the raised stop"
    assert stops[0]["gross_r"] == pytest.approx(-2.5)


def test_both_intrabar_checks_only_ever_ADD_losses_never_remove_them():
    """The safety property that makes these two fixes shippable without
    re-litigating every published number: they can only book a trade the old
    code missed, never delete or improve one it recorded."""
    rows = _BASE + [(101.0, 102.0, 95.0, 96.0, 5e7)] + [(96.0, 97.0, 95.0, 96.0, 5e7)] * 3
    rep = turtle.replay(_bars(rows), allow_shorts=False)
    assert all(t["gross_r"] <= 0 for t in rep["trades"] if t["reason"] == turtle.STOP)


# ---------------------------------------------------------------------------
# costs, and the numbers that stop a fat tail reading as an edge
# ---------------------------------------------------------------------------

def test_every_trade_is_charged_a_round_trip_cost_and_shows_the_gross():
    rows = _BASE + [(101.0, 102.0, 100.5, 101.5, 5e7)] + [(101.0, 102.0, 95.0, 96.0, 5e7)] * 4
    rep = turtle.replay(_bars(rows), allow_shorts=False)
    assert rep["trades"], "fixture must produce a trade"
    for t in rep["trades"]:
        assert t["cost_r"] > 0, "a frictionless replay is not a real one"
        assert t["r"] == pytest.approx(t["gross_r"] - t["cost_r"], abs=1e-4)
        assert t["r"] < t["gross_r"], "cost always makes the net worse"


def test_zero_bps_reproduces_the_frictionless_replay(monkeypatch):
    monkeypatch.setattr(config, "TURTLE_COST_BPS", 0.0)
    rows = _BASE + [(101.0, 102.0, 100.5, 101.5, 5e7)] + [(101.0, 102.0, 95.0, 96.0, 5e7)] * 4
    rep = turtle.replay(_bars(rows), allow_shorts=False)
    for t in rep["trades"]:
        assert t["cost_r"] == 0.0 and t["r"] == pytest.approx(t["gross_r"])


def test_the_record_publishes_the_median_and_the_tail_concentration():
    """A trend system's mean is carried by a handful of trades. Publishing only
    the mean is how a fat tail gets read as an edge, so the median trade and
    the share held by the top ten travel with it."""
    trades = [{"r": -1.0, "gross_r": -1.0, "cost_r": 0.0, "system": 1,
               "reason": turtle.STOP} for _ in range(20)]
    trades.append({"r": 100.0, "gross_r": 100.0, "cost_r": 0.0, "system": 2,
                   "reason": turtle.CHANNEL})
    rec = turtle.summarize(trades)
    assert rec["avg_r"] > 0, "the mean says this system works"
    assert rec["median_r"] == -1.0, "the median says twenty of twenty-one lost"
    assert rec["top10_share"] > 0.99, "and one trade holds essentially all of it"


def test_top10_share_is_None_rather_than_a_share_of_a_loss():
    rec = turtle.summarize([{"r": -1.0, "gross_r": -1.0, "cost_r": 0.0,
                             "system": 1, "reason": turtle.STOP}])
    assert rec["top10_share"] is None


def test_shorts_mirror_every_rule():
    mids = [100.0] * 260 + ramp(99, 88) + [88.0] * 3
    rep = turtle.replay(band(mids), allow_shorts=True)
    pos = rep["position"]
    assert pos is not None and pos["side"] == "short"
    assert pos["entry"] == pytest.approx(99.0)
    assert pos["units"] == 4
    assert pos["stop"] == pytest.approx(96.0 + 4.0)   # last fill 96, +2N


def test_allow_shorts_false_really_takes_no_shorts():
    mids = [100.0] * 260 + ramp(99, 80) + [80.0] * 3
    rep = turtle.replay(band(mids), allow_shorts=False)
    assert rep["state"] == "flat"
    assert all(t["side"] == "long" for t in rep["trades"])


def test_a_frame_shorter_than_the_minimum_is_refused_not_guessed():
    assert turtle.replay(band([100.0] * (config.TURTLE_MIN_BARS - 1))) is None
    assert turtle.replay(None) is None
    assert turtle.replay(band([100.0] * 300).drop(columns=["High"])) is None


# ---------------------------------------------------------------------------
# the record
# ---------------------------------------------------------------------------

def test_R_is_measured_against_the_original_2N_risk():
    """One unit that moves exactly 2N in favour is +1R, whatever N is worth in
    dollars. Anchoring R to the position's own initial risk is what lets the
    per-name records be compared at all."""
    rec = turtle.summarize([{"r": 1.0, "system": 1, "reason": turtle.CHANNEL},
                            {"r": -1.0, "system": 2, "reason": turtle.STOP}])
    assert rec["n"] == 2 and rec["wins"] == 1 and rec["win_pct"] == 50.0
    assert rec["total_r"] == 0.0 and rec["avg_r"] == 0.0
    assert rec["by_system"]["1"]["n"] == 1 and rec["by_reason"]["stop"]["n"] == 1


def test_max_drawdown_is_peak_to_trough_on_the_closed_curve():
    # +5, -3, -1, +2  ->  curve 5, 2, 1, 3  ->  peak 5, trough 1  ->  -4
    rec = turtle.summarize([{"r": r, "system": 1, "reason": turtle.CHANNEL}
                            for r in (5.0, -3.0, -1.0, 2.0)])
    assert rec["total_r"] == 3.0
    assert rec["max_dd_r"] == -4.0


def test_an_empty_record_is_zero_and_None_not_a_fabricated_average():
    rec = turtle.summarize([])
    assert rec["n"] == 0 and rec["total_r"] == 0.0
    assert rec["win_pct"] is None and rec["avg_r"] is None


def test_every_published_number_is_finite_and_json_clean():
    from scanner import output
    df = band([100.0] * 260 + ramp(101, 140) + [140.0] * 5)
    row = turtle.build_row("TEST", {"name": "Test", "sector": "Materials"},
                           df, "nasdaq")
    assert row is not None
    text = output.dumps(row)
    assert "NaN" not in text and "Infinity" not in text


def test_ranking_puts_todays_signal_first_and_never_sorts_on_the_record():
    """A flattering replay must not float a name to the top: this page is a
    scanner, and letting the backtest column drive the order turns it into a
    curve-fit leaderboard."""
    fired = {"signal": "s2_long", "state": "flat", "dvol": 1.0,
             "nearest": {"distance_pct": 9.0}, "record": {"total_r": -50.0}}
    great = {"signal": "", "state": "flat", "dvol": 1e9,
             "nearest": {"distance_pct": 0.1}, "record": {"total_r": 900.0}}
    assert turtle.rank_key(fired) < turtle.rank_key(great)
    held = {"signal": "", "state": "long", "dvol": 1.0, "nearest": None, "record": {}}
    assert turtle.rank_key(held) < turtle.rank_key(great)


# ---------------------------------------------------------------------------
# liquidity
# ---------------------------------------------------------------------------

def test_the_liquidity_floor_removes_unfillable_breakouts():
    df = band([100.0] * 300)
    df["Volume"] = 100.0                       # $10k a day
    dvol, ok = turtle.liquidity(df, "nasdaq")
    assert dvol == pytest.approx(10_000.0) and ok is False
    df["Volume"] = 1e6                          # $100m a day
    assert turtle.liquidity(df, "nasdaq")[1] is True


def test_a_sub_floor_price_is_refused_on_the_market_that_sets_a_floor():
    df = band([0.5] * 300)
    df["Volume"] = 1e9
    assert turtle.liquidity(df, "nasdaq")[1] is False, "NASDAQ floor is $1.00"
    assert turtle.liquidity(df, "asx")[1] is True, "ASX floor is 10c"


# ---------------------------------------------------------------------------
# the runner
# ---------------------------------------------------------------------------

def test_the_params_block_echoes_the_real_constants():
    """The page renders rule numbers from THIS block rather than from its own
    prose, so a constant change cannot leave the page describing the old
    system. That property only holds if the block really reads config."""
    p = turtle_run.params_block()
    assert p["s1_entry"] == config.TURTLE_S1_ENTRY
    assert p["s2_entry"] == config.TURTLE_S2_ENTRY
    assert p["s1_exit"] == config.TURTLE_S1_EXIT
    assert p["s2_exit"] == config.TURTLE_S2_EXIT
    assert p["stop_n"] == config.TURTLE_STOP_N
    assert p["max_units"] == config.TURTLE_MAX_UNITS
    assert p["risk_pct"] == config.TURTLE_RISK_PCT


def test_the_original_parameters_are_the_shipped_parameters():
    """Not a tautology: it pins the NUMBERS. Retuning any of these makes the
    lens something other than the Turtle system, which is the one thing it
    exists to state exactly, so the change should have to be deliberate."""
    assert (config.TURTLE_S1_ENTRY, config.TURTLE_S1_EXIT) == (20, 10)
    assert (config.TURTLE_S2_ENTRY, config.TURTLE_S2_EXIT) == (55, 20)
    assert config.TURTLE_N_PERIOD == 20
    assert config.TURTLE_STOP_N == 2.0
    assert config.TURTLE_PYRAMID_STEP_N == 0.5
    assert config.TURTLE_MAX_UNITS == 4
    assert config.TURTLE_RISK_PCT == 0.01
    assert (config.TURTLE_MAX_UNITS_CLOSE_CORR,
            config.TURTLE_MAX_UNITS_LOOSE_CORR,
            config.TURTLE_MAX_UNITS_DIRECTION) == (6, 10, 12)
    assert (config.TURTLE_DRAWDOWN_STEP_PCT, config.TURTLE_DRAWDOWN_CUT_PCT) == (10.0, 20.0)


def test_the_aggregate_survives_an_empty_market():
    agg = turtle_run.aggregate([])
    assert agg["trades"] == 0 and agg["win_pct"] is None and agg["total_r"] == 0.0


def test_a_single_market_failure_must_not_discard_the_others():
    """turtle_run isolates per-market failures and still returns 1 if any
    failed. A step failure skips later steps by default, so without an
    explicit guard one flaky crypto fetch discards ASX's and NASDAQ's output
    AND -- the part that cannot be undone -- punches a permanent hole in the
    forward book, which has no backfill.

    The job must still go red. Only the discarding stops.
    """
    wf = (ROOT / ".github" / "workflows" / "turtle.yml").read_text(encoding="utf-8")
    commit = wf[wf.index("name: Commit & push"):]
    guard = commit[:commit.index("run: |")]
    assert "if: success() || failure()" in guard, \
        "the commit must survive a partial-failure scan"
    # and the alarm must be untouched
    assert "if: failure()" in wf, "a failed market must still alert"


def test_the_must_change_gate_is_ANY_OF_so_a_partial_run_still_commits():
    wf = (ROOT / ".github" / "workflows" / "turtle.yml").read_text(encoding="utf-8")
    line = [l for l in wf.splitlines() if "assert_staged.sh" in l][0]
    assert line.count("public/data/") == 3, "all three markets listed, ANY-OF"


def test_crypto_is_in_the_runner_markets_unlike_specs():
    """Specs excludes crypto because its price filter is a cents filter. Every
    Turtle parameter is expressed in N and is unit-free, so the same exclusion
    would be cargo-culting."""
    assert "crypto" in turtle_run.MARKETS


def test_the_replay_starts_where_the_name_became_TRADEABLE():
    """4.7: the gate was a TODAY gate on a FIVE-YEAR record.

    Here a name is illiquid for its first 300 bars and liquid for the last
    200. The old code replayed all 500 on the strength of this month's volume
    -- which on a "today's top 100" universe means the biggest contributors
    are exactly the names that grew into it. Only the liquid tail may count.
    """
    mids = [100.0] * 300 + list(ramp(101, 200)) + [200.0] * 100
    df = band(mids)
    df.iloc[:300, df.columns.get_loc("Volume")] = 1.0        # $100/day: unfillable
    first, share = turtle.tradeable_from(df, "nasdaq")
    assert first >= 300, "the illiquid head must not be tradeable"
    assert 0.3 < share < 0.5, f"about 40% of the window was liquid, got {share}"

    full = turtle.replay(df, allow_shorts=False)
    gated = turtle.replay(df, allow_shorts=False, start_i=first)
    assert len(gated["trades"]) <= len(full["trades"]), \
        "gating can only ever remove trades from the record"
    assert all(t["entry_date"] >= str(df.index[first])[:10] for t in gated["trades"])


def test_build_row_publishes_how_much_of_the_window_was_fillable():
    df = band([100.0] * 260 + ramp(101, 140) + [140.0] * 5)
    row = turtle.build_row("T", {"name": "T"}, df, "nasdaq")
    assert row is not None
    assert row["liquid_share"] == pytest.approx(1.0), "a fully liquid name reads 1.0"


def test_the_published_unit_numbers_do_not_understate_a_stop_out():
    """A field called `unit_risk` that published HALF what a stop-out costs is
    a trap. Two fields now: per-N, and the actual 2N loss."""
    df = band([100.0] * 260 + ramp(101, 140) + [140.0] * 5)
    row = turtle.build_row("T", {"name": "T"}, df, "nasdaq", equity=5000.0)
    assert row["unit_risk_per_n"] == pytest.approx(50.0)
    assert row["unit_stop_loss"] == pytest.approx(100.0)
    assert "unit_risk" not in row, "the ambiguous name must be gone, not aliased"


# ---------------------------------------------------------------------------
# the whole publish path, end to end
# ---------------------------------------------------------------------------

def test_scan_market_publishes_a_complete_payload(tmp_path, monkeypatch):
    """Drives universe -> download -> build_row -> write_json with synthetic
    frames. Yahoo is unreachable from a sandbox, so this is the only place the
    runner's actual wiring gets exercised before it runs in CI -- and wiring is
    exactly where a lens that works in isolation falls over (a renamed key, a
    frame handed over with the wrong index, a sort on a field the row lacks).
    """
    frames = {
        "FIRE.AX": band([100.0] * 260 + ramp(101, 120)[:1]),
        "HELD.AX": band([100.0] * 260 + ramp(101, 140)),
        "NEAR.AX": band([100.0] * 260 + ramp(99, 100)),
        "THIN.AX": band([100.0] * 300),          # dropped by the liquidity gate
        "SHRT.AX": band([100.0] * 260 + ramp(99, 86)),
        "SHORTHIST.AX": band([100.0] * 50),      # dropped for too little history
    }
    frames["THIN.AX"]["Volume"] = 10.0
    items = [{"symbol": k.split(".")[0], "name": k + " Ltd", "sector": "Materials", "yf": k}
             for k in frames]

    monkeypatch.setattr(turtle_run.universe, "load_universe", lambda m, full=True: items)
    monkeypatch.setattr(turtle_run.data, "download", lambda t, **kw: frames)
    monkeypatch.setattr(turtle_run, "OUT_DIR", str(tmp_path))

    payload = turtle_run.scan_market("asx")
    out = tmp_path / "asx_turtle.json"
    assert out.exists(), "the runner must publish where it says it does"
    on_disk = json.loads(out.read_text(encoding="utf-8"))

    # the file and the return value are the same object, not two renderings
    assert on_disk == payload

    assert payload["market"] == "asx" and payload["lens"] == "turtle"
    assert payload["universe_size"] == 6
    assert payload["skipped_short_history"] == 1, "SHORTHIST is under TURTLE_MIN_BARS"
    assert payload["skipped_illiquid"] == 1, "THIN trades $1,000 a day"
    syms = [r["symbol"] for r in payload["results"]]
    assert set(syms) == {"FIRE", "HELD", "NEAR", "SHRT"}
    assert syms[0] == "FIRE", "a signal that fired today outranks everything"

    agg = payload["aggregate"]
    assert agg["names"] == 4 and agg["fired_today"] == 1
    assert agg["long"] + agg["short"] + agg["flat"] == 4
    assert payload["params"]["s2_entry"] == config.TURTLE_S2_ENTRY

    # publishable: strictly finite, and no numpy types survived the trip
    text = out.read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text
    assert text.endswith("\n")


def test_a_name_yahoo_never_returned_is_COUNTED_not_invisible(tmp_path, monkeypatch):
    """The 2026-08-21 incident, pinned.

    A scheduled run got 5 of 101 crypto names back from Yahoo, evaluated ONE,
    and published `errors: 0`. The loop walked `frames`, so the 96 names that
    never came back were invisible BY CONSTRUCTION -- not in the dict, never
    iterated, no counter moved. Walking the universe instead is the fix.
    """
    universe = [{"symbol": f"T{i}", "name": f"T{i}", "sector": "", "yf": f"T{i}.AX"}
                for i in range(10)]
    # only 8 of 10 come back -- 80%, above the floor
    frames = {f"T{i}.AX": band([100.0] * 260 + ramp(101, 130)) for i in range(8)}
    monkeypatch.setattr(turtle_run.universe, "load_universe", lambda m, full=True: universe)
    monkeypatch.setattr(turtle_run.data, "download", lambda t, **kw: frames)
    monkeypatch.setattr(turtle_run, "OUT_DIR", str(tmp_path))

    payload = turtle_run.scan_market("asx")
    assert payload["skipped_no_data"] == 2, "the two absent names must be counted"
    assert payload["data_coverage_pct"] == pytest.approx(80.0)
    assert payload["universe_size"] == 10


def test_a_gutted_download_REFUSES_to_publish_over_a_good_file(tmp_path, monkeypatch):
    """The coverage floor. Every watchdog here checks file AGE, so a fresh
    file holding one name is indistinguishable from a healthy one -- which is
    exactly how the incident went unreported. The run must raise instead."""
    universe = [{"symbol": f"T{i}", "name": f"T{i}", "sector": "", "yf": f"T{i}.AX"}
                for i in range(100)]
    frames = {"T0.AX": band([100.0] * 260 + ramp(101, 130))}      # 1 of 100
    monkeypatch.setattr(turtle_run.universe, "load_universe", lambda m, full=True: universe)
    monkeypatch.setattr(turtle_run.data, "download", lambda t, **kw: frames)
    monkeypatch.setattr(turtle_run, "OUT_DIR", str(tmp_path))

    with pytest.raises(RuntimeError, match="coverage"):
        turtle_run.scan_market("crypto")
    assert not (tmp_path / "crypto_turtle.json").exists(), \
        "yesterday's file is better than a gutted one"


def test_the_error_rate_is_reported_against_the_UNIVERSE(tmp_path, monkeypatch, capsys):
    """`errors.report(len(frames))` meant a run that got 5 names back and threw
    on none of them printed a flawless 0/5."""
    universe = [{"symbol": f"T{i}", "name": f"T{i}", "sector": "", "yf": f"T{i}.AX"}
                for i in range(10)]
    frames = {f"T{i}.AX": band([100.0] * 260 + ramp(101, 130)) for i in range(8)}
    monkeypatch.setattr(turtle_run.universe, "load_universe", lambda m, full=True: universe)
    monkeypatch.setattr(turtle_run.data, "download", lambda t, **kw: frames)
    monkeypatch.setattr(turtle_run, "OUT_DIR", str(tmp_path))
    turtle_run.scan_market("asx")
    out = capsys.readouterr().out
    assert "coverage 80.0%" in out and "2 no data" in out


def test_a_market_that_throws_is_reported_not_swallowed(monkeypatch, capsys):
    """TOP100 #67: a market that failed ENTIRELY used to print one line and
    exit 0, so a night with no ASX file looked like a night with no breakouts."""
    def boom(*a, **kw):
        raise RuntimeError("yahoo said no")
    monkeypatch.setattr(turtle_run, "scan_market", boom)
    rc = turtle_run.main(["--market", "asx"])
    assert rc == 1
    assert "FAILED" in capsys.readouterr().out


def test_one_bad_frame_never_kills_the_scan(tmp_path, monkeypatch):
    frames = {"GOOD.AX": band([100.0] * 260 + ramp(101, 130)),
              "BAD.AX": band([100.0] * 300)}
    frames["BAD.AX"]["High"] = "not a number"      # forces build_row to throw
    items = [{"symbol": k.split(".")[0], "name": k, "sector": "", "yf": k} for k in frames]
    monkeypatch.setattr(turtle_run.universe, "load_universe", lambda m, full=True: items)
    monkeypatch.setattr(turtle_run.data, "download", lambda t, **kw: frames)
    monkeypatch.setattr(turtle_run, "OUT_DIR", str(tmp_path))
    payload = turtle_run.scan_market("asx")
    assert [r["symbol"] for r in payload["results"]] == ["GOOD"]
    assert payload["errors"] >= 1, "the throw is COUNTED, not silent"


# ---------------------------------------------------------------------------
# the futures sleeve — the vehicle the system was designed for
# ---------------------------------------------------------------------------

def test_the_sleeve_is_diversified_across_real_market_groups():
    """One hundred NASDAQ names is one tech factor wearing a hundred tickers.
    Diversification across genuinely different markets is the MECHANISM that
    makes the Turtle expectancy positive, so the sleeve has to actually span
    them or it is testing something the system never claimed."""
    import collections
    groups = collections.Counter(f["group"] for f in config.TURTLE_FUTURES)
    assert len(config.TURTLE_FUTURES) >= 18, "the Turtles ran about twenty markets"
    for need in ("currency", "rates", "metals", "energy", "softs"):
        assert groups[need] >= 2, f"only {groups[need]} {need} market(s)"


def test_grains_and_meats_are_excluded_exactly_as_they_were():
    """Dennis excluded grains because he was already at exchange position
    limits in them for his own account, and meats over a pit corruption
    problem. Adding them because a data feed offers them would be a different
    portfolio wearing the same name."""
    syms = {f["symbol"] for f in config.TURTLE_FUTURES}
    for banned in ("ZC", "ZS", "ZW", "LE", "HE", "GF"):
        assert banned not in syms, f"{banned} was not a Turtle market"


def test_every_market_carries_a_dollars_per_point():
    """The single most important number in the sleeve: unit size is
    (1% x equity) / (N x dpp), so a wrong dpp misprices every position in
    that market and nothing downstream can detect it."""
    for f in config.TURTLE_FUTURES:
        assert f.get("dpp", 0) > 0, f"{f['symbol']} has no dollars-per-point"
        assert f["yf"].endswith("=F"), f"{f['symbol']} is not a futures series"
        if f.get("micro"):
            assert 0 < f["micro_dpp"] < f["dpp"], \
                f"{f['symbol']}'s micro must be smaller than its full contract"


def test_contract_sizing_says_a_unit_DOES_NOT_FIT_rather_than_rounding():
    """A $5,000 account cannot hold one crude contract at 1% risk. The honest
    output is a refusal plus the real cost of taking one anyway -- rounding
    0.025 contracts up to 1 is roughly 40x the intended size, and is the
    commonest way a small account destroys itself while believing it is
    following rules."""
    cl = next(f for f in config.TURTLE_FUTURES if f["symbol"] == "CL")
    c = turtle.contract_sizing(5000.0, 2.0, cl)
    assert c["full_contracts"] == pytest.approx(0.025)
    assert c["unit_fits"] is False
    assert c["one_contract_risk_pct"] > 2.0, \
        "and it must state what taking one anyway really risks"


def test_a_big_enough_account_makes_the_unit_fit():
    cl = next(f for f in config.TURTLE_FUTURES if f["symbol"] == "CL")
    assert turtle.contract_sizing(500_000.0, 2.0, cl)["unit_fits"] is True


def test_sizing_scales_with_dollars_per_point_not_with_price():
    """Two markets at the same price and the same N size completely
    differently, because the contract multiplier is what converts a point into
    money. Ignoring dpp is the bug that would make a futures sleeve read like
    a stock sleeve."""
    a = turtle.unit_size(100_000.0, 2.0, dollars_per_point=1_000)
    b = turtle.unit_size(100_000.0, 2.0, dollars_per_point=50)
    assert b == pytest.approx(a * 20)


def test_futures_is_a_declared_list_so_the_sleeve_has_no_survivorship():
    """Every other market here is 'whatever is listed today', which selects on
    outcomes. The sleeve is fixed and chosen on 1983 grounds, so nothing in it
    was picked because it went up."""
    src = (ROOT / "scanner" / "turtle_run.py").read_text(encoding="utf-8")
    assert "config.TURTLE_FUTURES" in src
    assert "futures" in turtle_run.MARKETS


def _rolling_tape(rolls=7, step=4.0, seed=3, n=500):
    """A back-adjusted continuous series: a quiet tape with quarterly contract
    rolls folded in as price steps, which is what a "=F" series really is."""
    rs = np.random.RandomState(seed)
    mid = 100 + np.cumsum(rs.normal(0, 0.4, n))
    for k, r in enumerate(range(63, n, 63)):
        if k >= rolls:
            break
        mid[r:] += (1 if k % 2 else -1) * step
    return pd.DataFrame(
        {"Open": mid, "High": mid + 0.5, "Low": mid - 0.5, "Close": mid,
         "Volume": np.full(n, 1e6)},
        index=pd.bdate_range("2015-01-01", periods=n))


def test_contract_rolls_are_detected_in_a_back_adjusted_series():
    """A roll is not a tradeable overnight move, but true range counts it in
    full. Measured: N runs 13-22% high on the bar AFTER a roll -- the bar a
    position opened that day is sized and stopped from."""
    r = turtle.roll_suspects(_rolling_tape(rolls=7))
    assert r["bars"] == 7, f"7 rolls simulated, {r['bars']} found"
    assert 0 < r["share"] < 0.05
    assert r["last"]


def test_an_ordinary_tape_flags_nothing():
    """The detector must not fire on stocks or crypto, which have no rolls --
    a false positive here would put a scary caveat on a clean market."""
    assert turtle.roll_suspects(band([100.0] * 300))["bars"] == 0
    assert turtle.roll_suspects(band(list(range(100, 400))))["bars"] == 0


def test_it_says_whether_TODAYS_N_is_affected():
    """The only part that changes a decision being made now: is a roll inside
    the current 20-bar N window?"""
    tape = _rolling_tape(rolls=7)
    assert turtle.roll_suspects(tape)["in_n_window"] is False
    # put a roll two bars from the end
    late = tape.copy()
    late.iloc[-2:, :] += 6.0
    assert turtle.roll_suspects(late)["in_n_window"] is True


def test_roll_detection_does_NOT_touch_the_true_range_formula():
    """Detection and disclosure only. Quietly winsorising TR to make a futures
    number look better is the exact dishonesty this lens exists to refuse, and
    the true-range formula is frozen detection law."""
    tape = _rolling_tape(rolls=7)
    before = float(turtle.compute_n(tape).iloc[-1])
    turtle.roll_suspects(tape)
    assert float(turtle.compute_n(tape).iloc[-1]) == before
    # Asked of the CODE, not the prose: the docstring explains at length why
    # winsorising TR would be dishonest, and a substring ban reads that
    # justification as the offence.
    src = (ROOT / "scanner" / "turtle.py").read_text(encoding="utf-8")
    fn = src[src.index("def roll_suspects"):src.index("def liquidity")]
    body = fn.split('"""')[-1]                      # everything after the docstring
    for banned in ("clip(", "winsor", "atr(", "compute_n("):
        assert banned not in body, f"roll_suspects must not modify N ({banned})"
    assert "return" in body and "df[" in body, "the slice must be the real body"


def test_only_futures_rows_carry_the_roll_block():
    """Stocks have no rolls; publishing an empty block on 2,212 ASX rows would
    be noise in every payload."""
    df = band([100.0] * 260 + ramp(101, 140) + [140.0] * 5)
    stock = turtle.build_row("T", {"name": "T"}, df, "nasdaq")
    assert "rolls" not in stock
    fut = turtle.build_row("CL", {"name": "Crude", "dpp": 1000, "micro": "MCL",
                                  "micro_dpp": 100, "group": "energy"},
                           df, "futures")
    assert fut is not None and "rolls" in fut


# ---------------------------------------------------------------------------
# fences — the freeze, and the report-only promise
# ---------------------------------------------------------------------------

def test_nothing_in_the_broker_reads_the_turtle_lens():
    for p in (ROOT / "scanner" / "broker").rglob("*.py"):
        assert "turtle" not in p.read_text(encoding="utf-8").lower(), \
            f"the Turtle lens is report-only and must not reach the bot: {p}"


def test_no_turtle_constant_leaks_into_the_bots_published_rules():
    """bot_rules.json is the BOT's rule set and the dashboard warns on drift
    against it. A fourth lens's constants in there would be describing a
    system the bot does not run."""
    src = (ROOT / "scanner" / "run.py").read_text(encoding="utf-8")
    assert "TURTLE_" not in src
    rules = ROOT / "public" / "data" / "bot_rules.json"
    if rules.exists():
        assert "turtle" not in rules.read_text(encoding="utf-8").lower()


def test_the_lens_never_writes_anything_but_its_own_files():
    src = (ROOT / "scanner" / "turtle_run.py").read_text(encoding="utf-8")
    assert src.count("output.write_json(") == 1
    assert "_turtle.json" in src
    for forbidden in ("vivek_bot_book", "alert_history", "sector_map",
                      "journal/", "bot_rules"):
        assert forbidden not in src, f"the Turtle runner touches {forbidden}"


def test_the_engine_does_not_import_the_bot():
    """Asked of the IMPORTS, not of the file's text.

    A substring ban would fail on this module's own docstring, which explains
    at length why scanner/broker is never imported -- the Tier 3 trap where
    the justification reads as the offence.
    """
    for name in ("turtle.py", "turtle_run.py"):
        src = (ROOT / "scanner" / name).read_text(encoding="utf-8")
        imports = [ln.strip() for ln in src.splitlines()
                   if ln.strip().startswith(("import ", "from "))]
        for ln in imports:
            assert "broker" not in ln, f"{name} imports the bot: {ln}"
            assert "vivek" not in ln.lower(), f"{name} imports VIVEK: {ln}"


def test_prints_are_ascii_only():
    """Project rule 9 -- Windows consoles are cp1252 and choke on arrows."""
    for name in ("turtle.py", "turtle_run.py"):
        for i, line in enumerate((ROOT / "scanner" / name).read_text(encoding="utf-8").splitlines(), 1):
            if "print(" in line or 'f"[' in line:
                assert line.isascii(), f"{name}:{i} non-ascii in a print: {line!r}"


# ---------------------------------------------------------------------------
# the futures sleeve's blast radius and its coverage floor (2026-08-21)
# ---------------------------------------------------------------------------

def test_a_futures_fetch_failure_never_costs_an_equity_publish(tmp_path, monkeypatch):
    """`=F` symbols have never been through data.download in this repo, so the
    first futures night is the night MOST likely to fail -- and a failure
    there must cost the futures file only. Futures is deliberately FIRST in
    the market list here, which is the stronger ordering claim: even a
    failure that precedes the equity scans must leave them publishing. The
    run still returns 1, so the alarm is unchanged; only the discarding
    stops."""
    eq_frames = {"GOOD.AX": band([100.0] * 260 + ramp(101, 130))}
    items = [{"symbol": "GOOD", "name": "GOOD", "sector": "", "yf": "GOOD.AX"}]

    def fake_download(tickers, **kw):
        if any(str(t).endswith("=F") for t in tickers):
            return {}                     # the whole =F download dies
        return eq_frames

    monkeypatch.setattr(turtle_run.universe, "load_universe",
                        lambda m, full=True: items)
    monkeypatch.setattr(turtle_run.data, "download", fake_download)
    monkeypatch.setattr(turtle_run, "OUT_DIR", str(tmp_path))

    rc = turtle_run.main(["--market", "futures,asx"])
    assert rc == 1, "a failed market is still a red run"
    assert (tmp_path / "asx_turtle.json").exists(), \
        "the equity publish must survive the futures failure"
    assert not (tmp_path / "futures_turtle.json").exists(), \
        "and nothing may be published for the market that failed"


def test_THIRTEEN_of_twentyone_futures_priced_refuses_to_publish(tmp_path, monkeypatch):
    """The arithmetic the shared floor got wrong: 13 of 21 is 61.9%, ABOVE
    the 60% share floor, so the old rule published a sleeve missing eight
    contracts -- whole asset groups absent -- as if it were whole. The
    absolute ceiling for small universes must catch it, and the refusal must
    NAME every missing contract, because on a fixed 21-row table each absence
    is a market group rather than throttle noise."""
    sleeve = config.TURTLE_FUTURES
    assert len(sleeve) == 21, "the sleeve arithmetic below assumes 21 rows"
    frames = {f["yf"]: band([100.0] * 300) for f in sleeve[:13]}
    monkeypatch.setattr(turtle_run.data, "download", lambda t, **kw: frames)
    monkeypatch.setattr(turtle_run, "OUT_DIR", str(tmp_path))

    with pytest.raises(RuntimeError) as e:
        turtle_run.scan_market("futures")
    msg = str(e.value)
    for f in sleeve[13:]:
        assert f["symbol"] in msg, f"the refusal must name {f['symbol']}"
    assert not (tmp_path / "futures_turtle.json").exists(), \
        "yesterday's file is better than a gutted one"


def test_nineteen_of_twentyone_still_publishes_and_NAMES_the_missing(tmp_path, monkeypatch):
    """The other side of the ceiling: one or two individually broken Yahoo
    symbols must not hold the whole sleeve hostage forever. Two missing
    publishes -- with both absentees named in the payload, not merely
    counted."""
    sleeve = config.TURTLE_FUTURES
    frames = {f["yf"]: band([100.0] * 300) for f in sleeve[:19]}
    monkeypatch.setattr(turtle_run.data, "download", lambda t, **kw: frames)
    monkeypatch.setattr(turtle_run, "OUT_DIR", str(tmp_path))

    payload = turtle_run.scan_market("futures")
    assert (tmp_path / "futures_turtle.json").exists()
    assert payload["skipped_no_data"] == 2
    assert payload["skipped_no_data_symbols"] == \
        sorted(f["symbol"] for f in sleeve[19:]), \
        "each absence on a small sleeve is an asset group and must be named"


def test_equity_universes_KEEP_the_share_floor_not_the_absolute_one(tmp_path, monkeypatch):
    """The sleeve rule must not silently tighten ASX/NASDAQ/crypto: 62 of 100
    priced is dozens of names missing -- far beyond the absolute ceiling --
    but 62% is above the 60% share floor a directory-scale universe is judged
    by, so the market still publishes. And at that scale the missing are NOT
    named: the list would be hundreds of lines of throttle noise."""
    universe = [{"symbol": f"T{i}", "name": f"T{i}", "sector": "", "yf": f"T{i}.AX"}
                for i in range(100)]
    frames = {f"T{i}.AX": band([100.0] * 260 + ramp(101, 130)) for i in range(62)}
    monkeypatch.setattr(turtle_run.universe, "load_universe",
                        lambda m, full=True: universe)
    monkeypatch.setattr(turtle_run.data, "download", lambda t, **kw: frames)
    monkeypatch.setattr(turtle_run, "OUT_DIR", str(tmp_path))

    payload = turtle_run.scan_market("asx")
    assert (tmp_path / "asx_turtle.json").exists()
    assert payload["data_coverage_pct"] == pytest.approx(62.0)
    assert payload["skipped_no_data_symbols"] == []


def test_the_small_universe_ceiling_actually_covers_the_sleeve():
    """Dead-code insurance: grow the sleeve past TURTLE_SMALL_UNIVERSE_MAX and
    the absolute rule silently stops applying to the very universe it was
    built for -- this fails instead. And the ceiling must be a real gate:
    more permissive than the sleeve size and it never fires."""
    assert 0 < len(config.TURTLE_FUTURES) <= config.TURTLE_SMALL_UNIVERSE_MAX
    assert 0 < config.TURTLE_SMALL_UNIVERSE_MAX_MISSING < len(config.TURTLE_FUTURES)


def test_the_coverage_rule_is_PUBLISHED_beside_the_results():
    """The page states the floor from params rather than hardcoding it, per
    the mirror rule -- so the params block must actually carry all three
    numbers the sentence is built from."""
    p = turtle_run.params_block()
    assert p["min_coverage_pct"] == config.TURTLE_MIN_COVERAGE_PCT
    assert p["small_universe_max"] == config.TURTLE_SMALL_UNIVERSE_MAX
    assert p["small_universe_max_missing"] == config.TURTLE_SMALL_UNIVERSE_MAX_MISSING
