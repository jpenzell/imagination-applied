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
# Chrome 157 as recorded on a real Mac (2026-11-10): helpers are now "(Aperitif Renderer)"
HELPER = ("/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/"
          "Versions/157.0.8103.50/Helpers/Google Chrome Helper (Aperitif Renderer).app/Contents/MacOS/"
          "Google Chrome Helper (Aperitif Renderer)")
HELPER_OLD = ("/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/"
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
        self.assertEqual(procs[2].cls, "automation_browser/renderer")
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


    # ---- macOS specifics found by desk-checking the first real-Mac run paths

    def test_framework_python_is_not_a_gui_app(self):
        clt = ("/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/"
               "Resources/Python.app/Contents/MacOS/Python")
        brew = ("/opt/homebrew/Cellar/python@3.13/3.13.2/Frameworks/Python.framework/Versions/3.13/"
                "Resources/Python.app/Contents/MacOS/Python")
        xcode = ("/Applications/Xcode.app/Contents/Developer/Library/Frameworks/Python3.framework/Versions/3.9/"
                 "Resources/Python.app/Contents/MacOS/Python")
        claude_app = "/Applications/Claude.app/Contents/MacOS/Claude"
        procs = [P(1, clt, "python3 guardian.py watch", ppid=1),
                 P(2, brew, "python3 /x/server.py", ppid=1),
                 P(3, xcode, "python3 -m http.server", ppid=1),
                 P(31, claude_app),
                 P(32, clt, "python3 /Users/j/mcp/server.py", ppid=31)]
        g.classify(procs, self.cfg, UID)
        for pr in procs[:3]:
            self.assertFalse(pr.is_gui, pr.comm)
            self.assertIsNone(pr.app)
            self.assertEqual(pr.cls, "other")
        self.assertEqual(procs[4].cls, "mcp_server", "a Python MCP server under Claude.app folds into Claude helpers")
        self.assertEqual(procs[4].key, "Claude helpers (MCP servers)")

    def test_electron_renderers_fold_into_their_own_app_not_browser(self):
        claude_app = "/Applications/Claude.app/Contents/MacOS/Claude"
        claude_rend = ("/Applications/Claude.app/Contents/Frameworks/Claude Helper (Renderer).app/"
                       "Contents/MacOS/Claude Helper (Renderer)")
        dbx_rend = ("/Applications/Dropbox.app/Contents/Frameworks/Dropbox Helper (Renderer).app/"
                    "Contents/MacOS/Dropbox Helper (Renderer)")
        procs = [P(31, claude_app, rss_mb=400),
                 P(32, claude_rend, claude_rend + " --type=renderer", ppid=31, rss_mb=900),
                 P(40, "/Applications/Dropbox.app/Contents/MacOS/Dropbox"),
                 P(41, dbx_rend, dbx_rend + " --type=renderer", ppid=40, rss_mb=200)]
        g.classify(procs, self.cfg, UID)
        self.assertEqual(procs[1].cls, "ai_app/renderer")
        self.assertEqual(procs[1].key, "Claude")
        self.assertEqual(procs[3].cls, "gui_app/renderer")
        self.assertEqual(procs[3].key, "Dropbox")
        groups = {gr["key"]: gr for gr in g.aggregate(procs, self.cfg)}
        self.assertEqual(groups["Claude"]["class"], "ai_app")
        self.assertEqual(groups["Claude"]["rss_mb"], 1300)
        self.assertNotIn("browser", {gr["class"] for gr in groups.values()})

    def test_crashpad_handler_belongs_to_its_browser(self):
        crashpad = ("/Users/j/Library/Caches/ms-playwright/chromium-1200/chrome-mac/Chromium.app/Contents/"
                    "Frameworks/Chromium Framework.framework/Versions/142/Helpers/chrome_crashpad_handler")
        procs = [P(20, PW_CHROME, PW_CHROME + " --headless"),
                 P(21, crashpad, crashpad + " --monitor-self-annotation=ptype=crashpad-handler --database=/x", ppid=20),
                 P(22, PW_CHROME, PW_CHROME + " --type=gpu-process", ppid=20)]
        g.classify(procs, self.cfg, UID)
        self.assertEqual({p.key for p in procs}, {procs[0].key})
        self.assertEqual({p.cls.split("/")[0] for p in procs}, {"automation_browser"})

    def test_archive_utility_is_not_a_browser(self):
        au = "/System/Library/CoreServices/Applications/Archive Utility.app/Contents/MacOS/Archive Utility"
        procs = [P(50, au), P(51, "/Applications/Archive Thing.app/Contents/MacOS/Archive Thing")]
        g.classify(procs, self.cfg, UID)
        self.assertEqual(procs[0].cls, "system", "lives under /System, and is not a browser")
        self.assertEqual(procs[1].cls, "gui_app", "'Arc' inside another name is not the Arc browser")

    def test_npm_wrapper_and_native_codex_binary_are_one_session(self):
        procs = [P(60, "/opt/homebrew/bin/node", "node /Users/j/.npm-global/bin/codex", ppid=500),
                 P(61, "/Users/j/.npm-global/lib/node_modules/@openai/codex/bin/codex-aarch64-apple-darwin",
                   "codex-aarch64-apple-darwin", ppid=60, rss_mb=800),
                 P(62, "/Users/j/.local/share/claude/versions/2.0.37", "claude --resume x", ppid=500)]
        g.classify(procs, self.cfg, UID)
        self.assertEqual([p.key for p in procs], ["agent:codex", "agent:codex", "agent:claude"])

    def test_gui_app_is_never_a_dev_server_or_model_worker(self):
        code = "/Applications/Visual Studio Code.app/Contents/MacOS/Electron"
        procs = [P(70, code, code + " --vite --webpack ollama runner")]
        g.classify(procs, self.cfg, UID)
        self.assertEqual(procs[0].cls, "gui_app")

    # ---- found on the first real-Mac run (2026-11-10, 8GB M-series Air, macOS 27, Chrome 157)

    def test_chrome_157_aperitif_helper_is_still_a_renderer(self):
        """The name marker 'Helper (Renderer)' no longer matches; --type=renderer must carry it."""
        procs = [P(1901, CHROME, CHROME + " --restore-last-session"),
                 P(13639, HELPER, HELPER + " --type=renderer --lang=en-US", ppid=1901, rss_mb=763),
                 P(80, HELPER_OLD, HELPER_OLD + " --type=renderer", ppid=1901, rss_mb=100)]
        g.classify(procs, self.cfg, UID)
        self.assertEqual(procs[1].cls, "browser/renderer")
        self.assertEqual(procs[2].cls, "browser/renderer", "the old name still works")
        self.assertEqual({p.key for p in procs}, {"Google Chrome"})

    def test_native_claude_code_bundle_is_an_agent_session_not_a_gui_app(self):
        """Claude Code's native install is a real claude.app bundle; the first run showed it as gui_app 'claude'."""
        cc = ("/Users/j/Library/Application Support/Claude/claude-code/2.1.321/e6736b2d954d/claude.app/"
              "Contents/MacOS/claude")
        disclaimer = "/Applications/Claude.app/Contents/Helpers/disclaimer"
        procs = [P(5176, "/Applications/Claude.app/Contents/MacOS/Claude"),
                 P(16375, disclaimer, disclaimer + " --pgroup -- " + cc + " --output-format stream-json", ppid=5176),
                 P(16376, cc, cc + " --output-format stream-json --verbose", ppid=16375, rss_mb=250)]
        g.classify(procs, self.cfg, UID)
        self.assertFalse(procs[2].is_gui)
        self.assertEqual(procs[2].cls, "agent_session")
        self.assertEqual(procs[2].key, "agent:claude")
        self.assertEqual(procs[1].key, "Claude", "the launcher helper inside Claude.app stays with Claude")

    def test_chatgpt_app_engine_and_home_folder_services_fold_under_chatgpt(self):
        """The ChatGPT app embeds Codex: a codex app-server, 30+ node workers, Aperitif renderers and a
        'Codex Computer Use.app' service under ~/.codex were all seen; they belong to ChatGPT."""
        gpt = "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT"
        codex = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
        node = "/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node"
        cua = "/Users/j/.codex/computer-use/Codex Computer Use.app/Contents/MacOS/SkyComputerUseService"
        rend = ("/Applications/ChatGPT.app/Contents/Frameworks/Codex Framework.framework/Versions/157.0.8103.39/"
                "Helpers/Codex (Aperitif Renderer).app/Contents/MacOS/Codex (Aperitif Renderer)")
        procs = [P(1408, gpt, rss_mb=788),
                 P(1462, codex, codex + " -c features.code_mode_host=true app-server", ppid=1408, rss_mb=1208),
                 P(1709, node, node + " ./server.mjs", ppid=1462),
                 P(1525, cua, ppid=1408),
                 P(1483, rend, rend + " --type=renderer", ppid=1408, rss_mb=1990)]
        g.classify(procs, self.cfg, UID)
        self.assertEqual([p.cls for p in procs], ["ai_app", "ai_app", "ai_app", "mcp_server", "ai_app/renderer"])
        self.assertEqual({p.key for p in procs[:3]} | {procs[4].key}, {"ChatGPT"})
        self.assertEqual(procs[3].key, "ChatGPT helpers (MCP servers)")
        groups = {gr["key"]: gr for gr in g.aggregate(procs, self.cfg)}
        self.assertEqual(groups["ChatGPT"]["rss_mb"], 788 + 1208 + 100 + 1990)
        self.assertNotIn("browser", {gr["class"] for gr in groups.values()})


class MacParsingTests(unittest.TestCase):
    """The macOS readers, fed recorded output formats (documented formats; the first real run
    on a Mac should compare these against what the machine actually prints)."""

    def test_parse_ps_macos_format(self):
        codex = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
        wserver = "/System/Library/PrivateFrameworks/SkyLight.framework/Resources/WindowServer"
        comm_out = (
            "    1 /sbin/launchd\n"
            "  512 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome\n"
            "  530 " + HELPER + "\n"
            " 9001 /Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/"
            "Resources/Python.app/Contents/MacOS/Python\n"
            " 1462 " + codex + "\n"
            "  539 " + wserver + "\n")
        # the 1462 and 539 lines are verbatim `ps -ww -ax -o pid=,ppid=,pgid=,uid=,pcpu=,rss=,etime=,time=,args=`
        # output from a real Mac (2026-11-10): `time` minutes run past 59, uid 88 is _windowserver
        main_out = (
            "    1     0     1    0   0.0   9876 12-03:04:05 15:31.27 /sbin/launchd\n"
            f"  512     1   512  {UID}   3.2 412340    02:03:04 1-00:12:33.90 "
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --restore-last-session\n"
            f"  530   512   512  {UID}   0.4 912000       59:59 0:01.23 " + HELPER +
            " --type=renderer --lang=en-US --user-data-dir=/Users/j/Library/Application Support/Google/Chrome\n"
            f" 9001     1  9001  {UID}   0.0  40000       00:30 0:00.05 python3 /Users/j/guardian.py watch\n"
            f" 1462  1408  1408   {UID}  43.2 278400 03:55:51  14:34.55 " + codex +
            " -c features.code_mode_host=true app-server --analytics-default-enabled\n"
            "  539     1   539    88  33.1  44368 03:57:22  89:46.54 " + wserver + " -daemon\n")
        procs = {p.pid: p for p in g.parse_ps(comm_out, main_out)}
        self.assertEqual(set(procs), {1, 512, 530, 9001, 1462, 539})
        self.assertEqual(procs[1462].cputime_s, 14 * 60 + 34)
        self.assertEqual(procs[1462].etime_s, 3 * 3600 + 55 * 60 + 51)
        self.assertEqual(procs[539].cputime_s, 89 * 60 + 46)
        self.assertEqual(procs[539].uid, 88)
        self.assertEqual(procs[539].name, "WindowServer")
        self.assertEqual(procs[530].comm, HELPER, "comm with spaces and parentheses survives")
        self.assertEqual(procs[530].rss_kb, 912000)
        self.assertEqual(procs[530].etime_s, 59 * 60 + 59)
        self.assertEqual(procs[530].cputime_s, 1)
        self.assertEqual(procs[512].cputime_s, 86400 + 12 * 60 + 33)
        self.assertEqual(procs[1].etime_s, 12 * 86400 + 3 * 3600 + 4 * 60 + 5)
        self.assertEqual(procs[1].uid, 0)
        self.assertTrue(procs[530].args.endswith("Support/Google/Chrome"))
        self.assertEqual(procs[9001].name, "Python")

    def test_parse_mac_sample_formats(self):
        # verbatim from an 8GB M-series Air under pressure (2026-11-10); the therm block below is
        # the Intel form, the Apple-silicon form (no CPU_Speed_Limit line at all) is tested after
        raw = {
            "pressure": "2\n", "level": "26\n",
            "swap": "total = 10240.00M  used = 9305.50M  free = 934.50M  (encrypted)",
            "memsize": "8589934592",
            "loadavg": "{ 5.81 6.24 6.75 }",
            "vm_stat": ("Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
                        "Pages free:                                     5152.\n"
                        "Pages active:                                  62418.\n"
                        "Pages stored in compressor:                   368316.\n"
                        "Pages occupied by compressor:                 192962.\n"
                        "Decompressions:                             98765432.\n"),
            "therm": ("Note: No thermal warning level has been recorded\n"
                      "Note: No performance warning level has been recorded\n"
                      "CPU_Scheduler_Limit \t= 100\n"
                      "CPU_Available_CPUs \t= 10\n"
                      "CPU_Speed_Limit \t= 72\n"),
        }
        s = g.parse_mac_sample(raw, {})
        self.assertEqual(s["pressure_level"], 2)
        self.assertTrue(s["pressure_read"])
        self.assertEqual(s["free_pct"], 26)
        self.assertEqual(s["swap_total_mb"], 10240.0)
        self.assertEqual(s["swap_used_mb"], 9305.5)
        self.assertEqual(s["mem_total_mb"], 8192)
        self.assertEqual(s["load1"], 5.81)
        self.assertEqual(s["compressed_mb"], 192962 * 16384 // (1024 * 1024),
                         "'occupied by compressor' (3015MB, what top calls compressor), not 'stored in'")
        self.assertEqual(s["cpu_speed_limit"], 72)
        apple_silicon = ("Note: No thermal warning level has been recorded\n"
                         "Note: No performance warning level has been recorded\n"
                         "Note: No CPU power status has been recorded\n")
        self.assertEqual(g.parse_mac_sample({"therm": apple_silicon}, {})["cpu_speed_limit"], 100)
        # a Mac that prints nothing useful must degrade to safe defaults, not crash
        s2 = g.parse_mac_sample({k: "" for k in raw}, {})
        self.assertEqual(s2["pressure_level"], 1)
        self.assertFalse(s2["pressure_read"])
        self.assertIsNone(s2["free_pct"])
        self.assertEqual(s2["cpu_speed_limit"], 100)
        # swap reported in GB (seen on large configs)
        s3 = g.parse_mac_sample({"swap": "total = 8.00G  used = 2.50G  free = 5.50G  (encrypted)"}, {})
        self.assertEqual((s3["swap_total_mb"], s3["swap_used_mb"]), (8192.0, 2560.0))

    def test_plist_uses_the_chosen_python_and_watch(self):
        txt = g.plist_text(g.Path("/Users/j/guardian-src/tools/laptop-guardian/guardian.py"),
                           g.load_config(g.Path("/nonexistent")), python="/opt/homebrew/bin/python3")
        self.assertIn("<string>/opt/homebrew/bin/python3</string>", txt)
        self.assertIn("<string>watch</string>", txt)
        self.assertIn(f"<string>{g.LABEL}</string>", txt)
        self.assertIn("<key>KeepAlive</key><true/>", txt)

    def test_ps_command_never_truncates(self):
        self.assertIn("-ww", g.ps_command("pid=,comm="))

    def test_memory_is_physical_footprint_on_mac(self):
        """Under pressure ps RSS read a 1.9GB renderer as 150MB; libproc's phys_footprint is what
        Activity Monitor shows. Elsewhere it is None and RSS stands."""
        if not g.IS_MAC:
            self.assertIsNone(g.phys_footprint_kb(os.getpid()))
            return
        me = g.phys_footprint_kb(os.getpid())
        self.assertIsInstance(me, int)
        self.assertGreater(me, 1024, "a Python process has more than 1MB of footprint")
        self.assertIsNone(g.phys_footprint_kb(2 ** 30), "an unknown pid reads as None, never 0")
        mine = {p.pid: p for p in g.list_processes()}[os.getpid()]
        self.assertLess(abs(mine.rss_kb - me) / me, 0.5, "list_processes carries the footprint, not RSS")


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
        import shutil
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
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

    def test_gui_process_is_shielded_even_when_a_rule_misfires(self):
        self.cfg["mode"] = "act"
        app = P(90, "/Applications/Visual Studio Code.app/Contents/MacOS/Electron")
        g.classify([app], self.cfg, UID)
        r = g.apply_decisions([g.Decision("kill", app, "test", "dev_server", "crit")], self.cfg)
        self.assertEqual(r[0]["result"], "protected (GUI app)")
        self.assertEqual(self.killed, [])

    def test_reclaim_runs_on_the_background_worker_and_logs_when_done(self):
        """The census is ~110 s of `du` on a real Mac; the sampling loop must not wait for it."""
        import threading
        gate = threading.Event()
        calls = []
        import scratch
        orig = scratch.census

        def slow_census(home=None):
            calls.append("census")
            gate.wait(5)
            return []
        scratch.census = slow_census
        try:
            bg = g.Background()
            d = g.Decision("reclaim", None, "Only 9GB free on disk.", "disk", "warn")
            t0 = g.time.time()
            applied = g.apply_decisions([d], self.cfg, dry_run=True, background=bg)
            self.assertLess(g.time.time() - t0, 1.0, "apply_decisions returned without waiting for du")
            self.assertEqual(applied[0]["result"], "census running in the background")
            self.assertTrue(bg.busy())
            self.assertEqual([e["action"] for e in g.read_events(1) if e["kind"] == "decision"], [],
                             "nothing logged until the job finishes")
            # a second reclaim while the first census runs is refused, not queued
            applied2 = g.apply_decisions([d], self.cfg, dry_run=True, background=bg)
            self.assertTrue(applied2[0]["result"].startswith("skipped: reclaim job"))
            gate.set()
            bg.thread.join(5)
            self.assertFalse(bg.busy())
            done = [e for e in g.read_events(1) if e["kind"] == "decision" and e["action"] == "reclaim"]
            self.assertEqual([e["result"] for e in done],
                             ["skipped: reclaim job still running", "would reclaim 0.0GB (safe tiers)"])
            self.assertEqual(calls, ["census"])
            # without a worker (watch --once) it still runs inline and logs normally
            applied3 = g.apply_decisions([d], self.cfg, dry_run=True)
            self.assertEqual(applied3[0]["result"], "would reclaim 0.0GB (safe tiers)")
        finally:
            scratch.census = orig

    def test_events_are_logged(self):
        self.cfg["mode"] = "observe"
        g.apply_decisions(self.kill_decision(), self.cfg)
        lines = g.EVENTS_PATH.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn('"kind": "decision"', lines[0])



GPT = "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT"
GPT_REND = ("/Applications/ChatGPT.app/Contents/Frameworks/Codex Framework.framework/Versions/157.0.8103.39/"
            "Helpers/Codex (Aperitif Renderer).app/Contents/MacOS/Codex (Aperitif Renderer)")
GPT_CODEX = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
GPT_NODE = "/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node"
GPT_CUA = "/Users/j/.codex/computer-use/Codex Computer Use.app/Contents/MacOS/SkyComputerUseService"
GPT_CRASH = ("/Applications/ChatGPT.app/Contents/Frameworks/Codex Framework.framework/Versions/157.0.8103.39/"
             "Helpers/browser_crashpad_handler")


def chatgpt_procs():
    """The ChatGPT app as recorded on a real Mac: main, a big renderer, the Codex engine, a
    per-task node worker that outlives the app, the computer-use service, a crashpad handler."""
    return [P(1408, GPT, rss_mb=800),
            P(1483, GPT_REND, GPT_REND + " --type=renderer", ppid=1408, rss_mb=1900),
            P(1462, GPT_CODEX, GPT_CODEX + " app-server", ppid=1408, rss_mb=1300),
            P(1709, GPT_NODE, GPT_NODE + " /tmp/x/trusted-worker.js", ppid=1462, rss_mb=280),
            P(1525, GPT_CUA, ppid=1408, rss_mb=60),
            P(1420, GPT_CRASH, ppid=1, rss_mb=3),
            P(5176, "/Applications/Claude.app/Contents/MacOS/Claude", rss_mb=300)]


class FakeOps:
    """Stands in for the Mac: records what refresh would do to it."""

    def __init__(self, quits=True, age=3600.0, front="Claude", idle=20.0, answer="Refresh now"):
        self.procs = chatgpt_procs()
        self.alive_pids = {p.pid for p in self.procs}
        self.quits, self.age, self.front, self.idle, self.answer = quits, age, front, idle, answer
        self.calls = []

    def processes(self, cfg):
        return g.classify([p for p in self.procs if p.pid in self.alive_pids], cfg, UID)

    def sample(self):
        return {"pressure_level": 2, "free_pct": 20, "swap_used_mb": 8000, "disk_free_gb": 16.6}

    def activity_age(self, app, cfg):
        return self.age

    def front_app(self):
        return self.front

    def user_idle(self):
        return self.idle

    def quit(self, bundle, main, chromium_like):
        self.calls.append(("quit", bundle, chromium_like))
        if self.quits:      # the app and its own helpers exit; the per-task worker lingers
            self.alive_pids -= {1408, 1483, 1462, 1525, 1420}
        return "applescript"

    def alive(self, p):
        return p.pid in self.alive_pids

    def term(self, p):
        self.calls.append(("term", p.pid))
        self.alive_pids.discard(p.pid)

    def clear_caches(self, app, running):
        self.calls.append(("clear", app, sorted(running)))
        return 3800

    def cache_mb(self, app):
        return 3800

    def reopen(self, bundle):
        self.calls.append(("reopen", bundle))
        self.procs.append(P(9000, GPT, rss_mb=600))
        self.alive_pids.add(9000)

    def sleep(self, seconds):
        pass

    def ask(self, text, buttons, default):
        self.calls.append(("ask", text))
        return self.answer


class RefreshTests(unittest.TestCase):
    """Refresh when idle: quit cleanly, clear caches, reopen; only when the agent is idle and
    only with consent. Nothing here touches a real app."""

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = g.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.saved = (g.CONFIG_DIR, g.CONFIG_PATH, g.CONFIG_HISTORY, g.LOG_DIR, g.EVENTS_PATH)
        g.CONFIG_DIR = self.tmp / "cfg"
        g.CONFIG_PATH = g.CONFIG_DIR / "config.json"
        g.CONFIG_HISTORY = g.CONFIG_DIR / "config-history.jsonl"
        g.LOG_DIR = self.tmp / "logs"
        g.EVENTS_PATH = g.LOG_DIR / "events.jsonl"
        self.cfg = g.load_config(g.Path("/nonexistent"))
        self.cfg["notify"] = False
        self.rcfg = self.cfg["refresh"]

    def tearDown(self):
        g.CONFIG_DIR, g.CONFIG_PATH, g.CONFIG_HISTORY, g.LOG_DIR, g.EVENTS_PATH = self.saved

    def phases(self):
        return [(e.get("phase"), e.get("app")) for e in g.read_events(1) if e["kind"] == "refresh"]

    def test_family_and_main_process(self):
        fam, main = g.app_family(g.classify(chatgpt_procs(), self.cfg, UID), "ChatGPT")
        self.assertEqual(main.pid, 1408, "the crashpad handler (also ppid 1) is not the main process")
        self.assertEqual({p.pid for p in fam}, {1408, 1483, 1462, 1709, 1525, 1420})
        self.assertEqual(g.bundle_path(main.comm), "/Applications/ChatGPT.app")
        self.assertEqual(g.bundle_path(GPT_REND), "/Applications/ChatGPT.app", "outermost bundle")

    def test_parsers_on_recorded_macos_output(self):
        macos27 = ('"Claude" ASN:0x0-0x88088: (in front) \n    bundleID=[ NULL ] \n    bundle path=[ NULL ] \n')
        self.assertEqual(g.parse_front_app(macos27), "Claude")
        self.assertEqual(g.parse_front_app('"LSDisplayName"="Google Chrome"\n'), "Google Chrome")
        self.assertEqual(g.parse_front_app(""), "")
        self.assertAlmostEqual(g.parse_hid_idle('    | |     "HIDIdleTime" = 86657115916\n'), 86.657, places=2)
        self.assertIsNone(g.parse_hid_idle("nothing here"))
        self.assertEqual(g.parse_dialog("button returned:Refresh now, gave up:false\n"), "Refresh now")
        self.assertEqual(g.parse_dialog("button returned:, gave up:true\n"), "", "nobody answered")
        self.assertEqual(g.parse_dialog(""), "")

    def test_newest_mtime_sees_a_session_file_being_written(self):
        d = self.tmp / "sessions" / "2026" / "09" / "09"
        d.mkdir(parents=True)
        old, new = d / "old.jsonl", d / "active.jsonl"
        old.write_text("x")
        new.write_text("y")
        os.utime(old, (1000, 1000))
        os.utime(new, (5000, 5000))
        self.assertEqual(g.newest_mtime([self.tmp / "sessions"]), 5000)
        self.assertEqual(g.newest_mtime([old, self.tmp / "missing"]), 1000)
        self.assertEqual(g.newest_mtime([self.tmp / "missing"]), 0.0)

    def test_decide_never_interrupts_an_agent_or_the_app_in_front(self):
        d = lambda mode, age, front, idle: g.refresh_decide(mode, self.rcfg, age, front, idle)[0]
        self.assertEqual(d("ask", 30, False, 5), "wait", "agent wrote 30 s ago")
        self.assertEqual(d("auto", 30, False, 9999), "wait")
        self.assertEqual(d("ask", 3600, True, 5), "wait", "you are using the app")
        self.assertEqual(d("ask", 3600, False, 5), "ask")
        self.assertEqual(d("ask", 3600, False, 3600), "wait", "nobody there to answer; ask later")
        self.assertEqual(d("ask", None, False, 5), "ask", "no agent signal: the owner decides")
        self.assertEqual(d("auto", 3600, False, 5), "wait", "auto waits until you are away")
        self.assertEqual(d("auto", 3600, False, 600), "refresh")
        self.assertEqual(d("auto", None, False, 600), "wait", "auto needs proof the agent is idle")
        self.assertEqual(d("auto", 3600, False, None), "wait")

    def test_due_checks_size_pressure_cooldown_and_snooze(self):
        grp = {"key": "ChatGPT", "rss_mb": 10000}
        hot, calm = sample(level=2, free=20), sample(level=1, free=60)
        due = lambda mode="ask", grp=grp, s=hot, st=None, now=10 ** 6: g.refresh_due(mode, grp, s, self.cfg, st or {}, now)
        self.assertEqual(due(), "")
        self.assertEqual(due(mode="never"), "set to never")
        self.assertEqual(due(mode="yes please"), "set to never", "an unknown mode is never consent")
        self.assertEqual(due(grp=None), "not running")
        self.assertIn("only 2.0GB", due(grp={"key": "ChatGPT", "rss_mb": 2048}))
        self.assertEqual(due(s=calm), "no memory pressure")
        self.assertIn("refreshed 1.0h ago", due(st={"last": 10 ** 6 - 3600}))
        self.assertIn("you said not now", due(st={"snooze_until": 10 ** 6 + 600}))

    def test_refresh_quits_cleans_reopens_and_records_before_and_after(self):
        ops = FakeOps()
        rec = g.refresh_app("ChatGPT", self.cfg, ops)
        self.assertEqual(rec["phase"], "done")
        self.assertEqual([c[0] for c in ops.calls], ["quit", "term", "clear", "reopen"])
        self.assertEqual(ops.calls[0], ("quit", "/Applications/ChatGPT.app", True))
        self.assertEqual(ops.calls[1], ("term", 1709), "only the helper that outlived the app")
        self.assertEqual(ops.calls[2], ("clear", "ChatGPT", ["Claude"]), "other running apps stay guarded")
        self.assertEqual(rec["before"]["app_mb"], 800 + 1900 + 1300 + 280 + 60 + 3)
        self.assertEqual(rec["after"]["app_mb"], 600)
        self.assertEqual((rec["memory_back_mb"], rec["caches_freed_mb"], rec["leftovers"]), (3743, 3800, 1))
        self.assertEqual(self.phases(), [("started", "ChatGPT"), ("done", "ChatGPT")])
        self.assertIn("ChatGPT: done: memory 4.2GB -> 0.6GB", g.render_report(1))

    def test_refresh_leaves_a_working_agent_alone(self):
        ops = FakeOps(age=30.0)
        rec = g.refresh_app("ChatGPT", self.cfg, ops)
        self.assertEqual(rec["phase"], "aborted")
        self.assertEqual(ops.calls, [], "nothing was sent to the app")
        self.assertEqual(g.refresh_app("ChatGPT", self.cfg, FakeOps(age=30.0), force=True)["phase"], "done")

    def test_app_that_does_not_quit_is_left_running(self):
        ops = FakeOps(quits=False)
        rec = g.refresh_app("ChatGPT", self.cfg, ops)
        self.assertEqual(rec["phase"], "aborted")
        self.assertIn("did not quit", rec["result"])
        self.assertEqual([c[0] for c in ops.calls], ["quit"], "no kill, no cache clearing, no relaunch")

    def test_dry_run_and_not_running(self):
        ops = FakeOps()
        rec = g.refresh_app("ChatGPT", self.cfg, ops, dry_run=True)
        self.assertEqual((rec["phase"], rec["would_clear_mb"], ops.calls), ("dry-run", 3800, []))
        self.assertEqual(g.refresh_app("Codex", self.cfg, FakeOps())["result"], "not running")

    def test_dialog_answers(self):
        st = {}
        ops = FakeOps(answer="Not now")
        g.refresh_ask("ChatGPT", self.cfg, st, 10.1, 1500, ops)
        self.assertEqual([c[0] for c in ops.calls], ["ask"])
        self.assertIn("10.1 GB", ops.calls[0][1])
        self.assertIn("idle for 25 minutes", ops.calls[0][1])
        self.assertAlmostEqual(st["snooze_until"], g.time.time() + 120 * 60, delta=5)
        st, ops = {}, FakeOps(answer="")
        g.refresh_ask("ChatGPT", self.cfg, st, 10.1, 1500, ops)
        self.assertAlmostEqual(st["snooze_until"], g.time.time() + 30 * 60, delta=5, msg="unanswered: ask again sooner")
        self.assertEqual([c[0] for c in ops.calls], ["ask"])
        st, ops = {}, FakeOps(answer="Always when idle")
        rec = g.refresh_ask("ChatGPT", self.cfg, st, 10.1, 1500, ops)
        self.assertEqual(rec["phase"], "done")
        self.assertEqual(g.json.loads(g.CONFIG_PATH.read_text())["refresh"]["apps"], {"ChatGPT": "auto"})
        self.assertAlmostEqual(st["last"], g.time.time(), delta=5)
        self.assertEqual([p for p, _ in self.phases()],
                         ["asked", "declined", "asked", "unanswered", "asked", "started", "done"])
        g.undo_config_change()
        self.assertNotIn("refresh", g.json.loads(g.CONFIG_PATH.read_text()), "the standing consent can be undone")

    def test_tick_only_starts_a_job_when_everything_lines_up(self):
        snap = lambda quiet="": {"groups": [{"key": "ChatGPT", "rss_mb": 10000, "n": 99}],
                                 "sample": sample(level=2, free=20), "quiet": quiet}

        def tick(ops, cfg=None, quiet="", state=None, bg=None):
            bg = bg or g.Background()
            app = g.refresh_tick(cfg or self.cfg, snap(quiet), {} if state is None else state, bg, g.time.time(), ops=ops)
            if bg.thread:
                bg.thread.join(5)
            return app

        ops = FakeOps(answer="Not now")
        state = {}
        self.assertEqual(tick(ops, state=state), "ChatGPT")
        self.assertEqual([c[0] for c in ops.calls], ["ask"])
        self.assertIsNone(tick(ops, state=state), "snoozed and throttled: not asked again")
        self.assertEqual(len(ops.calls), 1)
        self.assertIsNone(tick(FakeOps(age=30.0)), "Codex is working")
        self.assertIsNone(tick(FakeOps(front="ChatGPT")), "you are using it")
        self.assertIsNone(tick(FakeOps(), quiet="Keynote"), "presenting")
        observe = dict(self.cfg, mode="observe")
        self.assertIsNone(tick(FakeOps(), cfg=observe))
        self.assertIsNone(g.refresh_tick(self.cfg, snap(), {}, None, g.time.time(), ops=FakeOps()), "watch --once")
        # auto acts unasked only in act mode; in nudge mode it still asks
        auto = g.json.loads(g.json.dumps(self.cfg))
        auto["refresh"]["apps"]["ChatGPT"] = "auto"
        ops = FakeOps(idle=900.0, answer="Not now")
        self.assertEqual(tick(ops, cfg=auto), None, "nudge mode downgrades auto to ask; you are away, so it waits")
        ops = FakeOps(idle=900.0)
        self.assertEqual(tick(ops, cfg=dict(auto, mode="act")), "ChatGPT")
        self.assertEqual([c[0] for c in ops.calls], ["quit", "term", "clear", "reopen"], "no dialog in auto")

    def test_restart_remembers_cooldown_and_snooze(self):
        g.refresh_app("ChatGPT", self.cfg, FakeOps())
        g.refresh_ask("Codex", self.cfg, {}, 7.0, None, FakeOps(answer="Not now"))
        g.refresh_app("Claude", self.cfg, FakeOps(), dry_run=True)
        state = g.refresh_state_from_events()
        now = g.time.time()
        self.assertAlmostEqual(state["ChatGPT"]["last"], now, delta=5)
        self.assertAlmostEqual(state["Codex"]["snooze_until"], now + 120 * 60, delta=5)
        self.assertEqual(state.get("Claude", {}).get("last", 0.0), 0.0, "a dry run is not a refresh")
        self.assertIn("refreshed 0.0h ago", g.refresh_due("ask", {"rss_mb": 10000}, sample(level=2), self.cfg,
                                                           state["ChatGPT"], now))

    def test_consent_is_never_self_tuned(self):
        auto, review = g.split_tuning({"refresh": {"apps": {"ChatGPT": "auto"}, "min_gb": 4}})
        self.assertEqual(auto, {"refresh": {"min_gb": 4}})
        self.assertEqual(review, {"refresh": {"apps": {"ChatGPT": "auto"}}}, "the diagnosis cannot grant consent")
        self.assertEqual(self.cfg["refresh"]["apps"], {"ChatGPT": "ask"}, "default is to ask, for ChatGPT only")


class DiskTests(unittest.TestCase):
    """The ledger, the fast-drop alert and cache clearing on quit. Found on the first real Mac:
    free disk fell 8 GB in two hours and nothing guardian measured had grown."""

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = g.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.saved = (g.LOG_DIR, g.EVENTS_PATH, g.SAMPLES_PATH, g.sample_system, g.list_processes)
        g.LOG_DIR = self.tmp / "logs"
        g.EVENTS_PATH = g.LOG_DIR / "events.jsonl"
        g.SAMPLES_PATH = g.LOG_DIR / "samples.tsv"
        self.cfg = g.load_config(g.Path("/nonexistent"))
        self.cfg["notify"] = False
        import scratch
        self.scratch = scratch
        self.saved_scratch = (scratch.census, scratch.system_buckets, scratch.reclaim)
        self.free = 20.7
        self.rows = [{"name": "Codex sessions", "mb": 9600}]
        self.temp_mb = 90
        g.sample_system = lambda: {"disk_free_gb": self.free}
        scratch.census = lambda home=None, only_app=None: [dict(r) for r in self.rows]
        scratch.system_buckets = lambda *a, **k: [{"name": "Temporary files", "mb": self.temp_mb}]

    def tearDown(self):
        g.LOG_DIR, g.EVENTS_PATH, g.SAMPLES_PATH, g.sample_system, g.list_processes = self.saved
        self.scratch.census, self.scratch.system_buckets, self.scratch.reclaim = self.saved_scratch

    def test_drop_detector(self):
        hist = [(0, 20.7), (600, 20.5), (1800, 19.0), (3000, 16.6)]
        self.assertEqual(g.disk_drop(hist, 3000, 3600, 3), 4.1)
        self.assertEqual(g.disk_drop(hist, 3000, 3600, 5), 0.0, "below the threshold")
        self.assertEqual(g.disk_drop(hist, 3000, 600, 3), 0.0, "only one reading in a 10 minute window")
        self.assertEqual(g.disk_drop([(0, 12.0), (600, 19.4)], 600, 3600, 3), 0.0, "space coming back is not a drop")
        self.assertEqual(g.disk_drop([], 0, 3600, 3), 0.0)

    def test_fast_drop_alert_names_what_grew(self):
        g.write_ledger()
        self.free, self.temp_mb = 12.1, 7900
        rec = g.disk_drop_job(self.cfg, 8.6)
        self.assertIn("Disk space fell 8.6GB in the last 60 minutes (12.1GB free)", rec["text"])
        self.assertIn("Temporary files +7.6GB", rec["text"])
        self.assertEqual(len(g.read_ledger()), 2)
        self.assertEqual([e["trigger"] for e in g.read_events(1) if e["kind"] == "disk"], ["fast-drop"])
        report = g.render_report(1)
        self.assertIn("## Disk", report)
        self.assertIn("+7.6 GB  Temporary files", report)

    def test_first_alert_without_a_baseline_says_so(self):
        rec = g.disk_drop_job(self.cfg, 3.2)
        self.assertIn("First measurement taken", rec["text"])

    def test_ledger_baseline_picks_the_oldest_entry_in_the_window(self):
        now = g.time.time()
        mk = lambda hours_ago: {"ts": g.datetime.fromtimestamp(now - hours_ago * 3600).isoformat(timespec="seconds"),
                                "free_gb": 20, "items": {}}
        entries = [mk(50), mk(20), mk(6), mk(0)]
        self.assertEqual(g.ledger_baseline(entries, 24, now), entries[1])
        self.assertEqual(g.ledger_baseline(entries, 3, now), entries[2], "nothing in the window: the previous one")
        self.assertIsNone(g.ledger_baseline(entries[:1], 24, now))

    def test_quit_needs_two_samples_and_a_relaunch_resets_it(self):
        st, guard = {}, {"Google Chrome", "ChatGPT"}
        self.assertEqual(g.quit_tracker(st, {"Google Chrome", "ChatGPT"}, guard), [])
        self.assertEqual(g.quit_tracker(st, {"ChatGPT"}, guard), [], "gone for one sample: could be a relaunch")
        self.assertEqual(g.quit_tracker(st, {"ChatGPT", "Google Chrome"}, guard), [], "it came back")
        self.assertEqual(g.quit_tracker(st, {"ChatGPT"}, guard), [])
        self.assertEqual(g.quit_tracker(st, {"ChatGPT"}, guard), ["Google Chrome"])
        self.assertEqual(g.quit_tracker(st, {"ChatGPT"}, guard), [], "reported once")
        self.assertEqual(g.quit_tracker({}, set(), guard), [], "never seen running is not a quit")

    def test_caches_are_cleared_on_quit_unless_the_app_is_back(self):
        calls = []
        self.rows = [{"name": "Chrome caches", "tier": "safe", "app": "Google Chrome", "mb": 1600, "paths": []}]

        def reclaim(tier, home=None, dry_run=True, running=frozenset(), rows=None):
            calls.append((tier, dry_run, sorted(running), [r["name"] for r in rows]))
            return {"freed_mb": 1600, "items": [{"name": "Chrome caches", "mb": 1600}], "skipped": []}
        self.scratch.reclaim = reclaim
        g.list_processes = lambda: [P(31, "/Applications/Claude.app/Contents/MacOS/Claude")]
        rec = g.clear_caches_on_quit("Google Chrome", self.cfg)
        self.assertEqual(calls, [("safe", False, ["Claude"], ["Chrome caches"])])
        self.assertEqual((rec["trigger"], rec["app"], rec["freed_mb"]), ("quit", "Google Chrome", 1600))
        g.list_processes = lambda: [P(10, CHROME)]
        self.assertIsNone(g.clear_caches_on_quit("Google Chrome", self.cfg), "it is running again: hands off")
        self.assertEqual(len(calls), 1)

    def test_disk_trend_reads_the_samples(self):
        g.LOG_DIR.mkdir(parents=True)
        now = g.datetime.now()
        rows = ["ts\tlevel\tfree_pct\tswap_used_mb\tcompressed_mb\tload1\tdisk_free_gb\ttop"]
        for minutes_ago, free in ((90, 20.7), (50, 19.0), (1, 16.6)):
            rows.append("\t".join([(now - g.timedelta(minutes=minutes_ago)).isoformat(timespec="seconds"),
                                   "2", "27", "8000", "3000", "5.0", str(free), "x=1"]))
        g.SAMPLES_PATH.write_text("\n".join(rows) + "\n")
        self.assertEqual(g.disk_trend(1), -2.4)
        self.assertEqual(g.disk_trend(24), -4.1)
        self.assertIsNone(g.disk_trend(0.001))

    def test_big_items_lists_and_never_touches(self):
        d = self.tmp / "Downloads"
        (d / "course-build").mkdir(parents=True)
        (d / "course-build" / "video.mp4").write_bytes(b"x" * (3 * 1024 * 1024))
        (d / "notes.txt").write_bytes(b"x" * 1024)
        (d / ".hidden").write_bytes(b"x" * (5 * 1024 * 1024))
        items = g.big_items([d, self.tmp / "missing"], top=5)
        self.assertEqual([(mb, g.os.path.basename(p)) for mb, _when, p in items], [(3, "course-build"), (0, "notes.txt")])
        self.assertTrue((d / "course-build" / "video.mp4").exists())


class FakeProc:
    def __init__(self):
        self.code = None

    def poll(self):
        return self.code


class FakeArchiveOps:
    """Stands in for the drive, the folders, the dialog and the copy process."""

    def __init__(self, answer="Not now", idle=10.0, gb=5.0, drive="My Passport"):
        self.answer, self.idle, self.drive = answer, idle, drive
        vol = {"name": drive, "path": f"/Volumes/{drive}", "base": f"/Volumes/{drive}", "free_mb": 3_000_000}
        cands = [{"root": "/Users/j/Documents/Codex", "name": "2026-10-03", "path": "/Users/j/Documents/Codex/2026-10-03",
                  "mb": int(gb * 1024 * 0.6), "logical_mb": 3000, "age_days": 37, "keep": ""},
                 {"root": "/Users/j/Documents/Codex", "name": "2026-09-17", "path": "/Users/j/Documents/Codex/2026-09-17",
                  "mb": int(gb * 1024 * 0.4), "logical_mb": 2000, "age_days": 37, "keep": ""}]
        self.the_plan = {"days": 30, "move": cands, "keep": [], "volume": vol if drive else None,
                         "why": "" if drive else "no external drive is connected", "mb": sum(c["mb"] for c in cands)}
        self.calls, self.proc = [], FakeProc()

    def volumes(self):
        self.calls.append(("volumes",))
        return [self.the_plan["volume"]] if self.drive else []

    def plan(self, cfg):
        self.calls.append(("plan",))
        return self.the_plan

    def user_idle(self):
        return self.idle

    def ask(self, text, buttons, default):
        self.calls.append(("ask", text, buttons, default))
        return self.answer

    def show(self, plan):
        self.calls.append(("show",))

    def start(self, cfg):
        self.calls.append(("start",))
        return self.proc


class ArchiveTests(unittest.TestCase):
    """Old work folders move to an external drive: only when asked, only after the copy checks
    out. The copying itself is tested in test_archive.py; this is the asking and the telling."""

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = g.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.saved = (g.CONFIG_DIR, g.CONFIG_PATH, g.CONFIG_HISTORY, g.LOG_DIR, g.EVENTS_PATH, g.sample_system)
        g.CONFIG_DIR = self.tmp / "cfg"
        g.CONFIG_PATH = g.CONFIG_DIR / "config.json"
        g.CONFIG_HISTORY = g.CONFIG_DIR / "config-history.jsonl"
        g.LOG_DIR = self.tmp / "logs"
        g.EVENTS_PATH = g.LOG_DIR / "events.jsonl"
        g.sample_system = lambda: {"disk_free_gb": 24.9}
        self.cfg = g.load_config(g.Path("/nonexistent"))
        self.cfg["notify"] = False
        import archive
        self.saved_archive = (archive.volumes, archive._same_disk)
        archive.volumes = lambda: []                 # never look at the drives really connected

    def tearDown(self):
        g.CONFIG_DIR, g.CONFIG_PATH, g.CONFIG_HISTORY, g.LOG_DIR, g.EVENTS_PATH, g.sample_system = self.saved
        import archive
        archive.volumes, archive._same_disk = self.saved_archive

    def tick(self, ops, st, cfg=None, free=19.0, quiet="", bg=False):
        bg = g.Background() if bg is False else bg
        snap = {"sample": sample(level=2, free=20, disk=free), "quiet": quiet, "groups": []}
        out = g.archive_tick(cfg or self.cfg, snap, st, bg, g.time.time(), ops=ops)
        if bg is not None and bg.thread:
            bg.thread.join(5)
        return out

    def phases(self):
        return [e["phase"] for e in g.read_events(1) if e["kind"] == "archive"]

    def test_defaults_ask_first_and_are_never_self_tuned(self):
        a = self.cfg["archive"]
        self.assertEqual((a["roots"], a["offer"], a["min_age_days"]), (["Documents/Codex"], True, 30))
        auto, review = g.split_tuning({"archive": {"min_age_days": 1, "roots": ["Documents"], "offer_below_gb": 500}})
        self.assertEqual(auto, {}, "a diagnosis cannot widen what may leave this Mac")
        self.assertEqual(set(review["archive"]), {"min_age_days", "roots", "offer_below_gb"})

    def test_measures_first_then_asks_and_a_no_is_remembered(self):
        ops, st = FakeArchiveOps(answer="Not now"), {}
        self.assertEqual(self.tick(ops, st), "scan")
        self.assertEqual([c[0] for c in ops.calls], ["volumes", "plan"])
        self.assertEqual(self.tick(ops, st), "ask")
        _, text, buttons, default = ops.calls[-1]
        self.assertEqual((buttons, default), (["Not now", "Show me", "Move them"], "Not now"),
                         "a stray Return must move nothing")
        self.assertIn("This Mac has 19 GB free. 2 folders in Codex have not been used for 30+ days and take 5.0 GB", text)
        self.assertIn("Move them to My Passport?", text)
        self.assertAlmostEqual(st["snooze_until"], g.time.time() + 3 * 86400, delta=5)
        self.assertIsNone(self.tick(ops, st))
        self.assertEqual(self.phases(), ["scan", "asked", "declined"])
        self.assertNotIn(("start",), ops.calls)
        # a restart does not ask again
        self.assertAlmostEqual(g.archive_state_from_events()["snooze_until"], st["snooze_until"], delta=5)

    def test_does_not_ask_when_it_would_be_pointless_or_rude(self):
        def never(why, ops=None, **kw):
            ops, st = ops or FakeArchiveOps(), {}
            first = self.tick(ops, st, **kw)
            st["next_check"] = 0.0
            self.assertIsNone(self.tick(ops, st, **kw) if first == "scan" else first, why)
            self.assertNotIn("ask", [c[0] for c in ops.calls], why)
        never("the disk has room", free=60.0)
        never("no drive is connected", ops=FakeArchiveOps(drive=""))
        never("you are away from the keyboard", ops=FakeArchiveOps(idle=900.0))
        never("too little to be worth a dialog", ops=FakeArchiveOps(gb=1.0))
        never("presenting", quiet="Keynote")
        never("observe mode", cfg=dict(self.cfg, mode="observe"))
        never("watch --once", bg=None)
        off = g.json.loads(g.json.dumps(self.cfg))
        off["archive"]["offer"] = False
        never("switched off", cfg=off)
        busy = g.Background()
        gate = g.threading.Event()
        busy.submit("census", gate.wait)
        try:
            self.assertIsNone(g.archive_tick(self.cfg, {"sample": sample(disk=19.0), "quiet": ""}, {}, busy,
                                             g.time.time(), ops=FakeArchiveOps()), "the worker is busy")
        finally:
            gate.set()

    def test_a_yes_starts_one_run_and_nothing_is_asked_while_it_runs(self):
        ops, st = FakeArchiveOps(answer="Move them"), {}
        self.tick(ops, st)
        self.assertEqual(self.tick(ops, st), "ask")
        self.assertEqual([c[0] for c in ops.calls].count("start"), 1)
        self.assertIs(st["proc"], ops.proc)
        calls = len(ops.calls)
        st["next_check"] = 0.0
        self.assertIsNone(self.tick(ops, st), "the copy is running")
        self.assertEqual(len(ops.calls), calls, "not even a look at the drive")
        ops.proc.code = 0
        self.assertIsNone(self.tick(ops, st))
        self.assertIsNone(st["proc"])
        self.assertAlmostEqual(st["snooze_until"], g.time.time() + 6 * 3600, delta=5)
        self.assertEqual(self.phases(), ["scan", "asked", "accepted"])

    def test_show_me_opens_the_list_and_asks_again_soon(self):
        ops, st = FakeArchiveOps(answer="Show me"), {}
        self.tick(ops, st)
        self.tick(ops, st)
        self.assertIn(("show",), ops.calls)
        self.assertNotIn(("start",), ops.calls)
        self.assertAlmostEqual(st["snooze_until"], g.time.time() + 600, delta=5)
        silent, st2 = FakeArchiveOps(answer=""), {}
        self.tick(silent, st2)
        self.tick(silent, st2)
        self.assertAlmostEqual(st2["snooze_until"], g.time.time() + 7200, delta=5, msg="nobody answered")

    def test_a_drive_swap_means_measuring_again(self):
        ops, st = FakeArchiveOps(), {}
        self.tick(ops, st)
        ops.drive = "Other Drive"
        ops.the_plan["volume"] = dict(ops.the_plan["volume"], name="Other Drive")
        st["scan"]["plan"] = dict(st["scan"]["plan"], volume={"name": "My Passport"})
        self.assertEqual(self.tick(ops, st), "scan", "the plan named a drive that is gone")

    def test_the_plan_reads_plainly(self):
        plan = FakeArchiveOps().the_plan
        plan["keep"] = [{"name": "2026-09-23", "mb": 23200, "keep": "changed 14 days ago"}]
        lines = g.archive_lines(plan)
        self.assertIn("Not used for 30+ days", lines[0])
        self.assertIn("Total 5.0 GB in 2 folders.", lines[3])
        self.assertIn("2026-09-23: changed 14 days ago", lines[5])
        self.assertIn("Destination: My Passport (2930 GB free)", lines[-1])
        one = dict(plan, move=plan["move"][:1], mb=plan["move"][0]["mb"])
        self.assertIn("1 folder in Codex has not been used for 30+ days and takes 3.0 GB", g.archive_text(one, 19.2))
        self.assertIn("Move it to My Passport?", g.archive_text(one, None))
        nowhere = dict(plan, volume=None, why="no external drive is connected")
        self.assertEqual(g.archive_lines(nowhere)[-1], "Destination: none (no external drive is connected)")

    def test_a_run_moves_reports_and_can_be_undone(self):
        import archive
        home, drive = self.tmp / "home", self.tmp / "drive"
        src = home / "Documents" / "Codex" / "2026-09-17"
        (src / "work").mkdir(parents=True)
        (src / "work" / "data.bin").write_bytes(b"d" * 500_000)
        blocked = home / "Documents" / "Codex" / "2026-09-18"
        blocked.mkdir()
        (blocked / "x").write_bytes(b"x")
        drive.mkdir()
        vol = {"name": "Drive", "path": str(drive), "base": str(drive), "free_mb": 9_000_000}
        cand = lambda p, **kw: dict({"root": str(p.parent), "name": p.name, "path": str(p), "mb": 1,
                                     "logical_mb": 1, "age_days": 40, "keep": ""}, **kw)
        plan = {"days": 30, "volume": vol, "why": "", "mb": 2, "keep": [],
                "move": [cand(src), cand(blocked, newest=1.0)]}       # the second changed after it was measured
        saved_home = archive.HOME
        archive.HOME = home
        self.addCleanup(setattr, archive, "HOME", saved_home)
        said = []
        res = g.archive_run(self.cfg, plan, out=said.append)
        self.assertEqual(([r["name"] for r in res["moved"]], [r["name"] for r in res["kept"]]),
                         (["2026-09-17"], ["2026-09-18"]))
        self.assertFalse(src.exists())
        self.assertTrue(blocked.exists())
        tar = drive / "Guardian Archive" / g.HOSTNAME / "Documents" / "Codex" / "2026-09-17.tar"
        self.assertTrue(tar.exists())
        self.assertIn("Moved 1 folder", res["text"])
        self.assertIn("This Mac now has 24.9 GB free", res["text"])
        self.assertIn("1 stayed: 2026-09-18 (it changed after it was measured)", res["text"])
        self.assertEqual(self.phases(), ["started", "moved", "kept", "done"])
        self.assertIn("## Archive", g.render_report(1))
        self.assertIn("Moved 1 folder", g.render_report(1))
        # only one run at a time
        import fcntl
        with open(g.LOG_DIR / "archive.lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.assertTrue(g.archive_run(self.cfg, plan, out=said.append).get("busy"))
        # and back again, from the command line
        import contextlib
        import io
        args = g.argparse.Namespace(offer=None, list=False, restore="2026-09-17", announce=False, yes=False,
                                    older_than=None, to=None, only=None, root=None, second_copy=False, second_home=None, check=False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            g.archive_cmd(self.cfg, args)
            g.archive_cmd(self.cfg, g.argparse.Namespace(**dict(vars(args), restore=None, list=True)))
        self.assertIn("back at", buf.getvalue())
        self.assertIn("Nothing has been moved to a drive.", buf.getvalue())
        self.assertEqual((src / "work" / "data.bin").read_bytes(), b"d" * 500_000)
        self.assertTrue(tar.exists(), "the drive keeps its copy")

    def test_the_agent_says_which_folders_macos_keeps_from_it(self):
        import archive
        home = self.tmp / "home"
        for n in ("Documents/Codex", "Downloads", "Desktop"):
            (home / n).mkdir(parents=True)
        saved = (g.HOME, archive.HOME, archive.volumes)
        g.HOME = archive.HOME = home
        archive.volumes = lambda: []

        def restore():
            g.HOME, archive.HOME, archive.volumes = saved
            g.os.chmod(home / "Documents", 0o755)
        self.addCleanup(restore)
        a = g.access_check(self.cfg)
        self.assertEqual((a["ok"], a["blocked"]), (["~/Documents", "~/Downloads", "~/Desktop", "~/Documents/Codex"], []))
        g.os.chmod(home / "Documents", 0o000)
        if g.os.access(home / "Documents", g.os.R_OK):
            self.skipTest("running as a user who can read anything")
        a = g.access_report(self.cfg)
        self.assertEqual(a["blocked"], ["~/Documents"], "the root inside it is not named twice")
        self.assertEqual(a["ok"], ["~/Downloads", "~/Desktop"])
        g.access_report(self.cfg)
        events = [e for e in g.read_events(1) if e["kind"] == "access"]
        self.assertEqual([e["notified"] for e in events], [True, False], "said once, not at every start")
        self.assertEqual(events[0]["blocked"], ["~/Documents"])
        # the plan says so instead of "nothing to move"
        plan = g.archive_plan(self.cfg)
        self.assertEqual(plan["problems"], [[str(home / "Documents" / "Codex"), "macOS will not let this program read it"]])
        lines = g.archive_lines(plan)
        self.assertEqual(lines[0], "Could not look in ~/Documents/Codex: macOS will not let this program read it.")
        self.assertNotIn("No work folder has been unused", "\n".join(lines))
        help_text = "\n".join(g.access_help("/Library/Developer/X/Python.app/Contents/MacOS/Python"))
        self.assertIn("Full Disk Access", help_text)
        self.assertIn("  /Library/Developer/X/Python.app\n", help_text)
        self.assertIn("guardian.py install", help_text)

    def test_the_helper_is_started_as_the_real_program_not_a_launcher_stub(self):
        # the first real Mac: the same permission was refused when the job was started through
        # /usr/bin/python3 (a stub) and honoured when started as the program the stub runs
        real = g.real_program(g.sys.executable)
        self.assertTrue(g.os.access(real, g.os.X_OK))
        self.assertEqual(g.real_program(real), real, "already the real program: unchanged")
        self.assertEqual(g.real_program("/nonexistent/python3"), "/nonexistent/python3", "cannot tell: left alone")
        picked = g.pick_python()
        self.assertTrue(g.os.access(picked, g.os.X_OK))
        self.assertIn(f"<string>{picked}</string>", g.plist_text(g.Path("/x/guardian.py"), self.cfg, picked))

    def test_an_archive_with_one_home_is_flagged_until_it_has_two(self):
        # the first real Mac: three work folders moved to one USB drive and removed from the Mac
        import archive
        home, first, second = self.tmp / "home", self.tmp / "first", self.tmp / "second"
        saved_home = archive.HOME
        archive.HOME = home
        self.addCleanup(setattr, archive, "HOME", saved_home)
        for name in ("2026-09-17", "2026-10-01"):
            src = home / "Documents" / "Codex" / name
            (src / "work").mkdir(parents=True)
            (src / "work" / "data.bin").write_bytes(name.encode() * 40_000)
            folder = first / "Guardian Archive" / "Mac" / "Documents" / "Codex"
            r = archive.archive_one({"path": str(src), "root": str(src.parent), "name": name, "mb": 1}, folder,
                                    manifest=g.archive_manifest(), host="Mac")
            self.assertTrue(r["ok"], r)
        homes = g.archive_homes(self.cfg)
        self.assertEqual((homes["total"], len(homes["single"]), len(homes["reachable"]), homes["other"]), (2, 2, 2, None))
        menu = {"homes": homes, "access": {"blocked": []}, "archive_state": {}, "activity_age": lambda a: None,
                "background": g.Background(), "dirty": False, "last_action": None}
        snap = {"sample": sample(level=1, free=60, disk=100), "groups": [], "quiet": ""}
        issue = [i for i in g.build_issues(self.cfg, snap, menu) if i["id"] == "one-copy"][0]
        self.assertEqual(issue["title"], f"2 archived folders exist only on {homes['drive']}")
        self.assertIn("If that drive fails, it is gone.", issue["detail"])
        self.assertEqual(issue["action"], {"id": "second_copy", "label": "How to make a second copy", "args": {}},
                         "no second drive connected: explain, do not guess a place")
        g.handle_request({"action": "second_copy", "ts": g.time.time()}, self.cfg, menu)
        self.assertIn("a single drive is not a backup", (g.LOG_DIR / "second-copy.txt").read_text())
        # a second drive is connected: the button names it, and the copy is checked
        second.mkdir()
        archive.volumes = lambda: [{"name": "Backup", "path": str(second), "fs": "apfs", "free_mb": 900_000}]
        archive._same_disk = lambda a, b: False
        homes = g.archive_homes(self.cfg)
        menu["homes"] = homes
        issue = [i for i in g.build_issues(self.cfg, snap, menu) if i["id"] == "one-copy"][0]
        self.assertEqual(issue["action"], {"id": "second_copy", "label": "Copy them to Backup too",
                                           "args": {"to": str(second)}})
        g.handle_request({"action": "second_copy", "to": str(second), "ts": g.time.time()}, self.cfg, menu)
        menu["background"].thread.join(20)
        self.assertIn("2 archived folders (0.0 GB) now also on second; each copy was checked.", menu["last_action"]["text"])
        copy = second / "Guardian Archive" / "Mac" / "Documents" / "Codex" / "2026-09-17.tar"
        self.assertEqual(copy.read_bytes(), (first / "Guardian Archive/Mac/Documents/Codex/2026-09-17.tar").read_bytes())
        self.assertEqual(menu["homes"]["single"], [])
        self.assertEqual([i for i in g.build_issues(self.cfg, snap, menu) if i["id"] == "one-copy"], [])
        # the second drive is unplugged again: the copies are remembered
        import shutil
        archive.volumes = lambda: []
        shutil.move(str(second), str(self.tmp / "unplugged"))
        self.assertEqual(g.archive_homes(self.cfg)["single"], [])
        # the first drive dies: the folder comes back from the second copy
        shutil.move(str(self.tmp / "unplugged"), str(second))
        shutil.rmtree(first)
        import contextlib
        import io
        args = g.argparse.Namespace(offer=None, list=False, restore="2026-09-17", announce=False, yes=False,
                                    older_than=None, to=None, only=None, root=None, second_copy=False, second_home=None, check=False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            g.archive_cmd(self.cfg, args)
            g.archive_cmd(self.cfg, g.argparse.Namespace(**dict(vars(args), restore=None, list=True)))
        self.assertIn("back at", buf.getvalue())
        self.assertEqual((home / "Documents/Codex/2026-09-17/work/data.bin").read_bytes(), b"2026-09-17" * 40_000)
        self.assertIn("second copy: " + str(second), buf.getvalue())
        self.assertIn("drive not connected", buf.getvalue())

    def test_your_own_copy_in_a_folder_you_name_counts(self):
        import archive
        import shutil
        home, first, cloud = self.tmp / "home", self.tmp / "first", self.tmp / "cloud" / "Backups"
        saved_home = archive.HOME
        archive.HOME = home
        self.addCleanup(setattr, archive, "HOME", saved_home)
        src = home / "Documents" / "Codex" / "2026-09-17"
        src.mkdir(parents=True)
        (src / "a.txt").write_bytes(b"a" * 9000)
        folder = first / "Guardian Archive" / "Mac" / "Documents" / "Codex"
        archive.archive_one({"path": str(src), "root": str(src.parent), "name": src.name, "mb": 1}, folder,
                            manifest=g.archive_manifest(), host="Mac")
        shutil.copytree(first / "Guardian Archive", cloud / "Guardian Archive")      # dragged there in Finder
        self.assertEqual(len(g.archive_homes(self.cfg)["single"]), 1, "guardian does not know about that folder yet")
        cfg = g.json.loads(g.json.dumps(self.cfg))
        cfg["archive"]["second_homes"] = [str(cloud)]
        homes = g.archive_homes(cfg)
        self.assertEqual(homes["single"], [])
        rows = archive.read_manifest(g.archive_manifest())
        self.assertEqual([(r["kind"], r.get("verified")) for r in rows], [("archived", None), ("second", False)],
                         "found by name and size, and said to be unchecked")
        # a file of the same name but another size is not a copy
        other = cloud / "Guardian Archive" / "Mac" / "Documents" / "Codex" / "2026-09-17.tar"
        other.write_bytes(b"truncated")
        self.assertEqual(len(g.archive_homes(cfg)["single"]), 1, "the folder is there and the file no longer matches")

    def test_the_question_says_they_will_have_one_home(self):
        plan = FakeArchiveOps().the_plan
        self.assertIn("They will then exist only on My Passport until you make a second copy.", g.archive_text(plan, 19.0))

    def test_switching_the_offer_off_is_remembered(self):
        import contextlib
        import io
        args = g.argparse.Namespace(offer="off", list=False, restore=None, announce=False, yes=False,
                                    older_than=None, to=None, only=None, root=None, second_copy=False, second_home=None, check=False)
        with contextlib.redirect_stdout(io.StringIO()):
            g.archive_cmd(self.cfg, args)
        self.assertFalse(g.load_config(g.CONFIG_PATH)["archive"]["offer"])


class MenuTests(unittest.TestCase):
    """The shield in the menu bar: the helper publishes what is going on and takes clicks as
    small request files. Found on the first real day: 43 identical 'memory warn' notifications
    and nothing to click during a three-hour critical spell."""

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = g.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.saved = (g.CONFIG_DIR, g.CONFIG_PATH, g.CONFIG_HISTORY, g.LOG_DIR, g.EVENTS_PATH, g.PAUSE_PATH)
        g.CONFIG_DIR = self.tmp / "cfg"
        g.CONFIG_PATH = g.CONFIG_DIR / "config.json"
        g.CONFIG_HISTORY = g.CONFIG_DIR / "config-history.jsonl"
        g.PAUSE_PATH = g.CONFIG_DIR / "paused"
        g.LOG_DIR = self.tmp / "logs"
        g.EVENTS_PATH = g.LOG_DIR / "events.jsonl"
        self.cfg = g.load_config(g.Path("/nonexistent"))
        self.cfg["notify"] = False

    def tearDown(self):
        g.CONFIG_DIR, g.CONFIG_PATH, g.CONFIG_HISTORY, g.LOG_DIR, g.EVENTS_PATH, g.PAUSE_PATH = self.saved

    def snap(self, level=2, free=24, disk=30, chatgpt=10240, chrome=3100):
        return {"sample": dict(sample(level=level, free=free, disk=disk), swap_used_mb=9200, mem_total_mb=8192),
                "groups": [{"key": "ChatGPT", "rss_mb": chatgpt, "n": 118, "class": "ai_app"},
                           {"key": "Google Chrome", "rss_mb": chrome, "n": 29, "class": "browser"},
                           {"key": "Claude", "rss_mb": 1400, "n": 12, "class": "ai_app"}], "quiet": ""}

    def menu(self, age=60.0, **more):
        return dict({"dirty": False, "snap": None, "last_action": None, "background": g.Background(),
                     "archive_state": {}, "refresh_state": {}, "access": {"blocked": []},
                     "activity_age": lambda app: age}, **more)

    def click(self, req, menu=None, cfg=None):
        menu = menu or self.menu()
        changed = g.handle_request(dict(req, ts=g.time.time()), cfg or self.cfg, menu)
        if menu["background"].thread:
            menu["background"].thread.join(10)
        return changed, menu

    def test_tight_memory_is_quiet_and_a_critical_spell_speaks(self):
        procs = [P(1, "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT", rss_mb=9000)]
        g.classify(procs, self.cfg, UID)
        pressure = lambda cfg, **kw: [d for d in g.Engine(cfg).step(sample(**kw), procs)
                                      if d.action == "notify" and d.cls == "pressure"]
        self.assertEqual(self.cfg["notify_level"], "important")
        self.assertEqual(pressure(self.cfg, level=2, free=24), [], "tight is where a small Mac lives")
        crit = pressure(self.cfg, level=4, free=12)
        self.assertEqual(len(crit), 1)
        self.assertIn("Memory critical (free 12%). Biggest: ChatGPT 8.8GB.", crit[0].reason)
        loud = dict(self.cfg, notify_level="all")
        self.assertEqual(len(pressure(loud, level=2, free=24)), 1, "the old behaviour is one setting away")
        auto, review = g.split_tuning({"notify_level": "all", "refresh": {"agent_idle_minutes": 5}})
        self.assertEqual(auto, {}, "a diagnosis cannot make it louder or cut the idle wait below ten minutes")

    def test_what_needs_a_look_and_what_puts_a_dot_on_the_icon(self):
        state = lambda snap, menu: g.build_state(self.cfg, snap, menu)
        busy = state(self.snap(), self.menu(age=60.0))
        self.assertEqual((busy["headline"], busy["attention"]), ("Memory is tight", "none"))
        only = busy["issues"][0]
        self.assertEqual((only["severity"], only["title"]), ("info", "ChatGPT has grown to 10.0 GB"))
        self.assertTrue(only["action"]["busy"])
        self.assertIn("agent was working 1 min ago", only["action"]["warning"])
        idle = state(self.snap(), self.menu(age=3600.0))
        self.assertEqual((idle["attention"], idle["issues"][0]["severity"]), ("warn", "warn"),
                         "its agent is idle: a good moment, so the icon says so")
        self.assertEqual(idle["issues"][0]["action"], {"id": "refresh", "label": "Refresh ChatGPT",
                                                       "args": {"app": "ChatGPT"}, "busy": False, "warning": ""})
        crit = state(self.snap(level=4, free=12), self.menu(age=3600.0))
        self.assertEqual((crit["headline"], crit["attention"]), ("Memory is critically low", "crit"))
        self.assertEqual([i["id"] for i in crit["issues"]], ["memory-critical"], "one entry, one button")
        self.assertEqual(crit["issues"][0]["action"]["label"], "Refresh ChatGPT")
        calm = state(self.snap(level=1, free=60, chatgpt=2000), self.menu())
        self.assertEqual((calm["headline"], calm["attention"], calm["issues"]), ("All good", "none", []))
        # disk, permissions, Chrome and the archive each bring their own button
        plan = {"days": 30, "mb": 5148, "volume": {"name": "My Passport", "path": "/Volumes/My Passport"},
                "move": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}
        menu = self.menu(access={"blocked": ["~/Documents"]}, archive_state={"scan": {"ts": 0, "plan": plan}})
        saved = g.os.path.ismount
        g.os.path.ismount = lambda p: p == "/Volumes/My Passport"
        try:
            many = state(self.snap(disk=17, chrome=5600, chatgpt=1000), menu)
        finally:
            g.os.path.ismount = saved
        self.assertEqual([(i["id"], i["severity"], i["action"]["id"]) for i in many["issues"]],
                         [("disk-low", "warn", "reclaim"), ("access", "warn", "doctor"),
                          ("chrome", "info", "close_duplicate_tabs"), ("archive", "info", "archive")])
        self.assertIn("5.0 GB of old work folders can move to My Passport", many["issues"][3]["title"])
        self.assertEqual(many["top"][0], {"key": "ChatGPT", "gb": 1.0, "n": 118})
        self.assertEqual(many["settings"], {"mode": "nudge", "notify": False, "notify_level": "important",
                                            "refresh": {"ChatGPT": "ask"}, "archive_offer": True,
                                            "trim_auto": False})
        self.assertEqual((many["refreshable"], many["chrome_running"]), (["ChatGPT"], True))

    def test_the_status_file_is_whole_or_absent(self):
        st = g.build_state(self.cfg, self.snap(), self.menu())
        g.write_state(st)
        back = g.json.loads(g.state_path().read_text())
        self.assertEqual(back["headline"], "Memory is tight")
        self.assertAlmostEqual(back["ts"], g.time.time(), delta=5)
        self.assertEqual(sorted(g.os.listdir(g.LOG_DIR)), ["state.json"], "no half-written file left beside it")

    def test_clicks_arrive_in_order_once_and_stale_ones_are_dropped(self):
        d = g.requests_dir()
        d.mkdir(parents=True)
        now = g.time.time()
        (d / "1000-pause.json").write_text(g.json.dumps({"action": "pause", "minutes": 30, "ts": now}))
        (d / "1001-resume.json").write_text(g.json.dumps({"action": "resume", "ts": now}))
        (d / "0999-old.json").write_text(g.json.dumps({"action": "reclaim", "ts": now - 3600}))
        (d / "1002-broken.json").write_text("{not json")
        (d / "1003-list.json").write_text("[1, 2]")
        (d / ".1004-refresh.json.tmp").write_text(g.json.dumps({"action": "refresh", "ts": now}))
        self.assertEqual([r["action"] for r in g.read_requests()], ["pause", "resume"])
        self.assertEqual(g.os.listdir(d), [".1004-refresh.json.tmp"], "a file still being written is left alone")
        self.assertEqual(g.read_requests(), [])

    def test_pause_and_resume(self):
        self.assertIsNone(g.pause_until())
        _, menu = self.click({"action": "pause", "minutes": 60})
        self.assertAlmostEqual(g.pause_until(), g.time.time() + 3600, delta=5)
        self.assertIn("Paused for 1 hour:", menu["last_action"]["text"])
        paused = g.build_state(self.cfg, self.snap(level=4, free=10), menu)
        self.assertTrue(paused["paused"])
        self.assertTrue(paused["headline"].startswith("Paused until "))
        self.assertEqual((paused["issues"], paused["attention"]), ([], "none"), "paused means quiet")
        self.click({"action": "resume"})
        self.assertIsNone(g.pause_until())
        g.PAUSE_PATH.write_text("2026-11-10T08:00:00")           # written by an older `guardian.py pause`
        self.assertEqual(g.pause_until(), 0.0, "paused until resumed")

    def test_settings_from_the_menu_are_a_short_fixed_list(self):
        changed, _ = self.click({"action": "set", "key": "mode", "value": "act"})
        self.assertTrue(changed)
        self.click({"action": "set", "key": "notifications", "value": "none"})
        self.click({"action": "set", "key": "refresh", "app": "ChatGPT", "value": "auto"})
        self.click({"action": "set", "key": "archive_offer", "value": False})
        cfg = g.load_config(g.CONFIG_PATH)
        self.assertEqual((cfg["mode"], cfg["autopilot"], cfg["notify"], cfg["refresh"]["apps"]["ChatGPT"],
                          cfg["archive"]["offer"]), ("act", True, False, "auto", False))
        self.click({"action": "set", "key": "notifications", "value": "all"})
        cfg = g.load_config(g.CONFIG_PATH)
        self.assertEqual((cfg["notify"], cfg["notify_level"]), (True, "all"))
        before = g.CONFIG_PATH.read_text()
        for bad in ({"key": "refresh", "app": "Finder", "value": "auto"}, {"key": "mode", "value": "root"},
                    {"key": "protect", "value": []}, {"key": "renderers.kill_under_pressure", "value": True}):
            changed, menu = self.click(dict({"action": "set"}, **bad))
            self.assertFalse(changed)
            self.assertFalse(menu["last_action"]["ok"])
        self.assertEqual(g.CONFIG_PATH.read_text(), before, "nothing else can be changed by a click")
        g.undo_config_change()
        cfg = g.load_config(g.CONFIG_PATH)
        self.assertEqual((cfg["notify"], cfg["notify_level"]), (False, "important"), "and every click can be undone")

    def test_a_click_refreshes_only_a_listed_app_and_reports_back(self):
        ops = FakeOps()
        changed, menu = self.click({"action": "refresh", "app": "ChatGPT", "force": True}, self.menu(ops=ops))
        self.assertFalse(changed)
        self.assertEqual([c[0] for c in ops.calls], ["quit", "term", "clear", "reopen"])
        self.assertTrue(menu["last_action"]["ok"])
        self.assertIn("ChatGPT: memory", menu["last_action"]["text"])
        self.assertAlmostEqual(menu["refresh_state"]["ChatGPT"]["last"], g.time.time(), delta=5)
        self.assertTrue(menu["dirty"], "the icon is told at once")
        # its agent is working and the click did not say 'anyway': left alone
        ops = FakeOps(age=30.0)
        _, menu = self.click({"action": "refresh", "app": "ChatGPT"}, self.menu(ops=ops))
        self.assertEqual(ops.calls, [])
        self.assertFalse(menu["last_action"]["ok"])
        ops = FakeOps()
        _, menu = self.click({"action": "refresh", "app": "Google Chrome"}, self.menu(ops=ops))
        self.assertEqual(ops.calls, [])
        self.assertIn("not on the list", menu["last_action"]["text"])

    def test_other_clicks(self):
        import archive
        saved = archive.volumes
        archive.volumes = lambda: []
        self.addCleanup(setattr, archive, "volumes", saved)
        _, menu = self.click({"action": "archive"})
        self.assertIn("Plug in an external drive first", menu["last_action"]["text"])
        _, menu = self.click({"action": "rm -rf"})
        self.assertIsNone(menu["last_action"], "an unknown action does nothing")
        self.assertEqual([e["result"] for e in g.read_events(1) if e["kind"] == "menu"][-1], "unknown action; ignored")
        busy = self.menu()
        gate = g.threading.Event()
        busy["background"].submit("census", gate.wait)
        try:
            g.handle_request({"action": "reclaim", "ts": g.time.time()}, self.cfg, busy)
            self.assertIn("Busy with another job (census)", busy["last_action"]["text"])
        finally:
            gate.set()
        _, menu = self.click({"action": "report"})
        self.assertIn("# Guardian report", (g.LOG_DIR / "report-now.md").read_text())

    def test_the_menu_bar_app_starts_at_login_and_stays_quit_when_quit(self):
        text = g.menu_plist_text(g.Path("/Users/j/Applications/Guardian.app"))
        self.assertIn("<string>/Users/j/Applications/Guardian.app/Contents/MacOS/Guardian</string>", text)
        self.assertIn("<key>RunAtLoad</key><true/>", text)
        self.assertIn("<key>SuccessfulExit</key><false/>", text)


NODE = "/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node"


class AheadTests(unittest.TestCase):
    """Getting ahead of a bad spell. Measured on the first real Mac: ChatGPT was back at 10 GB
    half an hour after a refresh; 36 tool servers it had started for its threads had used no
    processor time in 90 minutes (1.1 GB); one thread had a 1.2 GB history; and swap climbing
    1 GB in ten minutes came before 19 of the day's 25 critical spells."""

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = g.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.saved = (g.CONFIG_DIR, g.CONFIG_PATH, g.CONFIG_HISTORY, g.LOG_DIR, g.EVENTS_PATH, g.PAUSE_PATH, g.HOME,
                      g.still_same_process, g.os.kill)
        g.CONFIG_DIR = self.tmp / "cfg"
        g.CONFIG_PATH = g.CONFIG_DIR / "config.json"
        g.CONFIG_HISTORY = g.CONFIG_DIR / "config-history.jsonl"
        g.PAUSE_PATH = g.CONFIG_DIR / "paused"
        g.LOG_DIR = self.tmp / "logs"
        g.EVENTS_PATH = g.LOG_DIR / "events.jsonl"
        g.HOME = self.tmp / "home"
        self.killed = []
        g.still_same_process = lambda p: True
        g.os.kill = lambda pid, sig: self.killed.append((pid, sig))
        self.cfg = g.load_config(g.Path("/nonexistent"))
        self.cfg["notify"] = False

    def tearDown(self):
        (g.CONFIG_DIR, g.CONFIG_PATH, g.CONFIG_HISTORY, g.LOG_DIR, g.EVENTS_PATH, g.PAUSE_PATH, g.HOME,
         g.still_same_process, g.os.kill) = self.saved

    def family(self, over=None):
        """ChatGPT as recorded: the app, the Codex engine, and the tool servers it starts per thread."""
        hour = 5400
        spec = {
            100: ("/Applications/ChatGPT.app/Contents/MacOS/ChatGPT", "", 1, 700, hour, 300),
            110: ("/Applications/ChatGPT.app/Contents/Resources/codex", " app-server", 100, 1100, hour, 900),
            201: (NODE, " ./mcp/launch.mjs", 110, 35, hour, 0.0),                 # never did anything
            202: (NODE, " ./server.mjs", 110, 35, hour, 0.3),                     # next to nothing
            203: (NODE, " scripts/mcp/server.mjs --stdio", 110, 30, hour, 6.0),   # worked earlier
            204: (NODE, " kernel.js --session-id c43", 110, 420, hour, 26.0),     # a live session with a child
            205: (NODE, " trusted-worker.js", 204, 200, hour, 9.0),
            206: (NODE, " ./mcp/launch.mjs", 110, 35, 600, 0.0),                  # ten minutes old
            300: ("/Applications/ChatGPT.app/Contents/Frameworks/ChatGPT Helper (Renderer).app/Contents/MacOS/"
                  "ChatGPT Helper (Renderer)", " --type=renderer", 100, 1400, hour, 50),
            400: ("/Applications/Claude.app/Contents/MacOS/Claude", "", 1, 800, hour, 100),
            401: ("/Applications/Claude.app/Contents/Resources/cua_node/bin/node", " ./server.mjs", 400, 60, hour, 0.0),
        }
        spec.update(over or {})
        procs = [P(pid, comm, comm + args, ppid=ppid, rss_mb=mb, age=age, cputime=cpu)
                 for pid, (comm, args, ppid, mb, age, cpu) in spec.items()]
        g.classify(procs, self.cfg, UID)
        return procs

    def test_only_old_idle_childless_helpers_of_a_listed_app_are_trimmed(self):
        procs, track, now = self.family(), {}, 1_000_000.0
        self.assertEqual({p.key for p in procs if p.pid in (201, 202, 203, 204, 205, 206, 300)}, {"ChatGPT"})
        g.helper_track(track, procs, self.cfg, now)
        self.assertEqual(sorted(track), [201, 202, 203, 204, 205, 206], "the app, its engine and its windows are not helpers")
        ids = lambda t: sorted(p.pid for p in g.trim_candidates("ChatGPT", procs, track, self.cfg, t))
        self.assertEqual(ids(now), [201, 202], "never worked, over an hour old")
        self.assertEqual(g.trim_candidates("Claude", procs, track, self.cfg, now), [], "Claude is not on the list")
        # 31 minutes later: the one that worked earlier has been quiet all that time; the young
        # one is now old enough but is still younger than an hour
        later = now + 31 * 60
        aged = self.family({203: (NODE, " scripts/mcp/server.mjs --stdio", 110, 30, 5400 + 1860, 6.0),
                            206: (NODE, " ./mcp/launch.mjs", 110, 35, 600 + 1860, 0.0),
                            202: (NODE, " ./server.mjs", 110, 35, 5400 + 1860, 2.5)})      # it just did some work
        g.helper_track(track, aged, self.cfg, later)
        self.assertEqual(ids(later), [201, 203])
        self.assertEqual(g.trim_summary(aged, track, self.cfg, later), [{"app": "ChatGPT", "n": 2, "mb": 65}])
        # a reused pid starts from scratch; a helper that quit is forgotten
        reused = [p for p in self.family({201: (NODE, " kernel.js", 110, 300, 5, 3.0)}) if p.pid != 203]
        g.helper_track(track, reused, self.cfg, later + 30)
        self.assertNotIn(203, track)
        self.assertEqual(track[201]["since"], later + 30)

    def test_trimming_asks_politely_and_only_when_told(self):
        procs, track, now = self.family(), {}, 1_000_000.0
        g.helper_track(track, procs, self.cfg, now)
        rec = g.trim_app("ChatGPT", self.cfg, procs, track, now, dry_run=True)
        self.assertEqual((rec["found"], rec["mb"], rec["closed"], self.killed), (2, 70, 0, []))
        rec = g.trim_app("ChatGPT", self.cfg, procs, track, now)
        self.assertEqual(sorted(self.killed), [(201, g.signal.SIGTERM), (202, g.signal.SIGTERM)], "a request to quit, never a kill")
        self.assertEqual(rec["closed"], 2)
        self.assertEqual([e["closed"] for e in g.read_events(1) if e["kind"] == "trim"], [0, 2])
        self.assertNotIn("trim.idle_minutes", g.TUNABLE, "a diagnosis cannot make trimming more eager")

    def test_helpers_of_a_thread_in_use_are_spared_where_guardian_can_tell(self):
        # the first real Mac: scripting helpers run in their thread's folder; the tool servers
        # run in a plugin folder and carry nothing that names a thread
        home = str(g.HOME)
        procs, track, now = self.family(), {}, 1_000_000.0
        g.helper_track(track, procs, self.cfg, now)
        cwds = {201: home + "/.codex/plugins/cache/data-analytics/1.1.0", 202: home + "/Documents/Codex/2026-09-09/i-x20"}
        ids = lambda in_use: sorted(p.pid for p in g.trim_candidates("ChatGPT", procs, track, self.cfg, now, cwds, in_use))
        self.assertEqual(ids(set()), [201, 202])
        self.assertEqual(ids({home + "/Documents/Codex/2026-09-09/i-x20"}), [201], "its thread is in use")
        self.assertEqual(ids({home + "/Documents/Codex/2026-09-09"}), [201], "a folder inside the thread's folder counts")
        self.assertEqual(ids({home + "/Documents/Codex/2026-11-06/i-fe"}), [201, 202], "another thread's folder does not")
        self.assertEqual(ids({home}), [201, 202], "a thread working in the home folder does not shield everything under it")
        cwds[202] = home
        self.assertEqual(ids({home}), [201], "but a helper working in home itself is tied to it")
        # which folders are in use comes from the threads written in the last half hour
        scan = {"threads": [{"cwd": "~/Documents/Codex/2026-09-09/i-x20", "idle_s": 30, "mb": 1231},
                            {"cwd": "~", "idle_s": 600, "mb": 2},
                            {"cwd": "~/Documents/Codex/2026-10-28/my-x20", "idle_s": 5900, "mb": 77},
                            {"cwd": "", "idle_s": 5, "mb": 1}]}
        self.assertEqual(g.dirs_in_use(scan, self.cfg), {home + "/Documents/Codex/2026-09-09/i-x20", home})
        self.assertEqual(g.dirs_in_use(None, self.cfg), set())
        # working folders are asked for once per helper and forgotten when it is gone
        cache = {5: "/old", 7: "/kept"}
        saved = g.IS_MAC
        g.IS_MAC = False
        try:
            self.assertEqual(g.helper_cwds(cache, [7, 9]), {7: "/kept", 9: ""})
        finally:
            g.IS_MAC = saved

    def test_trimming_by_itself_is_off_until_switched_on_and_says_what_it_did(self):
        procs, now = self.family(), 1_000_000.0
        menu = self.menu(trim=[{"app": "ChatGPT", "n": 2, "mb": 70}])
        g.helper_track(menu["helpers"], procs, self.cfg, now)
        cfg = g.json.loads(g.json.dumps(self.cfg))
        cfg["mode"] = "act"
        cfg["trim"]["min_mb"] = 50
        self.assertFalse(self.cfg["trim"]["auto"], "off by default")
        self.assertEqual(g.auto_trim(cfg, menu, procs, now, "early"), [])
        self.assertEqual(self.killed, [])
        cfg["trim"]["auto"] = True
        self.assertEqual(g.auto_trim(dict(cfg, mode="nudge"), menu, procs, now, "early"), [], "only in autopilot")
        small = dict(menu, trim=[{"app": "ChatGPT", "n": 2, "mb": 40}])
        self.assertEqual(g.auto_trim(cfg, small, procs, now, "early"), [], "too little to be worth it")
        self.assertEqual(self.killed, [])
        done = g.auto_trim(cfg, menu, procs, now, "early")
        self.assertEqual([(r["closed"], r["trigger"]) for r in done], [(2, "early")])
        self.assertEqual(sorted(pid for pid, _ in self.killed), [201, 202])
        self.assertIn("Memory was filling up fast, so Guardian closed 2 idle ChatGPT helpers", menu["last_action"]["text"])
        self.assertIn("If a tool in a thread stops responding, refresh the app.", menu["last_action"]["text"])
        self.assertTrue(menu["dirty"])
        # not again for half an hour, however the readings look
        self.killed.clear()
        menu["trim"] = [{"app": "ChatGPT", "n": 2, "mb": 70}]
        self.assertEqual(g.auto_trim(cfg, menu, procs, now + 600, "critical"), [])
        self.assertEqual(self.killed, [])
        self.assertEqual(len(g.auto_trim(cfg, menu, procs, now + 1900, "critical")), 1)
        self.assertIn("Memory was critically low", menu["last_action"]["text"])
        # the switch is one of the few settings the menu may change, and a diagnosis may not
        g.handle_request({"action": "set", "key": "trim_auto", "value": True, "ts": g.time.time()}, self.cfg, self.menu())
        self.assertTrue(g.load_config(g.CONFIG_PATH)["trim"]["auto"])
        auto, review = g.split_tuning({"trim": {"auto": True, "idle_minutes": 1}})
        self.assertEqual(auto, {})

    def test_swap_climbing_fast_is_the_early_warning(self):
        t0 = 1_000_000.0
        hist = lambda vals, step=30: [(t0 + i * step, v) for i, v in enumerate(vals)]
        last = lambda h: h[-1][0]
        # 21:53 to 22:03 on the first real day: 5.1 GB to 7.8 GB, then thirteen critical samples
        real = hist([5120 + i * 135 for i in range(21)])
        self.assertEqual(g.swap_climb(real, last(real), 600, 1000), 2700)
        slow = hist([8400 + i * 30 for i in range(21)])
        self.assertEqual(g.swap_climb(slow, last(slow), 600, 1000), 0.0, "0.6 GB in ten minutes is ordinary")
        falling = hist([9000 - i * 100 for i in range(21)])
        self.assertEqual(g.swap_climb(falling, last(falling), 600, 1000), 0.0)
        dip = hist([9000] * 8 + [7000] * 4 + [8600] * 8)
        self.assertEqual(g.swap_climb(dip, last(dip), 600, 1000), 1600, "measured from the lowest point in the window")
        asleep = [(t0, 3000), (t0 + 30, 3000)] + [(t0 + 3600 + i * 30, 6000) for i in range(4)]
        self.assertEqual(g.swap_climb(asleep, last(asleep), 600, 1000), 0.0, "a lid closed for an hour is not a climb")
        self.assertEqual(g.swap_climb(real[:4], last(real[:4]), 600, 100), 0.0, "four readings prove nothing")
        self.assertEqual(g.swap_climb([], t0, 600, 1000), 0.0)

    def test_long_threads_and_how_many_are_active(self):
        import os
        sess = g.HOME / ".codex" / "sessions"
        now = g.time.time()

        def thread(rel, mb, minutes_ago, cwd):
            p = sess / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "wb") as f:
                f.write(('{"type":"session_meta","payload":{"id":"x","cwd":%s}}\n' % g.json.dumps(cwd)).encode())
                f.truncate(max(mb * 1048576, 200))          # size on paper; no disk used
            os.utime(p, (now - minutes_ago * 60,) * 2)
        home = str(g.HOME)
        thread("2026/09/09/rollout-2026-09-09T16-59-02-aaa.jsonl", 1231, 0, home + "/Documents/Codex/2026-09-09/i-x20")
        thread("2026/11/06/rollout-2026-11-06T09-00-00-bbb.jsonl", 57, 1, home + "/Documents/Codex/2026-11-06/i-fe")
        thread("2026/11/10/rollout-2026-11-10T21-00-00-ccc.jsonl", 2, 11, home)
        thread("2026/11/10/rollout-2026-11-10T21-33-00-ddd.jsonl", 0, 95, home)       # touched when the app reopened
        thread("2026/10/28/rollout-2026-10-28T10-00-00-eee.jsonl", 77, 56, home + "/Documents/Codex/2026-10-28/my-x20")
        thread("2026/10/01/rollout-2026-10-01T10-00-00-fff.jsonl", 900, 600, home)    # not touched for ten hours
        (sess / "2026/11/10/notes.txt").write_text("not a thread")
        scan = g.thread_scan(self.cfg, now)
        self.assertEqual([t["mb"] for t in scan["threads"]], [1231, 77, 57, 2, 0])
        self.assertEqual(scan["active"], 3, "written in the last half hour and not empty")
        big = scan["big"]
        self.assertEqual([(t["mb"], t["started"], t["cwd"]) for t in big],
                         [(1231, "2026-09-09", "~/Documents/Codex/2026-09-09/i-x20")])
        text = g.render_threads(scan, self.cfg)
        self.assertIn("1231 MB   started 2026-09-09   last written    just now   ~/Documents/Codex/2026-09-09/i-x20   <-- long history", text)
        self.assertIn("start a new thread", text)
        self.assertEqual((sess / "2026/11/06/rollout-2026-11-06T09-00-00-bbb.jsonl").stat().st_size, 57 * 1048576,
                         "reading never writes")

    def snap(self, level=2, free=24):
        return {"sample": dict(sample(level=level, free=free, disk=30), swap_used_mb=7800, mem_total_mb=8192),
                "groups": [{"key": "ChatGPT", "rss_mb": 10100, "n": 113, "class": "ai_app"},
                           {"key": "Google Chrome", "rss_mb": 3100, "n": 29, "class": "browser"}], "quiet": ""}

    def menu(self, **more):
        return dict({"dirty": False, "snap": None, "last_action": None, "background": g.Background(),
                     "archive_state": {}, "refresh_state": {}, "access": {"blocked": []}, "helpers": {},
                     "activity_age": lambda app: 30.0, "trim": [], "threads": None, "early": None}, **more)

    def test_the_gentlest_fix_is_offered_first(self):
        trim = [{"app": "ChatGPT", "n": 33, "mb": 1100}]
        ids = lambda st: [(i["id"], i["severity"], (i.get("action") or {}).get("id")) for i in st["issues"]]
        early = {"until": g.time.time() + 600, "rise_mb": 2700, "minutes": 10}
        st = g.build_state(self.cfg, self.snap(), self.menu(trim=trim, early=early))
        self.assertEqual(ids(st), [("filling", "warn", "trim"), ("grown:ChatGPT", "info", "refresh")])
        self.assertEqual(st["attention"], "warn", "the dot comes on before the slow spell")
        self.assertIn("Swap grew 2.6 GB in the last 10 minutes", st["issues"][0]["detail"])
        self.assertEqual(st["issues"][0]["action"]["label"], "Trim idle ChatGPT helpers")
        self.assertEqual(st["trim"], trim)
        # nothing to trim: the warning falls back to the refresh, and says its agent is busy
        st = g.build_state(self.cfg, self.snap(), self.menu(early=early))
        self.assertEqual(ids(st), [("filling", "warn", "refresh")])
        self.assertTrue(st["issues"][0]["action"]["busy"])
        # the warning lapses on its own
        st = g.build_state(self.cfg, self.snap(), self.menu(trim=trim, early=dict(early, until=g.time.time() - 1)))
        self.assertEqual(ids(st), [("grown:ChatGPT", "info", "refresh"), ("trim:ChatGPT", "info", "trim")])
        self.assertEqual(st["attention"], "none")
        self.assertIn("33 idle ChatGPT helpers hold 1.1 GB", st["issues"][1]["title"])
        # critical: trim first there too, and it is not listed twice
        st = g.build_state(self.cfg, self.snap(level=4, free=12), self.menu(trim=trim, early=early))
        self.assertEqual(ids(st), [("memory-critical", "crit", "trim"), ("grown:ChatGPT", "info", "refresh")])
        # too little to be worth a click
        st = g.build_state(self.cfg, self.snap(), self.menu(trim=[{"app": "ChatGPT", "n": 3, "mb": 90}]))
        self.assertEqual(ids(st), [("grown:ChatGPT", "info", "refresh")])
        # threads
        heavy = {"mb": 1231, "started": "2026-09-09", "cwd": "~/x", "idle_s": 5, "file": "f"}
        st = g.build_state(self.cfg, self.snap(), self.menu(threads={"ts": 0, "active": 4, "threads": [heavy], "big": [heavy]}))
        thread = [i for i in st["issues"] if i["id"] == "threads"][0]
        self.assertEqual(thread["title"], "One agent thread has a 1.2 GB history")
        self.assertIn("Started 2026-09-09.", thread["detail"])
        self.assertIn("4 threads are active at once", thread["detail"])
        st = g.build_state(self.cfg, self.snap(), self.menu(threads={"ts": 0, "active": 5, "threads": [], "big": []}))
        self.assertEqual([i["title"] for i in st["issues"] if i["id"] == "threads"], ["5 agent threads are active at once"])
        st = g.build_state(self.cfg, self.snap(), self.menu(threads={"ts": 0, "active": 2, "threads": [], "big": []}))
        self.assertEqual([i for i in st["issues"] if i["id"] == "threads"], [])

    def test_clicks_for_trim_and_threads(self):
        procs = self.family()
        menu = self.menu(procs=lambda: procs)
        g.helper_track(menu["helpers"], procs, self.cfg, g.time.time())
        g.handle_request({"action": "trim", "app": "ChatGPT", "ts": g.time.time()}, self.cfg, menu)
        self.assertEqual(sorted(pid for pid, _ in self.killed), [201, 202])
        self.assertIn("Closed 2 idle ChatGPT helpers, about 0.1 GB. ChatGPT itself was not touched.", menu["last_action"]["text"])
        self.killed.clear()
        g.handle_request({"action": "trim", "app": "Claude", "ts": g.time.time()}, self.cfg, menu)
        self.assertEqual(self.killed, [])
        self.assertFalse(menu["last_action"]["ok"])
        g.handle_request({"action": "threads", "ts": g.time.time()}, self.cfg, menu)
        self.assertIn("Agent threads written in the last 2 hours: 0", (g.LOG_DIR / "threads-now.txt").read_text())


# vm_stat exactly as the first real Mac printed it while it was thrashing (2026-11-11 00:14)
VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                     5298.
Pages active:                                  45745.
Pages inactive:                                42458.
Pages speculative:                              1252.
Pages throttled:                                   0.
Pages wired down:                             153255.
Pages purgeable:                                   0.
"Translation faults":                     2412686733.
Pages copy-on-write:                        14841133.
Pages zero filled:                         408213986.
Pages reactivated:                        1366109996.
Pages purged:                               46595456.
File-backed pages:                             35033.
Anonymous pages:                               54422.
Pages stored in compressor:                   417704.
Pages occupied by compressor:                 238673.
Decompressions:                           1520319111.
Compressions:                             1578748313.
Pageins:                                   201564301.
Pageouts:                                     943631.
Swapins:                                   143729787.
Swapouts:                                  148099631.
"""


class LagTests(unittest.TestCase):
    """What slowness on a small Mac actually is. Measured on the first real one under heavy
    use: 160-190 MB swapped in and 650-1400 MB decompressed every second, the app in front
    with 11% of its memory in RAM, and macOS reporting 'level 2, 26% free' the whole time."""

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = g.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.saved = (g.LOG_DIR, g.EVENTS_PATH, g.SAMPLES_PATH, g.PAUSE_PATH, g.CONFIG_DIR)
        g.LOG_DIR = self.tmp / "logs"
        g.EVENTS_PATH = g.LOG_DIR / "events.jsonl"
        g.SAMPLES_PATH = g.LOG_DIR / "samples.tsv"
        g.CONFIG_DIR = self.tmp / "cfg"
        g.PAUSE_PATH = g.CONFIG_DIR / "paused"
        self.cfg = g.load_config(g.Path("/nonexistent"))
        self.cfg["notify"] = False

    def tearDown(self):
        g.LOG_DIR, g.EVENTS_PATH, g.SAMPLES_PATH, g.PAUSE_PATH, g.CONFIG_DIR = self.saved

    def later(self, seconds, swapin_mb_s, decompress_mb_s):
        """The same vm_stat a while later, having moved this much per second."""
        page = 16384
        bump = lambda name, mb_s: lambda m: f"{name}:{' ' * 20}{int(m.group(1)) + int(mb_s * seconds * 1048576 / page)}."
        text = g.re.sub(r"Swapins:\s+(\d+)\.", bump("Swapins", swapin_mb_s), VM_STAT)
        text = g.re.sub(r"Decompressions:\s+(\d+)\.", bump("Decompressions", decompress_mb_s), text)
        return text

    def test_the_rate_of_shuffling_is_read_from_vm_stat(self):
        a = g.vm_counters(VM_STAT)
        self.assertAlmostEqual(a["Swapins"], 143729787 * 16384 / 1048576)
        self.assertEqual(sorted(a), ["Compressions", "Decompressions", "Swapins", "Swapouts"])
        b = g.vm_counters(self.later(10, 161.9, 652.3))
        r = g.vm_rates(a, b, 10.0)
        self.assertEqual((r["swapin_mb_s"], r["decompress_mb_s"], r["swapout_mb_s"]), (161.9, 652.3, 0.0))
        self.assertIsNone(g.vm_rates(None, b, 10.0), "the first reading has nothing to compare with")
        self.assertIsNone(g.vm_rates(a, b, 2.0), "two readings a moment apart are noise")
        self.assertIsNone(g.vm_rates(a, b, 3600.0), "the Mac slept in between")
        self.assertIsNone(g.vm_rates(b, a, 10.0), "totals went backwards: a restart")
        self.assertIsNone(g.vm_counters("Pages free: 12."), "not vm_stat output")
        self.assertIsNone(g.vm_counters(""))

    def test_slow_and_very_slow(self):
        lvl = lambda si, de: g.lag_level({"swapin_mb_s": si, "decompress_mb_s": de}, self.cfg)
        self.assertEqual(lvl(161.9, 652.3), "severe", "the first real reading")
        self.assertEqual(lvl(187.7, 1392.3), "severe")
        self.assertEqual(lvl(12.0, 850.0), "severe", "squeezing alone can be the whole lag")
        self.assertEqual(lvl(45.0, 120.0), "slow")
        self.assertEqual(lvl(4.0, 310.0), "slow")
        self.assertEqual(lvl(3.0, 40.0), "none")
        self.assertEqual(g.lag_level({"swapin_mb_s": None, "decompress_mb_s": None}, self.cfg), "none", "no reading yet")
        self.assertEqual(g.lag_level({}, self.cfg), "none")
        auto, review = g.split_tuning({"lag": {"swapin_mb_s": 50, "severe_swapin_mb_s": 5}})
        self.assertEqual((auto, review), ({"lag": {"swapin_mb_s": 50}}, {"lag": {"severe_swapin_mb_s": 5}}))

    def real(self, **over):
        """The moment as measured: macOS says level 2 and 26% free."""
        return dict(sample(level=2, free=26, disk=28), swap_used_mb=7122, mem_total_mb=8192,
                    swapin_mb_s=161.9, decompress_mb_s=652.3, **over)

    def test_thrashing_counts_as_critical_whatever_macos_says(self):
        self.assertTrue(g.is_critical(self.real(), self.cfg))
        self.assertFalse(g.is_critical(dict(self.real(), swapin_mb_s=3.0, decompress_mb_s=40.0), self.cfg))
        self.assertTrue(g.under_pressure(dict(sample(level=1, free=60), swapin_mb_s=45.0, decompress_mb_s=100.0), self.cfg))
        procs = [P(1, "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT", rss_mb=5400)]
        g.classify(procs, self.cfg, UID)
        said = [d for d in g.Engine(self.cfg).step(self.real(), procs) if d.action == "notify" and d.cls == "pressure"]
        self.assertEqual(len(said), 1, "the default is to speak up only when it is serious; this is")
        self.assertIn("The Mac is slow: 162 MB a second of memory is going to and from disk (free 26%). Biggest: ChatGPT 5.3GB.",
                      said[0].reason)
        self.assertEqual(said[0].severity, "crit")

    def test_the_menu_says_why_it_is_slow_and_who_has_the_ram(self):
        groups = [{"key": "ChatGPT", "rss_mb": 5570, "res_mb": 625, "n": 60, "class": "ai_app"},
                  {"key": "Google Chrome", "rss_mb": 4830, "res_mb": 870, "n": 33, "class": "browser"},
                  {"key": "Claude", "rss_mb": 1480, "res_mb": 225, "n": 13, "class": "ai_app"}]
        menu = {"access": {"blocked": []}, "archive_state": {}, "activity_age": lambda a: 30.0, "background": g.Background(),
                "trim": [{"app": "ChatGPT", "n": 40, "mb": 900}], "last_action": None}
        st = g.build_state(self.cfg, {"sample": self.real(), "groups": groups, "quiet": "", "front": "ChatGPT"}, menu)
        self.assertEqual((st["headline"], st["attention"]), ("Very slow: memory is being shuffled to disk", "crit"))
        self.assertEqual(st["lag"], {"level": "severe", "swapin_mb_s": 161.9, "decompress_mb_s": 652.3})
        top = st["issues"][0]
        self.assertEqual((top["id"], top["title"]), ("memory-critical", "This Mac is very slow right now"))
        self.assertEqual(top["detail"], "162 MB of memory a second is being read back from disk. ChatGPT, in front, has 11% "
                                        "of its memory in RAM. Google Chrome, in the background, is holding 0.8 GB of RAM.")
        self.assertEqual(top["action"]["id"], "trim", "the gentlest help first")
        slow = dict(self.real(), swapin_mb_s=45.0, decompress_mb_s=120.0)
        st = g.build_state(self.cfg, {"sample": slow, "groups": groups, "quiet": "", "front": "Claude"}, menu)
        self.assertEqual((st["headline"], st["attention"], st["issues"][0]["id"], st["issues"][0]["title"]),
                         ("Slowing down: memory is being shuffled", "warn", "lag", "Things are slowing down"))
        self.assertIn("Claude, in front, has 15% of its memory in RAM. Google Chrome, in the background, is holding 0.8 GB",
                      st["issues"][0]["detail"])
        squeezing = dict(self.real(), swapin_mb_s=12.1, decompress_mb_s=388.5)      # 00:35 on the first real night
        st = g.build_state(self.cfg, {"sample": squeezing, "groups": groups, "quiet": "", "front": "TextEdit"}, menu)
        self.assertTrue(st["issues"][0]["detail"].startswith(
            "389 MB of memory a second is being squeezed and unsqueezed to make room. Google Chrome, in the background,"))
        calm = dict(self.real(), swapin_mb_s=2.0, decompress_mb_s=30.0)
        st = g.build_state(self.cfg, {"sample": calm, "groups": groups, "quiet": ""}, menu)
        self.assertEqual((st["headline"], st["lag"]["level"]), ("Memory is tight", "none"))

    def test_in_ram_is_kept_apart_from_what_an_app_wants(self):
        procs = [P(1, "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT", rss_mb=600),
                 P(2, "/Applications/ChatGPT.app/Contents/Frameworks/ChatGPT Helper (Renderer).app/Contents/MacOS/"
                      "ChatGPT Helper (Renderer)", "x --type=renderer", ppid=1, rss_mb=300)]
        procs[0].rss_kb, procs[1].rss_kb = 5000 * 1024, 2000 * 1024        # the full footprint, as libproc reports it
        g.classify(procs, self.cfg, UID)
        grp = g.aggregate(procs, self.cfg)[0]
        self.assertEqual((grp["key"], grp["rss_mb"], grp["res_mb"]), ("ChatGPT", 7000, 900))

    def test_the_diary_keeps_the_rates(self):
        g.log_sample(self.real(), [{"key": "ChatGPT", "rss_mb": 5570}])
        g.log_sample(sample(level=1, free=60), [])
        lines = g.SAMPLES_PATH.read_text().splitlines()
        self.assertTrue(lines[0].endswith("\ttop\tswapin_mb_s\tdecompress_mb_s"))
        self.assertTrue(lines[1].endswith("\tChatGPT=5570\t161.9\t652.3"))
        self.assertTrue(lines[2].endswith("\t\t\t"), "no reading is an empty cell, not a zero")
        self.assertEqual(lines[1].split("\t")[6], "28", "older columns stay where every reader expects them")

    def test_the_status_page_says_one_thing_to_this_mac_only(self):
        import urllib.error
        import urllib.request
        saved = dict(g.LINK)
        self.addCleanup(lambda: g.LINK.update(saved))
        server = g.start_status_server(0)
        self.addCleanup(lambda: (server.shutdown(), server.server_close()))
        host, port = server.server_address
        self.assertEqual(host, "127.0.0.1")
        g.LINK.update(lag="severe", ts=123.0, seen=0.0)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=5) as r:
            body = g.json.loads(r.read())
        self.assertEqual(body, {"v": 1, "lag": "severe", "ts": 123.0}, "how the Mac is doing, and nothing else")
        self.assertAlmostEqual(g.LINK["seen"], g.time.time(), delta=5)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/events", timeout=5)
        self.assertEqual(cm.exception.code, 404)
        self.assertIsNone(g.start_status_server(port), "a taken port is reported, not fatal")


class AutopilotTests(unittest.TestCase):
    """Bounded self-tuning, config history/undo, and the hygiene schedule."""

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = g.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.saved = (g.CONFIG_DIR, g.CONFIG_PATH, g.CONFIG_HISTORY, g.LOG_DIR, g.EVENTS_PATH)
        g.CONFIG_DIR = self.tmp / "cfg"
        g.CONFIG_PATH = g.CONFIG_DIR / "config.json"
        g.CONFIG_HISTORY = g.CONFIG_DIR / "config-history.jsonl"
        g.LOG_DIR = self.tmp / "logs"
        g.EVENTS_PATH = g.LOG_DIR / "events.jsonl"

    def tearDown(self):
        g.CONFIG_DIR, g.CONFIG_PATH, g.CONFIG_HISTORY, g.LOG_DIR, g.EVENTS_PATH = self.saved

    # ---- found on the first real Mac: the auto-diagnosis ran against a logged-out claude CLI

    def _fake_cli(self, body: str) -> str:
        cli = self.tmp / "claude"
        cli.write_text("#!/bin/sh\n" + body + "\n")
        cli.chmod(0o755)
        return str(cli)

    def _ask_with(self, body: str):
        cfg = g.load_config(g.Path("/nonexistent"))
        cfg["notify"] = False
        cfg["ai"]["timeout_seconds"] = 20
        exe = self._fake_cli(body)
        saved = g.find_ai_command, g.snapshot
        g.find_ai_command = lambda cfg: ("claude", exe)
        g.snapshot = lambda cfg: {"sample": {"ts": 0}, "groups": [], "classes": {}}
        try:
            outcome = {}
            return g.ask(cfg, hours=1, quiet=True, outcome=outcome), outcome
        finally:
            g.find_ai_command, g.snapshot = saved

    def test_ask_failure_recognises_what_is_not_a_diagnosis(self):
        self.assertEqual(g.ask_failure(1, "Not logged in \u00b7 Please run /login"), "not logged in")
        self.assertEqual(g.ask_failure(0, "Invalid API key \u00b7 Please run /login"), "not logged in")
        self.assertEqual(g.ask_failure(0, ""), "printed nothing")
        self.assertTrue(g.ask_failure(2, "error: unknown option --output-format").startswith("exit 2: error"))
        real = "## What is actually slowing this Mac down\n- ChatGPT holds 9GB...\n" + "x" * 500
        self.assertEqual(g.ask_failure(0, real), "")
        self.assertEqual(g.ask_failure(0, real + "\nIf you see 401 errors, run /login."), "",
                         "a long real answer that mentions login is still a diagnosis")

    def test_logged_out_cli_is_a_failed_ask_not_a_diagnosis(self):
        path, outcome = self._ask_with('echo "Not logged in \u00b7 Please run /login"; exit 1')
        self.assertIsNone(path)
        self.assertEqual((outcome["result"], outcome["reason"]), ("failed", "not logged in"))
        self.assertEqual(list(g.LOG_DIR.glob("diagnosis-*.md")), [], "no diagnosis file for a login error")
        ev = [e for e in g.read_events(1) if e["kind"] == "ask"]
        self.assertEqual([(e["result"], e["reason"]) for e in ev], [("failed", "not logged in")])

    def test_real_answer_is_saved_and_its_suggestion_kept_for_review(self):
        body = ("cat <<'EOF'\n## What is actually slowing this Mac down\n- ChatGPT\n\n"
                "```json guardian-suggestion\n{\"notify_cooldown_seconds\": 1800}\n```\nEOF")
        path, outcome = self._ask_with(body)
        self.assertEqual(outcome["result"], "ok")
        self.assertIn("ChatGPT", path.read_text())
        self.assertEqual(g.json.loads((g.CONFIG_DIR / "suggested-config.json").read_text()),
                         {"notify_cooldown_seconds": 1800})

    def test_cli_environment_always_names_the_user(self):
        """Seen on a real Mac: with USER unset the logged-in claude CLI says 'Not logged in'."""
        env = g.ai_env({"PATH": "/usr/bin", "CLAUDECODE": "1"})
        self.assertNotIn("CLAUDECODE", env)
        self.assertTrue(env["USER"])
        self.assertEqual(env["USER"], env["LOGNAME"])
        self.assertTrue(env["HOME"])
        self.assertEqual(g.ai_env({"USER": "someone"})["USER"], "someone", "an existing value is kept")

    def test_failed_ask_does_not_spend_the_daily_run_and_backs_off(self):
        ai = {"day": "d", "runs": 0, "retry_after": 0.0, "fail_notified": None}
        fail = {"result": "failed", "via": "claude", "reason": "not logged in"}
        msg = g.record_ask_outcome(ai, fail, 1000.0, "d")
        self.assertIn("not logged in", msg)
        self.assertIn("`claude`", msg)
        self.assertEqual(ai["runs"], 0, "a failure is not a diagnosis")
        self.assertEqual(ai["retry_after"], 1000.0 + 6 * 3600, "and is not retried every 30 s")
        self.assertEqual(g.record_ask_outcome(ai, fail, 30000.0, "d"), "", "one notification a day")
        self.assertIn("Could not get a diagnosis", g.record_ask_outcome(ai, fail, 90000.0, "d+1"))
        msg = g.record_ask_outcome(ai, {"result": "ok", "path_name": "diagnosis-x.md"}, 95000.0, "d+1")
        self.assertEqual((ai["runs"], msg), (1, "Diagnosis written to diagnosis-x.md"))

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
