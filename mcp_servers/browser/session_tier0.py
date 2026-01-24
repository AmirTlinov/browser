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

from .session_cdp import CdpConnection

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




__all__ = ["_Tier0EventBus"]
