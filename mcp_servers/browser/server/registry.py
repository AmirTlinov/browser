"""Tool registry wiring for the MCP server.

`server/registry.py` is intentionally wiring-only: it composes handlers into a
`ToolRegistry` and must stay small.
"""

from __future__ import annotations

from .dispatch import ToolRegistry, logger
from .flow import make_flow_handler
from .handlers.unified import UNIFIED_HANDLERS
from .run import make_run_handler
from .runbook import make_runbook_handler


def create_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_many(UNIFIED_HANDLERS)

    flow_handler = make_flow_handler(registry)
    registry.register("flow", flow_handler, True)

    run_handler = make_run_handler(flow_handler)
    registry.register("run", run_handler, True)

    runbook_handler = make_runbook_handler(registry)
    registry.register("runbook", runbook_handler, False)

    logger.info("Registered %d tool handlers", len(registry))
    return registry
