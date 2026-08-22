# Turtle money-UI pass — audit (Phases A–E)

Branch `turtle-ui-pass`, layered on top of the overnight UI pass (Phases 2–10,
closed out in `handoffs/2026-08-23-turtle-ui-overnight.md`). This pass ran
Phases A → E under the standing "owner is going to bed" instruction, in
order, each DO → AUDIT → GATE → COMMIT. Every gate passed on the first
attempt; the three-strikes-then-BLOCKED escalation was never triggered.
**Not pushed** — see Push status, below.

---

## 1. origin/main — verified, not trusted

The incoming brief claimed `origin/main = 116bb4f`. Fetched and checked:
the true tip was one commit further, `80ef86b6a657acc26d28fd8c520f88e911d31e2e`
("journal: manual close x1 - ZUMZ", an unrelated `vivek_bot_book` journal
commit — not Turtle). Rebased onto the *real* tip, not the brief's stale
one; documented in `reviews/2026-08-23-turtle-phaseA-verify.md`. Zero
conflicts (confirmed zero file overlap in advance); all 9 prior commits
replayed with new SHAs, content byte-identical (diffed old-tip vs new HEAD
on every touched file — empty). `git merge-base HEAD origin/main` now
reads `80ef86b6a657acc26d28fd8c520f88e911d31e2e` — confirmed still an
ancestor at the close of this pass.

## 2. Local commits, Phase A → E1

| Phase | SHA | Commit |
|---|---|---|
| A | `01c90f8` | docs: turtle Phase A verification (money-UI pass) |
| B | `6d83f7d` | turtle: chart back-link + mynames fence |
| C | `c693319` | turtle: 5x print on the book |
| D | `0314086` | turtle: cash-skip dollars + next-stop from payload |
| E1 | `388fecb` | turtle: cache bumps after money-UI |

E2 (this document) follows as the sixth and final commit.

## 3. Journal integrity — the one number that overrides every other claim here

```
JOURNAL_SHA_AFTER_REBASE (taken once, immediately after the Phase A rebase):
4934d7341ff83c721e48bff0c0df1819a36c54978f4f44d502d0f302b4d2d956  journal/turtle_book.asx.json
f720efae30f20ba22aa115c5f3bf41e2c8276991900cd5f572c1ea6ec01f5d3e  journal/turtle_book.crypto.json
3dd336243ad623cc225ccb1ac037ab16c55080d0aca0f45f3c6436d38aba511b  journal/turtle_book.crypto5x.json
a454f8e28deba081263ea7bd65f80416eda8489b2bb6ae9f745db41871f03790  journal/turtle_book.futures.json
ff51271c109cc669f9c5a4b32440cc3048a738a78c290b8d92e2dfb8cb0862d2  journal/turtle_book.json
b63308271498712e81dfe5058ad9aaff7b5c1aaca5f230e289a8aebae03edda8  journal/turtle_book.nasdaq.json

FINAL (re-hashed just now, end of Phase E1):
4934d7341ff83c721e48bff0c0df1819a36c54978f4f44d502d0f302b4d2d956  journal/turtle_book.asx.json        MATCH
f720efae30f20ba22aa115c5f3bf41e2c8276991900cd5f572c1ea6ec01f5d3e  journal/turtle_book.crypto.json     MATCH
3dd336243ad623cc225ccb1ac037ab16c55080d0aca0f45f3c6436d38aba511b  journal/turtle_book.crypto5x.json   MATCH
a454f8e28deba081263ea7bd65f80416eda8489b2bb6ae9f745db41871f03790  journal/turtle_book.futures.json    MATCH
ff51271c109cc669f9c5a4b32440cc3048a738a78c290b8d92e2dfb8cb0862d2  journal/turtle_book.json            MATCH
b63308271498712e81dfe5058ad9aaff7b5c1aaca5f230e289a8aebae03edda8  journal/turtle_book.nasdaq.json     MATCH
```

All six byte-identical, checked after every phase's own GATE and again
here. Note this baseline is *not* the same as the overnight pass's
`PHASE0_JOURNAL_SHA` — `asx`/`nasdaq`/`futures` match across both nights
(nothing moved them), but `crypto`/`crypto5x`/the combined `turtle_book.json`
differ, because `origin/main` genuinely advanced between the two passes
(the `116bb4f`/`80ef86b` data commits this pass rebased onto). That is the
crypto5× sleeve going live, not drift.

## 4. The 5× print, as of this SHA

```
crypto5x summary:  started 2026-08-22
                    equity_start 5,000.0 · equity 5,000.0 · return 0.00%
                    open 6 positions / 6 units · closed 0
                    leverage 5.0 · posted_margin 1,159.76 · free_margin 3,840.24
                    params: fractional=true · cost_bps=15.0 · margin_mode=isolated

open (all long, all 1 Turtle-unit / 1 fill):
  ZEC   S2   qty 1.2655     posted $199.39
  BCH   S2   qty 4.2657     posted $236.43
  DASH  S2   qty 26.4031    posted $213.28
  UNI   S1   qty 213.6562   posted $176.91
  NEAR  S2   qty 491.5529   posted $189.63
  WLD   S2   qty 1,776.6464 posted $144.12

combined skip_counts: {cash: 70, per_market_cap: 1, close_corr_cap: 12, total: 83}
```

Unchanged from the Phase A verification snapshot (journals are frozen this
whole pass, §3) — this is the same print, now rendered honestly instead of
invisibly. "THE MONEY STORY" stands exactly as the brief stated it: cash
crypto couldn't fit units (70 cash skips, $102,242 notional refused — the
real figure Phase D's combined-card sentence now shows); 5× fitted 6 units
with $3,840.24 free margin still left; the close-correlation cap (6, frozen)
is what actually bound after that — 12 skips, all `close_corr_cap`, 6 adds
on the held names above and 6 entries on APT/ATOM/DOT/FIL/ONDO/XLM. The
by-market table's own note (`turtle.js:1046-1086`) now states this live,
deriving "6/6" from the skip rows themselves rather than a hardcoded
number.

## 5. Cash 2026-08-21 closed rows — byte-stability vs `9adda79`, re-confirmed

`af7c795` is a blob hash, not a commit — `journal/turtle_book.crypto.json`'s
content at commit `9adda792e0d06b56108eaa14c7d60d5c55f4abd7`. Checked a
third time tonight (once before the Phase A rebase, once after, once now),
via Python dict-equality rather than a text diff so field-order noise can't
hide a real change: both the blob and the current file carry exactly the
same 5 closed rows dated 2026-08-21 — AAVE, ADA, BCH, ETC, XRP — field-for-
field identical all three times. Unmoved.

## 6. UNI / NEAR / NRBY — three names, three different reasons to be careful

- **UNI** is the Yahoo-override path. `scanner/config.py:1841-1847`
  (`TURTLE_5X_YF_OVERRIDES`) maps `"UNI": "UNI7083-USD"` because the bare
  ticker `UNI-USD` on Yahoo resolves to a different coin (UNICORN), not
  Uniswap. `scanner/turtle_run.py`'s `five_x_rows` is the only caller that
  builds rows from this map — confirmed by a repo-wide grep, nothing in the
  cash-crypto scan's own row-building path touches it. The override is
  scoped to the 5× sleeve only, exactly as FROZEN LAW requires.
- **NEAR** is real — NEAR Protocol, not in the override map at all (it
  doesn't need one), trading under its own ticker. Confirmed live in
  tonight's BOOK payload: `"symbol": "NEAR"`, real fills, real posted
  margin (§4).
- **NRBY** is unrelated to either. It is a synthetic TEST FIXTURE symbol —
  `tests/test_turtle.py:33,58,826,852` — one of four (FIRE/HELD/NRBY/SHRT)
  used to exercise the scan's own state buckets, standing for "near a
  trigger level," not for NEAR Protocol. It only resembles "NEAR" as text.
  The standing instruction not to "rename NRBY back" is protecting against
  exactly the mistake that similarity invites — renaming a fixture symbol
  into a collision with a real, currently-open crypto5× position's ticker.

## 7. Grok's ten — still already-done

All ten items from the overnight audit (`handoffs/2026-08-23-turtle-ui-overnight.md`
§4) stand exactly as reported: eight already done before tonight, two
"don't"s already respected. One of those two — "do NOT star Turtle into MY
NAMES" — was flagged there as "not yet a *permanent test*"; Phase B closed
that gap tonight (§8, item 7 below is the same fix, since it's also the
owner's own ranked-ten item 7). Everything else Grok-ten covers is
untouched by this pass: no `setInterval`/`setTimeout`/`location.reload`
was added, `nav.js` still carries zero diff across this entire pass
(`git diff --stat 585a6ab..HEAD`, §11 below), and the FALLBACK mirror is
untouched.

## 8. The owner's ranked ten — status after Phases C and D

The full list is `handoffs/2026-08-23-turtle-ui-overnight.md` §7. Status
now:

| # | What | Status | Where |
|---|---|---|---|
| 1 | Real futures margin file | **Not done — owner's to supply.** Still forbidden to invent. `_load_margin_file()` still returns `None`, futures still 0/0. | — |
| 2 | Cumulative $ of cash-declined signals on the forward-book card | **Done, Phase D.** "70 cash skips on 2026-08-22 across 3 books: $102,242 notional the cash books refused." Summed from `want_notional` on the latest bar only, partial-data honesty built in (none needed tonight — 0 of 70 rows missing the field). | `turtle.js:1093-1116` (computed), `:1252` (rendered) |
| 3 | "Would this cash-skip fit on 5×?" annotation | **Done, Phase D — client-side, not server-side.** The original description assumed `posted_want` already existed on skip rows; checked the real data and it does not (only `want_notional` does, on cash-reason rows). Built as a read-only comparison — `want_notional / leverage` vs the levered sibling's real `free_margin` — found via `scanMarketFor`'s own suffix rule in reverse, never a hardcoded sleeve key. Live-verified: crypto cash-skips each show "fits on 5×"; asx/nasdaq cash-skips (no levered sibling exists) correctly show nothing. | `fitsOnLeveredHTML`, `turtle.js:1173-1187` |
| 4 | Liquidation-distance column on BOOK's open-positions table | **Done, Phase C.** Was buried in the SIGNALS-view detail grid only; now a real column ("Liq dist.") on the levered open-positions table itself, using the pre-existing `liqDistanceR()` unchanged. | `turtle.js:939-958` (`posRow`) |
| 5 | Margin-headroom-for-next-unit sentence on the crypto5× by-market row | **Partial.** The raw free-margin figure is visible (posted/free in the Vehicle cell, Phase C), but no sentence computes "N more typical-sized units would fit." Not attempted — sizing a hypothetical unit from the by-market row alone risked exactly the kind of guess Phase D's own DO-NOT list warns against (a wrong number is worse than none). Left as a real, well-scoped item for a future pass. | `turtle.js:1061-1066` |
| 6 | next-add / next-stop columns on BOOK's open positions | **Done, Phase D — without the engine dependency the original item assumed.** The ranked-ten entry said this "requires `turtle_book.py` to start persisting `next_add`... it doesn't today." Built instead entirely client-side from fields already on the row (`last_fill`, `n`, `side`, `fills.length`) — Turtle's own published 0.5N-per-add rule, never a call into engine math. Shared by both BOOK's table and the SIGNALS-view detail grid via one function so the two views can't quote different numbers. | `nextAddStr`, `turtle.js:496-510` |
| 7 | Permanent fence test: Turtle can never write MY NAMES | **Done, Phase B.** Was true by inspection only; now a permanent test targeting the actual mechanism (`window.PM.watch`, the `gbs:manual_journal` key) every other lens uses to star a name — the pre-existing "no localStorage" ban would not have caught a future regression through that API. | `test/turtle.test.js:347` |
| 8 | Correlation-bucket headroom readout (all bucket types, all markets) | **Partial.** Phase C's by-market note surfaces close-corr specifically for the levered sleeve ("6/6 crypto units already held"), derived from the skip rows, not hardcoded — but there is no readout across `direction_cap`/`loose_corr_cap`/`per_market_cap` for every market. Scoped down deliberately: the money story tonight was close-corr on crypto5×; a full utilization readout is real future work, not squeezed in. | `capBind`, `turtle.js:1046-1086` |
| 9 | Skip-board dedup by symbol × reason with a repeat count | **Done, Phase C.** Deduped by symbol×reason×action with a count; re-sorted by ascending reason rarity, which turned out to be the actual readability fix tonight (zero real duplicates exist yet — the raw `slice(0,40)` was burying the 12 close-corr rows under 40 consecutive ASX cash rows by ORDER, not volume). | `turtle.js:1150-1165` |
| 10 | Surface `roll_suspect` more prominently on futures | **Not done — correctly blocked on item 1.** Futures is still 0/0; nothing to surface. | — |

**Net: 6 of 10 fully done tonight (2, 3, 4, 6, 7, 9), 2 partial (5, 8), 2
correctly untouched pending the owner (1, 10).**

## 9. Beyond the ranked list

Two things Phase C built that aren't on either the Grok-ten or the
owner's-ten:

- **Coin/share quantity as its own column** (`qtyStr`, `turtle.js:937`,
  wired into `posRow`). Not a ranked-ten item — it came out of Phase A's
  own display-honesty investigation (the brief's flagged risk that BOOK
  might be labelling coin quantity AS Turtle units). That risk turned out
  not to exist in shipped code (both existing renderers already used
  `fills.length` correctly) — but the investigation surfaced a real gap:
  quantity itself was nowhere on the table, only recoverable by dividing
  `cost_basis` by an unlabelled number in a different view. UNI is the
  sharpest example: 213.6562 UNI is 1 Turtle unit, and the page now says
  both, in two labelled columns, instead of neither.
- **`capSkipBadgeHTML`** (`turtle.js:557-571`, called from `rowHTML`) — a
  chip on a SIGNALS row when that specific name was skipped on its levered
  sibling sleeve for `close_corr_cap`. Narrower than ranked-ten item 8 (one
  symbol, one reason, not a full bucket readout) but live-verified doing
  real work tonight: ZEC on the crypto SIGNALS view shows both "5× margin"
  (it's open there) and "5× cap" (a further add was declined there) side
  by side, from the same generic `scanMarketFor` cross-reference the open-
  position jump already used.

## 10. What I refused

- Did not push, at any point, under any gate result.
- Did not retune `TURTLE_MAX_UNITS_CLOSE_CORR` (still 6) or raise it because
  5× filled it on day one — grepped clean in every phase's diff.
- Did not raise crypto5×'s or any sleeve's equity to make a unit fit.
- Did not add a 4-hour Donchian, a 5th market button, or fetch
  `data/crypto5x_turtle.json` anywhere.
- Did not invent a futures margin file, a roll number, or a margin schema.
- Did not touch `nav.js`, `scanner/broker/`, `universe.py`, or any
  `config.py` NUMBER.
- Did not flatten `journal/` or reset a data commit; every rebase was
  checked for zero file overlap before it ran.
- Did not write a fake `posted_want` onto a skip row to make item 3 above
  easier — checked the real field name against real data first (§8, item
  3) and built around what's actually published.
- Did not attempt ranked-ten items 5 or 8 in full — both would have
  required either a guessed sizing computation or engine changes outside
  this pass's UI-only scope; left as real, correctly-scoped future items
  rather than rushed or faked.
- Did not run the Lighthouse / screenshot-diff / mobile-screenshot-matrix
  e2e steps locally (documented in the Phase E1 commit) — they depend on a
  GitHub Actions cache with no meaningful local equivalent. Did run the
  full `python -m pytest -q`, the full 23-suite JS battery, and the two
  self-contained e2e suites (smoke, hang-probe) — all clean.

## 11. Diffstat, this whole pass (Phase A → E1)

```
$ git diff --stat 585a6ab..HEAD
 public/chart.html                          |   2 +-
 public/js/chart.js                         |  16 +-
 public/js/turtle.js                        | 290 +++++++++++++++++++++++++----
 public/turtle.html                         |   2 +-
 public/version.json                        |   2 +-
 reviews/2026-08-23-turtle-phaseA-verify.md |  72 +++++++
 test/turtle.test.js                        | 221 ++++++++++++++++++++++
 7 files changed, 563 insertions(+), 42 deletions(-)
```

Turtle-namespaced (`turtle.js`, `turtle.html`) ± `chart.js`/`chart.html`
(the Phase B back-link, explicitly in scope) ± `test/turtle.test.js` ±
`version.json` ± one `reviews/` doc. No `scanner/`, `scanner/broker/`,
`universe.py`, `config.py` number, `nav.js`, or `journal/` file anywhere
in it. This document adds one more markdown file on top.

## 12. Push status

**NOT PUSHED.** Waiting for "upload it."

---

*THEN STOP. The night is over. Do not push. Do not start a Phase F.*
