"""
DOM tool handlers - screenshots, DOM access, page info.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

from ... import tools as smart_tools
from ..types import ToolContent, ToolResult

if TYPE_CHECKING:
    from ...config import BrowserConfig
    from ...launcher import BrowserLauncher


def handle_screenshot(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    url = args.get("url")
    if url:
        smart_tools.navigate_to(config, url)

    with smart_tools.get_session(config) as (session, target):
        data_b64 = session.capture_screenshot()
        binary = base64.b64decode(data_b64, validate=False)
        shot = {"targetId": target["id"], "content_b64": data_b64, "bytes": len(binary)}

    max_bytes = min(config.http_max_bytes, 900_000)
    approx_limit = int(max_bytes * 1.37)
    data_b64 = shot["content_b64"]
    truncated = len(data_b64) > approx_limit
    if truncated:
        data_b64 = data_b64[:approx_limit]

    return ToolResult(
        content=[
            ToolContent(
                type="text",
                text=f"bytes={shot['bytes']}, truncated={truncated}, target={shot['targetId']}",
            ),
            ToolContent(type="image", data=data_b64, mime_type="image/png"),
        ]
    )


def handle_dump_dom(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    dom = smart_tools.dump_dom_html(
        config,
        url=args["url"],
        max_chars=args.get("max_chars", 50000),
    )
    return ToolResult.json(dom)


def handle_browser_get_dom(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.get_dom(
        config,
        selector=args.get("selector"),
        max_chars=args.get("max_chars", 50000),
        include_metadata=args.get("include_metadata", True),
    )
    return ToolResult.json(result)


def handle_browser_get_element(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.get_element_info(config, args["selector"])
    return ToolResult.json(result)


def handle_browser_get_page_info(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.get_page_info(config)
    return ToolResult.json(result)


DOM_HANDLERS: dict[str, tuple] = {
    "screenshot": (handle_screenshot, True),
    "dump_dom": (handle_dump_dom, True),
    "browser_get_dom": (handle_browser_get_dom, True),
    "browser_get_element": (handle_browser_get_element, True),
    "browser_get_page_info": (handle_browser_get_page_info, True),
}
