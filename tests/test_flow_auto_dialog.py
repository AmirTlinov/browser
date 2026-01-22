from __future__ import annotations

from contextlib import contextmanager

import pytest


def test_flow_auto_dialog_dismiss(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flow should auto-dismiss a blocking JS dialog when configured (run/flow internal)."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    cdp_dialog_calls: list[bool] = []

    class DummySession:
        tab_id = "tab1"
        tab_url = "about:blank"

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001
            if "Date.now" in expression:
                return 1_000_000
            return None

        def send(self, method: str, params=None):  # noqa: ANN001
            if method == "Page.handleJavaScriptDialog":
                cdp_dialog_calls.append(bool((params or {}).get("accept")))
                telemetry.dialog_open = False
                telemetry.dialog_last = None
                return {}
            return {}

    class DummyTelemetry:
        dialog_open = True
        dialog_last = {"type": "alert", "message": "Hi", "url": "https://example.test/"}

    telemetry = DummyTelemetry()

    @contextmanager
    def fake_shared_session(_cfg: BrowserConfig, timeout: float = 5.0):  # noqa: ARG001
        yield DummySession(), {"id": "tab1", "webSocketDebuggerUrl": "ws://dummy", "url": "about:blank"}

    # Keep the test hermetic: no real CDP/Chrome.
    monkeypatch.setattr(session_manager, "shared_session", fake_shared_session)
    monkeypatch.setattr(session_manager, "ensure_telemetry", lambda _sess: {"enabled": True})
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tab_id: telemetry)
    monkeypatch.setattr(session_manager, "_schedule_auto_dialog_handle", lambda *_a, **_k: None)
    session_manager._session_tab_id = "tab1"  # best-effort for code paths that read tab_id

    # Patch "final" probe so flow doesn't try to read a real page.
    from mcp_servers.browser import tools as tools_module

    monkeypatch.setattr(
        tools_module,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "about:blank", "title": "Dummy", "readyState": "complete"}},
    )

    registry = create_default_registry()

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        if name == "page":
            return ToolResult.json({"ok": True})
        raise AssertionError(f"Unexpected dispatch: {name}")

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()

    res = handler(
        cfg,
        launcher=None,  # dispatch is mocked; flow won't use launcher directly in this test
        args={
            "steps": [{"tool": "page", "args": {"detail": "triage"}}],
            "final": "none",
            "auto_dialog": "dismiss",
            "auto_recover": False,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("flow", {}).get("dialogsAutoHandled") == 1
    assert cdp_dialog_calls == [False]
    assert isinstance(res.data.get("steps"), list)
    assert res.data["steps"][0]["ok"] is True


def test_flow_start_at_skips_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    """flow(start_at=N) skips steps < N (used by run(start_at=...))."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    class DummySession:
        tab_id = "tab1"
        tab_url = "about:blank"

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001
            if "Date.now" in expression:
                return 1_000_000
            return None

    @contextmanager
    def fake_shared_session(_cfg: BrowserConfig, timeout: float = 5.0):  # noqa: ARG001
        yield DummySession(), {"id": "tab1", "webSocketDebuggerUrl": "ws://dummy", "url": "about:blank"}

    monkeypatch.setattr(session_manager, "shared_session", fake_shared_session)
    monkeypatch.setattr(session_manager, "ensure_telemetry", lambda _sess: {"enabled": True})
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tab_id: None)
    session_manager._session_tab_id = "tab1"  # best-effort for code paths that read tab_id

    from mcp_servers.browser import tools as tools_module

    monkeypatch.setattr(
        tools_module,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "about:blank", "title": "Dummy", "readyState": "complete"}},
    )

    registry = create_default_registry()
    calls: list[int] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001
        if name == "page":
            calls.append(1)
            return ToolResult.json({"ok": True})
        raise AssertionError(f"Unexpected dispatch: {name}")

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()

    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"tool": "page", "args": {}}, {"tool": "page", "args": {}}],
            "final": "none",
            "start_at": 1,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is True
    assert res.data.get("flow", {}).get("start_at") == 1
    assert calls == [1]


def test_session_manager_auto_dialog_triggers_on_tier0_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-0 dialogOpening event should schedule auto-handling when enabled (run/flow)."""
    from mcp_servers.browser.session import session_manager

    # Keep the test isolated from other runs.
    session_manager.recover_reset()

    calls: list[tuple[str, bool]] = []

    def fake_schedule(tab_id: str, *, accept: bool) -> None:
        calls.append((tab_id, bool(accept)))

    monkeypatch.setattr(session_manager, "_schedule_auto_dialog_handle", fake_schedule)

    session_manager.set_auto_dialog("tab1", "accept", ttl_s=30.0)
    session_manager._ingest_tier0_event(  # type: ignore[attr-defined]
        "tab1",
        {
            "method": "Page.javascriptDialogOpening",
            "params": {"type": "alert", "message": "hi", "url": "https://example.com/"},
        },
    )

    assert calls == [("tab1", True)]
