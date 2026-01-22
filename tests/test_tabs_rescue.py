from __future__ import annotations

import pytest


def test_tabs_rescue_creates_fresh_tab_and_closes_old(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.handlers import unified as unified_handlers
    from mcp_servers.browser.session import session_manager

    cfg = BrowserConfig.from_env()

    # Seed a current session tab.
    session_manager._session_tab_id = "tab_old"  # noqa: SLF001

    calls: list[tuple[str, object]] = []

    def fake_best_effort_current_url(_cfg: BrowserConfig) -> str | None:  # noqa: ARG001
        return "https://example.test/old"

    monkeypatch.setattr(unified_handlers, "_best_effort_current_url", fake_best_effort_current_url)

    def fake_new_tab(_cfg: BrowserConfig, url: str = "about:blank") -> str:  # noqa: ARG001
        calls.append(("new_tab", url))
        session_manager._session_tab_id = "tab_new"  # noqa: SLF001
        return "tab_new"

    def fake_close_tab(_cfg: BrowserConfig, tab_id: str | None = None) -> bool:  # noqa: ARG001
        calls.append(("close_tab", tab_id))
        return True

    monkeypatch.setattr(session_manager, "new_tab", fake_new_tab)
    monkeypatch.setattr(session_manager, "close_tab", fake_close_tab)

    res = unified_handlers.handle_tabs(cfg, launcher=None, args={"action": "rescue", "close_old": True})
    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("action") == "rescue"

    payload = res.data.get("result")
    assert isinstance(payload, dict)
    assert payload.get("success") is True
    assert payload.get("mode") == "rescue"
    assert payload.get("closedOld") is True

    before = payload.get("before")
    after = payload.get("after")
    assert isinstance(before, dict)
    assert isinstance(after, dict)
    assert before.get("sessionTabId") == "tab_old"
    assert after.get("sessionTabId") == "tab_new"
    assert after.get("url") == "https://example.test/old"

    assert calls == [("new_tab", "https://example.test/old"), ("close_tab", "tab_old")]
