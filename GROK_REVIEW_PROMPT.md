# CODE REVIEW BRIEF — "Vivek 5.0" multi-market trading scanner + paper-trade bot

You are a **staff-level engineer and quant reviewer**. Below is a large, real, production trading-signal system. Your job is to review **everything** — correctness, money-safety, signal-logic soundness, security, performance, and maintainability — and return a prioritized findings report.

You do NOT have the repository. This document is self-contained: **Part C embeds the highest-risk source verbatim**, and **Part D is a precise file-by-file map** of the rest (with line counts and responsibilities) so you can reason about the whole even where code isn't inlined. Where you need to see code that isn't inlined, say so explicitly and state what you'd check.

Treat this as adversarial: assume there are real bugs that lose money, leak data, or silently corrupt results. Find them.

---

## 0. HOW TO REVIEW (read this first)

**Priorities, in order:**
1. **Money & execution correctness** — anything that could place a wrong/duplicate/mis-sized order, mismanage an exit, mis-mark a position, or fail to stop out. This system has a Bybit live path (currently paper/testnet-gated) plus a paper "bot book" that is the *only* track record.
2. **Signal logic soundness** — the VIVEK 200-SMA engine and its grading/hysteresis/direction/trigger logic. Whipsaw, look-ahead, double-counting, direction flips, badge ratcheting.
3. **Security** — the site is fully public on Cloudflare Pages; the API functions dispatch GitHub Actions and read/write a shared KV store.
4. **Data correctness** — the frontend reads JSON the backend writes; stale/contradictory/frozen artifacts mislead trading decisions.
5. **Performance & UX** — mobile PWA, 1.5MB payloads, re-render cascades.
6. **Maintainability & dead code.**

**Method:** For each finding give: (a) a one-line title, (b) the concrete mechanism with file/function evidence, (c) a *failure scenario* — specific inputs/state → wrong outcome, (d) severity 1–5 (5 = loses money or leaks data), (e) a suggested fix. Prefer fewer, verified, high-severity findings over a long list of style nits. **Challenge the design, not just the code** — if the whole approach to (say) direction hysteresis is unsound, say so.

**Verification stance:** where you assert a bug, describe the exact path that triggers it. If you're inferring from a summary (Part D) rather than inlined code, mark the finding **[INFERRED — needs the file]** and say which file resolves it.

**What is OUT OF SCOPE (already known/decided — do not re-report, but DO challenge if you think we're wrong):**
- The PhaseMap detection maths are frozen by a separate owner spec — review its *engineering* (error handling, determinism, output) but do not propose changing what constitutes a sweep/displacement/zone.
- Known & accepted: the site is public (Cloudflare Access is a pending owner action); the sole data source is yfinance (delayed, survivor-biased — a paid provider is a pending decision); the retired "firehose" track-record journal; the bot is paper-only pending a testnet round-trip drill.
- We have already run an internal audit that found ~107 issues (see Section 2). **Do not simply repeat those** — your value is to (1) *verify or refute* the highest-severity ones with fresh eyes, (2) find what we **missed**, especially interactions across subsystems, and (3) tell us which of our findings we've mis-prioritized.

---

## 1. WHAT THE SYSTEM IS

**Vivek 5.0** is a three-lens trading scanner + paper-trade journal + (paper, gated-live) execution bot. Owner is a solo retail trader in Melbourne, Australia. Markets: **ASX** (~2,000 names), **NASDAQ** (~1,430 Global Select names), **crypto** (top-100 by cap + pinned extras).

**Stack:**
- **Scanners**: Python (`scanner/`, `phasemap/`), run in **GitHub Actions** on cron. They write JSON to `public/data/` and commit it back to `main`.
- **Frontend**: vanilla JS + CSS, static, served by **Cloudflare Pages** (auto-deploys on push to `main`). No build step. PWA with a service worker. iOS-style dark theme.
- **Backend API**: **Cloudflare Pages Functions** (`functions/api/*.js`) — Workers runtime (NOT Node; no `require`, no fs; env via `context.env`; a KV binding `JOURNAL_KV`). These dispatch GitHub Actions (scan/close) and back the cross-device journal sync + the cloud stop/target watcher.
- **Broker (built, gated off)**: Bybit USDT perpetuals via `pybit`. IBKR planned later for ASX.

**The three lenses:**
1. **VIVEK** (core) — price *reacting* at its **200-period SMA**, read on Weekly / 3-Day / Daily(as an "H4 proxy") levels. Grades A+/A/B+/WATCH; per-timeframe plans (entry / stop / TP1-3); three entry "triggers": **reclaim / retest / break**; a setup is **ARMED** only when a trigger fires, else WATCHING. `scanner/vivek.py` + `scanner/scan.py`.
2. **PhaseMap** (trap lens) — liquidity **sweep → displacement**, zone-based (zones are *bands*, never single prices). A state machine: TRAP_SET → SWEPT → DISPLACED → RUNNING → STALLED/COMPLETE/DEAD. Deterministic; no LLM in the scan path. `phasemap/` package. **Detection maths are spec-frozen.**
3. **Specs** (discovery lens) — sub-$0.50 names breaking out of a base on a ≥3× volume spike. Its own backtest says it's a shortlist generator, not an entry system. `scanner/spec.py` via `scanner/spec_run.py`.

**Confluence** is the headline feature: when 2+ lenses agree on one name in the same direction, banners appear site-wide, Discord gets pinged (`scanner/confluence_alert.py`), and an ALERTS page logs it.

**The bot book** (`journal/vivek_bot_book.json`) is the ONE track record: A+ only, max 10 open per market, one per symbol, short slots reserved, daily-loss guards. Paper today.

**Data flow (critical to understand):**
```
GitHub Actions cron ──► scanner/*.py or phasemap/run.py
    ├─ download bars (yfinance)          [scanner/data.py, phasemap provider]
    ├─ compute signals / zones           [vivek.py, spec.py, phasemap engine]
    ├─ manage paper bot book             [broker/vivek_run.py → vivek_bot.py decisions]
    ├─ write public/data/*.json          [scanner/output.py, phasemap/output/writer.py]
    └─ git commit + push to main (retry loop on race)
                    │
                    ▼
Cloudflare Pages auto-deploys public/ ──► browser (vanilla JS reads the JSON)
                    ▲
Cloudflare Functions (functions/api/*) ──► dispatch Actions (scan/close),
                                            KV journal sync, cloud stop watcher (tick.js)
```

**Key cadences:** `scan.yml` every 30 min in market hours (weekend crypto-only); `crypto_bot.yml` hourly 24/7; `phasemap.yml` nightly; `lens_backtest.yml` weekly (owns `vivek_backtest.json`); `stop_watcher.yml` every 5 min; `test.yml` on every push. **GitHub cron is best-effort and observed to fire a fraction of scheduled times, hours late** — reason about the consequences.

**Money/rules constants live in `scanner/config.py`** and are published to `public/data/bot_rules.json` each scan; the dashboard reads them (single source of truth). Selected values: bot trades **A+ only**, min R:R 1.5, risk **0.35%**/trade (band 0.25–0.5), leverage 5× stocks / 3× crypto, **max 10 positions per market**, one per symbol, max-per-sector 3, daily-loss-limit 3%, skip `retest` entries, prefer `1W` timeframe. `VIVEK_BOT_MAX_STOP_PCT = 50`.

---

## 2. WHAT WE ALREADY FOUND (verify / refute / extend — don't just repeat)

Our internal 12-reviewer audit surfaced these highest-severity items. **Confirm the real ones, refute any you think are wrong, and — most valuable — find what these missed.**

**Money / bot:**
- A held bot position (MDB) dropped out of the NASDAQ universe after it was expanded; the runner only downloads *universe* tickers, so that position is unpriceable → its stop can never fire and it squats a slot forever. (Suspected class of bug: **open-book ⊄ download set**.)
- Bybit order qty/price are formatted with hardcoded decimal ladders, never fetched from `get_instruments_info` → step-size rejections / mis-sizing.
- `submit()` wraps a retrying client in a second retry loop (up to ~9 submits); a timeout *after* Bybit accepts an order can double-enter.
- `reconcile` reads `exitType` but Bybit V5 closed-pnl carries `execType` → every live exit closes as reason "unknown"; and it deducts a $40 ASX-CFD fee from crypto perp PnL.
- reconcile only walks the journal's open list → an orphan position at Bybit (crash between submit and save) is invisible to marking and kill-switch.
- The hardened risk stack (pre_trade_check's 12 gates, circuit_breaker, kill_switch) is wired only into the *legacy scalp* path, **not** the VIVEK path that actually maintains the track record.
- Three market books each size off the same $10k equity; one funded account → up to 9% aggregate daily loss.
- The bot-page "KILL SWITCH" only dims cards + writes localStorage; it doesn't touch the real Actions-run bot.

**Signal logic:**
- Direction is a zero-width sign test (`price >= level` → long else short) with no dead-band, while grade hysteresis persists only `{symbol: grade}` (no direction) → a 0.1% wobble flips LONG↔SHORT while the A+ badge is held across the flip.
- Grade hysteresis reads the *published* (already-hysteresis'd) grade → a 7-scorer stays A+ indefinitely, lowering the bot's effective A+ bar.
- The grade/armed gate is computed from the 1D plan only, but the bot prefers the 1W plan → weekly-armed setups get demoted and never traded; 3D plans never considered by the bot's plan picker.
- A reclaim trigger re-fires for ~6 consecutive daily scans with entry = each day's close (drifts up to ~4% off the true trigger).
- The "H4 200 SMA" chip is actually the Daily-200 (on 24/7 crypto that's ~6× off the true H4-200).
- Stops anchor to the plan frame's *own* distant 200-SMA (the "AXON 37% stop on a 1D plan" geometry).

**Security:**
- `/api/close`: symbol/market are only length-capped then interpolated into a shell `run:` block in the workflow → **CI command injection**.
- `/api/tick`: auth returns true when `TICK_SECRET` is unset ("open by default"), and its response leaks closed-trade details across *all* synced journals in KV.
- `/api/journal`: no rate limit; accepts 4-char sync codes; KV key is `SHA-256("gbs-journal:"+code)` → enumerable.
- The scan/close daily-cap counters are non-atomic read-modify-write → bypassable under concurrency.
- `price`/`quote` proxies: no throttling → free public market-data relay.

**Data correctness:**
- The AI-BOT page renders a *frozen June* `bot_status.json` as if live.
- VIVEK trigger tooltips hardcode "+1.6R / 56% win" while the live backtest says +0.66R.
- The long-only backtest cron was committed a day after its only July fire date → the "evidence" file predates the universe expansion.
- NASDAQ Specs is structurally empty ($0.50 cap vs a ~$4 min-bid exchange) yet still offers the tab.
- Timestamps: five writers, four formats (market-local offsets, `Z`, bare dates).

**Performance:**
- Dashboard downloads the 1.5MB scan file twice per load (confluence re-fetches what was just parsed) and re-renders the full list ~4× (an open trade-plan panel snaps shut ~1s after you open it).
- ~4MB of scan payloads persisted to localStorage, starving the journal's iOS quota.
- JSON shipped `indent=2` (~41% bloat).

Again: **your job is not to re-list these.** Verify the scary ones, kill the wrong ones, and find the ones we didn't.

---

## 3. WHAT TO PAY SPECIAL ATTENTION TO (open questions we want answered)

1. **The whole direction/hysteresis/trigger interaction in VIVEK.** Given the code in Part C (`vivek.py`) and the summaries of `scan.py`, is there a coherent, whipsaw-resistant way price at the 200-SMA should map to {grade, direction, armed, entry}? Design-level critique welcome.
2. **The Bybit order lifecycle end-to-end** (submit → fill → reconcile → exit → kill). Trace a partial fill, a timeout-after-accept, a stop-and-target-in-the-same-bar, and a manual position. Where does state diverge from the broker?
3. **The paper backtester vs the live bot** — do they share the same management rules, or has logic drifted? (`vivek_backtest.py` replays the engine; `vivek_run.py`/`vivek_bot.py` run live.) A backtest that manages trades differently than the bot invalidates the "evidence."
4. **Concurrency across 6+ Actions workflows** all committing to `public/data` on `main` with copy-pasted retry loops — construct a sequence where one workflow reverts another's fresh data.
5. **The security surface as a whole** — chain the individual weaknesses. E.g. open-by-default tick + KV enumeration + no rate limit: what's the worst an anonymous internet user can do?
6. **Anything that makes a displayed number wrong** — a trader acts on these. Mis-marked PnL, stale "live" data shown as fresh, contradictory copy, backtest cohorts with tiny/insane N.

---

---

# PART C — VERBATIM SOURCE (the high-risk core)

The following files are the highest-bug-density, highest-blast-radius code, given in full. Everything else is mapped in Part D. Line numbers are included as a reference for your findings.


## === C1. MONEY-PATH CONFIG CONSTANTS (scanner/config.py, extract) ===

### `scanner/config.py`  (lines 240–410)
> VIVEK engine + bot constants — the single source of truth for sizing/gates/leverage.
```python
  240  # the Weekly (and a higher-TF daily proxy for H4). Low leverage, tiny risk,
  241  # pre-defined TP1/TP2/TP3 with structured scale-outs and SL that only ever moves
  242  # in the trade's favour.
  243  # Schema version stamped into every *_vivek.json. Bump when the row/payload
  244  # shape the frontend depends on changes (e.g. a new per-row field). The UI reads
  245  # this to tell "old data, missing fields" apart from "no setups", instead of
  246  # silently hiding features. v2 = adds entry_types + freshness/version stamping.
  247  VIVEK_SCHEMA_VERSION   = 3
  248  VIVEK_SMA              = 200       # the moving average everything keys off
  249  VIVEK_AT_LEVEL_TOL     = 0.02      # within 2% of the 200 SMA = "at the level"
  250  VIVEK_NEAR_TOL         = 0.04      # within 4% = "in play" (tightened from 6% for selectivity)
  251  # Coins pinned into the crypto universe regardless of market-cap rank
  252  # (2026-07-02, the FLASH gap: not in CoinGecko's top-100 -> invisible to
  253  # every scanner). Add symbols here to guarantee coverage; Yahoo-less coins
  254  # drop out at scan time harmlessly.
  255  CRYPTO_EXTRA_SYMBOLS   = ["XMR", "FLASH"]
  256  
  257  VIVEK_INCLUDE_3D_LEVEL = True      # 2026-07-02: also treat the 3-Day 200 SMA as an in-play
  258                                     # level (W > 3D > D). Found via XMR: price sat AT the 3D-200
  259                                     # (the level the community was watching) but was -23% from
  260                                     # the Daily and +10% from the Weekly -> invisible to the scan
  261  VIVEK_DATA_PERIOD      = "5y"      # long history so a Weekly SMA200 is meaningful
  262  VIVEK_MIN_WEEKLY_BARS  = 60        # need at least this many weekly bars to use Weekly SMA
  263  VIVEK_MIN_HISTORY      = 220       # min daily bars to compute a Daily SMA200 (~H4 proxy)
  264  VIVEK_ATR_STOP_MULT    = 1.0       # stop sits ATR×this beyond the reaction extreme
  265  VIVEK_PIVOT_WINDOW     = 4         # swing pivot lookback for structure + stops
  266  VIVEK_SCORE_MAX        = 10
  267  # Grade ladder (note: B+ and WATCH, not B/C, per 5.0 grading)
  268  VIVEK_GRADE_CUTOFFS    = [("A+", 8), ("A", 6), ("B+", 4), ("WATCH", 2)]
  269  # Grade hysteresis: a setup holds its PREVIOUS (higher) grade unless its score
  270  # falls more than this many points below that grade's cutoff. Stops borderline
  271  # names flip-flopping (e.g. A+↔A) on tiny scan-to-scan data differences. 0 = off.
  272  VIVEK_GRADE_HYSTERESIS = 1
  273  # Drop a still-forming trailing daily bar (the current session's incomplete bar)
  274  # so grades/plans key off COMPLETED bars only — removes partial-bar variance.
  275  VIVEK_DROP_FORMING_BAR = True
  276  
  277  # Structural take-profits — TP1/TP2/TP3 land on REAL prior structure (resistance
  278  # above for longs, support below for shorts), so R:R varies and means something.
  279  # R-multiples are only a fallback when there isn't enough structure to fill 3 TPs.
  280  VIVEK_TARGET_LOOKBACK  = 180       # daily bars searched for prior swing structure
  281  VIVEK_TP_MIN_R         = 0.8       # a target must sit at least this many R beyond entry
  282  VIVEK_TP_MAX_R         = 10.0      # ignore structure further than this (unrealistic target)
  283  VIVEK_TP_CLUSTER_R     = 0.6       # merge structural levels within this many R of each other
  284  VIVEK_TP_R             = [1.5, 3.0, 5.0]   # fallback TP1/TP2/TP3 when structure is thin
  285  VIVEK_MIN_TRADEABLE_RR = 1.5       # A/A+ need at least this R:R to TP2, else demote to B+
  286  VIVEK_SHORT_TP_FLOOR   = 0.05      # a short's targets can't fall below 5% of entry (price→0 floor)
  287  
  288  # Trigger model — a setup is ARMED only when one of three mechanical triggers has
  289  # fired on the latest completed bar; otherwise it is merely WATCHING (caps at B+).
  290  # This replaces "entry = last close" with condition -> trigger -> armed.
  291  VIVEK_TRIGGER_LOOKBACK = 5         # bars to look back for the pierce that precedes a reclaim
  292  VIVEK_RETEST_VOL_MULT  = 1.0       # a retest should come on <= average volume (calm test)
  293  VIVEK_BREAK_VOL_MULT   = 1.5       # a structure break needs >= this x average volume to count
  294  VIVEK_TRIGGER_PRIORITY = ["reclaim", "retest", "break"]   # first match wins
  295  VIVEK_MIN_TF_BARS      = 30        # min bars to build a per-timeframe plan (e.g. Weekly)
  296  
  297  # 5.0 execution rules (used by the autonomous bot + dashboard)
  298  VIVEK_RISK_PCT_DEFAULT = 0.25      # % of equity risked per trade (0.25–0.5 range)
  299  VIVEK_RISK_PCT_MAX     = 0.5
  300  VIVEK_MAX_LEVERAGE     = 5         # hard cap; 2.5–3× preferred
  301  VIVEK_TP_SCALE_LONG    = [0.25, 0.50, 0.15]   # book at TP1 / TP2 / TP3 (10% runner left)
  302  VIVEK_TP_SCALE_SHORT   = [0.50, 0.25, 0.15]   # shorts bank more, sooner
  303  
  304  # VIVEK paper journal — realistic intraday execution. Trades are only OPENED
  305  # during the (delayed) market session and entered at the delayed intraday price
  306  # at that moment; they then mark-to-market against the observed intraday price on
  307  # every market-hours scan — mirroring manual trading off a ~15-min-delayed feed.
  308  VIVEK_JOURNAL_MARKET_HOURS   = True    # gate new entries to the live session
  309  VIVEK_JOURNAL_FEED_DELAY_MIN = 15      # ~15-min delayed feed → action window shifts +15m
  310  
  311  # Execution-cost realism (fees + slippage). Modelled as an R-drag computed from
  312  # each trade's own fills so the forward-test expectancy is NET, not gross:
  313  #   • commission is paid on the entry and on every exit (a fraction of notional);
  314  #   • slippage is paid only on MARKET-style fills — the entry and a stop/trail
  315  #     close — never on a resting TP limit, which fills at its level.
  316  # Values are in basis points (1 bp = 0.01%). Stocks are cheap/liquid; crypto
  317  # perps carry a wider spread + taker fee, so they cost more. "default" backstops
  318  # any market key not listed.
  319  VIVEK_COSTS_ENABLED   = True
  320  VIVEK_COMMISSION_BPS  = {"asx": 2.0, "nasdaq": 1.0, "crypto": 6.0, "default": 2.0}
  321  VIVEK_SLIPPAGE_BPS    = {"asx": 5.0, "nasdaq": 4.0, "crypto": 8.0, "default": 5.0}
  322  # Base local session per market (pre-delay), as (open_h, open_m, close_h, close_m).
  323  # None = 24/7 (crypto). The feed delay is added to both ends at runtime.
  324  VIVEK_JOURNAL_SESSION = {
  325      "asx":    (10, 0, 16, 0),
  326      "nasdaq": (9, 30, 16, 0),
  327      "crypto": None,
  328  }
  329  
  330  # Autonomous bot — strict VIVEK 5.0 rules (see scanner/broker/vivek_bot.py).
  331  VIVEK_BOT_MIN_GRADE    = "A+"      # A+ ONLY — never A / B+ / WATCH
  332  VIVEK_BOT_MIN_RR       = 1.5       # skip setups whose R:R (to TP2) is below this
  333  # Skip non-operating vehicles (REITs / ETFs / LICs / managed funds) — they hug
  334  # their 200 SMA so they over-produce reactions, but aren't what we want the bot
  335  # trading. Affects the bot's selection only; the scanner still displays them.
  336  VIVEK_BOT_EXCLUDE_FUNDS = True
  337  # Favour the strongest trigger: the walk-forward backtest showed "retest" is
  338  # flat-to-negative while "reclaim" carries the edge, so the bot skips these
  339  # entry types. Selection-only; the scanner still shows them. Empty list = take all.
  340  VIVEK_BOT_SKIP_ENTRY_TYPES = ["retest"]
  341  VIVEK_BOT_PREFER_TF    = "1W"      # Weekly plans are primary (less noise); fall back to 1D
  342  # Per-market leverage: stocks 5× (positions sit smaller), crypto 3×.
  343  VIVEK_BOT_LEVERAGE     = {"asx": 5, "nasdaq": 5, "crypto": 3}
  344  # LONG-ONLY: the walk-forward backtest showed the short side loses ~0.5R per
  345  # trade on every market tested (ASX/NASDAQ/Crypto) while longs carry the edge,
  346  # so the bot is long-only for now — shorts disabled and no short slots reserved.
  347  # The short machinery is retained behind the flag in case it's reworked later.
  348  VIVEK_BOT_ALLOW_SHORTS   = False   # False → bot never opens a short
  349  VIVEK_BOT_MAX_POSITIONS  = 10      # max concurrent open positions PER MARKET
  350  VIVEK_BOT_MIN_SHORTS     = 0       # reserved short slots (0 while long-only)
  351  VIVEK_BOT_RISK_PCT       = 0.35    # % equity risked per trade (flexible 0.25–0.5 band)
  352  # Tradeability gates — quality-of-fill filters, NOT strategy changes. They only
  353  # block pathological entries the paper model can't price honestly:
  354  #  • MIN_PRICE: sub-5c ASX names (e.g. a $0.021 micro-cap) trade with spreads
  355  #    worth multiple R — a paper fill at "the price" is fiction. Per-market floor.
  356  #  • MAX_STOP_PCT: a structural stop >50% from entry (seen: −95% on a weekly
  357  #    crypto plan) makes R sizing meaningless — risk-based units go microscopic
  358  #    and the position is a lottery ticket, not a managed trade.
  359  VIVEK_BOT_MIN_PRICE      = {"asx": 0.05, "nasdaq": 1.0, "crypto": 0.0, "default": 0.0}
  360  VIVEK_BOT_MAX_STOP_PCT   = 50.0    # skip if |entry−stop| > this % of entry (0 = off)
  361  #  • MIN_STOP_PCT: the inverse pathology — a stop <1% from entry usually means a
  362  #    dead/pegged instrument (stablecoin-likes, defensives glued to the SMA).
  363  #    Risk sizing then buys a leverage-capped MAX position in something that
  364  #    doesn't move, squatting in a scarce slot for months. 0 = off.
  365  VIVEK_BOT_MIN_STOP_PCT   = 1.0
  366  #  • MIN_ADV / MAX_NOTIONAL_PCT_ADV: liquidity honesty. Values are 20-day average
  367  #    dollar volume in the market's QUOTE currency (A$ for ASX, US$ elsewhere).
  368  #    Below MIN_ADV a real fill would eat multiple R in spread/impact, so the
  369  #    paper edge is fiction exactly where it looks best. On top of the floor the
  370  #    position's notional may not exceed MAX_NOTIONAL_PCT_ADV % of ADV. Crypto
  371  #    top-100 is deep enough that the floor is off there. Unknown ADV = exempt
  372  #    (fail-open, same as unknown sectors). 0 = off.
  373  VIVEK_BOT_MIN_ADV        = {"asx": 250_000, "nasdaq": 2_000_000, "crypto": 0, "default": 0}
  374  VIVEK_BOT_MAX_NOTIONAL_PCT_ADV = 2.0
  375  # Slot hygiene — positions are capital even when flat:
  376  #  • MAX_HOLD_DAYS: a position that hasn't reached TP1 after this many calendar
  377  #    days is going nowhere — close it (exit_reason "time") and free the slot.
  378  #    Runners past TP1 are exempt: they're already risk-free. 0 = off.
  379  VIVEK_BOT_MAX_HOLD_DAYS  = 28
  380  #  • REENTRY_COOLDOWN_DAYS: after a full stop-out, don't re-enter the same
  381  #    symbol for this many days — stops the bot churning the same level and
  382  #    re-donating 1R per scan cycle while a setup keeps re-arming. 0 = off.
  383  VIVEK_BOT_REENTRY_COOLDOWN_DAYS = 7
  384  # Earnings gap-avoidance (best-effort, fail-open): skip NEW entries when the
  385  # name reports within the buffer. Gapping through a stop is the one tail the
  386  # stop can't manage. Lookup is one yfinance call per candidate FILL (a handful
  387  # per run, not the universe) and any lookup failure lets the trade through.
  388  VIVEK_BOT_EARNINGS_BUFFER_DAYS = 3
  389  VIVEK_BOT_EARNINGS_MARKETS     = ("nasdaq",)   # ASX earnings data on yfinance is too patchy to trust
  390  # Crypto correlation: coins have no GICS sector, so the per-sector cap never
  391  # bound them — 4 alts are usually ONE beta-to-BTC bet. Synthetic sectors:
  392  # majors below get "crypto-major", everything else "crypto-alt", then the
  393  # normal VIVEK_BOT_MAX_PER_SECTOR cap applies.
  394  VIVEK_BOT_CRYPTO_MAJORS  = ("BTC", "ETH")
  395  # Correlation control: cap open positions per GICS sector per market so the book
  396  # can't quietly become one macro bet (e.g. 6 ASX materials names = one iron-ore
  397  # trade). Empty/unknown sectors (crypto) are exempt. 0 = off.
  398  VIVEK_BOT_MAX_PER_SECTOR = 3
  399  # Push a digest of the bot's opens/closes through alert_dispatch each run.
  400  # OFF by default: the scan workflow exports SMTP creds, and alert_dispatch fires
  401  # EVERY configured channel — enabling this without wanting it means an email per
  402  # bot trade event (hourly-ish in session). Flip to True when you want pushes
  403  # (and add DISCORD_WEBHOOK_URL to the scan workflow env for Discord instead).
  404  VIVEK_BOT_NOTIFY_TRADES = False
  405  # Daily-loss guardrail (per market). Once today's realised + open-unrealised P&L
  406  # falls to -this% of equity, the runner HALTS new entries for the rest of the
  407  # session (it still manages/closes open positions). In a future live phase this
  408  # is also where a flatten would fire; in paper it just stops adding risk.
  409  VIVEK_BOT_MAX_DAILY_LOSS_PCT = 3.0
  410  # Weekly circuit breaker (per market): the daily guard resets at midnight, so
```


## === C2. VIVEK SIGNAL ENGINE ===

### `scanner/vivek.py`  (651 lines)
> The 200-SMA engine: evaluate, levels/plans, grading, DIRECTION, detect_trigger, narrative. Signal correctness lives here.
```python
    1  """VIVEK engine — 5.0Trading.Bull-style setups built around the 200 SMA.
    2  
    3  5.0's edge, distilled into mechanical rules:
    4    * The 200 SMA on the higher timeframes (Weekly, H4) is THE level. Trades are
    5      reactions at it — a bounce off it as support, a rejection at it as
    6      resistance, or a break-and-retest.
    7    * Direction follows the reaction: long when price holds the 200 SMA from above,
    8      short when it's rejected from below.
    9    * Every trade defines Entry, SL and TP1/TP2/TP3 up front, with structured
   10      scale-outs and an SL that only ever moves in the trade's favour.
   11  
   12  Data note: the daily scan pipeline gives daily bars. We compute a true Weekly
   13  200 SMA (resampled from a long daily history) and use the Daily 200 SMA as the
   14  "higher-timeframe-below-weekly" proxy for 5.0's H4 level. A real H4 200 SMA needs
   15  intraday infrastructure and is a future upgrade (see ROADMAP); the rules and
   16  grading below are written so that swap is a drop-in.
   17  
   18  Grading: A+ (clear Weekly/H4 200 SMA reaction + strong structure) · A (good
   19  interaction + solid structure) · B+ (some relevance, weaker structure) · WATCH
   20  (near the level but missing a clean reaction or structure).
   21  """
   22  
   23  import numpy as np
   24  import pandas as pd
   25  
   26  from . import config
   27  from .grading import grade_from_points
   28  from .indicators import atr as calc_atr, pivot_highs, pivot_lows, sma
   29  
   30  
   31  def _weekly_sma200(df: pd.DataFrame) -> tuple[float | None, int]:
   32      """Weekly 200 SMA from a daily frame (resampled W-FRI). Returns (value, n_weeks)."""
   33      try:
   34          wk = df["Close"].resample("W-FRI").last().dropna()
   35      except Exception:
   36          return None, 0
   37      n = len(wk)
   38      if n < config.VIVEK_MIN_WEEKLY_BARS:
   39          return None, n
   40      window = min(config.VIVEK_SMA, n)         # use full 200 when available, else best effort
   41      return float(sma(wk, window).iloc[-1]), n
   42  
   43  
   44  def _structure(df: pd.DataFrame, direction: str) -> float:
   45      """0..1 structure score: are recent swings stacking in the trade's favour?
   46  
   47      Long wants higher lows (and ideally higher highs); short wants lower highs.
   48      """
   49      pw = config.VIVEK_PIVOT_WINDOW
   50      lows = pivot_lows(df, pw).dropna().tail(3).tolist()
   51      highs = pivot_highs(df, pw).dropna().tail(3).tolist()
   52      score = 0.0
   53      if direction == "long":
   54          if len(lows) >= 2 and lows[-1] > lows[0]:
   55              score += 0.6
   56          if len(highs) >= 2 and highs[-1] >= highs[0]:
   57              score += 0.4
   58      else:
   59          if len(highs) >= 2 and highs[-1] < highs[0]:
   60              score += 0.6
   61          if len(lows) >= 2 and lows[-1] <= lows[0]:
   62              score += 0.4
   63      return round(score, 2)
   64  
   65  
   66  def evaluate(df: pd.DataFrame) -> dict | None:
   67      """Find a 200 SMA reaction. Returns a signal dict or None if no setup."""
   68      if df is None or len(df) < config.VIVEK_MIN_HISTORY:
   69          return None
   70  
   71      close = df["Close"]
   72      price = float(close.iloc[-1])
   73      if not np.isfinite(price) or price <= 0:
   74          return None
   75  
   76      daily_sma = float(sma(close, config.VIVEK_SMA).iloc[-1])      # H4 proxy
   77      weekly_sma, n_weeks = _weekly_sma200(df)
   78      if not np.isfinite(daily_sma) or daily_sma <= 0:
   79          return None
   80  
   81      atr = float(calc_atr(df, 14).iloc[-1])
   82      pw = config.VIVEK_PIVOT_WINDOW
   83      recent = df.tail(max(2 * pw + 1, 12))
   84      swing_low = float(recent["Low"].min())
   85      swing_high = float(recent["High"].max())
   86  
   87      # 3-Day 200 SMA (2026-07-02, the XMR gap): a name can sit exactly AT the
   88      # 3D-200 while being far from both the Weekly and Daily 200s — previously
   89      # invisible. Same epoch-anchored resample the 3-Day plan/chart uses.
   90      sma_3d = None
   91      if getattr(config, "VIVEK_INCLUDE_3D_LEVEL", False):
   92          d3 = _resample_3day_ohlc(df)
   93          if d3 is not None and len(d3) >= config.VIVEK_SMA:
   94              v = float(sma(d3["Close"], config.VIVEK_SMA).iloc[-1])
   95              if np.isfinite(v) and v > 0:
   96                  sma_3d = v
   97  
   98      # Evaluate each higher-timeframe 200 SMA level; keep the strongest "in play".
   99      levels = []
  100      if weekly_sma:
  101          levels.append(("weekly", weekly_sma))
  102      if sma_3d:
  103          levels.append(("3d", sma_3d))
  104      levels.append(("h4", daily_sma))   # Daily-200 proxy for the H4 200 SMA
  105  
  106      best = None
  107      for tf, lvl in levels:
  108          dist = (price - lvl) / price                  # >0: price above the level
  109          adist = abs(dist)
  110          if adist > config.VIVEK_NEAR_TOL:
  111              continue                                  # not in play
  112          at_level = adist <= config.VIVEK_AT_LEVEL_TOL
  113  
  114          # Direction + reaction type from how price is sitting relative to the level.
  115          if price >= lvl:
  116              direction = "long"                        # holding the level as support
  117              touched = swing_low <= lvl * (1 + config.VIVEK_AT_LEVEL_TOL)
  118              reaction = "bounce" if (touched and price > swing_low) else "hold"
  119          else:
  120              direction = "short"                       # rejected by the level as resistance
  121              touched = swing_high >= lvl * (1 - config.VIVEK_AT_LEVEL_TOL)
  122              reaction = "reject" if (touched and price < swing_high) else "fade"
  123  
  124          struct = _structure(df, direction)
  125          cand = {
  126              "tf": tf, "level": lvl, "dist_pct": round(dist * 100, 2),
  127              "at_level": at_level, "direction": direction, "reaction": reaction,
  128              "structure": struct,
  129          }
  130          # Rank: weekly beats 3d beats h4; then "at level"; then reaction
  131          # quality; then structure.
  132          cand["_rank"] = (
  133              {"weekly": 2, "3d": 1.5}.get(tf, 1)
  134              + (2 if at_level else 0)
  135              + (2 if reaction in ("bounce", "reject") else 0)
  136              + struct
  137          )
  138          if best is None or cand["_rank"] > best["_rank"]:
  139              best = cand
  140  
  141      if best is None:
  142          return None
  143  
  144      # Confluence bonus: both the Weekly AND Daily 200 SMA near price together.
  145      confluence = bool(weekly_sma) and abs((daily_sma - weekly_sma) / price) <= config.VIVEK_NEAR_TOL
  146  
  147      return {
  148          "close": price,
  149          "weekly_sma200": round(weekly_sma, 8) if weekly_sma else None,
  150          "daily_sma200": round(daily_sma, 8),
  151          "weekly_bars": n_weeks,
  152          "atr": round(atr, 8),
  153          "swing_low": round(swing_low, 8),
  154          "swing_high": round(swing_high, 8),
  155          "level_tf": best["tf"],
  156          "level": round(best["level"], 8),
  157          "dist_pct": best["dist_pct"],
  158          "at_level": best["at_level"],
  159          "direction": best["direction"],
  160          "reaction": best["reaction"],
  161          "structure": best["structure"],
  162          "confluence": confluence,
  163          "uptrend": best["direction"] == "long",   # for frontend filters that read `uptrend`
  164      }
  165  
  166  
  167  def score_and_grade(sig: dict) -> tuple[int, str | None, list[str]]:
  168      """Score out of VIVEK_SCORE_MAX, then map to A+/A/B+/WATCH."""
  169      pts = 0
  170      fired: list[str] = []
  171  
  172      # 1) Which 200 SMA is in play (the heart of the setup).
  173      if sig["level_tf"] == "weekly":
  174          pts += 4
  175          fired.append("WEEKLY 200 SMA")
  176      elif sig["level_tf"] == "3d":
  177          pts += 3
  178          fired.append("3D 200 SMA")
  179      else:
  180          pts += 3
  181          fired.append("H4 200 SMA")
  182  
  183      # 2) Right at the level vs merely near it (near-only adds nothing — that's
  184      #    what separates a WATCH from a tradeable grade).
  185      if sig["at_level"]:
  186          pts += 2
  187          fired.append("AT THE LEVEL")
  188  
  189      # 3) Reaction quality — a clean bounce/reject is what makes it actionable.
  190      if sig["reaction"] in ("bounce", "reject"):
  191          pts += 2
  192          fired.append("CLEAN REACTION")
  193  
  194      # 4) Structure stacking in the trade's favour.
  195      if sig["structure"] >= 0.8:
  196          pts += 2
  197          fired.append("STRONG STRUCTURE")
  198      elif sig["structure"] >= 0.5:
  199          pts += 1
  200          fired.append("OK STRUCTURE")
  201  
  202      # 5) Weekly + H4 confluence.
  203      if sig.get("confluence"):
  204          pts += 1
  205          fired.append("W+H4 CONFLUENCE")
  206  
  207      pts = min(pts, config.VIVEK_SCORE_MAX)
  208      grade = grade_from_points(pts, config.VIVEK_GRADE_CUTOFFS)
  209      return pts, grade, fired
  210  
  211  
  212  def _structural_targets(df: pd.DataFrame, direction: str, entry: float, risk: float) -> list[float]:
  213      """Up to three REAL targets from prior structure, ordered away from entry.
  214  
  215      Longs aim at prior resistance (pivot highs above entry); shorts at prior
  216      support (pivot lows below entry). Targets must sit between MIN_R and MAX_R
  217      of risk away, and clustered pivots are merged so the three TPs are distinct.
  218      Returns [] when there's no usable structure (caller falls back to R-multiples).
  219      """
  220      if risk <= 0:
  221          return []
  222      pw = config.VIVEK_PIVOT_WINDOW
  223      look = df.tail(config.VIVEK_TARGET_LOOKBACK)
  224      lo = entry + config.VIVEK_TP_MIN_R * risk
  225      hi = entry + config.VIVEK_TP_MAX_R * risk
  226      if direction == "long":
  227          piv = pivot_highs(look, pw).dropna().tolist()
  228          cands = sorted(p for p in piv if lo <= p <= hi)
  229      else:
  230          lo = entry - config.VIVEK_TP_MAX_R * risk
  231          hi = entry - config.VIVEK_TP_MIN_R * risk
  232          piv = pivot_lows(look, pw).dropna().tolist()
  233          cands = sorted((p for p in piv if lo <= p <= hi), reverse=True)
  234  
  235      picked: list[float] = []
  236      for p in cands:
  237          if all(abs(p - q) >= config.VIVEK_TP_CLUSTER_R * risk for q in picked):
  238              picked.append(float(p))
  239          if len(picked) == 3:
  240              break
  241      return picked
  242  
  243  
  244  def _build_levels(df: pd.DataFrame, direction: str, entry: float, level: float,
  245                    swing_low: float, swing_high: float, atr: float) -> dict:
  246      """The shared SL + TP1/TP2/TP3 construction, given a known entry.
  247  
  248      TPs land on real prior structure where it exists; any remaining slots fall
  249      back to R-multiples placed strictly beyond the last target so ordering holds.
  250      R:R is measured to the ACTUAL TP2, so it genuinely varies between setups.
  251      Returns {} (caller treats as "no plan") when the stop gives non-positive risk.
  252      """
  253      atr = max(atr, entry * 0.001)
  254      buf = atr * config.VIVEK_ATR_STOP_MULT
  255  
  256      if direction == "long":
  257          stop = min(swing_low, level) - buf
  258          risk = entry - stop
  259          scale = config.VIVEK_TP_SCALE_LONG
  260          sign = 1
  261      else:
  262          stop = max(swing_high, level) + buf
  263          risk = stop - entry
  264          scale = config.VIVEK_TP_SCALE_SHORT
  265          sign = -1
  266  
  267      if risk <= 0:
  268          return {}
  269  
  270      struct = _structural_targets(df, direction, entry, risk)
  271      tps: list[float] = []
  272      basis: list[str] = []
  273      for i in range(3):
  274          if i < len(struct):
  275              tps.append(struct[i])
  276              basis.append("structural")
  277              continue
  278          # Fallback R-multiple, forced strictly beyond the previous TP.
  279          cand = entry + sign * risk * config.VIVEK_TP_R[i]
  280          if tps:
  281              min_next = tps[-1] + sign * risk * 0.5
  282              cand = max(cand, min_next) if direction == "long" else min(cand, min_next)
  283          tps.append(cand)
  284          basis.append("measured")
  285  
  286      # A short's price can't go below zero, so a far R-multiple fallback must not
  287      # imply a negative target. Floor short TPs at a small fraction of entry while
  288      # keeping them strictly descending.
  289      if direction == "short":
  290          floor = entry * config.VIVEK_SHORT_TP_FLOOR
  291          eps = entry * 0.001
  292          tps = [max(tps[i], floor + (2 - i) * eps) for i in range(3)]
  293  
  294      rr = round(abs(tps[1] - entry) / risk, 2)   # headline R:R to the ACTUAL TP2
  295  
  296      def rnd(v):
  297          return round(float(v), 8)
  298  
  299      return {
  300          "entry": rnd(entry),
  301          "stop": rnd(stop),
  302          "tp1": rnd(tps[0]), "tp2": rnd(tps[1]), "tp3": rnd(tps[2]),
  303          "risk": rnd(risk),
  304          "rr": rr,
  305          "direction": direction,
  306          "scale": scale,                      # fraction booked at TP1/TP2/TP3
  307          "target": rnd(tps[1]),               # generic field for shared row code
  308          "trail": rnd(entry),                 # SL→BE after TP1 (5.0 rule)
  309          "tp_basis": basis,                   # per-TP: "structural" vs "measured"
  310          "target_basis": basis[1],            # how the headline target was set
  311          "structural_tps": sum(1 for b in basis if b == "structural"),
  312      }
  313  
  314  
  315  def compute_levels(df: pd.DataFrame, sig: dict) -> dict:
  316      """Entry (= last close), SL, TP1/TP2/TP3 for a signal. Kept for callers/tests
  317      that want the detection-price plan; the live scan uses build_tf_plan (which
  318      sets the entry from the fired trigger instead)."""
  319      lv = _build_levels(df, sig["direction"], sig["close"], sig["level"],
  320                         sig["swing_low"], sig["swing_high"], sig["atr"])
  321      return lv or {"rr": 0}
  322  
  323  
  324  def _resample_weekly_ohlc(df: pd.DataFrame) -> pd.DataFrame | None:
  325      """Daily OHLCV -> a true Weekly (W-FRI) OHLCV frame, for the Weekly plan."""
  326      try:
  327          wk = pd.DataFrame({
  328              "Open":   df["Open"].resample("W-FRI").first(),
  329              "High":   df["High"].resample("W-FRI").max(),
  330              "Low":    df["Low"].resample("W-FRI").min(),
  331              "Close":  df["Close"].resample("W-FRI").last(),
  332              "Volume": df["Volume"].resample("W-FRI").sum(),
  333          }).dropna()
  334          return wk if len(wk) else None
  335      except Exception:
  336          return None
  337  
  338  
  339  def _resample_3day_ohlc(df: pd.DataFrame) -> pd.DataFrame | None:
  340      """Daily OHLCV -> a 3-Day OHLCV frame for the 3-Day plan.
  341  
  342      Bins are EPOCH-anchored 3-calendar-day buckets so they're identical to the
  343      chart's bucketBars(daily, 3·86400) — the plan, the 3-Day candles and the
  344      markers therefore line up exactly (same as the Weekly plan aligning with the
  345      chart's W-FRI resample)."""
  346      try:
  347          # "72h" (a tick-like freq) so origin="epoch" actually takes effect — a
  348          # plain "3D" silently ignores the origin and anchors to the data start.
  349          d3 = pd.DataFrame({
  350              "Open":   df["Open"].resample("72h", origin="epoch").first(),
  351              "High":   df["High"].resample("72h", origin="epoch").max(),
  352              "Low":    df["Low"].resample("72h", origin="epoch").min(),
  353              "Close":  df["Close"].resample("72h", origin="epoch").last(),
  354              "Volume": df["Volume"].resample("72h", origin="epoch").sum(),
  355          }).dropna()
  356          return d3 if len(d3) else None
  357      except Exception:
  358          return None
  359  
  360  
  361  def detect_trigger(frame: pd.DataFrame, direction: str, level: float) -> dict | None:
  362      """Has a mechanical entry trigger fired on the LAST bar of `frame`?
  363  
  364      Three triggers, checked in VIVEK_TRIGGER_PRIORITY order (first match wins):
  365        * reclaim — price pierced the 200 SMA within the lookback and the last bar
  366          closed back through it (a bounce reclaim / rejection close-through).
  367        * retest  — the last bar tagged the level and closed back the right side of
  368          it on calm (<= average) volume — a retest that held.
  369        * break   — the last bar closed beyond the most recent minor swing pivot
  370          with >= BREAK_VOL_MULT x average volume — a break of small structure.
  371  
  372      Returns {type, entry, bar} (bar = integer index of the trigger bar) or None
  373      when the setup is merely WATCHING. `entry` is the trigger price, NOT just the
  374      close — a retest enters at the level, a break enters at the broken pivot.
  375      """
  376      n = len(frame)
  377      if n < 3:
  378          return None
  379      high = frame["High"].to_numpy(dtype=float)
  380      low = frame["Low"].to_numpy(dtype=float)
  381      close = frame["Close"].to_numpy(dtype=float)
  382      vol = frame["Volume"].to_numpy(dtype=float)
  383      last = n - 1
  384      lc = close[last]
  385      is_long = direction == "long"
  386      k = min(config.VIVEK_TRIGGER_LOOKBACK, n - 1)
  387      avg_vol = float(np.nanmean(vol[-20:])) if n >= 5 else float(np.nanmean(vol) or 0.0)
  388      at_tol = level * config.VIVEK_AT_LEVEL_TOL
  389  
  390      candidates: dict[str, dict] = {}
  391  
  392      # reclaim — pierced the level recently, last bar closed back through it.
  393      if is_long:
  394          pierced = any(low[i] <= level for i in range(last - k, last + 1))
  395          if pierced and lc > level:
  396              candidates["reclaim"] = {"type": "reclaim", "entry": float(lc), "bar": last}
  397      else:
  398          pierced = any(high[i] >= level for i in range(last - k, last + 1))
  399          if pierced and lc < level:
  400              candidates["reclaim"] = {"type": "reclaim", "entry": float(lc), "bar": last}
  401  
  402      # retest — last bar tagged the level and held, on calm volume. Enter at the level.
  403      if is_long:
  404          held = low[last] <= level + at_tol and lc > level
  405      else:
  406          held = high[last] >= level - at_tol and lc < level
  407      if held and avg_vol > 0 and vol[last] <= avg_vol * config.VIVEK_RETEST_VOL_MULT:
  408          candidates["retest"] = {"type": "retest", "entry": float(level), "bar": last}
  409  
  410      # break — last bar closed beyond the most recent minor pivot with volume.
  411      piv = (pivot_highs if is_long else pivot_lows)(frame, config.VIVEK_PIVOT_WINDOW).dropna()
  412      if len(piv):
  413          brk = float(piv.iloc[-1])
  414          broke = (lc > brk) if is_long else (lc < brk)
  415          if broke and avg_vol > 0 and vol[last] >= avg_vol * config.VIVEK_BREAK_VOL_MULT:
  416              candidates["break"] = {"type": "break", "entry": brk, "bar": last}
  417  
  418      for name in config.VIVEK_TRIGGER_PRIORITY:
  419          if name in candidates:
  420              return candidates[name]
  421      return None
  422  
  423  
  424  def _recent_reaction_bar(frame: pd.DataFrame, direction: str, level: float) -> int | None:
  425      """Index of the most recent bar that reacted AT the level (within AT_LEVEL_TOL)."""
  426      n = len(frame)
  427      low = frame["Low"].to_numpy(dtype=float)
  428      high = frame["High"].to_numpy(dtype=float)
  429      for i in range(n - 1, max(-1, n - 60) - 1, -1):
  430          near = (abs(low[i] - level) / level <= config.VIVEK_AT_LEVEL_TOL) if direction == "long" \
  431              else (abs(high[i] - level) / level <= config.VIVEK_AT_LEVEL_TOL)
  432          if near:
  433              return i
  434      return None
  435  
  436  
  437  def build_tf_plan(frame: pd.DataFrame, direction: str) -> dict | None:
  438      """A full timeframe plan for `frame`: the 200 SMA level, structural SL/TPs,
  439      and the trigger state — all from ONE place (Python), so the row, chart and
  440      bot read identical numbers. Returns None when the frame is too short."""
  441      n = len(frame)
  442      if n < config.VIVEK_MIN_TF_BARS:
  443          return None
  444      close = frame["Close"]
  445      w = min(config.VIVEK_SMA, n)
  446      level = float(sma(close, w).iloc[-1])
  447      if not np.isfinite(level) or level <= 0:
  448          return None
  449      atr = float(calc_atr(frame, 14).iloc[-1])
  450      pw = config.VIVEK_PIVOT_WINDOW
  451      recent = frame.tail(max(2 * pw + 1, 12))
  452      swing_low = float(recent["Low"].min())
  453      swing_high = float(recent["High"].max())
  454  
  455      trigger = detect_trigger(frame, direction, level)
  456      entry = trigger["entry"] if trigger else float(close.iloc[-1])
  457      lv = _build_levels(frame, direction, entry, level, swing_low, swing_high, atr)
  458      if not lv:
  459          return None
  460  
  461      def _date(i):
  462          try:
  463              return frame.index[i].strftime("%Y-%m-%d")
  464          except Exception:
  465              return None
  466  
  467      react_i = _recent_reaction_bar(frame, direction, level)
  468      return {
  469          **lv,
  470          "level": round(level, 8),
  471          "swing_high": round(swing_high, 8),
  472          "swing_low": round(swing_low, 8),
  473          "sma_window": w,                                  # < 200 on short histories
  474          "armed": trigger is not None,
  475          "entry_trigger": trigger["type"] if trigger else None,
  476          "trigger_bar": _date(trigger["bar"]) if trigger else None,
  477          "reaction_bar": _date(react_i) if react_i is not None else None,
  478          "bars": n,
  479      }
  480  
  481  
  482  def build_plans(df: pd.DataFrame, sig: dict) -> dict:
  483      """Per-timeframe plans for a signal's direction. The Daily plan is the row/bot
  484      headline; the 3-Day and Weekly plans each get their OWN 200-SMA reaction so
  485      the chart's 3D and W toggles surface real setups (not a Daily reference)."""
  486      direction = sig["direction"]
  487      plans: dict[str, dict] = {}
  488      p1d = build_tf_plan(df, direction)
  489      if p1d:
  490          plans["1D"] = p1d
  491      d3 = _resample_3day_ohlc(df)
  492      if d3 is not None:
  493          p3d = build_tf_plan(d3, direction)
  494          if p3d:
  495              plans["3D"] = p3d
  496      wk = _resample_weekly_ohlc(df)
  497      if wk is not None:
  498          p1w = build_tf_plan(wk, direction)
  499          if p1w:
  500              plans["1W"] = p1w
  501      return plans
  502  
  503  
  504  def build_markers(plans: dict) -> dict:
  505      """Chart markers per timeframe, derived from the plans so the chart no longer
  506      computes its own. At most two per TF (the reaction at the level + the trigger
  507      bar) — deliberately minimal to keep the chart readable."""
  508      out: dict[str, list] = {}
  509      for tf, p in plans.items():
  510          ms = []
  511          if p.get("reaction_bar"):
  512              ms.append({"date": p["reaction_bar"], "kind": "reaction"})
  513          if p.get("trigger_bar"):
  514              ms.append({"date": p["trigger_bar"], "kind": "trigger", "label": p.get("entry_trigger")})
  515          out[tf] = ms
  516      return out
  517  
  518  
  519  def gate_grade(grade: str | None, sig: dict, rr: float, armed: bool = True) -> tuple[str | None, list[str]]:
  520      """Apply 5.0's hard requirements the raw structural score can't see.
  521  
  522      A tradeable grade (A+/A) needs BOTH a fired trigger (ARMED — not price merely
  523      sitting near the SMA) AND enough room to TP2. Otherwise the setup is demoted
  524      to B+ (WATCHING) with a chip explaining why. This keeps the A+/A list short
  525      and genuinely actionable.
  526      """
  527      if grade not in ("A+", "A"):
  528          return grade, []
  529      notes: list[str] = []
  530      if not armed:
  531          grade = "B+"
  532          notes.append("WATCHING (no trigger)")
  533      if rr < config.VIVEK_MIN_TRADEABLE_RR:
  534          grade = "B+"
  535          notes.append(f"LOW R:R ({rr:.1f})")
  536      return grade, notes
  537  
  538  
  539  def apply_grade_hysteresis(score: int, raw_grade: str | None, prev_grade: str | None,
  540                             cutoffs: list | None = None, margin: int | None = None) -> str | None:
  541      """Hold a setup's PREVIOUS (higher) grade across scans unless its score has
  542      clearly dropped — i.e. more than `margin` points below that grade's cutoff.
  543  
  544      This only smooths SCORE-boundary wobble (the A+↔A flip-flop from tiny
  545      scan-to-scan data differences); it is applied BEFORE gate_grade, so a genuine
  546      state change (un-armed, or R:R falling below the minimum) still demotes the
  547      setup. Promotions are never held back. A no-op when there's no prior grade.
  548      """
  549      cutoffs = config.VIVEK_GRADE_CUTOFFS if cutoffs is None else cutoffs
  550      margin = config.VIVEK_GRADE_HYSTERESIS if margin is None else margin
  551      if not prev_grade or prev_grade == raw_grade or margin <= 0:
  552          return raw_grade
  553      rank = {g: i for i, (g, _) in enumerate(cutoffs)}   # A+ = 0 (best)
  554      cut = dict(cutoffs)
  555      if prev_grade not in rank or raw_grade not in rank:
  556          return raw_grade
  557      # Only a demotion (raw is a worse tier than prev) is eligible to be held, and
  558      # only while the score is still within `margin` of the previous grade's cutoff.
  559      if rank[raw_grade] > rank[prev_grade] and score >= cut[prev_grade] - margin:
  560          return prev_grade
  561      return raw_grade
  562  
  563  
  564  # Entry-type categories — how price is interacting with the 200 SMA. Used by the
  565  # dashboard's filter chips so the user can sort setups by the trade trigger and
  566  # read overall market behaviour around the level. A setup can match more than one.
  567  ENTRY_TYPES = ["reclaim", "retest", "break"]
  568  ENTRY_TYPE_LABELS = {
  569      "reclaim": "Close back above 200 SMA after rejection",
  570      "retest":  "Retest with confirmation",
  571      "break":   "Break of small structure near 200 SMA",
  572  }
  573  
  574  
  575  def entry_types(sig: dict) -> list[str]:
  576      """Classify a 200-SMA interaction into one or more entry types (heuristic).
  577  
  578      * reclaim — a clean reaction at the level: price was pushed to the 200 SMA and
  579        closed back through it (bounce off support / rejection at resistance).
  580      * retest  — price is sitting right AT the level and holding, with confirming
  581        structure (a retest that held).
  582      * break   — recent swings are stacking strongly in the trade's direction near
  583        the level (a break of small structure / momentum entry).
  584      """
  585      react = sig.get("reaction")
  586      at = bool(sig.get("at_level"))
  587      struct = sig.get("structure", 0) or 0
  588      types: list[str] = []
  589      if react in ("bounce", "reject"):
  590          types.append("reclaim")
  591      if at and struct >= 0.5:
  592          types.append("retest")
  593      if struct >= 0.8:
  594          types.append("break")
  595      if not types:                      # every setup is near the level — default to retest
  596          types.append("retest")
  597      return types
  598  
  599  
  600  def build_detail(df: pd.DataFrame, sig: dict, lv: dict) -> dict:
  601      """Detail payload for the VIVEK ticker view."""
  602      return {
  603          "setup_type": "vivek",
  604          "level_tf": sig["level_tf"],
  605          "level": sig["level"],
  606          "weekly_sma200": sig["weekly_sma200"],
  607          "daily_sma200": sig["daily_sma200"],
  608          "dist_pct": sig["dist_pct"],
  609          "at_level": sig["at_level"],
  610          "reaction": sig["reaction"],
  611          "structure": sig["structure"],
  612          "confluence": sig["confluence"],
  613          "weekly_bars": sig["weekly_bars"],
  614          "atr": sig["atr"],
  615          "entry": lv.get("entry"), "stop": lv.get("stop"),
  616          "tp1": lv.get("tp1"), "tp2": lv.get("tp2"), "tp3": lv.get("tp3"),
  617          "scale": lv.get("scale"),
  618          "risk": lv.get("risk"),
  619          "tp_basis": lv.get("tp_basis"),
  620          "structural_tps": lv.get("structural_tps"),
  621          "rr": lv.get("rr"),
  622      }
  623  
  624  
  625  def narrative(symbol: str, sig: dict, lv: dict, detail: dict, currency_symbol: str = "$") -> str:
  626      """Plain-English explanation of the setup and why it earned its grade."""
  627      cur = currency_symbol
  628      tf = {"weekly": "Weekly", "3d": "3-Day"}.get(sig["level_tf"], "H4 (daily proxy)")
  629      side = "long" if sig["direction"] == "long" else "short"
  630      react = {
  631          "bounce": "bouncing off", "hold": "holding above",
  632          "reject": "being rejected at", "fade": "fading below",
  633      }.get(sig["reaction"], "reacting at")
  634      conf = " with Weekly+H4 200 SMA confluence" if sig["confluence"] else ""
  635      struct = ("a clean structure" if sig["structure"] >= 0.8
  636                else "a workable structure" if sig["structure"] >= 0.5
  637                else "thin structure")
  638      sc = lv.get("scale") or []
  639      sc_txt = " / ".join(f"{int(round(x*100))}%" for x in sc) if sc else "—"
  640      n_struct = lv.get("structural_tps") or 0
  641      where = "prior resistance" if side == "long" else "prior support"
  642      tgt_txt = (f"targets set at {where} ({n_struct}/3 from real structure)"
  643                 if n_struct else "targets set by R-multiples (no clear structure nearby)")
  644      return (
  645          f"{symbol} is {react} the {tf} 200 SMA ({cur}{sig['level']:.4f}), "
  646          f"{abs(sig['dist_pct']):.1f}% away{conf}, with {struct}. "
  647          f"A {side} reaction setup: enter {cur}{lv['entry']:.4f}, stop {cur}{lv['stop']:.4f} "
  648          f"(beyond the reaction); {tgt_txt}. Scale {sc_txt} into TP1 {cur}{lv['tp1']:.4f} / "
  649          f"TP2 {cur}{lv['tp2']:.4f} / TP3 {cur}{lv['tp3']:.4f}; move SL to break-even at TP1, "
  650          f"then below new support at TP2. {lv['rr']:.1f}R to TP2."
  651      )
```

### `scanner/scan.py`  (252 lines)
> Per-market orchestration: row build, grade HYSTERESIS, armed/R:R gate off the 1D plan, write <m>_vivek.json.
```python
    1  """Orchestration for the VIVEK scan: download -> 200-SMA reaction -> trigger ->
    2  per-timeframe plan -> grade -> rank, per market."""
    3  
    4  import datetime as dt
    5  import json
    6  import logging
    7  import os
    8  import pathlib
    9  import subprocess
   10  from collections import Counter
   11  from zoneinfo import ZoneInfo
   12  
   13  from . import config, pulse
   14  from .data import download, _frame_age_days
   15  from .universe import load_universe
   16  
   17  log = logging.getLogger(__name__)
   18  
   19  
   20  def _code_sha() -> str:
   21      """Short commit SHA the scan ran at, stamped into output so the frontend can
   22      tell whether the data was produced by the current build. GITHUB_SHA is set in
   23      Actions; fall back to a local `git rev-parse` for manual runs."""
   24      sha = os.environ.get("GITHUB_SHA")
   25      if sha:
   26          return sha[:7]
   27      try:
   28          out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
   29                               capture_output=True, text=True, timeout=3,
   30                               cwd=pathlib.Path(__file__).resolve().parents[1])
   31          return out.stdout.strip() if out.returncode == 0 else ""
   32      except Exception:
   33          return ""
   34  
   35  
   36  def _liquidity(df, market) -> float:
   37      # Crypto: Yahoo "Volume" is already USD dollar-volume; stocks: price * shares.
   38      if getattr(market, "volume_is_usd", False):
   39          return float(df["Volume"].iloc[-config.LIQUIDITY_LOOKBACK:].mean())
   40      turnover = (df["Close"] * df["Volume"]).iloc[-config.LIQUIDITY_LOOKBACK:].mean()
   41      return float(turnover)
   42  
   43  
   44  def _spark(df) -> list[float]:
   45      closes = df["Close"].iloc[-config.SPARK_BARS:].tolist()
   46      return [round(float(c), 8) for c in closes]
   47  
   48  
   49  def _load_prev_grades(out_root: str | None, market_key: str) -> dict:
   50      """{symbol: grade} from the PREVIOUS scan's JSON (read before it's overwritten)
   51      so grade hysteresis can hold a borderline name's prior grade across scans."""
   52      if not out_root:
   53          return {}
   54      p = pathlib.Path(out_root) / f"{market_key}_vivek.json"
   55      try:
   56          data = json.loads(p.read_text(encoding="utf-8"))
   57          return {r["symbol"]: r["grade"] for r in data.get("results", [])
   58                  if r.get("symbol") and r.get("grade")}
   59      except Exception:
   60          return {}
   61  
   62  
   63  def _bar_is_forming(market_key: str, last_date, now: dt.datetime) -> bool:
   64      """Is the trailing daily bar still forming (the current session's incomplete
   65      bar)? True only when the last bar is TODAY in the market tz and today's session
   66      has not yet closed; crypto (no session) forms until UTC midnight (all day)."""
   67      if last_date != now.date():
   68          return False                       # a prior, completed day's bar
   69      sess = config.VIVEK_JOURNAL_SESSION.get(market_key)
   70      if not sess:
   71          return True                        # crypto: today's bar forms until UTC midnight
   72      ch, cm = sess[2], sess[3]
   73      return (now.hour * 60 + now.minute) < (ch * 60 + cm)
   74  
   75  
   76  # VIVEK grade ordering (A+/A/B+/WATCH).
   77  _VIVEK_RANK = {"A+": 0, "A": 1, "B+": 2, "WATCH": 3}
   78  
   79  
   80  def scan_vivek_market(market_key: str, limit: int | None = None, full: bool = True,
   81                        out_root: str | None = None, progress: bool = True,
   82                        universe: list | None = None,
   83                        frames: dict | None = None,
   84                        pulse_data: list | None = None,
   85                        from_cache: int = 0) -> dict:
   86      """VIVEK (5.0-style) scan: 200 SMA reactions on the higher timeframes.
   87  
   88      Uses a long (VIVEK_DATA_PERIOD) daily history so a real Weekly 200 SMA can be
   89      computed. Produces rows carrying Entry / SL / TP1 / TP2 / TP3 + scale-outs and
   90      an A+/A/B+/WATCH grade with a plain-English reason.
   91  
   92      `frames` (deep daily history) may be passed in by the caller to AVOID a second
   93      Yahoo download — the runner already pulls this market's 5y history for the
   94      daily scanners, so VIVEK reuses it instead of fetching the same data again.
   95      """
   96      from . import vivek
   97      market = config.MARKETS[market_key]
   98      liquid_tier = config.LIQUID_TIER.get(market_key, float("inf"))
   99      if universe is None:
  100          universe = load_universe(market_key, full=full)
  101          if limit:
  102              universe = universe[:limit]
  103      meta = {u["yf"]: u for u in universe}
  104  
  105      if frames is None:
  106          if progress:
  107              print(f"  downloading {len(universe)} {market.label} tickers "
  108                    f"({config.VIVEK_DATA_PERIOD}) for VIVEK ...", flush=True)
  109          frames = download([u["yf"] for u in universe], period=config.VIVEK_DATA_PERIOD)
  110  
  111      now = dt.datetime.now(ZoneInfo(market.timezone))
  112      prev_grades = _load_prev_grades(out_root, market_key)   # for grade hysteresis
  113  
  114      results: list[dict] = []
  115      prices: dict[str, float] = {}        # last close for EVERY scanned symbol
  116      scanned = 0
  117      for yf_ticker, df in frames.items():
  118          scanned += 1
  119          symbol = meta.get(yf_ticker, {}).get("symbol", yf_ticker)
  120          # Snapshot the latest close for the whole universe (not just setups), so
  121          # the journal can price any open position — including held names that are
  122          # no longer a current setup — straight from the scan, every run.
  123          try:
  124              if len(df):
  125                  prices[symbol] = round(float(df["Close"].iloc[-1]), 8)
  126          except Exception:
  127              pass
  128          try:
  129              age = _frame_age_days(df)                        # measure freshness on the raw frame
  130              # Pin to COMPLETED bars: drop a still-forming trailing bar so a name's
  131              # grade/plan doesn't wobble as the current session's bar fills in.
  132              if (config.VIVEK_DROP_FORMING_BAR and len(df)
  133                      and _bar_is_forming(market_key, df.index[-1].date(), now)):
  134                  df = df.iloc[:-1]
  135              sig = vivek.evaluate(df)
  136              if sig is None:
  137                  continue
  138              turnover = _liquidity(df, market)
  139              if turnover < market.liquidity_min:
  140                  continue
  141              points, grade, fired = vivek.score_and_grade(sig)
  142              if grade is None:
  143                  continue
  144              # Hysteresis: hold the prior (higher) grade through small score wobble.
  145              # Applied BEFORE the gate so a genuine un-arm / low-R:R still demotes.
  146              grade = vivek.apply_grade_hysteresis(points, grade, prev_grades.get(symbol))
  147              # Per-timeframe plans (Daily + Weekly) from the ONE engine — the Daily
  148              # plan is the row/bot headline; both feed the chart so the row, chart
  149              # and bot read identical numbers. The Daily plan also carries the
  150              # trigger state (armed / entry_trigger / trigger_bar).
  151              plans = vivek.build_plans(df, sig)
  152              lv = plans.get("1D")
  153              if not lv or lv.get("rr", 0) <= 0:
  154                  continue
  155              armed = bool(lv.get("armed"))
  156              markers = vivek.build_markers(plans)
  157              # Selectivity gate: only ARMED setups (a trigger fired) earn A/A+;
  158              # otherwise the setup is WATCHING and capped at B+. Also demote on low
  159              # R:R. Keeps the tradeable list short and genuinely actionable.
  160              grade, gate_notes = vivek.gate_grade(grade, sig, lv["rr"], armed)
  161              fired = fired + gate_notes
  162              # Entry-type chips reflect the FIRED trigger when armed; fall back to
  163              # the descriptive heuristic for watching setups.
  164              entry_types = ([lv["entry_trigger"]] if armed and lv.get("entry_trigger")
  165                             else vivek.entry_types(sig))
  166  
  167              info = meta.get(yf_ticker, {})
  168              close = sig["close"]
  169              detail = vivek.build_detail(df, sig, lv)
  170              is_long = sig["direction"] == "long"
  171              results.append({
  172                  "symbol": info.get("symbol", yf_ticker),
  173                  "name": info.get("name", yf_ticker),
  174                  "sector": info.get("sector", ""),
  175                  "dir": "LONG" if is_long else "SHORT",
  176                  "setup_type": "vivek",
  177                  "grade": grade,
  178                  "score": points,
  179                  "score_max": config.VIVEK_SCORE_MAX,
  180                  "chips": fired,
  181                  "level_tf": sig["level_tf"],
  182                  "level": sig["level"],
  183                  "at_level": sig["at_level"],
  184                  "reaction": sig["reaction"],
  185                  "entry_types": entry_types,
  186                  "armed": armed,
  187                  "entry_trigger": lv.get("entry_trigger"),
  188                  "trigger_bar": lv.get("trigger_bar"),
  189                  "plans": plans,
  190                  "markers": markers,
  191                  "confluence": sig["confluence"],
  192                  "price": round(close, 8),
  193                  "entry": lv["entry"], "stop": lv["stop"],
  194                  "tp1": lv["tp1"], "tp2": lv["tp2"], "tp3": lv["tp3"],
  195                  "scale": lv["scale"], "risk": lv["risk"],
  196                  "rr": lv["rr"],
  197                  "rr_text": f"{lv['rr']:.1f}:1",
  198                  "liquidity": "LIQUID" if turnover >= liquid_tier else "OK",
  199                  "turnover": round(turnover),
  200                  "data_age_days": age,   # 0 = fresh; >0 = reused cache (raw-frame age)
  201                  "spark": _spark(df),
  202                  "detail": detail,
  203                  "analysis": vivek.narrative(info.get("symbol", yf_ticker), sig, lv,
  204                                              detail, market.currency_symbol),
  205              })
  206          except Exception as e:
  207              if progress:
  208                  print(f"  warning: VIVEK {yf_ticker} → {e}", flush=True)
  209  
  210      # Rank by VIVEK grade, then score, then R:R.
  211      counts = _finalize_vivek(results)
  212      if pulse_data is None:
  213          # PULSE retired from the UI 2026-07-03; stopped fetching 2026-07-09 —
  214          # it was still hitting Yahoo for macro quotes on every scheduled scan.
  215          # Restore by swapping [] back to pulse.fetch().
  216          pulse_data = []
  217      downloaded = len(frames)
  218      return {
  219          "market": market.key,
  220          "label": market.label,
  221          "setup_type": "vivek",
  222          # Freshness + version stamp so the UI can show data age / coverage and
  223          # detect when committed data is a build behind the running code, instead
  224          # of silently hiding features that depend on newer fields.
  225          "schema_version": config.VIVEK_SCHEMA_VERSION,
  226          "code_sha": _code_sha(),
  227          "currency": market.currency,
  228          "currency_symbol": market.currency_symbol,
  229          "timezone": market.timezone,
  230          "tz_label": market.tz_label,
  231          "generated_at": now.isoformat(timespec="seconds"),
  232          "scanned": scanned,
  233          "downloaded": downloaded,
  234          "from_cache": from_cache,                 # tickers reused from last-good cache
  235          "fresh": max(0, downloaded - from_cache),
  236          "universe_size": len(universe),
  237          "coverage_pct": round(100 * downloaded / max(len(universe), 1)),
  238          "score_max": config.VIVEK_SCORE_MAX,
  239          "sma": config.VIVEK_SMA,
  240          "sector_counts": dict(counts.most_common()),
  241          "pulse": pulse_data,
  242          "results": results,
  243          "prices": prices,                 # universe-wide last-close snapshot
  244      }
  245  
  246  
  247  def _finalize_vivek(results: list[dict]) -> Counter:
  248      counts = Counter(r["sector"] for r in results if r["sector"])
  249      for r in results:
  250          r["sector_count"] = counts.get(r["sector"], 0)
  251      results.sort(key=lambda r: (_VIVEK_RANK.get(r["grade"], 9), -r["score"], -r["rr"]))
  252      return counts
```


## === C3. BACKTEST + TRADE-MANAGEMENT PRIMITIVES ===

### `scanner/vivek_journal.py`  (372 lines)
> Shared trade-management primitives (_snapshot/_mark/_apply_costs/_r_of/costs_for) used by BOTH the backtester and the live bot. P&L math.
```python
    1  """VIVEK-native paper-trade journal — realistic intraday forward test.
    2  
    3  This measures the trigger-based system the way it would actually be traded:
    4  
    5    * Trades are only OPENED during the live (delayed) market session — ASX
    6      10:00–16:00 AEST shifted +15 min for the ~15-min feed delay, etc.
    7    * Entry is the DELAYED INTRADAY PRICE at the moment the setup is taken during
    8      the session — not the historical trigger-bar close. The structural stop and
    9      TP1/TP2/TP3 come from the same per-timeframe plan the row/chart/bot use.
   10    * Every market-hours scan then marks each open trade to the observed intraday
   11      price: it books a scale-out when price reaches a TP, moves the SL by the 5.0
   12      rules (BE at TP1, locked structure at TP2, never adverse), and closes at the
   13      observed price when the stop is hit. MAE/MFE and realized R are recorded.
   14  
   15  So entries and exits both use the delayed intraday prices a manual trader would
   16  actually see and act on — there is no look-ahead into a daily bar's full range.
   17  
   18  Single source of truth: it consumes the SAME per-timeframe plans the row, chart
   19  and bot use (row["plans"][tf]) — it never recomputes a level.
   20  """
   21  
   22  import datetime as dt
   23  import json
   24  import logging
   25  import pathlib
   26  from zoneinfo import ZoneInfo
   27  
   28  from . import config
   29  from .broker.vivek_bot import manage_position, _is_fund_or_reit
   30  from .journal_common import atomic_write
   31  
   32  log = logging.getLogger(__name__)
   33  
   34  ROOT = pathlib.Path(__file__).resolve().parents[1]
   35  JOURNAL_FILE = ROOT / "journal" / "vivek_journal.json"
   36  PUBLIC_FILE = ROOT / "public" / "data" / "vivek_journal.json"
   37  
   38  JOURNAL_VERSION = 2                 # v2 = intraday entry/exit pricing + market-hours gate
   39  TIMEFRAMES = ("1D", "1W")          # 4H is browser-only (no server-side intraday)
   40  MAX_CLOSED = 4000
   41  
   42  
   43  # ── execution-cost model (fees + slippage) ───────────────────────────────────
   44  # Costs are modelled as an R-drag derived from a trade's own fills, so prices
   45  # (and therefore the gross R mechanics + their tests) are untouched and only the
   46  # NET realized_r reflects the drag. Pass costs=None to run cost-free.
   47  
   48  def costs_for(market: str | None) -> tuple[float, float] | None:
   49      """(slippage_frac, commission_frac) for a market, or None when costs are off."""
   50      if not getattr(config, "VIVEK_COSTS_ENABLED", False):
   51          return None
   52      slip = config.VIVEK_SLIPPAGE_BPS.get(market, config.VIVEK_SLIPPAGE_BPS["default"])
   53      comm = config.VIVEK_COMMISSION_BPS.get(market, config.VIVEK_COMMISSION_BPS["default"])
   54      return (slip / 10_000.0, comm / 10_000.0)
   55  
   56  
   57  def _cost_r(trade: dict, slip_frac: float, comm_frac: float) -> float:
   58      """Round-trip cost of a trade expressed in R (risk multiples).
   59  
   60      Entry is a market fill → pays slippage + commission on the full position.
   61      Each exit pays commission on its booked fraction; only a market exit (a stop
   62      or trailed close) also pays slippage — a resting TP limit fills at its level.
   63      """
   64      entry, risk = trade.get("entry"), trade.get("risk")
   65      if not risk or risk <= 0 or not entry:
   66          return 0.0
   67      cost_price = entry * (slip_frac + comm_frac)                  # entry: full size, market
   68      for ex in trade.get("exits", []):
   69          frac = ex.get("pct", 0.0)
   70          px = ex.get("price", entry)
   71          # TP limits pay no slippage; stop + time-stop closes are market fills.
   72          is_market = str(ex.get("reason", "")).startswith(("stop", "time"))
   73          cost_price += frac * px * (comm_frac + (slip_frac if is_market else 0.0))
   74      return cost_price / risk
   75  
   76  
   77  def _apply_costs(trade: dict, costs: tuple[float, float] | None) -> None:
   78      """Set gross_r / cost_r / net realized_r on the trade from its accumulated R."""
   79      gross = trade.get("gross_r", trade.get("realized_r", 0.0))
   80      trade["gross_r"] = round(gross, 4)
   81      trade["cost_r"] = round(_cost_r(trade, *costs), 4) if costs else 0.0
   82      trade["realized_r"] = round(trade["gross_r"] - trade["cost_r"], 4)
   83  
   84  
   85  def _load() -> dict:
   86      if JOURNAL_FILE.exists():
   87          try:
   88              j = json.loads(JOURNAL_FILE.read_text(encoding="utf-8"))
   89              j.setdefault("open", [])
   90              j.setdefault("closed", [])
   91              return j
   92          except Exception:
   93              # A corrupt/half-written file must never crash the run or be silently
   94              # overwritten — park it for inspection and start from a clean book.
   95              try:
   96                  bad = JOURNAL_FILE.with_suffix(".corrupt.json")
   97                  JOURNAL_FILE.replace(bad)
   98                  log.warning("vivek journal corrupt — parked at %s, starting fresh", bad.name)
   99              except Exception:
  100                  pass
  101      return {"version": JOURNAL_VERSION, "open": [], "closed": []}
  102  
  103  
  104  def _save(j: dict) -> None:
  105      j["version"] = JOURNAL_VERSION
  106      j["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
  107      if len(j["closed"]) > MAX_CLOSED:
  108          j["closed"] = j["closed"][-MAX_CLOSED:]
  109      j["expectancy"] = expectancy(j["closed"])
  110      payload = json.dumps(j, indent=2)
  111      atomic_write(JOURNAL_FILE, payload)
  112      atomic_write(PUBLIC_FILE, payload)
  113  
  114  
  115  def _trade_id(symbol: str, direction: str, tf: str, entry_day: str) -> str:
  116      return f"{symbol}:{direction}:{tf}:{entry_day}"
  117  
  118  
  119  def market_open(market_key: str, now: dt.datetime) -> bool:
  120      """Is `market_key` inside its delay-adjusted trading session at `now`?
  121  
  122      `now` must be timezone-aware in the market's own timezone. Crypto (session
  123      None) is always open; stock markets are closed on weekends.
  124      """
  125      if not config.VIVEK_JOURNAL_MARKET_HOURS:
  126          return True
  127      sess = config.VIVEK_JOURNAL_SESSION.get(market_key)
  128      if sess is None:
  129          return True                                  # 24/7 (crypto)
  130      if now.weekday() >= 5:
  131          return False                                 # weekend
  132      oh, om, ch, cm = sess
  133      delay = config.VIVEK_JOURNAL_FEED_DELAY_MIN
  134      open_min = oh * 60 + om + delay
  135      close_min = ch * 60 + cm + delay
  136      cur = now.hour * 60 + now.minute
  137      return open_min <= cur <= close_min
  138  
  139  
  140  def _r_of(price, entry, risk, is_long):
  141      return (price - entry) / risk if is_long else (entry - price) / risk
  142  
  143  
  144  def _snapshot(row: dict, tf: str, plan: dict, market: str,
  145                entry_price: float, day: str) -> dict | None:
  146      """Open a paper trade at the current delayed intraday price.
  147  
  148      Returns None to "not chase" — when the move has already played out (price at
  149      or beyond TP1) or the entry would be on the wrong side of the stop.
  150      """
  151      direction = "short" if str(row.get("dir", "LONG")).upper() == "SHORT" else "long"
  152      is_long = direction == "long"
  153      stop = plan["stop"]
  154      tp1, tp2, tp3 = plan["tp1"], plan["tp2"], plan["tp3"]
  155      if is_long:
  156          if entry_price <= stop or entry_price >= tp1:
  157              return None
  158      else:
  159          if entry_price >= stop or entry_price <= tp1:
  160              return None
  161      risk = abs(entry_price - stop)
  162      if risk <= 0:
  163          return None
  164      entry_type = plan.get("entry_trigger") or (row.get("entry_types") or [None])[0]
  165      return {
  166          "id": _trade_id(row["symbol"], direction, tf, day),
  167          "symbol": row["symbol"], "name": row.get("name", row["symbol"]),
  168          "sector": row.get("sector", ""), "market": market,
  169          "direction": direction, "grade": row["grade"], "entry_type": entry_type,
  170          "timeframe": tf,
  171          "entry": round(entry_price, 8), "stop": stop,
  172          "tp1": tp1, "tp2": tp2, "tp3": tp3,
  173          "scale": plan["scale"], "risk": round(risk, 8),
  174          "rr": round(abs(tp2 - entry_price) / risk, 2),
  175          "trigger_bar": plan.get("trigger_bar"),       # the bar the trigger fired on (reference)
  176          "entry_date": day, "opened_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
  177          "status": "open",
  178          "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
  179          "booked_pct": 0.0, "realized_r": 0.0, "gross_r": 0.0, "cost_r": 0.0, "exits": [],
  180          "mae": round(entry_price, 8), "mfe": round(entry_price, 8),
  181          "mae_r": 0.0, "mfe_r": 0.0,
  182      }
  183  
  184  
  185  def _mark(trade: dict, price: float, day: str, costs: tuple[float, float] | None = None) -> None:
  186      """Mark an open trade to the observed intraday `price` for this scan.
  187  
  188      Single-price observation (no intrabar range), so there's no ambiguity: at
  189      most one of {stop, TP scale-outs} resolves per scan. Books TPs at the TP
  190      level (a resting limit), closes the stop at the observed price (so an
  191      overnight gap fills at the gapped price), and moves the SL by the 5.0 rules.
  192  
  193      `costs` = (slippage_frac, commission_frac) applies the execution-cost R-drag
  194      so realized_r is reported NET (gross_r/cost_r are kept alongside). None = off.
  195      """
  196      is_long = trade["direction"] == "long"
  197      entry, risk = trade["entry"], trade["risk"]
  198      if risk <= 0:
  199          return
  200      # Accumulate gross R here; costs are applied to derive the net realized_r.
  201      trade.setdefault("gross_r", trade.get("realized_r", 0.0))
  202      # running MAE/MFE from the prices we actually observe
  203      trade["mfe"] = max(trade["mfe"], price) if is_long else min(trade["mfe"], price)
  204      trade["mae"] = min(trade["mae"], price) if is_long else max(trade["mae"], price)
  205  
  206      pos = {"symbol": trade["symbol"], "direction": trade["direction"], "entry": entry,
  207             "stop": trade["stop"], "tp1": trade["tp1"], "tp2": trade["tp2"],
  208             "tp3": trade["tp3"], "scale": trade["scale"],
  209             "tp1_hit": trade["tp1_hit"], "tp2_hit": trade["tp2_hit"], "tp3_hit": trade["tp3_hit"]}
  210  
  211      stop_hit = price <= pos["stop"] if is_long else price >= pos["stop"]
  212      if stop_hit:
  213          remaining = round(1.0 - trade["booked_pct"], 6)
  214          if remaining > 1e-9:
  215              trade["exits"].append({"reason": "stop", "price": round(price, 8), "pct": remaining, "date": day})
  216              trade["gross_r"] = round(trade["gross_r"] + remaining * _r_of(price, entry, risk, is_long), 4)
  217              trade["booked_pct"] = 1.0
  218          trade["status"] = "closed"
  219          trade["exit_price"] = round(price, 8)
  220          trade["exit_date"] = day
  221          trade["exit_reason"] = ("target" if pos["tp3_hit"]
  222                                  else "trail" if pos["tp1_hit"] else "stop")
  223      else:
  224          for a in manage_position(pos, price):          # books TPs reached + moves SL
  225              if a["action"] == "scale":
  226                  name = a["tp"].lower()
  227                  pct, px = a["book_pct"], pos[name]
  228                  trade["exits"].append({"reason": name, "price": px, "pct": pct, "date": day})
  229                  trade["gross_r"] = round(trade["gross_r"] + pct * _r_of(px, entry, risk, is_long), 4)
  230                  trade["booked_pct"] = round(trade["booked_pct"] + pct, 6)
  231          trade["tp1_hit"], trade["tp2_hit"], trade["tp3_hit"] = pos["tp1_hit"], pos["tp2_hit"], pos["tp3_hit"]
  232          trade["stop"] = pos["stop"]
  233  
  234      # Derive the NET realized_r from accumulated gross R minus execution costs.
  235      _apply_costs(trade, costs)
  236      trade["mae_r"] = round(_r_of(trade["mae"], entry, risk, is_long), 3)
  237      trade["mfe_r"] = round(_r_of(trade["mfe"], entry, risk, is_long), 3)
  238      if trade["status"] == "closed":
  239          try:
  240              d0 = dt.date.fromisoformat(trade["entry_date"])
  241              d1 = dt.date.fromisoformat(trade["exit_date"])
  242              trade["hold_days"] = (d1 - d0).days
  243          except Exception:
  244              trade["hold_days"] = None
  245  
  246  
  247  def _stats(trades: list[dict]) -> dict:
  248      n = len(trades)
  249      if not n:
  250          return {"n": 0, "win_rate": 0.0, "expectancy_r": 0.0, "total_r": 0.0,
  251                  "avg_win_r": 0.0, "avg_loss_r": 0.0, "avg_hold_days": 0.0,
  252                  "avg_mae_r": 0.0, "avg_mfe_r": 0.0,
  253                  "gross_expectancy_r": 0.0, "avg_cost_r": 0.0}
  254      rs = [t.get("realized_r", 0.0) for t in trades]
  255      wins = [r for r in rs if r > 0]
  256      losses = [r for r in rs if r <= 0]
  257      holds = [t["hold_days"] for t in trades if t.get("hold_days") is not None]
  258      maes = [t["mae_r"] for t in trades if t.get("mae_r") is not None]
  259      mfes = [t["mfe_r"] for t in trades if t.get("mfe_r") is not None]
  260      # Net (realized_r) is the headline; gross/cost expose the execution-cost drag.
  261      gross = [t.get("gross_r", t.get("realized_r", 0.0)) for t in trades]
  262      cost = [t.get("cost_r", 0.0) for t in trades]
  263      return {
  264          "n": n,
  265          "win_rate": round(100 * len(wins) / n, 1),
  266          "expectancy_r": round(sum(rs) / n, 3),
  267          "total_r": round(sum(rs), 2),
  268          "avg_win_r": round(sum(wins) / len(wins), 3) if wins else 0.0,
  269          "avg_loss_r": round(sum(losses) / len(losses), 3) if losses else 0.0,
  270          "avg_hold_days": round(sum(holds) / len(holds), 1) if holds else 0.0,
  271          "avg_mae_r": round(sum(maes) / len(maes), 3) if maes else 0.0,
  272          "avg_mfe_r": round(sum(mfes) / len(mfes), 3) if mfes else 0.0,
  273          "gross_expectancy_r": round(sum(gross) / n, 3),
  274          "avg_cost_r": round(sum(cost) / n, 3),
  275      }
  276  
  277  
  278  def expectancy(closed: list[dict]) -> dict:
  279      """Expectancy overall and split by grade, entry_type and timeframe."""
  280      def split(key, values):
  281          return {v: _stats([t for t in closed if t.get(key) == v]) for v in values}
  282      return {
  283          "overall": _stats(closed),
  284          "by_grade": split("grade", ["A+", "A"]),
  285          "by_entry_type": split("entry_type", config.VIVEK_TRIGGER_PRIORITY),
  286          "by_timeframe": split("timeframe", ["1D", "1W", "4H"]),
  287      }
  288  
  289  
  290  def _current_price(frames: dict, yf_ticker: str | None):
  291      df = frames.get(yf_ticker) if yf_ticker else None
  292      if df is None or len(df) == 0:
  293          return None
  294      try:
  295          return float(df["Close"].iloc[-1])
  296      except Exception:
  297          return None
  298  
  299  
  300  def update(market: str, results: list[dict], frames: dict, universe: list[dict],
  301             now: dt.datetime | None = None) -> dict:
  302      """Open newly-armed A/A+ setups at the current intraday price (market hours
  303      only), mark this market's open trades to the observed price, and save.
  304  
  305      `frames` is the deep daily history keyed by yfinance ticker — its last bar's
  306      close is the latest (delayed) price during the session. `now` is injectable
  307      for testing; it defaults to the market's local wall clock.
  308      """
  309      mkt = config.MARKETS[market]
  310      if now is None:
  311          now = dt.datetime.now(ZoneInfo(mkt.timezone))
  312      day = now.strftime("%Y-%m-%d")
  313      is_open = market_open(market, now)
  314      costs = costs_for(market)                         # fees + slippage R-drag (None = off)
  315  
  316      j = _load()
  317      known = {t["id"] for t in j["open"]} | {t["id"] for t in j["closed"]}
  318      open_keys = {(t["symbol"], t["direction"], t["timeframe"])
  319                   for t in j["open"] if t.get("market") == market}
  320      yf_map = {u["symbol"]: u["yf"] for u in universe}
  321  
  322      # 1) open new ARMED A/A+ setups at the current intraday price (session only).
  323      added = 0
  324      if is_open:
  325          for row in results:
  326              if row.get("grade") not in ("A+", "A"):
  327                  continue
  328              # Keep the forward-test to the same tradeable universe as the bot —
  329              # don't let REIT/ETF/fund reactions pad the signal's expectancy.
  330              if getattr(config, "VIVEK_BOT_EXCLUDE_FUNDS", True) and _is_fund_or_reit(row):
  331                  continue
  332              price = _current_price(frames, yf_map.get(row["symbol"]))
  333              if price is None:
  334                  continue
  335              direction = "short" if str(row.get("dir", "LONG")).upper() == "SHORT" else "long"
  336              plans = row.get("plans") or {}
  337              for tf in TIMEFRAMES:
  338                  plan = plans.get(tf)
  339                  if not plan or not plan.get("armed"):
  340                      continue
  341                  tid = _trade_id(row["symbol"], direction, tf, day)
  342                  if tid in known or (row["symbol"], direction, tf) in open_keys:
  343                      continue
  344                  snap = _snapshot(row, tf, plan, market, price, day)
  345                  if snap is None:                       # don't chase / bad risk
  346                      continue
  347                  j["open"].append(snap)
  348                  known.add(tid)
  349                  open_keys.add((row["symbol"], direction, tf))
  350                  added += 1
  351  
  352      # 2) mark this market's open trades to the observed price (session only).
  353      still_open, closed_now = [], 0
  354      for t in j["open"]:
  355          if t.get("market") != market:
  356              still_open.append(t)
  357              continue
  358          price = _current_price(frames, yf_map.get(t["symbol"]))
  359          if is_open and price is not None:
  360              _mark(t, price, day, costs)
  361          if t["status"] == "closed":
  362              j["closed"].append(t)
  363              closed_now += 1
  364          else:
  365              still_open.append(t)
  366      j["open"] = still_open
  367  
  368      _save(j)
  369      log.info("vivek journal [%s]: %s · +%d new, %d closed this run (%d open, %d closed total)",
  370               market, "OPEN" if is_open else "closed-session",
  371               added, closed_now, len(j["open"]), len(j["closed"]))
  372      return j
```

### `scanner/vivek_backtest.py`  (459 lines)
> Walk-forward replay of the real engine. Compare its management to the live bot for drift — the 'evidence' depends on parity.
```python
    1  """VIVEK 5.0 walk-forward backtester.
    2  
    3  Replays the REAL engine over history rather than reimplementing the strategy:
    4  for each symbol it walks the daily series bar-by-bar and, on every bar where
    5  price is near a 200 SMA, runs the exact same ``vivek.evaluate`` /
    6  ``build_plans`` / grading the live scanner uses on a slice of history *up to and
    7  including that bar* (so there is no look-ahead). When that produces an ARMED
    8  A+/A setup it opens a paper trade at the NEXT bar's open and manages it forward
    9  with the same 5.0 rules (scale at TP1/2/3, SL → break-even at TP1 → locked
   10  structure at TP2) and the same fees + slippage R-drag the live bot/journal use.
   11  
   12  Fills are pessimistic intrabar: within a bar the adverse extreme (the stop
   13  side) is checked BEFORE the favourable extreme, so when a bar's range spans
   14  both a stop and a target the stop is assumed to fill first.
   15  
   16  Backtestable timeframes: Daily (1D), 3-Day (3D) and Weekly (1W). 4H is not
   17  backtestable server-side (no deep intraday history). Trades also carry the
   18  LEVEL that produced the signal (level_tf: weekly / 3d / h4-proxy) so the
   19  report can answer "does the 3D-200 level earn its keep?" separately from
   20  "which plan timeframe manages best". Honest caveats: today's universe →
   21  survivorship bias; yfinance data quality; A+ setups are rare so N is modest.
   22  
   23  CLI:  python -m scanner.vivek_backtest --market all --limit 60 --period 10y
   24  """
   25  
   26  import argparse
   27  import datetime as dt
   28  import json
   29  import logging
   30  import pathlib
   31  
   32  import numpy as np
   33  import pandas as pd
   34  
   35  from . import config, vivek
   36  from .broker.vivek_bot import size_position, _is_fund_or_reit
   37  from .vivek_journal import _snapshot, _mark, _apply_costs, _r_of, costs_for
   38  
   39  log = logging.getLogger("vivek_backtest")
   40  
   41  ROOT = pathlib.Path(__file__).resolve().parents[1]
   42  OUT_FILE = ROOT / "public" / "data" / "vivek_backtest.json"
   43  
   44  EQUITY = config.VIVEK_BOT_ACCOUNT_EQUITY
   45  TIMEFRAMES = ("1D", "3D", "1W")
   46  LEVEL_TFS = ("weekly", "3d", "h4")     # which 200-SMA produced the signal
   47  
   48  
   49  # ── per-symbol replay ─────────────────────────────────────────────────────────
   50  
   51  def _candidate_mask(df: pd.DataFrame) -> np.ndarray:
   52      """Bars where price is near a 200 SMA (daily or weekly) — the only place a
   53      reaction can exist. A superset of the engine's in-play test (the engine
   54      re-checks precisely), so it only saves work, never invents trades."""
   55      close = df["Close"]
   56      tol = config.VIVEK_NEAR_TOL * 1.3                      # widen so we never miss one
   57      dsma = close.rolling(config.VIVEK_SMA).mean()
   58      wk = close.resample("W-FRI").last()
   59      wsma = wk.rolling(config.VIVEK_SMA).mean().reindex(df.index, method="ffill")
   60      # 3-Day 200 SMA — epoch-anchored 72h buckets, identical to the engine's
   61      # _resample_3day_ohlc, so slice anchoring can't drift from this mask.
   62      d3 = close.resample("72h", origin="epoch").last().dropna()
   63      sma3 = d3.rolling(config.VIVEK_SMA).mean().reindex(df.index, method="ffill")
   64      near_d = (close - dsma).abs() / close <= tol
   65      near_w = (close - wsma).abs() / close <= tol
   66      near_3 = (close - sma3).abs() / close <= tol
   67      return (near_d.fillna(False) | near_w.fillna(False) | near_3.fillna(False)).to_numpy()
   68  
   69  
   70  def _build_row(sig: dict, df_slice: pd.DataFrame, symbol: str, name: str, sector: str):
   71      """Replicate scan.py's row build (grade + gate + plans), minus hysteresis."""
   72      points, grade, _ = vivek.score_and_grade(sig)
   73      if grade is None:
   74          return None, None, None
   75      plans = vivek.build_plans(df_slice, sig)
   76      lv = plans.get("1D")
   77      if not lv or lv.get("rr", 0) <= 0:
   78          return None, None, None
   79      armed = bool(lv.get("armed"))
   80      grade, _notes = vivek.gate_grade(grade, sig, lv["rr"], armed)
   81      if grade is None:
   82          return None, None, None
   83      entry_types = ([lv["entry_trigger"]] if armed and lv.get("entry_trigger")
   84                     else vivek.entry_types(sig))
   85      row = {"symbol": symbol, "name": name, "sector": sector,
   86             "dir": "LONG" if sig["direction"] == "long" else "SHORT",
   87             "grade": grade, "entry_types": entry_types,
   88             "level_tf": sig.get("level_tf")}
   89      return row, plans, grade
   90  
   91  
   92  def _force_close(tr: dict, price: float, day: str, costs) -> None:
   93      """Close any still-open remainder at `price` (end of data)."""
   94      is_long = tr["direction"] == "long"
   95      remaining = round(1.0 - tr.get("booked_pct", 0.0), 6)
   96      if remaining > 1e-9:
   97          tr["exits"].append({"reason": "eod", "price": round(price, 8), "pct": remaining, "date": day})
   98          tr["gross_r"] = round(tr.get("gross_r", 0.0) + remaining * _r_of(price, tr["entry"], tr["risk"], is_long), 4)
   99          tr["booked_pct"] = 1.0
  100      tr["status"] = "closed"
  101      tr["exit"] = round(price, 8)
  102      tr["exit_date"] = day
  103      tr["exit_reason"] = "target" if tr.get("tp3_hit") else ("trail" if tr.get("tp1_hit") else "eod")
  104      _apply_costs(tr, costs)
  105  
  106  
  107  def _manage_bar(tr: dict, high: float, low: float, close: float, day: str, costs, is_last: bool) -> None:
  108      is_long = tr["direction"] == "long"
  109      adverse, favourable = (low, high) if is_long else (high, low)
  110      _mark(tr, adverse, day, costs)                         # stop side first (pessimistic)
  111      if tr["status"] == "open":
  112          _mark(tr, favourable, day, costs)                 # then any targets
  113      if tr["status"] == "open" and is_last:
  114          _force_close(tr, close, day, costs)
  115  
  116  
  117  def replay_symbol(df: pd.DataFrame, market: str, symbol: str, name: str, sector: str,
  118                    long_only: bool = False) -> list[dict]:
  119      """Walk one symbol's daily history and return its closed backtest trades."""
  120      if df is None or len(df) < config.VIVEK_MIN_HISTORY + 5:
  121          return []
  122      df = df[~df.index.duplicated(keep="last")].sort_index()
  123      n = len(df)
  124      idx = df.index
  125      o, h, l, c = df["Open"].to_numpy(), df["High"].to_numpy(), df["Low"].to_numpy(), df["Close"].to_numpy()
  126      cand = _candidate_mask(df)
  127      costs = costs_for(market)
  128  
  129      closed: list[dict] = []
  130      open_slots = {tf: None for tf in TIMEFRAMES}
  131      pending: list[tuple] = []                              # (tf, plan, row) → open at next bar's open
  132  
  133      for j in range(config.VIVEK_MIN_HISTORY, n):
  134          day = idx[j].date().isoformat()
  135          # 1) open queued entries at THIS bar's open
  136          for tf, plan, row in pending:
  137              if open_slots[tf] is None and np.isfinite(o[j]):
  138                  tr = _snapshot(row, tf, plan, market, float(o[j]), day)
  139                  if tr is not None:
  140                      tr["market"] = market
  141                      tr["level_tf"] = row.get("level_tf")
  142                      open_slots[tf] = tr
  143          pending = []
  144  
  145          # 2) manage open trades on this bar (intrabar, stop-first)
  146          for tf in TIMEFRAMES:
  147              tr = open_slots[tf]
  148              if tr is None:
  149                  continue
  150              _manage_bar(tr, float(h[j]), float(l[j]), float(c[j]), day, costs, is_last=(j == n - 1))
  151              if tr["status"] == "closed":
  152                  closed.append(tr)
  153                  open_slots[tf] = None
  154  
  155          # 3) detect a new signal at this bar (uses its close), queue for next bar
  156          if cand[j] and any(open_slots[tf] is None for tf in TIMEFRAMES):
  157              try:
  158                  sig = vivek.evaluate(df.iloc[:j + 1])
  159              except Exception:
  160                  sig = None
  161              if sig is not None:
  162                  row, plans, grade = _build_row(sig, df.iloc[:j + 1], symbol, name, sector)
  163                  if row and grade in ("A+", "A") and not (long_only and row["dir"] == "SHORT"):
  164                      for tf in TIMEFRAMES:
  165                          p = plans.get(tf)
  166                          if p and p.get("armed") and open_slots[tf] is None:
  167                              pending.append((tf, p, row))
  168      return closed
  169  
  170  
  171  # ── aggregation ───────────────────────────────────────────────────────────────
  172  
  173  def _dollars(tr: dict) -> float:
  174      sz = size_position(EQUITY, tr["entry"], tr["stop"])
  175      return (tr.get("realized_r") or 0.0) * sz["risk_usd"]
  176  
  177  
  178  def _metrics(trades: list[dict]) -> dict:
  179      n = len(trades)
  180      if not n:
  181          return {"n": 0, "win_rate": 0.0, "avg_r": 0.0, "expectancy_r": 0.0,
  182                  "profit_factor": None, "total_r": 0.0, "total_usd": 0.0, "max_dd_usd": 0.0}
  183      rs = [t.get("realized_r") or 0.0 for t in trades]
  184      ds = [_dollars(t) for t in trades]
  185      wins = [r for r in rs if r > 0]
  186      gross_win = sum(r for r in rs if r > 0)
  187      gross_loss = abs(sum(r for r in rs if r < 0))
  188      # max drawdown on the cumulative $ curve, ordered by exit date
  189      order = sorted(range(n), key=lambda i: trades[i].get("exit_date") or "")
  190      cum = peak = dd = 0.0
  191      for i in order:
  192          cum += ds[i]; peak = max(peak, cum); dd = min(dd, cum - peak)
  193      return {
  194          "n": n,
  195          "win_rate": round(100 * len(wins) / n, 1),
  196          "avg_r": round(sum(rs) / n, 3),
  197          "expectancy_r": round(sum(rs) / n, 3),
  198          # None (not inf): float("inf") serialises as bare `Infinity`, which is
  199          # not valid JSON and breaks the frontend's response.json()
  200          "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
  201          "total_r": round(sum(rs), 2),
  202          "total_usd": round(sum(ds), 2),
  203          "max_dd_usd": round(dd, 2),
  204      }
  205  
  206  
  207  def _split(trades: list[dict], key, values=None) -> dict:
  208      vals = values or sorted({t.get(key) for t in trades if t.get(key) is not None})
  209      return {str(v): _metrics([t for t in trades if t.get(key) == v]) for v in vals}
  210  
  211  
  212  def aggregate(trades: list[dict]) -> dict:
  213      return {
  214          "overall": _metrics(trades),
  215          "by_entry_type": _split(trades, "entry_type", config.VIVEK_TRIGGER_PRIORITY),
  216          "by_timeframe": _split(trades, "timeframe", list(TIMEFRAMES)),
  217          "by_market": _split(trades, "market"),
  218          "by_grade": _split(trades, "grade", ["A+", "A"]),
  219          "by_direction": _split(trades, "direction", ["long", "short"]),
  220          "by_level_tf": _split(trades, "level_tf", list(LEVEL_TFS)),
  221      }
  222  
  223  
  224  # ── driver ────────────────────────────────────────────────────────────────────
  225  
  226  # Slim trade record stored in the report — enough to recompute every metric and
  227  # to MERGE markets together across separate (streamed) runs.
  228  _SLIM_KEYS = ("symbol", "market", "timeframe", "level_tf", "entry_type", "grade",
  229                "direction", "entry", "stop", "exit", "entry_date", "exit_date",
  230                "exit_reason", "realized_r", "gross_r", "cost_r", "sector")
  231  
  232  
  233  def _slim(tr: dict) -> dict:
  234      return {k: tr.get(k) for k in _SLIM_KEYS}
  235  
  236  
  237  def run_market_trades(mk: str, limit: int | None, period: str,
  238                        exclude_funds: bool = True, long_only: bool = False) -> tuple[list[dict], dict]:
  239      """Backtest ONE market; return (slim trades, coverage entry)."""
  240      from .universe import load_universe
  241      from .data import download
  242  
  243      uni = load_universe(mk, full=False)
  244      if exclude_funds:
  245          uni = [u for u in uni if not _is_fund_or_reit({"name": u.get("name"), "sector": u.get("sector")})]
  246      if limit:
  247          uni = uni[:limit]
  248      log.info("[%s] downloading %d tickers (%s) ...", mk, len(uni), period)
  249      frames = download([u["yf"] for u in uni], period=period)
  250      meta = {u["yf"]: u for u in uni}
  251      trades: list[dict] = []
  252      for yf, df in frames.items():
  253          u = meta.get(yf, {})
  254          try:
  255              trades.extend(replay_symbol(df, mk, u.get("symbol", yf), u.get("name", yf),
  256                                          u.get("sector", ""), long_only=long_only))
  257          except Exception as e:
  258              log.warning("[%s] %s replay error: %s", mk, yf, e)
  259      log.info("[%s] %d trades from %d symbols", mk, len(trades), len(uni))
  260      return [_slim(t) for t in trades], {"symbols": len(uni), "trades": len(trades)}
  261  
  262  
  263  # ── portfolio-level simulation ───────────────────────────────────────────────
  264  # The per-trade replay answers "does a signal have edge?"; this answers the
  265  # question the bot actually lives with: does that edge SURVIVE slot contention
  266  # once the book rules (10 slots, one/symbol, sector cap, cooldown) compete for
  267  # capital? Chronological, per market, using the same rules as the live bot.
  268  # The time stop and daily/weekly guards need intra-trade price paths the slim
  269  # records don't carry, so they are NOT simulated (noted in the output).
  270  
  271  def portfolio_sim(trades: list[dict]) -> dict:
  272      from collections import Counter
  273      from .broker.vivek_bot import _sector_key
  274  
  275      skip_types = set(getattr(config, "VIVEK_BOT_SKIP_ENTRY_TYPES", ()) or ())
  276      long_only = not getattr(config, "VIVEK_BOT_ALLOW_SHORTS", True)
  277      max_pos = config.VIVEK_BOT_MAX_POSITIONS
  278      max_sector = int(getattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 0) or 0)
  279      cooldown = int(getattr(config, "VIVEK_BOT_REENTRY_COOLDOWN_DAYS", 0) or 0)
  280  
  281      elig = [t for t in trades
  282              if t.get("grade") == "A+"
  283              and t.get("entry_type") not in skip_types
  284              and (not long_only or t.get("direction") == "long")
  285              and t.get("entry_date") and t.get("exit_date")]
  286      if not elig:
  287          return {"note": "no bot-eligible trades with entry dates (re-run the "
  288                          "backtest to regenerate trades with entry_date)",
  289                  "eligible": _metrics([]), "portfolio": _metrics([])}
  290  
  291      def add_days(day: str, n: int) -> str:
  292          return (dt.date.fromisoformat(day) + dt.timedelta(days=n)).isoformat()
  293  
  294      taken_all: list[dict] = []
  295      skips: Counter = Counter()
  296      peak_open = 0
  297      for mk in sorted({t["market"] for t in elig}):
  298          # Weekly first on ties — mirrors the bot's prefer_tf ordering.
  299          trs = sorted((t for t in elig if t["market"] == mk),
  300                       key=lambda t: (t["entry_date"],
  301                                      0 if t.get("timeframe") == "1W" else 1))
  302          open_pos: list[dict] = []
  303          open_syms: set = set()
  304          sector_count: Counter = Counter()
  305          cooldown_until: dict = {}
  306          for t in trs:
  307              day = t["entry_date"]
  308              still = []
  309              for p in open_pos:                       # free slots exited BEFORE today
  310                  if p["exit_date"] < day:
  311                      open_syms.discard(p["symbol"])
  312                      sk = _sector_key(p["symbol"], p.get("sector"), mk)
  313                      if sk:
  314                          sector_count[sk] -= 1
  315                      if cooldown and p.get("exit_reason") == "stop":
  316                          cooldown_until[p["symbol"]] = add_days(p["exit_date"], cooldown)
  317                  else:
  318                      still.append(p)
  319              open_pos = still
  320              sym, sk = t["symbol"], _sector_key(t["symbol"], t.get("sector"), mk)
  321              if sym in open_syms:
  322                  skips["dup_symbol"] += 1
  323              elif cooldown_until.get(sym, "") >= day:
  324                  skips["cooldown"] += 1
  325              elif len(open_pos) >= max_pos:
  326                  skips["book_full"] += 1
  327              elif max_sector and sk and sector_count[sk] >= max_sector:
  328                  skips["sector_cap"] += 1
  329              else:
  330                  open_pos.append(t)
  331                  open_syms.add(sym)
  332                  if sk:
  333                      sector_count[sk] += 1
  334                  taken_all.append(t)
  335                  peak_open = max(peak_open, len(open_pos))
  336  
  337      return {
  338          "params": {"max_positions": max_pos, "max_per_sector": max_sector,
  339                     "cooldown_days": cooldown, "long_only": long_only,
  340                     "skip_entry_types": sorted(skip_types),
  341                     "not_simulated": ["time_stop", "daily_guard", "weekly_guard",
  342                                       "adv_gates (no historical ADV)"]},
  343          "eligible": _metrics(elig),          # unconstrained: every bot-eligible signal
  344          "portfolio": _metrics(taken_all),    # what the book rules actually let through
  345          "taken": len(taken_all), "skipped": dict(skips), "peak_open": peak_open,
  346      }
  347  
  348  
  349  def build_report(trades: list[dict], coverage: dict, params: dict, status: str) -> dict:
  350      return {
  351          "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
  352          "status": status,                                  # "partial" while streaming, "complete" when done
  353          "params": params,
  354          "coverage": coverage,
  355          "results": aggregate(trades),
  356          "portfolio": portfolio_sim(trades),
  357          "trades": trades,
  358          "caveats": [
  359              "Survivorship bias — today's universe excludes delisted names.",
  360              "yfinance daily data (dividend-adjusted); occasional gaps.",
  361              "Intrabar fills assume the stop fills before the target within a bar.",
  362              "A+ setups are rare, so trade counts (N) can be small and noisy.",
  363              "4H is not backtested (no deep intraday history).",
  364              "Portfolio sim: time stop and loss guards are not replayed "
  365              "(no intra-trade price paths in the slim records).",
  366          ],
  367      }
  368  
  369  
  370  def run_backtest(markets: list[str], limit: int | None, period: str,
  371                   exclude_funds: bool = True, long_only: bool = False) -> dict:
  372      """Backtest several markets in one process (no streaming)."""
  373      trades, coverage = [], {}
  374      for mk in markets:
  375          tr, cov = run_market_trades(mk, limit, period, exclude_funds, long_only)
  376          trades += tr
  377          coverage[mk] = cov
  378      params = {"markets": markets, "limit": limit, "period": period,
  379                "exclude_funds": exclude_funds, "long_only": long_only, "equity": EQUITY,
  380                "intrabar": "pessimistic (stop-first)", "timeframes": list(TIMEFRAMES)}
  381      return build_report(trades, coverage, params, "complete")
  382  
  383  
  384  def _print(report: dict) -> None:
  385      r = report["results"]
  386      def line(label, m):
  387          pf = "inf" if m["profit_factor"] is None else f"{m['profit_factor']:.2f}"
  388          print(f"  {label:<14} n={m['n']:<4} win {m['win_rate']:>5}%  "
  389                f"avgR {m['avg_r']:+.2f}  exp {m['expectancy_r']:+.2f}R  "
  390                f"PF {pf:<5} totR {m['total_r']:+.1f}  ${m['total_usd']:+.0f}  maxDD ${m['max_dd_usd']:.0f}")
  391      print("\n=== VIVEK 5.0 BACKTEST ===")
  392      print("params:", report["params"])
  393      print("coverage:", report["coverage"])
  394      print("\nOVERALL"); line("overall", r["overall"])
  395      for grp in ("by_entry_type", "by_timeframe", "by_level_tf", "by_market", "by_grade", "by_direction"):
  396          print(f"\n{grp.upper()}")
  397          for k, m in r[grp].items():
  398              if m["n"]:
  399                  line(k, m)
  400      port = report.get("portfolio") or {}
  401      if port.get("portfolio", {}).get("n"):
  402          print("\nPORTFOLIO (bot book rules applied chronologically)")
  403          line("eligible", port["eligible"])
  404          line("portfolio", port["portfolio"])
  405          print(f"  taken {port['taken']} · peak open {port['peak_open']} · "
  406                f"skips {port['skipped'] or 'none'}")
  407      elif port.get("note"):
  408          print(f"\nPORTFOLIO: {port['note']}")
  409  
  410  
  411  def main() -> None:
  412      ap = argparse.ArgumentParser(description="VIVEK 5.0 walk-forward backtest")
  413      ap.add_argument("--market", action="append", choices=[*config.MARKETS, "all"])
  414      ap.add_argument("--limit", type=int, default=60, help="max symbols per market (0 = all)")
  415      ap.add_argument("--period", default="10y", help="yfinance history period (e.g. 10y, max)")
  416      ap.add_argument("--include-funds", action="store_true", help="don't exclude REITs/ETFs/funds")
  417      ap.add_argument("--long-only", action="store_true", help="skip short setups (long-only system)")
  418      ap.add_argument("--merge", action="store_true",
  419                      help="merge this run's market(s) into the existing results file (streaming)")
  420      ap.add_argument("--status", choices=["partial", "complete"],
  421                      help="override the report status (default: auto)")
  422      ap.add_argument("--out", default=str(OUT_FILE))
  423      args = ap.parse_args()
  424      logging.basicConfig(level=logging.INFO, format="%(message)s")
  425      markets = list(config.MARKETS) if (not args.market or "all" in args.market) else args.market
  426      out = pathlib.Path(args.out)
  427  
  428      # Carry over trades/coverage for OTHER markets from a previous (streamed) run.
  429      prior_trades, coverage = [], {}
  430      if args.merge and out.exists():
  431          try:
  432              prev = json.loads(out.read_text())
  433              prior_trades = [t for t in prev.get("trades", []) if t.get("market") not in markets]
  434              coverage = {k: v for k, v in prev.get("coverage", {}).items() if k not in markets}
  435          except Exception as e:
  436              log.warning("could not read prior results (%s) — starting fresh", e)
  437  
  438      new_trades = []
  439      for mk in markets:
  440          tr, cov = run_market_trades(mk, args.limit or None, args.period,
  441                                      not args.include_funds, args.long_only)
  442          new_trades += tr
  443          coverage[mk] = cov
  444  
  445      trades = prior_trades + new_trades
  446      done = set(coverage)
  447      status = args.status or ("complete" if done >= set(config.MARKETS) else "partial")
  448      params = {"markets": sorted(done), "limit": args.limit or None, "period": args.period,
  449                "exclude_funds": not args.include_funds, "long_only": args.long_only, "equity": EQUITY,
  450                "intrabar": "pessimistic (stop-first)", "timeframes": list(TIMEFRAMES)}
  451      report = build_report(trades, coverage, params, status)
  452      _print(report)
  453      out.parent.mkdir(parents=True, exist_ok=True)
  454      out.write_text(json.dumps(report, indent=2))
  455      print(f"\nwrote {out}  (status={status}, markets done: {sorted(done)})")
  456  
  457  
  458  if __name__ == "__main__":
  459      main()
```


## === C4. BOT DECISION + PAPER RUNNER + GUARD ===

### `scanner/broker/vivek_bot.py`  (450 lines)
> Pure decision engine: A+ gate, plan/entry-type pick, sizing, fund exclusion, book caps + sector cap.
```python
    1  """VIVEK autonomous-bot decision engine — strict VIVEK 5.0 rules.
    2  
    3  Pure decision logic (no broker calls) so it is fully testable and auditable. A
    4  runner feeds it VIVEK scan rows + the account equity, PER MARKET; this module
    5  decides what to trade and how big. Wiring it to Bybit/IBKR bracket orders is a
    6  thin layer on top — this module never places an order itself.
    7  
    8  The rules it enforces (locked-in, audited on every decision):
    9  
   10    1. A+ ONLY. It will not take A, B+ or WATCH under any circumstances.
   11    2. ENTRY TYPE is labelled on every trade — reclaim / retest / break — in both
   12       the logs and the returned ticket, with the full human description.
   13    3. TIMEFRAME: Weekly plans are primary (less noise); it falls back to the
   14       Daily plan only if the Weekly one has no armed trigger. The timeframe it
   15       traded is recorded on the ticket. A runner can override the preference
   16       (e.g. to mirror the timeframe the user has selected on the chart).
   17    4. SIZING: risk 0.25–0.5% of equity per trade; leverage is 5× for stocks
   18       (ASX/NASDAQ) and 3× for crypto. Effective size + leverage are logged.
   19    5. BOOK (per market): at most 10 open, of which AT LEAST 4 must be short — so
   20       at most 6 longs. The bot reserves the short slots to hold a deliberate
   21       short bias and never lets the book run long-heavy. One position per symbol.
   22  
   23  Single source of truth: it reads the SAME per-timeframe plans the row, chart and
   24  journal use (row["plans"][tf]) — it never recomputes a level.
   25  """
   26  
   27  import logging
   28  
   29  from scanner import config as _cfg
   30  
   31  log = logging.getLogger("vivek_bot")
   32  
   33  _LEVEL_KEYS = ("entry", "stop", "tp1", "tp2", "tp3")
   34  
   35  # Rule 2 — the three (and only three) allowed entry types, with auditable labels.
   36  ENTRY_TYPE_LABEL = {
   37      "reclaim": "Close back above the 200 SMA after rejection",
   38      "retest":  "Retest of the level with confirmation",
   39      "break":   "Break of small structure near the 200 SMA",
   40  }
   41  
   42  
   43  def _direction(row: dict) -> str:
   44      return "short" if str(row.get("dir", "LONG")).upper() == "SHORT" else "long"
   45  
   46  
   47  # Non-operating vehicles the bot should not trade (REITs / ETFs / LICs / funds).
   48  # A REIT or fund hugs its 200 SMA, so it over-produces "reactions" without being
   49  # a real momentum/trend trade. Detected by sector + name so it catches funds that
   50  # sit under an operating-sector label (e.g. a real-estate income fund tagged
   51  # "Financial Services") as well as the ETFs/LICs that have no GICS sector at all.
   52  _FUND_NAME_KEYWORDS = ("REIT", "TRUST", "FUND", "ETF", "SPDR", "ISHARES",
   53                         "VANGUARD", "BETASHARES", "VANECK", "GLOBAL X")
   54  _FUND_SECTOR_HINTS = ("reit", "real estate investment trust")
   55  _NON_OPERATING_SECTORS = {"not applicable", "not applic", "n/a"}   # the ETF/LIC/fund tag
   56  
   57  
   58  def _is_fund_or_reit(row: dict) -> bool:
   59      name = str(row.get("name") or "").upper()
   60      sector = str(row.get("sector") or "").strip().lower()
   61      if any(h in sector for h in _FUND_SECTOR_HINTS):
   62          return True
   63      if sector in _NON_OPERATING_SECTORS:              # ETFs / LICs carry no operating sector
   64          return True
   65      return any(kw in name for kw in _FUND_NAME_KEYWORDS)
   66  
   67  
   68  def _pick_plan(row: dict, prefer_tf: str) -> tuple[str | None, dict | None]:
   69      """Rule 3 — choose the timeframe plan to trade.
   70  
   71      Weekly (or the runner-supplied `prefer_tf`) is primary; fall back to the
   72      other timeframe. Only an ARMED plan with a complete level set qualifies.
   73      Returns (timeframe, plan) or (None, None).
   74      """
   75      plans = row.get("plans") or {}
   76      order = [prefer_tf] + [tf for tf in ("1W", "1D") if tf != prefer_tf]
   77      for tf in order:
   78          p = plans.get(tf)
   79          if p and p.get("armed") and all(p.get(k) is not None for k in _LEVEL_KEYS):
   80              return tf, p
   81      return None, None
   82  
   83  
   84  # ── 1. should we take it? (A+ only, armed, ordered, R:R, labelled) ────────────
   85  
   86  def evaluate_setup(row: dict, prefer_tf: str | None = None, min_rr: float | None = None) -> dict:
   87      """Decide whether a VIVEK row is takeable, on the preferred timeframe's plan.
   88  
   89      Returns a decision dict; on a take it carries the timeframe, the entry-type
   90      label, and the plan it will trade. Every skip carries an auditable code.
   91      """
   92      prefer_tf = prefer_tf or _cfg.VIVEK_BOT_PREFER_TF
   93      min_rr = _cfg.VIVEK_BOT_MIN_RR if min_rr is None else min_rr
   94      sym = row.get("symbol", "?")
   95      grade = row.get("grade")
   96  
   97      def skip(code, reason):
   98          log.info("SKIP  %-8s [%s] %s", sym, code, reason)
   99          return {"take": False, "grade": grade, "reason": reason, "code": code}
  100  
  101      # Long-only: shorts lost on every market in the backtest, so the bot skips
  102      # them while VIVEK_BOT_ALLOW_SHORTS is False.
  103      if not getattr(_cfg, "VIVEK_BOT_ALLOW_SHORTS", True) and _direction(row) == "short":
  104          return skip("shorts_disabled", f"{sym} is a short — bot is long-only")
  105  
  106      # Don't trade REITs / ETFs / LICs / managed funds (they hug the 200 SMA).
  107      if getattr(_cfg, "VIVEK_BOT_EXCLUDE_FUNDS", True) and _is_fund_or_reit(row):
  108          return skip("fund_reit", f"{sym} is a REIT/ETF/fund — excluded from bot trading")
  109  
  110      # Rule 1 — A+ ONLY.
  111      if grade != _cfg.VIVEK_BOT_MIN_GRADE:
  112          return skip("not_a_plus", f"grade {grade} — bot trades {_cfg.VIVEK_BOT_MIN_GRADE} only")
  113  
  114      # Rule 3 — pick the timeframe plan (Weekly primary).
  115      tf, plan = _pick_plan(row, prefer_tf)
  116      if plan is None:
  117          return skip("no_armed_plan", f"no armed {prefer_tf}/1D plan to trade")
  118  
  119      direction = _direction(row)
  120      e, s = float(plan["entry"]), float(plan["stop"])
  121      t1, t2, t3 = float(plan["tp1"]), float(plan["tp2"]), float(plan["tp3"])
  122      ordered = (s < e < t1 < t2 < t3) if direction == "long" else (s > e > t1 > t2 > t3)
  123      if not ordered:
  124          return skip("bad_level_order", f"{tf} levels not ordered for {direction}")
  125  
  126      rr = float(plan.get("rr", 0) or 0)
  127      if rr < min_rr:
  128          return skip("low_rr", f"{tf} R:R {rr:.1f} < min {min_rr:.1f}")
  129  
  130      # Tradeability: a structural stop miles from entry (e.g. −95% on a weekly
  131      # crypto plan) makes risk-based sizing meaningless — units go microscopic and
  132      # the "trade" is a lottery ticket. Cap the stop distance as a % of entry.
  133      max_stop_pct = float(getattr(_cfg, "VIVEK_BOT_MAX_STOP_PCT", 0) or 0)
  134      if max_stop_pct > 0 and e > 0:
  135          stop_pct = abs(e - s) / e * 100.0
  136          if stop_pct > max_stop_pct:
  137              return skip("wide_stop",
  138                          f"{tf} stop {stop_pct:.0f}% from entry > max {max_stop_pct:.0f}%")
  139  
  140      # The inverse pathology: a stop <1% from entry is a dead/pegged instrument
  141      # (stablecoin-likes, defensives glued to the SMA). Risk sizing then buys a
  142      # leverage-capped MAX position in something that doesn't move — a slot
  143      # squatter, not a trade.
  144      min_stop_pct = float(getattr(_cfg, "VIVEK_BOT_MIN_STOP_PCT", 0) or 0)
  145      if min_stop_pct > 0 and e > 0:
  146          stop_pct = abs(e - s) / e * 100.0
  147          if stop_pct < min_stop_pct:
  148              return skip("stop_too_tight",
  149                          f"{tf} stop {stop_pct:.2f}% from entry < min {min_stop_pct:g}% — "
  150                          f"dead/pegged instrument")
  151  
  152      # Rule 2 — entry-type label (must be one of the three known triggers).
  153      et = plan.get("entry_trigger") or (row.get("entry_types") or [None])[0]
  154      # Favour the strongest trigger — skip the entry types the backtest flagged
  155      # weak (default: retest). Reclaim carries the edge.
  156      if et in set(getattr(_cfg, "VIVEK_BOT_SKIP_ENTRY_TYPES", ()) or ()):
  157          return skip("weak_entry_type", f"{et} entry — backtest weak; bot favours reclaim")
  158      et_label = ENTRY_TYPE_LABEL.get(et)
  159      if et_label is None:
  160          return skip("unknown_entry_type", f"entry type {et!r} not one of reclaim/retest/break")
  161  
  162      why = f"A+ {direction} · {tf} · {et}: {et_label} · entry {e:g} SL {s:g} · R:R {rr:.1f}"
  163      log.info("TAKE  %-8s %s", sym, why)
  164      return {"take": True, "grade": grade, "direction": direction, "timeframe": tf,
  165              "entry_type": et, "entry_type_label": et_label, "rr": rr,
  166              "reason": why, "code": "OK", "_plan": plan}
  167  
  168  
  169  # ── 2. position sizing (0.25–0.5% risk; 5× stocks / 3× crypto) ────────────────
  170  
  171  def _leverage_for(market: str | None) -> float:
  172      return float(_cfg.VIVEK_BOT_LEVERAGE.get(market, _cfg.VIVEK_BOT_LEVERAGE["asx"]))
  173  
  174  
  175  def size_position(equity: float, entry: float, stop: float,
  176                    risk_pct: float | None = None, max_leverage: float | None = None) -> dict:
  177      """Risk-based size: risk a small % of equity, cap implied leverage at the
  178      per-market leverage. Risk % is clamped to the 0.25–0.5 band."""
  179      risk_pct = _cfg.VIVEK_BOT_RISK_PCT if risk_pct is None else risk_pct
  180      risk_pct = min(max(risk_pct, 0.25), _cfg.VIVEK_RISK_PCT_MAX)      # 0.25–0.5 band
  181      max_lev = _cfg.VIVEK_MAX_LEVERAGE if max_leverage is None else max_leverage
  182  
  183      stop_dist = abs(entry - stop)
  184      if stop_dist <= 0 or entry <= 0 or equity <= 0:
  185          return {"units": 0.0, "notional": 0.0, "risk_usd": 0.0,
  186                  "risk_pct": risk_pct, "leverage": 0.0, "stop_dist": stop_dist,
  187                  "leverage_capped": False}
  188  
  189      risk_usd = equity * (risk_pct / 100.0)
  190      units = risk_usd / stop_dist
  191      notional = units * entry
  192  
  193      # Cap notional so implied leverage never exceeds the per-market max.
  194      max_notional = equity * max_lev
  195      capped = False
  196      if notional > max_notional:
  197          capped = True
  198          units = max_notional / entry
  199          notional = units * entry
  200          risk_usd = units * stop_dist
  201  
  202      return {
  203          "units": round(units, 8), "notional": round(notional, 2),
  204          "risk_usd": round(risk_usd, 2), "risk_pct": risk_pct,
  205          "leverage": round(notional / equity if equity else 0.0, 2),
  206          "stop_dist": round(stop_dist, 8), "leverage_capped": capped,
  207      }
  208  
  209  
  210  # ── 3. full trade plan ────────────────────────────────────────────────────────
  211  
  212  def plan_trade(row: dict, equity: float, market: str | None = None,
  213                 prefer_tf: str | None = None, risk_pct: float | None = None,
  214                 min_rr: float | None = None) -> dict:
  215      """Combine evaluate + size into a ready-to-place ticket (or a skip)."""
  216      decision = evaluate_setup(row, prefer_tf, min_rr)
  217      if not decision["take"]:
  218          return {**decision, "plan": None}
  219  
  220      # Tradeability: sub-floor prices (e.g. a $0.021 ASX micro-cap) carry spreads
  221      # worth multiple R — a paper fill at "the price" is fiction. Per-market floor.
  222      floors = getattr(_cfg, "VIVEK_BOT_MIN_PRICE", None) or {}
  223      floor = float(floors.get(market, floors.get("default", 0)) or 0)
  224      px = float(row.get("price") or 0)
  225      if floor > 0 and 0 < px < floor:
  226          sym = row.get("symbol", "?")
  227          reason = f"price {px:g} below the {market} tradeability floor {floor:g}"
  228          log.info("SKIP  %-8s [min_price] %s", sym, reason)
  229          return {"take": False, "grade": decision.get("grade"), "reason": reason,
  230                  "code": "min_price", "plan": None}
  231  
  232      plan = decision["_plan"]
  233      tf = decision["timeframe"]
  234      direction = decision["direction"]
  235      entry, stop = float(plan["entry"]), float(plan["stop"])
  236      tps = [float(plan["tp1"]), float(plan["tp2"]), float(plan["tp3"])]
  237      max_lev = _leverage_for(market)
  238      sizing = size_position(equity, entry, stop, risk_pct, max_lev)
  239  
  240      # Liquidity honesty (row["adv_usd"] = 20-day average dollar volume in the
  241      # market's quote currency, enriched by the runner; unknown = exempt):
  242      # below the ADV floor a real fill eats multiple R in spread/impact, and
  243      # even above it the position must stay a sliver of the daily tape.
  244      adv = row.get("adv_usd")
  245      if adv is not None and adv > 0:
  246          sym = row.get("symbol", "?")
  247          floors = getattr(_cfg, "VIVEK_BOT_MIN_ADV", None) or {}
  248          min_adv = float(floors.get(market, floors.get("default", 0)) or 0)
  249          if min_adv > 0 and adv < min_adv:
  250              reason = (f"20d avg dollar volume {adv:,.0f} below the {market} "
  251                        f"liquidity floor {min_adv:,.0f}")
  252              log.info("SKIP  %-8s [illiquid] %s", sym, reason)
  253              return {"take": False, "grade": decision.get("grade"), "reason": reason,
  254                      "code": "illiquid", "plan": None}
  255          max_adv_pct = float(getattr(_cfg, "VIVEK_BOT_MAX_NOTIONAL_PCT_ADV", 0) or 0)
  256          if max_adv_pct > 0 and sizing["notional"] > adv * (max_adv_pct / 100.0):
  257              reason = (f"notional {sizing['notional']:,.0f} is "
  258                        f"{sizing['notional'] / adv * 100:.1f}% of ADV {adv:,.0f} "
  259                        f"— max {max_adv_pct:g}%")
  260              log.info("SKIP  %-8s [size_vs_adv] %s", sym, reason)
  261              return {"take": False, "grade": decision.get("grade"), "reason": reason,
  262                      "code": "size_vs_adv", "plan": None}
  263      scale = plan.get("scale") or (
  264          _cfg.VIVEK_TP_SCALE_LONG if direction == "long" else _cfg.VIVEK_TP_SCALE_SHORT)
  265  
  266      ticket = {
  267          "symbol": row.get("symbol"),
  268          "name": row.get("name", row.get("symbol")),
  269          "sector": row.get("sector", ""),   # persisted on the position so the
  270          "market": market,                  # sector cap holds ACROSS runs
  271          "direction": direction,
  272          "timeframe": tf,                              # Rule 3 — recorded per trade
  273          "entry_type": decision["entry_type"],         # Rule 2 — labelled per trade
  274          "entry_type_label": decision["entry_type_label"],
  275          "grade": "A+",
  276          "entry": entry, "stop": stop,
  277          "tp1": tps[0], "tp2": tps[1], "tp3": tps[2],
  278          "tp_plan": [
  279              {"level": tps[0], "book_pct": scale[0], "sl_move": "breakeven"},
  280              {"level": tps[1], "book_pct": scale[1], "sl_move": "below_support"},
  281              {"level": tps[2], "book_pct": scale[2], "sl_move": "hold"},
  282          ],
  283          "scale": scale, "rr": decision["rr"], "leverage_target": max_lev,
  284          **sizing,
  285      }
  286      log.info("PLAN  %-8s A+ %-5s %s · %s · entry %g SL %g · %g units  $%.0f notional  "
  287               "risk $%.2f (%.2f%%)  lev %.1fx%s",
  288               ticket["symbol"], direction, tf, ticket["entry_type"], entry, stop,
  289               ticket["units"], ticket["notional"], ticket["risk_usd"], ticket["risk_pct"],
  290               ticket["leverage"], "  [lev-capped]" if ticket["leverage_capped"] else "")
  291      return {**decision, "plan": ticket}
  292  
  293  
  294  # ── 4. live management: scale-outs + SL movement (never adverse) ──────────────
  295  
  296  def _favourable(new_sl: float, cur_sl: float, is_long: bool) -> bool:
  297      """A long's SL may only move UP; a short's only DOWN. Never against the trade."""
  298      return new_sl > cur_sl if is_long else new_sl < cur_sl
  299  
  300  
  301  def manage_position(pos: dict, price: float, support: float | None = None) -> list[dict]:
  302      """Apply the 5.0 management rules to an open position at `price`.
  303  
  304      Mutates `pos` (sets tp*_hit flags, advances `stop`) and returns the actions
  305      taken: book at TP1/TP2/TP3, SL → break-even at TP1, SL → new support at TP2.
  306      SL is only ever moved in the trade's favour.
  307      """
  308      is_long = pos.get("direction", "long") == "long"
  309      scale = pos.get("scale") or (
  310          _cfg.VIVEK_TP_SCALE_LONG if is_long else _cfg.VIVEK_TP_SCALE_SHORT)
  311      reached = (lambda lvl: price >= lvl) if is_long else (lambda lvl: price <= lvl)
  312      sym = pos.get("symbol", "?")
  313      actions: list[dict] = []
  314  
  315      if not pos.get("tp1_hit") and pos.get("tp1") is not None and reached(pos["tp1"]):
  316          pos["tp1_hit"] = True
  317          actions.append({"action": "scale", "tp": "TP1", "book_pct": scale[0], "price": price})
  318          be = pos["entry"]
  319          if _favourable(be, pos["stop"], is_long):
  320              pos["stop"] = be
  321              actions.append({"action": "sl", "to": "breakeven", "price": be})
  322          log.info("MANAGE %-8s TP1 @ %g → book %d%%, SL → break-even (%g)",
  323                   sym, price, round(scale[0] * 100), be)
  324  
  325      if not pos.get("tp2_hit") and pos.get("tp2") is not None and reached(pos["tp2"]):
  326          pos["tp2_hit"] = True
  327          actions.append({"action": "scale", "tp": "TP2", "book_pct": scale[1], "price": price})
  328          new_sl = support if support is not None else pos.get("tp1", pos["stop"])
  329          if new_sl is not None and _favourable(new_sl, pos["stop"], is_long):
  330              pos["stop"] = new_sl
  331              actions.append({"action": "sl", "to": "support", "price": new_sl})
  332          log.info("MANAGE %-8s TP2 @ %g → book %d%%, SL → %g (locked structure)",
  333                   sym, price, round(scale[1] * 100), pos["stop"])
  334  
  335      if not pos.get("tp3_hit") and pos.get("tp3") is not None and reached(pos["tp3"]):
  336          pos["tp3_hit"] = True
  337          actions.append({"action": "scale", "tp": "TP3", "book_pct": scale[2], "price": price})
  338          log.info("MANAGE %-8s TP3 @ %g → book %d%% (runner trails)",
  339                   sym, price, round(scale[2] * 100))
  340  
  341      return actions
  342  
  343  
  344  # ── 5. process one market's scan into plans, with the book rules ──────────────
  345  
  346  def _sector_key(symbol: str, sector: str | None, market: str | None) -> str:
  347      """Sector bucket for the correlation cap. Crypto has no GICS sector, so
  348      coins get synthetic buckets: the configured majors are 'crypto-major',
  349      everything else is 'crypto-alt' — 4 alts are usually ONE beta-to-BTC bet."""
  350      s = str(sector or "").strip().lower()
  351      if s:
  352          return s
  353      if market == "crypto":
  354          majors = {m.upper() for m in getattr(_cfg, "VIVEK_BOT_CRYPTO_MAJORS", ()) or ()}
  355          return "crypto-major" if str(symbol or "").upper() in majors else "crypto-alt"
  356      return ""
  357  
  358  
  359  def decide(rows: list[dict], equity: float, market: str | None = None,
  360             prefer_tf: str | None = None, open_book: list[dict] | None = None, **kw) -> dict:
  361      """Run the engine over ONE market's VIVEK scan and apply the book rules.
  362  
  363      Rows are expected best-first (the scan sorts by grade → score → R:R). The
  364      book caps (Rule 5) are evaluated against the CURRENT open book passed in via
  365      `open_book` (a list of {symbol, direction} already held in this market), so
  366      the limits hold ACROSS RUNS, not just within one scan: at most
  367      VIVEK_BOT_MAX_POSITIONS (10) open, at most (10 − VIVEK_BOT_MIN_SHORTS) = 6
  368      long so ≥4 short slots stay reserved, and one position per symbol.
  369  
  370      Returns {plans, skipped, summary}; `plans` are the NEW entries this run.
  371      """
  372      from collections import Counter
  373  
  374      max_pos = kw.get("max_positions", _cfg.VIVEK_BOT_MAX_POSITIONS)
  375      min_shorts = kw.get("min_shorts", _cfg.VIVEK_BOT_MIN_SHORTS)
  376      max_long = max(0, max_pos - min_shorts)          # reserve the short slots
  377      plans, skipped = [], []
  378      reasons: Counter = Counter()
  379  
  380      # Seed the counters from the positions ALREADY open in this market, so new
  381      # entries can only fill the remaining capacity.
  382      book = open_book or []
  383      open_syms: set[str] = {str(p.get("symbol") or "").upper() for p in book}
  384      existing = len(book)
  385      longs = sum(1 for p in book if str(p.get("direction")) == "long")
  386      shorts = sum(1 for p in book if str(p.get("direction")) == "short")
  387  
  388      # Correlation control: positions per sector (existing + taken this run), so
  389      # the book can't quietly become one macro bet. Unknown sectors are exempt —
  390      # except crypto, which gets synthetic major/alt buckets via _sector_key.
  391      max_sector = int(kw.get("max_per_sector", getattr(_cfg, "VIVEK_BOT_MAX_PER_SECTOR", 0)) or 0)
  392      sector_counts: Counter = Counter()
  393      for p in book:
  394          sk = _sector_key(p.get("symbol"), p.get("sector"), market)
  395          if sk:
  396              sector_counts[sk] += 1
  397  
  398      # Re-entry cooldown: symbols recently stopped out (supplied by the runner
  399      # from the closed book) are untouchable — no churning the same level.
  400      cooldown_syms = {str(s).upper() for s in (kw.get("cooldown_syms") or ())}
  401  
  402      def drop(out, code, reason):
  403          log.info("SKIP  %-8s [%s] %s", (out.get("plan") or out).get("symbol", "?"), code, reason)
  404          reasons[code] += 1
  405          skipped.append({**out, "take": False, "code": code, "reason": reason, "plan": None})
  406  
  407      for row in rows:
  408          out = plan_trade(row, equity, market=market, prefer_tf=prefer_tf, **{
  409              k: kw[k] for k in ("risk_pct", "min_rr") if k in kw})
  410          if not out.get("plan"):
  411              reasons[out.get("code", "skip")] += 1
  412              skipped.append(out)
  413              continue
  414          sym = str(row.get("symbol") or "").upper()
  415          direction = out["direction"]
  416          sector = _sector_key(sym, row.get("sector"), market)
  417          if sym in open_syms:
  418              drop(out, "dup_symbol", f"already holding {sym}")
  419          elif sym in cooldown_syms:
  420              drop(out, "cooldown", f"{sym} stopped out recently — re-entry cooldown active")
  421          elif longs + shorts >= max_pos:                 # existing + taken so far
  422              drop(out, "book_full", f"already at the {max_pos}-position cap for {market}")
  423          elif direction == "long" and longs >= max_long:
  424              drop(out, "long_cap", f"long cap {max_long} reached — reserving the ≥{min_shorts}-short slots")
  425          elif max_sector and sector and sector_counts[sector] >= max_sector:
  426              drop(out, "sector_cap",
  427                   f"already {sector_counts[sector]} open in '{sector}' — cap {max_sector}/sector")
  428          else:
  429              plans.append(out)
  430              open_syms.add(sym)
  431              if sector:
  432                  sector_counts[sector] += 1
  433              if direction == "long":
  434                  longs += 1
  435              else:
  436                  shorts += 1
  437  
  438      short_bias_met = shorts >= min_shorts
  439      summary = {
  440          "market": market, "setups": len(rows), "existing": existing,
  441          "taken": len(plans), "total_open": longs + shorts,
  442          "longs": longs, "shorts": shorts, "min_shorts": min_shorts,
  443          "short_bias_met": short_bias_met,
  444          "skipped": len(skipped), "skip_reasons": dict(reasons),
  445      }
  446      log.info("VIVEK bot [%s]: +%d new (book %d→%d) — %d long / %d short%s · skips: %s",
  447               market, summary["taken"], existing, summary["total_open"], longs, shorts,
  448               "" if short_bias_met else f"  ⚠ short bias unmet (<{min_shorts})",
  449               summary["skip_reasons"] or "none")
  450      return {"plans": plans, "skipped": skipped, "summary": summary}
```

### `scanner/broker/vivek_run.py`  (451 lines)
> The paper-book runner each scan: download universe, reconcile, open/mark/close. Imports only vivek_bot+vivek_guard (NOT the hardened risk stack).
```python
    1  """VIVEK execution/runner layer — Phase 1–2 (dry-run + paper book).
    2  
    3  This is the thin orchestration layer that sits between the pure decision engine
    4  (`vivek_bot.decide`) and a broker. In Phase 1–2 there is NO broker: it keeps a
    5  persistent PAPER book per market and resolves it with the same intraday
    6  mark-to-market the journal uses. Live execution is deliberately NOT wired here —
    7  the runner refuses to place a real order regardless of config (see the hard
    8  gates below), so this can run on every scan with zero risk.
    9  
   10  What it does each run, per market:
   11  
   12    1. Loads the persistent book (journal/vivek_bot_book.json) — Gap 1. The book
   13       survives across runs, so the 10-position cap, ≥4-short bias and one-per-
   14       symbol rules hold over time, not just within a single scan.
   15    2. Marks every OPEN position to the observed intraday price (reusing the
   16       journal's `_mark` / `manage_position`), booking scale-outs and closing on
   17       stops — but only during the delay-adjusted market session.
   18    3. Asks `vivek_bot.decide(..., open_book=...)` what NEW A+ entries to add,
   19       filling the remaining capacity. New fills enter at the current intraday
   20       price with the journal's don't-chase guard.
   21    4. Writes the book back — UNLESS dry-run is on, in which case it logs the
   22       decisions and leaves the book untouched (final safety gate).
   23  
   24  Every position the runner records carries the entry-type label, timeframe and
   25  grade end-to-end (Gap 3), so the audit trail never loses why a trade was taken.
   26  
   27  SAFETY — three independent gates, all must be cleared for a live order, and the
   28  third is not implemented in this phase so a live order is impossible here:
   29  
   30      VIVEK_BOT_ENABLED       master switch (False → runner is a no-op)
   31      VIVEK_BOT_DRY_RUN       True → decide + log only, never mutate the book
   32      VIVEK_BOT_MODE[market]  "live" is logged and TREATED AS PAPER in this phase
   33      VIVEK_LIVE_CONFIRMED    extra hard lock checked by the (future) broker layer
   34  """
   35  
   36  import datetime as dt
   37  import json
   38  import logging
   39  import pathlib
   40  from zoneinfo import ZoneInfo
   41  
   42  from .. import config
   43  from . import vivek_bot, vivek_guard
   44  from ..vivek_journal import (_apply_costs, _current_price, _mark, _r_of,
   45                               _snapshot, costs_for, market_open)
   46  from ..journal_common import atomic_write
   47  
   48  log = logging.getLogger("vivek_run")
   49  
   50  ROOT = pathlib.Path(__file__).resolve().parents[2]
   51  BOOK_FILE = ROOT / "journal" / "vivek_bot_book.json"
   52  PUBLIC_FILE = ROOT / "public" / "data" / "vivek_bot_book.json"
   53  
   54  BOOK_VERSION = 1
   55  TIMEFRAMES = ("1D", "1W")          # server-side intraday timeframes (4H is browser-only)
   56  MAX_CLOSED = 4000
   57  
   58  
   59  # ── persistence (separate from the signal journal — Decision §9.2) ────────────
   60  
   61  def _load_book() -> dict:
   62      if BOOK_FILE.exists():
   63          try:
   64              b = json.loads(BOOK_FILE.read_text(encoding="utf-8"))
   65              b.setdefault("open", [])
   66              b.setdefault("closed", [])
   67              return b
   68          except Exception:
   69              # Never let a corrupt/half-written book crash the run or get silently
   70              # clobbered — park it for inspection and continue from a clean book.
   71              try:
   72                  bad = BOOK_FILE.with_suffix(".corrupt.json")
   73                  BOOK_FILE.replace(bad)
   74                  log.warning("vivek book corrupt — parked at %s, starting fresh", bad.name)
   75              except Exception:
   76                  pass
   77      return {"version": BOOK_VERSION, "mode": "paper", "open": [], "closed": []}
   78  
   79  
   80  def _save_book(book: dict) -> None:
   81      book["version"] = BOOK_VERSION
   82      book["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
   83      if len(book["closed"]) > MAX_CLOSED:
   84          book["closed"] = book["closed"][-MAX_CLOSED:]
   85      payload = json.dumps(book, indent=2)
   86      atomic_write(BOOK_FILE, payload)
   87      atomic_write(PUBLIC_FILE, payload)
   88  
   89  
   90  def _ticket_to_position(out: dict, entry_price: float, market: str, day: str) -> dict | None:
   91      """Build a paper book position from a decide() plan, filling at the current
   92      intraday price with the journal's don't-chase guard. Carries entry_type +
   93      label + timeframe + grade + sector end-to-end. Returns None to not-chase."""
   94      plan = out["plan"]
   95      tf = plan["timeframe"]
   96      # Reuse the journal's snapshot so the fill model (don't-chase, risk, MAE/MFE,
   97      # ids) is identical to the forward-test journal — single source of truth.
   98      row = {
   99          "symbol": plan["symbol"],
  100          "name": plan.get("name", plan["symbol"]),
  101          "sector": plan.get("sector", ""),   # persists so the sector cap holds across runs
  102          "dir": "SHORT" if plan["direction"] == "short" else "LONG",
  103          "grade": plan["grade"],
  104          "entry_types": [plan["entry_type"]],
  105      }
  106      jplan = {
  107          "stop": plan["stop"], "tp1": plan["tp1"], "tp2": plan["tp2"], "tp3": plan["tp3"],
  108          "scale": plan["scale"], "entry_trigger": plan["entry_type"],
  109          "armed": True, "trigger_bar": plan.get("trigger_bar"),
  110      }
  111      snap = _snapshot(row, tf, jplan, market, entry_price, day)
  112      if snap is None:
  113          return None
  114      # Bolt the bot-specific sizing + the auditable entry-type label onto the
  115      # position so the book records exactly what the bot decided.
  116      snap["entry_type_label"] = plan["entry_type_label"]
  117      snap["units"] = plan["units"]
  118      snap["notional"] = plan["notional"]
  119      snap["leverage"] = plan["leverage"]
  120      snap["leverage_target"] = plan["leverage_target"]
  121      snap["risk_pct"] = plan["risk_pct"]
  122      snap["risk_usd"] = plan["risk_usd"]
  123      snap["source"] = "vivek_bot"
  124      # Signal-vs-fill: record the plan's entry level next to the actual fill so
  125      # the scan-cadence slippage is MEASURED, not assumed. Positive bps = the
  126      # fill was worse than the signal (paid up on a long / sold down on a short).
  127      sig = float(plan.get("entry") or 0)
  128      if sig > 0:
  129          slip_bps = (float(snap["entry"]) - sig) / sig * 1e4
  130          if plan["direction"] == "short":
  131              slip_bps = -slip_bps
  132          snap["signal_entry"] = round(sig, 8)
  133          snap["fill_slip_bps"] = round(slip_bps, 1)
  134      return snap
  135  
  136  
  137  def _close_time_stop(pos: dict, price: float, day: str,
  138                       costs: tuple[float, float] | None) -> None:
  139      """Close a stalled position at the observed price (exit_reason 'time') —
  140      same accounting as the journal's stop-close path."""
  141      is_long = pos.get("direction") == "long"
  142      remaining = round(1.0 - (pos.get("booked_pct") or 0.0), 6)
  143      pos.setdefault("gross_r", pos.get("realized_r", 0.0))
  144      if remaining > 1e-9:
  145          pos.setdefault("exits", []).append(
  146              {"reason": "time", "price": round(price, 8), "pct": remaining, "date": day})
  147          pos["gross_r"] = round(
  148              pos["gross_r"] + remaining * _r_of(price, pos["entry"], pos["risk"], is_long), 4)
  149          pos["booked_pct"] = 1.0
  150      pos["status"] = "closed"
  151      pos["exit_price"] = round(price, 8)
  152      pos["exit_date"] = day
  153      pos["exit_reason"] = "time"
  154      _apply_costs(pos, costs)
  155      try:
  156          pos["hold_days"] = (dt.date.fromisoformat(day)
  157                              - dt.date.fromisoformat(pos["entry_date"])).days
  158      except Exception:
  159          pos["hold_days"] = None
  160  
  161  
  162  def _held_days(pos: dict, day: str) -> int | None:
  163      try:
  164          return (dt.date.fromisoformat(day) - dt.date.fromisoformat(pos["entry_date"])).days
  165      except Exception:
  166          return None
  167  
  168  
  169  def _cooldown_symbols(book: dict, market: str, day: str) -> set[str]:
  170      """Symbols fully stopped out within VIVEK_BOT_REENTRY_COOLDOWN_DAYS of `day`."""
  171      days = int(getattr(config, "VIVEK_BOT_REENTRY_COOLDOWN_DAYS", 0) or 0)
  172      if days <= 0:
  173          return set()
  174      try:
  175          cutoff = (dt.date.fromisoformat(day) - dt.timedelta(days=days)).isoformat()
  176      except ValueError:
  177          return set()
  178      return {str(t.get("symbol") or "").upper()
  179              for t in book.get("closed", [])
  180              if t.get("market") == market and t.get("exit_reason") == "stop"
  181              and cutoff <= str(t.get("exit_date") or "") <= day}
  182  
  183  
  184  def _earnings_within(yf_symbol: str | None, buffer_days: int) -> bool:
  185      """Best-effort: does this name report within `buffer_days`? Fail-OPEN —
  186      any lookup problem returns False so a data hiccup never blocks trading.
  187      Called only for the handful of fills per run, never the universe."""
  188      if not yf_symbol or buffer_days <= 0:
  189          return False
  190      try:
  191          import yfinance as yf
  192          cal = yf.Ticker(yf_symbol).calendar
  193          dates = []
  194          if isinstance(cal, dict):
  195              raw = cal.get("Earnings Date") or []
  196              dates = raw if isinstance(raw, (list, tuple)) else [raw]
  197          elif cal is not None and hasattr(cal, "loc"):        # legacy DataFrame shape
  198              dates = list(cal.loc["Earnings Date"]) if "Earnings Date" in getattr(cal, "index", []) else []
  199          today = dt.date.today()
  200          horizon = today + dt.timedelta(days=buffer_days)
  201          for d in dates:
  202              # Normalise datetime/pandas-Timestamp → plain date. A datetime IS a
  203              # date subclass, so comparing it against a date raises TypeError —
  204              # without this the gate would silently fail-open on Timestamps.
  205              if isinstance(d, dt.datetime):
  206                  d = d.date()
  207              if isinstance(d, dt.date) and today <= d <= horizon:
  208                  return True
  209      except Exception:
  210          pass
  211      return False
  212  
  213  
  214  def _enrich_adv(results: list[dict], frames: dict, yf_map: dict) -> None:
  215      """Stamp row['adv_usd'] (20-day average dollar volume, quote currency) on
  216      each scan row so the decision engine's liquidity gates can read it.
  217      Missing/broken data leaves the row un-stamped (exempt, fail-open)."""
  218      for row in results:
  219          df = frames.get(yf_map.get(row.get("symbol")))
  220          if df is None or "Volume" not in getattr(df, "columns", ()):
  221              continue
  222          try:
  223              tail = df.tail(20)
  224              adv = float((tail["Close"] * tail["Volume"]).mean())
  225              if adv > 0:
  226                  row["adv_usd"] = round(adv, 2)
  227          except Exception:
  228              continue
  229  
  230  
  231  # ── per-market run ────────────────────────────────────────────────────────────
  232  
  233  def run_market(market: str, results: list[dict], frames: dict, universe: list[dict],
  234                 equity: float | None = None, dry_run: bool | None = None,
  235                 now: dt.datetime | None = None) -> dict:
  236      """Run the execution layer for ONE market and return the (updated) book.
  237  
  238      No-op (returns the loaded book unchanged) when VIVEK_BOT_ENABLED is False.
  239      When `dry_run` (defaults to VIVEK_BOT_DRY_RUN) is True it decides + logs but
  240      does NOT write the book — the final safety gate.
  241      """
  242      if not config.VIVEK_BOT_ENABLED:
  243          log.info("vivek_run [%s]: disabled (VIVEK_BOT_ENABLED=False) — no-op", market)
  244          return _load_book()
  245  
  246      equity = config.VIVEK_BOT_ACCOUNT_EQUITY if equity is None else equity
  247      dry_run = config.VIVEK_BOT_DRY_RUN if dry_run is None else dry_run
  248      mode = config.VIVEK_BOT_MODE.get(market, "paper")
  249      # Phase 1–2 NEVER places a live order. A "live" mode is logged loudly and
  250      # treated as paper until the broker layer (Phase 3) is wired and reviewed.
  251      if mode == "live":
  252          if not (config.VIVEK_LIVE_CONFIRMED and not dry_run):
  253              log.warning("vivek_run [%s]: MODE=live but live execution is NOT wired "
  254                          "(LIVE_CONFIRMED=%s, dry_run=%s) — treating as PAPER",
  255                          market, config.VIVEK_LIVE_CONFIRMED, dry_run)
  256          mode = "paper"
  257  
  258      mkt = config.MARKETS[market]
  259      if now is None:
  260          now = dt.datetime.now(ZoneInfo(mkt.timezone))
  261      day = now.strftime("%Y-%m-%d")
  262      is_open = market_open(market, now)
  263      yf_map = {u["symbol"]: u["yf"] for u in universe}
  264      costs = costs_for(market)                         # fees + slippage R-drag (None = off)
  265  
  266      def price_of(sym):
  267          return _current_price(frames, yf_map.get(sym))
  268  
  269      book = _load_book()
  270      book["mode"] = mode
  271  
  272      # 1) manage open positions for THIS market — mark to the observed price.
  273      closed_now = 0
  274      closed_events: list[dict] = []          # for the end-of-run alert digest
  275      still_open = []
  276      max_hold = int(getattr(config, "VIVEK_BOT_MAX_HOLD_DAYS", 0) or 0)
  277      for pos in book["open"]:
  278          if pos.get("market") != market:
  279              still_open.append(pos)
  280              continue
  281          price = price_of(pos["symbol"])
  282          if is_open and price is not None:
  283              _mark(pos, price, day, costs)
  284              # Time stop: hasn't reached TP1 after MAX_HOLD_DAYS → it's going
  285              # nowhere and squatting in a scarce slot. Runners past TP1 are
  286              # exempt (already risk-free). Session-only, like every other fill.
  287              if (pos.get("status") == "open" and max_hold > 0
  288                      and not pos.get("tp1_hit")
  289                      and (_held_days(pos, day) or 0) > max_hold):
  290                  _close_time_stop(pos, price, day, costs)
  291                  log.info("vivek_run [%s]: TIME-STOP %s — %s days without TP1, "
  292                           "closed @ %g (%+.2fR)", market, pos["symbol"],
  293                           _held_days(pos, day), price, pos.get("realized_r") or 0)
  294          if pos.get("status") == "closed":
  295              book["closed"].append(pos)
  296              closed_events.append(pos)
  297              closed_now += 1
  298          else:
  299              # stamp live unrealised P&L so the book/UI/guard can read it
  300              if price is not None:
  301                  ur = vivek_guard._unreal_r(pos, price)
  302                  pos["unreal_r"] = round(ur, 3)
  303                  pos["unreal_usd"] = round(ur * (pos.get("risk_usd", 0.0) or 0.0), 2)
  304              still_open.append(pos)
  305      book["open"] = still_open
  306  
  307      # 2) daily-loss guardrail — once the session is down ≥ the limit, stop adding
  308      #    risk for the rest of the day (open positions are still managed above).
  309      guard = vivek_guard.check(book, market, day, equity, price_of)
  310      book.setdefault("guard", {})[market] = guard
  311      if guard["breached"]:
  312          kind = guard.get("breach_kind") or "daily"
  313          hit_usd = guard["session_usd"] if kind == "daily" else guard.get("week_usd", 0.0)
  314          hit_lim = guard["limit_usd"] if kind == "daily" else guard.get("week_limit_usd", 0.0)
  315          log.warning("vivek_run [%s]: %s-LOSS GUARD — P&L $%.2f ≤ -$%.2f "
  316                      "— halting new entries for %s",
  317                      market, kind.upper(), hit_usd, hit_lim, day)
  318          try:
  319              from .alert_dispatch import send as _alert
  320              _alert("vivek_guard",
  321                     f"VIVEK {kind}-loss guard [{market}] — P&L ${hit_usd:.2f}",
  322                     f"Limit -${hit_lim:.2f}. New entries halted for {day}. "
  323                     f"{'DRY RUN.' if dry_run else 'Paper book — managing open positions only.'}")
  324          except Exception as e:
  325              log.warning("could not send guard alert: %s", e)
  326  
  327      # 3) decide NEW entries against the CURRENT book (caps/short-bias across runs).
  328      # Sector rides along so decide() can enforce the per-sector correlation cap;
  329      # ADV is stamped on the rows for the liquidity gates; recently-stopped
  330      # symbols are handed over for the re-entry cooldown.
  331      _enrich_adv(results, frames, yf_map)
  332      open_book = [{"symbol": p["symbol"], "direction": p["direction"],
  333                    "sector": p.get("sector", "")}
  334                   for p in book["open"] if p.get("market") == market]
  335      decision = vivek_bot.decide(results, equity, market=market, open_book=open_book,
  336                                  cooldown_syms=_cooldown_symbols(book, market, day))
  337  
  338      # 4) fill new entries at the current intraday price (session only, guard clear).
  339      added, chased, earnings_skipped = 0, 0, 0
  340      earnings_gate = (market in (getattr(config, "VIVEK_BOT_EARNINGS_MARKETS", ()) or ()))
  341      earnings_buffer = int(getattr(config, "VIVEK_BOT_EARNINGS_BUFFER_DAYS", 0) or 0)
  342      opened_events: list[dict] = []          # for the end-of-run alert digest
  343      if is_open and not guard["breached"]:
  344          for out in decision["plans"]:
  345              sym = out["plan"]["symbol"]
  346              price = _current_price(frames, yf_map.get(sym))
  347              if price is None:
  348                  continue
  349              # Earnings gap-avoidance (best-effort, fail-open) — only for the
  350              # handful of names actually being filled, never the universe.
  351              if earnings_gate and _earnings_within(yf_map.get(sym), earnings_buffer):
  352                  earnings_skipped += 1
  353                  log.info("SKIP  %-8s [earnings] reports within %dd — gap risk",
  354                           sym, earnings_buffer)
  355                  continue
  356              pos = _ticket_to_position(out, price, market, day)
  357              if pos is None:                              # don't chase
  358                  chased += 1
  359                  continue
  360              # guard against a duplicate already in the persistent book
  361              if any(p["symbol"] == sym and p.get("market") == market for p in book["open"]):
  362                  continue
  363              book["open"].append(pos)
  364              opened_events.append(pos)
  365              added += 1
  366  
  367      book_open = sum(1 for p in book["open"] if p.get("market") == market)
  368      book_short = sum(1 for p in book["open"]
  369                       if p.get("market") == market and p.get("direction") == "short")
  370  
  371      # Book-level snapshot for the UI/header: total open + live unrealised P&L.
  372      book["summary"] = {
  373          "open": len(book["open"]),
  374          "unreal_usd": round(sum(p.get("unreal_usd", 0.0) or 0.0 for p in book["open"]), 2),
  375          "updated_day": day,
  376      }
  377  
  378      if dry_run:
  379          log.info("vivek_run [%s]: DRY-RUN · %s · would add %d, close %d "
  380                   "(book unchanged: %d open, %d short) · decision: %s",
  381                   market, "OPEN" if is_open else "closed-session", added, closed_now,
  382                   book_open, book_short, decision["summary"]["skip_reasons"] or "none")
  383          return book
  384  
  385      _save_book(book)
  386      log.info("vivek_run [%s]: %s · %s · +%d new, %d closed (%d open, %d short)",
  387               market, mode.upper(), "OPEN" if is_open else "closed-session",
  388               added, closed_now, book_open, book_short)
  389  
  390      # Trade-event digest through the shared alert dispatcher. OFF by default:
  391      # the scan workflow exports SMTP creds and alert_dispatch fires every
  392      # configured channel, so this would EMAIL each bot trade event. Flip
  393      # VIVEK_BOT_NOTIFY_TRADES in config when pushes are wanted.
  394      if getattr(config, "VIVEK_BOT_NOTIFY_TRADES", False) and (opened_events or closed_events):
  395          try:
  396              from .alert_dispatch import send as _alert
  397              lines = [f"OPEN  {p['symbol']} {p.get('direction','?')} @ {p.get('entry')} "
  398                       f"({p.get('timeframe','?')} {p.get('entry_type','?')})"
  399                       for p in opened_events]
  400              lines += [f"CLOSE {p['symbol']} {p.get('exit_reason','?')} @ {p.get('exit')} "
  401                        f"→ {(p.get('realized_r') or 0):+.2f}R"     # .get default won't catch a stored None
  402                        for p in closed_events]
  403              _alert("order_placed",
  404                     f"VIVEK bot [{market}]: {len(opened_events)} opened, {len(closed_events)} closed",
  405                     "\n".join(lines))
  406          except Exception as e:                            # alerts must never break a run
  407              log.warning("could not send trade-event alert: %s", e)
  408      return book
  409  
  410  
  411  # ── CLI: dry-run smoke test from the latest scan JSON ─────────────────────────
  412  
  413  def main() -> None:
  414      import argparse
  415  
  416      parser = argparse.ArgumentParser(description="VIVEK execution/runner layer (paper book)")
  417      parser.add_argument("--market", action="append", choices=[*config.MARKETS, "all"],
  418                          help="market(s) to run; default = all")
  419      parser.add_argument("--dry-run", action="store_true",
  420                          help="force dry-run (decide + log only, never write the book)")
  421      parser.add_argument("--live", action="store_true",
  422                          help="force-write the paper book (overrides VIVEK_BOT_DRY_RUN); "
  423                               "still PAPER only — never a real order")
  424      args = parser.parse_args()
  425  
  426      logging.basicConfig(level=logging.INFO, format="%(message)s")
  427      if not config.VIVEK_BOT_ENABLED:
  428          print("VIVEK_BOT_ENABLED is False — runner is a no-op. "
  429                "Set it True in config.py to exercise the paper book.")
  430          return
  431  
  432      dry_run = True if args.dry_run else (False if args.live else None)
  433      markets = list(config.MARKETS) if (not args.market or "all" in args.market) else args.market
  434  
  435      from ..universe import load_universe
  436      from ..data import download, merge_with_cache
  437  
  438      for market_key in markets:
  439          pub = ROOT / "public" / "data" / f"{market_key}_vivek.json"
  440          if not pub.exists():
  441              print(f"[{market_key}] no scan JSON ({pub.name}) — run the scanner first")
  442              continue
  443          results = json.loads(pub.read_text(encoding="utf-8")).get("results", [])
  444          universe = load_universe(market_key, full=True)
  445          fresh = download([u["yf"] for u in universe], period=config.VIVEK_DATA_PERIOD)
  446          frames, _ = merge_with_cache(market_key, fresh, [u["yf"] for u in universe])
  447          run_market(market_key, results, frames, universe, dry_run=dry_run)
  448  
  449  
  450  if __name__ == "__main__":
  451      main()
```

### `scanner/broker/vivek_guard.py`  (97 lines)
> Per-market daily-loss guard for the VIVEK book.
```python
    1  """VIVEK loss guardrails (per market) — daily stop + weekly circuit breaker.
    2  
    3  A small, pure helper the runner consults BEFORE opening new entries. It sums the
    4  session's damage — today's realised P&L on closed positions plus the current
    5  unrealised P&L on open positions — and reports whether it has breached
    6  VIVEK_BOT_MAX_DAILY_LOSS_PCT of equity. Because that guard resets at midnight,
    7  it also runs a WEEKLY breaker: realised P&L over the trailing 7 calendar days
    8  plus open unrealised against VIVEK_BOT_MAX_WEEKLY_LOSS_PCT — five max-loss days
    9  in a row no longer sail through. Either breach halts new entries (open
   10  positions are still managed/closed).
   11  
   12  Kept broker-agnostic and side-effect-free so it is fully unit-testable: it never
   13  touches a file or a broker. The runner owns persistence and any alerting.
   14  """
   15  
   16  import datetime as _dt
   17  
   18  from .. import config
   19  
   20  
   21  def _unreal_r(pos: dict, price: float) -> float:
   22      """Current unrealised R of an open position at `price` (0 on bad risk)."""
   23      risk = pos.get("risk") or 0.0
   24      if risk <= 0:
   25          return 0.0
   26      entry = pos["entry"]
   27      return (price - entry) / risk if pos.get("direction") == "long" else (entry - price) / risk
   28  
   29  
   30  def session_pnl(book: dict, market: str, day: str, price_of) -> dict:
   31      """Today's P&L for `market`: realised on positions closed today + open unrealised.
   32  
   33      `price_of(symbol)` returns the current price or None. P&L is in account
   34      currency, derived from each position's R and its sized `risk_usd`.
   35      """
   36      realised = sum(
   37          (t.get("realized_r", 0.0) or 0.0) * (t.get("risk_usd", 0.0) or 0.0)
   38          for t in book.get("closed", [])
   39          if t.get("market") == market and t.get("exit_date") == day
   40      )
   41      unrealised, open_n = 0.0, 0
   42      for p in book.get("open", []):
   43          if p.get("market") != market:
   44              continue
   45          open_n += 1
   46          price = price_of(p.get("symbol"))
   47          if price is None:
   48              continue
   49          unrealised += _unreal_r(p, price) * (p.get("risk_usd", 0.0) or 0.0)
   50      return {
   51          "realised_usd": round(realised, 2),
   52          "unrealised_usd": round(unrealised, 2),
   53          "session_usd": round(realised + unrealised, 2),
   54          "open": open_n,
   55      }
   56  
   57  
   58  def week_pnl(book: dict, market: str, day: str, unrealised_usd: float) -> float:
   59      """Trailing-7-day P&L: realised on trades closed in the window + open
   60      unrealised (already computed by session_pnl — passed in, not re-priced)."""
   61      try:
   62          cutoff = (_dt.date.fromisoformat(day) - _dt.timedelta(days=7)).isoformat()
   63      except ValueError:
   64          return 0.0
   65      realised = sum(
   66          (t.get("realized_r", 0.0) or 0.0) * (t.get("risk_usd", 0.0) or 0.0)
   67          for t in book.get("closed", [])
   68          if t.get("market") == market and cutoff <= str(t.get("exit_date") or "") <= day
   69      )
   70      return round(realised + unrealised_usd, 2)
   71  
   72  
   73  def check(book: dict, market: str, day: str, equity: float, price_of) -> dict:
   74      """Evaluate the loss guards for `market`.
   75  
   76      Returns {breached, breach_kind, session_usd, limit_usd, week_usd, ...}.
   77      `breached` is True once session P&L ≤ -(equity × MAX_DAILY_LOSS_PCT%) OR
   78      trailing-7-day P&L ≤ -(equity × MAX_WEEKLY_LOSS_PCT%).
   79      """
   80      pnl = session_pnl(book, market, day, price_of)
   81      pct = getattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 0.0) or 0.0
   82      limit = round(equity * (pct / 100.0), 2)
   83      daily_breach = limit > 0 and pnl["session_usd"] <= -limit
   84  
   85      wpct = getattr(config, "VIVEK_BOT_MAX_WEEKLY_LOSS_PCT", 0.0) or 0.0
   86      wlimit = round(equity * (wpct / 100.0), 2)
   87      wusd = week_pnl(book, market, day, pnl["unrealised_usd"])
   88      weekly_breach = wlimit > 0 and wusd <= -wlimit
   89  
   90      return {
   91          "market": market, "day": day,
   92          "breached": daily_breach or weekly_breach,
   93          "breach_kind": ("daily" if daily_breach else "weekly" if weekly_breach else None),
   94          "limit_usd": limit, "limit_pct": pct,
   95          "week_usd": wusd, "week_limit_usd": wlimit, "week_limit_pct": wpct,
   96          **pnl,
   97      }
```


## === C5. BYBIT LIVE ORDER PATH (paper/testnet-gated) ===

### `scanner/broker/bybit_bracket.py`  (163 lines)
> Build/submit a Bybit bracket. Qty/price ladders; double retry loop; orderLinkId.
```python
    1  """Build and submit Bybit USDT-perpetual bracket orders from scalp signals.
    2  
    3  Bybit V5 supports embedded TP/SL on the entry order — cleaner than Alpaca's
    4  separate OCO legs. One order call does everything:
    5    entry (limit or market)
    6      ├── takeProfit  →  limit order auto-placed by Bybit on fill
    7      └── stopLoss    →  stop-market auto-placed by Bybit on fill
    8  
    9  Only crypto signals (asset_type="crypto") are submitted here.
   10  NASDAQ and ASX signals are skipped — those go via IBKR (future).
   11  
   12  Symbol mapping: yfinance "BTC-USD" → Bybit "BTCUSDT" (drop "-USD", add "USDT").
   13  """
   14  
   15  import logging
   16  import os
   17  import time
   18  
   19  from . import bybit_client as bc
   20  from scanner import config
   21  
   22  log = logging.getLogger(__name__)
   23  
   24  _CRYPTO_ASSET_TYPE = "crypto"
   25  
   26  
   27  # ── symbol utilities ──────────────────────────────────────────────────────────
   28  
   29  def to_bybit_symbol(yf_ticker: str) -> str:
   30      """Convert a yfinance crypto ticker to a Bybit linear perpetual symbol.
   31  
   32      "BTC-USD"  → "BTCUSDT"
   33      "ETH-USD"  → "ETHUSDT"
   34      "SOL-USD"  → "SOLUSDT"
   35      """
   36      base = yf_ticker.upper().replace("-USD", "").replace("-USDT", "")
   37      return base + "USDT"
   38  
   39  
   40  def _fmt_qty(qty: float) -> str:
   41      """Format quantity to a reasonable precision for Bybit."""
   42      if qty >= 1000:
   43          return f"{qty:.1f}"
   44      if qty >= 100:
   45          return f"{qty:.2f}"
   46      if qty >= 10:
   47          return f"{qty:.3f}"
   48      if qty >= 1:
   49          return f"{qty:.4f}"
   50      return f"{qty:.5f}"
   51  
   52  
   53  def _fmt_price(price: float) -> str:
   54      """Format price to a reasonable precision for Bybit."""
   55      if price >= 10_000:
   56          return f"{price:.1f}"
   57      if price >= 100:
   58          return f"{price:.2f}"
   59      if price >= 1:
   60          return f"{price:.4f}"
   61      return f"{price:.6f}"
   62  
   63  
   64  def calc_qty(entry: float, notional: float) -> float:
   65      """Position size in base-asset units given notional dollar exposure (legacy)."""
   66      return notional / entry if entry > 0 else 0.0
   67  
   68  
   69  def calc_qty_risk(entry: float, stop: float, risk_per_trade: float) -> float:
   70      """ATR/stop-based position sizing: risk a fixed dollar amount per trade.
   71  
   72      qty = risk_per_trade / |entry - stop|
   73  
   74      This gives consistent dollar risk per trade regardless of instrument
   75      volatility, unlike fixed-notional sizing which lets risk vary with ATR.
   76      Falls back to 0.0 if stop == entry (zero risk distance) or entry <= 0.
   77      """
   78      stop_dist = abs(entry - stop)
   79      if stop_dist <= 0 or entry <= 0:
   80          return 0.0
   81      return risk_per_trade / stop_dist
   82  
   83  
   84  def _order_link_id(symbol: str, direction: str, session_day: str) -> str:
   85      """Deterministic client order ID — prevents double-submission on retried scans."""
   86      raw = f"{symbol}_{direction}_{session_day}"
   87      return raw[:36]   # Bybit max = 36 chars
   88  
   89  
   90  # ── order submission ──────────────────────────────────────────────────────────
   91  
   92  def submit(pos: dict) -> dict:
   93      """Submit a bracket entry order to Bybit with embedded TP and SL.
   94  
   95      pos keys expected:
   96        symbol, direction, entry, stop, target, units, session_day, asset_type
   97  
   98      Returns:
   99        {"order_id": ..., "order_link_id": ..., "status": "New"}  on success
  100        {"skipped": True, "reason": "..."}                         on skip/error
  101      """
  102      asset_type = pos.get("asset_type", "").lower()
  103      if asset_type != _CRYPTO_ASSET_TYPE:
  104          return {
  105              "skipped": True,
  106              "reason":  f"asset_type='{asset_type}' not supported by Bybit broker "
  107                         "(only crypto; use IBKR for ASX/commodities)",
  108          }
  109  
  110      direction = pos["direction"].lower()
  111      symbol    = to_bybit_symbol(pos["symbol"])
  112      side      = "Buy" if direction == "long" else "Sell"
  113      entry     = float(pos["entry"])
  114      stop      = float(pos["stop"])
  115      target    = float(pos["target"])
  116      units     = float(pos.get("units", 0))
  117      sess_day  = pos.get("session_day", "")
  118  
  119      if units <= 0:
  120          return {"skipped": True, "reason": "units=0, position too small"}
  121  
  122      order_link_id = _order_link_id(symbol, direction, sess_day)
  123  
  124      order_kwargs = dict(
  125          category="linear",
  126          symbol=symbol,
  127          side=side,
  128          orderType="Limit",
  129          qty=_fmt_qty(units),
  130          price=_fmt_price(entry),
  131          timeInForce="GTC",
  132          orderLinkId=order_link_id,
  133          takeProfit=_fmt_price(target),
  134          stopLoss=_fmt_price(stop),
  135          tpTriggerBy="LastPrice",
  136          slTriggerBy="LastPrice",
  137          tpslMode="Full",
  138      )
  139  
  140      result   = None
  141      last_exc = None
  142      attempts = config.ORDER_RETRY_ATTEMPTS
  143      for attempt in range(1, attempts + 1):
  144          try:
  145              result = bc.place_order(**order_kwargs)
  146              break
  147          except Exception as e:
  148              last_exc = e
  149              if attempt < attempts:
  150                  wait = config.ORDER_RETRY_BACKOFF_BASE ** attempt
  151                  log.warning("order attempt %d/%d failed (%s) — retrying in %ds",
  152                              attempt, attempts, e, wait)
  153                  time.sleep(wait)
  154  
  155      if result is None:
  156          return {"skipped": True, "reason": f"Bybit API error after {attempts} attempts: {last_exc}"}
  157  
  158      return {
  159          "order_id":      result.get("orderId", ""),
  160          "order_link_id": result.get("orderLinkId", order_link_id),
  161          "bybit_symbol":  symbol,
  162          "status":        result.get("orderStatus", "New"),
  163      }
```

### `scanner/broker/bybit_client.py`  (216 lines)
> pybit HTTP wrapper + _retry.
```python
    1  """Thin wrapper around the Bybit V5 Unified Trading API.
    2  
    3  Auth via env vars:
    4    BYBIT_API_KEY       Bybit key ID (always required)
    5  
    6    RSA auth (new Bybit API keys — paste public key on Bybit, store private key here):
    7    BYBIT_PRIVATE_KEY   Full PEM content of your private key
    8                        (-----BEGIN RSA PRIVATE KEY----- ... -----END RSA PRIVATE KEY-----)
    9  
   10    HMAC auth (older keys that have an API secret):
   11    BYBIT_API_SECRET    Bybit secret key
   12  
   13    RSA is used when BYBIT_PRIVATE_KEY is set; HMAC otherwise.
   14  
   15  Mode:
   16    BYBIT_TESTNET=false  → live endpoint (api.bybit.com)
   17    default              → testnet endpoint (api-testnet.bybit.com)  ← safe default
   18  
   19  Create testnet API keys at: https://testnet.bybit.com/app/user/api-management
   20  Create live API keys at:    https://www.bybit.com/app/user/api-management
   21  
   22  Permissions needed on the key (Unified Trading, Read-Write):
   23    - Orders + Positions
   24  DO NOT grant Withdrawal permissions.
   25  
   26  NB: every public call routes through _retry() for exponential-backoff on
   27  transient network/API errors. Do not add un-retried duplicates of these
   28  functions — a previous version shadowed the retry-wrapped copies, silently
   29  disabling retries on the live order path.
   30  """
   31  
   32  import logging
   33  import os
   34  import time
   35  
   36  from pybit.unified_trading import HTTP
   37  
   38  from scanner import config as _cfg
   39  
   40  log = logging.getLogger(__name__)
   41  
   42  
   43  def _testnet() -> bool:
   44      return os.environ.get("BYBIT_TESTNET", "true").lower() != "false"
   45  
   46  
   47  def _session() -> HTTP:
   48      api_key     = os.environ["BYBIT_API_KEY"]
   49      private_key = os.environ.get("BYBIT_PRIVATE_KEY", "").strip()
   50      api_secret  = os.environ.get("BYBIT_API_SECRET", "").strip()
   51  
   52      if private_key:
   53          # RSA auth — new Bybit API keys use RSA public/private key pairs
   54          return HTTP(
   55              testnet=_testnet(),
   56              api_key=api_key,
   57              private_key=private_key,
   58          )
   59      else:
   60          # HMAC auth — older Bybit API keys with an API secret
   61          return HTTP(
   62              testnet=_testnet(),
   63              api_key=api_key,
   64              api_secret=api_secret,
   65          )
   66  
   67  
   68  def _retry(fn, *args, **kwargs):
   69      """Call fn(*args, **kwargs) with exponential-backoff retry on failure.
   70  
   71      Reads ORDER_RETRY_ATTEMPTS (default 3) and ORDER_RETRY_BACKOFF_BASE
   72      (default 2) from config.  Sleep schedule: 2s, 4s, 8s for base=2.
   73      Re-raises the final exception if all attempts are exhausted.
   74      """
   75      attempts = int(_cfg.ORDER_RETRY_ATTEMPTS)
   76      base     = float(_cfg.ORDER_RETRY_BACKOFF_BASE)
   77  
   78      last_exc: Exception | None = None
   79      for attempt in range(1, attempts + 1):
   80          try:
   81              return fn(*args, **kwargs)
   82          except Exception as exc:
   83              last_exc = exc
   84              if attempt == attempts:
   85                  log.error(
   86                      "Bybit API failed after %d attempt(s): %s",
   87                      attempts, exc,
   88                  )
   89                  raise
   90              wait = base ** attempt
   91              log.warning(
   92                  "Bybit API error (attempt %d/%d): %s — retrying in %.0fs",
   93                  attempt, attempts, exc, wait,
   94              )
   95              time.sleep(wait)
   96  
   97      raise last_exc  # unreachable; satisfies type checkers
   98  
   99  
  100  # ── order management ──────────────────────────────────────────────────────────
  101  
  102  def place_order(**kwargs) -> dict:
  103      return _retry(lambda: _session().place_order(**kwargs))["result"]
  104  
  105  
  106  def cancel_order(symbol: str, order_id: str) -> dict:
  107      return _retry(
  108          lambda: _session().cancel_order(
  109              category="linear", symbol=symbol, orderId=order_id
  110          )
  111      )["result"]
  112  
  113  
  114  def cancel_all_orders(symbol: str | None = None) -> dict:
  115      kwargs = {"category": "linear", "settleCoin": "USDT"}
  116      if symbol:
  117          kwargs["symbol"] = symbol
  118      return _retry(lambda: _session().cancel_all_orders(**kwargs))["result"]
  119  
  120  
  121  # ── position management ───────────────────────────────────────────────────────
  122  
  123  def get_positions(symbol: str | None = None) -> list[dict]:
  124      kwargs = {"category": "linear", "settleCoin": "USDT"}
  125      if symbol:
  126          kwargs["symbol"] = symbol
  127      return _retry(lambda: _session().get_positions(**kwargs))["result"].get("list", [])
  128  
  129  
  130  def close_position(symbol: str, side: str, qty: str) -> dict:
  131      """Close an open position with a market order (reduceOnly).
  132  
  133      side: "Buy" or "Sell" — must be the OPPOSITE of the position's side.
  134      """
  135      return _retry(
  136          lambda: _session().place_order(
  137              category="linear",
  138              symbol=symbol,
  139              side=side,
  140              orderType="Market",
  141              qty=qty,
  142              reduceOnly=True,
  143              timeInForce="IOC",
  144          )
  145      )["result"]
  146  
  147  
  148  def close_all_positions() -> list[dict]:
  149      """Flatten every open linear position with a market reduceOnly order."""
  150      positions = get_positions()
  151      results = []
  152      for p in positions:
  153          size = p.get("size", "0")
  154          if float(size) == 0:
  155              continue
  156          pos_side   = p.get("side", "")
  157          close_side = "Sell" if pos_side == "Buy" else "Buy"
  158          symbol     = p["symbol"]
  159          try:
  160              r = close_position(symbol, close_side, size)
  161              results.append({"symbol": symbol, "result": r})
  162              log.info("bybit: closed %s %s %s", symbol, pos_side, size)
  163          except Exception as e:
  164              results.append({"symbol": symbol, "error": str(e)})
  165              log.error("bybit: ERROR closing %s: %s", symbol, e)
  166      return results
  167  
  168  
  169  # ── order status ─────────────────────────────────────────────────────────────
  170  
  171  def get_order_status(symbol: str, order_id: str) -> dict:
  172      """Fetch current status of a specific order (open or historical)."""
  173      sess = _session()
  174  
  175      def _fetch():
  176          resp = sess.get_open_orders(category="linear", symbol=symbol, orderId=order_id)
  177          orders = resp["result"].get("list", [])
  178          if orders:
  179              return orders[0]
  180          resp2 = sess.get_order_history(
  181              category="linear", symbol=symbol, orderId=order_id, limit=1
  182          )
  183          hist = resp2["result"].get("list", [])
  184          return hist[0] if hist else {}
  185  
  186      return _retry(_fetch)
  187  
  188  
  189  # ── closed P&L history ────────────────────────────────────────────────────────
  190  
  191  def get_closed_pnl(symbol: str | None = None, limit: int = 50) -> list[dict]:
  192      """Recent closed position P&L records — used by reconcile to detect exits."""
  193      kwargs = {"category": "linear", "limit": limit}
  194      if symbol:
  195          kwargs["symbol"] = symbol
  196      return _retry(lambda: _session().get_closed_pnl(**kwargs))["result"].get("list", [])
  197  
  198  
  199  # ── account info ──────────────────────────────────────────────────────────────
  200  
  201  def wallet_balance() -> dict:
  202      def _fetch():
  203          resp  = _session().get_wallet_balance(accountType="UNIFIED")
  204          coins = resp["result"].get("list", [{}])[0].get("coin", [])
  205          usdt  = next((c for c in coins if c["coin"] == "USDT"), {})
  206          return {
  207              "equity":     float(usdt.get("equity", 0)),
  208              "available":  float(usdt.get("availableToWithdraw", 0)),
  209              "unrealised": float(usdt.get("unrealisedPnl", 0)),
  210          }
  211  
  212      return _retry(_fetch)
  213  
  214  
  215  def mode() -> str:
  216      return "TESTNET" if _testnet() else "LIVE ⚠️"
```

### `scanner/broker/bybit_reconcile.py`  (159 lines)
> Bybit -> journal sync. exitType/execType; fee model; open-list-only.
```python
    1  """Sync Bybit position and closed-PnL state into the scalp journal.
    2  
    3  Bybit is ground truth. The journal mirrors it, never leads it.
    4  
    5  Called at the start of every bybit_run invocation so the journal always
    6  reflects what the broker actually holds before new orders go in.
    7  
    8  State transitions handled:
    9    position exists at Bybit, size > 0  → keep open, update unrealised PnL
   10    position closed (not in Bybit list)  → look up closed_pnl, mark closed
   11    order still pending (not filled yet) → keep as open with broker_status="pending"
   12  """
   13  
   14  import datetime as dt
   15  import logging
   16  
   17  from . import bybit_client as bc
   18  from .bybit_bracket import to_bybit_symbol
   19  from scanner.scalp_journal import BROK_RT
   20  
   21  log = logging.getLogger(__name__)
   22  
   23  
   24  def _now_ts() -> str:
   25      return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
   26  
   27  
   28  def _positions_by_symbol(positions: list[dict]) -> dict[str, dict]:
   29      """Index Bybit positions by symbol, ignoring zero-size entries."""
   30      out = {}
   31      for p in positions:
   32          if float(p.get("size", 0)) != 0:
   33              out[p["symbol"]] = p
   34      return out
   35  
   36  
   37  def _find_closed_pnl(symbol: str, direction: str, closed_records: list[dict]) -> dict | None:
   38      """Find the most recent closed-PnL record matching symbol + direction."""
   39      wanted_side = "Buy" if direction == "long" else "Sell"
   40      matches = [
   41          r for r in closed_records
   42          if r.get("symbol") == symbol and r.get("side") == wanted_side
   43      ]
   44      if not matches:
   45          return None
   46      # Bybit returns records newest-first
   47      return matches[0]
   48  
   49  
   50  def reconcile_journal(j: dict) -> dict:
   51      """Mutate the journal in-place: sync every Bybit-tracked open position."""
   52  
   53      # Fetch current state once
   54      try:
   55          live_positions = bc.get_positions()
   56      except Exception as e:
   57          log.error("could not fetch Bybit positions: %s", e)
   58          return j
   59  
   60      try:
   61          closed_pnl_records = bc.get_closed_pnl(limit=50)
   62      except Exception as e:
   63          log.warning("could not fetch Bybit closed PnL: %s", e)
   64          closed_pnl_records = []
   65  
   66      pos_index = _positions_by_symbol(live_positions)
   67      now_ts    = _now_ts()
   68      survivors = []
   69  
   70      for pos in j.get("open", []):
   71          # Journal positions without a Bybit order ID are paper-only — leave untouched
   72          if not pos.get("broker_order_id"):
   73              survivors.append(pos)
   74              continue
   75  
   76          bybit_sym = pos.get("bybit_symbol") or to_bybit_symbol(pos["symbol"])
   77          direction = pos.get("direction", "long")
   78          live      = pos_index.get(bybit_sym)
   79  
   80          if live:
   81              # Position still open at Bybit — update P&L and position-level risk metrics
   82              unreal     = float(live.get("unrealisedPnl", 0))
   83              avg_price  = float(live.get("avgPrice", 0))   # actual average fill price
   84              mark_price = float(live.get("markPrice", 0))  # current mark price
   85  
   86              entry    = float(pos.get("entry", 0))
   87              stop_p   = float(pos["stop"])
   88              target_p = float(pos["target"])
   89              risk_usd = float(pos.get("risk_per_trade") or
   90                               abs(entry - stop_p) * float(pos.get("units", 1)))
   91  
   92              stop_dist_pct   = (abs(mark_price - stop_p) / mark_price * 100
   93                                 if mark_price > 0 else 0.0)
   94              target_dist_pct = (abs(target_p - mark_price) / mark_price * 100
   95                                 if mark_price > 0 else 0.0)
   96              current_r       = round(unreal / risk_usd, 2) if risk_usd > 0 else 0.0
   97  
   98              fill_price = avg_price if avg_price > 0 else pos.get("fill_price")
   99  
  100              survivors.append({
  101                  **pos,
  102                  "unreal_pnl":       round(unreal, 2),
  103                  "broker_status":    "open",
  104                  "fill_price":       (round(fill_price, 8) if fill_price else pos.get("fill_price")),
  105                  "mark_price":       (round(mark_price, 6) if mark_price else None),
  106                  "current_r":        current_r,
  107                  "stop_dist_pct":    round(stop_dist_pct, 2),
  108                  "target_dist_pct":  round(target_dist_pct, 2),
  109              })
  110              continue
  111  
  112          # Position is gone from Bybit — find out why via closed_pnl
  113          closed_rec = _find_closed_pnl(bybit_sym, direction, closed_pnl_records)
  114  
  115          if closed_rec:
  116              closed_pnl = float(closed_rec.get("closedPnl", 0))
  117              exit_type  = closed_rec.get("exitType", "unknown")
  118              reason_map = {
  119                  "takeProfit":        "target",
  120                  "StopLoss":          "stop",
  121                  "Liq":               "liquidated",
  122                  "BustTrade":         "liquidated",
  123                  "PartialTakeProfit": "target",
  124              }
  125              reason = reason_map.get(exit_type, exit_type.lower())
  126              pnl    = round(closed_pnl - BROK_RT, 2)
  127  
  128              fill_price = float(pos.get("fill_price") or pos["entry"])
  129              stop       = float(pos["stop"])
  130              risk       = abs(fill_price - stop)
  131              r_val      = (round(closed_pnl / (risk * float(pos.get("units", 1))), 2)
  132                            if risk > 0 else 0.0)
  133  
  134              # Detect fill-price divergence from intended entry
  135              intended = float(pos["entry"])
  136              slip_pct = abs(fill_price - intended) / intended * 100 if intended > 0 else 0.0
  137  
  138              log.info("%s %s → %s  pnl=$%.2f  r=%.2f  slip=%.2f%%",
  139                       pos["symbol"], direction, reason, pnl, r_val, slip_pct)
  140  
  141              j["closed"].append({
  142                  **pos,
  143                  "status":        "closed",
  144                  "exit_ts":       now_ts,
  145                  "reason":        reason,
  146                  "pnl":           pnl,
  147                  "r":             r_val,
  148                  "fill_price":    pos.get("fill_price"),
  149                  "entry_slip_pct": round(slip_pct, 3),
  150                  "broker_status": "closed",
  151              })
  152          else:
  153              # No closed record found yet — order may not have filled
  154              log.warning("%s not in live positions and no closed record "
  155                          "— keeping open (may be pending entry)", pos["symbol"])
  156              survivors.append({**pos, "broker_status": "pending"})
  157  
  158      j["open"] = survivors
  159      return j
```


## === C6. HARDENED RISK STACK (only wired into the scalp path today) ===

### `scanner/broker/pre_trade_check.py`  (174 lines)
> 12-gate pre-trade validation.
```python
    1  """Pre-trade risk gate — runs before every order submission (Phase 5).
    2  
    3  Single entry point: pre_trade_check(pos, journal, sess_day) returns
    4  {ok, reason, checks, failed} so bybit_run.py makes one go/no-go call.
    5  
    6  Checks (in order):
    7    1.  portfolio_heat   — total open risk % of account (PORTFOLIO_HEAT_LIMIT)
    8    2.  max_positions    — hard cap on concurrent open positions (MAX_OPEN_POSITIONS)
    9    3.  drawdown         — equity drawdown circuit breaker (MAX_DRAWDOWN_PAUSE/CLOSE)
   10    4.  consec_losses    — consecutive loss circuit breaker (CONSEC_LOSS_PAUSE)
   11    5.  daily_loss       — session P&L vs daily loss cap (SCALP_MAX_DAILY_LOSS)
   12    6.  daily_cap        — trade count vs daily trade cap (SCALP_MAX_TRADES_PER_DAY)
   13    7.  corr_cap         — correlation group position limit (SCALP_MAX_PER_GROUP)
   14    8.  sector_cap       — sector/theme exposure limit (SECTOR_EXPOSURE_CAP)
   15    9.  order_size       — fat-finger / minimum notional guard
   16    10. max_capital      — total open notional vs MAX_MANAGED_CAPITAL_USD cap
   17    11. slippage         — expected slippage tolerance (warn/reject)
   18  
   19  bybit_run.py still owns the "already_open" and "not_crypto" gates since those
   20  are signal-selection concerns, not portfolio risk.
   21  """
   22  
   23  import logging
   24  from scanner import config as _cfg
   25  from scanner.scalp_journal import _session_day, _corr_group, MAX_GROUP
   26  from scanner.broker.risk_manager import (
   27      check_portfolio_heat,
   28      check_drawdown,
   29      check_sector_cap,
   30      check_max_positions,
   31      check_order_size,
   32      check_max_capital,
   33      check_htf_bias,
   34  )
   35  from scanner.broker.circuit_breaker import check_consecutive_losses
   36  
   37  log = logging.getLogger(__name__)
   38  
   39  
   40  def pre_trade_check(
   41      pos: dict,
   42      journal: dict,
   43      sess_day: str = "",
   44      submitted_this_run: int = 0,
   45      bias_map: dict | None = None,
   46  ) -> dict:
   47      """Return {ok, reason, checks, failed} for a candidate position.
   48  
   49      pos  — proposed position dict; must include at minimum:
   50               symbol, direction, entry, stop, units, risk_per_trade,
   51               sector (or corr_group), asset_type
   52      journal — live scalp journal dict (open + closed lists)
   53      sess_day — optional session-day override (YYYY-MM-DD); defaults to today
   54      submitted_this_run — orders already submitted in the current bybit_run loop
   55      bias_map — optional {symbol: {weekly, threeDay}} HTF bias map; pass None to
   56                 skip the bias check (treated as "no data — allowed")
   57      """
   58      if not sess_day:
   59          sess_day = _session_day()
   60  
   61      today_closed = [
   62          c for c in journal.get("closed", [])
   63          if c.get("session_day") == sess_day and not c.get("skip_daily_count")
   64      ]
   65      # today_open filters by session_day intentionally: overnight holds opened on a
   66      # previous session day are NOT counted here because the daily trade cap (check 6)
   67      # tracks new trades entered today, not total open positions.  Those older
   68      # positions ARE counted by portfolio_heat (check 1) and max_positions (check 2),
   69      # which use all open positions regardless of when they were opened.
   70      today_open  = [p for p in journal.get("open", []) if p.get("session_day") == sess_day]
   71      today_pnl   = sum(c.get("pnl", 0) for c in today_closed)
   72      trades_used = len(today_closed) + len(today_open) + submitted_this_run
   73  
   74      symbol    = pos.get("symbol", "?")
   75      direction = pos.get("direction", "?")
   76      entry     = float(pos.get("entry", 0))
   77      units     = float(pos.get("units", 0))
   78      checks: dict[str, dict] = {}
   79  
   80      # 1. Portfolio heat
   81      checks["portfolio_heat"] = check_portfolio_heat(journal.get("open", []))
   82  
   83      # 2. Max open positions
   84      checks["max_positions"] = check_max_positions(journal)
   85  
   86      # 3. Drawdown circuit breaker
   87      checks["drawdown"] = check_drawdown(journal)
   88  
   89      # 4. Consecutive loss circuit breaker
   90      checks["consec_losses"] = check_consecutive_losses(journal)
   91  
   92      # 5. Daily session loss
   93      max_loss = float(_cfg.SCALP_MAX_DAILY_LOSS)
   94      if today_pnl < -max_loss:
   95          checks["daily_loss"] = {
   96              "ok": False,
   97              "reason": f"session P&L ${today_pnl:.2f} < -${max_loss:.0f}",
   98          }
   99      else:
  100          checks["daily_loss"] = {"ok": True}
  101  
  102      # 6. Daily trade cap
  103      max_daily = int(_cfg.SCALP_MAX_TRADES_PER_DAY)
  104      if trades_used >= max_daily:
  105          checks["daily_cap"] = {
  106              "ok": False,
  107              "reason": f"daily cap ({max_daily}) reached — {trades_used} trades used",
  108          }
  109      else:
  110          checks["daily_cap"] = {"ok": True}
  111  
  112      # 7. Correlation group cap
  113      group = _corr_group(symbol, pos.get("asset_type", ""), pos.get("sector", ""))
  114      group_n = sum(
  115          1 for p in journal.get("open", [])
  116          if (p.get("corr_group") or _corr_group(
  117              p["symbol"], p.get("asset_type", ""), p.get("sector", "")
  118          )) == group
  119      )
  120      if group_n >= MAX_GROUP:
  121          checks["corr_cap"] = {
  122              "ok": False,
  123              "reason": f"corr group '{group}' at cap ({group_n}/{MAX_GROUP})",
  124          }
  125      else:
  126          checks["corr_cap"] = {"ok": True}
  127  
  128      # 8. Sector exposure cap
  129      checks["sector_cap"] = check_sector_cap(journal.get("open", []), pos)
  130  
  131      # 9. Order size validation
  132      checks["order_size"] = check_order_size(units, entry)
  133  
  134      # 10. Max managed capital cap
  135      checks["max_capital"] = check_max_capital(journal)
  136  
  137      # 11. Slippage tolerance
  138      slippage_pct  = float(pos.get("slippage_pct", 0))
  139      reject_slip   = float(_cfg.SLIPPAGE_REJECT_PCT)
  140      warn_slip     = float(_cfg.SLIPPAGE_WARN_PCT)
  141      if slippage_pct > reject_slip:
  142          checks["slippage"] = {
  143              "ok": False,
  144              "reason": f"slippage {slippage_pct:.2%} > reject threshold {reject_slip:.2%}",
  145          }
  146      elif slippage_pct > warn_slip:
  147          log.warning("slippage warn: %s %.2f%% > warn threshold %.2f%%",
  148                      symbol, slippage_pct * 100, warn_slip * 100)
  149          checks["slippage"] = {"ok": True}
  150      else:
  151          checks["slippage"] = {"ok": True}
  152  
  153      # 12. HTF bias alignment (Weekly + 3D must not oppose direction)
  154      checks["htf_bias"] = check_htf_bias(symbol, direction, bias_map or {})
  155  
  156      # Aggregate
  157      failed = {k: v for k, v in checks.items() if not v.get("ok")}
  158      ok     = len(failed) == 0
  159  
  160      if ok:
  161          log.info("pre-trade OK  %s %s  trades_used=%d  heat=%.1f%%  dd=%.1f%%",
  162                   symbol, direction, trades_used,
  163                   checks["portfolio_heat"].get("heat", 0) * 100,
  164                   checks["drawdown"].get("dd", 0) * 100)
  165      else:
  166          reasons = "; ".join(v.get("reason", k) for k, v in failed.items())
  167          log.warning("pre-trade BLOCKED  %s %s  — %s", symbol, direction, reasons)
  168  
  169      return {
  170          "ok":     ok,
  171          "checks": checks,
  172          "failed": list(failed.keys()),
  173          "reason": "; ".join(v.get("reason", "") for v in failed.values()) if not ok else "",
  174      }
```

### `scanner/broker/circuit_breaker.py`  (176 lines)
> Consecutive-loss / drawdown / anomaly halts.
```python
    1  """Circuit breakers — safety layers beyond the daily kill-switch (Phase 5).
    2  
    3  check_consecutive_losses()   — pause after N consecutive losing trades
    4  check_drawdown_breaker()     — pause/close at drawdown thresholds (wraps risk_manager)
    5  check_anomaly_breaker()      — pause if anomaly detector has fired
    6  check_all()                  — run all circuit breakers and return aggregated result
    7  
    8  Self-healing notifications: check_all() persists breaker state in
    9  journal/alert_state.json["cb_state"] and logs INFO (+ smart_send) whenever a
   10  previously-fired breaker transitions back to ok=True.
   11  """
   12  
   13  import json
   14  import logging
   15  import pathlib
   16  
   17  from scanner import config as _cfg
   18  from scanner.journal_common import atomic_write as _atomic_write
   19  
   20  log  = logging.getLogger(__name__)
   21  ROOT = pathlib.Path(__file__).resolve().parents[2]
   22  _STATE_FILE = ROOT / "journal" / "alert_state.json"
   23  
   24  
   25  def _load_cb_state() -> dict:
   26      if _STATE_FILE.exists():
   27          try:
   28              data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
   29              return data.get("cb_state", {})
   30          except Exception:
   31              pass
   32      return {}
   33  
   34  
   35  def _save_cb_state(cb_state: dict) -> None:
   36      _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
   37      try:
   38          if _STATE_FILE.exists():
   39              data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
   40          else:
   41              data = {}
   42      except Exception:
   43          data = {}
   44      data["cb_state"] = cb_state
   45      try:
   46          _atomic_write(_STATE_FILE, json.dumps(data, indent=2))
   47      except Exception as e:
   48          log.warning("circuit_breaker: could not save state: %s", e)
   49  
   50  
   51  def check_consecutive_losses(journal: dict) -> dict:
   52      """Pause if the last N closed trades are all losses.
   53  
   54      N is controlled by config.CONSEC_LOSS_PAUSE (default 4).
   55      Trades flagged skip_daily_count (stop-gaps) are excluded.
   56      """
   57      n_required = int(_cfg.CONSEC_LOSS_PAUSE)
   58      closed = [t for t in journal.get("closed", []) if not t.get("skip_daily_count")]
   59  
   60      if len(closed) < n_required:
   61          return {"ok": True, "consec_losses": 0, "threshold": n_required, "reason": ""}
   62  
   63      recent   = closed[-n_required:]
   64      n_losses = sum(1 for t in recent if t.get("pnl", 0) < 0)
   65      fired    = n_losses >= n_required
   66  
   67      if fired:
   68          log.warning("CONSECUTIVE LOSS BREAKER — last %d trades all losses (threshold %d)",
   69                      n_losses, n_required)
   70          try:
   71              from .alert_dispatch import send as _alert
   72              _alert(
   73                  "anomaly",
   74                  f"Consecutive loss circuit breaker fired",
   75                  f"Last {n_required} trades were all losses. New orders paused until reviewed.",
   76              )
   77          except Exception:
   78              pass
   79  
   80      return {
   81          "ok":            not fired,
   82          "consec_losses": n_losses,
   83          "threshold":     n_required,
   84          "reason":        f"last {n_losses} consecutive losses ≥ threshold {n_required}" if fired else "",
   85      }
   86  
   87  
   88  def check_drawdown_breaker(journal: dict) -> dict:
   89      """Drawdown circuit breaker — delegates to risk_manager.check_drawdown and
   90      fires an alert when it triggers."""
   91      from .risk_manager import check_drawdown
   92      result = check_drawdown(journal)
   93      if not result["ok"]:
   94          try:
   95              from .alert_dispatch import send as _alert
   96              _alert(
   97                  "anomaly",
   98                  f"Drawdown circuit breaker: {result['action']}",
   99                  f"Drawdown {result['dd']:.1%} — "
  100                  f"pause threshold {result['pause_threshold']:.0%}, "
  101                  f"close threshold {result['close_threshold']:.0%}.",
  102              )
  103          except Exception:
  104              pass
  105      return result
  106  
  107  
  108  def check_anomaly_breaker(last_anomaly_fired: bool = False) -> dict:
  109      """Block new trades if the anomaly detector has recently fired.
  110  
  111      Controlled by config.ANOMALY_PAUSE_ON_TRIGGER (default True).
  112      Pass last_anomaly_fired=True when the anomaly module returned alerts on
  113      the current run.
  114      """
  115      if not _cfg.ANOMALY_PAUSE_ON_TRIGGER:
  116          return {"ok": True, "paused": False, "reason": ""}
  117      if last_anomaly_fired:
  118          log.warning("ANOMALY CIRCUIT BREAKER — anomaly detected, pausing new trades")
  119          return {
  120              "ok":     False,
  121              "paused": True,
  122              "reason": "anomaly detection fired — pausing new trades until next scan",
  123          }
  124      return {"ok": True, "paused": False, "reason": ""}
  125  
  126  
  127  def check_all(journal: dict, last_anomaly_fired: bool = False) -> dict:
  128      """Run all circuit breakers; return aggregated {ok, checks, failed, reason}.
  129  
  130      All three checks always run unconditionally so the caller gets a complete
  131      picture of every active breaker in a single call.  Alerts may fire in
  132      multiple checks on the same run — that is intentional (each breaker owns its
  133      own alert so the log contains a full diagnosis).
  134  
  135      Self-healing: when a breaker that was previously fired is now clear, an INFO
  136      log + smart_send("info", ...) is emitted so the operator knows the condition
  137      resolved without manual intervention.
  138      """
  139      prev_state = _load_cb_state()
  140  
  141      checks: dict[str, dict] = {}
  142      checks["consecutive_losses"] = check_consecutive_losses(journal)
  143      checks["drawdown"]           = check_drawdown_breaker(journal)
  144      checks["anomaly"]            = check_anomaly_breaker(last_anomaly_fired)
  145  
  146      # Detect cleared breakers (was fired → now ok)
  147      for name, result in checks.items():
  148          was_fired = prev_state.get(name, False)
  149          now_ok    = result.get("ok", True)
  150          if was_fired and now_ok:
  151              log.info("CIRCUIT BREAKER CLEARED: %s — trading may resume", name)
  152              try:
  153                  from .alert_router import smart_send
  154                  smart_send(
  155                      "info",
  156                      f"Circuit breaker cleared: {name}",
  157                      "The condition that triggered this breaker has resolved. Trading may resume.",
  158                  )
  159              except Exception:
  160                  pass
  161  
  162      # Persist current fired-state for next run
  163      _save_cb_state({name: not r.get("ok", True) for name, r in checks.items()})
  164  
  165      failed = {k: v for k, v in checks.items() if not v.get("ok")}
  166      ok     = len(failed) == 0
  167      if not ok:
  168          reasons = "; ".join(v.get("reason", k) for k, v in failed.items())
  169          log.warning("circuit breaker(s) active: %s", reasons)
  170  
  171      return {
  172          "ok":     ok,
  173          "checks": checks,
  174          "failed": list(failed.keys()),
  175          "reason": "; ".join(v.get("reason", "") for v in failed.values()) if not ok else "",
  176      }
```

### `scanner/broker/kill_switch.py`  (126 lines)
> Flatten-all on daily-loss breach. Which book does it read?
```python
    1  """Daily-loss kill-switch.
    2  
    3  Checks the session P&L (realised + unrealised) against SCALP_MAX_DAILY_LOSS.
    4  If the limit is breached, flattens all broker positions and cancels all orders,
    5  then fires an alert via alert_dispatch.
    6  
    7  Runs:
    8    • At the start of bybit_run / paper_run (pre-trade gate)
    9    • As a standalone hourly workflow to catch moves between scans
   10      (python -m scanner.broker.kill_switch)
   11  """
   12  
   13  import logging
   14  import os
   15  import pathlib
   16  import sys
   17  
   18  ROOT = pathlib.Path(__file__).resolve().parents[2]
   19  sys.path.insert(0, str(ROOT))
   20  
   21  log = logging.getLogger(__name__)
   22  
   23  
   24  def check_and_kill(j: dict, dry_run: bool = False) -> bool:
   25      """Return True if the kill switch fired (caller must abort new orders).
   26  
   27      j  — the scalp journal dict (open + closed lists)
   28      """
   29      from scanner.config import SCALP_MAX_DAILY_LOSS
   30      from scanner.scalp_journal import _session_day
   31  
   32      today        = _session_day()
   33      today_closed = [c for c in j.get("closed", []) if c.get("session_day") == today]
   34      today_pnl    = sum(c.get("pnl", 0) for c in today_closed)
   35      unrealised   = sum(p.get("unreal_pnl") or 0 for p in j.get("open", []))
   36      total_session = today_pnl + unrealised
   37  
   38      if total_session >= -SCALP_MAX_DAILY_LOSS:
   39          return False
   40  
   41      log.warning("KILL SWITCH TRIGGERED — session P&L = $%.2f (limit -$%.2f)",
   42                  total_session, SCALP_MAX_DAILY_LOSS)
   43  
   44      # Dispatch alert to all configured channels
   45      try:
   46          from .alert_dispatch import send as _alert
   47          _alert(
   48              "kill_switch",
   49              f"Kill switch triggered — session P&L ${total_session:.2f}",
   50              f"Daily loss limit: -${SCALP_MAX_DAILY_LOSS}. "
   51              f"{'DRY RUN — not flattening.' if dry_run else 'Flattening all positions now.'}",
   52          )
   53      except Exception as e:
   54          log.warning("could not send kill-switch alert: %s", e)
   55  
   56      if dry_run:
   57          log.info("kill-switch: dry_run=True — not flattening")
   58          return True
   59  
   60      if os.environ.get("BYBIT_API_KEY"):
   61          from scanner.broker import bybit_client as bc
   62          try:
   63              bc.cancel_all_orders()
   64              log.info("kill-switch: Bybit orders cancelled")
   65          except Exception as e:
   66              log.error("kill-switch: error cancelling Bybit orders: %s", e)
   67          try:
   68              bc.close_all_positions()
   69              log.info("kill-switch: Bybit positions closed")
   70          except Exception as e:
   71              log.error("kill-switch: error closing Bybit positions: %s", e)
   72  
   73      elif os.environ.get("ALPACA_API_KEY"):
   74          from scanner.broker import alpaca_client as ac
   75          try:
   76              resp = ac.close_all_positions()
   77              log.info("kill-switch: Alpaca positions closed: %s", resp)
   78          except Exception as e:
   79              log.error("kill-switch: error closing Alpaca positions: %s", e)
   80          try:
   81              resp = ac.cancel_all_orders()
   82              log.info("kill-switch: Alpaca orders cancelled: %s", resp)
   83          except Exception as e:
   84              log.error("kill-switch: error cancelling Alpaca orders: %s", e)
   85  
   86      else:
   87          log.warning("kill-switch: no broker API keys set — skipping flatten")
   88  
   89      return True
   90  
   91  
   92  def run_standalone(dry_run: bool = False) -> None:
   93      """Load the journal and run the kill-switch check (for the hourly workflow)."""
   94      import json
   95      from scanner.scalp_journal import SCALP_JOURNAL_FILE
   96  
   97      j = {"open": [], "closed": []}
   98      if SCALP_JOURNAL_FILE.exists():
   99          try:
  100              j = json.loads(SCALP_JOURNAL_FILE.read_text())
  101          except Exception as e:
  102              log.error("could not read journal: %s", e)
  103  
  104      triggered = check_and_kill(j, dry_run=dry_run)
  105      if not triggered:
  106          from scanner.config import SCALP_MAX_DAILY_LOSS
  107          from scanner.scalp_journal import _session_day
  108          today = _session_day()
  109          pnl   = sum(c.get("pnl", 0) for c in j.get("closed", [])
  110                      if c.get("session_day") == today)
  111          unreal = sum(p.get("unreal_pnl") or 0 for p in j.get("open", []))
  112          log.info("kill-switch OK — session P&L $%.2f / limit -$%.2f",
  113                   pnl + unreal, SCALP_MAX_DAILY_LOSS)
  114  
  115  
  116  if __name__ == "__main__":
  117      import argparse
  118      logging.basicConfig(
  119          level=logging.INFO,
  120          format="%(asctime)s  %(levelname)-7s  %(message)s",
  121          datefmt="%Y-%m-%d %H:%M:%S UTC",
  122      )
  123      p = argparse.ArgumentParser(description="Run the daily-loss kill-switch check")
  124      p.add_argument("--dry-run", action="store_true", help="Log only, don't flatten")
  125      args = p.parse_args()
  126      run_standalone(dry_run=args.dry_run)
```


## === C7. CLOUDFLARE FUNCTIONS (public API surface — Workers runtime) ===

### `functions/api/scan.js`  (132 lines)
> POST -> dispatch scan.yml. KV cooldown+cap (non-atomic). Echoes raw errors.
```javascript
    1  /* Cloudflare Pages Function — POST /api/scan
    2   *
    3   * Triggers a fresh cloud scan by dispatching the GitHub Actions "Scheduled scan"
    4   * workflow (which scans every market, commits the data, and redeploys the site).
    5   *
    6   * The GitHub token NEVER reaches the browser — it lives only here as a Pages
    7   * environment variable. One-time setup (see below) is required before the button
    8   * works; until then this returns a friendly "not configured" message and the UI
    9   * falls back to just reloading the latest data.
   10   *
   11   * One-time setup (guided):
   12   *   1. GitHub → Settings → Developer settings → Fine-grained personal access
   13   *      tokens → Generate new token. Scope it to the repo
   14   *      FakeCurrency/googy-boys-scanner with Repository permission
   15   *      "Actions: Read and write". Copy the token.
   16   *   2. Cloudflare Pages → your project → Settings → Environment variables → add
   17   *        GH_DISPATCH_TOKEN = <the token>
   18   *      (optionally GH_REPO and GH_WORKFLOW to override the defaults below).
   19   *   3. Redeploy. The SCAN button now kicks off a fresh scan.
   20   */
   21  export const onRequestPost = async ({ env, request }) => {
   22    const token = env.GH_DISPATCH_TOKEN;
   23    const repo = env.GH_REPO || "FakeCurrency/googy-boys-scanner";
   24    const workflow = env.GH_WORKFLOW || "scan.yml";
   25    const ref = env.GH_REF || "main";
   26  
   27    // Per-market scan: the dashboard sends the market it's currently showing so a
   28    // single tab (e.g. ASX) refreshes fast, without re-scanning everything.
   29    let market = "all";
   30    try {
   31      const body = await request.json();
   32      const m = String((body && body.market) || "").toLowerCase();
   33      if (["asx", "nasdaq", "crypto", "all"].includes(m)) market = m;
   34    } catch (_) { /* no/invalid body → full scan */ }
   35  
   36    const json = (status, body) =>
   37      new Response(JSON.stringify(body), {
   38        status,
   39        headers: { "Content-Type": "application/json" },
   40      });
   41  
   42    if (!token) {
   43      return json(503, {
   44        ok: false,
   45        configured: false,
   46        message:
   47          "Scan button not set up yet — add a GH_DISPATCH_TOKEN env var in Cloudflare (see functions/api/scan.js).",
   48      });
   49    }
   50  
   51    // Abuse guard (2026-07-09): the site is public and every call here burns a
   52    // GitHub Actions run. KV-backed cooldown — one dispatch per market per
   53    // 5 minutes, and a hard daily cap across all markets. Degrades to
   54    // no-limiting if the KV binding is absent, so a misconfig can't brick the
   55    // button. (Reuses the JOURNAL_KV namespace — see functions/api/journal.js.)
   56    if (env.JOURNAL_KV) {
   57      try {
   58        const cdKey = `ratelimit:scan:${market}`;
   59        if (await env.JOURNAL_KV.get(cdKey)) {
   60          return json(429, {
   61            ok: false, configured: true,
   62            message: "A scan for this market was requested in the last 5 minutes — it's still running. The data refreshes automatically when it lands.",
   63          });
   64        }
   65        const dayKey = `ratelimit:scan:day:${new Date().toISOString().slice(0, 10)}`;
   66        const used = parseInt((await env.JOURNAL_KV.get(dayKey)) || "0", 10);
   67        const DAILY_CAP = 40;
   68        if (used >= DAILY_CAP) {
   69          return json(429, {
   70            ok: false, configured: true,
   71            message: "Daily manual-scan limit reached — the scheduled scans keep running as normal.",
   72          });
   73        }
   74        await env.JOURNAL_KV.put(cdKey, "1", { expirationTtl: 300 });
   75        await env.JOURNAL_KV.put(dayKey, String(used + 1), { expirationTtl: 172800 });
   76      } catch (_) { /* KV hiccup → let the request through */ }
   77    }
   78  
   79    const url = `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`;
   80  
   81    // Abort if GitHub is slow so the browser never hangs on this request.
   82    const ctrl = new AbortController();
   83    const timer = setTimeout(() => ctrl.abort(), 10000);
   84    try {
   85      const res = await fetch(url, {
   86        method: "POST",
   87        headers: {
   88          Authorization: `Bearer ${token}`,
   89          Accept: "application/vnd.github+json",
   90          "X-GitHub-Api-Version": "2022-11-28",
   91          "User-Agent": "googy-boys-scanner",
   92          "Content-Type": "application/json",
   93        },
   94        body: JSON.stringify({ ref, inputs: { market } }),
   95        signal: ctrl.signal,
   96      });
   97  
   98      if (res.status === 204) {
   99        const scope = market === "all" ? "Full scan" : `${market.toUpperCase()} scan`;
  100        const eta = market === "all" ? "~6–10 minutes" : "~2–4 minutes";
  101        return json(202, {
  102          ok: true,
  103          configured: true,
  104          market,
  105          message: `${scope} started — fresh data in ${eta}.`,
  106        });
  107      }
  108  
  109      // Map the common GitHub failure modes to a clear, actionable message.
  110      const detail = (await res.text().catch(() => "")).slice(0, 200);
  111      const friendly = {
  112        401: "Scan token is invalid or expired — regenerate GH_DISPATCH_TOKEN in Cloudflare.",
  113        403: "Scan token lacks permission (needs Actions: Read and write) or GitHub is rate-limiting.",
  114        404: `Workflow "${workflow}" or repo not found — check GH_WORKFLOW / GH_REPO.`,
  115        422: `GitHub couldn't dispatch on ref "${ref}" — check the branch exists and the workflow has workflow_dispatch.`,
  116        429: "GitHub is rate-limiting scan requests — wait a minute and try again.",
  117      }[res.status] || `GitHub rejected the request (${res.status}). ${detail}`;
  118  
  119      return json(502, { ok: false, configured: true, status: res.status, message: friendly });
  120    } catch (err) {
  121      const aborted = err && err.name === "AbortError";
  122      return json(aborted ? 504 : 502, {
  123        ok: false,
  124        configured: true,
  125        message: aborted
  126          ? "GitHub took too long to respond — the scan may still start; check back shortly."
  127          : `Network error reaching GitHub: ${err}`,
  128      });
  129    } finally {
  130      clearTimeout(timer);
  131    }
  132  };
```

### `functions/api/close.js`  (105 lines)
> POST -> dispatch close_position.yml. INJECTION SINK (fields length-capped only).
```javascript
    1  /* Cloudflare Pages Function — POST /api/close
    2   *
    3   * Receives a manual position-close request from the journal UI and dispatches
    4   * the GitHub Actions "close_position" workflow to record it in the journal JSON,
    5   * commit, and let Cloudflare Pages redeploy.
    6   *
    7   * Requires the same GH_DISPATCH_TOKEN used by /api/scan (Actions: read+write).
    8   *
    9   * Request body (JSON):
   10   *   { symbol, direction, market, price, exit_date, journal_type }
   11   */
   12  export const onRequestPost = async ({ request, env }) => {
   13    const token = env.GH_DISPATCH_TOKEN;
   14    const repo  = env.GH_REPO     || "FakeCurrency/googy-boys-scanner";
   15    const ref   = env.GH_REF      || "main";
   16  
   17    const json = (status, body) =>
   18      new Response(JSON.stringify(body), {
   19        status,
   20        headers: { "Content-Type": "application/json" },
   21      });
   22  
   23    if (!token) {
   24      return json(503, {
   25        ok: false,
   26        message: "GH_DISPATCH_TOKEN not configured — add it to Cloudflare Pages env vars.",
   27      });
   28    }
   29  
   30    let body;
   31    try {
   32      body = await request.json();
   33    } catch {
   34      return json(400, { ok: false, message: "Invalid JSON body." });
   35    }
   36  
   37    const price = parseFloat(body?.price);
   38    if (!body?.symbol || !isFinite(price) || price <= 0) {
   39      return json(400, { ok: false, message: "symbol and a positive price are required." });
   40    }
   41  
   42    const inputs = {
   43      symbol:       String(body.symbol).slice(0, 20),
   44      direction:    body.direction === "short" ? "short" : "long",
   45      market:       String(body.market || "").slice(0, 20),
   46      price:        String(price),
   47      exit_date:    /^\d{4}-\d{2}-\d{2}$/.test(body.exit_date) ? body.exit_date : "",
   48      journal_type: body.journal_type === "scalp" ? "scalp" : "swing",
   49    };
   50  
   51    // Abuse guard (2026-07-09): public endpoint, each call burns an Actions run.
   52    // One close per symbol per minute + daily cap. No KV binding → no limiting.
   53    if (env.JOURNAL_KV) {
   54      try {
   55        const cdKey = `ratelimit:close:${inputs.symbol}`;
   56        if (await env.JOURNAL_KV.get(cdKey)) {
   57          return json(429, { ok: false, message: "A close for this symbol was just requested — give it a minute to process." });
   58        }
   59        const dayKey = `ratelimit:close:day:${new Date().toISOString().slice(0, 10)}`;
   60        const used = parseInt((await env.JOURNAL_KV.get(dayKey)) || "0", 10);
   61        if (used >= 60) {
   62          return json(429, { ok: false, message: "Daily close-request limit reached." });
   63        }
   64        await env.JOURNAL_KV.put(cdKey, "1", { expirationTtl: 60 });
   65        await env.JOURNAL_KV.put(dayKey, String(used + 1), { expirationTtl: 172800 });
   66      } catch (_) { /* KV hiccup → let it through */ }
   67    }
   68  
   69    const url  = `https://api.github.com/repos/${repo}/actions/workflows/close_position.yml/dispatches`;
   70    const ctrl = new AbortController();
   71    const timer = setTimeout(() => ctrl.abort(), 10_000);
   72  
   73    try {
   74      const res = await fetch(url, {
   75        method: "POST",
   76        headers: {
   77          Authorization:          `Bearer ${token}`,
   78          Accept:                 "application/vnd.github+json",
   79          "X-GitHub-Api-Version": "2022-11-28",
   80          "User-Agent":           "vivek-beta-scanner",
   81          "Content-Type":         "application/json",
   82        },
   83        body: JSON.stringify({ ref, inputs }),
   84        signal: ctrl.signal,
   85      });
   86  
   87      if (res.status === 204) {
   88        return json(202, {
   89          ok: true,
   90          message: `${inputs.symbol} ${inputs.direction} close queued — journal updates in ~1 minute.`,
   91        });
   92      }
   93  
   94      const detail = (await res.text().catch(() => "")).slice(0, 200);
   95      return json(502, { ok: false, message: `GitHub error ${res.status}: ${detail}` });
   96    } catch (err) {
   97      const aborted = err?.name === "AbortError";
   98      return json(aborted ? 504 : 502, {
   99        ok: false,
  100        message: aborted ? "GitHub took too long — try again." : `Network error: ${err}`,
  101      });
  102    } finally {
  103      clearTimeout(timer);
  104    }
  105  };
```

### `functions/api/journal.js`  (101 lines)
> KV journal GET/PUT. No rate limit; short codes; SHA-256 key.
```javascript
    1  /* Cloudflare Pages Function — GET/PUT /api/journal?code=<syncCode>
    2   *
    3   * Stores the user's "My Trades" journal JSON so it syncs across devices. The
    4   * data is keyed by a SHA-256 hash of the user's private sync code (the raw code
    5   * is never stored), so two devices using the same code share one journal.
    6   *
    7   * This is paper-trade bookkeeping only — no money, no secrets. Anyone who knows
    8   * the code can read/write that journal, so use a non-obvious code.
    9   *
   10   * One-time setup (so the sync code works):
   11   *   1. Cloudflare dashboard → Workers & Pages → KV → Create a namespace
   12   *        (e.g. name it "gbs-journal").
   13   *   2. Your Pages project → Settings → Functions → KV namespace bindings →
   14   *        Add binding:  Variable name = JOURNAL_KV  →  select the namespace.
   15   *   3. Redeploy. Until this binding exists, the app reports "sync not set up"
   16   *      and the Backup/Restore buttons still work as a manual fallback.
   17   */
   18  
   19  const json = (status, body) =>
   20    new Response(JSON.stringify(body), {
   21      status,
   22      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
   23    });
   24  
   25  async function keyFor(code) {
   26    const bytes = new TextEncoder().encode("gbs-journal:" + code);
   27    const digest = await crypto.subtle.digest("SHA-256", bytes);
   28    const hex = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
   29    return "journal:" + hex;
   30  }
   31  
   32  const cleanCode = (url) => (new URL(url).searchParams.get("code") || "").trim();
   33  
   34  // Brute-force guard: someone guessing sync codes produces GET *misses* — a
   35  // legit user misses at most once or twice at setup. Count only misses per IP
   36  // per day (so the counter costs a KV write only on misses, not on normal
   37  // traffic — the write quota stays protected) and lock the IP out past the cap.
   38  // Fail-open if KV hiccups: a limiter outage must never break sync.
   39  const MISS_DAY_LIMIT = 30;
   40  
   41  const missKey = (request) =>
   42    `ratelimit:journal-miss:${new Date().toISOString().slice(0, 10)}:` +
   43    (request.headers.get("CF-Connecting-IP") || "unknown");
   44  
   45  async function tooManyMisses(env, request) {
   46    try {
   47      return parseInt((await env.JOURNAL_KV.get(missKey(request))) || "0", 10) >= MISS_DAY_LIMIT;
   48    } catch (_) { return false; }
   49  }
   50  
   51  async function countMiss(env, request) {
   52    try {
   53      const key = missKey(request);
   54      const n = parseInt((await env.JOURNAL_KV.get(key)) || "0", 10) + 1;
   55      await env.JOURNAL_KV.put(key, String(n), { expirationTtl: 172800 });
   56    } catch (_) { /* fail-open */ }
   57  }
   58  
   59  export const onRequestGet = async ({ env, request }) => {
   60    if (!env.JOURNAL_KV) {
   61      return json(503, { ok: false, configured: false,
   62        message: "Cloud sync not set up — add a JOURNAL_KV namespace in Cloudflare (see functions/api/journal.js)." });
   63    }
   64    const code = cleanCode(request.url);
   65    if (code.length < 4) return json(400, { ok: false, configured: true, message: "Sync code must be at least 4 characters." });
   66    if (await tooManyMisses(env, request)) {
   67      return json(429, { ok: false, configured: true,
   68        message: "Too many unknown sync codes from this connection today — try again tomorrow." });
   69    }
   70  
   71    const raw = await env.JOURNAL_KV.get(await keyFor(code));
   72    let data = null;
   73    if (raw) { try { data = JSON.parse(raw); } catch (_) { data = null; } }
   74    else await countMiss(env, request);   // unknown code — brute-force signal
   75    return json(200, { ok: true, configured: true, data });
   76  };
   77  
   78  export const onRequestPut = async ({ env, request }) => {
   79    if (!env.JOURNAL_KV) {
   80      return json(503, { ok: false, configured: false,
   81        message: "Cloud sync not set up — add a JOURNAL_KV namespace in Cloudflare." });
   82    }
   83    const code = cleanCode(request.url);
   84    if (code.length < 4) return json(400, { ok: false, configured: true, message: "Sync code must be at least 4 characters." });
   85    if (await tooManyMisses(env, request)) {
   86      return json(429, { ok: false, configured: true,
   87        message: "Too many unknown sync codes from this connection today — try again tomorrow." });
   88    }
   89  
   90    let body;
   91    try { body = await request.json(); } catch (_) { return json(400, { ok: false, configured: true, message: "Invalid JSON body." }); }
   92    if (!body || typeof body !== "object" || !Array.isArray(body.trades)) {
   93      return json(400, { ok: false, configured: true, message: "Body must be a journal object with a trades array." });
   94    }
   95    // Guard against accidental giant payloads (KV value limit is 25 MB; journals are tiny).
   96    const serialized = JSON.stringify(body);
   97    if (serialized.length > 2_000_000) return json(413, { ok: false, configured: true, message: "Journal too large to sync." });
   98  
   99    await env.JOURNAL_KV.put(await keyFor(code), serialized);
  100    return json(200, { ok: true, configured: true });
  101  };
```

### `functions/api/tick.js`  (175 lines)
> Cloud stop watcher. Open-by-default auth; leaks cross-journal details; mutates KV.
```javascript
    1  /* Cloudflare Pages Function — cloud-side stop/target watcher.  GET|POST /api/tick
    2   *
    3   * Walks every synced journal in KV and auto-closes any OPEN paper position whose
    4   * live price has hit its stop or target — so stops fire 24/7 without keeping a
    5   * chart page open on any device. This is 100% paper bookkeeping: it never places
    6   * a real order. The matching client-side logic (chart.js maybeAutoClose) still
    7   * runs when a chart is open; both guard on status so a trade is closed once.
    8   *
    9   * Trigger it on a schedule with the GitHub Action .github/workflows/stop_watcher.yml
   10   * (every 5 min), an external uptime cron, or a Cloudflare cron Worker. Honest
   11   * fills: a stop that gaps through fills at the worse live price (never better
   12   * than the stop); a target never credits overshoot — identical to the chart.
   13   *
   14   * Setup: needs the same JOURNAL_KV binding as /api/journal. Optionally set a
   15   * TICK_SECRET env var (and the matching GitHub secret) to require a bearer token.
   16   */
   17  
   18  import { fetchBinancePrice, fetchYahooChart } from "./_prices.js";
   19  import { isVivek, manageVivek } from "./_vivek_manage.js";
   20  
   21  const json = (status, body) =>
   22    new Response(JSON.stringify(body), {
   23      status,
   24      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
   25    });
   26  
   27  function nowParts() {
   28    const d = new Date();
   29    const p = (n) => String(n).padStart(2, "0");
   30    return {
   31      date: `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}`,
   32      time: `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`,
   33    };
   34  }
   35  
   36  // Commodity/index symbols → their Yahoo tickers (mirrors journal.js YF_TICKER),
   37  // so a GOLD or NAS100 position resolves a real quote instead of a dead lookup.
   38  const YF_TICKER = {
   39    NAS100: "^NDX", US30: "^DJI", SPX500: "^GSPC", GER40: "^GDAXI", UK100: "^FTSE", JP225: "^N225",
   40    GOLD: "GC=F", SILVER: "SI=F", COPPER: "HG=F", PLATINUM: "PL=F", PALLADIUM: "PA=F",
   41    OIL: "CL=F", WTI: "CL=F", BRENT: "BZ=F", NATGAS: "NG=F", WHEAT: "ZW=F", COFFEE: "KC=F",
   42  };
   43  
   44  // Memoised live-price lookups (one cache per invocation dedups shared symbols).
   45  // Both paths fall back gracefully: crypto tries Binance then Yahoo; stocks try
   46  // both Yahoo hosts. A null result simply means "no fill this pass" — the trade
   47  // stays open and is re-checked next tick (never closed on a missing price).
   48  async function cryptoPrice(sym, cache) {
   49    const k = "C:" + sym;
   50    if (k in cache) return cache[k];
   51    let px = await fetchBinancePrice(sym);
   52    if (px == null) {
   53      try {
   54        const result = await fetchYahooChart(sym, { interval: "1m", range: "1d" });
   55        px = result?.meta?.regularMarketPrice ?? null;
   56      } catch (_) { px = null; }
   57    }
   58    return (cache[k] = px);
   59  }
   60  async function stockPrice(sym, aType, cache) {
   61    const up = String(sym || "").toUpperCase();
   62    const ticket = YF_TICKER[up]
   63      || (aType === "asx" && !String(sym).includes(".") ? sym + ".AX" : sym);
   64    const k = "S:" + ticket;
   65    if (k in cache) return cache[k];
   66    let px = null;
   67    try {
   68      const result = await fetchYahooChart(ticket, { interval: "1m", range: "1d" });
   69      px = result?.meta?.regularMarketPrice ?? result?.meta?.previousClose ?? null;
   70    } catch (_) { px = null; }
   71    return (cache[k] = px);
   72  }
   73  
   74  /* VIVEK scale-out management lives in _vivek_manage.js (shared so CI can
   75   * unit-test the exact code the watcher runs — drift vs the client = wrong P&L). */
   76  
   77  // Decide whether an open trade has hit its stop/target and, if so, the fill.
   78  function resolveClose(t, px) {
   79    if (px == null) return null;
   80    const long = t.direction !== "short";
   81    const stopped  = t.stop   != null && (long ? px <= t.stop   : px >= t.stop);
   82    const targeted = t.target != null && (long ? px >= t.target : px <= t.target);
   83    if (!stopped && !targeted) return null;
   84    // Stop takes precedence if somehow both are satisfied in one gap.
   85    if (stopped) {
   86      const fill = long ? Math.min(t.stop, px) : Math.max(t.stop, px);
   87      return { fill, kind: "stop" };
   88    }
   89    return { fill: t.target, kind: "target" };
   90  }
   91  
   92  async function runTick(env) {
   93    if (!env.JOURNAL_KV) {
   94      return json(503, { ok: false, configured: false, message: "JOURNAL_KV not bound." });
   95    }
   96    const cache = {};
   97    const np = nowParts();
   98    let journals = 0, closed = 0;
   99    const details = [];
  100  
  101    let cursor;
  102    do {
  103      const list = await env.JOURNAL_KV.list({ prefix: "journal:", cursor });
  104      cursor = list.list_complete ? null : list.cursor;
  105      for (const { name } of list.keys) {
  106        journals++;
  107        let data;
  108        try { data = JSON.parse((await env.JOURNAL_KV.get(name)) || "null"); } catch (_) { data = null; }
  109        if (!data || !Array.isArray(data.trades)) continue;
  110  
  111        let changed = false;
  112        for (const t of data.trades) {
  113          if (!t || t.status !== "open") continue;
  114          if (t.stop == null && t.target == null) continue;
  115          const aType = t.asset_type || "crypto";
  116          const isStock = aType === "asx" || aType === "nasdaq"
  117            || aType === "commodity" || aType === "index";
  118          const px = await (isStock ? stockPrice(t.symbol, aType, cache) : cryptoPrice(t.symbol, cache));
  119  
  120          // VIVEK trades (stop + tp1) get the full scale-out rules — TP partials,
  121          // SL trailing, stop closes the remainder — identical to the client.
  122          if (isVivek(t)) {
  123            const r = manageVivek(t, px, np);
  124            if (!r) continue;
  125            changed = true;
  126            if (r === "close") {
  127              closed++;
  128              details.push({ symbol: t.symbol, dir: t.direction, kind: t.exit_reason, fill: t.exit });
  129            } else {
  130              details.push({ symbol: t.symbol, dir: t.direction, kind: "scale-out", fill: px });
  131            }
  132            continue;
  133          }
  134  
  135          // Legacy (non-VIVEK) trades: simple full close on stop or target.
  136          const hit = resolveClose(t, px);
  137          if (!hit) continue;
  138          t.status = "closed";
  139          t.exit = hit.fill;
  140          t.exit_date = np.date;
  141          t.exit_time = np.time;
  142          t.auto_closed = hit.kind;
  143          t.closed_by = "cloud-watcher";
  144          t.mtime = Date.now();
  145          changed = true;
  146          closed++;
  147          details.push({ symbol: t.symbol, dir: t.direction, kind: hit.kind, fill: hit.fill });
  148        }
  149  
  150        if (changed) {
  151          data.updated_at = Date.now();
  152          await env.JOURNAL_KV.put(name, JSON.stringify(data));
  153        }
  154      }
  155    } while (cursor);
  156  
  157    return json(200, { ok: true, journals, closed, details, at: new Date().toISOString() });
  158  }
  159  
  160  function authorised(request, env) {
  161    if (!env.TICK_SECRET) return true;          // open unless a secret is configured
  162    const url = new URL(request.url);
  163    const fromQuery = url.searchParams.get("key");
  164    const header = request.headers.get("Authorization") || "";
  165    const fromHeader = header.startsWith("Bearer ") ? header.slice(7) : "";
  166    return fromQuery === env.TICK_SECRET || fromHeader === env.TICK_SECRET;
  167  }
  168  
  169  export const onRequest = async ({ request, env }) => {
  170    if (request.method !== "GET" && request.method !== "POST") {
  171      return json(405, { ok: false, message: "Use GET or POST." });
  172    }
  173    if (!authorised(request, env)) return json(401, { ok: false, message: "Unauthorized." });
  174    return runTick(env);
  175  };
```

### `functions/api/_vivek_manage.js`  (107 lines)
> VIVEK cloud-management logic used by tick.js — check parity with the Python.
```javascript
    1  /* Shared VIVEK scale-out management — used by the cloud watcher (tick.js)
    2   * and unit-tested in CI (test/vivek_manage.test.js). Underscore files are
    3   * not routed by Cloudflare Pages, same as _prices.js. */
    4  
    5  /* ── VIVEK scale-out management (parity with public/js/journal.js manage()) ───
    6   * A VIVEK trade (has stop + tp1) must NOT be full-closed at a single "target":
    7   * the rules book partials at TP1/TP2/TP3, trail the SL (break-even at TP1, TP1
    8   * at TP2) and close the remainder on the stop. Before this, a trade whose page
    9   * was closed got legacy handling — full exit at tp2, untrailed stop — so the
   10   * journal diverged from the rules whenever nobody had a chart open. The
   11   * constants mirror the client exactly; drift between the two = wrong P&L.   */
   12  export const VK = {
   13    EQUITY: 10000, RISK_PCT: 0.35, RISK_MIN: 0.25, RISK_MAX: 0.5,
   14    LEVERAGE: { asx: 5, nasdaq: 5, crypto: 3 },
   15    SCALE: { long: [0.25, 0.50, 0.15], short: [0.50, 0.25, 0.15] },
   16    COMMISSION_BPS: { asx: 2, nasdaq: 1, crypto: 6, default: 2 },
   17    SLIPPAGE_BPS: { asx: 5, nasdaq: 4, crypto: 8, default: 5 },
   18  };
   19  export const isVivek = (t) => t && t.stop != null && t.tp1 != null;
   20  export const vkMarket = (t) => {
   21    const a = t.market || t.asset_type;
   22    if (a === "crypto") return "crypto";
   23    if (a === "asx") return "asx";
   24    return "nasdaq";               // nasdaq + commodity/index use nasdaq-tier costs
   25  };
   26  export function vkSizeRiskUsd(market, entry, stop) {
   27    const riskPct = Math.min(Math.max(VK.RISK_PCT, VK.RISK_MIN), VK.RISK_MAX) / 100;
   28    const dist = Math.abs(entry - stop);
   29    if (!(dist > 0) || !(entry > 0)) return 0;
   30    let riskUsd = VK.EQUITY * riskPct;
   31    const maxN = VK.EQUITY * (VK.LEVERAGE[market] || VK.LEVERAGE.asx);
   32    if ((riskUsd / dist) * entry > maxN) riskUsd = (maxN / entry) * dist;
   33    return riskUsd;
   34  }
   35  export function vkInit(t) {
   36    const isLong = t.direction !== "short";
   37    if (!(t.risk > 0)) t.risk = Math.abs(t.entry - t.stop);
   38    if (t.risk_usd == null) t.risk_usd = vkSizeRiskUsd(vkMarket(t), t.entry, t.stop);
   39    if (!Array.isArray(t.scale)) t.scale = VK.SCALE[isLong ? "long" : "short"];
   40    if (!Array.isArray(t.exits)) t.exits = [];
   41    if (t.gross_r == null) t.gross_r = 0;
   42    if (t.booked_pct == null) t.booked_pct = 0;
   43    if (t.tp1_hit == null) { t.tp1_hit = false; t.tp2_hit = false; t.tp3_hit = false; }
   44  }
   45  export const vkR = (price, entry, risk, isLong) => (isLong ? price - entry : entry - price) / risk;
   46  export function vkFinalize(t) {
   47    const m = vkMarket(t);
   48    const slip = (VK.SLIPPAGE_BPS[m] ?? VK.SLIPPAGE_BPS.default) / 1e4;
   49    const comm = (VK.COMMISSION_BPS[m] ?? VK.COMMISSION_BPS.default) / 1e4;
   50    let cp = t.entry * (slip + comm);
   51    for (const ex of t.exits) {
   52      const market = /^(stop|manual)/.test(ex.reason || "");
   53      cp += (ex.pct || 0) * (ex.price || t.entry) * (comm + (market ? slip : 0));
   54    }
   55    t.cost_r = +(cp / t.risk).toFixed(4);
   56    t.realized_r = +((t.gross_r || 0) - t.cost_r).toFixed(4);
   57  }
   58  // Returns "close" | "book" | false. np = {date, time} for close stamps.
   59  export function manageVivek(t, px, np) {
   60    if (t.status !== "open" || px == null) return false;
   61    vkInit(t);
   62    const isLong = t.direction !== "short", risk = t.risk;
   63    if (!(risk > 0)) return false;
   64    let booked = false;
   65  
   66    const stopHit = isLong ? px <= t.stop : px >= t.stop;
   67    if (stopHit) {
   68      // Honest gap fill: never better than the stop.
   69      const fill = isLong ? Math.min(t.stop, px) : Math.max(t.stop, px);
   70      const remaining = +(1 - (t.booked_pct || 0)).toFixed(6);
   71      if (remaining > 1e-9) {
   72        t.exits.push({ reason: "stop", price: +fill.toFixed(8), pct: remaining, date: np.date });
   73        t.gross_r = +((t.gross_r || 0) + remaining * vkR(fill, t.entry, risk, isLong)).toFixed(4);
   74        t.booked_pct = 1;
   75      }
   76      t.status = "closed"; t.exit = +fill.toFixed(8);
   77      t.exit_date = np.date; t.exit_time = np.time;
   78      t.exit_reason = t.tp3_hit ? "target" : (t.tp1_hit ? "trail" : "stop");
   79      t.auto_closed = "stop"; t.closed_by = "cloud-watcher"; t.mtime = Date.now();
   80      vkFinalize(t);
   81      return "close";
   82    }
   83  
   84    const scale = t.scale;
   85    const reached = (lvl) => (isLong ? px >= lvl : px <= lvl);
   86    const valid = (lvl) => (isLong ? lvl > t.entry : lvl < t.entry);   // chased-entry guard
   87    const fav = (nsl, csl) => (isLong ? nsl > csl : nsl < csl);        // SL only in our favour
   88    const book = (name, lvl, pct) => {
   89      t.exits.push({ reason: name, price: +lvl.toFixed(8), pct, date: np.date });
   90      t.gross_r = +((t.gross_r || 0) + pct * vkR(lvl, t.entry, risk, isLong)).toFixed(4);
   91      t.booked_pct = +((t.booked_pct || 0) + pct).toFixed(6);
   92      booked = true;
   93    };
   94    if (!t.tp1_hit && t.tp1 != null && valid(t.tp1) && reached(t.tp1)) {
   95      t.tp1_hit = true; book("tp1", t.tp1, scale[0]);
   96      if (fav(t.entry, t.stop)) t.stop = t.entry;                      // SL → break-even
   97    }
   98    if (!t.tp2_hit && t.tp2 != null && valid(t.tp2) && reached(t.tp2)) {
   99      t.tp2_hit = true; book("tp2", t.tp2, scale[1]);
  100      if (t.tp1 != null && fav(t.tp1, t.stop)) t.stop = t.tp1;         // SL → locked structure
  101    }
  102    if (!t.tp3_hit && t.tp3 != null && valid(t.tp3) && reached(t.tp3)) {
  103      t.tp3_hit = true; book("tp3", t.tp3, scale[2]);
  104    }
  105    if (booked) { t.mtime = Date.now(); vkFinalize(t); return "book"; }
  106    return false;
  107  }
```

### `functions/api/_prices.js`  (201 lines)
> Shared price fetch helper.
```javascript
    1  /* Shared price/candle helpers for the API Functions (Cloudflare Workers runtime).
    2   *
    3   * This file exports helpers only — it has no request handler, so it is bundled
    4   * into the Functions that import it and is never itself a routable endpoint.
    5   *
    6   * Design goals (resilience + consistency):
    7   *   • Live prices never depend on a single upstream. Crypto prefers Binance
    8   *     (real-time, keyless, 24/7) and falls back to Yahoo; everything else uses
    9   *     Yahoo across BOTH hosts (query1 → query2) before giving up.
   10   *   • Historical candles are trimmed to a target bar-count per range so every
   11   *     asset type returns a consistent-length series for the chart.
   12   *   • Every fetch has a timeout and is wrapped so one dead source can't hang or
   13   *     crash the caller — failures degrade to the next source, then to null.
   14   */
   15  
   16  const UA = "Mozilla/5.0 (compatible; VivekBetaScanner/1.0)";
   17  const YH_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"];
   18  const BINANCE_PRICE = "https://api.binance.com/api/v3/ticker/price?symbol=";
   19  const BINANCE_KLINES = "https://api.binance.com/api/v3/klines";
   20  
   21  // Common base tickers that are crypto even without a -USD/USDT suffix.
   22  const KNOWN_CRYPTO = new Set([
   23    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT",
   24    "MATIC", "LTC", "TRX", "ATOM", "UNI", "ARB", "OP", "SUI", "APT", "NEAR",
   25    "INJ", "TIA", "SEI", "RNDR", "FIL", "AAVE", "MKR", "PEPE", "WIF", "BONK",
   26  ]);
   27  
   28  /** True if the symbol looks like a crypto pair (suffix or known base). */
   29  export function isCryptoSymbol(sym) {
   30    const s = String(sym || "").toUpperCase();
   31    if (/-USD$/.test(s) || /USDT$/.test(s) || /-USDT$/.test(s)) return true;
   32    const base = s.replace(/-USD$/, "").replace(/-USDT$/, "").replace(/USDT$/, "");
   33    return KNOWN_CRYPTO.has(base);
   34  }
   35  
   36  /** Normalise any crypto symbol to its Binance USDT pair (BTC-USD → BTCUSDT). */
   37  export function binanceSymbol(sym) {
   38    const base = String(sym || "").toUpperCase()
   39      .replace(/-USD$/, "").replace(/-USDT$/, "").replace(/USDT$/, "");
   40    return base + "USDT";
   41  }
   42  
   43  /** Normalise any crypto symbol to its Yahoo pair (BDX → BDX-USD, BDXUSDT → BDX-USD).
   44   * Crypto MUST be queried on Yahoo as "<base>-USD"; a bare base like "BDX" resolves
   45   * to a same-named EQUITY (BDX = Becton Dickinson), which is the wrong instrument. */
   46  export function yahooCryptoSymbol(sym) {
   47    const base = String(sym || "").toUpperCase()
   48      .replace(/-USD$/, "").replace(/-USDT$/, "").replace(/USDT$/, "");
   49    return base + "-USD";
   50  }
   51  
   52  /** Map our chart intervals to Binance kline intervals. */
   53  function binanceInterval(interval) {
   54    return ({
   55      "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
   56      "60m": "1h", "1h": "1h", "1d": "1d", "1wk": "1w", "1mo": "1M",
   57    })[interval] || "1d";
   58  }
   59  
   60  /** Target bar-count per range so all asset types return a consistent-length series. */
   61  export function targetBars(range, interval) {
   62    if (["1m", "5m", "15m", "30m", "60m", "1h"].includes(interval)) return 500;
   63    return ({
   64      "1d": 2, "5d": 5, "1mo": 22, "3mo": 66, "6mo": 130,
   65      "1y": 260, "2y": 520, "5y": 1000, "10y": 1000, "max": 1000,
   66    })[range] || 260;
   67  }
   68  
   69  async function timedFetch(url, opts = {}, timeout = 9000) {
   70    return fetch(url, { ...opts, signal: AbortSignal.timeout(timeout), cf: { cacheTtl: 0 } });
   71  }
   72  
   73  /** Fetch a Yahoo v8 chart result, trying both hosts before failing. */
   74  export async function fetchYahooChart(sym, { interval = "1d", range = "1d", timeout = 9000 } = {}) {
   75    let lastErr;
   76    for (const host of YH_HOSTS) {
   77      try {
   78        const url = `https://${host}/v8/finance/chart/${encodeURIComponent(sym)}` +
   79          `?interval=${interval}&range=${range}&events=div`;
   80        const res = await timedFetch(url, { headers: { "User-Agent": UA, "Accept": "application/json" } }, timeout);
   81        if (!res.ok) { lastErr = new Error(`yahoo ${res.status}`); continue; }
   82        const data = await res.json();
   83        const result = data?.chart?.result?.[0];
   84        if (!result) { lastErr = new Error("yahoo: empty result"); continue; }
   85        return result;
   86      } catch (e) { lastErr = e; }
   87    }
   88    throw lastErr || new Error("yahoo: all hosts failed");
   89  }
   90  
   91  /** Live Binance spot price (or null on any failure). */
   92  export async function fetchBinancePrice(sym, timeout = 6000) {
   93    try {
   94      const r = await timedFetch(BINANCE_PRICE + encodeURIComponent(binanceSymbol(sym)), {}, timeout);
   95      if (!r.ok) return null;
   96      const j = await r.json();
   97      return j && j.price != null ? +j.price : null;
   98    } catch (_) { return null; }
   99  }
  100  
  101  /** Binance klines → candle objects ({time:sec, o,h,l,c,volume}); [] on failure. */
  102  export async function fetchBinanceCandles(sym, { interval = "1d", limit = 260, timeout = 9000 } = {}) {
  103    try {
  104      const url = `${BINANCE_KLINES}?symbol=${encodeURIComponent(binanceSymbol(sym))}` +
  105        `&interval=${binanceInterval(interval)}&limit=${Math.min(limit, 1000)}`;
  106      const r = await timedFetch(url, {}, timeout);
  107      if (!r.ok) return [];
  108      const rows = await r.json();
  109      if (!Array.isArray(rows)) return [];
  110      return rows.map((k) => ({
  111        time: Math.floor(k[0] / 1000),
  112        open: +k[1], high: +k[2], low: +k[3], close: +k[4],
  113        volume: k[5] == null ? 0 : Math.round(+k[5]),
  114      }));
  115    } catch (_) { return []; }
  116  }
  117  
  118  /** Yahoo chart result → clean candle objects (nulls dropped). */
  119  export function yahooCandles(result) {
  120    const ts = result?.timestamp || [];
  121    const q = result?.indicators?.quote?.[0] || {};
  122    const { open = [], high = [], low = [], close = [], volume = [] } = q;
  123    const out = [];
  124    for (let i = 0; i < ts.length; i++) {
  125      const o = open[i], h = high[i], l = low[i], c = close[i];
  126      if (o == null || h == null || l == null || c == null) continue;  // skip padded gaps
  127      out.push({ time: ts[i], open: +o, high: +h, low: +l, close: +c, volume: volume[i] == null ? 0 : Math.round(volume[i]) });
  128    }
  129    return out;
  130  }
  131  
  132  /** Trim a candle series to the last `n` bars (keeps lengths consistent). */
  133  export function trimCandles(candles, n) {
  134    return n > 0 && candles.length > n ? candles.slice(candles.length - n) : candles;
  135  }
  136  
  137  /**
  138   * Resilient live price with a source-aware fallback chain.
  139   * @returns {{price:number|null, source:string|null, delayed:boolean}}
  140   */
  141  export async function livePrice(sym, assetType, prefer = null) {
  142    const crypto = assetType ? assetType === "crypto" : isCryptoSymbol(sym);
  143    if (crypto && prefer !== "yahoo") {
  144      const b = await fetchBinancePrice(sym);
  145      if (b != null) return { price: +b, source: "binance", delayed: false };
  146    }
  147    // Crypto must be queried on Yahoo as "<base>-USD" (a bare base resolves to a
  148    // same-named equity); stocks/commodities use the symbol as-is.
  149    const ySym = crypto ? yahooCryptoSymbol(sym) : sym;
  150    try {
  151      const result = await fetchYahooChart(ySym, { interval: "1d", range: "1d" });
  152      const m = result?.meta;
  153      const px = m?.regularMarketPrice ?? m?.previousClose ?? null;
  154      if (px != null) return { price: +px, source: "yahoo", delayed: !crypto };
  155    } catch (_) { /* give up */ }
  156    return { price: null, source: null, delayed: false };
  157  }
  158  
  159  /**
  160   * Resilient candle history, consistent-length across asset types.
  161   * Crypto → Binance klines (fallback Yahoo); others → Yahoo (dual host).
  162   * @returns {{candles:Array, source:string|null, delayed:boolean}}
  163   */
  164  export async function history(sym, assetType, { range = "1y", interval = "1d", prefer = null } = {}) {
  165    const crypto = assetType ? assetType === "crypto" : isCryptoSymbol(sym);
  166    const want = targetBars(range, interval);
  167  
  168    // `prefer:"yahoo"` skips the Binance pair guess — used by the VIVEK daily chart
  169    // so a thin coin (no/!=Binance pair) matches the scan's Yahoo <base>-USD series
  170    // exactly, instead of a wrong pair that throws the price scale off.
  171    if (crypto && prefer !== "yahoo") {
  172      const c = await fetchBinanceCandles(sym, { interval, limit: want });
  173      if (c.length) return { candles: trimCandles(c, want), source: "binance", delayed: false };
  174    }
  175    // Crypto on Yahoo MUST be "<base>-USD" (a bare base = a same-named equity).
  176    const ySym = crypto ? yahooCryptoSymbol(sym) : sym;
  177    try {
  178      const result = await fetchYahooChart(ySym, { interval, range });
  179      const c = yahooCandles(result);
  180      if (c.length) {
  181        return { candles: trimCandles(c, want), source: "yahoo", delayed: !crypto,
  182                 recent_div: recentDividend(result) };
  183      }
  184    } catch (_) { /* fall through */ }
  185    return { candles: [], source: null, delayed: false };
  186  }
  187  
  188  /** Most recent dividend within ~45 days from a Yahoo chart result (events=div),
  189   *  or null. Recent dividends mean the ADJUSTED series (and every level derived
  190   *  from it) differs from the raw prices a broker shows. */
  191  export function recentDividend(result, windowDays = 45) {
  192    const divs = result?.events?.dividends;
  193    if (!divs) return null;
  194    const cutoff = Date.now() / 1000 - windowDays * 86400;
  195    let latest = null;
  196    for (const k of Object.keys(divs)) {
  197      const d = divs[k];
  198      if (d && d.date >= cutoff && (!latest || d.date > latest.date)) latest = d;
  199    }
  200    return latest ? { date: latest.date, amount: +latest.amount || 0 } : null;
  201  }
```

### `functions/api/price.js`  (80 lines)
> Yahoo price proxy — unthrottled.
```javascript
    1  /* Cloudflare Pages Function — GET /api/price?symbol=BTC-USD
    2   *
    3   * Resilient price + history proxy. Crypto prefers Binance (real-time, 24/7) and
    4   * falls back to Yahoo; stocks/commodities use Yahoo across both hosts. History
    5   * is trimmed to a consistent bar-count per range so every asset type returns a
    6   * comparable-length series for the chart.
    7   *
    8   *   GET /api/price?symbol=AAPL
    9   *     → { ok, price, symbol, source }
   10   *   GET /api/price?symbol=BTC-USD&range=1y&interval=1d&type=crypto
   11   *     → { ok, price, symbol, source, delayed, bars, candles:[{time,open,high,low,close,volume}] }
   12   */
   13  import { livePrice, history } from "./_prices.js";
   14  
   15  // Successful responses edge-cache for ~20s — chart opens and journal refreshes
   16  // re-request the same symbols in bursts; a short shared cache absorbs those
   17  // instead of hammering Yahoo into throttling. Errors are never cached.
   18  const json = (status, body) =>
   19    new Response(JSON.stringify(body), {
   20      status,
   21      headers: {
   22        "Content-Type": "application/json",
   23        "Cache-Control": status === 200 ? "public, max-age=15, s-maxage=20" : "no-store",
   24      },
   25    });
   26  
   27  export const onRequestGet = async ({ request }) => {
   28    const url = new URL(request.url);
   29    const symbol = url.searchParams.get("symbol") || "";
   30  
   31    // Whitelist the ranges / intervals we actually use so the param can't craft
   32    // arbitrary upstream requests.
   33    const RANGES = new Set(["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "max"]);
   34    const INTERVALS = new Set(["1m", "5m", "15m", "30m", "60m", "1h", "1d", "1wk", "1mo"]);
   35    const range = RANGES.has(url.searchParams.get("range")) ? url.searchParams.get("range") : null;
   36    const interval = INTERVALS.has(url.searchParams.get("interval")) ? url.searchParams.get("interval") : null;
   37    const assetType = (url.searchParams.get("type") || "").toLowerCase() || null;  // optional hint
   38    // Optional source override: "yahoo" forces the Yahoo path (skips the Binance
   39    // pair guess) so VIVEK crypto charts match the scan's <base>-USD series.
   40    const prefer = ["yahoo", "binance"].includes((url.searchParams.get("src") || "").toLowerCase())
   41      ? url.searchParams.get("src").toLowerCase() : null;
   42    const wantCandles = Boolean(range && interval);
   43  
   44    if (!symbol || symbol.length > 30 || !/^[\w.\-^=]+$/i.test(symbol)) {
   45      return json(400, { ok: false, error: "Invalid symbol" });
   46    }
   47  
   48    try {
   49      const live = await livePrice(symbol, assetType, prefer);
   50  
   51      if (!wantCandles) {
   52        if (live.price == null) return json(502, { ok: false, error: "no price from any source", symbol });
   53        return json(200, { ok: true, price: +live.price.toFixed(8), symbol, source: live.source });
   54      }
   55  
   56      const hist = await history(symbol, assetType, { range, interval, prefer });
   57      // Prefer the live tick for `price`; fall back to the last candle close.
   58      const lastClose = hist.candles.length ? hist.candles[hist.candles.length - 1].close : null;
   59      const price = live.price != null ? +live.price : lastClose;
   60  
   61      if (price == null && !hist.candles.length) {
   62        return json(502, { ok: false, error: "no price or history from any source", symbol });
   63      }
   64  
   65      return json(200, {
   66        ok: true,
   67        symbol,
   68        price: price == null ? null : +price.toFixed(8),
   69        source: hist.source || live.source,
   70        delayed: hist.delayed,
   71        bars: hist.candles.length,
   72        candles: hist.candles,
   73        // dividend within ~45d → the adjusted series (and levels) differs from
   74        // the raw prices a broker shows; the chart surfaces this as a chip
   75        recent_div: hist.recent_div || null,
   76      });
   77    } catch (err) {
   78      return json(502, { ok: false, error: String(err && err.message ? err.message : err), symbol });
   79    }
   80  };
```

### `functions/api/quote.js`  (59 lines)
> Quote proxy — unthrottled.
```javascript
    1  // Cloudflare Pages Function — resilient single-quote proxy.
    2  // GET /api/quote?sym=BHP.AX  → { price, currency, time, source }
    3  // GET /api/quote?sym=BTC-USD → { price, currency, time, source }
    4  //
    5  // Crypto prefers Binance (real-time, 24/7); stocks/commodities use Yahoo across
    6  // both hosts. Currency is preserved from Yahoo meta (so ASX returns AUD).
    7  import { isCryptoSymbol, fetchBinancePrice, fetchYahooChart, yahooCryptoSymbol } from "./_prices.js";
    8  
    9  // Successful quotes are edge-cached for ~20s: the journal opens with a batch
   10  // of per-symbol fetches, so a short shared cache absorbs repeat opens (and
   11  // multiple devices) instead of hammering Yahoo into throttling us. Errors are
   12  // never cached.
   13  const json = (status, body) =>
   14    new Response(JSON.stringify(body), {
   15      status,
   16      headers: {
   17        "Content-Type": "application/json",
   18        "Cache-Control": status === 200 ? "public, max-age=15, s-maxage=20" : "no-store",
   19      },
   20    });
   21  
   22  export async function onRequestGet(ctx) {
   23    const url = new URL(ctx.request.url);
   24    const sym = url.searchParams.get("sym") || "";
   25    // src=yahoo forces the Yahoo path (skips the Binance pair guess) so a VIVEK
   26    // crypto header price matches its chart's scan-consistent <base>-USD series.
   27    const prefer = url.searchParams.get("src") === "yahoo" ? "yahoo" : null;
   28  
   29    if (!/^[A-Za-z0-9.\^=\-_]{1,20}$/.test(sym)) {
   30      return json(400, { error: "Invalid symbol" });
   31    }
   32  
   33    const now = Math.floor(Date.now() / 1000);
   34  
   35    // Crypto: Binance first (keyless, real-time), Yahoo as a backstop.
   36    const crypto = isCryptoSymbol(sym);
   37    if (crypto && prefer !== "yahoo") {
   38      const px = await fetchBinancePrice(sym);
   39      if (px != null) return json(200, { price: px, currency: "USD", time: now, source: "binance" });
   40    }
   41  
   42    // Stocks / commodities (and crypto fallback): Yahoo across both hosts. Crypto
   43    // must use "<base>-USD" so a bare base can't resolve to a same-named equity.
   44    try {
   45      const result = await fetchYahooChart(crypto ? yahooCryptoSymbol(sym) : sym, { interval: "1m", range: "1d" });
   46      const meta = result?.meta;
   47      if (!meta) return json(502, { error: "No data returned for " + sym });
   48      const price = meta.regularMarketPrice ?? meta.previousClose ?? null;
   49      if (price == null) return json(502, { error: "No price for " + sym });
   50      return json(200, {
   51        price,
   52        currency: meta.currency ?? "USD",
   53        time: meta.regularMarketTime ?? now,
   54        source: "yahoo",
   55      });
   56    } catch (err) {
   57      return json(502, { error: "Upstream failed: " + String(err && err.message ? err.message : err) });
   58    }
   59  }
```


## === C8. FRONTEND P&L (journal page) ===

### `public/js/journal.js`  (1103 lines)
> Journal page P&L: bot vs manual, comparison, edge/lens trackers, close modal, live refresh. Manual-close-after-TP1 math; sizing-constant mirror.
```javascript
    1  /* Paper-trade journal — Claude (bot) vs Me (manual), head to head.
    2   *
    3   *  • Claude  = the autonomous bot's paper book  (data/vivek_bot_book.json),
    4   *              written server-side every scan. Read-only here.
    5   *  • Me      = the trades you take from the charts (the shared manual store,
    6   *              localStorage + optional cross-device sync). Sized + managed by
    7   *              the SAME VIVEK rules as the bot: risk 0.35% of a $10k book,
    8   *              5× stocks / 3× crypto leverage cap, scale at TP1/2/3, SL → BE at
    9   *              TP1 → locked structure at TP2, close on the stop. You pick the
   10   *              setup; the rules run the trade. $ P&L uses 1R = the $ risked.
   11   *
   12   *  All R/$ and equity curves are computed at render time and refreshed against
   13   *  live prices, so both sides update as trades open and close.
   14   */
   15  (() => {
   16    "use strict";
   17    const $  = (s) => document.querySelector(s);
   18    const $$ = (s) => Array.from(document.querySelectorAll(s));
   19  
   20    const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
   21      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
   22    const up  = (s) => esc(String(s == null ? "" : s).toUpperCase());
   23  
   24    const GRADE_CLS = { "A+": "g-aplus", "A": "g-a", "B+": "g-b", "B": "g-b", "WATCH": "g-c", "C": "g-c" };
   25    const rcls = (r) => (r >= 0 ? "r-pos" : "r-neg");
   26    const rfmt = (r) => (r == null || isNaN(r) ? "—" : (r >= 0 ? "+" : "") + (+r).toFixed(2) + "R");
   27    const pcls = (v) => (v >= 0 ? "r-pos" : "r-neg");
   28    const dfmt = (v) => (v == null || isNaN(v) ? "—" : (v >= 0 ? "+" : "-") + "$" + Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0, minimumFractionDigits: 0 }));
   29    const d2   = (v) => (v == null || isNaN(v) ? "—" : (v >= 0 ? "+" : "-") + "$" + Math.abs(v).toFixed(2));
   30    const px   = (v) => (v == null || isNaN(v) ? "—" : (+v).toLocaleString(undefined, { maximumFractionDigits: 6 }));
   31    const round = (v, n) => +(+v).toFixed(n);
   32  
   33    // SYMBOL → { grade, entry_type } from the live scans, used only as a fallback
   34    // for older manual trades that were logged before grade/setup were captured.
   35    const scanMeta = new Map();
   36    // "market:SYMBOL" → last scan price. The scan refreshes this every run, so it's
   37    // the reliable "Now" source for manual trades (no flaky live-quote fetch).
   38    const scanPrice = new Map();
   39  
   40    // ── VIVEK sizing + cost model (mirrors scanner/broker/vivek_bot.py + config) ──
   41    // Each market is sized off its own $10k book; the account spans all three, so
   42    // the starting capital shown to the user is 3 × $10k = $30k.
   43    const EQUITY = 10000, RISK_PCT = 0.35, RISK_MIN = 0.25, RISK_MAX = 0.5;
   44    const START_CAPITAL = EQUITY * 3;        // $30k — ASX + NASDAQ + Crypto books
   45    const money0 = (v) => "$" + Math.round(v).toLocaleString();
   46    const LEVERAGE = { asx: 5, nasdaq: 5, crypto: 3 };
   47    const SCALE = { long: [0.25, 0.50, 0.15], short: [0.50, 0.25, 0.15] };
   48    const COMMISSION_BPS = { asx: 2, nasdaq: 1, crypto: 6, default: 2 };
   49    const SLIPPAGE_BPS   = { asx: 5, nasdaq: 4, crypto: 8, default: 5 };
   50  
   51    const STOCK_TYPES = new Set(["asx", "nasdaq", "commodity", "index"]);
   52    const NONCRYPTO = new Set(["NAS100","US30","SPX500","GER40","UK100","JP225",
   53      "GOLD","SILVER","OIL","WTI","BRENT","NATGAS","COPPER","PLATINUM","PALLADIUM","WHEAT","COFFEE"]);
   54    const YF_TICKER = {
   55      NAS100:"^NDX",US30:"^DJI",SPX500:"^GSPC",GER40:"^GDAXI",UK100:"^FTSE",JP225:"^N225",
   56      GOLD:"GC=F",SILVER:"SI=F",COPPER:"HG=F",PLATINUM:"PL=F",PALLADIUM:"PA=F",
   57      OIL:"CL=F",WTI:"CL=F",BRENT:"BZ=F",NATGAS:"NG=F",WHEAT:"ZW=F",COFFEE:"KC=F",
   58    };
   59  
   60    function isCryptoTrade(t) {
   61      // Bot trades carry `market` ("asx"/"nasdaq"/"crypto"); manual trades from the
   62      // chart carry `asset_type`. Prefer whichever is set so a bot ASX position is
   63      // never mistaken for crypto (which would misprice + misclassify it).
   64      const a = (t && (t.market || t.asset_type)) || null;
   65      if (a === "crypto") return true;
   66      if (STOCK_TYPES.has(a)) return false;
   67      if (a == null || a === "") return !NONCRYPTO.has(String((t && t.symbol) || "").toUpperCase());
   68      return false;
   69    }
   70    // Market key for sizing/costs: crypto / asx / nasdaq (stocks default to nasdaq fees).
   71    function marketOf(t) {
   72      if (isCryptoTrade(t)) return "crypto";
   73      if (t.market === "asx" || t.asset_type === "asx") return "asx";
   74      return "nasdaq";
   75    }
   76  
   77    // Risk-based size: risk a slice of equity, cap notional at the market leverage.
   78    // 1R in dollars === risk_usd, so $ P&L for any VIVEK trade = R × risk_usd.
   79    function sizeOf(market, entry, stop) {
   80      const riskPct = Math.min(Math.max(RISK_PCT, RISK_MIN), RISK_MAX) / 100;
   81      const dist = Math.abs(entry - stop);
   82      if (!(dist > 0) || !(entry > 0)) return { units: 0, risk_usd: 0, notional: 0, leverage: 0 };
   83      let risk_usd = EQUITY * riskPct, units = risk_usd / dist, notional = units * entry;
   84      const maxN = EQUITY * (LEVERAGE[market] || LEVERAGE.asx);
   85      if (notional > maxN) { units = maxN / entry; notional = units * entry; risk_usd = units * dist; }
   86      return { units, risk_usd, notional, leverage: notional / EQUITY };
   87    }
   88  
   89    const costsFor = (market) => [
   90      (SLIPPAGE_BPS[market]   ?? SLIPPAGE_BPS.default)   / 1e4,
   91      (COMMISSION_BPS[market] ?? COMMISSION_BPS.default) / 1e4,
   92    ];
   93    // Round-trip cost in R: entry is a market fill; a stop/manual close pays
   94    // slippage, a resting TP limit does not. Mirrors vivek_journal._cost_r.
   95    function costR(t, slip, comm) {
   96      const entry = t.entry, risk = t.risk;
   97      if (!(risk > 0) || !entry) return 0;
   98      let cp = entry * (slip + comm);
   99      for (const ex of t.exits || []) {
  100        const market = /^(stop|manual)/.test(ex.reason || "");
  101        cp += (ex.pct || 0) * (ex.price || entry) * (comm + (market ? slip : 0));
  102      }
  103      return cp / risk;
  104    }
  105  
  106    const rOf = (price, entry, risk, isLong) => (isLong ? (price - entry) : (entry - price)) / risk;
  107    const fav = (nsl, csl, isLong) => (isLong ? nsl > csl : nsl < csl);
  108    const isVivek = (t) => t && t.stop != null && t.tp1 != null;
  109  
  110    // ── auto-management of a manual position (mirror of vivek_journal._mark) ──────
  111    function ensureInit(t) {
  112      if (t._init) return;
  113      t.market = marketOf(t);
  114      const isLong = t.direction !== "short";
  115      if (isVivek(t)) {
  116        t.risk = Math.abs(t.entry - t.stop);
  117        t.risk_usd = sizeOf(t.market, t.entry, t.stop).risk_usd;
  118        if (!Array.isArray(t.scale)) t.scale = SCALE[isLong ? "long" : "short"];
  119      }
  120      if (t.gross_r == null) t.gross_r = 0;
  121      if (t.booked_pct == null) t.booked_pct = 0;
  122      if (!Array.isArray(t.exits)) t.exits = [];
  123      if (t.tp1_hit == null) { t.tp1_hit = false; t.tp2_hit = false; t.tp3_hit = false; }
  124      if (t.mae == null) t.mae = t.entry;
  125      if (t.mfe == null) t.mfe = t.entry;
  126      t._init = true;
  127    }
  128    function finalizeR(t) {
  129      const [slip, comm] = costsFor(t.market);
  130      t.cost_r = round(costR(t, slip, comm), 4);
  131      t.realized_r = round((t.gross_r || 0) - t.cost_r, 4);
  132    }
  133    function book(t, name, price, pct, isLong) {
  134      t.exits.push({ reason: name, price: round(price, 8), pct, date: today() });
  135      t.gross_r = round((t.gross_r || 0) + pct * rOf(price, t.entry, t.risk, isLong), 4);
  136      t.booked_pct = round((t.booked_pct || 0) + pct, 6);
  137    }
  138    // Returns the kind of change so the caller can decide whether to PERSIST:
  139    //   false   — nothing material (or only MAE/MFE drift)
  140    //   "book"  — a TP scaled out / stop trailed (still open)
  141    //   "close" — the position closed
  142    // MAE/MFE high-water marks are tracked in memory only — they moved on almost
  143    // every tick and were burning the KV write quota; they ride along on the next
  144    // material save.
  145    function manage(t, price) {
  146      if (t.status !== "open" || !isVivek(t) || price == null) return false;
  147      ensureInit(t);
  148      const isLong = t.direction !== "short", risk = t.risk;
  149      if (!(risk > 0)) return false;
  150      t.mfe = isLong ? Math.max(t.mfe, price) : Math.min(t.mfe, price);
  151      t.mae = isLong ? Math.min(t.mae, price) : Math.max(t.mae, price);
  152  
  153      let material = false;
  154      const stopHit = isLong ? price <= t.stop : price >= t.stop;
  155      if (stopHit) {
  156        const remaining = round(1 - (t.booked_pct || 0), 6);
  157        if (remaining > 1e-9) {
  158          t.exits.push({ reason: "stop", price: round(price, 8), pct: remaining, date: today() });
  159          t.gross_r = round((t.gross_r || 0) + remaining * rOf(price, t.entry, risk, isLong), 4);
  160          t.booked_pct = 1;
  161        }
  162        t.status = "closed"; t.exit = round(price, 8);
  163        t.exit_date = today(); t.exit_time = nowTime();
  164        t.exit_reason = t.tp3_hit ? "target" : (t.tp1_hit ? "trail" : "stop");
  165        material = true;
  166      } else {
  167        const scale = t.scale, reached = (lvl) => (isLong ? price >= lvl : price <= lvl);
  168        // A TP only counts if it's a genuine profit target BEYOND the entry. This
  169        // stops a chased entry (taken above the plan's TP1) from instantly booking
  170        // "TP1" and trailing the stop to break-even on the entry bar.
  171        const valid = (lvl) => (isLong ? lvl > t.entry : lvl < t.entry);
  172        if (!t.tp1_hit && t.tp1 != null && valid(t.tp1) && reached(t.tp1)) {
  173          t.tp1_hit = true; book(t, "tp1", t.tp1, scale[0], isLong);
  174          if (fav(t.entry, t.stop, isLong)) t.stop = t.entry;        // SL → break-even
  175          material = true;
  176        }
  177        if (!t.tp2_hit && t.tp2 != null && valid(t.tp2) && reached(t.tp2)) {
  178          t.tp2_hit = true; book(t, "tp2", t.tp2, scale[1], isLong);
  179          if (fav(t.tp1, t.stop, isLong)) t.stop = t.tp1;            // SL → locked structure
  180          material = true;
  181        }
  182        if (!t.tp3_hit && t.tp3 != null && valid(t.tp3) && reached(t.tp3)) {
  183          t.tp3_hit = true; book(t, "tp3", t.tp3, scale[2], isLong); material = true;
  184        }
  185      }
  186      if (material) finalizeR(t);
  187      return material ? (t.status === "closed" ? "close" : "book") : false;
  188    }
  189    // Make sure a CLOSED manual trade has its realized R/$ resolved once.
  190    function ensureClosedR(t) {
  191      if (t.status !== "closed") return;
  192      ensureInit(t);
  193      if (!isVivek(t)) { t.realized_r = null; return; }
  194      if (!t.exits.length && t.exit != null) {       // a manual full close from the chart
  195        const isLong = t.direction !== "short";
  196        t.gross_r = round(rOf(t.exit, t.entry, t.risk, isLong), 4);
  197        t.exits = [{ reason: "manual", price: t.exit, pct: 1, date: t.exit_date || today() }];
  198        t.booked_pct = 1;
  199      }
  200      finalizeR(t);
  201    }
  202  
  203    // FX honesty: ASX positions are priced in A$ while NASDAQ/crypto are US$.
  204    // Every $ AGGREGATE on this page converts ASX P&L to US$ at the scan's
  205    // published AUD/USD rate (data/fx.json) so the head-to-head totals stop
  206    // mixing currencies at face value (~50% overstatement of ASX P&L).
  207    let FX_AUDUSD = 0.66;                       // fallback until fx.json loads
  208    const fxOf = (t) => ((t.market || t.asset_type) === "asx" ? FX_AUDUSD : 1);
  209    const dollarsOf = (t) => (t.realized_r != null && t.risk_usd != null
  210      ? t.realized_r * t.risk_usd * fxOf(t) : null);
  211    async function loadFx() {
  212      try {
  213        const r = await fetch("data/fx.json", { cache: "no-cache" });
  214        if (r.ok) { const j = await r.json(); if (j && j.audusd > 0) FX_AUDUSD = +j.audusd; }
  215      } catch (_) { /* keep fallback */ }
  216    }
  217  
  218    // ── time helpers ──────────────────────────────────────────────────────────
  219    const pad = (n) => String(n).padStart(2, "0");
  220    const today = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
  221    const nowTime = () => { const d = new Date(); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
  222    function openedMs(t) {
  223      const ms = Date.parse(t.opened_at || `${t.entry_date || ""}T${t.entry_time || "10:00"}`);
  224      return isNaN(ms) ? null : ms;
  225    }
  226    function exitMs(t) {
  227      const ms = Date.parse(t.closed_at || `${t.exit_date || ""}T${t.exit_time || "16:00"}`);
  228      return isNaN(ms) ? null : ms;
  229    }
  230    function durText(fromMs, toMs) {
  231      if (fromMs == null || toMs == null || toMs < fromMs) return "—";
  232      const h = (toMs - fromMs) / 3.6e6;
  233      if (h < 24) return `${Math.max(0, Math.round(h))}h`;
  234      const d = h / 24;
  235      return d < 10 ? `${d.toFixed(1)}d` : `${Math.round(d)}d`;
  236    }
  237  
  238    // ── stats + equity ────────────────────────────────────────────────────────
  239    function stats(closed, openN) {
  240      const rs = closed.map((t) => t.realized_r).filter((r) => r != null);
  241      const ds = closed.map((t) => dollarsOf(t)).filter((v) => v != null);
  242      const wins = rs.filter((r) => r > 0).length;
  243      // max drawdown on the cumulative $ curve
  244      let cum = 0, peak = 0, dd = 0;
  245      for (const v of ds) { cum += v; peak = Math.max(peak, cum); dd = Math.min(dd, cum - peak); }
  246      return {
  247        n: closed.length, open: openN,
  248        totalR: rs.reduce((a, b) => a + b, 0),
  249        totalD: ds.reduce((a, b) => a + b, 0),
  250        win: rs.length ? (100 * wins / rs.length) : null,
  251        maxDD: dd,
  252      };
  253    }
  254    // Equity series ordered by exit time: cumulative R and cumulative $.
  255    function series(closed) {
  256      const sorted = closed.slice().filter((t) => t.realized_r != null)
  257        .sort((a, b) => (exitMs(a) || 0) - (exitMs(b) || 0));
  258      let r = 0, d = 0;
  259      const pts = [{ r: 0, d: 0, date: sorted.length ? sorted[0].entry_date || null : null }];
  260      for (const t of sorted) { r += t.realized_r; d += (dollarsOf(t) || 0); pts.push({ r: round(r, 3), d: round(d, 2), date: t.exit_date || null }); }
  261      return pts;
  262    }
  263  
  264    function statCards(host, s, accent) {
  265      const cell = (label, val, cls) =>
  266        `<div class="stat-card"><div class="stat-label">${label}</div><div class="stat-value ${cls || ""}">${val}</div></div>`;
  267      const equity = START_CAPITAL + s.totalD;          // realised account value
  268      host.innerHTML =
  269        cell("Account value", `${money0(equity)}<span class="stat-sub"> from ${money0(START_CAPITAL)}</span>`, pcls(s.totalD)) +
  270        cell("Total $", dfmt(s.totalD), pcls(s.totalD)) +
  271        cell("Total R", rfmt(s.totalR), rcls(s.totalR)) +
  272        cell("Win rate", s.win == null ? "—" : s.win.toFixed(0) + "%", "") +
  273        cell("Trades", `${s.n}<span class="stat-sub"> closed · ${s.open} open</span>`, "") +
  274        cell("Max drawdown", dfmt(s.maxDD), s.maxDD < 0 ? "r-neg" : "");
  275    }
  276  
  277    // Dual-line equity chart: cumulative $ (filled) + cumulative R (line), each
  278    // normalised to its own range inside the same box, with end-value labels.
  279    function drawEquity(elId, pts, label) {
  280      const el = $("#" + elId);
  281      if (!el) return;
  282      if (!pts || pts.length < 2) {
  283        el.innerHTML = `<div class="jr-empty">No closed trades yet${label ? ` for ${label}` : ""} — the curve appears here.</div>`;
  284        return;
  285      }
  286      const w = 1000, h = 120, pad = 8;
  287      const norm = (vals) => {
  288        const mn = Math.min(0, ...vals), mx = Math.max(0, ...vals), rng = (mx - mn) || 1;
  289        return (v) => h - pad - ((v - mn) / rng) * (h - 2 * pad);
  290      };
  291      const xs = (i) => pad + (i / (pts.length - 1)) * (w - 2 * pad);
  292      const ds = pts.map((p) => p.d), rs = pts.map((p) => p.r);
  293      const yD = norm(ds), yR = norm(rs);
  294      const lineD = pts.map((p, i) => `${xs(i).toFixed(1)},${yD(p.d).toFixed(1)}`).join(" ");
  295      const lineR = pts.map((p, i) => `${xs(i).toFixed(1)},${yR(p.r).toFixed(1)}`).join(" ");
  296      const area = `${pad},${yD(0).toFixed(1)} ${lineD} ${xs(pts.length - 1).toFixed(1)},${yD(0).toFixed(1)}`;
  297      const endD = ds[ds.length - 1], endR = rs[rs.length - 1];
  298      // Softer, muted up/down colours + a fade-to-transparent gradient fill.
  299      const col = endD >= 0 ? "#3fb784" : "#d07070";
  300      const gid = elId + "-g";
  301      const dated = pts.filter((p) => p.date);
  302      const dlabel = (s) => s ? new Date(s + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "";
  303      const first = dated.length ? dlabel(dated[0].date) : "";
  304      const last = dated.length ? dlabel(dated[dated.length - 1].date) : "";
  305      el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" class="jr-eqsvg">
  306        <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
  307          <stop offset="0" stop-color="${col}" stop-opacity="0.16"/><stop offset="1" stop-color="${col}" stop-opacity="0"/>
  308        </linearGradient></defs>
  309        <line x1="0" y1="${yD(0).toFixed(1)}" x2="${w}" y2="${yD(0).toFixed(1)}" stroke="#222a38" stroke-width="1" stroke-dasharray="2 4"/>
  310        <polygon points="${area}" fill="url(#${gid})"/>
  311        <polyline points="${lineD}" fill="none" stroke="${col}" stroke-width="1.6" stroke-linejoin="round"/>
  312        <polyline points="${lineR}" fill="none" stroke="#7aa7e6" stroke-width="1.1" stroke-dasharray="4 5" opacity="0.5"/>
  313      </svg>
  314      <div class="jr-eqaxis"><span>${first}</span><span>${last}</span></div>
  315      <div class="jr-eqtags"><span class="${pcls(endD)}">${dfmt(endD)}</span><span class="lg-r">${rfmt(endR)}</span></div>`;
  316    }
  317  
  318    // ── tables ────────────────────────────────────────────────────────────────
  319    const gradeChip = (g) => g ? `<span class="g ${GRADE_CLS[g] || "g-c"}">${esc(g)}</span>` : "—";
  320    // Full-word, dog-balls direction pill (owner 2026-07-10): a trade's
  321    // AT-ENTRY direction must be unmissable, because the scan's read can flip
  322    // after entry and the chart may show the opposite setup today.
  323    const dirChip = (d) => `<span class="dir ${d === "short" ? "dir-s" : "dir-l"}">${d === "short" ? "▼ SHORT" : "▲ LONG"}</span>`;
  324    // Warn chip when the CURRENT scan reads the opposite way to an open trade.
  325    const flipChip = (t) => {
  326      if (t.status === "closed") return "";
  327      const now = (scanMeta.get(symKey(t)) || {}).dir;
  328      if (!now) return "";
  329      const trade = String(t.direction || "long").toUpperCase() === "SHORT" ? "SHORT" : "LONG";
  330      if (String(now).toUpperCase() === trade) return "";
  331      return `<span class="jr-flip" title="The scanner's read on this chart flipped AFTER entry — the position was taken as ${trade}">⚠ CHART NOW READS ${esc(String(now).toUpperCase())}</span>`;
  332    };
  333    // Grade + setup type: the bot logs these; manual trades now do too. For trades
  334    // taken before that, fall back to the live scan's grade/trigger for the symbol
  335    // so older rows aren't blank (scanMeta is filled from *_vivek.json at load).
  336    const symKey = (t) => String((t && t.symbol) || "").toUpperCase();
  337    const gradeOf = (t) => t.grade || (scanMeta.get(symKey(t)) || {}).grade || null;
  338    const entryTypeOf = (t) => t.entry_type || (scanMeta.get(symKey(t)) || {}).entry_type || null;
  339  
  340    // Setup chip: the timeframe + entry trigger of the trade — e.g. "Weekly
  341    // reclaim" — coloured by trigger (reclaim green / retest red / break amber).
  342    const SETUP_CLS = { reclaim: "su-reclaim", retest: "su-retest", break: "su-break" };
  343    const TF_NAME = { "1W": "Weekly", "1D": "Daily", "3D": "3-Day", "4H": "4-Hour" };
  344    function setupChip(t) {
  345      const et = String(entryTypeOf(t) || "").toLowerCase();
  346      const tf = t.timeframe || "";
  347      if (!et && !tf) return "";
  348      const tfn = TF_NAME[tf] || tf;
  349      const label = et ? `${tfn} ${et}` : tfn;
  350      return `<span class="jr-setup ${SETUP_CLS[et] || ""}" title="Setup">${esc(label)}</span>`;
  351    }
  352    // Market chip: which book the ticker belongs to — ASX / NASDAQ / Crypto —
  353    // colour-coded to match the dashboard's market accents.
  354    const MKT_LABEL = { asx: "ASX", nasdaq: "NASDAQ", crypto: "CRYPTO" };
  355    function marketChip(t) {
  356      const m = marketOf(t);
  357      return `<span class="jr-mkt jr-mkt-${m}" title="Market">${MKT_LABEL[m] || up(m)}</span>`;
  358    }
  359    // Symbol cell links to the chart for that ticker, with market + setup chips after it.
  360    const symCell = (t) =>
  361      `<td class="jr-sym"><a class="jr-symlink" href="chart.html?s=${esc(t.symbol)}&m=${marketOf(t)}&src=journal" title="Open ${up(t.symbol)} chart">` +
  362      `${dirChip(t.direction)} ${up(t.symbol)}</a>${marketChip(t)}${setupChip(t)}${flipChip(t)}</td>`;
  363    // Date + time stamp from a parsed epoch (opened / closed).
  364    function stamp(ms) {
  365      if (ms == null) return "—";
  366      const d = new Date(ms); if (isNaN(d)) return "—";
  367      return `${d.toLocaleDateString(undefined, { day: "numeric", month: "short" })} ${d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
  368    }
  369  
  370    // Now / Unreal-R / Unreal-$ cells (returned separately — some tables put other
  371    // columns between Now and the R/$ pair).
  372    //  • Bot positions are marked to market by the scan SERVER-SIDE every run
  373    //    (unreal_r / unreal_usd live in the book JSON), so render those straight
  374    //    away — reliable, refreshed each scan, no client fetch.
  375    //  • Manual positions are filled by refreshLive (scan-price snapshot first,
  376    //    then a live quote) — these carry the data-* hooks it reads.
  377    function liveCellParts(t, side) {
  378      const isLong = t.direction !== "short";
  379      if (side === "bot") {
  380        const risk = t.risk != null ? t.risk : Math.abs(t.entry - (t.stop ?? t.entry));
  381        const now = (t.unreal_r != null && risk > 0)
  382          ? (isLong ? t.entry + t.unreal_r * risk : t.entry - t.unreal_r * risk) : null;
  383        const ur = t.unreal_r, ud = t.unreal_usd != null ? t.unreal_usd * fxOf(t) : null;
  384        return {
  385          now: `<td class="num jr-now">${now != null ? px(now) : "—"}</td>`,
  386          ur: `<td class="num jr-ur ${ur != null ? rcls(ur) : ""}">${ur != null ? rfmt(ur) : "—"}</td>`,
  387          ud: `<td class="num jr-ud ${ud != null ? pcls(ud) : ""}">${ud != null ? d2(ud) : "—"}</td>`,
  388        };
  389      }
  390      return {
  391        now: `<td class="num jr-now" data-entry="${t.entry}" data-stop="${t.stop ?? ""}" data-long="${isLong}" data-ru="${t.risk_usd ?? ""}">…</td>`,
  392        ur: `<td class="num jr-ur">—</td>`,
  393        ud: `<td class="num jr-ud">—</td>`,
  394      };
  395    }
  396    // Now+R+$ as three adjacent cells (for the per-section tables).
  397    function liveCells(t, side) {
  398      const p = liveCellParts(t, side);
  399      return p.now + p.ur + p.ud;
  400    }
  401  
  402    // Per-section (Claude / Me) tables sit in half-width side-by-side columns, so
  403    // they carry only the per-side essentials — the full-width combined tables in
  404    // the comparison overview above show entry/stop/targets/timestamps in full.
  405    function openRows(list, side, nowMs) {
  406      if (!list.length) return `<div class="jr-empty">No open positions.</div>`;
  407      const head = `<tr><th>Symbol</th><th>Gr</th><th class="num">Entry</th><th class="num">Stop</th><th class="num">Now</th>
  408        <th class="num">R</th><th class="num">$</th><th class="num">Opened</th>${side === "me" ? "<th></th>" : ""}</tr>`;
  409      // Newest position at the top.
  410      const rows = list.slice().sort((a, b) => (openedMs(b) || 0) - (openedMs(a) || 0)).map((t) => {
  411        const isLong = t.direction !== "short";
  412        const actions = side === "me"
  413          ? `<td class="num jr-actions"><button class="jr-close-btn" data-close="${esc(t.id)}">Close</button>` +
  414            `<button class="jr-note-btn${t.note ? " has-note" : ""}" data-note="${esc(t.id)}" ` +
  415            `title="${t.note ? esc(t.note) : "Add a note — why did you take this trade?"}">📝</button>` +
  416            `<button class="jr-del-btn" data-del="${esc(t.id)}" title="Remove from journal (no P&L logged)">✕</button></td>` : "";
  417        return `<tr data-tid="${esc(t.id)}" data-side="${side}">
  418          ${symCell(t)}
  419          <td>${gradeChip(gradeOf(t))}</td>
  420          <td class="num">${px(t.entry)}</td>
  421          <td class="num">${px(t.stop)}</td>
  422          ${liveCells(t, side)}
  423          <td class="num jr-stamp">${stamp(openedMs(t))}<span class="num-sub"> · ${durText(openedMs(t), nowMs)}</span></td>${actions}</tr>`;
  424      }).join("");
  425      return `<table class="jr-table"><thead>${head}</thead><tbody>${rows}</tbody></table>`;
  426    }
  427  
  428    function closedRows(list) {
  429      if (!list.length) return `<div class="jr-empty">No closed trades yet.</div>`;
  430      const head = `<tr><th>Symbol</th><th>Gr</th><th class="num">R</th><th class="num">$</th>
  431        <th class="num">Opened</th><th class="num">Closed</th><th>Reason</th></tr>`;
  432      const rows = list.slice().sort((a, b) => (exitMs(b) || 0) - (exitMs(a) || 0)).map((t) => {
  433        const d = dollarsOf(t);
  434        return `<tr>
  435          ${symCell(t)}
  436          <td>${gradeChip(gradeOf(t))}</td>
  437          <td class="num ${t.realized_r == null ? "" : rcls(t.realized_r)}">${rfmt(t.realized_r)}</td>
  438          <td class="num ${d == null ? "" : pcls(d)}">${d == null ? "—" : d2(d)}</td>
  439          <td class="num jr-stamp">${stamp(openedMs(t))}</td>
  440          <td class="num jr-stamp">${stamp(exitMs(t))}<span class="num-sub"> · ${durText(openedMs(t), exitMs(t))}</span></td>
  441          <td><span class="jr-reason jr-reason-${esc(t.exit_reason || "manual")}">${esc(t.exit_reason || "manual")}</span>${t.note ? ` <span class="jr-note-tag" title="${esc(t.note)}">📝</span>` : ""}</td></tr>`;
  442      }).join("");
  443      return `<table class="jr-table"><thead>${head}</thead><tbody>${rows}</tbody></table>`;
  444    }
  445  
  446    // ── Same positions: you and Claude in the same trade, head to head ─────────
  447    // A trade "matches" when both sides hold the same symbol, in the same market,
  448    // the same way (long/short). One shared Now column (same live price for both);
  449    // Claude's R/$ are marked server-side each scan, yours update live.
  450    const tradeKey = (t) => `${marketOf(t)}:${symKey(t)}:${t.direction === "short" ? "S" : "L"}`;
  451  
  452    function renderBoth() {
  453      const openHost = $("#both-open");
  454      if (!openHost) return;
  455  
  456      // open overlaps — every (Claude, me) pair currently open on the same key
  457      const meByKey = new Map();
  458      for (const t of state.me.open) {
  459        const k = tradeKey(t);
  460        if (!meByKey.has(k)) meByKey.set(k, []);
  461        meByKey.get(k).push(t);
  462      }
  463      const pairs = [];
  464      for (const b of state.bot.open) {
  465        for (const m of meByKey.get(tradeKey(b)) || []) pairs.push([b, m]);
  466      }
  467      pairs.sort((a, b) => (openedMs(b[1]) || 0) - (openedMs(a[1]) || 0));
  468      const nEl = $("#both-open-n");
  469      if (nEl) nEl.textContent = pairs.length ? `(${pairs.length})` : "";
  470  
  471      if (!pairs.length) {
  472        openHost.innerHTML = `<div class="jr-empty">No overlap right now — when you and Claude hold the
  473          same position, it lines up here head to head.</div>`;
  474      } else {
  475        const head = `<tr><th>Symbol</th><th class="num">Now</th>
  476          <th class="num h-bot bsep">🤖 Entry</th><th class="num h-bot">🤖 Opened</th><th class="num h-bot">🤖 R</th><th class="num h-bot">🤖 $</th>
  477          <th class="num h-me bsep">✏️ Entry</th><th class="num h-me">✏️ Opened</th><th class="num h-me">✏️ R</th><th class="num h-me">✏️ $</th></tr>`;
  478        const body = pairs.map(([b, m]) => {
  479          // Claude's cells are static (marked by the scan) — plain classes so
  480          // refreshLive only drives the Me cells (.jr-ur/.jr-ud) + shared Now.
  481          const ur = b.unreal_r, ud = b.unreal_usd != null ? b.unreal_usd * fxOf(b) : null;
  482          const me = liveCellParts(m, "me");
  483          return `<tr data-tid="${esc(m.id)}" data-side="me">
  484            ${symCell(b)}
  485            ${me.now}
  486            <td class="num bsep">${px(b.entry)}</td>
  487            <td class="num jr-stamp">${stamp(openedMs(b))}</td>
  488            <td class="num ${ur != null ? rcls(ur) : ""}">${ur != null ? rfmt(ur) : "—"}</td>
  489            <td class="num ${ud != null ? pcls(ud) : ""}">${ud != null ? d2(ud) : "—"}</td>
  490            <td class="num bsep">${px(m.entry)}</td>
  491            <td class="num jr-stamp">${stamp(openedMs(m))}</td>
  492            ${me.ur}${me.ud}</tr>`;
  493        }).join("");
  494        openHost.innerHTML = `<table class="jr-table"><thead>${head}</thead><tbody>${body}</tbody></table>`;
  495      }
  496  
  497      // settled head-to-heads — same symbol+direction, both sides fully closed.
  498      // Totals per symbol (either side may have traded it more than once).
  499      const agg = (list) => {
  500        const out = new Map();
  501        for (const t of list) {
  502          if (t.realized_r == null) continue;
  503          const k = tradeKey(t);
  504          const a = out.get(k) || { n: 0, r: 0, d: 0, t };
  505          a.n += 1; a.r += t.realized_r; a.d += (dollarsOf(t) || 0);
  506          out.set(k, a);
  507        }
  508        return out;
  509      };
  510      const bAgg = agg(state.bot.closed), mAgg = agg(state.me.closed);
  511      const settled = [];
  512      for (const [k, b] of bAgg) { const m = mAgg.get(k); if (m) settled.push([b, m]); }
  513      settled.sort((x, y) => Math.abs(y[0].r + y[1].r) - Math.abs(x[0].r + x[1].r));
  514  
  515      const wrap = $("#both-closed-wrap");
  516      if (wrap) wrap.hidden = !settled.length;
  517      if (settled.length) {
  518        const win = (b, m) => b.r > m.r + 1e-9
  519          ? `<span class="both-win w-bot">🤖 Claude</span>`
  520          : m.r > b.r + 1e-9 ? `<span class="both-win w-me">✏️ Me</span>`
  521          : `<span class="both-win">Tie</span>`;
  522        const head = `<tr><th>Symbol</th>
  523          <th class="num h-bot bsep">🤖 R</th><th class="num h-bot">🤖 $</th>
  524          <th class="num h-me bsep">✏️ R</th><th class="num h-me">✏️ $</th>
  525          <th class="num">Trades</th><th class="num">Winner</th></tr>`;
  526        const body = settled.map(([b, m]) => `<tr>
  527          ${symCell(b.t)}
  528          <td class="num bsep ${rcls(b.r)}">${rfmt(b.r)}</td>
  529          <td class="num ${pcls(b.d)}">${d2(b.d)}</td>
  530          <td class="num bsep ${rcls(m.r)}">${rfmt(m.r)}</td>
  531          <td class="num ${pcls(m.d)}">${d2(m.d)}</td>
  532          <td class="num"><span class="num-sub">${b.n} vs ${m.n}</span></td>
  533          <td class="num">${win(b, m)}</td></tr>`).join("");
  534        $("#both-closed").innerHTML = `<table class="jr-table"><thead>${head}</thead><tbody>${body}</tbody></table>`;
  535      }
  536    }
  537  
  538    // ── live prices (reused from the manual-journal helpers) ──────────────────
  539    // Hard client-side timeout so a slow/hanging upstream can never leave the
  540    // "Now" cell stuck on the "…" placeholder — it aborts and we fall back to "—".
  541    async function fetchJSON(url, ms = 6000) {
  542      const ctrl = new AbortController();
  543      const t = setTimeout(() => ctrl.abort(), ms);
  544      try {
  545        const r = await fetch(url, { cache: "no-store", signal: ctrl.signal });
  546        return r.ok ? await r.json() : null;
  547      } catch (_) { return null; }
  548      finally { clearTimeout(t); }
  549    }
  550    async function cryptoPrice(sym) {
  551      const pair = encodeURIComponent(String(sym || "").toUpperCase() + "USDT");
  552      let j = await fetchJSON(`https://api.binance.com/api/v3/ticker/price?symbol=${pair}`);
  553      if (j && j.price != null) return +j.price;
  554      // Binance doesn't list every coin (e.g. BDX/Beldex) — fall back to Yahoo's
  555      // <base>-USD via our quote proxy so those still get a live price.
  556      j = await fetchJSON(`/api/quote?sym=${encodeURIComponent(String(sym || "").toUpperCase() + "-USD")}`);
  557      return j && j.price != null ? +j.price : null;
  558    }
  559    async function stockPrice(sym, market) {
  560      const up_ = String(sym || "").toUpperCase();
  561      const ticket = YF_TICKER[up_] || (market === "asx" && !String(sym).includes(".") ? sym + ".AX" : sym);
  562      const j = await fetchJSON(`/api/quote?sym=${encodeURIComponent(ticket)}`);
  563      return j && j.price != null ? +j.price : null;
  564    }
  565    const priceFor = (t) => (marketOf(t) === "crypto" ? cryptoPrice(t.symbol) : stockPrice(t.symbol, marketOf(t)));
  566  
  567    // ── store (manual side) ───────────────────────────────────────────────────
  568    const MJ_KEY = "gbs:manual_journal";
  569    function mjLoad() {
  570      if (window.GBSSync) return window.GBSSync.load();
  571      try { const r = localStorage.getItem(MJ_KEY); if (r) return JSON.parse(r); } catch (_) {}
  572      return { trades: [], deleted: [] };
  573    }
  574    // Local-only save: for changes the rules COMPUTE (TP scale-outs, stop trails,
  575    // auto-closes). Every device re-derives these from the same entry/targets +
  576    // price, so they must NEVER be pushed to the shared cloud store — doing so on
  577    // every price move is what burned the KV write quota.
  578    function mjSaveLocal(d) {
  579      if (window.GBSSync) { window.GBSSync.saveLocal(d); return; }
  580      localStorage.setItem(MJ_KEY, JSON.stringify(d));
  581    }
  582    // Cloud save: ONLY for genuine user actions (take / close / delete / import).
  583    function mjSave(d) {
  584      if (window.GBSSync) { window.GBSSync.saveLocal(d); window.GBSSync.syncOutDebounced(); return; }
  585      localStorage.setItem(MJ_KEY, JSON.stringify(d));
  586    }
  587  
  588    // ── state + render ────────────────────────────────────────────────────────
  589    const state = { bot: { open: [], closed: [] }, me: { open: [], closed: [] } };
  590  
  591    function splitBot(book) {
  592      const open = (book.open || []).slice();
  593      const closed = (book.closed || []).slice();
  594      // Bot trades already carry net realized_r + risk_usd from the server.
  595      // updated_at rides along so the UI can show how fresh the bot's marks are.
  596      return { open, closed, updated_at: book.updated_at || null };
  597    }
  598    function splitMe(data) {
  599      const trades = (data.trades || []).filter((t) => t && t.status);
  600      const open = [], closed = [];
  601      for (const t of trades) {
  602        if (t.status === "open") { ensureInit(t); open.push(t); }
  603        else if (t.status === "closed") { ensureClosedR(t); closed.push(t); }
  604      }
  605      return { open, closed };
  606    }
  607  
  608    function renderSide(side) {
  609      const d = state[side], pre = side;
  610      const s = stats(d.closed, d.open.length);
  611      statCards($("#" + pre + "-stats"), s);
  612      drawEquity(pre + "-equity", series(d.closed), side === "bot" ? "Claude" : "you");
  613      $("#" + pre + "-open").innerHTML = openRows(d.open, side, Date.now());
  614      $("#" + pre + "-closed").innerHTML = closedRows(d.closed);
  615      $("#" + pre + "-open-n").textContent = d.open.length ? `(${d.open.length})` : "";
  616      $("#" + pre + "-closed-n").textContent = d.closed.length ? `(${d.closed.length})` : "";
  617      return s;
  618    }
  619  
  620    function renderComparison(sb, sm) {
  621      drawEquity("cmp-eq-bot", series(state.bot.closed), "Claude");
  622      drawEquity("cmp-eq-me", series(state.me.closed), "you");
  623      const row = (label, b, m, fmt, better) => {
  624        const bv = fmt(b), mv = fmt(m);
  625        const lead = better == null ? "" : (b > m ? "lead-bot" : m > b ? "lead-me" : "");
  626        return `<div class="cmp-row ${lead}">
  627          <span class="cmp-k">${label}</span>
  628          <span class="cmp-v cmp-bot">${bv}</span>
  629          <span class="cmp-vs">vs</span>
  630          <span class="cmp-v cmp-me">${mv}</span></div>`;
  631      };
  632      $("#cmp-stats").innerHTML =
  633        `<div class="cmp-head"><span></span><span class="cmp-bot">🤖 Claude</span><span></span><span class="cmp-me">✏️ Me</span></div>` +
  634        row("Account value", START_CAPITAL + sb.totalD, START_CAPITAL + sm.totalD, money0, true) +
  635        row("Total R", sb.totalR, sm.totalR, rfmt, true) +
  636        row("Total $", sb.totalD, sm.totalD, dfmt, true) +
  637        row("Win rate", sb.win || 0, sm.win || 0, (v) => v ? v.toFixed(0) + "%" : "—", true) +
  638        row("Trades", sb.n, sm.n, (v) => String(v), null) +
  639        row("Open now", sb.open, sm.open, (v) => String(v), null) +
  640        row("Max DD", sb.maxDD, sm.maxDD, dfmt, null);
  641    }
  642  
  643    // ── Edge tracker: forward expectancy per setup cell (timeframe × trigger) ──
  644    // This is the table that eventually says which setups ACTUALLY make money
  645    // forward — the backtest's answer (weekly reclaim best) checked against real
  646    // closed trades. Cells need ~20 trades before the numbers mean anything.
  647    function renderEdgeTracker() {
  648      const host = $("#edge-tracker");
  649      if (!host) return;
  650      const closed = [...state.bot.closed, ...state.me.closed]
  651        .filter((t) => t.realized_r != null);
  652      if (!closed.length) {
  653        host.innerHTML = `<div class="jr-empty">No closed trades yet — as positions close, this breaks down
  654          win rate and average R by setup (e.g. Weekly reclaim vs Daily reclaim), so you can see which
  655          cells carry the edge forward, not just in the backtest.</div>`;
  656        return;
  657      }
  658      const cells = new Map();
  659      for (const t of closed) {
  660        const tf = TF_NAME[t.timeframe] || t.timeframe || "?";
  661        const et = String(entryTypeOf(t) || "—").toLowerCase();
  662        const key = `${tf} ${et}`;
  663        let c = cells.get(key);
  664        if (!c) { c = { key, et, n: 0, wins: 0, sumR: 0 }; cells.set(key, c); }
  665        c.n += 1; c.sumR += t.realized_r;
  666        if (t.realized_r > 0) c.wins += 1;
  667      }
  668      const rows = [...cells.values()].sort((a, b) => (b.sumR / b.n) - (a.sumR / a.n)).map((c) => {
  669        const avg = c.sumR / c.n, win = 100 * c.wins / c.n;
  670        const thin = c.n < 20 ? ` <span class="num-sub" title="Fewer than 20 trades — read directionally only">⚠</span>` : "";
  671        return `<tr>
  672          <td><span class="jr-setup ${SETUP_CLS[c.et] || ""}">${esc(c.key)}</span></td>
  673          <td class="num">${c.n}${thin}</td>
  674          <td class="num">${win.toFixed(0)}%</td>
  675          <td class="num ${rcls(avg)}">${rfmt(avg)}</td>
  676          <td class="num ${rcls(c.sumR)}">${rfmt(c.sumR)}</td></tr>`;
  677      }).join("");
  678      host.innerHTML = `<table class="jr-table"><thead><tr>
  679        <th>Setup</th><th class="num">Trades</th><th class="num">Win %</th>
  680        <th class="num">Avg R</th><th class="num">Total R</th></tr></thead>
  681        <tbody>${rows}</tbody></table>`;
  682    }
  683  
  684    // ── Lens tracker: same idea as the edge tracker, but split by which LENS
  685    // produced the trade (chart.js stamps `lens` on every sim trade since
  686    // 2026-07-05; older trades group under "untagged").
  687    function renderLensTracker() {
  688      const host = $("#lens-tracker");
  689      if (!host) return;
  690      const closed = [...state.bot.closed, ...state.me.closed]
  691        .filter((t) => t.realized_r != null);
  692      if (!closed.length) {
  693        host.innerHTML = `<div class="jr-empty">No closed trades yet — as positions close, this shows
  694          win rate and expectancy per LENS (VIVEK vs PhaseMap vs Specs), so the three-lens system gets
  695          judged by results, not vibes.</div>`;
  696        return;
  697      }
  698      const cells = new Map();
  699      for (const t of closed) {
  700        const key = String(t.lens || "untagged").toLowerCase();
  701        let c = cells.get(key);
  702        if (!c) { c = { key, n: 0, wins: 0, sumR: 0, sumD: 0 }; cells.set(key, c); }
  703        c.n += 1; c.sumR += t.realized_r;
  704        c.sumD += (dollarsOf(t) || 0);
  705        if (t.realized_r > 0) c.wins += 1;
  706      }
  707      const rows = [...cells.values()].sort((a, b) => (b.sumR / b.n) - (a.sumR / a.n)).map((c) => {
  708        const avg = c.sumR / c.n, win = 100 * c.wins / c.n;
  709        const thin = c.n < 20 ? ` <span class="num-sub" title="Fewer than 20 trades — read directionally only">⚠</span>` : "";
  710        return `<tr>
  711          <td><span class="jr-setup">${esc(c.key.toUpperCase())}</span></td>
  712          <td class="num">${c.n}${thin}</td>
  713          <td class="num">${win.toFixed(0)}%</td>
  714          <td class="num ${rcls(avg)}">${rfmt(avg)}</td>
  715          <td class="num ${rcls(c.sumR)}">${rfmt(c.sumR)}</td>
  716          <td class="num ${pcls(c.sumD)}">${dfmt(c.sumD)}</td></tr>`;
  717      }).join("");
  718      host.innerHTML = `<table class="jr-table"><thead><tr>
  719        <th>Lens</th><th class="num">Trades</th><th class="num">Win %</th>
  720        <th class="num">Avg R</th><th class="num">Total R</th><th class="num">Total $</th></tr></thead>
  721        <tbody>${rows}</tbody></table>`;
  722    }
  723  
  724    // ── NEW POSITIONS RECENTLY TAKEN (owner 2026-07-05): one small box per
  725    // side at the top of the page — every position opened in the last 7 days,
  726    // newest first, so the daily check-in is a single glance.
  727    const NEW_POS_WINDOW_MS = 7 * 24 * 3.6e6;
  728    function renderNewPositions() {
  729      const now = Date.now();
  730      const ago = (ms) => {
  731        const h = (now - ms) / 3.6e6;
  732        if (h < 1) return "just now";
  733        if (h < 24) return Math.round(h) + "h ago";
  734        const d = Math.floor(h / 24);
  735        return d === 1 ? "1d ago" : d + "d ago";
  736      };
  737      const paint = (hostId, side, label) => {
  738        const host = $("#" + hostId);
  739        if (!host) return;
  740        const recent = [...side.open, ...side.closed]
  741          .map((t) => ({ t, ms: openedMs(t) }))
  742          .filter((x) => x.ms != null && now - x.ms <= NEW_POS_WINDOW_MS)
  743          .sort((a, b) => b.ms - a.ms)
  744          .slice(0, 6);
  745        const rows = recent.map(({ t, ms }) =>
  746          `<a class="jr-new-row" href="chart.html?m=${marketOf(t)}&s=${encodeURIComponent(t.symbol)}&pm=1">
  747            ${dirChip(t.direction)}
  748            <b class="jr-new-sym">${esc(t.symbol)}</b>
  749            <span class="jr-new-entry">@ ${px(t.entry)}</span>
  750            ${t.lens ? `<span class="jr-new-lens">${up(t.lens)}</span>` : ""}
  751            ${t.status === "closed" ? `<span class="jr-new-closed">closed</span>` : ""}
  752            ${flipChip(t)}
  753            <span class="jr-new-ago">${ago(ms)}</span>
  754          </a>`).join("");
  755        host.innerHTML = `<div class="jr-new-hd">${label} <span class="jr-new-n">${recent.length}</span></div>` +
  756          (rows || `<div class="jr-new-empty">No new positions in the last 7 days.</div>`);
  757      };
  758      paint("new-bot", state.bot, "🤖 Claude · new positions");
  759      paint("new-me", state.me, "✏️ Me · new positions");
  760    }
  761  
  762    function renderAll() {
  763      const sb = renderSide("bot"), sm = renderSide("me");
  764      renderNewPositions();
  765      renderComparison(sb, sm);
  766      renderBoth();
  767      renderEdgeTracker();
  768      renderLensTracker();
  769      const note = $("#bot-note");
  770      if (note) {
  771        if (state.bot.open.length || state.bot.closed.length) {
  772          // Freshness instead of blank: how old are the bot's marks? Amber >2h.
  773          const t = Date.parse(state.bot.updated_at || "");
  774          const m = isFinite(t) ? Math.max(0, Math.round((Date.now() - t) / 60000)) : null;
  775          note.textContent = m == null ? "" :
  776            m < 60 ? `marked ${m}m ago` : m < 48 * 60 ? `marked ${Math.round(m / 60)}h ago` : `marked ${Math.round(m / 1440)}d ago`;
  777          note.style.color = m != null && m > 120 ? "var(--orange)" : "";
  778        } else {
  779          note.textContent = "Autonomous bot is in dry-run — its trades appear here once enabled.";
  780        }
  781      }
  782      // Always-visible account summary in the sticky topbar: who's where, at a glance.
  783      const ts = $("#jr-topsum");
  784      if (ts) {
  785        const cell = (who, st, openN) =>
  786          `<span class="ts-who">${who}</span><span class="${pcls(st.totalD)}">${money0(START_CAPITAL + st.totalD)}</span>` +
  787          `<span class="ts-who">· ${openN} open</span>`;
  788        ts.innerHTML = cell("🤖", sb, state.bot.open.length) + cell("✏️", sm, state.me.open.length);
  789      }
  790      const fxn = $("#fx-note");
  791      if (fxn) fxn.textContent = ` · $ figures in US$ — ASX P&L converted at AUD/USD ${FX_AUDUSD.toFixed(4)}`;
  792      // Strategy-review checkpoint (owner decision, locked until the evidence
  793      // exists): NASDAQ slot weighting + confluence priority get reviewed at 30
  794      // closed bot trades — not before, so the forward test isn't reset mid-run.
  795      const chk = $("#review-checkpoint");
  796      if (chk) {
  797        const n = state.bot.closed.length;
  798        chk.textContent = n >= 30
  799          ? `✅ Review checkpoint reached — ${n}/30 closed bot trades: time to review NASDAQ allocation & confluence priority.`
  800          : `Strategy review checkpoint: ${n}/30 closed bot trades. NASDAQ allocation & confluence-priority decisions stay locked until then.`;
  801      }
  802    }
  803  
  804    // Run async work in small waves so we never burst dozens of quote requests at
  805    // once (Yahoo throttles bursts, which made the "Now" column fall back to "—").
  806    async function inBatches(items, size, fn) {
  807      for (let i = 0; i < items.length; i += size) {
  808        await Promise.all(items.slice(i, i + size).map(fn));
  809      }
  810    }
  811  
  812    // ── live refresh: price the MANUAL opens, auto-manage them, update cells ────
  813    // Bot rows are already marked to market by the scan (rendered from the book
  814    // JSON), so this only touches Me rows. Each Me symbol's price comes from the
  815    // latest scan snapshot first (reliable, refreshes every scan); a live quote is
  816    // only fetched as a fallback when the symbol isn't in the current scan.
  817    async function refreshLive() {
  818      let meChanged = false;   // any persisted change (MAE/MFE, scale-out, close)
  819      let meClosed = false;    // a position actually CLOSED → rows move tables
  820      const data = mjLoad();
  821      const byId = new Map((data.trades || []).map((t) => [t.id, t]));
  822  
  823      // Each Me position is rendered in TWO tables (combined + per-section), so
  824      // GROUP rows by symbol and resolve each symbol's price once.
  825      const trs = $$("tbody tr[data-tid][data-side='me']");
  826      const keyOf = (t) => marketOf(t) + ":" + String(t.symbol || "").toUpperCase();
  827      const groups = new Map();            // key -> { src, rows:[tr], manual }
  828      for (const tr of trs) {
  829        const id = tr.getAttribute("data-tid");
  830        const src = byId.get(id);
  831        if (!src) continue;
  832        const key = keyOf(src);
  833        let g = groups.get(key);
  834        if (!g) { g = { src, key, rows: [], manual: src }; groups.set(key, g); }
  835        g.rows.push(tr);
  836      }
  837  
  838      const paint = (g, price) => {
  839        if (g.manual && price != null) {
  840          const r = manage(g.manual, price);   // false | "book" | "close"
  841          if (r) { meChanged = true; if (r === "close") meClosed = true; }
  842        }
  843        const src = g.src;
  844        for (const tr of g.rows) {
  845          const nowCell = tr.querySelector(".jr-now");
  846          if (!nowCell || !document.body.contains(nowCell)) continue;
  847          const urCell = tr.querySelector(".jr-ur");
  848          const udCell = tr.querySelector(".jr-ud");
  849          if (price == null) { nowCell.textContent = "—"; continue; }
  850          const isLong = src.direction !== "short";
  851          const risk = src.risk != null ? src.risk : Math.abs(src.entry - (src.stop ?? src.entry));
  852          const ru = src.risk_usd;
  853          nowCell.textContent = px(price);
  854          if (src.status === "closed") { nowCell.textContent = "closed"; continue; }
  855          if (risk > 0) {
  856            const ur = rOf(price, src.entry, risk, isLong);
  857            if (urCell) { urCell.textContent = rfmt(ur); urCell.className = "num jr-ur " + rcls(ur); }
  858            if (ru != null && udCell) { const ud = ur * ru * fxOf(src); udCell.textContent = d2(ud); udCell.className = "num jr-ud " + pcls(ud); }
  859          }
  860        }
  861      };
  862  
  863      // Scan price first (reliable, every scan); live quote only if absent.
  864      await inBatches([...groups.values()], 6, async (g) => {
  865        const price = scanPrice.has(g.key) ? scanPrice.get(g.key) : await priceFor(g.src);
  866        paint(g, price);
  867      });
  868  
  869      // Persist rule-computed changes (scale-outs, auto-close) LOCALLY only — never
  870      // to the cloud (each device re-derives them, so cloud pushes here just burned
  871      // the KV quota). Only RE-RENDER when a position actually closed (rows move
  872      // between the open/closed tables).
  873      if (meChanged) mjSaveLocal(data);
  874      if (meClosed) { loadMe(data); renderAll(); }
  875    }
  876  
  877    // ── loaders ───────────────────────────────────────────────────────────────
  878    function loadMe(data) { state.me = splitMe(data || mjLoad()); }
  879    async function loadBot() {
  880      try {
  881        const r = await fetch("data/vivek_bot_book.json", { cache: "no-cache" });
  882        if (r.ok) state.bot = splitBot(await r.json());
  883      } catch (_) { /* keep empty */ }
  884    }
  885    // Pull per-symbol grade/trigger (fallback) + the scan's last price (the Now
  886    // source for manual trades) from the live scans. Re-runnable: prices overwrite.
  887    async function loadScanMeta() {
  888      const files = [["asx_vivek.json", "asx"], ["nasdaq_vivek.json", "nasdaq"], ["crypto_vivek.json", "crypto"]];
  889      await Promise.all(files.map(async ([f, mkt]) => {
  890        try {
  891          const r = await fetch("data/" + f, { cache: "no-cache" });
  892          if (!r.ok) return;
  893          const j = await r.json();
  894          for (const row of (j.results || [])) {
  895            const sym = String(row.symbol || "").toUpperCase();
  896            if (!sym) continue;
  897            if (!scanMeta.has(sym)) scanMeta.set(sym, { grade: row.grade || null, entry_type: row.entry_trigger || null, dir: row.dir || null });
  898            if (row.price != null) scanPrice.set(mkt + ":" + sym, +row.price);
  899          }
  900          // Universe-wide last-close snapshot — covers held names that are no longer
  901          // a current setup (so any open position can be priced from the scan).
  902          const pm = j.prices || {};
  903          for (const sym in pm) {
  904            if (pm[sym] != null) scanPrice.set(mkt + ":" + String(sym).toUpperCase(), +pm[sym]);
  905          }
  906        } catch (_) { /* skip a missing/blocked file */ }
  907      }));
  908    }
  909  
  910    // ── close modal (Me) ──────────────────────────────────────────────────────
  911    let closeId = null;
  912    function openCloseModal(id) {
  913      const t = mjLoad().trades.find((x) => x.id === id);
  914      if (!t) return;
  915      closeId = id;
  916      $("#jr-modal-title").textContent = "Close " + String(t.symbol || "").toUpperCase();
  917      $("#jr-exit-price").value = "";
  918      $("#jr-price-tag").textContent = "loading live…";
  919      $("#jr-close-overlay").hidden = false;
  920      priceFor(t).then((p) => { if (p != null) { $("#jr-exit-price").value = +(+p).toFixed(6); $("#jr-price-tag").textContent = "live"; } else $("#jr-price-tag").textContent = ""; });
  921    }
  922    function closeModal() { $("#jr-close-overlay").hidden = true; closeId = null; }
  923  
  924    // Remove a manual trade entirely (no P&L logged) — for setups you logged but
  925    // didn't actually take (e.g. a fund/REIT not listed on your broker). Records a
  926    // tombstone so the deletion propagates across synced devices.
  927    // Post-trade review needs the WHY, not just the numbers — a free-text note
  928    // per manual trade (cloud-synced: adding/editing one is a genuine user action).
  929    function editNote(id) {
  930      const data = mjLoad();
  931      const t = data.trades.find((x) => x.id === id);
  932      if (!t) return;
  933      const note = prompt(`Note for ${String(t.symbol || "").toUpperCase()} — why did you take it?`,
  934                          t.note || "");
  935      if (note == null) return;                      // cancelled
  936      t.note = note.trim();
  937      if (!t.note) delete t.note;
  938      t.mtime = Date.now();
  939      mjSave(data);
  940      renderAll();
  941      refreshLive();
  942    }
  943  
  944    function removeTrade(id) {
  945      const data = mjLoad();
  946      const t = (data.trades || []).find((x) => x.id === id);
  947      if (!t) return;
  948      const sym = String(t.symbol || "").toUpperCase();
  949      if (!confirm(`Remove ${sym} from your journal?\n\nThis deletes the trade entirely — no profit/loss is logged. Use this for setups you didn't actually take.`)) return;
  950      data.trades = (data.trades || []).filter((x) => x.id !== id);
  951      if (!Array.isArray(data.deleted)) data.deleted = [];
  952      if (!data.deleted.includes(id)) data.deleted.push(id);
  953      mjSave(data); loadMe(data); renderAll(); refreshLive();
  954    }
  955    function saveClose() {
  956      if (!closeId) return;
  957      const data = mjLoad();
  958      const t = data.trades.find((x) => x.id === closeId);
  959      const exit = parseFloat($("#jr-exit-price").value);
  960      if (!t || !(exit > 0)) return;
  961      t.status = "closed"; t.exit = exit; t.exit_date = today(); t.exit_time = nowTime();
  962      t.exit_reason = "manual"; t.mtime = Date.now();
  963      delete t._init;                              // force a clean re-resolve
  964      mjSave(data); closeModal(); loadMe(data); renderAll(); refreshLive();
  965    }
  966  
  967    // ── cross-device sync + backup/restore (Cloudflare KV via gbs-sync) ────────
  968    function syncStatus(msg, cls) {
  969      const el = $("#mj-sync-status");
  970      if (el) { el.textContent = msg || ""; el.className = "mj-sync-status" + (cls ? " " + cls : ""); }
  971    }
  972    function afterStoreChange() { loadMe(); renderAll(); refreshLive(); }
  973    function wireSync() {
  974      // Backup / Restore
  975      const exportBtn = $("#mj-export-btn");
  976      if (exportBtn) exportBtn.addEventListener("click", () => {
  977        const blob = new Blob([JSON.stringify(mjLoad(), null, 2)], { type: "application/json" });
  978        const url = URL.createObjectURL(blob);
  979        const a = Object.assign(document.createElement("a"), { href: url, download: `my-trades-${today()}.json` });
  980        document.body.appendChild(a); a.click(); a.remove();
  981        setTimeout(() => URL.revokeObjectURL(url), 1000);
  982      });
  983      // CSV of BOTH books (open + closed) — for tax time and Excel analysis.
  984      // $ P&L column is US$-converted like the page; native risk/prices as-is.
  985      const csvBtn = $("#mj-csv-btn");
  986      if (csvBtn) csvBtn.addEventListener("click", () => {
  987        const cols = ["side", "symbol", "market", "direction", "grade", "entry_type",
  988                      "timeframe", "status", "entry", "stop", "exit", "entry_date",
  989                      "exit_date", "exit_reason", "realized_r", "risk_usd",
  990                      "pnl_usd", "note"];
  991        const csvEsc = (v) => {
  992          const s = v == null ? "" : String(v);
  993          return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  994        };
  995        const rows = [];
  996        const push = (t, side) => rows.push(cols.map((c) => csvEsc(
  997          c === "side" ? side
  998          : c === "pnl_usd" ? (dollarsOf(t) == null ? "" : dollarsOf(t).toFixed(2))
  999          : c === "market" ? marketOf(t)
 1000          : t[c])).join(","));
 1001        for (const t of [...state.bot.open, ...state.bot.closed]) push(t, "claude");
 1002        for (const t of [...state.me.open, ...state.me.closed]) push(t, "me");
 1003        const blob = new Blob([cols.join(",") + "\n" + rows.join("\n") + "\n"], { type: "text/csv" });
 1004        const url = URL.createObjectURL(blob);
 1005        const a = Object.assign(document.createElement("a"), { href: url, download: `vivek-journal-${today()}.csv` });
 1006        document.body.appendChild(a); a.click(); a.remove();
 1007        setTimeout(() => URL.revokeObjectURL(url), 1000);
 1008      });
 1009      const importBtn = $("#mj-import-btn"), importInput = $("#mj-import-input");
 1010      if (importBtn && importInput) {
 1011        importBtn.addEventListener("click", () => importInput.click());
 1012        importInput.addEventListener("change", () => {
 1013          const file = importInput.files && importInput.files[0];
 1014          if (!file) return;
 1015          const reader = new FileReader();
 1016          reader.onload = () => {
 1017            let incoming;
 1018            try { incoming = JSON.parse(reader.result); } catch (_) { alert("That file isn't valid trade backup JSON."); return; }
 1019            if (!incoming || !Array.isArray(incoming.trades)) { alert("That file doesn't look like a trades backup."); return; }
 1020            const merged = window.GBSSync ? window.GBSSync.merge(mjLoad(), incoming) : incoming;
 1021            mjSave(merged); afterStoreChange();
 1022            alert(`Imported — ${merged.trades.length} trade(s) now in your journal.`);
 1023          };
 1024          reader.readAsText(file); importInput.value = "";
 1025        });
 1026      }
 1027      // Cloud sync (private code)
 1028      const codeEl = $("#mj-sync-code"), onBtn = $("#mj-sync-on"), offBtn = $("#mj-sync-off"), nowBtn = $("#mj-sync-now");
 1029      if (!codeEl || !window.GBSSync) return;
 1030      const reflect = () => {
 1031        const on = window.GBSSync.enabled();
 1032        codeEl.value = on ? window.GBSSync.getCode() : "";
 1033        if (onBtn) onBtn.classList.toggle("mj-hidden", on);
 1034        if (offBtn) offBtn.classList.toggle("mj-hidden", !on);
 1035        if (nowBtn) nowBtn.classList.toggle("mj-hidden", !on);
 1036        syncStatus(on ? "Sync ON — same trades on every device with this code." : "", on ? "live" : "");
 1037      };
 1038      const enable = async () => {
 1039        const code = (codeEl.value || "").trim();
 1040        if (code.length < 4) { syncStatus("Pick a code with at least 4 characters.", "neg"); return; }
 1041        window.GBSSync.setCode(code); syncStatus("Connecting…");
 1042        try {
 1043          const probe = await window.GBSSync.pull();
 1044          if (probe.configured === false) {
 1045            window.GBSSync.setCode(""); reflect();
 1046            syncStatus("Cloud sync isn't set up on the server yet — use Backup/Restore for now.", "neg"); return;
 1047          }
 1048          await window.GBSSync.syncOut(); afterStoreChange(); reflect();
 1049        } catch (_) { syncStatus("Couldn't reach the sync server — trades are still saved on this device.", "neg"); }
 1050      };
 1051      const syncedAt = () => syncStatus("Synced at " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), "live");
 1052      if (onBtn) onBtn.addEventListener("click", enable);
 1053      if (offBtn) offBtn.addEventListener("click", () => { window.GBSSync.setCode(""); reflect(); syncStatus("Sync off — this device keeps its own copy."); });
 1054      if (nowBtn) nowBtn.addEventListener("click", async () => { syncStatus("Syncing…"); try { await window.GBSSync.syncOut(); afterStoreChange(); syncedAt(); } catch (_) { syncStatus("Sync failed — will retry on the next change.", "neg"); } });
 1055      codeEl.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); enable(); } });
 1056      const silentPull = async () => { if (!window.GBSSync.enabled()) return; try { await window.GBSSync.syncIn(); afterStoreChange(); syncedAt(); } catch (_) {} };
 1057      document.addEventListener("visibilitychange", () => { if (!document.hidden) silentPull(); });
 1058      setInterval(() => { if (!document.hidden) silentPull(); }, 60000);
 1059      reflect();
 1060      if (window.GBSSync.enabled()) silentPull();
 1061    }
 1062  
 1063    // ── wire-up ───────────────────────────────────────────────────────────────
 1064    function wire() {
 1065      document.addEventListener("click", (e) => {
 1066        const del = e.target.closest("[data-del]");
 1067        if (del) { removeTrade(del.getAttribute("data-del")); return; }
 1068        const noteBtn = e.target.closest("[data-note]");
 1069        if (noteBtn) { editNote(noteBtn.getAttribute("data-note")); return; }
 1070        const btn = e.target.closest("[data-close]");
 1071        if (btn) openCloseModal(btn.getAttribute("data-close"));
 1072      });
 1073      $("#jr-modal-x").addEventListener("click", closeModal);
 1074      $("#jr-modal-cancel").addEventListener("click", closeModal);
 1075      $("#jr-modal-save").addEventListener("click", saveClose);
 1076      $("#jr-close-overlay").addEventListener("click", (e) => { if (e.target.id === "jr-close-overlay") closeModal(); });
 1077      // react to manual trades opened on another tab/device
 1078      window.addEventListener("storage", (e) => { if (e.key === MJ_KEY) { loadMe(); renderAll(); refreshLive(); } });
 1079      document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshLive(); });
 1080      setInterval(() => { if (!document.hidden) refreshLive(); }, 20000);
 1081      // Pick up a fresh scan while the page is open: re-pull the bot book + scan
 1082      // prices every few minutes and re-render (the bot side + manual Now update).
 1083      setInterval(async () => {
 1084        if (document.hidden) return;
 1085        await Promise.all([loadBot(), loadScanMeta()]);
 1086        renderAll();
 1087        refreshLive();
 1088      }, 180000);
 1089    }
 1090  
 1091    async function init() {
 1092      loadMe();
 1093      renderAll();                 // paint Me immediately
 1094      await Promise.all([loadBot(), loadScanMeta(), loadFx()]);
 1095      renderAll();                 // repaint with Claude + grade/setup fallback
 1096      wire();
 1097      wireSync();
 1098      refreshLive();
 1099    }
 1100  
 1101    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
 1102    else init();
 1103  })();
```


---

# PART D — COMPLETE FILE MAP

Every source file, with line count and responsibility. Files marked **[INLINED]** appear verbatim in Part C — review those directly. For all others, reason from the description; flag findings **[INFERRED — needs the file]** and name the file.

## scanner/ — Python signal engines, journals, alerts (run in GitHub Actions)

| File | LoC | Responsibility & known/suspect issues |
|---|---|---|
| `config.py` | 798 | ALL tunable constants (SMA/tolerances/grades/bot sizing/leverage/limits/fees). Relevant constants inlined in Part C. **No constant may be hardcoded elsewhere** — check for drift. |
| `vivek.py` | 651 | **[INLINED]** The VIVEK 200-SMA engine: `evaluate` (build signal), levels/plans per timeframe (weekly/3d/daily-"h4"), grading, direction, `detect_trigger` (reclaim/retest/break), `narrative`. The heart of signal correctness. |
| `scan.py` | 254 | **[INLINED]** Orchestrates a VIVEK market scan: for each ticker builds the row, applies grade hysteresis (`_load_prev_grades`/`apply_grade_hysteresis`), gates armed/R:R off the **1D plan**, writes `<market>_vivek.json`. Note line ~152: headline plan is always 1D regardless of `level_tf`. |
| `run.py` | 215 | CLI entry `python -m scanner.run`. Calls scan per market, writes sectors.json + bot_rules.json, invokes the bot runner + journal. Also historically emitted the retired PULSE (now `pulse_data=[]`) and the retired legacy journal via `--journal`. |
| `spec.py` | 181 | Specs engine (volume-spike base breakout, sub-$0.50). Gates: spike≥3×, off-high≥40%, price>base-high, 9SMA rising. `SPEC_MAX_PRICE=0.50` — structurally excludes all of NASDAQ (min-bid ~$4). |
| `spec_run.py` | 178 | Nightly Specs orchestrator (asx+nasdaq) → `<m>_spec.json` + static candle files. |
| `spec_backtest.py` | 238 | Specs proof-of-edge replay. |
| `vivek_backtest.py` | 459 | **[INLINED]** Walk-forward replay of the REAL engine (no look-ahead): candidate mask (near any 200-SMA incl 3D), `_build_row`, `_snapshot`/`_mark`/`_manage_bar` (pessimistic intrabar, stop-first), cohorts by entry_type/timeframe/level_tf/grade/direction. Owns `vivek_backtest.json`. **Compare its management rules to the live bot for drift.** |
| `vivek_journal.py` | 372 | Trade-management primitives (`_snapshot`, `_mark`, `_apply_costs`, `_r_of`, `costs_for`) shared by the backtester and bot runner. The journal-as-track-record role was retired; the module stays for these primitives. |
| `confluence_alert.py` | 266 | Computes 2+/3-lens direction-aligned alignments from the 3 latest scan files; posts to Discord (state-deduped via `journal/confluence_state.json`); appends to `alert_history.json` (cap 800, "permanent log" — actually ~25 days). Watchlist-aware pings gated on `GBS_SYNC_CODE` (unset → dormant). |
| `universe.py` | 239 | Loads tickers. ASX from official directory (~2000); NASDAQ Global Select (~1430) — returns `sector:""` for every NASDAQ+crypto name (breaks the sector cap); crypto top-100 from CoinGecko + `CRYPTO_EXTRA_SYMBOLS`. |
| `data.py` | 262 | yfinance batch downloader (chunked, retry). Sole decision-data source. |
| `marketcaps.py` | 205 | Market-cap cache. `_SCAN_FILES` still lists retired outputs (asx.json/asx_reversal.json…) that no longer exist; non-atomic cache write. |
| `sectors.py` | 408 | Sector/index dashboard (the NEWS page) + movers. |
| `indicators.py` | 142 | EMA/SMA/RSI/ADX/SuperTrend/pivots. |
| `grading.py` | 36 | `grade_from_points`/`score_chips`. |
| `discord.py` | 273 | Discord webhook builders + digest. |
| `confluence_alert.py` | (above) | |
| `journal_common.py` | 84 | Shared journal helpers. |
| `pulse.py` | 64 | Macro-quote fetcher — **retired from UI; `run.py` no longer calls it** (dead-ish). |
| **DEAD/RETIRED** | | `notify.py` (451, Telegram digest — nothing imports it), `alerts.py` (176, email — never wired, `--alert` unused), `reversal.py` (188) + `analysis.py` (86, imported only by reversal), `journal.py` (327, legacy fib journal — writes `journal.json` nobody reads), `scalp_journal.py` (404, retired scalp path). **Confirm each is truly unreachable before recommending deletion.** |

## scanner/broker/ — execution + risk (the money path)

| File | LoC | Responsibility & known/suspect issues |
|---|---|---|
| `vivek_bot.py` | 450 | **[INLINED]** Pure decision engine: A+-only gate, entry-type/timeframe selection (`_pick_plan` — considers 1W/1D, not 3D), sizing (`size_position`), fund/REIT exclusion, book caps (max 10, ≥N short reserve, one/symbol, sector cap that no-ops on empty sectors). No broker calls. |
| `vivek_run.py` | 451 | **[INLINED]** The paper-book runner invoked each scan: downloads *universe* frames, reconciles the book, opens/marks/closes paper positions per market. Imports only `vivek_bot`+`vivek_guard` — NOT the hardened risk stack. Suspected: open-book positions not in the universe download are unpriceable. |
| `vivek_guard.py` | 97 | **[INLINED]** Per-market daily-loss guard for the VIVEK book. |
| `bybit_bracket.py` | 163 | **[INLINED]** Builds/submits a Bybit bracket (entry+embedded TP/SL). Hardcoded qty/price decimal ladders; `submit()` double-loops retries; deterministic `orderLinkId`. |
| `bybit_client.py` | 216 | **[INLINED]** pybit HTTP wrapper: `place_order`, cancel(_all), `get_positions`, `close_position(_all)`, `get_order_status`, `get_closed_pnl`, `wallet_balance`, `_retry` (retries any exception). Testnet-gated. |
| `bybit_reconcile.py` | 159 | **[INLINED]** Syncs Bybit → scalp journal. Reads `exitType` (V5 sends `execType`); deducts `BROK_RT`=$40 CFD fee from crypto PnL; only walks `j['open']` (orphans invisible); pending-forever GTC. |
| `bybit_run.py` | 469 | Live/paper crypto runner (the scalp path). Wires pre_trade_check + circuit_breaker + kill_switch (which the VIVEK path does NOT). |
| `pre_trade_check.py` | 174 | **[INLINED]** 12-gate pre-trade validation (sizing, spread, session, correlation, daily cap…). Only wired into bybit_run/paper_run. |
| `circuit_breaker.py` | 176 | **[INLINED]** Consecutive-loss / drawdown / anomaly halts. Only wired into the scalp path. |
| `kill_switch.py` | 126 | **[INLINED]** Flatten-all on daily-loss breach. `check_and_kill` reads the **scalp** journal's session P&L (`SCALP_MAX_DAILY_LOSS`); does it cover the VIVEK book? |
| `risk_manager.py` | 304 | Python risk engine (sizing/heat/stance). Mirrors — and may drift from — `public/js/risk_manager.js`. |
| `paper_run.py` | 216 | Paper crypto runner. |
| `reconcile.py` / `bracket_order.py` / `alpaca_client.py` | 132/90/82 | **Legacy Alpaca** OCO path — superseded by Bybit; confirm dead. |
| `anomaly.py` `attribution.py` `expectancy.py` `fill_analysis.py` `performance_report.py` `scaling_advisor.py` `live_vs_backtest.py` `event_calendar.py` | 169/166/152/165/242/192/120/72 | Analytics/reporting layer feeding `public/data/*.json` (attribution/expectancy/performance/fill_analysis). Check whether any still write files the frontend reads, and whether they run at all. |
| `alert_digest.py` `alert_dispatch.py` `alert_router.py` | 174/119/234 | Alert fan-out (Discord/Telegram/email). |

## phasemap/ — the trap lens (detection maths SPEC-FROZEN; review engineering only)

| File | LoC | Responsibility |
|---|---|---|
| `run.py` | 208 | Nightly orchestrator. `run_date` stamped from (late) cron wall-clock; run_market loop has no per-ticker try/except; can publish empty results + mass-prune charts on a data outage. |
| `engine/setup_engine.py` | 555 | The state machine (TRAP_SET→…→DEAD). **Maths frozen** — review determinism/edge-handling only. |
| `engine/scanner.py` `zones.py` `indicators.py` `buffers.py` | 153/122/176/48 | Zone construction, indicators, ring buffers. |
| `output/writer.py` | 143 | Writes slim `latest.json` + `narrations.json` sidecar + full dated snapshot; `validate_snapshot`/`validate_published` schema gates. **`validate_snapshot` accepts results=[]** (empty-publish risk). |
| `narrate/renderer.py` `templates.py` | 132/177 | Deterministic narration templates. `_stats_text` interpolates market label verbatim ("on the CRYPTO"); 552 narrations collapse to ~18 skeletons. |
| `data/provider.py` | 63 | yfinance provider; silently `continue`s on missing symbols → empty cache on outage. |
| `backtest/harness.py` `report.py` `__main__.py` | 194/196/73 | Zero-lookahead replay → stats JSON feeding the narration `{stats}` slot + Insights. |
| `config.py` | 95 | `RULESET_VERSION` + zone params. |

## functions/api/ — Cloudflare Pages Functions (Workers runtime) — ALL [INLINED]

| File | LoC | Responsibility & suspect issues |
|---|---|---|
| `scan.js` | 132 | **[INLINED]** POST → dispatch `scan.yml`. KV cooldown (5min/market) + daily cap 40 — **non-atomic**. Echoes raw GitHub error bodies. |
| `close.js` | 105 | **[INLINED]** POST → dispatch `close_position.yml`. symbol/market only length-capped → **shell injection in the workflow**. No caller in `public/` (orphaned since the track journal was retired). |
| `journal.js` | 101 | **[INLINED]** GET/PUT the KV journal store. Key = SHA-256("gbs-journal:"+code). **No rate limit; 4-char min code → enumerable.** |
| `tick.js` | 175 | **[INLINED]** The cloud stop/target watcher. Auth **open by default** when `TICK_SECRET` unset; response **leaks closed-trade details across all journals**; mutates KV. |
| `price.js` `quote.js` | 80/59 | **[INLINED]** Yahoo/Binance price proxies. **No throttling** → free public data relay. |
| `_prices.js` `_vivek_manage.js` | 201/108 | **[INLINED]** Shared price fetch helper + the VIVEK cloud-management logic used by tick.js (mirrors the Python management — check parity; there is a `test/vivek_manage.test.js`). |

## public/js/ — frontend (vanilla, no build)

| File | LoC | Responsibility & suspect issues |
|---|---|---|
| `app.js` | 1809 | **[INLINED]** Dashboard: fetch scan → render rows/stats/filters/sorts/AT-LEVEL strip/confluence banner/search/notify bell. Suspects: 4× full-list innerHTML re-render (expanded panel snaps shut); AT-LEVEL tooltip reads wrong field (`r.dist_pct` vs `r.detail.dist_pct`); hardcoded VK_ENTRY_Q backtest numbers; M.C sort no-op on crypto; localStorage caches full 1.5MB payloads; ~350 lines of retired-lens render code + a zombie 90s pulse interval. |
| `chart.js` | 2758 | **[INLINED]** The chart page (a 148KB single IIFE): PhaseMap overlay, Binance/Yahoo live data, VIVEK plan ladder, PhaseMap-only fallback, sim buy/sell, prev/next nav, drawing tools, the new bot-position banner. Suspects: size calculator captures 1D entry/stop, not the active TF; crypto fallback hijacked to a 1H stream; retired scalp/reversal/short code + guaranteed-404 fetches; no visibilitychange (polls forever in background tabs); measure/OHLC desync on live path. |
| `journal.js` | 1103 | **[INLINED]** Journal page: bot book vs manual "Me", comparison overview (closed-only), edge/lens trackers (pooled bot+manual), NEW POSITIONS boxes, direction pills + flip warnings, close modal, live refresh. Suspects: manual close after TP1 books only the TP1 leg; sizing constants hardcoded (mirror drift); bot trades lack a `lens` field (tracker all UNTAGGED); crypto priced from hourly snapshot. |
| `risk_manager.js` | 1094 | The browser risk engine (sizing/kill/heat/stance). Duplicates the Python `broker/risk_manager.py` — check drift. Has JS unit tests. |
| `bot.js` | 766 | **[INLINED]** AI-BOT page: seeds RiskManager from `bot_status.json` (**frozen June file**), rules form (selects don't offer 0.35/10 → save writes junk), fake KILL SWITCH. |
| `phasemap-shared.js` | 372 | `PM` namespace: esc/fmt, `PM.watch` (unified KV-synced watchlist w/ tombstones + legacy migration), `loadConfluence` (re-fetches the just-parsed 1.5MB file), `staleBadgeHTML`, `fmtMelb`. Shared by phasemap/specs/mynames pages. |
| `phasemap.js` | 315 | PhaseMap list page. Fabricates TRAP_SET/LONG badges for snapshot-less stars; generic empty state on the watchlist tab. |
| `specs.js` | 219 | Specs list page. Expanded rows snap shut on async re-render; renders an always-empty NASDAQ tab. |
| `mynames.js` | 136 | ★ MY NAMES aggregation. Unstar → full network refetch of everything. |
| `alerts.js` | 108 | ALERTS log page (market filter, day-collapse, triples toggle, search, NEW dots). |
| `sectors.js` | 306 | NEWS page. Timestamps in viewer-local tz (violates Melbourne convention); `esc` escapes only `&<>` and is used in an attribute. |
| `gbs-sync.js` | 189 | The KV journal sync client (`GBSSync`). Silent quota-fail catch. Has JS tests. |
| `nav.js` | 103 | Shared top-nav renderer (recent addition — `#site-nav` mount). |
| `phasemap-insights.js` | 97 | Insights page: fills cards from `stats/*.json` (asx/nasdaq/specs_asx — **omits crypto**), falls back to hardcoded (now-contradictory) HTML. Fetches the 916KB backtest file but reads only aggregates. |
| `sw-register.js` | 37 | SW registration + update toast. |

## functions & workflows

| Workflow | Trigger | Notes |
|---|---|---|
| `scan.yml` | 30-min market hours (+ weekend crypto cron) | VIVEK scans + bot stocks book + confluence. Injects unused SMTP secrets. Commits whole `public/data`. Weekend cron duplicates `crypto_bot.yml`. |
| `crypto_bot.yml` | hourly 24/7 | crypto scans + crypto bot book. |
| `phasemap.yml` | nightly | PhaseMap + Specs + confluence + schema gate (validates slim latest + sidecar). |
| `lens_backtest.yml` | weekly Sun | PhaseMap/Specs/VIVEK replays; **owns `vivek_backtest.json`**. |
| `vivek_backtest.yml` | monthly 1st | long-only evidence → `vivek_backtest_longonly.json` only. **Never fired on schedule** (cron committed a day late). |
| `stop_watcher.yml` | */5 | cloud stop/target (via tick.js). **Observed firing ~5×/day, not 288.** |
| `close_position.yml` | dispatch | manual close (the injection sink). |
| `kill_switch.yml` `discord_digest.yml` | dispatch / sched | flatten; daily digest. |
| `test.yml` | every push | pytest + JS tests + syntax gate. |

All 6 data-committing workflows copy-paste a ~25-line fetch/reset/rm/checkout/push retry loop that has already drifted between copies.

## tests (pytest + node) — ~290 tests, run on every push

`tests/` (Python): test_vivek (541), test_phase7 (312), test_order_path (252, the Bybit bracket/reconcile/kill path), test_vivek_bot_gates (230), test_vivek_journal (218), test_vivek_run (182), test_risk_manager (184), test_discord (163), test_scalp_journal (158), test_vivek_backtest (132), + circuit_breaker/pre_trade_check/data/sizing/grading/universe/guard/funds/quality.
`test/` (node): risk_manager.test.js (492), unit.test.js (498 — **tests HAND-COPIED mirrors of chart.js/journal.js constants that have already drifted**), vivek_manage.test.js (192).
`phasemap/tests/`: fixtures/units/narration/backtest/output/next_evidence + synth.

**Review the tests too:** do they assert real behavior of the shipped code, or copies that drift? Which money-path branches are uncovered?

---

# PART E — DELIVERABLE FORMAT

Return your review as:

1. **Executive summary** (≤10 lines): the 3–5 things that would most hurt this trader, in plain English.
2. **Findings table**, sorted by severity desc, then confidence. Columns: `#`, `severity (1–5)`, `confidence (High/Med/Inferred)`, `subsystem`, `title`, `file:function`, `failure scenario (concrete inputs→wrong output)`, `fix`.
3. **Cross-subsystem risks**: interactions that aren't visible in any single file (e.g. workflow race + wholesale data commit; open tick auth + KV enumeration; backtest-vs-bot management drift).
4. **Verdict on our audit** (Section 2): which of our top findings you CONFIRM, which you REFUTE (with reasoning), which we MIS-PRIORITIZED.
5. **What you could not assess** and which exact files you'd need to finish.

Be specific, be adversarial, and show the trigger path for every money/security finding. You now have the full brief (Sections 0–3), the high-risk code verbatim (Part C), and a map of everything else (Part D). Begin the review.
