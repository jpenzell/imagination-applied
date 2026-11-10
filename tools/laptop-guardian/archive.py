#!/usr/bin/env python3
"""Guardian archive: move work folders nobody has used for weeks to an external drive.

The biggest thing on the first real Mac's disk was not a cache. It was 41 GB of dated Codex
work folders in ~/Documents/Codex, most of it a month old. That is the owner's data, so:

  * nothing here runs without a yes (the default is a dry run that only measures);
  * "unused" means no file changed AND no Codex / Claude Code thread worked in the folder
    (on that Mac the oldest folder had not changed in two months, and a thread was still
    using it that morning);
  * a folder is removed only after its copy has been read back from the drive and compared
    with the original entry by entry and byte by byte, and only if the folder did not
    change meanwhile. Any doubt at all leaves the folder exactly where it was.

One folder becomes one .tar file: that works on any drive format and keeps symlinks,
permissions and dates. Finder tags and other extended attributes are not kept. The drive's
copy is never deleted by guardian, not even on restore.

Stdlib only. guardian.py owns the asking, the logging and the command line.
"""
import fcntl
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path

HOME = Path.home()
HOST = socket.gethostname().split(".")[0]
ARCHIVE_FOLDER = "Guardian Archive"
NOTE_NAME = "ARCHIVED-BY-GUARDIAN.txt"
CHUNK = 1 << 20
IS_MAC = sys.platform == "darwin"
# Never a root: app state (which is where transcripts and sessions live), downloads, apps.
# Every dot-folder (~/.codex, ~/.claude, ~/.ssh ...) is refused as well.
FORBIDDEN_TOP = {"Library", "Downloads", "Applications"}
SF_DATALESS = 0x40000000      # a cloud placeholder: reading it would download the file
GOOD_FS = {"apfs", "hfs", "exfat"}     # msdos cannot hold a file over 4 GB; ntfs is read-only
CWD_RE = re.compile(r'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"')


class ArchiveError(Exception):
    pass


# ----------------------------------------------------------------- what could move

def resolve_root(raw, home: Path = None) -> Path:
    home = home or HOME
    p = Path(str(raw)).expanduser()
    return Path(os.path.normpath(p if p.is_absolute() else home / p))


def root_problem(root: Path, home: Path = None) -> str:
    """'' when guardian may offer this folder's children, else why not."""
    home = home or HOME
    try:
        rel = Path(os.path.realpath(root)).relative_to(os.path.realpath(home))
    except ValueError:
        return "outside the home folder"
    if not rel.parts:
        return "the home folder itself"
    if rel.parts[0] in FORBIDDEN_TOP or rel.parts[0].startswith("."):
        return f"~/{rel.parts[0]} is never archived"
    if root.is_symlink() or not root.is_dir():
        return "not a folder"
    return ""


def _raise(err):
    raise err


def walk_entries(src):
    """Every directory, file and symlink under src (src itself first) as (path, lstat), in
    one fixed order. The writer, the verifier and the measuring all use this walk, so they
    agree on what the folder contains. Sockets, pipes and devices are skipped: not data.
    An unreadable directory raises instead of being silently treated as empty."""
    src = str(src)
    yield src, os.lstat(src)
    for d, dirs, files in os.walk(src, followlinks=False, onerror=_raise):
        dirs.sort()
        links = [n for n in dirs if os.path.islink(os.path.join(d, n))]
        for n in sorted(files + links):
            p = os.path.join(d, n)
            st = os.lstat(p)
            if stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode):
                yield p, st
        for n in dirs:
            if n not in links:
                p = os.path.join(d, n)
                yield p, os.lstat(p)


def tree_stat(src) -> dict:
    """One walk: bytes on disk, bytes of content, entries, newest change, cloud placeholders."""
    out = {"disk": 0, "logical": 0, "entries": 0, "newest": 0.0, "dataless": 0}
    for _p, st in walk_entries(src):
        out["entries"] += 1
        out["disk"] += st.st_blocks * 512
        if stat.S_ISREG(st.st_mode):
            out["logical"] += st.st_size
            if getattr(st, "st_flags", 0) & SF_DATALESS:
                out["dataless"] += 1
        if st.st_mtime > out["newest"]:
            out["newest"] = st.st_mtime
    return out


def session_cwds(session_dirs, since: float, home: Path = None) -> dict:
    """{working folder: when a thread there was last active} from agent session logs changed
    since the given time. Codex rollouts and Claude Code transcripts both carry "cwd" near
    the top; only the first 16 KB of each recent file is read, and nothing is written."""
    home = home or HOME
    out = {}
    for raw in session_dirs or []:
        base = resolve_root(raw, home)
        try:
            walker = os.walk(base, followlinks=False)
            for d, _dirs, files in walker:
                for f in files:
                    if not f.endswith(".jsonl"):
                        continue
                    p = os.path.join(d, f)
                    try:
                        m = os.lstat(p).st_mtime
                        if m < since:
                            continue
                        with open(p, "rb") as fh:
                            head = fh.read(16384).decode("utf-8", "replace")
                    except OSError:
                        continue
                    for raw_cwd in set(CWD_RE.findall(head)):
                        try:
                            cwd = json.loads('"' + raw_cwd + '"')
                        except ValueError:
                            cwd = raw_cwd
                        if m > out.get(cwd, 0.0):
                            out[cwd] = m
        except OSError:
            continue
    return out


def last_thread_use(path: str, cwds: dict) -> float:
    """When an agent thread last worked in this folder or anywhere inside it (0.0 = never seen)."""
    prefix = path.rstrip("/") + "/"
    return max([t for c, t in cwds.items() if c == path or c.startswith(prefix)] or [0.0])


def scan(roots, min_age_days: float, min_mb: float = 50, now: float = None, home: Path = None,
         session_dirs=None, restored: dict = None) -> list:
    """Every child folder of every root, each with what it holds and, in 'keep', why it stays
    ('' = it could move). Read-only. Biggest first."""
    now = now or time.time()
    home = home or HOME
    restored = restored or {}
    cwds = session_cwds(session_dirs, now - min_age_days * 86400, home)
    out = []
    for raw in roots or []:
        root = resolve_root(raw, home)
        if root_problem(root, home):
            continue
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue
        for c in children:
            if c.name.startswith(".") or c.is_symlink() or not c.is_dir():
                continue
            row = {"root": str(root), "name": c.name, "path": str(c), "mb": 0, "logical_mb": 0,
                   "entries": 0, "newest": 0.0, "age_days": 0, "keep": ""}
            try:
                s = tree_stat(c)
            except OSError as e:
                row["keep"] = f"could not be read ({e.strerror or e})"
                out.append(row)
                continue
            used = last_thread_use(str(c), cwds)
            back = restored.get(str(c), 0.0)
            last = max(s["newest"], used, back)
            age = (now - last) / 86400
            row.update(mb=round(s["disk"] / 1048576), logical_mb=round(s["logical"] / 1048576),
                       entries=s["entries"], newest=s["newest"], age_days=int(age))
            if s["dataless"]:
                row["keep"] = "partly in the cloud, not on this disk"
            elif age < min_age_days:
                what = ("an agent thread worked in it" if last == used else
                        "you brought it back" if last == back else "changed")
                row["keep"] = f"{what} {int(age)} days ago" if age >= 1 else f"{what} today"
            elif s["disk"] < min_mb * 1048576:
                row["keep"] = "small"
            out.append(row)
    return sorted(out, key=lambda r: -r["mb"])


# ----------------------------------------------------------------- where it could go

MOUNT_RE = re.compile(r"^(\S+) on (/.*) \(([^)]*)\)$")


def parse_mounts(text: str) -> list:
    """`mount` on macOS: '/dev/disk7s1 on /Volumes/My Passport (apfs, local, nodev, journaled)'."""
    out = []
    for line in text.splitlines():
        m = MOUNT_RE.match(line.strip())
        if m:
            flags = [f.strip() for f in m.group(3).split(",")]
            out.append({"device": m.group(1), "path": m.group(2), "fs": flags[0], "flags": flags[1:]})
    return out


def _disk_no(device: str):
    m = re.match(r"/dev/disk(\d+)", device)
    return m.group(1) if m else None


def eligible_volumes(mounts: list, free_mb=None, writable=None) -> list:
    """Drives a folder could move to: mounted under /Volumes, local, writable, a format that
    holds big files, and not another volume of the startup disk (that would free nothing)."""
    free_mb = free_mb or (lambda p: shutil.disk_usage(p).free // 1048576)
    writable = writable or (lambda p: os.access(p, os.W_OK))
    boot = next((_disk_no(m["device"]) for m in mounts if m["path"] == "/"), None)
    out = []
    for m in mounts:
        name = m["path"][len("/Volumes/"):] if m["path"].startswith("/Volumes/") else ""
        if not name or "/" in name or name.startswith("."):
            continue
        if m["fs"] not in GOOD_FS or "local" not in m["flags"] or "read-only" in m["flags"] \
                or "nobrowse" in m["flags"]:
            continue
        if boot is not None and _disk_no(m["device"]) == boot:
            continue
        try:
            if not writable(m["path"]):
                continue
            out.append({"name": name, "path": m["path"], "fs": m["fs"], "free_mb": int(free_mb(m["path"]))})
        except OSError:
            continue
    return out


def volumes() -> list:
    import subprocess
    try:
        text = subprocess.run(["mount"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return []
    return eligible_volumes(parse_mounts(text))


def pick_destination(vols: list, wanted: str = "", need_mb: float = 0):
    """(volume, '') or (None, why). wanted is a volume name or a folder on one; '' means the
    connected drive with the most room. The result's 'base' is where Guardian Archive goes."""
    wanted = (wanted or "").rstrip("/")
    if wanted:
        vols = [v for v in vols if wanted in (v["name"], v["path"]) or wanted.startswith(v["path"] + "/")]
        if not vols:
            return None, f"{wanted} is not connected"
    if not vols:
        return None, "no external drive is connected"
    best = max(vols, key=lambda v: v["free_mb"])
    need = need_mb * 1.05 + 1024
    if best["free_mb"] < need:
        return None, f"{best['name']} has {best['free_mb'] / 1024:.0f} GB free; {need / 1024:.0f} GB is needed"
    return dict(best, base=wanted if wanted.startswith("/") else best["path"]), ""


def dest_dir(volume: dict, root: str, home: Path = None, host: str = None) -> Path:
    """<drive>/Guardian Archive/<this Mac>/<the root, relative to home>/"""
    rel = os.path.relpath(os.path.realpath(root), os.path.realpath(home or HOME))
    if rel.startswith(".."):               # never climb out of the archive folder
        rel = os.path.basename(str(root).rstrip("/"))
    return Path(volume["base"]) / ARCHIVE_FOLDER / (host or HOST) / rel


# ----------------------------------------------------------------- copy, check, remove

def _fcntl(f, name: str, number: int):
    if IS_MAC:
        try:
            fcntl.fcntl(f.fileno(), getattr(fcntl, name, number), 1)
        except (OSError, ValueError):
            pass


def _nocache(f):
    """Tens of GB should not pass through the file cache of a Mac that is short of memory;
    and a read-back that skips the cache really comes from the drive."""
    _fcntl(f, "F_NOCACHE", 48)


class _HashWriter:
    def __init__(self, f):
        self.f, self.h, self.n = f, hashlib.sha256(), 0

    def write(self, b):
        self.h.update(b)
        self.n += len(b)
        return self.f.write(b)

    def tell(self):
        return self.n


def write_tar(src, tar_path) -> dict:
    src = Path(src)
    base = str(src.parent)
    entries = 0
    with open(tar_path, "wb", buffering=4 * CHUNK) as raw:
        _nocache(raw)
        hw = _HashWriter(raw)
        with tarfile.open(fileobj=hw, mode="w", format=tarfile.PAX_FORMAT, copybufsize=CHUNK) as tar:
            for path, _st in walk_entries(src):
                ti = tar.gettarinfo(path, arcname=os.path.relpath(path, base))
                if ti is None:
                    raise ArchiveError(f"cannot archive {path}")
                if ti.isreg():
                    with open(path, "rb", buffering=0) as f:
                        _nocache(f)
                        tar.addfile(ti, f)
                else:
                    tar.addfile(ti)
                tar.members.clear()      # tarfile keeps a record per entry; a big folder has 500,000
                entries += 1
        raw.flush()
        os.fsync(raw.fileno())
        _fcntl(raw, "F_FULLFSYNC", 51)
    return {"entries": entries, "bytes": hw.n, "sha256": hw.h.hexdigest()}


def _readn(f, n: int) -> bytes:
    parts, got = [], 0
    while got < n:
        b = f.read(n - got)
        if not b:
            break
        parts.append(b)
        got += len(b)
    return b"".join(parts)


def _same_content(tf, path: str) -> bool:
    with open(path, "rb", buffering=0) as f:
        _nocache(f)
        while True:
            a, b = _readn(tf, CHUNK), _readn(f, CHUNK)
            if a != b:
                return False
            if not a:
                return True


def verify_tar(src, tar_path) -> dict:
    """Read the archive back and compare it with the folder: the same entries in the same
    order, the same types, link targets and sizes, and the same bytes in every file.
    {'ok': bool, 'entries': n, 'why': str}"""
    src = Path(src)
    base = str(src.parent)
    n = 0
    try:
        with open(tar_path, "rb", buffering=4 * CHUNK) as raw:
            _nocache(raw)
            with tarfile.open(fileobj=raw, mode="r:") as tar:
                for path, st in walk_entries(src):
                    arc = os.path.relpath(path, base)
                    m = tar.next()
                    tar.members.clear()
                    if m is None:
                        return {"ok": False, "entries": n, "why": f"missing from the copy: {arc}"}
                    if m.name.rstrip("/") != arc:
                        return {"ok": False, "entries": n, "why": f"differs: {arc} (the copy has {m.name} there)"}
                    if stat.S_ISDIR(st.st_mode):
                        same = m.isdir()
                    elif stat.S_ISLNK(st.st_mode):
                        same = m.issym() and m.linkname == os.readlink(path)
                    elif m.islnk():        # a second name for a file already in the copy
                        same = os.path.samestat(st, os.lstat(os.path.join(base, m.linkname)))
                    else:
                        same = m.isreg() and m.size == st.st_size and _same_content(tar.extractfile(m), path)
                    if not same:
                        return {"ok": False, "entries": n, "why": f"differs: {arc}"}
                    n += 1
                extra = tar.next()
                if extra is not None:
                    return {"ok": False, "entries": n, "why": f"the copy has an extra entry: {extra.name}"}
    except (OSError, tarfile.TarError, ArchiveError) as e:
        return {"ok": False, "entries": n, "why": f"could not be read back ({e})"}
    return {"ok": True, "entries": n, "why": ""}


def free_name(folder: Path, name: str) -> Path:
    p, i = folder / f"{name}.tar", 2
    while p.exists() or p.with_name(p.name + ".partial").exists():
        p, i = folder / f"{name}-{i}.tar", i + 1
    return p


def force_rmtree(path) -> int:
    """Remove a folder even if parts of it are read-only or locked (module caches often are).
    Returns how many entries could not be removed."""
    failed = []
    kw = {"onexc" if sys.version_info >= (3, 12) else "onerror": lambda _f, p, _e: failed.append(p)}
    shutil.rmtree(path, **kw)
    if failed and os.path.lexists(path):
        for d, dirs, files in os.walk(path):       # unlock, top down, then try once more
            for q in [d] + [os.path.join(d, n) for n in dirs + files]:
                try:
                    if hasattr(os, "lchflags"):
                        os.lchflags(q, 0)
                    if not os.path.islink(q):
                        os.chmod(q, 0o700)
                except OSError:
                    pass
        failed.clear()
        shutil.rmtree(path, **kw)
    return len(failed)


def read_manifest(path) -> list:
    out = []
    try:
        for line in Path(path).read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return out


def _append(path, row: dict):
    if path is None:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")


def on_drive(rows: list) -> list:
    """Folders that were moved and have not been brought back, oldest first."""
    back = {r.get("archive") for r in rows if r.get("kind") == "restored"}
    return [r for r in rows if r.get("kind") == "archived" and r.get("archive") not in back]


def restored_at(rows: list) -> dict:
    """{folder: when it was last brought back}: a folder you asked for counts as used then."""
    out = {}
    for r in rows:
        if r.get("kind") == "restored" and r.get("source"):
            out[r["source"]] = max(out.get(r["source"], 0.0), datetime.fromisoformat(r["ts"]).timestamp())
    return out


def _note(root: str, row: dict, restore_hint: str):
    """One plain file in the root saying where things went: found by a person browsing
    Finder long after the notification is forgotten."""
    try:
        p = Path(root) / NOTE_NAME
        new = not p.exists()
        with p.open("a") as f:
            if new:
                f.write("Guardian moved these folders to an external drive to free space on this Mac.\n"
                        "Each was copied, the copy was read back and compared byte for byte, and only then\n"
                        "was the folder removed here. Bring one back with the command on its line.\n\n")
            f.write(f"{row['ts'][:16].replace('T', ' ')}  {row['name']}  ({row['mb'] / 1024:.1f} GB)  ->  "
                    f"{row['archive']}\n    bring it back: {restore_hint} {row['name']}\n")
    except OSError:
        pass


def archive_one(cand: dict, folder: Path, manifest=None, restore_hint: str = "guardian.py archive --restore",
                host: str = None) -> dict:
    """Copy one folder to <folder>/<name>.tar, read the copy back, and only if it matches and
    the folder did not change, remove the folder. Returns {'ok', 'name', 'why', ...}."""
    src = Path(cand["path"])
    res = {"ok": False, "name": src.name, "source": str(src), "why": "", "mb": cand.get("mb", 0)}
    part = None
    t0 = time.time()
    try:
        before = tree_stat(src)
        if before["dataless"]:
            raise ArchiveError("partly in the cloud, not on this disk")
        if cand.get("newest") and before["newest"] > cand["newest"] + 1:
            raise ArchiveError("it changed after it was measured")
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        tar_path = free_name(folder, src.name)
        part = tar_path.with_name(tar_path.name + ".partial")
        w = write_tar(src, part)
        v = verify_tar(src, part)
        if not v["ok"]:
            raise ArchiveError("the copy does not match: " + v["why"])
        after = tree_stat(src)
        if v["entries"] != w["entries"] or any(after[k] != before[k] for k in ("newest", "entries", "logical")):
            raise ArchiveError("the folder changed while it was being copied")
        os.replace(part, tar_path)
        part = None
    except (OSError, tarfile.TarError, ArchiveError) as e:
        if part is not None:
            try:
                part.unlink()
            except OSError:
                pass
        res["why"] = str(e)
        return res
    row = {"ts": datetime.now().isoformat(timespec="seconds"), "host": host or HOST, "kind": "archived",
           "name": src.name, "source": str(src), "root": cand.get("root", str(src.parent)),
           "archive": str(tar_path), "mb": round(before["disk"] / 1048576), "entries": w["entries"],
           "bytes": w["bytes"], "sha256": w["sha256"], "seconds": round(time.time() - t0, 1)}
    try:                                   # a small card next to the archive, for whoever finds the drive
        Path(str(tar_path) + ".json").write_text(json.dumps(row, indent=1) + "\n")
    except OSError:
        pass
    _append(manifest, row)                 # recorded before anything is removed
    left = force_rmtree(src)
    _note(row["root"], row, restore_hint)
    res.update(ok=True, archive=str(tar_path), mb=row["mb"], entries=row["entries"],
               seconds=row["seconds"], leftover=left)
    if left:
        res["why"] = f"copied and checked, but {left} items could not be removed here"
    return res


# ----------------------------------------------------------------- bring one back

_TRUSTED = {"filter": "fully_trusted"} if hasattr(tarfile, "fully_trusted_filter") else {}


def _extract(tar, into):
    """Unpack one entry at a time (no per-entry record kept in memory). Folders get their
    permissions and dates last, so a read-only folder can still be filled; links get their
    dates too, which tarfile leaves at 'now'. The archive is our own, checked when written."""
    into = str(into)
    folders = []
    while True:
        m = tar.next()
        tar.members.clear()
        if m is None:
            break
        tar.extract(m, into, set_attrs=not m.isdir(), **_TRUSTED)
        target = os.path.join(into, m.name)
        if m.isdir():
            folders.append((target, m.mode, m.mtime))
        elif m.issym():
            try:
                os.utime(target, (m.mtime, m.mtime), follow_symlinks=False)
            except (OSError, NotImplementedError):
                pass
    for target, mode, mtime in reversed(folders):
        os.utime(target, (mtime, mtime))
        os.chmod(target, mode & 0o7777)


def restore(row: dict, manifest=None, keep_free_mb: int = 2048) -> dict:
    """Put an archived folder back where it was. The drive's copy stays."""
    tar_path, target = Path(row["archive"]), Path(row["source"])
    res = {"ok": False, "name": row["name"], "source": str(target), "why": ""}
    if not tar_path.exists():
        res["why"] = f"its drive is not connected (looked for {tar_path})"
        return res
    if target.exists() or target.is_symlink():
        res["why"] = f"{target} already exists"
        return res
    parent = target.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(parent).free // 1048576
        need = row.get("bytes", 0) // 1048576
        if free - need < keep_free_mb:
            raise ArchiveError(f"it needs {need / 1024:.1f} GB and this Mac has {free / 1024:.1f} GB free")
        tmp = parent / f".guardian-restore-{os.getpid()}"
        try:
            with tarfile.open(tar_path, "r:") as tar:
                _extract(tar, tmp)
            v = verify_tar(tmp / target.name, tar_path)
            if not v["ok"]:
                raise ArchiveError("what came back does not match the drive's copy: " + v["why"])
            os.rename(tmp / target.name, target)
        finally:
            if tmp.exists():
                force_rmtree(tmp)
    except (OSError, tarfile.TarError, ArchiveError) as e:
        res["why"] = str(e)
        return res
    _append(manifest, {"ts": datetime.now().isoformat(timespec="seconds"), "host": row.get("host", HOST),
                       "kind": "restored", "name": row["name"], "source": str(target), "archive": str(tar_path)})
    res.update(ok=True, archive=str(tar_path), mb=row.get("mb", 0))
    return res
