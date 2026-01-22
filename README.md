Browser MCP Server
==================

This repository hosts a lightweight Model Context Protocol (MCP) server (protocol `2025-06-18`) that exposes controlled Internet access to AI agents via a locally installed Chrome/Chromium browser.

The server provides **full browser automation capabilities** via Chrome DevTools Protocol (CDP), including mouse control, keyboard input, scrolling, DOM manipulation, and screenshots.

Highlights
----------
- Launches or reuses a Chrome instance with a dedicated profile and remote debugging port, using safe defaults.
- Provides MCP tools to perform safe HTTP GET requests and headless DOM fetches via `--dump-dom`.
- Full browser automation via Chrome DevTools Protocol (CDP): clicks, keyboard, scrolling, drag & drop.
- Enforces basic safety through an allowlist of hosts and configurable timeouts/size limits.

Quick start
-----------

**✅ RECOMMENDED (No Restart): Extension Mode (Your Normal Chrome)**

This is the best experience if you want the agent to drive *your* already-running Chrome
profile (with your tabs, cookies, and extensions) **without** restarting with a
`--remote-debugging-port`.

```bash
# 1) Install the extension (unpacked, dev mode)
#    chrome://extensions → Developer mode → Load unpacked → vendor/browser_extension
#
# 2) Run the MCP server (defaults to extension mode)
./scripts/run_browser_mcp.sh
```

Then open the extension popup and turn **Agent control** ON.

**Alternative (Same Browser): Attach via CDP Port**

Use this if you prefer the classic DevTools Protocol attach flow.

```bash
# 1) Start your browser with a CDP debugging port (localhost only!)
./scripts/start_user_browser_cdp.sh

# 2) Run the MCP server in attach mode
MCP_BROWSER_MODE=attach ./scripts/run_browser_mcp.sh
```

**Alternative: Launch a Dedicated Browser (Portable Chromium)**

Use this if you want a clean, disposable profile for automation.

```bash
# 1. Install Python dependencies
python -m pip install -r requirements.txt

# 2. Download portable Chromium locally (one-time, ~165MB download)
./scripts/install_local_chromium.sh

# 3. Run the MCP server in launch mode
MCP_BROWSER_MODE=launch ./scripts/run_browser_mcp.sh
```

**Alternative: System Chromium**

If you prefer system-wide installation, avoid snap versions:

```bash
# Snap Chromium has issues (ignores --user-data-dir, SingletonLock/profile conflicts)
# Use proper Chromium instead:
./scripts/install_chromium.sh
```

**Defaults:** Profile `~/.gemini/browser-profile`, CDP port `9222`.


Configuration
-------------
Environment variables:
- `MCP_BROWSER_BINARY` — path to Chrome/Chromium binary. If unset, the server auto-detects in this order:
  1. Local Chromium: `vendor/chromium/chrome` (portable, installed via `install_local_chromium.sh`)
  2. System Chromium: `/usr/bin/chromium`, `/usr/bin/chromium-browser`, etc.
  3. System Chrome: `/usr/bin/google-chrome`, `/usr/bin/google-chrome-stable`, etc.
  4. Snap Chromium (last resort - has known issues)
- `MCP_BROWSER_MODE` — lifecycle mode: `extension` (recommended), `attach`, or `launch`. Note: `scripts/run_browser_mcp.sh` defaults to `extension`.
- `MCP_BROWSER_PROFILE` — user-data-dir; default `~/.gemini/browser-profile`.
- `MCP_BROWSER_PORT` — remote debugging port; default `9222`.
- `MCP_BROWSER_FLAGS` — extra flags appended to Chrome launch.
- `MCP_AUTO_PORT_FALLBACK` — if set to `1`, allows switching to a free port + an owned profile when the configured port is busy/unresponsive (default: `0` for deterministic behavior).
- `MCP_ALLOW_HOSTS` — comma-separated allowlist (e.g., `example.com,github.com`). Empty or `*` disables host filtering.
- `MCP_HTTP_TIMEOUT` — request timeout seconds (default 10).
- `MCP_HTTP_MAX_BYTES` — maximum bytes to return from HTTP responses (default 1_000_000).
- `MCP_HEADLESS` — set to `1` for headless mode, `0` for visible window (default: `1`, headless).
- `MCP_WINDOW_SIZE` — initial window size in visible mode, format `width,height` (default: `1280,900`).

Available tools
---------------

This server exports a small set of **unified** tools. The canonical
source of truth is `tools/list` (and the generated snapshot in `contracts/`).

| Tool | What it does |
|------|--------------|
| `page` | Analyze page structure/content; diagnostics/resources/perf/locators |
| `flow` | Batch multiple steps into one call (single compact summary + optional screenshot) |
| `run` | OAVR runner (Observe → Act → Verify → Report); uses `flow` under the hood |
| `app` | High-level macros/adapters for complex apps (e.g. `app(op='diagram')`, `app(op='insert')`) |
| `navigate` | Navigate/back/forward/reload (unified) |
| `click` | Click by text/selector/coordinates |
| `type` | Type text, type into selector, or press key |
| `scroll` | Scroll directions or to element/top/bottom |
| `form` | Fill/select/focus/clear/wait-for-element |
| `screenshot` | Screenshot page or element |
| `tabs` | List/switch/new/close tabs |
| `cookies` | Get/set/delete cookies |
| `captcha` | Detect/interact with common CAPTCHA flows |
| `mouse` | Move/hover/drag low-level |
| `resize` | Resize viewport/window |
| `js` | Evaluate JS in the page |
| `http` | Safe HTTP GET outside the browser (allowlist enforced) |
| `fetch` | Fetch from page context (cookies/session; subject to CORS) |
| `upload` | Upload file(s) to file input |
| `dialog` | Handle alert/confirm/prompt |
| `totp` | Generate TOTP codes (2FA helper) |
| `wait` | Wait for navigation/load/element/text |
| `browser` | Launch/status; DOM/element helpers |

**Output format:** tool text responses are returned as compact **context-format Markdown**
(`"[LEGEND]" + "[CONTENT]"`), not JSON.

Safety defaults
---------------
- Enforce allowlist via `MCP_ALLOW_HOSTS=example.com,github.com`; `*` keeps permissive mode.
- The launcher refuses to start Chrome if the CDP port is already occupied and reports a clear error.
- Chrome is started with `--remote-allow-origins=*` so CDP WebSocket accepts localhost clients.

Safety notes
------------
- Set `MCP_ALLOW_HOSTS` to the minimal set you need; otherwise the server will allow all hosts.
- Ensure the CDP port (`MCP_BROWSER_PORT`) is free before launching to avoid hijacking an existing browser session.
- Headless runs reuse the same profile; isolate with dedicated profiles if you need stricter separation.

Architecture
------------

```
┌──────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│   AI Agent       │─────▶│   MCP Server    │─────▶│   Chrome        │
│   (Claude, etc)  │ MCP  │   (Python)      │ CDP  │   Browser       │
└──────────────────┘      └─────────────────┘      └─────────────────┘
```

The server uses Chrome DevTools Protocol (CDP) directly via WebSocket for all browser automation, including cookie management and in-page fetch requests. This provides deterministic, extension-free operation with any Chrome/Chromium browser.

Testing
-------
Run the test suite:
```
pytest -q --maxfail=1 --cov=mcp_servers --cov-report=term-missing
```
