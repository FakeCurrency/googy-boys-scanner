#!/usr/bin/env python3
"""Operational auto-recovery script — Phase 7 Operational Automation.

Cleans up stale state that accumulates across GitHub Actions runs so the
live-execution loop stays healthy without manual intervention.

Actions performed:
  1. expire_acks       — purge alert acknowledgments whose window has passed
  2. ensure_dirs       — create any missing runtime directories (journal/, public/data/)
  3. validate_journals — warn if journal JSON files are missing or malformed
  4. rotate_logs       — if --rotate-logs flag set, truncate log files that exceed
                         the HEALTH_LOG_SIZE_CRIT_MB threshold (keeps the last 25%)

Usage:
  python scripts/auto_recover.py            # normal run (all safe actions)
  python scripts/auto_recover.py --dry-run  # show what would happen, do nothing
  python scripts/auto_recover.py --rotate-logs  # also rotate oversized logs

Exit codes:
  0  all recovery actions succeeded
  1  one or more actions failed (see output)
"""

import argparse
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner import config as _cfg

_REQUIRED_DIRS = [
    ROOT / "journal",
    ROOT / "public" / "data",
]

_JOURNAL_FILES = {
    "scalp_journal": ROOT / "journal" / "scalp_journal.json",
    "journal":       ROOT / "journal" / "journal.json",
}

_LOG_FILES = [
    ROOT / "journal" / "bybit_run.log",
    ROOT / "journal" / "scan.log",
    ROOT / "journal" / "paper_run.log",
]

_STATE_FILE = ROOT / "journal" / "alert_state.json"


# ── helpers ───────────────────────────────────────────────────────────────────

def _log(msg: str, dry: bool = False) -> None:
    prefix = "[DRY-RUN] " if dry else ""
    print(f"{prefix}{msg}")


# ── individual recovery actions ───────────────────────────────────────────────

def expire_acks(dry: bool = False) -> list[str]:
    """Remove alert acknowledgments whose expiry time has passed."""
    actions: list[str] = []
    if not _STATE_FILE.exists():
        return actions

    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        actions.append(f"WARN: could not read alert_state.json: {e}")
        return actions

    acks  = data.get("acknowledged", {})
    now   = dt.datetime.now(dt.timezone.utc)
    stale = []
    for event_type, ack_until_raw in list(acks.items()):
        try:
            ack_until = dt.datetime.fromisoformat(ack_until_raw)
            if now >= ack_until:
                stale.append(event_type)
        except Exception:
            stale.append(event_type)

    for event_type in stale:
        actions.append(f"expire_acks: removed expired acknowledgment for '{event_type}'")
        if not dry:
            del acks[event_type]

    if stale and not dry:
        data["acknowledged"] = acks
        try:
            from scanner.scalp_journal import _atomic_write
            _atomic_write(_STATE_FILE, json.dumps(data, indent=2))
        except Exception as e:
            actions.append(f"WARN: could not save alert_state.json: {e}")

    if not stale:
        actions.append("expire_acks: no expired acknowledgments")

    return actions


def ensure_dirs(dry: bool = False) -> list[str]:
    """Create any required runtime directories that are missing."""
    actions: list[str] = []
    for d in _REQUIRED_DIRS:
        if d.exists():
            actions.append(f"ensure_dirs: {d.relative_to(ROOT)} — OK")
        else:
            actions.append(f"ensure_dirs: creating missing directory {d.relative_to(ROOT)}")
            if not dry:
                d.mkdir(parents=True, exist_ok=True)
    return actions


def validate_journals(dry: bool = False) -> list[str]:
    """Warn if any journal file is absent or malformed (no repair, only report)."""
    actions: list[str] = []
    for name, path in _JOURNAL_FILES.items():
        if not path.exists():
            actions.append(f"validate_journals: {name} not found (first run?)")
            continue
        try:
            j = json.loads(path.read_text(encoding="utf-8"))
            open_n   = len(j.get("open",   []))
            closed_n = len(j.get("closed", []))
            actions.append(f"validate_journals: {name} OK — {open_n} open, {closed_n} closed")
        except Exception as e:
            actions.append(f"validate_journals: {name} is malformed — {e}")
    return actions


def rotate_logs(dry: bool = False) -> list[str]:
    """Truncate log files that exceed HEALTH_LOG_SIZE_CRIT_MB, keeping the last 25%."""
    actions: list[str] = []
    limit_mb = float(getattr(_cfg, "HEALTH_LOG_SIZE_CRIT_MB", 200))
    keep_frac = 0.25

    for lf in _LOG_FILES:
        if not lf.exists():
            continue
        mb = lf.stat().st_size / 1_048_576
        if mb <= limit_mb:
            actions.append(f"rotate_logs: {lf.name} ({mb:.1f} MB) — within limit")
            continue

        keep_bytes = int(lf.stat().st_size * keep_frac)
        actions.append(
            f"rotate_logs: {lf.name} ({mb:.1f} MB > {limit_mb:.0f} MB limit)"
            f" — truncating to last {keep_frac:.0%}"
        )
        if not dry:
            try:
                content = lf.read_bytes()
                tail    = content[-keep_bytes:]
                header  = (
                    f"[auto_recover: log rotated at {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')} "
                    f"({mb:.1f} MB → kept last {keep_frac:.0%})]\n"
                ).encode()
                lf.write_bytes(header + tail)
            except Exception as e:
                actions.append(f"rotate_logs: WARN: could not rotate {lf.name}: {e}")

    return actions


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Vivek's Beta Scanner — operational auto-recovery")
    ap.add_argument("--dry-run",     action="store_true", help="Report actions without executing")
    ap.add_argument("--rotate-logs", action="store_true", help="Also rotate oversized log files")
    args = ap.parse_args()

    dry   = args.dry_run
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    print(f"\n=== Vivek's Beta Scanner — Auto-Recovery  {stamp} ===")
    if dry:
        print("(dry-run mode — no changes will be made)\n")
    else:
        print()

    all_actions: list[str] = []
    all_actions += expire_acks(dry)
    all_actions += ensure_dirs(dry)
    all_actions += validate_journals(dry)
    if args.rotate_logs:
        all_actions += rotate_logs(dry)

    errors = [a for a in all_actions if "WARN" in a or "malformed" in a]
    for action in all_actions:
        _log(f"  {action}", dry=False)

    print()
    if errors:
        print(f"Recovery complete — {len(errors)} warning(s) require attention.")
        return 1
    else:
        print("Recovery complete — all checks passed.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
