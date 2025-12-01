"""
Scroll operations for browser automation.

Provides page scrolling and element scrolling into view.
"""
from __future__ import annotations

import json
from typing import Any

from ...config import BrowserConfig
from ...session import session_manager
from ..base import SmartToolError, get_session


def scroll_page(
    config: BrowserConfig,
    delta_x: float,
    delta_y: float,
    x: float = 100,
    y: float = 100,
) -> dict[str, Any]:
    """Scroll the page by delta amounts using mouse wheel.

    Args:
        config: Browser configuration
        delta_x: Horizontal scroll delta in pixels (positive = right)
        delta_y: Vertical scroll delta in pixels (positive = down)
        x: X coordinate where scroll event occurs (default: 100)
        y: Y coordinate where scroll event occurs (default: 100)

    Returns:
        Dict with deltas, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            session.scroll(delta_x, delta_y, x, y)
            return {
                "deltaX": delta_x,
                "deltaY": delta_y,
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }
        except (OSError, ValueError, KeyError) as e:
            raise SmartToolError(
                tool="scroll_page",
                action="scroll",
                reason=str(e),
                suggestion="Ensure page is scrollable",
            ) from e


def scroll_to_element(config: BrowserConfig, selector: str) -> dict[str, Any]:
    """Scroll element into view using JavaScript.

    Args:
        config: Browser configuration
        selector: CSS selector for element to scroll to

    Returns:
        Dict with selector, element bounds, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            js = f"""
            (() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) throw new Error('Element not found');
                el.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                const rect = el.getBoundingClientRect();
                return {{top: rect.top, left: rect.left, width: rect.width, height: rect.height}};
            }})()
            """
            result = session.eval_js(js)
            return {
                "selector": selector,
                "rect": result,
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }
        except (OSError, ValueError, KeyError) as e:
            raise SmartToolError(
                tool="scroll_to_element",
                action="scroll",
                reason=str(e),
                suggestion="Check selector is correct and element exists",
            ) from e
