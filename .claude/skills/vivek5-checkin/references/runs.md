# Reading GitHub runs for a check-in

Contents: 1 listing runs · 2 why a run went red · 3 green runs that hide trouble · 4 the digest · 5 the scan gate · 6 the after-close lenses · 7 kill switch and watchdog · 8 ops.yml and cron-job.org

All tools take owner `FakeCurrency`, repo `googy-boys-scanner`. Every log line starts with a UTC timestamp; convert to Melbourne before telling Viv.

## 1. Listing runs

- `mcp__github__actions_list` method `list_workflow_runs`, no `resource_id`, perPage 100, page 1 (then page 2 if page 1's oldest `created_at` is still inside the window). Newest first. 100 runs is about 19 hours today.
- No server-side failure filter exists: keep `conclusion == "failure"` yourself. Do not pass a branch filter (it has returned old runs out of order); check `head_branch` yourself.
- One workflow: `resource_id` = the file name, e.g. `morning_plays.yml`.
- Jobs: `list_workflow_jobs` with the run id. Logs: `mcp__github__get_job_logs` with `job_id`, `return_content: true`, `tail_lines` 60 to 150. A log returns 404 until the job finishes, and forever for an outage-starved job.
- The interesting lines can sit under the next step's echoed script and ~25 lines of cleanup noise. If a tail shows only cleanup, raise `tail_lines`. The "Node.js 20 is deprecated" warning is on every run and is never the failure.

## 2. Why a run went red (a "Run failed" email)

Only `conclusion: failure` sends that email. `cancelled` (a newer run took over, or the scan queue evicted it) and `action_required` (a bot-pushed commit on a PR branch waiting for approval, zero jobs ran) send none.

**GitHub runner outage** (nothing in the scanner broke). All of these hold:
- the run is `failure` but its job is `cancelled`;
- the job has no runner (`runner_id` 0, empty `runner_name`, no steps);
- the job ended about 15 minutes after it was created, whatever its own timeout;
- `get_job_logs` gives 404, and `failed_only` says "No failed jobs found". Don't trust that call alone: it is blind to this case.

Several workflows go red in the same window, and the next run of each is green. Example: 5 Oct 2026 19:31 to 21:03 UTC (06:31 to 08:03 Tue Melbourne), seven red runs. Tell Viv: "GitHub had no machines free for about an hour and a half; nothing in the scanner broke and the next runs caught up."

**A real fault**: the job had a runner and a step failed. Read the failed step's log; the decisive line is the last `##[error]` that is not "Process completed with exit code N". Common ones:
- `ASSERT-STAGED FAILED (<label>): none of [...] has staged changes after a successful run. Output is being LOST` means the job ran but its results were not saved. In scan.yml this hard gate runs only on GitHub-scheduled runs; heartbeat runs only warn.
- `BOOK VERIFY FAIL: <problem>` means the paper book failed its self-check and nothing was saved. A "STALE" combined book heals on the next scan; a duplicate symbol or cross-market row needs fixing.
- `SCHEMA GATE FAILED` usually means a just-merged change and the data disagree.
- `ERROR scanning <m>` then `!! N market(s) FAILED to scan` is a scanner crash. Yahoo throttling alone ("batch attempt 1/4 failed (empty result (likely throttled))") is normal and almost never turns a run red.
- `Could not push after retries` means too many jobs were saving at once; the next run redoes it. close_position.yml prints its own version, `Could not push the close after 5 attempts`: the manual close did not land, and the workflow re-queues itself (up to 3 attempts). Check the next attempt before telling Viv.
- PhaseMap `a must-change gate tripped ... the healthy markets were committed, this run is red for the starved one`: usually one market (often crypto) got no data; the others published.
- `::error::morning_plays: Discord POST ... failed` or `Discord returned HTTP <n>`: the digest did not deliver; the next rung retries.

**Code checks (CI)** red on a `claude/*` branch with event `pull_request` is unmerged work in progress; main is fine. Red on `push` to main means a merged change broke a test: fix it (it does not stop the scanner).

**Something Claude did.** A red Ops run before 6 Oct 2026 could be Claude's own slip (run #32 passed `job_id`). Since then ops failures are green, so a red Ops run is an outage. A run Claude dispatched and then cancelled can email "Run cancelled".

## 3. Green runs that hide trouble

- **ops.yml**: a failed action prints `OPS RESULT: FAILED (exit N)` plus `##[error]exit N -- read the log. Green on purpose...`. Success prints `OPS RESULT: OK`.
- **kill_switch.yml**: firing prints `KILL SWITCH TRIGGERED` and `::error::KILL SWITCH TRIGGERED for: <markets>`, and the run stays green.
- **morning_plays.yml**:
  - A refusal (`slot is waiting for a post-close <market> scan`) is green. It only matters if the LAST rung also refused: 21:45 Melbourne for ASX, 10:45 for US.
  - A missing webhook (`::warning::DISCORD_MORNING_WEBHOOK_URL is not set`) is green too.
- **scan.yml**: a run whose gate printed `-> skip` scanned nothing and is green. A heartbeat run that lost its write only warns (`::warning::book not staged (manual run ...)`). Trust the data stamps.
- **momentum / ignition**: exit 3 (`published nothing - the download came back empty and the previous file was kept`) is green by design.
- **evidence_brief.yml**: exit 1 ("brief names an ISSUE") stays green.
- **commit_sentinel.yml**: an anomaly is a green run with `COMMIT SENTINEL: <k> anomaly(ies)` and a warning.

## 4. The digest (morning_plays.yml, job `digest`, step `Post the morning digest`)

- **Which run.** The first run at or after 17:15 Melbourne is the ASX slot, from cron-job.org's 06:15 UTC rung. The first at or after 07:15 Melbourne (20:15 UTC the day before) is the US slot (NASDAQ + crypto). Under AEST, or New York on EST from 2 Nov, these move: see schedule.md.
- **Which trigger.** The env block above the output shows it: `EVENT: workflow_dispatch` with `SLOT_INPUT: asx|us` is the cron-job.org ladder; `EVENT: schedule` with `SCHEDULE: 58 5 * * 1-5` (etc.) is GitHub's late backstop.
- **Delivered** prints three lines:
  1. `morning_plays: asx slot data gate passed (asx scan Thu 16:45 is past the Thu 16:40 close (Australia/Sydney)).`
  2. `morning_plays: asx slot: 6 new of 9 qualifying long plays (asx 6); 1 message(s)` (6 = tickers posted, 9 = qualifying before the 7-day de-dup).
  3. `morning_plays: delivered 1 message(s).`
- **Zero new.** "0 new of 9" (all already shared this week) and "0 new of 0" (nothing qualified) are healthy deliveries. Both still post one message.
- **Later rungs** print `slot already went out today (<Day HH:MM> Australia/Melbourne) - no-op.` That means success. `slot is before its target time` means the run came before the floor.
- **What the logs never show.** The tickers and the Discord text. The de-dup state lives in the Actions cache, not the repo.

## 5. The scan gate (scan.yml, job `gate`)

One line: `scan gate: <schedule|heartbeat>: asx <Day HH:MM> <state>; nasdaq <Day HH:MM> <state> -> <markets | skip>`. Times are market-local.
- **live**: the market is open now.
- **shut**: after the close, this means the post-close scan already landed, which is good.
- **owes its closing scan**: the close was missed and this run catches it up.
- **closing slot before the close (the other DST regime's copy)**: a late GitHub cron, harmless.

A heartbeat for crypto prints `scan gate: heartbeat:  -> crypto`.

## 6. The after-close lenses

- **Momentum** (momentum.yml, job `momentum`, step `Which market is due`). It prints one line per market, `<m> DUE|skip owes <time Z> file <time Z> - <reason>`, then `picked: <market>` or `picked: nothing due`.
  - Every finished morning_plays run triggers it, so most runs are 15-second "nothing due" runs. That is normal.
  - The screen step then prints `momentum: <m> scanned X/Y ... hits H ...` and `Pushed.`.
- **Ignition ASX and NASDAQ** (ignition_asx.yml / ignition_nasdaq.yml, job `ignition`, step `Is this run due`, both through `scripts/ignition_due.py <market>`). Only the backstops are gated (ASX `24 7,9` UTC, NASDAQ `34 22,23` UTC). `gate: run=false` after `backstop: already screened after the <market> <time> close` is a correct skip, and so is NASDAQ's `gate: intraday run landed at/after 15:30 New York`. The bar is final at 16:40 Sydney (ASX) and 16:30 New York (NASDAQ).
- **Ignition crypto** (ignition.yml). It publishes the new UTC bar at about 16:45 to 17:00 Melbourne via its 05:44 UTC cron, because the 00:14 UTC primary has not fired in days.

## 7. Kill switch and watchdog (kill_switch.yml, job `check`)

- **Kill switch.** Each market prints `kill-switch OK [<m>] - book P&L $<x> / limit -$4500.00 (<n> open, <k> live-priced)`.
  - Its "book P&L" is whole-life, not the guard's day figure, so the two never match.
  - GitHub runs it about every 4 to 7 hours, not every 30 minutes. That is a known gap and Viv's decision.
- **Watchdog.** `watchdog: N finding(s), M alerted, K recovered (live, host=kill_switch)`, then `watchdog:   [CRITICAL|WARNING] <msg>` lines.
  - "alerted" reaches nobody: Telegram and email are empty.
  - The `kill_switch.yml: last successful run Xh ago (limit 2h)` CRITICAL is chronic, from the throttling above.
  - The `crypto_bot.yml` WARNING is noise: crypto is scanned by the heartbeat through scan.yml now.

## 8. ops.yml and cron-job.org

**Dispatching an ops read**
1. `mcp__github__actions_run_trigger` method `run_workflow`, workflow_id `ops.yml`, ref `main`, inputs `{"action": "<action>", "args": "<JSON as a string>"}`.
2. Find the newest ops run, wait until it completes (15 to 30 s), get its job, read the log.
3. The result is `ops: <action> -> HTTP <status>`, then JSON, then `OPS RESULT: OK` or `OPS RESULT: FAILED (exit N)`. Exit codes: 1 HTTP error, 2 bad args or missing secret, 3 network, 4 unexpected.
4. Dispatch one at a time: the `ops` queue keeps only one pending run.

**Actions**
- **Safe in a check-in**: `cronjob-list`, `cronjob-history` (args `{"id": N}`), `cronjob-get`, `cf-deployments`, `site-probe`.
- **Never without asking**: `cronjob-create/update/delete`, `cf-set-var`, `cf-delete-var`, `cf-redeploy`.
- **If a secret is missing or gives HTTP 401/403**: tell Viv, since no email will.

**Reading cron-job.org output**
- **cronjob-list**: per job `lastStatus` (1 = cron-job.org got HTTP 2xx), `lastExecution` and `nextExecution` (unix seconds UTC).
- **cronjob-history**: `{"history": [newest first: date, datePlanned, httpStatus, status, statusText, duration], "predictions": [...]}`.
- **No body in either.** `body` is false, so you cannot see whether a ping actually started a scan. The funnel ledger's `heartbeat` trigger (the status script prints `h`) is where a heal shows up.
- **What a status means.** The heartbeat answers 200 whether it did nothing (market fresh) or dispatched a scan. A 503 means it could not heal, or could not tell: no token, the cap of 30 heals per market per day, GitHub refused the dispatch or timed out (a timeout may still have started a scan), or the site could not read its own data file. The body is not saved, so the scan ledger is how you tell which: a scan at that hour means it went through.
- **A missed scan inside a session.** Match the gap to the job's ping at that hour (`datePlanned`):
  - **No entry at all:** cron-job.org did not fire.
  - **One 503 between 200s:** GitHub refused or dropped that one request. It needs nothing, because the next ping catches up. Example: the 02:10 NASDAQ ping on Thu 8 Oct 2026 got a 503 and no scan started; 03:10 was 200. Tell Viv "the timer fired on time, GitHub didn't take that one request, the next hour caught up".
  - **Repeated 503s:** a real problem (token, cap or GitHub). Say which and ask.

**Checking the live site**
- `site-probe` with `{"paths": [...]}`, up to 10 site-relative GETs.
- **Only age brackets come back.** Each `/api/health` row returns status and `ok` only, not the age. To estimate an age, probe one market at several `max_h` values (1 to 48).
- **Never put a write endpoint in `paths`**: `/api/heartbeat`, `/api/scan`, `/api/close` or `/api/morning_plays`.
- **Is main live?** `cf-deployments` lists the last 8 production deploys with commit and status.
