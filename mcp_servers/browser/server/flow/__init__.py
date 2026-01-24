"""Flow tool (multi-step execution engine).

This package owns the high-leverage batching/automation entrypoint (`flow`) and
its internal actions (assert/when/repeat/macro). It is intentionally separated
from `server/registry.py` so registry stays wiring-only.
"""

from __future__ import annotations

from .handler import make_flow_handler

__all__ = ["make_flow_handler"]

