# Vivek 5.0 — Owner's Health Check (runbook)

Step-by-step checks to confirm the whole system is healthy, plus what to do
when an email arrives. Written 2026-07-26 after the scheduler-ghosting +
CI-flake week. Times are Melbourne unless marked UTC.

---

## The 60-second daily check

1. **Open the dashboard** → deck header: green dot + "Last scanned: …".
   - During a market's session: should read under ~1–2 h.
   - Stock markets outside their session (nights/weekends): reading "hours
     ago" is NORMAL — they scan only while open. Crypto should never read
     older than ~3 h (hourly weekdays, 6-hourly + hourly bot on weekends).
2. **Open `/api/health`** (bookmark `googy-boys-scanner.pages.dev/api/health`).
   - `"ok": true` and `age_h` under 4 → the entire pipeline heartbeat is good.
   - This is the single most truthful number in the system: it reads the
     PUBLISHED bot book off the live site — scanner, commit, deploy all have
     to work for it to stay fresh.
3. **Glance at the bot strip** on the dashboard ("Bot: N open · …") — it
   re-marks with every scan.

All three good → everything is moving. Done.

## The 5-minute weekly check

4. **GitHub → repo → Actions**: recent runs green? Then open the
   **Scheduled scan** workflow — recent runs green and roughly hourly during
   sessions. (GitHub's scheduler drifts runs by up to a couple of hours —
   drift is normal; the :47 backstop covers dropped ASX slots.)
5. **Actions search: `is:failure`** — an empty week = clean. Any red run:
   open it; the failed STEP name tells the story (and the email already did).
6. **Journal page** — P&L headline present, "marked Xm ago" fresh after the
   latest scan; ALERTS page keeps filling.
7. **End-to-end probe**: tap **SCAN** on the dashboard → within ~10 min
   "Last scanned" resets to minutes ago. That one tap proves the whole loop:
   dispatch → Actions run → data commit → Cloudflare deploy → fresh site.

## When an email arrives — triage by subject

- **"…/api/health is down"** (uptime monitor): open `/api/health` yourself.
  `ok:true` → it was a seconds-long blip (usually mid-deploy) — ignore; the
  "up again" mail follows. `ok:false` with `age_h` > 4 → tap SCAN; if a
  manual scan doesn't land either, check Actions for red runs.
- **"Tests workflow run"** (some jobs not successful): CI quality gates on a
  CODE push — the live site is unaffected and keeps deploying regardless.
  If the failed job/step is e2e tooling (screenshot-diff, lighthouse), it's
  plumbing, not the scanner.
- **Watchdog "stale" email**: the backstop is usually already fixing it
  (worst case ~40 min behind a dropped slot). Tap SCAN to fix it instantly.
- **"succeeded" / "fixed"**: good news in the same envelope — archive it.

**Universal remedy: tap SCAN.** It is the manual override for nearly every
freshness problem.

## One-time settings that cut email noise (owner side)

- Uptime monitor: alert only after **2–3 consecutive failed checks** (deploy
  blips last one check; real outages last many).
- GitHub → Settings → Notifications → Actions: email on **failed workflows
  only** (the "succeeded/fixed" mails read like alarms at a glance).

## What's already automatic (no action needed)

- **:47 backstop cron** re-runs any ASX scan slot GitHub silently drops
  (skips itself when the hour's scan already landed).
- **Watchdog** (kill-switch, half-hourly) emails if data truly stales (>4 h),
  with anti-spam rules (first / 6-h reminder / recovery).
- **assert_staged** makes a scheduled run that commits nothing FAIL loudly —
  silent-green is impossible.
- **Tests** gate every code push (≈290 py + 180 JS checks, e2e smoke,
  Lighthouse + screenshot-diff tripwires).
