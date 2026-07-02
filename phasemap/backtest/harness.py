"""M4 backtest & proof harness (spec Section 10).

Replays history bar-by-bar with ZERO lookahead: signals come from the SAME
SetupEngine the nightly scan uses, driven forward one bar at a time via its
recorder hook — nothing here feeds the engine any future data. Forward
returns / MAE / time-to-target are measured after the fact from bars that
were strictly in the signal's future.

A signal = a displacement confirmation (the state machine entering
DISPLACED). Its forward story is read off the engine's own zone objects as
they update, so the harness can never disagree with the product's rules.
"""

import math
import random

from phasemap.config import CONFIG
from phasemap.engine.buffers import pct_floor  # noqa: F401  (re-export convenience)
from phasemap.engine.indicators import compute_indicators
from phasemap.engine.setup_engine import SetupEngine


class SignalRecorder:
    """Watches one engine run and logs every displacement signal + outcome."""

    def __init__(self, ticker: str, ind, market: str):
        self.ticker = ticker
        self.ind = ind
        self.market = market
        self.signals = []
        self._active = None

    def __call__(self, i: int, eng: SetupEngine) -> None:
        # A fresh displacement confirmation = a new signal.
        if (eng.displacement_index == i and eng.state == "DISPLACED" and
                (self._active is None or self._active["sweep_index"] != eng.sweep_index)):
            if self._active is not None:
                self._active["end_index"] = i - 1
            self._active = self._capture(i, eng)
            self.signals.append(self._active)
        a = self._active
        if a is None:
            return
        # The engine reset (expiry/terminal re-entry) → stop tracking.
        if eng.sweep_index != a["sweep_index"]:
            a["end_index"] = a.get("end_index") or i
            self._active = None
            return
        # Zone outcomes, read straight off the live zone objects.
        if eng.targets:
            t1 = eng.targets[0]
            if a["t1_touched_bar"] is None and t1.status != "UNTESTED":
                a["t1_touched_bar"] = i
            if a["t1_consumed_bar"] is None and t1.status == "CONSUMED":
                a["t1_consumed_bar"] = i
            if len(eng.targets) > 1 and a["t2_consumed_bar"] is None \
                    and eng.targets[1].status == "CONSUMED":
                a["t2_consumed_bar"] = i
        if a["stalled_bar"] is None and eng.state == "STALLED":
            a["stalled_bar"] = i
        if a["dead_bar"] is None and eng.state == "DEAD":
            a["dead_bar"] = i
        if a["complete_bar"] is None and eng.state == "COMPLETE":
            a["complete_bar"] = i

    def _capture(self, i: int, eng: SetupEngine) -> dict:
        ind = self.ind
        close = float(ind.close[i])
        entry_mid = (eng.entry.low + eng.entry.high) / 2 if eng.entry else close
        anchor_ctx = any(eng.swept_below_anchor.get(k)
                         for k in ("yearly_open", "quarterly_open"))
        tier = "A+" if anchor_ctx else "A"
        if eng.flip_tag == "SLOW_FLIP":
            tier = {"A+": "A", "A": "Watch"}[tier]
        turnover = ind.turnover20[i]
        t1 = eng.targets[0] if eng.targets else None
        return {
            "ticker": self.ticker,
            "market": self.market,
            "direction": "bullish" if eng.bull else "bearish",
            "sweep_index": eng.sweep_index,
            "signal_index": i,
            "signal_date": ind.dates[i].isoformat(),
            "tier": tier,
            "anchor_context": bool(anchor_ctx),
            "flip": eng.flip_tag,
            # 12 dp — 6 dp rounds micro-priced coins (sub-cent crypto) to 0.0
            # and a zero entry_mid poisons every forward-return division
            "close": round(close, 12),
            "entry_mid": round(entry_mid, 12),
            "t1_low": round(t1.low, 12) if t1 else None,
            "t1_high": round(t1.high, 12) if t1 else None,
            "n_targets": len(eng.targets),
            "illiquid": bool(math.isnan(turnover) or turnover < CONFIG.turnover_floor),
            "cents": close < 1.0,
            "t1_touched_bar": None, "t1_consumed_bar": None, "t2_consumed_bar": None,
            "stalled_bar": None, "dead_bar": None, "complete_bar": None,
            "end_index": None,
        }


def _finalize(sig: dict, ind) -> None:
    """Post-hoc measurement from strictly-future bars."""
    i = sig["signal_index"]
    n = len(ind.close)
    bull = sig["direction"] == "bullish"
    sign = 1.0 if bull else -1.0
    em = sig["entry_mid"]
    for h in CONFIG.fwd_return_bars:
        j = i + h
        sig[f"fwd_{h}"] = round(sign * (float(ind.close[j]) / em - 1), 4) \
            if (j < n and em > 0) else None
    end = min(n, i + CONFIG.stats_window_bars + 1)
    if end > i + 1 and em > 0:
        if bull:
            sig["mae"] = round(float(min(ind.low[i + 1:end])) / em - 1, 4)
        else:
            sig["mae"] = round(-(float(max(ind.high[i + 1:end])) / em - 1), 4)
    else:
        sig["mae"] = None
    w = CONFIG.stats_window_bars
    t1b, db = sig["t1_consumed_bar"], sig["dead_bar"]
    sig["time_to_t1"] = (t1b - i) if t1b is not None else None
    sig["t1_hit"] = bool(t1b is not None and t1b - i <= w and (db is None or db > t1b))
    # The 50% rule, measured (spec: "how often STALLED saved capital vs cut a
    # winner"): after a stall, did T1 still get consumed first (cut a winner)
    # or did the hard floor break first (saved capital)?
    if sig["stalled_bar"] is not None:
        if t1b is not None and (db is None or t1b < db):
            sig["stall_class"] = "cut_winner"
        elif db is not None:
            sig["stall_class"] = "saved_capital"
        else:
            sig["stall_class"] = "neither"
    else:
        sig["stall_class"] = None


def run_ticker(ticker: str, df, market: str, volume_is_usd: bool = False) -> list:
    """All signals for one ticker, both directions, fully measured."""
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df = df[(df[["Open", "High", "Low", "Close"]] > 0).all(axis=1)].reset_index(drop=True)
    if len(df) < CONFIG.min_history_bars:
        return []
    ind = compute_indicators(df, volume_is_usd=volume_is_usd)
    out = []
    for bull in (True, False):
        rec = SignalRecorder(ticker, ind, market)
        eng = SetupEngine(ind=ind, bull=bull, market=market, recorder=rec)
        eng.process()
        for sig in rec.signals:
            _finalize(sig, ind)
            out.append(sig)
    return out


def random_baseline(frames: dict, n_signals: int, market: str) -> dict:
    """Deterministic random-entry baseline on the same tickers/window: sample
    the same NUMBER of entries across the same universe, enter at the close,
    measure the same forward horizons (long side — the unconditioned drift)."""
    rng = random.Random(CONFIG.backtest_seed)
    tickers = sorted(frames)
    rets = {h: [] for h in CONFIG.fwd_return_bars}
    if not tickers or n_signals <= 0:
        return {f"fwd_{h}": None for h in CONFIG.fwd_return_bars} | {"n": 0}
    for _ in range(n_signals):
        t = tickers[rng.randrange(len(tickers))]
        df = frames[t]
        closes = df["Close"].to_numpy()
        hi = len(closes) - max(CONFIG.fwd_return_bars) - 1
        lo = CONFIG.min_history_bars
        if hi <= lo:
            continue
        i = rng.randrange(lo, hi)
        for h in CONFIG.fwd_return_bars:
            if closes[i] > 0:
                rets[h].append(float(closes[i + h]) / float(closes[i]) - 1)
    out = {"n": len(rets[CONFIG.fwd_return_bars[0]])}
    for h in CONFIG.fwd_return_bars:
        vals = rets[h]
        out[f"fwd_{h}"] = round(sum(vals) / len(vals), 4) if vals else None
    return out


def buy_hold_baseline(frames: dict) -> dict:
    """Mean per-ticker buy-and-hold return over the same replay window."""
    rets = []
    for df in frames.values():
        closes = df["Close"].dropna().to_numpy()
        start = CONFIG.min_history_bars - 1
        if len(closes) > start and closes[start] > 0:
            rets.append(float(closes[-1]) / float(closes[start]) - 1)
    return {"n": len(rets),
            "total_return": round(sum(rets) / len(rets), 4) if rets else None}
