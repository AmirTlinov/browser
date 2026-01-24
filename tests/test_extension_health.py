from __future__ import annotations

import base64
import json
import os
from pathlib import Path


def _write_extension_manifest(root: Path) -> None:
    ext_dir = root / "vendor" / "browser_extension"
    ext_dir.mkdir(parents=True, exist_ok=True)
    key = base64.b64encode(b"testkey").decode("ascii")
    (ext_dir / "manifest.json").write_text(json.dumps({"name": "Browser Extension", "key": key}), encoding="utf-8")


def _write_wrapper(root: Path, *, platform: str) -> Path:
    if platform == "win32":
        wrapper = root / ".venv" / "Scripts" / "browser-mcp-native-host.cmd"
    else:
        wrapper = root / ".venv" / "bin" / "browser-mcp-native-host"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    if os.name != "nt":
        wrapper.chmod(0o755)
    return wrapper


def test_extension_health_native_host_missing(monkeypatch, tmp_path: Path) -> None:
    from mcp_servers.browser.extension_health import collect_extension_health

    platform = "linux"
    root = tmp_path / "repo"
    home = tmp_path / "home"
    _write_extension_manifest(root)

    monkeypatch.setenv("MCP_NATIVE_BROKER_DIR", str(tmp_path / "runtime"))

    health = collect_extension_health(root=root, platform=platform, home=home, include_profiles=False)
    assert health["summary"]["status"] == "native_host_missing"
    assert health["ok"] is False


def test_extension_health_waiting_for_extension(monkeypatch, tmp_path: Path) -> None:
    from mcp_servers.browser.extension_health import collect_extension_health
    from mcp_servers.browser.native_host_installer import HOST_NAME

    platform = "linux"
    root = tmp_path / "repo"
    home = tmp_path / "home"
    _write_extension_manifest(root)
    wrapper = _write_wrapper(root, platform=platform)

    monkeypatch.setenv("MCP_NATIVE_BROKER_DIR", str(tmp_path / "runtime"))

    expected_id = collect_extension_health(root=root, platform=platform, home=home)["extension"]["expectedId"]
    origin = f"chrome-extension://{expected_id}/"

    manifest_path = home / ".config" / "google-chrome" / "NativeMessagingHosts" / f"{HOST_NAME}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"name": HOST_NAME, "type": "stdio", "path": str(wrapper), "allowed_origins": [origin]}),
        encoding="utf-8",
    )
    if os.name != "nt":
        manifest_path.chmod(0o644)

    health = collect_extension_health(root=root, platform=platform, home=home, include_profiles=False)
    assert health["summary"]["status"] == "waiting_for_extension"
    assert health["ok"] is False


def test_extension_health_group_writable_manifest(monkeypatch, tmp_path: Path) -> None:
    if os.name == "nt":
        return

    from mcp_servers.browser.extension_health import collect_extension_health
    from mcp_servers.browser.native_host_installer import HOST_NAME

    platform = "linux"
    root = tmp_path / "repo"
    home = tmp_path / "home"
    _write_extension_manifest(root)
    wrapper = _write_wrapper(root, platform=platform)

    monkeypatch.setenv("MCP_NATIVE_BROKER_DIR", str(tmp_path / "runtime"))

    expected_id = collect_extension_health(root=root, platform=platform, home=home)["extension"]["expectedId"]
    origin = f"chrome-extension://{expected_id}/"

    manifest_path = home / ".config" / "google-chrome" / "NativeMessagingHosts" / f"{HOST_NAME}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"name": HOST_NAME, "type": "stdio", "path": str(wrapper), "allowed_origins": [origin]}),
        encoding="utf-8",
    )
    manifest_path.chmod(0o664)

    health = collect_extension_health(root=root, platform=platform, home=home, include_profiles=False)
    assert health["summary"]["status"] == "native_host_misconfigured"
