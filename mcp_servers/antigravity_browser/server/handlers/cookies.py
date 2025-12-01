"""
Cookie tool handlers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ... import tools as smart_tools
from ..types import ToolResult

if TYPE_CHECKING:
    from ...config import BrowserConfig
    from ...launcher import BrowserLauncher


def handle_browser_set_cookie(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.set_cookie(
        config=config,
        name=args["name"],
        value=args["value"],
        domain=args["domain"],
        path=args.get("path", "/"),
        secure=args.get("secure", False),
        http_only=args.get("httpOnly", False),
        same_site=args.get("sameSite", "Lax"),
        expires=args.get("expires"),
    )
    return ToolResult.json(result)


def handle_browser_set_cookies(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.set_cookies_batch(config, args["cookies"])
    return ToolResult.json(result)


def handle_browser_get_cookies(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.get_all_cookies(
        config,
        urls=args.get("urls"),
        offset=args.get("offset", 0),
        limit=args.get("limit", 20),
        name_filter=args.get("name_filter"),
    )
    return ToolResult.json(result)


def handle_browser_delete_cookie(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.delete_cookie(
        config=config,
        name=args["name"],
        domain=args.get("domain"),
        path=args.get("path"),
        url=args.get("url"),
    )
    return ToolResult.json(result)


COOKIE_HANDLERS: dict[str, tuple] = {
    "browser_set_cookie": (handle_browser_set_cookie, True),
    "browser_set_cookies": (handle_browser_set_cookies, True),
    "browser_get_cookies": (handle_browser_get_cookies, True),
    "browser_delete_cookie": (handle_browser_delete_cookie, True),
}
