"""
scratch -- the disk side of guardian.

macOS uses free disk as swap. When the folders that AI apps, Chrome and dev tools
scribble into fill the disk, there is nowhere for memory to spill and the Mac
freezes instead of slowing down. This module measures those folders, sorts them
into tiers, and reclaims the tiers that are safe by construction.

Tiers
  safe      rebuildable caches. Deleting them costs a slower first launch, nothing else.
            Reclaimed automatically in act mode when disk drops below the floor.
  safe-old  logs, snapshots, trash: delete only entries older than N days
            ("older:N" judges top-level entries, "older-files:N" judges every file
            and leaves the folders in place, which is what app log folders need).
  review    your data or expensive-to-rebuild binaries (session transcripts, iOS
            backups, pinned browsers). Measured and explained, never auto-deleted.
  report    measured for the picture; nothing to reclaim here.

Everything stays under $HOME, symlinks are never followed, dry-run is the default.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

IS_MAC = sys.platform == "darwin"

# name, globs (relative to home), tier, what it is, method, app(s) that must not be running
# (paths and names below were checked against a real Mac on 2026-11-10: Claude desktop 2.x,
# the ChatGPT app that embeds Codex, Claude Code native install)
LOCATIONS = [
    ("Chrome caches",
     ["Library/Caches/Google/Chrome", "Library/Caches/Google/Chrome Canary",
      "Library/Application Support/Google/Chrome/*/Cache",
      "Library/Application Support/Google/Chrome/*/Code Cache",
      "Library/Application Support/Google/Chrome/*/GPUCache",
      "Library/Application Support/Google/Chrome/*/DawnCache",
      "Library/Application Support/Google/Chrome/*/DawnWebGPUCache",
      "Library/Application Support/Google/Chrome/*/DawnGraphiteCache",
      "Library/Application Support/Google/Chrome/*/Service Worker/CacheStorage",
      "Library/Application Support/Google/Chrome/*/Service Worker/ScriptCache",
      "Library/Application Support/Google/Chrome/GrShaderCache",
      "Library/Application Support/Google/Chrome/ShaderCache",
      "Library/Application Support/Google/Chrome/GraphiteDawnCache",
      "Library/Application Support/Google/Chrome/component_crx_cache"],
     "safe", "page, script and GPU caches; Chrome rebuilds them as you browse", "clear", "Google Chrome"),
    ("Claude desktop caches",
     ["Library/Application Support/Claude/Cache", "Library/Application Support/Claude/Code Cache",
      "Library/Application Support/Claude/GPUCache", "Library/Application Support/Claude/DawnCache",
      "Library/Application Support/Claude/DawnWebGPUCache",
      "Library/Application Support/Claude/DawnGraphiteCache",
      "Library/Application Support/Claude/Service Worker/CacheStorage",
      "Library/Application Support/Claude/GraphiteDawnCache",
      "Library/Application Support/Claude/GPUPersistentCache",
      "Library/Caches/Claude", "Library/Caches/com.anthropic.claudefordesktop",
      "Library/Caches/com.anthropic.claudefordesktop.ShipIt"],
     "safe", "Electron caches of the Claude desktop app", "clear", "Claude"),
    ("Cowork sessions / VM",
     ["Library/Application Support/Claude/local-agent-mode-sessions",
      "Library/Application Support/Claude/cowork*", "Library/Application Support/Claude/vm*",
      "Library/Application Support/Claude/claude-code-vm",
      "Library/Application Support/Claude/claude-code-sessions",
      "Library/Application Support/Claude/scratch-workspaces",
      "Library/Application Support/Claude/sessions"],
     "report", "Cowork VM bundle (vm_bundles), Claude Code VM and session data inside the Claude app folder; "
               "never reclaimed", None, None),
    ("Claude desktop data",
     ["Library/Application Support/Claude"],
     "report", "settings, local MCP state, Cowork session data; the caches above are the reclaimable part", None, None),
    ("Claude Code transcripts",
     [".claude/projects", ".claude/sessions"],
     "review", "every Claude Code conversation as JSONL; this is your history, prune old ones only with a backup", None, None),
    ("Claude Code scratch",
     [".claude/shell-snapshots", ".claude/debug", ".claude/statsig", ".claude/file-history",
      ".claude/todos", ".claude/session-env"],
     "safe-old", "shell snapshots, debug logs, todo lists older than 14 days", "older:14", None),
    ("Claude Code other data",
     [".claude/plans", ".claude/backups", ".claude/downloads", ".claude/ide", ".claude/plugins", ".claude/cache"],
     "report", "plans, settings backups, native-install downloads, plugin caches", None, None),
    ("Codex sessions",
     [".codex/sessions", ".codex/archived_sessions", ".codex/history.jsonl", ".codex/memories",
      ".codex/memories_v2", ".codex/*.sqlite", ".codex/*.sqlite-wal"],
     "review", "Codex session logs and thread-history database (10GB+ is normal); back up before pruning",
     None, None),
    ("Codex logs",
     [".codex/log", ".codex/logs"],
     "safe-old", "Codex CLI logs older than 14 days", "older-files:14", None),
    ("Codex app caches",
     ["Library/Caches/com.openai.codex", "Library/Caches/Codex"],
     "safe", "Codex updater (Sparkle) downloads and the Codex desktop UI's page caches", "clear",
     ["Codex", "ChatGPT"]),
    ("Codex app data",
     ["Library/Application Support/Codex", "Library/Application Support/com.openai.codex",
      "Library/Application Support/OpenAI", ".codex/sqlite", ".codex/plugins", ".codex/cache",
      ".codex/computer-use", ".codex/generated_images"],
     "report", "Codex desktop app state (the ChatGPT app embeds Codex), plugins, computer-use service", None, None),
    ("ChatGPT desktop caches",
     ["Library/Caches/com.openai.chat", "Library/Caches/com.openai.atlas",
      "Library/Containers/com.openai.chat/Data/Library/Caches",
      "Library/Containers/com.openai.atlas/Data/Library/Caches"],
     "safe", "ChatGPT desktop app caches", "clear", "ChatGPT"),
    ("ChatGPT desktop data",
     ["Library/Application Support/com.openai.chat", "Library/Application Support/com.openai.atlas",
      "Library/Containers/com.openai.chat/Data/Library/Application Support",
      "Library/Containers/com.openai.atlas/Data/Library/Application Support"],
     "report", "ChatGPT app state", None, None),
    ("Dropbox cache",
     ["Library/CloudStorage/Dropbox/.dropbox.cache", "Dropbox/.dropbox.cache",
      "Library/Caches/com.getdropbox.dropbox", "Library/Caches/com.dropbox.DropboxMacUpdate"],
     "safe", "Dropbox's staging area for syncs; it refills as needed", "clear", "Dropbox"),
    ("npm cache", [".npm/_cacache"], "safe", "downloaded packages; npm re-downloads on demand", "clear", None),
    ("pip cache", ["Library/Caches/pip", ".cache/pip"], "safe", "downloaded wheels", "clear", None),
    ("Homebrew cache", ["Library/Caches/Homebrew"], "safe", "downloaded bottles; `brew cleanup` territory", "clear", None),
    ("uv / pnpm / yarn caches",
     [".cache/uv", "Library/Caches/uv", "Library/pnpm/store", "Library/Caches/pnpm", "Library/Caches/Yarn"],
     "safe", "package manager stores", "clear", None),
    ("Playwright / Puppeteer browsers",
     ["Library/Caches/ms-playwright", ".cache/puppeteer"],
     "review", "pinned browser binaries for agent automation; ~500MB each to re-download", None, None),
    ("Other app caches",
     ["Library/Caches"],
     "report", "everything under ~/Library/Caches not named above", None, None),
    ("Logs", ["Library/Logs"], "safe-old", "log files older than 30 days (folders stay)", "older-files:30", None),
    ("Trash", [".Trash"], "safe-old", "items in the Trash older than 30 days", "older:30", None),
    ("Downloads", ["Downloads"], "report", "yours to sort; often the biggest folder", None, None),
    ("Documents", ["Documents"], "report", "your documents", None, None),
    ("Desktop", ["Desktop"], "report", "files on the Desktop", None, None),
    ("Movies, Music, Pictures", ["Movies", "Music", "Pictures"], "report", "media libraries", None, None),
    ("Mail and Messages", ["Library/Mail", "Library/Messages"], "report", "mail and message stores", None, None),
    ("App containers", ["Library/Containers", "Library/Group Containers"],
     "report", "sandboxed apps' data not named above", None, None),
    ("Other Application Support", ["Library/Application Support"],
     "report", "app data not named above", None, None),
    ("iOS device backups",
     ["Library/Application Support/MobileSync/Backup"],
     "review", "iPhone/iPad backups; delete from Finder > device > Manage Backups", None, None),
    ("Xcode DerivedData",
     ["Library/Developer/Xcode/DerivedData", "Library/Developer/Xcode/iOS DeviceSupport",
      "Library/Developer/CoreSimulator/Caches"],
     "review", "build products and simulator caches; rebuild on next build", None, None),
    ("Docker / OrbStack images",
     ["Library/Containers/com.docker.docker/Data/vms", ".orbstack/data", "OrbStack"],
     "review", "VM disk images; prune from the app", None, None),
]

TIER_ORDER = {"safe": 0, "safe-old": 1, "review": 2, "report": 3}

# Rows that mean "this folder minus everything named elsewhere", so that no byte is counted
# twice and the rows can be added up and compared with the change in free space.
REMAINDER = {"Other app caches", "Claude desktop data", "Other Application Support", "App containers"}


def du_kb(path: Path) -> int:
    """Size in KB without following symlinks. Uses du when present (fast), else walks."""
    if shutil.which("du"):
        try:
            out = subprocess.run(["du", "-sk", str(path)], capture_output=True, text=True, timeout=600).stdout
            return int(out.split()[0]) if out.strip() else 0
        except Exception:
            pass
    total = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total // 1024


def readable(path) -> bool:
    """Can this folder be listed? macOS privacy protection (Documents, Downloads, Desktop,
    removable drives) refuses a background program until the owner allows it, and `du` then
    reports 0. On the first real Mac the agent's ledger read Documents as 0 GB; it held 41."""
    try:
        os.scandir(path).close()
        return True
    except NotADirectoryError:
        return True
    except OSError:
        return False


def expand(home: Path, pattern: str) -> list:
    if any(ch in pattern for ch in "*?["):
        return [p for p in home.glob(pattern) if p.exists() and not p.is_symlink()]
    p = home / pattern
    return [p] if p.exists() and not p.is_symlink() else []


def census(home: Path = None, only_app: str = None) -> list:
    """Measure every known location. Returns rows sorted biggest first.
    With only_app, measure just the rows guarded by that app (its caches): seconds, not minutes,
    which matters when the app is closed and waiting to be reopened."""
    home = home or Path.home()
    memo = {}

    def du(p: Path) -> int:
        if p not in memo:
            memo[p] = du_kb(p)
        return memo[p]

    found = []
    for name, globs, tier, what, method, app in LOCATIONS:
        if only_app and only_app not in ([app] if isinstance(app, str) else (app or [])):
            continue
        paths = []
        for g in globs:
            paths += expand(home, g)
        found.append((name, tier, what, method, app, paths))
    rows = []
    for name, tier, what, method, app, paths in found:
        kb = sum(du(p) for p in paths)
        if name in REMAINDER:
            inside = {q for other in found if other[0] != name for q in other[5]
                      if any(p in q.parents for p in paths)}
            outermost = [q for q in inside if not any(r in q.parents for r in inside)]
            kb = max(0, kb - sum(du(q) for q in outermost))
        rows.append({"name": name, "tier": tier, "what": what, "method": method, "app": app,
                     "paths": [str(p) for p in paths], "mb": kb // 1024,
                     "unreadable": any(not readable(p) for p in paths)})
    rows.sort(key=lambda r: (-r["mb"], TIER_ORDER[r["tier"]]))
    return rows


def guard_apps() -> set:
    """Every app whose running state guards a cache row."""
    out = set()
    for _name, _globs, _tier, _what, _method, app in LOCATIONS:
        out.update([app] if isinstance(app, str) else (app or []))
    return out


# --------------------------------------------------------------------------
# The ledger: what the free space was spent on
# --------------------------------------------------------------------------
# First real Mac: free disk fell 8 GB in two hours while every folder guardian measured
# grew 0.1 GB. The space had gone to the per-user temp folder under /var/folders (leftover
# test fixtures). The ledger measures the places outside the home folder too, and says how
# much of a change it cannot explain.

def user_temp_dir():
    """macOS per-user temp folder (/var/folders/xx/yyyy/T), which is not $TMPDIR-dependent."""
    try:
        t = os.confstr(65537)          # _CS_DARWIN_USER_TEMP_DIR; Python has no name for it
        if t:
            return Path(t)
    except (ValueError, OSError, AttributeError):
        pass
    import tempfile
    t = tempfile.gettempdir()
    return Path(t) if "/var/folders/" in t else None


def system_buckets(temp_dir: Path = None, vm_dir: Path = Path("/System/Volumes/VM")) -> list:
    """Space users on the same disk that live outside the home folder. Measured, never touched."""
    if not IS_MAC and temp_dir is None:
        return []
    out = []

    def add(name: str, what: str, paths: list):
        kb = sum(du_kb(Path(p)) for p in paths if p and Path(p).exists())
        out.append({"name": name, "what": what, "mb": kb // 1024})

    add("Temporary files", "scratch space of apps, agents and test runs; macOS clears what is 3 days old",
        [temp_dir or user_temp_dir()])
    swap = 0
    try:
        for e in os.scandir(vm_dir):
            if e.is_file(follow_symlinks=False):
                swap += e.stat(follow_symlinks=False).st_size
    except OSError:
        pass
    out.append({"name": "Swap files", "what": "memory that did not fit in RAM; shrinks when apps are closed",
                "mb": swap // (1024 * 1024)})
    if IS_MAC:
        add("Applications", "installed apps; they grow when they update", ["/Applications"])
        add("Apple downloads", "on-device models and macOS updates",
            ["/System/Library/AssetsV2", "/Library/Updates"])
        add("System logs", "diagnostic logs kept by macOS", ["/private/var/db/diagnostics", "/private/var/db/uuidtext"])
    return out


def entry_access(entry: dict) -> str:
    """'full' or 'limited': how much of the disk this snapshot was allowed to read. A program
    without Full Disk Access under-reads Mail, Messages, Photos and other apps' containers."""
    return entry.get("access") or ("limited" if entry.get("unreadable") else "full")


def comparable(a: dict, b: dict) -> bool:
    """Two snapshots can be compared only if both saw the same amount of the disk. The first
    real Mac's helper got Full Disk Access at midday; the next snapshot 'found' 14 GB of
    pictures and 8 GB of app containers that had been there all along, and the alert said
    they had grown."""
    return entry_access(a) == entry_access(b)


def ledger_entry(rows: list, buckets: list, free_gb, ts: float, access: str = None) -> dict:
    """One ledger line. A place that could not be read is listed under 'unreadable' and left
    out of 'items': unknown is not zero."""
    items = {r["name"]: r["mb"] for r in rows if not r.get("unreadable")}
    items.update({b["name"]: b["mb"] for b in buckets})
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts)), "free_gb": free_gb, "items": items}
    blind = sorted(r["name"] for r in rows if r.get("unreadable"))
    if blind:
        entry["unreadable"] = blind
    if access:
        entry["access"] = access
    return entry


def ledger_diff(old: dict, new: dict) -> dict:
    """What changed between two ledger entries. 'unexplained_mb' is the part of the change in
    free space that no measured place accounts for (positive: space went somewhere unseen)."""
    if not comparable(old, new):
        return {"from": old["ts"], "to": new["ts"], "used_mb": None, "changes": [], "unexplained_mb": None,
                "unreadable": [], "incomparable": True}
    names = set(old["items"]) & set(new["items"])      # only what both snapshots really measured
    blind = sorted((set(old["items"]) ^ set(new["items"])) | set(old.get("unreadable", []))
                   | set(new.get("unreadable", [])))
    changes = [(n, new["items"][n] - old["items"][n]) for n in names]
    changes = sorted((c for c in changes if c[1]), key=lambda c: -abs(c[1]))
    used_mb = None
    if old.get("free_gb") is not None and new.get("free_gb") is not None:
        used_mb = round((old["free_gb"] - new["free_gb"]) * 1e9 / (1024 * 1024))
    unexplained = None if used_mb is None else used_mb - sum(mb for _, mb in changes)
    return {"from": old["ts"], "to": new["ts"], "used_mb": used_mb, "changes": changes,
            "unexplained_mb": unexplained, "unreadable": blind}


def render_ledger_diff(diff: dict, min_mb: int = 100, top: int = 8) -> list:
    sign = lambda mb: f"{'+' if mb >= 0 else '-'}{abs(mb) / 1024:.1f} GB"
    used = diff["used_mb"]
    head = f"since {diff['from'][5:16].replace('T', ' ')}: " + (
        "free space unknown" if used is None else
        f"free space {'fell' if used > 0 else 'rose'} {abs(used) / 1024:.1f} GB")
    lines = [head]
    if diff.get("incomparable"):
        return [f"since {diff['from'][5:16].replace('T', ' ')}: not compared. One of the two snapshots was taken "
                "without permission to read every folder, so what looks like growth was only hidden before."]
    shown = [c for c in diff["changes"] if abs(c[1]) >= min_mb][:top]
    for name, mb in shown:
        lines.append(f"    {sign(mb):>9}  {name}")
    if not shown:
        lines.append("    nothing measured changed by more than 0.1 GB")
    un = diff["unexplained_mb"]
    if un is not None and abs(un) >= max(min_mb, 300):
        lines.append(f"    {sign(un):>9}  not explained by anything measured")
    if diff.get("unreadable"):
        lines.append("    not compared (one of the two snapshots could not read them): "
                     + ", ".join(diff["unreadable"]))
    return lines


def local_snapshots() -> list:
    """Time Machine local snapshots hold 'purgeable' space that still blocks swap growth."""
    if not IS_MAC or not shutil.which("tmutil"):
        return []
    try:
        out = subprocess.run(["tmutil", "listlocalsnapshots", "/"], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return []
    return parse_local_snapshots(out)


def parse_local_snapshots(text: str) -> list:
    """'Snapshots for disk /:' header then one 'com.apple.TimeMachine.2026-11-09-120000.local' per line."""
    return [line.strip() for line in text.splitlines() if "com.apple.TimeMachine" in line]


def blocked_by(row: dict, running: set):
    """The running app that makes this row unsafe to touch right now, or None.
    A row's app may be one name or a list (the Codex caches belong to Codex.app and to the
    ChatGPT app that embeds it)."""
    apps = row.get("app")
    if not apps:
        return None
    for a in ([apps] if isinstance(apps, str) else apps):
        if a in running:
            return a
    return None


def reclaimable_mb(rows: list, tiers=("safe", "safe-old"), running: set = frozenset()) -> int:
    return sum(r["mb"] for r in rows if r["tier"] in tiers and not blocked_by(r, running))


def _older_than(path: Path, days: int) -> bool:
    try:
        return path.lstat().st_mtime < time.time() - days * 86400
    except OSError:
        return False


def _delete_entry(p: Path, dry_run: bool) -> int:
    """Delete one directory entry (file, symlink, or tree). Returns KB freed (estimated)."""
    kb = du_kb(p) if p.is_dir() and not p.is_symlink() else max(1, p.lstat().st_size // 1024)
    if not dry_run:
        try:
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink()
        except OSError:
            return 0
    return kb


def _reclaim_old_files(p: Path, days: int, dry_run: bool):
    """Delete files older than N days anywhere under p; never follow symlinks, keep every folder
    (apps assume their log folder exists). Returns (KB freed, files)."""
    freed_kb = n = 0
    for root, dirs, files in os.walk(p, followlinks=False):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for f in files:
            fp = Path(root) / f
            if fp.is_symlink() or not _older_than(fp, days):
                continue
            freed_kb += _delete_entry(fp, dry_run)
            n += 1
    return freed_kb, n


def reclaim(tier: str, home: Path = None, dry_run: bool = True, running: set = frozenset(),
            rows: list = None) -> dict:
    """Reclaim one tier ('safe' or 'safe-old'). Never touches review/report tiers."""
    home = (home or Path.home()).resolve()
    if tier not in ("safe", "safe-old"):
        raise ValueError("only the safe and safe-old tiers can be reclaimed by guardian")
    rows = census(home) if rows is None else rows     # an empty list means "nothing", not "everything"
    result = {"tier": tier, "dry_run": dry_run, "freed_mb": 0, "items": [], "skipped": []}
    for r in rows:
        if r["tier"] != tier or not r["paths"]:
            continue
        who = blocked_by(r, running)
        if who:
            result["skipped"].append({"name": r["name"], "why": f"{who} is running"})
            continue
        freed_kb = 0
        n = 0
        for ps in r["paths"]:
            p = Path(ps)
            try:
                p.resolve().relative_to(home)
            except ValueError:
                result["skipped"].append({"name": r["name"], "why": f"{p} is outside home"})
                continue
            if not p.is_dir() or p.is_symlink():
                continue
            method = r["method"] or "clear"
            if method.startswith("older-files:"):
                kb, cnt = _reclaim_old_files(p, int(method.split(":")[1]), dry_run)
                freed_kb += kb
                n += cnt
                continue
            days = int(method.split(":")[1]) if method.startswith("older:") else None
            try:
                entries = list(p.iterdir())
            except OSError:
                continue
            for e in entries:
                if days is not None and not _older_than(e, days):
                    continue
                freed_kb += _delete_entry(e, dry_run)
                n += 1
        result["items"].append({"name": r["name"], "entries": n, "mb": freed_kb // 1024})
        result["freed_mb"] += freed_kb // 1024
    return result


def render(rows: list, snapshots: list = None, disk_free_gb=None, running: set = frozenset()) -> str:
    lines = []
    if disk_free_gb is not None:
        lines.append(f"Disk free: {disk_free_gb} GB  (this is also the ceiling for swap)")
    if snapshots:
        lines.append(f"Time Machine local snapshots: {len(snapshots)} (purgeable, but they still crowd swap; "
                     f"thin with: sudo tmutil thinlocalsnapshots / 50000000000 4)")
    safe = reclaimable_mb(rows, ("safe",), running)
    old = reclaimable_mb(rows, ("safe-old",), running)
    lines.append(f"Reclaimable now: {safe / 1024:.1f} GB safe caches + up to {old / 1024:.1f} GB old logs/trash"
                 f"  ->  guardian.py scratch --reclaim safe --yes")
    lines.append("")
    lines.append(f"{'GB':>7}  {'tier':9} {'location':26} what")
    for r in rows:
        if r["mb"] == 0 and not r["paths"]:
            continue
        note = ""
        who = blocked_by(r, running)
        if who:
            note = f"  [{who} is running; skipped until it quits]"
        if r.get("unreadable"):
            note += "  [macOS would not let this program read it: the size is not known]"
        lines.append(f"{r['mb'] / 1024:7.2f}  {r['tier']:9} {r['name']:26} {r['what']}{note}")
    missing = [r["name"] for r in rows if not r["paths"]]
    if missing:
        lines.append("")
        lines.append("not present on this machine: " + ", ".join(missing))
    return "\n".join(lines)
