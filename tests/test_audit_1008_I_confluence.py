"""Audit #62 (2026-10-08): ``confluence_alert --dry-run`` must write nothing.

The module docstring promises ``--dry-run  # preview, write nothing new``, but
main() returned early only when something was push-worthy. Under the
triples-only threshold the common dry run (2-lens alignments only) fell
through to ``_save_state_if_changed`` and recorded the new alignments as seen
(-count) in journal/confluence_state.json. The next REAL run's ``diff_new``
then found nothing fresh and never wrote them to alert_history.json - the
ALERTS page log the edge pipeline ingests - so they were never measured.
Drives the SHIPPED main() against a tmp filesystem.
"""

import json

import pytest

from scanner import confluence_alert as ca


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "phasemap" / "asx").mkdir(parents=True)
    monkeypatch.setattr(ca, "DATA", data)
    monkeypatch.setattr(ca, "STATE_FILE", tmp_path / "journal" / "confluence_state.json")
    monkeypatch.setattr(ca, "HISTORY_FILE", data / "phasemap" / "alert_history.json")
    monkeypatch.setattr(ca.config, "CONF_ALERT_MIN_LENSES", 3, raising=False)
    (tmp_path / "journal").mkdir()

    def scan(count):
        vivek = {"results": [{"symbol": "WES", "dir": "LONG", "grade": "A+"}]}
        pm = {"results": [{"ticker": "WES", "direction": "bullish",
                           "state": "SWEPT", "tier": "T1"}]}
        spec = {"results": [{"symbol": "WES", "grade": "A"}] if count >= 3 else []}
        (data / "asx_vivek.json").write_text(json.dumps(vivek), encoding="utf-8")
        (data / "phasemap" / "asx" / "latest.json").write_text(json.dumps(pm), encoding="utf-8")
        (data / "asx_spec.json").write_text(json.dumps(spec), encoding="utf-8")
    return scan


def _logged(path):
    if not path.exists():
        return []
    return [e.get("ticker") for e in
            json.loads(path.read_text(encoding="utf-8")).get("entries", [])]


@pytest.mark.parametrize("count", [2, 3])   # below AND at the push threshold
def test_a_dry_run_writes_no_state_and_no_history(wired, count):
    wired(count)
    assert ca.main(["--market", "asx", "--dry-run"]) == 0
    assert not ca.STATE_FILE.exists()
    assert not ca.HISTORY_FILE.exists()


def test_a_dry_run_leaves_an_existing_state_byte_identical(wired):
    ca.STATE_FILE.write_text('{"asx:OLD:long": -2}\n', encoding="utf-8")
    before = ca.STATE_FILE.read_bytes()
    wired(2)
    ca.main(["--market", "asx", "--dry-run"])
    assert ca.STATE_FILE.read_bytes() == before


def test_the_real_run_after_a_dry_run_still_logs_the_alignment(wired):
    # The failure the audit traced: preview, then the scheduled run.
    wired(2)
    ca.main(["--market", "asx", "--dry-run"])
    assert ca.main(["--market", "asx"]) == 0
    assert "WES" in _logged(ca.HISTORY_FILE)
    assert json.loads(ca.STATE_FILE.read_text(encoding="utf-8")) == {"asx:WES:long": -2}
