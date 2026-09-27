#!/usr/bin/env bash
# deploy/bin/preflight.sh -- every check of deploy/DESIGN.md 7 step 0, each
# printed as PASS / FAIL / WARN / INFO with the exact remedy. Exits 1 on any
# FAIL. cutover.sh refuses to start unless this is green. READ-ONLY: it
# changes nothing on the box (no unit is started, stopped or reconfigured).
#
#     sudo /usr/local/lib/vivek5/bin/preflight.sh [--measure]
#
# --measure additionally runs a DRY ASX scan (--limit 40, VIVEK_GIT_PUBLISH=0)
# in a throw-away git worktree and prints its max RSS, for sizing the box.
#
# The alert-channel check is a FAIL unless VIVEK_ACCEPT_NO_ALERT_CHANNEL=1 is
# set in the calling shell, in which case it is a loud WARN (D8: cutover
# deletes GitHub's red-run email, the last alarm; a silent VPS is a design
# failure, not a config gap).
#
# COEXISTENCE (M6): this box also runs the owner's trading bots. Machine-wide
# facts they depend on (the timezone, the firewall, the journal, other TCP
# listeners) are printed as INFO and never changed. Root never executes a
# file the jobs user can write: every venv/checkout python runs AS vivek5 with
# a clean environment, and anything that needs the jobs' secrets runs through
# systemd-run with the units' own EnvironmentFile= parser (no `. jobs.env`:
# bash would expand a `$` in a password). No `set -x` in deploy/bin (pinned).
set -uo pipefail   # deliberately no -e: every check must run and report

measure=0
for a in "$@"; do
  case "$a" in
    --measure) measure=1 ;;
    -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "preflight.sh: unknown argument '$a'" >&2; exit 2 ;;
  esac
done

die()  { printf 'preflight.sh: %s\n' "$*" >&2; exit 1; }
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
[ "$(id -u)" -eq 0 ] || die "run as root: sudo /usr/local/lib/vivek5/bin/preflight.sh"
refuse_unsafe_path

here="$(cd "$(dirname "$0")" && pwd)"
kit="$(cd "$here/.." && pwd)"
etc=/etc/vivek5
node_bin=/opt/vivek5/node/bin/node
caddy_bin=/opt/vivek5/caddy/caddy
fails=0; warns=0
# github.com's PUBLISHED ssh host-key fingerprints -- identical to install.sh's
# GITHUB_FPS (test-pinned); a known_hosts key outside this set is a FAIL.
GITHUB_FPS="SHA256:uNiVztksCsDhcc0u9e8BujQXVUpKZIDTMczCvj3tD2s SHA256:p2QAMXNIC1TJYWeIOttrVc98/R1BUFWu3/LiyKgUfQM SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU"
pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n      remedy: %s\n' "$1" "$2"; fails=$((fails + 1)); }
warn() { printf 'WARN  %s\n      note:   %s\n' "$1" "$2"; warns=$((warns + 1)); }
info() { printf 'INFO  %s\n' "$1"; }
vermaj() { sed -E 's/^[^0-9]*([0-9]+).*/\1/'; }
env_get() {  # <file> <KEY>: the raw value, as systemd's EnvironmentFile reads it (no shell expansion)
  sed -n "s/^$2=//p" "$1" 2>/dev/null | tail -1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

# ---- 0. environment (read key by key, never sourced) -----------------------
[ -r "$etc/jobs.env" ] || fail "$etc/jobs.env is not readable" "run the full install.sh first"
vivek_home="$(env_get "$etc/jobs.env" VIVEK_HOME)"; vivek_home="${vivek_home:-/opt/vivek5/app}"
publish="$(env_get "$etc/jobs.env" VIVEK_PUBLISH)"; publish="${publish:-/opt/vivek5/publish}"
venv="$(env_get "$etc/jobs.env" VIVEK_VENV)"; venv="${venv:-/opt/vivek5/venv}"
state_dir="$(env_get "$etc/jobs.env" VIVEK_STATE_DIR)"; state_dir="${state_dir:-/opt/vivek5/state}"
domain="$(env_get "$etc/caddy.env" VIVEK_DOMAIN)"
api_phase="$(env_get "$etc/api.env" VIVEK_PHASE)"; api_phase="${api_phase:-1}"
py="$venv/bin/python"

# Anything from the venv or the checkout runs AS vivek5 with a clean env.
as_vivek5_clean() {
  sudo -u vivek5 -H env -i -C "$vivek_home" PATH=/usr/local/bin:/usr/bin:/bin \
    HOME="$state_dir/home" TZ=UTC LANG=C.UTF-8 "$@"
}
# Exactly the job units' environment: systemd parses jobs.env itself.
as_job() {
  systemd-run --quiet --wait --pipe --collect --unit="vivek5-preflight-$$-$RANDOM" \
    -p User=vivek5 -p EnvironmentFile="$etc/jobs.env" -p Environment=TZ=UTC \
    -p WorkingDirectory="$vivek_home" -- "$@"
}

echo "Vivek 5.0 VPS preflight  $(date -u +%Y-%m-%dT%H:%M:%SZ)  host=$(hostname)"
echo

# ---- 1. OS / clock / resources ----------------------------------------------
if [ -r /etc/os-release ]; then
  os_id="$(sed -n 's/^ID=//p' /etc/os-release | tr -d '"')"
  os_ver="$(sed -n 's/^VERSION_ID=//p' /etc/os-release | tr -d '"')"
  os_name="$(sed -n 's/^PRETTY_NAME=//p' /etc/os-release | tr -d '"')"
  if [ "$os_id" = "ubuntu" ] && [ "$os_ver" = "24.04" ]; then pass "Ubuntu 24.04 ($os_name)"
  else fail "OS is ${os_name:-unknown}, kit is for Ubuntu 24.04" "use an Ubuntu 24.04 image (python3.12 + systemd 255 are what the kit is tested on)"; fi
else
  fail "/etc/os-release missing" "use Ubuntu 24.04"
fi
tz="$(timedatectl show -p Timezone --value 2>/dev/null || echo '?')"
ntp="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || echo '?')"
info "system timezone: $tz (left as it is -- other services on this box may depend on it; every vivek5-* unit runs with TZ=UTC)"
if [ "$ntp" = "yes" ]; then pass "NTP synchronized"; else fail "NTPSynchronized=$ntp: the market windows and the second-writer timestamps need a true clock" "enable time sync (timedatectl set-ntp true -- machine-wide: make sure nothing else on the box manages the clock), wait a minute, re-run"; fi
mem_total_kb="$(sed -n 's/^MemTotal:[[:space:]]*\([0-9]*\).*/\1/p' /proc/meminfo 2>/dev/null)"
mem_avail_kb="$(sed -n 's/^MemAvailable:[[:space:]]*\([0-9]*\).*/\1/p' /proc/meminfo 2>/dev/null)"
swap_total_kb="$(sed -n 's/^SwapTotal:[[:space:]]*\([0-9]*\).*/\1/p' /proc/meminfo 2>/dev/null)"
mem_total_mb=$(( ${mem_total_kb:-0} / 1024 )); mem_avail_mb=$(( ${mem_avail_kb:-0} / 1024 )); swap_mb=$(( ${swap_total_kb:-0} / 1024 ))
info "RAM total ${mem_total_mb} MiB, available ${mem_avail_mb} MiB, swap ${swap_mb} MiB"
if [ "$mem_total_mb" -lt 4096 ] && [ "$swap_mb" -eq 0 ]; then
  warn "RAM is ${mem_total_mb} MiB (< 4 GB; ${mem_avail_mb} MiB free) and NO swap is active" "a full ASX scan beside the trading bots can run the box out of memory; sudo <source>/deploy/bin/install.sh --units --with-swap adds a 4G /swapfile (your call: it is machine-wide)"
fi
cpus="$(nproc 2>/dev/null || echo 1)"
if [ "$cpus" -lt 2 ]; then
  warn "$cpus vCPU: the scans will compete with the live trading bot for the only core" "the heavy units yield (Nice=10, CPUWeight=20), but 2+ vCPUs is the comfortable size"
else
  pass "$cpus vCPUs"
fi

# ---- 2. toolchain (OUR node and caddy, never the system's) ------------------
if [ -x "$node_bin" ] && [ "$("$node_bin" --version | vermaj)" -ge 22 ]; then pass "vendored node $("$node_bin" --version) at $node_bin"
else fail "vendored node >= 22 missing at $node_bin" "sudo <source>/deploy/bin/install.sh (downloads the pinned Node 22 LTS, checksum-verified)"; fi
info "system node: $(command -v node >/dev/null 2>&1 && echo "$(command -v node) $(node --version 2>/dev/null)" || echo none) (never used or changed by this kit)"
if [ -x "$caddy_bin" ]; then
  cv="$("$caddy_bin" version | sed -E 's/^v?([0-9]+\.[0-9]+).*/\1/')"
  if python3 -c "import sys; a=tuple(int(x) for x in sys.argv[1].split('.')[:2]); sys.exit(0 if a>=(2,8) else 1)" "$cv"; then pass "vendored caddy $cv at $caddy_bin"; else fail "vendored caddy $cv < 2.8" "sudo <source>/deploy/bin/install.sh (pins a Caddy >= 2.8 release)"; fi
else
  fail "vendored caddy missing at $caddy_bin" "sudo <source>/deploy/bin/install.sh"
fi
info "system caddy: $(command -v caddy >/dev/null 2>&1 && command -v caddy || echo none); caddy.service unit file: $(ls /etc/systemd/system/caddy.service /lib/systemd/system/caddy.service /usr/lib/systemd/system/caddy.service 2>/dev/null | head -1 || true)$( [ -e /lib/systemd/system/caddy.service ] || [ -e /usr/lib/systemd/system/caddy.service ] || [ -e /etc/systemd/system/caddy.service ] || echo none) (never used or changed by this kit)"
if [ -x "$py" ]; then
  pv="$(as_vivek5_clean "$py" --version 2>&1)"
  case "$pv" in "Python 3.12."*) pass "venv $pv" ;; *) fail "venv python is '$pv', need 3.12" "rm -rf $venv; sudo <source>/deploy/bin/install.sh" ;; esac
  pins_out="$(as_vivek5_clean "$py" - "$vivek_home/requirements.txt" <<'PY' 2>&1
import importlib, importlib.metadata as md, re, sys
pins = {}
for line in open(sys.argv[1], encoding="utf-8"):
    m = re.match(r"^\s*([A-Za-z0-9_.-]+)==([^\s#]+)", line)
    if m:
        pins[m.group(1).lower()] = m.group(2)
mods = {"pandas": "pandas", "numpy": "numpy", "yfinance": "yfinance", "requests": "requests", "pybit": "pybit", "yaml": "pyyaml"}
bad = []
for mod, dist in mods.items():
    try:
        importlib.import_module(mod)
        have = md.version(dist)
    except Exception as e:
        bad.append(f"{mod}: import failed ({type(e).__name__})")
        continue
    want = pins.get(dist)
    tag = "ok" if (want is None or have == want) else "MISMATCH"
    if tag == "MISMATCH":
        bad.append(f"{dist} {have} != pinned {want}")
    print(f"      {dist:10s} {have:10s} pinned {want or '-'}  {tag}")
print("BAD:" + ";".join(bad))
PY
)"
  printf '%s\n' "$pins_out" | grep -v '^BAD:'
  bad="$(printf '%s\n' "$pins_out" | sed -n 's/^BAD://p')"
  if [ -z "$bad" ] && printf '%s\n' "$pins_out" | grep -q '^BAD:'; then pass "venv imports pandas, numpy, yfinance, requests, pybit, yaml at the pinned versions"; else fail "venv pins: ${bad:-the check did not run}" "sudo -u vivek5 $venv/bin/pip install -r $vivek_home/requirements.txt"; fi
  as_vivek5_clean "$py" -c "import scanner, phasemap, scanner.config" >/dev/null 2>&1 && pass "scanner + phasemap import from $vivek_home (as vivek5)" || fail "scanner/phasemap do not import from $vivek_home" "check the clone and the venv"
else
  fail "$py missing" "sudo <source>/deploy/bin/install.sh"
fi

# ---- 3. disk ----------------------------------------------------------------
avail_gb="$(df -BG --output=avail /opt/vivek5 2>/dev/null | tail -1 | tr -dc '0-9')"
if [ -n "$avail_gb" ] && [ "$avail_gb" -ge 20 ]; then pass "${avail_gb} GB free under /opt/vivek5 (>= 20)"; else fail "${avail_gb:-?} GB free under /opt/vivek5, need >= 20 (2.4 GB clone x2 growing ~0.7 GB/month)" "resize the disk (40 GB recommended) or move /opt/vivek5"; fi

# ---- 4. units ---------------------------------------------------------------
cal_bad=""
while read -r c; do
  [ -n "$c" ] || continue
  systemd-analyze calendar "$c" >/dev/null 2>&1 || cal_bad="$cal_bad | $c"
done < <(grep -h '^OnCalendar=' "$kit"/systemd/*.timer | sed 's/^OnCalendar=//' | sort -u)
if [ -z "$cal_bad" ]; then pass "every OnCalendar line parses (systemd-analyze calendar)"; else fail "OnCalendar lines rejected:$cal_bad" "fix deploy/systemd/*.timer (tests/test_vps_deploy.py pins this)"; fi
installed="$(ls /etc/systemd/system/vivek5-* 2>/dev/null | wc -l)"
if [ "$installed" -eq 0 ]; then
  fail "no vivek5-* units in /etc/systemd/system" "sudo <source>/deploy/bin/install.sh --units"
else
  if systemd-analyze verify /etc/systemd/system/vivek5-* >/dev/null 2>&1; then pass "systemd-analyze verify on $installed installed units"; else fail "systemd-analyze verify rejects an installed unit" "systemd-analyze verify /etc/systemd/system/vivek5-*  (then fix deploy/systemd and re-run install.sh --units)"; fi
  stale=""
  for f in "$kit"/systemd/vivek5-*; do cmp -s "$f" "/etc/systemd/system/$(basename "$f")" || stale="$stale $(basename "$f")"; done
  drift=""
  for f in "$vivek_home"/deploy/systemd/vivek5-*; do [ -e "$f" ] || continue; cmp -s "$f" "$kit/systemd/$(basename "$f")" || drift="$drift $(basename "$f")"; done
  if [ -z "$stale" ] && [ -z "$drift" ] && [ ! -e "$state_dir/UNITS_STALE" ]; then pass "installed units match the operator kit and the checkout"
  else warn "units differ:${stale:+ installed vs kit:$stale}${drift:+ checkout vs kit:$drift}$([ -e "$state_dir/UNITS_STALE" ] && echo ' (UNITS_STALE marker)')" "sudo git -C <source> pull && sudo <source>/deploy/bin/install.sh --units (the root-owned source clone, never /opt/vivek5/app)"; fi
fi

# ---- 5. env files, key, host keys, sudoers, users, state -------------------
check_env_file() {  # <path> <group>
  local f="$1" grp="$2" mode own
  if [ ! -e "$f" ]; then fail "$f missing" "sudo <source>/deploy/bin/install.sh"; return; fi
  mode="$(stat -c %a "$f")"; own="$(stat -c %U:%G "$f")"
  [ "$mode" = "640" ] && [ "$own" = "root:$grp" ] && pass "$f is 0640 $own" || fail "$f is $mode $own, must be 0640 root:$grp" "sudo chown root:$grp $f; sudo chmod 0640 $f"
  if grep -Eq '^\s*GH_ADMIN_TOKEN\s*=' "$f"; then fail "$f assigns GH_ADMIN_TOKEN" "delete that line: the cutover token lives only in the calling shell"; fi
}
check_env_file "$etc/jobs.env" vivek5
check_env_file "$etc/api.env" vivek5-api
check_env_file "$etc/caddy.env" vivek5-caddy
for f in "$etc/jobs.env" "$etc/api.env"; do
  [ -r "$f" ] || continue          # a missing file is already a FAIL above, never a "no CHANGE_ME" PASS
  if grep -Eq '^[A-Z_]+=.*CHANGE_ME' "$f"; then fail "$f still has CHANGE_ME: $(grep -Eo '^[A-Z_]+=.*CHANGE_ME' "$f" | cut -d= -f1 | tr '\n' ' ')" "set each value or blank it (a blank alert leg is disabled, not a placeholder)"; else pass "$f has no CHANGE_ME"; fi
done
if [ -z "$domain" ] || [ "$domain" = "CHANGE_ME" ]; then fail "VIVEK_DOMAIN not set in $etc/caddy.env" "set the hostname that points at this box (D7: TLS needs a name; Workers cannot call an IP)"; fi
bh="$(env_get "$etc/caddy.env" VIVEK_API_BASIC_HASH)"
if [ "$api_phase" = "2" ] && { [ -z "$bh" ] || [ "$bh" = "CHANGE_ME" ]; }; then fail "phase 2 but VIVEK_API_BASIC_HASH is unset in $etc/caddy.env" "$caddy_bin hash-password (interactive), paste the hash RAW into caddy.env"; fi
if [ -x "$caddy_bin" ] && [ -r "$etc/Caddyfile" ] && [ -n "$domain" ] && [ "$domain" != "CHANGE_ME" ]; then
  # --envfile, never `. caddy.env`: bash would expand the bcrypt `$2a$14$...`
  if "$caddy_bin" validate --adapter caddyfile --config "$etc/Caddyfile" --envfile "$etc/caddy.env" >/dev/null 2>&1; then pass "$etc/Caddyfile validates with $etc/caddy.env"; else fail "$etc/Caddyfile does not validate with $etc/caddy.env" "$caddy_bin validate --adapter caddyfile --config $etc/Caddyfile --envfile $etc/caddy.env"; fi
fi
if grep -Eq '^DISPATCH_TOKEN=[0-9a-f]{64}$' "$etc/api.env" 2>/dev/null; then pass "DISPATCH_TOKEN is 32 random bytes (hex)"; else fail "DISPATCH_TOKEN in api.env is not a 64-hex value" "openssl rand -hex 32 and paste it as DISPATCH_TOKEN"; fi
if [ -f "$etc/deploy_key" ]; then
  km="$(stat -c '%a %U:%G' "$etc/deploy_key")"
  [ "$km" = "640 root:vivek5" ] && pass "deploy key present, 0640 root:vivek5" || fail "deploy key is $km" "sudo chown root:vivek5 $etc/deploy_key; sudo chmod 0640 $etc/deploy_key"
else
  fail "$etc/deploy_key missing" "sudo <source>/deploy/bin/install.sh (generates + prints it)"
fi
if [ -s "$etc/known_hosts" ]; then
  unknown_fp=""
  while read -r _bits fp _rest; do
    case " $GITHUB_FPS " in *" $fp "*) ;; *) unknown_fp="$unknown_fp $fp" ;; esac
  done < <(ssh-keygen -lf "$etc/known_hosts" 2>/dev/null || echo "0 unreadable")
  if [ -z "$unknown_fp" ]; then pass "known_hosts holds only GitHub's published host keys ($(grep -c . "$etc/known_hosts") keys)"
  else fail "known_hosts carries key(s) GitHub does not publish:$unknown_fp" "stop: something may be between this box and GitHub. Otherwise sudo rm $etc/known_hosts && sudo <source>/deploy/bin/install.sh (re-scans and refuses any unpublished key); if GitHub rotated a key, update GITHUB_FPS in install.sh and preflight.sh"; fi
else
  fail "$etc/known_hosts missing/empty" "sudo <source>/deploy/bin/install.sh (scans github.com and checks every key against the published fingerprints)"
fi
# No sudo grant is used any more (update.sh asks vivek5-api-restart.path to
# restart the API; NoNewPrivileges=yes forbids sudo in that unit anyway).
if [ -e /etc/sudoers.d/vivek5 ]; then
  warn "/etc/sudoers.d/vivek5 still exists (an earlier kit's grant: vivek5 may restart vivek5-api / reload vivek5-caddy)" "sudo <source>/deploy/bin/install.sh --units removes it (only if it carries this kit's header)"
else
  pass "no sudo grant for any vivek5 user"
fi
for u in vivek5 vivek5-api vivek5-caddy; do id -u "$u" >/dev/null 2>&1 && pass "user $u exists" || fail "user $u missing" "sudo <source>/deploy/bin/install.sh"; done
for u in vivek5-api vivek5; do
  id -nG "$u" 2>/dev/null | tr ' ' '\n' | grep -qx vivek5-spool && pass "$u is in group vivek5-spool" \
    || fail "$u is not in vivek5-spool (the adapter writes the spool, the runner reads it; without BOTH every dispatch is lost)" "sudo usermod -aG vivek5-spool $u"
done
kv="$(stat -c '%a %U:%G' "$state_dir/kv.json" 2>/dev/null || echo missing)"
[ "$kv" = "660 vivek5-api:vivek5-spool" ] && pass "state/kv.json is 0660 vivek5-api:vivek5-spool" || fail "state/kv.json is $kv (the adapter's cooldowns and caps live there)" "sudo <source>/deploy/bin/install.sh (recreates it 0660 vivek5-api:vivek5-spool)"
sp="$(stat -c '%a %U:%G' "$state_dir/spool" 2>/dev/null || echo none)"
[ "$sp" = "3770 vivek5:vivek5-spool" ] && pass "state/spool is 3770 vivek5:vivek5-spool (setgid + sticky)" || warn "state/spool is $sp (want 3770 vivek5:vivek5-spool)" "sudo <source>/deploy/bin/install.sh fixes the modes"
[ -e "$state_dir/HALT" ] && fail "state/HALT present: $(head -c 300 "$state_dir/HALT" | tr '\n' ' ')" "python -m scanner.vps accept-upstream (sync data from origin) or clear-halt (fixed by hand)" || pass "no HALT"
parked="$(ls "$state_dir/spool" 2>/dev/null | grep -E '\.(halted|retry|stuck)$' | tr '\n' ' ')"
[ -z "$parked" ] || warn "parked dispatches in state/spool: $parked" ".halted re-run after accept-upstream/clear-halt, .retry on the next drain; .stuck need a look (deploy/DESIGN.md 3.5)"

# ---- 6. git: publish clone can push via the deploy key ---------------------
if [ -d "$publish/.git" ]; then
  url="$(as_vivek5_clean git -C "$publish" remote get-url origin 2>/dev/null || echo '?')"
  if printf '%s' "$url" | grep -Eq '^https?://[^/@]+@'; then fail "publish remote carries a credential in the URL" "sudo -u vivek5 git -C $publish remote set-url origin git@github.com:OWNER/REPO.git (deploy key, never a token in the URL)"; else pass "publish remote $url"; fi
  if out="$(as_job git -C "$publish" push --dry-run origin HEAD:main 2>&1)"; then pass "git push --dry-run from the publish clone via the deploy key"; else fail "git push --dry-run failed: $(printf '%s' "$out" | tail -1)" "register $etc/deploy_key.pub as a WRITE deploy key on the repo; verify known_hosts"; fi
else
  fail "$publish is not a clone" "sudo <source>/deploy/bin/install.sh"
fi
if [ -d "$vivek_home/.git" ]; then
  pass "working checkout at $vivek_home ($(as_vivek5_clean git -C "$vivek_home" rev-parse --short HEAD 2>/dev/null))"
  shallow="$(as_vivek5_clean git -C "$vivek_home" rev-parse --is-shallow-repository 2>/dev/null)"
  [ "$shallow" = "false" ] && pass "working checkout is a FULL clone (update.sh's second-writer scan sees every commit)" \
    || fail "working checkout is shallow ($shallow): update.sh cannot see foreign data commits behind the boundary" "sudo -u vivek5 git -C $vivek_home fetch --unshallow origin"
else
  fail "$vivek_home is not a clone" "sudo <source>/deploy/bin/install.sh"
fi
for clone in "$vivek_home" "$publish"; do
  locks="$(find "$clone/.git" -maxdepth 4 -name '*.lock' -type f 2>/dev/null | tr '\n' ' ')"
  [ -z "$locks" ] || warn "git lock files in $clone/.git: $locks" "a git process was killed mid-write; the publish step clears its own, update.sh clears the checkout's -- re-run preflight after the next publish"
done

# ---- 7. domain + TLS front door --------------------------------------------
if [ -n "$domain" ] && [ "$domain" != "CHANGE_ME" ]; then
  resolved="$(getent ahosts "$domain" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ')"
  mine="$(hostname -I 2>/dev/null | tr ' ' '\n'; curl -sS --max-time 8 https://api.ipify.org 2>/dev/null; echo)"
  if [ -z "$resolved" ]; then
    fail "$domain does not resolve" "create the A/AAAA record for $domain -> this box"
  else
    hit=""; for ip in $resolved; do printf '%s\n' "$mine" | grep -qx "$ip" && hit=1; done
    if [ -n "$hit" ]; then pass "$domain resolves to this box ($resolved)"; else warn "$domain resolves to $resolved, none of which is a local/public address of this box" "fine if a proxy/tunnel fronts the box; otherwise fix DNS"; fi
  fi
  if systemctl is-active --quiet vivek5-api.service 2>/dev/null; then
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "https://$domain/api/vps" 2>/dev/null || true)"; code="${code:-000}"
    case "$code" in
      200) pass "https://$domain/api/vps answers 200" ;;
      503) warn "https://$domain/api/vps answers 503 (HALT, a CRITICAL job failed/halted, or the ledger is unreadable)" "sudo -u vivek5 $py -m scanner.vps ledger" ;;
      *)   fail "https://$domain/api/vps answers HTTP $code" "systemctl status vivek5-caddy.service vivek5-api.service; journalctl -u vivek5-caddy -n 50 (certificate?); port 443 reachable?" ;;
    esac
  else
    info "vivek5-api.service is not running yet: /api/vps not probed (cutover step 1 starts it and checks)"
  fi
fi
systemctl is-active --quiet vivek5-caddy.service 2>/dev/null && info "vivek5-caddy.service is active" || info "vivek5-caddy.service is not running (cutover.sh starts it)"

# ---- 8. ports, firewall, journal (INFO except a busy :80/:443) --------------
ports_rc=0
ports_out="$("$here/ports.sh" --check 2>&1)" || ports_rc=$?
printf '%s\n' "$ports_out" | sed 's/^/      /'
case "$ports_rc" in
  0) pass ":80 and :443 are free (or already ours)" ;;
  1) fail ":80/:443 are held by another process on this box (listed above)" "do NOT stop it (it may be the trading bots' stack): run the scanner on its own server, or front it with a Cloudflare Tunnel (deploy/DESIGN.md section 6)" ;;
  *) fail "could not list the TCP listeners (ports.sh exit $ports_rc), so :80/:443 were NOT checked" "sudo apt-get install iproute2 (ss), then re-run" ;;
esac
if command -v ufw >/dev/null 2>&1; then
  info "firewall (ufw status; this kit never changes it):"
  ufw status 2>&1 | sed 's/^/      /'
else
  info "ufw not installed (this kit configures no firewall; your provider's firewall must allow 80/443 in)"
fi
info "journal: $(journalctl --disk-usage 2>/dev/null | tail -1 || echo '?') (this kit installs no journald drop-in; the vivek5 units only disable per-unit rate limiting)"

# ---- 9. egress ---------------------------------------------------------------
# curl's -w prints 000 on a transport failure; `|| echo 000` would append a
# second one ("000000" -- the stop_watcher bug CLAUDE.md records).
probe() { local c; c="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 -A 'Mozilla/5.0 (vivek5-preflight)' "$1" 2>/dev/null || true)"; printf '%s' "${c:-000}"; }
y="$(probe 'https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1d&interval=1d')"
b="$(probe 'https://api.binance.com/api/v3/ping')"
g="$(probe 'https://api.github.com/')"
echo "      egress: yahoo=$y binance=$b api.github.com=$g"
[ "$y" = "200" ] && pass "Yahoo chart endpoint 200" || fail "Yahoo answers $y from this IP (every scan depends on it)" "pick another region/provider IP, or wire EODHD_API_TOKEN as the escape hatch; do not raise the throttles"
[ "$b" = "200" ] && pass "Binance ping 200" || warn "Binance answers $b (price relay for crypto)" "non-US region, or accept the relay degrading to Yahoo"
[ "$g" = "200" ] && pass "api.github.com 200" || warn "api.github.com answers $g" "cutover.sh needs it once (disable workflows); publishing itself uses ssh to github.com"
smtp_host="$(env_get "$etc/jobs.env" GBS_SMTP_HOST)"; smtp_host="${smtp_host:-smtp.gmail.com}"
tcp_open() { timeout 6 bash -c 'exec 3<>"/dev/tcp/$1/$2"' _ "$1" "$2" >/dev/null 2>&1; }
s587=closed; s465=closed
tcp_open "$smtp_host" 587 && s587=open
tcp_open "$smtp_host" 465 && s465=open
if [ "$s587" = "closed" ] && [ "$s465" = "closed" ]; then
  warn "outbound SMTP is blocked from this box ($smtp_host :587 and :465 both unreachable -- many VPS providers block mail ports)" "use Telegram for alerts (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID in $etc/jobs.env); email alerts cannot leave this box"
else
  pass "outbound SMTP reachable ($smtp_host :587 $s587, :465 $s465)"
fi

# ---- 10. alert channel round-trip (D8) --------------------------------------
if [ -x "$py" ] && [ -d "$vivek_home" ]; then
  ta="$(as_job "$py" -m scanner.watchdog --test-alert 2>&1)"
  printf '%s\n' "$ta" | sed 's/^/      /'
  if printf '%s\n' "$ta" | grep -Eq 'sent via (telegram|email)'; then
    pass "an alert channel round-trips (watchdog --test-alert, with the units' own environment)"
  elif [ "${VIVEK_ACCEPT_NO_ALERT_CHANNEL:-0}" = "1" ]; then
    warn "NO ALERT CHANNEL DELIVERS and VIVEK_ACCEPT_NO_ALERT_CHANNEL=1 was set: after cutover a failing VPS is SILENT (no red-run email exists any more). This is a standing risk you are choosing." "set TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID or GBS_SMTP_* in $etc/jobs.env as soon as you can"
  else
    fail "no alert channel delivered (Telegram/SMTP unconfigured or failing)" "set TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID (or GBS_SMTP_HOST/PORT/USER/PASS + GBS_ALERT_TO) in $etc/jobs.env and re-run; to proceed anyway export VIVEK_ACCEPT_NO_ALERT_CHANNEL=1 (loud WARN)"
  fi
fi

# ---- 11. optional sizing run -------------------------------------------------
if [ "$measure" = "1" ] && [ -x "$py" ]; then
  echo "      measuring: dry ASX scan --limit 40 in a throw-away worktree (VIVEK_GIT_PUBLISH=0) ..."
  # Measured at the heavy units' own priority (M6 C8): the live trading bot
  # on this box must not feel a sizing run either.
  as_vivek5_clean nice -n 10 ionice -c 2 -n 7 env VIVEK_GIT_PUBLISH=0 VIVEK_STATE_DIR="$state_dir" "$py" - "$vivek_home" "$py" <<'PY'
import os, resource, shutil, subprocess, sys, tempfile, time
home, py = sys.argv[1], sys.argv[2]
wt = tempfile.mkdtemp(prefix="measure-", dir=os.environ["VIVEK_STATE_DIR"])
os.rmdir(wt)
subprocess.run(["git", "-C", home, "worktree", "add", "--detach", "-q", wt, "HEAD"], check=True)
t0 = time.time()
try:
    rc = subprocess.run([py, "-m", "scanner.run", "--market", "asx", "--limit", "40",
                         "--out", os.path.join(wt, "public", "data")], cwd=wt).returncode
    rss_mib = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024.0
    print(f"      measure: dry ASX scan (--limit 40) rc={rc} wall={time.time()-t0:.0f}s "
          f"max RSS={rss_mib:.0f} MiB -- a full 2,200-name ASX run is larger; the heavy units are "
          f"throttled (not killed) above MemoryHigh=1G, so raise it if the full scan needs more")
finally:
    subprocess.run(["git", "-C", home, "worktree", "remove", "--force", wt])
    shutil.rmtree(wt, ignore_errors=True)
PY
fi

echo
echo "preflight: $fails FAIL, $warns WARN"
[ "$fails" -eq 0 ] || exit 1
exit 0
