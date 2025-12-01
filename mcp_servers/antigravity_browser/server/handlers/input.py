"""
Input tool handlers - mouse, keyboard, scroll, forms.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ... import tools as smart_tools
from ..types import ToolResult

if TYPE_CHECKING:
    from ...config import BrowserConfig
    from ...launcher import BrowserLauncher


# ─────────────────────────────────────────────────────────────────────────────
# Click handlers
# ─────────────────────────────────────────────────────────────────────────────


def handle_browser_click(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.dom_action_click(config, args["selector"])
    return ToolResult.json(result)


def handle_browser_click_pixel(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.click_at_pixel(
        config,
        x=float(args["x"]),
        y=float(args["y"]),
        button=args.get("button", "left"),
    )
    return ToolResult.json(result)


def handle_browser_double_click(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.double_click_at_pixel(
        config,
        x=float(args["x"]),
        y=float(args["y"]),
    )
    return ToolResult.json(result)


# ─────────────────────────────────────────────────────────────────────────────
# Mouse handlers
# ─────────────────────────────────────────────────────────────────────────────


def handle_browser_move_mouse(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.move_mouse_to(
        config,
        x=float(args["x"]),
        y=float(args["y"]),
    )
    return ToolResult.json(result)


def handle_browser_hover(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.hover_element(config, args["selector"])
    return ToolResult.json(result)


def handle_browser_drag(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.drag_from_to(
        config,
        from_x=float(args["from_x"]),
        from_y=float(args["from_y"]),
        to_x=float(args["to_x"]),
        to_y=float(args["to_y"]),
        steps=int(args.get("steps", 10)),
    )
    return ToolResult.json(result)


# ─────────────────────────────────────────────────────────────────────────────
# Keyboard handlers
# ─────────────────────────────────────────────────────────────────────────────


def handle_browser_type(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.dom_action_type(
        config,
        selector=args["selector"],
        text=args["text"],
        clear=args.get("clear", True),
    )
    return ToolResult.json(result)


def handle_browser_press_key(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.press_key(
        config,
        key=args["key"],
        modifiers=int(args.get("modifiers", 0)),
    )
    return ToolResult.json(result)


def handle_browser_type_text(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.type_text(config, args["text"])
    return ToolResult.json(result)


# ─────────────────────────────────────────────────────────────────────────────
# Scroll handlers
# ─────────────────────────────────────────────────────────────────────────────


def handle_browser_scroll(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.scroll_page(
        config,
        delta_x=float(args.get("delta_x", 0)),
        delta_y=float(args["delta_y"]),
    )
    return ToolResult.json(result)


def handle_browser_scroll_down(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    amount = float(args.get("amount", 300))
    result = smart_tools.scroll_page(config, 0, amount)
    return ToolResult.json(result)


def handle_browser_scroll_up(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    amount = float(args.get("amount", 300))
    result = smart_tools.scroll_page(config, 0, -amount)
    return ToolResult.json(result)


def handle_browser_scroll_to_element(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.scroll_to_element(config, args["selector"])
    return ToolResult.json(result)


# ─────────────────────────────────────────────────────────────────────────────
# Form handlers
# ─────────────────────────────────────────────────────────────────────────────


def handle_browser_select_option(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.select_option(
        config,
        selector=args["selector"],
        value=args["value"],
        by=args.get("by", "value"),
    )
    return ToolResult.json(result)


def handle_browser_focus(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.focus_element(config, args["selector"])
    return ToolResult.json(result)


def handle_browser_clear_input(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.clear_input(config, args["selector"])
    return ToolResult.json(result)


# ─────────────────────────────────────────────────────────────────────────────
# Window handlers
# ─────────────────────────────────────────────────────────────────────────────


def handle_browser_resize_viewport(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.resize_viewport(
        config,
        width=int(args["width"]),
        height=int(args["height"]),
    )
    return ToolResult.json(result)


def handle_browser_resize_window(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.resize_window(
        config,
        width=int(args["width"]),
        height=int(args["height"]),
    )
    return ToolResult.json(result)


def handle_browser_wait_for_element(
    config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]
) -> ToolResult:
    result = smart_tools.wait_for_element(
        config,
        selector=args["selector"],
        timeout=float(args.get("timeout", 10.0)),
    )
    return ToolResult.json(result)


INPUT_HANDLERS: dict[str, tuple] = {
    # Click
    "browser_click": (handle_browser_click, True),
    "browser_click_pixel": (handle_browser_click_pixel, True),
    "browser_double_click": (handle_browser_double_click, True),
    # Mouse
    "browser_move_mouse": (handle_browser_move_mouse, True),
    "browser_hover": (handle_browser_hover, True),
    "browser_drag": (handle_browser_drag, True),
    # Keyboard
    "browser_type": (handle_browser_type, True),
    "browser_press_key": (handle_browser_press_key, True),
    "browser_type_text": (handle_browser_type_text, True),
    # Scroll
    "browser_scroll": (handle_browser_scroll, True),
    "browser_scroll_down": (handle_browser_scroll_down, True),
    "browser_scroll_up": (handle_browser_scroll_up, True),
    "browser_scroll_to_element": (handle_browser_scroll_to_element, True),
    # Form
    "browser_select_option": (handle_browser_select_option, True),
    "browser_focus": (handle_browser_focus, True),
    "browser_clear_input": (handle_browser_clear_input, True),
    # Window
    "browser_resize_viewport": (handle_browser_resize_viewport, True),
    "browser_resize_window": (handle_browser_resize_window, True),
    "browser_wait_for_element": (handle_browser_wait_for_element, True),
}
