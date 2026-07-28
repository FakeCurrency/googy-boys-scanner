"""TOP100 Tier 4d/4e — engine correctness (#63, #65, #70, #71, #72, #73).

Six items that all live in the layer where a number is COMPUTED rather than
where it is displayed or guarded. Four are fixes; one (#70) is a finding that
the code is already right, pinned here so the ratchet cannot be "fixed" into
something worse by a later reading of the same docstring; one (#73) is a pure
speed-up whose entire correctness claim is "the output did not move at all",
so it is tested against a frozen copy of the code it replaced.
"""

import sys
import types

import numpy as np
import pandas as pd
import pytest

from scanner import config, indicators, reversal, scan, sectorcache, vivek

pytestmark = pytest.mark.risk

REPO = __import__("pathlib").Path(__file__).resolve().parents[1]


# ── frame builders ────────────────────────────────────────────────────────────

def _walk(n=340, seed=3, drift=0.0, start=100.0):
    rs = np.random.RandomState(seed)
    close = start + np.cumsum(rs.normal(drift, 0.2, n))
    return _ohlc(close)


def _ohlc(close):
    close = np.asarray(close, dtype="float64")
    return pd.DataFrame(
        {"Open": close * 0.999, "High": close * 1.01,
         "Low": close * 0.99, "Close": close, "Volume": 2e6},
        index=pd.date_range("2021-01-01", periods=len(close), freq="D"))


def _flat(n=340, price=100.0):
    """A halted name: not one tick of movement, from the first bar to the last."""
    return _ohlc(np.full(n, price))


# ══ #63 — a NaN risk is not a positive risk ══════════════════════════════════
#
# `_build_levels` promised "no plan unless the stop gives positive risk" and
# tested `risk <= 0`, which is False for NaN. The plan was therefore BUILT, and
# every downstream gate is a `>` or a `<` that NaN also passes — up to and
# including the daily/weekly loss guards, which a NaN `risk_usd` disarms for the
# whole book. These tests pin the enforcement, and pin that it only ever removes.

def test_a_nan_swing_low_no_longer_builds_a_plan():
    df = _walk()
    assert vivek._build_levels(df, "long", 100.0, 99.0,
                               float("nan"), 101.0, 1.0) == {}


def test_a_nan_atr_no_longer_builds_a_plan():
    # `max(atr, entry * 0.001)` keeps the NaN: `0.1 > nan` is False, so Python's
    # max returns its first argument. This is the likelier of the two routes in.
    df = _walk()
    assert vivek._build_levels(df, "long", 100.0, 99.0,
                               98.0, 101.0, float("nan")) == {}
    assert vivek._build_levels(df, "short", 100.0, 101.0,
                               98.0, 102.0, float("nan")) == {}


def test_the_old_guard_really_did_let_nan_through():
    """The whole item in one line: `<= 0` and `not (> 0)` are not the same test.

    Without this the fix reads like a style change. NaN is the only value in
    Python for which the two disagree, and it is exactly the value that got in.
    """
    nan = float("nan")
    assert (nan <= 0) is False          # the old guard: NaN passes, plan built
    assert (not (nan > 0)) is True      # the new guard: NaN rejected
    for finite in (-5.0, -0.001, 0.0, 0.001, 5.0, 1e9):
        assert (finite <= 0) == (not (finite > 0))


def test_the_change_can_only_ever_remove_a_plan_never_add_one():
    """Every input that built a plan before still builds the identical plan."""
    df = _walk()
    for direction, level, sl, sh in (("long", 99.0, 98.0, 101.0),
                                     ("short", 101.0, 98.0, 102.0)):
        lv = vivek._build_levels(df, direction, 100.0, level, sl, sh, 1.0)
        assert lv, "a finite, positive-risk plan must still be built"
        assert lv["risk"] > 0
        assert lv["direction"] == direction
        # and the ordering the rest of the system relies on is intact
        if direction == "long":
            assert lv["stop"] < lv["entry"] < lv["tp1"] < lv["tp2"] < lv["tp3"]
        else:
            assert lv["stop"] > lv["entry"] > lv["tp1"] > lv["tp2"] > lv["tp3"]


def test_a_non_positive_finite_risk_is_still_refused():
    """The pre-existing behaviour, unchanged — a stop on the wrong side."""
    df = _walk()
    assert vivek._build_levels(df, "long", 100.0, 110.0, 110.0, 111.0, 0.01) == {}


def test_structural_targets_guard_is_depth_only_and_says_so():
    """#63's second guard. Unreachable in production today; kept correct anyway.

    Its fallback is what makes it worth having: `[]` means "no structure, use
    R-multiples", and R-multiples off a NaN risk are NaN TARGETS rather than no
    plan — i.e. the fallback is worse than the bug it guards against.
    """
    df = _walk()
    assert vivek._structural_targets(df, "long", 100.0, float("nan")) == []
    assert vivek._structural_targets(df, "long", 100.0, 0.0) == []
    assert vivek._structural_targets(df, "short", 100.0, -1.0) == []


def test_the_sole_production_caller_guards_before_it_reaches_the_helper():
    """Why the helper's guard is depth-only: `_build_levels` already refused."""
    src = (REPO / "scanner" / "vivek.py").read_text(encoding="utf-8")
    guard = src.index("if not (risk > 0):          # TOP100 #63")
    call = src.index("struct = _structural_targets(df, direction, entry, risk)")
    assert guard < call, "the guard must precede the only call site"


# ══ #70 — the hysteresis ratchet works; this pins WHY, not a change ═══════════
#
# Triaged as a defect ("the max_runs ratchet is defeated by grade ALTERNATION")
# and, on replay, found not to be one. The tests below are the replay. They exist
# so the next reader of the docstring reaches the same conclusion without having
# to rebuild the simulation, and so "fixing" the reset fails loudly.

def _replay(scores, dirs=None, raw_of=None):
    """scan.py's exact feedback loop: publish the held grade, feed `held` back."""
    published, prev, held, prev_dir = [], None, 0, None
    for i, score in enumerate(scores):
        cur_dir = (dirs or ["LONG"] * len(scores))[i]
        raw = (raw_of or vivek.grade_from_points)(score, config.VIVEK_GRADE_CUTOFFS)
        grade, held = vivek.apply_grade_hysteresis(
            score, raw, prev, prev_dir=prev_dir, cur_dir=cur_dir, held_runs=held)
        published.append(grade)
        prev, prev_dir = grade, cur_dir
    return published


def test_the_replay_matches_the_real_call_site():
    """The loop above is a mirror, so pin the three things it mirrors."""
    src = (REPO / "scanner" / "scan.py").read_text(encoding="utf-8")
    assert 'points, raw_grade, prev.get("grade"),' in src        # PUBLISHED grade
    assert 'held_runs=prev.get("held", 0))' in src               # fed back
    assert "grade, held_runs = vivek.apply_grade_hysteresis(" in src


def test_a_decaying_setup_demotes_after_exactly_max_runs():
    """8 then 7 forever. A+ cutoff is 8, margin 1, so 7 is holdable — 3 times."""
    out = _replay([8, 7, 7, 7, 7, 7])
    assert out[0] == "A+"
    assert out[1:4] == ["A+", "A+", "A+"], "three renewals, per max_runs"
    assert out[4] == "A", "the 5th scan demotes — the ratchet bites"
    assert out[5] == "A"


def test_a_score_crash_demotes_immediately_without_spending_a_renewal():
    """5 is below `cut[A+] - margin` = 7, so the hold is never eligible."""
    assert _replay([8, 5, 5]) == ["A+", "B+", "B+"]


def test_a_direction_flip_kills_the_hold_on_the_spot():
    """The previous badge described the opposite trade."""
    assert _replay([8, 7], dirs=["LONG", "SHORT"]) == ["A+", "A"]
    assert _replay([8, 7], dirs=["LONG", "LONG"]) == ["A+", "A+"]


def test_oscillation_never_demotes_AND_THAT_IS_THE_POINT():
    """NOT a defect. Do not "fix" this by carrying held_runs through a re-earn.

    8,7,8,7,... never demotes because every 8 GENUINELY RE-EARNS A+ on its own
    score — `raw_grade == prev_grade`, the first early return, hysteresis not
    even consulted. Resetting is correct: the counter bounds how long a grade may
    be held WITHOUT being earned, and this grade was just earned. Making the
    counter survive a re-earn would demote a setup that is scoring at its cutoff
    every other scan, which is precisely the A+/A boundary wobble the whole
    mechanism exists to smooth. The docstring's claim is about CONSECUTIVE holds
    and is satisfied here: the longest unearned run below is one.
    """
    assert set(_replay([8, 7] * 6)) == {"A+"}
    assert set(_replay([8, 7, 7] * 4)) == {"A+"}
    # ...and the run of genuinely unearned scans never exceeds the bound.
    long_decay = _replay([8] + [7] * 10)
    assert long_decay.count("A+") == 4, "1 earned + 3 held, then it decays"


def test_a_promotion_is_never_held_back():
    assert _replay([6, 8]) == ["A", "A+"]


def test_max_runs_is_the_constant_the_docstring_names():
    assert config.VIVEK_GRADE_HYSTERESIS_MAX_RUNS == 3
    assert config.VIVEK_GRADE_HYSTERESIS == 1
    assert dict(config.VIVEK_GRADE_CUTOFFS)["A+"] == 8


# ══ #71 — RSI is NaN where RSI is undefined, not 100 ══════════════════════════

def test_warm_up_is_nan_not_a_reading():
    out = indicators.rsi(pd.Series(np.linspace(100, 110, 40)), 14)
    assert np.isnan(out.iloc[0]), "RSI does not exist on the first bar"


def test_a_series_with_no_losses_is_still_a_genuine_100():
    """The one case the old `.fillna(100)` was actually written for. Kept."""
    out = indicators.rsi(pd.Series(np.linspace(100, 200, 60)), 14)
    assert out.iloc[-1] == pytest.approx(100.0)


def test_a_halted_series_is_nan_rather_than_maximally_overbought():
    """A price that has not moved reported the most extreme reading available."""
    out = indicators.rsi(pd.Series(np.full(60, 100.0)), 14)
    assert np.isnan(out.iloc[-1])
    assert not (out.iloc[-1] == 100.0)


def test_a_falling_series_is_unaffected():
    out = indicators.rsi(pd.Series(np.linspace(200, 100, 60)), 14)
    assert 0 <= float(out.iloc[-1]) < 50


def _rsi_pre_71(series, period=14):
    """The implementation as it stood before #71, for the equivalence check."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return (100 - 100 / (1 + rs)).fillna(100)


def test_the_only_readings_that_moved_are_the_two_undefined_ones():
    for build in (lambda: pd.Series(np.linspace(100, 200, 80)),
                  lambda: pd.Series(_walk(120, seed=11)["Close"].to_numpy()),
                  lambda: pd.Series(np.linspace(200, 100, 80))):
        s = build()
        old, new = _rsi_pre_71(s), indicators.rsi(s)
        # ignore the warm-up bar, which is undefined by construction
        pd.testing.assert_series_equal(old.iloc[1:], new.iloc[1:])


@pytest.mark.parametrize("consumer", [reversal])
def test_no_live_consumer_outcome_changes(monkeypatch, consumer):
    """The "no behaviour change" claim, tested rather than argued.

    Runs the REAL `evaluate` twice — once against the shipped `rsi`, once against
    the pre-#71 one — and compares every derived field. The raw `rsi`/`rsi_ma`
    readings are excluded because they are the thing that changed.
    """
    frames = [_walk(400, seed=s, drift=d)
              for s, d in ((5, 0.05), (6, -0.05), (7, 0.0), (8, 0.15))]
    for df in frames:
        new = consumer.evaluate(df)
        monkeypatch.setattr(consumer, "rsi", _rsi_pre_71)
        old = consumer.evaluate(df)
        monkeypatch.undo()
        assert (new is None) == (old is None)
        if new is None:
            continue
        derived = {k: v for k, v in new.items() if k not in ("rsi", "rsi_ma")}
        assert derived == {k: v for k, v in old.items() if k not in ("rsi", "rsi_ma")}


def test_a_halted_name_never_reaches_the_rsi_chip_at_all(monkeypatch):
    """Why the flat-series change cannot move a trade, stated as a test.

    `reversal.evaluate` returns None at `c <= s26l` — a flat close IS its own
    26-SMA — so the halted frame that #71 re-values is rejected several steps
    before RSI is consulted. Under BOTH implementations.
    """
    df = _flat(400)
    assert reversal.evaluate(df) is None
    monkeypatch.setattr(reversal, "rsi", _rsi_pre_71)
    assert reversal.evaluate(df) is None


# ══ #72 — a "200 SMA" that is not a 200 SMA now says so ══════════════════════

def test_a_short_frame_is_flagged_as_a_proxy():
    plan = vivek.build_tf_plan(_walk(60, seed=21, drift=0.05), "long")
    assert plan is not None
    assert plan["sma_window"] == 60
    assert plan["sma_proxy"] is True


def test_a_full_history_frame_is_not_flagged():
    plan = vivek.build_tf_plan(_walk(340, seed=22, drift=0.02), "long")
    assert plan is not None
    assert plan["sma_window"] == config.VIVEK_SMA
    assert plan["sma_proxy"] is False


def test_the_flag_is_derived_here_not_recomputed_by_each_reader():
    """`sma_proxy` must agree with `sma_window` for every frame length."""
    for n in (35, 60, 150, 199, 201, 340):
        plan = vivek.build_tf_plan(_walk(n, seed=23, drift=0.05), "long")
        if plan is None:
            continue
        assert plan["sma_proxy"] == (plan["sma_window"] < config.VIVEK_SMA)


def test_a_frame_under_the_minimum_still_builds_nothing():
    assert vivek.build_tf_plan(_walk(config.VIVEK_MIN_TF_BARS - 1), "long") is None


def _rows(*specs):
    return [{"symbol": sym, "grade_raw": g, "sma_proxy": p, "sma_window": w}
            for sym, g, p, w in specs]


def test_the_proxy_count_prints_on_a_clean_run_too(capsys):
    """A line that only appears when something is wrong has no baseline."""
    scan._report_sma_proxies(_rows(("AAA", "A+", False, 200),
                                   ("BBB", "A", False, 200)))
    out = capsys.readouterr().out
    assert "2/2 setups key off a full 200-period level" in out
    assert "0 use a shorter proxy" in out
    assert "WARNING" not in out


def test_the_warning_is_scoped_to_what_the_bot_can_actually_buy(capsys):
    scan._report_sma_proxies(_rows(("AAA", "WATCH", True, 40),
                                   ("BBB", "B+", True, 55)))
    out = capsys.readouterr().out
    assert "2 use a shorter proxy" in out
    assert "proxy windows 40-55 bars" in out
    assert "WARNING" not in out, "a WATCH-grade short history is a curiosity"

    scan._report_sma_proxies(_rows(("CCC", "A+", True, 40),
                                   ("DDD", "WATCH", True, 55)))
    out = capsys.readouterr().out
    assert "WARNING 1 tradeable-grade setup(s)" in out
    assert "CCC" in out and "DDD" not in out


def test_every_tradeable_grade_is_covered_by_the_warning(capsys):
    for grade in sorted(config.TRADEABLE_GRADES):
        scan._report_sma_proxies(_rows(("ZZZ", grade, True, 42)))
        assert "WARNING" in capsys.readouterr().out, grade


def test_an_empty_result_set_prints_nothing(capsys):
    scan._report_sma_proxies([])
    assert capsys.readouterr().out == ""


def test_the_row_reports_the_headline_plan_not_the_daily_one():
    """`hp` is the plan the row shows and the bot reads; 1D may not be it."""
    src = (REPO / "scanner" / "scan.py").read_text(encoding="utf-8")
    assert '"sma_proxy": bool(hp.get("sma_proxy")),' in src
    assert '"sma_window": hp.get("sma_window"),' in src


def test_the_payloads_top_level_sma_is_only_a_config_echo():
    """The field that could not contradict a proxy — the reason #72 exists."""
    src = (REPO / "scanner" / "scan.py").read_text(encoding="utf-8")
    assert '"sma": config.VIVEK_SMA,' in src


# ══ #65 — 'nothing was learned' and 'there is nothing to learn' ══════════════

def _fake_yf(monkeypatch, info=None, raises=False):
    mod = types.ModuleType("yfinance")

    class _T:
        def __init__(self, sym):
            self.sym = sym

        def get_info(self):
            if raises:
                raise RuntimeError("rate limited")
            return info

    mod.Ticker = _T
    monkeypatch.setitem(sys.modules, "yfinance", mod)


def test_a_real_sector_is_ok(monkeypatch):
    _fake_yf(monkeypatch, {"sector": "  Financials  "})
    assert sectorcache._fetch_sector("CBA.AX") == ("Financials", "ok")


def test_a_profile_with_no_sector_is_none_not_failed(monkeypatch):
    """An ETF or a trust. Retrying returns the same nothing tomorrow."""
    _fake_yf(monkeypatch, {"longName": "Some ETF"})
    assert sectorcache._fetch_sector("VAS.AX") == ("", "none")
    _fake_yf(monkeypatch, {"sector": None})
    assert sectorcache._fetch_sector("VAS.AX") == ("", "none")
    _fake_yf(monkeypatch, None)
    assert sectorcache._fetch_sector("VAS.AX") == ("", "none")


def test_a_raising_fetch_is_failed_not_none(monkeypatch):
    """Nothing was learned. This name is worth retrying; the ETF is not."""
    _fake_yf(monkeypatch, raises=True)
    assert sectorcache._fetch_sector("NOPE.AX") == ("", "failed")


def _run_refresh(monkeypatch, outcomes):
    """Drive `refresh` over a fixed target list with scripted per-symbol outcomes."""
    saved = {}
    targets = [("asx", sym) for sym in outcomes]
    monkeypatch.setattr(sectorcache, "_scan_symbols", lambda: [])
    monkeypatch.setattr(sectorcache, "_targets", lambda syms, cache, cap: targets)
    monkeypatch.setattr(sectorcache, "load_cache", lambda: {})
    monkeypatch.setattr(sectorcache, "save_cache", lambda c: saved.update(c))
    monkeypatch.setattr(sectorcache, "_PACE_S", 0)
    monkeypatch.setattr(sectorcache, "_fetch_sector",
                        lambda yf_sym: outcomes[yf_sym.split(".")[0]])
    return sectorcache.refresh(), saved


def test_refresh_caches_only_what_it_actually_learned(monkeypatch, capsys):
    cache, saved = _run_refresh(monkeypatch, {
        "AAA": ("Financials", "ok"),
        "BBB": ("", "none"),
        "CCC": ("", "failed"),
    })
    assert set(cache) == {sectorcache._key("asx", "AAA")}
    assert saved == cache, "the learned sector is persisted"
    out = capsys.readouterr().out
    assert "got 1 / none 1 / failed 1 of 3" in out
    assert "cache now holds 1 symbols" in out


def test_the_warning_fires_on_a_failure_and_names_the_consequence(monkeypatch, capsys):
    _run_refresh(monkeypatch, {"AAA": ("", "failed")})
    out = capsys.readouterr().out
    assert "WARNING 1 profile fetch(es) FAILED" in out
    # the sentence that makes it actionable: this is a CORRELATION-CAP problem
    assert "exempt from the per-sector cap" in out


def test_a_run_where_every_name_is_genuinely_sectorless_is_not_a_warning(monkeypatch, capsys):
    """The distinction the single `got X/N` line could not draw."""
    _run_refresh(monkeypatch, {"AAA": ("", "none"), "BBB": ("", "none")})
    out = capsys.readouterr().out
    assert "got 0 / none 2 / failed 0 of 2" in out
    assert "WARNING" not in out


def test_the_counts_print_on_a_fully_clean_run(monkeypatch, capsys):
    _run_refresh(monkeypatch, {"AAA": ("Energy", "ok")})
    out = capsys.readouterr().out
    assert "got 1 / none 0 / failed 0 of 1" in out
    assert "WARNING" not in out


def test_nothing_is_saved_when_nothing_was_learned(monkeypatch):
    cache, saved = _run_refresh(monkeypatch, {"AAA": ("", "none"),
                                              "BBB": ("", "failed")})
    assert cache == {}
    assert saved == {}, "save_cache must not be called on a no-op run"


def test_caching_behaviour_is_deliberately_unchanged():
    """#65 shipped its OBSERVABILITY half only, and that is the decision.

    Caching the 'none' verdict is inert today (`_targets` filters on a falsy
    sector, so a cached blank is still "missing") and the version that is NOT
    inert changes which names carry a sector -> which sectors the cap counts ->
    which trades get taken. Owner's call. If `_targets` ever stops filtering on
    truthiness this test should fail and the decision be re-taken deliberately.
    """
    syms = [(0, "asx", "AAA"), (1, "asx", "BBB")]
    blank = {sectorcache._key("asx", "AAA"): {"sector": "", "ts": "2026-07-28"}}
    # a cached blank is STILL "missing" — which is what makes caching one inert
    assert sectorcache._targets(syms, blank, 10) == [("asx", "AAA"), ("asx", "BBB")]
    real = {sectorcache._key("asx", "AAA"): {"sector": "Energy", "ts": "2026-07-28"}}
    assert sectorcache._targets(syms, real, 10) == [("asx", "BBB")]


# ══ #73 — supertrend, 25x faster and bit-identical ═══════════════════════════
#
# The whole claim of this item is a NEGATIVE one: nothing changed. A trailing
# stop line that is "almost" the same is worse than a slow one, so the only test
# that matters is a bit-for-bit comparison against a FROZEN copy of the loop
# that shipped before it — kept below deliberately, because comparing the new
# code against a re-derivation of itself would prove nothing.


def _supertrend_pre_73(df, period=14, mult=3.0):
    """The implementation as it stood before #73. Do not tidy this."""
    atr_ = indicators.atr(df, period)
    hl2 = (df["High"] + df["Low"]) / 2
    upper = hl2 + mult * atr_
    lower = hl2 - mult * atr_
    close = df["Close"]

    final_upper = upper.copy()
    final_lower = lower.copy()
    st = pd.Series(index=df.index, dtype="float64")
    going_up = True

    for i in range(len(df)):
        if i == 0:
            st.iat[i] = lower.iat[i]
            continue
        final_upper.iat[i] = (
            upper.iat[i]
            if (upper.iat[i] < final_upper.iat[i - 1]
                or close.iat[i - 1] > final_upper.iat[i - 1])
            else final_upper.iat[i - 1]
        )
        final_lower.iat[i] = (
            lower.iat[i]
            if (lower.iat[i] > final_lower.iat[i - 1]
                or close.iat[i - 1] < final_lower.iat[i - 1])
            else final_lower.iat[i - 1]
        )
        if going_up and close.iat[i] < final_lower.iat[i]:
            going_up = False
        elif not going_up and close.iat[i] > final_upper.iat[i]:
            going_up = True
        st.iat[i] = final_lower.iat[i] if going_up else final_upper.iat[i]

    return st


def _same_series(a, b):
    """Bit-identical, not close: same values, same NaN placement, same index."""
    return (a.index.equals(b.index)
            and str(a.dtype) == str(b.dtype)
            and np.array_equal(a.to_numpy(), b.to_numpy(), equal_nan=True))


@pytest.mark.parametrize("n", [0, 1, 2, 3, 5, 14, 15, 50, 300, 1300])
def test_bit_identical_at_every_length_including_the_degenerate_ones(n):
    """Lengths 0-3 are where an off-by-one in the loop's seeding would hide.

    The old loop seeded bar 0 from `lower` and started the recurrence at bar 1;
    an n of 0 or 1 never enters the recurrence at all, so those are the two
    cases a rewrite is most likely to get wrong and least likely to notice.
    """
    df = _walk(n, seed=2, drift=0.05)
    assert _same_series(_supertrend_pre_73(df), indicators.supertrend(df))


def _chop(n=600, seed=1, drift=0.0, vol=1.0):
    """A tape volatile enough that the direction latch really does flip both ways."""
    rs = np.random.RandomState(seed)
    return _ohlc(100.0 + np.cumsum(rs.normal(drift, vol, n)))


@pytest.mark.parametrize("seed,drift", [(1, 0.0), (2, 0.4), (3, -0.4), (4, 0.0)])
def test_bit_identical_across_trending_and_chopping_tapes(seed, drift):
    df = _chop(600, seed=seed, drift=drift)
    assert _same_series(_supertrend_pre_73(df), indicators.supertrend(df))


@pytest.mark.parametrize("seed", [1, 4])
def test_both_latch_directions_are_actually_exercised(seed):
    """Otherwise the tests above only ever prove one branch of the rewrite.

    `going_up` publishes the LOWER band (trail below price) and `not going_up`
    the UPPER one (trail above), so "the latch flipped" is observable as the
    line crossing the close — and both sides must appear, on the same tape, for
    the equivalence claim to cover the whole state machine.
    """
    df = _chop(600, seed=seed)
    st, close = indicators.supertrend(df), df["Close"]
    assert (st < close).any(), "never trailed below price — uptrend branch unused"
    assert (st > close).any(), "never trailed above price — downtrend branch unused"
    assert _same_series(_supertrend_pre_73(df), st)


def test_bit_identical_on_a_halted_frame():
    """A suspended name: still ranging intrabar, but going nowhere."""
    df = _flat(200)
    assert _same_series(_supertrend_pre_73(df), indicators.supertrend(df))


def test_a_fully_frozen_frame_puts_the_trail_exactly_on_the_close():
    """The degenerate input, and it is a real one — a halted ASX name.

    High == Low == Close makes ATR exactly 0, so both bands collapse ONTO the
    close and every comparison in the recurrence is an exact float equality.
    That is the only input on which `<` vs `<=` is even distinguishable, which
    is worth knowing: on any real tape those two boundaries are equality-inert
    (at equality both branches assign the same value), so a mutation there
    changes nothing and no test can or should claim to catch it. What IS worth
    pinning is that the collapsed case does not divide, drift or go NaN.
    """
    n, price = 120, 7.5
    df = pd.DataFrame(
        {"Open": price, "High": price, "Low": price, "Close": price, "Volume": 1e6},
        index=pd.date_range("2022-01-01", periods=n, freq="D"))
    st = indicators.supertrend(df)
    assert _same_series(_supertrend_pre_73(df), st)
    assert (st == df["Close"]).all()
    assert float(indicators.atr(df, 14).iloc[-1]) == 0.0


def test_a_nan_band_carries_the_trail_forward_rather_than_reversing_it():
    """NaN fails every comparison in BOTH versions, so the latch cannot flip on it.

    This is the one place a numpy rewrite could plausibly diverge from pandas —
    it does not, and the reason it does not is that both are IEEE comparisons
    that are False against NaN. Worth a named test because the failure mode is a
    trailing stop silently reversing on a bad bar.
    """
    df = _walk(200, seed=9)
    df.loc[df.index[50:55], ["High", "Low", "Close"]] = np.nan
    old, new = _supertrend_pre_73(df), indicators.supertrend(df)
    assert _same_series(old, new)
    # the observable consequence, stated: the trail HOLDS across the gap. It does
    # not go NaN (a NaN trail would compare False against every price and quietly
    # stop stopping anything) and it does not jump (no flip, no band reset).
    window = new.iloc[49:56].to_numpy()
    assert np.isfinite(window).all()
    assert len(set(window.tolist())) == 1, "the trail must be flat across the gap"


def test_bit_identical_when_the_frame_carries_integer_prices():
    """`.iat` handed the old loop numpy ints; the rewrite casts to float64 up front."""
    df = _walk(120, seed=11, start=400.0).round(0).astype({"Close": "int64"})
    assert _same_series(_supertrend_pre_73(df), indicators.supertrend(df))


def test_the_production_call_sites_still_get_a_series_indexed_like_the_frame():
    """Both callers index off it — `.iloc[-1]` and `.to_numpy()` — so shape matters."""
    df = _walk(340)
    st = indicators.supertrend(df, config.ATR_PERIOD, config.SUPERTREND_MULT)
    assert isinstance(st, pd.Series)
    assert st.index.equals(df.index)
    assert str(st.dtype) == "float64"
    assert float(st.iloc[-1]) == float(_supertrend_pre_73(
        df, config.ATR_PERIOD, config.SUPERTREND_MULT).iloc[-1])


def test_the_recurrence_was_kept_and_only_the_pandas_lookups_were_dropped():
    """#73 said "vectorisable". It is not, and the docstring must keep saying so.

    Each final band is a running min/max whose reset condition reads the running
    value itself, and the direction latch reads both finished bands — so bar i
    genuinely needs bar i-1. A future "proper vectorisation" that changes the
    output is a trading change, not a refactor; this test makes the reasoning
    findable from the code rather than only from TOP100.md.
    """
    src = (REPO / "scanner" / "indicators.py").read_text(encoding="utf-8")
    body = src.split("def supertrend(")[1].split("\ndef ")[0]
    assert "BIT-IDENTICAL" in body
    assert "cannot be" in body
    assert ".iat[" not in body, "the pandas element access is the thing that went"
