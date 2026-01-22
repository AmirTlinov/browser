from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from typing import Any

from .. import tools
from ..config import BrowserConfig
from ..tools.base import SmartToolError
from ..tools.smart.overlay import dismiss_blocking_overlay_best_effort
from .file_chooser import enable_file_chooser_intercept, set_files_via_file_chooser


@dataclass(frozen=True)
class KeyChord:
    """A keyboard shortcut expressed as a key + modifiers."""

    key: str
    alt: bool = False
    ctrl: bool = False
    meta: bool = False
    shift: bool = False
    note: str | None = None

    def modifiers_bitmask(self) -> int:
        # CDP modifiers bitmask: 1=Alt, 2=Ctrl, 4=Meta, 8=Shift
        return (1 if self.alt else 0) | (2 if self.ctrl else 0) | (4 if self.meta else 0) | (8 if self.shift else 0)


@dataclass(frozen=True)
class ImportHints:
    """Heuristics for opening a file chooser in a complex web app."""

    # Candidates to click to open an "import/upload" panel/menu.
    open_candidates: tuple[str, ...] = ()
    # Candidates to click that should directly open the native file chooser.
    choose_candidates: tuple[str, ...] = ()
    # Keyboard shortcuts to try (best effort) to open a chooser.
    shortcuts: tuple[KeyChord, ...] = ()
    # Explicit multi-step click paths (each path is a sequence of keywords to click).
    # Useful for nested menus: e.g., ["Tools", "Upload", "My device"].
    paths: tuple[tuple[str, ...], ...] = ()


def _norm_list(raw: Any, *, max_items: int = 50, max_len: int = 80) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if not s:
            continue
        out.append(s[:max_len])
        if len(out) >= max_items:
            break
    return tuple(out)


def _parse_shortcuts(raw: Any) -> tuple[KeyChord, ...]:
    if not isinstance(raw, list):
        return ()
    out: list[KeyChord] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not isinstance(key, str) or not key.strip():
            continue
        out.append(
            KeyChord(
                key=key.strip(),
                alt=bool(item.get("alt", False)),
                ctrl=bool(item.get("ctrl", False)),
                meta=bool(item.get("meta", False)),
                shift=bool(item.get("shift", False)),
                note=str(item.get("note")) if isinstance(item.get("note"), str) else None,
            )
        )
        if len(out) >= 20:
            break
    return tuple(out)


def parse_import_hints(raw: Any) -> ImportHints:
    """Parse user/adapter-provided hints for import flows (best-effort)."""
    if not isinstance(raw, dict):
        return ImportHints()
    raw_paths = raw.get("paths")
    paths: list[tuple[str, ...]] = []
    if isinstance(raw_paths, list):
        for p in raw_paths:
            if not isinstance(p, list):
                continue
            seq = _norm_list(p, max_items=10, max_len=80)
            if not seq:
                continue
            paths.append(seq)
            if len(paths) >= 20:
                break
    return ImportHints(
        open_candidates=_norm_list(raw.get("open_candidates") or raw.get("openCandidates")),
        choose_candidates=_norm_list(raw.get("choose_candidates") or raw.get("chooseCandidates")),
        shortcuts=_parse_shortcuts(raw.get("shortcuts")),
        paths=tuple(paths),
    )


def merge_import_hints(base: ImportHints, override: ImportHints) -> ImportHints:
    """Merge hints with "override-first" priority and de-duplication."""

    def dedup_str(items: tuple[str, ...]) -> tuple[str, ...]:
        seen: set[str] = set()
        out: list[str] = []
        for it in items:
            key = str(it).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(it)
        return tuple(out)

    def dedup_chords(items: tuple[KeyChord, ...]) -> tuple[KeyChord, ...]:
        seen: set[tuple[str, int]] = set()
        out: list[KeyChord] = []
        for ch in items:
            try:
                k = (str(ch.key).strip().lower(), int(ch.modifiers_bitmask()))
            except Exception:
                continue
            if k in seen:
                continue
            seen.add(k)
            out.append(ch)
        return tuple(out)

    def dedup_paths(items: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...]:
        seen: set[tuple[str, ...]] = set()
        out: list[tuple[str, ...]] = []
        for p in items:
            norm = tuple(str(x).strip().lower() for x in p if isinstance(x, str) and str(x).strip())
            if not norm:
                continue
            if norm in seen:
                continue
            seen.add(norm)
            out.append(tuple(p))
        return tuple(out)

    return ImportHints(
        open_candidates=dedup_str(tuple(override.open_candidates) + tuple(base.open_candidates)),
        choose_candidates=dedup_str(tuple(override.choose_candidates) + tuple(base.choose_candidates)),
        shortcuts=dedup_chords(tuple(override.shortcuts) + tuple(base.shortcuts)),
        paths=dedup_paths(tuple(override.paths) + tuple(base.paths)),
    )


def default_import_hints() -> ImportHints:
    """Generic (cross-site) import heuristics, language-agnostic-ish (EN/RU minimal)."""
    return ImportHints(
        # Stage A: open any import/upload surface (best-effort).
        open_candidates=(
            # EN
            "upload",
            "import",
            "insert",
            "place",
            "open",
            "file",
            # RU (stems to match prefixes/contains)
            "загруз",
            "импорт",
            "встав",
            "откры",
            "файл",
        ),
        # Stage B: trigger file chooser
        choose_candidates=(
            # EN
            "my device",
            "from device",
            "browse",
            "choose file",
            "select file",
            # RU
            "моё устройство",
            "мое устройство",
            "с устройства",
            "обзор",
            "выберите файл",
            "выбрать файл",
        ),
        # Keyboard shortcuts: attempt to open a chooser without UI clicking.
        shortcuts=(
            KeyChord(key="o", ctrl=True, note="Ctrl+O (common: open/import)"),
            KeyChord(key="o", meta=True, note="Cmd+O (macOS common: open/import)"),
        ),
        paths=(),
    )


def _click_keyword(config: BrowserConfig, *, keyword: str) -> bool:
    """Best-effort click by keyword using AX (safer for canvas apps than CSS selectors)."""
    k = str(keyword or "").strip()
    if not k:
        return False
    try:
        tools.click_accessibility(config, role=None, name=k, index=0)
        return True
    except Exception:
        return False


def import_via_file_chooser(
    config: BrowserConfig,
    *,
    file_paths: list[str],
    hints: ImportHints | None = None,
    timeout_s: float = 12.0,
) -> dict[str, Any]:
    """Universal "import file into the current web app" (best-effort).

    Core idea:
    - Intercept the native file chooser (CDP).
    - Trigger it via keyboard shortcuts and/or UI keyword clicks.
    - Accept by setting files on the intercepted chooser input.
    """
    hints = hints or default_import_hints()
    timeout_s = max(2.0, min(float(timeout_s), 60.0))

    # Always run under intercept; disable in a finally.
    enable_file_chooser_intercept(config, enabled=True)
    try:
        # Generic overlay dismissal: helps when cookie banners/onboarding dialogs intercept clicks.
        # Keep bounded: import should remain fast and not spin.
        try:
            for _ in range(2):
                dismissed = dismiss_blocking_overlay_best_effort(config)
                if not dismissed:
                    break
                time.sleep(0.08)
        except Exception:
            pass

        # Strategy 1: shortcuts (fast, language-agnostic)
        for chord in hints.shortcuts:
            try:
                tools.press_key(config, chord.key, modifiers=chord.modifiers_bitmask())
                chooser = set_files_via_file_chooser(config, file_paths=file_paths, timeout=min(1.2, timeout_s))
                return {"ok": True, "strategy": "shortcut", "shortcut": chord.key, "chooser": chooser}
            except SmartToolError:
                continue
            except Exception:
                continue

        # Strategy 1b: explicit click paths (fast when known, still generic via keywords).
        for path in hints.paths:
            ok_path = True
            for kw in path:
                if not _click_keyword(config, keyword=kw):
                    ok_path = False
                    break
                time.sleep(0.05)
            if not ok_path:
                continue
            try:
                chooser = set_files_via_file_chooser(config, file_paths=file_paths, timeout=min(6.0, timeout_s))
                return {"ok": True, "strategy": "path", "path": list(path), "chooser": chooser}
            except SmartToolError:
                continue
            except Exception:
                continue

        # Strategy 2: direct chooser candidates (click "My device"/"Browse" without opening menus)
        for kw in hints.choose_candidates:
            if not _click_keyword(config, keyword=kw):
                continue
            try:
                chooser = set_files_via_file_chooser(config, file_paths=file_paths, timeout=min(3.0, timeout_s))
                return {"ok": True, "strategy": "choose_candidate", "keyword": kw, "chooser": chooser}
            except SmartToolError:
                continue
            except Exception:
                continue

        # Strategy 3: open surface then choose
        for open_kw in ("", *hints.open_candidates):
            if open_kw:
                _click_keyword(config, keyword=open_kw)
                time.sleep(0.05)

            for choose_kw in hints.choose_candidates:
                if not _click_keyword(config, keyword=choose_kw):
                    continue
                try:
                    chooser = set_files_via_file_chooser(config, file_paths=file_paths, timeout=min(5.0, timeout_s))
                    return {
                        "ok": True,
                        "strategy": "open_then_choose",
                        **({"open": open_kw} if open_kw else {}),
                        "choose": choose_kw,
                        "chooser": chooser,
                    }
                except SmartToolError:
                    continue
                except Exception:
                    continue

        raise SmartToolError(
            tool="import_flow",
            action="import",
            reason="Failed to trigger a file chooser via shortcuts or UI heuristics",
            suggestion="Provide params.hints with better open/choose candidates or add a site-specific adapter",
            details={
                "openCandidates": list(hints.open_candidates),
                "chooseCandidates": list(hints.choose_candidates),
                "paths": [list(p) for p in hints.paths],
                "shortcuts": [c.__dict__ for c in hints.shortcuts],
            },
        )
    finally:
        # Best-effort cleanup.
        with contextlib.suppress(Exception):
            enable_file_chooser_intercept(config, enabled=False)
