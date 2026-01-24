"""Server package for MCP browser automation.

Keep this package import light: importing `mcp_servers.browser.server.*` should not
eagerly pull the whole tool registry (avoids circular imports with session/tools).
"""

from __future__ import annotations

from typing import Any

__all__ = ["ToolRegistry", "create_default_registry"]


def __getattr__(name: str) -> Any:  # pragma: no cover
    if name in {"ToolRegistry", "create_default_registry"}:
        from .registry import ToolRegistry, create_default_registry

        return {"ToolRegistry": ToolRegistry, "create_default_registry": create_default_registry}[name]
    raise AttributeError(name)
