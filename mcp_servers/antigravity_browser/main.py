"""
MCP Server for browser automation via Chrome DevTools Protocol.

This module provides the main entry point and protocol handling.
Tool dispatch is handled via registry pattern in server/registry.py.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

from .config import BrowserConfig
from .http_client import HttpClientError
from .launcher import BrowserLauncher
from .server.definitions import get_all_tool_definitions
from .server.registry import create_default_registry

SUPPORTED_PROTOCOL_VERSIONS = ["0.1.0", "2025-06-18", "2024-11-05"]
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[1]
DEFAULT_PROTOCOL_VERSION = LATEST_PROTOCOL_VERSION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("mcp.browser")


def _write_message(payload: dict[str, Any]) -> None:
    """Write JSON-RPC message to stdout."""
    data = json.dumps(payload, ensure_ascii=False)
    line = (data + "\n").encode()
    if dump_path := os.environ.get("MCP_DUMP_FRAMES"):
        with open(dump_path, "ab") as fp:
            fp.write(b"--out--\n")
            fp.write(line)
    sys.stdout.buffer.write(line)
    sys.stdout.buffer.flush()


def _read_message() -> dict[str, Any] | None:
    """Read JSON-RPC message from stdin."""
    line = sys.stdin.buffer.readline()
    if not line:
        return None
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


class McpServer:
    """MCP Server with registry-based tool dispatch."""

    def __init__(self) -> None:
        self.config = BrowserConfig.from_env()
        self.launcher = BrowserLauncher(self.config)
        self.registry = create_default_registry()

    def _select_protocol(self, params: dict[str, Any]) -> str:
        """Select protocol version from client request."""
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS:
            return requested
        return DEFAULT_PROTOCOL_VERSION

    def handle_initialize(self, request_id: Any, params: dict[str, Any] | None = None) -> None:
        """Handle initialize request."""
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
        """Handle tools/list request."""
        _write_message({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": get_all_tool_definitions()},
        })

    def _log_call(self, name: str, arguments: dict[str, Any]) -> None:
        """Log tool call with sanitized arguments."""
        safe_args = dict(arguments)
        if "url" in safe_args and isinstance(safe_args["url"], str):
            safe_args["url"] = safe_args["url"].split("?")[0]
        logger.info("tool=%s args=%s", name, safe_args)

    def handle_call_tool(self, request_id: Any, name: str, arguments: dict[str, Any]) -> None:
        """
        Handle tool call via registry dispatch.

        Cyclomatic complexity: ~5 (down from 71!)
        """
        try:
            self._log_call(name, arguments)

            if not self.registry.has(name):
                raise HttpClientError(f"Unknown tool {name}")

            result = self.registry.dispatch(name, self.config, self.launcher, arguments)
            content = result.to_content_list()

            _write_message({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": content},
            })

        except Exception as exc:
            logger.exception("tool_call_failed")
            _write_message({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32001, "message": str(exc)},
            })

    def dispatch(self, message: dict[str, Any]) -> None:
        """Dispatch incoming JSON-RPC message to appropriate handler."""
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
            _write_message({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Method {method} not found"},
            })


def main() -> None:
    """Main entry point for MCP server."""
    server = McpServer()
    while True:
        message = _read_message()
        if message is None:
            break
        server.dispatch(message)


if __name__ == "__main__":
    main()
