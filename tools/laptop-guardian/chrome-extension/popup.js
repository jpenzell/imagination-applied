async function refresh() {
  const tabs = await chrome.tabs.query({});
  document.getElementById("total").textContent = tabs.length;
  document.getElementById("awake").textContent = tabs.filter(t => !t.discarded).length;
  const day = new Date().toISOString().slice(0, 10);
  const { daily = {}, lastSweep } = await chrome.storage.local.get(["daily", "lastSweep"]);
  const d = daily[day] || { slept: 0, parked: 0 };
  document.getElementById("slept").textContent = d.slept;
  document.getElementById("parked").textContent = d.parked;
  if (lastSweep) {
    const mins = Math.round((Date.now() - lastSweep.at) / 60000);
    document.getElementById("last").textContent = `Last check ${mins} min ago: ${lastSweep.looked} tabs looked at.`;
  }
  const { enabled = true } = await chrome.storage.sync.get("enabled");
  document.getElementById("enabled").checked = enabled;
}

document.getElementById("sweep").addEventListener("click", async () => {
  const b = document.getElementById("sweep");
  b.textContent = "Tidying…";
  const s = await chrome.runtime.sendMessage({ type: "sweep" });
  b.textContent = `Done: ${s.slept} to sleep, ${s.parked} parked`;
  refresh();
});
document.getElementById("parked-open").addEventListener("click", async () => {
  const [root] = await chrome.bookmarks.search({ title: "Guardian Parked" });
  chrome.tabs.create({ url: root ? `chrome://bookmarks/?id=${root.id}` : "chrome://bookmarks" });
});
document.getElementById("enabled").addEventListener("change", e => chrome.storage.sync.set({ enabled: e.target.checked }));
document.getElementById("options").addEventListener("click", e => { e.preventDefault(); chrome.runtime.openOptionsPage(); });
refresh();
