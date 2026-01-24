from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

HOST_NAME = "com.openai.browser_mcp"
_LOGGER = logging.getLogger("mcp.browser.native_host_installer")
_EXT_ID_RE = re.compile(r"^[a-p]{32}$")
_EXT_NAME_HINTS = {"Browser MCP", "Browser Extension"}


@dataclass(frozen=True, slots=True)
class InstallTarget:
    label: str
    path: Path


@dataclass(slots=True)
class InstallReport:
    ok: bool = False
    wrote: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    manifest_path: str | None = None


@dataclass(frozen=True, slots=True)
class ExtensionDiscovery:
    ids: list[str]
    user_data_roots: list[Path]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _extension_manifest_path(root: Path) -> Path:
    return root / "vendor" / "browser_extension" / "manifest.json"


def _compute_extension_id(key_b64: str) -> str:
    der = base64.b64decode(key_b64)
    digest = hashlib.sha256(der).digest()[:16]
    alphabet = "abcdefghijklmnop"
    return "".join(alphabet[b >> 4] + alphabet[b & 0xF] for b in digest)


def _manifest_description(root: Path) -> str:
    try:
        data = json.loads(_extension_manifest_path(root).read_text(encoding="utf-8"))
        return str(data.get("description") or "").strip()
    except Exception:
        return ""


def _manifest_name(root: Path) -> str:
    try:
        data = json.loads(_extension_manifest_path(root).read_text(encoding="utf-8"))
        return str(data.get("name") or "").strip()
    except Exception:
        return ""


def _normalize_ext_id(raw: str) -> str | None:
    candidate = str(raw or "").strip().lower()
    if _EXT_ID_RE.match(candidate):
        return candidate
    return None


def _profile_pref_files_for_root(root: Path) -> list[Path]:
    out: list[Path] = []
    for name in ["Default", "Profile *", "Guest Profile", "System Profile"]:
        for profile in sorted(root.glob(name)):
            for pref in ["Preferences", "Secure Preferences"]:
                candidate = profile / pref
                if candidate.exists():
                    out.append(candidate)
    return out


def _extension_root_dir(root: Path) -> Path:
    return _extension_manifest_path(root).parent


def _normalize_fs_path(raw: str, *, platform: str) -> str:
    candidate = str(raw or "").strip()
    if not candidate:
        return ""
    if platform == "win32":
        return str(PureWindowsPath(candidate)).rstrip("\\/").lower()
    try:
        resolved = Path(candidate).expanduser().resolve()
    except Exception:
        resolved = Path(candidate).expanduser()
    return str(resolved).rstrip("/")


def _matches_extension_path(candidate: str, *, expected: set[str], platform: str) -> bool:
    norm = _normalize_fs_path(candidate, platform=platform)
    if not norm:
        return False
    return norm in expected


def _user_data_roots(platform: str, home: Path) -> list[Path]:
    if platform == "darwin":
        base = home / "Library" / "Application Support"
        return [
            base / "Google" / "Chrome",
            base / "Google" / "Chrome Beta",
            base / "Google" / "Chrome Dev",
            base / "Google" / "Chrome Canary",
            base / "Chromium",
            base / "BraveSoftware" / "Brave-Browser",
            base / "Microsoft Edge",
        ]
    if platform.startswith("linux"):
        cfg = home / ".config"
        return [
            cfg / "google-chrome",
            cfg / "google-chrome-beta",
            cfg / "google-chrome-unstable",
            cfg / "google-chrome-dev",
            cfg / "chromium",
            cfg / "BraveSoftware" / "Brave-Browser",
            cfg / "microsoft-edge",
        ]
    if platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else (home / "AppData" / "Local")
        return [
            base / "Google" / "Chrome" / "User Data",
            base / "Google" / "Chrome Beta" / "User Data",
            base / "Google" / "Chrome Dev" / "User Data",
            base / "Google" / "Chrome SxS" / "User Data",
            base / "Chromium" / "User Data",
            base / "BraveSoftware" / "Brave-Browser" / "User Data",
            base / "Microsoft" / "Edge" / "User Data",
        ]
    return []


def _discover_installed_extensions(
    *,
    root: Path | None = None,
    platform: str | None = None,
    home: Path | None = None,
    extra_ids: list[str] | None = None,
) -> ExtensionDiscovery:
    root = root or _repo_root()
    platform = platform or sys.platform
    home = home or Path.home()
    description_hint = _manifest_description(root)
    name_hint = _manifest_name(root)
    ext_dir = _extension_root_dir(root)
    expected_paths: set[str] = set()
    expected_paths.add(_normalize_fs_path(str(ext_dir), platform=platform))
    with contextlib.suppress(Exception):
        expected_paths.add(_normalize_fs_path(str(ext_dir.resolve()), platform=platform))

    found: set[str] = set()
    found_roots: set[Path] = set()
    if extra_ids:
        for raw in extra_ids:
            norm = _normalize_ext_id(raw)
            if norm:
                found.add(norm)

    for base in _user_data_roots(platform, home):
        if not base.exists():
            continue
        for pref in _profile_pref_files_for_root(base):
            try:
                data = json.loads(pref.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            settings = (
                data.get("extensions", {}).get("settings", {}) if isinstance(data.get("extensions"), dict) else {}
            )
            if not isinstance(settings, dict):
                continue
            for ext_id, entry in settings.items():
                norm = _normalize_ext_id(ext_id)
                if not norm:
                    continue
                entry_path = str(entry.get("path") or "").strip() if isinstance(entry, dict) else ""
                matched = False
                if entry_path and _matches_extension_path(entry_path, expected=expected_paths, platform=platform):
                    matched = True
                else:
                    manifest = entry.get("manifest") if isinstance(entry, dict) else None
                    if isinstance(manifest, dict):
                        desc = str(manifest.get("description") or "").strip()
                        name = str(manifest.get("name") or "").strip()
                        if (
                            (description_hint and desc == description_hint)
                            or (name and name in _EXT_NAME_HINTS)
                            or (name_hint and name == name_hint and desc)
                        ):
                            matched = True
                if matched:
                    found.add(norm)
                    found_roots.add(base)

    return ExtensionDiscovery(ids=sorted(found), user_data_roots=sorted(found_roots))


def discover_installed_extension_ids(
    *,
    root: Path | None = None,
    platform: str | None = None,
    home: Path | None = None,
    extra_ids: list[str] | None = None,
) -> list[str]:
    discovery = _discover_installed_extensions(
        root=root,
        platform=platform,
        home=home,
        extra_ids=extra_ids,
    )
    return discovery.ids


def _wrapper_path(root: Path, *, platform: str, venv_dir: Path | None = None) -> Path:
    venv_dir = venv_dir or (root / ".venv")
    if platform == "win32":
        candidate = venv_dir / "Scripts" / "browser-mcp-native-host.cmd"
    else:
        candidate = venv_dir / "bin" / "browser-mcp-native-host"
    if venv_dir.exists():
        return candidate
    base = root / ".native-host"
    return base / ("browser-mcp-native-host.cmd" if platform == "win32" else "browser-mcp-native-host")


def _write_wrapper(path: Path, *, python_exe: str, root: Path, platform: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    py = str(python_exe)
    root_str = str(root)
    if platform == "win32":
        content = "\n".join(
            [
                "@echo off",
                "setlocal",
                f'set "MCP_ROOT={root_str}"',
                'set "PYTHONPATH=%MCP_ROOT%;%PYTHONPATH%"',
                f'"{py}" -m mcp_servers.browser.native_host',
                "",
            ]
        )
    else:
        content = "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f'ROOT="{root_str}"',
                'export PYTHONPATH="$ROOT:${PYTHONPATH:-}"',
                f'exec "{py}" -m mcp_servers.browser.native_host',
                "",
            ]
        )
    path.write_text(content, encoding="utf-8")
    if platform != "win32":
        path.chmod(0o755)


def _targets_for_platform(platform: str, home: Path, *, extra_roots: list[Path] | None = None) -> list[InstallTarget]:
    if platform == "darwin":
        base = home / "Library" / "Application Support"
        targets = [
            InstallTarget("chrome", base / "Google" / "Chrome" / "NativeMessagingHosts"),
            InstallTarget("chrome-beta", base / "Google" / "Chrome Beta" / "NativeMessagingHosts"),
            InstallTarget("chrome-dev", base / "Google" / "Chrome Dev" / "NativeMessagingHosts"),
            InstallTarget("chrome-canary", base / "Google" / "Chrome Canary" / "NativeMessagingHosts"),
            InstallTarget("chromium", base / "Chromium" / "NativeMessagingHosts"),
            InstallTarget("brave", base / "BraveSoftware" / "Brave-Browser" / "NativeMessagingHosts"),
            InstallTarget("edge", base / "Microsoft Edge" / "NativeMessagingHosts"),
        ]
    elif platform.startswith("linux"):
        cfg = home / ".config"
        targets = [
            InstallTarget("chrome", cfg / "google-chrome" / "NativeMessagingHosts"),
            InstallTarget("chrome-beta", cfg / "google-chrome-beta" / "NativeMessagingHosts"),
            InstallTarget("chrome-unstable", cfg / "google-chrome-unstable" / "NativeMessagingHosts"),
            InstallTarget("chrome-dev", cfg / "google-chrome-dev" / "NativeMessagingHosts"),
            InstallTarget("chromium", cfg / "chromium" / "NativeMessagingHosts"),
            InstallTarget("brave", cfg / "BraveSoftware" / "Brave-Browser" / "NativeMessagingHosts"),
            InstallTarget("edge", cfg / "microsoft-edge" / "NativeMessagingHosts"),
        ]
    else:
        targets = []
    for root in extra_roots or []:
        targets.append(InstallTarget("detected", root / "NativeMessagingHosts"))
    seen: set[str] = set()
    deduped: list[InstallTarget] = []
    for target in targets:
        key = str(target.path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(target)
    return deduped


def _windows_manifest_path(home: Path) -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else (home / "AppData" / "Local")
    return base / "BrowserMCP" / "NativeMessagingHosts" / f"{HOST_NAME}.json"


def _windows_registry_targets() -> list[tuple[str, str]]:
    return [
        ("chrome", r"Software\Google\Chrome\NativeMessagingHosts"),
        ("chrome-beta", r"Software\Google\Chrome Beta\NativeMessagingHosts"),
        ("chrome-dev", r"Software\Google\Chrome Dev\NativeMessagingHosts"),
        ("chrome-canary", r"Software\Google\Chrome SxS\NativeMessagingHosts"),
        ("chromium", r"Software\Chromium\NativeMessagingHosts"),
        ("brave", r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts"),
        ("edge", r"Software\Microsoft\Edge\NativeMessagingHosts"),
    ]


def _write_manifest(path: Path, manifest: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        with contextlib.suppress(Exception):
            path.chmod(0o644)


def install_native_host(
    *,
    root: Path | None = None,
    python_exe: str | None = None,
    platform: str | None = None,
    home: Path | None = None,
) -> InstallReport:
    report = InstallReport()
    root = root or _repo_root()
    platform = platform or sys.platform
    home = home or Path.home()
    python_exe = python_exe or sys.executable

    manifest_path = _extension_manifest_path(root)
    if not manifest_path.exists():
        report.errors.append(f"extension manifest not found: {manifest_path}")
        return report

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    key = str(data.get("key") or "").strip()
    if not key:
        report.errors.append("extension manifest missing `key` (required for stable extension id)")
        return report

    default_ext_id = _compute_extension_id(key)
    extra_ids_env = os.environ.get("MCP_EXTENSION_IDS") or os.environ.get("MCP_EXTENSION_ID") or ""
    extra_ids = [s.strip() for s in extra_ids_env.split(",") if s.strip()]
    discovery = _discover_installed_extensions(root=root, platform=platform, home=home, extra_ids=extra_ids)
    discovered = list(discovery.ids)
    if default_ext_id not in discovered:
        discovered.insert(0, default_ext_id)
    allowed_origins = [f"chrome-extension://{ext_id}/" for ext_id in discovered]

    wrapper = _wrapper_path(root, platform=platform)
    try:
        _write_wrapper(wrapper, python_exe=python_exe, root=root, platform=platform)
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"failed to create native host wrapper: {exc}")
        return report

    host_manifest = {
        "name": HOST_NAME,
        "description": "Browser MCP native host (extension bridge).",
        "path": str(wrapper),
        "type": "stdio",
        "allowed_origins": allowed_origins,
    }

    if platform == "win32":
        manifest_file = _windows_manifest_path(home)
        try:
            _write_manifest(manifest_file, host_manifest)
            report.manifest_path = str(manifest_file)
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"failed to write native host manifest: {exc}")
            return report

        try:
            import winreg  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"winreg unavailable: {exc}")
            return report

        wrote_any = False
        for label, reg_path in _windows_registry_targets():
            try:
                full_path = f"{reg_path}\\{HOST_NAME}"
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, full_path) as key_handle:
                    winreg.SetValueEx(key_handle, "", 0, winreg.REG_SZ, str(manifest_file))
                report.wrote.append(f"{label}:HKCU\\{full_path}")
                wrote_any = True
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{label}: registry write failed: {exc}")

        report.ok = wrote_any
        return report

    targets = _targets_for_platform(platform, home, extra_roots=discovery.user_data_roots)
    if not targets:
        report.errors.append(f"unsupported platform for installer: {platform}")
        return report

    out_name = f"{HOST_NAME}.json"
    wrote_any = False
    for target in targets:
        try:
            target.path.mkdir(parents=True, exist_ok=True)
            out_path = target.path / out_name
            _write_manifest(out_path, host_manifest)
            report.wrote.append(f"{target.label}:{out_path}")
            wrote_any = True
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"{target.label}: failed to install: {exc}")

    report.ok = wrote_any
    report.manifest_path = str(wrapper)
    return report


def ensure_native_host_installed() -> InstallReport:
    """Best-effort auto-install for extension mode (fail-soft)."""
    report = InstallReport()
    if str(os.environ.get("MCP_NATIVE_HOST_AUTO_INSTALL") or "1") in {"0", "false", "no"}:
        return report
    try:
        report = install_native_host()
        if report.ok:
            _LOGGER.info("native_host_install_ok targets=%s", report.wrote)
        else:
            _LOGGER.warning("native_host_install_failed errors=%s", report.errors)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("native_host_install_exception %s", exc)
    return report


__all__ = ["HOST_NAME", "InstallReport", "InstallTarget", "install_native_host", "ensure_native_host_installed"]
