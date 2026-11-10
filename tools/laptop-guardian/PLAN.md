# Guardian: from prototype to a product your dad could run

Status as of 2026-11-10. What exists is a working, tested prototype in Python (the
watchdog), a tested Chrome extension (tab sleep and park), and a disk layer. None of it has
run on a Mac yet. This document is the plan for turning it into a native, zero-overhead
Mac app with a basic and an advanced mode, and the work order for building it on a real
Mac with Claude Code or Codex.

## 1. What the slowdown actually is (and what we are optimizing for)

Josh's machines run Claude (desktop app, Claude Code CLI, Cowork, Claude in Chrome), ChatGPT
(desktop app, chatgpt.com, Codex CLI and app) and Chrome, all day, on two Macs. Four
things compound:

1. **Memory.** Chrome renderers, the Claude desktop app (Electron, plus one `node` process
   per MCP server it has configured), ChatGPT desktop, and every open Claude Code / Codex
   session (each a `node` process of 300 MB to 2 GB). When the sum passes physical RAM,
   macOS compresses and swaps; past that, it freezes.
2. **Disk as the swap ceiling ("scratch").** macOS can only swap into free disk. Codex
   session logs (`~/.codex/sessions`, 10 GB+ is normal), Claude Code transcripts
   (`~/.claude/projects`), Chrome and Electron caches, Playwright browsers, npm caches,
   Dropbox's cache and Time Machine local snapshots all grow without bound. Low disk
   turns "slow" into "frozen".
3. **Orphans.** Runs that end badly leave behind headless Chromes, MCP server processes
   whose parent app quit, and idle agent sessions. They hold memory for days.
4. **CPU and heat.** A runaway process pins a core; a hot Mac throttles itself to 60%
   and everything feels slow regardless of memory.

Guardian measures all four, acts only where an action is safe by construction, and
explains everything else in plain language.

## 2. Product shape

A **menu bar app** (no Dock icon, no window unless you click). One icon whose color is the
answer to "is my Mac OK?":

- green: fine
- amber: under memory pressure or disk getting low, guardian is handling it
- red: critical, click to see what to close

**Basic mode (default, the dad mode).** The only setting is one switch, "Keep my Mac
running smoothly", which is the prototype's `autopilot on`: always running, acts on the
safe-by-construction list, tidies caches daily, tunes its own thresholds within fixed
ranges from its diagnoses, and reports what it did. Clicking the icon shows:

```
Your Mac is OK.                              (or: "Your Mac is struggling")
Memory  ████████░░  busy        Disk  ██████░░░░  58 GB free

Biggest right now
  Chrome            6.1 GB   (142 tabs, 40 asleep)        [Tidy tabs]
  Claude            2.3 GB   (12 helpers)
  ChatGPT           0.7 GB
  Codex sessions    1.9 GB   (3 running, 1 idle since Tue)  [Close idle]

Today: 2 abandoned browsers closed, 1.4 GB of caches cleared, 31 tabs put to sleep.
[Free up space now]   [Pause while I present]   Settings · Advanced
```

Every line is a sentence a non-technical person can act on. The buttons do the obvious thing
and say what they did.

**Advanced mode.** The same window gains: the process table by class, thresholds, the
mode switch (observe / nudge / act), the protect and never-touch lists, the diary, the
scratch census with tiers, "Ask Claude about this" (sends the diary to the Claude Code or
Codex CLI if installed) and the per-rule log.

**Chrome extension.** Ships alongside; the app's "Tidy tabs" button and the extension's
popup are the same feature from two sides. The extension is the only thing that can see
which tabs are done (last activation time), so it owns sleep and park; the app owns
everything outside the browser.

## 3. Architecture: zero overhead

| layer | technology | why |
|---|---|---|
| App + UI | Swift, SwiftUI `MenuBarExtra`, macOS 14+ | native, ~20 MB resident, no runtime, Apple-signed |
| Pressure | `DispatchSource.makeMemoryPressureSource` | the kernel wakes us on warn/critical; no polling needed for the main signal |
| Process scan | `proc_listallpids` + `proc_pidinfo` (libproc), `sysctl` | ~1 ms for 500 processes (jäger measured 0.6 ms); every 60 s idle, 10 s under pressure |
| Disk | `statfs`, `FileManager` enumeration on a background thread, at most hourly | census of named folders only, never a full-disk walk |
| Actions | `kill(2)`, `setpriority(2)`, `FileManager.removeItem`, `osascript` only for Chrome tab census | all user-level; no helper tool, no root, no kernel extension |
| Persistence | JSONL diary in `~/Library/Logs/Guardian`, config in `~/Library/Application Support/Guardian/config.json` | same formats as the prototype so the Python tool, the app and `ask` all read the same diary |
| Launch at login | `SMAppService.mainApp` | the supported, user-visible way (shows in System Settings > Login Items) |
| Updates | Sparkle, or none for personal use | |
| Distribution | Developer ID signed + notarized DMG | otherwise Gatekeeper blocks it on dad's Mac |

Overhead budget: under 0.1% CPU averaged, under 30 MB resident, zero network. The app
must never be in its own top-20 list.

The Python prototype remains the **reference implementation**: its policy engine and its
36 tests define the behavior; the Swift port is checked against the same synthetic
scenarios (ported test cases), and against the prototype's live output side by side on
the same Mac.

## 4. What the engine knows about Claude and ChatGPT specifically

| thing | how guardian sees it | what it does |
|---|---|---|
| Claude desktop app | `ai_app` class; its child processes (`node` MCP servers, Claude Code launched from the app) fold into "Claude helpers" | surfaces as one line with a helper count; never killed |
| MCP servers whose parent died | `mcp_orphan` class: `node`/`npx`/`uvx` with "mcp" in the command and parent = launchd | closed after 10 min idle (act mode) |
| Claude Code / Codex CLI sessions | `agent_session` class, keyed by tool | counted; stale (24 h old, idle 15 min) ones are reported, closed only if you opt in |
| Cowork | tracked as part of the Claude app tree; its VM/session data is measured under "Claude desktop data" | measured, never deleted |
| ChatGPT desktop | `ai_app` class; caches under `~/Library/Caches/com.openai.chat` in the `safe` tier | surfaced; caches reclaimable when the app is not running |
| chatgpt.com, claude.ai tabs | extension never sleeps or parks them (a conversation may be mid-run) | left alone by default; configurable |
| Transcripts and sessions (`~/.claude/projects`, `~/.codex/sessions`) | `review` tier | measured and explained; pruning only with a verified backup, never automatic |
| Electron caches (Claude), Chrome caches | `safe` tier | cleared automatically under disk pressure when the app is not running |

## 5. Work order for a session on the Mac (Claude Code or Codex, with Xcode installed)

Do these in order; each step is verifiable on its own.

1. **Baseline with the prototype.** `python3 guardian.py doctor && python3 guardian.py status
   && python3 guardian.py scratch`. Fix any macOS parsing surprise in the prototype first
   (sysctl / vm_stat / pmset / ps output), with a test. Install it, run 3 days in nudge mode.
   This diary is what the app is judged against.
2. **Load the extension unpacked** (chrome://extensions > Developer mode > Load unpacked >
   `chrome-extension/`). Run `HEADED=1 node chrome-extension/test_extension.mjs`. Use it for
   a week; tune the basic levels.
3. **Create the Xcode project** `Guardian` (SwiftUI, macOS 14, App Sandbox OFF because we
   read other processes and delete caches; hardened runtime ON for notarization).
   Package layout: `GuardianCore` (Swift package: sampling, classifier, engine, scratch,
   diary; no UI; unit tests ported from `test_guardian.py` and `test_scratch.py`) and the
   `Guardian` app target (MenuBarExtra, Basic/Advanced views, settings, login item).
4. **Port in this order**, running the prototype side by side: sampling (compare
   `status` output), classifier (compare group keys and sizes), engine (replay the
   prototype's `samples.tsv` and `events.jsonl` through the Swift engine and diff the
   decisions), scratch census (compare GB per location), actions.
5. **Basic view** as in section 2. Copy is sentences, not labels. Every action button
   reports back in the same panel ("Closed 2 abandoned browsers, freed 1.1 GB").
6. **Advanced view**, mode switch, lists, diary viewer, "Ask Claude" (shells out to
   `claude -p` exactly as the prototype's `ask` does).
7. **Sign and notarize** with the Developer ID; build a DMG; install on the second Mac from
   the DMG as a stranger would; then on dad's Mac.
8. **Retire the Python agent** on each Mac (`guardian.py uninstall`) once the app has run a
   week with the same decisions.

## 6. What else a professional version needs

- **A real-Mac baseline before any more code.** Everything above is designed from
  documented behavior; the three-day diary from step 1 will change thresholds and may
  change priorities (for example, if Codex sessions turn out to dominate memory, "Close
  idle sessions" moves into Basic mode).
- **Chrome tab identity for renderers.** The app sees "a 3 GB renderer"; only the extension
  can name the tab. A tiny native-messaging bridge between the two would let the app say
  "the Figma tab is using 3 GB". Nice-to-have, not v1.
- **Safari and Arc** profiles for the classifier if either is in use.
- **An account-free, telemetry-free posture** stated in the UI. The diary never leaves
  the machine unless you press "Ask Claude", and then it goes to the CLI you already use.
- **Two-Mac view.** Both diaries carry the hostname; a later version can show the other
  Mac's last digest via Dropbox (write-only mirror, consistent with decision 36).
- **A weekly plain-English digest** ("This week Chrome was the problem 4 days out of 5;
  closing duplicate tabs saved 2 GB a day") as the thing a non-technical user actually
  reads. The prototype's `report` is the seed.
- **Recovery path.** Everything guardian deletes is a rebuildable cache or an old log;
  everything it closes is relaunchable; every parked tab is a bookmark. The UI should say
  this in one line wherever an action is offered, and "Undo" should exist where it can
  (reopen parked tabs, restart a closed dev server command).
