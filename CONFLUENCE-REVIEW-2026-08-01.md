# Confluence Quality & Decision-Surface Effectiveness — 2026-08-01

*(Saturday deep work, owner-ordered. Read-only at `5007cfc2`, computed by
replicating the SHIPPED confluence logic exactly — `loadConfluence` in
phasemap-shared.js: VIVEK contributes every published row by its `dir`,
PhaseMap contributes only states SWEPT/DISPLACED/RUNNING, Specs always
long; a name qualifies at ≥2 lenses on its majority side. No
recommendations. Friday-close data; Monday re-grades everything.)*

---

## 1. Current confluence reality

**101 aligned multi-lens names: ASX 55, NASDAQ 44, crypto 2. Every one is
a dual. Triples visible right now: ZERO, in any market.** The system's
loudest event does not currently exist on the board — and in the entire
14-day alert history only one ticker (PGO) has ever printed one.

- **Every aligned pair is VIVEK + PHASEMAP.** Specs contributes zero legs
  today: its 10 sub-50¢ names don't intersect the other lenses' actives.
  The "third lens" is structurally absent from current confluence.
- **Opposed co-presence outnumbers alignment: 158 names** (71 ASX, 81
  NASDAQ, 6 crypto) have two lenses active in OPPOSITE directions and
  are correctly excluded. The aligned set is the minority case — the
  filter is doing real work.
- By displayed VIVEK grade among the 101: **A+ 27** (17 ASX / 9 NASDAQ /
  1 crypto), A 32, B+ 41, WATCH 1. Displayed grade equals `grade_raw`
  on all 27 A+ today, so the chip's honesty caveat (smoothed vs raw) is
  currently moot.
- **Top of WHAT NEEDS MY EYES right now, by its real rule** (count desc →
  A+ flag → alphabetical): with every name tied at count 2, the order
  inside the A+ tier is **literally alphabetical** — ASX: COG, CQE, DJW,
  EVT, EX20, FMG, GOZ, GPEQ…; NASDAQ: API, BEAM, CHYM, CSIQ, GRFS,
  NFLX, OLMA, PPLI…; crypto: BTC. That is "why" those names are first:
  the ranking has no third differentiator.

## 2. Quality of the agreement signal

- **84% of the aligned set rides PhaseMap's weakest active read.** PM
  tier distribution among the 101: **Watch 85, A+ 9, A 7** — and the
  Watch-tier legs are overwhelmingly SWEPT, the earliest active state.
  The genuinely strong PM legs exist but are few: EVT (RUNNING/A+ long),
  OLMA (RUNNING/A+ short), GPEQ and DJW (RUNNING/A). 
- **The ranking is putting MORE agreements first, not better ones —
  measurably.** Count is the primary key, but every current name counts
  2, so the live sort degrades to A+-then-alphabet. EVT — VIVEK A+ plus
  the strongest PhaseMap read on the ASX board — ranks behind COG, CQE
  and DJW because of the letter E. PM tier and state appear nowhere in
  the ranking. Today, "top of the strip" ≠ "highest-quality agreement";
  it means "alphabetically early A+ dual."
- **Fund/LIC/ETF noise: 21 of the 101 (21%) are fund-flagged by the
  deck's own heuristic, including 6 of the 27 A+** (CQE, EX20, GPEQ,
  L1IF-class names on the ASX side). The eyes chips carry **no fund
  marker** — a CQE chip is visually identical to an FMG chip; the FUND
  badge exists only down in the row list.
- Two honest defects observed in the machinery (display-layer, recorded
  not fixed): **NFLX is a false fund flag** — the keyword test matches
  `ETF` *inside* "N**ETF**LIX", so Netflix wears a FUND/REIT badge on
  the deck rows; and **97 ASX tickers carry two active PhaseMap rows in
  opposite directions** (e.g. DJW: RUNNING/bullish/A *and*
  SWEPT/bearish/Watch). The confluence count handles this correctly
  (majority side), but the chip/detail can end up describing whichever
  row loaded last — an aligned-long chip whose tooltip cites the bearish
  read is possible today.

## 3. Decision-surface effectiveness (observational)

- **STALLED — extended observation.** What it surfaced had existed in
  raw JSON for ~3 weeks with zero action; within hours of it rendering,
  three of its members were cut for +0.70R and the freed capacity is
  the entire subject of Monday. Two structural virtues observed: it
  renders the *engine's* stall mark (`stale_pinged`) rather than a
  parallel display heuristic, so the page and the probe cannot
  disagree; and it covers the post-TP1 runner gap the 28d rule exempts.
  It has now also survived its first state transition cleanly (7 rows →
  4 after the closes, no stale remnants).
- **EYES — what it makes obvious:** that direction-aligned agreement
  exists at all, its side, the A+ subset, and one-click routes to
  combined charts; triples, when they ever occur, will pulse loudest —
  correct hierarchy in principle. **What it leaves buried or noisy:**
  the PM-leg quality gradient (a RUNNING/A+ leg and a SWEPT/Watch leg
  render identically), the 21% fund share (no marker at chip level),
  the alphabetical order inside grade ties, and — by design — the fact
  that opposed co-presence is half again larger than the aligned set
  (invisible discipline; worth knowing it's the minority being shown).
- **Friction, surface → decision:** for entries there is none to
  measure — the bot acts or doesn't by frozen rules, and the strip is
  watch-only. For the owner's actual lever (closes), the path is
  unchanged from this morning's observation: journal-page strip →
  Actions tab → six manual fields, including an exit price the operator
  must fetch themselves (the strip shows ages, not marks). Three pages
  and one hand-copied number per decision, as a fact of the current
  workflow.

## 4. Monday readiness of the surfaces

- **STALLED at Monday open:** the four kept names at 25–26 days held.
  The strip shows held-days but not days-to-time-stop — the owner does
  the 28-minus arithmetic himself (ADP reaches 28 **Wednesday**, the
  other three **Thursday**). Content otherwise static until a close,
  TP1, or the time-stop.
- **EYES at Monday open:** rebuilt from Monday's first scans plus
  Sunday-night PhaseMap/Specs. On current composition, expect the same
  shape: tens of duals per stock market, zero triples, alphabetical A+
  head, BTC the only weekend-live aligned name. If the weekend crypto
  scans fill slots from BDX/BTC, the strip will already reflect BTC's
  alignment before any stock opens.
- **Gaps that force multi-page work for a capacity decision, as they
  stand:** free-slot count lives in the deck's bot strip and HORIZON's
  cap line, not beside either surface; the bot's actual queue order
  (scan ranking vs held-set) is on no page — the deck shows the ranked
  scan but not "eligible & not held"; and the close workflow still
  requires the mark from a fourth place (the book/journal page). None
  of this blocks a decision; all of it adds steps — factual workflow
  accounting, nothing more.

## 5. Track-record link (light, and honestly thin)

The 14-day alert history (800 entries, 395 distinct tickers, Jul 18–31)
against the 21-trade closed book:

- **Zero closed positions had printed a confluence alert before entry** —
  unsurprising and structurally correct: confluence is not an entry
  input (frozen), so any overlap happens mid-life.
- 7 of 21 closed names printed an alert at some point while held: net
  **+0.06R** (mean +0.01). The 14 never-alerted closes: net **−6.46R**
  (mean −0.46). 13 of the 26 currently open have printed one.
- Stated plainly: this is descriptive, confounded, and proves nothing.
  A name must survive long enough, near active structure, to print an
  alert at all — the never-alerted group contains every fast stop-out
  almost by construction. n=21 across one month of one regime. No edge
  claim is made or supportable yet; this is the baseline the file will
  let us re-measure against in a month.

---

*The measurable sentence this review reduces to: the system's loudest
signal currently fires zero triples, ranks its 101 duals alphabetically
past the A+ flag, carries a 21% fund share and an 84% weakest-tier
PhaseMap leg — and the one surface that has already changed a real
decision is the quiet list of old positions, not the loud one.*
