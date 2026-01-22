from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any

from ..config import BrowserConfig
from ..tools.base import SmartToolError, get_session


def _validate_files(*, file_paths: list[str]) -> list[str]:
    if not isinstance(file_paths, list) or not file_paths:
        raise SmartToolError(
            tool="file_chooser",
            action="validate",
            reason="file_paths must be a non-empty list",
            suggestion="Provide file_paths=['/absolute/path/to/file']",
        )
    out: list[str] = []
    for raw in file_paths:
        p = Path(str(raw)).expanduser()
        if not p.is_absolute():
            raise SmartToolError(
                tool="file_chooser",
                action="validate",
                reason=f"File path must be absolute: {raw}",
                suggestion="Provide absolute paths (starting with /...)",
            )
        if not p.exists():
            raise SmartToolError(
                tool="file_chooser",
                action="validate",
                reason=f"File not found: {p}",
                suggestion="Create the file first or fix the path",
            )
        out.append(str(p))
    return out


def set_files_via_file_chooser(
    config: BrowserConfig,
    *,
    file_paths: list[str],
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Accept the most recent intercepted file chooser by setting files on its input.

    Requirements:
    - The caller must have enabled interception via Page.setInterceptFileChooserDialog(enabled=True)
    - The file chooser must have been opened by the page (Page.fileChooserOpened event)

    Works in both launch/attach and extension mode as long as Page.fileChooserOpened is available.
    """
    files = _validate_files(file_paths=file_paths)

    with get_session(config, ensure_diagnostics=False) as (session, target):
        # Ensure domains needed by setFileInputFiles (batch in extension mode).
        with suppress(Exception):
            enable_domains = getattr(session, "enable_domains", None)
            if callable(enable_domains):
                enable_domains(page=True, dom=True, strict=False)
            else:
                session.send("Page.enable")
                session.send("DOM.enable")

        params = None
        try:
            wait_for_event = getattr(session, "wait_for_event", None)
            if callable(wait_for_event):
                params = wait_for_event("Page.fileChooserOpened", timeout=float(timeout))
            else:
                params = session.conn.wait_for_event("Page.fileChooserOpened", timeout=float(timeout))  # type: ignore[attr-defined]
        except Exception as exc:
            raise SmartToolError(
                tool="file_chooser",
                action="wait",
                reason=str(exc),
                suggestion="Ensure Page.setInterceptFileChooserDialog(enabled=True) is set and re-trigger the chooser",
            ) from exc

        if params is None:
            raise SmartToolError(
                tool="file_chooser",
                action="wait",
                reason="Timed out waiting for Page.fileChooserOpened",
                suggestion="Re-trigger the file chooser and retry",
            )

        backend_node_id = params.get("backendNodeId") if isinstance(params, dict) else None
        node_id = params.get("nodeId") if isinstance(params, dict) else None

        set_params: dict[str, Any] = {"files": files}
        if isinstance(backend_node_id, int) and backend_node_id > 0:
            set_params["backendNodeId"] = backend_node_id
        elif isinstance(node_id, int) and node_id > 0:
            set_params["nodeId"] = node_id
        else:
            raise SmartToolError(
                tool="file_chooser",
                action="accept",
                reason="fileChooserOpened event missing backendNodeId/nodeId",
                suggestion="Update the extension event allowlist to include Page.fileChooserOpened (extension mode) or upgrade Chrome",
                details={"event": params},
            )

        try:
            session.send("DOM.setFileInputFiles", set_params)
        except Exception as exc:
            raise SmartToolError(
                tool="file_chooser",
                action="accept",
                reason=str(exc),
                suggestion="Retry with a different file or ensure the input is still attached",
                details={"setParams": {k: v for k, v in set_params.items() if k != "files"}},
            ) from exc

        return {
            "ok": True,
            "target": target.get("id"),
            "files": files,
            "chooser": {k: v for k, v in (params or {}).items() if k in {"mode", "frameId", "backendNodeId", "nodeId"}},
        }


def enable_file_chooser_intercept(config: BrowserConfig, *, enabled: bool = True) -> dict[str, Any]:
    """Enable/disable file chooser interception (prevents native dialog; emits Page.fileChooserOpened)."""
    with get_session(config, ensure_diagnostics=False) as (session, target):
        try:
            session.send("Page.setInterceptFileChooserDialog", {"enabled": bool(enabled)})
        except Exception as exc:
            raise SmartToolError(
                tool="file_chooser",
                action="intercept",
                reason=str(exc),
                suggestion="Upgrade Chrome or switch to launch/attach mode with a compatible CDP endpoint",
            ) from exc
        return {"ok": True, "enabled": bool(enabled), "target": target.get("id")}
