from __future__ import annotations


def test_list_tabs_filters_to_session_by_default(monkeypatch) -> None:  # noqa: ANN001
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.tools import list_tabs
    from mcp_servers.browser.session import session_manager

    monkeypatch.setattr(
        session_manager,
        "list_tabs",
        lambda _cfg: [
            {"id": "t1", "url": "https://a.example", "title": "A", "current": False},
            {"id": "t2", "url": "https://b.example", "title": "B", "current": True},
        ],
    )
    monkeypatch.setattr(session_manager, "get_session_tab_ids", lambda: {"t2"})
    monkeypatch.setattr(session_manager, "_session_tab_id", "t2", raising=False)

    cfg = BrowserConfig.from_env()
    res = list_tabs(cfg)

    tabs = res.get("tabs")
    assert isinstance(tabs, list)
    assert len(tabs) == 1
    assert tabs[0].get("id") == "t2"
    assert res.get("scope") == "session"


def test_list_tabs_include_all(monkeypatch) -> None:  # noqa: ANN001
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.tools import list_tabs
    from mcp_servers.browser.session import session_manager

    monkeypatch.setattr(
        session_manager,
        "list_tabs",
        lambda _cfg: [
            {"id": "t1", "url": "https://a.example", "title": "A", "current": False},
            {"id": "t2", "url": "https://b.example", "title": "B", "current": True},
        ],
    )
    monkeypatch.setattr(session_manager, "get_session_tab_ids", lambda: {"t2"})
    monkeypatch.setattr(session_manager, "_session_tab_id", "t2", raising=False)

    cfg = BrowserConfig.from_env()
    res = list_tabs(cfg, include_all=True)

    tabs = res.get("tabs")
    assert isinstance(tabs, list)
    assert len(tabs) == 2
    assert res.get("scope") == "all"
