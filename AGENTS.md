# Browser MCP — Agent Rules (Golden Path)

This repo is optimized for humans + AI agents to collaborate without guesswork.

Golden path:
- Run `./tools/setup` once (creates `.venv`, installs `.[dev]`).
- Run `./tools/doctor` first (diagnose).
- Then run `./tools/gate` (fail-closed correctness + doc drift gate).

Doc standard:
- Repo-root `AGENTS.md` and repo-root `README.md` are freeform Markdown.
- Every other `.md` doc MUST be written in the context format:
  - A `[LEGEND]` block (definitions)
  - A `[CONTENT]` block (body that references tokens)

Change protocol (contracts-first):
1) Update contracts/interfaces first.
2) Update implementation.
3) Update tests.
4) Update docs (context format).
