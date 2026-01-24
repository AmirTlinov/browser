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

if TYPE_CHECKING:
    from .extension_gateway import ExtensionGateway

from .session_cdp import CdpConnection, ExtensionCdpConnection

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




__all__ = ["BrowserSession"]
