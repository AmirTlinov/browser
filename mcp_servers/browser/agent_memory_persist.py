"""Persisted agent memory (disk-backed, safe-by-default).

Design
- Store a small JSON snapshot under `data/memory/` (gitignored).
- Atomic writes: write temp file then replace.
- Best-effort: corrupt files are ignored (fail-soft) unless explicitly requested.

Security posture
- This is NOT encrypted.
- Callers must refuse persisting sensitive keys by default.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from contextlib import suppress
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    # mcp_servers/browser/agent_memory_persist.py -> repo root is parents[2]
    return Path(__file__).resolve().parents[2]


def memory_dir() -> Path:
    raw = os.environ.get("MCP_AGENT_MEMORY_DIR")
    if isinstance(raw, str) and raw.strip():
        return Path(raw.strip()).expanduser()
    return _repo_root() / "data" / "memory"


def memory_file() -> Path:
    return memory_dir() / "agent_memory.json"


def load_items(*, path: Path | None = None) -> dict[str, dict[str, Any]]:
    p = path or memory_file()
    try:
        if not p.exists() or not p.is_file():
            return {}
        raw = p.read_text(encoding="utf-8", errors="replace")
        obj = json.loads(raw)
    except Exception:
        return {}

    if not isinstance(obj, dict):
        return {}

    items = obj.get("items")
    if not isinstance(items, dict):
        return {}

    out: dict[str, dict[str, Any]] = {}
    for k, v in items.items():
        if not (isinstance(k, str) and k.strip()):
            continue
        if isinstance(v, dict):
            out[k] = dict(v)
    return out


def save_items(*, items: dict[str, dict[str, Any]], path: Path | None = None) -> dict[str, Any]:
    p = path or memory_file()
    p.parent.mkdir(parents=True, exist_ok=True)

    now_ms = int(time.time() * 1000)
    payload = {"version": 1, "updatedAt": now_ms, "items": items}
    text = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)

    tmp = p.with_suffix(p.suffix + ".tmp")
    bak = p.with_suffix(p.suffix + ".bak")

    try:
        if p.exists() and p.is_file():
            shutil.copyfile(p, bak)
    except Exception:
        # Backup is best-effort.
        pass

    tmp.write_text(text, encoding="utf-8")
    with suppress(Exception):
        os.chmod(tmp, 0o600)
    tmp.replace(p)
    with suppress(Exception):
        os.chmod(p, 0o600)

    return {"ok": True, "path": str(p), "updatedAt": now_ms, "keys": len(items)}
