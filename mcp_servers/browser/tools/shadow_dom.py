"""Shared JavaScript helpers for working with complex DOM surfaces.

These helpers traverse:
- *open* shadow roots (via `el.shadowRoot`)
- same-origin iframes (via `iframe.contentDocument`)

Cross-origin iframes are intentionally skipped (access throws).
"""

from __future__ import annotations

DEEP_QUERY_JS = r"""
const __mcpCssEscape = (value) => {
  try {
    if (globalThis.CSS && typeof globalThis.CSS.escape === 'function') return globalThis.CSS.escape(String(value));
  } catch (e) {
    // ignore
  }
  return String(value).replace(/[^a-zA-Z0-9_-]/g, (c) => `\\${c}`);
};

const __mcpCollectRoots = (start) => {
  const roots = [];
  const queue = [{ root: start, depth: 0 }];
  const MAX_ROOTS = 60;
  const MAX_DEPTH = 6;
  const MAX_SCAN = 4000;

  while (queue.length && roots.length < MAX_ROOTS) {
    const item = queue.shift();
    const root = item && item.root;
    const depth = item && typeof item.depth === 'number' ? item.depth : 0;
    if (!root) continue;
    if (roots.includes(root)) continue;
    roots.push(root);
    if (depth >= MAX_DEPTH) continue;
    if (!root.querySelectorAll) continue;

    let scanned = 0;
    for (const el of root.querySelectorAll('*')) {
      scanned += 1;
      if (scanned > MAX_SCAN) break;
      if (el && el.shadowRoot) {
        queue.push({ root: el.shadowRoot, depth: depth + 1 });
        if (roots.length + queue.length >= MAX_ROOTS) break;
      }
      if (el && (el.tagName === 'IFRAME' || el.tagName === 'FRAME')) {
        try {
          const doc = el.contentDocument || (el.contentWindow && el.contentWindow.document);
          if (doc) {
            queue.push({ root: doc, depth: depth + 1 });
            if (roots.length + queue.length >= MAX_ROOTS) break;
          }
        } catch (e) {
          // Cross-origin frame; ignore.
        }
      }
    }
  }

  return roots;
};

const __mcpIsVisible = (el) => {
  try {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const style = globalThis.getComputedStyle ? globalThis.getComputedStyle(el) : null;
    if (!style) return true;
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    if (Number(style.opacity || '1') === 0) return false;
    return true;
  } catch (e) {
    return false;
  }
};

const __mcpQueryAllDeep = (selector, maxTotal) => {
  const roots = __mcpCollectRoots(document);
  const out = [];
  const cap = typeof maxTotal === 'number' && maxTotal > 0 ? maxTotal : 1000;

  for (const r of roots) {
    try {
      out.push(...Array.from(r.querySelectorAll(selector)));
      if (out.length >= cap) break;
    } catch (e) {
      // ignore
    }
  }

  return out.slice(0, cap);
};

const __mcpPickIndex = (length, index) => {
  if (!length || length <= 0) return null;
  let idx = typeof index === 'number' ? index : 0;
  if (idx < 0) idx = length + idx;
  if (idx < 0) idx = 0;
  if (idx >= length) idx = length - 1;
  return idx;
};
"""
