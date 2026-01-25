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
                "enum": ["navigation", "load", "domcontentloaded", "networkidle", "none"],
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
- Scroll to stable handle: scroll(ref="dom:123")
- Scroll to bottom: scroll(to_bottom=true)
- Scroll to top: scroll(to_top=true)
- Scroll inside container: scroll(direction="down", amount=400, container_selector=".feed")
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
            "backendDOMNodeId": {
                "type": "integer",
                "description": "Stable element handle to scroll into view (from page(detail='ax'))",
            },
            "ref": {
                "type": "string",
                "description": "Stable element ref like 'dom:123' (from page(detail='ax'))",
            },
            "to_top": {"type": "boolean", "description": "Scroll to top of page"},
            "to_bottom": {"type": "boolean", "description": "Scroll to bottom of page"},
            "container_selector": {
                "type": "string",
                "description": "Optional CSS selector for a scrollable container (for feeds/lists)",
            },
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
- Prefer AX (role+name): click(text="Submit", role="button", strategy="ax")
- By backend DOM node id (stable handle): click(backendDOMNodeId=123)
- By ref (stable handle): click(ref="dom:123")
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
            "backendDOMNodeId": {
                "type": "integer",
                "description": "Stable element handle (from page(detail='ax'))",
            },
            "ref": {
                "type": "string",
                "description": "Stable element ref like 'dom:123' (from page(detail='ax'))",
            },
            "x": {"type": "number", "description": "X coordinate for pixel click"},
            "y": {"type": "number", "description": "Y coordinate for pixel click"},
            "role": {
                "type": "string",
                "enum": ["button", "link", "checkbox", "radio", "tab", "menuitem"],
                "description": "Filter by element role",
            },
            "strategy": {
                "type": "string",
                "enum": ["auto", "ax", "dom"],
                "default": "auto",
                "description": "Element-finding strategy: auto (default), ax (Accessibility), dom (JS/DOM)",
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
- Type into element by backend handle: type(backendDOMNodeId=123, text="user@example.com", clear=true)
- Type into element by ref: type(ref="dom:123", text="user@example.com", clear=true)
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
            "backendDOMNodeId": {
                "type": "integer",
                "description": "Stable element handle (from page(detail='ax'))",
            },
            "ref": {
                "type": "string",
                "description": "Stable element ref like 'dom:123' (from page(detail='ax'))",
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
- Hover element by ref: mouse(action="hover", ref="dom:123")
- Drag and drop: mouse(action="drag", from_x=100, from_y=100, to_x=300, to_y=300)
- Drag by refs: mouse(action="drag", from_ref="dom:123", to_ref="dom:456")
- Drag from ref to coords: mouse(action="drag", from_ref="dom:123", to_x=300, to_y=300)
- Drag from coords to ref: mouse(action="drag", from_x=100, from_y=100, to_ref="dom:456")
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
            "backendDOMNodeId": {
                "type": "integer",
                "description": "Stable element handle (for hover; from page(detail='ax'))",
            },
            "ref": {
                "type": "string",
                "description": "Stable element ref like 'dom:123' (for hover; from page(detail='ax'))",
            },
            "from_x": {"type": "number", "description": "Drag start X"},
            "from_y": {"type": "number", "description": "Drag start Y"},
            "to_x": {"type": "number", "description": "Drag end X"},
            "to_y": {"type": "number", "description": "Drag end Y"},
            "from_backendDOMNodeId": {
                "type": "integer",
                "description": "Stable drag start handle (from page(detail='ax'))",
            },
            "to_backendDOMNodeId": {
                "type": "integer",
                "description": "Stable drag end handle (from page(detail='ax'))",
            },
            "from_ref": {
                "type": "string",
                "description": "Stable drag start ref like 'dom:123' (from page(detail='ax'))",
            },
            "to_ref": {
                "type": "string",
                "description": "Stable drag end ref like 'dom:123' (from page(detail='ax'))",
            },
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
- Focus field by label/name (iframe-safe): form(focus_key="Email Address", form_index=0)
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
            "focus_key": {
                "type": "string",
                "description": "Focus a field by label/name/id/placeholder (works across same-origin iframes + open shadow DOM)",
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
- Rescue (fresh tab, no restart): tabs(action="rescue")
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
                "enum": ["list", "switch", "new", "close", "rescue"],
                "default": "list",
                "description": "Tab action",
            },
            "tab_id": {"type": "string", "description": "Tab ID for switch/close"},
            "url_contains": {
                "type": "string",
                "description": "Switch to tab containing this URL substring",
            },
            "url": {"type": "string", "description": "URL for new tab"},
            "close_old": {
                "type": "boolean",
                "default": True,
                "description": "For rescue: close the previous session tab (best-effort) (default: true)",
            },
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
- Default (AI-native): page()  # triage + affordances + next actions
- In MCP_TOOLSET=v2: page() defaults to detail="map" (actions-first)
- Fast frontend triage (delta capable): page(detail="triage", since=<cursor>)
- Form details: page(detail="forms", form_index=0)
- Links list: page(detail="links", limit=20)
- Main content: page(detail="content")
- Frontend issues: page(detail="diagnostics")
- Delta frontend issues: page(detail="diagnostics", since=<cursor>)
- Accessibility query: page(detail="ax", role="button", name="Save")
- Visual AX overlay: page(detail="ax", role="button", name="Save", with_screenshot=true)
- Resource waterfall: page(detail="resources", sort="duration")
- Performance vitals: page(detail="performance")
- Frames/iframes map: page(detail="frames")
- Visual frames overlay: page(detail="frames", with_screenshot=true)
- Stable selectors: page(detail="locators", kind="button")
- Visual locator overlay: page(detail="locators", with_screenshot=true)
- Capability map (actions-first): page(detail="map")
- Navigation graph (visited pages): page(detail="graph")
- Super-report (one call): page(detail="audit")
- Super-report + net trace: page(detail="audit", trace=true)
- Page info: page(info=true)
- Store full payload off-context: page(detail="diagnostics", store=true)

THIS IS YOUR PRIMARY TOOL - call it first to understand the page.

RESPONSE FORMAT:
- Text results are returned as compact context-format Markdown ([LEGEND] + [CONTENT]), not JSON.
""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        # Some MCP clients omit arguments entirely when no params are provided.
        # Defaulting to {} makes `page()` invocations reliable.
        "default": {},
        "properties": {
            "detail": {
                "type": "string",
                "enum": [
                    "forms",
                    "links",
                    "buttons",
                    "inputs",
                    "content",
                    "triage",
                    "diagnostics",
                    "ax",
                    "resources",
                    "performance",
                    "frames",
                    "locators",
                    "map",
                    "graph",
                    "audit",
                ],
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
            "auto_scroll": {
                "description": "Auto-scroll the page before analysis (best-effort; useful for lazy-loaded content).",
                "oneOf": [
                    {"type": "boolean"},
                    {
                        "type": "object",
                        "properties": {
                            "max_iters": {
                                "type": "integer",
                                "default": 8,
                                "description": "Max scroll iterations (bounded server-side).",
                            },
                            "direction": {
                                "type": "string",
                                "enum": ["down", "up", "left", "right"],
                                "default": "down",
                                "description": "Scroll direction per iteration.",
                            },
                            "amount": {
                                "type": "integer",
                                "default": 700,
                                "description": "Scroll delta per iteration (pixels).",
                            },
                            "settle_ms": {
                                "type": "integer",
                                "default": 150,
                                "description": "Sleep after each scroll (ms) to allow lazy loads.",
                            },
                            "until_js": {
                                "type": "string",
                                "description": "JS expression that returns true when scrolling can stop.",
                            },
                            "container_selector": {
                                "type": "string",
                                "description": "Optional CSS selector for a scrollable container (feeds/lists).",
                            },
                            "stop_on_url_change": {
                                "type": "boolean",
                                "default": False,
                                "description": "Stop auto-scroll if the page URL changes (guards against SPA state jumps).",
                            },
                            "required": {
                                "type": "boolean",
                                "default": False,
                                "description": "If true, fail the tool call when auto-scroll errors.",
                            },
                        },
                        "additionalProperties": False,
                    },
                ],
            },
            "auto_expand": {
                "description": "Auto-expand collapsed content (best-effort; 'show more/read more' patterns).",
                "oneOf": [
                    {"type": "boolean"},
                    {
                        "type": "object",
                        "properties": {
                            "phrases": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Lowercased phrases to match (e.g., show more, read more).",
                            },
                            "selectors": {
                                "oneOf": [
                                    {"type": "string"},
                                    {"type": "array", "items": {"type": "string"}},
                                ],
                                "description": "CSS selector(s) to scan for expand controls.",
                            },
                            "include_links": {
                                "type": "boolean",
                                "default": False,
                                "description": "Allow anchor tags when they look like buttons (#/javascript:/role=button).",
                            },
                            "click_limit": {
                                "type": "integer",
                                "default": 6,
                                "description": "Max clicks per iteration.",
                            },
                            "max_iters": {
                                "type": "integer",
                                "default": 6,
                                "description": "Max expand iterations (bounded server-side).",
                            },
                            "settle_ms": {
                                "type": "integer",
                                "default": 150,
                                "description": "Sleep after each click batch (ms) to allow hydration.",
                            },
                            "required": {
                                "type": "boolean",
                                "default": False,
                                "description": "If true, fail the tool call when auto-expand errors.",
                            },
                        },
                        "additionalProperties": False,
                    },
                ],
            },
            "since": {
                "type": "integer",
                "description": "For detail='triage'/'diagnostics'/'resources': return only changes since this cursor (ms)",
            },
            "store": {
                "type": "boolean",
                "default": False,
                "description": "Store the full result as an artifact for drilldown (keeps context window small)",
            },
            "role": {
                "type": "string",
                "description": "For detail='ax': accessibility role filter (e.g., button, link, checkbox)",
            },
            "name": {
                "type": "string",
                "description": "For detail='ax': accessibility name filter (visible label / accessible name)",
            },
            "sort": {
                "type": "string",
                "enum": ["start", "duration", "size"],
                "default": "start",
                "description": "For diagnostics/resources: sort resource timings",
            },
            "kind": {
                "type": "string",
                "enum": ["all", "button", "link", "input"],
                "default": "all",
                "description": "For detail='locators': what elements to include",
            },
            "info": {
                "type": "boolean",
                "description": "Get page info (url, title, scroll, viewport)",
            },
            "clear": {
                "type": "boolean",
                "default": False,
                "description": "For detail='diagnostics': clear stored events after snapshot",
            },
            "with_screenshot": {
                "type": "boolean",
                "default": False,
                "description": "For detail='triage', 'locators', or 'ax': attach a screenshot image to the result",
            },
            "overlay": {
                "type": "boolean",
                "default": True,
                "description": "For detail='locators' or 'ax' + with_screenshot: draw numbered overlay boxes (default: true)",
            },
            "overlay_limit": {
                "type": "integer",
                "default": 20,
                "description": "For detail='locators' or 'ax' + with_screenshot: cap overlay items (default: 20)",
            },
            "trace": {
                "description": "For detail='audit': optionally capture a bounded Tier-0 network trace (stored as an artifact) for deep debugging.",
                "oneOf": [
                    {"type": "boolean"},
                    {
                        "type": "object",
                        "properties": {
                            "include": {
                                "description": "Include URL substring patterns (case-insensitive).",
                                "oneOf": [
                                    {"type": "string"},
                                    {"type": "array", "items": {"type": "string"}},
                                ],
                            },
                            "exclude": {
                                "description": "Exclude URL substring patterns (case-insensitive).",
                                "oneOf": [
                                    {"type": "string"},
                                    {"type": "array", "items": {"type": "string"}},
                                ],
                            },
                            "types": {
                                "description": "Resource types (e.g., XHR, Fetch). Defaults to XHR/Fetch if no filters are set.",
                                "oneOf": [
                                    {"type": "string"},
                                    {"type": "array", "items": {"type": "string"}},
                                ],
                            },
                            "capture": {
                                "type": "string",
                                "enum": ["meta", "request", "body", "full"],
                                "default": "meta",
                                "description": "Capture level: meta only, request postData, response body, or full (request+body).",
                            },
                            "redact": {
                                "type": "boolean",
                                "default": True,
                                "description": "Redact sensitive tokens from captured bodies (recommended).",
                            },
                            "maxBodyBytes": {
                                "type": "integer",
                                "default": 80000,
                                "description": "Max bytes per response body (after decoding).",
                            },
                            "maxTotalBytes": {
                                "type": "integer",
                                "default": 600000,
                                "description": "Total byte budget across all captured bodies (0 = unbounded).",
                            },
                            "since": {
                                "type": "integer",
                                "description": "Only include requests completed after this timestamp (ms).",
                            },
                            "offset": {
                                "type": "integer",
                                "default": 0,
                                "description": "Pagination offset within the matched request set.",
                            },
                            "limit": {
                                "type": "integer",
                                "default": 20,
                                "description": "Max trace items to include (tool output stays bounded; full trace goes to artifact).",
                            },
                            "store": {
                                "type": "boolean",
                                "default": True,
                                "description": "Store the trace as an artifact for drilldown (recommended).",
                            },
                            "export": {
                                "type": "boolean",
                                "default": False,
                                "description": "Export the artifact to disk (implies store=true).",
                            },
                            "overwrite": {
                                "type": "boolean",
                                "default": False,
                                "description": "Overwrite export destination if exists.",
                            },
                            "name": {
                                "type": "string",
                                "description": "Optional export filename for the trace artifact.",
                            },
                            "clear": {
                                "type": "boolean",
                                "default": False,
                                "description": "Clear the Tier-0 net trace buffer after capture.",
                            },
                        },
                        "additionalProperties": False,
                    },
                ],
            },
        },
        "additionalProperties": False,
    },
}
# ═══════════════════════════════════════════════════════════════════════════════
# EXTRACT CONTENT (structured, paginated)
# ═══════════════════════════════════════════════════════════════════════════════

EXTRACT_TOOL: dict[str, Any] = {
    "name": "extract_content",
    "description": """SMART EXTRACT: Get structured content from page with pagination.
Use instead of full DOM dumps when you need specific data.
OVERVIEW MODE (default):
Returns content structure summary with counts and hints.

DETAIL MODES with pagination:
- content_type="main" + offset/limit: Main text paragraphs
- content_type="table": List of tables with metadata
- content_type="table" + table_index=N + offset/limit: Rows of table N
- content_type="links" + offset/limit: All links
- content_type="headings": Document outline (h1-h6)
- content_type="images" + offset/limit: Images with metadata
""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Optional URL to navigate before extraction (one-call navigate+extract).",
            },
            "wait": {
                "type": "string",
                "enum": ["navigation", "load", "domcontentloaded", "networkidle", "none"],
                "default": "load",
                "description": "What to wait for after navigation (default: load).",
            },
            "content_type": {
                "type": "string",
                "enum": ["overview", "main", "table", "links", "headings", "images"],
                "description": "What to extract (default: overview)",
                "default": "overview",
            },
            "selector": {
                "type": "string",
                "description": "Optional CSS selector to limit scope",
            },
            "offset": {
                "type": "integer",
                "description": "Starting index for paginated results (default: 0)",
                "default": 0,
            },
            "limit": {
                "type": "integer",
                "description": "Max items to return (default: 10, max: 50)",
                "default": 10,
            },
            "table_index": {
                "type": "integer",
                "description": "Specific table index when content_type='table'",
            },
            "auto_expand": {
                "description": "Auto-expand collapsed content before extraction (best-effort).",
                "oneOf": [
                    {"type": "boolean"},
                    {
                        "type": "object",
                        "properties": {
                            "phrases": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Phrases to match (show more/read more/etc.)",
                            },
                            "selectors": {
                                "type": ["string", "array"],
                                "description": "Selectors to scan for expandable controls.",
                            },
                            "include_links": {
                                "type": "boolean",
                                "default": False,
                                "description": "Allow anchor tags when they act like buttons.",
                            },
                            "click_limit": {
                                "type": "integer",
                                "default": 6,
                                "description": "Max clicks per iteration.",
                            },
                            "max_iters": {
                                "type": "integer",
                                "default": 6,
                                "description": "Max iterations (bounded).",
                            },
                            "timeout_s": {
                                "type": "number",
                                "default": 0.4,
                                "description": "Per-condition wait timeout.",
                            },
                            "wait": {
                                "type": "object",
                                "description": "Optional wait args after each click batch.",
                            },
                            "settle_ms": {
                                "type": "integer",
                                "default": 150,
                                "description": "Backoff between iterations (ms).",
                            },
                            "required": {
                                "type": "boolean",
                                "default": False,
                                "description": "If true, fail the tool call when auto-expand errors.",
                            },
                        },
                        "additionalProperties": False,
                    },
                ],
            },
            "auto_scroll": {
                "description": "Auto-scroll before extraction (best-effort; useful for lazy-loaded content).",
                "oneOf": [
                    {"type": "boolean"},
                    {
                        "type": "object",
                        "properties": {
                            "max_iters": {
                                "type": "integer",
                                "default": 8,
                                "description": "Max scroll iterations (bounded server-side).",
                            },
                            "direction": {
                                "type": "string",
                                "enum": ["down", "up", "left", "right"],
                                "default": "down",
                                "description": "Scroll direction per iteration.",
                            },
                            "amount": {
                                "type": "integer",
                                "default": 700,
                                "description": "Scroll delta per iteration (pixels).",
                            },
                            "settle_ms": {
                                "type": "integer",
                                "default": 150,
                                "description": "Sleep after each scroll (ms) to allow lazy loads.",
                            },
                            "until_js": {
                                "type": "string",
                                "description": "JS expression that returns true when scrolling can stop.",
                            },
                            "container_selector": {
                                "type": "string",
                                "description": "Optional CSS selector for a scrollable container (feeds/lists).",
                            },
                            "stop_on_url_change": {
                                "type": "boolean",
                                "default": False,
                                "description": "Stop auto-scroll if the page URL changes.",
                            },
                            "required": {
                                "type": "boolean",
                                "default": False,
                                "description": "If true, fail the tool call when auto-scroll errors.",
                            },
                        },
                        "additionalProperties": False,
                    },
                ],
            },
            "store": {
                "type": "boolean",
                "default": False,
                "description": "Store the full result as an artifact (keeps output small).",
            },
        },
        "required": [],
        "additionalProperties": False,
    },
}
# ═══════════════════════════════════════════════════════════════════════════════
# FLOW (SUPER-TOOL)
# ═══════════════════════════════════════════════════════════════════════════════

FLOW_TOOL: dict[str, Any] = {
    "name": "flow",
    "description": """DEPRECATED: use `run(...)` instead.

Run a compact multi-step browser workflow in a single tool call.

Goal: reduce tool-call count + reduce output noise. One call = many steps + one compact summary.

STEP FORMATS:
1) Explicit:
   {"tool": "navigate", "args": {"url": "https://example.com"}}
2) Shorthand:
   {"navigate": {"url": "https://example.com"}}

OPTIONAL EXPORTS (explicit or shorthand steps):
- Export scalar fields from a step's raw payload without dumping the full output:
  {"tool":"page","args":{"detail":"triage"},"export":{"cursor":"cursor","url":"triage.url"}}

STATEFUL FLOWS (export → interpolate):
- Exports persist across steps inside the same `flow(...)`/`run(...)` call.
- Reference exported vars in later step args via `{{var}}` or `${var}`.
  - Exact placeholder preserves scalar type: {"timeout":"{{cursor}}"} → int
  - Inline replacement stringifies: {"url":".../{{artifactId}}"} → str
OUTPUT:
- Always context-format Markdown (`[LEGEND]` + `[CONTENT]`), not JSON.
- Step list is summary-only by default (no massive dumps).
""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "minItems": 1,
                "description": "List of steps to execute (explicit or shorthand format)",
                "items": {"type": "object"},
            },
            "start_at": {
                "type": "integer",
                "default": 0,
                "description": "Start executing steps from this index (resume a partially completed flow)",
            },
            "record_memory_key": {
                "type": "string",
                "description": "Optional: record the original steps into agent memory under this key (runbook recorder)",
            },
            "record_mode": {
                "type": "string",
                "enum": ["sanitized", "raw"],
                "default": "sanitized",
                "description": "Recorder mode: sanitized (safe-by-default) or raw (stores literals; risky)",
            },
            "record_on_failure": {
                "type": "boolean",
                "default": False,
                "description": "If true, record steps even when the flow fails (default: false)",
            },
            "stop_on_error": {
                "type": "boolean",
                "default": True,
                "description": "Stop the flow on the first non-optional error (default: true)",
            },
            "delta_final": {
                "type": "boolean",
                "default": True,
                "description": "If final snapshot is enabled, make it delta-only (since the flow start) (default: true)",
            },
            "steps_output": {
                "type": "string",
                "enum": ["compact", "errors", "none"],
                "default": "compact",
                "description": "How much per-step output to return (default: compact)",
            },
            "screenshot_on_error": {
                "type": "boolean",
                "default": False,
                "description": "If the flow fails, attach a screenshot (default: false)",
            },
            "triage_on_error": {
                "type": "boolean",
                "default": True,
                "description": "If the flow fails, include a delta triage snapshot (default: true)",
            },
            "diagnostics_on_error": {
                "type": "boolean",
                "default": False,
                "description": "If the flow fails, include a delta diagnostics snapshot (default: false)",
            },
            "final": {
                "type": "string",
                "enum": ["none", "observe", "audit", "triage", "diagnostics", "map", "graph"],
                "default": "observe",
                "description": "Attach one compact final snapshot (default: observe)",
            },
            "final_limit": {
                "type": "integer",
                "default": 30,
                "description": "Limit for final=audit/triage/diagnostics (default: 30)",
            },
            "step_proof": {
                "type": "boolean",
                "default": False,
                "description": "Attach compact per-step proof (internal; default: false)",
            },
            "proof_screenshot": {
                "type": "string",
                "enum": ["none", "artifact"],
                "default": "none",
                "description": "How to capture screenshots for proof (default: none)",
            },
            "screenshot_on_ambiguity": {
                "type": "boolean",
                "default": False,
                "description": "Capture a screenshot when a step is ambiguous (default: false)",
            },
            "auto_dialog": {
                "type": "string",
                "enum": ["auto", "off", "dismiss", "accept"],
                "default": "off",
                "description": "Auto-handle blocking JS dialogs (default: off)",
            },
            "auto_recover": {
                "type": "boolean",
                "default": False,
                "description": "Auto-recover from CDP brick states (default: false)",
            },
            "max_recoveries": {
                "type": "integer",
                "default": 0,
                "description": "Maximum number of recovery attempts (default: 0)",
            },
            "recover_hard": {
                "type": "boolean",
                "default": False,
                "description": "Prefer hard recovery (restart owned Chrome) when recovering (default: false)",
            },
            "recover_timeout": {
                "type": "number",
                "default": 5.0,
                "description": "Recovery timeout seconds (default: 5.0)",
            },
            "timeout_profile": {
                "type": "string",
                "enum": ["fast", "default", "slow"],
                "default": "default",
                "description": "Optional timeout profile (sets sane defaults for timeouts and internal waits)",
            },
            "action_timeout": {
                "type": "number",
                "default": 30.0,
                "description": "Per-step watchdog seconds (guarantees bounded flow time; default: 30.0)",
            },
            "auto_download": {
                "type": "boolean",
                "default": False,
                "description": "Auto-capture downloads after click-like steps (stores as artifact when detected; default: false)",
            },
            "auto_download_timeout": {
                "type": "number",
                "default": 3.0,
                "description": "Auto-download wait seconds (bounded; default: 3.0)",
            },
            "auto_tab": {
                "type": "boolean",
                "default": False,
                "description": "Auto-switch to a newly opened tab after click-like actions (best-effort; default: false)",
            },
            "auto_affordances": {
                "type": "boolean",
                "default": True,
                "description": "Auto-refresh affordances when act(ref/label) looks stale (URL mismatch or missing refs; default: true)",
            },
            "with_screenshot": {
                "type": "boolean",
                "default": False,
                "description": "Attach a final screenshot image to the result",
            },
        },
        "required": ["steps"],
        "additionalProperties": False,
    },
}
# ═══════════════════════════════════════════════════════════════════════════════
# RUN (North Star v3)
# ═══════════════════════════════════════════════════════════════════════════════

RUN_TOOL: dict[str, Any] = {
    "name": "run",
    "description": """Run an AI-native scenario using OAVR: Observe → Act → Verify → Report.

This is the recommended entrypoint for multi-step work:
- Holds one shared CDP session across all actions (less flake, fewer round-trips).
- Returns a compact report + proof so agents avoid extra "check" calls.

Default report behavior:
- MCP_TOOLSET=v1/default: report="observe"
- MCP_TOOLSET=v2: report="map"

INTERNAL ACTIONS (v2):
`run()` can execute the same action steps as `flow`, including (common set):
- navigate, click, type, scroll, form, wait
- page (triage/diagnostics/ax/locators/resources/performance)
- app (high-level app macros/adapters for complex web apps)
- dialog (alert/confirm/prompt)
- captcha (analyze/screenshot/click_blocks/submit)
- fetch, storage, download
- net(action="harLite")  # Tier-0 network slice
- net(action="trace")    # Tier-0 deep trace (bounded, on-demand)
These are not separate top-level tools in v2; they are actions inside `run`.

INTERNAL ACTIONS (v3 additions; only inside `run(actions=[...])`, not top-level tools):
Schemas (shape):
- assert: {"assert": {"timeout_s": 5, "url": "...", "title": "...", "selector": "...", "text": "...", "js": "..." }}
- when: {"when": {"if": {"url": "...", "selector": "...", "text": "...", "js": "..."}, "then": [...], "else": [...]}}
- macro: {"macro": {"name": "...", "args": {...}, "dry_run": true}}

Notes:
- Server-side only (no LLM execution); deterministic and bounded by run limits.
- assert is fail-closed: timeout or mismatch fails the run.
- when executes a single branch (no loops); else is optional.
- macro is for compact, deterministic expansions (e.g., include saved step lists).

INTERNAL ACTIONS (v4 additions; only inside `run(actions=[...])`, not top-level tools):
Schemas (shape):
- repeat: {"repeat": {"max_iters": 5, "until": {"selector": "...", "text": "...", "url": "...", "js": "..."}, "steps": [...], "max_time_s": 20, "backoff_s": 0.2, "backoff_factor": 1.5, "backoff_max_s": 2.0}}

Notes:
- repeat is bounded: max_iters is capped server-side (no unbounded loops).
- If `until` is omitted, repeat runs exactly max_iters times and succeeds (like a for-loop).
- If `until` is provided and never matches, repeat fails closed after max_iters.
- Optional `max_time_s` adds a wall-clock budget for the whole repeat loop (fail-closed when exhausted).
- Optional backoff (`backoff_s`, `backoff_factor`, `backoff_max_s`) sleeps between iterations (deterministic, bounded).
- `js` conditions are evaluated in-page and must return a truthy value.

Examples:
1) {"assert": {"url": "https://example.com", "title": "Example Domain", "timeout_s": 5}}
2) {"when": {"if": {"selector": "#login", "text": "Sign in"}, "then": [{"click": {"selector": "#login"}}], "else": [{"navigate": {"url": "https://example.com/login"}}]}}
3) {"macro": {"name": "trace_then_screenshot", "args": {"trace": "harLite"}, "dry_run": true}}
4) {"macro": {"name": "include_memory_steps", "args": {"memory_key": "workflow.login", "params": {"user": "alice"}}}}
5) {"repeat": {"max_iters": 10, "until": {"selector": "#result"}, "steps": [{"scroll": {"direction": "down"}}]}}
6) {"macro": {"name": "auto_expand", "args": {"phrases": ["show more", "read more"]}}}
6) {"repeat": {"max_iters": 8, "until": {"js": "window.scrollY > 2000"}, "steps": [{"scroll": {"direction": "down"}}]}}

HIGH-LEVERAGE INTERNAL ACTION:
- act(ref="aff:...")  # resolve a stable affordance ref from page(detail="locators") / page(detail="map") / page(detail="triage")
  This is the fastest way to click/focus without re-specifying selectors/text.
- act(label="Save", kind="button")  # deterministic label resolver (exact match; uses stored affordances; may refresh once)

ACTION FORMATS (same as flow steps):
1) Explicit:
   {"tool": "navigate", "args": {"url": "https://example.com"}}
2) Shorthand:
   {"navigate": {"url": "https://example.com"}}

STATEFUL RUNS (export → interpolate):
- You can export scalars from one action and reuse them in later actions via `{{var}}` / `${var}`.
  This enables single-call pipelines (e.g., capture trace → read artifact → act on results) without extra tool calls.

SAFETY:
- Mark an action as irreversible (requires confirm_irreversible=true):
  {"tool":"click","args":{"text":"Delete"},"irreversible":true}

ROBUSTNESS:
- If a blocking JS dialog is open, non-dialog actions fail fast with a dialog suggestion.
- Optional: auto-handle dialogs (dismiss/accept) based on policy mode (strict vs permissive).
- Optional: auto-recover from known CDP brick states and continue (bounded attempts).
- If any action produces an image (e.g., CAPTCHA screenshot), the image is stored off-context
  as an artifact and surfaced via `next` drilldown hints.
OUTPUT:
- Always context-format Markdown (`[LEGEND]` + `[CONTENT]`), not JSON.
- Defaults to a delta observe report since the run start.
""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "Human goal (optional, for logging/traceability)"},
            "actions": {
                "type": "array",
                "minItems": 1,
                "description": "List of actions to execute (explicit or shorthand format)",
                "items": {"type": "object"},
            },
            "record_memory_key": {
                "type": "string",
                "description": "Optional: record the original actions into agent memory under this key (runbook recorder)",
            },
            "record_mode": {
                "type": "string",
                "enum": ["sanitized", "raw"],
                "default": "sanitized",
                "description": "Recorder mode: sanitized (safe-by-default) or raw (stores literals; risky)",
            },
            "record_on_failure": {
                "type": "boolean",
                "default": False,
                "description": "If true, record actions even when the run fails (default: false)",
            },
            # Back-compat alias (deprecated)
            "steps": {
                "type": "array",
                "minItems": 1,
                "description": "DEPRECATED alias for actions",
                "items": {"type": "object"},
            },
            "start_at": {
                "type": "integer",
                "default": 0,
                "description": "Start executing actions from this index (resume a partially completed run)",
            },
            "stop_on_error": {
                "type": "boolean",
                "default": True,
                "description": "Stop on the first non-optional error (default: true)",
            },
            "confirm_irreversible": {
                "type": "boolean",
                "default": False,
                "description": "Allow steps explicitly marked irreversible=true (default: false)",
            },
            "auto_dialog": {
                "type": "string",
                "enum": ["auto", "off", "dismiss", "accept"],
                "default": "auto",
                "description": "Auto-handle blocking JS dialogs: auto (strict->off, permissive->dismiss), or force off/dismiss/accept",
            },
            "auto_recover": {
                "type": "boolean",
                "default": True,
                "description": "Auto-recover from known CDP brick states (timeouts/unreachable) and continue when safe (default: true)",
            },
            "max_recoveries": {
                "type": "integer",
                "default": 1,
                "description": "Maximum number of auto-recovery attempts per run (default: 1)",
            },
            "recover_hard": {
                "type": "boolean",
                "default": False,
                "description": "Prefer hard recovery (restart owned Chrome) when recovering (default: false)",
            },
            "recover_timeout": {
                "type": "number",
                "default": 5.0,
                "description": "Recovery timeout seconds (default: 5.0)",
            },
            "timeout_profile": {
                "type": "string",
                "enum": ["fast", "default", "slow"],
                "default": "default",
                "description": "Optional timeout profile (sets sane defaults for timeouts and internal waits)",
            },
            "action_timeout": {
                "type": "number",
                "default": 30.0,
                "description": "Per-action watchdog seconds (guarantees bounded run time; default: 30.0)",
            },
            "auto_download": {
                "type": "boolean",
                "default": False,
                "description": "Auto-capture downloads after click-like actions (stores as artifact when detected; default: false)",
            },
            "auto_download_timeout": {
                "type": "number",
                "default": 3.0,
                "description": "Auto-download wait seconds (bounded; default: 3.0)",
            },
            "auto_tab": {
                "type": "boolean",
                "default": False,
                "description": "Auto-switch to a newly opened tab after click-like actions (best-effort; default: false)",
            },
            "auto_affordances": {
                "type": "boolean",
                "default": True,
                "description": "Auto-refresh affordances when act(ref/label) looks stale (URL mismatch or missing refs; default: true)",
            },
            "proof": {
                "type": "boolean",
                "default": True,
                "description": "Attach compact per-action proof (delta triage + page state) to avoid extra check calls",
            },
            "proof_screenshot": {
                "type": "string",
                "enum": ["none", "artifact"],
                "default": "artifact",
                "description": "How to capture screenshots for proof (default: store off-context as artifact)",
            },
            "screenshot_on_ambiguity": {
                "type": "boolean",
                "default": True,
                "description": "When proof is enabled, capture a screenshot if the action is ambiguous (default: true)",
            },
            "delta_report": {
                "type": "boolean",
                "default": True,
                "description": "Make report snapshots delta-only since the run start (default: true)",
            },
            "actions_output": {
                "type": "string",
                "enum": ["compact", "errors", "none"],
                "default": "compact",
                "description": "How much per-action output to return (default: compact)",
            },
            "screenshot_on_error": {
                "type": "boolean",
                "default": False,
                "description": "If the run fails, attach a screenshot (default: false)",
            },
            "report": {
                "type": "string",
                "enum": ["none", "observe", "audit", "triage", "diagnostics", "map", "graph"],
                "default": "observe",
                "description": "Attach one compact final report snapshot (default: observe)",
            },
            "report_limit": {
                "type": "integer",
                "default": 30,
                "description": "Limit for report=audit/triage/diagnostics (default: 30)",
            },
            "with_screenshot": {
                "type": "boolean",
                "default": False,
                "description": "Attach a final screenshot image to the result",
            },
        },
        # NOTE: Some MCP clients (including OpenCode) reject top-level anyOf/oneOf/allOf.
        # We validate presence of actions/steps in the handler instead.
        "additionalProperties": False,
    },
}
# ═══════════════════════════════════════════════════════════════════════════════
# RUNBOOK
# ═══════════════════════════════════════════════════════════════════════════════

RUNBOOK_TOOL: dict[str, Any] = {
    "name": "runbook",
    "description": """Runbooks: save and execute reusable step lists stored in agent memory.
USAGE:
- Save: runbook(action="save", key="runbook_login", steps=[...])
- Run: runbook(action="run", key="runbook_login", params={...}, run_args={...})
- List: runbook(action="list", limit=20)
- Get: runbook(action="get", key="runbook_login")
- Delete: runbook(action="delete", key="runbook_login")
""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["save", "run", "list", "get", "delete"],
                "default": "list",
                "description": "Runbook action",
            },
            "key": {"type": "string", "description": "Runbook key in agent memory"},
            "steps": {
                "type": "array",
                "description": "Runbook step list (for action='save')",
                "items": {"type": "object"},
            },
            "params": {"type": "object", "description": "Params for {{param:...}} placeholders (for action='run')"},
            "run_args": {
                "type": "object",
                "description": "Optional run(...) arguments (for action='run'); actions are provided by the runbook",
            },
            "goal": {"type": "string", "description": "Optional goal string (for action='run')"},
            "allow_sensitive": {
                "type": "boolean",
                "default": False,
                "description": "Allow sensitive keys / literals (NOT encrypted; use carefully)",
            },
            "include_sensitive": {
                "type": "boolean",
                "default": False,
                "description": "Include sensitive keys in list output (default: false)",
            },
            "limit": {
                "type": "integer",
                "default": 20,
                "description": "Limit for list, and preview size for get (default: 20)",
            },
        },
        "additionalProperties": False,
    },
}
# ═══════════════════════════════════════════════════════════════════════════════
# APP (High-level macros/adapters)
# ═══════════════════════════════════════════════════════════════════════════════

APP_TOOL: dict[str, Any] = {
    "name": "app",
    "description": """High-level app macros/adapters for complex web apps (Miro/Figma/etc.).

Use this when a site is *not* DOM-driven (canvas apps) and low-level click/drag would require
hundreds of tiny actions. This tool moves the loop into the server for speed + stability.
USAGE:
- Auto-detect app from current URL:
  app(op="diagram", params={...})

- Force a specific adapter:
  app(app="miro", op="diagram", params={...})

Common params (for diagram adapters):
- strategy: "auto" (paste-first in extension mode, then import fallback), "paste" (paste only), "import" (file chooser only)

Common ops:
- op="diagram": generate and insert a simple architecture diagram (SVG) via paste→drop→import fallbacks
- op="insert": insert user-provided payload (svg/text/files) with the same fast fallbacks

WITHIN run():
  run(actions=[
    {"tool":"app","args":{"app":"miro","op":"diagram","params":{"title":"...", "nodes":[...], "edges":[...]}}}
  ])

DRY RUN (planning / debugging):
  app(app="miro", op="diagram", params={...}, dry_run=true)
""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "app": {
                "type": "string",
                "default": "auto",
                "description": "Adapter name ('auto' to detect by URL)",
            },
            "op": {
                "type": "string",
                "description": "Operation name (adapter-specific), e.g. 'diagram'",
            },
            "params": {
                "type": "object",
                "description": "Operation parameters (adapter-specific)",
            },
            "dry_run": {
                "type": "boolean",
                "default": False,
                "description": "If true, return the planned steps without executing them",
            },
        },
        "required": ["op"],
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
- By stable handle: screenshot(ref="dom:123")  # or backendDOMNodeId=123

RESPONSE: Base64 PNG image""",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector to screenshot specific element",
            },
            "backendDOMNodeId": {
                "type": "integer",
                "description": "Stable element handle (from page(detail='ax'))",
            },
            "ref": {
                "type": "string",
                "description": "Stable element ref like 'dom:123' (from page(detail='ax'))",
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
            # Some MCP clients omit arguments entirely when no params are provided.
            "default": {},
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
                "fallback_http": {
                    "type": "boolean",
                    "default": False,
                    "description": "Fallback to http() on CORS/opaque errors (GET only; allowlist enforced).",
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "storage",
        "description": """Storage operations (localStorage / sessionStorage).
USAGE:
- List keys: storage(action="list", storage="local", limit=20)
- Get value (preview): storage(action="get", key="theme", reveal=true)
- Set one: storage(action="set", key="theme", value="dark")
- Set many: storage(action="set_many", items={"k1":"v1","k2":"v2"})
- Delete: storage(action="delete", key="theme")
- Clear: storage(action="clear")

NOTES:
- Safe-by-default: strict policy blocks mutation and sensitive value reveal.
- To store a revealed value off-context: storage(action="get", key="...", reveal=true, store=true)""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "set", "set_many", "delete", "clear"],
                    "default": "list",
                },
                "storage": {
                    "type": "string",
                    "enum": ["local", "session"],
                    "default": "local",
                    "description": "Storage backend",
                },
                "key": {"type": "string", "description": "Storage key (get/set/delete)"},
                "value": {
                    "description": "Value to set (set)",
                    "type": ["string", "number", "boolean", "object", "array", "null"],
                    "items": {},
                    "additionalProperties": True,
                },
                "items": {
                    "type": "object",
                    "description": "Key/value map for set_many",
                    "additionalProperties": True,
                },
                "offset": {"type": "integer", "default": 0},
                "limit": {"type": "integer", "default": 20},
                "max_chars": {"type": "integer", "default": 2000},
                "reveal": {
                    "type": "boolean",
                    "default": False,
                    "description": "Reveal value preview (unsafe; strict may block sensitive keys)",
                },
                "store": {
                    "type": "boolean",
                    "default": False,
                    "description": "Store revealed value off-context as an artifact (requires reveal=true)",
                },
            },
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
        "name": "download",
        "description": """Wait for a download to complete and optionally store it as an artifact.
USAGE:
- Store as artifact (default): download(timeout=30)
- Metadata only: download(store=false)

NOTES:
- Designed to be used after triggering a download (click).
- Keeps output cognitive-cheap: returns an artifact id + minimal metadata.""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "timeout": {
                    "type": "number",
                    "default": 30.0,
                    "description": "Seconds to wait for a new download (default: 30.0)",
                },
                "poll_interval": {
                    "type": "number",
                    "default": 0.2,
                    "description": "Polling interval seconds (default: 0.2)",
                },
                "stable_ms": {
                    "type": "integer",
                    "default": 500,
                    "description": "File size must be stable for N ms before considering it complete (default: 500)",
                },
                "store": {
                    "type": "boolean",
                    "default": True,
                    "description": "Store the downloaded file as an artifact (default: true)",
                },
                "sha256": {
                    "type": "boolean",
                    "default": True,
                    "description": "Compute sha256 for small downloads (default: true; may skip for large files)",
                },
                "sha256_max_bytes": {
                    "type": "integer",
                    "default": 209715200,
                    "description": "Max bytes to hash for sha256 (default: 200MB). Larger files skip hashing.",
                },
            },
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
                "timeout": {
                    "type": "number",
                    "default": 2,
                    "description": "Max seconds to wait for a dialog to appear when none is active",
                },
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
- Wait for DOMContentLoaded: wait(for="domcontentloaded")
- Wait for navigation: wait(for="navigation")
- Wait for network idle: wait(for="networkidle")

RESPONSE: {"waited_for": "element", "found": true, "duration_ms": 1500}""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "for": {
                    "type": "string",
                    "enum": ["element", "text", "navigation", "domcontentloaded", "networkidle", "load"],
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
        "description": """Browser control: lifecycle + policy + DOM.
USAGE:
- Check status: browser(action="status")
- Launch: browser(action="launch")
- Emergency recovery (CDP hung / dialog-brick): browser(action="recover")  # add hard=true to restart owned Chrome
- Get/set safety policy: browser(action="policy", mode="strict")  # or mode="permissive"
- Get DOM: browser(action="dom", selector="#content")
- Store DOM as artifact (no huge dump): browser(action="dom", store=true)
- Get element: browser(action="element", selector="#btn")
- Agent memory (safe KV): browser(action="memory", memory_action="set", key="token", value="...")
- Agent memory list: browser(action="memory", memory_action="list")
- Agent memory get (redacted by default): browser(action="memory", memory_action="get", key="token")
- Persist memory (non-sensitive): browser(action="memory", memory_action="save")
- Load memory (after restart): browser(action="memory", memory_action="load")
- Use memory in run without revealing: run(actions=[{type:{selector:"#pwd", text:"{{mem:token}}"}}], report="map")

DRILLDOWN:
- browser(action="artifact", artifact_action="get", id="...", offset=0, max_chars=4000)

RESPONSE (status):
{"running": true, "version": "Chrome/130.0", "port": 9222}""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "launch", "recover", "policy", "dom", "element", "artifact", "memory"],
                    "default": "status",
                },
                "hard": {
                    "type": "boolean",
                    "default": False,
                    "description": "Hard recovery (restart owned Chrome). If false, may still escalate to hard when CDP is unresponsive (action='recover')",
                },
                "timeout": {
                    "type": "number",
                    "default": 5.0,
                    "description": "Recovery timeout in seconds (action='recover')",
                },
                "mode": {
                    "type": "string",
                    "enum": ["permissive", "strict"],
                    "description": "Safety policy mode (for action='policy')",
                },
                "selector": {"type": "string", "description": "For dom/element actions"},
                "store": {
                    "type": "boolean",
                    "default": False,
                    "description": "Store full DOM off-context as an artifact (use with action='dom')",
                },
                "max_chars": {
                    "type": "integer",
                    "default": 50000,
                    "description": "Max DOM chars (action='dom') or max artifact slice chars (action='artifact', hard-capped to 4000)",
                },
                "artifact_action": {
                    "type": "string",
                    "enum": ["list", "get", "delete", "export"],
                    "default": "list",
                    "description": "Artifact action (for action='artifact')",
                },
                "id": {"type": "string", "description": "Artifact id (required for artifact_action='get'|'delete')"},
                "kind": {"type": "string", "description": "Filter by kind (artifact_action='list')"},
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Max items for artifact_action='list'",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "description": "Text offset for artifact_action='get' (chars)",
                },
                "name": {
                    "type": "string",
                    "description": "Export filename (optional, artifact_action='export')",
                },
                "overwrite": {
                    "type": "boolean",
                    "default": False,
                    "description": "Overwrite export destination if exists (artifact_action='export')",
                },
                # Agent memory (server-local, safe-by-default)
                "memory_action": {
                    "type": "string",
                    "enum": ["list", "get", "set", "delete", "clear", "save", "load"],
                    "default": "list",
                    "description": "Memory operation (requires action='memory')",
                },
                "key": {"type": "string", "description": "Memory key (get/set/delete)"},
                "prefix": {"type": "string", "description": "Key prefix filter (list/clear)"},
                "value": {
                    "description": "Memory value (set)",
                    "type": ["string", "number", "boolean", "object", "array", "null"],
                    # Some schema consumers require `items` for array even in union types.
                    "items": {},
                    # Allow arbitrary objects (JSON-like) by default.
                    "additionalProperties": True,
                },
                "reveal": {
                    "type": "boolean",
                    "default": False,
                    "description": "Reveal value on get (unsafe; blocked by strict policy for sensitive keys)",
                },
                "memory_max_chars": {
                    "type": "integer",
                    "default": 2000,
                    "description": "Max chars to return when reveal=true (memory get)",
                },
                "memory_max_bytes": {
                    "type": "integer",
                    "default": 20000,
                    "description": "Max stored bytes for set (memory set)",
                },
                "memory_max_keys": {
                    "type": "integer",
                    "default": 200,
                    "description": "Max keys for memory store (LRU-evicted)",
                },
                "persist": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, also write memory snapshot to disk (permissive only)",
                },
                "allow_sensitive": {
                    "type": "boolean",
                    "default": False,
                    "description": "Allow persisting/loading sensitive keys (NOT encrypted; use carefully)",
                },
                "replace": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, load replaces current memory (load only)",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "artifact",
        "description": """Artifact store for high-fidelity payloads (keeps context window small).
USAGE:
- List: artifact(action="list", limit=20)
- Get text slice: artifact(action="get", id="...", offset=0, max_chars=4000)
- Delete: artifact(action="delete", id="...")
- Export to outbox: artifact(action="export", id="...", name="optional.ext", overwrite=false)

NOTE:
- Large payloads are produced by other tools (e.g., browser(action="dom", store=true)).""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "delete", "export"],
                    "default": "list",
                    "description": "Artifact action",
                },
                "id": {"type": "string", "description": "Artifact id (required for get/delete/export)"},
                "kind": {"type": "string", "description": "Filter by kind (list only)"},
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Max items for list",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "description": "Text offset for get (chars)",
                },
                "max_chars": {
                    "type": "integer",
                    "default": 4000,
                    "description": "Max returned chars for get",
                },
                "name": {"type": "string", "description": "Export filename (optional, export only)"},
                "overwrite": {
                    "type": "boolean",
                    "default": False,
                    "description": "Overwrite export destination if exists (export only)",
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
    EXTRACT_TOOL,
    RUN_TOOL,
    FLOW_TOOL,
    RUNBOOK_TOOL,
    APP_TOOL,
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

# Tool count: 27 (down from 54)
