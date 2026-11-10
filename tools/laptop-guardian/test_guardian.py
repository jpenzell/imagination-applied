#!/usr/bin/env python3
"""Policy-engine tests. Run: python3 test_guardian.py  (stdlib unittest, no deps).

These feed synthetic macOS-style process tables through classify() and Engine
so the decisions can be checked without a Mac, pressure, or a real kill.
"""
import json
import os
import unittest

import guardian as g

UID = os.getuid()
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HELPER = ("/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/"
          "Versions/142/Helpers/Google Chrome Helper (Renderer).app/Contents/MacOS/Google Chrome Helper (Renderer)")
PW_CHROME = "/Users/j/Library/Caches/ms-playwright/chromium-1200/chrome-mac/Chromium.app/Contents/MacOS/Chromium"


def P(pid, comm, args=None, ppid=1, cpu=0.0, rss_mb=100, age=60, cputime=0, uid=UID):
    return g.Proc(pid, ppid, pid, uid, cpu, int(rss_mb * 1024), age, cputime, comm, args or comm)


def sample(level=1, free=60, disk=100, ts=1_000_000.0):
    return {"ts": ts, "pressure_level": level, "free_pct": free, "disk_free_gb": disk,
            "cpu_speed_limit": 100}


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = g.load_config(g.Path("/nonexistent"))

    def test_chrome_helpers_fold_into_chrome(self):
        procs = [P(10, CHROME), P(11, HELPER, HELPER + " --type=renderer --lang=en", ppid=10, rss_mb=900),
                 P(12, HELPER, HELPER + " --type=renderer", ppid=10, rss_mb=700)]
        g.classify(procs, self.cfg, UID)
        self.assertEqual(procs[0].cls, "browser")
        self.assertEqual(procs[1].cls, "browser/renderer")
        self.assertEqual({p.key for p in procs}, {"Google Chrome"})
        groups = g.aggregate(procs, self.cfg)
        self.assertEqual(groups[0]["rss_mb"], 1700)
        self.assertEqual(groups[0]["n"], 3)

    def test_playwright_chrome_is_automation_and_separate(self):
        procs = [P(10, CHROME), P(20, PW_CHROME, PW_CHROME + " --headless --remote-debugging-pipe"),
                 P(21, PW_CHROME, PW_CHROME + " --type=renderer", ppid=20, rss_mb=500)]
        g.classify(procs, self.cfg, UID)
        self.assertEqual(procs[0].cls, "browser")
        self.assertEqual(procs[1].cls, "automation_browser")
        self.assertEqual(procs[2].cls, "automation_browser")
        self.assertIn("[automation pid 20]", procs[2].key)
        self.assertNotEqual(procs[0].key, procs[1].key)

    def test_main_chrome_with_remote_debugging_is_not_automation(self):
        procs = [P(10, CHROME, CHROME + " --remote-debugging-port=9222")]
        g.classify(procs, self.cfg, UID)
        self.assertEqual(procs[0].cls, "debug_browser")

    def test_agent_cli_vs_desktop_app(self):
        procs = [P(30, "/opt/homebrew/bin/claude", "claude --resume abc"),
                 P(31, "/Applications/Claude.app/Contents/MacOS/Claude"),
                 P(32, "/usr/bin/python3", "python3 /Users/j/Documents/Codex/2026/run.py"),
                 P(33, "/opt/homebrew/bin/node", "node /Users/j/.npm-global/bin/codex exec")]
        g.classify(procs, self.cfg, UID)
        self.assertEqual(procs[0].cls, "agent_session")
        self.assertEqual(procs[0].key, "agent:claude")
        self.assertEqual(procs[1].cls, "ai_app", "the Claude desktop app is tracked as an AI app, not a CLI session")
        self.assertEqual(procs[2].cls, "other", "a script in a folder named Codex is not a Codex session")
        self.assertEqual(procs[3].cls, "agent_session")
        self.assertEqual(procs[3].key, "agent:codex")

    def test_mcp_servers_fold_under_their_ai_app_and_orphans_are_flagged(self):
        claude_app = "/Applications/Claude.app/Contents/MacOS/Claude"
        procs = [P(31, claude_app),
                 P(32, "/opt/homebrew/bin/node", "node /Users/j/mcp/josh-content/index.js", ppid=31, rss_mb=120),
                 P(33, "/opt/homebrew/bin/node", "node /x/node_modules/.bin/mcp-server-dropbox", ppid=32, rss_mb=80),
                 P(34, "/opt/homebrew/bin/node", "node /Users/j/.npm/_npx/abc/mcp-server-github", ppid=1, rss_mb=90),
                 P(35, "/opt/homebrew/bin/node", "node /Users/j/site/server.js", ppid=1)]
        g.classify(procs, self.cfg, UID)
        self.assertEqual(procs[0].cls, "ai_app")
        self.assertEqual(procs[1].cls, "mcp_server")
        self.assertEqual(procs[2].cls, "mcp_server", "grandchildren of the app fold in too")
        self.assertEqual(procs[1].key, "Claude helpers (MCP servers)")
        self.assertEqual(procs[3].cls, "mcp_orphan", "parent gone + 'mcp' in the command = orphaned server")
        self.assertEqual(procs[4].cls, "other", "a plain node server with a dead parent is not an MCP orphan")
        groups = {gr["key"]: gr for gr in g.aggregate(procs, self.cfg)}
        self.assertEqual(groups["Claude helpers (MCP servers)"]["rss_mb"], 200)

    def test_word_boundaries_for_dev_servers(self):
        procs = [P(40, "/opt/homebrew/bin/node", "node /app/node_modules/.bin/vite dev"),
                 P(41, "/opt/homebrew/bin/node", "node /Users/j/invites/server.js")]
        g.classify(procs, self.cfg, UID)
        self.assertEqual(procs[0].cls, "dev_server")
        self.assertEqual(procs[1].cls, "other")

    def test_other_users_are_foreign_and_watched_names_surface(self):
        procs = [P(50, "/usr/sbin/mds_stores", uid=UID + 1),
                 P(51, "/Applications/Scratch Desktop.app/Contents/MacOS/Scratch Desktop")]
        g.classify(procs, self.cfg, UID)
        self.assertEqual(procs[0].cls, "foreign")
        self.assertEqual(procs[1].cls, "watched")

    def test_quiet_mode_when_presenting(self):
        procs = [P(60, "/Applications/Keynote.app/Contents/MacOS/Keynote")]
        g.classify(procs, self.cfg, UID)
        self.assertEqual(g.quiet_mode(procs, self.cfg), "Keynote")
        self.assertEqual(g.quiet_mode([P(61, "/bin/zsh")], self.cfg), "")


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.cfg = g.load_config(g.Path("/nonexistent"))
        self.cfg["interval_seconds"] = 30

    def run_steps(self, engine, make_procs, samples):
        """make_procs(i, now) -> procs ; samples: list of sample dicts. Returns all decisions."""
        out = []
        for i, s in enumerate(samples):
            procs = g.classify(make_procs(i, s["ts"]), self.cfg, UID)
            out += engine.step(s, procs, now=s["ts"])
        return out

    def test_no_decisions_when_calm(self):
        e = g.Engine(self.cfg)
        d = self.run_steps(e, lambda i, now: [P(10, CHROME, rss_mb=4000)],
                           [sample(ts=1e6 + 30 * i) for i in range(10)])
        self.assertEqual([x for x in d if x.action != "log"], [])

    def test_episode_start_end_and_notification_names_offender(self):
        e = g.Engine(self.cfg)
        samples = [sample(level=2, free=10, ts=1e6), sample(level=4, free=4, ts=1e6 + 30),
                   sample(level=1, free=40, ts=1e6 + 60)]
        d = self.run_steps(e, lambda i, now: [P(10, CHROME, rss_mb=6000), P(11, "/bin/zsh")], samples)
        kinds = [(x.action, x.cls) for x in d]
        self.assertIn(("log", "episode"), kinds)
        self.assertEqual(sum(1 for x in d if x.action == "notify" and x.cls == "pressure"), 1,
                         "one pressure notification per cooldown, not one per sample")
        ended = [x for x in d if x.cls == "episode" and "ended" in x.reason]
        self.assertEqual(len(ended), 1)
        self.assertIn("Google Chrome 6000MB", ended[0].reason)
        self.assertIn("peak critical", ended[0].reason)
        self.assertEqual(e.episodes_today, 1)

    def test_orphaned_automation_chrome_is_killed_after_idle(self):
        e = g.Engine(self.cfg)
        # parent gone (ppid 1), 0% cpu: cputime never advances
        mk = lambda i, now: [P(20, PW_CHROME, PW_CHROME + " --headless", ppid=1, age=3600 + 30 * i, cputime=5)]
        samples = [sample(ts=1e6 + 30 * i) for i in range(25)]   # 12 minutes
        d = self.run_steps(e, mk, samples)
        kills = [x for x in d if x.action == "kill"]
        self.assertEqual(len(kills), 1)
        self.assertEqual(kills[0].proc.pid, 20)
        self.assertIn("abandoned", kills[0].reason)
        self.assertEqual(kills[0].cls, "automation_browser")

    def test_orphaned_mcp_server_is_killed_after_idle(self):
        e = g.Engine(self.cfg)
        mk = lambda i, now: [P(34, "/opt/homebrew/bin/node", "node /x/mcp-server-github", ppid=1,
                               age=3600 + 30 * i, cputime=2)]
        d = self.run_steps(e, mk, [sample(ts=1e6 + 30 * i) for i in range(25)])
        kills = [x for x in d if x.action == "kill"]
        self.assertEqual(len(kills), 1)
        self.assertEqual(kills[0].cls, "mcp_orphan")
        self.assertIn("MCP server abandoned", kills[0].reason)

    def test_automation_chrome_with_live_parent_is_left_alone(self):
        e = g.Engine(self.cfg)
        mk = lambda i, now: [P(5, "/opt/homebrew/bin/node", "node agent.js"),
                             P(20, PW_CHROME, PW_CHROME + " --headless", ppid=5, age=3600 + 30 * i, cputime=5)]
        d = self.run_steps(e, mk, [sample(ts=1e6 + 30 * i) for i in range(25)])
        self.assertEqual([x for x in d if x.action == "kill"], [])

    def test_busy_orphan_automation_chrome_is_left_alone(self):
        e = g.Engine(self.cfg)
        # cputime grows 15s per 30s sample = 50% cpu: not idle
        mk = lambda i, now: [P(20, PW_CHROME, PW_CHROME + " --headless", ppid=1, age=3600 + 30 * i, cputime=15 * i)]
        d = self.run_steps(e, mk, [sample(ts=1e6 + 30 * i) for i in range(25)])
        self.assertEqual([x for x in d if x.action == "kill"], [])

    def test_runaway_cpu_gets_reniced_once(self):
        e = g.Engine(self.cfg)
        # 100% cpu: cputime +30 per 30s sample; a bare python script, not a GUI app
        mk = lambda i, now: [P(70, "/usr/bin/python3", "python3 loop.py", ppid=400, age=100 + 30 * i, cputime=30 * i, cpu=100)]
        d = self.run_steps(e, mk, [sample(ts=1e6 + 30 * i) for i in range(30)])   # 15 min
        ren = [x for x in d if x.action == "renice"]
        self.assertEqual(len(ren), 1)
        self.assertEqual(ren[0].proc.pid, 70)

    def test_gui_app_never_reniced_or_killed(self):
        e = g.Engine(self.cfg)
        mk = lambda i, now: [P(10, CHROME, ppid=1, age=100 + 30 * i, cputime=30 * i, cpu=100, rss_mb=9000)]
        d = self.run_steps(e, mk, [sample(level=4, free=3, ts=1e6 + 30 * i) for i in range(30)])
        self.assertEqual([x for x in d if x.action in ("renice", "kill")], [])

    def test_fat_renderer_under_pressure_notifies_not_kills_by_default(self):
        e = g.Engine(self.cfg)
        mk = lambda i, now: [P(10, CHROME), P(11, HELPER, HELPER + " --type=renderer", ppid=10, rss_mb=3000)]
        d = self.run_steps(e, mk, [sample(level=2, free=9, ts=1e6 + 30 * i) for i in range(15)])
        rend = [x for x in d if x.cls == "renderer"]
        self.assertEqual(len(rend), 1)
        self.assertEqual(rend[0].action, "notify")
        self.cfg["renderers"]["kill_under_pressure"] = True
        e2 = g.Engine(self.cfg)
        d2 = self.run_steps(e2, mk, [sample(level=2, free=9, ts=1e6 + 30 * i) for i in range(15)])
        self.assertEqual([x.action for x in d2 if x.cls == "renderer"], ["kill"])

    def test_critical_pressure_reclaims_model_worker_after_two_strikes(self):
        e = g.Engine(self.cfg)
        mk = lambda i, now: [P(80, "/opt/homebrew/bin/ollama", "ollama runner --model x", rss_mb=14000)]
        d = self.run_steps(e, mk, [sample(level=4, free=3, ts=1e6 + 30 * i) for i in range(3)])
        kills = [x for x in d if x.action == "kill"]
        self.assertEqual(len(kills), 1)
        self.assertEqual(kills[0].cls, "model_worker")
        # same worker at warn (not critical) pressure: never
        e2 = g.Engine(self.cfg)
        d2 = self.run_steps(e2, mk, [sample(level=2, free=12, ts=1e6 + 30 * i) for i in range(5)])
        self.assertEqual([x for x in d2 if x.action == "kill"], [])

    def test_stale_agent_session_notifies_by_default(self):
        e = g.Engine(self.cfg)
        mk = lambda i, now: [P(30, "/opt/homebrew/bin/claude", "claude", ppid=300, age=30 * 3600 + 30 * i, cputime=10)]
        d = self.run_steps(e, mk, [sample(ts=1e6 + 30 * i) for i in range(35)])   # 17 min idle
        st = [x for x in d if x.cls == "agent_session"]
        self.assertEqual([x.action for x in st], ["notify"])
        self.cfg["agent_sessions"]["kill_when_stale"] = True
        d2 = self.run_steps(g.Engine(self.cfg), mk, [sample(ts=1e6 + 30 * i) for i in range(35)])
        self.assertEqual([x.action for x in d2 if x.cls == "agent_session"], ["kill"])

    def test_pid_recycled_resets_tracking(self):
        e = g.Engine(self.cfg)
        # 20 samples idle orphan, then the pid comes back as a brand-new process (age resets)
        def mk(i, now):
            age = 3600 + 30 * i if i < 20 else 5 + 30 * (i - 20)
            return [P(20, PW_CHROME, PW_CHROME + " --headless", ppid=1, age=age, cputime=5)]
        d = self.run_steps(e, mk, [sample(ts=1e6 + 30 * i) for i in range(22)])
        self.assertEqual(sum(1 for x in d if x.action == "kill"), 0,
                         "idle clock must restart when the pid is reused before the limit")

    def test_disk_and_thermal_warnings(self):
        e = g.Engine(self.cfg)
        s = sample(disk=9, ts=1e6)
        s["cpu_speed_limit"] = 60
        d = e.step(s, [], now=1e6)
        self.assertEqual({(x.cls, x.action) for x in d}, {("disk", "reclaim"), ("thermal", "notify")})
        d2 = e.step(sample(disk=9, ts=1e6 + 3600), [], now=1e6 + 3600)
        self.assertEqual([x for x in d2 if x.cls == "disk"], [], "disk reclaim has a long cooldown")


class ApplyTests(unittest.TestCase):
    """apply_decisions must respect mode, quiet, protect and dry-run. Uses a temp log dir."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.old = (g.LOG_DIR, g.EVENTS_PATH)
        g.LOG_DIR = g.Path(self.tmp)
        g.EVENTS_PATH = g.LOG_DIR / "events.jsonl"
        self.cfg = g.load_config(g.Path("/nonexistent"))
        self.cfg["notify"] = False
        self.killed = []
        g.terminate = lambda p, grace=15: self.killed.append(p.pid) or "terminated"
        self.proc = P(20, PW_CHROME, PW_CHROME + " --headless")
        g.classify([self.proc], self.cfg, UID)

    def tearDown(self):
        g.LOG_DIR, g.EVENTS_PATH = self.old

    def kill_decision(self):
        return [g.Decision("kill", self.proc, "test", "automation_browser", "warn")]

    def test_nudge_mode_never_kills(self):
        self.cfg["mode"] = "nudge"
        r = g.apply_decisions(self.kill_decision(), self.cfg)
        self.assertEqual(r[0]["result"], "would kill")
        self.assertEqual(self.killed, [])

    def test_act_mode_kills_safe_class(self):
        self.cfg["mode"] = "act"
        r = g.apply_decisions(self.kill_decision(), self.cfg)
        self.assertEqual(r[0]["result"], "terminated")
        self.assertEqual(self.killed, [20])

    def test_dry_run_overrides_act(self):
        self.cfg["mode"] = "act"
        r = g.apply_decisions(self.kill_decision(), self.cfg, dry_run=True)
        self.assertEqual(r[0]["result"], "would kill (dry-run)")
        self.assertEqual(self.killed, [])

    def test_protected_app_is_never_killed(self):
        self.cfg["mode"] = "act"
        chrome = P(10, CHROME)
        g.classify([chrome], self.cfg, UID)
        r = g.apply_decisions([g.Decision("kill", chrome, "test", "browser", "crit")], self.cfg)
        self.assertEqual(r[0]["result"], "protected")
        self.assertEqual(self.killed, [])

    def test_quiet_holds_kills_except_abandoned_automation(self):
        self.cfg["mode"] = "act"
        worker = P(80, "/opt/homebrew/bin/ollama", "ollama runner", rss_mb=14000)
        g.classify([worker], self.cfg, UID)
        r = g.apply_decisions([g.Decision("kill", worker, "test", "model_worker", "crit")] + self.kill_decision(),
                              self.cfg, quiet="Keynote")
        self.assertEqual(r[0]["result"], "held (quiet: Keynote)")
        self.assertEqual(r[1]["result"], "terminated")
        self.assertEqual(self.killed, [20])

    def test_events_are_logged(self):
        self.cfg["mode"] = "observe"
        g.apply_decisions(self.kill_decision(), self.cfg)
        lines = g.EVENTS_PATH.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn('"kind": "decision"', lines[0])



class AutopilotTests(unittest.TestCase):
    """Bounded self-tuning, config history/undo, and the hygiene schedule."""

    def setUp(self):
        import tempfile
        self.tmp = g.Path(tempfile.mkdtemp())
        self.saved = (g.CONFIG_DIR, g.CONFIG_PATH, g.CONFIG_HISTORY, g.LOG_DIR, g.EVENTS_PATH)
        g.CONFIG_DIR = self.tmp / "cfg"
        g.CONFIG_PATH = g.CONFIG_DIR / "config.json"
        g.CONFIG_HISTORY = g.CONFIG_DIR / "config-history.jsonl"
        g.LOG_DIR = self.tmp / "logs"
        g.EVENTS_PATH = g.LOG_DIR / "events.jsonl"

    def tearDown(self):
        g.CONFIG_DIR, g.CONFIG_PATH, g.CONFIG_HISTORY, g.LOG_DIR, g.EVENTS_PATH = self.saved

    def test_split_tuning_only_auto_applies_bounded_numeric_thresholds(self):
        suggestion = {
            "notify_cooldown_seconds": 1800,                 # tunable, in range
            "cpu": {"sustain_seconds": 900, "renice_to": 19},  # first tunable, second not
            "renderers": {"memory_mb": 50000, "kill_under_pressure": True},  # out of range; kill switch
            "mode": "act",                                   # never automatic
            "agent_sessions": {"stale_after_hours": 48},
        }
        auto, review = g.split_tuning(suggestion)
        self.assertEqual(auto, {"notify_cooldown_seconds": 1800, "cpu": {"sustain_seconds": 900},
                                "agent_sessions": {"stale_after_hours": 48}})
        self.assertEqual(review, {"cpu": {"renice_to": 19},
                                  "renderers": {"memory_mb": 50000, "kill_under_pressure": True},
                                  "mode": "act"})

    def test_apply_and_undo_keep_history(self):
        g.apply_config_change({"mode": "act", "autopilot": True}, "autopilot on")
        g.apply_config_change({"cpu": {"sustain_seconds": 900}}, "auto-tuning")
        cfg = g.load_config(g.CONFIG_PATH)
        self.assertEqual(cfg["mode"], "act")
        self.assertEqual(cfg["cpu"]["sustain_seconds"], 900)
        self.assertEqual(cfg["cpu"]["runaway_pct"], 90, "untouched keys keep defaults")
        last = g.undo_config_change()
        self.assertEqual(last["why"], "auto-tuning")
        cfg = g.load_config(g.CONFIG_PATH)
        self.assertEqual(cfg["cpu"]["sustain_seconds"], 600)
        self.assertEqual(cfg["mode"], "act", "undo only reverts the last change")
        self.assertIsNotNone(g.undo_config_change())
        self.assertEqual(g.load_config(g.CONFIG_PATH)["mode"], "nudge")
        self.assertIsNone(g.undo_config_change(), "nothing left to undo")
        kinds = [json.loads(l)["why"] for l in g.EVENTS_PATH.read_text().splitlines()]
        self.assertEqual(kinds, ["autopilot on", "auto-tuning", "undo", "undo"])

    def test_hygiene_schedule(self):
        cfg = g.load_config(g.Path("/nonexistent"))
        now = g.datetime(2026, 11, 10, 4, 5)
        up = now.timestamp() - 30
        self.assertFalse(g.hygiene_due(now, None, cfg, up), "not in the first ten minutes after start")
        self.assertTrue(g.hygiene_due(now, None, cfg, up - 700), "first run ~10 min after start, any hour")
        yesterday = (now - g.timedelta(hours=24)).timestamp()
        self.assertTrue(g.hygiene_due(now, yesterday, cfg, up - 9999), "daily at the hygiene hour")
        self.assertFalse(g.hygiene_due(g.datetime(2026, 11, 10, 15, 0), yesterday, cfg, up - 9999), "not at other hours")
        self.assertFalse(g.hygiene_due(now, now.timestamp() - 3600, cfg, up - 9999), "not twice in a day")

    def test_run_hygiene_runs_safe_tier_only_when_worth_it(self):
        import scratch
        cfg = g.load_config(g.Path("/nonexistent"))
        rows = [{"name": "Chrome caches", "tier": "safe", "mb": 7000, "app": "Google Chrome", "paths": [], "method": "clear"},
                {"name": "Logs", "tier": "safe-old", "mb": 100, "app": None, "paths": [], "method": "older:30"}]
        calls = []
        saved = (scratch.census, scratch.reclaim)
        scratch.census = lambda home=None: rows
        scratch.reclaim = lambda tier, home=None, dry_run=True, running=frozenset(), rows=None: (
            calls.append((tier, dry_run)) or {"freed_mb": 10, "skipped": []})
        try:
            sample = {"mem_total_mb": 16384, "disk_free_gb": 200}
            h = g.run_hygiene(cfg, sample, running=set(), dry_run=True)
            self.assertEqual([c[0] for c in calls], ["safe-old", "safe"], "7GB reclaimable: safe tier runs")
            self.assertTrue(h["safe_tier_run"])
            calls.clear()
            h = g.run_hygiene(cfg, sample, running={"Google Chrome"}, dry_run=True)
            self.assertEqual([c[0] for c in calls], ["safe-old"], "Chrome running: its caches do not count, so only old logs")
            calls.clear()
            g.run_hygiene(cfg, {"mem_total_mb": 16384, "disk_free_gb": 20}, running={"Google Chrome"}, dry_run=True)
            self.assertEqual([c[0] for c in calls], ["safe-old", "safe"], "disk below 2x RAM: safe tier runs anyway")
        finally:
            scratch.census, scratch.reclaim = saved


if __name__ == "__main__":
    unittest.main(verbosity=1)
