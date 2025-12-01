"""
CAPTCHA tool handlers.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from ... import tools as smart_tools
from ..types import ToolContent, ToolResult

if TYPE_CHECKING:
    from ...config import BrowserConfig
    from ...launcher import BrowserLauncher


def handle_analyze_captcha(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    result = smart_tools.analyze_captcha(
        config,
        force_grid_size=args.get("force_grid_size", 0),
    )
    return ToolResult.json(result)


def handle_get_captcha_screenshot(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    result = smart_tools.get_captcha_screenshot(
        config,
        grid_size=args.get("grid_size", 0),
    )

    if not result.get("screenshot"):
        return ToolResult.json(result)

    # Return image with metadata
    metadata = {k: v for k, v in result.items() if k != "screenshot"}
    return ToolResult(
        content=[
            ToolContent(type="image", data=result["screenshot"], mime_type="image/png"),
            ToolContent(type="text", text=json.dumps(metadata, ensure_ascii=False)),
        ]
    )


def handle_click_captcha_blocks(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    result = smart_tools.click_captcha_blocks(
        config,
        blocks=args["blocks"],
        grid_size=args.get("grid_size", 0),
    )
    return ToolResult.json(result)


def handle_click_captcha_area(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    result = smart_tools.click_captcha_area(
        config,
        area_id=args["area_id"],
    )
    return ToolResult.json(result)


def handle_submit_captcha(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    result = smart_tools.submit_captcha(config)
    return ToolResult.json(result)


CAPTCHA_HANDLERS: dict[str, tuple] = {
    "analyze_captcha": (handle_analyze_captcha, True),
    "get_captcha_screenshot": (handle_get_captcha_screenshot, True),
    "click_captcha_blocks": (handle_click_captcha_blocks, True),
    "click_captcha_area": (handle_click_captcha_area, True),
    "submit_captcha": (handle_submit_captcha, True),
}
