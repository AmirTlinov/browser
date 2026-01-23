from __future__ import annotations

from contextlib import contextmanager

import pytest


def test_flow_interpolates_mem_placeholder_without_leaking(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    session_manager.recover_reset()
    session_manager.set_policy("permissive")
    session_manager.memory_set(key="token", value="secret")
    session_manager._session_tab_id = "tab1"

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

    called: list[tuple[str, dict]] = []

    registry = create_default_registry()

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        called.append((name, dict(arguments) if isinstance(arguments, dict) else {}))
        return ToolResult.json({"ok": True})

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {"tool": "type", "args": {"selector": "#pwd", "text": "{{mem:token}}", "clear": True}},
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert called
    assert called[0][0] == "type"
    assert called[0][1].get("text") == "secret"

    # Step note must not leak secrets; type() note only includes text_len.
    assert isinstance(res.data, dict)
    steps = res.data.get("steps")
    assert isinstance(steps, list) and steps
    note = steps[0].get("note")
    assert isinstance(note, str)
    assert "secret" not in note


def test_flow_missing_mem_key_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.session import session_manager

    session_manager.recover_reset()
    session_manager.set_policy("permissive")
    session_manager._session_tab_id = "tab1"

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

    registry = create_default_registry()
    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {"tool": "type", "args": {"selector": "#pwd", "text": "{{mem:missing}}", "clear": True}},
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    steps = res.data.get("steps")
    assert isinstance(steps, list) and steps
    assert steps[0].get("ok") is False
    assert "memory" in str(steps[0].get("error", "")).lower()
