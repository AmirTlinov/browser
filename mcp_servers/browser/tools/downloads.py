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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import BrowserConfig
from ..session import session_manager
from .base import SmartToolError, get_session


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


def wait_for_download(
    config: BrowserConfig,
    *,
    timeout: float = 30.0,
    poll_interval: float = 0.2,
    stable_ms: int = 500,
    baseline: list[str] | None = None,
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
        if not (isinstance(dl_cfg, dict) and dl_cfg.get("enabled") is True and dl_cfg.get("available") is True):
            raise SmartToolError(
                tool="download",
                action="configure",
                reason="Downloads are not available (CDP download behavior could not be set)",
                suggestion="Try again, or run in permissive policy; if it persists, update Chrome/Chromium to a version that supports Page.setDownloadBehavior.",
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
            raise SmartToolError(
                tool="download",
                action="wait",
                reason="Timed out waiting for a new download",
                suggestion="Trigger the download (click) then call download wait with a longer timeout",
                details={"timeoutSec": timeout_f},
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
            },
            "target": target["id"],
            "sessionTabId": session_manager.tab_id,
        }
