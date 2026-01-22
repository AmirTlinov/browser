[LEGEND]
EXTENSION_MODE = Browser MCP mode that uses a Chrome extension to control an already-running, user-owned Chrome profile.
EXTENSION = The MV3 Chrome extension installed in the user’s normal Chrome.
GATEWAY = The local WebSocket server inside Browser MCP that the extension connects to.
BRIDGE_PROTOCOL = The message protocol used over the Extension↔Gateway WebSocket.
RPC = Request/response messages (server→extension) used for tab + state operations and for CDP command transport.
CDP_EVENT = A forwarded DevTools Protocol event emitted by the extension (tab-scoped).
KILL_SWITCH = A user-visible on/off toggle that disables all agent control immediately.

[CONTENT]
# Extension Bridge Contract

This doc defines the [CONTRACT|LEGEND.md] for [BRIDGE_PROTOCOL] used by Browser MCP in [EXTENSION_MODE].

## Why this exists
- In [EXTENSION_MODE], Browser MCP must control the user’s normal Chrome *without* launching a separate browser instance.
- The [EXTENSION] is the only reliable way to attach DevTools to an already-running Chrome tab without forcing the user to restart with `--remote-debugging-port`.
- The [GATEWAY] keeps server-side logic AI-native (same tools) while the extension becomes a thin transport layer.

## Transport
- The [EXTENSION] connects as a WebSocket client to the local [GATEWAY] (127.0.0.1).
- Messages MUST be JSON objects.
- Message schema: `contracts/extension_bridge.json`.

## Message types
### Handshake
- `hello` (extension → gateway): identifies the extension instance and sends initial state.
- `helloAck` (gateway → extension): confirms connection and assigns a `sessionId`.
  - `serverStartedAtMs` + `gatewayPort` are OPTIONAL but recommended: they let the extension pick the newest live gateway (when multiple Codex sessions exist) and display the actual bound port.

### Requests (server → extension)
- `rpc`: generic request envelope (a single [RPC] request).
- `rpcResult`: response envelope (`ok=true` with `result`, or `ok=false` with `error`).

### Events (extension → server)
- `cdpEvent`: forwarded CDP event (tab-scoped). Each event is a [CDP_EVENT] used for Tier-0 telemetry + waits.
  - `tabId` is treated as a string in the bridge for stability (Chrome uses integers internally).

### Keepalive + logs
- `ping` / `pong`: best-effort keepalive.
- `log`: extension-side logs surfaced to the gateway (bounded / best-effort).

## Required UX safety
- The extension MUST expose a [KILL_SWITCH] that makes agent control non-ambiguous and instantly reversible.
- When disabled, the extension MUST refuse to execute new `rpc` requests that would change browser state.
