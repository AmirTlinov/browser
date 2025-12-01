"""
Mouse input operations for browser automation.

Provides click, double-click, move, hover, and drag operations.
"""
from __future__ import annotations

import json
from typing import Any

from ...config import BrowserConfig
from ...session import session_manager
from ..base import SmartToolError, get_session


def click_at_pixel(config: BrowserConfig, x: float, y: float, button: str = "left") -> dict[str, Any]:
    """Click at specific pixel coordinates.

    Args:
        config: Browser configuration
        x: X coordinate in pixels
        y: Y coordinate in pixels
        button: Mouse button ("left", "right", "middle")

    Returns:
        Dict with coordinates, button, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            session.click(x, y, button)
            return {
                "x": x,
                "y": y,
                "button": button,
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }
        except (OSError, ValueError, KeyError) as e:
            raise SmartToolError(
                tool="click_at_pixel",
                action="click",
                reason=str(e),
                suggestion="Ensure coordinates are within viewport bounds",
            ) from e


def double_click_at_pixel(config: BrowserConfig, x: float, y: float) -> dict[str, Any]:
    """Double-click at specific pixel coordinates.

    Args:
        config: Browser configuration
        x: X coordinate in pixels
        y: Y coordinate in pixels

    Returns:
        Dict with coordinates, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            session.double_click(x, y)
            return {
                "x": x,
                "y": y,
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }
        except (OSError, ValueError, KeyError) as e:
            raise SmartToolError(
                tool="double_click_at_pixel",
                action="double_click",
                reason=str(e),
                suggestion="Ensure coordinates are within viewport bounds",
            ) from e


def move_mouse_to(config: BrowserConfig, x: float, y: float) -> dict[str, Any]:
    """Move mouse to specific coordinates.

    Args:
        config: Browser configuration
        x: X coordinate in pixels
        y: Y coordinate in pixels

    Returns:
        Dict with coordinates, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            session.move_mouse(x, y)
            return {
                "x": x,
                "y": y,
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }
        except (OSError, ValueError, KeyError) as e:
            raise SmartToolError(
                tool="move_mouse_to",
                action="move",
                reason=str(e),
                suggestion="Ensure coordinates are within viewport bounds",
            ) from e


def hover_element(config: BrowserConfig, selector: str) -> dict[str, Any]:
    """Hover over an element by moving mouse to its center.

    Args:
        config: Browser configuration
        selector: CSS selector for element to hover

    Returns:
        Dict with selector, calculated coordinates, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            js = f"""
            (() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) throw new Error('Element not found');
                const rect = el.getBoundingClientRect();
                return {{x: rect.x + rect.width/2, y: rect.y + rect.height/2}};
            }})()
            """
            pos = session.eval_js(js)
            if not pos:
                raise SmartToolError(
                    tool="hover_element",
                    action="find",
                    reason=f"Element not found: {selector}",
                    suggestion="Check selector is correct and element is in DOM",
                )
            session.move_mouse(pos["x"], pos["y"])
            return {
                "selector": selector,
                "x": pos["x"],
                "y": pos["y"],
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }
        except SmartToolError:
            raise
        except (OSError, ValueError, KeyError) as e:
            raise SmartToolError(
                tool="hover_element",
                action="hover",
                reason=str(e),
                suggestion="Check element exists and is visible",
            ) from e


def drag_from_to(
    config: BrowserConfig,
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
    steps: int = 10,
) -> dict[str, Any]:
    """Drag from one point to another with smooth movement.

    Args:
        config: Browser configuration
        from_x: Starting X coordinate
        from_y: Starting Y coordinate
        to_x: Ending X coordinate
        to_y: Ending Y coordinate
        steps: Number of intermediate steps for smooth movement (default: 10)

    Returns:
        Dict with from/to coordinates, steps, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            session.drag(from_x, from_y, to_x, to_y, steps)
            return {
                "from": {"x": from_x, "y": from_y},
                "to": {"x": to_x, "y": to_y},
                "steps": steps,
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }
        except (OSError, ValueError, KeyError) as e:
            raise SmartToolError(
                tool="drag_from_to",
                action="drag",
                reason=str(e),
                suggestion="Ensure coordinates are within viewport bounds",
            ) from e
