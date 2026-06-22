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

## Architecture in one paragraph

GitHub Actions runs the Python scanner on a cron. Results are written as JSON
to `public/data/` and committed to `main`. Cloudflare Pages serves `public/`
as a static site — no build step. The Bybit executor reads the scan output,
applies pre-trade gates (daily cap, correlation caps, loss limit, event calendar,
regime filter), submits bracket orders via the Bybit V5 API, and writes the
journal back. The kill switch can flatten everything at any time. All alerting
goes through `scanner/broker/alert_dispatch.py`.
