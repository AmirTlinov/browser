"""
Network tool handlers - HTTP fetch, JS eval, basic operations.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from ... import tools as smart_tools
from ...http_client import http_get
from ..types import ToolContent, ToolResult

if TYPE_CHECKING:
    from ...config import BrowserConfig
    from ...launcher import BrowserLauncher


def handle_http_get(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    url = args["url"]
    resp = http_get(url, config)
    return ToolResult(
        content=[
            ToolContent(
                type="text",
                text=f"status={resp['status']}, truncated={resp['truncated']}, headers={resp['headers']}",
            ),
            ToolContent(type="text", text=resp["body"]),
        ]
    )


def handle_browser_fetch(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    resp = smart_tools.browser_fetch(
        config,
        url=args["url"],
        method=args.get("method", "GET"),
        headers=args.get("headers"),
        body=args.get("body"),
        credentials=args.get("credentials", "include"),
    )
    return ToolResult(
        content=[
            ToolContent(
                type="text",
                text=f"ok=True, status={resp.get('status')}, statusText={resp.get('statusText', '')}",
            ),
            ToolContent(type="text", text=resp.get("body", "")),
        ]
    )


def handle_js_eval(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.eval_js(config, args["expression"])
    return ToolResult.json(result)


def handle_launch_browser(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = launcher.ensure_running()
    status = "started" if result.started else "skipped"
    return ToolResult.text(f"{status}: {result.message}")


def handle_cdp_version(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    should_start = args.get("start", True)
    launch_result = launcher.ensure_running() if should_start else None
    version = launcher.cdp_version()
    prefix = "launched" if launch_result and launch_result.started else "ready"
    return ToolResult(
        content=[
            ToolContent(
                type="text",
                text=f"{prefix}: {launch_result.message if launch_result else 'CDP checked'}",
            ),
            ToolContent(type="text", text=json.dumps(version, ensure_ascii=False)),
        ]
    )


NETWORK_HANDLERS: dict[str, tuple] = {
    "http_get": (handle_http_get, False),
    "browser_fetch": (handle_browser_fetch, True),
    "js_eval": (handle_js_eval, True),
    "launch_browser": (handle_launch_browser, False),  # Handles its own launching
    "cdp_version": (handle_cdp_version, False),  # Handles its own launching
}
