Antigravity Browser MCP Server
==============================

This repository hosts a lightweight Model Context Protocol (MCP) server (protocol `2025-06-18`) that exposes controlled Internet access to AI agents via the locally installed Antigravity/Chrome browser.

The server provides **full browser automation capabilities** matching Antigravity IDE, including mouse control, keyboard input, scrolling, DOM manipulation, and screenshots.

Highlights
----------
- Launches or reuses a Chrome instance with a dedicated profile and remote debugging port, mirroring the Antigravity launcher defaults.
- Provides MCP tools to perform safe HTTP GET requests and headless DOM fetches via `--dump-dom`.
- Full browser automation via Chrome DevTools Protocol (CDP): clicks, keyboard, scrolling, drag & drop.
- Enforces basic safety through an allowlist of hosts and configurable timeouts/size limits.

Quick start
-----------

**✅ RECOMMENDED: Use Local Chromium (No System Installation Required)**

The simplest way is to use the bundled local Chromium - no system dependencies:

```bash
# 1. Install Python dependencies
python -m pip install -r requirements.txt

# 2. Download portable Chromium locally (one-time, ~165MB download)
./scripts/install_local_chromium.sh

# 3. Run the MCP server
./scripts/run_browser_mcp.sh
```

The local Chromium is automatically detected and used - no configuration needed!

**Alternative: System Chromium**

If you prefer system-wide installation, avoid snap versions:

```bash
# Snap Chromium has issues (ignores --user-data-dir, blocks extensions, SingletonLock)
# Use proper Chromium instead:
./scripts/install_chromium.sh
```

**Defaults:** Profile `~/.gemini/antigravity-browser-profile`, CDP port `9222`.


Configuration
-------------
Environment variables:
- `MCP_BROWSER_BINARY` — path to Chrome/Chromium binary. If unset, the server auto-detects in this order:
  1. Local Chromium: `vendor/chromium/chrome` (portable, installed via `install_local_chromium.sh`)
  2. System Chromium: `/usr/bin/chromium`, `/usr/bin/chromium-browser`, etc.
  3. System Chrome: `/usr/bin/google-chrome`, `/usr/bin/google-chrome-stable`, etc.
  4. Snap Chromium (last resort - has known issues)
- `MCP_BROWSER_PROFILE` — user-data-dir; default `~/.gemini/antigravity-browser-profile`.
- `MCP_BROWSER_PORT` — remote debugging port; default `9222`.
- `MCP_BROWSER_FLAGS` — extra flags appended to Chrome launch.
- `MCP_ALLOW_HOSTS` — comma-separated allowlist (e.g., `example.com,github.com`). Empty or `*` disables host filtering.
- `MCP_HTTP_TIMEOUT` — request timeout seconds (default 10).
- `MCP_HTTP_MAX_BYTES` — maximum bytes to return from HTTP responses (default 1_000_000).
- `MCP_HEADLESS` — set to `1` for headless mode, `0` for visible window (default: `0`, visible).
- `MCP_WINDOW_SIZE` — initial window size in visible mode, format `width,height` (default: `1280,900`).

Available tools
---------------

### Basic Tools
| Tool | Description |
|------|-------------|
| `http_get` | Fetches an URL over HTTP(S) with allowlist enforcement |
| `launch_browser` | Ensures Chrome is running with the configured debugging port/profile |
| `cdp_version` | Launches Chrome if needed and returns `/json/version` payload |
| `js_eval` | Evaluates a JavaScript expression via CDP Runtime |

### Fetch & Cookie Tools (CDP-based)
| Tool | Description |
|------|-------------|
| `browser_fetch` | Fetch URL from page context (uses page cookies, subject to CORS) |
| `browser_set_cookie` | Set a single cookie via CDP Network domain |
| `browser_set_cookies` | Set multiple cookies in batch |
| `browser_get_cookies` | Get all cookies (optionally filtered by URLs) |
| `browser_delete_cookie` | Delete a cookie by name and domain |

### Navigation Tools
| Tool | Description |
|------|-------------|
| `browser_navigate` | Navigate to a URL in the active browser tab |
| `browser_back` | Navigate back in browser history |
| `browser_forward` | Navigate forward in browser history |
| `browser_reload` | Reload the current page (optional cache bypass) |

### Screenshot & DOM Tools
| Tool | Description |
|------|-------------|
| `screenshot` | Captures a PNG screenshot via CDP |
| `dump_dom` | Renders a page and returns its DOM HTML |
| `browser_get_dom` | Get DOM HTML of current page or specific element |
| `browser_get_element` | Get detailed info about an element (bounds, attributes, text) |
| `browser_get_page_info` | Get current page info (URL, title, scroll position, viewport) |

### Click Tools
| Tool | Description |
|------|-------------|
| `browser_click` | Click an element by CSS selector |
| `browser_click_pixel` | Click at specific pixel coordinates |
| `browser_double_click` | Double-click at specific coordinates |

### Mouse Tools
| Tool | Description |
|------|-------------|
| `browser_move_mouse` | Move mouse to specific coordinates |
| `browser_hover` | Hover over an element (move mouse to its center) |
| `browser_drag` | Drag from one point to another (drag & drop) |

### Keyboard Tools
| Tool | Description |
|------|-------------|
| `browser_type` | Type text into an input element |
| `browser_press_key` | Press a keyboard key (Enter, Tab, Escape, ArrowUp, etc.) |
| `browser_type_text` | Type text using keyboard events (for focused element) |

### Scroll Tools
| Tool | Description |
|------|-------------|
| `browser_scroll` | Scroll the page by delta amounts |
| `browser_scroll_down` | Scroll down by a specified amount |
| `browser_scroll_up` | Scroll up by a specified amount |
| `browser_scroll_to_element` | Scroll an element into view |

### Form Tools
| Tool | Description |
|------|-------------|
| `browser_select_option` | Select an option in a `<select>` dropdown |
| `browser_focus` | Focus an element |
| `browser_clear_input` | Clear an input element's value |

### Window Tools
| Tool | Description |
|------|-------------|
| `browser_resize_viewport` | Resize the browser viewport (content area) |
| `browser_resize_window` | Resize the browser window |

### Wait Tools
| Tool | Description |
|------|-------------|
| `browser_wait_for_element` | Wait for an element to appear in the DOM |

Tool Comparison with Antigravity IDE
------------------------------------

| Antigravity IDE | This MCP Server | Status |
|-----------------|-----------------|--------|
| `browser_navigate` | `browser_navigate` | ✅ |
| `browser_click_element` | `browser_click` | ✅ |
| `click_browser_pixel` | `browser_click_pixel` | ✅ |
| `browser_input` | `browser_type` | ✅ |
| `browser_press_key` | `browser_press_key` | ✅ |
| `browser_scroll` | `browser_scroll` | ✅ |
| `browser_scroll_down` | `browser_scroll_down` | ✅ |
| `browser_scroll_up` | `browser_scroll_up` | ✅ |
| `browser_drag_pixel_to_pixel` | `browser_drag` | ✅ |
| `browser_move_mouse` | `browser_move_mouse` | ✅ |
| `browser_select_option` | `browser_select_option` | ✅ |
| `browser_resize_window` | `browser_resize_window` | ✅ |
| `capture_browser_screenshot` | `screenshot` | ✅ |
| `browser_get_dom` | `browser_get_dom` | ✅ |

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
