"""
Tool registry with dispatch table for MCP server.

Replaces the massive if-elif chain with clean O(1) lookup.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from .types import ToolResult

if TYPE_CHECKING:
    from ..config import BrowserConfig
    from ..launcher import BrowserLauncher

logger = logging.getLogger("mcp.browser.registry")

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
        """Dispatch tool call to appropriate handler."""
        handler_info = self._handlers.get(name)
        if handler_info is None:
            raise KeyError(f"Unknown tool: {name}")

        handler, requires_browser = handler_info

        if requires_browser:
            launch_res = launcher.ensure_running()

            mode = getattr(config, "mode", "launch")
            if mode == "extension":
                try:
                    from ..session import session_manager as _session_manager

                    gw = _session_manager.get_extension_gateway()
                    if gw is None:
                        return ToolResult.error(
                            "Extension gateway is not configured (mode=extension)",
                            tool=name,
                            suggestion="Start the server with MCP_BROWSER_MODE=extension and ensure the gateway starts successfully",
                        )
                    if not gw.is_connected():
                        try:
                            connect_timeout = float(os.environ.get("MCP_EXTENSION_CONNECT_TIMEOUT") or 4.0)
                        except Exception:
                            connect_timeout = 4.0
                        connect_timeout = max(0.0, min(connect_timeout, 15.0))
                        if connect_timeout > 0:
                            with suppress(Exception):
                                gw.wait_for_connection(timeout=connect_timeout)
                    if not gw.is_connected():
                        return ToolResult.error(
                            "Extension is not connected (mode=extension)",
                            tool=name,
                            suggestion='Ensure the Browser MCP extension is installed/enabled, then retry (check via browser(action="status"))',
                            details={"gateway": gw.status()},
                        )
                except Exception:
                    # If we can't validate readiness, let the tool attempt and surface its own error.
                    pass
            else:
                try:
                    if not launcher.cdp_ready(timeout=0.6):
                        return ToolResult.error(
                            "CDP endpoint not reachable (port may be in use or Chrome is hung)",
                            tool=name,
                            suggestion='Try browser(action="recover") (hard restart if owned) or change MCP_BROWSER_PORT',
                            details={"cdpPort": config.cdp_port, "message": getattr(launch_res, "message", None)},
                        )
                except Exception:
                    pass

        return handler(config, launcher, arguments)

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._handlers.keys())

    def __len__(self) -> int:
        return len(self._handlers)


__all__ = ["HandlerFunc", "ToolRegistry", "logger"]

