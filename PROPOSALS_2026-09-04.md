# Post-freeze proposals — for the Sep 4, 2026 checkpoint

Fifteen decisions, each with its evidence, options and a recommendation.
**Nothing in this file has been deployed.** Every item below would change what
gets traded, sized, displayed as opportunity, or measured — which makes each
one the owner's call, per the w3-1 freeze rule ("where a conclusion would
change live trading, the deliverable stops at the proposal"). Evidence
citations are to `EDGE_RESEARCH_2026-08-20.md` (sections §1–§7) and to the
live artefacts named inline. All of the evidence carries the same caveat: **~4
weeks of one rising-tape regime, 5-session horizons, in-sample.** Where a
proposal's evidence will have matured further by Sep 4, P13 says when to
re-read it.

How to read the recommendations: **DO** = the evidence is one-directional and
the change is cheap to reverse. **HOLD** = the instinct is wrong or the sample
is too thin; the proposal exists to stop a change, not start one. **DECIDE** =
two defensible answers; the trade-offs are laid out and the choice is genuinely
yours.

---

## P1 — Point the deck's entry-type tint at the long-only CANONICAL blocks. **DO**

**Problem** (§2, §5): the deck's reclaim chip is GREEN off
`vivek_backtest_longonly.json` (+0.178R, 10 years, generated Aug 1). The
canonical 5-year weekly file says reclaim **−0.096R**, and the live book's own
43 reclaim closes say **−0.153R** — 3.6 SE below the chip's claim. The two
files even rank the patterns differently (tint: reclaim ≫ retest > break;
canonical: break > reclaim > retest). Decomposed, the window/vintage gap
(+0.138R) drives more of the disagreement than the shorts-blending (+0.080R):
the tint's edge substantially lives in 2016–2021.

**What already shipped (data only, batch-100 WS-F)**: the canonical weekly
replay now publishes `by_entry_type_long`, `by_direction_entry_type` and
`by_timeframe_long` blocks — long-only numbers from the RIGHT window, in the
file `lens_backtest.yml` refreshes weekly. The evidence the tint should read
now exists on every run. What was deliberately NOT touched (per the standing
instruction): `loadEntryQuality()` still reads the longonly file.

**The change**: one edit — point `loadEntryQuality()` at
`vivek_backtest.json`'s `by_entry_type_long` block. Optionally retire
`vivek_backtest.yml` (monthly, longonly) afterwards or keep it as a
long-window reference clearly labelled as such.

**Consequence to expect**: the reclaim chip goes AMBER/RED (long-only 5y
reclaim is ~breakeven-to-negative). That is not a bug; that is the point. The
bot trades reclaim almost exclusively, so the deck will stop telling you its
main pattern is its best one while the live book votes otherwise.

**Effort**: ~1 hour incl. tests. **Reversible**: fully.

---

## P2 — A 1D entry-quality gate: three variants. **DECIDE**

**Problem** (§3): the rules-side bleed is ONE cell. All 7 full stop-outs were
1D-timeframe entries (binomial ~0.4% if stops were level-tf-neutral); 3 of 7
never ticked positive (MFE 0.0R), the rest peaked ≤ +0.29R. Live timeframe
split across all 45 closes: 1D **−6.82R** (n=20), 1W **+0.88R** (n=20), 3D
−0.94R (n=5). No 1W entry has ever hit a full stop. This is entry quality on
the H4-proxy level, not exit tuning — no stop width rescues an MFE-zero trade.

**Variants**, in increasing severity:

| | change | mechanism | expected effect | risk |
|---|---|---|---|---|
| **2a** | 1D confirmation requirement | 1D plans only armed after a second consecutive qualifying scan (an arming-hysteresis, config constant) | trims the wrong-from-entry cohort; keeps 1D exposure | fewer 1D entries; may lag genuine moves by a session |
| **2b** | tighten the 1D grade floor | bot takes 1D entries only at a score above the A+ cutoff (e.g. ≥9) | cheap; keyed to existing machinery | §6 says score digits are noise at 5s — the floor may select nothing real |
| **2c** | drop 1D from bot eligibility | `VIVEK_BOT_LEVEL_TF_ALLOW` excludes the 1D/H4 proxy | removes the entire measured bleed (−9.05R of stops) | halves the entry surface; 1D is also where 3 of the time-stop's +2.14R harvest came from; one regime of evidence |

**Recommendation**: 2c is what the current numbers support, but on 7 stops
from one regime it is aggressive. A defensible middle: run **2a** live from
Sep 4 while the w3-2 cycle accumulates a second regime of 1D evidence, with 2c
pre-registered as the action if the 1D cohort is still net-negative at the
next 30-close readout. **Do not** loosen stops or shorten the time-stop in
response to this cell (see P11) — the evidence points away from both.

**Effort**: 2b/2c are config-level; 2a needs a small state file (same shape as
grade hysteresis). All three touch ringfenced `broker/` files → owner-present
change only.

---

## P3 — Short-side display honesty. **DECIDE**

**Problem** (§7): the short signal has been ANTI-predictive this window —
signed excess over the median name **−1.56%/5s** (ASX, n=237) and −0.96%
(NASDAQ, n=243). This is after removing the tide, so it is not "shorts fight a
rising tape" — the selection itself inverted. Meanwhile the deck displays
shorts as opportunity with identical visual weight to longs, and ~65% of
confluence alerts are shorts. The bot is protected (`allow_shorts: false`);
your attention is not.

**Options**:
- **3a** — a standing regime chip on short rows ("short signal measuring
  inverted since Jul-26 — see edge report"), driven by the now-daily
  `edge_summary.json` short-side numbers, so it appears and DISAPPEARS on
  evidence rather than by edict.
- **3b** — dim shorts the way products are dimmed (`is_product` pattern),
  regime-gated as in 3a.
- **3c** — a longs-first default sort with shorts intact.
- **3d** — nothing visual; rely on the weekly Discord digest carrying the
  short-side number.

**Recommendation**: 3a. It is honest in both directions — if the short side
un-inverts in a down-tape (untested and untestable from this window, said
plainly in §7), the chip clears itself. 3b encodes today's regime as a
permanent judgement; 3d spends the finding on a channel glanced weekly while
the deck is read daily.

**Effort**: 3a ~half a day (app.js reads edge_summary.json short block +
threshold constant in config). Display-only; no broker/ files.

---

## P4 — Retire or demote the 🎯 High-conviction badge. **DO** (demote), **DECIDE** (retire)

**Evidence** (§6): tagged names underperform untagged at 5 sessions — all:
−0.62% (n=170, 41% win) vs +0.12% (n=1,525); longs-only: +0.36% (n=107) vs
**+1.44%** (n=813), ~1.6 SE and the same direction as two independent
measurements (§1 aligned longs +0.06 vs unaligned +1.58; §2 live reclaim
−0.15R). Three lines of evidence now agree: **the weekly-reclaim cell the
badge celebrates is not where the current edge is.** The fairness caveat is
real (the badge claims full-trade merit; this is a 5-session test) — but
nothing measurable today supports the visual weight it gets.

**Recommendation**: demote now — strip the emoji-weight styling to a plain
quiet tag so the deck stops actively steering attention toward the measured
underperformer; keep computing it so the ledger keeps scoring it (the roster
baseline already records `high_conviction` per row — the scoring is free from
here). Pre-register retirement at the P13 Sep-23 checkpoint if the 20-session
numbers agree with the 5-session ones. Retiring outright today on ~1.6 SE
would be doing to the badge what the badge did to the evidence.

**Effort**: CSS + one template line. Display-only.

---

## P5 — De-emphasise the within-grade score digits. **DO**

**Evidence** (§6): within grade A+, Spearman ρ = **+0.012** (n=795) against
5-session forward returns. Buckets: score 8 → −0.17%, score 9 → +0.35%, score
10 → **−0.75%, 42% win** (n=111). Not merely flat — non-monotonic, with the
top score the worst bucket. The 8-vs-10 distinction the deck renders carries
no measurable information at this horizon.

**Recommendation**: keep the score in the payload and the tooltips (it is the
grade's own arithmetic and the audit trail needs it); stop rendering it as a
headline discriminator on the row (smaller, muted, no sort-by-score default).
Do NOT remove it from grading itself — that would be a signal change, and
nothing here says the score fails at the horizons grading targets; it says the
DISPLAYED precision is decoration at 5 sessions.

**Effort**: display-only, ~an hour.

---

## P6 — Reposition the ⨂ aligned badge: it is a SHORT-side tool. **DECIDE**

**Evidence** (§1): in aggregate the badge adds nothing (aligned +0.18% vs
unaligned A+ +0.12%, difference 0.06pp on ~0.37pp SE). The interaction is the
finding: alignment NEUTRALISES both directions — aligned shorts +0.25% vs
unaligned shorts **−1.78%** (~4 SE apart), aligned longs +0.06% vs unaligned
longs **+1.58%** (~2.5 SE). PhaseMap agreement reads as a filter against
trending continuation: it rescues shorts and it COSTS longs.

**Options**:
- **6a** — direction-aware badge: keep ⨂ prominent on shorts ("aligned —
  historically the shorts that don't bleed"), mute it on longs.
- **6b** — leave the deck alone; encode the interaction in the weekly digest
  and re-decide at n≈250 aligned longs.

**Recommendation**: 6b for the badge itself (n=111 aligned longs is a strong
hypothesis, not law — §1's own words), BUT stop any further build-out that
treats alignment as generic extra conviction (banners, pings, ranking weight)
until the interaction is confirmed or dead. The confluence Discord pings
already exist and are dedup-gated; they can stand. The Eyes strip ranking
(count → grade) is unaffected either way.

---

## P7 — Concentration on the sheet: name the crypto share of the paper profit. **DO**

**Evidence** (§4): +8.65R unrealized at analysis time; crypto = 3 positions =
**+4.09R (47%)**; Materials 3 = +2.13R (25%); six positions carry ~72%. The
tide arithmetic is now published daily (`book_stress.json`: −3% uniform →
+3.7R with 0 stop-outs; −5% → ~0R) and the journal's tide line renders it. What
is NOT yet stated anywhere is the **name-concentration** of the headline: the
+8.65R reads as breadth of skill and is mostly three crypto marks plus tide.

**Proposal**: one row on the status sheet + one line on the journal tide
strip: "top 3 positions carry N% of unrealized R (crypto M%)". Computed
client-side from the book the pages already load — no new fetch, no engine
change. **The cap discussion that follows from it** (a per-asset-class
unrealized-concentration note, or an actual crypto slot sub-cap) is a trade
change: flag-only, same style as the review flags — if wanted, spec it after
the display has run for a fortnight.

**Effort**: display half ~half a day. Cap half: owner decision first.

---

## P8 — Backfill `sector` onto CLOSED book rows. **DO, after Sep 4**

**Problem** (§3): the rules-side stop-out cohort carries no sector field —
those rows closed before the 2026-07-28 enrichment, so sector-conditioning the
bleed (was it one sector's tape?) is impossible today. Analysis said so
plainly rather than approximating.

**Proposal**: one idempotent script (resize_book_notional.py pattern: dry by
default, frozen-field verification, `--apply` gate) that writes `sector` onto
closed rows only, sourced universe-first (the only full-coverage source, per
the CLAUDE.md three-source order), cache second, never overwriting a non-blank
field. Closed rows are outside every guard and every decision path — but they
are INSIDE the w3-1 record, and the freeze says do not modify w3-1-tagged
rows. A metadata-only backfill almost certainly honours the freeze's intent —
but "almost certainly" is exactly what the freeze exists to not rely on.

**Recommendation**: ship the script now if convenient, run `--apply` only
after Sep 4. Zero urgency; the payoff is that the NEXT bleed analysis can
condition on sector.

**Effort**: ~half a day incl. tests.

---

## P9 — The FX sizing fix (#61): state of play, restated with current numbers. **DECIDE**

**The standing fact** (CLAUDE.md Tier 4 §61): `VIVEK_BOT_POSITION_NOTIONAL =
5000` is currency-less. ASX positions are sized as **A$5,000 ≈ US$3,485** (at
0.6969) while NASDAQ positions are US$5,000 — every ASX position is ~30%
smaller than intended, and has been since the resize. The same face-value
mixing sits in the $150k portfolio ceiling, the daily/weekly guard
accumulation, and the review-flag threshold (ASX under-flags). The fix is one
line (divide by `_fx_of(market)` before sizing) in the ringfenced
`vivek_bot.py`, and it makes every FUTURE ASX position ~43% larger in units.
The front-end twin (`dollarsPerPoint` fallback of 1 for bare ASX tickers,
~43% overstated) is recorded with provenance and is live-inert only while
positions exist that its page doesn't size.

**Why it is here again**: it interacts with the w3-1 readout. If the fix lands
mid-sample, the ASX legs of the cohort change size regime mid-experiment —
the exact mixture the 2026-07-28 resize was run to end. R is size-invariant,
so the R record survives; the dollar record splits again.

**Options**: (a) fix at the w3-1 boundary (Sep 4, with the cycle readout) and
accept a clean new regime for w3-2; (b) fix immediately after the 30-close
readout whenever that lands; (c) leave as-is and re-declare the intended ASX
notional as A$5,000 (i.e. the current behaviour, made deliberate — then the
guards' mixed-currency sums still need the one-line fix or an explicit
waiver).

**Recommendation**: (a). One boundary, both changes (sizing + guard
accumulation), one regime stamp (`sizing_mode` already records regimes —
worth adding an `fx` note to the row at the same time).

---

## P10 — The risk_manager wiring gap: a decision matrix, not a default. **DECIDE**

**The standing fact** (CLAUDE.md Tier 1 §16): every consumer of
`risk_manager` (pre_trade_check, circuit_breaker, scaling_advisor,
performance_report) is handed the SCALP journal. The bot book — the only track
record — is guarded by NONE of: portfolio heat (7%), the drawdown breaker, the
consecutive-loss breaker. `scripts/health_check.py` reports what those guards
WOULD say, without arming them. The guards that ARE live on the book: daily +
weekly loss guards, 30-slot / $150k / per-symbol / per-market-sector caps,
kill-switch loss check.

**The matrix** — each guard separately, because "wire it all up" is how a
system acquires two overlapping breakers that disagree:

| guard | what it adds over the live guards | overlap/conflict | recommendation |
|---|---|---|---|
| portfolio heat (7% of equity at risk) | a book-wide open-risk ceiling; the resize took open risk to ~15.7% of equity, so **it would currently be BREACHED at arming** | none of the live guards read open risk book-wide | arm REPORT-first (health_check already prints it); decide the number knowing 7% blocks all new entries today |
| drawdown breaker | halts on peak-to-trough equity | overlaps weekly loss guard in intent, different measurement | HOLD until the dollar series is single-regime (see P9); R-based version worth specifying instead |
| consecutive-loss breaker | halts after N straight losers | "consecutive" on the bot book means file order across 3 markets (documented, not fixed) | fix the ordering definition BEFORE arming, or it fires on an artefact |

**Recommendation**: nothing arms by default. If any of it arms on Sep 4, arm
portfolio heat only, at a number chosen with the 15.7% fact on the table —
arming a 7% cap against a 15.7% book means choosing to freeze new entries
until attrition, which may even be wanted, but should be chosen, not
discovered.

---

## P11 — DEFENSE of the 28-day time-stop. **HOLD — do not "fix" it**

**Evidence** (§3): the time-stop is the rules' one WORKING exit — **+2.14R
over 11 exits**, harvesting modest winners and scratches, while full stops did
−9.05R and the single trail exit −0.06R. The 1W cohort's only mechanical exits
are time-stops (+0.38R over 7). The intuitive post-freeze move — "28 days is
too slow, tighten it" — aims at the only mechanism with a positive ledger.

**Proposal**: none. This item exists to pre-empt one. Any shortening proposal
should have to beat the recorded +2.14R with more than intuition — i.e. a
replay showing the same 11 exits at 14/21 days net MORE than +2.14R, plus the
counterfactual on the still-open stalled cohort. Until that analysis exists,
the time-stop stands.

---

## P12 — Trail/target evaluation: pre-registered, not yet due. **HOLD**

**Evidence**: n=1 trail exit (−0.06R) and 3 gated closes total at the last
readout — nothing about trailing, TP laddering (the 0.90 ladder + 10% runner)
or breakeven moves is testable on the live sample yet. The excursion fields
(MFE/MAE now surfaced per row, `mfe_zero_rate` now in the backtest blocks)
are the inputs a real evaluation needs, and they are accumulating.

**Pre-registration** (so the future analysis is honest): at 30 rules-side
closes, compute (a) R left on the table by tp1-at-0.25 vs holding to the
time-stop, (b) how often the trailed stop converted a winner to a scratch
(MFE ≥ +1R, exit ≤ +0.2R), (c) the breakeven-move's save rate. Decide trail
tuning THEN, on those three numbers, not before.

---

## P13 — Review checkpoints for the maturing evidence. **DO (calendar entries)**

The ledger's longer horizons were empty at analysis time (10-session n=3,
20-session n=0). They mature on their own — the checkpoints just need to be
kept:

- **Sep 9** — the bulk of the August alignments have matured 10-session
  returns. Re-read §1's aligned-vs-A+ and the short-side inversion at 10s
  (`python scripts/alert_edge_report.py --baseline`, or the committed
  `edge_summary.json` history).
- **Sep 23** — first meaningful 20-session cohort. This is where P4's
  "full-trade merit" caveat gets its answer: if High-conviction and the
  aligned-longs penalty hold at 20 sessions, the 5-session findings stop being
  horizon artefacts.
- **The w3-1 readout itself** stays what the freeze pre-registered: the first
  mechanical exits landing the week of Sep 4, judged at 30 closes, rules vs
  owner split (already surfaced on deck + journal + status sheet).

The Sunday Discord digest (live as of this batch) carries the headline numbers
weekly either way; these two dates are the ones where NEW horizons unlock
rather than the same numbers re-averaging.

---

## P14 — Backtest `limit: 60` → full universe. **DO, with its cost stated**

**The standing fact** (TOP100 #58, restated in §5): both backtest files run 60
symbols per market — every per-pattern claim, including the tint P1 repoints,
rests on **~4% of the universe the bot trades**. The #58 fix moved the NASDAQ
list off the 99-name CSV, but the cap stands.

**Cost, measured from the live job**: the weekly lens_backtest replay at
limit 60 fits comfortably in its runner window. The full ASX+NASDAQ universe
is ~3,600 names — naively ~60× the frame-fetch and replay work. With the #73
supertrend speedup (192s → 7.6s per universe per indicator) the ENGINE cost is
tractable; the binding constraint is Yahoo fetch volume + runner wall-clock
(hours, not minutes). Options: (a) full universe monthly, limit-60 weekly
(trend vs level split); (b) a stratified 600-name sample weekly (10× evidence,
~10× cost, still one runner-hour); (c) full universe once, now, as a one-off
calibration to measure how much the 60-name numbers actually drift.

**Recommendation**: (c) first — it converts "4% might be biased" into a
measured delta for one runner-afternoon, and THAT number decides whether (a)
or (b) is worth a standing cost. If the 60-name expectancies hold within ~1 SE
of the full run, the cap is a fine economy and the caveat retires.

---

## P15 — Breadth-conditioned entry throttle: measure first, gate later. **DECIDE (measure half: DO)**

**Evidence** (§4): the book's daily mark moves carry breadth beta 0.36–0.41%
per 1.00pp of above-200-day share, corr 0.67 (ASX) / 0.50 (NASDAQ); an
ordinary breadth reversion to the 6-month mean costs ~58% of the current paper
profit without a single stop-out. Both markets sit stretched (NASDAQ 67% vs
59% mean; ASX 47.5% vs 37.7%) — and the regime page now renders exactly that
stretch percentile (batch-100 WS-E). The system currently takes entries at the
same rate regardless.

**The measure half (report-only, freeze-safe, DO)**: stamp the market's
breadth percentile onto each book row at entry (`breadth_at_entry` — the
enrichment pattern: blank-only, frozen once written; the ledger's `enrich()`
already stamps it on alert rows). After a regime turn, the question "do
entries taken above p90 breadth underperform entries taken at p50?" answers
itself from the book, the same way the review-flag question does.

**The gate half (HOLD until the measure half has a down-tape in it)**: any of
— reduced new-entry rate above p90, a stretched-breadth review flag (NOTICE,
not a block, the P-flags pattern), or nothing. Choosing a gate today would be
fitting to one regime's 22 days — the exact move this batch's every section
warns against.

---

## The one-paragraph version

Repoint the tint at the long-only canonical blocks the backtest now publishes
(P1), quiet the two decorations the evidence failed (P4, P5), and put a
regime-gated honesty chip on the inverted short side (P3). Decide the 1D
question deliberately (P2 — the whole realized bleed lives there), at the same
boundary where the FX sizing regime is cleanest to fix (P9). Defend the
time-stop (P11), leave the trail alone until its pre-registered sample exists
(P12), and let P13's two dates tell you when the longer-horizon evidence is
in. Measure breadth-at-entry now so the throttle question (P15) and the
concentration question (P7) are answerable from the book's own rows by the
time a down-tape asks them. Run the full-universe backtest once (P14) so the
4%-evidence caveat either retires or becomes a number. Nothing here needs to
land before Sep 4, and none of it should land without you.
