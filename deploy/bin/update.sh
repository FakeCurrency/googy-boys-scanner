#!/usr/bin/env bash
# deploy/bin/update.sh -- advance the WORKING checkout to origin/main.
# deploy/DESIGN.md 3.7, verbatim in intent:
#
#   * repo lock EXCLUSIVE, NON-BLOCKING (same file every RUNNING job holds
#     shared, $VIVEK_STATE_DIR/locks/repo.lock; a QUEUED job no longer holds
#     it). Busy -> ledger `update: skipped busy`. A busy lock while a vivek5-*
#     job unit is running is expected (that job's TimeoutStartSec is its own
#     hang detector) and does not count; only an UNEXPLAINED busy lock -- no
#     vivek5 job running, yet the lock is held -- counts, and after 12 of those
#     in a row (= 1 h at */5) this exits 1 so the OnFailure hook alerts.
#   * with the lock held, stale git lock files a killed git left in the
#     checkout (.git/index.lock, ref locks) are removed and named.
#   * HEAD == origin/main and no interrupted sync pending -> exit 0 (and says
#     so).
#   * SECOND-WRITER CHECK before touching anything: a commit since
#     state/publish_head that touches a DATA ROOT and is not ours (GIT_AUTHOR_
#     NAME + GIT_AUTHOR_EMAIL) writes state/HALT (json: shas, authors, paths),
#     alerts CRITICAL, ledgers `halted`, exits 4 and syncs NOTHING.
#   * otherwise `git reset --mixed origin/main` (HEAD + index move, worktree
#     untouched) and `git checkout origin/main -- <path>` for every changed
#     NON-data path (rm if deleted upstream). Data paths are never checked out:
#     on a single-writer box the working files are the newer-or-equal truth.
#   * requirements.txt changed -> pip install -r; functions/** or deploy/api/**
#     -> write state/api-restart, which the ROOT-owned vivek5-api-restart.path
#     watches (its service runs `systemctl try-restart vivek5-api.service`).
#     There is no sudo on this path: this unit runs NoNewPrivileges=yes, which
#     makes a setuid sudo impossible by design, and no sudoers grant exists.
#     deploy/systemd|caddy|bin changed -> WARNING "re-run install.sh --units"
#     from the ROOT-OWNED source clone (+ state/UNITS_STALE marker that
#     preflight reports). NEVER touches /etc, never runs a root script.
#   * RESUMABLE: before the `reset --mixed` the pre-sync HEAD is written to
#     state/update_pending and removed only after every follow-up (checkouts,
#     pip, the restart request, the units warning) succeeded. A run killed or
#     failed in between (pip down, TimeoutStartSec) would otherwise find HEAD
#     == origin/main next time and call it "up to date" with the code paths,
#     the venv or the API left stale for good; the next run resumes from the
#     marker instead.
#   * a ledger row `update` on every path out, written by the runner itself
#     (`python -m scanner.vps ledger-note`: same lock, same section-3.6 shape
#     as every job row -- no mirror of the ledger code lives in this script).
#
# DATA ROOTS: asked from the runner (`python -m scanner.vps data-roots`, one
# path per line -- the union of every job's publish paths in
# scanner/vps/workflows.json); if that call fails (broken venv mid-upgrade)
# the fallback below names the four roots every job's paths live under:
# journal/, public/data/, data/ and backups/.
#
# Runs as vivek5 from vivek5-update.timer with jobs.env loaded (systemd
# EnvironmentFile=, never a shell `.`). No `set -x` anywhere in deploy/bin
# (test-pinned).
set -euo pipefail

vivek_home="${VIVEK_HOME:-/opt/vivek5/app}"
state_dir="${VIVEK_STATE_DIR:-/opt/vivek5/state}"
venv="${VIVEK_VENV:-/opt/vivek5/venv}"
: "${GIT_AUTHOR_NAME:?GIT_AUTHOR_NAME must be set (jobs.env) - it is the VPS identity the second-writer check keys on}"
: "${GIT_AUTHOR_EMAIL:?GIT_AUTHOR_EMAIL must be set (jobs.env)}"
py="$venv/bin/python"
[ -x "$py" ] || py="$(command -v python3)"
# The checkout this script lives in (== VIVEK_HOME on the box): scanner.vps
# is importable from here, whatever VIVEK_HOME points at.
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

ledger_row() {  # <status> <exit-code> <one line>  -- the runner's own writer (M3)
  ( cd "$repo_root" && "$py" -m scanner.vps ledger-note --started "$started" update "$1" "$2" "$3" ) \
    || echo "update: ledger write failed (non-fatal)"
}

notify() {  # <SEVERITY> <text>  -- best effort, through the repo's own alert channels
  ( cd "$repo_root" && "$py" - "$1" "$2" <<'PY' ) || echo "update: notify unavailable ($1: $2)"
import sys
sev, text = sys.argv[1], sys.argv[2]
from scanner import config
from scanner.broker import alert_dispatch as ad
sent = []
for ch in config.ALERT_CHANNELS.get(sev, []):
    try:
        if ch == "telegram" and ad._telegram(text):
            sent.append(ch)
        elif ch == "email" and ad._email("[Vivek 5.0 VPS] update.sh " + sev, text):
            sent.append(ch)
    except Exception:
        pass
print("update: notify " + sev + " sent via " + (",".join(sent) or "NONE"))
PY
}

# vivek5-* JOB units running right now (read-only; empty when systemd cannot say).
running_jobs() {
  systemctl list-units --no-legend --plain --state=active,activating 'vivek5-*.service' 2>/dev/null \
    | awk '{print $1}' | grep -vE '^vivek5-(api|caddy|update|api-restart)\.service$|^vivek5-failed@' | tr '\n' ' ' || true
}

mkdir -p "$state_dir/locks"
exec 9>"$state_dir/locks/repo.lock"
skips_file="$state_dir/update_skips"
if ! flock -x -n 9; then
  running="$(running_jobs)"
  if [ -n "$running" ]; then
    # a job is RUNNING: the busy lock is explained (its own TimeoutStartSec
    # is the hang detector); this is not a step toward the alarm
    rm -f "$skips_file"
    echo "update: skipped busy - running: $running"
    ledger_row skipped 0 "skipped busy (running: ${running% })"
    exit 0
  fi
  n=$(( $(cat "$skips_file" 2>/dev/null || echo 0) + 1 ))
  echo "$n" > "$skips_file"
  echo "update: skipped busy - the repo lock is held but no vivek5 job unit is running (unexplained; consecutive: $n)"
  ledger_row skipped 0 "skipped busy, unexplained x$n"
  if (( n % 12 == 0 )); then
    echo "update: WARNING - $n consecutive unexplained busy skips (>= 1 h): something outside the vivek5 units holds the repo lock (an operator shell? an orphaned process?)"
    exit 1
  fi
  exit 0
fi
rm -f "$skips_file"

cd "$vivek_home"
# The EXCLUSIVE repo lock means no job (and no momentum-gate fetch) is using
# git here: a lock file left now is a killed git's debris, and it would fail
# every fetch/reset until removed by hand (2026-09-27 book review).
for lf in .git/index.lock .git/HEAD.lock .git/ORIG_HEAD.lock .git/FETCH_HEAD.lock .git/packed-refs.lock .git/shallow.lock .git/config.lock; do
  if [ -f "$lf" ]; then rm -f "$lf" && echo "update: removed stale $lf (a git process was killed mid-write)"; fi
done
while IFS= read -r lf; do
  [ -n "$lf" ] || continue
  rm -f "$lf" && echo "update: removed stale $lf"
done < <(find .git/refs -name '*.lock' -type f 2>/dev/null || true)
if ! git fetch -q origin main; then
  ledger_row failed 1 "git fetch origin main failed"
  exit 1
fi
head="$(git rev-parse HEAD)"
target="$(git rev-parse origin/main)"
pending="$state_dir/update_pending"
if [ -s "$pending" ]; then
  p="$(tr -d ' \n\r' < "$pending")"
  if git cat-file -e "$p^{commit}" 2>/dev/null; then
    echo "update: resuming an interrupted sync from ${p:0:7} (state/update_pending)"
    head="$p"
  else
    echo "update: ignoring an unreadable state/update_pending ('$p')"
    rm -f "$pending"
  fi
fi
if [ "$head" = "$target" ]; then
  rm -f "$pending"
  echo "update: up to date at ${head:0:7}"
  ledger_row ok 0 "up to date at ${head:0:7}"
  exit 0
fi

# --- data roots -------------------------------------------------------------
roots=""
if roots_out="$("$py" -m scanner.vps data-roots 2>/dev/null)"; then
  roots="$(printf '%s\n' "$roots_out" | sed -e 's#/*$##' -e '/^$/d' | tr '\n' ' ')"
fi
[ -n "$roots" ] || roots="journal public/data data backups"
is_data() {  # <path>
  local r
  for r in $roots; do
    [[ "$1" == "$r" || "$1" == "$r/"* ]] && return 0
  done
  return 1
}

changed="$(git diff --name-status --no-renames "$head" "$target")"

# --- second-writer check (fail-closed, DESIGN 3.4 step 2) ------------------
since="$head"
if [ -s "$state_dir/publish_head" ]; then
  ph="$(tr -d ' \n\r' < "$state_dir/publish_head")"
  if git cat-file -e "$ph^{commit}" 2>/dev/null; then since="$ph"; fi
fi
foreign_shas=""; foreign_authors=""; foreign_paths=""
while read -r sha; do
  [ -n "$sha" ] || continue
  ident="$(git log -1 --format='%an%x1f%ae' "$sha")"
  an="${ident%%$'\x1f'*}"; ae="${ident#*$'\x1f'}"
  if [ "$an" = "$GIT_AUTHOR_NAME" ] && [ "$ae" = "$GIT_AUTHOR_EMAIL" ]; then continue; fi
  hit=""
  while read -r p; do
    [ -n "$p" ] || continue
    if is_data "$p"; then hit="1"; foreign_paths="$foreign_paths $p"; fi
  done < <(git diff-tree --no-commit-id --name-only -r "$sha")
  if [ -n "$hit" ]; then
    foreign_shas="$foreign_shas $sha"
    foreign_authors="$foreign_authors $an<$ae>"
  fi
done < <(git rev-list "$since..$target")

if [ -n "$foreign_shas" ]; then
  "$py" - "$state_dir/HALT" "$foreign_shas" "$foreign_authors" "$foreign_paths" <<'PY'
import datetime as dt, json, os, sys, tempfile
path, shas, authors, paths = sys.argv[1:5]
body = {"at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "update.sh", "reason": "non-VPS commit touched a data root upstream",
        "shas": shas.split(), "authors": sorted(set(authors.split())),
        "paths": sorted(set(paths.split()))}
os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".HALT.", suffix=".tmp")
with os.fdopen(fd, "w") as fh:
    json.dump(body, fh, indent=2)
    fh.write("\n")
os.replace(tmp, path)
PY
  msg="HALT: a non-VPS commit touched a data root upstream ($foreign_shas by$foreign_authors). Book writers refuse to run until 'python -m scanner.vps accept-upstream' or 'clear-halt'. Working checkout NOT synced."
  echo "update: CRITICAL $msg"
  notify CRITICAL "$msg"
  ledger_row halted 4 "halted: foreign data commit$foreign_shas"
  exit 4
fi

# --- sync code, keep data --------------------------------------------------
printf '%s\n' "$head" > "$pending"
git reset -q --mixed "$target"
synced=0; kept=0
while IFS=$'\t' read -r st p; do
  [ -n "${p:-}" ] || continue
  if is_data "$p"; then kept=$((kept + 1)); continue; fi
  case "$st" in
    D) rm -f -- "$p" ;;
    *) git checkout -q "$target" -- "$p" ;;
  esac
  synced=$((synced + 1))
done <<< "$changed"
echo "update: ${head:0:7} -> ${target:0:7}: $synced code path(s) checked out, $kept data path(s) left to the working tree"

notes=""
if grep -q $'\trequirements.txt$' <<< "$changed"; then
  echo "update: requirements.txt changed - pip install"
  if "$venv/bin/pip" install -q -r requirements.txt; then
    notes="$notes pip-installed"
  else
    ledger_row failed 1 "pip install -r requirements.txt failed after ${target:0:7}"
    exit 1
  fi
fi
if grep -Eq $'\t(functions/|deploy/api/)' <<< "$changed"; then
  # vivek5-api-restart.path (root) watches this file and runs
  # `systemctl try-restart vivek5-api.service`: restarted if running, never
  # started (before cutover / after rollback it is a no-op).
  echo "update: functions/ or deploy/api/ changed - requesting an API restart (state/api-restart)"
  if printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$target" > "$state_dir/api-restart"; then
    notes="$notes api-restart-requested"
  else
    ledger_row failed 1 "could not write state/api-restart after ${target:0:7}"
    exit 1
  fi
fi
if grep -Eq $'\tdeploy/(systemd|caddy|bin)/' <<< "$changed"; then
  touch "$state_dir/UNITS_STALE"
  src="$(cat /usr/local/lib/vivek5/SOURCE 2>/dev/null || echo /usr/local/src/vivek5)"
  msg="deploy/systemd, deploy/caddy or deploy/bin changed at ${target:0:7}: on the box run 'sudo git -C $src pull && sudo $src/deploy/bin/install.sh --units' (the ROOT-OWNED source clone -- never a script from /opt/vivek5/app as root; update.sh itself never touches the system)."
  echo "update: WARNING $msg"
  notify WARNING "$msg"
  notes="$notes units-stale"
fi

rm -f "$pending"
ledger_row ok 0 "synced to ${target:0:7}${notes:+ (${notes# })}"
exit 0
