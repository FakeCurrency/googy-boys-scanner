"""SECTOR BREADTH + HORIZON — the rotation surface (2026-07-28).

These tests exist because of a specific, expensive miss: ASX Consumer
Discretionary ran for four weeks, the book held none of it, and every number
the system published pointed the other way. Each test below pins one of the
reasons that was possible, so the surface cannot silently regress to it.

The module is REPORT-ONLY and these tests assume that: they check what is
visible, never what is taken. If a change here starts affecting `decide()`,
that is a trade change and needs the owner, not a green test run.
"""

import json

import pytest

from scanner import config
from scanner import sectorbreadth as sb

pytestmark = pytest.mark.risk


@pytest.fixture(autouse=True)
def _no_real_sector_cache(tmp_path, monkeypatch):
    """Every test gets an EMPTY sector cache unless it writes one itself.

    `_denominator` falls back to the on-disk cache when a universe carries no
    sectors, so without this an unrelated test would quietly read the real
    data/sector_map.json and change answer whenever a scan refreshed it.
    """
    monkeypatch.setattr(sb, "SECTOR_CACHE_FILE", tmp_path / "no_sector_map.json")


def _uni(**counts):
    """A universe with `counts` names per sector: _uni(Materials=766, ...)."""
    out = []
    for sector, n in counts.items():
        name = sector.replace("_", " ")
        out.extend({"symbol": f"{sector[:3].upper()}{i}", "yf": f"{sector[:3]}{i}.AX",
                    "sector": name} for i in range(n))
    return out


def _res(sector, n, grade="A+", armed=True, direction="LONG", start=0):
    name = sector.replace("_", " ")
    return [{"symbol": f"{sector[:3].upper()}{i}", "sector": name, "grade": grade,
             "armed": armed, "dir": direction} for i in range(start, start + n)]


def _pos(symbol, sector, market="asx", notional=5_000.0):
    return {"symbol": symbol, "market": market, "sector": sector,
            "direction": "long", "status": "open", "notional": notional}


# ── the headline: rate, not raw count ────────────────────────────────────────

def test_rate_ranks_a_small_hot_sector_above_a_huge_cold_one():
    """THE bug the July miss turned on. Materials lists 766 ASX names and
    out-counts every sector on every scan regardless of what it is doing; on
    raw counts Consumer Discretionary ranked 6th that day, on rate it ranked
    3rd. Raw counts measure the exchange's composition, not the market's."""
    uni = _uni(Materials=766, Consumer_Discretionary=104)
    res = _res("Materials", 30) + _res("Consumer_Discretionary", 11)
    snap = sb.compute("asx", res, uni)
    by = {b["sector"]: b for b in snap["sectors"]}
    # Materials wins on the raw count that used to be the only published number…
    assert by["Materials"]["ag"] > by["Consumer Discretionary"]["ag"]
    # …and loses decisively on the one that means something.
    assert by["Consumer Discretionary"]["rate"] > by["Materials"]["rate"]
    assert by["Consumer Discretionary"]["rank"] < by["Materials"]["rank"]


def test_unclassified_is_computed_but_never_ranked():
    """389 of 2,212 ASX names carry 'Unclassified'. On the first live run that
    bucket came out TOP of the leaderboard at 23.4%, demoting every real sector
    by a place — the same 'big undifferentiated bucket looks like breadth'
    failure in a new costume. It must be visible and unranked."""
    uni = _uni(Unclassified=389, Real_Estate=62)
    res = _res("Unclassified", 91) + _res("Real_Estate", 14)
    snap = sb.compute("asx", res, uni)
    by = {b["sector"]: b for b in snap["sectors"]}
    assert by["Unclassified"]["rate"] > by["Real Estate"]["rate"]   # it IS higher
    assert by["Unclassified"]["rank"] is None                       # …and unranked
    assert by["Unclassified"]["ag"] == 91                           # …but not hidden
    assert by["Real Estate"]["rank"] == 1


def test_a_tiny_sector_cannot_top_the_board_on_one_setup():
    """One setup in a 3-name sector is 33% and would lead every scan forever."""
    uni = _uni(Tiny=3, Financials=198)
    snap = sb.compute("asx", _res("Tiny", 1) + _res("Financials", 33), uni)
    by = {b["sector"]: b for b in snap["sectors"]}
    assert by["Tiny"]["rate"] > by["Financials"]["rate"]
    assert by["Tiny"]["rank"] is None and by["Financials"]["rank"] == 1


def test_only_tradeable_grades_count_toward_the_rate():
    uni = _uni(Energy=100)
    res = _res("Energy", 5) + _res("Energy", 40, grade="WATCH", start=5)
    snap = sb.compute("asx", res, uni)
    (b,) = [x for x in snap["sectors"] if x["sector"] == "Energy"]
    assert b["setups"] == 45 and b["ag"] == 5
    assert b["rate"] == pytest.approx(0.05)      # 5/100, not 45/100
    assert b["setup_rate"] == pytest.approx(0.45)


def test_a_sector_with_no_listed_names_gets_no_rate_instead_of_a_wrong_one():
    """Held positions carrying a divergent taxonomy (REFINEMENTS #112: Yahoo's
    'Insurance' where the ASX universe says 'Financials') create a bucket with a
    holding and zero listed names. Dividing by zero names must not invent a
    rate, and it must not vanish either — the holding is real."""
    snap = sb.compute("asx", [], _uni(Financials=198),
                      [_pos("SUN", "Insurance")])
    by = {b["sector"]: b for b in snap["sectors"]}
    assert by["Insurance"]["held"] == 1 and by["Insurance"]["names"] == 0
    assert by["Insurance"]["rate"] is None and by["Insurance"]["rank"] is None


# ── the index tape, joined from a fetch already being paid for ───────────────

def test_the_sector_index_tape_is_joined_onto_the_breadth_rows():
    tape = {"sectors": [{"symbol": "XDJ", "name": "Cons. Disc.", "chg_pct": 1.79},
                        {"symbol": "XMJ", "name": "Materials", "chg_pct": -1.92}]}
    snap = sb.compute("asx", _res("Consumer_Discretionary", 11),
                      _uni(Consumer_Discretionary=104, Materials=766), [], tape)
    by = {b["sector"]: b for b in snap["sectors"]}
    assert by["Consumer Discretionary"]["index"] == "XDJ"
    assert by["Consumer Discretionary"]["index_chg"] == pytest.approx(1.79)
    assert by["Materials"]["index_chg"] == pytest.approx(-1.92)


def test_a_malformed_tape_degrades_to_no_tape_rather_than_crashing():
    for bad in ({"sectors": "nope"}, {"sectors": [{"symbol": "XDJ"}]},
                {"sectors": [{"symbol": "XDJ", "chg_pct": "n/a"}]}, {}, None):
        snap = sb.compute("asx", _res("Consumer_Discretionary", 11),
                          _uni(Consumer_Discretionary=104), [], bad)
        assert snap["sectors"][0]["index_chg"] is None


def test_us_names_map_onto_the_us_tape_including_yahoos_spellings():
    # NASDAQ sectors come from Yahoo profiles, which say "Consumer Cyclical"
    # where GICS says "Consumer Discretionary". Both must reach XLY.
    assert sb._index_for("nasdaq", "Consumer Cyclical") == "XLY"
    assert sb._index_for("nasdaq", "Consumer Discretionary") == "XLY"
    assert sb._index_for("asx", "Consumer Discretionary") == "XDJ"
    assert sb._index_for("asx", "Nonsense Sector") == ""     # never guesses


# ── capacity: the actual cause of the July miss ──────────────────────────────

def test_book_state_reports_capacity_globally():
    st = sb.book_state([_pos(f"S{i}", "Materials") for i in range(30)])
    assert st["open"] == 30 and st["at_cap"] is True and st["free"] == 0
    assert st["notional"] == pytest.approx(150_000.0)
    st = sb.book_state([_pos("BHP", "Materials")])
    assert st["at_cap"] is False and st["free"] == 29


def test_book_state_publishes_the_per_position_size():
    """Free SLOTS are only meaningful in dollars once you know the slot size.

    The two ceilings disagree by an order of magnitude while the legacy
    positions are still on the book: 24/30 slots reads 80% full, $6.1k of $150k
    reads 4% invested. The page reconciles them as free x position size, which
    it cannot do unless this number rides along.
    """
    st = sb.book_state([_pos("BHP", "Materials", notional=250.0)])
    assert st["position_notional"] == pytest.approx(
        float(config.VIVEK_BOT_POSITION_NOTIONAL))
    assert st["position_notional"] > 0            # fixed-notional mode is live
    # the dollar cap looks wide open while the slot cap is what actually binds
    assert st["notional"] == pytest.approx(250.0)
    assert st["free"] * st["position_notional"] < st["max_notional"] - st["notional"]


def test_horizon_fires_when_a_leading_sector_is_unheld_and_the_book_is_full():
    """The alarm that would have printed every day from 30 June to 27 July."""
    uni = _uni(Consumer_Discretionary=104, Materials=766)
    snap = sb.compute("asx", _res("Consumer_Discretionary", 11) + _res("Materials", 30), uni,
                      [_pos(f"MAT{i}", "Materials") for i in range(30)])
    book = sb.book_state([_pos(f"MAT{i}", "Materials") for i in range(30)])
    hz = sb.horizon(snap, book, {"rows": []}, cap_streak=20)
    assert hz["expand"] is True
    assert "Consumer Discretionary" in hz["unheld_leaders"]
    assert "Materials" not in hz["unheld_leaders"]          # it IS held
    joined = " ".join(hz["notes"])
    assert "FULL" in joined and "20 straight sessions" in joined
    assert "Consumer Discretionary" in joined


def test_horizon_stays_quiet_when_the_book_can_act():
    uni = _uni(Consumer_Discretionary=104)
    snap = sb.compute("asx", _res("Consumer_Discretionary", 11), uni, [])
    book = sb.book_state([_pos("BHP", "Materials")])         # 1 of 30 used
    hz = sb.horizon(snap, book, {"rows": []})
    # The leader is still reported as unheld — that is information — but the
    # actionable "look wider" state needs the capacity half to be true too.
    assert hz["unheld_leaders"] == ["Consumer Discretionary"]
    assert hz["expand"] is False


def test_horizon_names_the_per_sector_cap_when_that_is_what_is_binding():
    """A different failure with the same symptom: the sector IS held, at the
    cap, so more of it cannot be taken. The limit is the rule, not the market,
    and the note has to say which."""
    monkey = config.VIVEK_BOT_MAX_PER_SECTOR
    uni = _uni(Consumer_Discretionary=104)
    held = [_pos(f"CD{i}", "Consumer Discretionary") for i in range(monkey)]
    snap = sb.compute("asx", _res("Consumer_Discretionary", 11), uni, held)
    hz = sb.horizon(snap, sb.book_state(held), {"rows": []})
    assert any("per-sector cap" in n for n in hz["notes"])


# ── the persisted series: the only long sector memory in the system ──────────

def test_history_keeps_one_row_per_market_per_day_last_write_wins():
    hist = {"version": 1, "rows": []}
    uni = _uni(Materials=766)
    for ag in (10, 20, 30):                     # three scans, same session
        snap = sb.compute("asx", _res("Materials", ag), uni)
        hist = sb.append_history(hist, snap, sb.book_state([]), "2026-07-28")
    assert len(hist["rows"]) == 1
    assert hist["rows"][0]["s"]["Materials"][0] == 30       # the LAST scan's
    # a second market on the same day is its own row
    snap = sb.compute("nasdaq", [], _uni(Technology=500))
    hist = sb.append_history(hist, snap, sb.book_state([]), "2026-07-28")
    assert len(hist["rows"]) == 2


def test_history_is_capped_without_losing_the_recent_end(monkeypatch):
    monkeypatch.setattr(config, "SECTOR_BREADTH_HISTORY_MAX", 5)
    hist = {"version": 1, "rows": []}
    snap = sb.compute("asx", _res("Materials", 3), _uni(Materials=766))
    for d in range(1, 12):
        hist = sb.append_history(hist, snap, sb.book_state([]), f"2026-07-{d:02d}")
    assert len(hist["rows"]) == 5
    assert hist["rows"][-1]["d"] == "2026-07-11"            # newest survives


def test_trend_shows_a_sector_lifting_across_weeks():
    """The number that makes a rotation visible WHILE it happens instead of
    unrecoverable afterwards. Four quiet days, then four hot ones."""
    hist = {"version": 1, "rows": []}
    uni = _uni(Consumer_Discretionary=100)
    for d, ag in enumerate([2, 2, 3, 2, 9, 11, 12, 10], start=1):
        snap = sb.compute("asx", _res("Consumer_Discretionary", ag), uni)
        hist = sb.append_history(hist, snap, sb.book_state([]), f"2026-07-{d:02d}")
    t = sb.trend(hist, "asx", "Consumer Discretionary", window=4)
    assert t["days"] == 8
    assert t["mean"] == pytest.approx(0.105)       # (9+11+12+10)/4 / 100
    assert t["prev"] == pytest.approx(0.0225)
    assert t["chg"] > 0                            # rising, and by how much


def test_cap_streak_counts_only_the_unbroken_recent_run():
    hist = {"version": 1, "rows": []}
    snap = sb.compute("asx", [], _uni(Materials=766))
    for d, full in enumerate([True, True, False, True, True, True], start=1):
        book = sb.book_state([_pos(f"S{i}", "Materials") for i in range(30 if full else 4)])
        hist = sb.append_history(hist, snap, book, f"2026-07-{d:02d}")
    assert sb.cap_streak(hist, "asx") == 3         # not 5
    assert sb.cap_streak(hist, "nasdaq") == 0


def test_series_is_aligned_to_the_day_axis_for_plotting():
    hist = {"version": 1, "rows": []}
    # day 1 has both sectors, day 2 only one — the gap must be a hole, not a shift
    s1 = sb.compute("asx", _res("Materials", 30), _uni(Materials=766, Energy=100))
    hist = sb.append_history(hist, s1, sb.book_state([]), "2026-07-01")
    s2 = sb.compute("asx", _res("Materials", 60), _uni(Materials=766))
    hist = sb.append_history(hist, s2, sb.book_state([]), "2026-07-02")
    ser = sb.series(hist)["asx"]
    assert ser["days"] == ["2026-07-01", "2026-07-02"]
    # 4 dp, deliberately: the series is a plot input published to the browser,
    # so it ships the same rounded rate `compute` does rather than 16 digits of
    # float noise per cell per day.
    assert ser["sectors"]["Materials"] == [round(30 / 766, 4), round(60 / 766, 4)]
    assert ser["sectors"]["Energy"] == [pytest.approx(0.0), None]
    assert len(ser["open"]) == len(ser["days"])


# ── the streak: the difference between a shrug and a miss in progress ────────

def _run(days, *, held_on=(), market="asx"):
    """History for `days` sessions of the real 2026-07-28 ASX board shape.

    Unclassified leads it at 23.4% -- above every genuine sector -- which is
    exactly the trap the reconstruction has to step over.
    """
    uni = _uni(Unclassified=389, Real_Estate=62, Financials=198,
               Consumer_Discretionary=104)
    hist = {"version": 1, "rows": []}
    for d in range(1, days + 1):
        held = ([_pos("CD0", "Consumer Discretionary", market=market)]
                if d in held_on else [])
        snap = sb.compute(market,
                          _res("Unclassified", 91) + _res("Real_Estate", 14)
                          + _res("Financials", 33)
                          + _res("Consumer_Discretionary", 11),
                          uni, held)
        hist = sb.append_history(hist, snap, sb.book_state(held), f"2026-07-{d:02d}")
    return hist


def test_a_non_sector_bucket_cannot_take_a_leader_slot_in_the_reconstruction():
    """THE defect this function shipped with, pinned.

    History stores every bucket that had listed names, and on the real board
    "Unclassified" (91/389 = 23.4%) outranks all three genuine leaders. The live
    panel refuses it a rank; a reconstruction that forgets to would hand it slot
    one every single day, push Consumer Discretionary out of the top three, and
    report a streak of zero for the one sector the whole surface exists to
    catch -- silently, and only for the sector that mattered.
    """
    hist = _run(6)
    assert sb.unheld_streak(hist, "asx", "Consumer Discretionary") == 6
    assert sb.unheld_streak(hist, "asx", "Unclassified") == 0   # never a leader


def test_the_streak_counts_only_the_unbroken_recent_run():
    # held on day 4 of 7 — the run is the three sessions since, not all seven
    hist = _run(7, held_on=(4,))
    assert sb.unheld_streak(hist, "asx", "Consumer Discretionary") == 3


def test_a_sector_that_is_not_leading_has_no_streak():
    hist = _run(5)
    # Industrials never appears in these rows at all; a missing sector is a zero,
    # not a crash and not an inherited count from the sector above it.
    assert sb.unheld_streak(hist, "asx", "Industrials") == 0
    assert sb.unheld_streak(hist, "nasdaq", "Consumer Discretionary") == 0
    assert sb.unheld_streak({"rows": []}, "asx", "Consumer Discretionary") == 0


def test_a_thin_sector_cannot_invent_a_streak_out_of_noise():
    """Same bar as the live board: a 3-name sector reading 33% must not rank
    here either, or the streak column fills with sectors nobody can trade."""
    hist = {"version": 1, "rows": []}
    uni = _uni(Tiny=3, Materials=766)
    for d in range(1, 5):
        snap = sb.compute("asx", _res("Tiny", 1) + _res("Materials", 30), uni)
        hist = sb.append_history(hist, snap, sb.book_state([]), f"2026-07-{d:02d}")
    assert hist["rows"][-1]["s"]["Tiny"] == [1, 3, 0, None]      # stored...
    assert sb.unheld_streak(hist, "asx", "Tiny") == 0            # ...never led


def test_an_unknown_held_count_stops_the_streak_instead_of_extending_it():
    """UNKNOWN IS NOT ZERO -- the one line the backfill is load-bearing on.

    A reconstructed session from before the bot book existed writes `held: null`,
    because "the book held none of this sector" and "there was no book" are not
    the same claim and only the first is evidence of a miss. `None` is falsy, so
    the obvious `if cell[2]: break` counts straight THROUGH the unknown days and
    reports the whole reconstructed period as one unbroken run. The first
    backfill would then have handed every sector a six-month streak at once and
    paged the owner about all of them -- destroying the credibility of the only
    number on the board that was built to be believed.
    """
    hist = _run(5)                                  # 5 sessions, leading, unheld
    for r in hist["rows"][:2]:                      # the oldest two: reconstructed
        r["r"] = 1
        for cell in r["s"].values():
            cell[2] = None
    assert sb.unheld_streak(hist, "asx", "Consumer Discretionary") == 3


def test_a_held_position_and_an_unknown_stop_the_streak_the_same_way():
    """Both are "stop counting", and the run reported is only the part we can
    stand behind. A null on the MOST RECENT session means we cannot claim even
    one honest unheld day, so the answer is zero, not one."""
    hist = _run(4)
    for cell in hist["rows"][-1]["s"].values():
        cell[2] = None
    assert sb.unheld_streak(hist, "asx", "Consumer Discretionary") == 0


def test_the_streak_survives_a_gap_in_the_sessions():
    """Weekends and holidays leave no row. A run of sessions is not broken by a
    day the market was shut, and counting rows rather than dates is what makes
    that true without the function needing a calendar."""
    hist = _run(3)
    for r in hist["rows"]:                       # 01, 02, 03 -> 01, 02, 09
        if r["d"] == "2026-07-03":
            r["d"] = "2026-07-09"
    assert sb.unheld_streak(hist, "asx", "Consumer Discretionary") == 3


def test_horizon_says_how_long_and_publishes_it_for_the_page():
    """A one-day reading and a nineteen-day reading are different sentences and
    the alarm has to read differently. This is the number the July post-mortem
    could not produce afterwards, which is why it is computed live."""
    hist = _run(19)
    snap = sb.compute("asx",
                      _res("Unclassified", 91) + _res("Real_Estate", 14)
                      + _res("Financials", 33) + _res("Consumer_Discretionary", 11),
                      _uni(Unclassified=389, Real_Estate=62, Financials=198,
                           Consumer_Discretionary=104))
    hz = sb.horizon(snap, sb.book_state([]), hist)
    assert hz["unheld_streaks"]["Consumer Discretionary"] == 19
    assert hz["longest_unheld"] == 19
    assert any("19 sessions running" in n for n in hz["notes"])


def _today_snap():
    return sb.compute("asx",
                      _res("Unclassified", 91) + _res("Real_Estate", 14)
                      + _res("Financials", 33) + _res("Consumer_Discretionary", 11),
                      _uni(Unclassified=389, Real_Estate=62, Financials=198,
                           Consumer_Discretionary=104))


def test_a_long_run_goes_loud_even_when_the_book_has_plenty_of_room():
    """The reading the old `expand` rule could not produce, and the worse of the
    two cases. Capped out is at least an explanation; a fortnight of leading
    with nothing held AND 30 free slots is the scanner having pointed at it
    every session while nothing happened. It must not read as business as
    usual just because the book was not the thing in the way."""
    hz = sb.horizon(_today_snap(), sb.book_state([]), _run(14))
    assert hz["expand"] is True
    assert "Consumer Discretionary" in hz["sustained"]
    # first, because the dashboard strip shows only notes[0]
    assert hz["notes"][0].startswith("LOOK WIDER")
    assert "30 free slots" in hz["notes"][0]
    # the banner must not call this a capacity problem — the book was wide open
    assert "14 straight sessions" in hz["expand_why"]
    assert "barely act" not in hz["expand_why"]


def test_a_full_book_still_gets_the_capacity_wording():
    full = [_pos(f"S{i}", "Materials") for i in range(30)]
    hz = sb.horizon(_today_snap(), sb.book_state(full), {"rows": []})
    assert hz["expand"] is True
    assert "barely act" in hz["expand_why"]
    assert sb.horizon(_today_snap(), sb.book_state([]), _run(1))["expand_why"] == ""


def test_a_short_run_with_room_stays_calm():
    """Below the threshold the page describes and does not shout. An alarm that
    fires on day two is an alarm that gets scrolled past by day three."""
    hz = sb.horizon(_today_snap(), sb.book_state([]), _run(2))
    assert hz["expand"] is False
    assert hz["sustained"] == []
    assert not any(n.startswith("LOOK WIDER") for n in hz["notes"])


def test_the_run_threshold_is_configurable(monkeypatch):
    monkeypatch.setattr(config, "SECTOR_BREADTH_RUN_ALERT", 0)   # off
    assert sb.horizon(_today_snap(), sb.book_state([]), _run(30))["sustained"] == []
    monkeypatch.setattr(config, "SECTOR_BREADTH_RUN_ALERT", 2)
    # every top-3 sector is unheld in this fixture, so all three qualify at 2
    assert set(sb.horizon(_today_snap(), sb.book_state([]), _run(2))["sustained"]) == {
        "Real Estate", "Financials", "Consumer Discretionary"}


def test_a_first_day_leader_is_not_dressed_up_as_a_run():
    """Day one says nothing extra. A badge on the first session would train the
    eye to ignore the badge, which costs exactly what the badge is worth."""
    hist = _run(1)
    snap = sb.compute("asx",
                      _res("Unclassified", 91) + _res("Real_Estate", 14)
                      + _res("Financials", 33) + _res("Consumer_Discretionary", 11),
                      _uni(Unclassified=389, Real_Estate=62, Financials=198,
                           Consumer_Discretionary=104))
    hz = sb.horizon(snap, sb.book_state([]), hist)
    assert hz["unheld_streaks"]["Consumer Discretionary"] == 1
    assert not any("sessions running" in n for n in hz["notes"])
    # but the ZERO-held alarm itself still fires on day one
    assert any("ZERO held" in n for n in hz["notes"])


# ── the NASDAQ denominator ───────────────────────────────────────────────────

def test_a_universe_with_no_sector_column_falls_back_to_the_classified_cache(tmp_path, monkeypatch):
    """NASDAQ's symbol file carries no sector at all, so on the first live run
    every US bucket came out names=0, nothing ranked, and the panel was blank
    for half the book. The sector cache is the only US taxonomy that exists."""
    cache = {f"nasdaq:TEC{i}": {"sector": "Technology"} for i in range(60)}
    cache.update({f"nasdaq:CYC{i}": {"sector": "Consumer Cyclical"} for i in range(40)})
    cache["asx:BHP"] = {"sector": "Materials"}          # other markets ignored
    (tmp_path / "map.json").write_text(json.dumps(cache))
    monkeypatch.setattr(sb, "SECTOR_CACHE_FILE", tmp_path / "map.json")

    res = _res("Technology", 6) + _res("Consumer_Cyclical", 10)
    snap = sb.compute("nasdaq", res, [])               # <- no universe sectors
    by = {b["sector"]: b for b in snap["sectors"]}
    assert by["Technology"]["names"] == 60
    assert by["Consumer Cyclical"]["names"] == 40
    # 25% beats 10%, and the cheap raw count (Technology 6 vs 10) does not decide it
    assert by["Consumer Cyclical"]["rank"] == 1
    assert by["Technology"]["rank"] == 2
    assert by["Consumer Cyclical"]["index"] == "XLY"    # Yahoo spelling still maps


def test_a_sectorless_scan_row_is_bucketed_from_the_cache(tmp_path, monkeypatch):
    """NASDAQ scan rows ship sector-less — `output.write` runs before
    `vivek_run` enriches them — so the first live US run had a fine denominator
    and a numerator of zero in every bucket: eleven sectors 'leading' at 0.0%."""
    (tmp_path / "map.json").write_text(json.dumps(
        {f"nasdaq:TEC{i}": {"sector": "Technology"} for i in range(60)}))
    monkeypatch.setattr(sb, "SECTOR_CACHE_FILE", tmp_path / "map.json")
    res = [dict(r, sector="") for r in _res("Technology", 6)]   # <- as published
    by = {b["sector"]: b for b in sb.compute("nasdaq", res, [])["sectors"]}
    assert by["Technology"]["ag"] == 6 and by["Technology"]["rate"] == 0.1


def test_a_sector_on_the_row_beats_the_cache(tmp_path, monkeypatch):
    (tmp_path / "map.json").write_text(json.dumps({"nasdaq:TEC0": {"sector": "Utilities"}}))
    monkeypatch.setattr(sb, "SECTOR_CACHE_FILE", tmp_path / "map.json")
    by = {b["sector"]: b for b in sb.compute("nasdaq", _res("Technology", 1), [])["sectors"]}
    assert by["Technology"]["ag"] == 1
    assert by.get("Utilities", {}).get("ag", 0) == 0


def test_a_sector_with_no_setups_at_all_is_not_called_a_leader(tmp_path, monkeypatch):
    """A whole board can sit at zero on a quiet day. 'Leading on breadth with
    ZERO held' at 0.0% is noise, and noise is how an alarm gets ignored."""
    snap = sb.compute("asx", [], _uni(Materials=766, Energy=100))
    hz = sb.horizon(snap, sb.book_state([]), {"version": 1, "rows": []})
    assert hz["leaders"] == [] and hz["unheld_leaders"] == []
    assert not any("Leading on breadth" in n for n in hz["notes"])


def test_the_fallback_denominator_is_labelled_not_passed_off_as_listings(tmp_path, monkeypatch):
    """A cache-derived rate is over a SUBSET of listings, so it is not
    comparable to an ASX rate. The page has to be able to say so."""
    (tmp_path / "map.json").write_text(
        json.dumps({f"nasdaq:TEC{i}": {"sector": "Technology"} for i in range(60)}))
    monkeypatch.setattr(sb, "SECTOR_CACHE_FILE", tmp_path / "map.json")
    assert sb.compute("nasdaq", _res("Technology", 6), [])["names_source"] == "classified"
    assert sb.compute("asx", _res("Materials", 30),
                      _uni(Materials=766))["names_source"] == "universe"
    assert sb.compute("asx", [], [])["names_source"] == "none"


def test_a_universe_that_has_sectors_never_consults_the_cache(tmp_path, monkeypatch):
    """ASX ships GICS with its directory; the cache must not be able to
    contradict or pad the real listing count."""
    (tmp_path / "map.json").write_text(
        json.dumps({f"asx:X{i}": {"sector": "Materials"} for i in range(999)}))
    monkeypatch.setattr(sb, "SECTOR_CACHE_FILE", tmp_path / "map.json")
    snap = sb.compute("asx", _res("Materials", 30), _uni(Materials=766))
    assert {b["sector"]: b["names"] for b in snap["sectors"]}["Materials"] == 766


def test_an_unreadable_cache_degrades_to_no_denominator_not_a_crash(tmp_path, monkeypatch):
    (tmp_path / "map.json").write_text("{ this is not json")
    monkeypatch.setattr(sb, "SECTOR_CACHE_FILE", tmp_path / "map.json")
    snap = sb.compute("nasdaq", _res("Technology", 6), [])
    by = {b["sector"]: b for b in snap["sectors"]}
    assert by["Technology"]["names"] == 0 and by["Technology"]["rate"] is None
    assert snap["names_source"] == "none"


# ── the publish step ─────────────────────────────────────────────────────────

@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "HISTORY_FILE", tmp_path / "sector_history.json")
    monkeypatch.setattr(sb, "PUBLIC_FILE", tmp_path / "pub" / "sector_breadth.json")
    (tmp_path / "pub").mkdir()
    return tmp_path


def test_update_writes_both_files_and_is_idempotent_within_a_day(paths):
    markets = {"asx": {"results": _res("Consumer_Discretionary", 11),
                       "universe": _uni(Consumer_Discretionary=104)}}
    out = paths / "pub"
    p1 = sb.update(markets, out_dir=out, positions=[], day="2026-07-28")
    p2 = sb.update(markets, out_dir=out, positions=[], day="2026-07-28")
    assert (out / "sector_breadth.json").exists()
    assert (paths / "sector_history.json").exists()
    assert len(json.loads((paths / "sector_history.json").read_text())["rows"]) == 1
    assert p1["markets"]["asx"]["sectors"] == p2["markets"]["asx"]["sectors"]


def test_a_market_not_scanned_this_run_keeps_its_previous_block(paths):
    """A crypto-only weekend run must not blank the ASX picture."""
    out = paths / "pub"
    sb.update({"asx": {"results": _res("Materials", 30),
                       "universe": _uni(Materials=766)}},
              out_dir=out, positions=[], day="2026-07-28")
    after = sb.update({"nasdaq": {"results": [], "universe": _uni(Technology=500)}},
                      out_dir=out, positions=[], day="2026-07-29")
    assert "asx" in after["markets"]
    assert after["markets"]["asx"]["sectors"][0]["sector"] == "Materials"


def test_crypto_is_skipped_because_coins_have_no_sector(paths):
    got = sb.update({"crypto": {"results": [], "universe": []}},
                    out_dir=paths / "pub", positions=[], day="2026-07-28")
    assert got["markets"] == {}


def test_the_whole_surface_can_be_switched_off(paths, monkeypatch):
    monkeypatch.setattr(config, "SECTOR_BREADTH_ENABLED", False)
    assert sb.update({"asx": {"results": [], "universe": []}},
                     out_dir=paths / "pub", day="2026-07-28") is None
    assert not (paths / "pub" / "sector_breadth.json").exists()


def test_published_payload_carries_what_the_page_needs(paths):
    markets = {"asx": {"results": _res("Consumer_Discretionary", 11) + _res("Materials", 30),
                       "universe": _uni(Consumer_Discretionary=104, Materials=766)}}
    held = [_pos(f"MAT{i}", "Materials") for i in range(30)]
    got = sb.update(markets, out_dir=paths / "pub", positions=held, day="2026-07-28")
    blk = got["markets"]["asx"]
    assert blk["book"]["at_cap"] is True
    assert blk["horizon"]["expand"] is True
    assert "Consumer Discretionary" in blk["horizon"]["unheld_leaders"]
    assert all("trend" in b for b in blk["sectors"])
    assert got["series"]["asx"]["days"] == ["2026-07-28"]
    # and it must round-trip as JSON — this is a published file
    json.loads(json.dumps(got))


# ── the push (2026-07-28) ────────────────────────────────────────────────────
#
# The surface above only works on the days it gets opened, and the July miss
# happened with every ingredient already on the page. These pin the one path
# that reaches out instead of waiting to be looked at.

@pytest.fixture
def push(monkeypatch):
    """Capture pings instead of sending them, with the push switched ON."""
    sent = []
    monkeypatch.setattr(config, "SECTOR_BREADTH_RUN_ALERT_PUSH", True)
    monkeypatch.setattr(config, "SECTOR_BREADTH_RUN_ALERT_REPEAT_DAYS", 7)
    return sent


def _memory(hist):
    """The ping memory as it sits on disk — asserted through the published
    shape, not an accessor, because the shape is what has to survive a
    round-trip through `load_history`/`append_history` in CI."""
    return (hist.get("alerts") or {}).get("sector_run") or {}


def _blocks(hist, *, held=(), market="asx"):
    """A published block for the fixture board, exactly as `update()` builds it."""
    pos = list(held)
    snap = sb.compute(market,
                      _res("Unclassified", 91) + _res("Real_Estate", 14)
                      + _res("Financials", 33) + _res("Consumer_Discretionary", 11),
                      _uni(Unclassified=389, Real_Estate=62, Financials=198,
                           Consumer_Discretionary=104), pos)
    book = sb.book_state(pos)
    return {market: {**snap, "book": book, "horizon": sb.horizon(snap, book, hist)}}


def test_a_sustained_run_pings_once_with_the_streak_in_it(push):
    hist = _run(14)
    fired = sb.notify(hist, _blocks(hist), "2026-07-14", send=lambda *a: push.append(a))
    assert "asx|Consumer Discretionary" in fired
    event, title, details = next(a for a in push if "Consumer Discretionary" in a[1])
    assert event == "sector_run"
    assert "LOOK WIDER" in title and "14 sessions" in title
    # the number that separates a shrug from a miss in progress must be in the
    # body too, not only in a title a phone may truncate
    assert "14 straight sessions" in details
    assert "11 A+/A across 104 listed names = 10.6%" in details


def test_the_same_run_does_not_ping_again_tomorrow(push):
    hist = _run(14)
    blocks = _blocks(hist)
    assert sb.notify(hist, blocks, "2026-07-14", send=lambda *a: push.append(a))
    assert sb.notify(hist, blocks, "2026-07-15", send=lambda *a: push.append(a)) == []
    assert sb.notify(hist, blocks, "2026-07-20", send=lambda *a: push.append(a)) == []
    assert len([a for a in push if "Consumer Discretionary" in a[1]]) == 1


def test_a_run_that_is_still_going_pings_again_after_the_repeat_window(push):
    """A rotation that lasts a month must not go silent after one message —
    the whole failure was four weeks of nothing being said."""
    hist = _run(14)
    blocks = _blocks(hist)
    sb.notify(hist, blocks, "2026-07-14", send=lambda *a: push.append(a))
    assert sb.notify(hist, blocks, "2026-07-21", send=lambda *a: push.append(a))
    assert len([a for a in push if "Consumer Discretionary" in a[1]]) == 2


def test_a_run_that_ends_is_forgotten_so_the_next_one_pings_fresh(push):
    """Otherwise a sector that ran in July, stopped, and came back in October
    would land inside a stale repeat window and say nothing."""
    hist = _run(14)
    sb.notify(hist, _blocks(hist), "2026-07-14", send=lambda *a: push.append(a))
    quiet = _blocks(hist, held=[_pos("CD0", "Consumer Discretionary")])
    assert sb.notify(hist, quiet, "2026-07-15", send=lambda *a: push.append(a)) == []
    # only the sector that stopped is forgotten; the other two are still running
    assert "asx|Consumer Discretionary" not in _memory(hist)
    assert "asx|Financials" in _memory(hist)
    # ...and now it runs again, one day later, well inside the 7-day window
    assert "asx|Consumer Discretionary" in sb.notify(
        hist, _blocks(hist), "2026-07-16", send=lambda *a: push.append(a))


def test_a_short_run_never_pings(push):
    hist = _run(2)
    assert sb.notify(hist, _blocks(hist), "2026-07-02",
                     send=lambda *a: push.append(a)) == []
    assert push == []


def test_the_push_can_be_switched_off_without_touching_the_surface(monkeypatch):
    monkeypatch.setattr(config, "SECTOR_BREADTH_RUN_ALERT_PUSH", False)
    hist = _run(14)
    sent = []
    assert sb.notify(hist, _blocks(hist), "2026-07-14", send=lambda *a: sent.append(a)) == []
    assert sent == []
    # the note is still on the page — only the interruption is off
    assert _blocks(hist)["asx"]["horizon"]["notes"][0].startswith("LOOK WIDER")


def test_the_message_says_whether_the_book_could_have_acted(push):
    """Room-and-not-taken and wanted-and-couldn't are different failures and
    the reader must not have to go and look up which one this was."""
    hist = _run(14)
    sb.notify(hist, _blocks(hist), "2026-07-14", send=lambda *a: push.append(a))
    assert "30 free slots" in push[0][2]
    assert "$150,000" in push[0][2]

    full = [_pos(f"S{i}", "Materials") for i in range(30)]
    hist2 = _run(14)
    sb.notify(hist2, _blocks(hist2, held=full), "2026-07-14",
              send=lambda *a: push.append(a))
    capped = next(a for a in push if "FULL" in a[2])
    assert "could not have taken this" in capped[2]


def test_a_market_that_did_not_scan_keeps_its_memory(push):
    """`blocks` carries carried-forward markets too; re-pinging one would be
    the alarm reporting a stale streak as news."""
    hist = _run(14)
    sb.notify(hist, _blocks(hist), "2026-07-14", send=lambda *a: push.append(a))
    before = dict(_memory(hist))
    # a crypto-only weekend: nothing recomputed, so notify sees no blocks
    assert sb.notify(hist, {}, "2026-07-18", send=lambda *a: push.append(a)) == []
    assert _memory(hist) == before


def test_two_markets_both_ping_in_one_run(push):
    """The router's rate limit is per EVENT TYPE, so it would have silenced the
    second market — scan.yml runs them sequentially in one job."""
    hist = _run(14)
    hist = {"version": 1, "rows": hist["rows"] + _run(14, market="nasdaq")["rows"]}
    blocks = {**_blocks(hist), **_blocks(hist, market="nasdaq")}
    fired = sb.notify(hist, blocks, "2026-07-14", send=lambda *a: push.append(a))
    assert {"asx|Consumer Discretionary", "nasdaq|Consumer Discretionary"} <= set(fired)


def test_a_failing_send_is_not_recorded_as_sent(push):
    """A dropped ping must be retried on the next scan, not written off."""
    def boom(*a):
        raise RuntimeError("webhook down")
    hist = _run(14)
    assert sb.notify(hist, _blocks(hist), "2026-07-14", send=boom) == []
    assert _memory(hist) == {}
    assert sb.notify(hist, _blocks(hist), "2026-07-14",
                     send=lambda *a: push.append(a))


def test_the_ping_memory_rides_in_the_history_file(paths, push, monkeypatch):
    """Not journal/alert_state.json — scan.yml does not stage that, so every
    Actions run would read 'never pinged' and fire again."""
    monkeypatch.setattr(config, "SECTOR_BREADTH_RUN_ALERT", 1)
    sent = []
    monkeypatch.setattr("scanner.broker.alert_router.smart_send",
                        lambda *a: sent.append(a))
    markets = {"asx": {"results": _res("Consumer_Discretionary", 11),
                       "universe": _uni(Consumer_Discretionary=104)}}
    sb.update(markets, out_dir=paths / "pub", positions=[], day="2026-07-28")
    on_disk = json.loads((paths / "sector_history.json").read_text())
    assert on_disk["alerts"]["sector_run"]["asx|Consumer Discretionary"]["d"] == "2026-07-28"
    assert len(sent) == 1
    # and it survives the round-trip the streak itself depends on
    assert len(on_disk["rows"]) == 1
    sb.update(markets, out_dir=paths / "pub", positions=[], day="2026-07-29")
    assert len(sent) == 1


def test_a_broken_alert_path_never_costs_a_scan(paths, monkeypatch):
    """Report-only means report-only: the data still publishes."""
    monkeypatch.setattr(config, "SECTOR_BREADTH_RUN_ALERT_PUSH", True)
    monkeypatch.setattr(sb, "notify", lambda *a, **k: 1 / 0)
    got = sb.update({"asx": {"results": _res("Materials", 30),
                             "universe": _uni(Materials=766)}},
                    out_dir=paths / "pub", positions=[], day="2026-07-28")
    assert got["markets"]["asx"]["sectors"]
    assert (paths / "pub" / "sector_breadth.json").exists()


def test_the_alert_routes_to_discord_only():
    """Owner decision (2026-07-28): the same channel the confluence pings land
    in. Nothing is BROKEN when this fires, so it must not sit in the same feed
    at the same volume as order failures and circuit breakers."""
    from scanner.broker import alert_router as ar
    assert ar.get_severity("sector_run") == "NOTICE"
    assert ar.get_channels("sector_run") == ["discord"]
    # the router must not second-guess our per-sector dedupe
    assert config.ALERT_RATE_LIMITS["sector_run"] == 0
    assert ar._CHAN_MAP["NOTICE"] == ["discord"]     # config-less fallback agrees


def test_the_message_is_plain_ascii(push):
    """It is built by scanner code, and scanner code prints on cp1252 consoles."""
    hist = _run(14)
    sb.notify(hist, _blocks(hist), "2026-07-14", send=lambda *a: push.append(a))
    for event, title, details in push:
        (event + title + details).encode("ascii")
