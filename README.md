# Vivek 5.0 — ASX · NASDAQ · Crypto swing scanner

A three-lens **swing/position** scanner that reviews ~3,600 names a day, grades the
setups it finds, and forward-tests its own high-conviction calls in a paper book
that nobody is allowed to edit. It publishes to a static site on Cloudflare Pages
and runs on GitHub Actions, driven by free cron-job.org pings.

The point of the system is **an honest track record**, not a signal feed. Every
design argument in this repo resolves the same way: a number that flatters the
record is worse than no number.

Paper only: no order is ever placed with real capital.

---

## The lenses

| Lens | What it looks for | Grades | Cadence |
|---|---|---|---|
| **VIVEK** | Reaction at the 200-SMA, with Weekly / 3-day / Daily plans | A+ / A / B+ / WATCH | Hourly in each market's session, plus a closing scan; crypto hourly 24/7 |
| **PhaseMap** | Sweep → displacement zones (the owner's master spec is the source of truth) | zone quality | Nightly |
| **Specs** | 3× volume-spike base breakouts under $0.50 | A+ / A / B | Nightly, discovery-only |

Multi-lens agreement raises a **confluence** banner, a chip on the deck and a line
on the ALERTS page (labelled unproven: the evidence so far shows no edge). Specs
is discovery-only by its own backtest — it is not traded. Two more lenses are
report-only and outside every signal path: **MOMENTUM** (EMA + RSI-divergence
screen after each close) and **IGNITION** (coil → breakout, crypto / ASX /
NASDAQ, with its own replay against random timing).

All weights, thresholds and grade cut-offs live in
[`scanner/config.py`](scanner/config.py) — the single source of truth. The
front-end mirrors a handful of its constants, and
`tests/test_js_config_mirrors.py` fails the build if they drift.

## The bot book — the only track record

`journal/vivek_bot_book.<market>.json` (one canonical file per market) is the
record. It takes **A/A+ longs in the four high-conviction cells** (1W reclaim,
1W break, 3D reclaim, 1D break) on rows reacting at a weekly or 3-day level, at
most 60 open across all markets at a fixed $2,500 each (the same $150,000 book
as the earlier 30 × $5,000), one position per symbol, six per sector per market,
behind windowed daily/weekly loss guards and a 28-day time stop. It is marked to
market server-side every scan.

It is deliberately boring to change. Trade-rule edits need explicit owner
sign-off, and while a cycle is running the rules are frozen — every mid-cycle
tweak resets the sample and throws away the only evidence the system produces.
The current open questions and their pre-registered checkpoints are in
[`docs/DECISIONS_2026-10-14.md`](docs/DECISIONS_2026-10-14.md);
[`docs/archive/RESEARCH-LEDGER.md`](docs/archive/RESEARCH-LEDGER.md) records
what was tested and killed earlier, so nothing gets re-litigated.

## Running it

```bash
pip install -r requirements.txt          # Python 3.12 (the version CI runs)

# scan (writes public/data/<market>_vivek.json and friends)
python -m scanner.run                    # all markets
python -m scanner.run --market asx       # one market (repeatable)
python -m scanner.run --curated          # smaller bundled ASX list — much faster
python -m scanner.run --limit 40         # quick slice for a smoke test

# the paper bot: audit the book (read-only)
python -m scanner.broker.vivek_run --verify

# backtests (survivor-biased — see the caveat below)
python -m scanner.vivek_backtest --market all --limit 60 --period 5y
python -m phasemap.backtest

# serve the site locally (fetch() needs http://, not file://)
python serve.py                          # then open http://localhost:8765
```

The default ASX scan covers the **full ASX-listed directory (~2,000 names)** pulled
live, so it takes a few minutes. NASDAQ uses Global Select (~1,430); crypto is the
top 200 by market cap (stablecoins and tokenised cash funds removed) plus pinned
extras, priced from exchange klines.

## Tests

```bash
pip install -r requirements-dev.txt      # requirements.txt + pytest, PyYAML, xdist, pyflakes
python -m pytest -n 4 --dist loadfile    # the Python suites (no test reaches the network)
for f in test/*.test.js; do node "$f"; done   # the JS suites, no framework
```

Both run on every push (`.github/workflows/test.yml`), plus a Playwright e2e pass,
a Lighthouse budget tripwire and a screenshot-diff gate at desktop and 390px.

Two house rules the suites enforce rather than document:

- **Tests read the shipped file.** They slice real functions out of `public/js/*.js`
  and run them, because a re-typed fixture drifts in step with the bug.
- **Any edit to a `public/js` or `public/css` asset bumps its `?v=` in every HTML
  page that loads it.** `/js/*` and `/css/*` are served immutable for a year, so a
  missed bump pins the old file for anyone who already visited. A skew across
  pages is a bug in its own right and `test/cache.test.js` fails on it.

## Layout

```
scanner/              Python engine
  config.py           markets, thresholds, weights, grade cut-offs  <- tune here
  universe.py         ticker lists          data.py      the one fetch path (yfinance + exchange klines)
  indicators.py       EMA / RSI / ATR / SuperTrend / pivots
  vivek.py            the VIVEK lens        spec.py      the Specs lens
  scan.py             per-market orchestration      run.py   CLI entry point
  ignition/ momentum/ the report-only lenses
  broker/             the paper bot, loss guards, kill switch, alert router
phasemap/             the PhaseMap lens (own runner, own tests)
functions/api/        Cloudflare Pages Functions — health, heartbeat, scan, close, digest trigger, price
public/               the deployed static site (this folder IS the deploy)
journal/              the books — vivek_bot_book.<market>.json is the track record
data/                 sector map (feeds the sector cap), edge ledgers, research outputs
tests/ · test/        Python suites · JS suites
docs/                 decision pack, REFINE200 ledger, CLAUDE.md history, archived notes
.github/workflows/    25 workflows; OPERATIONS.md has the schedule
```

## Operating it

[`OPERATIONS.md`](OPERATIONS.md) is the runbook (including "Who triggers what")
and [`HEALTHCHECK.md`](HEALTHCHECK.md) is the 60-second daily check.
[`CLAUDE.md`](CLAUDE.md) carries the working rules for anyone — human or agent —
changing this repo.

GitHub's cron is best-effort, so the real clock is a set of free cron-job.org
jobs that call two endpoints:

- **`/api/health`** — the alarm. GitHub-independent; an external monitor watches it.
- **`/api/heartbeat`** — the healer. Dispatches a scan when a market's data goes
  stale, behind a per-market floor, a heal window and a daily cap.

## Caveats, stated plainly

- **Stock data is yfinance**: ~15 minutes delayed, no delisted history. Fine for
  operating, not fine for publishable backtest numbers.
- **Every backtest here is survivor-biased** — the universe is *today's* listed
  names. Use the numbers to compare cohorts, never as a return forecast.
- **The site is public.** The manual scan and close endpoints accept same-origin
  JSON only and are rate-limited, but are not authenticated; Cloudflare Access is
  the real fix and is pending owner action.
