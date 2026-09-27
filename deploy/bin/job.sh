#!/usr/bin/env bash
# deploy/bin/job.sh -- the ONE ExecStart every vivek5-* job unit uses.
#
# Thin on purpose (deploy/DESIGN.md 3.1): change to the working checkout,
# stamp the build sha the scan publishes as `code_sha`, and hand off to the
# runner. Locks, gates, publish and the ledger all live INSIDE
# `python -m scanner.vps run` -- there is no flock here, so nothing is
# double-locked, and there is no `set -x` anywhere under deploy/bin
# (test-pinned: a trace would print every secret in the environment).
set -eu

cd "${VIVEK_HOME:-/opt/vivek5/app}"
GITHUB_SHA="$(git rev-parse HEAD 2>/dev/null || true)"
export GITHUB_SHA
exec "${VIVEK_VENV:-/opt/vivek5/venv}/bin/python" -m scanner.vps run "$@"
