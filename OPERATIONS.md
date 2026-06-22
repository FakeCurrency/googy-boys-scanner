# Vivek's Beta Scanner — Operations Runbook

Last updated: 2026-06-22

---

## Quick reference

| What | Command |
|------|---------|
| Run scan (crypto scalp) | `python -m scanner.run crypto scalp` |
| Run Bybit executor | `python -m scanner.broker.bybit_run` |
| Dry run (log only) | `python -m scanner.broker.bybit_run --dry-run` |
| Check kill-switch | `python -m scanner.broker.kill_switch` |
| Send alert digest | `python -m scanner.alerts` |
| Run all tests | `pytest tests/ -v` |
| Serve frontend locally | `python -m http.server 8000 --directory public` |

---

## How the system runs day-to-day

GitHub Actions handles everything automatically:

| Workflow | Schedule | What it does |
|----------|----------|--------------|
| `crypto_scalp.yml` | Every 30 min (trading hours) | Scans crypto, runs Bybit executor, commits output |
| `scan.yml` | Every 30 min | Scans NASDAQ/ASX, updates scalp.json |
| `stop_watcher.yml` | Every 15 min | Checks stop/target hits on open positions |
| `kill_switch.yml` | Every hour | Standalone kill-switch check |
| `backtest.yml` | Weekly | Re-runs scalp backtest, writes backtest_results.json |

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
- Disable the `crypto_scalp.yml` workflow in GitHub → Actions → (select workflow) → … → Disable workflow

**Emergency flatten** (kill all positions now):
```bash
python -m scanner.broker.kill_switch
```
Or trigger the `kill_switch.yml` workflow manually in GitHub Actions.

**Full stop** (no scans, no orders):
- Disable `crypto_scalp.yml` AND `scan.yml` in GitHub Actions

---

## Kill switch

The kill switch fires automatically when session P&L hits -$500 (SCALP_MAX_DAILY_LOSS).

When it fires:
1. All Bybit orders are cancelled
2. All Bybit positions are closed at market
3. An alert fires via Telegram/Discord/email (if configured)
4. No new orders are placed until the next AEST session day

**Manual kill switch:**
```bash
# Check status
python -m scanner.broker.kill_switch

# Force flatten (even if loss limit not yet reached)
FORCE_KILL=1 python -m scanner.broker.kill_switch
```

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
| `GH_DISPATCH_TOKEN` | Cloudflare Pages env | PAT with `repo` + `workflow` scopes |

---

## What to do when things break

### "BYBIT_API_KEY not set — running in SIMULATED mode"
No action needed unless you want live execution. Add the secret to GitHub.

### Orders are being rejected
Check `journal/bybit_run.log` for `order skipped` lines with the reason.
Common causes: symbol not available on Bybit, qty too small, price out of range.

### Scan produces no results
1. Check `public/data/health.json` for `quality_skipped` counts
2. Check `journal/scan.log` for data quality errors
3. `yfinance` outages happen — the next run usually recovers automatically

### Kill switch fired unexpectedly
1. Check `journal/bybit_run.log` for the session P&L at trigger time
2. Check `journal/scalp_journal.json` for any unusually large losses
3. If it was a false positive (e.g. unrealised P&L not yet settled), wait for the next AEST session day

### Frontend not updating
1. Check if the last GitHub Actions run completed successfully
2. Check Cloudflare Pages deploy log for build errors
3. Force-reload the browser (Ctrl+Shift+R) to bypass cache

---

## Key file locations

| File | Purpose |
|------|---------|
| `journal/scalp_journal.json` | Source of truth for all scalp positions |
| `public/data/scalp_journal.json` | Public copy consumed by the dashboard |
| `public/data/scalp.json` | Latest scan output |
| `public/data/health.json` | Scan freshness + system health |
| `public/data/performance.json` | Daily/weekly performance metrics |
| `public/data/events.json` | Economic event calendar (update monthly) |
| `journal/bybit_run.log` | Bybit execution log |
| `journal/paper_run.log` | Alpaca paper execution log |
| `journal/scan.log` | Scanner engine log |

---

## Updating the event calendar

Edit `public/data/events.json` monthly to keep FOMC, CPI, NFP dates current.
Format:
```json
{"date": "YYYY-MM-DD", "event": "FOMC Rate Decision", "impact": "high"}
```
Impact levels: `"high"` (blocks trading), `"medium"` (no block, informational only).

---

---

## Environment modes

The system has three distinct operating modes. Never mix up credentials.

| Mode | BYBIT_API_KEY | BYBIT_TESTNET | BYBIT_LIVE_CONFIRMED | What happens |
|------|--------------|---------------|----------------------|--------------|
| **SIMULATED** | not set | any | any | Full pipeline runs; orders logged only, never sent |
| **TESTNET** | set | `true` (default) | any | Real API calls to testnet.bybit.com — no real money |
| **LIVE** | set | `false` | `true` | Real API calls to api.bybit.com — real capital at risk |

**Critical**: `BYBIT_TESTNET=false` alone is **not enough** to enable live trading.
`BYBIT_LIVE_CONFIRMED=true` must also be set as a GitHub Secret.
Without it, the executor logs an error and falls back to dry_run.

---

## Phase 5 circuit breakers

The following automatic safety mechanisms trigger before any order is submitted:

| Breaker | Threshold | Action |
|---------|-----------|--------|
| Portfolio heat | > 7% of account at risk | Block new order |
| Max open positions | ≥ 10 concurrent | Block new order |
| Drawdown — pause | ≥ 12% from equity peak | Block new orders (all) |
| Drawdown — close all | ≥ 15% from equity peak | Flatten all positions |
| Consecutive losses | ≥ 4 in a row | Block new orders |
| Anomaly detector | Scan drought / DQ spike | Block new orders |
| Daily loss | ≥ $500 session P&L loss | Block new orders |
| Daily trade cap | ≥ 5 trades/session | Block new orders |
| Correlation cap | ≥ 2 open in same group | Skip this signal |
| Sector cap | > 40% of account in one sector | Skip this signal |
| Order size (min) | Notional < $10 | Skip (data error) |
| Order size (max) | Notional > $5,000 | Skip (fat-finger guard) |
| Max slippage | Expected slip > 1% | Block; warn at > 0.3% |

All thresholds live in `scanner/config.py` — never hardcode them.

---

## Runbooks

### Runbook 1 — Daily loss circuit breaker fired

**Symptoms:** Alert received "Kill switch triggered" or "session P&L -$500".

1. Check `journal/bybit_run.log` for the triggering session P&L line.
2. Check `journal/scalp_journal.json` for the losing trades — identify the cause.
3. **Do not re-enable trading today.** Wait for the next AEST session day (counter resets at midnight AEST).
4. Review the losing trades: was it a strategy failure or an external event (flash crash, major news)?
5. If it was a news event, check `public/data/events.json` — add the event if missing.
6. If it was a strategy failure, review regime detection and reduce `SCALP_RISK_PER_TRADE` if needed.

### Runbook 2 — Drawdown circuit breaker fired (pause/close_all)

**Symptoms:** Log line `DRAWDOWN X% >= pause/close threshold`.

1. Check current equity vs peak in `journal/scalp_journal.json` → `closed[].pnl` sum.
2. **pause (12%):** No new orders until drawdown recovers. Monitor manually; manually re-enable when drawdown < 8%.
3. **close_all (15%):** All positions should already be closed by the broker call. Verify in Bybit dashboard.
4. Review all losing trades — look for regime mismatch, correlated losses, or data quality issues.
5. Run `python -m scanner.broker.bybit_run --dry-run` to verify system is stable before re-enabling.
6. To reset: once drawdown recovers, restart with `python -m scanner.broker.bybit_run`.

### Runbook 3 — Consecutive loss breaker fired

**Symptoms:** Log line `CONSECUTIVE LOSS BREAKER — last 4 trades all losses`.

1. Check the last 4 trades in `journal/scalp_journal.json`.
2. Were they all in the same regime/market? If so, regime detection may need tuning.
3. Were they in the same corr_group? If so, lower `SCALP_MAX_PER_GROUP`.
4. Check `public/data/health.json` for scan anomalies around the same time.
5. Wait 1 session day before allowing new orders (manually clear by restarting bybit_run.py).

### Runbook 4 — Orders are being rejected by pre_trade_check

**Symptoms:** Log lines `pre-trade BLOCKED sym direction — reason`.

1. Check the `failed` reasons: `portfolio_heat`, `drawdown`, `sector_cap`, `order_size`, etc.
2. For `portfolio_heat`: close some existing positions or wait for them to hit target/stop.
3. For `order_size` min: check if the entry/stop spread is reasonable — this often indicates bad scan data.
4. For `order_size` max: check `ORDER_SIZE_MAX_USD` in config.py; increase if account size has grown.
5. For `sector_cap`: you have too many open positions in one sector — let some close before adding more.

### Runbook 5 — Frontend not showing latest data

1. Check the last GitHub Actions run in the Actions tab — did `crypto_scalp.yml` pass?
2. Check `public/data/health.json` — what's the `generated_at` timestamp?
3. Force-reload the browser (Ctrl+Shift+R) to bypass Cloudflare's edge cache.
4. If Actions is failing, check `journal/scan.log` and `journal/bybit_run.log`.

---

## Backup and restore

### Creating a backup

```bash
python scripts/backup_journal.py backup
```

This copies journals, scan data, config, and log tails to `backups/YYYY-MM-DDTHH-MM-SS/`.

### Listing backups

```bash
python scripts/backup_journal.py list
```

### Restoring from a backup

```bash
python scripts/backup_journal.py restore 2026-07-01T14-30-00
```

You will be asked to type `yes` to confirm before any files are overwritten.

**Important:** Restoring does not affect live Bybit positions. After restoring, reconcile
the journal against live broker positions:
```bash
python -m scanner.broker.bybit_run --dry-run   # reconcile + log without submitting orders
```

---

## Pre-live validation checklist (Phase 5)

Complete every item before switching from TESTNET to LIVE capital.

### Tier 1 — Must pass

- [ ] **Minimum testnet period**: run TESTNET mode for at least 2 weeks with real signal flow
- [ ] **Minimum trade sample**: at least 30 testnet trades recorded in `scalp_journal.json`
- [ ] **Kill switch test**: manually trigger `FORCE_KILL=1 python -m scanner.broker.kill_switch` and verify Bybit testnet orders are cancelled
- [ ] **Drawdown test**: inject a fake losing streak into the journal and verify the circuit breaker fires
- [ ] **Consecutive loss test**: add 4 consecutive negative PnL entries, verify breaker fires
- [ ] **Pre-trade check test**: run `python -m scanner.broker.bybit_run --dry-run` with a full journal and verify all checks pass/fail as expected
- [ ] **Alert channels**: verify Telegram/Discord/email alerts actually arrive for kill_switch, order_placed, order_rejected events

### Tier 2 — Should pass

- [ ] **Slippage & fill analysis**: compare `fill_price` vs `entry` across 10+ testnet trades; avg slip should be < 0.5%
- [ ] **Live vs backtest reconciliation**: run `python -m scanner.broker.live_vs_backtest` and check that live win rate is within 10% of backtest
- [ ] **Event calendar**: verify at least one future high-impact date is in `public/data/events.json` and blackout mode activates correctly
- [ ] **Backup test**: run `python scripts/backup_journal.py backup` and verify files are created correctly
- [ ] **Gradual capital ramp-up plan**: document your ramp schedule (e.g. start at 25% of target position size, scale to 50% after 20 live trades, full size after 50 trades with positive expectancy)

### Tier 3 — Recommended

- [ ] **Stress test — flash crash**: manually set a large negative PnL and verify close_all fires at -15% drawdown
- [ ] **Stress test — API outage**: set an invalid API key and verify the system falls back to SIMULATED gracefully
- [ ] **Stress test — data quality**: delete `public/data/scalp_crypto.json` and verify the executor handles missing data gracefully
- [ ] **Live price feed**: verify Bybit mark prices are updating in reconcile (check `mark_price` in journal entries)
- [ ] **Performance baseline**: document expected win rate, avg R, and max drawdown from backtest before going live

---

## Architecture in one paragraph

GitHub Actions runs the Python scanner on a cron. Results are written as JSON
to `public/data/` and committed to `main`. Cloudflare Pages serves `public/`
as a static site — no build step. The Bybit executor reads the scan output,
applies pre-trade gates (portfolio heat, daily cap, correlation caps, loss limit,
event calendar, drawdown, consecutive loss breaker, and order size validation),
submits bracket orders via the Bybit V5 API, and writes the journal back.
The kill switch can flatten everything at any time. All alerting goes through
`scanner/broker/alert_dispatch.py`. Risk constants live in `scanner/config.py`.
