# Googy Boys Scanner — ASX & NASDAQ

A daily **Fibonacci‑EMA setup scanner**, rebuilt from
[asx-scanner-app.web.app](https://asx-scanner-app.web.app/) and extended with a second market.
It reviews a universe of stocks each day, finds those in a healthy uptrend that have paused and
pulled back to a key moving average, grades them **A+ / A / B / C**, computes **Entry / Stop /
Target** and a **risk‑reward** read, and publishes everything to a dense dark **market‑terminal**
web page — a macro **PULSE** bar, full price columns, a watchlist, and an **ASX ⇄ NASDAQ** toggle.

> General information only — not financial advice. Markets carry risk.

## How it works (the method)

- Seven EMAs on the Fibonacci ladder: **8 · 13 · 21 · 34 · 55 · 89 · 144** (daily close).
- Six **signal chips**, each worth points (out of 13): full bullish alignment (3), core Fib
  pullback (3), strong Fib confluence (3), EMA compression (2), weekly bullish (1), volume (1).
- **Grade = the sum of those points** (A+ ≥ 10, A ≥ 8, B ≥ 5, C ≥ 3 — all tunable in `config.py`).
- **Entry** = the pullback EMA, **Stop** = below the recent swing low, **Target** = nearest
  resistance above (or a 2R fallback); **P2** = an ATR SuperTrend trailing stop. Poor reward‑to‑risk
  is flagged **LOW R:R** rather than demoted.
- **PULSE** bar: macro context (gold, silver, brent, WTI, nat‑gas, tech & biotech indices, 10Y
  yields, AUD/USD) with 1‑day and 5‑day moves.
- **Liquidity filter** removes thin names; the most liquid are tagged **LIQUID**.
- **Watchlist** — star any setup (saved in your browser) and view it under the **Watch** tab.

All weights and thresholds live in [`scanner/config.py`](scanner/config.py).

## Two scanners

- **Pullbacks** (the Fib-EMA scan above) — continuation setups in an *existing* uptrend.
- **Reversals** — a second scanner for the *start* of a new uptrend: a beaten-down/basing stock
  reclaiming and crossing up through its short SMAs (9 over 26), coming off a base, with volume and
  RSI turning up. Uses SMA 9/26/43/200 + RSI 14 + Vol 20; scored out of 14 (see `scanner/reversal.py`
  and the `REV_*` settings in `config.py`). Switch with the **Pullbacks / Reversals** toggle in the
  header. Both scans run from one daily download.

## On the website

- **Click a row** to expand a detail dropdown — plain-English analysis, the swing/EMA level
  breakdown, trailing stop, volume, EMA alignment ladder, and market structure (HH/HL).
- **Click a ticker** to open a full **candlestick chart** (`chart.html`) with EMA 34/55/89, the
  SuperTrend line, marked price levels (high / resistance / EMA-watch / stop / leg-low / low),
  volume, and an *Open in TradingView* link.
- **Journal** page (`journal.html`) — the forward-test track record: stats, equity curve, open
  positions and closed trades.

## Project layout

```
scanner/            Python engine
  config.py         markets, thresholds, point weights, grade cut-offs  <- tune here
  universe.py       loads the ticker lists
  data.py           batched Yahoo Finance (yfinance) downloads
  indicators.py     EMA / ATR / SuperTrend / pivots
  signals.py        the 5 chips + scoring + grading
  levels.py         entry / stop / target / R:R
  scan.py           orchestration per market
  output.py         writes public/data/<market>.json
  run.py            CLI entry point
data_universe/      asx_tickers.csv, nasdaq_tickers.csv (edit to grow/trim the universe)
public/             the static site (this folder is what gets deployed)
  index.html  about.html  css/  js/  data/<market>.json
.github/workflows/  scan.yml — scheduled scan + publish
```

## Easiest: double-click

Two batch files are included for non-technical use:

- **`Start Fib Scanner.bat`** — serves the site and opens it at `http://localhost:8765`.
- **`Refresh Data.bat`** — re-runs the scanner so the results are up to date.

## Run it from a terminal

```bash
# 1. install dependencies (Python 3.11+)
pip install -r requirements.txt

# 2. run the scan (writes public/data/asx.json and public/data/nasdaq.json)
python -m scanner.run                 # both markets (full ASX directory + NASDAQ)
python -m scanner.run --market asx    # one market
python -m scanner.run --curated       # use the smaller bundled ASX list (much faster)
python -m scanner.run --limit 40      # quick test on a small slice

# 3. serve the site (fetch() needs http://, not file://)
python -m http.server 8765 --directory public
# then open http://localhost:8765
```

> The default ASX scan covers the **entire ASX-listed directory (~2,000 names)** pulled live from
> the ASX, so it takes a few minutes. NASDAQ uses a curated large-cap list. Use `--curated` (ASX
> top names) or `--limit N` for a fast run.

## Backtest & paper-trade journal

```bash
# Quick-sanity backtest — replays the same signals over history and reports
# results in R multiples (win rate, expectancy, profit factor, drawdown) by grade.
python -m scanner.backtest                # curated liquid names, both markets
python -m scanner.backtest --market asx --limit 15

# Bigger backtest — all curated liquid names, or the full ASX directory.
python -m scanner.backtest --limit 200      # all liquid names, both markets
python -m scanner.backtest --market asx --full --limit 150

# Paper-trade journal (forward test) — opens a paper position for each new A+/A
# setup and walks open positions forward (stop/target/trail) into a track record.
python -m scanner.journal                  # update from the latest scans
python -m scanner.run --journal            # scan AND update the journal in one go

# Email alerts of new A+/A setups (writes a preview; emails only if SMTP is set).
python -m scanner.alerts                    # new since last run  (--all for every current A+/A)
python -m scanner.run --journal --alert     # scan, journal, and alert together
```

Set `GBS_SMTP_HOST`, `GBS_SMTP_PORT`, `GBS_SMTP_USER`, `GBS_SMTP_PASS` and `GBS_ALERT_TO` to enable
email; otherwise the digest is written to `public/data/alert_preview.html` so you can preview it.

The journal is stored in `journal/journal.json` (full history) and mirrored to
`public/data/journal.json`. It builds a **bias-free** record over time — the trustworthy
counterpart to the backtest.

> The backtest universe is *today's* listed names, so its numbers are **optimistic**
> (survivorship bias). Use them to compare grades and tune `config.py`, not as a return
> forecast. No orders are ever placed — execution stays manual.

## Customising

- **Universe** — the ASX scan uses the **full live ASX directory** by default; NASDAQ uses
  `data_universe/nasdaq_tickers.csv`. Edit that CSV (`symbol,name`) to grow/trim NASDAQ, or edit
  `data_universe/asx_tickers.csv` (used by `--curated`). The liquidity filter prunes thin names, so
  a generous list is fine. To expand NASDAQ to its full directory too, switch its loader to
  `_fetch_nasdaq_listed` in `scanner/universe.py`.
- **Strictness / grades** — edit `POINTS`, `GRADE_CUTOFFS` and the signal thresholds in
  `scanner/config.py`.
- **Add another market** — add an entry to `MARKETS` in `config.py`, drop in a
  `data_universe/<key>_tickers.csv`, and add a button to the `.market-switch` in
  `public/index.html`.

## Automate (GitHub Actions + GitHub Pages)

1. Push this folder to a GitHub repo.
2. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. `.github/workflows/scan.yml` then runs after each market close, commits the fresh JSON, and
   redeploys the site. You can also trigger it manually from the **Actions** tab
   (Run workflow / `workflow_dispatch`).

### Alternative: Firebase Hosting (like the original `.web.app`)

A `firebase.json` is included (serves the `public/` folder). To deploy:

```bash
npm install -g firebase-tools
firebase login
firebase init hosting      # choose existing/new project; keep "public" as the public dir
firebase deploy
```

Run the scanner (locally or in CI) before each deploy so `public/data/*.json` is current, or keep
the GitHub Action as the scheduler and use Firebase only for hosting.

## Notes

- Data is from Yahoo Finance via `yfinance` (free, no API key). It's unofficial but reliable for a
  once‑daily scan; failed/delisted tickers are skipped automatically.
- This is a clean reimplementation of the original app's described methodology — not a copy of its
  private source. Point weights and cut‑offs are a faithful reconstruction and easy to tune.
