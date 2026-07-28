# Vivek 5.0 — Operations Runbook

Last updated: 2026-07-21 (bottom-half runbooks rewritten for the bot-book era — the previous versions described the retired scalp system)

---

## Quick reference

| What | Command |
|------|---------|
| Run a VIVEK scan | `python -m scanner.run --market asx` (or nasdaq / crypto) |
| Run Bybit executor (PARKED until ROADMAP P3) | `python -m scanner.broker.bybit_run` |
| Dry run (log only) | `python -m scanner.broker.bybit_run --dry-run` |
| Check kill-switch | `python -m scanner.broker.kill_switch` |
| Audit bot-book integrity (read-only) | `python -m scanner.broker.vivek_run --verify` |
| Rebuild derived combined book | `python -m scanner.broker.vivek_run --rebuild-combined` |
| Freshness watchdog (read-only preview) | `python -m scanner.watchdog --dry-run` |
| Run all tests | `pytest tests/ -v` |
| Serve frontend locally | `python -m http.server 8000 --directory public` |

---

## How the system runs day-to-day

GitHub Actions handles everything automatically:

| Workflow | Schedule | What it does |
|----------|----------|--------------|
| `scan.yml` | Market-hours crons (weekend = crypto-only) | VIVEK scans SEQUENTIALLY (nasdaq, crypto, asx) + paper bot book + confluence alert |
| `crypto_bot.yml` | Hourly, 24/7 | Crypto VIVEK scan + crypto slice of the bot book |
| `backup_book.yml` | Daily 21:35 UTC | Snapshots the bot book + journal state into `backups/` |
| `phasemap.yml` | Nightly 08:30 UTC | PhaseMap + Specs + confluence + schema gate |
| `lens_backtest.yml` | Weekly Sun | PhaseMap/Specs/VIVEK replays -> Insights stats |
| `vivek_backtest.yml` | Monthly 1st | Long-only VIVEK evidence file |
| `kill_switch.yml` | Every 30 min, 24/7 | Standalone loss check on the BOT BOOK (per market) — open positions re-priced with LIVE quotes, falling back to last-scan marks per symbol. Also hosts the freshness watchdog |
| `stop_watcher.yml` | Every 5 min | Curls /api/tick (cloud watcher for the KV-synced manual journal) |
| `close_position.yml` | Manual dispatch | journal_type=bot closes a BOT BOOK position (the real track record); swing/scalp edit the legacy journals. Re-dispatches itself (max 3) if the scan mutex evicts it — Runbook 4 |
| `test.yml` | Every push/PR | pytest + JS tests |

(Table rewritten 2026-07-20 — the previous one listed retired workflows:
crypto_scalp.yml, backtest.yml, and a 15-min stop watcher no longer exist.)

Cloudflare Pages serves `public/` automatically on every push to `main`.

---

## Starting the system

No manual start is needed — GitHub Actions runs on schedule.

To enable live broker execution:
1. Add `BYBIT_API_KEY` and `BYBIT_API_SECRET` to GitHub repo Settings → Secrets
2. Set `BYBIT_TESTNET=true` first for at least 2 weeks of paper-trading
3. Only set `BYBIT_TESTNET=false` when ready for real capital (requires deliberate opt-in)

Without `BYBIT_API_KEY`, the system runs in **SIMULATED mode** — full pipeline, no actual orders.

---

## Stopping the system

**Pause new orders only** (without touching existing positions):
- Disable `scan.yml` and `crypto_bot.yml` in GitHub → Actions → (select workflow) → … → Disable workflow

**Emergency flatten** (kill all positions now):
```bash
python -m scanner.broker.kill_switch
```
Or trigger the `kill_switch.yml` workflow manually in GitHub Actions.

**Full stop** (no scans, no orders):
- Disable `scan.yml` AND `crypto_bot.yml` in GitHub Actions

---

## Kill switch

The standalone check (kill_switch.yml, every 30 min, 24/7) reads the BOT BOOK
per market and fires when a market's session P&L (today's realised + open
unrealised) breaches VIVEK_BOT_MAX_DAILY_LOSS_PCT of VIVEK_BOT_ACCOUNT_EQUITY.

**The dollar figure moved on 2026-07-28** with fixed-notional sizing: equity is
now $150,000 (was $10,000), so the 3% daily limit is **$4,500 per market** and
the 6% weekly limit is $9,000 — up from $300/$600. Equity no longer sizes
positions (that is `VIVEK_BOT_POSITION_NOTIONAL`, a flat $5,000 x 30 slots);
it survives precisely to scale these guards and the leverage ceiling, which is
why it had to move with the book rather than stay at the old figure.
Open positions are re-priced with LIVE quotes at check time (2026-07-20
Phase 4) — one batched fetch; any symbol that can't be quoted falls back to
the mark stamped at the last scan, so the check degrades gracefully instead
of failing.

When it fires:
1. All Bybit orders are cancelled (only if broker keys are configured)
2. All Bybit positions are closed at market (same condition)
3. An alert fires via Telegram/Discord/email (if configured)
4. The paper book itself is NOT modified — the runner's own guard halts new
   entries for the session

**Manual kill switch:**
```bash
python -m scanner.broker.kill_switch          # add --dry-run to log only
```
(Note 2026-07-20: the previously documented FORCE_KILL env var never existed
in code; the switch fires on the bot book's daily-loss limit.)

---

## Watchdog alerts (2026-07-20, Phase 5)

`scanner/watchdog.py` runs inside kill_switch.yml (every 30 min) and
crypto_bot.yml (hourly). It exists because of the 2026-07-20 incident: runs
can finish GREEN while committing nothing, and GitHub's cron can silently
skip runs for hours — neither produced any alert. The watchdog covers both:
content probes (timestamps inside committed files) and run-history probes
(GitHub API: each critical workflow's last successful run).

**Noise contract:** one alert on first detection, one reminder every 6h
while unresolved, one recovery notice — never a message per check. If a run
FAILED outright, GitHub's own failure email is the alert; the watchdog stays
quiet about that workflow. CRITICAL = Discord/Telegram + email; WARNING = no
email. Thresholds live in scanner/config.py (WATCHDOG_*).

**What each alert means / what to do:**

- *"bot book updated_at is Nh old"* (CRITICAL) — no run has SAVED the track
  record recently. Check Actions: are crypto_bot/scan runs green but
  committing nothing (staging problem — see the assert_staged gate), or not
  firing at all (scheduler)? Dispatch "Crypto bot" manually; if its commit
  step stages nothing, that run's log now says exactly why.
- *"book MISSING / unreadable"* (CRITICAL) — restore from git history or
  `backups/` (see Runbooks), then `python -m scanner.broker.vivek_run
  --verify`.
- *"<workflow>: last successful run Nh ago"* — the schedule is being skipped
  or the workflow is failing silently. Open Actions → that workflow. If
  GitHub's scheduler is degraded (runs simply absent), dispatch manually;
  it self-heals when the scheduler recovers.
- *"newest backup is Nh old"* (CRITICAL) — the track record isn't being
  snapshotted. Dispatch "Backup bot book" manually today, then investigate.
- *"PhaseMap latest.json is N days behind"* — the nightly didn't publish;
  dispatch "PhaseMap nightly scan" manually.

**Must-change gates:** scan.yml / crypto_bot.yml / phasemap.yml /
backup_book.yml now FAIL (red run → email + Discord) when a scheduled run
stages none of its must-change outputs (`scripts/assert_staged.sh`). A red
run with "ASSERT-STAGED FAILED" means output is being produced but LOST
between the scan step and git — exactly the Phase 3 staging bug pattern.
Manual dispatches only warn (dry-runs/tests legitimately stage nothing).

**External heartbeat (2026-07-21, Phase 6):** `GET /api/health` on the site
returns 200 while the published bot book is under 4h old, 503 otherwise —
served entirely by Cloudflare, zero GitHub involvement. Point a free external
monitor at it so pipeline silence alerts you even if GitHub's scheduler (and
therefore the in-repo watchdog) is down:

1. Sign up at uptimerobot.com (free tier is fine).
2. Add monitor → type "HTTP(s)" → URL
   `https://googy-boys-scanner.pages.dev/api/health` → interval 5 min.
3. Add your email as the alert contact. Done — it emails on 503/timeouts
   and again on recovery. (`?max_h=N` overrides the threshold per-probe.)

**Per-market mode (2026-07-28):** `?market=asx|nasdaq|crypto` asks "did THIS
market scan?" instead of "is the pipeline alive?", reading that market's
`public/data/<m>_prices.json` sidecar rather than the combined book. Use it when
you want to know whether one market has gone quiet — the default answer stays
green off any other market's commit, which is right for an uptime monitor and
wrong for a per-market check. scan.yml's `:47` ASX backstop uses it; an unknown
market name returns 400 rather than a misleadingly healthy 200.

**Prove the alert channels deliver:**
```bash
python -m scanner.watchdog --test-alert   # with DISCORD_WEBHOOK_URL / GBS_SMTP_* / TELEGRAM_* exported
```
Prints, per severity route, which channels actually delivered and which are
unconfigured/failing. Run it once after any secret change — an unexercised
email path is a CRITICAL that silently degrades to Discord-only.

**Mark-sanity guard (2026-07-21, Phase 6):** a position mark that moves more
than VIVEK_MARK_SANITY_PCT (ASX/NASDAQ 35%, crypto 60%) against its last
accepted mark — a split under auto_adjust, or a vendor bad print — does NOT
manage the position: stops/TPs pause, `suspect_price_runs` counts on the
position (visible in the book), an "anomaly" alert fires on the 2nd
consecutive hit, and the price is ACCEPTED on the 3rd so a real crash is
delayed at most two runs, never ignored. The kill switch drops such quotes
the same way (falls back to the stamped mark). If you get the alert: check
the symbol for a split/halt; nothing to do if it's real — the guard
self-resolves either way.

---

## Environment variables

### Required for live trading
| Variable | Where | Purpose |
|----------|-------|---------|
| `BYBIT_API_KEY` | GitHub Secret | Bybit key ID |
| `BYBIT_API_SECRET` | GitHub Secret | Bybit HMAC secret (or use RSA below) |
| `BYBIT_PRIVATE_KEY` | GitHub Secret | RSA private key PEM (alternative to API_SECRET) |

### Optional — broker mode
| Variable | Default | Purpose |
|----------|---------|---------|
| `BYBIT_TESTNET` | `true` | Use testnet endpoint. Set to `false` ONLY for live capital. |

### Optional — alerts
| Variable | Purpose |
|----------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Target chat ID (negative for group chats) |
| `DISCORD_WEBHOOK_URL` | Discord webhook URL |
| `GBS_SMTP_HOST` | SMTP hostname for email alerts |
| `GBS_SMTP_PORT` | SMTP port (default 587) |
| `GBS_SMTP_USER` | SMTP username |
| `GBS_SMTP_PASS` | SMTP password |
| `GBS_ALERT_TO` | Alert recipient email |
| `GBS_ALERT_FROM` | Alert sender email (defaults to SMTP_USER) |

### Required for GitHub dispatch (Cloudflare Functions)
| Variable | Where | Purpose |
|----------|-------|---------|
| `GH_DISPATCH_TOKEN` | Cloudflare Pages env | Fine-grained PAT scoped to **this repo only** with "Actions: Read and write" (see functions/api/scan.js). Avoid classic account-wide `repo`+`workflow` tokens — they can touch every repo on the account. |

---

## What to do when things break (runbooks — bot-book era)

*(Rewritten 2026-07-21. The old runbooks 1–5 described the retired scalp
system — scalp_journal.json, crypto_scalp.yml, SCALP_* knobs — and would have
walked an incident responder into dead files. Git history has them.)*

### Runbook 1 — Watchdog CRITICAL: "bot book updated_at is Nh old"
No run has SAVED the track record recently. See "Watchdog alerts" above for
the full decision tree; the short version:
1. GitHub → Actions: are `crypto_bot` / `scan` runs green but committing
   nothing (the run log's assert_staged line says exactly why), or absent
   (scheduler outage)?
2. Dispatch "Crypto bot" manually. If it commits, the scheduler was skipping;
   it self-heals. If it stages nothing, read that run's log — the staging gate
   prints the missing outputs.
3. Never edit the book by hand to "fix" freshness.

### Runbook 2 — Book corrupt or missing
The runner ABORTS on an unreadable book (BookCorruptError) and touches
nothing, so the damage is contained at detection.
1. `python -m scanner.broker.vivek_run --verify` — read-only; lists exactly
   what is wrong (unparseable file, cross-market strays, duplicate opens,
   stale combined view).
2. Stale/missing COMBINED view only → `python -m scanner.broker.vivek_run
   --rebuild-combined` (the canonical per-market files are the record; the
   combined file is derived and always regenerable).
3. A damaged CANONICAL file → restore it (see "Backup and restore" below),
   then `--verify` again, then let the next scheduled run proceed.
4. Never hand-edit position rows. If a single position is genuinely wrong,
   close it via close_position.yml with a note, and record why.

### Runbook 3 — Daily/weekly loss guard or kill switch fired
1. The alert names the market and the breached limit
   (`VIVEK_BOT_MAX_DAILY_LOSS_PCT` 3% / `VIVEK_BOT_MAX_WEEKLY_LOSS_PCT` 6% of
   `VIVEK_BOT_ACCOUNT_EQUITY` — $4,500 / $9,000 since the 2026-07-28 equity
   move; see Kill switch above). The runner halts NEW entries for that market;
   open positions keep being managed. The half-hourly kill switch
   (kill_switch.yml) independently re-checks the book with live quotes and
   only flattens a broker if broker keys are set (none are, in paper).
2. Read the guard block in `journal/vivek_bot_book.<market>.json` for the
   session numbers it saw.
3. Do nothing to the book. The guard resets on the next session day. If the
   loss came from ONE position gapping, check the symbol for news/corporate
   action; the mark-sanity guard (above) covers splits/bad prints.
4. Only investigate rules if guards fire repeatedly — and remember: no rule
   changes while the sample is accumulating (ROADMAP P1).

### Runbook 4 — Close one bot-book position manually
GitHub → Actions → "Close position (manual)" → Run workflow:
`journal_type=bot`, symbol, direction, market, exit price (use the live
quote), exit date blank for today. Leave `attempt` at 1 — it is the internal
retry counter, not something you set. The close runs the `--verify` gate after
writing. `swing`/`scalp` journal_types edit the RETIRED legacy journals — never
use them for the track record.

It queues behind any running scan (same `scan` concurrency group — one book
writer at a time; expect up to ~15 min). GitHub keeps only ONE run pending per
group, so a close waiting behind a scan can be evicted by a later arrival —
**since 2026-07-28 it re-dispatches itself when that happens** (REFINEMENTS
#109), up to 3 attempts, and you will see a fresh "Close position (manual)" run
appear a couple of minutes later with `attempt=2`. What you should still check:

- If the re-dispatch chain hits attempt 3 the last run FAILS loudly with a job
  summary saying so. Run the close by hand at a quieter time.
- A close that FAILED (red, not cancelled) is never retried — that is a real
  error, usually a symbol/direction that matches no open position. Read the log.
- A run you cancel yourself is not resurrected: the re-dispatch only fires when
  the close job executed zero steps, which is what an eviction looks like.

### Runbook 5 — Frontend stale or site down
1. `https://googy-boys-scanner.pages.dev/api/health` — 200 = the published
   book is <4h old (the pipeline is fine; it's a display problem);
   503 = the pipeline is stale (see Runbook 1).
2. Check the last Actions run, then Cloudflare Pages deploy log.
3. Hard-reload (Ctrl+Shift+R). The service worker is network-first for data
   and HTML, so a normal reload usually suffices.

### Runbook 6 — Scan produced nothing / garbage
yfinance outages happen. A scan with no results does not touch open
positions' management (they re-mark on whatever prices ARE available; a
symbol with no price gets `unpriced_runs` counted on the position instead of
a silent stale mark). The next run usually recovers. Only investigate after
two consecutive empty scheduled runs — then check the run log's download
errors and yfinance GitHub issues before touching anything.

---

## Key file locations (current)

| File | Purpose |
|------|---------|
| `journal/vivek_bot_book.<market>.json` | CANONICAL per-market track record — the record itself |
| `journal/vivek_bot_book.json` + `public/data/vivek_bot_book.json` | Derived combined view (regenerable) |
| `public/data/bot_rules.json` | The executing bot's rule constants, published each scan (dashboard reads them) |
| `public/data/<m>_vivek.json` | Latest VIVEK scan per market |
| `public/data/phasemap/<m>/latest.json` (+ `narrations.json`) | Latest PhaseMap per market |
| `public/data/<m>_spec.json` | Latest Specs (discovery) scan |
| `public/data/vivek_backtest.json` / `vivek_backtest_longonly.json` | Weekly / monthly backtest evidence |
| `public/data/events.json` | Economic event calendar (owner-maintained, update monthly) |
| `backups/<timestamp>/` | Nightly book snapshots (see below) |
| `journal/journal.json`, `journal/scalp_journal.json` | FROZEN legacy history — kept for reference, never written |

*(2026-07-21: the scalp-era `public/data` files — health.json,
performance.json, expectancy.json, attribution.json, fill_analysis.json,
health_runtime.json, journal.json, bot data charts/scalp/ — were deleted; they
had frozen in June and contradicted the real record. `bot_status.json` remains
only as the AI-BOT page's frozen seed; the page labels it stale.)*

---

## Updating the event calendar

Edit `public/data/events.json` monthly to keep FOMC, CPI, NFP dates current.
Format:
```json
{"date": "YYYY-MM-DD", "event": "FOMC Rate Decision", "impact": "high"}
```
Impact levels: `"high"` (blocks the parked live executor), `"medium"`
(informational).

---

## Backup and restore

**What runs:** backup_book.yml, nightly 21:35 UTC. It snapshots the canonical
book files + legacy journals + events.json + config.py into
`backups/<timestamp>/` (keep 30), commits ONLY that directory, and — since
2026-07-21 — also uploads the whole `backups/` set as a GitHub Actions
artifact (90-day retention). The artifact is the OFF-TREE copy: a bad
force-push or repo corruption can no longer take the record and every backup
with it in one stroke. The watchdog alerts (CRITICAL) if the newest snapshot
is >26h old.

**Restore (repo copy):**
```bash
python scripts/backup_journal.py list
python scripts/backup_journal.py restore <backup-dir>   # asks for "yes"
python -m scanner.broker.vivek_run --rebuild-combined
python -m scanner.broker.vivek_run --verify
```

**Restore (artifact copy, if the tree itself is damaged):** Actions →
"Backup bot book" → pick a run → download the `book-backups-*` artifact →
unzip into `backups/` → same restore commands.

**Drill protocol (run one every ~3 months):** restore the latest snapshot
into a scratch clone, run `--rebuild-combined` + `--verify`, confirm "book
verify OK" with plausible open/closed counts, discard the clone. A backup
that has never been restored is a hope, not a backup.

- 2026-07-21 — drill on snapshot `2026-07-20T22-32-20` in a scratch clone:
  restore + rebuild + verify OK (3 market files, 24 open / 4 closed).

---

## Circuit breakers (Bybit live-executor path — PARKED until ROADMAP P3)

`pre_trade_check.py` / `circuit_breaker.py` gate the BYBIT executor
(`bybit_run.py`), which does not run on any schedule today. They are built
and unit-tested, and become load-bearing only when live execution is wired.
The PAPER book's active protections are the ones above: daily/weekly loss
guards, the 30-open-across-all-markets ceiling + one-per-symbol and
3-per-sector caps, re-entry cooldown
(`VIVEK_BOT_REENTRY_COOLDOWN_DAYS` 7), time stop (`VIVEK_BOT_MAX_HOLD_DAYS`
28), mark-sanity guard, book integrity gates.

Headline breaker thresholds (all in `scanner/config.py`): portfolio heat 7%,
drawdown pause 12% / flatten 15%, ≥4 consecutive losses, order notional
$10–$5,000, daily loss and trade caps, sector/correlation caps, slippage
reject. Re-verify every number against config before relying on this
paragraph — config is the source of truth, prose is not.

### Environment modes (unchanged — the three-key live gate)

| Mode | BYBIT_API_KEY | BYBIT_TESTNET | BYBIT_LIVE_CONFIRMED | What happens |
|------|--------------|---------------|----------------------|--------------|
| **SIMULATED** | not set | any | any | Full pipeline; orders logged only |
| **TESTNET** | set | `true` (default) | any | Real API calls to testnet — no real money |
| **LIVE** | set | `false` | `true` | Real capital at risk |

`BYBIT_TESTNET=false` alone is NOT enough — without `BYBIT_LIVE_CONFIRMED=true`
the executor logs an error and falls back to dry-run. The per-market mode flip
in config.py is the third gate.

### Path to live capital (condensed — ROADMAP P3 is the source of truth)

1. **First:** the paper book proves or kills the edge (~30 closed, untouched
   rules). No live work before that.
2. One supervised END-TO-END testnet drill: place → fill → reconcile →
   kill-switch flatten.
3. Live tiny (0.1%/trade), crypto only, ≥2 weeks in parallel with paper.
4. Normal sizing only after the parallel period matches expectations.

---

## Alert routing (current)

All scanner alerts go through `alert_dispatch` / `alert_router.smart_send()`:

| Severity | Channels | Typical events |
|----------|----------|----------------|
| CRITICAL | Discord + Telegram + Email | book corrupt, book/backup stale (watchdog), kill_switch, scan_error |
| WARNING  | Discord + Telegram | suspect price (mark-sanity), loss guard, staleness warnings |
| INFO     | log only | routine events |

Tuning lives in `scanner/config.py` (`ALERT_SEVERITY`, `ALERT_CHANNELS`,
`ALERT_RATE_LIMITS`). Note: rate-limit state does NOT survive between Actions
runs (nothing commits `journal/alert_state.json` — deliberately), so treat
the limiter as per-run; the watchdog's own first/6h/recovery contract is what
prevents alert storms across runs.

**Proving delivery:** Actions → "Alert-path self-test" → Run workflow (added
2026-07-21). It sends one clearly-labelled test message through every
configured channel and prints per-channel delivery in the job summary. Run it
after ANY alert-secret change. A green job does NOT mean all channels
delivered — read the summary.

---

## Weekly review (current files — every Sunday, ~10 minutes)

1. JOURNAL page (or `public/data/vivek_bot_book.json`): open/closed counts,
   anything with `suspect_price_runs` or `unpriced_runs` stuck on.
2. `/api/health` returns 200; external monitor (UptimeRobot) shows no
   incidents this week.
3. Actions: any red runs this week? Any watchdog Discord messages?
4. `backups/` has last night's snapshot; artifact uploaded.
5. Insights page (weekly backtest) — context only. NO rule changes while the
   book sample accumulates (ROADMAP P1).

---

## Architecture in one paragraph

GitHub Actions runs the three Python lenses on crons and writes JSON into
`public/data/`, committed to `main`; Cloudflare Pages serves `public/` as a
static site (no build step) plus a few Pages Functions (`/api/*`: scan/close
dispatch, KV journal sync, price proxies, and the GitHub-independent
`/api/health` heartbeat). The paper-book runner (`vivek_run.py`) fills A+
plans at observed intraday prices into per-market canonical book files —
the system's only track record — under daily/weekly loss guards, slot caps,
a mark-sanity guard and hard integrity gates (corrupt book → loud abort;
post-write `--verify`; must-change staging asserts). A half-hourly
kill-switch workflow re-prices the book with live quotes, and the freshness
watchdog alerts (Discord/Telegram/email, strict noise rules) when anything
stops updating. Bybit live execution exists behind three explicit gates and
is parked until the paper record earns it.
