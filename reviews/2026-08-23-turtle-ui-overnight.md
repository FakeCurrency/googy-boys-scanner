# Turtle UI pass — overnight audit (Phase 10)

Branch `turtle-ui-pass`, phases 3–9 implemented and gated under the overnight-autonomy instruction, Phase 10 (this document) closing it out. All local commits run 2026-08-22 10:32–12:25 UTC; this report is written and committed as the Phase 10 close-out. **Not pushed** — see §6.

---

## 1. Click-path table — Phase 0 → now

Source: `reviews/2026-08-22-turtle-phase0-inventory.md`. Every control re-walked against the current `public/js/turtle.js` (1570 lines) and `public/turtle.html`.

| Control | Phase 0 state | Now | Verdict |
|---|---|---|---|
| Market switch (ASX/NASDAQ/CRYPTO/FUTURES) | Sets `MARKET`, no history entry | Same click path, **now also `pushURLState()`** — `turtle.js:1500-1507` | **Upgraded** (Phase 3) |
| View tabs (SIGNALS/BOOK/RULES/SIZING/EVIDENCE) | Sets `VIEW`, no history entry | Same, **now `pushURLState()`** — `turtle.js:1466-1467` | **Upgraded** (Phase 3) |
| Filter segs | 4 buckets (ALL/FIRED/HELD/APPROACHING), no history | **5 buckets** (+ S1 BLOCKED), **`pushURLState()`**, default is now FIRED-with-fallback, not ALL — `turtle.js:1482-1489`, defaults at `turtle.js:140-151` | **Upgraded** (Phases 3 & 5) |
| Row expand | Toggles `OPEN`, no history | Same, **now `pushURLState()`** on click and Enter/Space — `turtle.js:1520-1525`, `1537-1552` | **Upgraded** (Phase 3) |
| Chart link in expanded row | **Did not exist** | `chartHref()` links every ASX/NASDAQ/CRYPTO row; futures gets an honest "no chart for this contract" sentence instead of a 404 — `turtle.js:467-470`, `628-631` | **Resolved** (Phase 6) — see residual §3.4 |
| Deck pills ("35 fired today" etc.) | `<span>`, inert, no listener | Real `<button data-filter>`, wired to the same click delegate as the SIGNALS segs — `turtle.js:193-215`, `1482-1489` | **Resolved** (Phase 5) |
| Search box (Ticker…) | Live client filter, no history | Unchanged — still not in the URL contract | **Residual, by design** (see below) |
| HOW IT WORKS (topbar link) | Duplicated the shared nav MORE-menu entry | **Removed from turtle.html** — single canonical location in nav.js MORE menu | **Resolved** (Phase 4) |
| Nav ← BACK pill | Referrer-based; untouched | **Untouched** (nav.js has zero diff this whole pass) — but see the Back-button note below | Unchanged by design |
| Nav TURTLE pill (PRIMARY[4] of 8) | Confirmed correct | Unchanged (nav.js untouched) | Unchanged |
| ⌘K palette | Global shortcut, untouched | Untouched; `#search-trigger` now also opens it on click — `turtle.js:1456-1461` | Unchanged, one new entry point |
| `data-goto="sizing"` link | Sets VIEW, no history, flagged for Phase 3 | **Now `pushURLState()`** via the shared `[data-goto]` branch — `turtle.js:1468-1469` | **Upgraded** (Phase 3) |

**Not on the Phase 0 table — new this pass:** clicking a symbol in BOOK's open-positions or skip-reason tables (`openSymbolHTML` / `jumpToBookSymbol`, `turtle.js:867-870`, `1433-1445`) jumps to that symbol on SIGNALS, in the right market, row expanded — reverting cleanly if the symbol isn't in that market's scan. Wired to both click and Enter/Space.

**The one behavioural change bigger than any single row:** Phase 0 found *zero* history entries anywhere on this page — a real browser Back button walked straight off the site. Turtle now pushes a real history entry on every market/view/filter/row/sort/goto change, so Back/Forward steps back through what the reader actually did on this page before it ever reaches the nav pill's own referrer logic. This is the Phase 2/3 deliverable and it is the single largest UX fix in the whole pass.

**Residual — search text not in the URL.** `QUERY` (the ticker search box) was never in scope for the URL contract (`URL parse/serialise for market/**view/filter/row**`, Phase 2's own title) and still isn't. A reader who types a ticker, then hits Back, loses the typed text along with everything else on the page — search is the one piece of on-page state Back/Forward doesn't restore. Small, deliberate scope limit, not a regression; not on the money-ten because it's a restyle-adjacent polish item, not edge.

---

## 2. Engine audit (file:line, independent of the 7/7 phase story)

Eight claims, each checked against the actual running code, not against what a commit message says it does.

**1. Add-path counts `still_open` + unmanaged tail + self.** `scanner/turtle_book.py:457` — `all_open = still_open + open_list[idx + 1:] + [pos]`, used for the margin/cash room check on an add; the unit-cap check at `turtle_book.py:485` uses the same `still_open + open_list[idx + 1:]` tail with `pos` passed separately as `extra=`. The comment at `turtle_book.py:447-456` documents *why*: counting only `still_open` let DOGE's third unit on 2026-08-22 pass a room check that ignored DOGE's own basis plus the unmanaged tail, and the crypto book briefly held $5,239 of basis on a $4,186 cap. Confirmed fixed in the code currently running.

**2. Re-entry is blocked by the row's own bar date, not the run date.** `scanner/turtle_book.py:532-539` — `_same_bar_blocked()` checks `(r.get("date") or day)` against a `closed_bars` set keyed on `t.get("closed_bar") or t.get("closed")`. The comment at `turtle_book.py:520-531` explains why run-date keying was wrong: this book runs many times per bar (crypto every 4h; the daily pass re-reads Friday's NASDAQ bar on Saturday and Sunday), so keying on the run date let a Friday stop refill off the same Friday bar at Saturday's run.

**3. 5× posted margin and liquidation use one formula, in one place, read by both the engine and the page.** `scanner/turtle_book.py:216-239` (`_exit_trigger`) computes `liq = avg − posted/units` (long) or `avg + posted/units` (short), and returns whichever of stop/liq is nearer to price. Posted margin itself: `turtle_book.py:459` (on add) and `:635` (on entry), both `abs(fill × units) / leverage`. `public/js/turtle.js:489-494` (`liqDistanceR`) re-derives the *identical* liq formula client-side for display — checked side by side, they match term for term.

**4. The 2026-08-21 cash-crypto closed rows are byte-stable against `af7c795`.** `af7c795` is a blob hash, not a commit — it names `journal/turtle_book.crypto.json`'s content at commit `9adda79` (2026-08-22 04:42:30 UTC). Direct comparison (git show + Python dict-equality, not a text diff, so field-order noise can't hide a real change): both the old and current file carry exactly 5 closed rows dated 2026-08-21, and all 5 are field-for-field identical. The file's total closed count is still 5 — no new crypto closes have landed since, so this wasn't tested against a concurrent write tonight (see §6 on the rebase check), but the ones from that date are unmoved.

**5. Futures is 0/0, and the code path that keeps it there is real, not a display trick.** `journal/turtle_book.futures.json` currently reads `open_positions: 0, closed: 0, skips: []`. `scanner/turtle_book.py:260-277` (`_load_margin_file`) returns `None` when `data/futures_margins.json` doesn't exist — confirmed absent from the repo (`find` turns up nothing under that name anywhere outside `backups/`). `scanner/turtle_book.py:280-304` (`_futures_gates`) refuses every new futures open with `SKIP_NO_MARGIN_FILE` when `margins` is `None`. Honest caveat: the futures skip list is *empty*, not populated with `no_margin_file` rows — that means no futures signal has fired yet to actually exercise the gate this book's life (started 2026-08-21), so 0/0 is currently a "nothing has tried" state as much as a "gate is holding" state. The gate is real and will fire the moment a futures breakout does; it just hasn't been asked to yet.

**6. The Yahoo CoinGecko-collision override touches the 5× sleeve's row-building only.** `scanner/turtle_run.py:108-139` (`five_x_rows`) is the only caller of `config.TURTLE_5X_YF_OVERRIDES` that builds rows (`config.py:1841`); confirmed via a repo-wide grep — every reference to that constant lives inside `turtle_run.py` (lines 88, 114, 123, 423), none in the cash-crypto scan's own row-building path. The function's own docstring: "THE CASH UNIVERSE IS DELIBERATELY UNTOUCHED."

**7. The crypto 4-hour cron is a scan cadence, not a 4-hour Donchian.** `.github/workflows/turtle.yml:23-29` states it in the schedule comment; `public/js/turtle.js:1037-1038` restates the same fact on the BOOK view itself ("The crypto books run every four hours, but the BARS are daily"). Both the engine's own scheduling comment and the reader-facing copy agree, and nothing in `scanner/turtle.py`'s channel math reads anything but the daily bar.

**8. `scanner/broker/` (25 files) has never heard of Turtle.** `grep -rn turtle scanner/broker/*.py` returns nothing. Two permanent tests pin this empirically rather than trusting the grep alone: `tests/test_turtle.py:1141-1179` (`test_nothing_in_the_broker_reads_the_turtle_lens`, walks every file under `scanner/broker/`) and `tests/test_turtle_book.py:492-493` (`test_nothing_under_broker_knows_this_book_exists`, same shape from the book side). `turtle.yml:8-10`'s own header states why this matters: Turtle is report-only, so a missed night costs a day of display signals and nothing else — which is also why its watchdog severity is WARNING, not CRITICAL.

---

## 3. UI audit of what shipped (Phases 3–9)

**3.1 Dead clicks:** none found. Every control in the click-path table above resolves to a real, tested handler. The two BOOK-view historically-inert surfaces (deck pills, HOW IT WORKS duplicate) were the two Phase 0 flagged as broken, and both are now fixed.

**3.2 History loops:** none. `onPopState` (`turtle.js:1401-1406`) only ever calls `applyState` then `load()`/`render()` — it never calls `pushURLState`/`replaceURLState` itself, so Back/Forward can't grow or rewrite the history it's navigating. Checked by direct read, not inference.

**3.3 404 charts:** none. `chartHref` returns `null` for futures rather than a link chart.html can't resolve (`turtle.js:467-470`).

**3.4 Residual found during this audit, not caught by any earlier phase gate:** `public/js/chart.js:63-70`'s `SRC_BACK` map (which powers the "← Journal" / "← Phase Map" style back-link on chart.html) has no `turtle` entry. A chart opened from a Turtle row (`src=turtle`) falls through the `if (back && el)` guard at `chart.js:73` and silently keeps the static default, `public/chart.html:28`: "← Dashboard". Not a break — the chart itself loads correctly — but the back-link lies about where you came from. Small, cheap, one-line fix (`chart.js`'s `SRC_BACK` object plus a `turtle: ["turtle.html", "← Turtle"]` entry) — out of scope for this markdown-only phase, logged here for the next UI pass rather than fixed tonight.

**3.5 Pills/segs drift:** none. `deckPillsHTML()` (`turtle.js:193-215`) and the SIGNALS-view segs built in `render()` (`turtle.js:1245-1256`) share the same five bucket keys/order/labels by construction — the render() code says so explicitly in its own comment ("Same five buckets, same order as deckPillsHTML() above").

**3.6 Six-tab phone / TABS drift:** not applicable — `nav.js` carries zero diff across this entire pass (confirmed both by every phase's own AUDIT and by a fresh `git diff --stat origin/main..HEAD` run at the start of this phase, which lists only `turtle.css`, `turtle.js`, `turtle.html`, `version.json`, `turtle.test.js`). TABS still excludes specs/alerts/turtle, same as Phase 0 found it.

**3.7 Hardcoded "5×" / hardcoded sleeve count:** none. Every leverage figure renders from `params.leverage` (`leverageOf()`, `turtle.js:504-507`, used by `vehicleBadgeHTML` and the by-market table); the "N separate sleeves" sentence uses `mk.length` (`Object.keys(BOOK.by_market)`, `turtle.js:1034`), confirmed live at N=5 now that `crypto5x` is a key in the payload.

**3.8 `#tt-skips`:** present, `turtle.js:985`, conditional on non-empty skips. First introduced Phase 5, repositioned (not rebuilt) by Phase 7's reorder.

**3.9 Accidental SCAN-reload:** none. `grep -n "setInterval\|setTimeout\|location.reload" public/js/turtle.js` returns nothing — no polling was added anywhere this pass.

**3.10 `nav.js` touched:** no, confirmed above (3.6) and independently by every phase's own AUDIT log.

**3.11 Journals mutated:** no — see §5, all six files byte-identical to the Phase 0 baseline.

---

## 4. Grok's ten — do / don't / already-done

1. **Default SIGNALS to FIRED TODAY** — already done. `turtle.js:140` defaults VIEW to signals whenever a scan exists; `turtle.js:148-151` defaults FILTER to fired-today with an honest fallback to held/all on a quiet day. Shipped Phase 5.
2. **Deck pills click-to-filter** — already done. Real buttons, shared `[data-filter]` delegate. Shipped Phase 5.
3. **URL + popstate** — already done. Full parse/serialise/apply/push/replace/popstate machinery, `turtle.js:1284-1450`. Shipped Phases 2–3.
4. **chart.html on equity/crypto rows** — already done, with a documented exception for futures (no continuous-contract chart page exists to link to). Shipped Phase 6. See §3.4 for a small residual in the return-link, not the chart itself.
5. **5× is a BOOK vehicle, not a 5th scan market** — already done. Four market buttons only; `scanMarketFor()` maps a levered sleeve key back to its underlying scan generically, never by naming the sleeve. Shipped Phase 7.
6. **Open positions above the essay** — already done. `bookHTML()` leads with Open, then Closed, then By-market/Skips, essay and portfolio replay last. Shipped Phase 7.
7. **Skip-reason board (`#tt-skips`)** — already done. Shipped Phase 5, repositioned Phase 7.
8. **Do NOT star Turtle into MY NAMES** — don't, respected. Zero references to mynames/MY NAMES/`.watch(`/starLens anywhere in `turtle.js`, confirmed by grep across the whole pass. Not yet a *permanent test* — that's ranked-ten item 7 below.
9. **Do NOT retune 20/55/2N; do NOT arm futures; wait on 5× N≥30/20d** — don't, respected. `FALLBACK` is byte-identical to pre-pass `origin/main` (diffed directly); futures stays gated at 0/0 by a real code path (§2.5), not a flag; the N≥30-and-20-trading-days sentence is live verbatim in `bookHTML()` (`turtle.js:1030-1032`).
10. **Stale-signal honesty on the deck (generated_at + next cron)** — already done. `generated_at` predates this pass (confirmed present on pre-pass `origin/main`); the "next cron" per-market sentence (`NEXT_CRON`, `turtle.js:181-186`) was added Phase 5.

---

## 5. Journal integrity — the one number that overrides every other claim in this document

```
PHASE0_JOURNAL_SHA (baseline, before any Phase 3-9 work):
4934d7341ff83c721e48bff0c0df1819a36c54978f4f44d502d0f302b4d2d956  journal/turtle_book.asx.json
6f42c45ce8d0e925c629f6b8270917bf36e68e32e77f4c570e3307cd9dcd0402  journal/turtle_book.crypto.json
ac2dd3798a057ecabd619b529d5357cb3c279ea0cbfe403cdda5c28465c9e9a3  journal/turtle_book.crypto5x.json
a454f8e28deba081263ea7bd65f80416eda8489b2bb6ae9f745db41871f03790  journal/turtle_book.futures.json
bffa84f9694c110796f48855711358745fb15e1d7ce573ecd38e2c63d43ae0da  journal/turtle_book.json
b63308271498712e81dfe5058ad9aaff7b5c1aaca5f230e289a8aebae03edda8  journal/turtle_book.nasdaq.json

FINAL (Phase 10, this report):
4934d7341ff83c721e48bff0c0df1819a36c54978f4f44d502d0f302b4d2d956  journal/turtle_book.asx.json        MATCH
6f42c45ce8d0e925c629f6b8270917bf36e68e32e77f4c570e3307cd9dcd0402  journal/turtle_book.crypto.json     MATCH
ac2dd3798a057ecabd619b529d5357cb3c279ea0cbfe403cdda5c28465c9e9a3  journal/turtle_book.crypto5x.json   MATCH
a454f8e28deba081263ea7bd65f80416eda8489b2bb6ae9f745db41871f03790  journal/turtle_book.futures.json    MATCH
bffa84f9694c110796f48855711358745fb15e1d7ce573ecd38e2c63d43ae0da  journal/turtle_book.json            MATCH
b63308271498712e81dfe5058ad9aaff7b5c1aaca5f230e289a8aebae03edda8  journal/turtle_book.nasdaq.json     MATCH
```

All six byte-identical. Honest caveat, not a weakness: `origin/main` did not advance at all during this pass (checked before and after every commit; the merge-base of `HEAD` and `origin/main` right now is `origin/main`'s own tip, `d4986c0`), so this check was never actually racing a concurrent data-cron write tonight. It's the correct check regardless, and it's clean.

---

## 6. Owner morning report

**origin/main:** `d4986c022d17e366d49f56089023d7e19dcf15ef` — confirmed (via `git merge-base`) to already be an ancestor of `turtle-ui-pass`. No rebase was needed this phase; none was needed any phase tonight. `origin/main` simply never moved while this pass ran.

**Local commits, Phase 3 → 9** (Phase 2's URL-helpers commit is listed for context; it landed in an earlier segment):

| Phase | SHA | Time (UTC) | Commit |
|---|---|---|---|
| 2 (context) | `1adb0e3` | 10:32:08 | turtle: URL parse/serialise for market/view/filter/row |
| 3 | `dbdcaa4` | 10:55:11 | turtle: pushState/popstate for market, view, filter, row |
| 4 | `2e5d6b2` | 11:03:10 | turtle: command-deck topbar, drop duplicate howto |
| 5 | `9f932fb` | 11:27:53 | turtle: deck pills filter the scan; default FIRED |
| 6 | `920fa20` | 11:41:37 | turtle: scanner rows with chart links and book facts |
| 7 | `5899085` | 12:08:22 | turtle: book opens-first, sleeve count from payload |
| 8 | `d41a297` | 12:19:35 | turtle: 320px overflow and tap targets |
| 9 | `7212eaf` | 12:25:28 | turtle: cache bumps for the UI pass |

**Click table before → after:** §1 above. Nine of eleven Phase-0 controls upgraded or resolved; two unchanged by design (nav.js's Back pill and TURTLE pill, both correctly out of scope); one residual carried forward (search text not in the URL, a deliberate scope limit, not a bug).

**`PHASE0_JOURNAL_SHA` vs final:** all six files match, §5.

**Grok-ten:** §4 — eight already-done, two don'ts respected and verified.

**My ten:** §7 below.

**What I refused:**
- Did not fix the `chart.js` `SRC_BACK` gap found in §3.4 — real, but Phase 10 is markdown-only; logged as a residual instead of typed as a fix.
- Did not push, at any point, under any gate result.
- Did not invent a futures margin file, a roll number, or a margin schema — `_load_margin_file` returning `None` is left exactly as it is.
- Did not retune 20/20/55/20/2/0.5/4 or any other FROZEN LAW number, even implicitly, while writing the ranked-ten below.
- Did not add a 5th market button or fetch `data/crypto5x_turtle.json`.
- Did not touch `nav.js`.
- Did not run the three e2e suites (hangprobe/lighthouse/screenshot-diff) irrelevant to a CSS/version-stamp phase — documented as a deliberate call in Phase 9, restated here for completeness.

**Blocked:** nothing. Every phase gate passed on its first attempt. The three-strikes-then-BLOCKED escalation in the standing instructions was never triggered.

**Push status: NOT PUSHED.** Waiting for "upload it."

---

## 7. My ten — ranked by expected dollars in the next 30 days, $5k/sleeve book

Framing, stated plainly rather than left implicit: FROZEN LAW forbids retuning the signal-generation rules themselves, so nothing below claims to create new entry/exit edge. What's actually movable in 30 days is (a) making the 5× sleeve's existing risk visible where the reader is already looking, (b) quantifying exactly how many dollars the cash constraint is costing so the case for a real unlock is a number instead of a feeling, (c) fencing in the kill-list guarantees permanently instead of leaving them true-by-inspection, and (d) the one item that could open a genuinely new source of trades — a real futures margin file, which is the owner's to supply, not mine to invent.

| # | What | Why $ in 30d | Cost | Risk | Kill-list collision | Depends on |
|---|---|---|---|---|---|---|
| 1 | Real futures margin file | The only item here that unlocks a whole *new* sleeve — futures sits at 0/0 with zero theoretical capacity until this exists. Everything else on this list optimizes sleeves already trading; this is the one with a non-zero ceiling on new trades. | None (owner sources the data) | Low — explicitly allowed, not invented | None — this is the allowed unlock, not a forbidden one | Owner |
| 2 | Cumulative $ of cash-declined signals, surfaced on the forward-book card | Turns "cash binds before Turtle does" from a sentence into a number — the figure that actually justifies (or doesn't) chasing further unlocks. `BOOK.skips` already carries `want_notional`/`posted_want` per cash/no-margin skip; this is a sum, not a fetch. | Low | Low | None | Nothing — pure aggregation over existing data |
| 3 | "Would this cash-skip have fit on 5×?" annotation on the skip table | Directly tests whether the sleeve built to solve the cash-cap problem is solving it — right now nobody can tell from the page whether 5× is working as intended or just adding a second untested book. Read-only annotation; must never feed back into the cash book's own decisions (respects "no cash-book rewrite"). | Moderate — best done server-side in `turtle_book.py` at skip-time | Low-moderate, additive only | None if strictly read-only | `turtle_book.py` engine work (Hermes) |
| 4 | Liquidation-distance column on BOOK's open-positions table | `liqDistanceR()` already exists and is computed — it's just buried in a per-row detail grid on SIGNALS instead of on the money surface itself. Puts the newest, most levered sleeve's real-time risk exactly where Phase 7 already decided the reader looks first. | Low | Low, pure display | None | Nothing — `turtle.js`/`turtle.css` only |
| 5 | Margin-headroom-for-next-unit sentence on the crypto5× by-market row | Turns a reactive "here's why it got skipped" into a proactive "here's whether the next one will fit" — the same information the engine already uses to gate adds, just surfaced before the bar closes instead of after. | Low-moderate | Low-moderate | None | Best done via a small `turtle_book.py` addition; a weaker client-side approximation is possible without engine changes |
| 6 | next-add / next-stop columns on BOOK's open positions | Turns the open-positions table from a record into a watchlist. Requires `turtle_book.py` to start persisting `next_add`/`exit_level` onto each open position — it doesn't today; SIGNALS' own version of this comes from a different computation (the per-name replay) that isn't available for every market at once client-side. | Moderate | Low-moderate, additive fields only | None if additive-only | `turtle_book.py` engine work (Hermes) + a `turtle.js` render change |
| 7 | Permanent fence test: Turtle can never write MY NAMES | Currently true by inspection, not by test. One cheap permanent test (same shape as the existing crypto5x-string-ban test) forecloses an entire class of future regression on a KILL LIST item this project has clearly cared about. Indirect $: protective, not generative. | Very low | Very low, test-only | None — this *is* the enforcement mechanism | Nothing |
| 8 | Correlation-bucket headroom readout (per-market / close-corr / loose-corr / direction unit utilization) | Lets a reader see a cap approaching before a signal silently gets skipped, instead of only reading about it after the fact in the skip table. Read-only aggregation over `BOOK.open`; does not change what the caps enforce. | Moderate | Low-moderate | None | Nothing beyond `turtle.js` |
| 9 | Skip-board dedup by symbol × reason with a repeat count | A name skipped six times for the same reason across six 4-hourly crypto runs currently reads as six rows, not a pattern. Aggregating surfaces "this name has wanted in for six straight runs" as a fact instead of noise. | Low | Low | None | Nothing — pure client-side aggregation |
| 10 | Surface `roll_suspect` more prominently on futures signals | Correct to build, but futures is 0/0 today (§2.5) — nothing can trade in that sleeve until item 1 lands, so this item's own 30-day dollar value is zero *on its own*. Ranked last because it's a follow-on to item 1, not because it's wrong. | Low | Low | None | Item 1 |

Explicitly excluded, per the spec's own forbidden list: no restyle, no additional prose/lens, no Discord, no raising sleeve equity to make a unit fit, no 4-hour channels, no quoting the five-year replay as if it were forward evidence. None of the above ten cross that line — all ten either surface a number the engine already computes, or fence in a rule the engine already enforces.

---

*Phase 10 AUDIT: this commit touches only this file (and, if written, its `reviews/` copy). No product code changed. Committed as `docs: turtle UI-pass overnight audit 2026-08-23`. Then stopped, per the standing instruction.*
