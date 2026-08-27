#!/usr/bin/env python3
"""Backup and restore journal state, config, and public data (Phase 5 — 5.4).

Usage:
  python scripts/backup_journal.py backup           # create timestamped backup
  python scripts/backup_journal.py verify [<path>]  # check the newest is complete
  python scripts/backup_journal.py restore <path>   # restore from a backup directory
  python scripts/backup_journal.py list             # list available backups

Backup directory: backups/YYYY-MM-DDTHH-MM-SS/
Files backed up (2026-07-21 — trimmed to the LIVE state set; the scalp-era
public/data files were retired and deleted, see git history):
  journal/vivek_bot_book*.json  (canonical per-market books = THE track record)
  journal/journal.json + journal/scalp_journal.json  (frozen legacy history)
  journal/*.log  (last 50k lines each)
  public/data/vivek_bot_book.json + events.json
  scanner/config.py
  (2026-07-28, TOP100 #50) accumulated state: data/sector_history.json,
  data/sector_map.json + its public twin, journal/confluence_state.json,
  public/data/phasemap/alert_history.json, data/universe_cache/*.json —
  see the comment on BACKUP_FILES for why each one cannot be recomputed.

REQUIRED_FILES is the subset `verify` insists on. It is what turns "a backup
directory appeared" into "the backup contains the track record", which is the
only version of the question worth asking.

Restore:
  Overwrites the live files from the backup directory after confirmation.
  Does NOT restore *.log files (logs are append-only, no restore needed).
"""

import argparse
import json
import pathlib
import shutil
import sys
from datetime import datetime, timezone

ROOT       = pathlib.Path(__file__).resolve().parents[1]
BACKUP_DIR = ROOT / "backups"

BACKUP_FILES = [
    # THE track record (2026-07-20, review C2 + Phase 3 layout v2): the
    # CANONICAL per-market book files come first — they are the record.
    # The combined file + public twin are derived views (kept for
    # convenience; regenerable via vivek_run --rebuild-combined).
    "journal/vivek_bot_book.asx.json",
    "journal/vivek_bot_book.nasdaq.json",
    "journal/vivek_bot_book.crypto.json",
    "journal/vivek_bot_book.unassigned.json",
    "journal/vivek_bot_book.json",
    "public/data/vivek_bot_book.json",
    "journal/journal.json",
    "journal/scalp_journal.json",
    # (2026-07-21: the retired scalp-era public/data files — asx/nasdaq
    #  pullback/reversal/short scans, scalp*.json, health.json,
    #  performance.json — were deleted from public/data; entries dropped.
    #  _copy() skips missing files, so old backups still restore cleanly.)
    "public/data/events.json",
    "scanner/config.py",
    # TOP100 #50 (2026-07-28) - state that ACCUMULATES and was never snapshotted.
    # The inclusion rule: back a file up when losing it loses information that
    # cannot be recomputed from what remains. Every entry below fails that test
    # in a different way.
    #
    #   data/sector_history.json      the ONLY long sector memory in the system
    #                                 (the PhaseMap archive is 7 days). One row
    #                                 per market per day; the pre-2026-06-28
    #                                 rows exist solely because a ~25-minute
    #                                 backfill replayed the engine to make them,
    #                                 and `held` is null there because it is
    #                                 genuinely unknowable. It also carries the
    #                                 sector_run ping memory, so losing it
    #                                 re-fires the sector-run alarm for every
    #                                 sector mid-run.
    #   data/sector_map.json          a SIGNAL PATH since REFINEMENTS #38 - it
    #   public/data/sector_map.json   decides which rows the 3-per-sector cap
    #                                 can see, so a wipe changes which trades
    #                                 get taken until it refills. It accretes
    #                                 across scans (seeded from the open book)
    #                                 and no single run rebuilds it. The public
    #                                 twin travels with it for the same reason
    #                                 the book's twin does: a restore that puts
    #                                 back only the canonical file leaves the
    #                                 dashboard disagreeing with the engine.
    #   journal/confluence_state.json alert dedupe. Regenerable in the sense
    #                                 that the next scan writes one - by
    #                                 re-firing every ping it had already sent.
    #   public/data/phasemap/alert_history.json
    #                                 the permanent ALERTS-page log, append-only
    #                                 and 139KB of it. Nothing reconstructs it.
    #   data/universe_cache/*.json    asx.json is effectively IRREPLACEABLE: the
    #                                 ASX directory fetch is dead, so the 2,212
    #                                 names in it are frozen and a refetch
    #                                 returns nothing. nasdaq/crypto would come
    #                                 back on the next fetch; they travel with
    #                                 asx because a half-restored roster dir is
    #                                 worse than a whole one.
    #
    # Deliberately OUT: public/data/regime.json and sector_breadth.json. A scan
    # recomputes both wholesale from bars, so a snapshot of them is a snapshot
    # of something the next run overwrites anyway.
    "data/sector_history.json",
    "data/sector_map.json",
    "public/data/sector_map.json",
    "journal/confluence_state.json",
    "public/data/phasemap/alert_history.json",
    "data/universe_cache/asx.json",
    "data/universe_cache/nasdaq.json",
    "data/universe_cache/crypto.json",
]

# The subset whose ABSENCE means the backup failed, checked by verify() after
# the snapshot is written (TOP100 #50). Two different bugs land here:
#   (a) a path quietly dropped from BACKUP_FILES - backup() then never copies
#       it, the run stays green, and the loss surfaces at restore time, which
#       is the one moment you cannot do anything about it;
#   (b) a source file that vanished from the TREE - backup() prints "skip (not
#       found)" and carries on, so a deleted book reads as a successful backup.
# `backup_book.yml` could see neither: its gate is
# `assert_staged.sh "book backup" backups`, which proves a DIRECTORY appeared.
# An empty directory would have passed it.
#
# Kept deliberately shorter than BACKUP_FILES. A required file that can
# legitimately be absent turns the nightly job into a recurring failure email
# about nothing, and a muted channel is how the original blackout happened:
#   - vivek_bot_book.unassigned.json is written only when a row has no market,
#     so it is normally absent and is NOT required (it is still backed up);
#   - events.json is small, published, and cheap to lose.
REQUIRED_FILES = [
    "journal/vivek_bot_book.asx.json",
    "journal/vivek_bot_book.nasdaq.json",
    "journal/vivek_bot_book.crypto.json",
    "journal/vivek_bot_book.json",
    "public/data/vivek_bot_book.json",
    "journal/journal.json",
    "journal/scalp_journal.json",
    "scanner/config.py",
    "data/sector_history.json",
    "data/sector_map.json",
    "public/data/sector_map.json",
    "journal/confluence_state.json",
    "public/data/phasemap/alert_history.json",
    "data/universe_cache/asx.json",
]

LOG_FILES = [
    "journal/bybit_run.log",
    "journal/scan.log",
    "journal/paper_run.log",
]
LOG_TAIL_LINES = 50_000

# Retention (2026-07-20): nightly snapshots are ~100KB each and were unbounded.
# Keep the newest N; backup() prunes older ones (the workflow stages deletions
# with `git add -A backups`). 30 dailies ≈ a month of restore points.
BACKUP_KEEP = 30


def _dated_dirs() -> list[pathlib.Path]:
    """Timestamped backup dirs, oldest first. Anything else under backups/ is
    ignored — prune() must never delete a hand-made directory, and verify()
    must never pick one as 'the newest backup'."""
    if not BACKUP_DIR.exists():
        return []
    return sorted(d for d in BACKUP_DIR.iterdir()
                  if d.is_dir() and len(d.name) == 19 and d.name[4] == "-")


def prune(keep: int = BACKUP_KEEP) -> int:
    """Delete all but the newest `keep` timestamped backup dirs. Returns count
    removed. Timestamp-format dirs only — anything else is left untouched."""
    if not BACKUP_DIR.exists() or keep <= 0:
        return 0
    dated = _dated_dirs()
    removed = 0
    for d in dated[:-keep] if len(dated) > keep else []:
        shutil.rmtree(d, ignore_errors=True)
        removed += 1
        print(f"  prune {d.name}")
    return removed


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")


def backup() -> pathlib.Path:
    ts      = _ts()
    dest    = BACKUP_DIR / ts
    dest.mkdir(parents=True, exist_ok=True)

    copied = []
    for rel in BACKUP_FILES:
        src = ROOT / rel
        if not src.exists():
            print(f"  skip  {rel}  (not found)")
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        copied.append(rel)
        print(f"  copy  {rel}")

    # Tail large log files (last N lines only)
    for rel in LOG_FILES:
        src = ROOT / rel
        if not src.exists():
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
        tail  = "\n".join(lines[-LOG_TAIL_LINES:])
        target.write_text(tail, encoding="utf-8")
        print(f"  tail  {rel}  ({min(len(lines), LOG_TAIL_LINES)} lines)")
        copied.append(rel)

    # Write a manifest
    manifest = {
        "created_at": ts,
        "files":      copied,
        "root":       str(ROOT),
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2))

    pruned = prune()
    if pruned:
        print(f"  pruned {pruned} old backup(s) (keep {BACKUP_KEEP})")
    print(f"\nBackup complete -> {dest}")
    return dest


def verify(backup_path: str | None = None) -> int:
    """Check a finished backup actually CONTAINS every REQUIRED_FILES entry.

    Returns 0 if the snapshot is complete, 1 otherwise (the caller exits with
    it). Defaults to the newest timestamped dir, which is the one the run that
    just finished wrote.

    Three questions, because a file can be useless in three ways:
      present?    - covers a path dropped from BACKUP_FILES and a source file
                    that vanished from the tree (backup() only prints "skip").
      non-empty?  - a 0-byte snapshot is WORSE than a missing one, because
                    restore() would happily copy it over the live file.
      parses?     - .json only. This is the half that reaches back past the
                    backup and checks the LIVE state set, since the copy is
                    byte-identical to the source: the nightly run is the only
                    job that touches all of these files every day, so it is the
                    only place a corrupt book gets noticed within 24 hours
                    rather than at restore time.
    """
    if backup_path:
        dest = pathlib.Path(backup_path)
        if not dest.exists():
            dest = BACKUP_DIR / backup_path
    else:
        dated = _dated_dirs()
        if not dated:
            print("VERIFY FAILED: no backups found under backups/", file=sys.stderr)
            return 1
        dest = dated[-1]

    if not dest.is_dir():
        print(f"VERIFY FAILED: not a backup directory: {dest}", file=sys.stderr)
        return 1

    problems = []
    for rel in REQUIRED_FILES:
        f = dest / rel
        if not f.exists():
            problems.append(f"{rel}  MISSING from the backup")
            continue
        if f.stat().st_size == 0:
            problems.append(f"{rel}  EMPTY (0 bytes)")
            continue
        if rel.endswith(".json"):
            try:
                json.loads(f.read_text(encoding="utf-8"))
            except Exception as e:
                problems.append(f"{rel}  UNPARSEABLE ({type(e).__name__}: {e})")

    print(f"Verifying {dest.name}: {len(REQUIRED_FILES)} required file(s)")
    if problems:
        print(f"\nVERIFY FAILED - {len(problems)} problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print(
            "\nA required file is one whose absence means the snapshot is not a\n"
            "restore point. Either it was dropped from BACKUP_FILES in\n"
            "scripts/backup_journal.py, or it is gone from the working tree.",
            file=sys.stderr,
        )
        return 1
    print("  all present, non-empty, and parseable.")
    return 0


def restore(backup_path: str) -> None:
    src_dir = pathlib.Path(backup_path)
    if not src_dir.exists():
        # Try relative to BACKUP_DIR
        src_dir = BACKUP_DIR / backup_path
    if not src_dir.exists():
        print(f"ERROR: backup directory not found: {backup_path}", file=sys.stderr)
        sys.exit(1)

    manifest_file = src_dir / "manifest.json"
    if not manifest_file.exists():
        print(f"ERROR: not a valid backup (no manifest.json)", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(manifest_file.read_text())
    print(f"Restoring backup from {manifest.get('created_at', '?')}")
    print(f"Files: {', '.join(manifest.get('files', []))}")
    print()
    answer = input("Type 'yes' to confirm restore (this overwrites live files): ").strip()
    if answer.lower() != "yes":
        print("Aborted.")
        return

    restored = []
    for rel in BACKUP_FILES:
        src = src_dir / rel
        if not src.exists():
            continue
        dest = ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        restored.append(rel)
        print(f"  restored  {rel}")

    print(f"\nRestored {len(restored)} files.")


def list_backups() -> None:
    if not BACKUP_DIR.exists():
        print("No backups directory found.")
        return
    backups = sorted(BACKUP_DIR.iterdir(), reverse=True)
    if not backups:
        print("No backups found.")
        return
    print(f"{'Backup':<26}  {'Files':>5}  {'Size':>8}")
    print("-" * 45)
    for b in backups:
        mf = b / "manifest.json"
        n_files = "?"
        if mf.exists():
            try:
                m      = json.loads(mf.read_text())
                n_files = len(m.get("files", []))
            except Exception:
                pass
        size = sum(f.stat().st_size for f in b.rglob("*") if f.is_file())
        print(f"{b.name:<26}  {str(n_files):>5}  {size/1024:>7.0f}K")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backup/restore journal and scan data")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("backup",  help="Create a timestamped backup")
    rp = sub.add_parser("restore", help="Restore from a backup")
    rp.add_argument("path", help="Backup directory name or path")
    sub.add_parser("list", help="List available backups")
    vp = sub.add_parser("verify", help="Check a backup contains every required file")
    vp.add_argument("path", nargs="?", default=None,
                    help="Backup dir (default: the newest)")
    args = ap.parse_args()

    if args.cmd == "backup":
        backup()
    elif args.cmd == "restore":
        restore(args.path)
    elif args.cmd == "list":
        list_backups()
    elif args.cmd == "verify":
        sys.exit(verify(args.path))
    else:
        ap.print_help()
