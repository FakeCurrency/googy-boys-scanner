#!/usr/bin/env bash
# deploy/bin/rollback.sh -- undo cutover.sh (deploy/DESIGN.md 7, last line):
#
#   1. stop + disable every vivek5 timer, the spool path, then the API
#      adapter; wait for any vivek5-* job still running to finish (30 min)
#      so the box stops writing BEFORE GitHub starts again
#   2. re-enable the same 15 workflows (GET each until state == active)
#   3. repository variable VPS_ACTIVE=0
#   4. print what only the owner can do: restore GH_DISPATCH_TOKEN in
#      Cloudflare Pages (its value is his) and delete DISPATCH_URL/DISPATCH_TOKEN
#
# GH_ADMIN_TOKEN from the calling shell or `read -rs`, unset on exit; no
# `set -x` in deploy/bin (test-pinned). cutover.sh calls this with --yes when
# step 7 finds a timer without a NEXT elapse.
#
#     GH_ADMIN_TOKEN=github_pat_... sudo -E deploy/bin/rollback.sh [--yes]
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
    -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "rollback.sh: unknown argument '$a'" >&2; exit 2 ;;
  esac
done

here="$(cd "$(dirname "$0")" && pwd)"
kit="$(cd "$here/.." && pwd)"
etc=/etc/vivek5
step() { printf '\n==> rollback %s\n' "$*"; }
die()  { printf 'rollback.sh: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die "run as root: GH_ADMIN_TOKEN=... sudo -E deploy/bin/rollback.sh"
set -a; . "$etc/jobs.env"; set +a
publish="${VIVEK_PUBLISH:-/opt/vivek5/publish}"

url="$(git -C "$publish" remote get-url origin)"
repo="${url#git@github.com:}"; repo="${repo#https://github.com/}"; repo="${repo%.git}"
[ -n "$repo" ] && [ "$repo" != "$url" ] || die "cannot read OWNER/REPO from the publish remote '$url'"

if [ "$assume_yes" != "1" ]; then
  read -r -p "Roll back: stop the VPS timers and re-enable the ${#workflows[@]} GitHub workflows for $repo? [y/N] " reply
  [ "$reply" = "y" ] || [ "$reply" = "Y" ] || die "not confirmed"
fi

gh_body="$(mktemp)"
trap 'unset GH_ADMIN_TOKEN; rm -f "$gh_body"' EXIT
gh() {  # <METHOD> <path> [json]
  local args=(-sS -o "$gh_body" -w '%{http_code}' -X "$1"
              -H "Authorization: Bearer $GH_ADMIN_TOKEN"
              -H "Accept: application/vnd.github+json"
              -H "X-GitHub-Api-Version: 2022-11-28" --max-time 60)
  if [ -n "${3:-}" ]; then args+=(-H "Content-Type: application/json" -d "$3"); fi
  curl "${args[@]}" "https://api.github.com$2" || echo 000
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
step "1: stop the VPS writer"
for f in "$kit"/systemd/vivek5-*.timer; do
  t="$(basename "$f")"
  systemctl disable --now "$t" >/dev/null 2>&1 && echo "    disabled $t" || echo "    (not enabled) $t"
done
systemctl disable --now vivek5-spool.path >/dev/null 2>&1 && echo "    disabled vivek5-spool.path" || echo "    (not enabled) vivek5-spool.path"
deadline=$(( $(date +%s) + 1800 ))
while :; do
  running="$(systemctl list-units --no-legend --plain --state=active,activating 'vivek5-*.service' 2>/dev/null | awk '{print $1}' | grep -v '^vivek5-api.service$' | tr '\n' ' ' || true)"
  [ -z "$running" ] && break
  echo "    $(date -u +%H:%M:%S) still running: $running"
  [ "$(date +%s)" -lt "$deadline" ] || { echo "    jobs still running after 30 min - they will finish and publish once more; continuing"; break; }
  sleep 20
done
systemctl disable --now vivek5-api.service >/dev/null 2>&1 && echo "    disabled vivek5-api.service" || echo "    (not enabled) vivek5-api.service"

# ---- 2 ----------------------------------------------------------------------
step "2: re-enable the ${#workflows[@]} GitHub workflows"
if [ -z "${GH_ADMIN_TOKEN:-}" ]; then
  read -rs -p "GH_ADMIN_TOKEN (input hidden): " GH_ADMIN_TOKEN; echo
  export GH_ADMIN_TOKEN
fi
[ -n "${GH_ADMIN_TOKEN:-}" ] || die "no GH_ADMIN_TOKEN - the VPS timers are stopped; re-enable the workflows by hand on GitHub"
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
    [ ] if the VPS pushed commits after the last Actions run, the next Actions scan simply builds on them (same files, same identity rules)
    [ ] after a suspected compromise: rotate the deploy key (GitHub -> Settings -> Deploy keys) and re-run install.sh
    [ ] DELETE the GH_ADMIN_TOKEN on GitHub
DONE
[ "$rc" -eq 0 ] || die "one or more GitHub calls failed above - check the workflow states on GitHub by hand"
exit 0
