"""Session subsystem.

This module is split into focused submodules to keep files small:
- session_cdp.py: raw CDP + extension CDP connections
- session_tier0.py: Tier-0 telemetry event bus
- browser_session.py: BrowserSession wrapper
- session_manager.py: SessionManager implementation

`session.py` remains the stable import surface (re-exports).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from .config import BrowserConfig
from .diagnostics import DIAGNOSTICS_SCRIPT_SOURCE, DIAGNOSTICS_SCRIPT_VERSION
from .http_client import HttpClientError
from .sensitivity import is_sensitive_key
from .telemetry import Tier0Telemetry
from .session_helpers import _import_websocket

if TYPE_CHECKING:
    from .extension_gateway import ExtensionGateway

def _extension_rpc_timeout(base: float | None = None) -> float:
    """Return a robust default timeout for extension RPC/CDP calls."""
    try:
        configured = float(os.environ.get("MCP_EXTENSION_RPC_TIMEOUT") or 8.0)
    except Exception:
        configured = 8.0
    configured = max(2.0, min(configured, 30.0))
    if base is None:
        return configured
    try:
        base_val = float(base)
    except Exception:
        base_val = configured
    return max(base_val, configured)



class CdpConnection:
    """Low-level CDP WebSocket connection."""

    def __init__(self, ws_url: str, timeout: float = 5.0):
        websocket = _import_websocket()
        self.ws = websocket.create_connection(ws_url, timeout=timeout)
        self.ws_url = ws_url
        self.timeout = timeout
        self._next_id = 1
        # CDP is event-heavy. We must not drop events while waiting for command responses,
        # otherwise higher-level waits (load/dialog/navigation) become flaky.
        self._event_queue: list[dict[str, Any]] = []
        self._max_event_queue = 2000
        self._event_sink: Callable[[dict[str, Any]], None] | None = None

    def set_event_sink(self, sink: Callable[[dict[str, Any]], None] | None) -> None:
        """Attach a best-effort event sink called for every received CDP event."""
        self._event_sink = sink

    def _push_event(self, event: dict[str, Any]) -> None:
        """Store an event for later consumption (bounded)."""
        if not isinstance(event, dict):
            return
        if not isinstance(event.get("method"), str):
            return

        sink = self._event_sink
        if sink is not None:
            with suppress(Exception):
                # Telemetry must never break browser operations.
                sink(event)

        self._event_queue.append(event)
        if len(self._event_queue) > self._max_event_queue:
            # Drop oldest events to avoid unbounded growth in long sessions.
            del self._event_queue[: len(self._event_queue) - self._max_event_queue]

    def pop_event(self, event_name: str) -> dict[str, Any] | None:
        """Pop the oldest queued event params for the given event name."""
        if not event_name:
            return None
        for i, ev in enumerate(self._event_queue):
            if ev.get("method") == event_name:
                self._event_queue.pop(i)
                params = ev.get("params")
                return params if isinstance(params, dict) else {}
        return None

    def drain_events(self, *, max_messages: int = 50) -> int:
        """Best-effort: drain already-buffered CDP events without blocking.

        This is used between tool steps (run/flow) to reduce dialog/navigation races:
        a dialog can open between commands, and we want Tier-0 to see it *before* the
        next action is issued.

        Safety:
        - Never blocks (uses a 0-timeout recv).
        - Only stores CDP events (method + params, no id).
        - If a non-event message is received unexpectedly, we stop immediately.
        """
        drained = 0
        for _ in range(max(0, int(max_messages))):
            try:
                self.ws.settimeout(0.0)
                raw = self.ws.recv()
            except Exception as exc:  # noqa: BLE001
                msg = str(exc).lower()
                if isinstance(exc, TimeoutError) or "timed out" in msg or "would block" in msg:
                    break
                break

            try:
                data = json.loads(raw)
            except Exception:
                continue

            if isinstance(data, dict) and isinstance(data.get("method"), str) and "id" not in data:
                self._push_event(data)
                drained += 1
                continue

            # Unexpected non-event; stop to avoid consuming responses.
            break

        return drained

    def abort(self) -> None:
        """Best-effort hard break of the underlying socket.

        Why:
        - Some websocket-client operations (notably send()) can block in ways that a normal
          ws.close() doesn't reliably interrupt from another thread.
        - Watchdogs use this to ensure tool calls can't freeze the MCP server process.
        """
        import socket

        # Prefer closing the raw socket to avoid websocket-client internal locks.
        try:
            sock = getattr(self.ws, "sock", None)
        except Exception:
            sock = None

        if sock is not None:
            with suppress(Exception):
                sock.shutdown(socket.SHUT_RDWR)
            with suppress(Exception):
                sock.close()

        # Do not call websocket-client close() here: it may attempt to take internal locks
        # and can itself hang in dialog-brick scenarios. The raw socket shutdown/close is
        # the reliable breaker.

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send CDP command and wait for response."""
        msg_id = self._next_id
        self._next_id += 1

        msg = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params

        # Guard against websocket-client send() stalls: set a small socket timeout and
        # fail fast, otherwise a single blocked send can freeze the whole MCP server.
        old_sock_timeout: float | None = None
        try:
            sock = getattr(self.ws, "sock", None)
            if sock is not None and hasattr(sock, "gettimeout"):
                old_sock_timeout = sock.gettimeout()
        except Exception:
            old_sock_timeout = None
        try:
            with suppress(Exception):
                # Keep it bounded but not overly aggressive; recv() enforces the full deadline.
                self.ws.settimeout(min(2.0, max(0.5, float(self.timeout))))
            self.ws.send(json.dumps(msg))
        except Exception as exc:  # noqa: BLE001
            raise HttpClientError(str(exc)) from exc
        finally:
            if old_sock_timeout is not None:
                with suppress(Exception):
                    self.ws.settimeout(old_sock_timeout)

        return self._recv_until(msg_id)

    def send_many(self, commands: list[dict[str, Any]], *, stop_on_error: bool = True) -> list[dict[str, Any]]:
        """Send multiple CDP commands sequentially (best-effort helper).

        In extension mode, a specialized implementation batches these in one transport
        round-trip. For direct CDP connections, this simply loops `send(...)` so callers
        can share one code path.
        """
        out: list[dict[str, Any]] = []
        for i, cmd in enumerate(commands):
            if not isinstance(cmd, dict):
                continue
            method = cmd.get("method")
            if not isinstance(method, str) or not method.strip():
                if stop_on_error:
                    raise HttpClientError("send_many: each command must include a non-empty 'method'")
                out.append({"ok": False, "error": "missing method", "index": i})
                continue
            params = cmd.get("params") if isinstance(cmd.get("params"), dict) else None
            try:
                out.append(self.send(method, params))
            except Exception as exc:  # noqa: BLE001
                if stop_on_error:
                    raise
                out.append({"ok": False, "error": str(exc), "method": str(method)})
            try:
                delay_ms = int(cmd.get("delayMs") or 0)
            except Exception:
                delay_ms = 0
            if delay_ms > 0:
                time.sleep(min(5.0, delay_ms / 1000.0))
        return out

    def _recv_until(self, expected_id: int) -> dict[str, Any]:
        """Wait for response with specific ID."""
        deadline = time.time() + self.timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise HttpClientError("CDP response timed out")

            # websocket-client `recv()` can block indefinitely unless a socket timeout is set.
            # Keep the timeout small so we can enforce our own deadline reliably.
            try:
                self.ws.settimeout(min(0.5, remaining))
                raw = self.ws.recv()
            except Exception as exc:  # noqa: BLE001
                # Treat timeouts as "no message yet"; retry until deadline.
                msg = str(exc).lower()
                if isinstance(exc, TimeoutError) or "timed out" in msg:
                    continue
                raise HttpClientError(str(exc)) from exc

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # CDP event: store and keep waiting for the command response.
            if isinstance(data, dict) and isinstance(data.get("method"), str) and "id" not in data:
                self._push_event(data)
                continue

            if data.get("id") == expected_id:
                if "error" in data:
                    raise HttpClientError(str(data["error"]))
                return data.get("result", {})
            # Otherwise: it's likely an event; ignore.

    def wait_for_event(self, event_name: str, timeout: float = 10.0) -> dict | None:
        """Wait for specific CDP event."""
        # Fast-path: consume from queue first.
        queued = self.pop_event(event_name)
        if queued is not None:
            return queued

        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break

            try:
                self.ws.settimeout(min(0.5, remaining))
                raw = self.ws.recv()
            except Exception as exc:  # noqa: BLE001
                msg = str(exc).lower()
                if isinstance(exc, TimeoutError) or "timed out" in msg:
                    continue
                raise HttpClientError(str(exc)) from exc

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if isinstance(data, dict) and isinstance(data.get("method"), str) and "id" not in data:
                if data.get("method") == event_name:
                    params = data.get("params")
                    sink = self._event_sink
                    if sink is not None:
                        with suppress(Exception):
                            sink(data)
                    return params if isinstance(params, dict) else {}
                self._push_event(data)
        return None

    def close(self):
        """Close the WebSocket connection."""
        # Safety-first: avoid websocket-client close() hangs by preferring a raw-socket shutdown.
        # (Graceful close handshakes are not worth risking an MCP server wedge.)
        with suppress(Exception):
            self.abort()



class ExtensionCdpConnection:
    """CDP-like connection that proxies commands/events through the local extension gateway.

    This is used when MCP_BROWSER_MODE=extension to control the user's already-running Chrome
    (no separate Chrome instance, no --remote-debugging-port requirement).
    """

    def __init__(self, gateway: ExtensionGateway, tab_id: str, *, timeout: float = 5.0) -> None:
        self.gateway = gateway
        self.tab_id = str(tab_id or "").strip()
        self.ws_url = f"extension://tab/{self.tab_id}"
        self.timeout = float(timeout)
        self._event_sink: Callable[[dict[str, Any]], None] | None = None

    def set_event_sink(self, sink: Callable[[dict[str, Any]], None] | None) -> None:
        # Best-effort: the gateway already forwards events to Tier-0 telemetry.
        self._event_sink = sink

    def pop_event(self, event_name: str) -> dict[str, Any] | None:
        params = self.gateway.pop_event(self.tab_id, event_name)
        if params is None:
            return None
        sink = self._event_sink
        if sink is not None:
            with suppress(Exception):
                sink({"method": event_name, "params": params})
        return params

    def drain_events(self, *, max_messages: int = 50) -> int:  # noqa: ARG002
        # Events are pushed asynchronously by the gateway; there's no socket to drain here.
        return 0

    def abort(self) -> None:
        # No underlying socket to break; keep semantics for watchdog compatibility.
        return

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.gateway.cdp_send(self.tab_id, method, params, timeout=self.timeout)

    def send_many(self, commands: list[dict[str, Any]], *, stop_on_error: bool = True) -> list[dict[str, Any]]:
        return self.gateway.cdp_send_many(self.tab_id, commands, timeout=self.timeout, stop_on_error=stop_on_error)

    def wait_for_event(self, event_name: str, timeout: float = 10.0) -> dict | None:
        params = self.gateway.wait_for_event(self.tab_id, event_name, timeout=timeout)
        if params is None:
            return None
        sink = self._event_sink
        if sink is not None:
            with suppress(Exception):
                sink({"method": event_name, "params": params})
        return params

    def close(self) -> None:
        # Do not close the gateway on per-tool connection close.
        return




__all__ = ["CdpConnection", "ExtensionCdpConnection", "_extension_rpc_timeout"]
