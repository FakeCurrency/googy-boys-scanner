#!/usr/bin/env python3
"""Backup and restore journal state, config, and public data (Phase 5 — 5.4).

Usage:
  python scripts/backup_journal.py backup           # create timestamped backup
  python scripts/backup_journal.py restore <path>   # restore from a backup directory
  python scripts/backup_journal.py list             # list available backups

Backup directory: backups/YYYY-MM-DDTHH-MM-SS/
Files backed up:
  journal/journal.json
  journal/scalp_journal.json
  journal/*.log  (last 50k lines each)
  public/data/*.json
  scanner/config.py

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
    "journal/journal.json",
    "journal/scalp_journal.json",
    "public/data/asx.json",
    "public/data/nasdaq.json",
    "public/data/asx_reversal.json",
    "public/data/asx_spec.json",
    "public/data/asx_short.json",
    "public/data/scalp.json",
    "public/data/scalp_crypto.json",
    "public/data/scalp_journal.json",
    "public/data/health.json",
    "public/data/performance.json",
    "public/data/events.json",
    "scanner/config.py",
]

LOG_FILES = [
    "journal/bybit_run.log",
    "journal/scan.log",
    "journal/paper_run.log",
]
LOG_TAIL_LINES = 50_000


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

    print(f"\nBackup complete → {dest}")
    return dest


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
    args = ap.parse_args()

    if args.cmd == "backup":
        backup()
    elif args.cmd == "restore":
        restore(args.path)
    elif args.cmd == "list":
        list_backups()
    else:
        ap.print_help()
