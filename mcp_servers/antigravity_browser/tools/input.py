"""
Mouse and keyboard input tools for browser automation.

Provides:
- Mouse operations: click, double-click, move, hover, drag
- Keyboard operations: press key, type text
- DOM actions: click element, type into element
- Scroll operations: scroll page, scroll to element
"""
from __future__ import annotations

import json
from typing import Any

from ..config import BrowserConfig
from ..session import session_manager
from .base import SmartToolError, get_session

# ─────────────────────────────────────────────────────────────────────────────
# Mouse operations
# ─────────────────────────────────────────────────────────────────────────────


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
        except Exception as e:
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
        except Exception as e:
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
        except Exception as e:
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
        except Exception as e:
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
        except Exception as e:
            raise SmartToolError(
                tool="drag_from_to",
                action="drag",
                reason=str(e),
                suggestion="Ensure coordinates are within viewport bounds",
            ) from e


# ─────────────────────────────────────────────────────────────────────────────
# Keyboard operations
# ─────────────────────────────────────────────────────────────────────────────


def press_key(config: BrowserConfig, key: str, modifiers: int = 0) -> dict[str, Any]:
    """Press a keyboard key with optional modifiers.

    Args:
        config: Browser configuration
        key: Key to press (e.g., "Enter", "Tab", "a", "A")
        modifiers: Modifier bitmask (1=Alt, 2=Ctrl, 4=Meta, 8=Shift)

    Returns:
        Dict with key, modifiers, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            session.press_key(key, modifiers)
            return {
                "key": key,
                "modifiers": modifiers,
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }
        except Exception as e:
            raise SmartToolError(
                tool="press_key",
                action="press",
                reason=str(e),
                suggestion="Ensure key name is valid (e.g., 'Enter', 'Tab', 'Escape')",
            ) from e


def type_text(config: BrowserConfig, text: str) -> dict[str, Any]:
    """Type text using keyboard events for currently focused element.

    Args:
        config: Browser configuration
        text: Text to type

    Returns:
        Dict with text, length, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            session.type_text(text)
            return {
                "text": text,
                "length": len(text),
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }
        except Exception as e:
            raise SmartToolError(
                tool="type_text",
                action="type",
                reason=str(e),
                suggestion="Ensure an input element is focused before typing",
            ) from e


# ─────────────────────────────────────────────────────────────────────────────
# DOM actions
# ─────────────────────────────────────────────────────────────────────────────


def dom_action_click(config: BrowserConfig, selector: str) -> dict[str, Any]:
    """Click an element via JavaScript (programmatic click).

    Args:
        config: Browser configuration
        selector: CSS selector for element to click

    Returns:
        Dict with selector, element tag, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            js = f"""
            (() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) throw new Error('Element not found: ' + {json.dumps(selector)});
                el.click();
                return {{clicked: true, tagName: el.tagName}};
            }})()
            """
            result = session.eval_js(js)
            return {
                "command": "click",
                "selector": selector,
                "result": result,
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }
        except Exception as e:
            raise SmartToolError(
                tool="dom_action_click",
                action="click",
                reason=str(e),
                suggestion="Check selector is correct and element is clickable",
            ) from e


def dom_action_type(config: BrowserConfig, selector: str, text: str, clear: bool = True) -> dict[str, Any]:
    """Type into an input element via JavaScript.

    Args:
        config: Browser configuration
        selector: CSS selector for input element
        text: Text to type
        clear: Whether to clear existing value first (default: True)

    Returns:
        Dict with selector, text, final value, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            clear_js = "el.value = '';" if clear else ""
            js = f"""
            (() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) throw new Error('Element not found: ' + {json.dumps(selector)});
                el.focus();
                {clear_js}
                el.value += {json.dumps(text)};
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                return {{typed: true, value: el.value}};
            }})()
            """
            result = session.eval_js(js)
            return {
                "command": "type",
                "selector": selector,
                "text": text,
                "result": result,
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }
        except Exception as e:
            raise SmartToolError(
                tool="dom_action_type",
                action="type",
                reason=str(e),
                suggestion="Check selector is correct and element is an input/textarea",
            ) from e


# ─────────────────────────────────────────────────────────────────────────────
# Scroll operations
# ─────────────────────────────────────────────────────────────────────────────


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
        except Exception as e:
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
        except Exception as e:
            raise SmartToolError(
                tool="scroll_to_element",
                action="scroll",
                reason=str(e),
                suggestion="Check selector is correct and element exists",
            ) from e
