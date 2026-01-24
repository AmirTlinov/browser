"""Protocol and tool contract definitions.

This is the single source of truth for:
- supported MCP protocol versions
- server identity
- capabilities advertised by initialize
- unified tool list
"""

from __future__ import annotations

import os
from typing import Any

from .definitions_unified import UNIFIED_TOOL_DEFINITIONS

SERVER_INFO: dict[str, str] = {"name": "browser", "version": "0.1.0"}

SUPPORTED_PROTOCOL_VERSIONS = ["0.1.0", "2025-06-18", "2024-11-05"]
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[1]
DEFAULT_PROTOCOL_VERSION = LATEST_PROTOCOL_VERSION

CAPABILITIES: dict[str, Any] = {
    "logging": {},
    "prompts": {"listChanged": False},
    "resources": {"subscribe": False, "listChanged": False},
    "tools": {"listChanged": False},
}


def select_protocol(requested: Any) -> str:
    if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return DEFAULT_PROTOCOL_VERSION


def initialize_result(protocol: str) -> dict[str, Any]:
    return {
        "protocolVersion": protocol,
        "serverInfo": SERVER_INFO,
        "capabilities": CAPABILITIES,
        "instructions": "",
    }


def tools_list() -> list[dict[str, Any]]:
    toolset = (os.environ.get("MCP_TOOLSET") or "").strip().lower()
    if toolset in {"v2", "northstar", "north-star"}:
        # Minimal, cognitively-cheap toolset:
        # - browser: lifecycle/status/recover
        # - page: perception (ax/dom/snapshot)
        # - run: batch steps (single MCP call)
        # - runbook: reuse recorded step lists
        # - app: high-level macros for canvas apps (Miro/Figma/etc.)
        allowed = {"browser", "page", "run", "runbook", "app"}
        return [t for t in UNIFIED_TOOL_DEFINITIONS if isinstance(t, dict) and t.get("name") in allowed]
    return UNIFIED_TOOL_DEFINITIONS


def contract_snapshot(protocol: str | None = None) -> dict[str, Any]:
    return {
        "protocolVersion": protocol or DEFAULT_PROTOCOL_VERSION,
        "serverInfo": SERVER_INFO,
        "tools": tools_list(),
    }
