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

## Install (two minutes)

```bash
git clone --branch claude/charming-einstein-ln9egd https://github.com/jpenzell/imagination-applied.git ~/guardian-src
cd ~/guardian-src/tools/laptop-guardian
python3 test_guardian.py          # 25 policy tests, should say OK
python3 guardian.py status        # what it sees right now
python3 guardian.py install       # launchd agent: starts at login, restarts if it dies
python3 guardian.py test-notify   # grant notification permission the first time
```

macOS ships `python3` with the Xcode Command Line Tools (`xcode-select --install` if
`python3` is missing). Nothing else is needed.

Do this on each Mac. Logs and config are per machine and carry the hostname, so the
two diaries never get confused.

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

## Commands

```
guardian.py status                 pressure, swap, compressor, thermal, disk, top apps by class
guardian.py watch --once --dry-run one cycle, print decisions, exit
guardian.py watch --once --dry-run --simulate level=4,free=3   exercise the policy on fake readings
guardian.py report --hours 24      episodes, usual suspects, actions
guardian.py ask                    Claude Code / Codex diagnoses the diary (needs `claude` or `codex` on PATH)
guardian.py config --apply-suggestion   apply the config change `ask` proposed
guardian.py chrome                 tab census: how many tabs, how many duplicates
guardian.py chrome --close-duplicates   close duplicate URLs (all stay in History)
guardian.py doctor                 check install, permissions, swap ceiling, login items
guardian.py install | uninstall    launchd agent
guardian.py pause | resume
guardian.py config [--set key=value ...]
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

- Memory is measured as resident set size from `ps`. Activity Monitor's "Memory" column
  also counts compressed pages, so under heavy pressure guardian's numbers read lower
  than Activity Monitor's for the same process. Rankings stay the same.
- It cannot see inside Chrome. It knows a renderer is 3 GB, not which tab that is. Use
  `chrome://discards` or the `chrome` subcommand for that.
- It cannot free wired GPU memory or kernel leaks, and some slowness is not memory at all
  (thermal throttling is reported; a failing SSD or a Spotlight reindex is not).
- Notifications come from `osascript`, which macOS lists under "Script Editor" in
  System Settings > Notifications. Allow it once.
- `chrome` needs Automation permission for Google Chrome the first time (macOS prompts).
- Policy tests run anywhere; the macOS sampling code paths (`sysctl`, `vm_stat`, `pmset`,
  launchd) were written against documented output formats and verified on Linux fallbacks
  only. Run `doctor` and `status` first on each Mac and read what they print.

## Uninstall

```bash
python3 guardian.py uninstall      # removes the launchd agent; logs and config stay
```
