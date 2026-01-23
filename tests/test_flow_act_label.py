from __future__ import annotations

from contextlib import contextmanager

import pytest


def test_flow_act_label_resolves_to_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """act(label=...) should resolve deterministically to a concrete tool call."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    session_manager.recover_reset()
    session_manager._session_tab_id = "tab1"
    session_manager.set_affordances(
        "tab1",
        items=[
            {
                "ref": "aff:111",
                "tool": "click",
                "args": {"text": "Save-1", "role": "button"},
                "meta": {"kind": "button", "text": "Save"},
            },
            {
                "ref": "aff:222",
                "tool": "click",
                "args": {"text": "Save-2", "role": "button"},
                "meta": {"kind": "button", "text": "Save"},
            },
        ],
        url="https://example.com/",
        cursor=1_000_000,
    )

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

    # Avoid real CDP calls during final context.
    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "about:blank", "title": "Dummy", "readyState": "complete"}},
    )

    called: list[tuple[str, dict]] = []

    registry = create_default_registry()

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        called.append((name, dict(arguments) if isinstance(arguments, dict) else {}))
        if name in {"click", "page", "dialog", "navigate", "js"}:
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"tool": "act", "args": {"label": "Save", "kind": "button", "index": 1}}],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert called and called[0][0] == "click"
    assert called[0][1].get("text") == "Save-2"


def test_flow_act_label_ambiguous_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """If label matches multiple affordances and index is omitted, act(label) must fail closed."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    session_manager.recover_reset()
    session_manager._session_tab_id = "tab1"
    session_manager.set_affordances(
        "tab1",
        items=[
            {
                "ref": "aff:111",
                "tool": "click",
                "args": {"text": "Save-1", "role": "button"},
                "meta": {"kind": "button", "text": "Save"},
            },
            {
                "ref": "aff:222",
                "tool": "click",
                "args": {"text": "Save-2", "role": "button"},
                "meta": {"kind": "button", "text": "Save"},
            },
        ],
        url="https://example.com/",
        cursor=1_000_000,
    )

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

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "about:blank", "title": "Dummy", "readyState": "complete"}},
    )

    called: list[str] = []

    registry = create_default_registry()

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        called.append(name)
        if name in {"page", "dialog", "navigate", "js"}:
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"tool": "act", "args": {"label": "Save", "kind": "button"}}],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert "click" not in called

    assert isinstance(res.data, dict)
    steps = res.data.get("steps")
    assert isinstance(steps, list) and steps
    assert steps[0].get("ok") is False
    assert "ambiguous" in str(steps[0].get("error", "")).lower()
