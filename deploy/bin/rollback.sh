#!/usr/bin/env bash
# deploy/bin/rollback.sh -- undo cutover.sh (deploy/DESIGN.md 7, last line):
#
#   1. stop + disable, in this order: the API adapter FIRST (so no new
#      dispatch is accepted with a 202 that will never run), the spool path,
#      the api-restart path, every vivek5 timer; wait for any vivek5-* job still running to finish
#      (30 min) so the box stops writing BEFORE GitHub starts again; then OUR
#      Caddy. Every unit touched is a vivek5-* unit cutover.sh started -- no
#      other service on this box is stopped, restarted or reconfigured (M6).
#      Dispatches still in state/spool are LISTED: they were accepted but not
#      executed, and must be re-issued via GitHub.
#   2. re-enable the same 15 workflows (GET each until state == active)
#   3. repository variable VPS_ACTIVE=0
#   4. print what only the owner can do: restore GH_DISPATCH_TOKEN in
#      Cloudflare Pages (its value is his) and delete DISPATCH_URL/DISPATCH_TOKEN
#
# GH_ADMIN_TOKEN is PROMPTED (read -rs), reaches curl through a 0600 config
# file (never argv), and is unset on exit; no `set -x` in deploy/bin
# (test-pinned). cutover.sh calls this with --yes when step 7 finds a timer
# without a NEXT elapse.
#
#     sudo /usr/local/lib/vivek5/bin/rollback.sh [--yes]
set -euo pipefail
trap 'unset GH_ADMIN_TOKEN' EXIT

# Must stay identical to cutover.sh and scanner/config.py VPS_WORKFLOWS_TO_DISABLE.
workflows=(
  alert_returns.yml backup_book.yml confluence.yml crypto_bot.yml
  evidence_brief.yml kill_switch.yml lens_backtest.yml momentum.yml
  morning_plays.yml phasemap.yml reco_note.yml scan.yml vivek_backtest.yml
  close_position.yml dispatch_scan.yml
)

assume_yes=0
for a in "$@"; do
  case "$a" in
    --yes) assume_yes=1 ;;
    -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "rollback.sh: unknown argument '$a'" >&2; exit 2 ;;
  esac
done

step() { printf '\n==> rollback %s\n' "$*"; }
die()  { printf 'rollback.sh: %s\n' "$*" >&2; exit 1; }
# Root runs this file: refuse if it, or any directory above it, can be written
# by a non-root user -- a compromised job would otherwise become root the next
# time the operator runs it (2026-09-27 security review). A root-owned sticky
# directory (like /tmp) is accepted.
refuse_unsafe_path() {
  local p uid mode
  p="$(readlink -f "$0")"
  while :; do
    read -r uid mode < <(stat -c '%u %a' "$p") || die "cannot stat $p"
    if [ "$uid" != "0" ]; then
      die "refusing to run as root from $p: it is owned by uid $uid, not root (use a root-owned copy, e.g. /usr/local/lib/vivek5/bin/ or a root clone in /usr/local/src/vivek5)"
    fi
    if (( 8#$mode & 8#022 )) && ! { [ -d "$p" ] && (( 8#$mode & 8#1000 )); }; then
      die "refusing to run as root from $p: it is writable by group/other (mode $mode)"
    fi
    [ "$p" = "/" ] && break
    p="$(dirname "$p")"
  done
}
# Every systemctl that changes a unit goes through here and refuses any target
# that is not a vivek5-* unit (M6 C10: nothing else on this box is ours).
v5ctl() {
  local verb="$1" u
  shift
  for u in "$@"; do
    case "$u" in
      -*|vivek5-*) ;;
      *) printf 'refusing: systemctl %s %s -- not a vivek5-* unit\n' "$verb" "$u" >&2; return 97 ;;
    esac
  done
  systemctl "$verb" "$@"
}
[ "$(id -u)" -eq 0 ] || die "run as root: sudo /usr/local/lib/vivek5/bin/rollback.sh"
refuse_unsafe_path

here="$(cd "$(dirname "$0")" && pwd)"
kit="$(cd "$here/.." && pwd)"
etc=/etc/vivek5
env_get() {  # <file> <KEY>: the raw value, as systemd's EnvironmentFile reads it (no shell expansion)
  sed -n "s/^$2=//p" "$1" 2>/dev/null | tail -1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}
publish="$(env_get "$etc/jobs.env" VIVEK_PUBLISH)"; publish="${publish:-/opt/vivek5/publish}"
state_dir="$(env_get "$etc/jobs.env" VIVEK_STATE_DIR)"; state_dir="${state_dir:-/opt/vivek5/state}"
# Root never runs git in the vivek5-owned clones (no safe.directory for root).
url="$(sudo -u vivek5 -H env -i PATH=/usr/bin:/bin HOME="$state_dir/home" git -C "$publish" remote get-url origin)"
repo="${url#git@github.com:}"; repo="${repo#https://github.com/}"; repo="${repo%.git}"
[ -n "$repo" ] && [ "$repo" != "$url" ] || die "cannot read OWNER/REPO from the publish remote '$url'"

if [ "$assume_yes" != "1" ]; then
  read -r -p "Roll back: stop the VPS units and re-enable the ${#workflows[@]} GitHub workflows for $repo? [y/N] " reply
  [ "$reply" = "y" ] || [ "$reply" = "Y" ] || die "not confirmed"
fi

gh_body="$(mktemp)"; gh_cfg="$(mktemp)"
chmod 0600 "$gh_body" "$gh_cfg"
trap 'unset GH_ADMIN_TOKEN; rm -f "$gh_body" "$gh_cfg"' EXIT
gh() {  # <METHOD> <path> [json]  -- the token reaches curl via -K (a 0600 file), never argv
  local args=(-sS -o "$gh_body" -w '%{http_code}' -X "$1" -K "$gh_cfg"
              -H "Accept: application/vnd.github+json"
              -H "X-GitHub-Api-Version: 2022-11-28" --max-time 60)
  if [ -n "${3:-}" ]; then args+=(-H "Content-Type: application/json" --data-binary "$3"); fi
  # curl's -w already prints 000 on a transport failure: `|| true` keeps
  # the status from aborting, `|| echo 000` would APPEND a second 000.
  local c
  c="$(curl "${args[@]}" "https://api.github.com$2" || true)"
  printf '%s' "${c:-000}"
}
json_field() { python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get(sys.argv[2], ""))' "$gh_body" "$1" 2>/dev/null || echo ""; }
set_variable() {  # <name> <value>
  local code
  code="$(gh PATCH "/repos/$repo/actions/variables/$1" "{\"name\":\"$1\",\"value\":\"$2\"}")"
  if [ "$code" = "404" ]; then code="$(gh POST "/repos/$repo/actions/variables" "{\"name\":\"$1\",\"value\":\"$2\"}")"; fi
  echo "    variable $1=$2 -> HTTP $code"
  case "$code" in 201|204) return 0 ;; *) return 1 ;; esac
}

# ---- 1 ----------------------------------------------------------------------
step "1: stop the VPS writer (API first, then the spool path, the timers, running jobs, Caddy)"
v5ctl disable --now vivek5-api.service >/dev/null 2>&1 && echo "    disabled vivek5-api.service (no new dispatch is accepted)" || echo "    (not enabled) vivek5-api.service"
v5ctl disable --now vivek5-spool.path >/dev/null 2>&1 && echo "    disabled vivek5-spool.path" || echo "    (not enabled) vivek5-spool.path"
v5ctl disable --now vivek5-api-restart.path >/dev/null 2>&1 && echo "    disabled vivek5-api-restart.path" || echo "    (not enabled) vivek5-api-restart.path"
for f in "$kit"/systemd/vivek5-*.timer; do
  t="$(basename "$f")"
  v5ctl disable --now "$t" >/dev/null 2>&1 && echo "    disabled $t" || echo "    (not enabled) $t"
done
deadline=$(( $(date +%s) + 1800 ))
while :; do
  running="$(systemctl list-units --no-legend --plain --state=active,activating 'vivek5-*.service' 2>/dev/null | awk '{print $1}' | grep -vE '^vivek5-(api|caddy)\.service$' | tr '\n' ' ' || true)"
  [ -z "$running" ] && break
  echo "    $(date -u +%H:%M:%S) still running: $running"
  [ "$(date +%s)" -lt "$deadline" ] || { echo "    jobs still running after 30 min - they will finish and publish once more; continuing"; break; }
  sleep 20
done
v5ctl disable --now vivek5-caddy.service >/dev/null 2>&1 && echo "    disabled vivek5-caddy.service" || echo "    (not enabled) vivek5-caddy.service"
left="$(ls "$state_dir/spool" 2>/dev/null | grep -E '\.json$|\.json\.(halted|retry|stuck)$' || true)"
if [ -n "$left" ]; then
  echo "    THESE DISPATCHES WERE ACCEPTED BUT NOT EXECUTED - re-issue them via GitHub once the workflows are back:"
  for n in $left; do
    printf '      %s  ' "$n"
    python3 -c 'import json,sys
try:
    d=json.load(open(sys.argv[1])); print(d.get("workflow","?"), json.dumps(d.get("inputs",{}), sort_keys=True))
except Exception as e:
    print("(unreadable: %s)" % type(e).__name__)' "$state_dir/spool/$n"
  done
else
  echo "    state/spool holds no pending dispatch"
fi

# ---- 2 ----------------------------------------------------------------------
step "2: re-enable the ${#workflows[@]} GitHub workflows"
if [ -z "${GH_ADMIN_TOKEN:-}" ]; then
  read -rs -p "GH_ADMIN_TOKEN (input hidden): " GH_ADMIN_TOKEN; echo
fi
[ -n "${GH_ADMIN_TOKEN:-}" ] || die "no GH_ADMIN_TOKEN - the VPS units are stopped; re-enable the workflows by hand on GitHub"
printf 'header = "Authorization: Bearer %s"\n' "$GH_ADMIN_TOKEN" > "$gh_cfg"
rc=0
for wf in "${workflows[@]}"; do
  code="$(gh PUT "/repos/$repo/actions/workflows/$wf/enable")"
  printf '    enable  %-22s -> HTTP %s\n' "$wf" "$code"
  [ "$code" = "204" ] || rc=1
done
for wf in "${workflows[@]}"; do
  state=""
  for _ in 1 2 3 4 5 6; do
    code="$(gh GET "/repos/$repo/actions/workflows/$wf")"
    state="$(json_field state)"
    [ "$state" = "active" ] && break
    sleep 5
  done
  printf '    verify  %-22s -> HTTP %s state=%s\n' "$wf" "$code" "$state"
  [ "$state" = "active" ] || rc=1
done

# ---- 3 ----------------------------------------------------------------------
step "3: VPS_ACTIVE=0"
set_variable VPS_ACTIVE 0 || rc=1

# ---- 4 ----------------------------------------------------------------------
step "4: owner actions"
cat <<DONE
    [ ] Cloudflare Pages: restore GH_DISPATCH_TOKEN (its value is yours; ops.yml
        action=cf-set-var args={"name":"GH_DISPATCH_TOKEN","value":"<token>","type":"secret_text"})
        and delete DISPATCH_URL + DISPATCH_TOKEN (action=cf-delete-var args={"name":"DISPATCH_URL"}, same for DISPATCH_TOKEN)
        -- until then the SCAN button, close-all, the healer and the plays pinger answer 503
    [ ] re-issue any dispatch listed under step 1 via GitHub (close_position.yml / scan.yml)
    [ ] if the VPS pushed commits after the last Actions run, the next Actions scan simply builds on them (same files, same identity rules)
    [ ] after a suspected compromise: rotate the deploy key (GitHub -> Settings -> Deploy keys) and re-run install.sh
    [ ] DELETE the GH_ADMIN_TOKEN on GitHub
DONE
[ "$rc" -eq 0 ] || die "one or more GitHub calls failed above - check the workflow states on GitHub by hand"
exit 0
