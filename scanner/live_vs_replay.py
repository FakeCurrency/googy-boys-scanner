"""Live vs replay, trade by trade (the owner's "20 more", 2 Nov, #3).

The decision replay of the live rules makes about +0.06R a trade over five
years; hc4-1's rules closes made about -0.28R. This study asks WHERE the gap
is, on the live book's own trades: it replays every symbol the cycle traded
through the parity engine (the same rules, unconstrained: one position per
symbol, the cooldown, every gate, no slot cap) and lines each live trade up
with the replay's trade on that symbol nearest its entry date.

  * UNMATCHED -- the live bot took a trade the replay never took within
    ``TOLERANCE_DAYS``: a selection gap (the live scan reads the forming bar
    intraday; the replay reads completed bars and fills at the next open).
  * ENTRY -- what the live fill cost against the replay's, in the live
    trade's R (positive = the live bot paid more).
  * OUTCOME -- live R against the replay's R (headline worst-print fill and
    the house fill), with the two exit reasons side by side.

If the matched replay trades lost too, the window was a bad one for the
rules; if they made money, the live implementation is where the R went.

SIMULATION ONLY and READ-ONLY: it reads the book and writes only to --out /
--summary-md (the decision_replay workflow points both at RUNNER_TEMP and
the step summary). Nothing under scanner/broker/ is called to decide. ASCII
prints only.

    python -m scanner.live_vs_replay --cycle hc4-1 --out /tmp/gap.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import math
import pathlib
import sys
from collections import Counter

from . import config

log = logging.getLogger("live_vs_replay")

ROOT = pathlib.Path(__file__).resolve().parents[1]
MARKETS = ("asx", "nasdaq", "crypto")
TOLERANCE_DAYS = 3


# -- the live side -------------------------------------------------------------

def live_rows(root: pathlib.Path, cycle: str) -> list[dict]:
    """Every row (closed and open) the cycle opened, from the canonical books."""
    out = []
    for mk in MARKETS:
        p = root / "journal" / f"vivek_bot_book.{mk}.json"
        if not p.exists():
            continue
        book = json.loads(p.read_text(encoding="utf-8"))
        for status in ("closed", "open"):
            for r in book.get(status) or []:
                if r.get("cycle") == cycle:
                    out.append(dict(r, market=r.get("market") or mk,
                                    status=r.get("status") or status))
    return out


def live_r(row: dict) -> float | None:
    v = row.get("realized_r") if row.get("status") == "closed" else row.get("unreal_r")
    return float(v) if isinstance(v, (int, float)) and math.isfinite(v) else None


def is_rules_exit(row: dict) -> bool:
    return str(row.get("exit_reason") or "").strip().lower() in ("stop", "time", "trail", "target")


# -- matching --------------------------------------------------------------------

def _days(a: str, b: str) -> int | None:
    try:
        return (dt.date.fromisoformat(str(a)[:10]) - dt.date.fromisoformat(str(b)[:10])).days
    except (TypeError, ValueError):
        return None


def match(live: list[dict], replay: list[dict], tol: int = TOLERANCE_DAYS) -> list[dict]:
    """One pair per live row: the replay trade on the same market+symbol whose
    entry is nearest the live entry, within ``tol`` days (a replay trade pairs
    with one live row at most; the nearest claims it)."""
    by_sym: dict[tuple, list[dict]] = {}
    for t in replay:
        by_sym.setdefault((t.get("market"), str(t.get("symbol") or "").upper()), []).append(t)
    cands = []
    for i, r in enumerate(live):
        for t in by_sym.get((r.get("market"), str(r.get("symbol") or "").upper()), []):
            d = _days(r.get("entry_date"), t.get("entry_date"))
            if d is not None and abs(d) <= tol:
                cands.append((abs(d), i, id(t), t, d))
    cands.sort(key=lambda c: (c[0], c[1]))
    used_live, used_rep, chosen = set(), set(), {}
    for _, i, tid, t, d in cands:
        if i in used_live or tid in used_rep:
            continue
        used_live.add(i)
        used_rep.add(tid)
        chosen[i] = (t, d)
    out = []
    for i, r in enumerate(live):
        t, d = chosen.get(i, (None, None))
        out.append(compare(r, t, d))
    return out


def compare(r: dict, t: dict | None, days_off: int | None) -> dict:
    """One live row beside its replay trade (or none)."""
    rec = {"symbol": r.get("symbol"), "market": r.get("market"), "status": r.get("status"),
           "cell": f"{r.get('timeframe')} {r.get('entry_type')}",
           "live_entry_date": r.get("entry_date"), "live_exit_date": r.get("exit_date"),
           "live_exit_reason": r.get("exit_reason") if r.get("status") == "closed" else "open",
           "live_r": live_r(r), "rules": r.get("status") == "open" or is_rules_exit(r),
           "matched": t is not None}
    if t is None:
        return rec
    sign = -1.0 if r.get("direction") == "short" else 1.0
    try:
        risk = float(r.get("risk") or 0)
        gap = sign * (float(r["entry"]) - float(t["entry"])) / risk if risk > 0 else None
    except (KeyError, TypeError, ValueError):
        gap = None
    rec.update({"replay_entry_date": t.get("entry_date"), "replay_exit_date": t.get("exit_date"),
                "replay_exit_reason": t.get("exit_reason"), "days_off": days_off,
                "replay_r": t.get("realized_r"), "replay_r_house": t.get("realized_r_house"),
                "entry_gap_r": None if gap is None else round(gap, 4)})
    return rec


# -- the summary -------------------------------------------------------------------

def _tot(vals) -> float:
    return round(sum(v for v in vals if isinstance(v, (int, float))), 2)


def summarize(pairs: list[dict], cycle: str) -> dict:
    closed = [p for p in pairs if p["status"] == "closed" and p["rules"]]
    m_closed = [p for p in closed if p["matched"]]
    unmatched = [p for p in pairs if not p["matched"]]
    gaps = [p["entry_gap_r"] for p in pairs if p.get("entry_gap_r") is not None]
    by_market = {}
    for mk in MARKETS:
        mc = [p for p in m_closed if p["market"] == mk]
        if mc or any(p["market"] == mk for p in pairs):
            by_market[mk] = {"rules_closed": sum(1 for p in closed if p["market"] == mk),
                             "matched": len(mc), "live_r": _tot(p["live_r"] for p in mc),
                             "replay_r": _tot(p["replay_r"] for p in mc),
                             "replay_r_house": _tot(p["replay_r_house"] for p in mc)}
    return {
        "cycle": cycle,
        "tolerance_days": TOLERANCE_DAYS,
        "live_rows": len(pairs),
        "rules_closed": len(closed),
        "matched": sum(1 for p in pairs if p["matched"]),
        "unmatched": len(unmatched),
        "unmatched_live_r": _tot(p["live_r"] for p in unmatched),
        "matched_closed": {
            "n": len(m_closed),
            "live_r": _tot(p["live_r"] for p in m_closed),
            "replay_r": _tot(p["replay_r"] for p in m_closed),
            "replay_r_house": _tot(p["replay_r_house"] for p in m_closed),
            "unmatched_closed_live_r": _tot(p["live_r"] for p in closed if not p["matched"]),
        },
        "entry_gap_r": {"n": len(gaps), "avg": round(sum(gaps) / len(gaps), 4) if gaps else None,
                        "total": round(sum(gaps), 2)},
        "exit_crosstab": dict(Counter(f"{p['live_exit_reason']} -> {p['replay_exit_reason']}"
                                      for p in m_closed)),
        "by_market": by_market,
    }


def _r(v) -> str:
    return "-" if not isinstance(v, (int, float)) else f"{v:+.2f}"


def markdown(summary: dict, pairs: list[dict]) -> str:
    s, mc = summary, summary["matched_closed"]
    lines = [f"## Live vs replay, trade by trade ({s['cycle']})", "",
             f"- {s['live_rows']} live rows; {s['rules_closed']} closed by the rules. The replay "
             f"took a trade within {s['tolerance_days']} days of {s['matched']} of them; "
             f"{s['unmatched']} it never took (live R on those {_r(s['unmatched_live_r'])}).",
             f"- Matched rules closes: n={mc['n']}, live {_r(mc['live_r'])}R against the replay's "
             f"{_r(mc['replay_r'])}R ({_r(mc['replay_r_house'])}R at the house stop fill). "
             f"Unmatched rules closes: {_r(mc['unmatched_closed_live_r'])}R.",
             f"- Entry: the live fill cost {_r((s['entry_gap_r'] or {}).get('avg'))}R a trade "
             f"against the replay's next-open fill (n={(s['entry_gap_r'] or {}).get('n')}).",
             "", "| market | rules closed | matched | live R | replay R | replay R (house) |",
             "|---|---|---|---|---|---|"]
    for mk, b in s["by_market"].items():
        lines.append(f"| {mk} | {b['rules_closed']} | {b['matched']} | {_r(b['live_r'])} | "
                     f"{_r(b['replay_r'])} | {_r(b['replay_r_house'])} |")
    lines += ["", "| live exit -> replay exit | n |", "|---|---|"]
    for k, n in sorted(s["exit_crosstab"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {k} | {n} |")
    lines += ["", "| symbol | market | cell | live entry | live exit | live R | replay entry | "
              "replay exit | replay R | entry gap R |", "|---|---|---|---|---|---|---|---|---|---|"]
    for p in sorted(pairs, key=lambda p: (p["market"] or "", str(p["live_entry_date"]))):
        lines.append(
            f"| {p['symbol']} | {p['market']} | {p['cell']} | {p['live_entry_date']} | "
            f"{p['live_exit_reason']} {p.get('live_exit_date') or ''} | {_r(p['live_r'])} | "
            f"{p.get('replay_entry_date') or 'never'} | "
            f"{(p.get('replay_exit_reason') or '') + ' ' + (p.get('replay_exit_date') or '')} | "
            f"{_r(p.get('replay_r'))} | {_r(p.get('entry_gap_r'))} |")
    return "\n".join(lines) + "\n"


# -- the replay side (network: runs in CI) ------------------------------------------

def universe_entries(mk: str, rows: list[dict]) -> list[dict]:
    """The universe entry for each symbol the cycle traded (crypto needs its
    identity fields); a symbol the directory no longer lists gets a minimal
    entry from the book row."""
    from .universe import load_universe
    want = {}
    for r in rows:
        if r.get("market") == mk:
            want.setdefault(str(r.get("symbol") or "").upper(), r)
    uni = {str(u.get("symbol") or "").upper(): u for u in load_universe(mk, full=True)}
    out = []
    for sym, r in sorted(want.items()):
        u = uni.get(sym) or {"symbol": r.get("symbol"), "name": r.get("name") or r.get("symbol"),
                             "sector": r.get("sector") or "",
                             "yf": f"{r.get('symbol')}{config.MARKETS[mk].suffix}"}
        out.append(u)
    return out


def replay_trades(rows: list[dict], period: str, window_start: str) -> tuple[list[dict], dict]:
    """The parity engine, unconstrained, over every symbol the rows traded."""
    from . import vivek_parity as vp
    from .vivek_backtest import fetch_market_frames
    trades, coverage = [], {}
    for mk in MARKETS:
        uni = universe_entries(mk, rows)
        if not uni:
            continue
        frames, sources = fetch_market_frames(mk, uni, period)
        meta = {u["yf"]: u for u in uni}
        series = vp.collect_series(mk, frames, meta, workers=1)
        coverage[mk] = {"symbols": len(uni), "priced": len(frames), "replayed": len(series),
                        "data_sources": sources}
        for s in series:
            for t in vp.run_book([s], vp.baseline_rules(), max_total=math.inf, max_sector=0)["taken"]:
                if str(t.get("entry_date") or "") >= window_start:
                    trades.append(dict(t, market=mk))
    return trades, coverage


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cycle", default="hc4-1")
    ap.add_argument("--period", default="5y")
    ap.add_argument("--out", default=None)
    ap.add_argument("--summary-md", default=None)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    rows = live_rows(ROOT, args.cycle)
    if not rows:
        print(f"live_vs_replay: no {args.cycle} rows in the book")
        return 0
    first = min(str(r.get("entry_date") or "9999")[:10] for r in rows)
    start = (dt.date.fromisoformat(first) - dt.timedelta(days=TOLERANCE_DAYS + 7)).isoformat()
    trades, coverage = replay_trades(rows, args.period, start)
    pairs = match(rows, trades)
    summary = summarize(pairs, args.cycle)
    summary["coverage"] = coverage
    md = markdown(summary, pairs)
    print(md)
    if args.out:
        from . import output
        output.write_json(pathlib.Path(args.out), {"summary": summary, "pairs": pairs})
    if args.summary_md:
        with open(args.summary_md, "a", encoding="utf-8") as fh:
            fh.write("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
