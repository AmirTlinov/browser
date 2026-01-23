"""
Session management for isolated browser tab sessions.

Each MCP server process gets its own isolated browser tab to prevent
conflicts when multiple agents work with the same browser simultaneously.

Architecture:
- SessionManager: Singleton managing the current session's tab
- BrowserSession: Context manager for CDP operations on the session tab
- All browser operations should go through SessionManager.get_session()
"""

from __future__ import annotations

import json
import hashlib
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

if TYPE_CHECKING:
    from .extension_gateway import ExtensionGateway


class _Tier0EventBus:
    """Background CDP event reader for Tier-0 telemetry.

    This keeps Tier-0 buffers "alive" even between tool calls (no page injection).
    Best-effort: failures must never break tool execution.
    """

    def __init__(self, *, ws_url: str, on_event: Callable[[dict[str, Any]], None], name: str) -> None:
        self.ws_url = ws_url
        self._on_event = on_event
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._conn: CdpConnection | None = None

    def start(self) -> None:
        if self._thread.is_alive():
            return
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass

    def _run(self) -> None:
        backoff = 0.2
        while not self._stop.is_set():
            conn: CdpConnection | None = None
            try:
                conn = CdpConnection(self.ws_url, timeout=5.0)
                self._conn = conn

                # Enable high-signal domains (best-effort).
                with suppress(Exception):
                    conn.send_many(
                        [
                            {"method": "Page.enable", "params": {}},
                            {"method": "Runtime.enable", "params": {}},
                            {"method": "Network.enable", "params": {}},
                            {"method": "Log.enable", "params": {}},
                        ]
                    )

                backoff = 0.2

                while not self._stop.is_set():
                    try:
                        conn.ws.settimeout(0.5)
                        raw = conn.ws.recv()
                    except Exception as exc:  # noqa: BLE001
                        msg = str(exc).lower()
                        if isinstance(exc, TimeoutError) or "timed out" in msg:
                            continue
                        raise

                    try:
                        data = json.loads(raw)
                    except Exception:
                        continue

                    if isinstance(data, dict) and isinstance(data.get("method"), str) and "id" not in data:
                        with suppress(Exception):
                            # Telemetry must never break.
                            self._on_event(data)
            except Exception:
                # Reconnect loop (best-effort).
                pass
            finally:
                try:
                    if conn is not None:
                        conn.close()
                except Exception:
                    pass
                self._conn = None

            if self._stop.is_set():
                break

            time.sleep(backoff)
            backoff = min(backoff * 1.5, 2.0)


def _normalize_policy_mode(raw: str) -> str:
    """Normalize policy mode string."""
    v = (raw or "").strip().lower()
    if v in {"strict", "locked", "secure"}:
        return "strict"
    return "permissive"


def _repo_root() -> Path:
    # mcp_servers/browser/session.py -> repo root is parents[2]
    return Path(__file__).resolve().parents[2]


def _downloads_root() -> Path:
    raw = os.environ.get("MCP_DOWNLOAD_DIR")
    if isinstance(raw, str) and raw.strip():
        return Path(raw.strip()).expanduser()
    return _repo_root() / "data" / "downloads"


def _import_websocket():
    """Import websocket-client with fallback paths."""
    try:
        import websocket

        return websocket
    except ImportError:
        import sys

        candidates = [
            # Repo-local vendored deps (portable, no system deps).
            _repo_root() / "vendor" / "python",
            Path.home()
            / ".local"
            / "lib"
            / f"python{sys.version_info.major}.{sys.version_info.minor}"
            / "site-packages",
        ]
        for path in candidates:
            if path.exists() and str(path) not in sys.path:
                sys.path.insert(0, str(path))
        import websocket

        return websocket


def _http_get_json(url: str, timeout: float = 2.0) -> Any:
    """Fetch JSON from URL."""
    from urllib.error import URLError
    from urllib.request import urlopen

    try:
        with urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except URLError as e:
        raise HttpClientError(str(e)) from e


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


class BrowserSession:
    """
    High-level browser session for a specific tab.

    Wraps CdpConnection with common browser operations.
    Use as context manager for automatic cleanup.
    """

    def __init__(self, connection: CdpConnection, tab_id: str, tab_url: str = ""):
        self.conn = connection
        self.tab_id = tab_id
        self.tab_url = tab_url
        self._page_enabled = False
        self._runtime_enabled = False
        self._dom_enabled = False
        self._network_enabled = False
        self._log_enabled = False
        self._performance_enabled = False

    def __enter__(self) -> BrowserSession:
        self.enable_page()
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        """Close the session connection."""
        self.conn.close()

    def enable_page(self) -> None:
        """Enable Page domain for navigation events."""
        self.enable_domains(page=True)

    def enable_runtime(self) -> None:
        """Enable Runtime domain for JS evaluation."""
        self.enable_domains(runtime=True)

    def enable_dom(self) -> None:
        """Enable DOM domain (needed for DOM.* APIs like setFileInputFiles/getBoxModel)."""
        self.enable_domains(dom=True)

    def enable_network(self) -> None:
        """Enable Network domain (needed for cookie/network events)."""
        self.enable_domains(network=True)

    def enable_log(self) -> None:
        """Enable Log domain (console/entryAdded events)."""
        self.enable_domains(log=True)

    def enable_performance(self) -> None:
        """Enable Performance domain (getMetrics)."""
        self.enable_domains(performance=True)

    def enable_domains(
        self,
        *,
        page: bool = False,
        runtime: bool = False,
        dom: bool = False,
        network: bool = False,
        log: bool = False,
        performance: bool = False,
        strict: bool = True,
    ) -> None:
        """Enable common CDP domains with caching and batching.

        Why this exists:
        - In extension mode, every CDP command is an RPC round-trip to the gateway.
        - Many flows call Runtime.enable / Network.enable repeatedly out of caution.
        - This helper makes domain enabling idempotent, cached, and batched.
        """
        cmds: list[dict[str, Any]] = []
        flags: list[str] = []

        if page and not self._page_enabled:
            cmds.append({"method": "Page.enable", "params": {}})
            flags.append("page")
        if runtime and not self._runtime_enabled:
            cmds.append({"method": "Runtime.enable", "params": {}})
            flags.append("runtime")
        if dom and not self._dom_enabled:
            cmds.append({"method": "DOM.enable", "params": {}})
            flags.append("dom")
        if network and not self._network_enabled:
            cmds.append({"method": "Network.enable", "params": {}})
            flags.append("network")
        if log and not self._log_enabled:
            cmds.append({"method": "Log.enable", "params": {}})
            flags.append("log")
        if performance and not self._performance_enabled:
            cmds.append({"method": "Performance.enable", "params": {}})
            flags.append("performance")

        if not cmds:
            return

        # Prefer batching; if it fails, fall back to per-command enables.
        try:
            self.conn.send_many(cmds)  # type: ignore[attr-defined]
            for f in flags:
                if f == "page":
                    self._page_enabled = True
                elif f == "runtime":
                    self._runtime_enabled = True
                elif f == "dom":
                    self._dom_enabled = True
                elif f == "network":
                    self._network_enabled = True
                elif f == "log":
                    self._log_enabled = True
                elif f == "performance":
                    self._performance_enabled = True
            return
        except Exception:
            # Fall back below.
            pass

        failures: list[tuple[str, str]] = []
        for cmd, f in zip(cmds, flags, strict=False):
            try:
                self.conn.send(cmd["method"], cmd.get("params"))
            except Exception as exc:  # noqa: BLE001
                failures.append((str(cmd.get("method") or ""), str(exc)))
                continue
            if f == "page":
                self._page_enabled = True
            elif f == "runtime":
                self._runtime_enabled = True
            elif f == "dom":
                self._dom_enabled = True
            elif f == "network":
                self._network_enabled = True
            elif f == "log":
                self._log_enabled = True
            elif f == "performance":
                self._performance_enabled = True

        if strict and failures:
            failed_names = ", ".join(m for m, _ in failures if m)
            details = "; ".join(f"{m}: {err}" for m, err in failures if m)
            raise HttpClientError(f"Failed to enable CDP domain(s): {failed_names}. Details: {details}")

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send raw CDP command (for compatibility with existing code)."""
        return self.conn.send(method, params)

    def send_many(self, commands: list[dict[str, Any]], *, stop_on_error: bool = True) -> list[dict[str, Any]]:
        """Send multiple CDP commands (batched when supported).

        In extension mode, this collapses many CDP commands into a single gateway
        round-trip via `cdp.sendMany`. For direct CDP connections it falls back to
        sequential sends.
        """
        try:
            return self.conn.send_many(commands, stop_on_error=stop_on_error)  # type: ignore[attr-defined]
        except Exception:
            out: list[dict[str, Any]] = []
            for cmd in commands:
                if not isinstance(cmd, dict):
                    continue
                method = cmd.get("method")
                if not isinstance(method, str) or not method.strip():
                    continue
                params = cmd.get("params") if isinstance(cmd.get("params"), dict) else None
                try:
                    out.append(self.send(method, params))
                except Exception as exc:  # noqa: BLE001
                    if stop_on_error:
                        raise
                    out.append({"ok": False, "error": str(exc), "method": str(method)})
            return out

    def wait_for_event(self, event_name: str, timeout: float = 10.0) -> dict | None:
        """Wait for a CDP event on this session's connection (best-effort)."""
        try:
            return self.conn.wait_for_event(event_name, timeout=timeout)  # type: ignore[attr-defined]
        except Exception:
            return None

    def capture_screenshot(self, format: str = "png", clip: dict | None = None) -> str:
        """Alias for screenshot() for compatibility."""
        return self.screenshot(format, clip)

    # ─────────────────────────────────────────────────────────────────────────
    # Navigation
    # ─────────────────────────────────────────────────────────────────────────

    def navigate(self, url: str, wait_load: bool = True, timeout: float = 10.0) -> str:
        """Navigate to URL, optionally waiting for load."""
        self.conn.send("Page.navigate", {"url": url})
        if wait_load:
            self.wait_load(timeout)
        self.tab_url = url
        return url

    def wait_load(self, timeout: float = 10.0) -> bool:
        """Wait for page load event."""
        result = self.conn.wait_for_event("Page.loadEventFired", timeout)
        return result is not None

    def reload(self, ignore_cache: bool = False) -> None:
        """Reload current page."""
        self.conn.send("Page.reload", {"ignoreCache": ignore_cache})
        self.wait_load()

    def go_back(self) -> str:
        """Navigate back in history."""
        with suppress(Exception):
            self.eval_js("window.history.back()")
        time.sleep(0.3)
        return self.get_url()

    def go_forward(self) -> str:
        """Navigate forward in history."""
        with suppress(Exception):
            self.eval_js("window.history.forward()")
        time.sleep(0.3)
        return self.get_url()

    # ─────────────────────────────────────────────────────────────────────────
    # JavaScript
    # ─────────────────────────────────────────────────────────────────────────

    def eval_js(self, expression: str, *, timeout: float | None = None) -> Any:
        """Evaluate JavaScript and return result.

        Robustness notes:
        - If Tier-0 telemetry knows a blocking JS dialog is open, fail fast instead of hanging.
        - If a custom timeout is provided, it temporarily overrides the CDP command timeout for
          this call only (best-effort).
        """
        # Fail-fast when a blocking JS dialog is open (Runtime.evaluate can hang indefinitely).
        # This relies on Tier-0 telemetry (best-effort); if telemetry is not enabled, we proceed.
        try:
            telemetry = session_manager.get_telemetry(self.tab_id)
            if telemetry is not None and getattr(telemetry, "dialog_open", False):
                meta = getattr(telemetry, "dialog_last", None)
                details = meta.get("type") if isinstance(meta, dict) else "dialog"
                raise HttpClientError(f"Blocking JS dialog is open ({details}). Handle it via dialog() then retry.")
        except HttpClientError:
            raise
        except Exception:
            pass

        # Enable Page as well so JS dialog events can be observed on this connection.
        # (In most flows Page is already enabled; this is cheap + idempotent.)
        with suppress(Exception):
            self.enable_page()

        self.enable_runtime()

        old_timeout: float | None = None
        if timeout is not None:
            try:
                old_timeout = float(self.conn.timeout)
                self.conn.timeout = float(timeout)
            except Exception:
                old_timeout = None

        try:
            result = self.conn.send(
                "Runtime.evaluate",
                {
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": True,
                },
            )
        except HttpClientError as exc:
            # If the call timed out, try to detect if a JS dialog opened during evaluation.
            # When Page domain is enabled, Chrome emits Page.javascriptDialogOpening.
            msg = str(exc).lower()
            if "cdp response timed out" in msg and hasattr(self.conn, "pop_event"):
                opened: dict[str, Any] | None = None
                try:
                    opened = self.conn.pop_event("Page.javascriptDialogOpening")  # type: ignore[attr-defined]
                except Exception:
                    opened = None

                if opened is not None:
                    # Best-effort: reflect the dialog state in Tier-0 so subsequent calls can fail fast.
                    try:
                        telemetry = session_manager.get_telemetry(self.tab_id)
                        if telemetry is not None:
                            telemetry.dialog_open = True
                    except Exception:
                        pass
                    raise HttpClientError(
                        "Runtime.evaluate blocked by a JS dialog. Handle it via dialog() and retry."
                    ) from exc
            raise
        finally:
            if old_timeout is not None:
                with suppress(Exception):
                    self.conn.timeout = old_timeout

        if "result" not in result:
            return None
        value = result["result"]
        # CDP returns undefined as {"type":"undefined"} (no "value" field). Returning the raw
        # dict makes `bool(eval_js(...))` incorrectly truthy and breaks checks like:
        #   globalThis.__mcpDiag && ...
        # Normalize undefined (and null) to Python None.
        try:
            if isinstance(value, dict) and value.get("type") == "undefined":
                return None
            if isinstance(value, dict) and value.get("type") == "object" and value.get("subtype") == "null":
                return None
        except Exception:
            pass
        return value.get("value", value)

    def get_url(self) -> str:
        """Get current page URL."""
        return self.eval_js("window.location.href") or ""

    def get_title(self) -> str:
        """Get current page title."""
        return self.eval_js("document.title") or ""

    # ─────────────────────────────────────────────────────────────────────────
    # Mouse Input
    # ─────────────────────────────────────────────────────────────────────────

    def click(self, x: float, y: float, button: str = "left", click_count: int = 1) -> None:
        """Click at coordinates."""
        self.conn.send_many(
            [
                {
                    "method": "Input.dispatchMouseEvent",
                    "params": {
                        "type": "mousePressed",
                        "x": x,
                        "y": y,
                        "button": button,
                        "clickCount": click_count,
                    },
                },
                {
                    "method": "Input.dispatchMouseEvent",
                    "params": {
                        "type": "mouseReleased",
                        "x": x,
                        "y": y,
                        "button": button,
                        "clickCount": click_count,
                    },
                },
            ]
        )

    def double_click(self, x: float, y: float) -> None:
        """Double-click at coordinates."""
        self.click(x, y, click_count=2)

    def move_mouse(self, x: float, y: float) -> None:
        """Move mouse to coordinates."""
        self._mouse_event("mouseMoved", x, y, "none", 0)

    def drag(self, from_x: float, from_y: float, to_x: float, to_y: float, steps: int = 10) -> None:
        """Drag from one point to another."""
        steps = max(1, int(steps))
        cmds: list[dict[str, Any]] = []
        cmds.append(
            {
                "method": "Input.dispatchMouseEvent",
                "params": {
                    "type": "mousePressed",
                    "x": from_x,
                    "y": from_y,
                    "button": "left",
                    "clickCount": 1,
                },
            }
        )
        for i in range(1, steps + 1):
            progress = i / steps
            x = from_x + (to_x - from_x) * progress
            y = from_y + (to_y - from_y) * progress
            cmds.append(
                {
                    "method": "Input.dispatchMouseEvent",
                    "params": {"type": "mouseMoved", "x": x, "y": y, "button": "left", "clickCount": 0},
                    # Best-effort spacing for apps that detect drag thresholds/timing.
                    "delayMs": 10,
                }
            )
        cmds.append(
            {
                "method": "Input.dispatchMouseEvent",
                "params": {
                    "type": "mouseReleased",
                    "x": to_x,
                    "y": to_y,
                    "button": "left",
                    "clickCount": 1,
                },
            }
        )
        self.conn.send_many(cmds)

    def scroll(self, delta_x: float = 0, delta_y: float = 0, x: float = 0, y: float = 0) -> None:
        """Scroll the page."""
        self.conn.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseWheel",
                "x": x,
                "y": y,
                "deltaX": delta_x,
                "deltaY": delta_y,
            },
        )

    def _mouse_event(self, event_type: str, x: float, y: float, button: str, click_count: int) -> None:
        """Dispatch mouse event."""
        self.conn.send(
            "Input.dispatchMouseEvent",
            {
                "type": event_type,
                "x": x,
                "y": y,
                "button": button,
                "clickCount": click_count,
            },
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Keyboard Input
    # ─────────────────────────────────────────────────────────────────────────

    def press_key(self, key: str, modifiers: int = 0) -> None:
        """Press a keyboard key."""
        # Key codes for special keys
        key_codes = {
            "Enter": 13,
            "Tab": 9,
            "Escape": 27,
            "Backspace": 8,
            "Delete": 46,
            "ArrowUp": 38,
            "ArrowDown": 40,
            "ArrowLeft": 37,
            "ArrowRight": 39,
            "Home": 36,
            "End": 35,
            "PageUp": 33,
            "PageDown": 34,
        }
        key_code = key_codes.get(key, ord(key[0].upper()) if len(key) == 1 else 0)

        self.conn.send_many(
            [
                {
                    "method": "Input.dispatchKeyEvent",
                    "params": {
                        "type": "keyDown",
                        "key": key,
                        "code": f"Key{key.upper()}" if len(key) == 1 else key,
                        "windowsVirtualKeyCode": key_code,
                        "modifiers": modifiers,
                    },
                },
                {
                    "method": "Input.dispatchKeyEvent",
                    "params": {
                        "type": "keyUp",
                        "key": key,
                        "code": f"Key{key.upper()}" if len(key) == 1 else key,
                        "windowsVirtualKeyCode": key_code,
                        "modifiers": modifiers,
                    },
                },
            ]
        )

    def type_text(self, text: str) -> None:
        """Type text character by character."""
        if not text:
            return

        # Fast path: CDP has a dedicated text insertion API (single command).
        # This is dramatically faster than char-by-char key events and works well for
        # most editable inputs (it may not emit full keydown/keyup sequences).
        try:
            self.conn.send("Input.insertText", {"text": str(text)})
            return
        except Exception:
            # Fallback: char events.
            pass

        # Batch key events to avoid chatty round-trips (especially in extension mode).
        # Chunking keeps per-batch execution bounded even when timeouts are low.
        batch_size = 250
        for i in range(0, len(text), batch_size):
            chunk = text[i : i + batch_size]
            cmds = [{"method": "Input.dispatchKeyEvent", "params": {"type": "char", "text": c}} for c in chunk]
            self.conn.send_many(cmds)

    # ─────────────────────────────────────────────────────────────────────────
    # Screenshots & DOM
    # ─────────────────────────────────────────────────────────────────────────

    def screenshot(
        self,
        format: str = "png",
        clip: dict | None = None,
        capture_beyond_viewport: bool = False,
    ) -> str:
        """Capture screenshot, return base64 data."""
        params: dict[str, Any] = {"format": format, "fromSurface": True}
        if clip:
            params["clip"] = clip
        if capture_beyond_viewport:
            # Best-effort: not supported by all Chrome versions.
            params["captureBeyondViewport"] = True
        result = self.conn.send("Page.captureScreenshot", params)
        return result.get("data", "")

    def get_dom(self, selector: str | None = None) -> str:
        """Get DOM HTML."""
        if selector:
            js = f"document.querySelector({json.dumps(selector)})?.outerHTML || ''"
        else:
            js = "document.documentElement.outerHTML"
        return self.eval_js(js) or ""


class SessionManager:
    """
    Singleton manager for the MCP session's isolated browser tab.

    Ensures each MCP process has its own tab for isolation.
    Thread-safe for single-process MCP servers.
    """

    _instance: SessionManager | None = None
    _session_tab_id: str | None = None

    def __new__(cls) -> SessionManager:
        if cls._instance is None:
            inst = super().__new__(cls)
            inst._bootstrap_scripts = {}
            inst._diagnostics_state = {}
            inst._telemetry = {}
            inst._telemetry_lock = threading.Lock()
            inst._tier0_buses = {}
            inst._affordances = {}
            inst._affordances_state = {}
            inst._affordances_lock = threading.Lock()
            inst._nav_graph = {}
            inst._nav_graph_lock = threading.Lock()
            inst._agent_memory = {}
            inst._agent_memory_lock = threading.Lock()
            inst._download_state = {}
            inst._download_lock = threading.Lock()
            inst._captcha_state = {}
            inst._captcha_lock = threading.Lock()
            inst._policy_mode = _normalize_policy_mode(os.environ.get("MCP_POLICY", "permissive"))
            inst._shared_session = None
            inst._shared_target = None
            inst._shared_refcount = 0
            inst._shared_cdp_port = None
            inst._tab_ws_urls = {}
            inst._extension_gateway = None
            inst._extension_gateway_error = None
            inst._auto_dialog = {}
            inst._auto_dialog_lock = threading.Lock()
            inst._auto_dialog_last_handled_ms = {}

            # Best-effort: load persisted agent memory (non-sensitive only by default).
            # This keeps the server restart-safe without leaking secrets by default.
            try:
                if inst._policy_mode != "strict":
                    from .agent_memory_persist import load_items

                    items = load_items()
                    if isinstance(items, dict):
                        with inst._agent_memory_lock:
                            for k, entry in items.items():
                                if not (isinstance(k, str) and k.strip()):
                                    continue
                                if not isinstance(entry, dict):
                                    continue
                                if entry.get("sensitive") is True or is_sensitive_key(k):
                                    continue
                                # Mark as loaded-from-disk (helps debugging without revealing values).
                                e = dict(entry)
                                e["persisted"] = True
                                inst._agent_memory[k] = e
            except Exception:
                pass
            cls._instance = inst
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton state (for testing)."""
        inst = cls._instance
        if inst is not None:
            try:
                buses = getattr(inst, "_tier0_buses", {}) or {}
                for bus in list(buses.values()):
                    if isinstance(bus, _Tier0EventBus):
                        bus.stop()
            except Exception:
                pass
        cls._instance = None
        cls._session_tab_id = None

    def recover_reset(self) -> dict[str, Any]:
        """Reset in-memory state for emergency recovery (no CDP calls).

        Use when the CDP endpoint/tab is in a bad state (timeouts, dialog brick, etc.).
        This is safe to call even if Chrome is not responding: it only clears local caches
        and stops background threads, preventing resource leaks and allowing a clean relaunch.
        """

        old_tab = self._session_tab_id

        shared_closed = False
        try:
            if isinstance(getattr(self, "_shared_session", None), BrowserSession):
                with suppress(Exception):
                    self._shared_session.close()
                shared_closed = True
        except Exception:
            shared_closed = False

        stopped_buses = 0
        try:
            buses = getattr(self, "_tier0_buses", {}) or {}
            for bus in list(buses.values()):
                if isinstance(bus, _Tier0EventBus):
                    stopped_buses += 1
                    with suppress(Exception):
                        bus.stop()
        except Exception:
            stopped_buses = 0

        # Clear local state (do not attempt any CDP calls).
        self._session_tab_id = None
        self._shared_session = None
        self._shared_target = None
        self._shared_refcount = 0
        self._shared_cdp_port = None

        with suppress(Exception):
            self._bootstrap_scripts.clear()
        with suppress(Exception):
            self._diagnostics_state.clear()
        with suppress(Exception):
            self._telemetry.clear()
        with suppress(Exception):
            self._tier0_buses.clear()
        with suppress(Exception):
            self._tab_ws_urls.clear()
        try:
            with suppress(Exception), self._auto_dialog_lock:
                self._auto_dialog.clear()
            self._auto_dialog_last_handled_ms.clear()
        except Exception:
            pass
        with suppress(Exception):
            self._affordances.clear()
        with suppress(Exception):
            self._affordances_state.clear()
        with suppress(Exception):
            self._nav_graph.clear()
        with suppress(Exception):
            self._agent_memory.clear()
        with suppress(Exception):
            self._download_state.clear()
        with suppress(Exception):
            self._captcha_state.clear()

        return {
            "clearedSessionTabId": old_tab,
            "sharedSessionClosed": shared_closed,
            "stoppedTier0Buses": stopped_buses,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # CAPTCHA state (workbench-grade stability for multi-step flows)
    # ─────────────────────────────────────────────────────────────────────────

    def set_captcha_state(self, tab_id: str, *, state: dict[str, Any]) -> None:
        """Persist the last CAPTCHA grid mapping for a tab (best-effort).

        This is used to make screenshot→click flows stable within a single `run`,
        avoiding re-analysis drift between steps.
        """
        if not isinstance(tab_id, str) or not tab_id:
            return
        if not isinstance(state, dict) or not state:
            return
        now_ms = int(time.time() * 1000)
        payload = {"ts": now_ms, **state}
        try:
            with self._captcha_lock:
                self._captcha_state[tab_id] = payload
        except Exception:
            pass

    def get_captcha_state(self, tab_id: str, *, max_age_ms: int = 90_000) -> dict[str, Any] | None:
        """Return recent CAPTCHA state for a tab (or None if missing/stale)."""
        if not isinstance(tab_id, str) or not tab_id:
            return None
        try:
            with self._captcha_lock:
                raw = self._captcha_state.get(tab_id)
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None
        try:
            ts = int(raw.get("ts") or 0)
        except Exception:
            ts = 0
        if ts <= 0:
            return None
        now_ms = int(time.time() * 1000)
        max_age_ms = max(0, int(max_age_ms))
        if max_age_ms and (now_ms - ts) > max_age_ms:
            return None
        return raw

    @property
    def tab_id(self) -> str | None:
        """Current session's tab ID."""
        return self._session_tab_id

    def set_extension_gateway(self, gateway: ExtensionGateway | None) -> None:
        """Attach an ExtensionGateway instance (used in MCP_BROWSER_MODE=extension)."""
        self._extension_gateway = gateway
        if gateway is not None:
            self._extension_gateway_error = None

    def get_extension_gateway(self) -> ExtensionGateway | None:
        gw = getattr(self, "_extension_gateway", None)
        return gw  # type: ignore[return-value]

    def set_extension_gateway_error(self, error: str | None) -> None:
        """Store an extension gateway startup/config error for AI-first diagnostics."""
        self._extension_gateway_error = str(error) if error else None

    def get_extension_gateway_error(self) -> str | None:
        err = getattr(self, "_extension_gateway_error", None)
        return err if isinstance(err, str) and err else None

    def _require_extension_gateway_connected(self) -> ExtensionGateway:
        gw = self.get_extension_gateway()
        if gw is None:
            err = self.get_extension_gateway_error()
            if err:
                raise HttpClientError(f"Extension gateway failed to start (mode=extension): {err}")
            raise HttpClientError("Extension gateway is not configured (mode=extension)")

        if not gw.is_connected():
            try:
                connect_timeout = float(os.environ.get("MCP_EXTENSION_CONNECT_TIMEOUT") or 2.0)
            except Exception:
                connect_timeout = 2.0
            connect_timeout = max(0.0, min(connect_timeout, 15.0))
            if connect_timeout > 0:
                gw.wait_for_connection(timeout=connect_timeout)

        if not gw.is_connected():
            raise HttpClientError(
                "Extension is not connected (mode=extension). "
                "Ensure the Browser MCP extension is installed/enabled in your normal Chrome profile. "
                "Connection should be automatic; if you just updated the repo, reload the unpacked extension."
            )
        return gw

    def _get_targets(self, config: BrowserConfig) -> list:
        """Get list of browser targets."""
        try:
            return _http_get_json(f"http://127.0.0.1:{config.cdp_port}/json/list") or []
        except (OSError, json.JSONDecodeError, ValueError):
            return []

    def _get_browser_ws(self, config: BrowserConfig) -> str:
        """Get browser-level WebSocket URL."""
        version = _http_get_json(f"http://127.0.0.1:{config.cdp_port}/json/version")
        ws_url = version.get("webSocketDebuggerUrl")
        if not ws_url:
            raise HttpClientError("CDP browser WebSocket URL not found")
        return ws_url

    def _create_tab(self, config: BrowserConfig, url: str = "about:blank") -> str:
        """Create a new browser tab, return tab ID."""
        browser_ws = self._get_browser_ws(config)
        conn = CdpConnection(browser_ws, timeout=5.0)
        try:
            result = conn.send("Target.createTarget", {"url": url})
            tab_id = result.get("targetId")
            if not tab_id:
                raise HttpClientError("Failed to create browser tab")
            return tab_id
        finally:
            conn.close()

    def _get_tab_ws_url(self, config: BrowserConfig, tab_id: str) -> str | None:
        """Get WebSocket URL for specific tab."""
        targets = self._get_targets(config)
        for target in targets:
            if target.get("id") == tab_id:
                return target.get("webSocketDebuggerUrl")
        return None

    def _ensure_session_tab(self, config: BrowserConfig) -> str:
        """Ensure session has an isolated tab, create if needed."""
        if getattr(config, "mode", "launch") == "extension":
            gw = self._require_extension_gateway_connected()

            # Multi-client safety: when this process is proxying through another Browser MCP
            # instance, avoid implicitly adopting the user's active tab. Peers should default to
            # isolated tabs to prevent cross-agent interference.
            force_isolated = bool(getattr(gw, "is_proxy", False))
            if os.environ.get("MCP_EXTENSION_FORCE_NEW_TAB") == "1":
                force_isolated = True

            def _ext_get(tab_id: str) -> dict[str, Any] | None:
                try:
                    info = gw.rpc_call("tabs.get", {"tabId": str(tab_id)}, timeout=2.0)
                except Exception:
                    info = None
                return info if isinstance(info, dict) else None

            # Check if current tab still exists
            if self._session_tab_id:
                info = _ext_get(self._session_tab_id)
                if isinstance(info, dict) and str(info.get("id") or ""):
                    return self._session_tab_id
                self._session_tab_id = None

            # Create new isolated tab
            # UX-first default: if the extension is configured to follow the user's active tab,
            # adopt it as the session tab (no surprise "new tab" unless needed).
            follow_active = False
            focused = ""
            if not force_isolated:
                try:
                    st = gw.rpc_call("state.get", {}, timeout=1.5)
                except Exception:
                    st = None
                try:
                    follow_active = bool(st.get("followActive")) if isinstance(st, dict) else False
                    focused = str(st.get("focusedTabId") or "").strip() if isinstance(st, dict) else ""
                except Exception:
                    follow_active = False
                    focused = ""

            if follow_active and focused:
                info = _ext_get(focused)
                url = str(info.get("url") or "") if isinstance(info, dict) else ""
                if url and not (url.startswith("chrome://") or url.startswith("chrome-extension://")):
                    self._session_tab_id = focused
                    return self._session_tab_id

            created = gw.rpc_call("tabs.create", {"url": "about:blank", "active": True}, timeout=5.0)
            new_id = None
            if isinstance(created, dict):
                new_id = created.get("tabId") or created.get("id")
            elif isinstance(created, (int, str)):
                new_id = created
            new_id_s = str(new_id or "").strip()
            if not new_id_s:
                raise HttpClientError("Failed to create browser tab (extension mode)")
            self._session_tab_id = new_id_s
            return self._session_tab_id

        # Check if current tab still exists
        if self._session_tab_id:
            ws_url = self._get_tab_ws_url(config, self._session_tab_id)
            if ws_url:
                return self._session_tab_id
            # Tab was closed, need new one
            self._session_tab_id = None

        # Create new isolated tab
        self._session_tab_id = self._create_tab(config, "about:blank")
        return self._session_tab_id

    def ensure_diagnostics(self, session: BrowserSession) -> dict[str, Any]:
        """Install in-page diagnostics instrumentation (best-effort).

        Controlled via env var:
        - MCP_DIAGNOSTICS=0 disables instrumentation
        """

        if os.environ.get("MCP_DIAGNOSTICS", "1") == "0":
            return {"enabled": False}

        tab_id = session.tab_id
        if not tab_id:
            return {"enabled": False}

        # IMPORTANT: never rely on Python truthiness of JS return values.
        # We require a strict boolean `true` and validate a minimal contract:
        # - __mcpDiag exists
        # - __version matches
        # - snapshot() is a function (instrumentation is actually usable)
        check_expr = (
            "("
            "globalThis.__mcpDiag && "
            f"globalThis.__mcpDiag.__version === {json.dumps(DIAGNOSTICS_SCRIPT_VERSION)} && "
            "typeof globalThis.__mcpDiag.snapshot === 'function'"
            ") === true"
        )

        now_ts = time.time()
        force_inject = False
        state = self._diagnostics_state.get(tab_id)
        if (
            isinstance(state, dict)
            and state.get("version") == DIAGNOSTICS_SCRIPT_VERSION
            and state.get("available") is True
            and isinstance(state.get("lastCheck"), (int, float))
            and now_ts - float(state["lastCheck"]) < 10
        ):
            # IMPORTANT: on full navigations / reloads some pages may wipe globals,
            # while our cache still says "available". Re-check cheaply before returning cached.
            still_available = False
            try:
                still_available = session.eval_js(check_expr, timeout=0.7) is True
            except Exception:
                still_available = False

            if still_available:
                state["lastCheck"] = now_ts
                return {
                    "enabled": True,
                    "cached": True,
                    "available": True,
                    "scriptId": state.get("scriptId"),
                    "tabId": tab_id,
                }
            # Otherwise: fall through to reinstall / re-add script.
            force_inject = True

        session.enable_page()

        script_key = f"mcp_diag_v{DIAGNOSTICS_SCRIPT_VERSION}"
        scripts: dict[str, str] = self._bootstrap_scripts.setdefault(tab_id, {})
        script_id = scripts.get(script_key)

        if not script_id:
            try:
                res = session.send(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {"source": DIAGNOSTICS_SCRIPT_SOURCE},
                )
                identifier = res.get("identifier")
                if isinstance(identifier, str) and identifier:
                    script_id = identifier
                    scripts[script_key] = identifier
            except Exception:
                # Best-effort only; do not break tool execution.
                script_id = None

        available = False
        try:
            available = session.eval_js(check_expr, timeout=0.7) is True
        except Exception:
            available = False

        if (not available) or force_inject:
            with suppress(Exception):
                session.eval_js(DIAGNOSTICS_SCRIPT_SOURCE, timeout=1.2)

            try:
                available = session.eval_js(check_expr, timeout=0.7) is True
            except Exception:
                available = False

        self._diagnostics_state[tab_id] = {
            "version": DIAGNOSTICS_SCRIPT_VERSION,
            "available": available,
            "scriptId": script_id,
            "lastCheck": now_ts,
        }

        return {"enabled": True, "available": available, "scriptId": script_id, "tabId": tab_id}

    def ensure_telemetry(self, session: BrowserSession) -> dict[str, Any]:
        """Enable Tier-0 CDP telemetry and attach an event sink (best-effort).

        Controlled via env var:
        - MCP_TIER0=0 disables Tier-0 telemetry.
        """

        if os.environ.get("MCP_TIER0", "1") == "0":
            return {"enabled": False}

        tab_id = session.tab_id
        if not tab_id:
            return {"enabled": False}

        # Extension mode: events are pushed by the extension gateway; do not start a WS reader.
        if isinstance(getattr(session, "conn", None), ExtensionCdpConnection):
            telemetry = self._telemetry.get(tab_id)
            if not isinstance(telemetry, Tier0Telemetry):
                telemetry = Tier0Telemetry()
                self._telemetry[tab_id] = telemetry

            # Enable domains that emit high-signal events. Best-effort; ignore failures.
            with suppress(Exception):
                session.enable_domains(page=True, runtime=True, network=True, log=True, strict=False)

            return {"enabled": True, "tabId": tab_id, "cursor": telemetry.cursor, "mode": "extension"}

        # Keep the latest WS URL for this tab (used for dialog auto-handling and recovery).
        try:
            if isinstance(session.conn.ws_url, str) and session.conn.ws_url:
                self._tab_ws_urls[tab_id] = session.conn.ws_url
        except Exception:
            pass

        # Ensure buffers exist.
        telemetry = self._telemetry.get(tab_id)
        if not isinstance(telemetry, Tier0Telemetry):
            telemetry = Tier0Telemetry()
            self._telemetry[tab_id] = telemetry

        # Start a background event bus so Tier-0 works even between tool calls.
        with suppress(Exception):
            self._ensure_tier0_bus(tab_id=tab_id, ws_url=session.conn.ws_url)

        # If a background bus is active for this tab, avoid ingesting events from the
        # tool-call connection as well (prevents double-counting / duplicate signals).
        bus_active = False
        try:
            bus = self._tier0_buses.get(tab_id)
            bus_active = isinstance(bus, _Tier0EventBus) and bus.ws_url == session.conn.ws_url
        except Exception:
            bus_active = False

        if not bus_active:
            # Fallback: attach event sink for this connection (used when MCP_TIER0=0
            # or when the background bus failed to start).
            with suppress(Exception):
                session.conn.set_event_sink(lambda ev, tid=tab_id: self._ingest_tier0_event(tid, ev))
        else:
            # Even with a background Tier-0 bus, attach a tiny dialog-only sink.
            # This improves reliability for dialogs that open immediately after a click,
            # before the bus has fully reconnected, without duplicating noisy streams.
            def _dialog_only_sink(ev: dict[str, Any], tid: str = tab_id) -> None:
                try:
                    m = ev.get("method") if isinstance(ev, dict) else None
                    if m in {"Page.javascriptDialogOpening", "Page.javascriptDialogClosed"}:
                        self._ingest_tier0_event(tid, ev)
                except Exception:
                    return

            with suppress(Exception):
                session.conn.set_event_sink(_dialog_only_sink)

        # Enable domains that emit high-signal events. Best-effort; ignore failures.
        with suppress(Exception):
            session.enable_domains(page=True, runtime=True, network=True, log=True, strict=False)

        return {"enabled": True, "tabId": tab_id, "cursor": telemetry.cursor}

    def _ingest_tier0_event(self, tab_id: str, event: dict[str, Any]) -> None:
        method = event.get("method") if isinstance(event, dict) else None
        with self._telemetry_lock:
            telemetry = self._telemetry.get(tab_id)
            if not isinstance(telemetry, Tier0Telemetry):
                telemetry = Tier0Telemetry()
                self._telemetry[tab_id] = telemetry
            telemetry.ingest(event)

        # Async dialog auto-handling: if a dialog opens while a tool call is waiting on CDP,
        # handle it out-of-band to avoid long timeouts/hangs. This is used by run/flow.
        if method == "Page.javascriptDialogOpening":
            mode = self.get_auto_dialog_mode(tab_id)
            if mode in {"accept", "dismiss"}:
                self._schedule_auto_dialog_handle(tab_id, accept=(mode == "accept"))

    def _ensure_tier0_bus(self, *, tab_id: str, ws_url: str) -> None:
        if os.environ.get("MCP_TIER0", "1") == "0":
            return
        if not tab_id or not ws_url:
            return

        bus = self._tier0_buses.get(tab_id)
        if isinstance(bus, _Tier0EventBus) and bus.ws_url == ws_url:
            # Assume alive; it is best-effort and daemonized.
            return

        # Stop old bus (if any) and replace.
        if isinstance(bus, _Tier0EventBus):
            with suppress(Exception):
                bus.stop()

        bus = _Tier0EventBus(
            ws_url=ws_url,
            on_event=lambda ev, tid=tab_id: self._ingest_tier0_event(tid, ev),
            name=f"mcp-tier0-{tab_id[:6]}",
        )
        self._tier0_buses[tab_id] = bus
        bus.start()

    def clear_telemetry(self, tab_id: str) -> None:
        with self._telemetry_lock:
            telemetry = self._telemetry.get(tab_id)
            if not isinstance(telemetry, Tier0Telemetry):
                return
            telemetry.console.clear()
            telemetry.errors.clear()
            telemetry.network.clear()
            telemetry.harLite.clear()
            telemetry.dialogs.clear()
            telemetry.dialog_open = False
            telemetry.dialog_last = None
            telemetry.navigation.clear()
            telemetry._req.clear()  # type: ignore[attr-defined]
            telemetry._req_done.clear()  # type: ignore[attr-defined]

    def clear_har_lite(self, tab_id: str) -> None:
        """Clear only HAR-lite buffer (Tier-0), leaving other buffers intact."""
        with self._telemetry_lock:
            telemetry = self._telemetry.get(tab_id)
            if not isinstance(telemetry, Tier0Telemetry):
                return
            telemetry.harLite.clear()

    def clear_net_trace(self, tab_id: str) -> None:
        """Clear Tier-0 net trace buffer (recent completed request cache)."""
        with self._telemetry_lock:
            telemetry = self._telemetry.get(tab_id)
            if not isinstance(telemetry, Tier0Telemetry):
                return
            telemetry._req_done.clear()  # type: ignore[attr-defined]

    def note_dialog_closed(
        self,
        tab_id: str,
        *,
        accepted: bool | None = None,
        user_input: str | None = None,
    ) -> None:
        """Best-effort: mark a JS dialog as closed in Tier-0 telemetry.

        This is used to keep dialogOpen state consistent across tool calls when
        the page emits `Page.javascriptDialogOpening` but the corresponding
        `...Closed` event is missed (common in brittle dialog-brick scenarios).
        """
        if not isinstance(tab_id, str) or not tab_id:
            return

        params: dict[str, Any] = {}
        if isinstance(accepted, bool):
            params["result"] = bool(accepted)
        if isinstance(user_input, str) and user_input:
            params["userInput"] = user_input

        ev: dict[str, Any] = {"method": "Page.javascriptDialogClosed", "params": params}

        with self._telemetry_lock:
            telemetry = self._telemetry.get(tab_id)
            if not isinstance(telemetry, Tier0Telemetry):
                telemetry = Tier0Telemetry()
                self._telemetry[tab_id] = telemetry
            telemetry.ingest(ev)

    def get_telemetry(self, tab_id: str) -> Tier0Telemetry | None:
        with self._telemetry_lock:
            telemetry = self._telemetry.get(tab_id)
            return telemetry if isinstance(telemetry, Tier0Telemetry) else None

    def tier0_snapshot(self, tab_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Thread-safe Tier-0 snapshot helper."""
        with self._telemetry_lock:
            telemetry = self._telemetry.get(tab_id)
            if not isinstance(telemetry, Tier0Telemetry):
                return None
            return telemetry.snapshot(**kwargs)

    # ─────────────────────────────────────────────────────────────────────────
    # Auto-dialog (best-effort)
    # ─────────────────────────────────────────────────────────────────────────

    def set_auto_dialog(self, tab_id: str, mode: str, *, ttl_s: float = 60.0) -> None:
        """Enable best-effort dialog auto-handling for a tab (used by run/flow).

        This is intentionally small and temporary:
        - Stored per tab_id
        - TTL-based (expires automatically)
        - Only supports accept/dismiss/off
        """
        if not isinstance(tab_id, str) or not tab_id:
            return
        m = str(mode or "").strip().lower()
        if m in {"accept", "ok", "yes"}:
            m = "accept"
        elif m in {"dismiss", "cancel", "no"}:
            m = "dismiss"
        else:
            m = "off"

        try:
            ttl = float(ttl_s)
        except Exception:
            ttl = 60.0
        ttl = max(0.0, min(ttl, 10 * 60.0))
        until = (time.time() + ttl) if m != "off" else 0.0

        try:
            with self._auto_dialog_lock:
                if m == "off":
                    self._auto_dialog.pop(tab_id, None)
                else:
                    self._auto_dialog[tab_id] = {"mode": m, "until": until}
        except Exception:
            pass

    def clear_auto_dialog(self, tab_id: str) -> None:
        if not isinstance(tab_id, str) or not tab_id:
            return
        try:
            with self._auto_dialog_lock:
                self._auto_dialog.pop(tab_id, None)
        except Exception:
            pass

    def get_auto_dialog_mode(self, tab_id: str) -> str:
        """Return active auto-dialog mode for tab_id: accept|dismiss|off."""
        if not isinstance(tab_id, str) or not tab_id:
            return "off"
        try:
            with self._auto_dialog_lock:
                rec = self._auto_dialog.get(tab_id)
        except Exception:
            rec = None
        if not isinstance(rec, dict):
            return "off"
        mode = rec.get("mode")
        until = rec.get("until")
        if not (isinstance(mode, str) and mode in {"accept", "dismiss"}):
            return "off"
        try:
            if isinstance(until, (int, float)) and until > 0 and time.time() > float(until):
                with suppress(Exception), self._auto_dialog_lock:
                    self._auto_dialog.pop(tab_id, None)
                return "off"
        except Exception:
            return "off"
        return mode

    def _schedule_auto_dialog_handle(self, tab_id: str, *, accept: bool) -> None:
        """Handle a JS dialog out-of-band to unblock stuck tool calls (best-effort)."""
        # Throttle to avoid storms on repeated events.
        now_ms = int(time.time() * 1000)
        try:
            last = int(self._auto_dialog_last_handled_ms.get(tab_id) or 0)
        except Exception:
            last = 0
        if last and (now_ms - last) < 500:
            return
        self._auto_dialog_last_handled_ms[tab_id] = now_ms

        # Extension mode: handle via gateway (no direct WS access).
        gw = self.get_extension_gateway()
        if gw is not None and gw.is_connected():

            def _worker_ext() -> None:
                try:
                    gw.cdp_send_many(
                        tab_id,
                        commands=[
                            {"method": "Page.enable", "params": {}},
                            {"method": "Page.handleJavaScriptDialog", "params": {"accept": bool(accept)}},
                        ],
                        timeout=1.5,
                        stop_on_error=True,
                    )
                    with suppress(Exception):
                        self.note_dialog_closed(tab_id, accepted=bool(accept))
                except Exception:
                    return

            try:
                t = threading.Thread(
                    target=_worker_ext,
                    name=f"mcp-auto-dialog-ext-{tab_id[:6]}",
                    daemon=True,
                )
                t.start()
            except Exception:
                _worker_ext()
            return

        ws_url = None
        try:
            bus = self._tier0_buses.get(tab_id)
            if isinstance(bus, _Tier0EventBus) and isinstance(bus.ws_url, str) and bus.ws_url:
                ws_url = bus.ws_url
        except Exception:
            ws_url = None
        if not ws_url:
            try:
                ws_url = self._tab_ws_urls.get(tab_id)
            except Exception:
                ws_url = None
        if not (isinstance(ws_url, str) and ws_url):
            return

        def _worker() -> None:
            conn = None
            try:
                conn = CdpConnection(ws_url, timeout=1.5)
                # Best-effort: some Chrome builds are pickier about dialog handling unless
                # the Page domain is enabled on the connection that issues the command.
                with suppress(Exception):
                    conn.send("Page.enable")
                conn.send("Page.handleJavaScriptDialog", {"accept": bool(accept)})
                with suppress(Exception):
                    self.note_dialog_closed(tab_id, accepted=bool(accept))
            except Exception:
                # Best-effort only; never escalate from a background auto-handler.
                return
            finally:
                with suppress(Exception):
                    if conn is not None:
                        conn.close()

        try:
            t = threading.Thread(target=_worker, name=f"mcp-auto-dialog-{tab_id[:6]}", daemon=True)
            t.start()
        except Exception:
            # Fall back to synchronous best-effort (still bounded by conn timeout).
            _worker()

    # ─────────────────────────────────────────────────────────────────────────
    # Affordances (stable, cognitive-cheap action refs)
    # ─────────────────────────────────────────────────────────────────────────

    def set_affordances(
        self,
        tab_id: str,
        *,
        items: list[dict[str, Any]],
        url: str | None = None,
        cursor: int | None = None,
    ) -> None:
        """Replace the affordance mapping for a tab (best-effort).

        Each item must be a dict with:
        - ref: "aff:<hash>"
        - tool: tool name (e.g., "click", "form")
        - args: dict of tool arguments

        The mapping is intentionally small and best-effort:
        - Stored per-tab.
        - Replaced on each new `page()` / triage / locators observation.

        Note:
        - Refs are stable hashes derived from {tool,args,meta}; they may survive
          simple reorders but will naturally change when the underlying semantics change.
        """

        if not isinstance(tab_id, str) or not tab_id:
            return
        if not isinstance(items, list):
            return

        mapping: dict[str, dict[str, Any]] = {}
        for it in items[:100]:
            if not isinstance(it, dict):
                continue
            ref = it.get("ref")
            tool = it.get("tool")
            args = it.get("args")
            if not (isinstance(ref, str) and ref.startswith("aff:")):
                continue
            if not (isinstance(tool, str) and tool):
                continue
            if not isinstance(args, dict):
                continue
            mapping[ref] = {
                "tool": tool,
                "args": args,
                **({"meta": it.get("meta")} if isinstance(it.get("meta"), dict) else {}),
            }

        with self._affordances_lock:
            self._affordances[tab_id] = mapping
            self._affordances_state[tab_id] = {
                "url": url if isinstance(url, str) and url else None,
                "cursor": int(cursor) if isinstance(cursor, int) else None,
                "updatedAt": int(time.time() * 1000),
                "count": len(mapping),
            }

    def resolve_affordance(self, tab_id: str, ref: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Resolve an affordance ref ("aff:N") to a concrete tool spec."""
        if not (isinstance(tab_id, str) and tab_id):
            return None, None
        if not (isinstance(ref, str) and ref.startswith("aff:")):
            return None, None
        with self._affordances_lock:
            mapping = self._affordances.get(tab_id)
            state = self._affordances_state.get(tab_id)
            if not isinstance(mapping, dict):
                return None, state if isinstance(state, dict) else None
            item = mapping.get(ref)
            return (item if isinstance(item, dict) else None, state if isinstance(state, dict) else None)

    def resolve_affordance_by_label(
        self,
        tab_id: str,
        *,
        label: str,
        kind: str | None = None,
        index: int | None = None,
        max_matches: int = 10,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
        """Resolve an affordance by a deterministic, exact label match.

        This is an *in-memory* resolver only:
        - It never performs any CDP calls.
        - It relies on affordances previously stored via set_affordances() (page locators/triage/map).

        Semantics
        - Exact match after whitespace normalization + lowercasing.
        - If multiple matches exist and index is None: return (None, state, matches).
        - If index is provided: select matches[index] (0-based), otherwise error.
        """

        if not (isinstance(tab_id, str) and tab_id):
            return None, None, []

        raw_label = str(label or "")
        q = " ".join(raw_label.split()).strip().lower()
        if not q:
            return None, None, []

        kind_norm = str(kind or "").strip().lower() if kind is not None else ""
        if kind_norm in {"", "all"}:
            kind_norm = ""
        elif kind_norm not in {"button", "link", "input"}:
            # Unknown kind: treat as non-match (caller should surface a validation error).
            kind_norm = "__invalid__"

        with self._affordances_lock:
            mapping = self._affordances.get(tab_id)
            state = self._affordances_state.get(tab_id)

        state_out = state if isinstance(state, dict) else None
        if not isinstance(mapping, dict) or not mapping:
            return None, state_out, []

        def _cand_label(meta: dict[str, Any] | None) -> str:
            if not isinstance(meta, dict):
                return ""
            for k in ("text", "name", "fillKey", "id", "placeholder", "selector"):
                v = meta.get(k)
                if isinstance(v, str) and v.strip():
                    return " ".join(v.split()).strip()
            return ""

        matches: list[dict[str, Any]] = []
        for ref, spec in mapping.items():
            if not (isinstance(ref, str) and ref.startswith("aff:")):
                continue
            if not isinstance(spec, dict):
                continue
            meta = spec.get("meta") if isinstance(spec.get("meta"), dict) else None

            if kind_norm:
                mk = str(meta.get("kind") or "").strip().lower() if isinstance(meta, dict) else ""
                if mk != kind_norm:
                    continue

            lbl = _cand_label(meta)
            if not lbl:
                continue
            if " ".join(lbl.split()).strip().lower() != q:
                continue

            matches.append(
                {
                    "ref": ref,
                    **({"kind": meta.get("kind")} if isinstance(meta, dict) and meta.get("kind") else {}),
                    "label": lbl,
                    **({"tool": spec.get("tool")} if isinstance(spec.get("tool"), str) else {}),
                }
            )
            if len(matches) >= max(0, int(max_matches)):
                break

        matches.sort(key=lambda m: (str(m.get("kind") or ""), str(m.get("label") or ""), str(m.get("ref") or "")))

        if not matches:
            return None, state_out, []
        if len(matches) > 1 and index is None:
            return None, state_out, matches

        if index is None:
            pick = 0
        else:
            try:
                pick = int(index)
            except Exception:
                return None, state_out, matches

        if pick < 0 or pick >= len(matches):
            return None, state_out, matches

        chosen_ref = matches[pick].get("ref")
        if not isinstance(chosen_ref, str) or not chosen_ref:
            return None, state_out, matches

        chosen = mapping.get(chosen_ref)
        if isinstance(chosen, dict):
            return ({"ref": chosen_ref, **chosen}, state_out, matches)
        return (None, state_out, matches)

    # ─────────────────────────────────────────────────────────────────────────
    # Navigation graph (best-effort, bounded)
    # ─────────────────────────────────────────────────────────────────────────

    def note_nav_graph_observation(
        self,
        tab_id: str,
        *,
        url: str,
        title: str | None = None,
        link_edges: list[dict[str, Any]] | None = None,
        max_nodes: int = 30,
        max_edges: int = 60,
    ) -> dict[str, Any] | None:
        """Update the per-tab navigation graph from an observation (map/triage/locators).

        This method is intentionally:
        - in-memory only (no CDP calls)
        - safe-by-default (drops query/fragment)
        - bounded (prunes to max_nodes/max_edges)
        """

        if not (isinstance(tab_id, str) and tab_id):
            return None

        raw_url = str(url or "").strip()
        if not raw_url:
            return None

        def _redact(u: str) -> str:
            try:
                parts = urlsplit(u)
                return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            except Exception:
                return u

        def _node_id(u: str) -> str:
            digest = hashlib.sha1(u.encode("utf-8")).hexdigest()[:10]
            return f"nav:{digest}"

        def _edge_id(*, src: str, dst: str, kind: str, label: str | None, ref: str | None) -> str:
            blob = "|".join(
                [
                    src,
                    dst,
                    kind,
                    (label or ""),
                    (ref or ""),
                ]
            )
            digest = hashlib.sha1(blob.encode("utf-8")).hexdigest()[:10]
            return f"edge:{digest}"

        def _prune(nodes: dict[str, dict[str, Any]], edges: dict[str, dict[str, Any]]) -> None:
            # Keep the most recently seen nodes.
            keep_n = max(1, min(int(max_nodes), 200))
            keep_e = max(0, min(int(max_edges), 500))

            def _ts(d: dict[str, Any]) -> int:
                try:
                    return int(d.get("lastSeenAt") or 0)
                except Exception:
                    return 0

            if len(nodes) > keep_n:
                ordered = sorted(nodes.values(), key=lambda n: (-_ts(n), str(n.get("id") or "")))
                keep_ids = {str(n.get("id")) for n in ordered[:keep_n] if isinstance(n, dict) and n.get("id")}
                for nid in list(nodes.keys()):
                    if nid not in keep_ids:
                        nodes.pop(nid, None)
                # Drop edges that reference missing nodes.
                for eid, e in list(edges.items()):
                    if not isinstance(e, dict):
                        edges.pop(eid, None)
                        continue
                    if str(e.get("from") or "") not in nodes or str(e.get("to") or "") not in nodes:
                        edges.pop(eid, None)

            if len(edges) > keep_e:
                ordered_e = sorted(edges.values(), key=lambda e: (-_ts(e), str(e.get("id") or "")))
                keep_edge_ids = {str(e.get("id")) for e in ordered_e[:keep_e] if isinstance(e, dict) and e.get("id")}
                for eid in list(edges.keys()):
                    if eid not in keep_edge_ids:
                        edges.pop(eid, None)

        now_ms = int(time.time() * 1000)
        url_redacted = _redact(raw_url)
        cur_id = _node_id(url_redacted)
        title_str = str(title).strip() if isinstance(title, str) and title.strip() else None

        with self._nav_graph_lock:
            graph = self._nav_graph.get(tab_id)
            if not isinstance(graph, dict):
                graph = {"nodes": {}, "edges": {}, "current": None, "updatedAt": None}
                self._nav_graph[tab_id] = graph

            nodes = graph.get("nodes")
            edges = graph.get("edges")
            if not isinstance(nodes, dict):
                nodes = {}
                graph["nodes"] = nodes
            if not isinstance(edges, dict):
                edges = {}
                graph["edges"] = edges

            prev_id = graph.get("current") if isinstance(graph.get("current"), str) else None

            # Upsert current node.
            node = nodes.get(cur_id)
            if not isinstance(node, dict):
                node = {"id": cur_id, "url": url_redacted, "firstSeenAt": now_ms, "visits": 0}
            node["url"] = url_redacted
            if title_str:
                node["title"] = title_str
            try:
                node["visits"] = int(node.get("visits") or 0) + 1
            except Exception:
                node["visits"] = 1
            node["lastSeenAt"] = now_ms
            nodes[cur_id] = node

            # Transition edge (between last observed page and current page).
            if prev_id and prev_id != cur_id:
                eid = _edge_id(src=prev_id, dst=cur_id, kind="nav", label=None, ref=None)
                e = edges.get(eid)
                if not isinstance(e, dict):
                    e = {"id": eid, "from": prev_id, "to": cur_id, "kind": "nav", "count": 0, "firstSeenAt": now_ms}
                try:
                    e["count"] = int(e.get("count") or 0) + 1
                except Exception:
                    e["count"] = 1
                e["lastSeenAt"] = now_ms
                edges[eid] = e

            graph["current"] = cur_id

            # Link affordance edges (bounded).
            if isinstance(link_edges, list):
                for it in link_edges[:50]:
                    if not isinstance(it, dict):
                        continue
                    to_raw = it.get("to")
                    if not isinstance(to_raw, str) or not to_raw.strip():
                        continue
                    to_url = _redact(to_raw.strip())
                    to_id = _node_id(to_url)

                    # Create a node stub for the target.
                    if to_id not in nodes:
                        nodes[to_id] = {
                            "id": to_id,
                            "url": to_url,
                            "firstSeenAt": now_ms,
                            "visits": 0,
                            "lastSeenAt": now_ms,
                        }
                    else:
                        try:
                            nodes[to_id]["lastSeenAt"] = max(int(nodes[to_id].get("lastSeenAt") or 0), now_ms)
                        except Exception:
                            nodes[to_id]["lastSeenAt"] = now_ms

                    label = it.get("label") if isinstance(it.get("label"), str) and it.get("label") else None
                    ref = it.get("ref") if isinstance(it.get("ref"), str) and it.get("ref") else None
                    eid = _edge_id(src=cur_id, dst=to_id, kind="link", label=label, ref=ref)
                    e = edges.get(eid)
                    if not isinstance(e, dict):
                        e = {
                            "id": eid,
                            "from": cur_id,
                            "to": to_id,
                            "kind": "link",
                            **({"label": label} if label else {}),
                            **({"ref": ref} if ref else {}),
                            "count": 0,
                            "firstSeenAt": now_ms,
                        }
                    try:
                        e["count"] = int(e.get("count") or 0) + 1
                    except Exception:
                        e["count"] = 1
                    e["lastSeenAt"] = now_ms
                    edges[eid] = e

            _prune(nodes, edges)
            graph["updatedAt"] = now_ms

            return {"current": cur_id, "nodes": len(nodes), "edges": len(edges), "updatedAt": now_ms}

    def get_nav_graph_view(
        self,
        tab_id: str,
        *,
        node_limit: int = 30,
        edge_limit: int = 60,
    ) -> dict[str, Any] | None:
        if not (isinstance(tab_id, str) and tab_id):
            return None
        node_limit = max(0, min(int(node_limit), 200))
        edge_limit = max(0, min(int(edge_limit), 500))

        with self._nav_graph_lock:
            graph = self._nav_graph.get(tab_id)
            if not isinstance(graph, dict):
                return None
            nodes = graph.get("nodes") if isinstance(graph.get("nodes"), dict) else {}
            edges = graph.get("edges") if isinstance(graph.get("edges"), dict) else {}
            current = graph.get("current") if isinstance(graph.get("current"), str) else None
            updated_at = graph.get("updatedAt")

            def _ts(d: dict[str, Any]) -> int:
                try:
                    return int(d.get("lastSeenAt") or 0)
                except Exception:
                    return 0

            node_items = [n for n in nodes.values() if isinstance(n, dict)]
            edge_items = [e for e in edges.values() if isinstance(e, dict)]
            node_items.sort(key=lambda n: (-_ts(n), str(n.get("id") or "")))
            edge_items.sort(key=lambda e: (-_ts(e), str(e.get("id") or "")))

            return {
                "summary": {"nodes": len(nodes), "edges": len(edges)},
                **({"current": current} if current else {}),
                "nodes": node_items[:node_limit],
                "edges": edge_items[:edge_limit],
                **({"updatedAt": updated_at} if updated_at is not None else {}),
            }

    # ─────────────────────────────────────────────────────────────────────────
    # Agent memory (safe-by-default KV)
    # ─────────────────────────────────────────────────────────────────────────

    def memory_set(
        self,
        *,
        key: str,
        value: Any,
        max_bytes: int = 20_000,
        max_keys: int = 200,
    ) -> dict[str, Any]:
        """Store a JSON-serializable value for later reuse.

        Notes:
        - Stored values are NOT echoed in tool outputs by default (handler controls reveal).
        - Keys are global to this server instance (not per-tab).
        - Values are bounded by size; oldest keys are evicted when over max_keys.
        """

        k = str(key or "").strip()
        if not k:
            raise ValueError("missing key")
        if len(k) > 128:
            raise ValueError("key too long")
        if not re.match(r"^[A-Za-z0-9_.-]+$", k):
            raise ValueError("invalid key")

        try:
            raw = json.dumps(value, ensure_ascii=True)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("value is not JSON-serializable") from exc

        b = len(raw.encode("utf-8"))
        max_bytes = max(100, min(int(max_bytes), 500_000))
        if b > max_bytes:
            raise ValueError("value too large")

        now_ms = int(time.time() * 1000)
        sensitive = is_sensitive_key(k)

        with self._agent_memory_lock:
            entry = self._agent_memory.get(k)
            if not isinstance(entry, dict):
                entry = {"createdAt": now_ms}
            entry.update(
                {
                    "key": k,
                    "value": value,
                    "bytes": b,
                    "sensitive": bool(sensitive),
                    "updatedAt": now_ms,
                }
            )
            self._agent_memory[k] = entry

            # Evict oldest keys if we exceed max_keys.
            max_keys = max(1, min(int(max_keys), 2000))
            if len(self._agent_memory) > max_keys:
                ordered = [
                    (str(kk), vv)
                    for kk, vv in self._agent_memory.items()
                    if isinstance(kk, str) and isinstance(vv, dict)
                ]
                ordered.sort(key=lambda it: int(it[1].get("updatedAt") or 0))
                for kk, _vv in ordered[: max(0, len(self._agent_memory) - max_keys)]:
                    self._agent_memory.pop(kk, None)

        return {
            "key": k,
            "bytes": b,
            "sensitive": bool(sensitive),
            "updatedAt": now_ms,
        }

    def memory_get(self, *, key: str) -> dict[str, Any] | None:
        k = str(key or "").strip()
        if not k:
            return None
        with self._agent_memory_lock:
            entry = self._agent_memory.get(k)
            return dict(entry) if isinstance(entry, dict) else None

    def memory_delete(self, *, key: str) -> bool:
        k = str(key or "").strip()
        if not k:
            return False
        with self._agent_memory_lock:
            return self._agent_memory.pop(k, None) is not None

    def memory_clear(self, *, prefix: str | None = None) -> int:
        pref = str(prefix or "").strip()
        with self._agent_memory_lock:
            if not pref:
                n = len(self._agent_memory)
                self._agent_memory.clear()
                return n
            keys = [k for k in self._agent_memory if isinstance(k, str) and k.startswith(pref)]
            for k in keys:
                self._agent_memory.pop(k, None)
            return len(keys)

    def memory_list(self, *, prefix: str | None = None) -> list[dict[str, Any]]:
        pref = str(prefix or "").strip()
        with self._agent_memory_lock:
            items = []
            for k, entry in self._agent_memory.items():
                if not isinstance(k, str):
                    continue
                if pref and not k.startswith(pref):
                    continue
                if not isinstance(entry, dict):
                    continue
                items.append(
                    {
                        "key": k,
                        **({"bytes": entry.get("bytes")} if isinstance(entry.get("bytes"), int) else {}),
                        **({"updatedAt": entry.get("updatedAt")} if isinstance(entry.get("updatedAt"), int) else {}),
                        **({"sensitive": True} if entry.get("sensitive") is True else {}),
                    }
                )
        items.sort(key=lambda it: str(it.get("key") or ""))
        return items

    def memory_export_entries(
        self,
        *,
        prefix: str | None = None,
        allow_sensitive: bool = False,
    ) -> dict[str, dict[str, Any]]:
        """Export entries for persistence (best-effort)."""

        pref = str(prefix or "").strip()
        out: dict[str, dict[str, Any]] = {}
        with self._agent_memory_lock:
            for k, entry in self._agent_memory.items():
                if not isinstance(k, str) or not k.strip():
                    continue
                if pref and not k.startswith(pref):
                    continue
                if not isinstance(entry, dict):
                    continue
                sensitive = bool(entry.get("sensitive") is True or is_sensitive_key(k))
                if sensitive and not allow_sensitive:
                    continue
                if "value" not in entry:
                    continue
                out[k] = {
                    "value": entry.get("value"),
                    **({"bytes": entry.get("bytes")} if isinstance(entry.get("bytes"), int) else {}),
                    **({"createdAt": entry.get("createdAt")} if isinstance(entry.get("createdAt"), int) else {}),
                    **({"updatedAt": entry.get("updatedAt")} if isinstance(entry.get("updatedAt"), int) else {}),
                    **({"sensitive": True} if sensitive else {}),
                }
        return out

    def memory_import_entries(
        self,
        entries: dict[str, dict[str, Any]],
        *,
        allow_sensitive: bool = False,
        replace: bool = False,
        max_keys: int = 200,
    ) -> dict[str, Any]:
        """Import persisted entries into memory.

        - replace=false: merge/overwrite only the provided keys
        - replace=true: clear current memory first
        """

        if not isinstance(entries, dict):
            return {"loaded": 0, "skipped": 0}
        if replace:
            with self._agent_memory_lock:
                self._agent_memory.clear()

        loaded = 0
        skipped = 0
        for k, entry in entries.items():
            if not isinstance(k, str) or not k.strip():
                skipped += 1
                continue
            sensitive = bool((isinstance(entry, dict) and entry.get("sensitive") is True) or is_sensitive_key(k))
            if sensitive and not allow_sensitive:
                skipped += 1
                continue
            if not isinstance(entry, dict) or "value" not in entry:
                skipped += 1
                continue
            try:
                self.memory_set(key=k, value=entry.get("value"), max_bytes=500_000, max_keys=max_keys)
                loaded += 1
            except Exception:
                skipped += 1

        return {"loaded": loaded, "skipped": skipped}

    # ─────────────────────────────────────────────────────────────────────────
    # Downloads (best-effort, no output spam)
    # ─────────────────────────────────────────────────────────────────────────

    def get_download_dir(self, tab_id: str) -> Path:
        """Return the per-tab download directory (created if missing)."""
        root = _downloads_root()
        root.mkdir(parents=True, exist_ok=True)
        safe_tab = (tab_id or "").strip() or "unknown"
        # Tab IDs are already safe-ish, but keep path deterministic.
        safe_tab = "".join(c for c in safe_tab if c.isalnum() or c in {"_", "-"}).strip("_-") or "tab"
        dl = root / safe_tab
        dl.mkdir(parents=True, exist_ok=True)
        return dl

    def ensure_downloads(self, session: BrowserSession) -> dict[str, Any]:
        """Configure CDP download behavior to a per-tab directory (best-effort).

        This avoids guessing OS-level download locations and enables deterministic
        download capture for agents.
        """
        if os.environ.get("MCP_DOWNLOADS", "1") == "0":
            return {"enabled": False}

        tab_id = session.tab_id
        if not tab_id:
            return {"enabled": False}

        now_ts = time.time()
        with self._download_lock:
            state = self._download_state.get(tab_id)
            if (
                isinstance(state, dict)
                and state.get("available") is True
                and isinstance(state.get("lastCheck"), (int, float))
                and now_ts - float(state["lastCheck"]) < 30
                and isinstance(state.get("dir"), str)
                and state.get("dir")
            ):
                state["lastCheck"] = now_ts
                # Do not leak absolute paths; return repo-relative when possible.
                try:
                    rel = Path(state["dir"]).resolve().relative_to(_repo_root())
                    rel_dir = str(rel)
                except Exception:
                    rel_dir = Path(state["dir"]).name
                return {"enabled": True, "cached": True, "available": True, "dir": rel_dir}

        dl_dir = self.get_download_dir(tab_id)
        ok = False
        method = None
        err: str | None = None

        params = {"behavior": "allow", "downloadPath": str(dl_dir), "eventsEnabled": True}
        # Try Page domain first (more likely to be available on a tab target).
        try:
            session.send("Page.setDownloadBehavior", params)
            ok = True
            method = "Page.setDownloadBehavior"
        except Exception as exc:
            err = str(exc)
            # Fallback: Browser domain (may not exist on target WS).
            try:
                session.send("Browser.setDownloadBehavior", params)
                ok = True
                method = "Browser.setDownloadBehavior"
            except Exception as exc2:
                err = str(exc2)

        with self._download_lock:
            self._download_state[tab_id] = {
                "available": ok,
                "dir": str(dl_dir),
                "method": method,
                "lastCheck": now_ts,
                **({"error": err} if err and not ok else {}),
            }

        try:
            rel = dl_dir.resolve().relative_to(_repo_root())
            rel_dir = str(rel)
        except Exception:
            rel_dir = dl_dir.name
        return {"enabled": True, "available": ok, "dir": rel_dir, **({"method": method} if method else {})}

    # ─────────────────────────────────────────────────────────────────────────
    # Policy (safety as a mode)
    # ─────────────────────────────────────────────────────────────────────────

    def get_policy(self) -> dict[str, Any]:
        """Return the current safety policy (AI-friendly, low-noise)."""
        mode = getattr(self, "_policy_mode", "permissive")
        mode = _normalize_policy_mode(mode)
        return {
            "mode": mode,
            "strict": mode == "strict",
            # Strict policy constraints (enforced in tools/base.py and specific tools):
            "allowFileScheme": mode != "strict",
            "allowCookieMutation": mode != "strict",
            "requireExplicitAllowHosts": mode == "strict",
        }

    def set_policy(self, mode: str) -> dict[str, Any]:
        """Set policy mode for this server instance."""
        self._policy_mode = _normalize_policy_mode(mode)
        return self.get_policy()

    def get_active_shared_session(self) -> tuple[BrowserSession, dict[str, str]] | None:
        """Return active shared CDP session (if any).

        Used to reuse a single WebSocket connection across many tool calls (e.g. flow).
        """

        if (
            isinstance(getattr(self, "_shared_session", None), BrowserSession)
            and isinstance(getattr(self, "_shared_target", None), dict)
            and isinstance(getattr(self, "_shared_refcount", 0), int)
            and int(getattr(self, "_shared_refcount", 0)) > 0
        ):
            return self._shared_session, self._shared_target
        return None

    @contextmanager
    def shared_session(
        self, config: BrowserConfig, timeout: float = 5.0
    ) -> Generator[tuple[BrowserSession, dict[str, str]], None, None]:
        """Hold a single CDP WebSocket connection open across nested operations.

        When active, tools that call tools.base.get_session(...) will reuse the same
        BrowserSession without closing it, reducing latency and flakiness.
        """

        active = self.get_active_shared_session()
        if active:
            # Defensive: avoid accidental nesting across different browser instances.
            if self._shared_cdp_port is not None and self._shared_cdp_port != config.cdp_port:
                raise HttpClientError("shared_session already active for a different CDP port")
            self._shared_refcount += 1
            try:
                yield active
            finally:
                self._shared_refcount -= 1
                if self._shared_refcount <= 0:
                    sess, _target = active
                    sess.close()
                    self._shared_session = None
                    self._shared_target = None
                    self._shared_cdp_port = None
                    self._shared_refcount = 0
            return

        sess: BrowserSession | None = None
        target: dict[str, str] | None = None
        try:
            sess = self.get_session(config, timeout)

            # Best-effort: enable Page + Tier-1 diagnostics early (before any dialogs block JS),
            # but NEVER fail the shared session setup on these.
            with suppress(Exception):
                sess.enable_page()
            with suppress(Exception):
                self.ensure_diagnostics(sess)

            target = {
                "id": sess.tab_id,
                "webSocketDebuggerUrl": sess.conn.ws_url,
                "url": sess.tab_url,
            }

            self._shared_session = sess
            self._shared_target = target
            self._shared_cdp_port = config.cdp_port
            self._shared_refcount = 1

            yield sess, target
        finally:
            # Cleanup must be deterministic even if setup partially failed.
            try:
                self._shared_refcount -= 1
            except Exception:
                self._shared_refcount = 0

            if self._shared_refcount <= 0:
                if sess is not None:
                    with suppress(Exception):
                        sess.close()
                self._shared_session = None
                self._shared_target = None
                self._shared_cdp_port = None
                self._shared_refcount = 0

    def get_session(self, config: BrowserConfig, timeout: float = 5.0) -> BrowserSession:
        """
        Get a BrowserSession for the current session's tab.

        Creates isolated tab on first call, reuses it for subsequent calls.
        Returns BrowserSession that should be used as context manager.
        """
        if getattr(config, "mode", "launch") == "extension":
            tab_id = self._ensure_session_tab(config)
            gw = self.get_extension_gateway()
            if gw is None:
                raise HttpClientError("Extension gateway is not configured (mode=extension)")
            conn = ExtensionCdpConnection(gw, tab_id, timeout=timeout)
            return BrowserSession(conn, tab_id)

        tab_id = self._ensure_session_tab(config)
        ws_url = self._get_tab_ws_url(config, tab_id)

        if not ws_url:
            # Tab disappeared during operation, recreate
            self._session_tab_id = None
            tab_id = self._ensure_session_tab(config)
            ws_url = self._get_tab_ws_url(config, tab_id)

        if not ws_url:
            raise HttpClientError("Failed to get session tab WebSocket URL")

        conn = CdpConnection(ws_url, timeout=timeout)
        return BrowserSession(conn, tab_id)

    @contextmanager
    def session(self, config: BrowserConfig, timeout: float = 5.0) -> Generator[BrowserSession, None, None]:
        """Context manager for browser session."""
        sess = self.get_session(config, timeout)
        try:
            sess.enable_page()
            yield sess
        finally:
            sess.close()

    def switch_tab(self, config: BrowserConfig, tab_id: str) -> bool:
        """Switch session to use different tab."""
        if getattr(config, "mode", "launch") == "extension":
            gw = self._require_extension_gateway_connected()

            old_id = self._session_tab_id
            try:
                info = gw.rpc_call("tabs.get", {"tabId": str(tab_id)}, timeout=2.0)
            except Exception:
                info = None
            if not isinstance(info, dict):
                return False

            self._session_tab_id = str(tab_id)

            # Keep Tier-0 bus focused on the current session tab (avoid leaking threads).
            if old_id and old_id != tab_id:
                with suppress(Exception):
                    bus = self._tier0_buses.pop(old_id, None)
                    if isinstance(bus, _Tier0EventBus):
                        bus.stop()
                with suppress(Exception):
                    self._affordances.pop(old_id, None)
                with suppress(Exception):
                    self._affordances_state.pop(old_id, None)
                with suppress(Exception), self._captcha_lock:
                    self._captcha_state.pop(old_id, None)

            # Activate in browser UI (best-effort).
            with suppress(Exception):
                gw.rpc_call("tabs.activate", {"tabId": str(tab_id)}, timeout=2.0)
            return True

        old_id = self._session_tab_id
        ws_url = self._get_tab_ws_url(config, tab_id)
        if not ws_url:
            return False
        self._session_tab_id = tab_id

        # Keep Tier-0 bus focused on the current session tab (avoid leaking threads).
        if old_id and old_id != tab_id:
            with suppress(Exception):
                bus = self._tier0_buses.pop(old_id, None)
                if isinstance(bus, _Tier0EventBus):
                    bus.stop()
            with suppress(Exception):
                self._affordances.pop(old_id, None)
            with suppress(Exception):
                self._affordances_state.pop(old_id, None)
            with suppress(Exception), self._captcha_lock:
                self._captcha_state.pop(old_id, None)

        # Try to activate in browser UI (best-effort, ignore failures)
        try:
            conn = CdpConnection(ws_url, timeout=3.0)
            conn.send("Target.activateTarget", {"targetId": tab_id})
            conn.close()
        except OSError:
            pass  # Connection failures are acceptable for UI activation
        return True

    def list_tabs(self, config: BrowserConfig) -> list:
        """List all browser tabs with current session marked."""
        if getattr(config, "mode", "launch") == "extension":
            gw = self._require_extension_gateway_connected()

            raw = gw.rpc_call("tabs.list", {}, timeout=3.0)
            items = raw if isinstance(raw, list) else []
            tabs: list[dict[str, Any]] = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                tid = str(it.get("id") or it.get("tabId") or "").strip()
                if not tid:
                    continue
                tabs.append(
                    {
                        "id": tid,
                        "url": str(it.get("url") or ""),
                        "title": str(it.get("title") or ""),
                        "current": tid == self._session_tab_id,
                    }
                )
            return tabs

        targets = self._get_targets(config)
        tabs = []
        for t in targets:
            if t.get("type") == "page":
                tabs.append(
                    {
                        "id": t.get("id"),
                        "url": t.get("url", ""),
                        "title": t.get("title", ""),
                        "current": t.get("id") == self._session_tab_id,
                    }
                )
        return tabs

    def new_tab(self, config: BrowserConfig, url: str = "about:blank") -> str:
        """Create new tab and switch session to it."""
        if getattr(config, "mode", "launch") == "extension":
            gw = self._require_extension_gateway_connected()

            old_id = self._session_tab_id
            created = gw.rpc_call("tabs.create", {"url": str(url), "active": True}, timeout=5.0)
            new_id = None
            if isinstance(created, dict):
                new_id = created.get("tabId") or created.get("id")
            elif isinstance(created, (int, str)):
                new_id = created
            tab_id = str(new_id or "").strip()
            if not tab_id:
                raise HttpClientError("Failed to create browser tab (extension mode)")

            self._session_tab_id = tab_id

            if old_id and old_id != tab_id:
                with suppress(Exception):
                    bus = self._tier0_buses.pop(old_id, None)
                    if isinstance(bus, _Tier0EventBus):
                        bus.stop()
                with suppress(Exception):
                    self._affordances.pop(old_id, None)
                with suppress(Exception):
                    self._affordances_state.pop(old_id, None)
                with suppress(Exception), self._captcha_lock:
                    self._captcha_state.pop(old_id, None)

            # Best-effort: activate in browser UI so it is visible to the user.
            with suppress(Exception):
                gw.rpc_call("tabs.activate", {"tabId": tab_id}, timeout=2.0)
            return tab_id

        old_id = self._session_tab_id
        tab_id = self._create_tab(config, url)
        self._session_tab_id = tab_id

        # Keep Tier-0 bus focused on the current session tab (avoid leaking threads).
        if old_id and old_id != tab_id:
            with suppress(Exception):
                bus = self._tier0_buses.pop(old_id, None)
                if isinstance(bus, _Tier0EventBus):
                    bus.stop()
            with suppress(Exception):
                self._affordances.pop(old_id, None)
            with suppress(Exception):
                self._affordances_state.pop(old_id, None)
            with suppress(Exception), self._captcha_lock:
                self._captcha_state.pop(old_id, None)

        # Best-effort: activate in browser UI so "new tab" is cognitively obvious in visible mode.
        try:
            ws_url = self._get_tab_ws_url(config, tab_id)
            if ws_url:
                conn = CdpConnection(ws_url, timeout=3.0)
                conn.send("Target.activateTarget", {"targetId": tab_id})
                conn.close()
        except OSError:
            pass
        return tab_id

    def close_tab(self, config: BrowserConfig, tab_id: str | None = None) -> bool:
        """Close a tab. Closes session tab if no ID provided."""
        target_id = tab_id or self._session_tab_id
        if not target_id:
            return False

        if getattr(config, "mode", "launch") == "extension":
            gw = self._require_extension_gateway_connected()

            try:
                res = gw.rpc_call("tabs.close", {"tabId": str(target_id)}, timeout=3.0)
                ok = bool(res.get("success")) if isinstance(res, dict) else True
            except Exception:
                ok = False

            if ok and target_id == self._session_tab_id:
                self._session_tab_id = None

            with suppress(Exception):
                self._bootstrap_scripts.pop(str(target_id), None)
            with suppress(Exception):
                self._diagnostics_state.pop(str(target_id), None)
            with suppress(Exception):
                self._telemetry.pop(str(target_id), None)
            with suppress(Exception):
                self._tab_ws_urls.pop(str(target_id), None)
            with suppress(Exception):
                self._affordances.pop(str(target_id), None)
            with suppress(Exception):
                self._affordances_state.pop(str(target_id), None)
            with suppress(Exception):
                self.clear_auto_dialog(str(target_id))
            with suppress(Exception), self._captcha_lock:
                self._captcha_state.pop(str(target_id), None)
            with suppress(Exception):
                bus = self._tier0_buses.pop(str(target_id), None)
                if isinstance(bus, _Tier0EventBus):
                    bus.stop()
            return ok

        try:
            browser_ws = self._get_browser_ws(config)
            conn = CdpConnection(browser_ws, timeout=3.0)
            conn.send("Target.closeTarget", {"targetId": target_id})
            conn.close()

            if target_id == self._session_tab_id:
                self._session_tab_id = None

            with suppress(Exception):
                self._bootstrap_scripts.pop(target_id, None)
            with suppress(Exception):
                self._diagnostics_state.pop(target_id, None)
            with suppress(Exception):
                self._telemetry.pop(target_id, None)
            with suppress(Exception):
                self._tab_ws_urls.pop(target_id, None)
            with suppress(Exception):
                self._affordances.pop(target_id, None)
            with suppress(Exception):
                self._affordances_state.pop(target_id, None)
            with suppress(Exception):
                self.clear_auto_dialog(target_id)
            with suppress(Exception), self._captcha_lock:
                self._captcha_state.pop(target_id, None)
            with suppress(Exception):
                bus = self._tier0_buses.pop(target_id, None)
                if isinstance(bus, _Tier0EventBus):
                    bus.stop()
            return True
        except (OSError, ValueError, KeyError):
            return False


# Global session manager instance
session_manager = SessionManager()
