Browser MCP Server
==================

![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-2025--06--18-5c6ac4)
![Modes](https://img.shields.io/badge/modes-extension%20%7C%20attach%20%7C%20launch-2ea44f)

A lightweight Model Context Protocol (MCP) server that gives AI agents controlled, real-browser
automation through Chrome/Chromium via Chrome DevTools Protocol (CDP).

It is designed to be predictable and safe: allowlisted hosts, bounded timeouts, stable tooling, and
one shared session for multi-step runs.

What you get
------------
- Drive a real browser: click, type, scroll, drag, screenshot, and navigate.
- Make long sequences reliable with `run(...)` and `flow(...)` (single call, bounded, low noise).
- Extension mode for your existing Chrome profile (no restart, no debug port).

Quick start (golden path)
-------------------------
1) One-time setup:

```bash
./tools/setup
```

2) Diagnose environment:

```bash
./tools/doctor
```

3) Verify the repo is healthy:

```bash
./tools/gate
```

4) Run the server (extension mode is default):

```bash
./scripts/run_browser_mcp.sh
```

Choose a mode
-------------
**Recommended: Extension mode (no restart).**
- Drives your existing Chrome profile with your tabs/cookies/extensions.
- No CDP port needed; fewer connection headaches.

```bash
./scripts/run_browser_mcp.sh
```

**Attach to a CDP port (classic).**

```bash
./scripts/start_user_browser_cdp.sh
MCP_BROWSER_MODE=attach ./scripts/run_browser_mcp.sh
```

**Launch a dedicated Chromium (clean profile).**

```bash
python -m pip install -r requirements.txt
./scripts/install_local_chromium.sh
MCP_BROWSER_MODE=launch ./scripts/run_browser_mcp.sh
```

Configuration
-------------
Environment variables:
- `MCP_BROWSER_BINARY` — path to Chrome/Chromium binary. If unset, the server auto-detects in this order:
  1. Local Chromium: `vendor/chromium/chrome` (portable, installed via `install_local_chromium.sh`)
  2. System Chromium: `/usr/bin/chromium`, `/usr/bin/chromium-browser`, etc.
  3. System Chrome: `/usr/bin/google-chrome`, `/usr/bin/google-chrome-stable`, etc.
  4. Snap Chromium (last resort - has known issues)
- `MCP_BROWSER_MODE` — lifecycle mode: `extension` (recommended), `attach`, or `launch`.
- `MCP_BROWSER_PROFILE` — user-data-dir; default `~/.gemini/browser-profile`.
- `MCP_BROWSER_PORT` — remote debugging port; default `9222`.
- `MCP_BROWSER_FLAGS` — extra flags appended to Chrome launch.
- `MCP_EXTENSION_RPC_TIMEOUT` — extension-mode RPC/CDP timeout seconds (default 8).
- `MCP_EXTENSION_CONNECT_TIMEOUT` — wait-for-extension connect timeout seconds (default 4).
- `MCP_NATIVE_HOST_AUTO_INSTALL` — auto-install Native Messaging host on startup (default 1; set 0 to disable).
- `MCP_EXTENSION_AUTO_LAUNCH` — auto-launch managed Chrome with the extension if no broker is found (default 0; opt-in).
- `MCP_EXTENSION_PROFILE` — user-data-dir for the managed extension Chrome profile (default `~/.gemini/browser-extension-profile`).
- `MCP_EXTENSION_IDS` — comma-separated extension IDs to allow in the native host manifest (optional).
- `MCP_AUTO_PORT_FALLBACK` — if set to `1`, allows switching to a free port + an owned profile when the configured port is busy/unresponsive (default: `0`).
- `MCP_ALLOW_HOSTS` — comma-separated allowlist (e.g., `example.com,github.com`). Empty or `*` disables host filtering.
- `MCP_HTTP_TIMEOUT` — request timeout seconds (default 10).
- `MCP_HTTP_MAX_BYTES` — maximum bytes to return from HTTP responses (default 1_000_000).
- `MCP_HEADLESS` — set to `1` for headless mode, `0` for visible window (default: `1`).
- `MCP_WINDOW_SIZE` — initial window size in visible mode, format `width,height` (default: `1280,900`).

Available tools
---------------
This server exports a small set of **unified** tools. The canonical source of truth is `tools/list`
(and the generated snapshot in `contracts/`).

| Tool | What it does |
|------|--------------|
| `page` | Analyze page structure/content; diagnostics/resources/perf/locators |
| `extract_content` | Structured content extraction with pagination |
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

Docs and guides
---------------
- `docs/RUN_GUIDE.md` — minimal-call run/flow examples
- `docs/AGENT_PLAYBOOK.md` — patterns for low-noise automation
- `docs/MACROS.md` — macro catalog for `run(...)`
- `docs/RUNBOOKS.md` — recording and replaying step lists
- `docs/RELEASE_NOTES.md` — recent changes
- `TROUBLESHOOTING.md` — common fixes

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

The server uses Chrome DevTools Protocol (CDP) directly via WebSocket for all browser automation,
including cookie management and in-page fetch requests.

Testing
-------
Recommended:
```
./tools/gate
```

Focused runs:
```
pytest -q --maxfail=1 --cov=mcp_servers --cov-report=term-missing
```

Live integration (real sites):
```
RUN_BROWSER_INTEGRATION=1 pytest -q tests/test_real_sites_smoke.py
```

Strict live allowlist (fail on low pass-rate):
```
RUN_BROWSER_INTEGRATION=1 RUN_BROWSER_INTEGRATION_EDGE=1 \
RUN_BROWSER_INTEGRATION_LIVE_STRICT=1 \
RUN_BROWSER_INTEGRATION_LIVE_ALLOWLIST=content_root_debug,table_index,container_news \
RUN_BROWSER_INTEGRATION_LIVE_MIN_PASS=1.0 \
pytest -q tests/test_real_sites_smoke.py
```
