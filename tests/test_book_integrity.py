"""NEXT100 Stage 1 -- the book is the only track record, so its integrity
gate and its writer must be able to catch what would otherwise reach main.

  #7  `vivek_run --verify` proves the book APPEND-ONLY against git HEAD (a
      closed row never rewritten or dropped, an open row never vanishing,
      the closed count never falling -- bar the MAX_CLOSED trim, exactly) and
      checks every open row's money (entry/risk/units/notional finite > 0,
      a long's stop never below its original, booked_pct = its exits).
  #8  the book writes can never publish a bare NaN (JSON.parse rejects it and
      the deck, journal and status lamp all go blank), and a non-finite fill
      is refused instead of skipping the stop-cap check.
"""
from __future__ import annotations

import copy
import json
import logging
import shutil
import subprocess
import sys

import pytest

from scanner import config
from scanner.broker import vivek_run as vr
from tests.test_vivek_run import (_aest, _enable, _frame, _mfile, _row, _vpos,
                                  _write_market_book)

pytestmark = pytest.mark.risk


def _strict(text: str):
    """json.loads that refuses NaN / Infinity, as JSON.parse does."""
    def _no(tok):
        raise ValueError(f"non-JSON constant {tok}")
    return json.loads(text, parse_constant=_no)


def _closed(rid, r=1.25, **kw):
    row = _vpos(rid.split("-")[0], id=rid, status="closed", realized_r=r,
                exit_reason="stop", exit_date="2024-01-05", booked_pct=1.0,
                exits=[{"reason": "stop", "price": 95.0, "pct": 1.0, "date": "2024-01-05"}])
    row.update(kw)
    return row


# ── #7 (b): open-row money checks (no git needed) ────────────────────────────

def _probs_for(tmp_path, monkeypatch, row):
    _enable(monkeypatch, tmp_path)
    _write_market_book(tmp_path, "asx", open_=[row])
    vr._write_combined()
    return vr.verify_books()


def test_a_healthy_runner_passes(tmp_path, monkeypatch):
    row = _vpos(id="BHP-1", stop=100.0, booked_pct=0.25, realized_r=0.375,
                exits=[{"reason": "tp1", "price": 106.0, "pct": 0.25, "date": "2024-01-03"}])
    assert _probs_for(tmp_path, monkeypatch, row) == []


@pytest.mark.parametrize("over,needle", [
    ({"stop": 95.0}, "'stop' 95 is BELOW the original stop 96"),
    ({"units": float("nan")}, "'units' is not a finite number > 0"),
    ({"notional": 0.0}, "'notional' is not a finite number > 0"),
    ({"entry": None}, "'entry' is not a finite number > 0"),
    ({"risk": float("inf")}, "'risk' is not a finite number > 0"),
    ({"booked_pct": 0.25}, "'booked_pct' 0.25 does not match its exits' pct sum 0"),
    ({"booked_pct": 1.5}, "'booked_pct' is not in [0, 1]"),
    ({"realized_r": float("nan")}, "'realized_r' is not finite"),
    ({"stop": None}, "'stop' is not a finite number"),
])
def test_a_bad_open_row_fails_naming_market_id_and_field(tmp_path, monkeypatch, over, needle):
    probs = _probs_for(tmp_path, monkeypatch, _vpos(id="BHP-1", **over))
    assert any(p.startswith("asx: open BHP-1 ") and needle in p for p in probs), probs


def test_the_stop_check_has_float_slack_not_room(tmp_path, monkeypatch):
    """8-dp rounding puts entry - risk a hair off the stop it came from."""
    ok = _vpos(id="BHP-1", entry=12.23999977, risk=2.563042, stop=9.67695777)
    assert _probs_for(tmp_path, monkeypatch, ok) == []
    bad = _vpos(id="BHP-1", entry=12.23999977, risk=2.563042, stop=9.6769)
    assert any("BELOW the original" in p for p in _probs_for(tmp_path, monkeypatch, bad))


def test_the_committed_book_verifies_clean():
    """The real book, as committed: zero false alarms (resized rows included)."""
    for m in config.MARKETS:
        f = vr.ROOT / "journal" / f"vivek_bot_book.{m}.json"
        if f.exists():
            book = json.loads(f.read_text(encoding="utf-8"))
            assert vr._open_row_money_problems(m, book.get("open") or []) == []


# ── #7 (a): append-only against git HEAD ─────────────────────────────────────

def _git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", *args],
                   cwd=repo, check=True, capture_output=True)


@pytest.fixture
def committed(tmp_path, monkeypatch):
    """A git repo whose HEAD holds an ASX book with two open and two closed
    rows; returns (edit, verify): edit(fn) rewrites the working-tree book
    through fn(book) and re-derives the combined view, verify() runs the gate."""
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    repo = tmp_path / "repo"
    jdir = repo / "journal"
    jdir.mkdir(parents=True)
    _enable(monkeypatch, jdir)
    _write_market_book(jdir, "asx",
                       open_=[_vpos("BHP", id="BHP-1"), _vpos("CBA", id="CBA-1")],
                       closed=[_closed("OLD-1"), _closed("MID-1", r=-1.0)])
    vr._write_combined()
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")

    def edit(fn):
        book = json.loads(_mfile(jdir, "asx").read_text(encoding="utf-8"))
        fn(book)
        _mfile(jdir, "asx").write_text(json.dumps(book), encoding="utf-8")
        vr._write_combined()

    return edit, vr.verify_books


def test_an_untouched_book_is_clean(committed):
    _, verify = committed
    assert verify() == []


def test_closing_an_open_row_and_appending_is_legal(committed):
    edit, verify = committed

    def close(b):
        row = b["open"].pop(0)
        row.update(status="closed", realized_r=-1.0)
        b["closed"].append(row)
    edit(close)
    assert verify() == []


def test_a_rewritten_closed_r_fails(committed):
    edit, verify = committed
    edit(lambda b: b["closed"][1].update(realized_r=2.0))
    probs = verify()
    assert any("asx: closed MID-1 was REWRITTEN (realized_r)" in p for p in probs), probs


def test_a_dropped_open_row_fails(committed):
    edit, verify = committed
    edit(lambda b: b["open"].pop(1))
    probs = verify()
    assert any("asx: open CBA-1 VANISHED" in p for p in probs), probs


def test_a_removed_closed_row_fails_and_the_count_may_not_fall(committed):
    edit, verify = committed
    edit(lambda b: b["closed"].pop(1))
    probs = verify()
    assert any("asx: closed MID-1 is GONE" in p for p in probs), probs
    assert any("closed count fell from 2 to 1" in p for p in probs), probs


def test_the_max_closed_trim_drops_exactly_the_oldest(committed, monkeypatch):
    edit, verify = committed
    monkeypatch.setattr(vr, "MAX_CLOSED", 2)

    def trim_oldest(b):
        b["closed"] = b["closed"][1:] + [_closed("NEW-1")]
    edit(trim_oldest)
    assert verify() == []

    def trim_middle(b):                       # HEAD held [OLD-1, MID-1]
        b["closed"] = [_closed("OLD-1"), _closed("NEW-2")]     # dropped MID-1, kept OLD-1
    edit(trim_middle)
    assert any("MID-1 is GONE" in p for p in verify())


def test_a_tampered_stop_and_nan_units_fail_the_same_gate(committed):
    edit, verify = committed

    def tamper(b):
        b["open"][0]["stop"] = 90.0
        b["open"][1]["units"] = float("nan")
    edit(tamper)
    probs = verify()
    assert any("open BHP-1 'stop' 90 is BELOW" in p for p in probs), probs
    assert any("open CBA-1 'units'" in p for p in probs), probs


def test_no_git_is_a_notice_not_a_failure(tmp_path, monkeypatch, caplog):
    _enable(monkeypatch, tmp_path)                    # tmp_path is no git checkout
    _write_market_book(tmp_path, "asx", open_=[_vpos(id="BHP-1")])
    vr._write_combined()
    with caplog.at_level(logging.INFO, logger="vivek_run"):
        assert vr.verify_books() == []
    notes = [r.getMessage() for r in caplog.records if "NOTICE" in r.getMessage()]
    assert len(notes) == 1 and "append-only check vs git HEAD skipped" in notes[0]


def test_the_cli_verify_passes_on_the_committed_book():
    """`python -m scanner.broker.vivek_run --verify` on the real checkout:
    green, and the append-only leg really ran against HEAD."""
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    got = subprocess.run([sys.executable, "-m", "scanner.broker.vivek_run", "--verify"],
                         cwd=vr.ROOT, capture_output=True, text=True, timeout=120)
    assert got.returncode == 0, got.stdout + got.stderr
    assert "book verify OK" in got.stdout
    assert "append-only check vs HEAD over" in got.stdout + got.stderr \
        or "NOTICE" in got.stdout + got.stderr


# ── #8: NaN-proof writes and fills ───────────────────────────────────────────

def test_a_nan_in_a_row_is_written_as_null_and_named_once(tmp_path, monkeypatch, caplog):
    _enable(monkeypatch, tmp_path)
    book = {"open": [_vpos(id="BHP-1", mae_r=float("nan"), unreal_usd=float("inf"))],
            "closed": [_closed("OLD-1")]}
    with caplog.at_level(logging.WARNING, logger="vivek_run"):
        vr._save_market_book("asx", copy.deepcopy(book))
    for path in (_mfile(tmp_path, "asx"), vr.BOOK_FILE, vr.PUBLIC_FILE):
        saved = _strict(path.read_text(encoding="utf-8"))   # parses as JSON.parse would
        (row,) = [r for r in saved["open"] if r.get("id") == "BHP-1"]
        assert row["mae_r"] is None and row["unreal_usd"] is None
    warns = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1
    assert "open:BHP-1 mae_r" in warns[0] and "open:BHP-1 unreal_usd" in warns[0]
    assert warns[0].isascii()


def test_the_combined_view_scrubs_what_it_folds_in_too(tmp_path, monkeypatch):
    """The combined view also folds in the preserved unassigned entries, read
    with a NaN-tolerant json.loads: its own writer must scrub as well."""
    _enable(monkeypatch, tmp_path)
    _write_market_book(tmp_path, "asx", open_=[_vpos(id="BHP-1")])
    vr.UNASSIGNED_FILE.write_text(json.dumps(
        {"entries": [_vpos("ODD", market="lse", id="ODD-1", mae_r=float("nan"))]}),
        encoding="utf-8")
    vr._write_combined()
    for path in (vr.BOOK_FILE, vr.PUBLIC_FILE):
        saved = _strict(path.read_text(encoding="utf-8"))
        (odd,) = [r for r in saved["open"] if r.get("id") == "ODD-1"]
        assert odd["mae_r"] is None


def test_a_finite_book_writes_byte_for_byte_as_before(tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path)
    book = {"open": [_vpos(id="BHP-1")], "closed": [_closed("OLD-1")]}
    vr._save_market_book("asx", book)
    assert _mfile(tmp_path, "asx").read_text(encoding="utf-8") == json.dumps(book, indent=2)


def _ticket(**kw):
    p = {"symbol": "BHP", "name": "BHP", "sector": "", "direction": "long",
         "grade": "A+", "entry_type": "reclaim", "entry_type_label": "Reclaim",
         "timeframe": "1D", "entry": 100.0, "stop": 96.0,
         "tp1": 106.0, "tp2": 112.0, "tp3": 120.0, "scale": [0.25, 0.50, 0.15],
         "units": 25.0, "notional": 2500.0, "rr": 3.0, "leverage": 1.0,
         "leverage_target": 5, "risk_pct": 0.25, "risk_usd": 100.0}
    p.update(kw)
    return {"plan": p}


@pytest.mark.parametrize("fill", [float("nan"), float("inf"), 0.0, -101.0, None, "x"])
def test_a_non_finite_or_non_positive_fill_is_refused(fill, caplog):
    with caplog.at_level(logging.INFO, logger="vivek_run"):
        assert vr._ticket_to_position(_ticket(), fill, "asx", "2024-01-02") is None
    assert any("[bad_fill]" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("stop", [float("nan"), 0.0, -5.0])
def test_a_non_finite_or_non_positive_stop_is_refused(stop):
    assert vr._ticket_to_position(_ticket(stop=stop), 101.0, "asx", "2024-01-02") is None


def test_a_sound_fill_still_fills():
    pos = vr._ticket_to_position(_ticket(), 101.0, "asx", "2024-01-02")
    assert pos is not None and pos["entry"] == 101.0 and pos["risk"] == 5.0


def test_a_nan_quote_never_reaches_the_book(tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path)
    bk = vr.run_market("asx", [_row()], {"BHP.AX": _frame(float("nan"))},
                       [{"symbol": "BHP", "yf": "BHP.AX"}], now=_aest(2024, 1, 2, 11, 0))
    assert bk["open"] == []
    assert vr.LAST_SKIPS["asx"]["reasons"] == {"BHP": "refused_at_fill"}
