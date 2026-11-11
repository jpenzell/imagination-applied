#!/usr/bin/env python3
"""Tests for the archive layer. Builds a fake home and a fake drive in a temp folder; never
touches the real home or a real drive. Run: python3 test_archive.py"""
import json
import os
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import archive

DAY = 86400
# `mount` exactly as the first real Mac printed it (2026-11-10, macOS 27, a USB drive attached)
MOUNT = """/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)
devfs on /dev (devfs, local, nobrowse)
/dev/disk3s6 on /System/Volumes/VM (apfs, local, noexec, journaled, noatime, nobrowse)
/dev/disk3s2 on /System/Volumes/Preboot (apfs, local, journaled, nobrowse)
/dev/disk3s4 on /System/Volumes/Update (apfs, local, journaled, nobrowse)
/dev/disk1s2 on /System/Volumes/xarts (apfs, local, noexec, journaled, noatime, nobrowse)
/dev/disk1s1 on /System/Volumes/iSCPreboot (apfs, local, journaled, nobrowse)
/dev/disk1s3 on /System/Volumes/Hardware (apfs, local, journaled, nobrowse)
/dev/disk3s5 on /System/Volumes/Data (apfs, local, journaled, nobrowse, protect, root data)
map auto_home on /System/Volumes/Data/home (autofs, automounted, nobrowse)
/dev/disk7s1 on /Volumes/My Passport (apfs, local, nodev, nosuid, journaled, noowners)
/dev/disk3s3 on /Volumes/Recovery (apfs, local, journaled, nobrowse)
"""


def mk(path: Path, data: bytes = b"x" * 4096):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def age_tree(top: Path, days: float):
    """Give everything under top (and top) a modification time `days` ago."""
    t = time.time() - days * DAY
    for d, dirs, files in os.walk(top, topdown=False):
        for n in files + dirs:
            os.utime(os.path.join(d, n), (t, t), follow_symlinks=False)
    os.utime(top, (t, t))


def listing(top: Path) -> list:
    out = []
    for p, st in archive.walk_entries(top):
        rel = os.path.relpath(p, top)
        if os.path.islink(p):
            out.append((rel, "link", os.readlink(p)))
        elif os.path.isdir(p):
            out.append((rel, "dir", ""))
        else:
            out.append((rel, "file", Path(p).read_bytes()))
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(archive.force_rmtree, self.tmp)
        self.home = self.tmp / "home"
        self.root = self.home / "Documents" / "Codex"
        self.drive = self.tmp / "drive" / "Guardian Archive" / "Mac" / "Documents" / "Codex"
        self.manifest = self.tmp / "logs" / "archive.jsonl"

    def work_folder(self, name="2026-09-17", days=40, big=b"") -> Path:
        """A realistic work folder: nested files, a non-ASCII name, a symlink to a file and to a
        folder, a second name for the same file, an empty folder, a read-only folder, a pipe."""
        src = self.root / name
        mk(src / "project" / "work" / "data.bin", big or os.urandom(300_000))
        mk(src / "project" / "notes über.txt", "héllo".encode())
        mk(src / "project" / "outputs" / "report.html", b"<html>" + b"r" * 70_000)
        os.symlink("work/data.bin", src / "project" / "latest")
        os.symlink("project/work", src / "shortcut")
        os.link(src / "project" / "work" / "data.bin", src / "same-file.bin")
        (src / "empty").mkdir()
        mk(src / "locked" / "module.py", b"print(1)\n")
        os.chmod(src / "locked", 0o555)
        os.mkfifo(src / "a-pipe")
        age_tree(src, days)
        return src

    def cand(self, src: Path) -> dict:
        return {"path": str(src), "root": str(src.parent), "name": src.name, "mb": 1,
                "newest": archive.tree_stat(src)["newest"]}


class WhereTests(unittest.TestCase):
    def vols(self, text=MOUNT, free=None, writable=lambda p: True):
        free = free or {"/Volumes/My Passport": 3_161_000}
        return archive.eligible_volumes(archive.parse_mounts(text), free_mb=lambda p: free.get(p, 50_000),
                                        writable=writable)

    def test_only_the_external_drive_qualifies_on_a_real_mac(self):
        self.assertEqual(self.vols(), [{"name": "My Passport", "path": "/Volumes/My Passport", "fs": "apfs",
                                        "free_mb": 3_161_000}])

    def test_drives_that_cannot_take_the_folders_are_left_out(self):
        extra = MOUNT + "\n".join([
            "/dev/disk3s9 on /Volumes/Scratch (apfs, local, journaled)",                    # same disk as /
            "/dev/disk8s1 on /Volumes/CAMERA (msdos, local, nodev, nosuid, noowners)",      # 4 GB file limit
            "/dev/disk9s1 on /Volumes/Installer (hfs, local, nodev, nosuid, read-only, noowners)",
            "//josh@nas/share on /Volumes/share (smbfs, nodev, nosuid, mounted by josh)",   # network
            "/dev/disk10s2 on /Volumes/Photos SSD (exfat, local, nodev, nosuid, noowners)",
            "/dev/disk11s1 on /Volumes/Locked (apfs, local, journaled)",
        ]) + "\n"
        names = [v["name"] for v in self.vols(extra, writable=lambda p: not p.endswith("Locked"))]
        self.assertEqual(names, ["My Passport", "Photos SSD"])

    def test_picks_the_roomiest_or_the_named_drive_and_refuses_a_full_one(self):
        vols = [{"name": "A", "path": "/Volumes/A", "fs": "apfs", "free_mb": 90_000},
                {"name": "B", "path": "/Volumes/B", "fs": "exfat", "free_mb": 400_000}]
        self.assertEqual(archive.pick_destination(vols, "", 30_000)[0]["name"], "B")
        v, _ = archive.pick_destination(vols, "A", 30_000)
        self.assertEqual((v["name"], v["base"]), ("A", "/Volumes/A"))
        v, _ = archive.pick_destination(vols, "/Volumes/A/Mac Archive/", 30_000)
        self.assertEqual(v["base"], "/Volumes/A/Mac Archive")
        self.assertEqual(archive.pick_destination(vols, "C", 1), (None, "C is not connected"))
        self.assertEqual(archive.pick_destination([], "", 1), (None, "no external drive is connected"))
        v, why = archive.pick_destination(vols, "A", 89_000)
        self.assertIsNone(v)
        self.assertIn("A has 88 GB free", why)

    def test_destination_path_names_this_mac_and_the_root(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t) / "home"
            (home / "Documents" / "Codex").mkdir(parents=True)
            d = archive.dest_dir({"base": "/Volumes/My Passport"}, str(home / "Documents" / "Codex"), home, "Joshs-Air")
            self.assertEqual(str(d), "/Volumes/My Passport/Guardian Archive/Joshs-Air/Documents/Codex")


class ScanTests(Base):
    def scan(self, **kw):
        kw.setdefault("home", self.home)
        return {r["name"]: r for r in archive.scan(["Documents/Codex"], 30, 0.1, **kw)}

    def test_roots_that_hold_app_state_sessions_or_downloads_are_refused(self):
        for rel in ["Library/Application Support/Claude", "Downloads", ".codex/sessions", ".claude/projects",
                    "Documents/../.codex", "."]:
            p = archive.resolve_root(rel, self.home)
            p.mkdir(parents=True, exist_ok=True)
            self.assertTrue(archive.root_problem(p, self.home), rel)
        self.assertTrue(archive.root_problem(self.tmp, self.home), "outside home")
        self.root.mkdir(parents=True)
        self.assertEqual(archive.root_problem(self.root, self.home), "")
        (self.home / "Linked").symlink_to(self.home / "Library")
        self.assertTrue(archive.root_problem(self.home / "Linked", self.home), "a link into Library")
        self.assertEqual(archive.scan(["Downloads", ".codex/sessions"], 0, 0, home=self.home), [])

    def test_a_folder_with_one_recent_file_deep_inside_stays(self):
        # the first real Mac: a 22 GB folder dated September whose build logs were two weeks old
        old = self.work_folder("2026-09-17", days=40)
        live = self.work_folder("2026-09-23", days=48)
        deep = live / "project" / "work" / "build.log"
        mk(deep, b"built\n")
        t = time.time() - 14 * DAY
        os.utime(deep, (t, t))
        os.utime(deep.parent, (t, t))
        os.utime(live, (time.time() - 48 * DAY,) * 2)       # the folder's own date still says September
        rows = self.scan()
        self.assertEqual(rows[old.name]["keep"], "")
        self.assertEqual(rows[old.name]["age_days"], 40)
        self.assertEqual(rows[live.name]["keep"], "changed 14 days ago")

    def test_a_folder_an_agent_thread_is_working_in_stays(self):
        # the first real Mac: no file in 2026-09-09 had changed for two months; a Codex thread
        # whose working folder it was had been active that morning
        src = self.work_folder("2026-09-09", days=60)
        other = self.work_folder("2026-09-10", days=60)
        cwd = json.dumps(str(src / "project"))
        mk(self.home / ".codex/sessions/2026/09/09/rollout-a.jsonl",
           ('{"timestamp":"2026-09-09T23:59:02Z","type":"session_meta","payload":{"id":"x","cwd":%s,"cli":"1"}}\n' % cwd).encode())
        stale = self.home / ".codex/sessions/2026/09/10/rollout-b.jsonl"
        mk(stale, ('{"type":"session_meta","payload":{"cwd":%s}}\n' % json.dumps(str(other))).encode())
        os.utime(stale, (time.time() - 50 * DAY,) * 2)
        mk(self.home / ".codex/sessions/notes.txt", ('"cwd":%s' % json.dumps(str(other))).encode())
        rows = self.scan(session_dirs=[".codex/sessions", ".claude/projects"])
        self.assertEqual(rows[src.name]["keep"], "an agent thread worked in it today")
        self.assertEqual(rows[other.name]["keep"], "", "a thread that ended 50 days ago does not hold it")

    def test_session_working_folders_with_spaces_and_escapes(self):
        p = self.home / ".claude/projects/-x/t.jsonl"
        mk(p, b'{"type":"summary"}\n{"cwd":"/Users/j/My \\"Work\\"/caf\\u00e9","sessionId":"1"}\n')
        self.assertEqual(list(archive.session_cwds([".claude/projects"], 0, self.home)), ['/Users/j/My "Work"/café'])
        self.assertEqual(archive.last_thread_use("/Users/j/My", {"/Users/j/My \"Work\"/café": 5.0}), 0.0,
                         "a name that merely starts the same is a different folder")

    def test_small_hidden_linked_restored_and_cloud_folders(self):
        keep = self.work_folder("2026-09-01", days=90)
        tiny = self.root / "2026-09-02"
        mk(tiny / "a.txt", b"x")
        age_tree(tiny, 90)
        mk(self.root / ".cache" / "blob", b"x" * 400_000)
        mk(self.root / "AGENTS.md", b"notes")
        (self.root / "alias").symlink_to(keep)
        back = self.work_folder("2026-09-03", days=90)
        cloud = self.work_folder("2026-09-04", days=90)
        real = archive.tree_stat
        with mock.patch.object(archive, "tree_stat",
                               lambda p: dict(real(p), dataless=1) if str(p) == str(cloud) else real(p)):
            rows = self.scan(restored={str(back): time.time() - 2 * DAY})
        self.assertEqual(sorted(rows), ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"])
        self.assertEqual(rows["2026-09-01"]["keep"], "")
        self.assertEqual(rows["2026-09-02"]["keep"], "small")
        self.assertEqual(rows["2026-09-03"]["keep"], "you brought it back 2 days ago")
        self.assertEqual(rows["2026-09-04"]["keep"], "partly in the cloud, not on this disk")

    def test_a_root_macos_will_not_let_guardian_read_is_a_problem_not_an_empty_plan(self):
        # the first real Mac: the background agent was refused ~/Documents and logged "0 folders"
        self.work_folder("2026-09-17", days=40)
        self.assertEqual(archive.root_problems(["Documents/Codex", "Downloads"], self.home),
                         [[str(self.home / "Downloads"), "~/Downloads is never archived"]])
        os.chmod(self.root, 0o000)
        self.addCleanup(os.chmod, self.root, 0o755)
        if os.access(self.root, os.R_OK):
            self.skipTest("running as a user who can read anything")
        self.assertEqual(archive.root_problems(["Documents/Codex"], self.home),
                         [[str(self.root), "macOS will not let this program read it"]])
        self.assertEqual(archive.scan(["Documents/Codex"], 30, 0.1, home=self.home), [])

    def test_an_unreadable_folder_is_reported_not_treated_as_empty(self):
        src = self.work_folder("2026-09-05", days=90)
        os.chmod(src / "locked", 0o000)
        self.addCleanup(os.chmod, src / "locked", 0o755)
        if os.access(src / "locked", os.R_OK):
            self.skipTest("running as a user who can read anything")
        self.assertIn("could not be read", self.scan()[src.name]["keep"])


class CopyTests(Base):
    def test_the_copy_is_checked_entry_by_entry_and_byte_by_byte(self):
        src = self.work_folder()
        tar = self.tmp / "t.tar"
        w = archive.write_tar(src, tar)
        self.assertEqual(w["entries"], 13, "everything but the pipe")
        self.assertEqual(archive.verify_tar(src, tar), {"ok": True, "entries": 13, "why": ""})
        with tarfile.open(tar) as t:
            kinds = {m.name: m.type for m in t}
        self.assertEqual(kinds["2026-09-17/project/latest"], tarfile.SYMTYPE)
        self.assertEqual(kinds["2026-09-17/shortcut"], tarfile.SYMTYPE, "a link to a folder stays a link")
        self.assertIn(tarfile.LNKTYPE, (kinds["2026-09-17/same-file.bin"], kinds["2026-09-17/project/work/data.bin"]))

        def differs(change, undo):
            change()
            try:
                return archive.verify_tar(src, tar)
            finally:
                undo()
        notes = src / "project" / "notes über.txt"
        r = differs(lambda: notes.write_bytes("héllp".encode()), lambda: notes.write_bytes("héllo".encode()))
        self.assertEqual((r["ok"], r["why"]), (False, "differs: 2026-09-17/project/notes über.txt"), "same size, one byte")
        new = src / "project" / "outputs" / "zz-new.txt"
        r = differs(lambda: new.write_bytes(b"new"), new.unlink)
        self.assertFalse(r["ok"], "a file the copy does not have")
        link = src / "project" / "latest"
        r = differs(lambda: (link.unlink(), os.symlink("elsewhere", link)),
                    lambda: (link.unlink(), os.symlink("work/data.bin", link)))
        self.assertEqual(r["why"], "differs: 2026-09-17/project/latest")
        report = src / "project" / "outputs" / "report.html"
        body = report.read_bytes()
        r = differs(report.unlink, lambda: report.write_bytes(body))
        self.assertFalse(r["ok"], "a file only the copy has")
        self.assertTrue(archive.verify_tar(src, tar)["ok"], "all changes undone")

    def test_a_damaged_or_cut_off_copy_is_caught(self):
        src = self.work_folder(big=bytes(range(256)) * 4000)
        tar = self.tmp / "t.tar"
        archive.write_tar(src, tar)
        raw = bytearray(tar.read_bytes())
        at = raw.find(bytes(range(256)) * 4) + 5000
        raw[at] ^= 0xFF
        (self.tmp / "flipped.tar").write_bytes(raw)
        self.assertEqual(archive.verify_tar(src, self.tmp / "flipped.tar")["ok"], False, "one flipped bit")
        (self.tmp / "cut.tar").write_bytes(raw[:len(raw) // 2])
        self.assertEqual(archive.verify_tar(src, self.tmp / "cut.tar")["ok"], False, "the drive was unplugged")
        self.assertEqual(archive.verify_tar(src, self.tmp / "absent.tar")["ok"], False)

    def test_a_folder_is_removed_only_after_its_copy_checks_out(self):
        src = self.work_folder()
        before = listing(src)
        r = archive.archive_one(self.cand(src), self.drive, manifest=self.manifest, host="Mac")
        self.assertTrue(r["ok"], r)
        self.assertFalse(src.exists(), "removed here, read-only folder and all")
        self.assertEqual(sorted(os.listdir(self.drive)), ["2026-09-17.tar", "2026-09-17.tar.json"])
        row = archive.read_manifest(self.manifest)[0]
        self.assertEqual((row["kind"], row["name"], row["source"], row["archive"]),
                         ("archived", "2026-09-17", str(src), str(self.drive / "2026-09-17.tar")))
        import hashlib
        self.assertEqual(row["sha256"], hashlib.sha256((self.drive / "2026-09-17.tar").read_bytes()).hexdigest())
        note = (self.root / archive.NOTE_NAME).read_text()
        self.assertIn("2026-09-17", note)
        self.assertIn("archive --restore 2026-09-17", note)
        # and it comes back the same
        back = archive.restore(row, manifest=self.manifest, keep_free_mb=0)
        self.assertTrue(back["ok"], back)
        self.assertEqual(listing(src), before)
        self.assertEqual(os.stat(src / "same-file.bin").st_ino, os.stat(src / "project/work/data.bin").st_ino)
        self.assertAlmostEqual(os.stat(src / "project/outputs/report.html").st_mtime, time.time() - 40 * DAY, delta=5)
        self.assertTrue((self.drive / "2026-09-17.tar").exists(), "the drive keeps its copy")
        rows = archive.read_manifest(self.manifest)
        self.assertEqual(archive.on_drive(rows), [])
        self.assertAlmostEqual(archive.restored_at(rows)[str(src)], time.time(), delta=5)
        # a folder you asked for is not offered again the next morning
        found = archive.scan(["Documents/Codex"], 30, 0.1, home=self.home, restored=archive.restored_at(rows))
        self.assertEqual(found[0]["keep"], "you brought it back today")

    def test_any_doubt_leaves_the_folder_where_it_was(self):
        src = self.work_folder()
        before = listing(src)

        def kept(why_part, **patches):
            with mock.patch.multiple(archive, **patches):
                r = archive.archive_one(self.cand(src), self.drive, manifest=self.manifest)
            self.assertFalse(r["ok"])
            self.assertIn(why_part, r["why"])
            self.assertEqual(listing(src), before, why_part)
            self.assertEqual([n for n in os.listdir(self.drive) if "2026-09-17" in n], [], "no half copy left behind")
            self.assertEqual(archive.read_manifest(self.manifest), [])
        self.drive.mkdir(parents=True)
        kept("does not match", verify_tar=lambda s, t: {"ok": False, "entries": 3, "why": "differs: x"})
        real_write = archive.write_tar

        def write_then_touch(s, t):
            out = real_write(s, t)
            os.utime(Path(s) / "empty")              # something touched the folder during the copy
            return out
        kept("changed while it was being copied", write_tar=write_then_touch,
             verify_tar=lambda s, t: {"ok": True, "entries": 13, "why": ""})
        age_tree(src, 40)

        def no_room(s, t):
            raise OSError(28, "No space left on device")
        kept("No space left", write_tar=no_room)
        real_stat = archive.tree_stat
        kept("in the cloud", tree_stat=lambda p: dict(real_stat(p), dataless=2))
        # measured an hour ago, changed since
        stale = dict(self.cand(src), newest=time.time() - 41 * DAY)
        r = archive.archive_one(stale, self.drive, manifest=self.manifest)
        self.assertEqual((r["ok"], r["why"]), (False, "it changed after it was measured"))
        # the drive is gone (its mount point is not a folder guardian can write)
        mk(self.tmp / "nodrive", b"")
        r = archive.archive_one(self.cand(src), self.tmp / "nodrive" / "x", manifest=self.manifest)
        self.assertFalse(r["ok"])
        self.assertEqual(listing(src), before)

    def test_a_second_folder_of_the_same_name_gets_its_own_archive(self):
        first = self.work_folder()
        self.assertTrue(archive.archive_one(self.cand(first), self.drive, manifest=self.manifest)["ok"])
        again = self.work_folder()
        r = archive.archive_one(self.cand(again), self.drive, manifest=self.manifest)
        self.assertEqual(Path(r["archive"]).name, "2026-09-17-2.tar")
        self.assertEqual(len(archive.on_drive(archive.read_manifest(self.manifest))), 2)
        self.assertEqual((self.root / archive.NOTE_NAME).read_text().count("bring it back:"), 2)

    def test_a_second_copy_is_checked_against_the_recorded_checksum(self):
        src = self.work_folder()
        archive.archive_one(self.cand(src), self.drive, manifest=self.manifest, host="Mac")
        row = archive.read_manifest(self.manifest)[0]
        first = Path(row["archive"])
        second = self.tmp / "second"
        other_disk = lambda a, b: False
        self.assertEqual(archive.archive_rel(str(first)), "Mac/Documents/Codex/2026-09-17.tar")
        self.assertIn("same drive", archive.copy_archive(row, second, self.manifest)["why"], "tmp is one disk")
        r = archive.copy_archive(row, second, self.manifest, same_disk=other_disk)
        self.assertTrue(r["ok"], r)
        copy = second / "Guardian Archive" / "Mac" / "Documents" / "Codex" / "2026-09-17.tar"
        self.assertEqual((r["copy"], copy.read_bytes()), (str(copy), first.read_bytes()))
        self.assertTrue(Path(str(copy) + ".json").exists(), "the card travels with it")
        rows = archive.read_manifest(self.manifest)
        self.assertEqual([(x["kind"], x.get("verified")) for x in rows], [("archived", None), ("second", True)])
        self.assertEqual(archive.recorded_copies(rows), {str(first): [str(copy)]})
        self.assertIn("already exists", archive.copy_archive(row, second, self.manifest, same_disk=other_disk)["why"])
        self.assertTrue(first.exists(), "nothing is ever removed by copying")
        # finding copies someone made by hand: same name and exact size, in the usual place or loose
        self.assertEqual(archive.find_copies(row, [str(second)]), [str(copy)])
        loose = self.tmp / "loose"
        loose.mkdir()
        (loose / "2026-09-17.tar").write_bytes(first.read_bytes())
        (self.tmp / "wrong").mkdir()
        (self.tmp / "wrong" / "2026-09-17.tar").write_bytes(first.read_bytes()[:-1])
        self.assertEqual(archive.find_copies(row, [str(loose), str(self.tmp / "wrong"), str(self.tmp / "nowhere")]),
                         [str(loose / "2026-09-17.tar")])
        self.assertEqual(archive.find_copies(row, [str(first.parents[4])]), [], "the first copy is not its own second")
        # a recorded copy counts while its drive is away, not once the file is gone from it
        self.assertTrue(archive.copy_still_counts(str(copy)))
        self.assertTrue(archive.copy_still_counts("/Volumes/Unplugged/Guardian Archive/x.tar"))
        self.assertTrue(archive.copy_still_counts(str(copy), row["bytes"]))
        self.assertFalse(archive.copy_still_counts(str(copy), row["bytes"] + 1), "cut short or grown: not a copy any more")
        copy.unlink()
        self.assertFalse(archive.copy_still_counts(str(copy)))

    def test_a_first_copy_that_has_gone_bad_is_said_loudly_and_not_copied(self):
        src = self.work_folder(big=bytes(range(256)) * 4000)
        archive.archive_one(self.cand(src), self.drive, manifest=self.manifest, host="Mac")
        row = archive.read_manifest(self.manifest)[0]
        first = Path(row["archive"])
        raw = bytearray(first.read_bytes())
        raw[len(raw) // 2] ^= 0x01                              # one bit rots on the drive
        first.write_bytes(raw)
        second = self.tmp / "second"
        r = archive.copy_archive(row, second, self.manifest, same_disk=lambda a, b: False)
        self.assertFalse(r["ok"])
        self.assertTrue(r["first_copy_damaged"])
        self.assertIn("no longer matches the checksum", r["why"])
        left = [str(p) for p in second.rglob("*") if p.is_file()]
        self.assertEqual(left, [], "a bad copy is not kept as if it were a backup")
        self.assertEqual([x["kind"] for x in archive.read_manifest(self.manifest)], ["archived"])
        first.unlink()
        self.assertIn("not reachable", archive.copy_archive(row, second, self.manifest, same_disk=lambda a, b: False)["why"])

    def test_a_folder_comes_back_from_the_second_copy_when_the_first_drive_is_gone(self):
        src = self.work_folder()
        before = listing(src)
        archive.archive_one(self.cand(src), self.drive, manifest=self.manifest, host="Mac")
        row = archive.read_manifest(self.manifest)[0]
        r = archive.copy_archive(row, self.tmp / "second", self.manifest, same_disk=lambda a, b: False)
        Path(row["archive"]).unlink()
        self.assertIn("not connected", archive.restore(row, manifest=self.manifest, keep_free_mb=0)["why"])
        back = archive.restore(row, manifest=self.manifest, keep_free_mb=0, source=r["copy"])
        self.assertTrue(back["ok"], back)
        self.assertEqual(listing(src), before)
        rows = archive.read_manifest(self.manifest)
        self.assertEqual((rows[-1]["kind"], rows[-1]["archive"], rows[-1]["read_from"]), ("restored", row["archive"], r["copy"]))
        self.assertEqual(archive.on_drive(rows), [])

    def test_restore_refuses_rather_than_overwrite_or_fill_the_disk(self):
        src = self.work_folder()
        archive.archive_one(self.cand(src), self.drive, manifest=self.manifest)
        row = archive.read_manifest(self.manifest)[0]
        self.assertIn("free", archive.restore(row, manifest=self.manifest, keep_free_mb=10 ** 12)["why"])
        self.assertFalse(src.exists())
        mk(src / "new-work.txt", b"mine")
        self.assertIn("already exists", archive.restore(row, manifest=self.manifest, keep_free_mb=0)["why"])
        self.assertEqual((src / "new-work.txt").read_bytes(), b"mine")
        gone = dict(row, archive=str(self.tmp / "unplugged" / "2026-09-17.tar"), source=str(self.root / "other"))
        self.assertIn("not connected", archive.restore(gone, manifest=self.manifest, keep_free_mb=0)["why"])
        self.assertEqual([r["kind"] for r in archive.read_manifest(self.manifest)], ["archived"])
        self.assertEqual([n for n in os.listdir(self.root) if n.startswith(".guardian-restore")], [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
