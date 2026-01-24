from __future__ import annotations


def test_runtime_dir_infers_run_user(monkeypatch, tmp_path) -> None:
    from mcp_servers.browser import native_broker_paths

    # Force env path to be unset so we hit the inference path.
    monkeypatch.delenv("MCP_NATIVE_BROKER_DIR", raising=False)
    monkeypatch.delenv("MCP_NATIVE_HOST_DIR", raising=False)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

    monkeypatch.setattr(native_broker_paths, "_infer_xdg_runtime_dir", lambda _uid: tmp_path)

    p = native_broker_paths.runtime_dir()
    assert p.exists()
    assert p.name == "browser-mcp"
