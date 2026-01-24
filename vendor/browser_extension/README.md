[LEGEND]
EXTENSION = The MV3 Chrome extension installed into the user’s normal Chrome profile.
BROKER = The local Native Messaging host (`com.openai.browser_mcp`) that bridges the extension to Browser MCP server processes without TCP ports.
EXTENSION_MODE = Browser MCP mode that uses the extension instead of a separate Chrome instance.
KILL_SWITCH = A user-visible toggle that disables all agent control immediately.

[CONTENT]
# Browser MCP Extension

This [EXTENSION] enables [EXTENSION_MODE] by acting as a thin DevTools Protocol proxy:
- The extension attaches to real tabs via `chrome.debugger`.
- The extension connects to a local [BROKER] over Native Messaging (portless: no `127.0.0.1:<port>` gateway).
  The broker multiplexes multiple Browser MCP server peers through a single extension connection.
- For high-frequency input (drag/typing), the extension supports batched CDP (`cdp.sendMany`) so Browser MCP can send many events in one bridge round-trip.
- For low-noise control-plane calls (tabs/state), the extension supports RPC batching (`rpc.batch`) so Browser MCP can collapse multiple RPC calls into one message.
- Browser MCP keeps its AI-native tools unchanged; only the transport changes.

For canvas apps, the extension also enables a clipboard write bridge:
- Browser MCP can write clipboard data via an [OFFSCREEN_DOC|LEGEND.md] (Chrome MV3) and then paste into the app ([CLIPBOARD_BRIDGE|LEGEND.md] + [PASTE_FLOW|LEGEND.md]).
  This avoids slow menu hunting and reduces “chatty” UI loops.
- The clipboard bridge uses an offscreen “ping” handshake and strict timeouts so a stuck clipboard call fails fast and the agent can fall back to drag&drop/import.
- For SVG diagrams, the extension can also render `image/png` (in the [OFFSCREEN_DOC|LEGEND.md]) and write *both* `image/png` and `image/svg+xml` to the clipboard, improving paste compatibility across apps.

## Install (unpacked, dev mode)
1. Open `chrome://extensions`.
2. Enable **Developer mode** (Chrome limitation: extensions cannot enable this themselves).
3. Click **Load unpacked** → select `vendor/browser_extension`.
4. Pin the “Browser MCP” extension and open its popup to verify it is enabled.

## Run Browser MCP in extension mode
- Set `MCP_BROWSER_MODE=extension`.
- The server auto-installs the native host on startup (best-effort). You can also install it manually:
  - `./tools/setup`
  - `./tools/install_native_host`

This mode is portless: the extension talks to the [BROKER] via Native Messaging and the Browser MCP server connects via local IPC.

## Popup controls
- **Agent control** ([KILL_SWITCH]): when OFF, the extension refuses to execute any browser-changing commands and disconnects the native bridge (fail-closed).
- The extension keeps the native bridge healthy automatically; you generally don't need to touch the popup.
- Auto-launch of a managed Chrome is optional and disabled by default (`MCP_EXTENSION_AUTO_LAUNCH=1` to enable).
- **Follow active tab**: when ON, Browser MCP will (by default) adopt your currently focused tab as the session tab.
  In multi-CLI usage, peer sessions default to isolated tabs to avoid cross-agent interference.
- **Reconnect**: forces a reconnect to the native host (rarely needed).
- **Copy diagnostics**: copies a small JSON snapshot for debugging.

## Known limitations (Chrome platform constraints)
- Only one DevTools debugger can be attached to a tab at a time. If the extension cannot attach, close DevTools for that tab.
- Some internal pages (e.g. `chrome://…`) may not be debuggable via the extension.
