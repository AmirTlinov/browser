"""Run-internal helpers for high-leverage automation.

This package is intentionally small and deterministic:
- No LLM execution server-side.
- Bounded expansions (no infinite loops).
- Fail-closed when inputs are ambiguous or invalid.

The primary consumer is the `run(...)` / `flow(...)` engine in `server/registry.py`.
"""

from .macros import expand_macro

__all__ = [
    "expand_macro",
]

