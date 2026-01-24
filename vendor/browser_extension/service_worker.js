// Browser MCP Extension (MV3): CDP proxy + portless native bridge.
//
// This runs in the user's normal Chrome and lets Browser MCP control tabs via:
// - chrome.debugger (DevTools Protocol on real tabs)
// - Chrome Native Messaging (no localhost TCP ports)

const STORAGE_KEY = "mcp_ext_state_v1";
const PROFILE_ID_KEY = "mcp_profile_id_v1";
const NATIVE_HOST_NAME = "com.openai.browser_mcp";

// Forward only high-signal events (keep the bridge cognitively cheap).
const FORWARD_EVENT_ALLOWLIST = new Set([
  // Page lifecycle / navigation
  "Page.loadEventFired",
  "Page.domContentEventFired",
  "Page.frameNavigated",
  "Page.navigatedWithinDocument",
  // File chooser (critical for import/upload flows in canvas apps like Miro/Figma)
  "Page.fileChooserOpened",
  // Dialogs (critical for robustness)
  "Page.javascriptDialogOpening",
  "Page.javascriptDialogClosed",
  // JS errors / console
  "Runtime.consoleAPICalled",
  "Runtime.exceptionThrown",
  // Network failures / status correlation
  "Network.requestWillBeSent",
  "Network.responseReceived",
  "Network.loadingFinished",
  "Network.loadingFailed",
  // DevTools log domain
  "Log.entryAdded",
]);

let nativePort = null;
let nativeConnected = false;
let nativeHandshakeOk = false;
let nativeHelloAck = null;
let connectInFlight = null;
let reconnectTimer = null;
let backoffMs = 500;
// Keep reconnection bounded so installing the native host later doesn't require a manual "Reconnect".
const MAX_BACKOFF_MS = 10_000;

let state = {
  // Flagship default: "just works" without a manual UI toggle.
  // Keep followActive OFF by default to avoid cross-agent interference when multiple
  // CLIs are running concurrently.
  enabled: true,
  followActive: false,
  focusedTabId: null,
  lastError: null,
};

let profileId = null;

// tabId(number) -> true (best-effort local cache; MV3 can reset anytime)
const attachedTabs = new Set();

function sendToGateway(payload) {
  // Native-only (portless).
  try {
    if (nativePort && nativeHandshakeOk) {
      nativePort.postMessage(payload);
      return true;
    }
  } catch (_e) {
    // ignore
  }

  return false;
}

function log(level, message, meta) {
  const payload = { type: "log", level, message, meta };
  sendToGateway(payload);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, Number(ms) || 0)));
}

async function hasOffscreenDocument() {
  try {
    if (chrome.offscreen?.hasDocument) return await chrome.offscreen.hasDocument();
  } catch (_e) {
    // ignore
  }

  // Fallback: Chrome 116+ runtime.getContexts
  try {
    if (chrome.runtime?.getContexts) {
      const ctxs = await chrome.runtime.getContexts({ contextTypes: ["OFFSCREEN_DOCUMENT"] });
      return Array.isArray(ctxs) && ctxs.length > 0;
    }
  } catch (_e) {
    // ignore
  }

  return false;
}

async function ensureOffscreenClipboard() {
  if (!chrome.offscreen?.createDocument) throw new Error("chrome.offscreen.createDocument is not available");

  const isTransient = (err) => {
    const msg = String(err?.message || err || "").toLowerCase();
    return (
      msg.includes("receiving end does not exist") ||
      msg.includes("message port closed") ||
      msg.includes("port closed") ||
      msg.includes("no receiving end") ||
      msg.includes("timed out")
    );
  };

  const ping = async () => {
    // Ping the offscreen doc to avoid long timeouts when it isn't ready yet.
    const resp = await sendOffscreenMessageRetry({ type: "offscreen.ping" }, 1200, 3);
    if (!resp || resp.ok !== true) throw new Error("Offscreen ping failed");
  };

  // Fast path: doc exists and responds.
  if (await hasOffscreenDocument()) {
    try {
      await ping();
      return;
    } catch (_e) {
      // fall through to heal below
    }
  }

  // MV3: only one offscreen document is allowed. If it's racing, swallow the error.
  try {
    await chrome.offscreen.createDocument({
      url: chrome.runtime.getURL("offscreen.html"),
      reasons: ["CLIPBOARD"],
      justification: "Write clipboard contents for paste operations initiated by Browser MCP.",
    });
  } catch (e) {
    const msg = String(e?.message || e).toLowerCase();
    if (msg.includes("only one offscreen")) {
      // Another call/context likely won the race. Continue to ping.
    } else {
      // Re-check: another call might have created it.
      if (!(await hasOffscreenDocument())) throw e;
    }
  }

  // Wait for the document to become responsive. If it fails, try one heal-cycle.
  try {
    await ping();
    return;
  } catch (e) {
    if (!isTransient(e)) throw e;
  }

  // Heal: close and re-create once (best-effort).
  try { await closeOffscreenDocument(); } catch (_e) {}
  await sleep(50);
  await chrome.offscreen.createDocument({
    url: chrome.runtime.getURL("offscreen.html"),
    reasons: ["CLIPBOARD"],
    justification: "Write clipboard contents for paste operations initiated by Browser MCP.",
  });
  await ping();
}

async function closeOffscreenDocument() {
  try {
    if (!chrome.offscreen?.closeDocument) return;
    if (!(await hasOffscreenDocument())) return;
    await chrome.offscreen.closeDocument();
  } catch (_e) {
    // ignore
  }
}

function sendOffscreenMessage(payload, timeoutMs = 4000) {
  return new Promise((resolve, reject) => {
    let done = false;
    const t = setTimeout(() => {
      if (done) return;
      done = true;
      reject(new Error("Offscreen message timed out"));
    }, Math.max(250, Number(timeoutMs) || 0));

    try {
      chrome.runtime.sendMessage(payload, (resp) => {
        if (done) return;
        done = true;
        clearTimeout(t);
        const err = chrome.runtime.lastError;
        if (err) {
          reject(new Error(String(err.message || err)));
          return;
        }
        resolve(resp);
      });
    } catch (e) {
      if (done) return;
      done = true;
      clearTimeout(t);
      reject(e);
    }
  });
}

async function sendOffscreenMessageRetry(payload, timeoutMs = 4000, attempts = 2) {
  const maxAttempts = Math.max(1, Math.min(Number(attempts) || 1, 6));
  let lastErr = null;
  for (let i = 0; i < maxAttempts; i++) {
    try {
      // eslint-disable-next-line no-await-in-loop
      return await sendOffscreenMessage(payload, timeoutMs);
    } catch (e) {
      lastErr = e;
      const msg = String(e?.message || e || "").toLowerCase();
      const retryable = msg.includes("receiving end does not exist") || msg.includes("message port closed") || msg.includes("timed out");
      if (!retryable || i >= maxAttempts - 1) throw e;
      // eslint-disable-next-line no-await-in-loop
      await sleep(40 + i * 60);
    }
  }
  throw lastErr || new Error("Offscreen message failed");
}

async function loadState() {
  try {
    const stored = await chrome.storage.local.get({ [STORAGE_KEY]: state });
    const s = stored?.[STORAGE_KEY];
    if (s && typeof s === "object") {
      state = { ...state, ...s };
    }
  } catch (_e) {
    // ignore
  }
}

async function saveState() {
  try {
    await chrome.storage.local.set({ [STORAGE_KEY]: state });
  } catch (_e) {
    // ignore
  }
}

function setLastError(message) {
  const next = message ? String(message) : null;
  if ((state.lastError ?? null) === next) return;
  state.lastError = next;
  // Best-effort persistence (don't block SW).
  try {
    saveState();
  } catch (_e) {
    // ignore
  }
}

async function ensureProfileId() {
  if (typeof profileId === "string" && profileId) return profileId;

  try {
    const stored = await chrome.storage.local.get({ [PROFILE_ID_KEY]: null });
    const existing = stored?.[PROFILE_ID_KEY];
    if (typeof existing === "string" && existing.trim()) {
      profileId = existing.trim();
      return profileId;
    }
  } catch (_e) {
    // ignore
  }

  try {
    const created = typeof crypto?.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    profileId = String(created).trim() || `${Date.now()}-${Math.random()}`;
    await chrome.storage.local.set({ [PROFILE_ID_KEY]: profileId });
    return profileId;
  } catch (_e) {
    profileId = `${Date.now()}-${Math.random()}`;
    return profileId;
  }
}

function buildHelloPayload() {
  return {
    type: "hello",
    protocolVersion: "2026-01-11",
    extensionId: chrome.runtime.id,
    extensionVersion: chrome.runtime.getManifest().version,
    userAgent: navigator.userAgent,
    ...(profileId ? { profileId } : {}),
    capabilities: {
      debugger: true,
      tabs: true,
      clipboardWrite: true,
      clipboardSvgBundle: true,
      cdpSendMany: true,
      rpcBatch: true,
    },
    state: {
      enabled: !!state.enabled,
      followActive: !!state.followActive,
      focusedTabId: state.focusedTabId ?? null,
    },
  };
}

async function tryConnectNativeOnce(reason, timeoutMs = 1200) {
  return await new Promise((resolve) => {
    let done = false;
    let port = null;
    const deadline = Math.max(250, Number(timeoutMs) || 0);

    const t = setTimeout(() => {
      if (done) return;
      done = true;
      try { port?.disconnect(); } catch (_e) {}
      resolve(null);
    }, deadline);

    const finish = (result) => {
      if (done) return;
      done = true;
      clearTimeout(t);
      resolve(result);
    };

    let onMsg = null;
    const cleanup = () => {
      if (port && onMsg) {
        try { port.onMessage.removeListener(onMsg); } catch (_e) {}
      }
    };

    try {
      port = chrome.runtime.connectNative(NATIVE_HOST_NAME);
    } catch (_e) {
      clearTimeout(t);
      resolve(null);
      return;
    }

    onMsg = (msg) => {
      if (!msg || typeof msg !== "object") return;
      if (msg.type !== "helloAck") return;
      cleanup();
      finish({ port, ack: msg });
    };

    try {
      port.onMessage.addListener(onMsg);
      port.onDisconnect.addListener(() => {
        cleanup();
        finish(null);
      });
    } catch (_e) {
      cleanup();
      clearTimeout(t);
      resolve(null);
      return;
    }

    try {
      port.postMessage(buildHelloPayload());
    } catch (_e) {
      // ignore
    }
  });
}

function scheduleReconnect(reason) {
  if (!state.enabled) return;
  if (reconnectTimer) return;
  const delay = Math.min(Math.max(backoffMs, 250), MAX_BACKOFF_MS);
  // Jitter reduces "thundering herd" when multiple Chrome profiles/extensions are enabled.
  const jitter = Math.floor(Math.random() * 180);
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect(reason || "reconnect");
  }, delay + jitter);
  backoffMs = Math.min(Math.floor(backoffMs * 1.8), MAX_BACKOFF_MS);
}

function connect(reason) {
  if (!state.enabled) return;
  if (connectInFlight) return;
  if (nativePort) return;

  connectInFlight = (async () => {
    try { nativePort?.disconnect(); } catch (_e) {}
    nativePort = null;
    nativeConnected = false;
    nativeHandshakeOk = false;
    nativeHelloAck = null;

    await ensureProfileId();

    // Native Messaging only (portless).
    let nativeRes = null;
    try {
      nativeRes = await tryConnectNativeOnce(reason, 1200);
    } catch (_e) {
      nativeRes = null;
    }
    if (nativeRes && nativeRes.port && nativeRes.ack) {
      nativePort = nativeRes.port;
      nativeConnected = true;
      nativeHandshakeOk = true;
      nativeHelloAck = nativeRes.ack;

      backoffMs = 200;
      setLastError(null);

      nativePort.onMessage.addListener((msg) => {
        if (!msg || typeof msg !== "object") return;
        if (msg.type === "rpc") {
          handleRpc(msg).catch((e) => {
            log("error", "rpc handler failed", { error: String(e?.message || e) });
          });
        }
      });

      nativePort.onDisconnect.addListener(() => {
        nativeConnected = false;
        nativeHandshakeOk = false;
        nativePort = null;
        nativeHelloAck = null;
        if (state.enabled) setLastError("Native bridge disconnected");
        scheduleReconnect("native_disconnect");
      });

      log("info", "bridge connected", { reason, transport: "native", helloAck: nativeRes.ack || {} });
      return;
    }

    if (state.enabled) {
      setLastError("Native host not available yet. Start Browser MCP to auto-install; ensure this extension is installed in your profile.");
    }
    scheduleReconnect("native_connect_failed");
  })().finally(() => {
    connectInFlight = null;
  });
}

function ensureConnected(reason) {
  if (!state.enabled) return;
  if (nativeConnected) return;
  connect(reason || "ensureConnected");
}

function rpcReply(id, ok, result, errorMessage, errorData) {
  const out = { type: "rpcResult", id, ok: !!ok };
  if (ok) out.result = result;
  else out.error = { message: String(errorMessage || "rpc failed"), ...(errorData ? { data: errorData } : {}) };
  sendToGateway(out);
}

function normalizeTab(tab) {
  if (!tab) return null;
  return {
    id: String(tab.id),
    url: tab.url || "",
    title: tab.title || "",
    active: !!tab.active,
    windowId: tab.windowId,
  };
}

async function getActiveTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs && tabs[0] ? tabs[0] : null;
}

async function setEnabled(nextEnabled) {
  const enabled = !!nextEnabled;
  state.enabled = enabled;
  await saveState();

  if (!enabled) {
    // Stop all gateway activity when the kill-switch is OFF (fail-closed).
    try { nativePort?.disconnect(); } catch (_e) {}
    nativePort = null;
    nativeConnected = false;
    nativeHandshakeOk = false;
    nativeHelloAck = null;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    backoffMs = 500;
    await closeOffscreenDocument();
    await detachAll();
  } else if (state.followActive) {
    ensureConnected("setEnabled");
    // Best-effort: attach to the user's active tab for instant "I can see it" UX.
    const tab = await getActiveTab();
    if (tab?.id) {
      state.focusedTabId = String(tab.id);
      await saveState();
      await ensureDebuggerAttached(tab.id);
    }
  }

  log("info", "enabled updated", { enabled });
}

async function setFollowActive(nextFollowActive) {
  state.followActive = !!nextFollowActive;
  await saveState();

  if (state.enabled && state.followActive) {
    ensureConnected("setFollowActive");
    const tab = await getActiveTab();
    if (tab?.id) {
      state.focusedTabId = String(tab.id);
      await saveState();
      await ensureDebuggerAttached(tab.id);
    }
  }

  log("info", "followActive updated", { followActive: state.followActive });
}

async function detachAll() {
  try {
    const targets = await chrome.debugger.getTargets();
    const attached = Array.isArray(targets) ? targets.filter((t) => t && t.attached && t.tabId) : [];
    for (const t of attached) {
      try {
        await chrome.debugger.detach({ tabId: t.tabId });
      } catch (_e) {
        // ignore
      }
    }
  } catch (_e) {
    // ignore
  } finally {
    attachedTabs.clear();
  }
}

async function isDebuggerAttached(tabId) {
  if (attachedTabs.has(tabId)) return true;
  try {
    const targets = await chrome.debugger.getTargets();
    const found = Array.isArray(targets) ? targets.find((t) => t && t.tabId === tabId) : null;
    if (found && found.attached) {
      attachedTabs.add(tabId);
      return true;
    }
  } catch (_e) {
    // ignore
  }
  return false;
}

async function ensureDebuggerAttached(tabId) {
  if (!state.enabled) throw new Error("Agent control is OFF (enable it in the extension popup)");

  if (await isDebuggerAttached(tabId)) return;

  try {
    await chrome.debugger.attach({ tabId }, "1.3");
    attachedTabs.add(tabId);
  } catch (e) {
    // If attach failed, re-check if we are attached anyway (MV3 restarts can confuse local cache).
    if (await isDebuggerAttached(tabId)) return;
    const msg = String(e?.message || e);
    throw new Error(`Failed to attach debugger: ${msg}`);
  }
}

async function cdpSend(tabIdStr, method, params) {
  if (!state.enabled) throw new Error("Agent control is OFF (enable it in the extension popup)");
  const tabId = Number(tabIdStr);
  if (!Number.isFinite(tabId)) throw new Error("Invalid tabId");
  await ensureDebuggerAttached(tabId);
  return await chrome.debugger.sendCommand({ tabId }, String(method), params && typeof params === "object" ? params : undefined);
}

async function tabsList() {
  const tabs = await chrome.tabs.query({});
  return (tabs || []).map(normalizeTab).filter(Boolean);
}

async function tabsGet(tabIdStr) {
  const tabId = Number(tabIdStr);
  if (!Number.isFinite(tabId)) return null;
  try {
    const tab = await chrome.tabs.get(tabId);
    return normalizeTab(tab);
  } catch (_e) {
    return null;
  }
}

async function tabsCreate(url, active) {
  const tab = await chrome.tabs.create({ url: String(url || "about:blank"), active: active !== false });
  return { tabId: String(tab.id), tab: normalizeTab(tab) };
}

async function tabsActivate(tabIdStr) {
  const tabId = Number(tabIdStr);
  if (!Number.isFinite(tabId)) throw new Error("Invalid tabId");
  const tab = await chrome.tabs.update(tabId, { active: true });
  if (tab?.windowId !== undefined) {
    try {
      await chrome.windows.update(tab.windowId, { focused: true });
    } catch (_e) {
      // ignore
    }
  }
  return { success: true, tab: normalizeTab(tab) };
}

async function tabsClose(tabIdStr) {
  const tabId = Number(tabIdStr);
  if (!Number.isFinite(tabId)) throw new Error("Invalid tabId");
  await chrome.tabs.remove(tabId);
  attachedTabs.delete(tabId);
  return { success: true };
}

async function dispatchRpc(method, params) {
  const m = String(method || "");
  const p = params && typeof params === "object" ? params : {};

  if (m === "rpc.batch") {
    const calls = Array.isArray(p.calls) ? p.calls : [];
    const stopOnError = p.stopOnError !== false;
    if (!calls.length) return [];

    const results = [];
    for (let i = 0; i < calls.length; i++) {
      const call = calls[i] && typeof calls[i] === "object" ? calls[i] : {};
      const methodName = String(call.method || "");
      const methodParams = call.params && typeof call.params === "object" ? call.params : {};

      if (!methodName) {
        if (stopOnError) {
          const err = new Error(`rpc.batch failed at ${i}: missing method`);
          err.data = { index: i, resultsCount: results.length };
          throw err;
        }
        results.push({ ok: false, error: "missing method" });
        continue;
      }

      try {
        const res = await dispatchRpc(methodName, methodParams);
        results.push({ ok: true, result: res });
      } catch (e) {
        const msg = String(e?.message || e);
        if (stopOnError) {
          const err = new Error(`rpc.batch failed at ${i}: ${methodName}: ${msg}`);
          err.data = { index: i, method: methodName, error: msg, resultsCount: results.length };
          throw err;
        }
        results.push({ ok: false, error: msg, method: methodName });
      }
    }

    return results;
  }

  if (m === "tabs.list") return await tabsList();
  if (m === "tabs.get") return await tabsGet(p.tabId);
  if (m === "tabs.create") return await tabsCreate(p.url, p.active);
  if (m === "tabs.activate") return await tabsActivate(p.tabId);
  if (m === "tabs.close") return await tabsClose(p.tabId);
  if (m === "state.get") {
    const ack = nativeHelloAck;
    return {
      extensionId: chrome.runtime.id,
      enabled: !!state.enabled,
      followActive: !!state.followActive,
      focusedTabId: state.focusedTabId ?? null,
      gateway: {
        transport: "native",
        connected: !!nativeConnected,
        handshakeOk: !!nativeHandshakeOk,
        brokerId: ack?.brokerId ?? null,
        peerCount: ack?.peerCount ?? null,
        sessionId: ack?.sessionId ?? null,
        brokerStartedAtMs: ack?.brokerStartedAtMs ?? null,
      },
      lastError: state.lastError ?? null,
    };
  }
  if (m === "state.set") {
    if (Object.prototype.hasOwnProperty.call(p, "enabled")) await setEnabled(p.enabled);
    if (Object.prototype.hasOwnProperty.call(p, "followActive")) await setFollowActive(p.followActive);
    return { success: true };
  }
  if (m === "cdp.send") return (await cdpSend(p.tabId, p.method, p.params)) || {};
  if (m === "cdp.sendMany") {
    if (!state.enabled) throw new Error("Agent control is OFF (enable it in the extension popup)");
    const tabId = Number(p.tabId);
    if (!Number.isFinite(tabId)) throw new Error("Invalid tabId");

    const commands = Array.isArray(p.commands) ? p.commands : [];
    const stopOnError = p.stopOnError !== false;
    if (!commands.length) return [];

    await ensureDebuggerAttached(tabId);

    const results = [];
    for (let i = 0; i < commands.length; i++) {
      const cmd = commands[i] && typeof commands[i] === "object" ? commands[i] : {};
      const methodName = String(cmd.method || "");
      const methodParams = cmd.params && typeof cmd.params === "object" ? cmd.params : undefined;
      const delayMs = Number(cmd.delayMs || 0);

      if (!methodName) {
        if (stopOnError) {
          const err = new Error(`cdp.sendMany failed at ${i}: missing method`);
          err.data = { index: i, resultsCount: results.length };
          throw err;
        }
        results.push({ ok: false, error: "missing method" });
        continue;
      }

      try {
        const res = await chrome.debugger.sendCommand({ tabId }, methodName, methodParams);
        results.push(res || {});
      } catch (e) {
        const msg = String(e?.message || e);
        if (stopOnError) {
          const err = new Error(`cdp.sendMany failed at ${i}: ${methodName}: ${msg}`);
          err.data = { index: i, method: methodName, error: msg, resultsCount: results.length };
          throw err;
        }
        results.push({ ok: false, error: msg, method: methodName });
      }

      if (delayMs > 0) await sleep(delayMs);
    }

    return results;
  }
  if (m === "clipboard.writeText") {
    if (!state.enabled) throw new Error("Agent control is OFF (enable it in the extension popup)");
    const text = String(p.text ?? "");
    await ensureOffscreenClipboard();
    const resp = await sendOffscreenMessageRetry({ type: "offscreen.clipboard.writeText", text }, 5000, 2);
    if (!resp || resp.ok !== true) throw new Error(String(resp?.error || "Clipboard writeText failed"));
    return resp.result || { ok: true };
  }
  if (m === "clipboard.write") {
    if (!state.enabled) throw new Error("Agent control is OFF (enable it in the extension popup)");
    const items = Array.isArray(p.items) ? p.items : [];
    await ensureOffscreenClipboard();
    const resp = await sendOffscreenMessageRetry({ type: "offscreen.clipboard.write", items }, 8000, 2);
    if (!resp || resp.ok !== true) throw new Error(String(resp?.error || "Clipboard write failed"));
    return resp.result || { ok: true };
  }
  if (m === "clipboard.writeSvg") {
    if (!state.enabled) throw new Error("Agent control is OFF (enable it in the extension popup)");
    const svg = String(p.svg ?? "");
    const includePng = p.includePng !== false;
    const width = p.width;
    const height = p.height;
    const scale = p.scale;
    await ensureOffscreenClipboard();
    const resp = await sendOffscreenMessageRetry(
      { type: "offscreen.clipboard.writeSvgBundle", svg, includePng, width, height, scale },
      12000,
      2
    );
    if (!resp || resp.ok !== true) throw new Error(String(resp?.error || "Clipboard writeSvg failed"));
    return resp.result || { ok: true };
  }

  throw new Error(`Unknown rpc method: ${m}`);
}

async function handleRpc(msg) {
  const id = msg.id;
  const method = String(msg.method || "");
  const params = msg.params && typeof msg.params === "object" ? msg.params : {};

  try {
    rpcReply(id, true, await dispatchRpc(method, params));
  } catch (e) {
    const msg = String(e?.message || e);
    state.lastError = msg;
    await saveState();
    const data = e && typeof e === "object" ? e.data : undefined;
    rpcReply(id, false, null, msg, data && typeof data === "object" ? data : undefined);
  }
}

// UI bridge (popup).
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  // Do not intercept intra-extension offscreen messages (clipboard bridge).
  if (message?.type && String(message.type).startsWith("offscreen.")) return false;
  (async () => {
    try {
      if (message?.type === "ui.getState") {
        const ack = nativeHelloAck;
        sendResponse({
          extensionId: chrome.runtime.id,
          enabled: !!state.enabled,
          followActive: !!state.followActive,
          focusedTabId: state.focusedTabId ?? null,
          gateway: {
            transport: "native",
            connected: !!nativeConnected,
            handshakeOk: !!nativeHandshakeOk,
            brokerId: ack?.brokerId ?? null,
            peerCount: ack?.peerCount ?? null,
            sessionId: ack?.sessionId ?? null,
          },
          lastError: state.lastError ?? null,
        });
        return;
      }
      if (message?.type === "ui.setEnabled") {
        await setEnabled(!!message.enabled);
        sendResponse({ ok: true });
        return;
      }
      if (message?.type === "ui.setFollowActive") {
        await setFollowActive(!!message.followActive);
        sendResponse({ ok: true });
        return;
      }
      if (message?.type === "ui.reconnect") {
        try { nativePort?.disconnect(); } catch (_e) {}
        ensureConnected("ui_reconnect");
        sendResponse({ ok: true });
        return;
      }
      sendResponse({ ok: false, error: "Unknown ui message" });
    } catch (e) {
      sendResponse({ ok: false, error: String(e?.message || e) });
    }
  })();
  return true;
});

// Forward debugger events to the gateway (low-noise allowlist).
chrome.debugger.onEvent.addListener((source, method, params) => {
  if (!state.enabled) return;
  if (!FORWARD_EVENT_ALLOWLIST.has(String(method))) return;
  const tabId = source?.tabId;
  if (!tabId) return;
  try {
    sendToGateway({ type: "cdpEvent", tabId: String(tabId), method, params: params || {} });
  } catch (_e) {
    // ignore
  }
});

chrome.debugger.onDetach.addListener((source, reason) => {
  if (source?.tabId) attachedTabs.delete(source.tabId);
  log("warn", "debugger detached", { tabId: source?.tabId, reason });
});

chrome.tabs.onActivated.addListener(async (activeInfo) => {
  try {
    state.focusedTabId = activeInfo?.tabId ? String(activeInfo.tabId) : null;
    await saveState();
    if (state.enabled && state.followActive && activeInfo?.tabId) {
      await ensureDebuggerAttached(activeInfo.tabId);
    }
  } catch (_e) {
    // ignore
  }
});

chrome.runtime.onInstalled.addListener(async () => {
  await loadState();
  // Connect on install/update when enabled.
  ensureConnected("onInstalled");
  chrome.alarms.create("mcpKeepAlive", { periodInMinutes: 1 });
});

chrome.runtime.onStartup?.addListener(async () => {
  await loadState();
  // Auto-connect only when enabled (kill-switch must be fail-closed).
  ensureConnected("onStartup");
  chrome.alarms.create("mcpKeepAlive", { periodInMinutes: 1 });
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm?.name !== "mcpKeepAlive") return;
  if (!state.enabled) return;
  ensureConnected("alarm_keepalive");
  sendToGateway({ type: "ping", ts: Date.now() });
});

(async () => {
  await loadState();
  // Connect on boot when enabled.
  ensureConnected("boot");
  chrome.alarms.create("mcpKeepAlive", { periodInMinutes: 1 });
  const tab = await getActiveTab();
  if (tab?.id) state.focusedTabId = String(tab.id);
  await saveState();
})();
