"""NEXT100 Stage 1 -- what a NEW bot row records when it is taken, and the
horizon stamp. REPORT ONLY: nothing here may change which trades are taken.

  #1  a real fill through run_market carries the live cycle tag ('hc4-2')
      -- a behaviour test, so a broken stamp fails here instead of every hc4-2
      row landing untagged and PR-9..PR-16 reading zero forever;
  #2  the fill stamps: adv / adv_share, score, rank / rank_of, freed_by,
      trigger_bar (+ trigger_bar_forming), earnings {next, lookup};
  H   the horizon stamp (item 5's input): a runner still open on the first
      in-session run at VIVEK_BOT_HORIZON_STAMP_DAYS held.

Every stamp is on NEW rows only, and survives the one close writer.
"""
from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import pytest

import scanner.vivek as vivek
from scanner import config
from scanner.broker import vivek_guard
from scanner.broker import vivek_run as vr
from scanner.vivek_journal import _OPEN_ONLY_FIELDS, _close_remaining
from tests.test_vivek_run import (_aest, _enable, _fake_yf, _frame, _held, _mfile, _ny,
                                  _row, _write_market_book)

pytestmark = pytest.mark.risk

STAMPS = ("adv", "adv_share", "score", "rank", "rank_of", "trigger_bar_forming")


def _saved(tmp_path, market):
    return json.loads(_mfile(tmp_path, market).read_text(encoding="utf-8"))


# ── #1: the cycle tag on a REAL fill ─────────────────────────────────────────

def test_a_real_fill_is_tagged_with_the_live_cycle_and_carries_the_stamps(tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path)
    # A cycle is live (its literal, 'hc4-2', is pinned in test_level_gate.py),
    # so this test can never pass vacuously on an empty tag.
    assert config.VIVEK_BOT_CYCLE_TAG
    uni = [{"symbol": "BHP", "yf": "BHP.AX"}]
    bk = vr.run_market("asx", [_row(score=9)], {"BHP.AX": _frame(101.0)}, uni,
                       now=_aest(2024, 1, 2, 11, 0))
    (pos,) = bk["open"]
    (disk,) = _saved(tmp_path, "asx")["open"]
    for row in (pos, disk):                       # the run's view AND the saved file
        assert row["cycle"] == config.VIVEK_BOT_CYCLE_TAG
        assert row["adv"] == 101_000_000.0       # 101 x 1e6, the completed bars
        assert row["adv_share"] == round(2500.0 / 101_000_000.0, 8)
        assert row["score"] == 9
        assert (row["rank"], row["rank_of"]) == (1, 1)
        assert row["trigger_bar"] == "2024-01-01"   # was null on every row
        assert row["trigger_bar_forming"] is False
        assert "freed_by" not in row             # the book had room
        assert "earnings" not in row             # ASX is not an earnings-gated market


def test_no_active_cycle_means_no_cycle_key(tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "VIVEK_BOT_CYCLE_TAG", "")
    bk = vr.run_market("asx", [_row()], {"BHP.AX": _frame(101.0)},
                       [{"symbol": "BHP", "yf": "BHP.AX"}], now=_aest(2024, 1, 2, 11, 0))
    (pos,) = bk["open"]
    assert "cycle" not in pos                     # absent != empty


# ── #2: the fill stamps ──────────────────────────────────────────────────────

def test_the_trigger_bar_comes_from_the_plan_the_bot_walked_to(tmp_path, monkeypatch):
    """decide()'s ticket (the ringfenced plan_trade) never carries the trigger
    bar; the runner reads it off the scan row's own plan for the ticket's
    timeframe -- the 1W plan here, not the 1D one beside it."""
    from tests.test_vivek_run import _plan
    _enable(monkeypatch, tmp_path)
    plans = {"1W": _plan(entry_trigger="reclaim", trigger_bar="2024-01-05"),
             "1D": _plan(trigger_bar="2023-12-29")}
    bk = vr.run_market("asx", [_row(plans=plans)], {"BHP.AX": _frame(101.0)},
                       [{"symbol": "BHP", "yf": "BHP.AX"}], now=_aest(2024, 1, 2, 11, 0))
    (pos,) = bk["open"]
    assert pos["timeframe"] == "1W" and pos["trigger_bar"] == "2024-01-05"
    assert pos["trigger_bar_forming"] is True     # that week ends Fri 5 Jan


def test_an_exempt_adv_is_recorded_as_null_with_no_share(tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path)
    frame = _frame(101.0).drop(columns=["Volume"])     # no volume -> no adv_usd
    bk = vr.run_market("asx", [_row()], {"BHP.AX": frame},
                       [{"symbol": "BHP", "yf": "BHP.AX"}], now=_aest(2024, 1, 2, 11, 0))
    (pos,) = bk["open"]
    assert pos["adv"] is None and "adv_share" not in pos


def test_rank_is_the_place_among_the_runs_slot_candidates(tmp_path, monkeypatch):
    """One slot, three takeable rows: A is refused at the fill (earnings), the
    refill hands its slot to B. B is 2nd of the 3 that wanted a slot."""
    from tests.test_vivek_run import _one_slot_left
    uni, frames, _ = _one_slot_left(tmp_path, monkeypatch, ["AAA", "BBB", "CCC"], {"AAA.AX"})
    rows = [_row(s) for s in ("AAA", "BBB", "CCC")]
    bk = vr.run_market("asx", rows, frames, uni, now=_aest(2024, 1, 2, 11, 0))
    new = [p for p in bk["open"] if p["symbol"] in ("AAA", "BBB", "CCC")]
    assert [p["symbol"] for p in new] == ["BBB"]
    assert (new[0]["rank"], new[0]["rank_of"]) == (2, 3)


def test_slot_queue_keeps_walk_order_and_only_slot_seekers():
    rows = [{"symbol": s} for s in ("A", "B", "C", "D", "E")]
    d1 = {"plans": [{"plan": {"symbol": "C"}}],
          "skipped": [{"code": "global_cap", "symbol": "E"},
                      {"code": "dup_symbol", "symbol": "A"},      # already held
                      {"code": "low_rr"}]}                          # not takeable
    d2 = {"plans": [{"plan": {"symbol": "B"}}], "skipped": []}
    assert vr._slot_queue(rows, [d1]) == ["C", "E"]
    assert vr._slot_queue(rows, [d1, d2]) == ["B", "C", "E"]


def _rotation(tmp_path, monkeypatch, cap):
    _enable(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_OPEN_TOTAL", cap)
    _write_market_book(tmp_path, "asx", open_=[_held("STOPME"), _held("KEEP")])
    uni = [{"symbol": s, "yf": f"{s}.AX"} for s in ("STOPME", "KEEP", "NEW")]
    frames = {"STOPME.AX": _frame(95.0), "KEEP.AX": _frame(101.0), "NEW.AX": _frame(101.0)}
    return vr.run_market("asx", [_row("NEW")], frames, uni, now=_aest(2024, 1, 2, 11, 0))


def test_a_fill_into_a_slot_this_run_freed_names_the_row_that_freed_it(tmp_path, monkeypatch):
    bk = _rotation(tmp_path, monkeypatch, cap=2)          # full until STOPME stopped
    (new,) = [p for p in bk["open"] if p["symbol"] == "NEW"]
    assert new["freed_by"] == {"id": "STOPME-1", "exit_reason": "stop"}


def test_a_fill_with_room_to_spare_has_no_freed_by(tmp_path, monkeypatch):
    bk = _rotation(tmp_path, monkeypatch, cap=3)
    (new,) = [p for p in bk["open"] if p["symbol"] == "NEW"]
    assert "freed_by" not in new


def test_stamps_are_for_new_rows_only(tmp_path, monkeypatch):
    bk = _rotation(tmp_path, monkeypatch, cap=3)
    (keep,) = [p for p in bk["open"] if p["symbol"] == "KEEP"]
    assert not any(k in keep for k in STAMPS + ("freed_by", "earnings"))
    assert keep["trigger_bar"] is None               # never restated


def _nasdaq_fill(tmp_path, monkeypatch, dates):
    _enable(monkeypatch, tmp_path)
    assert "nasdaq" in config.VIVEK_BOT_EARNINGS_MARKETS
    monkeypatch.setattr(vr, "_EARNINGS_CACHE", {})
    _fake_yf(monkeypatch, dates, [])
    bk = vr.run_market("nasdaq", [_row("AAPL")], {"AAPL": _frame(101.0)},
                       [{"symbol": "AAPL", "yf": "AAPL"}], now=_ny(2024, 1, 3, 12, 0))
    (pos,) = bk["open"]
    return pos


def test_a_nasdaq_fill_records_the_next_report_the_buffer_saw(tmp_path, monkeypatch):
    pos = _nasdaq_fill(tmp_path, monkeypatch, [dt.date(2023, 10, 20), dt.date(2024, 1, 25)])
    assert pos["earnings"] == {"next": "2024-01-25", "lookup": "ok"}


def test_a_failed_earnings_lookup_is_visible_on_the_row(tmp_path, monkeypatch):
    """It still fails OPEN (the fill is taken), but the row now says so."""
    pos = _nasdaq_fill(tmp_path, monkeypatch, RuntimeError)
    assert pos["earnings"] == {"next": None, "lookup": "failed"}


def test_no_report_listed_is_ok_with_no_next(tmp_path, monkeypatch):
    pos = _nasdaq_fill(tmp_path, monkeypatch, [])
    assert pos["earnings"] == {"next": None, "lookup": "ok"}


# trigger_bar_forming: the bar's LAST day from its label, per timeframe.

@pytest.mark.parametrize("tf,bar,now,want", [
    ("1W", "2026-11-06", _aest(2026, 11, 3, 11, 0), True),    # the week ends Friday
    ("1W", "2026-10-30", _aest(2026, 11, 3, 11, 0), False),
    ("3D", "2026-10-31", _aest(2026, 11, 3, 11, 0), False),   # Oct 31 - Nov 2
    ("3D", "2026-11-03", _aest(2026, 11, 4, 11, 0), True),    # Nov 3 - Nov 5
    ("1D", "2026-11-03", _aest(2026, 11, 3, 11, 0), True),    # today, in session
    ("1D", "2026-11-03", _aest(2026, 11, 3, 16, 30), False),  # today, after the close
    ("1D", "2026-11-02", _aest(2026, 11, 3, 11, 0), False),
    ("4H", "2026-11-03", _aest(2026, 11, 3, 11, 0), None),    # not a traded timeframe
    ("1D", None, _aest(2026, 11, 3, 11, 0), None),
    ("1D", "junk", _aest(2026, 11, 3, 11, 0), None),
])
def test_trigger_bar_forming(tf, bar, now, want):
    assert vr._trigger_bar_forming("asx", tf, bar, now) is want


@pytest.mark.parametrize("tf,resample", [("1W", vivek._resample_weekly_ohlc),
                                         ("3D", vivek._resample_3day_ohlc)])
def test_the_bar_end_offsets_match_the_real_resamplers(tf, resample):
    """Every COMPLETE bin's last day is its label + the offset (the last bin
    may be partial, so it is left out)."""
    idx = pd.date_range("2026-09-01", "2026-11-20", freq="D")
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Volume": 1.0,
                       "Close": [float(d.toordinal()) for d in idx]}, index=idx)
    out = resample(df).iloc[:-1]
    offs = {(pd.Timestamp.fromordinal(int(c)).date() - lab.date()).days
            for lab, c in out["Close"].items()}
    assert offs == {vr._BAR_END_OFFSET_DAYS[tf]}
    assert vr._BAR_END_OFFSET_DAYS["1D"] == 0
    assert set(vr._BAR_END_OFFSET_DAYS) == set(config.VIVEK_BOT_ENTRY_CELLS)


# ── H: the horizon stamp ─────────────────────────────────────────────────────

def test_the_horizon_day_is_derived_from_the_time_stop():
    assert config.VIVEK_BOT_HORIZON_STAMP_DAYS == config.VIVEK_BOT_MAX_HOLD_DAYS + 1 == 29


def _runner(symbol="RUN"):
    """Past TP1 (a quarter booked at 106, stop at break-even): the time stop
    exempts it, so it is still open on day 29."""
    return _held(symbol, tp1_hit=True, stop=100.0, booked_pct=0.25,
                 exits=[{"reason": "tp1", "price": 106.0, "pct": 0.25, "date": "2024-01-10"}],
                 realized_r=0.375, gross_r=0.375, last_mark=110.0)


def _run(tmp_path, monkeypatch, rows, price, when, seed=True):
    if seed:
        _enable(monkeypatch, tmp_path)
        _write_market_book(tmp_path, "asx", open_=rows)
    uni = [{"symbol": p["symbol"], "yf": p["symbol"] + ".AX"} for p in rows]
    frames = {u["yf"]: _frame(price) for u in uni}
    return vr.run_market("asx", [], frames, uni, now=when)


def test_a_runner_is_stamped_once_on_its_first_run_at_the_horizon(tmp_path, monkeypatch):
    bk = _run(tmp_path, monkeypatch, [_runner()], 110.0, _aest(2024, 1, 29, 11, 0))
    assert "horizon" not in bk["open"][0]                   # held 28: not yet
    bk = _run(tmp_path, monkeypatch, [_runner()], 110.0, _aest(2024, 1, 30, 11, 0), seed=False)
    (pos,) = bk["open"]
    h = pos["horizon"]
    assert (h["day"], h["held"], h["tp1_hit"]) == ("2024-01-30", 29, True)
    assert h["booked"] == round(pos["realized_r"], 4)
    assert h["r"] == round(pos["realized_r"] + vivek_guard._unreal_r(pos, 110.0), 3)
    bk = _run(tmp_path, monkeypatch, [_runner()], 111.0, _aest(2024, 1, 31, 11, 0), seed=False)
    assert bk["open"][0]["horizon"] == h                    # written once


def test_a_pre_tp1_row_on_day_29_is_time_stopped_with_no_stamp(tmp_path, monkeypatch):
    bk = _run(tmp_path, monkeypatch, [_held("PRE")], 101.0, _aest(2024, 1, 30, 11, 0))
    (row,) = bk["closed"]
    assert row["exit_reason"] == "time" and "horizon" not in row


def test_a_row_closed_before_the_horizon_gets_none(tmp_path, monkeypatch):
    bk = _run(tmp_path, monkeypatch, [_held("EARLY")], 95.0, _aest(2024, 1, 11, 11, 0))
    (row,) = bk["closed"]
    assert row["exit_reason"] == "stop" and "horizon" not in row


def test_a_closed_session_run_stamps_nothing(tmp_path, monkeypatch):
    bk = _run(tmp_path, monkeypatch, [_runner()], 110.0, _aest(2024, 1, 30, 18, 0))
    assert "horizon" not in bk["open"][0]


def _boom(*a, **k):
    raise RuntimeError("stamp bug – test")      # non-ASCII on purpose


def test_a_raising_fill_stamp_never_costs_the_fill(tmp_path, monkeypatch, caplog):
    """REPORT ONLY: a bug in the stamps logs one ASCII WARNING; the fill, the
    cycle tag and the saved book all stand."""
    _enable(monkeypatch, tmp_path)
    monkeypatch.setattr(vr, "_stamp_fills", _boom)
    with caplog.at_level("WARNING", logger="vivek_run"):
        bk = vr.run_market("asx", [_row()], {"BHP.AX": _frame(101.0)},
                           [{"symbol": "BHP", "yf": "BHP.AX"}], now=_aest(2024, 1, 2, 11, 0))
    (pos,) = bk["open"]
    (disk,) = _saved(tmp_path, "asx")["open"]
    assert disk["id"] == pos["id"] and disk["cycle"] == config.VIVEK_BOT_CYCLE_TAG
    assert not any(k in disk for k in STAMPS)
    (warn,) = [r.getMessage() for r in caplog.records if "fill stamps skipped" in r.getMessage()]
    assert pos["id"] in warn and warn.isascii()


def test_a_raising_horizon_stamp_never_costs_the_run(tmp_path, monkeypatch, caplog):
    _enable(monkeypatch, tmp_path)
    _write_market_book(tmp_path, "asx", open_=[_runner()])
    monkeypatch.setattr(vr, "_stamp_horizon", _boom)
    with caplog.at_level("WARNING", logger="vivek_run"):
        bk = _run(tmp_path, monkeypatch, [_runner()], 110.0, _aest(2024, 1, 30, 11, 0),
                  seed=False)
    (pos,) = bk["open"]
    assert "horizon" not in pos and pos["unreal_r"] is not None
    assert _saved(tmp_path, "asx")["open"][0]["id"] == pos["id"]
    (warn,) = [r.getMessage() for r in caplog.records
               if "horizon stamp skipped" in r.getMessage()]
    assert warn.isascii()


def test_the_close_keeps_the_horizon_stamp(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, [_runner()], 110.0, _aest(2024, 1, 30, 11, 0))
    bk = _run(tmp_path, monkeypatch, [_runner()], 99.0, _aest(2024, 2, 1, 11, 0), seed=False)
    (row,) = bk["closed"]
    assert row["exit_reason"] == "trail" and row["horizon"]["day"] == "2024-01-30"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0.0, -1.0, None])
def test_a_bad_mark_stamps_nothing(bad, monkeypatch):
    pos = _runner()
    vr._stamp_horizon(pos, bad, "2024-01-30")
    assert "horizon" not in pos
    pos = dict(_runner(), realized_r=float("nan"))
    vr._stamp_horizon(pos, 110.0, "2024-01-30")
    assert "horizon" not in pos


def test_the_horizon_is_off_with_the_time_stop(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_HORIZON_STAMP_DAYS", 0)
    pos = _runner()
    vr._stamp_horizon(pos, 110.0, "2024-03-30")
    assert "horizon" not in pos


# ── the one close writer keeps every stamp ───────────────────────────────────

def test_the_close_writer_keeps_every_stamp():
    stamps = {"cycle": "hc4-2", "adv": 1e8, "adv_share": 2.5e-05, "score": 9,
              "rank": 2, "rank_of": 3, "freed_by": {"id": "X-1", "exit_reason": "stop"},
              "trigger_bar": "2024-01-01", "trigger_bar_forming": False,
              "earnings": {"next": None, "lookup": "failed"},
              "d14": {"day": "2024-01-15"}, "horizon": {"day": "2024-01-30"}}
    assert not set(stamps) & set(_OPEN_ONLY_FIELDS)
    pos = dict(_held("BHP"), **stamps)
    _close_remaining(pos, 99.0, "2024-02-01", "manual", None)
    assert pos["status"] == "closed"
    assert {k: pos[k] for k in stamps} == stamps
