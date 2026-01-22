[LEGEND]
OUTPUT_FORMAT = The textual shape of [TOOL_RESULT|LEGEND.md] for this server.

[CONTENT]
Contract: Tool output format v1

## Purpose
Define [OUTPUT_FORMAT] so agents can consume results without JSON parsing and without [NOISE|LEGEND.md].

## Scope
- In scope: text response format, truncation, and error representation.
- Out of scope: per-tool payload meaning (defined by tool schemas + behavior).

## Interface
- Tool text responses are returned as Markdown in [CTX_FORMAT|LEGEND.md].
- Default is summary-first: small, stable key/value blocks and short lists.
- Large payloads MUST be paginated or truncated with an explicit marker.

## Errors
- Errors are returned as text in the same [CTX_FORMAT|LEGEND.md].
- The error body MUST include a human-readable reason and a suggested next action.

## Examples
```md
[LEGEND]
FORMAT = Compact key/value output (not JSON).

[CONTENT]
ok: true
tool: page
summary:
  url: https://example.com
  title: Example
next:
  - page(detail="diagnostics")
```

