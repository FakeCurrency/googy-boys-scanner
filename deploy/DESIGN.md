# Vivek 5.0 on a VPS — design (v1, 2026-09-26)

Owner ask: "I believe I'm ready to push the googy scanner to my VPS server."
The repo has no VPS path today: every scheduled job is a GitHub Actions
workflow, the site is Cloudflare Pages, the API is Pages Functions (Workers
runtime + KV), and the data store is git itself. This document is the
contract for the deployment kit under `deploy/` and the small in-tree
changes that make the same code run on one Linux box.

## 0. Decisions (state them, do not re-derive)

| # | Decision | Why |
|---|----------|-----|
| D1 | **systemd timers + a Python venv**, not Docker, not a bespoke scheduler | tz-aware `OnCalendar=... Australia/Sydney`, `Persistent=true` catches a reboot, journald logs, `flock` mutex; the sandbox that built this has no docker daemon but does have systemd 255, so units and calendars are verifiable here |
| D2 | **Git publishing stays ON** — the VPS commits+pushes data to `main` exactly as Actions do | least-change: Cloudflare Pages keeps deploying as a mirror, GitHub history/backups keep working, Claude sessions keep reading committed data. Turning it off needs a data-root refactor; noted as a follow-up, not done here |
| D3 | **The Pages Functions run unchanged on the VPS under a thin Node adapter** (Workers-API shims) | `_prices.js` alone is ~450 lines of hard-won Yahoo/Binance logic with JS tests; a Python port would be a second copy that drifts. Node >= 18 has `fetch/Request/Response/URL/AbortController` |
| D4 | **`_dispatch.js` gains ONE alternate transport: `DISPATCH_URL` + `DISPATCH_TOKEN`** | on the VPS a "dispatch" must start a LOCAL job, not a GitHub workflow. Same code path for Phase 1 (Cloudflare Functions dispatching to the VPS) and Phase 2 (adapter looping back to itself) |
| D5 | **One writer.** Cutover DISABLES the scheduled GitHub workflows before the VPS timers start; the kit ships `cutover.sh` / `rollback.sh` / `preflight.sh` | the 30-position cap is global and the scan mutex only protects same-repo Actions runs; a VPS and Actions both writing the book is the one failure that cannot be undone |
| D6 | Two phases, same kit: **Phase 1 runner-only** (Cloudflare keeps serving; Functions dispatch to the VPS), **Phase 2 full self-host** (Caddy serves `public/` from the checkout; adapter serves `/api/*`) | the owner can stop after Phase 1 and lose nothing; Phase 2 is DNS + one more service |
| D7 | Caddy for TLS/static (`apt install caddy`), API bound to 127.0.0.1 | auto-HTTPS with a domain; the PWA's service worker needs a secure context |
| D8 | No trade-logic change. Nothing under `scanner/broker/` is edited. `scanner/config.py` gets a `VPS_*` block for new constants (config-first rule) | CLAUDE.md |

## 1. Layout on the box

```
/opt/vivek5/app        the git checkout (main), owned by user vivek5
/opt/vivek5/venv       python3.12 venv with requirements.txt
/opt/vivek5/state/     spool/  locks/  kv.json  runs.json   (never in git)
/etc/vivek5/vivek5.env secrets + settings, 0640 root:vivek5, loaded via EnvironmentFile=
/etc/caddy/Caddyfile   from deploy/Caddyfile (Phase 2)
```
Repo-relative state the code already uses (`.cache/`, `.scan-skipped`,
watchdog state) simply persists inside the checkout — it is gitignored.

## 2. Components and file ownership

| Comp | Files | Owner agent |
|------|-------|-------------|
| C1 job runner | `scanner/vps/__init__.py`, `jobs.py`, `gate.py`, `ledger.py`, `publish.py`, `spool.py`, `__main__.py`; `tests/test_vps_jobs.py`; `VPS_*` constants in `scanner/config.py` | build-jobs |
| C2 host kit | `deploy/systemd/*.service|*.timer|*.path`, `deploy/bin/{install,update,cutover,rollback,preflight,job}.sh`, `deploy/Caddyfile`, `deploy/env.example`; `tests/test_vps_deploy.py` | build-host |
| C3 API adapter | `deploy/api/server.mjs`, `deploy/api/shims.mjs`; `functions/api/_dispatch.js` (DISPATCH_URL transport); `test/vps_api.test.js` (+ a step in `.github/workflows/test.yml`); dispatch-related assertions in existing JS tests | build-api |
| C4 couplings | `scanner/watchdog.py` ledger mode; `scanner/scan.py` build stamp fallback; `tests/test_watchdog.py` additions | build-couplings |
| C5 docs | `deploy/README.md` (runbook), CLAUDE.md section, OPERATIONS.md pointer | docs |

## 3. Interfaces (the contract between components)

### 3.1 CLI — `python -m scanner.vps`
```
python -m scanner.vps run <job> [key=value ...]     # run one job end to end
python -m scanner.vps gate <job> [key=value ...]    # exit 0 = due, 3 = not due (prints why)
python -m scanner.vps drain-spool                   # execute queued dispatches
python -m scanner.vps ledger [--json]               # print runs.json
python -m scanner.vps list                          # print the JOBS table
```
`run` = acquire lock -> gate -> steps -> publish -> ledger. Exit 0 ok,
3 skipped-by-gate (still writes a ledger row with status "skipped"),
1 any failure. Every step's stdout/stderr goes to the journal unchanged.

### 3.2 JOBS table (`scanner/vps/jobs.py`)
One entry per scheduled/dispatchable workflow; keys are the GitHub workflow
file names so `WATCHDOG_RUNS` maps 1:1:
```
Job(
  name="scan.yml", args={"market": "asx"|"nasdaq"|"crypto"|"all", "reason": "cron|manual|heartbeat", "extra": ""},
  lock="scan",                  # shared by scan/crypto_bot/close_position/confluence
  gate=gate.market_window,      # None for un-gated jobs
  steps=[...],                  # list of argv lists, run sequentially, fail-fast unless step.continue_on_error
  publish=Publish(paths=[...], must_change=[...], message="data: scan {utc:%Y-%m-%d %H:%M} UTC"),
  timeout_s=...,
)
```
Steps, env, staging lists, must-change sets and commit messages are
TRANSCRIBED from the workflows by the understand phase; the runner must
not invent them.

### 3.3 Spool file (written by the API adapter, read by `drain-spool`)
`/opt/vivek5/state/spool/<utc-iso>-<8hex>.json`
```json
{"id":"...","received_at":"2026-09-26T21:44:00Z","workflow":"scan.yml",
 "inputs":{"market":"asx","reason":"manual"},"source":"api/scan"}
```
A systemd `.path` unit (`DirectoryNotEmpty=`) starts `vivek5-spool.service`,
which runs `drain-spool`: for each file (oldest first) map
`workflow+inputs` -> `run <job> key=value`, move the file to `spool/done/`
(or `spool/failed/`). Unknown workflow -> failed, logged.

### 3.4 Runs ledger `/opt/vivek5/state/runs.json`
```json
{"scan.yml": {"last_start":"...","last_end":"...","status":"ok|failed|skipped",
              "exit":0,"args":{"market":"asx"},"host":"vps"},
 "crypto_bot.yml": {...}}
```
Atomic write (temp + `os.replace`). `watchdog.probe_runs` reads it when
`VIVEK_RUNS_LEDGER` is set, with the same age/severity table and the same
"latest run FAILED -> stay silent" rule it applies to GitHub run history.

### 3.5 Publish (git), single-writer semantics
```
for p in paths: git add -- p            # one pathspec per call, missing path = log + continue
assert any(must_change staged)          # else exit 1 loudly (assert_staged parity)
git -c user.name=... commit -m message
for attempt in 1..5: git pull --rebase -X theirs origin main && git push origin HEAD:main && break; sleep 2**attempt
```
Never `git add -A/-u`, never `reset --hard`, never touch a path outside
the job's list. An incoming upstream commit that touches `journal/` and
was authored by `github-actions[bot]` is a SECOND WRITER: log
`[second_writer]` at WARNING and raise a `vps_second_writer` alert
through `alert_router` (channel-less today, but on the ledger and in the
journal). `VIVEK_GIT_PUBLISH=0` skips the whole step (data stays on disk;
only for a throwaway box).

### 3.6 Locks
`flock` on `/opt/vivek5/state/locks/<lock>.lock`, taken by `job.sh`
(host side) AND re-checked by the runner (defence in depth). `scan` is the
book mutex: scan.yml, crypto_bot.yml, close_position.yml, confluence.yml.
Every other job locks on its own name. `update.sh` takes `scan` too, so a
code pull never interleaves with a book write.

### 3.7 Environment (all read via `EnvironmentFile=/etc/vivek5/vivek5.env`)
Jobs: `VIVEK_HOME=/opt/vivek5/app`, `VIVEK_STATE_DIR=/opt/vivek5/state`,
`VIVEK_GIT_PUBLISH=1`, `VIVEK_RUNS_LEDGER=$VIVEK_STATE_DIR/runs.json`,
`GITHUB_SHA` (set by job.sh from `git rev-parse HEAD` for the build stamp),
`GIT_AUTHOR_NAME/EMAIL` for data commits, plus every secret the workflows
pass through (`TELEGRAM_*`, `GBS_SMTP_*`, `GBS_ALERT_*`,
`DISCORD_MORNING_WEBHOOK_URL`, `BYBIT_*`, `ALPACA_*`; `WATCHDOG_HOST`).
API adapter: `PORT=8787`, `VIVEK_PUBLIC_DIR=$VIVEK_HOME/public`,
`DISPATCH_URL=http://127.0.0.1:8787/api/dispatch`, `DISPATCH_TOKEN`,
`MORNING_PLAYS_TRIGGER_SECRET`, `TRUST_PROXY=1` (Caddy sets X-Forwarded-For).
Cutover scripts: `GH_ADMIN_TOKEN` (fine-grained, Actions: read+write) — used
once, never stored in the env file.

## 4. Schedule (systemd `OnCalendar`, tz suffix where the market decides)

| Unit | OnCalendar | Gate |
|------|-----------|------|
| scan@asx | `Mon..Fri 11:07,12:07,13:07,14:07,15:07,16:07,16:30 Australia/Sydney` | market window (config.MARKET_SCAN_WINDOWS) |
| scan-backstop@asx | `Mon..Fri 16:47 Australia/Sydney` | skip if that market's `generated_at` < 60 min old (the :47 rule) |
| scan@nasdaq | `Mon..Fri 10:37,11:07,12:07,13:07,14:07,15:07,16:07 America/New_York` | market window |
| scan-backstop@nasdaq | `Mon..Fri 16:47 America/New_York` | freshness |
| crypto_bot | `*-*-* *:22 UTC` and `*:52` backstop | :52 skips when fresh (transcribe crypto_bot.yml) |
| kill_switch | `*:15,45 UTC` | none |
| phasemap | `08:30 UTC` daily | none |
| confluence | `08:45 UTC` | unstaged-tree rule (transcribe) |
| reco_note | `08:52 UTC` | none |
| backup_book | `21:35 UTC` + `23:35` backstop | skip when today's `backups/<date>T…` exists |
| alert_returns | `22:20 UTC` + `23:50` backstop | backstop skips when the ledger shows a success today |
| evidence_brief | `21:00 UTC` | none, read-only |
| lens_backtest | `Sun 08:00 UTC` | none |
| vivek_backtest | `*-*-01 08:00 UTC` | none |
| morning_plays@asx | `Mon..Fri 06,07,08,09,10:15,45 UTC` | the script's own `--slot` + post-close gate |
| morning_plays@us | `Mon..Fri 20,21,22,23:15,45 UTC` | same |
| momentum | `*:41 UTC` hourly | `scripts/momentum_due.py` (data-driven) |
| update | every 5 min | repo lock; ff-only |
| spool.path | on spool dir non-empty | — |

`Persistent=true` on every timer; `RandomizedDelaySec=0` (the minute
matters for the closing scans). The in-job gate is kept even where the
calendar already encodes it — a timer fired late by a reboot must still
respect the market window.

## 5. Caddy (Phase 2)
`root * /opt/vivek5/app/public`, `file_server`, `encode zstd gzip`,
headers mirroring `public/_headers` (`/js/*` and `/css/*` 86400; everything
else `max-age=0, must-revalidate`; `X-Content-Type-Options: nosniff`),
`handle /api/*` -> `reverse_proxy 127.0.0.1:8787`. Optional commented
`basic_auth` block for `/api/scan` and `/api/close`. `{$VIVEK_DOMAIN}` from
the env; no domain -> `:80` with a loud comment that the service worker
will not register over plain HTTP on a public IP.

## 6. Cutover (the runbook's spine)
1. Provision Ubuntu 24.04, `curl -fsSL .../deploy/bin/install.sh | sudo bash`
   (or clone then run) — creates the user, venv, units, env template.
2. Fill `/etc/vivek5/vivek5.env`. `deploy/bin/preflight.sh` checks: git can
   push (deploy key / token), Yahoo reachable, python imports, node present,
   every timer's calendar parses, disk space.
3. Dry run: `python -m scanner.vps run scan.yml market=asx extra=--limit\ 12`
   with `VIVEK_GIT_PUBLISH=0` to prove the path.
4. `deploy/bin/cutover.sh` — disables the 13 scheduled workflows on GitHub
   via the API (needs `GH_ADMIN_TOKEN` for the one call), verifies each is
   `disabled_manually`, then `systemctl enable --now` every timer + the
   spool path unit + the api service. Prints what it did.
5. Phase 1 wiring on Cloudflare: set `DISPATCH_URL=https://<vps>/api/dispatch`
   and `DISPATCH_TOKEN` in the Pages project env; `GH_DISPATCH_TOKEN` may
   stay but is no longer used when `DISPATCH_URL` is set.
6. Phase 2: point DNS at the VPS, enable Caddy, done. Cloudflare Pages can
   stay as a mirror or be deleted.
7. `rollback.sh` reverses 4 (stops timers, re-enables workflows).

## 7. Tests
* `tests/test_vps_jobs.py` — JOBS table completeness vs the workflow set;
  every step argv exists (module importable / script present); gate math
  (market windows, DST, weekends, reboot-late fire); ledger atomicity;
  publish in a temp git repo (one pathspec per add, must-change assert,
  second-writer detection, rebase+push retry); spool mapping incl. unknown
  workflow.
* `tests/test_vps_deploy.py` — every scheduled workflow has a timer; every
  `OnCalendar` passes `systemd-analyze calendar`; `systemd-analyze verify`
  on the units (with a path-rewritten copy); `bash -n` on every script;
  `env.example` names every variable the units/scripts/adapter read;
  Caddyfile carries the `_headers` rules; no `DISCORD_WEBHOOK_URL` literal.
* `test/vps_api.test.js` — adapter serves each Function; KV shim TTLs;
  `/api/dispatch` fail-closed (no token -> 503, bad -> 401) and spool file
  shape; `_dispatch.js` uses DISPATCH_URL when set and GitHub otherwise;
  X-Forwarded-For -> CF-Connecting-IP. Registered in test.yml.
* Existing suites stay green. `tests/test_workflow_*` still pin the YAML.
