#!/usr/bin/env bash
# deploy/bin/gc.sh -- weekly `git gc` of BOTH clones (deploy/DESIGN.md 4).
#
# gc.auto is 0 on the box (install.sh), because an automatic repack of a
# multi-GB pack triggered by an ordinary data commit would run on a 1-2 vCPU
# box while a job holds the book lock. This timer does it on Sunday 03:00 UTC
# under the EXCLUSIVE repo lock (the same file every job holds SHARED, and
# update.sh takes exclusive), single-threaded so it never starves a scan that
# starts while it runs. Non-blocking: a busy repo means "skip, try next week".
set -euo pipefail

vivek_home="${VIVEK_HOME:-/opt/vivek5/app}"
publish="${VIVEK_PUBLISH:-/opt/vivek5/publish}"
state_dir="${VIVEK_STATE_DIR:-/opt/vivek5/state}"
ledger="${VIVEK_RUNS_LEDGER:-$state_dir/runs.json}"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

ledger_row() {  # <status> <exit-code> <one line>
  python3 - "$ledger" "gc" "$1" "$2" "$3" "$started" "$(dirname "$ledger")/locks/ledger.lock" <<'PY' || true
import datetime as dt, fcntl, json, os, sys, tempfile
path, key, status, code, line, started, lockf = sys.argv[1:8]
now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
os.makedirs(os.path.dirname(lockf) or ".", exist_ok=True)
with open(lockf, "a+") as lk:
    fcntl.flock(lk, fcntl.LOCK_EX)
    try:
        with open(path) as fh:
            book = json.load(fh)
        if not isinstance(book, dict):
            book = {}
    except (OSError, ValueError):
        book = {}
    row = dict(book.get(key) or {})
    row.update({"last_start": started, "last_end": now, "last_status": status,
                "last_exit": int(code), "last_args": {}, "last_line": line[:300],
                "host": "vps"})
    if status == "ok":
        row["last_success_at"] = now
        row["consecutive_failures"] = 0
    elif status == "skipped":
        row["last_skip_at"] = now
    else:
        row["last_failure_at"] = now
        row["consecutive_failures"] = int(row.get("consecutive_failures") or 0) + 1
    book[key] = row
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".runs.", suffix=".tmp")
    with os.fdopen(fd, "w") as fh:
        json.dump(book, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)
PY
}

mkdir -p "$state_dir/locks"
exec 9>"$state_dir/locks/repo.lock"
if ! flock -x -n 9; then
  echo "gc: a job holds the repo lock - skipping this week"
  ledger_row skipped 0 "skipped busy"
  exit 0
fi

rc=0
for clone in "$vivek_home" "$publish"; do
  if [ ! -d "$clone/.git" ]; then
    echo "gc: $clone is not a git clone - skipped"
    continue
  fi
  echo "gc: $clone"
  if ! git -C "$clone" -c pack.threads=1 gc --prune=2.weeks.ago; then
    echo "gc: FAILED in $clone"
    rc=1
  fi
done

# State hygiene: the runner leaves one summary file per run in state/summaries
# (GITHUB_STEP_SUMMARY parity) and drain-spool parks every dispatch in
# spool/done or spool/failed; nothing else removes them. Keep 30 days -- long
# enough to read back why a run went red, short enough that a 48-scan/day
# crypto cadence never fills the disk the watchdog's disk_low probe guards.
for d in "$state_dir/summaries" "$state_dir/spool/done" "$state_dir/spool/failed"; do
  if [ -d "$d" ]; then
    find "$d" -type f -mtime +30 -delete 2>/dev/null || echo "gc: could not prune $d (non-fatal)"
  fi
done

if [ "$rc" -eq 0 ]; then
  ledger_row ok 0 "gc ok (both clones)"
else
  ledger_row failed "$rc" "git gc failed - see journal"
fi
exit "$rc"
