"""Backup retention (2026-07-20, Phase 2): backups/ was unbounded."""

import importlib.util
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "backup_journal",
    pathlib.Path(__file__).resolve().parents[1] / "scripts" / "backup_journal.py")
bj = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bj)


def _mk(tmp_path, names):
    for n in names:
        d = tmp_path / n
        d.mkdir()
        (d / "manifest.json").write_text("{}")


def test_prune_keeps_newest_n(tmp_path, monkeypatch):
    monkeypatch.setattr(bj, "BACKUP_DIR", tmp_path)
    names = [f"2026-06-{d:02d}T21-35-00" for d in range(1, 31)] \
          + [f"2026-07-{d:02d}T21-35-00" for d in range(1, 6)]      # 35 total
    _mk(tmp_path, names)
    removed = bj.prune(keep=30)
    assert removed == 5
    left = sorted(p.name for p in tmp_path.iterdir())
    assert len(left) == 30
    assert left[0] == "2026-06-06T21-35-00"        # oldest five gone
    assert left[-1] == "2026-07-05T21-35-00"       # newest kept


def test_prune_ignores_non_timestamp_dirs_and_small_sets(tmp_path, monkeypatch):
    monkeypatch.setattr(bj, "BACKUP_DIR", tmp_path)
    _mk(tmp_path, ["2026-07-01T21-35-00", "2026-07-02T21-35-00"])
    (tmp_path / "notes").mkdir()                   # non-timestamp dir
    assert bj.prune(keep=30) == 0                  # under the cap: nothing pruned
    assert (tmp_path / "notes").exists()
    assert bj.prune(keep=1) == 1                   # cap 1 -> oldest dated dir goes
    assert (tmp_path / "notes").exists()           # never touched
    assert (tmp_path / "2026-07-02T21-35-00").exists()


def test_prune_handles_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(bj, "BACKUP_DIR", tmp_path / "nope")
    assert bj.prune() == 0
