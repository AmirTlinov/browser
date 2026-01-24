function $(id) {
  return document.getElementById(id);
}

function setBadge(kind, text) {
  const el = $("connBadge");
  el.classList.remove("badge--ok", "badge--warn", "badge--danger");
  el.classList.add(kind);
  el.textContent = text;
}

async function getState() {
  return await chrome.runtime.sendMessage({ type: "ui.getState" });
}

async function setEnabled(enabled) {
  return await chrome.runtime.sendMessage({ type: "ui.setEnabled", enabled: !!enabled });
}

async function setFollowActive(followActive) {
  return await chrome.runtime.sendMessage({ type: "ui.setFollowActive", followActive: !!followActive });
}

async function reconnect() {
  return await chrome.runtime.sendMessage({ type: "ui.reconnect" });
}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(String(text || ""));
    return true;
  } catch (_e) {
    return false;
  }
}

function render(state) {
  const connected = !!state?.gateway?.connected;
  const enabled = !!state?.enabled;

  if (!enabled) setBadge("badge--warn", "Disabled");
  else if (connected) setBadge("badge--ok", "Ready");
  else setBadge("badge--danger", "Not connected");

  $("enabledToggle").checked = enabled;
  $("followToggle").checked = !!state?.followActive;

  if (!enabled) $("statusHint").textContent = "Agent control is OFF.";
  else if (connected) $("statusHint").textContent = "";
  else $("statusHint").textContent = state?.lastError ? String(state.lastError) : "Native bridge is not connected.";

  $("transport").textContent = state?.gateway?.transport || "native";
  $("brokerId").textContent = state?.gateway?.brokerId || "—";
  $("peerCount").textContent = state?.gateway?.peerCount ?? "—";
  $("sessionId").textContent = state?.gateway?.sessionId ?? "—";
  $("extId").textContent = state?.extensionId || "—";
  $("focusedTab").textContent = state?.focusedTabId ?? "—";
  $("lastError").textContent = state?.lastError ? String(state.lastError) : "—";
}

async function refresh() {
  const state = await getState();
  render(state);
}

document.addEventListener("DOMContentLoaded", async () => {
  await refresh();

  $("enabledToggle").addEventListener("change", async (e) => {
    await setEnabled(!!e.target.checked);
    await refresh();
  });

  $("followToggle").addEventListener("change", async (e) => {
    await setFollowActive(!!e.target.checked);
    await refresh();
  });

  $("reconnectBtn").addEventListener("click", async () => {
    await reconnect();
    await refresh();
  });

  $("copyDiagnosticsBtn").addEventListener("click", async () => {
    const st = await getState();
    const ok = await copyToClipboard(JSON.stringify(st || {}, null, 2));
    if (!ok) $("lastError").textContent = "Failed to copy";
  });

  // Poll lightly while popup is open.
  const timer = setInterval(refresh, 900);
  window.addEventListener("unload", () => clearInterval(timer));
});
