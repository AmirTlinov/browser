[LEGEND]
QUALITY_SNAPSHOT = A short evidence-backed view of quality and drift.
DRIFT = A mismatch between what docs/scripts claim and what code actually does.
NEXT_ACTION = The smallest change that removes the biggest risk.

[CONTENT]
# Code Review Notes (living)

This doc is a [QUALITY_SNAPSHOT].

## What’s good (structurally)
- Server surface is unified (single registry + unified handlers).
- Contract snapshot exists and is test-checked.
- Core logic is decomposed into focused modules (config / launcher / session / tools).

## What to watch (highest leverage)
- [DRIFT] in docs and scripts is the fastest way to break user trust.
- Safety boundaries (allowlist + redirects + dumps) must stay boring and correct.

## [NEXT_ACTION]
If you’re changing behavior or contracts:
1) Update contracts first ([CHANGE_PROTOCOL|LEGEND.md]).
2) Run `./tools/gate` before merging.

