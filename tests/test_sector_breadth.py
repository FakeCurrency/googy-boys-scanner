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
