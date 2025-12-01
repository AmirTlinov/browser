from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

from . import smart_tools
from .config import BrowserConfig
from .http_client import HttpClientError, http_get
from .launcher import BrowserLauncher

SUPPORTED_PROTOCOL_VERSIONS = ["0.1.0", "2025-06-18", "2024-11-05"]
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[1]
DEFAULT_PROTOCOL_VERSION = LATEST_PROTOCOL_VERSION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("mcp.browser")


def _write_message(payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False)
    line = (data + "\n").encode()
    if dump_path := os.environ.get("MCP_DUMP_FRAMES"):
        with open(dump_path, "ab") as fp:
            fp.write(b"--out--\n")
            fp.write(line)
    sys.stdout.buffer.write(line)
    sys.stdout.buffer.flush()


def _read_message() -> dict[str, Any] | None:
    line = sys.stdin.buffer.readline()
    if not line:
        return None
    # tolerate CRLF
    line = line.strip()
    if not line:
        return None
    msg = json.loads(line.decode())
    if os.environ.get("MCP_TRACE"):
        logger.info("recv %s", msg)
    if dump_path := os.environ.get("MCP_DUMP_FRAMES"):
        with open(dump_path, "ab") as fp:
            fp.write(b"--in--\n")
            fp.write(line + b"\n")
    return msg


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        # ═══════════════════════════════════════════════════════════════════════
        # SMART TOOLS (Recommended for AI agents)
        # These high-level tools are cognitively optimized for LLM usage.
        # Use these FIRST before falling back to low-level browser_* tools.
        # ═══════════════════════════════════════════════════════════════════════
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
                        "description": "Section to get details for. Omit for overview."
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Starting index for paginated results (default: 0)",
                        "default": 0
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max items to return (default: 10, max: 50)",
                        "default": 10
                    },
                    "form_index": {
                        "type": "integer",
                        "description": "Specific form index when detail='forms'"
                    },
                    "include_content": {
                        "type": "boolean",
                        "description": "Include content preview in overview (default: false)",
                        "default": False
                    }
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
                        "description": "Element role to narrow search"
                    },
                    "near_text": {"type": "string", "description": "Find element near this text (for unlabeled elements)"},
                    "index": {"type": "integer", "description": "If multiple matches, which one (0=first, -1=last)", "default": 0}
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
  "password": "secret123",
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
                        "additionalProperties": True
                    },
                    "form_index": {"type": "integer", "description": "Which form (0=first)", "default": 0},
                    "submit": {"type": "boolean", "description": "Submit after filling", "default": False}
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
                    "submit": {"type": "boolean", "description": "Submit search (default: true)", "default": True}
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
                        "default": "overview"
                    },
                    "selector": {"type": "string", "description": "Optional CSS selector to limit scope"},
                    "offset": {
                        "type": "integer",
                        "description": "Starting index for paginated results (default: 0)",
                        "default": 0
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max items to return (default: 10, max: 50)",
                        "default": 10
                    },
                    "table_index": {
                        "type": "integer",
                        "description": "Specific table index when content_type='table'"
                    }
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
                        "description": "What to wait for"
                    },
                    "timeout": {"type": "number", "description": "Max wait seconds (default: 10)", "default": 10},
                    "text": {"type": "string", "description": "Text to wait for (when condition='text')"},
                    "selector": {"type": "string", "description": "CSS selector (when condition='element')"}
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
  {action: "fill", data: {email: "user@ex.com", password: "123"}, submit: true},
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
                        "items": {"type": "object"}
                    }
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
                        "description": "Absolute paths to files to upload"
                    },
                    "selector": {"type": "string", "description": "CSS selector for file input (auto-detected if omitted)"}
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
                    "accept": {"type": "boolean", "description": "True=OK/Accept, False=Cancel/Dismiss", "default": True},
                    "prompt_text": {"type": "string", "description": "Text to enter for prompt() dialogs"}
                },
                "required": [],
                "additionalProperties": False,
            },
        },
        {
            "name": "list_tabs",
            "description": """TAB LIST: List all open browser tabs.

Returns tab IDs, URLs and titles. Use switch_tab() to change active tab.""",
            "inputSchema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {},
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
                    "url_pattern": {"type": "string", "description": "URL substring to match"}
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
                    "url": {"type": "string", "description": "URL to open (default: about:blank)", "default": "about:blank"}
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
                    "tab_id": {"type": "string", "description": "Target ID to close (current tab if omitted)"}
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
                    "digits": {"type": "integer", "description": "Number of digits (default: 6)", "default": 6},
                    "interval": {"type": "integer", "description": "Time interval in seconds (default: 30)", "default": 30}
                },
                "required": ["secret"],
                "additionalProperties": False,
            },
        },
        # ─────────────────────────────────────────────────────────────────────
        # CAPTCHA Tools
        # ─────────────────────────────────────────────────────────────────────
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
                        "description": "Force grid size (3 for 3x3, 4 for 4x4). Default: 0 = auto-detect. Use when auto-detection fails for mosaic-style 4x4 CAPTCHAs.",
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
                        "description": "Grid size (3 for 3x3, 4 for 4x4). Default: auto-detect from CAPTCHA type.",
                        "default": 0
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
                        "description": "List of block numbers to click (1-based index)"
                    },
                    "grid_size": {
                        "type": "integer",
                        "default": 0,
                        "description": "Force grid size (3 for 3x3, 4 for 4x4). Default: 0 = auto-detect. Use when auto-detection fails."
                    }
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
                        "description": "ID of the area to click (from analyze_captcha clickable_areas)"
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
        # ─────────────────────────────────────────────────────────────────────
        # Basic tools
        # ─────────────────────────────────────────────────────────────────────
        {
            "name": "http_get",
            "description": "Fetches an URL over HTTP(S) with optional allowlist enforcement.",
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
                    "httpOnly": {"type": "boolean", "description": "HTTP only (not accessible via JS)", "default": False},
                    "sameSite": {"type": "string", "enum": ["Strict", "Lax", "None"], "default": "Lax"},
                    "expires": {"type": "number", "description": "Expiration timestamp in seconds since epoch"},
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
                        "description": "Array of cookie objects with name, value, domain, and optional path/secure/httpOnly/sameSite/expires",
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
                    },
                },
                "required": ["cookies"],
                "additionalProperties": False,
            },
        },
        {
            "name": "browser_get_cookies",
            "description": "Get all cookies or cookies for specific URLs via CDP.",
            "inputSchema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of URLs to get cookies for. If empty, returns all cookies.",
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
        {
            "name": "browser_fetch",
            "description": "Fetch URL from page context. Subject to CORS. Navigate to target domain first for cross-origin requests.",
            "inputSchema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                    "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"], "default": "GET"},
                    "headers": {"type": "object", "description": "Request headers as key-value pairs"},
                    "body": {"type": "string", "description": "Request body (for POST/PUT/PATCH)"},
                    "credentials": {"type": "string", "enum": ["include", "same-origin", "omit"], "default": "include"},
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
                    "expression": {"type": "string", "description": "JavaScript expression"},
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
        },
        # ─────────────────────────────────────────────────────────────────────
        # Navigation tools
        # ─────────────────────────────────────────────────────────────────────
        {
            "name": "browser_navigate",
            "description": "Navigate to a URL in the active browser tab.",
            "inputSchema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to navigate to"},
                    "wait_load": {"type": "boolean", "description": "Wait for page load (default: true)"},
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
                    "ignore_cache": {"type": "boolean", "description": "Bypass cache (default: false)"},
                },
                "required": [],
                "additionalProperties": False,
            },
        },
        # ─────────────────────────────────────────────────────────────────────
        # Screenshot & DOM tools
        # ─────────────────────────────────────────────────────────────────────
        {
            "name": "screenshot",
            "description": "Takes a screenshot of the current page via CDP and returns base64 PNG.",
            "inputSchema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Optional URL to navigate to first"},
                },
                "required": [],
                "additionalProperties": False,
            },
        },
        {
            "name": "dump_dom",
            "description": "Uses Chrome to render a page and return its DOM HTML.",
            "inputSchema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to render"},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
        {
            "name": "browser_get_dom",
            "description": "Get DOM HTML of the current page or a specific element.",
            "inputSchema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector (optional, returns full page if omitted)"},
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
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector"},
                },
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
        # ─────────────────────────────────────────────────────────────────────
        # Click tools
        # ─────────────────────────────────────────────────────────────────────
        {
            "name": "browser_click",
            "description": "Click an element by CSS selector.",
            "inputSchema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of element to click"},
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
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "Mouse button (default: left)"},
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
        # ─────────────────────────────────────────────────────────────────────
        # Mouse tools
        # ─────────────────────────────────────────────────────────────────────
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
                    "selector": {"type": "string", "description": "CSS selector of element to hover"},
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
                    "steps": {"type": "integer", "description": "Number of intermediate steps (default: 10)"},
                },
                "required": ["from_x", "from_y", "to_x", "to_y"],
                "additionalProperties": False,
            },
        },
        # ─────────────────────────────────────────────────────────────────────
        # Keyboard tools
        # ─────────────────────────────────────────────────────────────────────
        {
            "name": "browser_type",
            "description": "Type text into an input element.",
            "inputSchema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of input element"},
                    "text": {"type": "string", "description": "Text to type"},
                    "clear": {"type": "boolean", "description": "Clear existing value first (default: true)"},
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
                    "key": {"type": "string", "description": "Key to press (e.g., Enter, Tab, Escape, ArrowUp, a, A)"},
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
                "properties": {
                    "text": {"type": "string", "description": "Text to type"},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
        # ─────────────────────────────────────────────────────────────────────
        # Scroll tools
        # ─────────────────────────────────────────────────────────────────────
        {
            "name": "browser_scroll",
            "description": "Scroll the page by delta amounts.",
            "inputSchema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {
                    "delta_x": {"type": "number", "description": "Horizontal scroll delta (pixels)"},
                    "delta_y": {"type": "number", "description": "Vertical scroll delta (pixels, positive=down)"},
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
                    "amount": {"type": "number", "description": "Pixels to scroll (default: 300)"},
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
                    "amount": {"type": "number", "description": "Pixels to scroll (default: 300)"},
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
                    "selector": {"type": "string", "description": "CSS selector of element to scroll to"},
                },
                "required": ["selector"],
                "additionalProperties": False,
            },
        },
        # ─────────────────────────────────────────────────────────────────────
        # Form tools
        # ─────────────────────────────────────────────────────────────────────
        {
            "name": "browser_select_option",
            "description": "Select an option in a <select> dropdown.",
            "inputSchema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of select element"},
                    "value": {"type": "string", "description": "Value, text, or index to select"},
                    "by": {"type": "string", "enum": ["value", "text", "index"], "description": "Selection method (default: value)"},
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
                    "selector": {"type": "string", "description": "CSS selector of element to focus"},
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
                    "selector": {"type": "string", "description": "CSS selector of input element"},
                },
                "required": ["selector"],
                "additionalProperties": False,
            },
        },
        # ─────────────────────────────────────────────────────────────────────
        # Window tools
        # ─────────────────────────────────────────────────────────────────────
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
        # ─────────────────────────────────────────────────────────────────────
        # Wait tools
        # ─────────────────────────────────────────────────────────────────────
        {
            "name": "browser_wait_for_element",
            "description": "Wait for an element to appear in the DOM.",
            "inputSchema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of element to wait for"},
                    "timeout": {"type": "number", "description": "Maximum wait time in seconds (default: 10)"},
                },
                "required": ["selector"],
                "additionalProperties": False,
            },
        },
    ]


class McpServer:
    def __init__(self) -> None:
        self.config = BrowserConfig.from_env()
        self.launcher = BrowserLauncher(self.config)

    def _select_protocol(self, params: dict[str, Any]) -> str:
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS:
            return requested
        return DEFAULT_PROTOCOL_VERSION

    def handle_initialize(self, request_id: Any, params: dict[str, Any] | None = None) -> None:
        protocol = self._select_protocol(params or {})
        _write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": protocol,
                    "serverInfo": {"name": "antigravity-browser", "version": "0.1.0"},
                    "capabilities": {
                        "logging": {},
                        "prompts": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                        "tools": {"listChanged": False},
                    },
                    "instructions": "",
                },
            }
        )

    def handle_list_tools(self, request_id: Any) -> None:
        _write_message({"jsonrpc": "2.0", "id": request_id, "result": {"tools": _tool_definitions()}})

    def _result_content(self, text: str) -> dict[str, Any]:
        return {"type": "text", "text": text}

    def _log_call(self, name: str, arguments: dict[str, Any]) -> None:
        safe_args = dict(arguments)
        if "url" in safe_args and isinstance(safe_args["url"], str):
            safe_args["url"] = safe_args["url"].split("?")[0]
        logger.info("tool=%s args=%s", name, safe_args)

    def handle_call_tool(self, request_id: Any, name: str, arguments: dict[str, Any]) -> None:
        try:
            self._log_call(name, arguments)
            content: list[dict[str, Any]] = []

            # ═══════════════════════════════════════════════════════════════════
            # SMART TOOLS (High-level AI-friendly operations)
            # ═══════════════════════════════════════════════════════════════════
            if name == "analyze_page":
                self.launcher.ensure_running()
                result = smart_tools.analyze_page(
                    self.config,
                    detail=arguments.get("detail"),
                    offset=arguments.get("offset", 0),
                    limit=arguments.get("limit", 10),
                    form_index=arguments.get("form_index"),
                    include_content=arguments.get("include_content", False)
                )
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]

            elif name == "click_element":
                self.launcher.ensure_running()
                result = smart_tools.click_element(
                    self.config,
                    text=arguments.get("text"),
                    role=arguments.get("role"),
                    near_text=arguments.get("near_text"),
                    index=arguments.get("index", 0)
                )
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]

            elif name == "fill_form":
                self.launcher.ensure_running()
                result = smart_tools.fill_form(
                    self.config,
                    data=arguments.get("data", {}),
                    form_index=arguments.get("form_index", 0),
                    submit=arguments.get("submit", False)
                )
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]

            elif name == "search_page":
                self.launcher.ensure_running()
                result = smart_tools.search_page(
                    self.config,
                    query=arguments["query"],
                    submit=arguments.get("submit", True)
                )
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]

            elif name == "extract_content":
                self.launcher.ensure_running()
                result = smart_tools.extract_content(
                    self.config,
                    content_type=arguments.get("content_type", "overview"),
                    selector=arguments.get("selector"),
                    offset=arguments.get("offset", 0),
                    limit=arguments.get("limit", 10),
                    table_index=arguments.get("table_index")
                )
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]

            elif name == "wait_for":
                self.launcher.ensure_running()
                result = smart_tools.wait_for(
                    self.config,
                    condition=arguments["condition"],
                    timeout=arguments.get("timeout", 10.0),
                    text=arguments.get("text"),
                    selector=arguments.get("selector")
                )
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]

            elif name == "execute_workflow":
                self.launcher.ensure_running()
                result = smart_tools.execute_workflow(
                    self.config,
                    steps=arguments.get("steps", [])
                )
                # Handle screenshots in workflow
                workflow_content = []
                for step_result in result.get("results", []):
                    if step_result.get("screenshot_b64"):
                        import base64
                        workflow_content.append({
                            "type": "image",
                            "data": step_result.pop("screenshot_b64"),
                            "mimeType": "image/png"
                        })
                workflow_content.insert(0, self._result_content(json.dumps(result, ensure_ascii=False, indent=2)))
                content = workflow_content

            elif name == "upload_file":
                self.launcher.ensure_running()
                result = smart_tools.upload_file(
                    self.config,
                    file_paths=arguments.get("file_paths", []),
                    selector=arguments.get("selector")
                )
                content = [self._result_content(json.dumps(result, ensure_ascii=False, indent=2))]

            elif name == "handle_dialog":
                self.launcher.ensure_running()
                result = smart_tools.handle_dialog(
                    self.config,
                    accept=arguments.get("accept", True),
                    prompt_text=arguments.get("prompt_text")
                )
                content = [self._result_content(json.dumps(result, ensure_ascii=False, indent=2))]

            elif name == "list_tabs":
                self.launcher.ensure_running()
                result = smart_tools.list_tabs(self.config)
                content = [self._result_content(json.dumps(result, ensure_ascii=False, indent=2))]

            elif name == "switch_tab":
                self.launcher.ensure_running()
                result = smart_tools.switch_tab(
                    self.config,
                    tab_id=arguments.get("tab_id"),
                    url_pattern=arguments.get("url_pattern")
                )
                content = [self._result_content(json.dumps(result, ensure_ascii=False, indent=2))]

            elif name == "new_tab":
                self.launcher.ensure_running()
                result = smart_tools.new_tab(
                    self.config,
                    url=arguments.get("url", "about:blank")
                )
                content = [self._result_content(json.dumps(result, ensure_ascii=False, indent=2))]

            elif name == "close_tab":
                self.launcher.ensure_running()
                result = smart_tools.close_tab(
                    self.config,
                    tab_id=arguments.get("tab_id")
                )
                content = [self._result_content(json.dumps(result, ensure_ascii=False, indent=2))]

            elif name == "generate_totp":
                result = smart_tools.generate_totp(
                    secret=arguments["secret"],
                    digits=arguments.get("digits", 6),
                    interval=arguments.get("interval", 30)
                )
                content = [self._result_content(json.dumps(result, ensure_ascii=False, indent=2))]

            # ─────────────────────────────────────────────────────────────────
            # CAPTCHA tools
            # ─────────────────────────────────────────────────────────────────
            elif name == "analyze_captcha":
                result = smart_tools.analyze_captcha(
                    self.config,
                    force_grid_size=arguments.get("force_grid_size", 0)
                )
                content = [self._result_content(json.dumps(result, ensure_ascii=False, indent=2))]

            elif name == "get_captcha_screenshot":
                result = smart_tools.get_captcha_screenshot(
                    self.config,
                    grid_size=arguments.get("grid_size", 0)
                )
                # Return as image content if screenshot available
                if result.get("screenshot"):
                    content = [
                        {"type": "image", "data": result["screenshot"], "mimeType": "image/png"},
                        {"type": "text", "text": json.dumps({k: v for k, v in result.items() if k != "screenshot"}, ensure_ascii=False, indent=2)}
                    ]
                else:
                    content = [self._result_content(json.dumps(result, ensure_ascii=False, indent=2))]

            elif name == "click_captcha_blocks":
                result = smart_tools.click_captcha_blocks(
                    self.config,
                    blocks=arguments["blocks"],
                    grid_size=arguments.get("grid_size", 0)
                )
                content = [self._result_content(json.dumps(result, ensure_ascii=False, indent=2))]

            elif name == "click_captcha_area":
                result = smart_tools.click_captcha_area(
                    self.config,
                    area_id=arguments["area_id"]
                )
                content = [self._result_content(json.dumps(result, ensure_ascii=False, indent=2))]

            elif name == "submit_captcha":
                result = smart_tools.submit_captcha(self.config)
                content = [self._result_content(json.dumps(result, ensure_ascii=False, indent=2))]

            # ─────────────────────────────────────────────────────────────────
            # Basic tools
            # ─────────────────────────────────────────────────────────────────
            elif name == "http_get":
                url = arguments["url"]
                resp = http_get(url, self.config)
                content = [
                    self._result_content(
                        f"status={resp['status']}, truncated={resp['truncated']}, headers={resp['headers']}"
                    ),
                    self._result_content(resp["body"]),
                ]
            elif name == "browser_fetch":
                url = arguments["url"]
                method = arguments.get("method", "GET")
                headers = arguments.get("headers")
                body = arguments.get("body")
                credentials = arguments.get("credentials", "include")
                self.launcher.ensure_running()
                resp = smart_tools.browser_fetch(self.config, url, method, headers, body, credentials)
                content = [
                    self._result_content(
                        f"ok=True, status={resp.get('status')}, statusText={resp.get('statusText', '')}"
                    ),
                    self._result_content(resp.get("body", "")),
                ]
            elif name == "browser_set_cookie":
                self.launcher.ensure_running()
                result = smart_tools.set_cookie(
                    config=self.config,
                    name=arguments["name"],
                    value=arguments["value"],
                    domain=arguments["domain"],
                    path=arguments.get("path", "/"),
                    secure=arguments.get("secure", False),
                    http_only=arguments.get("httpOnly", False),
                    same_site=arguments.get("sameSite", "Lax"),
                    expires=arguments.get("expires"),
                )
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_set_cookies":
                self.launcher.ensure_running()
                cookies = arguments["cookies"]
                result = smart_tools.set_cookies_batch(self.config, cookies)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_get_cookies":
                self.launcher.ensure_running()
                urls = arguments.get("urls")
                result = smart_tools.get_all_cookies(self.config, urls)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_delete_cookie":
                self.launcher.ensure_running()
                result = smart_tools.delete_cookie(
                    config=self.config,
                    name=arguments["name"],
                    domain=arguments.get("domain"),
                    path=arguments.get("path"),
                    url=arguments.get("url"),
                )
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "launch_browser":
                result = self.launcher.ensure_running()
                content = [self._result_content(f"{'started' if result.started else 'skipped'}: {result.message}")]
            elif name == "cdp_version":
                should_start = arguments.get("start", True)
                launch_result = self.launcher.ensure_running() if should_start else None
                version = self.launcher.cdp_version()
                prefix = "launched" if launch_result and launch_result.started else "ready"
                content = [
                    self._result_content(f"{prefix}: {launch_result.message if launch_result else 'CDP checked'}"),
                    self._result_content(json.dumps(version, ensure_ascii=False)),
                ]
            elif name == "js_eval":
                expr = arguments["expression"]
                self.launcher.ensure_running()
                result = smart_tools.eval_js(self.config, expr)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]

            # ─────────────────────────────────────────────────────────────────
            # Navigation tools
            # ─────────────────────────────────────────────────────────────────
            elif name == "browser_navigate":
                url = arguments["url"]
                wait_load = arguments.get("wait_load", True)
                self.launcher.ensure_running()
                result = smart_tools.navigate_to(self.config, url, wait_load)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_back":
                self.launcher.ensure_running()
                result = smart_tools.go_back(self.config)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_forward":
                self.launcher.ensure_running()
                result = smart_tools.go_forward(self.config)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_reload":
                ignore_cache = arguments.get("ignore_cache", False)
                self.launcher.ensure_running()
                result = smart_tools.reload_page(self.config, ignore_cache)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]

            # ─────────────────────────────────────────────────────────────────
            # Screenshot & DOM tools
            # ─────────────────────────────────────────────────────────────────
            elif name == "screenshot":
                import base64
                url = arguments.get("url")
                self.launcher.ensure_running()
                if url:
                    # Navigate to URL first, then screenshot
                    smart_tools.navigate_to(self.config, url)
                # Screenshot session's current tab using context manager
                with smart_tools.get_session(self.config) as (session, target):
                    data_b64 = session.capture_screenshot()
                    binary = base64.b64decode(data_b64, validate=False)
                    shot = {"targetId": target["id"], "content_b64": data_b64, "bytes": len(binary)}
                max_bytes = min(self.config.http_max_bytes, 900_000)
                approx_limit = int(max_bytes * 1.37)
                data_b64 = shot["content_b64"]
                truncated = len(data_b64) > approx_limit
                if truncated:
                    data_b64 = data_b64[:approx_limit]
                content = [
                    self._result_content(f"bytes={shot['bytes']}, truncated={truncated}, target={shot['targetId']}"),
                    {"type": "image", "mimeType": "image/png", "data": data_b64},
                ]
            elif name == "dump_dom":
                url = arguments["url"]
                self.launcher.ensure_running()
                dom = smart_tools.dump_dom_html(self.config, url)
                content = [
                    self._result_content(f"target={dom['targetId']}"),
                    self._result_content(dom["html"]),
                ]
            elif name == "browser_get_dom":
                selector = arguments.get("selector")
                self.launcher.ensure_running()
                result = smart_tools.get_dom(self.config, selector)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_get_element":
                selector = arguments["selector"]
                self.launcher.ensure_running()
                result = smart_tools.get_element_info(self.config, selector)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_get_page_info":
                self.launcher.ensure_running()
                result = smart_tools.get_page_info(self.config)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]

            # ─────────────────────────────────────────────────────────────────
            # Click tools
            # ─────────────────────────────────────────────────────────────────
            elif name == "browser_click":
                selector = arguments["selector"]
                self.launcher.ensure_running()
                result = smart_tools.dom_action_click(self.config, selector)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_click_pixel":
                x = float(arguments["x"])
                y = float(arguments["y"])
                button = arguments.get("button", "left")
                self.launcher.ensure_running()
                result = smart_tools.click_at_pixel(self.config, x, y, button)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_double_click":
                x = float(arguments["x"])
                y = float(arguments["y"])
                self.launcher.ensure_running()
                result = smart_tools.double_click_at_pixel(self.config, x, y)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]

            # ─────────────────────────────────────────────────────────────────
            # Mouse tools
            # ─────────────────────────────────────────────────────────────────
            elif name == "browser_move_mouse":
                x = float(arguments["x"])
                y = float(arguments["y"])
                self.launcher.ensure_running()
                result = smart_tools.move_mouse_to(self.config, x, y)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_hover":
                selector = arguments["selector"]
                self.launcher.ensure_running()
                result = smart_tools.hover_element(self.config, selector)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_drag":
                from_x = float(arguments["from_x"])
                from_y = float(arguments["from_y"])
                to_x = float(arguments["to_x"])
                to_y = float(arguments["to_y"])
                steps = int(arguments.get("steps", 10))
                self.launcher.ensure_running()
                result = smart_tools.drag_from_to(self.config, from_x, from_y, to_x, to_y, steps)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]

            # ─────────────────────────────────────────────────────────────────
            # Keyboard tools
            # ─────────────────────────────────────────────────────────────────
            elif name == "browser_type":
                selector = arguments["selector"]
                text = arguments["text"]
                clear = arguments.get("clear", True)
                self.launcher.ensure_running()
                result = smart_tools.dom_action_type(self.config, selector, text, clear)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_press_key":
                key = arguments["key"]
                modifiers = int(arguments.get("modifiers", 0))
                self.launcher.ensure_running()
                result = smart_tools.press_key(self.config, key, modifiers)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_type_text":
                text = arguments["text"]
                self.launcher.ensure_running()
                result = smart_tools.type_text(self.config, text)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]

            # ─────────────────────────────────────────────────────────────────
            # Scroll tools
            # ─────────────────────────────────────────────────────────────────
            elif name == "browser_scroll":
                delta_x = float(arguments.get("delta_x", 0))
                delta_y = float(arguments["delta_y"])
                self.launcher.ensure_running()
                result = smart_tools.scroll_page(self.config, delta_x, delta_y)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_scroll_down":
                amount = float(arguments.get("amount", 300))
                self.launcher.ensure_running()
                result = smart_tools.scroll_page(self.config, 0, amount)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_scroll_up":
                amount = float(arguments.get("amount", 300))
                self.launcher.ensure_running()
                result = smart_tools.scroll_page(self.config, 0, -amount)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_scroll_to_element":
                selector = arguments["selector"]
                self.launcher.ensure_running()
                result = smart_tools.scroll_to_element(self.config, selector)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]

            # ─────────────────────────────────────────────────────────────────
            # Form tools
            # ─────────────────────────────────────────────────────────────────
            elif name == "browser_select_option":
                selector = arguments["selector"]
                value = arguments["value"]
                by = arguments.get("by", "value")
                self.launcher.ensure_running()
                result = smart_tools.select_option(self.config, selector, value, by)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_focus":
                selector = arguments["selector"]
                self.launcher.ensure_running()
                result = smart_tools.focus_element(self.config, selector)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_clear_input":
                selector = arguments["selector"]
                self.launcher.ensure_running()
                result = smart_tools.clear_input(self.config, selector)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]

            # ─────────────────────────────────────────────────────────────────
            # Window tools
            # ─────────────────────────────────────────────────────────────────
            elif name == "browser_resize_viewport":
                width = int(arguments["width"])
                height = int(arguments["height"])
                self.launcher.ensure_running()
                result = smart_tools.resize_viewport(self.config, width, height)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]
            elif name == "browser_resize_window":
                width = int(arguments["width"])
                height = int(arguments["height"])
                self.launcher.ensure_running()
                result = smart_tools.resize_window(self.config, width, height)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]

            # ─────────────────────────────────────────────────────────────────
            # Wait tools
            # ─────────────────────────────────────────────────────────────────
            elif name == "browser_wait_for_element":
                selector = arguments["selector"]
                timeout = float(arguments.get("timeout", 10.0))
                self.launcher.ensure_running()
                result = smart_tools.wait_for_element(self.config, selector, timeout)
                content = [self._result_content(json.dumps(result, ensure_ascii=False))]

            else:
                raise HttpClientError(f"Unknown tool {name}")

            _write_message({"jsonrpc": "2.0", "id": request_id, "result": {"content": content}})
        except Exception as exc:  # noqa: BLE001
            logger.exception("tool_call_failed")
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32001, "message": str(exc)},
                }
            )

    def dispatch(self, message: dict[str, Any]) -> None:
        if not message:
            return
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}

        if method == "initialize":
            self.handle_initialize(request_id, params)
        elif method == "notifications/initialized":
            return
        elif method in ("tools/list", "list_tools"):
            self.handle_list_tools(request_id)
        elif method in ("tools/call", "call_tool"):
            name = params.get("name")
            arguments = params.get("arguments") or params.get("args") or {}
            self.handle_call_tool(request_id, name or "", arguments)
        elif method == "ping":
            _write_message({"jsonrpc": "2.0", "id": request_id, "result": {"pong": True}})
        else:
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method {method} not found"},
                }
            )


def main() -> None:
    server = McpServer()
    while True:
        message = _read_message()
        if message is None:
            break
        server.dispatch(message)


if __name__ == "__main__":
    main()
