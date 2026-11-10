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
