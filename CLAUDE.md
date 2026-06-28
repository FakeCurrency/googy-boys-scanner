# Vivek 5.0 — CLAUDE.md

This file is read automatically at the start of every Claude Code session.
Read it fully before touching any code.

---

## What this project is

A multi-market trading signal scanner + paper-trade journal + (in-progress) live execution bot.
Owner: Vivek (Australia). Brand name everywhere: **Vivek 5.0** (renamed from "Vivek's Beta Scanner") — never "Googy Boys Scanner".

**The goal:** autonomous scalp trading bot that detects setups, places bracket orders at a broker,
manages exits, and journals everything — starting with crypto (Bybit), later expanding to ASX and
commodity futures via IBKR.

---

## Tech stack

| Layer | What |
|-------|------|
| Scanner engine | Python (`scanner/`) — runs in GitHub Actions |
| Frontend | Vanilla JS + CSS — static site on **Cloudflare Pages** (`public/`) |
| Backend API | Cloudflare Pages Functions (`functions/api/*.js`) — CF Workers runtime |
| Scheduler | GitHub Actions cron (`.github/workflows/`) |
| Data source | `yfinance` — free, delayed ~15 min (adequate for 1h/1d bars) |
| Broker (planned) | **Bybit** for crypto futures; **IBKR** for ASX + commodity futures |
| Live crypto prices | Bybit WS / Binance WS — free, real-time (to be wired) |

---

## Repository layout

```
scanner/             Python signal engines + journal managers
  config.py          ALL tunable constants live here — never hardcode magic numbers
  signals.py         Daily Fib-EMA pullback scanner (long)
  reversal.py        Base-breakout / trend-reversal scanner
  spec.py            Speculative volume-spike breakouts
  short.py           Bearish pullback scanner (mirror of signals.py)
  scalp.py           1h TTM-squeeze intraday scanner
  indicators.py      EMA, SMA, RSI, ADX, SuperTrend, pivot highs/lows
  grading.py         grade_from_points(), score_chips() — shared scoring
  journal.py         Swing paper-trade journal (long + short)
  scalp_journal.py   Scalp paper-trade journal (1h bars, pessimistic fill model)
  data.py            yfinance batch downloader (chunked, with retry)
  alerts.py          Email digest builder
  run.py             CLI entry point: python -m scanner.run [market] [scan_type]
  broker/            Live execution module (currently Alpaca wired; switch to Bybit)
    alpaca_client.py  Alpaca paper/live bracket orders — REPLACE with bybit_client.py
    bracket_order.py  OCO bracket logic — reuse for Bybit
    reconcile.py      Syncs broker fills back into journal
    kill_switch.py    Flattens all positions if daily loss limit breached

public/              Static frontend (Cloudflare Pages serves this)
  index.html         Main dashboard
  journal.html       Paper-trade journal page
  js/journal.js      Journal JS — ALWAYS bump ?v= query string on edit (currently v=17)
  js/app.js          Dashboard JS
  css/styles.css     Global styles
  css/journal.css    Journal-specific styles (has both .jr-* and .mj-* classes — keep both)
  data/              Scan output JSON files (written by GitHub Actions, read by frontend)

functions/api/       Cloudflare Pages Functions (CF Workers runtime — NOT Node.js)
  scan.js            Triggers GitHub Actions scan dispatch
  price.js           Live price proxy → Yahoo Finance (avoids CORS)
  close.js           Triggers close_position.yml workflow
  quote.js           Single-ticker quote endpoint
  tick.js            Tick/stream endpoint

.github/workflows/
  scan.yml           Main scan scheduler (every 30 min, trading hours)
  crypto_scalp.yml   1h crypto scalp scan
  stop_watcher.yml   Cloud-side stop/target checker (runs between scans)
  close_position.yml Manual position close (dispatched by /api/close)
  backtest.yml       Weekly scalp backtest
  kill_switch.yml    Emergency flatten — dispatched by broker/kill_switch.py

journal/             Source-of-truth journal JSON (committed by Actions)
  journal.json       Swing longs + shorts
  scalp_journal.json Scalp positions

data/                Universe files, market caps cache
data_universe/       Ticker lists per market
```

---

## Scanner engines — how each one works

### Pullback (signals.py)
Daily bars. Finds stocks in an uptrend (above EMA 144) that have pulled back to a Fibonacci EMA
(21/34/55). Entry at EMA, stop below swing low, target at nearest resistance.
Score out of 15: alignment(3) + pullback(3) + confluence(3) + compression(2) + weekly(1) + volume(1) + adx(1) + rsi_pullback(1).

### Reversal (reversal.py)
Daily bars. Finds beaten-down stocks turning up: 9-SMA crossing over 26-SMA, price above both,
volume expansion. Score out of 14: reclaim(4) + base(3) + volume(3) + breakout(2) + rsi(2).

### Spec (spec.py)
Daily bars. Volume-spike breakouts from a base — cheap/beaten-down names with a 3× volume spike.
Mandatory gates: spike ≥ 3×, off high ≥ 40%, price > base high, 9-SMA rising. Score out of 11.

### Short (short.py)
Daily bars. Mirror of pullback but bearish. Hard gates: sustained downtrend (≥75% bars below EMA144),
bear EMA stack, no ascending pivot lows, weak bounce volume. Score out of 13.

### Scalp (scalp.py)
**1h bars.** TTM Squeeze momentum: Bollinger Bands inside Keltner Channels = squeeze, then momentum
histogram fires long or short. Also checks EMA trend, RSI, volume. Score out of 8.
Runs across crypto, select NASDAQ, and select ASX instruments on 30-min cron.

---

## Grading system

```
A+  → top tier, immediately tradeable
A   → tradeable
B   → watch list
C   → weak / informational
```

Grades A+/A can be demoted to B if R:R < 1.5 (`DEMOTE_LOW_RR = True` in config.py).

---

## Journal model

**Swing journal** (`journal.py` + `journal/journal.json`):
- Max 10 concurrent longs, 10 shorts
- $1,000 AUD per trade, $5 brokerage each way
- Stop/target checked on every scan run via `stop_watcher.yml`
- Atomic writes: temp file + `os.replace()` — never corrupt on crash

**Scalp journal** (`scalp_journal.py` + `journal/scalp_journal.json`):
- Pessimistic fill model: next-bar-open + 0.03% slippage
- Stop-gap detection: if the stop is hit on the very first bar the position never really opened
  → those trades are flagged `skip_daily_count: true`
- Daily trade cap (5) and daily loss limit ($500) reset at 08:00 UTC
- Correlation groups: max 2 open positions per group (metals, energy, us_tech, etc.)

**Manual journals** (My Stocks / My Crypto):
- Stored in browser `localStorage`, optionally synced via Cloudflare KV (`gbs-sync.js`)
- Separate from the paper-trade journals above

---

## Key config constants (scanner/config.py)

All thresholds live here. Never hardcode numbers in scanner logic — always add to config.py first.

Important ones:
```python
EMA_PERIODS = [8, 13, 21, 34, 55, 89, 144]
PULLBACK_EMAS = [21, 34, 55]
PULLBACK_TOL = 0.025        # within 2.5% of EMA counts as pullback
COMPRESSION_TOL = 0.06
CONFLUENCE_BAND = 0.02
VOLUME_MULT = 1.4
DEMOTE_LOW_RR = True
MIN_TRADEABLE_RR = 1.5
SPEC_VOL_SPIKE = 3.0        # mandatory 3× volume spike for specs
SHORT_DOWNTREND_BARS = 15
SCALP_LEVERAGE = 5
SCALP_MAX_TRADES_PER_DAY = 5
SCALP_MAX_DAILY_LOSS = 500
SCALP_DAY_ANCHOR_UTC = 8    # daily reset hour
```

---

## Deployment

**Cloudflare Pages** serves `public/` automatically on every push to `main`.
There is no build step — it's static HTML/CSS/JS.

**Always push to `main`** for changes to go live. Feature branches don't deploy.

**GitHub Actions** runs the scanner on schedule and commits output JSON back to `main`.
Secrets needed in GitHub repo settings:
- `GH_DISPATCH_TOKEN` — PAT with `repo` + `workflow` scopes (used by CF Functions to trigger scans)
- `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` — Alpaca paper broker (currently wired but REPLACING with Bybit)
- `BYBIT_API_KEY` / `BYBIT_API_SECRET` — **next to add** (Bybit futures execution)
- `IBKR_*` — future (ASX + commodity futures via IB Gateway)

---

## Broker integration — current state + next steps

### What's built (scanner/broker/)
- `bracket_order.py` — OCO bracket order model (entry + stop + target as one linked order)
- `alpaca_client.py` — Alpaca paper API client (submits brackets, handles fills)
- `reconcile.py` — syncs broker fill prices back into the JSON journal
- `kill_switch.py` — emergency flatten if daily loss limit is breached between scans

### What needs to happen next: **swap Alpaca → Bybit**
1. Create `scanner/broker/bybit_client.py` using the `pybit` library (`pip install pybit`)
2. Bybit Unified Trading Account → Futures API → USDT perpetuals
3. Replicate the bracket order pattern: entry order + linked SL + TP
4. Wire `BYBIT_API_KEY` + `BYBIT_API_SECRET` as GitHub Secrets
5. Set `BYBIT_TESTNET=true` first (Bybit has a full testnet at `testnet.bybit.com`)
6. Run parallel with paper journal for ≥2 weeks before enabling real capital

### Future: IBKR for ASX + commodity futures
- Use `ib_insync` Python library (wraps the TWS API)
- Requires IB Gateway running on a VPS (always-on, connects to IBKR servers)
- Gives real-time data + order execution for: ASX stocks, Gold/Oil/Gas futures (CME/CBOT), NASDAQ stocks
- See ROADMAP.md item #4

---

## Cloudflare Functions — important constraints

Functions live in `functions/api/` and run in the **CF Workers runtime** (not Node.js):
- No `require()` — use `import` or inline everything
- No file system access
- `fetch()` is available globally (no need to import)
- Environment variables accessed via `context.env.VARIABLE_NAME`
- `GH_DISPATCH_TOKEN` must be set in Cloudflare Pages dashboard → Settings → Environment Variables

---

## Development rules

1. **Brand name:** Always "Vivek 5.0" — never "Vivek's Beta Scanner" or "Googy Boys Scanner"
2. **Config first:** Any new threshold/constant goes in `config.py` before being used in logic
3. **Version bump:** Every edit to `public/js/journal.js` → bump `?v=` in `journal.html` (currently v=17)
4. **Atomic writes:** Journal saves must use `_atomic_write()` (temp + os.replace) — never write directly
5. **Push to main:** All changes go to `main` for Cloudflare Pages to pick up
6. **No magic numbers** in scanner logic — they belong in config.py
7. **Feature branch:** `claude/how-you-go-m2wk8c` was the feature branch; it's now merged. New work goes on `main` or a new branch merged back to `main`
8. **CF Functions:** Remember Workers runtime constraints (no Node.js builtins)

---

## Running the scanner locally

```bash
# Install deps
pip install -r requirements.txt

# Run a scan
python -m scanner.run asx pullback
python -m scanner.run nasdaq reversal
python -m scanner.run crypto scalp

# Serve the frontend locally
python serve.py   # or: python -m http.server 8000 --directory public

# Backtest
python -m scanner.scalp_backtest
```

---

## What's working ✅ vs what's next 🔜

| Feature | Status |
|---------|--------|
| Pullback / Reversal / Spec / Short daily scanners | ✅ live |
| Scalp 1h TTM-squeeze scanner | ✅ live |
| Paper-trade journal (swing + scalp) | ✅ live |
| Cloud stop/target watcher | ✅ live |
| Manual journal (My Stocks / My Crypto) | ✅ live |
| Close-position modal with live price | ✅ live |
| Scalp backtest (out-of-sample) | ✅ live |
| Email alerts | ✅ live |
| **Bybit live execution (crypto futures)** | 🔜 next |
| **Real-time crypto prices via Bybit/Binance WS** | 🔜 next |
| **IBKR integration (ASX + commodity futures)** | 🔜 future |
| Site privacy (Cloudflare Access) | 🔜 future |
