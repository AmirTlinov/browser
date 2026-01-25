"""Extract-content retry schema fragments."""

from __future__ import annotations

from typing import Any

EXTRACT_RETRY_PROPERTIES: dict[str, Any] = {
    "retry_on_error": {
        "type": "boolean",
        "default": False,
        "description": "Detect common error text and attempt bounded recovery before extraction.",
    },
    "error_texts": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Text snippets that signal partial failure (lazy load errors).",
    },
    "max_error_retries": {
        "type": "integer",
        "default": 2,
        "description": "Max recovery attempts when error text is detected (bounded).",
    },
    "retry_wait": {
        "type": "object",
        "description": "Optional wait args between recovery steps (for + timeout).",
        "properties": {
            "for": {
                "type": "string",
                "enum": ["navigation", "load", "domcontentloaded", "networkidle"],
                "default": "networkidle",
            },
            "timeout": {
                "type": "number",
                "default": 6.0,
            },
        },
        "additionalProperties": False,
    },
    "retry_scroll": {
        "type": "object",
        "description": "Optional scroll args between recovery checks.",
        "properties": {
            "direction": {
                "type": "string",
                "enum": ["down", "up", "left", "right"],
                "default": "down",
            },
            "amount": {
                "type": "integer",
                "default": 400,
            },
            "container_selector": {
                "type": "string",
            },
        },
        "additionalProperties": False,
    },
    "retry_reload": {
        "type": "boolean",
        "default": False,
        "description": "Reload the page during recovery attempts.",
    },
}
