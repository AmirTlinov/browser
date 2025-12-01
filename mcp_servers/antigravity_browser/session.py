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
import time
from collections.abc import Generator
from contextlib import contextmanager, suppress
from typing import Any

from .config import BrowserConfig
from .http_client import HttpClientError


def _import_websocket():
    """Import websocket-client with fallback paths."""
    try:
        import websocket
        return websocket
    except ImportError:
        import sys
        from pathlib import Path
        candidates = [
            Path(__file__).resolve().parent.parent / "vendor" / "python",
            Path.home() / ".local" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages",
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

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send CDP command and wait for response."""
        msg_id = self._next_id
        self._next_id += 1

        msg = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params

        self.ws.send(json.dumps(msg))
        return self._recv_until(msg_id)

    def _recv_until(self, expected_id: int) -> dict[str, Any]:
        """Wait for response with specific ID."""
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            raw = self.ws.recv()
            data = json.loads(raw)
            if data.get("id") == expected_id:
                if "error" in data:
                    raise HttpClientError(str(data["error"]))
                return data.get("result", {})
        raise HttpClientError("CDP response timed out")

    def wait_for_event(self, event_name: str, timeout: float = 10.0) -> dict | None:
        """Wait for specific CDP event."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.ws.settimeout(0.5)
                raw = self.ws.recv()
                data = json.loads(raw)
                if data.get("method") == event_name:
                    return data.get("params", {})
            except (json.JSONDecodeError, OSError, TimeoutError):
                continue
        return None

    def close(self):
        """Close the WebSocket connection."""
        with suppress(Exception):
            self.ws.close()


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
        if not self._page_enabled:
            self.conn.send("Page.enable")
            self._page_enabled = True

    def enable_runtime(self) -> None:
        """Enable Runtime domain for JS evaluation."""
        self.conn.send("Runtime.enable")

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send raw CDP command (for compatibility with existing code)."""
        return self.conn.send(method, params)

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

    def eval_js(self, expression: str) -> Any:
        """Evaluate JavaScript and return result."""
        self.enable_runtime()
        result = self.conn.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
            "replMode": True,
        })
        if "result" not in result:
            return None
        value = result["result"]
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
        self._mouse_event("mousePressed", x, y, button, click_count)
        self._mouse_event("mouseReleased", x, y, button, click_count)

    def double_click(self, x: float, y: float) -> None:
        """Double-click at coordinates."""
        self.click(x, y, click_count=2)

    def move_mouse(self, x: float, y: float) -> None:
        """Move mouse to coordinates."""
        self._mouse_event("mouseMoved", x, y, "none", 0)

    def drag(self, from_x: float, from_y: float, to_x: float, to_y: float, steps: int = 10) -> None:
        """Drag from one point to another."""
        self._mouse_event("mousePressed", from_x, from_y, "left", 1)
        for i in range(1, steps + 1):
            progress = i / steps
            x = from_x + (to_x - from_x) * progress
            y = from_y + (to_y - from_y) * progress
            self._mouse_event("mouseMoved", x, y, "left", 0)
            time.sleep(0.01)
        self._mouse_event("mouseReleased", to_x, to_y, "left", 1)

    def scroll(self, delta_x: float = 0, delta_y: float = 0, x: float = 0, y: float = 0) -> None:
        """Scroll the page."""
        self.conn.send("Input.dispatchMouseEvent", {
            "type": "mouseWheel",
            "x": x,
            "y": y,
            "deltaX": delta_x,
            "deltaY": delta_y,
        })

    def _mouse_event(self, event_type: str, x: float, y: float, button: str, click_count: int) -> None:
        """Dispatch mouse event."""
        self.conn.send("Input.dispatchMouseEvent", {
            "type": event_type,
            "x": x,
            "y": y,
            "button": button,
            "clickCount": click_count,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # Keyboard Input
    # ─────────────────────────────────────────────────────────────────────────

    def press_key(self, key: str, modifiers: int = 0) -> None:
        """Press a keyboard key."""
        # Key codes for special keys
        key_codes = {
            "Enter": 13, "Tab": 9, "Escape": 27, "Backspace": 8, "Delete": 46,
            "ArrowUp": 38, "ArrowDown": 40, "ArrowLeft": 37, "ArrowRight": 39,
            "Home": 36, "End": 35, "PageUp": 33, "PageDown": 34,
        }
        key_code = key_codes.get(key, ord(key[0].upper()) if len(key) == 1 else 0)

        for event_type in ["keyDown", "keyUp"]:
            self.conn.send("Input.dispatchKeyEvent", {
                "type": event_type,
                "key": key,
                "code": f"Key{key.upper()}" if len(key) == 1 else key,
                "windowsVirtualKeyCode": key_code,
                "modifiers": modifiers,
            })

    def type_text(self, text: str) -> None:
        """Type text character by character."""
        for char in text:
            self.conn.send("Input.dispatchKeyEvent", {
                "type": "char",
                "text": char,
            })

    # ─────────────────────────────────────────────────────────────────────────
    # Screenshots & DOM
    # ─────────────────────────────────────────────────────────────────────────

    def screenshot(self, format: str = "png", clip: dict | None = None) -> str:
        """Capture screenshot, return base64 data."""
        params: dict[str, Any] = {"format": format, "fromSurface": True}
        if clip:
            params["clip"] = clip
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
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton state (for testing)."""
        cls._instance = None
        cls._session_tab_id = None

    @property
    def tab_id(self) -> str | None:
        """Current session's tab ID."""
        return self._session_tab_id

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

    def get_session(self, config: BrowserConfig, timeout: float = 5.0) -> BrowserSession:
        """
        Get a BrowserSession for the current session's tab.

        Creates isolated tab on first call, reuses it for subsequent calls.
        Returns BrowserSession that should be used as context manager.
        """
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
        ws_url = self._get_tab_ws_url(config, tab_id)
        if not ws_url:
            return False
        self._session_tab_id = tab_id

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
        targets = self._get_targets(config)
        tabs = []
        for t in targets:
            if t.get("type") == "page":
                tabs.append({
                    "id": t.get("id"),
                    "url": t.get("url", ""),
                    "title": t.get("title", ""),
                    "current": t.get("id") == self._session_tab_id,
                })
        return tabs

    def new_tab(self, config: BrowserConfig, url: str = "about:blank") -> str:
        """Create new tab and switch session to it."""
        tab_id = self._create_tab(config, url)
        self._session_tab_id = tab_id
        return tab_id

    def close_tab(self, config: BrowserConfig, tab_id: str | None = None) -> bool:
        """Close a tab. Closes session tab if no ID provided."""
        target_id = tab_id or self._session_tab_id
        if not target_id:
            return False

        try:
            browser_ws = self._get_browser_ws(config)
            conn = CdpConnection(browser_ws, timeout=3.0)
            conn.send("Target.closeTarget", {"targetId": target_id})
            conn.close()

            if target_id == self._session_tab_id:
                self._session_tab_id = None
            return True
        except (OSError, ValueError, KeyError):
            return False


# Global session manager instance
session_manager = SessionManager()
