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

Subcommands:  status  watch  ask  report  chrome  doctor  install  uninstall
              pause  resume  config  test-notify

Prior art this borrows from, with thanks:
  TomGranot/mac-memory-guard   kernel pressure level as the only trigger
  trentshaines/oomguard        leaky strike counters, "a job is a process group"
  deltartificial/jager         fast lane for agent-driven browsers, stale lane
  IgorGanapolsky/mac-yolo-safeguards   "never touch GUI apps", orphan Chrome
  kylebrodeur/mac-optimize     disk free is your swap ceiling
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections import defaultdict
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
NOT_GUI_BUNDLES = {"Python", "Python3", "Python Launcher"}


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


def list_processes() -> list:
    """All processes, via ps. Two calls because comm can contain spaces."""
    comm_out = subprocess.run(ps_command("pid=,comm="), capture_output=True, text=True).stdout
    main_out = subprocess.run(ps_command(PS_MAIN_COLS), capture_output=True, text=True).stdout
    return parse_ps(comm_out, main_out)


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
        is_renderer = any(mark in p.comm for mark in rn)
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
        if owner and not p.is_gui:
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


def apply_decisions(decisions: list, cfg: dict, quiet: str = "", dry_run: bool = False,
                    simulated: bool = False, running: set = frozenset()) -> list:
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
    log_event("start", version=VERSION, mode=cfg["mode"], interval=cfg["interval_seconds"], dry_run=dry_run)
    snap = snapshot(cfg)
    s = snap["sample"]
    if s.get("disk_free_gb") is not None and s.get("mem_total_mb") and \
            s["disk_free_gb"] * 1024 < s["mem_total_mb"]:
        log_event("health", note=f"disk free {s['disk_free_gb']}GB is below RAM size; swap ceiling is low")
    last_digest_day = None
    ai_runs_today = 0
    ai_day = None
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
                                      simulated=bool(simulate), running=running_apps(snap["procs"]))
            if once:
                for a in applied:
                    print(json.dumps(a, default=str))
                break
            today = datetime.now().date()
            if ai_day != today:
                ai_day, ai_runs_today = today, 0
            # AI diagnosis after a bad day, at most N times a day
            if engine.episodes_today >= cfg["ai"]["auto_after_episodes"] and \
                    ai_runs_today < cfg["ai"]["max_runs_per_day"] and engine.episode is None:
                ai_runs_today += 1
                path = ask(cfg, hours=24, quiet=True)
                if path:
                    notify("Guardian", f"{engine.episodes_today} pressure episodes today. Diagnosis written to {path.name}", cfg)
            # Proactive hygiene (autopilot / act mode only): old logs and trash daily, safe
            # caches when they are big or the disk is tight. Nothing in the review tier, ever.
            now = datetime.now()
            if cfg["mode"] == "act" and not snap["quiet"] and hygiene_due(now, last_hygiene, cfg, up_since):
                last_hygiene = now.timestamp()
                h = run_hygiene(cfg, snap["sample"], running_apps(snap["procs"]), dry_run=dry_run)
                log_event("hygiene", **h)
                if h["freed_mb"] >= 256:
                    notify("Guardian", f"Tidied up: freed {h['freed_mb'] / 1024:.1f}GB of caches and old logs.", cfg)
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


def ask(cfg: dict, hours: float = 24, quiet: bool = False):
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
        return None
    if name == "claude":
        cmd = [exe, "-p", prompt, "--output-format", "text"]
    else:
        cmd = [exe, "exec", "--skip-git-repo-check", prompt]
    try:
        env = dict(os.environ)
        env.pop("CLAUDECODE", None)          # allow running from inside a Claude Code session
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=cfg["ai"]["timeout_seconds"], env=env, cwd=str(HOME))
        answer = out.stdout.strip() or out.stderr.strip()
    except subprocess.TimeoutExpired:
        answer = f"({name} timed out after {cfg['ai']['timeout_seconds']}s)"
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

def pick_python() -> str:
    """The interpreter launchd should run. Apple's /usr/bin/python3 is the stable path, but
    without the Command Line Tools it is only a stub that pops a dialog; so probe it, and fall
    back to whatever python is running this install (Homebrew, uv, pyenv)."""
    if IS_MAC:
        try:
            r = subprocess.run(["/usr/bin/python3", "-c", "import sys; print(sys.version_info >= (3, 9))"],
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and r.stdout.strip() == "True":
                return "/usr/bin/python3"
        except Exception:
            pass
    return sys.executable or "/usr/bin/python3"


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
        print(f"{ok('CPU_Speed_Limit' in raw['therm'])} pmset -g therm: "
              f"{'CPU_Speed_Limit=' + str(sw.get('cpu_speed_limit')) if 'CPU_Speed_Limit' in raw['therm'] else 'no CPU_Speed_Limit line (assuming 100)'}")
        loaded = LABEL in sh(["launchctl", "list"])
        print(f"{ok(loaded)} launchd agent {LABEL} {'loaded' if loaded else 'not loaded (run: install)'}")
        if PLIST_PATH.exists():
            txt = PLIST_PATH.read_text()
            print(f"{ok(str(script.resolve()) in txt)} plist points at this script")
            m = re.search(r"<string>([^<]*python[^<]*)</string>", txt)
            print(f"{ok(m and Path(m.group(1)).exists())} plist python: {m.group(1) if m else '?'}")
    print(f"{ok(CONFIG_PATH.exists())} config {CONFIG_PATH} ({'present' if CONFIG_PATH.exists() else 'defaults in use'}) "
          f"mode={cfg['mode']} autopilot={'on' if cfg.get('autopilot') else 'off'}")
    print(f"{ok(not PAUSE_PATH.exists())} {'PAUSED (run: resume)' if PAUSE_PATH.exists() else 'not paused'}")
    name, exe = find_ai_command(cfg)
    print(f"{ok(exe)} AI CLI for `ask`: {name + ' at ' + exe if exe else 'none found (claude or codex)'}")
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
    ev = read_events(24)
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
What it never does: close an app you can see, delete your transcripts, sessions, downloads
or anything outside rebuildable caches, or act while paused.
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
