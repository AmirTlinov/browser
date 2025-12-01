"""
Tool registry with dispatch table for MCP server.

Replaces the massive if-elif chain with clean O(1) lookup.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .types import ToolResult

if TYPE_CHECKING:
    from ..config import BrowserConfig
    from ..launcher import BrowserLauncher

logger = logging.getLogger("mcp.browser.registry")

# Type alias for handler function
HandlerFunc = Callable[["BrowserConfig", "BrowserLauncher", dict[str, Any]], ToolResult]


class ToolRegistry:
    """Registry for tool handlers with automatic browser lifecycle management."""

    def __init__(self) -> None:
        # name -> (handler, requires_browser)
        self._handlers: dict[str, tuple[HandlerFunc, bool]] = {}

    def register(
        self,
        name: str,
        handler: HandlerFunc,
        requires_browser: bool = True,
    ) -> None:
        """Register a tool handler."""
        self._handlers[name] = (handler, requires_browser)

    def register_many(self, handlers: dict[str, tuple[HandlerFunc, bool]]) -> None:
        """Register multiple handlers at once."""
        self._handlers.update(handlers)

    def get(self, name: str) -> tuple[HandlerFunc, bool] | None:
        """Get handler and its browser requirement."""
        return self._handlers.get(name)

    def has(self, name: str) -> bool:
        """Check if handler exists."""
        return name in self._handlers

    def dispatch(
        self,
        name: str,
        config: BrowserConfig,
        launcher: BrowserLauncher,
        arguments: dict[str, Any],
    ) -> ToolResult:
        """
        Dispatch tool call to appropriate handler.

        Args:
            name: Tool name
            config: Browser configuration
            launcher: Browser launcher instance
            arguments: Tool arguments

        Returns:
            ToolResult from handler

        Raises:
            KeyError: If tool not found
        """
        handler_info = self._handlers.get(name)
        if handler_info is None:
            raise KeyError(f"Unknown tool: {name}")

        handler, requires_browser = handler_info

        # Ensure browser is running if needed
        if requires_browser:
            launcher.ensure_running()

        return handler(config, launcher, arguments)

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._handlers.keys())

    def __len__(self) -> int:
        return len(self._handlers)


def create_default_registry() -> ToolRegistry:
    """Create registry with all default handlers."""
    from .handlers import ALL_HANDLERS

    registry = ToolRegistry()
    registry.register_many(ALL_HANDLERS)
    logger.info("Registered %d tool handlers", len(registry))
    return registry
