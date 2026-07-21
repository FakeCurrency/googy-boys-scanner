#!/usr/bin/env bash
# assert_staged.sh <label> <path> [<path>...]
#
# Run AFTER `git add` in a workflow commit step: exits 0 if AT LEAST ONE of
# the listed must-change paths has a staged diff, exits 1 loudly otherwise.
#
# WHY (2026-07-20 incident, Phase 5): a successful scheduled scan can never
# legitimately commit nothing — every scan rewrites *_vivek.json with a
# wall-clock generated_at and every non-dry bot run re-stamps the book's
# updated_at. Yet the Phase 3 staging bug ran GREEN five times in a row while
# committing zero bytes, freezing the site and the track record for hours
# with no alert of any kind. This gate turns "success that did no work" into
# a red run, which triggers the existing failure email + Discord alert.
#
# Call it once per independent invariant ("all must change" = several calls,
# one path each; "any of these" = one call, several paths).
set -u
label="${1:?usage: assert_staged.sh <label> <path> [<path>...]}"
shift
[ "$#" -ge 1 ] || { echo "::error::assert_staged($label): no paths given"; exit 2; }

for p in "$@"; do
  # Path has a staged difference vs HEAD (covers modified AND newly added).
  if ! git diff --cached --quiet -- "$p" 2>/dev/null; then
    echo "assert_staged($label): OK - '$p' has staged changes"
    exit 0
  fi
done

echo "::error::ASSERT-STAGED FAILED ($label): none of [$*] has staged changes after a successful run. Output is being LOST (see the 2026-07-20 staging incident in OPERATIONS.md). Do not ignore this."
git status --short | head -20 || true
exit 1
