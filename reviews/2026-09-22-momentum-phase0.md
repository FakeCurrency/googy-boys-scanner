# VIVEK MOMENTUM — Phase 0 inventory

**Written:** 2026-09-22 · **Branch:** `vivek-momentum-v1` · **Status:** read-only inventory, no engine code yet

Everything in this note was **verified by running or reading it on this tree**. Where the build
brief, `HANDOFF_2026-09-22.md` Part 17, and the scanner spec disagree, the disagreement is
recorded with a ruling rather than silently resolved — that is the whole point of the phase.

---

## 1. The SHA, and a correction about it

**`origin/main` = `2f52df7f22614ead9e526d6864d05d835aaedd8d`** ("data: scan 2026-09-22 02:54 UTC").

The first read of `origin/main` in this session returned `14f40817454b723c9f11bbcdbee6c5e4a264bbfb`
and that was **wrong** — an artefact of a shallow clone whose remote ref was 3 commits stale.
`git rev-parse --is-shallow-repository` was `true` with 50 commits. After `git fetch --unshallow`
the tree has 3,149 commits and `origin/main` resolves to `2f52df7`. `14f4081` is an ancestor.

Two consequences worth stating, because both were briefly believed otherwise:

- `claude/epic-keller-pr4x0x` is **not ahead of main** — it points at the same commit, `2f52df7`.
- `HANDOFF_2026-09-22.md` **is on main** (commits `0ecac89` + `62d8f15`), so branching off main
  keeps the governing playbook in the tree.

> **Habit worth keeping:** in a shallow clone, a remote-tracking ref is a snapshot from clone time,
> not a live answer. Unshallow before reasoning about branch topology.

### Branch-name conflict, unresolved by design

The build brief says to branch off current `origin/main` as **`vivek-momentum-v1`**; this session's
harness instructions designate **`claude/epic-keller-pr4x0x`** as the push target and say never to
push elsewhere without explicit permission. Nothing is pushed in Phases 0–7, so the conflict is not
yet live. I have developed on `vivek-momentum-v1` (the brief's explicit instruction, branched off
current `origin/main` so the eventual diff carries only momentum files). **At "upload it" the owner
picks the push target** — this is flagged rather than guessed.

---

## 2. THE BLOCKING FINDING: the spec was not on this tree, and its path in the brief is wrong

The brief tells me to port `scanner-spec/reference/vivek50_screen.py` and cites commit `80d4d44`.
Three corrections:

| Brief says | Reality |
|---|---|
| `scanner-spec/` | **`tradingview/scanner-spec/`** — the brief's path does not and never did exist |
| implies it is on this tree | **absent from `origin/main` entirely**; `tradingview/` is not even a top-level entry on main |
| "if only on 80d4d44, cherry-pick" | `80d4d44` was **unreachable** until the clone was unshallowed; it lives only on `origin/claude/optimistic-darwin-r6s49g` |

Note the brief also says "Do NOT reuse: … optimistic-darwin" as a branch name. That is the branch
the spec is stranded on. The instruction is about not *reusing the branch*, not about avoiding its
content.

### What I landed, and why it is a subtree and not a cherry-pick

Commit **`a1bdc19f`** — `tradingview: recover the scanner specification pack (subtree of 80d4d44)`.

`80d4d44` has three hunks. One adds `tradingview/scanner-spec/**` (landed). The other two *modify*
`tradingview/Final_Top_Script.pine` and `tradingview/README.md` — and the whole `tradingview/`
directory is absent from main, so **those hunks have no base to apply to**; a plain `git cherry-pick`
would conflict. They are stale-claim corrections to the Pine script (the auto stop cap is Auto-mode
only; the target floor is 5% of entry, not zero; the price-pane RSI columns fire at 75/25, not
70/30). They are recorded in the commit message so the correction is not lost, and can be landed
separately if the owner wants the Pine sources on main.

Authorship is credited to Vivek, since it is his commit.

### It is verified, and it is wired into nothing

- **`reference/vivek50_selftest.py` was EXECUTED on this tree: `28/28 tests passed.`** That is the
  Phase 2 foundation proven before a line of engine code, not assumed from a commit message.
  (It needed dependencies — see §8.)
- `pytest.ini` sets `testpaths = tests phasemap/tests` and `python_files = test_*.py`, so nothing
  under `tradingview/` is ever collected, and `vivek50_selftest.py` would not match the pattern
  even if it were. **Proven two ways:** zero `tradingview` paths appear in a full
  `pytest --collect-only`, and `pytest --collect-only tradingview/` — pointing pytest *straight at
  it* — collects nothing at all. That is a stronger result than a before/after count, which could
  have coincided.
- No module under `scanner/` or `phasemap/` imports it; it is outside `test.yml`'s path filter.

### The brief's file list for the spec pack was incomplete

It names four files. There are **eight**: `README.md`, `VIVEK_5.0_SCANNER_SPEC.md` (10,885 lines),
`VIVEK_5.0_SCANNER_SPEC_CORE.md` (2,534), and `reference/{vivek50_screen.py (1,215),
vivek50_selftest.py (851), vivek50_scan_cli.py (350), baserate.py (123), worked_example.py (91)}`.
`baserate.py` is the 1.95M-symbol-day base-rate study behind the score-distribution claim, and
`worked_example.py` is the bar-by-bar divergence-timing walkthrough. Both are load-bearing evidence
and neither was mentioned.

---

## 3. Where the brief is factually wrong about this repo

Each of these was read, not inferred. None is fatal; all would have produced a wrong build.

### 3.1 The index nav pill is labelled `SCAN`, not `VIVEK 5.0`

`public/js/nav.js:26` — `{ href: "index.html", label: "SCAN", tab: "📡", key: "index" }`.
A nav test written against the brief's `"VIVEK 5.0"` would fail on a true tree.

### 3.2 The mode enum is `1`/`2`, and "mode B" is a UNION — there is no "B only"

The brief describes "MODE A (divergence only)", implies a B mode, and calls mode C "both,
directions agree". The spec §5.4 is:

```
passes_A = rule_A_fired
passes_B = rule_A_fired OR rule_B_fired      <-- a UNION, not "B alone"
passes_C = rule_A_fired AND rule_B_fired AND directions_agree
```

And `reference/vivek50_screen.py:157` implements only `mode: int = 2  # 1 = RULE A only, 2 = RULE A or RULE B`.
**Mode C is specified but NOT implemented in the reference.** So:

- brief "MODE A" ≡ spec A ≡ reference `mode=1`
- brief "MODE B" ≡ spec B ≡ reference `mode=2` ≡ **A or B**, not B alone
- brief "MODE C" ≡ spec C ≡ **no reference implementation exists**

**Ruling:** implement A / B / C faithfully to spec §5.4 with **default A**, and pin the default in a
test. Mode C is *specified*, so implementing it is not "inventing a new filter" (which the brief
forbids); what the brief reserves to the owner is whether to **default** to it. The reference's
`mode=2` default is deliberately NOT carried over.

### 3.3 Rule B has THREE optional score terms, not two

The brief says "scored 1–3 (MACD sign, close vs 200)". `vivek50_screen.py:779-784`:

```
bullScore = 1 + (useMacd and macdHist > 0 ? 1 : 0)
              + (useSlow and close > maSlow ? 1 : 0)
              + (useRsi  and rsiV > 50 ? 1 : 0)
```

`use_rsi` defaults **False** (`:132`), which is why the observed max is 3 — `max_score` is derived as
`1 + use_macd + use_slow + use_rsi` (`:211`). The brief's two terms are right *for the shipped
defaults* but the third exists and must be published as a term, not dropped.

**Also two easily-conflated constants:** `min_score = 1` (`:133`, Pine's *display* threshold) and
`min_signal_score = 2` (`:160`, Rule B's *gate*). They are different numbers doing different jobs.

### 3.4 `scanner/indicators.py` exists, and the brief's claims about it need splitting

The brief says repo pivot helpers are the wrong tool and there is no MACD helper. **Both verified** —
but there is a third fact it misses. `scanner/indicators.py` ships
`ema/sma/rsi/atr/supertrend/pivot_highs/pivot_lows`, and spec §7.4 rules on it explicitly:

- `pivot_highs(df, window=3)` / `pivot_lows(df, window=3)` take a **DataFrame of price columns** —
  unusable for a pivot on an *RSI series*. Brief correct.
- **No MACD anywhere in `scanner/`** (`grep -rn macd scanner/ -i` → zero hits). Brief correct.
- Its `rsi()` and `atr()` are "fine here" per §7.4, but its **`ema()` is NOT safe for the 200** —
  see §4.1. The brief does not mention this and it is the sharpest trap in the build.

### 3.5 Schema field naming is nested, not flat

The brief requires `rule_a_bars_ago` and `rule_a_pivot_bars_ago`. Spec §5.8 publishes
`rule_a: {bars_ago, pivot_bars_ago, …}` nested, with `rule_b: {}`, `context: {}`, `flags: []`,
`params: {}`, `summary: {}` and a first-class `errors: []`.

**Ruling:** the CORE spec wins on schema shape (the brief's own precedence rule says so). Both
required *facts* are published; the brief's flat names are prose for the same two numbers. The
schema test will assert the nested paths.

### 3.6 The `?v=`/`version.json` mechanism is not what the brief describes

The brief says "tests/test_version_stamp.py will fail if you bump nav.js ?v= on HTML pages without
updating public/version.json". True, but the mechanism is broader and worth stating exactly — see §5.

---

## 4. The algorithm, as the spec actually defines it

Read first-hand from `VIVEK_5.0_SCANNER_SPEC_CORE.md`. These are the facts that must not be
re-derived.

### 4.1 Pine-seeded EMA — measured, and it only matters for the 200 (§7.4)

Pine's `ta.ema` and `ta.rma` **seed with the SMA of the first `length` values and return `na`
before that**. `pandas.ewm(adjust=False)` seeds with the *first value* and emits from bar 0. The
seed error decays as `(1-alpha)^n`, so how much survives is entirely a function of alpha:

| Series | alpha | Seed error left at 500 bars | Verdict |
|---|---|---|---|
| RSI 14 (`rma`) | 1/14 | ~1e-17 | irrelevant |
| ATR 14 | 1/14 | ~1e-17 | irrelevant |
| EMA 20 | 2/21 | ~1e-22 | irrelevant |
| EMA 50 | 2/51 | ~3e-9 | irrelevant |
| **EMA 200** | **2/201** | **~0.67%** | **MATTERS — 0.247 price units adrift at bar 600** |

0.247 units is enough to flip `close > slow`, which is one of Rule B's scoring terms. A name near
its 200-EMA scores 3 under one convention and 2 under the other — a visible disagreement with the
owner's chart, on exactly the boundary the screen cares about.

**Ruling:** the momentum package implements its own Pine-faithful `ema`/`rma`/`rsi`/`atr`/`macd`.
§7.4 would permit reusing `indicators.py` for RSI and ATR, but self-contained maths is chosen for
two reasons: Pine parity end-to-end (which is what the 28 reference assertions actually test), and
removability — `scanner/momentum/` then imports no repo indicator at all.

Two further §7.4 facts: **750 daily bars is the recommendation** (at 250 bars an EMA200 still carries
~60% of its seed error under either convention), and a name with fewer than `slow_len` bars has no
200-EMA, so the term contributes 0 and **the score is capped at 2**. The spec calls that flag
`slow_ready` / `short_history`; the brief calls it `sma_or_ema_proxy`. Spec naming wins, brief
concept satisfied.

### 4.2 Strict pivots, and the tie question that is genuinely open (§7.5)

Two separate issues, and the spec is careful to mark one settled and one not.

**Settled — a flat region must not produce pivots.** The naive
`series == series.rolling(w, center=True).min()` makes *every* bar of a constant window both a max
and a min, cascading nonsense divergences. Halted ASX small caps, delisted-but-quoted names and
stablecoins all produce exactly this. Guard twice: compare the centre bar against the window **with
the centre removed** (or write the explicit loop), and reject frames whose last 20 bars have zero
price range. The reference has a test asserting **zero** pivots on a perfectly flat 300-bar series.

**NOT settled — strict vs non-strict at a tie.** Whether Pine's `ta.pivotlow` requires strictly
lower or `<=` is *not documented by TradingView* and nobody involved had a chart to settle it. The
disagreement was measured, not assumed: over ~3,380 divergences from 300 tick-rounded random walks
the conventions differ on **27 (0.8%)**, and **not in one direction** — 10 fire only under strict,
17 only under non-strict, because an extra intervening pivot re-bases "the previous pivot" and can
push a valid divergence outside the 6–61 bar window.

**Ruling:** config flag, **default strict** (the only convention that cannot fire on a flat series),
exactly as the reference ships (`pivot_strict_left/right = True`). The open question is recorded
here and in the config comment so it is not re-litigated. It is a five-minute empirical check
against a real chart and it belongs to the owner.

### 4.3 The 5-bar detection lag is inherent, and both numbers must ship (§5.3B)

Rule B has **zero** lag: a cross on bar `i` is knowable at the close of bar `i`. Rule A has a
**5-bar** lag: a divergence confirmed on bar `i` describes a pivot at bar `i-5`, and the TradingView
label is drawn at `i-5`. So if both rules report `bars_ago = 1` the underlying market events are
**six bars apart in age**.

`pivot_bars_ago = bars_ago + 5` always. There is no way to remove the lag — you cannot know a bar
was a local low until you have seen the bars after it — and **any implementation reporting a
divergence sooner than 5 bars after the pivot has a look-ahead bug.** The spec recommends *equal*
freshness windows plus explicit reporting of both numbers, so the asymmetry is visible rather than
silently compensated for.

### 4.4 Freshness window (§5.3)

`div_fresh_bars` / `signal_fresh_bars`. Spec's table says default 3 but its recommendation says
**"start with both at 1 for a week"**, and the reference already ships `1`. The brief says 1.
**No conflict — v1 is 1.** The unit is *bars*, deliberately: 3 bars is 3 sessions on ASX/NASDAQ and
3 calendar days on crypto, and that asymmetry is correct because the indicator's unit is bars.

### 4.4B Cadence — the brief's "is the market open" gate is the WRONG gate here (§5.11)

The brief says: *"cron after each equity close (same timezone-gate style as other jobs: cron is a
superset, job decides if market is open)"*. Spec §5.11 says the opposite about the second half, and
it is right:

> **"Do not schedule a market-hours cron for a daily screener: a forming bar's RSI and EMA move all
> session, so an intraday run produces a signal that may not exist at the close."**

For this lens the market must be **CLOSED**, so gating on "is the market open" inverts the
requirement. The spec's schedule is chosen to be post-close **in both halves of the DST year**:

| Market | Run at | Why |
|---|---|---|
| ASX | **06:30 UTC** | after the 16:00 Sydney close under AEST (06:00 UTC) *and* AEDT (05:00 UTC) |
| NASDAQ | **21:30 UTC** | after the 16:00 New York close under EST *and* EDT |
| crypto | **00:30 UTC** | just after the UTC day boundary that defines the daily bar |

**Ruling for Phase 4:** those fixed UTC times, weekdays-only for the two equity markets, and the
in-job check is on the **DATA, not the clock** — `MAX_DATA_AGE_DAYS = 3` measured in the market's own
calendar (§5.6), which is the honest question ("is the last bar the latest close?") rather than a
guess at the trading calendar. The spec's DST warning still applies and is respected by choosing
times that clear the close in both regimes rather than hard-coding an offset.

This also matches the nearest in-repo analogue rather than the busiest one. **`phasemap.yml` — the
other nightly EOD lens — has NO tz gate at all**: one cron (`30 8 * * *`), with its header stating
the AEDT hour-shift is "fine — all three markets' sessions are complete either way".
`MARKET_SCAN_WINDOWS` exists for `scan.yml`, which fires 7×/day *inside* market hours, and it covers
only `asx` and `nasdaq` (there is no crypto entry). Momentum should copy phasemap, not scan.

The `phasemap.yml` shape to pattern-copy: `permissions: {contents: write}` ·
`concurrency: {group: phasemap, cancel-in-progress: false}` · `timeout-minutes: 120` ·
`workflow_dispatch` with `market` (choice) + `args` inputs · steps `actions/checkout@v4`,
`actions/setup-python@v5` (python 3.12, `cache: pip`), `pip install -r requirements.txt`.
`WATCHDOG_RUNS["phasemap.yml"]` is `{max_age_h: 26.0, severity: "WARNING"}` — the template if the
owner wants a momentum entry (§7.2).

### 4.5 Quality gates (§5.6) — and the one that creates a coupling decision

| Gate | Default |
|---|---|
| `MIN_PRICE` | ASX A$0.02 · NASDAQ US$1.00 · crypto none |
| `MIN_DOLLAR_ADV` | ASX A$250k · NASDAQ US$1M · crypto US$5M (20-day mean of `close*volume`) |
| `MAX_DATA_AGE_DAYS` | 3, **measured in the market's own calendar**, not the runner's clock |
| `MIN_BARS` | 250 warn · 60 hard reject |
| Volume sanity | reject if the last 5 bars are all `volume == 0` |
| Non-operating listings | exclude ASX LICs/ETFs/trusts, NASDAQ preferred/warrants/rights/notes |

**The coupling decision.** §5.6 says of the last row: *"The owner's existing scanner already solves
this: see `scan.py::_product_tag` and `config.PRODUCT_NAME_PATTERNS`. Reuse it, do not rewrite it."*
But `scanner/scan.py` is on the brief's **absolute kill list**, and `_product_tag` is private.

**Ruling:** import the *patterns* from `scanner/config.py` (a pure-constants module every lens
already imports) and implement the word-boundary matcher inside `scanner/momentum/`. This reuses the
data §5.6 points at without importing the core lens, and it deliberately does **not** delegate to
the bot's matcher — per CLAUDE.md, the bot's is *substring* (`"ETF" in "NETFLIX"` is True) and the
correct discipline is the front end's `\b` matching. Reading a constant from `config.py` is not
"touching" `scan.py`, and removing `scanner/momentum/` leaves `config.py` untouched.

### 4.6 Ranking (§5.7) — deterministic, six levels

`confluence (A+B agreeing) → Rule A present → smaller bars_ago → higher |score| → higher dollar ADV
→ symbol alphabetically`. The final tie-break exists so a re-run on the same data reproduces the
order; without it, diffing yesterday's list against today's is impossible. Matches the brief's
"ranking puts Rule A first".

### 4.7 Direction and bias (§5.5) — do not collapse `conflict`

`rule_a_dir` / `rule_b_dir` ∈ {bull, bear, **both**, none} (`both` when one bullish and one bearish
divergence confirmed inside the same window). `bias` ∈ {long, short, **conflict**, none}.
**`conflict` must not be collapsed into a direction by a priority rule** — surfacing the
disagreement is the entire point of a human-review shortlist. In modes A and B a conflict is
*flagged, never dropped*.

### 4.8 Never fill indicator NaNs (§7.6)

`crossover` requires `a[i] > b[i] and a[i-1] <= b[i-1]`; with NaN every comparison is false in both
Pine and pandas, so no cross fires during warm-up — which is correct. The trap is a **manufactured
cross at the first non-NaN bar** if you `fillna(0)` or `dropna()` mid-stream: the 200-EMA suddenly
appearing looks like a cross. Let the NaNs propagate and let the freshness window ignore them.

### 4.9 Base rate: "score >= 2" is almost a no-op

Over 1.95M simulated symbol-days, **score 1 is 2% of crosses** (2 is 37%, 3 is 61%). The scoring
terms are correlated with the cross by construction, so **raising the threshold cannot make the rule
selective.** The brief's "do NOT tighten B by raising the threshold in v1" is therefore not a
preference, it is the measured conclusion.

---

## 4B. The 28 assertions to port in Phase 2 — enumerated from the file, not the commit message

`reference/vivek50_selftest.py` has exactly **28 `test_*` functions**, which is where the commit
message's "28 assertions" comes from. The list, so Phase 2 ports by name rather than by memory:

**Pine primitive parity (7)** — `warmup_lengths_match_pine` · `rma_is_wilder_not_an_ema` ·
`rsi_degenerate_cases` · `crossover_is_nan_safe_and_uses_the_previous_bar` ·
`pivot_is_confirmed_right_bars_late` · `the_barssince_off_by_one_sets_a_6_to_61_bar_window` ·
`valuewhen_needs_two_occurrences`

**Rule A (2)** — `a_bullish_divergence_fires_five_bars_after_the_pivot` ·
`b_bearish_divergence_fires_five_bars_after_the_pivot`

**Rule B (3)** — `c_cross_with_macd_up_and_price_above_the_200_scores_three` ·
`d_cross_with_macd_down_and_price_below_the_200_scores_one` ·
`the_score_is_arithmetic_not_a_lookup`

**Degenerate data (5)** — `e_a_flat_series_produces_nothing_and_does_not_crash` ·
`gaps_and_nans_do_not_raise` · `g_a_frame_shorter_than_the_slow_ma_is_sensible_not_fatal` ·
`h_a_single_bar_spike_does_not_leak_or_crash` ·
`h_interior_nan_rows_are_dropped_and_do_not_poison_the_averages`

**Causality (2)** — `f_no_look_ahead_anywhere` (truncate at every bar, re-derive, compare) and
`h_the_lookahead_proof_catches_a_planted_lookahead`. **The second one is the important one**: it
guards the gate, proving the causality proof actually fails when a look-ahead is deliberately
planted. Without it, a proof that silently checks nothing passes forever. Port both.

**Modes / freshness (3)** — `mode_1_is_divergence_only` ·
`h_mode_1_does_not_let_rule_b_colour_the_direction` · `freshness_windows_are_in_bars`

**Frame hygiene — the 4 adversarial findings (6)** —
`h_equal_consecutive_lows_make_no_pivot_under_the_strict_rule` ·
**`h_a_descending_frame_is_REFUSED_not_screened`** ·
`h_a_duplicated_or_gapped_index_is_positional_and_harmless` ·
`h_a_descending_then_flat_rsi_is_zero_not_undefined` ·
`h_a_mistyped_source_is_refused_instead_of_silently_meaning_close` ·
`h_matches_a_naive_bar_by_bar_pine_reading`

**One ruling falls out of that list.** The brief says a reverse-chronological frame must be
"REJECTED **or** auto-sorted, never silently screened". The reference **REFUSES** it — the test name
says so in capitals, and this was the worst of the four defects the adversarial pass found (a
descending frame was screened silently and returned a complete, plausible, *wrong* answer).
**Phase 2 will refuse, not auto-sort**, matching the reference: auto-sorting hides the fact that the
caller handed over a frame in the wrong order, and the next caller with a genuinely corrupt frame
gets silence instead of an error. The brief's separate instruction to "sort frames oldest→newest"
applies to *our own* loading path, where we control the order — not to laundering a bad input.

## 5. The live CI and front-end contracts, verified

### 5.1 Nav — the live arrays

`public/js/nav.js:25-51`. PRIMARY (6), in order:

| key | href | label | tab |
|---|---|---|---|
| index | index.html | **SCAN** | 📡 |
| recommendations | recommendations.html | RECS | 🧭 |
| phasemap | phasemap.html | PHASEMAP | 🗺️ |
| specs | specs.html | SPECS ⚡ | ⚡ |
| alerts | alerts.html | ALERTS | 🔔 |
| journal | journal.html | JOURNAL | 📒 |

`TABS = PRIMARY.filter(x => x.key !== "alerts")` → **5**.
`MORE` (3): sectors/NEWS, system/SYSTEM, about/HOW IT WORKS.
`SHEET = [...PRIMARY.filter(x => x.key === "alerts"), ...MORE]` → 4.

`pageKey()` lowercases the filename, strips `.html`, special-cases only a `phasemap` prefix — so
`momentum.html` → `"momentum"` with **no change needed**.

After inserting momentum after specs: PRIMARY 7, TABS must filter **both** alerts and momentum to
stay at 5, SHEET becomes 5 (momentum precedes alerts, following PRIMARY order).

**Command palette needs no new entry.** `nav.js:350` builds it as
`const base = [...PRIMARY, ...MORE].map(...)` — derived, not hardcoded, so inserting into PRIMARY
gives the palette command for free. It indexes nav items only, so nothing starts fetching a new
payload on page load. The brief's "add one go-to command if the page list is hardcoded there" is
conditional and the condition is false.

### 5.2 The version stamp — the gate most likely to fail the push

`tests/test_version_stamp.py`. The digest is:

```python
fingerprint() = sha1( "\n".join(sorted(unique refs)) + "\nsw:" + CACHE )[:8]
#  refs  = every (href|src)="…?v=N" across sorted(public/*.html)   [deduped, sorted]
#  CACHE = the `const CACHE = "…"` literal in public/sw.js
```

**Reproduced exactly on this tree: 28 refs, `sw:vivek5-v8`, fingerprint `69e01b09`** — which matches
the shipped `public/version.json` (`2026.09.20-69e01b09`). So the gate is currently green and I can
replay it rather than guess, exactly as the brief requires:

```bash
.venv/bin/python -c "
import importlib.util
s=importlib.util.spec_from_file_location('vs','tests/test_version_stamp.py')
m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
print(m.fingerprint())"
```

Adding `momentum.html` with new `?v=` refs (`css/momentum.css`, `js/momentum.js`) **and** bumping
`js/nav.js?v=` across every referencing page both move the digest. `version.json` must then read
`2026.09.22-<new digest>`. There is deliberately **no generator script** — the failure message
prints the value to write.

Also pinned: ≥20 refs must be found (a regex matching nothing would freeze the digest and make every
future bump invisible — green forever, checking nothing).

### 5.3 `sw.js` needs NO change — verified

`sw.js` precaches only `index.html` and `offline.html`, fetched dynamically at install. **There is
no page list to join.** So adding a page requires no `sw.js` edit and no `CACHE` bump — the CACHE
name is only bumped when the *shell* changes. (Current: `vivek5-v8`.) This matters because bumping
CACHE would move the version fingerprint for no reason.

### 5.4 JS suite registration — 22 suites, all 22 registered

`test.yml` has 27 `node test/…` lines: 22 unit suites + 5 e2e. `ls test/*.test.js` → 22. So the tree
is currently consistent, and
`tests/test_screenshot_determinism.py::test_every_javascript_suite_has_a_step_in_the_workflow`
**will fail the push** if `test/momentum.test.js` lands without its own step.

### 5.5 e2e — the new PAGE is harmless, but the NAV EDIT is photographed

I first concluded "no baseline re-cut needed". That was **half right, and worth correcting in place**,
because the two halves of this change have different blast radii.

| Gate | Page scope | Adding `momentum.html` | Editing `nav.js` |
|---|---|---|---|
| `lighthouse.e2e.js` | `index.html?lite=1` only | none | fixture-pinned; reports, never gates |
| `screenshot-diff.e2e.js` | 4 `VIEWS`: index/journal × 1280 + 390 | none | **the two 1280 views photograph `.nav-pills` — drift is expected** |
| `screenshots.e2e.js` | 6 `PAGES` × [360, 390, 430] | none unless added | none — `.nav-pills` is `display:none` ≤680px |
| `smoke.e2e.js` | specific visits + a 5-page 320px overflow loop | none unless added | pills hidden at 320px |

So: **the new page is invisible to every e2e gate, but a 7th desktop pill is not.** The budget is 2%
and the cache key is `screenshot-baselines-v22-…` (`test.yml:388`).

**Ruling: measure the drift, do not pre-emptively bump the key.** A pre-emptive bump discards the
only evidence of how much the pill actually moved — the exact mistake this repo already paid for
nine times (CLAUDE.md's screenshot-gate section, v1→v10). On the nine `deck-top` pages the strip is
`flex: 1 1 0` with `overflow-x: auto`, so the 7th pill may simply scroll out of view at 1280 rather
than reflow anything. That is a measurement to take in Phase 6, not a prediction to make now.

*Unverified and worth a look in Phase 6:* `about.html`, `recommendations.html` and `system.html` use
a bare `<header class="topbar">` with no `deck-top`, so their `.nav-pills` is `inline-flex` with no
overflow scroll. A 7th pill could push those three headers past the viewport somewhere around
681–1000px — and **nothing in CI would catch it**, because every screenshot/overflow gate runs at
320/360/390/430 where the pill row is hidden.

### 5.6 `test/cache.test.js` — a gate the brief never mentions, and it auto-covers the new page

`test/cache.test.js:212` does `fs.readdirSync(dir).filter(f => f.endsWith(".html"))` — it
**auto-discovers every `public/*.html`**, so `momentum.html` is covered the moment it exists, with no
registration. Three assertions bite:

1. `:222` **"no asset is requested at two different `?v=` across pages"** — bumping `js/nav.js?v=` is
   therefore **all-or-nothing across all 12 referencing pages plus momentum.html**. One page left
   behind fails CI. The comment at `:196` records the live incident: `index.html` asked for
   `js/horizon.js?v=6` while `sectors.html` still asked `?v=5`, and `public/_headers` puts `/js/*` on
   `max-age=86400`, so one page was pinning a 24-hour-stale body.
2. `:239` "every versioned asset reference points at a file that exists" — `momentum.html` may not
   link `css/momentum.css?v=1` before that file exists.
3. `:252` a floor on how many versioned assets are found, so the regex cannot silently match nothing.

**Current versions** (from `index.html`): `js/nav.js?v=24` · `css/styles.css?v=115` ·
`css/fonts.css?v=2` · `css/status.css?v=1`.

### 5.7 TABS = 5 is a **CSS** constraint, and the filters ignore insert position

Two facts that together are the likeliest way to break the mobile bar:

- `public/css/styles.css:1533` — `.site-tabs { display: grid; grid-template-columns: repeat(6, 1fr); }`
  inside `@media (max-width: 680px)`. The grid is **saturated at exactly 6** = 5 tabs + the MORE
  button. Nothing in `nav.js` states or checks the 5; **the enforcer is the grid.**
- `TABS` and `SHEET` both key on the **literal string `"alerts"`**, so **insert position is
  irrelevant to both**. Inserting a 7th PRIMARY entry without widening *both* predicates yields
  `TABS.length === 6` and a SHEET with no momentum row.

**Ruling — derive both from one set**, so a key can never fall out of TABS *and* SHEET and become
unreachable on a phone (the pill row is `display:none` ≤680px, so a key in neither is a shipped page
with no mobile entry point — and nothing would fail):

```js
const OFF_TAB = new Set(["alerts", "momentum"]);
const TABS  = PRIMARY.filter((x) => !OFF_TAB.has(x.key));
const SHEET = [...PRIMARY.filter((x) => OFF_TAB.has(x.key)), ...MORE];
```

PRIMARY 7 · TABS 5 (unchanged set) · SHEET 5 (`momentum` first, since `filter` preserves PRIMARY
order). The whole nav change is then one contiguous region — a clean one-block revert.

**There are SIX `is-here` sites, not four.** Beyond the four item-level ones, two *container*-level
ones are driven by different arrays: the desktop `MORE ▾` button uses `moreActive = more.some(...)`
over `MORE` only (`nav.js:94`), and the mobile MORE tab uses `sheetActive = SHEET.some(...)` over
`SHEET` (`nav.js:147`). Consequence: putting momentum in SHEET correctly lights the mobile MORE tab
on `momentum.html`, while the desktop `MORE ▾` button correctly stays dark because momentum is a
top-level pill there. Both are the wanted behaviour and neither needs new code.

### 5.8 Purple is the most semantically overloaded colour in the codebase

`--purple: #bf5af2` **already exists** (`styles.css:65`, the iOS system palette) and is
**byte-identical to `--ema-144`** (`:68`). It already carries five live meanings:

| Where | Means |
|---|---|
| `--ema-144` | the 144 EMA chart line |
| `phasemap.css:117 .pm-tag-fund` | **FUND / product** |
| `journal.css:506` | time-stop exit reason chip |
| `journal.css .jr-new-lens` | a "new lens" chip |
| `phasemap-insights.html:71` | **the SPECS lens** — `fill="var(--purple)">SPECS — base breakout` |

A sixth violet, `#a78bfa`, is the chart purple in `app.js`/`chart.js`; `journal.css` also keeps
`--me: #b98bff`. **There is no genuinely unclaimed accent token** — the only `:root` accents without
a lens or state meaning are `--teal` (already the London clock) and `--ema-8` pink (the New York clock).

The owner specified purple explicitly (the 🟣 glyph, "Purple illuminate on this page only") and the
standing defaults say not to ask mid-phase, so **purple it is.** Three verified constraints follow:

1. **Do NOT redefine `--purple`.** It is in the shipped contrast gate — `test/contrast.test.js:53`
   lists `["purple", 3.0]` against `--bg`/`--panel`/`--panel-2` — so a darkened value fails CI, and
   it would silently repaint a chart line, a fund tag, an exit chip and another lens's identity.
2. **A soft tint goes in as `rgba(191,90,242,0.16)`.** The house tint strength is exactly 0.16
   across `--blue-soft`/`--green-soft`/`--red-soft`/`--orange-soft`, and there is no `--purple-soft`.
   An rgba value is invisible to the contrast gate, whose regex requires a `#` hex.
3. **Avoid a purple chip inside a deck row's `.row-chips`**, where `.pm-tag-fund` purple may already
   sit — one row, one colour, two meanings. Drive the left badge through the existing inline
   `--grade-color` custom property instead: `.row-grade` already turns it into a 9%/30%/15%-on-hover
   `color-mix` system, so the shared rule cannot regress.

**Flagged, not silently accepted:** purple already denotes *the SPECS lens* in the insights diagram.
That is the closest possible collision for a new lens accent.

### 5.9 The purple pill belongs in `styles.css`, NOT `momentum.css`

This inverts the obvious instinct, so it is worth stating. The pill row renders on **all 13 pages**
via `nav.js`, but a per-page stylesheet is fetched only by its own page. Put the pill colour in
`momentum.css` and the pill is purple on `momentum.html` and default grey on the other twelve —
i.e. **the wayfinding colour is missing from every page you would navigate *from*,** which is the
only place it does any work. All existing cross-page nav chrome already lives in `styles.css`
(`.nav-back` at `:1761`, `.pm-topnav .howto-link`, `.site-tab[data-tabkey=…]`).

The specificity must also be right, because the existing cascade fights back:
`.nav-pills .howto-link:hover` (`:1414`, specificity 0,3,0) sets `color: var(--green)`, and
`.nav-pills .howto-link.is-here` (`:1500`, 0,3,0) sets `background: var(--blue)`. A rest-only purple
rule at 0,3,0 **flickers green on mouse-over**; an `is-here` rule that does not exceed 0,3,0 **stays
blue**. So every momentum rule is a compound selector carrying a momentum-only hook (`.nav-momentum`,
or `[data-tabkey="momentum"]` on mobile) at higher specificity — which also means the other twelve
pills are untouched *by construction* and the block reverts cleanly.

**No test asserts nav pill colour** (`contrast.test.js` only checks `:root` tokens against surfaces,
never a foreground-on-accent pair), so neither the shipped blue pill (3.65:1) nor a purple one
(3.52:1) is gated. A deliberate call, not a constraint — see §7.

### 5.10 The deck row markup is in JS, not HTML

`public/index.html:168` is `<section class="rows" id="results" aria-live="polite"></section>` —
**empty**. Every row is a template literal at `public/js/app.js:1310-1343`
(`<div class="row-wrap…"><div class="row"><div class="row-grade">…`). "Clone index.html's row
anatomy" therefore means cloning that JS template, not copying markup.

### 5.11 FOUR gates auto-enrol the new files — no registration, no opt-out

These are the ones that bite silently, because nothing tells you they apply. Each was read
first-hand. **`public/js/momentum.js` and `public/momentum.html` are covered the moment they exist.**

1. **`test/status.test.js:428`** — globs `public/*.html`; for **any** page matching
   `js/nav.js?v=\d+` it *requires* `js/status.js?v=\d+` **and** `css/status.css?v=\d+`.
   So carrying the shared nav obliges `momentum.html` to load the status lamp too. The rationale is
   the repo's own: *"a control nobody loads is not a control"* — a nav page without the lamp is a
   page where the health signal silently does not exist.
2. **`test/escaping.test.js:29-30`** — globs `public/js/*.js`. If `momentum.js` defines
   `const esc = …` it must escape **all five** of `& < > " '` globally, return `""` for
   null/undefined, and stringify `0`/`false`/numbers. If it merely *calls* `esc(` it must define it
   or use `PM.esc`. (The repo has no bundler, so `esc` is hand-copied per IIFE and has already
   drifted into three different character classes, one live-exploitable through a double-quoted
   attribute.) **Decision: use `PM.esc`** — HANDOFF 17.6 requires it anyway.
3. **`test/leaks.test.js:312`** — no `beforeunload`/`onbeforeunload` anywhere in `public/js`
   (it disqualifies the page from the bfcache for no benefit).
4. **`test/cache.test.js:212`** — §5.6 above.

Three further content bans on `public/js/momentum.js`, each a pin protecting a "two readers and no
more" invariant elsewhere: it must not contain the literal `"data/funnel_history.json"`
(`tests/test_funnel_history.py` names exactly `app.js` and `status.js` as its only readers and fails
on a third), must not contain `spec_graduation`, and if it mentions `vivek_backtest` it must not
also contain `total_usd` / `max_dd_usd` / `params.equity` (those dollar columns are priced under
`params.sizing_mode`, not the live book). None constrains anything momentum actually needs — they
are listed so a future edit does not trip them blind.

Plus the one CI *syntax* gate that exists: `for f in public/js/*.js; do node --check "$f"; done`
(`test.yml:131-134`). So `momentum.js` must parse under plain `node --check`.

### 5.12 Four CLAUDE.md / test.yml claims are STALE — do not reason from them

Each of these was checked against the shipped tree. They are recorded because three of them would
have led me to a wrong number.

| Claim, and where | Reality |
|---|---|
| CLAUDE.md, repeatedly: "pyflakes at its 9 pre-existing warnings" | **There is NO pyflakes gate — no linter of any kind — in any workflow.** `grep -rn 'pyflakes\|flake8\|ruff\|pylint\|mypy' .github/workflows/ requirements.txt` returns nothing. The `python` job is four steps ending at `python -m pytest -q`. It is a *local habit*, so momentum cannot break it in CI and no warning count needs preserving. |
| CLAUDE.md workflow table: "pytest + 15 JS suites"; `test.yml:11-12` header: "1255 pytest (58 files) + 650 JS assertions across 16 suites" | **22 JS suites, 22 registered; 72 `tests/*.py` (79 files / 1,360 tests collected including `phasemap/tests`).** Both counts are a smell test, not a gate, so nothing fails — but do not use 15/16 to reason about insertion position or parity. |
| CLAUDE.md STATUS section: "baselines re-cut at `screenshot-baselines-v19`" | **The shipped key is `v22`** (`test.yml:388`). Three bumps are undocumented, and it is invisible to CI because `test_screenshot_determinism.py:259` only asserts the integer is `>= 11`. |
| CLAUDE.md: "the newest is `screenshot_sentinel.test.js`" | It is registered at `test.yml:172` with **five** suites registered after it (api_guards, access_log, morning_plays_api, sector_cap, status). The *rule* is still a live gate; only "newest" is stale. |

One more, and it is a trap in the registration gate itself:
`test_every_javascript_suite_has_a_step_in_the_workflow` is a **raw substring check over the whole
file**, so a `node test/momentum.test.js` inside a *comment* would satisfy it while the suite never
runs — a green tick on a commit that checked nothing. The job scoping is not enforced, so putting
the step in the `javascript` job is discipline, not a gate.

Also: the **Lighthouse budget is 1.7MB** against a deterministic ~1.15MB baseline, measured on
`index.html?lite=1` **only**. That is a further reason momentum assets must never be referenced from
`index.html` — they would spend headroom that exists for the deck. (CLAUDE.md's 5.0MB → 2.5MB
narrative is the history of that number, not its current value.)

### 5.12B No path-filter edit is needed — HANDOFF 17.7's condition is already met

17.7 says to add `public/<lens>.html`, `public/js/<lens>.js`, `public/css/<lens>.css` and
`scanner/<lens>*.py` to the filter *"if not already covered"*. **They are all already covered.**
The shipped push filter (`test.yml:18-86`) is:

```
scanner/** · phasemap/** · tests/** · test/** · public/js/** · functions/** · requirements.txt
scripts/** · pytest.ini · public/css/** · public/*.html · public/sw.js · public/version.json
journal/** · data/** · .github/workflows/**
```

Every new momentum file lands inside one of those globs, `momentum.yml` included. And
`pull_request:` carries **no** paths filter at all, so a PR runs the whole gate unconditionally.

`public/data/**` is deliberately **out**, which is the reason the lens must publish to
`public/data/momentum/` and nothing else: ~20 scan commits a day would each pay a full Playwright
install to re-test code that did not change. It is also why any gate that reads `public/data/`
becomes a delayed-action fuse pointed at whoever pushes code next — the documented cause of both
the screenshot-calendar and the Lighthouse-tape failures.

### 5.13 A new workflow file is auto-enumerated by pinned tests

`tests/test_workflow_hardening.py:43` — `ALL_WF = sorted(WF.glob("*.yml"))`. `momentum.yml` is
therefore **automatically** subject to five invariants:

1. `test_every_run_block_is_valid_shell` — `bash -n` over every `run:` scalar.
2. `test_no_git_add_stages_more_than_one_path_at_a_time` — one pathspec per `git add` (it is
   ALL-OR-NOTHING: one missing path stages *none*).
3. `test_a_swallowed_git_add_always_has_something_downstream_that_can_tell` — `|| true` on a
   `git add` requires `assert_staged.sh` **in the same step**.
4. `test_every_workflow_declares_its_permissions` — must declare a `permissions:` block.
5. `test_the_first_party_actions_are_the_five_we_reviewed` — the `actions/*` set must remain
   **exactly** `{checkout, setup-python, setup-node, cache, upload-artifact}`. **momentum.yml may not
   introduce a new action**, or this tripwire fires. Nor may anything float on `@main`/`@master`/`@latest`.

And from `tests/test_workflow_mutex.py`:
`test_the_wait_loop_watches_every_member_of_the_group` — **if momentum.yml used `group: scan` it
would have to be added to close_position.yml's watched-names list, and would fail the test until it
was.** So HANDOFF 17.5's "own concurrency group" rule is test-enforced, not merely advice. Using
`group: momentum` satisfies it by construction.

`scripts/assert_staged.sh <label> <path>…` is **ANY-OF**: exits 0 if at least one listed path has a
staged diff. "All must change" = several calls of one path each.

---

### 5.14 `public/data/momentum/` is swept up by NOTHING — verified

The output directory is the other half of removability, so it was checked rather than assumed:

- **No broad glob over `public/data/`** exists anywhere in `scanner/`, `scripts/`, `tests/` or
  `functions/`. The only `glob("*.json")` calls are `scanner/history_archive.py:109` (scoped to its
  own `base` dir) and two in the tests, both scoped to the **e2e fixture** directory.
- **Backups are an explicit allowlist, not a tree sweep.** `tests/test_backup_completeness.py`
  asserts specific paths are *members of* `backup_journals.BACKUP_FILES` / `REQUIRED_FILES`; it does
  not assert the list covers the tree. So momentum output needs no backup entry and omitting one
  fails nothing.
- **`.gitignore` has no rule touching `public/`** — the only data-ish entries are `.cache/`
  (the frame cache) and `.scan-skipped`. So `public/data/momentum/*.json` commits normally.
- `public/data/**` is outside `test.yml`'s path filter (§5.12B), so publishing never triggers CI.

Combined with the subdirectory layout, this is why the brief's `public/data/momentum/<market>.json`
beats HANDOFF 17.2's `public/data/<market>_momentum.json`: the subdirectory cannot be caught by a
future `public/data/*.json` glob, and deletion is one `git rm -r`.

## 5B. THE FENCE NAME COLLIDES — two of the specified fences fail on the pristine tree

This is the sharpest finding in the phase and it blocks Phase 1 as literally specified.

**The word "momentum" already exists in two of the files the fences are supposed to keep clean**, as
ordinary English prose written years before this lens was conceived:

```
scanner/broker/vivek_bot.py:58   # a real momentum/trend trade. Detected by sector + name ...
scanner/vivek.py:725               the level (a break of small structure / momentum entry).
```

Both are comments about price behaviour. Neither has anything to do with this lens. But they mean:

- **HANDOFF 17.4's fence template — `assert "<lens>" not in src.lower()` — goes RED on
  `vivek_bot.py` the moment it is written**, with no momentum code in the tree at all.
- **The brief's fence #5, "grep `scanner/vivek.py` has no 'momentum'", is already violated** by
  `vivek.py:725`.

A fence that is red on a pristine tree is not a strict fence, it is a fence that gets deleted. And
HANDOFF 17.1 anticipated exactly this: *"Avoid a name that collides with an existing field or state
string."* The owner chose MOMENTUM, so the name stands — **the fences move to the token, not the
English noun.**

### The corrected fence design

Fence on **identifiers**, which is what `tests/test_conviction.py:184` already does for its own
display/bot fence (the house precedent, and it uses a regex over import statements, not a substring
over the whole file):

```python
ROOT = pathlib.Path(__file__).resolve().parents[1]
_IMPORT = re.compile(r"^\s*(?:from|import)\s+.*\bmomentum\b", re.M)   # import lines only
_TOKEN  = re.compile(r"scanner[./]momentum|MOMENTUM_|momentum\.json|data/momentum")
```

- **`_IMPORT`** answers "can this file reach the lens?" — the question the fence exists to ask.
- **`_TOKEN`** answers "does this file name the lens's module, config prefix or artefact?" and
  deliberately does **not** match the bare English word, so `vivek_bot.py:58` and `vivek.py:725`
  stay green.
- Applied to `(ROOT/"scanner"/"broker").glob("*.py")` — `.glob`, matching the house precedent;
  `broker/` has no subdirectories, and globbing `*.py` also sidesteps the `__pycache__/*.pyc` files
  sitting in that directory.

**Both directions**, per the `is_product` precedent HANDOFF 17.4 cites: the lens may not reach the
bot, *and* the bot may not reach the lens.

**A test must pin the collision itself** — asserting that the two known prose mentions are still
tolerated — or the next person to "tighten" the fence to a bare substring re-breaks it and cannot
tell a real leak from a comment about price behaviour.

## 6. Conflicts between the three governing documents, and how each is ruled

The brief's own precedence rule: *"live file + CORE spec win over this prompt; this prompt wins over
inventing new filters"*, and *"If a spec sentence and HANDOFF Part 17 conflict, HANDOFF fences win."*

| # | Conflict | Ruling |
|---|---|---|
| 1 | **Layout.** HANDOFF 17.2 and spec §5.8 both prescribe a flat module (`scanner/<lens>.py`, `public/data/<market>_<lens>.json`). The brief specifies a package (`scanner/momentum/`) and a data *directory* (`public/data/momentum/<market>.json`). | **Brief wins.** This is a *convention*, not a fence (fences are 17.4), and the package form better serves 17.0's governing principle — deletion is `git rm -r scanner/momentum public/data/momentum`. It also keeps the output out of any `public/data/*.json` glob. Fence #4 is written against this layout. |
| 2 | **Fence count.** The brief lists 6 fences. HANDOFF 17.4 additionally requires: engine is offline/deterministic (no `requests`/`urllib`/`yfinance`/`datetime.now`/`time.time`), every threshold in config (no magic numbers), a broader forbidden-artefact list (`_vivek.json`, `_spec.json`, `latest.json`, `vivek_bot_book`, `bot_rules.json`, `alert_history.json`, `funnel_history.json`), and fencing **in both directions** per the `is_product` precedent. | **HANDOFF wins — implement the union.** These are fences, and fences win outright. |
| 3 | **Mode C.** Spec §5.4 defines it; the reference does not implement it; the brief calls it "a later owner decision". | Implement A/B/C to spec, **default A**, pin the default. Implementing a *specified* mode is not inventing a filter; the owner's reserved decision is the default. |
| 4 | **Rule B in mode A.** The reference only populates `rule_b` when `mode == 2` (`:1088`). The brief says "Ship B computation in the payload/evidence but do NOT default the deck to B or C." | **Brief wins** — compute and publish `rule_b` on every row regardless of mode; mode gates only `passes`. A deliberate, recorded deviation from the reference. |
| 5 | **`WATCHDOG_RUNS`.** HANDOFF 17.5 asks for an entry if the workflow commits data. That means editing `scanner/config.py`, which is not on the brief's allowed-files list. | **Owner decision — see §7.** Default: omit, and pin the omission as a *decision* (the repo's own precedent for `confluence.yml`'s deliberate absence of `assert_staged`). |
| 6 | **`CLAUDE.md` section.** HANDOFF 17.9 requires one; it is not on the brief's allowed-files list. | **Owner decision — see §7.** The content will be drafted in the Phase 7 handoff note so it is one paste away. |
| 7 | **`test.yml`.** Not on the brief's allowed-files list, yet the brief itself mandates registering the JS suite there, and 17.7 requires path-filter entries. | **Must edit** — the allowed-files list is simply incomplete here; its own fence instruction requires it. |
| 8 | **`scanner/config.py` for tunables.** HANDOFF 17.3 says every threshold goes in `scanner/config.py` under a `<LENS>_` prefix. The brief says `scanner/momentum/config.py`. | **Brief wins** — a package-local config is strictly more removable and satisfies the *intent* (no magic numbers in the engine) exactly. Shared constants that §5.6 mandates reusing are still imported from `scanner/config.py`. |

---

## 7. Open owner decisions (flagged, not guessed — none blocks Phases 1–6)

1. **Push target** — `vivek-momentum-v1` (brief) vs `claude/epic-keller-pr4x0x` (harness). §1.
2. **`WATCHDOG_RUNS` entry** for `momentum.yml`. Adding one means the watchdog alarms if the lens
   stops publishing; it costs a one-line edit to `scanner/config.py` (off the allowed list) and one
   more thing to remove at deletion. **Recommendation: omit for a report-only v1**, with the
   omission pinned as a decision. A report-only lens going quiet costs nothing but a stale page.
3. **`CLAUDE.md` section** (HANDOFF 17.9). **Recommendation: yes**, but as a separate commit the
   owner can drop, since it is off the allowed list.
4. **Add `momentum.html` to `smoke.e2e.js`'s page-error loop?** One line; catches a JS error on the
   new page that no unit suite would. HANDOFF 17.7 calls it "cheap insurance". It edits a file off
   the allowed list. **Recommendation: yes, as its own droppable commit**, and explicitly **not**
   `screenshots.e2e.js` / `screenshot-diff.e2e.js`, so no baseline re-cut is ever needed (§5.5).
5. **Crypto in v1.** Brief: "crypto optional v1", owner defaults say "Markets v1: ASX + NASDAQ
   (crypto engine may run, page may show it)". **Plan: engine + CLI support all three; the workflow
   schedules ASX + NASDAQ only**; the page shows a CRYPTO button that honestly renders empty until
   something publishes.
6. **The strict-pivot tie convention** (§4.2) — a five-minute check against a real TradingView chart
   that only the owner can do. Default strict until then.
7. **The `is-here` pill contrast.** White on `var(--purple)` measures **3.52:1**, essentially matching
   the shipped blue pill's 3.65:1, but below AA-normal (4.5) at the pill's 12.5px/700. Nothing in CI
   gates a foreground-on-accent pair either way. **Recommendation: accept parity with the existing
   blue pill** rather than introduce a one-off dark foreground (`#1a0526` on purple = 5.45:1) that
   would make MOMENTUM the only pill in the row that reads differently.
8. **Purple already means "the SPECS lens"** in `phasemap-insights.html:71`, and "FUND" on the
   PhaseMap tag (§5.8). The owner specified purple, so purple ships — but he may prefer to know that
   the deck already teaches purple = Specs/fund before it also means Momentum.
9. **`chart.js`'s `SRC_BACK` map, `manifest.json` shortcuts and `404.html`'s recovery buttons** are
   three further hardcoded page lists that do **not** follow `nav.js`. None breaks without a momentum
   entry (an unknown `src` falls through to the default back-link), so **recommendation: leave all
   three alone** — each addition is one more file in the revert. Revisit only if momentum rows will
   deep-link into `chart.html?src=momentum`.

---

## 8. Environment notes (this sandbox, not the repo)

The container had **no Python dependencies installed** — `numpy`, `pandas` and even `pytest` were
absent, and `pip install -r requirements.txt` failed against a Debian-managed `PyYAML 6.0.1`
("Cannot uninstall … RECORD file not found"). Resolved with a venv at `.venv/` (gitignored), which
is also the local path CLAUDE.md documents:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Exact pins installed: numpy 2.4.6, pandas 3.0.3, pytest 9.1.1, PyYAML 6.0.3, yfinance 1.4.1.
**Run every gate as `.venv/bin/python -m pytest`,** not bare `python`.

---

## 9. Baselines for the Phase 7 no-regression proof

Captured before any engine code:

| Measure | Value |
|---|---|
| `origin/main` | `2f52df7f22614ead9e526d6864d05d835aaedd8d` |
| pytest collection | **1,360 tests across 79 files** |
| JS unit suites | **22**, all registered in `test.yml` |
| `journal/` | **9 files**; manifest sha256 `362856ced4c463c09fd715c62f5d606b51b65fcb691e7ab18547b03369e680d8` |
| version fingerprint | `69e01b09` (28 refs, `sw:vivek5-v8`) |
| reference selftest | **28/28 pass** |

`journal/` hashes are stored at `scratchpad/journal-before.sha256`; regenerate with
`find journal -type f | sort | xargs sha256sum`.

---

## 10. The file list for Phases 1–6

**New (all additive, all removable in one `git rm`):**

```
scanner/momentum/__init__.py
scanner/momentum/config.py        every tunable + the rationale comments
scanner/momentum/ema.py           Pine-seeded EMA / RMA
scanner/momentum/macd.py          Pine-compatible MACD (nothing in the repo has one)
scanner/momentum/pivots.py        strict both-sides pivots on a 1-D series
scanner/momentum/screen.py        Rule A + Rule B + gates + ranking
scanner/momentum/run.py           CLI: python -m scanner.momentum.run --market asx
tests/test_momentum_fences.py     the union of brief + HANDOFF 17.4 fences
tests/test_momentum_screen.py     28 ported assertions + causality + sort-order
test/momentum.test.js             nav contract, purple, fetch path, empty state
public/momentum.html              MUST load, in this order: css/fonts.css, css/styles.css,
                                  css/status.css, css/momentum.css -- and js/status.js,
                                  because test/status.test.js requires the lamp on any
                                  page that loads nav.js (5.11)
public/js/momentum.js             use PM.esc, no beforeunload, must pass `node --check` (5.11)
public/css/momentum.css           the PAGE's own styles only; namespaced --mo-* tokens like
                                  phasemap.css. The nav pill colour goes in styles.css (5.9)
public/data/momentum/.gitkeep
.github/workflows/momentum.yml    own concurrency group, declared permissions, tz gate
reviews/2026-09-22-momentum-phase0.md      (this file)
reviews/2026-09-22-momentum-handoff.md     (Phase 7)
```

**Modified (minimally):**

```
public/js/nav.js                  +1 PRIMARY entry; OFF_TAB set drives TABS + SHEET (one region)
public/css/styles.css             purple pill selectors ONLY -- must be here, not momentum.css (5.9)
public/*.html  (x12)              js/nav.js ?v=24 -> 25 AND css/styles.css ?v=115 -> 116,
                                  in the SAME commit, on EVERY page -- cache.test.js:222 fails
                                  on any cross-page ?v= skew (5.6)
public/version.json               re-stamp to 2026.09.22-<digest>, replayed from the test (5.2)
.github/workflows/test.yml        the node test/momentum.test.js step + path-filter entries
```

The 12 pages that stamp `nav.js`: `404`, `about`, `alerts`, `index`, `journal`, `phasemap`,
`phasemap-insights`, `phasemap-legend`, `recommendations`, `sectors`, `specs`, `system`
(`chart.html` deliberately carries its own minimal nav). `momentum.html` must request the same
bumped versions.

**Already landed:** `tradingview/scanner-spec/**` (commit `a1bdc19f`).

**Untouched, and `git diff --stat` will prove it:** `scanner/vivek.py`, `scanner/scan.py`,
`scanner/conviction.py`, `scanner/broker/**`, `scanner/confluence_alert.py`, `scripts/morning_plays.py`,
`phasemap/**`, `journal/**`, `public/data/*_vivek.json`, `bot_rules.json`.
