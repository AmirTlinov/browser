from __future__ import annotations

from contextlib import contextmanager

import pytest


def test_flow_act_refreshes_on_url_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
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
                "ref": "aff:old",
                "tool": "click",
                "args": {"text": "Save-old", "role": "button"},
                "meta": {"kind": "button", "text": "Save"},
            }
        ],
        url="https://old.example/",
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
        lambda _cfg: {
            "pageInfo": {"url": "https://new.example/", "title": "Dummy", "readyState": "complete"}
        },
    )

    refreshed = {"called": False}

    def fake_get_page_locators(_cfg, kind="all", offset=0, limit=80):  # noqa: ANN001
        refreshed["called"] = True
        session_manager.set_affordances(
            "tab1",
            items=[
                {
                    "ref": "aff:new",
                    "tool": "click",
                    "args": {"text": "Save-new", "role": "button"},
                    "meta": {"kind": "button", "text": "Save"},
                }
            ],
            url="https://new.example/",
            cursor=2_000_000,
        )
        return {"locators": {"items": []}}

    monkeypatch.setattr(tools, "get_page_locators", fake_get_page_locators)

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
            "steps": [{"tool": "act", "args": {"label": "Save", "kind": "button"}}],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "auto_affordances": True,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert refreshed["called"] is True
    assert any(name == "click" and args.get("text") == "Save-new" for name, args in called)
