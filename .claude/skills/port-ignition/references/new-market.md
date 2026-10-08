# A NEW market (not in `config.MARKETS`)

Do this before the recipe. It covers six things: the stock list (with the
stop rule), an Ignition-only registry so nothing else enrols the market, a
page to show it on, chart links that draw the right instrument, the tests
that pin the fence, and the extra suites to run. None of this existed for
the ASX or NASDAQ ports. It was researched on 2026-10-08 and
prototype-checked, but the first real one (likely NYSE) will meet things
nobody has seen. Record them back in this file.

Contents: 1 stock list + stop rule · 2 Ignition-only registry · 3 the
Ignition page · 4 chart links · 5 fence tests · 6 extra suites

## 1. The stock list, and when to stop

Ship nothing unless ONE source passes all of these:

1. It is published by the exchange operator or its official reference-data
   arm (nasdaqtrader.com for every US listing, TMX, LSEG, HKEX).
   Index-constituent lists (Wikipedia, FTSE 100, S&P/TSX 60) do not count:
   they are survivor- and size-biased, the opposite of where coils live.
2. It is free: no key, login, licence click-through or paid tier. EODHD and
   Norgate are an open owner decision, so they are out.
3. It is one bulk machine-readable file for the whole board (TXT, CSV, JSON;
   XLSX only if parsed with the stdlib or an exact pin), not a paged
   screener or a JS app.
4. Code can build its URL: stable, or derived from the date.
5. It carries the symbol, the name, and a security-type or ETF field (or
   names clean enough for the name filter).
6. It is proven from a GitHub runner. This container cannot reach any of
   these hosts (proxy 403), so a failure here proves nothing. Prove it with
   `.github/workflows/data_depth.yml` (READ-ONLY; takes a `symbols` input)
   for the Yahoo side. For the list itself, use the first kick run, or a
   short dry-run dispatch whose log shows the fetched count. A 403, 451,
   WAF challenge or HTML page is a stop.
7. The data side passes too: about 80% of a sample, plus the regime index,
   return 400+ daily bars on Yahoo. Otherwise stop, on data rather than on
   the list.

If nothing passes, stop and tell the owner in plain words what you tried
and why each failed.

Known candidates (from memory, re-prove on a runner):

| market | list | Yahoo ticker | notes |
|---|---|---|---|
| NYSE (+ American, Arca) | `https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt` (pipe-delimited; `Exchange` N = NYSE, A = NYSE American, P = Arca; `ETF` Y/N; `Test Issue` Y/N; file ends with a `File Creation Time` line) | bare; class dots become dashes (`BRK.B` → `BRK-B`) | GO. The same host already serves NASDAQ's list (`universe._fetch_nasdaq_listed`). Drop ETFs, test issues, warrants, rights, units and preferreds; P (Arca) is almost all ETFs |
| TSX / TSXV | TMX company directory JSON (`https://www.tsx.com/json/company-directory/search/tsx/%5E*`, `.../tsxv/%5E*`) | `.TO` / `.V`; `RCI.B` → `RCI-B.TO`, `REI.UN` → `REI-UN.TO` | GO only if the JSON still answers from a runner. Drop ETFs, and on TSXV `.P` shells and `.H` NEX names. C$. Regime `^GSPTSE` |
| LSE / AIM | no stable bulk file known | `.L` | likely STOP. Even with a list it is quoted in pence (GBp): floors x100, and Yahoo's 100x unit glitches |
| HKEX | `ListOfSecurities.xlsx` | `0700.HK` (4 digits) | needs an XLSX parser. Data-age 8–10 for Lunar New Year |

The code shape (model it on `universe._fetch_nasdaq_listed` and its
`load_universe` branch):

- `_fetch_<m>_listed()` in `scanner/universe.py`. It must live there: the
  lens may only import the modules the fences test allows.
- An explicit `_CACHE_MIN[<m>]` (the default is 400).
- NO bundled `data_universe/<m>_tickers.csv`, and never a list typed from
  memory. A hand-made list is a few hundred large caps, which is the
  opposite of where coils live, and it would quietly stand in for the real
  board. On a list outage `load_universe` falls back to the last-good cache
  (`data/universe_cache/<m>.json`); with no cache it returns `[]`, and
  `run.py` exits 3 and keeps the last published file. That is the honest
  outcome. Nothing commits the cache for an Ignition-only market (scan.yml
  does that for the VIVEK markets), so if you want it to survive between
  runs, add `data/universe_cache/<m>.json` to the new workflow's
  actions/cache `path`. Never commit it from the lens workflow.
- Filter by the file's own symbology first, and by name words only as a
  second fence. In `otherlisted.txt` the `NASDAQ Symbol` column marks
  preferreds `-`, warrants `+`, units `=`, rights `^`, when-issued `#` and
  called `*`; the ACT column uses `$`, `.WS`, `.U`, `.R`. A common stock
  is a 1–5 letter root with an optional one-letter class (`BRK.B`). Keep
  "Common Units" (MLP equity) and ADRs. Test the name fence against real
  operating companies so it drops no company (the `is_product` lesson in
  CLAUDE.md: bare "Depositary Shares" is a real company's ADR).
- Tests: feed a canned list file through the parser, never the network
  (`tests/conftest.py` refuses venues). Cover the outage path too: a failed
  fetch with no cache gives `[]` and an exit 3, not a stand-in list.

## 2. The Ignition-only registry (never `config.MARKETS`)

`config.MARKETS` feeds the VIVEK scan, the paper bot, the kill switch, the
watchdog and the backtest. A new key there enrols the market in all of
them, now and in any future loop. Register it beside them instead:

```python
# scanner/config.py, straight after MARKETS (it needs MarketConfig):
# IGNITION-ONLY MARKETS: screened by scanner/ignition/ and NOTHING else. NOT in
# MARKETS on purpose - MARKETS is the VIVEK scan + paper bot registry and its
# iterators (run.py --market all, vivek_run, kill_switch, watchdog,
# vivek_backtest --market all) would enrol it. Moving a key into MARKETS is an
# owner decision (VIVEK + the bot on it), not a port step.
IGNITION_ONLY_MARKETS = {
    "nyse": MarketConfig(key="nyse", label="NYSE", suffix="", currency="USD",
                         currency_symbol="$", timezone="America/New_York",
                         liquidity_min=1_000_000),
}
# (open_h, open_m, close_h, close_m) local - VIVEK_JOURNAL_SESSION's shape, kept
# apart because app.js mirrors that table and a key there means a VIVEK deck.
IGNITION_ONLY_SESSIONS = {"nyse": (9, 30, 16, 0)}
```

Then route the lens through one lookup:

- `engine.py` gets `meta(market)`:
  `config.MARKETS.get(market) or config.IGNITION_ONLY_MARKETS.get(market)`.
  Use it everywhere the lens read `config.MARKETS[...]` (turnover floor,
  `volume_is_usd`). In `backtest.py` and `run.py`, call `E.meta(market)`.
- `run.py` gets `session(market)`: `IGNITION_ONLY_SESSIONS` first, then
  `VIVEK_JOURNAL_SESSION`. It belongs in run.py, not the engine: the fences
  test forbids the engine reading non-`IGNITION_*` config. Use it for
  `bar_is_forming` and `bar_freshness`. Without a session the lens treats
  the market as 24/7 and calls every bar forming.
- `universe.load_universe`: resolve the MarketConfig with the same
  MARKETS-then-IGNITION_ONLY lookup.
- Make sure `IGNITION_BAR_FINAL[<m>]` is in `IGNITION_FORMING_UNTIL_BAR_FINAL`.

Keep the key OUT of everything VIVEK, the bot and the schedulers read:
`VIVEK_JOURNAL_SESSION`, `MARKET_SCAN_WINDOWS`, `ALERT_RETURNS_BAR_FINAL`,
`MORNING_PLAYS_*`, `VIVEK_KILL_SWITCH_BROKERS`, bot dicts, `scan.yml`
options, `scan_gate`, and the `heartbeat.js` / `health.js` / `scan.js` /
`close.js` allowlists.

## 3. The Ignition page (build it once)

The panel opens from the deck pill, and the deck is a VIVEK page (it loads
`<m>_vivek.json`; the market buttons are hard-coded). An Ignition-only
market has no deck, so give the lens its own page, the way Momentum has
one. Build it the first time; later ports only extend `IGNITION_MARKETS`.

- `public/ignition.html`: copy the `momentum.html` shell (head and top
  bar). It needs:
  - `status.js` / `status.css` (status.test.js enforces this) and a
    `.deck-top-right`;
  - `phasemap-shared.js` loaded BEFORE `ignition.js` (it uses `PM.fmtMelb`
    and `PM.fetchTimeout`);
  - an empty `id="ig-market"` switch container and
    `<div class="ig-panel" id="ignition-panel" hidden>`;
  - no SCAN button;
  - the same `?v=` tags as index.html (test/cache.test.js).
- `ignition.js` page mode (~30 lines), active only when `#ig-market`
  exists:
  - pick the market from `?m=` (via `isMarket`), else `IGNITION_MARKETS[0]`;
  - build the switch buttons from `IGNITION_MARKETS`, so no HTML edit per
    port;
  - load and sync that market, and refresh every `LIVE_TTL_MS`;
  - say "No <M> Ignition screen yet" when the file is missing;
  - update `?m=` with `history.replaceState`.
  
  Keep it on private state so the pinned `window.Ignition` API keys don't
  move.
- Navigation: add `{href:"ignition.html", label:"IGNITION", key:"ignition",
  tab:<a glyph, not ⚡ (SPECS uses it)>}` to `MORE` in `public/js/nav.js`.
  Leave `PRIMARY` and the 5-slot bottom bar alone (test/momentum.test.js
  pins it).
- chart.js back-link: ONLY an Ignition-only market's chart goes back to
  `ignition.html?m=<market>`. The deck markets (crypto, ASX, NASDAQ) keep
  going back to the deck exactly as before; changing their flow is not part
  of a port. Branch on the market (`IGNITION_ONLY` list in chart.js, or
  "not a deck market"), apply it everywhere `SRC_BACK_MAP` is read (three
  places on 2026-10-08, including the `fail()` rebuilds; `grep -n
  SRC_BACK_MAP public/js/chart.js`), and pin both directions in
  test/deep_history.test.js: a deck market's back-link is unchanged, the
  new market's goes to the page.
- Tests:
  - slice the page-mode function in `test/ignition.test.js`;
  - in `tests/test_ignition_frontend.py`, check that ignition.html loads
    both assets with a version and has no hand-typed market literals;
  - add "ignition.html" to the narrow-width list in
    `test/e2e/screenshots.e2e.js`.
- Look at it with the `run-googy-boys-scanner` driver
  (`nav /ignition.html?m=<m>`). The data file appears only after the first
  run.

## 4. Chart links must draw the right instrument

Every Ignition link is `chart.html?s=<SYM>&m=<m>&src=ignition`. chart.js
maps an unknown `m` to `"asx"` (`VALID_MARKETS`), so `m=nyse&s=RMD` draws
the ASX ResMed plan in A$. That is a wrong-instrument bug, not a cosmetic
one. Fix it:

- `VALID_MARKETS`, `MARKET_LABEL` and the `.ct-market[data-mk]` chip style.
- `yfTickerFor`: append the market suffix (none for NYSE, `.TO`, `.L`).
  Keep a parity test with config's suffix.
- `tvSymbolFor`: `NYSE:` / `TSX:` / `LSE:`.
- The currency symbol in the header, the `tickerSession` / `MOM_SESSION`
  sessions, and the compare index.
- Bump `chart.js?v=` in chart.html, then restamp version.json.

## 5. Fence tests (new file, e.g. `tests/test_ignition_only_markets.py`)

- `IGNITION_ONLY_MARKETS` shares no key with `MARKETS`, and is a subset of
  `IGNITION_MARKETS`. Every Ignition market resolves through `E.meta`.
  Every non-crypto Ignition market has `RUN.session(m)` and an
  `IGNITION_BAR_FINAL` entry.
- Tripwire: `set(config.MARKETS) == {"asx", "nasdaq", "crypto"}`, with a
  docstring naming the enrolment points, so a later move into MARKETS is a
  visible decision.
- Not scanned or traded:
  - `scanner.run`, `vivek_run` and `vivek_backtest` with `--market <m>`
    exit 2;
  - scan.yml's market options, `scan_gate`, `MARKET_SCAN_WINDOWS`,
    `MORNING_PLAYS_*`, `VIVEK_KILL_SWITCH_BROKERS` and the bot dicts share
    no key with the registry;
  - a text fence: nothing under `scanner/broker/` (nor run.py, scan.py,
    vivek_backtest.py, watchdog.py, scripts/scan_gate.py,
    scripts/morning_plays.py) mentions `IGNITION_ONLY_`.
- Lens behaviour: forming at 15:59 and 16:29 New York, complete at 16:30;
  `expected_completed` is None; `max_age_days` as set; explicit floors.
- Re-point every `"nyse"` sentinel in the existing suites if porting NYSE.

## 6. Extra suites for a new market

```bash
python3 -m pytest tests/test_ignition_only_markets.py tests/test_universe.py tests/test_deck_session_stale.py tests/test_alert_returns.py tests/test_kill_switch_book.py tests/test_watchdog.py tests/test_scan_windows.py
node test/deep_history.test.js && node test/cache.test.js && node test/status.test.js && node test/momentum.test.js
```
