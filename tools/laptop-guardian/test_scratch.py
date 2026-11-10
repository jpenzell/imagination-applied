#!/usr/bin/env python3
"""Tests for the disk layer. Builds a fake home directory; never touches the real one."""
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import scratch


def mk(path: Path, size_kb: int = 4, age_days: float = 0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * (size_kb * 1024))
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))


class ScratchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        # every run builds ~50 MB of fake home; 156 runs once left 7.8 GB in /var/folders
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        # safe tier
        mk(self.home / "Library/Application Support/Google/Chrome/Default/Cache/data_0", 2048)
        mk(self.home / "Library/Application Support/Google/Chrome/Profile 1/Code Cache/js/0", 1024)
        mk(self.home / "Library/Application Support/Claude/Cache/blob", 3072)
        mk(self.home / ".npm/_cacache/index-v5/a", 512)
        # safe-old tier: one old, one fresh
        mk(self.home / "Library/Logs/old.log", 1024, age_days=45)
        mk(self.home / "Library/Logs/fresh.log", 1024, age_days=1)
        # an app log folder with fresh mtime but old files inside: files go, folder stays
        mk(self.home / "Library/Logs/Claude/mcp-server-old.log", 1024, age_days=60)
        mk(self.home / "Library/Logs/Claude/mcp.log", 1024, age_days=0)
        # Cowork session data inside the Claude app folder: report tier, never touched
        mk(self.home / "Library/Application Support/Claude/local-agent-mode-sessions/s1/vm.img", 4096)
        mk(self.home / ".Trash/old-thing", 2048, age_days=40)
        # review / report tiers
        mk(self.home / ".claude/projects/p1/session.jsonl", 4096)
        mk(self.home / ".codex/sessions/2026/s.jsonl", 8192)
        mk(self.home / ".codex/thread_history_1.sqlite", 4096)
        # the ChatGPT app embeds Codex: its caches are safe but wait for Codex OR ChatGPT to quit
        mk(self.home / "Library/Caches/Codex/Default/Cache/data_1", 2048)
        mk(self.home / "Library/Caches/com.openai.codex/org.sparkle-project.Sparkle/update.zip", 1024)
        mk(self.home / ".codex/computer-use/Codex Computer Use.app/Contents/MacOS/svc", 64)
        mk(self.home / "Downloads/big.zip", 16384)
        # a symlink that points outside home: must never be followed or deleted through
        self.outside = self.tmp / "outside"
        mk(self.outside / "secret", 64)
        (self.home / "Library/Caches").mkdir(parents=True, exist_ok=True)
        os.symlink(self.outside, self.home / "Library/Caches/Homebrew")

    def rows(self):
        return scratch.census(self.home)

    def by(self, rows, name):
        return next(r for r in rows if r["name"] == name)

    def test_census_measures_and_tiers(self):
        rows = self.rows()
        self.assertEqual(self.by(rows, "Chrome caches")["mb"], 3)
        self.assertEqual(self.by(rows, "Chrome caches")["tier"], "safe")
        self.assertEqual(self.by(rows, "Claude desktop caches")["mb"], 3)
        self.assertEqual(self.by(rows, "Claude Code transcripts")["tier"], "review")
        self.assertEqual(self.by(rows, "Codex sessions")["mb"], 12, "thread-history sqlite counts as sessions")
        self.assertEqual(self.by(rows, "Codex app caches")["mb"], 3)
        self.assertEqual(self.by(rows, "Other app caches")["mb"], 0, "named caches are not counted twice")
        self.assertEqual(self.by(rows, "Downloads")["tier"], "report")
        self.assertEqual(rows[0]["name"], "Downloads", "sorted biggest first")

    def test_symlinked_location_is_ignored(self):
        rows = self.rows()
        self.assertEqual(self.by(rows, "Homebrew cache")["paths"], [])

    def test_reclaimable_excludes_running_apps(self):
        rows = self.rows()
        self.assertEqual(scratch.reclaimable_mb(rows, ("safe",)), 3 + 3 + 3 + 0)   # chrome + claude + codex + npm(0.5 -> 0)
        self.assertEqual(scratch.reclaimable_mb(rows, ("safe",), running={"Google Chrome"}), 6)
        self.assertEqual(scratch.reclaimable_mb(rows, ("safe",), running={"ChatGPT"}), 6,
                         "the Codex caches wait for either Codex or the ChatGPT app that embeds it")
        self.assertEqual(scratch.reclaimable_mb(rows, ("safe",), running={"Codex"}), 6)

    def test_dry_run_deletes_nothing(self):
        before = sum(1 for _ in self.home.rglob("*"))
        r = scratch.reclaim("safe", self.home, dry_run=True)
        self.assertTrue(r["dry_run"])
        self.assertGreaterEqual(r["freed_mb"], 6)
        self.assertEqual(sum(1 for _ in self.home.rglob("*")), before)

    def test_safe_reclaim_clears_caches_but_keeps_data(self):
        r = scratch.reclaim("safe", self.home, dry_run=False)
        self.assertFalse((self.home / "Library/Application Support/Google/Chrome/Default/Cache/data_0").exists())
        self.assertTrue((self.home / "Library/Application Support/Google/Chrome/Default/Cache").is_dir(),
                        "the cache directory itself stays; only contents go")
        self.assertFalse((self.home / "Library/Application Support/Claude/Cache/blob").exists())
        self.assertTrue((self.home / ".claude/projects/p1/session.jsonl").exists())
        self.assertTrue((self.home / ".codex/sessions/2026/s.jsonl").exists())
        self.assertTrue((self.home / "Downloads/big.zip").exists())
        self.assertTrue((self.outside / "secret").exists())
        self.assertEqual(r["skipped"], [])

    def test_running_app_caches_are_skipped(self):
        r = scratch.reclaim("safe", self.home, dry_run=False, running={"ChatGPT"})
        self.assertIn({"name": "Codex app caches", "why": "ChatGPT is running"}, r["skipped"])
        self.assertTrue((self.home / "Library/Caches/Codex/Default/Cache/data_1").exists())
        self.assertFalse((self.home / "Library/Application Support/Google/Chrome/Default/Cache/data_0").exists())
        self.assertTrue((self.home / ".codex/thread_history_1.sqlite").exists())
        mk(self.home / "Library/Application Support/Google/Chrome/Default/Cache/data_0", 2048)
        mk(self.home / "Library/Application Support/Claude/Cache/blob", 3072)
        mk(self.home / ".npm/_cacache/index-v5/a", 512)
        r = scratch.reclaim("safe", self.home, dry_run=False, running={"Google Chrome", "Claude"})
        self.assertTrue((self.home / "Library/Application Support/Google/Chrome/Default/Cache/data_0").exists())
        self.assertTrue((self.home / "Library/Application Support/Claude/Cache/blob").exists())
        self.assertFalse((self.home / ".npm/_cacache/index-v5/a").exists())
        self.assertFalse((self.home / "Library/Caches/Codex/Default/Cache/data_1").exists())
        self.assertEqual({s["name"] for s in r["skipped"]}, {"Chrome caches", "Claude desktop caches"})

    def test_safe_old_only_deletes_old_entries(self):
        scratch.reclaim("safe-old", self.home, dry_run=False)
        self.assertFalse((self.home / "Library/Logs/old.log").exists())
        self.assertTrue((self.home / "Library/Logs/fresh.log").exists())
        self.assertFalse((self.home / ".Trash/old-thing").exists())
        self.assertFalse((self.home / "Library/Logs/Claude/mcp-server-old.log").exists(), "old file inside a fresh folder")
        self.assertTrue((self.home / "Library/Logs/Claude/mcp.log").exists())
        self.assertTrue((self.home / "Library/Logs/Claude").is_dir(), "log folders are left for the app")

    def test_cowork_and_ai_app_data_are_report_tier_and_untouched(self):
        rows = self.rows()
        self.assertEqual(self.by(rows, "Cowork sessions / VM")["tier"], "report")
        self.assertEqual(self.by(rows, "Cowork sessions / VM")["mb"], 4)
        for name in ("Claude desktop data", "ChatGPT desktop data", "Codex app data", "Claude Code other data"):
            self.assertEqual(self.by(rows, name)["tier"], "report")
        for name in ("Claude Code transcripts", "Codex sessions"):
            self.assertEqual(self.by(rows, name)["tier"], "review")
        scratch.reclaim("safe", self.home, dry_run=False)
        scratch.reclaim("safe-old", self.home, dry_run=False)
        self.assertTrue((self.home / "Library/Application Support/Claude/local-agent-mode-sessions/s1/vm.img").exists())

    def test_census_for_one_app_measures_only_its_caches(self):
        """Used while that app is closed and waiting to be reopened: it must be quick and narrow."""
        rows = scratch.census(self.home, only_app="ChatGPT")
        self.assertEqual({r["name"] for r in rows}, {"Codex app caches", "ChatGPT desktop caches"})
        self.assertEqual(sum(r["mb"] for r in rows), 3)
        r = scratch.reclaim("safe", self.home, dry_run=False, rows=rows)
        self.assertFalse((self.home / "Library/Caches/Codex/Default/Cache/data_1").exists())
        self.assertTrue((self.home / "Library/Application Support/Google/Chrome/Default/Cache/data_0").exists(),
                        "Chrome's caches are not ChatGPT's")
        self.assertTrue((self.home / ".codex/thread_history_1.sqlite").exists())
        self.assertEqual(scratch.census(self.home, only_app="Nonexistent"), [])
        nothing = scratch.reclaim("safe", self.home, dry_run=False, rows=[])
        self.assertEqual(nothing["freed_mb"], 0, "an empty row list must not fall back to a full census")
        self.assertTrue((self.home / "Library/Application Support/Google/Chrome/Default/Cache/data_0").exists())

    def test_rows_never_count_a_byte_twice(self):
        """Claude's folder holds its caches and the Cowork VM; Application Support holds Claude's
        folder. Each remainder row is its folder minus what is named elsewhere."""
        mk(self.home / "Library/Application Support/Claude/config/settings.bin", 2048)
        mk(self.home / "Library/Application Support/SomeApp/data.bin", 5120)
        mk(self.home / "Library/Containers/com.example.app/Data/blob", 1024)
        mk(self.home / "Documents/report.docx", 7168)
        rows = self.rows()
        self.assertEqual(self.by(rows, "Claude desktop caches")["mb"], 3)
        self.assertEqual(self.by(rows, "Cowork sessions / VM")["mb"], 4)
        self.assertEqual(self.by(rows, "Claude desktop data")["mb"], 2, "3 + 4 + 2 on disk; only the 2 is 'other'")
        self.assertEqual(self.by(rows, "Other Application Support")["mb"], 5,
                         "Claude's whole folder and Chrome's caches are named elsewhere")
        self.assertEqual(self.by(rows, "App containers")["mb"], 1)
        self.assertEqual(self.by(rows, "Documents")["mb"], 7)
        under_support = sum(self.by(rows, n)["mb"] for n in (
            "Claude desktop caches", "Cowork sessions / VM", "Claude desktop data",
            "Other Application Support", "Chrome caches"))
        self.assertEqual(under_support, scratch.du_kb(self.home / "Library/Application Support") // 1024)

    def test_guard_apps_lists_every_app_that_guards_a_cache(self):
        self.assertLessEqual({"Google Chrome", "Claude", "ChatGPT", "Codex", "Dropbox"}, scratch.guard_apps())

    def test_system_buckets_measure_temp_and_swap_outside_home(self):
        temp, vm = self.tmp / "T", self.tmp / "VM"
        mk(temp / "tmpabc12345/home/big.bin", 6144)
        mk(vm / "swapfile0", 2048)
        mk(vm / "swapfile1", 1024)
        got = {b["name"]: b["mb"] for b in scratch.system_buckets(temp_dir=temp, vm_dir=vm)}
        self.assertEqual((got["Temporary files"], got["Swap files"]), (6, 3))

    def test_ledger_names_what_ate_the_disk_and_admits_what_it_cannot_see(self):
        rows = [{"name": "Codex sessions", "mb": 9600}, {"name": "Chrome caches", "mb": 1600}]
        old = scratch.ledger_entry(rows, [{"name": "Temporary files", "mb": 90}], 20.7, 1_000_000)
        rows2 = [{"name": "Codex sessions", "mb": 9650}, {"name": "Chrome caches", "mb": 400}]
        new = scratch.ledger_entry(rows2, [{"name": "Temporary files", "mb": 7900}], 12.1, 1_007_200)
        d = scratch.ledger_diff(old, new)
        self.assertEqual(d["used_mb"], round(8.6e9 / 1048576))
        self.assertEqual(d["changes"][0], ("Temporary files", 7810))
        self.assertEqual(d["changes"][1], ("Chrome caches", -1200))
        self.assertEqual(d["unexplained_mb"], d["used_mb"] - (7810 - 1200 + 50))
        text = "\n".join(scratch.render_ledger_diff(d))
        self.assertIn("free space fell 8.0 GB", text)
        self.assertIn("+7.6 GB  Temporary files", text)
        self.assertIn("-1.2 GB  Chrome caches", text)
        self.assertIn("+1.5 GB  not explained by anything measured", text)
        self.assertNotIn("Codex sessions", text, "50 MB is below the noise floor")
        same = scratch.render_ledger_diff(scratch.ledger_diff(old, old))
        self.assertIn("nothing measured changed", "\n".join(same))

    def test_tmutil_listing_parses(self):
        out = ("Snapshots for disk /:\n"
               "com.apple.TimeMachine.2026-11-09-120000.local\n"
               "com.apple.TimeMachine.2026-11-10-080000.local\n")
        self.assertEqual(len(scratch.parse_local_snapshots(out)), 2)
        self.assertEqual(scratch.parse_local_snapshots("Snapshots for disk /:\n"), [])
        self.assertEqual(scratch.parse_local_snapshots(""), [])

    def test_review_tiers_cannot_be_reclaimed(self):
        with self.assertRaises(ValueError):
            scratch.reclaim("review", self.home, dry_run=False)
        with self.assertRaises(ValueError):
            scratch.reclaim("report", self.home, dry_run=False)

    def test_render_mentions_reclaimable_and_running(self):
        text = scratch.render(self.rows(), [], 12.5, running={"Claude"})
        self.assertIn("Disk free: 12.5 GB", text)
        self.assertIn("Claude is running; skipped", text)
        self.assertIn("Reclaimable now:", text)


class BlockedTests(unittest.TestCase):
    """macOS can refuse a background program the Documents, Downloads and Desktop folders.
    The first real Mac's agent wrote 'Documents: 0' into its ledger; the folder held 41 GB."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        mk(self.home / "Documents/Codex/2026-09-23/big.bin", 3072)
        mk(self.home / "Downloads/video.mp4", 2048)
        self.blocked = self.home / "Documents"

        def cleanup():
            os.chmod(self.blocked, 0o755)
            shutil.rmtree(self.tmp, ignore_errors=True)
        self.addCleanup(cleanup)

    def test_a_folder_that_cannot_be_read_is_unknown_not_empty(self):
        full = scratch.ledger_entry(scratch.census(self.home), [], 20.0, 1_000_000)
        self.assertEqual((full["items"]["Documents"], full["items"]["Downloads"]), (3, 2))
        self.assertNotIn("unreadable", full)
        os.chmod(self.blocked, 0o000)
        if scratch.readable(self.blocked):
            self.skipTest("running as a user who can read anything")
        rows = {r["name"]: r for r in scratch.census(self.home)}
        self.assertTrue(rows["Documents"]["unreadable"])
        self.assertFalse(rows["Downloads"]["unreadable"])
        self.assertFalse(rows["Trash"]["unreadable"], "a place that does not exist is simply absent")
        blind = scratch.ledger_entry(list(rows.values()), [], 20.0, 1_003_600)
        self.assertNotIn("Documents", blind["items"])
        self.assertEqual(blind["unreadable"], ["Documents"])
        self.assertIn("the size is not known", scratch.render(list(rows.values())))
        # comparing a full snapshot with a blind one must not report 3 MB "freed"
        for old, new in ((full, blind), (blind, full)):
            diff = scratch.ledger_diff(old, new)
            self.assertEqual(diff["changes"], [])
            self.assertEqual(diff["unreadable"], ["Documents"])
            self.assertIn("not compared", scratch.render_ledger_diff(diff)[-1])
        mk(self.home / "Downloads/more.mp4", 5120)
        later = scratch.ledger_entry(scratch.census(self.home), [], 19.9, 1_007_200)
        self.assertEqual(scratch.ledger_diff(blind, later)["changes"], [("Downloads", 5)])


if __name__ == "__main__":
    unittest.main(verbosity=1)
