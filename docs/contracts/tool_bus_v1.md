[LEGEND]
TOOL_BUS = The contract for how tools are invoked and reported.

[CONTENT]
Contract: Tool bus v1

## Purpose
Define [TOOL_BUS]: how tools are invoked, how results are returned, and how failures are represented.

## Scope
- In scope: MCP method surface, response content types, error handling.
- Out of scope: tool-specific schemas (those are per-tool definitions).

## Interface
- Transport: MCP over stdio JSON-RPC.
- Tool list: `tools/list` returns tool definitions with JSON Schemas.
- Tool call: `tools/call` routes to the unified registry.
- Tool result: MCP `content[]` items:
  - `text`: formatted as [CTX_FORMAT|LEGEND.md] (see `tool_output_format_v1.md`).
  - `image`: base64 PNG (for screenshots).

## Errors
- On failure, server returns `isError=true` and a text payload describing:
  - what failed,
  - why it failed,
  - what to try next.

## Examples
```json
{"jsonrpc":"2.0","id":"1","method":"tools/list","params":{}}
```

