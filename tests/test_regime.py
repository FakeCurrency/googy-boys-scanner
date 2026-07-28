"""REGIME + RELATIVE STRENGTH — the other half of the July post-mortem.

`sectorbreadth` answers "which sector is setting up today and do I hold any".
This module answers the two questions that miss actually raised: was the market
as bad as the index said, and who was beating it. Every test below pins one
specific way that answer could come out wrong and be believed anyway — a
silently mis-joined price matrix, a denominator that counts names which cannot
be measured, an "Unclassified" bucket that is really the whole market wearing a
sector's name, a streak that keeps counting through a session it should break
on.

REPORT-ONLY, and these tests assume it: they check what is published, never
what is taken. If a change here starts reaching `decide()`, that is a trade
change and needs the owner, not a green run.
"""

import json

import numpy as np
import pandas as pd
import pytest

from scanner import config
from scanner import regime

pytestmark = pytest.mark.risk


# ── builders ─────────────────────────────────────────────────────────────────

def _days(n=520, start="2024-01-01"):
    return pd.bdate_range(start, periods=n)


def _frame(closes, index=None, tz=None):
    """An OHLCV frame from a close series. `tz` makes the index tz-aware."""
    idx = pd.DatetimeIndex(index if index is not None else _days(len(closes)))
    if tz:
        idx = idx.tz_localize(tz)
    px = np.asarray(closes, dtype="float64")
    return pd.DataFrame({"Open": px, "High": px * 1.01, "Low": px * 0.99,
                         "Close": px, "Volume": np.full(len(px), 1e6)}, index=idx)


def _drift(n, rate, seed, vol=0.012, start=10.0):
    rng = np.random.default_rng(seed)
    return start * np.exp(np.cumsum(rng.normal(rate, vol, n)))


def _market(sectors, n_days=520, seed=0):
    """(frames, universe) for {sector: (count, daily_drift)}."""
    frames, uni, idx, k = {}, [], _days(n_days), 0
    for sector, (count, rate) in sectors.items():
        for i in range(count):
            yft = f"S{k:04d}.AX"
            frames[yft] = _frame(_drift(n_days, rate, seed + k), idx)
            uni.append({"symbol": f"S{k:04d}", "yf": yft, "sector": sector})
            k += 1
    return frames, uni


# ── the price matrix: the join that fails without erroring ───────────────────

def test_mixed_timezone_indexes_align_into_one_row_per_session():
    """Yahoo hands back tz-aware indexes for some tickers and naive ones for
    others IN THE SAME BATCH. pandas does not raise on that — it stacks them,
    producing a matrix twice as tall with every row half empty, which reads
    downstream as "half the market had no data" every single day. The
    normalise-before-join is the only thing standing between that and a
    published breadth series that is quietly halved."""
    idx = _days(300)
    frames = {"A.AX": _frame(_drift(300, 0.001, 1), idx),
              "B.AX": _frame(_drift(300, 0.001, 2), idx, tz="UTC"),
              "C.AX": _frame(_drift(300, 0.001, 3), idx, tz="Australia/Sydney")}
    uni = [{"symbol": t[:1], "yf": t, "sector": "Materials"} for t in frames]

    closes, _ = regime.close_matrix(frames, uni)

    assert list(closes.columns) == ["A.AX", "B.AX", "C.AX"]
    assert len(closes) == 300                     # not 900, not 600
    assert closes.notna().all().all()             # every cell filled on every row
    assert closes.index.tz is None


def test_matrix_is_keyed_by_yf_ticker_so_duplicate_display_symbols_both_count():
    """Two universe rows can share a display symbol (dual listings, a stale
    row). Keying columns on `symbol` would collapse them into one column and
    undercount the market; `yf` is unique by construction."""
    idx = _days(120)
    frames = {"AAA.AX": _frame(_drift(120, 0.001, 4), idx),
              "AAA.NZ": _frame(_drift(120, 0.001, 5), idx)}
    uni = [{"symbol": "AAA", "yf": "AAA.AX", "sector": "Materials"},
           {"symbol": "AAA", "yf": "AAA.NZ", "sector": "Materials"}]

    closes, sector_of = regime.close_matrix(frames, uni)

    assert closes.shape[1] == 2
    assert set(sector_of) == {"AAA.AX", "AAA.NZ"}


def test_pseudo_sessions_are_dropped_not_published_as_market_wide_blanks():
    """One mis-dated bar creates a date on which exactly one name traded. Left
    in, it publishes as a session where the market vanished."""
    idx = _days(300)
    frames = {f"S{i}.AX": _frame(_drift(300, 0.001, 10 + i), idx) for i in range(20)}
    stray = _frame(_drift(301, 0.001, 99),
                   pd.DatetimeIndex(list(idx) + [idx[-1] + pd.Timedelta(days=1)]))
    frames["S0.AX"] = stray
    uni = [{"symbol": t[:-3], "yf": t, "sector": "Materials"} for t in frames]

    kept = regime._trading_days(regime.close_matrix(frames, uni)[0])

    assert len(kept) == 300


def test_empty_frames_return_an_empty_matrix_rather_than_raising():
    closes, sector_of = regime.close_matrix({}, [{"symbol": "X", "yf": "X.AX"}])
    assert closes.empty and sector_of == {}


# ── breadth: the denominator ─────────────────────────────────────────────────

def test_above200_excludes_names_that_have_no_200_day_average():
    """A name listed six weeks ago has no 200-day average and is neither above
    nor below it. Counting it in the DENOMINATOR alone drags participation down
    by the size of the IPO tail — a market where every established name is in an
    uptrend would print 60% purely because 40% of the register is new."""
    idx = _days(400)
    frames, uni = {}, []
    for i in range(10):                                   # long history, all rising
        yft = f"OLD{i}.AX"
        frames[yft] = _frame(_drift(400, 0.002, 200 + i), idx)
        uni.append({"symbol": f"OLD{i}", "yf": yft, "sector": "Materials"})
    for i in range(10):                                   # 30 sessions of history
        yft = f"NEW{i}.AX"
        frames[yft] = _frame(_drift(30, 0.002, 300 + i), idx[-30:])
        uni.append({"symbol": f"NEW{i}", "yf": yft, "sector": "Materials"})

    blk = regime.compute("asx", frames, uni, bench=None, days=10)

    assert blk["latest"]["above200"] == 1.0               # 10/10, not 10/20
    assert blk["latest"]["n"] == 20                       # but all 20 have prices


def test_a_market_with_too_little_history_publishes_the_full_shape_not_a_stub():
    """A new market's first week has fewer than 200 bars. The page must render
    "not enough history yet", which it cannot do if the block is missing the
    keys it reads."""
    idx = _days(50)
    frames = {f"S{i}.AX": _frame(_drift(50, 0.001, 400 + i), idx) for i in range(20)}
    uni = [{"symbol": t[:-3], "yf": t, "sector": "Materials"} for t in frames]

    blk = regime.compute("asx", frames, uni, bench=None)
    full = regime.compute(*_full_args())

    assert set(blk) >= set(full) - {"generated_at"}
    assert blk["days"] == [] and blk["sectors"] == {}
    assert blk["latest"]["state"] == "UNKNOWN"
    assert blk["windows"]["sma_slow"] == config.VIVEK_SMA
    json.dumps(blk)                                        # and it publishes


def _full_args():
    frames, uni = _market({"Materials": (20, 0.001)}, seed=500)
    return ("asx", frames, uni, None, 20)


# ── sectors: what is rankable ────────────────────────────────────────────────

def test_unclassified_is_never_ranked_as_a_sector():
    """389 of 2,212 ASX names carry "Unclassified". A bucket that big is an
    average of the whole market, so it tracks the market by construction and
    would sit mid-table forever while looking like a finding."""
    frames, uni = _market({"Consumer Discretionary": (20, 0.002),
                           "Unclassified": (60, 0.001),
                           "Materials": (20, 0.0005)}, seed=600)

    blk = regime.compute("asx", frames, uni, bench=None, days=20)

    assert "Unclassified" not in blk["sectors"]
    assert set(blk["sectors"]) == {"Consumer Discretionary", "Materials"}


def test_sectors_below_min_names_are_computed_but_not_ranked():
    """Participation on a 3-name sector is 0% or 33% and tops every leaderboard
    on noise. Same threshold as breadth, deliberately — two surfaces that
    disagreed about what is rankable would disagree about who is leading."""
    frames, uni = _market({"Consumer Discretionary": (20, 0.001),
                           "Materials": (20, 0.001),
                           "Health Care": (config.SECTOR_BREADTH_MIN_NAMES - 1, 0.02)},
                          seed=700)

    blk = regime.compute("asx", frames, uni, bench=None, days=20)

    assert "Health Care" not in blk["sectors"]             # despite being hottest
    assert "Health Care" not in blk["leaders"]


def test_relative_strength_is_the_sector_median_minus_the_market_median():
    """THE sentence the old surface could not represent: "the market has been
    shit to trade yet consumer discretionaries went up". A participation rate is
    absolute and says nothing about who is beating whom; rs21 is the frame in
    which a rotation is one number."""
    frames, uni = _market({"Consumer Discretionary": (20, 0.004),
                           "Materials": (20, -0.001),
                           "Financials": (20, -0.001)}, seed=800)

    blk = regime.compute("asx", frames, uni, bench=None, days=20)
    cd = blk["sectors"]["Consumer Discretionary"]

    assert cd["rank"] == 1
    assert cd["latest"]["rs21"] > 0                        # beating the market...
    assert cd["latest"]["ret21"] > 0
    assert blk["sectors"]["Materials"]["latest"]["rs21"] < 0
    assert blk["leaders"][0] == "Consumer Discretionary"


def test_a_sector_can_lead_on_relative_strength_while_its_own_return_is_negative():
    """The reading that makes RS worth having separately from return: in a
    market falling 10% a sector falling 2% is the strongest thing on the board,
    and it is the one that leads when the tape turns."""
    frames, uni = _market({"Consumer Discretionary": (20, -0.0005),
                           "Materials": (20, -0.004),
                           "Financials": (20, -0.004)}, seed=900)

    blk = regime.compute("asx", frames, uni, bench=None, days=20)
    cd = blk["sectors"]["Consumer Discretionary"]

    assert cd["latest"]["ret21"] < 0                       # it went DOWN
    assert cd["latest"]["rs21"] > 0                        # and still led
    assert cd["rank"] == 1


# ── the streak: the number the miss actually needed ──────────────────────────

def test_rs_streak_counts_back_from_today_and_breaks_on_the_first_miss():
    """Not "consumer discretionaries are strong today" but "they have been top
    three for thirty-one straight sessions". A streak that survived a session
    outside the top N would be a count of good days, not a run."""
    sectors = {
        # oldest ... newest — A is top-1 for the last three sessions only
        "A": {"rs21": [0.01, -0.05, 0.09, 0.09, 0.09]},
        "B": {"rs21": [0.05, 0.05, 0.02, 0.02, 0.02]},
        "C": {"rs21": [0.04, 0.04, 0.01, 0.01, 0.01]},
    }
    assert regime.rs_streak(sectors, "A", top_n=1) == 3
    assert regime.rs_streak(sectors, "B", top_n=1) == 0     # not top today
    assert regime.rs_streak(sectors, "B", top_n=2) == 5     # top-2 the whole time
    assert regime.rs_streak(sectors, "MISSING", top_n=1) == 0


def test_rs_streak_stops_at_a_session_where_nothing_could_be_ranked():
    """Before the return window fills, every sector's rs21 is None. That is not
    a session the leader failed to lead — it is a session with no ranking, and
    counting through it would inflate every streak to the length of the series."""
    sectors = {"A": {"rs21": [None, None, 0.09, 0.09]},
               "B": {"rs21": [None, None, 0.01, 0.01]}}
    assert regime.rs_streak(sectors, "A", top_n=1) == 2


def test_streak_is_available_on_the_first_run_because_history_is_recomputed():
    """The entire argument for measuring rotation with arithmetic instead of a
    state file: HORIZON had to start remembering the day it shipped and is
    useful around Christmas. This can answer "how long has that been true"
    about a run that started months before the module existed."""
    frames, uni = _market({"Consumer Discretionary": (20, 0.004),
                           "Materials": (20, 0.0),
                           "Financials": (20, 0.0),
                           "Energy": (20, 0.0)}, seed=1000)

    blk = regime.compute("asx", frames, uni, bench=None, days=126)

    assert blk["sectors"]["Consumer Discretionary"]["streak"] > 30
    assert len(blk["days"]) == 126


# ── the pre-setup pool ───────────────────────────────────────────────────────

def test_basing_counts_use_the_engines_own_eligibility_gates():
    """`near` must mean "eligible to become a setup", not "close-ish by a number
    invented on this page". evaluate() discards anything further than
    VIVEK_NEAR_TOL from the 200-day level before it looks at direction,
    reaction or structure, so the near-pool IS the setup count's leading
    indicator — but only while it is defined by the same constant."""
    idx = _days(400)
    frames, uni = {}, []
    for i in range(20):                       # pinned flat: price ≈ its own SMA
        yft = f"FLAT{i}.AX"
        frames[yft] = _frame(np.full(400, 10.0) + np.linspace(0, 0.001, 400), idx)
        uni.append({"symbol": f"FLAT{i}", "yf": yft, "sector": "Materials"})

    blk = regime.compute("asx", frames, uni, bench=None, days=5)
    mats = blk["sectors"]["Materials"]

    assert mats["latest"]["near"] == 20
    assert mats["latest"]["at"] == 20                      # at ⊂ near
    assert mats["latest"]["near_rate"] == 1.0
    assert blk["windows"]["near_tol"] == config.VIVEK_NEAR_TOL
    assert blk["windows"]["at_tol"] == config.VIVEK_AT_LEVEL_TOL


def test_a_name_far_from_its_average_is_in_neither_pool():
    """The pool is only useful if it excludes what has already run."""
    idx = _days(400)
    frames, uni = {}, []
    for i in range(20):                       # +0.4%/day: miles above the SMA
        yft = f"RUN{i}.AX"
        frames[yft] = _frame(_drift(400, 0.004, 1100 + i, vol=0.002), idx)
        uni.append({"symbol": f"RUN{i}", "yf": yft, "sector": "Materials"})

    blk = regime.compute("asx", frames, uni, bench=None, days=5)

    assert blk["sectors"]["Materials"]["latest"]["near"] == 0
    assert blk["latest"]["above200"] == 1.0                # above it, not near it


# ── the state read ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("a200,net_hl,want", [
    (0.72, 0.05, "BROAD"),
    (0.72, -0.01, "MIXED"),     # participation is there, today is not
    (0.45, 0.01, "MIXED"),
    (0.30, 0.01, "NARROW"),
    (0.60, -0.08, "NARROW"),    # broad on paper, breaking down right now
    (None, 0.05, "UNKNOWN"),
])
def test_state_thresholds(a200, net_hl, want):
    assert regime.state(a200, net_hl) == want


def test_state_is_unknown_rather_than_narrow_when_there_is_no_reading():
    """A market with no 200-day coverage must not read as risk-off. "I don't
    know" and "it's bad" are different instructions."""
    assert regime.state(None, None) == "UNKNOWN"


# ── the benchmark leg and the divergence sentence ────────────────────────────

def test_divergence_states_the_gap_between_the_median_name_and_the_index():
    """July, as a number. The index was carried down by its biggest names while
    the median name did fine — both true at once, and previously unreadable
    because the only market-wide figure published anywhere was the index print.
    An index is roughly twenty names in a trench coat."""
    idx = _days(520)
    frames, uni = _market({"Consumer Discretionary": (20, 0.003),
                           "Materials": (20, 0.002)}, seed=1200)
    bench = _frame(_drift(520, -0.001, 1300, vol=0.006), idx)   # index falling

    blk = regime.compute("asx", frames, uni, bench=bench, days=20)

    assert blk["latest"]["median_ret21"] > 0
    assert blk["latest"]["bench_ret21"] < 0
    assert blk["latest"]["divergence"] > 0
    assert any("better than the index makes it look" in n for n in blk["notes"])


def test_a_missing_benchmark_costs_the_divergence_line_and_nothing_else():
    """One index download is the module's only network call. Everything that
    matters is computed from bars already in memory, so a failed fetch must
    degrade to silence on one sentence, not to a blank page."""
    frames, uni = _market({"Materials": (20, 0.001)}, seed=1400)

    blk = regime.compute("asx", frames, uni, bench=None, days=20)

    assert blk["latest"]["bench_ret21"] is None
    assert blk["latest"]["divergence"] is None
    assert blk["latest"]["above200"] is not None
    assert blk["notes"]                                    # still says something
    assert not any("index" in n for n in blk["notes"])


def test_a_corrupt_benchmark_frame_is_survived():
    frames, uni = _market({"Materials": (20, 0.001)}, seed=1500)
    blk = regime.compute("asx", frames, uni, bench="not a frame at all", days=20)
    assert blk["latest"]["divergence"] is None
    assert blk["latest"]["above200"] is not None


def test_fetch_benchmark_never_raises(monkeypatch):
    monkeypatch.setattr(config, "REGIME_BENCHMARK", {"asx": "^AXJO"}, raising=False)
    monkeypatch.setattr("scanner.data.download",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no net")))
    assert regime.fetch_benchmark("asx") is None
    assert regime.fetch_benchmark("nowhere") is None


# ── publication: JSON that a browser will actually parse ─────────────────────

def test_no_nan_reaches_the_published_json():
    """`json.dumps` emits a bare NaN token that every browser's JSON.parse
    rejects. One thin sector with no median would take the whole page down
    rather than showing one blank cell."""
    assert regime._r(float("nan")) is None
    assert regime._r(float("inf")) is None
    assert regime._r(None) is None
    assert regime._r("abc") is None
    assert regime._r(0.123456) == 0.1235

    frames, uni = _market({"Materials": (20, 0.001)}, seed=1600)
    blk = regime.compute("asx", frames, uni, bench=None, days=126)
    text = json.dumps(blk)

    assert "NaN" not in text and "Infinity" not in text
    assert json.loads(text)["market"] == "asx"


def test_every_series_is_the_same_length_as_the_day_axis():
    """The front end plots any series against any other without carrying
    alignment logic, which is only safe if they share one axis."""
    frames, uni = _market({"Materials": (20, 0.001),
                           "Consumer Discretionary": (20, 0.002)}, seed=1700)
    blk = regime.compute("asx", frames, uni, bench=None, days=40)
    n = len(blk["days"])

    assert n == 40
    for key in ("n", "above200", "above50", "hi20", "lo20", "net_hl",
                "median_ret21", "median_ret63", "bench_ret21"):
        assert len(blk[key]) == n, key
    for name, v in blk["sectors"].items():
        for key in ("rs21", "rs63", "ret21", "ret63", "near", "at"):
            assert len(v[key]) == n, f"{name}.{key}"


def test_update_merges_so_a_crypto_only_run_cannot_blank_the_asx_read(tmp_path,
                                                                     monkeypatch):
    """Same rule as breadth: markets are published on the days they run, and a
    market that did not run keeps what it last said. Weekend crypto scans must
    not erase Friday's ASX board."""
    monkeypatch.setattr(config, "REGIME_ENABLED", True, raising=False)
    frames, uni = _market({"Materials": (20, 0.001)}, seed=1800)

    first = regime.update({"asx": {"frames": frames, "universe": uni, "bench": None}},
                          out_dir=tmp_path, day="2026-07-27")
    assert first["markets"]["asx"]["latest"]["above200"] is not None

    second = regime.update({"crypto": {"frames": {}, "universe": []}},
                           out_dir=tmp_path, day="2026-07-28")

    assert "crypto" not in second["markets"]               # no sectors to rank
    assert second["markets"]["asx"]["days"] == first["markets"]["asx"]["days"]
    assert second["day"] == "2026-07-28"
    assert json.loads((tmp_path / "regime.json").read_text())["markets"]["asx"]


def test_update_returns_none_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REGIME_ENABLED", False, raising=False)
    assert regime.update({"asx": {"frames": {}, "universe": []}}, out_dir=tmp_path) is None
    assert not (tmp_path / "regime.json").exists()


def test_an_explicit_none_bench_never_touches_the_network(tmp_path, monkeypatch):
    """How a caller (and every test) says "do not go out", as distinct from
    having no opinion. Without this the scan's own run would double-download."""
    monkeypatch.setattr(config, "REGIME_ENABLED", True, raising=False)
    monkeypatch.setattr(regime, "fetch_benchmark",
                        lambda m: pytest.fail("fetched despite explicit bench"))
    frames, uni = _market({"Materials": (20, 0.001)}, seed=1900)
    regime.update({"asx": {"frames": frames, "universe": uni, "bench": None}},
                  out_dir=tmp_path)


def test_update_writes_atomically_and_leaves_no_temp_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REGIME_ENABLED", True, raising=False)
    frames, uni = _market({"Materials": (20, 0.001)}, seed=2000)
    regime.update({"asx": {"frames": frames, "universe": uni, "bench": None}},
                  out_dir=tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == ["regime.json"]


# ── the sentences the page prints ────────────────────────────────────────────

def test_notes_survive_a_block_with_nothing_in_it():
    """A number nobody interprets is a number nobody acts on, so the page prints
    these verbatim — which means a KeyError here is a blank panel."""
    assert regime.notes({}) == []
    assert regime.notes({"latest": {}, "sectors": {}, "leaders": []}) == []


def test_notes_name_the_leader_and_how_long_it_has_led():
    frames, uni = _market({"Consumer Discretionary": (20, 0.004),
                           "Materials": (20, 0.0),
                           "Financials": (20, 0.0),
                           "Energy": (20, 0.0)}, seed=2100)

    blk = regime.compute("asx", frames, uni, bench=None, days=126)
    joined = " ".join(blk["notes"])

    assert "Consumer Discretionary leads on relative strength" in joined
    assert "straight sessions" in joined


def test_report_prints_ascii_only(capsys):
    """Windows console is cp1252. A non-ASCII byte in a printed string is a
    UnicodeEncodeError that kills the scan after the work is already done."""
    frames, uni = _market({"Consumer Discretionary": (20, 0.003),
                           "Materials": (20, 0.001)}, seed=2200)
    blk = regime.compute("asx", frames, uni, bench=None, days=20)

    regime.report("asx", blk)
    out = capsys.readouterr().out

    assert out.strip()
    out.encode("ascii")                                    # raises if it is not
