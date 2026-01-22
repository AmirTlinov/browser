from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..config import BrowserConfig
from ..tools.base import SmartToolError
from .clipboard import clipboard_write_svg, clipboard_write_text
from .drop_flow import drop_files_best_effort
from .import_flow import ImportHints, import_via_file_chooser
from .paste_flow import paste_best_effort

InsertStrategy = Literal["auto", "paste", "drop", "import"]
InsertKind = Literal["svg", "text", "files"]


@dataclass(frozen=True)
class InsertPayload:
    kind: InsertKind
    svg: str | None = None
    text: str | None = None
    file_paths: list[str] | None = None


def parse_insert_payload(params: dict[str, Any]) -> InsertPayload:
    """Parse a generic insert payload from adapter params (best-effort, deterministic)."""
    svg = params.get("svg") if isinstance(params.get("svg"), str) else None
    text = params.get("text") if isinstance(params.get("text"), str) else None

    file_paths = params.get("file_paths") or params.get("filePaths") or params.get("files")
    if isinstance(file_paths, str):
        file_paths = [file_paths]
    if file_paths is not None and not isinstance(file_paths, list):
        file_paths = None
    files_norm: list[str] | None = None
    if isinstance(file_paths, list) and file_paths:
        files_norm = [str(p) for p in file_paths if isinstance(p, str) and p.strip()]
        if not files_norm:
            files_norm = None

    provided = [k for k, v in (("svg", svg), ("text", text), ("files", files_norm)) if v]
    if len(provided) != 1:
        raise SmartToolError(
            tool="app",
            action="insert",
            reason="Provide exactly one payload: svg | text | file_paths",
            suggestion="Use params={svg:'<svg...>'} OR params={text:'...'} OR params={file_paths:['/abs/file.png']}",
            details={"provided": provided},
        )

    if svg is not None:
        if not svg.strip():
            raise SmartToolError(
                tool="app",
                action="insert",
                reason="svg is empty",
                suggestion="Provide a non-empty SVG string",
            )
        return InsertPayload(kind="svg", svg=svg)

    if text is not None:
        return InsertPayload(kind="text", text=text)

    return InsertPayload(kind="files", file_paths=files_norm or [])


def _write_svg_outbox(*, repo_root: Path, svg: str, prefix: str) -> Path:
    out_dir = repo_root / "data" / "outbox"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{prefix}_{int(time.time())}.svg"
    path.write_text(str(svg), encoding="utf-8")
    return path


def insert_best_effort(
    config: BrowserConfig,
    *,
    payload: InsertPayload,
    repo_root: Path,
    hints: ImportHints,
    strategy: InsertStrategy = "auto",
    prefer: str = "ctrl",
    verify: bool = True,
    png_scale: float = 2.0,
    timeout_s: float = 15.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Insert SVG/text/files into the current app with paste→drop→import fallbacks (best-effort).

    Design goals:
    - One call for "put this thing into the canvas app" (Miro/Figma-class UIs).
    - Deterministic fallbacks, low-noise output, explicit artifacts.
    - No site hardcoding: adapters provide optional `hints` for the import step only.
    """
    strategy = str(strategy or "auto").strip().lower()  # type: ignore[assignment]
    if strategy not in {"auto", "paste", "drop", "import"}:
        raise SmartToolError(
            tool="app",
            action="insert",
            reason="Invalid strategy",
            suggestion="Use strategy='auto'|'paste'|'drop'|'import'",
            details={"strategy": strategy},
        )

    prefer = str(prefer or "ctrl").strip().lower()
    if prefer not in {"ctrl", "meta"}:
        prefer = "ctrl"

    timeout_s = max(2.0, min(float(timeout_s), 60.0))

    if dry_run:
        if payload.kind == "svg":
            svg_path = _write_svg_outbox(repo_root=repo_root, svg=payload.svg or "", prefix="insert_svg")
            return {
                "ok": True,
                "dry_run": True,
                "op": "insert",
                "kind": "svg",
                "strategy": strategy,
                "prefer": prefer,
                "verify": bool(verify),
                "artifact": {"file": str(svg_path), "type": "image/svg+xml"},
            }
        if payload.kind == "text":
            return {
                "ok": True,
                "dry_run": True,
                "op": "insert",
                "kind": "text",
                "strategy": strategy,
                "prefer": prefer,
                "verify": bool(verify),
                "bytes": len((payload.text or "").encode("utf-8")),
            }
        return {
            "ok": True,
            "dry_run": True,
            "op": "insert",
            "kind": "files",
            "strategy": strategy,
            "file_paths": list(payload.file_paths or []),
        }

    # ──────────────────────────────────────────────────────────────────────
    # SVG payload
    # ──────────────────────────────────────────────────────────────────────
    if payload.kind == "svg":
        svg = str(payload.svg or "")
        svg_path = _write_svg_outbox(repo_root=repo_root, svg=svg, prefix="insert_svg")

        paste: dict[str, Any] | None = None
        paste_error: str | None = None

        # Fast path (extension mode): write clipboard (SVG+PNG) and paste.
        if strategy in {"auto", "paste"} and getattr(config, "mode", "launch") == "extension":
            try:
                clipboard_write_svg(
                    config, svg=svg, include_png=True, scale=float(png_scale), timeout_s=min(12.0, timeout_s)
                )
                paste = paste_best_effort(
                    config,
                    prefer=prefer,
                    verify_screenshot=(strategy == "auto") and bool(verify),
                    settle_ms=400,
                )
                changed = paste.get("changed") is True
                if strategy == "paste" or changed:
                    return {
                        "ok": True,
                        "op": "insert",
                        "kind": "svg",
                        "strategy": strategy,
                        "artifact": {"file": str(svg_path), "type": "image/svg+xml"},
                        "paste": paste,
                    }
            except SmartToolError as exc:
                paste_error = exc.reason
            except Exception as exc:  # noqa: BLE001
                paste_error = str(exc)

            if strategy == "paste":
                raise SmartToolError(
                    tool="app",
                    action="insert",
                    reason=f"Paste failed: {paste_error or 'unknown error'}",
                    suggestion="Retry, or use strategy='drop'/'import' to avoid clipboard",
                )

        drop_res: dict[str, Any] | None = None
        drop_error: str | None = None
        if strategy in {"auto", "drop"}:
            try:
                drop_res = drop_files_best_effort(
                    config,
                    file_paths=[str(svg_path)],
                    verify_screenshot=True,
                    settle_ms=1700,
                )
                if strategy == "drop" or (
                    isinstance(drop_res, dict) and drop_res.get("verify", {}).get("changed") is True
                ):
                    return {
                        "ok": True,
                        "op": "insert",
                        "kind": "svg",
                        "strategy": strategy,
                        "artifact": {"file": str(svg_path), "type": "image/svg+xml"},
                        **({"paste": paste} if isinstance(paste, dict) else {}),
                        **({"pasteError": paste_error} if paste_error else {}),
                        "drop": drop_res,
                    }
            except SmartToolError as exc:
                drop_error = exc.reason
            except Exception as exc:  # noqa: BLE001
                drop_error = str(exc)

            if strategy == "drop":
                raise SmartToolError(
                    tool="app",
                    action="insert",
                    reason=f"Drop failed: {drop_error or 'unknown error'}",
                    suggestion="Use strategy='import' to drive file chooser import instead",
                )

        imported = import_via_file_chooser(
            config,
            file_paths=[str(svg_path)],
            hints=hints,
            timeout_s=timeout_s,
        )
        return {
            "ok": True,
            "op": "insert",
            "kind": "svg",
            "strategy": strategy,
            "artifact": {"file": str(svg_path), "type": "image/svg+xml"},
            **({"paste": paste} if isinstance(paste, dict) else {}),
            **({"pasteError": paste_error} if paste_error else {}),
            **({"drop": drop_res} if isinstance(drop_res, dict) else {}),
            **({"dropError": drop_error} if drop_error else {}),
            "import": imported,
        }

    # ──────────────────────────────────────────────────────────────────────
    # Text payload
    # ──────────────────────────────────────────────────────────────────────
    if payload.kind == "text":
        text = str(payload.text or "")
        try:
            clipboard_write_text(config, text=text, timeout_s=min(6.0, timeout_s))
            pasted = paste_best_effort(config, prefer=prefer, verify_screenshot=bool(verify), settle_ms=350)
            return {
                "ok": True,
                "op": "insert",
                "kind": "text",
                "strategy": strategy,
                "bytes": len(text.encode("utf-8")),
                "paste": pasted,
            }
        except SmartToolError as exc:
            raise SmartToolError(
                tool="app",
                action="insert",
                reason=exc.reason,
                suggestion=exc.suggestion,
                details=exc.details,
            ) from exc

    # ──────────────────────────────────────────────────────────────────────
    # Local files payload
    # ──────────────────────────────────────────────────────────────────────
    if strategy == "paste":
        raise SmartToolError(
            tool="app",
            action="insert",
            reason="strategy='paste' is not supported for file insertion",
            suggestion="Use strategy='auto' (recommended), 'drop', or 'import' for file_paths payloads",
        )

    file_paths = list(payload.file_paths or [])
    if not file_paths:
        raise SmartToolError(
            tool="app",
            action="insert",
            reason="file_paths is required",
            suggestion="Provide params={file_paths:['/abs/path/to/file.png']}",
        )

    dropped: dict[str, Any] | None = None
    drop_error: str | None = None
    if strategy in {"auto", "drop"}:
        try:
            dropped = drop_files_best_effort(config, file_paths=[str(p) for p in file_paths], verify_screenshot=True)
            if strategy == "drop" or (isinstance(dropped, dict) and dropped.get("verify", {}).get("changed") is True):
                return {
                    "ok": True,
                    "op": "insert",
                    "kind": "files",
                    "strategy": strategy,
                    "drop": dropped,
                    "files": file_paths,
                }
        except SmartToolError as exc:
            drop_error = exc.reason
        except Exception as exc:  # noqa: BLE001
            drop_error = str(exc)

        if strategy == "drop":
            raise SmartToolError(
                tool="app",
                action="insert",
                reason=f"Drop failed: {drop_error or 'unknown error'}",
                suggestion="Use strategy='import' to drive file chooser import instead",
            )

    imported = import_via_file_chooser(
        config, file_paths=[str(p) for p in file_paths], hints=hints, timeout_s=timeout_s
    )
    out: dict[str, Any] = {
        "ok": True,
        "op": "insert",
        "kind": "files",
        "strategy": strategy,
        "files": file_paths,
        "import": imported,
    }
    if dropped is not None:
        out["drop"] = dropped
    if drop_error:
        out["dropError"] = drop_error
    return out
