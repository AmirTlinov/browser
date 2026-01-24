from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from .native_broker_discovery import discover_best_broker
from .native_broker_paths import runtime_dir
from .native_host_installer import HOST_NAME

_EXT_ORIGIN_PREFIX = "chrome-extension://"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _extension_manifest_path(root: Path) -> Path:
    return root / "vendor" / "browser_extension" / "manifest.json"


def _compute_extension_id(key_b64: str) -> str:
    der = base64.b64decode(key_b64)
    digest = hashlib.sha256(der).digest()[:16]
    alphabet = "abcdefghijklmnop"
    return "".join(alphabet[b >> 4] + alphabet[b & 0xF] for b in digest)


def _expected_extension_id(root: Path) -> tuple[str | None, str | None]:
    manifest_path = _extension_manifest_path(root)
    if not manifest_path.exists():
        return None, f"extension manifest not found: {manifest_path}"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, f"failed to parse extension manifest: {exc}"

    key = str(data.get("key") or "").strip()
    if not key:
        return None, "extension manifest missing `key` (required for stable extension id)"

    try:
        return _compute_extension_id(key), None
    except Exception as exc:  # noqa: BLE001
        return None, f"failed to compute extension id from manifest key: {exc}"


def _wrapper_path(root: Path, *, platform: str) -> Path:
    venv_dir = root / ".venv"
    if platform == "win32":
        candidate = venv_dir / "Scripts" / "browser-mcp-native-host.cmd"
    else:
        candidate = venv_dir / "bin" / "browser-mcp-native-host"
    if venv_dir.exists():
        return candidate
    base = root / ".native-host"
    return base / ("browser-mcp-native-host.cmd" if platform == "win32" else "browser-mcp-native-host")


def _native_host_manifest_candidates(*, platform: str, home: Path) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    if platform == "darwin":
        base = home / "Library" / "Application Support"
        out.extend(
            [
                ("chrome", base / "Google" / "Chrome" / "NativeMessagingHosts" / f"{HOST_NAME}.json"),
                ("chrome-beta", base / "Google" / "Chrome Beta" / "NativeMessagingHosts" / f"{HOST_NAME}.json"),
                ("chrome-dev", base / "Google" / "Chrome Dev" / "NativeMessagingHosts" / f"{HOST_NAME}.json"),
                ("chrome-canary", base / "Google" / "Chrome Canary" / "NativeMessagingHosts" / f"{HOST_NAME}.json"),
                ("chromium", base / "Chromium" / "NativeMessagingHosts" / f"{HOST_NAME}.json"),
                ("brave", base / "BraveSoftware" / "Brave-Browser" / "NativeMessagingHosts" / f"{HOST_NAME}.json"),
                ("edge", base / "Microsoft Edge" / "NativeMessagingHosts" / f"{HOST_NAME}.json"),
            ]
        )
        return out

    if platform.startswith("linux"):
        cfg = home / ".config"
        out.extend(
            [
                ("chrome", cfg / "google-chrome" / "NativeMessagingHosts" / f"{HOST_NAME}.json"),
                ("chrome-beta", cfg / "google-chrome-beta" / "NativeMessagingHosts" / f"{HOST_NAME}.json"),
                ("chrome-unstable", cfg / "google-chrome-unstable" / "NativeMessagingHosts" / f"{HOST_NAME}.json"),
                ("chrome-dev", cfg / "google-chrome-dev" / "NativeMessagingHosts" / f"{HOST_NAME}.json"),
                ("chromium", cfg / "chromium" / "NativeMessagingHosts" / f"{HOST_NAME}.json"),
                ("brave", cfg / "BraveSoftware" / "Brave-Browser" / "NativeMessagingHosts" / f"{HOST_NAME}.json"),
                ("edge", cfg / "microsoft-edge" / "NativeMessagingHosts" / f"{HOST_NAME}.json"),
            ]
        )
        return out

    if platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else (home / "AppData" / "Local")
        out.append(("windows", base / "BrowserMCP" / "NativeMessagingHosts" / f"{HOST_NAME}.json"))
        return out

    return out


def _file_group_writable(path: Path) -> bool:
    if os.name == "nt":
        return False
    try:
        mode = path.stat().st_mode
    except Exception:
        return False
    return (mode & 0o020) != 0


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def collect_extension_health(
    *,
    root: Path | None = None,
    platform: str | None = None,
    home: Path | None = None,
    include_profiles: bool = False,
) -> dict[str, Any]:
    """Return a low-noise diagnostic bundle for portless extension mode."""

    root = root or _repo_root()
    platform = platform or sys.platform
    home = home or Path.home()

    expected_id, expected_err = _expected_extension_id(root)
    wrapper = _wrapper_path(root, platform=platform)

    wrapper_exists = wrapper.exists()
    wrapper_executable = os.access(wrapper, os.X_OK) if wrapper_exists else False

    origin_expected = f"{_EXT_ORIGIN_PREFIX}{expected_id}/" if expected_id else None

    manifests: list[dict[str, Any]] = []
    any_manifest_exists = False
    any_manifest_ok = False
    any_manifest_allows_expected = False
    any_manifest_bad_perms = False
    first_manifest_path: str | None = None

    for label, manifest_path in _native_host_manifest_candidates(platform=platform, home=home):
        exists = manifest_path.exists()
        any_manifest_exists = any_manifest_exists or exists
        if first_manifest_path is None and exists:
            first_manifest_path = str(manifest_path)

        problems: list[str] = []
        allows_expected = False
        ok = False
        if exists:
            if _file_group_writable(manifest_path):
                any_manifest_bad_perms = True
                problems.append("manifest is group-writable (Chrome will reject native messaging host)")

            data = _load_json(manifest_path)
            if not data:
                problems.append("invalid JSON")
            else:
                if str(data.get("name") or "") != HOST_NAME:
                    problems.append("manifest.name mismatch")
                if str(data.get("type") or "") and str(data.get("type") or "") != "stdio":
                    problems.append("manifest.type mismatch")
                raw_path = str(data.get("path") or "").strip()
                if not raw_path:
                    problems.append("manifest.path missing")
                else:
                    host_path = Path(raw_path)
                    if not host_path.exists():
                        problems.append("native host wrapper not found")
                allowed = data.get("allowed_origins")
                if origin_expected:
                    if isinstance(allowed, list) and origin_expected in [str(x) for x in allowed]:
                        allows_expected = True
                        any_manifest_allows_expected = True
                    else:
                        problems.append("allowed_origins missing expected extension id")
                ok = not problems
                any_manifest_ok = any_manifest_ok or ok

        manifests.append(
            {
                "label": label,
                "path": str(manifest_path),
                "exists": exists,
                "ok": ok,
                "allowsExpectedExtension": allows_expected,
                **({"problems": problems} if problems else {}),
            }
        )

    broker = None
    with contextlib.suppress(Exception):
        broker = discover_best_broker(timeout=0.12)

    broker_info: dict[str, Any] = {
        "runtimeDir": str(runtime_dir()),
        "connected": broker is not None,
        "brokerId": broker.broker_id if broker else None,
        "socketPath": str(broker.socket_path) if broker else None,
        "peerCount": broker.peer_count if broker else 0,
        "brokerStartedAtMs": broker.broker_started_at_ms if broker else 0,
    }

    status = "unknown"
    reason = ""
    hint = ""
    ok = False

    if broker is not None:
        status = "connected"
        reason = "Extension bridge is connected (native broker is reachable)."
        hint = "No action needed."
        ok = True
    elif expected_err:
        status = "repo_misconfigured"
        reason = expected_err
        hint = "Ensure the repo contains vendor/browser_extension/manifest.json with a stable `key`."
    elif not any_manifest_exists:
        status = "native_host_missing"
        reason = "Native Messaging host manifest is not installed for this browser."
        hint = "Start Browser MCP (auto-install) or run ./tools/install_native_host once."
    elif not any_manifest_ok:
        status = "native_host_misconfigured"
        reason = "Native Messaging host manifest exists but is misconfigured."
        if any_manifest_bad_perms:
            hint = "Fix file permissions (must not be group-writable). Re-run ./tools/install_native_host."
        elif not wrapper_exists:
            hint = "Run ./tools/setup (ensures .venv + browser-mcp-native-host wrapper), then re-run ./tools/install_native_host."
        elif origin_expected and not any_manifest_allows_expected:
            hint = "Re-run ./tools/install_native_host to refresh allowed_origins, then reload the extension."
        else:
            hint = "Re-run ./tools/install_native_host, then reload the extension."
    else:
        status = "waiting_for_extension"
        reason = "Native host looks installed, but the extension has not connected yet."
        hint = "Ensure the Browser MCP extension is installed/enabled in your normal Chrome profile; it should auto-connect within ~1 minute."

    out: dict[str, Any] = {
        "ok": ok,
        "summary": {"ok": ok, "status": status, "reason": reason, "hint": hint},
        "extension": {
            "expectedId": expected_id,
            "expectedOrigin": origin_expected,
        },
        "nativeHost": {
            "hostName": HOST_NAME,
            "wrapperPath": str(wrapper),
            "wrapperExists": wrapper_exists,
            "wrapperExecutable": wrapper_executable,
            "firstManifestPath": first_manifest_path,
            "manifests": manifests,
        },
        "broker": broker_info,
    }

    if include_profiles:
        from .native_host_installer import discover_installed_extension_ids  # local import (heavy)

        extra_ids_env = os.environ.get("MCP_EXTENSION_IDS") or os.environ.get("MCP_EXTENSION_ID") or ""
        extra_ids = [s.strip() for s in extra_ids_env.split(",") if s.strip()]
        discovered = discover_installed_extension_ids(root=root, platform=platform, home=home, extra_ids=extra_ids)
        out["profiles"] = {
            "discoveredExtensionIds": discovered,
            "expectedIdFound": bool(expected_id and expected_id in discovered),
        }

    return out


__all__ = ["collect_extension_health"]
