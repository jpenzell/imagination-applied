#!/usr/bin/env python3
"""Tests for the disk layer. Builds a fake home directory; never touches the real one."""
import os
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
        self.home = self.tmp / "home"
        # safe tier
        mk(self.home / "Library/Application Support/Google/Chrome/Default/Cache/data_0", 2048)
        mk(self.home / "Library/Application Support/Google/Chrome/Profile 1/Code Cache/js/0", 1024)
        mk(self.home / "Library/Application Support/Claude/Cache/blob", 3072)
        mk(self.home / ".npm/_cacache/index-v5/a", 512)
        # safe-old tier: one old, one fresh
        mk(self.home / "Library/Logs/old.log", 1024, age_days=45)
        mk(self.home / "Library/Logs/fresh.log", 1024, age_days=1)
        mk(self.home / ".Trash/old-thing", 2048, age_days=40)
        # review / report tiers
        mk(self.home / ".claude/projects/p1/session.jsonl", 4096)
        mk(self.home / ".codex/sessions/2026/s.jsonl", 8192)
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
        self.assertEqual(self.by(rows, "Codex sessions")["mb"], 8)
        self.assertEqual(self.by(rows, "Downloads")["tier"], "report")
        self.assertEqual(rows[0]["name"], "Downloads", "sorted biggest first")

    def test_symlinked_location_is_ignored(self):
        rows = self.rows()
        self.assertEqual(self.by(rows, "Homebrew cache")["paths"], [])

    def test_reclaimable_excludes_running_apps(self):
        rows = self.rows()
        self.assertEqual(scratch.reclaimable_mb(rows, ("safe",)), 3 + 3 + 0)   # chrome + claude + npm(0.5 -> 0)
        self.assertEqual(scratch.reclaimable_mb(rows, ("safe",), running={"Google Chrome"}), 3)

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
        r = scratch.reclaim("safe", self.home, dry_run=False, running={"Google Chrome", "Claude"})
        self.assertTrue((self.home / "Library/Application Support/Google/Chrome/Default/Cache/data_0").exists())
        self.assertTrue((self.home / "Library/Application Support/Claude/Cache/blob").exists())
        self.assertFalse((self.home / ".npm/_cacache/index-v5/a").exists())
        self.assertEqual({s["name"] for s in r["skipped"]}, {"Chrome caches", "Claude desktop caches"})

    def test_safe_old_only_deletes_old_entries(self):
        scratch.reclaim("safe-old", self.home, dry_run=False)
        self.assertFalse((self.home / "Library/Logs/old.log").exists())
        self.assertTrue((self.home / "Library/Logs/fresh.log").exists())
        self.assertFalse((self.home / ".Trash/old-thing").exists())

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


if __name__ == "__main__":
    unittest.main(verbosity=1)
