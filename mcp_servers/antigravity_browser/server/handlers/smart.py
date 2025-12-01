"""
Smart tool handlers - high-level AI-friendly operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ... import tools as smart_tools
from ..types import ToolResult

if TYPE_CHECKING:
    from ...config import BrowserConfig
    from ...launcher import BrowserLauncher


def handle_analyze_page(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.analyze_page(
        config,
        detail=args.get("detail"),
        offset=args.get("offset", 0),
        limit=args.get("limit", 10),
        form_index=args.get("form_index"),
        include_content=args.get("include_content", False),
    )
    return ToolResult.json(result)


def handle_click_element(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.click_element(
        config,
        text=args.get("text"),
        role=args.get("role"),
        near_text=args.get("near_text"),
        index=args.get("index", 0),
    )
    return ToolResult.json(result)


def handle_fill_form(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.fill_form(
        config,
        data=args.get("data", {}),
        form_index=args.get("form_index", 0),
        submit=args.get("submit", False),
    )
    return ToolResult.json(result)


def handle_search_page(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.search_page(
        config,
        query=args["query"],
        submit=args.get("submit", True),
    )
    return ToolResult.json(result)


def handle_extract_content(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.extract_content(
        config,
        content_type=args.get("content_type", "overview"),
        selector=args.get("selector"),
        offset=args.get("offset", 0),
        limit=args.get("limit", 10),
        table_index=args.get("table_index"),
    )
    return ToolResult.json(result)


def handle_wait_for(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.wait_for(
        config,
        condition=args["condition"],
        timeout=args.get("timeout", 10.0),
        text=args.get("text"),
        selector=args.get("selector"),
    )
    return ToolResult.json(result)


def handle_execute_workflow(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    import json

    include_screenshots = args.get("include_screenshots", False)
    result = smart_tools.execute_workflow(
        config,
        steps=args.get("steps", []),
        include_screenshots=include_screenshots,
        compact_results=args.get("compact_results", True),
    )

    if not include_screenshots:
        return ToolResult.json(result)

    # Handle screenshots in workflow
    from ..types import ToolContent

    content_list = [ToolContent(type="text", text=json.dumps(result, ensure_ascii=False))]
    for step_result in result.get("executed", []):
        if step_result.get("screenshot_b64"):
            content_list.append(
                ToolContent(
                    type="image",
                    data=step_result.pop("screenshot_b64"),
                    mime_type="image/png",
                )
            )
    return ToolResult(content=content_list)


def handle_upload_file(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.upload_file(
        config,
        file_paths=args.get("file_paths", []),
        selector=args.get("selector"),
    )
    return ToolResult.json(result)


def handle_dialog(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.handle_dialog(
        config,
        accept=args.get("accept", True),
        prompt_text=args.get("prompt_text"),
    )
    return ToolResult.json(result)


def handle_generate_totp(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.generate_totp(
        secret=args["secret"],
        digits=args.get("digits", 6),
        interval=args.get("interval", 30),
    )
    return ToolResult.json(result)


# Handler registry: name -> (handler, requires_browser)
SMART_HANDLERS: dict[str, tuple] = {
    "analyze_page": (handle_analyze_page, True),
    "click_element": (handle_click_element, True),
    "fill_form": (handle_fill_form, True),
    "search_page": (handle_search_page, True),
    "extract_content": (handle_extract_content, True),
    "wait_for": (handle_wait_for, True),
    "execute_workflow": (handle_execute_workflow, True),
    "upload_file": (handle_upload_file, True),
    "handle_dialog": (handle_dialog, True),
    "generate_totp": (handle_generate_totp, False),  # No browser needed
}
