"""Shared schema fragments for reliability policy fields."""

from __future__ import annotations

from typing import Any

RELIABILITY_POLICY_PROPERTIES: dict[str, Any] = {
    "heuristic_level": {
        "type": "integer",
        "enum": [0, 1, 2, 3],
        "default": 1,
        "description": "Reliability heuristic level: 0 strict/minimal, 1 balanced (default), 2 robust, 3 diagnostic.",
    },
    "strict_params": {
        "type": "boolean",
        "default": False,
        "description": "Fail fast on invalid params when true; otherwise coerce with warnings.",
    },
    "auto_dismiss_overlays": {
        "type": "boolean",
        "default": False,
        "description": "Best-effort dismiss blocking DOM overlays before click/type/form steps.",
    },
}

__all__ = ["RELIABILITY_POLICY_PROPERTIES"]
