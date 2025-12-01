"""
DOM tools for browser automation.

Provides:
- get_dom: Get HTML content from page or element with size limits
- get_element_info: Get detailed element information
- screenshot: Capture page screenshot
"""
from __future__ import annotations

import base64
import json
from typing import Any

from ..config import BrowserConfig
from ..session import session_manager
from .base import SmartToolError, get_session

# Default and max limits for HTML content
DEFAULT_MAX_CHARS = 50000  # 50KB default
MAX_CHARS_LIMIT = 200000  # 200KB max


def get_dom(
    config: BrowserConfig,
    selector: str | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    include_metadata: bool = True,
) -> dict[str, Any]:
    """Get DOM HTML from session's tab with size limiting.

    IMPORTANT: Consider using analyze_page() or extract_content() for
    structured data - they are more context-efficient.

    Args:
        config: Browser configuration
        selector: Optional CSS selector to get HTML of specific element
        max_chars: Maximum HTML characters to return (default: 50000, max: 200000)
        include_metadata: Include HTML size metadata (default: True)

    Returns:
        Dict with:
        - html: HTML content (truncated if exceeds max_chars)
        - truncated: True if HTML was truncated
        - totalChars: Original HTML size before truncation
        - returnedChars: Actual returned size
        - target: Target ID
        - hint: Suggestion if truncated
    """
    max_chars = min(max_chars, MAX_CHARS_LIMIT)

    with get_session(config) as (session, target):
        try:
            html = session.get_dom(selector)
            total_chars = len(html)
            truncated = total_chars > max_chars

            if truncated:
                html = html[:max_chars]

            result: dict[str, Any] = {
                "html": html,
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }

            if include_metadata:
                result["totalChars"] = total_chars
                result["returnedChars"] = len(html)
                result["truncated"] = truncated

            if truncated:
                result["hint"] = (
                    f"HTML truncated ({total_chars} -> {max_chars} chars). "
                    f"Options: 1) Use selector='...' to get specific element, "
                    f"2) Use max_chars={min(total_chars, MAX_CHARS_LIMIT)} for full content, "
                    f"3) Use analyze_page() or extract_content() for structured data."
                )

            return result
        except Exception as e:
            raise SmartToolError(
                tool="get_dom",
                action="get",
                reason=str(e),
                suggestion="Check selector is valid. Consider using analyze_page() instead.",
            ) from e


def get_element_info(config: BrowserConfig, selector: str) -> dict[str, Any]:
    """Get detailed element information by CSS selector.

    Args:
        config: Browser configuration
        selector: CSS selector to find element

    Returns:
        Dict with element info (tag, id, class, text, bounds, attributes), target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            js = f"""
            (() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return {{
                    tagName: el.tagName,
                    id: el.id,
                    className: el.className,
                    text: el.textContent?.slice(0, 200),
                    bounds: {{ x: rect.x, y: rect.y, width: rect.width, height: rect.height }},
                    attributes: Object.fromEntries([...el.attributes].map(a => [a.name, a.value]))
                }};
            }})()
            """
            result = session.eval_js(js)
            if result is None:
                raise SmartToolError(
                    tool="get_element",
                    action="find",
                    reason=f"Element not found: {selector}",
                    suggestion="Check selector is correct",
                )
            return {"element": result, "target": target["id"], "sessionTabId": session_manager.tab_id}
        except SmartToolError:
            raise
        except Exception as e:
            raise SmartToolError(
                tool="get_element",
                action="get",
                reason=str(e),
                suggestion="Check selector syntax",
            ) from e


def screenshot(config: BrowserConfig) -> dict[str, Any]:
    """Take screenshot of session's tab.

    Args:
        config: Browser configuration

    Returns:
        Dict with base64 screenshot, byte size, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            data_b64 = session.capture_screenshot()
            binary = base64.b64decode(data_b64, validate=False)
            return {
                "content_b64": data_b64,
                "bytes": len(binary),
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }
        except Exception as e:
            raise SmartToolError(
                tool="screenshot",
                action="capture",
                reason=str(e),
                suggestion="Ensure page is loaded",
            ) from e
