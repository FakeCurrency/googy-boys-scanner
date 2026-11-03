"""The session-level journal/ check in tests/conftest.py (NEXT100 #10) -- pinned.

conftest hashes every file under journal/ on the session's CONTROLLER at start
and at finish, and fails the session if anything changed, appeared or went
(CLAUDE.md rule 1 reads a post-test diff there as a REAL change, so a leak
would be committed as truth). A hook nothing exercises can rot silently -- a
refactor drops the exit-status line and every leak goes green again -- so its
working parts are driven here on fakes: the digest, the diff, the finish
hook's verdict, and that an xdist WORKER never snapshots or judges (it would
see its siblings' writes mid-run). End to end it was mutation-verified with a
throwaway test that wrote journal/ (plain run and -n 2: exit 1, files named).
"""
import types

import pytest

from tests import conftest as cf


class _Reporter:
    """Stands in for pytest's terminalreporter: records what it was asked to print."""
    def __init__(self):
        self.out = []

    def write_line(self, line, **markup):
        self.out.append(line)

    def write_sep(self, sep, title=None, **markup):
        self.out.append(f"{sep * 3} {title} {sep * 3}")


def _session(exitstatus=pytest.ExitCode.OK, worker=False, reporter=None):
    plugins = {"terminalreporter": reporter} if reporter is not None else {}
    config = types.SimpleNamespace(stash={}, pluginmanager=types.SimpleNamespace(get_plugin=plugins.get))
    if worker:
        config.workerinput = {"workerid": "gw0"}
    return types.SimpleNamespace(config=config, exitstatus=exitstatus)


@pytest.fixture
def journal(tmp_path, monkeypatch):
    j = tmp_path / "journal"
    (j / "sub").mkdir(parents=True)
    (j / "alert_state.json").write_text("{}", encoding="utf-8")
    (j / "sub" / "book.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(cf, "ROOT", tmp_path)
    monkeypatch.setattr(cf, "JOURNAL_DIR", j)
    return j


def test_the_digest_hashes_every_file_under_journal(journal):
    d = cf._journal_digest()
    assert sorted(d) == ["journal/alert_state.json", "journal/sub/book.json"]
    (journal / "alert_state.json").write_text("{ }", encoding="utf-8")       # one byte more
    assert cf._journal_digest()["journal/alert_state.json"] != d["journal/alert_state.json"]


def test_the_diff_names_every_changed_added_and_removed_file():
    before = {"journal/a": "1", "journal/b": "2", "journal/c": "3"}
    after = {"journal/a": "1", "journal/b": "X", "journal/d": "4"}
    assert cf._journal_changes(before, after) == [
        "changed  journal/b", "removed  journal/c", "added    journal/d"]
    assert cf._journal_changes(before, dict(before)) == []


def test_a_journal_that_moved_fails_a_green_session(journal, capsys):
    s = _session()
    cf.pytest_sessionstart(s)
    cf.pytest_sessionfinish(s, s.exitstatus)
    assert s.exitstatus == pytest.ExitCode.OK, "an untouched journal must not fail anything"
    assert capsys.readouterr().err == ""
    (journal / "alert_state.json").write_text('{"last_sent": {}}', encoding="utf-8")
    (journal / "leak.json").write_text("{}", encoding="utf-8")
    cf.pytest_sessionfinish(s, s.exitstatus)
    assert s.exitstatus == pytest.ExitCode.TESTS_FAILED
    err = capsys.readouterr().err
    assert "changed  journal/alert_state.json" in err and "added    journal/leak.json" in err
    assert err.isascii(), "the report must print on a cp1252 console"


def test_the_report_goes_to_the_terminal_reporter_when_there_is_one(journal, capsys):
    tr = _Reporter()
    s = _session(reporter=tr)
    cf.pytest_sessionstart(s)
    (journal / "sub" / "book.json").unlink()
    cf.pytest_sessionfinish(s, s.exitstatus)
    assert s.exitstatus == pytest.ExitCode.TESTS_FAILED
    text = "\n".join(tr.out)
    assert "journal/ is NOT byte-clean" in text and "removed  journal/sub/book.json" in text
    assert text.isascii(), "the report must print on a cp1252 console"
    assert capsys.readouterr().err == ""


def test_a_session_that_already_failed_keeps_its_own_status(journal):
    s = _session(exitstatus=pytest.ExitCode.INTERRUPTED)
    cf.pytest_sessionstart(s)
    (journal / "alert_state.json").unlink()
    cf.pytest_sessionfinish(s, s.exitstatus)
    assert s.exitstatus == pytest.ExitCode.INTERRUPTED


def test_an_xdist_worker_never_snapshots_or_judges(journal):
    s = _session(worker=True)
    cf.pytest_sessionstart(s)
    assert s.config.stash == {}
    # and a worker holding a snapshot anyway still leaves the verdict to the controller
    s.config.stash[cf._JOURNAL_AT_START] = cf._journal_digest()
    (journal / "alert_state.json").write_text("changed", encoding="utf-8")
    cf.pytest_sessionfinish(s, s.exitstatus)
    assert s.exitstatus == pytest.ExitCode.OK


def test_the_running_session_took_its_snapshot(request):
    """The hooks are live in THIS suite: the module the tests above drive is
    the registered conftest, and (outside an xdist worker) its snapshot of the
    real journal/ is in the session's stash."""
    assert request.config.pluginmanager.is_registered(cf)
    assert cf._is_xdist_worker(request.config) or cf._JOURNAL_AT_START in request.config.stash
