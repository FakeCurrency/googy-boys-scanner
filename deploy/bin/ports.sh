#!/usr/bin/env bash
# deploy/bin/ports.sh -- print every TCP listener on this box with its
# process (M6 C4). READ-ONLY: it never stops, kills or reconfigures anything.
#
#     sudo deploy/bin/ports.sh            print the listeners (INFO)
#     sudo deploy/bin/ports.sh --check    ...and exit 1 when :80 or :443 is
#                                         held by anything other than OUR Caddy
#                                         (user vivek5-caddy)
#
# This box also runs the owner's trading bots. If one of them -- or anything
# else -- already answers on :80/:443, the scanner must not take the port
# from it: preflight.sh FAILS and cutover.sh refuses, with the options below.
# Run as root: ss shows other users' process names only to root. No `set -x`
# anywhere in deploy/bin (test-pinned).
set -uo pipefail

check=0
case "${1:-}" in
  "") ;;
  --check) check=1 ;;
  -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "ports.sh: unknown argument '$1'" >&2; exit 2 ;;
esac

die() { printf 'ports.sh: %s\n' "$*" >&2; exit 2; }
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
[ "$(id -u)" -ne 0 ] || refuse_unsafe_path

if ! listeners="$(ss -Htlnp 2>/dev/null)"; then
  echo "ports: 'ss -Htlnp' failed (iproute2 missing?) - cannot list listeners"
  [ "$check" = "1" ] && exit 2
  exit 0
fi
echo "TCP listeners on this box (ss -Htlnp):"
if [ -n "$listeners" ]; then printf '%s\n' "$listeners" | sed 's/^/      /'; else echo "      (none)"; fi
[ "$check" = "1" ] || exit 0

bad=""
while read -r line; do
  [ -n "$line" ] || continue
  # columns: State Recv-Q Send-Q Local:Port Peer:Port Process
  local_addr="$(printf '%s\n' "$line" | awk '{print $4}')"
  port="${local_addr##*:}"
  case "$port" in 80|443) ;; *) continue ;; esac
  pids="$(printf '%s\n' "$line" | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u)"
  if [ -z "$pids" ]; then
    bad="$bad
      :$port is held by a process ss would not name (run this as root to see it)"
    continue
  fi
  for pid in $pids; do
    user="$(ps -o user= -p "$pid" 2>/dev/null | tr -d ' ')"
    comm="$(ps -o comm= -p "$pid" 2>/dev/null | tr -d ' ')"
    if [ "$user" != "vivek5-caddy" ]; then
      bad="$bad
      :$port is held by '${comm:-?}' (pid $pid, user ${user:-?})"
    fi
  done
done <<< "$listeners"

if [ -n "$bad" ]; then
  cat <<MSG
PORTS BUSY:$bad

  Vivek 5.0's front door needs ports 80 and 443 (Caddy obtains the TLS
  certificate on :80 and serves the dispatch endpoint on :443). Something else
  on this box already uses them. This kit will NOT stop, reconfigure or share
  that process -- it may be part of the trading bots this box exists for.
  Options:
    1. run the scanner on its OWN server (a small VPS of its own), or
    2. keep this box and front the scanner with a Cloudflare Tunnel
       (cloudflared): no inbound port at all, the tunnel dials out
       (deploy/DESIGN.md section 6).
  Then re-run preflight.
MSG
  exit 1
fi
echo "ports: :80/:443 are free or held by vivek5-caddy"
exit 0
