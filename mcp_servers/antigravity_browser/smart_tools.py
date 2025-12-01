"""
Smart high-level browser tools for AI agents.

This module provides backward-compatible re-exports from the refactored tools package.
All functionality is now organized in the tools/ subdirectory by domain.

For new code, prefer importing directly from specific modules:
    from mcp_servers.antigravity_browser.tools.navigation import navigate_to
    from mcp_servers.antigravity_browser.tools.page import analyze_page

Module organization:
- tools/base.py: Common utilities, errors, session management
- tools/navigation.py: Page navigation and history
- tools/dom.py: DOM operations and screenshots
- tools/page.py: Page analysis, content extraction
- tools/smart.py: High-level AI-friendly interactions (click_element, fill_form, etc.)
- tools/input.py: Mouse, keyboard, scroll operations
- tools/forms.py: Form utilities (select, focus, clear, wait)
- tools/tabs.py: Tab management
- tools/cookies.py: Cookie operations
- tools/captcha.py: CAPTCHA detection and solving
- tools/network.py: HTTP fetch, JS evaluation
- tools/viewport.py: Window/viewport resizing
- tools/dialog.py: JavaScript dialog handling
- tools/upload.py: File upload
- tools/totp.py: 2FA code generation
"""
from __future__ import annotations

# These may not be available if dependencies are missing
from contextlib import suppress

# Re-export everything from tools package for backward compatibility
# ruff: noqa: F401
from .tools import (
    # Base utilities
    PageContext,
    SmartToolError,
    # Network
    browser_fetch,
    # Forms
    clear_input,
    # Input
    click_at_pixel,
    # Tabs
    close_tab,
    # Cookies
    delete_cookie,
    dom_action_click,
    dom_action_type,
    double_click_at_pixel,
    drag_from_to,
    dump_dom_html,
    ensure_allowed,
    ensure_allowed_navigation,
    eval_js,
    focus_element,
    # TOTP
    generate_totp,
    get_all_cookies,
    # DOM
    get_dom,
    get_element_info,
    get_session,
    get_session_tab_id,
    # Navigation
    go_back,
    go_forward,
    # Dialog
    handle_dialog,
    hover_element,
    list_tabs,
    move_mouse_to,
    navigate_to,
    new_tab,
    press_key,
    reload_page,
    # Viewport
    resize_viewport,
    resize_window,
    screenshot,
    scroll_page,
    scroll_to_element,
    select_option,
    set_cookie,
    set_cookies_batch,
    switch_tab,
    type_text,
    # Upload
    upload_file,
    wait_for_element,
    with_retry,
)

with suppress(ImportError):
    from .tools import (
        analyze_page,
        extract_content,
        get_page_context,
        get_page_info,
        wait_for,
    )

with suppress(ImportError):
    from .tools import (
        click_element,
        execute_workflow,
        fill_form,
        search_page,
    )

with suppress(ImportError):
    from .tools import (
        analyze_captcha,
        click_captcha_area,
        click_captcha_blocks,
        get_captcha_screenshot,
        submit_captcha,
    )

# Legacy aliases for backward compatibility
_ensure_allowed = ensure_allowed
_ensure_allowed_navigation = ensure_allowed_navigation
_get_session = get_session  # Note: This is now a context manager!

__all__ = [
    # Base
    "SmartToolError",
    "PageContext",
    "with_retry",
    "get_session",
    "get_session_tab_id",
    "ensure_allowed",
    "ensure_allowed_navigation",
    # Navigation
    "navigate_to",
    "go_back",
    "go_forward",
    "reload_page",
    # DOM
    "get_dom",
    "get_element_info",
    "screenshot",
    # Page analysis
    "analyze_page",
    "extract_content",
    "wait_for",
    "get_page_context",
    "get_page_info",
    # Smart interactions
    "click_element",
    "fill_form",
    "search_page",
    "execute_workflow",
    # Input
    "click_at_pixel",
    "double_click_at_pixel",
    "move_mouse_to",
    "hover_element",
    "drag_from_to",
    "press_key",
    "type_text",
    "dom_action_click",
    "dom_action_type",
    "scroll_page",
    "scroll_to_element",
    # Forms
    "select_option",
    "focus_element",
    "clear_input",
    "wait_for_element",
    # Tabs
    "list_tabs",
    "switch_tab",
    "new_tab",
    "close_tab",
    # Cookies
    "set_cookie",
    "set_cookies_batch",
    "get_all_cookies",
    "delete_cookie",
    # Captcha
    "analyze_captcha",
    "get_captcha_screenshot",
    "click_captcha_blocks",
    "click_captcha_area",
    "submit_captcha",
    # Network
    "browser_fetch",
    "eval_js",
    "dump_dom_html",
    # Viewport
    "resize_viewport",
    "resize_window",
    # Dialog
    "handle_dialog",
    # Upload
    "upload_file",
    # TOTP
    "generate_totp",
]
