#!/usr/bin/env bash
# deploy/bin/update.sh -- advance the WORKING checkout to origin/main.
# deploy/DESIGN.md 3.7, verbatim in intent:
#
#   * repo lock EXCLUSIVE, NON-BLOCKING (same file every job holds shared,
#     $VIVEK_STATE_DIR/locks/repo.lock). Busy -> ledger `update: skipped busy`,
#     bump a counter, and after 12 consecutive skips (= 1 h at */5) exit 1 so
#     the OnFailure hook alerts that something may be hung.
#   * HEAD == origin/main -> exit 0.
#   * SECOND-WRITER CHECK before touching anything: a commit since
#     state/publish_head that touches a DATA ROOT and is not ours (GIT_AUTHOR_
#     NAME + GIT_AUTHOR_EMAIL) writes state/HALT (json: shas, authors, paths),
#     alerts CRITICAL, ledgers `halted`, exits 4 and syncs NOTHING.
#   * otherwise `git reset --mixed origin/main` (HEAD + index move, worktree
#     untouched) and `git checkout origin/main -- <path>` for every changed
#     NON-data path (rm if deleted upstream). Data paths are never checked out:
#     on a single-writer box the working files are the newer-or-equal truth.
#   * requirements.txt changed -> pip install -r; functions/** or deploy/api/**
#     -> `sudo systemctl restart vivek5-api.service` (the sudoers grant);
#     deploy/systemd|caddy|bin changed -> WARNING "re-run install.sh --units"
#     (+ state/UNITS_STALE marker that preflight reports). NEVER touches /etc.
#   * a ledger row `update` on every path out.
#
# DATA ROOTS: asked from the runner (`python -m scanner.vps data-roots`, one
# path per line -- the union of every job's publish paths in
# scanner/vps/workflows.json); if that call fails (broken venv mid-upgrade)
# the fallback below names the four roots every job's paths live under:
# journal/, public/data/, data/ and backups/. The LEDGER row is written here
# in the 3.6 shape (the runner has no ledger-note verb) under the same
# locks/ledger.lock scanner/vps/ledger.py takes, atomically.
#
# Runs as vivek5 from vivek5-update.timer with jobs.env loaded; a hand run
# needs the same variables (`set -a; . /etc/vivek5/jobs.env; set +a`).
# No `set -x` anywhere in deploy/bin (test-pinned).
set -euo pipefail

vivek_home="${VIVEK_HOME:-/opt/vivek5/app}"
state_dir="${VIVEK_STATE_DIR:-/opt/vivek5/state}"
venv="${VIVEK_VENV:-/opt/vivek5/venv}"
ledger="${VIVEK_RUNS_LEDGER:-$state_dir/runs.json}"
: "${GIT_AUTHOR_NAME:?GIT_AUTHOR_NAME must be set (jobs.env) - it is the VPS identity the second-writer check keys on}"
: "${GIT_AUTHOR_EMAIL:?GIT_AUTHOR_EMAIL must be set (jobs.env)}"
py="$venv/bin/python"
[ -x "$py" ] || py="$(command -v python3)"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

ledger_row() {  # <status> <exit-code> <one line>
  "$py" - "$ledger" "update" "$1" "$2" "$3" "$started" "$(dirname "$ledger")/locks/ledger.lock" <<'PY' || echo "update: ledger write failed (non-fatal)"
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

notify() {  # <SEVERITY> <text>  -- best effort, through the repo's own alert channels
  ( cd "$vivek_home" && "$py" - "$1" "$2" <<'PY' ) || echo "update: notify unavailable ($1: $2)"
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

mkdir -p "$state_dir/locks"
exec 9>"$state_dir/locks/repo.lock"
if ! flock -x -n 9; then
  skips_file="$state_dir/update_skips"
  n=$(( $(cat "$skips_file" 2>/dev/null || echo 0) + 1 ))
  echo "$n" > "$skips_file"
  echo "update: skipped busy (a job holds the repo lock; consecutive skips: $n)"
  ledger_row skipped 0 "skipped busy x$n"
  if (( n % 12 == 0 )); then
    echo "update: WARNING - $n consecutive busy skips (>= 1 h): a job may be hung on the repo lock"
    exit 1
  fi
  exit 0
fi
rm -f "$state_dir/update_skips"

cd "$vivek_home"
if ! git fetch -q origin main; then
  ledger_row failed 1 "git fetch origin main failed"
  exit 1
fi
head="$(git rev-parse HEAD)"
target="$(git rev-parse origin/main)"
if [ "$head" = "$target" ]; then
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
  echo "update: functions/ or deploy/api/ changed - restarting vivek5-api.service"
  if sudo -n systemctl restart vivek5-api.service; then
    notes="$notes api-restarted"
  else
    ledger_row failed 1 "api restart failed after ${target:0:7}"
    exit 1
  fi
fi
if grep -Eq $'\tdeploy/(systemd|caddy|bin)/' <<< "$changed"; then
  touch "$state_dir/UNITS_STALE"
  msg="deploy/systemd, deploy/caddy or deploy/bin changed at ${target:0:7}: re-run 'sudo deploy/bin/install.sh --units' on the box (update.sh never touches /etc)."
  echo "update: WARNING $msg"
  notify WARNING "$msg"
  notes="$notes units-stale"
fi

ledger_row ok 0 "synced to ${target:0:7}${notes:+ (${notes# })}"
exit 0
