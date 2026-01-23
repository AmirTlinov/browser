from __future__ import annotations

from contextlib import contextmanager

import pytest


def test_flow_final_map_attaches_map_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """flow(final='map') should attach a bounded map snapshot without requiring real Chrome."""
    import mcp_servers.browser.tools as tools
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    session_manager.recover_reset()

    class DummySession:
        tab_id = "tab1"
        tab_url = "about:blank"

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            if "Date.now" in expression:
                return 1_000_000
            return None

        def close(self) -> None:
            return

    @contextmanager
    def fake_shared_session(_cfg: BrowserConfig, timeout: float = 5.0):  # noqa: ARG001
        yield DummySession(), {"id": "tab1", "webSocketDebuggerUrl": "ws://dummy", "url": "about:blank"}

    monkeypatch.setattr(session_manager, "shared_session", fake_shared_session)
    monkeypatch.setattr(session_manager, "ensure_telemetry", lambda _sess: {"enabled": True})
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tab_id: None)
    monkeypatch.setattr(
        session_manager,
        "tier0_snapshot",
        lambda *a, **k: {"cursor": 1_000_000, "summary": {}, "harLite": [], "network": [], "dialogOpen": False},
    )
    session_manager._session_tab_id = "tab1"

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "about:blank", "title": "Dummy", "readyState": "complete"}},
    )

    map_payload = {
        "map": {"page": {"url": "about:blank"}, "summary": {"jsErrors": 1}, "actions": {"items": []}},
        "cursor": 1_000_000,
        "duration_ms": 1,
        "sessionTabId": "tab1",
        "target": "tab1",
    }
    monkeypatch.setattr(tools, "get_page_map", lambda *a, **k: map_payload)

    registry = create_default_registry()

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        if name in {"navigate", "js", "page", "dialog", "click"}:
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"tool": "page", "args": {"info": True}}],
            "final": "map",
            "stop_on_error": True,
            "auto_recover": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("map") == map_payload


def test_run_report_map_includes_map(monkeypatch: pytest.MonkeyPatch) -> None:
    """run(report='map') should surface map under report.map."""
    import mcp_servers.browser.tools as tools
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    session_manager.recover_reset()

    class DummySession:
        tab_id = "tab1"
        tab_url = "about:blank"

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            if "Date.now" in expression:
                return 1_000_000
            return None

        def close(self) -> None:
            return

    @contextmanager
    def fake_shared_session(_cfg: BrowserConfig, timeout: float = 5.0):  # noqa: ARG001
        yield DummySession(), {"id": "tab1", "webSocketDebuggerUrl": "ws://dummy", "url": "about:blank"}

    monkeypatch.setattr(session_manager, "shared_session", fake_shared_session)
    monkeypatch.setattr(session_manager, "ensure_telemetry", lambda _sess: {"enabled": True})
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tab_id: None)
    monkeypatch.setattr(
        session_manager,
        "tier0_snapshot",
        lambda *a, **k: {"cursor": 1_000_000, "summary": {}, "harLite": [], "network": [], "dialogOpen": False},
    )
    session_manager._session_tab_id = "tab1"

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "about:blank", "title": "Dummy", "readyState": "complete"}},
    )

    map_payload = {
        "map": {"page": {"url": "about:blank"}, "summary": {"jsErrors": 1}, "actions": {"items": []}},
        "cursor": 1_000_000,
        "duration_ms": 1,
        "sessionTabId": "tab1",
        "target": "tab1",
    }
    monkeypatch.setattr(tools, "get_page_map", lambda *a, **k: map_payload)

    registry = create_default_registry()

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        if name in {"navigate", "js", "page", "dialog", "click"}:
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("run")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "actions": [{"tool": "page", "args": {"info": True}}],
            "report": "map",
            "auto_recover": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    report = res.data.get("report")
    assert isinstance(report, dict)
    assert report.get("map") == map_payload
