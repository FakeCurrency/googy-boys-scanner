"""TURTLE forward paper book (scanner/turtle_book.py), added 2026-08-21.

The five-year replay cannot answer "does this work" -- its universe is today's
listed names, so it was selected on outcomes the system could not have known.
This book is the honest test: it starts flat, takes only what fires from the
day it starts, and pays costs. These tests exist because a forward record that
is quietly wrong is worse than no forward record at all -- it looks like
evidence.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from scanner import config, turtle_book as tb

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolated_book(tmp_path, monkeypatch):
    """Never touch the real journal/ from a test run."""
    monkeypatch.setattr(tb, "BOOK_DIR", str(tmp_path))
    yield


def row(sym, price, n, signal="", sector="Materials", o=None, h=None, l=None,
        x1lo=None, x2lo=None, x1hi=1e9, x2hi=1e9, dvol=1e7):
    o = price if o is None else o
    h = price if h is None else h
    l = price if l is None else l
    return {"symbol": sym, "name": sym, "sector": sector, "price": price,
            "n": n, "dvol": dvol, "signal": signal, "state": "flat",
            "bar": {"o": o, "h": h, "l": l, "c": price},
            "exits": {"x1_lo": x1lo if x1lo is not None else price * 0.5,
                      "x2_lo": x2lo if x2lo is not None else price * 0.5,
                      "x1_hi": x1hi, "x2_hi": x2hi}}


# ---------------------------------------------------------------------------
# it only ever takes what fires FROM NOW
# ---------------------------------------------------------------------------

def test_it_starts_flat_and_takes_only_what_fires():
    """The whole point. A book that inherited the replay's open positions
    would inherit the replay's survivorship with them."""
    b = tb.update("asx", [row("AAA", 100.0, 2.0),           # no signal
                          row("BBB", 50.0, 1.0, "s2_long")], day="2026-08-21")
    assert [p["symbol"] for p in b["open"]] == ["BBB"]
    assert b["started"] == "2026-08-21"


def test_a_unit_is_one_percent_of_equity_per_N():
    b = tb.update("asx", [row("AAA", 100.0, 2.0, "s2_long")], day="2026-08-21")
    pos = b["open"][0]
    # 1% of $5,000 = $50 of risk per N; N = 2.0 -> 25 units
    assert pos["units"] == pytest.approx(25.0)
    assert pos["stop"] == pytest.approx(100.0 - config.TURTLE_STOP_N * 2.0)


def test_the_entry_is_charged_a_fee_immediately():
    b = tb.update("asx", [row("AAA", 100.0, 2.0, "s2_long")], day="2026-08-21")
    pos = b["open"][0]
    assert pos["fees"] > 0, "a forward record without costs is a slower backtest"


# ---------------------------------------------------------------------------
# exits
# ---------------------------------------------------------------------------

def test_a_stop_is_taken_and_booked_net_of_fees():
    tb.update("asx", [row("AAA", 100.0, 2.0, "s2_long")], day="2026-08-21")
    b = tb.update("asx", [row("AAA", 95.0, 2.0, o=98.0, h=99.0, l=95.0,
                              x1lo=50.0, x2lo=50.0)], day="2026-08-22")
    assert not b["open"] and len(b["closed"]) == 1
    t = b["closed"][0]
    assert t["reason"] == tb.STOP
    assert t["exit"] == pytest.approx(96.0), "filled at the stop, not the close"
    assert t["pnl"] < t["gross"], "fees always make the net worse"
    assert t["r"] < t["gross_r"]


def test_the_entering_system_owns_the_exit_channel():
    """A System 2 position must not leave on the 10-day channel just because
    that level arrives first."""
    tb.update("asx", [row("AAA", 100.0, 2.0, "s2_long")], day="2026-08-21")
    # 10-day low is 99 (would exit an S1 book); 20-day low is 90 (does not)
    b = tb.update("asx", [row("AAA", 98.0, 2.0, h=100.0, l=98.0,
                              x1lo=99.0, x2lo=90.0)], day="2026-08-22")
    assert b["open"], "an S2 position must ignore the 10-day channel"
    assert not b["closed"]


def test_a_gap_through_the_stop_books_the_gap():
    tb.update("asx", [row("AAA", 100.0, 2.0, "s2_long")], day="2026-08-21")
    b = tb.update("asx", [row("AAA", 80.0, 2.0, o=80.0, h=81.0, l=79.0,
                              x1lo=50.0, x2lo=50.0)], day="2026-08-22")
    assert b["closed"][0]["exit"] == pytest.approx(80.0), \
        "you are filled at the gap, not at the stop you wanted"


# ---------------------------------------------------------------------------
# pyramiding
# ---------------------------------------------------------------------------

def test_adds_walk_the_shared_stop_up_under_the_whole_position():
    tb.update("asx", [row("AAA", 100.0, 2.0, "s2_long")], day="2026-08-21")
    b = tb.update("asx", [row("AAA", 101.5, 2.0, o=100.5, h=101.9, l=100.0)],
                  day="2026-08-22")
    pos = b["open"][0]
    assert len(pos["fills"]) == 2, "one rung reached at +1/2N = 101"
    assert pos["stop"] == pytest.approx(pos["last_fill"] - config.TURTLE_STOP_N * 2.0)
    assert pos["stop"] > 96.0, "the add dragged the first unit's stop up"


def test_the_stop_an_add_raised_is_tested_on_the_same_bar():
    """The engine bug this book must not inherit: a bar that adds a unit,
    raising the shared stop, and then trades through that new stop."""
    tb.update("asx", [row("AAA", 100.0, 2.0, "s2_long")], day="2026-08-21")
    b = tb.update("asx", [row("AAA", 97.0, 2.0, o=101.0, h=104.0, l=97.0,
                              x1lo=50.0, x2lo=50.0)], day="2026-08-22")
    assert b["closed"], "the raised stop must be honoured on its own bar"
    assert b["closed"][0]["reason"] == tb.STOP


def test_a_position_never_exceeds_the_four_unit_ceiling():
    tb.update("asx", [row("AAA", 100.0, 2.0, "s2_long")], day="2026-08-21")
    b = tb.update("asx", [row("AAA", 130.0, 2.0, o=100.5, h=130.0, l=100.0)],
                  day="2026-08-22")
    assert len(b["open"][0]["fills"]) <= config.TURTLE_MAX_UNITS


# ---------------------------------------------------------------------------
# the constraints the replay does not have
# ---------------------------------------------------------------------------

def test_the_book_CANNOT_SPEND_MORE_CASH_THAN_IT_HAS():
    """The replay has no cash constraint and that is a real gap in it: crypto's
    median unit is ~30% of a $5,000 account, so a four-unit position is ~119%
    of the book. Impossible without margin, and the replay records it anyway.

    This is also the finding a reader should take from the book: at 1% risk
    per N, one unit routinely consumes a quarter to a half of a small cash
    account, which is precisely the leverage the Turtles got from futures
    margin and an equity account does not have.
    """
    rows = [row(f"S{i}", 10.0, 0.2, "s2_long") for i in range(12)]
    b = tb.update("asx", rows, day="2026-08-21")
    spent = sum(p["cost_basis"] for p in b["open"])
    cap = config.TURTLE_BOOK_EQUITY * config.TURTLE_BOOK_MAX_NOTIONAL_PCT / 100.0
    assert spent <= cap + 1e-6, f"spent {spent} against a {cap} account"
    assert any(k["reason"] == tb.SKIP_CASH for k in b["skips"]), \
        "and it records WHY it stopped, from the closed enum"


def test_the_correlated_bucket_cap_is_ENFORCED_not_merely_displayed():
    # tiny N relative to price -> small notional, so cash does not bind first
    rows = [row(f"S{i}", 1.0, 0.5, "s2_long", sector="Materials") for i in range(10)]
    b = tb.update("asx", rows, day="2026-08-21")
    assert len(b["open"]) <= config.TURTLE_MAX_UNITS_CLOSE_CORR
    assert any(k["reason"] == tb.SKIP_CLOSE_CORR_CAP for k in b["skips"])


def test_crypto_is_ONE_correlated_bucket_because_it_behaves_like_one_market():
    rows = [row(f"C{i}", 1.0, 0.5, "s2_long", sector="") for i in range(10)]
    b = tb.update("crypto", rows, day="2026-08-21")
    assert len(b["open"]) <= config.TURTLE_MAX_UNITS_CLOSE_CORR, \
        "pretending coins are uncorrelated is how a book holds one bet twelve times"


def test_the_drawdown_rule_compounds_and_shrinks_the_next_unit():
    b = tb.empty_book("asx")
    b["closed"] = [{"pnl": -1000.0, "r": -1.0}]          # 20% down on 5,000
    assert tb.realized_equity(b) == pytest.approx(4000.0)
    assert tb.sizing_equity(b) == pytest.approx(4000.0 * 0.64), "two 10% steps"


def test_PYRAMIDS_COUNT_AGAINST_THE_DIRECTION_CAP():
    """The largest silent way this stops being the Turtle system.

    The ceilings are on TOTAL UNITS, not on positions. Checking them only when
    a new NAME opens lets twelve names each pyramid to four and hold 48 units
    one way against a 12-unit cap -- the book would look diversified and be
    four times the intended size in one direction.
    """
    # 6 names, small N so cash does not bind, all one sector -> 6-unit bucket cap
    day1 = [row(f"S{i}", 1.0, 0.5, "s2_long", sector="Materials") for i in range(8)]
    b = tb.update("asx", day1, day="2026-08-21")
    opened = len(b["open"])
    assert opened == config.TURTLE_MAX_UNITS_CLOSE_CORR, \
        f"the bucket cap should bind at {config.TURTLE_MAX_UNITS_CLOSE_CORR}, got {opened}"

    # now let every one of them run far enough to want three more units each.
    # x2lo well below the bar keeps the 20-day channel out of the way -- this
    # test is about the ceilings, not about exits.
    day2 = [row(f"S{i}", 3.0, 0.5, o=1.1, h=3.0, l=1.05, x1lo=0.1, x2lo=0.1)
            for i in range(8)]
    b = tb.update("asx", day2, day="2026-08-22")
    total_units = sum(len(p["fills"]) for p in b["open"])
    assert total_units <= config.TURTLE_MAX_UNITS_DIRECTION, \
        f"{total_units} units one way against a {config.TURTLE_MAX_UNITS_DIRECTION}-unit cap"
    capped = [k for k in b["skips"] if k["action"] == "add"
              and k["reason"] in (tb.SKIP_DIRECTION_CAP, tb.SKIP_CLOSE_CORR_CAP)]
    assert capped, "and it must record which ceiling stopped the pyramid"
    assert capped[0]["cap"] and capped[0]["units_on_book"] is not None, \
        "with enough detail to reproduce the decision"


def test_the_bucket_cap_also_binds_on_a_pyramid_rung():
    day1 = [row(f"S{i}", 1.0, 0.5, "s2_long", sector="Materials") for i in range(3)]
    tb.update("asx", day1, day="2026-08-21")
    day2 = [row(f"S{i}", 3.0, 0.5, o=1.1, h=3.0, l=1.05, x1lo=0.1, x2lo=0.1)
            for i in range(3)]
    b = tb.update("asx", day2, day="2026-08-22")
    bucket_units = sum(len(p["fills"]) for p in b["open"]
                       if (p.get("sector") or "").lower() == "materials")
    assert bucket_units <= config.TURTLE_MAX_UNITS_CLOSE_CORR


def test_a_name_stopped_out_TODAY_cannot_be_refilled_TODAY():
    """The manage loop can flatten a name and the entry loop would then see it
    flat and refill the very breakout that just stopped out. The rules wait for
    a NEW channel break, not the same one still standing."""
    tb.update("asx", [row("AAA", 100.0, 2.0, "s2_long")], day="2026-08-21")
    # gaps down through the stop AND still prints a fresh breakout signal
    b = tb.update("asx", [row("AAA", 90.0, 2.0, "s2_long", o=90.0, h=120.0,
                              l=89.0, x1lo=50.0, x2lo=50.0)], day="2026-08-22")
    assert len(b["closed"]) == 1, "it must stop out"
    assert not b["open"], "and it must NOT be refilled the same session"
    assert any(k["reason"] == tb.SKIP_SAME_BAR_REENTRY for k in b["skips"])
    assert b["skip_counts"].get(tb.SKIP_SAME_BAR_REENTRY) == 1


def test_the_next_session_may_re_enter_normally():
    """The block is same-session only -- a genuinely new break the next day is
    a legitimate Turtle entry and must not be suppressed."""
    tb.update("asx", [row("AAA", 100.0, 2.0, "s2_long")], day="2026-08-21")
    tb.update("asx", [row("AAA", 90.0, 2.0, "s2_long", o=90.0, h=120.0, l=89.0,
                          x1lo=50.0, x2lo=50.0)], day="2026-08-22")
    b = tb.update("asx", [row("AAA", 95.0, 2.0, "s2_long")], day="2026-08-23")
    assert b["open"] and b["open"][0]["symbol"] == "AAA"


def test_skips_are_counted_not_merely_logged():
    """A book that quietly declines half its signals looks identical to one
    that had no signals. Which ceiling is binding is the whole story."""
    rows = [row(f"S{i}", 10.0, 0.2, "s2_long") for i in range(12)]
    b = tb.update("asx", rows, day="2026-08-21")
    assert b["skip_counts"]["total"] > 0
    assert b["skip_counts"].get(tb.SKIP_CASH, 0) > 0
    # every recorded reason is from the closed enum -- an unknown one is a bug
    for k in b["skips"]:
        assert k["reason"] in tb.SKIP_REASONS, k["reason"]
        for field in ("as_of", "market", "symbol", "action", "reason"):
            assert k.get(field), f"skip record missing {field}: {k}"
        assert k["action"] in ("entry", "add")


def test_the_per_name_ceiling_records_itself_when_it_bites():
    """A position at 4 units that WANTS a fifth must say so. Silently not
    adding is indistinguishable from the price never reaching the rung."""
    tb.update("asx", [row("AAA", 100.0, 2.0, "s2_long")], day="2026-08-21")
    tb.update("asx", [row("AAA", 130.0, 2.0, o=100.5, h=130.0, l=100.0,
                          x1lo=1.0, x2lo=1.0)], day="2026-08-22")
    b = tb.update("asx", [row("AAA", 200.0, 2.0, o=140.0, h=200.0, l=139.0,
                              x1lo=1.0, x2lo=1.0)], day="2026-08-23")
    assert len(b["open"][0]["fills"]) == config.TURTLE_MAX_UNITS
    assert any(k["reason"] == tb.SKIP_PER_MARKET_CAP for k in b["skips"]), \
        "the 4-unit ceiling must record itself"


def test_a_futures_unit_under_one_contract_is_REFUSED_not_rounded():
    """Rounding 0.025 contracts up to 1 is roughly 40x the intended size and
    is the commonest way a small account destroys itself while believing it is
    following rules. The refusal is the honest output."""
    r = row("CL", 70.0, 2.0, "s2_long", sector="")
    r["contracts"] = {"dpp": 1000, "micro": "MCL", "micro_dpp": 100,
                      "full_contracts": 0.025, "micro_contracts": 0.25,
                      "unit_fits": False, "one_contract_risk_pct": 8.0}
    b = tb.update("futures", [r], day="2026-08-21")
    assert not b["open"], "a fraction of a contract cannot be bought"
    sk = [k for k in b["skips"] if k["reason"] == tb.SKIP_UNIT_LT_ONE]
    assert sk and sk[0]["one_contract_risk_pct"] == 8.0, \
        "and it records what taking one anyway would really risk"


def test_a_futures_unit_that_DOES_fit_is_taken_normally():
    # $50 of risk (1% of 5,000); N = 5.00 at $5 a point -> exactly 2 contracts.
    r = row("MES", 5000.0, 5.0, "s2_long", sector="")
    r["contracts"] = {"dpp": 50, "micro": "MES", "micro_dpp": 5,
                      "full_contracts": 0.2, "micro_contracts": 2.0,
                      "unit_fits": True, "one_contract_risk_pct": 1.0}
    b = tb.update("futures", [r], day="2026-08-21")
    assert [p["symbol"] for p in b["open"]] == ["MES"]
    pos = b["open"][0]
    assert pos["contracts"] == 2 and pos["contract"] == "MES", \
        "1% of 5,000 = $50 of risk; N=20 at $5/pt -> 0.5 -> 2 micro contracts"
    assert pos["units"] == pytest.approx(pos["contracts"] * 5), \
        "units carries contracts x dpp so P&L arithmetic stays correct"


def test_every_skip_reason_the_module_can_emit_is_in_the_closed_enum():
    """An unknown reason must be a bug, not a shrug. _skip() asserts on the
    way in; this pins that the enum is actually closed at the source."""
    src = (ROOT / "scanner" / "turtle_book.py").read_text(encoding="utf-8")
    assert "assert reason in SKIP_REASONS" in src
    import re
    emitted = set(re.findall(r"_skip\([^)]*?(SKIP_[A-Z_]+)", src, re.S))
    assert emitted, "no skip reasons emitted?"
    for e in emitted:
        assert getattr(tb, e) in tb.SKIP_REASONS


def test_the_two_unemitted_enum_values_are_documented_as_such():
    """loose_corr_cap and s1_skip_after_win are never emitted here. An enum
    with unexplained dead entries invites someone to wire them wrongly."""
    src = (ROOT / "scanner" / "turtle_book.py").read_text(encoding="utf-8")
    assert "never emitted" in src
    assert "Loosely correlated" in src and "taxonomy this repo" in src, \
        "the loose-correlation taxonomy gap must be stated"


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------

def test_the_book_survives_a_round_trip_and_keeps_accumulating():
    tb.update("asx", [row("AAA", 100.0, 2.0, "s2_long")], day="2026-08-21")
    # 100.5 is below the +1/2N rung at 101, so AAA does not pyramid and eat
    # the cash BBB needs -- the add path has its own tests.
    tb.update("asx", [row("AAA", 100.5, 2.0), row("BBB", 20.0, 0.4, "s2_long")],
              day="2026-08-22")
    b = tb.load_book("asx")
    assert {p["symbol"] for p in b["open"]} == {"AAA", "BBB"}
    assert b["started"] == "2026-08-21", "the start date is never rewritten"


def test_a_name_missing_from_todays_scan_is_carried_and_counted_unpriced():
    """It must not be silently closed. A name that drops out of the scan is
    unpriced, not exited -- inventing an exit price would fabricate a result."""
    tb.update("asx", [row("AAA", 100.0, 2.0, "s2_long")], day="2026-08-21")
    b = tb.update("asx", [], day="2026-08-22")
    assert len(b["open"]) == 1
    assert b["open"][0]["unpriced_runs"] == 1
    assert not b["closed"]


def test_the_published_file_is_strictly_finite():
    tb.update("asx", [row("AAA", 100.0, 2.0, "s2_long")], day="2026-08-21")
    text = pathlib.Path(tb.book_path("asx")).read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text
    json.loads(text)


def test_the_combined_view_is_derived_from_the_per_market_files(tmp_path, monkeypatch):
    monkeypatch.setattr(tb, "ROOT", str(tmp_path))
    (tmp_path / "public" / "data").mkdir(parents=True)
    tb.update("asx", [row("AAA", 100.0, 2.0, "s2_long")], day="2026-08-21")
    tb.update("crypto", [row("BTC", 100.0, 2.0, "s2_long", sector="")], day="2026-08-21")
    tb.write_combined()
    c = json.loads(pathlib.Path(tb.BOOK_DIR, "turtle_book.json").read_text(encoding="utf-8"))
    assert {p["symbol"] for p in c["open"]} == {"AAA", "BTC"}
    assert set(c["by_market"]) == {"asx", "crypto"}
    assert c["equity_start"] == pytest.approx(2 * config.TURTLE_BOOK_EQUITY)


# ---------------------------------------------------------------------------
# fences
# ---------------------------------------------------------------------------

def test_the_book_never_imports_the_paper_bot():
    """The owner's standing requirement: Turtle stays completely separate --
    own file, own slot pool, own equity, own sizing."""
    src = (ROOT / "scanner" / "turtle_book.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        if line.strip().startswith(("import ", "from ")):
            assert "broker" not in line, f"imports the bot: {line}"
            assert "vivek" not in line.lower(), f"imports VIVEK: {line}"


def test_nothing_under_broker_knows_this_book_exists():
    for p in (ROOT / "scanner" / "broker").rglob("*.py"):
        assert "turtle" not in p.read_text(encoding="utf-8").lower(), \
            f"the Turtle book must not reach the bot: {p}"


def test_it_writes_only_its_own_files():
    """Asked of the CODE, not of the file's text -- the module docstring
    explains that it borrows the bot book's SHAPE, and a substring ban reads
    that justification as the offence (the Tier 3 trap)."""
    src = (ROOT / "scanner" / "turtle_book.py").read_text(encoding="utf-8")
    code = [ln for ln in src.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    # drop docstrings: everything between a line opening ''' and the next one
    body, inside = [], False
    for ln in code:
        ticks = ln.count('"""')
        if inside:
            if ticks:
                inside = False
            continue
        if ticks == 1:
            inside = True
            continue
        if ticks >= 2:
            continue
        body.append(ln)
    joined = "\n".join(body)
    for forbidden in ("vivek_bot_book", "bot_rules", "sector_map",
                      "alert_history", "scalp", "swing"):
        assert forbidden not in joined, f"the Turtle book touches {forbidden}"


def test_writes_are_atomic():
    src = (ROOT / "scanner" / "turtle_book.py").read_text(encoding="utf-8")
    assert "atomic_write" in src
    assert "open(path, \"w\")" not in src, "project rule 7: temp + os.replace"


# ---------------------------------------------------------------------------
# futures write isolation -- asked of the WRITES, not of the code's shape
# ---------------------------------------------------------------------------
# The futures sleeve became a fourth market on 2026-08-21. Everything below
# exists because "a market's run can only write its own file" was, until now,
# a property of how book_path() HAPPENS to be spelled -- which is how an
# invariant quietly stops being true. These tests observe the filesystem:
# mispoint the futures write path at an equity journal and they die.

def _futures_row(sym="MES", price=5000.0, n=5.0):
    r = row(sym, price, n, "s2_long", sector="")
    r["contracts"] = {"dpp": 50, "micro": "MES", "micro_dpp": 5,
                      "full_contracts": 0.2, "micro_contracts": 2.0,
                      "unit_fits": True, "one_contract_risk_pct": 1.0}
    return r


def test_a_futures_run_writes_ONLY_the_futures_file():
    """The whole isolation claim, as an observation: after a futures session
    that OPENED a position -- so the write path definitely ran -- the book
    directory contains exactly one file, and it is the futures one. A write
    path pointed at turtle_book.asx.json (or any equity journal) fails this
    on both sides: the wrong file exists and the right one does not."""
    b = tb.update("futures", [_futures_row()], day="2026-08-21")
    assert b["open"], "the entry must actually have been taken and persisted"
    written = sorted(p.name for p in pathlib.Path(tb.BOOK_DIR).iterdir())
    assert written == ["turtle_book.futures.json"], \
        f"a futures run wrote {written}"


def test_a_futures_run_cannot_alter_a_live_equity_book(tmp_path, monkeypatch):
    """The live equity books are append-only forward records that cannot be
    backfilled. Seed all three, run a futures session that opens AND the
    combined regeneration after it, and require every equity book back
    BYTE-identical -- not merely 'same symbols', because a rewrite that
    reorders keys or restamps generated_at is still a foreign write."""
    monkeypatch.setattr(tb, "ROOT", str(tmp_path))
    (tmp_path / "public" / "data").mkdir(parents=True, exist_ok=True)
    for m in ("asx", "nasdaq", "crypto"):
        tb.update(m, [row("AAA", 100.0, 2.0, "s2_long")], day="2026-08-20")
    before = {m: pathlib.Path(tb.book_path(m)).read_bytes()
              for m in ("asx", "nasdaq", "crypto")}
    tb.update("futures", [_futures_row()], day="2026-08-21")
    tb.write_combined()
    for m, blob in before.items():
        assert pathlib.Path(tb.book_path(m)).read_bytes() == blob, \
            f"the futures run altered the {m} book"


def test_the_combined_view_INCLUDES_the_futures_book(tmp_path, monkeypatch):
    """The page's BOOK view reads ONLY the combined file (turtle.js fetches
    data/turtle_book.json and nothing per-market), so a futures book absent
    from write_combined's default is a futures book that exists on disk and
    renders NOWHERE -- including the cash-unconstrained disclosure the page
    keys off open futures positions. Reverting the default to the equity
    trio turns this red."""
    monkeypatch.setattr(tb, "ROOT", str(tmp_path))
    (tmp_path / "public" / "data").mkdir(parents=True, exist_ok=True)
    tb.update("asx", [row("AAA", 100.0, 2.0, "s2_long")], day="2026-08-21")
    tb.update("futures", [_futures_row()], day="2026-08-21")
    tb.write_combined()
    c = json.loads(pathlib.Path(tb.BOOK_DIR, "turtle_book.json")
                   .read_text(encoding="utf-8"))
    assert "futures" in c["by_market"], "the by_market table must carry it"
    assert any(p.get("market") == "futures" for p in c["open"]), \
        "the open futures position must reach the page"
    assert any(p.get("market") == "asx" for p in c["open"]), \
        "and the equity books must still be there beside it"
