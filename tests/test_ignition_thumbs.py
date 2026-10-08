"""IGNITION mini charts (scanner/ignition/thumbs.py) -- the data contract.

The panel draws a candlestick thumbnail beside every Ignition row from the
sidecar `public/data/ignition/<market>_charts.json`. The browser NEVER derives
engine geometry: every index it needs (the base box `b`, the trigger bar `t`,
the exit bar `x`) is computed here, from the window's own dates, and these
tests hold each one to the engine's own definition -- the base the row's
`base.high`/`base.low` were measured on, the bar its `trigger_date` names.

Display only, and proven so: the screen payload is byte-identical with and
without the sidecar, the replay and the engine never import this module, and
the chart window is a fixed bar count with no market branch.

Fixtures come from tests/test_ignition.py (the designed decline -> base ->
breakout tape and its variants), loaded as a module so its tests are not
collected twice. Network is never touched. New `tests/*.py` need no
registration -- pytest collects the directory.
"""

from __future__ import annotations

import ast
import copy
import datetime as dt
import importlib.util
import inspect
import json
import pathlib
import types

import numpy as np
import pandas as pd
import pytest

from scanner import config, output
from scanner.ignition import engine as E
from scanner.ignition import run as RUN
from scanner.ignition import thumbs

ROOT = pathlib.Path(__file__).resolve().parents[1]
LENS = ROOT / "scanner" / "ignition"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ig = _load("_ig_suite_thumbs", "test_ignition.py")
_fences = _load("_ig_fences_suite_thumbs", "test_ignition_fences.py")
fx, T, MARKET = _ig.fx, _ig.T, _ig.MARKET
NB = int(config.IGNITION_BASE_BARS)
BARS = int(config.IGNITION_CHART_BARS)
sig = thumbs.sig


def chart(done, forming=None, market=MARKET):
    """(the engine's row, the chart series built for it)."""
    row = E.screen_frame(done, market, forming=forming)
    assert row is not None, "the fixture should screen"
    return row, thumbs.series(done, forming, row)


def window_dates(done, forming, n):
    """The window's dates, derived HERE from the frames (never from thumbs)."""
    idx = list(done.index) + (list(forming.index) if forming is not None else [])
    return [pd.Timestamp(i).strftime("%Y-%m-%d") for i in idx[-n:]]


def walk(n, seed=1, price=50.0, start="2024-01-01"):
    """A plain random walk with real wicks and volume -- for the shape tests
    that need no particular state."""
    rng = np.random.default_rng(seed)
    c = price * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.01,
                         "Low": np.minimum(o, c) * 0.99, "Close": c,
                         "Volume": rng.uniform(1e5, 9e5, n)},
                        index=pd.date_range(start, periods=n, freq="D"))


def quiet_forming(done):
    """A forming bar that triggers nothing: the last bar again, a day later."""
    q = done.iloc[-1:].copy()
    q.index = [done.index[-1] + pd.Timedelta(days=1)]
    q["Close"] = q["Close"] * 1.001
    return q


COILED = (fx("short").iloc[:400], None)                          # bar 400 is the trigger
PROVISIONAL = (fx("short").iloc[:400], fx("short").iloc[400:401])
IGNITING = (fx("base").iloc[:T + 1], None)
RUNNING = (fx("base").iloc[:T + 6], None)
RUNNING_FORMING = (fx("base").iloc[:T + 6], fx("base").iloc[T + 6:T + 7])
CLOSED_TRAIL = (fx("trail_early").iloc[:T + 10], None)
CLOSED_STOP = (fx("failed").iloc[:T + 6], None)
GAP_BELOW = (fx("gap_below").iloc[:T + 4], None)


# ---------------------------------------------------------------------------
# 1. lengths, the last bar and the last price
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", [COILED, IGNITING, RUNNING, CLOSED_TRAIL],
                         ids=["coiled", "igniting", "running", "closed"])
def test_a_completed_window_is_CHART_BARS_long_and_ends_on_the_rows_last_bar(case):
    done, forming = case
    row, s = chart(done, forming)
    assert s["f"] == 0
    for k in ("o", "h", "l", "c", "v"):
        assert len(s[k]) == BARS, k
    assert len(s["ma"]) == len(config.IGNITION_CHART_SMAS)
    assert all(len(a) == len(s["c"]) for a in s["ma"])
    assert s["end"] == row["last_bar"]
    assert s["c"][-1] == sig(row["price"])


@pytest.mark.parametrize("case", [PROVISIONAL, RUNNING_FORMING],
                         ids=["provisional", "running+forming"])
def test_a_forming_bar_adds_one_bar_after_end(case):
    done, forming = case
    row, s = chart(done, forming)
    assert s["f"] == 1
    for k in ("o", "h", "l", "c", "v"):
        assert len(s[k]) == BARS + 1, k
    assert all(len(a) == BARS + 1 for a in s["ma"])
    assert s["end"] == row["last_bar"] == window_dates(done, None, 1)[0]
    assert s["c"][-1] == sig(row["price"]) == sig(forming["Close"].iloc[-1])


def test_a_coiled_row_with_a_quiet_forming_bar_draws_it_and_prices_from_it():
    done = COILED[0]
    forming = quiet_forming(done)
    row, s = chart(done, forming)
    assert row["state"] == "COILED" and s["f"] == 1 and len(s["c"]) == BARS + 1
    assert s["c"][-1] == sig(row["price"]) and s["end"] == row["last_bar"]


def test_the_window_is_capped_at_CHART_BARS_and_a_short_history_ships_shorter():
    """150 bars -> the CHART_BARS cap; fewer than CHART_BARS -> every bar."""
    for n, want in ((150, BARS), (BARS - 30, BARS - 30)):
        s = thumbs.series(walk(n), None, {"state": "COILED"})
        assert [len(s[k]) for k in ("o", "h", "l", "c", "v")] == [want] * 5, n
        assert all(len(a) == want for a in s["ma"])


def test_fewer_than_two_bars_is_unusable():
    with pytest.raises(ValueError):
        thumbs.series(walk(1), None, {"state": "COILED"})
    with pytest.raises(ValueError):
        thumbs.series(walk(5).iloc[:0], None, {"state": "COILED"})


def test_a_forming_bar_that_does_not_add_exactly_one_bar_is_ignored():
    """screen_frame's own guard: a 'forming' bar dated on the last completed
    day, or two of them, is not a forming bar -- the window stays completed."""
    done = walk(200)
    dup = done.iloc[-1:].copy()
    two = walk(2, start=str((done.index[-1] + pd.Timedelta(days=1)).date()))
    for fm in (dup, two):
        s = thumbs.series(done, fm, {"state": "COILED"})
        assert s["f"] == 0 and len(s["c"]) == BARS
        assert s["c"][-1] == sig(done["Close"].iloc[-1])


# ---------------------------------------------------------------------------
# 2. COILED geometry -- the base the row's base.high/base.low describe
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("forming", [False, True], ids=["completed", "with-forming"])
def test_the_coiled_box_spans_the_60_bars_before_the_last_completed_bar(forming):
    done = COILED[0]
    fm = quiet_forming(done) if forming else None
    row, s = chart(done, fm)
    assert row["state"] == "COILED"
    last = len(s["c"]) - 1 - s["f"]
    assert s["b"] == [last - NB, last - 1]
    b0, b1 = s["b"]
    assert max(s["h"][b0:b1 + 1]) == sig(row["base"]["high"])
    assert min(s["l"][b0:b1 + 1]) == sig(row["base"]["low"])
    assert "t" not in s and "x" not in s


# ---------------------------------------------------------------------------
# 3. trigger geometry
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", [IGNITING, RUNNING, RUNNING_FORMING, CLOSED_TRAIL,
                                  CLOSED_STOP, GAP_BELOW, PROVISIONAL],
                         ids=["igniting", "running", "running+forming", "closed-trail",
                              "closed-stop", "gap-below-stop", "provisional"])
def test_t_is_the_trigger_bar_and_the_box_is_the_60_bars_before_it(case):
    done, forming = case
    row, s = chart(done, forming)
    dates = window_dates(done, forming, len(s["c"]))
    t = dates.index(row["trigger_date"])
    assert s["t"] == t
    assert s["b"] == [t - NB, t - 1]
    b0, b1 = s["b"]
    assert max(s["h"][b0:b1 + 1]) == sig(row["base"]["high"])
    assert min(s["l"][b0:b1 + 1]) == sig(row["base"]["low"])


def test_a_provisional_trigger_is_the_forming_bar():
    done, forming = PROVISIONAL
    row, s = chart(done, forming)
    assert row["state"] == "IGNITING" and row["provisional"] is True
    assert s["f"] == 1 and s["t"] == len(s["c"]) - 1
    assert "x" not in s


@pytest.mark.parametrize("case,reason", [(CLOSED_TRAIL, "trail"), (CLOSED_STOP, "stop")],
                         ids=["trail", "stop"])
def test_a_closed_row_marks_its_exit_bar(case, reason):
    done, forming = case
    row, s = chart(done, forming)
    assert row["state"] == "CLOSED" and row["exit_reason"] == reason
    dates = window_dates(done, forming, len(s["c"]))
    assert s["x"] == dates.index(row["exit_date"]) > s["t"]


def test_a_gap_below_the_stop_exits_on_the_bar_after_the_trigger():
    row, s = chart(*GAP_BELOW)
    assert row["exit_reason"] == "gap_below_stop" and row["exit_date"] == row["entry_date"]
    assert s["x"] == s["t"] + 1


def test_open_trigger_rows_carry_no_exit():
    for case in (IGNITING, RUNNING):
        _, s = chart(*case)
        assert "x" not in s


def test_a_trigger_outside_the_window_emits_no_t_x_or_b():
    s = thumbs.series(walk(200), None, {"state": "RUNNING", "trigger_date": "1999-01-01",
                                         "exit_date": "1999-01-02"})
    assert not {"t", "x", "b"} & set(s)


def test_a_base_that_starts_before_the_window_emits_no_box():
    """b is omitted when i0 < 0, never clipped -- a clipped box would say
    the base started where the window happens to."""
    s = thumbs.series(walk(NB), None, {"state": "COILED"})
    assert "b" not in s
    s = thumbs.series(walk(NB + 1), None, {"state": "COILED"})
    assert s["b"] == [0, NB - 1]


# ---------------------------------------------------------------------------
# 4. significant figures
# ---------------------------------------------------------------------------

def test_sig_keeps_five_significant_figures_and_never_fixed_decimals():
    assert config.IGNITION_CHART_SIG_FIGS == 5, "the cases below are written for 5"
    assert sig(4.0812345e-06) == 4.0812e-06
    assert sig(3.42000008) == 3.42
    assert sig(0.035) == 0.035
    assert sig(123456.7) == 123460.0
    neg_zero = sig(-0.0)
    assert neg_zero == 0.0 and str(neg_zero) == "0.0"
    for bad in (float("nan"), float("inf"), -float("inf"), None, "x"):
        assert sig(bad) is None, bad
    assert sig("2.5") == 2.5


# ---------------------------------------------------------------------------
# 5. volume
# ---------------------------------------------------------------------------

def test_volume_is_an_int_0_to_100_of_the_windows_loudest_bar():
    _, s = chart(*RUNNING)
    assert all(isinstance(v, int) and 0 <= v <= 100 for v in s["v"])
    assert max(s["v"]) == config.IGNITION_CHART_VOL_SCALE == 100
    vol = RUNNING[0]["Volume"].to_numpy()[-BARS:]
    assert s["v"] == [int(round(100 * x / vol.max())) for x in vol]


def test_an_all_zero_volume_window_is_all_zeros_not_a_crash():
    df = walk(200)
    df["Volume"] = 0.0
    s = thumbs.series(df, None, {"state": "COILED"})
    assert s["v"] == [0] * BARS


def test_a_non_finite_volume_bar_reads_as_silent():
    df = walk(200)
    df.iloc[-3, df.columns.get_loc("Volume")] = np.inf
    df.iloc[-2, df.columns.get_loc("Volume")] = np.nan
    s = thumbs.series(df, None, {"state": "COILED"})
    assert s["v"][-3] == 0 and s["v"][-2] == 0 and max(s["v"]) == 100


# ---------------------------------------------------------------------------
# 6. the SMA lines
# ---------------------------------------------------------------------------

def _sma_by_hand(close: np.ndarray, p: int) -> list:
    return [float(np.mean(close[j - p + 1:j + 1])) if j >= p - 1 else None
            for j in range(len(close))]


@pytest.mark.parametrize("forming", [False, True], ids=["completed", "with-forming"])
def test_each_ma_line_is_its_sma_on_the_whole_frame_sliced_to_the_window(forming):
    done = walk(250)                     # the 200-SMA warms up INSIDE the window
    fm = quiet_forming(done) if forming else None
    s = thumbs.series(done, fm, {"state": "COILED"})
    n = len(s["c"])
    close = np.r_[done["Close"].to_numpy(), fm["Close"].to_numpy() if forming else []]
    for k, p in enumerate(config.IGNITION_CHART_SMAS):
        want = _sma_by_hand(close, int(p))[-n:]
        got = s["ma"][k]
        assert [g is None for g in got] == [w is None for w in want], p
        for g, w in zip(got, want):
            if w is not None:
                assert g == pytest.approx(w, rel=1e-4), (p, g, w)   # 5 sig figs
    longest = max(config.IGNITION_CHART_SMAS)
    nulls = sum(v is None for v in s["ma"][list(config.IGNITION_CHART_SMAS).index(longest)])
    assert nulls == max(0, longest - 1 - (len(close) - n)), "warm-up bars must be null"


def test_the_drawn_lines_reproduce_the_engines_ribbon():
    """The chart's four lines ARE the coil's four SMAs: their spread is the
    ribbon the row was screened on, to 5 significant figures."""
    if tuple(config.IGNITION_CHART_SMAS) != tuple(config.IGNITION_RIBBON_SMAS):
        pytest.skip("IGNITION_CHART_SMAS no longer equals IGNITION_RIBBON_SMAS")
    done = COILED[0]
    _, s = chart(done)
    ribbon = E.base_features(E.clean(done), MARKET)["ribbon"].to_numpy()[-len(s["c"]):]
    checked = 0
    for i, r in enumerate(ribbon):
        vals = [a[i] for a in s["ma"]]
        if any(v is None for v in vals):
            continue
        assert max(vals) / min(vals) - 1 == pytest.approx(r, abs=2e-4), i
        checked += 1
    assert checked == len(s["c"])


# ---------------------------------------------------------------------------
# 7. publishable: no NaN token, and compact
# ---------------------------------------------------------------------------

def test_the_payload_serialises_without_a_nan_or_infinity_token():
    df = walk(260)
    df.iloc[5, df.columns.get_loc("Open")] = np.nan       # clean() reads it as the close
    df.iloc[6, df.columns.get_loc("High")] = np.inf
    df.iloc[7, df.columns.get_loc("Volume")] = np.inf
    rows, missing = thumbs.build([{"yf": "A", "state": "COILED"}], {"A": df}, {})
    text = output.dumps(thumbs.payload("crypto", "2031-01-01T00:00:00+00:00", rows, missing),
                        indent=None, separators=(",", ":"))
    assert "NaN" not in text and "Infinity" not in text
    assert json.loads(text)["rows"]["A"]["ma"][3][0] is None


def test_a_row_costs_under_9000_compact_bytes():
    """Catches an indent=2 publish or fixed 8-decimal rounding (both blow
    well past it); a 5-significant-figure row near 50 is ~7.2 KB."""
    frames = {f"S{i}": walk(300, seed=i) for i in range(100)}
    results = [{"yf": k, "state": "COILED"} for k in frames]
    rows, missing = thumbs.build(results, frames, {})
    assert missing == [] and len(rows) == 100
    body = thumbs.payload("asx", "2031-01-01T00:00:00+00:00", rows, missing)
    text = output.dumps(body, indent=None, separators=(",", ":"))
    assert len(text.encode("ascii")) / 100 < 9000


# ---------------------------------------------------------------------------
# 8. purity, and one bad frame costs one chart
# ---------------------------------------------------------------------------

def test_series_and_build_never_mutate_their_inputs():
    done, forming = PROVISIONAL
    row = E.screen_frame(done, MARKET, forming=forming)
    row_before = copy.deepcopy(row)
    done_before, forming_before = done.copy(deep=True), forming.copy(deep=True)
    thumbs.series(done, forming, row)
    frames, fm = {"A": done}, {"A": forming}
    results = [row | {"yf": "A"}]
    results_before = copy.deepcopy(results)
    thumbs.build(results, frames, fm)
    assert row == row_before and results == results_before
    pd.testing.assert_frame_equal(done, done_before)
    pd.testing.assert_frame_equal(forming, forming_before)
    assert list(frames) == ["A"] and list(fm) == ["A"]


def test_one_broken_frame_lands_in_missing_and_the_others_still_build():
    good = walk(200)
    broken = good.drop(columns=["Close"])                 # clean() -> empty -> raises
    results = [{"yf": "GONE", "state": "COILED"}, {"yf": "Z", "state": "COILED"},
               {"yf": "B", "state": "COILED"}, {"yf": "A", "state": "COILED"}]
    rows, missing = thumbs.build(results, {"A": good, "B": broken, "Z": good}, {})
    assert list(rows) == ["Z", "A"], "insertion order is the screen's results order"
    assert missing == ["B", "GONE"]


# ---------------------------------------------------------------------------
# 9. the sidecar body
# ---------------------------------------------------------------------------

def test_the_payload_keys_order_and_config_echo():
    body = thumbs.payload("asx", "2031-01-01T00:00:00+00:00", {"X": {}}, ["Q", "B"])
    assert list(body) == ["schema_version", "lens", "market", "generated_at", "bars",
                          "smas", "rows", "missing"]
    assert body["schema_version"] == thumbs.SCHEMA_VERSION == 1
    assert body["lens"] == "ignition" and body["market"] == "asx"
    assert body["bars"] == config.IGNITION_CHART_BARS
    assert body["smas"] == list(config.IGNITION_CHART_SMAS)
    assert body["missing"] == ["B", "Q"]


def test_a_series_carries_only_the_contract_keys():
    for case in (COILED, PROVISIONAL, CLOSED_TRAIL):
        _, s = chart(*case)
        assert set(s) <= {"end", "f", "o", "h", "l", "c", "v", "ma", "b", "t", "x"}, set(s)
        assert list(s)[:8] == ["end", "f", "o", "h", "l", "c", "v", "ma"]


# ---------------------------------------------------------------------------
# 10. the screen does not move, and the sidecar shares its stamp
# ---------------------------------------------------------------------------

def test_the_screen_payload_is_byte_identical_with_and_without_the_sidecar(monkeypatch):
    # elapsed_s is a stopwatch, not data: pin RUN's own `time` reference only.
    monkeypatch.setattr(RUN, "time", types.SimpleNamespace(time=lambda: 0.0))
    frames, rows = _ig._fresh_frames()
    now = dt.datetime.now(dt.timezone.utc)
    bare = RUN.screen_market(MARKET, frames=frames, rows=rows, now=now)
    charts: dict = {}
    with_charts = RUN.screen_market(MARKET, frames=frames, rows=rows, now=now,
                                    charts_out=charts)
    assert output.dumps(with_charts) == output.dumps(bare)
    assert charts["generated_at"] == with_charts["generated_at"]
    assert set(charts["rows"]) == {r["yf"] for r in with_charts["results"]}
    assert len(charts["rows"]) == 4 and charts["missing"] == []
    for r in with_charts["results"]:
        s = charts["rows"][r["yf"]]
        assert s["end"] == r["last_bar"] and s["c"][-1] == sig(r["price"])


def test_the_screen_hands_the_builder_its_forming_bars():
    """A frame whose last bar is TODAY (UTC) is split into completed bars + a
    forming bar by the screen; the chart is built from both, so a provisional
    trigger is the window's last bar."""
    now = dt.datetime.now(dt.timezone.utc)
    today = pd.Timestamp(now.date())
    frames = {"PRV-USD": _ig.redate(fx("short").iloc[:401], today)}
    charts: dict = {}
    pl = RUN.screen_market(MARKET, frames=frames, rows=[], now=now, charts_out=charts)
    row, = pl["results"]
    assert row["state"] == "IGNITING" and row["provisional"] is True
    s = charts["rows"]["PRV-USD"]
    assert s["f"] == 1 and s["t"] == len(s["c"]) - 1 == BARS
    assert s["end"] == row["last_bar"] and s["c"][-1] == sig(row["price"])


def test_a_screen_that_returns_nothing_fills_no_sidecar():
    charts: dict = {}
    assert RUN.screen_market(MARKET, frames={}, rows=[], charts_out=charts) is None
    assert charts == {}


# ---------------------------------------------------------------------------
# the CLI, over frames that really screen
# ---------------------------------------------------------------------------

@pytest.fixture
def cli(monkeypatch):
    frames, rows = _ig._fresh_frames()
    state = {"published": []}

    def fake_write_json(path, payload, **kw):
        if state.get("fail") and str(path).endswith(state["fail"]):
            raise OSError("disk full")
        state["published"].append((pathlib.Path(path).relative_to(ROOT).as_posix(),
                                   payload, kw))
        return pathlib.Path(path)

    monkeypatch.setattr(RUN, "_download", lambda m, p, n: (rows, dict(frames), {}))
    monkeypatch.setattr(RUN.sdata, "merge_with_cache",
                        lambda key, fresh, t, **k: (dict(fresh), {}))
    monkeypatch.setattr(output, "write_json", fake_write_json)
    state["raw"] = _fences.record_writes(monkeypatch)
    return state


def test_the_cli_publishes_the_screen_then_its_compact_sidecar(cli):
    assert RUN.main(["--market", "crypto"]) == 0
    assert [p for p, _, _ in cli["published"]] == ["public/data/ignition/crypto.json",
                                                    "public/data/ignition/crypto_charts.json"]
    (_, screen, skw), (_, charts, ckw) = cli["published"]
    assert skw == {"newline": True}
    assert ckw == {"newline": True, "indent": None, "separators": (",", ":")}
    assert charts["generated_at"] == screen["generated_at"]
    assert set(charts["rows"]) == {r["yf"] for r in screen["results"]} != set()
    assert cli["raw"] == []


def test_a_row_whose_chart_fails_is_missing_and_the_run_still_publishes(cli, monkeypatch):
    real = thumbs.series

    def series(done, forming, row):
        if row.get("yf") == "RUN-USD":
            raise ValueError("synthetic")
        return real(done, forming, row)

    monkeypatch.setattr(RUN.thumbs, "series", series)
    assert RUN.main(["--market", "crypto"]) == 0
    (_, screen, _), (_, charts, _) = cli["published"]
    assert charts["missing"] == ["RUN-USD"] and "RUN-USD" not in charts["rows"]
    assert "RUN-USD" in {r["yf"] for r in screen["results"]}


def test_a_dry_run_and_a_backtest_never_publish_a_sidecar(cli):
    assert RUN.main(["--market", "crypto", "--dry-run"]) == 0
    assert cli["published"] == []
    assert RUN.main(["--market", "crypto", "--backtest"]) == 0
    assert [p for p, _, _ in cli["published"]] == ["public/data/ignition/crypto_backtest.json"]


def test_a_failed_sidecar_write_fails_the_run(cli):
    """Raised out of main(): under `python -m` that is exit 1, ignition.yml's
    red arm, and the commit step never runs -- the screen file written to the
    runner's disk is committed by nothing. The previous pair stays live."""
    cli["fail"] = "crypto_charts.json"
    with pytest.raises(OSError):
        RUN.main(["--market", "crypto"])
    assert [p for p, _, _ in cli["published"]] == ["public/data/ignition/crypto.json"]


# ---------------------------------------------------------------------------
# 11. display only, and no market branch
# ---------------------------------------------------------------------------

def test_the_replay_and_the_engine_never_import_the_chart_builder():
    for name in ("backtest.py", "engine.py"):
        mods = set(_fences._imports(LENS / name))
        assert not any(m == "scanner.ignition.thumbs" or m.endswith(".thumbs")
                       for m in mods), (name, sorted(mods))


def test_the_chart_window_is_bars_and_never_a_calendar_window():
    assert "IGNITION_CHART_BARS" not in E.CALENDAR_WINDOWS
    with pytest.raises(KeyError):
        E.bars("asx", "IGNITION_CHART_BARS")
    tree = ast.parse((LENS / "thumbs.py").read_text(encoding="utf-8"))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"bars", "mkt", "IGNITION_BARS_PER_YEAR"}, names & {"bars", "mkt"}
    assert not any(a.endswith("_BY_MARKET") for a in names)
    for fn in (thumbs.series, thumbs.build):
        assert "market" not in inspect.signature(fn).parameters


def test_the_asx_and_crypto_windows_on_one_frame_are_identical():
    """The same weekday tape screened as an ASX stock and as a coin: the
    rows differ in nothing the chart reads, and the chart is the same."""
    done = fx("base").iloc[:T + 6]
    done.index = pd.bdate_range("2021-01-04", periods=len(done))
    a_row, a = chart(done, market="asx")
    c_row, c = chart(done, market="crypto")
    assert a_row["state"] == c_row["state"] == "RUNNING"
    assert a == c and len(a["c"]) == BARS
