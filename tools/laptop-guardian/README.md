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
| `guardian.py` | the watchdog: memory pressure, process classes, tiered actions, diary, `ask` | 65 tests (policy + macOS parsers on output recorded from a real Mac) |
| `scratch.py` | the disk side: census of app data folders in tiers, safe reclaim, swap-ceiling check | 12 tests |
| `chrome-extension/` | tabs you are done with go to sleep; tabs untouched for days get parked as bookmarks | 1 end-to-end run in real Chromium |

The native menu bar app with a basic (dad) mode and an advanced mode is specified in
[PLAN.md](PLAN.md), with the work order for building it on a Mac.

## Install (two minutes)

```bash
git clone --branch claude/charming-einstein-ln9egd https://github.com/jpenzell/imagination-applied.git ~/guardian-src
cd ~/guardian-src/tools/laptop-guardian
python3 test_guardian.py && python3 test_scratch.py   # 77 tests, should say OK twice
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

It never touches the active tab, pinned tabs, tabs playing sound, or sites on the
never-touch list (claude.ai, chatgpt.com, Meet, Zoom, Gmail, Calendar by default, because a
conversation may be mid-run). Basic mode is one choice (gentle / normal / aggressive);
advanced mode exposes the minutes and the list. The badge shows the tab count.

Load it: chrome://extensions, turn on Developer mode, "Load unpacked", pick the
`chrome-extension` folder. Test it: `node chrome-extension/test_extension.mjs` (launches a
throwaway Chrome profile, needs nothing but Node 22 and Chrome).

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
guardian.py chrome                 tab census: how many tabs, how many duplicates
guardian.py chrome --close-duplicates   close duplicate URLs (all stay in History)
guardian.py doctor                 check install, permissions, swap ceiling, login items
guardian.py install | uninstall    launchd agent
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
- Under launchd, the first disk census may trigger macOS "python3 would like to access your
  Downloads folder" prompts. Allow them once; denying only makes those rows read 0.

## Uninstall

```bash
python3 guardian.py uninstall      # removes the launchd agent; logs and config stay
```
