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

## Phase 6 — Live Validation & Gradual Capital Deployment

Complete this protocol before committing real capital to the system.
The goal is to validate execution under real market conditions while limiting downside risk.

### Stage overview

| Stage | Name | Duration | Capital | Goal |
|-------|------|----------|---------|------|
| 1 | Structured Testnet Validation | 3–4 weeks | Testnet only | Validate execution layer |
| 2 | Live vs Expected Fill Analysis | Ongoing during Stage 1–2 | N/A | Understand real slippage |
| 3 | Small Live Capital Deployment | 4–8 weeks | Very small ($3k–$8k) | First real-money test |
| 4 | Gradual Capital Scaling | Ongoing | Increasing slowly | Controlled growth |
| 5 | Post-Trade Review & Refinement | Ongoing | Live capital | Continuous improvement |

Set `LIVE_DEPLOYMENT_STAGE` in `scanner/config.py` to reflect your current stage (1–5).

---

### Stage 1 — Structured Testnet Validation (3–4 weeks)

**Objective:** Run the system on Bybit Testnet with real order flow (fake money) to validate execution.

**Preparation checklist:**
- [ ] Set `BYBIT_TESTNET=true` (GitHub Secret)
- [ ] Set very conservative risk parameters: reduce `SCALP_RISK_PER_TRADE` to $25–$50
- [ ] Enable all alert channels (Telegram + Discord + Email) and verify they fire
- [ ] Turn on detailed logging (`LOG_LEVEL=DEBUG` or similar)
- [ ] Enable pre-trade risk checks (they are enabled by default in Phase 5)
- [ ] Test Kill Switch manually: `FORCE_KILL=1 python -m scanner.broker.kill_switch`
- [ ] Test Daily Loss Circuit Breaker: add a fake -$600 PnL entry to the journal and verify the breaker fires

**During testnet:**
- Let it run without manual interference
- Monitor alerts daily
- Log any issues in a running document
- Do not override any risk rules

**Weekly review during testnet:**
1. Review all trades taken that week
2. Check slippage vs expected (`public/data/fill_analysis.json`)
3. Review any circuit breaker or kill-switch triggers
4. Check `public/data/health.json` for anomalies

**Exit criteria (must pass all before Stage 3):**
- Minimum 40–60 completed testnet trades
- At least 3–4 weeks of runtime
- No unhandled errors or system crashes
- Kill switch and circuit breakers tested at least once
- Slippage data collected (`fill_analysis.json` has at least 20 entries)

---

### Stage 2 — Live vs Expected Fill Analysis (runs parallel with Stage 1)

Every live/testnet trade records `entry` (intended price from scan) and `fill_price` (actual broker fill).
The fill analysis module computes weekly summaries in `public/data/fill_analysis.json`.

**Metrics tracked automatically:**

| Metric | Field | Description |
|--------|-------|-------------|
| Entry slippage | `entry_slip_pct` | (fill − entry) / entry × 100 — positive = worse fill |
| Slippage in R | `slip_in_r` | Slippage as fraction of the trade's risk distance |
| Weekly averages | `by_week[].avg_slip_pct` | Mean slippage per completed week |

**Weekly review protocol:**
1. Check `public/data/fill_analysis.json` → `all_time.avg_slip_pct`
2. If avg slippage is consistently > 0.3%, investigate:
   - Reduce `SCALP_RISK_PER_TRADE` (smaller orders fill better)
   - Tighten `SLIPPAGE_REJECT_PCT` in config
   - Avoid trading assets with wide spreads at open/close
3. Update expectancy calculations — subtract real slippage from expected R

---

### Stage 3 — Small Live Capital Deployment (4–8 weeks)

**Only start after successfully completing Stage 1 exit criteria.**

**Rules:**

| Rule | Value | Reasoning |
|------|-------|-----------|
| Starting capital | $3,000–$8,000 max | Set `LIVE_STAGE3_CAPITAL_MAX_USD` in config |
| Position size | 35% of normal (`LIVE_STAGE3_POSITION_MULT = 0.35`) | Applied automatically when `LIVE_DEPLOYMENT_STAGE=3` |
| Risk per trade | Max 0.5% of account | With $5k account + 35% mult + $100 risk → $35 effective risk |
| Weekly review | Every Sunday | Mandatory — see Stage 5 review template |
| Scaling rule | Only increase capital after 4+ profitable weeks with max DD < 5% | `check_stage4_milestones()` in `scaling_advisor.py` |

**Setup:**
1. Set `LIVE_DEPLOYMENT_STAGE=3` in `scanner/config.py`
2. Set `BYBIT_TESTNET=false` in GitHub Secrets
3. Set `BYBIT_LIVE_CONFIRMED=true` in GitHub Secrets
4. Fund the Bybit account with $3,000–$8,000 max
5. Run `python -m scanner.broker.bybit_run --dry-run` and verify Stage 3 sizing logs appear

**Protocol:**
1. Run the system exactly as configured — no manual order overrides
2. Review every trade at the end of each week
3. Log lessons learned in a running document
4. Only increase risk/capital after meeting Stage 4 milestones

---

### Stage 4 — Gradual Capital Scaling

The scaling advisor checks milestone conditions automatically after each run.
Check the log for `scaling advisor` lines or read `journal/bybit_run.log`.

**Milestone framework:**

| Level | Condition | Action |
|-------|-----------|--------|
| 1 | 4+ consecutive profitable weeks + max DD < 5% | Increase capital by ~37.5% (`LIVE_STAGE4_L1_BUMP`) |
| 2 | Another 4+ profitable weeks + DD < 6% | Increase capital by another ~37.5% (`LIVE_STAGE4_L2_BUMP`) |
| 3 | Consistent performance over 3+ months (13+ data weeks) | Move to normal risk parameters (`LIVE_DEPLOYMENT_STAGE=5`) |
| 4 | Proven over 6+ months (26+ data weeks) with controlled drawdowns | Scale more aggressively |

**Check milestone status:**
```bash
python -c "
import json, pathlib
from scanner.broker.scaling_advisor import check_stage4_milestones
j = json.loads((pathlib.Path('journal/scalp_journal.json')).read_text())
import pprint; pprint.pprint(check_stage4_milestones(j))
"
```

**Golden rule:** Never increase capital after a winning streak out of excitement.
Only scale after consistent, controlled performance verified by `check_stage4_milestones()`.

---

### Stage 5 — Post-Trade Review & Continuous Improvement

This should become a permanent weekly habit once the system is in production.

**Weekly review (every Sunday):**

| Area | What to review | Question |
|------|---------------|---------|
| Trade quality | All closed trades this week | Did setups play out as expected? Any patterns in winners/losers? |
| Slippage | `public/data/fill_analysis.json` → `by_week[0]` | Is it worse than expected? Any bad assets or time slots? |
| Risk management | `journal/bybit_run.log` for circuit breaker lines | Were they appropriate? Should thresholds be adjusted? |
| Regime performance | `public/data/performance.json` → `regime_breakdown` | Should risk be adjusted based on regime? |
| System health | `public/data/health.json` | Any errors, delays, or anomalies? |

**Monthly review:**
- Overall P&L and expectancy (compare to backtest baseline)
- Max drawdown and recovery time
- Performance by market regime
- Any strategy or parameter changes needed
- Review alert volume (too many? too few? useful?)

---

### Final recommendations before going live

| Area | Advice |
|------|--------|
| Don't rush Stage 3 | Many people go live too early and trade emotionally. Take your time in testnet. |
| Document everything | Keep a running log of lessons, issues, and changes. Invaluable over 6+ months. |
| Stay conservative on capital | It's better to start too small than too big. You can always scale up. |
| Treat first 2–3 months as data collection | Focus on learning, not making maximum profit. |
| Have a clear scaling plan | Decide your rules before you start making money — not during a winning streak. |

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
