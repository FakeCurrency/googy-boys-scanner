"""Tests for scripts/commit_sentinel.py + commit_sentinel.yml (2026-08-20).

The sentinel is the detection half of branch protection: it must NAME every
identity anomaly on a push to main and must never be able to block one.
These tests drive the real main() via argv (the test_vivek_run pattern —
the CLI surface is what the workflow calls, so that is what gets tested)
and pin the workflow's structural decisions so they read as decisions.
"""

import json
import re
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import commit_sentinel  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
WF = (ROOT / ".github" / "workflows" / "commit_sentinel.yml").read_text(encoding="utf-8")


def _commit(cid="a" * 40, email="github-actions[bot]@users.noreply.github.com",
            name="github-actions[bot]", cemail=None, cname=None):
    return {
        "id": cid,
        "author": {"email": email, "name": name},
        "committer": {"email": cemail or email, "name": cname or name},
    }


def _event(pusher="FakeCurrency", commits=None, **extra):
    evt = {
        "pusher": {"name": pusher},
        "sender": {"login": pusher},
        "commits": commits if commits is not None else [_commit()],
        "before": "b" * 40,
        "after": "c" * 40,
    }
    evt.update(extra)
    return evt


def _run(tmp_path, evt):
    p = tmp_path / "event.json"
    p.write_text(json.dumps(evt), encoding="utf-8")
    return commit_sentinel.main([str(p)])


# ── the clean cases: every legitimate writer stays silent ────────────────────

def test_a_scan_bot_push_is_clean(tmp_path, capsys):
    rc = _run(tmp_path, _event(pusher="github-actions[bot]"))
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_every_observed_identity_is_allowed(tmp_path):
    for email in sorted(commit_sentinel.ALLOWED_EMAILS):
        rc = _run(tmp_path, _event(commits=[_commit(email=email, name="x")]))
        assert rc == 0, f"legitimate identity {email} must not alert"


def test_a_claude_session_push_is_clean(tmp_path):
    # Claude sessions author as noreply@anthropic.com and push as the owner.
    rc = _run(tmp_path, _event(pusher="FakeCurrency",
                               commits=[_commit(email="noreply@anthropic.com", name="Claude")]))
    assert rc == 0


# ── the anomalies: each one is exit 1 and NAMED in the report ────────────────

def test_an_unknown_author_email_is_flagged(tmp_path, capsys):
    rc = _run(tmp_path, _event(commits=[_commit(email="evil@example.com", name="Notabot")]))
    assert rc == 1
    out = capsys.readouterr().out
    assert "evil@example.com" in out and "AUTHOR" in out


def test_an_unknown_committer_is_flagged_even_when_the_author_is_clean(tmp_path, capsys):
    rc = _run(tmp_path, _event(commits=[_commit(cemail="quiet@example.com")]))
    assert rc == 1
    assert "COMMITTER" in capsys.readouterr().out


def test_an_unknown_pusher_is_flagged_even_when_every_commit_is_clean(tmp_path, capsys):
    # THE GROK CLASS: an integration pushing commits that wear the owner's
    # identity. Commit metadata is clean; the authenticated pusher is not.
    rc = _run(tmp_path, _event(pusher="grok-connector[bot]"))
    assert rc == 1
    assert "grok-connector[bot]" in capsys.readouterr().out


def test_the_historical_one_offs_are_NOT_allowlisted(tmp_path):
    # A mangled git config and a 2026-07 parity probe both appeared once on
    # main; their shape coming back should trip the wire, not be grandfathered.
    for email in ("your-email@example.comvk91.vivek.kumar@gmail.com",
                  "actions@users.noreply.github.com"):
        assert email not in commit_sentinel.ALLOWED_EMAILS
        assert _run(tmp_path, _event(commits=[_commit(email=email)])) == 1


def test_a_truncated_payload_is_itself_an_anomaly(tmp_path, capsys):
    # GitHub caps commits at 20/payload. "Could not see everything" must never
    # read as "everything was fine".
    rc = _run(tmp_path, _event(commits=[_commit()], size=25))
    assert rc == 1
    assert "PARTIAL VISIBILITY" in capsys.readouterr().out


def test_a_force_push_is_flagged(tmp_path, capsys):
    rc = _run(tmp_path, _event(forced=True))
    assert rc == 1
    assert "FORCE-PUSH" in capsys.readouterr().out


def test_a_missing_email_is_flagged_not_skipped(tmp_path, capsys):
    rc = _run(tmp_path, _event(commits=[{"id": "d" * 40, "author": {}, "committer": {}}]))
    assert rc == 1
    assert "MISSING" in capsys.readouterr().out


# ── the CLI contract the workflow depends on ─────────────────────────────────

def test_a_bad_event_path_is_a_crash_not_an_anomaly(capsys):
    # The workflow treats exit 1 as "anomaly found" and anything else as a
    # crash — an unreadable payload must never masquerade as a finding.
    assert commit_sentinel.main(["/nonexistent/event.json"]) == 2
    assert commit_sentinel.main([]) == 2


def test_the_report_is_ascii_only(tmp_path, capsys):
    _run(tmp_path, _event(pusher="grok-connector[bot]", forced=True, size=25))
    out = capsys.readouterr().out
    assert all(ord(ch) < 128 for ch in out), "scanner-side prints are ASCII-only (project rule 9)"


# ── workflow structure: the decisions stay decisions ─────────────────────────

def test_the_workflow_tolerates_exit_1_and_fails_on_anything_else():
    # Anomaly = content (green run + Discord); crash = red. Same shape as
    # evidence_brief.yml, and the -ne 1 test is what implements it.
    assert re.search(r'\[ "\$rc" -ne 0 \] && \[ "\$rc" -ne 1 \]', WF)


def test_the_workflow_is_detection_only():
    # Nothing in it may write the repo: no git commit/push/revert, and its
    # token is read-only.
    assert "permissions:\n  contents: read" in WF
    for verb in ("git push", "git revert", "git commit", "git reset"):
        assert verb not in WF, f"detection-only: '{verb}' has no business here"


def test_the_workflow_is_NOT_in_the_scan_concurrency_group():
    # The scan group keeps ONE pending run and evicts the rest; ~20 data
    # pushes a day queueing here would evict real scans (2026-07-28 lesson).
    assert "group: scan" not in WF
    assert not re.search(r"^\s*concurrency:", WF, re.M), \
        "no concurrency key at all - the job writes nothing and must never queue"


def test_the_alert_uses_the_proven_discord_path():
    # BOM-trimmed URL + named UA — the two halves of CLAUDE.md "ALERT
    # DELIVERY" that made the channel deliverable at all.
    assert "\\ufeff" in WF
    assert "vivek5-alerts/1.0" in WF
    assert "DISCORD_WEBHOOK_URL" in WF


def test_it_fires_on_every_push_to_main_with_no_path_filter():
    assert re.search(r"on:\s*\n\s*push:\s*\n\s*branches: \[main\]", WF)
    assert "paths" not in WF, "the quiet-edit scenario IS a data-file edit - no path filter"


def test_the_pusher_allowlist_is_the_observed_set():
    assert commit_sentinel.ALLOWED_PUSHERS == {"FakeCurrency", "github-actions[bot]"}


@pytest.mark.parametrize("email", sorted(commit_sentinel.ALLOWED_EMAILS))
def test_every_allowlisted_email_was_actually_observed_on_main(email):
    # The allowlist is a claim about history; keep it small and deliberate.
    assert email in {
        "github-actions[bot]@users.noreply.github.com",
        "noreply@anthropic.com",
        "294004674+FakeCurrency@users.noreply.github.com",
        "vivek@strategicnutrition.com.au",
        "vk91.vivek.kumar@gmail.com",
    }
