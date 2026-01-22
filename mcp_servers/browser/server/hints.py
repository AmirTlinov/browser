"""Small helpers for producing tool-call hints ("next" actions).

These strings are user/agent-visible and must stay compatible with the active toolset:
- v1: artifact(...) tool exists
- v2 (North Star): only browser/page/run are exposed; artifacts are accessed via browser(action="artifact", ...)
"""

from __future__ import annotations

import os

_V2_TOOLSET_NAMES = {"v2", "northstar", "north-star"}


def _toolset() -> str:
    return (os.environ.get("MCP_TOOLSET") or "").strip().lower()


def is_v2_toolset() -> bool:
    return _toolset() in _V2_TOOLSET_NAMES


def artifact_list_hint(*, limit: int = 20, kind: str | None = None) -> str:
    limit_i = int(limit) if isinstance(limit, int) else 20
    limit_i = max(1, min(limit_i, 100))
    if is_v2_toolset():
        if kind:
            return f'browser(action="artifact", artifact_action="list", limit={limit_i}, kind="{kind}")'
        return f'browser(action="artifact", artifact_action="list", limit={limit_i})'
    if kind:
        return f'artifact(action="list", limit={limit_i}, kind="{kind}")'
    return f'artifact(action="list", limit={limit_i})'


def artifact_get_hint(*, artifact_id: str, offset: int = 0, max_chars: int = 4000) -> str:
    off = int(offset) if isinstance(offset, int) else 0
    off = max(0, off)
    mx = int(max_chars) if isinstance(max_chars, int) else 4000
    # Keep drilldowns cognitively cheap by default: use pagination (offset) instead of huge slices.
    mx = max(200, min(mx, 4000))
    if is_v2_toolset():
        return f'browser(action="artifact", artifact_action="get", id="{artifact_id}", offset={off}, max_chars={mx})'
    return f'artifact(action="get", id="{artifact_id}", offset={off}, max_chars={mx})'


def artifact_delete_hint(*, artifact_id: str) -> str:
    if is_v2_toolset():
        return f'browser(action="artifact", artifact_action="delete", id="{artifact_id}")'
    return f'artifact(action="delete", id="{artifact_id}")'


def artifact_export_hint(*, artifact_id: str, name: str | None = None, overwrite: bool = False) -> str:
    ov = "true" if overwrite else "false"
    nm = (name or "").strip()
    if nm:
        if is_v2_toolset():
            return (
                f'browser(action="artifact", artifact_action="export", id="{artifact_id}", name="{nm}", overwrite={ov})'
            )
        return f'artifact(action="export", id="{artifact_id}", name="{nm}", overwrite={ov})'
    if is_v2_toolset():
        return f'browser(action="artifact", artifact_action="export", id="{artifact_id}", overwrite={ov})'
    return f'artifact(action="export", id="{artifact_id}", overwrite={ov})'
