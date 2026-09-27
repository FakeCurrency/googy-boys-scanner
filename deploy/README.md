# Vivek 5.0 on your own server: the runbook

This is the step-by-step guide for moving the scanner's engine room off GitHub
and onto a server you rent from Binary Lane. It is written for a trader, not a
systems administrator. Every technical word is explained the first time it
appears (and again in the Glossary in section 1), and every box of commands
comes with one sentence saying what it does and whether it changes anything.

- **This file** is the one you follow.
- **`deploy/DESIGN.md`** is the engineering contract (for Claude and for
  reviewers). You do not need to read it.

Nothing in this runbook touches real money. The scanner's bot is a PAPER bot.
The only real-money system in the picture is your ICT LIVE bot, and the whole
design of this kit is about leaving it alone.

---

## 0. Read this first

**The short version.** Today the scanner's jobs (the scans, the paper bot, the
kill switch, the backups, the morning plays digest) run on GitHub's computers,
a service called GitHub Actions. The website is served by Cloudflare. This kit
lets the same jobs run on a server you control, in two stages:

- **Phase 1 (the one to do now).** The server runs every scheduled job. The
  website stays exactly where it is, at https://googy-boys-scanner.pages.dev/,
  and keeps working exactly as it does today.
- **Phase 2 (optional, later).** The server also serves the website itself.

**Where should it run? There are two options, and the recommendation is
Option A.**

- **Option A (recommended): a second, small Binary Lane server just for the
  scanner.** Nothing the scanner does (a heavy ASX scan, a full disk, a bad
  code update, a mistake while you are learning the commands) can slow down,
  starve or stop ICT LIVE, because they live on different machines. It costs
  one more small server a month. That is cheap insurance next to a real-money
  bot.
- **Option B: the same box as ICT LIVE (`ict-bot`)**, and only after you
  upgrade it to 4 GB of memory with Binary Lane's "Change Plan". The kit has
  safeguards for sharing a box (section 3), but a shared box always shares
  memory, processor time, disk and network with your real-money bot. Today's
  `ict-bot` (1 vCPU, 2 GB) is too small to share.

> ### What this kit will never do to your ICT bots
>
> - It never stops, restarts, reloads, edits or kills any program or service
>   whose name does not start with `vivek5-`. Every service command in the kit
>   goes through a guard that refuses any other name, and there is no
>   `kill`, `pkill` or `killall` anywhere in it.
> - It never changes the box's clock, timezone or time-sync settings. The
>   scanner's jobs carry their own timezone setting internally.
> - It never installs, upgrades or replaces the system's Node.js or any system
>   copy of Caddy. It downloads its OWN private copies (checksum-verified) into
>   `/opt/vivek5/node` and `/opt/vivek5/caddy`.
> - It never touches the firewall (`ufw`, `iptables`, or Binary Lane's Cloud
>   Firewall).
> - It never changes the system log settings (journald), so your bots' log
>   history is not shortened.
> - It never adds swap unless you ask for it with `--with-swap`.
> - It never takes ports 80 or 443 away from another program. If something
>   already uses them, preflight fails and cutover refuses.
> - Its heavy jobs always run at LOWER processor and disk priority than
>   everything else on the box, and above 1 GB of memory they are throttled
>   (slowed down and made to hand memory back) instead of crowding your bots.
>   The dispatch door (the scanner's always-on API program) has a hard
>   512 MB cap.
> - It starts nothing when you install it. Nothing runs until cutover.
> - It never needs your ICT exchange keys, and you must never put them in any
>   file under `/etc/vivek5` (section 6.4 explains why this matters).
>
> Two honest limits, so nothing surprises you: `install.sh` asks Ubuntu's
> package manager to install 14 standard packages, and if one of them is
> already installed and Ubuntu has a newer version, it gets upgraded (normal
> Ubuntu maintenance, but still a change to shared software); and a Claude
> Code session you run on the box with admin rights can reach everything,
> which is why section 5 gives it strict instructions.

---

## 1. Glossary

Plain-English meanings of every technical word used below.

| Word | What it means |
|---|---|
| **VPS** | "Virtual private server": a computer you rent by the month in a data centre. Your Binary Lane servers are VPSes. |
| **SSH** | The secure way to log in to a server from your laptop and type commands. `ssh root@<address>` opens a command window on the server. |
| **root** | The all-powerful admin account on a Linux server. Commands run as root can change anything. |
| **sudo** | "Do this one command as root." `sudo <command>` asks for admin rights for that command only. If you are already logged in as root you can leave the word `sudo` out. |
| **systemd** | The part of Ubuntu that starts and supervises programs. It is how the scanner's jobs are scheduled and kept running. |
| **unit** | One thing systemd manages, described in a small text file. All of this kit's units are named `vivek5-...`. |
| **service** | A unit that runs a program, either once (a scan) or for ever (the web front door). |
| **timer** | A unit that starts a service on a schedule, like an alarm clock. `vivek5-scan@asx.timer` starts an ASX scan at 11:07, 12:07 and so on. |
| **path unit** | A unit that starts a service when a file appears or changes. The kit uses two. |
| **cron** | The old name for "run this on a schedule". GitHub's schedules are crons; on the server, timers do the same job. |
| **journal / journalctl** | Where systemd keeps every program's printed output (its logs). `journalctl -u <unit>` shows one unit's log. |
| **swap** | Disk space the server can use as emergency extra memory. Slow, but it stops a memory spike from crashing things. |
| **port** | A numbered door on a server that a network program listens behind. Web traffic uses port 80 (plain) and 443 (encrypted). SSH uses 22. |
| **firewall** | A filter that decides which ports the outside world may reach. |
| **deploy key** | A key that lets ONE server push to ONE GitHub repository, and nothing else. The server uses it to publish scan data. |
| **git, repository, branch, main** | git is the version-history system that stores the code and the data. The repository ("repo") is the project on GitHub. A branch is a line of history; `main` is the one the website is built from. |
| **commit / push** | A commit is one saved change; a push sends commits to GitHub. |
| **GitHub Actions / workflow** | GitHub's computers that run jobs on a schedule. Each job is a "workflow" file such as `scan.yml`. |
| **Cloudflare Pages** | The service that hosts the website today (`googy-boys-scanner.pages.dev`). It rebuilds the site whenever `main` changes. Its small server-side programs ("Functions") run the SCAN and close buttons. |
| **token / secret** | A long password that a program uses. Never paste one into a chat. |
| **env file** | A plain text file of `NAME=value` settings a program reads when it starts. This kit has three, in `/etc/vivek5/`. |
| **Caddy** | A small web server. The kit runs its own private copy as the "front door" that receives requests from Cloudflare. |
| **TLS / HTTPS** | Encryption for web traffic (the padlock in a browser). Caddy gets the certificate for it automatically. |
| **DNS / hostname** | DNS is the internet's phone book. A hostname (for example `something.bnr.la`) is a name that DNS turns into your server's address. |
| **Phase 1 / Phase 2** | Phase 1: the server runs the jobs, Cloudflare still serves the site. Phase 2: the server serves the site too. |
| **preflight** | A read-only check script. It tests everything and changes nothing. Cutover will not start until it is green. |
| **cutover** | The one-time switch from GitHub to the server: it switches GitHub's jobs off and the server's on, in a safe order. |
| **rollback** | The undo of cutover: the server's jobs off, GitHub's back on. |
| **HALT** | A safety stop. If the server sees that someone else changed the data on GitHub, it stops writing the paper book until you decide what to keep (section 12.6). |
| **ledger** | The server's run diary, `/opt/vivek5/state/runs.json`: for every job, when it last ran and whether it worked. |
| **spool** | A queue folder. When you press SCAN or close-all on the site, the request is written into the spool and the server runs it in order. |
| **dry run** | Running a job for real on the server but with publishing switched off, so nothing is pushed to GitHub. |
| **tmux** | A tool that keeps a command running on the server after you disconnect. Used for the Claude Code session in section 5. |
| **Remote Control** | A Claude Code feature: a Claude session running ON the server that you can drive from the Claude app on your phone or laptop. |

---

## 2. What this is

### Today

- GitHub Actions runs 15 workflows on schedules. They write the scan results
  and the paper book as commits on `main`. Cloudflare Pages notices each
  commit and republishes the website.
- The site's SCAN button, close-all button and the "healer" (which starts a
  scan when data goes stale) ask GitHub to start a job.
- When a GitHub job fails, GitHub emails you. That red-run email is your main
  alarm today.

### Phase 1 (what you are installing)

- The server runs the same 14 jobs on its own timers: the same schedule, the
  same code, the same rules. It pushes the data to `main` exactly as GitHub
  did, under its own name (`vivek5-vps@<server name>`). Cloudflare Pages keeps
  republishing the site from GitHub, so the website does not move.
- At cutover, 15 GitHub workflows are switched off, so there is only ever ONE
  writer of the paper book. Two writers could each open a position and break
  the 30-position cap. That is the one mistake that cannot be undone, and the
  kit guards against it three separate ways (section 12.6).
- The site's buttons now ask the server instead of GitHub, through one small,
  locked door on the server called `/api/dispatch`. It only accepts a few
  exact requests (scan a market, close a position that is really open at a
  sensible price, send the plays digest), and only with a secret token.
- Alarms: GitHub's red-run emails stop (those workflows are off). The server
  sends its own alerts to **Telegram** instead. That is why an alert channel
  is required before cutover.

**What changes for you:** alerts arrive in Telegram instead of email; "is it
working?" is answered on the server (section 12) instead of on GitHub's
Actions page; a Claude session starts a scan in a different way (section
12.15).

**What does not change:** the website address and how it looks; the
strategies, grades and the paper bot's rules (four cells, A/A+, 30 positions,
$5,000 per position, loss guards); GitHub still holds all the code and all the
data history; Claude sessions still change the code the same way, and their
changes reach the server within 5 minutes.

### Phase 2 (optional, later)

The server also serves the website, from its own copy of the files, with the
SCAN and close buttons protected by a password. Cloudflare Pages can stay up
as a mirror or be deleted. Section 11.

---

## 3. Pick where it runs

### Option A (recommended): a second Binary Lane server

In the Binary Lane panel, create a new server with:

- **Operating system:** Ubuntu 24.04 LTS
- **Location:** Melbourne
- **Memory:** 4 GB if the budget allows. If not, 2 GB works, and you add a
  swap file during install (`--with-swap`, section 6.2).
- **Processors:** 2 vCPU if that size offers it; 1 vCPU works (preflight will
  print a WARN, which is fine on a server of its own).
- **Disk:** 40 GB or more. The kit needs 20 GB free; the data history grows
  about 0.7 GB a month.
- **Name:** something like `vivek5-scanner`. The name becomes part of the
  scanner's identity on GitHub (`vivek5-vps@vivek5-scanner`).
- **Access:** root over SSH, the same way you log in to `ict-bot` today.

Write down its permalink hostname (the `<words>.bnr.la` name Binary Lane shows
for the server). You will use it as the scanner's hostname in section 6.6.

### Option B: the same box as ICT LIVE (`ict-bot`)

Only do this if a second server is really not possible.

1. **Upgrade `ict-bot` to 4 GB with "Change Plan" first.** Changing the memory
   size usually needs the server to power off and on; the panel tells you.
   Do it at a moment when ICT LIVE can safely stop and start again (markets
   closed, following your usual ICT routine), and afterwards check that ICT
   LIVE and ICT DEMO are running again before you go any further.
2. **The safeguards you get on a shared box, in plain words:**
   - The scanner runs as its own users (`vivek5`, `vivek5-api`,
     `vivek5-caddy`) in its own folders (`/opt/vivek5`, `/etc/vivek5`,
     `/usr/local/lib/vivek5`). It does not run as root and cannot write to
     your bots' folders.
   - It uses its own private copies of Node.js and Caddy under `/opt/vivek5`.
     Whatever your bots use is never installed, upgraded or replaced.
   - The box clock and timezone are left exactly as they are.
   - The firewall is left exactly as it is.
   - The system log settings are left exactly as they are.
   - The scanner's heavy jobs (scans, backtests) run at lower processor and
     disk priority than ICT LIVE, so ICT LIVE wins every contest for the
     processor. Above 1 GB of memory a scanner job is throttled (slowed
     down and made to hand memory back).
   - Nothing starts when you install. Everything waits for cutover.
   - The kit never stops, restarts or edits a program or service that is not
     named `vivek5-...`.
   - If ICT (or anything else) already uses ports 80 or 443, the kit refuses
     rather than taking them (section 8 tells you what to do then).
3. **What Option B cannot fix:** one disk, one network connection and (on 1
   vCPU) one processor are still shared. A full disk stops both. A Claude
   Code session you run on the box with admin rights can reach ICT's files.

---

## 4. Requirements (have these ready)

### 4.1 The server size, and what `--measure` tells you

Preflight (section 8) has a `--measure` option that runs a small ASX scan (40
stocks) at the scanner's low priority and prints its peak memory ("max RSS").
A full ASX scan covers about 2,200 stocks and needs more, so the real test is
the full ASX dry run in section 9, which prints a "Memory peak" line.

Rules of thumb:

- **Option A with 2 GB:** install with `--with-swap`. After the full ASX dry
  run, if "Memory peak" sits at about 1 GB (the soft ceiling, meaning the job
  was being squeezed), or the run took well over an hour, use Binary Lane's
  "Change Plan" to go to 4 GB.
- **Option B:** 4 GB before you start, no exceptions. Preflight prints a WARN
  on any box under 4 GB with no swap.

### 4.2 A hostname that points at the server

Cloudflare will only call the server over HTTPS, and HTTPS needs a name, not
a bare IP address. The easiest name is the Binary Lane permalink
(`<words>.bnr.la`) that already points at the server. If the certificate
cannot be issued for that shared name (shared domains sometimes hit the
certificate authorities' weekly limits; Caddy tries two authorities), use a
name on a domain you own instead: create a DNS "A record" such as
`scanner.yourdomain.com` pointing at the server's IPv4 address.

This command asks DNS where the name points; it changes nothing (replace the
example name with yours):

```bash
getent hosts your-words.bnr.la
```

It should print the server's own IP address.

### 4.3 An alert channel: a Telegram bot in 5 minutes

Binary Lane shows "Port Blocking: Enabled" on your server, which almost
certainly blocks outgoing email, so Telegram is the alert channel.

1. In Telegram, open a chat with **@BotFather** (the blue-tick official
   account) and send `/newbot`.
2. Give it a display name (for example `Vivek5 Alerts`) and a username that
   ends in `bot` (for example `vivek5_alerts_bot`).
3. BotFather replies with a **token** that looks like
   `123456789:AAH...`. That is your `TELEGRAM_BOT_TOKEN`. Keep it private.
4. Open a chat with your new bot and send it any message, for example `hi`.
   (A bot cannot message you until you have messaged it first.)
5. In a web browser, open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` with your token in place
   of `<TOKEN>` (no spaces, keep the word `bot` in front). Find
   `"chat":{"id":` followed by a number, for example `"chat":{"id":123456789`.
   That number is your `TELEGRAM_CHAT_ID`.

**One switch turns Telegram on for this server.** In `/etc/vivek5/jobs.env`
(section 6.4) set `VIVEK_TELEGRAM_ENABLED=1` once the two Telegram lines hold
your bot's values. Without it, no Telegram message can leave the server and
preflight's alert check fails. This switch lives only on the server, so it
does not change what GitHub's jobs do before cutover. Expect WARNING-level
events as well as CRITICAL ones, so the occasional message will say
something is worth a look rather than broken.

**The alternative, stated plainly.** You may run preflight and cutover with
`VIVEK_ACCEPT_NO_ALERT_CHANNEL=1` (section 8). Preflight then prints a loud
WARN instead of a FAIL. It means: after cutover, if the server breaks, nothing
will tell you except an outside monitor (section 12.14). That is a standing
risk you would be choosing.

### 4.4 A GitHub deploy key with write access

`install.sh` creates the key and prints its public half. You add it to the
repo on GitHub (section 6.3). Nothing to prepare.

### 4.5 A fine-grained GitHub token for cutover (`GH_ADMIN_TOKEN`)

Used once, by cutover, to switch the 15 GitHub workflows off and set one
repository variable. Create it just before cutover:

1. GitHub, your picture (top right) > **Settings** > **Developer settings** >
   **Personal access tokens** > **Fine-grained tokens** > **Generate new
   token**.
2. Name: `vivek5 cutover`. Expiration: 7 days.
3. Repository access: **Only select repositories** >
   `FakeCurrency/googy-boys-scanner`.
4. Repository permissions: **Actions: Read and write**; **Variables: Read and
   write**. (Metadata: Read-only is added automatically.)
5. Generate, and copy it once. You paste it only into cutover's hidden prompt,
   never into a chat or a file. Delete it after cutover (section 10.6). If you
   ever roll back, you create a new one the same way.

### 4.6 Optional: a Cloudflare API token so cutover does the Cloudflare step itself

If you give cutover a Cloudflare token, it changes the three Cloudflare
settings in one go. If not, you do them by hand in the Cloudflare dashboard
(section 10.3). To create one: dash.cloudflare.com > your profile (top right)
> **API Tokens** > **Create Token** > **Create Custom Token** > permission
**Account / Cloudflare Pages / Edit** > your account > **Create Token**. You
also need your **Account ID** (shown in the dashboard's right-hand column on
the Workers and Pages overview, and inside every dashboard web address) and
the Pages project name, which is `googy-boys-scanner`.

### 4.7 Two values to fetch now, while they are easy to find

- **The morning plays Discord webhook.** GitHub will never show you the saved
  `DISCORD_MORNING_WEBHOOK_URL` secret again, so get it from Discord: Server
  Settings > Integrations > Webhooks > the plays webhook > **Copy Webhook
  URL**. (Or create a new webhook for the same channel.)
- **A copy of `GH_DISPATCH_TOKEN` from Cloudflare.** Cutover deletes it from
  Cloudflare. You only need it again if you ever roll back. In the Cloudflare
  dashboard: Workers and Pages > `googy-boys-scanner` > Settings > Variables
  and Secrets. It is stored as plain text, so you can read and copy it. Put it
  in your password manager.

### 4.8 Two GitHub Actions secrets for `ops.yml` (after install)

`ops.yml` is the workflow a cloud Claude session uses to reach the server
(section 12.15). It needs two repository secrets, which you add once the
server exists (the cutover checklist reminds you):

- `VPS_DISPATCH_URL` = `https://<your hostname>/api/dispatch`
- `VPS_DISPATCH_TOKEN` = the `DISPATCH_TOKEN` value from
  `/etc/vivek5/api.env` on the server (section 10.6 shows how to read it).

---

## 5. Driving this from Claude Code on the box (Remote Control)

You can do everything in this runbook yourself over SSH. Or you can run a
Claude Code session ON the server and drive it from the Claude app on your
phone or laptop ("Remote Control"). Claude then reads this file, runs the
commands, and explains what it sees. You still do the few steps that involve
a secret or a browser.

**On Option B this session will have admin rights on the box that runs ICT
LIVE.** That is the main reason Option A is recommended. If you use it on
Option B, give it the instruction below word for word, and remove its admin
rights when you are done (step 9).

**Step 1. As root, install tmux and git, and create a normal user for
Claude.** This installs two small packages and adds a user account named
`vivek`; it changes nothing else. (If `useradd` says the user already exists,
pick another name and use it everywhere below.)

```bash
apt-get update && apt-get install -y tmux git
useradd -m -s /bin/bash vivek
```

**Step 2. Give that user admin rights through a sudoers file.** This lets the
Claude session run `sudo` without typing a password (Claude cannot type one).
It changes who may use `sudo`. The file name matters: do NOT call it `vivek5`,
because the kit treats a file of that name as its own.

```bash
echo 'vivek ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/vivek-claude
chmod 0440 /etc/sudoers.d/vivek-claude
visudo -cf /etc/sudoers.d/vivek-claude
```

The last line checks the file and should print `parsed OK`.

**Step 3. Switch to that user.** This changes nothing.

```bash
su - vivek
```

**Step 4. Install Claude Code.** This downloads Claude Code into `vivek`'s
home folder only.

```bash
curl -fsSL https://claude.ai/install.sh | bash
export PATH="$HOME/.local/bin:$PATH"
claude --version
```

The last line prints a version number if it worked. (Optional, so you do not
retype the `export` line after every login:
`echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc`.)

**Step 5. Download a reading copy of the project and go into it.** This is
Claude's working copy for reading this runbook; it is not the copy the server
runs. It changes nothing outside `vivek`'s home folder.

```bash
git clone https://github.com/FakeCurrency/googy-boys-scanner.git ~/googy-boys-scanner
cd ~/googy-boys-scanner
```

**Step 6. Log in to Claude once.** This starts Claude Code interactively.

```bash
claude
```

It prints a web address. Open it in a browser on your phone or laptop, sign in
to claude.ai (a Pro, Max, Team or Enterprise plan; API keys do not work for
Remote Control), and paste the code it shows you back into the server window.
Accept the "trust this folder" question. Then type `/exit`.

**Step 7. Start Remote Control inside tmux, so it keeps running after you
disconnect.** The first line starts it in the background; the second shows it
to you.

```bash
tmux new-session -d -s rc "cd ~/googy-boys-scanner && claude remote-control"
tmux attach-session -t rc
```

Answer `y` once when it asks. Then detach (leave it running) by pressing
**Ctrl+b**, letting go, then pressing **d**. You can now close SSH.

**Step 8. Find it in the app.** In the Claude app, open **Code**. The session
shows with a computer icon. If the connection drops, `claude remote-control
--continue` (run in the project folder, inside tmux as in step 7) resumes it
within about 4 hours.

**What to say to it, first message, word for word:**

> Follow deploy/README.md. Do not run cutover.sh until preflight is green and I have read its output. Never stop, restart or edit the ICT bots.

**Who does what.**

- **Claude on the box can:** run `install.sh` (first WITHOUT `--yes`, so you
  see the printed plan; it stops without changing anything, and only after
  you say so, again with `--yes`), run preflight and the dry runs, read the
  ledger and the logs, and explain every line.
- **You do yourself:** the Binary Lane panel; the Telegram bot; registering
  the deploy key on GitHub; typing secrets into `/etc/vivek5/jobs.env` (open
  your own SSH window and use `sudo nano`, section 6.4, so tokens never pass
  through a chat); and running `cutover.sh` and `rollback.sh` in your own SSH
  window, because they ask for hidden tokens that Claude cannot type and must
  never see.

**Step 9. When you are finished,** stop the session (it uses a few hundred MB
of memory while it runs) and, on Option B especially, take its admin rights
away. These two commands end the Claude session and delete the sudoers file
from step 2:

```bash
tmux kill-session -t rc
sudo rm /etc/sudoers.d/vivek-claude
```

---

## 6. Install (Phase 1)

Log in to the scanner's server over SSH. If you are logged in as root you can
leave out every `sudo` below.

### 6.1 Get a root-owned copy of the code

This downloads the project into `/usr/local/src/vivek5`, a folder only root
can change. It changes nothing else. (If it says `git: command not found`,
first run `sudo apt-get update && sudo apt-get install -y git`.)

```bash
sudo git clone https://github.com/FakeCurrency/googy-boys-scanner /usr/local/src/vivek5
```

Why this folder and not your home folder: install, preflight, cutover and
rollback run as root, and they refuse to run from any folder another user can
write to. That way a job that misbehaves can never trick root into running its
code.

### 6.2 Run the installer

This prints every change it is about to make, then waits. **Nothing changes
until you type the word `yes`.**

```bash
sudo /usr/local/src/vivek5/deploy/bin/install.sh --phase 1
```

On a 2 GB Option A server, add swap in the same run instead:

```bash
sudo /usr/local/src/vivek5/deploy/bin/install.sh --phase 1 --with-swap
```

If it stops with `not confirmed ... nothing was changed`, you did not type
`yes` (or Claude ran it without `--yes`, which is the intended way to show you
the plan).

What it prints, in order (it takes a while: the project history is about
2.4 GB and is downloaded twice):

1. the plan, and the `Type yes` prompt;
2. `OS` (Ubuntu 24.04) and `TCP listeners already on this box` (for
   information only; it shows which programs already use which ports);
3. `apt packages`, then `Node 22.23.3` and `Caddy 2.10.2`, each downloaded and
   checked against its published checksum;
4. `users vivek5, vivek5-api, vivek5-caddy, group vivek5-spool`;
5. `deploy key` and, below it, one line starting `ssh-ed25519`: the public
   half of the deploy key (section 6.3);
6. `github.com host keys`: GitHub's server fingerprints, checked against the
   set GitHub publishes (if one does not match, install stops, because that
   would mean something is in the way between you and GitHub);
7. `clones`, `venv + requirements`, `units` (copied, not enabled, not
   started), the env files, `sudo: no grant for any vivek5 user`;
8. `Caddy config`: at this point it says the Caddyfile is not validated yet,
   because you have not set the hostname;
9. `install.sh finished. NOTHING was started. Next:` and a short list.

### 6.3 Register the deploy key on GitHub

This prints the public half of the key again. It is not a secret and changes
nothing.

```bash
sudo cat /etc/vivek5/deploy_key.pub
```

On GitHub: the repo > **Settings** > **Deploy keys** > **Add deploy key**
(the direct address is
https://github.com/FakeCurrency/googy-boys-scanner/settings/keys). Title:
`vivek5-vps <server name>`. Paste the whole line. **Tick "Allow write
access".** Click **Add key**.

### 6.4 Edit the job settings: `/etc/vivek5/jobs.env`

This opens the file in a simple editor. Save with **Ctrl+O** then **Enter**;
exit with **Ctrl+X**. It changes only this file.

```bash
sudo nano /etc/vivek5/jobs.env
```

Format rules: one `NAME=value` per line, no spaces around `=`, no quotes
needed, never the word `export`. Paste values cleanly (no leading or trailing
spaces).

Replace every `CHANGE_ME`. Preflight refuses cutover while any remains.

| Line | What to put |
|---|---|
| `VIVEK_TELEGRAM_ENABLED=0` | set to `1` once the two Telegram lines are filled in (section 4.3) |
| `TELEGRAM_BOT_TOKEN=CHANGE_ME` | the BotFather token (section 4.3) |
| `TELEGRAM_CHAT_ID=CHANGE_ME` | your chat id number (section 4.3) |
| `DISCORD_MORNING_WEBHOOK_URL=CHANGE_ME` | the plays webhook address (section 4.7). Blank it (`DISCORD_MORNING_WEBHOOK_URL=`) to switch the digest off; blank is accepted |

Leave these alone: the paths (`VIVEK_HOME`, `VIVEK_PUBLISH`,
`VIVEK_STATE_DIR`, `VIVEK_VENV`, `VIVEK_RUNS_LEDGER`), `VIVEK_GIT_PUBLISH=1`,
the four `GIT_...` identity lines (install already wrote
`vivek5-vps@<server name>`), `GIT_SSH_COMMAND`, `HOME`, `XDG_CACHE_HOME`,
`WATCHDOG_HOST`.

Optional:

- `VIVEK_BACKUP_TARGET=`: a second copy of the backups on ANOTHER machine, in
  the form `user@host:/path`. Leave blank unless you have one set up (section
  12.10).
- `GBS_SMTP_...` and `GBS_ALERT_TO`: email alerts. Binary Lane's port blocking
  almost certainly stops email from leaving the server; preflight tells you.

**Must stay blank: `BYBIT_API_KEY`, `BYBIT_API_SECRET`, `BYBIT_TESTNET`,
`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`.** The scanner's kill switch uses these
only to "flatten" an exchange account when the PAPER book breaches its loss
limit, and a flatten closes EVERY position on that account. Never put the
exchange keys ICT LIVE trades with into this file. With these lines blank, the
kill switch alerts and logs and never contacts an exchange, which is the
intended state.

Never put `GH_ADMIN_TOKEN` in any file here. Preflight fails if you do.

### 6.5 The API settings: `/etc/vivek5/api.env`

Nothing to change in Phase 1. Install generated `DISPATCH_TOKEN` (64 random
characters), which cutover copies to Cloudflare. `VIVEK_PHASE=1`.
`MORNING_PLAYS_TRIGGER_SECRET` may stay blank (the server sends the digest on
its own timers).

### 6.6 The front door settings: `/etc/vivek5/caddy.env`

This opens the file; it changes only this file.

```bash
sudo nano /etc/vivek5/caddy.env
```

Set `VIVEK_DOMAIN=` to your hostname, just the name, for example
`VIVEK_DOMAIN=your-words.bnr.la` (no `https://`, no slash at the end). Leave
`VIVEK_API_BASIC_USER` and `VIVEK_API_BASIC_HASH` as they are; they are for
Phase 2, and the `CHANGE_ME` there is fine in Phase 1.

### 6.7 Re-run the unit step

This re-copies the service definitions and now checks the front door's
settings against your hostname. It asks for `yes` again and starts nothing.

```bash
sudo /usr/local/src/vivek5/deploy/bin/install.sh --units
```

You should see `Caddyfile.phase1 validated for <your hostname>`.

---

## 7. Firewall

The kit does not touch any firewall. Binary Lane shows "Cloud Firewall:
Unconfigured", which means everything is allowed, and the scanner works as it
is.

If you decide to use Binary Lane's Cloud Firewall (or `ufw` on the server),
it must keep open, inbound:

- **port 22 (SSH)** on every server, or you lock yourself out;
- on `ict-bot`, **whatever ports ICT LIVE and ICT DEMO need** (check your ICT
  setup before changing anything there);
- on the server that runs the scanner, **ports 80 and 443**. Port 80 is how
  the certificate is issued and renewed; port 443 is where Cloudflare calls the
  dispatch door.

The scanner also needs to reach OUT to the internet: HTTPS (443) to Yahoo,
Binance, GitHub and Telegram, and SSH (22) to `github.com` for pushes.
Preflight prints `ufw status` so you can see whether `ufw` is active. Never
switch `ufw` on without first allowing port 22.

---

## 8. Preflight

This checks everything and changes nothing. Run it as often as you like. It
runs from `/usr/local/lib/vivek5/bin`, the root-owned copy install made.

```bash
sudo /usr/local/lib/vivek5/bin/preflight.sh
```

The sizing version, which also runs a small dry ASX scan (section 4.1):

```bash
sudo /usr/local/lib/vivek5/bin/preflight.sh --measure
```

Every line starts with **PASS**, **FAIL**, **WARN** or **INFO**. A FAIL comes
with a `remedy:` line. The last line reads `preflight: N FAIL, M WARN`.
Cutover needs **0 FAIL**. WARNs are things to read and understand, not
blockers.

While it runs you should receive **two Telegram test messages** ("Watchdog
TEST ALERT ... if you can read this, this channel delivers"). That is the
alert check working.

What the checks mean:

| Check | What it is asking |
|---|---|
| Ubuntu 24.04 | the kit is built and tested for exactly this version |
| system timezone (INFO) / NTP synchronized | the zone is only shown, never changed; the clock must be synced to internet time, because market windows depend on it |
| RAM / swap / vCPUs (WARN) | is the server big enough to run scans beside anything else on it |
| vendored node / caddy | the kit's private Node.js and Caddy are installed; the system's own are shown as INFO and never used |
| venv ... pinned versions / scanner imports | the Python environment is complete and at the exact versions the project pins |
| GB free under /opt/vivek5 | at least 20 GB free disk |
| OnCalendar / systemd-analyze verify / units match | every schedule line is valid and the installed units match the kit |
| env files 0640 / no CHANGE_ME / VIVEK_DOMAIN / Caddyfile validates / DISPATCH_TOKEN | the three settings files are complete and private |
| deploy key / known_hosts | the key exists with the right permissions; GitHub's fingerprints are the published ones |
| no sudo grant / users / vivek5-spool / kv.json / state/spool | the kit's users, groups and folders have the right permissions |
| no HALT / parked dispatches | nothing is stopped or waiting (section 12.6) |
| publish remote / git push --dry-run | the server can push to GitHub with the deploy key (a test push that sends nothing) |
| FULL clone / git lock files | the working copy has all history; no leftover lock files from a crashed git |
| resolves to this box / /api/vps | the hostname points here; the front door answers (only probed once it is running, i.e. after cutover) |
| :80 and :443 are free | nothing else on the box uses the web ports |
| ufw / journal (INFO) | shown for your information, never changed |
| Yahoo / Binance / api.github.com | the server can reach its data sources |
| outbound SMTP (WARN) | whether email could leave the server; usually blocked on Binary Lane |
| an alert channel round-trips | a real test message was delivered through Telegram (or email) |

Common failures and what to do:

- **`git push --dry-run failed`**: the deploy key is not registered, or
  "Allow write access" was not ticked (section 6.3).
- **`still has CHANGE_ME`**: a value in `jobs.env` was not filled in or
  blanked (section 6.4).
- **`no alert channel delivered`**: `VIVEK_TELEGRAM_ENABLED` is not `1` in
  `jobs.env` (section 4.3), the token or chat id is wrong, or you never sent
  your bot a first message.
- **`:80/:443 are held by another process`**: something else (possibly part of
  ICT) uses the web ports. Do not stop it. Use Option A, or ask Claude about
  fronting the scanner with a Cloudflare Tunnel (a connection the server makes
  outwards, so it needs no open port; this is a follow-up, not built yet).
- **`Yahoo answers ...`** (not 200): Yahoo is refusing this server's address.
  Try again later; if it persists, the server needs a different address.
- **`does not resolve` / `resolves to ... none of which is ... this box`**:
  the hostname points somewhere else; fix it at your DNS provider, or use the
  Binary Lane permalink.
- **`NTPSynchronized=no`**: the clock is not syncing. This is a machine-wide
  setting, so on `ict-bot` check with your ICT setup before changing it.
- **`RAM is ... and NO swap`** (WARN): section 4.1.

**Going ahead without an alert channel** (section 4.3 explains the risk).
This runs preflight with the risk acknowledgement, turning that one FAIL into
a WARN:

```bash
sudo VIVEK_ACCEPT_NO_ALERT_CHANNEL=1 /usr/local/lib/vivek5/bin/preflight.sh
```

---

## 9. Dry run

A dry run is a real job on the server with publishing switched off: it
downloads prices, scans, updates the server's own copy of the book, and pushes
nothing to GitHub. GitHub stays the only writer while you test.

**Paste these two helper commands into your SSH window once per login.** They
define two short commands, `v5` (run the scanner's control program exactly
the way the scheduled jobs run it: as the `vivek5` user, with the settings in
`jobs.env`, at low priority) and `v5dry` (the same, with publishing forced
off). Defining them changes nothing.

```bash
v5() {
  sudo systemd-run --quiet --wait --pipe --collect --unit="vivek5-cli-$(date +%s)-$RANDOM" \
    -p User=vivek5 -p EnvironmentFile=/etc/vivek5/jobs.env -p Environment=TZ=UTC \
    -p WorkingDirectory=/opt/vivek5/app \
    -p Nice=10 -p CPUWeight=20 -p IOSchedulingClass=best-effort -p IOSchedulingPriority=7 -p MemoryHigh=1G \
    -- /opt/vivek5/venv/bin/python -m scanner.vps "$@"
}
v5dry() {
  sudo systemd-run --wait --pipe --collect --unit="vivek5-dryrun-$(date +%s)-$RANDOM" \
    -p User=vivek5 -p EnvironmentFile=/etc/vivek5/jobs.env -p Environment=TZ=UTC \
    -p WorkingDirectory=/opt/vivek5/app \
    -p Nice=10 -p CPUWeight=20 -p IOSchedulingClass=best-effort -p IOSchedulingPriority=7 -p MemoryHigh=1G \
    -- /usr/bin/env VIVEK_GIT_PUBLISH=0 /opt/vivek5/venv/bin/python -m scanner.vps "$@"
}
```

(Why `/usr/bin/env VIVEK_GIT_PUBLISH=0` and not a setting: `jobs.env` says
`VIVEK_GIT_PUBLISH=1`, and a setting from the file would win over one given
next to it. Putting it on the program's own command line always wins.)

**The three dry runs.** Each one really runs the job; none pushes anything.

1. The crypto job (quick, and crypto trades every day):

   ```bash
   v5dry run crypto_bot.yml reason=manual
   ```

2. The kill switch, in its own dry mode (it also runs the freshness watchdog,
   which may send you a Telegram message if the server's copy of the data is a
   few hours old; that is expected on a dry run):

   ```bash
   v5dry run kill_switch.yml dry_run=true
   ```

3. The full ASX scan, the real size test. Start it at a quiet time (a weekend
   is ideal). In a SECOND SSH window, run `watch -n 5 free -m` to watch memory
   while it works (press Ctrl+C to stop watching).

   ```bash
   v5dry run scan.yml market=asx reason=manual
   ```

**What to look for in the output.**

- A line `publish: VIVEK_GIT_PUBLISH=0 - not committing (no-op)`: proof that
  nothing was pushed.
- The job's last line, for example
  `=== crypto_bot.yml ok exit=0 in 95s (waited 0s for locks)`. `ok` is what
  you want.
- systemd's summary at the very end, including `Memory peak:` (section 4.1).

**Then read the ledger.** This prints the run diary; it changes nothing.

```bash
v5 ledger
```

Each line is one job: its name, its last status (`ok`, `failed`, `skipped`,
`halted`), exit code, when it ended, when it last succeeded and last failed,
how many failures in a row (`x0` is good), and its last message (a dry run
says `publish disabled`).

**If a dry run failed:** the ledger remembers the failure, and the front door
reports it (`/api/vps` answers 503), which would stop cutover at step 1. Fix
the cause, then run the same dry run again until it says `ok`.

**Safety net you should know about.** Even if you forgot the `0`, the server
refuses to push before cutover: it has no record yet of the last published
commit (`state/publish_head`), so its publish step stops with "fail-closed"
and pushes nothing. You should still always use `v5dry` before cutover.

The dry runs leave test data in the server's working copy. Cutover resets that
copy to GitHub's latest at step 5, so there is nothing to clean up.

---

## 10. Cutover

### 10.1 Before you start

- [ ] Preflight shows `0 FAIL`, and you have read every WARN.
- [ ] All three dry runs ended `ok`, and `v5 ledger` shows them `ok`.
- [ ] You received the Telegram test messages (or you chose the risk in
      section 4.3 knowingly).
- [ ] `GH_ADMIN_TOKEN` is created (section 4.5); optionally the Cloudflare
      token, account id and project name (section 4.6).
- [ ] A copy of `GH_DISPATCH_TOKEN` is in your password manager (section 4.7).
- [ ] It is a quiet time: a Saturday or Sunday is ideal (ASX and NASDAQ
      closed; only crypto runs). Allow 45 to 60 minutes.
- [ ] You are in **your own SSH window**, not the Claude session: cutover asks
      for hidden tokens.

### 10.2 Run it

This is the switch. It changes GitHub (15 workflows off, one variable set),
Cloudflare (three settings) and the server (the vivek5 units start). It
prompts before anything happens and stops at the first problem.

```bash
sudo /usr/local/lib/vivek5/bin/cutover.sh
```

(If you chose to go without an alert channel:
`sudo VIVEK_ACCEPT_NO_ALERT_CHANNEL=1 /usr/local/lib/vivek5/bin/cutover.sh`.)

What each step does, as the script prints it:

- **step 0: preflight.** Runs preflight again and stops unless it is green.
  Asks for `GH_ADMIN_TOKEN` (typing is hidden: paste and press Enter). Checks
  the token works: `token ok for FakeCurrency/googy-boys-scanner`.
- **step 1: start OUR Caddy + the API adapter.** The first time the kit ever
  starts anything. Caddy fetches the HTTPS certificate, then the script checks
  `https://<your hostname>/api/vps` answers 200.
- **step 2: Cloudflare Pages.** Asks for a Cloudflare API token. Paste it
  (then the account id and project name `googy-boys-scanner`) and the script
  makes the change itself; or press Enter with it blank and do it by hand
  (section 10.3), then answer `y` to `All three done?`.
- **step 3: disable the 15 GitHub workflows** and set the repository variable
  `VPS_ACTIVE=1` (a second lock: even a re-enabled scan, crypto, close or
  scan-kick workflow does nothing while it is 1).
- **step 4: drain.** Waits until no GitHub run of those workflows is still
  queued or running (up to 30 minutes), then checks once more a minute later.
- **step 5: pristine start.** Resets the server's two copies of the project to
  GitHub's latest and records that point (`state/publish_head`).
- **step 6: enable every vivek5 timer** and the two path units.
- **step 7: assert.** Checks every timer has a next run time and the front
  door is set to come back after a reboot. If anything is wrong it runs
  rollback automatically and stops.
- **step 8: the post-cutover checklist** (section 10.6 has the full version).

### 10.3 The Cloudflare step by hand (if you left the token blank)

1. dash.cloudflare.com > **Workers and Pages** > `googy-boys-scanner` >
   **Settings** > **Variables and Secrets** (Production).
2. Add `DISPATCH_URL`, type **Text**, value
   `https://<your hostname>/api/dispatch`.
3. Add `DISPATCH_TOKEN`, type **Secret**, value = the server's token. In a
   second SSH window, this prints it (it changes nothing; do not paste it into
   a chat):

   ```bash
   sudo sed -n 's/^DISPATCH_TOKEN=//p' /etc/vivek5/api.env
   ```

4. Delete `GH_DISPATCH_TOKEN` (you saved a copy in section 4.7).
5. Cloudflare applies variable changes only to NEW deployments, so redeploy:
   **Deployments** > the latest production deployment > the three dots >
   **Retry deployment**.
6. Back in the cutover window, answer `y`.

Do not use `ops.yml action=cf-set-var` for `DISPATCH_TOKEN`: that route
records the value in the run's inputs on GitHub, and the repo is public.
(`DISPATCH_URL` and the delete are fine through `ops.yml` if you prefer.)

If you gave cutover the Cloudflare token, it made the three changes but did
not redeploy. Redeploy right after cutover (step 5 above, or ask a Claude
session to run `ops.yml` with `action=cf-redeploy`). Until then the site's
buttons still point at GitHub, which is now switched off, and answer with an
error; the server's first data push (within the hour) also triggers a fresh
deployment.

### 10.4 Troubleshooting a stopped cutover

- **step 1 does not answer 200:** read `sudo journalctl -u
  vivek5-caddy.service -n 50` (certificate problems show here: port 80
  closed, or the hostname does not point at the server) and `sudo journalctl
  -u vivek5-api.service -n 50`. A 503 means the ledger shows a failed or
  halted scan, crypto, kill switch or backup run: re-run that dry run until it
  is `ok`.
- **step 3 `could not disable`:** the token lacks Actions write or Variables
  write. Nothing else was changed; make a correct token and run cutover again.
- **step 4 runs out after 30 minutes:** GitHub runs are still going. Wait (or
  cancel them on GitHub's Actions page) and run cutover again; the workflows
  stay switched off meanwhile.
- **step 6 or 7 fails:** cutover has already rolled back automatically. Read
  the `not armed:` line, fix, run preflight, try again.

### 10.5 What you should see in the first hour

(The minute past the hour is the same in Melbourne and in UTC.)

- `v5 ledger` shows `update` every 5 minutes (`up to date at ...` or
  `synced to ...`), `kill_switch.yml ok` at :15 and :45, `crypto_bot.yml ok`
  at :22 with a `pushed` commit, and the :52 crypto backstop as `skipped`
  (normal: the data was already fresh).
- On GitHub, new commits on `main` by `vivek5-vps@<server name>`.
  `commit_sentinel.yml` shows one warning about the new author name. That is
  expected.
- Cloudflare Pages deploys after each data commit, as it does today, and the
  site's crypto data time moves forward.
- `https://<your hostname>/api/vps` answers with `"ok":true`.
- Telegram stays quiet. A message means something to look at.

This shows every timer and when it fires next; it changes nothing:

```bash
systemctl list-timers --all 'vivek5-*'
```

### 10.6 Post-cutover checklist

- [ ] **Delete `GH_ADMIN_TOKEN` on GitHub now** (Settings > Developer
      settings > Fine-grained tokens > the token > Delete). It was single use.
- [ ] If you made a Cloudflare token only for cutover, delete it too.
- [ ] If cutover did the Cloudflare step, redeploy Pages (section 10.3).
- [ ] Watch the first crypto run: `v5 ledger`, or live:
      `sudo journalctl -u vivek5-crypto-bot.service -f` (Ctrl+C stops
      watching).
- [ ] Confirm a data commit by `vivek5-vps@<server name>` lands on `main`
      within the hour.
- [ ] Press SCAN on the site once and watch it arrive:
      `sudo journalctl -u vivek5-spool.service -f`.
- [ ] Add the two `ops.yml` secrets on GitHub (repo > Settings > Secrets and
      variables > Actions > New repository secret): `VPS_DISPATCH_URL` =
      `https://<your hostname>/api/dispatch`, and `VPS_DISPATCH_TOKEN` = the
      value printed by
      `sudo sed -n 's/^DISPATCH_TOKEN=//p' /etc/vivek5/api.env`.
- [ ] Set up the outside monitor on `/api/vps` (section 12.14).
- [ ] Remove Claude's admin rights if you used section 5 (step 9 there).
- [ ] Phase 2 when you are ready (section 11).

---

## 11. Phase 2: the server serves the website

Only when Phase 1 has been calm for a while.

1. **Choose the SCAN/close password.** This asks for a password twice and
   prints its scrambled form (a "bcrypt hash", starting `$2a$`). It changes
   nothing.

   ```bash
   sudo /opt/vivek5/caddy/caddy hash-password
   ```

2. **Put the hash in the front door settings.** Open the file, set
   `VIVEK_API_BASIC_USER=` to a login name of your choice and paste the hash
   exactly as printed after `VIVEK_API_BASIC_HASH=` (no quotes, nothing
   else).

   ```bash
   sudo nano /etc/vivek5/caddy.env
   ```

3. **Switch to Phase 2.** This installs the Phase 2 front door, checks it,
   reloads Caddy, sets `VIVEK_PHASE=2` and restarts the API. It asks for
   `yes`.

   ```bash
   sudo /usr/local/src/vivek5/deploy/bin/install.sh --units --phase 2
   ```

4. **Check it.** Open `https://<your hostname>/` in a browser. The site loads
   from your server. Pressing SCAN or close asks for the login from step 2
   once per browser session.
5. **DNS.** The site is at whatever name `VIVEK_DOMAIN` holds. To use a nicer
   name later, point its DNS A record at the server, change `VIVEK_DOMAIN`,
   re-run step 3, and update the two `DISPATCH_URL` values (Cloudflare Pages
   and the `VPS_DISPATCH_URL` GitHub secret).
6. **Cloudflare Pages: mirror or delete.** Keep it and
   `googy-boys-scanner.pages.dev` stays a working mirror (its buttons still
   send requests to your server, without the password, exactly as in Phase
   1). Delete the Pages project and only your server serves the site; then
   move any outside monitor that watches `pages.dev/api/health` to
   `https://<your hostname>/api/health`.

---

## 12. Day-2 operations

Remember to paste the `v5` helper (section 9) once per SSH login.

### 12.1 What runs when

| Job | When (server timers) |
|---|---|
| ASX scans | weekdays 11:07, 12:07, 13:07, 14:07, 15:07, 16:07, close scan 16:30, backstop 17:15 (Sydney time, which is Melbourne time) |
| NASDAQ scans | weekdays 10:37, 11:07 to 15:07 hourly, close scan 16:07, backstop 17:15 (New York time; overnight in Melbourne) |
| Crypto + paper bot | every hour at :22, freshness backstop at :52 |
| Kill switch + watchdog | every hour at :15 and :45 |
| Morning plays digest | weekdays, tries every 30 minutes until that market's post-close data has landed, then sends once: ASX from 06:15 UTC (16:15 Melbourne, 17:15 in summer), US from 20:15 UTC (06:15 Melbourne next morning, 07:15 in summer) |
| PhaseMap, confluence, reco note | daily 08:30, 08:45, 08:52 UTC (18:30 to 18:52 Melbourne, an hour later in summer) |
| Backups | daily 21:35 UTC, backstop 23:35 UTC (morning in Melbourne) |
| Edge pipeline (alert returns) | daily 22:20 UTC, backstop 23:50 UTC |
| Evidence brief | daily 21:00 UTC |
| Momentum | weekdays 06:30 and 21:30 UTC, daily 00:30 UTC, every 3 hours at :41, and after each plays digest |
| Backtests | lens: Sundays 08:00 UTC; VIVEK: the 1st of each month 08:00 UTC |
| Code updates | every 5 minutes |
| Housekeeping (git gc) | Sundays 03:00 UTC |

UTC to Melbourne: add 10 hours (11 hours from the first Sunday in October to
the first Sunday in April).

### 12.2 Reading the ledger

This prints the run diary; it changes nothing.

```bash
v5 ledger
```

The same as raw data, if a Claude session wants to read it:

```bash
v5 ledger --json
```

`skipped` is normal (a backstop that found fresh data, a scan outside market
hours). `failed` or `halted` on `scan.yml`, `crypto_bot.yml`,
`kill_switch.yml` or `backup_book.yml` is the thing to look at, and those
also make `/api/vps` answer 503 and send a Telegram alert. The `update`, `gc`
and `spool` lines come from the housekeeping scripts.

### 12.3 Logs, unit by unit

These show logs; they change nothing. `-n 100` shows the last 100 lines; `-f`
follows live (Ctrl+C stops).

```bash
sudo journalctl -u vivek5-crypto-bot.service -n 100 --no-pager
sudo journalctl -u vivek5-scan@asx.service -n 100 --no-pager
sudo journalctl -u vivek5-spool.service -f
```

The unit names: `vivek5-scan@asx`, `vivek5-scan@nasdaq`,
`vivek5-scan-close@asx`, `vivek5-scan-close@nasdaq`,
`vivek5-scan-backstop@asx`, `vivek5-scan-backstop@nasdaq`,
`vivek5-crypto-bot`, `vivek5-crypto-bot-backstop`, `vivek5-kill-switch`,
`vivek5-phasemap`, `vivek5-confluence`, `vivek5-reco-note`,
`vivek5-backup-book`, `vivek5-backup-book-backstop`, `vivek5-alert-returns`,
`vivek5-alert-returns-backstop`, `vivek5-evidence-brief`,
`vivek5-lens-backtest`, `vivek5-vivek-backtest`, `vivek5-morning-plays@asx`,
`vivek5-morning-plays@us`, `vivek5-momentum`, `vivek5-update`, `vivek5-gc`,
`vivek5-spool` (runs the site's requests), `vivek5-api` (the dispatch door),
`vivek5-caddy` (the HTTPS front door), `vivek5-api-restart`, and
`vivek5-failed@...` (the alert hook). Add `.service` to each when you use it
with `journalctl -u`.

These show every scanner unit that is currently failed, and every timer; they
change nothing:

```bash
systemctl list-units --failed 'vivek5-*'
systemctl list-timers --all 'vivek5-*'
```

Harmless messages you may see: `[kv] ... falling back to in-place writes of
kv.json` in the `vivek5-api` log (expected on this layout), and `gate not due`
lines (a job deciding it has nothing to do).

### 12.4 Trigger a scan by hand

- **Easiest:** press SCAN on the site. After cutover it queues on the server.
- **On the server:** this runs an ASX scan now, whatever the time (it is a
  real run that publishes):

  ```bash
  v5 run scan.yml market=asx
  ```

  (`market=` can be `asx`, `nasdaq`, `crypto` or `all`. For the crypto paper
  bot use `v5 run crypto_bot.yml`.) A run you start by hand prints its
  result on your screen; if it fails it does not also send a Telegram alert.
- **From a cloud Claude session:** section 12.15.

Do not use `systemctl start vivek5-scan@asx.service` for this: that is the
scheduled hourly slot, and outside market hours it correctly decides to skip.

### 12.5 Close a position by hand

- **On the site:** the close-all button and the stalled strip work as before.
  After cutover they queue the close on the server, which checks the symbol is
  really open in the book and that the price is within the sanity band of the
  book's last price.
- **On the server (CLI):** this closes one bot-book position at the price you
  give. Double-check the price: this route skips the sanity band (it is the
  operator override).

  ```bash
  v5 run close_position.yml symbol=BHP market=asx price=45.10
  ```

  Optional: `direction=short` for a short, `exit_date=2026-09-26` to book it on
  an earlier day. The default is a long in the bot book.
- **Through the API, from the server:** this sends the same request the site
  sends, with the token read straight from the settings file so it never
  appears on a command line. It queues a real close.

  ```bash
  sudo sed -n 's/^DISPATCH_TOKEN=\(.*\)$/Authorization: Bearer \1/p' /etc/vivek5/api.env \
    | curl -sS -H @- -H 'Content-Type: application/json' \
      --data '{"workflow":"close_position.yml","inputs":{"symbol":"BHP","market":"asx","price":"45.10","journal_type":"bot"}}' \
      "https://$(sudo sed -n 's/^VIVEK_DOMAIN=//p' /etc/vivek5/caddy.env)/api/dispatch"
  ```

  It answers `{"ok":true,"id":"..."}` (queued), or a plain message: `422`
  names the problem (not open, or the price is too far from the last mark),
  `429` means a cooldown or cap (section 12.13).
- **From a cloud Claude session:** `ops.yml` with `action=vps-dispatch` and
  `args={"workflow":"close_position.yml","inputs":{"symbol":"BHP","market":"asx","price":"45.10","journal_type":"bot"}}`.

If a queued close cannot run (for example during a HALT), it is never lost: it
waits in the spool and Telegram tells you the symbol, market and price.

### 12.6 HALT: what it means and what to do

**What it means.** The server is supposed to be the ONLY writer of the data
on GitHub. Before every publish (and every 5 minutes when it checks for code
updates) it looks at what landed on `main` since its own last push. If a
commit that it did not make touched any data file (the book, the scan
results, backups), it writes a HALT file, sends a CRITICAL Telegram alert,
stops writing the paper book, and pushes nothing. Typical causes: a Claude
session hand-edited a data file (for example a hand-written reco note), or a
GitHub workflow was switched back on by mistake.

While halted: the book-writing jobs (scans, crypto, closes) refuse to run;
other jobs keep running and fail safely at their publish step (nothing is
pushed, and they alert too, so a halted night is noisy on purpose); queued
closes wait as `.halted` files in the spool; `/api/vps` answers 503.

**Look first.** This prints which commits, by whom, touching which files. It
changes nothing.

```bash
sudo cat /opt/vivek5/state/HALT
```

**Then choose one.** Both wait politely for any running job to finish first,
both re-queue the waiting closes, and both clear the HALT.

- **Accept GitHub's version** (the usual choice, for example after a
  hand-written reco note): this copies every data file from GitHub into the
  server's working copy, overwriting the server's own, and prints how many
  files it replaced in each folder.

  ```bash
  v5 accept-upstream
  ```

- **Keep the server's version** (you have already fixed things by hand, or
  the foreign commit should be overwritten): this clears the HALT and moves
  the server's bookmark past those commits. The server's next publish then
  writes its own copy of each file over them.

  ```bash
  v5 clear-halt
  ```

Not sure which? Do nothing yet (the HALT is the safe state), and ask a Claude
session to read the HALT file and the commits with you. If a GitHub workflow
was re-enabled, switch it off again first.

### 12.7 How code updates land

A code change pushed to `main` (by you or a Claude session) reaches the server
within 5 minutes, through `vivek5-update`:

- it first checks for foreign data commits (section 12.6) and halts instead of
  syncing if it finds any;
- it copies in the changed CODE files only; data files on the server are
  never replaced by it;
- if `requirements.txt` changed, it installs the new Python packages;
- if the API code changed, it asks the root-owned `vivek5-api-restart` unit to
  restart the API (only if it is running);
- a job already running finishes on the old code; the next one uses the new.

### 12.8 Updating the units (when Telegram says "re-run install.sh --units")

If a change touches the service definitions, the front door config or the
admin scripts, `vivek5-update` cannot apply it (it never changes system
files). You get a WARNING telling you to run these two commands, which update
the root-owned copy of the code and then re-install the units. The second one
prints its plan and asks for `yes`.

```bash
sudo git -C /usr/local/src/vivek5 pull
sudo /usr/local/src/vivek5/deploy/bin/install.sh --units
```

Running units that changed and are long-running (the front door, the API,
timers) are restarted; a scan in progress is never interrupted.

### 12.9 Rotating the deploy key

Do this if the key may have leaked, or once a year. It is designed so pushing
never stops.

1. Make a new key next to the old one. This creates two new files and changes
   nothing else:

   ```bash
   sudo ssh-keygen -q -t ed25519 -N '' -C "vivek5-vps@$(hostname) deploy key" -f /etc/vivek5/deploy_key.new
   sudo cat /etc/vivek5/deploy_key.new.pub
   ```

2. Add that public line on GitHub as a new deploy key WITH write access
   (section 6.3).
3. Swap the files. This moves the old key aside and puts the new one in its
   place, with the permissions the kit expects:

   ```bash
   sudo mv /etc/vivek5/deploy_key /etc/vivek5/deploy_key.old
   sudo mv /etc/vivek5/deploy_key.pub /etc/vivek5/deploy_key.pub.old
   sudo mv /etc/vivek5/deploy_key.new /etc/vivek5/deploy_key
   sudo mv /etc/vivek5/deploy_key.new.pub /etc/vivek5/deploy_key.pub
   sudo chown root:vivek5 /etc/vivek5/deploy_key && sudo chmod 0640 /etc/vivek5/deploy_key && sudo chmod 0644 /etc/vivek5/deploy_key.pub
   ```

4. Run preflight; `git push --dry-run ... via the deploy key` must PASS.
5. Delete the OLD key on GitHub (Settings > Deploy keys), then delete the old
   files: `sudo rm /etc/vivek5/deploy_key.old /etc/vivek5/deploy_key.pub.old`.

### 12.10 Backups, on and off the server

- **Every day** the backup job snapshots the paper book and journal state into
  `backups/` and pushes it to GitHub (30 kept). GitHub is therefore the
  off-server copy of the data, as today.
- **Optional second copy:** set `VIVEK_BACKUP_TARGET=user@host:/path` in
  `jobs.env` to also copy `backups/` to another machine. That machine must
  accept SSH from the `vivek5` user without a password prompt; once it is set,
  a failed copy fails the backup job loudly.
- **Not in git, so keep your own copy:** the settings in `/etc/vivek5`
  (Telegram token and chat id, the webhook). Keep those values in your
  password manager. The `DISPATCH_TOKEN` and deploy key can simply be
  regenerated. `/opt/vivek5/state` (ledger, queues, cooldowns) rebuilds itself.
- **If the server dies:** create a new one and follow this runbook again. All
  the data is on GitHub. If your Binary Lane plan offers server backups,
  switching them on for the scanner's server is a cheap extra layer.

### 12.11 Disk

These show free space and what uses it; they change nothing.

```bash
df -h /opt/vivek5
sudo du -sh /opt/vivek5/app/.git /opt/vivek5/publish/.git /opt/vivek5/venv
sudo journalctl --disk-usage
```

The project history grows about 0.7 GB a month. The watchdog sends a CRITICAL
alert when less than 3 GB is free. Housekeeping runs every Sunday. If space
gets tight, resize the disk in the Binary Lane panel; moving the old history
out of git is a listed follow-up (section 14).

### 12.12 The watchdog and alerts

What sends a Telegram message:

- any scanner unit that fails (the alert includes its last 30 log lines);
- a HALT or a second writer (CRITICAL);
- a failed scan, crypto, close, kill switch or backup run (CRITICAL);
- stale data (the freshness watchdog, run inside the kill switch and crypto
  jobs; it says a problem once, reminds every 6 hours, and announces
  recovery);
- `disk_low` (CRITICAL, under 3 GB free);
- a queued request that could not even be attempted (refused, unreadable);
- `vivek5-update` asking you to re-run `install.sh --units`, or reporting the
  code lock busy for an hour with no job explaining it.

CRITICAL goes to Telegram and email (email only if configured and not
blocked); WARNING goes to Telegram. Every alert is also written to a file on
the server, even when nothing could be delivered. This shows the last 50; it
changes nothing:

```bash
sudo tail -n 50 /opt/vivek5/state/alerts.log
```

### 12.13 Cooldowns and caps on the dispatch door

So a stuck button or a leaked token cannot flood the server:

| Request | Cooldown | Daily cap |
|---|---|---|
| scan | 5 minutes per market | 40 |
| close | 60 seconds per symbol (a close-all counts as one batch) | 60 |
| plays digest | 5 minutes per slot | 12 |

More than 20 requests already waiting also answers `429` ("the runner is
behind"). The Cloudflare Functions apply their own matching cooldowns first.
The command line on the server (`v5 run ...`) is not limited.

### 12.14 `/api/vps` and an outside monitor (UptimeRobot)

`https://<your hostname>/api/vps` is a read-only status page anyone can open.
It answers **200** with `"ok":true` when all is well, and **503** when: a
HALT is in place, OR the last run of the scan, crypto, kill switch or backup
job failed or halted, OR the ledger cannot be read. It shows statuses and
times only, never messages or arguments.

Telegram alerts come FROM the server, so if the whole server is down nothing
arrives. An outside monitor closes that gap. In UptimeRobot (free): Add New
Monitor > HTTP(s) > URL `https://<your hostname>/api/vps` > interval 5
minutes > alert contact: your email or Telegram. It alerts on anything other
than 200. The existing monitor on `googy-boys-scanner.pages.dev/api/health`
keeps working too: it reads the published data, so it now also notices if the
server stops publishing.

### 12.15 Cloud Claude sessions after cutover

- To start a scan, a close or the digest, a cloud session dispatches `ops.yml`
  with `action=vps-dispatch`, for example
  `args={"workflow":"scan.yml","inputs":{"market":"asx"}}`. This needs the
  two secrets from section 10.6. The answer `202 {ok, id}` means queued.
- The old way (touching `.github/scan-kick`, or `dispatch_scan.yml`) is
  switched off and guarded. It does nothing now.
- A session must never switch a disabled workflow back on, and must never
  edit data files on `main` (the book, `public/data`, `data`, `backups`). The
  server would HALT (section 12.6). Code changes are fine.
- CLAUDE.md carries these rules for every session.

---

## 13. Rollback (going back to GitHub)

Rollback switches the server's jobs off and GitHub's back on. Use it if the
server is not working and you cannot fix it quickly.

1. Create a NEW `GH_ADMIN_TOKEN` (section 4.5; the cutover one was deleted).
2. In your own SSH window, run rollback. It changes the server (every vivek5
   unit stopped, the API first so no new request is accepted), GitHub (the 15
   workflows back on, `VPS_ACTIVE=0`) and prints what only you can do. It asks
   before it starts and asks for the token (hidden).

   ```bash
   sudo /usr/local/lib/vivek5/bin/rollback.sh
   ```

3. It lists any request that was accepted but not yet run ("THESE DISPATCHES
   WERE ACCEPTED BUT NOT EXECUTED"). Re-issue those on the site or on GitHub
   once the workflows are back.
4. In Cloudflare Pages: add `GH_DISPATCH_TOKEN` back (the copy from section
   4.7, type Secret), delete `DISPATCH_URL` and `DISPATCH_TOKEN`, and redeploy
   (section 10.3, step 5). Until you do, the site's SCAN and close buttons
   answer with an error.
5. Delete the new `GH_ADMIN_TOKEN` on GitHub.
6. If you suspect the server was compromised: delete its deploy key on GitHub
   (Settings > Deploy keys).

Nothing is lost: the server's last pushes are on `main`, and GitHub's next
scan simply continues from them.

---

## 14. Known limits and follow-ups

Stated plainly, so none of them surprises you later.

- **Alert texts that say `python -m scanner.vps accept-upstream`** mean
  `v5 accept-upstream` when you type it yourself (section 12).
- **The git history keeps growing** (2.4 GB, about 0.7 GB a month), because
  the data is still published as commits. Moving `backups/` and `data/history`
  out of git, or stopping data commits, is a follow-up.
- **The site's status lamp still links to GitHub's Actions page** for
  failures; it does not read the server's ledger yet. After cutover, the truth
  is `v5 ledger` and `/api/vps`.
- **Some friendly error messages on the site still mention GitHub** (the
  Functions' wording was left unchanged on purpose).
- **The front door config is only fully checked in CI when a new enough Caddy
  is available there**; otherwise that test is skipped. `install.sh --units`
  and preflight always check it on the server.
- **The API's rate-limit memory (`kv.json`) is rewritten in place** because
  of the server's folder permissions. A crash mid-write can only reset
  cooldowns and caps, never touch the book.
- **A hand-written reco note by a Claude session causes a HALT** (any foreign
  data commit does). Narrowing that rule is your call; until then run
  `v5 accept-upstream` after such a note.
- **While halted, jobs that do not write the book still run** and fail at
  their publish step. Skipping them instead is your call.
- **The first week on the server:** the morning plays digest's 7-day "already
  sent" memory and the watchdog's alert memory start empty (GitHub's copies do
  not transfer), so a few recent names may be sent again and a current stale
  finding may be announced once more.
- **The NASDAQ second scan** runs at 11:07 New York all year (GitHub ran it at
  11:37 during US summer time). Same number of scans.
- **Not yet proven on a real box, by design of how it was built:** the
  script parts that need a running systemd (timer next-run times, the restart
  path unit, `try-restart`) were tested against stand-ins. Cutover step 7
  checks them for real and rolls back by itself if any is wrong.
- **Deliberately not set:** a system-call filter on the API service (it could
  break Node in ways only a real box would show).
- **A Cloudflare Tunnel** (so the server needs no open port at all) is a
  follow-up if ports 80/443 are ever unavailable.

---

## 15. Your checklist: the things only you can do, in order

1. Choose Option A (recommended: a new Binary Lane server, Ubuntu 24.04 LTS,
   Melbourne, 4 GB RAM, or 2 GB and install with `--with-swap`) or Option B
   (Change Plan `ict-bot` to 4 GB first, at a time ICT LIVE can restart).
2. Create the Telegram bot and note `TELEGRAM_BOT_TOKEN` and
   `TELEGRAM_CHAT_ID` (section 4.3).
3. Put the Telegram values in `jobs.env` and set `VIVEK_TELEGRAM_ENABLED=1`
   (section 4.3), or knowingly choose `VIVEK_ACCEPT_NO_ALERT_CHANNEL=1`.
4. Fetch the plays Discord webhook address and save a copy of
   `GH_DISPATCH_TOKEN` from Cloudflare (section 4.7).
5. Optional: set up the Claude Code Remote Control session on the server
   (section 5).
6. Run the install (`sudo git clone ... /usr/local/src/vivek5`, then
   `install.sh --phase 1`), read the printed plan, type `yes` (section 6).
7. Register the printed deploy key on GitHub with write access (section 6.3).
8. Fill in `/etc/vivek5/jobs.env` yourself (Telegram, webhook; broker lines
   stay blank) and `/etc/vivek5/caddy.env` (`VIVEK_DOMAIN`), then
   `install.sh --units` (sections 6.4 to 6.7).
9. If you use a firewall, keep 22, the ICT ports, and 80/443 on the scanner's
   server open (section 7).
10. Run preflight until it shows 0 FAIL and read its output; run the three
    dry runs (sections 8 and 9).
11. Create `GH_ADMIN_TOKEN` (and optionally the Cloudflare token) (sections
    4.5 and 4.6).
12. Run `cutover.sh` yourself in your own SSH window on a quiet day; do the
    Cloudflare step by hand if you gave no Cloudflare token, and redeploy
    Pages (section 10).
13. Delete `GH_ADMIN_TOKEN` (and the Cloudflare token if single-use).
14. Add the GitHub secrets `VPS_DISPATCH_URL` and `VPS_DISPATCH_TOKEN`.
15. Set up the UptimeRobot monitor on `https://<your hostname>/api/vps`.
16. Remove Claude's sudo file (`/etc/sudoers.d/vivek-claude`) when finished.
17. Later, optional: Phase 2 (section 11).
