"""BACKFILL — reconstructing the history the rotation surface never had.

`sectorbreadth` started writing history on 2026-07-28, a week after the ASX
Consumer Discretionary run it was built to catch had already happened. The
streak could only ever say "1" and the trend column had nothing to trend, so
`scripts/backfill_sector_history.py` replays the real engine over past sessions
and writes the rows that would have been written.

A reconstruction that overstates itself is worse than none at all: it hands the
alarm a fabricated streak and pages the owner about a run that never happened.
So most of what is pinned below is not "does it compute the right number" but
"does it refuse to claim more than it knows" -- held written null rather than
zero before the book existed, real rows never overwritten by replayed ones,
re-running never double-counting, and a name that did not exist yet graded as
nothing rather than as flat.

REPORT-ONLY, like everything it feeds. These rows change what is SAID about a
sector and never what is taken in it.
"""

import datetime as dt
import importlib.util
import json
import pathlib

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from scanner import config
from scanner import sectorbreadth as sb

pytestmark = pytest.mark.risk

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load():
    """Import the script by path -- `scripts/` is not a package."""
    path = ROOT / "scripts" / "backfill_sector_history.py"
    spec = importlib.util.spec_from_file_location("_backfill", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bf = _load()


# ── builders ─────────────────────────────────────────────────────────────────

GRID = ["2026-06-24", "2026-06-25", "2026-06-26", "2026-06-29", "2026-06-30"]
HORIZON = "2026-06-28"          # the bot book's real earliest entry


def _uni(**sectors):
    out = []
    for sector, n in sectors.items():
        label = sector.replace("_", " ")
        out += [{"symbol": f"{sector[:2].upper()}{i}", "sector": label}
                for i in range(n)]
    return out


def _named(sector, n, grade="A+", days=None):
    """`n` names in `sector`, each graded on every day in `days`."""
    days = GRID if days is None else days
    return [(f"{sector[:2].upper()}{i}", sector, {"g": {d: grade for d in days}})
            for i in range(n)]


def _pos(symbol, sector, entry, exit_=None, market="asx"):
    return {"market": market, "symbol": symbol, "sector": sector,
            "entry": entry, "exit": exit_}


def _bounce_frame(periods=340, seed=7, start="2025-06-02"):
    """A frame the real engine actually grades -- same shape as test_vivek's."""
    rs = np.random.RandomState(seed)
    close = 100 + np.cumsum(rs.normal(0, 0.2, periods))
    close = close - (close.mean() - 100)
    close[-14:-4] = np.linspace(close[-15], 99.0, 10)
    close[-4:] = np.linspace(99.0, 101.5, 4)
    return pd.DataFrame({"Open": close * 0.999, "High": close * 1.01,
                         "Low": close * 0.99, "Close": close, "Volume": 2e6},
                        index=pd.bdate_range(start, periods=periods))


def _job(df, symbol="BHP", sector="Materials", grid=None, market="asx"):
    grid = grid or [str(d.date()) for d in df.index[-20:]]
    return (f"{symbol}.AX", symbol, sector, df.to_dict("records"),
            [str(t) for t in df.index], grid, market)


# ── the replay is the REAL engine, not a reimplementation ────────────────────

def test_the_replay_grades_with_the_shipped_engine():
    """The whole premise. If this walked a copy of the grading rules the
    reconstruction would drift from live the first time the engine changed, and
    nobody would notice because both sides would still be self-consistent."""
    df = _bounce_frame()
    _sym, _sec, res = bf.replay_name(_job(df))
    assert res["g"], "the engine grades this frame in test_vivek; it must here too"
    assert set(res["g"].values()) <= {"A+", "A", "B+", "WATCH"}


def test_only_bars_at_or_before_the_session_are_visible():
    """Point-in-time, and the entire discipline is one `df.loc[:day]`.

    Pinned by construction rather than by inspection: replaying a single early
    session must give the same grade whether or not the future exists in the
    frame handed in. If truncation ever regressed, a reconstruction would be
    grading June with July's bars and would look BETTER, not broken.
    """
    df = _bounce_frame()
    cut = str(df.index[-30].date())
    full = bf.replay_name(_job(df, grid=[cut]))[2]["g"]
    truncated = bf.replay_name(_job(df.loc[:cut], grid=[cut]))[2]["g"]
    assert full == truncated


def test_a_name_with_too_few_bars_is_absent_not_flat():
    """A name listed last month did not have a bad June, it had no June. Grading
    it off 50 bars would invent a setup out of a lookback the engine cannot
    fill, and every such name would land in some sector's numerator."""
    df = _bounce_frame()
    grid = [str(d.date()) for d in df.index[-10:]]
    short = df.iloc[-(config.VIVEK_SMA - 20):]
    assert bf.replay_name(_job(short, grid=grid))[2]["g"] == {}


def test_one_exploding_name_does_not_take_the_market_with_it():
    """2,200 names replay in one process pool; a single malformed frame must cost
    that name's row, not the run. Live scan.py swallows the same exception."""
    df = _bounce_frame()
    broken = df.copy()
    broken["Close"] = np.nan
    grid = [str(d.date()) for d in df.index[-5:]]
    assert bf.replay_name(_job(broken, grid=grid))[2]["g"] == {}


def test_hysteresis_is_threaded_forward_across_the_walk(monkeypatch):
    """Live holds a grade across scans through small score wobble, keyed by
    symbol. A replay that started every session cold would grade the same tape
    lower than the board did and understate participation on every reconstructed
    session -- invisibly, because the output would still be a page of grades.

    Pinned on the CALL and not on the output, deliberately. On a tape steady
    enough to grade A+ throughout, the held answer and the cold answer are
    identical, so comparing the two proves nothing: the chain has to be observed
    being handed forward.
    """
    from scanner import vivek
    seen = []
    real = vivek.apply_grade_hysteresis

    def _spy(score, raw_grade, prev_grade, *a, **kw):
        seen.append(prev_grade)
        return real(score, raw_grade, prev_grade, *a, **kw)

    monkeypatch.setattr(vivek, "apply_grade_hysteresis", _spy)
    df = _bounce_frame()
    grid = [str(d.date()) for d in df.index[-25:]]
    graded = bf.replay_name(_job(df, grid=grid))[2]["g"]
    assert len(graded) > 5 and len(seen) == len(graded)
    assert seen[0] is None                                # session one is cold
    # Exactly one cold call for the whole walk. Reset-per-day would give 25.
    assert sum(1 for p in seen if p is None) == 1


# ── held: the line the alarm's credibility rests on ──────────────────────────

def test_sessions_before_the_book_record_held_as_null_never_zero():
    """THE test. `unheld_streak` counts sessions a sector led while the book held
    nothing; the book's memory starts 2026-06-28. Writing 0 for the ~100 earlier
    sessions would have manufactured a six-month streak for every sector on the
    board and fired the Discord alarm on all of them the first time this ran."""
    rows = bf.build_rows("asx", _named("Consumer Discretionary", 6),
                         GRID, _uni(Consumer_Discretionary=20, Materials=20),
                         [_pos("MA0", "Materials", HORIZON)], HORIZON)
    by_day = {r["d"]: r for r in rows}
    for day in ("2026-06-24", "2026-06-25", "2026-06-26"):       # pre-horizon
        assert all(c[2] is None for c in by_day[day]["s"].values())
    for day in ("2026-06-29", "2026-06-30"):                     # book exists
        assert by_day[day]["s"]["Materials"][2] == 1
        assert by_day[day]["s"]["Consumer Discretionary"][2] == 0


def test_the_streak_stops_at_the_edge_of_what_is_known():
    """End to end with the real `unheld_streak`: five leading unheld sessions,
    only two of them after the book existed, so the honest answer is two."""
    rows = bf.build_rows("asx", _named("Consumer Discretionary", 6),
                         GRID, _uni(Consumer_Discretionary=20, Materials=20),
                         [], HORIZON)
    hist, _added, _skipped = bf.merge_rows({"rows": []}, rows, "asx")
    assert sb.unheld_streak(hist, "asx", "Consumer Discretionary") == 2


def test_a_position_with_no_sector_is_still_counted():
    """28 of the 36 positions on the books ship sector-less. Dropping them would
    read the book as holding nothing of a sector it is actually in -- which is
    the precise input that fires the alarm."""
    uni = _uni(Consumer_Discretionary=20)
    sector_of = {u["symbol"]: u["sector"] for u in uni}
    blank = [_pos("CO0", "", "2026-06-01")]
    assert bf.held_on(blank, "asx", "2026-06-15", sector_of) == \
        {"consumer discretionary": 1}


def test_held_respects_entry_and_exit_dates_and_the_market():
    uni = _uni(Materials=20)
    sector_of = {u["symbol"]: u["sector"] for u in uni}
    pos = [_pos("MA0", "Materials", "2026-06-10", "2026-06-20"),
           _pos("MA1", "Materials", "2026-06-10", market="nasdaq")]
    assert bf.held_on(pos, "asx", "2026-06-09", sector_of) == {}     # before entry
    assert bf.held_on(pos, "asx", "2026-06-15", sector_of) == {"materials": 1}
    assert bf.held_on(pos, "asx", "2026-06-25", sector_of) == {}     # after exit
    assert bf.held_on(pos, "nasdaq", "2026-06-15", sector_of) == {"materials": 1}


def test_the_real_book_horizon_is_read_from_the_canonical_files():
    """Not hard-coded: the horizon has to move on its own as the book ages, or
    the null band would stay frozen at today's answer forever."""
    positions, horizon = bf.book_positions()
    assert positions and len(horizon) == 10 and horizon[4] == "-"
    assert all(p["market"] and p["symbol"] and p["entry"] for p in positions)


# ── rows are the SAME shape live rows are ────────────────────────────────────

def test_a_reconstructed_row_is_readable_by_the_live_consumers():
    """Same keys, same cell layout, so `trend` and `unheld_streak` need no
    knowledge that a row was replayed. A second format would be a second thing
    to keep in step and the first to fall out of it."""
    rows = bf.build_rows("asx", _named("Materials", 4), GRID,
                         _uni(Materials=20), [], HORIZON)
    live_keys = {"d", "m", "open", "max", "cap", "s"}
    assert live_keys <= set(rows[0]) and rows[0]["r"] == 1
    for cell in rows[0]["s"].values():
        assert len(cell) == 4
    hist = {"rows": rows}
    assert sb.trend(hist, "asx", "Materials")["days"] == len(GRID)


def test_reconstructed_rows_are_marked_so_the_caveats_stay_attached():
    """Survivorship and cold-start hysteresis are real and unfixable here. The
    marker is how a reader (or a later change) can tell which rows carry them."""
    rows = bf.build_rows("asx", _named("Materials", 4), GRID,
                         _uni(Materials=20), [], HORIZON)
    assert all(r.get("r") == 1 for r in rows)


def test_the_denominator_is_every_listed_name_not_only_the_graded_ones():
    """Rate is A+/A over names LISTED. Dividing by names that happened to grade
    would print 100% for a sector where one name in eighty set up."""
    rows = bf.build_rows("asx", _named("Materials", 4), GRID,
                         _uni(Materials=80, Financials=30), [], HORIZON)
    assert rows[0]["s"]["Materials"][:2] == [4, 80]
    assert rows[0]["s"]["Financials"][:2] == [0, 30]


def test_only_tradeable_grades_reach_the_numerator():
    """`compute` counts A+/A. A replay that counted every graded name would make
    every sector look like it was leading on every session."""
    rows = bf.build_rows("asx", _named("Materials", 5, grade="B+"), GRID,
                         _uni(Materials=20), [], HORIZON)
    assert rows[0]["s"]["Materials"][0] == 0


def test_a_name_with_no_sector_anywhere_is_dropped_not_bucketed_as_blank():
    rows = bf.build_rows("asx", [("ZZ9", "", {"g": {d: "A+" for d in GRID}})],
                         GRID, _uni(Materials=20), [], HORIZON)
    assert "" not in rows[0]["s"] and rows[0]["s"]["Materials"][0] == 0


# ── merge: a real row always wins ────────────────────────────────────────────

def test_a_real_session_is_never_overwritten_by_a_replayed_one():
    """The live scan saw the actual board with the actual book. A backfill can
    only ever fill gaps -- otherwise a re-run would quietly downgrade observed
    history to reconstructed history and take the held counts with it."""
    real = {"d": "2026-06-30", "m": "asx", "open": 3, "max": 30, "cap": 0,
            "s": {"Materials": [9, 20, 2, None]}}
    rows = bf.build_rows("asx", _named("Materials", 4), GRID,
                         _uni(Materials=20), [], HORIZON)
    hist, added, skipped = bf.merge_rows({"rows": [real]}, rows, "asx")
    assert (added, skipped) == (4, 1)
    kept = [r for r in hist["rows"] if r["d"] == "2026-06-30"][0]
    assert kept["s"]["Materials"] == [9, 20, 2, None] and "r" not in kept


def test_re_running_the_backfill_is_idempotent():
    """It is a manual workflow someone will fire twice. Twice must equal once,
    or the second run doubles the row count and every streak with it."""
    rows = bf.build_rows("asx", _named("Materials", 4), GRID,
                         _uni(Materials=20), [], HORIZON)
    hist, _a, _s = bf.merge_rows({"rows": []}, rows, "asx")
    once = json.dumps(hist, sort_keys=True)
    hist, _a, _s = bf.merge_rows(hist, rows, "asx")
    assert json.dumps(hist, sort_keys=True) == once


def test_a_backfill_of_one_market_leaves_the_other_alone():
    other = {"d": "2026-06-24", "m": "nasdaq", "open": 1, "max": 30, "cap": 0,
             "r": 1, "s": {"Technology": [4, 40, 0, None]}}
    rows = bf.build_rows("asx", _named("Materials", 4), GRID,
                         _uni(Materials=20), [], HORIZON)
    hist, _a, _s = bf.merge_rows({"rows": [other]}, rows, "asx")
    assert other in hist["rows"]


def test_rows_come_out_sorted_and_capped_like_the_live_writer():
    rows = bf.build_rows("asx", _named("Materials", 4), GRID,
                         _uni(Materials=20), [], HORIZON)
    hist, _a, _s = bf.merge_rows({"rows": []}, list(reversed(rows)), "asx")
    days = [r["d"] for r in hist["rows"]]
    assert days == sorted(days)
    assert hist["version"] == sb.HISTORY_VERSION


# ── the session grid ─────────────────────────────────────────────────────────

def test_a_thinly_covered_date_is_not_a_session():
    """One name carrying a stray date is a mis-dated row or a foreign holiday
    leaking in. Replaying it publishes a day the market apparently vanished, and
    a zero-participation day breaks every streak running through it."""
    idx = pd.bdate_range("2026-06-01", periods=10)
    frames = {f"N{i}": pd.DataFrame({"Close": range(10)}, index=idx)
              for i in range(20)}
    ghost = idx.tolist() + [pd.Timestamp("2026-05-04")]
    frames["ODD"] = pd.DataFrame({"Close": range(11)}, index=pd.DatetimeIndex(ghost))
    grid = bf.session_grid(frames, 0, 0.5)
    assert "2026-05-04" not in grid and len(grid) == 10


def test_the_still_forming_bar_is_dropped():
    """scan.py pins grades to completed bars. A reconstruction that graded off
    half of today would disagree with the live board on the one session the
    owner can check, which is the fastest way to lose trust in the other 125."""
    idx = pd.bdate_range(end="2026-07-28", periods=6)
    frames = {f"N{i}": pd.DataFrame({"Close": range(6)}, index=idx)
              for i in range(5)}
    tz = ZoneInfo(config.MARKETS["asx"].timezone)
    # MARKET-LOCAL: 11:00 in Melbourne, an hour into a session that closes 16:00.
    mid = dt.datetime(2026, 7, 28, 11, 0, tzinfo=tz)
    assert "2026-07-28" not in bf.session_grid(frames, 0, 0.5, "asx", now=mid)
    shut = dt.datetime(2026, 7, 28, 17, 30, tzinfo=tz)             # after the bell
    assert "2026-07-28" in bf.session_grid(frames, 0, 0.5, "asx", now=shut)
    tomorrow = dt.datetime(2026, 7, 29, 11, 0, tzinfo=tz)
    assert "2026-07-28" in bf.session_grid(frames, 0, 0.5, "asx", now=tomorrow)


def test_the_grid_takes_the_most_recent_sessions():
    idx = pd.bdate_range("2026-01-01", periods=200)
    frames = {"N": pd.DataFrame({"Close": range(200)}, index=idx)}
    grid = bf.session_grid(frames, 20, 0.5)
    assert len(grid) == 20 and grid[-1] == str(idx[-1].date())


def test_no_frames_is_an_empty_grid_not_a_crash():
    assert bf.session_grid({}, 10, 0.5) == []


# ── the report is the actual deliverable ─────────────────────────────────────

def test_the_report_names_the_longest_run_and_when_it_happened():
    """The owner's question was never "populate a trend column", it was "how do
    I not miss an entire sector running again". The answer is a sector, a length
    and two dates."""
    rows = bf.build_rows("asx", _named("Consumer Discretionary", 6), GRID,
                         _uni(Consumer_Discretionary=20, Materials=20),
                         [], HORIZON)
    hist, _a, _s = bf.merge_rows({"rows": []}, rows, "asx")
    text = "\n".join(bf.report(hist, "asx", HORIZON))
    assert "Consumer Discretionary" in text
    assert "5 sessions" in text and GRID[0] in text and GRID[-1] in text


def test_a_run_that_pre_dates_the_book_is_flagged_as_such():
    """Leading is all that can be claimed there; whether it was held is not
    knowable. An unflagged line would read as a miss that may never have been."""
    rows = bf.build_rows("asx", _named("Consumer Discretionary", 6), GRID,
                         _uni(Consumer_Discretionary=20), [], HORIZON)
    hist, _a, _s = bf.merge_rows({"rows": []}, rows, "asx")
    assert "pre-dates the book" in "\n".join(bf.report(hist, "asx", HORIZON))


def test_a_thin_sector_cannot_lead_the_report_either():
    """Same bar the live board applies. A 3-name sector with one setup reads 33%
    and would top the post-mortem forever."""
    rows = bf.build_rows("asx", _named("Tiny", 1) + _named("Materials", 6),
                         GRID, _uni(Tiny=3, Materials=40), [], HORIZON)
    hist, _a, _s = bf.merge_rows({"rows": []}, rows, "asx")
    assert rows[0]["s"]["Tiny"] == [1, 3, None, None]        # stored...
    assert "Tiny" not in "\n".join(bf.report(hist, "asx", HORIZON))  # ...never leads


def test_a_non_sector_bucket_cannot_lead_the_report_either():
    """"Unclassified" is 91/389 on the real ASX board -- above every genuine
    sector. It holds rank one every day unless excluded, pushing the sector that
    actually ran out of the top three and out of the post-mortem entirely."""
    rows = bf.build_rows("asx",
                         _named("Unclassified", 91) + _named("Materials", 6),
                         GRID, _uni(Unclassified=389, Materials=40), [], HORIZON)
    hist, _a, _s = bf.merge_rows({"rows": []}, rows, "asx")
    text = "\n".join(bf.report(hist, "asx", HORIZON))
    assert "Unclassified" not in text and "Materials" in text


def test_the_report_survives_a_market_with_nothing_in_it():
    assert bf.report({"rows": []}, "asx", HORIZON) == ["  no rows"]


# ── park and re-merge: how the CI push survives a race ───────────────────────

@pytest.fixture
def _history(tmp_path, monkeypatch):
    """Point the module's history file at a scratch copy."""
    path = tmp_path / "sector_history.json"
    path.write_text(json.dumps({"version": sb.HISTORY_VERSION, "rows": []}))
    monkeypatch.setattr(sb, "HISTORY_FILE", path)
    return path


def _park(tmp_path, rows, market="asx"):
    out = tmp_path / "rows.json"
    bf.dump_rows(str(out), market, HORIZON, rows)
    return str(out)


def test_a_parked_reconstruction_survives_the_replay_being_thrown_away(tmp_path):
    """The replay costs half an hour; the push it feeds can lose a race. Parking
    the rows outside the repo is what lets a retry re-merge instead of re-run."""
    rows = bf.build_rows("asx", _named("Materials", 4), GRID,
                         _uni(Materials=20), [], HORIZON)
    blob = json.loads(pathlib.Path(_park(tmp_path, rows)).read_text())
    assert blob["market"] == "asx" and blob["horizon"] == HORIZON
    assert blob["rows"] == rows


def test_merging_a_parked_run_into_a_file_a_scan_has_since_written(tmp_path, _history):
    """The race that actually happens: a live scan pushes a REAL row for today
    while the replay is still running. Re-applying our copy would revert it; the
    merge keeps it and fills only the sessions it has no answer for."""
    real = {"d": "2026-06-30", "m": "asx", "open": 3, "max": 30, "cap": 0,
            "s": {"Materials": [9, 20, 2, None]}}
    _history.write_text(json.dumps({"version": sb.HISTORY_VERSION, "rows": [real]}))
    rows = bf.build_rows("asx", _named("Materials", 4), GRID,
                         _uni(Materials=20), [], HORIZON)
    assert bf.merge_only(_park(tmp_path, rows)) == 0
    on_disk = json.loads(_history.read_text())
    kept = [r for r in on_disk["rows"] if r["d"] == "2026-06-30"][0]
    assert kept["s"]["Materials"] == [9, 20, 2, None]      # the scan's row won
    assert len(on_disk["rows"]) == len(GRID)


def test_the_retry_loop_converges_because_re_merging_is_idempotent(tmp_path, _history):
    """Five attempts run identical code. If the second changed the file the loop
    would push a different reconstruction each time it lost a race."""
    rows = bf.build_rows("asx", _named("Materials", 4), GRID,
                         _uni(Materials=20), [], HORIZON)
    parked = _park(tmp_path, rows)
    bf.merge_only(parked)
    once = _history.read_text()
    for _attempt in range(4):
        bf.merge_only(parked)
    assert _history.read_text() == once


def test_merge_only_refuses_an_empty_parked_file(tmp_path, _history):
    """A replay that found nothing must not be committed as a reconstruction of
    nothing -- that is a non-zero exit so the workflow step fails loudly."""
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"market": "asx", "horizon": HORIZON, "rows": []}))
    assert bf.merge_only(str(empty)) == 1
    assert json.loads(_history.read_text())["rows"] == []
