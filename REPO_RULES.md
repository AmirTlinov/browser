[LEGEND]
RESPONSIBILITY = A module-owned unit of logic/rules/state/tests that should evolve together.
WIRING = Composition only (registration/DI/routing). No business logic.
PUBLIC_API = The only supported import surface of a module.
DRIFT = A mismatch between docs/contracts and the live server behavior.

[CONTENT]
# Repo Rules (Browser MCP)

## Golden Path

```bash
./tools/setup
./tools/lint
./tools/gate
```

## Structure & Ownership
- New [RESPONSIBILITY] => new owner module/folder under `mcp_servers/browser/*`.
- Shared code only when 2+ real consumers exist, and the name is domain-specific (no new `utils/` dumps).
- [WIRING] lives in server/registry/handlers layers; domain logic lives in `tools/*` and `apps/*`.

## Public API Boundaries
- External consumers treat MCP `tools/list` as source of truth; `contracts/unified_tools.*` is the generated snapshot.
- Internal Python imports should prefer module public entrypoints; avoid reaching into deep internals unless explicitly marked.

## Contracts & Anti-Drift
- The authoritative tool contract is the runtime `tools/list` output.
- `contracts/unified_tools.json` and `contracts/unified_tools.md` must match `contract_snapshot()`.
- If you change tool schemas/descriptions, regenerate snapshots:

If these drift, that is [DRIFT] and must be fixed before merging.

[PUBLIC_API] here means: consumers rely on MCP `tools/list` + the generated snapshots, not internal Python module structure.

```bash
./tools/contracts
```

## Docs
- Repo-root `README.md` and `AGENTS.md` are freeform.
- All other `.md` files must be context-format: `[LEGEND]` then `[CONTENT]`.
