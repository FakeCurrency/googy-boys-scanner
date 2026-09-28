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
    # NaN / inf (review F3, TOP100 #63): `nan <= 0` is False, so these used to
    # be RESIZED -- NaN written into units / risk_usd -- instead of skipped.
    {"risk": float("nan")}, {"entry": float("nan")},
    {"risk": float("inf")}, {"entry": float("inf")},
    {"risk": float("-inf")}, {"entry": float("-inf")},
    {"risk": "nan"}, {"entry": "inf"},    # as a string from a hand edit
    {"direction": "short", "risk": float("nan")},
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


# ══ the 2026-09-27 resize ($5,000 -> $2,500, owner-approved) ═════════════════
#
# Four things were added for the second use and each is pinned below: the row
# is sized at the SIGNAL it was sized at on entry (not the fill), its review
# flags are restated in review_flags' exact words, the market's guard block is
# restamped through the engine's one writer, and --check / --kick give the
# one-shot workflow a crash-distinguishable signal and a config-bound mandate.

from scanner import config                                    # noqa: E402
from scanner.broker import vivek_bot, vivek_guard             # noqa: E402

STAMP2 = "2026-09-28T00:00:00+00:00"


def _bot_row(fill=104.0, sig=100.0, stop=80.0, notional=5_000.0, **kw) -> dict:
    """A row shaped like one decide() opened: SIZED at the signal, filled later.

    `_ticket_to_position` copies the plan's units / notional / risk_usd, and the
    plan was sized at the signal close -- so units = notional / signal_entry and
    risk_usd = units x (signal_entry - stop), while `entry` / `risk` describe the
    fill. The defaults are a 20% stop, wide enough that the as-taken $1,000 1R
    (22% of the $4,500 guard) carried a review flag at the 15.0 threshold.
    """
    s = vivek_bot.size_position(150_000.0, sig, stop, notional_target=notional)
    base = dict(entry=fill, stop=stop, risk=round(fill - stop, 8),
                signal_entry=sig,
                fill_slip_bps=round((fill - sig) / sig * 1e4, 1),
                units=s["units"], notional=s["notional"], risk_usd=s["risk_usd"],
                risk_pct=s["risk_pct"], leverage=s["leverage"],
                sizing_mode=s["sizing_mode"], unreal_r=0.2,
                unreal_usd=round(0.2 * s["risk_usd"], 2))
    base.update(kw)
    return _pos(**base)


def _flags(risk, entry, stop, monkeypatch, thresh):
    """The REAL review_flags output for this ticket at `thresh`."""
    monkeypatch.setattr(config, "VIVEK_BOT_REVIEW_DAILY_LOSS_PCT", thresh)
    return vivek_bot.review_flags({"risk_usd": risk, "entry": entry, "stop": stop})


# ── A. signal-basis sizing ────────────────────────────────────────────────────

def test_a_bot_row_restates_by_exactly_the_target_ratio_because_it_is_sized_at_its_signal():
    p = _bot_row()                                   # fill 104, signal 100, stop 80
    units, risk = p["units"], p["risk_usd"]
    rec = rz.resize_position(p, 2_500.0, 150_000.0, STAMP2)
    assert rec["action"] == "resized" and rec["sized_at"] == "signal_entry"
    assert p["notional"] == 2_500.0
    assert p["units"] == pytest.approx(units * 0.5, rel=1e-12)
    assert p["risk_usd"] == pytest.approx(risk * 0.5, abs=0.005)
    # ...i.e. exactly what the bot would have booked had it opened at $2,500.
    fresh = vivek_bot.size_position(150_000.0, 100.0, 80.0, notional_target=2_500.0)
    assert (p["units"], p["risk_usd"]) == (fresh["units"], fresh["risk_usd"])


def test_sizing_at_the_fill_would_have_moved_the_risk_off_the_target_ratio():
    # The reason A exists, stated as a number: at the fill the same row would
    # risk 2500/104 x 24 = $576.92, not half of $1,000. A regression to fill
    # sizing turns the test above red and this one tells you why.
    fill_sized = vivek_bot.size_position(150_000.0, 104.0, 80.0, notional_target=2_500.0)
    assert fill_sized["risk_usd"] == pytest.approx(576.92, abs=0.01)
    assert fill_sized["risk_usd"] != pytest.approx(500.0, abs=0.01)


@pytest.mark.parametrize("sig", [None, 0.0, -5.0, float("nan"), float("inf"),
                                 "junk", 80.0, 79.0])
def test_a_row_with_no_usable_signal_is_sized_at_the_fill(sig):
    # absent / zero / negative / NaN / inf / unparseable / on-or-past the stop
    p = _bot_row()
    if sig is None:
        p.pop("signal_entry")
    else:
        p["signal_entry"] = sig
    rec = rz.resize_position(p, 2_500.0, 150_000.0, STAMP2)
    assert rec["action"] == "resized" and rec["sized_at"] == "entry"
    assert p["units"] == pytest.approx(2_500.0 / 104.0)
    assert p["risk_usd"] == pytest.approx(round(2_500.0 / 104.0 * 24.0, 2))


def test_a_short_signal_must_sit_below_its_stop_to_be_used():
    ok = _pos(direction="short", entry=100.0, stop=110.0, risk=10.0, signal_entry=98.0)
    bad = _pos(direction="short", entry=100.0, stop=110.0, risk=10.0, signal_entry=111.0)
    assert rz.sizing_price(ok, 110.0) == (98.0, "signal_entry")
    assert rz.sizing_price(bad, 110.0) == (100.0, "entry")


def test_the_optional_cap_is_measured_at_the_price_the_row_is_sized_at():
    # Signal 100 / stop 50 is a 50% stop to the sizer; capped at 25% the dollar
    # risk must land exactly on 2500 x 25% -- which it only does if the cap and
    # the sizer read the same price (the fill, 104, would read 51.9%).
    p = _bot_row(sig=100.0, stop=50.0, fill=104.0)
    rec = rz.resize_position(p, 2_500.0, 150_000.0, STAMP2, max_stop_pct=25.0)
    assert rec["capped"] == pytest.approx(50.0)
    assert p["risk_usd"] == pytest.approx(625.0)


def test_the_dollar_mark_moves_by_the_same_factor_as_the_risk():
    # unreal_usd is stamped off the UNROUNDED R; the stored 3-dp unreal_r would
    # put this one ~$0.20 off. Scaling keeps it within a cent of the engine.
    p = _bot_row(unreal_r=0.123, unreal_usd=123.4)       # R really 0.1234
    rz.resize_position(p, 2_500.0, 150_000.0, STAMP2)
    assert p["unreal_usd"] == pytest.approx(61.7)
    assert p["unreal_r"] == 0.123                          # R never moves


def test_signal_entry_is_frozen_and_the_review_pair_is_writable():
    assert {"signal_entry", "fill_slip_bps"} <= set(rz.FROZEN)
    assert {"review", "review_before"} <= set(rz.WRITES)
    assert not ({"review", "review_before"} & set(rz.FROZEN))


def test_a_flagged_bot_row_resize_only_writes_its_allow_list(monkeypatch):
    p = _bot_row()
    p["review"] = _flags(p["risk_usd"], 100.0, 80.0, monkeypatch, 15.0)
    before = copy.deepcopy(p)
    rz.resize_position(p, 2_500.0, 150_000.0, STAMP2)
    moved = {k for k in set(before) | set(p) if before.get(k) != p.get(k)}
    assert "review" in moved and "review_before" in moved
    assert moved <= set(rz.WRITES), moved - set(rz.WRITES)


# ── B. review flags ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("risk,entry,stop", [
    (406.77, 0.805, 0.67402159), (1_186.49, 141.99, 108.296), (250.0, 100.0, 90.0),
    (12_345.67, 50.0, 30.0), (0.49, 10.0, 9.99), (593.25, 141.99000549, 108.29602605)])
def test_the_rebuilt_note_is_worded_exactly_like_review_flags(risk, entry, stop,
                                                              monkeypatch):
    f = _flags(risk, entry, stop, monkeypatch, 0.001)[0]
    share = risk / f["limit_usd"] * 100.0
    assert rz.review_note(risk, share, f["limit_usd"],
                          abs(entry - stop) / entry * 100.0) == f["note"]


def test_a_restated_flag_is_byte_equal_to_review_flags_for_a_fresh_ticket_at_the_new_size(
        monkeypatch):
    # Taken at $5,000 under the 15.0 threshold; restated to $2,500 it must be
    # exactly what review_flags writes for a fresh $2,500 ticket under 7.5 --
    # the owner's pairing (notional and threshold halved together).
    p = _bot_row()
    taken = _flags(p["risk_usd"], 100.0, 80.0, monkeypatch, 15.0)
    assert taken, "fixture must be flagged at entry"
    p["review"] = copy.deepcopy(taken)
    rz.resize_position(p, 2_500.0, 150_000.0, STAMP2)
    fresh = _flags(p["risk_usd"], 100.0, 80.0, monkeypatch, 7.5)
    assert p["review"] == fresh
    assert json.dumps(p["review"]) == json.dumps(fresh)      # key order too
    assert p["review_before"] == taken
    assert p["review"][0]["stop_pct"] == taken[0]["stop_pct"]
    assert p["review"][0]["limit_usd"] == taken[0]["limit_usd"]


def test_a_restatement_never_adds_or_drops_a_flag(monkeypatch):
    # Whether the row was flagged is an ENTRY-time fact: a flagged row cut far
    # below any threshold stays flagged, and a clean row cut is not re-judged.
    # Each resize runs under the threshold that would make a RE-JUDGING
    # implementation fail: 50 would drop the flag, 0.001 would add one.
    flagged = _bot_row(review=[{"code": "heavy_risk", "share_pct": 22.2,
                                "stop_pct": 20.0, "risk_usd": 1000.0,
                                "limit_usd": 4500.0, "note": "n"}])
    monkeypatch.setattr(config, "VIVEK_BOT_REVIEW_DAILY_LOSS_PCT", 50.0)
    assert rz.resize_position(flagged, 100.0, 150_000.0, STAMP2)["action"] == "resized"
    clean = _bot_row(review=[])
    monkeypatch.setattr(config, "VIVEK_BOT_REVIEW_DAILY_LOSS_PCT", 0.001)
    assert rz.resize_position(clean, 100.0, 150_000.0, STAMP2)["action"] == "resized"
    assert len(flagged["review"]) == 1 and flagged["review"][0]["risk_usd"] == 20.0
    assert clean["review"] == []


def test_a_row_without_a_review_key_stays_without_one():
    # Absent (written before flags existed) != [] (checked, clean). A resize
    # must not manufacture either key on a row that never had one.
    p = _bot_row()
    assert "review" not in p
    rz.resize_position(p, 2_500.0, 150_000.0, STAMP2)
    assert "review" not in p and "review_before" not in p


def test_an_empty_review_list_is_kept_and_recorded_as_taken():
    p = _bot_row(review=[])
    rz.resize_position(p, 2_500.0, 150_000.0, STAMP2)
    assert p["review"] == [] and p["review_before"] == []


def test_an_unknown_flag_code_is_carried_verbatim():
    other = {"code": "something_else", "note": "keep me", "risk_usd": 1.0}
    p = _bot_row(review=[other])
    rz.resize_position(p, 2_500.0, 150_000.0, STAMP2)
    assert p["review"] == [other] and p["review_before"] == [other]


def test_review_before_keeps_the_list_as_taken_through_a_later_resize(monkeypatch):
    p = _bot_row()
    taken = _flags(p["risk_usd"], 100.0, 80.0, monkeypatch, 15.0)
    p["review"] = copy.deepcopy(taken)
    rz.resize_position(p, 2_500.0, 150_000.0, STAMP2)
    rz.resize_position(p, 1_000.0, 150_000.0, "2026-10-01T00:00:00+00:00")
    assert p["review_before"] == taken                   # not the $2,500 version
    assert p["review"] == _flags(p["risk_usd"], 100.0, 80.0, monkeypatch, 0.001)


def test_a_skipped_row_does_not_touch_its_flags():
    p = _bot_row(notional=2_500.0, review=[{"code": "heavy_risk", "risk_usd": 1.0,
                                            "limit_usd": 4500.0, "share_pct": 0.0,
                                            "stop_pct": 20.0, "note": "n"}])
    before = copy.deepcopy(p)
    assert rz.resize_position(p, 2_500.0, 150_000.0, STAMP2)["action"] == "skipped"
    assert p == before


# ── D. the guard block ────────────────────────────────────────────────────────

def _guarded_book(day="2026-09-26", notified="2026-09-26:daily") -> dict:
    row = _bot_row(entry_date="2026-09-22", last_mark=100.0,
                   day_marks={"2026-09-25": 104.0, "2026-09-26": 102.0})
    book = {"open": [row], "closed": [], "market": "asx", "version": 2}
    vivek_run._restamp(book, "asx", day)                 # the as-stored block
    book["guard"]["asx"]["notified"] = notified
    return book


def test_restamp_is_the_identity_on_an_unchanged_book():
    book = _guarded_book()
    before = copy.deepcopy(book)
    assert rz.restamp(book, "asx") == ("2026-09-26", True)
    assert book["guard"] == before["guard"] and book["summary"] == before["summary"]


def test_apply_restates_the_guard_for_the_same_session_at_the_new_size(
        book_dir, monkeypatch, tmp_path):
    book = _guarded_book()
    old = copy.deepcopy(book["guard"]["asx"])
    assert old["session_usd"] < 0 and old["week_usd"] < 0    # a real window to halve
    path = _write_book(book_dir, "asx", book)
    monkeypatch.setattr(vivek_run, "BOOK_FILE", tmp_path / "combined.json")
    monkeypatch.setattr(vivek_run, "PUBLIC_FILE", tmp_path / "public.json")
    monkeypatch.setattr(vivek_run, "verify_books", lambda: [])
    assert rz.main(["--market", "asx", "--target", "2500", "--equity", "150000",
                    "--apply"]) == 0
    saved = json.loads(path.read_text(encoding="utf-8"))
    g = saved["guard"]["asx"]
    assert g["day"] == old["day"]                         # same window, not a new one
    assert g["notified"] == old["notified"]               # carried, never re-announced
    assert g["session_usd"] == pytest.approx(old["session_usd"] / 2, abs=0.01)
    assert g["week_usd"] == pytest.approx(old["week_usd"] / 2, abs=0.01)
    expect = vivek_guard.check(saved, "asx", old["day"], 150_000.0,
                               lambda s: 100.0)
    assert g["session_usd"] == expect["session_usd"] and g["week_usd"] == expect["week_usd"]
    assert saved["summary"] == vivek_run._summary_of(saved, old["day"])
    assert set(saved["summary"]) == {"open", "unreal_usd", "updated_day"}


def test_restamp_falls_back_to_the_summary_day_then_the_market_local_today():
    book = {"open": [_bot_row(last_mark=100.0)], "closed": [],
            "summary": {"open": 1, "unreal_usd": 0.0, "updated_day": "2026-09-20"}}
    assert rz.restamp(book, "asx") == ("2026-09-20", True)
    assert book["guard"]["asx"]["day"] == "2026-09-20"
    bare = {"open": [_bot_row(last_mark=100.0)], "closed": []}
    day, ok = rz.restamp(bare, "asx")
    assert ok and len(day) == 10 and bare["guard"]["asx"]["day"] == day


# ── C. --check / --kick ───────────────────────────────────────────────────────

def _kick(tmp_path, text, name="resize-kick"):
    k = tmp_path / name
    k.write_text(text, encoding="utf-8")
    return k


@pytest.fixture
def isolated(book_dir, monkeypatch, tmp_path):
    """book_dir + the derived pair redirected into tmp, verify stubbed."""
    monkeypatch.setattr(vivek_run, "BOOK_FILE", tmp_path / "combined.json")
    monkeypatch.setattr(vivek_run, "PUBLIC_FILE", tmp_path / "public.json")
    monkeypatch.setattr(vivek_run, "verify_books", lambda: [])
    return book_dir


ARGS = ["--market", "asx", "--target", "5000", "--equity", "150000"]


def test_check_exits_three_when_rows_are_pending_and_writes_nothing(isolated, capsys):
    path = _write_book(isolated, "asx", {"open": [_pos()], "closed": []})
    before = path.read_bytes()
    assert rz.CHECK_PENDING_EXIT == 3
    assert rz.main(ARGS + ["--check"]) == 3
    assert path.read_bytes() == before
    assert not (isolated / "combined.json").exists()
    assert "CHECK: 1 open row(s) off" in capsys.readouterr().out


def test_check_exits_zero_when_every_row_is_at_target(isolated, capsys):
    _write_book(isolated, "asx", {"open": [_pos(notional=5_000.0)], "closed": []})
    assert rz.main(ARGS + ["--check"]) == 0
    assert "CHECK: 0 open row(s) off" in capsys.readouterr().out


def test_check_is_three_before_apply_and_zero_after_it(isolated):
    _write_book(isolated, "asx", {"open": [_pos()], "closed": [],
                                  "market": "asx", "version": 2})
    assert rz.main(ARGS + ["--check"]) == 3
    assert rz.main(ARGS + ["--apply"]) == 0
    assert rz.main(ARGS + ["--check"]) == 0


def test_check_with_apply_is_refused_before_anything_is_read(isolated, capsys):
    path = _write_book(isolated, "asx", {"open": [_pos()], "closed": []})
    before = path.read_bytes()
    assert rz.main(ARGS + ["--check", "--apply"]) == 2
    assert path.read_bytes() == before
    assert "cannot be combined" in capsys.readouterr().out


def test_an_unknown_flag_is_a_usage_error_not_a_pending_signal(isolated):
    with pytest.raises(SystemExit) as e:
        rz.main(ARGS + ["--chekc"])
    assert e.value.code == 2


@pytest.mark.parametrize("mode", [[], ["--check"], ["--apply"]])
def test_a_kick_that_disagrees_with_the_target_is_refused_in_every_mode(
        isolated, tmp_path, capsys, mode):
    path = _write_book(isolated, "asx", {"open": [_pos()], "closed": []})
    before = path.read_bytes()
    k = _kick(tmp_path, "# owner said 2500\ntarget=2500\n")
    assert rz.main(ARGS + ["--kick", str(k)] + mode) == 2      # target is 5000
    assert path.read_bytes() == before
    assert "refusing" in capsys.readouterr().out


def test_a_kick_within_a_cent_of_the_target_authorises_the_run(isolated, tmp_path, capsys):
    path = _write_book(isolated, "asx", {"open": [_pos()], "closed": [],
                                         "market": "asx", "version": 2})
    k = _kick(tmp_path, "# 2026-09-27 owner\n\ntarget=5000.004\n")
    assert rz.main(ARGS + ["--kick", str(k), "--check"]) == 3
    assert rz.main(ARGS + ["--kick", str(k), "--apply"]) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["open"][0]["notional"] == 5_000.0
    assert "matches --target" in capsys.readouterr().out
    k2 = _kick(tmp_path, "target=5000.01\n", name="k2")
    assert rz.main(ARGS + ["--kick", str(k2), "--check"]) == 2


def test_a_missing_kick_file_is_refused(isolated, tmp_path, capsys):
    _write_book(isolated, "asx", {"open": [_pos()], "closed": []})
    assert rz.main(ARGS + ["--kick", str(tmp_path / "absent")]) == 2
    assert "cannot be read" in capsys.readouterr().out
    with pytest.raises(ValueError, match="cannot be read"):
        rz.kick_target(tmp_path / "absent")


@pytest.mark.parametrize("text,why", [
    ("", "found 0"), ("# nothing\n\n", "found 0"),
    ("target=2500\ntarget=5000\n", "found 2"),
    ("target=2500\n# ok\ntarget=2500\n", "found 2"),       # even when they agree
    ("target=2500\napply=yes\n", "found 2"),                 # a stray line
    ("target=\n", "expected"), ("amount=2500\n", "expected"),
    ("target=2500 # inline\n", "expected"),
    ("target=abc\n", "not a number"), ("target=0\n", "positive"),
    ("target=-5\n", "positive"), ("target=nan\n", "positive"),
    ("target=inf\n", "positive")])
def test_a_malformed_kick_authorises_nothing(tmp_path, text, why):
    with pytest.raises(ValueError, match=why):
        rz.kick_target(_kick(tmp_path, text))


def test_the_kick_reads_its_one_target_line_past_comments_blanks_and_a_bom(tmp_path):
    k = tmp_path / "resize-kick"
    k.write_bytes("﻿# target=9999 in a comment is not a target\n"
                  "#\n\n  target = 2500  \n".encode("utf-8"))
    assert rz.kick_target(k) == 2500.0
    assert rz.kick_target(str(k)) == 2500.0                  # a str path too


# ── E. idempotence, with the new fields ───────────────────────────────────────

def test_a_second_apply_writes_no_file_and_leaves_the_review_pair_alone(
        isolated, tmp_path, monkeypatch):
    row = _bot_row()
    row["review"] = _flags(row["risk_usd"], 100.0, 80.0, monkeypatch, 15.0)
    monkeypatch.setattr(config, "VIVEK_BOT_REVIEW_DAILY_LOSS_PCT", 7.5)
    path = _write_book(isolated, "asx", {"open": [row], "closed": [],
                                         "market": "asx", "version": 2})
    args = ["--market", "asx", "--target", "2500", "--equity", "150000", "--apply"]
    assert rz.main(args) == 0
    first = json.loads(path.read_text(encoding="utf-8"))["open"][0]
    assert first["review_before"] == row["review"] and first["review"] != row["review"]
    files = [path, tmp_path / "combined.json", tmp_path / "public.json"]
    snap = [f.read_bytes() for f in files]
    # Bytes alone cannot prove it: the derived pair is stamped to the SECOND,
    # so a rebuild inside the same second is byte-identical. Count the writers.
    writes = []
    monkeypatch.setattr(rz, "atomic_write", lambda *a, **k: writes.append(a[0]))
    monkeypatch.setattr(vivek_run, "_write_combined", lambda: writes.append("combined"))
    assert rz.main(args) == 0
    assert writes == []
    assert [f.read_bytes() for f in files] == snap


# ── the live book, as a property (holds before AND after the apply) ──────────

def _live_open_rows() -> list[dict]:
    rows = []
    for f in sorted((ROOT / "journal").glob("vivek_bot_book.*.json")):
        if "unassigned" in f.name:
            continue
        rows += (json.loads(f.read_text(encoding="utf-8")).get("open") or [])
    return rows


def test_live_bot_rows_are_sized_at_their_signal_entry():
    """The convention the signal-basis resize rests on, on the real book."""
    rows = [p for p in _live_open_rows() if rz.basis_stop(p) is not None
            and rz.sizing_price(p, rz.basis_stop(p))[1] == "signal_entry"]
    if not rows:
        pytest.skip("no live bot rows carrying signal_entry in this checkout")
    for p in rows:
        sig = float(p["signal_entry"])
        # rel=1e-3: signal_entry is stored to 8 dp, a 1e-4-scale error on a
        # sub-cent coin. A fill-basis restatement misses by the slippage
        # (ASTS 6.6%, SMCI 5.1% on 2026-09-27), so the tolerance still bites.
        assert p["units"] * sig == pytest.approx(p["notional"], rel=1e-3), p["symbol"]
        assert p["units"] * abs(sig - rz.basis_stop(p)) == pytest.approx(
            p["risk_usd"], rel=1e-3, abs=0.05), p["symbol"]


def test_live_flags_restate_to_exactly_what_review_flags_would_write(monkeypatch):
    """Any target, any threshold: a restated flag == a fresh one at that size."""
    rows = [p for p in _live_open_rows() if p.get("review")
            and rz.sizing_price(p, rz.basis_stop(p))[1] == "signal_entry"]
    if not rows:
        pytest.skip("no flagged live bot rows in this checkout")
    for p in rows:
        q = copy.deepcopy(p)
        assert rz.resize_position(q, 1_234.0, 150_000.0, STAMP2)["action"] == "resized"
        fresh = _flags(q["risk_usd"], float(q["signal_entry"]), rz.basis_stop(q),
                       monkeypatch, 0.001)

        def drop(fl):
            return [{k: v for k, v in f.items() if k != "stop_pct"} for f in fl]
        assert drop(q["review"]) == drop(fresh), q["symbol"]
        assert [f["stop_pct"] for f in q["review"]] == [f["stop_pct"] for f in p["review"]]
        assert len(q["review"]) == len(p["review"])


# == review fixes (2026-09-28) =================================================
#
# F2  an off-target row the script CANNOT restate is "stuck": --check exits 4
#     (not 0), --apply exits 4 before writing anything.
# F4  a swallowed guard failure is reported as such, never as "restamped".
# C4  a restated row that already banked a partial exit is named in the report,
#     because its realised dollars (realized_r x risk_usd) restate with it.

ARGS2 = ["--market", "asx", "--target", "2500", "--equity", "150000"]


def _stuck_row(notional=5_000.0, **kw) -> dict:
    """An open row with no usable sizing basis (risk 0), at `notional`."""
    return _bot_row(symbol="NIC", risk=0.0, notional=notional, **kw)


def _snap(isolated):
    """Every file the script could write, as bytes (None when absent)."""
    names = ["vivek_bot_book.asx.json", "combined.json", "public.json"]
    return {n: ((isolated / n).read_bytes() if (isolated / n).exists() else None)
            for n in names}


def test_the_stuck_exit_is_a_distinct_named_code():
    assert rz.STUCK_EXIT == 4
    assert len({0, 1, 2, rz.CHECK_PENDING_EXIT, rz.STUCK_EXIT}) == 5


def test_a_stuck_row_at_the_old_size_makes_check_exit_four_not_zero(isolated, capsys):
    _write_book(isolated, "asx", {"open": [_stuck_row()], "closed": [],
                                  "market": "asx", "version": 2})
    before = _snap(isolated)
    assert rz.main(ARGS2 + ["--check"]) == rz.STUCK_EXIT
    out = capsys.readouterr().out
    # The line used to read "CHECK: 0 open row(s) off" over a $5,000 row.
    assert "CHECK: 1 open row(s) off the $2,500 target - 0 to restate, " \
           "1 off target but NOT restatable: NIC (asx)" in out
    assert "no usable entry/risk basis" in out
    assert _snap(isolated) == before


def test_apply_refuses_a_stuck_row_before_writing_anything(isolated, capsys):
    _write_book(isolated, "asx", {"open": [_stuck_row()], "closed": [],
                                  "market": "asx", "version": 2})
    before = _snap(isolated)
    assert rz.main(ARGS2 + ["--apply"]) == rz.STUCK_EXIT
    assert "REFUSED: 1 open row(s) off target cannot be restated (NIC (asx))" \
           in capsys.readouterr().out
    assert _snap(isolated) == before
    assert before["combined.json"] is None       # the derived pair not rebuilt


def test_an_unsizeable_row_already_at_the_target_is_not_stuck(isolated, capsys):
    # Nothing is left behind, so it must not turn the run red either.
    _write_book(isolated, "asx", {"open": [_stuck_row(notional=2_500.0)],
                                  "closed": [], "market": "asx", "version": 2})
    before = _snap(isolated)
    assert rz.main(ARGS2 + ["--check"]) == 0
    assert "CHECK: 0 open row(s) off the $2,500 target - 0 to restate, " \
           "0 off target but NOT restatable" in capsys.readouterr().out
    assert rz.main(ARGS2 + ["--apply"]) == 0         # a no-op, not a refusal
    assert _snap(isolated)["vivek_bot_book.asx.json"] == \
        before["vivek_bot_book.asx.json"]


def test_stuck_wins_on_check_and_apply_still_writes_nothing(isolated, capsys):
    # --check: 4 even with a restatable row pending (review RR-5, 2026-09-28):
    # --apply is certain to refuse, so the workflow's preview must go red
    # instead of queueing a writer into the one-slot scan mutex to do nothing.
    # --apply: 4 before any write, never half the book restated.
    ok = _bot_row(symbol="OK")
    _write_book(isolated, "asx", {"open": [ok, _stuck_row()], "closed": [],
                                  "market": "asx", "version": 2})
    before = _snap(isolated)
    assert rz.main(ARGS2 + ["--check"]) == rz.STUCK_EXIT
    assert "CHECK: 2 open row(s) off the $2,500 target - 1 to restate, " \
           "1 off target but NOT restatable: NIC (asx)" in capsys.readouterr().out
    assert rz.main(ARGS2 + ["--apply"]) == rz.STUCK_EXIT
    assert _snap(isolated) == before


def test_a_dry_run_names_the_stuck_row_and_still_exits_zero(isolated, capsys):
    _write_book(isolated, "asx", {"open": [_stuck_row()], "closed": []})
    assert rz.main(ARGS2) == 0
    out = capsys.readouterr().out
    assert "NOT RESTATABLE: 1 open row(s)" in out and "NIC" in out
    assert "dry run: nothing written" in out


@pytest.mark.parametrize("notional", [None, "junk", float("nan")])
def test_an_unreadable_notional_on_an_unsizeable_row_counts_as_stuck(
        isolated, notional):
    row = _stuck_row()
    row["notional"] = notional
    _write_book(isolated, "asx", {"open": [row], "closed": []})
    assert rz.main(ARGS2 + ["--check"]) == rz.STUCK_EXIT


def test_a_sizer_that_returns_nothing_is_stuck_too(isolated, monkeypatch):
    _write_book(isolated, "asx", {"open": [_bot_row()], "closed": []})
    monkeypatch.setattr(vivek_bot, "size_position",
                        lambda *a, **k: {"units": 0.0, "notional": 0.0})
    before = _snap(isolated)
    assert rz.main(ARGS2 + ["--check"]) == rz.STUCK_EXIT
    assert rz.main(ARGS2 + ["--apply"]) == rz.STUCK_EXIT
    assert _snap(isolated) == before


def test_a_stuck_row_is_measured_against_the_size_it_was_wanted_at():
    # Under --max-stop-pct the wanted size is the CAPPED one, not the target:
    # a row sitting at the raw target is still off it.
    row = _bot_row(sig=100.0, stop=50.0, fill=104.0, notional=2_500.0)
    rec = rz.resize_position(copy.deepcopy(row), 2_500.0, 150_000.0, STAMP2,
                             max_stop_pct=25.0)
    assert rec["want"] == pytest.approx(1_250.0)
    rec.update(action="skipped", reason="sizer returned nothing")
    assert [c["symbol"] for c in rz.stuck_rows(
        {"asx": {"changes": [rec]}}, 2_500.0)] == ["AAA"]
    # ...and a no-basis row, which never gets a `want`, falls back to target.
    nb = rz.resize_position(_stuck_row(notional=2_500.0), 2_500.0, 150_000.0, STAMP2)
    assert nb["want"] is None
    assert rz.stuck_rows({"asx": {"changes": [nb]}}, 2_500.0) == []


def test_skips_that_are_not_failures_are_never_stuck():
    done = rz.resize_position(_bot_row(notional=2_500.0), 2_500.0, 150_000.0, STAMP2)
    closed = rz.resize_position(_bot_row(status="closed"), 2_500.0, 150_000.0, STAMP2)
    assert (done["reason"], closed["reason"]) == ("already at target", "not open")
    assert rz.stuck_rows({"asx": {"changes": [done, closed]}}, 2_500.0) == []


# -- F4: the guard restamp can fail, and the log must say so ------------------

def _boom(*a, **k):
    raise RuntimeError("guard exploded")


def test_restamp_reports_a_swallowed_guard_failure(monkeypatch):
    book = _guarded_book()
    old = book["guard"]["asx"]
    monkeypatch.setattr(vivek_guard, "check", _boom)
    day, ok = rz.restamp(book, "asx")
    assert (day, ok) == ("2026-09-26", False)
    assert book["guard"]["asx"] is old                    # left as it was
    bare = {"open": [_bot_row(last_mark=100.0)], "closed": []}
    assert rz.restamp(bare, "asx")[1] is False            # absent stays absent
    assert "asx" not in (bare.get("guard") or {})


def test_apply_never_claims_a_guard_restamp_that_did_not_happen(
        isolated, monkeypatch, capsys):
    book = _guarded_book()
    old = copy.deepcopy(book["guard"]["asx"])
    path = _write_book(isolated, "asx", book)
    monkeypatch.setattr(vivek_guard, "check", _boom)
    assert rz.main(ARGS2 + ["--apply"]) == 0              # display-only: still writes
    out = capsys.readouterr().out
    assert "guard NOT restamped - see warning above" in out
    assert "summary + guard restamped" not in out
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["guard"]["asx"] == old                   # the old-size window, as stored
    assert saved["open"][0]["notional"] == 2_500.0


def test_apply_says_restamped_when_it_was(isolated, capsys):
    _write_book(isolated, "asx", _guarded_book())
    assert rz.main(ARGS2 + ["--apply"]) == 0
    out = capsys.readouterr().out
    assert "(summary + guard restamped for 2026-09-26)" in out
    assert "NOT restamped" not in out


# -- C4/F5: a banked partial's dollars restate with the row ------------------

def _glbe(**kw) -> dict:
    """GLBE's shape on 2026-09-27: tp1 (25%) banked while it was $5,000."""
    return _bot_row(symbol="GLBE", booked_pct=0.25, tp1_hit=True,
                    realized_r=0.1033,
                    exits=[{"reason": "tp1", "price": 125.0, "pct": 0.25,
                            "date": "2026-09-22"}], **kw)


def test_the_report_names_a_restated_row_whose_partial_was_banked_at_the_old_size():
    p = _glbe()                                  # risk_usd 1000 -> 500
    rec = rz.resize_position(p, 2_500.0, 150_000.0, STAMP2)
    out = "\n".join(rz.report({"nasdaq": {"changes": [rec]}}, 2_500.0, 150_000.0))
    assert ("GLBE: 25% already banked at $5,000 - its realised $103.30 -> "
            "$51.65 is restated with the row; R unchanged (+0.1033R)") in out
    assert "1 restated row(s) carry a partial exit banked at the old size" in out
    assert p["realized_r"] == 0.1033 and len(p["exits"]) == 1     # R frozen


def test_the_live_glbe_numbers_read_as_the_review_measured_them():
    # realized_r 0.1033 x risk_usd 616.43 = $63.68 -> x 308.22 = $31.84.
    c = {"symbol": "GLBE", "booked_pct": 0.25, "n_exits": 1, "realized_r": 0.1033,
         "notional_before": 5_000.0, "risk_usd_before": 616.43,
         "risk_usd_after": 308.22}
    assert "realised $63.68 -> $31.84" in rz.banked_line(c)


def test_an_exit_without_a_booked_share_is_still_named():
    rec = rz.resize_position(
        _bot_row(symbol="LEG", booked_pct=0.0,
                 exits=[{"reason": "tp1", "pct": 0.25}]), 2_500.0, 150_000.0, STAMP2)
    assert "LEG: 1 exit(s) already banked at $5,000" in rz.banked_line(rec)


def test_no_banked_line_for_a_row_that_banked_nothing_or_was_not_restated():
    clean = rz.resize_position(_bot_row(symbol="CLN"), 2_500.0, 150_000.0, STAMP2)
    assert rz.banked_line(clean) == ""
    held = rz.resize_position(_glbe(notional=2_500.0), 2_500.0, 150_000.0, STAMP2)
    assert held["action"] == "skipped"
    out = "\n".join(rz.report({"nasdaq": {"changes": [clean, held]}},
                              2_500.0, 150_000.0))
    assert "already banked" not in out and "carry a partial exit" not in out
