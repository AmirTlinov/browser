"""
Browser automation tools organized by domain.

Each module provides focused functionality:
- base: Common utilities, errors, session management
- types: TypedDict definitions for responses
- js_helpers: Reusable JavaScript helper functions
- navigation: Page navigation and history
- dom: DOM operations and screenshots
- page: Page analysis, content extraction
- smart: High-level AI-friendly interactions
- input: Mouse, keyboard, scroll operations
- forms: Form utilities (select, focus, clear, wait)
- tabs: Tab management
- cookies: Cookie operations
- captcha: CAPTCHA detection and solving
- network: HTTP fetch, JS evaluation
- viewport: Window/viewport resizing
- dialog: JavaScript dialog handling
- upload: File upload
- totp: 2FA code generation
"""

from .base import (
    PageContext,
    SmartToolError,
    ensure_allowed,
    ensure_allowed_navigation,
    get_session,
    get_session_tab_id,
    with_retry,
)
from .captcha import (
    analyze_captcha,
    click_captcha_area,
    click_captcha_blocks,
    get_captcha_screenshot,
    submit_captcha,
)
from .cookies import delete_cookie, get_all_cookies, set_cookie, set_cookies_batch
from .dialog import handle_dialog
from .dom import get_dom, get_element_info, screenshot
from .downloads import wait_for_download
from .forms import clear_input, focus_element, select_option, wait_for_element
from .input import (
    click_at_pixel,
    dom_action_click,
    dom_action_type,
    double_click_at_pixel,
    drag_from_to,
    hover_element,
    move_mouse_to,
    press_key,
    scroll_page,
    scroll_to_element,
    type_text,
)
from .navigation import go_back, go_forward, navigate_to, reload_page
from .network import browser_fetch, dump_dom_html, eval_js
from .page import (
    analyze_page,
    extract_content,
    get_page_audit,
    get_page_ax,
    get_page_context,
    get_page_diagnostics,
    get_page_frames,
    get_page_graph,
    get_page_info,
    get_page_locators,
    get_page_map,
    get_page_performance,
    get_page_resources,
    get_page_triage,
    wait_for,
)
from .smart import (
    click_accessibility,
    click_backend_node,
    click_element,
    drag_backend_node_to_xy,
    drag_backend_nodes,
    drag_xy_to_backend_node,
    execute_workflow,
    fill_form,
    focus_field,
    hover_backend_node,
    query_ax,
    scroll_backend_node,
    search_page,
    type_backend_node,
)
from .storage import storage_action
from .tabs import close_tab, list_tabs, new_tab, switch_tab
from .totp import generate_totp
from .upload import upload_file
from .viewport import resize_viewport, resize_window

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
    "get_page_ax",
    "extract_content",
    "wait_for",
    "get_page_context",
    "get_page_info",
    "get_page_audit",
    "get_page_diagnostics",
    "get_page_frames",
    "get_page_graph",
    "get_page_resources",
    "get_page_performance",
    "get_page_locators",
    "get_page_map",
    "get_page_triage",
    # Smart interactions
    "click_accessibility",
    "click_backend_node",
    "hover_backend_node",
    "drag_backend_nodes",
    "drag_backend_node_to_xy",
    "drag_xy_to_backend_node",
    "scroll_backend_node",
    "click_element",
    "fill_form",
    "focus_field",
    "query_ax",
    "search_page",
    "type_backend_node",
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
    # Downloads
    "wait_for_download",
    # Storage
    "storage_action",
    # Upload
    "upload_file",
    # TOTP
    "generate_totp",
]
