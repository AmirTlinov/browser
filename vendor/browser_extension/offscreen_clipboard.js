// Offscreen document (MV3) for clipboard operations.
//
// Service workers cannot access the Clipboard API directly.
// This document is created via chrome.offscreen.createDocument({reasons:['CLIPBOARD']})
// and handles clipboard write requests.

function withTimeout(promise, ms, label) {
  const timeoutMs = Math.max(50, Number(ms) || 0);
  const name = String(label || "operation");
  return new Promise((resolve, reject) => {
    let done = false;
    const t = setTimeout(() => {
      if (done) return;
      done = true;
      reject(new Error(`${name} timed out`));
    }, timeoutMs);

    Promise.resolve(promise)
      .then((v) => {
        if (done) return;
        done = true;
        clearTimeout(t);
        resolve(v);
      })
      .catch((e) => {
        if (done) return;
        done = true;
        clearTimeout(t);
        reject(e);
      });
  });
}

function base64ToUint8Array(b64) {
  const raw = atob(String(b64 || ""));
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function parseSvgSize(svgText) {
  const fallback = { width: 1200, height: 800, source: "fallback" };
  const raw = String(svgText || "").trim();
  if (!raw) return fallback;

  try {
    const doc = new DOMParser().parseFromString(raw, "image/svg+xml");
    const svg = doc?.documentElement;
    if (!svg || String(svg.tagName).toLowerCase() !== "svg") return fallback;

    const parseLen = (value) => {
      const s = String(value || "").trim();
      if (!s) return null;
      const m = s.match(/^([0-9.]+)(px)?$/i);
      if (!m) return null;
      const n = Number(m[1]);
      return Number.isFinite(n) && n > 0 ? n : null;
    };

    let w = parseLen(svg.getAttribute("width"));
    let h = parseLen(svg.getAttribute("height"));
    if (w && h) return { width: w, height: h, source: "width_height" };

    const vb = String(svg.getAttribute("viewBox") || "").trim();
    if (vb) {
      const parts = vb.split(/[\s,]+/).map((x) => Number(x)).filter((n) => Number.isFinite(n));
      if (parts.length >= 4) {
        w = parts[2] > 0 ? parts[2] : null;
        h = parts[3] > 0 ? parts[3] : null;
        if (w && h) return { width: w, height: h, source: "viewBox" };
      }
    }
  } catch (_e) {
    // ignore
  }
  return fallback;
}

async function svgToPngBlob(svgText, opts) {
  const svg = String(svgText || "");
  const scale = Math.max(0.25, Math.min(Number(opts?.scale || 1) || 1, 8));

  const inferred = parseSvgSize(svg);
  const w0 = Number(opts?.width) || inferred.width;
  const h0 = Number(opts?.height) || inferred.height;

  const width = Math.max(1, Math.min(Math.floor(w0 * scale), 4096));
  const height = Math.max(1, Math.min(Math.floor(h0 * scale), 4096));

  const svgBlob = new Blob([svg], { type: "image/svg+xml" });
  const url = URL.createObjectURL(svgBlob);

  try {
    const img = new Image();
    img.decoding = "async";
    const loaded = new Promise((resolve, reject) => {
      img.onload = () => resolve(true);
      img.onerror = () => reject(new Error("Failed to load SVG into Image()"));
    });
    img.src = url;
    await withTimeout(loaded, 3000, "SVG image load");

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas 2D context unavailable");

    // Keep transparency by default; many canvas apps accept PNG alpha.
    ctx.clearRect(0, 0, width, height);
    ctx.drawImage(img, 0, 0, width, height);

    const blob = await new Promise((resolve, reject) => {
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("canvas.toBlob returned null"))), "image/png");
    });
    return { blob, width, height, scale, source: inferred.source };
  } finally {
    try { URL.revokeObjectURL(url); } catch (_e) {}
  }
}

async function writeText(text) {
  const s = String(text ?? "");
  if (navigator.clipboard?.writeText) {
    await withTimeout(navigator.clipboard.writeText(s), 4000, "clipboard.writeText");
    return { ok: true, method: "navigator.clipboard.writeText", bytes: s.length };
  }

  // Fallback: execCommand('copy') (best-effort).
  const ta = document.createElement("textarea");
  ta.value = s;
  ta.setAttribute("readonly", "true");
  ta.style.position = "fixed";
  ta.style.left = "-9999px";
  document.body.appendChild(ta);
  ta.select();
  const ok = document.execCommand("copy");
  document.body.removeChild(ta);
  if (!ok) throw new Error("execCommand('copy') failed");
  return { ok: true, method: "document.execCommand(copy)", bytes: s.length };
}

async function writeItems(items) {
  if (!navigator.clipboard?.write) throw new Error("navigator.clipboard.write is not available");
  if (typeof ClipboardItem === "undefined") throw new Error("ClipboardItem is not available");

  const entries = {};
  const arr = Array.isArray(items) ? items : [];
  for (const it of arr) {
    if (!it || typeof it !== "object") continue;
    const mime = String(it.mime || "").trim();
    const dataBase64 = String(it.dataBase64 || "");
    if (!mime || !dataBase64) continue;
    const bytes = base64ToUint8Array(dataBase64);
    entries[mime] = new Blob([bytes], { type: mime });
  }

  const mimes = Object.keys(entries);
  if (!mimes.length) throw new Error("No clipboard items provided");

  await withTimeout(navigator.clipboard.write([new ClipboardItem(entries)]), 7000, "clipboard.write");
  return { ok: true, method: "navigator.clipboard.write", mimes };
}

async function writeSvgBundle(message) {
  if (!navigator.clipboard?.write) throw new Error("navigator.clipboard.write is not available");
  if (typeof ClipboardItem === "undefined") throw new Error("ClipboardItem is not available");

  const svg = String(message?.svg || "");
  if (!svg.trim()) throw new Error("svg is required");

  const includePng = message?.includePng !== false;
  const svgBlob = new Blob([svg], { type: "image/svg+xml" });
  const entries = { "image/svg+xml": svgBlob };

  let pngInfo = null;
  if (includePng) {
    try {
      pngInfo = await withTimeout(
        svgToPngBlob(svg, {
          width: message?.width,
          height: message?.height,
          scale: message?.scale,
        }),
        9000,
        "SVG→PNG render"
      );
      entries["image/png"] = pngInfo.blob;
    } catch (_e) {
      // Robustness: if PNG rendering fails (e.g., SVG references unsupported resources),
      // still write SVG to clipboard rather than failing the whole operation.
      pngInfo = null;
    }
  }

  await withTimeout(navigator.clipboard.write([new ClipboardItem(entries)]), 9000, "clipboard.write");
  return {
    ok: true,
    method: "navigator.clipboard.write",
    mimes: Object.keys(entries),
    png: pngInfo ? { width: pngInfo.width, height: pngInfo.height, scale: pngInfo.scale, source: pngInfo.source } : null,
  };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    try {
      if (message?.type === "offscreen.ping") {
        sendResponse({ ok: true, ts: Date.now() });
        return;
      }
      if (message?.type === "offscreen.clipboard.writeText") {
        const res = await writeText(message.text);
        sendResponse({ ok: true, result: res });
        return;
      }
      if (message?.type === "offscreen.clipboard.write") {
        const res = await writeItems(message.items);
        sendResponse({ ok: true, result: res });
        return;
      }
      if (message?.type === "offscreen.clipboard.writeSvgBundle") {
        const res = await writeSvgBundle(message);
        sendResponse({ ok: true, result: res });
        return;
      }
      sendResponse({ ok: false, error: "Unknown offscreen message" });
    } catch (e) {
      sendResponse({ ok: false, error: String(e?.message || e) });
    }
  })();
  return true;
});
