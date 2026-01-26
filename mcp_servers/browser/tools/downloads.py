"""Downloads utilities (best-effort, cognitive-cheap).

Goal:
- Allow agents to reliably capture downloads without flooding context with logs.
- Prefer deterministic filesystem-based detection over protocol guessing.

Design:
- Configure a per-tab download directory via CDP (best-effort).
- Wait for a new file to appear and stabilize.
"""

from __future__ import annotations

import mimetypes
import os
import re
import ssl
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from contextlib import suppress
import shutil

from ..config import BrowserConfig
from ..http_client import HttpClientError
from ..session import session_manager
from ..session_helpers import _downloads_root, _repo_root
from .base import SmartToolError, ensure_allowed, get_session


@dataclass(frozen=True)
class _DownloadCandidate:
    path: Path
    started_from_temp: bool = False


def _read_xdg_download_dir() -> Path | None:
    cfg = Path.home() / ".config" / "user-dirs.dirs"
    if not cfg.exists():
        return None
    try:
        lines = cfg.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return None
    for line in lines:
        if not line.startswith("XDG_DOWNLOAD_DIR="):
            continue
        raw = line.split("=", 1)[1].strip()
        if raw.startswith("\"") and raw.endswith("\""):
            raw = raw[1:-1]
        raw = raw.replace("$HOME", str(Path.home()))
        try:
            raw = str(Path(raw).expanduser())
        except Exception:
            pass
        candidate = Path(raw)
        return candidate
    return None


def _default_download_dirs(primary_dir: Path) -> list[Path]:
    dirs: list[Path] = []
    xdg_dir = _read_xdg_download_dir()
    if xdg_dir and xdg_dir != primary_dir:
        dirs.append(xdg_dir)
    home_downloads = Path.home() / "Downloads"
    if home_downloads != primary_dir and home_downloads not in dirs:
        dirs.append(home_downloads)
    return [d for d in dirs if d.exists() and d.is_dir()]


def _resolve_download_path(file_name: str, primary_dir: Path) -> Path | None:
    if not file_name:
        return None
    for directory in [primary_dir, *_default_download_dirs(primary_dir)]:
        try:
            candidate = (directory / file_name).resolve()
        except Exception:
            continue
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _download_max_bytes(config: BrowserConfig) -> int:
    raw = os.environ.get("MCP_DOWNLOAD_MAX_BYTES")
    if isinstance(raw, str) and raw.strip():
        try:
            return max(0, min(int(raw.strip()), 2_000_000_000))
        except Exception:
            pass
    try:
        cfg = int(getattr(config, "http_max_bytes", 1_000_000))
    except Exception:
        cfg = 1_000_000
    return max(cfg, 50_000_000)


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", name or "").strip().strip(".")
    return cleaned or "download"


def _filename_from_cd(header: str | None) -> str | None:
    if not isinstance(header, str) or not header:
        return None
    # Try RFC 5987 filename*=UTF-8''... first.
    m = re.search(r"filename\\*=([^;]+)", header, flags=re.IGNORECASE)
    if m:
        raw = m.group(1).strip().strip("\"'")
        if raw.lower().startswith("utf-8''"):
            raw = raw[7:]
        try:
            return urllib.parse.unquote(raw)
        except Exception:
            return raw
    m = re.search(r"filename=([^;]+)", header, flags=re.IGNORECASE)
    if m:
        raw = m.group(1).strip().strip("\"'")
        return raw
    return None


def _filename_from_url(url: str) -> str | None:
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return None
    if not parsed.path:
        return None
    name = Path(urllib.parse.unquote(parsed.path)).name
    return name or None


class _SafeRedirectHandler(HTTPRedirectHandler):
    def __init__(self, config: BrowserConfig) -> None:
        super().__init__()
        self._config = config

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        absolute = urllib.parse.urljoin(req.full_url, str(newurl))
        parsed = urllib.parse.urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            raise SmartToolError(
                tool="download",
                action="fetch",
                reason="Only http/https redirects are supported",
                suggestion="Use a direct http(s) URL or a file:// URL",
                details={"redirect": absolute},
            )
        if not self._config.is_host_allowed(parsed.hostname or ""):
            raise SmartToolError(
                tool="download",
                action="fetch",
                reason=f"Host {parsed.hostname} is not in allowlist (redirect)",
                suggestion="Update MCP_ALLOW_HOSTS allowlist",
                details={"redirect": absolute},
            )
        return super().redirect_request(req, fp, code, msg, headers, absolute)


def _download_via_url(
    config: BrowserConfig,
    *,
    url: str,
    file_name: str | None,
    max_bytes: int,
    timeout: float,
    dest_dir: Path | None,
) -> dict[str, Any]:
    if not isinstance(url, str) or not url.strip():
        raise SmartToolError(
            tool="download",
            action="fetch",
            reason="url must be a non-empty string",
            suggestion="Provide url=\"https://...\" or url=\"file:///...\"",
        )
    url = url.strip()
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme == "file":
        policy = session_manager.get_policy()
        if policy.get("allowFileScheme") is False:
            raise SmartToolError(
                tool="download",
                action="fetch",
                reason="file:// downloads are blocked by policy",
                suggestion="Switch to permissive policy or use http(s) URL",
            )
        path = Path(urllib.parse.unquote(parsed.path)).expanduser()
        if not path.exists() or not path.is_file():
            raise SmartToolError(
                tool="download",
                action="fetch",
                reason="file:// path does not exist",
                suggestion="Ensure the file exists and is accessible",
                details={"path": str(path)},
            )
        try:
            size = int(path.stat().st_size)
        except Exception:
            size = 0
        if max_bytes and size > max_bytes:
            raise SmartToolError(
                tool="download",
                action="fetch",
                reason="Download exceeded max_bytes limit",
                suggestion="Increase MCP_DOWNLOAD_MAX_BYTES",
                details={"maxBytes": int(max_bytes)},
            )
        if dest_dir is not None:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_name = _safe_filename(file_name or path.name)
            candidate = dest_dir / dest_name
            if candidate.exists():
                suffix = 1
                while (dest_dir / f"{candidate.stem}-{suffix}{candidate.suffix}").exists():
                    suffix += 1
                candidate = dest_dir / f"{candidate.stem}-{suffix}{candidate.suffix}"
            shutil.copy2(path, candidate)
            path = candidate
        mime, _enc = mimetypes.guess_type(str(path))
        return {
            "path": path,
            "fileName": _safe_filename(file_name or path.name),
            "mimeType": mime or "application/octet-stream",
            "bytes": int(path.stat().st_size),
            "fallback": True,
        }

    if parsed.scheme not in ("http", "https"):
        raise SmartToolError(
            tool="download",
            action="fetch",
            reason="Only http(s) or file URLs are supported",
            suggestion="Provide a valid URL or use the browser download capture",
        )

    try:
        ensure_allowed(url, config)
    except HttpClientError as exc:
        raise SmartToolError(
            tool="download",
            action="fetch",
            reason=str(exc),
            suggestion="Update MCP_ALLOW_HOSTS allowlist or use a permitted URL",
        ) from exc

    dest = dest_dir or _downloads_root()
    dest.mkdir(parents=True, exist_ok=True)

    req = Request(url, headers={"User-Agent": "mcp-browser/1.0"})
    ctx = ssl.create_default_context()
    opener = build_opener(_SafeRedirectHandler(config), HTTPSHandler(context=ctx))

    try:
        with opener.open(req, timeout=timeout) as resp:
            cd = resp.headers.get("Content-Disposition")
            name = file_name or _filename_from_cd(cd) or _filename_from_url(url) or "download"
            name = _safe_filename(name)
            candidate = dest / name
            if candidate.exists():
                suffix = 1
                while (dest / f"{candidate.stem}-{suffix}{candidate.suffix}").exists():
                    suffix += 1
                candidate = dest / f"{candidate.stem}-{suffix}{candidate.suffix}"

            total = 0
            try:
                with candidate.open("wb") as f:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if max_bytes and total > max_bytes:
                            raise SmartToolError(
                                tool="download",
                                action="fetch",
                                reason="Download exceeded max_bytes limit",
                                suggestion="Increase MCP_DOWNLOAD_MAX_BYTES or use CDP download capture",
                                details={"maxBytes": int(max_bytes)},
                            )
                        f.write(chunk)
            except SmartToolError:
                with suppress(Exception):
                    if candidate.exists():
                        candidate.unlink()
                raise

            mime = resp.headers.get("Content-Type")
            if not isinstance(mime, str) or not mime:
                mime, _enc = mimetypes.guess_type(str(candidate))
            return {
                "path": candidate,
                "fileName": candidate.name,
                "mimeType": mime or "application/octet-stream",
                "bytes": int(total),
                "fallback": True,
            }
    except SmartToolError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SmartToolError(
            tool="download",
            action="fetch",
            reason=str(exc) or "Download fetch failed",
            suggestion="Check URL, allowlist, or network connectivity",
        ) from exc


def wait_for_download(
    config: BrowserConfig,
    *,
    timeout: float = 30.0,
    poll_interval: float = 0.2,
    stable_ms: int = 500,
    baseline: list[str] | None = None,
    allow_fallback_dirs: bool = True,
) -> dict[str, Any]:
    """Wait for a new download to complete and return metadata (no artifact storage here).

    Notes:
    - This function is binary-safe (does not read file contents).
    - It returns a repo-relative path when possible (no absolute paths by default).
    - `baseline` is an internal escape hatch used by run/flow auto-capture to avoid
      missing instant downloads (baseline taken *before* a click).
    """
    try:
        timeout_f = float(timeout)
    except Exception:
        timeout_f = 30.0
    timeout_f = max(1.0, min(timeout_f, 180.0))

    try:
        poll_f = float(poll_interval)
    except Exception:
        poll_f = 0.2
    poll_f = max(0.05, min(poll_f, 1.0))

    stable_s = max(0.0, float(max(0, int(stable_ms))) / 1000.0)

    with get_session(config) as (session, target):
        dl_cfg = session_manager.ensure_downloads(session)
        downloads_available = (
            isinstance(dl_cfg, dict) and dl_cfg.get("enabled") is True and dl_cfg.get("available") is True
        )
        if not downloads_available and not allow_fallback_dirs:
            raise SmartToolError(
                tool="download",
                action="configure",
                reason="Downloads are not available (CDP download behavior could not be set)",
                suggestion="Re-run with allow_fallback_dirs=true, or update Chrome/Chromium to a version that supports Page.setDownloadBehavior.",
                details={"downloadConfig": dl_cfg if isinstance(dl_cfg, dict) else {}},
            )

        if session.tab_id is None:
            raise SmartToolError(
                tool="download",
                action="session",
                reason="No active tab id",
                suggestion="Navigate to a page first, then retry download wait",
            )

        dl_dir = session_manager.get_download_dir(session.tab_id)
        fallback_dirs = _default_download_dirs(dl_dir)
        if isinstance(baseline, list) and baseline:
            baseline_set = {str(n) for n in baseline if isinstance(n, str) and n}
        else:
            baseline_set = {p.name for p in dl_dir.iterdir() if p.is_file()}
        fallback_baselines: dict[Path, set[str]] = {}
        for directory in fallback_dirs:
            try:
                fallback_baselines[directory] = {p.name for p in directory.iterdir() if p.is_file()}
            except Exception:
                fallback_baselines[directory] = set()

        deadline = time.time() + timeout_f
        candidate: _DownloadCandidate | None = None
        last_size: int | None = None
        stable_since: float | None = None

        def _list_files(directory: Path) -> list[Path]:
            try:
                return [p for p in directory.iterdir() if p.is_file()]
            except Exception:
                return []

        def _pick_candidate(files: list[Path], baseline: set[str]) -> _DownloadCandidate | None:
            new_files = [p for p in files if p.name not in baseline]
            if not new_files:
                return None
            tmp = [p for p in new_files if p.name.endswith(".crdownload")]
            if tmp:
                tmp.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
                t = tmp[0]
                final_name = t.name[: -len(".crdownload")]
                if final_name:
                    return _DownloadCandidate(path=t.parent / final_name, started_from_temp=True)
            finals = [p for p in new_files if not p.name.endswith(".crdownload")]
            if finals:
                finals.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
                return _DownloadCandidate(path=finals[0], started_from_temp=False)
            return None

        while time.time() < deadline:
            candidate = _pick_candidate(_list_files(dl_dir), baseline_set)
            if candidate is None:
                for directory in fallback_dirs:
                    base = fallback_baselines.get(directory, set())
                    candidate = _pick_candidate(_list_files(directory), base)
                    if candidate is not None:
                        break

            if candidate is not None and candidate.path.exists():
                try:
                    size = int(candidate.path.stat().st_size)
                except Exception:
                    size = 0

                if last_size is not None and size == last_size:
                    if stable_since is None:
                        stable_since = time.time()
                    if stable_s <= 0.0 or (time.time() - stable_since) >= stable_s:
                        break
                else:
                    last_size = size
                    stable_since = None

            time.sleep(poll_f)

        if candidate is None or not candidate.path.exists():
            suggestion = "Trigger the download (click) then call download wait with a longer timeout"
            if not downloads_available:
                suggestion = (
                    "CDP downloads unavailable. Retry with url=... (direct fetch) or ensure browser supports "
                    "Page.setDownloadBehavior."
                )
            raise SmartToolError(
                tool="download",
                action="wait",
                reason="Timed out waiting for a new download",
                suggestion=suggestion,
                details={
                    "timeoutSec": timeout_f,
                    "downloadConfig": dl_cfg if isinstance(dl_cfg, dict) else {},
                    "fallbackDirs": [str(p) for p in fallback_dirs],
                },
            )

        path = candidate.path
        try:
            size = int(path.stat().st_size)
        except Exception:
            size = 0

        mime, _enc = mimetypes.guess_type(str(path))
        mime = mime or "application/octet-stream"
        ext = path.suffix if path.suffix else ""

        # Repo-relative path (no absolute paths by default).
        try:
            rel = path.resolve().relative_to(Path(__file__).resolve().parents[3])
            rel_path = str(rel)
        except Exception:
            rel_path = path.name

        return {
            "download": {
                "fileName": path.name,
                "bytes": size,
                "mimeType": mime,
                **({"ext": ext} if ext else {}),
                "path": rel_path,
                **({"startedFromTemp": True} if candidate.started_from_temp else {}),
                **({"unmanaged": True} if not downloads_available else {}),
            },
            "target": target["id"],
            "sessionTabId": session_manager.tab_id,
        }


def wait_for_download_or_fetch(
    config: BrowserConfig,
    *,
    timeout: float = 30.0,
    poll_interval: float = 0.2,
    stable_ms: int = 500,
    baseline: list[str] | None = None,
    allow_fallback_dirs: bool = True,
    url: str | None = None,
    file_name: str | None = None,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Wait for a download; fall back to direct URL/file fetch if provided."""
    try:
        return wait_for_download(
            config,
            timeout=timeout,
            poll_interval=poll_interval,
            stable_ms=stable_ms,
            baseline=baseline,
            allow_fallback_dirs=allow_fallback_dirs,
        )
    except SmartToolError as exc:
        if not (isinstance(url, str) and url.strip()):
            raise

        tab_id = session_manager.tab_id
        dest_dir = session_manager.get_download_dir(tab_id) if tab_id else None
        max_bytes_i = int(max_bytes) if isinstance(max_bytes, int) and max_bytes > 0 else _download_max_bytes(config)
        fetched = _download_via_url(
            config,
            url=url,
            file_name=file_name,
            max_bytes=max_bytes_i,
            timeout=timeout,
            dest_dir=dest_dir,
        )
        path = fetched.get("path")
        if not isinstance(path, Path):
            raise exc
        try:
            rel = path.resolve().relative_to(_repo_root())
            rel_path = str(rel)
        except Exception:
            rel_path = path.name
        return {
            "download": {
                "fileName": fetched.get("fileName"),
                "bytes": fetched.get("bytes"),
                "mimeType": fetched.get("mimeType"),
                "path": rel_path,
                "fallback": True,
                "unmanaged": True,
            },
            "target": tab_id,
            "sessionTabId": tab_id,
        }
