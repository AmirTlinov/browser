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

async function setGatewayUrl(gatewayUrl) {
  return await chrome.runtime.sendMessage({ type: "ui.setGatewayUrl", gatewayUrl: String(gatewayUrl || "") });
}

async function resetGatewayUrl() {
  return await chrome.runtime.sendMessage({ type: "ui.resetGatewayUrl" });
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

  if (!state?.enabled) setBadge("badge--warn", "Disabled");
  else if (connected) setBadge("badge--ok", "Connected");
  else setBadge("badge--warn", "Waiting…");

  $("enabledToggle").checked = !!state?.enabled;
  $("followToggle").checked = !!state?.followActive;

  $("gatewayUrl").textContent = state?.gateway?.connectedUrl || state?.gateway?.url || "ws://127.0.0.1:8765";
  $("gatewayUrlInput").value = state?.gateway?.configuredUrl || "ws://127.0.0.1:8765";
  $("gatewayLastGood").textContent = state?.gateway?.lastGoodUrl || "—";
  $("extId").textContent = state?.extensionId || "—";
  $("focusedTab").textContent = state?.focusedTabId ?? "—";
  $("lastError").textContent = state?.lastError ? String(state.lastError) : "";
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

  $("saveGatewayBtn").addEventListener("click", async () => {
    await setGatewayUrl($("gatewayUrlInput").value);
    await refresh();
  });

  $("resetGatewayBtn").addEventListener("click", async () => {
    await resetGatewayUrl();
    await refresh();
  });

  $("gatewayUrlInput").addEventListener("keydown", async (e) => {
    if (e.key !== "Enter") return;
    await setGatewayUrl($("gatewayUrlInput").value);
    await refresh();
  });

  $("copyExtIdBtn").addEventListener("click", async () => {
    const ok = await copyToClipboard($("extId").textContent);
    if (!ok) $("lastError").textContent = "Failed to copy";
  });

  // Poll lightly while popup is open.
  const timer = setInterval(refresh, 900);
  window.addEventListener("unload", () => clearInterval(timer));
});
