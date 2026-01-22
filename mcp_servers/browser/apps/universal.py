from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..config import BrowserConfig
from ..tools.base import SmartToolError
from .base import AppAdapter, AppAdapterError
from .clipboard import clipboard_write_svg, clipboard_write_text
from .diagram import DiagramLayout, default_browser_mcp_architecture_spec, diagram_spec_to_svg
from .drop_flow import drop_files_best_effort
from .import_flow import default_import_hints, import_via_file_chooser, merge_import_hints, parse_import_hints
from .insert import insert_best_effort, parse_insert_payload
from .paste_flow import paste_best_effort


def _repo_root() -> Path:
    # mcp_servers/browser/apps/*.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3]


class UniversalAdapter(AppAdapter):
    """Generic adapter that can run on any site (best-effort heuristics)."""

    name = "universal"

    def match(self, *, url: str) -> bool:  # noqa: ARG002
        # Always available as a fallback when no app-specific adapter matches.
        return True

    def invoke(self, *, config: BrowserConfig, op: str, params: dict[str, Any], dry_run: bool) -> dict[str, Any]:
        operation = str(op or "").strip().lower()
        if operation not in {"import", "diagram", "paste", "insert"}:
            raise AppAdapterError(
                app=self.name,
                op=operation,
                reason="Unknown operation",
                suggestion="Supported ops: import, diagram, paste, insert",
                details={"op": op},
            )

        if operation == "insert":
            hints = merge_import_hints(default_import_hints(), parse_import_hints(params.get("hints")))
            try:
                png_scale_raw = params.get("png_scale")
                png_scale = float(png_scale_raw) if isinstance(png_scale_raw, (int, float)) else 2.0
                timeout_raw = params.get("timeout_s")
                timeout_s = float(timeout_raw) if isinstance(timeout_raw, (int, float)) else 15.0

                payload = parse_insert_payload(params)
                return insert_best_effort(
                    config,
                    payload=payload,
                    repo_root=_repo_root(),
                    hints=hints,
                    strategy=str(params.get("strategy") or "auto"),
                    prefer=str(params.get("prefer") or "ctrl"),
                    verify=bool(params.get("verify", True)),
                    png_scale=png_scale,
                    timeout_s=timeout_s,
                    dry_run=dry_run,
                )
            except SmartToolError as exc:
                raise AppAdapterError(
                    app=self.name,
                    op=operation,
                    reason=exc.reason,
                    suggestion=exc.suggestion,
                    details=exc.details,
                ) from exc
            except Exception as exc:  # noqa: BLE001
                raise AppAdapterError(
                    app=self.name,
                    op=operation,
                    reason=str(exc),
                    suggestion="Retry with fewer params; ensure the tab is focused and the app is ready",
                ) from exc

        if operation == "import":
            file_paths = params.get("file_paths") or params.get("filePaths") or params.get("files")
            if isinstance(file_paths, str):
                file_paths = [file_paths]
            if not isinstance(file_paths, list) or not file_paths:
                raise AppAdapterError(
                    app=self.name,
                    op=operation,
                    reason="file_paths is required",
                    suggestion="Provide params={file_paths:['/abs/path/to/file.svg']}",
                )

            hints = merge_import_hints(default_import_hints(), parse_import_hints(params.get("hints")))
            timeout_s = params.get("timeout_s") if isinstance(params.get("timeout_s"), (int, float)) else None
            timeout_s = float(timeout_s) if timeout_s is not None else 12.0

            if dry_run:
                return {
                    "ok": True,
                    "dry_run": True,
                    "op": "import",
                    "file_paths": [str(p) for p in file_paths if isinstance(p, str)],
                    "hints": {
                        "open_candidates": list(hints.open_candidates),
                        "choose_candidates": list(hints.choose_candidates),
                        "paths": [list(p) for p in hints.paths],
                        "shortcuts": [c.__dict__ for c in hints.shortcuts],
                    },
                }

            # Best-effort: allow page to settle first (helps SPAs).
            try:
                from .. import tools

                tools.wait_for(config, condition="networkidle", timeout=5)
            except Exception:
                pass

            dropped: dict[str, Any] | None = None
            drop_error: str | None = None
            try:
                dropped = drop_files_best_effort(
                    config, file_paths=[str(p) for p in file_paths], verify_screenshot=True
                )
                if isinstance(dropped, dict) and dropped.get("verify", {}).get("changed") is True:
                    return dropped
            except SmartToolError as exc:
                drop_error = exc.reason
            except Exception as exc:  # noqa: BLE001
                drop_error = str(exc)

            imported = import_via_file_chooser(
                config, file_paths=[str(p) for p in file_paths], hints=hints, timeout_s=timeout_s
            )
            if isinstance(imported, dict):
                if dropped is not None:
                    imported["drop"] = dropped
                if drop_error:
                    imported["dropError"] = drop_error
            return imported

        if operation == "paste":
            text = params.get("text") if isinstance(params.get("text"), str) else None
            if text is None:
                raise AppAdapterError(
                    app=self.name,
                    op=operation,
                    reason="text is required",
                    suggestion="Provide params={text:'Hello'}",
                )

            prefer = str(params.get("prefer") or "ctrl").strip().lower()
            verify = bool(params.get("verify", False))

            if dry_run:
                return {
                    "ok": True,
                    "dry_run": True,
                    "op": "paste",
                    "bytes": len(text.encode("utf-8")),
                    "prefer": prefer,
                    "verify": verify,
                }

            try:
                clipboard_write_text(config, text=text, timeout_s=6.0)
                pasted = paste_best_effort(config, prefer=prefer, verify_screenshot=verify, settle_ms=350)
                return {"ok": True, "op": "paste", "bytes": len(text.encode("utf-8")), "paste": pasted}
            except SmartToolError as exc:
                raise AppAdapterError(
                    app=self.name, op=operation, reason=exc.reason, suggestion=exc.suggestion, details=exc.details
                ) from exc

        # diagram
        strategy = str(params.get("strategy") or "auto").strip().lower()
        if strategy not in {"auto", "paste", "import"}:
            raise AppAdapterError(
                app=self.name,
                op=operation,
                reason="Invalid strategy",
                suggestion="Use strategy='auto'|'paste'|'import'",
                details={"strategy": strategy},
            )

        raw_spec = params.get("spec") if isinstance(params.get("spec"), dict) else params
        spec = raw_spec if isinstance(raw_spec, dict) and raw_spec else default_browser_mcp_architecture_spec()
        svg, meta = diagram_spec_to_svg(spec, layout=DiagramLayout())

        out_dir = _repo_root() / "data" / "outbox"
        out_dir.mkdir(parents=True, exist_ok=True)
        svg_path = out_dir / f"diagram_{int(time.time())}.svg"
        svg_path.write_text(svg, encoding="utf-8")

        hints = merge_import_hints(default_import_hints(), parse_import_hints(params.get("hints")))

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "op": "diagram",
                "strategy": strategy,
                "artifact": {"file": str(svg_path), "type": "image/svg+xml", "meta": meta},
                "importHints": {
                    "open_candidates": list(hints.open_candidates),
                    "choose_candidates": list(hints.choose_candidates),
                    "paths": [list(p) for p in hints.paths],
                    "shortcuts": [c.__dict__ for c in hints.shortcuts],
                },
            }

        paste: dict[str, Any] | None = None
        paste_error: str | None = None

        # Fast path: in extension mode we can write clipboard via offscreen doc and paste.
        if strategy in {"auto", "paste"} and getattr(config, "mode", "launch") == "extension":
            try:
                png_scale = params.get("png_scale")
                png_scale = float(png_scale) if isinstance(png_scale, (int, float)) else 2.0
                clipboard_write_svg(config, svg=svg, include_png=True, scale=png_scale, timeout_s=12.0)
                paste = paste_best_effort(
                    config,
                    prefer="ctrl",
                    verify_screenshot=(strategy == "auto"),
                    settle_ms=350,
                )

                changed = paste.get("changed") is True
                if strategy == "paste" or changed:
                    return {
                        "ok": True,
                        "op": "diagram",
                        "strategy": strategy,
                        "artifact": {"file": str(svg_path), "type": "image/svg+xml", "meta": meta},
                        "paste": paste,
                    }
            except SmartToolError as exc:
                paste_error = exc.reason
            except Exception as exc:  # noqa: BLE001
                paste_error = str(exc)

            if strategy == "paste":
                raise AppAdapterError(
                    app=self.name,
                    op=operation,
                    reason=f"Paste failed: {paste_error or 'unknown error'}",
                    suggestion="Retry, or use strategy='import' to force file chooser import",
                )

        dropped2: dict[str, Any] | None = None
        drop_error2: str | None = None
        if strategy == "auto":
            try:
                dropped2 = drop_files_best_effort(
                    config, file_paths=[str(svg_path)], verify_screenshot=True, settle_ms=1700
                )
                if isinstance(dropped2, dict) and dropped2.get("verify", {}).get("changed") is True:
                    return {
                        "ok": True,
                        "op": "diagram",
                        "strategy": strategy,
                        "artifact": {"file": str(svg_path), "type": "image/svg+xml", "meta": meta},
                        **({"paste": paste} if isinstance(paste, dict) else {}),
                        **({"pasteError": paste_error} if paste_error else {}),
                        "drop": dropped2,
                    }
            except SmartToolError as exc:
                drop_error2 = exc.reason
            except Exception as exc:  # noqa: BLE001
                drop_error2 = str(exc)

        imported = import_via_file_chooser(config, file_paths=[str(svg_path)], hints=hints, timeout_s=12.0)
        return {
            "ok": True,
            "op": "diagram",
            "strategy": strategy,
            "artifact": {"file": str(svg_path), "type": "image/svg+xml", "meta": meta},
            **({"paste": paste} if isinstance(paste, dict) else {}),
            **({"pasteError": paste_error} if paste_error else {}),
            **({"drop": dropped2} if isinstance(dropped2, dict) else {}),
            **({"dropError": drop_error2} if drop_error2 else {}),
            "import": imported,
        }
