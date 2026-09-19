"""The h4_sma seam must stay INERT until the owner says otherwise.

evaluate() gained an optional `h4_sma` so the A/B harness can measure what a
real 4H level would do using the real engine. The whole value of that parameter
is that passing nothing reproduces today's scan exactly -- if it ever stops
doing so, the owner's deck changed without anyone deciding to change it.
"""
import numpy as np
import pandas as pd

from scanner import config, scan, vivek


def _frame(n=340, seed=7):
    rs = np.random.RandomState(seed)
    close = 100 + np.cumsum(rs.normal(0, 0.2, n))
    close = close - (close.mean() - 100)
    close[-14:-4] = np.linspace(close[-15], 99.0, 10)
    close[-4:] = np.linspace(99.0, 101.5, 4)
    return pd.DataFrame({"Open": close * 0.999, "High": close * 1.01,
                         "Low": close * 0.99, "Close": close, "Volume": 2e6},
                        index=pd.date_range("2021-01-01", periods=n, freq="D"))


def test_omitting_h4_sma_is_byte_identical_to_the_shipped_behaviour():
    df = _frame()
    assert vivek.evaluate(df) == vivek.evaluate(df, h4_sma=None)


def test_passing_none_or_a_junk_value_falls_back_to_the_daily_proxy():
    """Fail-closed: a NaN, a zero or a negative must not become a price level."""
    df = _frame()
    base = vivek.evaluate(df)
    for bad in (None, float("nan"), 0.0, -5.0):
        assert vivek.evaluate(df, h4_sma=bad) == base, f"{bad!r} was treated as a level"


def test_a_real_h4_level_DOES_change_the_outcome_so_the_ab_is_measuring_something():
    """The guard above would also pass if the parameter were ignored entirely.
    This is the other half: a genuine level must actually reach the ranking."""
    df = _frame()
    base = vivek.evaluate(df)
    assert base is not None
    # A level right on top of price: it must become the in-play H4 candidate.
    near = float(df["Close"].iloc[-1])
    out = vivek.evaluate(df, h4_sma=near)
    assert out is not None
    assert (out["level"], out["level_tf"]) != (base["level"], base["level_tf"]) \
        or out["at_level"]


def test_no_production_caller_passes_h4_sma_yet():
    """The seam exists for measurement. The day scan.py starts passing a real
    level is the day grades move, and it needs the owner's sign-off first."""
    src = open(scan.__file__, encoding="utf-8").read()
    assert "h4_sma" not in src, (
        "scan.py now passes a real 4H level into evaluate() — that changes which "
        "names appear and what grade they carry. It is a trade decision.")


def test_the_engine_still_labels_the_proxy_honestly():
    src = open(vivek.__file__, encoding="utf-8").read()
    assert 'Daily-200 proxy for the H4 200 SMA' in src


def test_the_ab_harness_never_writes_anything():
    import ast, pathlib
    p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "h4_level_ab.py"
    tree = ast.parse(p.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in ("write", "write_text", "replace", "to_json",
                                          "to_csv", "commit"), \
                f"the A/B harness calls {node.func.attr}() — it must only measure"
    assert config.VIVEK_DATA_PERIOD == "5y", "the A/B must compare against the live scan period"
