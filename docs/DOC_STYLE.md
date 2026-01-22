[LEGEND]
STYLE_RULE = A deterministic rule enforced by [GATE|LEGEND.md].

[CONTENT]
## Context-format docs ([DOC_FORMAT|LEGEND.md])
Every Markdown doc except repo-root `README.md` and repo-root `AGENTS.md` MUST follow:
- First non-empty line: `[LEGEND]`
- Exactly one `[CONTENT]` header (outside code fences)

This file defines the repo's doc [STYLE_RULE].

## Tokens
- Prefer reusing [GLOBAL_TOKEN|LEGEND.md] over repeating meanings.
- Do not shadow global tokens locally ([NO_SHADOWING|LEGEND.md]).
- Only introduce new tokens when they remove real repetition (avoid token spam).

## Contracts
Versioned contracts live in `docs/contracts/*_vN.md` and follow `docs/contracts/CONTRACT_STANDARD.md`.
