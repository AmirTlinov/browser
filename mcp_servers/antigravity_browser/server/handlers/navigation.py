"""
Navigation tool handlers - page navigation and history.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ... import tools as smart_tools
from ..types import ToolResult

if TYPE_CHECKING:
    from ...config import BrowserConfig
    from ...launcher import BrowserLauncher


def handle_browser_navigate(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    result = smart_tools.navigate_to(
        config,
        url=args["url"],
        wait_load=args.get("wait_load", True),
    )
    return ToolResult.json(result)


def handle_browser_back(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    result = smart_tools.go_back(config)
    return ToolResult.json(result)


def handle_browser_forward(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    result = smart_tools.go_forward(config)
    return ToolResult.json(result)


def handle_browser_reload(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    result = smart_tools.reload_page(
        config,
        ignore_cache=args.get("ignore_cache", False),
    )
    return ToolResult.json(result)


NAVIGATION_HANDLERS: dict[str, tuple] = {
    "browser_navigate": (handle_browser_navigate, True),
    "browser_back": (handle_browser_back, True),
    "browser_forward": (handle_browser_forward, True),
    "browser_reload": (handle_browser_reload, True),
}
