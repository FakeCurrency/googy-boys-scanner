"""MOMENTUM screen -- three layers of proof, deliberately in this order.

The maths here was PORTED from `tradingview/scanner-spec/reference/
vivek50_screen.py`, and a port of trading maths is exactly where a silent
transcription error lives. So correctness is not asserted from a reading of the
code; it is measured three ways:

  LAYER 1  SELF-CONTAINED behaviour. Runs with no reference present, and pins
           the properties the build brief names explicitly: strict pivots on a
           tie, the 5-bar lag, refusal of a reverse-chronological frame, the
           <200-bar score cap, and the measured Pine-vs-pandas EMA drift.
  LAYER 2  DIFFERENTIAL equivalence. The port and the reference are run over
           the same deterministic corpus and every field of every row must be
           bit-identical.
  LAYER 3  THE BORROWED 28. The reference's own assertions, executed verbatim
           against THIS package via a shim, so they cannot drift from it. If
           the spec pack is ever updated, these follow automatically.

WHY ALL THREE, AND THE BUG THAT PROVED IT. The differential passed
bit-identically while the port still had SIX latent `NameError`s -- the ported
`cfg = (cfg or DEFAULT_CONFIG)` fallbacks, where my namespace rewrite had
required a trailing dot. The differential could never see them because it always
passes `cfg` explicitly, so that branch never evaluated. Layer 3 caught all six
on its first run. A single layer here would have shipped them.

Layers 2 and 3 SKIP -- visibly, with a reason -- when the reference is absent,
rather than passing vacuously. Layer 1 then still pins real behaviour.
"""

from __future__ import annotations

import dataclasses
import pathlib
import sys
import types

import numpy as np
import pandas as pd
import pytest

from scanner.momentum import ema as E
from scanner.momentum import macd as M
from scanner.momentum import pivots as P
from scanner.momentum import screen as S
from scanner.momentum.config import MomentumConfig

ROOT = pathlib.Path(__file__).resolve().parents[1]
REF_DIR = ROOT / "tradingview" / "scanner-spec" / "reference"
REF_MISSING = "the spec pack is not in the tree, so equivalence with the " \
              "reference implementation is UNPROVEN in this run"


# ---------------------------------------------------------------------------
# frames
# ---------------------------------------------------------------------------

def frame(close, *, vol=None, start="2020-01-01", spread=0.004):
    """OHLCV from a close path. Title-case columns on purpose: that is what
    `scanner/data.py` hands back, and `prepare_frame` is what lowercases them."""
    c = np.asarray(close, dtype=float)
    prev = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame(
        {"Open": prev,
         "High": np.maximum(c, prev) * (1.0 + spread),
         "Low": np.minimum(c, prev) * (1.0 - spread),
         "Close": c,
         "Volume": (vol if vol is not None else np.full(c.size, 1e6))},
        index=pd.bdate_range(start, periods=c.size, name="date"))


def corpus():
    """A deterministic set covering ramps, walks, and every degenerate shape
    the spec's adversarial pass called out. Seeded, so a failure reproduces."""
    out = {}
    for n in (60, 61, 199, 200, 260, 400, 800):
        out[f"ramp{n}"] = frame(np.linspace(10, 100, n))
        out[f"fall{n}"] = frame(np.linspace(100, 10, n))
    for s in range(8):
        r = np.random.default_rng(s)
        out[f"walk{s}"] = frame(100 * np.exp(np.cumsum(r.normal(0, 0.025, 700))))
        # tick-ROUNDED, because ties only occur on a rounded tape and ties are
        # the whole subject of the strict-pivot rule
        out[f"tick{s}"] = frame(np.round(100 * np.exp(np.cumsum(r.normal(0, 0.025, 700))), 2))
    out["flat300"] = frame(np.full(300, 42.0))
    c = np.linspace(10, 50, 400); c[150:170] = c[149]
    out["flatpatch"] = frame(c)
    rng = np.random.default_rng(99)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 500))); c[200:205] = np.nan
    out["nanholes"] = frame(c)
    c = np.linspace(10, 60, 400); c[380:] = c[379]
    out["halted"] = frame(c, vol=np.concatenate([np.full(380, 1e6), np.zeros(20)]))
    out["spike"] = frame(np.array([10.0] * 50 + [80.0] + [10.0] * 50))
    out["intramp"] = frame(np.arange(1, 501, dtype=float))
    return out


CORPUS = corpus()


# ===========================================================================
# LAYER 1 -- self-contained
# ===========================================================================

def test_a_reverse_chronological_frame_is_REFUSED_not_silently_screened():
    """The worst of the four defects the spec's adversarial pass found.

    A descending frame used to be screened without complaint and returned a
    complete, plausible, WRONG answer -- the RSI read backwards. It is REFUSED,
    not auto-sorted: sorting would launder the caller's mistake, and the next
    caller handing over a genuinely corrupt frame would get silence instead of
    an error. (Our own loader sorts what IT controls; that is a different job.)
    """
    f = CORPUS["walk0"]
    rev = f.iloc[::-1]
    with pytest.raises(ValueError, match="DESCENDING|descending"):
        S.prepare_frame(rev)
    row = S.screen_symbol(rev, symbol="REV")
    assert row["ok"] is False and row["reason"], "a refusal must carry a reason"
    assert row["passes"] is False, "a refused frame must never pass the screen"


def test_equal_consecutive_lows_make_no_pivot_under_the_strict_rule():
    """A flat stretch must yield ZERO pivots.

    `series == series.rolling(w, center=True).min()` makes every bar of a
    constant window simultaneously a max and a min, so you get a pivot on every
    bar and a cascade of nonsense divergences behind it. Halted small caps,
    delisted-but-quoted names and stablecoins all produce exactly that shape.
    """
    s = pd.Series([5.0, 4.0, 3.0, 2.0, 1.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    strict = P.pivot_low_confirmed(s, 3, 3, strict_left=True, strict_right=True)
    assert strict.notna().sum() == 0, "a tie must disqualify the pivot"
    loose = P.pivot_low_confirmed(s, 3, 3, strict_left=False, strict_right=False)
    assert loose.notna().sum() > 0, (
        "the non-strict convention must differ, or the flag is decorative and "
        "the 0.8% measured disagreement could not exist")


def test_a_perfectly_flat_series_produces_nothing_and_does_not_crash():
    row = S.screen_symbol(CORPUS["flat300"], symbol="FLAT")
    assert row["rule_a"] is False and row["rule_b"] is False
    assert row["passes"] is False
    rsi = E.rsi_wilder(pd.Series(np.full(300, 42.0)), 14)
    assert rsi.dropna().empty, (
        "RSI is UNDEFINED on a halted series (0/0), not 100 -- a name that has "
        "not moved a tick must not read as maximally overbought")


def test_the_five_bar_lag_is_reported_as_two_separate_numbers():
    """Rule A is knowable `piv_right` bars AFTER the pivot, and the chart label
    sits at the pivot. Both must ship, because the owner opening TradingView
    sees the label at one bar and the scanner naming another."""
    cfg = MomentumConfig(mode="B", div_fresh_bars=60, signal_fresh_bars=60)
    fired = 0
    for sym, f in CORPUS.items():
        row = S.screen_symbol(f, cfg, symbol=sym)
        if not row.get("rule_a"):
            continue
        fired += 1
        assert row["rule_a_pivot_bars_ago"] == row["rule_a_bars_ago"] + cfg.piv_right
        assert row["rule_a_label_bars_ago"] == row["rule_a_pivot_bars_ago"], (
            "the drawn label sits at the pivot bar")
        assert row["rule_a_bars_ago"] >= 0
    assert fired >= 3, f"only {fired} rule-A hits in the corpus - the property is near-vacuous"


def test_a_frame_shorter_than_the_slow_ma_caps_the_score_at_two():
    """A 200-EMA that does not exist cannot award its point, so the score is
    capped at 2 -- and that is PUBLISHED as `slow_ready`, not hidden, because a
    capped score must not read as a weak signal."""
    row = S.screen_symbol(frame(np.linspace(10, 40, 120)), MomentumConfig(mode="B"), symbol="SHORT")
    assert row["ok"] is True, "a short frame is screenable, just not fully"
    assert row["slow_ready"] is False
    assert row["above_slow"] is None, "unknown is not False"
    ev = S.evaluate(frame(np.linspace(10, 40, 120)), MomentumConfig(mode="B"))
    assert ev["slow"].isna().all(), "there is no 200 MA to compare against"
    assert int(ev["bull_score"].max()) <= 2


def test_a_frame_below_min_bars_is_refused_with_a_reason_not_an_exception():
    row = S.screen_symbol(frame(np.linspace(10, 20, 30)), symbol="TINY")
    assert row["ok"] is False and row["reason"]
    assert row["passes"] is False


def test_pine_seeding_and_pandas_ewm_disagree_on_the_200_AND_ONLY_THE_200():
    """The measured fixture, reproducing the spec's own numbers.

    Pine seeds with the SMA of the first `length` values and emits na before
    that; `ewm(adjust=False)` seeds on the first value and emits from bar 0. The
    seed error decays as (1-alpha)^n, so it survives in inverse proportion to
    alpha. 0.247 price units on the 200 is enough to flip `close > slow`, which
    is one of Rule B's two live scoring terms -- so the same name scores 3 here
    and 2 on the owner's chart.
    """
    ramp = pd.Series(np.arange(1000, dtype=float))
    ewm = ramp.ewm(span=200, adjust=False).mean()

    assert np.allclose(E.ema_pine(ramp, 200, seed="first").to_numpy(),
                       ewm.to_numpy(), equal_nan=True), (
        'seed="first" must reproduce pandas exactly, or the comparison this '
        "test makes is against something nobody actually uses")

    pine = E.ema_pine(ramp, 200, seed="sma")
    assert _warm(pine) == 199, "Pine emits na through warm-up"
    assert _warm(ewm) == 0, "pandas emits from bar 0"
    assert abs(pine.iloc[600] - ewm.iloc[600]) == pytest.approx(0.247, abs=0.002)
    assert abs(pine.iloc[999] - ewm.iloc[999]) == pytest.approx(0.0046, abs=0.0005)

    for span in (20, 50):
        p = E.ema_pine(ramp, span, seed="sma")
        e = ramp.ewm(span=span, adjust=False).mean()
        assert abs(p.iloc[600] - e.iloc[600]) < 1e-9, (
            f"EMA{span} must have forgotten its seed by bar 600 - that is why "
            "only the 200 is worth carrying a custom implementation for")


def _warm(series) -> int:
    """POSITION of the first non-NaN bar.

    Positional, not `first_valid_index()`: on a frame-derived series that
    returns a Timestamp, so a test written against the bare-Series case passes
    on some indicators and TypeErrors on others.
    """
    v = np.asarray(series, dtype=float)
    idx = np.flatnonzero(~np.isnan(v))
    return int(idx[0]) if idx.size else -1


def test_the_warm_up_fingerprints_match_pine():
    """First-valid bar per indicator. A drift here means the seeding moved."""
    c = pd.Series(100 + np.arange(400, dtype=float))
    # through prepare_frame, because the indicators take LOWERCASE columns and
    # that normalisation is the screen's front door, not the caller's job
    df = S.prepare_frame(frame(100 + np.arange(400, dtype=float)))
    assert _warm(E.rsi_wilder(c, 14)) == 14
    assert _warm(E.ema_pine(c, 20)) == 19
    assert _warm(E.ema_pine(c, 50)) == 49
    assert _warm(E.ema_pine(c, 200)) == 199
    assert _warm(M.macd_pine(c, 12, 26, 9)[2]) == 33, (
        "the signal line is an EMA OF THE MACD LINE, so 26 warm-up bars plus 9")
    assert _warm(E.atr_wilder(df, 14)) == 13


def test_rule_b_reads_the_macd_sign_only_and_zero_scores_neither_side():
    cfg = MomentumConfig(mode="B")
    for f in (CORPUS["walk1"], CORPUS["tick2"]):
        ev = S.cross_signal(S.prepare_frame(f), cfg)
        h = ev["macd_hist"].to_numpy()
        zero = np.isclose(h, 0.0) & ~np.isnan(h)
        if zero.any():
            assert not ev["macd_agrees_bull"].to_numpy()[zero].any()
            assert not ev["macd_agrees_bear"].to_numpy()[zero].any()
        both = ev["macd_agrees_bull"].to_numpy() & ev["macd_agrees_bear"].to_numpy()
        assert not both.any(), "a histogram cannot agree with both directions"


def test_the_score_is_one_plus_the_terms_and_maxes_at_three():
    cfg = MomentumConfig(mode="B")
    assert cfg.max_score == 3, "1 + macd + beyond-slow, with use_rsi OFF"
    assert MomentumConfig(use_rsi=True).max_score == 4
    ev = S.cross_signal(S.prepare_frame(CORPUS["walk0"]), cfg)
    sc = ev["bull_score"].to_numpy()
    assert sc.min() >= 1 and sc.max() <= cfg.max_score
    rebuilt = (1 + ev["macd_agrees_bull"].astype(int)
               + ev["above_slow"].fillna(False).astype(int)).to_numpy()
    assert (sc == rebuilt).all(), "the score is arithmetic, not a lookup table"


def test_freshness_of_N_admits_bars_ago_zero_to_N_minus_one():
    """`within=1` means the FINAL BAR ONLY. `bars_ago == N` is OUTSIDE a window
    of N. Off by one here silently widens or empties the whole screen."""
    mask = np.zeros(10, dtype=bool)
    mask[7] = True                       # bars_ago == 2 on a 10-bar frame
    assert S._last_true(mask, 1) is None
    assert S._last_true(mask, 2) is None
    assert S._last_true(mask, 3) == 7
    assert S._last_true(mask, 9) == 7


def test_mode_A_is_divergence_only_and_never_passes_on_rule_b():
    """The v1 default. Rule B is still COMPUTED and published as evidence --
    the brief requires that -- it simply cannot make a row pass."""
    a = MomentumConfig(mode="A", signal_fresh_bars=60, div_fresh_bars=60)
    b = a.replace(mode="B")
    saw_b_only = 0
    for sym, f in CORPUS.items():
        ra, rb = S.screen_symbol(f, a, symbol=sym), S.screen_symbol(f, b, symbol=sym)
        assert ra["rule_b"] == rb["rule_b"], "Rule B is computed in mode A too"
        assert ra["passes"] == bool(ra["rule_a"])
        if rb["rule_b"] and not rb["rule_a"]:
            saw_b_only += 1
            assert ra["passes"] is False, "mode A must not pass on Rule B alone"
    assert saw_b_only >= 1, "no B-only row in the corpus - the property is vacuous"


def test_a_conflict_is_flagged_and_never_collapsed_to_one_direction():
    cfg = MomentumConfig(mode="B", div_fresh_bars=60, signal_fresh_bars=60)
    for sym, f in CORPUS.items():
        row = S.screen_symbol(f, cfg, symbol=sym)
        dirs = {row["rule_a_direction"], row["rule_b_direction"]} - {""}
        if dirs == {"bull", "bear"} or "both" in dirs:
            assert row["direction"] == "conflict", (
                "surfacing the disagreement is the point of a review shortlist")


def test_the_engine_is_deterministic_on_repeated_calls():
    cfg = MomentumConfig(mode="B")
    for sym in ("walk3", "tick4", "flatpatch", "halted"):
        a = S.screen_symbol(CORPUS[sym], cfg, symbol=sym)
        b = S.screen_symbol(CORPUS[sym], cfg, symbol=sym)
        assert a.keys() == b.keys()
        for k in a:
            assert a[k] == b[k] or (isinstance(a[k], float) and np.isnan(a[k])
                                    and np.isnan(b[k])), k


def test_no_look_ahead_on_the_real_corpus():
    """Truncate at every bar, re-derive, require bar i's value to be unchanged
    by bars that had not happened yet. Ported from the reference's own proof and
    run here over OUR corpus as well."""
    cfg = MomentumConfig(mode="B")
    for sym in ("walk0", "tick1", "flatpatch", "spike"):
        S.assert_no_lookahead(CORPUS[sym], cfg)


def test_screen_frames_takes_the_downloader_return_type_unchanged():
    """`data.download()` hands back {ticker: DataFrame} with TITLE-case columns.
    It must feed straight in -- if this needed a rename, the loader would be
    carrying knowledge that belongs at the screen's front door."""
    out = S.screen_frames({k: CORPUS[k] for k in ("walk0", "ramp400", "flat300")},
                          MomentumConfig(mode="B"), market="test")
    assert isinstance(out, pd.DataFrame)
    assert {"symbol", "passes", "rule_a", "rule_b"} <= set(out.columns)


def test_the_unsatisfiable_rule_b_config_is_refused_by_assert_screenable():
    """Switch off every optional term and `min_signal_score=2` can never be
    reached, so Rule B would silently find nothing for ever. Deliberately NOT
    in `validate()` -- see that method's docstring."""
    bad = MomentumConfig(use_macd=False, use_slow=False)
    bad.validate()                       # structurally fine
    with pytest.raises(ValueError, match="can never be reached"):
        bad.assert_screenable()
    MomentumConfig().assert_screenable()


# ===========================================================================
# LAYER 2 + 3 -- the reference
# ===========================================================================

def _install_shim():
    """Expose THIS package under the reference module's name.

    The reference's own test-suite does `import vivek50_screen as V` and then
    calls `V.<fn>`, so pointing that name at this package runs its assertions
    against this code with no transcription at all.

    Three adaptations, each needed and each a fact about the reference:
      * `mode` is an int there and a letter here, so the config factory maps it.
      * The reference's DEFAULT is the UNION (its mode 2); ours ships mode A.
        Tests that omit `cfg` mean "the reference's default", so the wrapper
        substitutes that rather than our product default -- otherwise a test of
        Rule B detection would fail on our choice of screen rather than on the
        maths.
      * Attribute WRITES are forwarded to the owning module, because one test
        monkeypatches an internal (`V._pivot`) to plant a look-ahead and require
        the proof to catch it. Patching a facade would leave the real caller
        untouched and the proof would "pass" having tested nothing.
    """
    if not (REF_DIR / "vivek50_screen.py").exists():
        pytest.skip(REF_MISSING)
    if str(REF_DIR) not in sys.path:
        sys.path.insert(0, str(REF_DIR))

    letter = {1: "A", 2: "B"}

    class RefCfg(MomentumConfig):
        def replace(self, **kw):
            if isinstance(kw.get("mode"), int):
                kw["mode"] = letter[kw["mode"]]
            # validates, exactly as the reference's replace() does -- one test
            # requires a mistyped source to raise HERE while the plain
            # constructor stays lenient so screen_symbol can report it as a row
            # reason instead of throwing.
            return dataclasses.replace(self, **kw).validate()

    def make(**kw):
        if isinstance(kw.get("mode"), int):
            kw["mode"] = letter[kw["mode"]]
        return RefCfg(**kw)

    ref_default = RefCfg(mode="B").validate()

    def wrap(fn):
        def inner(*a, **k):
            if len(a) >= 2 and a[1] is None:
                a = (a[0], ref_default) + a[2:]
            elif len(a) < 2 and k.get("cfg") is None:
                k["cfg"] = ref_default
            return fn(*a, **k)
        return inner

    owner: dict = {}

    class ShimModule(types.ModuleType):
        def __setattr__(self, name, value):
            if owner.get(name) is not None:
                setattr(owner[name], name, value)
            types.ModuleType.__setattr__(self, name, value)

    shim = ShimModule("vivek50_screen")
    plain = {
        E: ("wilder_rma", "rsi_wilder", "ema_pine", "sma_pine", "ma_pine",
            "true_range", "atr_wilder"),
        M: ("macd_pine",),
        P: ("crossover", "crossunder", "cross", "pivot_low_confirmed",
            "pivot_high_confirmed", "valuewhen", "barssince", "shift_bool", "_pivot"),
        S: ("prepare_frame",),
    }
    for mod, names in plain.items():
        for n in names:
            owner[n] = mod
            types.ModuleType.__setattr__(shim, n, getattr(mod, n))
    for n in ("rsi_divergence", "cross_signal", "evaluate", "screen_symbol",
              "screen_frames", "assert_no_lookahead"):
        owner[n] = S
        types.ModuleType.__setattr__(shim, n, wrap(getattr(S, n)))
    for n, v in (("ScreenConfig", make), ("DEFAULT_CONFIG", ref_default),
                 ("OHLC_COLUMNS", S.OHLC_COLUMNS),
                 ("CAUSAL_COLUMNS", S.CAUSAL_COLUMNS)):
        types.ModuleType.__setattr__(shim, n, v)
    sys.modules["vivek50_screen"] = shim
    return shim


def _reference():
    """The real reference module, imported under a private name so it and the
    shim can coexist in one pytest process."""
    if not (REF_DIR / "vivek50_screen.py").exists():
        pytest.skip(REF_MISSING)
    if str(REF_DIR) not in sys.path:
        sys.path.insert(0, str(REF_DIR))
    name = "_momentum_reference"
    if name in sys.modules:
        return sys.modules[name]
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, REF_DIR / "vivek50_screen.py")
    mod = importlib.util.module_from_spec(spec)
    # REGISTERED BEFORE exec_module, and it has to be: `dataclasses` resolves a
    # string annotation by looking up `sys.modules[cls.__module__]`, so building
    # ScreenConfig inside an unregistered module dies with an AttributeError on
    # None. Loading it under a private name lets the real reference and the shim
    # (which owns the name "vivek50_screen") coexist in one pytest process.
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        del sys.modules[name]
        raise
    return mod


def _same(a, b):
    if isinstance(a, float) and isinstance(b, float):
        return (a == b) or (np.isnan(a) and np.isnan(b))
    return a == b


@pytest.mark.parametrize("letter,num", [("A", 1), ("B", 2)])
def test_the_port_is_BIT_IDENTICAL_to_the_reference(letter, num):
    """LAYER 2. Every field of every row, both modes, wide windows so the 14
    CONDITIONAL evidence keys populate too -- a differential that only ever
    compares the 35 always-present keys is not comparing the evidence."""
    ref = _reference()
    rcfg = ref.ScreenConfig(mode=num, div_fresh_bars=60, signal_fresh_bars=60).validate()
    mcfg = MomentumConfig(mode=letter, div_fresh_bars=60, signal_fresh_bars=60).validate()
    keys, hits_a, hits_b, diffs = set(), 0, 0, []
    for sym, f in CORPUS.items():
        r = ref.screen_symbol(f, rcfg, symbol=sym, market="t")
        m = S.screen_symbol(f, mcfg, symbol=sym, market="t")
        if set(r) != set(m):
            diffs.append(f"{sym}: keys differ {sorted(set(r) ^ set(m))}")
            continue
        keys |= set(r)
        hits_a += bool(r.get("rule_a"))
        hits_b += bool(r.get("rule_b"))
        diffs += [f"{sym}.{k}: ref={r[k]!r} port={m[k]!r}" for k in r if not _same(r[k], m[k])]
    assert diffs == [], "\n  ".join(diffs[:20])
    assert len(keys) >= 49, (
        f"only {len(keys)} keys compared - the conditional evidence keys did "
        "not populate, so the differential proved less than it looks")
    assert hits_a >= 3 and hits_b >= 3, (
        f"rule_a fired {hits_a}, rule_b {hits_b} - too few to call this a "
        "comparison of the firing paths")


def test_the_indicators_are_bit_identical_to_the_reference():
    """LAYER 2, one level down: a row-level match could in principle hide two
    compensating indicator errors."""
    ref = _reference()
    for sym in ("walk0", "tick3", "ramp800", "flatpatch", "nanholes", "halted"):
        f = S.prepare_frame(CORPUS[sym])
        c = f["close"]
        pairs = [
            (E.rsi_wilder(c, 14), ref.rsi_wilder(c, 14)),
            (E.ema_pine(c, 200), ref.ema_pine(c, 200)),
            (E.sma_pine(c, 50), ref.sma_pine(c, 50)),
            (E.wilder_rma(c, 14), ref.wilder_rma(c, 14)),
            (E.atr_wilder(f, 14), ref.atr_wilder(f, 14)),
        ]
        pairs += list(zip(M.macd_pine(c, 12, 26, 9), ref.macd_pine(c, 12, 26, 9)))
        for mine, theirs in pairs:
            assert np.array_equal(mine.to_numpy(), theirs.to_numpy(), equal_nan=True), sym


def _borrowed():
    if not (REF_DIR / "vivek50_selftest.py").exists():
        pytest.skip(REF_MISSING)
    _install_shim()
    import importlib
    if "vivek50_selftest" in sys.modules:
        del sys.modules["vivek50_selftest"]
    return importlib.import_module("vivek50_selftest")


def _borrowed_names():
    """Collected at import time so each of the 28 is its own pytest case."""
    try:
        if not (REF_DIR / "vivek50_selftest.py").exists():
            return []
        src = (REF_DIR / "vivek50_selftest.py").read_text(encoding="utf-8")
        import re
        return re.findall(r"^def (test_\w+)\(", src, re.M)
    except OSError:
        return []


BORROWED = _borrowed_names()


def test_all_twenty_eight_reference_assertions_are_collected():
    """If the reference's suite grows or shrinks, notice rather than silently
    running fewer. 28 is the number its own commit message claims."""
    if not BORROWED:
        pytest.skip(REF_MISSING)
    assert len(BORROWED) == 28, f"the reference now has {len(BORROWED)} tests, not 28"


@pytest.mark.parametrize("name", BORROWED or ["_none"])
def test_borrowed(name, capsys):
    """LAYER 3. The reference's own assertion, executed verbatim against this
    package. These are not copies -- they are the originals, so they cannot
    drift from the spec they came with."""
    if not BORROWED:
        pytest.skip(REF_MISSING)
    mod = _borrowed()
    getattr(mod, name)()
    capsys.readouterr()          # the reference prints its findings; keep -q quiet
