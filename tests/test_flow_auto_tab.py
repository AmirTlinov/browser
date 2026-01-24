from __future__ import annotations

from contextlib import contextmanager

import pytest


def test_flow_auto_tab_switches_to_new_tab(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    session_manager.recover_reset()
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

    tabs_call = {"n": 0}

    def fake_list_tabs(_cfg: BrowserConfig):  # noqa: ANN001
        tabs_call["n"] += 1
        if tabs_call["n"] == 1:
            return [{"id": "tab1", "url": "https://a", "title": "A", "current": True}]
        return [
            {"id": "tab1", "url": "https://a", "title": "A", "current": True},
            {"id": "tab2", "url": "https://b", "title": "B", "current": False},
        ]

    switched: list[str] = []

    def fake_switch_tab(_cfg: BrowserConfig, tab_id: str):  # noqa: ANN001
        switched.append(tab_id)
        return True

    monkeypatch.setattr(session_manager, "list_tabs", fake_list_tabs)
    monkeypatch.setattr(session_manager, "switch_tab", fake_switch_tab)

    registry = create_default_registry()

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        if name == "click":
            return ToolResult.json({"ok": True})
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
            "steps": [{"click": {"text": "Open"}, "auto_tab": True}],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert switched == ["tab2"]
