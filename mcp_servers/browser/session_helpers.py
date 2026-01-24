"""Session helper utilities shared across session submodules."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .http_client import HttpClientError


def _normalize_policy_mode(raw: str) -> str:
    v = (raw or "").strip().lower()
    if v in {"strict", "locked", "secure"}:
        return "strict"
    return "permissive"


def _repo_root() -> Path:
    # mcp_servers/browser/session_helpers.py -> repo root is parents[2]
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


__all__ = [
    "_downloads_root",
    "_http_get_json",
    "_import_websocket",
    "_normalize_policy_mode",
    "_repo_root",
]

