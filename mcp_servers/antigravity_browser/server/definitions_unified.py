"""
Unified MCP tool definitions.

Design principles:
1. One tool = one concept (not one action)
2. Smart defaults + optional precision
3. Rich response with context
4. Auto-wait where appropriate
"""

from __future__ import annotations

from typing import Any

# ═══════════════════════════════════════════════════════════════════════════════
# NAVIGATION
# ═══════════════════════════════════════════════════════════════════════════════

NAVIGATE_TOOL: dict[str, Any] = {
    "name": "navigate",
    "description": """Navigate to URL or perform navigation action.

USAGE:
- Go to URL: navigate(url="https://example.com")
- Go back: navigate(action="back")
- Go forward: navigate(action="forward")
- Reload: navigate(action="reload")

AUTO-WAIT: Waits for page load by default. Use wait="none" to skip.

RESPONSE EXAMPLE:
{
  "url": "https://example.com/",
  "title": "Example Domain",
  "waited": "load"
}""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to navigate to"},
            "action": {
                "type": "string",
                "enum": ["back", "forward", "reload"],
                "description": "Navigation action instead of URL",
            },
            "wait": {
                "type": "string",
                "enum": ["load", "domcontentloaded", "networkidle", "none"],
                "default": "load",
                "description": "What to wait for after navigation (default: load)",
            },
        },
        "additionalProperties": False,
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# SCROLL
# ═══════════════════════════════════════════════════════════════════════════════

SCROLL_TOOL: dict[str, Any] = {
    "name": "scroll",
    "description": """Scroll the page in any direction or to specific element.

USAGE:
- Scroll down: scroll(direction="down")
- Scroll up 500px: scroll(direction="up", amount=500)
- Scroll to element: scroll(to="#footer")
- Scroll to bottom: scroll(to_bottom=true)
- Scroll to top: scroll(to_top=true)

RESPONSE EXAMPLE:
{
  "scrollX": 0,
  "scrollY": 450,
  "atBottom": false,
  "atTop": false
}""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": ["up", "down", "left", "right"],
                "description": "Scroll direction",
            },
            "amount": {
                "type": "number",
                "default": 300,
                "description": "Pixels to scroll (default: 300)",
            },
            "to": {
                "type": "string",
                "description": "CSS selector of element to scroll into view",
            },
            "to_top": {"type": "boolean", "description": "Scroll to top of page"},
            "to_bottom": {"type": "boolean", "description": "Scroll to bottom of page"},
        },
        "additionalProperties": False,
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# CLICK
# ═══════════════════════════════════════════════════════════════════════════════

CLICK_TOOL: dict[str, Any] = {
    "name": "click",
    "description": """Universal click tool - by text, selector, or coordinates.

USAGE (in order of preference):
- By visible text: click(text="Sign In")
- By text + role: click(text="Submit", role="button")
- By selector: click(selector="#login-btn")
- By coordinates: click(x=100, y=200)
- Double click: click(text="file.txt", double=true)
- Right click: click(selector=".item", button="right")

AUTO-WAIT: After clicking links, waits for navigation.

RESPONSE EXAMPLE:
{
  "success": true,
  "clicked": {"tag": "BUTTON", "text": "Sign In", "x": 150, "y": 300},
  "page_changed": false
}""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Visible text of element to click (preferred)",
            },
            "selector": {
                "type": "string",
                "description": "CSS selector of element",
            },
            "x": {"type": "number", "description": "X coordinate for pixel click"},
            "y": {"type": "number", "description": "Y coordinate for pixel click"},
            "role": {
                "type": "string",
                "enum": ["button", "link", "checkbox", "radio", "tab", "menuitem"],
                "description": "Filter by element role",
            },
            "near": {
                "type": "string",
                "description": "Find element near this text (for unlabeled elements)",
            },
            "index": {
                "type": "integer",
                "default": 0,
                "description": "If multiple matches, which one (0=first, -1=last)",
            },
            "double": {
                "type": "boolean",
                "default": False,
                "description": "Double click instead of single",
            },
            "button": {
                "type": "string",
                "enum": ["left", "right", "middle"],
                "default": "left",
                "description": "Mouse button",
            },
            "wait_after": {
                "type": "string",
                "enum": ["auto", "navigation", "none"],
                "default": "auto",
                "description": "What to wait for after click",
            },
        },
        "additionalProperties": False,
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# TYPE
# ═══════════════════════════════════════════════════════════════════════════════

TYPE_TOOL: dict[str, Any] = {
    "name": "type",
    "description": """Type text into element or press keys.

USAGE:
- Type into element: type(selector="#email", text="user@example.com")
- Type into focused: type(text="hello world")
- Press key: type(key="Enter")
- Key with modifier: type(key="a", ctrl=true)  # Ctrl+A
- Clear and type: type(selector="#search", text="query", clear=true)

RESPONSE EXAMPLE:
{
  "success": true,
  "typed": "user@example.com",
  "element": {"tag": "INPUT", "type": "email"}
}""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to type"},
            "selector": {
                "type": "string",
                "description": "CSS selector of input element (omit to type into focused)",
            },
            "key": {
                "type": "string",
                "description": "Key to press (Enter, Tab, Escape, ArrowUp, etc.)",
            },
            "clear": {
                "type": "boolean",
                "default": False,
                "description": "Clear existing value before typing",
            },
            "submit": {
                "type": "boolean",
                "default": False,
                "description": "Press Enter after typing",
            },
            "ctrl": {"type": "boolean", "description": "Hold Ctrl"},
            "alt": {"type": "boolean", "description": "Hold Alt"},
            "shift": {"type": "boolean", "description": "Hold Shift"},
            "meta": {"type": "boolean", "description": "Hold Meta/Cmd"},
        },
        "additionalProperties": False,
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# MOUSE
# ═══════════════════════════════════════════════════════════════════════════════

MOUSE_TOOL: dict[str, Any] = {
    "name": "mouse",
    "description": """Low-level mouse operations: move, hover, drag.

USAGE:
- Move to coordinates: mouse(action="move", x=100, y=200)
- Hover element: mouse(action="hover", selector="#menu")
- Drag and drop: mouse(action="drag", from_x=100, from_y=100, to_x=300, to_y=300)

RESPONSE EXAMPLE:
{
  "action": "hover",
  "position": {"x": 150, "y": 200}
}""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["move", "hover", "drag"],
                "description": "Mouse action to perform",
            },
            "x": {"type": "number", "description": "X coordinate"},
            "y": {"type": "number", "description": "Y coordinate"},
            "selector": {
                "type": "string",
                "description": "CSS selector for hover action",
            },
            "from_x": {"type": "number", "description": "Drag start X"},
            "from_y": {"type": "number", "description": "Drag start Y"},
            "to_x": {"type": "number", "description": "Drag end X"},
            "to_y": {"type": "number", "description": "Drag end Y"},
            "steps": {
                "type": "integer",
                "default": 10,
                "description": "Drag interpolation steps",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# RESIZE
# ═══════════════════════════════════════════════════════════════════════════════

RESIZE_TOOL: dict[str, Any] = {
    "name": "resize",
    "description": """Resize browser viewport or window.

USAGE:
- Resize viewport: resize(width=1280, height=720)
- Resize window: resize(width=1280, height=720, target="window")
- Mobile viewport: resize(width=375, height=667)

RESPONSE EXAMPLE:
{
  "target": "viewport",
  "width": 1280,
  "height": 720
}""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "width": {"type": "integer", "description": "Width in pixels"},
            "height": {"type": "integer", "description": "Height in pixels"},
            "target": {
                "type": "string",
                "enum": ["viewport", "window"],
                "default": "viewport",
                "description": "What to resize",
            },
        },
        "required": ["width", "height"],
        "additionalProperties": False,
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# FORM
# ═══════════════════════════════════════════════════════════════════════════════

FORM_TOOL: dict[str, Any] = {
    "name": "form",
    "description": """Work with forms: fill fields, select options, submit.

USAGE:
- Fill form: form(fill={"email": "user@example.com", "password": "secret"})
- Fill and submit: form(fill={...}, submit=true)
- Select dropdown: form(select={"selector": "#country", "value": "US"})
- Focus element: form(focus="#email")
- Clear input: form(clear="#search")
- Wait for element: form(wait_for="#results", timeout=10)

RESPONSE EXAMPLE:
{
  "action": "fill",
  "fields_filled": 3,
  "submitted": true
}""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "fill": {
                "type": "object",
                "additionalProperties": True,
                "description": "Field names/labels mapped to values",
            },
            "submit": {
                "type": "boolean",
                "default": False,
                "description": "Submit form after filling",
            },
            "form_index": {
                "type": "integer",
                "default": 0,
                "description": "Which form on page (0=first)",
            },
            "select": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string"},
                    "value": {"type": "string"},
                    "by": {"type": "string", "enum": ["value", "text", "index"]},
                },
                "description": "Select dropdown option",
            },
            "focus": {
                "type": "string",
                "description": "CSS selector of element to focus",
            },
            "clear": {
                "type": "string",
                "description": "CSS selector of input to clear",
            },
            "wait_for": {
                "type": "string",
                "description": "CSS selector to wait for",
            },
            "timeout": {
                "type": "number",
                "default": 10,
                "description": "Timeout for wait_for in seconds",
            },
        },
        "additionalProperties": False,
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════════════════════════

TABS_TOOL: dict[str, Any] = {
    "name": "tabs",
    "description": """Manage browser tabs: list, switch, open, close.

USAGE:
- List tabs: tabs(action="list")
- Switch by ID: tabs(action="switch", tab_id="ABC123")
- Switch by URL: tabs(action="switch", url_contains="github")
- Open new tab: tabs(action="new", url="https://example.com")
- Close current: tabs(action="close")
- Close by ID: tabs(action="close", tab_id="ABC123")

RESPONSE EXAMPLE (list):
{
  "action": "list",
  "tabs": [
    {"id": "ABC123", "url": "https://example.com", "title": "Example", "active": true}
  ],
  "total": 1
}""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "switch", "new", "close"],
                "default": "list",
                "description": "Tab action",
            },
            "tab_id": {"type": "string", "description": "Tab ID for switch/close"},
            "url_contains": {
                "type": "string",
                "description": "Switch to tab containing this URL substring",
            },
            "url": {"type": "string", "description": "URL for new tab"},
        },
        "additionalProperties": False,
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# COOKIES
# ═══════════════════════════════════════════════════════════════════════════════

COOKIES_TOOL: dict[str, Any] = {
    "name": "cookies",
    "description": """Manage browser cookies: get, set, delete.

USAGE:
- Get all: cookies(action="get")
- Get filtered: cookies(action="get", name_filter="session")
- Set one: cookies(action="set", name="token", value="abc", domain=".example.com")
- Set multiple: cookies(action="set", cookies=[{name, value, domain}, ...])
- Delete: cookies(action="delete", name="token")

RESPONSE EXAMPLE (get):
{
  "action": "get",
  "cookies": [
    {"name": "session", "value": "abc123", "domain": ".example.com"}
  ],
  "total": 1
}""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["get", "set", "delete"],
                "default": "get",
                "description": "Cookie action",
            },
            "name": {"type": "string", "description": "Cookie name"},
            "value": {"type": "string", "description": "Cookie value (for set)"},
            "domain": {"type": "string", "description": "Cookie domain (for set)"},
            "path": {"type": "string", "default": "/", "description": "Cookie path"},
            "secure": {"type": "boolean", "description": "HTTPS only"},
            "httpOnly": {"type": "boolean", "description": "HTTP only"},
            "expires": {"type": "number", "description": "Expiration timestamp"},
            "sameSite": {"type": "string", "enum": ["Strict", "Lax", "None"]},
            "cookies": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Multiple cookies to set",
            },
            "name_filter": {
                "type": "string",
                "description": "Filter cookies by name substring",
            },
        },
        "additionalProperties": False,
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# CAPTCHA
# ═══════════════════════════════════════════════════════════════════════════════

CAPTCHA_TOOL: dict[str, Any] = {
    "name": "captcha",
    "description": """Detect and interact with CAPTCHAs.

USAGE:
- Analyze CAPTCHA: captcha(action="analyze")
- Get screenshot with grid: captcha(action="screenshot")
- Click checkbox: captcha(action="click_checkbox")
- Click grid blocks: captcha(action="click_blocks", blocks=[1, 4, 7])
- Submit: captcha(action="submit")

WORKFLOW:
1. captcha(action="analyze") - detect type
2. captcha(action="screenshot") - see the challenge
3. captcha(action="click_blocks", blocks=[...]) - select images
4. captcha(action="submit") - verify

RESPONSE EXAMPLE (analyze):
{
  "detected": true,
  "type": "recaptcha_v2_image",
  "challenge": "Select all images with traffic lights",
  "grid": {"rows": 3, "cols": 3}
}""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["analyze", "screenshot", "click_checkbox", "click_blocks", "click_area", "submit"],
                "default": "analyze",
                "description": "CAPTCHA action",
            },
            "blocks": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Block numbers to click (1-indexed)",
            },
            "area_id": {
                "type": "integer",
                "description": "Clickable area ID from analyze",
            },
            "grid_size": {
                "type": "integer",
                "description": "Force grid size (3 or 4)",
            },
        },
        "additionalProperties": False,
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE ANALYSIS (keep existing, just improve docs)
# ═══════════════════════════════════════════════════════════════════════════════

PAGE_TOOL: dict[str, Any] = {
    "name": "page",
    "description": """Analyze current page structure and content.

USAGE:
- Overview: page()
- Form details: page(detail="forms", form_index=0)
- Links list: page(detail="links", limit=20)
- Main content: page(detail="content")
- Page info: page(info=true)

THIS IS YOUR PRIMARY TOOL - call it first to understand the page.

RESPONSE EXAMPLE (overview):
{
  "url": "https://example.com/login",
  "title": "Login",
  "pageType": "form",
  "counts": {"forms": 1, "links": 5, "buttons": 2, "inputs": 3},
  "preview": {"topLinks": ["Home", "Register", "Help"]},
  "suggestedActions": ["page(detail='forms', form_index=0)"]
}""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "detail": {
                "type": "string",
                "enum": ["forms", "links", "buttons", "inputs", "content"],
                "description": "Section to get details for",
            },
            "form_index": {
                "type": "integer",
                "description": "Specific form index when detail='forms'",
            },
            "offset": {
                "type": "integer",
                "default": 0,
                "description": "Pagination offset",
            },
            "limit": {
                "type": "integer",
                "default": 10,
                "description": "Max items to return",
            },
            "info": {
                "type": "boolean",
                "description": "Get page info (url, title, scroll, viewport)",
            },
        },
        "additionalProperties": False,
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# SCREENSHOT
# ═══════════════════════════════════════════════════════════════════════════════

SCREENSHOT_TOOL: dict[str, Any] = {
    "name": "screenshot",
    "description": """Take a screenshot of the current page.

USAGE:
- Full page: screenshot()
- Specific element: screenshot(selector="#main-content")

RESPONSE: Base64 PNG image""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector to screenshot specific element",
            },
            "full_page": {
                "type": "boolean",
                "default": False,
                "description": "Capture full scrollable page",
            },
        },
        "additionalProperties": False,
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# UTILITY TOOLS (keep as-is)
# ═══════════════════════════════════════════════════════════════════════════════

UTILITY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "js",
        "description": """Execute JavaScript in browser context.

USAGE: js(code="document.title")

RESPONSE EXAMPLE:
{"result": "Page Title"}""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "JavaScript code to execute"},
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    },
    {
        "name": "http",
        "description": """Make HTTP request (not through browser).

USAGE: http(url="https://api.example.com/data")

Use for API calls. For page fetching, use navigate() instead.""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "fetch",
        "description": """Make fetch request from browser context (with cookies/session).

USAGE: fetch(url="/api/user", method="POST", body='{"name": "test"}')

Useful for authenticated API calls.""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                    "default": "GET",
                },
                "body": {"type": "string", "description": "Request body"},
                "headers": {"type": "object", "description": "Request headers"},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "upload",
        "description": """Upload file to file input.

USAGE: upload(file_paths=["/path/to/file.pdf"])""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Absolute paths to files",
                },
                "selector": {
                    "type": "string",
                    "description": "File input selector (auto-detected if omitted)",
                },
            },
            "required": ["file_paths"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dialog",
        "description": """Handle JavaScript alert/confirm/prompt dialogs.

USAGE:
- Accept: dialog(accept=true)
- Dismiss: dialog(accept=false)
- With text: dialog(accept=true, text="my answer")""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "accept": {
                    "type": "boolean",
                    "default": True,
                    "description": "Accept or dismiss",
                },
                "text": {"type": "string", "description": "Text for prompt dialog"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "totp",
        "description": """Generate TOTP code for 2FA.

USAGE: totp(secret="JBSWY3DPEHPK3PXP")

RESPONSE: {"code": "123456", "remaining_seconds": 15}""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "secret": {
                    "type": "string",
                    "description": "Base32-encoded TOTP secret",
                },
                "digits": {"type": "integer", "default": 6},
                "interval": {"type": "integer", "default": 30},
            },
            "required": ["secret"],
            "additionalProperties": False,
        },
    },
    {
        "name": "wait",
        "description": """Wait for condition.

USAGE:
- Wait for element: wait(for="element", selector="#results")
- Wait for text: wait(for="text", text="Success")
- Wait for navigation: wait(for="navigation")
- Wait for network idle: wait(for="networkidle")

RESPONSE: {"waited_for": "element", "found": true, "duration_ms": 1500}""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "for": {
                    "type": "string",
                    "enum": ["element", "text", "navigation", "networkidle", "load"],
                    "description": "What to wait for",
                },
                "selector": {"type": "string", "description": "For element wait"},
                "text": {"type": "string", "description": "For text wait"},
                "timeout": {
                    "type": "number",
                    "default": 10,
                    "description": "Timeout in seconds",
                },
            },
            "required": ["for"],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser",
        "description": """Browser control: launch, status, DOM.

USAGE:
- Check status: browser(action="status")
- Launch: browser(action="launch")
- Get DOM: browser(action="dom", selector="#content")
- Get element: browser(action="element", selector="#btn")

RESPONSE (status):
{"running": true, "version": "Chrome/130.0", "port": 9222}""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "launch", "dom", "element"],
                    "default": "status",
                },
                "selector": {"type": "string", "description": "For dom/element actions"},
                "max_chars": {
                    "type": "integer",
                    "default": 50000,
                    "description": "Max DOM chars",
                },
            },
            "additionalProperties": False,
        },
    },
]

# ═══════════════════════════════════════════════════════════════════════════════
# COMBINED EXPORT
# ═══════════════════════════════════════════════════════════════════════════════

UNIFIED_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    # Core navigation & interaction
    PAGE_TOOL,
    NAVIGATE_TOOL,
    CLICK_TOOL,
    TYPE_TOOL,
    SCROLL_TOOL,
    FORM_TOOL,
    SCREENSHOT_TOOL,
    # Management
    TABS_TOOL,
    COOKIES_TOOL,
    CAPTCHA_TOOL,
    # Low-level
    MOUSE_TOOL,
    RESIZE_TOOL,
    # Utilities
    *UTILITY_TOOLS,
]

# Tool count: 20 (down from 54)
