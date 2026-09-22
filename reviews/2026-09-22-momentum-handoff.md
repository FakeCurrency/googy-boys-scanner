# VIVEK MOMENTUM v1 — landing note

**Branch:** `vivek-momentum-v1` · **Base:** `origin/main` @ `2f52df7f` · **Written:** 2026-09-22
**Status:** 8 commits, local only. **Nothing has been pushed and no PR exists.**

The inventory, every ruling, and every conflict between the brief, HANDOFF Part 17 and the spec are
in `reviews/2026-09-22-momentum-phase0.md`. This note is what a reviewer needs: what shipped, what
proves it, what is still the owner's to decide, and how to take it out again.

---

## 1. What it is

A fourth, **report-only** lens. On daily bars, per market, it screens for:

- **Rule A** — an RSI *regular divergence* off strict both-sides pivots **on the RSI series**, not
  on price. Confirmed within `div_fresh_bars` closed bars.
- **Rule B** — a 20/50 moving-average cross scored `1 + MACD agrees + price beyond the 200`,
  gated at `min_signal_score`.

v1 ships **mode A** (divergence only) on a **1-bar** freshness window. Rule B is computed and
published as evidence on every row regardless, so widening to mode B later is a config change and
not a re-scan.

**It changes no trades, and that is structural rather than promised.** Nothing under
`scanner/broker/` can reach it, it imports neither the bot nor the HIGH CONVICTION rule, it is not
in the confluence machinery, and it owns exactly one output directory.

---

## 2. The two facts the surfaces exist to carry

**The two rules do not mean the same thing.** Rule B has zero detection lag — a cross on bar `i` is
knowable at the close of bar `i`. Rule A has a **five-bar** lag, because you cannot know a bar was a
local low until you have seen the bars after it, so a divergence confirmed on bar `i` describes a
pivot at `i-5` and **that is where TradingView draws the label**. If both rules report
`bars_ago = 1`, the underlying market events are six bars apart in age. Every row therefore carries
both numbers and the page shows both. Show one and the owner opens a chart, finds the label on a
different bar from the date we named, and stops trusting the page.

**"Score ≥ 2" is not a filter, and this is measured.** Over 1.95M simulated symbol-days a bare
score of 1 is **2%** of crosses (2 is 37%, 3 is 61%) — the scoring terms are correlated with the
cross by construction. Raising the threshold cannot make Rule B selective, so v1 does not try.

---

## 3. What proves it

| Claim | Evidence |
|---|---|
| The maths is the owner's tested reference | **Bit-identical** over 35,360 field values, all 49 row keys (35 always-present + 14 conditional), both modes, Rule A firing 496× and Rule B 548×. Indicator-level bit-identity separately, because a row match could hide two compensating errors. |
| …and stays that way | The reference's **own 28 assertions run verbatim against this package** through a shim, so they cannot drift from the spec they came with. 28/28. |
| No look-ahead | The causality proof truncates the frame at every bar and re-derives: 223 cut points × 40 columns, 41 screen re-runs, zero mismatches — plus the meta-test that **plants** a look-ahead and requires the proof to catch it. |
| The tests aren't decorative | **8 mutations to the ported maths**, one at a time (pivot strictness, EMA seeding, MACD sign, the 5-bar lag, the score base, the freshness window, crossover's previous-bar rule, silent sorting of a descending frame). All 8 caught; sources restored byte-identical. |
| Pine parity on the number that matters | EMA200 Pine-vs-pandas drift reproduces the spec exactly: **0.2466** price units at bar 600 (spec: 0.247), 0.0046 at bar 999, against **0.000000** for the EMA 20 and 50. |
| The page works | Real browser, four pages, two viewports: zero uncaught page errors with data, without data, and at 320px; honest empty states; 16 rows rendering with both-age chips; filters narrowing correctly. |
| The nav didn't break anything | MOMENTUM illuminates solid purple on its own page and rests on the tint elsewhere; **no other pill turned purple**; exactly 5 bottom tabs at 320px with MOMENTUM reachable via MORE; e2e smoke green including its 320px overflow checks on all five registered pages. |
| It didn't move the photographed pages | Screenshot drift **measured**, old tree vs new, same fixtures, frozen clock: index-desktop 0.01%, index-390 0.00%, journal-desktop 0.59%, journal-390 0.00% — against a 2% budget. `screenshot-baselines-v22` stands. |
| It is genuinely removable | The removal was **executed**: one commit, and the tree returns to exactly the baseline — **1360 tests / 79 files, all 22 JS suites green**. See §6. |

**Gate at `41aadaf3`:** full pytest green at **1467 tests / 83 files** (baseline 1360/79), **23 JS
suites** all green and all registered, e2e smoke green, `journal/` byte-identical (9 files, manifest
`362856ce…`).

---

## 4. Everything the branch touches

**New** — `scanner/momentum/{__init__,config,ema,macd,pivots,gates,screen,run}.py` ·
`tests/test_momentum_{fences,screen,publish,workflow}.py` · `test/momentum.test.js` ·
`public/momentum.html` · `public/js/momentum.js` · `public/css/momentum.css` ·
`public/data/momentum/.gitkeep` · `.github/workflows/momentum.yml` · `reviews/*.md` ·
`tradingview/scanner-spec/**` (recovered, see §5).

**Modified, minimally** — `public/js/nav.js` (one PRIMARY entry; `OFF_TAB` now drives TABS and
SHEET) · `public/css/styles.css` (+60 lines, every selector carrying `[href="momentum.html"]`) ·
14 HTML pages (**version bumps only**: exactly 27 changed lines, 13 × `nav.js?v=25` and 14 ×
`styles.css?v=116`) · `public/version.json` (one string) · `.github/workflows/test.yml` (+11: the
node step).

**Verified untouched** — `scanner/broker/**`, `vivek.py`, `scan.py`, `spec.py`, `conviction.py`,
`confluence_alert.py`, `morning_plays.py`, `phasemap/**`, `journal/**`, `scanner/config.py`,
`bot_rules.json`, the published `*_vivek.json`, and `scan.yml` / `crypto_bot.yml` /
`close_position.yml`.

---

## 5. Three things a reviewer should know before reading the diff

**The spec pack was not on main.** The brief cited `scanner-spec/` and commit `80d4d44`. The real
path is `tradingview/scanner-spec/`, `tradingview/` does not exist on main at all, and `80d4d44`
lives only on `origin/claude/optimistic-darwin-r6s49g` — it was unreachable until the shallow clone
was deepened. Commit `a1bdc19f` lands the docs+reference subtree (the commit's other two hunks
modify files that have no base on main). It is wired into nothing: `pytest.ini`'s `testpaths` make
it uncollectable, proven two ways.

**Two of the specified fences were red on a pristine tree.** The word "momentum" already appears in
`scanner/broker/vivek_bot.py:58` and `scanner/vivek.py:725` as ordinary prose about price
behaviour, so HANDOFF 17.4's `assert "<lens>" not in src.lower()` and the brief's fence #5 fail
before any code exists. The fences moved to the **import/module token**, following
`tests/test_conviction.py`'s precedent, with a tripwire enumerating the two known prose sites so a
third gets a human look. A fence that is red on a clean tree is one that gets deleted.

**Four gates auto-enrol new files and the brief named none of them** — `cache.test.js` (cross-page
`?v=` skew, which is why the nav bump is all-or-nothing across 13 pages), `status.test.js` (a
nav-bearing page must also load the status lamp), `escaping.test.js`, `leaks.test.js`. A fifth,
`test_publish_integrity.py`, sweeps `scanner/` recursively — and the reference's own writer would
slip past both its construct sweeps if it had been copied in wholesale.

---

## 6. How to remove it

One commit, and this was executed rather than asserted:

```bash
git rm -r scanner/momentum public/data/momentum \
          tests/test_momentum_*.py test/momentum.test.js \
          public/momentum.html public/js/momentum.js public/css/momentum.css \
          .github/workflows/momentum.yml
git checkout <base> -- public/js/nav.js public/css/styles.css public/version.json \
                       .github/workflows/test.yml public/*.html
```

Result: 1360 tests / 79 files, 22 JS suites, all green — the exact baseline. Only the spec pack and
these two notes remain, and both are documentation wired into nothing.

---

## 7. Open for the owner — none of it blocks review

1. **Push target.** The brief says `vivek-momentum-v1`; this session's harness designates
   `claude/epic-keller-pr4x0x`. Nothing is pushed, so it is still an open choice.
2. **`WATCHDOG_RUNS` entry for `momentum.yml`** — deliberately omitted and **pinned as a decision**
   (`test_there_is_DELIBERATELY_no_watchdog_entry`), because for a report-only lens a quiet day
   costs a stale page and nothing else, and an entry means editing `scanner/config.py`. The test
   says exactly what to add and to delete itself in the same commit.
3. **A `CLAUDE.md` section** (HANDOFF 17.9). Not written, because `CLAUDE.md` is off the brief's
   allowed-file list. Draft below, ready to paste as its own droppable commit.
4. **`momentum.html` in `smoke.e2e.js`'s 320px loop** — one line of cheap insurance that HANDOFF
   17.7 recommends. Not added, for the same allowed-list reason. (The page is already verified at
   320px by hand.) **Not** recommended for `screenshots.e2e.js` or `screenshot-diff.e2e.js`, which
   would drag the baselines in.
5. **The strict-pivot tie convention.** Whether Pine's `ta.pivotlow` needs strictly-lower or `<=`
   is undocumented by TradingView and was never settled empirically. Measured disagreement: **0.8%**
   of divergences, and **not in one direction** (10 fire only under strict, 17 only under
   non-strict). Default is strict — the only convention that cannot fire on a flat series. Settling
   it is a five-minute check against a real chart and only the owner can do it.
6. **Purple already means other things.** `--purple` is byte-identical to `--ema-144` and already
   denotes a FUND tag, a time-stop exit chip and — closest to home — **the SPECS lens** in the
   insights diagram. Purple was specified, so purple shipped; flagged because the deck already
   teaches it.
7. **Mode B / mode C.** Both implemented, neither defaulted. Switching is `--mode B` or a config
   default change, with no re-scan needed.

### Draft `CLAUDE.md` section

```markdown
## MOMENTUM — the divergence lens (2026-09-22) — REPORT-ONLY

A fourth lens, additive and deletable in one commit. Daily bars, per market:
**Rule A** an RSI regular divergence off STRICT both-sides pivots computed on
the RSI SERIES (not price); **Rule B** a 20/50 cross scored 1 + MACD-agrees +
price-beyond-the-200. v1 ships mode A (divergence only) on a 1-bar window;
Rule B is computed and published as evidence regardless.

**IT CHANGES NO TRADES, STRUCTURALLY.** Nothing under `scanner/broker/` can
reach it, it imports neither `vivek_bot` nor `conviction`, it is not in the
confluence machinery, and it owns exactly `public/data/momentum/`.
`tests/test_momentum_fences.py` fences BOTH directions. NOTE the fences are on
the IMPORT/MODULE TOKEN, not the word: "momentum" already appears as ordinary
prose in `vivek_bot.py:58` and `vivek.py:725`, so a substring fence is red on a
clean tree. A tripwire enumerates those two sites.

**The maths is a PORT of `tradingview/scanner-spec/reference/vivek50_screen.py`,
extracted rather than retyped.** `tests/test_momentum_screen.py` proves it three
ways: self-contained behaviour, bit-identity against the reference, and the
reference's own 28 assertions run verbatim against this package. Layers 2 and 3
skip visibly if the spec pack is removed.

**Two numbers that are not negotiable.** Rule A carries a FIVE-BAR detection lag
and every row publishes both `rule_a_bars_ago` (knowable) and
`rule_a_pivot_bars_ago` (where TradingView draws the label). And the EMA 200
uses PINE's SMA seeding, not `ewm(adjust=False)`: measured 0.247 price units
adrift at bar 600, enough to flip `close > slow`, which is one of Rule B's two
live scoring terms.

**Cadence:** post-close only, one market per run — ASX 06:30 UTC, NASDAQ 21:30
UTC, crypto 00:30 UTC, each chosen to clear the close in BOTH halves of the DST
year. A daily screener must NOT run intraday: a forming bar's RSI and EMA move
all session. `momentum.yml` has its OWN concurrency group and deliberately no
`WATCHDOG_RUNS` entry (pinned as a decision). Exit 3 means "the download came
back empty, the previous file stands" and never reaches the commit step.

**Honest limits:** survivorship bias in any backtest off this; the strict-vs-
non-strict pivot tie convention is undocumented upstream and unsettled (0.8% of
divergences, both directions); "score >= 2" filters almost nothing (score 1 is
2% of crosses over 1.95M simulated symbol-days), so it is not a quality dial.

**To wire it into trades** would need: the owner's sign-off with numbers, a
walk-forward replay of the cells the way HIGH CONVICTION got one, and removal of
the fences above — in that order.
```

---

## 8. Merge

Rebase-and-merge, never squash, never a merge commit — the eight commits are the
argument. After merge: PR number, SHA on main, the file list from §4, the test counts from §3, the
journal hashes before == after, and Grok can review.
