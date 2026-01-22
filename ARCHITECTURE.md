[LEGEND]
FLOW = A runtime path from input to side-effects.
REGISTRY = The dispatch table from tool name → handler.
HANDLER = The server-side wrapper that validates args and calls domain tools.
DOMAIN_TOOL = A focused function in `tools/*` that implements one capability.

[CONTENT]
## [FLOW]
1) MCP client sends JSON-RPC over stdio.
2) `main.McpServer` parses message and routes to a handler.
3) [REGISTRY] resolves the tool name to a [HANDLER].
4) The [HANDLER] calls one or more [DOMAIN_TOOL] functions.
5) Browser automation happens via CDP WebSocket sessions (isolated tab per server process).
6) Response is returned as MCP `content[]` (text in [CTX_FORMAT|LEGEND.md], images as `image/png`).

## Structure (by responsibility)
- Contract + versioning: `server/contract.py`
- Dispatch: `server/registry.py`, `server/handlers/unified.py`
- Safety: `server/redaction.py`, `config.py`, `http_client.py`
- Browser lifecycle: `launcher.py`
- CDP session: `session.py`
- Capabilities: `tools/*`

