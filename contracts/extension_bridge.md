[LEGEND]
EXTENSION_MODE = Browser MCP mode that uses a Chrome extension to control an already-running, user-owned Chrome profile.
EXTENSION = The MV3 Chrome extension installed in the user’s normal Chrome.
BROKER = The local bridge process that sits between [EXTENSION] and Browser MCP server processes.
IPC = Local OS-level inter-process communication channel between Browser MCP server processes and the [BROKER] (no TCP ports).
BRIDGE_PROTOCOL = The message protocol used between the [EXTENSION] and [BROKER].
RPC = Request/response messages (server→extension) used for tab + state operations and for CDP command transport.
CDP_EVENT = A forwarded DevTools Protocol event emitted by the extension (tab-scoped).
KILL_SWITCH = A user-visible on/off toggle that disables all agent control immediately.
NATIVE_HOST = A Chrome Native Messaging host used by the [EXTENSION] to communicate without opening network ports directly.
LEGACY_GATEWAY = The legacy local WebSocket gateway inside Browser MCP (TCP localhost). Kept only for fallback/debug.
AUTO_LAUNCH = Optional managed Chrome launch with the extension preloaded (opt-in).

[CONTENT]
# Extension Bridge Contract

This doc defines the [CONTRACT|LEGEND.md] for [BRIDGE_PROTOCOL] used by Browser MCP in [EXTENSION_MODE].

## Why this exists
- In [EXTENSION_MODE], Browser MCP must control the user’s normal Chrome *without* launching a separate browser instance.
- The [EXTENSION] is the only reliable way to attach DevTools to an already-running Chrome tab without forcing the user to restart with `--remote-debugging-port`.
- The [BROKER] makes the bridge *portless*: the extension never needs to connect to `127.0.0.1:<port>`, removing “gateway not reachable” / port-collision failure modes.

## Transport
- Default (flagship): The [EXTENSION] connects to a [NATIVE_HOST] (`com.openai.browser_mcp`). The [NATIVE_HOST] acts as the [BROKER] and exposes a local [IPC] endpoint for Browser MCP server processes to connect to. No TCP ports are required.
- Optional fallback: If explicitly enabled, Browser MCP may [AUTO_LAUNCH] a managed Chrome instance with `--load-extension`.
- Legacy (testing only): Browser MCP has a [LEGACY_GATEWAY] implementation on `127.0.0.1`, but the flagship extension build is native-only to guarantee “0 TCP ports”.
- Messages MUST be JSON objects.
- Message schema: `contracts/extension_bridge.json`.

## Message types
### Handshake
- `hello` ([EXTENSION] → [BROKER]): identifies the extension instance and sends initial state.
- `helloAck` ([BROKER] → [EXTENSION]): confirms connection and assigns a `sessionId`.
  - In portless mode, `gatewayPort` is legacy and MAY be omitted.

### Peer handshake (server-side)
- `peerHello` (Browser MCP server → [BROKER]): connects a server process to the broker.
- `peerHelloAck` ([BROKER] → Browser MCP server): confirms peer connection.

### Requests (server → extension)
- `rpc`: generic request envelope (a single [RPC] request). `timeoutMs` is optional and is used for best-effort request budgeting across proxies.
- `rpcResult`: response envelope (`ok=true` with `result`, or `ok=false` with `error`).

### Events (extension → server)
- `cdpEvent`: forwarded CDP event (tab-scoped). Each event is a [CDP_EVENT] used for Tier-0 telemetry + waits.
  - `tabId` is treated as a string in the bridge for stability (Chrome uses integers internally).

### Keepalive + logs
- `ping` / `pong`: best-effort keepalive.
- `log`: extension-side logs surfaced to the broker (bounded / best-effort).

## Required UX safety
- The extension MUST expose a [KILL_SWITCH] that makes agent control non-ambiguous and instantly reversible.
- When disabled, the extension MUST refuse to execute new `rpc` requests that would change browser state.
