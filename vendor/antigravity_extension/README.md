Antigravity Browser Extension (offline, unpacked)
==================================================

Purpose
-------
Lightweight MV3 extension that lets the Antigravity/MCP agent fetch web content from the active browser without running the IDE. It exposes a simple `chrome.runtime.sendMessage` API:
- `{ type: "fetch", url }` — performs HTTP(S) GET in the extension context with allowlist enforcement.
- `{ type: "setAllowlist", hosts: ["example.com", "github.com"] }` — updates allowed hosts (stored in `chrome.storage.local`).

Key files
---------
- `manifest.json` — background service worker entry (`service_worker.js`), host permissions `<all_urls>`, no content scripts.
- `service_worker.js` — implements allowlist, fetch with 1MB cap, and basic error reporting.
- `static/` — icons and landing page (kept from original package).

Install (developer mode)
------------------------
1. Open Chrome → `chrome://extensions`.
2. Enable *Developer mode*.
3. Click *Load unpacked* and select `vendor/antigravity_extension`.
4. (Optional) Set allowlist via DevTools console:
   ```js
   chrome.runtime.sendMessage("<EXTENSION_ID>", { type: "setAllowlist", hosts: ["example.com"] }, console.log);
   ```

Usage examples
--------------
Fetch allowed URL:
```js
chrome.runtime.sendMessage("<EXTENSION_ID>", { type: "fetch", url: "https://example.com" }, console.log);
```
Forbidden host returns `{ ok:false, error:"Host ... is not allowed" }`.

Notes
-----
- Default allowlist is `*` (all hosts). For production, set an explicit list.
- Only GET is implemented; extend `service_worker.js` if you need POST/headers.
- Body is truncated to 1 MB to protect memory.

