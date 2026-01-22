[LEGEND]

[CONTENT]
Contract: Documentation format v1

## Purpose
Define [DOC_FORMAT|LEGEND.md]: a deterministic documentation shape that humans and agents can parse without guesswork.

## Scope
- In scope: required blocks, token rules, and what the gate validates.
- Out of scope: repository-specific vocabulary (that lives in `LEGEND.md`).

## Interface
Rules:
- Every Markdown doc (except repo-root `AGENTS.md` and repo-root `README.md`) MUST follow [DOC_FORMAT|LEGEND.md].
- The first non-empty line MUST be `[LEGEND]`.
- A document MUST include exactly one content header: `[CONTENT]`.

Token rules:
- Definitions live in `[LEGEND]` as `TOKEN = Meaning`.
- References in content are written as `[TOKEN]` (optionally `[TOKEN|LEGEND.md]`).
- Local tokens must not redefine global tokens ([NO_SHADOWING|LEGEND.md]).

Contract rules:
- Versioned contracts in `docs/contracts/*_vN.md` must follow `CONTRACT_STANDARD.md`.

## Errors
If a doc violates [DOC_FORMAT|LEGEND.md] or token rules, the gate fails closed.

## Examples
```md
[LEGEND]
TERM = A locally-defined term for this document.

[CONTENT]
This uses [TERM] without repeating the meaning.
```

