---
name: vivek5-checkin
description: "Check how Viv's Vivek 5.0 trading scanner is running and report back in plain English: today's ASX, NASDAQ and crypto scans and closing scans, the Discord plays digest, Momentum, Ignition and PhaseMap, the paper bot book, and what any GitHub 'Run failed' emails were about. Fixes small breakages itself and asks before anything that changes trades or schedules. Use whenever Viv asks how the scanner is going, whether everything is working, for a status or check-in, whether the close or the digest ran, why he is getting failure emails, or to watch a session and tell him, even if he never says check-in."
---

# Scanner check-in

Viv wants to know one thing: is the machine working, and does he need to do anything. Answer that in plain words, numbers first, Melbourne time. He is not technical ("???" was his reply to a jargon-heavy update), so the report never says generated_at, workflow, assert_staged, cron or commit.

Work from the repo (scanner/googy-boys-scanner, a Claude Code session) and the GitHub MCP tools. A session cannot reach the live site, api.github.com or cron-job.org directly; ops.yml is the window onto those (step 4).

## 1. Run the status script (one call answers most of it)

```bash
python3 -I <this skill's folder>/scripts/scanner_status.py --repo <the repo>
```

In the scanner repo the skill lives at `.claude/skills/vivek5-checkin/`, so from the repo root that is `python3 -I .claude/skills/vivek5-checkin/scripts/scanner_status.py --repo .` On Windows use the repo venv's python (`.venv\Scripts\python.exe`): there is often no `python3`, and Python there needs the `tzdata` package for time zones, which the venv has.

It fetches origin/main and prints, in Melbourne time: each market's scans this session and whether the closing scan landed, crypto's last 24 hours, the after-close lenses, the paper bot (open count against 60, loss guards, what opened or closed, names with no price or near their stop), new multi-lens alignments, and a verdict list split into LOOKS WRONG and NOT DUE YET. Add `--since "<when>"` to measure changes from the last check-in in this chat instead of the last 24 hours. Read its output before deciding anything; its flags are where to dig, not the final word (a public holiday looks like a missing session).

## 2. Check what the repo cannot see, with the GitHub tools

Load `mcp__github__actions_list`, `mcp__github__actions_get` and `mcp__github__get_job_logs` with ToolSearch. Owner `FakeCurrency`, repo `googy-boys-scanner`. Details and exact log lines are in `references/runs.md`; read it the first time you do this.

1. **Failure emails.** List the last 100 runs with no filter (newest first; a branch filter has returned old runs out of order) and keep those with conclusion `failure` since the window start. For each, classify it with the signatures in runs.md: GitHub outage, a real fault, a pull-request branch, or something Claude did. `cancelled` and `action_required` send no failure email. If there were none, say so; do not search Gmail for them (the connected inbox is not the one GitHub mails). A session sees only this repo, so if Viv says an email arrived and nothing here failed, ask him for its subject line: it may be another of his repos, cron-job.org or Cloudflare.
2. **The digest.** Read the `Post the morning digest` step of the first `morning_plays.yml` run after 17:15 (ASX) or 07:15 (US) Melbourne. Report sent with the count of new plays, or why not. A later "already went out today" is success.
3. **The kill switch and watchdog.** Read the newest `kill_switch.yml` run's log for the per-market `kill-switch OK` lines and the `watchdog:` lines. Only mention them if something triggered, or if Viv asks.

Use a subagent for the run listing when the window is long; the raw listing is large.

## 3. Judge against the normal day, not against perfection

`references/schedule.md` has the expected timeline and the list of things that look broken but are normal. The big ones:

- **cron-job.org is the real clock.** GitHub's own crons land hours late or never. A late GitHub run is not an outage when the cron-job.org path delivered.
- **The ASX close counts from 16:40 Sydney.** A scan at 16:15 is not the close.
- **NASDAQ belongs to New York's date.** At a Melbourne afternoon check-in, its book is 9 to 10 hours old by design.
- **Late by design:**
  - PhaseMap and the reco note land overnight.
  - Ignition ASX's first screen lands about 17:30 to 18:15; Ignition NASDAQ's about 08:35 to 09:30 (its bar is final at 07:30). GitHub runs both, so either can slip hours.
  - On Sundays and Mondays crypto Momentum lands 5 to 6 hours late (about 17:00).
  - Hundreds of ASX names showing a day-old price intraday is thin trading, not a fault.
- **Green does not mean fine.**
  - A failed Ops action, a triggered kill switch and a digest still refused at its last rung are all green runs.
  - A green scan run can have scanned nothing. Trust the data stamps.

## 4. Look further only when something is unexplained

- **Scans missing inside a session.** Read cron-job.org through ops.yml with `cronjob-list`. Then use `cronjob-history` with args `{"id": N}`; the job ids are in schedule.md.
- **Is the live site serving today's data?** Use ops.yml `site-probe` with paths `/api/health?market=<m>&max_h=<h>`.
- **Reading an ops run.** Judge it by its `OPS RESULT:` line, never its colour.
- **One ops dispatch at a time.** The ops queue keeps only one pending run.

## 5. Fix small, ask big

Viv's rule: he says what to do and Claude ships it (branch, PR, rebase-merge once green). For a check-in that means:

- **Fix without asking:** a clear, contained breakage in code or config that a test can cover. Use a branch, tests, a PR and a rebase-merge when green, then confirm on the next real run.
- **Ask first:** anything that changes which trades get taken, position sizes, the PhaseMap rules, cron-job.org jobs, Cloudflare settings, secrets, spending money, or deleting data.
- **Never, during a check-in:**
  - Call `/api/heartbeat`, `/api/scan`, `/api/close` or `/api/morning_plays`, even through site-probe paths. They dispatch real work and spend heal budget.
  - Re-send the digest. It posts to a real Discord channel.
  - Dispatch PhaseMap by hand. A later scheduled run then fails its must-change check and emails Viv.
  - Dispatch a mutating ops action.
  - Rerun or cancel a run you did not start.
- **Before you dispatch anything** (a missed report-only lens, an ops read), check that no run of it is already queued. A duplicate you then cancel can email Viv "Run cancelled". Your own mistakes must never reach his inbox: that was the whole point of the 6 Oct ops change.
- **Known gaps are not news.** Some are already known and only Viv can decide them: the kill switch runs about 5 times a day instead of every 30 minutes, nothing alerts him while Telegram and email are empty, and the other open decisions in schedule.md. Mention one only if it got worse or he asks. Never re-raise the ones marked declined.

## 6. Report

Use this shape and drop any section with nothing to say. Times are Melbourne with the day (Thu 16:45).

```
**[All good | One thing to look at | Broken: <what>]** <one line on why>

**Scans**
- ASX: <n> scans today, <first> to <last>. Close scan <time>.
- NASDAQ (last night): <n> scans, close scan <time>.
- Crypto: <n> in 24 h, last <time>.

**After the close**
- ASX digest: sent <time>, <n> new plays. US digest: sent <time>, <n> new plays.
- Momentum <time>. Ignition ASX <time or "not yet, usually by about 18:15">, NASDAQ <time>. PhaseMap <time>.

**Paper bot**
- <open>/60 open (ASX <a>, NASDAQ <b>, crypto <c>). <Book full, new setups skipped | n free>.
- Opened: <SYM (market)>. Closed: <SYM reason R>.
- Loss guards <clear | breached on X, new entries paused>. <Nothing unpriced | names>.

**Failure emails**
- <None since ... | time, what failed, cause in plain words, whether he needs to act>

**Done / needs you**
- <what you fixed, with the PR link> | <the one decision he has to make>
```

Rules for the words:
- Numbers first, plain words. No em dashes, no comma before "and".
- "Not due yet" is never "missing". Give the time it is due.
- Flag a risk once, in one line. Read R, not dollars, for the bot; sizes changed on 28 Sep.
- Rules' closes and his own hand closes are separate. Never pool them.
- Keep it under about 25 lines. If he asked one narrow question (did the digest go out?), answer that first in one or two lines, then add only what he would want to know.
