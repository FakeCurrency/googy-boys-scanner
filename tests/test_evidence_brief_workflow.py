"""evidence_brief.yml — the pins (2026-08-01).

The workflow is the DELIVERY layer for scripts/evidence_brief.py, whose own
tests pin that it writes nothing and imports nothing from scanner/ or broker/.
What is worth pinning here is the shape of the delivery:

  * it never joins the book-writers' mutex (it writes no book),
  * it never commits (no git in the run blocks at all),
  * the script's exit code 1 — the "brief names an issue" flag — is
    tolerated, not turned into a daily failure email (the stop_watcher 503
    lesson: an alarm that cannot stop ringing gets muted),
  * a missing Discord webhook degrades to the step summary, never to red.
"""
from __future__ import annotations

import pathlib
import re

WF = (pathlib.Path(__file__).resolve().parents[1]
      / ".github" / "workflows" / "evidence_brief.yml").read_text(encoding="utf-8")


def test_it_is_scheduled_daily_and_hand_dispatchable():
    assert re.search(r'cron:\s*"0 21 \* \* \*"', WF), "daily 21:00 UTC cron missing"
    assert "workflow_dispatch" in WF


def test_it_reads_and_never_writes():
    assert "contents: read" in WF, "must hold read-only permissions"
    assert "contents: write" not in WF
    # Scan CODE lines only — the header comment names assert_staged precisely
    # to record why it is absent, and a ban that reads comments would forbid
    # the explanation of the ban.
    code = "\n".join(l for l in WF.splitlines() if not l.lstrip().startswith("#"))
    for banned in ("git add", "git commit", "git push", "assert_staged"):
        assert banned not in code, f"a read-only reporter must not contain '{banned}'"


def test_it_is_not_in_the_scan_mutex():
    # The `scan` group serializes BOOK WRITERS. A reader joining it would let
    # a morning brief evict a queued close or backstop scan (the group keeps
    # ONE pending run and cancels the previous) for no protection in return.
    assert "group: scan" not in WF


def test_the_issue_flag_is_tolerated_and_a_crash_is_not():
    # rc 1 means the brief SAYS "ISSUE:" — content, delivered, green run.
    # Any other non-zero rc is a crash and must stay fatal.
    assert re.search(r'\[ "\$rc" -ne 0 \] && \[ "\$rc" -ne 1 \]', WF), \
        "the rc 0/1-valid, else-fatal discrimination has been lost"
    assert "exit \"$rc\"" in WF


def test_the_discord_leg_is_gone_and_the_brief_still_lands_in_the_summary():
    # Post-to-Discord removed 2026-08-27 with the whole channel (owner
    # ruling). The brief's delivery is the step summary; the pin is that the
    # summary write survives and the removed channel stays removed.
    assert "DISCORD_WEBHOOK_URL" not in WF, "the removed channel crept back in"
    assert "GITHUB_STEP_SUMMARY" in WF, "the brief must still land somewhere readable"


def test_it_has_a_timeout():
    assert "timeout-minutes:" in WF, "an unbounded job holds a runner for 6h by default"
