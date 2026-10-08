"""Mini price charts for the IGNITION panel -- DISPLAY ONLY.

Built by run.py AFTER the screen sorts (mcap's precedent), from the same
completed frames and forming bars the rows were screened on, and published as
the sidecar `public/data/ignition/<market>_charts.json`. It feeds no state,
count, replay or bot file: the screen payload and the replay are byte-for-byte
what they were without it. Contract (field names, index rules): CLAUDE.md,
IGNITION -> MINI CHARTS.

ENGINE-GATED on purpose (it is not in tests/test_ignition_fences.py's
`_NOT_ENGINE`): no clock, no network, no file access, config reads limited to
`IGNITION_*`. The browser draws; this module only slices and rounds, and it
computes every index the page needs from the window's own dates, so the page
never re-derives engine geometry.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from scanner import config
from scanner.indicators import sma

from . import engine as E

SCHEMA_VERSION = 1


def sig(x) -> Optional[float]:
    """A chart price at config.IGNITION_CHART_SIG_FIGS significant figures --
    never fixed decimals, which zero a sub-cent coin (round(4.08e-06, 4) is
    0.0). Non-finite or unreadable -> None (null in the JSON)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(x):
        return None
    return float(f"{x:.{int(config.IGNITION_CHART_SIG_FIGS)}g}") + 0.0   # + 0.0: no "-0.0"


def series(done: pd.DataFrame, forming: Optional[pd.DataFrame], row: dict) -> dict:
    """One row's arrays (contract: end, f, o/h/l/c, v, ma, and the optional
    b/t/x indices). Raises on unusable input; NEVER mutates its inputs.

    `done` = the completed bars the row was screened on, `forming` = the
    forming bar or None. The forming bar is appended with screen_frame's own
    guard (it must add exactly one bar), so the window ends where the row's
    price came from."""
    d = E.clean(done)
    if not len(d):
        raise ValueError("no completed bars")
    df = d
    if forming is not None and len(forming):
        both = E.clean(pd.concat([d, E.clean(forming)]))
        if len(both) == len(d) + 1:                       # screen_frame's own guard
            df = both
    f = len(df) - len(d)
    n = min(int(config.IGNITION_CHART_BARS) + f, len(df))
    if n < 2:
        raise ValueError("fewer than two bars")
    w = df.iloc[-n:]
    days = [E._date(i) for i in w.index]
    at = {day: k for k, day in enumerate(days)}
    vol = w["Volume"].to_numpy(dtype=float)
    vol = np.where(np.isfinite(vol), vol, 0.0)
    vmax = float(vol.max())
    scale = int(config.IGNITION_CHART_VOL_SCALE)
    out = {"end": days[-1 - f], "f": f,
           "o": [sig(x) for x in w["Open"]], "h": [sig(x) for x in w["High"]],
           "l": [sig(x) for x in w["Low"]], "c": [sig(x) for x in w["Close"]],
           "v": [int(round(scale * x / vmax)) if vmax > 0 else 0 for x in vol],
           # Whole frame first, THEN the window: a 200-SMA needs its history.
           "ma": [[sig(x) for x in sma(df["Close"], int(p)).iloc[-n:]]
                  for p in config.IGNITION_CHART_SMAS]}
    nb = int(config.IGNITION_BASE_BARS)
    if row.get("state") == "COILED":
        # engine base_high/base_low at the last completed bar T are
        # High/Low.shift(1).rolling(nb): bars T-nb .. T-1.
        i1 = n - 1 - f - 1
    else:
        t = at.get(row.get("trigger_date"))
        if t is None:
            return out
        out["t"], i1 = t, t - 1
        x = at.get(row.get("exit_date"))
        if x is not None:
            out["x"] = x
    if i1 - nb + 1 >= 0:
        out["b"] = [i1 - nb + 1, i1]
    return out


def build(results: List[dict], frames: Dict[str, pd.DataFrame],
          forming: Dict[str, pd.DataFrame]) -> Tuple[Dict[str, dict], List[str]]:
    """({yf: series}, sorted yf list of the rows no chart could be built for).
    One bad frame costs its own chart and nothing else."""
    rows: Dict[str, dict] = {}
    missing: List[str] = []
    for r in results:
        yf = r.get("yf")
        try:
            rows[yf] = series(frames[yf], forming.get(yf), r)
        except Exception:                                 # noqa: BLE001 -- a chart never costs the screen
            missing.append(str(yf))
    return rows, sorted(missing)


def payload(market: str, generated_at: str, rows: Dict[str, dict], missing: List[str]) -> dict:
    """The sidecar body. `generated_at` is the SAME run's screen stamp -- the
    page draws only when the two match."""
    return {"schema_version": SCHEMA_VERSION, "lens": "ignition", "market": market,
            "generated_at": generated_at, "bars": int(config.IGNITION_CHART_BARS),
            "smas": [int(p) for p in config.IGNITION_CHART_SMAS], "rows": rows,
            "missing": sorted(missing)}
