# The normal day, and what only looks broken

Times are Melbourne unless they say otherwise. Melbourne and Sydney share a clock. NASDAQ times come New York first, with the Melbourne equivalent in brackets.

Written for **New York + 16 h = Melbourne**: New York on EST (UTC-5) since Sun 1 Nov 2026, Melbourne on AEDT (UTC+11). Next shifts: US summer time from Sun 14 Mar 2027 makes it New York + 15 h (every NASDAQ time an hour earlier in Melbourne), then Melbourne's AEST from Sun 4 Apr 2027 makes it New York + 14 h. The status script's `clocks:` line says which applies today; what moves is under "When the clocks change" at the end.

## A normal weekday

**Overnight: the NASDAQ session (its New York date is yesterday's in Melbourne)**
- 10:40 New York (02:40 Melbourne) NASDAQ open ping (cron-job.org 8587591). Scan lands about 10:44 New York (02:44 Melbourne).
- 11:10 to 16:10 New York (03:10 to 08:10 Melbourne) hourly pings (8587598). Scans land about 11:14 to 15:14 New York (03:14 to 07:14 Melbourne); the 16:10 ping's scan is the close.
- 16:05 New York (08:05 Melbourne): the NASDAQ close counts from here. Post-close scan about 16:10 to 16:16 New York (08:10 to 08:16 Melbourne), from the 16:10 ping or GitHub's 21:07 UTC cron.
- 16:15 New York (08:15 Melbourne) US digest (NASDAQ + crypto) from the first ladder rung after the close. The ladder runs every 30 min from 15:15 to 18:45 New York (07:15 to 10:45 Melbourne), so the 07:15 and 07:45 rungs come before the close and print "waiting for a post-close nasdaq scan": normal. If the post-close scan lands at 16:16 New York, an 08:15 refusal then an 08:45 send is normal.
- About 16:49 New York (08:49 Melbourne) Momentum NASDAQ. It is due from the 16:30 New York bar-final, and the 08:45 digest rung's run wakes it.
- About 16:35 to 17:30 New York (08:35 to 09:30 Melbourne) Ignition NASDAQ. Its bar is final from 16:30 New York (08:30 Melbourne) and its GitHub cron is 21:34 UTC, four minutes later; later still when GitHub is slow.

**Daytime: the ASX session**
- 11:10 to 16:10 hourly pings (8587588). Scans land about :15 past.
- 11:30 Momentum crypto due (00:30 UTC). It usually lands 11:30 to 12:15, but on Sundays and Mondays about 16:30 to 17:15 (only GitHub's crons wake it then).
- About 12:15 the nightly bot-book backup (GitHub's 21:35 UTC cron, landing late).
- 11:45 to 13:25 the edge ledgers (22:20 UTC cron, landing late).
- 16:40 ASX close ping (8587590). The close counts from 16:40 Sydney, because Yahoo shows the auction about 20 min late. Scan stamped about 16:45, saved by about 16:50.
- 16:45 to 17:00 Ignition crypto publishes the new UTC bar.
- 17:15 ASX digest from the first ladder rung. Rungs run every 30 min to 21:45.
- About 17:16 to 17:25 Momentum ASX (it counts from 16:40, the ASX bar-final; under AEST the 06:41 UTC backstop or the next digest rung picks it up).
- 17:20 ASX close probe (8587683). It heals only if no scan at or after 16:40 landed. No run from it is healthy.
- About 17:30 to 18:15 Ignition ASX's first screen (GitHub cron `24 6` UTC = 17:24); a re-screen around 00:30 to 02:00 is common. A very late GitHub day can push the first one past midnight.

**Overnight again**
- Midnight to about 04:30 PhaseMap + Specs (GitHub's 08:30 UTC cron lands 5 to 9 hours late). Its `run_date` is the Melbourne date it ran, so it usually reads the day after the bars it screened.

**Crypto (24/7)**
- Hourly ping at :22 (8587599, stale after 45 min). Scans land about :25.
- About 4 extra a day from GitHub's crypto_bot.yml.
- One gap of about 100 min is normal (a heal queued behind an ASX scan). Repeated gaps, or more than 2 hours, is a problem.

## Things that look broken but are normal

- **GitHub's crons run late or never.** Backstops land 3 to 8 hours late, the 00:14 UTC Ignition crypto cron has not fired in days, and the kill switch runs about every 4 to 7 hours. In the week to 5 Oct GitHub ran 5 of 35 ASX scans. cron-job.org is the real clock. Judge by the data stamps and the first ladder runs.
- **Most runs are no-ops.** About 20 Momentum runs a day print "nothing due", digest rungs print "already went out today" (or, before the close, "waiting for a post-close ... scan"), and backstop scans print "-> skip". All correct.
- **Almost every scan is a heartbeat (`h`).** cron-job.org started them, as designed since 6 Oct. The status lamp's old "self-heal" amber wording predates this.
- **Stale-looking prices.** ASX shows hundreds of names with a day-old price intraday, and around 1,000 at 11:15: thin names that have not traded yet. The close scan drops to about 300.
- **Cache numbers.** ASX "from cache" in the hundreds intraday is normal and falls to about 0 at the close. About 30 crypto coins come from Yahoo because no exchange lists them.
- **ASX coverage reads about 90% (about 1,726 of 1,923 names).** About 197 codes never come back from Yahoo: mostly funds, trusts and bond lines, none of them held. The scan log's two "recovery batches" that come back empty are these. Every run, not a fault. Only a drop well below 1,700, or a held name among the missing, is news.
- **NASDAQ looks old by day.** Its book and scan are 8 to 9 hours old at a Melbourne afternoon check-in, and /api/health?market=nasdaq answers 503 (its 4 h line) from about 12:15 Melbourne until the next open scan at about 10:44 New York (02:44 Melbourne). Shut market, not a fault.
- **Book full: 60 of 60 open.** Every new setup is skipped (global cap). That is the rules working.
- **15 to 25 positions marked stalled** (14+ days, under 0.5R either way). The journal's STALLED fold lists them and the rules' 28-day time stop handles them; Viv stopped closing by hand on 14 Oct. Routine: stalled rows do not light the status lamp.
- **A loss-guard breach.** The guard working: new entries pause for the day and nothing is sold. Amber, not red.
- **"REVIEW <SYM>" lines in a scan log.** Flagged plans before the caps ran. Names the 60 cap dropped never opened. Only rows in the book were bought.
- **The connected Gmail has no GitHub emails.** It is the wrong inbox. Use the run list.
- **Sunday Ignition commits with a `_backtest.json`.** Each Ignition workflow re-runs its replay weekly (UTC Sunday: ASX 02:17, crypto 03:37, NASDAQ 04:47; the stock replays take 30 to 60 minutes) so its forward bucket fills. A screen re-stamp rides along. Expected.
- **An Ignition ASX or NASDAQ backstop runs although a file landed after the close.** The gate also re-runs when the file's bars are behind (more than half its names a bar old, or no name on the close's bar yet; on an exchange holiday that is every backstop). Expected.

## When the clocks change

Jobs set in New York time keep their New York time and move in Melbourne; jobs set in UTC (the US digest ladder, GitHub's crons) keep their UTC time and move in New York, and in Melbourne only when Melbourne changes.

- **US summer time (EDT) from Sun 14 Mar 2027: New York + 15 h.** Every NASDAQ time is an hour earlier in Melbourne: open ping 01:40, hourly pings 02:10 to 07:10, close gate 07:05, post-close scan about 07:10 to 07:16. The US digest ladder stays at 07:15 to 10:45 Melbourne, so its 07:15 rung can send; a 07:15 refusal then a 07:45 send is normal. Momentum NASDAQ about 07:49. Ignition NASDAQ's bar is final at 07:30 and its cron still runs at 08:34. The NASDAQ health 503 starts about 11:15.
- **Melbourne on AEST from Sun 4 Apr 2027: New York + 14 h.** NASDAQ moves another hour earlier in Melbourne (open ping 00:40, close gate 06:05), and so does everything set in UTC: US digest ladder 06:15 to 09:45, Ignition NASDAQ's cron 07:34, PhaseMap from about 23:30. ASX times stay the same in Melbourne. The ASX digest's 06:15 UTC rung becomes 16:15, before its 16:30 floor, so the digest goes at 16:45 or 17:15. Ignition ASX's 06:24 UTC primary (16:24) runs before the close; its 07:24 backstop re-screens.
- **Back to this page's times:** Melbourne's AEDT from Sun 3 Oct 2027 makes it New York + 15 h again (as in March), and US EST from Sun 7 Nov 2027 makes it New York + 16 h, the times above.

## cron-job.org jobs

All are GET pings to googy-boys-scanner.pages.dev, Mon to Fri unless noted.

- 8587588 ASX hourly 11:10 to 16:10 Sydney, /api/heartbeat?market=asx&stale_min=15
- 8587590 ASX close 16:40 Sydney, same URL
- 8587683 ASX close probe 17:20 Sydney, stale_min=40
- 8587591 NASDAQ open 10:40 New York (02:40 Melbourne), market=nasdaq stale_min=15
- 8587598 NASDAQ hourly 11:10 to 16:10 New York (03:10 to 08:10 Melbourne)
- 8587599 crypto every hour at :22 UTC, every day, stale_min=45
- 8424425 ASX digest ladder 06:15 to 10:45 UTC every 30 min, /api/morning_plays?slot=asx&key=***
- 8424432 US digest ladder 20:15 to 23:45 UTC every 30 min, which is 15:15 to 18:45 New York (07:15 to 10:45 Melbourne), slot=us

## Open decisions that are Viv's (mention only if one got worse, or he asks)

- **The kill switch's real cadence.** About 5 runs a day instead of 48. A cron-job.org trigger would fix it.
- **PhaseMap landing overnight.** It could be moved to cron-job.org (it needs a small endpoint change).
- **No alert channel.** Telegram and email are empty, so guard, watchdog, stall and review alerts reach nobody. The check-in is the delivery.
- **Forward-return stamps.** The old worry about pre-5 Oct ASX stamps is closed: it does not reproduce (0 of 10,777 checkable stamps differ). Still open: 67 later stamps that read the 13 Oct bar differ. Pruning old weekend and wrong-token rows is his call.
- **Refusing "proxied" A+ setups.** Their 200-SMA used fewer than 200 bars.
- **Pending setup.** The data provider (EODHD or Norgate), Cloudflare Access on /api/close and /api/scan, and deleting the orphaned secrets.

**Declined or settled. Never re-raise:**
- FX sizing: kept, the notional is in each market's own currency.
- Trimming the seven wide-stop legacy positions.
- Anything about the removed risk_manager stack.
- Sector caps: 6 per sector in each market (settled 27 Sep). Since hc4-2 (2 Nov) a sector is its GICS-11 bucket, so one sector no longer splits into several labels, and the bot holds one position per company (crypto exempt).
- The digest trigger secret: it is set.
