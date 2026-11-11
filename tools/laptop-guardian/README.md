# Laptop Guardian

A small watchdog that lives on a Mac which runs AI agents (Claude Code, Codex, Cowork)
and a lot of Chrome, and keeps it from grinding to a halt. One Python file, no
dependencies, runs as you, never as root.

It does three things the usual "memory cleaner" apps don't:

1. **Watches the right signal.** Free RAM on a Mac is supposed to be near zero. The real
   freeze signal is the kernel's own memory-pressure level plus growing swap and
   compressor use. Guardian reads that directly (`kern.memorystatus_vm_pressure_level`),
   the same signal behind Activity Monitor's pressure graph. It stays silent at green.
2. **Knows who started what.** Every process you own is classified: your Chrome, a
   Chrome that an agent launched (Playwright, headless, temp profile), a Chrome you opened
   with remote debugging for Codex, a Claude/Codex CLI session, a local model worker, a dev
   server, a GUI app. Chrome's forty helper processes fold into one line. That is what lets
   it act on an abandoned automation browser while never touching the Chrome you are
   typing in.
3. **Learns your machine.** It keeps a diary (one line every 30 s, every decision with its
   reason). `guardian ask` hands that diary to Claude Code or Codex and gets back a plain
   English diagnosis, a one-time to-do list, and a config change you review before it is
   applied. After a bad day (three pressure episodes) it does this on its own and leaves a
   diagnosis file for you.

**Status:** working prototype. Three parts, all tested; first real run on a Mac (8 GB
M-series Air, macOS 27) on 2026-11-10, which found the fixes in the git log:

| part | what | tests |
|---|---|---|
| `guardian.py` | the watchdog: memory pressure, process classes, tiered actions, diary, `ask` | 104 tests (policy + macOS parsers on output recorded from a real Mac) |
| `menubar/` | the shield in the menu bar: what is going on, one-click fixes, a few settings | built and run on a real Mac; the click path is covered by the guardian tests |
| `scratch.py` | the disk side: census of app data folders in tiers, safe reclaim, swap-ceiling check | 17 tests |
| `archive.py` | old work folders move to an external drive: copy, read the copy back, compare, then remove | 20 tests, plus a real move of 5 GB to a USB drive |
| `chrome-extension/` | tabs you are done with go to sleep; tabs untouched for days get parked as bookmarks | 54 logic checks that run on any Mac, plus 1 end-to-end run in real Chromium |

The native menu bar app with a basic (dad) mode and an advanced mode is specified in
[PLAN.md](PLAN.md), with the work order for building it on a Mac.

## Install (two minutes)

```bash
git clone --branch claude/charming-einstein-ln9egd https://github.com/jpenzell/imagination-applied.git ~/guardian-src
cd ~/guardian-src/tools/laptop-guardian
python3 test_guardian.py && python3 test_scratch.py && python3 test_archive.py   # 141 tests, should say OK three times
python3 guardian.py menu install       # the shield in the menu bar (builds a small app; needs Apple's Command Line Tools)
python3 guardian.py scratch       # what is filling the disk
python3 guardian.py status        # what it sees right now
python3 guardian.py install       # launchd agent: starts at login, restarts if it dies
python3 guardian.py test-notify   # grant notification permission the first time
```

macOS ships `python3` with the Xcode Command Line Tools (`xcode-select --install` if
`python3` is missing). Nothing else is needed.

Or run it all in one go, read-only, with the output saved for review:

```bash
bash mac-first-run.sh            # tests, doctor, status, dry-run watch, simulate, scratch, chrome
bash mac-first-run.sh --install  # same, then autopilot on + notification + agent checks
```

Do this on each Mac. Logs and config are per machine and carry the hostname, so the
two diaries never get confused.

## Autopilot: always running, optimizing on its own

```bash
python3 guardian.py autopilot on
```

That is the one switch for "keep my Mac running smoothly". It installs the login agent if
needed, turns on act mode, and adds two things nudge/act alone do not do:

- **Daily hygiene.** Once a day (4 am by default, and once about ten minutes after a fresh
  start) it clears old logs and Trash, and clears rebuildable caches when they add up to
  more than 5 GB or the disk has less free space than twice your RAM. Caches of an app
  that is running are left alone until it quits.
- **Bounded self-tuning.** After a bad day (three pressure episodes) it asks Claude Code or
  Codex for a diagnosis. Numeric thresholds the diagnosis suggests (cooldowns, idle times,
  memory limits) are applied on the spot, each within a fixed range. Anything else it
  suggests, such as a kill switch or a mode change, waits in `suggested-config.json` for
  you. Every change is logged and `guardian.py config --undo` reverts the last one.

The running agent reloads its config within a minute of any change, so `autopilot on`,
`autopilot off`, `config --set` and self-tuning all take effect without a restart.

```
$ python3 guardian.py autopilot status
autopilot: ON   mode=act   agent loaded: True   paused: False
  last hygiene: 2026-11-11T04:00:31 freed 2.3GB
  last self-tuning: never
  Last 24h: 1 pressure episodes, under pressure 4% of the time, 3 actions. Usual suspects: Google Chrome, agent:codex.
```

## The shield in the menu bar

```bash
python3 guardian.py menu install     # build it, put it in ~/Applications, start it now and at login
python3 guardian.py menu status
python3 guardian.py menu uninstall   # the helper keeps running
```

One click on the shield shows what is going on and what you can do about it right now.

- **The icon.** A plain shield means nothing needs you. An amber dot means there is a
  problem with a fix, or a good moment to act (for example, ChatGPT has grown and its agent
  is idle). A filled shield with a red dot means memory is critically low. Two bars mean
  paused; a dashed shield means the helper is not running, with a button to start it.
  Memory being merely tight puts no dot there: on a small Mac it always is.
- **Needs a look.** Each entry says what is wrong and carries the one button that helps.
- **Using the most memory.** The five biggest apps, in GB as Activity Monitor counts them.
- **Fix it now.** Trim an AI app's idle helpers (interrupts nothing), refresh a bloated AI
  app (it asks first, and warns if its agent was just working), close duplicate Chrome tabs, clear rebuildable caches, move old work folders to
  a drive. These work at any time, not only when guardian would have offered.
- **Pause** for 30 minutes, an hour, three hours or until tomorrow; it resumes on its own.
- **Settings**, the few that matter: how much guardian does on its own, how often it
  notifies, what happens when ChatGPT grows, whether it offers to move old work folders.
  Every change goes through the same history as `config --set`, so `config --undo` works.
- **Today's report, a check-up, an AI diagnosis** open as text.

The app is only a face: about 800 lines of Swift, 16 MB, no permissions. It reads one small
file the helper writes after every sample (`~/Library/Logs/guardian/state.json`) and turns a
click into a request file (`~/.config/guardian/requests/`) that the helper picks up within a
second. So every action is still carried out, and logged, by the one program that has the
permissions. The helper accepts a short fixed list of actions and settings; anything else in
that folder is ignored. Requests older than ten minutes are dropped.

Notifications changed with it. The first real day produced 43 notifications that all said
memory was tight and offered nothing to do. Now a notification means a critical spell or
something you can act on, and the icon carries the steady state. "Whenever memory is
tight" in Settings brings the old behaviour back.

## Getting ahead of a bad spell

A refresh is relief, not prevention. On the first real Mac, ChatGPT was back at 10 GB half
an hour after being refreshed to 2.3 GB: that is what five Codex threads cost. Three things
came out of measuring where that memory sits.

```bash
python3 guardian.py trim            # dry run: idle helper programs that could close
python3 guardian.py trim --yes
python3 guardian.py threads         # agent threads written recently, with the size of their histories
```

- **Trim idle helpers.** Codex starts three tool servers and a few scripting helpers for
  every thread it opens. Ninety minutes after a relaunch, 62 of 80 had used no processor
  time at all and held 1.2 GB. Trim asks only those to stop: helpers of a listed app, over
  an hour old, idle for half an hour, with no children and not part of a running session.
  The app, its windows and anything working are untouched, and nothing is force-killed.
  Tested by closing two: Codex did not restart them and carried on. Not yet known: whether
  an old thread you return to later can still use a tool whose helper was trimmed; if one
  does not respond, a refresh restores it. Scripting helpers run in their thread's folder,
  so those of a thread written in the last half hour are spared. The tool servers carry
  nothing that names their thread, so one serving the thread in use can be among those
  closed. For that reason trimming on its own is a switch that starts off ("When memory
  fills up fast: Trim idle helpers on its own" in the menu's Settings). Switched on, and in
  autopilot, guardian trims when the early warning fires or memory is critical, at most
  once every half hour, and says what it did.
- **Flag heavy threads.** The Codex engine holding a thread with a 1.2 GB history open was
  itself using 1.1 GB. Guardian lists a thread once its history passes 300 MB, says so once
  in a notification, and counts how many threads are in use at the same time. It cannot
  start a fresh thread for you; it tells you when one would help.
- **Warn early.** Swap climbing 1 GB within ten minutes came before 19 of that day's 25
  critical spells, usually by 5 to 12 minutes; 9 of its 16 firings were followed by one.
  When it fires, the shield gets its amber dot and the menu offers the gentlest fix first:
  trim if there is something to trim, otherwise a refresh. No notification; the dot is
  enough for a signal that is right a little over half the time.

## Disk: what the free space was spent on

Free disk is the ceiling for swap, so on a small Mac it matters as much as memory.

```bash
python3 guardian.py disk                 # free space, trend, where it went, who gets it back
python3 guardian.py disk --snapshot      # measure everything now (about a minute) and compare
python3 guardian.py disk --big           # biggest items in Downloads, Documents, Desktop
python3 guardian.py disk --big --in ~/Documents/Codex
```

- **A ledger.** Every six hours (and on demand) guardian measures every place it knows, with
  no byte counted twice, plus the places outside the home folder: the per-user temp folder,
  swap files, /Applications, Apple's model and update downloads, system logs. `disk` and
  `report` show what changed between snapshots and how much of the change nothing measured
  explains. The first real Mac lost 8 GB in two hours while every home folder guardian
  watched grew 0.1 GB; it was leftover temp folders, which is why the ledger looks there.
- **A fast-drop alert.** When free space falls 3 GB within an hour, guardian measures and
  names what grew.
- **Caches cleared at the right moment.** An app's caches cannot be cleared while it runs,
  and AI apps and browsers are always running. In act mode, when one of them quits and less
  than 40 GB is free, its caches are cleared right then.
- **Snapshots are compared only with their equals.** A snapshot taken without Full Disk
  Access cannot see Mail, Messages, Photos or other apps' containers. On the first real Mac
  the helper got that access at midday and the next alert said pictures had grown 14 GB and
  app containers 8 GB; they had only been hidden. Each snapshot now records how much it
  could see, and two that differ are not compared.
- **Yours to decide.** Documents, Downloads, agent session histories and VM images are
  measured and listed, never touched. `disk --big` dates each folder by the newest change
  anywhere inside it, not by the folder's own date. Old work folders can move to an
  external drive: see the next section.

## Archive: old work folders move to an external drive

Caches are the small part. On the first real Mac the biggest thing on the disk was 41 GB of
dated Codex work folders in `~/Documents/Codex`. That is your work, so guardian never
deletes it. What it can do, when you say so, is move the folders nobody is using to an
external drive and bring any of them back on request.

```bash
python3 guardian.py archive                    # dry run: what could move, what stays and why, where to
python3 guardian.py archive --yes              # copy, check each copy, then remove the folders here
python3 guardian.py archive --only 2026-09-17  # just these     --older-than 14    --to "My Passport"
python3 guardian.py archive --root ~/Documents/Codex/2026-09-23/project/work   # look inside one folder
python3 guardian.py archive --list             # what is on a drive now
python3 guardian.py archive --restore 2026-09-17
python3 guardian.py archive --offer off        # stop guardian asking on its own
python3 guardian.py archive --second-copy      # copy archives that have one home to a second drive, checked
python3 guardian.py archive --second-home DIR  # a folder where you keep your own copies; guardian looks there
python3 guardian.py archive --check            # read every reachable copy and compare it with its checksum
```

- **"Unused" is measured, not guessed.** A folder qualifies when no file or folder anywhere
  inside it has changed for 30 days *and* no Codex or Claude Code thread has worked in it in
  that time (guardian reads the working folder from the top of each recent session log; it
  never writes there). Both rules came from the first real Mac. Going by each folder's own
  date, 37 GB looked a month old; a 22 GB folder dated September had build logs from two
  weeks before, and the oldest folder of all, unchanged for two months, was the working
  folder of a thread that had been active that morning. The honest number was 5 GB.
- **Nothing is removed on trust.** Each folder becomes one `.tar` file on the drive, written
  under a temporary name. Guardian then reads that file back from the drive, bypassing the
  file cache, and compares it with the folder entry by entry and byte by byte. Only if
  everything matches, and the folder did not change during the copy, is the file given its
  final name, the move recorded, and the folder removed. Any doubt (a mismatch, a full or
  unplugged drive, a file that changed, a cloud placeholder that is not really on this
  disk) leaves the folder exactly where it was and no half copy behind.
- **You can always find it again.** The drive gets `Guardian Archive/<this Mac>/Documents/
  Codex/<name>.tar` with a small `.json` card beside it (date, size, checksum). The folder
  the work came from gets one text file, `ARCHIVED-BY-GUARDIAN.txt`, listing what went where
  and the command that brings each one back. `archive --restore` unpacks to the original
  place, checks the result against the drive's copy, and refuses to overwrite anything or
  to fill the disk. The drive keeps its copy; guardian never deletes from the drive.
- **One drive is not a backup.** After a move the folder exists in one place. Guardian says
  so in the question before you agree, in the notification afterwards, in `archive --list`,
  in `doctor`, behind the shield, and once a week for as long as it stays true. It keeps
  track of where each archive has copies. With a second drive connected, the shield offers
  to copy the archives there: the first copy is read once and must still match the checksum
  recorded when it was written, and the new copy is read back. If you keep your own copy
  somewhere (a cloud folder, a network share), name the folder with `--second-home` and
  guardian recognises a copy by name and exact size, marked as unchecked. A copy counts
  while its drive is away; it stops counting if the file disappears or changes size. When
  the first drive is not connected, `--restore` reads from the second copy.
- **It asks; it never decides.** When less than 40 GB is free, an external drive is
  connected, at least 2 GB would move and you are at the keyboard, guardian shows one dialog
  with three buttons. "Not now" (the default button, so a stray Return moves nothing) means
  no question for three days. "Show me" opens the full list as a text file and asks again
  in ten minutes. "Move them" starts the copy as its own low-priority process; a
  notification tells you what moved and how much is free. A diagnosis cannot change any of
  the `archive` settings on its own.
- **Which drives.** Mounted under `/Volumes`, local, writable, APFS / Mac OS Extended /
  exFAT, and not another volume of the startup disk. Network shares and FAT32 are left out.
- **Limits.** Finder tags and other extended attributes are not kept; sockets and pipes are
  not copied. Measured on a USB hard drive: about 26 MB/s end to end (write, read back,
  compare), so 5 GB takes a few minutes and 20 GB about a quarter of an hour. Memory use
  stays near 20 MB whatever the folder size. Only the children of the configured roots are
  offered (`archive.roots`, default `Documents/Codex`); `~/Library`, `~/Downloads` and every
  dot-folder (transcripts, sessions) are refused as roots.

## Refresh when idle: getting memory back from an AI app that has grown

Long-running AI apps pile up. On the first real Mac (8 GB) the ChatGPT app, which embeds
Codex, held 10 GB in 99 processes: about 75 were helpers over an hour old that had done
almost nothing, and 3.8 GB of its caches could never be cleared because it never quit.

```bash
python3 guardian.py refresh                       # what it sees and what it would do, read-only
python3 guardian.py refresh ChatGPT --now         # do it now (refuses while Codex is working)
python3 guardian.py refresh ChatGPT --mode auto   # ask | auto | never
```

A refresh quits the app the way Cmd+Q does, clears that app's caches, reopens it in the
background, and writes what came back (memory before and after, disk freed) to the diary
and to `report`. The running agent considers it only when all of these hold: the app is
listed under `refresh.apps`, it holds more than `min_gb` (6), the Mac is under memory
pressure, its agent has been idle for `agent_idle_minutes` (20; for Codex that means no
session file written), the app is not the one in front, and it was not refreshed in the
last six hours.

Consent is per app:

- **ask** (default, and only for ChatGPT out of the box): a dialog with *Not now*,
  *Always when idle* and *Refresh now*. It waits until you are at the keyboard to ask.
- **auto**: no dialog; it acts when the agent is idle and you have been away from the
  keyboard for three minutes. Act mode only. Needs an activity signal for the app.
- **never**: left alone. Any app not listed is never touched.

It is never forced. If the app does not quit within 45 seconds it is left running, and
nothing is cleared or relaunched. The AI diagnosis may tune the thresholds but can never
change the consent. Chats and threads live in the app's own storage and are kept; open
windows may need reopening.

What autopilot never does: close an app you can see without your say-so, interrupt a
running agent task, delete transcripts, sessions,
downloads or anything outside rebuildable caches, or act while paused or while you are
presenting. `autopilot off` drops back to nudge mode (still watching, only notifying).

## The three modes

| mode | what it does | default |
|---|---|---|
| `observe` | log only, never speaks | |
| `nudge` | log + notifications that name the offender; tells you what `act` would have done | yes |
| `act` | nudge + reclaims known-safe targets (below). GUI apps are never killed | |

Run in `nudge` for a few days, read `guardian report`, then switch:

```bash
python3 guardian.py config --set mode=act
launchctl kickstart -k gui/$(id -u)/local.guardian
```

### What `act` mode is allowed to do

| situation | action | why it is safe |
|---|---|---|
| Automation Chrome (Playwright / headless / temp profile) whose parent process is gone and that has been idle 10 min (2 min under pressure) | close it | nobody is driving it; it is the classic leak from an agent run that ended badly |
| Automation Chrome over 2 GB while the Mac is under memory pressure | close it | the agent that owns it can relaunch; your real Chrome is a different class |
| Any non-GUI process at 90%+ CPU for 10 min | `renice` it to low priority | reversible, loses nothing, gives the UI its CPU back |
| Local model worker (Ollama runner, llama-server) over 12 GB at **critical** pressure, two samples in a row | close it | the serving daemon stays up and reloads the model on next request |
| Dev server (next, vite, webpack, astro) over 3 GB at **critical** pressure | close it | a restart is one command |
| Claude / Codex CLI session older than 24 h and idle 15 min | notify only (set `agent_sessions.kill_when_stale` to close) | your sessions matter; default is to tell you |
| One Chrome renderer (a single tab) over 2.5 GB under pressure for 5 min | notify only (set `renderers.kill_under_pressure` to close) | closing a renderer shows "Aw, Snap" on that tab; reload brings it back |
| Disk free below 20 GB | notify | swap cannot grow past free disk; low disk turns pressure into freezes |
| CPU thermally throttled | notify | the Mac is slow because it is hot, not because of RAM |

What it will never do: kill anything owned by root or another user, kill a GUI app
(anything under `/Applications/*.app`, except an automation browser), kill Finder, Dock,
Terminal, Dropbox, Claude, Codex, Chrome, Zoom, Keynote (the `protect` list), or act while
you are presenting (see quiet mode).

### Quiet mode

If Keynote or PowerPoint is running, or you are in a Zoom meeting (`CptHost` present),
notifications stop and all actions are held except closing an abandoned automation
browser. Before a talk you can also hard-pause:

```bash
python3 guardian.py pause     # until resume; survives restarts
python3 guardian.py resume
```

## The disk side ("scratch")

macOS swaps into free disk. When the folders that apps scribble into fill the disk, there
is nowhere for memory to spill and the Mac freezes instead of slowing down. So guardian
measures those folders and sorts them into tiers:

```
$ python3 guardian.py scratch
Disk free: 41.2 GB  (this is also the ceiling for swap)
Time Machine local snapshots: 6 (purgeable, but they still crowd swap; thin with: sudo tmutil thinlocalsnapshots / 50000000000 4)
Reclaimable now: 7.8 GB safe caches + up to 2.1 GB old logs/trash  ->  guardian.py scratch --reclaim safe --yes

     GB  tier      location                   what
  14.20  review    Codex sessions             Codex session logs (10GB+ is normal); back up before pruning
   6.10  safe      Chrome caches              page, script and GPU caches; Chrome rebuilds them  [Google Chrome is running; skipped until it quits]
   3.90  report    Downloads                  yours to sort; often the biggest folder
   2.40  review    Claude Code transcripts    every Claude Code conversation as JSONL; this is your history ...
   1.10  safe      Claude desktop caches      Electron caches of the Claude desktop app
   ...
```

| tier | what | who deletes |
|---|---|---|
| `safe` | rebuildable caches: Chrome, Claude desktop (Electron), ChatGPT desktop, Dropbox cache, npm/pip/brew/uv | `scratch --reclaim safe --yes`; automatically in act mode when disk drops below `disk_floor_gb` |
| `safe-old` | logs, Trash, Claude Code shell snapshots and debug logs older than 14 to 30 days | same |
| `review` | your data or expensive binaries: Codex sessions, Claude Code transcripts, iOS backups, Playwright browsers, Xcode DerivedData, Docker images | you, with a backup; guardian only measures and explains |
| `report` | Downloads, app data folders | nobody |

Caches of an app that is running are skipped until it quits. Nothing outside your home
folder is ever touched, symlinks are never followed, and the default is a dry run.

## Chrome: tabs you are done with

Guardian cannot see inside Chrome, and Chrome's own Memory Saver only acts when memory is
already tight. The extension in `chrome-extension/` does the two things that matter:

- **Sleep** tabs idle longer than an hour (`chrome.tabs.discard`): the tab stays in the
  strip, its memory is freed, it reloads when you click it.
- **Park** tabs untouched for three days: bookmarked under "Guardian Parked / date", then
  closed. Nothing is lost.

It never touches the active tab, pinned tabs, private (incognito) tabs, tabs playing sound,
or sites on the never-touch list (claude.ai, chatgpt.com, Meet, Zoom, Gmail, Calendar by
default, because a conversation may be mid-run). Basic mode is one choice (gentle / normal /
aggressive); advanced mode exposes the minutes and the list. The badge shows the tab count.

Idle is measured from when you last had the tab in front. Chrome's own number is when you
last switched *to* a tab, so version 0.1 could put a tab to sleep five minutes after you
left it, however long you had been reading it; the extension now also remembers when it
last saw each tab in front. Sleeping a tab reloads it when you come back, so text typed
into a form and not submitted is lost; pin a tab, or add its site to the list, to keep it.

Load it: chrome://extensions, turn on Developer mode, "Load unpacked", pick the
`chrome-extension` folder. After the files change (a `git pull`), click the round arrow on
its card there so Chrome picks them up. Test the logic on any Mac, no install needed:

```bash
/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc chrome-extension/test_logic_jsc.js
```

54 checks against a stand-in for Chrome: every never-touch rule, the bookmark saved before
a tab is closed, the counts. `node chrome-extension/test_extension.mjs` runs it end to end
in a throwaway Chrome profile (needs Node 22).

## Claude and ChatGPT on this Mac

`status` has a line for them:

```
  AI on this Mac  : Claude 2.3GB/4p, Claude helpers (MCP servers) 0.9GB/12p, ChatGPT 0.6GB/2p, agent:claude 1.1GB/3p, agent:codex 0.8GB/2p
```

The Claude and ChatGPT desktop apps are the `ai_app` class and are never killed. The
`node` processes the Claude app spawns (one per MCP server) fold into "Claude helpers". An
MCP server whose parent app has quit is an orphan and is closed after 10 idle minutes in
act mode. Claude Code and Codex CLI sessions are counted per tool; stale ones are reported.

## Commands

```
guardian.py status                 pressure, swap, compressor, thermal, disk, top apps by class
guardian.py watch --once --dry-run one cycle, print decisions, exit
guardian.py watch --once --dry-run --simulate level=4,free=3   exercise the policy on fake readings
guardian.py report --hours 24      episodes, usual suspects, actions
guardian.py ask                    Claude Code / Codex diagnoses the diary (needs `claude` or `codex` on PATH)
guardian.py config --apply-suggestion   apply the config change `ask` proposed
guardian.py scratch                disk census by tier; --reclaim safe|safe-old|all [--yes]
guardian.py disk                   free space, where it went, what comes back on its own; --snapshot, --big
guardian.py refresh [APP]          quit, clean and reopen a bloated AI app while idle; --now, --mode ask|auto|never
guardian.py archive                old work folders to an external drive (dry run); --yes, --list, --restore NAME
guardian.py chrome                 tab census: how many tabs, how many duplicates
guardian.py chrome --close-duplicates   close duplicate URLs (all stay in History)
guardian.py doctor                 check install, permissions, swap ceiling, login items
guardian.py install | uninstall    launchd agent
guardian.py trim [--yes]           close an AI app's idle helper programs (dry run without --yes)
guardian.py threads                agent threads in use and the size of their histories
guardian.py menu install|uninstall|status   the shield in the menu bar
guardian.py autopilot on|off|status   always running and optimizing: act mode + daily hygiene + bounded self-tuning
guardian.py pause | resume
guardian.py config [--set key=value ...] [--undo]
```

## Where things live

| path | what |
|---|---|
| `~/.config/guardian/config.json` | your overrides; every key you leave out falls back to the defaults in `guardian.py` |
| `~/.config/guardian/suggested-config.json` | the last change `ask` proposed, until you apply it |
| `~/Library/Logs/guardian/events.jsonl` | every decision with class, reason, result |
| `~/Library/Logs/guardian/samples.tsv` | one line per 30 s: level, free %, swap, compressor, load, disk, top 5 |
| `~/Library/Logs/guardian/digest-YYYY-MM-DD.md` | daily report, written at 8 am (`digest_hour`) |
| `~/Library/Logs/guardian/diagnosis-*.md` | what the AI said |
| `~/Library/Logs/guardian/state.json` | what the helper last saw, for the menu bar icon |
| `~/.config/guardian/requests/` | clicks from the menu bar, picked up within a second |
| `~/Applications/Guardian.app` | the menu bar app |
| `~/Library/Logs/guardian/disk-ledger.jsonl` | one disk measurement per line |
| `~/Library/Logs/guardian/archive.jsonl` | every folder moved to a drive or brought back, with where it is |
| `<drive>/Guardian Archive/<Mac>/...` | the moved folders, one `.tar` each |
| `~/Library/LaunchAgents/local.guardian.plist` | the agent |

A gap in `samples.tsv` means guardian itself was not running.

## Reading the first report

After a day in `nudge` mode:

```bash
python3 guardian.py report
python3 guardian.py ask
```

The report tells you what percentage of the day was spent under pressure and which
apps were named most often. The three usual outcomes:

- **Chrome is the top name every time.** Run `guardian.py chrome`. More than ~60 tabs or
  duplicates by the dozen is the cause. Turn on Memory Saver (chrome://settings/performance),
  audit extensions (each one runs in every tab), and let `--close-duplicates` do the boring part.
- **An automation browser or an agent session shows up at odd hours.** That is a run that
  ended without cleaning up. `act` mode handles the browser; for sessions decide whether
  you want `kill_when_stale`.
- **Pressure episodes with nobody big named.** Many medium processes, no single hog:
  look at `by class` in `status`. Often it is too many agent sessions open at once, or the
  swap ceiling (disk free below RAM size, see `doctor`).

## Config example

```json
{
  "mode": "act",
  "notify_cooldown_seconds": 900,
  "watch": ["Scratch", "Scratch Desktop", "Figma"],
  "agent_sessions": {"stale_after_hours": 36},
  "renderers": {"kill_under_pressure": true},
  "quiet_when_running": ["Keynote", "CptHost", "Microsoft PowerPoint", "OBS"]
}
```

`watch` names apps that should always be surfaced in `status` and reports even when
they are not the biggest (the question "is Scratch the problem?" gets answered either way).

## How it compares to what already exists

| project | the good idea guardian borrows | what it lacks |
|---|---|---|
| [mac-memory-guard](https://github.com/TomGranot/mac-memory-guard) | kernel pressure level as the only trigger; helpers folded per app | never acts; one dialog, no memory of yesterday |
| [oomguard](https://github.com/trentshaines/oomguard) | leaky strike counters; "a job is a process group"; disk as swap ceiling | kills the biggest job regardless of what it is; Swift build |
| [jäger](https://github.com/deltartificial/jager) | fast lane for agent-driven browsers; stale lane for forgotten sessions | Rust toolchain; no pressure awareness; no notion of GUI vs. automation Chrome |
| [mac-yolo-safeguards](https://github.com/IgorGanapolsky/mac-yolo-safeguards) | never touch GUI apps; orphaned automation Chrome is the known-safe reclaim | built around iOS Simulators and one person's agent fleet |
| [mac-optimize](https://github.com/kylebrodeur/mac-optimize) | disk hygiene, Codex session backups | notification only; separate tools, no single picture |

Guardian's additions: the process classifier (user vs. automation vs. debug browser,
agent sessions, model workers), quiet mode for presentations, the per-machine diary, the
`ask` loop that turns the diary into a diagnosis and a reviewed config change, and the
Chrome tab census.

## Limits, honestly

- Memory is the physical footprint from libproc (`proc_pid_rusage`), the number in
  Activity Monitor's "Memory" column, so compressed and swapped pages count. The first
  real run showed why: `ps` RSS read a 1.9 GB renderer as 150 MB on an 8 GB Mac with 9 GB
  of swap in use. RSS is only the fallback for processes libproc will not report.
- It cannot see inside Chrome. It knows a renderer is 3 GB, not which tab that is. Use
  `chrome://discards` or the `chrome` subcommand for that.
- It cannot free wired GPU memory or kernel leaks, and some slowness is not memory at all
  (thermal throttling is reported; a failing SSD or a Spotlight reindex is not).
- Notifications come from `osascript`, which macOS lists under "Script Editor" in
  System Settings > Notifications. Allow it once.
- `chrome` needs Automation permission for Google Chrome the first time (macOS prompts).
- Policy tests run anywhere; the macOS sampling code paths (`sysctl`, `vm_stat`, `pmset`,
  launchd) were written against documented output formats and verified on Linux fallbacks
  only. `bash mac-first-run.sh` runs the whole read-only first pass on a Mac and saves the
  output; add `--install` to also switch autopilot on. Read what it prints.
- On macOS, Apple's and Homebrew's `python3` really execute a `Python.app` inside a
  framework. Guardian treats those as command-line processes, not GUI apps, so Python MCP
  servers fold under Claude and guardian itself can be reniced like any other script.
- macOS decides per program which of your folders it may read, and the background agent is
  a different program from the same command typed in Terminal. On the first real Mac the
  agent was refused Documents, Downloads and Desktop with no prompt anyone saw: its ledger
  read Documents as 0 GB (it held 41) and its archive scan found nothing to move. Guardian
  now treats "refused" as unknown, never as empty. The agent checks its own access when it
  starts, tells you once a week while something is refused, and `guardian.py doctor` prints
  its answer and the steps. What worked on that Mac: macOS never listed the helper under
  Files and Folders, so the grant is Privacy & Security > Full Disk Access, with the real
  Python program dragged into the list. Two things had to be true at once. The program
  allowed must be the real one (`Python.app` inside the Command Line Tools), and the helper
  must be *started* as that program: started through `/usr/bin/python3`, which is a launcher
  stub, the same grant was refused. `guardian.py install` now resolves the stub to the real
  program, and `doctor` warns when the helper is started through a stub. The price: that
  path contains the Python version, so after an Apple tools update run `install` again;
  and the grant covers any background job run by that Python, not Guardian alone.

## Uninstall

```bash
python3 guardian.py uninstall      # removes the launchd agent; logs and config stay
```
