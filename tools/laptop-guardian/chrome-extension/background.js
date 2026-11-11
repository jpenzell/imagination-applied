// Guardian for Chrome -- background service worker.
//
// Every few minutes: look at every tab, and
//   * SLEEP  tabs idle longer than `sleepAfterMin`  (chrome.tabs.discard: the tab stays in
//            the strip, memory is freed, it reloads when you click it)
//   * PARK   tabs idle longer than `parkAfterHours` (bookmark it under
//            "Guardian Parked / <date>", then close it)
// Never: the active tab in each window, pinned tabs, tabs playing sound, tabs on the
// never-touch list (claude.ai and chatgpt.com by default: a conversation may be mid-run).
//
// Idle = time since the tab was last in front: the later of Chrome's tab.lastAccessed (when
// it was last switched TO, Chrome 121+) and the last sweep that saw it active.

const DEFAULTS = {
  enabled: true,
  level: "normal",            // basic mode: gentle | normal | aggressive
  sleepAfterMin: 60,          // advanced overrides
  parkAfterHours: 72,
  neverTouch: ["claude.ai", "chatgpt.com", "chat.openai.com", "meet.google.com", "zoom.us", "mail.google.com", "calendar.google.com"],
  parkFolderName: "Guardian Parked",
  advanced: false,
  stepAside: true,            // when Guardian says the Mac is struggling and Chrome is not in front,
  stepAsideIdleMin: 5,        // sleep background tabs idle this long, at once
  guardianPort: 47613,        // Guardian's status page, on this Mac only (127.0.0.1)
};

const STEP_ASIDE_EVERY_MIN = 5;

const LEVELS = {
  gentle:     { sleepAfterMin: 180, parkAfterHours: 168 },
  normal:     { sleepAfterMin: 60,  parkAfterHours: 72 },
  aggressive: { sleepAfterMin: 20,  parkAfterHours: 24 },
};

async function getSettings() {
  const stored = await chrome.storage.sync.get(DEFAULTS);
  const s = { ...DEFAULTS, ...stored };
  if (!s.advanced) Object.assign(s, LEVELS[s.level] || LEVELS.normal);
  return s;
}

function hostOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; }
}

// A never-touch entry as a bare host: "www.Example.com", "https://example.com/page" and
// "example.com:8080" all mean example.com.
function siteOf(entry) {
  return String(entry).trim().toLowerCase().replace(/^[a-z][a-z0-9+.-]*:\/\//, "")
    .replace(/[\/?#].*$/, "").replace(/:\d+$/, "").replace(/^(\*\.|www\.)/, "");
}

// Local calendar day. (toISOString() is UTC: west of Greenwich "today" would end mid-evening.)
function dayKey(d = new Date()) {
  const p = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function untouchable(tab, settings) {
  if (!tab.url || !/^https?:/.test(tab.url)) return "internal";
  if (tab.active) return "active";
  if (tab.incognito) return "private";   // a private tab's address must never end up in bookmarks
  if (tab.pinned) return "pinned";
  if (tab.audible) return "audible";
  const h = hostOf(tab.url);
  if (settings.neverTouch.some(e => { const d = siteOf(e); return d && (h === d || h.endsWith("." + d)); })) return "never-touch";
  return null;
}

async function parkFolder(settings) {
  const today = dayKey();
  const [root] = await chrome.bookmarks.search({ title: settings.parkFolderName });
  const rootId = root ? root.id : (await chrome.bookmarks.create({ title: settings.parkFolderName })).id;
  const kids = await chrome.bookmarks.getChildren(rootId);
  const day = kids.find(k => k.title === today && !k.url);
  return day ? day.id : (await chrome.bookmarks.create({ parentId: rootId, title: today })).id;
}

// Exposed for tests and the popup: runSweep({now, sleepAfterMin, parkAfterHours}) -> stats
// One sweep at a time: a double click on "Tidy up now", or a click during the timed sweep,
// must not bookmark the same tab twice or lose a count.
let sweeping = Promise.resolve();
function runSweep(overrides = {}) {
  const run = sweeping.then(() => sweepOnce(overrides));
  sweeping = run.catch(() => {});
  return run;
}

// Ask Guardian (the helper that watches this Mac) how hard the Mac is struggling. It answers on
// 127.0.0.1 only. No answer means it is not running: carry on exactly as before.
async function askGuardian(settings) {
  try {
    const signal = (typeof AbortSignal !== "undefined" && AbortSignal.timeout) ? AbortSignal.timeout(2500) : undefined;
    const r = await fetch(`http://127.0.0.1:${settings.guardianPort}/status`, { signal, cache: "no-store" });
    if (!r.ok) return null;
    const s = await r.json();
    return s && typeof s.lag === "string" ? s : null;
  } catch (e) { return null; }
}

async function chromeInFront() {
  try { const w = await chrome.windows.getLastFocused(); return !!(w && w.focused); }
  catch (e) { return true; }      // cannot tell: assume you are here, and do nothing
}

// Once a minute. If the Mac is struggling and you are not in Chrome, Chrome steps aside: the
// background tabs go to sleep now instead of after an hour. Nothing is closed or parked.
async function pulse(overrides = {}) {
  const settings = { ...(await getSettings()), ...overrides };
  const now = overrides.now || Date.now();
  const status = settings.enabled && settings.stepAside ? await askGuardian(settings) : null;
  const link = { at: now, ok: !!status, lag: status ? status.lag : null };
  let stats = null;
  if (status && (status.lag === "slow" || status.lag === "severe") && !(await chromeInFront())) {
    const { lastAside = 0 } = await chrome.storage.session.get("lastAside");
    if (now - lastAside >= STEP_ASIDE_EVERY_MIN * 60000) {
      await chrome.storage.session.set({ lastAside: now });
      stats = await runSweep({ ...overrides, stepAside: true });
      link.steppedAside = stats.slept;
    }
  }
  await chrome.storage.local.set({ guardian: link });
  return { link, stats };
}

async function sweepOnce(overrides) {
  const settings = { ...(await getSettings()), ...overrides };
  const aside = !!overrides.stepAside;
  const stats = { looked: 0, slept: 0, parked: 0, skipped: {} };
  if (!settings.enabled) return stats;
  const now = overrides.now || Date.now();
  const tabs = await chrome.tabs.query({});
  // tab.lastAccessed is when a tab was last switched TO, not when you left it. Remember when
  // each tab was last seen active, so a tab you just left starts its idle clock from then.
  // (Session storage survives worker restarts and is dropped, like tab ids, when Chrome quits.)
  const { seenActive = {} } = await chrome.storage.session.get("seenActive");
  const seen = {};
  for (const tab of tabs) {
    if (tab.active) seen[tab.id] = now;
    else if (seenActive[tab.id]) seen[tab.id] = seenActive[tab.id];
  }
  await chrome.storage.session.set({ seenActive: seen });
  let folderId = null;
  for (const tab of tabs) {
    stats.looked++;
    let why = untouchable(tab, settings);
    // Stepping aside is done in a hurry, so it is more careful: a tab in a group was put there
    // by you or by an agent that may be working in it, and a tab still loading is in use.
    if (!why && aside && tab.groupId !== undefined && tab.groupId !== -1) why = "grouped";
    if (!why && aside && tab.status === "loading") why = "loading";
    if (why) { stats.skipped[why] = (stats.skipped[why] || 0) + 1; continue; }
    const idleMin = (now - Math.max(tab.lastAccessed || now, seen[tab.id] || 0)) / 60000;
    if (!aside && idleMin >= settings.parkAfterHours * 60) {
      try {
        folderId = folderId || await parkFolder(settings);
        await chrome.bookmarks.create({ parentId: folderId, title: tab.title || tab.url, url: tab.url });
        await chrome.tabs.remove(tab.id);
        stats.parked++;
      } catch (e) { stats.skipped.error = (stats.skipped.error || 0) + 1; }
    } else if (idleMin >= (aside ? settings.stepAsideIdleMin : settings.sleepAfterMin) && !tab.discarded) {
      try { await chrome.tabs.discard(tab.id); stats.slept++; }
      catch (e) { stats.skipped.error = (stats.skipped.error || 0) + 1; }
    }
  }
  const day = dayKey();
  const { daily = {} } = await chrome.storage.local.get("daily");
  const d = daily[day] || { slept: 0, parked: 0 };
  d.slept += stats.slept; d.parked += stats.parked;
  if (aside) d.aside = (d.aside || 0) + stats.slept;
  daily[day] = d;
  for (const k of Object.keys(daily)) if (k < dayKey(new Date(Date.now() - 14 * 86400000))) delete daily[k];
  await chrome.storage.local.set({ daily, lastSweep: { at: Date.now(), ...stats, aside } });
  await updateBadge();
  return stats;
}

async function updateBadge() {
  const tabs = await chrome.tabs.query({});
  const awake = tabs.filter(t => !t.discarded).length;
  await chrome.action.setBadgeText({ text: String(tabs.length) });
  await chrome.action.setBadgeBackgroundColor({ color: awake > 60 ? "#c0392b" : awake > 30 ? "#e67e22" : "#2c7a4b" });
}

function ensureAlarms() {
  chrome.alarms.create("sweep", { periodInMinutes: 5 });
  chrome.alarms.create("pulse", { periodInMinutes: 1 });
}
chrome.runtime.onInstalled.addListener(() => { ensureAlarms(); updateBadge(); });
chrome.runtime.onStartup.addListener(ensureAlarms);
chrome.alarms.onAlarm.addListener(a => {
  if (a.name === "sweep") runSweep();
  else if (a.name === "pulse") pulse();
});
chrome.tabs.onCreated.addListener(updateBadge);
chrome.tabs.onRemoved.addListener(updateBadge);
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg && msg.type === "sweep") { runSweep(msg.overrides || {}).then(reply); return true; }
  if (msg && msg.type === "badge") { updateBadge().then(() => reply(true)); return true; }
  if (msg && msg.type === "pulse") { pulse(msg.overrides || {}).then(reply); return true; }
});

self.runSweep = runSweep;
self.pulse = pulse;
self.getSettings = getSettings;
