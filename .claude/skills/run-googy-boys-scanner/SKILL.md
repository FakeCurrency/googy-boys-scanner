---
name: run-googy-boys-scanner
description: Run, start, drive, test and screenshot the Vivek 5.0 scanner site (googy-boys-scanner) locally - serve public/ with serve.py, click through the deck / chart / journal in headless Chromium with the committed driver, stub the price API so stock charts draw, and run the scan gate, pytest and JS suites directly.
---

# Run Vivek 5.0 (googy-boys-scanner)

The "app" is a static site (`public/`, Cloudflare Pages in production) that
renders scan JSON the GitHub Actions jobs commit to `public/data/`. Locally
you serve `public/` with `serve.py` and drive it with
`.claude/skills/run-googy-boys-scanner/driver.js`: a Playwright script that
starts its own server, reads commands from stdin (one per line), and writes
screenshots to `/tmp/vivek-shots/`. The Python scanner is batch code with no
UI; you exercise it through its CLIs and tests (see Direct invocation).

All paths are relative to the repo root.

## Prerequisites

Nothing to install in the Claude Code cloud container. These were already
there and are what the driver uses:

- Node 22 with a global `playwright` (`/opt/node22/lib/node_modules/playwright`;
  the driver falls back to `npm root -g` when `require("playwright")` fails)
- Chromium at `/opt/pw-browsers/chromium` (the driver uses it automatically;
  never run `npx playwright install`)
- Python 3.11, `lsof`

## Setup

```bash
python3 -m pip install -q -r requirements.txt
```

Only needed for Python tests and scanner code. The site itself needs no build.

## Run (agent path): drive the site

```bash
node .claude/skills/run-googy-boys-scanner/driver.js <<'CMDS'
nav /index.html
wait .row-wrap
eval document.getElementById("scan-title").textContent
text #deck-pills .fpill
click #deck-pills [data-pill="confl"]
sleep 400
count .row-wrap
shot deck
errors
CMDS
```

Then look at the picture with the Read tool: `/tmp/vivek-shots/deck.png`.

Commands (`#` starts a comment; the first failing command prints `FAIL`,
stops the run and exits 1):

| command | does |
|---|---|
| `nav <path>` | go to `http://localhost:$PORT<path>` |
| `wait <selector>` | wait up to 30s until it is VISIBLE |
| `click <selector>` / `fill <selector> <text>` / `press <key>` | input |
| `eval <js>` / `text <selector>` / `count <selector>` | print a value |
| `viewport <w> <h>` | fresh page at that size (default 1500x950) |
| `scroll <selector>` | scroll the first match into view |
| `shot <name>` | viewport PNG to `$SHOTS` (default `/tmp/vivek-shots`) |
| `fullshot <name>` | whole-page PNG |
| `sleep <ms>` | wait |
| `errors` | page errors, console errors and HTTP >= 400 seen so far |

Flags: `--fixtures` serves `test/e2e/fixtures/data` as `/data/` (the
deterministic set the e2e gates photograph); `--stub-price` answers
`/api/price` (daily) and `/api/quote` from the committed PhaseMap chart files
so stock charts draw. Env: `PORT` (default 8765), `SHOTS`, `PW_CHROMIUM`.

A chart, switched to weekly candles:

```bash
node .claude/skills/run-googy-boys-scanner/driver.js --stub-price <<'CMDS'
nav /chart.html?s=PME&m=asx
wait .tf-btn[data-tf="1W"]
click .tf-btn[data-tf="1W"]
sleep 1000
text .tf-btn.is-active
shot chart-pme-weekly
CMDS
```

Switching market and opening a row's plan ladder:

```bash
node .claude/skills/run-googy-boys-scanner/driver.js <<'CMDS'
nav /index.html
wait .row-wrap
click .market-btn[data-market="crypto"]
sleep 1500
eval document.querySelector(".market-btn.is-active").textContent
click .row-wrap .row-expand
wait .vk-ladder-h .vk-cell
text .vk-ladder-h .vk-cell
shot crypto-expanded
CMDS
```

Phone width on fixture data, journal first:

```bash
node .claude/skills/run-googy-boys-scanner/driver.js --fixtures <<'CMDS'
viewport 390 844
nav /journal.html
wait #jr-pnl
text #jr-pnl-total
count table tbody tr
shot journal-390-top
nav /index.html
wait .row-wrap
click .row-wrap .row-expand
wait .vk-ladder-h .vk-cell
scroll .vk-ladder-h
shot deck-390-expanded
CMDS
```

Pages: `index.html` (the deck), `chart.html?s=<SYM>&m=<asx|nasdaq|crypto>`,
`journal.html`, `recommendations.html`, `phasemap.html`, `specs.html`,
`momentum.html`, `alerts.html`, `sectors.html`, `system.html`.

## Run (human path)

```bash
python3 serve.py 8765 public
```

Open http://localhost:8765/ and Ctrl-C to stop. It sends `no-store`, so a
reload picks up JS/CSS edits. From an agent, start it in the background,
poll with `curl -s -o /dev/null http://localhost:8765/index.html`, and stop it with:

```bash
lsof -ti:8765 -sTCP:LISTEN | xargs -r kill
```

## Direct invocation

Most PRs touch scanner/workflow logic, not pixels. Call it directly.

The scan gate (which markets a scan.yml run scans), at any instant:

```bash
python3 scripts/scan_gate.py --event schedule --schedule "7 0-5 * * 1-5" --now 2026-10-08T01:07:00+00:00
python3 scripts/scan_gate.py --event workflow_dispatch --reason heartbeat --market all --now 2026-10-08T21:30:00+00:00
```

One Python test file, one JS suite:

```bash
python3 -m pytest tests/test_scan_windows.py
node test/heartbeat.test.js
```

## Test

```bash
python3 -m pytest -x
for f in test/*.test.js; do node "$f" > /dev/null 2>&1 || echo "FAIL $f"; done
NODE_PATH=/opt/node22/lib/node_modules PW_CHROMIUM=/opt/pw-browsers/chromium node test/e2e/smoke.e2e.js
```

The e2e smoke test serves `public/` itself on port 8943 and ends with
`ALL E2E CHECKS PASSED`.

## Gotchas

- **`/api/*` does not exist locally.** Those are Cloudflare Pages Functions
  and `serve.py` only serves files, so every page logs `404 /api/health` and
  the top-bar status lamp reads **DOWN**. That is expected; do not chase it.
- **A stock chart with a live VIVEK row shows "Chart unavailable" without
  `--stub-price`.** chart.js fetches its candles from `/api/price` (Yahoo via
  the Function). PhaseMap-only names (e.g. BTC) draw anyway from
  `data/phasemap/charts/<m>/<SYM>.json`. This container cannot reach Yahoo
  or Binance either (proxy CONNECT 403), so the stub is the only way. It
  serves ~220 daily bars: long SMAs barely draw, there is no intraday, and a
  name without a chart file (e.g. BHP) still dead-ends. Use names with one,
  e.g. `ls public/data/phasemap/charts/asx | head`.
- **`wait` means visible.** `#stalled-strip` exists on the journal but is
  `hidden` when no position is stale (always, on fixtures), so waiting on it
  times out. Wait on `#jr-pnl` for the journal, `.row-wrap` for the deck.
- **The deck lists one grade tier at a time** (A+ by default), so
  `count .row-wrap` is that tier's rows: the ⨂ Multi-lens pill read 25
  while the filtered A+ list held 8. Do not assert one against the other.
- **Live data moves.** `public/data/` is whatever the last scan committed
  (row counts, "Last scanned: 50m ago"). Use `--fixtures` when you want the
  same page twice; it reads "75d ago" and 404s the files the fixture set
  lacks (`*_prices.json`, `phasemap/asx/latest.json`, ...), which is normal.
- **Use `shot`, not `fullshot`, for anything you need to read.** The deck at
  390px is ~8,000px tall and the journal ~5,000px at desktop width; a whole-page image is
  shrunk until the text is a blur. Scroll to what matters, then `shot`.
- **The first-visit tour scrim swallows clicks.** The driver pre-sets
  `localStorage["gbs:onboarded"]="1"` and blocks the service worker, as the
  e2e tests do. Do the same in any new Playwright script.
- **`python3 -m pytest -q` prints no summary.** `pytest.ini` already adds
  `-q`; a second one hides the "N passed" line. Run it without `-q`.
- **Leftover `.claude/worktrees/` break the full pytest run**
  (`tests/test_scanner_untouched_by_chart_depth.py` walks the whole tree).
  Remove them first: `git worktree remove --force <path>; git worktree prune`.

## Troubleshooting

- `port 8765 already in use -- stop it or set PORT=`: a `serve.py` is still
  running. Kill it with the `lsof` line above, or prefix `PORT=8766`.
- `FAIL wait <selector>` / `Timeout 30000ms exceeded`: the element never
  became visible. Take a `shot` right after `nav` to see what rendered, or
  `eval document.body.innerText.slice(0, 300)`.
- `page.evaluate: TypeError: Cannot read properties of null` on a chart:
  the chart failed to load and "Chart unavailable" replaced the whole page,
  `#tf-toggle` included. Add `--stub-price` (see Gotchas). Once a chart
  loads, its timeframe buttons are `.tf-btn[data-tf="1D"|"3D"|"1W"]`.
- `curl: (56) CONNECT tunnel failed, response 403`: the container's proxy
  refuses that host (Yahoo, Binance). Use the committed data or the stub.
