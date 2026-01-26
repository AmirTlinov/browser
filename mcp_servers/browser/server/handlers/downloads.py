"""Download/upload handlers for unified tool registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ... import tools
from ...config import BrowserConfig
from ..artifacts import artifact_store
from ..hints import artifact_export_hint, artifact_get_hint
from ..types import ToolResult


def handle_upload(config: BrowserConfig, launcher, args: dict[str, Any]) -> ToolResult:  # noqa: ANN001
    """Upload file."""
    result = tools.upload_file(
        config,
        file_paths=args["file_paths"],
        selector=args.get("selector"),
    )
    return ToolResult.json(result)


def handle_download(config: BrowserConfig, launcher, args: dict[str, Any]) -> ToolResult:  # noqa: ANN001
    """Wait for a download to complete and store it as an artifact (cognitive-cheap)."""
    try:
        timeout = float(args.get("timeout", 30))
    except Exception:
        timeout = 30.0
    timeout = max(1.0, min(timeout, 180.0))

    store = bool(args.get("store", True))
    sha256_enabled = bool(args.get("sha256", True))
    try:
        sha256_max_bytes = int(args.get("sha256_max_bytes", 209_715_200))
    except Exception:
        sha256_max_bytes = 209_715_200
    sha256_max_bytes = max(0, min(sha256_max_bytes, 2_000_000_000))
    baseline = args.get("_baseline")
    if not isinstance(baseline, list):
        baseline = None
    else:
        baseline = [str(x) for x in baseline if isinstance(x, str) and x]

    fallback_url = args.get("url") if isinstance(args.get("url"), str) else None
    fallback_name = None
    if isinstance(args.get("file_name"), str):
        fallback_name = args.get("file_name")
    elif isinstance(args.get("filename"), str):
        fallback_name = args.get("filename")
    try:
        max_bytes = int(args.get("max_bytes")) if args.get("max_bytes") is not None else None
    except Exception:
        max_bytes = None

    result = tools.wait_for_download_or_fetch(
        config,
        timeout=timeout,
        poll_interval=args.get("poll_interval", 0.2),
        stable_ms=args.get("stable_ms", 500),
        baseline=baseline,
        allow_fallback_dirs=bool(args.get("allow_fallback_dirs", True)),
        url=fallback_url,
        file_name=fallback_name,
        max_bytes=max_bytes,
    )

    if not store:
        return ToolResult.json(result)
    dl = result.get("download") if isinstance(result, dict) else None
    if not isinstance(dl, dict):
        return ToolResult.json(result)

    file_name = dl.get("fileName") if isinstance(dl.get("fileName"), str) else None
    mime_type = dl.get("mimeType") if isinstance(dl.get("mimeType"), str) else "application/octet-stream"
    rel_path = dl.get("path") if isinstance(dl.get("path"), str) else None

    # Resolve the downloaded file path safely (prefer repo-relative paths).
    src_path: Path | None = None
    if rel_path and not rel_path.startswith("/"):
        try:
            root = Path(artifact_store.base_dir).resolve().parent.parent
            candidate = (root / rel_path).resolve()
            if candidate.exists() and candidate.is_file():
                src_path = candidate
        except Exception:
            src_path = None

    if src_path is None and isinstance(file_name, str) and file_name:
        try:
            from ...session import session_manager as _session_manager
            from ...tools import downloads as _downloads

            tab_id = _session_manager.tab_id
            if tab_id:
                dl_dir = _session_manager.get_download_dir(tab_id)
                candidate = _downloads._resolve_download_path(file_name, dl_dir)
                if candidate is not None:
                    src_path = candidate
        except Exception:
            src_path = None

    if src_path is None:
        # Keep the download metadata, but avoid failing the whole call.
        dl["stored"] = False
        dl["note"] = "Download detected but could not resolve file path for artifact storage"
        return ToolResult.json(result)

    sha256: str | None = None
    sha256_skipped = False
    if sha256_enabled:
        try:
            size = int(src_path.stat().st_size)
        except Exception:
            size = 0

        if sha256_max_bytes and size > sha256_max_bytes:
            sha256_skipped = True
        else:
            try:
                import hashlib

                h = hashlib.sha256()
                with src_path.open("rb") as f:
                    while True:
                        chunk = f.read(1024 * 1024)
                        if not chunk:
                            break
                        h.update(chunk)
                sha256 = h.hexdigest()
            except Exception:
                sha256 = None

    ext = src_path.suffix if src_path.suffix else None
    ref = artifact_store.put_file(
        kind="download_file",
        src_path=src_path,
        mime_type=mime_type if isinstance(mime_type, str) else "application/octet-stream",
        ext=ext,
        metadata={
            "fileName": file_name,
            "mimeType": mime_type,
            "bytes": dl.get("bytes"),
            **({"sha256": sha256} if isinstance(sha256, str) and sha256 else {}),
            **({"sha256Skipped": True, "sha256MaxBytes": int(sha256_max_bytes)} if sha256_skipped else {}),
            "source": "download",
        },
    )

    # Attach a compact artifact pointer and v2-compatible drilldown hints.
    out = dict(result)
    out["stored"] = True
    out["artifact"] = {
        "id": ref.id,
        "kind": ref.kind,
        "mimeType": ref.mime_type,
        "bytes": ref.bytes,
        "createdAt": ref.created_at,
        **({"sha256": sha256} if isinstance(sha256, str) and sha256 else {}),
    }
    if sha256_skipped:
        out["artifact"]["sha256Skipped"] = True
        out["artifact"]["sha256MaxBytes"] = int(sha256_max_bytes)

    is_textish = (
        str(ref.mime_type or "").startswith("text/")
        or str(ref.mime_type or "").endswith("+json")
        or str(ref.mime_type or "").endswith("+xml")
    )
    if str(ref.mime_type or "").startswith("image/") or is_textish:
        out["next"] = [artifact_get_hint(artifact_id=ref.id, offset=0, max_chars=4000)]
    else:
        out["next"] = [artifact_export_hint(artifact_id=ref.id, overwrite=False)]

    # Do not leak filesystem paths in the agent-visible output.
    try:
        if isinstance(out.get("download"), dict):
            out["download"].pop("path", None)
            if isinstance(sha256, str) and sha256:
                out["download"]["sha256"] = sha256
            if sha256_skipped:
                out["download"]["sha256Skipped"] = True
                out["download"]["sha256MaxBytes"] = int(sha256_max_bytes)
    except Exception:
        pass
    return ToolResult.json(out)
