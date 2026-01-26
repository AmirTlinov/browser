from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


def test_download_stores_artifact_and_sha256(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.artifacts import artifact_store
    from mcp_servers.browser.server.handlers import unified as unified_handlers

    cfg = BrowserConfig.from_env()

    # Create a fake repo-like layout so handle_download can resolve repo-relative paths.
    repo = tmp_path / "repo"
    dl_dir = repo / "data" / "downloads" / "tab1"
    dl_dir.mkdir(parents=True, exist_ok=True)
    base_dir = repo / "data" / "artifacts"
    base_dir.mkdir(parents=True, exist_ok=True)

    # Point the global artifact store at our temp base_dir.
    artifact_store.base_dir = base_dir  # type: ignore[assignment]

    content = b"hello download"
    file_path = dl_dir / "file.txt"
    file_path.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()

    def fake_wait_for_download(_cfg: BrowserConfig, **kwargs):  # noqa: ANN001, ARG001
        return {
            "download": {
                "fileName": "file.txt",
                "bytes": len(content),
                "mimeType": "text/plain",
                "path": "data/downloads/tab1/file.txt",
            },
            "target": "tab1",
            "sessionTabId": "tab1",
        }

    monkeypatch.setattr(unified_handlers.tools, "wait_for_download_or_fetch", fake_wait_for_download)

    res = unified_handlers.handle_download(cfg, launcher=None, args={"timeout": 1, "store": True, "sha256": True})
    assert not res.is_error
    assert isinstance(res.data, dict)

    out = res.data
    assert out.get("stored") is True


def test_download_fallback_url_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.session import session_manager
    from mcp_servers.browser.server.artifacts import artifact_store
    from mcp_servers.browser.server.handlers import unified as unified_handlers

    cfg = BrowserConfig.from_env()
    session_manager.set_policy("permissive")
    monkeypatch.setenv("MCP_DOWNLOAD_DIR", str(tmp_path / "downloads"))
    monkeypatch.setattr(session_manager, "_session_tab_id", "tab1")

    base_dir = tmp_path / "artifacts"
    base_dir.mkdir(parents=True, exist_ok=True)
    artifact_store.base_dir = base_dir  # type: ignore[assignment]

    content = b"fallback download"
    expected = hashlib.sha256(content).hexdigest()
    local_file = tmp_path / "fallback.txt"
    local_file.write_bytes(content)
    file_url = f"file://{local_file}"

    from mcp_servers.browser.tools import downloads as downloads_mod

    def fake_wait_for_download(_cfg: BrowserConfig, **kwargs):  # noqa: ANN001, ARG001
        raise unified_handlers.tools.SmartToolError(
            tool="download",
            action="wait",
            reason="Timed out waiting for a new download",
            suggestion="Trigger the download then retry",
        )

    monkeypatch.setattr(downloads_mod, "wait_for_download", fake_wait_for_download)

    res = unified_handlers.handle_download(
        cfg,
        launcher=None,
        args={"timeout": 1, "store": True, "url": file_url, "file_name": "fallback.txt"},
    )
    assert not res.is_error
    out = res.data
    assert isinstance(out, dict)
    download = out.get("download")
    assert isinstance(download, dict)
    assert download.get("fileName") == "fallback.txt"
    assert download.get("fallback") is True
    artifact = out.get("artifact")
    assert isinstance(artifact, dict)

    dl = out.get("download")
    assert isinstance(dl, dict)
    assert "path" not in dl  # must not leak filesystem paths
    assert dl.get("sha256") == expected

    art = out.get("artifact")
    assert isinstance(art, dict)
    assert isinstance(art.get("id"), str) and art["id"]
    assert art.get("sha256") == expected
