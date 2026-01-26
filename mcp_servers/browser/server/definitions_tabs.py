"""Tabs tool schema definition."""

from __future__ import annotations

from typing import Any

TABS_TOOL: dict[str, Any] = {
    "name": "tabs",
    "description": """Manage browser tabs: list, switch, open, close.
USAGE:
- List tabs: tabs(action="list")
- List all tabs (opt-out privacy): tabs(action="list", include_all=true)
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
            "include_all": {
                "type": "boolean",
                "default": False,
                "description": "For list: include all user tabs (default: session-only)",
            },
            "offset": {
                "type": "integer",
                "default": 0,
                "description": "For list: starting offset",
            },
            "limit": {
                "type": "integer",
                "default": 20,
                "description": "For list: maximum tabs to return",
            },
        },
        "additionalProperties": False,
    },
}

__all__ = ["TABS_TOOL"]
