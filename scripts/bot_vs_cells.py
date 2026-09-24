"""The paper book against the four-cell sleeve (2026-09-24). READ-ONLY.

PR #42 measured the sleeve the bot is meant to trade -- 5.0 longs at A+/A in a
high-conviction cell (1W reclaim, 1W break, 3D reclaim, 1D break), reacting at
a weekly or 3-day 200-SMA, stop <= VIVEK_BOT_MAX_STOP_PCT -- at +0.263R a trade
on the house fill. This asks whether the book the bot actually holds is that
sleeve: every open and closed paper position is classified in-cell /
out-of-cell / unknown against the predicates the live gate applies
(vivek_bot.evaluate_setup + vivek_run._apply_level_gate), with the journal's
own closed R and nothing re-derived.

Two readings of a position are taken from outside the book row, because the
row cannot answer them:
  * the GRADE it was taken at. plan_trade stamps every ticket "grade": "A+",
    so since A became takeable (2026-09-21, cycle hc4-1) an A take is recorded
    as A+. The true grade is the scan row's grade_raw in the commit that first
    wrote the position (git history; a shallow clone reaches back only so far,
    and a position older than the history keeps the book's stamp);
  * the STOP the cap was tested on. The gate reads it off the plan's entry
    (the signal close); the book fills later at a live quote. The plan stop is
    entry - risk (risk is frozen at the fill), measured against signal_entry.

Writes only the note it is pointed at. Never stages or edits journal/.

  python scripts/bot_vs_cells.py --out reviews/2026-09-24-bot-vs-cells.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner import config  # noqa: E402
from scanner.broker.vivek_bot import _is_fund_or_reit  # noqa: E402
from scanner.journal_common import atomic_write  # noqa: E402

MARKETS = ("asx", "nasdaq", "crypto")
GRADE_RAW_SINCE = "2026-07-20"   # H2: evaluate_setup reads grade_raw from this day
A_TAKEABLE_SINCE = "2026-09-21"  # A joined A+ (hc4-1); the ticket still stamps "A+"
MECHANICAL = ("stop", "trail", "target", "time", "tp")


# -- reading ---------------------------------------------------------------

def load_book(root: pathlib.Path = ROOT) -> list[dict]:
    """Every paper position, open and closed, from the canonical per-market files."""
    out = []
    for m in MARKETS:
        d = json.loads((root / "journal" / f"vivek_bot_book.{m}.json").read_text(encoding="utf-8"))
        for side in ("open", "closed"):
            for r in d.get(side) or []:
                out.append(dict(r, _market=m, _side=side))
    return out


def entry_scans(rows: list[dict], root: pathlib.Path = ROOT) -> dict:
    """{position id: the scan row that opened it}, from git history.

    The commit that first wrote the id into the market's book is the scan run
    that took it; that commit's <market>_vivek.json holds the rows decide()
    saw. Positions older than the available history map to nothing."""
    days = subprocess.run(["git", "log", "--format=%cs"], cwd=root,
                          capture_output=True, text=True).stdout.split()
    first = days[-1] if days else ""                   # the oldest commit this clone holds
    out = {}
    for r in rows:
        if not first or (r.get("entry_date") or "") <= first:     # the boundary day is ambiguous
            continue
        m = r["_market"]
        found = subprocess.run(["git", "log", "--reverse", "--format=%H %cI", f"-S\"{r['id']}\"",
                                "--", f"journal/vivek_bot_book.{m}.json"],
                               cwd=root, capture_output=True, text=True).stdout.split()
        if len(found) < 2:
            continue
        shown = subprocess.run(["git", "show", f"{found[0]}:public/data/{m}_vivek.json"],
                               cwd=root, capture_output=True, text=True)
        try:
            scan = json.loads(shown.stdout)
        except ValueError:
            continue
        row = next((x for x in scan.get("results") or [] if x.get("symbol") == r["symbol"]), None)
        if row is not None:
            out[r["id"]] = {"grade_raw": row.get("grade_raw"), "grade": row.get("grade"),
                            "level_tf": row.get("level_tf"), "is_product": row.get("is_product"),
                            "data_age_days": row.get("data_age_days"),
                            "generated_at": scan.get("generated_at"), "commit": found[0][:9],
                            "committed_at": found[1]}
    return out


# -- the predicates --------------------------------------------------------

def plan_stop_pct(r: dict) -> float | None:
    """The stop distance the gate tested: plan stop against the signal close."""
    entry, risk, sig = r.get("entry"), r.get("risk"), r.get("signal_entry")
    if not (entry and risk and sig):
        return None
    stop0 = entry - risk if r.get("direction") == "long" else entry + risk
    return abs(sig - stop0) / sig * 100.0


def fill_stop_pct(r: dict) -> float | None:
    """The same stop against the fill -- how PR #42 measured the sleeve."""
    entry, risk = r.get("entry"), r.get("risk")
    return risk / entry * 100.0 if entry and risk else None


def classify(r: dict, scan: dict | None = None) -> dict:
    """in / out / unknown against the sleeve, with the failing predicates named."""
    why, unknown = [], []
    cells = {(tf, et) for tf, ets in config.VIVEK_BOT_ENTRY_CELLS.items() for et in ets}
    if r.get("direction") != "long":
        why.append("short")
    if _is_fund_or_reit({"name": r.get("name"), "sector": r.get("sector")}):
        why.append("fund/REIT")
    if scan and scan.get("grade_raw"):
        grade, src = scan["grade_raw"], "scan grade_raw"
    elif (r.get("entry_date") or "") >= A_TAKEABLE_SINCE:
        grade, src = None, "book stamp (A or A+)"
    elif (r.get("entry_date") or "") >= GRADE_RAW_SINCE:
        grade, src = r.get("grade"), "book (A+ only, raw)"
    else:
        grade, src = r.get("grade"), "book (displayed grade)"
    if grade is None:
        unknown.append("grade")
    elif grade not in config.VIVEK_BOT_GRADES:
        why.append(f"grade {grade}")
    elif src == "book (displayed grade)":
        unknown.append("grade source")
    if (r.get("timeframe"), r.get("entry_type")) not in cells:
        why.append(f"{r.get('timeframe')} {r.get('entry_type')} is not a cell")
    lvl = str(r.get("level_tf") or "").strip().lower()
    if not lvl:
        unknown.append("level_tf")
    elif lvl not in config.VIVEK_BOT_LEVEL_TF_ALLOW:
        why.append(f"{lvl} level")
    ps, fs = plan_stop_pct(r), fill_stop_pct(r)
    stop = ps if ps is not None else fs
    if stop is None:
        unknown.append("stop")
    elif stop > config.VIVEK_BOT_MAX_STOP_PCT:
        why.append(f"stop {stop:.1f}%")
    cls = "out" if why else ("unknown" if unknown else "in")
    return {"cls": cls, "why": why, "unknown": unknown, "grade": grade, "grade_src": src,
            "plan_stop": ps, "fill_stop": fs,
            "fill_over_cap": fs is not None and fs > config.VIVEK_BOT_MAX_STOP_PCT}


# -- freshness (the deck's session + 2h rule, app.js sessionStaleness) -----

def session_staleness(generated_at: str, market: str, now: dt.datetime) -> dict:
    sess = config.VIVEK_JOURNAL_SESSION.get(market)
    grace = dt.timedelta(hours=config.VIVEK_DECK_SESSION_GRACE_H)
    try:
        t = dt.datetime.fromisoformat(generated_at)
    except (TypeError, ValueError):
        t = None
    if sess is None:                                   # crypto: no session, wall clock
        return {"stale": t is None or now - t > grace, "ref": now - grace, "edge": "wall clock"}
    tz = ZoneInfo(config.MARKETS[market].timezone)
    today = now.astimezone(tz).date()
    for back in range(8):
        day = today - dt.timedelta(days=back)
        if day.weekday() >= 5:
            continue
        close = dt.datetime(day.year, day.month, day.day, sess[2], sess[3], tzinfo=tz)
        opn = dt.datetime(day.year, day.month, day.day, sess[0], sess[1], tzinfo=tz)
        for ref, edge in ((close, "close"), (opn, "open")):
            if ref + grace <= now:
                return {"stale": t is None or t < ref, "ref": ref, "edge": edge}
    return {"stale": False, "ref": None, "edge": None}


def freshness(now: dt.datetime, root: pathlib.Path = ROOT) -> list[dict]:
    out = []
    for m in MARKETS:
        scan = json.loads((root / "public" / "data" / f"{m}_vivek.json").read_text(encoding="utf-8"))
        book = json.loads((root / "journal" / f"vivek_bot_book.{m}.json").read_text(encoding="utf-8"))
        s = session_staleness(scan.get("generated_at"), m, now)
        out.append({"market": m, "generated_at": scan.get("generated_at"),
                    "downloaded": scan.get("downloaded"), "universe": scan.get("universe_size"),
                    "book_updated": book.get("updated_at"), **s})
    return out


# -- the note --------------------------------------------------------------

def _r(v):
    return "--" if v is None else f"{v:+.2f}"


def _pct(v):
    return "--" if v is None else f"{v:.1f}%"


def closed_stats(rows: list[dict]) -> dict:
    rs = [float(r.get("realized_r") or 0.0) for r in rows]
    n = len(rs)
    return {"n": n, "net_r": round(sum(rs), 2), "r_per_trade": round(sum(rs) / n, 3) if n else None,
            "win_pct": round(100.0 * sum(1 for x in rs if x > 0) / n, 1) if n else None}


def predicates_block() -> str:
    cells = ", ".join(f"{tf} {et}" for tf, ets in config.VIVEK_BOT_ENTRY_CELLS.items() for et in ets)
    return "\n".join([
        "```text",
        "direction        = long only",
        f"grades           = {', '.join(config.VIVEK_BOT_GRADES)}",
        "grade_source     = grade_raw",
        f"cells            = {cells}",
        f"cell_walk        = {' > '.join(config.VIVEK_BOT_ENTRY_CELLS)}",
        f"level_tf         = {', '.join(config.VIVEK_BOT_LEVEL_TF_ALLOW)}",
        "level_tf_missing = dropped",
        f"max_stop_pct     = {config.VIVEK_BOT_MAX_STOP_PCT:g}",
        f"min_stop_pct     = {config.VIVEK_BOT_MIN_STOP_PCT:g}",
        "stop_basis       = plan entry, then fill",
        f"min_rr           = {config.VIVEK_BOT_MIN_RR:g}",
        f"exclude_funds    = {config.VIVEK_BOT_EXCLUDE_FUNDS}",
        f"max_per_sector   = {config.VIVEK_BOT_MAX_PER_SECTOR}",
        f"max_open_total   = {config.VIVEK_BOT_MAX_OPEN_TOTAL}",
        f"max_hold_days    = {config.VIVEK_BOT_MAX_HOLD_DAYS}",
        "```"])


def build_note(rows: list[dict], scans: dict, fresh: list[dict], now: dt.datetime,
               prose: dict) -> str:
    for r in rows:
        r["_c"] = classify(r, scans.get(r["id"]))
    op = [r for r in rows if r["_side"] == "open"]
    cl = [r for r in rows if r["_side"] == "closed"]
    n_in_open = sum(1 for r in op if r["_c"]["cls"] == "in")
    fill_ok = sum(1 for r in op if r["_c"]["cls"] == "in" and not r["_c"]["fill_over_cap"])
    by = lambda rs, c: [r for r in rs if r["_c"]["cls"] == c]  # noqa: E731
    stamped = [r for r in op if scans.get(r["id"], {}).get("grade_raw")
               and scans[r["id"]]["grade_raw"] != r.get("grade")]
    L = [f"**Gate matches four-cell: {prose['matches']}. Open positions in-cell: "
         f"{n_in_open}/{len(op)}** ({fill_ok}/{len(op)} if the stop is read at the fill, as "
         "#42 measured the sleeve).", "",
         "# Paper book vs the four-cell edge -- 2026-09-24", "",
         f"Read-only. Book as committed at {prose['book_asof']}; generated by "
         "`scripts/bot_vs_cells.py`. Closed R is the journal's own `realized_r`; nothing is "
         "re-derived. No rule, book row or `bot_rules.json` value is changed by this note.", "",
         "## 1. The gate, from live code", "", prose["gate"], "",
         "The predicates, as the code reads today (`tests/test_bot_vs_cells.py` fails if "
         "this block and the code drift apart):", "", predicates_block(), "",
         prose["verdict"], "",
         "## 2. Every paper position, classified", "",
         "| | n | closed R | R/trade | win% |", "|---|---|---|---|---|"]
    for c, label in (("in", "in-cell"), ("out", "out-of-cell"), ("unknown", "unknown")):
        s = closed_stats(by(cl, c))
        L.append(f"| {label} | {len(by(op, c))} open / {s['n']} closed | {_r(s['net_r'])} | "
                 f"{'--' if s['r_per_trade'] is None else format(s['r_per_trade'], '+.3f')} | "
                 f"{'--' if s['win_pct'] is None else format(s['win_pct'], '.1f') + '%'} |")
    inc = by(cl, "in")
    mech = [r for r in inc if str(r.get("exit_reason") or "") in MECHANICAL]
    hand = [r for r in inc if str(r.get("exit_reason") or "") not in MECHANICAL]
    sm, sh = closed_stats(mech), closed_stats(hand)
    L += ["", f"In-cell closes by who closed them: the rules (stop/trail/target/28-day time "
          f"stop) {sm['n']} for {_r(sm['net_r'])}R; by hand {sh['n']} for {_r(sh['net_r'])}R. "
          "The #42 sleeve has neither a 28-day time stop nor a hand close, so the book's closed "
          "R is not a read of the sleeve's +0.263R -- it is a read of the sleeve managed "
          "differently.", ""]
    L += ["## 3. Stale / wrong takes still live", "", prose["wrong"], ""]
    wrong_rows = [r for r in op if r["_c"]["cls"] != "in" or r["_c"]["fill_over_cap"]]
    if wrong_rows:
        L += ["| market | symbol | why | plan stop | fill stop |", "|---|---|---|---|---|"]
        for r in wrong_rows:
            c = r["_c"]
            why = "; ".join(c["why"] + [f"unknown {u}" for u in c["unknown"]]) or \
                f"in-cell by the gate; fill stop over {config.VIVEK_BOT_MAX_STOP_PCT:g}%"
            L.append(f"| {r['_market'].upper()} | {r['symbol']} | {why} | {c['plan_stop']:.2f}% | "
                     f"{c['fill_stop']:.2f}% |")
        L.append("")
    if stamped:
        L += [f"Recorded as A+ but taken at grade_raw A ({len(stamped)} of {len(op)} open): "
              + ", ".join(f"{r['symbol']} ({r['_market'].upper()})" for r in stamped)
              + ". In-cell either way -- A is in the sleeve -- but the book cannot say so; "
              "see the patch in section 5.", ""]
    if prose.get("wrong_after"):
        L += [prose["wrong_after"], ""]
    L += ["## 4. Freshness -- last 5.0 scan vs session + "
          f"{config.VIVEK_DECK_SESSION_GRACE_H}h (the deck's rule)", "",
          f"As of {now.strftime('%Y-%m-%d %H:%M')} UTC.", "",
          "| market | last scan (market time) | must be at/after | verdict | book written | coverage |",
          "|---|---|---|---|---|---|"]
    for f in fresh:
        ref = f["ref"].strftime("%Y-%m-%d %H:%M %Z") if f["ref"] is not None else "--"
        edge = f" ({f['edge']})" if f["edge"] else ""
        L.append(f"| {f['market'].upper()} | {f['generated_at']} | {ref}{edge} | "
                 f"{'STALE' if f['stale'] else 'fresh'} | {f['book_updated']} | "
                 f"{f['downloaded']}/{f['universe']} |")
    at_entry = []
    for r in op:
        e = scans.get(r["id"]) or {}
        if e.get("generated_at") and e.get("committed_at"):
            v = session_staleness(e["generated_at"], r["_market"],
                                  dt.datetime.fromisoformat(e["committed_at"]))
            at_entry.append((r, e, v["stale"]))
    stale_entries = [f"{r['symbol']} ({r['_market'].upper()}, scan {e['generated_at']}, "
                     f"taken {e['committed_at']})" for r, e, st in at_entry if st]
    ages = [int(e.get("data_age_days") or 0) for _, e, _ in at_entry]
    L += ["", f"At entry: {len(at_entry)} of {len(op)} open positions traced to the scan that "
          f"took them; {len(stale_entries)} were taken off a payload that was stale by the same "
          f"rule at the moment of the take"
          + (": " + "; ".join(stale_entries) if stale_entries else "")
          + f". Largest row data age at entry: {max(ages) if ages else '--'} day(s) "
          f"(the gate refuses over {config.VIVEK_BOT_MAX_DATA_AGE_DAYS}).",
          "", prose["fresh"], "", "## 5. The smallest patch that would restrict it (NOT applied)", "",
          prose["patch"], "", "## 6. The table -- every open and closed paper position", "",
          "grade = the grade the position was taken at (source in brackets); plan stop = the "
          "stop the gate tested (signal close); fill stop = the same stop at the fill; R = the "
          "journal's closed `realized_r`.", "",
          "| side | market | symbol | class | why out / unknown | grade | tf | trigger | level | "
          "plan stop | fill stop | cycle | entry | exit | R |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    order = {"in": 0, "unknown": 1, "out": 2}
    for r in sorted(rows, key=lambda r: (r["_side"] != "open", order[r["_c"]["cls"]],
                                         r["_market"], r.get("entry_date") or "", r["symbol"])):
        c = r["_c"]
        why = "; ".join(c["why"] + [f"unknown {u}" for u in c["unknown"]])
        g = c["grade"] or r.get("grade")
        L.append(f"| {r['_side']} | {r['_market'].upper()} | {r['symbol']} | {c['cls']} | {why} | "
                 f"{g} ({c['grade_src']}) | {r.get('timeframe')} | {r.get('entry_type')} | "
                 f"{r.get('level_tf') or '--'} | {_pct(c['plan_stop'])} | {_pct(c['fill_stop'])} | "
                 f"{r.get('cycle') or '--'} | {r.get('entry_date')} | "
                 f"{(r.get('exit_reason') or '') + ' ' + (r.get('exit_date') or '') if r['_side'] == 'closed' else 'open'} | "
                 f"{_r(r.get('realized_r')) if r['_side'] == 'closed' else '--'} |")
    return "\n".join(L) + "\n"


def read_prose(text: str) -> dict:
    """'@@ name' alone on a line starts a section; its body runs to the next
    marker. A diff hunk header ('@@ -650,6 +650,12 @@ ...') is body text."""
    out, key = {}, None
    for line in text.splitlines():
        if re.fullmatch(r"@@ [a-z_]+", line.strip()):
            key = line.strip()[3:]
            out[key] = []
        elif key is not None:
            out[key].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--prose", required=True, help="text file of '@@ name' sections: matches, "
                                                   "book_asof, gate, verdict, wrong, wrong_after, fresh, patch")
    ap.add_argument("--entry-scans", default=None, help="cache of entry_scans() output")
    ap.add_argument("--now", default=None, help="ISO time for the freshness check")
    a = ap.parse_args(argv)
    rows = load_book()
    cache = pathlib.Path(a.entry_scans) if a.entry_scans else None
    if cache and cache.exists():
        scans = json.loads(cache.read_text(encoding="utf-8"))
    else:
        scans = entry_scans(rows)
        if cache:
            atomic_write(cache, json.dumps(scans, indent=1, sort_keys=True) + "\n", newline="\n")
    now = dt.datetime.fromisoformat(a.now) if a.now else dt.datetime.now(dt.timezone.utc)
    prose = read_prose(pathlib.Path(a.prose).read_text(encoding="utf-8"))
    md = build_note(rows, scans, freshness(now), now, prose)
    atomic_write(pathlib.Path(a.out), md, newline="\n")
    print(f"bot_vs_cells: {len(rows)} positions -> {a.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
