"""Statistics for the decision replay (SIMULATION ONLY; NEXT100 #16, #17).

Three readings the replay's tables did not carry:

* ``random_timing`` -- the one test of whether buying at the 200-SMA beats
  buying the SAME names on random days: every taken trade of the live-rules
  arm gets ``VIVEK_PARITY_RANDOM_DRAWS`` entries on its own bars at random
  signal days within +/- ``VIVEK_PARITY_RANDOM_WINDOW_BARS`` of the real one,
  each run through the same exit model (``vivek_parity._run_trade``). It also
  cancels most survivorship bias: the random entries live on the same
  survivor-biased tape.
* ``bootstrap_bands`` / ``paired_bands`` -- entry-month block bootstrap: the
  months are resampled with replacement and each month's trades travel
  together (one regime per month), so the 90% band says how far R per
  slot-month moves when the calendar is redrawn. A variant is read PAIRED:
  the months are drawn once and applied to both arms, and P(no gain) is the
  share of resamples where the variant's figure is not above the baseline's.
* ``placebo_pass_rate`` -- with 17 variants a run, two or three false PASSes
  are expected by chance. Each placebo drops the same share of the baseline's
  trades at random as the real variant dropped and is scored with the real
  ``variant_passes`` gate; the rate of placebo PASSes is printed beside the
  real verdict. It models an entry filter; for an exit-rule variant (whose
  trades differ in R, not in count) it reads as "what a random subset passes".

Everything here reads closed trade lists and the replay's ``SymbolSeries``;
nothing is a trade path. Seeded from ``VIVEK_PARITY_RANDOM_SEED`` and
deterministic for the same data and order-independent per trade (each
trade's stream is keyed by market, symbol and entry date). ASCII only.
"""

from __future__ import annotations

import math
import zlib
from collections import defaultdict

import numpy as np

from . import config
from . import vivek_parity as vp
from .vivek_journal import _snapshot


def _seed(seed: int | None = None) -> int:
    return int(config.VIVEK_PARITY_RANDOM_SEED if seed is None else seed)


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    return round(float(np.percentile(np.asarray(values, dtype=float), q)), 4)


def _mean(values: list[float]) -> float | None:
    return round(float(np.mean(values)), 4) if values else None


def _band(values: list[float]) -> dict:
    return {"mean": _mean(values), "p5": _pct(values, 5), "p95": _pct(values, 95)}


# ── #16 random timing ─────────────────────────────────────────────────────────

def draw_signal_bars(rng: np.random.Generator, s: vp.SymbolSeries, j0: int, draws: int,
                     window: int) -> np.ndarray:
    """The signal bars of one trade's draws: ``draws`` integers (with
    replacement) in [j0 - window, j0 + window], never j0 itself, each with a
    finite next open (the fill bar j + 1 exists, as a real signal needs).
    Empty when the window holds no such bar."""
    n = len(s.days)
    lo, hi = max(0, j0 - int(window)), min(n - 2, j0 + int(window))
    if hi < lo:
        return np.array([], dtype=int)
    cand = np.arange(lo, hi + 1)
    cand = cand[cand != j0]
    cand = cand[np.isfinite(s.o[cand + 1])]
    if not len(cand):
        return np.array([], dtype=int)
    return rng.choice(cand, size=int(draws), replace=True).astype(int)


def _reanchored_plan(tr: dict, fill: float) -> dict:
    """The real trade's plan geometry hung on the random fill.

    Re-anchored: the INITIAL stop and TP1/TP2/TP3 sit at the same FRACTION of
    the fill as the real ones sat of the real entry (so 1R, the ladder's R:R
    and the trail steps are the same in R terms); the scale-out ladder, the
    entry type and timeframe are copied. NOT re-anchored (the exit model reads
    them from the rules, not the plan): the pre-TP1 time stop, the trail,
    the costs and the stop-fill conventions."""
    entry = float(tr["entry"])
    stop0 = tr.get("initial_stop")
    if stop0 is None:
        stop0 = tr["stop"]

    def at(level) -> float:
        return fill * float(level) / entry

    return {"stop": at(stop0), "tp1": at(tr["tp1"]), "tp2": at(tr["tp2"]), "tp3": at(tr["tp3"]),
            "scale": tr["scale"], "entry": fill, "entry_trigger": tr.get("entry_type"),
            "trigger_bar": None, "structural_tps": tr.get("structural_tps")}


def _draw_trade(tr: dict, s: vp.SymbolSeries, j: int, rules: vp.ParityRules) -> dict | None:
    """One random entry: signal bar j, fill at bar j + 1's open, managed by the
    replay's own bar loop until it closes."""
    k = j + 1
    fill = float(s.o[k])
    if not (fill > 0):
        return None
    row = {"symbol": s.symbol, "name": s.name, "sector": s.sector,
           "dir": "SHORT" if tr.get("direction") == "short" else "LONG",
           "grade": tr.get("grade"), "entry_types": [tr.get("entry_type")],
           "level_tf": tr.get("level_tf")}
    d = _snapshot(row, tr.get("timeframe") or "1W", _reanchored_plan(tr, fill), s.market,
                  fill, s.iso(k))
    if d is None:
        return None
    d.update({"market": s.market, "level_tf": tr.get("level_tf"), "initial_stop": d["stop"],
              "adv_usd": None, "signal_date": s.iso(j), "mfe_r_at": {}, "close_r_at": {},
              "structural_tps": tr.get("structural_tps"), "random_draw": True})
    return vp._run_trade(d, s, k, rules)


def _bar_of(s: vp.SymbolSeries, day: str | None) -> int | None:
    if not day:
        return None
    want = vp._iso_to_int(day)
    k = int(np.searchsorted(s.days, want))
    return k if k < len(s.days) and int(s.days[k]) == want else None


def _versus(real: list[float], real_house: list[float], draws_r: np.ndarray,
            draws_house: np.ndarray) -> dict:
    """real vs random on a (trades x draws) matrix: draw b's average over the
    trades is one random book; P = the share of those averages >= the real
    mean (resolution 1/draws)."""
    if not real:
        return {"n": 0, "real": None, "random": None, "delta_r": None, "p_value": None}
    real_mean = float(np.mean(real))
    draw_avgs = draws_r.mean(axis=0)
    return {
        "n": len(real),
        "real": {"mean_r": round(real_mean, 4), "mean_r_house": _mean(real_house)},
        "random": {"draws": int(draws_r.size), "mean_r": round(float(draws_r.mean()), 4),
                   "mean_r_house": round(float(draws_house.mean()), 4),
                   "draw_avg_p5": _pct(draw_avgs.tolist(), 5),
                   "draw_avg_p95": _pct(draw_avgs.tolist(), 95)},
        "delta_r": round(real_mean - float(draws_r.mean()), 4),
        "p_value": round(float(np.mean(draw_avgs >= real_mean)), 4),
    }


def random_timing(series: list[vp.SymbolSeries], taken: list[dict],
                  rules: vp.ParityRules | None = None, draws: int | None = None,
                  seed: int | None = None, window: int | None = None) -> dict:
    """The random-timing baseline for the live-rules arm (see the module doc).

    Per taken trade: ``draws`` random signal bars on the SAME series
    (``draw_signal_bars``), each filled at the next open with the plan
    re-anchored to that fill (``_reanchored_plan``) and run through the same
    exit model the trade used (``vivek_parity._run_trade`` under ``rules``).
    A draw is filed under its PARENT trade's market. Returns mean R real vs
    random, the difference and the P value per market and overall, with the
    bookkeeping (draws per trade, window, seed, trades skipped for want of a
    series or an eligible bar)."""
    rules = rules or vp.baseline_rules()
    draws = int(config.VIVEK_PARITY_RANDOM_DRAWS if draws is None else draws)
    window = int(config.VIVEK_PARITY_RANDOM_WINDOW_BARS if window is None else window)
    seed = _seed(seed)
    by_key = {(s.market, s.symbol): s for s in series}
    rows: dict[str, list] = defaultdict(list)          # market -> [(real, house, [draw r], [draw house])]
    skipped = {"no_series": 0, "no_bar": 0, "no_draw": 0}
    for tr in taken:
        s = by_key.get((tr.get("market"), tr.get("symbol")))
        if s is None or draws <= 0:
            skipped["no_series"] += 1
            continue
        j0 = _bar_of(s, tr.get("signal_date"))
        if j0 is None:
            k0 = _bar_of(s, tr.get("entry_date"))
            j0 = None if k0 is None or k0 < 1 else k0 - 1
        if j0 is None:
            skipped["no_bar"] += 1
            continue
        rng = np.random.default_rng(seed + zlib.crc32(
            f"{s.market}|{s.symbol}|{tr.get('entry_date')}".encode()))
        got = [_draw_trade(tr, s, int(j), rules) for j in draw_signal_bars(rng, s, j0, draws, window)]
        got = [d for d in got if d is not None]
        if len(got) != draws:
            skipped["no_draw"] += 1
            continue
        rows[s.market].append((float(tr.get("realized_r") or 0.0),
                               float(tr.get("realized_r_house") if tr.get("realized_r_house")
                                     is not None else (tr.get("realized_r") or 0.0)),
                               [float(d.get("realized_r") or 0.0) for d in got],
                               [float(d.get("realized_r_house") if d.get("realized_r_house")
                                      is not None else (d.get("realized_r") or 0.0)) for d in got]))

    def block(items: list) -> dict:
        if not items:
            return _versus([], [], np.zeros((0, draws)), np.zeros((0, draws)))
        return _versus([i[0] for i in items], [i[1] for i in items],
                       np.array([i[2] for i in items], dtype=float),
                       np.array([i[3] for i in items], dtype=float))

    every = [i for mk in sorted(rows) for i in rows[mk]]
    return {
        "method": "same names, same exit model, random signal days within +/- window bars; "
                  "stop and TPs re-anchored as the same fraction of the random fill",
        "draws_per_trade": draws, "window_bars": window, "seed": seed,
        "trades": len(every), "draws_total": len(every) * draws, "skipped": skipped,
        "overall": block(every),
        "by_market": {mk: block(rows[mk]) for mk in sorted(rows)},
    }


# ── #17 month-block bootstrap, paired bands, placebo ──────────────────────────

def _by_month(trades: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        day = str(t.get("entry_date") or "")
        if len(day) >= 7:
            out[day[:7]].append(t)
    return out


def _resample(groups: dict[str, list[dict]], months: list[str], idx: np.ndarray) -> list[dict]:
    out: list[dict] = []
    for i in idx:
        out.extend(groups.get(months[int(i)], ()))
    return out


def _rpsm(trades: list[dict]) -> float | None:
    return vp._slot_month_stats(trades)[1]


def bootstrap_bands(trades: list[dict], n: int | None = None, seed: int | None = None) -> dict:
    """Entry-month block bootstrap of one arm: ``n`` resamples of its months
    with replacement (each month's trades together); R per slot-month
    (``vivek_parity._slot_month_stats``) and total R per resample; the mean
    and the 5th / 95th percentiles of each."""
    n = int(config.VIVEK_PARITY_BOOTSTRAP_N if n is None else n)
    groups = _by_month(trades)
    months = sorted(groups)
    point = _rpsm(trades)
    if not months or n <= 0:
        return {"n": 0, "months": len(months), "trades": len(trades), "point_r_per_slot_month": point,
                "r_per_slot_month": _band([]), "total_r": _band([]), "undefined": 0}
    rng = np.random.default_rng(_seed(seed))
    idx = rng.integers(0, len(months), size=(n, len(months)))
    rpsm, totals, undefined = [], [], 0
    for row in idx:
        sample = _resample(groups, months, row)
        v = _rpsm(sample)
        if v is None:
            undefined += 1
        else:
            rpsm.append(v)
        totals.append(sum(float(t.get("realized_r") or 0.0) for t in sample))
    return {"n": n, "months": len(months), "trades": len(trades), "point_r_per_slot_month": point,
            "r_per_slot_month": _band(rpsm), "total_r": _band(totals), "undefined": undefined}


def paired_bands(baseline: list[dict], variant: list[dict], n: int | None = None,
                 seed: int | None = None) -> dict:
    """The 90% band of the DIFFERENCE in R per slot-month, variant minus
    baseline, paired by entry month: the months (the union of both arms')
    are drawn once per resample and applied to both. P(no gain) is the share
    of resamples where the variant's figure is <= the baseline's (an
    undefined figure on either side counts as no gain: fail closed)."""
    n = int(config.VIVEK_PARITY_BOOTSTRAP_N if n is None else n)
    gb, gv = _by_month(baseline), _by_month(variant)
    months = sorted(set(gb) | set(gv))
    if not months or n <= 0:
        return {"n": 0, "months": len(months), "delta_r_per_slot_month": _band([]),
                "p_no_gain": None, "undefined": 0}
    rng = np.random.default_rng(_seed(seed))
    idx = rng.integers(0, len(months), size=(n, len(months)))
    deltas, no_gain, undefined = [], 0, 0
    for row in idx:
        b = _rpsm(_resample(gb, months, row))
        v = _rpsm(_resample(gv, months, row))
        if b is None or v is None:
            undefined += 1
            no_gain += 1
            continue
        deltas.append(round(v - b, 4))
        if v <= b:
            no_gain += 1
    return {"n": n, "months": len(months), "delta_r_per_slot_month": _band(deltas),
            "p_no_gain": round(no_gain / n, 4), "undefined": undefined}


def placebo_pass_rate(baseline: list[dict], variant: list[dict], n: int | None = None,
                      seed: int | None = None, skip_markets: tuple[str, ...] = ()) -> dict:
    """``n`` dropout placebos: each drops, uniformly at random, the same share
    of the baseline's trades as the real variant dropped (count-wise; a
    variant with as many trades or more drops nothing, so every placebo IS
    the baseline and cannot pass a strict gate), scored with the real
    ``vivek_parity.variant_passes`` gate. Returns the rate of placebo PASSes."""
    n = int(config.VIVEK_PARITY_PLACEBO_N if n is None else n)
    nb = len(baseline)
    if nb == 0 or n <= 0:
        return {"n": 0, "passes": 0, "rate": None, "drop_share": None, "dropped": 0}
    share = max(0.0, min(1.0, 1.0 - len(variant) / nb))
    k = int(round(share * nb))
    rng = np.random.default_rng(_seed(seed))
    passes = 0
    for _ in range(n):
        drop = set(rng.choice(nb, size=k, replace=False).tolist()) if k else set()
        placebo = [t for i, t in enumerate(baseline) if i not in drop]
        if vp.variant_passes(baseline, placebo, skip_markets=skip_markets)["pass"]:
            passes += 1
    return {"n": n, "passes": passes, "rate": round(passes / n, 4),
            "drop_share": round(share, 4), "dropped": k}


def variant_stats(baseline: list[dict], variant: list[dict], skip_markets: tuple[str, ...] = (),
                  name: str = "", n_boot: int | None = None, n_placebo: int | None = None,
                  seed: int | None = None) -> dict:
    """The 'stats' block beside a variant's verdict: the paired 90% band and
    P(no gain), and the placebo pass rate. The variant's name salts the seed
    so a stream does not depend on the grid's order."""
    salt = _seed(seed) + zlib.crc32(name.encode())
    return {"band": paired_bands(baseline, variant, n_boot, salt),
            "placebo": placebo_pass_rate(baseline, variant, n_placebo, salt + 1, skip_markets)}


# ── hooks for vivek_parity (one line each there) ──────────────────────────────

def attach(report: dict, series: list[vp.SymbolSeries], taken: list[dict],
           rules: vp.ParityRules | None = None) -> dict:
    """Adds ``versus.random_timing`` and ``baseline.stats.bootstrap`` to a
    built report. Returns the report."""
    report.setdefault("versus", {})["random_timing"] = random_timing(series, taken, rules)
    report.setdefault("baseline", {}).setdefault("stats", {})["bootstrap"] = bootstrap_bands(taken)
    return report


def _fmt(v, nd: int = 3, sign: bool = True) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "n/a"
    return f"{v:+.{nd}f}" if sign else f"{v:.{nd}f}"


def stats_cells(stats: dict | None) -> str:
    """The three variant-table cells: 90% band of dR/slot-month, P(no gain),
    placebo pass rate."""
    if not stats:
        return "n/a | n/a | n/a"
    band = (stats.get("band") or {}).get("delta_r_per_slot_month") or {}
    p = (stats.get("band") or {}).get("p_no_gain")
    pl = stats.get("placebo") or {}
    band_txt = (f"{_fmt(band.get('p5'))}..{_fmt(band.get('p95'))}"
                if band.get("p5") is not None else "n/a")
    pl_txt = ("n/a" if pl.get("rate") is None
              else f"{pl['rate'] * 100:.0f}% of {pl.get('n')}")
    return f"{band_txt} | {_fmt(p, 2, sign=False)} | {pl_txt}"


def versus_markdown(report: dict) -> list[str]:
    """The random-timing section for the step summary / log."""
    rt = (report.get("versus") or {}).get("random_timing")
    if not rt:
        return []
    lines = ["", "### Versus random timing (same names, same exits, random days)", "",
             f"{rt.get('draws_per_trade')} draws per taken trade within +/- {rt.get('window_bars')} "
             f"bars of the real signal; {rt.get('trades')} trades, {rt.get('draws_total')} draws; "
             f"P = share of random books averaging >= the real mean R (seed {rt.get('seed')}).", "",
             "| market | n | real mean R (house) | random mean R (house) | delta | P |",
             "|---|---|---|---|---|---|"]
    blocks = [("overall", rt.get("overall") or {})] + sorted((rt.get("by_market") or {}).items())
    for label, b in blocks:
        real, rnd = b.get("real") or {}, b.get("random") or {}
        lines.append(f"| {label} | {b.get('n', 0)} | {_fmt(real.get('mean_r'))} "
                     f"({_fmt(real.get('mean_r_house'))}) | {_fmt(rnd.get('mean_r'))} "
                     f"({_fmt(rnd.get('mean_r_house'))}) | {_fmt(b.get('delta_r'))} | "
                     f"{_fmt(b.get('p_value'), 2, sign=False)} |")
    bs = ((report.get("baseline") or {}).get("stats") or {}).get("bootstrap") or {}
    if bs.get("n"):
        band = bs.get("r_per_slot_month") or {}
        lines += ["", f"Baseline R/slot-month {_fmt(bs.get('point_r_per_slot_month'))}; "
                  f"90% band {_fmt(band.get('p5'))}..{_fmt(band.get('p95'))} over {bs.get('n')} "
                  f"entry-month block resamples ({bs.get('months')} months, each month's trades "
                  f"together)."]
    return lines
