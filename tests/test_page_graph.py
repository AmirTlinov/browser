from __future__ import annotations

import pytest


def test_page_graph_returns_stored_nav_graph(monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ARG001
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.session import session_manager
    from mcp_servers.browser.tools.page import graph as graph_tool

    session_manager.recover_reset()
    session_manager._session_tab_id = "tab1"

    summary = session_manager.note_nav_graph_observation(
        "tab1",
        url="https://example.com/a?token=1#frag",
        title="A",
        link_edges=[{"ref": "aff:1", "label": "Docs", "to": "https://example.com/docs?x=1"}],
    )
    assert isinstance(summary, dict)

    cfg = BrowserConfig.from_env()
    res = graph_tool.get_page_graph(cfg, limit=20)
    assert isinstance(res, dict)
    g = res.get("graph")
    assert isinstance(g, dict)
    assert res.get("sessionTabId") == "tab1"

    nodes = g.get("nodes")
    edges = g.get("edges")
    assert isinstance(nodes, list) and nodes
    assert isinstance(edges, list) and edges

    # URLs should be redacted (query/fragment dropped)
    assert any(isinstance(n, dict) and n.get("url") == "https://example.com/a" for n in nodes)
    assert any(isinstance(n, dict) and n.get("url") == "https://example.com/docs" for n in nodes)

    # Link edge should be present
    link_edges = [e for e in edges if isinstance(e, dict) and e.get("kind") == "link"]
    assert link_edges
    assert link_edges[0].get("ref") == "aff:1"


def test_page_graph_seeds_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.session import session_manager
    from mcp_servers.browser.tools.page import graph as graph_tool

    session_manager.recover_reset()
    session_manager._session_tab_id = "tab1"

    monkeypatch.setattr(
        graph_tool,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/", "title": "Home", "readyState": "complete"}},
    )

    cfg = BrowserConfig.from_env()
    res = graph_tool.get_page_graph(cfg, limit=10)
    assert isinstance(res, dict)
    g = res.get("graph")
    assert isinstance(g, dict)
    nodes = g.get("nodes")
    assert isinstance(nodes, list) and nodes
    assert any(isinstance(n, dict) and n.get("url") == "https://example.com/" for n in nodes)
