"""VIVEK 5.0 walk-forward backtester.

Replays the REAL engine over history rather than reimplementing the strategy:
for each symbol it walks the daily series bar-by-bar and, on every bar where
price is near a 200 SMA, runs the exact same ``vivek.evaluate`` /
``build_plans`` / grading the live scanner uses on a slice of history *up to and
including that bar* (so there is no look-ahead). When that produces an ARMED
A+/A setup it opens a paper trade at the NEXT bar's open and manages it forward
with the same 5.0 rules (scale at TP1/2/3, SL → break-even at TP1 → locked
structure at TP2) and the same fees + slippage R-drag the live bot/journal use.

Fills are pessimistic intrabar: within a bar the adverse extreme (the stop
side) is checked BEFORE the favourable extreme, so when a bar's range spans
both a stop and a target the stop is assumed to fill first.

Backtestable timeframes: Daily (1D), 3-Day (3D) and Weekly (1W). 4H is not
backtestable server-side (no deep intraday history). Trades also carry the
LEVEL that produced the signal (level_tf: weekly / 3d / h4-proxy) so the
report can answer "does the 3D-200 level earn its keep?" separately from
"which plan timeframe manages best". Honest caveats: today's universe →
survivorship bias; yfinance data quality; A+ setups are rare so N is modest.

CLI:  python -m scanner.vivek_backtest --market all --limit 60 --period 10y
"""

import argparse
import datetime as dt
import json
import logging
import pathlib

import numpy as np
import pandas as pd

from . import config, output, vivek
from .broker.vivek_bot import size_position, _is_fund_or_reit
from .vivek_journal import _snapshot, _mark, _apply_costs, _r_of, costs_for

log = logging.getLogger("vivek_backtest")

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_FILE = ROOT / "public" / "data" / "vivek_backtest.json"

EQUITY = config.VIVEK_BOT_ACCOUNT_EQUITY
TIMEFRAMES = ("1D", "3D", "1W")
LEVEL_TFS = ("weekly", "3d", "h4")     # which 200-SMA produced the signal


def _sizing_basis() -> dict:
    """Which of the two sizing models priced this report's dollar columns.

    ``_risk_usd`` calls ``size_position(EQUITY, ...)`` with no
    ``notional_target``, so the report silently inherits whichever mode config
    is in — and the two modes do not produce comparable dollars for the same
    trades. The 2026-07-26 report priced at risk-% off a $10,000 equity; the
    next one prices at a flat $5,000 per entry (owner decision, 2026-07-28).
    Same trades, ``total_usd`` moves by an order of magnitude, and until now
    nothing in the file recorded why.

    Worse than uninformative: under ``fixed_notional`` the equity drops out of
    the dollar column ENTIRELY. Units are ``notional / entry``, so EQUITY
    survives only in the leverage cap — which a $5,000 position on a $150,000
    book can never reach. ``equity`` alone therefore *reads* like the basis
    while having no effect on it, which is the failure mode worth naming: a
    number that looks like the answer to the question a reader is asking.

    ``vivek_bot`` already stamps ``sizing_mode`` onto every live book row
    (``tests/test_fixed_notional.py``). This is the same stamp on the report
    that is supposed to be that book's evidence.

    R-multiples are ratios and are unaffected by any of this, which is why the
    Insights page reads ``total_r`` and never the dollars.
    """
    notional = float(getattr(config, "VIVEK_BOT_POSITION_NOTIONAL", 0) or 0)
    return {"equity": EQUITY,
            "position_notional": notional,
            "sizing_mode": "fixed_notional" if notional > 0 else "risk_pct"}


# ── per-symbol replay ─────────────────────────────────────────────────────────

def _candidate_mask(df: pd.DataFrame) -> np.ndarray:
    """Bars where price is near a 200 SMA (daily or weekly) — the only place a
    reaction can exist. A superset of the engine's in-play test (the engine
    re-checks precisely), so it only saves work, never invents trades."""
    close = df["Close"]
    tol = config.VIVEK_NEAR_TOL * 1.3                      # widen so we never miss one
    dsma = close.rolling(config.VIVEK_SMA).mean()
    wk = close.resample("W-FRI").last()
    wsma = wk.rolling(config.VIVEK_SMA).mean().reindex(df.index, method="ffill")
    # 3-Day 200 SMA — epoch-anchored 72h buckets, identical to the engine's
    # _resample_3day_ohlc, so slice anchoring can't drift from this mask.
    d3 = close.resample("72h", origin="epoch").last().dropna()
    sma3 = d3.rolling(config.VIVEK_SMA).mean().reindex(df.index, method="ffill")
    near_d = (close - dsma).abs() / close <= tol
    near_w = (close - wsma).abs() / close <= tol
    near_3 = (close - sma3).abs() / close <= tol
    return (near_d.fillna(False) | near_w.fillna(False) | near_3.fillna(False)).to_numpy()


def _turnover_series(df: pd.DataFrame, market: str) -> np.ndarray:
    """Rolling average turnover per bar — ``scan.py::_liquidity``, vectorised.

    TOP100 #59: the live scan drops any name whose average turnover over the
    last ``LIQUIDITY_LOOKBACK`` bars is under the market's ``liquidity_min``,
    and the backtest applied NO liquidity test at all. The gap is not a rounding
    error, it is the direction of the bias: the names it let through are the
    thin ones, which are exactly where the backtest's own fill model is most
    optimistic (it fills at the open, at the trigger price, in whatever size the
    sizer asks for). So the untested population inflated the published edge and
    could never have been traded.

    ``rolling(N).mean()`` at bar ``j`` is the mean of bars ``j-N+1 .. j``, which
    is precisely what ``_liquidity`` computes as ``.iloc[-N:].mean()`` on a
    slice ending at ``j`` — and the replay loop starts at ``VIVEK_MIN_HISTORY``
    (220) so the window is always full. ``min_periods=1`` is not slack, it is
    the parity detail: bare ``.mean()`` skips NaNs and divides by the count that
    survived, and rolling's default ``min_periods=window`` would instead return
    NaN for a window holding a single missing bar — turning a name the live scan
    passes into one the backtest silently drops. A whole-window NaN comes back
    NaN either way, and ``NaN < liq_min`` is False in both files, so a name with
    no volume data at all keeps passing exactly as it does live.
    """
    if getattr(config.MARKETS[market], "volume_is_usd", False):
        # Crypto: Yahoo "Volume" is already USD dollar-volume.
        s = df["Volume"]
    else:
        s = df["Close"] * df["Volume"]
    return s.rolling(config.LIQUIDITY_LOOKBACK, min_periods=1).mean().to_numpy()


def _build_row(sig: dict, df_slice: pd.DataFrame, symbol: str, name: str, sector: str):
    """Replicate scan.py's row build (grade + gate + plans), minus hysteresis.

    PARITY: the armed/R:R gate reads the best bot-relevant plan (1W > 3D > 1D),
    exactly like scan.py — a backtest gated differently from the live scan
    would invalidate the evidence.

    TOP100 #57 — the docstring above said that before the code did. The R:R
    survival test ran on ``lv`` (the DAILY plan) where scan.py runs it on
    ``hp = gate_plan or lv`` (the HEADLINE plan — the gated timeframe when
    armed), so a weekly- or 3D-armed setup whose 1D plan was missing or had
    rr <= 0 was dropped from the backtest and kept by the live scan. That is
    the population the bot preferentially trades: `pending` below only ever
    opens ARMED plans, and the gate order is 1W > 3D > 1D, so the discarded
    cohort was drawn from the TOP of the bot's own preference list. The
    published evidence was therefore silently missing trades the live system
    takes, while claiming parity in this docstring — the failure mode #57 is
    about is not the gate being wrong, it is the gate being wrong in the one
    file whose entire job is to say what the gate does.

    Two smaller things came with the shape: `float(... or 0)` instead of
    `.get("rr", 0)` (a plan carrying an explicit ``rr: None`` raised
    ``TypeError`` on ``None <= 0`` — and `_build_row` is called OUTSIDE
    replay's try/except, so that killed the whole symbol's replay rather than
    skipping one bar), and `gate_rr` now reads `hp` in both branches, which is
    what the old two-branch expression already computed once the 1D plan was
    known to be valid. Only the survival test's population moved.
    """
    points, grade, _ = vivek.score_and_grade(sig)
    if grade is None:
        return None, None, None
    plans = vivek.build_plans(df_slice, sig)
    lv = plans.get("1D")
    gate_tf = next((tf for tf in ("1W", "3D", "1D")
                    if (plans.get(tf) or {}).get("armed")), None)
    gate_plan = plans.get(gate_tf) if gate_tf else None
    armed = gate_plan is not None
    hp = gate_plan or lv
    if not hp or float(hp.get("rr") or 0) <= 0:
        return None, None, None
    gate_rr = float(hp.get("rr") or 0)
    grade, _notes = vivek.gate_grade(grade, sig, gate_rr, armed)
    if grade is None:
        return None, None, None
    entry_types = ([gate_plan["entry_trigger"]] if armed and gate_plan.get("entry_trigger")
                   else vivek.entry_types(sig))
    row = {"symbol": symbol, "name": name, "sector": sector,
           "dir": "LONG" if sig["direction"] == "long" else "SHORT",
           "grade": grade, "entry_types": entry_types,
           "level_tf": sig.get("level_tf")}
    return row, plans, grade


def _force_close(tr: dict, price: float, day: str, costs) -> None:
    """Close any still-open remainder at `price` (end of data)."""
    is_long = tr["direction"] == "long"
    remaining = round(1.0 - tr.get("booked_pct", 0.0), 6)
    if remaining > 1e-9:
        tr["exits"].append({"reason": "eod", "price": round(price, 8), "pct": remaining, "date": day})
        tr["gross_r"] = round(tr.get("gross_r", 0.0) + remaining * _r_of(price, tr["entry"], tr["risk"], is_long), 4)
        tr["booked_pct"] = 1.0
    tr["status"] = "closed"
    tr["exit"] = round(price, 8)
    tr["exit_date"] = day
    tr["exit_reason"] = "target" if tr.get("tp3_hit") else ("trail" if tr.get("tp1_hit") else "eod")
    _apply_costs(tr, costs)


def _manage_bar(tr: dict, high: float, low: float, close: float, day: str, costs, is_last: bool) -> None:
    is_long = tr["direction"] == "long"
    adverse, favourable = (low, high) if is_long else (high, low)
    _mark(tr, adverse, day, costs)                         # stop side first (pessimistic)
    if tr["status"] == "open":
        _mark(tr, favourable, day, costs)                 # then any targets
    if tr["status"] == "open" and is_last:
        _force_close(tr, close, day, costs)


def replay_symbol(df: pd.DataFrame, market: str, symbol: str, name: str, sector: str,
                  long_only: bool = False) -> list[dict]:
    """Walk one symbol's daily history and return its closed backtest trades."""
    if df is None or len(df) < config.VIVEK_MIN_HISTORY + 5:
        return []
    df = df[~df.index.duplicated(keep="last")].sort_index()
    # 24/7 markets: never let the still-forming UTC daily bar into the replay
    # (2026-07-20 — parity with the scan's VIVEK_DROP_FORMING_BAR / H3): a
    # partial final candle would seed the last detect/manage step with numbers
    # that change until midnight.
    if market == "crypto" and len(df) and df.index[-1].date() == dt.datetime.now(dt.timezone.utc).date():
        df = df.iloc[:-1]
        if len(df) < config.VIVEK_MIN_HISTORY + 5:
            return []
    n = len(df)
    idx = df.index
    o, h, l, c = df["Open"].to_numpy(), df["High"].to_numpy(), df["Low"].to_numpy(), df["Close"].to_numpy()
    cand = _candidate_mask(df)
    turnover = _turnover_series(df, market)
    liq_min = config.MARKETS[market].liquidity_min
    costs = costs_for(market)

    closed: list[dict] = []
    open_slots = {tf: None for tf in TIMEFRAMES}
    pending: list[tuple] = []                              # (tf, plan, row) → open at next bar's open

    for j in range(config.VIVEK_MIN_HISTORY, n):
        day = idx[j].date().isoformat()
        # 1) open queued entries at THIS bar's open
        for tf, plan, row in pending:
            if open_slots[tf] is None and np.isfinite(o[j]):
                tr = _snapshot(row, tf, plan, market, float(o[j]), day)
                if tr is not None:
                    tr["market"] = market
                    tr["level_tf"] = row.get("level_tf")
                    open_slots[tf] = tr
        pending = []

        # 2) manage open trades on this bar (intrabar, stop-first)
        for tf in TIMEFRAMES:
            tr = open_slots[tf]
            if tr is None:
                continue
            _manage_bar(tr, float(h[j]), float(l[j]), float(c[j]), day, costs, is_last=(j == n - 1))
            if tr["status"] == "closed":
                closed.append(tr)
                open_slots[tf] = None

        # 3) detect a new signal at this bar (uses its close), queue for next bar
        #    TOP100 #59 — the liquidity gate the live scan applies (scan.py:171).
        #    scan.py tests it AFTER `evaluate`; here it is tested BEFORE, purely
        #    to skip the expensive engine call on a bar that cannot produce a
        #    trade either way. The outcome is identical because turnover is a
        #    function of the frame alone: `evaluate` neither reads nor changes
        #    it, and a bar where `evaluate` would have THROWN was already a
        #    no-trade bar (the except below sets sig=None).
        #    `not (x < min)` rather than `x >= min` — they differ on NaN, and NaN
        #    is the real case (a name with no volume data). scan.py's `if
        #    turnover < liquidity_min: continue` PASSES a NaN; `>=` would have
        #    dropped it, which is a new divergence introduced by the fix for one.
        if (cand[j] and not (turnover[j] < liq_min)
                and any(open_slots[tf] is None for tf in TIMEFRAMES)):
            try:
                sig = vivek.evaluate(df.iloc[:j + 1])
            except Exception:
                sig = None
            if sig is not None:
                row, plans, grade = _build_row(sig, df.iloc[:j + 1], symbol, name, sector)
                if row and grade in ("A+", "A") and not (long_only and row["dir"] == "SHORT"):
                    for tf in TIMEFRAMES:
                        p = plans.get(tf)
                        if p and p.get("armed") and open_slots[tf] is None:
                            pending.append((tf, p, row))
    return closed


# ── aggregation ───────────────────────────────────────────────────────────────

def _risk_usd(tr: dict) -> float:
    """Report-currency dollars at risk, sized the way the live bot sizes one.

    The currency conversion (TOP100 #61, see ``fx_rates``) is applied HERE
    rather than in ``_dollars``, and that placement is the fix rather than a
    detail: ``_metrics`` multiplies this by ``mae_r`` as well, so converting one
    caller would have left the open-drawdown curve summing A$ troughs into a US$
    equity line. One conversion at the single point where a trade's local
    dollars are produced is the only version of this that cannot be half-done.

    TOP100 #69, and the reason the published dollar figures were not readable.
    This used to call ``size_position(EQUITY, tr["entry"], tr["stop"])`` — but
    ``stop`` TRAILS. ``vivek_journal._mark`` writes ``manage_position``'s moved
    stop back onto the trade (``vivek_journal.py:255``), so any trade that
    reached TP1 carries a BREAKEVEN stop, ``stop_dist`` is 0, and
    ``size_position`` returns ``risk_usd: 0.0`` — a documented, correct answer
    to a degenerate input, and the wrong question to have asked.

    The consequence, measured on the committed report rather than reasoned
    about: **842 of its 2,611 trades (32.3%) carry ``stop == entry``, every one
    of them a ``trail`` exit, and every one contributed exactly $0.00** to
    ``total_usd`` and to the drawdown curve. They are worth +113.51R between
    them. 47.9% of ALL winning trades were in that set. So the dollar column
    was not noisy or approximate — it counted the losers in full and roughly
    half the winners not at all, and ``max_dd_usd`` was a drawdown computed
    with the recoveries deleted. It is the one number on the page that looks
    like money, which is why it gets read first.

    ``entry -/+ risk`` reconstructs the ORIGINAL stop exactly: ``risk`` is
    ``abs(entry - stop)`` frozen at fill (``vivek_journal.py:184/196``) and is
    never rewritten afterwards. Same reasoning, and the same fix, as
    ``scripts/resize_book_notional.py`` — which had to solve this for the live
    book and left the note that made it findable here.
    """
    risk = tr.get("risk")
    if not risk or risk <= 0:
        # Pre-#69 records have no `risk` key. Fall back to the stored stop and
        # accept the old answer for them rather than inventing one — a merged
        # run mixing old and new slim records must not silently reprice history.
        local = size_position(EQUITY, tr["entry"], tr["stop"])["risk_usd"]
    else:
        entry = tr["entry"]
        orig_stop = entry - risk if str(tr.get("direction", "long")) == "long" else entry + risk
        local = size_position(EQUITY, entry, orig_stop)["risk_usd"]
    return local * _fx_of(tr.get("market"))


_FX: dict | None = None
_FX_PATH: pathlib.Path = OUT_FILE.parent / "fx.json"


def fx_rates() -> dict:
    """AUD→USD rate for the report, and where it came from. Memoised per process.

    TOP100 #61. Every dollar figure in this report was a SUM ACROSS MARKETS of
    numbers in two different currencies. ``_risk_usd`` sizes off the trade's own
    ``entry``, which is quoted in the market's currency, so an ASX trade's
    "usd" was A$ and a NASDAQ one's was US$ — added at face value, with the AUD
    leg overstated by 1/rate (~43% at 0.70). The R figures beside them were
    always right, because R divides by the position's own risk and the currency
    cancels; that asymmetry is why this survived so long, and it is the same one
    the live book hit on 2026-07-28 (dollar P&L moved $766 on a resize while R
    did not move at all).

    Reads the rate the SCAN already publishes rather than fetching one. That is
    not laziness about freshness — it is the only way this report and the
    journal page can be guaranteed to quote the same number, and two surfaces
    disagreeing about a conversion is worse than either being a few hours old.
    A backtest spans years anyway: a single spot rate is a convention for making
    the total addable, not a claim about what the trade was worth on the day.
    The report says so via ``source``, and ``fallback`` is a distinct value
    precisely so a reader can tell a real rate from a hard-coded one.

    Fails soft in both directions — an unreadable file and a nonsense rate land
    on the same fallback, because a mis-parsed 6969 would silently multiply the
    ASX leg by four thousand and that failure is not visibly wrong on a page.
    """
    global _FX
    if _FX is not None:
        return _FX
    rate, source = None, "fallback"
    try:
        rate = float(json.loads(_FX_PATH.read_text(encoding="utf-8")).get("audusd") or 0)
        if 0.4 < rate < 1.2:                          # same sanity band as run.py
            source = "fx.json"
        else:
            rate = None
    except Exception:
        rate = None
    _FX = {"audusd": round(rate if rate else float(config.FX_AUDUSD_FALLBACK), 4),
           "source": source, "currency": config.REPORT_CURRENCY}
    return _FX


def set_fx_path(out_file: str | pathlib.Path) -> pathlib.Path:
    """Point ``fx_rates`` at the ``fx.json`` sitting beside ``out_file``.

    ``--out`` is a FILE path, so the rate lives in its PARENT — the scan writes
    ``fx.json`` into the same ``public/data`` directory it writes every report
    into, and the two travel together. Without this a run with a non-default
    ``--out`` reads the default location, finds nothing on a fresh checkout, and
    silently reports the FALLBACK rate while stamping the payload ``"USD"``. The
    numbers would be wrong by a few percent and nothing on the page would say so
    — which is the exact failure mode #61 exists to end, reintroduced one layer
    up.

    Clearing the memo is the load-bearing half rather than tidiness: ``fx_rates``
    caches on first call, so a path set after anything has already asked for a
    rate would be accepted and ignored. Returns the new path so a caller can log
    what it actually resolved to.
    """
    global _FX, _FX_PATH
    _FX_PATH = pathlib.Path(out_file).parent / "fx.json"
    _FX = None
    return _FX_PATH


def _fx_of(market: str | None) -> float:
    """Multiplier taking ``market``'s local dollars into the report currency.

    An UNKNOWN market returns 1.0 rather than raising. That is the conservative
    choice here only because the report currency is USD and every market this
    repo has ever had is USD except one: the cost of guessing wrong is a leg
    reported ~43% high, the cost of raising is no report at all, and a merged
    file carrying a market this build does not know about is a real case
    (streamed per-market runs are merged by a later process).
    """
    mk = config.MARKETS.get(str(market))
    if mk is None or getattr(mk, "currency", config.REPORT_CURRENCY) == config.REPORT_CURRENCY:
        return 1.0
    return float(fx_rates()["audusd"])


def _dollars(tr: dict) -> float:
    return (tr.get("realized_r") or 0.0) * _risk_usd(tr)


def _exit_order(trades: list[dict]) -> list[int]:
    """Indices ordered by exit date, with a MISSING date sorted LAST.

    ``key=lambda i: t[i].get("exit_date") or ""`` sorted a missing date to the
    FRONT, where it lands before every real trade and corrupts the cumulative
    curve from its first step — the one position on the curve where a wrong
    value does the most damage, since peak and trough are both measured from
    there. ``(date is None, date)`` moves the unknowns to the end without
    disturbing the order of everything that does have a date.
    """
    return sorted(range(len(trades)),
                  key=lambda i: (not trades[i].get("exit_date"),
                                 trades[i].get("exit_date") or ""))


def _metrics(trades: list[dict]) -> dict:
    n = len(trades)
    if not n:
        return {"n": 0, "win_rate": 0.0, "avg_r": 0.0, "expectancy_r": 0.0,
                "profit_factor": None, "total_r": 0.0, "total_usd": 0.0,
                "max_dd_usd": 0.0, "max_dd_open_usd": 0.0}
    rs = [t.get("realized_r") or 0.0 for t in trades]
    ds = [_dollars(t) for t in trades]
    wins = [r for r in rs if r > 0]
    gross_win = sum(r for r in rs if r > 0)
    gross_loss = abs(sum(r for r in rs if r < 0))
    # Max drawdown on the cumulative $ curve, ordered by exit date.
    #
    # TOP100 #69, the headline half: this curve only ever moves AT AN EXIT, so a
    # position that bled for four months and then recovered to +0.2R shows as a
    # single upward step and no drawdown at all. That is not a small
    # understatement — it is the difference between a curve you could have sat
    # through and one you could not, which is the only question a drawdown
    # number is asked. `max_dd_open_usd` re-walks the same curve charging each
    # trade's worst OPEN moment (`mae_r`, which `_mark` already tracked and
    # `_SLIM_KEYS` was dropping) against the equity level it sits at.
    #
    # It is a SECOND number, not a replacement, and the docstring has to say
    # what it is not: MAE carries no timestamp, so each trade's trough is
    # charged at its exit slot rather than when it really happened, and
    # concurrent trades' troughs are therefore never summed. It understates a
    # simultaneous drawdown across many names and it is measured GROSS (MAE is
    # a price excursion; no exit costs are paid at a low that was never sold
    # into). What it does say honestly, and the realised figure cannot, is how
    # deep any single position dug before it came back.
    order = _exit_order(trades)
    cum = peak = dd = dd_open = 0.0
    for i in order:
        mae_usd = min(trades[i].get("mae_r") or 0.0, 0.0) * _risk_usd(trades[i])
        dd_open = min(dd_open, (cum + mae_usd) - peak)
        cum += ds[i]
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
        dd_open = min(dd_open, cum - peak)
    return {
        "n": n,
        "win_rate": round(100 * len(wins) / n, 1),
        "avg_r": round(sum(rs) / n, 3),
        "expectancy_r": round(sum(rs) / n, 3),
        # None (not inf): float("inf") serialises as bare `Infinity`, which is
        # not valid JSON and breaks the frontend's response.json()
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "total_r": round(sum(rs), 2),
        "total_usd": round(sum(ds), 2),
        "max_dd_usd": round(dd, 2),
        "max_dd_open_usd": round(dd_open, 2),
    }


def _split(trades: list[dict], key, values=None) -> dict:
    vals = values or sorted({t.get(key) for t in trades if t.get(key) is not None})
    return {str(v): _metrics([t for t in trades if t.get(key) == v]) for v in vals}


def aggregate(trades: list[dict]) -> dict:
    return {
        "overall": _metrics(trades),
        "by_entry_type": _split(trades, "entry_type", config.VIVEK_TRIGGER_PRIORITY),
        "by_timeframe": _split(trades, "timeframe", list(TIMEFRAMES)),
        "by_market": _split(trades, "market"),
        "by_grade": _split(trades, "grade", ["A+", "A"]),
        "by_direction": _split(trades, "direction", ["long", "short"]),
        "by_level_tf": _split(trades, "level_tf", list(LEVEL_TFS)),
    }


# ── driver ────────────────────────────────────────────────────────────────────

# Slim trade record stored in the report — enough to recompute every metric and
# to MERGE markets together across separate (streamed) runs.
# `risk` and `mae_r` added by TOP100 #69. Both were already computed and
# maintained per bar by vivek_journal (`risk` frozen at fill, `mae_r` updated by
# `_mark`) and thrown away here, which is why two defects downstream had no
# data to be fixed with: `risk` is the ORIGINAL stop distance, without which
# `_risk_usd` had to size off the trailed stop and zeroed every breakeven-
# trailed winner; `mae_r` is the only trace of what happened BETWEEN entry and
# exit, without which a drawdown curve can only step at exits.
_SLIM_KEYS = ("symbol", "market", "timeframe", "level_tf", "entry_type", "grade",
              "direction", "entry", "stop", "risk", "exit", "entry_date", "exit_date",
              "exit_reason", "realized_r", "gross_r", "cost_r", "mae_r", "sector")


def _slim(tr: dict) -> dict:
    return {k: tr.get(k) for k in _SLIM_KEYS}


def _sample(items: list[dict], limit: int | None) -> list[dict]:
    """Pick ``limit`` names spread evenly across ``items``, deterministically.

    TOP100 #58, the second half. Taking ``items[:limit]`` off an
    alphabetically-sorted directory is not a sample of the market, it is a
    sample of the letter A — on the ASX that is shells, tiny ETFs and
    numeric-prefixed codes, a population with its own liquidity and volatility
    profile, and the backtest was reporting its behaviour as the market's. An
    even stride over the same sorted list spans the alphabet instead. It is
    still not a random sample and this function does not pretend otherwise;
    what it buys is that the slice is no longer correlated with the one thing
    the sort key encodes.

    Deterministic on purpose — no RNG, no seed to remember. Two runs of the
    same universe pick the same names, so a change in the numbers is a change
    in the DATA or the ENGINE and never in who happened to be drawn. That
    matters more here than sampling purity: this report's job is to be
    comparable with last month's copy of itself.
    """
    n = len(items)
    if not limit or limit >= n:
        return items
    step = n / limit
    return [items[int(i * step)] for i in range(limit)]


def run_market_trades(mk: str, limit: int | None, period: str,
                      exclude_funds: bool = True, long_only: bool = False) -> tuple[list[dict], dict]:
    """Backtest ONE market; return (slim trades, coverage entry)."""
    from .universe import load_universe
    from .data import download

    # TOP100 #58 — was `full=False`, the BUNDLED CSV: 99 curated NASDAQ mega-caps
    # against the ~1,430 names the live scan actually walks, and the smaller
    # bundled ASX list against ~2,212. The live scan runs `full=True`, so the
    # backtest was evidence about a different, and much larger-cap, market than
    # the one being traded. Runtime is unchanged — `limit` still decides how many
    # frames get downloaded; only WHICH names, and out of what, has moved.
    uni_all = load_universe(mk, full=True)
    if exclude_funds:
        uni_all = [u for u in uni_all
                   if not _is_fund_or_reit({"name": u.get("name"), "sector": u.get("sector")})]
    uni = _sample(uni_all, limit)
    log.info("[%s] downloading %d of %d tickers (%s) ...", mk, len(uni), len(uni_all), period)
    frames = download([u["yf"] for u in uni], period=period)
    meta = {u["yf"]: u for u in uni}
    trades: list[dict] = []
    for yf, df in frames.items():
        u = meta.get(yf, {})
        try:
            trades.extend(replay_symbol(df, mk, u.get("symbol", yf), u.get("name", yf),
                                        u.get("sector", ""), long_only=long_only))
        except Exception as e:
            log.warning("[%s] %s replay error: %s", mk, yf, e)
    log.info("[%s] %d trades from %d symbols", mk, len(trades), len(uni))
    # `universe` / `sampled_pct` are the half that makes `symbols` readable. A
    # bare "symbols: 60" invites the reading "the market has 60 names in it";
    # 60 of 1,987 is the same run described honestly, and it is the number a
    # reader needs before deciding what the expectancy below is worth.
    return [_slim(t) for t in trades], {
        "symbols": len(uni), "universe": len(uni_all),
        "sampled_pct": round(100 * len(uni) / max(len(uni_all), 1), 1),
        "trades": len(trades),
    }


# ── portfolio-level simulation ───────────────────────────────────────────────
# The per-trade replay answers "does a signal have edge?"; this answers the
# question the bot actually lives with: does that edge SURVIVE slot contention
# once the book rules (slot cap, one/symbol, sector cap, cooldown) compete for
# capital? Chronological, per market, using the same rules as the live bot.
# The time stop and daily/weekly guards need intra-trade price paths the slim
# records don't carry, so they are NOT simulated (noted in the output).

def _stop_pct(tr: dict) -> float | None:
    """|entry − ORIGINAL stop| as a % of entry, or None when it is unknowable.

    Read ``risk``, never ``stop``. ``stop`` TRAILS (``vivek_journal._mark``
    writes the moved stop back onto the trade), so a trade that reached TP1
    carries a BREAKEVEN stop and ``abs(entry - stop)`` is 0 — which the gates
    below would read as a 0% stop and reject as ``stop_too_tight``. Every trade
    that trailed is a trade that went far enough to take TP1, i.e. a WINNER, so
    the fallback that looks reasonable would have deleted winners specifically
    and improved every metric it touched. ``risk`` is the distance frozen at
    fill and never rewritten, which is the number the live gate saw.

    Returns None rather than guessing for pre-#69 slim records that carry no
    ``risk`` at all. The caller does not gate those — the same treatment they
    got before #68 existed, so a merged run mixing old and new records reports
    the old population for the old half instead of silently culling its winners.
    """
    entry = tr.get("entry")
    risk = tr.get("risk")
    if not entry or entry <= 0 or not risk or risk <= 0:
        return None
    return abs(risk) / entry * 100.0


def _bot_gate(tr: dict) -> str | None:
    """Replay the live bot's pre-trade TRADEABILITY gates. Skip code, or None.

    TOP100 #68. ``not_simulated`` listed the time stop, the two loss guards and
    the ADV gates — and quietly omitted these three, which are not exotic: they
    are the reason a real book cannot take a $0.021 ASX micro-cap or a plan
    whose structural stop sits 95% from entry. The sim was therefore crediting
    the portfolio with trades the bot would have refused at the door, and doing
    it while publishing a list that read as exhaustive. An incomplete caveat is
    worse than none, because it is the thing a reader checks INSTEAD of reading
    the code.

    All three are computable from a slim record — they are functions of entry
    price and stop distance only — so the honest fix is to simulate them and
    shorten the list, not to lengthen it. What genuinely cannot be replayed
    stays out: the earnings buffer needs a historical calendar, the ADV gates
    need historical volume the slim record does not carry, and both guards need
    intra-trade price paths.

    Gate ORDER mirrors ``vivek_bot`` exactly — the two stop-distance tests in
    ``evaluate_setup``, then ``min_price`` in ``plan_trade`` — so a trade that
    fails two of them is attributed to the same one the live log would name.

    ``min_price`` reads ``entry`` where the live gate reads the row's scan-time
    ``price``. They are not the same field and the difference is deliberate: a
    slim record has no scan-time price, and the question the floor asks — "is
    this fillable at a price whose spread is not worth multiple R" — is a
    question about the price you TRANSACT at, which in this replay is the entry.
    """
    pct = _stop_pct(tr)
    if pct is not None:
        hi = float(getattr(config, "VIVEK_BOT_MAX_STOP_PCT", 0) or 0)
        if hi > 0 and pct > hi:
            return "wide_stop"
        lo = float(getattr(config, "VIVEK_BOT_MIN_STOP_PCT", 0) or 0)
        if lo > 0 and pct < lo:
            return "stop_too_tight"
    floors = getattr(config, "VIVEK_BOT_MIN_PRICE", None) or {}
    floor = float(floors.get(tr.get("market"), floors.get("default", 0)) or 0)
    entry = float(tr.get("entry") or 0)
    if floor > 0 and 0 < entry < floor:
        return "min_price"
    return None


def portfolio_sim(trades: list[dict]) -> dict:
    from collections import Counter
    from .broker.vivek_bot import _sector_key

    skip_types = set(getattr(config, "VIVEK_BOT_SKIP_ENTRY_TYPES", ()) or ())
    long_only = not getattr(config, "VIVEK_BOT_ALLOW_SHORTS", True)
    # Slot count. The live book's binding constraint is now a GLOBAL cap shared
    # across markets (VIVEK_BOT_MAX_OPEN_TOTAL), but this sim runs one market at
    # a time and structurally cannot model cross-market contention. Using the
    # per-market cap (equal to the global one) would let each of 3 markets fill
    # a whole book and overstate how many trades the real book can carry, so the
    # sim gets that market's AVERAGE share of the shared cap instead. A market
    # that wins contention can hold more than this live; the sim is deliberately
    # the conservative reading, and it keeps these numbers comparable with the
    # published history from when the cap really was per-market.
    max_pos = config.VIVEK_BOT_MAX_POSITIONS
    _total_cap = int(getattr(config, "VIVEK_BOT_MAX_OPEN_TOTAL", 0) or 0)
    if _total_cap:
        max_pos = min(max_pos, max(1, _total_cap // max(len(config.MARKETS), 1)))
    max_sector = int(getattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 0) or 0)
    cooldown = int(getattr(config, "VIVEK_BOT_REENTRY_COOLDOWN_DAYS", 0) or 0)

    # TOP100 #68 — the tradeability gates run HERE, in the eligibility filter,
    # because that is where they run live: `evaluate_setup` and `plan_trade`
    # both reject before a slot is ever considered. So they shrink `eligible`
    # too, not just `portfolio` — `eligible` means "every signal the bot would
    # have been willing to take", and a 95%-stop plan was never one of those.
    gate_skips: Counter = Counter()
    ungated = 0
    elig = []
    for t in trades:
        if (t.get("grade") != "A+" or t.get("entry_type") in skip_types
                or (long_only and t.get("direction") != "long")
                or not t.get("entry_date") or not t.get("exit_date")):
            continue
        code = _bot_gate(t)
        if code:
            gate_skips[code] += 1
            continue
        if not t.get("risk"):
            # Counted, not hidden: a record with no `risk` skipped the two
            # stop-distance gates entirely (see `_stop_pct`). A non-zero number
            # here means part of this population is reported on the OLD rules.
            ungated += 1
        elig.append(t)
    if not elig:
        return {"note": "no bot-eligible trades with entry dates (re-run the "
                        "backtest to regenerate trades with entry_date)",
                "eligible": _metrics([]), "portfolio": _metrics([])}

    def add_days(day: str, n: int) -> str:
        return (dt.date.fromisoformat(day) + dt.timedelta(days=n)).isoformat()

    taken_all: list[dict] = []
    skips: Counter = Counter()
    peak_open = 0
    for mk in sorted({t["market"] for t in elig}):
        # Weekly first on ties — mirrors the bot's prefer_tf ordering.
        trs = sorted((t for t in elig if t["market"] == mk),
                     key=lambda t: (t["entry_date"],
                                    0 if t.get("timeframe") == "1W" else 1))
        open_pos: list[dict] = []
        open_syms: set = set()
        sector_count: Counter = Counter()
        cooldown_until: dict = {}
        for t in trs:
            day = t["entry_date"]
            still = []
            for p in open_pos:                       # free slots exited BEFORE today
                if p["exit_date"] < day:
                    open_syms.discard(p["symbol"])
                    sk = _sector_key(p["symbol"], p.get("sector"), mk)
                    if sk:
                        sector_count[sk] -= 1
                    if cooldown and p.get("exit_reason") == "stop":
                        cooldown_until[p["symbol"]] = add_days(p["exit_date"], cooldown)
                else:
                    still.append(p)
            open_pos = still
            sym, sk = t["symbol"], _sector_key(t["symbol"], t.get("sector"), mk)
            if sym in open_syms:
                skips["dup_symbol"] += 1
            elif cooldown_until.get(sym, "") >= day:
                skips["cooldown"] += 1
            elif len(open_pos) >= max_pos:
                skips["book_full"] += 1
            elif max_sector and sk and sector_count[sk] >= max_sector:
                skips["sector_cap"] += 1
            else:
                open_pos.append(t)
                open_syms.add(sym)
                if sk:
                    sector_count[sk] += 1
                taken_all.append(t)
                peak_open = max(peak_open, len(open_pos))

    return {
        "params": {"max_positions": max_pos, "max_per_sector": max_sector,
                   "cooldown_days": cooldown, "long_only": long_only,
                   "skip_entry_types": sorted(skip_types),
                   # Say what IS replayed, not only what is not — a bare
                   # "not_simulated" list invites the reader to assume
                   # everything absent from it was modelled, which is the
                   # assumption #68 was about.
                   "simulated_gates": ["min_price", "max_stop_pct", "min_stop_pct",
                                       "max_positions", "one_per_symbol",
                                       "max_per_sector", "reentry_cooldown"],
                   "not_simulated": ["time_stop", "daily_guard", "weekly_guard",
                                     "earnings_buffer (no historical calendar)",
                                     "adv_gates (no historical ADV)",
                                     "cross_market_contention (one market at a time)"]},
        "eligible": _metrics(elig),          # unconstrained: every bot-eligible signal
        "portfolio": _metrics(taken_all),    # what the book rules actually let through
        "taken": len(taken_all), "skipped": dict(skips), "peak_open": peak_open,
        # Rejected at the door by `_bot_gate`, before slot contention. Kept
        # apart from `skipped` on purpose: these are trades the bot would never
        # have wanted, `skipped` are trades it wanted and had no room for, and
        # summing them would answer neither question.
        "gated": dict(gate_skips), "gated_unknown_stop": ungated,
    }


def build_report(trades: list[dict], coverage: dict, params: dict, status: str) -> dict:
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,                                  # "partial" while streaming, "complete" when done
        # TOP100 #61 — every `*_usd` figure below is in this currency, converted
        # at this rate. Published rather than assumed: a total that silently
        # changed units between report versions would be unreadable next to last
        # month's copy, which is the one comparison this file exists to support.
        "currency": config.REPORT_CURRENCY,
        "fx": fx_rates(),
        "params": params,
        "coverage": coverage,
        "results": aggregate(trades),
        "portfolio": portfolio_sim(trades),
        "trades": trades,
        "caveats": [
            "Survivorship bias — today's universe excludes delisted names.",
            "yfinance daily data (dividend-adjusted); occasional gaps.",
            "Intrabar fills assume the stop fills before the target within a bar.",
            "A+ setups are rare, so trade counts (N) can be small and noisy.",
            "4H is not backtested (no deep intraday history).",
            "Dollar columns (total_usd, max_dd_usd) are priced under "
            "params.sizing_mode and are NOT comparable across runs that "
            "changed it — a switch between risk-% and fixed-notional moves "
            "them by an order of magnitude on identical trades. Read total_r "
            "and expectancy_r, which are ratios and carry across.",
            "Portfolio sim: the slot/symbol/sector/cooldown caps and the "
            "price + stop-distance gates ARE replayed; the time stop, the "
            "daily/weekly loss guards, the earnings buffer and the ADV gates "
            "are not (no intra-trade price paths, earnings calendar or "
            "historical volume in the slim records), and it runs one market at "
            "a time so cross-market slot contention is not modelled.",
        ],
    }


def run_backtest(markets: list[str], limit: int | None, period: str,
                 exclude_funds: bool = True, long_only: bool = False) -> dict:
    """Backtest several markets in one process (no streaming)."""
    trades, coverage = [], {}
    for mk in markets:
        tr, cov = run_market_trades(mk, limit, period, exclude_funds, long_only)
        trades += tr
        coverage[mk] = cov
    params = {"markets": markets, "limit": limit, "period": period,
              "exclude_funds": exclude_funds, "long_only": long_only,
              **_sizing_basis(),
              "intrabar": "pessimistic (stop-first)", "timeframes": list(TIMEFRAMES)}
    return build_report(trades, coverage, params, "complete")


def _print(report: dict) -> None:
    r = report["results"]
    def line(label, m):
        pf = "inf" if m["profit_factor"] is None else f"{m['profit_factor']:.2f}"
        print(f"  {label:<14} n={m['n']:<4} win {m['win_rate']:>5}%  "
              f"avgR {m['avg_r']:+.2f}  exp {m['expectancy_r']:+.2f}R  "
              f"PF {pf:<5} totR {m['total_r']:+.1f}  ${m['total_usd']:+.0f}  maxDD ${m['max_dd_usd']:.0f}")
    print("\n=== VIVEK 5.0 BACKTEST ===")
    # TOP100 #61 — the console is the surface with no schema, so the units have
    # to be said in words: every `$` below is a converted total, not a native
    # one. `source` is printed rather than only the rate because "0.66 fallback"
    # and "0.66 fx.json" are the same number meaning different things, and the
    # fallback case is the one where the ASX leg may be several percent out with
    # nothing else on screen to hint at it. ASCII only (project rule 9).
    fx = report.get("fx") or {}
    if fx:
        note = " (published rate)" if fx.get("source") == "fx.json" else " (FALLBACK - no fx.json read)"
        print(f"currency: all $ figures are {report.get('currency', '?')} "
              f"@ AUDUSD {fx.get('audusd')}{note}")
    print("params:", report["params"])
    print("coverage:", report["coverage"])
    print("\nOVERALL"); line("overall", r["overall"])
    for grp in ("by_entry_type", "by_timeframe", "by_level_tf", "by_market", "by_grade", "by_direction"):
        print(f"\n{grp.upper()}")
        for k, m in r[grp].items():
            if m["n"]:
                line(k, m)
    port = report.get("portfolio") or {}
    if port.get("portfolio", {}).get("n"):
        print("\nPORTFOLIO (bot book rules applied chronologically)")
        line("eligible", port["eligible"])
        line("portfolio", port["portfolio"])
        print(f"  taken {port['taken']} · peak open {port['peak_open']} · "
              f"skips {port['skipped'] or 'none'}")
    elif port.get("note"):
        print(f"\nPORTFOLIO: {port['note']}")


def main() -> None:
    ap = argparse.ArgumentParser(description="VIVEK 5.0 walk-forward backtest")
    ap.add_argument("--market", action="append", choices=[*config.MARKETS, "all"])
    ap.add_argument("--limit", type=int, default=60, help="max symbols per market (0 = all)")
    ap.add_argument("--period", default="10y", help="yfinance history period (e.g. 10y, max)")
    ap.add_argument("--include-funds", action="store_true", help="don't exclude REITs/ETFs/funds")
    ap.add_argument("--long-only", action="store_true", help="skip short setups (long-only system)")
    ap.add_argument("--merge", action="store_true",
                    help="merge this run's market(s) into the existing results file (streaming)")
    ap.add_argument("--status", choices=["partial", "complete"],
                    help="override the report status (default: auto)")
    ap.add_argument("--out", default=str(OUT_FILE))
    # Parity mode (n≥30 decision pack): exact live lifecycle + variant grid.
    # Simulation only — does not touch vivek_bot.py / the live book rules.
    ap.add_argument("--parity", action="store_true",
                    help="replay the LIVE bot lifecycle (A+/long-only/time-stop/ADV/"
                         "global slots) and run the V1–V4 variant grid; writes "
                         "public/data/vivek_backtest_parity.json by default")
    ap.add_argument("--no-variants", action="store_true",
                    help="with --parity: skip the variant grid (baseline only)")
    ap.add_argument("--exclude-from", default=None,
                    help="with --parity: JSON path of {market:[symbols]} to exclude "
                         "(for out-of-sample runs disjoint from a prior sample)")
    ap.add_argument("--sample-out", default=None,
                    help="with --parity: write this run's sampled symbols JSON "
                         "(for later --exclude-from)")
    ap.add_argument("--tag", default="parity",
                    help="with --parity: mode/tag stamp on the report "
                         "(e.g. parity_oos)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    markets = list(config.MARKETS) if (not args.market or "all" in args.market) else args.market

    if args.parity:
        from . import vivek_parity as parity
        # Default out/period for parity differ from the Insights walk-forward.
        if args.out == str(OUT_FILE):
            default_name = ("public/data/vivek_backtest_parity_oos.json"
                            if args.exclude_from else
                            getattr(config, "VIVEK_PARITY_OUT_FILE",
                                    "public/data/vivek_backtest_parity.json"))
            out = ROOT / default_name
        else:
            out = pathlib.Path(args.out)
        period = args.period
        if period == "10y":
            # argparse default is 10y; parity default is the config knob (5y).
            period = getattr(config, "VIVEK_PARITY_DEFAULT_PERIOD", "5y")
        set_fx_path(out)
        excl = parity.load_exclude_map(args.exclude_from) if args.exclude_from else None
        tag = args.tag or ("parity_oos" if args.exclude_from else "parity")
        report = parity.run_parity(markets, args.limit or None, period,
                                   run_variants=not args.no_variants,
                                   exclude_map=excl, tag=tag)
        parity.print_parity(report)
        out.parent.mkdir(parents=True, exist_ok=True)
        output.write_json(out, report)
        if args.sample_out:
            sample_path = pathlib.Path(args.sample_out)
            sample_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "generated_at": report.get("generated_at"),
                "tag": tag,
                "params": {"limit": args.limit or None, "period": period,
                           "markets": list(markets)},
                "by_market": report.get("sampled_symbols") or {},
            }
            output.write_json(sample_path, payload)
            print(f"wrote sample map {sample_path}")
        print(f"\nwrote {out}  (parity complete, markets: {sorted(report.get('coverage', {}))})")
        return

    out = pathlib.Path(args.out)
    # TOP100 #61 — before ANY report is built, so the memo cannot be primed from
    # the default location by a stray earlier call. See `set_fx_path`.
    set_fx_path(out)

    # Carry over trades/coverage for OTHER markets from a previous (streamed) run.
    prior_trades, coverage = [], {}
    if args.merge and out.exists():
        try:
            prev = json.loads(out.read_text())
            prior_trades = [t for t in prev.get("trades", []) if t.get("market") not in markets]
            coverage = {k: v for k, v in prev.get("coverage", {}).items() if k not in markets}
        except Exception as e:
            log.warning("could not read prior results (%s) — starting fresh", e)

    new_trades = []
    for mk in markets:
        tr, cov = run_market_trades(mk, args.limit or None, args.period,
                                    not args.include_funds, args.long_only)
        new_trades += tr
        coverage[mk] = cov

    trades = prior_trades + new_trades
    done = set(coverage)
    status = args.status or ("complete" if done >= set(config.MARKETS) else "partial")
    params = {"markets": sorted(done), "limit": args.limit or None, "period": args.period,
              "exclude_funds": not args.include_funds, "long_only": args.long_only,
              **_sizing_basis(),
              "intrabar": "pessimistic (stop-first)", "timeframes": list(TIMEFRAMES)}
    report = build_report(trades, coverage, params, status)
    _print(report)
    out.parent.mkdir(parents=True, exist_ok=True)
    # TOP100 #62/#64 — was `out.write_text(json.dumps(report, indent=2))`, which
    # was non-atomic AND took the platform's locale encoding rather than utf-8.
    # This report is the Insights page's proof-of-edge source and the run before
    # it takes hours, so a truncated file here costs a week.
    output.write_json(out, report)
    print(f"\nwrote {out}  (status={status}, markets done: {sorted(done)})")


if __name__ == "__main__":
    main()
