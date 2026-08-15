# Vivek 5.0 — ASX · NASDAQ · Crypto swing scanner

A three-lens **swing/position** scanner that reviews ~3,500 names a day, grades the
setups it finds, and forward-tests its own A+ calls in a paper book that nobody is
allowed to edit. It publishes to a static site on Cloudflare Pages and runs entirely
on GitHub Actions.

The point of the system is **an honest track record**, not a signal feed. Every
design argument in this repo resolves the same way: a number that flatters the
record is worse than no number.

> General information only — not financial advice. No orders are ever placed
> automatically with real capital; live trading is double-gated and off.

---

## The three lenses

| Lens | What it looks for | Grades | Cadence |
|---|---|---|---|
| **VIVEK** | Reaction at the 200-SMA, with Weekly / 3-day / Daily plans | A+ / A / B+ / WATCH | Hourly in each market window |
| **PhaseMap** | Sweep → displacement zones (`docs/` spec is the source of truth) | zone quality | Nightly 08:30 UTC |
| **Specs** | 3× volume-spike base breakouts | A+ / A / B / C | Nightly, discovery-only |

Multi-lens agreement raises a **confluence** banner and a Discord ping. Specs is
discovery-only by its own backtest — it is not traded.

All weights, thresholds and grade cut-offs live in
[`scanner/config.py`](scanner/config.py). That file is the single source of truth;
the front-end mirrors its constants and `test/risk_defaults.test.js` fails the build
if the two drift.

## The bot book — the only track record

`journal/vivek_bot_book.json` is the record. It takes **A+ only**, at most 30 open
across all markets combined, one position per symbol, three per sector, behind daily
loss guards. It is marked to market server-side every scan.

It is deliberately boring to change. Trade-rule edits need explicit owner sign-off,
and while a pre-registered cycle is running the rules are frozen — every mid-cycle
tweak resets the sample and throws away the only evidence the system produces.
[`RESEARCH-LEDGER.md`](RESEARCH-LEDGER.md) is the permanent record of what has been
tested and what has been killed, so nothing gets re-litigated.

## Running it

```bash
pip install -r requirements.txt          # Python 3.11+

# scan (writes public/data/<market>_vivek.json and friends)
python -m scanner.run                    # all markets
python -m scanner.run --market asx       # one market (repeatable)
python -m scanner.run --curated          # smaller bundled ASX list — much faster
python -m scanner.run --limit 40         # quick slice for a smoke test

# the paper bot: open/manage A+ positions in the bot book
python -m scanner.broker.vivek_run

# backtests (survivor-biased — see the caveat below)
python -m scanner.vivek_backtest --market all --limit 60 --period 5y
python -m phasemap.backtest

# serve the site locally (fetch() needs http://, not file://)
python serve.py                          # then open http://localhost:8765
```

The default ASX scan covers the **full ASX-listed directory (~2,000 names)** pulled
live, so it takes a few minutes. NASDAQ uses Global Select (~1,430); crypto is the
top 100 by market cap plus pinned extras.

## Tests

```bash
python -m pytest -q                      # ~290 Python tests
for f in test/*.test.js; do node "$f"; done   # 18 JS suites, no framework
```

Both run on every push (`.github/workflows/test.yml`), plus a Playwright e2e pass, a
Lighthouse budget tripwire and a screenshot-diff gate at desktop and 390px.

Two house rules the suites enforce rather than document:

- **Tests read the shipped file.** They slice real functions out of `public/js/*.js`
  and run them, because a re-typed fixture drifts in step with the bug.
- **Any edit to a `public/js` or `public/css` asset bumps its `?v=` in every HTML
  page that loads it.** `/js/*` and `/css/*` are served with `max-age=86400`, so a
  missed bump means a day of stale code for anyone who already visited. A skew
  across pages is a bug in its own right and `test/cache.test.js` fails on it.

## Layout

```
scanner/              Python engine
  config.py           markets, thresholds, weights, grade cut-offs  <- tune here
  universe.py         ticker lists          data.py      batched yfinance downloads
  indicators.py       EMA / RSI / ATR / SuperTrend / pivots
  vivek.py            the VIVEK lens        reversal.py  retired lens (kept: spec.py imports its helpers)
  scan.py             per-market orchestration      run.py   CLI entry point
  broker/             the paper bot, risk manager, circuit breakers, kill switch
phasemap/             the PhaseMap lens (own runner, own tests)
functions/api/        Cloudflare Pages Functions — health, heartbeat, scan, close, price
public/               the deployed static site (this folder IS the deploy)
journal/              the books — vivek_bot_book.json is the track record
tests/ · test/        Python suites · JS suites
.github/workflows/    16 workflows; OPERATIONS.md has the schedule
```

## Operating it

[`OPERATIONS.md`](OPERATIONS.md) is the runbook and [`HEALTHCHECK.md`](HEALTHCHECK.md)
is the 60-second daily check. [`CLAUDE.md`](CLAUDE.md) carries the working rules for
anyone — human or agent — changing this repo.

Two endpoints exist because GitHub's cron is best-effort and every in-repo backstop
is itself a cron, so a scheduler outage takes the backstops with it:

- **`/api/health`** — the alarm. GitHub-independent; an external monitor watches it.
- **`/api/heartbeat`** — the healer. Dispatches a scan when the book goes stale,
  behind a shared cooldown and a daily cap.

## Caveats, stated plainly

- **Data is yfinance**: ~15 minutes delayed, no delisted history. Fine for operating,
  not fine for publishable backtest numbers.
- **Every backtest here is survivor-biased** — the universe is *today's* listed
  names. Use the numbers to compare cohorts, never as a return forecast. The
  Insights page carries this warning on every figure.
- **The site is public.** The manual scan and close endpoints are rate-limited but
  unauthenticated; Cloudflare Access is the real fix and is pending owner action.
