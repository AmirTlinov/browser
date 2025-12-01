const DEFAULT_ALLOWLIST = ["*"];
const MAX_BODY_BYTES = 1_000_000;
let allowlist = [...DEFAULT_ALLOWLIST];
let lastActiveTabId = null;

async function loadAllowlist() {
  try {
    const { allowlist: stored } = await chrome.storage.local.get({ allowlist: DEFAULT_ALLOWLIST });
    if (Array.isArray(stored) && stored.length > 0) {
      allowlist = stored.map((h) => String(h).toLowerCase());
    }
  } catch (e) {
    console.warn("Failed to load allowlist", e);
  }
}

function saveAllowlist(hosts) {
  allowlist = hosts;
  return chrome.storage.local.set({ allowlist });
}

function isHostAllowed(host) {
  if (!host) return false;
  const normalized = host.toLowerCase();
  if (allowlist.includes("*")) return true;
  return allowlist.some((allowed) => normalized === allowed || normalized.endsWith(`.${allowed}`));
}

async function getActiveTabId() {
  if (lastActiveTabId !== null) return lastActiveTabId;
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tabs && tabs[0]) {
    lastActiveTabId = tabs[0].id;
    return lastActiveTabId;
  }
  const created = await chrome.tabs.create({ url: "https://example.com/", active: true });
  lastActiveTabId = created?.id ?? null;
  return lastActiveTabId;
}

async function ensureContentScript(tabId) {
  if (tabId === null || tabId === undefined) return false;
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["content_script.js"],
    });
    return true;
  } catch (err) {
    return false;
  }
}

async function handleFetch(url) {
  const parsed = new URL(url);
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error("Only http/https protocols are supported");
  }
  if (!isHostAllowed(parsed.hostname)) {
    throw new Error(`Host ${parsed.hostname} is not allowed`);
  }
  const resp = await fetch(parsed.toString(), { method: "GET", mode: "cors", credentials: "omit" });
  const buffer = await resp.arrayBuffer();
  const truncated = buffer.byteLength > MAX_BODY_BYTES;
  const sliced = truncated ? buffer.slice(0, MAX_BODY_BYTES) : buffer;
  const decoder = new TextDecoder();
  const body = decoder.decode(sliced);
  const headers = {};
  resp.headers.forEach((v, k) => {
    headers[k] = v;
  });
  return {
    ok: true,
    status: resp.status,
    headers,
    body,
    truncated,
  };
}

async function handleDom(message) {
  const { command, selector, text, clear, code } = message;
  const tabId = await getActiveTabId();
  if (!tabId) return { ok: false, error: "No active tab" };
  const injected = await ensureContentScript(tabId);
  if (!injected) return { ok: false, error: "Failed to inject content script" };
  let js;
  if (command === "click") {
    js = `window.__ag_control.click(${JSON.stringify(selector)})`;
  } else if (command === "type") {
    js = `window.__ag_control.type(${JSON.stringify(selector)}, ${JSON.stringify(text || "")}, ${clear !== false})`;
  } else if (command === "eval_js") {
    js = `window.__ag_control.evalJs(${JSON.stringify(code || "")})`;
  } else {
    return { ok: false, error: `Unknown dom command ${command}` };
  }
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      func: (src) => {
        // eslint-disable-next-line no-eval
        return eval(src);
      },
      args: [js],
      world: "MAIN",
    });
    return { ok: true, value: result };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    if (message?.type === "setAllowlist") {
      const hosts = Array.isArray(message.hosts) ? message.hosts.map((h) => String(h).toLowerCase()) : DEFAULT_ALLOWLIST;
      await saveAllowlist(hosts);
      sendResponse({ ok: true, allowlist });
      return;
    }
    if (message?.type === "fetch") {
      try {
        const result = await handleFetch(message.url);
        sendResponse(result);
      } catch (err) {
        sendResponse({ ok: false, error: err?.message || String(err) });
      }
      return;
    }
    if (message?.type === "dom") {
      const result = await handleDom(message);
      sendResponse(result);
      return;
    }
    sendResponse({ ok: false, error: "Unknown message type" });
  })();
  return true;
});

chrome.runtime.onInstalled.addListener(() => {
  loadAllowlist();
});

loadAllowlist();
