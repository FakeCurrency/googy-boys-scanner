"""Commit sentinel — the DETECTION half of branch protection (2026-08-20).

Reads a GitHub push-event payload (the JSON at GITHUB_EVENT_PATH) and checks
three things against what main's real history actually looks like:

  1. The AUTHENTICATED PUSHER (payload `pusher.name` / `sender.login`) is a
     known account. This is the field commit metadata cannot forge — an
     integration pushing under its own installation shows up here no matter
     what identity its commits claim.
  2. Every commit the payload lists carries a known author/committer email.
  3. Nothing is hiding: a truncated payload (GitHub caps `commits` at 20) or
     a force-push is itself reported, because "could not see everything" must
     never read as "everything was fine".

Exit 0 = all known. Exit 1 = anomaly NAMED in the printed report (the
workflow surfaces it on the run page and stays green — detection only; nothing is
ever blocked or reverted, per the owner's incident review). Any other exit
is a crash and the workflow goes red.

THE ALLOWLIST IS OBSERVED, NOT GUESSED — census over 1,933 commits of main,
2026-08-20:
    1267  github-actions[bot]@users.noreply.github.com   (scan/close/backfill bots)
     281  noreply@anthropic.com                          (Claude sessions)
     289  294004674+FakeCurrency@users.noreply.github.com (owner, web + local)
      81  vivek@strategicnutrition.com.au                (owner, local git)
      13  vk91.vivek.kumar@gmail.com                     (owner, older local git)
Two historical one-offs are deliberately NOT allowed, so their shape coming
back trips the wire: "your-email@example.com..." (a mangled git config) and
actions@users.noreply.github.com (a 2026-07 parity probe).

HONEST LIMIT, recorded so nobody oversells this: the 2026-08-20 incident
commit (d4e4720fa, the Grok connector) was authored AND committed as the
owner's own identity with no signature — byte-indistinguishable in git
metadata from a local owner push, and an app pushing with a user-scoped
token can wear the owner's login in the pusher field too. This tripwire
catches identity anomalies: new bots, misconfigured emails, unknown
pushers, force-pushes. A perfectly disguised integration is what BRANCH
PROTECTION prevents, and that is an open owner discussion, not this script.

Stdlib-only (the workflow runs it with no pip install). ASCII-only prints.
"""

import json
import sys

ALLOWED_PUSHERS = {
    "FakeCurrency",            # the owner — also how Claude-session pushes authenticate
    "github-actions[bot]",     # every scheduled writer (scan, close, backup, backfill)
}

ALLOWED_EMAILS = {
    "github-actions[bot]@users.noreply.github.com",
    "noreply@anthropic.com",
    "294004674+FakeCurrency@users.noreply.github.com",
    "vivek@strategicnutrition.com.au",
    "vk91.vivek.kumar@gmail.com",
}


def findings_from_event(evt: dict) -> list[str]:
    """Every anomaly in the payload, as plain one-line statements. Empty list
    means the push looked like every legitimate push before it."""
    findings = []

    pusher = str((evt.get("pusher") or {}).get("name") or "")
    sender = str((evt.get("sender") or {}).get("login") or "")
    for who, field in ((pusher, "pusher"), (sender, "sender")):
        if who and who not in ALLOWED_PUSHERS:
            findings.append(
                f"UNKNOWN {field.upper()}: '{who}' pushed to main - not in the known-pusher set "
                f"{sorted(ALLOWED_PUSHERS)}. If this is a new integration or collaborator, "
                f"add it to scripts/commit_sentinel.py deliberately.")

    commits = evt.get("commits") or []
    for c in commits:
        cid = str(c.get("id") or "")[:9] or "?"
        for role in ("author", "committer"):
            email = str((c.get(role) or {}).get("email") or "")
            if email and email not in ALLOWED_EMAILS:
                findings.append(
                    f"UNKNOWN {role.upper()} EMAIL on {cid}: '{email}' "
                    f"({(c.get(role) or {}).get('name') or '?'}) - not in the observed identity set.")
            if not email:
                findings.append(f"MISSING {role} email on {cid} - malformed commit metadata.")

    # GitHub caps the payload's commits list at 20; a bigger push means part
    # of it was NOT inspected, and that fact is itself worth an alert.
    size = evt.get("size")
    if isinstance(size, int) and size > len(commits):
        findings.append(
            f"PARTIAL VISIBILITY: payload lists {len(commits)} of {size} commits - "
            f"inspect the full range {str(evt.get('before') or '')[:9]}..{str(evt.get('after') or '')[:9]} by hand.")

    if evt.get("forced"):
        findings.append(
            "FORCE-PUSH to main: history was rewritten. No legitimate writer in this "
            "repo force-pushes main.")

    return findings


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python scripts/commit_sentinel.py <github-event.json>")
        return 2
    try:
        with open(argv[0], encoding="utf-8") as fh:
            evt = json.load(fh)
    except (OSError, ValueError) as e:
        print(f"could not read event payload: {e}")
        return 2

    findings = findings_from_event(evt)
    n = len(evt.get("commits") or [])
    pusher = (evt.get("pusher") or {}).get("name") or "?"
    if not findings:
        print(f"OK: {n} commit(s) pushed by '{pusher}' - every identity known.")
        return 0
    print(f"COMMIT SENTINEL: {len(findings)} anomaly(ies) on push by '{pusher}':")
    for f in findings:
        print(f"  - {f}")
    print("Detection only - nothing was blocked or reverted. If this was you,")
    print("update the allowlist in scripts/commit_sentinel.py; if not, check the")
    print("commits above and the repo's integrations/collaborators NOW.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
