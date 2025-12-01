"""
DOM tools for browser automation.

Provides:
- get_dom: Get HTML content from page or element
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


def get_dom(config: BrowserConfig, selector: str | None = None) -> dict[str, Any]:
    """Get DOM HTML from session's tab.

    Args:
        config: Browser configuration
        selector: Optional CSS selector to get HTML of specific element

    Returns:
        Dict with html content, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            html = session.get_dom(selector)
            return {"html": html, "target": target["id"], "sessionTabId": session_manager.tab_id}
        except Exception as e:
            raise SmartToolError(
                tool="get_dom",
                action="get",
                reason=str(e),
                suggestion="Check selector is valid",
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
