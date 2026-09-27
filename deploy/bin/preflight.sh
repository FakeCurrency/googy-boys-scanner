#!/usr/bin/env bash
# deploy/bin/preflight.sh -- every check of deploy/DESIGN.md 7 step 0, each
# printed as PASS / FAIL / WARN with the exact remedy. Exits 1 on any FAIL.
# cutover.sh refuses to start unless this is green.
#
#     sudo deploy/bin/preflight.sh [--measure]
#
# --measure additionally runs a DRY ASX scan (--limit 40, VIVEK_GIT_PUBLISH=0)
# in a throw-away git worktree and prints its max RSS, for sizing the box.
#
# The alert-channel check is a FAIL unless VIVEK_ACCEPT_NO_ALERT_CHANNEL=1 is
# set in the calling shell, in which case it is a loud WARN (D8: cutover
# deletes GitHub's red-run email, the last alarm; a silent VPS is a design
# failure, not a config gap). No `set -x` in deploy/bin (test-pinned).
set -uo pipefail   # deliberately no -e: every check must run and report

measure=0
for a in "$@"; do
  case "$a" in
    --measure) measure=1 ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "preflight.sh: unknown argument '$a'" >&2; exit 2 ;;
  esac
done

here="$(cd "$(dirname "$0")" && pwd)"
kit="$(cd "$here/.." && pwd)"
etc=/etc/vivek5
fails=0; warns=0
pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n      remedy: %s\n' "$1" "$2"; fails=$((fails + 1)); }
warn() { printf 'WARN  %s\n      note:   %s\n' "$1" "$2"; warns=$((warns + 1)); }
as_vivek5() { if [ "$(id -un)" = "vivek5" ]; then "$@"; else sudo -u vivek5 -H "$@"; fi; }
vermaj() { sed -E 's/^[^0-9]*([0-9]+).*/\1/'; }

# ---- 0. environment --------------------------------------------------------
if [ -r "$etc/jobs.env" ]; then
  set -a; . "$etc/jobs.env"; set +a
else
  fail "$etc/jobs.env is not readable by $(id -un)" "run as root (sudo deploy/bin/preflight.sh) after install.sh"
fi
if [ -r /etc/caddy/vivek5.env ]; then
  set -a; . /etc/caddy/vivek5.env; set +a
fi
vivek_home="${VIVEK_HOME:-/opt/vivek5/app}"
publish="${VIVEK_PUBLISH:-/opt/vivek5/publish}"
venv="${VIVEK_VENV:-/opt/vivek5/venv}"
state_dir="${VIVEK_STATE_DIR:-/opt/vivek5/state}"
py="$venv/bin/python"
domain="${VIVEK_DOMAIN:-}"

echo "Vivek 5.0 VPS preflight  $(date -u +%Y-%m-%dT%H:%M:%SZ)  host=$(hostname)"
echo

# ---- 1. OS / clock ----------------------------------------------------------
if [ -r /etc/os-release ]; then
  . /etc/os-release
  if [ "${ID:-}" = "ubuntu" ] && [ "${VERSION_ID:-}" = "24.04" ]; then pass "Ubuntu 24.04 (${PRETTY_NAME:-})"
  else fail "OS is ${PRETTY_NAME:-unknown}, kit is for Ubuntu 24.04" "use an Ubuntu 24.04 image (python3.12 + systemd 255 are what the kit is tested on)"; fi
else
  fail "/etc/os-release missing" "use Ubuntu 24.04"
fi
tz="$(timedatectl show -p Timezone --value 2>/dev/null || echo '?')"
ntp="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || echo '?')"
if [ "$tz" = "Etc/UTC" ] || [ "$tz" = "UTC" ]; then pass "box timezone $tz"; else fail "box timezone is '$tz', must be UTC (two naive local-date calls in the engine)" "sudo timedatectl set-timezone Etc/UTC"; fi
if [ "$ntp" = "yes" ]; then pass "NTP synchronized"; else fail "NTPSynchronized=$ntp" "sudo systemctl enable --now systemd-timesyncd; sudo timedatectl set-ntp true; wait a minute"; fi

# ---- 2. toolchain -----------------------------------------------------------
if command -v node >/dev/null 2>&1 && [ "$(node --version | vermaj)" -ge 22 ]; then pass "node $(node --version) ($(command -v node))"; else fail "node >= 22 required ($(node --version 2>/dev/null || echo none))" "sudo deploy/bin/install.sh (NodeSource 22.x)"; fi
[ -x /usr/bin/node ] && pass "/usr/bin/node present (vivek5-api.service ExecStart)" || fail "/usr/bin/node missing" "install Node from NodeSource or symlink your node binary to /usr/bin/node"
if command -v caddy >/dev/null 2>&1; then
  cv="$(caddy version | sed -E 's/^v?([0-9]+\.[0-9]+).*/\1/')"
  if python3 -c "import sys; a=tuple(int(x) for x in '$cv'.split('.')[:2]); sys.exit(0 if a>=(2,8) else 1)"; then pass "caddy $cv"; else fail "caddy $cv < 2.8 (no basic_auth, no handle_errors <status>)" "remove Ubuntu's caddy and install from dl.cloudsmith.io/public/caddy/stable (install.sh does this)"; fi
else
  fail "caddy not installed" "sudo deploy/bin/install.sh"
fi
if [ -x "$py" ]; then
  pv="$("$py" --version 2>&1)"
  case "$pv" in "Python 3.12."*) pass "venv $pv" ;; *) fail "venv python is '$pv', need 3.12" "rm -rf $venv; sudo deploy/bin/install.sh" ;; esac
  pins_out="$("$py" - "$vivek_home/requirements.txt" <<'PY' 2>&1
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
  if [ -z "$bad" ]; then pass "venv imports pandas, numpy, yfinance, requests, pybit, yaml at the pinned versions"; else fail "venv pins: $bad" "$venv/bin/pip install -r $vivek_home/requirements.txt"; fi
  ( cd "$vivek_home" && "$py" -c "import scanner, phasemap, scanner.config" ) >/dev/null 2>&1 && pass "scanner + phasemap import from $vivek_home" || fail "scanner/phasemap do not import from $vivek_home" "check the clone and the venv"
else
  fail "$py missing" "sudo deploy/bin/install.sh"
fi

# ---- 3. disk ----------------------------------------------------------------
avail_gb="$(df -BG --output=avail /opt/vivek5 2>/dev/null | tail -1 | tr -dc '0-9')"
if [ -n "$avail_gb" ] && [ "$avail_gb" -ge 20 ]; then pass "${avail_gb} GB free under /opt/vivek5 (>= 20)"; else fail "${avail_gb:-?} GB free under /opt/vivek5, need >= 20 (2.4 GB clone x2 growing ~0.7 GB/month + journal 2 GB)" "resize the disk (40 GB recommended) or move /opt/vivek5"; fi

# ---- 4. units ---------------------------------------------------------------
cal_bad=""
while read -r c; do
  [ -n "$c" ] || continue
  systemd-analyze calendar "$c" >/dev/null 2>&1 || cal_bad="$cal_bad | $c"
done < <(grep -h '^OnCalendar=' "$kit"/systemd/*.timer | sed 's/^OnCalendar=//' | sort -u)
if [ -z "$cal_bad" ]; then pass "every OnCalendar line parses (systemd-analyze calendar)"; else fail "OnCalendar lines rejected:$cal_bad" "fix deploy/systemd/*.timer (tests/test_vps_deploy.py pins this)"; fi
installed="$(ls /etc/systemd/system/vivek5-* 2>/dev/null | wc -l)"
if [ "$installed" -eq 0 ]; then
  fail "no vivek5-* units in /etc/systemd/system" "sudo deploy/bin/install.sh --units"
else
  if systemd-analyze verify /etc/systemd/system/vivek5-* >/dev/null 2>&1; then pass "systemd-analyze verify on $installed installed units"; else fail "systemd-analyze verify rejects an installed unit" "systemd-analyze verify /etc/systemd/system/vivek5-*  (then fix deploy/systemd and re-run install.sh --units)"; fi
  stale=""
  for f in "$kit"/systemd/vivek5-*; do cmp -s "$f" "/etc/systemd/system/$(basename "$f")" || stale="$stale $(basename "$f")"; done
  if [ -z "$stale" ] && [ ! -e "$state_dir/UNITS_STALE" ]; then pass "installed units match deploy/systemd"; else warn "installed units differ from the checkout:${stale:- (UNITS_STALE marker)}" "sudo deploy/bin/install.sh --units"; fi
fi

# ---- 5. env files, key, host keys, sudoers, users, state -------------------
check_env_file() {  # <path> <group>
  local f="$1" grp="$2" mode own
  if [ ! -e "$f" ]; then fail "$f missing" "sudo deploy/bin/install.sh"; return; fi
  mode="$(stat -c %a "$f")"; own="$(stat -c %U:%G "$f")"
  [ "$mode" = "640" ] && [ "$own" = "root:$grp" ] && pass "$f is 0640 $own" || fail "$f is $mode $own, must be 0640 root:$grp" "sudo chown root:$grp $f; sudo chmod 0640 $f"
  if grep -Eq '^[A-Z_]+=.*CHANGE_ME' "$f"; then fail "$f still has CHANGE_ME: $(grep -Eo '^[A-Z_]+=.*CHANGE_ME' "$f" | cut -d= -f1 | tr '\n' ' ')" "set each value or blank it (a blank alert leg is disabled, not a placeholder)"; else pass "$f has no CHANGE_ME"; fi
  if grep -Eq '^\s*GH_ADMIN_TOKEN\s*=' "$f"; then fail "$f assigns GH_ADMIN_TOKEN" "delete that line: the cutover token lives only in the calling shell"; fi
}
check_env_file "$etc/jobs.env" vivek5
check_env_file "$etc/api.env" vivek5-api
if grep -Eq '^DISPATCH_TOKEN=[0-9a-f]{64}$' "$etc/api.env" 2>/dev/null; then pass "DISPATCH_TOKEN is 32 random bytes (hex)"; else fail "DISPATCH_TOKEN in api.env is not a 64-hex value" "openssl rand -hex 32 and paste it as DISPATCH_TOKEN"; fi
if [ -f "$etc/deploy_key" ]; then
  km="$(stat -c '%a %U:%G' "$etc/deploy_key")"
  [ "$km" = "640 root:vivek5" ] && pass "deploy key present, 0640 root:vivek5" || fail "deploy key is $km" "sudo chown root:vivek5 $etc/deploy_key; sudo chmod 0640 $etc/deploy_key"
else
  fail "$etc/deploy_key missing" "sudo deploy/bin/install.sh (generates + prints it)"
fi
[ -s "$etc/known_hosts" ] && pass "known_hosts seeded ($(grep -c . "$etc/known_hosts") host keys)" || fail "$etc/known_hosts missing/empty" "sudo ssh-keyscan -t ed25519,ecdsa,rsa github.com > $etc/known_hosts (then verify the fingerprints)"
if [ -f /etc/sudoers.d/vivek5 ] && visudo -cf /etc/sudoers.d/vivek5 >/dev/null 2>&1; then pass "sudoers.d/vivek5 valid"; else fail "/etc/sudoers.d/vivek5 missing or invalid" "sudo deploy/bin/install.sh"; fi
for u in vivek5 vivek5-api; do id -u "$u" >/dev/null 2>&1 && pass "user $u exists" || fail "user $u missing" "sudo deploy/bin/install.sh"; done
id -nG vivek5-api 2>/dev/null | tr ' ' '\n' | grep -qx vivek5-spool && pass "vivek5-api is in group vivek5-spool" || fail "vivek5-api not in vivek5-spool (cannot write the spool)" "sudo usermod -aG vivek5-spool vivek5-api"
sp="$(stat -c '%a %U:%G' "$state_dir/spool" 2>/dev/null || echo none)"
[ "$sp" = "2770 vivek5:vivek5-spool" ] && pass "state/spool is 2770 vivek5:vivek5-spool" || warn "state/spool is $sp (want 2770 vivek5:vivek5-spool)" "sudo deploy/bin/install.sh fixes the modes"
[ -e "$state_dir/HALT" ] && fail "state/HALT present: $(head -c 300 "$state_dir/HALT" | tr '\n' ' ')" "python -m scanner.vps accept-upstream (sync data from origin) or clear-halt (fixed by hand)" || pass "no HALT"

# ---- 6. git: publish clone can push via the deploy key ---------------------
if [ -d "$publish/.git" ]; then
  url="$(git -C "$publish" remote get-url origin 2>/dev/null || echo '?')"
  if printf '%s' "$url" | grep -Eq '^https?://[^/@]+@'; then fail "publish remote carries a credential in the URL" "git -C $publish remote set-url origin git@github.com:OWNER/REPO.git (deploy key, never a token in the URL)"; else pass "publish remote $url"; fi
  if out="$(as_vivek5 env GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh}" git -C "$publish" push --dry-run origin HEAD:main 2>&1)"; then pass "git push --dry-run from the publish clone via the deploy key"; else fail "git push --dry-run failed: $(printf '%s' "$out" | tail -1)" "register $etc/deploy_key.pub as a WRITE deploy key on the repo; verify known_hosts"; fi
else
  fail "$publish is not a clone" "sudo deploy/bin/install.sh"
fi
[ -d "$vivek_home/.git" ] && pass "working checkout at $vivek_home ($(git -C "$vivek_home" rev-parse --short HEAD 2>/dev/null))" || fail "$vivek_home is not a clone" "sudo deploy/bin/install.sh"

# ---- 7. domain + TLS front door --------------------------------------------
if [ -z "$domain" ] || [ "$domain" = "CHANGE_ME" ]; then
  fail "VIVEK_DOMAIN not set in /etc/caddy/vivek5.env" "set the hostname that points at this box (D7: TLS needs a name; Workers cannot call an IP), then sudo deploy/bin/install.sh --units"
else
  resolved="$(getent ahosts "$domain" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ')"
  mine="$(hostname -I 2>/dev/null | tr ' ' '\n'; curl -sS --max-time 8 https://api.ipify.org 2>/dev/null; echo)"
  if [ -z "$resolved" ]; then
    fail "$domain does not resolve" "create the A/AAAA record for $domain -> this box"
  else
    hit=""; for ip in $resolved; do printf '%s\n' "$mine" | grep -qx "$ip" && hit=1; done
    if [ -n "$hit" ]; then pass "$domain resolves to this box ($resolved)"; else warn "$domain resolves to $resolved, none of which is a local/public address of this box" "fine if a proxy/tunnel fronts the box; otherwise fix DNS"; fi
  fi
  if systemctl is-active --quiet vivek5-api.service 2>/dev/null; then
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "https://$domain/api/vps" 2>/dev/null || echo 000)"
    case "$code" in
      200) pass "https://$domain/api/vps answers 200" ;;
      503) warn "https://$domain/api/vps answers 503 (HALT or a CRITICAL job failed)" "python -m scanner.vps ledger" ;;
      *)   fail "https://$domain/api/vps answers HTTP $code" "systemctl status caddy vivek5-api; journalctl -u caddy -n 50 (certificate?); port 443 open?" ;;
    esac
  else
    warn "vivek5-api.service is not running yet, /api/vps not probed" "cutover step 1 enables it and re-checks https://$domain/api/vps"
  fi
fi
systemctl is-active --quiet caddy 2>/dev/null && pass "caddy is active" || warn "caddy is not active" "sudo deploy/bin/install.sh --units (needs VIVEK_DOMAIN) or systemctl enable --now caddy"

# ---- 8. egress ---------------------------------------------------------------
probe() { curl -sS -o /dev/null -w '%{http_code}' --max-time 20 -A 'Mozilla/5.0 (vivek5-preflight)' "$1" 2>/dev/null || echo 000; }
y="$(probe 'https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1d&interval=1d')"
b="$(probe 'https://api.binance.com/api/v3/ping')"
g="$(probe 'https://api.github.com/')"
echo "      egress: yahoo=$y binance=$b api.github.com=$g"
[ "$y" = "200" ] && pass "Yahoo chart endpoint 200" || fail "Yahoo answers $y from this IP (every scan depends on it)" "pick another region/provider IP, or wire EODHD_API_TOKEN as the escape hatch; do not raise the throttles"
[ "$b" = "200" ] && pass "Binance ping 200" || warn "Binance answers $b (price relay for crypto)" "non-US region, or accept the relay degrading to Yahoo"
[ "$g" = "200" ] && pass "api.github.com 200" || warn "api.github.com answers $g" "cutover.sh needs it once (disable workflows); publishing itself uses ssh to github.com"

# ---- 9. alert channel round-trip (D8) --------------------------------------
if [ -x "$py" ] && [ -d "$vivek_home" ]; then
  ta="$(cd "$vivek_home" && "$py" -m scanner.watchdog --test-alert 2>&1)"
  printf '%s\n' "$ta" | sed 's/^/      /'
  if printf '%s\n' "$ta" | grep -Eq 'sent via (telegram|email)'; then
    pass "an alert channel round-trips (watchdog --test-alert)"
  elif [ "${VIVEK_ACCEPT_NO_ALERT_CHANNEL:-0}" = "1" ]; then
    warn "NO ALERT CHANNEL DELIVERS and VIVEK_ACCEPT_NO_ALERT_CHANNEL=1 was set: after cutover a failing VPS is SILENT (no red-run email exists any more). This is a standing risk you are choosing." "set TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID or GBS_SMTP_* in $etc/jobs.env as soon as you can"
  else
    fail "no alert channel delivered (Telegram/SMTP unconfigured or failing)" "set TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID (or GBS_SMTP_HOST/PORT/USER/PASS + GBS_ALERT_TO) in $etc/jobs.env and re-run; to proceed anyway export VIVEK_ACCEPT_NO_ALERT_CHANNEL=1 (loud WARN)"
  fi
fi

# ---- 10. optional sizing run -------------------------------------------------
if [ "$measure" = "1" ] && [ -x "$py" ]; then
  echo "      measuring: dry ASX scan --limit 40 in a throw-away worktree (VIVEK_GIT_PUBLISH=0) ..."
  as_vivek5 env VIVEK_GIT_PUBLISH=0 VIVEK_STATE_DIR="$state_dir" "$py" - "$vivek_home" "$py" <<'PY'
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
          f"max RSS={rss_mib:.0f} MiB -- a full 2,200-name ASX run is larger; size RAM at ~2x that plus 2 GB, with swap")
finally:
    subprocess.run(["git", "-C", home, "worktree", "remove", "--force", wt])
    shutil.rmtree(wt, ignore_errors=True)
PY
fi

echo
echo "preflight: $fails FAIL, $warns WARN"
[ "$fails" -eq 0 ] || exit 1
exit 0
