"""Backup completeness (TOP100 #50, 2026-07-28).

`backup_book.yml`'s only gate was `assert_staged.sh "book backup" backups`,
which proves a DIRECTORY appeared. It could not see what was in it, so the
three files this item found missing from `BACKUP_FILES` — sector_history,
sector_map, confluence_state — had never been snapshotted and the nightly run
had been green about it every night regardless.

The tests below are mostly about the two ways that stays fixed: the required
list cannot drift away from the backed-up list, and `verify()` actually bites
on each of the three ways a file in a finished backup can be useless.
"""

import importlib.util
import json
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "backup_journal", _ROOT / "scripts" / "backup_journal.py")
bj = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bj)


# --------------------------------------------------------------------------
# the two lists
# --------------------------------------------------------------------------

def test_every_required_file_is_actually_backed_up():
    """The half-edit this catches: a path removed from BACKUP_FILES but left in
    REQUIRED_FILES. backup() would then never copy it, and verify() would fail
    every night on a file nothing was even trying to save."""
    missing = [r for r in bj.REQUIRED_FILES if r not in bj.BACKUP_FILES]
    assert not missing, (
        f"REQUIRED_FILES entries absent from BACKUP_FILES: {missing} — "
        "nothing copies them, so the nightly verify can only ever fail"
    )


def test_the_accumulated_state_files_are_in_the_backup_list():
    """The #50 additions, pinned by name.

    Each is here because losing it loses something no run recomputes:
    sector_history is the only long sector memory (and holds the sector_run
    ping dedupe); sector_map is a SIGNAL PATH since REFINEMENTS #38, so a wipe
    changes which trades get taken until it refills; confluence_state is alert
    dedupe, whose 'regeneration' is re-firing every ping it had already sent;
    alert_history is the permanent ALERTS log; universe_cache/asx.json is
    frozen because the ASX directory fetch is dead, so a refetch returns
    nothing at all.
    """
    for rel in (
        "data/sector_history.json",
        "data/sector_map.json",
        "public/data/sector_map.json",
        "journal/confluence_state.json",
        "public/data/phasemap/alert_history.json",
        "data/universe_cache/asx.json",
    ):
        assert rel in bj.BACKUP_FILES, f"{rel} dropped out of BACKUP_FILES"


def test_the_unassigned_book_is_backed_up_but_never_required():
    """It is written only when a row has no market, so it is normally ABSENT.

    Promoting it to REQUIRED_FILES looks like tidying and would turn the
    nightly job into a permanent failure email about a file that is missing
    precisely because nothing has gone wrong.
    """
    rel = "journal/vivek_bot_book.unassigned.json"
    assert rel in bj.BACKUP_FILES
    assert rel not in bj.REQUIRED_FILES


def test_the_track_record_itself_is_required():
    """The per-market book files ARE the track record (layout v2). If this list
    ever stops naming them, #50 has been undone."""
    for m in ("asx", "nasdaq", "crypto"):
        assert f"journal/vivek_bot_book.{m}.json" in bj.REQUIRED_FILES


@pytest.mark.parametrize("rel", bj.REQUIRED_FILES)
def test_every_required_file_exists_in_the_tree(rel):
    """The other failure mode, and the one backup() is silent about: a source
    file gone from the tree. It prints 'skip (not found)' and carries on, so a
    deleted book reads as a successful backup. Every one of these is committed,
    so this fails in CI the moment one is removed — 24 hours before the backup
    would have noticed, and without needing the backup to run at all."""
    assert (_ROOT / rel).exists(), f"required state file missing from the tree: {rel}"


# --------------------------------------------------------------------------
# verify()
# --------------------------------------------------------------------------

def _tree(tmp_path):
    """A synthetic ROOT carrying every BACKUP_FILES path, plus a backups/ dir."""
    root = tmp_path / "repo"
    for rel in bj.BACKUP_FILES:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('{"ok": 1}' if rel.endswith(".json") else "# config\n")
    return root


@pytest.fixture
def live(tmp_path, monkeypatch):
    root = _tree(tmp_path)
    monkeypatch.setattr(bj, "ROOT", root)
    monkeypatch.setattr(bj, "BACKUP_DIR", root / "backups")
    return root


def test_a_real_backup_of_a_complete_tree_verifies(live, capsys):
    """The round-trip, and the strongest of these tests: it proves BACKUP_FILES
    actually COPIES everything REQUIRED_FILES demands, rather than merely
    listing it. The subset assertion above can be satisfied by two lists that
    agree with each other and disagree with backup()."""
    bj.backup()
    assert bj.verify() == 0


def test_verify_fails_when_a_required_file_is_missing(live):
    """The exact bug #50 found, reproduced: a required path never reaches the
    snapshot. Before this gate the run was green and the loss surfaced at
    restore time."""
    dest = bj.backup()
    (dest / "data" / "sector_history.json").unlink()
    assert bj.verify() == 1


def test_verify_fails_on_a_zero_byte_file(live):
    """Worse than missing: restore() would copy it over the live file, so an
    empty snapshot is an active hazard rather than a gap."""
    dest = bj.backup()
    (dest / "journal" / "vivek_bot_book.asx.json").write_text("")
    assert bj.verify() == 1


def test_verify_fails_on_unparseable_json(live):
    """The copy is byte-identical to the source, so this reaches back past the
    backup and reports a corrupt LIVE file. The nightly run is the only job
    that opens all of this state every day."""
    dest = bj.backup()
    (dest / "journal" / "vivek_bot_book.json").write_text("{not json")
    assert bj.verify() == 1


def test_a_non_json_required_file_is_not_json_checked(live):
    """scanner/config.py is required and is Python. The parse check must be
    scoped by extension or the gate fails every night on a valid file."""
    dest = bj.backup()
    (dest / "scanner" / "config.py").write_text("VIVEK_BOT_MAX_OPEN_TOTAL = 30\n")
    assert bj.verify() == 0


def test_verify_reports_failure_when_there_are_no_backups_at_all(live):
    assert bj.verify() == 1


def test_verify_defaults_to_the_newest_snapshot_not_a_stray_directory(live):
    """`backups/` can hold hand-made dirs. Picking one as 'the newest backup'
    would verify a directory nothing wrote and pass or fail meaninglessly."""
    good = bj.backup()
    stray = bj.BACKUP_DIR / "zzz-notes"          # sorts AFTER any timestamp
    stray.mkdir()
    assert bj.verify() == 0                       # ignored the stray
    (good / "journal" / "journal.json").unlink()
    assert bj.verify() == 1                       # and really read `good`


def test_verify_accepts_an_explicit_path(live):
    dest = bj.backup()
    assert bj.verify(str(dest)) == 0
    assert bj.verify(dest.name) == 0               # resolved under backups/


def test_verify_rejects_a_path_that_is_not_a_backup(live, tmp_path):
    assert bj.verify(str(tmp_path / "nowhere")) == 1


def test_a_backup_of_a_tree_missing_a_required_source_is_caught(live):
    """backup() only prints 'skip (not found)' for a file gone from the tree.
    verify() is what makes that visible in the same run."""
    (live / "journal" / "confluence_state.json").unlink()
    bj.backup()
    assert bj.verify() == 1


def test_the_manifest_is_not_what_verify_trusts(live):
    """A manifest records what backup() BELIEVES it copied. Checking the files
    on disk is strictly stronger, and the difference matters exactly when the
    two disagree."""
    dest = bj.backup()
    manifest = json.loads((dest / "manifest.json").read_text())
    assert "data/sector_history.json" in manifest["files"]
    (dest / "data" / "sector_history.json").unlink()   # manifest still claims it
    assert bj.verify() == 1
