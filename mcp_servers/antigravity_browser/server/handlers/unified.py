"""
Unified tool handlers.

Maps new unified tools to existing implementations.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from ... import tools
from ..types import ToolResult

if TYPE_CHECKING:
    from ...config import BrowserConfig
    from ...launcher import BrowserLauncher


# ═══════════════════════════════════════════════════════════════════════════════
# NAVIGATE
# ═══════════════════════════════════════════════════════════════════════════════


def handle_navigate(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Unified navigation: URL or action (back/forward/reload)."""
    wait_type = args.get("wait", "load")

    if "url" in args:
        result = tools.navigate_to(config, args["url"])
    elif "action" in args:
        action = args["action"]
        if action == "back":
            result = tools.go_back(config)
        elif action == "forward":
            result = tools.go_forward(config)
        elif action == "reload":
            result = tools.reload_page(config)
        else:
            return ToolResult.error(f"Unknown action: {action}")
    else:
        return ToolResult.error("Either 'url' or 'action' is required")

    # Auto-wait
    if wait_type != "none":
        _wait_for_condition(config, wait_type)

    result["waited"] = wait_type
    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# SCROLL
# ═══════════════════════════════════════════════════════════════════════════════


def handle_scroll(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Unified scroll: direction, to element, or to top/bottom."""
    if args.get("to"):
        result = tools.scroll_to_element(config, args["to"])
    elif args.get("to_top"):
        result = tools.scroll_page(config, 0, -99999)
        result["atTop"] = True
    elif args.get("to_bottom"):
        result = tools.scroll_page(config, 0, 99999)
        result["atBottom"] = True
    elif args.get("direction"):
        direction = args["direction"]
        amount = args.get("amount", 300)

        delta_x, delta_y = 0, 0
        if direction == "down":
            delta_y = amount
        elif direction == "up":
            delta_y = -amount
        elif direction == "right":
            delta_x = amount
        elif direction == "left":
            delta_x = -amount

        result = tools.scroll_page(config, delta_x, delta_y)
    else:
        # Default: scroll down
        result = tools.scroll_page(config, 0, 300)

    # Add scroll position info
    page_info = tools.get_page_info(config)
    result["scrollX"] = page_info.get("pageInfo", {}).get("scrollX", 0)
    result["scrollY"] = page_info.get("pageInfo", {}).get("scrollY", 0)

    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# CLICK
# ═══════════════════════════════════════════════════════════════════════════════


def handle_click(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Unified click: text, selector, or coordinates."""
    wait_after = args.get("wait_after", "auto")
    double = args.get("double", False)
    button = args.get("button", "left")

    result: dict[str, Any] = {"success": False}

    # By text (preferred - uses smart click_element)
    if args.get("text"):
        click_result = tools.click_element(
            config,
            text=args["text"],
            role=args.get("role"),
            near_text=args.get("near"),
            index=args.get("index", 0),
        )
        result = click_result
        result["method"] = "text"

    # By selector
    elif args.get("selector"):
        if double:
            # Get element position and double click
            elem = tools.get_element_info(config, args["selector"])
            if elem.get("element"):
                bounds = elem["element"].get("bounds", {})
                x = bounds.get("x", 0) + bounds.get("width", 0) / 2
                y = bounds.get("y", 0) + bounds.get("height", 0) / 2
                result = tools.double_click_at_pixel(config, x, y)
            else:
                return ToolResult.error(f"Element not found: {args['selector']}")
        else:
            result = tools.dom_action_click(config, args["selector"])
        result["method"] = "selector"

    # By coordinates
    elif "x" in args and "y" in args:
        x, y = float(args["x"]), float(args["y"])
        if double:
            result = tools.double_click_at_pixel(config, x, y)
        else:
            result = tools.click_at_pixel(config, x, y, button=button)
        result["method"] = "coordinates"
        result["clicked"] = {"x": x, "y": y}

    else:
        return ToolResult.error("Specify 'text', 'selector', or 'x'+'y' coordinates")

    # Auto-wait after click
    if wait_after == "auto":
        # Check if we clicked a link
        clicked_info = result.get("result", {})
        if clicked_info.get("href") or clicked_info.get("tagName") == "A":
            _wait_for_condition(config, "load", timeout=5)
            result["page_changed"] = True
        else:
            time.sleep(0.1)  # Brief stabilization
            result["page_changed"] = False
    elif wait_after == "navigation":
        _wait_for_condition(config, "load", timeout=10)
        result["page_changed"] = True

    result["success"] = True
    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TYPE
# ═══════════════════════════════════════════════════════════════════════════════


def handle_type(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Unified type: into element, into focused, or press key."""
    result: dict[str, Any] = {"success": False}

    # Build modifiers bitmask
    modifiers = 0
    if args.get("alt"):
        modifiers |= 1
    if args.get("ctrl"):
        modifiers |= 2
    if args.get("meta"):
        modifiers |= 4
    if args.get("shift"):
        modifiers |= 8

    # Press single key
    if args.get("key"):
        result = tools.press_key(config, args["key"], modifiers=modifiers)
        result["action"] = "key_press"

    # Type into specific element
    elif args.get("selector") and args.get("text"):
        result = tools.dom_action_type(
            config,
            selector=args["selector"],
            text=args["text"],
            clear=args.get("clear", False),
        )
        result["action"] = "type_into_element"

        if args.get("submit"):
            tools.press_key(config, "Enter")
            result["submitted"] = True

    # Type into focused element
    elif args.get("text"):
        result = tools.type_text(config, args["text"])
        result["action"] = "type_into_focused"

        if args.get("submit"):
            tools.press_key(config, "Enter")
            result["submitted"] = True

    else:
        return ToolResult.error("Specify 'text' or 'key'")

    result["success"] = True
    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# MOUSE
# ═══════════════════════════════════════════════════════════════════════════════


def handle_mouse(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Low-level mouse: move, hover, drag."""
    action = args.get("action")

    if action == "move":
        if "x" not in args or "y" not in args:
            return ToolResult.error("'x' and 'y' required for move")
        result = tools.move_mouse_to(config, float(args["x"]), float(args["y"]))

    elif action == "hover":
        if "selector" not in args:
            return ToolResult.error("'selector' required for hover")
        result = tools.hover_element(config, args["selector"])

    elif action == "drag":
        required = ["from_x", "from_y", "to_x", "to_y"]
        if not all(k in args for k in required):
            return ToolResult.error(f"Required for drag: {required}")
        result = tools.drag_from_to(
            config,
            float(args["from_x"]),
            float(args["from_y"]),
            float(args["to_x"]),
            float(args["to_y"]),
            steps=args.get("steps", 10),
        )

    else:
        return ToolResult.error("'action' required: move, hover, or drag")

    result["action"] = action
    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# RESIZE
# ═══════════════════════════════════════════════════════════════════════════════


def handle_resize(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Resize viewport or window."""
    width = int(args["width"])
    height = int(args["height"])
    target = args.get("target", "viewport")

    if target == "viewport":
        result = tools.resize_viewport(config, width, height)
    else:
        result = tools.resize_window(config, width, height)

    result["target"] = target
    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# FORM
# ═══════════════════════════════════════════════════════════════════════════════


def handle_form(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Form operations: fill, select, focus, clear, wait."""
    result: dict[str, Any] = {}

    if args.get("fill"):
        fill_result = tools.fill_form(
            config,
            data=args["fill"],
            submit=args.get("submit", False),
            form_index=args.get("form_index", 0),
        )
        result = fill_result
        result["action"] = "fill"

    elif args.get("select"):
        sel = args["select"]
        select_result = tools.select_option(
            config,
            selector=sel["selector"],
            value=sel["value"],
            by=sel.get("by", "value"),
        )
        result = select_result
        result["action"] = "select"

    elif args.get("focus"):
        result = tools.focus_element(config, args["focus"])
        result["action"] = "focus"

    elif args.get("clear"):
        result = tools.clear_input(config, args["clear"])
        result["action"] = "clear"

    elif args.get("wait_for"):
        result = tools.wait_for_element(
            config,
            selector=args["wait_for"],
            timeout=args.get("timeout", 10),
        )
        result["action"] = "wait"

    else:
        return ToolResult.error("Specify 'fill', 'select', 'focus', 'clear', or 'wait_for'")

    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════════════════════════


def handle_tabs(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Tab management: list, switch, new, close."""
    action = args.get("action", "list")

    if action == "list":
        result = tools.list_tabs(config, url_filter=args.get("url_contains"))
        result["action"] = "list"

    elif action == "switch":
        if args.get("tab_id"):
            result = tools.switch_tab(config, tab_id=args["tab_id"])
        elif args.get("url_contains"):
            result = tools.switch_tab(config, url_pattern=args["url_contains"])
        else:
            return ToolResult.error("'tab_id' or 'url_contains' required for switch")
        result["action"] = "switch"

    elif action == "new":
        result = tools.new_tab(config, url=args.get("url", "about:blank"))
        result["action"] = "new"

    elif action == "close":
        result = tools.close_tab(config, tab_id=args.get("tab_id"))
        result["action"] = "close"

    else:
        return ToolResult.error(f"Unknown action: {action}")

    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# COOKIES
# ═══════════════════════════════════════════════════════════════════════════════


def handle_cookies(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Cookie management: get, set, delete."""
    action = args.get("action", "get")

    if action == "get":
        result = tools.get_all_cookies(
            config,
            name_filter=args.get("name_filter"),
        )
        result["action"] = "get"

    elif action == "set":
        if args.get("cookies"):
            result = tools.set_cookies_batch(config, args["cookies"])
        elif args.get("name") and args.get("value") and args.get("domain"):
            result = tools.set_cookie(
                config,
                name=args["name"],
                value=args["value"],
                domain=args["domain"],
                path=args.get("path", "/"),
                secure=args.get("secure", False),
                http_only=args.get("httpOnly", False),
                expires=args.get("expires"),
                same_site=args.get("sameSite", "Lax"),
            )
        else:
            return ToolResult.error("For set: need 'name', 'value', 'domain' or 'cookies' array")
        result["action"] = "set"

    elif action == "delete":
        if not args.get("name"):
            return ToolResult.error("'name' required for delete")
        result = tools.delete_cookie(
            config,
            name=args["name"],
            domain=args.get("domain"),
            path=args.get("path"),
        )
        result["action"] = "delete"

    else:
        return ToolResult.error(f"Unknown action: {action}")

    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# CAPTCHA
# ═══════════════════════════════════════════════════════════════════════════════


def handle_captcha(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """CAPTCHA detection and interaction."""
    action = args.get("action", "analyze")

    if action == "analyze":
        result = tools.analyze_captcha(config, force_grid_size=args.get("grid_size", 0))

    elif action == "screenshot":
        result = tools.get_captcha_screenshot(
            config,
            grid_size=args.get("grid_size"),
        )

    elif action == "click_checkbox":
        result = tools.click_captcha_area(config, area_id=1)

    elif action == "click_blocks":
        if not args.get("blocks"):
            return ToolResult.error("'blocks' array required")
        result = tools.click_captcha_blocks(
            config,
            blocks=args["blocks"],
            grid_size=args.get("grid_size", 0),
        )

    elif action == "click_area":
        result = tools.click_captcha_area(
            config,
            area_id=args.get("area_id", 1),
        )

    elif action == "submit":
        result = tools.submit_captcha(config)

    else:
        return ToolResult.error(f"Unknown action: {action}")

    result["action"] = action
    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE
# ═══════════════════════════════════════════════════════════════════════════════


def handle_page(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Page analysis - primary tool for understanding page."""
    if args.get("info"):
        result = tools.get_page_info(config)
    elif args.get("detail"):
        result = tools.analyze_page(
            config,
            detail=args["detail"],
            offset=args.get("offset", 0),
            limit=args.get("limit", 10),
            form_index=args.get("form_index"),
        )
    else:
        result = tools.analyze_page(config)

    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# SCREENSHOT
# ═══════════════════════════════════════════════════════════════════════════════


def handle_screenshot(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Take screenshot."""
    result = tools.screenshot(config)
    # screenshot() returns content_b64, not data
    data = result.get("content_b64") or result.get("data", "")
    return ToolResult.image(data, "image/png")


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITY HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════


def handle_js(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Execute JavaScript."""
    result = tools.eval_js(config, args["code"])
    return ToolResult.json(result)


def handle_http(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """HTTP request outside browser."""
    from ...http_client import http_get

    result = http_get(args["url"], config)
    return ToolResult.json(result)


def handle_fetch(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Fetch from browser context."""
    result = tools.browser_fetch(
        config,
        url=args["url"],
        method=args.get("method", "GET"),
        body=args.get("body"),
        headers=args.get("headers"),
    )
    return ToolResult.json(result)


def handle_upload(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Upload file."""
    result = tools.upload_file(
        config,
        file_paths=args["file_paths"],
        selector=args.get("selector"),
    )
    return ToolResult.json(result)


def handle_dialog(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Handle JS dialog."""
    result = tools.handle_dialog(
        config,
        accept=args.get("accept", True),
        prompt_text=args.get("text"),
    )
    return ToolResult.json(result)


def handle_totp(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Generate TOTP code."""
    result = tools.generate_totp(
        secret=args["secret"],
        digits=args.get("digits", 6),
        interval=args.get("interval", 30),
    )
    return ToolResult.json(result)


def handle_wait(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Wait for condition."""
    wait_for = args["for"]
    timeout = args.get("timeout", 10)

    start = time.time()

    if wait_for == "element":
        if not args.get("selector"):
            return ToolResult.error("'selector' required for element wait")
        result = tools.wait_for_element(config, args["selector"], timeout)
    elif wait_for in ("navigation", "load", "networkidle"):
        result = _wait_for_condition(config, wait_for, timeout)
    elif wait_for == "text":
        result = tools.wait_for(config, condition="text", text=args.get("text"), timeout=timeout)
    else:
        return ToolResult.error(f"Unknown wait type: {wait_for}")

    result["waited_for"] = wait_for
    result["duration_ms"] = int((time.time() - start) * 1000)
    return ToolResult.json(result)


def handle_browser(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Browser control: status, launch, dom, element."""
    action = args.get("action", "status")

    if action == "status":
        result = launcher.cdp_version()
        result["action"] = "status"
        result["running"] = result.get("status") == 200

    elif action == "launch":
        launcher.ensure_running()
        result = {"action": "launch", "launched": True}

    elif action == "dom":
        result = tools.get_dom(
            config,
            selector=args.get("selector"),
            max_chars=args.get("max_chars", 50000),
        )
        result["action"] = "dom"

    elif action == "element":
        if not args.get("selector"):
            return ToolResult.error("'selector' required for element")
        result = tools.get_element_info(config, args["selector"])
        result["action"] = "element"

    else:
        return ToolResult.error(f"Unknown action: {action}")

    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _wait_for_condition(config: BrowserConfig, condition: str, timeout: float = 10) -> dict[str, Any]:
    """Wait for navigation/load condition."""
    try:
        result = tools.wait_for(config, condition=condition, timeout=timeout)
        return {"found": True, **result}
    except Exception:
        return {"found": False, "timeout": True}


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

UNIFIED_HANDLERS: dict[str, tuple] = {
    # Core
    "page": (handle_page, True),
    "navigate": (handle_navigate, True),
    "click": (handle_click, True),
    "type": (handle_type, True),
    "scroll": (handle_scroll, True),
    "form": (handle_form, True),
    "screenshot": (handle_screenshot, True),
    # Management
    "tabs": (handle_tabs, True),
    "cookies": (handle_cookies, True),
    "captcha": (handle_captcha, True),
    # Low-level
    "mouse": (handle_mouse, True),
    "resize": (handle_resize, True),
    # Utility
    "js": (handle_js, True),
    "http": (handle_http, False),
    "fetch": (handle_fetch, True),
    "upload": (handle_upload, True),
    "dialog": (handle_dialog, True),
    "totp": (handle_totp, False),
    "wait": (handle_wait, True),
    "browser": (handle_browser, False),
}
