// Minimal DOM control helper injected into all pages.
// Exposes a tiny API via window.__ag_control for the service worker to call.

(function () {
  if (window.__ag_control) return;

  function find(selector) {
    return document.querySelector(selector);
  }

  async function click(selector) {
    const el = find(selector);
    if (!el) throw new Error(`Element not found: ${selector}`);
    el.click();
    return true;
  }

  async function type(selector, text, clear = true) {
    const el = find(selector);
    if (!el) throw new Error(`Element not found: ${selector}`);
    if (clear) el.value = "";
    el.focus();
    el.value += text;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  async function evalJs(code) {
    // eslint-disable-next-line no-eval
    return eval(code);
  }

  window.__ag_control = { click, type, evalJs };
})();
