# Build Spec — Multi-Market Trading Scanner + Paper-Trade Journals (Streamlit edition)

**Audience:** Grok, building a parallel implementation on **Streamlit** for side-by-side beta testing against the reference build (static site + Python scanner on GitHub Actions + Cloudflare Pages).

**Goal:** Produce the *same outputs* (same setups, same grades, same paper-trade results) from the *same inputs* so the two builds can be compared. Match the numbers below **exactly** — they are the contract. Where Streamlit differs architecturally (no static JSON + cron), use the guidance in §13.

> Everything here is general-information tooling, not financial advice. No real orders are placed — the journals are a forward test.

---

## 1. What you're building

A Python app that, on a schedule, for each market:

1. Downloads OHLCV price data (Yahoo Finance via `yfinance`).
2. Runs **5 scan engines** over a universe of tickers.
3. Grades each setup **A+ / A / B / C** from a points system.
4. Computes **Entry / Stop / Target / Risk:Reward**.
5. Updates **paper-trade journals** (swing + scalp) — a bias-free forward test.
6. Optionally runs a **backtest** and emails **alerts**.
7. Renders it all in a dense dashboard with charts.

Markets: **ASX**, **NASDAQ**, **Crypto**. Plus a cross-asset **Scalp** (1h intraday) scan.

---

## 2. Tech stack (Streamlit)

| Concern | Reference build | Your Streamlit build |
|---|---|---|
| Compute | `scanner/` Python package | Same Python logic, imported by the app |
| Scheduling | GitHub Actions cron (every 30 min) | `st.cache_data(ttl=1800)` + optional APScheduler / external cron |
| Storage | JSON files in `public/data/` | SQLite (recommended) or JSON on disk |
| UI | Static HTML/JS | Streamlit multipage app + Plotly |
| Charts | lightweight-charts | Plotly candlestick + subplots |
| Secrets | Cloudflare/GH env vars | `st.secrets` |

**Dependencies:** `streamlit pandas numpy yfinance plotly` (+ `apscheduler` if you self-schedule, `streamlit-lightweight-charts` if you prefer TV-style charts).

Keep all the **pure logic** (engines, scoring, fills, metrics) in plain Python modules with **no Streamlit imports**, so it's identical to the reference build and unit-testable. Streamlit is only the presentation + caching layer.

---

## 3. Data layer

### 3.1 Markets

| Market | yf suffix | Currency | Symbol | Timezone | Liquidity min (local) |
|---|---|---|---|---|---|
| asx | `.AX` | AUD | A$ | Australia/Sydney | 100,000 |
| nasdaq | `` (none) | USD | $ | America/New_York | 1,000,000 |
| crypto | `-USD` | USD | $ | UTC | 3,000,000 (volume already USD) |

### 3.2 Download helper (match this exactly)

```python
import yfinance as yf
def download(tickers, period=None, interval="1d", chunk=75, retries=2):
    # daily: period="2y"; scalp scan: period="60d", interval="1h", chunk=30
    # journal 1h walk: period="5d", interval="1h", chunk=30
    period = period or "2y"
    frames = {}
    for start in range(0, len(tickers), chunk):
        batch = tickers[start:start+chunk]
        data = yf.download(batch, period=period, interval=interval,
                           group_by="ticker", auto_adjust=True, threads=True, progress=False)
        for t in batch:
            df = data[t].copy() if isinstance(data.columns, pd.MultiIndex) else data.copy()
            df = df.dropna()
            if len(df): frames[t] = df
    return frames
```

- `auto_adjust=True` (matters — adjusted closes).
- Daily history: **`period="2y"`**, require **`MIN_HISTORY = 160`** bars to evaluate.
- 1h history is capped by Yahoo at ~730 days; scalp scan uses **60d**, journal walk **5d**, backtest up to **720d**.
- Columns used: `Open High Low Close Volume`. Strip timezone (`df.index = df.index.tz_localize(None)`) before rolling ops.

### 3.3 Universes (CSV: `symbol,name,type,sector,yf`)

Approx sizes: **ASX ~94, NASDAQ ~99, crypto ~60, scalp ~51**. The scalp universe is cross-asset (commodities futures + ASX blue chips + NASDAQ mega-caps + a couple of ETFs). Reuse the same CSVs from the reference repo so universes are identical — that's essential for beta parity.

Scalp universe `type` ∈ {`commodity`, `asx`, `nasdaq`}; each row has a `sector`.

---

## 4. Indicators (shared)

- **EMA** `close.ewm(span=n, adjust=False).mean()`
- **SMA** `close.rolling(n).mean()`
- **ATR(n)**: True Range = max(H−L, |H−prevC|, |L−prevC|); ATR = Wilder/rolling mean of TR over n.
- **RSI(n)**, **ADX(n)** standard.
- **SuperTrend(ATR, mult)** — used as the swing trailing stop.
- **Bollinger Bands(20, 2)**, **Keltner Channels(20, 1.5×ATR)** — for the squeeze.

---

## 5. The five scan engines (exact parameters)

> Grade = **sum of points**, checked high→low against cut-offs. `TRADEABLE = {A+, A}`.

### 5.1 Pullbacks (continuation in an existing uptrend) — `<market>.json`

EMA ladder (daily close): **8 · 13 · 21 · 34 · 55 · 89 · 144**

| Signal | Points | Rule |
|---|---|---|
| alignment | 3 | full bullish EMA stack (8>13>21>…>144) |
| pullback | 3 | price within `PULLBACK_TOL=2.5%` of a core EMA (21/34/55) |
| confluence | 3 | ≥`CONFLUENCE_MIN=3` EMAs within `CONFLUENCE_BAND=2%` of price |
| compression | 2 | `(maxEMA−minEMA)/price ≤ COMPRESSION_TOL=6%` |
| weekly | 1 | weekly uptrend: EMA`WEEKLY_FAST=10` > EMA`WEEKLY_SLOW=20` |
| volume | 1 | last vol ≥ `VOLUME_MULT=1.4` × 20-bar avg |
| adx | 1 | `ADX(14) > ADX_TREND_MIN=25` |
| rsi_pullback | 1 | `RSI(21)` in **38–62** |

`SCORE_MAX = 15`. **Cut-offs:** A+ ≥10, A ≥8, B ≥5, C ≥3.
**R:R demotion:** if `DEMOTE_LOW_RR=True`, an A+/A setup with R:R < `MIN_TRADEABLE_RR=1.5` is demoted to B. Flag `low_rr` when R:R < `LOW_RR_THRESHOLD=1.5`.

### 5.2 Reversals (start of a *new* uptrend) — `<market>_reversal.json`

SMAs **9/26/43/200**, RSI 14 (+ its 14 SMA), Vol-20.

| Signal | Points | Rule |
|---|---|---|
| reclaim | 4 | 9 crossed up over 26 within `REV_CROSS_LOOKBACK=15` bars (the trigger) |
| base | 3 | ≥`REV_BASE_OFF_HIGH=20%` below 1-yr high (`lookback 252`); recently below SMA200 (`45`) |
| volume | 3 | 5-day avg vol ≥ `1.4`× Vol-20, or a day ≥ `2.0`× |
| breakout | 2 | close above base high (bars −45..−5) |
| rsi | 2 | RSI turning up through its MA, band **48–72** |

`SCORE_MAX=14`. **Cut-offs:** A+ ≥11, A ≥9, B ≥6, C ≥4. `min_history=230`. Stop = recent swing low (`lookback 12`).

### 5.3 Specs (speculative volume-spike breakouts, cheap small-caps) — `<market>_spec.json`

SMAs 9/26/43/200. **Mandatory gates** (fail any → skip): vol spike ≥`3.0`× Vol-20 within `5` bars; base ≥`40%` below 1-yr high; breakout = close above base high (bars −40..−3). Bonuses: fresh ~3-mo high (`63`), fresh 9/26 cross (`12`), 9-SMA curling up. RSI band **45–85**. Skip if >`60%` extended above 9-SMA. **`SPEC_MAX_PRICE=0.50`** (disabled for crypto). Cut-offs: A+ ≥8, A ≥6, B ≥4, C ≥2 (`score_max 11`). `min_history=230`.

### 5.4 Shorts (bearish pullback in a downtrend) — `<market>_short.json`

**3 hard gates:** price below EMA144 for ≥`15` bars; EMA8 below EMA21 for ≥`10` bars; weak bounce (down-day volume > up-day volume over `8` bars). Mirror of the long pullback logic, inverted. *(Known weak — deferred for refinement.)*

### 5.5 Scalp (1h intraday, cross-asset) — `scalp.json` → **see §6**

---

## 6. Scalp engine (the most developed — match precisely)

**Timeframe:** 1h bars. **Stop:** 1.5×ATR. **Target:** 3×ATR → 2:1 R:R.

### 6.1 Parameters

```
SQ_PERIOD=20  SQ_BB_MULT=2.0  SQ_KC_MULT=1.5  SQ_MOM_PERIOD=12  SQ_FIRE_LOOKBACK=4
PIVOT_WINDOW=3  PIVOT_LOOKBACK=60
SCALP_ATR_PERIOD=14  SCALP_ATR_STOP_MULT=1.5  SCALP_ATR_TARGET_MULT=3.0  SCALP_MIN_BARS=65
```

### 6.2 TTM Squeeze signals

- **BB(20,2):** mid = SMA20; upper/lower = mid ± 2·std(20, ddof=0).
- **KC(20, 1.5×ATR):** mid = SMA20; upper/lower = mid ± 1.5·ATR(20).
- **Squeeze ON** = BB entirely inside KC: `(bb_upper < kc_upper) & (bb_lower > kc_lower)`.
- **Momentum** (the histogram): `val = close − ((max_high(20)+min_low(20))/2 + SMA20)/2`, then **linear-regression value** of `val` over `SQ_MOM_PERIOD=12` (rolling polyfit degree 1, value at last point of each window).
- **Squeeze FIRED** = `(not on_now) AND (on within the previous SQ_FIRE_LOOKBACK=4 bars)`.

### 6.3 `evaluate(df, direction)` → signal dict (or None)

1. Need ≥`SCALP_MIN_BARS=65` bars; strip tz.
2. **Direction gate** (stable): long requires `last_close ≥ SMA20`; short requires `last_close ≤ SMA20`. Else None.
3. `momentum_dir`: mom>0 (long) / mom<0 (short).
4. `momentum_accel`: mom rising (long) / falling (short) vs previous bar.
5. `volume`: last vol ≥ **1.3** × mean(vol[−21:−1]).
6. **Pivots:** find nearest pivot support below / resistance above over last `PIVOT_LOOKBACK=60` bars (`PIVOT_WINDOW=3` each side; broken resistance flips to support and vice-versa). `pivot_ok` long = price ≥ nearest_support×0.98; short = price ≤ nearest_resistance×1.02.

### 6.4 Scoring + grading

| Signal | Points |
|---|---|
| squeeze_fired | 3 |
| squeeze_on | 1 |
| momentum_dir | 2 |
| momentum_accel | 1 |
| pivot_ok | 2 |
| volume | 1 |

`SCORE_MAX=10`. **Cut-offs:** A+ ≥8 **AND `squeeze_fired` must be true** (hard gate), A ≥7, B ≥4, C ≥2.

### 6.5 Levels

```
atr = ATR(14).iloc[-1];  risk = 1.5*atr
long:  stop = entry - risk;  target = entry + 3.0*atr
short: stop = entry + risk;  target = entry - 3.0*atr
rr = |target-entry| / risk   # = 2.0
entry = last close
```

### 6.6 Dedup

After sorting results by (grade rank, −score, −rr), **keep only the highest-scoring direction per symbol** (no GOLD long *and* GOLD short).

---

## 7. Grading + sort

Sort key for every engine's results: `(GRADE_RANK[grade], -score, -rr)` where `GRADE_RANK = {A+:0, A:1, B:2, C:3}`. `TRADEABLE_GRADES = {A+, A}`.

---

## 8. Paper-trade journals (forward test)

Two journals, both opening a paper position for **every new A+/A setup** and walking it forward against fresh prices. **No real orders.**

### 8.1 Swing journal (daily bars) — Longs + Shorts

- Sizing: **$1,000** per trade, **$5** brokerage each way ($10 round-trip).
- Max **10** concurrent longs, **10** shorts.
- Exit: SuperTrend(ATR, 3.0) trailing stop, or fixed target, or stop.
- P&L in **R multiples** *and* dollars. Show **½-Kelly** sizing after ≥20 closed trades.

### 8.2 Scalp journal (1h bars) — **the important one**

- Sizing: **$1,000 margin × 5× leverage = $5,000 notional**. `units = int(5000 / entry)`.
- Brokerage: **$20 each way → $40 round-trip** (CFD style).
- Daily caps: **max 5 trades/day**, **$500 daily loss limit** (no new trades if breached).
- Open only **A+/A**; one position per (symbol, direction).
- **Pessimistic fill model** (§9) — match exactly.
- Store on each position: `session_day`, `corr_group`, `yf_ticker`, `opened_ts`.

---

## 9. Pessimistic fill model (THE most important parity contract)

Both the journal *and* the backtest use the **identical** model. Naive "fill at signal close" overstates results — don't do it.

```
SLIP = 0.0003        # 0.03% one-way slippage
BROK_RT = 40         # $ round-trip
NOTIONAL = 5000

# ENTRY: open of the NEXT 1h bar after the signal, + slippage
raw_open = open[signal_index + 1]
entry = raw_open*(1+SLIP)  if long  else raw_open*(1-SLIP)
risk  = entry - stop       if long  else stop - entry      # must be > 0
units = int(NOTIONAL / entry)

# GAP-THROUGH on the fill bar → immediate stop-out at raw_open
if long  and entry <= stop: close at raw_open, reason="stop-gap"
if short and entry >= stop: close at raw_open, reason="stop-gap"

# WALK forward bar by bar. Check GAP-THROUGH (bar opens past a level) first:
long:
  if open[k] <= stop:   exit raw=open[k], "stop-gap"
  elif open[k] >= target: exit raw=open[k], "target-gap"
  elif low[k] <= stop:   exit raw=stop,   "stop"      # stop checked before target
  elif high[k] >= target: exit raw=target, "target"
short: mirror (open>=stop stop-gap; open<=target target-gap; high>=stop stop; low<=target target)

# EXIT slippage makes the exit worse:
exit_px = raw*(1-SLIP) if long else raw*(1+SLIP)

# P&L:
pnl = units*(exit_px-entry) - BROK_RT   if long
pnl = units*(entry-exit_px) - BROK_RT   if short
R   = (exit_px-entry)/risk  (long)  /  (entry-exit_px)/risk  (short)

# Backtest only: abandon at market (last close) after MAX_HOLD_BARS = 48 bars → reason="timeout"
```

Key subtleties: **entry is next-bar open (never the signal close)**; **gaps fill at the bar open, not the level** (worse on stops, windfall on targets); **stop is checked before target within a bar** (conservative); a `filled` flag persists so re-runs don't re-apply entry slippage.

---

## 10. Risk management (match exactly)

### 10.1 Session-boundary daily reset (not UTC midnight)

Daily trade-count / loss-limit reset at a fixed **08:00 UTC** anchor — the quiet window between NASDAQ close (~21:00 UTC) and ASX open. This avoids resetting **mid-session** during AEDT (Oct–Apr), when the ASX session straddles 00:00 UTC.

```python
def session_day(ts=None):
    t = parse(ts) if ts else utcnow()
    return (t - timedelta(hours=8)).strftime("%Y-%m-%d")
```

Store `session_day` on each position at open; sum today's trades/P&L by it.

### 10.2 Correlation caps (portfolio risk)

Highly-correlated names are **one bet**. Max **2** open positions per correlation group.

```
groups (symbol → bucket; unlisted → "<type>:<sector>"):
  metals:        GOLD SILVER GLD SLV NST
  energy:        OIL BRENT NATGAS WDS STO ORG
  materials_au:  COPPER BHP RIO FMG
  ags:           WHEAT COFFEE
  au_financials: CBA NAB WBC ANZ MQG QBE SUN
  us_tech:       AAPL MSFT NVDA META GOOGL AMZN TSLA AMD AVGO NFLX
                 PLTR CRM ORCL ADBE MU QCOM SPY QQQ
```

When opening: skip if the group already has ≥2 open positions.

---

## 11. Backtest (out-of-sample, no look-ahead)

Replay the scalp engine **bar by bar**, re-evaluating using only data **through** each bar (`df.iloc[:i+1]`), trade every A+/A with the §9 fills, no overlapping positions per direction (resume after the exit bar). Window up to ~12 months (clamp to ~720 days of 1h data).

**Report:**
- **Win rate** = wins / trades.
- **Profit factor** = gross win $ / gross loss $.
- **Expectancy** = mean R and mean $ per trade.
- **Max drawdown** = max(peak − equity) on the cumulative $ curve.
- Avg hold (bars), totals, plus **by grade**, **by direction**, **per symbol**, equity curve.

Run this **separately from the live scan** (it's heavy — weekly is fine). The live forward-test numbers and the backtest must roughly **agree**; if they diverge, the fill model or data is wrong.

---

## 12. Alerts (optional)

Email a digest of **new** A+/A setups since last run. **Dedup by symbol** — keep only the highest-scoring direction per asset so the same name isn't alerted long *and* short. Use `st.secrets` for SMTP creds.

---

## 13. Streamlit-specific implementation

### 13.1 App structure (multipage)

```
app.py                 # Dashboard (market + scan-type tabs)
pages/2_Journal.py     # Overall / Longs / Shorts / Scalp tabs
pages/3_Backtest.py    # backtest metrics + equity curve
pages/4_Feeds.py       # embedded X timelines
core/                  # PURE logic — no streamlit imports
  data.py engines/ scalp.py levels.py journal.py scalp_journal.py backtest.py config.py
```

### 13.2 Caching & scheduling (replaces cron + JSON)

Streamlit has no cron. Use cache TTL so the first visitor each interval refreshes:

```python
@st.cache_data(ttl=1800, show_spinner="Scanning…")   # 30 min, matches reference cadence
def run_all_scans(market): ...

@st.cache_data(ttl=1800)
def get_scalp(): ...
```

For deterministic 30-min refresh independent of traffic, run an **APScheduler** job (or an external cron / GitHub Action) that writes results to the shared store; the app just reads. For beta, `ttl=1800` is enough.

### 13.3 Persistence — DON'T use `st.session_state` for journals

`st.session_state` is per-user-session and dies on rerun/restart. The journal is global, persistent state → use **SQLite** (recommended) or a JSON file on disk:

```python
@st.cache_resource
def db():
    con = sqlite3.connect("journal.db", check_same_thread=False)
    con.execute("CREATE TABLE IF NOT EXISTS scalp_open(...)")
    con.execute("CREATE TABLE IF NOT EXISTS scalp_closed(...)")
    return con
```

Update flow each refresh: open new A+/A (respecting daily caps + correlation caps), walk open positions on fresh 1h data, move closed ones to the closed table. Identical logic to §8–§10.

### 13.4 Charts (Plotly)

Candlestick + indicator overlays + a **momentum-histogram subplot** (the scalp money-shot):

```python
from plotly.subplots import make_subplots
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.03)
fig.add_trace(go.Candlestick(...), row=1, col=1)
# overlays: BB upper/mid/lower, KC upper/lower, EMA9, EMA21 as go.Scatter on row 1
# level lines via fig.add_hline(y=entry/stop/target, annotation_text="TARGET +2.5% (2.0R)")
# momentum histogram on row 2 with LazyBear colours:
#   v>=0 & rising aqua #00e6cc / fading teal #127d70 ; v<0 & falling red #ff3b3b / rising maroon #7d1f1f
fig.add_trace(go.Bar(x=t, y=mom, marker_color=colors), row=2, col=1)
st.plotly_chart(fig, use_container_width=True)
```

Label levels with **% from entry and R** (e.g. `TARGET +2.5% (2.0R)`, `STOP -1.2% (1R)`). Alternatively use the `streamlit-lightweight-charts` component to mirror the reference look.

### 13.5 UI patterns

- Stat cards → `st.metric` in `st.columns`.
- Tables → `st.dataframe` (style by grade/R/$; green/red).
- Market & scan-type selectors → `st.tabs` or `st.radio` in the sidebar.
- Journal tabs → `st.tabs(["Overall","Longs","Shorts","Scalp"])`. **Overall** = all journals combined by $ P&L (one equity curve, combined win rate / profit factor / expectancy).
- Feeds page → `st.components.v1.html` embedding the official X timeline widget (free, no API key) for the watch-list accounts; AI daily summaries would need the paid X API (Basic ≈ $100/mo) so leave that out for beta.
- "Last scanned" timestamp shown from the cache's generation time.

---

## 14. Parity checklist (for beta comparison)

Run both builds on the **same universe CSVs** at the **same time** and confirm:

- [ ] Same tickers download / survive `MIN_HISTORY` filters.
- [ ] Identical grade for each symbol per engine (same points → same A+/A/B/C).
- [ ] Same scalp results after dedup (same symbol + direction + score).
- [ ] Same Entry/Stop/Target/RR per setup (within float rounding).
- [ ] Scalp journal opens the **same** positions (respecting daily cap = 5, loss limit = $500, correlation cap = 2/group, session-day = 08:00 UTC anchor).
- [ ] Pessimistic fills identical: next-bar-open entry, gap-through handling, $40 RT + 0.03% slippage, stop-before-target.
- [ ] Backtest metrics (win rate, profit factor, max DD, expectancy) match within sampling noise.
- [ ] Alert dedup: one direction per symbol.

If any box fails, the divergence is a bug in one build — that's exactly what the beta is for.

---

## 15. Exact constants (copy verbatim)

```python
# Pullback
EMA_PERIODS=[8,13,21,34,55,89,144]; SCORE_MAX=15
GRADE_CUTOFFS=[("A+",10),("A",8),("B",5),("C",3)]; TRADEABLE={"A+","A"}
PULLBACK_EMAS=[21,34,55]; PULLBACK_TOL=0.025; COMPRESSION_TOL=0.06
CONFLUENCE_BAND=0.02; CONFLUENCE_MIN=3; VOLUME_MULT=1.4; VOLUME_LOOKBACK=20
ADX_PERIOD=14; ADX_TREND_MIN=25; RSI_PERIOD=21; RSI_BAND=(38,62)
SWING_LOOKBACK=20; STOP_BUFFER=0.01; RESIST_LOOKBACK=120; PIVOT_WINDOW=3
ATR_PERIOD=14; SUPERTREND_MULT=3.0; WEEKLY_FAST=10; WEEKLY_SLOW=20
DEMOTE_LOW_RR=True; MIN_TRADEABLE_RR=1.5; LOW_RR_THRESHOLD=1.5
POSITION_SIZE_USD=1000; BROKERAGE_EACH_WAY=5; MAX_POSITIONS_LONG=10; MAX_POSITIONS_SHORT=10

# Reversal
REV_SMAS=[9,26,43,200]; REV_POINTS={reclaim:4,base:3,volume:3,breakout:2,rsi:2}
REV_CUTOFFS=[("A+",11),("A",9),("B",6),("C",4)]; REV_CROSS_LOOKBACK=15
REV_BASE_OFF_HIGH=0.20; REV_VOL_MULT=1.4; REV_VOL_SPIKE=2.0; REV_RSI_BAND=(48,72); REV_MIN_HISTORY=230

# Spec
SPEC_VOL_SPIKE=3.0; SPEC_VOL_RECENT=5; SPEC_OFF_HIGH=0.40; SPEC_RSI_BAND=(45,85)
SPEC_MAX_EXT=0.60; SPEC_MAX_PRICE=0.50; SPEC_CUTOFFS=[("A+",8),("A",6),("B",4),("C",2)]

# Short gates
SHORT_DOWNTREND_BARS=15; SHORT_EMA_ALIGN_BARS=10; SHORT_BOUNCE_VOL_WINDOW=8

# Scalp engine
SQ_PERIOD=20; SQ_BB_MULT=2.0; SQ_KC_MULT=1.5; SQ_MOM_PERIOD=12; SQ_FIRE_LOOKBACK=4
PIVOT_WINDOW=3; PIVOT_LOOKBACK=60; SCALP_ATR_PERIOD=14
SCALP_ATR_STOP_MULT=1.5; SCALP_ATR_TARGET_MULT=3.0; SCALP_MIN_BARS=65
SCALP_VOLUME_MULT=1.3
SCALP_POINTS={squeeze_fired:3,squeeze_on:1,momentum_dir:2,momentum_accel:1,pivot_ok:2,volume:1}
SCALP_SCORE_MAX=10; SCALP_CUTOFFS=[("A+",8),("A",7),("B",4),("C",2)]   # A+ also requires squeeze_fired

# Scalp journal / fills / risk
SCALP_POSITION_SIZE=1000; SCALP_LEVERAGE=5            # NOTIONAL=5000
SCALP_BROKERAGE_EACH_WAY=20                            # BROK_RT=40
SCALP_MAX_TRADES_PER_DAY=5; SCALP_MAX_DAILY_LOSS=500
SCALP_FILL_SLIPPAGE_PCT=0.0003                         # 0.03% one-way
SCALP_DAY_ANCHOR_UTC=8; SCALP_MAX_PER_GROUP=2
MAX_HOLD_BARS=48                                       # backtest timeout

# Data
DAILY_PERIOD="2y"; MIN_HISTORY=160
SCALP_SCAN="60d"/1h; SCALP_WALK="5d"/1h; BACKTEST<=720d/1h
```

---

## 16. Build order (suggested)

1. `core/data.py` + universes → confirm downloads match.
2. `core/scalp.py` (engine) → confirm grades match reference `scalp.json`.
3. Pessimistic fill model + `core/scalp_journal.py` → confirm journal opens/closes match.
4. Session reset + correlation caps.
5. `core/backtest.py` → confirm metrics.
6. Streamlit Dashboard + Journal pages + Plotly charts.
7. Swing engines (pullback/reversal/spec/short) for full coverage.
8. Alerts + Feeds.

Start with the **scalp path end-to-end** — it's the most valuable and the strictest parity test.
