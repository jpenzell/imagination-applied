// Extension test with no dependencies beyond Node 22 and a Chrome/Chromium binary.
//
// Launches Chrome with the extension loaded and remote debugging on, attaches ONLY to the
// extension's service worker over the DevTools protocol (attaching to pages makes Chrome
// crash on tabs.discard), opens tabs against a local HTTP server, runs sweeps with the idle
// clock pushed forward, and checks parks, sleeps, and the leave-alone rules.
//
// Run:   node test_extension.mjs                               (Mac: finds Google Chrome)
//        xvfb-run -a node test_extension.mjs                   (Linux container)
//        CHROME_PATH=/path/to/chrome node test_extension.mjs
import { spawn } from "child_process";
import { fileURLToPath } from "url";
import http from "http";
import path from "path";
import fs from "fs";
import os from "os";

const here = path.dirname(fileURLToPath(import.meta.url));
const candidates = [process.env.CHROME_PATH,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome", "/usr/bin/google-chrome", "/usr/bin/chromium"].filter(Boolean);
const chromePath = candidates.find(p => fs.existsSync(p));
if (!chromePath) { console.error("no Chrome found; set CHROME_PATH"); process.exit(2); }

const server = http.createServer((req, res) => {
  res.writeHead(200, { "content-type": "text/html" });
  res.end(`<title>${req.url}</title><h1>${req.url}</h1>`);
});
await new Promise(r => server.listen(0, "127.0.0.1", r));
const port = server.address().port;
const A = `http://127.0.0.1:${port}`;        // ordinary sites
const NEVER = `http://localhost:${port}`;    // stand-in for claude.ai (never-touch via override)

const userDir = fs.mkdtempSync(path.join(os.tmpdir(), "guardian-ext-"));
const chrome = spawn(chromePath, [
  "--remote-debugging-port=0", `--user-data-dir=${userDir}`, `--load-extension=${here}`,
  `--disable-extensions-except=${here}`, "--no-first-run", "--no-default-browser-check",
  "--disable-background-networking", "--no-sandbox", "--window-size=900,600", "about:blank",
], { stdio: ["ignore", "ignore", "ignore"] });
const cleanup = () => { try { chrome.kill("SIGKILL"); } catch {} server.close(); fs.rmSync(userDir, { recursive: true, force: true }); };
process.on("exit", cleanup);

const sleep = ms => new Promise(r => setTimeout(r, ms));
let devPort = null;
for (let i = 0; i < 100 && !devPort; i++) {
  try { devPort = parseInt(fs.readFileSync(path.join(userDir, "DevToolsActivePort"), "utf8").split("\n")[0], 10) || null; } catch {}
  if (!devPort) await sleep(200);
}
if (!devPort) { console.error("Chrome did not open a debugging port"); process.exit(2); }

// Chrome ships component extensions with their own background.js workers, so probe each
// service-worker target for our runSweep function instead of trusting the file name.
let ws = null, nextId = 1;
const pending = new Map();
const cdp = (method, params) => new Promise(res => { const id = nextId++; pending.set(id, res); ws.send(JSON.stringify({ id, method, params })); });
async function connect(url) {
  const sock = new WebSocket(url);
  await new Promise((res, rej) => { sock.onopen = res; sock.onerror = rej; });
  sock.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
  return sock;
}
for (let i = 0; i < 100 && !ws; i++) {
  let list = [];
  try { list = await (await fetch(`http://127.0.0.1:${devPort}/json/list`)).json(); } catch {}
  for (const t of list.filter(t => t.type === "service_worker" && t.url.startsWith("chrome-extension://"))) {
    try {
      ws = await connect(t.webSocketDebuggerUrl);
      const r = await cdp("Runtime.evaluate", { expression: "typeof self.runSweep", returnByValue: true });
      if (r.result?.result?.value === "function") break;
      ws.close(); ws = null;
    } catch { ws = null; }
  }
  if (!ws) await sleep(200);
}
if (!ws) { console.error("Guardian service worker not found; is the extension loading?"); process.exit(2); }
async function evalInWorker(fn, args) {
  const expression = `(${fn.toString()})(${JSON.stringify(args)})`;
  const r = await cdp("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error("worker threw: " + JSON.stringify(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails));
  return r.result?.result?.value;
}

const future = Date.now() + 200 * 60 * 60 * 1000;   // 200h later: everything looks idle
const overrides = { neverTouch: ["localhost"] };

// Sweep 1: park everything idle except the active tab and the never-touch tab.
const s1 = await evalInWorker(async ({ A, NEVER, now, overrides }) => {
  const urls = [`${A}/active`, `${A}/one`, `${A}/two`, `${NEVER}/chat`, `${A}/three`];
  const ids = [];
  for (const u of urls) ids.push((await chrome.tabs.create({ url: u, active: false })).id);
  await chrome.tabs.update(ids[0], { active: true });
  await new Promise(r => setTimeout(r, 2500));
  const stats = await self.runSweep({ now, parkAfterHours: 100, sleepAfterMin: 1, ...overrides });
  const tabs = (await chrome.tabs.query({})).map(t => ({ url: t.url, active: t.active, discarded: t.discarded }));
  const [root] = await chrome.bookmarks.search({ title: "Guardian Parked" });
  const tree = root ? await chrome.bookmarks.getSubTree(root.id) : [];
  return { stats, tabs, tree };
}, { A, NEVER, now: future, overrides });

const fails = [];
const check = (cond, msg) => { if (!cond) fails.push(msg); };
const left = s1.tabs.filter(t => t.url.startsWith("http"));
check(s1.stats.parked === 3, `expected 3 parked, got ${s1.stats.parked}`);
check(left.some(t => t.url.endsWith("/active") && t.active && !t.discarded), "active tab must survive untouched");
check(left.some(t => t.url.startsWith(NEVER)), "never-touch tab must survive");
check(!left.some(t => /\/(one|two|three)$/.test(t.url)), "idle tabs should have been parked");
check(s1.stats.skipped["never-touch"] === 1, "never-touch skip should be counted once");
const day = s1.tree[0]?.children?.find(c => !c.url);
check(day && day.children.length === 3 && day.children.every(b => b.url.startsWith(A)),
      "parked bookmarks should sit in a dated folder with their URLs");

// Sweep 2: only sleep (discard), no park.
const s2 = await evalInWorker(async ({ A, now, overrides }) => {
  const t = await chrome.tabs.create({ url: `${A}/sleepy`, active: false });
  await new Promise(r => setTimeout(r, 2500));
  const stats = await self.runSweep({ now, parkAfterHours: 10000, sleepAfterMin: 1, ...overrides });
  const tab = await chrome.tabs.get(t.id);
  const { daily } = await chrome.storage.local.get("daily");
  return { stats, sleepyDiscarded: tab.discarded, sleepyUrl: tab.url, daily };
}, { A, now: future, overrides });
check(s2.stats.slept >= 1, `expected >=1 slept, got ${s2.stats.slept}`);
check(s2.sleepyDiscarded === true, "the idle tab should be discarded (asleep) but still present");
check(s2.sleepyUrl.endsWith("/sleepy"), "a discarded tab keeps its URL");
const today = new Date().toISOString().slice(0, 10);
check(s2.daily && s2.daily[today] && s2.daily[today].parked === 3, "daily counters should record the parks");

// Sweep 3: nothing is idle (now = real now): nothing happens.
const s3 = await evalInWorker(async (overrides) => self.runSweep({ now: Date.now(), ...overrides }), overrides);
check(s3.parked === 0 && s3.slept === 0, "a fresh sweep must not touch recently used tabs");

console.log(JSON.stringify({ chrome: chromePath, sweep1: s1.stats, sweep2: s2.stats, sweep3: s3 }, null, 1));
ws.close();
cleanup();
if (fails.length) { console.error("FAIL\n - " + fails.join("\n - ")); process.exit(1); }
console.log("OK: parks idle tabs into a dated bookmark folder, sleeps idle tabs, leaves active and never-touch tabs alone");
process.exit(0);
