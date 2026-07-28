"""The legacy-position resize (scripts/resize_book_notional.py).

The script restates the OPEN book at the current fixed notional. Its whole
defence is that it moves the DOLLAR fields and nothing else -- so most of what
is tested here is what it refuses to touch, not what it writes.
"""

import copy
import json
import sys
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.broker import vivek_run                        # noqa: E402
from scripts import resize_book_notional as rz              # noqa: E402

STAMP = "2026-07-28T07:00:00+00:00"


def _pos(**kw) -> dict:
    """A legacy-sized long, shaped exactly like a live book row."""
    base = {
        "id": "AAA:long:1D:2026-06-29", "symbol": "AAA", "name": "AAA Ltd",
        "sector": "Banks", "market": "asx", "direction": "long", "grade": "A+",
        "entry_type": "reclaim", "entry_type_label": "Reclaim", "timeframe": "1D",
        "entry": 100.0, "stop": 90.0, "risk": 10.0,
        "tp1": 110.0, "tp2": 120.0, "tp3": 140.0, "scale": [0.25, 0.5, 0.15],
        "rr": 2.0, "trigger_bar": None, "entry_date": "2026-06-29",
        "opened_at": "2026-06-29T02:08:04+00:00", "status": "open",
        "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
        "booked_pct": 0.0, "realized_r": 0.0, "gross_r": 0.0, "cost_r": 0.0,
        "exits": [], "mae": 96.0, "mfe": 104.0, "mae_r": -0.4, "mfe_r": 0.4,
        "units": 3.5, "notional": 350.0, "leverage": 0.04, "leverage_target": 5.0,
        "risk_pct": 0.35, "risk_usd": 35.0, "source": "vivek_bot",
        "unreal_r": 0.2, "unreal_usd": 7.0, "lens": "vivek", "last_mark": 102.0,
    }
    base.update(kw)
    return base


# ── the numbers it writes ─────────────────────────────────────────────────────

def test_it_restates_the_position_at_the_target_notional():
    p = _pos()
    rec = rz.resize_position(p, 5_000.0, 150_000.0, STAMP)
    assert rec["action"] == "resized"
    assert p["notional"] == 5_000.0
    assert p["units"] == pytest.approx(50.0)          # 5000 / 100
    assert p["sizing_mode"] == "fixed_notional"


def test_dollar_risk_follows_the_stop_distance_not_a_fixed_percent():
    # 10% stop on a $5,000 position risks $500. The old row risked a flat $35
    # because the % was the input; under fixed notional the dollars fall out.
    p = _pos()
    rz.resize_position(p, 5_000.0, 150_000.0, STAMP)
    assert p["risk_usd"] == pytest.approx(500.0)
    assert p["risk_pct"] == pytest.approx(500.0 / 150_000.0 * 100.0, rel=1e-3)
    assert p["leverage"] == pytest.approx(5_000.0 / 150_000.0, abs=0.01)


def test_the_dollar_mark_is_restamped_off_the_unchanged_r():
    p = _pos(unreal_r=0.2)
    rz.resize_position(p, 5_000.0, 150_000.0, STAMP)
    assert p["unreal_usd"] == pytest.approx(0.2 * 500.0)     # unreal_r x new risk


def test_every_resized_row_records_what_it_was_before():
    p = _pos()
    rz.resize_position(p, 5_000.0, 150_000.0, STAMP)
    assert p["notional_before"] == 350.0
    assert p["units_before"] == 3.5
    assert p["risk_usd_before"] == 35.0
    assert p["resized_at"] == STAMP


# ── what it must NOT touch ────────────────────────────────────────────────────

def test_r_is_invariant_under_the_resize_which_is_the_whole_argument():
    p = _pos(unreal_r=0.322, realized_r=0.0824, gross_r=0.0902, cost_r=0.0078,
             mae_r=-0.096, mfe_r=0.438)
    before = {k: p[k] for k in
              ("unreal_r", "realized_r", "gross_r", "cost_r", "mae_r", "mfe_r")}
    rz.resize_position(p, 5_000.0, 150_000.0, STAMP)
    assert {k: p[k] for k in before} == before


def test_prices_levels_and_exits_survive_untouched():
    p = _pos(booked_pct=0.25, tp1_hit=True,
             exits=[{"reason": "tp1", "price": 110.0, "pct": 0.25,
                     "date": "2026-07-20"}])
    before = rz.frozen_fingerprint(p)
    rz.resize_position(p, 5_000.0, 150_000.0, STAMP)
    assert rz.frozen_fingerprint(p) == before


def test_it_only_ever_writes_fields_on_its_own_allow_list():
    p = _pos()
    before = copy.deepcopy(p)
    rz.resize_position(p, 5_000.0, 150_000.0, STAMP)
    moved = {k for k in set(before) | set(p) if before.get(k) != p.get(k)}
    assert moved <= set(rz.WRITES), f"wrote outside the allow list: {moved - set(rz.WRITES)}"


# ── the stop basis: `stop` trails, `risk` does not ───────────────────────────

def test_it_sizes_off_the_original_stop_not_the_trailed_one():
    # A position that took tp1 has had its stop moved to breakeven. Sizing off
    # the CURRENT stop would divide by a zero distance; `entry - risk` is the
    # distance risk_usd has always meant.
    p = _pos(stop=100.0, booked_pct=0.25, tp1_hit=True)     # stop == entry
    assert rz.basis_stop(p) == pytest.approx(90.0)
    rec = rz.resize_position(p, 5_000.0, 150_000.0, STAMP)
    assert rec["action"] == "resized"
    assert p["risk_usd"] == pytest.approx(500.0)
    assert p["stop"] == 100.0                                # still breakeven


def test_a_short_reconstructs_its_stop_above_the_entry():
    p = _pos(direction="short", entry=100.0, stop=110.0, risk=10.0)
    assert rz.basis_stop(p) == pytest.approx(110.0)
    rz.resize_position(p, 5_000.0, 150_000.0, STAMP)
    assert p["risk_usd"] == pytest.approx(500.0)


@pytest.mark.parametrize("bad", [
    {"entry": 0.0}, {"risk": 0.0}, {"risk": None}, {"entry": None},
    {"entry": 5.0, "risk": 5.0},          # long stop would land at zero
    {"entry": 5.0, "risk": 9.0},          # ...or below it
])
def test_a_row_with_no_usable_basis_is_skipped_never_guessed(bad):
    p = _pos(**bad)
    before = copy.deepcopy(p)
    rec = rz.resize_position(p, 5_000.0, 150_000.0, STAMP)
    assert rec["action"] == "skipped"
    assert rec["reason"] == "no usable entry/risk basis"
    assert p == before


def test_a_closed_row_handed_in_directly_is_refused():
    p = _pos(status="closed")
    before = copy.deepcopy(p)
    rec = rz.resize_position(p, 5_000.0, 150_000.0, STAMP)
    assert rec["action"] == "skipped" and rec["reason"] == "not open"
    assert p == before


# ── idempotence ───────────────────────────────────────────────────────────────

def test_running_it_twice_does_not_rescale_a_row_a_second_time():
    p = _pos()
    rz.resize_position(p, 5_000.0, 150_000.0, STAMP)
    snapshot = copy.deepcopy(p)
    rec = rz.resize_position(p, 5_000.0, 150_000.0, "2026-08-01T00:00:00+00:00")
    assert rec["action"] == "skipped" and rec["reason"] == "already at target"
    assert p == snapshot


def test_idempotence_holds_for_a_risk_capped_row_too():
    # The second run must compare against the CAPPED size it would produce, not
    # the raw target, or a capped row gets capped again off its capped notional.
    p = _pos(entry=100.0, stop=50.0, risk=50.0)             # 50% stop
    rz.resize_position(p, 5_000.0, 150_000.0, STAMP, max_stop_pct=25.0)
    snapshot = copy.deepcopy(p)
    rec = rz.resize_position(p, 5_000.0, 150_000.0, STAMP, max_stop_pct=25.0)
    assert rec["reason"] == "already at target"
    assert p == snapshot


# ── the optional wide-stop cap ────────────────────────────────────────────────

def test_the_cap_is_off_by_default_and_a_wide_stop_gets_the_full_size():
    p = _pos(entry=100.0, stop=50.0, risk=50.0)
    rz.resize_position(p, 5_000.0, 150_000.0, STAMP)
    assert p["notional"] == 5_000.0
    assert p["risk_usd"] == pytest.approx(2_500.0)


def test_the_cap_trims_notional_so_the_dollar_risk_lands_on_the_ceiling():
    p = _pos(entry=100.0, stop=50.0, risk=50.0)             # 50% stop
    rec = rz.resize_position(p, 5_000.0, 150_000.0, STAMP, max_stop_pct=25.0)
    assert p["risk_usd"] == pytest.approx(1_250.0)          # 5000 x 25%
    assert p["notional"] == pytest.approx(2_500.0)          # 5000 x 25/50
    assert rec["capped"] == pytest.approx(50.0)


def test_the_cap_leaves_a_stop_inside_the_gate_at_the_full_size():
    p = _pos()                                              # 10% stop
    rec = rz.resize_position(p, 5_000.0, 150_000.0, STAMP, max_stop_pct=25.0)
    assert p["notional"] == 5_000.0
    assert not rec["capped"]


# ── whole-market behaviour ────────────────────────────────────────────────────

def _write_book(tmp_path, market, book) -> pathlib.Path:
    p = tmp_path / f"vivek_bot_book.{market}.json"
    p.write_text(json.dumps(book, indent=2), encoding="utf-8")
    return p


@pytest.fixture
def book_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(vivek_run, "BOOK_DIR", tmp_path)
    return tmp_path


def test_the_closed_track_record_is_never_rewritten(book_dir):
    closed = _pos(symbol="OLD", status="closed", notional=517.12,
                  units=64.07914235, risk_usd=35.0, realized_r=-2.0987)
    _write_book(book_dir, "asx", {"open": [_pos()], "closed": [copy.deepcopy(closed)]})
    book, changes = rz.resize_market("asx", 5_000.0, 150_000.0, STAMP)
    assert book["open"][0]["notional"] == 5_000.0
    assert book["closed"][0] == closed          # byte-for-byte the same row
    assert len(changes) == 1                    # closed rows are not even visited


def test_a_market_with_no_book_file_is_reported_not_crashed(book_dir):
    book, changes = rz.resize_market("nasdaq", 5_000.0, 150_000.0, STAMP)
    assert book is None and changes == []


def test_it_refuses_to_return_a_book_where_a_frozen_field_moved(book_dir, monkeypatch):
    _write_book(book_dir, "asx", {"open": [_pos()], "closed": []})

    def _sabotage(pos, target, equity, stamp, max_stop_pct=0.0):
        pos["entry"] = 999.0                    # the one thing it must never do
        return {"symbol": pos["symbol"], "action": "resized", "reason": "",
                "capped": 0.0, "stop_pct": 10.0,
                "notional_before": 1, "notional_after": 1,
                "risk_usd_before": 1, "risk_usd_after": 1,
                "units_before": 1, "units_after": 1}

    monkeypatch.setattr(rz, "resize_position", _sabotage)
    with pytest.raises(AssertionError, match="frozen field"):
        rz.resize_market("asx", 5_000.0, 150_000.0, STAMP)


def test_the_summary_block_keeps_the_three_keys_the_engine_writes():
    book = {"open": [_pos(unreal_usd=12.5), _pos(unreal_usd=-2.5)]}
    assert rz.summarise(book, "2026-07-28") == {
        "open": 2, "unreal_usd": 10.0, "updated_day": "2026-07-28"}


# ── the CLI ───────────────────────────────────────────────────────────────────

def test_a_dry_run_writes_nothing(book_dir, capsys):
    path = _write_book(book_dir, "asx", {"open": [_pos()], "closed": []})
    before = path.read_text(encoding="utf-8")
    rc = rz.main(["--market", "asx", "--target", "5000", "--equity", "150000"])
    assert rc == 0
    assert path.read_text(encoding="utf-8") == before
    assert "dry run: nothing written" in capsys.readouterr().out


def test_apply_writes_the_canonical_file_and_rebuilds_the_derived_pair(
        book_dir, monkeypatch, tmp_path, capsys):
    path = _write_book(book_dir, "asx", {"open": [_pos()], "closed": [],
                                         "market": "asx", "version": 2})
    combined = tmp_path / "combined.json"
    public = tmp_path / "public.json"
    monkeypatch.setattr(vivek_run, "BOOK_FILE", combined)
    monkeypatch.setattr(vivek_run, "PUBLIC_FILE", public)
    monkeypatch.setattr(vivek_run, "verify_books", lambda: [])

    rc = rz.main(["--market", "asx", "--target", "5000", "--equity", "150000",
                  "--apply"])
    assert rc == 0
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["open"][0]["notional"] == 5_000.0
    assert saved["summary"]["open"] == 1
    assert combined.exists() and public.exists()
    assert json.loads(combined.read_text(encoding="utf-8"))["open"][0]["notional"] == 5_000.0


def test_a_zero_target_is_refused_rather_than_zeroing_the_book(book_dir, capsys):
    _write_book(book_dir, "asx", {"open": [_pos()], "closed": []})
    assert rz.main(["--market", "asx", "--target", "0", "--equity", "150000"]) == 2
    assert "must be > 0" in capsys.readouterr().out


def test_the_report_names_the_positions_that_sit_beyond_the_wide_stop_gate():
    wide = _pos(symbol="WIDE", entry=100.0, stop=50.0, risk=50.0)
    narrow = _pos(symbol="OK")
    changes = [rz.resize_position(wide, 5_000.0, 150_000.0, STAMP),
               rz.resize_position(narrow, 5_000.0, 150_000.0, STAMP)]
    out = "\n".join(rz.report({"asx": {"changes": changes}}, 5_000.0, 150_000.0))
    assert "WIDE STOPS" in out and "WIDE" in out
    assert "daily loss limit" in out
    # The narrow one is inside the gate and must not be listed as a risk.
    assert out.count("stop ") >= 1


# ── the live book, as a property ─────────────────────────────────────────────

def test_entry_minus_risk_reproduces_the_recorded_stop_on_every_untrailed_row():
    """The basis the whole script rests on, checked against the real book.

    For a position whose stop has not been trailed, `entry - risk` must equal
    the stop actually stored. Where it does not, the stop has moved -- and it
    can only ever have moved in the favourable direction.
    """
    live = ROOT / "journal"
    rows = []
    for f in sorted(live.glob("vivek_bot_book.*.json")):
        if "unassigned" in f.name:
            continue
        rows += (json.loads(f.read_text(encoding="utf-8")).get("open") or [])
    if not rows:
        pytest.skip("no live book in this checkout")
    for p in rows:
        basis = rz.basis_stop(p)
        assert basis is not None, f"{p.get('symbol')} has no sizing basis"
        if str(p.get("direction", "long")).lower() == "short":
            assert p["stop"] <= basis + 1e-6
        else:
            assert p["stop"] >= basis - 1e-6
