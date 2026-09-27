#!/usr/bin/env bash
# deploy/bin/gc.sh -- weekly `git gc` of BOTH clones (deploy/DESIGN.md 4).
#
# gc.auto is 0 on the box (install.sh), because an automatic repack of a
# multi-GB pack triggered by an ordinary data commit would run on a 1-2 vCPU
# box while a job holds the book lock. This timer does it on Sunday 03:00 UTC,
# single-threaded with a bounded delta window, from a unit that yields CPU,
# I/O and memory to the owner's live trading bot (M6 C8).
#
# LOCKS -- gc must never stall a JOB (2026-09-27 ops review): it used to hold
# the repo lock EXCLUSIVE for the whole multi-GB repack, and every job takes
# that lock SHARED with a bounded wait -- the kill switch (every 30 min, 10-min
# budget) failed with a lock timeout, a CRITICAL page, every Sunday a repack
# ran long. Now:
#   * repo lock SHARED (waits up to $repo_wait s): compatible with every running job;
#     it still excludes update.sh and accept-upstream/clear-halt, the only
#     things that move the working checkout's HEAD/index. A concurrent
#     momentum-gate fetch is safe beside a gc (its objects are younger than
#     --prune; a pack written during the repack is kept).
#   * the publish clone additionally under the `publish` lock EXCLUSIVE (the
#     lock every publish takes, with a 10-min budget), and its gc is BOUNDED
#     (timeout, $pub_bound s) so a publish queued behind it never times out; a
#     gc killed by the bound leaves only temporary packs the next gc removes.
#   * busy (update.sh / an operator verb holds repo EXCLUSIVE) -> skip, retry
#     next week; ledger `skipped`.
set -euo pipefail

vivek_home="${VIVEK_HOME:-/opt/vivek5/app}"
publish="${VIVEK_PUBLISH:-/opt/vivek5/publish}"
state_dir="${VIVEK_STATE_DIR:-/opt/vivek5/state}"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# Lock waits and the publish-clone bound, in seconds. The defaults are the
# design (the env names exist so the tests can exercise the busy paths without
# waiting minutes; nothing on the box sets them). pub_wait + pub_bound stay
# under the 600 s every publish waits for the publish lock
# (config.VPS_LOCK_WAIT_S["default"]), so a publish queued behind gc never
# times out.
repo_wait="${VIVEK_GC_REPO_WAIT_S:-60}"
pub_wait="${VIVEK_GC_PUBLISH_WAIT_S:-150}"
pub_bound="${VIVEK_GC_PUBLISH_BOUND_S:-420}"

py="${VIVEK_VENV:-/opt/vivek5/venv}/bin/python"
[ -x "$py" ] || py="$(command -v python3)"
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"

ledger_row() {  # <status> <exit-code> <one line>  -- the runner's own writer (M3)
  ( cd "$repo_root" && "$py" -m scanner.vps ledger-note --started "$started" gc "$1" "$2" "$3" ) || true
}

mkdir -p "$state_dir/locks"
exec 9>"$state_dir/locks/repo.lock"
if ! flock -s -w "$repo_wait" 9; then
  echo "gc: the repo lock is held EXCLUSIVE (update.sh or an operator verb) - skipping this week"
  ledger_row skipped 0 "skipped busy"
  exit 0
fi

gc_clone() {  # <clone> [timeout-seconds]
  local cmd=(git -C "$1" -c pack.threads=1 -c pack.windowMemory=256m gc --prune=2.weeks.ago)
  if [ -n "${2:-}" ]; then timeout "$2" "${cmd[@]}"; else "${cmd[@]}"; fi
}

rc=0
notes=""
if [ -d "$vivek_home/.git" ]; then
  echo "gc: $vivek_home (working checkout, repo lock shared)"
  if ! gc_clone "$vivek_home"; then echo "gc: FAILED in $vivek_home"; rc=1; notes="$notes app-failed"; fi
else
  echo "gc: $vivek_home is not a git clone - skipped"
fi

if [ -d "$publish/.git" ]; then
  exec 8>"$state_dir/locks/publish.lock"
  if flock -x -w "$pub_wait" 8; then
    echo "gc: $publish (publish clone, publish lock exclusive, bounded at ${pub_bound}s)"
    prc=0
    gc_clone "$publish" "$pub_bound" || prc=$?
    flock -u 8
    if [ "$prc" -eq 124 ]; then
      echo "gc: the publish clone's gc hit its ${pub_bound}s bound (killed; only temporary packs are left) - run it by hand at a quiet time: sudo -u vivek5 git -C $publish gc"
      rc=1; notes="$notes publish-timed-out"
    elif [ "$prc" -ne 0 ]; then
      echo "gc: FAILED in $publish"; rc=1; notes="$notes publish-failed"
    fi
  else
    echo "gc: a publish holds the publish lock - the publish clone is skipped this week"
    notes="$notes publish-skipped-busy"
  fi
  exec 8>&-
else
  echo "gc: $publish is not a git clone - skipped"
fi

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
  ledger_row ok 0 "gc ok${notes:+ (${notes# })}"
else
  ledger_row failed "$rc" "git gc failed (${notes# }) - see journal"
fi
exit "$rc"
