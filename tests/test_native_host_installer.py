from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _prefs_path(home: Path, platform: str) -> Path:
    if platform == "darwin":
        base = home / "Library" / "Application Support" / "Google" / "Chrome"
    elif platform.startswith("linux"):
        base = home / ".config" / "google-chrome"
    else:
        base = home / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
    return base / "Default" / "Preferences"


def test_discover_installed_extension_ids_by_path(tmp_path: Path) -> None:
    from mcp_servers.browser.native_host_installer import discover_installed_extension_ids

    platform = sys.platform
    repo_root = tmp_path / "repo"
    ext_dir = repo_root / "vendor" / "browser_extension"
    ext_dir.mkdir(parents=True)
    (ext_dir / "manifest.json").write_text(
        json.dumps({"name": "Browser Extension", "description": "Local web-access bridge for MCP without IDE."}),
        encoding="utf-8",
    )

    home = tmp_path / "home"
    pref_path = _prefs_path(home, platform)
    pref_path.parent.mkdir(parents=True, exist_ok=True)
    ext_id = "a" * 32
    pref_path.write_text(
        json.dumps({"extensions": {"settings": {ext_id: {"path": str(ext_dir)}}}}),
        encoding="utf-8",
    )

    discovered = discover_installed_extension_ids(root=repo_root, platform=platform, home=home)
    assert ext_id in discovered


def test_write_manifest_permissions(tmp_path: Path) -> None:
    if os.name == "nt":
        return

    from mcp_servers.browser.native_host_installer import _write_manifest

    manifest_path = tmp_path / "host.json"
    _write_manifest(manifest_path, {"name": "test", "type": "stdio"})
    mode = manifest_path.stat().st_mode & 0o777
    assert mode == 0o644
