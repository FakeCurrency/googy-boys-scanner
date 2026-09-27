#!/usr/bin/env bash
# deploy/bin/install.sh -- prepare an Ubuntu 24.04 box for Vivek 5.0 BESIDE
# whatever else it already runs (deploy/DESIGN.md 1, D1/D7/D9, M6). ROOT,
# IDEMPOTENT, and it runs FROM A ROOT-OWNED CHECKOUT, never `curl | bash`:
#
#     sudo git clone https://github.com/FakeCurrency/googy-boys-scanner /usr/local/src/vivek5
#     sudo /usr/local/src/vivek5/deploy/bin/install.sh [--phase 1|2] [--yes] [--with-swap]
#     sudo /usr/local/src/vivek5/deploy/bin/install.sh --units [--phase 1|2] [--yes]
#
# COEXISTENCE: this box also runs the owner's trading bots (ICT LIVE trades
# REAL money). install.sh prints every system-wide change it is about to make
# and waits for you to type `yes` (or pass --yes). It NEVER: changes the
# timezone, installs/replaces the system node, installs the distro caddy or
# touches caddy.service, configures a firewall, creates swap (unless you pass
# --with-swap), installs a journald drop-in, or stops/restarts anything that is
# not vivek5-*. It STARTS NOTHING: no timer, no service, no path unit --
# cutover.sh starts the vivek5-* units after a green preflight.
#
# --units re-copies the unit files, the root-owned operator kit and the
# Caddyfile only (run it after update.sh reports deploy/ changed: first
# `sudo git -C /usr/local/src/vivek5 pull`, then this). A CHANGED long-running
# unit (vivek5-api/-caddy, a .path, a .timer) is try-restarted -- restarted
# only if it is ALREADY running; it enables and starts nothing.
# --with-swap (with or without --units) adds a 4G /swapfile + fstab line +
# vm.swappiness=10, only when the box has no swap at all.
# No `set -x` anywhere in deploy/bin (test-pinned).
set -euo pipefail

# Vendored runtimes: pinned, checksum-verified, installed under /opt/vivek5
# and used ONLY by the vivek5-* units. Bump a version and its hash together.
NODE_VERSION=22.23.3        # Node 22 LTS (Jod), linux-x64 tarball from nodejs.org
NODE_SHA256=df450af89261115ef9f9e3830c3eeb2cc9213b63c720b1af623cb5dcbe2e02de
CADDY_VERSION=2.10.2        # >= 2.8 (basic_auth, handle_errors <status>)
CADDY_SHA512=747df7ee74de188485157a383633a1a963fd9233b71fbb4a69ddcbcc589ce4e2cc82dacf5dbbe136cb51d17e14c59daeb5d9bc92487610b0f3b93680b2646546
# github.com's PUBLISHED ssh host-key fingerprints (RSA, ECDSA, Ed25519 --
# docs.github.com "GitHub's SSH key fingerprints"; DSA is retired and never
# scanned). ssh-keyscan is trust-on-first-use; this turns it into a check:
# every key it returns must be one of these or install.sh refuses. Same list
# in preflight.sh (test-pinned). If GitHub rotates a key, update both.
GITHUB_FPS="SHA256:uNiVztksCsDhcc0u9e8BujQXVUpKZIDTMczCvj3tD2s SHA256:p2QAMXNIC1TJYWeIOttrVc98/R1BUFWu3/LiyKgUfQM SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU"

app=/opt/vivek5/app
publish=/opt/vivek5/publish
venv=/opt/vivek5/venv
state=/opt/vivek5/state
node_dir=/opt/vivek5/node
caddy_home=/opt/vivek5/caddy
caddy_bin=$caddy_home/caddy
etc=/etc/vivek5
opkit=/usr/local/lib/vivek5

phase=""
units_only=0
assume_yes=0
with_swap=0
usage() { sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; }
log()  { printf '\n==> %s\n' "$*"; }
die()  { printf 'install.sh: %s\n' "$*" >&2; exit 1; }
while [ $# -gt 0 ]; do
  case "$1" in
    --phase) [ $# -ge 2 ] || die "--phase needs a value (1 or 2)"; phase="$2"; shift 2 ;;
    --phase=*) phase="${1#*=}"; shift ;;
    --units) units_only=1; shift ;;
    --yes) assume_yes=1; shift ;;
    --with-swap) with_swap=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "install.sh: unknown argument '$1'" >&2; usage >&2; exit 2 ;;
  esac
done

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

[ "$(id -u)" -eq 0 ] || die "run as root: sudo deploy/bin/install.sh"
refuse_unsafe_path
here="$(cd "$(dirname "$0")" && pwd)"
kit="$(cd "$here/.." && pwd)"
src_repo="$(cd "$kit/.." && pwd)"
[ -f "$kit/DESIGN.md" ] || die "cannot find deploy/DESIGN.md next to this script - run it from a checkout"
git -C "$src_repo" rev-parse --git-dir >/dev/null 2>&1 || die "$src_repo is not a git checkout - clone the repo (as root) and run deploy/bin/install.sh from it, not from a pipe"
# Every path below is absolute. Leave root's cwd (often /root, 0700): the
# `sudo -u vivek5` git/pip/python calls must not start in a directory the
# jobs user cannot enter.
cd /

# The phase defaults to whatever the installed api.env says, so a bare
# `--units` re-run can never downgrade a Phase 2 box to the Phase 1 Caddyfile.
env_get() {  # <file> <KEY>: the raw value, as systemd's EnvironmentFile reads it (no shell expansion)
  sed -n "s/^$2=//p" "$1" 2>/dev/null | tail -1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}
if [ -z "$phase" ] && [ -r "$etc/api.env" ]; then
  phase="$(env_get "$etc/api.env" VIVEK_PHASE)"
fi
phase="${phase:-1}"
case "$phase" in 1|2) ;; *) die "--phase must be 1 or 2 (got '$phase')" ;; esac

# ---- the plan, printed BEFORE anything changes (M6 C12) ---------------------
if [ "$units_only" = "1" ]; then
  cat <<PLAN

install.sh --units will make these system-wide changes (nothing else):
  * copy deploy/systemd/vivek5-*.{service,timer,path} into /etc/systemd/system
    (removing vivek5-* units no longer in the checkout) + systemctl daemon-reload.
    Nothing is enabled or started; vivek5-api / vivek5-caddy are restarted
    ONLY if they are already running.
  * refresh the root-owned operator kit in $opkit
  * write $etc/Caddyfile (phase $phase) and create $etc/caddy.env if absent
  * remove /etc/sudoers.d/vivek5 if an EARLIER version of this kit wrote it
    (only a file carrying this kit's header; no sudo grant is used any more)
PLAN
  if [ "$with_swap" = "1" ]; then
    echo "  * --with-swap: /swapfile (4G) + an /etc/fstab line + /etc/sysctl.d/99-vivek5-swap.conf (vm.swappiness=10), only if the box has no swap"
  fi
else
  cat <<PLAN

install.sh will make these system-wide changes, and NOTHING else:
  * apt-get install: git rsync curl ca-certificates openssl python3.12-venv
    python3-pip sudo openssh-client xz-utils tzdata iproute2 procps
    (never nodejs, never caddy)
  * system users vivek5 (jobs), vivek5-api (API adapter), vivek5-caddy (TLS
    front door) and group vivek5-spool (vivek5 + vivek5-api are members)
  * NO sudo grant for any vivek5 user: /etc/sudoers.d/vivek5 is REMOVED if an
    earlier version of this kit wrote it (update.sh asks the root-owned
    vivek5-api-restart.path to restart the API instead)
  * /opt/vivek5: app + publish clones, venv, state/, node/ (pinned Node
    $NODE_VERSION, checksum-verified), caddy/ (pinned Caddy $CADDY_VERSION, checksum-verified)
  * /etc/vivek5: jobs.env, api.env, caddy.env, Caddyfile, deploy_key, known_hosts
  * $opkit: a root-owned copy of preflight/cutover/rollback/ports + the unit files
  * vivek5-* unit files copied into /etc/systemd/system + daemon-reload.
    They are NOT enabled and NOT started -- cutover.sh does that later
    (the one root unit, vivek5-api-restart.service, runs exactly
    'systemctl try-restart vivek5-api.service' when update.sh asks).
PLAN
  if [ "$with_swap" = "1" ]; then
    echo "  * --with-swap: /swapfile (4G) + an /etc/fstab line + /etc/sysctl.d/99-vivek5-swap.conf (vm.swappiness=10), only if the box has no swap"
  fi
  cat <<PLAN
  Left alone: the timezone, the system node, the distro caddy / caddy.service,
  the firewall, journald, swap (without --with-swap), and every non-vivek5 unit.
PLAN
fi
if [ "$assume_yes" != "1" ]; then
  reply=""
  read -r -p "Type yes to make these changes: " reply || true
  [ "$reply" = "yes" ] || die "not confirmed (type the word yes, or pass --yes) - nothing was changed"
fi

as_vivek5() { sudo -u vivek5 -H "$@"; }

# Earlier kits granted vivek5 `sudo systemctl restart vivek5-api.service` for
# update.sh -- which could never use it (NoNewPrivileges=yes forbids setuid).
# Remove OUR file only: it must carry the header this kit wrote.
remove_stale_sudoers() {  # [path] (the tests pass a temp file; the box never does)
  local f="${1:-/etc/sudoers.d/vivek5}"
  [ -e "$f" ] || return 0
  if grep -q '^# Vivek 5.0: update.sh restarts the API adapter' "$f"; then
    rm -f "$f"
    echo "    removed $f (an earlier kit's grant; nothing uses sudo any more)"
  else
    echo "    WARNING: $f exists but was not written by this kit - left alone; review it by hand"
  fi
}

add_swap() {
  log "--with-swap: 4G /swapfile (only when the box has no swap)"
  if [ -n "$(swapon --show --noheadings 2>/dev/null)" ]; then
    echo "    swap is already active - nothing added:"
    swapon --show | sed 's/^/      /'
  else
    if [ ! -f /swapfile ]; then
      fallocate -l 4G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=4096 status=none
      chmod 0600 /swapfile
      mkswap /swapfile >/dev/null
    fi
    swapon /swapfile
    grep -qE '^/swapfile[[:space:]]' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    printf '# Vivek 5.0 install.sh --with-swap\nvm.swappiness=10\n' > /etc/sysctl.d/99-vivek5-swap.conf
    sysctl -q -w vm.swappiness=10
    echo "    /swapfile 4G active, in /etc/fstab, vm.swappiness=10"
  fi
}

install_operator_kit() {
  log "operator kit -> $opkit (root-owned; run preflight / cutover / rollback from HERE)"
  install -d -m 0755 -o root -g root "$opkit" "$opkit/bin" "$opkit/systemd" "$opkit/caddy"
  local s f
  for s in preflight.sh cutover.sh rollback.sh ports.sh; do
    install -m 0755 -o root -g root "$here/$s" "$opkit/bin/$s"
  done
  find "$opkit/systemd" -maxdepth 1 -type f -name 'vivek5-*' -delete
  for f in "$kit"/systemd/vivek5-*; do install -m 0644 -o root -g root "$f" "$opkit/systemd/"; done
  for f in "$kit"/caddy/Caddyfile.phase*; do install -m 0644 -o root -g root "$f" "$opkit/caddy/"; done
  install -m 0644 -o root -g root "$kit/DESIGN.md" "$opkit/DESIGN.md"
  printf '%s\n' "$src_repo" > "$opkit/SOURCE"
  chmod 0644 "$opkit/SOURCE"
  echo "    ok (source: $src_repo)"
}

install_units() {
  log "units -> /etc/systemd/system (copied, never symlinked; NOT enabled, NOT started)"
  local f b changed=()
  for f in "$kit"/systemd/vivek5-*; do
    b="$(basename "$f")"
    cmp -s "$f" "/etc/systemd/system/$b" || changed+=("$b")
    install -m 0644 -o root -g root "$f" /etc/systemd/system/
  done
  for f in /etc/systemd/system/vivek5-*; do
    [ -f "$f" ] || continue
    b="$(basename "$f")"
    if [ ! -e "$kit/systemd/$b" ]; then
      echo "    removing stale unit $b (no longer in deploy/systemd)"
      v5ctl disable --now "$b" >/dev/null 2>&1 || true
      rm -f "$f"
    fi
  done
  systemctl daemon-reload
  # A changed long-running unit picks up its new definition only on a
  # restart: try-restart = restart it IF it is already running (after
  # cutover), nothing at all before cutover (C7). Never a oneshot job unit --
  # that would kill a running scan; they read the new file at their next start.
  for b in "${changed[@]}"; do
    case "$b" in
      vivek5-api.service|vivek5-caddy.service|vivek5-*.path|vivek5-*.timer)
        v5ctl try-restart "$b" >/dev/null 2>&1 || true
        echo "    changed: $b (try-restarted: only if it was running)" ;;
      *) echo "    changed: $b" ;;
    esac
  done
  rm -f "$state/UNITS_STALE"
  echo "    $(ls "$kit"/systemd/vivek5-* | wc -l) unit files installed; cutover.sh enables and starts them, not this script"
  install_operator_kit
}

install_caddy_config() {
  log "Caddy config (phase $phase) -> $etc/Caddyfile + $etc/caddy.env (OUR Caddy only)"
  getent group vivek5-caddy >/dev/null || die "user/group vivek5-caddy is missing - run the full install.sh once (without --units)"
  install -d -m 0755 -o root -g root "$etc"
  if [ ! -e "$etc/caddy.env" ]; then
    cat > "$etc/caddy.env" <<'CENV'
# /etc/vivek5/caddy.env -- environment for vivek5-caddy.service ONLY (the
# Caddyfile's {$...} placeholders). systemd reads it with EnvironmentFile=,
# which does NOT shell-expand: paste values raw, including a bcrypt hash.
# The hostname that points at this box. REQUIRED for both phases (D7).
VIVEK_DOMAIN=CHANGE_ME
# Phase 2 only: HTTP basic auth for POST /api/scan and /api/close. Make the
# hash interactively (the password never lands in shell history or ps):
#   /opt/vivek5/caddy/caddy hash-password
VIVEK_API_BASIC_USER=vivek
VIVEK_API_BASIC_HASH=CHANGE_ME
CENV
  fi
  chown root:vivek5-caddy "$etc/caddy.env"
  chmod 0640 "$etc/caddy.env"
  install -m 0644 -o root -g root "$kit/caddy/Caddyfile.phase$phase" "$etc/Caddyfile"
  local domain hash
  domain="$(env_get "$etc/caddy.env" VIVEK_DOMAIN)"
  hash="$(env_get "$etc/caddy.env" VIVEK_API_BASIC_HASH)"
  if [ -z "$domain" ] || [ "$domain" = "CHANGE_ME" ]; then
    echo "    Caddyfile not validated yet: set VIVEK_DOMAIN in $etc/caddy.env, then re-run --units"
    return 0
  fi
  if [ "$phase" = "2" ] && { [ -z "$hash" ] || [ "$hash" = "CHANGE_ME" ]; }; then
    echo "    Caddyfile not validated yet: Phase 2 needs VIVEK_API_BASIC_HASH in $etc/caddy.env, then re-run --units"
    return 0
  fi
  if [ ! -x "$caddy_bin" ]; then
    echo "    $caddy_bin not installed yet (a full install.sh run vendors it) - not validated"
    return 0
  fi
  # --envfile, never `. caddy.env`: bash would expand the `$2a$14$...` hash.
  if "$caddy_bin" validate --adapter caddyfile --config "$etc/Caddyfile" --envfile "$etc/caddy.env" >/dev/null 2>&1; then
    echo "    Caddyfile.phase$phase validated for $domain"
    # reload only if it is ALREADY running (cutover.sh is what starts it)
    v5ctl try-reload-or-restart vivek5-caddy.service >/dev/null 2>&1 || true
  else
    die "caddy validate failed on $etc/Caddyfile (phase $phase) - fix $etc/caddy.env and re-run --units"
  fi
}

if [ "$units_only" = "1" ]; then
  install_units
  install_caddy_config
  remove_stale_sudoers
  if [ "$with_swap" = "1" ]; then add_swap; fi
  if [ -r "$etc/api.env" ] && ! grep -q "^VIVEK_PHASE=$phase\$" "$etc/api.env"; then
    sed -i "s/^VIVEK_PHASE=.*/VIVEK_PHASE=$phase/" "$etc/api.env"
    v5ctl try-restart vivek5-api.service >/dev/null 2>&1 || true
    echo "    api.env VIVEK_PHASE set to $phase (adapter restarted only if it was running)"
  fi
  exit 0
fi

# ---------------------------------------------------------------------------
log "OS"
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  echo "    ${PRETTY_NAME:-unknown}"
  if [ "${ID:-}" != "ubuntu" ] || [ "${VERSION_ID:-}" != "24.04" ]; then
    echo "    WARNING: this kit is written and tested for Ubuntu 24.04 (python3.12, systemd 255)"
  fi
fi
[ "$(uname -m)" = "x86_64" ] || die "this kit vendors linux x86_64 builds of Node and Caddy; uname -m says $(uname -m)"

log "TCP listeners already on this box (INFO; nothing is touched)"
"$here/ports.sh" || true

log "apt packages (never nodejs, never caddy)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3.12-venv python3-pip git rsync curl ca-certificates openssl tzdata sudo openssh-client xz-utils iproute2 procps >/dev/null
echo "    ok"

fetch() { curl -fsSL --retry 3 --max-time 600 -o "$2" "$1"; }

log "Node $NODE_VERSION -> $node_dir (pinned + SHASUMS256-verified; the system node is left alone)"
have=""
[ -x "$node_dir/bin/node" ] && have="$("$node_dir/bin/node" --version 2>/dev/null || true)"
if [ "$have" != "v$NODE_VERSION" ]; then
  tmp="$(mktemp -d)"
  tarball="node-v${NODE_VERSION}-linux-x64.tar.xz"
  fetch "https://nodejs.org/dist/v${NODE_VERSION}/${tarball}" "$tmp/$tarball"
  fetch "https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt" "$tmp/SHASUMS256.txt"
  ( cd "$tmp" && grep -E "  ${tarball}\$" SHASUMS256.txt | sha256sum -c --status - ) \
    || die "the Node tarball does not match the release's SHASUMS256.txt - not installed"
  [ "$(sha256sum "$tmp/$tarball" | cut -d' ' -f1)" = "$NODE_SHA256" ] \
    || die "the Node tarball does not match the pinned NODE_SHA256 - not installed"
  rm -rf "$node_dir.new"
  install -d -m 0755 -o root -g root "$node_dir.new"
  tar -xJf "$tmp/$tarball" -C "$node_dir.new" --strip-components=1 --no-same-owner
  chown -R root:root "$node_dir.new"
  chmod -R go-w "$node_dir.new"
  rm -rf "$node_dir.old"
  if [ -e "$node_dir" ]; then mv "$node_dir" "$node_dir.old"; fi
  mv "$node_dir.new" "$node_dir"
  rm -rf "$node_dir.old" "$tmp"
fi
echo "    $("$node_dir/bin/node" --version) at $node_dir/bin/node (used only by vivek5-api.service)"

log "Caddy $CADDY_VERSION -> $caddy_bin (pinned + checksums-verified; the distro caddy and caddy.service are left alone)"
have=""
[ -x "$caddy_bin" ] && have="$("$caddy_bin" version 2>/dev/null | awk '{print $1}')"
if [ "$have" != "v$CADDY_VERSION" ]; then
  tmp="$(mktemp -d)"
  tarball="caddy_${CADDY_VERSION}_linux_amd64.tar.gz"
  sums="caddy_${CADDY_VERSION}_checksums.txt"
  base="https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}"
  fetch "$base/$tarball" "$tmp/$tarball"
  fetch "$base/$sums" "$tmp/$sums"
  ( cd "$tmp" && grep -E "  ${tarball}\$" "$sums" | sha512sum -c --status - ) \
    || die "the Caddy tarball does not match the release's checksums file - not installed"
  [ "$(sha512sum "$tmp/$tarball" | cut -d' ' -f1)" = "$CADDY_SHA512" ] \
    || die "the Caddy tarball does not match the pinned CADDY_SHA512 - not installed"
  tar -xzf "$tmp/$tarball" -C "$tmp" caddy
  install -d -m 0755 -o root -g root "$caddy_home"
  install -m 0755 -o root -g root "$tmp/caddy" "$caddy_bin"
  rm -rf "$tmp"
fi
echo "    $("$caddy_bin" version | awk '{print $1}') at $caddy_bin (used only by vivek5-caddy.service)"

log "users vivek5, vivek5-api, vivek5-caddy, group vivek5-spool"
# Idempotent, and explicit about the primary group (never left to
# login.defs' USERGROUPS_ENAB): a same-named group left behind by an earlier
# half-run is reused instead of failing `useradd --user-group`.
mkuser() {  # <name> <home>
  id -u "$1" >/dev/null 2>&1 && return 0
  if getent group "$1" >/dev/null; then
    useradd --system --gid "$1" --home-dir "$2" --no-create-home --shell /usr/sbin/nologin "$1"
  else
    useradd --system --user-group --home-dir "$2" --no-create-home --shell /usr/sbin/nologin "$1"
  fi
}
getent group vivek5-spool >/dev/null || groupadd --system vivek5-spool
mkuser vivek5 "$state/home"
mkuser vivek5-api /nonexistent
mkuser vivek5-caddy "$caddy_home"
# BOTH sides of the spool: the adapter (vivek5-api) writes it, the runner
# (vivek5) reads and moves it. Without vivek5 in the group every dispatch the
# adapter answered 202 for was unreadable to the drainer (security review).
usermod -aG vivek5-spool vivek5-api
usermod -aG vivek5-spool vivek5
# No global systemd-journal membership: vivek5-failed@.service carries
# SupplementaryGroups=systemd-journal for its own journalctl call.
echo "    ok"

log "layout under /opt/vivek5"
install -d -m 0755 -o root -g root /opt/vivek5
install -d -m 0755 -o vivek5 -g vivek5 "$app" "$publish" "$venv"
# state/ is readable by the adapter (group vivek5-spool: /api/vps reads
# runs.json + HALT) and writable only by the runner. spool/ is the one tree
# both write: setgid (the group sticks) + STICKY (the adapter can rename only
# its own entries, never the runner's done/ or failed/).
install -d -m 2750 -o vivek5 -g vivek5-spool "$state"
install -d -m 3770 -o vivek5 -g vivek5-spool "$state/spool" "$state/spool/.tmp"
install -d -m 2750 -o vivek5 -g vivek5-spool "$state/spool/done" "$state/spool/failed"
install -d -m 0750 -o vivek5 -g vivek5 "$state/locks" "$state/summaries" "$state/home" "$state/cache" "$state/tmp"
if [ ! -e "$state/kv.json" ]; then
  echo '{}' > "$state/kv.json"
fi
chown vivek5-api:vivek5-spool "$state/kv.json"
chmod 0660 "$state/kv.json"
# The flag update.sh writes and vivek5-api-restart.path watches. Created here
# (not by the first request) so every request is a plain write to an existing
# file the path unit already watches.
[ -e "$state/api-restart" ] || install -m 0644 -o vivek5 -g vivek5-spool /dev/null "$state/api-restart"
install -d -m 0700 -o vivek5-caddy -g vivek5-caddy "$caddy_home/data" "$caddy_home/config"
echo "    ok"

log "GitHub remote"
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
echo "    $ssh_url"

# The deploy key and the host keys come BEFORE the clones: a private repo
# can only be cloned over ssh with the key, and the key must be printed on
# the run that fails (it used to be generated after the clone died).
install -d -m 0755 -o root -g root "$etc"
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
  ssh-keyscan -t ed25519,ecdsa,rsa github.com > "$etc/known_hosts" 2>/dev/null || true
  [ -s "$etc/known_hosts" ] || { rm -f "$etc/known_hosts"; die "ssh-keyscan github.com returned no host key (no egress on :22?) - nothing to verify, not written"; }
fi
chmod 0644 "$etc/known_hosts"
echo "    fingerprints (checked against GitHub's published set, https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints):"
ssh-keygen -lf "$etc/known_hosts" | sed 's/^/      /'
unknown_fp=""
while read -r _bits fp _rest; do
  case " $GITHUB_FPS " in *" $fp "*) ;; *) unknown_fp="$unknown_fp $fp" ;; esac
done < <(ssh-keygen -lf "$etc/known_hosts")
if [ -n "$unknown_fp" ]; then
  rm -f "$etc/known_hosts"
  die "github.com presented host key(s) GitHub does not publish:$unknown_fp - someone may be between this box and GitHub (or GitHub rotated a key: update GITHUB_FPS here and in preflight.sh from the docs page). known_hosts NOT kept."
fi
echo "    ok: every key is one GitHub publishes"

log "clones (app = full, publish = --filter=blob:none; both on the ssh remote)"
for pair in "$app:" "$publish:--filter=blob:none"; do
  dir="${pair%%:*}"; flt="${pair#*:}"
  if [ ! -e "$dir/.git" ]; then
    echo "    cloning $https_url -> $dir ${flt:+($flt)} (2.4 GB history: this takes a while)"
    # The first clone goes over https (a public repo needs no key yet); a
    # private one falls back to ssh with the deploy key printed above. Either
    # way the remote is then set to ssh, so every later fetch/push uses the key.
    # shellcheck disable=SC2086
    if ! as_vivek5 git clone -q $flt --branch main "$https_url" "$dir"; then
      rm -rf "$dir"; install -d -m 0755 -o vivek5 -g vivek5 "$dir"
      echo "    https clone failed - trying ssh with the deploy key"
      # shellcheck disable=SC2086
      as_vivek5 env GIT_SSH_COMMAND="ssh -i $etc/deploy_key -o IdentitiesOnly=yes -o UserKnownHostsFile=$etc/known_hosts -o StrictHostKeyChecking=yes -o BatchMode=yes" \
        git clone -q $flt --branch main "$ssh_url" "$dir" \
        || die "clone failed over https and ssh - register the deploy key printed above (with write access), then re-run"
    fi
  fi
  # Root never runs git in these vivek5-owned clones (no system-wide
  # safe.directory: that switched off git's ownership guard for root, and a
  # jobs-user core.fsmonitor then ran as root -- security review).
  as_vivek5 git -C "$dir" remote set-url origin "$ssh_url"
  as_vivek5 git -C "$dir" config gc.auto 0
  as_vivek5 git -C "$dir" config advice.detachedHead false
done
echo "    ok"

log "venv + requirements (exact pins) + compileall"
[ -x "$venv/bin/python" ] || as_vivek5 python3 -m venv "$venv"
as_vivek5 "$venv/bin/pip" install -q -r "$app/requirements.txt"
as_vivek5 "$venv/bin/python" -m compileall -q "$venv/lib" >/dev/null 2>&1 || true
echo "    $(as_vivek5 "$venv/bin/python" --version) at $venv"

install_units

log "/etc/vivek5 env files (written ONLY if absent)"
install -d -m 0755 -o root -g root "$etc"
if [ ! -e "$etc/jobs.env" ]; then
  # A HOST-SCOPED identity: a second box installed from the same template (a
  # rehearsal clone, a reinstall while the old box still runs) then reads as
  # a foreign writer to the second-writer check instead of passing silently.
  host="$(hostname -s 2>/dev/null | tr -cd 'A-Za-z0-9.-')"
  host="${host:-box}"
  tmp_env="$(mktemp)"
  sed -e "s|^GIT_AUTHOR_NAME=.*|GIT_AUTHOR_NAME=vivek5-vps@$host|" \
      -e "s|^GIT_COMMITTER_NAME=.*|GIT_COMMITTER_NAME=vivek5-vps@$host|" "$kit/env/jobs.env.example" > "$tmp_env"
  install -m 0640 -o root -g vivek5 "$tmp_env" "$etc/jobs.env"
  rm -f "$tmp_env"
  echo "    wrote $etc/jobs.env from the template (identity vivek5-vps@$host) - EDIT ITS CHANGE_ME VALUES"
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

log "sudo: no grant for any vivek5 user"
remove_stale_sudoers
echo "    ok"

if [ "$with_swap" = "1" ]; then add_swap; fi

install_caddy_config

cat <<DONE

install.sh finished. NOTHING was started. Next:
  1. edit $etc/jobs.env   (every CHANGE_ME: alert channel, morning-plays webhook)
     edit $etc/caddy.env  (VIVEK_DOMAIN; Phase 2 also the basic-auth hash)
  2. register the deploy key printed above, then re-run:
       sudo $src_repo/deploy/bin/install.sh --units
  3. sudo $opkit/bin/preflight.sh [--measure]      until every line is PASS
  4. sudo $opkit/bin/cutover.sh                    (it prompts for GH_ADMIN_TOKEN;
     never type a token on the command line -- it lands in shell history)
DONE
