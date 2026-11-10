#!/usr/bin/env python3
"""
guardian -- keeps a Mac that runs AI agents and Chrome from grinding to a halt.

One file, standard library only, runs as you (never root). It samples the
kernel's own memory-pressure signal, classifies every process you own into
"what is this and who started it", and responds in tiers:

  observe  log only
  nudge    log + macOS notifications that NAME the offender (default)
  act      nudge + reclaim known-safe targets (orphaned automation Chrome,
           runaway non-GUI processes get reniced, oversized model workers,
           forgotten dev servers). GUI apps are never killed.

It also keeps a diary (events.jsonl, samples.tsv) and can hand that diary to
Claude Code or Codex ("guardian ask") for a diagnosis in plain English plus a
suggested config change you review before it is applied.

Subcommands:  status  watch  ask  report  chrome  scratch  disk  refresh  archive
              autopilot  doctor  install  uninstall  pause  resume  config  test-notify

Prior art this borrows from, with thanks:
  TomGranot/mac-memory-guard   kernel pressure level as the only trigger
  trentshaines/oomguard        leaky strike counters, "a job is a process group"
  deltartificial/jager         fast lane for agent-driven browsers, stale lane
  IgorGanapolsky/mac-yolo-safeguards   "never touch GUI apps", orphan Chrome
  kylebrodeur/mac-optimize     disk free is your swap ceiling
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path

VERSION = "0.1.0"
IS_MAC = sys.platform == "darwin"
HOME = Path.home()
LABEL = "local.guardian"
CONFIG_DIR = HOME / ".config" / "guardian"
CONFIG_PATH = CONFIG_DIR / "config.json"
PAUSE_PATH = CONFIG_DIR / "paused"
STATE_DIR = HOME / ".local" / "state" / "guardian"
LOG_DIR = (HOME / "Library" / "Logs" / "guardian") if IS_MAC else (STATE_DIR / "logs")
EVENTS_PATH = LOG_DIR / "events.jsonl"
SAMPLES_PATH = LOG_DIR / "samples.tsv"
STDOUT_LOG = LOG_DIR / "guardian.out.log"
PLIST_PATH = HOME / "Library" / "LaunchAgents" / f"{LABEL}.plist"
HOSTNAME = socket.gethostname().split(".")[0]

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "mode": "nudge",
    "interval_seconds": 30,
    "notify": True,
    "notify_cooldown_seconds": 600,
    "pressure_warn_level": 2,
    "free_pct_floor": 8,
    "disk_floor_gb": 20,
    "top_n": 4,
    "cpu": {
        "runaway_pct": 90,
        "sustain_seconds": 600,
        "renice_to": 15,
    },
    "automation_browser": {
        "markers": [
            "ms-playwright", "Chrome for Testing", "agent-browser",
            "puppeteer", "--headless", "--enable-automation",
            "--user-data-dir=/tmp", "--user-data-dir=/var/folders",
            "--user-data-dir=/private/tmp",
        ],
        "orphan_idle_seconds": 600,
        "idle_cpu_pct": 1.0,
        "pressure_idle_seconds": 120,
        "memory_mb": 2048,
    },
    "agent_sessions": {
        "markers": ["claude", "codex", "claude-code", "cowork"],
        "stale_after_hours": 24,
        "idle_cpu_pct": 5,
        "idle_seconds": 900,
        "kill_when_stale": False,
    },
    "renderers": {
        "markers": ["Helper (Renderer)"],
        "memory_mb": 2500,
        "sustain_seconds": 300,
        "kill_under_pressure": False,
    },
    "dev_server": {
        "markers": ["next-server", "vite", "webpack", "nodemon", "astro dev"],
        "memory_mb": 3000,
    },
    "model_worker": {
        "markers": ["ollama runner", "llama-server", "lms-llama", "mlx_lm"],
        "memory_mb": 12000,
    },
    "safe_kill_classes": ["automation_browser", "model_worker", "dev_server", "mcp_orphan"],
    "ai_apps": ["Claude", "ChatGPT", "Codex", "Cowork", "Claude Code"],
    "scratch": {"auto_reclaim_in_act_mode": True, "cooldown_hours": 6},
    # Disk: a ledger entry every N hours, an alert when free space falls fast, and clearing a
    # quit app's caches while the disk is tight.
    "disk": {"ledger_hours": 6, "alert_drop_gb": 3, "alert_window_minutes": 60,
             "clear_caches_on_quit": True, "clear_on_quit_below_gb": 40},
    # Refresh when idle. Per app: "ask" (a dialog, default), "auto" (when its agent is idle and
    # you are away; act mode only) or "never". Only apps listed here are ever touched.
    "refresh": {
        "apps": {"ChatGPT": "ask"},
        "activity_paths": {"ChatGPT": [".codex/sessions"], "Codex": [".codex/sessions"]},
        "min_gb": 6,
        "agent_idle_minutes": 20,
        "user_idle_minutes": 3,
        "cooldown_hours": 6,
        "snooze_minutes": 120,
        "only_under_pressure": True,
        "clear_caches": True,
        "reopen": True,
        "quit_timeout_seconds": 45,
        "settle_seconds": 75,
    },
    # Archive: work folders that no file change and no agent thread has touched for N days
    # can move to an external drive. Always asked, never automatic, and nothing is removed
    # until its copy has been read back from the drive and matches. Only the children of
    # the listed roots are ever offered.
    "archive": {
        "roots": ["Documents/Codex"],
        "session_dirs": [".codex/sessions", ".claude/projects"],
        "min_age_days": 30,
        "min_folder_mb": 50,
        "destination": "",
        "offer": True,
        "offer_below_gb": 40,
        "offer_min_gb": 2,
        "snooze_days": 3,
        "scan_hours": 12,
    },
    "autopilot": False,
    "hygiene": {"hour": 4, "safe_tier_when_reclaimable_gb": 5, "safe_tier_when_disk_below_x_ram": 2},
    "protect": [
        "Finder", "Dock", "WindowServer", "loginwindow", "Terminal", "iTerm2",
        "tmux", "Dropbox", "Claude", "Codex", "ChatGPT", "Cowork", "Google Chrome",
        "Safari", "zoom.us", "Keynote", "Microsoft PowerPoint", "guardian",
    ],
    "watch": ["Scratch", "Scratch Desktop"],
    "quiet_when_running": ["Keynote", "CptHost", "Microsoft PowerPoint"],
    "digest_hour": 8,
    "ai": {
        "command": "auto",
        "auto_after_episodes": 3,
        "max_runs_per_day": 1,
        "timeout_seconds": 240,
        "auto_apply_tuning": False,
    },
}

# Keys the AI diagnosis may change on its own in autopilot, with the range it may use.
# Anything else it suggests (kill switches, lists, mode) waits for a human.
TUNABLE = {
    "interval_seconds": (15, 120),
    "notify_cooldown_seconds": (120, 7200),
    "pressure_warn_level": (2, 4),
    "disk_floor_gb": (10, 100),
    "cpu.runaway_pct": (70, 100),
    "cpu.sustain_seconds": (120, 3600),
    "renderers.memory_mb": (1000, 8000),
    "renderers.sustain_seconds": (60, 1800),
    "automation_browser.orphan_idle_seconds": (120, 3600),
    "automation_browser.memory_mb": (1000, 8000),
    "agent_sessions.stale_after_hours": (6, 168),
    "agent_sessions.idle_seconds": (300, 7200),
    "hygiene.safe_tier_when_reclaimable_gb": (1, 50),
    "refresh.min_gb": (3, 20),
    "disk.alert_drop_gb": (1, 20),
    "disk.clear_on_quit_below_gb": (10, 200),
    "refresh.agent_idle_minutes": (5, 240),
    "refresh.cooldown_hours": (1, 48),
}
CONFIG_HISTORY = CONFIG_DIR / "config-history.jsonl"


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path = CONFIG_PATH) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if path.exists():
        try:
            cfg = deep_merge(cfg, json.loads(path.read_text()))
        except Exception as e:  # pragma: no cover
            print(f"guardian: could not parse {path}: {e}; using defaults", file=sys.stderr)
    if cfg["mode"] not in ("observe", "nudge", "act"):
        cfg["mode"] = "nudge"
    return cfg


def flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in (d or {}).items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, key))
        else:
            out[key] = v
    return out


def unflatten(flat: dict) -> dict:
    out = {}
    for k, v in flat.items():
        node = out
        parts = k.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = v
    return out


def split_tuning(suggestion: dict):
    """(auto-applicable, needs-review). Only TUNABLE keys inside their range are auto-applicable."""
    auto, review = {}, {}
    for k, v in flatten(suggestion).items():
        rng = TUNABLE.get(k)
        if rng and isinstance(v, (int, float)) and not isinstance(v, bool) and rng[0] <= v <= rng[1]:
            auto[k] = v
        else:
            review[k] = v
    return unflatten(auto), unflatten(review)


def apply_config_change(changes: dict, why: str) -> dict:
    """Merge changes into the config file, keeping a history so it can be undone."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    before = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    after = deep_merge(before, changes)
    CONFIG_PATH.write_text(json.dumps(after, indent=2) + "\n")
    with CONFIG_HISTORY.open("a") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), "why": why,
                            "changes": changes, "before": before}) + "\n")
    log_event("config", why=why, changes=changes)
    return after


def undo_config_change():
    """Restore the config as it was before the last change. Returns the undone entry or None."""
    if not CONFIG_HISTORY.exists():
        return None
    lines = CONFIG_HISTORY.read_text().splitlines()
    if not lines:
        return None
    last = json.loads(lines[-1])
    CONFIG_PATH.write_text(json.dumps(last["before"], indent=2) + "\n")
    CONFIG_HISTORY.write_text("\n".join(lines[:-1]) + ("\n" if lines[:-1] else ""))
    log_event("config", why="undo", undone=last["changes"])
    return last


def hygiene_due(now: datetime, last_ts: float, cfg: dict, up_since: float) -> bool:
    """Daily at the hygiene hour; or once, ten minutes after a fresh start if it never ran."""
    if last_ts is None:
        return (now.timestamp() - up_since) >= 600
    if now.timestamp() - last_ts < 20 * 3600:
        return False
    return now.hour == cfg["hygiene"]["hour"]


def run_hygiene(cfg: dict, sample: dict, running: set, dry_run: bool = False) -> dict:
    """Proactive tidy-up: old logs/trash always; safe caches when they are big or disk is tight."""
    import scratch
    rows = scratch.census()
    hy = cfg["hygiene"]
    reclaimable = scratch.reclaimable_mb(rows, ("safe",), running)
    ram_mb = sample.get("mem_total_mb") or 0
    disk_mb = (sample.get("disk_free_gb") or 0) * 1024
    do_safe = reclaimable >= hy["safe_tier_when_reclaimable_gb"] * 1024 or \
        (ram_mb and disk_mb < hy["safe_tier_when_disk_below_x_ram"] * ram_mb)
    out = {"dry_run": dry_run, "freed_mb": 0, "tiers": [], "safe_reclaimable_mb": reclaimable,
           "safe_tier_run": bool(do_safe)}
    for tier in (["safe-old"] + (["safe"] if do_safe else [])):
        r = scratch.reclaim(tier, dry_run=dry_run, running=running, rows=rows)
        out["freed_mb"] += r["freed_mb"]
        out["tiers"].append({"tier": tier, "freed_mb": r["freed_mb"], "skipped": r["skipped"]})
    return out


# --------------------------------------------------------------------------
# Process model
# --------------------------------------------------------------------------

class Proc:
    __slots__ = ("pid", "ppid", "pgid", "uid", "cpu", "rss_kb", "etime_s", "cputime_s",
                 "comm", "args", "app", "cls", "key", "is_gui", "chrome_type")

    def __init__(self, pid, ppid, pgid, uid, cpu, rss_kb, etime_s, cputime_s, comm, args):
        self.pid = pid
        self.ppid = ppid
        self.pgid = pgid
        self.uid = uid
        self.cpu = cpu
        self.rss_kb = rss_kb
        self.etime_s = etime_s
        self.cputime_s = cputime_s
        self.comm = comm
        self.args = args
        self.app = None
        self.cls = "other"
        self.key = comm
        self.is_gui = False
        self.chrome_type = None

    @property
    def rss_mb(self) -> float:
        return self.rss_kb / 1024.0

    @property
    def name(self) -> str:
        return os.path.basename(self.comm) or self.comm

    def to_dict(self) -> dict:
        return {
            "pid": self.pid, "ppid": self.ppid, "cpu": round(self.cpu, 1),
            "rss_mb": round(self.rss_mb), "age_s": self.etime_s, "name": self.name,
            "app": self.app, "class": self.cls, "key": self.key,
        }


def parse_etime(s: str) -> int:
    """[[dd-]hh:]mm:ss -> seconds."""
    s = s.strip()
    days = 0
    if "-" in s:
        d, s = s.split("-", 1)
        days = int(d)
    parts = [int(float(p)) for p in s.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, sec = parts[-3:]
    return days * 86400 + h * 3600 + m * 60 + sec


APP_RE = re.compile(r"/([^/]+)\.app/")


def agent_head_match(mark: str, heads: list) -> bool:
    """'codex' matches the command 'codex' and the native binary the npm wrapper spawns
    ('codex-aarch64-apple-darwin'), but not 'codex.js' paths or folders called Codex."""
    m = mark.lower()
    return any(h == m or h.startswith(m + "-") for h in heads)


def word_in(marker: str, text: str) -> bool:
    """marker appears in text as a whole word/path segment (so 'vite' != 'invite')."""
    m = re.escape(marker.lower())
    return re.search(r"(^|[/\s\-_=])" + m + r"($|[/\s\-_.:])", text) is not None


def bundle_of(path: str):
    """Outermost .app bundle name in a path, or None."""
    m = APP_RE.search(path)
    return m.group(1) if m else None


# .app bundles that are not applications: framework-internal shims. Apple's and Homebrew's
# python3 really execute ".../Python.framework/.../Resources/Python.app/Contents/MacOS/Python",
# so without this every Python process (guardian itself, Python MCP servers) would read as
# a GUI app called "Python" and be exempt from renice.
# Claude Code's native install is a bundle too (".../claude-code/<ver>/<hash>/claude.app/Contents/
# MacOS/claude"), as is the codex binary the ChatGPT app ships ("CodexCLI.app"); both are CLIs.
NOT_GUI_BUNDLES = {"Python", "Python3", "Python Launcher", "claude", "CodexCLI"}


def is_gui_path(comm: str) -> bool:
    """True when comm lives inside a real application bundle (something with a Dock icon)."""
    m = APP_RE.search(comm)
    if not m:
        return False
    if m.group(1) in NOT_GUI_BUNDLES:
        return False
    prefix = comm[:m.start()]
    if ".framework/" in prefix or "/Frameworks/" in prefix:
        return False
    # an app bundle nested inside another app's bundle (Xcode's Python.app, Chrome's helpers)
    # is judged by the outermost one, which is what APP_RE found; but a framework shim
    # anywhere in the path is never a GUI process
    if re.search(r"\.framework/.*/Python\.app/", comm):
        return False
    return True


def app_of(comm: str):
    """The application a process belongs to (outermost bundle), or None for non-GUI executables."""
    return bundle_of(comm) if is_gui_path(comm) else None


BROWSER_BUNDLES = {
    "Google Chrome", "Google Chrome Canary", "Google Chrome Beta", "Google Chrome Dev",
    "Google Chrome for Testing", "Chromium", "Chrome for Testing", "Brave Browser",
    "Microsoft Edge", "Arc", "Vivaldi", "Opera", "Comet", "Dia",
}
BROWSER_BINARIES = {"chrome", "chromium", "chromium-browser", "google-chrome", "google chrome",
                    "headless_shell", "chrome-headless-shell"}


def is_browser_process(comm: str) -> bool:
    """A Chromium-family executable (main or helper). crashpad handlers are not browsers."""
    base = os.path.basename(comm)
    if "crashpad" in base.lower():
        return False
    b = bundle_of(comm)
    if b and (b in BROWSER_BUNDLES or b.startswith("Google Chrome")):
        return True
    return base.lower() in BROWSER_BINARIES


PS_MAIN_COLS = "pid=,ppid=,pgid=,uid=,pcpu=,rss=,etime=,time=,args="


def ps_command(cols: str) -> list:
    # -ww: never truncate to the terminal width (macOS ps does when it thinks it has one)
    return ["ps", "-ww", "-ax" if IS_MAC else "-e", "-o", cols]


# On macOS `ps` reports resident set size, which leaves out every page the kernel has
# compressed or swapped out. On a Mac under pressure that is most of a process's memory:
# the first real run saw a 1.9GB renderer reading 150MB and Chrome's main process (356MB)
# reading 100MB. Activity Monitor's "Memory" column is the physical footprint from
# proc_pid_rusage(); libproc gives the same number through ctypes for every process you
# own, about 2ms for 500 pids. Other users' processes keep their RSS.
_libproc = None


class _RusageInfoV2(ctypes.Structure):
    _fields_ = [("ri_uuid", ctypes.c_uint8 * 16)] + [(n, ctypes.c_uint64) for n in (
        "ri_user_time", "ri_system_time", "ri_pkg_idle_wkups", "ri_interrupt_wkups", "ri_pageins",
        "ri_wired_size", "ri_resident_size", "ri_phys_footprint", "ri_proc_start_abstime",
        "ri_proc_exit_abstime", "ri_child_user_time", "ri_child_system_time", "ri_child_pkg_idle_wkups",
        "ri_child_interrupt_wkups", "ri_child_pageins", "ri_child_elapsed_abstime",
        "ri_diskio_bytesread", "ri_diskio_byteswritten")]


def phys_footprint_kb(pid: int):
    """Physical footprint in KB (the number Activity Monitor shows), or None when unreadable."""
    global _libproc
    if not IS_MAC:
        return None
    if _libproc is None:
        try:
            lib = ctypes.CDLL("/usr/lib/libproc.dylib")
            lib.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(_RusageInfoV2)]
            lib.proc_pid_rusage.restype = ctypes.c_int
            _libproc = lib
        except (OSError, AttributeError):
            _libproc = False
    if not _libproc:
        return None
    info = _RusageInfoV2()
    if _libproc.proc_pid_rusage(pid, 2, ctypes.byref(info)) != 0:   # 2 = RUSAGE_INFO_V2
        return None
    return int(info.ri_phys_footprint // 1024)


def list_processes() -> list:
    """All processes, via ps (two calls because comm can contain spaces); memory from libproc."""
    comm_out = subprocess.run(ps_command("pid=,comm="), capture_output=True, text=True).stdout
    main_out = subprocess.run(ps_command(PS_MAIN_COLS), capture_output=True, text=True).stdout
    procs = parse_ps(comm_out, main_out)
    for p in procs:
        fp = phys_footprint_kb(p.pid)
        if fp:
            p.rss_kb = fp
    return procs


def parse_ps(comm_out: str, main_out: str) -> list:
    """Turn the two ps listings into Proc objects. Pure, so it can be tested on recorded macOS output.

    On macOS `comm` is the executable's full path (which may contain spaces, e.g.
    ".../Google Chrome Helper (Renderer)"), `time` is mm:ss.hh and `etime` is [[dd-]hh:]mm:ss.
    """
    comms = {}
    for line in comm_out.splitlines():
        line = line.strip()
        if not line:
            continue
        pid, _, comm = line.partition(" ")
        try:
            comms[int(pid)] = comm.strip()
        except ValueError:
            continue
    procs = []
    for line in main_out.splitlines():
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        try:
            pid, ppid, pgid, puid = (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
            cpu = float(parts[4])
            rss = int(parts[5])
            etime = parse_etime(parts[6])
            cputime = parse_etime(parts[7])
        except ValueError:
            continue
        args = parts[8]
        comm = comms.get(pid) or args.split(" ")[0]
        p = Proc(pid, ppid, pgid, puid, cpu, rss, etime, cputime, comm, args)
        procs.append(p)
    return procs


def classify(procs: list, cfg: dict, my_uid: int) -> list:
    """Attach app, class and aggregation key to every process."""
    by_pid = {p.pid: p for p in procs}
    ab = cfg["automation_browser"]["markers"]
    ag = cfg["agent_sessions"]["markers"]
    rn = cfg["renderers"]["markers"]
    dv = cfg["dev_server"]["markers"]
    mw = cfg["model_worker"]["markers"]
    watch = [w.lower() for w in cfg.get("watch", [])]

    # First pass: browsers. Decide per browser *main* process, then inherit.
    browser_main_class = {}
    for p in procs:
        p.is_gui = is_gui_path(p.comm)
        p.app = app_of(p.comm) or (None if bundle_of(p.comm) else bundle_of(p.args))
        m = re.search(r"--type=([a-z\-]+)", p.args)
        p.chrome_type = m.group(1) if m else None
        if is_browser_process(p.comm) and p.chrome_type is None:
            automated = any(mark in p.args or mark in p.comm for mark in ab)
            debug = "--remote-debugging" in p.args
            browser_main_class[p.pid] = ("automation_browser" if automated
                                         else "debug_browser" if debug else "browser")
    # a browser process without --type whose parent is itself a browser main (Chrome's
    # relaunch-on-update child, odd helpers) belongs to that main, it is not a new browser
    mains = set(browser_main_class)
    for pid in mains:
        if by_pid[pid].ppid in mains:
            del browser_main_class[pid]

    for p in procs:
        if p.uid != my_uid:
            p.cls = "foreign"
            p.key = p.name
            continue
        low_args = p.args.lower()
        root = p
        hops = 0
        while root.ppid in by_pid and root.pid not in browser_main_class and hops < 6:
            root = by_pid[root.ppid]
            hops += 1
        # --type=renderer is the stable signal: Chrome 157 renamed its helpers to
        # "Google Chrome Helper (Aperitif Renderer)", which the name marker alone misses
        is_renderer = p.chrome_type == "renderer" or any(mark in p.comm for mark in rn)
        if root.pid in browser_main_class:
            p.cls = browser_main_class[root.pid]
            label = root.app or root.name
            if p.cls == "automation_browser":
                p.key = f"{label} [automation pid {root.pid}]"
            elif p.cls == "debug_browser":
                p.key = f"{label} [remote-debugging]"
            else:
                p.key = label
            if is_renderer:
                p.cls = p.cls + "/renderer"
            continue
        if is_renderer and not p.is_gui:
            # a renderer helper whose app we cannot place (should not happen on macOS)
            p.cls = "browser/renderer"
            p.key = p.app or p.name
            continue
        # Electron renderers ("Claude Helper (Renderer)", "Dropbox Helper (Renderer)") fall
        # through to their app below and keep a /renderer suffix for the fat-renderer rule.
        if not p.is_gui and any(word_in(mark, low_args) for mark in mw):
            p.cls = "model_worker"
            p.key = p.name
            continue
        if not p.is_gui and any(word_in(mark, low_args) for mark in dv):
            p.cls = "dev_server"
            p.key = p.name
            continue
        heads = [os.path.basename(tok).lower() for tok in [p.comm] + p.args.split()[:2]]
        agent = next((mark for mark in ag if agent_head_match(mark, heads)), None)
        if not p.is_gui and agent:
            p.cls = "agent_session"
            p.key = "agent:" + agent.lower()
            continue
        if p.comm.startswith(("/System/", "/usr/libexec/", "/usr/sbin/", "/sbin/")):
            p.cls = "system"
            p.key = p.name
            continue
        ai_apps = cfg.get("ai_apps", [])
        if p.is_gui and p.app in ai_apps:
            p.cls = "ai_app" + ("/renderer" if is_renderer else "")
            p.key = p.app
            continue
        # helper spawned by an AI desktop app (MCP servers, Claude Code run from Claude.app)
        anc, hops = p, 0
        owner = None
        while anc.ppid in by_pid and hops < 6:
            anc = by_pid[anc.ppid]
            hops += 1
            if anc.is_gui and anc.app in ai_apps:
                owner = anc.app
                break
        # a bundle an AI app spawned from inside the home folder (~/.codex/computer-use/
        # "Codex Computer Use.app") is a service of that app, not an app of its own
        if owner and (not p.is_gui or not p.comm.startswith(("/Applications/", "/System/"))):
            p.cls = "mcp_server"
            p.key = f"{owner} helpers (MCP servers)"
            continue
        if not p.is_gui and p.ppid == 1 and "mcp" in low_args and \
                p.name in ("node", "npx", "uvx", "uv", "python3", "python", "Python", "bun", "deno"):
            p.cls = "mcp_orphan"
            p.key = f"orphaned MCP server: {p.args.split()[-1][-40:]}"
            continue
        if p.is_gui:
            p.cls = "gui_app" + ("/renderer" if is_renderer else "")
            p.key = p.app or p.name
            if any(w in (p.key or "").lower() for w in watch):
                p.cls = "watched"
            continue
        p.cls = "other"
        p.key = p.name
    return procs


def aggregate(procs: list, cfg: dict) -> list:
    """Sum memory and CPU per key (one line for all of Chrome's helpers)."""
    groups = {}
    for p in procs:
        if p.cls == "foreign":
            continue
        g = groups.setdefault(p.key, {"key": p.key, "class": p.cls.split("/")[0],
                                      "rss_mb": 0.0, "cpu": 0.0, "n": 0, "pids": []})
        g["rss_mb"] += p.rss_mb
        g["cpu"] += p.cpu
        g["n"] += 1
        g["pids"].append(p.pid)
    out = sorted(groups.values(), key=lambda g: -g["rss_mb"])
    for g in out:
        g["rss_mb"] = round(g["rss_mb"])
        g["cpu"] = round(g["cpu"], 1)
    return out


# --------------------------------------------------------------------------
# System sampling
# --------------------------------------------------------------------------

def sh(cmd: list, timeout: int = 10) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def sysctl(name: str) -> str:
    return sh(["sysctl", "-n", name])


def read_mac_raw() -> dict:
    """The raw text of every macOS reading. Kept separate so parse_mac_sample() is testable."""
    return {
        "pressure": sysctl("kern.memorystatus_vm_pressure_level"),
        "level": sysctl("kern.memorystatus_level"),
        "swap": sysctl("vm.swapusage"),
        "memsize": sysctl("hw.memsize"),
        "loadavg": sysctl("vm.loadavg"),
        "vm_stat": sh(["vm_stat"]),
        "therm": sh(["pmset", "-g", "therm"]),
    }


def parse_mac_sample(raw: dict, s: dict) -> dict:
    """Fill a sample from raw macOS command output.

    kern.memorystatus_vm_pressure_level: 1 normal, 2 warn, 4 critical.
    kern.memorystatus_level: percent of memory the kernel considers available.
    vm.swapusage: 'total = 3072.00M  used = 1517.25M  free = 1554.75M  (encrypted)'
    vm_stat: 'Mach Virtual Memory Statistics: (page size of 16384 bytes)' then
             'Pages occupied by compressor:   123456.'
    pmset -g therm: 'CPU_Speed_Limit \t= 100' (plus notes; absent on some models -> 100)
    """
    lvl = (raw.get("pressure") or "").strip()
    s["pressure_level"] = int(lvl) if lvl.isdigit() else 1
    s["pressure_read"] = lvl.isdigit()
    fl = (raw.get("level") or "").strip()
    s["free_pct"] = int(fl) if fl.isdigit() else None
    m = re.search(r"total\s*=\s*([\d.]+)([KMG])\s+used\s*=\s*([\d.]+)([KMG])", raw.get("swap") or "")
    if m:
        unit = {"K": 1 / 1024, "M": 1.0, "G": 1024.0}
        s["swap_total_mb"] = round(float(m.group(1)) * unit[m.group(2)], 1)
        s["swap_used_mb"] = round(float(m.group(3)) * unit[m.group(4)], 1)
    ms = (raw.get("memsize") or "").strip()
    s["mem_total_mb"] = int(ms) // (1024 * 1024) if ms.isdigit() else None
    m = re.search(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)", raw.get("loadavg") or "")
    s["load1"] = float(m.group(1)) if m else None
    vs = raw.get("vm_stat") or ""
    m = re.search(r"Pages occupied by compressor:\s+(\d+)", vs)
    ps = re.search(r"page size of (\d+) bytes", vs)
    if m and ps:
        s["compressed_mb"] = int(m.group(1)) * int(ps.group(1)) // (1024 * 1024)
    m = re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", raw.get("therm") or "")
    s["cpu_speed_limit"] = int(m.group(1)) if m else 100
    return s


def sample_system() -> dict:
    s = {"ts": time.time(), "host": HOSTNAME, "pressure_level": 1, "free_pct": None,
         "swap_used_mb": None, "swap_total_mb": None, "compressed_mb": None,
         "mem_total_mb": None, "load1": None, "cpu_speed_limit": 100, "disk_free_gb": None,
         "source": "darwin" if IS_MAC else "linux"}
    if IS_MAC:
        parse_mac_sample(read_mac_raw(), s)
    else:
        mi = {}
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                k, _, v = line.partition(":")
                mi[k] = int(v.strip().split()[0])
        except Exception:
            pass
        if mi:
            s["mem_total_mb"] = mi.get("MemTotal", 0) // 1024
            avail = mi.get("MemAvailable", 0)
            s["free_pct"] = int(100 * avail / max(1, mi.get("MemTotal", 1)))
            s["swap_total_mb"] = mi.get("SwapTotal", 0) // 1024
            s["swap_used_mb"] = (mi.get("SwapTotal", 0) - mi.get("SwapFree", 0)) // 1024
            s["pressure_level"] = 4 if s["free_pct"] < 5 else 2 if s["free_pct"] < 15 else 1
        try:
            s["load1"] = float(Path("/proc/loadavg").read_text().split()[0])
        except Exception:
            pass
    try:
        st = os.statvfs(str(HOME))
        s["disk_free_gb"] = round(st.f_bavail * st.f_frsize / 1e9, 1)
    except Exception:
        pass
    return s


def pressure_word(level: int) -> str:
    return {1: "normal", 2: "warn", 4: "critical"}.get(level, str(level))


def quiet_mode(procs: list, cfg: dict) -> str:
    """Name of the reason we should stay quiet (presenting, in a meeting), or ''."""
    names = {p.name for p in procs} | {p.app for p in procs if p.app}
    for q in cfg.get("quiet_when_running", []):
        if q in names:
            return q
    return ""


# --------------------------------------------------------------------------
# Policy engine (pure: snapshot in, decisions out)
# --------------------------------------------------------------------------

class Decision:
    def __init__(self, action: str, proc, reason: str, cls: str, severity: str = "info"):
        self.action = action        # notify | renice | kill | log
        self.proc = proc
        self.reason = reason
        self.cls = cls
        self.severity = severity

    def __repr__(self):
        who = f"pid {self.proc.pid} {self.proc.name}" if self.proc else "-"
        return f"<{self.action} {who}: {self.reason}>"


class Engine:
    """Tracks per-pid state across samples and emits decisions."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.track = {}         # pid -> dict(first_seen, etime0, cputime0, hot_since, idle_since, mem_since)
        self.episode = None     # dict when under pressure
        self.episodes_today = 0
        self.day = None
        self.last_notify = {}   # key -> ts
        self.strikes = defaultdict(float)
        self.prev_sample_ts = None

    def _t(self, p: Proc, now: float) -> dict:
        t = self.track.get(p.pid)
        if t is None or t["etime0"] > p.etime_s:   # pid recycled
            t = {"first_seen": now, "etime0": p.etime_s, "cputime0": p.cputime_s,
                 "hot_since": None, "idle_since": None, "mem_since": None,
                 "last_cputime": p.cputime_s, "last_ts": now, "inst_cpu": p.cpu}
            self.track[p.pid] = t
        return t

    def _update_cpu(self, p: Proc, t: dict, now: float):
        dt = now - t["last_ts"]
        if dt >= 5:
            inst = 100.0 * (p.cputime_s - t["last_cputime"]) / dt
            t["inst_cpu"] = max(0.0, min(inst, 1600.0))
            t["last_cputime"] = p.cputime_s
            t["last_ts"] = now
        return t["inst_cpu"] if t["last_ts"] != t["first_seen"] else p.cpu

    def step(self, sample: dict, procs: list, now: float = None) -> list:
        now = now or sample["ts"]
        cfg = self.cfg
        decisions = []
        day = datetime.fromtimestamp(now).date()
        if self.day != day:
            self.day = day
            self.episodes_today = 0

        level = sample["pressure_level"]
        free = sample.get("free_pct")
        under_pressure = level >= cfg["pressure_warn_level"] or (
            free is not None and free <= cfg["free_pct_floor"])
        critical = level >= 4 or (free is not None and free <= max(2, cfg["free_pct_floor"] // 2))

        mine = [p for p in procs if p.cls != "foreign"]
        groups = aggregate(mine, cfg)
        seen = set()

        # ---- episode bookkeeping
        if under_pressure and self.episode is None:
            self.episode = {"start": now, "peak_level": level, "top": groups[:cfg["top_n"]],
                            "min_free": free}
            self.episodes_today += 1
            decisions.append(Decision("log", None,
                                      f"pressure episode started ({pressure_word(level)}, free {free}%)",
                                      "episode", "warn"))
        elif under_pressure and self.episode is not None:
            self.episode["peak_level"] = max(self.episode["peak_level"], level)
            if free is not None and (self.episode["min_free"] is None or free < self.episode["min_free"]):
                self.episode["min_free"] = free
        elif not under_pressure and self.episode is not None:
            dur = int(now - self.episode["start"])
            top = ", ".join(f"{g['key']} {g['rss_mb']}MB" for g in self.episode["top"][:3])
            decisions.append(Decision("log", None,
                                      f"pressure episode ended after {dur}s; peak {pressure_word(self.episode['peak_level'])}; top: {top}",
                                      "episode", "info"))
            self.episode = None

        # ---- pressure notification naming the offenders
        if under_pressure and self._cooldown_ok("pressure", now):
            top = "; ".join(f"{g['key']} {g['rss_mb'] / 1024:.1f}GB" for g in groups[:cfg["top_n"]])
            decisions.append(Decision("notify", None,
                                      f"Memory {pressure_word(level)} (free {free}%). Biggest: {top}",
                                      "pressure", "crit" if critical else "warn"))

        # ---- per process rules
        ab, ag, rn, cpu = cfg["automation_browser"], cfg["agent_sessions"], cfg["renderers"], cfg["cpu"]
        for p in mine:
            seen.add(p.pid)
            t = self._t(p, now)
            inst = self._update_cpu(p, t, now)
            base = p.cls.split("/")[0]

            # idle / hot timers
            idle_thr = ab["idle_cpu_pct"] if base in ("automation_browser", "mcp_orphan") else ag["idle_cpu_pct"]
            if inst < idle_thr:
                t["idle_since"] = t["idle_since"] or now
            else:
                t["idle_since"] = None
            if inst >= cpu["runaway_pct"]:
                t["hot_since"] = t["hot_since"] or now
            else:
                t["hot_since"] = None

            # 1. orphaned / idle automation browser (main process only) or orphaned MCP server
            if base in ("automation_browser", "mcp_orphan") and p.chrome_type is None:
                orphan = p.ppid == 1
                idle_for = (now - t["idle_since"]) if t["idle_since"] else 0
                limit = ab["pressure_idle_seconds"] if under_pressure else ab["orphan_idle_seconds"]
                if orphan and idle_for >= limit and self._cooldown_ok(f"kill:{p.pid}", now, 1800):
                    what = "automation browser" if base == "automation_browser" else "MCP server"
                    decisions.append(Decision("kill", p,
                                              f"{what} abandoned (parent gone, idle {int(idle_for)}s)",
                                              base, "warn"))
                    continue
                grp = next((g for g in groups if g["key"] == p.key), None)
                if under_pressure and grp and grp["rss_mb"] >= ab["memory_mb"] \
                        and self._cooldown_ok(f"kill:{p.pid}", now, 1800):
                    decisions.append(Decision("kill", p,
                                              f"automation browser using {grp['rss_mb']}MB under pressure",
                                              "automation_browser", "warn"))
                    continue

            # 2. stale agent sessions (claude / codex CLIs forgotten for a day)
            if base == "agent_session":
                age_h = p.etime_s / 3600.0
                idle_for = (now - t["idle_since"]) if t["idle_since"] else 0
                if age_h >= ag["stale_after_hours"] and idle_for >= ag["idle_seconds"]:
                    if self._cooldown_ok(f"stale:{p.pid}", now, 6 * 3600):
                        act = "kill" if ag["kill_when_stale"] else "notify"
                        decisions.append(Decision(act, p,
                                                  f"agent session {p.name} is {age_h:.0f}h old and idle {int(idle_for / 60)}min",
                                                  "agent_session", "info"))

            # 3. runaway CPU on anything that is not a GUI app
            if t["hot_since"] and now - t["hot_since"] >= cpu["sustain_seconds"] and not p.is_gui \
                    and base not in ("system",):
                if self._cooldown_ok(f"hot:{p.pid}", now, 1800):
                    decisions.append(Decision("renice", p,
                                              f"{p.name} at {inst:.0f}% CPU for {int((now - t['hot_since']) / 60)}min",
                                              base, "warn"))

            # 4. fat renderers under pressure (one tab eating the machine)
            if p.cls.endswith("/renderer") and under_pressure and p.rss_mb >= rn["memory_mb"]:
                t["mem_since"] = t["mem_since"] or now
                if now - t["mem_since"] >= rn["sustain_seconds"] and self._cooldown_ok(f"rend:{p.pid}", now, 1800):
                    act = "kill" if rn["kill_under_pressure"] else "notify"
                    decisions.append(Decision(act, p,
                                              f"one browser tab/renderer holds {p.rss_mb:.0f}MB under pressure (pid {p.pid})",
                                              "renderer", "warn"))
            elif p.cls.endswith("/renderer"):
                t["mem_since"] = None

            # 5. critical pressure: reclaim the biggest known-safe job
            if critical and base in cfg["safe_kill_classes"] and base != "automation_browser":
                limit = cfg.get(base, {}).get("memory_mb", 10 ** 9)
                if p.rss_mb >= limit:
                    self.strikes[p.pid] += 1
                    if self.strikes[p.pid] >= 2 and self._cooldown_ok(f"kill:{p.pid}", now, 1800):
                        self.strikes[p.pid] = 0
                        decisions.append(Decision("kill", p,
                                                  f"critical pressure and {p.name} holds {p.rss_mb:.0f}MB",
                                                  base, "crit"))
            else:
                self.strikes[p.pid] = self.strikes[p.pid] / 2

        # ---- forget pids that vanished
        for pid in list(self.track):
            if pid not in seen:
                del self.track[pid]
                self.strikes.pop(pid, None)

        # ---- disk as swap ceiling
        dfree = sample.get("disk_free_gb")
        if dfree is not None and dfree < cfg["disk_floor_gb"] and \
                self._cooldown_ok("disk", now, cfg["scratch"]["cooldown_hours"] * 3600):
            decisions.append(Decision("reclaim", None,
                                      f"Only {dfree}GB free on disk. Swap cannot grow past that; memory freezes get likelier.",
                                      "disk", "warn"))
        if sample.get("cpu_speed_limit", 100) < 100 and self._cooldown_ok("therm", now, 3600):
            decisions.append(Decision("notify", None,
                                      f"CPU is thermally throttled to {sample['cpu_speed_limit']}% speed.",
                                      "thermal", "warn"))
        return decisions

    def _cooldown_ok(self, key: str, now: float, secs: int = None) -> bool:
        secs = self.cfg["notify_cooldown_seconds"] if secs is None else secs
        last = self.last_notify.get(key, 0)
        if now - last >= secs:
            self.last_notify[key] = now
            return True
        return False


# --------------------------------------------------------------------------
# Effects: notify, renice, kill, log
# --------------------------------------------------------------------------

def notify(title: str, body: str, cfg: dict):
    if not cfg.get("notify", True):
        return
    body = body.replace("\\", "/").replace('"', "'")[:230]
    title = title.replace("\\", "/").replace('"', "'")
    if IS_MAC:
        sh(["osascript", "-e", f'display notification "{body}" with title "{title}"'])
    elif shutil.which("notify-send"):
        sh(["notify-send", title, body])


def log_event(kind: str, **fields):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "host": HOSTNAME, "kind": kind}
    rec.update(fields)
    with EVENTS_PATH.open("a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return rec


def log_sample(sample: dict, groups: list):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    new = not SAMPLES_PATH.exists()
    with SAMPLES_PATH.open("a") as f:
        if new:
            f.write("ts\tlevel\tfree_pct\tswap_used_mb\tcompressed_mb\tload1\tdisk_free_gb\ttop\n")
        top = ";".join(f"{g['key']}={g['rss_mb']}" for g in groups[:5])
        f.write("\t".join(str(x) for x in [
            datetime.fromtimestamp(sample["ts"]).isoformat(timespec="seconds"),
            sample["pressure_level"], sample.get("free_pct"), sample.get("swap_used_mb"),
            sample.get("compressed_mb"), sample.get("load1"), sample.get("disk_free_gb"), top]) + "\n")


def still_same_process(p: Proc) -> bool:
    """Re-check owner and age before signalling so a recycled pid is never hit."""
    out = sh(["ps", "-o", "uid=,etime=", "-p", str(p.pid)])
    if not out:
        return False
    try:
        uid, et = out.split()
        return int(uid) == os.getuid() and parse_etime(et) >= p.etime_s
    except ValueError:
        return False


def terminate(p: Proc, grace: int = 15) -> str:
    if not still_same_process(p):
        return "gone"
    try:
        os.kill(p.pid, signal.SIGTERM)
    except ProcessLookupError:
        return "gone"
    except PermissionError:
        return "denied"
    deadline = time.time() + grace
    while time.time() < deadline:
        time.sleep(0.5)
        try:
            os.kill(p.pid, 0)
        except ProcessLookupError:
            return "terminated"
    if still_same_process(p):
        try:
            os.kill(p.pid, signal.SIGKILL)
            return "killed"
        except ProcessLookupError:
            return "terminated"
    return "terminated"


def running_apps(procs: list) -> set:
    return {p.app for p in procs if p.app and p.cls != "foreign"}


class Background:
    """One slot for slow work (the disk census is `du` over tens of GB: ~110 s on the first
    real Mac) so the 30 s sampling loop never waits on it. A second job while one runs is
    refused rather than queued; every caller has its own cooldown and will come back."""

    def __init__(self):
        self.thread = None
        self.name = None

    def busy(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def submit(self, name: str, fn) -> bool:
        if self.busy():
            return False

        def run():
            try:
                fn()
            except Exception as e:  # pragma: no cover
                log_event("error", error=repr(e), job=name)
        self.name = name
        self.thread = threading.Thread(target=run, name=f"guardian-{name}", daemon=True)
        self.thread.start()
        return True


def apply_decisions(decisions: list, cfg: dict, quiet: str = "", dry_run: bool = False,
                    simulated: bool = False, running: set = frozenset(), background=None) -> list:
    """Carry out decisions. With `background` (a Background), the disk reclaim, which needs a
    census, runs on that worker and logs its own event when done; everything else is immediate."""
    mode = cfg["mode"]
    applied = []
    for d in decisions:
        rec = {"action": d.action, "class": d.cls, "reason": d.reason, "severity": d.severity,
               "proc": d.proc.to_dict() if d.proc else None, "mode": mode, "result": None}
        if simulated:
            rec["simulated"] = True
        if d.action == "log":
            rec["result"] = "logged"
        elif d.action == "notify":
            if mode == "observe" or quiet or dry_run:
                rec["result"] = f"suppressed ({'quiet: ' + quiet if quiet else mode if mode == 'observe' else 'dry-run'})"
            else:
                notify("Guardian", d.reason, cfg)
                rec["result"] = "notified"
        elif d.action == "reclaim":
            def reclaim_job(rec=rec, d=d):
                import scratch
                rows = scratch.census()
                could = scratch.reclaimable_mb(rows, ("safe", "safe-old"), running)
                if mode == "act" and cfg["scratch"]["auto_reclaim_in_act_mode"] and not dry_run and not simulated:
                    freed = 0
                    for tier in ("safe", "safe-old"):
                        freed += scratch.reclaim(tier, dry_run=False, running=running, rows=rows)["freed_mb"]
                    rec["result"] = f"reclaimed {freed / 1024:.1f}GB of caches/old logs"
                    if not quiet:
                        notify("Guardian", f"{d.reason} Freed {freed / 1024:.1f}GB of rebuildable caches.", cfg)
                else:
                    rec["result"] = f"would reclaim {could / 1024:.1f}GB (safe tiers)"
                    if mode != "observe" and not quiet and not dry_run:
                        notify("Guardian", f"{d.reason} `guardian scratch --reclaim all --yes` would free {could / 1024:.1f}GB.", cfg)
            if background is not None:
                if background.submit("reclaim", lambda: (reclaim_job(), log_event("decision", **rec))):
                    rec["result"] = "census running in the background"
                else:
                    rec["result"] = f"skipped: {background.name} job still running"
                    log_event("decision", **rec)
                applied.append(rec)
                continue
            reclaim_job()
        elif d.action == "renice":
            if mode != "act" or dry_run or quiet:
                rec["result"] = ("would renice (dry-run)" if dry_run else
                                 f"held (quiet: {quiet})" if mode == "act" else
                                 "would renice" if mode == "nudge" else "observed")
                if mode == "nudge" and not quiet and not dry_run:
                    notify("Guardian", d.reason + " (act mode would renice it)", cfg)
            else:
                try:
                    os.setpriority(os.PRIO_PROCESS, d.proc.pid, cfg["cpu"]["renice_to"])
                    rec["result"] = f"reniced to {cfg['cpu']['renice_to']}"
                except Exception as e:
                    rec["result"] = f"renice failed: {e}"
                if not quiet:
                    notify("Guardian", f"Slowed down {d.proc.name}: {d.reason}", cfg)
        elif d.action == "kill":
            protected = d.proc.name in cfg["protect"] or (d.proc.app in cfg["protect"]
                                                           and d.cls != "automation_browser")
            # whatever a rule decided: an app you can see is never closed, only an automation browser
            gui_shield = d.proc.is_gui and d.cls != "automation_browser"
            if protected or gui_shield:
                rec["result"] = "protected" if protected else "protected (GUI app)"
            elif mode != "act" or dry_run or (quiet and d.cls != "automation_browser"):
                rec["result"] = ("would kill (dry-run)" if dry_run else
                                 f"held (quiet: {quiet})" if mode == "act" else
                                 "would kill" if mode == "nudge" else "observed")
                if mode == "nudge" and not quiet and not dry_run:
                    notify("Guardian", d.reason + " (act mode would close it)", cfg)
            else:
                rec["result"] = terminate(d.proc)
                if not quiet:
                    notify("Guardian", f"Closed {d.proc.name}: {d.reason}", cfg)
        log_event("decision", **rec)
        applied.append(rec)
    return applied


# --------------------------------------------------------------------------
# Refresh when idle: a bloated AI app is quit cleanly, its caches cleared and the app
# reopened, but only while its agent is idle and only with the owner's say-so
# --------------------------------------------------------------------------
# First real Mac: the ChatGPT app (which embeds Codex) held 10 GB in 99 processes on an
# 8 GB machine; about 75 of them were helpers over an hour old that had done almost nothing,
# and 3.8 GB of its caches could never be cleared because the app never quits.

def under_pressure(sample: dict, cfg: dict) -> bool:
    free = sample.get("free_pct")
    return sample.get("pressure_level", 1) >= cfg["pressure_warn_level"] or (
        free is not None and free <= cfg["free_pct_floor"])


def newest_mtime(paths: list) -> float:
    """Most recent modification time under the given files/folders; 0.0 when there is none.
    Codex appends to ~/.codex/sessions/**/*.jsonl while a task runs (477 files scan in 20 ms)."""
    newest = 0.0
    for raw in paths:
        p = Path(raw)
        try:
            if p.is_file():
                newest = max(newest, p.stat().st_mtime)
                continue
            for d, _dirs, files in os.walk(p, followlinks=False):
                for f in files:
                    try:
                        m = os.lstat(os.path.join(d, f)).st_mtime
                    except OSError:
                        continue
                    if m > newest:
                        newest = m
        except OSError:
            continue
    return newest


def parse_front_app(text: str) -> str:
    """Name of the frontmost app from `lsappinfo info -only name <asn>`.
    macOS 27 prints '"Claude" ASN:0x0-0x88088: (in front)'; older systems '"LSDisplayName"="Claude"'."""
    m = re.search(r'"LSDisplayName"\s*=\s*"([^"]+)"', text) or re.search(r'^\s*"([^"]+)"\s+ASN:', text, re.M)
    return m.group(1) if m else ""


def parse_hid_idle(text: str):
    """Seconds since the last key or pointer event, from `ioreg -c IOHIDSystem` (nanoseconds)."""
    vals = [int(v) for v in re.findall(r'"HIDIdleTime"\s*=\s*(\d+)', text)]
    return min(vals) / 1e9 if vals else None


def parse_dialog(out: str) -> str:
    """Button name from osascript's 'button returned:Refresh now, gave up:false'; '' if nobody answered."""
    if "gave up:true" in out:
        return ""
    m = re.search(r"button returned:([^,\n]*)", out)
    return m.group(1).strip() if m else ""


def ask_dialog(text: str, buttons: list, default: str, timeout: int = 120) -> str:
    esc = lambda s: s.replace("\\", "/").replace('"', "'")
    script = (f'display dialog "{esc(text)}" with title "Guardian" buttons {{'
              + ", ".join(f'"{esc(b)}"' for b in buttons)
              + f'}} default button "{esc(default)}" giving up after {int(timeout)}')
    try:
        r = subprocess.run(["osascript", "-e", "tell me to activate", "-e", script],
                           capture_output=True, text=True, timeout=timeout + 15)
    except Exception as e:
        log_event("error", error=repr(e), job="dialog")
        return ""
    if r.returncode != 0:        # a dialog that cannot be shown must be visible in the diary
        log_event("error", error=(r.stderr or "osascript failed").strip()[:200], job="dialog")
    return parse_dialog(r.stdout)


def bundle_path(comm: str):
    m = APP_RE.search(comm)
    return comm[:m.end() - 1] if m else None


def app_family(procs: list, app: str):
    """Every process that belongs to an app (its helpers and the services it spawned) and its
    main process: the one launchd started, living in <App>.app/Contents/MacOS."""
    fam = [p for p in procs if p.key in (app, f"{app} helpers (MCP servers)")]
    pids = {p.pid for p in fam}
    mains = [p for p in fam if p.app == app and p.ppid not in pids and p.chrome_type is None
             and os.path.dirname(p.comm).endswith(f"/{app}.app/Contents/MacOS")]
    mains.sort(key=lambda p: -p.rss_kb)
    return fam, (mains[0] if mains else None)


def refresh_due(mode: str, grp, sample: dict, cfg: dict, st: dict, now: float) -> str:
    """'' when a refresh is worth considering, otherwise the reason it is not."""
    rcfg = cfg["refresh"]
    if mode not in ("ask", "auto"):
        return "set to never"
    if grp is None:
        return "not running"
    if grp["rss_mb"] < rcfg["min_gb"] * 1024:
        return f"only {grp['rss_mb'] / 1024:.1f}GB (acts at {rcfg['min_gb']}GB)"
    if rcfg["only_under_pressure"] and not under_pressure(sample, cfg):
        return "no memory pressure"
    if now - st.get("last", 0) < rcfg["cooldown_hours"] * 3600:
        return f"refreshed {(now - st['last']) / 3600:.1f}h ago"
    if now < st.get("snooze_until", 0):
        return f"you said not now ({int((st['snooze_until'] - now) / 60)}min left)"
    return ""


def refresh_decide(mode: str, rcfg: dict, activity_age_s, is_front: bool, user_idle_s):
    """('wait' | 'ask' | 'refresh', why). Never while the app's agent is working or the app is in
    front. 'auto' also needs proof the agent is idle and the owner away from the keyboard;
    'ask' waits until the owner is there to answer."""
    if activity_age_s is not None and activity_age_s < rcfg["agent_idle_minutes"] * 60:
        return "wait", f"its agent was working {int(activity_age_s // 60)}min ago"
    if is_front:
        return "wait", "you are using it"
    if mode == "auto":
        if activity_age_s is None:
            return "wait", "cannot tell whether it is busy (use ask for this app)"
        if user_idle_s is None or user_idle_s < rcfg["user_idle_minutes"] * 60:
            return "wait", "you are at the keyboard"
        return "refresh", "its agent is idle and you are away"
    if user_idle_s is not None and user_idle_s > 600:
        return "wait", "you are away; it will ask when you are back"
    return "ask", "its agent is idle"


class MacAppOps:
    """Everything refresh does to the machine, in one place so tests can substitute it."""

    def processes(self, cfg):
        return classify(list_processes(), cfg, os.getuid())

    def sample(self):
        return sample_system()

    def activity_age(self, app: str, cfg: dict):
        paths = [HOME / p for p in (cfg["refresh"].get("activity_paths") or {}).get(app, [])]
        paths = [p for p in paths if p.exists()]
        if not paths:
            return None
        m = newest_mtime(paths)
        return (time.time() - m) if m else None

    def front_app(self) -> str:
        asn = sh(["lsappinfo", "front"])
        return parse_front_app(sh(["lsappinfo", "info", "-only", "name", asn])) if asn else ""

    def user_idle(self):
        return parse_hid_idle(sh(["ioreg", "-c", "IOHIDSystem", "-d", "4"]))

    def quit(self, bundle: str, main: Proc, chromium_like: bool) -> str:
        """Ask the app to quit the way Cmd+Q does. If macOS will not let us send that (no
        Automation permission), Chromium-based apps also shut down cleanly on SIGTERM."""
        try:
            r = subprocess.run(["osascript", "-e", f'tell application "{bundle}" to quit'],
                               capture_output=True, text=True, timeout=20)
            if r.returncode == 0:
                return "applescript"
        except Exception:
            pass
        if chromium_like and still_same_process(main):
            try:
                os.kill(main.pid, signal.SIGTERM)
                return "sigterm"
            except OSError:
                pass
        return ""

    def alive(self, p: Proc) -> bool:
        return still_same_process(p)

    def term(self, p: Proc):
        if still_same_process(p):
            try:
                os.kill(p.pid, signal.SIGTERM)
            except OSError:
                pass

    def clear_caches(self, app: str, running: set) -> int:
        import scratch
        rows = scratch.census(only_app=app)
        return scratch.reclaim("safe", dry_run=False, running=running, rows=rows)["freed_mb"] if rows else 0

    def cache_mb(self, app: str) -> int:
        import scratch
        return sum(r["mb"] for r in scratch.census(only_app=app) if r["tier"] == "safe")

    def reopen(self, bundle: str):
        subprocess.run(["open", "-g", "-a", bundle], capture_output=True, text=True, timeout=30)

    def sleep(self, seconds: float):
        time.sleep(seconds)

    def ask(self, text: str, buttons: list, default: str) -> str:
        return ask_dialog(text, buttons, default)


def _refresh_measure(ops, cfg: dict, app: str):
    fam, main = app_family(ops.processes(cfg), app)
    s = ops.sample()
    return ({"app_mb": round(sum(p.rss_mb for p in fam)), "processes": len(fam),
             "swap_used_mb": s.get("swap_used_mb"), "free_pct": s.get("free_pct"),
             "pressure_level": s.get("pressure_level"), "disk_free_gb": s.get("disk_free_gb")}, fam, main)


def refresh_app(app: str, cfg: dict, ops=None, dry_run: bool = False, force: bool = False) -> dict:
    """Quit the app cleanly, clear its caches, reopen it in the background, and record what came
    back. It is never forced: if the agent is working, or the app does not quit, it is left alone."""
    ops = ops or MacAppOps()
    rcfg = cfg["refresh"]
    before, fam, main = _refresh_measure(ops, cfg, app)
    rec = {"app": app, "before": before, "dry_run": dry_run}

    def done(phase: str, result: str, **more):
        rec.update(phase=phase, result=result, **more)
        log_event("refresh", **rec)
        return rec

    if main is None:
        return done("aborted", "not running")
    age = ops.activity_age(app, cfg)
    if not force and age is not None and age < rcfg["agent_idle_minutes"] * 60:
        return done("aborted", f"its agent was working {int(age)}s ago; left alone")
    bundle = bundle_path(main.comm)
    if dry_run:
        return done("dry-run", "would quit, clear caches and reopen", would_clear_mb=ops.cache_mb(app))
    log_event("refresh", app=app, phase="started", before=before)
    how = ops.quit(bundle, main, any(p.chrome_type for p in fam))
    if not how:
        return done("aborted", "could not ask it to quit; left running")
    deadline = rcfg["quit_timeout_seconds"]
    while ops.alive(main) and deadline > 0:
        ops.sleep(1)
        deadline -= 1
    if ops.alive(main):
        return done("aborted", f"it did not quit within {rcfg['quit_timeout_seconds']}s; left running", quit_via=how)
    ops.sleep(8)
    leftovers = [p for p in fam if p.pid != main.pid and ops.alive(p)]
    for p in leftovers:          # helpers of an app that has quit; nothing the owner can see
        ops.term(p)
    freed_mb = 0
    if rcfg["clear_caches"]:
        freed_mb = ops.clear_caches(app, running_apps(ops.processes(cfg)) - {app})
    if rcfg["reopen"]:
        ops.reopen(bundle)
    ops.sleep(rcfg["settle_seconds"])
    after, _, _ = _refresh_measure(ops, cfg, app)
    back_mb = before["app_mb"] - after["app_mb"]
    out = done("done", f"memory {before['app_mb'] / 1024:.1f}GB -> {after['app_mb'] / 1024:.1f}GB, "
                       f"{freed_mb / 1024:.1f}GB of caches cleared",
               after=after, quit_via=how, leftovers=len(leftovers), caches_freed_mb=freed_mb, memory_back_mb=back_mb)
    notify("Guardian", f"Refreshed {app}: {before['app_mb'] / 1024:.1f}GB -> {after['app_mb'] / 1024:.1f}GB of memory, "
                       f"{freed_mb / 1024:.1f}GB of disk back.", cfg)
    return out


REFRESH_BUTTONS = ["Not now", "Always when idle", "Refresh now"]


def refresh_ask(app: str, cfg: dict, st: dict, gb: float, age_s, ops=None) -> dict:
    """Ask the owner, then act on the answer. 'Always when idle' is remembered in the config."""
    ops = ops or MacAppOps()
    rcfg = cfg["refresh"]
    idle = f" and its agent has been idle for {int(age_s // 60)} minutes" if age_s is not None else ""
    text = (f"{app} has grown to {gb:.1f} GB{idle}. Refresh it now? Guardian quits it cleanly, clears its "
            f"caches and reopens it. Chats and threads are kept; open windows may need reopening.")
    log_event("refresh", app=app, phase="asked", gb=round(gb, 1))
    answer = ops.ask(text, REFRESH_BUTTONS, "Refresh now")
    now = time.time()
    if answer == "Always when idle":
        apply_config_change({"refresh": {"apps": {app: "auto"}}}, f"refresh {app}: always when idle (chosen in the dialog)")
    if answer in ("Refresh now", "Always when idle"):
        rec = refresh_app(app, cfg, ops)
        if rec.get("phase") == "done":
            st["last"] = time.time()
        else:
            st["snooze_until"] = now + 30 * 60
        return rec
    minutes = rcfg["snooze_minutes"] if answer == "Not now" else 30
    st["snooze_until"] = now + minutes * 60
    return log_event("refresh", app=app, phase="declined" if answer == "Not now" else "unanswered",
                     snooze_minutes=minutes)


def refresh_state_from_events(hours: float = 48) -> dict:
    """Rebuild cooldowns and snoozes after a restart, so a restart never re-asks at once."""
    state = {}
    for e in read_events(hours):
        if e.get("kind") != "refresh" or not e.get("app"):
            continue
        st = state.setdefault(e["app"], {"last": 0.0, "snooze_until": 0.0, "next_check": 0.0})
        ts = datetime.fromisoformat(e["ts"]).timestamp()
        if e.get("phase") == "done" and not e.get("dry_run"):
            st["last"] = max(st["last"], ts)
        elif e.get("phase") in ("declined", "unanswered"):
            st["snooze_until"] = max(st["snooze_until"], ts + e.get("snooze_minutes", 30) * 60)
    return state


def refresh_tick(cfg: dict, snap: dict, state: dict, background, now: float, ops=None, dry_run: bool = False):
    """Called once per sample. Cheap checks first; the dialog and the refresh run on the worker.
    Returns the app a job was started for, or None."""
    rcfg = cfg.get("refresh") or {}
    if cfg["mode"] == "observe" or snap.get("quiet") or background is None or background.busy():
        return None
    for app, mode in (rcfg.get("apps") or {}).items():
        st = state.setdefault(app, {"last": 0.0, "snooze_until": 0.0, "next_check": 0.0})
        if now < st["next_check"]:
            continue
        grp = next((g for g in snap["groups"] if g["key"] == app), None)
        if refresh_due(mode, grp, snap["sample"], cfg, st, now):
            continue
        st["next_check"] = now + 120
        ops = ops or MacAppOps()
        if mode == "auto" and cfg["mode"] != "act":
            mode = "ask"                      # acting unasked is for act mode only
        age = ops.activity_age(app, cfg)
        verdict, _why = refresh_decide(mode, rcfg, age, ops.front_app() == app, ops.user_idle())
        if verdict == "wait":
            continue
        gb = grp["rss_mb"] / 1024

        def job(app=app, verdict=verdict, st=st, gb=gb, age=age, ops=ops):
            if dry_run:
                refresh_app(app, cfg, ops, dry_run=True)
                st["snooze_until"] = time.time() + 3600
            elif verdict == "ask":
                refresh_ask(app, cfg, st, gb, age, ops)
            else:
                rec = refresh_app(app, cfg, ops)
                if rec.get("phase") == "done":
                    st["last"] = time.time()
                else:                              # it would not quit, or the agent woke up
                    st["snooze_until"] = time.time() + 1800
        if background.submit(f"refresh:{app}", job):
            return app
    return None


def refresh_cmd(cfg: dict, args):
    ops = MacAppOps()
    rcfg = cfg["refresh"]
    if args.mode:
        if not args.app:
            print("name the app: guardian.py refresh ChatGPT --mode ask|auto|never")
            return
        apply_config_change({"refresh": {"apps": {args.app: args.mode}}}, f"refresh {args.app}: {args.mode}")
        print(f"{args.app}: {args.mode} (the running agent picks it up within a minute)")
        return
    if args.now:
        if not args.app:
            print("name the app: guardian.py refresh ChatGPT --now")
            return
        rec = refresh_app(args.app, cfg, ops, force=args.force)
        print(f"{args.app}: {rec['phase']}: {rec['result']}")
        return
    snap = snapshot(cfg)
    state = refresh_state_from_events()
    now = time.time()
    apps = [args.app] if args.app else list((rcfg.get("apps") or {}))
    print("Refresh when idle (quit cleanly, clear caches, reopen). Modes: ask, auto (when idle and you are away), never.")
    for app in apps:
        mode = (rcfg.get("apps") or {}).get(app, "never")
        grp = next((g for g in snap["groups"] if g["key"] == app), None)
        size = f"{grp['rss_mb'] / 1024:.1f}GB in {grp['n']} processes" if grp else "not running"
        why = refresh_due(mode, grp, snap["sample"], cfg, state.get(app, {}), now)
        if not why:
            age = ops.activity_age(app, cfg)
            verdict, reason = refresh_decide(mode, rcfg, age, ops.front_app() == app, ops.user_idle())
            why = {"wait": "waiting: ", "ask": "would ask you now: ", "refresh": "would refresh now: "}[verdict] + reason
        else:
            why = "nothing to do: " + why
        print(f"  {app:14} mode={mode:5}  {size:28}  {why}")
    print("Do it now: guardian.py refresh APP --now      Change consent: guardian.py refresh APP --mode ask|auto|never")


# --------------------------------------------------------------------------
# Disk: the ledger (what the free space was spent on), the fast-drop alert, and clearing an
# app's caches the moment it quits
# --------------------------------------------------------------------------

def ledger_path() -> Path:
    return LOG_DIR / "disk-ledger.jsonl"


def read_ledger(limit: int = 400) -> list:
    p = ledger_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines()[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def write_ledger(rows: list = None) -> dict:
    """Measure everything (a full census: a minute or two; call it from the worker) and append
    one ledger entry."""
    import scratch
    rows = scratch.census() if rows is None else rows
    entry = scratch.ledger_entry(rows, scratch.system_buckets(), sample_system().get("disk_free_gb"), time.time())
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with ledger_path().open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def ledger_baseline(entries: list, hours: float, now: float = None):
    """The oldest entry inside the window (never the latest one), or None."""
    if len(entries) < 2:
        return None
    cutoff = datetime.fromtimestamp(now or time.time()) - timedelta(hours=hours)
    inside = [e for e in entries[:-1] if datetime.fromisoformat(e["ts"]) >= cutoff]
    return inside[0] if inside else entries[-2]


def disk_drop(history: list, now: float, window_s: float, drop_gb: float) -> float:
    """How far free space fell inside the window (highest reading to the latest), or 0.0 if
    that is less than drop_gb. history is [(ts, free_gb), ...] oldest first."""
    recent = [f for t, f in history if now - t <= window_s and f is not None]
    if len(recent) < 2:
        return 0.0
    fell = max(recent) - recent[-1]
    return round(fell, 1) if fell >= drop_gb else 0.0


def disk_drop_job(cfg: dict, fell_gb: float, quiet: str = "") -> dict:
    """Free space is falling fast: measure, compare with the previous ledger entry, and say
    which place grew. (The first real Mac lost 8 GB in two hours to leftover temp folders.)"""
    import scratch
    entries = read_ledger()
    prev = entries[-1] if entries else None
    new = write_ledger()
    minutes = cfg["disk"]["alert_window_minutes"]
    text = f"Disk space fell {fell_gb:.1f}GB in the last {minutes} minutes ({new['free_gb']}GB free)."
    grew = []
    if prev:
        diff = scratch.ledger_diff(prev, new)
        grew = [(n, mb) for n, mb in diff["changes"] if mb >= 200][:3]
        if grew:
            text += f" Grew since {prev['ts'][11:16]}: " + ", ".join(f"{n} +{mb / 1024:.1f}GB" for n, mb in grew) + "."
        else:
            text += " Nothing guardian measures grew; see `guardian.py disk`."
    else:
        text += " First measurement taken; the next alert will name what grew."
    rec = log_event("disk", trigger="fast-drop", fell_gb=fell_gb, free_gb=new["free_gb"], grew=grew, text=text)
    if not quiet:
        notify("Guardian", text, cfg)
    return rec


def quit_tracker(state: dict, running: set, guard: set) -> list:
    """Apps that were seen running and have now been gone for two samples in a row (so a
    relaunch or an update that restarts the app is not mistaken for a quit)."""
    seen, gone = state.setdefault("seen", set()), state.setdefault("gone", {})
    out = []
    for app in sorted(guard):
        if app in running:
            seen.add(app)
            gone.pop(app, None)
        elif app in seen:
            gone[app] = gone.get(app, 0) + 1
            if gone[app] >= 2:
                out.append(app)
                seen.discard(app)
                gone.pop(app, None)
    return out


def clear_caches_on_quit(app: str, cfg: dict):
    """The app has quit: its caches are rebuildable and nothing is using them. Clear them now,
    because an app that is always open never gives another chance."""
    import scratch
    running = running_apps(classify(list_processes(), cfg, os.getuid()))
    if app in running:
        return None
    rows = scratch.census(only_app=app)
    r = scratch.reclaim("safe", dry_run=False, running=running, rows=rows)
    rec = log_event("scratch", trigger="quit", app=app, freed_mb=r["freed_mb"], items=r["items"], skipped=r["skipped"])
    if r["freed_mb"] >= 512:
        notify("Guardian", f"{app} quit, so I cleared {r['freed_mb'] / 1024:.1f}GB of its caches. It rebuilds them as needed.", cfg)
    return rec


def disk_trend(hours: float):
    """Change in free space over the last N hours from the 30 s samples (GB, or None)."""
    if not SAMPLES_PATH.exists():
        return None
    cutoff = datetime.now() - timedelta(hours=hours)
    vals = []
    for line in SAMPLES_PATH.read_text().splitlines()[1:]:
        parts = line.split("\t")
        try:
            if datetime.fromisoformat(parts[0]) >= cutoff:
                vals.append(float(parts[6]))
        except (ValueError, IndexError):
            continue
    return round(vals[-1] - vals[0], 1) if len(vals) >= 2 else None


def big_items(folders: list, top: int = 12) -> list:
    """The biggest top-level items in the given folders: (mb, date of the newest change anywhere
    inside, path). Read-only. (A folder's own date only moves when something is added or removed
    directly in it: the first real Mac's 22 GB folder read 'September' with work from last week.)"""
    import archive
    import scratch
    out = []
    for folder in folders:
        try:
            entries = [e for e in Path(folder).iterdir() if not e.name.startswith(".")]
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir() and not e.is_symlink():
                    try:
                        st = archive.tree_stat(e)
                        mb, when = st["disk"] // 1048576, st["newest"]
                    except OSError:               # part of it is unreadable: size from du, folder's own date
                        mb, when = scratch.du_kb(e) // 1024, e.lstat().st_mtime
                else:
                    mb, when = e.lstat().st_size // 1048576, e.lstat().st_mtime
                out.append((mb, datetime.fromtimestamp(when).strftime("%Y-%m-%d"), str(e)))
            except OSError:
                continue
    return sorted(out, reverse=True)[:top]


def disk_cmd(cfg: dict, args):
    import scratch
    if args.big is not None or args.inside:
        folders = [Path(args.inside).expanduser()] if args.inside else \
            [HOME / "Downloads", HOME / "Documents", HOME / "Desktop"]
        where = str(folders[0]).replace(str(HOME), "~") if args.inside else "Downloads, Documents and Desktop"
        print(f"Biggest items in {where} (yours to decide; guardian never deletes these):")
        for mb, when, path in big_items(folders, args.big or 15):
            print(f"  {mb / 1024:7.2f} GB  last changed {when}  {path.replace(str(HOME), '~')}")
        return
    if args.snapshot:
        print("measuring (a minute or two)...", flush=True)
        write_ledger()
    s = sample_system()
    free, floor = s.get("disk_free_gb"), cfg["disk_floor_gb"]
    print(f"Disk: {free} GB free (guardian's floor is {floor} GB; free disk is also the ceiling for swap)")
    h1, h24 = disk_trend(1), disk_trend(24)
    fmt = lambda v: "no data" if v is None else f"{v:+.1f} GB"
    print(f"  last hour {fmt(h1)}    last 24 hours {fmt(h24)}")
    entries = read_ledger()
    if len(entries) >= 2:
        for label, base in (("previous snapshot", entries[-2]), ("oldest in 24 hours", ledger_baseline(entries, 24))):
            if base is None or (label.startswith("oldest") and base is entries[-2]):
                continue
            print(f"  Where it went, {label}:")
            for line in scratch.render_ledger_diff(scratch.ledger_diff(base, entries[-1])):
                print("    " + line)
    elif entries:
        print(f"  One snapshot so far ({entries[-1]['ts'][11:16]}); the next one will show what changed.")
    else:
        print("  No snapshot yet: run `guardian.py disk --snapshot`, or wait for the agent's first one.")
    if entries:
        latest = entries[-1]["items"]
        running = running_apps(classify(list_processes(), cfg, os.getuid()))
        mine, yours = [], []
        for name, _globs, tier, _what, _method, app in scratch.LOCATIONS:
            mb = latest.get(name, 0)
            if mb < 200:
                continue
            if tier in ("safe", "safe-old"):
                who = scratch.blocked_by({"app": app}, running)
                mine.append((mb, name, f"when {who} quits or is refreshed" if who else
                             "old entries only, at the next tidy-up" if tier == "safe-old" else "at the next tidy-up"))
            else:
                yours.append((mb, name))
        outside = [(mb, n) for n, mb in latest.items() if n in ("Temporary files", "Swap files", "Applications",
                                                                 "Apple downloads", "System logs") and mb >= 200]
        if mine:
            print("  Guardian gets back on its own:")
            for mb, name, when in sorted(mine, reverse=True):
                print(f"    {mb / 1024:6.1f} GB  {name:26} {when}")
        if yours:
            print("  Yours to decide (measured, never touched):")
            for mb, name in sorted(yours, reverse=True)[:8]:
                print(f"    {mb / 1024:6.1f} GB  {name}")
        if outside:
            print("  Outside your home folder:")
            for mb, name in sorted(outside, reverse=True):
                print(f"    {mb / 1024:6.1f} GB  {name}")
        if entries[-1].get("unreadable"):
            print("  Not measured in the latest snapshot (macOS did not allow it; see guardian.py doctor): "
                  + ", ".join(entries[-1]["unreadable"]))
    print("More: disk --snapshot (measure now)   disk --big (biggest items in your folders)   disk --big --in FOLDER")
    print("Old work folders can move to an external drive, checked before anything is removed: guardian.py archive")


# --------------------------------------------------------------------------
# Access: macOS decides per program which of your folders it may read
# --------------------------------------------------------------------------

def access_check(cfg: dict) -> dict:
    """Which of the owner's folders this very process may list. The background agent can be
    refused what the same command typed in Terminal is allowed (the first real Mac's agent
    read Documents, Downloads and Desktop as empty), so only the agent's own answer counts."""
    import archive
    import scratch
    places = [HOME / n for n in ("Documents", "Downloads", "Desktop")]
    places += [archive.resolve_root(r) for r in (cfg.get("archive") or {}).get("roots", [])]
    places += [Path(v["path"]) for v in archive.volumes()]
    ok, blocked, errors = [], [], {}
    for p in places:
        name = str(p).replace(str(HOME), "~")
        try:
            if not p.is_dir() or name in ok or name in blocked:
                continue
        except OSError:
            pass
        if any(name.startswith(b + "/") for b in blocked):
            continue                                # its parent is already named
        (ok if scratch.readable(p) else blocked).append(name)
        if name in blocked:
            try:
                os.scandir(p).close()
            except OSError as e:
                errors[name] = f"{type(e).__name__}: errno {e.errno} {e.strerror}"
    program = sh(["ps", "-o", "comm=", "-p", str(os.getpid())]).strip() or sys.executable
    # Places only Full Disk Access opens: tells "no permission at all" from "folders only".
    probes = [HOME / "Library" / n for n in ("Safari", "Mail", "Messages")]
    full = next((scratch.readable(q) for q in probes if q.is_dir()), None)
    return {"ts": time.time(), "ok": ok, "blocked": blocked, "program": program, "errors": errors,
            "full_disk_access": full}


def access_report(cfg: dict, announce: bool = True) -> dict:
    """Check, write the answer to the diary (doctor reads it from there), and say so once a
    week while something is blocked."""
    a = access_check(cfg)
    told = any(e.get("kind") == "access" and e.get("notified") for e in read_events(7 * 24))
    tell = bool(a["blocked"]) and announce and not told
    log_event("access", ok=a["ok"], blocked=a["blocked"], program=a["program"], notified=tell,
              errors=a.get("errors") or {}, full_disk_access=a.get("full_disk_access"))
    if tell:
        notify("Guardian", f"macOS is not letting Guardian's background helper read {', '.join(a['blocked'])}. "
                           "It cannot measure them or offer to move old work folders. "
                           "The steps are in: guardian.py doctor", cfg)
    return a


def access_help(program: str) -> list:
    app = program.split(".app/")[0] + ".app" if ".app/" in program else program
    return ["macOS privacy protection decides this per program; the same command in Terminal is a different program.",
            "macOS does not ask about a background helper and does not list it under Files and Folders,",
            "so the way in is: System Settings > Privacy & Security > Full Disk Access. Drag this program",
            "into the list (or use + and paste its path), then check its switch is on:",
            f"  {app}",
            "To see it in Finder next to that page:  open -R '" + app + "'",
            "This lets any background job run by this Python read your files; switch it off there any time.",
            "Then run `guardian.py install` (restarts the helper as that exact program) and `guardian.py doctor`."]


# --------------------------------------------------------------------------
# Archive: old work folders move to an external drive, when you say so
# --------------------------------------------------------------------------

ARCHIVE_BUTTONS = ["Not now", "Show me", "Move them"]


def archive_manifest() -> Path:
    return LOG_DIR / "archive.jsonl"


def archive_plan(cfg: dict, days=None, to=None, only=None, roots=None) -> dict:
    """What could move and where to. Read-only: one walk of each root."""
    import archive
    acfg = cfg["archive"]
    days = acfg["min_age_days"] if days is None else days
    rows = archive.read_manifest(archive_manifest())
    problems = archive.root_problems(roots or acfg["roots"])
    found = archive.scan(roots or acfg["roots"], days, acfg["min_folder_mb"], session_dirs=acfg["session_dirs"],
                         restored=archive.restored_at(rows))
    move = [c for c in found if not c["keep"] and (not only or c["name"] in only)]
    vol, why = archive.pick_destination(archive.volumes(), to or acfg.get("destination") or "",
                                        sum(c["logical_mb"] for c in move))
    return {"days": days, "move": move, "keep": [c for c in found if c["keep"]], "volume": vol, "why": why,
            "mb": sum(c["mb"] for c in move), "problems": problems}


def archive_lines(plan: dict) -> list:
    """The plan as plain lines: for the command line and for the dialog's 'Show me'."""
    short = lambda p: p.replace(str(HOME), "~")
    out = [f"Could not look in {short(root)}: {why}." for root, why in plan.get("problems") or []]
    if plan["move"]:
        out.append(f"Not used for {plan['days']}+ days (no file changed, no Codex or Claude Code thread worked there):")
        for c in plan["move"]:
            out.append(f"  {c['mb'] / 1024:7.2f} GB  unused {c['age_days']:4d} days  {short(c['path'])}")
        out.append(f"  Total {plan['mb'] / 1024:.1f} GB in {len(plan['move'])} folders.")
    elif not out or plan["keep"]:
        out.append(f"No work folder has been unused for {plan['days']}+ days.")
    if plan["keep"]:
        out.append(f"Staying on this Mac ({len(plan['keep'])}):")
        for c in plan["keep"][:10]:
            out.append(f"  {c['mb'] / 1024:7.2f} GB  {c['name']}: {c['keep']}")
        if len(plan["keep"]) > 10:
            out.append(f"  ... and {len(plan['keep']) - 10} smaller ones")
    vol = plan["volume"]
    if vol:
        import archive
        where = sorted({str(archive.dest_dir(vol, c["root"])) for c in plan["move"]})
        out.append(f"Destination: {vol['name']} ({vol['free_mb'] / 1024:.0f} GB free)"
                   + (": " + ", ".join(where) if where else ""))
    else:
        out.append(f"Destination: none ({plan['why']})")
    return out


def archive_text(plan: dict, free_gb) -> str:
    move, n = plan["move"], len(plan["move"])
    roots = ", ".join(sorted({Path(c["root"]).name for c in move}))
    free = f"This Mac has {free_gb:.0f} GB free. " if free_gb is not None else ""
    return (f"{free}{n} folder{'s' if n != 1 else ''} in {roots} {'have' if n != 1 else 'has'} not been used "
            f"for {plan['days']}+ days and take{'' if n != 1 else 's'} {plan['mb'] / 1024:.1f} GB (the biggest is "
            f"{move[0]['name']}, {move[0]['mb'] / 1024:.1f} GB). Move {'them' if n != 1 else 'it'} to "
            f"{plan['volume']['name']}? Each folder is copied, the copy is checked byte for byte, and only "
            "then is it removed here. Any folder can be brought back later.")


def archive_run(cfg: dict, plan: dict, announce: bool = False, out=print) -> dict:
    """Move every folder in the plan, one at a time. Only one run at a time (a lock file)."""
    import archive
    import fcntl
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    lock = open(LOG_DIR / "archive.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        out("another archive run is in progress")
        return {"moved": [], "kept": [], "busy": True}
    vol = plan["volume"]
    free0 = sample_system().get("disk_free_gb")
    log_event("archive", phase="started", folders=len(plan["move"]), mb=plan["mb"], volume=vol["name"])
    hint = f"python3 {Path(__file__).resolve()} archive --restore"
    moved, kept = [], []
    try:
        for c in plan["move"]:
            out(f"  {c['name']}: copying {c['mb'] / 1024:.1f} GB to {vol['name']} and checking the copy ...")
            r = archive.archive_one(c, archive.dest_dir(vol, c["root"]), manifest=archive_manifest(),
                                    restore_hint=hint)
            log_event("archive", phase="moved" if r["ok"] else "kept", name=r["name"], mb=r["mb"], why=r["why"],
                      archive=r.get("archive"), seconds=r.get("seconds"))
            (moved if r["ok"] else kept).append(r)
            out(f"    moved in {r['seconds']:.0f}s" + (f" ({r['why']})" if r["why"] else "") if r["ok"]
                else f"    left where it was: {r['why']}")
            if not r["ok"] and not os.path.ismount(vol["path"]):
                out(f"  {vol['name']} is no longer connected; stopping")
                break
    finally:
        lock.close()
    free1 = sample_system().get("disk_free_gb")
    mb = sum(r["mb"] for r in moved)
    if moved:
        text = (f"Moved {len(moved)} folder{'s' if len(moved) != 1 else ''} ({mb / 1024:.1f} GB) to {vol['name']}; "
                f"each copy was checked before the folder was removed. This Mac now has {free1} GB free.")
    else:
        text = "No folder was moved."
    if kept:
        text += f" {len(kept)} stayed: " + "; ".join(f"{r['name']} ({r['why']})" for r in kept[:3]) + "."
    if moved:
        text += " Bring one back: guardian.py archive --restore NAME."
    log_event("archive", phase="done", moved=len(moved), mb=mb, kept=[[r["name"], r["why"]] for r in kept],
              volume=vol["name"], free_before=free0, free_after=free1, text=text)
    if announce:
        notify("Guardian", text, cfg)
    return {"moved": moved, "kept": kept, "text": text}


class ArchiveOps:
    """What the archive offer does to the machine, in one place so tests can substitute it."""

    def volumes(self) -> list:
        import archive
        return archive.volumes()

    def plan(self, cfg: dict) -> dict:
        return archive_plan(cfg)

    def user_idle(self):
        return MacAppOps().user_idle()

    def ask(self, text: str, buttons: list, default: str) -> str:
        return ask_dialog(text, buttons, default, timeout=300)

    def show(self, plan: dict):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / "archive-plan.txt"
        path.write_text("\n".join(
            [f"Guardian, {datetime.now():%Y-%m-%d %H:%M}: what could move to an external drive", ""]
            + archive_lines(plan) + ["", "Nothing has been copied or removed. Guardian will ask again shortly.",
                                     f"Or do it yourself: python3 {Path(__file__).resolve()} archive --yes"]) + "\n")
        subprocess.run(["open", "-t", str(path)], capture_output=True, text=True, timeout=30)

    def start(self, cfg: dict):
        """The copy runs in its own low-priority process: it can take half an hour, and the
        worker slot must stay free for everything else."""
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(Path(__file__).resolve()), "archive", "--yes", "--announce"]
        if shutil.which("nice"):
            cmd = ["nice", "-n", "10"] + cmd
        return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=open(LOG_DIR / "archive.out.log", "ab"),
                                stderr=subprocess.STDOUT)


def archive_ask(cfg: dict, st: dict, plan: dict, free_gb, ops=None) -> dict:
    """Ask the owner. The safe answer is the default button, so a stray Return moves nothing."""
    ops = ops or ArchiveOps()
    log_event("archive", phase="asked", folders=len(plan["move"]), mb=plan["mb"], volume=plan["volume"]["name"])
    answer = ops.ask(archive_text(plan, free_gb), ARCHIVE_BUTTONS, "Not now")
    if answer == "Move them":
        st["scan"] = None
        st["proc"] = ops.start(cfg)
        return log_event("archive", phase="accepted", folders=len(plan["move"]), mb=plan["mb"])
    if answer == "Show me":
        ops.show(plan)
    minutes = {"Show me": 10, "Not now": cfg["archive"]["snooze_days"] * 1440}.get(answer, 120)
    st["snooze_until"] = time.time() + minutes * 60
    return log_event("archive", phase={"Show me": "shown", "Not now": "declined"}.get(answer, "unanswered"),
                     snooze_minutes=minutes)


def archive_state_from_events(days: float = 14) -> dict:
    """Rebuild the snooze after a restart, so a restart never re-asks at once."""
    st = {"snooze_until": 0.0, "next_check": 0.0, "scan": None, "proc": None}
    for e in read_events(days * 24):
        if e.get("kind") != "archive":
            continue
        ts = datetime.fromisoformat(e["ts"]).timestamp()
        if e.get("phase") in ("declined", "unanswered", "shown"):
            st["snooze_until"] = max(st["snooze_until"], ts + e.get("snooze_minutes", 120) * 60)
        elif e.get("phase") in ("accepted", "done"):
            st["snooze_until"] = max(st["snooze_until"], ts + 6 * 3600)
    return st


def archive_tick(cfg: dict, snap: dict, st: dict, background, now: float, ops=None, dry_run: bool = False):
    """Called once per sample. Offers only when the disk is tight, an external drive is
    connected, enough would move to matter, and you are at the keyboard to answer.
    Returns 'scan' or 'ask' when it started a job, else None."""
    acfg = cfg.get("archive") or {}
    proc = st.get("proc")
    if proc is not None:
        if proc.poll() is None:
            return None                              # a move is running
        st["proc"], st["scan"] = None, None
        st["snooze_until"] = max(st.get("snooze_until", 0.0), now + 6 * 3600)
    if not acfg.get("offer") or cfg["mode"] == "observe" or snap.get("quiet") or dry_run \
            or background is None or background.busy():
        return None
    free = snap["sample"].get("disk_free_gb")
    if free is None or free >= acfg["offer_below_gb"] or now < st.get("snooze_until", 0.0) \
            or now < st.get("next_check", 0.0):
        return None
    st["next_check"] = now + 300
    ops = ops or ArchiveOps()
    names = {v["name"] for v in ops.volumes()}
    if not names:
        return None
    scan = st.get("scan")
    if scan is None or now - scan["ts"] > acfg["scan_hours"] * 3600 or \
            (scan["plan"]["volume"] and scan["plan"]["volume"]["name"] not in names):
        def scan_job():
            plan = ops.plan(cfg)
            st["scan"] = {"ts": time.time(), "plan": plan}
            st["next_check"] = 0.0
            log_event("archive", phase="scan", folders=len(plan["move"]), mb=plan["mb"],
                      volume=plan["volume"]["name"] if plan["volume"] else None, why=plan["why"],
                      problems=plan.get("problems") or [])
        return "scan" if background.submit("archive-scan", scan_job) else None
    plan = scan["plan"]
    if plan["volume"] is None or plan["mb"] < acfg["offer_min_gb"] * 1024:
        return None                                  # not worth a dialog; the next scan may differ
    idle = ops.user_idle()
    if idle is not None and idle > 120:
        return None                                  # ask when you are there to answer
    return "ask" if background.submit("archive-ask", lambda: archive_ask(cfg, st, plan, free, ops)) else None


def archive_cmd(cfg: dict, args):
    import archive
    manifest = archive_manifest()
    if args.offer:
        apply_config_change({"archive": {"offer": args.offer == "on"}}, f"archive offer {args.offer}")
        print(f"offer {args.offer}: guardian " + ("asks when the disk is tight and a drive is connected"
                                                 if args.offer == "on" else "will not ask; `guardian.py archive` still works"))
        return
    rows = archive.read_manifest(manifest)
    if args.list:
        there = archive.on_drive(rows)
        if not there:
            print("Nothing has been moved to a drive.")
            return
        print("Moved to an external drive (bring one back: guardian.py archive --restore NAME):")
        for r in there:
            here = "connected" if Path(r["archive"]).exists() else "drive not connected"
            print(f"  {r['ts'][:10]}  {r['mb'] / 1024:6.1f} GB  {r['name']:22} {r['archive']}  ({here})")
        return
    if args.restore:
        want = str(Path(args.restore).expanduser())
        found = [r for r in archive.on_drive(rows) if args.restore == r["name"] or want == r["source"]]
        if not found:
            print(f"nothing called {args.restore} is on a drive; see: guardian.py archive --list")
            return
        row = found[-1]
        print(f"bringing back {row['name']} ({row['mb'] / 1024:.1f} GB) from {row['archive']} ...", flush=True)
        r = archive.restore(row, manifest=manifest)
        log_event("archive", phase="restored" if r["ok"] else "restore-failed", name=row["name"], mb=row["mb"],
                  why=r["why"])
        print(f"  back at {r['source']} (the drive keeps its copy)" if r["ok"] else f"  not restored: {r['why']}")
        return
    if not args.announce:
        print("measuring (up to a minute)...", flush=True)
    roots = None
    if args.root:
        roots = [str(Path(r).expanduser().resolve()) for r in args.root]
        for r in roots:
            why = archive.root_problem(Path(r))
            if why:
                print(f"{r}: {why}")
                return
    plan = archive_plan(cfg, days=args.older_than, to=args.to, only=args.only, roots=roots)
    for line in archive_lines(plan):
        print(line)
    if not args.yes:
        print("Dry run: nothing was copied or removed. Do it: guardian.py archive --yes")
        print("Choose: --only NAME ...   --older-than DAYS   --to DRIVE   --root FOLDER (look inside another folder)")
        return
    if not plan["move"]:
        return
    if plan["volume"] is None:
        print(f"Nothing moved: {plan['why']}.")
        if args.announce:
            notify("Guardian", f"No folder was moved: {plan['why']}.", cfg)
        return
    try:
        os.nice(10)
    except OSError:
        pass
    res = archive_run(cfg, plan, announce=args.announce, out=lambda t: print(t, flush=True))
    if res.get("text"):
        print(res["text"])


# --------------------------------------------------------------------------
# Snapshot and status
# --------------------------------------------------------------------------

def snapshot(cfg: dict) -> dict:
    sample = sample_system()
    procs = classify(list_processes(), cfg, os.getuid())
    groups = aggregate([p for p in procs if p.cls != "foreign"], cfg)
    classes = defaultdict(lambda: {"rss_mb": 0, "n": 0})
    for p in procs:
        if p.cls == "foreign":
            continue
        c = classes[p.cls.split("/")[0]]
        c["rss_mb"] += p.rss_mb
        c["n"] += 1
    for c in classes.values():
        c["rss_mb"] = round(c["rss_mb"])
    return {"sample": sample, "groups": groups, "classes": dict(classes),
            "procs": procs, "quiet": quiet_mode(procs, cfg)}


def fmt_gb(mb) -> str:
    return f"{(mb or 0) / 1024:.1f}GB"


def print_status(cfg: dict, snap: dict, n: int = 12):
    s = snap["sample"]
    print(f"guardian {VERSION} on {HOSTNAME}  mode={cfg['mode']}"
          f"{'  AUTOPILOT' if cfg.get('autopilot') else ''}{'  PAUSED' if PAUSE_PATH.exists() else ''}")
    print(f"  memory pressure : {pressure_word(s['pressure_level'])}   free {s.get('free_pct')}%   "
          f"swap {fmt_gb(s.get('swap_used_mb'))}/{fmt_gb(s.get('swap_total_mb'))}   "
          f"compressed {fmt_gb(s.get('compressed_mb'))}   RAM {fmt_gb(s.get('mem_total_mb'))}")
    print(f"  load / thermal  : load1 {s.get('load1')}   cpu speed limit {s.get('cpu_speed_limit')}%   "
          f"disk free {s.get('disk_free_gb')}GB")
    if snap["quiet"]:
        print(f"  quiet mode      : {snap['quiet']} is running; notifications and kills held")
    print("  by class        : " + "  ".join(f"{k} {fmt_gb(v['rss_mb'])}/{v['n']}p"
                                            for k, v in sorted(snap["classes"].items(),
                                                               key=lambda kv: -kv[1]['rss_mb'])))
    print(f"  top {n} by memory (helpers folded into their app):")
    for g in snap["groups"][:n]:
        print(f"    {fmt_gb(g['rss_mb']):>8}  {g['cpu']:5.1f}% cpu  {g['n']:3d}p  [{g['class']}]  {g['key']}")
    ai = [g for g in snap["groups"] if g["class"] in ("ai_app", "mcp_server", "agent_session", "mcp_orphan")]
    if ai:
        print("  AI on this Mac  : " + ", ".join(f"{g['key']} {fmt_gb(g['rss_mb'])}/{g['n']}p" for g in ai))
    watched = [g for g in snap["groups"] if g["class"] == "watched"]
    for g in watched:
        print(f"  watched         : {g['key']} {fmt_gb(g['rss_mb'])} {g['cpu']}% cpu")


# --------------------------------------------------------------------------
# Watch loop (what launchd runs)
# --------------------------------------------------------------------------

def read_events(hours: float) -> list:
    if not EVENTS_PATH.exists():
        return []
    cutoff = datetime.now() - timedelta(hours=hours)
    out = []
    for line in EVENTS_PATH.read_text().splitlines():
        try:
            rec = json.loads(line)
            if datetime.fromisoformat(rec["ts"]) >= cutoff:
                out.append(rec)
        except Exception:
            continue
    return out


def parse_simulate(spec: str) -> dict:
    """'level=4,free=3,disk=9' -> sample overrides (for testing the policy without a real crunch)."""
    out = {}
    names = {"level": "pressure_level", "free": "free_pct", "disk": "disk_free_gb", "therm": "cpu_speed_limit"}
    for part in (spec or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[names.get(k.strip(), k.strip())] = float(v) if "." in v else int(v)
    return out


def watch(cfg: dict, once: bool = False, dry_run: bool = False, simulate: dict = None):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    engine = Engine(cfg)
    background = None if once else Background()
    log_event("start", version=VERSION, mode=cfg["mode"], interval=cfg["interval_seconds"], dry_run=dry_run)
    snap = snapshot(cfg)
    s = snap["sample"]
    if s.get("disk_free_gb") is not None and s.get("mem_total_mb") and \
            s["disk_free_gb"] * 1024 < s["mem_total_mb"]:
        log_event("health", note=f"disk free {s['disk_free_gb']}GB is below RAM size; swap ceiling is low")
    last_digest_day = None
    ai = {"day": None, "runs": 0, "retry_after": 0.0, "fail_notified": None}
    refresh_state = refresh_state_from_events()
    archive_state = archive_state_from_events()
    access = {"ts": time.time(), "ok": [], "blocked": []} if once else access_report(cfg)
    disk_hist = deque(maxlen=400)
    ledger = read_ledger(1)
    last_ledger = datetime.fromisoformat(ledger[-1]["ts"]).timestamp() if ledger else 0.0
    last_drop_alert = 0.0
    quit_state = {}
    guard = None
    up_since = time.time()
    cfg_mtime = CONFIG_PATH.stat().st_mtime if CONFIG_PATH.exists() else None
    last_hygiene = None
    for e in reversed(read_events(48)):
        if e["kind"] == "hygiene":
            last_hygiene = datetime.fromisoformat(e["ts"]).timestamp()
            break
    while True:
        try:
            # live config reload (autopilot tuning, `config --set`, `autopilot on/off`)
            mt = CONFIG_PATH.stat().st_mtime if CONFIG_PATH.exists() else None
            if mt != cfg_mtime:
                cfg_mtime = mt
                cfg = load_config()
                engine.cfg = cfg
                log_event("reload", mode=cfg["mode"], autopilot=cfg.get("autopilot", False))
            if PAUSE_PATH.exists():
                time.sleep(cfg["interval_seconds"])
                if once:
                    break
                continue
            snap = snapshot(cfg)
            if simulate:
                snap["sample"].update(simulate)
                snap["sample"]["simulated"] = True
            decisions = engine.step(snap["sample"], snap["procs"])
            if not simulate:
                log_sample(snap["sample"], snap["groups"])
            applied = apply_decisions(decisions, cfg, quiet=snap["quiet"], dry_run=dry_run,
                                      simulated=bool(simulate), running=running_apps(snap["procs"]),
                                      background=background)
            if once:
                for a in applied:
                    print(json.dumps(a, default=str))
                break
            if not simulate:
                refresh_tick(cfg, snap, refresh_state, background, time.time(), dry_run=dry_run)
                if access["blocked"] and time.time() - access["ts"] > 600:
                    again = access_check(cfg)          # has the owner allowed it since?
                    if again["blocked"] != access["blocked"]:
                        log_event("access", ok=again["ok"], blocked=again["blocked"], program=again["program"],
                                  notified=False)
                        archive_state["scan"], archive_state["next_check"] = None, 0.0
                    access = again
                archive_tick(cfg, snap, archive_state, background, time.time(), dry_run=dry_run)
                # ---- disk: ledger, fast-drop alert, caches of an app that just quit
                dcfg, t_now = cfg["disk"], time.time()
                free_gb = snap["sample"].get("disk_free_gb")
                if free_gb is not None:
                    disk_hist.append((t_now, free_gb))
                fell = disk_drop(list(disk_hist), t_now, dcfg["alert_window_minutes"] * 60, dcfg["alert_drop_gb"])
                if fell and t_now - last_drop_alert > 3 * 3600 and not background.busy():
                    last_drop_alert = last_ledger = t_now
                    background.submit("disk-drop", lambda fell=fell, q=snap["quiet"]: disk_drop_job(cfg, fell, q))
                elif t_now - last_ledger > dcfg["ledger_hours"] * 3600 and not background.busy():
                    last_ledger = t_now
                    background.submit("ledger", write_ledger)
                if guard is None:
                    import scratch
                    guard = scratch.guard_apps()
                for app in quit_tracker(quit_state, running_apps(snap["procs"]), guard):
                    tight = free_gb is not None and free_gb < dcfg["clear_on_quit_below_gb"]
                    if not (cfg["mode"] == "act" and cfg["scratch"]["auto_reclaim_in_act_mode"]
                            and dcfg["clear_caches_on_quit"] and tight and not dry_run):
                        continue
                    if not background.submit(f"quit:{app}", lambda app=app: clear_caches_on_quit(app, cfg)):
                        quit_state["seen"].add(app)      # worker busy: notice the quit again next time
            today = datetime.now().date()
            if ai["day"] != today:
                ai.update(day=today, runs=0)
            # AI diagnosis after a bad day, at most N real diagnoses a day. It runs on the
            # worker (the CLI can take minutes); a failure does not use up the day's run.
            if engine.episodes_today >= cfg["ai"]["auto_after_episodes"] and \
                    ai["runs"] < cfg["ai"]["max_runs_per_day"] and engine.episode is None and \
                    time.time() >= ai["retry_after"] and not background.busy():
                def ask_job(cfg=cfg, episodes=engine.episodes_today, today=today):
                    outcome = {}
                    ask(cfg, hours=24, quiet=True, outcome=outcome)
                    msg = record_ask_outcome(ai, outcome, time.time(), today)
                    if msg:
                        notify("Guardian", f"{episodes} pressure episodes today. {msg}", cfg)
                background.submit("ask", ask_job)
            # Proactive hygiene (autopilot / act mode only): old logs and trash daily, safe
            # caches when they are big or the disk is tight. Nothing in the review tier, ever.
            now = datetime.now()
            if cfg["mode"] == "act" and not snap["quiet"] and hygiene_due(now, last_hygiene, cfg, up_since) \
                    and not background.busy():
                last_hygiene = now.timestamp()

                def hygiene_job(cfg=cfg, sample=snap["sample"], running=running_apps(snap["procs"])):
                    h = run_hygiene(cfg, sample, running, dry_run=dry_run)
                    log_event("hygiene", **h)
                    if h["freed_mb"] >= 256:
                        notify("Guardian", f"Tidied up: freed {h['freed_mb'] / 1024:.1f}GB of caches and old logs.", cfg)
                background.submit("hygiene", hygiene_job)
            # Daily digest
            if now.hour == cfg["digest_hour"] and last_digest_day != now.date():
                last_digest_day = now.date()
                path = write_digest(cfg, 24)
                if path and not snap["quiet"]:
                    notify("Guardian", digest_oneliner(24), cfg)
        except Exception as e:
            log_event("error", error=repr(e))
        time.sleep(cfg["interval_seconds"])


# --------------------------------------------------------------------------
# Reports and digests
# --------------------------------------------------------------------------

def summarize(hours: float) -> dict:
    ev = [e for e in read_events(hours) if not e.get("simulated")]
    episodes = [e for e in ev if e["kind"] == "decision" and e["class"] == "episode" and "ended" in e["reason"]]
    started = [e for e in ev if e["kind"] == "decision" and e["class"] == "episode" and "started" in e["reason"]]
    actions = [e for e in ev if e["kind"] == "decision" and e["action"] in ("kill", "renice")]
    notifies = [e for e in ev if e["kind"] == "decision" and e["action"] == "notify"]
    errors = [e for e in ev if e["kind"] == "error"]
    offenders = defaultdict(int)
    for e in episodes:
        m = re.search(r"top: (.*)$", e["reason"])
        if m:
            for part in m.group(1).split(", "):
                name = part.rsplit(" ", 1)[0]
                offenders[name] += 1
    for e in actions + notifies:
        if e.get("proc"):
            offenders[e["proc"]["key"]] += 1
    samples = []
    if SAMPLES_PATH.exists():
        cutoff = datetime.now() - timedelta(hours=hours)
        for line in SAMPLES_PATH.read_text().splitlines()[1:]:
            parts = line.split("\t")
            try:
                if datetime.fromisoformat(parts[0]) >= cutoff:
                    samples.append(parts)
            except Exception:
                continue
    warn_samples = sum(1 for p in samples if p[1] not in ("1", "None"))
    return {"hours": hours, "episodes": len(started), "episode_details": episodes, "actions": actions,
            "notifies": notifies, "errors": errors, "offenders": sorted(offenders.items(), key=lambda kv: -kv[1]),
            "samples": len(samples), "pct_time_under_pressure": round(100 * warn_samples / max(1, len(samples)))}


def digest_oneliner(hours: float) -> str:
    s = summarize(hours)
    top = ", ".join(k for k, _ in s["offenders"][:3]) or "nobody in particular"
    return (f"Last {int(hours)}h: {s['episodes']} pressure episodes, under pressure {s['pct_time_under_pressure']}% "
            f"of the time, {len(s['actions'])} actions. Usual suspects: {top}.")


def render_report(hours: float) -> str:
    s = summarize(hours)
    lines = [f"# Guardian report for {HOSTNAME}, last {int(hours)}h ({datetime.now():%Y-%m-%d %H:%M})", ""]
    lines.append(f"- Samples: {s['samples']}  |  time under memory pressure: {s['pct_time_under_pressure']}%")
    lines.append(f"- Pressure episodes: {s['episodes']}  |  actions taken or proposed: {len(s['actions'])}  |  "
                 f"notifications: {len(s['notifies'])}  |  errors: {len(s['errors'])}")
    lines.append("")
    lines.append("## Usual suspects (times named as a top offender)")
    for k, n in s["offenders"][:10]:
        lines.append(f"- {k}: {n}")
    if not s["offenders"]:
        lines.append("- none recorded")
    lines.append("")
    lines.append("## Episodes")
    for e in s["episode_details"][-15:]:
        lines.append(f"- {e['ts']}: {e['reason']}")
    if not s["episode_details"]:
        lines.append("- none")
    lines.append("")
    entries = read_ledger()
    base = ledger_baseline(entries, hours)
    if base is not None:
        import scratch
        lines.append("## Disk (what the free space was spent on)")
        lines += ["- " + ln.strip() for ln in scratch.render_ledger_diff(scratch.ledger_diff(base, entries[-1]))]
        lines.append("")
    refreshes = [e for e in read_events(hours) if e.get("kind") == "refresh"
                 and e.get("phase") in ("done", "aborted", "declined")]
    if refreshes:
        lines.append("## Refreshes (quit cleanly, clear caches, reopen)")
        for e in refreshes[-10:]:
            lines.append(f"- {e['ts']}: {e.get('app')}: {e.get('phase')}"
                         + (f": {e['result']}" if e.get("result") else ""))
        lines.append("")
    moves = [e for e in read_events(hours) if e.get("kind") == "archive"
             and e.get("phase") in ("done", "restored", "declined")]
    if moves:
        lines.append("## Archive (old work folders moved to an external drive)")
        for e in moves[-10:]:
            lines.append(f"- {e['ts']}: " + (e.get("text") or f"{e['phase']}" + (f" {e['name']}" if e.get("name") else "")))
        lines.append("")
    lines.append("## Actions")
    for e in s["actions"][-20:]:
        who = e["proc"]["key"] if e.get("proc") else "-"
        lines.append(f"- {e['ts']}: {e['action']} {who}: {e['reason']} -> {e['result']}")
    if not s["actions"]:
        lines.append("- none")
    if s["errors"]:
        lines.append("")
        lines.append("## Errors")
        for e in s["errors"][-10:]:
            lines.append(f"- {e['ts']}: {e['error']}")
    return "\n".join(lines) + "\n"


def write_digest(cfg: dict, hours: float):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"digest-{datetime.now():%Y-%m-%d}.md"
    path.write_text(render_report(hours))
    log_event("digest", path=str(path))
    return path


# --------------------------------------------------------------------------
# AI layer: hand the diary to Claude Code or Codex
# --------------------------------------------------------------------------

ASK_PROMPT = """You are diagnosing why a Mac laptop keeps slowing down. Below is a diary from a
small watchdog ("guardian") that runs on the machine: its config, a live snapshot
of memory pressure and the biggest process groups, and a summary of the last
{hours} hours of pressure episodes and actions.

Answer in this exact shape:

## What is actually slowing this Mac down
Three bullets max, most likely cause first. Name specific apps/processes from the data.
Say what is normal (e.g. Chrome using 4GB with 40 tabs is normal) versus what is a problem.

## What to do once, by hand
Concrete, ordered, each one line. Chrome settings (Memory Saver, extensions),
login items, Spotlight, Dropbox selective sync, etc. Only things supported by the data.

## What guardian should do differently
Explain in two sentences, then give a JSON object with ONLY the config keys that
should change, inside a fenced block tagged `json guardian-suggestion`. Valid keys
are the ones in the config shown. If nothing should change, give an empty object.

Keep the whole answer under 400 words. No preamble.

### Config
{config}

### Live snapshot
{snapshot}

### Last {hours} hours
{report}
"""


def find_ai_command(cfg: dict):
    pref = cfg["ai"].get("command", "auto")
    candidates = []
    if pref and pref != "auto":
        candidates.append(pref)
    candidates += ["claude", "codex"]
    for c in candidates:
        exe = shutil.which(c)
        if exe:
            return c, exe
    # launchd's PATH is short; look where the installers actually put the binaries
    for c in candidates:
        places = [HOME / ".local/bin" / c, HOME / ".claude/local" / c, HOME / ".npm-global/bin" / c,
                  Path("/opt/homebrew/bin") / c, Path("/usr/local/bin") / c, HOME / ".volta/bin" / c]
        places += sorted(HOME.glob(f".nvm/versions/node/*/bin/{c}"), reverse=True)
        for pth in places:
            if pth.is_file() and os.access(pth, os.X_OK):
                return c, str(pth)
    return None, None


AUTH_HINTS = ("not logged in", "/login", "please log in", "login required", "invalid api key",
              "authentication_error", "unauthorized", "401")


def ask_failure(returncode, answer: str) -> str:
    """Why the CLI's output is not a diagnosis, or '' when it is one.

    The first real auto-run got "Not logged in · Please run /login" (exit 1) from the claude
    CLI; that line was saved as the diagnosis and logged as ok."""
    text = (answer or "").strip()
    if not text:
        return "printed nothing"
    if len(text) < 400 and any(h in text.lower() for h in AUTH_HINTS):
        return "not logged in"
    if returncode not in (0, None):
        return f"exit {returncode}: {text.splitlines()[0][:120]}"
    return ""


def record_ask_outcome(ai: dict, outcome: dict, now: float, today) -> str:
    """Update the watch loop's diagnosis accounting; returns a notification text or ''.

    A diagnosis counts toward the daily cap. A failure does not, but it is not retried for
    six hours (so a logged-out CLI is not called every 30 s) and is announced once a day."""
    if outcome.get("result") == "ok":
        ai["runs"] += 1
        return f"Diagnosis written to {outcome.get('path_name', 'the log folder')}"
    ai["retry_after"] = now + 6 * 3600
    if ai.get("fail_notified") == today:
        return ""
    ai["fail_notified"] = today
    via, reason = outcome.get("via") or "claude/codex", outcome.get("reason") or "no CLI found"
    if reason == "not logged in":
        return f"Could not get a diagnosis: the {via} command-line tool is not logged in. Run `{via}` in Terminal and sign in."
    return f"Could not get a diagnosis ({via}: {reason})."


def ai_env(base: dict = None) -> dict:
    """Environment for the claude/codex CLI. CLAUDECODE is dropped so `ask` works from inside a
    Claude Code session. USER and LOGNAME are guaranteed: without USER the claude CLI cannot
    find its keychain login on macOS and answers "Not logged in" even when it is logged in."""
    env = dict(os.environ if base is None else base)
    env.pop("CLAUDECODE", None)
    try:
        import pwd
        me = pwd.getpwuid(os.getuid()).pw_name
    except Exception:  # pragma: no cover
        me = env.get("USER") or ""
    if me:
        env.setdefault("USER", me)
        env.setdefault("LOGNAME", me)
    env.setdefault("HOME", str(HOME))
    return env


def ask(cfg: dict, hours: float = 24, quiet: bool = False, outcome: dict = None):
    """Hand the diary to Claude Code / Codex. Returns the diagnosis path, or None when there is
    no diagnosis (no CLI, not logged in, error, timeout); `outcome` is filled either way."""
    outcome = {} if outcome is None else outcome
    snap = snapshot(cfg)
    live = {"sample": {k: v for k, v in snap["sample"].items() if k != "ts"},
            "top": snap["groups"][:15], "by_class": snap["classes"]}
    prompt = ASK_PROMPT.format(hours=int(hours), config=json.dumps(cfg, indent=1),
                               snapshot=json.dumps(live, indent=1, default=str),
                               report=render_report(hours))
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    packet = LOG_DIR / f"ask-packet-{datetime.now():%Y-%m-%d-%H%M}.md"
    packet.write_text(prompt)
    name, exe = find_ai_command(cfg)
    if not exe:
        msg = f"No claude or codex CLI on PATH. Paste this file into any assistant: {packet}"
        if not quiet:
            print(msg)
        log_event("ask", result="no-cli", packet=str(packet))
        outcome.update(result="no-cli", via=None, reason="no claude or codex CLI found")
        return None
    if name == "claude":
        cmd = [exe, "-p", prompt, "--output-format", "text"]
    else:
        cmd = [exe, "exec", "--skip-git-repo-check", prompt]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=cfg["ai"]["timeout_seconds"], env=ai_env(), cwd=str(HOME))
        answer = out.stdout.strip() or out.stderr.strip()
        why = ask_failure(out.returncode, answer)
    except subprocess.TimeoutExpired:
        answer, why = "", f"timed out after {cfg['ai']['timeout_seconds']}s"
    except OSError as e:
        answer, why = "", f"could not run: {e}"
    if why:
        log_event("ask", result="failed", via=name, reason=why, packet=str(packet))
        outcome.update(result="failed", via=name, reason=why)
        if not quiet:
            print(f"No diagnosis: {name} {why}.")
            if why == "not logged in":
                print(f"Run `{name}` in Terminal and sign in, then run this again.")
            print(f"The packet it would have read is at {packet}; you can paste it into any assistant.")
        return None
    path = LOG_DIR / f"diagnosis-{datetime.now():%Y-%m-%d-%H%M}.md"
    path.write_text(f"# Guardian diagnosis via {name} ({datetime.now():%Y-%m-%d %H:%M})\n\n{answer}\n")
    suggestion = None
    m = re.search(r"```json guardian-suggestion\s*(\{.*?\})\s*```", answer, re.S)
    if m:
        try:
            suggestion = json.loads(m.group(1))
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            if cfg["ai"].get("auto_apply_tuning"):
                auto, review = split_tuning(suggestion)
                if auto:
                    apply_config_change(auto, f"auto-tuning from {name} diagnosis {path.name}")
                    notify("Guardian", f"Tuned myself from today's diagnosis: {', '.join(flatten(auto))}. "
                                       f"Undo: guardian.py config --undo", cfg)
                suggestion_for_review = review
            else:
                suggestion_for_review = suggestion
            if suggestion_for_review:
                (CONFIG_DIR / "suggested-config.json").write_text(json.dumps(suggestion_for_review, indent=2) + "\n")
        except json.JSONDecodeError:
            suggestion = None
    log_event("ask", result="ok", via=name, path=str(path), suggestion=suggestion)
    outcome.update(result="ok", via=name, path_name=path.name)
    if not quiet:
        print(answer)
        print(f"\n[saved to {path}]")
        if suggestion:
            print(f"[config suggestion saved to {CONFIG_DIR / 'suggested-config.json'}; "
                  f"review it, then: guardian.py config --apply-suggestion]")
    return path


# --------------------------------------------------------------------------
# Chrome tab hygiene (the one thing a watchdog can't see from outside)
# --------------------------------------------------------------------------

JXA_LIST = r'''
const app = Application("Google Chrome");
const out = [];
const wins = app.windows();
for (let wi = 0; wi < wins.length; wi++) {
  const tabs = wins[wi].tabs();
  for (let ti = 0; ti < tabs.length; ti++) {
    out.push({w: wi, t: ti, url: tabs[ti].url(), title: tabs[ti].title()});
  }
}
JSON.stringify(out);
'''

JXA_CLOSE = r'''
function run(argv) {
  const app = Application("Google Chrome");
  const targets = JSON.parse(argv[0]);
  targets.sort((a, b) => (b.w - a.w) || (b.t - a.t));
  let n = 0;
  for (const x of targets) { app.windows[x.w].tabs[x.t].close(); n++; }
  return String(n);
}
'''


def chrome_tabs(close_duplicates: bool = False, json_out: bool = False):
    if not IS_MAC:
        print("chrome: macOS only (uses Chrome's AppleScript interface)")
        return
    raw = sh(["osascript", "-l", "JavaScript", "-e", JXA_LIST], timeout=30)
    if not raw:
        print("chrome: could not talk to Google Chrome. Is it running? "
              "The first run asks for Automation permission (System Settings > Privacy & Security > Automation).")
        return
    tabs = json.loads(raw)
    by_win = defaultdict(int)
    for t in tabs:
        by_win[t["w"]] += 1
    seen = {}
    dups = []
    for t in tabs:
        u = t["url"].split("#")[0]
        if u in seen and not u.startswith(("chrome://", "about:")):
            dups.append(t)
        else:
            seen[u] = t
    if json_out:
        print(json.dumps({"windows": len(by_win), "tabs": len(tabs), "duplicates": dups}, indent=1))
    else:
        print(f"Chrome: {len(tabs)} tabs in {len(by_win)} windows; {len(dups)} duplicate tabs")
        for t in dups[:30]:
            print(f"  dup  w{t['w']} t{t['t']}  {t['title'][:60]}  {t['url'][:70]}")
    if close_duplicates and dups:
        n = sh(["osascript", "-l", "JavaScript", "-e", JXA_CLOSE,
                json.dumps([{"w": t["w"], "t": t["t"]} for t in dups])], timeout=60)
        log_event("chrome", closed_duplicates=int(n or 0), tabs_before=len(tabs))
        print(f"closed {n} duplicate tabs (they are all in History if you want one back)")


# --------------------------------------------------------------------------
# launchd install / uninstall / doctor
# --------------------------------------------------------------------------

def real_program(python: str) -> str:
    """The program that is actually running once `python` has started. Apple's
    /usr/bin/python3 is a launcher stub that re-executes a Python.app deep inside the Command
    Line Tools. macOS ties a background job's folder permissions to the program the job was
    STARTED as, so a job started through the stub is refused even after Python itself has
    been allowed. Measured on the first real Mac with one and the same grant: started as the
    stub, 'Operation not permitted' on Documents; started as the real program, allowed."""
    probe = ("import os,subprocess;print(subprocess.run(['ps','-o','comm=','-p',str(os.getpid())],"
             "capture_output=True,text=True).stdout.strip())")
    try:
        r = subprocess.run([python, "-c", probe], capture_output=True, text=True, timeout=30)
        real = r.stdout.strip()
        if r.returncode == 0 and real.startswith("/") and os.access(real, os.X_OK):
            return real
    except Exception:
        pass
    return python


def pick_python() -> str:
    """The interpreter launchd should run: Apple's python3 when it works (without the Command
    Line Tools it is only a stub that pops a dialog), else whatever python is running this
    install (Homebrew, uv, pyenv); in both cases resolved to the real program behind it."""
    choice = sys.executable or "/usr/bin/python3"
    if IS_MAC:
        try:
            r = subprocess.run(["/usr/bin/python3", "-c", "import sys; print(sys.version_info >= (3, 9))"],
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and r.stdout.strip() == "True":
                choice = "/usr/bin/python3"
        except Exception:
            pass
        return real_program(choice)
    return choice


def plist_text(script: Path, cfg: dict, python: str = None) -> str:
    python = python or pick_python()
    path_env = ":".join([str(HOME / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin",
                         "/usr/bin", "/bin", "/usr/sbin", "/sbin", str(HOME / ".npm-global/bin")])
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>{script}</string>
    <string>watch</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>Nice</key><integer>5</integer>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>{STDOUT_LOG}</string>
  <key>StandardErrorPath</key><string>{STDOUT_LOG}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>{path_env}</string>
    <key>HOME</key><string>{HOME}</string>
  </dict>
</dict>
</plist>
"""


def launchctl_domain() -> str:
    return f"gui/{os.getuid()}"


def install(cfg: dict, script: Path):
    if not IS_MAC:
        print("install: launchd is macOS only. On Linux run `guardian.py watch` under systemd --user or tmux.")
        return
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps({"mode": cfg["mode"]}, indent=2) + "\n")
        print(f"wrote {CONFIG_PATH} (mode={cfg['mode']}); every other key falls back to defaults")
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    python = pick_python()
    PLIST_PATH.write_text(plist_text(script.resolve(), cfg, python))
    print(f"agent will run {python} {script.resolve()} watch")
    sh(["launchctl", "bootout", launchctl_domain(), str(PLIST_PATH)])
    out = subprocess.run(["launchctl", "bootstrap", launchctl_domain(), str(PLIST_PATH)],
                         capture_output=True, text=True)
    if out.returncode != 0:
        print(f"launchctl bootstrap failed: {out.stderr.strip()}")
        print(f"try: launchctl bootout {launchctl_domain()} {PLIST_PATH}; launchctl bootstrap {launchctl_domain()} {PLIST_PATH}")
        return
    print(f"installed {LABEL}: starts at login, restarted if it dies, logs in {LOG_DIR}")
    print(f"status:  python3 {script} status      log: tail -f {EVENTS_PATH}")
    notify("Guardian", "Installed. I'll stay quiet until memory pressure actually rises.", cfg)


def uninstall():
    if IS_MAC and PLIST_PATH.exists():
        sh(["launchctl", "bootout", launchctl_domain(), str(PLIST_PATH)])
        PLIST_PATH.unlink()
        print(f"removed {LABEL}. Logs kept in {LOG_DIR}; config kept in {CONFIG_DIR}.")
    else:
        print("nothing installed")


def doctor(cfg: dict, script: Path):
    ok = lambda b: "OK " if b else "-- "
    print(f"guardian {VERSION} doctor on {HOSTNAME} ({'macOS' if IS_MAC else sys.platform})")
    print(f"{ok(sys.version_info >= (3, 9))} python {sys.version.split()[0]} at {sys.executable}")
    if IS_MAC:
        raw = read_mac_raw()
        lvl = raw["pressure"]
        print(f"{ok(lvl.isdigit())} kernel memory-pressure sysctl readable (level {lvl or '?'}, "
              f"memorystatus_level {raw['level'] or '?'}%)")
        sw = parse_mac_sample(raw, {})
        print(f"{ok(sw.get('swap_total_mb') is not None)} vm.swapusage parsed: {raw['swap'][:60] or '(empty)'}")
        print(f"{ok(sw.get('compressed_mb') is not None)} vm_stat compressor parsed: {sw.get('compressed_mb')}MB")
        has_limit = "CPU_Speed_Limit" in raw["therm"]
        print(f"{ok(has_limit or 'No thermal warning' in raw['therm'])} pmset -g therm: "
              f"{'CPU_Speed_Limit=' + str(sw.get('cpu_speed_limit')) if has_limit else 'no CPU_Speed_Limit line (normal on Apple silicon; assuming 100)'}")
        fp = phys_footprint_kb(os.getpid())
        print(f"{ok(fp)} per-process memory: "
              f"{'physical footprint via libproc (what Activity Monitor shows)' if fp else 'ps RSS only (reads low under pressure)'}")
        loaded = LABEL in sh(["launchctl", "list"])
        print(f"{ok(loaded)} launchd agent {LABEL} {'loaded' if loaded else 'not loaded (run: install)'}")
        if PLIST_PATH.exists():
            txt = PLIST_PATH.read_text()
            print(f"{ok(str(script.resolve()) in txt)} plist points at this script")
            m = re.search(r"<string>([^<]*[Pp]ython[^<]*)</string>", txt)
            print(f"{ok(m and Path(m.group(1)).exists())} plist python: {m.group(1) if m else '?'}")
            if m and Path(m.group(1)).exists() and real_program(m.group(1)) != m.group(1):
                print("--  the helper is started through a launcher stub; macOS will not honour folder "
                      "permissions for it. Fix: guardian.py install")
    print(f"{ok(CONFIG_PATH.exists())} config {CONFIG_PATH} ({'present' if CONFIG_PATH.exists() else 'defaults in use'}) "
          f"mode={cfg['mode']} autopilot={'on' if cfg.get('autopilot') else 'off'}")
    print(f"{ok(not PAUSE_PATH.exists())} {'PAUSED (run: resume)' if PAUSE_PATH.exists() else 'not paused'}")
    name, exe = find_ai_command(cfg)
    print(f"{ok(exe)} AI CLI for `ask`: {name + ' at ' + exe if exe else 'none found (claude or codex)'}")
    if IS_MAC:
        ops = MacAppOps()
        idle, front = ops.user_idle(), ops.front_app()
        print(f"{ok(idle is not None and front)} refresh signals: frontmost app {front or '?'}, "
              f"keyboard idle {'?' if idle is None else str(int(idle)) + 's'}; consent "
              + ", ".join(f"{a}={m}" for a, m in (cfg['refresh'].get('apps') or {}).items()))
    s = sample_system()
    if s.get("disk_free_gb") is not None and s.get("mem_total_mb"):
        enough = s["disk_free_gb"] * 1024 >= s["mem_total_mb"]
        print(f"{ok(enough)} disk free {s['disk_free_gb']}GB vs RAM {fmt_gb(s['mem_total_mb'])} "
              f"({'swap has room' if enough else 'free disk below RAM size: swap ceiling is low'})")
    print(f"{ok(s.get('cpu_speed_limit', 100) == 100)} thermal: cpu speed limit {s.get('cpu_speed_limit')}%")
    if IS_MAC:
        mds = sh(["mdutil", "-s", "/"])
        print(f"   spotlight: {mds.strip().splitlines()[-1] if mds else 'unknown'}")
        li = sh(["osascript", "-e", 'tell application "System Events" to get the name of every login item'])
        if li:
            items = [x.strip() for x in li.split(",") if x.strip()]
            print(f"   login items ({len(items)}): {', '.join(items)[:200]}")
    acc = next((e for e in reversed(read_events(24 * 14)) if e.get("kind") == "access"), None)
    if acc is None:
        print("-- background agent: no access check in its diary yet (it writes one when it starts)")
    elif acc["blocked"]:
        print(f"-- background agent CANNOT read {', '.join(acc['blocked'])} (its own check, {acc['ts']}); "
              "it measures them as unknown and cannot offer to move work folders")
        for line in access_help(acc.get("program") or ""):
            print("     " + line)
    else:
        print(f"OK  background agent can read {', '.join(acc['ok']) or 'your folders'} (its own check, {acc['ts']})")
    import archive
    acfg = cfg["archive"]
    good = [r for r in acfg["roots"] if not archive.root_problem(archive.resolve_root(r))]
    vols = archive.volumes()
    print(f"{ok(good and vols)} archive: {len(good)} of {len(acfg['roots'])} roots usable ({', '.join(acfg['roots'])}); drive "
          + (", ".join(f"{v['name']} ({v['free_mb'] / 1024:.0f} GB free)" for v in vols) or "none connected")
          + f"; offer {'on' if acfg['offer'] else 'off'}; "
          f"{len(archive.on_drive(archive.read_manifest(archive_manifest())))} folders on a drive")
    led = read_ledger(1)
    print(f"{ok(led)} disk ledger: {'last snapshot ' + led[-1]['ts'] if led else 'no snapshot yet (the agent takes one after start, then every ' + str(cfg['disk']['ledger_hours']) + 'h)'}")
    ev = read_events(24)
    last_ask = next((e for e in reversed(ev) if e["kind"] == "ask"), None)
    if last_ask:
        good = last_ask.get("result") == "ok"
        print(f"{ok(good)} last diagnosis attempt {last_ask['ts']}: {last_ask.get('result')}"
              f"{'' if good else ' (' + str(last_ask.get('reason') or 'see packet') + ')'}")
    print(f"   events last 24h: {len(ev)}   last start: "
          f"{next((e['ts'] for e in reversed(ev) if e['kind'] == 'start'), 'none')}")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def scratch_cmd(cfg: dict, args):
    import scratch
    running = running_apps(classify(list_processes(), cfg, os.getuid()))
    rows = scratch.census()
    snaps = scratch.local_snapshots()
    if args.json and not args.reclaim:
        print(json.dumps({"rows": rows, "snapshots": snaps, "running": sorted(running)}, indent=1))
        return
    if not args.reclaim:
        print(scratch.render(rows, snaps, sample_system().get("disk_free_gb"), running))
        return
    tiers = ["safe", "safe-old"] if args.reclaim == "all" else [args.reclaim]
    total = 0
    for tier in tiers:
        r = scratch.reclaim(tier, dry_run=not args.yes, running=running, rows=rows)
        total += r["freed_mb"]
        for it in r["items"]:
            print(f"  {'would free' if not args.yes else 'freed':10} {it['mb'] / 1024:6.2f}GB  {it['name']} ({it['entries']} entries)")
        for sk in r["skipped"]:
            print(f"  {'skipped':10}        -  {sk['name']}: {sk['why']}")
        log_event("scratch", tier=tier, dry_run=not args.yes, freed_mb=r["freed_mb"],
                  items=r["items"], skipped=r["skipped"])
    print(f"{'Would free' if not args.yes else 'Freed'} {total / 1024:.1f}GB total."
          + ("  Add --yes to do it." if not args.yes else ""))


AUTOPILOT_TEXT = """Autopilot is ON. Always running (launchd restarts it if it dies). What it does on its own:
  - closes automation browsers and MCP servers whose owner has gone away, after 10 idle minutes
  - slows down (renices) any non-app process pinning a CPU core for 10 minutes
  - at critical memory pressure, closes oversized local model workers and dev servers
  - clears rebuildable caches when the disk gets low, and once a day tidies old logs and trash
  - after a bad day (3+ pressure episodes) asks Claude/Codex for a diagnosis and applies the
    threshold tuning it suggests, within fixed ranges; everything else waits for you
  - stays quiet while you present or are in a Zoom meeting
  - keeps a ledger of what the disk is spent on, tells you when free space falls fast and what
    grew, and clears an app's caches when it quits while the disk is tight. See: guardian.py disk
  - when an AI app listed under `refresh` (ChatGPT by default) is bloated and its agent idle,
    asks whether to refresh it: quit cleanly, clear its caches, reopen. See: guardian.py refresh
  - when the disk is tight and an external drive is connected, asks whether to move work
    folders nobody has used for a month to it (copy, check the copy, then remove here). It
    never does this unasked. See: guardian.py archive
What it never does: close an app you can see without your say-so, interrupt a running agent
task, delete your transcripts, sessions, downloads or anything outside rebuildable caches,
or act while paused.
Watch it:  guardian.py report      Undo a tuning:  guardian.py config --undo      Off:  guardian.py autopilot off
"""


def autopilot_cmd(cfg: dict, args, script: Path):
    if args.state == "on":
        apply_config_change({"mode": "act", "autopilot": True, "ai": {"auto_apply_tuning": True}}, "autopilot on")
        if IS_MAC and LABEL not in sh(["launchctl", "list"]):
            install(load_config(), script)
        print(AUTOPILOT_TEXT)
    elif args.state == "off":
        apply_config_change({"mode": "nudge", "autopilot": False, "ai": {"auto_apply_tuning": False}}, "autopilot off")
        print("Autopilot OFF: still watching and notifying (nudge mode), no actions. `guardian.py uninstall` stops it entirely.")
    else:
        ev = read_events(48)
        hyg = next((e for e in reversed(ev) if e["kind"] == "hygiene"), None)
        tune = next((e for e in reversed(ev) if e["kind"] == "config" and "auto-tuning" in str(e.get("why", ""))), None)
        loaded = (LABEL in sh(["launchctl", "list"])) if IS_MAC else None
        print(f"autopilot: {'ON' if cfg.get('autopilot') else 'off'}   mode={cfg['mode']}   "
              f"agent loaded: {loaded}   paused: {PAUSE_PATH.exists()}")
        print(f"  last hygiene: {hyg['ts'] + ' freed ' + str(round(hyg['freed_mb'] / 1024, 1)) + 'GB' if hyg else 'never'}")
        print(f"  last self-tuning: {tune['ts'] + ' ' + json.dumps(tune['changes']) if tune else 'never'}")
        print("  " + digest_oneliner(24))


def config_cmd(cfg: dict, args):
    if args.undo:
        last = undo_config_change()
        print(f"undid {json.dumps(last['changes'])} ({last['why']}, {last['ts']})" if last else "nothing to undo")
        return
    if args.apply_suggestion:
        sp = CONFIG_DIR / "suggested-config.json"
        if not sp.exists():
            print("no suggestion on file; run `ask` first")
            return
        sug = json.loads(sp.read_text())
        current = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
        apply_config_change(sug, "applied suggestion by hand")
        sp.rename(sp.with_suffix(f".applied-{datetime.now():%Y%m%d-%H%M}.json"))
        print(f"applied {json.dumps(sug)} to {CONFIG_PATH} (the running agent picks it up within a minute)")
        _ = current
        return
    if args.set:
        current = {}
        for kv in args.set:
            k, _, v = kv.partition("=")
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                pass
            node = current
            keys = k.split(".")
            for part in keys[:-1]:
                node = node.setdefault(part, {})
            node[keys[-1]] = v
        apply_config_change(current, f"config --set {' '.join(args.set)}")
        print(f"updated {CONFIG_PATH} (the running agent picks it up within a minute)")
        return
    print(json.dumps(cfg, indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="guardian", description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", default=str(CONFIG_PATH), help="config file (default ~/.config/guardian/config.json)")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("status", help="pressure, top apps, what guardian is tracking")
    p.add_argument("-n", type=int, default=12)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("watch", help="run the loop (what launchd runs)")
    p.add_argument("--once", action="store_true", help="one sample, print decisions, exit")
    p.add_argument("--dry-run", action="store_true", help="never kill or renice, only log what would happen")
    p.add_argument("--simulate", metavar="level=4,free=3,disk=9", help="override readings to exercise the policy")
    p = sub.add_parser("ask", help="have Claude Code / Codex diagnose the diary")
    p.add_argument("--hours", type=float, default=24)
    p = sub.add_parser("report", help="summary of the last N hours")
    p.add_argument("--hours", type=float, default=24)
    p.add_argument("--write", action="store_true", help="also write a digest file")
    p = sub.add_parser("chrome", help="tab census; --close-duplicates closes duplicate URLs")
    p.add_argument("--close-duplicates", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("scratch", help="disk census of app data folders; --reclaim safe|safe-old|all [--yes]")
    p.add_argument("--reclaim", choices=["safe", "safe-old", "all"])
    p.add_argument("--yes", action="store_true", help="actually delete (default is a dry run)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("refresh", help="quit, clean and reopen a bloated AI app while it is idle (no flags: show the verdict)")
    p.add_argument("app", nargs="?")
    p.add_argument("--now", action="store_true", help="do it now, unless its agent is working")
    p.add_argument("--force", action="store_true", help="with --now: even if its agent looks busy")
    p.add_argument("--mode", choices=["ask", "auto", "never"], help="set the consent for this app")
    p = sub.add_parser("disk", help="free space, where it went, what guardian gets back, what is yours to decide")
    p.add_argument("--snapshot", action="store_true", help="measure everything now (a minute or two) and compare")
    p.add_argument("--big", nargs="?", type=int, const=15, default=None, metavar="N",
                   help="list the N biggest items in Downloads, Documents and Desktop")
    p.add_argument("--in", dest="inside", metavar="FOLDER", help="with --big: look inside this folder instead")
    p = sub.add_parser("archive", help="move work folders unused for a month to an external drive (no flags: dry run)")
    p.add_argument("--yes", action="store_true", help="copy, check each copy, then remove the folders here")
    p.add_argument("--older-than", type=int, metavar="DAYS", help="unused for at least this many days (default 30)")
    p.add_argument("--to", metavar="DRIVE", help="drive name, or a folder on it (default: the drive with most room)")
    p.add_argument("--only", nargs="+", metavar="NAME", help="just these folders")
    p.add_argument("--root", nargs="+", metavar="FOLDER",
                   help="for this run, offer the folders inside FOLDER instead of the configured roots")
    p.add_argument("--list", action="store_true", help="what is on a drive now")
    p.add_argument("--restore", metavar="NAME", help="bring one folder back (the drive keeps its copy)")
    p.add_argument("--offer", choices=["on", "off"], help="whether guardian asks on its own")
    p.add_argument("--announce", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("doctor", help="check the install")
    sub.add_parser("install", help="install the launchd agent (starts at login)")
    sub.add_parser("uninstall", help="remove the launchd agent")
    sub.add_parser("pause", help="hold all notifications and actions (e.g. before a talk)")
    sub.add_parser("resume")
    sub.add_parser("test-notify", help="send one notification to check permissions")
    p = sub.add_parser("config", help="show config; --set key=value; --apply-suggestion; --undo")
    p.add_argument("--set", nargs="*", metavar="KEY=VALUE")
    p.add_argument("--apply-suggestion", action="store_true")
    p.add_argument("--undo", action="store_true", help="revert the last config change (tuning or --set)")
    p = sub.add_parser("autopilot", help="on | off | status: always running and optimizing on its own")
    p.add_argument("state", nargs="?", choices=["on", "off", "status"], default="status")
    args = ap.parse_args(argv)
    cfg = load_config(Path(args.config))
    script = Path(__file__)

    if args.cmd in (None, "status"):
        snap = snapshot(cfg)
        if args.cmd == "status" and args.json:
            print(json.dumps({"sample": snap["sample"], "classes": snap["classes"],
                              "top": snap["groups"][:args.n], "quiet": snap["quiet"]}, indent=1, default=str))
        else:
            print_status(cfg, snap, getattr(args, "n", 12))
    elif args.cmd == "watch":
        if args.simulate and not args.dry_run and cfg["mode"] == "act":
            print("refusing to simulate in act mode without --dry-run (a real kill could follow a fake reading)")
            return
        watch(cfg, once=args.once, dry_run=args.dry_run, simulate=parse_simulate(args.simulate))
    elif args.cmd == "ask":
        ask(cfg, hours=args.hours)
    elif args.cmd == "report":
        print(render_report(args.hours))
        if args.write:
            print(f"[written to {write_digest(cfg, args.hours)}]")
    elif args.cmd == "chrome":
        chrome_tabs(close_duplicates=args.close_duplicates, json_out=args.json)
    elif args.cmd == "scratch":
        scratch_cmd(cfg, args)
    elif args.cmd == "refresh":
        refresh_cmd(cfg, args)
    elif args.cmd == "disk":
        disk_cmd(cfg, args)
    elif args.cmd == "archive":
        archive_cmd(cfg, args)
    elif args.cmd == "doctor":
        doctor(cfg, script)
    elif args.cmd == "install":
        install(cfg, script)
    elif args.cmd == "uninstall":
        uninstall()
    elif args.cmd == "pause":
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        PAUSE_PATH.write_text(datetime.now().isoformat())
        log_event("pause")
        print("paused: no notifications, no actions until `resume`")
    elif args.cmd == "resume":
        if PAUSE_PATH.exists():
            PAUSE_PATH.unlink()
        log_event("resume")
        print("resumed")
    elif args.cmd == "test-notify":
        notify("Guardian", "Notifications work. I'll only speak up when memory pressure rises.", cfg)
        print("sent (if nothing appeared: System Settings > Notifications > Script Editor / osascript)")
    elif args.cmd == "config":
        config_cmd(cfg, args)
    elif args.cmd == "autopilot":
        autopilot_cmd(cfg, args, script)


if __name__ == "__main__":
    main()
