"""Artifact store for keeping high-fidelity payloads off the agent context window.

Design goals:
- Keep tool responses small (cognitive-cheap) while preserving full fidelity on disk.
- Provide deterministic, minimal metadata + drilldown via a single `artifact` tool.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$")


def _repo_root() -> Path:
    # mcp_servers/browser/server/artifacts.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _make_id(prefix: str) -> str:
    # Deterministic enough for logs; unique enough for a local single-process server.
    suffix = f"{int(time.time() * 1000)}_{os.getpid()}"
    safe_prefix = re.sub(r"[^a-zA-Z0-9_-]+", "_", (prefix or "artifact")).strip("_")
    candidate = f"{safe_prefix}_{suffix}"
    return candidate[:128]


@dataclass(frozen=True)
class ArtifactRef:
    id: str
    kind: str
    mime_type: str
    bytes: int
    created_at: str
    path: str
    truncated: bool = False
    total_chars: int | None = None
    stored_chars: int | None = None


class ArtifactStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or (_repo_root() / "data" / "artifacts")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _validate_id(self, artifact_id: str) -> str:
        if not isinstance(artifact_id, str):
            raise ValueError("artifact id must be a string")
        if not _ID_RE.match(artifact_id):
            raise ValueError("invalid artifact id")
        return artifact_id

    def _meta_path(self, artifact_id: str) -> Path:
        return self.base_dir / f"{artifact_id}.meta.json"

    def _content_path(self, artifact_id: str, ext: str) -> Path:
        ext = ext if ext.startswith(".") else f".{ext}"
        return self.base_dir / f"{artifact_id}{ext}"

    def put_text(
        self,
        *,
        kind: str,
        text: str,
        mime_type: str,
        ext: str,
        total_chars: int | None = None,
        stored_chars: int | None = None,
        truncated: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRef:
        artifact_id = _make_id(kind or "text")
        self._validate_id(artifact_id)

        content_path = self._content_path(artifact_id, ext)
        raw = text if isinstance(text, str) else str(text)
        content_path.write_text(raw, encoding="utf-8")
        size = content_path.stat().st_size

        meta = {
            "id": artifact_id,
            "kind": kind,
            "mimeType": mime_type,
            "ext": ext,
            "bytes": size,
            "createdAt": _now_iso(),
            "truncated": bool(truncated),
            **({"totalChars": int(total_chars)} if isinstance(total_chars, int) else {}),
            **({"storedChars": int(stored_chars)} if isinstance(stored_chars, int) else {}),
            **({"meta": metadata} if isinstance(metadata, dict) and metadata else {}),
        }
        self._meta_path(artifact_id).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return ArtifactRef(
            id=artifact_id,
            kind=str(kind or ""),
            mime_type=str(mime_type or "text/plain"),
            bytes=int(size),
            created_at=str(meta["createdAt"]),
            path=str(content_path),
            truncated=bool(truncated),
            total_chars=int(total_chars) if isinstance(total_chars, int) else None,
            stored_chars=int(stored_chars) if isinstance(stored_chars, int) else None,
        )

    def put_json(self, *, kind: str, obj: Any, metadata: dict[str, Any] | None = None) -> ArtifactRef:
        artifact_id = _make_id(kind or "json")
        self._validate_id(artifact_id)

        content_path = self._content_path(artifact_id, ".json")
        content_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        size = content_path.stat().st_size

        meta = {
            "id": artifact_id,
            "kind": kind,
            "mimeType": "application/json",
            "ext": ".json",
            "bytes": size,
            "createdAt": _now_iso(),
            "truncated": False,
            **({"meta": metadata} if isinstance(metadata, dict) and metadata else {}),
        }
        self._meta_path(artifact_id).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return ArtifactRef(
            id=artifact_id,
            kind=str(kind or ""),
            mime_type="application/json",
            bytes=int(size),
            created_at=str(meta["createdAt"]),
            path=str(content_path),
            truncated=False,
        )

    def put_image_b64(
        self,
        *,
        kind: str,
        data_b64: str,
        mime_type: str = "image/png",
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRef:
        artifact_id = _make_id(kind or "image")
        self._validate_id(artifact_id)

        ext = ".png" if mime_type == "image/png" else ".bin"
        content_path = self._content_path(artifact_id, ext)
        binary = base64.b64decode(data_b64 or "", validate=False)
        content_path.write_bytes(binary)
        size = content_path.stat().st_size

        meta = {
            "id": artifact_id,
            "kind": kind,
            "mimeType": mime_type,
            "ext": ext,
            "bytes": size,
            "createdAt": _now_iso(),
            "truncated": False,
            **({"meta": metadata} if isinstance(metadata, dict) and metadata else {}),
        }
        self._meta_path(artifact_id).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return ArtifactRef(
            id=artifact_id,
            kind=str(kind or ""),
            mime_type=str(mime_type or "image/png"),
            bytes=int(size),
            created_at=str(meta["createdAt"]),
            path=str(content_path),
            truncated=False,
        )

    def put_file(
        self,
        *,
        kind: str,
        src_path: str | Path,
        mime_type: str | None = None,
        ext: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRef:
        """Copy a local file into the artifact store (binary-safe)."""
        path = Path(src_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError("source file not found")

        artifact_id = _make_id(kind or "file")
        self._validate_id(artifact_id)

        inferred_ext = ext
        if not inferred_ext:
            inferred_ext = path.suffix if path.suffix else ".bin"
        if not inferred_ext.startswith("."):
            inferred_ext = "." + inferred_ext

        content_path = self._content_path(artifact_id, inferred_ext)
        shutil.copyfile(path, content_path)
        size = content_path.stat().st_size

        inferred_mime = mime_type or "application/octet-stream"
        meta = {
            "id": artifact_id,
            "kind": kind,
            "mimeType": inferred_mime,
            "ext": inferred_ext,
            "bytes": size,
            "createdAt": _now_iso(),
            "truncated": False,
            **({"meta": metadata} if isinstance(metadata, dict) and metadata else {}),
        }
        self._meta_path(artifact_id).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return ArtifactRef(
            id=artifact_id,
            kind=str(kind or ""),
            mime_type=str(inferred_mime or "application/octet-stream"),
            bytes=int(size),
            created_at=str(meta["createdAt"]),
            path=str(content_path),
            truncated=False,
        )

    def list(self, *, limit: int = 20, kind: str | None = None) -> list[dict[str, Any]]:
        limit = max(0, min(int(limit), 200))
        out: list[tuple[float, dict[str, Any]]] = []

        for meta_path in sorted(self.base_dir.glob("*.meta.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            if not isinstance(meta, dict):
                continue

            if kind and str(meta.get("kind") or "") != str(kind):
                continue

            try:
                mtime = meta_path.stat().st_mtime
            except Exception:
                mtime = 0.0

            out.append(
                (
                    mtime,
                    {
                        "id": meta.get("id"),
                        "kind": meta.get("kind"),
                        "mimeType": meta.get("mimeType"),
                        "bytes": meta.get("bytes"),
                        "createdAt": meta.get("createdAt"),
                        "truncated": meta.get("truncated", False),
                        **({"totalChars": meta.get("totalChars")} if "totalChars" in meta else {}),
                        **({"storedChars": meta.get("storedChars")} if "storedChars" in meta else {}),
                    },
                )
            )

        out.sort(key=lambda t: t[0], reverse=True)
        return [item for _mtime, item in out[:limit]]

    def get_meta(self, *, artifact_id: str) -> dict[str, Any]:
        artifact_id = self._validate_id(artifact_id)
        meta_path = self._meta_path(artifact_id)
        if not meta_path.exists():
            raise FileNotFoundError("artifact not found")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            raise ValueError("invalid artifact metadata")
        return meta

    def get_text_slice(
        self,
        *,
        artifact_id: str,
        offset: int = 0,
        max_chars: int = 4000,
    ) -> dict[str, Any]:
        meta = self.get_meta(artifact_id=artifact_id)
        ext = str(meta.get("ext") or ".txt")
        content_path = self._content_path(str(meta["id"]), ext)
        if not content_path.exists():
            raise FileNotFoundError("artifact content not found")

        raw = content_path.read_text(encoding="utf-8", errors="replace")
        offset = max(0, int(offset))
        # Hard cap to protect agent cognitive budget (tool output is still text).
        max_chars = max(0, min(int(max_chars), 20_000))
        slice_text = raw[offset : offset + max_chars] if max_chars else ""
        truncated = offset + max_chars < len(raw)

        return {
            "artifact": {
                "id": meta.get("id"),
                "kind": meta.get("kind"),
                "mimeType": meta.get("mimeType"),
                "bytes": meta.get("bytes"),
                "createdAt": meta.get("createdAt"),
                "path": str(content_path),
                "offset": offset,
                "returnedChars": len(slice_text),
                "totalChars": len(raw),
                "truncated": truncated,
            },
            "text": slice_text,
        }

    def get_image_b64(self, *, artifact_id: str) -> tuple[dict[str, Any], str, str]:
        meta = self.get_meta(artifact_id=artifact_id)
        ext = str(meta.get("ext") or ".png")
        content_path = self._content_path(str(meta["id"]), ext)
        if not content_path.exists():
            raise FileNotFoundError("artifact content not found")
        binary = content_path.read_bytes()
        data_b64 = base64.b64encode(binary).decode("ascii")
        mime_type = str(meta.get("mimeType") or "image/png")
        payload = {
            "artifact": {
                "id": meta.get("id"),
                "kind": meta.get("kind"),
                "mimeType": mime_type,
                "bytes": meta.get("bytes"),
                "createdAt": meta.get("createdAt"),
                "path": str(content_path),
            }
        }
        return payload, data_b64, mime_type

    def delete(self, *, artifact_id: str) -> bool:
        meta = self.get_meta(artifact_id=artifact_id)
        ext = str(meta.get("ext") or ".txt")
        content_path = self._content_path(str(meta["id"]), ext)
        meta_path = self._meta_path(str(meta["id"]))

        ok = True
        try:
            if content_path.exists():
                content_path.unlink()
        except Exception:
            ok = False
        try:
            if meta_path.exists():
                meta_path.unlink()
        except Exception:
            ok = False
        return ok

    def export(
        self,
        *,
        artifact_id: str,
        out_dir: Path | None = None,
        name: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Export an artifact content file into a user-facing outbox folder.

        Returns a small, AI-friendly payload with a repo-relative path (no absolute paths).
        """
        meta = self.get_meta(artifact_id=artifact_id)
        ext = str(meta.get("ext") or ".bin")
        content_path = self._content_path(str(meta["id"]), ext)
        if not content_path.exists():
            raise FileNotFoundError("artifact content not found")

        root = _repo_root()
        out_dir = out_dir or (root / "data" / "outbox")
        out_dir.mkdir(parents=True, exist_ok=True)

        raw_name = (name or "").strip()
        if raw_name:
            # Keep export name safe and deterministic: no paths, no control chars.
            safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", raw_name).strip("._")
        else:
            safe = ""

        if not safe:
            safe = f"{meta.get('id')}{ext}"
        elif "." not in safe and isinstance(ext, str) and ext.startswith("."):
            safe = f"{safe}{ext}"

        # Hard cap to avoid ridiculous filenames.
        if len(safe) > 200:
            safe = safe[:200]

        dest_path = out_dir / safe
        if dest_path.exists() and not overwrite:
            raise FileExistsError("export destination exists")

        shutil.copyfile(content_path, dest_path)
        size = dest_path.stat().st_size

        try:
            rel = dest_path.relative_to(root)
            rel_path = str(rel)
        except Exception:
            rel_path = str(dest_path.name)

        return {
            "ok": True,
            "export": {
                "path": rel_path,
                "name": safe,
                "bytes": int(size),
            },
            "artifact": {
                "id": meta.get("id"),
                "kind": meta.get("kind"),
                "mimeType": meta.get("mimeType"),
                "bytes": meta.get("bytes"),
                "createdAt": meta.get("createdAt"),
            },
        }


artifact_store = ArtifactStore()
