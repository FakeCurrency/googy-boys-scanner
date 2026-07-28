"""REGIME -- what the tape is doing underneath the index, and who is leading it.

WHY THIS EXISTS (2026-07-28, the second half of the July post-mortem). HORIZON
answers "which sector is setting up TODAY, and do I hold any of it". It cannot
answer the two questions the owner actually asked after missing four weeks of
ASX consumer discretionaries:

  1. "The market has been SHIT to trade yet consumer discretionaries went up."
     Both halves of that sentence were true at once and the system could not
     represent it, because the only market-wide number anywhere was the index
     print. An index is roughly twenty names in a trench coat: on the ASX,
     BHP/CBA/CSL move XJO while four hundred mid-caps do something else
     entirely. `median_ret21` is the equal-weight answer -- what the MEDIAN name
     did -- and the gap between it and the index is the divergence he lived
     through, stated as a number instead of a feeling.

  2. "What can I probe so I don't miss an entire sector running again?" A
     participation rate is an absolute measure: it says how many names in a
     sector are setting up, never whether that sector is doing better than the
     rest of the market. A system with no relative frame literally cannot
     represent the sentence "consumer discretionaries are outperforming", which
     is the sentence that describes a rotation. `rs21`/`rs63` are that frame --
     the sector's median return minus the market's median return, over one and
     three months.

AND THE ONE THAT SEES IT EARLY. `near`/`at` count the names SITTING at their
200-day average without having triggered yet. Every VIVEK setup is drawn from
that pool -- `evaluate()` discards anything further than VIVEK_NEAR_TOL from the
level before it looks at anything else -- so the pool is the setup count's
leading indicator by construction. A sector whose basing count is climbing while
its setup count is still zero is a sector about to start printing setups.

WHY THIS NEEDS NO BACKFILL, WHICH IS THE POINT. Everything here is arithmetic on
daily closes, so a run computes the full six-month series from scratch every
time. HORIZON had to start remembering on the day it shipped and is useful
around Christmas; this is useful on its first run, and it can answer "how long
has that been true" about JUNE -- the month that was actually missed. There is
no state file, so there is nothing to corrupt, re-run wrong, or backfill.

THE HONEST CAVEATS, both stated on the page rather than buried here:
  * SURVIVORSHIP. The universe is today's listed names. A company delisted in
    May is absent from May's numbers, which flatters every historical reading
    slightly. Unavoidable without a point-in-time universe feed.
  * The benchmark leg is a single index download and is allowed to fail; when
    it does, the breadth lines still publish and the divergence simply is not
    claimed.

REPORT-ONLY, exactly like sectorbreadth: imported by scanner/run.py alone, never
by broker/. Nothing here reaches a trade decision. Wiring any of these numbers
into `decide()` changes which trades get taken and is the owner's call.

    python -m scanner.regime --market asx      # recompute from a live download
"""

import argparse
import datetime as dt
import json
import pathlib

import numpy as np
import pandas as pd

from . import config, output

ROOT = pathlib.Path(__file__).resolve().parents[1]
PUBLIC_FILE = ROOT / "public" / "data" / "regime.json"

SCHEMA_VERSION = 1

# Buckets that are the ABSENCE of a sector wearing a sector's clothes. Same list
# and same reason as sectorbreadth._NOT_A_SECTOR: 389 of the 2,212 ASX names
# carry "Unclassified", and a big undifferentiated bucket will always look like
# a trend because it is really an average of the whole market. Kept in sync
# deliberately -- if the two surfaces disagreed about what a sector is, they
# would disagree about who is leading.
_NOT_A_SECTOR = {"unclassified", "unknown", "n/a", "na", "none", "other",
                 "miscellaneous", "not applicable"}


def _norm(sector) -> str:
    return " ".join(str(sector or "").strip().split()).lower()


def _r(x, nd=4):
    """Round for publication, mapping every non-finite value to None.

    JSON has no NaN. `json.dumps` will happily emit a bare `NaN` token, which
    every browser's JSON.parse rejects -- one thin sector with no median would
    take the whole page down rather than showing one blank cell.
    """
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if np.isfinite(v) else None


def _series(s: pd.Series, nd=4) -> list:
    return [_r(v, nd) for v in s.tolist()]


def _counts(s: pd.Series) -> list:
    return [int(v) if np.isfinite(v) else 0 for v in s.tolist()]


def _dates(index) -> pd.DatetimeIndex:
    """A tz-naive session-date index, whatever timezone came in.

    Yahoo returns tz-AWARE indexes for some tickers and naive ones for others in
    the same batch, and pandas will not align the two -- the result is not an
    error, it is a matrix twice as tall as it should be with every row half
    empty, which reads downstream as "half the market had no data".

    The timezone is dropped by taking LOCAL WALL TIME, never by converting to
    UTC first. A daily ASX bar is stamped midnight Australia/Sydney; converting
    that to UTC gives 13:00 the PREVIOUS day, so a UTC round-trip would move
    every ASX session back one calendar date and misalign it against the
    tz-naive frames in the cache -- the exact failure this function exists to
    prevent, introduced by the fix for it.
    """
    idx = pd.DatetimeIndex(index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return idx.normalize()


# -- the aligned price matrix -------------------------------------------------

def close_matrix(frames: dict, universe: list, rows: int = 0):
    """One wide Close frame for a whole market, plus yf-ticker -> sector.

    Columns are keyed by yfinance ticker rather than display symbol because that
    is what `frames` is keyed by and it is unique by construction; two universe
    rows sharing a display symbol would otherwise silently collide into one
    column and be counted once.

    Indexes are normalised to tz-naive dates before the join. Yahoo hands back
    tz-aware indexes for some tickers and naive ones for others in the same
    batch, and pandas will not align the two -- the result is not an error, it
    is a matrix twice as tall as it should be with every row half empty, which
    reads downstream as "half the market had no data that day".
    """
    cols, sector_of = {}, {}
    for u in (universe or []):
        yft = u.get("yf")
        df = (frames or {}).get(yft)
        if df is None or "Close" not in getattr(df, "columns", []) or not len(df):
            continue
        s = df["Close"]
        try:
            s = pd.Series(s.to_numpy(dtype="float64"), index=_dates(s.index))
        except Exception:                                   # noqa: BLE001
            continue
        s = s[~s.index.duplicated(keep="last")]
        cols[yft] = s
        sector_of[yft] = u.get("sector") or ""
    if not cols:
        return pd.DataFrame(), {}
    closes = pd.concat(cols, axis=1, sort=False).sort_index()
    if rows and len(closes) > rows:
        closes = closes.iloc[-rows:]
    return closes, sector_of


def _trading_days(closes: pd.DataFrame) -> pd.DataFrame:
    """Drop pseudo-sessions: dates where almost nothing traded.

    A union index over two thousand tickers picks up every stray bar Yahoo has
    ever mis-dated, plus half-days and the odd foreign holiday, and each one
    would land in the series as a day the whole market vanished.
    """
    if closes.empty:
        return closes
    have = closes.notna().sum(axis=1)
    floor = float(getattr(config, "REGIME_MIN_DAY_COVERAGE", 0.5) or 0) * float(have.max())
    return closes[have >= floor]


# -- the per-market computation ----------------------------------------------

def compute(market: str, frames: dict, universe: list, bench=None,
            days: int = 0) -> dict:
    """Everything this module knows about one market, as publishable JSON.

    Series run oldest-first and are aligned to a single `days` axis so the front
    end can plot any of them against any other without carrying alignment logic.
    """
    days = int(days or getattr(config, "REGIME_DAYS", 126) or 126)
    w_fast, w_slow = (getattr(config, "REGIME_RET_WINDOWS", (21, 63)) or (21, 63))[:2]
    hl = int(getattr(config, "REGIME_HL_WINDOW", 20) or 20)
    sma_fast = int(getattr(config, "REGIME_FAST_SMA", 50) or 50)
    sma_slow = int(getattr(config, "VIVEK_SMA", 200) or 200)
    near_tol = float(getattr(config, "VIVEK_NEAR_TOL", 0.04) or 0.04)
    at_tol = float(getattr(config, "VIVEK_AT_LEVEL_TOL", 0.02) or 0.02)
    min_names = int(getattr(config, "SECTOR_BREADTH_MIN_NAMES", 15) or 0)
    top_n = int(getattr(config, "REGIME_TOP_N", 3) or 3)

    # Only ever load the tail the windows need. The slow SMA is the long pole:
    # `days` publishable sessions need `days + sma_slow` bars behind them, and a
    # rolling mean over a tail slice is identical to one over the whole frame
    # once that many bars are present. Cuts the working set from ~22MB a matrix
    # to ~7MB, which matters because there are eight of them.
    closes, sector_of = close_matrix(frames, universe,
                                     rows=days + sma_slow + max(w_slow, hl) + 5)
    closes = _trading_days(closes)
    # Published so the page can SAY what it is showing -- "top 3 on one-month
    # relative strength", "within 4% of the 200-day" -- instead of hard-coding
    # numbers that would silently drift out of sync with config.
    windows = {"fast": w_fast, "slow": w_slow, "hl": hl,
               "sma_fast": sma_fast, "sma_slow": sma_slow,
               "near_tol": near_tol, "at_tol": at_tol, "top_n": top_n}
    if closes.empty or len(closes) < sma_slow + 2:
        # Every key the populated shape has, so `report()`, `notes()` and the
        # front end can read a data-less market without a single guard. A new
        # market on its first week has fewer than 200 bars and lands here; the
        # cost of not doing this is a KeyError on a page that should say
        # "not enough history yet".
        return {"market": market, "days": [], "universe_size": len(universe or []),
                "covered": 0, "bench": "", "n": [], "above200": [], "above50": [],
                "hi20": [], "lo20": [], "net_hl": [], "median_ret21": [],
                "median_ret63": [], "bench_ret21": [], "sectors": {}, "leaders": [],
                "windows": windows,
                "latest": {"day": None, "n": None, "above200": None, "above50": None,
                           "hi20": None, "lo20": None, "net_hl": None,
                           "median_ret21": None, "bench_ret21": None,
                           "divergence": None, "state": "UNKNOWN"},
                "notes": []}

    slow = closes.rolling(sma_slow, min_periods=sma_slow).mean()
    fast = closes.rolling(sma_fast, min_periods=sma_fast).mean()
    ret_f = closes / closes.shift(w_fast) - 1.0
    ret_s = closes / closes.shift(w_slow) - 1.0
    gap = (closes - slow).abs() / closes
    # The pre-setup pool, defined by the ENGINE's own gates rather than a new
    # number invented here: `evaluate()` throws away anything further than
    # VIVEK_NEAR_TOL from the level before it considers direction, reaction or
    # structure, so "near" is precisely the set of names that are eligible to
    # become a setup and "at" is the tighter set that scores the AT THE LEVEL
    # point. Counting them is counting the fuel, one step ahead of the fire.
    near = gap <= near_tol
    at_lvl = gap <= at_tol
    hi = closes >= closes.rolling(hl, min_periods=hl).max()
    lo = closes <= closes.rolling(hl, min_periods=hl).min()

    has_slow = closes.notna() & slow.notna()
    has_fast = closes.notna() & fast.notna()
    n_slow = has_slow.sum(axis=1)
    n_fast = has_fast.sum(axis=1)
    n_any = closes.notna().sum(axis=1)

    frame = pd.DataFrame({
        "n": n_any,
        # Denominators are the names that HAVE the average that day, not every
        # name with a price. A recent listing has no 200-day average and is
        # neither above nor below it; counting it in the denominator alone would
        # drag participation down by the size of the IPO tail.
        "above200": ((closes > slow) & has_slow).sum(axis=1) / n_slow.replace(0, np.nan),
        "above50": ((closes > fast) & has_fast).sum(axis=1) / n_fast.replace(0, np.nan),
        "hi20": (hi & closes.notna()).sum(axis=1) / n_any.replace(0, np.nan),
        "lo20": (lo & closes.notna()).sum(axis=1) / n_any.replace(0, np.nan),
        "med_f": ret_f.median(axis=1),
        "med_s": ret_s.median(axis=1),
    })
    frame["net_hl"] = frame["hi20"] - frame["lo20"]

    axis = frame.index[-days:]
    frame = frame.loc[axis]

    # The benchmark leg: the cap-weighted index the owner actually watches, over
    # the SAME window as the equal-weight median, so the two are subtractable.
    bench_f = pd.Series(np.nan, index=axis)
    bench_sym = (getattr(config, "REGIME_BENCHMARK", {}) or {}).get(market) or ""
    if bench is not None and len(bench):
        try:
            b = bench["Close"] if hasattr(bench, "columns") else bench
            b = pd.Series(np.asarray(b, dtype="float64"), index=_dates(b.index))
            b = b[~b.index.duplicated(keep="last")].sort_index()
            bench_f = (b / b.shift(w_fast) - 1.0).reindex(axis)
        except Exception:                                   # noqa: BLE001
            bench_f = pd.Series(np.nan, index=axis)

    # -- per sector -----------------------------------------------------------
    groups: dict[str, list] = {}
    listed: dict[str, int] = {}
    for u in (universe or []):
        key = _norm(u.get("sector"))
        if not key or key in _NOT_A_SECTOR:
            continue
        name = " ".join(str(u.get("sector")).strip().split())
        listed[name] = listed.get(name, 0) + 1
        if u.get("yf") in sector_of:
            groups.setdefault(name, []).append(u["yf"])

    sectors: dict[str, dict] = {}
    for name, cols in groups.items():
        if listed.get(name, 0) < min_names:
            continue
        s_f = ret_f[cols].median(axis=1).loc[axis]
        s_s = ret_s[cols].median(axis=1).loc[axis]
        sectors[name] = {
            "names": listed.get(name, 0),
            "covered": len(cols),
            # RELATIVE, not absolute. The sector's median name against the whole
            # market's median name -- the frame in which "consumer
            # discretionaries are running while the market is not" is a single
            # number rather than two impressions that have to be held at once.
            "rs21": _series(s_f - frame["med_f"]),
            "rs63": _series(s_s - frame["med_s"]),
            "ret21": _series(s_f),
            "ret63": _series(s_s),
            "near": _counts(near[cols].sum(axis=1).loc[axis]),
            "at": _counts(at_lvl[cols].sum(axis=1).loc[axis]),
        }

    # Rank on the most recent session, and count how long that rank has held.
    ranked = sorted(
        [(v["rs21"][-1], name) for name, v in sectors.items()
         if v["rs21"] and v["rs21"][-1] is not None],
        key=lambda t: (-t[0], t[1]))
    for i, (_, name) in enumerate(ranked, 1):
        sectors[name]["rank"] = i
    for name, v in sectors.items():
        v.setdefault("rank", None)
        v["streak"] = rs_streak(sectors, name, top_n)
        v["latest"] = {"rs21": v["rs21"][-1] if v["rs21"] else None,
                       "rs63": v["rs63"][-1] if v["rs63"] else None,
                       "ret21": v["ret21"][-1] if v["ret21"] else None,
                       "ret63": v["ret63"][-1] if v["ret63"] else None,
                       "near": v["near"][-1] if v["near"] else 0,
                       "at": v["at"][-1] if v["at"] else 0,
                       "near_rate": _r((v["near"][-1] / v["names"])
                                       if v["near"] and v["names"] else None)}

    out = {
        "market": market,
        "days": [d.strftime("%Y-%m-%d") for d in axis],
        "universe_size": len(universe or []),
        "covered": int(closes.shape[1]),
        "bench": bench_sym,
        "n": _counts(frame["n"]),
        "above200": _series(frame["above200"]),
        "above50": _series(frame["above50"]),
        "hi20": _series(frame["hi20"]),
        "lo20": _series(frame["lo20"]),
        "net_hl": _series(frame["net_hl"]),
        "median_ret21": _series(frame["med_f"]),
        "median_ret63": _series(frame["med_s"]),
        "bench_ret21": _series(bench_f),
        "sectors": sectors,
        "leaders": [name for _, name in ranked[:top_n]],
        "windows": windows,
    }
    out["latest"] = latest(out)
    out["notes"] = notes(out)
    return out


def latest(blk: dict) -> dict:
    """The last session of every series, plus the two derived reads."""
    def last(key):
        seq = blk.get(key) or []
        return seq[-1] if seq else None

    a200, med, ben = last("above200"), last("median_ret21"), last("bench_ret21")
    div = None if (med is None or ben is None) else _r(med - ben)
    return {"day": (blk.get("days") or [None])[-1],
            "n": last("n"), "above200": a200, "above50": last("above50"),
            "hi20": last("hi20"), "lo20": last("lo20"), "net_hl": last("net_hl"),
            "median_ret21": med, "bench_ret21": ben, "divergence": div,
            "state": state(a200, last("net_hl"))}


def state(above200, net_hl) -> str:
    """A three-way read of participation. Deliberately coarse.

    Two numbers, both breadth: how much of the market is in an uptrend at all,
    and whether names are making new highs or new lows right now. A finer scale
    would imply a precision that a count of names above a moving average does
    not have.
    """
    on = float(getattr(config, "REGIME_RISK_ON_ABOVE200", 0.55) or 0.55)
    off = float(getattr(config, "REGIME_RISK_OFF_ABOVE200", 0.35) or 0.35)
    if above200 is None:
        return "UNKNOWN"
    if above200 >= on and (net_hl is None or net_hl >= 0):
        return "BROAD"
    if above200 <= off or (net_hl is not None and net_hl <= -0.05):
        return "NARROW"
    return "MIXED"


def rs_streak(sectors: dict, sector: str, top_n: int = 0) -> int:
    """Consecutive most-recent sessions this sector has been top-N on rs21.

    The number the July miss needed and no surface could produce: not "consumer
    discretionaries are strong today" but "consumer discretionaries have been in
    the top three for thirty-one straight sessions". Available on the FIRST run
    because the whole series is recomputed from bars, which is the entire
    argument for measuring rotation with arithmetic rather than with memory.
    """
    top_n = int(top_n or getattr(config, "REGIME_TOP_N", 3) or 3)
    names = list(sectors)
    if sector not in names:
        return 0
    length = min((len(sectors[n]["rs21"]) for n in names), default=0)
    n = 0
    for i in range(length - 1, -1, -1):
        col = [(sectors[nm]["rs21"][i], nm) for nm in names
               if sectors[nm]["rs21"][i] is not None]
        if not col:
            break
        col.sort(key=lambda t: (-t[0], t[1]))
        if sector not in [nm for _, nm in col[:top_n]]:
            break
        n += 1
    return n


def notes(blk: dict) -> list:
    """Plain sentences. The page prints these verbatim, so they carry the whole
    reading -- a number nobody interprets is a number nobody acts on."""
    out, lat = [], blk.get("latest") or {}
    win = blk.get("windows") or {}
    secs = blk.get("sectors") or {}
    pct = lambda v: f"{100 * v:.0f}%"                       # noqa: E731
    sgn = lambda v: f"{100 * v:+.1f}%"                      # noqa: E731

    # THE July sentence: the index and the median name disagreeing. This is the
    # one reading the owner had to feel rather than read, and the one that made
    # a genuinely tradeable month look like an untradeable one.
    div_min = float(getattr(config, "REGIME_DIVERGENCE_MIN", 0.02) or 0.02)
    med, ben, div = lat.get("median_ret21"), lat.get("bench_ret21"), lat.get("divergence")
    if div is not None and abs(div) >= div_min:
        if div > 0:
            out.append(f"The median name is {sgn(med)} over the last month while "
                       f"{blk.get('bench') or 'the index'} is {sgn(ben)} - the tape "
                       f"is {sgn(div)} better than the index makes it look.")
        else:
            out.append(f"{blk.get('bench') or 'The index'} is {sgn(ben)} over the last "
                       f"month while the median name is only {sgn(med)} - the index is "
                       f"being carried by its biggest names.")

    a200 = lat.get("above200")
    if a200 is not None:
        seq = [v for v in (blk.get("above200") or []) if v is not None]
        prior = seq[-22] if len(seq) >= 22 else None
        move = "" if prior is None else (
            f", up from {pct(prior)} a month ago" if a200 - prior > 0.02 else
            f", down from {pct(prior)} a month ago" if prior - a200 > 0.02 else
            f", flat on a month ago")
        out.append(f"{pct(a200)} of names are above their "
                   f"{win.get('sma_slow', 200)}-day average{move}. New "
                   f"{win.get('hl', 20)}-day highs minus lows: "
                   f"{sgn(lat.get('net_hl') or 0)} of the market.")

    # Who is leading, and for how long. The streak is what turns a leaderboard
    # into a warning -- a sector can top one session's ranking on noise, and no
    # sector tops thirty of them by accident.
    for name in (blk.get("leaders") or [])[:1]:
        v = secs.get(name) or {}
        rs, run = (v.get("latest") or {}).get("rs21"), v.get("streak") or 0
        if rs is None:
            continue
        out.append(f"{name} leads on relative strength at {sgn(rs)} against the market "
                   f"median over the last month"
                   + (f", and has been in the top {getattr(config, 'REGIME_TOP_N', 3)} "
                      f"for {run} straight sessions." if run > 1 else "."))

    # The pool, not the fire. A basing count climbing under a zero setup count is
    # the only signal here that leads the setup count rather than tracking it.
    pool = sorted((((v.get("latest") or {}).get("near") or 0,
                    (v.get("latest") or {}).get("near_rate") or 0,
                    v.get("names") or 0, name)
                   for name, v in secs.items()
                   if (v.get("latest") or {}).get("near")),
                  key=lambda t: -t[1])
    if pool:
        cnt, rate, listed, name = pool[0]
        out.append(f"{name} has the most names coiling at the "
                   f"{win.get('sma_slow', 200)}-day average without having triggered: "
                   f"{cnt} of {listed} ({pct(rate)}) are within "
                   f"{100 * win.get('near_tol', 0.04):.0f}% of the level right now.")
    return out


# -- the publish step ---------------------------------------------------------

def _write_json(path: pathlib.Path, payload) -> None:
    """Publish compact JSON atomically. TOP100 #64 — this used to be a
    byte-identical copy of the same five lines in the sibling module (and of
    two more elsewhere); the tmp+os.replace half was already right, but each
    copy carried json's `allow_nan=True` default, so a non-finite value that
    slipped past the local rounding helper published a bare `NaN` token and
    took the whole page down at JSON.parse. output.write_json is now the one
    publisher, and it nulls non-finite floats before dumping."""
    output.write_json(path, payload, indent=None, separators=(",", ":"), newline=True)


def fetch_benchmark(market: str):
    """The market's index frame, or None. Never raises, never blocks a scan.

    One ticker. It is the only network call this module makes, and everything
    except the divergence line survives without it.
    """
    sym = (getattr(config, "REGIME_BENCHMARK", {}) or {}).get(market)
    if not sym:
        return None
    try:
        from .data import download
        return (download([sym], period=getattr(config, "VIVEK_DATA_PERIOD", "5y")) or {}).get(sym)
    except Exception:                                       # noqa: BLE001
        return None


def wanted(market: str) -> bool:
    """Is this a market the module can say anything about? Crypto has no sectors
    to rank and no index to diverge from, so it is skipped rather than published
    as a board with one row."""
    return market in (getattr(config, "REGIME_BENCHMARK", {}) or {})


def publish(blocks: dict, out_dir=None, day: str | None = None) -> dict | None:
    """Merge freshly-computed blocks into the published file and write it.

    Split out from `update()` so scanner/run.py can compute each market's block
    INSIDE its own loop iteration, while that market's deep frames are already
    in memory, and hand over only the finished ~200KB block. The alternative --
    carrying every market's 5-year frames out of the loop to compute them
    together at the end -- holds two full markets of bars alive at once for no
    benefit, and the ASX set alone is the biggest object in the scan.

    A market absent from `blocks` keeps its previous entry rather than being
    blanked, exactly like sectorbreadth: a crypto-only weekend run must not
    erase Friday's ASX read.
    """
    if not getattr(config, "REGIME_ENABLED", True):
        return None
    out_dir = pathlib.Path(out_dir) if out_dir else PUBLIC_FILE.parent
    day = day or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    try:
        prev = json.loads((out_dir / "regime.json").read_text(encoding="utf-8"))
        merged = dict(prev.get("markets") or {})
    except Exception:                                       # noqa: BLE001
        merged = {}

    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for market, blk in (blocks or {}).items():
        if not blk or not wanted(market):
            continue
        blk = dict(blk)
        blk["generated_at"] = stamp
        merged[market] = blk

    payload = {"schema_version": SCHEMA_VERSION, "day": day,
               "generated_at": stamp, "markets": merged}
    _write_json(out_dir / "regime.json", payload)
    return payload


def update(markets: dict, out_dir=None, day: str | None = None) -> dict | None:
    """Compute every market handed in, then publish. The CLI and test path.

    `markets` is ``{market: {"frames": {...}, "universe": [...]}}``, optionally
    with a "bench" frame. An explicit "bench" key wins even when it is None --
    that is how a caller says "do not go to the network", as distinct from not
    having an opinion.
    """
    if not getattr(config, "REGIME_ENABLED", True):
        return None
    blocks = {}
    for market, data in (markets or {}).items():
        if not wanted(market):
            continue
        bench = data["bench"] if "bench" in data else fetch_benchmark(market)
        blocks[market] = compute(market, data.get("frames"),
                                 data.get("universe"), bench=bench)
    return publish(blocks, out_dir=out_dir, day=day)


def main() -> None:
    ap = argparse.ArgumentParser(description="Recompute the regime + sector RS surface")
    ap.add_argument("--market", action="append", help="asx | nasdaq (repeatable)")
    ap.add_argument("--out", default=str(ROOT / "public" / "data"))
    args = ap.parse_args()
    from .data import download, merge_with_cache
    from .universe import load_universe
    markets = {}
    for m in (args.market or ["asx", "nasdaq"]):
        try:
            uni = load_universe(m, full=True)
            fresh = download([u["yf"] for u in uni],
                             period=getattr(config, "VIVEK_DATA_PERIOD", "5y"))
            frames, _ = merge_with_cache(m, fresh, [u["yf"] for u in uni])
        except Exception as exc:                            # noqa: BLE001
            print(f"  regime: no data for {m} ({exc}) - skipped")
            continue
        markets[m] = {"frames": frames, "universe": uni}
    payload = update(markets, out_dir=args.out)
    if not payload:
        print("  regime: disabled")
        return
    for market, blk in (payload.get("markets") or {}).items():
        report(market, blk)


def report(market: str, blk: dict) -> None:
    """The scan's console line for one market. ASCII only (Windows cp1252)."""
    lat = blk.get("latest") or {}
    a200 = lat.get("above200")
    print(f"  regime [{market}]: {lat.get('state', '?')} | "
          f"{'-' if a200 is None else f'{100 * a200:.0f}%'} above the 200 | "
          f"leaders {', '.join(blk.get('leaders') or []) or '-'}")
    for note in blk.get("notes") or []:
        print(f"    . {note}")


if __name__ == "__main__":
    main()
