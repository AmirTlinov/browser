[LEGEND]
EXTENSION = The MV3 Chrome extension installed into the user’s normal Chrome profile.
GATEWAY = The local WebSocket server inside Browser MCP that the extension connects to.
EXTENSION_MODE = Browser MCP mode that uses the extension instead of a separate Chrome instance.
KILL_SWITCH = A user-visible toggle that disables all agent control immediately.

[CONTENT]
# Browser MCP Extension

This [EXTENSION] enables [EXTENSION_MODE] by acting as a thin DevTools Protocol proxy:
- The extension attaches to real tabs via `chrome.debugger`.
- The extension connects to the local [GATEWAY] over WebSocket (`ws://127.0.0.1:8765` by default).
  Discovery uses a quiet HTTP probe (`http://127.0.0.1:<port>/.well-known/browser-mcp-gateway`) to find a
  running gateway without noisy `WebSocket(...)` failures in the extension console.
  
  Multi-CLI note (flagship UX): Browser MCP uses a leader lock so **only one** process binds the gateway
  listener ports. Other Browser MCP processes connect as peers and proxy through that leader, so you can
  run many CLI sessions concurrently (10+) while the extension stays connected 100% (no port conflicts).
- For high-frequency input (drag/typing), the extension supports batched CDP (`cdp.sendMany`) so Browser MCP can send many events in one gateway round-trip.
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
4. Pin the “Browser MCP” extension, open its popup, and keep the [KILL_SWITCH] **OFF** until you need control.

## Run Browser MCP in extension mode
- Set `MCP_BROWSER_MODE=extension`.
- Optional:
  - `MCP_EXTENSION_PORT` (default `8765`)
  - `MCP_EXTENSION_HOST` (default `127.0.0.1`)
  - `MCP_EXTENSION_ID` (if you want the gateway to accept only your extension id)
  - `MCP_EXTENSION_PORT_RANGE` (e.g. `8765-8775`) to control the auto-bind range
  - `MCP_EXTENSION_PORT_SPAN` (default `50`) to control the default range size when `MCP_EXTENSION_PORT_RANGE` is not set

## Popup controls
- **Agent control** ([KILL_SWITCH]): when OFF, the extension refuses to execute any browser-changing commands.
- When [KILL_SWITCH] is OFF, the extension also avoids connecting to the [GATEWAY] (prevents noisy “connection refused” spam when Browser MCP isn’t running).
- **Follow active tab**: when ON, Browser MCP will (by default) adopt your currently focused tab as the session tab.
  In multi-CLI usage, peer sessions default to isolated tabs to avoid cross-agent interference.
- **Gateway (Configured)**: override the base gateway URL if needed (Save/Reset). In most cases you can keep the default.
- **Gateway (Last good)**: shows the last working gateway URL discovered automatically (useful when multiple sessions/ports exist).

## Known limitations (Chrome platform constraints)
- Only one DevTools debugger can be attached to a tab at a time. If the extension cannot attach, close DevTools for that tab.
- Some internal pages (e.g. `chrome://…`) may not be debuggable via the extension.
