# Vivek 5.0 on a VPS — design v2 (2026-09-26)

Owner ask: "I believe I'm ready to push the googy scanner to my VPS server."
The repo had no VPS path: every scheduled job is a GitHub Actions workflow,
the site is Cloudflare Pages, the API is Pages Functions (Workers runtime +
KV), and git is the data store. This is the contract for the kit under
`deploy/`, the `scanner/vps` job runner, and the small in-tree changes that
make the same code run on one Linux box.

v1 was reviewed by three adversarial passes (book safety, operations,
security) that REPRODUCED the failures rather than inferring them. v2 folds
every blocker and major in. The machine-readable transcriptions of the
workflows the builders work from live beside the session, not in git.

## 0. Decisions

| # | Decision | Why |
|---|----------|-----|
| D1 | **systemd timers + a Python 3.12 venv**, not Docker, not a bespoke scheduler | tz-aware `OnCalendar=... Australia/Sydney` (verified across all four 2026/27 DST changeovers), `Persistent=true` fires a missed timer ONCE after a reboot, journald logs, `flock` mutexes, `systemd-analyze verify/calendar` usable in CI |
| D2 | **Git publishing stays ON**: the VPS commits+pushes data to `main` as Actions do | least-change: Cloudflare Pages keeps deploying as a mirror, GitHub history/backups/Claude sessions keep working. Turning it off needs a data-root refactor (follow-up) |
| D3 | **The Pages Functions run UNCHANGED on the VPS under a thin Node adapter** | `_prices.js` alone is ~450 lines of hard-won Yahoo/Binance logic with JS tests; a Python port would drift. Verified: all 11 modules import as native ESM on Node 22 |
| D4 | **`_dispatch.js` gains ONE alternate transport: `DISPATCH_URL` + `DISPATCH_TOKEN`** (https or loopback only) | a "dispatch" on the VPS starts a LOCAL job. Same code path for Phase 1 (Cloudflare Functions -> VPS) and Phase 2 (adapter -> itself) |
| D5 | **One writer, enforced three ways**: cutover disables 15 workflows and drains in-flight runs; the publish step HALTS (fail-closed) on any non-VPS data commit upstream; a `vars.VPS_ACTIVE` job guard makes a re-enabled book-writer workflow a no-op | the 30-position cap is global; two writers is the one failure that cannot be undone |
| D6 | **Publish from a dedicated clone, never from the working checkout; whole-file re-apply, never a git merge of JSON** | reproduced: `git pull --rebase` refuses the dirty tree every scan leaves; `-X theirs` silently dropped a hand close from the book JSON; a modify/delete conflict wedged every later job |
| D7 | **Phase 1 already needs TLS, therefore a hostname**: Caddy from day one, API bound to 127.0.0.1 | Workers `fetch` validates public CAs; plain http would carry the bearer token in clear; the PWA service worker needs a secure context |
| D8 | **An alert channel is a cutover PRECONDITION** | Telegram/SMTP are unconfigured and Discord alerts were removed by owner ruling; cutover deletes GitHub's red-run email, the last alarm. A failing VPS must not be silent by design |
| D9 | Vendor repos for Node 22 and Caddy >= 2.8, never Ubuntu's apt versions | apt has Node 18 (cannot load these ESM files without a package.json) and Caddy 2.6.2 (no `basic_auth`) |
| D10 | No trade-logic change. Nothing under `scanner/broker/` is edited. New constants go in `scanner/config.py` (`VPS_*`) | CLAUDE.md |

## 1. Layout on the box (Ubuntu 24.04, box clock = UTC)

```
/opt/vivek5/app        the WORKING checkout (full clone of main): jobs run here, files are written here.
                       Its HEAD tracks origin/main; it NEVER commits. Tracked data files are dirty by design.
/opt/vivek5/publish    the PUBLISH clone (--filter=blob:none, ssh remote): the ONLY place git commits/pushes happen.
/opt/vivek5/venv       python3.12 venv (requirements.txt), pre-compiled, read-only at runtime
/opt/vivek5/state/     spool/ spool/.tmp spool/done spool/failed  locks/  summaries/  home/  cache/
                       kv.json  runs.json  publish_head  HALT (present only when halted)
/etc/vivek5/jobs.env   secrets + settings for the JOB units       0640 root:vivek5
/etc/vivek5/api.env    the API adapter's env ONLY                 0640 root:vivek5-api
/etc/vivek5/deploy_key ed25519 deploy key (write, this repo)      0640 root:vivek5
/etc/vivek5/known_hosts github.com host keys, pre-seeded
/etc/caddy/Caddyfile   from deploy/caddy/Caddyfile.phase1 or .phase2
/etc/systemd/system/vivek5-*.{service,timer,path}   COPIED by install.sh (never symlinked into the checkout)
/etc/sudoers.d/vivek5  exactly: vivek5 may `systemctl restart vivek5-api.service` and `systemctl reload caddy`
```
Users: `vivek5` (jobs, owns app/publish/venv/state) and `vivek5-api` (the Node
adapter; member of group `vivek5-spool`). `state/spool` is setgid group
`vivek5-spool`, group-writable, so the adapter can create and the runner can move.
Repo-relative state persists in the checkout: `.cache/` (frame cache, watchdog
state, morning-plays state) — this is an improvement over actions/cache.
**`.scan-skipped` is per-run: the runner deletes it before the first
`scanner.run` of every scan-family job and reads it only after its own runs.**
The four tracked-but-never-staged files (`journal/alert_state.json`,
`public/data/crypto_arriving.json`, `data/universe_cache/{nasdaq,crypto}.json`,
`data/notified_signals.json`) stay dirty in the working checkout and are never
published — named decision: alert rate limits now persist across runs (they
died with the Actions container); nothing else changes.

## 2. Components and file ownership

| Comp | Files | Builder |
|------|-------|---------|
| C1 job runner | `scanner/vps/{__init__,__main__,jobs,gate,ledger,publish,spool,locks,notify}.py`; `VPS_*` block in `scanner/config.py`; `tests/test_vps_jobs.py`, `tests/test_vps_publish.py` | build-jobs |
| C2 host kit | `deploy/systemd/*`, `deploy/bin/{install,update,preflight,cutover,rollback,job,gc}.sh`, `deploy/caddy/Caddyfile.phase1`, `deploy/caddy/Caddyfile.phase2`, `deploy/env/jobs.env.example`, `deploy/env/api.env.example`, `deploy/journald.conf`; `tests/test_vps_deploy.py` | build-host |
| C3 API adapter | `deploy/api/server.mjs`, `deploy/api/shims.mjs`, `deploy/api/dispatch.mjs`; `functions/package.json` (+ `.gitignore` negation); `functions/api/_dispatch.js`; the four endpoints' "configured" check; `test/vps_api.test.js` + its step in `.github/workflows/test.yml` | build-api |
| C4 couplings | `scanner/watchdog.py` (ledger mode, failed-run finding, disk_low); `scripts/ops.py` `vps-dispatch` action; `vars.VPS_ACTIVE` job guards in scan.yml / crypto_bot.yml / close_position.yml / dispatch_scan.yml; tests | build-couplings |
| C5 docs | `deploy/README.md` (runbook), CLAUDE.md section, OPERATIONS.md/README.md pointers | docs (after verify) |

Contract rule: C2's units invoke ONLY the C1 CLI below; C3 writes ONLY the
spool format below; C4 reads ONLY the ledger format below. Any change to
these three interfaces is a change to this file first.

## 3. Interfaces

### 3.1 CLI — `python -m scanner.vps` (cwd = /opt/vivek5/app, run by job.sh)
```
run <job> [key=value ...]      full job: preflight -> gate -> locks -> steps -> publish -> ledger
gate <job> [key=value ...]     exit 0 due / 3 not due (prints why); no locks, no side effects
drain-spool                    execute queued dispatches (oldest first)
notify-failure <unit>          OnFailure= hook: alert_router + state/alerts.log + ledger
ledger [--json]                print runs.json
list                           print the JOBS table
accept-upstream                clear HALT: sync data roots FROM origin/main into the working checkout (operator action)
clear-halt                     clear HALT without syncing (operator has fixed it by hand)
```
`run` exit codes: 0 ok · 3 skipped-by-gate (ledger `skipped`) · 4 halted
(ledger `halted`) · 1 failure. `key=value` args are OPERATOR-ONLY where marked
in the JOBS table (`extra`, `args`, `force`, `dry_run`); the spool drainer
drops them. Job names are the GitHub workflow file names.

Runner order inside `run`: (1) refuse if `state/HALT` exists and the job is a
book writer (exit 4); (2) evaluate the gate AT FIRE TIME; (3) acquire locks:
`repo` shared, then the job's family lock, then the job's own lock — lock
WAIT (`lock_wait_s`, default 7200 for scan-lock jobs, 600 otherwise) is
separate from the step timeout; (4) re-check "still worth running" for
slots that define it; (5) delete `.scan-skipped` for scan-family jobs; (6)
run steps sequentially, fail-fast unless `continue_on_error`; (7) publish;
(8) write the ledger row (always, including on failure). Step output goes to
the journal unchanged. `GITHUB_STEP_SUMMARY=state/summaries/<job>-<utc>.md`,
`GITHUB_OUTPUT=<tempfile>` (momentum_due), `GITHUB_SHA=$(git rev-parse HEAD)`.

### 3.2 JOBS table (`scanner/vps/jobs.py`) — TRANSCRIBED from the workflows
```
Job(name="scan.yml", slots={"hourly","close","backstop","manual"},
    args={"market": {"asx","nasdaq","crypto","all"}, "reason": {"cron","manual","heartbeat"}, "slot": ..., "extra": OPERATOR_ONLY},
    locks=("scan",), family="scan",
    gate=gate.scan_gate, steps=[...], publish=Publish(paths=[...], must_change={...}, message="data: scan {utc} UTC", rebuild_combined=True),
    timeout_s=7200, lock_wait_s=7200, heavy=False)
```
One entry per workflow that runs on the VPS: scan, crypto_bot, kill_switch,
phasemap, confluence, reco_note, backup_book, alert_returns, evidence_brief,
lens_backtest, vivek_backtest, morning_plays, momentum, close_position.
Steps, env, staging lists, must-change sets, commit messages and the
manual-vs-scheduled assert branches come from the transcriptions; the runner
must not invent them. Where a workflow step is Actions-only (checkout, pip
install, actions/cache, upload-artifact, redispatch, the `gh` calls, the
Discord failure ping, `git reset --hard`/`git add -A`) the JOBS table records
it as `dropped: <reason>` so a reader can audit the mapping.

Lock families: `scan` = book mutex (scan, crypto_bot, close_position,
confluence). `heavy` = phasemap, lens_backtest, vivek_backtest,
alert_returns, momentum (one heavy job at a time). `repo` = the working
checkout: every job holds it SHARED for its whole run; `update.sh` and
`gc.sh` take it EXCLUSIVE (non-blocking, skip + count). `publish` = the
publish clone, exclusive, held only during the publish step. kill_switch,
backup_book, reco_note, evidence_brief: own-name lock only.

### 3.3 Gates (`scanner/vps/gate.py`) — import config, never re-type numbers
* `scan_gate(market, slot)`:
  - `hourly`: weekday in the market's zone AND minute-of-day inside
    `config.MARKET_SCAN_WINDOWS[market]` (inclusive both ends) at FIRE time.
    No re-check after the lock.
  - `close` and `backstop`: weekday, local time >= 16:00, AND no post-close
    scan for today yet — "post-close" = `public/data/<market>_prices.json`
    `generated_at` at/after today's `config.MORNING_PLAYS_SLOT_GATE` time for
    that market (reuse `scripts.morning_plays.scan_is_post_close` or its
    helper; do not re-type the times). Re-checked after acquiring the lock:
    if a post-close scan landed while waiting, skip. No upper bound: a
    reboot-late close scan is still the post-close scan the digest needs.
  - `manual` (spool/API/operator): no window gate (parity with
    workflow_dispatch). `market=all` is reachable only here.
  - Probe failure (tz database unusable): fail OPEN to `all`, WARNING —
    parity with the YAML.
* `crypto_gate(slot)`: `hourly` always runs; `backstop` (:52) skips when the
  LOCAL `public/data/crypto_vivek.json` is fresher than the workflow's
  threshold (transcribe crypto_bot.yml; it was 3900 s against the deployed
  site — the source moves to the checkout, README says so).
* `backup_gate(slot)`: `backstop` skips when today's `backups/<date>T…`
  directory exists (transcribe).
* `alert_returns_gate(slot)`: `backstop` skips when the LEDGER shows a
  success for alert_returns.yml today (replaces the Actions-API check).
* `momentum_gate()`: `scripts/momentum_due.py` decides (`market=` output);
  empty -> skipped.
* morning_plays: no runner gate; the script's own `--slot` + per-day marker
  + post-close gate decide (transcribe the cron->slot mapping: asx / us).
* Everything else: no gate.

### 3.4 Publish (`scanner/vps/publish.py`) — the whole-file re-apply loop
Runs under `publish` (exclusive) while still holding `repo` (shared).
```
P = job.publish.paths (files and directory pathspecs), M = job.publish.must_change
1. cd /opt/vivek5/publish; git fetch origin main; git reset --hard origin/main; git clean -fdq
2. SECOND-WRITER CHECK (fail-closed): for every commit in <state/publish_head>..origin/main
   that touches a DATA ROOT (union of every job's publish paths) and whose author is not the VPS
   identity (GIT_AUTHOR_NAME + GIT_AUTHOR_EMAIL from jobs.env) -> write state/HALT (json: shas,
   authors, paths), notify(CRITICAL), ledger `halted`, exit 4. Do not push. Book-writer jobs refuse to
   run while HALT exists; `accept-upstream` / `clear-halt` clear it.
3. for p in P: if p exists in the working checkout -> copy it in (file: cp --preserve=timestamps;
   directory pathspec: rsync -a --delete); else leave the clone's copy as origin has it (the YAML's
   `cat-file -e` rule). Then `git add -- p` (one pathspec per call; a missing path logs and continues).
4. if job.publish.rebuild_combined: run `<venv>/bin/python -m scanner.broker.vivek_run --rebuild-combined`
   with cwd=/opt/vivek5/publish and PYTHONPATH unset (so the clone's own package resolves ROOT to the
   clone), then `git add` the two derived files. Then `--verify` there too; a STALE verdict is a failure.
5. MUST-CHANGE: `git diff --cached --quiet -- <m>` for m in M, with the workflow's ANY-OF / per-market /
   manual-branch semantics. A scan-family job downgrades a market's hard assert to a warning only if
   THIS run's `.scan-skipped` names that market. Nothing staged where something must be -> exit 1
   (assert_staged parity), publish clone reset, alert.
6. git -c user.name=$GIT_AUTHOR_NAME -c user.email=$GIT_AUTHOR_EMAIL commit -q -m "<message>"
7. git push origin HEAD:main. On rejection: sleep 2**attempt, go to 1 (max 5). Any other git error:
   `git reset --hard origin/main` in the clone, alert, exit 1. Never leave the clone mid-operation.
8. On success: state/publish_head = pushed sha; ledger row gets `pushed: <sha>`.
```
The working checkout is NOT touched by publish. Its HEAD is advanced by
`update.sh` (§3.7). Journal/stderr from git is REDACTED before it reaches the
ledger (`https://…@` -> `https://***@`, `Bearer \S+` -> `Bearer ***`); the
ledger stores exit code + one redacted last line, never full output.

### 3.5 Spool (written by C3, read by C1 `drain-spool`)
File: `state/spool/<YYYYMMDDTHHMMSSZ>-<8hex>.json`, written to `spool/.tmp/`
and `rename()`d into place (atomic). Body, and nothing else:
```json
{"id":"20260926T214400Z-1a2b3c4d","received_at":"2026-09-26T21:44:00Z",
 "workflow":"scan.yml","inputs":{"market":"asx","reason":"manual"},"source":"api/scan"}
```
Allowed `workflow` values and their VALIDATED input shapes (copied from the
Functions' own validators; anything else is refused by the adapter and, as
defence in depth, by the drainer):
* `scan.yml`: `market` in {asx,nasdaq,crypto,all}; `reason` in {manual,heartbeat}.
* `close_position.yml`: single: `symbol` /^[A-Z0-9.\-]{1,15}$/, `market` in
  {asx,nasdaq,crypto}, `direction` in {long,short}, `price` finite > 0,
  `exit_date` YYYY-MM-DD or '', `journal_type` in {bot,swing,scalp}; batch:
  `journal_type=bot` + `closes` (1..30 entries, each re-validated, re-serialised).
  The batch reaches the job as the `VIVEK_CLOSE_BATCH` ENV value, never argv.
* `morning_plays.yml`: `slot` in {asx,us}.
* `momentum.yml`: no inputs (internal chain only: the morning_plays job spools
  one at its end — the `workflow_run` equivalent).
`drain-spool`: only names matching the regex; `lstat` and skip symlinks;
size cap 16 KiB; parse errors record the exception TYPE only; a file moves to
`done/` only AFTER its job exits 0/3, to `failed/` after exit 1/4; if a move
fails, rename in place to `.stuck` so the `.path` unit stops re-firing.
Spool-driven jobs take the scan lock with the long blocking wait. The
`.path` unit uses `DirectoryNotEmpty=` and its service has
`StartLimitIntervalSec=0`.

### 3.6 Runs ledger `state/runs.json` (atomic temp+replace)
```json
{"scan.yml": {"last_start":"…","last_end":"…","last_status":"ok|failed|skipped|halted",
  "last_exit":0,"last_args":{"market":"asx","slot":"hourly"},"last_success_at":"…",
  "last_failure_at":"…","last_skip_at":"…","consecutive_failures":0,"waited_s":12,
  "pushed":"<sha>","last_line":"<redacted>","host":"vps"}, "crypto_bot.yml": {…}, "update": {…}}
```
Keys are workflow file names (all scan units write under `scan.yml`), plus
`update` and `gc`. Watchdog ledger mode (`VIVEK_RUNS_LEDGER` set) per
`WATCHDOG_RUNS` key: `last_failure_at` newer than `last_success_at` ->
finding `run_<wf>_failed` at the table's severity (CRITICAL for
kill_switch/backup_book/scan/crypto_bot), deduped/reminded/recovered by the
existing state machine; else age = now - max(last_success_at, last_skip_at)
(a gate-skip concluded `success` on Actions; keep that parity),
`session_aware` unchanged. GitHub mode is untouched. Also in ledger mode:
`disk_low` CRITICAL when free space under the checkout < `VPS_DISK_MIN_GB` (3).

### 3.7 `update.sh` (timer, every 5 min, user vivek5)
Takes `repo` EXCLUSIVE non-blocking; if any job holds it shared, record
`update: skipped busy` and bump a counter (alert after 12 consecutive = 1 h).
Otherwise, in the working checkout: `git fetch origin main`; if HEAD ==
origin/main exit 0. Else: compute `git diff --name-status HEAD origin/main`.
If any changed path is a DATA ROOT and was authored by a non-VPS identity
since `state/publish_head` -> HALT exactly as §3.4 step 2 (do not sync).
Otherwise `git reset -q --mixed origin/main` (HEAD + index move, worktree
untouched), then for each changed NON-data path: `git checkout -q origin/main
-- <path>` (or remove it if deleted upstream). Data paths are never checked
out (the working files are the newer-or-equal truth on a single-writer box).
Then: `requirements.txt` hash changed -> `pip install -r requirements.txt`;
`functions/**` or `deploy/api/**` changed -> `sudo systemctl restart
vivek5-api.service`; `deploy/systemd/**`, `deploy/caddy/**`, `deploy/bin/**`
changed -> notify(WARNING "re-run install.sh --units") — update.sh never
touches /etc. Ledger row `update` every run.

### 3.8 Environment
`jobs.env` (units: every vivek5-* job, update, gc): `VIVEK_HOME=/opt/vivek5/app`,
`VIVEK_PUBLISH=/opt/vivek5/publish`, `VIVEK_STATE_DIR=/opt/vivek5/state`,
`VIVEK_VENV=/opt/vivek5/venv`, `VIVEK_GIT_PUBLISH=1`,
`VIVEK_RUNS_LEDGER=/opt/vivek5/state/runs.json`, `GIT_AUTHOR_NAME=vivek5-vps`,
`GIT_AUTHOR_EMAIL=<an email already in scripts/commit_sentinel.py ALLOWED_EMAILS,
default the owner's GitHub noreply>` (+ COMMITTER twins),
`GIT_SSH_COMMAND=ssh -i /etc/vivek5/deploy_key -o IdentitiesOnly=yes -o
UserKnownHostsFile=/etc/vivek5/known_hosts -o StrictHostKeyChecking=yes`,
`HOME=/opt/vivek5/state/home`, `XDG_CACHE_HOME=/opt/vivek5/state/cache`,
`WATCHDOG_HOST=vps`, `VIVEK_BACKUP_TARGET=` (optional rsync/scp target for
off-box backups; if set the backup job fails when the copy fails), and every
secret the workflows pass through: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
`GBS_SMTP_HOST/PORT/USER/PASS`, `GBS_ALERT_TO/FROM`,
`DISCORD_MORNING_WEBHOOK_URL`, `BYBIT_API_KEY/SECRET`, `BYBIT_TESTNET`,
`ALPACA_API_KEY/SECRET_KEY`. Template values are `CHANGE_ME`; preflight
refuses any that remain. No leading `-` on any `EnvironmentFile=`.
`api.env` (vivek5-api only): `PORT=8787`, `VIVEK_PUBLIC_DIR=/opt/vivek5/app/public`,
`VIVEK_STATE_DIR`, `VIVEK_BOOK=/opt/vivek5/app/journal/vivek_bot_book.json`,
`DISPATCH_URL=http://127.0.0.1:8787/api/dispatch`, `DISPATCH_TOKEN` (>= 32
random bytes, generated by install.sh), `MORNING_PLAYS_TRIGGER_SECRET`,
`TRUST_PROXY=1`, `VIVEK_PHASE=1|2`, `EODHD_API_TOKEN` (optional). NO broker,
SMTP, Telegram, Discord or git credential ever appears here (test-pinned).
Cutover only: `GH_ADMIN_TOKEN` read from the calling shell's environment (or
`read -rs`), never from a file; scripts `trap unset` it; `set -x` is banned
in deploy/bin (test-pinned).

## 4. Schedule (systemd) — every line verified with `systemd-analyze calendar`

Every timer: `Persistent=true`, `AccuracySec=1s`; market/close/backstop timers
`RandomizedDelaySec=0`; heavy jobs may take `RandomizedDelaySec=10min`.
Every oneshot service: `TimeoutStartSec=` = the workflow's timeout-minutes,
`KillMode=mixed`, `OnFailure=vivek5-failed@%n.service`, `User=vivek5`,
`ProtectSystem=strict`, `ReadWritePaths=/opt/vivek5/app /opt/vivek5/publish
/opt/vivek5/state`, `ProtectHome=yes`, `PrivateTmp=yes`, `NoNewPrivileges=yes`,
`LogRateLimitIntervalSec=0`; heavy jobs `Nice=10`, `MemoryHigh=`, backtests
`IOSchedulingClass=idle`.

| Unit (all `vivek5-` prefixed) | OnCalendar lines | Runner invocation |
|------|-----------|------|
| scan@asx | `Mon..Fri *-*-* 11..15:07 Australia/Sydney` and `Mon..Fri *-*-* 16:07 Australia/Sydney` | `run scan.yml market=asx slot=hourly reason=cron` |
| scan-close@asx | `Mon..Fri *-*-* 16:30 Australia/Sydney` | `run scan.yml market=asx slot=close reason=cron` |
| scan-backstop@asx | `Mon..Fri *-*-* 17:15 Australia/Sydney` | `run scan.yml market=asx slot=backstop reason=cron` |
| scan@nasdaq | `Mon..Fri *-*-* 10:37 America/New_York` and `Mon..Fri *-*-* 11..15:07 America/New_York` | `run scan.yml market=nasdaq slot=hourly reason=cron` |
| scan-close@nasdaq | `Mon..Fri *-*-* 16:07 America/New_York` | `run scan.yml market=nasdaq slot=close reason=cron` |
| scan-backstop@nasdaq | `Mon..Fri *-*-* 17:15 America/New_York` | `run scan.yml market=nasdaq slot=backstop reason=cron` |
| crypto-bot | `*-*-* *:22 UTC` | `run crypto_bot.yml slot=hourly` |
| crypto-bot-backstop | `*-*-* *:52 UTC` | `run crypto_bot.yml slot=backstop` |
| kill-switch | `*-*-* *:15,45 UTC` | `run kill_switch.yml` |
| phasemap | `*-*-* 08:30 UTC` | `run phasemap.yml` |
| confluence | `*-*-* 08:45 UTC` | `run confluence.yml` |
| reco-note | `*-*-* 08:52 UTC` | `run reco_note.yml` |
| backup-book | `*-*-* 21:35 UTC` | `run backup_book.yml slot=primary` |
| backup-book-backstop | `*-*-* 23:35 UTC` | `run backup_book.yml slot=backstop` |
| alert-returns | `*-*-* 22:20 UTC` | `run alert_returns.yml slot=primary` |
| alert-returns-backstop | `*-*-* 23:50 UTC` | `run alert_returns.yml slot=backstop` |
| evidence-brief | `*-*-* 21:00 UTC` | `run evidence_brief.yml` |
| lens-backtest | `Sun *-*-* 08:00 UTC` | `run lens_backtest.yml` |
| vivek-backtest | `*-*-01 08:00 UTC` | `run vivek_backtest.yml` |
| morning-plays@asx | `Mon..Fri *-*-* 06..10:15,45 UTC` | `run morning_plays.yml slot=asx` |
| morning-plays@us | `Mon..Fri *-*-* 20..23:15,45 UTC` | `run morning_plays.yml slot=us` |
| momentum | `Mon..Fri *-*-* 06:30 UTC`, `Mon..Fri *-*-* 21:30 UTC`, `*-*-* 00:30 UTC`, `*-*-* 0/3:41 UTC` | `run momentum.yml` (+ spooled by morning_plays) |
| update | `*-*-* *:0/5 UTC` | `deploy/bin/update.sh` |
| gc | `Sun *-*-* 03:00 UTC` | `deploy/bin/gc.sh` (`git gc --prune=2.weeks.ago`, both clones, exclusive repo lock) |
| spool.path | `DirectoryNotEmpty=/opt/vivek5/state/spool` | `drain-spool` |
| api.service | long-running | `node deploy/api/server.mjs` as vivek5-api, `Restart=on-failure`, `RestartSec=5`, `StartLimitIntervalSec=0`, `MemoryMax=512M`, `EnvironmentFile=/etc/vivek5/api.env` only |
| failed@.service | template | `notify-failure %i` (journalctl -u %i -n 30 attached) |

Why 17:15 for the backstops: the GitHub `:47` backstops were dead code (the
market window ends 16:45 and the YAML gate applies the window first). The
VPS backstop instead re-fires the close-slot rule (post-close stamp missing)
after the close scan had time to fail; the window gate does not apply to
close/backstop slots (§3.3). The `.path` chain for momentum after
morning_plays reproduces `workflow_run`.

## 5. API adapter (C3)
`deploy/api/server.mjs`: Node >= 22, ESM, `http.createServer` on 127.0.0.1:PORT.
Routes `/api/<name>` to `functions/api/<name>.js` (`onRequestGet/Post/Head`
or `onRequest`) with a Workers-shaped `{request, env, waitUntil}`; builds a
WHATWG `Request` from the Node request with `CF-Connecting-IP` set from the
LAST hop of `X-Forwarded-For` only when `TRUST_PROXY=1` AND the TCP peer is
loopback, else the socket address. Shims (`shims.mjs`): `env.JOURNAL_KV`
{get, put(expirationTtl), delete} file-backed at `state/kv.json` (TTL
honoured, flushed on write); `env.ASSETS.fetch(Request)` serving
`VIVEK_PUBLIC_DIR` (path-normalised, no traversal); `globalThis.caches.default`
{match, put} in-memory LRU (~50 MB) honouring `s-maxage`; `ctx.waitUntil`.
`VIVEK_PHASE=1` serves ONLY `/api/dispatch`, `/api/vps`; `VIVEK_PHASE=2`
serves all Functions plus those two. Request logging = method + path only.
`/api/dispatch` (`dispatch.mjs`): POST only, body <= 16 KiB, bearer token
compared with `crypto.timingSafeEqual`; no `DISPATCH_TOKEN` -> 503, wrong ->
401; typed per-workflow validation exactly as §3.5 (unknown workflow or key
-> 400, never spooled); close sanity: symbol/market must be OPEN in
`VIVEK_BOOK` and price within `config`'s `VIVEK_MARK_SANITY_PCT[market]` of
the row's `last_mark` -> else 422 naming the mark (operator override is the
CLI on the box); per-key cooldown 5 min + daily caps (scan 40, close 60,
morning_plays 12) in the kv shim; spool depth > 20 -> 429; success -> 202
`{ok:true, id}`. `/api/vps` GET: `{ok, halted, jobs:{...}}` from runs.json,
503 when HALT exists or a CRITICAL-severity job's last run failed.
`functions/api/_dispatch.js`: when `env.DISPATCH_URL` is set, POST
`{workflow, inputs}` there with `Authorization: Bearer <DISPATCH_TOKEN>`;
refuse a URL that is not `https:` and not loopback (`{ok:false,status:0}`);
map 202 -> `{ok:true}`, other statuses -> `{ok:false,status}` with the same
refund rule; never echo the body. scan.js/close.js/heartbeat.js/
morning_plays.js: "configured" = `env.DISPATCH_URL || env.GH_DISPATCH_TOKEN`
(GitHub path and its tests unchanged when DISPATCH_URL is unset).
`functions/package.json` = `{"type":"module"}` (un-ignored; inert on Pages).

## 6. Caddy
`Caddyfile.phase1`: `{$VIVEK_DOMAIN}` site; `handle /api/dispatch` and
`handle /api/vps` -> `reverse_proxy 127.0.0.1:8787 { header_up
X-Forwarded-For {http.request.remote.host} }`; everything else 404. Optional
`remote_ip` allow-list block (Cloudflare egress ranges) left commented with
the reason. `Caddyfile.phase2`: `root * /opt/vivek5/app/public`,
`file_server`, `encode zstd gzip`, headers mirroring `public/_headers`
(`/js/*`, `/css/*` -> `public, max-age=86400`; everything else `public,
max-age=0, must-revalidate`; `X-Content-Type-Options nosniff`), `handle
/api/*` -> the adapter, **`basic_auth` ON by default for `/api/scan` and
`/api/close`** (`{$VIVEK_API_BASIC_USER}` / `{$VIVEK_API_BASIC_HASH}` from
`caddy hash-password`, read from `/etc/caddy/vivek5.env`), `/api/health`,
`/api/heartbeat`, `/api/price`, `/api/quote` open, access log with the
`key` query parameter deleted. No `:80`/IP-only branch: a hostname is
required (README offers Cloudflare Tunnel as the no-open-port alternative).

## 7. Cutover (`deploy/bin/cutover.sh`), in this order, abort on any failure
0. `preflight.sh` green: Ubuntu 24.04; `timedatectl` UTC + NTP synced; node >= 22, caddy >= 2.8,
   python 3.12 venv imports (pandas, numpy, yfinance, requests, pybit, yaml) at the pinned versions;
   >= 20 GB free; `systemd-analyze calendar` on every OnCalendar line and `systemd-analyze verify` on
   every installed unit; no `CHANGE_ME` in either env file, modes 0640; `git push --dry-run` from the
   publish clone succeeds via the deploy key; `VIVEK_DOMAIN` resolves to this box and
   `https://$VIVEK_DOMAIN/api/vps` answers; egress: Yahoo chart, Binance ping, api.github.com status
   codes printed; **an alert channel round-trips** (`python -m scanner.watchdog --test-alert` reports a
   delivered channel) — refused otherwise unless `VIVEK_ACCEPT_NO_ALERT_CHANNEL=1` is set in the shell,
   which the script prints as a standing risk; the ASX dry run's max RSS is printed for sizing.
1. `systemctl enable --now vivek5-api.service` (Phase 1 Caddyfile) — external check of `/api/vps`.
2. Cloudflare Pages env: set `DISPATCH_URL=https://$VIVEK_DOMAIN/api/dispatch` + `DISPATCH_TOKEN`,
   then DELETE `GH_DISPATCH_TOKEN` (via ops.yml `cf-set-var` / `cf-delete-var`, or the dashboard).
   From here every SCAN/close/heal request spools to the VPS and nothing can dispatch to GitHub.
3. GitHub, with `GH_ADMIN_TOKEN` (fine-grained, this repo, Actions: read+write, Variables: write):
   disable the 15 workflows (13 scheduled + close_position.yml + dispatch_scan.yml), GET each until
   `state == disabled_manually`; set repository variable `VPS_ACTIVE=1`.
4. Drain: poll `actions/runs?status=queued|in_progress` for those 15 until none remain (timeout 30 min).
5. Working checkout: `git fetch && git reset --hard origin/main` (pristine start from the last Actions
   commit); publish clone: `git fetch && git reset --hard origin/main`; `state/publish_head` = that sha.
6. `systemctl enable --now` every timer, `vivek5-spool.path`, `vivek5-update.timer`, `vivek5-gc.timer`.
7. Assert `systemctl list-timers --all` shows every expected timer with a non-empty NEXT; otherwise
   run rollback.sh automatically and exit 1.
8. Print the post-cutover checklist: delete `GH_ADMIN_TOKEN` on GitHub now; watch the first hourly
   crypto row in `python -m scanner.vps ledger`; Phase 2 = install Caddyfile.phase2 + DNS.
`rollback.sh`: stop/disable timers, path, api; re-enable the 15 workflows; set `VPS_ACTIVE=0`;
print that `GH_DISPATCH_TOKEN` must be restored in Cloudflare by the owner (its value is his).

## 8. Tests (all run in CI; every new `test/*.test.js` has a step in test.yml)
* `tests/test_vps_jobs.py`: JOBS table covers exactly the 14 VPS workflows; every step's module
  imports / script exists; every dropped Actions-only step is recorded with a reason; gates (windows,
  DST, weekend, close-slot no-upper-bound, backstop post-close rule, crypto/backup/alert backstops,
  manual bypass, probe fail-open); `.scan-skipped` deleted at job start; operator-only args dropped by
  the drainer; spool mapping incl. unknown workflow, oversize, symlink, partial file left alone;
  ledger atomicity + multi-field semantics; lock ordering; HALT refusal for book writers.
* `tests/test_vps_publish.py` (temp repos): dirty tracked file outside the path list still publishes;
  whole-file re-apply (an upstream sibling file is kept); rebuild-combined runs in the clone; must-change
  ANY-OF and per-market and manual branches; push rejection retries then succeeds; a non-VPS data commit
  upstream HALTs and nothing is pushed; a failed attempt leaves the clone clean; redaction.
* `tests/test_vps_deploy.py`: every VPS workflow has a timer; every OnCalendar passes
  `systemd-analyze calendar`; the ASX/NASDAQ timers' next elapses equal the documented local minutes;
  `systemd-analyze verify` on all units (path-rewritten copy); `bash -n` on every script; no `set -x`;
  no root units; no `-` EnvironmentFile; api unit loads api.env only; api.env.example carries no
  BYBIT_/ALPACA_/GBS_SMTP_/TELEGRAM_/DISCORD_/GIT_ names; jobs.env.example names every env var read by
  units/scripts/runner; both Caddyfiles pass `caddy validate`; phase2 carries the `_headers` rules and
  basic_auth on scan/close; no `DISCORD_WEBHOOK_URL` literal anywhere in deploy/.
* `test/vps_api.test.js`: adapter routes each Function; XFF trust rules; KV TTL; ASSETS traversal
  refused; `/api/dispatch` 503/401/400/422/429/202 matrix incl. `extra` over the wire -> 400, close of a
  non-open symbol -> 422, price off the mark band -> 422, spool file shape + atomic temp; Phase 1 route
  restriction; `_dispatch.js` picks DISPATCH_URL when set, refuses http non-loopback, GitHub path
  unchanged otherwise; the four endpoints accept DISPATCH_URL without GH_DISPATCH_TOKEN.
* `tests/test_watchdog.py` additions: ledger-mode parity fixture (same rows -> same findings as GitHub
  mode where they overlap), failed-run finding, skip counts as concluded success, disk_low.
* Existing suites stay green; workflow YAML pins stay green after the `VPS_ACTIVE` guards.

## 9. Explicitly NOT done here (follow-ups the owner may ask for)
Stopping data commits to git (needs a data-root refactor); moving `backups/`
and `data/history` out of git (2.4 GB repo, ~0.7 GB/month); status.js
reading the VPS ledger instead of linking to GitHub Actions; a Cloudflare
Tunnel instead of an open 443; EODHD as the Yahoo escape hatch (already wired
in `_prices.js`).
