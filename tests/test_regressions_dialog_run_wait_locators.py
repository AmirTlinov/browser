from __future__ import annotations

import time
from contextlib import contextmanager

import pytest


def test_dialog_closes_when_telemetry_says_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """dialog() should return handled=true when a dialog is open and clear local dialog state."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.session import session_manager
    from mcp_servers.browser.tools import dialog as dialog_tool

    class DummySession:
        tab_id = "tab1"

        def send(self, method: str, params=None):  # noqa: ANN001
            if method == "Page.handleJavaScriptDialog":
                return {}
            return {}

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            return None

    telemetry = type(
        "T0",
        (),
        {
            "dialog_open": True,
            "dialog_last": {"type": "alert", "message": "hi", "url": "https://example.com/"},
        },
    )()

    closed: list[tuple[str, bool | None, str | None]] = []

    def note_closed(tab_id: str, *, accepted=None, user_input=None):  # noqa: ANN001
        closed.append((tab_id, accepted, user_input))

    @contextmanager
    def fake_get_session(_cfg: BrowserConfig, timeout: float = 5.0, **kwargs):  # noqa: ARG001
        yield DummySession(), {"id": "tab1"}

    monkeypatch.setattr(dialog_tool, "get_session", fake_get_session)
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tid: telemetry)
    monkeypatch.setattr(session_manager, "note_dialog_closed", note_closed)

    cfg = BrowserConfig.from_env()
    res = dialog_tool.handle_dialog(cfg, accept=True, prompt_text=None, timeout=0.0)
    assert res.get("handled") is True
    assert closed and closed[0][0] == "tab1"


def test_dialog_clears_stale_open_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """If telemetry says dialogOpen but CDP says no dialog, dialog() should clear stale state."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.session import session_manager
    from mcp_servers.browser.tools import dialog as dialog_tool

    class DummySession:
        tab_id = "tab1"

        def send(self, method: str, params=None):  # noqa: ANN001
            if method == "Page.handleJavaScriptDialog":
                raise Exception("No dialog is showing")
            return {}

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            return None

    telemetry = type(
        "T0",
        (),
        {
            "dialog_open": True,
            "dialog_last": {"type": "confirm", "message": "stale", "url": "https://example.com/"},
        },
    )()

    cleared: list[str] = []

    def note_closed(tab_id: str, *, accepted=None, user_input=None):  # noqa: ANN001,ARG001
        cleared.append(tab_id)

    @contextmanager
    def fake_get_session(_cfg: BrowserConfig, timeout: float = 5.0, **kwargs):  # noqa: ARG001
        yield DummySession(), {"id": "tab1"}

    monkeypatch.setattr(dialog_tool, "get_session", fake_get_session)
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tid: telemetry)
    monkeypatch.setattr(session_manager, "note_dialog_closed", note_closed)

    cfg = BrowserConfig.from_env()
    res = dialog_tool.handle_dialog(cfg, accept=False, prompt_text=None, timeout=0.0)
    assert res.get("handled") is True
    assert res.get("staleStateCleared") is True
    assert cleared == ["tab1"]


def test_dialog_returns_runtime_ok_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """dialog() should surface a tiny runtimeOk bit for cross-call autonomy."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.session import session_manager
    from mcp_servers.browser.tools import dialog as dialog_tool

    class DummySession:
        tab_id = "tab1"

        def send(self, method: str, params=None):  # noqa: ANN001
            if method == "Page.handleJavaScriptDialog":
                return {}
            if method == "Page.getNavigationHistory":
                return {"currentIndex": 0, "entries": [{"url": "https://example.com/"}]}
            return {}

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            return 1 if expression == "1" else None

    telemetry = type(
        "T0",
        (),
        {
            "dialog_open": True,
            "dialog_last": {"type": "alert", "message": "hi", "url": "https://example.com/"},
        },
    )()

    @contextmanager
    def fake_get_session(_cfg: BrowserConfig, timeout: float = 5.0, **kwargs):  # noqa: ARG001
        yield DummySession(), {"id": "tab1"}

    monkeypatch.setattr(dialog_tool, "get_session", fake_get_session)
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tid: telemetry)
    monkeypatch.setattr(session_manager, "note_dialog_closed", lambda *a, **k: None)

    cfg = BrowserConfig.from_env()
    res = dialog_tool.handle_dialog(cfg, accept=True, prompt_text=None, timeout=0.0)
    assert res.get("handled") is True
    assert res.get("runtimeOk") is True


def test_dialog_soft_recovers_when_next_call_is_bricked(monkeypatch: pytest.MonkeyPatch) -> None:
    """dialog() should soft-recover (new tab) if post-close CDP health checks time out."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.http_client import HttpClientError
    from mcp_servers.browser.session import session_manager
    from mcp_servers.browser.tools import dialog as dialog_tool

    class Telemetry:
        dialog_open = True
        dialog_last = {"type": "alert", "message": "hi", "url": "https://example.com/"}

    t0 = Telemetry()

    class DummySession1:
        tab_id = "tab1"

        def send(self, method: str, params=None):  # noqa: ANN001,ARG002
            if method == "Page.handleJavaScriptDialog":
                return {}
            if method == "Page.getNavigationHistory":
                # Simulate the real-world failure mode: dialog closed, but the tab is now bricked.
                raise HttpClientError("CDP response timed out")
            return {}

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            return None

    class DummySession2:
        tab_id = "tab1"

        def send(self, method: str, params=None):  # noqa: ANN001,ARG002
            return {}

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            return None

    class DummySession3:
        tab_id = "tab2"

        def send(self, method: str, params=None):  # noqa: ANN001,ARG002
            return {}

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            return 1 if expression == "1" else None

    sessions = [DummySession1(), DummySession2(), DummySession3()]

    @contextmanager
    def fake_get_session(_cfg: BrowserConfig, timeout: float = 5.0, **kwargs):  # noqa: ARG001
        if not sessions:
            raise AssertionError("Unexpected extra get_session() call")
        sess = sessions.pop(0)
        yield sess, {"id": sess.tab_id}

    monkeypatch.setattr(dialog_tool, "get_session", fake_get_session)
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tid: t0)
    monkeypatch.setattr(session_manager, "note_dialog_closed", lambda *a, **k: None)

    recover_reset_calls: list[dict] = []
    close_calls: list[str] = []
    new_tab_calls: list[str] = []

    def fake_recover_reset():  # noqa: ANN001
        rec = {"reset": True}
        recover_reset_calls.append(rec)
        return rec

    def fake_close_tab(_cfg: BrowserConfig, tab_id: str | None = None) -> bool:  # noqa: ANN001
        close_calls.append(str(tab_id or ""))
        return True

    def fake_new_tab(_cfg: BrowserConfig, url: str = "about:blank") -> str:  # noqa: ANN001
        new_tab_calls.append(url)
        return "tab2"

    monkeypatch.setattr(session_manager, "recover_reset", fake_recover_reset)
    monkeypatch.setattr(session_manager, "close_tab", fake_close_tab)
    monkeypatch.setattr(session_manager, "new_tab", fake_new_tab)

    cfg = BrowserConfig.from_env()
    res = dialog_tool.handle_dialog(cfg, accept=True, prompt_text=None, timeout=0.0)

    assert res.get("handled") is True
    recovered = res.get("recovered")
    assert isinstance(recovered, dict) and recovered.get("mode") == "soft"
    assert recovered.get("sessionTabId") == "tab2"
    assert isinstance(recovered.get("reset"), dict)
    assert recover_reset_calls
    assert close_calls == ["tab1"]
    assert new_tab_calls


def test_wait_navigation_uses_cdp_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """wait(for=navigation) should succeed when a top-frame navigation event commits."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.session import session_manager
    from mcp_servers.browser.tools.page import wait as wait_tool

    class DummyConn:
        def pop_event(self, name: str):  # noqa: ANN001
            return None

        def wait_for_event(self, name: str, timeout: float = 10.0):  # noqa: ANN001
            if name == "Page.frameNavigated":
                return {"frame": {"url": "https://example.com/", "parentId": None}}
            return None

    class DummySession:
        tab_id = "tab1"
        conn = DummyConn()

        def send(self, method: str, params=None):  # noqa: ANN001
            if method == "Page.getNavigationHistory":
                return {"currentIndex": 0, "entries": [{"url": "https://old.example/"}]}
            return {}

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            return None

    @contextmanager
    def fake_get_session(_cfg: BrowserConfig, timeout: float = 5.0, **kwargs):  # noqa: ARG001
        yield DummySession(), {"id": "tab1"}

    monkeypatch.setattr(wait_tool, "get_session", fake_get_session)
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tid: None)
    session_manager._session_tab_id = "tab1"

    cfg = BrowserConfig.from_env()
    res = wait_tool.wait_for(cfg, condition="navigation", timeout=1.0)
    assert res.get("success") is True
    assert res.get("new_url") == "https://example.com/"


def test_wait_navigation_detects_commit_via_loader_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """wait(for=navigation) should detect a real commit via top-frame loaderId change."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.session import session_manager
    from mcp_servers.browser.tools.page import wait as wait_tool

    class DummyConn:
        def pop_event(self, name: str):  # noqa: ANN001
            return None

        def wait_for_event(self, name: str, timeout: float = 10.0):  # noqa: ANN001,ARG002
            return None

    class DummySession:
        tab_id = "tab1"
        conn = DummyConn()

        def __init__(self) -> None:
            self._tree_calls = 0

        def send(self, method: str, params=None):  # noqa: ANN001,ARG002
            if method == "Page.getNavigationHistory":
                return {"currentIndex": 0, "entries": [{"url": "https://example.com/"}]}
            if method == "Page.getFrameTree":
                self._tree_calls += 1
                lid = "l1" if self._tree_calls == 1 else "l2"
                return {"frameTree": {"frame": {"url": "https://example.com/", "loaderId": lid}}}
            return {}

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            return None

    @contextmanager
    def fake_get_session(_cfg: BrowserConfig, timeout: float = 5.0, **kwargs):  # noqa: ARG001
        yield DummySession(), {"id": "tab1"}

    monkeypatch.setattr(wait_tool, "get_session", fake_get_session)
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tid: None)
    session_manager._session_tab_id = "tab1"

    cfg = BrowserConfig.from_env()
    res = wait_tool.wait_for(cfg, condition="navigation", timeout=0.5)
    assert res.get("success") is True
    assert "loader" in str(res.get("note", "")).lower()


def test_wait_navigation_uses_tier0_events_for_race(monkeypatch: pytest.MonkeyPatch) -> None:
    """wait(for=navigation) should succeed even if URL already changed, using tier0 nav events."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.session import session_manager
    from mcp_servers.browser.tools.page import wait as wait_tool

    class DummyConn:
        def pop_event(self, name: str):  # noqa: ANN001
            return None

        def wait_for_event(self, name: str, timeout: float = 10.0):  # noqa: ANN001,ARG002
            return None

    class DummySession:
        tab_id = "tab1"
        conn = DummyConn()

        def send(self, method: str, params=None):  # noqa: ANN001,ARG002
            if method == "Page.getNavigationHistory":
                return {"currentIndex": 0, "entries": [{"url": "https://example.com/new"}]}
            return {}

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            return None

    @contextmanager
    def fake_get_session(_cfg: BrowserConfig, timeout: float = 5.0, **kwargs):  # noqa: ARG001
        yield DummySession(), {"id": "tab1"}

    monkeypatch.setattr(wait_tool, "get_session", fake_get_session)
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tid: None)
    monkeypatch.setattr(
        session_manager,
        "tier0_snapshot",
        lambda *a, **k: {
            "navigation": [{"ts": int(time.time() * 1000), "url": "https://example.com/new", "kind": "frame"}]
        },
    )
    session_manager._session_tab_id = "tab1"

    cfg = BrowserConfig.from_env()
    res = wait_tool.wait_for(cfg, condition="navigation", timeout=0.5)
    assert res.get("success") is True
    assert res.get("new_url") == "https://example.com/new"
    assert "tier0" in str(res.get("note", "")).lower()


def test_locators_available_on_regular_https_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """page(detail=locators) should return a Tier-0 map on https pages even if injection is unavailable."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.session import session_manager
    from mcp_servers.browser.tools.page import locators as locators_tool

    class DummySession:
        tab_id = "tab1"

        def send(self, method: str, params=None):  # noqa: ANN001
            if method == "Accessibility.getFullAXTree":
                return {
                    "nodes": [
                        {
                            "ignored": False,
                            "role": {"value": "button"},
                            "name": {"value": "More information..."},
                            "backendDOMNodeId": 123,
                            "properties": [{"name": "focusable", "value": {"value": True}}],
                        }
                    ]
                }
            if method == "Page.getNavigationHistory":
                return {"currentIndex": 0, "entries": [{"url": "https://example.com/"}]}
            return {}

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            # Pretend Tier-1 injection isn't available.
            return None

    @contextmanager
    def fake_get_session(_cfg: BrowserConfig, timeout: float = 5.0, **kwargs):  # noqa: ARG001
        yield DummySession(), {"id": "tab1"}

    monkeypatch.setattr(locators_tool, "get_session", fake_get_session)
    monkeypatch.setattr(session_manager, "ensure_telemetry", lambda _sess: {"enabled": True})
    monkeypatch.setattr(session_manager, "tier0_snapshot", lambda *a, **k: {"dialogOpen": False})
    monkeypatch.setattr(session_manager, "ensure_diagnostics", lambda _sess: {"enabled": True, "available": False})
    monkeypatch.setattr(session_manager, "set_affordances", lambda *a, **k: None)
    session_manager._session_tab_id = "tab1"

    cfg = BrowserConfig.from_env()
    res = locators_tool.get_page_locators(cfg, kind="all", offset=0, limit=20)
    locs = res.get("locators")
    assert isinstance(locs, dict)
    assert locs.get("tier") == "tier0"
    items = locs.get("items")
    assert isinstance(items, list) and items


def test_flow_watchdog_action_timeout_does_not_hang(monkeypatch: pytest.MonkeyPatch) -> None:
    """flow should return promptly if a step dispatch hangs (watchdog)."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    class DummySession:
        tab_id = "tab1"
        tab_url = "about:blank"

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            if "Date.now" in expression:
                return 1_000_000
            return None

    @contextmanager
    def fake_shared_session(_cfg: BrowserConfig, timeout: float = 5.0):  # noqa: ARG001
        yield DummySession(), {"id": "tab1", "webSocketDebuggerUrl": "ws://dummy", "url": "about:blank"}

    monkeypatch.setattr(session_manager, "shared_session", fake_shared_session)
    monkeypatch.setattr(session_manager, "ensure_telemetry", lambda _sess: {"enabled": True})
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tab_id: None)
    session_manager._session_tab_id = "tab1"

    registry = create_default_registry()

    def slow_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001
        if name == "page":
            time.sleep(1.0)
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", slow_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,  # dispatch is mocked
        args={
            "steps": [{"tool": "page", "args": {"detail": "triage"}}],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "action_timeout": 0.2,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    steps = res.data.get("steps")
    assert isinstance(steps, list) and steps
    assert steps[0].get("ok") is False
    assert "timed out" in str(steps[0].get("error", "")).lower()


def test_dialog_soft_recovers_when_post_handle_cdp_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """dialog() should attempt a soft heal if the tab becomes a CDP brick right after handling."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.session import session_manager
    from mcp_servers.browser.tools import dialog as dialog_tool

    class DummySession:
        tab_id = "tab1"

        def send(self, method: str, params=None):  # noqa: ANN001
            if method == "Page.handleJavaScriptDialog":
                return {}
            if method == "Page.getNavigationHistory":
                raise Exception("CDP response timed out")
            return {}

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            return None

    telemetry = type(
        "T0",
        (),
        {
            "dialog_open": True,
            "dialog_last": {"type": "alert", "message": "hi", "url": "https://example.com/"},
        },
    )()

    recovered: list[tuple[str, str]] = []

    def fake_close_tab(_cfg: BrowserConfig, tab_id: str | None = None) -> bool:  # noqa: ARG001
        recovered.append(("close", str(tab_id)))
        return True

    def fake_new_tab(_cfg: BrowserConfig, url: str = "about:blank") -> str:  # noqa: ARG001
        recovered.append(("new", url))
        return "tab2"

    @contextmanager
    def fake_get_session(_cfg: BrowserConfig, timeout: float = 5.0, **kwargs):  # noqa: ARG001
        yield DummySession(), {"id": "tab1"}

    monkeypatch.setattr(dialog_tool, "get_session", fake_get_session)
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tid: telemetry)
    monkeypatch.setattr(session_manager, "close_tab", fake_close_tab)
    monkeypatch.setattr(session_manager, "new_tab", fake_new_tab)

    cfg = BrowserConfig.from_env()
    res = dialog_tool.handle_dialog(cfg, accept=True, prompt_text=None, timeout=0.0)
    assert res.get("handled") is True
    rec = res.get("recovered")
    assert isinstance(rec, dict)
    assert rec.get("ok") is True
    assert rec.get("mode") == "soft"
    assert rec.get("sessionTabId") == "tab2"
    assert ("close", "tab1") in recovered
    assert ("new", "https://example.com/") in recovered


def test_dialog_stale_state_still_recovers_on_cdp_brick(monkeypatch: pytest.MonkeyPatch) -> None:
    """dialog() should still recover when the dialog is already gone but CDP is bricked."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.session import session_manager
    from mcp_servers.browser.tools import dialog as dialog_tool

    class DummySession:
        tab_id = "tab1"

        def send(self, method: str, params=None):  # noqa: ANN001
            if method == "Page.handleJavaScriptDialog":
                raise Exception("No dialog is showing")
            if method == "Page.getNavigationHistory":
                raise Exception("CDP response timed out")
            return {}

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            return None

    telemetry = type(
        "T0",
        (),
        {
            "dialog_open": True,
            "dialog_last": {"type": "alert", "message": "hi", "url": "https://example.com/"},
        },
    )()

    recovered: list[tuple[str, str]] = []

    def fake_close_tab(_cfg: BrowserConfig, tab_id: str | None = None) -> bool:  # noqa: ARG001
        recovered.append(("close", str(tab_id)))
        return True

    def fake_new_tab(_cfg: BrowserConfig, url: str = "about:blank") -> str:  # noqa: ARG001
        recovered.append(("new", url))
        return "tab2"

    @contextmanager
    def fake_get_session(_cfg: BrowserConfig, timeout: float = 5.0, **kwargs):  # noqa: ARG001
        yield DummySession(), {"id": "tab1"}

    monkeypatch.setattr(dialog_tool, "get_session", fake_get_session)
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tid: telemetry)
    monkeypatch.setattr(session_manager, "close_tab", fake_close_tab)
    monkeypatch.setattr(session_manager, "new_tab", fake_new_tab)

    cfg = BrowserConfig.from_env()
    res = dialog_tool.handle_dialog(cfg, accept=True, prompt_text=None, timeout=0.0)
    assert res.get("handled") is True
    assert res.get("staleStateCleared") is True
    rec = res.get("recovered")
    assert isinstance(rec, dict)
    assert rec.get("ok") is True
    assert rec.get("mode") == "soft"
    assert rec.get("sessionTabId") == "tab2"
    assert ("close", "tab1") in recovered
    assert ("new", "https://example.com/") in recovered


def test_dialog_soft_recovers_when_runtime_eval_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """dialog() should soft heal when Runtime stays bricked after handling the dialog."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.session import session_manager
    from mcp_servers.browser.tools import dialog as dialog_tool

    class DummySession:
        tab_id = "tab1"

        def send(self, method: str, params=None):  # noqa: ANN001
            if method == "Page.handleJavaScriptDialog":
                return {}
            if method == "Page.getNavigationHistory":
                return {"currentIndex": 0, "entries": [{"url": "https://example.com/"}]}
            return {}

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            if expression == "1":
                raise Exception("CDP response timed out")
            return None

    telemetry = type(
        "T0",
        (),
        {
            "dialog_open": True,
            "dialog_last": {"type": "alert", "message": "hi", "url": "https://example.com/"},
        },
    )()

    recovered: list[tuple[str, str]] = []

    def fake_close_tab(_cfg: BrowserConfig, tab_id: str | None = None) -> bool:  # noqa: ARG001
        recovered.append(("close", str(tab_id)))
        return True

    def fake_new_tab(_cfg: BrowserConfig, url: str = "about:blank") -> str:  # noqa: ARG001
        recovered.append(("new", url))
        return "tab2"

    @contextmanager
    def fake_get_session(_cfg: BrowserConfig, timeout: float = 5.0, **kwargs):  # noqa: ARG001
        yield DummySession(), {"id": "tab1"}

    monkeypatch.setattr(dialog_tool, "get_session", fake_get_session)
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tid: telemetry)
    monkeypatch.setattr(session_manager, "close_tab", fake_close_tab)
    monkeypatch.setattr(session_manager, "new_tab", fake_new_tab)

    cfg = BrowserConfig.from_env()
    res = dialog_tool.handle_dialog(cfg, accept=True, prompt_text=None, timeout=0.0)
    assert res.get("handled") is True
    rec = res.get("recovered")
    assert isinstance(rec, dict)
    assert rec.get("ok") is True
    assert rec.get("mode") == "soft"
    assert rec.get("sessionTabId") == "tab2"
    assert ("close", "tab1") in recovered
    assert ("new", "https://example.com/") in recovered
