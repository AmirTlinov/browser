from __future__ import annotations

from contextlib import contextmanager

import pytest


def test_flow_autohandles_dialog_open_between_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    """flow/run should not hang if a dialog opens between steps (setTimeout(alert) race)."""
    import mcp_servers.browser.tools as tools
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    cdp_dialog_calls: list[bool] = []

    class Telemetry:
        dialog_open = False
        dialog_last = None

    t0 = Telemetry()

    class DummyConn:
        def __init__(self) -> None:
            self._open_calls = 0

        def pop_event(self, name: str):  # noqa: ANN001
            if name == "Page.javascriptDialogOpening":
                self._open_calls += 1
                # The second check happens in the post-step guard of the first step.
                if self._open_calls == 2:
                    return {"type": "alert", "message": "hi", "url": "https://example.com/"}
            return None

    class DummySession:
        tab_id = "tab1"
        tab_url = "about:blank"
        conn = DummyConn()

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            if "Date.now" in expression:
                return 1_000_000
            return None

        def send(self, method: str, params=None):  # noqa: ANN001
            if method == "Page.handleJavaScriptDialog":
                cdp_dialog_calls.append(bool((params or {}).get("accept")))
                t0.dialog_open = False
                t0.dialog_last = None
                return {}
            return {}

        def close(self) -> None:
            return

    @contextmanager
    def fake_shared_session(_cfg: BrowserConfig, timeout: float = 5.0):  # noqa: ARG001
        yield DummySession(), {"id": "tab1", "webSocketDebuggerUrl": "ws://dummy", "url": "about:blank"}

    def fake_ingest(tab_id: str, ev: dict):  # noqa: ANN001
        if tab_id != "tab1":
            return
        method = ev.get("method")
        if method == "Page.javascriptDialogOpening":
            t0.dialog_open = True
            t0.dialog_last = ev.get("params")
        if method == "Page.javascriptDialogClosed":
            t0.dialog_open = False
            t0.dialog_last = None

    monkeypatch.setattr(session_manager, "shared_session", fake_shared_session)
    monkeypatch.setattr(session_manager, "ensure_telemetry", lambda _sess: {"enabled": True})
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tab_id: t0)
    monkeypatch.setattr(session_manager, "_ingest_tier0_event", fake_ingest)
    monkeypatch.setattr(session_manager, "_schedule_auto_dialog_handle", lambda *_a, **_k: None)
    session_manager._session_tab_id = "tab1"

    # Avoid touching a real browser for final context.
    monkeypatch.setattr(
        tools, "get_page_info", lambda _cfg: {"pageInfo": {"url": "about:blank", "title": "", "readyState": "complete"}}
    )

    registry = create_default_registry()

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        if name in {"navigate", "js", "page"}:
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {"tool": "navigate", "args": {"url": "https://example.com/"}},
                {"tool": "js", "args": {"code": "setTimeout(() => alert('x'), 0)"}},
                {"tool": "js", "args": {"code": "'after'"}},
                {"tool": "page", "args": {"info": True}},
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_dialog": "accept",
            "auto_recover": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    flow = res.data.get("flow")
    assert isinstance(flow, dict)
    assert flow.get("dialogsAutoHandled") == 1
    assert cdp_dialog_calls == [True]


def test_flow_retries_js_once_when_blocked_by_dialog(monkeypatch: pytest.MonkeyPatch) -> None:
    """When a read-ish step fails due to a dialog block, flow should auto-close + retry once."""
    import mcp_servers.browser.tools as tools
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    cdp_dialog_calls: list[bool] = []

    class DummySession:
        tab_id = "tab1"
        tab_url = "about:blank"

        class DummyConn:
            def pop_event(self, name: str):  # noqa: ANN001
                return None

        conn = DummyConn()

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            if "Date.now" in expression:
                return 1_000_000
            return None

        def send(self, method: str, params=None):  # noqa: ANN001
            if method == "Page.handleJavaScriptDialog":
                cdp_dialog_calls.append(bool((params or {}).get("accept")))
                t0.dialog_open = False
                t0.dialog_last = None
                return {}
            return {}

        def close(self) -> None:
            return

    @contextmanager
    def fake_shared_session(_cfg: BrowserConfig, timeout: float = 5.0):  # noqa: ARG001
        yield DummySession(), {"id": "tab1", "webSocketDebuggerUrl": "ws://dummy", "url": "about:blank"}

    monkeypatch.setattr(session_manager, "shared_session", fake_shared_session)
    monkeypatch.setattr(session_manager, "ensure_telemetry", lambda _sess: {"enabled": True})

    class Telemetry:
        # Start closed: the dialog block happens during the step (simulated by the error string),
        # so pre-step guard should not consume the only auto-handle attempt.
        dialog_open = False
        dialog_last = {"type": "alert", "message": "Hi", "url": "about:blank"}

    t0 = Telemetry()
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tab_id: t0)
    monkeypatch.setattr(session_manager, "_schedule_auto_dialog_handle", lambda *_a, **_k: None)
    session_manager._session_tab_id = "tab1"

    # Avoid touching a real browser for final context.
    monkeypatch.setattr(
        tools, "get_page_info", lambda _cfg: {"pageInfo": {"url": "about:blank", "title": "", "readyState": "complete"}}
    )

    registry = create_default_registry()

    calls: dict[str, int] = {"js": 0}

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        if name == "js":
            calls["js"] += 1
            if calls["js"] == 1:
                return ToolResult.error(
                    "Runtime.evaluate blocked by a JS dialog. Handle it via dialog() and retry.",
                    tool="js",
                )
            return ToolResult.json({"ok": True})
        return ToolResult.json({"ok": True})

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"tool": "js", "args": {"code": "'after'"}}],
            "final": "none",
            "stop_on_error": True,
            "auto_dialog": "accept",
            "auto_recover": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert cdp_dialog_calls == [True]
    assert calls["js"] == 2
