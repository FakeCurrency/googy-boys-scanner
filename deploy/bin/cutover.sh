#!/usr/bin/env bash
# deploy/bin/cutover.sh -- move the pipeline from GitHub Actions to this box,
# in EXACTLY the order of deploy/DESIGN.md 7, aborting on any failure:
#
#   0. preflight.sh green
#   1. systemctl enable --now vivek5-api.service; external check of /api/vps
#   2. Cloudflare Pages: DISPATCH_URL + DISPATCH_TOKEN set, GH_DISPATCH_TOKEN
#      deleted (via the Pages API when CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID
#      and CF_PAGES_PROJECT are in this shell; otherwise printed as the exact
#      ops.yml actions and confirmed by you)
#   3. GitHub (GH_ADMIN_TOKEN): disable the 15 workflows, GET each until
#      state == disabled_manually; repository variable VPS_ACTIVE=1
#   4. drain: poll queued|in_progress runs of those 15 until none (30 min)
#   5. app + publish clones reset --hard to origin/main; state/publish_head
#   6. enable --now every timer, vivek5-spool.path, update + gc timers
#   7. assert every timer is listed with a NEXT elapse, else rollback.sh + exit 1
#   8. print the post-cutover checklist
#
# GH_ADMIN_TOKEN (fine-grained: this repo, Actions read+write, Variables
# write) comes from the calling shell's environment or `read -rs` -- never
# from a file -- and is unset on exit. No `set -x` in deploy/bin (pinned).
#
#     GH_ADMIN_TOKEN=github_pat_... sudo -E deploy/bin/cutover.sh [--yes]
set -euo pipefail
trap 'unset GH_ADMIN_TOKEN' EXIT

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
    -h|--help) sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "cutover.sh: unknown argument '$a'" >&2; exit 2 ;;
  esac
done

here="$(cd "$(dirname "$0")" && pwd)"
kit="$(cd "$here/.." && pwd)"
etc=/etc/vivek5
step() { printf '\n==> step %s\n' "$*"; }
die()  { printf 'cutover.sh: ABORT - %s\n' "$*" >&2; exit 1; }
confirm() {
  [ "$assume_yes" = "1" ] && return 0
  local reply
  read -r -p "$1 [y/N] " reply
  [ "$reply" = "y" ] || [ "$reply" = "Y" ] || die "not confirmed"
}
[ "$(id -u)" -eq 0 ] || die "run as root (systemctl enable): GH_ADMIN_TOKEN=... sudo -E deploy/bin/cutover.sh"

set -a; . "$etc/jobs.env"; set +a
[ -r /etc/caddy/vivek5.env ] && { set -a; . /etc/caddy/vivek5.env; set +a; }
vivek_home="${VIVEK_HOME:-/opt/vivek5/app}"
publish="${VIVEK_PUBLISH:-/opt/vivek5/publish}"
state_dir="${VIVEK_STATE_DIR:-/opt/vivek5/state}"
domain="${VIVEK_DOMAIN:-}"
as_vivek5() { sudo -u vivek5 -H "$@"; }

# Repo slug from the publish clone's remote (git@github.com:OWNER/REPO.git).
url="$(git -C "$publish" remote get-url origin)"
repo="${url#git@github.com:}"; repo="${repo#https://github.com/}"; repo="${repo%.git}"
[ -n "$repo" ] && [ "$repo" != "$url" ] || die "cannot read OWNER/REPO from the publish remote '$url'"

# ---- GitHub REST helper: prints ONLY the HTTP code; body lands in $gh_body --
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

# ---- 0 ----------------------------------------------------------------------
step "0: preflight"
"$here/preflight.sh" || die "preflight is not green - fix every FAIL first"
[ -n "$domain" ] && [ "$domain" != "CHANGE_ME" ] || die "VIVEK_DOMAIN is not set"
if grep -Eqs '^\s*GH_ADMIN_TOKEN\s*=' "$etc"/*.env; then die "GH_ADMIN_TOKEN must not be assigned in any /etc/vivek5/*.env"; fi
if [ -z "${GH_ADMIN_TOKEN:-}" ]; then
  read -rs -p "GH_ADMIN_TOKEN (fine-grained, this repo, Actions rw + Variables rw; input hidden): " GH_ADMIN_TOKEN; echo
  export GH_ADMIN_TOKEN
fi
[ -n "${GH_ADMIN_TOKEN:-}" ] || die "no GH_ADMIN_TOKEN"
code="$(gh GET "/repos/$repo/actions/workflows?per_page=1")"
[ "$code" = "200" ] || die "GitHub API answers HTTP $code for $repo with this token (need Actions: read+write)"
echo "    token ok for $repo"

# ---- 1 ----------------------------------------------------------------------
step "1: enable the API adapter and check the public front door"
[ -f /etc/caddy/Caddyfile ] || die "/etc/caddy/Caddyfile missing - sudo deploy/bin/install.sh --units --phase 1"
systemctl enable --now vivek5-api.service
systemctl is-active --quiet caddy || die "caddy is not active"
code=000
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "https://$domain/api/vps" 2>/dev/null || echo 000)"
  [ "$code" = "200" ] && break
  sleep 5
done
echo "    https://$domain/api/vps -> HTTP $code"
[ "$code" = "200" ] || die "the dispatch front door does not answer 200 (see journalctl -u vivek5-api -u caddy)"

# ---- 2 ----------------------------------------------------------------------
step "2: Cloudflare Pages env: DISPATCH_URL + DISPATCH_TOKEN set, GH_DISPATCH_TOKEN deleted"
dispatch_url="https://$domain/api/dispatch"
dispatch_token="$(sed -n 's/^DISPATCH_TOKEN=//p' "$etc/api.env" | head -1)"
[ -n "$dispatch_token" ] && [ "$dispatch_token" != "CHANGE_ME" ] || die "DISPATCH_TOKEN missing from $etc/api.env"
if [ -n "${CLOUDFLARE_API_TOKEN:-}" ] && [ -n "${CLOUDFLARE_ACCOUNT_ID:-}" ] && [ -n "${CF_PAGES_PROJECT:-}" ]; then
  # Same body shape scripts/ops.py cf-set-var / cf-delete-var send.
  body="$(python3 -c 'import json,sys; print(json.dumps({"deployment_configs":{"production":{"env_vars":{"DISPATCH_URL":{"type":"plain_text","value":sys.argv[1]},"DISPATCH_TOKEN":{"type":"secret_text","value":sys.argv[2]},"GH_DISPATCH_TOKEN":None}}}}))' "$dispatch_url" "$dispatch_token")"
  code="$(curl -sS -o "$gh_body" -w '%{http_code}' -X PATCH --max-time 60 \
      -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json" -d "$body" \
      "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/pages/projects/$CF_PAGES_PROJECT" || echo 000)"
  echo "    Pages project $CF_PAGES_PROJECT PATCH -> HTTP $code"
  [ "$code" = "200" ] || die "Cloudflare Pages API refused the env change (body in $gh_body)"
else
  cat <<CF
    CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID / CF_PAGES_PROJECT are not in this
    shell, so do this by hand NOW (dispatch ops.yml from a Claude session with the
    GitHub MCP, or use the Pages dashboard -> Settings -> Environment variables):

      action=cf-set-var    args={"name":"DISPATCH_URL","value":"$dispatch_url","type":"plain_text"}
      action=cf-set-var    args={"name":"DISPATCH_TOKEN","value":"<DISPATCH_TOKEN from $etc/api.env>","type":"secret_text"}
      action=cf-delete-var args={"name":"GH_DISPATCH_TOKEN"}

    From then on every SCAN / close / heal / morning-plays request spools to
    this box and nothing can dispatch to GitHub.
CF
  confirm "    All three done?"
fi

# ---- 3 ----------------------------------------------------------------------
step "3: disable the ${#workflows[@]} GitHub workflows and set VPS_ACTIVE=1"
for wf in "${workflows[@]}"; do
  code="$(gh PUT "/repos/$repo/actions/workflows/$wf/disable")"
  printf '    disable %-22s -> HTTP %s\n' "$wf" "$code"
  [ "$code" = "204" ] || die "could not disable $wf (HTTP $code) - nothing else was changed; re-run when fixed"
done
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
done
set_variable VPS_ACTIVE 1 || die "could not set repository variable VPS_ACTIVE=1 (token needs Variables: write)"

# ---- 4 ----------------------------------------------------------------------
step "4: drain in-flight Actions runs of those workflows (timeout 30 min)"
inflight() {
  local total=0 s n
  for s in queued in_progress; do
    code="$(gh GET "/repos/$repo/actions/runs?status=$s&per_page=100")"
    [ "$code" = "200" ] || { echo "    runs?status=$s -> HTTP $code" >&2; return 1; }
    n="$(python3 -c 'import json,sys
wfs=set(sys.argv[2:]); d=json.load(open(sys.argv[1]))
print(sum(1 for r in d.get("workflow_runs",[]) if (r.get("path") or "").split("/")[-1] in wfs))' "$gh_body" "${workflows[@]}")"
    total=$((total + n))
  done
  echo "$total"
}
deadline=$(( $(date +%s) + 1800 ))
while :; do
  n="$(inflight)" || die "could not list runs"
  echo "    $(date -u +%H:%M:%S) in-flight runs: $n"
  [ "$n" = "0" ] && break
  [ "$(date +%s)" -lt "$deadline" ] || die "runs still in flight after 30 min - wait for them (or cancel them on GitHub), then re-run cutover.sh; the workflows stay disabled"
  sleep 30
done

# ---- 5 ----------------------------------------------------------------------
step "5: pristine start from the last Actions commit"
as_vivek5 git -C "$vivek_home" fetch -q origin main
as_vivek5 git -C "$vivek_home" reset -q --hard origin/main
as_vivek5 git -C "$publish" fetch -q origin main
as_vivek5 git -C "$publish" reset -q --hard origin/main
sha="$(git -C "$publish" rev-parse origin/main)"
as_vivek5 bash -c "printf '%s\n' '$sha' > '$state_dir/publish_head'"
rm -f "$state_dir/HALT"
echo "    app + publish at ${sha:0:7}; state/publish_head written"

# ---- 6 ----------------------------------------------------------------------
step "6: enable every timer, the spool path, update + gc"
expected=()
for f in "$kit"/systemd/vivek5-*.timer; do expected+=("$(basename "$f")"); done
for t in "${expected[@]}" vivek5-spool.path; do
  systemctl enable --now "$t" >/dev/null 2>&1 || { echo "    FAILED to enable $t"; "$here/rollback.sh" --yes; exit 1; }
  echo "    enabled $t"
done

# ---- 7 ----------------------------------------------------------------------
step "7: assert every timer has a NEXT elapse"
missing="$(systemctl list-timers --all --output=json | python3 -c 'import json,sys
want=set(sys.argv[1:]); rows=json.load(sys.stdin)
seen={r.get("unit"):r for r in rows}
bad=[t for t in sorted(want) if t not in seen or not seen[t].get("next")]
print(" ".join(bad))' "${expected[@]}")"
if [ -n "$missing" ]; then
  echo "    timers with no NEXT elapse: $missing"
  echo "    rolling back automatically"
  "$here/rollback.sh" --yes
  exit 1
fi
systemctl list-timers --all --no-pager 'vivek5-*' | sed 's/^/    /'
echo "    all ${#expected[@]} timers armed"

# ---- 8 ----------------------------------------------------------------------
step "8: post-cutover checklist"
cat <<DONE
    [ ] DELETE the GH_ADMIN_TOKEN on GitHub now (Settings -> Developer settings -> tokens); it was single-use
    [ ] watch the first hourly crypto row:  sudo -u vivek5 ${VIVEK_VENV:-/opt/vivek5/venv}/bin/python -m scanner.vps ledger
        (or: journalctl -u vivek5-crypto-bot -f)
    [ ] confirm a data commit by author '${GIT_AUTHOR_NAME:-vivek5-vps}' lands on main within the hour
        (commit_sentinel.yml will ::warning:: once on the new author name - expected)
    [ ] the SCAN button / close-all on the site should now spool here: tail -f journalctl -u vivek5-spool
    [ ] Phase 2 when ready: sudo deploy/bin/install.sh --units --phase 2 (basic-auth hash in /etc/caddy/vivek5.env) + DNS
    [ ] CLAUDE.md's '.github/scan-kick' trigger is retired: a scan is now 'systemctl start vivek5-scan@asx.service'
    [ ] GitHub Actions secrets for ops.yml action=vps-dispatch (how a cloud Claude session starts a scan now):
        VPS_DISPATCH_URL=https://${VIVEK_DOMAIN:-<VIVEK_DOMAIN>}/api/dispatch and VPS_DISPATCH_TOKEN = the
        DISPATCH_TOKEN value in /etc/vivek5/api.env (copy it from the box; it is never printed here)
DONE
exit 0
