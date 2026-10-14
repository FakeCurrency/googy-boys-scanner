# Repo size — where it comes from and the plan (REFINE200 #58 / #61, 2026-10-14)

**Plan only. Nothing in this note moves data.** The repository is ~2.4 GB on
GitHub (as reported by the REFINE200 finder; a cloud session holds a shallow
clone and cannot measure the full history) and keeps growing, because the
pipeline commits its outputs to `main` ~60 times a day. Git keeps every version
of every file for ever, so the cost of a file is how often its bytes change,
not how big it is today.

## What was measured (2026-10-14, from the committed history)

**The tracked tree** (what every CI checkout downloads and writes): ~187 MB.

| Area | Size | Notes |
|---|---|---|
| `data/` | 64 MB | `data/history` 53 MB (715 ASX files), ledgers, research (4.9 MB), caches |
| `public/data/` | 58 MB | PhaseMap 52 MB of it — 1,411 chart files (29 MB) + snapshots |
| `backups/` | 52 MB | 30 nightly snapshots × ~1.9 MB |
| everything else | ~13 MB | code, tests, vendor |

**One day of commits** (2026-10-13 06:30 → 2026-10-14 06:30 UTC, 62 commits),
measured three ways: the new blob bytes the commits introduced; those blobs
packed among themselves; and the INCREMENTAL packed size with each file's
previous version available as a delta base (the best case for git). The day
predates the REFINE200 PhaseMap changes (#59, #60).

| Source | Raw new bytes / day | Packed, best case / day | Why it changes |
|---|---|---|---|
| `public/data/phasemap/charts/` | 26.4 MB (1,365 files) | ~1.2 MB | every chart file rewritten nightly — **fixed by #59** (rewritten only when its bytes change) |
| `data/history/asx/` | 20.0 MB (258 files) | ~2.0 MB | one bar a session per file, BUT 46 of 258 files were whole-series rewrites (a dividend or split re-bases the adjusted series) — see the plan below |
| combined book `journal/vivek_bot_book.json` + `public/data/vivek_bot_book.json` | 33 MB (2 × 44 writes) | ~0.03 MB | a DERIVED view rewritten twice per scan; deltas well |
| `*_vivek.json` + `*_vivek_detail.json` | ~24 MB | part of ~2.3 MB "rest" | per-scan prices and plans |
| `public/data/funnel_history.json` | 7.3 MB (44 writes) | ~0.03 MB | append-only ledger |
| dated PhaseMap snapshots `phasemap/<m>/<date>.json` | ~3 MB | (new path every day) | nothing reads them — **#60 keeps 2**, but each one is still a new file in history |
| `data/edge_rosters.json` | 3.8 MB | — | **fixed by #62** (monthly shards; only the current month rewrites) |
| market caps, universe caches, ignition charts, ledgers | ~10 MB | in "rest" | |
| `backups/<stamp>/` | ~1.9 MB / night | ~0 | a backup copy is the SAME blob as the live file it copies, so git stores it once; its cost is the 52 MB in every checkout, not history |
| **Total** | **~144 MB** | **~5.5 MB** (16 MB packed without cross-day deltas) | |

Reading the table: git's packed growth is a few MB a day in the best case, but
the raw volume pushed is ~140 MB a day and the server only reaches the best case
when it repacks. The two sources that resist delta compression are the ones to
fix: files whose OLD bytes change (re-based price history) and files that are
new paths every day (dated snapshots). Rewrites of the same bytes (the combined
book, funnel history) are cheap in history and only cost push bandwidth.

## Already done in REFINE200

- **#59** PhaseMap chart files are rewritten only when their bytes change, at 8
  significant figures (was: all ~1,400 every night).
- **#60** two dated PhaseMap snapshots kept on disk (was 7).
- **#62** edge rosters in monthly shards; no 20k cap deleting evidence.
- **#63/#64** ~5 MB of unread research files moved off the site to
  `data/research/`; Discord-era orphans deleted.
- **#65/#66** compact JSON for PhaseMap `latest.json`/narrations, 5-significant-
  figure sparklines.
- **#67** the re-fetchable universe cache left out of nightly backups; the big
  ledgers ride only the newest 7 snapshots.

## The plan for `data/history` (#61)

`scanner/history_archive.py` keeps the adjusted daily bars of every ASX name
that set up (STORAGE ONLY — the one reader is `scripts/decision_pack.py`'s
stamp check). Each write REBUILDS the file from today's yfinance frame, which
`auto_adjust` has re-based onto the newest dividend/split, and rescales older
stored bars by the overlap ratio at the join. So a single dividend rewrites every
price in the file: 46 whole-series rewrites on the measured day, and the file is
re-encoded on every append.

**Option A — append-only bars + an adjustment ledger (recommended).** Store each
bar on the basis it had the day it was archived and never rewrite it. When the
join ratio says the frame was re-based, append `{"from": <date>, "ratio": r}` to
a per-file `adjustments` list instead of rescaling the stored bars. A reader
gets the adjusted series by multiplying each bar by the product of the ratios
recorded after it.
- For: every session becomes a small append (git deltas it to a few hundred
  bytes); a dividend costs one ledger entry instead of a whole file; it reuses
  the ratio the module already computes, so it needs no new download and no
  `auto_adjust=False` change to the scan (which would be a trade-path change);
  `splice_suspect` stays as the detector for a bad join.
- Against: readers must apply the ledger (today that is one script plus tests);
  a one-time migration rewrites the 715 files once (~53 MB raw, one commit); the
  stored ratios carry yfinance's rounding (~1e-6, below what any reader uses).

**Option B — raw (unadjusted) bars + corporate actions, adjusted at read time.**
Store raw OHLC plus a dividends/splits list and compute the back-adjustment on
read.
- For: the textbook layout; the record is independent of any vendor's
  adjustment method.
- Against: the scan downloads ADJUSTED frames, so this needs either a second
  download (`auto_adjust=False` / `actions=True`) for the ~300 archived names a
  day or a change to the scan's own download — the first costs Yahoo budget the
  scan already fights for, the second touches the trade path. Not worth it while
  A delivers the same git behaviour for free.

**Option C — move the archive out of `main`.** A separate data repository, a
monthly GitHub Release asset (a tarball of `data/history/`), or object storage.
- For: the main repo stops carrying it at all; CI checkouts lose 53 MB.
- Against: a second write path and credential (a release upload works with the
  workflow's own token; a second repo needs a PAT or deploy key); daily appends
  need somewhere to live between releases (the actions cache is evictable);
  restore and the decision-pack check must fetch it. Worth doing only if the
  archive is widened past the ~300 daily names (the full ASX download would add
  ~125 MB a year even append-only).

**Recommendation:** A now (a contained change to `history_archive.py`, its tests
and the one reader, no trade-path impact), C only if the archive is widened.

## Other proposals (each needs a yes before it is done)

1. **Stop committing dated PhaseMap snapshots.** Nothing reads them; each is a
   new path every night (~3 MB raw) whatever the keep count. Upload them as a
   workflow artifact instead. (A publishing change, not a detection change — no
   RULESET bump — but the spec describes the dated snapshot, so it is the
   owner's call.)
2. **Commit one copy of the derived combined book.** `journal/vivek_bot_book.json`
   and `public/data/vivek_bot_book.json` are byte-identical derived views written
   by every scan. Keeping only the public twin halves ~33 MB a day of pushes.
   `--verify`, the backups and several tests name the journal copy, so it is a
   small multi-file change.
3. **Backups: artifact-only.** The nightly snapshot is already uploaded as a
   90-day artifact; the in-tree copy costs every checkout 52 MB. The watchdog's
   `backup_stale` CRITICAL probes the committed directory, so switching needs
   that probe rewired to the run history (owner sign-off: it is a CRITICAL
   alarm).
4. **Do not rewrite history.** Shrinking the existing 2.4 GB needs a
   `git filter-repo` rewrite and a force-push of `main` — it breaks every clone,
   every open branch and the commit sentinel's identity check, and it destroys
   the audit trail of the track record. Fix the growth; leave the past.

## How to re-measure

```bash
# tracked tree by area
for d in public/data data backups; do git ls-files $d | xargs -d '\n' du -cb | tail -1; done
# one day's churn: list each commit's changed blobs, then pack them
git log --format=%H --since=<start> --until=<end> origin/main |
  while read h; do git diff-tree -r --no-commit-id "$h"; done |
  awk '$4 !~ /^0+$/ {print $4}' | sort -u | git pack-objects --stdout | wc -c
```

The best-case figure adds each changed path's previous blob to the pack and
subtracts the size of packing those bases alone.
