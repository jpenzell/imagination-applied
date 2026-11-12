// Logic tests for the Guardian Chrome extension that need neither Node nor a browser.
//
// macOS ships a JavaScript engine. From tools/laptop-guardian run:
//
//   /System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc chrome-extension/test_logic_jsc.js
//
// It prints one PASS/FAIL line per case and throws (non-zero exit) if any case fails.
// An optional argument tests another copy of the extension (used for before/after and
// mutation runs):   jsc chrome-extension/test_logic_jsc.js -- /path/to/other/copy
//
// How it works: a fake `chrome` API (tabs, bookmarks, storage, alarms, runtime, action) and a
// fake clock are handed to background.js / popup.js / options.js, which are evaluated
// unmodified. Every fake API call yields like the real asynchronous ones do, and each "service
// worker start" is a fresh evaluation of background.js, so nothing can hide in memory.
// What this cannot show: that real Chrome behaves like the fake (see README / test_extension.mjs).

const RealDate = Date;
const MIN = 60000, HOUR = 60 * MIN, DAY = 24 * HOUR;
const BASE = new RealDate(2026, 10, 10, 12, 0, 0).getTime();   // local noon, 10 Nov 2026
const clock = { t: BASE };
class FakeDate extends RealDate {
  constructor(...a) { if (a.length === 0) super(clock.t); else super(...a); }
  static now() { return clock.t; }
}
globalThis.Date = FakeDate;
const at = t => { clock.t = t; };
const pad = n => String(n).padStart(2, "0");
const localDay = ms => { const d = new RealDate(ms); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };

// jsc has no URL; background.js only needs .hostname (and a throw on garbage).
if (typeof globalThis.URL === "undefined") {
  globalThis.URL = class URL {
    constructor(u) {
      const m = /^([a-zA-Z][a-zA-Z0-9+.-]*):(?:\/\/(?:[^\/?#@]*@)?(\[[^\]]*\]|[^\/?#:]*)(?::\d*)?)?([^?#]*)(\?[^#]*)?(#.*)?$/.exec(String(u));
      if (!m) throw new TypeError("Invalid URL: " + u);
      this.href = String(u); this.protocol = m[1].toLowerCase() + ":";
      this.hostname = (m[2] || "").toLowerCase(); this.pathname = m[3] || "";
    }
  };
}

// ---- where is the extension? ---------------------------------------------------------------
const DIR = (() => {
  const fromStack = (/@(.*)\/[^\/]*:\d+:\d+/.exec(new Error().stack.split("\n")[0]) || [])[1];
  const arg = typeof arguments !== "undefined" && arguments[0];
  for (const d of [arg, fromStack, ".", "chrome-extension"].filter(Boolean)) {
    try { readFile(d + "/background.js"); return d; } catch (e) {}
  }
  throw new Error("cannot find background.js; run from tools/laptop-guardian");
})();

// ---- fake chrome -------------------------------------------------------------------------
const clone = v => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));
const tick = async (n = 2) => { for (let i = 0; i < n; i++) await null; };

function makeChrome({ tabs = [], sync = {}, local = {}, session = {}, bookmarks = [] } = {}) {
  const ops = [];   // every state-changing API call, in the order it took effect
  const state = {
    tabs: tabs.map(t => ({ ...t })),
    bookmarks: [{ id: "1", parentId: "0", title: "Bookmarks bar" }, { id: "2", parentId: "0", title: "Other bookmarks" }, ...bookmarks],
    nextBookmarkId: 100, nextTabId: 9000, alarms: {}, badge: {}, failCreate: null, opened: [],
    focused: true,          // is a Chrome window the one in front?
    guardian: null,         // what Guardian's status page answers; null = nothing is listening
    asked: [],              // every address the worker fetched
  };
  // The only thing the extension ever fetches is Guardian's status page on this machine.
  state.fetch = async (url) => {
    await tick();
    state.asked.push(String(url));
    if (state.guardian === null) throw new TypeError("Failed to fetch");
    if (state.guardian === "error") return { ok: false, async json() { return {}; } };
    return { ok: true, async json() { return clone(state.guardian); } };
  };
  const events = [];
  const ev = () => { const e = { listeners: [], addListener(f) { e.listeners.push(f); }, fire: (...a) => e.listeners.map(f => f(...a)) }; events.push(e); return e; };
  const area = (name, data) => ({
    data,
    async get(keys) {
      await tick();
      if (keys === undefined || keys === null) return clone(data);
      const out = {};
      if (typeof keys === "string") keys = [keys];
      if (Array.isArray(keys)) { for (const k of keys) if (k in data) out[k] = clone(data[k]); return out; }
      for (const k of Object.keys(keys)) out[k] = k in data ? clone(data[k]) : clone(keys[k]);
      return out;
    },
    async set(obj) { await tick(); for (const k of Object.keys(obj)) data[k] = clone(obj[k]); ops.push({ op: `storage.${name}.set`, keys: Object.keys(obj) }); },
    async remove(keys) { await tick(); for (const k of [].concat(keys)) delete data[k]; },
  });
  const onCreated = ev(), onRemoved = ev(), onAlarm = ev(), onInstalled = ev(), onStartup = ev(), onMessage = ev();
  const chrome = {
    ops, state,
    restartWorker() { for (const e of events) e.listeners.length = 0; },   // a new worker registers its listeners again
    tabs: {
      onCreated, onRemoved,
      async query() { await tick(); return state.tabs.map(clone); },
      async get(id) { await tick(); const t = state.tabs.find(x => x.id === id); if (!t) throw new Error("No tab with id: " + id); return clone(t); },
      async discard(id) {
        await tick();
        const t = state.tabs.find(x => x.id === id);
        if (!t) throw new Error("No tab with id: " + id);
        if (t.active || t.discarded) throw new Error("Cannot discard tab with id: " + id);
        t.discarded = true; ops.push({ op: "tabs.discard", id, url: t.url });
        return clone(t);
      },
      async remove(id) {
        await tick();
        const i = state.tabs.findIndex(x => x.id === id);
        if (i < 0) throw new Error("No tab with id: " + id);
        ops.push({ op: "tabs.remove", id, url: state.tabs[i].url });
        state.tabs.splice(i, 1); onRemoved.fire(id, {});
      },
      async create(props) { await tick(); const t = { id: state.nextTabId++, windowId: 1, active: true, ...props }; state.opened.push(t); return clone(t); },
    },
    bookmarks: {
      async search(q) {
        await tick();
        return state.bookmarks.filter(n => typeof q === "string" ? n.title.includes(q)
          : (q.title === undefined || n.title === q.title) && (q.url === undefined || n.url === q.url)).map(clone);
      },
      async getChildren(id) { await tick(); return state.bookmarks.filter(n => n.parentId === id).map(clone); },
      async create(b) {
        await tick(6);   // slower than tabs.remove: a close that does not wait for the bookmark shows up first in `ops`
        if (state.failCreate && state.failCreate(b)) throw new Error("bookmark could not be saved");
        const parentId = b.parentId || "2";
        const parent = state.bookmarks.find(n => n.id === parentId);
        if (!parent) throw new Error("Can't find parent bookmark for id.");
        if (parent.url) throw new Error("Parameter 'parentId' does not specify a folder.");
        const n = { id: String(state.nextBookmarkId++), parentId, title: b.title || "" };
        if (b.url) n.url = b.url;
        state.bookmarks.push(n); ops.push({ op: "bookmarks.create", bookmarkId: n.id, parentId, title: n.title, url: n.url });
        return clone(n);
      },
    },
    storage: { sync: area("sync", clone(sync)), local: area("local", clone(local)), session: area("session", clone(session)) },
    alarms: {
      onAlarm,
      create(name, info) { state.alarms[name] = clone(info); return Promise.resolve(); },
      async get(name) { await tick(); return state.alarms[name] ? { name, ...state.alarms[name] } : undefined; },
    },
    runtime: {
      onInstalled, onStartup, onMessage,
      sendMessage(msg) {
        return new Promise(res => { let later = false; for (const f of onMessage.listeners) if (f(msg, {}, res) === true) later = true; if (!later) res(undefined); });
      },
      openOptionsPage() { state.opened.push({ options: true }); },
      getManifest() { return { version: "9.8.7" }; },
      reload() { state.reloads = (state.reloads || 0) + 1; },
    },
    windows: { async getLastFocused() { await tick(); return { id: 1, focused: state.focused }; } },
    action: {
      async setBadgeText({ text }) { await tick(); state.badge.text = text; },
      async setBadgeBackgroundColor({ color }) { await tick(); state.badge.color = color; },
    },
  };
  return chrome;
}

// Evaluate one of the extension's scripts, unmodified, against a fake chrome. `self` collects
// what background.js exports. Each call is a fresh scope = a fresh service worker / page.
function boot(chrome, file = "background.js", extra = {}) {
  extra = { fetch: (...a) => chrome.state.fetch(...a), ...extra };
  const self = {}, names = Object.keys(extra);
  new Function("chrome", "self", ...names, readFile(DIR + "/" + file))(chrome, self, ...names.map(n => extra[n]));
  return self;
}

function makeDocument() {
  const els = {}, radios = {};
  let picked = null;
  const radio = v => radios[v] || (radios[v] = { value: v, get checked() { return picked === v; }, set checked(on) { if (on) picked = v; else if (picked === v) picked = null; } });
  return {
    els, radio,
    getElementById: id => els[id] || (els[id] = { id, textContent: "", value: "", checked: false, style: {}, handlers: {}, addEventListener(t, f) { this.handlers[t] = f; } }),
    querySelector(sel) {
      const m = /\[value=([\w-]+)\]/.exec(sel);
      if (m) return radio(m[1]);
      if (/:checked/.test(sel)) return picked ? radio(picked) : null;
      return null;
    },
  };
}

// ---- tiny test kit ---------------------------------------------------------------------------
const cases = [];
const test = (name, fn) => cases.push({ name, fn });
const assert = (cond, msg) => { if (!cond) throw new Error(msg); };
const eq = (got, want, msg) => assert(JSON.stringify(got) === JSON.stringify(want), `${msg || "value"}: expected ${JSON.stringify(want)}, got ${JSON.stringify(got)}`);

let nextId = 100;
// A tab last switched to `idle` ms ago (null = Chrome reports no lastAccessed at all).
function tab(url, idle, extra = {}) {
  return { id: nextId++, windowId: 1, url, title: "Title of " + url, active: false, pinned: false, audible: false,
           discarded: false, incognito: false, groupId: -1, ...(idle === null ? {} : { lastAccessed: clock.t - idle }), ...extra };
}
const front = () => tab("https://in-front.example/", 0, { active: true });   // every window has an active tab
const fate = (c, t) => { const cur = c.state.tabs.find(x => x.id === t.id); return !cur ? "closed" : cur.discarded ? "asleep" : "untouched"; };
const bookmarksFor = (c, url) => c.state.bookmarks.filter(n => n.url === url);
const folders = (c, title) => c.state.bookmarks.filter(n => !n.url && n.title === title);
const touched = (c, t) => c.ops.filter(o => o.id === t.id || (o.op === "bookmarks.create" && o.url !== undefined && o.url === t.url));
const today = () => localDay(clock.t);

// ============================== settings and levels ============================================
test("settings: defaults are level normal, 60 min sleep, 72 h park, enabled, AI sites on never-touch list", async () => {
  const bg = boot(makeChrome());
  const s = await bg.getSettings();
  eq([s.level, s.sleepAfterMin, s.parkAfterHours, s.enabled], ["normal", 60, 72, true], "defaults");
  for (const d of ["claude.ai", "chatgpt.com"]) assert(s.neverTouch.includes(d), d + " missing from default never-touch list");
});

for (const [level, sleepMin, parkH] of [["gentle", 180, 168], ["normal", 60, 72], ["aggressive", 20, 24]]) {
  test(`level ${level}: sleeps at ${sleepMin} min, parks at ${parkH} h, not a minute earlier`, async () => {
    at(BASE);
    const t = { early: tab("https://a.example/early", (sleepMin - 1) * MIN), sleepy: tab("https://a.example/sleepy", (sleepMin + 1) * MIN),
                almost: tab("https://a.example/almost", parkH * HOUR - MIN), old: tab("https://a.example/old", parkH * HOUR + MIN) };
    const c = makeChrome({ tabs: [front(), ...Object.values(t)], sync: { level } });
    const stats = await boot(c).runSweep();
    eq([fate(c, t.early), fate(c, t.sleepy), fate(c, t.almost), fate(c, t.old)], ["untouched", "asleep", "asleep", "closed"], "fates");
    eq([stats.slept, stats.parked], [2, 1], "stats");
  });
}

test("level: an unknown level falls back to normal", async () => {
  const s = await boot(makeChrome({ sync: { level: "ludicrous" } })).getSettings();
  eq([s.sleepAfterMin, s.parkAfterHours], [60, 72], "thresholds");
});

test("advanced: custom minutes/hours apply only when advanced is on", async () => {
  at(BASE);
  const mk = () => [front(), tab("https://a.example/10min", 10 * MIN), tab("https://a.example/3h", 3 * HOUR)];
  const custom = { level: "normal", sleepAfterMin: 5, parkAfterHours: 2 };
  const on = makeChrome({ tabs: mk(), sync: { ...custom, advanced: true } });
  await boot(on).runSweep();
  eq(on.state.tabs.length, 2, "advanced on: 3 h tab parked"); assert(on.state.tabs[1].discarded, "advanced on: 10 min tab asleep");
  const off = makeChrome({ tabs: mk(), sync: { ...custom, advanced: false } });
  await boot(off).runSweep();
  eq(off.state.tabs.map(x => !!x.discarded), [false, false, true], "advanced off: level normal rules (only the 3 h tab sleeps)");
});

test("enabled off: nothing is slept or parked", async () => {
  at(BASE);
  const tabs = [front(), tab("https://a.example/2h", 2 * HOUR), tab("https://a.example/30d", 30 * DAY)];
  const c = makeChrome({ tabs, sync: { enabled: false } });
  const stats = await boot(c).runSweep();
  eq([stats.slept, stats.parked, c.ops.filter(o => !o.op.startsWith("storage")).length, c.state.tabs.length], [0, 0, 0, 3], "no action");
});

// ============================== sleeping ====================================================
test("sleep: idle 61 min is discarded, 59 min is not, exactly 60 min is", async () => {
  at(BASE);
  const a = tab("https://a.example/61", 61 * MIN), b = tab("https://a.example/59", 59 * MIN), d = tab("https://a.example/60", 60 * MIN);
  const c = makeChrome({ tabs: [front(), a, b, d] });
  const stats = await boot(c).runSweep();
  eq([fate(c, a), fate(c, b), fate(c, d)], ["asleep", "untouched", "asleep"], "fates");
  eq(stats.slept, 2, "slept"); eq(c.state.tabs.length, 4, "sleeping never closes a tab");
});

test("sleep: a tab already asleep is not discarded or counted again", async () => {
  at(BASE);
  const z = tab("https://a.example/z", 5 * HOUR, { discarded: true });
  const c = makeChrome({ tabs: [front(), z] });
  const stats = await boot(c).runSweep();
  eq([stats.slept, touched(c, z).length], [0, 0], "no second discard");
});

test("idle: a tab with no lastAccessed, or one in the future, is left alone", async () => {
  at(BASE);
  const a = tab("https://a.example/unknown", null), b = tab("https://a.example/future", -2 * HOUR);
  const c = makeChrome({ tabs: [front(), a, b] });
  await boot(c).runSweep();
  eq([fate(c, a), fate(c, b)], ["untouched", "untouched"], "fates");
});

test("idle: a tab you were on until a moment ago is not idle, however long ago you switched TO it", async () => {
  // Chrome's lastAccessed is when a tab last BECAME active. X has been the selected tab of its
  // window for 4 days; the user then switches to W. X must get the full hour / three days.
  at(BASE);
  const x = tab("https://a.example/long-open", 4 * DAY, { active: true });
  const w = tab("https://a.example/w", 3 * MIN), old = tab("https://a.example/old", 2 * HOUR);
  const c = makeChrome({ tabs: [x, w, old] });
  const bg = boot(c);
  await bg.runSweep();
  eq([fate(c, x), fate(c, old)], ["untouched", "asleep"], "sweep while X is active");
  const live = id => c.state.tabs.find(t => t.id === id);
  live(x.id).active = false; live(w.id).active = true; live(w.id).lastAccessed = clock.t + MIN;   // user switches X -> W
  at(BASE + 5 * MIN); await bg.runSweep();
  eq(fate(c, x), "untouched", "5 min after leaving X");
  at(BASE + 55 * MIN); await bg.runSweep();
  eq(fate(c, x), "untouched", "55 min after leaving X");
  at(BASE + 65 * MIN); await bg.runSweep();
  eq(fate(c, x), "asleep", "65 min after leaving X");
  at(BASE + 71 * HOUR); await bg.runSweep();
  eq(fate(c, x), "asleep", "71 h after leaving X");
  at(BASE + 73 * HOUR); await bg.runSweep();
  eq([fate(c, x), bookmarksFor(c, x.url).length], ["closed", 1], "73 h after leaving X");
});

test("idle: the 'was just active' memory survives a service-worker restart", async () => {
  at(BASE);
  const x = tab("https://a.example/long-open", 4 * DAY, { active: true }), w = tab("https://a.example/w", 3 * MIN);
  const c = makeChrome({ tabs: [x, w] });
  await boot(c).runSweep();
  c.restartWorker(); const bg2 = boot(c);          // Chrome stops an idle worker after ~30 s
  c.state.tabs[0].active = false; c.state.tabs[1].active = true; c.state.tabs[1].lastAccessed = clock.t + MIN;
  at(BASE + 5 * MIN); await bg2.runSweep();
  eq(fate(c, x), "untouched", "X after restart");
});

// ============================== parking =====================================================
test("park: idle 73 h is bookmarked under 'Guardian Parked / <today>' and closed; 71 h only sleeps", async () => {
  at(BASE);
  const old = tab("https://a.example/old?q=1#frag", 73 * HOUR), mid = tab("https://a.example/mid", 71 * HOUR);
  const c = makeChrome({ tabs: [front(), old, mid] });
  const stats = await boot(c).runSweep();
  eq([fate(c, old), fate(c, mid), stats.parked, stats.slept], ["closed", "asleep", 1, 1], "fates and stats");
  const [root] = folders(c, "Guardian Parked"), [day] = folders(c, today()), [bm] = bookmarksFor(c, old.url);
  assert(root && day && bm, "root folder, dated folder and bookmark must all exist");
  eq([day.parentId, bm.parentId, bm.title, bm.url], [root.id, day.id, old.title, old.url], "bookmark placement and content");
});

test("park: the bookmark is saved BEFORE the tab is closed (for every parked tab)", async () => {
  at(BASE);
  const olds = [1, 2, 3, 4].map(i => tab(`https://a.example/old${i}`, (73 + i) * HOUR));
  const c = makeChrome({ tabs: [front(), ...olds] });
  await boot(c).runSweep();
  for (const t of olds) {
    const saved = c.ops.findIndex(o => o.op === "bookmarks.create" && o.url === t.url), closed = c.ops.findIndex(o => o.op === "tabs.remove" && o.id === t.id);
    assert(saved >= 0 && closed >= 0, "tab should have been bookmarked and closed: " + t.url);
    assert(saved < closed, `tab ${t.url} was closed before its bookmark existed`);
  }
});

test("park: if the bookmark cannot be saved the tab stays open", async () => {
  at(BASE);
  const a = tab("https://a.example/unsavable", 80 * HOUR), b = tab("https://a.example/fine", 80 * HOUR);
  const c = makeChrome({ tabs: [front(), a, b] });
  c.state.failCreate = bm => bm.url === a.url;
  const stats = await boot(c).runSweep();
  eq([fate(c, a) !== "closed", fate(c, b), stats.parked, stats.skipped.error], [true, "closed", 1, 1], "only the saved tab closes");
});

test("park: if no bookmark folder can be made, no tab is closed", async () => {
  at(BASE);
  const olds = [tab("https://a.example/1", 80 * HOUR), tab("https://a.example/2", 90 * HOUR)];
  const c = makeChrome({ tabs: [front(), ...olds] });
  c.state.failCreate = () => true;
  const stats = await boot(c).runSweep();
  eq([c.state.tabs.length, stats.parked, c.ops.filter(o => o.op === "tabs.remove").length], [3, 0, 0], "nothing closed");
});

test("park: an existing 'Guardian Parked' folder and today's folder are reused, not duplicated", async () => {
  at(BASE);
  const pre = [{ id: "50", parentId: "2", title: "Guardian Parked" }, { id: "51", parentId: "50", title: today() }, { id: "52", parentId: "51", title: "earlier", url: "https://earlier.example/" }];
  const c = makeChrome({ tabs: [front(), tab("https://a.example/1", 80 * HOUR)], bookmarks: pre });
  const bg = boot(c);
  await bg.runSweep();
  c.state.tabs.push(tab("https://a.example/2", 80 * HOUR));
  await bg.runSweep();
  eq([folders(c, "Guardian Parked").length, folders(c, today()).length, c.state.bookmarks.filter(n => n.parentId === "51").length], [1, 1, 3], "folders reused");
});

test("park: a tab with no title is bookmarked under its URL", async () => {
  at(BASE);
  const t = tab("https://a.example/untitled", 80 * HOUR, { title: "" });
  const c = makeChrome({ tabs: [front(), t] });
  await boot(c).runSweep();
  eq(bookmarksFor(c, t.url).map(b => b.title), [t.url], "title");
});

// ============================== never touch =================================================
// Each rule is checked at an age that would sleep (2 h) and one that would park (30 d), beside a
// control tab of the same age that must be acted on, so a sweep that did nothing cannot pass.
function never(name, make, sync) {
  for (const [label, idle, want] of [["2 h idle", 2 * HOUR, "asleep"], ["30 d idle", 30 * DAY, "closed"]]) {
    test(`never touch: ${name} (${label})`, async () => {
      at(BASE);
      const guarded = [].concat(make(idle)), control = tab("https://control.example/page", idle);
      const c = makeChrome({ tabs: [front(), ...guarded, control], sync });
      await boot(c).runSweep();
      eq(fate(c, control), want, "control tab of the same age");
      for (const g of guarded) {
        eq(fate(c, g), "untouched", "protected tab " + g.url);
        eq(touched(c, g).length, 0, "API calls naming protected tab " + g.url);
      }
    });
  }
}
never("the active tab", idle => tab("https://a.example/active", idle, { active: true }));
never("the active tab of a second and third window", idle => [tab("https://a.example/w2", idle, { active: true, windowId: 2 }), tab("https://a.example/w3", idle, { active: true, windowId: 3 })]);
never("a pinned tab", idle => tab("https://a.example/pinned", idle, { pinned: true }));
never("a private (incognito) tab", idle => tab("https://a.example/private", idle, { incognito: true }));
never("a tab playing sound", idle => tab("https://a.example/music", idle, { audible: true }));
never("a tab playing sound that is muted", idle => tab("https://a.example/muted", idle, { audible: true, mutedInfo: { muted: true } }));
never("claude.ai, with and without www, subdomains, any path", idle =>
  ["https://claude.ai/chat/abc", "https://www.claude.ai/", "https://api.claude.ai/x", "http://claude.ai/new?q=1", "https://CLAUDE.AI/chat"].map(u => tab(u, idle)));
never("chatgpt.com and chat.openai.com", idle =>
  ["https://chatgpt.com/c/123", "https://www.chatgpt.com/", "https://sub.chatgpt.com/x", "https://chat.openai.com/c/1"].map(u => tab(u, idle)));
never("Meet, Zoom, Gmail, Calendar", idle =>
  ["https://meet.google.com/abc-defg-hij", "https://us02web.zoom.us/j/1", "https://zoom.us/j/1", "https://mail.google.com/mail/u/0/", "https://calendar.google.com/calendar/u/0/r"].map(u => tab(u, idle)));
never("Chrome's own pages, files, extensions, blank and URL-less tabs", idle =>
  ["chrome://settings/", "chrome://newtab/", "file:///Users/x/doc.pdf", "chrome-extension://abcdef/page.html", "about:blank", "", undefined].map(u => tab(u, idle)));
never("claude.ai tabs in another window, even with the list edited to add a site", idle =>
  [tab("https://claude.ai/chat/1", idle, { windowId: 2 }), tab("https://mine.example/x", idle, { windowId: 2 })],
  { advanced: true, neverTouch: ["claude.ai", "chatgpt.com", "mine.example"] });
never("a site the user typed with www, a scheme, capitals, a path or a port", idle =>
  ["https://www.typed.example/a", "https://typed.example/b", "https://docs.pasted.example/doc/1", "https://shout.example/", "http://ported.example:8080/app"].map(u => tab(u, idle)),
  { advanced: true, neverTouch: ["www.typed.example", "https://Docs.Pasted.example/some/page", "SHOUT.example", "ported.example:8080"] });

test("never-touch matching is exact: look-alike hosts and mentions in the path are NOT protected", async () => {
  at(BASE);
  const fakes = ["https://notclaude.ai/", "https://claude.ai.evil.example/", "https://evilchatgpt.com/", "https://a.example/?next=https://claude.ai/", "https://a.example/claude.ai"].map(u => tab(u, 2 * HOUR));
  const c = makeChrome({ tabs: [front(), ...fakes] });
  await boot(c).runSweep();
  eq(fakes.map(t => fate(c, t)), fakes.map(() => "asleep"), "fates");
});

test("mixed strip: only ordinary idle tabs are touched, across two windows", async () => {
  at(BASE);
  const keep = [tab("https://a.example/active1", 9 * DAY, { active: true }), tab("https://a.example/active2", 9 * DAY, { active: true, windowId: 2 }),
                tab("https://a.example/pin", 9 * DAY, { pinned: true }), tab("https://a.example/sound", 9 * DAY, { audible: true, windowId: 2 }),
                tab("https://claude.ai/chat/9", 9 * DAY), tab("https://chatgpt.com/c/9", 9 * DAY, { windowId: 2 }), tab("https://a.example/fresh", 10 * MIN)];
  const sleepy = [tab("https://a.example/s1", 2 * HOUR), tab("https://a.example/s2", 30 * HOUR, { windowId: 2 })];
  const old = [tab("https://a.example/p1", 4 * DAY), tab("https://a.example/p2", 9 * DAY, { windowId: 2 })];
  const c = makeChrome({ tabs: [...keep, ...sleepy, ...old] });
  const stats = await boot(c).runSweep();
  eq(keep.map(t => fate(c, t)), keep.map(() => "untouched"), "protected and fresh tabs");
  eq(sleepy.map(t => fate(c, t)), ["asleep", "asleep"], "sleepy tabs"); eq(old.map(t => fate(c, t)), ["closed", "closed"], "old tabs");
  eq([stats.looked, stats.slept, stats.parked, stats.skipped], [11, 2, 2, { active: 2, pinned: 1, audible: 1, "never-touch": 2 }], "stats");
});

// ============================== counts ======================================================
test("counts: today's totals add up across sweeps and across a service-worker restart", async () => {
  at(BASE);
  const c = makeChrome({ tabs: [front(), tab("https://a.example/1", 2 * HOUR), tab("https://a.example/2", 3 * HOUR), tab("https://a.example/3", 80 * HOUR)] });
  await boot(c).runSweep();
  eq(c.storage.local.data.daily, { [today()]: { slept: 2, parked: 1 } }, "after first sweep");
  c.restartWorker(); const bg2 = boot(c);
  at(BASE + 5 * MIN); await bg2.runSweep();
  eq(c.storage.local.data.daily, { [today()]: { slept: 2, parked: 1 } }, "an idle sweep changes nothing");
  c.state.tabs.push(tab("https://a.example/4", 2 * HOUR), tab("https://a.example/5", 90 * HOUR));
  at(BASE + 10 * MIN); const stats = await bg2.runSweep();
  eq(c.storage.local.data.daily, { [today()]: { slept: 3, parked: 2 } }, "after third sweep");
  const last = c.storage.local.data.lastSweep;
  eq([last.at, last.looked, last.slept, last.parked], [clock.t, stats.looked, 1, 1], "lastSweep record");
});

test("counts: a day is the local calendar day (two sweeps either side of midnight UTC are the same 'today')", async () => {
  const midnight = new RealDate(2026, 10, 10).getTime(), utcFlip = Math.ceil(midnight / DAY) * DAY;
  if (utcFlip - 30 * MIN < midnight || utcFlip + 30 * MIN >= midnight + DAY) return "vacuous: this Mac's clock is on UTC";
  at(utcFlip - 30 * MIN);
  const c = makeChrome({ tabs: [front(), tab("https://a.example/1", 2 * HOUR)] });
  const bg = boot(c);
  await bg.runSweep();
  at(utcFlip + 30 * MIN);
  c.state.tabs.push(tab("https://a.example/2", 2 * HOUR), tab("https://a.example/3", 80 * HOUR));
  await bg.runSweep();
  eq(c.storage.local.data.daily, { "2026-11-10": { slept: 2, parked: 1 } }, "daily counters");
  eq(folders(c, "2026-11-10").length + "/" + folders(c, "2026-11-11").length + "/" + folders(c, "2026-11-09").length, "1/0/0", "dated park folder (10th/11th/9th)");
});

test("counts: a new day starts from zero, yesterday is kept, entries older than 14 days are dropped", async () => {
  at(BASE);
  const c = makeChrome({ tabs: [front(), tab("https://a.example/1", 2 * HOUR)] });
  const bg = boot(c);
  await bg.runSweep();
  const day1 = today();
  at(BASE + DAY); c.state.tabs.push(tab("https://a.example/2", 80 * HOUR));
  await bg.runSweep();
  eq(c.storage.local.data.daily, { [day1]: { slept: 1, parked: 0 }, [today()]: { slept: 0, parked: 1 } }, "two days");
  at(BASE + 16 * DAY); await bg.runSweep();
  eq(Object.keys(c.storage.local.data.daily), [today()], "old days pruned");
});

test("counts: 'Tidy up now' clicked twice saves each tab once and loses no count", async () => {
  at(BASE);
  const olds = [1, 2, 3].map(i => tab(`https://a.example/old${i}`, 80 * HOUR)), sleepy = [1, 2].map(i => tab(`https://a.example/s${i}`, 2 * HOUR));
  const c = makeChrome({ tabs: [front(), ...olds, ...sleepy] });
  boot(c);
  const replies = await Promise.all([c.runtime.sendMessage({ type: "sweep" }), c.runtime.sendMessage({ type: "sweep" })]);
  eq(olds.map(t => bookmarksFor(c, t.url).length), [1, 1, 1], "bookmarks per parked tab");
  eq(c.storage.local.data.daily[today()], { slept: 2, parked: 3 }, "today's counters");
  eq(replies.map(r => r.skipped.error || 0), [0, 0], "errors reported by either sweep");
  eq(folders(c, "Guardian Parked").length, 1, "'Guardian Parked' folders");
});

// ============================== stepping aside when the Mac is struggling ====================
// Measured on the first real Mac: with another app in front, five background Chrome tabs were
// still working and holding 2.6 GB while the Mac swapped 170 MB a second.
const strip = () => {
  at(BASE);
  return { front: front(), idle: tab("https://a.example/idle", 10 * MIN), fresh: tab("https://a.example/fresh", 2 * MIN),
           ancient: tab("https://a.example/ancient", 80 * HOUR), pinned: tab("https://a.example/pin", 3 * HOUR, { pinned: true }),
           sound: tab("https://a.example/sound", 3 * HOUR, { audible: true }), ai: tab("https://claude.ai/chat/1", 3 * HOUR),
           grouped: tab("https://a.example/agent-is-working-here", 3 * HOUR, { groupId: 7 }),
           loading: tab("https://a.example/loading", 3 * HOUR, { status: "loading" }),
           secret: tab("https://a.example/private", 3 * HOUR, { incognito: true }) };
};

test("step aside: the Mac is struggling and you are elsewhere: idle background tabs sleep at once, nothing is closed", async () => {
  const t = strip();
  const c = makeChrome({ tabs: Object.values(t) });
  c.state.guardian = { v: 1, lag: "severe" }; c.state.focused = false;
  const out = await boot(c).pulse();
  eq(Object.fromEntries(Object.entries(t).map(([k, v]) => [k, fate(c, v)])),
     { front: "untouched", idle: "asleep", fresh: "untouched", ancient: "asleep", pinned: "untouched", sound: "untouched",
       ai: "untouched", grouped: "untouched", loading: "untouched", secret: "untouched" }, "fates");
  eq(c.ops.filter(o => o.op === "bookmarks.create").length, 0, "nothing is parked in a hurry, not even a tab idle for days");
  const WHY = "&why=active.1_audible.1_grouped.1_loading.1_never-touch.1_pinned.1_private.1_ready.2_recent.1_tabs.10";
  eq(c.state.asked, ["http://127.0.0.1:47613/status?v=9.8.7" + WHY, "http://127.0.0.1:47613/status?v=9.8.7&aside=2&looked=10" + WHY],
     "asked Guardian, told it what was done and why the rest was left alone (counts only), and talked to nobody else");
  eq(c.state.asked.filter(u => /example|claude|https:/.test(u.split("?")[1])).length, 0, "no address or site name leaves Chrome");
  eq([out.stats.slept, out.stats.parked, out.stats.skipped.grouped, out.stats.skipped.loading], [2, 0, 1, 1], "stats");
  eq(c.storage.local.data.daily[today()], { slept: 2, parked: 0, aside: 2 }, "counted for today");
  eq([c.storage.local.data.guardian.ok, c.storage.local.data.guardian.lag, c.storage.local.data.guardian.steppedAside], [true, "severe", 2], "link recorded");
});

for (const [why, setup] of [
  ["you are in Chrome", c => { c.state.guardian = { v: 1, lag: "severe" }; c.state.focused = true; }],
  ["Guardian says the Mac is coping", c => { c.state.guardian = { v: 1, lag: "none" }; c.state.focused = false; }],
  ["Guardian is not running", c => { c.state.guardian = null; c.state.focused = false; }],
  ["Guardian answers with an error", c => { c.state.guardian = "error"; c.state.focused = false; }],
  ["Guardian answers nonsense", c => { c.state.guardian = { hello: 1 }; c.state.focused = false; }],
]) {
  test(`step aside: not when ${why}`, async () => {
    const t = strip();
    const c = makeChrome({ tabs: Object.values(t) });
    setup(c);
    const out = await boot(c).pulse();
    eq([fate(c, t.idle), fate(c, t.ancient), out.stats], ["untouched", "untouched", null], "tabs");
    eq(c.storage.local.data.guardian.ok, c.state.guardian !== null && c.state.guardian !== "error" && !!c.state.guardian.lag, "link health recorded");
  });
}

test("a newer copy in Guardian's folder: the extension reloads itself, once per version, and never for an older or odd one", async () => {
  const t = strip();
  const c = makeChrome({ tabs: Object.values(t) });
  c.state.focused = false;
  for (const ext of ["9.8.7", "9.8.6", "9.8", "rm -rf", 10, undefined]) {
    c.state.guardian = { v: 1, lag: "none", ext };
    const out = await boot(c).pulse();
    eq([c.state.reloads || 0, out.reloading], [0, undefined], "no reload for " + JSON.stringify(ext));
  }
  c.state.guardian = { v: 1, lag: "severe", ext: "9.10.0" };     // 10 is more than 8: numbers, not text
  const out = await boot(c).pulse();
  eq([c.state.reloads, out.reloading, out.stats, fate(c, t.idle)], [1, "9.10.0", null, "untouched"], "reloads first; the new copy does the work");
  eq(c.storage.local.data.reloadTried, "9.10.0", "remembered");
  c.restartWorker();
  await boot(c).pulse();
  eq(c.state.reloads, 1, "still 9.8.7 after the reload (Chrome loaded another folder): no second try, no loop");
  eq(fate(c, t.idle), "asleep", "and it carries on with its work");
  c.state.guardian = { v: 1, lag: "none", ext: "9.10.1" };
  await boot(c).pulse();
  eq(c.state.reloads, 2, "a later version is a new reason");
});

test("step aside: switched off in Settings, or tidying switched off, Guardian is not even asked", async () => {
  for (const sync of [{ stepAside: false }, { enabled: false }]) {
    const t = strip();
    const c = makeChrome({ tabs: Object.values(t), sync });
    c.state.guardian = { v: 1, lag: "severe" }; c.state.focused = false;
    await boot(c).pulse();
    eq([fate(c, t.idle), c.state.asked], ["untouched", []], JSON.stringify(sync));
  }
});

test("step aside: at most once every five minutes, and the memory of that survives a worker restart", async () => {
  const t = strip();
  const c = makeChrome({ tabs: Object.values(t) });
  c.state.guardian = { v: 1, lag: "slow" }; c.state.focused = false;
  await boot(c).pulse();
  eq(fate(c, t.idle), "asleep", "first pulse");
  at(BASE + 4 * MIN);    // the 2-minute tab is now 6 minutes idle, but Chrome stepped aside 4 minutes ago
  c.restartWorker();
  const again = await boot(c).pulse();
  eq([fate(c, t.fresh), again.stats], ["untouched", null], "four minutes later");
  at(BASE + 6 * MIN);
  await boot(c).pulse();
  eq(fate(c, t.fresh), "asleep", "six minutes later");
});

test("step aside: the one-minute 'pulse' alarm does it; the popup and settings show it", async () => {
  const t = strip();
  const c = makeChrome({ tabs: Object.values(t) });
  c.state.guardian = { v: 1, lag: "severe" }; c.state.focused = false;
  boot(c); c.runtime.onInstalled.fire({ reason: "update" }); await tick(20);
  c.alarms.onAlarm.fire({ name: "pulse" }); await tick(200);
  eq(fate(c, t.idle), "asleep", "after the pulse alarm");
  const doc = makeDocument();
  boot(c, "popup.js", { document: doc }); await tick(40);
  eq(String(doc.els.aside.textContent), "2", "popup: slept to make room today");
  assert(/struggling/.test(doc.els.link.textContent), "popup link line: " + doc.els.link.textContent);
  c.state.guardian = { v: 1, lag: "none" };
  at(clock.t + MIN); await boot(c).pulse();
  const doc2 = makeDocument();
  boot(c, "popup.js", { document: doc2 }); await tick(40);
  assert(/coping/.test(doc2.els.link.textContent), "popup link line: " + doc2.els.link.textContent);
  at(clock.t + 10 * MIN);
  const doc3 = makeDocument();
  boot(c, "popup.js", { document: doc3 }); await tick(40);
  assert(/not answering/.test(doc3.els.link.textContent), "a stale answer is not shown as current: " + doc3.els.link.textContent);
  const od = makeDocument();
  boot(c, "options.js", { document: od, setTimeout: () => 0 }); await tick(20);
  eq(od.els.stepAside.checked, true, "settings page shows it on by default");
  od.radio("normal").checked = true; od.els.stepAside.checked = false;
  await od.els.save.handlers.click();
  eq((await boot(c).getSettings()).stepAside, false, "and can switch it off");
});

// ============================== worker lifecycle, popup, options, manifest ==================
test("alarm: install and browser start both register the 5-minute 'sweep' alarm", async () => {
  const c = makeChrome({ tabs: [front()] });
  boot(c);
  eq(c.state.alarms, {}, "before any event");
  c.runtime.onInstalled.fire({ reason: "install" }); await tick(20);
  eq(c.state.alarms, { sweep: { periodInMinutes: 5 }, pulse: { periodInMinutes: 1 } }, "after onInstalled");
  eq(c.state.badge.text, "1", "badge set on install");
  const c2 = makeChrome(); boot(c2);
  c2.runtime.onStartup.fire();
  eq(c2.state.alarms, { sweep: { periodInMinutes: 5 }, pulse: { periodInMinutes: 1 } }, "after onStartup");
});

test("alarm: a restarted worker (no install/startup event) still sweeps when the 'sweep' alarm fires; other alarms do nothing", async () => {
  at(BASE);
  const t = tab("https://a.example/1", 2 * HOUR);
  const c = makeChrome({ tabs: [front(), t] });
  boot(c); c.runtime.onInstalled.fire({ reason: "install" }); await tick(20);
  c.restartWorker(); boot(c);
  eq(c.alarms.onAlarm.listeners.length, 1, "alarm listener registered synchronously at worker start");
  c.alarms.onAlarm.fire({ name: "something-else" }); await tick(60);
  eq(fate(c, t), "untouched", "after an unrelated alarm");
  c.alarms.onAlarm.fire({ name: "sweep" }); await tick(60);
  eq([fate(c, t), c.storage.local.data.lastSweep.slept], ["asleep", 1], "after the sweep alarm");
});

test("badge: shows the number of open tabs after a sweep", async () => {
  at(BASE);
  const c = makeChrome({ tabs: [front(), tab("https://a.example/1", 2 * HOUR), tab("https://a.example/2", 80 * HOUR), tab("https://a.example/3", 5 * MIN)] });
  await boot(c).runSweep();
  eq(c.state.badge.text, "3", "badge text");
});

test("popup: shows tabs awake / total and today's slept and parked counts; 'Tidy up now' runs a sweep", async () => {
  at(BASE + 11 * HOUR);   // 11 pm local: a UTC date and a local date disagree in most time zones
  const c = makeChrome({ tabs: [front(), tab("https://a.example/1", 2 * HOUR), tab("https://a.example/2", 3 * HOUR), tab("https://a.example/3", 80 * HOUR), tab("https://a.example/4", 50 * MIN)] });
  const bg = boot(c);
  await bg.runSweep();
  const doc = makeDocument();
  boot(c, "popup.js", { document: doc }); await tick(40);
  const text = id => String(doc.els[id].textContent);
  eq([text("total"), text("awake"), text("slept"), text("parked"), doc.els.enabled.checked], ["4", "2", "2", "1", true], "popup numbers");
  assert(/4 tabs looked at/.test(text("last")) || /5 tabs looked at/.test(text("last")), "last-check line: " + text("last"));
  at(clock.t + 15 * MIN);   // tab 4 is now 65 min idle
  await doc.els.sweep.handlers.click(); await tick(40);
  eq([text("sweep"), text("slept"), text("awake")], ["Done: 1 to sleep, 0 parked", "3", "1"], "after Tidy up now");
});

test("options: saving 'aggressive' changes what the worker does; advanced values are stored and clamped", async () => {
  const c = makeChrome();
  const doc = makeDocument();
  boot(c, "options.js", { document: doc, setTimeout: () => 0 }); await tick(20);
  eq([doc.radio("normal").checked, doc.els.sleepAfterMin.value, doc.els.parkAfterHours.value], [true, 60, 72], "form shows defaults");
  assert(/claude\.ai/.test(doc.els.neverTouch.value) && /chatgpt\.com/.test(doc.els.neverTouch.value), "form lists the default never-touch sites");
  doc.radio("aggressive").checked = true;
  await doc.els.save.handlers.click();
  const s = await boot(c).getSettings();
  eq([s.level, s.sleepAfterMin, s.parkAfterHours], ["aggressive", 20, 24], "after saving aggressive");
  assert(s.neverTouch.includes("claude.ai") && s.neverTouch.includes("chatgpt.com"), "saving must keep the never-touch list");
  doc.els.advanced.checked = true; doc.els.sleepAfterMin.value = "1"; doc.els.parkAfterHours.value = "0";
  doc.els.neverTouch.value = "claude.ai\n  chatgpt.com \n\nexample.org\n";
  await doc.els.save.handlers.click();
  const s2 = await boot(c).getSettings();
  eq([s2.advanced, s2.sleepAfterMin, s2.parkAfterHours, s2.neverTouch], [true, 5, 72, ["claude.ai", "chatgpt.com", "example.org"]], "after saving advanced");
});

test("manifest: MV3, files exist, and every chrome.* API the code calls is covered by a permission", async () => {
  const m = JSON.parse(readFile(DIR + "/manifest.json"));
  eq(m.manifest_version, 3, "manifest_version");
  const files = [m.background.service_worker, m.action.default_popup, m.options_page, "popup.js", "options.js"];
  for (const f of files) assert(readFile(DIR + "/" + f).length > 0, "missing file " + f);
  const needs = { tabs: "tabs", bookmarks: "bookmarks", storage: "storage", alarms: "alarms" }, free = ["runtime", "action", "windows"];
  const port = /guardianPort:\s*(\d+)/.exec(readFile(DIR + "/background.js"))[1];
  eq(m.host_permissions, [`http://127.0.0.1:${port}/*`], "the only host the extension may talk to is Guardian on this machine");
  const used = new Set();
  for (const f of ["background.js", "popup.js", "options.js"]) for (const hit of readFile(DIR + "/" + f).matchAll(/chrome\.(\w+)\./g)) used.add(hit[1]);
  for (const ns of used) assert(free.includes(ns) || m.permissions.includes(needs[ns]), `chrome.${ns} is used but not permitted by the manifest`);
  assert(m.action, "chrome.action needs an 'action' key");
  for (const page of [m.action.default_popup, m.options_page]) {
    const html = readFile(DIR + "/" + page);
    assert(!/<script(?![^>]*\bsrc=)[^>]*>/.test(html) && !/\son\w+=/.test(html), page + " has inline script (blocked by MV3)");
  }
});

// ---- run -------------------------------------------------------------------------------------
let failed = 0;
print(`Guardian extension logic tests (extension at: ${DIR})`);
for (const { name, fn } of cases) {
  let outcome = "did not finish (a promise never settled)", note = "";
  fn().then(v => { outcome = null; note = typeof v === "string" ? `  [${v}]` : ""; }, e => { outcome = (e && e.message) || String(e); });
  drainMicrotasks();
  if (outcome) failed++;
  print(`${outcome ? "FAIL" : "PASS"}  ${name}${outcome ? "\n        " + outcome : note}`);
}
print(`\n${cases.length - failed} of ${cases.length} cases passed`);
if (failed) throw new Error(`${failed} case(s) FAILED`);
print("OK");
