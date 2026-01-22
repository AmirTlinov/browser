from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..config import BrowserConfig
from ..session import session_manager
from ..tools.base import SmartToolError, get_session
from .paste_flow import _screenshot_hash, focus_canvas_best_effort


def _is_changed(before: str | None, after: str | None, *, threshold: int = 14) -> tuple[bool | None, int | None]:
    """Return (changed, hamming) using ahash when available."""
    if not before or not after:
        return None, None
    if before.startswith("ahash:") and after.startswith("ahash:"):
        try:
            a = int(before.split(":", 1)[1], 16)
            b = int(after.split(":", 1)[1], 16)
            hamming = int((a ^ b).bit_count())
            return hamming >= int(threshold), hamming
        except Exception:
            return before != after, None
    return before != after, None


def drop_files_best_effort(
    config: BrowserConfig,
    *,
    file_paths: list[str],
    settle_ms: int = 1400,
    verify_screenshot: bool = True,
    threshold: int = 14,
) -> dict[str, Any]:
    """Drop local files into the current page via CDP Input.dispatchDragEvent (best-effort).

    This is a powerful cross-site primitive for canvas apps that accept OS-style file drops.
    It can be attempted before menu-driven import flows to reduce UI hunting.
    """

    # Safety-as-mode: strict policy forbids uploading/dropping local files (data exfil risk).
    try:
        if session_manager.get_policy().get("mode") == "strict":
            raise SmartToolError(
                tool="drop_flow",
                action="validate",
                reason="Blocked by strict policy",
                suggestion='Switch to permissive via browser(action="policy", mode="permissive") if you have explicit user approval to drop local files',
            )
    except SmartToolError:
        raise
    except Exception:
        pass

    if not isinstance(file_paths, list) or not file_paths:
        raise SmartToolError(
            tool="drop_flow",
            action="validate",
            reason="file_paths is required",
            suggestion="Provide file_paths=['/abs/path/to/file.svg']",
        )

    validated: list[str] = []
    for fp in file_paths[:10]:
        if not isinstance(fp, str) or not fp.strip():
            continue
        p = Path(fp)
        if not p.exists():
            raise SmartToolError(
                tool="drop_flow",
                action="validate",
                reason=f"File not found: {fp}",
                suggestion="Provide absolute paths to existing files",
            )
        validated.append(str(p.absolute()))

    if not validated:
        raise SmartToolError(
            tool="drop_flow",
            action="validate",
            reason="No valid file paths provided",
            suggestion="Provide file_paths=['/abs/path/to/file.svg']",
        )

    settle_ms = max(100, min(int(settle_ms), 8000))
    threshold = max(1, min(int(threshold), 64))

    focus = focus_canvas_best_effort(config)
    if not isinstance(focus, dict) or focus.get("x") is None or focus.get("y") is None:
        raise SmartToolError(
            tool="drop_flow",
            action="focus",
            reason="Failed to pick a drop point",
            suggestion="Ensure the app canvas is visible and try again",
        )

    x = float(focus["x"])
    y = float(focus["y"])

    before_hash: str | None = None
    if verify_screenshot:
        backend_id = focus.get("backendDOMNodeId") if isinstance(focus, dict) else None
        backend_dom_node_id = int(backend_id) if isinstance(backend_id, int) else None
        _shot, before_hash = _screenshot_hash(config, backend_dom_node_id=backend_dom_node_id)

    drag_data = {"items": [], "files": validated, "dragOperationsMask": 1}

    with get_session(config) as (session, target):
        # Dispatch a minimal drag sequence.
        commands = [
            {
                "method": "Input.dispatchDragEvent",
                "params": {"type": "dragEnter", "x": x, "y": y, "data": drag_data, "modifiers": 0},
            },
            {
                "method": "Input.dispatchDragEvent",
                "params": {"type": "dragOver", "x": x, "y": y, "data": drag_data, "modifiers": 0},
            },
            {
                "method": "Input.dispatchDragEvent",
                "params": {"type": "drop", "x": x, "y": y, "data": drag_data, "modifiers": 0},
            },
        ]

        # Prefer batching (extension mode), but keep unit tests simple with a send() fallback.
        send_many = getattr(session, "send_many", None)
        if callable(send_many):
            send_many(commands)
        else:
            for cmd in commands:
                session.send(cmd["method"], cmd.get("params"))

    time.sleep(settle_ms / 1000.0)

    after_hash: str | None = None
    if verify_screenshot:
        backend_id = focus.get("backendDOMNodeId") if isinstance(focus, dict) else None
        backend_dom_node_id = int(backend_id) if isinstance(backend_id, int) else None
        _shot2, after_hash = _screenshot_hash(config, backend_dom_node_id=backend_dom_node_id)

    changed, hamming = _is_changed(before_hash, after_hash, threshold=threshold)

    return {
        "ok": True,
        "strategy": "drop",
        "files": validated,
        "focus": focus,
        "verify": {
            "before": before_hash,
            "after": after_hash,
            "changed": changed,
            "hamming": hamming,
            "threshold": threshold,
        }
        if verify_screenshot
        else {"changed": None},
        "target": target["id"],
        "sessionTabId": session_manager.tab_id,
    }
