"""2026-10-08 audit, cluster E -- #67: momentum's skipped_by_reason keyed each
skip on the reason TEXT before ' (', and the price and turnover reasons carry
their numbers and no bracket, so every distinct value became its own bucket
(798 keys in one committed ASX file: 'price 0.0060 below the asx floor
0.0200': 34, 'price 0.0030 ...': 22, ...). The screen now buckets by gate
with the same helper the backtest's signals_gated always used.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd

from scanner.momentum import backtest as BT
from scanner.momentum import gates as G
from scanner.momentum import run as R

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _frame(price: float, *, n: int = 300, vol: float = 1e6) -> pd.DataFrame:
    idx = pd.bdate_range(end=pd.Timestamp.now("UTC").tz_localize(None).normalize(),
                         periods=n) - pd.offsets.BDay(1)
    rng = np.random.default_rng(int(price * 1e5) % 2 ** 31)
    c = price * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    c = c * (price / c[-1])
    prev = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame({"Open": prev, "High": np.maximum(c, prev) * 1.01,
                         "Low": np.minimum(c, prev) * 0.99, "Close": c,
                         "Volume": np.full(n, vol)}, index=idx)


def test_sub_floor_prices_count_under_ONE_gate_not_one_key_per_price():
    frames = {f"P{i}.AX": _frame(p) for i, p in enumerate((0.006, 0.003, 0.007, 0.012, 0.019))}
    frames["THIN.AX"] = _frame(5.0, vol=1.0)          # turnover far under A$250k
    frames["THIN2.AX"] = _frame(7.0, vol=3.0)
    p = R.screen_market("asx", frames=frames, rows=[])
    by = p["summary"]["skipped_by_reason"]
    assert by.get("price") == 5, by
    assert by.get("turnover") == 2, by
    assert not any(any(ch.isdigit() for ch in k) for k in by), by
    assert p["summary"]["skipped_gates"] == 7


def test_the_screen_and_the_backtest_share_one_key():
    for reason in ("price 0.0060 below the asx floor 0.0200",
                   "turnover 9352 below the crypto floor 5000000",
                   "short history (59 < 60 bars)",
                   "stale frame (5 sessions old)",
                   "non-operating listing (fund / REIT / LIC / preferred / warrant)"):
        assert G.reason_key(reason) == G.reason_key(reason.replace("0", "9"))
    assert G.reason_key("price 0.0060 below the asx floor 0.0200") == "price"
    assert G.reason_key("non-operating listing (fund / REIT)") == "non-operating listing"
    # review of #67: an upper-case letter inside a gate's name does not cut it
    # short ("all-NaN close column" used to key as "all"), and every reason
    # gate_frame can return keys to a non-empty gate name
    assert G.reason_key("all-NaN close column") == "all-NaN close column"
    assert G.reason_key("last close is not positive (-1.0)") == "last close is not positive"
    assert G.reason_key("turnover not computable") == "turnover not computable"
    assert G.reason_key("no volume in the last 5 bars (suspended?)") == "no volume in the last"
    assert not hasattr(BT, "_reason_key"), "a second copy of the key"
    src = (ROOT / "scanner" / "momentum" / "run.py").read_text(encoding="utf-8")
    assert 'split(" (")' not in src
    assert "gates.reason_key(reason)" in src
