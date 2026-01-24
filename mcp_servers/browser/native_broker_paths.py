from __future__ import annotations

import os
import re
from pathlib import Path


def _infer_xdg_runtime_dir(uid: int | None) -> Path | None:
    if uid is None or uid < 0:
        return None
    try:
        candidate = Path("/run") / "user" / str(uid)
        if candidate.exists() and candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK):
            return candidate
    except Exception:
        return None
    return None


def _runtime_root() -> Path:
    raw = os.environ.get("MCP_NATIVE_BROKER_DIR") or os.environ.get("MCP_NATIVE_HOST_DIR")
    if isinstance(raw, str) and raw.strip():
        return Path(raw.strip()).expanduser()

    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if isinstance(xdg, str) and xdg.strip():
        return Path(xdg.strip()).expanduser() / "browser-mcp"

    uid = None
    try:
        uid = os.getuid()
    except Exception:
        uid = None
    inferred = _infer_xdg_runtime_dir(uid)
    if inferred is not None:
        return inferred / "browser-mcp"
    suffix = str(uid) if isinstance(uid, int) and uid >= 0 else "user"
    return Path("/tmp") / f"browser-mcp-{suffix}"


def runtime_dir() -> Path:
    p = _runtime_root()
    p.mkdir(parents=True, exist_ok=True)
    return p


_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def sanitize_broker_id(raw: str, *, max_len: int = 48) -> str:
    s = str(raw or "").strip()
    if not s:
        return "default"
    s = _SAFE_ID_RE.sub("-", s).strip("-.") or "default"
    return s[: max(8, int(max_len))]


def broker_socket_path(broker_id: str) -> Path:
    bid = sanitize_broker_id(broker_id)
    # Keep paths short: some platforms have strict AF_UNIX path length limits.
    return runtime_dir() / f"broker-{bid}.sock"


def broker_info_path(broker_id: str) -> Path:
    bid = sanitize_broker_id(broker_id)
    return runtime_dir() / f"broker-{bid}.json"
