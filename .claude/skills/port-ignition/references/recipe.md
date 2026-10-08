# The port recipe (file by file)

Built from the two real ports: the ASX (`git show aad51559`) and NASDAQ
(`git show 6898d686`, review fixes `git show f1e3e04f`). Read the NASDAQ
diff when a step is unclear: it is the newest template. Commit `6898d686`
also contains the mini-chart feature (`thumbs.py`, `*_charts.json`,
`chartSVG`). That part is NOT port work. A port only inherits the charts:
the new workflow stages `<m>_charts.json`, and publish-integrity gets a row
for it.

Line numbers drift, so find things by symbol: `grep -n SYMBOL file`.
`<m>` = market key (`nyse`), `<M>` = label (`NYSE`).

Contents: Part 1 config · Part 2 lens code · Part 3 backstop gate ·
Part 4 workflow + kick · Part 5 frontend · Part 6 tests · Part 7 CLAUDE.md ·
Verify locally · First replay

## Part 1: `scanner/config.py`

Add a paragraph to the IGNITION block like the ASX and NASDAQ ones: the
values, each with its reason, pre-registered on the port date. How to choose
each value is in `settings.md`.

1. `IGNITION_MARKETS`: append `<m>`. Crypto must stay first, because the
   fences test reads `[0]` as the grid centre.
2. `IGNITION_BARS_PER_YEAR[<m>]`: trading days a year. This only rescales
   the CALENDAR windows (`engine.bars()`). Chart windows (SMA 9/26/43/200,
   ATR 14, 20-bar volume, the 60-bar base, lookback, rearm, keep, the 9-SMA
   trail) stay in bars on every market.
3. `IGNITION_MAX_DATA_AGE_DAYS_BY_MARKET[<m>]`.
4. `IGNITION_MIN_BASE_TURNOVER[<m>]` and `IGNITION_MIN_TRIGGER_TURNOVER[<m>]`,
   in the market's own money, as Close x Volume. Set BOTH. The fallback
   makes the trigger 1x the floor.
5. `IGNITION_BT_COST_PCT_BY_MARKET[<m>]`.
6. `IGNITION_BT_CASES_BY_MARKET[<m>]` and
   `IGNITION_BT_DESIGN_CASES_BY_MARKET[<m>]`. Use `()` and `{}` unless a
   specific chart prompted the port. If one did, it is a design case and
   never scored (the ASX had DTR). Set them explicitly even when empty, or
   crypto's QNT falls through.
7. `IGNITION_BT_REGISTERED_DATE_BY_MARKET[<m>]`: the port date. The forward
   bucket starts here.
8. `IGNITION_REGIME_INDEX[<m>]`: (Yahoo ticker, label).
9. `IGNITION_BAR_FINAL[<m>]`: (tz, hour, minute) when the free feed's daily
   bar is final. Derive it, never retype it. It must be defined after
   `MARKETS`, `ALERT_RETURNS_BAR_FINAL` and `MORNING_PLAYS_SLOT_GATE`.
10. `IGNITION_FORMING_UNTIL_BAR_FINAL`: add `<m>` for any stock market.
    Leave the ASX as it is; changing it moves pinned ASX tests.
11. Any NEW `*_BY_MARKET` dict you introduce must also join `PER_MARKET` in
    `tests/test_ignition_fences.py`.

## Part 2: lens code (`scanner/ignition/`)

These are already generic, so read them but expect to edit only docstrings:

- `engine.py`: `mkt()`, `bars()`, `Params.from_config`.
- `run.py`: regime line, `max_age_days`, `data_note`, `--market` choices
  from `IGNITION_MARKETS`, cache key `ignition-<m>`.
- `backtest.py`: `prepare` drops the index and never-liquid names for every
  non-crypto market, and `design_cases` handles `{}`.
- `mcap.py`: uses bare or suffixed `yf` symbols and `<m>:` keys in the
  shared cache.

Text you MUST add in `backtest.py`:

- `COST_WHY[<m>]`: the why-sentence printed in the cost caveat. A missing
  key prints a bland default.
- `UNIVERSE_WHY[<m>]`: needed whenever the market label overstates what is
  really replayed. NASDAQ's says "NASDAQ Global Select (in good standing)";
  NYSE from nasdaqtrader means NYSE-listed common stock only.

Keep every existing market's caveat byte-identical.

## Part 3: `scripts/ignition_due.py`

It is generic and stdlib-only, and reads `config.IGNITION_BAR_FINAL`. Add a
docstring line for the market. It assumes a Mon–Fri week and ignores
holidays; on a holiday it fails open and runs a spare re-screen.

## Part 4: `.github/workflows/ignition_<m>.yml` + `.github/ignition-<m>-kick`

1. Copy `ignition_nasdaq.yml`, not the ASX twin: NASDAQ's has the
   late-intraday cutoff. Change `name: "Ignition scan (<M>)"` and the step
   names "Screen <M>" / "Backtest <M>". Every `run:` block except the `due`
   step must equal `ignition.yml`'s after replacing `--market crypto`,
   `public/data/ignition/crypto` and `ignition crypto`. That is pinned, and
   comments inside a `run: |` block count.
2. Crons (UTC only; see settings.md "Crons"): a primary past bar-final
   under both DST offsets, two backstops on the close's UTC weekday, and
   three intraday runs inside the session and at least 60 minutes before
   the close in both regimes. Use minutes no other Ignition twin uses, and
   avoid :00 and :30.
3. The `due` step:
   - Skip the intraday cron string once local time is at or past close − 30
     (`TZ=<tz> date +%H%M`).
   - The backstop cron string runs `python3 scripts/ignition_due.py <m>` on
     `origin/<ref>:public/data/ignition/<m>.json`.
   - Every other trigger is due.
4. Concurrency `group: ignition-<m>-${{ github.ref_name }}` with
   `cancel-in-progress: false`; cache key `ignition-<m>-frames-${{ github.run_id }}`
   with restore-keys `ignition-<m>-frames-`; `timeout-minutes: 300`;
   `permissions: contents: write`; push paths `.github/ignition-<m>-kick`;
   dispatch inputs `backtest` and `dry_run`. PATHS cover `<m>.json`,
   `<m>_charts.json` and `<m>_backtest.json`, with one `git add` and one
   `assert_staged` per path (inherited by the copy). No WATCHDOG entry, and
   never join the `scan` mutex.
5. Kick file, 4 lines like the others: a comment, then
   `kick: <date> first <M> replay (<windows, floors, cost>)`.
6. Update only the header comments of `ignition.yml` and the sibling twins
   that list the twins.

## Part 5: frontend

1. `public/js/ignition.js`:
   - `IGNITION_MARKETS` must equal config (`tests/test_ignition_frontend.py`).
   - `WF_NAME[<m>]` is exactly the workflow `name:`.
   - `CAP_CCY[<m>]`: `"US$"`, `"C$"`, `"£"`…
   - The tooltips that list markets or currencies: `SOURCE_TIP.yahoo`, the
     `COIL_COLS` cap column and the header comment.
   - `BAR_24_7` stays `["crypto"]`.
2. Bump `js/ignition.js?v=` (and `css/ignition.css?v=` if touched) in EVERY
   page that loads them: today `public/index.html`, plus `public/ignition.html`
   once it exists. Then restamp `public/version.json`:
   `python3 -m pytest tests/test_version_stamp.py` prints the exact value.
3. A NEW market has no deck. See `new-market.md` for the Ignition page and
   the chart.js changes.

## Part 6: tests

1. ADD `tests/test_ignition_<m>.py`, mirroring `tests/test_ignition_nasdaq.py`
   section by section:
   - fixture (`asx_frame` via importlib), windows, floors and turnover;
   - screen payload and regime, the age limit, forming until bar-final,
     freshness;
   - prefilter changes no trade, design-case behaviour, trade cost, hold
     and regime;
   - backtest payload, including caveats with no foreign words (ASX, coins,
     "none prompted");
   - frozen caveats for the existing markets: freeze NASDAQ's too;
   - workflow triggers, group, cache and timeout; crons vs session in BOTH
     DST regimes (2026-07-15 and 2026-12-15);
   - the `due` gate executed in bash at frozen instants;
   - the backstop gate table.
2. EDIT these:
   - `tests/test_ignition_asx.py`: the `BARS_PER_YEAR` and `IGNITION_MARKETS`
     equalities, and `TWINS[<m>] = (file, <M>)`. The parametrised step-shape
     and run-block pins then cover the new twin.
   - `tests/test_ignition_nasdaq.py`: the same tuples, and the `"nyse"`
     unknown-market row if porting NYSE.
   - `tests/test_ignition_fences.py`: the market tuple and its message, the
     write-path market loop, and `PER_MARKET` for any new dict.
   - `tests/test_ignition_workflow.py`: the `TWINS` tuple, and
     `ignition_<m>|ignition-<m>` in the removability regex.
   - `tests/test_ignition.py`: the "refuses a market" sentinel; re-point it
     to a key in neither `MARKETS` nor `IGNITION_MARKETS`.
   - `tests/test_ignition_mcap.py`: a `<m>_download` fixture plus tests for
     own cache keys, Yahoo-first, and a CLI that writes exactly 2 paths.
   - `tests/test_publish_integrity.py`: add
     `("public/data/ignition/<m>_charts.json", _COMPACT, True)` and
     `("public/data/ignition/<m>.json", {}, True)`. Both skip until the
     first run.
   - `test/ignition.test.js`:
     - add `REAL_<M>`, the market arrays and `isMarket`;
     - the URLs test, plus session-staleness, badge, regime and tooltip
       tests mirroring NASDAQ's;
     - the `fmtCap` unknown-market line and the real-payload loops;
     - re-point every `"nyse"` sentinel if porting NYSE.
3. New `tests/*.py` files are collected automatically. A new `test/*.test.js`
   FILE needs its own step in `.github/workflows/test.yml`, and a test
   enforces that. Prefer extending `test/ignition.test.js`.

## Part 7: `CLAUDE.md`

- The lens summary near the top and the repository layout line.
- The workflow table: an `ignition_<m>.yml` row (crons, gate, cutoff,
  group, cache, timeout, files, pins).
- The `assert_staged` caller list.
- The IGNITION section: the MINI CHARTS line that lists the workflows, plus
  a new "THE <M> PORT (date)" paragraph giving each value with its reason,
  the universe scope and the first replay's verdict.

## Verify locally

```bash
python3 -m pytest tests/test_ignition_<m>.py tests/test_ignition_asx.py tests/test_ignition_nasdaq.py tests/test_ignition.py tests/test_ignition_fences.py tests/test_ignition_workflow.py tests/test_ignition_frontend.py tests/test_ignition_mcap.py tests/test_ignition_thumbs.py tests/test_publish_integrity.py tests/test_version_stamp.py tests/test_workflow_hardening.py tests/test_workflow_mutex.py
node test/ignition.test.js
python3 scripts/ignition_due.py <m> "<a generated_at stamp>" --now <ISO>
python3 -m pytest                      # full gate, ~6 min: timeout 600000; no extra -q (pytest.ini adds it)
for f in test/*.test.js; do node "$f" >/dev/null 2>&1 || echo "FAIL $f"; done
NODE_PATH=/opt/node22/lib/node_modules PW_CHROMIUM=/opt/pw-browsers/chromium node test/e2e/smoke.e2e.js
```

For a new market, also run the suites `new-market.md` names.

## First replay

1. Push with the kick file in the commit. The branch push runs the screen
   AND the replay and commits the three files back to the branch.
2. `git pull --rebase`, then re-run `node test/ignition.test.js`. `REAL_<M>`
   now exists, so the real-data render tests run. Re-run
   `test_publish_integrity` too.
3. Read it:
   ```bash
   python3 -c "import json; from scanner.ignition import backtest as bt; print('\n'.join(bt.summary_lines(json.load(open('public/data/ignition/<m>_backtest.json')))))"
   ```
4. The decision statistic is `versus.random_timing`
   (`diff_r`, `diff_ci90`, `p_diff_le_0`). Read it beside the out-of-sample
   split, `top5_share_pct` / `exp_r_ex_top5`, `cost_stress` and the grid.
   For reference:
   - crypto: +1.15R, CI −0.06..+2.59, P 0.062 (borderline, fat-tailed);
   - ASX: +0.42R, CI +0.12..+0.73, P 0.009;
   - NASDAQ: +0.06R, CI −0.07..+0.19, P 0.24 (no edge shown).
5. Write the verdict into CLAUDE.md's port paragraph, the PR and the owner
   summary. The lens ships either way. Trading it needs the forward bucket
   to beat random timing, and the owner's ruling.
