# Vivek 5.0 on a VPS — design v3 (2026-09-27)

Owner ask: "I believe I'm ready to push the googy scanner to my VPS server."
The repo had no VPS path: every scheduled job is a GitHub Actions workflow,
the site is Cloudflare Pages, the API is Pages Functions (Workers runtime +
KV), and git is the data store. This is the contract for the kit under
`deploy/`, the `scanner/vps` job runner, and the small in-tree changes that
make the same code run on one Linux box.

v1 was reviewed by three adversarial passes (book safety, operations,
security) that REPRODUCED the failures rather than inferring them. v2 folds
every blocker and major in. v3 (2026-09-27) folds in the four reviews of the
SHIPPED kit (parity, book, security -- two blockers found only by running it
as two real users) and the owner's COEXISTENCE requirement: the target box
also runs his two trading bots ("ICT LIVE" trades real money, "ICT DEMO"), so
the kit changes no machine-wide state they depend on (section 10). The
machine-readable transcriptions of the workflows the builders work from live
beside the session, not in git.

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
| D9 | **Pinned, checksum-verified release tarballs** of Node 22 LTS (nodejs.org, SHASUMS256.txt) and Caddy >= 2.8 (GitHub release, its checksums file) under `/opt/vivek5/{node,caddy}` -- never apt, never NodeSource/cloudsmith, never the system `node` or `caddy.service` | apt has Node 18 (cannot load these ESM files without a package.json) and Caddy 2.6.2 (no `basic_auth`); and a vendor apt repo would REPLACE the system node / caddy the owner's bots may use (section 10) |
| D11 | **Coexistence**: the box also runs the owner's live trading bot; the kit changes no machine-wide state (section 10) | a scanner outage is recoverable, a disturbed live bot is not |
| D10 | No trade-logic change. Nothing under `scanner/broker/` is edited. New constants go in `scanner/config.py` (`VPS_*`) | CLAUDE.md |

## 1. Layout on the box (Ubuntu 24.04; the box's own timezone is left alone, every vivek5 unit runs TZ=UTC)

```
/opt/vivek5/app        the WORKING checkout (full clone of main): jobs run here, files are written here.
                       Its HEAD tracks origin/main; it NEVER commits. Tracked data files are dirty by design.
                       It stays a FULL clone (nothing fetches with --depth; preflight checks it).
/opt/vivek5/publish    the PUBLISH clone (--filter=blob:none, ssh remote): the ONLY place git commits/pushes happen.
/opt/vivek5/venv       python3.12 venv (requirements.txt), pre-compiled, owned by vivek5
/opt/vivek5/node       pinned Node 22 LTS (root-owned); used ONLY by vivek5-api.service
/opt/vivek5/caddy      pinned Caddy >= 2.8 binary (root) + data/ config/ (vivek5-caddy); ONLY vivek5-caddy.service
/opt/vivek5/state/     2750 vivek5:vivek5-spool: spool/ + spool/.tmp (3770: setgid + sticky), spool/done spool/failed
                       (2750), locks/ summaries/ home/ cache/ tmp/, kv.json (0660 vivek5-api), runs.json (0640),
                       publish_head, HALT (present only when halted)
/etc/vivek5/jobs.env   secrets + settings for the JOB units       0640 root:vivek5
/etc/vivek5/api.env    the API adapter's env ONLY                 0640 root:vivek5-api
/etc/vivek5/caddy.env  VIVEK_DOMAIN (+ Phase 2 basic auth)        0640 root:vivek5-caddy
/etc/vivek5/Caddyfile  from deploy/caddy/Caddyfile.phase1 or .phase2 (0644)
/etc/vivek5/deploy_key ed25519 deploy key (write, this repo)      0640 root:vivek5
/etc/vivek5/known_hosts github.com host keys, pre-seeded
/usr/local/lib/vivek5  ROOT-OWNED copy of preflight/cutover/rollback/ports.sh + the units + Caddyfiles:
                       the operator runs root scripts from HERE (or from a root-owned source clone,
                       e.g. /usr/local/src/vivek5), never from /opt/vivek5/app, which every job can write
/etc/systemd/system/vivek5-*.{service,timer,path}   COPIED by install.sh (never symlinked), never enabled by it
NO sudoers grant       update.sh (NoNewPrivileges=yes: a setuid sudo cannot work there) writes state/api-restart;
                       the ROOT vivek5-api-restart.path/.service runs `systemctl try-restart vivek5-api.service`.
                       install.sh removes an /etc/sudoers.d/vivek5 an earlier kit wrote (only one carrying its header)
```
Users: `vivek5` (jobs, owns app/publish/venv/state), `vivek5-api` (the Node
adapter) and `vivek5-caddy` (the TLS front door). BOTH `vivek5` and
`vivek5-api` are members of group `vivek5-spool`: the adapter creates spool
files (explicitly chmod 0660, `UMask=0007`) and the runner, a different user,
reads and moves them -- the 2026-09-27 security review showed every dispatch
silently lost when only one side was in the group. Every file the runner
writes through `atomic_write` is 0644 (runs.json 0640), never mkstemp's 0600:
the adapter reads the book to sanity-check a close and `/api/vps` reads the
ledger. No global `systemd-journal` membership (only `vivek5-failed@` has it).
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
| C2 host kit | `deploy/systemd/*` (incl. `vivek5-caddy.service`), `deploy/bin/{install,update,preflight,cutover,rollback,job,gc,ports}.sh`, `deploy/caddy/Caddyfile.phase1`, `deploy/caddy/Caddyfile.phase2`, `deploy/env/jobs.env.example`, `deploy/env/api.env.example`; `tests/test_vps_deploy.py` (no journald drop-in: removed for coexistence, section 10) | build-host |
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
gate <job> [key=value ...]     exit 0 due / 3 not due (prints why); no locks, no side effects -- EXCEPT
                               momentum.yml, whose gate runs `git fetch origin main` in the working
                               checkout (momentum_due reads main's stamps by design; never --depth,
                               under the repo lock, skipped with a warning when offline)
drain-spool                    execute queued dispatches (oldest first); exit 1 when one could not run
notify-failure <unit>          OnFailure= hook: alert_router + state/alerts.log + ledger
ledger [--json]                print runs.json
ledger-note <key> <status> <exit> [line ...]
                               one section-3.6 row for a host script (update.sh, gc.sh): the same
                               ledger.record, the same lock -- the scripts carry no ledger mirror
list                           print the JOBS table
accept-upstream                clear HALT: sync data roots FROM origin/main into the working checkout (operator action)
clear-halt                     clear HALT without syncing (operator has fixed it by hand)
```
`run` exit codes: 0 ok · 3 skipped-by-gate (ledger `skipped`) · 4 halted
(ledger `halted`) · 5 gave up WAITING for a lock (ledger `failed`; the spool
drainer re-queues it) · 1 failure. `key=value` args are OPERATOR-ONLY where
marked in the JOBS table (`extra`, `args`, `force`, `dry_run`, ...): a run
whose source is not the CLI (the spool, the momentum chain) carries NONE of
them -- not the caller's value and not the default. Job names are the GitHub
workflow file names.

Runner order inside `run`: (1) refuse if `state/HALT` exists and the job is a
book writer (exit 4); (2) evaluate the gate AT FIRE TIME; (3) acquire locks:
the job's family lock, then its own lock, then `repo` SHARED LAST -- a job
QUEUED on its family never pins `repo` (it used to, and update.sh saw the repo
busy all session) -- lock WAIT (`lock_wait_s`, default 7200 for scan-lock
jobs, 600 otherwise) is separate from the step timeout; (4) re-check "still
worth running" for slots that define it, at the SAME fire-time instant with
fresh data; (5) delete `.scan-skipped` for scan-family jobs; (6)
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
checkout: every RUNNING job holds it SHARED (taken last, after its family and
own locks); `update.sh` takes it EXCLUSIVE (non-blocking, skip + count);
`gc.sh` takes it SHARED (60 s wait, then skip) -- a repack under an exclusive
lock made the kill switch's 10-min lock budget run out every Sunday -- and
the `publish` lock for the publish clone only, its gc bounded at 420 s so a
queued publish (600 s budget) never times out; `accept-upstream` /
`clear-halt` take it EXCLUSIVE (blocking, printed,
config.VPS_OPERATOR_LOCK_WAIT_S) and then `publish`. `publish` = the publish
clone, exclusive, held only during the publish step (and by those two verbs
and gc's bounded publish-clone pass). kill_switch, backup_book, reco_note,
evidence_brief: own-name lock only. The order stays deadlock-free: the
repo-EXCLUSIVE holders hold no family/own lock, `publish` is only taken while
holding `repo`, and every wait on it is bounded.

### 3.3 Gates (`scanner/vps/gate.py`) — import config, never re-type numbers
* `scan_gate(market, slot)`:
  - `hourly`: weekday in the market's zone AND minute-of-day inside
    `config.MARKET_SCAN_WINDOWS[market]` (inclusive both ends) at FIRE time.
    No re-check after the lock.
  - `close`: weekday AND 16:00 <= local time <= the window's end (16:45):
    DUE, unconditionally -- scan.yml's closing cron runs whatever landed
    before it. (v2 applied the post-close rule here too; the 16:07 hourly
    ASX scan stamps `generated_at` AFTER its download, often 16:1x-16:2x, so
    that rule silently dropped the owner-mandated 16:30 scan most days --
    2026-09-27 parity review.) Past the window's end (a reboot-late
    `Persistent=` fire) it falls through to the backstop rule.
  - `backstop` (and a late `close`): weekday, local time >= 16:00, AND no
    post-close scan for today yet — "post-close" = `public/data/<market>_prices.json`
    `generated_at` at/after today's `config.MORNING_PLAYS_SLOT_GATE` time for
    that market (`scripts.morning_plays.scan_is_post_close`; the times are
    typed once). Re-checked after acquiring the lock AT THE FIRE-TIME
    INSTANT with fresh data: if a post-close scan landed while waiting, skip;
    a 16:30 close whose wait ran past 16:45 is still inside its window. No
    upper bound: a reboot-late close scan is still the post-close scan the
    digest needs.
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
  empty -> skipped. The stamps are read from origin/main (by design) after a
  plain `git fetch --quiet origin main` in the working checkout -- NEVER
  `--depth` (the workflow's `--depth=1` ran in a shallow runner checkout; on
  the box it converted the full clone to a shallow one every fire and hid
  foreign data commits from update.sh), bounded by
  `VPS_MOMENTUM_FETCH_TIMEOUT_S`, under `repo` SHARED
  (`VPS_MOMENTUM_FETCH_LOCK_WAIT_S`); offline / busy / timed out -> a warning
  and the last fetched ref.
* morning_plays: no runner gate; the script's own `--slot` + per-day marker
  + post-close gate decide (transcribe the cron->slot mapping: asx / us).
* Everything else: no gate.

### 3.4 Publish (`scanner/vps/publish.py`) — the whole-file re-apply loop
Runs under `publish` (exclusive) while still holding `repo` (shared).
```
P = job.publish.paths (files and directory pathspecs), M = job.publish.must_change
1. cd /opt/vivek5/publish; remove stale git lock files (index.lock, HEAD.lock, ref locks: a
   SIGKILLed git's debris -- safe under the exclusive publish flock); git fetch origin main;
   git reset --hard origin/main; git clean -fdq
2. SECOND-WRITER CHECK (fail-closed; NO state/publish_head at all is also fail-closed -- halted,
   nothing pushed -- unless VIVEK_BOOTSTRAP=1): for every commit in <state/publish_head>..origin/main
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
`update.sh` (§3.7). HALT scope, stated plainly: ANY non-VPS commit touching a
data root halts, including a Claude session hand-writing
`public/data/reco_note.json` -- after such a note the operator runs
`accept-upstream` (it syncs the note in and clears HALT). Narrowing that rule
(accept upstream when the VPS copy is unchanged since publish_head) is the
owner's call. `accept-upstream` and `clear-halt` hold `repo` EXCLUSIVE and
`publish` for their whole run (they wait for running jobs, printed) and list
what they overwrote per data root; both re-queue parked spool dispatches. Journal/stderr from git is REDACTED before it reaches the
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
The adapter writes every spool file 0660 (explicit chmod, `UMask=0007`) in
`spool/` 3770 vivek5:vivek5-spool (setgid + STICKY: the adapter can rename
only its own entries, never the runner's `done/`/`failed/`); the runner is in
the group and reads it.

`drain-spool`: only names matching the regex; opened `O_NOFOLLOW` + `fstat`
(a symlink or non-regular file is renamed `.stuck`, never followed); size cap
16 KiB; parse errors record the exception TYPE only; then by the job's exit:
0/3 -> `done/`, 1 -> `failed/`, 4 -> renamed in place `<name>.halted`
(re-queued by `accept-upstream`/`clear-halt`: a close accepted with 202 is
executed once the box is writable, not lost), 5 -> `<name>.retry` (re-queued
at the start of the next drain). Moves go only into REAL directories owned by
the runner; a failed move renames `.stuck`. After the walk, any leftover
`*.json` the drain did not consume (a symlink, a directory, a hand-dropped
`test.json`) is renamed `.stuck`, so the `.path` glob goes false and the
drainer cannot loop. A dispatch that could not even be attempted (refused,
unreadable, oversize, stuck) makes `drain-spool` exit 1 with a `spool` ledger
row, so the OnFailure hook alerts -- the adapter already said 202. A spooled
job that RAN and failed alerts from the runner with its args (for a close:
every symbol/market/price, enough to re-issue it by hand). Spool-driven jobs
take the scan lock with the long blocking wait. The `.path` unit uses
`PathExistsGlob=/opt/vivek5/state/spool/*.json` (`DirectoryNotEmpty=` would be
permanently true: done/ and failed/ live inside spool/; `.halted`/`.retry`/
`.stuck` never match) and its service has `StartLimitIntervalSec=0`.

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
`update: skipped busy`. A busy lock while a vivek5-* JOB unit is running is
expected (that job's `TimeoutStartSec` is its own hang detector) and does not
count; only an UNEXPLAINED busy lock (held, yet no vivek5 job unit running)
bumps a counter, alerting after 12 consecutive = 1 h. Otherwise, in the
working checkout: remove stale git lock files (safe under the exclusive
lock); `git fetch origin main`; if HEAD == origin/main say so and exit 0. Else: compute `git diff --name-status HEAD origin/main`.
If any changed path is a DATA ROOT and was authored by a non-VPS identity
since `state/publish_head` -> HALT exactly as §3.4 step 2 (do not sync).
Otherwise `git reset -q --mixed origin/main` (HEAD + index move, worktree
untouched), then for each changed NON-data path: `git checkout -q origin/main
-- <path>` (or remove it if deleted upstream). Data paths are never checked
out (the working files are the newer-or-equal truth on a single-writer box).
Then: `requirements.txt` hash changed -> `pip install -r requirements.txt`;
`functions/**` or `deploy/api/**` changed -> write `state/api-restart` (the
ROOT-owned `vivek5-api-restart.path` fires on the write and its oneshot runs
`systemctl try-restart vivek5-api.service`: restarted if running, never
started; no sudo -- the update unit runs `NoNewPrivileges=yes`, which forbids
setuid, and no sudoers grant exists); `deploy/systemd/**`, `deploy/caddy/**`,
`deploy/bin/**` changed -> notify(WARNING "re-run install.sh --units" from the
ROOT-OWNED source clone) — update.sh never touches /etc and never runs a root
script. RESUMABLE: the pre-sync HEAD is written to `state/update_pending`
before the `reset --mixed` and removed only once every follow-up above
succeeded, so a run killed or failed half-way (pip unreachable, the unit's
timeout) is finished by the next run instead of reading "up to date" with the
code, the venv or the API left stale. A busy repo lock counts as EXPLAINED
while any vivek5 job unit or `vivek5-gc.service` runs.
Ledger row `update` every run, via `python -m scanner.vps ledger-note`.

### 3.8 Environment
`jobs.env` (units: every vivek5-* job, update, gc): `VIVEK_HOME=/opt/vivek5/app`,
`VIVEK_PUBLISH=/opt/vivek5/publish`, `VIVEK_STATE_DIR=/opt/vivek5/state`,
`VIVEK_VENV=/opt/vivek5/venv`, `VIVEK_GIT_PUBLISH=1`,
`VIVEK_RUNS_LEDGER=/opt/vivek5/state/runs.json`, `GIT_AUTHOR_NAME=vivek5-vps`,
`GIT_AUTHOR_EMAIL=<an email already in scripts/commit_sentinel.py ALLOWED_EMAILS,
default the owner's GitHub noreply>` (+ COMMITTER twins),
`GIT_SSH_COMMAND=ssh -i /etc/vivek5/deploy_key -o IdentitiesOnly=yes -o
UserKnownHostsFile=/etc/vivek5/known_hosts -o StrictHostKeyChecking=yes -o BatchMode=yes
-o ConnectTimeout=30 -o ServerAliveInterval=15 -o ServerAliveCountMax=4` (a stalled
fetch/push fails in ~1 min instead of hanging with the book + publish locks held;
known_hosts is scanned by install.sh and REFUSED unless every key matches GitHub's
published fingerprints, pinned in install.sh and preflight.sh),
`HOME=/opt/vivek5/state/home`, `XDG_CACHE_HOME=/opt/vivek5/state/cache`,
`WATCHDOG_HOST=vps`, `VIVEK_BACKUP_TARGET=` (optional rsync/scp target for
off-box backups; if set the backup job fails when the copy fails), and every
secret the workflows pass through: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
`GBS_SMTP_HOST/PORT/USER/PASS`, `GBS_ALERT_TO/FROM`,
`DISCORD_MORNING_WEBHOOK_URL`, `BYBIT_API_KEY/SECRET`, `BYBIT_TESTNET`,
`ALPACA_API_KEY/SECRET_KEY`. Template values are `CHANGE_ME`; preflight
refuses any that remain. No leading `-` on any `EnvironmentFile=`. NO script
ever sources an env file with bash (`. jobs.env` expands `$` and runs
backticks -- a bcrypt hash or a password with `$` became a different value,
under `set -u` a crash): scripts read single keys with sed, preflight runs
job-environment checks through `systemd-run -p EnvironmentFile=`, Caddy is
validated with `--envfile`. install.sh writes the identity HOST-SCOPED
(`GIT_AUTHOR_NAME=vivek5-vps@<hostname>`) so a second box installed from the
same template is a foreign writer, not a silent twin.
`api.env` (vivek5-api only): `PORT=8787`, `VIVEK_PUBLIC_DIR=/opt/vivek5/app/public`,
`VIVEK_STATE_DIR`, `VIVEK_BOOK=/opt/vivek5/app/journal/vivek_bot_book.json`,
`DISPATCH_URL=http://127.0.0.1:8787/api/dispatch`, `DISPATCH_TOKEN` (>= 32
random bytes, generated by install.sh), `MORNING_PLAYS_TRIGGER_SECRET`,
`TRUST_PROXY=1`, `VIVEK_PHASE=1|2`, `EODHD_API_TOKEN` (optional). NO broker,
SMTP, Telegram, Discord or git credential ever appears here (test-pinned).
`caddy.env` (vivek5-caddy only): `VIVEK_DOMAIN`, Phase 2 `VIVEK_API_BASIC_USER`
/ `VIVEK_API_BASIC_HASH` (raw; systemd does not expand it).
Cutover only: `GH_ADMIN_TOKEN` (and optionally a Cloudflare Pages:Edit token)
PROMPTED with `read -rs` -- never typed on a command line (shell history),
never `sudo -E`, never from a file; it reaches curl through a 0600 `-K` config
file and request bodies through 0600 files, never argv (`/proc/*/cmdline` is
world-readable); scripts `trap unset` it; `set -x` is banned in deploy/bin
(test-pinned).

## 4. Schedule (systemd) — every line verified with `systemd-analyze calendar`

Every timer: `Persistent=true`, `AccuracySec=1s`; market/close/backstop timers
`RandomizedDelaySec=0`; heavy jobs may take `RandomizedDelaySec=10min`.
Every service: `Environment=TZ=UTC` (the box's zone is never changed).
Every oneshot job service: `TimeoutStartSec=` = the workflow's timeout-minutes +
the family's lock wait + `config.VPS_UNIT_TIMEOUT_MARGIN_MIN` (15): the runner's
own budget covers the wait and the steps and is the hang detector; the margin
covers the fire-time gate and the publish step, so systemd's kill is only ever
the outer backstop (a SIGKILL mid-push skips the runner's ledger row).
`KillMode=mixed` (SIGTERM to the runner, then SIGKILL to every leftover in the
cgroup: flocks are released with the processes -- the runner's lock fds are
close-on-exec, so no step child can keep one alive), `OnFailure=vivek5-failed@%n.service`,
`User=vivek5`, `ProtectSystem=strict`, `ReadWritePaths=/opt/vivek5/app
/opt/vivek5/publish /opt/vivek5/state`, `ProtectHome=yes`, `PrivateTmp=yes`,
`NoNewPrivileges=yes`, `ProtectProc=invisible`, `LogRateLimitIntervalSec=0`.
Heavy jobs (scan, crypto-bot, phasemap, the backtests, alert-returns,
momentum, and the spool drainer that runs dispatched scans) YIELD to the live
trading bot: `Nice=10`, `CPUWeight=20`, `IOSchedulingClass=best-effort`
(backtests `idle`), `IOSchedulingPriority=7`, soft `MemoryHigh=1G` (throttled,
never killed); NO `MemoryMax` on any job unit; the api keeps `MemoryMax=512M`.

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
| phasemap | `*-*-* 08:30 UTC` | `run phasemap.yml reason=cron` |
| confluence | `*-*-* 08:45 UTC` | `run confluence.yml reason=cron` |
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
| gc | `Sun *-*-* 03:00 UTC` | `deploy/bin/gc.sh` (`git gc --prune=2.weeks.ago`, both clones; repo lock SHARED -- never stalls a job, still excludes update.sh / the operator verbs; the publish clone also under the `publish` lock, bounded at 420 s so a queued publish never times out; Nice/CPUWeight/idle I/O/MemoryHigh=1G) |
| spool.path | `PathExistsGlob=/opt/vivek5/state/spool/*.json` | `drain-spool` |
| api-restart.path | `PathChanged=/opt/vivek5/state/api-restart` | `vivek5-api-restart.service`: ROOT (the only root unit), `systemctl try-restart vivek5-api.service`, nothing read from the flag |
| api.service | long-running, `WantedBy=multi-user.target` (enabled by cutover: survives a reboot) | `/opt/vivek5/node/bin/node deploy/api/server.mjs` as vivek5-api, `Restart=on-failure`, `RestartSec=5`, `StartLimitIntervalSec=0`, `MemoryMax=512M`, `UMask=0007`, `ReadWritePaths=` spool + kv.json only, `ProtectProc=invisible` + `ProcSubset=pid` and the kernel/namespace protections, `EnvironmentFile=/etc/vivek5/api.env` only |
| caddy.service | long-running, `WantedBy=multi-user.target` | `/opt/vivek5/caddy/caddy run --config /etc/vivek5/Caddyfile` as vivek5-caddy, `AmbientCapabilities=CAP_NET_BIND_SERVICE` (the only capability), XDG dirs under /opt/vivek5/caddy, `EnvironmentFile=/etc/vivek5/caddy.env`; no `--environ` (it would log the hash) |
| failed@.service | template | `notify-failure %i` (journalctl -u %i -n 30 attached; `SupplementaryGroups=systemd-journal` on this unit only) |

NASDAQ's second scan: GitHub delivered 11:37 New York under EDT (`37 14,15`)
and 11:07 under EST; the VPS fires 11:07 in both regimes (the documented
seven scans), recorded in workflows.json's scan.yml dropped list.

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
`/api/dispatch` (`dispatch.mjs`): POST only; the bearer is checked from the
HEADERS before a single body byte is read (then body <= 16 KiB; any other
route <= 64 KiB, and Caddy caps bodies at the edge), compared with
`crypto.timingSafeEqual`; no / `CHANGE_ME` / shorter-than-32-char
`DISPATCH_TOKEN` -> 503, wrong -> 401; typed per-workflow validation exactly
as §3.5 (unknown workflow or key -> 400, never spooled); close sanity:
symbol/market must be OPEN in `VIVEK_BOOK` and price within `config`'s
`VIVEK_MARK_SANITY_PCT[market]` of the row's `last_mark` -> else 422 naming
the mark (operator override is the CLI on the box); per-workflow cooldown
mirroring each Function's own TTL (`VPS_DISPATCH_COOLDOWN_S`: scan 300 s,
close 60 s, morning_plays 300 s) + daily caps (scan 40, close 60,
morning_plays 12) in the kv shim; spool depth > 20 -> 429; success -> 202
`{ok:true, id}`. `/api/vps` GET: `{ok, halted, jobs:{...}}` from runs.json,
503 when HALT exists, when a CRITICAL job's last run FAILED OR HALTED, or when
the ledger exists but cannot be read/parsed (only ENOENT means "no jobs yet").
`functions/api/_dispatch.js`: when `env.DISPATCH_URL` is set, POST
`{workflow, inputs}` there with `Authorization: Bearer <DISPATCH_TOKEN>`;
refuse a URL that is not `https:` and not loopback (`{ok:false,status:0}`);
map 202 -> `{ok:true}`, other statuses -> `{ok:false,status}` with the same
refund rule; `redirect: "manual"` (a 3xx is a refunded failure -- the bearer
never follows a redirect; ops.py's vps-dispatch refuses redirects too); never
echo the body. scan.js/close.js/heartbeat.js/
morning_plays.js: "configured" = `env.DISPATCH_URL || env.GH_DISPATCH_TOKEN`
(GitHub path and its tests unchanged when DISPATCH_URL is unset).
`functions/package.json` = `{"type":"module"}` (un-ignored; inert on Pages).

## 6. Caddy
OUR Caddy (`/opt/vivek5/caddy/caddy`, pinned, checksum-verified) run by
`vivek5-caddy.service` with `/etc/vivek5/Caddyfile` + `/etc/vivek5/caddy.env`
-- the distro/cloudsmith caddy and `caddy.service` are never installed,
started, reloaded or reconfigured. If :80/:443 are already held by another
process on the box, `ports.sh --check` makes preflight FAIL and cutover
refuse; the kit never takes a port from anything. The options it prints: run
the scanner on its own server, or front it with a **Cloudflare Tunnel**
(`cloudflared` dials out; no inbound port at all -- a follow-up the owner can
ask for, section 9).
Both Caddyfiles set the global `admin unix//opt/vivek5/caddy/data/admin.sock`:
never the default localhost:2019, which a distro/other Caddy on the box may
already hold (ours would fail to start) and which any local process could use
to rewrite routes or read the basic-auth hash; `caddy reload` finds the
socket in the same config.
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
`caddy hash-password` run interactively, read from `/etc/vivek5/caddy.env`), `/api/health`,
`/api/heartbeat`, `/api/price`, `/api/quote` open, access log with the
`key` query parameter deleted; `request_body { max_size 64KB }` on every
proxied handle. No `:80`/IP-only branch: a hostname is required.

## 7. Cutover (`deploy/bin/cutover.sh`), in this order, abort on any failure
0. `preflight.sh` green (run from the root-owned /usr/local/lib/vivek5/bin; it refuses to run as
   root from a path a non-root user can write, and runs every venv/checkout python AS vivek5):
   Ubuntu 24.04; NTP synced (the zone is INFO); :80/:443 free or ours; vendored node >= 22, caddy >= 2.8,
   python 3.12 venv imports (pandas, numpy, yfinance, requests, pybit, yaml) at the pinned versions;
   >= 20 GB free; `systemd-analyze calendar` on every OnCalendar line and `systemd-analyze verify` on
   every installed unit; no `CHANGE_ME` in either env file, modes 0640; `git push --dry-run` from the
   publish clone succeeds via the deploy key; `VIVEK_DOMAIN` resolves to this box and
   `https://$VIVEK_DOMAIN/api/vps` answers; egress: Yahoo chart, Binance ping, api.github.com status
   codes printed; **an alert channel round-trips** (`python -m scanner.watchdog --test-alert` reports a
   delivered channel) — refused otherwise unless `VIVEK_ACCEPT_NO_ALERT_CHANNEL=1` is set in the shell,
   which the script prints as a standing risk; the ASX dry run's max RSS is printed for sizing.
1. start `vivek5-caddy.service` + `vivek5-api.service` (Phase 1 Caddyfile) — the FIRST units the kit
   ever starts (install.sh starts nothing) — external check of `/api/vps`.
2. Cloudflare Pages env: set `DISPATCH_URL=https://$VIVEK_DOMAIN/api/dispatch` + `DISPATCH_TOKEN`,
   then DELETE `GH_DISPATCH_TOKEN` (via ops.yml `cf-set-var` / `cf-delete-var`, or the dashboard).
   From here every SCAN/close/heal request spools to the VPS and nothing can dispatch to GitHub.
3. GitHub, with `GH_ADMIN_TOKEN` (fine-grained, this repo, Actions: read+write, Variables: write):
   disable the 15 workflows (13 scheduled + close_position.yml + dispatch_scan.yml), GET each until
   `state == disabled_manually`; set repository variable `VPS_ACTIVE=1`.
4. Drain: poll `actions/runs?status=queued|in_progress|pending|waiting|requested` for those 15 until
   none remain (timeout 30 min), then poll once more 60 s later.
5. Working checkout: `git fetch && git reset --hard origin/main` (pristine start from the last Actions
   commit); publish clone: `git fetch && git reset --hard origin/main`; `state/publish_head` = that sha.
6. `systemctl enable --now` every timer (`vivek5-update.timer`, `vivek5-gc.timer` included),
   `vivek5-spool.path` and `vivek5-api-restart.path`.
7. Assert, one `systemctl show` per unit, that every expected timer is active with a real
   `NextElapseUSecRealtime`, both path units are active, and vivek5-api/-caddy are ENABLED and active
   (so a reboot brings the front door back); otherwise run rollback.sh automatically -- handing it the
   same admin token through the environment, never argv -- and exit 1.
8. Print the post-cutover checklist: delete `GH_ADMIN_TOKEN` on GitHub now; watch the first hourly
   crypto row in `python -m scanner.vps ledger`; Phase 2 = install Caddyfile.phase2 + DNS.
`rollback.sh`: stop/disable the API FIRST (no new 202s), then the spool path, the api-restart path and every timer, wait
for running jobs, then Caddy; list any dispatch still in state/spool ("accepted but not executed -
re-issue via GitHub"); re-enable the 15 workflows; set `VPS_ACTIVE=0`; print that `GH_DISPATCH_TOKEN`
must be restored in Cloudflare by the owner (its value is his). Every unit it touches is vivek5-*.

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
* `tests/test_vps_deploy.py`: the section 10 coexistence pins C1-C12 (static, plus `ports.sh` against a
  fake `ss`/`ps`, the `v5ctl` guard executed against a fake `systemctl`, the root path check executed);
  the 2026-09-27 host-review pins: the api-restart hook is the only root unit (one fixed command),
  update.service carries NoNewPrivileges and alone writes the venv, no sudoers written, api/caddy/paths
  carry [Install], `systemd-analyze verify` on every INSTANCE the timers start, ProtectSystem=strict +
  write paths per unit, every weekday 2026-09-28..2027-04-30 walked through the DST changes, update.sh
  resumes an interrupted sync, gc never blocks a job, cutover step 7 and the drain filter executed
  against fakes, GitHub host keys checked against the published fingerprints, no `000000` probes, no
  command substitution in an unquoted heredoc, a SIGKILLed runner releases its flocks;
  tokens never on argv; no env file sourced; every VPS workflow has a timer; every OnCalendar passes
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

## 10. Coexistence with the owner's trading bots (M6, 2026-09-27)

The target box also runs "ICT LIVE" (real money) and "ICT DEMO". Nothing the
kit does may change machine-wide state they depend on. Each rule is pinned in
`tests/test_vps_deploy.py`.

| # | Rule | Where |
|---|------|-------|
| C1 | The box timezone is never changed (no timedatectl zone setting anywhere); every vivek5 unit has `Environment=TZ=UTC`; preflight FAILS only on unsynced NTP and prints the zone as INFO | units, preflight |
| C2 | Never install/replace the system node: pinned Node 22 LTS tarball from nodejs.org, verified against its SHASUMS256.txt (and a pinned hash), in /opt/vivek5/node; one version constant at the top of install.sh | install.sh, vivek5-api.service |
| C3 | Never the distro/cloudsmith caddy, never `caddy.service`: pinned Caddy release tarball verified against the release checksums, /opt/vivek5/caddy/caddy, own `vivek5-caddy.service` (own user, `CAP_NET_BIND_SERVICE`, XDG dirs under /opt/vivek5/caddy, /etc/vivek5/{Caddyfile,caddy.env}) | install.sh, vivek5-caddy.service |
| C4 | install.sh and preflight print every TCP listener (`ss -Htlnp`); :80/:443 held by anything but vivek5-caddy -> preflight FAIL with the options, cutover refuses; never stop/kill/reconfigure another process; our Caddy's admin API is a unix socket, never TCP :2019 | ports.sh, Caddyfiles |
| C5 | No ufw/iptables configuration; preflight prints `ufw status` as INFO | install.sh, preflight |
| C6 | No swap by default; `--with-swap` makes a 4G /swapfile + fstab + `vm.swappiness=10` only when no swap exists; preflight WARNs under 4 GB RAM with no swap | install.sh, preflight |
| C7 | install.sh enables/starts NOTHING; cutover starts units only after a green preflight; rollback stops + disables every vivek5 unit it started | install/cutover/rollback |
| C8 | Heavy job units yield: `Nice=10`, `CPUWeight=20`, lowest I/O priority (backtests idle), soft `MemoryHigh=1G`, no `MemoryMax`; gc likewise (idle I/O, bounded delta window); api keeps `MemoryMax=512M`; preflight WARNs under 2 vCPUs and `--measure` runs at the heavy units' priority | units, preflight |
| C9 | preflight WARNs when outbound 587 and 465 are both blocked and recommends Telegram | preflight |
| C10 | Every systemctl that changes a unit goes through `v5ctl`, which refuses any target not named `vivek5-*`; no kill/pkill/killall anywhere in deploy/bin | all scripts |
| C11 | No journald drop-in (SystemMaxUse is global and would shorten the bots' log history); per-unit `LogRateLimitIntervalSec=0` stays; preflight prints `journalctl --disk-usage` | install.sh, preflight |
| C12 | install.sh prints every system-wide change first and requires a typed `yes` unless `--yes` | install.sh |

## 11. Shipped deviations (as built, 2026-09-27)

Sections 0-10 were rewritten to v3 after the reviews of the shipped kit, so
they already describe the build. This section keeps the contract honest
without rewriting history: every place the SHIPPED code differs from what v1
or v2 of this file promised, and the few places where the code still differs
from the text above, each with its reason. Where the two disagree, the code
and its pin win, and this list says so. (It is numbered 11 because section 10
already holds the coexistence table.)

### 11.1 Interfaces

| # | Earlier contract | As built | Why |
|---|---|---|---|
| I1 | 3.2: the JOBS table as `Job(...)` Python literals with `gate=gate.scan_gate` | `scanner/vps/workflows.json` (schema 1, transcribed 2026-09-26); `jobs.py` only wraps it in dataclasses and validates input; gates are named by string: `scan`, `crypto`, `backup`, `ledger_today`, `momentum` | repo-wide fence tests grep every `scanner/**/*.py` for evidence-artefact names, so a Python transcription trips them on the first commit. `ledger_today` is alert_returns' backstop gate: it reads THIS ledger instead of the Actions API |
| I2 | 3.1: lock wait 7200 s for scan-lock jobs, 600 s otherwise | `config.VPS_LOCK_WAIT_S = {scan: 7200, heavy: 3600, default: 600}` | a heavy job queued behind a backtest needs more than 10 minutes; pinned by `test_lock_families_and_waits_match_the_design` |
| I3 | 3.1 verbs: run, gate, drain-spool, notify-failure, ledger, list, accept-upstream, clear-halt | plus `ledger-note [--started ISO] <key> <status> <exit> [line...]`, `data-roots`, and `--json` on `ledger` / `list` | update.sh and gc.sh write their rows through the runner's own `ledger.record` (their embedded Python mirrors were deleted, M3); update.sh asks the runner for its second-writer scope instead of re-typing it |
| I4 | v2 exit codes 0/1/3/4 | exit 5 = gave up WAITING for a lock; the drainer parks exit 4 as `<name>.halted` and exit 5 as `<name>.retry` (`.retry` re-queued at the next drain, both by accept-upstream / clear-halt) | a close accepted with 202 must never be lost behind a hung scan or a HALT (book review K2) |
| I5 | 3.5 input shapes | the RUNNER's close_position spec is wider than the wire: `symbol` also takes the batch display form `SYM+N`, `market` also `scalp` / empty; the ADAPTER's validator is exactly 3.5 | the runner is also the operator CLI (legacy journals) and receives the adapter's canonical batch record |
| I6 | "operator-only args dropped by the drainer" | omitted ENTIRELY, value and default, for every source other than the CLI; morning_plays maps `--slot` from the slot alone | a spooled plays run came out carrying `force='true'` (the default) (M4) |
| I7 | 5: `/api/vps` = `{ok, halted, jobs}`, 503 on HALT or a FAILED critical job | `{ok, halted, failed, jobs, checked_at}`; rows projected to status and timestamps only (no `last_line`, no args: the route is open); 503 also when a critical job HALTED (M1) or the ledger exists but cannot be read or parsed | a 0600 `runs.json` once made the route permanently green while the kill switch failed (S1) |
| I8 | v2: one 300 s dispatch cooldown | per workflow, `config.VPS_DISPATCH_COOLDOWN_S = {scan.yml: 300, close_position.yml: 60, morning_plays.yml: 300}`, a JSON literal in `dispatch.mjs` parity-tested against config AND each Function's own `expirationTtl`; the 429 text names the right duration | close.js's own TTL is 60 s: the box refused a second close-all that Pages had accepted (M2) |
| I9 | 5: bearer compared with timingSafeEqual | also: the bearer is checked from the HEADERS before any body byte is read; unset / `CHANGE_ME` / shorter than `VPS_DISPATCH_TOKEN_MIN_CHARS` (32) answers 503; 413 over the body cap; Caddy caps bodies at 64 KB | security review: a placeholder token was accepted and 1 MiB unauthenticated bodies were buffered |
| I10 | 5: `_dispatch.js` posts to `DISPATCH_URL` | `redirect: "manual"` (a 3xx is a refunded failure); `scripts/ops.py` vps-dispatch refuses redirects too | the bearer must never follow a redirect |

### 11.2 Gates and the runner

| # | Earlier contract | As built | Why |
|---|---|---|---|
| G1 | v2: the close slot used the post-close rule | inside 16:00..window end the close slot is DUE unconditionally; past the window it falls through to the backstop rule; the post-lock re-check evaluates at the SAME fire-time instant with fresh data | the 16:07 ASX scan stamps `generated_at` after its download (often 16:1x-16:2x), so v2 dropped the owner-mandated 16:30 scan most days (parity review) |
| G2 | the workflow's `git fetch --depth=1` in the momentum gate | a plain `git fetch --quiet origin main`, never `--depth`, under `repo` SHARED (`VPS_MOMENTUM_FETCH_LOCK_WAIT_S`), bounded by `VPS_MOMENTUM_FETCH_TIMEOUT_S`; offline / busy / timed out -> a warning and the last fetched ref. `gate` is side-effect free EXCEPT for momentum.yml, and the CLI help says so | `--depth=1` turned the full working clone shallow on every fire and hid foreign data commits from update.sh (K3). Dropping the fetch was rejected: momentum_due reads main's stamps by design (M5) |
| G3 | v1: `repo` SHARED taken first | family -> own -> `repo` SHARED LAST | a job QUEUED on its family pinned `repo`, so update.sh saw the lock busy all session (K4) |
| G4 | phasemap / confluence `reason` defaulted to the schedule branch | default `manual` for an operator run; their timers pass `reason=cron` | an operator single-market run was graded like a scheduled one |
| G5 | GitHub's NASDAQ second fire (11:37 New York under EDT) | 11:07 New York in both DST regimes; recorded in workflows.json's scan.yml `dropped` list | the documented seven NASDAQ scans, identical all year |
| G6 | GitHub's `:47` backstops | 17:15 local backstops re-firing the post-close rule | the `:47` backstops were dead code behind the window gate |

### 11.3 Publish, spool and data

| # | Earlier contract | As built | Why |
|---|---|---|---|
| P1 | v2: a missing `state/publish_head` skipped the second-writer check | fail-closed (`halted`, nothing pushed) unless `VIVEK_BOOTSTRAP=1`; cutover step 5 writes it | without it the check cannot run |
| P2 | none | stale git lock files are removed at the top of every publish attempt (under the exclusive `publish` flock), by accept-upstream / clear-halt, and by update.sh in the working checkout (under `repo` EXCLUSIVE); preflight lists any it sees | a SIGKILLed git's `index.lock` wedged every later publish (K1) |
| P3 | v2: accept-upstream / clear-halt took no locks | both hold `repo` EXCLUSIVE then `publish` for their whole run (blocking, printed, `VPS_OPERATOR_LOCK_WAIT_S`); accept-upstream prints per-root overwritten / removed counts | they could run under a live job and overwrite what it was writing (K5) |
| P4 | none (in-tree, outside scanner/vps) | `scanner/journal_common.atomic_write` fchmods to its `mode` (default 0o644) before `os.replace`; `scanner/output.write_json` passes `mode` through; the ledger writes 0640 | mkstemp's 0600 made the book and every published file unreadable to the adapter after the first write, so every bot close answered 503 (security blocker) |
| P5 | 3.5: spool 2770, adapter in the group | `spool/` and `spool/.tmp` 3770 (setgid + sticky), `done/` and `failed/` 2750, files chmod 0660 before rename, `vivek5-api.service` `UMask=0007`, BOTH users in `vivek5-spool`; the drainer opens `O_NOFOLLOW` + `fstat`, moves only into real runner-owned dirs, renames any leftover `*.json` to `.stuck`, and `drain-spool` exits 1 with a `spool` ledger row when a 202 could not even be attempted | every dispatch was silently discarded when only the adapter was in the group (security blocker B1); a leftover `*.json` looped the drainer (K6) |
| P6 | `DirectoryNotEmpty=` on the spool | `PathExistsGlob=/opt/vivek5/state/spool/*.json` + `StartLimitIntervalSec=0` | `done/` and `failed/` live inside `spool/`, so DirectoryNotEmpty would be permanently true |
| P7 | 5: kv.json file-backed, temp + rename | temp + rename where the directory allows it, otherwise an IN-PLACE rewrite (EACCES / EPERM / EROFS: the adapter may write only `spool/` and `kv.json` itself); a `[kv] ... falling back to in-place writes` line in the api journal is expected | ProtectSystem=strict + a 2750 `state/`; a torn file costs rate-limit state and access-log rows only, never the book, and the loader treats bad JSON as empty |

### 11.4 Host kit

| # | Earlier contract | As built | Why |
|---|---|---|---|
| H1 | v1: `TimeoutStartSec` = the workflow timeout | workflow timeout + family lock wait + `VPS_UNIT_TIMEOUT_MARGIN_MIN` (15); `GIT_SSH_COMMAND` adds BatchMode, ConnectTimeout=30, ServerAliveInterval=15 / CountMax=4 | a job queued on the book lock was killed while still waiting; the margin covers the fire-time gate and the publish step so systemd's kill is only the outer backstop; a stalled push now fails in about a minute instead of hanging with the locks held |
| H2 | v2: a sudoers grant let update.sh restart the API | NO sudo: update.sh writes `state/api-restart`; the ROOT `vivek5-api-restart.path` (`PathChanged=`) starts `vivek5-api-restart.service`, a oneshot running exactly `systemctl --no-ask-password try-restart vivek5-api.service` (the only root unit; try-restart never starts a stopped API, so C7 holds); install.sh removes an earlier `/etc/sudoers.d/vivek5` only if it carries the kit's header | update.service runs `NoNewPrivileges=yes`, which makes a setuid sudo impossible: the grant could never have worked (ops review) |
| H3 | none | `WantedBy=multi-user.target` on vivek5-api and vivek5-caddy; cutover step 7 asserts both enabled and active | after a reboot the timers ran while the dispatch door and TLS front door stayed dead |
| H4 | Caddy's default admin endpoint | `admin unix//opt/vivek5/caddy/data/admin.sock` in both Caddyfiles | TCP :2019 collides with any other Caddy on the box and lets any local process rewrite routes or read the basic-auth hash (C4) |
| H5 | `ssh-keyscan` (trust on first use) | every github.com host key checked against GitHub's published fingerprints, pinned identically in install.sh and preflight.sh | an unpublished key now refuses the install |
| H6 | v2 install order | deploy key + known_hosts BEFORE the clones (https clone, ssh fallback with the key); `cd /` before any `sudo -u vivek5`; idempotent users with an explicit primary group; a bare `--phase` refused before anything changes; `--units --with-swap` works; `--units` try-restarts only CHANGED long-running units (api, caddy, paths, timers), never a oneshot job | a private repo died at the clone with no key printed; git/pip started in root's 0700 cwd |
| H7 | 3.7 v2 | update.sh is RESUMABLE (`state/update_pending` written before `reset --mixed`, removed only after every follow-up succeeded); a busy lock counts as explained while any vivek5 job unit or `vivek5-gc.service` runs | a run killed after the reset read "up to date" next time with code, venv or API left stale (ops review) |
| H8 | v2: gc under `repo` EXCLUSIVE | `repo` SHARED (60 s wait), the publish clone under `publish` EXCLUSIVE (150 s wait) with a 420 s bound (150 + 420 < the 600 s every publish waits); CPUWeight / MemoryHigh like a heavy job | an exclusive repack timed out the kill switch's 10-minute lock budget every Sunday |
| H9 | v2: operator ran root scripts from the checkout | root scripts refuse to run from any path a non-root user can write (`refuse_unsafe_path` in install / preflight / cutover / rollback / ports); install copies a root-owned operator kit to `/usr/local/lib/vivek5` and runs from a root-owned clone (`/usr/local/src/vivek5`); preflight runs every venv/checkout python AS vivek5 with `env -i`, job-environment checks through `systemd-run -p EnvironmentFile=`; root never runs git in the vivek5 clones (no system-wide `safe.directory`) | root executed code the jobs user could write (S2) |
| H10 | v2: scripts sourced `jobs.env` | no script sources an env file: keys read one at a time with sed; Caddy validated with `--envfile`; the alert round-trip runs through `systemd-run` with the units' own parser | bash expanded the bcrypt `$2a$...` hash and crashed under `set -u` (S4) |
| H11 | v2: tokens from the environment, `sudo -E` | tokens PROMPTED (`read -rs`); curl reads them from 0600 `-K` config files and bodies from 0600 `--data-binary @file`, never argv; `cutover.sh --yes` is refused without the Pages API inputs; the automatic rollback receives the same token through the environment; the usage lines are plain `sudo` | `/proc/*/cmdline` is world-readable (S3); `--yes` used to auto-confirm a manual Cloudflare step |
| H12 | 7 v2 | the drain polls queued / in_progress / pending / waiting / requested, matches runs by `workflow_id` (a run `path` may carry `@ref`), confirms zero once more 60 s later; step 7 uses one `systemctl show` per unit instead of the JSON timer listing; rollback stops the API FIRST and lists accepted-but-unexecuted spool entries | a run created just before the disable could be missed; an unverified JSON schema could abort cutover half-way under `set -euo pipefail` |
| H13 | v2 installed system-wide software and settings | the coexistence mandates C1-C12 of section 10. Before them the kit changed the box's timezone, installed Node from NodeSource and Caddy from a vendor apt repo with the distro Caddy unit, shipped a journald drop-in (`deploy/journald.conf`, now deleted) and started units at install. Now: the box zone untouched and `TZ=UTC` per unit (C1); pinned Node 22.23.3 (SHA256) and Caddy 2.10.2 (SHA512) tarballs under `/opt/vivek5` (C2, C3) served by our own `vivek5-caddy.service`; `ports.sh` (C4); no firewall (C5); swap only with `--with-swap` (C6); nothing starts at install (C7); heavy units yield (C8); the SMTP probe (C9); `v5ctl` and no kill-family calls (C10); no journald drop-in (C11); a printed plan and a typed `yes` (C12) | the target box also runs the owner's real-money bot (M6) |
| H14 | a fixed `vivek5-vps` identity | install.sh writes `vivek5-vps@<hostname -s>` into a fresh jobs.env | a second box installed from the same template must read as a foreign writer, not a silent twin |

### 11.5 Found while writing the runbook (NOT changed in code; `deploy/README.md` routes around each)

* R1. RESOLVED 2026-09-27 in cutover.sh (see its step 2 and step 8). cutover step 8 prints `sudo -u vivek5 $venv/bin/python -m scanner.vps ledger`.
  Without `jobs.env` the runner reads `<checkout>/.vps-state` (config
  `VPS_STATE_DIR_DEFAULT`), and from root's cwd it cannot even import
  `scanner`. The runbook defines `v5` (systemd-run with the units'
  `EnvironmentFile=`) and uses it for every operator verb.
* R2. RESOLVED 2026-09-27 in cutover.sh (see its step 2 and step 8). cutover step 8 says a scan is now `systemctl start vivek5-scan@asx.service`.
  That is `slot=hourly`, which the gate correctly skips outside the market
  window. A manual scan is `run scan.yml market=asx` (slot `manual`) or ops.yml
  `vps-dispatch` (README 12.4).
* R3. RESOLVED 2026-09-27 in cutover.sh (see its step 2 and step 8). cutover step 2's manual path prints `ops.yml action=cf-set-var` for
  `DISPATCH_TOKEN`: the value then rides the run's `workflow_dispatch` inputs,
  which GitHub records, on a public repo. The runbook sets the token in the
  Cloudflare dashboard (or through cutover's own Pages API prompt, whose body
  is a 0600 file).
* R4. RESOLVED 2026-09-27 in cutover.sh (see its step 2 and step 8). cutover never triggers a Pages redeploy. Pages applies env var changes to
  NEW deployments only, so the running Functions keep the GitHub transport
  until the next deployment (the box's first data push, or `ops.yml
  action=cf-redeploy`). The runbook adds the redeploy.
* R5. RESOLVED 2026-09-27: `config.TELEGRAM_ENABLED` now reads `VIVEK_TELEGRAM_ENABLED` (default off), set to
  `1` in the box's jobs.env only, so the D8 alert precondition can be met with Telegram without changing
  GitHub Actions' behaviour.
* R6. The checkout's `.cache/` (the morning-plays 7-day sent list and slot
  markers, the watchdog's alert memory, the frame cache) starts EMPTY on the
  box: the Actions cache does not transfer. For the first week a digest may
  repeat a name sent in the last 7 days, and a current stale finding is
  announced once more.
* R7. Alert and notification texts name `python -m scanner.vps accept-upstream` /
  `clear-halt`; on the box both need `jobs.env` (the runbook's `v5` form).

### 11.6 Verified only against stand-ins, or deliberately left open

* No PID-1 systemd was available where the kit was built: an empty
  `NextElapseUSecRealtime` for a never-firing timer, `PathChanged=` firing on a
  write to the pre-created flag, and `try-restart` from a `ProtectSystem=strict`
  root oneshot follow systemd 255's code and are exercised against fakes.
  Cutover step 7 checks the first on the real box and rolls back by itself.
* Whether `PUT .../workflows/{id}/disable` is idempotent on an already-disabled
  workflow (a cutover re-run) was not verifiable (api.github.com answers 403 to
  the build sessions); the die messages point at rollback.sh.
* `vivek5-spool.service`'s 8 h `TimeoutStartSec` can in theory be shorter than
  two queued scans that each wait out their full lock budget; a drain killed
  mid-job leaves that spool file unmoved and it re-runs on the next trigger.
* `default_exec`'s step timeout kills the direct child only; a grandchild that
  keeps stdout open is ended by the unit's `TimeoutStartSec` instead.
* Owner decisions, recorded not taken: HALT scope for a hand-written reco
  note, skipping non-book jobs while HALTed, a `SystemCallFilter=` on the API
  unit (Node 22's libuv may use io_uring; unverifiable without the box).
