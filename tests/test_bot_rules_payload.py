"""bot_rules.json's REFINE200 additions (run.bot_rules_payload).

* open_total / closed_total — the nav badge's "N / 60" and the SYSTEM page's
  closed-trade count, read off the canonical per-market books at publish time.
  open_total is the GLOBAL CAP's own count (vivek_run._book_elsewhere with no
  market excluded), so the badge can never disagree with what blocks a trade.
* entry_quality — the three entry-trigger cohorts the deck tints its chips
  with, copied from the 1MB long-only backtest so the browser stops
  downloading it (#69).
* not_enforced — PORTFOLIO_HEAT_LIMIT / CONSEC_LOSS_PAUSE are declared in
  config and read by no trade path, so they are no longer published as rules
  (#121). Enforcing them is a trade change, the owner's call.
"""

import json

from scanner import config, run
from scanner.broker import vivek_run


def _books(tmp_path, monkeypatch, books, unassigned=None):
    monkeypatch.setattr(vivek_run, "BOOK_DIR", tmp_path)
    monkeypatch.setattr(vivek_run, "UNASSIGNED_FILE", tmp_path / "vivek_bot_book.unassigned.json")
    for m, body in books.items():
        p = tmp_path / f"vivek_bot_book.{m}.json"
        p.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    if unassigned is not None:
        (tmp_path / "vivek_bot_book.unassigned.json").write_text(json.dumps(unassigned), encoding="utf-8")


def _rows(n):
    return [{"symbol": f"S{i}", "notional": 2500} for i in range(n)]


def test_open_and_closed_totals_count_every_canonical_book(tmp_path, monkeypatch):
    _books(tmp_path, monkeypatch, {
        "asx": {"open": _rows(3), "closed": _rows(5)},
        "nasdaq": {"open": _rows(2), "closed": _rows(1)},
    }, unassigned={"entries": [{"status": "open"}, {"status": "closed"}]})
    p = run.bot_rules_payload()
    # crypto has no file (a fresh clone): 0, never an error
    assert p["open_total"] == 3 + 2 + 1, "the unassigned open row counts, as it does for the cap"
    assert p["closed_total"] == 5 + 1
    assert p["open_total"] == vivek_run._book_elsewhere(None)["count"]


def test_an_unreadable_book_publishes_null_never_a_guessed_zero(tmp_path, monkeypatch):
    _books(tmp_path, monkeypatch, {"asx": {"open": _rows(3), "closed": []}, "nasdaq": "{not json"})
    p = run.bot_rules_payload()
    assert p["open_total"] is None
    assert p["closed_total"] is None


def test_entry_quality_carries_only_the_three_cohorts_the_deck_reads(tmp_path):
    f = tmp_path / "vivek_backtest_longonly.json"
    cohort = {"n": 217, "expectancy_r": 0.057, "win_rate": 53.0, "profit_factor": 1.16,
              "total_usd": 7650.04, "max_dd_usd": -19685.46}
    f.write_text(json.dumps({"generated_at": "2026-10-01T15:15:04Z", "results": {
        "by_entry_type": {"break": cohort, "reclaim": {"n": 3}, "mystery": cohort}}}), encoding="utf-8")
    eq = run._entry_quality(f)
    assert eq == {"source": "vivek_backtest_longonly.json", "generated_at": "2026-10-01T15:15:04Z",
                  "by_entry_type": {"break": {"n": 217, "expectancy_r": 0.057, "win_rate": 53.0,
                                              "profit_factor": 1.16}}}, eq


def test_entry_quality_is_null_when_the_backtest_is_missing_or_broken(tmp_path):
    assert run._entry_quality(tmp_path / "absent.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert run._entry_quality(bad) is None
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"results": {"by_entry_type": {}}}), encoding="utf-8")
    assert run._entry_quality(empty) is None


def test_the_published_entry_quality_matches_the_committed_backtest():
    """The deck used to read results.by_entry_type out of this very file."""
    if not run.ENTRY_QUALITY_SOURCE.exists():
        return
    bt = json.loads(run.ENTRY_QUALITY_SOURCE.read_text(encoding="utf-8"))
    eq = run.bot_rules_payload()["entry_quality"]
    for code, s in eq["by_entry_type"].items():
        assert s["expectancy_r"] == bt["results"]["by_entry_type"][code]["expectancy_r"]
        assert s["n"] == bt["results"]["by_entry_type"][code]["n"]


def test_the_unenforced_limits_are_not_published_as_rules():
    p = run.bot_rules_payload()
    assert "consec_loss_pause" not in p and "portfolio_heat_limit_pct" not in p
    ne = p["not_enforced"]
    assert ne["consec_loss_pause"] == config.CONSEC_LOSS_PAUSE
    assert ne["portfolio_heat_limit_pct"] == round(config.PORTFOLIO_HEAT_LIMIT * 100, 4)
    assert "no trade path" in ne["why"]


def test_the_payload_is_json_serialisable():
    json.dumps(run.bot_rules_payload(), allow_nan=False)
