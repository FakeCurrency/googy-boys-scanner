"""Global position ceiling across markets (owner decision, 2026-07-28).

The book used to be capped at 10 positions PER MARKET, which meant it sat at a
fixed 10/10/10 shape no matter where the A+ setups actually were. The owner
asked for 30 positions total, free to distribute — so the per-market cap is now
non-binding (set equal to the total) and the real ceiling is
config.VIVEK_BOT_MAX_OPEN_TOTAL, enforced across the canonical per-market book
files.

decide() only ever sees one market's scan, so vivek_run supplies the count from
the others. These pin both halves, and pin that the correlation control (3 per
sector) was deliberately NOT relaxed with it.
"""

import json

import pytest

from scanner import config
from scanner.broker import vivek_bot as vb
from scanner.broker import vivek_run as vr

pytestmark = pytest.mark.risk

# 11 distinct GICS-ish sectors so the per-sector cap (3) is not what binds in
# the tests that are about the global cap. One test below deliberately re-uses
# a single sector to prove that cap is still live.
SECTORS = ["Banks", "Materials", "Energy", "Utilities", "Real Estate",
           "Retailing", "Insurance", "Transportation", "Media", "Software",
           "Pharmaceuticals"]


def _plan(**kw):
    p = {"armed": True, "entry_trigger": "reclaim",
         "entry": 100.0, "stop": 96.0, "tp1": 106.0, "tp2": 112.0, "tp3": 120.0,
         "rr": 3.0, "scale": [0.25, 0.50, 0.15]}
    p.update(kw)
    return p


def _rows(n, sectors=None):
    """n distinct A+ long setups, each in its own sector unless told otherwise."""
    out = []
    for i in range(n):
        sec = sectors[i % len(sectors)] if sectors else SECTORS[i % len(SECTORS)]
        out.append({"symbol": f"S{i:02d}", "name": f"S{i:02d} Ltd", "sector": sec,
                    "dir": "LONG", "grade": "A+", "entry_types": ["reclaim"],
                    "price": 100.0, "plans": {"1W": _plan()}})
    return out


def _held(n, market_sectors=None):
    """n positions already open in THIS market."""
    return [{"symbol": f"H{i:02d}", "direction": "long",
             "sector": (market_sectors or SECTORS)[i % len(market_sectors or SECTORS)]}
            for i in range(n)]


# ── the owner's decision, pinned ─────────────────────────────────────────────

def test_the_book_holds_thirty_total_and_the_sector_cap_is_untouched():
    # Change these deliberately (they are the owner's, not an implementation
    # detail) — and update this test in the same commit when you do.
    assert config.VIVEK_BOT_MAX_OPEN_TOTAL == 30
    assert config.VIVEK_BOT_MAX_PER_SECTOR == 3
    # The per-market cap must never be the tighter of the two, or a market
    # could not hold the whole book and "30 total, flexible" would be a lie.
    assert config.VIVEK_BOT_MAX_POSITIONS >= config.VIVEK_BOT_MAX_OPEN_TOTAL


# ── decide(): the global gate ────────────────────────────────────────────────

def test_positions_open_in_other_markets_consume_this_market_s_room():
    d = vb.decide(_rows(10), equity=10_000, market="asx", open_book=[],
                  max_open_total=30, open_elsewhere=27)
    assert len(d["plans"]) == 3
    assert d["summary"]["skip_reasons"]["global_cap"] == 7
    assert d["summary"]["open_elsewhere"] == 27


def test_a_full_book_elsewhere_leaves_this_market_nothing():
    d = vb.decide(_rows(5), equity=10_000, market="crypto", open_book=[],
                  max_open_total=30, open_elsewhere=30)
    assert d["plans"] == []
    assert d["summary"]["skip_reasons"]["global_cap"] == 5


def test_this_market_s_own_open_positions_count_against_the_same_ceiling():
    # 26 elsewhere + 3 already held here = 29 of 30, so exactly one more.
    d = vb.decide(_rows(6), equity=10_000, market="asx", open_book=_held(3),
                  max_open_total=30, open_elsewhere=26)
    assert len(d["plans"]) == 1


def test_one_market_may_hold_the_entire_book():
    # Nothing open anywhere else: ASX alone can fill all 30 slots. This is the
    # whole point of the change — the old 10-per-market cap forbade it.
    d = vb.decide(_rows(40), equity=10_000, market="asx", open_book=[],
                  max_open_total=30, open_elsewhere=0)
    assert len(d["plans"]) == 30
    # Both caps sit at 30 here, and book_full is evaluated first, so the tail is
    # refused under whichever of the two names — what matters is that 30 got in.
    r = d["summary"]["skip_reasons"]
    assert r.get("book_full", 0) + r.get("global_cap", 0) == 10


def test_the_global_gate_is_off_unless_the_runner_asks_for_it():
    # Back-compat: every other caller (backtester, tooling, older tests) passes
    # no global kwargs and must keep getting the plain per-market behaviour.
    d = vb.decide(_rows(12), equity=10_000, market="asx", open_book=[])
    assert len(d["plans"]) == 12
    assert "global_cap" not in d["summary"]["skip_reasons"]
    assert d["summary"]["max_open_total"] == 0


def test_an_unreadable_sibling_book_stops_new_entries_rather_than_guessing():
    # open_elsewhere=None means the runner could not count the other markets.
    # Failing OPEN here would let the book blow through the ceiling silently.
    d = vb.decide(_rows(4), equity=10_000, market="asx", open_book=[],
                  max_open_total=30, open_elsewhere=None)
    assert d["plans"] == []
    assert d["summary"]["skip_reasons"]["global_cap_unknown"] == 4
    assert d["summary"]["open_elsewhere"] is None


def test_the_sector_cap_still_binds_inside_the_bigger_book():
    # 20 setups, all one sector, and 30 slots of global room: the correlation
    # control is what must stop this becoming one macro bet, not the book size.
    d = vb.decide(_rows(20, sectors=["Materials"]), equity=10_000, market="asx",
                  open_book=[], max_open_total=30, open_elsewhere=0)
    assert len(d["plans"]) == config.VIVEK_BOT_MAX_PER_SECTOR
    assert d["summary"]["skip_reasons"]["sector_cap"] == 17


# ── vivek_run._open_elsewhere(): the cross-market count ──────────────────────

def _write_book(tmp_path, market, n_open):
    (tmp_path / f"vivek_bot_book.{market}.json").write_text(json.dumps({
        "version": 2, "mode": "paper", "market": market,
        "open": [{"symbol": f"{market[:2].upper()}{i}", "market": market,
                  "direction": "long"} for i in range(n_open)],
        "closed": []}), encoding="utf-8")


@pytest.fixture
def book_dir(tmp_path, monkeypatch):
    """Point the runner's book paths at a temp dir — BOTH of them, so a real
    journal/vivek_bot_book.unassigned.json could never leak into a test."""
    monkeypatch.setattr(vr, "BOOK_DIR", tmp_path)
    monkeypatch.setattr(vr, "UNASSIGNED_FILE", tmp_path / "vivek_bot_book.unassigned.json")
    return tmp_path


def test_open_elsewhere_sums_the_other_markets_and_skips_our_own(book_dir):
    tmp_path = book_dir
    _write_book(tmp_path, "asx", 10)
    _write_book(tmp_path, "nasdaq", 8)
    _write_book(tmp_path, "crypto", 3)
    assert vr._open_elsewhere("asx") == 11        # nasdaq + crypto
    assert vr._open_elsewhere("crypto") == 18     # asx + nasdaq


def test_a_market_that_has_never_traded_contributes_nothing(book_dir):
    _write_book(book_dir, "nasdaq", 4)
    # asx + crypto files simply do not exist yet (fresh clone).
    assert vr._open_elsewhere("asx") == 4


def test_an_unreadable_sibling_book_reports_unknown_not_zero(book_dir):
    _write_book(book_dir, "nasdaq", 4)
    (book_dir / "vivek_bot_book.crypto.json").write_text("{ truncated", encoding="utf-8")
    assert vr._open_elsewhere("asx") is None


def test_positions_belonging_to_no_market_still_count_against_the_ceiling(book_dir):
    # Rows whose market is not in config.MARKETS live in the unassigned file.
    # They are open risk on the journal page and sit in NO market's open_book,
    # so if the ceiling ignored them the book could quietly exceed 30.
    _write_book(book_dir, "nasdaq", 4)
    (book_dir / "vivek_bot_book.unassigned.json").write_text(json.dumps({
        "entries": [{"symbol": "OLD1", "status": "open"},
                    {"symbol": "OLD2", "status": "open"},
                    {"symbol": "OLD3", "status": "closed"}]}), encoding="utf-8")
    assert vr._open_elsewhere("asx") == 6         # 4 nasdaq + 2 still-open strays


def test_an_unreadable_unassigned_file_also_fails_closed(book_dir):
    _write_book(book_dir, "nasdaq", 4)
    (book_dir / "vivek_bot_book.unassigned.json").write_text("{ truncated", encoding="utf-8")
    assert vr._open_elsewhere("asx") is None


def test_untagged_rows_in_a_sibling_book_are_still_counted(book_dir):
    # A row missing its "market" tag must not go uncounted against a risk cap —
    # the file IS that market's book. (This mirrors how _combined_view merges.)
    tmp_path = book_dir
    (tmp_path / "vivek_bot_book.nasdaq.json").write_text(json.dumps({
        "version": 2, "market": "nasdaq", "closed": [],
        "open": [{"symbol": "AAPL", "direction": "long"},        # no market key
                 {"symbol": "MSFT", "market": "nasdaq", "direction": "long"}],
    }), encoding="utf-8")
    assert vr._open_elsewhere("asx") == 2


# ── the correlation control the owner kept, and where it does NOT reach ──────
#
# He left the sector cap at 3 precisely so a 30-position book could not become
# one macro bet. On NASDAQ it cannot do that job: universe._fetch_nasdaq has no
# sector column, so every row arrives with sector='' and decide() exempts them.
# These tests PIN THE HOLE rather than paper over it — fixing it changes which
# trades get taken (bot risk = owner's call), so when he says go, the first two
# below are the ones that must flip. See REFINEMENTS #38.

def _sectorless_rows(n):
    rows = _rows(n)
    for r in rows:
        r["sector"] = ""
    return rows


def test_a_market_with_no_sector_data_has_no_correlation_control():
    # 30 NASDAQ setups that could all be semis: nothing refuses them today.
    d = vb.decide(_sectorless_rows(30), equity=10_000, market="nasdaq",
                  open_book=[], max_open_total=30, open_elsewhere=0)
    assert len(d["plans"]) == 30                      # <- the hole, pinned
    assert "sector_cap" not in d["summary"]["skip_reasons"]


def test_the_blind_sector_cap_is_reported_rather_than_hidden(caplog):
    with caplog.at_level("WARNING"):
        d = vb.decide(_sectorless_rows(12), equity=10_000, market="nasdaq",
                      open_book=[], max_open_total=30, open_elsewhere=0)
    assert d["summary"]["sector_coverage"] == 0.0
    assert d["summary"]["max_per_sector"] == config.VIVEK_BOT_MAX_PER_SECTOR
    assert "no correlation control" in caplog.text
    assert "0/12 scanned rows carry a sector" in caplog.text


def test_a_market_that_does_carry_sectors_reports_full_coverage():
    d = vb.decide(_rows(9), equity=10_000, market="asx", open_book=[],
                  max_open_total=30, open_elsewhere=0)
    assert d["summary"]["sector_coverage"] == 1.0


def test_crypto_keeps_its_correlation_control_without_gics_sectors():
    # Coins carry no sector either, but _sector_key buckets them major/alt off
    # the symbol — so crypto's cap DOES bind. This is the pattern NASDAQ needs.
    d = vb.decide(_sectorless_rows(10), equity=10_000, market="crypto",
                  open_book=[], max_open_total=30, open_elsewhere=0)
    assert len(d["plans"]) == config.VIVEK_BOT_MAX_PER_SECTOR
    assert d["summary"]["sector_coverage"] == 1.0


# ── the published rules ──────────────────────────────────────────────────────

def test_the_dashboard_is_told_about_the_global_cap():
    # bot_rules.json is how the site learns the executing bot's numbers; a cap
    # that exists only in Python would leave the system page quietly wrong.
    import inspect

    from scanner import run as scanner_run
    src = inspect.getsource(scanner_run.main)
    assert '"max_open_total": config.VIVEK_BOT_MAX_OPEN_TOTAL' in src
