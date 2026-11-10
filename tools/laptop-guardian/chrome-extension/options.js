const DEFAULTS = {
  level: "normal", sleepAfterMin: 60, parkAfterHours: 72, advanced: false,
  neverTouch: ["claude.ai", "chatgpt.com", "chat.openai.com", "meet.google.com", "zoom.us", "mail.google.com", "calendar.google.com"],
};

async function load() {
  const s = { ...DEFAULTS, ...(await chrome.storage.sync.get(DEFAULTS)) };
  document.querySelector(`input[name=level][value=${s.level}]`).checked = true;
  document.getElementById("advanced").checked = s.advanced;
  document.getElementById("adv").style.display = s.advanced ? "" : "none";
  document.getElementById("sleepAfterMin").value = s.sleepAfterMin;
  document.getElementById("parkAfterHours").value = s.parkAfterHours;
  document.getElementById("neverTouch").value = s.neverTouch.join("\n");
}

document.getElementById("advanced").addEventListener("change", e => {
  document.getElementById("adv").style.display = e.target.checked ? "" : "none";
});

document.getElementById("save").addEventListener("click", async () => {
  const s = {
    level: document.querySelector("input[name=level]:checked").value,
    advanced: document.getElementById("advanced").checked,
    sleepAfterMin: Math.max(5, parseInt(document.getElementById("sleepAfterMin").value, 10) || 60),
    parkAfterHours: Math.max(1, parseInt(document.getElementById("parkAfterHours").value, 10) || 72),
    neverTouch: document.getElementById("neverTouch").value.split("\n").map(x => x.trim()).filter(Boolean),
  };
  await chrome.storage.sync.set(s);
  document.getElementById("saved").textContent = "Saved";
  setTimeout(() => (document.getElementById("saved").textContent = ""), 1500);
});

load();
