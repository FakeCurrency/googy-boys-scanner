"""Backup completeness (TOP100 #50, 2026-07-28).

`backup_book.yml`'s only gate was `assert_staged.sh "book backup" backups`,
which proves a DIRECTORY appeared. It could not see what was in it, so the
three files this item found missing from `BACKUP_FILES` — sector_history
(gone with HORIZON on 2026-09-20), sector_map, confluence_state — had never
been snapshotted and the nightly run had been green about it every night
regardless.

The tests below are mostly about the two ways that stays fixed: the required
list cannot drift away from the backed-up list, and `verify()` actually bites
on each of the three ways a file in a finished backup can be useless.
"""

import datetime as _dt
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest
import yaml

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
    sector_map is a SIGNAL PATH since REFINEMENTS #38, so a wipe
    changes which trades get taken until it refills; confluence_state is alert
    dedupe, whose 'regeneration' is re-firing every ping it had already sent;
    alert_history is the permanent ALERTS log; universe_cache/asx.json is
    frozen because the ASX directory fetch is dead, so a refetch returns
    nothing at all.
    """
    for rel in (
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
    (dest / "data" / "sector_map.json").unlink()
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
    assert "data/sector_map.json" in manifest["files"]
    (dest / "data" / "sector_map.json").unlink()   # manifest still claims it
    assert bj.verify() == 1


# --------------------------------------------------------------------------
# the backstop cron's freshness gate (backup_book.yml), EXECUTED
# --------------------------------------------------------------------------
# The gate is shell inside the workflow, so these tests slice the SHIPPED
# `run:` block out of the YAML and run it in bash against a temp backups/ dir,
# with the clock faked by a `date` shim on PATH: a call without -d/--date gets
# `-d @$FAKE_NOW` prepended, so every reading of "now" is the test's.
#
# Why (2026-10-05 audit): the gate used to match the UTC CALENDAR date
# (`grep "^$(date -u +%Y-%m-%d)T"`). Both crons fire hours late, so the 21:35
# primary now lands after 00:00Z, and that match read the previous cycle's
# snapshot as tonight's: a dropped primary with an on-time backstop would have
# skipped and left a ~48h hole (watchdog backup_stale is 26h). And a primary
# landing BEFORE midnight was invisible to a backstop after it, so every night
# 09-05..09-28 took two snapshots.

_WF_DOC = yaml.safe_load(
    (_ROOT / ".github" / "workflows" / "backup_book.yml").read_text(encoding="utf-8"))
_GATE = next(s for s in _WF_DOC["jobs"]["backup"]["steps"]
             if s.get("name") == "Backstop freshness gate")
_CRONS = [c["cron"] for c in (_WF_DOC.get("on") or _WF_DOC[True])["schedule"]]
PRIMARY, BACKSTOP = "35 21 * * *", "35 23 * * *"
_SHELLS = [("bash", "-e"), ("bash", "-eo", "pipefail")]   # GitHub's default; and stricter


def _epoch(when: _dt.datetime) -> int:
    return int(when.replace(tzinfo=_dt.timezone.utc).timestamp())


def _utc(stamp: str) -> _dt.datetime:
    return _dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")


def _shim(tmp_path) -> pathlib.Path:
    d = tmp_path / "shimbin"
    if not d.exists():
        d.mkdir()
        real = shutil.which("date")
        (d / "date").write_text(
            "#!/bin/bash\n"
            'for a in "$@"; do case "$a" in -d|-d*|--date|--date=*) '
            f'exec {real} "$@";; esac; done\n'
            f'exec {real} -d "@$FAKE_NOW" "$@"\n')
        (d / "date").chmod(0o755)
    return d


def _env(tmp_path, now: _dt.datetime, **extra) -> dict:
    return {**os.environ, **extra,
            "PATH": f"{_shim(tmp_path)}{os.pathsep}{os.environ['PATH']}",
            "FAKE_NOW": str(_epoch(now))}


def _run_gate(tmp_path, now: str, snapshots=(), schedule=BACKSTOP,
              shell=_SHELLS[0], make_dir=True) -> str:
    """Run the shipped gate in a fresh checkout dir; return its `run` value."""
    work = pathlib.Path(tempfile.mkdtemp(dir=tmp_path))
    if make_dir:
        (work / "backups").mkdir()
        for name in snapshots:
            (work / "backups" / name).mkdir()
    (work / "gate.sh").write_text(_GATE["run"])
    out = work / "github_output"
    out.write_text("")
    p = subprocess.run(
        [*shell, "gate.sh"], cwd=work, capture_output=True, text=True,
        env=_env(tmp_path, _utc(now), SCHEDULE=schedule, GITHUB_OUTPUT=str(out)))
    assert p.returncode == 0, f"the gate must never fail the job:\n{p.stderr}"
    runs = re.findall(r"^run=(\w+)$", out.read_text(), re.M)
    assert len(runs) == 1, f"exactly one run= line expected, got {runs}"
    return runs[0]


def test_the_shim_really_fakes_the_clock(tmp_path):
    """Every verdict below depends on this; without it they test today."""
    p = subprocess.run(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], capture_output=True,
                       text=True, check=True,
                       env=_env(tmp_path, _utc("2020-01-02T03:04:05Z")))
    assert p.stdout.strip() == "2020-01-02T03:04:05Z"


def test_the_gate_keys_on_the_backstop_cron_it_is_written_for():
    assert _GATE["env"]["SCHEDULE"] == "${{ github.event.schedule }}"
    assert PRIMARY in _CRONS and BACKSTOP in _CRONS
    assert f'"$SCHEDULE" = "{BACKSTOP}"' in _GATE["run"]


def test_the_slot_hour_is_the_primary_crons_hour():
    """SLOT_H ties the gate to the 21:35 cron. Move the cron without it and
    the gate measures a slot nothing fires in."""
    m = re.search(r"^SLOT_H=(\d+)", _GATE["run"], re.M)
    assert m, "the gate lost its SLOT_H"
    assert m.group(1) == PRIMARY.split()[1]


@pytest.mark.parametrize("shell", _SHELLS)
def test_a_primary_that_landed_after_utc_midnight_satisfies_the_backstop(tmp_path, shell):
    """The live pattern since 09-29: Oct 4's 21:35 ran at 00:07Z on Oct 5 and
    the backstop at 02:20Z. One snapshot for the cycle, not two."""
    assert _run_gate(tmp_path, "2026-10-05T02:20:08Z",
                     ["2026-10-04T00-00-10", "2026-10-05T00-07-02"],
                     shell=shell) == "false"


@pytest.mark.parametrize("shell", _SHELLS)
def test_a_primary_before_midnight_satisfies_a_backstop_after_it(tmp_path, shell):
    """09-05..09-28: primary 23:47Z, backstop 01:39Z the next UTC day. The
    calendar match missed it and took a second snapshot every night."""
    assert _run_gate(tmp_path, "2026-09-17T01:39:36Z",
                     ["2026-09-16T01-36-34", "2026-09-16T23-47-15"],
                     shell=shell) == "false"


@pytest.mark.parametrize("shell", _SHELLS)
def test_only_the_previous_cycles_snapshot_means_the_backstop_runs(tmp_path, shell):
    """The hole: Oct 5's 21:35 dropped, the backstop on time at 23:35Z. The
    newest snapshot (00:07Z the same UTC day) is Oct 4's slot, so tonight has
    none - run. The calendar match skipped here."""
    assert _run_gate(tmp_path, "2026-10-05T23:35:00Z",
                     ["2026-10-04T00-00-10", "2026-10-05T00-07-02"],
                     shell=shell) == "true"


def test_a_late_backstop_after_a_dropped_primary_runs(tmp_path):
    """Same drop, the backstop landing after midnight (its usual lateness)."""
    assert _run_gate(tmp_path, "2026-10-06T02:20:00Z",
                     ["2026-10-04T00-00-10", "2026-10-05T00-07-02"]) == "true"


def test_the_slot_boundary_is_inclusive(tmp_path):
    assert _run_gate(tmp_path, "2026-10-05T23:35:00Z",
                     ["2026-10-05T21-00-00"]) == "false"
    assert _run_gate(tmp_path, "2026-10-05T23:35:00Z",
                     ["2026-10-05T20-59-59"]) == "true"


@pytest.mark.parametrize("shell", _SHELLS)
def test_fail_open_without_a_backups_dir(tmp_path, shell):
    """An absent/unreadable dir reads as no snapshot and must not abort the
    step, even under pipefail (ls exits 2, grep exits 1)."""
    assert _run_gate(tmp_path, "2026-10-05T23:35:00Z", make_dir=False,
                     shell=shell) == "true"
    assert _run_gate(tmp_path, "2026-10-05T23:35:00Z", shell=shell) == "true"


def test_stray_entries_are_not_snapshots(tmp_path):
    """Only fixed-width stamp dirs count - the rule _dated_dirs() applies."""
    assert _run_gate(tmp_path, "2026-10-05T23:35:00Z",
                     ["README", "2026-10-05T23-00-00-hand-made",
                      "2026-10-04T00-00-10"]) == "true"


@pytest.mark.parametrize("schedule", [PRIMARY, ""])
def test_the_gate_never_holds_back_the_primary_or_a_manual_run(tmp_path, schedule):
    assert _run_gate(tmp_path, "2026-10-05T23:35:00Z", ["2026-10-05T22-00-00"],
                     schedule=schedule) == "true"


def test_the_gate_recognises_what_backup_journal_actually_writes(live, tmp_path):
    """The names come from backup_journal._ts(). With the clock set to the
    snapshot's own instant it is at/after the latest slot by definition, so a
    format drift between the writer and the gate's filter fails here instead
    of making every backstop run."""
    dest = bj.backup()
    taken = _dt.datetime.strptime(dest.name, "%Y-%m-%dT%H-%M-%S")
    assert _run_gate(tmp_path, taken.strftime("%Y-%m-%dT%H:%M:%SZ"),
                     [dest.name]) == "false"
