from __future__ import annotations

from contextlib import contextmanager

import pytest


def test_flow_auto_download_after_click(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    """flow(auto_download=true) should capture downloads without an explicit download step."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    monkeypatch.setenv("MCP_DOWNLOAD_DIR", str(tmp_path))

    class DummySession:
        tab_id = "tab1"
        tab_url = "about:blank"

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001, ARG002
            if "Date.now" in expression:
                return 1_000_000
            return None

    @contextmanager
    def fake_shared_session(_cfg: BrowserConfig, timeout: float = 5.0):  # noqa: ARG001
        yield DummySession(), {"id": "tab1", "webSocketDebuggerUrl": "ws://dummy", "url": "about:blank"}

    monkeypatch.setattr(session_manager, "shared_session", fake_shared_session)
    monkeypatch.setattr(session_manager, "ensure_telemetry", lambda _sess: {"enabled": True})
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tab_id: None)
    monkeypatch.setattr(session_manager, "ensure_downloads", lambda _sess: {"enabled": True, "available": True})
    session_manager._session_tab_id = "tab1"  # best-effort for code paths that read tab_id

    registry = create_default_registry()
    real_dispatch = registry.dispatch
    calls: list[str] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001
        calls.append(name)
        if name == "click":
            return ToolResult.json({"ok": True})
        if name == "download":
            return ToolResult.json(
                {
                    "stored": True,
                    "artifact": {"id": "art1", "mimeType": "application/octet-stream", "bytes": 1},
                    "download": {"fileName": "file.bin", "bytes": 1, "mimeType": "application/octet-stream"},
                    "next": ['artifact(action="export", id="art1")'],
                }
            )
        return real_dispatch(name, cfg, launcher, arguments)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()

    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"tool": "click", "args": {"text": "Download"}}],
            "final": "none",
            "auto_download": True,
            "auto_download_timeout": 0.1,
            "auto_recover": False,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    steps = res.data.get("steps")
    assert isinstance(steps, list) and steps
    assert steps[0].get("ok") is True
    assert isinstance(steps[0].get("download"), dict)
    assert "download" in calls
