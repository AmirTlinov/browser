"""
MCP tool definitions.

Each tool definition contains:
- name: Tool identifier
- description: AI-friendly description with usage examples
- inputSchema: JSON Schema for tool arguments
"""

from __future__ import annotations

from typing import Any

# ═══════════════════════════════════════════════════════════════════════════════
# SMART TOOLS - High-level AI-friendly operations
# ═══════════════════════════════════════════════════════════════════════════════

SMART_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "analyze_page",
        "description": """PRIMARY TOOL: Analyze the current page and return a structured summary.

ALWAYS call this tool FIRST when you need to understand what's on a page.

OVERVIEW MODE (default, no params):
Returns compact summary with counts and hints - minimal context usage.
- Page metadata (URL, title, pageType)
- Element counts (forms, links, buttons, inputs)
- Preview samples (first few of each type)
- Hints showing how to get more details

DETAIL MODES (use detail parameter):
- detail="forms": List all forms with field counts
- detail="forms" + form_index=N: Full details of form N with all fields
- detail="links" + offset/limit: Paginated list of links
- detail="buttons": All buttons on page
- detail="inputs": Standalone inputs (not in forms)
- detail="content" + offset/limit: Main page content (paginated)

Examples:
- analyze_page() → overview with counts and hints
- analyze_page(detail="forms", form_index=0) → form 0 with all fields
- analyze_page(detail="links", offset=0, limit=20) → first 20 links""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "detail": {
                    "type": "string",
                    "enum": ["forms", "links", "buttons", "inputs", "content"],
                    "description": "Section to get details for. Omit for overview.",
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
                "form_index": {
                    "type": "integer",
                    "description": "Specific form index when detail='forms'",
                },
                "include_content": {
                    "type": "boolean",
                    "description": "Include content preview in overview (default: false)",
                    "default": False,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "click_element",
        "description": """SMART CLICK: Click elements using natural language, not CSS selectors.

PREFERRED over browser_click. Automatically finds elements by:
- text: Visible text ("Sign In", "Submit", "Next")
- role: Element type ("button", "link", "checkbox")
- near_text: Element near label text

Examples:
- click_element(text="Sign In") - clicks any element with "Sign In" text
- click_element(text="Submit", role="button") - clicks Submit button
- click_element(near_text="Remember me", role="checkbox") - clicks checkbox near text""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Visible text of the element to click"},
                "role": {
                    "type": "string",
                    "enum": ["button", "link", "checkbox", "radio", "tab", "menuitem"],
                    "description": "Element role to narrow search",
                },
                "near_text": {
                    "type": "string",
                    "description": "Find element near this text (for unlabeled elements)",
                },
                "index": {
                    "type": "integer",
                    "description": "If multiple matches, which one (0=first, -1=last)",
                    "default": 0,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "fill_form",
        "description": """SMART FORM: Fill entire form in one operation.

PREFERRED over multiple browser_type calls. Intelligently matches fields by:
- Field name/id
- Label text
- Placeholder text
- Aria-label

Example:
fill_form({
  "email": "user@example.com",
  "password": "<YOUR_PASSWORD>",
  "Remember me": true
}, submit=True)

For checkboxes/radios, use true/false as value.""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "description": "Field names/labels mapped to values",
                    "additionalProperties": True,
                },
                "form_index": {
                    "type": "integer",
                    "description": "Which form (0=first)",
                    "default": 0,
                },
                "submit": {
                    "type": "boolean",
                    "description": "Submit after filling",
                    "default": False,
                },
            },
            "required": ["data"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_page",
        "description": """SMART SEARCH: Search on any page with search functionality.

Automatically finds the search input and submits.
Works on Google, e-commerce sites, documentation, etc.

Example: search_page(query="Claude AI tutorial")""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search text"},
                "submit": {
                    "type": "boolean",
                    "description": "Submit search (default: true)",
                    "default": True,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "extract_content",
        "description": """SMART EXTRACT: Get structured content from page with pagination.

Use instead of browser_get_dom when you need specific data.

OVERVIEW MODE (default):
Returns content structure summary with counts and hints.

DETAIL MODES with pagination:
- content_type="main" + offset/limit: Main text paragraphs
- content_type="table": List of tables with metadata
- content_type="table" + table_index=N + offset/limit: Rows of table N
- content_type="links" + offset/limit: All links
- content_type="headings": Document outline (h1-h6)
- content_type="images" + offset/limit: Images with metadata

Examples:
- extract_content() → overview with counts
- extract_content(content_type="main", offset=0, limit=10) → first 10 paragraphs
- extract_content(content_type="table", table_index=0, limit=20) → first 20 rows of table 0""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
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
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "wait_for",
        "description": """SMART WAIT: Wait for condition before proceeding.

Use after actions that trigger page changes.

condition options:
- "navigation": URL changes (after click on link)
- "load": Page fully loaded
- "text": Specific text appears
- "element": Element appears (requires selector)
- "network_idle": No network activity""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "condition": {
                    "type": "string",
                    "enum": ["navigation", "load", "text", "element", "network_idle"],
                    "description": "What to wait for",
                },
                "timeout": {
                    "type": "number",
                    "description": "Max wait seconds (default: 10)",
                    "default": 10,
                },
                "text": {
                    "type": "string",
                    "description": "Text to wait for (when condition='text')",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector (when condition='element')",
                },
            },
            "required": ["condition"],
            "additionalProperties": False,
        },
    },
    {
        "name": "execute_workflow",
        "description": """BATCH OPERATIONS: Execute multiple actions in sequence.

Efficient for multi-step tasks. Each step is:
{action: "...", ...params}

Supported actions:
- navigate: {action: "navigate", url: "..."}
- click: {action: "click", text: "..."} or {action: "click", selector: "..."}
- type: {action: "type", selector: "...", text: "..."}
- fill: {action: "fill", data: {...}, submit: bool}
- wait: {action: "wait", condition: "...", timeout: N}
- screenshot: {action: "screenshot"}

Example: Login workflow
[
  {action: "navigate", url: "https://site.com/login"},
  {action: "fill", data: {email: "user@ex.com", password: "<YOUR_PASSWORD>"}, submit: true},
  {action: "wait", condition: "navigation"},
  {action: "screenshot"}
]""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "description": "Array of action steps",
                    "items": {"type": "object"},
                },
                "include_screenshots": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include screenshot base64 data in results (default: False)",
                },
                "compact_results": {
                    "type": "boolean",
                    "default": True,
                    "description": "Return compact results without redundant fields (default: True)",
                },
            },
            "required": ["steps"],
            "additionalProperties": False,
        },
    },
    {
        "name": "upload_file",
        "description": """FILE UPLOAD: Upload file(s) to file input elements.

Uses CDP for reliable file upload, works with hidden inputs too.

Example: upload_file(file_paths=["/path/to/image.png"])""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Absolute paths to files to upload",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector for file input (auto-detected if omitted)",
                },
            },
            "required": ["file_paths"],
            "additionalProperties": False,
        },
    },
    {
        "name": "handle_dialog",
        "description": """DIALOG HANDLER: Handle JavaScript alert/confirm/prompt dialogs.

Call when a dialog is blocking the page.

Example: handle_dialog(accept=True) or handle_dialog(accept=False, prompt_text="answer")""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "accept": {
                    "type": "boolean",
                    "description": "True=OK/Accept, False=Cancel/Dismiss",
                    "default": True,
                },
                "prompt_text": {
                    "type": "string",
                    "description": "Text to enter for prompt() dialogs",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_tabs",
        "description": """TAB LIST: List all open browser tabs.

Returns tab IDs, URLs and titles. Use switch_tab() to change active tab.

Supports pagination (offset/limit) and URL filtering for many tabs.""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "description": "Starting index for paginated results (default: 0)",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Maximum tabs to return (default: 20, max: 50)",
                },
                "url_filter": {
                    "type": "string",
                    "description": "Filter tabs by URL substring (optional)",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "switch_tab",
        "description": """TAB SWITCH: Switch to a different browser tab.

Provide either tab_id (from list_tabs) or url_pattern to match.""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "tab_id": {"type": "string", "description": "Target ID from list_tabs()"},
                "url_pattern": {"type": "string", "description": "URL substring to match"},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "new_tab",
        "description": """NEW TAB: Open a new browser tab.

Returns the new tab's ID.""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to open (default: about:blank)",
                    "default": "about:blank",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "close_tab",
        "description": """CLOSE TAB: Close a browser tab.

Closes current tab if no tab_id provided.""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "tab_id": {
                    "type": "string",
                    "description": "Target ID to close (current tab if omitted)",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "generate_totp",
        "description": """2FA CODE: Generate TOTP code for two-factor authentication.

Provide the Base32 secret from your authenticator app setup.

Example: generate_totp(secret="JBSWY3DPEHPK3PXP")""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "secret": {"type": "string", "description": "Base32-encoded TOTP secret"},
                "digits": {
                    "type": "integer",
                    "description": "Number of digits (default: 6)",
                    "default": 6,
                },
                "interval": {
                    "type": "integer",
                    "description": "Time interval in seconds (default: 30)",
                    "default": 30,
                },
            },
            "required": ["secret"],
            "additionalProperties": False,
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# CAPTCHA TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

CAPTCHA_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "analyze_captcha",
        "description": """CAPTCHA DETECTOR: Auto-detect CAPTCHA type on the current page.

Returns detected CAPTCHA info:
- type: recaptcha_v2_checkbox, recaptcha_v2_image, hcaptcha, turnstile, geetest, image_text, image_grid, unknown
- selector: CSS selector of the CAPTCHA element
- state: ready, solving, solved, expired
- clickable_areas: list of {id, name, selector} for checkbox/buttons

ALWAYS call this FIRST before interacting with any CAPTCHA.""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "force_grid_size": {
                    "type": "integer",
                    "default": 0,
                    "description": "Force grid size (3 for 3x3, 4 for 4x4). Default: 0 = auto-detect.",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_captcha_screenshot",
        "description": """CAPTCHA SCREENSHOT: Get screenshot of CAPTCHA with numbered grid overlay.

Returns base64 PNG image with numbered blocks (1-16 for 4x4 grid, 1-9 for 3x3).
Each block is labeled with a number for easy reference.

Use this to SEE the CAPTCHA challenge, then use click_captcha_blocks to click correct blocks.

Parameters:
- grid_size: Number of rows/columns (3 for 3x3, 4 for 4x4). Default: auto-detect.""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "grid_size": {
                    "type": "integer",
                    "description": "Grid size (3 for 3x3, 4 for 4x4). Default: auto-detect.",
                    "default": 0,
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "click_captcha_blocks",
        "description": """CAPTCHA CLICK BLOCKS: Click specific numbered blocks in a CAPTCHA grid.

After viewing get_captcha_screenshot, use this to click the correct blocks.
Block numbers start from 1 (top-left) and go left-to-right, top-to-bottom.

For a 3x3 grid:     For a 4x4 grid:
[1] [2] [3]         [1]  [2]  [3]  [4]
[4] [5] [6]         [5]  [6]  [7]  [8]
[7] [8] [9]         [9]  [10] [11] [12]
                    [13] [14] [15] [16]

Example: click_captcha_blocks(blocks=[1, 4, 7, 9]) - clicks blocks 1, 4, 7, and 9.""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "blocks": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of block numbers to click (1-based index)",
                },
                "grid_size": {
                    "type": "integer",
                    "default": 0,
                    "description": "Force grid size (3 for 3x3, 4 for 4x4). Default: 0 = auto-detect.",
                },
            },
            "required": ["blocks"],
            "additionalProperties": False,
        },
    },
    {
        "name": "click_captcha_area",
        "description": """CAPTCHA CLICK AREA: Click a specific area of the CAPTCHA (checkbox, button, etc.).

Use analyze_captcha first to get the list of clickable_areas with their IDs.
Then use this tool to click a specific area by its ID.

Example: click_captcha_area(area_id=0) - clicks the first clickable area (usually checkbox).""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "area_id": {
                    "type": "integer",
                    "description": "ID of the area to click (from analyze_captcha clickable_areas)",
                }
            },
            "required": ["area_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "submit_captcha",
        "description": """CAPTCHA SUBMIT: Find and click the verify/submit button for the CAPTCHA.

Automatically finds the verify button (e.g., "Verify", "Submit", "I'm not a robot") and clicks it.
Use this after selecting all correct images/blocks.""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# NETWORK TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

NETWORK_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "http_get",
        "description": "Fetches an URL over HTTP(S) with optional allowlist enforcement.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL to fetch"}},
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_fetch",
        "description": "Fetch URL from page context. Subject to CORS. Navigate to target domain first for cross-origin requests.",
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
                "headers": {
                    "type": "object",
                    "description": "Request headers as key-value pairs",
                },
                "body": {"type": "string", "description": "Request body (for POST/PUT/PATCH)"},
                "credentials": {
                    "type": "string",
                    "enum": ["include", "same-origin", "omit"],
                    "default": "include",
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "launch_browser",
        "description": "Ensures Chrome is running with the configured remote debugging port/profile.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "cdp_version",
        "description": "Starts Chrome if needed and returns /json/version metadata.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "start": {
                    "type": "boolean",
                    "description": "Launch Chrome when CDP is not listening (default: true)",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "js_eval",
        "description": "Evaluates a JavaScript expression in CDP Runtime on the active page.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "JavaScript expression"}
            },
            "required": ["expression"],
            "additionalProperties": False,
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# COOKIE TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

COOKIE_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "browser_set_cookie",
        "description": "Set a browser cookie via CDP Network.setCookie. Works on the current page domain or specified domain.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Cookie name"},
                "value": {"type": "string", "description": "Cookie value"},
                "domain": {"type": "string", "description": "Cookie domain (e.g., '.example.com')"},
                "path": {"type": "string", "description": "Cookie path (default: '/')", "default": "/"},
                "secure": {"type": "boolean", "description": "HTTPS only", "default": False},
                "httpOnly": {
                    "type": "boolean",
                    "description": "HTTP only (not accessible via JS)",
                    "default": False,
                },
                "sameSite": {
                    "type": "string",
                    "enum": ["Strict", "Lax", "None"],
                    "default": "Lax",
                },
                "expires": {
                    "type": "number",
                    "description": "Expiration timestamp in seconds since epoch",
                },
            },
            "required": ["name", "value", "domain"],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_set_cookies",
        "description": "Set multiple cookies at once via CDP.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "cookies": {
                    "type": "array",
                    "description": "Array of cookie objects",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "value": {"type": "string"},
                            "domain": {"type": "string"},
                            "path": {"type": "string"},
                            "secure": {"type": "boolean"},
                            "httpOnly": {"type": "boolean"},
                            "sameSite": {"type": "string"},
                            "expires": {"type": "number"},
                        },
                        "required": ["name", "value", "domain"],
                    },
                }
            },
            "required": ["cookies"],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_get_cookies",
        "description": """Get cookies with pagination and filtering.

Returns paginated list of cookies with total count and navigation hints.

Examples:
- browser_get_cookies() → first 20 cookies with total count
- browser_get_cookies(offset=20, limit=20) → next 20 cookies
- browser_get_cookies(name_filter="session") → filter by name""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of URLs to get cookies for.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Starting index for paginated results (default: 0)",
                    "default": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max cookies to return (default: 20, max: 100)",
                    "default": 20,
                },
                "name_filter": {
                    "type": "string",
                    "description": "Filter cookies by name substring",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_delete_cookie",
        "description": "Delete a cookie by name and optionally domain/path.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Cookie name to delete"},
                "domain": {"type": "string", "description": "Cookie domain"},
                "path": {"type": "string", "description": "Cookie path"},
                "url": {"type": "string", "description": "URL to match cookie"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# NAVIGATION TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

NAVIGATION_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "browser_navigate",
        "description": "Navigate to a URL in the active browser tab.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to navigate to"},
                "wait_load": {
                    "type": "boolean",
                    "description": "Wait for page load (default: true)",
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_back",
        "description": "Navigate back in browser history.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_forward",
        "description": "Navigate forward in browser history.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_reload",
        "description": "Reload the current page.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "ignore_cache": {
                    "type": "boolean",
                    "description": "Bypass cache (default: false)",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# DOM TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

DOM_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "screenshot",
        "description": "Takes a screenshot of the current page via CDP and returns base64 PNG.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Optional URL to navigate to first"}
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "dump_dom",
        "description": """Uses Chrome to render a page and return its DOM HTML.

IMPORTANT: Consider using browser_navigate(url) + analyze_page() instead -
they return structured data optimized for AI context.

Returns HTML with automatic size limiting (default 50KB, max 200KB).""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to render"},
                "max_chars": {
                    "type": "integer",
                    "default": 50000,
                    "description": "Maximum HTML characters (default: 50000, max: 200000)",
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_get_dom",
        "description": """Get DOM HTML of the current page or a specific element.

IMPORTANT: Consider using analyze_page() or extract_content() instead -
they return structured data optimized for AI context.

Returns HTML with automatic size limiting (default 50KB, max 200KB).
Use selector to get specific element's HTML for smaller response.""",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector (optional, returns full page if omitted)",
                },
                "max_chars": {
                    "type": "integer",
                    "default": 50000,
                    "description": "Maximum HTML characters (default: 50000, max: 200000)",
                },
                "include_metadata": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include size metadata and hints (default: true)",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_get_element",
        "description": "Get detailed information about an element (bounds, attributes, text).",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {"selector": {"type": "string", "description": "CSS selector"}},
            "required": ["selector"],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_get_page_info",
        "description": "Get current page information (URL, title, scroll position, viewport size).",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# INPUT TOOLS (Click, Mouse, Keyboard, Scroll, Form, Window)
# ═══════════════════════════════════════════════════════════════════════════════

INPUT_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    # Click
    {
        "name": "browser_click",
        "description": "Click an element by CSS selector.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of element to click"}
            },
            "required": ["selector"],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_click_pixel",
        "description": "Click at specific pixel coordinates.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "X coordinate"},
                "y": {"type": "number", "description": "Y coordinate"},
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "description": "Mouse button (default: left)",
                },
            },
            "required": ["x", "y"],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_double_click",
        "description": "Double-click at specific pixel coordinates.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "X coordinate"},
                "y": {"type": "number", "description": "Y coordinate"},
            },
            "required": ["x", "y"],
            "additionalProperties": False,
        },
    },
    # Mouse
    {
        "name": "browser_move_mouse",
        "description": "Move mouse to specific coordinates.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "X coordinate"},
                "y": {"type": "number", "description": "Y coordinate"},
            },
            "required": ["x", "y"],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_hover",
        "description": "Hover over an element (move mouse to its center).",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of element to hover"}
            },
            "required": ["selector"],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_drag",
        "description": "Drag from one point to another (drag & drop).",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "from_x": {"type": "number", "description": "Starting X coordinate"},
                "from_y": {"type": "number", "description": "Starting Y coordinate"},
                "to_x": {"type": "number", "description": "Ending X coordinate"},
                "to_y": {"type": "number", "description": "Ending Y coordinate"},
                "steps": {
                    "type": "integer",
                    "description": "Number of intermediate steps (default: 10)",
                },
            },
            "required": ["from_x", "from_y", "to_x", "to_y"],
            "additionalProperties": False,
        },
    },
    # Keyboard
    {
        "name": "browser_type",
        "description": "Type text into an input element.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of input element"},
                "text": {"type": "string", "description": "Text to type"},
                "clear": {
                    "type": "boolean",
                    "description": "Clear existing value first (default: true)",
                },
            },
            "required": ["selector", "text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_press_key",
        "description": "Press a keyboard key (Enter, Tab, Escape, ArrowUp, etc.).",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Key to press (e.g., Enter, Tab, Escape, ArrowUp, a, A)",
                },
                "modifiers": {
                    "type": "integer",
                    "description": "Modifier keys bitmask: 1=Alt, 2=Ctrl, 4=Meta, 8=Shift (default: 0)",
                },
            },
            "required": ["key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_type_text",
        "description": "Type text using keyboard events (for focused element).",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text to type"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    # Scroll
    {
        "name": "browser_scroll",
        "description": "Scroll the page by delta amounts.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "delta_x": {"type": "number", "description": "Horizontal scroll delta (pixels)"},
                "delta_y": {
                    "type": "number",
                    "description": "Vertical scroll delta (pixels, positive=down)",
                },
            },
            "required": ["delta_y"],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_scroll_down",
        "description": "Scroll down by a specified amount.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "Pixels to scroll (default: 300)"}
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_scroll_up",
        "description": "Scroll up by a specified amount.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "Pixels to scroll (default: 300)"}
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_scroll_to_element",
        "description": "Scroll an element into view.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of element to scroll to"}
            },
            "required": ["selector"],
            "additionalProperties": False,
        },
    },
    # Form
    {
        "name": "browser_select_option",
        "description": "Select an option in a <select> dropdown.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of select element"},
                "value": {"type": "string", "description": "Value, text, or index to select"},
                "by": {
                    "type": "string",
                    "enum": ["value", "text", "index"],
                    "description": "Selection method (default: value)",
                },
            },
            "required": ["selector", "value"],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_focus",
        "description": "Focus an element.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of element to focus"}
            },
            "required": ["selector"],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_clear_input",
        "description": "Clear an input element's value.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of input element"}
            },
            "required": ["selector"],
            "additionalProperties": False,
        },
    },
    # Window
    {
        "name": "browser_resize_viewport",
        "description": "Resize the browser viewport (content area).",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "width": {"type": "integer", "description": "Viewport width in pixels"},
                "height": {"type": "integer", "description": "Viewport height in pixels"},
            },
            "required": ["width", "height"],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_resize_window",
        "description": "Resize the browser window.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "width": {"type": "integer", "description": "Window width in pixels"},
                "height": {"type": "integer", "description": "Window height in pixels"},
            },
            "required": ["width", "height"],
            "additionalProperties": False,
        },
    },
    {
        "name": "browser_wait_for_element",
        "description": "Wait for an element to appear in the DOM.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of element to wait for"},
                "timeout": {
                    "type": "number",
                    "description": "Maximum wait time in seconds (default: 10)",
                },
            },
            "required": ["selector"],
            "additionalProperties": False,
        },
    },
]


def get_all_tool_definitions() -> list[dict[str, Any]]:
    """Get all tool definitions combined."""
    return [
        *SMART_TOOL_DEFINITIONS,
        *CAPTCHA_TOOL_DEFINITIONS,
        *NETWORK_TOOL_DEFINITIONS,
        *COOKIE_TOOL_DEFINITIONS,
        *NAVIGATION_TOOL_DEFINITIONS,
        *DOM_TOOL_DEFINITIONS,
        *INPUT_TOOL_DEFINITIONS,
    ]
