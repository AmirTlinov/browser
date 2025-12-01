"""
Tab management tool handlers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ... import tools as smart_tools
from ..types import ToolResult

if TYPE_CHECKING:
    from ...config import BrowserConfig
    from ...launcher import BrowserLauncher


def handle_list_tabs(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.list_tabs(
        config,
        offset=args.get("offset", 0),
        limit=args.get("limit", 20),
        url_filter=args.get("url_filter"),
    )
    return ToolResult.json(result)


def handle_switch_tab(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.switch_tab(
        config,
        tab_id=args.get("tab_id"),
        url_pattern=args.get("url_pattern"),
    )
    return ToolResult.json(result)


def handle_new_tab(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.new_tab(
        config,
        url=args.get("url", "about:blank"),
    )
    return ToolResult.json(result)


def handle_close_tab(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.close_tab(
        config,
        tab_id=args.get("tab_id"),
    )
    return ToolResult.json(result)


TAB_HANDLERS: dict[str, tuple] = {
    "list_tabs": (handle_list_tabs, True),
    "switch_tab": (handle_switch_tab, True),
    "new_tab": (handle_new_tab, True),
    "close_tab": (handle_close_tab, True),
}
