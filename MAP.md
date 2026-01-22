[LEGEND]
ENTRYPOINT = The canonical place to start reading/running the system.
GOLDEN_PATH = The minimal sequence to get to a reliable working state.
BOUNDARY = A module boundary where contracts and safety matter most.

[CONTENT]
## [GOLDEN_PATH]
- Read `README.md` for quick start.
- Run `./tools/doctor` ([DOCTOR|LEGEND.md]) to confirm the environment.
- Run `./tools/gate` ([GATE|LEGEND.md]) to catch doc drift and CI gates.

## [ENTRYPOINT]
- MCP server entrypoint: `mcp_servers/browser/main.py`
- Tool registry: `mcp_servers/browser/server/registry.py`
- Unified handlers (single surface): `mcp_servers/browser/server/handlers/unified.py`
- Browser lifecycle: `mcp_servers/browser/launcher.py`
- CDP session isolation: `mcp_servers/browser/session.py`

## [BOUNDARY] checklist (when changing behavior)
- Tool contract and schemas: `mcp_servers/browser/server/contract.py`
- Redaction & dumps: `mcp_servers/browser/server/redaction.py`
- Host allowlist (security): `mcp_servers/browser/config.py` and `mcp_servers/browser/http_client.py`
