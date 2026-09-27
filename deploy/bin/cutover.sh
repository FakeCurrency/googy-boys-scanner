#!/usr/bin/env bash
# deploy/bin/cutover.sh -- move the pipeline from GitHub Actions to this box,
# in EXACTLY the order of deploy/DESIGN.md 7, aborting on any failure:
#
#   0. preflight.sh green (incl. :80/:443 free or ours -- never taken from
#      another process on this box)
#   1. start vivek5-caddy + vivek5-api; external check of /api/vps
#   2. Cloudflare Pages: DISPATCH_URL + DISPATCH_TOKEN set, GH_DISPATCH_TOKEN
#      deleted (via the Pages API when you give it a token at the prompt;
#      otherwise printed as the exact ops.yml actions and confirmed by you)
#   3. GitHub (GH_ADMIN_TOKEN): disable the 15 workflows, GET each until
#      state == disabled_manually; repository variable VPS_ACTIVE=1
#   4. drain: poll queued|in_progress|pending|waiting|requested runs of those
#      15 until none (30 min), then once more a minute later
#   5. app + publish clones reset --hard to origin/main; state/publish_head
#   6. enable --now every vivek5 timer (update + gc included), vivek5-spool.path
#      and vivek5-api-restart.path
#   7. assert every timer is active with a NEXT elapse, both path units active,
#      and vivek5-api/-caddy enabled (so a reboot brings the front door back);
#      anything else -> rollback.sh (automatically, same token) + exit 1
#   8. print the post-cutover checklist
#
# Tokens are PROMPTED (read -rs), never typed on the command line (that is
# shell history) and never put on a command line here: curl gets them from a
# 0600 config file (-K) and request bodies from 0600 files, because every
# local user can read /proc/*/cmdline (security review). Unset on exit.
# Everything this script starts or stops is a vivek5-* unit (M6 C10).
# No `set -x` in deploy/bin (pinned).
#
#     sudo /usr/local/lib/vivek5/bin/cutover.sh [--yes]
set -euo pipefail
trap 'unset GH_ADMIN_TOKEN CLOUDFLARE_API_TOKEN' EXIT

# The 15 GitHub workflows that must be silent for the VPS to be the ONE
# writer: 13 scheduled + close_position.yml + dispatch_scan.yml (the two manual
# book-writer paths reachable from a browser / a Claude session). Same list as
# scanner/config.py VPS_WORKFLOWS_TO_DISABLE (test-pinned) and rollback.sh.
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
    -h|--help) sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "cutover.sh: unknown argument '$a'" >&2; exit 2 ;;
  esac
done

step() { printf '\n==> step %s\n' "$*"; }
die()  { printf 'cutover.sh: ABORT - %s\n' "$*" >&2; exit 1; }
confirm() {
  [ "$assume_yes" = "1" ] && return 0
  local reply
  read -r -p "$1 [y/N] " reply
  [ "$reply" = "y" ] || [ "$reply" = "Y" ] || die "not confirmed"
}
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
[ "$(id -u)" -eq 0 ] || die "run as root: sudo /usr/local/lib/vivek5/bin/cutover.sh"
refuse_unsafe_path

here="$(cd "$(dirname "$0")" && pwd)"
kit="$(cd "$here/.." && pwd)"
etc=/etc/vivek5
env_get() {  # <file> <KEY>: the raw value, as systemd's EnvironmentFile reads it (no shell expansion)
  sed -n "s/^$2=//p" "$1" 2>/dev/null | tail -1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}
vivek_home="$(env_get "$etc/jobs.env" VIVEK_HOME)"; vivek_home="${vivek_home:-/opt/vivek5/app}"
publish="$(env_get "$etc/jobs.env" VIVEK_PUBLISH)"; publish="${publish:-/opt/vivek5/publish}"
state_dir="$(env_get "$etc/jobs.env" VIVEK_STATE_DIR)"; state_dir="${state_dir:-/opt/vivek5/state}"
venv="$(env_get "$etc/jobs.env" VIVEK_VENV)"; venv="${venv:-/opt/vivek5/venv}"
author="$(env_get "$etc/jobs.env" GIT_AUTHOR_NAME)"
domain="$(env_get "$etc/caddy.env" VIVEK_DOMAIN)"
# Root never runs git in the vivek5-owned clones (no safe.directory for root).
as_vivek5() { sudo -u vivek5 -H env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="$state_dir/home" "$@"; }
as_vivek5_git() { sudo -u vivek5 -H env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="$state_dir/home" \
  GIT_SSH_COMMAND="$(env_get "$etc/jobs.env" GIT_SSH_COMMAND)" git "$@"; }

# Repo slug from the publish clone's remote (git@github.com:OWNER/REPO.git).
url="$(as_vivek5 git -C "$publish" remote get-url origin)"
repo="${url#git@github.com:}"; repo="${repo#https://github.com/}"; repo="${repo%.git}"
[ -n "$repo" ] && [ "$repo" != "$url" ] || die "cannot read OWNER/REPO from the publish remote '$url'"

# ---- GitHub REST helper: prints ONLY the HTTP code; body lands in $gh_body --
# The token reaches curl through a 0600 config file (-K), never argv.
gh_body="$(mktemp)"; gh_cfg="$(mktemp)"; cf_cfg="$(mktemp)"; cf_body="$(mktemp)"
chmod 0600 "$gh_body" "$gh_cfg" "$cf_cfg" "$cf_body"
trap 'unset GH_ADMIN_TOKEN CLOUDFLARE_API_TOKEN; rm -f "$gh_body" "$gh_cfg" "$cf_cfg" "$cf_body"' EXIT
gh() {  # <METHOD> <path> [json]  (json bodies here carry no secret)
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
# The automatic rollback (steps 6/7) needs the SAME admin token to re-enable
# the workflows: hand it over through the environment (root-only
# /proc/<pid>/environ), never argv; the EXIT trap unsets it.
auto_rollback() {
  echo "    rolling back automatically (rollback.sh --yes)"
  export GH_ADMIN_TOKEN
  "$here/rollback.sh" --yes || echo "    rollback.sh reported a failure - check the workflow states on GitHub by hand"
  exit 1
}
set_variable() {  # <name> <value>
  local code
  code="$(gh PATCH "/repos/$repo/actions/variables/$1" "{\"name\":\"$1\",\"value\":\"$2\"}")"
  if [ "$code" = "404" ]; then code="$(gh POST "/repos/$repo/actions/variables" "{\"name\":\"$1\",\"value\":\"$2\"}")"; fi
  echo "    variable $1=$2 -> HTTP $code"
  case "$code" in 201|204) return 0 ;; *) return 1 ;; esac
}

# ---- 0 ----------------------------------------------------------------------
step "0: preflight"
"$here/preflight.sh" || die "preflight is not green - fix every FAIL first"
[ -n "$domain" ] && [ "$domain" != "CHANGE_ME" ] || die "VIVEK_DOMAIN is not set in $etc/caddy.env"
if grep -Eqs '^\s*GH_ADMIN_TOKEN\s*=' "$etc"/*.env; then die "GH_ADMIN_TOKEN must not be assigned in any /etc/vivek5/*.env"; fi
"$here/ports.sh" --check >/dev/null || die ":80/:443 are held by another process on this box, or the listeners could not be listed - cutover will not take them (see preflight: own server or a Cloudflare Tunnel)"
if [ -z "${GH_ADMIN_TOKEN:-}" ]; then
  read -rs -p "GH_ADMIN_TOKEN (fine-grained, this repo, Actions rw + Variables rw; input hidden): " GH_ADMIN_TOKEN; echo
fi
[ -n "${GH_ADMIN_TOKEN:-}" ] || die "no GH_ADMIN_TOKEN"
# --yes answers OUR prompts; it cannot confirm a change a human makes by hand
# in the Cloudflare dashboard. Without the Pages API inputs, step 2 is manual
# -- and disabling the workflows (step 3) while Cloudflare still dispatches to
# GitHub leaves every SCAN / close click failing. Refuse BEFORE step 1.
if [ "$assume_yes" = "1" ] && { [ -z "${CLOUDFLARE_API_TOKEN:-}" ] || [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ] || [ -z "${CF_PAGES_PROJECT:-}" ]; }; then
  die "--yes cannot confirm step 2's MANUAL Cloudflare change: run without --yes (you are prompted for a Pages token, or to confirm the change by hand)"
fi
printf 'header = "Authorization: Bearer %s"\n' "$GH_ADMIN_TOKEN" > "$gh_cfg"
code="$(gh GET "/repos/$repo/actions/workflows?per_page=1")"
[ "$code" = "200" ] || die "GitHub API answers HTTP $code for $repo with this token (need Actions: read+write)"
echo "    token ok for $repo"

# ---- 1 ----------------------------------------------------------------------
step "1: start OUR Caddy + the API adapter and check the public front door"
[ -f "$etc/Caddyfile" ] || die "$etc/Caddyfile missing - sudo <source>/deploy/bin/install.sh --units --phase 1"
v5ctl enable --now vivek5-caddy.service vivek5-api.service
systemctl is-active --quiet vivek5-caddy.service || die "vivek5-caddy.service is not active (journalctl -u vivek5-caddy -n 50)"
code=000
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "https://$domain/api/vps" 2>/dev/null || true)"; code="${code:-000}"
  [ "$code" = "200" ] && break
  sleep 5
done
echo "    https://$domain/api/vps -> HTTP $code"
[ "$code" = "200" ] || die "the dispatch front door does not answer 200 (see journalctl -u vivek5-api -u vivek5-caddy)"

# ---- 2 ----------------------------------------------------------------------
step "2: Cloudflare Pages env: DISPATCH_URL + DISPATCH_TOKEN set, GH_DISPATCH_TOKEN deleted"
dispatch_url="https://$domain/api/dispatch"
dispatch_token="$(env_get "$etc/api.env" DISPATCH_TOKEN)"
[ -n "$dispatch_token" ] && [ "$dispatch_token" != "CHANGE_ME" ] || die "DISPATCH_TOKEN missing from $etc/api.env"
if [ -z "${CLOUDFLARE_API_TOKEN:-}" ] && [ "$assume_yes" != "1" ]; then
  read -rs -p "Cloudflare API token with Pages:Edit (blank = do step 2 by hand; input hidden): " CLOUDFLARE_API_TOKEN; echo
  if [ -n "$CLOUDFLARE_API_TOKEN" ]; then
    read -r -p "Cloudflare account id: " CLOUDFLARE_ACCOUNT_ID
    read -r -p "Cloudflare Pages project name: " CF_PAGES_PROJECT
  fi
fi
if [ -n "${CLOUDFLARE_API_TOKEN:-}" ] && [ -n "${CLOUDFLARE_ACCOUNT_ID:-}" ] && [ -n "${CF_PAGES_PROJECT:-}" ]; then
  # Same body shape scripts/ops.py cf-set-var / cf-delete-var send. The body
  # (it carries DISPATCH_TOKEN) and the auth header go through 0600 files.
  # The token reaches python through its ENVIRONMENT, never its argv:
  # /proc/<pid>/cmdline is world-readable, /proc/<pid>/environ is not.
  V5_DU="$dispatch_url" V5_DT="$dispatch_token" python3 -c 'import json,os,sys; open(sys.argv[1],"w").write(json.dumps({"deployment_configs":{"production":{"env_vars":{"DISPATCH_URL":{"type":"plain_text","value":os.environ["V5_DU"]},"DISPATCH_TOKEN":{"type":"secret_text","value":os.environ["V5_DT"]},"GH_DISPATCH_TOKEN":None}}}}))' \
    "$cf_body" < /dev/null
  printf 'header = "Authorization: Bearer %s"\n' "$CLOUDFLARE_API_TOKEN" > "$cf_cfg"
  code="$(curl -sS -o "$gh_body" -w '%{http_code}' -X PATCH --max-time 60 -K "$cf_cfg" \
      -H "Content-Type: application/json" --data-binary @"$cf_body" \
      "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/pages/projects/$CF_PAGES_PROJECT" || true)"; code="${code:-000}"
  : > "$cf_body"
  echo "    Pages project $CF_PAGES_PROJECT PATCH -> HTTP $code"
  [ "$code" = "200" ] || { : > "$cf_cfg"; die "Cloudflare Pages API refused the env change"; }
  # Pages applies env var changes only to NEW deployments, so redeploy main
  # (same request as scripts/ops.py cf-redeploy). A failure here is not fatal:
  # the vars are set; the dashboard's 'Retry deployment' finishes the job.
  code="$(curl -sS -o "$gh_body" -w '%{http_code}' -X POST --max-time 60 -K "$cf_cfg" \
      -F branch=main \
      "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/pages/projects/$CF_PAGES_PROJECT/deployments" || true)"; code="${code:-000}"
  : > "$cf_cfg"
  echo "    Pages project $CF_PAGES_PROJECT redeploy -> HTTP $code"
  case "$code" in 200|201) ;; *)
    echo "    WARNING: redeploy not confirmed. Cloudflare dashboard -> Workers & Pages -> $CF_PAGES_PROJECT"
    echo "             -> Deployments -> latest production -> Retry deployment, before relying on the buttons." ;;
  esac
else
  cat <<CF
    No Cloudflare API token given, so do this by hand NOW in the Cloudflare
    dashboard -> Workers & Pages -> the googy-boys-scanner project ->
    Settings -> Variables and Secrets (Production):

      1. add  DISPATCH_URL   = $dispatch_url            (type: Text; not secret,
         so ops.yml action=cf-set-var is fine for this one)
      2. add  DISPATCH_TOKEN = <the DISPATCH_TOKEN line in $etc/api.env>
                                                        (type: Secret / Encrypt)
      3. delete GH_DISPATCH_TOKEN (copy its value somewhere safe first:
         rollback needs it back). Deleting by name carries no secret, so
         ops.yml action=cf-delete-var args={"name":"GH_DISPATCH_TOKEN"} is fine too
      4. Deployments -> latest production deployment -> Retry deployment
         (Pages only applies variable changes to a NEW deployment)

    Do NOT set DISPATCH_TOKEN through ops.yml: workflow inputs are recorded
    on the run page of this PUBLIC repo. ops.yml action=cf-redeploy is fine.

    From then on every SCAN / close / heal / morning-plays request spools to
    this box and nothing can dispatch to GitHub.
CF
  confirm "    All four done?"
fi

# ---- 3 ----------------------------------------------------------------------
step "3: disable the ${#workflows[@]} GitHub workflows and set VPS_ACTIVE=1"
for wf in "${workflows[@]}"; do
  code="$(gh PUT "/repos/$repo/actions/workflows/$wf/disable")"
  printf '    disable %-22s -> HTTP %s\n' "$wf" "$code"
  [ "$code" = "204" ] || die "could not disable $wf (HTTP $code) - nothing else was changed; re-run when fixed"
done
wf_ids=()
for wf in "${workflows[@]}"; do
  state=""
  for _ in 1 2 3 4 5 6; do
    code="$(gh GET "/repos/$repo/actions/workflows/$wf")"
    state="$(json_field state)"
    [ "$state" = "disabled_manually" ] && break
    sleep 5
  done
  printf '    verify  %-22s -> HTTP %s state=%s\n' "$wf" "$code" "$state"
  [ "$state" = "disabled_manually" ] || die "$wf is '$state', not disabled_manually - run rollback.sh to re-enable what was disabled"
  wf_ids+=("$(json_field id)")
done
set_variable VPS_ACTIVE 1 || die "could not set repository variable VPS_ACTIVE=1 (token needs Variables: write)"

# ---- 4 ----------------------------------------------------------------------
step "4: drain in-flight Actions runs of those workflows (timeout 30 min)"
inflight() {
  local total=0 s n
  # every status a run can sit in before it finishes: a cron run created
  # seconds before the disable may be 'pending'/'waiting'/'requested'
  for s in queued in_progress pending waiting requested; do
    code="$(gh GET "/repos/$repo/actions/runs?status=$s&per_page=100")"
    [ "$code" = "200" ] || { echo "    runs?status=$s -> HTTP $code" >&2; return 1; }
    # match on the numeric workflow_id (read back in step 3); the run's
    # `path` may carry an @ref suffix, so the file-name match is a fallback
    n="$(python3 -c 'import json,sys
ids=set(x for x in sys.argv[2].split(",") if x); wfs=set(sys.argv[3:]); d=json.load(open(sys.argv[1]))
def mine(r):
    return str(r.get("workflow_id","")) in ids or (r.get("path") or "").split("@")[0].split("/")[-1] in wfs
print(sum(1 for r in d.get("workflow_runs",[]) if mine(r)))' "$gh_body" "$(IFS=,; echo "${wf_ids[*]}")" "${workflows[@]}")"
    total=$((total + n))
  done
  echo "$total"
}
deadline=$(( $(date +%s) + 1800 ))
confirmed=0
while :; do
  n="$(inflight)" || die "could not list runs"
  echo "    $(date -u +%H:%M:%S) in-flight runs: $n"
  if [ "$n" = "0" ]; then
    [ "$confirmed" = "1" ] && break
    confirmed=1
    echo "    none - polling once more in 60 s (a run created just before the disable can appear late)"
    sleep 60
    continue
  fi
  confirmed=0
  [ "$(date +%s)" -lt "$deadline" ] || die "runs still in flight after 30 min - wait for them (or cancel them on GitHub), then re-run cutover.sh; the workflows stay disabled"
  sleep 30
done

# ---- 5 ----------------------------------------------------------------------
step "5: pristine start from the last Actions commit"
as_vivek5_git -C "$vivek_home" fetch -q origin main
as_vivek5_git -C "$vivek_home" reset -q --hard origin/main
as_vivek5_git -C "$publish" fetch -q origin main
as_vivek5_git -C "$publish" reset -q --hard origin/main
sha="$(as_vivek5 git -C "$publish" rev-parse origin/main)"
as_vivek5 sh -c 'printf "%s\n" "$1" > "$2"' _ "$sha" "$state_dir/publish_head"
rm -f "$state_dir/HALT"
echo "    app + publish at ${sha:0:7}; state/publish_head written"

# ---- 6 ----------------------------------------------------------------------
step "6: enable every vivek5 timer (update + gc included), the spool path and the api-restart path"
expected=()
for f in "$kit"/systemd/vivek5-*.timer; do expected+=("$(basename "$f")"); done
paths=(vivek5-spool.path vivek5-api-restart.path)
for t in "${expected[@]}" "${paths[@]}"; do
  v5ctl enable --now "$t" >/dev/null 2>&1 || { echo "    FAILED to enable $t"; auto_rollback; }
  echo "    enabled $t"
done

# ---- 7 ----------------------------------------------------------------------
step "7: assert every timer is armed, both path units watch, and the front door survives a reboot"
# One `systemctl show` per unit (stable across systemd versions; no JSON
# table output assumed). A timer counts only when ACTIVE with a real next
# realtime elapse; an empty / n/a / 0 value means it will never fire.
missing=""
for t in "${expected[@]}"; do
  st="$(systemctl show --property=ActiveState --value "$t" 2>/dev/null || echo '?')"
  nx="$(systemctl show --property=NextElapseUSecRealtime --value "$t" 2>/dev/null || echo '')"
  case "$st:$nx" in
    active:|active:n/a|active:0|active:infinity) missing="$missing $t(no-next)" ;;
    active:*) ;;
    *) missing="$missing $t($st)" ;;
  esac
done
for u in "${paths[@]}"; do
  [ "$(systemctl show --property=ActiveState --value "$u" 2>/dev/null || echo '?')" = "active" ] || missing="$missing $u(inactive)"
done
for u in vivek5-api.service vivek5-caddy.service; do
  [ "$(systemctl is-enabled "$u" 2>/dev/null || true)" = "enabled" ] || missing="$missing $u(not-enabled)"
  systemctl is-active --quiet "$u" || missing="$missing $u(inactive)"
done
if [ -n "$missing" ]; then
  echo "    not armed:$missing"
  auto_rollback
fi
systemctl list-timers --all --no-pager 'vivek5-*' | sed 's/^/    /' || true
echo "    all ${#expected[@]} timers armed, ${#paths[@]} path units watching, api + caddy enabled"

# ---- 8 ----------------------------------------------------------------------
step "8: post-cutover checklist"
app_home="$(env_get "$etc/jobs.env" VIVEK_HOME)"; app_home="${app_home:-/opt/vivek5/app}"
cat <<DONE
    [ ] DELETE the GH_ADMIN_TOKEN on GitHub now (Settings -> Developer settings -> tokens); it was single-use
    [ ] watch the first hourly crypto row (reads the box's real ledger, via the units' own settings):
          sudo systemd-run --quiet --wait --pipe --collect -p User=vivek5 -p EnvironmentFile=$etc/jobs.env \\
            -p WorkingDirectory=$app_home $venv/bin/python -m scanner.vps ledger
        (or: journalctl -u vivek5-crypto-bot -f)
    [ ] confirm a data commit by author '${author:-vivek5-vps}' lands on main within the hour
        (commit_sentinel.yml will ::warning:: once on the new author name - expected)
    [ ] the SCAN button / close-all on the site should now spool here: journalctl -u vivek5-spool -f
    [ ] Phase 2 when ready: sudo <source>/deploy/bin/install.sh --units --phase 2 (basic-auth hash in $etc/caddy.env) + DNS
    [ ] CLAUDE.md's '.github/scan-kick' trigger is retired. A scan by hand is now
        'run scan.yml market=asx slot=manual reason=manual' (deploy/README.md, 'Trigger a scan by hand';
        the vivek5-scan@ units are the HOURLY slot and skip outside market hours), or from a Claude
        session: ops.yml action=vps-dispatch
    [ ] GitHub Actions secrets for ops.yml action=vps-dispatch (how a cloud Claude session starts a scan now):
        VPS_DISPATCH_URL=https://${domain:-<VIVEK_DOMAIN>}/api/dispatch and VPS_DISPATCH_TOKEN = the
        DISPATCH_TOKEN value in $etc/api.env (copy it from the box; it is never printed here)
DONE
exit 0
