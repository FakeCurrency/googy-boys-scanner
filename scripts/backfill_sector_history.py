#!/usr/bin/env python3
"""Rebuild `data/sector_history.json` backwards by REPLAYING the real engine.

WHY THIS EXISTS
---------------
HORIZON's trend column and its unheld-run streak are both read out of the
history file, and that file only started being written on 2026-07-28. So the
surface built to catch the July rotation opened its eyes the week after the
rotation, with no memory of it -- the streak that is supposed to say "the 19th
session running" could only ever say "1", and the trend column had nothing to
trend. Everything the module needs to say something useful about a multi-week
move, it needs weeks of history to say.

The bars are still there. The engine is deterministic. So the honest fix is to
run the SAME engine over the SAME names on each past session and write the rows
that would have been written, clearly marked as reconstructed.

WHAT IS REAL AND WHAT IS NOT
----------------------------
This is the part that matters more than the code, because a reconstruction that
overstates itself is worse than no reconstruction at all -- it would hand the
alarm a fabricated streak and page the owner about a run that never happened.

REAL, and computed the same way a live scan computes it:
  * the per-name grade. `evaluate -> score_and_grade -> build_plans ->
    gate_grade` is imported from `scanner.vivek` and called in scan.py's order,
    on the name's own bars truncated to the session being replayed. Nothing is
    reimplemented. What is skipped -- narrative, detail, spark, markers -- is
    presentation that no grade depends on.
  * the liquidity gate, recomputed per session off the truncated frame, so a
    name that was thin in March is correctly thin in March.
  * the sector denominator, from the same universe file the live scan divides by.

KNOWN TO BE WRONG, and bounded:
  * SURVIVORSHIP. The universe is today's listed set. A name delisted in April
    is absent from both numerator and denominator on every replayed April
    session, and a name listed in June has too few bars for the engine and
    returns nothing. Both understate activity; neither is fixable without a
    point-in-time listings history the project does not have. Six months keeps
    it small, and it is the reason rows carry `"r": 1`.
  * HYSTERESIS runs one chain per DAY, where live runs one per SCAN and several
    scans fire each session. A held grade therefore gets fewer chances to renew
    than it did live, so reconstructed A+/A counts skew slightly LOW. Wrong in
    the conservative direction, which is the direction to be wrong in.
  * The first `--warmup` sessions are computed and then DISCARDED, because a
    hysteresis chain starting cold cannot hold a grade it never saw.

UNKNOWN, and recorded as unknown:
  * HELD. The bot book's earliest entry is 2026-06-28; before that, whether the
    book held a sector is not merely unrecorded but unknowable -- there was no
    book. Those cells are written `null`, never `0`. This is the single most
    important line in the file: `unheld_streak` counts consecutive sessions a
    sector led while the book held NOTHING of it, so writing `0` for "unknown"
    would have manufactured streaks of up to six months on the first run and
    fired the Discord alarm on every sector at once. `unheld_streak` stops at a
    null exactly as it stops at a held position -- see sectorbreadth.

USAGE
-----
    python -m scripts.backfill_sector_history --market asx --sessions 126

CI ONLY in practice: it needs a full 5y download of the market's universe, which
is the same fetch a normal scan already performs. --dry-run writes nothing and
prints the report, which is the mode worth running first.
"""

from __future__ import annotations

import argparse
import concurrent.futures as _fut
import datetime as _dt
import json
import os
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner import config, sectorbreadth  # noqa: E402

_WARMUP_DEFAULT = 10


# ── the book: who held what, and from when ────────────────────────────────────

def book_positions() -> tuple[list[dict], str]:
    """Every bot position ever opened, with the date the book's memory starts.

    Returns (positions, horizon) where `horizon` is the earliest entry_date seen
    anywhere. Sessions before it get `held: null` -- see the module docstring.
    Reads the CANONICAL per-market files, not the derived combined view, so a
    stale rebuild cannot silently drop a market.
    """
    out: list[dict] = []
    for p in sorted((ROOT / "journal").glob("vivek_bot_book.*.json")):
        if "unassigned" in p.name:
            continue
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for bucket in ("open", "closed"):
            for pos in blob.get(bucket) or []:
                entry = str(pos.get("entry_date") or "")[:10]
                if not entry:
                    continue
                out.append({
                    "market": str(pos.get("market") or "").lower(),
                    "symbol": str(pos.get("symbol") or "").upper(),
                    "sector": str(pos.get("sector") or "").strip(),
                    "entry": entry,
                    "exit": str(pos.get("exit_date") or "")[:10] or None,
                })
    horizon = min((p["entry"] for p in out), default="")
    return out, horizon


def held_on(positions: list[dict], market: str, day: str,
            sector_of: dict) -> dict[str, int]:
    """Per-sector held counts for one market on one session.

    A position counts on `day` if it was entered on or before it and had not yet
    exited. Sector comes from the position row when it carries one and from the
    universe otherwise -- 28 of the 36 positions on the books ship sector-less
    (the NASDAQ symbol file has no sector column, and ASX rows predate the
    enrichment fix), and a blank would silently drop them out of the very bucket
    they are supposed to be filling.
    """
    counts: dict[str, int] = defaultdict(int)
    for pos in positions:
        if pos["market"] != market or pos["entry"] > day:
            continue
        if pos["exit"] and pos["exit"] <= day:
            continue
        sec = pos["sector"] or sector_of.get(pos["symbol"], "")
        if sec:
            counts[sectorbreadth._norm(sec)] += 1
    return dict(counts)


# ── the replay ────────────────────────────────────────────────────────────────

def replay_name(args) -> tuple[str, str, dict]:
    """Walk ONE name forward through the session grid, returning its grades.

    Runs in a worker process, so it takes and returns only picklable data and
    imports the engine itself rather than inheriting it.

    The frame is truncated to bars at or before each session -- `df.loc[:day]`
    is the whole of the point-in-time discipline, because the engine reads
    nothing but the frame it is handed. Hysteresis is threaded forward across
    the walk in the same variables scan.py threads it across scans.
    """
    yf_ticker, symbol, sector, frame_records, index_days, grid, market_key = args
    import pandas as pd
    from scanner import vivek, scan as _scan

    market = config.MARKETS[market_key]
    df_all = pd.DataFrame.from_records(frame_records, index=pd.DatetimeIndex(index_days))
    grades: dict[str, str] = {}
    prev_grade = prev_dir = None
    held_runs = 0

    for day in grid:
        df = df_all.loc[:day]
        # Fewer bars than the engine's longest lookback is not a signal-free
        # name, it is a name that did not exist yet. Skip rather than grade.
        if len(df) < config.VIVEK_SMA + 5:
            continue
        try:
            sig = vivek.evaluate(df)
            if sig is None:
                continue
            if _scan._liquidity(df, market) < market.liquidity_min:
                continue
            points, raw_grade, _fired = vivek.score_and_grade(sig)
            if raw_grade is None:
                continue
            cur_dir = "LONG" if sig["direction"] == "long" else "SHORT"
            grade, held_runs = vivek.apply_grade_hysteresis(
                points, raw_grade, prev_grade, prev_dir=prev_dir,
                cur_dir=cur_dir, held_runs=held_runs)
            plans = vivek.build_plans(df, sig)
            gate_tf = next((tf for tf in ("1W", "3D", "1D")
                            if (plans.get(tf) or {}).get("armed")), None)
            hp = plans.get(gate_tf) if gate_tf else plans.get("1D")
            if not hp or float(hp.get("rr") or 0) <= 0:
                continue
            grade, _notes = vivek.gate_grade(grade, sig, float(hp["rr"]),
                                             gate_tf is not None)
            if not grade:
                continue
            grades[day] = grade
            prev_grade, prev_dir = grade, cur_dir
        except Exception:
            # One bad name-day must never cost the other 2,211 names. A name that
            # throws simply has no setup that session, which is also what a live
            # scan records for it (scan.py swallows the same exception).
            continue
    # Only the grade is returned: the history row stores [ag, names, held,
    # index_chg] and `ag` counts grades, so `armed` has nowhere to go.
    return symbol, sector, {"g": grades}


def session_grid(frames: dict, sessions: int, min_coverage: float,
                 market_key: str = "", now=None) -> list[str]:
    """The last `sessions` real trading dates, most-covered first pass.

    A date on which only a handful of names have a bar is a mis-dated row or a
    foreign holiday leaking in, not a session -- replaying it would publish a day
    on which the market apparently vanished. Same test REGIME applies, same
    reason, deliberately the same constant.

    A still-forming trailing bar is dropped for the same reason scan.py drops it:
    a grade computed off half a session wobbles as the session fills in, and a
    reconstruction that disagrees with the live scan on TODAY is a reconstruction
    nobody will trust about June. Every other date in the grid is in the past and
    complete by construction.
    """
    seen: dict[str, int] = defaultdict(int)
    for df in frames.values():
        for ts in df.index:
            seen[str(ts.date())] += 1
    if not seen:
        return []
    best = max(seen.values())
    live = sorted(d for d, n in seen.items() if n >= best * min_coverage)
    if market_key and getattr(config, "VIVEK_DROP_FORMING_BAR", True):
        from zoneinfo import ZoneInfo

        from scanner.scan import _bar_is_forming
        # MARKET-LOCAL, exactly as scan.py builds it: `_bar_is_forming` compares
        # the wall clock against the market's own close time, so handing it UTC
        # would call the ASX open in Melbourne a closed session in July and a
        # forming one in December.
        now = now or _dt.datetime.now(ZoneInfo(config.MARKETS[market_key].timezone))
        live = [d for d in live
                if not _bar_is_forming(market_key, _dt.date.fromisoformat(d), now)]
    return live[-sessions:] if sessions else live


# ── assembly ──────────────────────────────────────────────────────────────────

def build_rows(market: str, per_name: list, grid: list[str], universe: list,
               positions: list[dict], horizon: str) -> list[dict]:
    """Turn per-name grade series into one history row per session.

    The row shape is `append_history`'s exactly -- {d, m, open, max, cap, s} with
    s[sector] = [ag, names, held, index_chg] -- because these rows are read back
    by the same `trend`, `unheld_streak` and `cap_streak` that read live ones. A
    reconstruction in a different shape would be a second format to maintain and
    a second thing to get wrong.
    """
    tradeable = set(getattr(config, "TRADEABLE_GRADES", {"A+", "A"}))
    sector_of = {str(u.get("symbol") or "").upper(): str(u.get("sector") or "")
                 for u in universe}

    # Denominator: names LISTED per sector, from the universe -- identical to
    # `compute`. It is a TODAY figure applied to past sessions; that is the
    # survivorship caveat in the docstring and it is why rows are marked.
    listed: dict[str, int] = defaultdict(int)
    labels: dict[str, str] = {}
    for u in universe:
        raw = str(u.get("sector") or "").strip()
        key = sectorbreadth._norm(raw)
        if not key:
            continue
        listed[key] += 1
        labels.setdefault(key, " ".join(raw.split()))

    by_day: dict[str, dict[str, int]] = {d: defaultdict(int) for d in grid}
    for symbol, sector, res in per_name:
        key = sectorbreadth._norm(sector or sector_of.get(symbol, ""))
        if not key:
            continue
        for day, grade in (res.get("g") or {}).items():
            if grade in tradeable:
                by_day[day][key] += 1

    rows = []
    for day in grid:
        held = held_on(positions, market, day, sector_of) if (horizon and day >= horizon) else None
        cells = {}
        for key, n_listed in listed.items():
            if not n_listed:
                continue
            ag = by_day[day].get(key, 0)
            # `null`, never `0`, for a session predating the book. See the module
            # docstring: this distinction is what keeps the streak honest.
            h = (held or {}).get(key, 0) if held is not None else None
            cells[labels.get(key, key)] = [ag, n_listed, h, None]
        rows.append({"d": day, "m": market, "open": None, "max": None,
                     "cap": 0, "r": 1, "s": cells})
    return rows


def merge_rows(hist: dict, new_rows: list[dict], market: str) -> tuple[dict, int, int]:
    """Fold reconstructed rows in. A REAL row always beats a reconstructed one.

    Re-running the backfill must therefore be safe and idempotent: it can only
    ever fill gaps, never overwrite a session the live scan actually observed.
    """
    have = {(r.get("d"), r.get("m")) for r in hist.get("rows", [])
            if not r.get("r")}
    added = skipped = 0
    rows = [r for r in hist.get("rows", [])
            if not (r.get("m") == market and r.get("r"))]     # drop OUR old ones
    for row in new_rows:
        if (row["d"], row["m"]) in have:
            skipped += 1
            continue
        rows.append(row)
        added += 1
    rows.sort(key=lambda r: (str(r.get("d")), str(r.get("m"))))
    keep = int(getattr(config, "SECTOR_BREADTH_HISTORY_MAX", 2000) or 0)
    if keep and len(rows) > keep:
        rows = rows[-keep:]
    hist["version"] = sectorbreadth.HISTORY_VERSION
    hist["rows"] = rows
    return hist, added, skipped


def dump_rows(path: str, market: str, horizon: str, rows: list[dict]) -> None:
    """Park the reconstruction OUTSIDE the repo so the merge can be redone.

    The replay costs half an hour and the push it feeds can lose a race with a
    live scan writing the same file. Keeping the rows on disk means a retry
    re-merges them against whatever landed meanwhile instead of re-running the
    replay -- or, worse, force-applying a half-hour-old copy of a shared file
    over the row a scan just observed for real.
    """
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps({"market": market, "horizon": horizon,
                               "rows": rows}), encoding="utf-8")
    os.replace(tmp, p)


def merge_only(path: str) -> int:
    """Fold a parked reconstruction into the history file as it stands NOW.

    The whole of the workflow's retry loop: reset to origin/main, run this, push.
    Because `merge_rows` lets a real row win every time, running it against a
    file a scan has just added to is not a conflict to resolve -- it is the
    normal case, and it converges.
    """
    blob = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    market, rows = blob.get("market") or "", blob.get("rows") or []
    if not market or not rows:
        print(f"  {path}: no rows to merge", flush=True)
        return 1
    hist = sectorbreadth.load_history()
    hist, added, skipped = merge_rows(hist, rows, market)
    sectorbreadth._write_json(sectorbreadth.HISTORY_FILE, hist)
    print(f"  merged +{added} reconstructed, {skipped} real rows left alone "
          f"-> {len(hist['rows'])} rows", flush=True)
    if _verify_merged(rows) != 0:
        return 1
    for line in report(hist, market, blob.get("horizon") or ""):
        print(line, flush=True)
    return 0


def _verify_merged(parked: list[dict]) -> int:
    """Re-READ the history file and prove every parked session is in it.

    TOP100 #55 (2026-07-28). The workflow's only gate on this step was
    `git diff --cached --quiet` -> "nothing to commit - every session was
    already real" -> exit 0, which is the sentence a half-hour replay prints
    when it lands nothing at all. Every other committing workflow in this repo
    answers that with `assert_staged`, and here that would be WRONG: the
    docstring on `merge_rows` promises the backfill is idempotent, so a second
    run legitimately produces a byte-identical file and would fail a
    must-change gate on the very property the script advertises.

    So the question is not "did the file change" but "does the file now CONTAIN
    the reconstruction", which is true on the first run and on a re-run alike.
    Answered by reading the file back off disk rather than re-inspecting the
    dict that was just written, because that is the half that can also catch a
    write to the wrong path, a truncated write, or a `_write_json` whose
    os.replace silently did not land -- none of which the in-memory copy knows
    about.

    A row is allowed to be absent for exactly one reason: it fell off the far
    end of SECTOR_BREADTH_HISTORY_MAX, which keeps the NEWEST rows. Anything
    older than the oldest date that survived is excused and said out loud.
    """
    written = sectorbreadth.load_history().get("rows", []) or []
    have = {(r.get("d"), r.get("m")) for r in written}
    absent = [r for r in parked if (r.get("d"), r.get("m")) not in have]
    if not absent:
        return 0
    floor = min((str(r.get("d")) for r in written), default="")
    truncated = [r for r in absent if floor and str(r.get("d")) < floor]
    lost = [r for r in absent if not (floor and str(r.get("d")) < floor)]
    if truncated:
        print(f"  {len(truncated)} session(s) predate the history cap "
              f"(SECTOR_BREADTH_HISTORY_MAX, oldest kept {floor}) - expected",
              flush=True)
    if not lost:
        return 0
    dates = ", ".join(sorted(str(r.get("d")) for r in lost)[:8])
    print(f"MERGE VERIFY FAILED: {len(lost)} replayed session(s) are NOT in "
          f"{sectorbreadth.HISTORY_FILE.name} after the write: {dates}"
          f"{' ...' if len(lost) > 8 else ''}\n"
          f"The replay produced them and the merge reported success, so the "
          f"rows were lost between the two. Do NOT let this commit: the file "
          f"would be published as a complete reconstruction of a period it "
          f"only partly covers, and the streak counter reads a gap as the end "
          f"of a run.", file=sys.stderr, flush=True)
    return 1


def report(hist: dict, market: str, horizon: str) -> list[str]:
    """What the reconstruction actually found -- the post-mortem, in numbers.

    This is the payoff, not the file. The owner's question was never "please
    populate a trend column"; it was "how do I not miss an entire sector running
    again". So say, for the period now reconstructed, which sectors led and for
    how long -- and be explicit that before the book existed, leading is all we
    can honestly claim, because held is unknown.
    """
    rows = [r for r in hist.get("rows", []) if r.get("m") == market]
    if not rows:
        return ["  no rows"]
    top_n = int(getattr(config, "SECTOR_BREADTH_TOP_N", 3) or 3)
    min_names = int(getattr(config, "SECTOR_BREADTH_MIN_NAMES", 15) or 0)

    runs: dict[str, int] = defaultdict(int)
    best: dict[str, tuple[int, str, str]] = {}
    start: dict[str, str] = {}
    for r in rows:
        cells = r.get("s") or {}
        rated = [(c[0] / c[1], c[0], name) for name, c in cells.items()
                 if len(c) >= 2 and c[1] and c[1] >= min_names and c[0] / c[1] > 0
                 and sectorbreadth._norm(name) not in sectorbreadth._NOT_A_SECTOR]
        rated.sort(key=lambda t: (-t[0], -t[1], t[2]))
        lead = {name for _, _, name in rated[:top_n]}
        for name in set(list(lead) + list(runs)):
            if name in lead:
                if not runs[name]:
                    start[name] = str(r.get("d"))
                runs[name] += 1
                cur = (runs[name], start[name], str(r.get("d")))
                if runs[name] >= best.get(name, (0,))[0]:
                    best[name] = cur
            else:
                runs[name] = 0

    lines = [f"  reconstructed {len(rows)} sessions "
             f"({rows[0].get('d')} -> {rows[-1].get('d')})",
             f"  book memory starts {horizon or 'never'} - sessions before it "
             f"record held as UNKNOWN, not zero",
             "  longest consecutive top-%d runs on participation:" % top_n]
    for name, (n, a, b) in sorted(best.items(), key=lambda kv: -kv[1][0])[:8]:
        flag = "  <- pre-dates the book" if horizon and a < horizon else ""
        lines.append(f"    {name:<26} {n:>3} sessions  {a} -> {b}{flag}")
    return lines


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Replay the engine to rebuild sector history")
    ap.add_argument("--market", default="asx")
    ap.add_argument("--sessions", type=int, default=config.REGIME_DAYS)
    ap.add_argument("--warmup", type=int, default=_WARMUP_DEFAULT,
                    help="leading sessions computed then discarded (cold hysteresis)")
    ap.add_argument("--limit", type=int, default=0, help="first N names only (testing)")
    ap.add_argument("--workers", type=int, default=0, help="0 = cpu_count")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the report; leave the history file alone")
    ap.add_argument("--rows-out", default="", help="park the reconstruction here")
    ap.add_argument("--merge-only", default="",
                    help="skip the replay: fold a parked reconstruction in and exit")
    args = ap.parse_args()

    if args.merge_only:
        return merge_only(args.merge_only)

    market = args.market.lower()
    if market not in config.MARKETS:
        print(f"unknown market {market!r}", flush=True)
        return 2

    from scanner.data import download
    from scanner.universe import load_universe

    universe = load_universe(market, full=True)
    if args.limit:
        universe = universe[:args.limit]
    print(f"backfill {market}: {len(universe)} names, "
          f"{args.sessions} sessions (+{args.warmup} warm-up)", flush=True)

    frames = download([u["yf"] for u in universe], period=config.VIVEK_DATA_PERIOD)
    print(f"  downloaded {len(frames)}/{len(universe)} frames", flush=True)
    if not frames:
        print("  no frames - refusing to write an empty reconstruction", flush=True)
        return 1

    grid = session_grid(frames, args.sessions + args.warmup,
                        float(getattr(config, "REGIME_MIN_DAY_COVERAGE", 0.5)),
                        market_key=market)
    if len(grid) <= args.warmup:
        print(f"  only {len(grid)} sessions available - nothing to publish", flush=True)
        return 1
    print(f"  session grid: {len(grid)} days, {grid[0]} -> {grid[-1]}", flush=True)

    meta = {u["yf"]: u for u in universe}
    jobs = []
    for yf_ticker, df in frames.items():
        info = meta.get(yf_ticker, {})
        # Records + a plain date index: DataFrames do not pickle cheaply and the
        # workers rebuild them once each, not once per session.
        jobs.append((yf_ticker,
                     str(info.get("symbol") or yf_ticker).upper(),
                     str(info.get("sector") or ""),
                     df.to_dict("records"),
                     [str(ts) for ts in df.index],
                     grid, market))

    workers = args.workers or (os.cpu_count() or 2)
    done: list = []
    t0 = _dt.datetime.now()
    with _fut.ProcessPoolExecutor(max_workers=workers) as pool:
        for i, res in enumerate(pool.map(replay_name, jobs, chunksize=8), 1):
            done.append(res)
            if i % 250 == 0:
                el = (_dt.datetime.now() - t0).total_seconds()
                print(f"  {i}/{len(jobs)} names  {el/60:.1f} min elapsed "
                      f"(~{el/i*(len(jobs)-i)/60:.1f} min left)", flush=True)

    published = grid[args.warmup:]
    positions, horizon = book_positions()
    rows = build_rows(market, done, published, universe, positions, horizon)
    graded = sum(len(r[2].get("g") or {}) for r in done)
    print(f"  {graded} name-sessions graded across {len(published)} published "
          f"sessions", flush=True)

    if args.rows_out:
        dump_rows(args.rows_out, market, horizon, rows)
        print(f"  parked {len(rows)} rows -> {args.rows_out}", flush=True)

    hist = sectorbreadth.load_history()
    hist, added, skipped = merge_rows(hist, rows, market)
    print(f"  merged: +{added} reconstructed, {skipped} real rows left alone",
          flush=True)
    for line in report(hist, market, horizon):
        print(line, flush=True)

    if args.dry_run:
        print("  dry-run: history not written", flush=True)
        return 0
    sectorbreadth._write_json(sectorbreadth.HISTORY_FILE, hist)
    print(f"  wrote {sectorbreadth.HISTORY_FILE.relative_to(ROOT)} "
          f"({len(hist['rows'])} rows)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
