#!/usr/bin/env bash
# deploy/bin/install.sh -- prepare an Ubuntu 24.04 box for Vivek 5.0
# (deploy/DESIGN.md 1, D1/D7/D9). ROOT, IDEMPOTENT, and it runs FROM A
# CHECKOUT, never from `curl | bash`:
#
#     git clone https://github.com/FakeCurrency/googy-boys-scanner /tmp/v5 && cd /tmp/v5
#     sudo deploy/bin/install.sh [--phase 1|2]
#
#     sudo deploy/bin/install.sh --units [--phase 1|2]   re-copy units + Caddyfile only
#
# What a full run does (each step skips what is already in place):
#   apt: python3.12-venv python3-pip git rsync curl ca-certificates gnupg
#   Node 22 from NodeSource and Caddy >= 2.8 from its cloudsmith repo (never
#   Ubuntu's node 18 / caddy 2.6.2 -- D9)
#   users vivek5 (jobs) + vivek5-api (adapter) + group vivek5-spool
#   /opt/vivek5/{app,publish,venv,state/...}: app = full clone, publish =
#   --filter=blob:none clone, both on the ssh remote with gc.auto 0
#   venv + pip install -r requirements.txt + compileall
#   units COPIED to /etc/systemd/system + daemon-reload (timers are NOT
#   enabled here -- cutover.sh does that, after the GitHub side is quiet)
#   /etc/vivek5/{jobs,api}.env from deploy/env/*.example ONLY IF ABSENT
#   (0640, DISPATCH_TOKEN generated), the ed25519 deploy key (printed, with
#   the GitHub instructions), github.com host keys (fingerprints printed for
#   you to verify), the journald drop-in, sudoers.d/vivek5 (exactly two
#   commands), the box clock on UTC, and the Caddyfile for --phase.
#
# No `set -x` anywhere in deploy/bin (test-pinned).
set -euo pipefail

app=/opt/vivek5/app
publish=/opt/vivek5/publish
venv=/opt/vivek5/venv
state=/opt/vivek5/state
etc=/etc/vivek5

phase=""
units_only=0
usage() { sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; }
while [ $# -gt 0 ]; do
  case "$1" in
    --phase) phase="${2:-}"; shift 2 ;;
    --phase=*) phase="${1#*=}"; shift ;;
    --units) units_only=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "install.sh: unknown argument '$1'" >&2; usage >&2; exit 2 ;;
  esac
done

log()  { printf '\n==> %s\n' "$*"; }
die()  { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root: sudo deploy/bin/install.sh"
here="$(cd "$(dirname "$0")" && pwd)"
kit="$(cd "$here/.." && pwd)"
src_repo="$(cd "$kit/.." && pwd)"
[ -f "$kit/DESIGN.md" ] || die "cannot find deploy/DESIGN.md next to this script - run it from a checkout"
git -C "$src_repo" rev-parse --git-dir >/dev/null 2>&1 || die "$src_repo is not a git checkout - clone the repo and run deploy/bin/install.sh from it, not from a pipe"

# The phase defaults to whatever the installed api.env says, so a bare
# `--units` re-run can never downgrade a Phase 2 box to the Phase 1 Caddyfile.
if [ -z "$phase" ] && [ -r "$etc/api.env" ]; then
  phase="$(sed -n 's/^VIVEK_PHASE=\([12]\).*/\1/p' "$etc/api.env" | head -1)"
fi
phase="${phase:-1}"
case "$phase" in 1|2) ;; *) die "--phase must be 1 or 2 (got '$phase')" ;; esac

as_vivek5() { sudo -u vivek5 -H "$@"; }

install_units() {
  log "units -> /etc/systemd/system (copied, never symlinked)"
  local f b
  for f in "$kit"/systemd/vivek5-*; do
    install -m 0644 -o root -g root "$f" /etc/systemd/system/
  done
  for f in /etc/systemd/system/vivek5-*; do
    [ -f "$f" ] || continue
    b="$(basename "$f")"
    if [ ! -e "$kit/systemd/$b" ]; then
      echo "    removing stale unit $b (no longer in deploy/systemd)"
      systemctl disable --now "$b" >/dev/null 2>&1 || true
      rm -f "$f"
    fi
  done
  systemctl daemon-reload
  rm -f "$state/UNITS_STALE"
  echo "    $(ls "$kit"/systemd/vivek5-* | wc -l) unit files installed; timers are enabled by cutover.sh, not here"
}

install_caddy_config() {
  log "Caddy config (phase $phase)"
  install -d -m 0755 /etc/caddy
  if [ ! -e /etc/caddy/vivek5.env ]; then
    cat > /etc/caddy/vivek5.env <<'CENV'
# Environment for /etc/caddy/Caddyfile placeholders (loaded by the
# caddy.service drop-in /etc/systemd/system/caddy.service.d/vivek5.conf).
# The hostname that points at this box. REQUIRED for both phases (D7).
VIVEK_DOMAIN=CHANGE_ME
# Phase 2 only: HTTP basic auth for POST /api/scan and /api/close.
# Hash with: caddy hash-password --plaintext '<password>'
VIVEK_API_BASIC_USER=vivek
VIVEK_API_BASIC_HASH=CHANGE_ME
CENV
  fi
  chown root:caddy /etc/caddy/vivek5.env 2>/dev/null || chown root:root /etc/caddy/vivek5.env
  chmod 0640 /etc/caddy/vivek5.env
  install -d -m 0755 /etc/systemd/system/caddy.service.d
  printf '[Service]\nEnvironmentFile=/etc/caddy/vivek5.env\n' > /etc/systemd/system/caddy.service.d/vivek5.conf
  install -m 0644 -o root -g root "$kit/caddy/Caddyfile.phase$phase" /etc/caddy/Caddyfile
  systemctl daemon-reload
  local domain hash
  domain="$(sed -n 's/^VIVEK_DOMAIN=//p' /etc/caddy/vivek5.env | head -1)"
  hash="$(sed -n 's/^VIVEK_API_BASIC_HASH=//p' /etc/caddy/vivek5.env | head -1)"
  if [ -z "$domain" ] || [ "$domain" = "CHANGE_ME" ]; then
    echo "    Caddy NOT (re)loaded: set VIVEK_DOMAIN in /etc/caddy/vivek5.env, then: sudo deploy/bin/install.sh --units --phase $phase"
    return 0
  fi
  if [ "$phase" = "2" ] && { [ -z "$hash" ] || [ "$hash" = "CHANGE_ME" ]; }; then
    echo "    Caddy NOT (re)loaded: Phase 2 needs VIVEK_API_BASIC_HASH in /etc/caddy/vivek5.env (caddy hash-password), then re-run --units"
    return 0
  fi
  if ( set -a; . /etc/caddy/vivek5.env; set +a; caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile >/dev/null ); then
    systemctl enable --now caddy >/dev/null
    systemctl reload caddy || systemctl restart caddy
    echo "    Caddyfile.phase$phase validated and loaded for $domain"
  else
    die "caddy validate failed on /etc/caddy/Caddyfile (phase $phase) - fix /etc/caddy/vivek5.env and re-run --units"
  fi
}

if [ "$units_only" = "1" ]; then
  install_units
  install_caddy_config
  if [ -r "$etc/api.env" ] && ! grep -q "^VIVEK_PHASE=$phase\$" "$etc/api.env"; then
    sed -i "s/^VIVEK_PHASE=.*/VIVEK_PHASE=$phase/" "$etc/api.env"
    systemctl try-restart vivek5-api.service >/dev/null 2>&1 || true
    echo "    api.env VIVEK_PHASE set to $phase (adapter restarted if it was running)"
  fi
  exit 0
fi

# ---------------------------------------------------------------------------
log "OS"
if [ -r /etc/os-release ]; then
  . /etc/os-release
  echo "    ${PRETTY_NAME:-unknown}"
  if [ "${ID:-}" != "ubuntu" ] || [ "${VERSION_ID:-}" != "24.04" ]; then
    echo "    WARNING: this kit is written and tested for Ubuntu 24.04 (python3.12, systemd 255)"
  fi
fi

log "apt packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3.12-venv python3-pip git rsync curl ca-certificates gnupg tzdata sudo openssh-client >/dev/null
echo "    ok"

log "Node 22 (NodeSource; Ubuntu's apt ships 18, which cannot import the Functions)"
node_major() { command -v node >/dev/null 2>&1 && node --version | sed -E 's/^v([0-9]+).*/\1/' || echo 0; }
if [ "$(node_major)" -lt 22 ]; then
  install -d -m 0755 /etc/apt/keyrings
  curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor --yes -o /etc/apt/keyrings/nodesource.gpg
  echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" > /etc/apt/sources.list.d/nodesource.list
  apt-get update -q
  apt-get install -y -q nodejs >/dev/null
fi
echo "    node $(node --version) at $(command -v node)"
[ -x /usr/bin/node ] || echo "    WARNING: vivek5-api.service expects /usr/bin/node; symlink your node there if it lives elsewhere"

log "Caddy >= 2.8 (official cloudsmith repo; Ubuntu's 2.6.2 has no basic_auth)"
caddy_ok() {
  command -v caddy >/dev/null 2>&1 || return 1
  caddy version | python3 -c 'import re,sys; m=re.search(r"v?(\d+)\.(\d+)", sys.stdin.read()); sys.exit(0 if m and (int(m.group(1)),int(m.group(2)))>=(2,8) else 1)'
}
if ! caddy_ok; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q
  apt-get install -y -q caddy >/dev/null
fi
echo "    $(caddy version)"

log "users vivek5, vivek5-api, group vivek5-spool"
getent group vivek5-spool >/dev/null || groupadd --system vivek5-spool
id -u vivek5 >/dev/null 2>&1 || useradd --system --home-dir "$state/home" --no-create-home --shell /usr/sbin/nologin vivek5
id -u vivek5-api >/dev/null 2>&1 || useradd --system --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin vivek5-api
usermod -aG vivek5-spool vivek5-api
# notify-failure attaches `journalctl -u <unit> -n 30`, which needs this group.
usermod -aG systemd-journal vivek5
echo "    ok"

log "layout under /opt/vivek5"
install -d -m 0755 -o root -g root /opt/vivek5
install -d -m 0755 -o vivek5 -g vivek5 "$app" "$publish"
# state/ is readable by the adapter (group vivek5-spool: /api/vps reads
# runs.json + HALT) and writable only by the runner; spool/ is the one tree
# both write (setgid so the runner can move what the adapter created).
install -d -m 2750 -o vivek5 -g vivek5-spool "$state"
install -d -m 2770 -o vivek5 -g vivek5-spool "$state/spool" "$state/spool/.tmp" "$state/spool/done" "$state/spool/failed"
install -d -m 0750 -o vivek5 -g vivek5 "$state/locks" "$state/summaries" "$state/home" "$state/cache"
if [ ! -e "$state/kv.json" ]; then
  echo '{}' > "$state/kv.json"
fi
chown vivek5-api:vivek5-spool "$state/kv.json"
chmod 0660 "$state/kv.json"
echo "    ok"

log "clones (app = full, publish = --filter=blob:none; both on the ssh remote)"
origin_url="$(git -C "$src_repo" remote get-url origin 2>/dev/null || true)"
ssh_url="${VIVEK_REPO_SSH:-}"
if [ -z "$ssh_url" ]; then
  case "$origin_url" in
    git@github.com:*) ssh_url="$origin_url" ;;
    https://github.com/*)
      repo_path="${origin_url#https://github.com/}"; repo_path="${repo_path%.git}"; repo_path="${repo_path%/}"
      ssh_url="git@github.com:${repo_path}.git" ;;
    *) die "cannot derive the GitHub ssh URL from origin '$origin_url'; set VIVEK_REPO_SSH=git@github.com:OWNER/REPO.git" ;;
  esac
fi
repo_path="${ssh_url#git@github.com:}"; repo_path="${repo_path%.git}"
https_url="https://github.com/$repo_path"
for pair in "$app:" "$publish:--filter=blob:none"; do
  dir="${pair%%:*}"; flt="${pair#*:}"
  if [ ! -e "$dir/.git" ]; then
    echo "    cloning $https_url -> $dir ${flt:+($flt)} (2.4 GB history: this takes a while)"
    # The first clone goes over https (no key registered yet); the remote is
    # then switched to ssh so every later fetch/push uses the deploy key.
    # shellcheck disable=SC2086
    as_vivek5 git clone -q $flt --branch main "$https_url" "$dir" || die "clone failed - if the repo is private, register the deploy key printed below first, then re-run"
  fi
  as_vivek5 git -C "$dir" remote set-url origin "$ssh_url"
  as_vivek5 git -C "$dir" config gc.auto 0
  as_vivek5 git -C "$dir" config advice.detachedHead false
  git config --system --get-all safe.directory 2>/dev/null | grep -qx "$dir" || git config --system --add safe.directory "$dir"
done
echo "    ok"

log "venv + requirements (exact pins) + compileall"
[ -x "$venv/bin/python" ] || as_vivek5 python3 -m venv "$venv"
as_vivek5 "$venv/bin/pip" install -q -r "$app/requirements.txt"
as_vivek5 "$venv/bin/python" -m compileall -q "$venv/lib" >/dev/null 2>&1 || true
echo "    $("$venv/bin/python" --version) at $venv"

install_units

log "/etc/vivek5 env files (written ONLY if absent)"
install -d -m 0755 -o root -g root "$etc"
if [ ! -e "$etc/jobs.env" ]; then
  install -m 0640 -o root -g vivek5 "$kit/env/jobs.env.example" "$etc/jobs.env"
  echo "    wrote $etc/jobs.env from the template - EDIT ITS CHANGE_ME VALUES"
fi
chown root:vivek5 "$etc/jobs.env"; chmod 0640 "$etc/jobs.env"
if [ ! -e "$etc/api.env" ]; then
  tmp_env="$(mktemp)"
  token="$(openssl rand -hex 32)"
  sed -e "s|^DISPATCH_TOKEN=.*|DISPATCH_TOKEN=$token|" -e "s|^VIVEK_PHASE=.*|VIVEK_PHASE=$phase|" "$kit/env/api.env.example" > "$tmp_env"
  install -m 0640 -o root -g vivek5-api "$tmp_env" "$etc/api.env"
  rm -f "$tmp_env"
  echo "    wrote $etc/api.env with a generated DISPATCH_TOKEN (cutover step 2 copies it to Cloudflare)"
fi
chown root:vivek5-api "$etc/api.env"; chmod 0640 "$etc/api.env"

log "deploy key (ed25519, write access to this repo only)"
if [ ! -f "$etc/deploy_key" ]; then
  ssh-keygen -q -t ed25519 -N '' -C "vivek5-vps@$(hostname) deploy key" -f "$etc/deploy_key"
fi
chown root:vivek5 "$etc/deploy_key"; chmod 0640 "$etc/deploy_key"
chmod 0644 "$etc/deploy_key.pub"
cat <<KEYMSG
    Register this PUBLIC key on GitHub, WITH write access:
      https://github.com/$repo_path/settings/keys -> Add deploy key
      title: vivek5-vps $(hostname)   [x] Allow write access

$(cat "$etc/deploy_key.pub")

    (root:vivek5 0640: ssh's permission check applies only to keys the
    caller owns, so the jobs user can read it and nobody else can.)
KEYMSG

log "github.com host keys -> $etc/known_hosts"
if [ ! -s "$etc/known_hosts" ]; then
  ssh-keyscan -t ed25519,ecdsa,rsa github.com > "$etc/known_hosts" 2>/dev/null || die "ssh-keyscan github.com failed (no egress on :22?)"
fi
chmod 0644 "$etc/known_hosts"
echo "    VERIFY these fingerprints against https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints"
ssh-keygen -lf "$etc/known_hosts" | sed 's/^/      /'
echo "    (a mismatch means someone is between this box and GitHub: delete the file and stop)"

log "journald cap (2G / 45 days)"
install -d -m 0755 /etc/systemd/journald.conf.d
if ! cmp -s "$kit/journald.conf" /etc/systemd/journald.conf.d/vivek5.conf 2>/dev/null; then
  install -m 0644 -o root -g root "$kit/journald.conf" /etc/systemd/journald.conf.d/vivek5.conf
  systemctl restart systemd-journald >/dev/null 2>&1 || true
fi
echo "    ok"

log "sudoers.d/vivek5 (exactly two commands)"
tmp_sudo="$(mktemp)"
cat > "$tmp_sudo" <<'SUDO'
# Vivek 5.0: update.sh restarts the API adapter when functions/ or deploy/api/
# change; the operator (as vivek5) may reload Caddy. Nothing else.
vivek5 ALL=(root) NOPASSWD: /usr/bin/systemctl restart vivek5-api.service, /usr/bin/systemctl reload caddy
SUDO
visudo -cf "$tmp_sudo" >/dev/null || die "generated sudoers file failed visudo -c"
install -m 0440 -o root -g root "$tmp_sudo" /etc/sudoers.d/vivek5
rm -f "$tmp_sudo"
echo "    ok"

log "box clock: Etc/UTC + NTP"
timedatectl set-timezone Etc/UTC 2>/dev/null || echo "    WARNING: timedatectl set-timezone failed (container?) - the box MUST run on UTC"
systemctl enable --now systemd-timesyncd >/dev/null 2>&1 || true
echo "    $(timedatectl show -p Timezone --value 2>/dev/null || echo '?') / NTPSynchronized=$(timedatectl show -p NTPSynchronized --value 2>/dev/null || echo '?')"

install_caddy_config

cat <<DONE

install.sh finished. Next:
  1. edit $etc/jobs.env  (every CHANGE_ME: alert channel, morning-plays webhook)
     edit /etc/caddy/vivek5.env (VIVEK_DOMAIN; Phase 2 also the basic-auth hash)
  2. register the deploy key printed above, then re-run: sudo deploy/bin/install.sh --units
  3. sudo $app/deploy/bin/preflight.sh [--measure]   until every line is PASS
  4. GH_ADMIN_TOKEN=... sudo -E $app/deploy/bin/cutover.sh
DONE
