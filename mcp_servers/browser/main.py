"""
MCP Server for browser automation via Chrome DevTools Protocol.

This module provides the main entry point and protocol handling.
Tool dispatch is handled via registry pattern in server/registry.py.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
from typing import Any

from .config import BrowserConfig
from .http_client import HttpClientError
from .launcher import BrowserLauncher
from .server.contract import (
    DEFAULT_PROTOCOL_VERSION,
    LATEST_PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    initialize_result,
    select_protocol,
    tools_list,
)
from .server.redaction import redact_jsonrpc_for_dump, redact_jsonrpc_for_log, redact_tool_arguments
from .server.registry import create_default_registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("mcp.browser")

__all__ = [
    "SUPPORTED_PROTOCOL_VERSIONS",
    "LATEST_PROTOCOL_VERSION",
    "DEFAULT_PROTOCOL_VERSION",
    "McpServer",
    "main",
]


def _write_message(payload: dict[str, Any]) -> None:
    """Write JSON-RPC message to stdout."""
    data = json.dumps(payload, ensure_ascii=False)
    line = (data + "\n").encode()
    if dump_path := os.environ.get("MCP_DUMP_FRAMES"):
        if dump_dir := os.path.dirname(dump_path):
            os.makedirs(dump_dir, exist_ok=True)
        with open(dump_path, "ab") as fp:
            fp.write(b"--out--\n")
            if os.environ.get("MCP_DUMP_FRAMES_RAW") == "1":
                fp.write(line)
            else:
                safe = redact_jsonrpc_for_dump(payload)
                fp.write((json.dumps(safe, ensure_ascii=False) + "\n").encode())
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
        logger.info("recv %s", redact_jsonrpc_for_log(msg))
    if dump_path := os.environ.get("MCP_DUMP_FRAMES"):
        if dump_dir := os.path.dirname(dump_path):
            os.makedirs(dump_dir, exist_ok=True)
        with open(dump_path, "ab") as fp:
            fp.write(b"--in--\n")
            if os.environ.get("MCP_DUMP_FRAMES_RAW") == "1":
                fp.write(line + b"\n")
            else:
                safe = redact_jsonrpc_for_dump(msg)
                fp.write((json.dumps(safe, ensure_ascii=False) + "\n").encode())
    return msg


class McpServer:
    """MCP Server with registry-based tool dispatch."""

    def __init__(self) -> None:
        self.config = BrowserConfig.from_env()
        self.launcher = BrowserLauncher(self.config)
        self.registry = create_default_registry()
        self.extension_gateway = None
        self.extension_gateway_error: str | None = None

        # Extension mode: control the user's already-running Chrome via a local MV3 extension.
        if getattr(self.config, "mode", "launch") == "extension":
            from .extension_auto_heal import ExtensionAutoHealer
            from .extension_gateway_native_peer import NativeExtensionGatewayPeer
            from .native_host_installer import ensure_native_host_installed
            from .session import session_manager

            try:
                ensure_native_host_installed()
                gw = NativeExtensionGatewayPeer(
                    on_cdp_event=lambda tab_id, ev: session_manager._ingest_tier0_event(tab_id, ev)  # noqa: SLF001
                )
                # Do not block MCP initialize on extension connectivity. Connecting is usually fast,
                # but we fail-soft and surface actionable status via browser(action="status") / tool errors.
                gw.start(wait_timeout=0.5)
                session_manager.set_extension_gateway(gw)  # type: ignore[arg-type]
                self.extension_gateway = gw
                ExtensionAutoHealer(gw).start()
            except Exception as exc:  # noqa: BLE001
                # Fail-soft: do not crash the MCP handshake; return actionable errors on tool calls.
                msg = str(exc)
                self.extension_gateway_error = msg
                with contextlib.suppress(Exception):
                    session_manager.set_extension_gateway_error(msg)
                logger.error("extension_gateway_start_failed: %s", msg)

    def handle_initialize(self, request_id: Any, params: dict[str, Any] | None = None) -> None:
        """Handle initialize request."""
        requested = (params or {}).get("protocolVersion") if isinstance(params, dict) else None
        protocol = select_protocol(requested)
        _write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": initialize_result(protocol),
            }
        )

    def handle_list_tools(self, request_id: Any) -> None:
        """Handle tools/list request."""
        _write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": tools_list()},
            }
        )

    def _log_call(self, name: str, arguments: dict[str, Any]) -> None:
        """Log tool call with sanitized arguments."""
        safe_args = redact_tool_arguments(name, arguments)
        logger.info("tool=%s args=%s", name, safe_args)

    def handle_call_tool(self, request_id: Any, name: str, arguments: dict[str, Any]) -> None:
        """
        Handle tool call via registry dispatch.

        Cyclomatic complexity: ~5 (down from 71!)
        """
        self._log_call(name, arguments)

        from .server.types import ToolResult
        from .tools.base import SmartToolError

        try:
            if not name:
                result = ToolResult.error("Missing tool name")
            elif not self.registry.has(name):
                result = ToolResult.error(f"Unknown tool: {name}", tool=name)
            else:
                result = self.registry.dispatch(name, self.config, self.launcher, arguments)
        except SmartToolError as e:
            logger.info("tool_error tool=%s action=%s reason=%s", e.tool, e.action, e.reason)
            result = ToolResult.error(e.reason, tool=e.tool, suggestion=e.suggestion, details=e.details)
        except HttpClientError as e:
            logger.info("http_error %s", str(e))
            result = ToolResult.error(str(e), tool=name)
        except Exception as exc:
            logger.exception("tool_call_failed")
            result = ToolResult.error(str(exc), tool=name)

        _write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": result.to_content_list(), "isError": result.is_error},
            }
        )

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
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method {method} not found"},
                }
            )


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
