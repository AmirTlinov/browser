from __future__ import annotations

from contextlib import contextmanager

import pytest


def test_page_locators_with_screenshot_adds_overlay_boxes(monkeypatch: pytest.MonkeyPatch) -> None:
    """page(detail='locators', with_screenshot=true) should produce overlay boxes even without bounds in items."""
    import mcp_servers.browser.tools as tools
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.handlers import unified as unified_handler
    from mcp_servers.browser.session import session_manager

    cfg = BrowserConfig.from_env()

    class DummySession:
        tab_id = "tab1"
        tab_url = "https://example.com/"

        def send(self, method: str, params=None):  # noqa: ANN001
            if method == "DOM.enable":
                return {}
            if method == "DOM.getBoxModel":
                return {"model": {"border": [10, 10, 110, 10, 110, 60, 10, 60]}}
            return {}

        def close(self) -> None:
            return

    @contextmanager
    def fake_shared_session(_cfg: BrowserConfig, timeout: float = 5.0):  # noqa: ARG001
        yield DummySession(), {"id": "tab1", "webSocketDebuggerUrl": "ws://dummy", "url": "https://example.com/"}

    @contextmanager
    def fake_get_session(_cfg: BrowserConfig, timeout: float = 5.0, **kwargs):  # noqa: ARG001
        yield DummySession(), {"id": "tab1"}

    session_manager.recover_reset()
    session_manager._session_tab_id = "tab1"

    monkeypatch.setattr(session_manager, "shared_session", fake_shared_session)
    monkeypatch.setattr(tools, "get_session", fake_get_session)
    monkeypatch.setattr(tools, "eval_js", lambda *_a, **_k: {"result": True, "target": "tab1"})
    monkeypatch.setattr(tools, "screenshot", lambda *_a, **_k: {"content_b64": "AAAA"})
    monkeypatch.setattr(
        tools,
        "get_page_locators",
        lambda *_a, **_k: {
            "locators": {
                "tier": "tier0",
                "items": [
                    {
                        "kind": "button",
                        "label": "More information...",
                        "ref": "dom:123",
                        "backendDOMNodeId": 123,
                    }
                ],
            }
        },
    )

    captured: dict[str, object] = {}

    def capture_render(payload):  # noqa: ANN001
        captured["payload"] = payload
        return "[CONTENT]\nok: true"

    monkeypatch.setattr("mcp_servers.browser.server.ai_format.render_ctx_markdown", capture_render)

    res = unified_handler.handle_page(
        cfg,
        launcher=None,  # not used by handler
        args={"detail": "locators", "with_screenshot": True, "overlay": True, "overlay_limit": 5},
    )

    assert not res.is_error
    assert res.content and len(res.content) >= 2

    payload = captured.get("payload")
    assert isinstance(payload, dict)
    overlay = payload.get("overlay")
    assert isinstance(overlay, dict)
    assert overlay.get("count", 0) > 0

    locs = payload.get("locators")
    assert isinstance(locs, dict)
    items = locs.get("items")
    assert isinstance(items, list) and items
    first = items[0]
    assert isinstance(first, dict)
    center = first.get("center")
    assert isinstance(center, dict)
    assert isinstance(center.get("x"), (int, float))
    assert isinstance(center.get("y"), (int, float))
